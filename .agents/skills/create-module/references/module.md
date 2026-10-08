# Module structure

This is an example shape, not a mandate to create these exact Todo modules. The approved target tree determines real paths and package names.

| Path | Responsibility |
|---|---|
| `modules/task-domain/Cargo.toml` | Small approved package and dependency list |
| `modules/task-domain/src/lib.rs` | Narrow public reexports |
| `modules/task-domain/src/task.rs` | State transitions and invariant owner |
| `modules/task-domain/src/title.rs` | Validated value type if it earns its own file |
| `modules/task-domain/src/error.rs` | Domain errors, if substantial enough to separate |
| `modules/task-domain/tests/public_behavior.rs` | Public-boundary behavior |
| `modules/task-storage/src/lib.rs` | Native persistence adapter, if approved separately |

Keep a small module in one file when splitting adds navigation without separation. Do not generate empty `service`, `repository`, `factory`, `manager`, and `utils` layers by convention.

## Bad: broad exports and hidden coupling

```rust
pub mod sql;
pub mod task;
pub mod ui_helpers;
pub use sql::*;
pub use task::*;
pub use ui_helpers::*;
```

Every consumer can bypass the intended boundary and depend on storage details.

## Better: expose the designed surface

```rust
mod task;
mod title;
mod error;

pub use task::{Task, Completion};
pub use title::Title;
pub use error::DomainError;
```

Use `pub(crate)` for cross-module internals only when justified. Keep the generated contract crate's public types separate from private invariants, with explicit conversions at approved boundaries. Do not grant callers access to a connection handle merely to avoid adding a required operation to the specification.

## Ownership test

For every proposed type or package, answer:

1. Which accepted requirement or supporting constraint needs it?
2. Which business rule does it own, and where is that rule currently implemented?
3. Which callers use its approved interface?
4. Which dependencies are permitted to point to it?
5. Which dependency or API change should fail an architecture check?

If the only answer is hypothetical future reuse, keep the implementation concrete and local. If two current callers have similar code with different semantics, do not force them through a flag-driven abstraction.

## Primary references

Checked 2026-10-07.

- [Rust modules](https://doc.rust-lang.org/rust-by-example/mod.html)
- [Cargo workspaces](https://doc.rust-lang.org/cargo/reference/workspaces.html)
- [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/about.html)
- [Prost generated service interfaces](https://docs.rs/prost-build/latest/prost_build/trait.ServiceGenerator.html)
