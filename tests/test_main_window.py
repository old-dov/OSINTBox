import time

from osintbox.normalizers import Finding
from osintbox.ui.main_window import MainWindow

# Note : pas de test sur _on_run_clicked ici -- il ouvre des QMessageBox modales (warning/
# question) qui bloqueraient indefiniment en pytest sans utilisateur pour cliquer. La logique
# qu'il orchestre (validate_target, ScanWorker) est deja couverte par test_validators.py et
# test_worker.py ; ce test se limite a la construction de la fenetre elle-meme.


def test_window_builds_and_loads_catalog_checkboxes(qapp):
    window = MainWindow()
    assert window.windowTitle() == "OSINTBox"
    assert set(window.tool_checkboxes) == {"sherlock", "maigret", "holehe", "theharvester"}
    assert window.results_table.columnCount() == 5
    assert not window.export_button.isEnabled()
    assert not window.stop_button.isEnabled()
    assert "00:00" in window.progress_label.text()
    assert "0 / 0" in window.progress_label.text()


def test_language_switch_updates_visible_labels_and_persists(qapp):
    from PySide6.QtCore import QSettings

    settings = QSettings("OSINTBox", "OSINTBox")
    previous = settings.value("language", "fr")
    try:
        window = MainWindow()
        window.language_combo.setCurrentIndex(0)
        window.language_combo.setCurrentIndex(1)
        assert window.run_button.text() == "Run"
        assert window.results_table.horizontalHeaderItem(0).text() == "Category"
        assert QSettings("OSINTBox", "OSINTBox").value("language") == "en"
        reopened_window = MainWindow()
        assert reopened_window.run_button.text() == "Run"
        window.language_combo.setCurrentIndex(0)
        assert window.run_button.text() == "Lancer"
        assert window.results_table.horizontalHeaderItem(0).text() == "Categorie"
    finally:
        settings.setValue("language", previous)


def _units_done(text: str) -> str:
    # Ignore le minutage et le libelle traduit, qui depend de la preference utilisateur.
    return " ".join(text.split("-- ", 1)[1].split()[:3])


def test_progress_counter_advances_once_per_terminal_status(qapp):
    window = MainWindow()
    window._total_units = 2
    window._update_progress_label()
    window._on_job_status_changed("sherlock", "queued")
    window._on_job_status_changed("sherlock", "running")
    assert _units_done(window.progress_label.text()) == "0 / 2"
    window._on_job_status_changed("maigret", "retrying")  # tentative en cours, pas final
    assert _units_done(window.progress_label.text()) == "0 / 2"
    window._on_job_status_changed("sherlock", "done")
    assert _units_done(window.progress_label.text()) == "1 / 2"
    window._on_job_status_changed("maigret", "rate_limited")  # statut final, compte desormais
    assert _units_done(window.progress_label.text()) == "2 / 2"
    window._on_job_status_changed("maigret", "rate_limited")  # deja compte, pas de double-compte
    assert _units_done(window.progress_label.text()) == "2 / 2"


def test_elapsed_timer_starts_on_run_and_stops_on_finish(qapp, monkeypatch):
    window = MainWindow()
    assert not window._elapsed_timer.isActive()

    monkeypatch.setattr("osintbox.ui.main_window.time.monotonic", lambda: 100.0)
    window._total_units = 1
    window._scan_start_time = time.monotonic()
    window._update_progress_label()
    window._elapsed_timer.start()
    assert window._elapsed_timer.isActive()

    monkeypatch.setattr("osintbox.ui.main_window.time.monotonic", lambda: 165.0)  # +65s
    window._update_progress_label()
    assert "01:05" in window.progress_label.text()

    window._on_finished_all([], False)
    assert not window._elapsed_timer.isActive()


def test_partial_findings_from_rate_limited_job_appear_in_results_table(qapp):
    # Bug reel : Maigret genuinement rate-limite (sur certains sites) avait quand meme trouve
    # des comptes reels, perdus avant ce correctif car seul le statut "done" les affichait.
    window = MainWindow()
    finding = Finding(source="maigret", category="username", type="social_profile", value="https://x")
    window._on_job_findings_ready("maigret", [finding])
    assert window.results_table.rowCount() == 1
    assert window.results_table.item(0, 1).text() == "maigret"


