# Solution specification

> Authoring template. Replace the guidance with project decisions during specification. This file is not a completed specification or an active plan. Machine fields belong in `.rdd/spec.json` under its schema.

## Baseline and authority

Record run ID, requirement source/digest, code baseline, mode, and prior run for amendments. State the product boundary from the requirements. Link stable requirement IDs rather than copying all requirement prose.

## Resolved decisions

Link each significant selected decision and its rationale in `docs/decisions/`. State source evidence and alternatives rejected. Resolve normative ambiguities before freeze; do not leave hidden assumptions as implementation choices.

## Vocabulary, state, and invariants

Define the solution representation of domain terms, legal/illegal states, ownership, identities, time semantics, validation, normalization, and transitions. Keep each semantic rule authoritative in one location.

## Module boundaries

For every module identify:

- Purpose and governing requirements.
- Owned state and invariants.
- Provided operations and consumed boundaries.
- Permitted and forbidden dependencies.
- Reason for a separate module/crate.
- Boundary enforcement and integration verification.

## Operation inventory

For every public or module operation specify caller, owner, inputs/outputs, errors, preconditions/postconditions, side effects, atomicity, concurrency, cancellation, retry/reconciliation, and scenario IDs. Define optional/future availability explicitly if staged implementation requires it.

## Canonical contracts

List exact `.proto` paths, packages/versions, generator/runtime versions, generated outputs, callable-signature enforcement, semantic constraints beyond the schema, and compatibility policy. Link the reproducible compile/consumer check and source digests.

## Persistence and recovery

Specify initialization versus unreadable/corrupt state, durable acknowledgment, transaction boundaries, interruption model, schema evolution, migration/rollback compatibility, backup/restore, and data lifecycle where required.

## User interaction

Specify observable flows, loading/error/empty states, keyboard and assistive-technology behavior, native permissions, and UI-to-application mappings. Link screen/interaction decisions without adding features outside the requirements.

## Quality designs

Map every NFR to a concrete design and verification protocol. Include datasets, supported environment matrix, performance evaluation, resource limits, privacy/security, observability, accessibility, packaging, and dependency qualification as applicable.

## Scenarios and traceability

Link golden, negative, boundary, concurrency, interruption, regression, and NFR scenarios. Define measurable oracles. Ensure all requirements and operations are mapped in the machine manifest.

## Independent review and freeze

Summarize resolved findings, outstanding non-normative risks, exact compile proof, and controller validation. Freeze only when there are no unresolved requirements/contract decisions and all required evidence is available.
