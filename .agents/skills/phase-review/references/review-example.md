# Worked phase review

A phase claims that backup restore atomically replaces the collection. The test suite reports success, and all inline markers disappeared.

## Independent inspection

The reviewer opens the test and finds that it restores a backup of the same dataset already in storage. A no-op implementation would pass. It also finds that an implementor manually removed a marker while the task ledger remains unresolved.

Correct findings identify the restoration requirement, exact test/diff location, the weak oracle, and the task-state mismatch. The phase remains open. Missing markers do not establish completion.

## Repair while open

Reopen the applicable test and implementation tasks using controller commands. Use two distinguishable valid datasets, assert full replacement, and exercise malformed input and interruption under the specified fault model. Preserve fixed scenario meaning; a new assertion clarifies that meaning rather than changing the requirement. Rerun affected checks, obtain and record independent review bound to the new HEAD, then rerun the phase gate.

If the frozen specification never defined replacement versus merge, that is a specification blocker. The reviewer cannot choose one during implementation merely to finish the phase.

## Evidence that still cannot pass

- A benchmark with timings but no evaluator for the required percentile and threshold.
- A platform matrix showing Linux success while required macOS checks are skipped.
- A command registered with an unimplemented handler.
- A contract compilation check that never compiles a consumer against the declared signature.
- A review attached to the previous PR head before conflict resolution.
- A test helper that catches every error and returns success.

## Review record

Use the actual JSON schema and record exact HEAD, source digest, reviewer identity, scope, findings, and conclusion. Preserve unresolved findings. The final project review checks the union of all phase claims and current regression evidence, rather than merely counting the number of approved PRs.

The objective is a defensible statement about the required behavior in its defined environments. It is not an unbounded guarantee that no defect can ever exist.
