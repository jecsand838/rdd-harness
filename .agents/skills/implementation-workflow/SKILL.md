---
name: implementation-workflow
description: Execute a frozen RDD phased backlog using TDD, strict task-category order, parallel isolated implementors, an independent live reviewer, phase-only acceptance gates, and one stacked PR per phase. Use as stage three or to resume an active implementation goal.
---

# Implementation workflow

Read `AGENTS.md` and the [workflow command sequence](../../../docs/harness/workflow-guide.md#stage-three-implementation). Inspect I0–I5 through `workflow nodes`; their state derives from tasks, leases, gates and seals. Use `./rdd status`, `./rdd doctor`, the frozen plan and the short native Goal objective. Do not create a second task ledger or copy all guidance into the objective.

## Establish the active baseline

Verify frozen requirements/specification/contracts/plan, task projections and accepted preparation/predecessor evidence. P01 starts at the exact prepared commit; later phases start at the preceding sealed head. Reconcile existing branches/PRs before creating them. Preserve frozen acceptance meaning, evaluator policy and historical evidence.

Use [domain-boundaries](../domain-boundaries/SKILL.md) for frozen module obligations and [context-integrity](../context-integrity/SKILL.md) for bounded packets. Delegate exact named profiles under the [runtime roster](../../../docs/harness/codex-runtime.md#runtime-contract), with no silent model substitution. Complex implementors may take large or small tasks; light implementors receive only small unambiguous scope. Requested settings do not attest backend execution.

The coordinator owns leases, integration and shared configuration. Workers own disjoint declared writes in isolated worktrees and preserve every task packet. Give them the full primary packet, local sites, producers, relevant contract/spec slices and required evidence; missing scope returns upstream rather than being groomed by implementors. Keep a read-only reviewer active under [phase-review](../phase-review/SKILL.md), observing coherent integrations and significant checks.

## Execute each phase

1. Begin only the controller-selected phase. Claim tasks from `./rdd next`, retaining stable branch/PR identity and exact lease baselines.
2. Complete **tests → deletion → modification → addition → documentation** in order, with dependency closure. Follow [behavioral RED](../../../docs/harness/evidence-guide.md#behavioral-red): tests must execute real assertions. Explicitly planned nonbehavioral scaffolding may enable initial compilation; missing tools and compiler errors are not RED. Later production tasks replace stubs. Preserve real persistence/IPC coverage and independent oracles.
3. Integrate worker commits sequentially, run the required checks on the integrated candidate, and record controller completion. A worker's prose is a pointer to evidence. Commit controller-generated all-site cleanup before another claim/integration; reconcile interrupted cleanup instead of deleting unfinished markers manually.
4. Keep feedback loops focused: implement the smallest scoped correction, rerun affected checks, refactor without weakening tests. Preserve reuse rationale and reject speculative additions. Wrong acceptance meaning returns to specification.
5. For an open-phase repair use `task reopen --reason` on existing tasks, including regression-test tasks. Preserve category order and scope. Recorded finding IDs authorize intermediate correction/completion; a new finding needs renewed enrollment. Independent resolution remains mandatory before phase/project acceptance. Packet restoration is preflighted and recoverable through reconciliation, including consumed selectors.
6. At completion commit the concrete candidate, run cumulative checks and obtain exact-source independent review. The [phase gate](../phase-review/SKILL.md#phase-acceptance-review) includes required operation, contract, architecture, privacy, accessibility, benchmark and platform evidence. All project checks must be allocated to phases and therefore run by the final cumulative gate.
7. Gate, publish/update the phase's single PR, verify checks/review at its actual head/base, then seal. Changed revisions invalidate affected evidence. Keep closed heads/bases immutable; planned later extensions must preserve accepted guarantees. Merging/releasing remains separately authorized.

## Blockers and completion

Use the [repair/recovery commands](../../../docs/harness/workflow-guide.md#repairs-and-interruptions). Record specification/planning escapes with origin/detection stage, affected IDs, exact candidates and evidence; stop dependent work and require a reproducing regression for preventive-control repair. A sealed defect is a closure failure, never an unrelated later task. Missing tools, credentials, hardware, review or budget remain distinct blockers. Preserve worktrees and export checkpoints; do not spin, drop tasks or manufacture results.

After every phase is sealed, run `./rdd gate project`. Completion requires exact frozen inputs, all tasks evidenced, no packets/shells outstanding, explicit executed golden results, required checks/platform evidence, zero unresolved findings, a currently verified PR stack and final validation/checkpoint artifacts. Historical seal reviews cannot clear later findings. Report exact revisions, PRs, evidence and environmental limits; harness tests or a stopped Goal never establish application success.

Read [the implementation example](references/implementation-example.md) for RED, live feedback and resumable failure handling.
