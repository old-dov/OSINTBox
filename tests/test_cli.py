from pathlib import Path

from osintbox.cli import _StreamingReporter
from osintbox.normalizers import Finding
from osintbox.queue import Job
from osintbox.runner import RunResult


def _job(tool_id: str, status: str, findings: list[Finding] | None = None, stderr: str = "") -> Job:
    job = Job(tool_id=tool_id, target="x", status=status)
    if status != "queued" and status != "running":
        job.result = RunResult(
            tool_id=tool_id, target="x",
            status="ok" if status == "done" else status,
            exit_code=0, stdout="", stderr=stderr, findings=findings or [],
        )
    return job


def test_intermediate_statuses_are_not_reported_as_results(monkeypatch):
    monkeypatch.setattr("osintbox.cli.save_run", lambda result: Path("unused"))
    reporter = _StreamingReporter()
    reporter.on_status_change(_job("sherlock", "queued"))
    reporter.on_status_change(_job("sherlock", "running"))
    assert reporter.all_findings == []
    assert not reporter.any_failure


def test_done_job_streams_findings_and_saves_immediately(monkeypatch):
    saved = []
    monkeypatch.setattr("osintbox.cli.save_run", lambda result: saved.append(result) or Path("fake.json"))
    reporter = _StreamingReporter()
    finding = Finding(source="sherlock", category="username", type="social_profile", value="https://x")
    reporter.on_status_change(_job("sherlock", "done", findings=[finding]))
    assert reporter.all_findings == [finding]
    assert not reporter.any_failure
    assert len(saved) == 1


def test_failed_job_marks_failure_without_saving(monkeypatch):
    saved = []
    monkeypatch.setattr("osintbox.cli.save_run", lambda result: saved.append(result) or Path("fake.json"))
    reporter = _StreamingReporter()
    reporter.on_status_change(_job("maigret", "rate_limited", stderr="banned"))
    assert reporter.any_failure
    assert reporter.all_findings == []
    assert saved == []


def test_rate_limited_job_with_partial_findings_still_surfaces_them(monkeypatch):
    # Regression : runner.run_tool conserve les findings deja extraits avant de changer le
    # statut en "rate_limited" (ex. Maigret ayant reellement trouve des comptes tout en etant
    # partiellement bloque par certains sites tiers) -- les jeter ici serait un vrai gachis de
    # donnees reelles. Bug trouve en testant la GUI sur un cas reel (22 comptes Maigret perdus).
    saved = []
    monkeypatch.setattr("osintbox.cli.save_run", lambda result: saved.append(result) or Path("fake.json"))
    reporter = _StreamingReporter()
    finding = Finding(source="maigret", category="username", type="social_profile", value="https://x")
    reporter.on_status_change(_job("maigret", "rate_limited", findings=[finding], stderr="bot protection"))
    assert reporter.any_failure  # toujours signale comme un echec (statut final != "done")
    assert reporter.all_findings == [finding]  # mais les findings reels ne sont pas perdus
    assert len(saved) == 1


def test_summary_groups_accumulated_findings_by_category(monkeypatch, capsys):
    monkeypatch.setattr("osintbox.cli.save_run", lambda result: Path("unused"))
    reporter = _StreamingReporter()
    reporter.all_findings = [
        Finding(source="sherlock", category="username", type="social_profile", value="a"),
        Finding(source="maigret", category="username", type="social_profile", value="b"),
    ]
    reporter.print_summary()
    out = capsys.readouterr().out
    assert "username (2)" in out
    assert "a" in out and "b" in out


def test_summary_shows_caveat_when_username_findings_present(capsys):
    from osintbox.normalizers import USERNAME_MATCH_CAVEAT

    reporter = _StreamingReporter()
    reporter.all_findings = [Finding(source="sherlock", category="username", type="social_profile", value="a")]
    reporter.print_summary()
    assert USERNAME_MATCH_CAVEAT in capsys.readouterr().out


def test_summary_no_caveat_without_username_findings(capsys):
    from osintbox.normalizers import USERNAME_MATCH_CAVEAT

    reporter = _StreamingReporter()
    reporter.all_findings = [Finding(source="holehe", category="email", type="account_exists", value="b.com")]
    reporter.print_summary()
    assert USERNAME_MATCH_CAVEAT not in capsys.readouterr().out


def test_summary_silent_when_no_findings(capsys):
    reporter = _StreamingReporter()
    reporter.print_summary()
    assert capsys.readouterr().out == ""


# ── report_dorking ───────────────────────────────────────────────────────────


def test_report_dorking_streams_findings_and_saves(monkeypatch):
    saved = []
    monkeypatch.setattr("osintbox.cli.save_run", lambda result: saved.append(result) or Path("fake.json"))
    reporter = _StreamingReporter()
    finding = Finding(source="dorking", category="dorking", type="exposed_pdf", value="https://x/y.pdf")
    reporter.report_dorking("example.com", [finding], [])
    assert reporter.all_findings == [finding]
    assert not reporter.any_failure
    assert len(saved) == 1


def test_report_dorking_marks_failure_when_errors_and_no_findings(monkeypatch):
    monkeypatch.setattr("osintbox.cli.save_run", lambda result: Path("fake.json"))
    reporter = _StreamingReporter()
    reporter.report_dorking("example.com", [], ["quota depasse"])
    assert reporter.any_failure


def test_report_dorking_errors_alongside_findings_do_not_fail_the_run(monkeypatch):
    monkeypatch.setattr("osintbox.cli.save_run", lambda result: Path("fake.json"))
    reporter = _StreamingReporter()
    finding = Finding(source="dorking", category="dorking", type="exposed_pdf", value="https://x/y.pdf")
    reporter.report_dorking("example.com", [finding], ["une erreur partielle"])
    assert not reporter.any_failure
    assert reporter.all_findings == [finding]
