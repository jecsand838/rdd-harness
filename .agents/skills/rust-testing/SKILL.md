---
name: rust-testing
description: Design or extend idiomatic Rust unit, integration, property, and failure tests tied to requirement scenarios. Use during phase TDD, test organization, regression work, persistence validation, or test-quality review; keep packaged Tauri and benchmark evidence separate from unit results.
---

# Rust testing

Read the frozen scenario, expected result, fixture digest, and failure model. Write tests that could fail for a plausible defect. Do not derive expected values from production code under test.

## Procedure

1. Put fast invariant tests beside their owner under `#[cfg(test)]`. Put public-boundary integration tests in a real Cargo target. A virtual workspace's root `tests/` directory is not automatically discovered; register an acceptance crate or `[[test]]` targets in specification.
2. Establish the phase's red baseline before production changes. Run new tests and record why they fail. An accidental missing import is not behavioral red evidence. Distinguish intentional contract-conforming incompleteness from harness/setup failure.
3. Isolate fixtures: temporary directories, independent database files, owned runtime state, fixed clocks, and deterministic seeds. Never reuse a user's database or depend on test order.
4. Use table-driven tests for exact boundaries. Use properties for invariants with an independent oracle; retain explicit regressions, seeds, and minimized failing inputs without sensitive data.
5. Exercise actual embedded Turso for persistence. Fakes cannot establish disk restart, commit uncertainty, locking, migration, or atomic restore semantics.
6. Control scheduling with barriers, channels, and failpoints. Use paused Tokio time for timer logic; inject calendar time separately. Avoid sleeps as synchronization or test timeouts as performance benchmarks.
7. Keep functional, security, accessibility, packaged-runtime, crash, and benchmark evidence identifiable. A mocked browser journey cannot establish Tauri IPC. Retrying does not erase an unexplained failure.

## Phase handoff

Record scenario IDs, commands, baseline/final results, fixture versions, environment, and limitations. Run targeted checks during development and the full configured gate at phase completion. Never weaken an assertion, skip a required platform, or raise a budget to pass.

Read [test patterns](references/patterns.md) for examples, Cargo discovery, and current platform caveats.
