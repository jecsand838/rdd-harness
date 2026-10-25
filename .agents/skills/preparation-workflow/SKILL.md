---
name: preparation-workflow
description: Convert frozen RDD specifications and acceptance scenarios into a validated target tree, task DAG, implementation verticals, sequential dependency-closed phases, categorized backlog, co-located task packets, contract conformance ownership, and implementation matrix. Use as stage two before implementation or after a new specification baseline.
---

# Preparation workflow

Read `AGENTS.md`, [the preparation command sequence](../../../docs/harness/workflow-guide.md#stage-two-preparation), the frozen specification/contracts and relevant [artifact schemas](../../../docs/harness/artifact-guide.md#plan-manifest). Inspect P0–P8 through `workflow nodes`; claim only `workflow next` work. P1–P5 belong to `rdd_task_planner`; the coordinator does not replace it. Keep a read-only reviewer comparing progress with frozen authority under [phase-review](../phase-review/SKILL.md).

P0–P4 record distinct immutable research/planning notes. P5 alone writes the assembled `.rdd/plan/plan.json`; `plan init` may initialize the draft. Return corrections to the producer instead of changing its accepted output through a successor. Requirements, domain identities, target architecture and generated contracts remain immutable. A frozen design defect is a critical escape requiring affected IDs/evidence and preventive-control regression, not an implementation task.

## Build the plan

1. Inspect existing modules, operations, migrations, tests, tools and docs using [reuse-analysis](../reuse-analysis/SKILL.md). Preserve baseline failures and accepted behavior. Regeneration plans replacement explicitly; amendment preserves unaffected work and covers the change impact.
2. Resolve the complete frozen target tree into exact files and writes, including build, test, fixtures, evaluators, packaging and documentation. Every actionable add/modify/delete file needs task ownership; retained/generated files and directories retain their proper dispositions. Missing architecture returns upstream.
3. Hydrate every task before freeze: objective, bounded instructions, requirement/specification/behavior/scenario links, producers and input timing, outputs, exact writes/sites, dependencies, category, phase, verticals and acceptance evidence. Split mixed-category or oversized work. Additions require rejected reuse alternatives; deletions include references and compatibility effects. Use the canonical [plan fields and packet format](../../../docs/harness/artifact-guide.md#comments-shells-and-generated-files).
4. Prove execution prerequisites at preparation, test RED, completion, phase and project acceptance. Baseline capabilities need evidence; future inputs need correctly ordered producers. A tests task may produce its own declared bootstrap runner. [Behavioral RED](../../../docs/harness/evidence-guide.md#behavioral-red) permits minimal planned nonbehavioral scaffolding, requires an executable failed assertion for every tests task, and requires later stub replacement. Product behavior cannot be implemented during preparation.
5. Apply [domain-boundaries](../domain-boundaries/SKILL.md): assign applicable provider, consumer, adapter and verification ownership for each frozen call, type import and composition export, with first-due and cumulative checks. Module-local implementation checks also need source, task and phase coverage when no interaction exists. Qualify future evidence transport with disposable samples; currently due evidence must already exist.
6. Use [plan-verticals](../plan-verticals/SKILL.md) for the producer DAG and shared-task memberships, then [plan-phases](../plan-phases/SKILL.md) for dependency-closed phases and **tests → deletion → modification → addition → documentation** barriers. Reject cycles and unsafe shared writes. Each phase must have a useful truthful outcome without future dependencies, due NFRs, regression checks and recovery behavior.
7. Generate the implementation matrix from canonical task/spec data, covering requirements, specifications, elements/operations, scenarios, verticals, phases and planned checks. Do not maintain a second editable matrix. Check every behavior's implementation/test ownership or preserved-baseline evidence.
8. Commit the complete plan, validate and run `readiness plan`. Obtain distinct semantic and execution reviews of every task/phase and their intermediate states, including exact runners, hosts, write sites and real RED feasibility. Use disposable materialization/provisioning probes. Preserve finding history; fix and re-review the same candidate before `plan freeze`.
9. Run `prepare` and `anchors verify`; inspect all primary/secondary packets, safe shells and sidecars. It enters `preparing`. Commit and push the materialized baseline, dispatch preparation CI at that exact SHA, import real hosted/native prerequisite evidence, and run `readiness preparation`.
10. Both final review perspectives now inspect the committed materialization and actual receipts. Only passing `gate preparation` grants `prepared`. Missing proof leaves the workflow incomplete; no label or schema success replaces it.

## Projection and exit conditions

[Canonical marker rules](../../../docs/harness/artifact-guide.md#comments-shells-and-generated-files) require full primary packets, local secondary instructions, exact site identity and safe encoding. Initial placement selectors must be unique. Noncommentable/deletion targets use adjacent sidecars; frozen/generated interfaces remain read-only. Never create bogus manifests/binaries or remove packets to simulate completion.

The full backlog must be hydrated, category-compatible, dependency-closed and independently accepted, with complete work-site and behavior coverage. Reproduction preserves frozen contract bytes. No production task has been performed. Record blockers through the controller and follow [context-integrity](../context-integrity/SKILL.md) for bounded handoffs and source freshness.

Read [the preparation example](references/preparation-example.md) for category conflicts and valid repair.
