//! JSON and CSV exports matching `osintbox/store.py`.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{Value, json};

use crate::normalizers::Finding;
use crate::runner::{RunResult, RunStatus};

pub const USERNAME_MATCH_CAVEAT: &str = "Confiance 'high' sur un compte username (sherlock/maigret) signifie qu'un compte existe avec ce pseudo exact sur ce site -- PAS que ce compte appartient a la cible. A verifier manuellement (photo, bio, activite) avant de conclure a une identite.";

pub fn safe_slug(value: &str) -> String {
    value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || "_.-".contains(ch) {
                ch
            } else {
                '_'
            }
        })
        .take(80)
        .collect()
}

fn timestamp(now: SystemTime) -> (String, String) {
    let duration = now.duration_since(UNIX_EPOCH).unwrap_or_default();
    let seconds = duration.as_secs();
    let days = (seconds / 86_400) as i64;
    let seconds_of_day = seconds % 86_400;
    // Proleptic Gregorian conversion from Unix days (civil_from_days).
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let mut year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = mp + if mp < 10 { 3 } else { -9 };
    if month <= 2 {
        year += 1;
    }
    let hour = seconds_of_day / 3_600;
    let minute = seconds_of_day / 60 % 60;
    let second = seconds_of_day % 60;
    let stamp = format!("{year:04}{month:02}{day:02}_{hour:02}{minute:02}{second:02}");
    let iso = format!(
        "{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}.{:06}+00:00",
        duration.subsec_micros()
    );
    (stamp, iso)
}

fn finding_json(finding: &Finding) -> Value {
    json!({
        "source": finding.source,
        "category": finding.category,
        "type": finding.kind,
        "value": finding.value,
        "confidence": finding.confidence,
        "raw": finding.raw,
    })
}

fn findings_json(findings: &[Finding]) -> Vec<Value> {
    findings.iter().map(finding_json).collect()
}

fn with_note(mut payload: Value, findings: &[Finding]) -> Value {
    if findings
        .iter()
        .any(|finding| finding.category == "username")
    {
        payload["note"] = json!(USERNAME_MATCH_CAVEAT);
    }
    payload
}

fn write_json(path: &Path, payload: &Value) -> io::Result<()> {
    let mut content = serde_json::to_string_pretty(payload)?;
    content.push('\n');
    fs::write(path, content)
}

pub fn save_run(results_dir: &Path, result: &RunResult, now: SystemTime) -> io::Result<PathBuf> {
    fs::create_dir_all(results_dir)?;
    let (stamp, generated_at) = timestamp(now);
    let path = results_dir.join(format!(
        "{}_{}_{}.json",
        safe_slug(&result.target),
        result.tool_id,
        stamp
    ));
    let status = match result.status {
        RunStatus::Ok => "ok",
        RunStatus::Error => "error",
        RunStatus::Timeout => "timeout",
        RunStatus::NotFound => "not_found",
        RunStatus::RateLimited => "rate_limited",
    };
    let payload = with_note(
        json!({
            "tool_id": result.tool_id,
            "target": result.target,
            "status": status,
            "exit_code": result.exit_code,
            "generated_at": generated_at,
            "findings": findings_json(&result.findings),
        }),
        &result.findings,
    );
    write_json(&path, &payload)?;
    Ok(path)
}

fn csv_field(field: &str) -> String {
    if field.contains([',', '"', '\n', '\r']) {
        format!("\"{}\"", field.replace('"', "\"\""))
    } else {
        field.to_owned()
    }
}

pub fn save_consolidated_report(
    results_dir: &Path,
    target: &str,
    findings: &[Finding],
    now: SystemTime,
) -> io::Result<(PathBuf, PathBuf)> {
    fs::create_dir_all(results_dir)?;
    let (stamp, generated_at) = timestamp(now);
    let base = format!("{}_report_{stamp}", safe_slug(target));
    let json_path = results_dir.join(format!("{base}.json"));
    let csv_path = results_dir.join(format!("{base}.csv"));
    let payload = with_note(
        json!({
            "target": target,
            "generated_at": generated_at,
            "finding_count": findings.len(),
            "findings": findings_json(findings),
        }),
        findings,
    );
    write_json(&json_path, &payload)?;
    let mut csv = String::from("source,category,type,value,confidence,raw\r\n");
    for finding in findings {
        let raw = serde_json::to_string(&finding.raw)?;
        let columns = [
            &finding.source,
            &finding.category,
            &finding.kind,
            &finding.value,
            &finding.confidence,
            &raw,
        ];
        csv.push_str(
            &columns
                .iter()
                .map(|column| csv_field(column))
                .collect::<Vec<_>>()
                .join(","),
        );
        csv.push_str("\r\n");
    }
    fs::write(&csv_path, csv)?;
    Ok((json_path, csv_path))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::normalizers::normalize_text;

    #[test]
    fn reports_match_python_schema_and_escape_csv() {
        let root = std::env::temp_dir().join(format!("osintbox-store-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let now = UNIX_EPOCH + std::time::Duration::from_secs(1_783_207_245);
        let mut findings =
            normalize_text("sherlock", "[+] GitHub: https://github.com/alice", "alice");
        assert_eq!(findings.len(), 1);
        findings[0].value = "a,\"b\"\nc".into();
        let result = RunResult {
            tool_id: "sherlock".into(),
            target: "al/ice".into(),
            status: RunStatus::Ok,
            exit_code: Some(0),
            stdout: String::new(),
            stderr: String::new(),
            findings: findings.clone(),
            run_dir: None,
        };
        let run_path = save_run(&root, &result, now).unwrap();
        assert!(
            run_path
                .file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("al_ice_sherlock_")
        );
        let run: Value = serde_json::from_slice(&fs::read(run_path).unwrap()).unwrap();
        assert_eq!(run["findings"][0]["type"], "social_profile");
        assert_eq!(run["generated_at"], "2026-07-04T23:20:45.000000+00:00");
        let (json_path, csv_path) =
            save_consolidated_report(&root, "al/ice", &findings, now).unwrap();
        let report: Value = serde_json::from_slice(&fs::read(json_path).unwrap()).unwrap();
        assert_eq!(report["finding_count"], 1);
        assert_eq!(report["note"], USERNAME_MATCH_CAVEAT);
        let csv = fs::read_to_string(csv_path).unwrap();
        assert!(csv.contains("\"a,\"\"b\"\"\nc\""));
        fs::remove_dir_all(root).unwrap();
    }
}
