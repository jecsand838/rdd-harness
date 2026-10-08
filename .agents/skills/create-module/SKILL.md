---
name: create-module
description: Create or extend an approved Rust domain module or Cargo package with cohesive types, restricted exports, generated contract binding, tests, and dependency boundaries. Use for module/package tasks or when deciding whether existing code should be extended instead of adding a module.
---

# Create or extend a module

Read the module inventory, target folder plan, contract, vertical dependencies, and owned task. During implementation, module ownership and external interfaces are frozen. Missing or conflicting architecture is a specification blocker.

## Procedure

1. Search existing crates, types, traits, dependencies, and callers. State the behavior the current owner cannot accommodate before adding a module. Prefer modification when it preserves cohesion; do not fold unrelated domains together solely to reduce file count.
2. Use the smallest approved compilation boundary. A Rust module is not automatically a Cargo package. Create a new package only for the approved isolation, independent dependency graph, or distinct target. Avoid one crate per entity or one generic shared crate for unrelated helpers.
3. Materialize the target layout from the plan. Register workspace membership, package metadata, dependencies, test targets, and generator inputs explicitly. Keep UI/WASM and native dependencies separated so the domain builds without Tauri or storage.
4. Put state and invariants on owning structs/enums/newtypes. Keep internal modules private and export only the approved API through `lib.rs`. Implement generated service traits or generator-bound adapters; keep transport-to-domain conversion at the boundary.
5. Add requirement-derived tests first for the phase. Then delete superseded paths, modify existing implementations, add the justified missing code, and finish documentation. Preserve dependency ordering within that category policy.
6. Wire actual callers. An unused new package and its passing isolated tests do not implement a user-visible requirement. Migrate old callers and remove duplicate rule owners.

## Completion evidence

Run affected target builds/tests and the architecture checks. Record public exports, dependency changes, actual callers, and requirement purpose. Leave generated files reproducible and the module registered in the implementation matrix. Do not edit frozen specifications to match an unplanned module.

Read [module patterns](references/module.md) for an example layout and boundary checks. Apply `rust-domain-types`, `protobuf-contracts`, and `rust-testing` only as needed.
