---
name: rust-domain-types
description: Design or refactor Rust domain code around private data, newtypes, enums, receiver methods, ownership, explicit errors, and justified traits or generics. Use for Rust business rules, boundary conversion, module APIs, or duplication and abstraction reviews in an RDD phase.
---

# Rust domain types

Read the applicable requirement IDs, approved domain specification, contract, and owned task before changing behavior. Treat examples in this skill as teaching examples, never as additional product requirements.

## Procedure

1. Locate the current rule owner with `rg`. Extend that owner before creating a helper, crate, trait, or service. Identify callers that must migrate and remove obsolete implementations within the phase.
2. Represent meaningful distinctions with types. Use a newtype when confusing two values is a real defect; use an enum when valid alternatives are finite. Keep invariant-bearing fields private. Validate construction and mutation, including deserialized input.
3. Put behavior that reads or changes a value on its owning type: `&self` for observation, `&mut self` for mutation, `self` for deliberate consumption. Prefer associated constructors returning `Result`. Keep sensible free functions for stateless algorithms and module orchestration; do not invent an empty struct to hold functions.
4. Keep ownership local. Borrow when no ownership transfer is needed; own data sent to a background task. Use `Arc` for actual shared ownership, not to suppress borrow-checker feedback. Do not clone whole collections merely to end a borrow without checking alternatives and cost.
5. Define errors at the layer that knows their meaning. Preserve internal causes, then map to the frozen public error vocabulary. Never leak SQL, paths, or task text through a public error. Use `Result` for expected failure; reserve panic for violated programmer invariants.
6. Introduce traits for a stable behavioral boundary, a genuine substitute, or controlled test inputs such as a clock. Start concrete otherwise. Use generics when static dispatch benefits callers; use `dyn Trait` when runtime heterogeneity or reduced type propagation earns its cost. Decide async trait `Send` and object-safety needs explicitly.
7. Convert generated transport types into validated domain values at the boundary. Generated fields being public does not make every representable message valid. Keep the generated service signature binding; avoid a second handwritten public API that can drift.

## Completion evidence

Run affected tests and configured Rust checks. Inspect public exports, new dependencies, unnecessary `pub`, clones, broad trait bounds, blanket conversions, and duplicate normalization. Record the changed rule owner and scenario IDs for the phase reviewer. Do not introduce a task-level approval gate.

Read [patterns](references/patterns.md) for original examples and primary sources.
