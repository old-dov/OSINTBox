"""Point d'entree CLI. Phase 0+1 : catalogue/normalisation/validation, 2 outils integres bout
en bout (Sherlock, Maigret). Phase 2 : plusieurs --tool passent par la queue (osintbox.queue)
avec profil de delai par outil et statut visible (queued/running/done/...). Phase 3 : les
resultats d'un outil sont affiches et sauvegardes des qu'il termine (streaming reel), plus un
recapitulatif final regroupe par categorie de recon (osintbox.normalizers.group_by_category)
plutot que par outil. Phase 4 : --dork lance le module de dorking (osintbox.dorking), hors
catalogue/queue (pas un outil subprocess -- une cible domaine + un provider de recherche API).
CLI only, pas d'UI web (decide avec l'utilisateur)."""

from __future__ import annotations

import argparse
import sys

from osintbox.catalog import CatalogError, ToolSpec, load_catalog
from osintbox.config import ConfigError, get_google_cse_credentials, load_config
from osintbox.consent import confirm_authorization
from osintbox.dorking import run_dorking
from osintbox.normalizers import Finding, USERNAME_MATCH_CAVEAT, group_by_category
from osintbox.queue import Job, run_queue
from osintbox.runner import RunResult
from osintbox.search_providers import google_cse_search
from osintbox.store import save_consolidated_report, save_run
from osintbox.validators import validate_target, validate_territory

_ERROR_MESSAGES = {
    "timeout": "a depasse le timeout",
    "not_found": "executable introuvable sur le PATH",
    "failed": "a echoue",
    "rate_limited": "bloque par rate-limit apres plusieurs tentatives",
}


def _select_tools(catalog: dict[str, ToolSpec], tool_ids: list[str] | None) -> list[ToolSpec]:
    if tool_ids:
        specs = []
        for tool_id in tool_ids:
            if tool_id not in catalog:
                raise SystemExit(f"Outil inconnu: {tool_id!r}. Disponibles: {', '.join(sorted(catalog))}")
            specs.append(catalog[tool_id])
        return specs
    if len(catalog) == 1:
        return [next(iter(catalog.values()))]
    raise SystemExit(f"Plusieurs outils disponibles, precise --tool (repetable) : {', '.join(sorted(catalog))}")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="osintbox", description="Orchestrateur d'outils de recon OSINT")
    p.add_argument("target", help="Valeur a rechercher (ex: un pseudo pour sherlock/maigret, un domaine pour --dork)")
    p.add_argument(
        "--tool", action="append", dest="tools",
        help="Identifiant d'un outil a lancer (voir catalog.yaml) -- repetable pour en lancer plusieurs",
    )
    p.add_argument(
        "--territory",
        help="Restreint la recherche a un territoire (code pays, ex: fr, us, de) -- "
             "supporte par maigret uniquement, ignore pour les autres outils",
    )
    p.add_argument(
        "--dork", action="store_true",
        help="Lance le dorking (cible = domaine) via Google Custom Search API -- necessite "
             "osintbox.local.yaml (voir osintbox.local.yaml.example)",
    )
    p.add_argument(
        "--yes", action="store_true",
        help="Saute la confirmation d'autorisation (usage scripte -- reste un choix explicite)",
    )
    return p


