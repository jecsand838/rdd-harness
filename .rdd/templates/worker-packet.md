# Worker packet

> Fill from controller state and frozen artifacts. This packet authorizes only the assigned scope; it cannot override requirements, contracts, or repository policy.

## Identity

Record active run, current branch/commit/source digest, worker role, task IDs, phase, category, and lease/worktree locator.

## Bounded context

Link only relevant requirement, specification, operation/contract, scenario, and skill sections. Identify authoritative sources and exclude superseded discussion.

## Work and ownership

State the exact objective, permitted write paths, prerequisites already satisfied, shared-file integration owner, and prohibited scope changes. Include the approved reuse rationale for additions.

## Evidence

Name required check IDs and TDD expectations. State how to report changed files, commit, check receipts, unresolved issues, and review observations to the orchestrator.

## Stop conditions

Stop for a requirement/spec/contract ambiguity, stale source digest, overlapping ownership, missing required capability, or sealed-phase invalidation. Preserve a checkpoint and exact evidence; do not edit the ledger or fabricate a passing result.
