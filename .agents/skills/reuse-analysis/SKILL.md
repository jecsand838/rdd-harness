---
name: reuse-analysis
description: Inspect an existing codebase for safe reuse and extension before planning additions, detect logical duplication and speculative abstractions, and justify each addition. Use during RDD preparation, implementation within frozen scope, and bloat review.
---

# Reuse analysis

Start from a required behavior and its invariants. Search the repository with `rg` and inspect callers, tests, visibility, ownership, and errors. Read [the reuse example](references/reuse-example.md) for a concrete decision record.

## Decide the smallest coherent change

1. Search by behavior, type, error, operation, and test oracle, not just the proposed class name. Inspect the existing module boundary and integration path. Record actual paths and symbols examined.
2. Identify the authoritative owner of the business rule. Prefer extending that owner when semantics, lifecycle, and dependencies align. Do not build a second validator or service merely to avoid understanding the first.
3. Compare three concrete options where applicable: modify existing code, extract a shared operation from observed duplication, or add a new component. Evaluate preserved behavior, dependency direction, test impact, migration risk, complexity, and navigation cost.
4. Distinguish coincidental similarity from shared semantics. Two five-line functions may be clearer than a generic abstraction with unrelated modes. Extract when the invariant or contract is shared, not to minimize line count mechanically.
5. Keep cohesive state and operations together. Prefer structs/enums with methods for owned state and invariants. Preserve small pure functions for stateless transformations. A blanket ban on functions would produce artificial objects and more bloat.
6. For every addition, record why existing components cannot satisfy the objective cleanly, why the new boundary is the smallest appropriate one, its requirement IDs, its callers, and how it avoids a second source of truth.
7. For every deletion, inspect transitive callers, exports, tests, docs, configuration, and migration history. Remove obsolete code deliberately; retain historical migrations when required to read existing data.
8. Surface uncertain semantic ownership or a needed contract change as a specification blocker. Implementation may optimize within approved boundaries; it cannot invent a new domain to bypass them.

## Reject common bloat patterns

Reject an unneeded repository trait wrapping an identical repository trait, a builder for a type with one construction path, a generic event bus for one caller, duplicated UI/native validation rules with no authoritative common owner, a `utils` module collecting unrelated behavior, and fake extension points without a requirement-backed use case.

Do not use a raw line-count cap as the sole quality metric. Record module and dependency counts, duplicate rule locations, public surface area, layering, unused abstractions, and unresolved scaffolds alongside the reason for the change.

## Output

Create a concise reuse rationale for the task. Keep it with the canonical plan before freeze and include its conclusion in phase review. Approval of an addition is a deliberate planning decision; it does not require an extra per-task human review gate.
