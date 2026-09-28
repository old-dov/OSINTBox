//! Standalone CLI for the ported subprocess tools. Dorking remains in Python.

use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use osintbox_core::catalog::{ToolSpec, load_catalog, parse_catalog};
use osintbox_core::normalizers::{Finding, group_by_category};
use osintbox_core::queue::{Job, JobStatus, QueueOptions, run_queue_live};
use osintbox_core::runner::RunnerOptions;
use osintbox_core::store::{USERNAME_MATCH_CAVEAT, save_consolidated_report, save_run};
use osintbox_core::{validate_target, validate_territory};

const CATALOG: &str = include_str!("../../../../osintbox/catalog.yaml");

struct Args {
    target: String,
    tools: Vec<String>,
    territory: Option<String>,
    yes: bool,
    catalog: Option<PathBuf>,
    results_dir: PathBuf,
}

fn usage() -> &'static str {
    "Usage: osintbox-rs <cible> --tool <id> [--tool <id> ...] [--territory <code>] [--yes] [--catalog <fichier>] [--results-dir <dossier>]\nLes recherches dorking restent disponibles dans la CLI Python."
}

fn parse_args(mut values: impl Iterator<Item = String>) -> Result<Option<Args>, String> {
    let mut target = None;
    let mut tools = Vec::new();
    let mut territory = None;
    let mut yes = false;
    let mut catalog = None;
    let mut results_dir = PathBuf::from("results");
    while let Some(value) = values.next() {
        match value.as_str() {
            "-h" | "--help" => return Ok(None),
            "--yes" => yes = true,
            "--tool" => tools.push(values.next().ok_or("--tool requiert un identifiant")?),
            "--territory" => territory = Some(values.next().ok_or("--territory requiert un code")?),
            "--catalog" => {
                catalog = Some(PathBuf::from(
                    values.next().ok_or("--catalog requiert un fichier")?,
                ))
            }
            "--results-dir" => {
                results_dir =
                    PathBuf::from(values.next().ok_or("--results-dir requiert un dossier")?)
            }
            _ if value.starts_with('-') => return Err(format!("Option inconnue: {value}")),
            _ if target.is_none() => target = Some(value),
            _ => return Err(format!("Argument inattendu: {value}")),
        }
    }
    let target = target.ok_or_else(|| usage().to_owned())?;
    Ok(Some(Args {
        target,
        tools,
        territory,
        yes,
        catalog,
        results_dir,
    }))
}

