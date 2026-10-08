---
name: specification-workflow
description: Derive and freeze complete, testable solution specifications, domain boundaries, and Protobuf contracts from formal repository requirements. Use as RDD stage one, for a new implementation, regeneration, requirement amendment, or a blocker that invalidates a frozen design.
---

# Specification workflow

Read `AGENTS.md`, `docs/harness/workflow-guide.md`, and `docs/harness/artifact-guide.md`. Run `./rdd status` and `./rdd doctor`. Use the installed controller's `--help` for command syntax; follow the command sequence in the workflow guide. Load only relevant supporting skills.

## Authority and scope

Treat `requirements/requirements.md` as the product source of truth. Preserve its exact text unless the user asks to amend requirements. A requirement marked draft may be used when the user's workflow instruction accepts that input; do not manufacture another approval gate. Resolve real ambiguity before freezing. Requirements identify obligations; specifications select mechanisms. Do not invent user features, implementation tasks, phase assignments, or production code in this stage.

Distinguish the selected run mode:

- **Regenerate:** Begin a fresh solution baseline. Archive the prior artifacts for history, remove superseded active specifications through the controller, and derive a complete replacement. Do not silently delete the working application or user data. Replacement production changes are planned later.
- **Amend:** Read the prior sealed baseline and requirement diff. Preserve unaffected decisions and contract identities. Expand the impact closure through requirements, operations, scenarios, data migrations, modules, dependency versions, NFRs, and existing tests. An unchanged requirement can still need a new design to repair a defect; record that reason.

Read `../amend-requirements/SKILL.md` for amendment handling and `../context-integrity/SKILL.md` before loading outside material.

## Inputs and work allocation

Initialize a run with `./rdd start --mode regenerate` or `./rdd start --mode amend`, then run `./rdd requirements index` and `./rdd spec init` when those artifacts do not already exist. Record the requirement digest and baseline commit in the active run. Inspect repository paths, manifests, current public APIs, migrations, tests, and relevant accepted evidence. For the supplied Todo document, inspect all functional and non-functional IDs and the normative vocabulary, capacity, platform, benchmark, and verification sections; headings alone do not contain the complete obligations.

Delegate independent analyses with bounded source packets:

1. A functional analyst produces obligation-to-scenario coverage, domain language, invariants, and state transitions.
2. A quality analyst produces measurable NFR designs, threat boundaries, persistence/recovery semantics, accessibility verification, and platform qualification.
3. A dependency researcher verifies official documentation, exact supported APIs, licenses, compatibility, failure modes, and a narrowly scoped feasibility experiment.
4. The orchestrator reconciles the solution. A fresh reviewer receives requirements and resulting artifacts, finds contradictions and missing coverage, and does not author its own approval evidence.

Use the runtime roles available in the local Codex installation. Do not claim a subagent ran if the runtime cannot create one. Report a capability blocker when the required independent review cannot be performed.

## Procedure

1. **Normalize obligations without rewriting authority.** Generate the requirement index using the controller. Link each statement to its original heading, revision, and acceptance text. Record global rules inherited by multiple requirements. Reject duplicate IDs and dangling references.
2. **Resolve decisions in the correct stage.** Ask concise architectural or directional questions whose answers change required behavior, supported environments, public contracts, or acceptance. Research routine implementation choices autonomously. Store the answer, affected requirement IDs, and selected decision. Do not leave normative TBDs hidden in prose.
3. **Qualify dependencies.** Use `research-dependencies`. For this stack use the current official Rust, Tokio, Tauri v2, and embedded Turso documentation and the bundled stack skills. Verify the selected Rust UI can package with Tauri, local embedded database behavior, async integration, and generated contract interoperability. Pin exact compatible versions in the solution lock rather than copying a tutorial's unbounded latest version.
4. **Design domains from behavior.** Use `domain-boundaries`. Specify owners, invariants, responsibilities, required operations, dependencies, and boundaries. Keep framework adapters and persistence mechanics from dictating business domains. Explain why each proposed module exists and where simpler organization was rejected.
5. **Specify complete observable behavior.** Define preconditions, postconditions, state transitions, normalization, error taxonomy, retries, cancellation, concurrency, atomicity, and relevant time semantics. Allocate all requirements to solution elements. Keep each rule authoritative in one place and link it elsewhere.
6. **Define the verification design.** Create golden paths for every functional requirement and add relevant invalid input, boundary, concurrency, interruption, regression, accessibility, and privacy cases. Define each scenario's stable ID, requirements, fixture, stimulus, observable oracle, and evidence method. A golden path alone does not establish recovery or security. For NFRs define measurable thresholds, reference environments, datasets, timing boundaries, sample counts, distributions, evaluators, and skip policy. Required unsupported platforms are blockers, not passes.
7. **Design canonical Protobuf contracts.** Select package names and versions, services/operations, fields, explicit presence, enum defaults, error representation, streaming if required, and compatibility rules. Describe semantic constraints that Protobuf cannot express. Map each public and module operation to behavioral scenarios. Local in-process modules do not need a network service merely because the schema uses service declarations. Generated trait or adapter checks must enforce the selected call signatures.
8. **Prove compilation before freeze.** Place the exact candidate `.proto` files under `contracts/`, list them in `contract_files`, and list generated outputs under `gen/` in `generated_files`. In a disposable experiment compile those bytes with the selected generators and Rust toolchain. Verify generated types and callable boundary signatures, imports, package names, and frontend interoperability. Preserve command, version, digest, and result evidence. Declare generation/compilation/consumer checks in `checks` and select them through `contract_check_ids`; `./rdd spec freeze` executes them. A successful parser invocation without usable generated signatures is insufficient. The experiment is evidence, not the application implementation.
9. **Review coherence and size.** Independently check requirement coverage, contract semantics, compile proof, dependency support, incomplete decisions, contradictory replicas of rules, speculative features, ungrounded abstractions, and source trust. Resolve findings while specification remains open. Do not pad documents to meet a page count.
10. **Freeze exact artifacts.** Validate the machine manifest against the repository schemas and controller checks. Run `./rdd spec validate` and then `./rdd spec freeze` to freeze the selected specifications, decisions, scenario definitions, dependency versions, and canonical contract bytes. Record the digest set. Leave no unresolved requirement or contract question. Report the frozen baseline and next-stage command.

## Exit conditions

Every requirement has an explicit solution mapping and acceptance strategy. Every boundary has a canonical owner and enforceable interface. Every required NFR has a protocol, including human evidence where automation cannot substitute. The exact contract set has a successful generation/compile experiment. Independent specification review is resolved. The controller accepts the freeze.

If infeasible, retain the evidence and the smallest concrete decision needed from the user. Do not weaken requirements to satisfy tooling. Preparation and implementation may report blockers; they cannot retroactively resolve requirement ambiguity.

Use `.rdd/templates/specification.md`, `.rdd/templates/scenario.md`, `.rdd/templates/dependency-research.md`, and `.rdd/templates/decision.md` for human-readable artifacts. Read [the worked review example](references/specification-example.md) when translating prose into scenarios and contracts.