def test_username_caveat_hidden_until_a_username_finding_arrives(qapp):
    # isHidden() (pas isVisible()) : reflete le flag explicite du widget, pas l'etat de la
    # fenetre parente -- MainWindow() n'est jamais .show()e dans ces tests (voir note en tete
    # de fichier), donc isVisible() serait toujours False independamment de setVisible().
    window = MainWindow()
    assert window.username_caveat_label.isHidden()
    finding = Finding(source="holehe", category="email", type="account_exists", value="b.com")
    window._on_job_findings_ready("holehe", [finding])
    assert window.username_caveat_label.isHidden()
    username_finding = Finding(source="maigret", category="username", type="social_profile", value="https://x")
    window._on_job_findings_ready("maigret", [username_finding])
    assert not window.username_caveat_label.isHidden()


def test_url_value_is_styled_as_a_link(qapp):
    window = MainWindow()
    finding = Finding(source="sherlock", category="username", type="social_profile", value="https://github.com/torvalds")
    window._on_job_findings_ready("sherlock", [finding])
    item = window.results_table.item(0, 3)
    assert item.font().underline()
    assert item.toolTip() != ""


def test_non_url_value_is_not_styled_as_a_link(qapp):
    window = MainWindow()
    finding = Finding(source="holehe", category="email", type="account_exists", value="b.com")
    window._on_job_findings_ready("holehe", [finding])
    item = window.results_table.item(0, 3)
    assert not item.font().underline()


def test_double_click_on_url_value_opens_it(qapp, monkeypatch):
    opened = []
    monkeypatch.setattr("osintbox.ui.main_window.QDesktopServices.openUrl", lambda url: opened.append(url.toString()))
    window = MainWindow()
    finding = Finding(source="sherlock", category="username", type="social_profile", value="https://github.com/torvalds")
    window._on_job_findings_ready("sherlock", [finding])
    window._on_result_cell_double_clicked(0, 3)
    assert opened == ["https://github.com/torvalds"]


def test_double_click_on_non_url_value_does_nothing(qapp, monkeypatch):
    opened = []
    monkeypatch.setattr("osintbox.ui.main_window.QDesktopServices.openUrl", lambda url: opened.append(url.toString()))
    window = MainWindow()
    finding = Finding(source="holehe", category="email", type="account_exists", value="b.com")
    window._on_job_findings_ready("holehe", [finding])
    window._on_result_cell_double_clicked(0, 3)
    assert opened == []


def test_result_rows_stay_fully_populated_with_sorting_enabled(qapp):
    # Regression : QTableWidget re-trie apres CHAQUE setItem() quand le tri est actif. Remplir
    # une ligne colonne par colonne pendant que le tri est actif la deplace avant d'ecrire les
    # colonnes suivantes, qui atterrissent alors sur la mauvaise ligne -- bug reel trouve en
    # testant la GUI (categorie correcte, tout le reste vide sur la quasi-totalite des lignes).
    window = MainWindow()
    findings = [
        Finding(source="sherlock", category="username", type="social_profile", value=f"https://x/{i}", confidence="high")
        for i in range(20)
    ]
    window._append_result_rows(findings)

    assert window.results_table.rowCount() == 20
    seen_values = set()
    for row in range(window.results_table.rowCount()):
        category = window.results_table.item(row, 0).text()
        source = window.results_table.item(row, 1).text()
        type_ = window.results_table.item(row, 2).text()
        value = window.results_table.item(row, 3).text()
        confidence = window.results_table.item(row, 4).text()
        assert category == "username"
        assert source == "sherlock"
        assert type_ == "social_profile"
        assert value.startswith("https://x/")
        assert confidence == "high"
        seen_values.add(value)
    assert len(seen_values) == 20  # chaque ligne correspond bien a un finding distinct
