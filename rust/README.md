# OSINTBox Rust migration

The Python CLI and PySide6 application remain the current user-facing version.
This workspace starts a gradual port of the core so each behavior can be checked
before the Rust implementation takes over.

## Implemented

- `osintbox-core`: target and territory validation with the same return contract,
  accepted values and error messages as `osintbox/validators.py`.
- Tool catalog loading and command construction from the existing YAML schema.
- Rust tests run locally and in the GitHub CI workflow.

## Next components

1. Port subprocess execution and output normalization, then compare against
   recorded local fixtures from Sherlock, Maigret, Holehe and theHarvester.
2. Connect a Rust executable to the existing desktop interface only after the
   CLI behavior and packaged Windows build have been verified.

The external OSINT tools are separate executables. Porting the orchestrator
does not replace those tools or remove their installation requirements.

Run the Rust checks with:

```text
cd rust
cargo fmt --all --check
cargo test --workspace --locked
```
