"""File d'attente sequentielle avec profil de delai par outil et backoff sur rate-limit
(plan section 2.4).

Sequentielle, pas "petits lots" : c'etait un point ouvert du plan (section 7), tranche vers
l'option la plus simple/sure par defaut -- rien n'empeche d'introduire un `max_concurrent` par
categorie plus tard si le besoin se confirme, mais pas de complexite ajoutee sans un cas d'usage
reel qui la justifie (meme principe que pour le choix CLI-d'abord).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from osintbox.catalog import ToolSpec
from osintbox.normalizers import Finding
from osintbox.runner import RunResult, run_tool

# queued -> running -> (retrying -> running)* -> (done | failed | timeout | not_found | rate_limited)
# "retrying" est distinct de "rate_limited" (le statut final si les tentatives s'epuisent) --
# avant cette distinction, un rate-limit intermediaire (en cours de nouvelle tentative) et un
# rate-limit final (abandon) etaient le meme statut, impossible a distinguer par les
# appelants de on_status_change : un appelant qui voulait extraire les findings ou compter un
# job comme "termine" uniquement sur un statut vraiment final ne pouvait pas savoir si un
# "rate_limited" recu allait etre suivi d'une nouvelle tentative ou etait deja la fin (bug reel
# trouve en testant la GUI -- des findings partiels reels de Maigret etaient perdus, et un
# doublon "[ERREUR] ... rate_limited" apparaissait pour une simple tentative en cours).
JOB_STATUSES = {"queued", "running", "retrying", "done", "failed", "timeout", "not_found", "rate_limited"}


@dataclass
class Job:
    tool_id: str
    target: str
    status: str = "queued"
    result: RunResult | None = None
    attempts: int = 0


def run_queue(
    catalog: dict[str, ToolSpec],
    jobs: list[tuple[str, str]],
    *,
    on_status_change: Callable[[Job], None] | None = None,
    max_retries_on_rate_limit: int = 1,
    backoff_base_s: float = 30.0,
    run_fn: Callable[[ToolSpec, str], RunResult] = run_tool,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], float] = time.time,
    should_cancel: Callable[[], bool] | None = None,
) -> list[Job]:
    """Execute `jobs` (liste de (tool_id, target)) l'un apres l'autre. Pour chaque outil, espace
    les runs CONSECUTIFS de ce meme outil d'au moins `spec.min_delay_s` secondes (peu importe la
    cible), et retente jusqu'a `max_retries_on_rate_limit` fois avec un backoff croissant si un
    run revient "rate_limited" (voir runner.looks_rate_limited).

    `run_fn`/`sleep_fn`/`now_fn` injectables -- tests unitaires sans vrai sous-processus ni
    vraie attente. `should_cancel` (ex. `QThread.isInterruptionRequested` cote GUI) verifie
    uniquement ENTRE deux jobs -- un sous-processus deja lance va a son terme (runner.run_tool
    fait un unique `communicate(timeout=...)` bloquant, pas de boucle de polling ou greffer une
    verification a mi-course sans reecrire ce mecanisme deja valide sur les 3 outils)."""
    last_run_ts: dict[str, float] = {}
    results: list[Job] = []

    for tool_id, target in jobs:
        if should_cancel is not None and should_cancel():
            break

        spec = catalog[tool_id]
        job = Job(tool_id=tool_id, target=target)
        _emit(job, "queued", on_status_change)

        result: RunResult | None = None
        # Accumule les findings de CHAQUE tentative (dedupliques par source/type/valeur), pas
        # seulement de la derniere : un run rate_limited peut avoir deja trouve des comptes
        # reels avant d'etre bloque (voir runner.run_tool), et la tentative suivante repart
        # d'un scan complet a zero -- si elle est elle-meme bloquee plus tot (frequent, le site
        # tiers se mefie d'autant plus apres une 1re rafale), remplacer job.result par ce seul
        # dernier essai perdrait les resultats reels de la 1re tentative. Bug reel trouve en
        # testant Maigret contre "jean_dovy" (2026-08-26) : 8 comptes reels trouves au 1er essai,
        # 0 au 2e (rate-limite plus tot), GUI affichait 0 resultat au final.
        accumulated_findings: list[Finding] = []
        seen_finding_keys: set[tuple[str, str, str]] = set()

        for attempt in range(max_retries_on_rate_limit + 1):
            job.attempts += 1

            elapsed = now_fn() - last_run_ts.get(tool_id, float("-inf"))
            wait = spec.min_delay_s - elapsed
            if wait > 0:
                sleep_fn(wait)

            _emit(job, "running", on_status_change)
            last_run_ts[tool_id] = now_fn()
            result = run_fn(spec, target)
            job.result = result

            for finding in result.findings:
                key = (finding.source, finding.type, finding.value)
                if key not in seen_finding_keys:
                    seen_finding_keys.add(key)
                    accumulated_findings.append(finding)

            if result.status == "rate_limited" and attempt < max_retries_on_rate_limit:
                _emit(job, "retrying", on_status_change)
                sleep_fn(backoff_base_s * (attempt + 1))
                continue
            break

        result.findings = accumulated_findings

        final_status = {
            "ok": "done",
            "error": "failed",
            "timeout": "timeout",
            "not_found": "not_found",
            "rate_limited": "rate_limited",
        }[result.status]
        _emit(job, final_status, on_status_change)
        results.append(job)

    return results


def _emit(job: Job, status: str, on_status_change: Callable[[Job], None] | None) -> None:
    job.status = status
    if on_status_change is not None:
        on_status_change(job)
