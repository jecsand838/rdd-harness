# Solution specification

> Authoring template. Replace the guidance with project decisions during specification. This file is not a completed specification or an active plan. Machine fields belong in `.rdd/spec.json` under its schema.

## Baseline and authority

Record run ID, requirement source/digest, code baseline, mode, and prior run for amendments. State the product boundary from the requirements. Link stable requirement IDs rather than copying all requirement prose.

## Resolved decisions

Link each significant selected decision and its rationale in `docs/decisions/`. State source evidence and alternatives rejected. Resolve normative ambiguities before freeze; do not leave hidden assumptions as implementation choices.

## Vocabulary, state, and invariants

Define the solution representation of domain terms, legal/illegal states, ownership, identities, time semantics, validation, normalization, and transitions. Keep each semantic rule authoritative in one location.

## Module boundaries

Reference the exact accepted `docs/specs/domain-inventory.json` handoff under `domain-boundaries`. Preserve each domain and interaction identity; return corrections to S1. For every module identify:

- Distinct functional subdomain owner, purpose and allocated requirements, or explicit supporting owner kind.
- Owned state and invariants.
- Provided Protobuf services/types, permitted consumed operations/types, and every directed call/type-only binding.
- Permitted and forbidden dependencies.
- Distinct implementation paths, approved public exports and construction/wiring entry points; justification if a separate crate is needed.
- Canonical source/generated identities, including shared support ownership.
- Disposable specification qualification and separate real implementation conformance checks.

## Functional inventory and target tree

Derive every functional subdomain and positive/failure behavior from the requirements. Give each one an invariant-owning module and reciprocal scenario links. Draft the complete folder system, including application, build, fixtures, evaluators, packaging and documentation, with path owners and purposes. Preparation must not discover missing architecture.

## Operation inventory

For every public or module operation specify caller, owner, inputs/outputs, errors, preconditions/postconditions, side effects, atomicity, concurrency, cancellation, retry/reconciliation, and scenario IDs. Define optional/future availability explicitly if staged implementation requires it.

## Canonical contracts

List exact `.proto` paths/import closure, packages, generator/runtime/configuration/lock identities, generated outputs and descriptor-derived symbols. Link solution operations to actual methods. Use schema-owned response success/failure variants and separately freeze adapter decoding, size, cancellation and lifecycle mappings. Link positive and negative disposable provider/consumer qualification on required targets. Define future real adoption, dependency and bypass checks without requiring product code here. Keep schema fields solely in Protobuf; exact downstream immutability is stronger than amendment compatibility.

## Persistence and recovery

Specify initialization versus unreadable/corrupt state, durable acknowledgment, transaction boundaries, interruption model, schema evolution, migration/rollback compatibility, backup/restore, and data lifecycle where required.

## User interaction

Specify observable flows, loading/error/empty states, keyboard behavior, native permissions, and UI-to-application mappings. Link screen/interaction decisions without adding features outside the requirements.

## Quality designs

Map every NFR to a concrete design and verification protocol. Include datasets, supported environment matrix, performance evaluation, resource limits, privacy/security, observability, accessibility, packaging, and dependency qualification as applicable.

## Scenarios and traceability

Link golden, negative, boundary, concurrency, interruption, regression, and NFR scenarios. Define measurable oracles. Ensure all requirements and behaviors are mapped in both directions. Every FR and positive operation needs golden coverage; every golden scenario must reference an FR.

## Check execution readiness

For every complete check identify exact tools/versions, runner/input paths, host facilities, external evidence and when each is needed. Link actual provisioning/qualification and transfer probes. Distinguish baseline resources from implementation outputs and never claim a partial oracle is the complete check.

## Independent review and freeze

Record S0–S8 node handoffs, registered authors, continuous review against requirements, and verified steering corrections. Record distinct final semantic/execution sessions, exact candidate identity and current readiness/compile evidence. Both perspectives must approve the same candidate with zero unresolved findings. Re-review after corrections; no missing proof or budget timeout can be called completion.
