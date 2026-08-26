"""Registre de normaliseurs sortie-brute-outil -> list[Finding], un par outil.

Adapte du pattern PenBox (penbox/normalizers.py : registre par decorateur + repli generique),
avec le schema Finding du plan OSINTBox (source/category/type/value/confidence/raw) plutot que
celui de PenBox (name/category/risk/detail/raw) -- confidence remplace risk, plus adapte a du
recon (on ne "risque" rien, on est plus ou moins sur qu'un profil appartient a la cible).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

_REGISTRY: dict[str, Callable[[Any, dict[str, Any]], list["Finding"]]] = {}

# Sherlock/Maigret marquent leurs hits confidence="high", ce qui signifie seulement "un compte
# existe avec ce pseudo exact sur ce site" -- pas "ce compte appartient a la cible". Un pseudo
# courant peut tres bien avoir ete pris par quelqu'un d'autre sur un site donne (retour
# utilisateur reel : match Twitter confirme, mais pas de compte reel sur 7 des 8 autres sites
# remontes pour le meme pseudo, 2026-08-26). Constante partagee par cli.py/main_window.py/
# store.py pour rappeler cette limite partout ou des findings "username" sont affiches/exportes.
USERNAME_MATCH_CAVEAT = (
    "Confiance 'high' sur un compte username (sherlock/maigret) signifie qu'un compte existe "
    "avec ce pseudo exact sur ce site -- PAS que ce compte appartient a la cible. A verifier "
    "manuellement (photo, bio, activite) avant de conclure a une identite."
)


@dataclass
class Finding:
    source: str
    category: str
    type: str
    value: str
    confidence: str = "medium"  # "high" | "medium" | "low"
    raw: dict[str, Any] = field(default_factory=dict)


def register(tool_id: str):
    def deco(fn: Callable[[Any, dict[str, Any]], list[Finding]]):
        _REGISTRY[tool_id] = fn
        return fn

    return deco


def group_by_category(findings: list[Finding]) -> dict[str, list[Finding]]:
    """Regroupe des findings par categorie de recon (plan section 2.3), pas par outil source --
    un outil peut alimenter plusieurs categories. Preserve l'ordre d'apparition des categories
    et des findings a l'interieur de chacune."""
    grouped: dict[str, list[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.category, []).append(finding)
    return grouped


def normalize(tool_id: str, raw: Any, target: str) -> list[Finding]:
    """raw est soit le stdout texte (output_mode="stdout", ex. sherlock), soit un objet
    JSON deja parse -- dict/list (output_mode="json_file", ex. maigret). target passe en plus
    pour les normaliseurs qui en ont besoin pour construire le Finding (le nom d'utilisateur
    cherche n'apparait pas forcement dans chaque entree de resultat)."""
    fn = _REGISTRY.get(tool_id)
    if fn is not None:
        return fn(raw, {"target": target})
    return _normalize_generic(tool_id, raw, target)


def _normalize_generic(tool_id: str, raw: Any, target: str) -> list[Finding]:
    """Repli pour les outils sans normaliseur dedie. Texte brut (stdout) : un Finding par
    ligne non vide. JSON deja structure sans normaliseur dedie : un Finding qui enveloppe le
    JSON brut plutot que d'essayer de deviner sa forme -- confiance basse dans les deux cas."""
    if isinstance(raw, str):
        findings = []
        for line in raw.splitlines():
            line = line.strip()
            if line:
                findings.append(Finding(source=tool_id, category=tool_id, type="raw_line", value=line, confidence="low"))
        return findings
    return [Finding(source=tool_id, category=tool_id, type="raw", value=target, confidence="low", raw=raw if isinstance(raw, dict) else {"items": raw})]


# Sherlock imprime "[+] SiteName: https://..." pour chaque site ou le username est trouve,
# avec --print-found --no-color (voir catalog.yaml). Pas de sortie JSON structuree native
# (son flag --json sert a CHARGER une liste de sites personnalisee, pas a exporter des
# resultats) -- confirme en testant reellement le CLI avant d'ecrire ce parseur.
_SHERLOCK_LINE_RE = re.compile(r"^\[\+\]\s*(?P<site>[^:]+):\s*(?P<url>https?://\S+)$")


@register("sherlock")
def _normalize_sherlock(stdout: str, ctx: dict[str, Any]) -> list[Finding]:
    findings = []
    for line in stdout.splitlines():
        match = _SHERLOCK_LINE_RE.match(line.strip())
        if match:
            findings.append(
                Finding(
                    source="sherlock",
                    category="username",
                    type="social_profile",
                    value=match.group("url"),
                    confidence="high",
                    raw={"site": match.group("site").strip(), "username": ctx["target"]},
                )
            )
    return findings


# Maigret produit un vrai JSON structure (-J simple), contrairement a Sherlock : un dict
# {nom_du_site: {status: {status, url, ids}, url_user, ...}}. Confirme en lancant reellement
# `maigret <user> -J simple` -- le rapport ne contient deja que les comptes "Claimed" (le
# filtrage equivalent au --print-found de Sherlock est fait par l'outil lui-meme), mais on
# revalide status.status au cas ou une version future du format change ce comportement.
@register("maigret")
def _normalize_maigret(raw: dict[str, Any], ctx: dict[str, Any]) -> list[Finding]:
    findings = []
    if not isinstance(raw, dict):
        return findings
    for site_name, entry in raw.items():
        status = (entry or {}).get("status", {})
        if status.get("status") != "Claimed":
            continue
        url = entry.get("url_user") or status.get("url")
        if not url:
            continue
        findings.append(
            Finding(
                source="maigret",
                category="username",
                type="social_profile",
                value=url,
                confidence="high",
                raw={"site": site_name, "username": ctx["target"], "extracted": status.get("ids", {})},
            )
        )
    return findings


# Holehe imprime "[+] site.tld" pour chaque site ou l'email est utilise (--only-used), plus un
# habillage (banniere donation/GitHub, ligne de legende "[+] Email used, [-] Email not used,
# [x] Rate limit", compteur final) qui ressemble a s'y meprendre a une ligne de resultat. La
# ligne de legende commence aussi par "[+] " -- confirme en lancant reellement le CLI (pas
# suppose depuis la doc). Le nom de site est ancre en fin de ligne et doit ressembler a un
# domaine pour exclure cette legende sans avoir a la lister explicitement.
_HOLEHE_LINE_RE = re.compile(r"^\[\+\]\s*(?P<site>[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,})\s*$")


@register("holehe")
def _normalize_holehe(stdout: str, ctx: dict[str, Any]) -> list[Finding]:
    findings = []
    for line in stdout.splitlines():
        match = _HOLEHE_LINE_RE.match(line.strip())
        if match:
            site = match.group("site")
            findings.append(
                Finding(
                    source="holehe",
                    category="email",
                    type="account_exists",
                    value=site,
                    confidence="high",
                    raw={"site": site, "email": ctx["target"]},
                )
            )
    return findings


# theHarvester (-f <path>) ecrit un JSON {"cmd": ..., "hosts": [...], "emails": [...], ...} --
# confirme en lancant reellement `theHarvester -d python.org -b crtsh -f <path>` : les cles
# absentes de resultats (ex. "emails" quand crt.sh n'en trouve pas) ne sont PAS presentes du
# tout dans le JSON, plutot que des listes vides -- d'ou les .get(key, []) defensifs plutot que
# raw[key] direct.
@register("theharvester")
def _normalize_theharvester(raw: dict[str, Any], ctx: dict[str, Any]) -> list[Finding]:
    findings = []
    if not isinstance(raw, dict):
        return findings
    for host in raw.get("hosts", []):
        findings.append(Finding(source="theharvester", category="domain", type="subdomain", value=host, confidence="high"))
    for email in raw.get("emails", []):
        findings.append(Finding(source="theharvester", category="email", type="email_address", value=email, confidence="high"))
    for ip in raw.get("ips", []):
        findings.append(Finding(source="theharvester", category="domain", type="ip", value=ip, confidence="medium"))
    return findings
