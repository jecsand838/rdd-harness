---
name: create-test-suite
description: Create an executable requirement-linked test suite with independent oracles, isolated fixtures, deterministic failure injection, runnable targets, and evidence capture. Use for new acceptance/integration/security/recovery suites or phase-first TDD test tasks.
---

# Create a test suite

Read the frozen scenario inventory and implementation matrix. Implement the assigned tests before production changes in the phase. Do not invent a smaller interpretation of a requirement because its evidence is difficult to collect.

## Procedure

1. Map each scenario to requirement IDs, preconditions, input, action, expected outcome, and an independent oracle. Include golden paths plus specified negative, boundary, concurrency, recovery, privacy, and platform cases.
2. Choose the smallest real boundary that can establish the claim. Use domain tests for pure invariants, actual Turso integration for persistence, packaged Tauri journeys for desktop behavior, and the designated reference environments for benchmarks.
3. Register executable targets and exact commands. Confirm discovery by listing/running tests; a source file or folder is not sufficient. Keep deterministic seeds, fixtures, clocks, temp directories, and cleanup owned by the suite.
4. Establish meaningful red evidence. Record the expected behavioral failure and distinguish infrastructure failure, unsupported environment, compile failure, skip, and pass. When the phase intentionally exposes an incomplete contract stub, document that separately from the behavior assertion.
5. Add fault controls at approved instrumentation boundaries and keep them out of release packages. Synchronize process-kill cut points, commit delays, filesystem faults, and queue admission deterministically.
6. Capture results with revision, environment, command, fixture identity, timestamps, outcome, and raw-log/artifact digests. Let the harness record completion only after evidence validates; never mark a requirement passed by removing an inline task.
7. Run focused feedback while implementing. Execute complete gates only at phase completion. Keep unexplained failures and required unavailable platforms as blockers; do not blanket-retry or silently skip them.

## Handoff

Provide suite discovery proof, red/final evidence, scenario coverage, required environments, and instrumentation exclusion checks. Preserve the frozen oracle unless specification is rerun. Read [suite design](references/suite.md) for concrete examples and benchmark rules.
