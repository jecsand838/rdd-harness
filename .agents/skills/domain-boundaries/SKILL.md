---
name: domain-boundaries
description: Derive cohesive domain modules and explicit Protobuf-enforced interfaces from functional requirements, invariants, and ownership. Use during RDD specification and architectural amendments; avoid guessing modules from UI pages or database tables.
---

# Domain boundaries

Read the complete functional requirements, shared vocabulary, data rules, and relevant NFRs. Read [the boundary example](references/boundary-example.md) for a worked split and rejected over-abstraction.

## Derive modules

1. Extract commands, queries, state transitions, business invariants, identities, and lifecycle rules. Group rules that must change together or be enforced atomically. Identify terms that have distinct meanings in different contexts.
2. Assign each invariant one authoritative owner. Record callers and data owners. Avoid a module per noun, table, endpoint, screen, or requirement ID. A small coherent domain can remain one module.
3. Separate domain behavior from transport and storage adapters. A Tauri command is an entry adapter; a database SDK is infrastructure. They do not automatically warrant a new business domain. Keep the actual number of Rust crates proportional to independently enforced boundaries, dependency isolation, and compilation needs.
4. Draw the directed dependency graph. Select one direction for domain/application/adapters, prohibit cycles, and identify shared types by semantic ownership. A generic `common` module is not a dumping ground. Move a type to a shared contract only when its semantics are actually shared.
5. Specify every boundary operation: owner, authorized callers, requirements, input/output, errors, side effects, atomicity, concurrency, cancellation, retry semantics, versioning, availability, and required scenarios. Define what may be retried safely and how uncertainty is surfaced.
6. Express public and module boundary shapes in canonical Protobuf. Select explicit presence where absence is meaningful, reserved deleted tags/names, stable packages, meaningful enum zero values, and typed error/status shapes. Keep business invariants in semantic specification and validate them at the owning boundary.
7. Enforce interfaces in the generated language. Ensure generated message types are used at the boundary and generated traits/adapters expose the approved method signatures. Test registration and reachability of each operation as well as its behavior. Protobuf messages alone cannot forbid an unreviewed direct database call.
8. Plan architecture verification: dependency/import allowlists, restricted visibility, generated-interface implementations, transport registration inventory, and integration tests. Choose enforceable checks for the selected Rust workspace. Do not claim documentation establishes isolation.

## Keep abstractions small

Require a reason for each trait, generic parameter, crate, adapter, and factory. A trait is useful for a real behavioral boundary, multiple implementations, or test-controlled external effects. A trait for every struct and a factory for every constructor inflate navigation without proving a requirement. Prefer concrete owned state with cohesive receiver methods where that matches the domain; keep pure transformations as small functions when state ownership adds no value.

Do not serialize the entire internal object graph just to reuse it as an API. The generated transport shape can be converted to a domain type that enforces valid state. Keep conversion at one visible boundary and avoid duplicated validation logic.

## Required artifact

For each module record purpose, requirement IDs, owned invariants/data, provided operations, consumed contracts, forbidden dependencies, and verification. Explain the smallest viable module layout and alternatives rejected. Freeze these decisions in specification; preparation chooses task order, not different domain semantics.

## Primary references

- Rust visibility and modules: <https://doc.rust-lang.org/reference/visibility-and-privacy.html>.
- Rust traits and generics: <https://doc.rust-lang.org/rust-by-example/trait.html> and <https://doc.rust-lang.org/rust-by-example/generics.html>.
- Protobuf presence: <https://protobuf.dev/programming-guides/field_presence/>.
- Protobuf schema evolution: <https://protobuf.dev/programming-guides/proto3/#updating>.
- Buf compatibility checks: <https://buf.build/docs/breaking/>.

These references explain available mechanisms. Module allocation and invariants are project design decisions derived from the requirements.
