---
name: implementation-workflow
description: Execute a frozen RDD phased backlog using TDD, strict task-category order, parallel isolated implementors, an independent live reviewer, phase-only acceptance gates, and one stacked PR per phase. Use as stage three or to resume an active implementation goal.
---

# Implementation workflow

Inspect I0–I5 through `workflow nodes`; their progress derives from the existing native goal, task leases, category barriers, phase gates, PRs and seals. Do not create a second task ledger or submit a caller-authored passed flag. The continuous reviewer compares each coherent integration snapshot and significant check result against the frozen plan and contracts, records live findings and verifies corrections; batch review cannot substitute for ongoing steering.

Read `AGENTS.md`, `docs/harness/workflow-guide.md`, `docs/harness/artifact-guide.md`, and the configured goal prompt. The short goal is the orchestration objective; this skill is its procedure. Do not expand the objective by pasting all requirements or this skill into it. Use the repository's launcher and command reference for supported goal-mode invocation.

## Establish the active baseline

Run `./rdd status` and `./rdd doctor`. Validate the frozen specification, canonical contracts, fully hydrated plan, every primary/secondary task projection, accepted preparation gate, and accepted predecessor evidence. P01 must start from the exact gate-accepted preparation commit; later phases start from the preceding sealed head. Resume from durable controller state, not chat memory. Reconcile existing branches and PRs before creating them again.

Requirements and frozen specifications are immutable in this workflow. The task/phase graph and acceptance criteria are frozen. The controller owns transitions and evidence. Never edit state JSON, generated markers, historical evidence, evaluator code, or frozen manifests to manufacture progress.

## Allocate roles and write ownership

Use the configured orchestrator, large implementor, small implementor, and independent reviewer roles. The requested model allocation is an account-specific preference; test availability and supported effort levels using the installed Codex runtime. A model name in configuration does not establish access. If the configured runtime cannot provide a required role, report the missing capability; do not silently claim equivalent multi-agent review.

Delegate a coherent large target to the large implementor. Use the smaller implementor for bounded edits with a clear oracle, such as a narrowly defined documentation or mapping change. Choose by dependency surface and ambiguity, not just line count. Each worker receives the already groomed full primary task packet, all local work sites, allowed write paths, predecessor capabilities, relevant contract/spec slices, expected evidence, category, phase and verticals. Do not ask an implementor to discover missing scope or refine an unfinished plan.

Use isolated branches/worktrees or the runtime's equivalent. Never assign overlapping write paths concurrently. The orchestrator owns shared configuration, integration, task leasing, phase branches, and PR reconciliation. The independent live reviewer reads diffs and evidence during work, sends actionable findings to the orchestrator, and does not mutate implementor workspaces. Live feedback does not create task-level review gates.

## Execute each phase

