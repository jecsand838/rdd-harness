---
name: phase-review
description: Continuously review all three RDD workflows, steer corrections, and independently review exact-candidate stage and phase acceptance. Bind findings to exact candidates, verify corrections, and validate project claims without task-level approval gates.
---

# Phase review

Follow [AGENTS.md](../../../AGENTS.md) for authority and critical-regression routing. Use the read-only `rdd_reviewer` profile independently of candidate authors. Read the requirements, frozen solution, phase scope, task graph, contracts, raw diff, relevant tests, benchmark protocols, and controller receipts. Read [the review example](references/review-example.md) for a false-positive success claim and a correct outcome.

## Specification and preparation reviews

Two distinct reviewer sessions provide `semantic` and `execution` perspectives. Neither reviewer may be a registered author of the artifacts it approves or later reused to author that candidate. The live reviewer may supply semantic approval; a distinct execution session uses a released author slot. Use actual runtime session observations and the candidate identity returned by the controller; profile/model/effort declarations are requested configuration and cannot attest an unobserved backend. A report label is not independent execution. Record findings and evidence using the stage-review schema accepted by `review record`.

- **Semantic:** Walk every requirement and observable behavior through its subdomain, owner, contract, scenario and oracle. Require reciprocal FR/golden and behavior/scenario coverage. At S3, inspect each claimed edge against fixture, stimulus and asserted result: requirement-label overlap alone cannot establish overwrite confirmation, unsubmitted-draft protection or editing-baseline establishment. Inspect target-folder ownership, resolved state/error/atomicity decisions, dependency research and applicable NFR protocols. During preparation, verify complete phase-by-phase implementation/test ownership and every task's bounded instructions and acceptance. Reject unjustified work and duplicate abstractions.
- **Execution:** Walk every task and check through its complete runner, tools/pins, input producers, timing, host facilities and evidence transport. Check RED bootstrap feasibility without implementing product behavior early. Inspect all exact write sites, placement and full primary/linked secondary packets. Confirm qualification uses the actual intended runtime rather than an undeclared cached tool or a partial oracle on another host.

Read actual outputs and raw receipts. For final `preparation` review, inspect committed materialization and readiness/CI evidence, not only the draft plan. Preserve findings and independently verify their closure. Changed inputs require renewed review of affected evidence; missing proof leaves acceptance incomplete.

## Live review

Remain active throughout authoring: compare specification progress with requirements, preparation with frozen specifications/contracts, and implementation with frozen plans/contracts. Inspect snapshots at node handoffs, contract generation, task integration and significant checks. Record live findings through the controller with exact candidate identity, affected obligations and correction destination; partial drafts are legitimate live-review subjects, never final approvals. Changed inputs require a fresh review cursor. Blocking findings stop ordinary affected work; bounded controller-enrolled corrections may progress while findings remain open. Independent resolution is required before acceptance. Observe a coherent diff or checkpoint and send focused findings to the orchestrator. State the affected requirement/scenario, file or operation, observed issue, expected result, severity, and a concrete reproduction or reasoning. Check task ordering, approved scope, interface boundaries, duplicate logic, weak assertions, and unsafe async/persistence behavior.

For publication, coordinate a brief no-source-write window with all active authors: finish the current write, retain claims and leases, then verify the reviewed snapshot still matches the current HEAD/digest and record the observation before writes resume. Read-only analysis may continue. If source changes, refresh the observation; never relabel an old report with a new digest. Do not hold the window for the entire review or change controller freshness checks.

## Phase acceptance review

Review the exact candidate HEAD and source digest. Re-read the phase's promised outcome without assuming later work will make it true.

1. Check all planned tasks are complete and their evidence is relevant. Verify every primary and secondary work-site packet through the controller; absence of text alone proves nothing.
2. Check each required operation is reachable and executes the specified behavior. Registration, generated types, and success-shaped mock outputs are insufficient.
3. Check explicit executed scenario IDs and results for every golden path; an aggregate pass with omitted, filtered or skipped scenarios is insufficient. Check negative/boundary/recovery/concurrency cases appropriate to the phase. Inspect assertions and real boundary coverage. Look for ignored tests, fixed return values, swallowed errors, or a fake database replacing the only persistence acceptance path.
4. Check TDD receipts distinguish expected behavioral RED from infrastructure failure and link to the introduced assertions.
5. Check requirement/spec/contract/plan digests and reproducible generated output. Confirm architecture checks detect forbidden direct calls, not just well-formed schemas.
6. Check cumulative regressions and previously accepted guarantees. If a sealed guarantee was never true, record closure failure and route to specification amendment.
7. Check every due NFR against its defined environment and measurement protocol. Skipped platforms, absent hardware, and benchmarks without assertions remain incomplete.
8. Check privacy, capability restrictions, diagnostics, cancellation, recovery, and data migration behavior where relevant. Verify no task content or secret leaked into logs or fixtures.
9. Check additions against their reuse rationale. Flag duplicate business rules, speculative generics, unused APIs, unnecessary dependencies, placeholder operations, and inconsistent documentation.
10. Check PR head, base, checks, and review evidence are current. Invalidate review after rebases, conflict resolution, code changes, or changed verification policy.

## Result

Write the review JSON using the schema accepted by `./rdd review record FILE`. Include the exact phase, HEAD, source digest, reviewer identity, requirement/scenario scope, findings, and disposition fields required by that schema. Do not invent missing machine fields; use the supplied template or `--help`.

An approval asserts that the required evidence supports this phase's claims; it is not a proof of universal correctness. If a required check cannot run, return an environment blocker with the missing evidence. If findings exist, keep the phase open and re-review the repaired candidate. The reviewer never changes a finding to resolved merely because the implementor says it is fixed.

## Project review

Check all phase seals and their linked evidence, final cumulative tests/benchmarks, completed PR policy, requirement coverage, operation availability, unresolved blockers, and source integrity. The controller creates the final validation artifact only after these conditions hold. Preserve the distinction between a complete ready-to-merge PR stack and merged or deployed production software.
