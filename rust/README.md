# OSINTBox Rust migration

The Python CLI and PySide6 application remain the current user-facing version.
This workspace starts a gradual port of the core so each behavior can be checked
before the Rust implementation takes over.

## Implemented

- `osintbox-core`: target and territory validation with the same return contract,
  accepted values and error messages as `osintbox/validators.py`.
- Tool catalog loading and command construction from the existing YAML schema.
- Subprocess execution with timeouts, persistent JSON reports, rate-limit
  detection and preservation of findings produced before a rate-limit warning.
- Normalization for Sherlock, Maigret, Holehe and theHarvester, plus the generic
  fallback and category grouping.
- Sequential queue with per-tool delays, rate-limit retries and backoff, status
  callbacks, deduplicated findings and cancellation between jobs.
- Standalone `osintbox-rs` CLI for catalog tools, with confirmation, streamed job
  statuses, per-tool JSON reports and consolidated JSON/CSV using the Python
  report schema. The catalog is embedded; `--catalog` can override it.
- Rust tests run locally and in the GitHub CI workflow.

## Next components

1. Compare Rust and Python reports from representative real tool runs and
   verify a packaged Windows CLI build.
2. Connect the Rust executable to the existing desktop interface once the
   packaged build has been verified. Dorking still uses the Python path.

The external OSINT tools are separate executables. Porting the orchestrator
does not replace those tools or remove their installation requirements.

Run the Rust checks with:

```text
cd rust
cargo fmt --all --check
cargo test --workspace --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo run -p osintbox-core --bin osintbox-rs -- --help
cargo run -p osintbox-core --bin osintbox-rs -- alice --tool sherlock
```

The CLI writes `results/` and `.osintbox_runs/` relative to its current
directory by default. `--results-dir` selects another export directory.
It launches the same external OSINT programs listed in the catalog; a
confirmation prompt is required unless `--yes` is passed explicitly.
The desktop worker uses the companion `osintbox-rs.exe` beside a packaged
`OSINTBox.exe`, or `OSINTBOX_RUST_CLI` in a source checkout. It receives
newline-delimited events with `--events-json` and requests cancellation
between tools through `--cancel-file`. The Python queue remains available
when the Rust executable is absent. `build_exe.bat` produces both binaries.
