"""Garde-fou d'autorisation -- confirmation explicite avant tout scan.

Absent de PenBox (contexte different : scripts de pentest lances par quelqu'un qui a deja
choisi sa cible dans un cadre de mission). OSINTBox automatise du bruteforce sur des centaines
de sites tiers pour un seul username/email -- un rappel + une confirmation explicite avant
chaque cible, pas juste une phrase dans un README qu'on ne relit jamais.
"""

from __future__ import annotations

AUTHORIZATION_PROMPT = (
    "\nOSINTBox va lancer une recherche OSINT sur : {target}\n"
    "A utiliser uniquement dans un cadre autorise (votre propre identite, ou pentest/bug\n"
    "bounty avec perimetre valide). N'utilisez jamais cet outil pour harceler ou surveiller\n"
    "quelqu'un sans son consentement.\n"
)


def confirm_authorization(target: str, *, auto_confirm: bool = False, prompt_fn=input) -> bool:
    """auto_confirm=True (flag --yes explicite en CLI) saute la question -- utile pour un
    usage scripte, mais reste un choix explicite de l'appelant, jamais le defaut."""
    if auto_confirm:
        return True
    print(AUTHORIZATION_PROMPT.format(target=target))
    answer = prompt_fn("Confirmez-vous etre autorise a scanner cette cible ? [oui/non] ")
    return answer.strip().lower() in ("oui", "o", "yes", "y")
