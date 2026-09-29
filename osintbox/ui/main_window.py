"""Fenetre principale (MVP desktop, decide avec l'utilisateur -- pas de parite complete avec
PenBox : pas d'historique de runs, pas de dialogue de diff, pas d'export SSH/vault, aucun sens
pour un outil OSINT local). Reutilise le backend CLI tel quel (catalog/queue/normalizers/store)
-- cette couche ne fait qu'orchestrer des widgets et le ScanWorker en arriere-plan."""

from __future__ import annotations

import time

from PySide6.QtCore import QSettings, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon
from pathlib import Path
import sys
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Statuts de job vraiment finaux, chacun emis AU PLUS UNE fois par job (queue.run_queue emet
# "retrying" -- pas "rate_limited" -- pour une tentative en cours qui va etre retentee, donc
# plus d'ambiguite ici depuis ce correctif : compter un de ces statuts comme "job termine" est
# fiable, jamais en double).
_PROGRESS_TERMINAL_STATUSES = frozenset({"done", "failed", "timeout", "not_found", "rate_limited"})
_VALUE_COLUMN = 3  # colonne "Valeur" dans results_table (voir setHorizontalHeaderLabels)

from osintbox.catalog import CatalogError, ToolSpec, load_catalog
from osintbox.consent import AUTHORIZATION_PROMPT
from osintbox.normalizers import USERNAME_MATCH_CAVEAT, Finding
from osintbox.store import save_consolidated_report
from osintbox.ui.worker import ScanWorker
from osintbox.ui.card_theme import GeometryMark
from osintbox.validators import validate_target, validate_territory


_ENGLISH = {
    "RECON / ANALYSE": "RECON / ANALYSIS",
    "Cible :": "Target:", "Territoire :": "Territory:",
    "pseudo (sherlock/maigret/holehe) ou domaine (dorking)": "username (sherlock/maigret/holehe) or domain (dorking)",
    "optionnel, ex: fr (maigret uniquement)": "optional, e.g. fr (maigret only)",
    "dorking (domaine)": "dorking (domain)",
    "Lancer": "Run", "Arreter": "Stop", "Exporter (JSON + CSV)": "Export (JSON + CSV)",
    "Statut :": "Status:", "Resultats :": "Results:",
    "Categorie": "Category", "Source": "Source", "Type": "Type", "Valeur": "Value", "Confiance": "Confidence",
    "Double-cliquer pour ouvrir dans le navigateur": "Double-click to open in browser",
    USERNAME_MATCH_CAVEAT: "A 'high' confidence username match (Sherlock/Maigret) means the username exists on that site, not that the account belongs to the target. Verify the photo, bio and activity before drawing a conclusion.",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OSINTBox")
        self.resize(900, 600)
        self._settings = QSettings("OSINTBox", "OSINTBox")
        self._language = str(self._settings.value("language", "fr"))

        self._worker: ScanWorker | None = None
        self._all_findings: list[Finding] = []
        self._current_target = ""
        self._counted_tool_ids: set[str] = set()
        self._dorking_counted = False
        self._stop_requested = False
        self._total_units = 0
        self._done_units = 0
        self._scan_start_time: float | None = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_progress_label)

        try:
            self._catalog: dict[str, ToolSpec] = load_catalog()
        except CatalogError as exc:
            self._catalog = {}
            QMessageBox.critical(self, "Catalogue invalide", str(exc))

        self._build_ui()
        self._apply_language()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        header = QFrame()
        header.setObjectName("brandHeader")
        header_layout = QHBoxLayout(header)
        icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "pictures" / "osint_box.ico"
        if icon_path.exists():
            logo = QLabel()
            logo.setPixmap(QIcon(str(icon_path)).pixmap(56, 56))
            header_layout.addWidget(logo)
        heading = QVBoxLayout()
        title = QLabel("OSINTBox")
        title.setObjectName("brandTitle")
        subtitle = QLabel("RECON / ANALYSE")
        subtitle.setObjectName("brandSubtitle")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header_layout.addLayout(heading)
        header_layout.addStretch()
        self.language_combo = QComboBox()
        self.language_combo.addItem("Français", "fr")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(1 if self._language == "en" else 0)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        header_layout.addWidget(self.language_combo)
        header_layout.addWidget(GeometryMark())
        layout.addWidget(header)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Cible :"))
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("pseudo (sherlock/maigret/holehe) ou domaine (dorking)")
        target_row.addWidget(self.target_input)
        target_row.addWidget(QLabel("Territoire :"))
        self.territory_input = QLineEdit()
        self.territory_input.setPlaceholderText("optionnel, ex: fr (maigret uniquement)")
        self.territory_input.setMaximumWidth(160)
        target_row.addWidget(self.territory_input)
        layout.addLayout(target_row)

        tools_row = QHBoxLayout()
        self.tool_checkboxes: dict[str, QCheckBox] = {}
        for tool_id, spec in sorted(self._catalog.items()):
            checkbox = QCheckBox(f"{tool_id} ({spec.target_type})")
            self.tool_checkboxes[tool_id] = checkbox
            tools_row.addWidget(checkbox)
        self.dork_checkbox = QCheckBox("dorking (domaine)")
        tools_row.addWidget(self.dork_checkbox)
        tools_row.addStretch()
        layout.addLayout(tools_row)

        run_row = QHBoxLayout()
        self.run_button = QPushButton("Lancer")
        self.run_button.clicked.connect(self._on_run_clicked)
        run_row.addWidget(self.run_button)
        self.stop_button = QPushButton("Arreter")
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.stop_button.setEnabled(False)
        run_row.addWidget(self.stop_button)
        self.export_button = QPushButton("Exporter (JSON + CSV)")
        self.export_button.clicked.connect(self._on_export_clicked)
        self.export_button.setEnabled(False)
        run_row.addWidget(self.export_button)
        run_row.addStretch()
        layout.addLayout(run_row)

        self.progress_label = QLabel()
        layout.addWidget(self.progress_label)
        self._update_progress_label()

        layout.addWidget(QLabel("Statut :"))
        self.status_list = QListWidget()
        self.status_list.setMaximumHeight(120)
        layout.addWidget(self.status_list)

        layout.addWidget(QLabel("Resultats :"))
        self.username_caveat_label = QLabel(USERNAME_MATCH_CAVEAT)
        self.username_caveat_label.setWordWrap(True)
        self.username_caveat_label.setStyleSheet("color: gray; font-style: italic;")
        self.username_caveat_label.setVisible(False)
        layout.addWidget(self.username_caveat_label)
        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(["Categorie", "Source", "Type", "Valeur", "Confiance"])
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.results_table.setSortingEnabled(True)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.cellDoubleClicked.connect(self._on_result_cell_double_clicked)
        layout.addWidget(self.results_table)

    def _on_language_changed(self) -> None:
        self._language = self.language_combo.currentData()
        self._settings.setValue("language", self._language)
        self._apply_language()

    def _say(self, french: str, english: str) -> str:
        return english if self._language == "en" else french

    def _apply_language(self) -> None:
        reverse = {english: french for french, english in _ENGLISH.items()}
        for widget in self.findChildren(QWidget):
            if not isinstance(widget, (QLabel, QPushButton, QCheckBox)):
                continue
            source = reverse.get(widget.text(), widget.text())
            widget.setText(_ENGLISH.get(source, source) if self._language == "en" else source)
        for widget in self.findChildren(QLineEdit):
            source = reverse.get(widget.placeholderText(), widget.placeholderText())
            widget.setPlaceholderText(_ENGLISH.get(source, source) if self._language == "en" else source)
        self.results_table.setHorizontalHeaderLabels([
            _ENGLISH.get(label, label) if self._language == "en" else label
            for label in ("Categorie", "Source", "Type", "Valeur", "Confiance")
        ])
        self._update_progress_label()

    # ── actions ──────────────────────────────────────────────────────────────

    def _on_run_clicked(self) -> None:
        target = self.target_input.text().strip()
        if not target:
            QMessageBox.warning(self, self._say("Cible manquante", "Missing target"), self._say("Entrez une cible avant de lancer.", "Enter a target before starting."))
            return

        selected_ids = [tool_id for tool_id, cb in self.tool_checkboxes.items() if cb.isChecked()]
        do_dork = self.dork_checkbox.isChecked()
        if not selected_ids and not do_dork:
            QMessageBox.warning(self, self._say("Rien a lancer", "Nothing selected"), self._say("Cochez au moins un outil ou le dorking.", "Select at least one tool or dorking."))
            return

        specs = [self._catalog[tool_id] for tool_id in selected_ids]
        for spec in specs:
            ok, error = validate_target(target, spec.target_type)
            if not ok:
                QMessageBox.critical(self, self._say("Cible invalide", "Invalid target"), f"{spec.id} ({spec.target_type}) : {error}")
                return
        if do_dork:
            ok, error = validate_target(target, "domain")
            if not ok:
                QMessageBox.critical(self, self._say("Cible invalide pour le dorking", "Invalid dorking target"), error)
                return

        territory = self.territory_input.text().strip()
        unsupported_territory_tools: list[str] = []
        if territory:
            ok, error = validate_territory(territory)
            if not ok:
                QMessageBox.critical(self, self._say("Territoire invalide", "Invalid territory"), error)
                return
            unsupported_territory_tools = [spec.id for spec in specs if not spec.territory_flag]
            specs = [spec.with_territory(territory) for spec in specs]

        if not self._confirm_authorization(target):
            return

        self._current_target = target
        self._all_findings = []
        self._counted_tool_ids = set()
        self._dorking_counted = False
        self._stop_requested = False
        self.results_table.setRowCount(0)
        self.username_caveat_label.setVisible(False)
        self.status_list.clear()
        for tool_id in unsupported_territory_tools:
            self.status_list.addItem(QListWidgetItem(self._say(f"[~] {tool_id} ne supporte pas le territoire, ignore pour cet outil.", f"[~] {tool_id} does not support territory; ignored for this tool.")))
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.export_button.setEnabled(False)

        self._total_units = len(specs) + (1 if do_dork else 0)
        self._done_units = 0
        self._scan_start_time = time.monotonic()
        self._update_progress_label()
        self._elapsed_timer.start()

        self._worker = ScanWorker(specs, target, do_dork)
        self._worker.job_status_changed.connect(self._on_job_status_changed)
        self._worker.job_findings_ready.connect(self._on_job_findings_ready)
        self._worker.job_error.connect(self._on_job_error)
        self._worker.dorking_status.connect(self._on_dorking_status)
        self._worker.finished_all.connect(self._on_finished_all)
        self._worker.start()

    def _confirm_authorization(self, target: str) -> bool:
        text = self._say(
            AUTHORIZATION_PROMPT.format(target=target) + "\nConfirmez-vous etre autorise a scanner cette cible ?",
            f"OSINTBox will search for: {target}\nUse it only with authorization and respect other people's privacy.\nDo you confirm you are authorized to scan this target?",
        )
        answer = QMessageBox.question(
            self, self._say("Autorisation requise", "Authorization required"), text,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _on_stop_clicked(self) -> None:
        if self._worker is not None:
            self._worker.requestInterruption()
        self._stop_requested = True
        self.stop_button.setEnabled(False)
        self.status_list.addItem(QListWidgetItem(self._say("-- arret demande (apres le job en cours) --", "-- stop requested (after current job) --")))
        self.status_list.scrollToBottom()

    def _on_export_clicked(self) -> None:
        if not self._all_findings:
            return
        json_path, csv_path = save_consolidated_report(self._current_target, self._all_findings)
        QMessageBox.information(self, self._say("Export termine", "Export complete"), f"JSON : {json_path}\nCSV : {csv_path}")

    # ── signaux du ScanWorker ────────────────────────────────────────────────

    def _on_job_status_changed(self, tool_id: str, status: str) -> None:
        self.status_list.addItem(QListWidgetItem(f"[{tool_id}] {status}"))
        self.status_list.scrollToBottom()
        if status in _PROGRESS_TERMINAL_STATUSES and tool_id not in self._counted_tool_ids:
            self._counted_tool_ids.add(tool_id)
            self._advance_progress()

    def _on_job_findings_ready(self, tool_id: str, findings: list[Finding]) -> None:
        self._all_findings.extend(findings)
        self._append_result_rows(findings)
        if any(f.category == "username" for f in findings):
            self.username_caveat_label.setVisible(True)

    def _on_job_error(self, tool_id: str, message: str) -> None:
        self.status_list.addItem(QListWidgetItem(f"[{self._say('ERREUR', 'ERROR')}] {tool_id} : {message}"))
        self.status_list.scrollToBottom()

    def _on_dorking_status(self, message: str) -> None:
        self.status_list.addItem(QListWidgetItem(f"[dorking] {message}"))
        self.status_list.scrollToBottom()
        is_terminal = message == "done" or message.startswith("error:") or message.startswith("errors:")
        if is_terminal and not self._dorking_counted:
            self._dorking_counted = True
            self._advance_progress()

    def _advance_progress(self) -> None:
        self._done_units += 1
        self._update_progress_label()

    def _update_progress_label(self) -> None:
        elapsed = 0.0 if self._scan_start_time is None else time.monotonic() - self._scan_start_time
        minutes, seconds = divmod(int(elapsed), 60)
        if self._language == "en":
            self.progress_label.setText(f"Elapsed: {minutes:02d}:{seconds:02d} -- {self._done_units} / {self._total_units} tool(s) completed")
        else:
            self.progress_label.setText(f"Temps ecoule : {minutes:02d}:{seconds:02d} -- {self._done_units} / {self._total_units} outil(s) termine(s)")

    def _on_finished_all(self, all_findings: list[Finding], any_failure: bool) -> None:
        self._elapsed_timer.stop()
        self._update_progress_label()
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.export_button.setEnabled(bool(self._all_findings))
        if self._stop_requested:
            self.status_list.addItem(QListWidgetItem(self._say(f"-- arrete : {len(self._all_findings)} resultat(s) avant arret --", f"-- stopped: {len(self._all_findings)} result(s) before stop --")))
        else:
            self.status_list.addItem(QListWidgetItem(self._say(f"-- termine : {len(self._all_findings)} resultat(s) --", f"-- finished: {len(self._all_findings)} result(s) --")))
        self.status_list.scrollToBottom()

    def _append_result_rows(self, findings: list[Finding]) -> None:
        """Qt re-trie la table apres CHAQUE setItem() quand le tri est actif -- remplir une
        ligne colonne par colonne pendant que le tri est actif la fait deplacer avant que les
        colonnes suivantes ne soient ecrites, et elles atterrissent alors sur la mauvaise ligne
        (categorie correcte car ecrite en premier, tout le reste vide/mélangé -- bug reel vu en
        testant la GUI). Fix : tri desactive pendant le remplissage, reactive une fois fini."""
        self.results_table.setSortingEnabled(False)
        for finding in findings:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            values = [finding.category, finding.source, finding.type, finding.value, finding.confidence]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == _VALUE_COLUMN and value.startswith(("http://", "https://")):
                    item.setForeground(QColor("#3391ff"))
                    font = item.font()
                    font.setUnderline(True)
                    item.setFont(font)
                    item.setToolTip(self._say("Double-cliquer pour ouvrir dans le navigateur", "Double-click to open in browser"))
                self.results_table.setItem(row, col, item)
        self.results_table.setSortingEnabled(True)

    def _on_result_cell_double_clicked(self, row: int, _column: int) -> None:
        item = self.results_table.item(row, _VALUE_COLUMN)
        if item is None:
            return
        value = item.text()
        if value.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(value))
