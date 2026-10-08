---
name: preparation-workflow
description: Convert frozen RDD specifications and acceptance scenarios into a validated target tree, task DAG, implementation verticals, sequential dependency-closed phases, categorized backlog, inline markers, generated contracts, and implementation matrix. Use as stage two before implementation or after a new specification baseline.
---

# Preparation workflow

Read `AGENTS.md`, `docs/harness/workflow-guide.md`, and `docs/harness/artifact-guide.md`. Run `./rdd status` and `./rdd doctor`; verify that specification is frozen and its digests still match. Read the exact frozen manifests and only the solution sections required for planning.

## Preserve the solution boundary

Treat requirements, frozen specification, accepted decisions, and canonical contracts as immutable inputs. A missing behavioral decision, incompatible contract, unqualified dependency, or contradictory requirement is a specification blocker. Record it and return to stage one. Do not turn an unresolved architecture question into an implementation task.

Inspect the existing codebase before planning. For regenerate, plan explicit replacement or removal; do not destroy an existing application merely because active specs were regenerated. For amendment, include the complete change impact closure and preserve unrelated behavior.

## Build the plan

Run `./rdd plan init` if no active draft plan exists. Populate `.rdd/plan/plan.json` using `.rdd/schemas/plan.schema.json`; keep detailed capability and operation reasoning in linked solution/plan notes.

1. **Inventory existing assets.** Map current modules, operations, database lifecycle, test fixtures, performance evaluators, observability, docs, dependency manifests, and shared files. Use `reuse-analysis` to distinguish reusable code from superficial name matches. Record concrete searched paths and rejected alternatives for every addition.
2. **Design the target tree.** Enumerate required paths, their role, and whether each is existing, added, modified, deleted, generated, or a temporary shell. Prefer language-appropriate crates and modules. Derive actual Todo paths from the approved specification; the boilerplate's empty `apps/` and `modules/` directories are navigational roots, not predetermined domains.
3. **Create executable tasks.** Each task has a stable ID, requirements and scenarios, exact write ownership, prerequisites, category, completion evidence, and an unambiguous result. In a greenfield first phase, explicitly include the test/build infrastructure and minimal nonbehavioral application entry scaffold needed for a runnable real-boundary assertion in the `tests` tasks. Plan typed explicit not-implemented boundary stubs only where needed to run assertions, and plan their replacement in subsequent modification/addition tasks. Every tests task still needs behavioral RED; the scaffold is not a green-bootstrap exemption. Do not claim compilation failures are behavioral RED or place accepted product behavior in that scaffold. Categories are exactly `tests`, `deletion`, `modification`, `addition`, or `documentation`. Split mixed-category work. An addition requires a reuse analysis and why a modification cannot meet the same objective. A deletion includes all known references, compatibility effects, and preserved behavior.
4. **Identify producers and consumers.** Name capabilities each task requires and produces. Classify each prerequisite as already in the accepted baseline or produced by another task. Include build/tooling prerequisites, shared configuration changes, database migration order, UI/native registration, fixtures, benchmark evaluators, docs, and packaging. A declaration that something is a baseline capability needs repository evidence.
5. **Derive verticals.** Use `plan-verticals` to build the real dependency DAG and ordered paths through it. A vertical is an ordering of dependent tasks, not a synonym for frontend/backend team. A task may be shared by multiple verticals. Detect missing producers, dependency cycles, duplicate ownership, and concurrent writes to the same path.
6. **Add category barriers.** Within every phase require tests before deletion before modification before addition before documentation. If an actual prerequisite goes from a later category to an earlier category, separate phases or revise a false task split. Do not relabel an addition as modification to pass validation. Test authoring can precede absent behavior; runtime migration execution still follows its safe sequence.
7. **Derive phases.** Use `plan-phases`. Assign each phase a usable outcome, prerequisites, produced capabilities, explicit scope exclusions, all relevant tests/NFR checks, regression obligations, rollback/recovery behavior, and one PR. Every phase's acceptance must be attainable from its baseline, completed predecessors, and own tasks. No future-phase dependency may support a current acceptance claim.
8. **Construct the implementation matrix.** Link requirement → solution element → operation → scenario → task → vertical → phase → planned evidence. Include required human/platform evidence and the phase in which it must be obtained. Test and benchmark commands must have concrete assertions, datasets, and exit semantics. A command named `test` that always returns success is not an evaluator.
9. **Review the plan independently.** Give a fresh reviewer the requirements, frozen spec, graph, target tree, operation inventory, and phase acceptance. Ask it to find impossible ordering, missing work, unsupported intermediate states, bloat, weak oracles, hidden late NFR work, and shared-file collisions. Resolve preparation errors here. Return design defects to specification.
10. **Freeze the plan.** Run `./rdd plan validate` and `./rdd plan freeze`. Validate graph closure, category order, full coverage, unique IDs, paths, operation availability, approved shell content, and contract integrity. The locked plan is the canonical instruction for materialization.
11. **Prepare exact approved artifacts.** Run `./rdd prepare` after plan freeze. The controller creates approved comment-only shells, sidecars for editable noncommentable/deleted paths, and deterministic `RDD:P01:T001` phase-prefixed task markers from the manifest. It rechecks the exact canonical contracts and reproduces generation/compilation with pinned checks, matching the specification baseline. It writes `.rdd/prepared.json` and the implementation matrix. Do not create fake valid manifests, production behavior, or a green test suite. Shells must not enter a build graph that requires working behavior before implementation. Run `./rdd anchors verify`, then commit the prepared baseline before implementation begins. Report the first executable task set and phase acceptance conditions.

## Marker and shell rules

The manifest owns task state; comments are projections. Use the controller's exact marker format rather than hand-building variants. An unresolved task must have a marker or a registered sidecar even when its file does not yet exist. Keep frozen/generated interfaces as read-only check inputs. Their paths cannot be task writes, and assigning a sidecar cannot bypass this restriction. Plan verification work on the relevant test source instead. Use a sidecar for JSON, lockfiles, binaries, planned deletions, or any format whose comments are unsafe. Never insert malformed content into `Cargo.toml`, capability JSON, or schema files to reserve a path.

Removing a marker cannot complete a task. Completion evidence changes controller state; projection then removes or updates the marker. The controller's reconciliation must detect missing, stale, duplicate, or unknown markers.

## Exit conditions and blockers

The full plan is dependency-closed, category-compatible, covered by independent review, and machine-valid. All required paths have approved shell handling. Contract generation reproduces the frozen bytes. No production task has been performed. No requirement, spec, or contract has changed.

If preparing the plan exposes an ambiguity, emit a precise blocker with affected IDs, evidence, and the minimum question to resolve in specification. Missing tools are environment blockers; a tool's absence is not evidence that the contract or implementation passed.

Read [the preparation example](references/preparation-example.md) for a complete category-order counterexample and valid repair.
