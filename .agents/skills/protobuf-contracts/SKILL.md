---
name: protobuf-contracts
description: Design, compile, generate, or verify frozen Protobuf module and local application API contracts with Rust message bindings and service signatures. Use for specification contract work, preparation materialization, compatibility checks, and implementation boundary enforcement; no network service is implied.
---

# Protobuf contracts

Read the active workflow authority. Specification owns interface design and amendments. Preparation materializes and verifies the exact approved source. Implementation consumes it; a needed field, operation, or semantic change is a specification blocker.

## Procedure

1. Specify cohesive module interfaces and the local UI-facing API. Define operation input/output, error meanings, ownership, validation, presence, ordering, limits, idempotency, admission, commit point, and cancellation separately from wire syntax.
2. Use versioned packages, stable field numbers, explicit optional/oneof choices, safe enum defaults, and reserved deleted field numbers/names. Never reuse a tag. Model calendar dates distinctly from UTC instants and preserve unknown/invalid input handling at native boundaries.
3. Pin Buf, Rust, Prost, generator source/configuration, and dependency locks. Qualify generated native and Rust/WASM consumers together. Keep generated messages free of Tauri, storage, and network runtime dependencies.
4. Generate both message shapes and operation signatures. The supplied `tools/proto-codegen` uses Prost's `ServiceGenerator` to emit local unary traits. Message compilation alone cannot enforce service methods. Implement providers through those generated traits and compile real callers against them.
5. Run Buf lint/build, generated-source drift checks, signature positive/negative proof, consumer/provider compilation, and semantic contract tests. For amendments, compare against the accepted baseline with the approved breaking-change policy.
6. Freeze every authoritative source and generator input in the specification's contract inventory, including root configuration paths. During preparation regenerate deterministically and compile without changing the schema. Never edit generated Rust to make it match an implementation.

## Commands

Run from the repository root. Use these only in the authorized workflow stage:

```sh
# First authorized generation: resolve locks, generate, and compile.
python3 tools/rdd/proto_traits.py --write --bootstrap-lock --target wasm32-unknown-unknown
# Subsequent deterministic verification; no generated-source mutation.
python3 tools/rdd/proto_traits.py --target wasm32-unknown-unknown
```

Commit the generated crate and both Cargo.lock files after first qualification. Missing Rust/Buf/target/dependency access is blocked evidence. Read [contract design](references/contracts.md) and [generation](references/generation.md) before selecting adapters or changing generator behavior.
