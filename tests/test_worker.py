from osintbox.catalog import ToolSpec
from osintbox.config import ConfigError
from osintbox.normalizers import Finding
from osintbox.queue import Job
from osintbox.runner import RunResult
from osintbox.search_providers import SearchResult
from osintbox.ui.worker import ScanWorker

SPEC = ToolSpec(id="sherlock", category="username", desc="d", command=["sherlock", "{target}"], target_type="username")


def _fake_run_queue(jobs_to_emit):
    def _run(catalog, jobs_spec, *, on_status_change=None, **kwargs):
        for job in jobs_to_emit:
            on_status_change(job)
        return jobs_to_emit
    return _run


def test_done_job_emits_status_and_findings(qapp, monkeypatch):
    finding = Finding(source="sherlock", category="username", type="social_profile", value="https://x")
    job = Job(
        tool_id="sherlock", target="alice", status="done",
        result=RunResult(tool_id="sherlock", target="alice", status="ok", exit_code=0, stdout="", stderr="", findings=[finding]),
    )
    monkeypatch.setattr("osintbox.ui.worker.run_queue", _fake_run_queue([job]))

    worker = ScanWorker([SPEC], "alice", False)
    statuses, findings_emitted, finished = [], [], []
    worker.job_status_changed.connect(lambda t, s: statuses.append((t, s)))
    worker.job_findings_ready.connect(lambda t, f: findings_emitted.append((t, f)))
    worker.finished_all.connect(lambda f, fail: finished.append((f, fail)))

    worker.run()

    assert statuses == [("sherlock", "done")]
    assert findings_emitted == [("sherlock", [finding])]
    assert finished == [([finding], False)]


def test_failed_job_emits_error_and_marks_failure(qapp, monkeypatch):
    job = Job(
        tool_id="sherlock", target="alice", status="timeout",
        result=RunResult(tool_id="sherlock", target="alice", status="timeout", exit_code=None, stdout="", stderr="boom", findings=[]),
    )
    monkeypatch.setattr("osintbox.ui.worker.run_queue", _fake_run_queue([job]))

    worker = ScanWorker([SPEC], "alice", False)
    errors, finished = [], []
    worker.job_error.connect(lambda t, m: errors.append((t, m)))
    worker.finished_all.connect(lambda f, fail: finished.append((f, fail)))

    worker.run()

    assert errors == [("sherlock", "timeout boom")]
    assert finished == [([], True)]


def test_dorking_only_no_tool_specs(qapp, monkeypatch):
    monkeypatch.setattr("osintbox.ui.worker.load_config", lambda: {"google_cse": {"api_key": "k", "cx": "c"}})
    monkeypatch.setattr("osintbox.ui.worker.get_google_cse_credentials", lambda config: ("k", "c"))
    monkeypatch.setattr(
        "osintbox.ui.worker.run_dorking",
        lambda target, api_key, cx, *, search_fn, should_cancel=None: (
            [Finding(source="dorking", category="dorking", type="exposed_pdf", value="https://x/y.pdf")], [],
        ),
    )

    worker = ScanWorker([], "example.com", True)
    findings_emitted, dorking_statuses, finished = [], [], []
    worker.job_findings_ready.connect(lambda t, f: findings_emitted.append((t, f)))
    worker.dorking_status.connect(dorking_statuses.append)
    worker.finished_all.connect(lambda f, fail: finished.append((f, fail)))

    worker.run()

    assert findings_emitted[0][0] == "dorking"
    assert dorking_statuses == ["running", "done"]
    assert finished[0][1] is False


def test_dorking_missing_config_marks_failure_without_crashing(qapp, monkeypatch):
    def _raise_config_error():
        raise ConfigError("osintbox.local.yaml introuvable")

    monkeypatch.setattr("osintbox.ui.worker.load_config", _raise_config_error)

    worker = ScanWorker([], "example.com", True)
    dorking_statuses, finished = [], []
    worker.dorking_status.connect(dorking_statuses.append)
    worker.finished_all.connect(lambda f, fail: finished.append((f, fail)))

    worker.run()

    assert dorking_statuses == ["running", "error: osintbox.local.yaml introuvable"]
    assert finished == [([], True)]


