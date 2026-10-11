---
name: phase-review
description: Continuously review all three RDD workflows, steer corrections, and independently review exact-candidate stage and phase acceptance. Bind findings to exact candidates, verify corrections, and validate project claims without task-level approval gates.
---

# Phase review

Start reviewer or researcher work with `./rdd review run --stage STAGE --purpose live|execution|research --prompt-file FILE`. The controller creates an explicitly read-only App Server thread with the canonical profile and inherited approval settings unchanged. Keep `live` persistent alongside the coordinator and at most two authors; `execution` is a distinct final reviewer in a released author slot. `research` is bounded evidence gathering, not approval. Read the requirements, frozen solution, phase scope, task graph, contracts, raw diff, relevant tests, benchmark protocols, and supplied controller receipts. Return source-linked JSON to the coordinator. Do not write files or run controller commands that create state, locks, temporary copies, receipts or other writes. Read [the review example](references/review-example.md) for a false-positive success claim and a correct outcome.

## Specification and preparation reviews

Two distinct reviewer sessions provide `semantic` and `execution` perspectives. Neither reviewer may be a registered author of the artifacts it approves or later reused to author that candidate. The live reviewer may supply semantic approval; a distinct execution session uses a released author slot. Use actual runtime session observations and the candidate identity supplied by the coordinator from the controller; profile/model/effort declarations are requested configuration and cannot attest an unobserved backend. A report label is not independent execution. Return findings and evidence using the stage-review schema accepted by `review record`; the coordinator records them.

- **Semantic:** Walk every requirement and observable behavior through its subdomain, owner, contract, scenario and oracle. Require reciprocal FR/golden and behavior/scenario coverage. Inspect target-folder ownership, resolved state/error/atomicity decisions, dependency research and applicable NFR protocols. During preparation, verify complete phase-by-phase implementation/test ownership and every task's bounded instructions and acceptance. Reject unjustified work and duplicate abstractions.
- **Execution:** Walk every task and check through its complete runner, tools/pins, input producers, timing, host facilities and evidence transport. Check RED bootstrap feasibility without implementing product behavior early. Inspect all exact write sites, placement and full primary/linked secondary packets. Confirm qualification uses the actual intended runtime rather than an undeclared cached tool or a partial oracle on another host.

Read the actual outputs and raw receipts. For final `preparation` review, inspect the committed materialization and readiness/CI evidence, not only the draft plan. Preserve earlier findings and independently verify their closure. Both perspectives must approve the same candidate with zero unresolved findings. Changed inputs invalidate affected approvals; a passed schema or another worker's assurance is not a substitute. Re-review corrected candidates until the exit criteria hold, or leave the workflow incomplete with a concrete blocker.

A frozen specification defect exposed in preparation, or a specification/planning defect exposed in implementation, is a critical harness regression. Record origin/detection stage and evidence immediately, stop affected execution, and require a reproducing regression before accepting the preventive-control repair. Distinguish an execution design defect from an external outage or denied permission.

## Live review

Remain active throughout authoring: compare specification progress with requirements, preparation with frozen specifications/contracts, and implementation with frozen plans/contracts. Inspect snapshots at node handoffs, contract generation, task integration and significant checks. Return live findings for the coordinator to record through the controller with exact candidate identity, affected obligations and correction destination; partial drafts are legitimate live-review subjects, never final approvals. Changed inputs require a fresh review cursor. Blocking findings stop affected work until independently verified resolution. Observe a coherent diff or checkpoint and return focused findings to the orchestrator. State the affected requirement/scenario, file or operation, observed issue, expected result, severity, and a concrete reproduction or reasoning. Check task ordering, approved scope, interface boundaries, duplicate logic, weak assertions, and unsafe async/persistence behavior.

Do not mutate implementor workspaces or silently take over their tasks. Do not demand a formal review after each task. Live feedback steers corrections without approving individual implementation tasks. Final stage/phase gates require current independent review. The continuous reviewer may provide final semantic approval if it authored no candidate artifacts; execution approval needs a distinct session.

## Phase acceptance review

Review the exact candidate HEAD and source digest. Re-read the phase's promised outcome without assuming later work will make it true.

1. Check all planned tasks are complete and their evidence is relevant. Verify every primary and secondary work-site packet through the controller; absence of text alone proves nothing.
2. Check each required operation is reachable and executes the specified behavior. Registration, generated types, and success-shaped mock outputs are insufficient.
3. Check explicit executed scenario IDs and results for every golden path; an aggregate pass with omitted, filtered or skipped scenarios is insufficient. Check negative/boundary/recovery/concurrency cases appropriate to the phase. Inspect assertions and real boundary coverage. Look for ignored tests, fixed return values, swallowed errors, or a fake database replacing the only persistence acceptance path.
4. Check TDD receipts distinguish expected behavioral RED from infrastructure failure and link to the introduced assertions.
5. Check requirement/spec/contract/plan digests and reproducible generated output. Confirm architecture checks detect forbidden direct calls, not just well-formed schemas.
6. Check cumulative regressions and previously accepted guarantees. If a sealed guarantee was never true, record closure failure and route to specification amendment.
7. Check every due NFR against its defined environment and measurement protocol. Skipped platforms, absent hardware, missing screen-reader evidence, and benchmarks without assertions remain incomplete.
8. Check privacy, capability restrictions, diagnostics, cancellation, recovery, and data migration behavior where relevant. Verify no task content or secret leaked into logs or fixtures.
9. Check additions against their reuse rationale. Flag duplicate business rules, speculative generics, unused APIs, unnecessary dependencies, placeholder operations, and inconsistent documentation.
10. Check PR head, base, checks, and review evidence are current. Invalidate review after rebases, conflict resolution, code changes, or changed verification policy.

## Result

Return review JSON as text using the schema accepted by `./rdd review record FILE`; the coordinator writes the report and records it. Include the exact phase, HEAD, source digest, actual reviewer session identity, requirement/scenario scope, findings, and disposition fields required by that schema. Do not invent missing machine fields; read the supplied schema/template and candidate packet. The read-only reviewer never executes the recording command.

An approval asserts that the required evidence supports this phase's claims; it is not a proof of universal correctness. If a required check cannot run, return an environment blocker with the missing evidence. If findings exist, keep the phase open and re-review the repaired candidate. The reviewer never changes a finding to resolved merely because the implementor says it is fixed.

## Project review

Check all phase seals and their linked evidence, final cumulative tests/benchmarks, completed PR policy, requirement coverage, operation availability, unresolved blockers, and source integrity. The controller creates the final validation artifact only after these conditions hold. Preserve the distinction between a complete ready-to-merge PR stack and merged or deployed production software.
