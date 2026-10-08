---
name: amend-requirements
description: Analyze a requirements or design-defect amendment against a prior RDD baseline, compute downstream impact, preserve valid artifacts and history, and begin the three workflows for affected work. Use when a requirement changes, is added or retired, or a sealed design/implementation defect requires a new run.
---

# Amend requirements

Read `AGENTS.md`, the selected current and prior requirements, prior spec/plan locks, and relevant sealed evidence. Use [the amendment example](references/amendment-example.md) to reason about unchanged requirements with changed evidence.

## Preserve identity and authority

Keep stable requirement IDs for the same obligation. Increment revisions for changed meaning. Retire removed IDs and never reuse them for unrelated behavior. Do not modify the user's canonical requirements without authorization; a workflow instruction to use the updated file already authorizes deriving downstream work from it.

Distinguish a requirement change from a specification correction, implementation defect, dependency incompatibility, and environment failure. Only the first necessarily changes requirement text. A sealed-phase defect starts a new amendment run even if the product obligations remain identical.

## Determine impact

1. Compare exact source baselines and identify added, changed, removed, and unchanged IDs. Read changed vocabulary, global data rules, platform matrices, benchmarks, and verification sections as well as ID blocks; a shared rule can affect many unchanged IDs.
2. Traverse requirement → solution → operation/contract → scenario → module/data/dependency → task/phase → evidence links. Include reverse callers, migration compatibility, release artifacts, docs, and cross-cutting NFRs.
3. State which artifacts remain semantically valid and why. An unchanged file is not automatically unaffected; changed meaning upstream may invalidate its tests or assumptions.
4. Reuse evidence only when its baseline, scope, environment, toolchain, and assertions remain valid for the new claim. Prior evidence can support analysis; final acceptance still needs current revision-bound verification as the controller requires.
5. In specification, revise only affected solution sections, scenarios, decisions, and contracts. Preserve stable contract tags, names, and versions where appropriate; classify intended breaking changes explicitly and design migration/compatibility behavior.
6. In preparation, regenerate the impacted task graph and phases from the newly frozen solution. Preserve the prior run's sealed history. Do not splice tasks into a sealed prior phase.
7. In implementation, create a new stack from the chosen accepted code baseline, execute the new phases, and maintain cumulative regression for unchanged requirements.

## Regeneration boundary

Use `regenerate` when the user requests a fresh complete solution baseline. Archive previous active specifications and generated plan history before replacement. Plan explicit production replacement/deletion tasks later; preserve repository history and user data. Do not treat regenerate as permission to wipe working trees or erase production databases.

## Blocker report

For a defect include observed behavior, expected obligation, minimal reproduction, affected accepted claim, revision, evidence, and the smallest architectural decision needed. A preparation or implementation agent reports the issue; specification owns its resolution.

## Completion

The new run records the prior baseline and reason, complete impact closure, retained artifact rationale, revised solution, compatibility consequences, and current verification obligations. No previous acceptance record is rewritten to make the history appear successful.
