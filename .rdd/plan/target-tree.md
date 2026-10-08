# Target tree and ownership

Safe intended materialization: comment-only approved source shells, while absent manifests/JSON/locks/binaries/SQL remain absent and are represented by their owner task sidecar. The corrected and frozen controller permits those sidecar targets without creating invalid reservation files. See `preparation-blocker.md` for amendment provenance.

| Path | Baseline / transition | Role and ordered owners | Preparation handling |
| --- | --- | --- | --- |
| CONTRIBUTING.md | Existing documentation modified | T021; Document reproducible build verification dependencies and revision evidence handoff | Preserve content; append marker only if selected inline anchor |
| Cargo.lock | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Remain absent; owner task sidecar only |
| Cargo.toml | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Remain absent; owner task sidecar only |
| README.md | Existing documentation modified | T021; Document reproducible build verification dependencies and revision evidence handoff | Preserve content; append marker only if selected inline anchor |
| apps/README.md | Existing documentation modified | T021; Document reproducible build verification dependencies and revision evidence handoff | Preserve content; append marker only if selected inline anchor |
| apps/desktop/Cargo.toml | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Remain absent; owner task sidecar only |
| apps/desktop/build.rs | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Comment-only unimported shell |
| apps/desktop/capabilities/main.json | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Remain absent; owner task sidecar only |
| apps/desktop/icons/icon.png | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Remain absent; owner task sidecar only |
| apps/desktop/permissions/application.toml | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Remain absent; owner task sidecar only |
| apps/desktop/src/commands.rs | Added during implementation | T017; Add native command adapters and desktop composition with release restrictions | Comment-only unimported shell |
| apps/desktop/src/diagnostics.rs | Added during implementation | T015; Add bounded private diagnostic events without operation dependencies | Comment-only unimported shell |
| apps/desktop/src/instance.rs | Added during implementation | T016; Add account and data-directory lease with acknowledged window activation | Comment-only unimported shell |
| apps/desktop/src/lib.rs | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Comment-only unimported shell |
| apps/desktop/src/main.rs | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Comment-only unimported shell |
| apps/desktop/src/runtime.rs | Added during implementation | T017; Add native command adapters and desktop composition with release restrictions | Comment-only unimported shell |
| apps/desktop/tauri.conf.json | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Remain absent; owner task sidecar only |
| apps/ui/Cargo.toml | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Remain absent; owner task sidecar only |
| apps/ui/index.html | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Comment-only unimported shell |
| apps/ui/resources/help.md | Added during implementation | T020; Write bundled offline help and user backup compatibility guide | Comment-only unimported shell |
| apps/ui/src/dialogs.rs | Added during implementation | T019; Add accessible offline Todo views editors dialogs and text resizing | Comment-only unimported shell |
| apps/ui/src/editor.rs | Added during implementation | T019; Add accessible offline Todo views editors dialogs and text resizing | Comment-only unimported shell |
| apps/ui/src/lib.rs | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Comment-only unimported shell |
| apps/ui/src/state.rs | Added during implementation | T018; Add typed Rust UI transport and draft query mutation state machines | Comment-only unimported shell |
| apps/ui/src/styles.css | Added during implementation | T019; Add accessible offline Todo views editors dialogs and text resizing | Comment-only unimported shell |
| apps/ui/src/transport.rs | Added during implementation | T018; Add typed Rust UI transport and draft query mutation state machines | Comment-only unimported shell |
| apps/ui/src/views.rs | Added during implementation | T019; Add accessible offline Todo views editors dialogs and text resizing | Comment-only unimported shell |
| benchmarks/README.md | Existing documentation modified | T021; Document reproducible build verification dependencies and revision evidence handoff | Preserve content; append marker only if selected inline anchor |
| contracts/fixtures/D1-oracle.json | Existing, frozen read-only input | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| contracts/fixtures/D1.json | Existing, frozen read-only input | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| contracts/fixtures/D2-oracle.json | Existing, frozen read-only input | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| contracts/fixtures/D2.json | Existing, frozen read-only input | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| contracts/qualification-inputs.json | Existing, frozen read-only input | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| contracts/rdd/v1/harness.proto | Existing, frozen read-only input | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| contracts/todo/v1/application.proto | Existing, frozen read-only input | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| contracts/todo/v1/backup.proto | Existing, frozen read-only input | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| contracts/todo/v1/collection.proto | Existing, frozen read-only input | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| contracts/todo/v1/model.proto | Existing, frozen read-only input | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| contracts/todo/v1/storage.proto | Existing, frozen read-only input | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| docs/compatibility.md | Added during implementation | T020; Write bundled offline help and user backup compatibility guide | Comment-only unimported shell |
| docs/dependency-inventory.md | Added during implementation | T021; Document reproducible build verification dependencies and revision evidence handoff | Comment-only unimported shell |
| docs/developer-guide.md | Added during implementation | T021; Document reproducible build verification dependencies and revision evidence handoff | Comment-only unimported shell |
| docs/release-handoff.md | Added during implementation | T021; Document reproducible build verification dependencies and revision evidence handoff | Comment-only unimported shell |
| docs/user-guide.md | Added during implementation | T020; Write bundled offline help and user backup compatibility guide | Comment-only unimported shell |
| gen/rust/.rdd-generated.json | Existing, frozen read-only generated interface | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| gen/rust/Cargo.lock | Existing, frozen read-only generated interface | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| gen/rust/Cargo.toml | Existing, frozen read-only generated interface | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| gen/rust/src/generated/rdd.v1.rs | Existing, frozen read-only generated interface | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| gen/rust/src/generated/todo.v1.rs | Existing, frozen read-only generated interface | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| gen/rust/src/lib.rs | Existing, frozen read-only generated interface | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| modules/README.md | Existing documentation modified | T021; Document reproducible build verification dependencies and revision evidence handoff | Preserve content; append marker only if selected inline anchor |
| modules/core/Cargo.toml | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Remain absent; owner task sidecar only |
| modules/core/src/application/admission.rs | Added during implementation | T014; Add application admission, committed outcomes and owned asynchronous lifecycle | Comment-only unimported shell |
| modules/core/src/application/lifecycle.rs | Added during implementation | T014; Add application admission, committed outcomes and owned asynchronous lifecycle | Comment-only unimported shell |
| modules/core/src/application/mod.rs | Added during implementation | T014; Add application admission, committed outcomes and owned asynchronous lifecycle | Comment-only unimported shell |
| modules/core/src/backup/format.rs | Added during implementation | T013; Add retained backup candidates and crash-safe selected-file publication | Comment-only unimported shell |
| modules/core/src/backup/mod.rs | Added during implementation | T013; Add retained backup candidates and crash-safe selected-file publication | Comment-only unimported shell |
| modules/core/src/backup/publication.rs | Added during implementation | T013; Add retained backup candidates and crash-safe selected-file publication | Comment-only unimported shell |
| modules/core/src/backup/selection.rs | Added during implementation | T013; Add retained backup candidates and crash-safe selected-file publication | Comment-only unimported shell |
| modules/core/src/collection/mod.rs | Added during implementation | T011; Add the single invariant-owning collection and deterministic selection provider | Comment-only unimported shell |
| modules/core/src/collection/query.rs | Added during implementation | T011; Add the single invariant-owning collection and deterministic selection provider | Comment-only unimported shell |
| modules/core/src/collection/types.rs | Added during implementation | T011; Add the single invariant-owning collection and deterministic selection provider | Comment-only unimported shell |
| modules/core/src/lib.rs | Added during implementation; later planned extension/replacement | T001 → T010; Bootstrap runnable native-boundary assertions and exact locked build harness, Replace test bootstrap providers with final source entry and packaging wiring | Comment-only unimported shell |
| modules/core/src/storage/mod.rs | Added during implementation | T012; Add sole embedded Turso owner with preflight and atomic receipt recovery | Comment-only unimported shell |
| modules/core/src/storage/preflight.rs | Added during implementation | T012; Add sole embedded Turso owner with preflight and atomic receipt recovery | Comment-only unimported shell |
| modules/core/src/storage/receipts.rs | Added during implementation | T012; Add sole embedded Turso owner with preflight and atomic receipt recovery | Comment-only unimported shell |
| modules/core/src/storage/schema.sql | Added during implementation | T012; Add sole embedded Turso owner with preflight and atomic receipt recovery | Remain absent; owner task sidecar only |
| rust-toolchain.toml | Existing, frozen read-only input | Boundary/fixture/toolchain qualification input | Never a task write/shell/anchor |
| tests/acceptance/Cargo.lock | Added during implementation | T001; Bootstrap runnable native-boundary assertions and exact locked build harness | Remain absent; owner task sidecar only |
| tests/acceptance/Cargo.toml | Added during implementation | T001; Bootstrap runnable native-boundary assertions and exact locked build harness | Remain absent; owner task sidecar only |
| tests/acceptance/README.md | Existing documentation modified | T021; Document reproducible build verification dependencies and revision evidence handoff | Preserve content; append marker only if selected inline anchor |
| tests/acceptance/fixtures/instance-child/Cargo.lock | Added during implementation | T005; Assert instance arbitration, startup, close and local help lifecycle | Remain absent; owner task sidecar only |
| tests/acceptance/fixtures/instance-child/Cargo.toml | Added during implementation | T005; Assert instance arbitration, startup, close and local help lifecycle | Remain absent; owner task sidecar only |
| tests/acceptance/fixtures/instance-child/src/main.rs | Added during implementation | T005; Assert instance arbitration, startup, close and local help lifecycle | Comment-only unimported shell |
| tests/acceptance/fixtures/recovery-child/Cargo.lock | Added during implementation | T004; Assert durable acknowledgment, real commit interruption and storage preservation | Remain absent; owner task sidecar only |
| tests/acceptance/fixtures/recovery-child/Cargo.toml | Added during implementation | T004; Assert durable acknowledgment, real commit interruption and storage preservation | Remain absent; owner task sidecar only |
| tests/acceptance/fixtures/recovery-child/src/main.rs | Added during implementation | T004; Assert durable acknowledgment, real commit interruption and storage preservation | Comment-only unimported shell |
| tests/acceptance/src/backup_fixtures.rs | Added during implementation | T003; Assert real backup parsing, publication and replacement boundaries | Comment-only unimported shell |
| tests/acceptance/src/commit_gate.rs | Added during implementation | T004; Assert durable acknowledgment, real commit interruption and storage preservation | Comment-only unimported shell |
| tests/acceptance/src/fixtures.rs | Added during implementation | T001; Bootstrap runnable native-boundary assertions and exact locked build harness | Comment-only unimported shell |
| tests/acceptance/src/ledger.rs | Added during implementation | T004; Assert durable acknowledgment, real commit interruption and storage preservation | Comment-only unimported shell |
| tests/acceptance/src/lib.rs | Added during implementation | T001; Bootstrap runnable native-boundary assertions and exact locked build harness | Comment-only unimported shell |
| tests/acceptance/tests/backup.rs | Added during implementation | T003; Assert real backup parsing, publication and replacement boundaries | Comment-only unimported shell |
| tests/acceptance/tests/capacity.rs | Added during implementation | T006; Assert full capacity and implement independent P1 P2 P3 evaluators | Comment-only unimported shell |
| tests/acceptance/tests/diagnostics.rs | Added during implementation | T008; Assert private bounded diagnostics and failure-independent operations | Comment-only unimported shell |
| tests/acceptance/tests/functional.rs | Added during implementation; later planned extension/replacement | T001 → T009; Bootstrap runnable native-boundary assertions and exact locked build harness, Assert direct invalid command inputs and implement security and handoff evaluators | Comment-only unimported shell |
| tests/acceptance/tests/lifecycle.rs | Added during implementation | T005; Assert instance arbitration, startup, close and local help lifecycle | Comment-only unimported shell |
| tests/acceptance/tests/pending.rs | Added during implementation | T007; Assert pending responsiveness and accessibility feedback through native observation | Comment-only unimported shell |
| tests/acceptance/tests/query.rs | Added during implementation | T002; Assert exact query, paging and calendar-independent selection oracles | Comment-only unimported shell |
| tests/acceptance/tests/recovery.rs | Added during implementation | T004; Assert durable acknowledgment, real commit interruption and storage preservation | Comment-only unimported shell |
| tests/architecture/check.py | Added during implementation | T001; Bootstrap runnable native-boundary assertions and exact locked build harness | Comment-only unimported shell |
| tests/desktop/accessibility.py | Added during implementation | T007; Assert pending responsiveness and accessibility feedback through native observation | Comment-only unimported shell |
| tests/desktop/benchmark.py | Added during implementation | T006; Assert full capacity and implement independent P1 P2 P3 evaluators | Comment-only unimported shell |
| tests/desktop/evaluator.py | Added during implementation | T006; Assert full capacity and implement independent P1 P2 P3 evaluators | Comment-only unimported shell |
| tests/desktop/manual-protocols.md | Added during implementation | T005; Assert instance arbitration, startup, close and local help lifecycle | Comment-only unimported shell |
| tests/desktop/observer/Cargo.lock | Added during implementation | T006; Assert full capacity and implement independent P1 P2 P3 evaluators | Remain absent; owner task sidecar only |
| tests/desktop/observer/Cargo.toml | Added during implementation | T006; Assert full capacity and implement independent P1 P2 P3 evaluators | Remain absent; owner task sidecar only |
| tests/desktop/observer/src/main.rs | Added during implementation | T006; Assert full capacity and implement independent P1 P2 P3 evaluators | Comment-only unimported shell |
| tests/desktop/security.py | Added during implementation | T009; Assert direct invalid command inputs and implement security and handoff evaluators | Comment-only unimported shell |
| tests/desktop/test_evaluator.py | Added during implementation | T006; Assert full capacity and implement independent P1 P2 P3 evaluators | Comment-only unimported shell |
| tests/integration/README.md | Existing documentation modified | T021; Document reproducible build verification dependencies and revision evidence handoff | Preserve content; append marker only if selected inline anchor |
| tests/release/build.py | Added during implementation | T001; Bootstrap runnable native-boundary assertions and exact locked build harness | Comment-only unimported shell |
| tests/release/handoff.py | Added during implementation | T009; Assert direct invalid command inputs and implement security and handoff evaluators | Comment-only unimported shell |

Shared files are serialized: T001 → T010 for application scaffold paths and T001 → T009 for functional.rs. Other writes are disjoint. Read-only generated/contracts/qualification paths have no implementation write owner. No deletion is justified because there is no previous Todo application.
