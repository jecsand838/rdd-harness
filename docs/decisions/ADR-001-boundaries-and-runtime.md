# ADR-001: one collection domain, Rust UI and local generated contracts

Status: selected in regenerate run R20261008T061841Z-666065, 2026-10-08; contingent on the recorded qualification checks passing before freeze.

## Context and options

FR-001–025 share one collection's identity, validation, query, capacity and replacement rules. NFR-TECH-001–004 require Rust, Tauri 2 and actual embedded `turso`; NFR-ARCH-001–002 require generated interfaces and controlled local access. The repository has no existing Todo owner to extend. A module per operation/table would split invariant ownership. A native-widget alternative would conflict with Tauri UI constraints; handwritten JavaScript UI behavior would violate the Rust scope. A network service, cloud SDK, generic persistence framework and browser storage add out-of-scope capability.

## Selected design

Use one pure collection owner, one native application coordinator, dedicated storage/backup effect adapters, a Tauri composition/transport adapter and a Leptos Rust/WASM UI. Three build units plus the already generated contracts crate provide the required platform/dependency boundaries without a crate per service. `solution.md` owns the precise graph and operation semantics. The UI calls approved typed Protobuf operations over local Tauri byte IPC. Queries return bounded summaries; a separate GetTask retrieves one editor record, avoiding maximum-capacity full-content IPC. Native service providers implement generated traits; WASM consumes generated messages through checked typed transport.

Native admission owns one pending mutation and drives accepted work to a known result. Explicit session/operation IDs, latest durable transaction receipt and current-session replay tracking distinguish repeated activation, deliberate equal-content creates and uncertain commit outcomes. Wall-clock timestamps may move backward. Calendar dates remain date-only. Unicode 16 default full case folding follows NFC only for search.

## Consequences and evidence

Contracts under `contracts/todo/v1/` and their generated inventory are freeze inputs. Contract and consumer proof verifies shapes/signatures; the separate real packaged invoke experiment qualifies runtime interoperability. Application behavior is future acceptance. Every invariant has one implementation owner; architecture tests must exercise negative bypass fixtures. `dependencies.md`, `reference-host.json`, `functional-analysis.md` and `quality.md` document sources, versions and verification. Routine mechanisms were researched autonomously under the user's workflow authorization; no product requirement was amended.
