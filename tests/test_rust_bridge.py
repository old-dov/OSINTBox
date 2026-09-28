import io
import json
from pathlib import Path

from osintbox.catalog import ToolSpec
from osintbox.ui.worker import ScanWorker


SPEC = ToolSpec(id="sherlock", category="username", desc="fixture",
                command=["sherlock", "{target}"], target_type="username")


def test_rust_events_feed_existing_worker_signals(qapp, monkeypatch):
    events = [
        {"tool_id": "sherlock", "status": "queued", "findings": [], "stderr": ""},
        {"tool_id": "sherlock", "status": "running", "findings": [], "stderr": ""},
        {"tool_id": "sherlock", "status": "done", "findings": [
            {"source": "sherlock", "category": "username", "type": "social_profile",
             "value": "https://github.com/alice", "confidence": "high", "raw": {"site": "GitHub"}}
        ], "stderr": ""},
    ]
    commands = []

    class FakeProcess:
        def __init__(self, command, **_kwargs):
            commands.append(command)
            self.stdout = io.StringIO("".join(json.dumps(event) + "\n" for event in events))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def wait(self):
            return 0

    monkeypatch.setattr("osintbox.ui.worker.subprocess.Popen", FakeProcess)
    worker = ScanWorker([SPEC], "alice", False, rust_executable=Path("fake-rust.exe"))
    statuses, findings, finished = [], [], []
    worker.job_status_changed.connect(lambda tool, status: statuses.append((tool, status)))
    worker.job_findings_ready.connect(lambda tool, items: findings.append((tool, items)))
    worker.finished_all.connect(lambda items, failure: finished.append((items, failure)))

    worker.run()

    assert statuses == [("sherlock", "queued"), ("sherlock", "running"), ("sherlock", "done")]
    assert findings[0][1][0].value == "https://github.com/alice"
    assert finished[0][1] is False
    assert "--events-json" in commands[0] and "--cancel-file" in commands[0]


def test_rust_partial_findings_on_failure(qapp, monkeypatch):
    event = {"tool_id": "sherlock", "status": "rate_limited", "stderr": "429",
             "findings": [{"source": "sherlock", "category": "username", "type": "social_profile",
                           "value": "https://github.com/alice", "confidence": "high", "raw": {}}]}

    class FakeProcess:
        stdout = io.StringIO(json.dumps(event) + "\n")

        def __init__(self, *_args, **_kwargs):
            self.stdout = io.StringIO(json.dumps(event) + "\n")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def wait(self):
            return 1

    monkeypatch.setattr("osintbox.ui.worker.subprocess.Popen", FakeProcess)
    worker = ScanWorker([SPEC], "alice", False, rust_executable=Path("fake-rust.exe"))
    findings, errors, finished = [], [], []
    worker.job_findings_ready.connect(lambda tool, items: findings.extend(items))
    worker.job_error.connect(lambda tool, message: errors.append((tool, message)))
    worker.finished_all.connect(lambda items, failure: finished.append((items, failure)))

    worker.run()

    assert len(findings) == 1
    assert errors == [("sherlock", "rate_limited 429")]
    assert len(finished[0][0]) == 1 and finished[0][1] is True
