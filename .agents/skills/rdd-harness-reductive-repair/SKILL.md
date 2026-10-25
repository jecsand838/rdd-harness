---
name: rdd-harness-reductive-repair
description: Research, audit, propose, independently review, apply, and verify a net-reductive RDD harness maintenance repair. Use when the user requests repair, not for read-only research, audit, or diff requests.
---

# RDD harness reductive repair

Carry authorized harness repair through current research, complete audit, exact reductive diff, independent review, application, verification, and final independent review. Use the linked skills as canonical procedures instead of duplicating their outputs or rules.

A user request to repair authorizes application within scope after required review and freshness checks; do not add routine confirmation. Research, audit, and diff requests alone do not authorize application. Plan Mode never applies changes: return the complete proposal and pending verification. Publishing, pushing, opening/updating PRs, merging, and releasing require separate explicit authorization in the current session.

## Build and review the candidate

1. Use [rdd-harness-research](../rdd-harness-research/SKILL.md), then [rdd-harness-audit](../rdd-harness-audit/SKILL.md). Reuse results only after checking scope, source/dirty-input identities, grounding, and relevant frozen policy. Missing grounding or workflow coverage stays explicitly incomplete.
2. Use [rdd-harness-reductive-repair-diff](../rdd-harness-reductive-repair-diff/SKILL.md) for the isolated candidate, detailed plan, complete patch, RED/GREEN evidence, and verified negative aggregate text-line delta including tests/docs. Preserve unrelated work. Impossible safe reduction is a stopping condition, not permission for harmful deletion.
3. Obtain independent, read-only review of the exact candidate and complete patch. Follow applicable native reviewer policy and [phase-review](../phase-review/SKILL.md)'s principles for coverage, execution evidence, and independence; do not impose its controller record/gate machinery on maintenance with no active run. The author cannot approve their own candidate. Supply finding IDs, authority sources, base/dirty/candidate/patch identities, complete diff, deletion/impact rationale, counts, and raw verification evidence.
4. Require review of defect resolution, preserved behavior/oracles, scope, protected policies/history, safe deletion/reuse, complete patch replay, metric integrity, and test adequacy. Correct findings in isolation and obtain renewed review of the changed candidate. Missing independent review leaves repair incomplete and unapplied.

## Apply only the reviewed candidate

Immediately before application, compare current commit, staged/unstaged/untracked content, relevant policy locks, patch hash, and candidate identity with the reviewed package. Reconcile input or review drift by refreshing affected research/audit, regenerating the patch/counts, rerunning checks, and obtaining current independent review. Do not silently use fuzzy hunks, three-way merge, conflict resolution, or omitted files that produce an unreviewed candidate.

Apply exactly the reviewed patch within authorized paths, retaining unrelated dirty work. Confirm the resulting complete content inventory matches the reviewed candidate. Never edit frozen active-run skills, verifiers, contracts, acceptance definitions, phase plans, receipts, or sealed history to make repair pass. Required changes use [amend-requirements](../amend-requirements/SKILL.md) and the existing specification workflow. Absence of `.rdd/run.json` permits ordinary harness maintenance, not fabricated controller gates or application-completion claims.

## Verify and finish

Run relevant focused and cumulative checks on applied source. Record exact commands, exits, assertions/test counts, environment, and final source identity; compare with proposed evidence. Recompute complete text-line reduction, text-byte and binary changes from the same pinned input, including tests/docs. Unexpected deltas or verification failures require a corrected, freshly reviewed candidate; never weaken checks or relabel missing evidence.

Obtain final independent review of the exact applied source, unresolved findings, counts, and actual results. Pre-application approval does not substitute for this review. If review or required execution is unavailable, report remaining incompleteness and preserve source/evidence for resumption. Do not publish an unreviewed correction.

Return resolved finding IDs, changed paths, base/dirty/final identities, complete final unified patch or accessible exact artifact, verified reduction counts, RED/GREEN and cumulative results, independent review disposition, impact, risks, and blockers. Distinguish verified harness maintenance from accepted application work. Stop after authorized local repair unless this session separately authorizes publication.
