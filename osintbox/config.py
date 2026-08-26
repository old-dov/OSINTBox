"""Chargement de la configuration locale (cles API) -- jamais commite (voir .gitignore).
Gap identifie des la Phase 0/1 (memoire osintbox_status) : stockage des cles API. Choix retenu
pour le dorking (Phase 4, premier module a en avoir besoin) : un fichier YAML local hors suivi
git plutot que des variables d'environnement -- plus simple a documenter pour un usage perso,
avec un exemple commite (osintbox.local.yaml.example) qui sert de documentation du format
attendu."""

from __future__ import annotations

from pathlib import Path

import yaml

from osintbox.paths import user_data_dir

CONFIG_PATH = user_data_dir() / "osintbox.local.yaml"


class ConfigError(RuntimeError):
    pass


def load_config(path: Path | None = None) -> dict:
    config_path = path or CONFIG_PATH
    if not config_path.is_file():
        raise ConfigError(
            f"Fichier de config introuvable: {config_path}. Copiez "
            f"osintbox.local.yaml.example vers osintbox.local.yaml et renseignez vos cles API."
        )
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_google_cse_credentials(config: dict) -> tuple[str, str]:
    section = config.get("google_cse") or {}
    api_key, cx = section.get("api_key"), section.get("cx")
    if not api_key or not cx:
        raise ConfigError(
            "Configuration 'google_cse' incomplete dans osintbox.local.yaml (api_key et cx "
            "requis). Voir osintbox.local.yaml.example."
        )
    return api_key, cx
