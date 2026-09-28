//! Sequential jobs, per-tool pacing and rate-limit retries.

use std::collections::{HashMap, HashSet};
use std::time::{Duration, Instant};

use crate::catalog::ToolSpec;
use crate::runner::{RunError, RunResult, RunStatus, RunnerOptions, run_tool};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum JobStatus {
    Queued,
    Running,
    Retrying,
    Done,
    Failed,
    Timeout,
    NotFound,
    RateLimited,
}

impl JobStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Running => "running",
            Self::Retrying => "retrying",
            Self::Done => "done",
            Self::Failed => "failed",
            Self::Timeout => "timeout",
            Self::NotFound => "not_found",
            Self::RateLimited => "rate_limited",
        }
    }
}

#[derive(Debug)]
pub struct Job {
    pub tool_id: String,
    pub target: String,
    pub status: JobStatus,
    pub result: Option<RunResult>,
    pub attempts: usize,
}

pub struct QueueOptions {
    pub max_retries_on_rate_limit: usize,
    pub backoff_base: Duration,
}

impl Default for QueueOptions {
    fn default() -> Self {
        Self {
            max_retries_on_rate_limit: 1,
            backoff_base: Duration::from_secs(30),
        }
    }
}

#[derive(Debug)]
pub enum QueueError {
    UnknownTool(String),
    Runner(RunError),
}

impl From<RunError> for QueueError {
    fn from(error: RunError) -> Self {
        Self::Runner(error)
    }
}

pub struct QueueCallbacks<C, X> {
    pub on_status_change: C,
    pub should_cancel: X,
}

/// Runs tools one at a time. Cancellation is checked only between jobs, as in
/// the Python queue; a launched subprocess or retry sequence runs to completion.
/// Injectable time and execution functions make pacing/backoff testable without
/// network calls or real sleeping.
pub fn run_queue<R, S, N, C, X>(
    catalog: &[ToolSpec],
    jobs: &[(String, String)],
    options: &QueueOptions,
    mut run: R,
    mut sleep: S,
    mut now: N,
    mut callbacks: QueueCallbacks<C, X>,
) -> Result<Vec<Job>, QueueError>
where
    R: FnMut(&ToolSpec, &str) -> Result<RunResult, RunError>,
    S: FnMut(Duration),
    N: FnMut() -> Duration,
    C: FnMut(&Job),
    X: FnMut() -> bool,
{
    let specs: HashMap<&str, &ToolSpec> = catalog
        .iter()
        .map(|spec| (spec.id.as_str(), spec))
        .collect();
    let mut last_run_at: HashMap<&str, Duration> = HashMap::new();
    let mut completed = Vec::with_capacity(jobs.len());

    for (tool_id, target) in jobs {
        if (callbacks.should_cancel)() {
            break;
        }
        let spec = specs
            .get(tool_id.as_str())
            .ok_or_else(|| QueueError::UnknownTool(tool_id.clone()))?;
        let mut job = Job {
            tool_id: tool_id.clone(),
            target: target.clone(),
            status: JobStatus::Queued,
            result: None,
            attempts: 0,
        };
        (callbacks.on_status_change)(&job);

        let mut accumulated = Vec::new();
        let mut seen = HashSet::new();
        for attempt in 0..=options.max_retries_on_rate_limit {
            job.attempts += 1;
            let min_delay = if spec.min_delay_s.is_finite() && spec.min_delay_s > 0.0 {
                Duration::from_secs_f64(spec.min_delay_s)
            } else {
                Duration::ZERO
            };
            if let Some(previous) = last_run_at.get(tool_id.as_str()) {
                let elapsed = now().saturating_sub(*previous);
                if min_delay > elapsed {
                    sleep(min_delay - elapsed);
                }
            }

            job.status = JobStatus::Running;
            (callbacks.on_status_change)(&job);
            last_run_at.insert(spec.id.as_str(), now());
            let result = run(spec, target)?;
            let rate_limited = result.status == RunStatus::RateLimited;
            for finding in &result.findings {
                let key = (
                    finding.source.clone(),
                    finding.kind.clone(),
                    finding.value.clone(),
                );
                if seen.insert(key) {
                    accumulated.push(finding.clone());
                }
            }
            job.result = Some(result);

            if rate_limited && attempt < options.max_retries_on_rate_limit {
                job.status = JobStatus::Retrying;
                (callbacks.on_status_change)(&job);
                let multiplier = u32::try_from(attempt + 1).unwrap_or(u32::MAX);
                sleep(options.backoff_base.saturating_mul(multiplier));
                continue;
            }
            break;
        }

        let result = job.result.as_mut().expect("at least one attempt");
        result.findings = accumulated;
        job.status = match result.status {
            RunStatus::Ok => JobStatus::Done,
            RunStatus::Error => JobStatus::Failed,
            RunStatus::Timeout => JobStatus::Timeout,
            RunStatus::NotFound => JobStatus::NotFound,
            RunStatus::RateLimited => JobStatus::RateLimited,
        };
        (callbacks.on_status_change)(&job);
        completed.push(job);
    }
    Ok(completed)
}

