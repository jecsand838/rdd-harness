---
name: phase-review
description: Independently review live RDD implementation progress and phase-completion evidence, identify correctness and bloat issues, bind findings to exact revisions, and validate final project claims without creating task-level approval gates.
---

# Phase review

Act independently of the implementor. Read the requirements, frozen solution, phase scope, task graph, contracts, raw diff, relevant tests, benchmark protocols, and controller receipts. Read [the review example](references/review-example.md) for a false-positive success claim and a correct outcome.

## Live review

Observe a coherent diff or checkpoint and send focused findings to the orchestrator. State the affected requirement/scenario, file or operation, observed issue, expected result, severity, and a concrete reproduction or reasoning. Check task ordering, approved scope, interface boundaries, duplicate logic, weak assertions, and unsafe async/persistence behavior.

Do not mutate implementor workspaces or silently take over their tasks. Do not demand a formal review after each task. Advisory feedback supports course correction; the formal gate is phase completion.

## Phase acceptance review

Review the exact candidate HEAD and source digest. Re-read the phase's promised outcome without assuming later work will make it true.

1. Check all planned tasks are complete and their evidence is relevant. Verify markers through the controller; absence of text alone proves nothing.
2. Check each required operation is reachable and executes the specified behavior. Registration, generated types, and success-shaped mock outputs are insufficient.
3. Check golden paths and negative/boundary/recovery/concurrency cases appropriate to the phase. Inspect assertions and real boundary coverage. Look for ignored tests, fixed return values, swallowed errors, or a fake database replacing the only persistence acceptance path.
4. Check TDD receipts distinguish expected behavioral RED from infrastructure failure and link to the introduced assertions.
5. Check requirement/spec/contract/plan digests and reproducible generated output. Confirm architecture checks detect forbidden direct calls, not just well-formed schemas.
6. Check cumulative regressions and previously accepted guarantees. If a sealed guarantee was never true, record closure failure and route to specification amendment.
7. Check every due NFR against its defined environment and measurement protocol. Skipped platforms, absent hardware, missing screen-reader evidence, and benchmarks without assertions remain incomplete.
8. Check privacy, capability restrictions, diagnostics, cancellation, recovery, and data migration behavior where relevant. Verify no task content or secret leaked into logs or fixtures.
9. Check additions against their reuse rationale. Flag duplicate business rules, speculative generics, unused APIs, unnecessary dependencies, placeholder operations, and inconsistent documentation.
10. Check PR head, base, checks, and review evidence are current. Invalidate review after rebases, conflict resolution, code changes, or changed verification policy.

## Result

Write the review JSON using the schema accepted by `./rdd review record FILE`. Include the exact phase, HEAD, source digest, reviewer identity, requirement/scenario scope, findings, and disposition fields required by that schema. Do not invent missing machine fields; use the supplied template or `--help`.

An approval asserts that the required evidence supports this phase's claims; it is not a proof of universal correctness. If a required check cannot run, return an environment blocker with the missing evidence. If findings exist, keep the phase open and re-review the repaired candidate. The reviewer never changes a finding to resolved merely because the implementor says it is fixed.

## Project review

Check all phase seals and their linked evidence, final cumulative tests/benchmarks, completed PR policy, requirement coverage, operation availability, unresolved blockers, and source integrity. The controller creates the final validation artifact only after these conditions hold. Preserve the distinction between a complete ready-to-merge PR stack and merged or deployed production software.
