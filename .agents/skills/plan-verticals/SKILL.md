---
name: plan-verticals
description: Convert scoped implementation tasks into a producer-consumer dependency DAG and ordered verticals with explicit prerequisites, shared tasks, conflict ownership, and cycle diagnostics. Use in RDD preparation before assigning phases.
---

# Plan verticals

Use [the graph example](references/vertical-example.md) to inspect a complete mapping. Read `reuse-analysis` before finalizing additions. Read `plan-phases` only after establishing real task dependencies.

A **vertical** is an ordered mapping of tasks that realizes a behavior or capability. It can cross tests, domain code, infrastructure, UI, and documentation. It is not a team or technology layer. Multiple verticals can share one prerequisite task; do not duplicate that task or its logic.

## Build the graph

1. Inventory the frozen requirements, solution elements, scenarios, operations, accepted baseline, and specification-owned target folder tree. Split work into tasks with a concrete output, category, allowed write set, and observable completion evidence.
2. List each task's consumed and produced capabilities. Require a producer for every consumed capability: a verified baseline asset or another task. An empty file shell is not an implemented capability. A compiled contract is only a shape capability, not implemented business behavior.
3. Add prerequisite edges for real execution dependencies. Include shared schema/generator configuration, fixtures, command registration, error behavior, migrations, performance evaluators, and packaging. Add explicit ordering for conflicting writes or assign a single integration owner.
4. Check for unknown IDs, self-dependencies, duplicate producers with inconsistent meanings, unreachable tasks, and cycles. Explain a cycle using the actual task path. Combining cyclic tasks into one phase does not remove their dependency cycle.
5. Repair a false split by defining a legitimate atomic task within one category; split independent concerns more precisely; or return an actual architectural cycle to specification. Do not delete an edge merely to make sorting succeed.
6. Group paths by delivered behavior and identify shared prerequisite joins. Keep vertical order compatible with the global graph. The graph remains authoritative when two vertical presentations share tasks.
7. Record a bounded concurrency plan: tasks eligible together must have satisfied predecessors and disjoint write ownership. Use worktrees to isolate execution, but do not treat isolation as proof that semantic conflicts disappear.
8. Give the resulting graph to `plan-phases`, which adds category barriers and closure constraints. Revalidate the combined graph after phase assignment.

## Distinguish kinds of order

- **Authoring:** A failing test can be written before feature behavior exists.
- **Compilation:** A generated type or minimal approved scaffold may be required for that test binary to run.
- **Runtime:** A data migration may require expansion, conversion, and contraction in a specific order.
- **Acceptance:** A phase cannot claim a behavior while the only operation implementation is a stub.

Do not collapse these into one misleading edge. Specify the actual prerequisite and which stage supplies it. If strict category order makes the plan impossible, expose the conflict rather than weakening TDD or relabeling categories.

## Completion

Every task appears in the graph and at least one vertical. Every consumed capability has evidence of a producer. Every task's write scope is unambiguous and every write has a co-located work site. Exactly one full primary packet and all secondary local references are defined; sorted vertical memberships are projected by the controller, not copied by hand. The DAG is acyclic, and its topological order supports meaningful phase boundaries. The implementation matrix preserves many-to-many requirement and scenario mappings rather than forcing each task to claim exactly one requirement.

The controller performs mechanical graph checks. The planner and independent reviewer must still detect missing semantic edges. A topological sort cannot discover an omitted prerequisite.
