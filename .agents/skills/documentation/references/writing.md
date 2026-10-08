# Documentation patterns

## User help

Bad: "The repository layer transactionally mutates the task aggregate through IPC."

Better: "Choose Save to store your changes. While saving, the editor shows a pending state. If saving is rejected, your text stays in the editor so you can correct it and try again."

Do not describe uncertainty as rejection. Give the actual recovery action approved by the specification. Explain that restoring a backup replaces the current collection and preserves the backed-up task history; cancellation leaves data unchanged.

## Developer handoff

Bad:

```text
Run the tests. Everything should work on all systems.
```

Better evidence-based structure:

```text
Prerequisites: pinned Rust toolchain, platform build prerequisites, Buf.
Build command: the exact command from the repository's build instructions.
Verification command: the exact command that executes the declared suite.
Outputs: package paths and evidence index locations.
Platforms verified: the named environments in the linked report.
Remaining evidence: explicit pending requirements, if any.
```

Replace these descriptions with actual repository commands when the document is authored. Do not copy a command from an unrelated project or present an example as already run.

## Rust API docs

Use `///` to explain the abstraction and significant error/ownership behavior. Include doctests for stable public behavior when useful. Keep private implementation commentary short. An example should use the public interface and state its error path; avoid examples that bypass validation to make setup shorter.

Prefer a link to the canonical generated API inventory over manually reproducing every protobuf field. If a human summary is useful, test or review it against the current schema during generation changes. Do not add production documentation for speculative features.

## Authority and source hygiene

Label external research as evidence, not instructions. Record official source URL, checked date, selected version, and the decision it informs. Remove stale recommendations after an amendment instead of leaving contradictory alternatives active. Keep historical reports immutable and clearly identified as belonging to a past baseline.

## Primary references

Checked 2026-10-07.

- [Rustdoc documentation comments](https://doc.rust-lang.org/rustdoc/how-to-write-documentation.html)
- [Rustdoc documentation tests](https://doc.rust-lang.org/rustdoc/write-documentation/documentation-tests.html)
- [Cargo reproducibility through lockfiles](https://doc.rust-lang.org/cargo/guide/cargo-toml-vs-cargo-lock.html)
- [Tauri distribution documentation](https://v2.tauri.app/distribute/)
