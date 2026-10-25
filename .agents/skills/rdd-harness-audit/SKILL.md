---
name: rdd-harness-audit
description: Audit the RDD harness's specification, preparation, and implementation workflows and handoffs using current research and repository evidence. Report defects and improvement proposals without source edits or run initialization.
---

# RDD harness audit

Use [rdd-harness-research](../rdd-harness-research/SKILL.md) first, reusing a brief only after checking source, scope, and policy identities. Read [reuse-analysis](../reuse-analysis/SKILL.md) and relevant [phase-review](../phase-review/SKILL.md) principles. These support evidence quality; they do not require controller review records or gates for maintenance with no active run.

Keep the audit read-only. Do not edit source, skills, requirements, generated files, or run state; initialize a run; repair findings; or publish. Inspect checks before executing them, using a disposable environment when they write artifacts. No active run means inspect the harness itself and report that limit, not fabricate application acceptance evidence.

## Inspect the complete workflow

Pin the commit and dirty-input content identities, research brief, audit scope, and relevant run/frozen policy identities. Inspect actual callers, validators, tests, CLI behavior, and documentation rather than relying on successful-looking prose. Cover all three stages and their handoffs:

- **Specification:** requirements and behavior coverage, domain/invariant ownership, scenarios and independent oracles, exact generated contracts, qualification, readiness, independent review, and freeze integrity.
- **Preparation:** frozen-input consumption, reuse/addition rationale, complete task packets and write sites, producer/dependency closure, category/phase feasibility, materialization, execution prerequisites, and preparation acceptance.
- **Implementation:** leases/integration, meaningful behavioral RED, category sweeps, protected contracts/oracles, continuous independent review, cumulative checks, exact-candidate gates, stack identity, sealed history, recovery, and project completion.

Trace transitions as well as individual controls: identities/policy pins, artifact inventories, validation before mutation, stale-input rejection, evidence transport, failure paths, and amendment routing. Compare normative promises with enforcement and tests. Inspect duplication, unnecessary wrappers, obsolete surfaces, and inconsistent guidance through actual call paths. A preferred alternative architecture alone is not a defect.

Run bounded existing checks where useful. Record exact commands, environment, exits, observed assertions/results, and evidence locations. Distinguish reproduced behavioral failures from suspected gaps, unavailable tools, skipped tests, or untested claims. Harness selftests establish only their measured harness behavior.

## Report

Deliver a source-linked audit in the response or requested analysis artifact with:

- Baseline/research identities, inspected stages/handoffs, commands/results, and explicit coverage gaps.
- Prioritized **evidenced defects**, each with a stable finding ID, severity, violated obligation/source, location, observed versus expected behavior, reproduction or inspectable proof, affected stages/IDs, impact, and smallest plausible correction.
- Separate **improvement proposals** with rationale, tradeoffs, and evidence needed to justify adoption. Keep hypotheses and style preferences out of the defect list.
- Protected/frozen-policy conflicts, environmental blockers, and unresolved evidence. Route required frozen-design or sealed-history changes through [amend-requirements](../amend-requirements/SKILL.md); an audit cannot authorize them.

An audit becomes stale when relevant source content, dirty input, frozen policies, scope, or research grounding changes. Record what needs rechecking. Missing coverage or grounding makes the audit incomplete; it does not imply uninspected workflows are sound. Repair requires the separate diff and repair workflows.