1. Begin only when the controller identifies the phase as ready. Create its branch from the sealed predecessor revision or baseline. Keep one stable branch and one PR identity per phase.
2. Execute **all `tests` tasks first**. Add the phase's required behavioral tests and fixtures. For greenfield work, the explicitly planned test task may also establish test/build infrastructure and the minimal buildable application entry scaffold needed to reach the real boundary; it must not implement product behavior. Use the already qualified generated signatures. A typed explicit not-implemented boundary stub can drive a failing behavioral assertion, while a missing executable cannot. Every tests task, including the first scaffold task, still needs behavioral RED; no green-bootstrap or compile-error exception exists. Later planned modification/addition tasks replace the stubs with real behavior, and no stub can satisfy product acceptance. Run the tests and retain expected RED evidence: assertions fail because the required behavior is absent or incorrect. Match actual assertion/panic diagnostics, not an expected-error phrase merely echoed as a source line in an unrelated traceback. A missing executable, network failure, invalid invocation, or unrelated build failure is an environment/setup issue. If a new interface initially cannot compile, treat that result as a setup failure. Establish the permitted scaffold, then obtain actual behavioral RED before completing the tests task. Do not claim a compiler error proves a business rule.
3. Execute **`deletion`**, then **`modification`**, then **`addition`**, then **`documentation`** tasks, respecting all prerequisites within each category. The controller's ready queue is authoritative. Do not start a later category while unresolved planned tasks remain in an earlier category. Additions must retain their approved reuse rationale.
4. Keep short feedback loops: implement the smallest change that satisfies the current failing behavior; rerun affected tests; refactor while keeping established behavior. Do not mock away the required persistence, command dispatch, authorization, or recovery boundary in the only acceptance test. Unit tests complement real integration checks.
5. Record completion evidence and reconcile markers through the controller. A worker's statement is a progress signal, not acceptance proof. Include exact relevant revision, command, output, scenario coverage, and artifact digests. Never record success from a skipped test, disabled assertion, empty suite, or unrelated fixture. Commit controller-generated marker cleanup after each completed task before claiming or integrating more work; task completion records durable state before projection cleanup.
6. Integrate disjoint worker commits sequentially on the phase branch, rerun the affected checks, and provide the reviewer current revision context. Keep tests, benchmarks, and evaluators within the frozen plan's meaning. If a test is demonstrably wrong, pause and route the conflict to the proper upstream stage; do not relax the oracle.
7. When planned tasks are complete, run the **phase completion gate** once against a concrete candidate. It includes cumulative regression, phase acceptance, benchmark protocols, exact contracts/generated outputs, operation availability, architecture boundaries, diagnostics/privacy, accessibility/platform evidence when due, task/marker consistency, and bloat/reuse review. Gate failures keep this phase open.
8. Repair findings within the still-open phase using `./rdd task reopen TASK_ID --reason TEXT` for affected existing tasks, including the test task when needed. Reopening invalidates current review/gate evidence and cannot add scope or reopen a sealed phase. Preserve the requested category order in a repair sweep: failing tests first, then deletion/modification/addition/documentation as applicable. Do not rewrite the frozen plan silently. A correction that changes scope, architecture, contract, acceptance meaning, or a sealed guarantee is a blocker requiring a new specification run.
9. Create or update the phase PR using the configured GitHub adapter. Its base is the preceding phase branch; the first phase targets the configured integration branch. Obtain CI and independent reviewer evidence for the exact PR head. After any rebase, conflict resolution, or change, invalidate affected gate evidence and rerun it. A passing ancestor SHA is insufficient.
10. Seal only after the controller accepts phase evidence, the PR's configured completion state, the independent review, and the exact revision. A closed phase is immutable history. Planned later extensions may change the same files while preserving accepted guarantees.

## Blockers and stopping behavior

- **Frozen specification/planning defect:** Record a critical harness regression with origin/detection stage, affected IDs, exact candidate and evidence. Stop affected execution; repair the preventive control and add a reproducing regression before a fresh trial. Do not normalize repeated amendments or edit contracts to fit convenient code. Intentional user requirement changes retain the amendment workflow.
- **Sealed-phase defect:** Use `./rdd block --kind closure --reason TEXT`. Preserve the stack and evidence. Start an amendment through specification; never conceal the fix in a later phase.
- **Environment/credentials/required hardware unavailable:** Record a resumable environment blocker with the exact failing command and needed capability. Do not convert missing evidence to success.
- **No progress, budget exhaustion, worker failure:** Save checkpoints, release or expire leases, preserve worktree/PR identities, and resume safely. Do not spin indefinitely or silently drop tasks.

## Final goal

Run `./rdd gate project` to validate completion. There must be no remaining primary/secondary task packets or unresolved task states, every golden scenario must have an explicit passing executed result, and there must be no unresolved review findings, no failing or missing required tests or benchmarks, no unfulfilled operation or requirement coverage, no incomplete phase PR, and a project-level validation artifact bound to the final revision and all sealed phase evidence.

The default PR completion policy keeps all PRs open, validated, and ready for the user to merge. If a different policy was explicitly configured, honor it. Do not publish releases, merge, or deploy merely to make the word “complete” true.

Report exact revisions, phase PR links, evidence locations, and any documented environment limitation. A blocked run is an honest partial result, never a production-ready claim.

Read `../phase-review/SKILL.md` for acceptance rules and [the implementation example](references/implementation-example.md) for RED evidence, live feedback, and resumable failure handling.
