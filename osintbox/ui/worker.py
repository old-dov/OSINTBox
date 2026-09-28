"""Execution du scan en arriere-plan (QThread) -- run_queue() et run_dorking() font des
sleep_fn() bloquants (delai entre outils, backoff rate-limit) : les executer sur le thread
principal Qt gelerait la fenetre. Emet des signaux pour que MainWindow mette a jour l'UI sur
le thread principal (jamais de widget touche depuis ce thread directement -- regle Qt)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from osintbox.catalog import CATALOG_PATH, ToolSpec
from osintbox.config import ConfigError, get_google_cse_credentials, load_config
from osintbox.dorking import run_dorking
from osintbox.normalizers import Finding
from osintbox.queue import Job, run_queue
from osintbox.runner import RunResult
from osintbox.search_providers import google_cse_search
from osintbox.store import RESULTS_DIR


def rust_cli_path() -> Path | None:
    """Use the companion binary in packaged builds, or an explicit dev override."""
    override = os.environ.get("OSINTBOX_RUST_CLI")
    if override:
        path = Path(override)
    elif getattr(sys, "frozen", False):
        path = Path(sys.executable).with_name("osintbox-rs.exe")
    else:
        return None
    return path if path.is_file() else None


class ScanWorker(QThread):
    job_status_changed = Signal(str, str)  # tool_id, status
    job_findings_ready = Signal(str, list)  # tool_id, list[Finding]
    job_error = Signal(str, str)  # tool_id, message
    dorking_status = Signal(str)  # message libre (running/done/error: .../errors: ...)
    finished_all = Signal(list, bool)  # all findings, any_failure

    def __init__(self, specs: list[ToolSpec], target: str, do_dork: bool, parent=None,
                 rust_executable: Path | None = None) -> None:
        super().__init__(parent)
        self._specs = specs
        self._target = target
        self._do_dork = do_dork
        self._rust_executable = rust_executable or rust_cli_path()
        self._cancel_path: Path | None = None

    def requestInterruption(self) -> None:
        super().requestInterruption()
        if self._cancel_path is not None:
            try:
                self._cancel_path.touch()
            except OSError:
                pass  # the temporary directory can close as the worker finishes

    def _run_rust(self, on_status_change) -> bool:
        """Translate the Rust CLI's newline-delimited events into existing Qt signals."""
        with tempfile.TemporaryDirectory(prefix="osintbox_cancel_") as temp_dir:
            self._cancel_path = Path(temp_dir) / "cancel"
            if self.isInterruptionRequested():
                self._cancel_path.touch()
            command = [str(self._rust_executable), self._target, "--yes", "--events-json",
                       "--catalog", str(CATALOG_PATH), "--results-dir", str(RESULTS_DIR),
                       "--cancel-file", str(self._cancel_path)]
            for spec in self._specs:
                command.extend(("--tool", spec.id))
                if spec.territory_flag and spec.command[-2:-1] == [spec.territory_flag]:
                    command.extend(("--territory", spec.command[-1]))
                    break
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            try:
                with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, encoding="utf-8", errors="replace",
                                      creationflags=flags) as process:
                    assert process.stdout is not None
                    last_message = ""
                    for line in process.stdout:
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            last_message = line.strip()
                            continue
                        tool_id = event.get("tool_id", "rust")
                        status = event.get("status", "failed")
                        result = None
                        if status in {"done", "failed", "timeout", "not_found", "rate_limited"}:
                            try:
                                findings = [Finding(**item) for item in event.get("findings", [])]
                            except (TypeError, ValueError):
                                findings = []
                            result = RunResult(tool_id=tool_id, target=self._target,
                                               status="ok" if status == "done" else status,
                                               exit_code=None, stdout="", stderr=event.get("stderr", ""),
                                               findings=findings)
                        on_status_change(Job(tool_id=tool_id, target=self._target,
                                             status=status, result=result))
                    code = process.wait()
            except OSError as exc:
                self.job_error.emit("rust", str(exc))
                return True
            finally:
                self._cancel_path = None
            if code and not self.isInterruptionRequested() and last_message:
                self.job_error.emit("rust", last_message[:300])
            return code != 0 and not self.isInterruptionRequested()

    def run(self) -> None:
        all_findings: list[Finding] = []
        any_failure = False

        def on_status_change(job: Job) -> None:
            nonlocal any_failure
            self.job_status_changed.emit(job.tool_id, job.status)
            if job.status == "done":
                all_findings.extend(job.result.findings)
                self.job_findings_ready.emit(job.tool_id, job.result.findings)
            elif job.status in ("failed", "timeout", "not_found", "rate_limited"):
                any_failure = True
                extra = job.result.stderr[-300:] if job.result and job.result.stderr else ""
                self.job_error.emit(job.tool_id, f"{job.status} {extra}".strip())
                # Statut final non-"done" mais des findings reels peuvent quand meme exister
                # (runner.run_tool les conserve avant de changer le statut, ex. Maigret
                # partiellement bloque mais ayant deja trouve des comptes) -- les perdre serait
                # un vrai gachis de donnees reelles, pas juste une histoire de statut. "retrying"
                # (tentative en cours, PAS ce statut) n'entre jamais dans cette branche, donc pas
                # de risque de compter deux fois les findings d'un job qui reussit au 2e essai.
                if job.result and job.result.findings:
                    all_findings.extend(job.result.findings)
                    self.job_findings_ready.emit(job.tool_id, job.result.findings)

        if self._specs:
            if self._rust_executable:
                any_failure |= self._run_rust(on_status_change)
            else:
                jobs_spec = [(spec.id, self._target) for spec in self._specs]
                run_queue(
                    {s.id: s for s in self._specs}, jobs_spec,
                    on_status_change=on_status_change, should_cancel=self.isInterruptionRequested,
                )

        if self.isInterruptionRequested():
            self.finished_all.emit(all_findings, any_failure)
            return

        if self._do_dork:
            self.dorking_status.emit("running")
            try:
                config = load_config()
                api_key, cx = get_google_cse_credentials(config)
            except ConfigError as exc:
                self.dorking_status.emit(f"error: {exc}")
                any_failure = True
            else:
                findings, errors = run_dorking(
                    self._target, api_key, cx,
                    search_fn=google_cse_search, should_cancel=self.isInterruptionRequested,
                )
                all_findings.extend(findings)
                if findings:
                    self.job_findings_ready.emit("dorking", findings)
                if errors:
                    if not findings:
                        any_failure = True
                    self.dorking_status.emit(f"errors: {'; '.join(errors)[:300]}")
                else:
                    self.dorking_status.emit("done")

        self.finished_all.emit(all_findings, any_failure)
