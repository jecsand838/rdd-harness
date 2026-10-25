---
name: domain-boundaries
description: Derive cohesive domain modules and explicit Protobuf-enforced interfaces from functional requirements, invariants, and ownership. Use during RDD specification and architectural amendments; avoid guessing modules from UI pages or database tables.
---

# Domain boundaries

Read the complete functional requirements, shared vocabulary, data rules, and relevant NFRs. Read [the boundary example](references/boundary-example.md) for a worked split and rejected over-abstraction.

## Derive modules

1. Extract commands, queries, state transitions, business invariants, identities, and lifecycle rules. Group rules that must change together or be enforced atomically. Identify terms that have distinct meanings in different contexts.
2. Assign each invariant one authoritative owner. Record callers and data owners. Avoid a module per noun, table, endpoint, screen, or requirement ID. Each accepted functional subdomain has one distinct owner module; several accepted subdomains cannot share a module. Correct the S1 inventory through its owner if the discovered split is wrong.
3. Separate domain behavior from transport and storage adapters. A Tauri command is an entry adapter; a database SDK is infrastructure. They do not automatically warrant a new business domain. Start with private implementation modules inside shared crates. Add separate implementation crates only when dependency isolation or independent builds require them. Explicit supporting owners cover entry adapters, presentation, orchestration, build support, infrastructure and shared types; they cannot own business invariants or replace a functional domain.
4. Draw the directed dependency graph. Select one direction for domain/application/adapters, prohibit cycles, and identify shared types by semantic ownership. A generic `common` module is not a dumping ground. Move a type to a shared contract only when its semantics are actually shared.
5. Specify every boundary operation: owner, authorized callers, requirements, input/output, errors, side effects, atomicity, concurrency, cancellation, retry semantics, versioning, availability, and required scenarios. Define what may be retried safely and how uncertainty is surfaced.
6. Express public and internal module boundary data and callable operations in canonical Protobuf. Give functional domain contracts separate packages within the existing generated contract crate. Type-only imports declare owned generated types and their source without inventing a service or operation. Select explicit presence where absence is meaningful, reserved deleted tags/names, stable packages, meaningful enum zero values, and typed error/status shapes. Keep business invariants in semantic specification and validate them at the owning boundary.
7. Enforce interfaces in the generated language. Ensure generated message types are used at the boundary and generated traits/adapters expose the approved method signatures. Test registration and reachability of each operation as well as its behavior. Protobuf messages alone cannot forbid an unreviewed direct database call.
8. Separate disposable specification qualification from real implementation conformance: dependency/import allowlists, restricted visibility, generated-interface implementations, registration and bypass tests. `pub(crate)` does not isolate sibling domains. Use narrower organization or justified crate boundaries and test actual forbidden access. Preserve four distinct enforcement layers: generated shape, real boundary use, behavioral semantics and operational evidence.

## Keep abstractions small

Require a reason for each trait, generic parameter, crate, adapter, and factory. A trait is useful for a real behavioral boundary, multiple implementations, or test-controlled external effects. A trait for every struct and a factory for every constructor inflate navigation without proving a requirement. Prefer concrete owned state with cohesive receiver methods where that matches the domain; keep pure transformations as small functions when state ownership adds no value.

Do not serialize the entire internal object graph just to reuse it as an API. The generated transport shape can be converted to a domain type that enforces valid state. Keep conversion at one visible boundary and avoid duplicated validation logic.

## Required artifact

Draft the complete target folder system during specification, including application owners and build/test/fixture/evaluator/packaging/documentation homes. Identify functional subdomains from the requirements and inventory every positive and failure behavior. Each functional requirement has an owner and golden scenarios; every positive operation has its own golden coverage. Keep exact behavior/scenario links reciprocal. A subdomain does not automatically require another crate.

S1 authors `docs/specs/domain-inventory.json` under the domain-inventory schema. Give domains stable IDs, distinct module owners, allocated requirements, behavior IDs and invariant IDs. Record supporting owners separately and enumerate directed interactions with exact consumer/provider module IDs, distinguishing `call`, `type_only` and `composition`. Only supporting `orchestration` owners may consume composition; record their initialization, registration, failure and lifecycle behaviors under that owner, with no business invariants or callable behaviors on the composition interaction. Record the complete artifact through S1; incomplete ownership or unresolved references cannot complete that node.

S6 references the accepted S1 artifact, its file hash and output digest. Preserve every identity and allocation; corrections return to S1 and invalidate downstream handoffs. Bind each interaction exclusively to descriptor `operations` for calls, generated `types` for imports, or `exports` for composition. Composition exports resolve to the provider's existing null-bound `construction`/`wiring` entries with owned Rust paths and frozen semantics; the provider must expose a genuine generated interface. A pair that both constructs and calls needs both interactions. Exact dependencies, provided/consumed ownership and cycle checks still apply. Never invent unused types, dummy RPCs or omit dependencies to satisfy validation.

For every module freeze distinct implementation paths, public exports, contract package, provided services/types, consumed operations/types, allowed dependencies and linked behavioral/adapter semantics. Expose only the approved interface and construction/wiring entry points; keep concrete implementations private. Generated request/response types enforce shapes, while private validated domain types own invariants. Preserve async owned-request, `Send` future and `Send + Sync` provider constraints; use concrete or generic consumers.

Qualification and actual boundary adoption are separate obligations. Compile the approved construction surface with a real consumer and prove the result exposes its intended generated interface. Execute registration/reachability, initialization failures and lifecycle semantics; reject private implementation/storage access and business calls disguised as construction. Rust visibility alone cannot restrict an arbitrary sibling caller. Require dependency/bypass checks against the actual allowed exports.

Preparation identifies each proof by interaction, consumer, provider and operation or export; type imports retain separate source/compile coverage. Every consumer needs its own owned source/tasks and verification. An unchanged provider may use verified baseline source; otherwise its exact export source needs production ownership. Checks consume both sources and run at first delivery, then cumulatively. Use existing leases to replace only approved implementation paths against unchanged consumers and frozen contracts. Contract changes return to specification.

Private helpers need no artificial contracts. Explain the smallest viable module layout and rejected alternatives. Preparation chooses task order, not different domain semantics. See `docs/harness/artifact-guide.md` and the schemas for machine fields rather than duplicating format definitions here.

## Primary references

- Rust visibility and modules: <https://doc.rust-lang.org/reference/visibility-and-privacy.html>.
- Rust traits and generics: <https://doc.rust-lang.org/rust-by-example/trait.html> and <https://doc.rust-lang.org/rust-by-example/generics.html>.
- Protobuf presence: <https://protobuf.dev/programming-guides/field_presence/>.
- Protobuf schema evolution: <https://protobuf.dev/programming-guides/proto3/#updating>.
- Buf compatibility checks: <https://buf.build/docs/breaking/>.

These references explain available mechanisms. Module allocation and invariants are project design decisions derived from the requirements.
