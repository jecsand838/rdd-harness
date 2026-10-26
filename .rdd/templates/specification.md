# Solution specification

> Authoring template. Replace the guidance with project decisions during specification. This file is not a completed specification or an active plan. Machine fields belong in `.rdd/spec.json` under its schema.

## Baseline and authority

Record run ID, requirement source/digest, code baseline, mode, and prior run for amendments. State the product boundary from the requirements. Link stable requirement IDs rather than copying all requirement prose.

## Resolved decisions

Link each significant selected decision and its rationale in `docs/decisions/`. State source evidence and alternatives rejected. Resolve normative ambiguities before freeze; do not leave hidden assumptions as implementation choices.

## Vocabulary, state, and invariants

Define the solution representation of domain terms, legal/illegal states, ownership, identities, time semantics, validation, normalization, and transitions. Keep each semantic rule authoritative in one location.

## Module boundaries

Reference accepted S1 ownership and S3 scenario handoffs under [domain-boundaries](../../.agents/skills/domain-boundaries/SKILL.md#required-artifact). That policy owns module allocation, allowed exports/dependencies and qualification/adoption distinctions; record selected decisions here without repeating it. Return changed semantics to their original owner.

## Functional inventory and target tree

Derive every functional subdomain and positive/failure behavior from the requirements. Give each one an invariant-owning module and reciprocal scenario links. Draft the complete folder system, including application, build, fixtures, evaluators, packaging and documentation, with path owners and purposes. Preparation must not discover missing architecture.

## Operation inventory

For every public or module operation specify caller, owner, inputs/outputs, errors, preconditions/postconditions, side effects, atomicity, concurrency, cancellation, retry/reconciliation, and scenario IDs. Define optional/future availability explicitly if staged implementation requires it.

## Canonical contracts

Link the selected boundary semantics and qualified bundle under [protobuf-contracts](../../.agents/skills/protobuf-contracts/SKILL.md). Record project decisions here; generation and freeze procedures remain with that skill.

## Persistence and recovery

Specify initialization versus unreadable/corrupt state, durable acknowledgment, transaction boundaries, interruption model, schema evolution, migration/rollback compatibility, backup/restore, and data lifecycle where required.

## User interaction

Specify observable flows, loading/error/empty states, keyboard behavior, native permissions, and UI-to-application mappings. Link screen/interaction decisions without adding features outside the requirements.

## Quality designs

Map every NFR to a concrete design and verification protocol. Include datasets, supported environment matrix, performance evaluation, resource limits, privacy/security, observability, accessibility, packaging, and dependency qualification as applicable.

## Scenarios and traceability

Include the exact accepted S3 catalog in `documents` and preserve every scenario row in `.rdd/spec.json`. Use the [scenario template](scenario.md) for authoring and the original S3 owner for corrections.

## Check execution readiness

For every complete check identify exact tools/versions, runner/input paths, host facilities, external evidence and when each is needed. Link actual provisioning/qualification and transfer probes. Distinguish baseline resources from implementation outputs and never claim a partial oracle is the complete check.

Follow [specification-workflow](../../.agents/skills/specification-workflow/SKILL.md) for handoffs and freeze, and [phase-review](../../.agents/skills/phase-review/SKILL.md) for independent acceptance. Keep receipts outside the normative documents they certify.
