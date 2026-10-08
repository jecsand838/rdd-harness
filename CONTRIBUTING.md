# Refining the harness

Use a dedicated change before specification freeze to alter controller policy, schemas, skill guidance, model roles or CI. Keep requirements changes explicit and preserve stable requirement IDs. Run `./rdd selftest`; qualify actual Rust/Buf contract generation when changing the generator.

Use argv-based subprocess calls, bounded time/output, exact source identities and explicit environment blockers. Keep external protocol fixtures labeled; a test double cannot attest real GitHub, Codex, compiler, desktop or reference-device behavior.

Add tests only for meaningful remaining risks: state transitions, write-scope escapes, lock/receipt drift, conflicting dependencies, evidence lies and interruption boundaries. Do not mirror trivial implementation details or inflate test counts.

Do not commit local credentials, user databases, worker runtime state or raw private application data. Preserve run evidence using the supported checkpoint export.