fn selected_tools(
    catalog: &[ToolSpec],
    tools: &[String],
    territory: Option<&str>,
    target: &str,
) -> Result<Vec<ToolSpec>, String> {
    let selected = if tools.is_empty() {
        if catalog.len() != 1 {
            return Err(format!(
                "Plusieurs outils disponibles, precise --tool : {}",
                catalog
                    .iter()
                    .map(|spec| spec.id.as_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            ));
        }
        vec![catalog[0].clone()]
    } else {
        tools
            .iter()
            .map(|id| {
                catalog
                    .iter()
                    .find(|spec| spec.id == *id)
                    .cloned()
                    .ok_or_else(|| format!("Outil inconnu: {id}"))
            })
            .collect::<Result<Vec<_>, _>>()?
    };
    selected
        .into_iter()
        .map(|spec| {
            let (valid, error) = validate_target(target, &spec.target_type);
            if !valid {
                return Err(format!(
                    "Cible invalide pour {} ({}): {error}",
                    spec.id, spec.target_type
                ));
            }
            if territory.is_some() && spec.territory_flag.is_none() {
                println!(
                    "[~] {} ne supporte pas --territory, ignore pour cet outil.",
                    spec.id
                );
            }
            Ok(spec.with_territory(territory).into_owned())
        })
        .collect()
}

fn confirm(target: &str) -> io::Result<bool> {
    println!(
        "\nOSINTBox va lancer une recherche OSINT sur : {target}\nA utiliser uniquement dans un cadre autorise (votre propre identite, ou pentest/bug\nbounty avec perimetre valide). N'utilisez jamais cet outil pour harceler ou surveiller\nquelqu'un sans son consentement.\n"
    );
    print!("Confirmez-vous etre autorise a scanner cette cible ? [oui/non] ");
    io::stdout().flush()?;
    let mut answer = String::new();
    io::stdin().read_line(&mut answer)?;
    Ok(matches!(
        answer.trim().to_lowercase().as_str(),
        "oui" | "o" | "yes" | "y"
    ))
}

fn report_job(
    job: &Job,
    results_dir: &Path,
    findings: &mut Vec<Finding>,
    any_failure: &mut bool,
    write_error: &mut Option<String>,
) {
    println!("[{}] {}", job.tool_id, job.status.as_str());
    if matches!(
        job.status,
        JobStatus::Queued | JobStatus::Running | JobStatus::Retrying
    ) {
        return;
    }
    let Some(result) = job.result.as_ref() else {
        return;
    };
    if job.status != JobStatus::Done {
        *any_failure = true;
        eprintln!(
            "[ERREUR] {} {}{}",
            job.tool_id,
            job.status.as_str(),
            if result.stderr.is_empty() {
                String::new()
            } else {
                format!(
                    " ({})",
                    result
                        .stderr
                        .chars()
                        .rev()
                        .take(300)
                        .collect::<String>()
                        .chars()
                        .rev()
                        .collect::<String>()
                )
            }
        );
        if result.findings.is_empty() {
            return;
        }
    }
    if result.findings.is_empty() {
        println!(
            "[+] {}: termine, aucun resultat pour '{}'.",
            job.tool_id, job.target
        );
    } else if job.status == JobStatus::Done {
        println!(
            "[+] {}: {} resultat(s).",
            job.tool_id,
            result.findings.len()
        );
    } else {
        println!(
            "[+] {}: {} resultat(s) partiel(s) malgre '{}'.",
            job.tool_id,
            result.findings.len(),
            job.status.as_str()
        );
    }
    findings.extend(result.findings.iter().cloned());
    match save_run(results_dir, result, SystemTime::now()) {
        Ok(path) => println!(
            "[+] {}: rapport sauvegarde: {}",
            job.tool_id,
            path.display()
        ),
        Err(error) => *write_error = Some(error.to_string()),
    }
}

fn run(args: Args) -> Result<i32, String> {
    let catalog = match &args.catalog {
        Some(path) => load_catalog(path).map_err(|error| format!("Catalogue invalide: {error}"))?,
        None => parse_catalog(CATALOG).map_err(|error| format!("Catalogue invalide: {error}"))?,
    };
    let territory = match args.territory.as_deref() {
        Some(value) => {
            let (valid, error) = validate_territory(value);
            if !valid {
                return Err(error);
            }
            Some(value)
        }
        None => None,
    };
    let specs = selected_tools(&catalog, &args.tools, territory, &args.target)?;
    if !args.yes && !confirm(&args.target).map_err(|error| error.to_string())? {
        println!("Annule : autorisation non confirmee.");
        return Ok(1);
    }
    let jobs = specs
        .iter()
        .map(|spec| (spec.id.clone(), args.target.clone()))
        .collect::<Vec<_>>();
    println!(
        "[~] File d'attente : {} sur '{}'...",
        specs
            .iter()
            .map(|spec| spec.id.as_str())
            .collect::<Vec<_>>()
            .join(", "),
        args.target
    );
    let runner_options = RunnerOptions::new(
        args.results_dir
            .parent()
            .unwrap_or(&args.results_dir)
            .join(".osintbox_runs"),
    );
    let mut findings = Vec::new();
    let mut any_failure = false;
    let mut write_error = None;
    run_queue_live(
        &specs,
        &jobs,
        &runner_options,
        &QueueOptions::default(),
        |job| {
            report_job(
                job,
                &args.results_dir,
                &mut findings,
                &mut any_failure,
                &mut write_error,
            )
        },
        || false,
    )
    .map_err(|error| format!("Execution interrompue: {error:?}"))?;
    if let Some(error) = write_error {
        return Err(format!("Impossible d'enregistrer un rapport: {error}"));
    }
    if !findings.is_empty() {
        println!("\n[=] Recapitulatif par categorie :");
        for (category, group) in group_by_category(&findings) {
            println!("  {category} ({}) :", group.len());
            for finding in &group {
                println!(
                    "    - [{}] {}/{}: {}",
                    finding.confidence, finding.source, finding.kind, finding.value
                );
            }
        }
        if findings
            .iter()
            .any(|finding| finding.category == "username")
        {
            println!("\n[i] {USERNAME_MATCH_CAVEAT}");
        }
        let (json, csv) = save_consolidated_report(
            &args.results_dir,
            &args.target,
            &findings,
            SystemTime::now(),
        )
        .map_err(|error| error.to_string())?;
        println!(
            "\n[+] Rapport consolide : {}\n[+] Rapport consolide : {}",
            json.display(),
            csv.display()
        );
    }
    Ok(i32::from(any_failure))
}

fn main() {
    let code = match parse_args(std::env::args().skip(1)) {
        Ok(None) => {
            println!("{}", usage());
            0
        }
        Ok(Some(args)) => match run(args) {
            Ok(code) => code,
            Err(error) => {
                eprintln!("[ERREUR] {error}");
                1
            }
        },
        Err(error) => {
            eprintln!("[ERREUR] {error}");
            2
        }
    };
    std::process::exit(code);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_unknown_options_and_invalid_target_before_execution() {
        assert!(parse_args(["alice", "--unknown"].into_iter().map(str::to_owned)).is_err());
        let args = parse_args(
            ["--tool", "sherlock", "--yes", "--flag"]
                .into_iter()
                .map(str::to_owned),
        );
        assert!(args.is_err());
        let catalog = parse_catalog(CATALOG).unwrap();
        assert!(selected_tools(&catalog, &["sherlock".into()], None, "--flag").is_err());
    }
}