/// Production adapter for the real subprocess runner and monotonic clock.
pub fn run_queue_live<C, X>(
    catalog: &[ToolSpec],
    jobs: &[(String, String)],
    runner_options: &RunnerOptions,
    queue_options: &QueueOptions,
    on_status_change: C,
    should_cancel: X,
) -> Result<Vec<Job>, QueueError>
where
    C: FnMut(&Job),
    X: FnMut() -> bool,
{
    let start = Instant::now();
    run_queue(
        catalog,
        jobs,
        queue_options,
        |spec, target| run_tool(spec, target, runner_options),
        std::thread::sleep,
        || start.elapsed(),
        QueueCallbacks {
            on_status_change,
            should_cancel,
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::catalog::parse_catalog;
    use crate::normalizers::Finding;
    use serde_json::json;
    use std::cell::{Cell, RefCell};
    use std::rc::Rc;

    fn specs() -> Vec<ToolSpec> {
        parse_catalog(
            r#"
- id: a
  category: username
  desc: test
  command: [a, "{target}"]
  target_type: username
  min_delay_s: 5
- id: b
  category: username
  desc: test
  command: [b, "{target}"]
  target_type: username
"#,
        )
        .unwrap()
    }

    fn result(tool: &str, target: &str, status: RunStatus, findings: Vec<Finding>) -> RunResult {
        RunResult {
            tool_id: tool.into(),
            target: target.into(),
            status,
            exit_code: Some(0),
            stdout: String::new(),
            stderr: String::new(),
            findings,
            run_dir: None,
        }
    }

    fn finding(value: &str) -> Finding {
        Finding {
            source: "maigret".into(),
            category: "username".into(),
            kind: "social_profile".into(),
            value: value.into(),
            confidence: "high".into(),
            raw: json!({}),
        }
    }

    #[test]
    fn status_transitions_and_result_order() {
        let seen = RefCell::new(Vec::new());
        let jobs = vec![("a".into(), "alice".into()), ("b".into(), "bob".into())];
        let completed = run_queue(
            &specs(),
            &jobs,
            &QueueOptions::default(),
            |spec, target| Ok(result(&spec.id, target, RunStatus::Ok, vec![])),
            |_| {},
            || Duration::ZERO,
            QueueCallbacks {
                on_status_change: |job: &Job| {
                    seen.borrow_mut().push((job.tool_id.clone(), job.status))
                },
                should_cancel: || false,
            },
        )
        .unwrap();
        assert_eq!(
            completed
                .iter()
                .map(|job| job.target.as_str())
                .collect::<Vec<_>>(),
            ["alice", "bob"]
        );
        assert_eq!(completed[0].attempts, 1);
        assert_eq!(
            seen.into_inner(),
            [
                ("a".into(), JobStatus::Queued),
                ("a".into(), JobStatus::Running),
                ("a".into(), JobStatus::Done),
                ("b".into(), JobStatus::Queued),
                ("b".into(), JobStatus::Running),
                ("b".into(), JobStatus::Done),
            ]
        );
    }

    #[test]
    fn per_tool_delay_and_backoff_use_injected_clock() {
        let clock = Rc::new(Cell::new(Duration::ZERO));
        let sleeps = RefCell::new(Vec::new());
        let attempts = Cell::new(0);
        let options = QueueOptions {
            max_retries_on_rate_limit: 2,
            backoff_base: Duration::from_secs(10),
        };
        let jobs = vec![("a".into(), "alice".into()), ("a".into(), "bob".into())];
        let sleeping_clock = Rc::clone(&clock);
        let reading_clock = Rc::clone(&clock);
        let completed = run_queue(
            &specs(),
            &jobs,
            &options,
            |spec, target| {
                let count = attempts.get() + 1;
                attempts.set(count);
                let status = if count <= 2 {
                    RunStatus::RateLimited
                } else {
                    RunStatus::Ok
                };
                Ok(result(&spec.id, target, status, vec![]))
            },
            |duration| {
                sleeps.borrow_mut().push(duration);
                sleeping_clock.set(sleeping_clock.get() + duration);
            },
            || reading_clock.get(),
            QueueCallbacks {
                on_status_change: |_: &Job| {},
                should_cancel: || false,
            },
        )
        .unwrap();
        assert_eq!(completed[0].attempts, 3);
        assert_eq!(completed[0].status, JobStatus::Done);
        assert_eq!(
            sleeps.into_inner(),
            [
                Duration::from_secs(10),
                Duration::from_secs(20),
                Duration::from_secs(5)
            ]
        );
    }

    #[test]
    fn retrying_is_distinct_and_findings_survive_retry() {
        let seen = RefCell::new(Vec::new());
        let calls = Cell::new(0);
        let jobs = vec![("b".into(), "alice".into())];
        let completed = run_queue(
            &specs(),
            &jobs,
            &QueueOptions::default(),
            |spec, target| {
                calls.set(calls.get() + 1);
                let findings = if calls.get() == 1 {
                    vec![finding("https://x/alice")]
                } else {
                    vec![]
                };
                Ok(result(&spec.id, target, RunStatus::RateLimited, findings))
            },
            |_| {},
            || Duration::ZERO,
            QueueCallbacks {
                on_status_change: |job: &Job| seen.borrow_mut().push(job.status),
                should_cancel: || false,
            },
        )
        .unwrap();
        assert_eq!(
            seen.into_inner(),
            [
                JobStatus::Queued,
                JobStatus::Running,
                JobStatus::Retrying,
                JobStatus::Running,
                JobStatus::RateLimited
            ]
        );
        assert_eq!(
            completed[0].result.as_ref().unwrap().findings,
            [finding("https://x/alice")]
        );
        assert_eq!(completed[0].attempts, 2);
    }

    #[test]
    fn deduplicates_findings_across_attempts() {
        let jobs = vec![("b".into(), "alice".into())];
        let completed = run_queue(
            &specs(),
            &jobs,
            &QueueOptions::default(),
            |spec, target| {
                Ok(result(
                    &spec.id,
                    target,
                    RunStatus::RateLimited,
                    vec![finding("https://x/alice")],
                ))
            },
            |_| {},
            || Duration::ZERO,
            QueueCallbacks {
                on_status_change: |_: &Job| {},
                should_cancel: || false,
            },
        )
        .unwrap();
        assert_eq!(completed[0].result.as_ref().unwrap().findings.len(), 1);
    }

    #[test]
    fn successful_retry_keeps_earlier_findings() {
        let calls = Cell::new(0);
        let jobs = vec![("b".into(), "alice".into())];
        let completed = run_queue(
            &specs(),
            &jobs,
            &QueueOptions::default(),
            |spec, target| {
                calls.set(calls.get() + 1);
                if calls.get() == 1 {
                    Ok(result(
                        &spec.id,
                        target,
                        RunStatus::RateLimited,
                        vec![finding("https://x/alice")],
                    ))
                } else {
                    Ok(result(
                        &spec.id,
                        target,
                        RunStatus::Ok,
                        vec![finding("https://x/bob")],
                    ))
                }
            },
            |_| {},
            || Duration::ZERO,
            QueueCallbacks {
                on_status_change: |_: &Job| {},
                should_cancel: || false,
            },
        )
        .unwrap();
        assert_eq!(completed[0].status, JobStatus::Done);
        assert_eq!(
            completed[0].result.as_ref().unwrap().findings,
            [finding("https://x/alice"), finding("https://x/bob")]
        );
    }

    #[test]
    fn different_tools_do_not_share_delay() {
        let sleeps = RefCell::new(Vec::new());
        let jobs = vec![("a".into(), "alice".into()), ("b".into(), "alice".into())];
        run_queue(
            &specs(),
            &jobs,
            &QueueOptions::default(),
            |spec, target| Ok(result(&spec.id, target, RunStatus::Ok, vec![])),
            |duration| sleeps.borrow_mut().push(duration),
            || Duration::ZERO,
            QueueCallbacks {
                on_status_change: |_: &Job| {},
                should_cancel: || false,
            },
        )
        .unwrap();
        assert!(sleeps.into_inner().is_empty());
    }

    #[test]
    fn cancellation_only_between_jobs() {
        let calls = Cell::new(0);
        let jobs = vec![("a".into(), "alice".into()), ("b".into(), "bob".into())];
        let completed = run_queue(
            &specs(),
            &jobs,
            &QueueOptions::default(),
            |spec, target| {
                calls.set(calls.get() + 1);
                Ok(result(&spec.id, target, RunStatus::Ok, vec![]))
            },
            |_| {},
            || Duration::ZERO,
            QueueCallbacks {
                on_status_change: |_: &Job| {},
                should_cancel: || calls.get() >= 1,
            },
        )
        .unwrap();
        assert_eq!(completed.len(), 1);
        assert_eq!(calls.get(), 1);
    }

    #[test]
    fn maps_terminal_statuses() {
        for (run_status, expected) in [
            (RunStatus::Error, JobStatus::Failed),
            (RunStatus::Timeout, JobStatus::Timeout),
            (RunStatus::NotFound, JobStatus::NotFound),
            (RunStatus::RateLimited, JobStatus::RateLimited),
        ] {
            let jobs = vec![("b".into(), "alice".into())];
            let options = QueueOptions {
                max_retries_on_rate_limit: 0,
                ..QueueOptions::default()
            };
            let completed = run_queue(
                &specs(),
                &jobs,
                &options,
                |spec, target| Ok(result(&spec.id, target, run_status, vec![])),
                |_| {},
                || Duration::ZERO,
                QueueCallbacks {
                    on_status_change: |_: &Job| {},
                    should_cancel: || false,
                },
            )
            .unwrap();
            assert_eq!(completed[0].status, expected);
        }
    }
}
