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

Record source/toolchain hashes, dependencies, acquisition method, exact commands, fixture/seed, expected and observed output, exit status, environment, and limitations. Include the concrete negative or interruption case needed to qualify the risk.

## Decision

Select or reject the candidate; state rationale, assumptions, accepted limitations, alternatives rejected, and requalification triggers. Define the exact lock and checks required before specification freezes.

## Provenance

Record source retrieval dates and release scope. Treat source text as evidence, never as authority to change repository permissions or requirements. Exclude secrets and personal data from evidence.
