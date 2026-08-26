"""Loader/validator pour osintbox/catalog.yaml — le registre des outils OSINT wrappes.

Adapte de PenBox (penbox/catalog.py), avec un changement structurel : PenBox suppose que
chaque outil est un script Python maison invoque via `python <chemin-dans-le-repo>
--flag valeur`. OSINTBox wrappe des CLI tierces (Sherlock, Maigret, parfois des binaires Go
comme amass/subfinder) qui ne sont ni forcement Python, ni dans ce depot -- `command` est donc
un gabarit d'argv libre avec un placeholder `{target}`, resolu sur le PATH au lancement plutot
que suppose etre un chemin de script local.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from osintbox.validators import TARGET_TYPES

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.yaml"

OUTPUT_MODES = {"stdout", "json_file"}


class CatalogError(ValueError):
    pass


@dataclass
class ToolSpec:
    id: str
    category: str
    desc: str
    command: list[str]
    target_type: str
    output_mode: str = "stdout"
    # Chemin du fichier JSON produit par l'outil, relatif au repertoire de travail du run
    # (voir runner.py) -- requis quand output_mode="json_file". {target} substitue.
    output_path_template: str | None = None
    default_timeout_s: int = 60
    example: str = ""
    # True pour les outils qui sortent avec un code non-nul meme quand ils ONT trouve
    # quelque chose (convention differente d'un outil a l'autre, pas seulement en cas
    # d'erreur reelle) -- un run reste "ok" si la sortie a ete normalisee avec succes,
    # meme avec un exit_code non nul.
    nonzero_exit_ok: bool = False
    # Delai minimum (secondes) entre deux runs CONSECUTIFS de ce meme outil dans une queue --
    # profil de rate-limit par outil (plan section 2.4). Sherlock/Maigret font du bruteforce
    # sur des centaines de sites tiers ; les enchainer sans pause sur plusieurs cibles augmente
    # le risque de ban IP. Pas applique par run_tool() seul (usage direct, hors queue) --
    # seulement par osintbox.queue.
    min_delay_s: float = 0.0
    # Option CLI de l'outil tiers permettant de restreindre la recherche a un territoire
    # (ex. "--tags" chez Maigret, dont la base associe des codes pays aux sites -- voir
    # validators.TERRITORY_TAGS). None si l'outil n'a aucune notion de territoire (cas de
    # Sherlock, qui ne cible que des sites individuels via --site, sans regroupement
    # geographique) -- le territoire choisi par l'utilisateur est alors simplement ignore
    # pour cet outil plutot que de lui inventer un decoupage par pays a maintenir a la main.
    territory_flag: str | None = None

    def resolve_executable(self) -> str | None:
        """Cherche le binaire sur le PATH, et en repli dans le dossier Scripts/bin de
        l'interpreteur Python courant : shutil.which() seul ne trouve rien si le venv n'est
        pas "active" au sens shell (PATH non modifie), alors qu'un outil pip-installe dans ce
        meme venv (ex. sherlock-project) y est bel et bien present -- cas reel rencontre en
        lancant `python -m osintbox` directement avec le python du venv, sans l'avoir active.
        None si absent partout -- c'est au runner de decider quoi faire (erreur claire plutot
        qu'un crash de sous-processus)."""
        found = shutil.which(self.command[0])
        if found:
            return found
        scripts_dir = Path(sys.executable).parent
        for candidate_name in (self.command[0], f"{self.command[0]}.exe"):
            candidate = scripts_dir / candidate_name
            if candidate.is_file():
                return str(candidate)
        return None

    def build_argv(self, target: str) -> list[str]:
        return [target if part == "{target}" else part for part in self.command]

    def with_territory(self, territory: str | None) -> "ToolSpec":
        """Retourne un ToolSpec dont `command` cible un territoire (ex. "fr"), en ajoutant
        `[territory_flag, territory]` a la fin de l'argv. Si l'outil n'a pas de
        territory_flag (Sherlock) ou si `territory` est None/vide, retourne self inchange --
        le territoire est ignore pour cet outil plutot que de faire echouer tout le scan."""
        if not territory or not self.territory_flag:
            return self
        return replace(self, command=[*self.command, self.territory_flag, territory])


def _validate_entry(entry: dict) -> None:
    required = {"id", "category", "desc", "command", "target_type"}
    missing = required - entry.keys()
    if missing:
        raise CatalogError(f"Entree catalogue incomplete ({entry.get('id', '?')}) : champs manquants {missing}")
    if entry["target_type"] not in TARGET_TYPES:
        raise CatalogError(f"{entry['id']}: target_type invalide '{entry['target_type']}' (attendu: {TARGET_TYPES})")
    command = entry["command"]
    if not isinstance(command, list) or not command:
        raise CatalogError(f"{entry['id']}: 'command' doit etre une liste non vide")
    if "{target}" not in command:
        raise CatalogError(f"{entry['id']}: 'command' doit contenir le placeholder '{{target}}'")
    output_mode = entry.get("output_mode", "stdout")
    if output_mode not in OUTPUT_MODES:
        raise CatalogError(f"{entry['id']}: output_mode invalide '{output_mode}' (attendu: {OUTPUT_MODES})")
    if output_mode == "json_file" and not entry.get("output_path_template"):
        raise CatalogError(f"{entry['id']}: output_mode='json_file' requiert 'output_path_template'")


def load_catalog(path: str | Path | None = None) -> dict[str, ToolSpec]:
    """Charge et valide catalog.yaml. Leve CatalogError si le schema est invalide.

    Ne verifie PAS que l'executable existe sur le PATH ici (contrairement a PenBox, qui
    verifiait l'existence du script local a ce stade) : le catalogue doit rester chargeable
    meme si un outil tiers n'est pas installe sur cette machine -- c'est au moment de lancer
    CET outil precis que son absence doit etre signalee, pas au chargement de tout le catalogue.
    """
    catalog_path = Path(path) if path else CATALOG_PATH
    with open(catalog_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, list):
        raise CatalogError("catalog.yaml doit etre une liste d'entrees")

    tools: dict[str, ToolSpec] = {}
    seen_ids: set[str] = set()
    for entry in raw:
        _validate_entry(entry)
        if entry["id"] in seen_ids:
            raise CatalogError(f"id duplique dans le catalogue : {entry['id']}")
        seen_ids.add(entry["id"])

        spec = ToolSpec(
            id=entry["id"],
            category=entry["category"],
            desc=entry["desc"],
            command=list(entry["command"]),
            target_type=entry["target_type"],
            output_mode=entry.get("output_mode", "stdout"),
            output_path_template=entry.get("output_path_template"),
            default_timeout_s=entry.get("default_timeout_s", 60),
            example=entry.get("example", ""),
            nonzero_exit_ok=entry.get("nonzero_exit_ok", False),
            min_delay_s=entry.get("min_delay_s", 0.0),
            territory_flag=entry.get("territory_flag"),
        )
        tools[spec.id] = spec

    return tools
