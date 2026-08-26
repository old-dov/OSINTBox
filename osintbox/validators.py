"""Validation stricte des valeurs de cible avant tout passage en argv de sous-processus.

Adapte de PenBox (penbox/validators.py) : meme principe (regex strictes, rejet des valeurs
qui ressemblent a une option pour eviter l'injection d'argv), types de cible etendus a ceux
du plan OSINTBox (username, email en plus de domain/host/ip/url).
"""

from __future__ import annotations

import ipaddress
import re

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
# Pas une RFC 5322 complete (inutilement permissive pour un usage recon) : suffisant pour
# rejeter les valeurs manifestement invalides avant de les passer a un sous-processus.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,64}@[A-Za-z0-9-]{1,253}(\.[A-Za-z0-9-]{1,63})+$")
_URL_RE = re.compile(r"^https?://[^\s]{1,2048}$")

TARGET_TYPES = {"username", "email", "domain", "host", "ip", "url"}

# Codes de territoire (tags pays ISO-3166-1 alpha-2 en minuscule) connus de la base Maigret,
# extraits reellement de son data.json (~/.maigret/data.json) plutot que devines depuis la
# doc -- 76 codes recenses au moment de l'ecriture. Sert de garde-fou cote client (rejeter une
# faute de frappe avant de lancer le sous-processus) : ce n'est PAS l'autorite finale sur les
# tags valides, Maigret filtre avec sa propre base a jour au moment du run -- une nouvelle
# entree que Maigret ajouterait apres coup serait rejetee ici jusqu'a mise a jour de cette
# liste, pas une erreur de Maigret lui-meme.
TERRITORY_TAGS = frozenset({
    "ae", "am", "ar", "at", "au", "az", "bd", "be", "bg", "br", "by", "ca", "ch", "cl", "cn",
    "co", "cr", "cz", "de", "dk", "dz", "ee", "eg", "es", "fi", "fr", "gb", "gr", "hk", "hr",
    "hu", "id", "ie", "il", "in", "ir", "it", "jp", "kg", "kr", "kz", "lk", "lt", "lv", "ma",
    "md", "mk", "mx", "my", "ng", "nl", "no", "nz", "ph", "pk", "pl", "pt", "ro", "rs", "ru",
    "sa", "se", "sg", "th", "tm", "tn", "tr", "tw", "tz", "ua", "us", "uz", "ve", "vn", "za",
})


def validate_territory(value: str) -> tuple[bool, str]:
    """Retourne (ok, message_erreur) pour un code de territoire (ex. "fr"). Meme garde
    anti-injection que validate_target (rejet d'une valeur commencant par '-') puisque cette
    valeur finit elle aussi en argv d'un sous-processus (voir ToolSpec.with_territory)."""
    value = (value or "").strip().lower()
    if not value:
        return False, "Territoire vide"
    if value.startswith("-"):
        return False, "Le territoire ne peut pas commencer par '-' (serait interprete comme une option)"
    if value not in TERRITORY_TAGS:
        return False, f"Territoire inconnu '{value}' (ex: fr, us, de, gb...)"
    return True, ""


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def validate_target(value: str, target_type: str) -> tuple[bool, str]:
    """Retourne (ok, message_erreur). message_erreur == "" si ok."""
    value = (value or "").strip()
    if not value:
        return False, "Valeur vide"
    if value.startswith("-"):
        return False, "La valeur ne peut pas commencer par '-' (serait interpretee comme une option)"

    if target_type == "username":
        return (True, "") if _USERNAME_RE.match(value) else (False, "Nom d'utilisateur invalide")

    if target_type == "email":
        return (True, "") if _EMAIL_RE.match(value) else (False, "Adresse email invalide")

    if target_type == "domain":
        return (True, "") if _DOMAIN_RE.match(value) else (False, "Domaine invalide (ex: exemple.com)")

    if target_type == "host":
        if _is_ip(value) or _HOSTNAME_RE.match(value):
            return True, ""
        return False, "Doit etre une IP ou un nom d'hote valide"

    if target_type == "ip":
        return (True, "") if _is_ip(value) else (False, "Adresse IP invalide")

    if target_type == "url":
        return (True, "") if _URL_RE.match(value) else (False, "URL invalide (doit commencer par http:// ou https://)")

    return False, f"Type de cible inconnu: {target_type}"
