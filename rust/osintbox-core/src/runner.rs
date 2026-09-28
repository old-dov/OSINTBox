//! Subprocess runner with timeout, persistent JSON reports and partial findings.

use std::ffi::OsString;
use std::fs;
use std::io::{self, Read};
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::catalog::ToolSpec;
use crate::normalizers::{Finding, normalize_json, normalize_text};
use crate::validate_target;

static RUN_COUNTER: AtomicU64 = AtomicU64::new(0);
const RATE_LIMIT_MARKERS: &[&str] = &[
    "rate limit exceeded",
    "rate limited",
    "too many requests",
    "429",
    "bot protection",
    "access denied",
    "banned",
    "blocked",
    "captcha",
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RunStatus {
    Ok,
    Error,
    Timeout,
    NotFound,
    RateLimited,
}

#[derive(Debug)]
pub struct RunResult {
    pub tool_id: String,
    pub target: String,
    pub status: RunStatus,
    pub exit_code: Option<i32>,
    pub stdout: String,
    pub stderr: String,
    pub findings: Vec<Finding>,
    pub run_dir: Option<PathBuf>,
}

#[derive(Debug)]
pub enum RunError {
    InvalidTarget(String),
    InvalidOutputPath(String),
    Io(io::Error),
}

impl From<io::Error> for RunError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

/// The caller chooses a writable run root, e.g. `%LOCALAPPDATA%/OSINTBox/.osintbox_runs`.
pub struct RunnerOptions {
    pub run_root: PathBuf,
    pub scripts_dir: Option<PathBuf>,
    pub timeout: Option<Duration>,
    pub env: Vec<(OsString, OsString)>,
}

impl RunnerOptions {
    pub fn new(run_root: impl Into<PathBuf>) -> Self {
        Self {
            run_root: run_root.into(),
            scripts_dir: None,
            timeout: None,
            env: Vec::new(),
        }
    }
}

pub fn looks_rate_limited(stdout: &str, stderr: &str) -> bool {
    let combined = format!("{stdout}\n{stderr}").to_lowercase();
    RATE_LIMIT_MARKERS
        .iter()
        .any(|marker| combined.contains(marker))
}

pub fn run_tool(
    spec: &ToolSpec,
    target: &str,
    options: &RunnerOptions,
) -> Result<RunResult, RunError> {
    let (valid, message) = validate_target(target, &spec.target_type);
    if !valid {
        return Err(RunError::InvalidTarget(message));
    }

    let Some(executable) = resolve_executable(&spec.command[0], options.scripts_dir.as_deref())
    else {
        return Ok(RunResult {
            tool_id: spec.id.clone(),
            target: target.into(),
            status: RunStatus::NotFound,
            exit_code: None,
            stdout: String::new(),
            stderr: format!("Executable introuvable sur le PATH: {}", spec.command[0]),
            findings: Vec::new(),
            run_dir: None,
        });
    };

    let run_dir = if spec.output_mode == "json_file" {
        fs::create_dir_all(&options.run_root)?;
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let sequence = RUN_COUNTER.fetch_add(1, Ordering::Relaxed);
        let directory = options.run_root.join(format!(
            "{}_{}_{}_{}_{}",
            safe_name(&spec.id),
            safe_name(target),
            std::process::id(),
            timestamp,
            sequence
        ));
        fs::create_dir(&directory)?;
        Some(directory)
    } else {
        None
    };

    let argv = spec.build_argv(target);
    let mut command = Command::new(executable);
    command
        .args(&argv[1..])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("PYTHONIOENCODING", "utf-8")
        .envs(options.env.iter().map(|(key, value)| (key, value)));
    if let Some(directory) = &run_dir {
        command.current_dir(directory);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    let mut child = command.spawn()?;
    let stdout_pipe = child.stdout.take().expect("piped stdout");
    let stderr_pipe = child.stderr.take().expect("piped stderr");
    let stdout_bytes = Arc::new(Mutex::new(Vec::new()));
    let stderr_bytes = Arc::new(Mutex::new(Vec::new()));
    let stdout_buffer = Arc::clone(&stdout_bytes);
    let stderr_buffer = Arc::clone(&stderr_bytes);
    let stdout_reader = thread::spawn(move || read_pipe(stdout_pipe, stdout_buffer));
    let stderr_reader = thread::spawn(move || read_pipe(stderr_pipe, stderr_buffer));

    let timeout = options
        .timeout
        .unwrap_or(Duration::from_secs(spec.default_timeout_s));
    let start = Instant::now();
    let mut exit_status = None;
    let mut timed_out = false;
    loop {
        if exit_status.is_none() {
            exit_status = child.try_wait()?;
        }
        if exit_status.is_some() && stdout_reader.is_finished() && stderr_reader.is_finished() {
            break;
        }
        if start.elapsed() >= timeout {
            timed_out = true;
            #[cfg(windows)]
            kill_tree(child.id());
            if exit_status.is_none() {
                let _ = child.kill();
                exit_status = Some(child.wait()?);
            }
            break;
        }
        thread::sleep(Duration::from_millis(20));
    }
    // A descendant can keep a pipe open after its parent exits. Keep the
    // deadline and any output already read instead of waiting indefinitely.
    if stdout_reader.is_finished() {
        stdout_reader.join().expect("stdout reader")?;
    }
    if stderr_reader.is_finished() {
        stderr_reader.join().expect("stderr reader")?;
    }
    let stdout = String::from_utf8_lossy(&stdout_bytes.lock().expect("stdout bytes")).into_owned();
    let mut stderr =
        String::from_utf8_lossy(&stderr_bytes.lock().expect("stderr bytes")).into_owned();
    let exit_code = exit_status.and_then(|status| status.code());
    let mut status = if timed_out {
        RunStatus::Timeout
    } else if exit_code == Some(0) || spec.nonzero_exit_ok {
        RunStatus::Ok
    } else {
        RunStatus::Error
    };
    let mut findings = Vec::new();

    if status == RunStatus::Ok && spec.output_mode == "stdout" {
        findings = normalize_text(&spec.id, &stdout, target);
    } else if status == RunStatus::Ok && spec.output_mode == "json_file" {
        let template = spec.output_path_template.as_deref().unwrap_or_default();
        let relative = template.replace("{target}", target);
        let path = Path::new(&relative);
        if path
            .components()
            .any(|part| !matches!(part, Component::Normal(_) | Component::CurDir))
        {
            return Err(RunError::InvalidOutputPath(relative));
        }
        let json_path = run_dir.as_ref().expect("JSON run dir").join(path);
        match fs::read_to_string(&json_path) {
            Ok(content) => match serde_json::from_str(&content) {
                Ok(raw) => findings = normalize_json(&spec.id, &raw, target),
                Err(error) => {
                    status = RunStatus::Error;
                    stderr.push_str(&format!(
                        "\nFichier JSON illisible ({}): {error}",
                        json_path.display()
                    ));
                }
            },
            Err(error) => {
                status = RunStatus::Error;
                stderr.push_str(&format!(
                    "\nFichier JSON attendu introuvable ({}): {error}",
                    json_path.display()
                ));
            }
        }
    }
    if matches!(status, RunStatus::Ok | RunStatus::Error) && looks_rate_limited(&stdout, &stderr) {
        status = RunStatus::RateLimited;
    }
    Ok(RunResult {
        tool_id: spec.id.clone(),
        target: target.into(),
        status,
        exit_code,
        stdout,
        stderr,
        findings,
        run_dir,
    })
}

fn read_pipe(mut pipe: impl Read, bytes: Arc<Mutex<Vec<u8>>>) -> io::Result<()> {
    let mut chunk = [0; 8192];
    loop {
        let count = pipe.read(&mut chunk)?;
        if count == 0 {
            return Ok(());
        }
        bytes
            .lock()
            .expect("pipe bytes")
            .extend_from_slice(&chunk[..count]);
    }
}

fn safe_name(value: &str) -> String {
    let safe: String = value
        .chars()
        .filter(|character| character.is_ascii_alphanumeric() || "_.-".contains(*character))
        .take(64)
        .collect();
    if safe.is_empty() {
        "target".into()
    } else {
        safe
    }
}

fn resolve_executable(name: &str, scripts_dir: Option<&Path>) -> Option<PathBuf> {
    let path = Path::new(name);
    if path.is_absolute() || path.components().count() > 1 {
        return path.is_file().then(|| path.to_path_buf());
    }
    let path_dirs = std::env::var_os("PATH")
        .map(|paths| std::env::split_paths(&paths).collect::<Vec<_>>())
        .unwrap_or_default();
    for directory in path_dirs.iter().map(PathBuf::as_path).chain(scripts_dir) {
        if let Some(candidate) = executable_in(directory, name) {
            return Some(candidate);
        }
    }
    None
}

fn executable_in(directory: &Path, name: &str) -> Option<PathBuf> {
    let candidate = directory.join(name);
    if candidate.is_file() {
        return Some(candidate);
    }
    #[cfg(windows)]
    {
        for extension in ["exe", "com", "cmd", "bat"] {
            let candidate = directory.join(format!("{name}.{extension}"));
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    None
}

#[cfg(windows)]
fn kill_tree(pid: u32) {
    use std::os::windows::process::CommandExt;
    let _ = Command::new("taskkill")
        .args(["/F", "/T", "/PID", &pid.to_string()])
        .creation_flags(0x08000000)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::catalog::parse_catalog;

    fn tool(id: &str, output_mode: &str, helper: &str) -> ToolSpec {
        let executable = std::env::current_exe().unwrap().display().to_string();
        let source = format!(
            r#"- id: {id}
  category: username
  desc: fixture
  command: ['{executable}', '--exact', 'runner::tests::{helper}', '--nocapture', '--format', '{{target}}']
  target_type: username
  output_mode: {output_mode}
  output_path_template: 'reports/report_{{target}}_simple.json'
  default_timeout_s: 5
"#
        );
        parse_catalog(&source).unwrap().remove(0)
    }

    fn options() -> RunnerOptions {
        let mut options =
            RunnerOptions::new(Path::new(env!("CARGO_MANIFEST_DIR")).join("../target/test-runs"));
        options
            .env
            .push(("OSINTBOX_RUNNER_CHILD".into(), "1".into()));
        options
    }

    #[test]
    fn helper_stdout() {
        if std::env::var_os("OSINTBOX_RUNNER_CHILD").is_some() {
            println!("\n[+] GitHub: https://github.com/pretty");
            println!("[!] Too many errors of type Bot protection");
        }
    }

    #[test]
    fn helper_json() {
        if std::env::var_os("OSINTBOX_RUNNER_CHILD").is_some() {
            fs::create_dir_all("reports").unwrap();
            fs::write("reports/report_pretty_simple.json", r#"{"GitHub":{"status":{"status":"Claimed","url":"https://github.com/pretty"},"url_user":"https://github.com/pretty"}}"#).unwrap();
        }
    }

    #[test]
    fn helper_sleep() {
        if std::env::var_os("OSINTBOX_RUNNER_CHILD").is_some() {
            thread::sleep(Duration::from_secs(2));
        }
    }

    #[test]
    fn helper_invalid_json() {
        if std::env::var_os("OSINTBOX_RUNNER_CHILD").is_some() {
            fs::create_dir_all("reports").unwrap();
            fs::write("reports/report_pretty_simple.json", "not JSON").unwrap();
        }
    }

    #[test]
    fn helper_no_json() {}

    #[test]
    fn helper_failure() {
        if std::env::var_os("OSINTBOX_RUNNER_CHILD").is_some() {
            panic!("fixture exits with an error");
        }
    }

    #[test]
    fn runner_keeps_findings_when_rate_limited() {
        let result = run_tool(
            &tool("sherlock", "stdout", "helper_stdout"),
            "pretty",
            &options(),
        )
        .unwrap();
        assert_eq!(result.status, RunStatus::RateLimited);
        assert_eq!(result.findings.len(), 1);
        assert_eq!(result.findings[0].value, "https://github.com/pretty");
    }

    #[test]
    fn runner_reads_persistent_json_report() {
        let result = run_tool(
            &tool("maigret", "json_file", "helper_json"),
            "pretty",
            &options(),
        )
        .unwrap();
        assert_eq!(result.status, RunStatus::Ok, "{}", result.stderr);
        assert_eq!(result.findings.len(), 1);
        assert!(
            result
                .run_dir
                .unwrap()
                .join("reports/report_pretty_simple.json")
                .exists()
        );
    }

    #[test]
    fn runner_enforces_timeout() {
        let mut options = options();
        options.timeout = Some(Duration::from_millis(100));
        let result = run_tool(
            &tool("sherlock", "stdout", "helper_sleep"),
            "pretty",
            &options,
        )
        .unwrap();
        assert_eq!(result.status, RunStatus::Timeout);
        assert!(result.findings.is_empty());
    }

    #[test]
    fn runner_reports_missing_and_invalid_json() {
        let missing = run_tool(
            &tool("maigret", "json_file", "helper_no_json"),
            "pretty",
            &options(),
        )
        .unwrap();
        assert_eq!(missing.status, RunStatus::Error);
        assert!(missing.stderr.contains("Fichier JSON attendu introuvable"));

        let invalid = run_tool(
            &tool("maigret", "json_file", "helper_invalid_json"),
            "pretty",
            &options(),
        )
        .unwrap();
        assert_eq!(invalid.status, RunStatus::Error);
        assert!(invalid.stderr.contains("Fichier JSON illisible"));
    }

    #[test]
    fn runner_honors_nonzero_exit_policy() {
        let mut spec = tool("sherlock", "stdout", "helper_failure");
        let failed = run_tool(&spec, "pretty", &options()).unwrap();
        assert_eq!(failed.status, RunStatus::Error);
        assert_ne!(failed.exit_code, Some(0));
        spec.nonzero_exit_ok = true;
        let accepted = run_tool(&spec, "pretty", &options()).unwrap();
        assert_eq!(accepted.status, RunStatus::Ok);
    }

    #[test]
    fn missing_tool_and_invalid_target() {
        let mut spec = tool("sherlock", "stdout", "helper_stdout");
        spec.command[0] = "this-osintbox-tool-does-not-exist".into();
        let result = run_tool(&spec, "pretty", &options()).unwrap();
        assert_eq!(result.status, RunStatus::NotFound);
        assert!(matches!(
            run_tool(&spec, "--flag", &options()),
            Err(RunError::InvalidTarget(_))
        ));
    }

    #[test]
    fn rate_limit_legend_is_not_a_false_positive() {
        assert!(!looks_rate_limited(
            "[+] Email used, [-] Email not used, [x] Rate limit",
            ""
        ));
        assert!(looks_rate_limited("", "HTTP 429 received from server"));
    }
}
