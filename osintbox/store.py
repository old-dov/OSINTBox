"""Stockage des resultats -- fichiers JSON par run (plan section 4 : "fichiers JSON par run
dans un premier temps, DB (SQLite) si besoin d'historique/comparaison entre scans"). PenBox est
deja passe a SQLite (penbox/store.py) mais avec un historique de runs a comparer/filtrer dans
une UI -- pas encore un besoin ici pour un CLI qui affiche puis ecrit un fichier."""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from dataclasses import asdict
from pathlib import Path

from osintbox.normalizers import USERNAME_MATCH_CAVEAT, Finding
from osintbox.paths import user_data_dir
from osintbox.runner import RunResult

RESULTS_DIR = user_data_dir() / "results"

_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_slug(value: str) -> str:
    return _UNSAFE_CHARS_RE.sub("_", value)[:80]


def save_run(result: RunResult) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"{_safe_slug(result.target)}_{result.tool_id}_{stamp}.json"

    payload = {
        "tool_id": result.tool_id,
        "target": result.target,
        "status": result.status,
        "exit_code": result.exit_code,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "findings": [asdict(f) for f in result.findings],
    }
    if any(f.category == "username" for f in result.findings):
        payload["note"] = USERNAME_MATCH_CAVEAT
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_consolidated_report(target: str, findings: list[Finding]) -> tuple[Path, Path]:
    """Export final consolide de tous les findings d'un run (plan section 2.5 : 'export final
    consolide (JSON/CSV/rapport) une fois les modules termines'), en plus des fichiers par
    outil deja ecrits par save_run(). Un fichier par format -- JSON pour la fidelite complete
    (raw inclus), CSV pour l'ouverture dans un tableur (raw serialise en JSON dans une colonne,
    plus simple qu'une colonne par cle possible qui varie par outil)."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _safe_slug(target)

    json_path = RESULTS_DIR / f"{slug}_report_{stamp}.json"
    json_payload = {
        "target": target,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "finding_count": len(findings),
        "findings": [asdict(f) for f in findings],
    }
    if any(f.category == "username" for f in findings):
        json_payload["note"] = USERNAME_MATCH_CAVEAT
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = RESULTS_DIR / f"{slug}_report_{stamp}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "category", "type", "value", "confidence", "raw"])
        for finding in findings:
            writer.writerow([
                finding.source, finding.category, finding.type, finding.value,
                finding.confidence, json.dumps(finding.raw, ensure_ascii=False),
            ])

    return json_path, csv_path