class _StreamingReporter:
    """Affiche et sauvegarde le resultat de chaque outil des qu'il termine (statut terminal
    atteint dans la queue, ou fin du dorking), plutot que d'attendre la fin de toute la file --
    accumule aussi les findings pour le recapitulatif categorise final."""

    def __init__(self) -> None:
        self.any_failure = False
        self.all_findings: list[Finding] = []

    def on_status_change(self, job: Job) -> None:
        print(f"[{job.tool_id}] {job.status}")
        if job.status not in ("done", "failed", "timeout", "not_found", "rate_limited"):
            return  # statut intermediaire (queued/running), rien a rapporter encore

        result = job.result

        if job.status != "done":
            self.any_failure = True
            reason = _ERROR_MESSAGES.get(job.status, job.status)
            extra = f" ({result.stderr[-300:]})" if result and result.stderr else ""
            print(f"[ERREUR] {job.tool_id} {reason}{extra}", file=sys.stderr)
            # Un statut final non-"done" (ex. rate_limited) n'implique pas "aucun resultat" --
            # runner.run_tool conserve les findings deja extraits avant de changer le statut
            # (voir sa docstring) : Maigret peut par ex. avoir reellement trouve 22 comptes tout
            # en etant partiellement bloque par certains sites tiers. Les perdre ici serait un
            # vrai gachis de donnees reelles -- bug trouve en testant la GUI sur un cas reel.
            if not result or not result.findings:
                return

        if not result.findings:
            print(f"[+] {job.tool_id}: termine, aucun resultat pour '{job.target}'.")
        elif job.status == "done":
            print(f"[+] {job.tool_id}: {len(result.findings)} resultat(s).")
        else:
            print(f"[+] {job.tool_id}: {len(result.findings)} resultat(s) partiel(s) malgre '{job.status}'.")
        self.all_findings.extend(result.findings)

        out_path = save_run(result)
        print(f"[+] {job.tool_id}: rapport sauvegarde: {out_path}")

    def report_dorking(self, target: str, findings: list[Finding], errors: list[str]) -> None:
        result = RunResult(
            tool_id="dorking", target=target, status="ok", exit_code=None,
            stdout="", stderr="; ".join(errors), findings=findings,
        )
        if findings:
            print(f"[+] dorking: {len(findings)} resultat(s).")
        elif not errors:
            print(f"[+] dorking: termine, aucun resultat pour '{target}'.")
        if errors:
            print(f"[!] dorking: {len(errors)} erreur(s) : {result.stderr[:300]}", file=sys.stderr)
            if not findings:
                self.any_failure = True
        self.all_findings.extend(findings)

        out_path = save_run(result)
        print(f"[+] dorking: rapport sauvegarde: {out_path}")

    def print_summary(self) -> None:
        if not self.all_findings:
            return
        print("\n[=] Recapitulatif par categorie :")
        grouped = group_by_category(self.all_findings)
        for category, findings in grouped.items():
            print(f"  {category} ({len(findings)}) :")
            for finding in findings:
                print(f"    - [{finding.confidence}] {finding.source}/{finding.type}: {finding.value}")
        if "username" in grouped:
            print(f"\n[i] {USERNAME_MATCH_CAVEAT}")


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        catalog = load_catalog()
    except CatalogError as exc:
        print(f"[ERREUR] Catalogue invalide: {exc}", file=sys.stderr)
        return 1

    specs = _select_tools(catalog, args.tools) if (args.tools or not args.dork) else []

    for spec in specs:
        ok, error = validate_target(args.target, spec.target_type)
        if not ok:
            print(f"[ERREUR] Cible invalide pour {spec.id} ({spec.target_type}): {error}", file=sys.stderr)
            return 1

    if args.dork:
        ok, error = validate_target(args.target, "domain")
        if not ok:
            print(f"[ERREUR] Cible invalide pour dorking (domain): {error}", file=sys.stderr)
            return 1

    if args.territory:
        ok, error = validate_territory(args.territory)
        if not ok:
            print(f"[ERREUR] {error}", file=sys.stderr)
            return 1
        for spec in specs:
            if not spec.territory_flag:
                print(f"[~] {spec.id} ne supporte pas --territory, ignore pour cet outil.")
        specs = [spec.with_territory(args.territory) for spec in specs]

    if not confirm_authorization(args.target, auto_confirm=args.yes):
        print("Annule : autorisation non confirmee.")
        return 1

    reporter = _StreamingReporter()

    if specs:
        jobs_spec = [(spec.id, args.target) for spec in specs]
        print(f"[~] File d'attente : {', '.join(s.id for s in specs)} sur '{args.target}'...")
        run_queue({s.id: s for s in specs}, jobs_spec, on_status_change=reporter.on_status_change)

    if args.dork:
        try:
            config = load_config()
            api_key, cx = get_google_cse_credentials(config)
        except ConfigError as exc:
            print(f"[ERREUR] {exc}", file=sys.stderr)
            reporter.any_failure = True
        else:
            print(f"[~] Dorking sur '{args.target}'...")
            findings, errors = run_dorking(args.target, api_key, cx, search_fn=google_cse_search)
            reporter.report_dorking(args.target, findings, errors)

    reporter.print_summary()

    if reporter.all_findings:
        json_path, csv_path = save_consolidated_report(args.target, reporter.all_findings)
        print(f"\n[+] Rapport consolide : {json_path}")
        print(f"[+] Rapport consolide : {csv_path}")

    return 1 if reporter.any_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
