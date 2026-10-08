---
name: plan-phases
description: Partition an RDD task dependency graph into sequential dependency-closed phases with strict tests/deletion/modification/addition/documentation order, honest acceptance, and one stacked PR per phase. Use in preparation and plan review.
---

# Plan phases

Read the actual dependency DAG and verticals before assigning phase numbers. Read [the phase example](references/phase-example.md) for category conflicts, closure, and sealing semantics.

## Formal constraints

Let `u -> v` mean task `v` requires task `u`. Require `phase(u) <= phase(v)`. Every completed phase prefix contains all prerequisites of its tasks.

Within each phase, categories have ranks `tests=0`, `deletion=1`, `modification=2`, `addition=3`, `documentation=4`. Add category barriers so all tasks in a lower rank complete before tasks in a higher rank begin. For an actual same-phase prerequisite require `rank(u) <= rank(v)`. If a later-rank producer must precede an earlier-rank consumer, put them in different phases or fix a false task boundary. Do not relabel the underlying work.

An independent phase's acceptance depends only on the accepted baseline, sealed predecessors, and its own work. Stacked PRs intentionally depend on predecessor branches. Independence does not mean every phase can start from the original repository alone.

## Partition procedure

1. Select an outcome that is useful and reviewable at its phase boundary. Prefer a cohesive behavior and its quality obligations over an arbitrary number of files or tokens.
2. Compute prerequisite closure. Move all required work into this or earlier phases. Include validation, recovery, privacy, diagnostics, accessibility, contracts, integrations, and benchmarks needed for the claimed outcome.
3. Apply category barriers and recheck the graph. Split a phase only at a boundary whose intermediate state is specified and acceptable. Source editing can temporarily break a build inside a phase; that does not authorize unsafe migration execution.
4. Enumerate operations that must work at completion. Enumerate future operations and their allowed unavailable behavior, if the frozen spec permits any. A registered command that returns a placeholder cannot support a current phase acceptance claim.
5. Define concrete gate check IDs and coverage for the phase. Include relevant golden, negative, boundary, interruption, regression, contract, architecture, benchmark, and required manual/platform checks. Determine the actual machine/environment needed before implementation starts.
6. Give each shared file a task-level owner and state its allowed later extensions. Require cumulative regression to preserve previously accepted guarantees.
7. Define recovery and rollback where the phase changes persistent data or deployment behavior. Distinguish a source rollback from database compatibility; they may have different constraints.
8. Assign one branch/PR per phase and the preceding phase as its base. Record how rebases invalidate revision-bound evidence. Do not seal before all local and remote evidence is current.
9. Review every phase by asking: “If all future tasks were cancelled, would this phase's stated outcome and acceptance still be true?” If not, refine the boundary or narrow the claim transparently before freeze.
10. Check the final union: every requirement and operation is fulfilled by the completed plan, and no quality work is indefinitely deferred to a generic cleanup phase.

## No reopening

A seal preserves a phase's accepted scope and evidence. Later planned tasks may modify the same files while maintaining those guarantees. If later work reveals the earlier guarantee was never satisfied, record a closure failure and start a specification amendment. Do not reopen the sealed record, change its acceptance text, or present the repair as unrelated later scope.

Open-phase gate failures are normal repair work while the phase remains open. Preserve strict category order for a repair sweep and rerun the full affected phase gate. A required upstream decision still blocks, even when the phase is not sealed.

## Review scope

Use the independent live reviewer for timely course correction. Use formal review gates at phase completion, not after every task. Task dependency checks, leases, TDD receipts, and task-state transitions are mechanical workflow controls, not separate reviewer approvals.