def test_rate_limited_job_with_partial_findings_still_emitted(qapp, monkeypatch):
    # Meme regression que cli.py : ne pas jeter des findings reels juste parce que le statut
    # final n'est pas "done" (voir queue.py -- "retrying" est desormais distinct de
    # "rate_limited", donc plus d'ambiguite sur le fait que ce statut soit vraiment final ici).
    finding = Finding(source="maigret", category="username", type="social_profile", value="https://x")
    job = Job(
        tool_id="maigret", target="alice", status="rate_limited",
        result=RunResult(tool_id="maigret", target="alice", status="rate_limited", exit_code=0, stdout="", stderr="bot protection", findings=[finding]),
    )
    monkeypatch.setattr("osintbox.ui.worker.run_queue", _fake_run_queue([job]))

    worker = ScanWorker([SPEC], "alice", False)
    errors, findings_emitted, finished = [], [], []
    worker.job_error.connect(lambda t, m: errors.append((t, m)))
    worker.job_findings_ready.connect(lambda t, f: findings_emitted.append((t, f)))
    worker.finished_all.connect(lambda f, fail: finished.append((f, fail)))

    worker.run()

    assert errors == [("maigret", "rate_limited bot protection")]
    assert findings_emitted == [("maigret", [finding])]
    assert finished == [([finding], True)]


def test_retrying_status_is_not_treated_as_an_error_or_final(qapp, monkeypatch):
    # "retrying" (tentative en cours) ne doit jamais declencher job_error ni job_findings_ready
    # -- seul le statut vraiment final (a la fin de _fake_run_queue) le fait. Ici on simule
    # uniquement l'emission intermediaire, sans job final, pour isoler ce comportement.
    def _fake_run_queue_with_retry(catalog, jobs_spec, *, on_status_change=None, **kwargs):
        retrying_job = Job(tool_id="sherlock", target="alice", status="retrying")
        on_status_change(retrying_job)
        return []

    monkeypatch.setattr("osintbox.ui.worker.run_queue", _fake_run_queue_with_retry)

    worker = ScanWorker([SPEC], "alice", False)
    statuses, errors, findings_emitted = [], [], []
    worker.job_status_changed.connect(lambda t, s: statuses.append((t, s)))
    worker.job_error.connect(lambda t, m: errors.append((t, m)))
    worker.job_findings_ready.connect(lambda t, f: findings_emitted.append((t, f)))

    worker.run()

    assert statuses == [("sherlock", "retrying")]
    assert errors == []
    assert findings_emitted == []


def test_interruption_after_queue_skips_dorking(qapp, monkeypatch):
    monkeypatch.setattr("osintbox.ui.worker.run_queue", _fake_run_queue([]))
    dorking_calls = []
    monkeypatch.setattr(
        "osintbox.ui.worker.run_dorking",
        lambda *a, **kw: dorking_calls.append(1) or ([], []),
    )

    worker = ScanWorker([SPEC], "alice", True)
    monkeypatch.setattr(worker, "isInterruptionRequested", lambda: True)
    finished = []
    worker.finished_all.connect(lambda f, fail: finished.append((f, fail)))

    worker.run()

    assert dorking_calls == []
    assert finished == [([], False)]


def test_dorking_rate_limit_errors_without_findings_marks_failure(qapp, monkeypatch):
    monkeypatch.setattr("osintbox.ui.worker.load_config", lambda: {})
    monkeypatch.setattr("osintbox.ui.worker.get_google_cse_credentials", lambda config: ("k", "c"))
    monkeypatch.setattr(
        "osintbox.ui.worker.run_dorking",
        lambda target, api_key, cx, *, search_fn, should_cancel=None: ([], ["quota depasse"]),
    )

    worker = ScanWorker([], "example.com", True)
    finished = []
    worker.finished_all.connect(lambda f, fail: finished.append((f, fail)))

    worker.run()

    assert finished == [([], True)]
