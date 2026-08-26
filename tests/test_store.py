import csv
import json

from osintbox.normalizers import USERNAME_MATCH_CAVEAT, Finding
from osintbox.runner import RunResult
from osintbox.store import save_consolidated_report, save_run


def test_save_run_writes_expected_json(tmp_path, monkeypatch):
    monkeypatch.setattr("osintbox.store.RESULTS_DIR", tmp_path)
    finding = Finding(source="sherlock", category="username", type="social_profile", value="https://x")
    result = RunResult(tool_id="sherlock", target="torvalds", status="ok", exit_code=0, stdout="", stderr="", findings=[finding])

    path = save_run(result)

    assert path.parent == tmp_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["tool_id"] == "sherlock"
    assert payload["target"] == "torvalds"
    assert payload["findings"][0]["value"] == "https://x"
    assert payload["note"] == USERNAME_MATCH_CAVEAT


def test_save_run_no_caveat_note_without_username_findings(tmp_path, monkeypatch):
    monkeypatch.setattr("osintbox.store.RESULTS_DIR", tmp_path)
    finding = Finding(source="holehe", category="email", type="account_exists", value="b.com")
    result = RunResult(tool_id="holehe", target="a@b.com", status="ok", exit_code=0, stdout="", stderr="", findings=[finding])

    path = save_run(result)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "note" not in payload


def test_save_consolidated_report_writes_json_and_csv(tmp_path, monkeypatch):
    monkeypatch.setattr("osintbox.store.RESULTS_DIR", tmp_path)
    findings = [
        Finding(source="sherlock", category="username", type="social_profile", value="https://a", raw={"site": "A"}),
        Finding(source="holehe", category="email", type="account_exists", value="b.com", confidence="high"),
    ]

    json_path, csv_path = save_consolidated_report("torvalds", findings)

    assert json_path.parent == tmp_path and csv_path.parent == tmp_path
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["target"] == "torvalds"
    assert payload["finding_count"] == 2
    assert len(payload["findings"]) == 2
    assert payload["note"] == USERNAME_MATCH_CAVEAT

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["source"] == "sherlock"
    assert json.loads(rows[0]["raw"]) == {"site": "A"}
    assert rows[1]["value"] == "b.com"


def test_save_consolidated_report_empty_findings_still_writes_files(tmp_path, monkeypatch):
    monkeypatch.setattr("osintbox.store.RESULTS_DIR", tmp_path)
    json_path, csv_path = save_consolidated_report("torvalds", [])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["finding_count"] == 0
    assert "note" not in payload
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows == []
