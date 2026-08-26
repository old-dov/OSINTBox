"""Emplacement des donnees utilisateur (resultats, runs bruts, config locale) -- distinct des
ressources bundlees en lecture seule (catalog.yaml, voir catalog.py). En script, relatif a la
racine du projet (comportement historique, inchange). En exe fige (PyInstaller --onefile) :
%LOCALAPPDATA%\\OSINTBox -- necessaire pour deux raisons : un exe installe dans Program Files
n'a generalement pas le droit d'ecriture a cote de lui-meme (UAC), et sys._MEIPASS est un
dossier temporaire nettoye a la fermeture du process, inutilisable pour des donnees censees
survivre a un run (voir runner.RUN_ROOT : "permet d'inspecter la sortie brute d'un outil apres
coup")."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def user_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OSINTBox"
    else:
        base = Path(__file__).resolve().parent.parent
    base.mkdir(parents=True, exist_ok=True)
    return base
