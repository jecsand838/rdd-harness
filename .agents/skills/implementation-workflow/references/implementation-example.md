# Worked implementation evidence example

The examples below are illustrative command output, not successful checks for this repository.

## Behavioral RED

A new test asserts that cancelling an already cancelled reservation preserves stock. Its compiled execution reports an assertion failure: expected 3, got 5. The associated check is configured with the expected failure pattern and scenario ID. Capture the failing check receipt before implementation.

The following do not establish behavioral RED:

- `cargo: command not found`.
- A crate download timeout.
- A syntax error in an unrelated module.
- A test command whose filter ran zero tests.
- A test process killed by an out-of-memory condition.

A compile failure can show that a signature is absent, but it is a setup diagnostic and never accepted task RED. It does not show that a business rule's assertion ran. Obtain a runnable behavioral failure before claiming the rule was driven by that test.

## Live review without a task gate

A worker modifies cancellation logic. The live reviewer notices that an in-memory mutex protects only one process while the approved storage boundary must enforce the invariant. It sends the requirement/scenario and diff location to the orchestrator. The orchestrator redirects the worker within its approved scope. No separate approval transition occurs for that task.

If the required atomic operation is missing from the frozen contract, the finding becomes a specification blocker. The worker cannot fix that by inventing a new method.

## Open-phase repair

After phase completion checks, the reviewer finds an uncovered relevant boundary case. While the phase is open, reopen the existing task using `./rdd task reopen T101 --reason 'Boundary case within the accepted task scope'`. Reopen the related test task too when a new regression assertion is required. Follow tests, deletion, modification, addition, documentation order among reopened work. Refresh gate and reviewer evidence for the new revision.

Do not use reopening to add a new product feature or change the oracle. Do not reopen a task in a sealed phase.

## Resume after interruption

A worker disappears after committing code but before task completion. Run status/resume, inspect the task lease and worktree, verify the commit's allowed paths, integrate it through the controller, and rerun relevant checks. Do not create a duplicate PR or trust the worker's last prose message as evidence.

If the next ready queue is empty while unresolved tasks remain, inspect missing predecessors and leases. If the frozen graph itself is wrong, record a planning blocker; do not edit the SQLite ledger manually.

## Final acceptance

Tests green is only one condition. The phase still requires current independent review, exact contract/source integrity, due NFR evidence, unresolved-marker reconciliation, and the configured PR state. A pending required macOS check cannot be replaced by a Linux pass. The project artifact must disclose the actual covered environments and acceptance policy.
