# Phase plan

> Human-readable companion to the canonical `.rdd/plan/plan.json`. Populate machine fields from the schema. Do not edit this narrative to override frozen task or phase state.

## Phase outcome

Name the phase, accepted predecessor, and complete outcome. State what must be true even if all future phases are cancelled.

## Capability closure

| Consumed capability | Baseline evidence or producer task | Produced capability | Acceptance evidence |
|---|---|---|---|
| Fill from real graph | Point to source/test or task ID | Define observable output | Link scenario/check IDs |

## Category order

List tasks under tests, deletion, modification, addition, documentation. Retain actual prerequisite edges inside each category. Show any later-category producer moved to an earlier phase instead of relabeling work.

## Target paths and ownership

List existing/added/deleted/generated paths, exact task write ownership, primary/secondary work sites, exact context selectors, adjacent-sidecar strategy, and shared-file integration owner. Record reuse rationale for every addition.

## Verticals

Describe ordered task paths through the phase, shared prerequisites, joins, and permitted disjoint concurrency.

## Gate inventory

Map requirements, operations, scenarios, checks, benchmarks, required platform/manual evidence, cumulative regressions, and exact acceptance conditions. Record how every current operation is proven available.

## Operational state

Describe data migration order, failure/recovery, rollback compatibility, unavailable future operations permitted by the frozen spec, and packaging behavior.

## PR and closure

State branch identity, base phase/branch, configured PR completion policy, exact-revision evidence rules, and the consequence of discovering a sealed-phase defect.

## Independent plan review

Record semantic and execution-readiness findings, actual independent reviewer sessions, and verified resolutions for the same candidate before plan freeze. After materialization, commit the projected packets/matrix and repeat both perspectives against the actual readiness/CI evidence before gate preparation.
