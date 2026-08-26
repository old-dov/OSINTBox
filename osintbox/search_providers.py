"""Providers de recherche pour le dorking -- API officielle uniquement, jamais de requete
HTTP directe vers une page de resultats de moteur de recherche (violerait ses ToS et pousserait
vers du contournement anti-bot -- decide explicitement avec l'utilisateur, voir plan section 6
et osintbox_status memoire)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import requests

GOOGLE_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchProviderError(RuntimeError):
    pass


class SearchRateLimited(SearchProviderError):
    pass


def google_cse_search(
    query: str,
    api_key: str,
    cx: str,
    *,
    num: int = 10,
    request_fn: Callable[..., "requests.Response"] = requests.get,
) -> list[SearchResult]:
    """Un appel = une requete Google Custom Search JSON API (quota gratuit : 100 requetes/jour,
    limite Google -- pas la notre). `num` plafonne a 10 resultats par requete (limite API)."""
    resp = request_fn(
        GOOGLE_CSE_ENDPOINT,
        params={"key": api_key, "cx": cx, "q": query, "num": min(num, 10)},
        timeout=15,
    )
    if resp.status_code == 429:
        raise SearchRateLimited(f"Quota Google CSE depasse (429) pour la requete: {query!r}")
    if resp.status_code != 200:
        raise SearchProviderError(f"Google CSE a repondu {resp.status_code} pour {query!r}: {resp.text[:300]}")

    data = resp.json()
    return [
        SearchResult(title=item.get("title", ""), url=item.get("link", ""), snippet=item.get("snippet", ""))
        for item in data.get("items", [])
    ]
