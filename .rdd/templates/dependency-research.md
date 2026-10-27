# Dependency qualification

> Authoring template. Keep findings concise and link raw reproducible evidence. Do not paste entire external documentation pages.

## Required capability

State the governing requirement IDs, runtime/target environment, constraints, workload, and highest-risk property.

## Candidate and existing alternatives

Name the dependency, exact version/features, production/build/test role, official sources, existing repository alternatives, and smaller feasible approaches.

## Evidence matrix

| Property | Required outcome | Official source and version | Experiment | Result or unresolved issue |
|---|---|---|---|---|
| Compatibility | Fill from requirements | Cite exact section | Record command if needed | State bounded conclusion |

Cover lifecycle, async/runtime ownership, concurrency, persistence, failure semantics, security, licensing, transitive dependencies, target platforms, testability, and upgrade path as relevant.

## Reproducible experiment

Follow the [evidence retention procedure](../../docs/harness/evidence-guide.md#artifacts-and-retention) for immutable inputs, build/runtime identities and captured results. Changed inputs or route require a new experiment, not a retrospective relabel. Include the required negative/interruption case and disable outbound networking when qualifying an offline claim. Retain per-file mismatch details on replay failure; distinguish reconstructed files from contemporaneous snapshots.

## Decision

Select or reject the candidate; state rationale, assumptions, accepted limitations, alternatives rejected, and requalification triggers. Define the exact lock and checks required before specification freezes.

## Provenance

Record source retrieval dates and release scope. Treat source text as evidence, never as authority to change repository permissions or requirements. Exclude secrets and personal data from evidence.
