"""Execution des outils du catalogue en sous-processus, avec timeout et kill.

Adapte de PenBox (penbox/runner.py) : meme squelette Popen + timeout + hard-kill (les cas
limites Windows deja rencontres la-bas -- un process reseau qui survit a un premier kill() --
s'appliquent tout autant ici), mais la sortie a normaliser est le stdout texte du sous-processus
(ou un fichier JSON selon ToolSpec.output_mode), pas un fichier JSON systematique : les outils
OSINT tiers ne produisent pas tous une sortie structuree propre (voir normalizers.py).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from osintbox.catalog import ToolSpec
from osintbox.normalizers import Finding, normalize
from osintbox.paths import user_data_dir

# Repertoire de travail par run, quand l'outil ecrit un fichier (output_mode="json_file") --
# ex. maigret cree `reports/report_<user>_simple.json` relatif a son cwd. Un dossier dedie et
# persistant par run (pas un tempfile auto-supprime) permet d'inspecter la sortie brute d'un
# outil apres coup en cas de probleme, comme PenBox le fait avec .penbox_runs/.
RUN_ROOT = user_data_dir() / ".osintbox_runs"


class ToolNotFoundError(RuntimeError):
    pass


# Signaux textuels de rate-limit/blocage -- pas une detection parfaite (chaque outil a sa
# propre facon de le signaler), mais couvre les cas generiques ET un cas reellement observe :
# Maigret imprime `[!] Too many errors of type "Bot protection" (7.14%)` / `"Access denied"`
# sur stdout quand un site tiers commence a le bloquer, vu en testant reellement Maigret sur
# un vrai run (pas suppose depuis la doc).
_RATE_LIMIT_MARKERS = (
    # "rate limit" seul est trop generique : holehe imprime toujours la legende
    # "[+] Email used, [-] Email not used, [x] Rate limit" meme quand tout se passe bien --
    # faux positif reel rencontre en integrant holehe (Phase 5). "rate limit exceeded"/
    # "rate limited" decrivent un evenement reel, pas un libelle d'interface.
    "rate limit exceeded", "rate limited", "too many requests", "429",
    "bot protection", "access denied", "banned", "blocked", "captcha",
)


def looks_rate_limited(stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}".lower()
    return any(marker in combined for marker in _RATE_LIMIT_MARKERS)


def _hard_kill(pid: int) -> None:
    """Dernier recours si proc.kill() n'a pas suffi (cf. PenBox : un process bloque sur un
    appel reseau peut survivre a TerminateProcess pendant un temps anormalement long)."""
    if sys.platform != "win32":
        return
    try:
        subprocess.Popen(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError:
        pass


@dataclass
class RunResult:
    tool_id: str
    target: str
    status: str  # "ok" | "error" | "timeout" | "not_found" | "rate_limited"
    exit_code: int | None
    stdout: str
    stderr: str
    findings: list[Finding]


def run_tool(spec: ToolSpec, target: str, timeout: float | None = None) -> RunResult:
    """Lance l'outil et attend sa fin (synchrone) -- suffisant pour la Phase 0 (1 outil,
    CLI). Le streaming (lire stdout au fil de l'eau pour la preview du plan) viendra une fois
    plusieurs outils en jeu, pas avant : pas de complexite ajoutee sans un second cas d'usage
    reel pour la justifier."""
    executable = spec.resolve_executable()
    if executable is None:
        return RunResult(
            tool_id=spec.id, target=target, status="not_found", exit_code=None,
            stdout="", stderr=f"Executable introuvable sur le PATH: {spec.command[0]}",
            findings=[],
        )

    argv = [executable] + spec.build_argv(target)[1:]
    timeout = timeout if timeout is not None else spec.default_timeout_s

    # Certains outils impriment des caracteres hors du charset de la console Windows
    # (cp1252) -- ex. maigret imprime un coeur Unicode (U+2665) dans sa banniere de don, qui
    # plante avec UnicodeEncodeError sans ca. Meme fix que PenBox (penbox/runner.py), retrouve
    # pour la meme raison en testant maigret reellement plutot que suppose.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    run_dir: Path | None = None
    if spec.output_mode == "json_file":
        RUN_ROOT.mkdir(parents=True, exist_ok=True)
        run_dir = RUN_ROOT / f"{spec.id}_{target}_{int(time.time())}"
        run_dir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        argv,
        cwd=str(run_dir) if run_dir else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=10)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            _hard_kill(proc.pid)
            try:
                stdout, stderr = proc.communicate(timeout=10)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
                exit_code = None

    if timed_out:
        status = "timeout"
    elif exit_code == 0 or spec.nonzero_exit_ok:
        status = "ok"
    else:
        status = "error"

    findings: list[Finding] = []
    if status == "ok" and spec.output_mode == "stdout":
        findings = normalize(spec.id, stdout, target)
    elif status == "ok" and spec.output_mode == "json_file":
        json_path = run_dir / spec.output_path_template.format(target=target)
        if json_path.exists():
            try:
                raw = json.loads(json_path.read_text(encoding="utf-8"))
                findings = normalize(spec.id, raw, target)
            except json.JSONDecodeError as exc:
                status = "error"
                stderr = f"{stderr}\nFichier JSON illisible ({json_path}): {exc}"
        else:
            status = "error"
            stderr = f"{stderr}\nFichier JSON attendu introuvable: {json_path}"

    # Verifie apres coup, pas avant : un outil peut se terminer normalement (exit 0) tout en
    # ayant ete partiellement bloque par des sites tiers (observe reellement avec Maigret --
    # `Search by username torvalds returned 13 accounts` malgre des avertissements "Bot
    # protection"/"Access denied" sur une partie des sites). Les findings deja extraits sont
    # conserves (partiels, mais reels) ; c'est le statut qui change, pour que la queue sache
    # qu'un backoff est justifie avant de reessayer ou d'enchainer la cible suivante.
    if status in ("ok", "error") and looks_rate_limited(stdout, stderr):
        status = "rate_limited"

    return RunResult(
        tool_id=spec.id, target=target, status=status, exit_code=exit_code,
        stdout=stdout or "", stderr=stderr or "", findings=findings,
    )
