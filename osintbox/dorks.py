"""Generation de requetes de dorking (plan section 3, phase 4) -- dorks de decouverte
conservateurs (fichiers exposes, panneaux d'admin, fuites git), pas de dorks agressifs ou
intrusifs. La cible est toujours un domaine."""

from __future__ import annotations

# (label, gabarit) -- le label sert de `Finding.type` (identifiant stable), le gabarit est le
# dork pret a executer une fois {target} substitue.
DORK_TEMPLATES: list[tuple[str, str]] = [
    ("exposed_pdf", "site:{target} filetype:pdf"),
    ("exposed_spreadsheet", "site:{target} (filetype:xls OR filetype:xlsx OR filetype:csv)"),
    ("exposed_sql", "site:{target} filetype:sql"),
    ("exposed_log", "site:{target} filetype:log"),
    ("exposed_env", "site:{target} filetype:env"),
    ("directory_listing", 'site:{target} intitle:"index of"'),
    ("admin_panel", "site:{target} inurl:admin"),
    ("login_page", 'site:{target} intitle:"login"'),
    ("git_exposure", 'site:{target} inurl:".git"'),
]


def build_dorks(target: str) -> list[tuple[str, str]]:
    return [(label, template.format(target=target)) for label, template in DORK_TEMPLATES]
