# Test patterns

## Test outcomes rather than mirrors

Bad:

```rust
#[test]
fn search_works() {
    let expected = production_filter(&fixture(), "alpha");
    assert_eq!(production_filter(&fixture(), "alpha"), expected);
}
```

Better illustrative boundary test:

```rust
#[test]
fn fr_012_search_includes_notes_and_retains_diacritics() {
    let tasks = vec![
        task("a", "Unrelated", "Alpha"),
        task("b", "ALPHA", ""),
        task("c", "Álpha", ""),
    ];
    assert_eq!(search_ids(&tasks, " alpha "), vec!["a", "b"]);
}
```

Here `task` and `search_ids` stand for the approved fixture builder and boundary. Expected identities come independently from requirements. Add canonical Unicode equivalence, empty queries, punctuation, and deterministic ordering separately.

## Make restart meaningful

Bad: write through a mock and assert the same in-memory mock contains the value.

Better persistence sequence:

1. Allocate a fresh temporary application-data location.
2. Open the pinned Turso engine through the production adapter.
3. Submit a command and await committed acknowledgment.
4. Drop every handle or exit the child process, as the scenario requires.
5. Reopen using a fresh adapter/process and compare every required field to independent expectations.
6. Confirm no remote service or credential was required.

For abrupt termination, the parent driver owns an acknowledgment ledger and explicit child checkpoints before commit, during pending commit, and after acknowledgment. Run the specified repetitions per platform. Validate sequential history, not only row counts. Avoid second-process inspection while a single-process database is open.

## Register virtual-workspace tests

An illustrative approved layout could be:

```text
modules/task-domain/src/lib.rs
modules/task-storage/tests/reopen.rs
tests/acceptance/Cargo.toml
tests/acceptance/tests/task_lifecycle.rs
```

Register the acceptance package as a workspace member. A directory alone is not a runnable suite. Avoid importing the native UI runtime into pure domain tests merely for fixture convenience.

## Distinguish clocks

Use `#[tokio::test(start_paused = true)]` with `test-util` for deterministic timer tests. Await readiness before advancing time. Inject a calendar source for local date, time-zone, and wall-clock corrections. Run P1/P2/P3 with real clocks and release packages, preserving raw samples and the required percentile method.

## Tauri automation as of 2026-10-07

The official guide describes `@wdio/tauri-service` with an embedded provider on Windows, Linux, and macOS. Direct `tauri-driver` has different platform limits. Pin the chosen route; do not assume all historic platform limitations still apply.

Embedded WebDriver and backend-access/mocking plugins belong only in instrumented builds. Release packages must exclude automation servers and mocks, and receive normal installation, restricted-native-operation, offline, and user-journey checks. Record tested revision and package digests.

## Primary references

Checked 2026-10-07.

Select primary sources tagged `rust-testing` in the [engineering source catalog](../../../../.rdd/sources/engineering.json).
