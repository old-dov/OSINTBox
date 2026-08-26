"""Orchestration du dorking (plan phase 4) -- construit les dorks (osintbox.dorks), les
execute via un provider de recherche officiel (osintbox.search_providers), normalise en
Finding. Delai conservateur entre requetes par defaut (plan section 6 : 'pas de scraping
agressif par defaut, profils de delai conservateurs, ajustables') -- ici pas de scraping (API
officielle), mais un delai reste une politesse envers le quota tiers et se comporte comme le
`min_delay_s` des autres outils du catalogue."""

from __future__ import annotations

import time
from typing import Callable

from osintbox.dorks import build_dorks
from osintbox.normalizers import Finding
from osintbox.search_providers import SearchProviderError, SearchRateLimited, SearchResult

DEFAULT_DELAY_S = 2.0


def run_dorking(
    target: str,
    api_key: str,
    cx: str,
    *,
    delay_s: float = DEFAULT_DELAY_S,
    search_fn: Callable[..., list[SearchResult]],
    sleep_fn: Callable[[float], None] = time.sleep,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[list[Finding], list[str]]:
    """Retourne (findings, erreurs). Une erreur provider sur un dork n'interrompt pas les
    suivants (juste collectee), sauf un rate-limit (quota depasse -> inutile d'insister).
    `should_cancel` (ex. `QThread.isInterruptionRequested` cote GUI) verifie entre deux dorks,
    meme logique que `queue.run_queue`."""
    findings: list[Finding] = []
    errors: list[str] = []

    for i, (label, query) in enumerate(build_dorks(target)):
        if should_cancel is not None and should_cancel():
            break
        if i > 0:
            sleep_fn(delay_s)
        try:
            results = search_fn(query, api_key, cx)
        except SearchRateLimited as exc:
            errors.append(str(exc))
            break
        except SearchProviderError as exc:
            errors.append(str(exc))
            continue

        for result in results:
            findings.append(
                Finding(
                    source="dorking",
                    category="dorking",
                    type=label,
                    value=result.url,
                    confidence="medium",
                    raw={"query": query, "title": result.title, "snippet": result.snippet},
                )
            )

    return findings, errors
