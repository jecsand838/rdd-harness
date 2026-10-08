# DEP-001 — pinned dependency qualification

Run `R20261008T061841Z-666065`; requirement baseline `151aa83117a87e886c076b07ac0599f3347d2f24`, TODO-REQ revision 2. Access date for every source below: **2026-10-08**. Research artifacts are disposable capability probes, not Todo implementation or acceptance results.

## Decision and scope

Select stable Rust 1.99.0, Tauri 2.12.1, embedded `turso` 0.8.2, Tokio 1.53.2, and Leptos 0.8.22 client-side rendering on the required arm64 macOS host. Keep the database local and disable Turso optional sync, allocator and FTS features. Use Cargo plus wasm-bindgen directly; neither Trunk, an HTTP server, an ORM, a JS UI package, a router nor SSR is necessary. The repository baseline contains a pinned toolchain and Protobuf generator, but no reusable Todo production implementation.

Required callers are native application operations and a bundled Rust/WASM UI; sensitive data remains local. Governing requirements are NFR-TECH-001–004, NFR-ARCH-001–002, NFR-MAINT-001, NFR-PLAT-001, NFR-OFF-001, NFR-PRIV-001–002, NFR-DATA-001–004, NFR-SEC-001–002, FR-012, FR-016–024. Performance and accessibility remain application verification obligations, not properties established by choosing these dependencies.

## Exact selection

Each direct version is an exact `=version` Cargo dependency; commit the complete Cargo locks. MSRVs and licenses below come from the published package manifests / `cargo info`, and compilation uses stable 1.99.0.

| Direct dependency / tool | Exact version and selected features | Purpose | License / MSRV |
|---|---|---|---|
| Rust / Cargo | 1.99.0; `aarch64-apple-darwin`, `wasm32-unknown-unknown` | Stable native/WASM toolchain | MIT OR Apache-2.0; toolchain itself |
| `tauri` | 2.12.1; defaults off, `wry`, `compression`; release `custom-protocol` | Native WebView/runtime and approved command boundary | MIT OR Apache-2.0; 1.90 |
| `tauri-build` / `tauri-cli` | 2.7.1 / 2.12.1 | ACL generation and `.app` packaging | MIT OR Apache-2.0 |
| `tauri-plugin-dialog` | 2.8.1; defaults off | Native-only selected-file dialogs | MIT OR Apache-2.0; 1.90 |
| `turso` | 0.8.2; defaults off, no optional features | Authoritative persistent local engine | MIT; published MSRV unspecified, native compile measured |
| `tokio` | 1.53.2; `rt-multi-thread`, `sync`, `time`, `macros` for probes/tests | Tauri's shared runtime, bounded admission / owned async work | MIT; 1.71 |
| `leptos` | 0.8.22; defaults off, `csr` only | Rust UI state/events and declarative DOM | MIT; 1.88 |
| `wasm-bindgen` / CLI | 0.2.129 / 0.2.129 | Generated Rust/WASM interop | MIT OR Apache-2.0 |
| `wasm-bindgen-futures`, `js-sys`, `web-sys` | 0.4.79, 0.3.106, 0.3.106; only needed DOM features | Native IPC promises and DOM/browser lifecycle access | MIT OR Apache-2.0 |
| `prost`, `prost-types` | 0.14.4 | Frozen generated Protobuf message/signature inventory | Apache-2.0; generator qualification owned by coordinator |
| `unicode-normalization`, `caseless` | 0.1.24 (`std`), 0.2.2 | NFC then Unicode default full case folding for literal search | MIT OR Apache-2.0; MIT |
| `serde`, `serde_json` | 1.0.229 (`derive`), 1.0.151 (`std`) | Strict typed backup JSON and private bounded diagnostics | MIT OR Apache-2.0; serde_json 1.71 |
| `chrono` | 0.4.45; defaults off, `std`, `clock` | Valid Gregorian dates, UTC instants and current local date | MIT OR Apache-2.0; 1.62 |
| `getrandom` | 0.4.3; `std`, native only | OS random 16-byte opaque IDs / tokens, rendered as lowercase hex | MIT OR Apache-2.0; 1.85 |
| `sha2` | 0.11.0; defaults off | SHA-256 candidate/artifact fingerprints | MIT OR Apache-2.0; 1.85 |
| `libc` | 0.2.190; `std`, native only | Narrow Darwin filesystem bindings | MIT OR Apache-2.0; 1.65 |

No UUID crate or tracing dependency is needed for the selected identity and diagnostics behavior. `turso_core =0.8.2` with `fs` is a **qualification / instrumented-test-only** direct dependency for the commit barrier; production still accesses the engine through `turso`. Turso's optional sync feature is disabled, but its published package still depends on sync-kit crates: absence of a feature is not a whole dependency-graph network audit. Local builder invocation and the production network-observation suite establish the relevant behavior. Transitive package versions, checksums and target-specific dependencies are in `Cargo.lock`; CLI acquisition locks are under `tool-locks/`. Retain appropriate third-party notices with delivered packages.

## Source provenance

| ID | Primary URL / version scope | Supported claim and limitation |
|---|---|---|
| D01 | https://doc.rust-lang.org/stable/releases.html — 1.99.0, released 2026-10-01 | Current stable release; installed `rustc` commit `b940084d7` matches. Does not establish application behavior. |
| D02 | https://docs.turso.tech/sdk/rust/quickstart and https://docs.turso.tech/sdk/rust/reference — current guide, checked against 0.8.2 source | `turso::Builder::new_local(...).build().await`, `connect`, parameterized `execute/query`, transactions; local mode needs no cloud credentials. Remote `turso_serverless` / legacy `libsql` are distinct integrations. |
| D03 | https://docs.turso.tech/sql-reference/multiprocess-access — current engine | Default single DB-owning process; experimental multiprocess is unnecessary here. Native instance arbitration is still an application obligation. |
| D04 | https://docs.rs/crate/turso/0.8.2/source/src/transaction.rs and https://docs.rs/crate/turso/0.8.2/source/src/lib.rs — published 0.8.2 package acquired by Cargo | `commit`, explicit `rollback`, drop records dangling rollback; next connection use resolves it. Public `with_io_impl(Arc<dyn turso_core::IO>)` supports instrumented test delegation. Detailed source pages were unavailable through the browser fetcher; the checksum-locked published Cargo source was inspected directly. |
| D05 | https://docs.rs/crate/turso_core/0.8.2/source/translate/pragma.rs and https://docs.rs/crate/turso_core/0.8.2/source/io/unix.rs — same locked source | FULL synchronous setting, fullfsync setting/readback, Darwin `F_FULLFSYNC`; `File::sync` receives completion and sync type. Readback and real-disk interruption probes supplement source evidence. No Turso Cloud durability claim is used. |
| D06 | https://docs.rs/crate/tauri/2.12.1 and https://docs.rs/crate/tauri/2.12.1/source/src/async_runtime.rs — 2.12.1 | Tauri 2 pin, MSRV/license; source owns one Tokio singleton runtime and accepts async commands. Do not create a runtime per command. |
| D07 | https://docs.rs/tokio/1.53.2/tokio/task/fn.spawn_blocking.html — 1.53.2 | Bounded blocking work can be offloaded; started blocking tasks cannot be aborted by dropping/aborting their handles. Mutation cancellation cannot imply rollback. |
| D08 | https://v2.tauri.app/start/frontend/leptos/ and https://docs.rs/crate/leptos/0.8.22 — Tauri 2 guide / Leptos 0.8.22 | Rust/WASM frontend integration; measured `csr` build. Documentation gives Trunk as a convenience, not a required runtime dependency. Framework selection does not prove VoiceOver semantics. |
| D09 | https://v2.tauri.app/security/capabilities/ and https://v2.tauri.app/security/csp/ — Tauri 2, validated with 2.12.1 | Explicit `AppManifest::commands` permits app ACLs; capabilities scope allowed commands to `main`. WASM needs `script-src 'wasm-unsafe-eval'`; generated bindgen loads bundled WASM with fetch, requiring `connect-src 'self'` alongside internal IPC sources. No remote capability is granted. |
| D10 | https://docs.rs/crate/tauri-plugin-dialog/2.8.1 and https://docs.rs/crate/tauri-plugin-single-instance/2.5.2/source/src/platform_impl/macos.rs — stable major 2 | Dialog native callbacks; current major 3 alphas excluded. Dialog depends transitively on fs plugin; no UI fs/dialog permission is granted merely by native usage. Single-instance source inspected from published checksum-locked package: socket under global `/tmp` uses bundle identifier, listener bind is asynchronously spawned, notification has no focus acknowledgment, and bind failure logs then continues. These facts reject that plugin for FR-024 / account-and-data-location arbitration. |
| D11 | https://docs.rs/crate/wasm-bindgen/0.2.129, https://docs.rs/crate/wasm-bindgen-futures/0.4.79, https://docs.rs/crate/js-sys/0.3.106, https://docs.rs/crate/web-sys/0.3.106 | Exact generated interop/promise/DOM family compiled and bundled. CLI/library versions must agree. |
| D12 | https://docs.rs/crate/unicode-normalization/0.1.24 and https://docs.rs/crate/caseless/0.2.2 — Unicode 16.0.0 constants measured from source | NFC iterator and full default fold. Newest normalization 0.1.25 uses Unicode 17 and was deliberately not selected, to avoid mixed search-data versions. |
| D13 | https://www.unicode.org/Public/16.0.0/ucd/CaseFolding.txt and https://www.unicode.org/reports/tr15/tr15-55.html — Unicode 16 | Default C/F case folding and NFC semantics. Search retains accents; storage text is not rewritten. No locale-specific/Turkic mode, SQL LIKE or SQLite NOCASE substitution. |
| D14 | https://doc.rust-lang.org/std/fs/fn.rename.html and https://doc.rust-lang.org/std/fs/struct.File.html — Rust 1.99.0 | Unix rename replacement is same-mount; `sync_all` reports I/O errors instead of relying on Drop. Local same-directory replacement/directory sync measured. Root's Darwin backup decision supplies final publication/alias/storage policy. |
| D15 | https://docs.rs/crate/chrono/0.4.45, https://docs.rs/crate/getrandom/0.4.3, https://docs.rs/crate/sha2/0.11.0, https://docs.rs/crate/libc/0.2.190 | Version/license/API scope; date constructors reject invalid Gregorian values, OS randomness, SHA-256 and Darwin bindings. Explicit product limits remain native domain rules. Time-zone refresh latency still needs acceptance testing. |
| D16 | https://docs.rs/crate/serde/1.0.229 and https://docs.rs/serde_json/1.0.151/serde_json/ — selected versions | Typed JSON serialization/deserialization; derive plus `deny_unknown_fields` rejects unknown/duplicate struct fields in probe. It does not replace complete backup/domain validation. |

Sources are evidence only. No external page is allowed to change requirements, permissions or controller commands. Registry HTTP metadata returned 403 even after an approved retry; exact versions were confirmed through current official docs and Cargo's published registry metadata/source instead.

## Evidence matrix

| Property | Evidence / decision | Remaining obligation |
|---|---|---|
| Native / WASM compatibility | Stable 1.99.0 compiled Turso0.8.2/Tokio1.53.2 on arm64; Leptos0.8.22 plus current generated messages compiled to wasm32. | Clean delivered package build and installed execution under NFR-PLAT / QUAL. |
| Local persistence and rollback | Persistent fixture commit/reopen, explicit rollback, dropped transaction rollback, constraint-error followed by explicit rollback passed. | All mutation / whole restore semantics, storage failure and corruption preservation. |
| Durable settings | Set `synchronous=FULL`, `fullfsync=ON`; queried values 2 and 1. Source maps fullfsync to Apple full flush. | Configure/read back on every relevant connection; no power-loss claim. |
| Meaningful process interruption | Five SIGKILL cases per before-commit, inside actual armed WAL sync during `commit`, and after emitted acknowledgment. Independent reopening saw 0, whole 1, and 1 respectively. | Requirements mandate 20 per cut point for every mutation class and restore; this spike is smaller qualification evidence. |
| Async lifecycle / concurrency | Tauri owns Tokio runtime; async command compiler accepted actual Turso awaits. Serialize admitted mutation, retain owner/task handles and reconcile uncertainty. | Duplicate activation, bounded admission, shutdown and delayed-UI checks. |
| Security and offline | Bundled WASM; CSP permits local WASM and internal IPC; app ACL scopes two experiment commands and rejects a registered forbidden command. Optional cloud sync absent. | Final packaged denied-operation / outbound-network / account-isolation suites; experiment command interfaces excluded from release. |
| Unicode / validation helpers | Unicode16 scalar fixtures, NFC equivalents, full fold (`Straße`, sigma, dotted I), accents and punctuation; pinned date/random/hash/typed-JSON APIs exercised. | Complete requirement fixtures, all field limits, capacity, query ordering and backup schema checks. |
| File lifecycle | New same-directory temp, flush, rename and directory sync worked on local SSD. Darwin rename binding available. | Root's specific destination policy, aliases, rejection of unsupported storage and interruption suite. |
| Licensing / dependency cost | Direct licenses listed; exact graph locked. No UI router/server, ORM, UUID abstraction or logging framework added. | Delivered graph/license inventory and notices; build-tool graph is distinct from runtime. |
| API stability / upgrades | Major2 Tauri plugins and stable frontend pinned; generator contracts used in native/WASM. Turso published MSRV unspecified but compiled. | Any toolchain/engine/frontend/plugin/Unicode update requalifies relevant native/WASM/package/failure probes and locks. |
| Performance / accessibility | No throughput or accessibility guarantee inferred from successful compilation. | P1–P3 with all raw samples, capacity tests, keyboard/VoiceOver/contrast/200% text checks on specified Mac. |

## Reproducible commands and experiment meaning

`Cargo.toml`, `Cargo.lock`, `rust-toolchain.toml`, `native/`, `ui/`, `desktop/`, `capture.py` and `recheck.py` contain the runnable probe. Only synthetic text/data is used. `native/src/commit_gate.rs` delegates unchanged PlatformIO/File operations; it arms after transaction statements and pauses only inside WAL `sync` called by `tx.commit()`. The parent kills the process at the emitted checkpoint and independently reopens using the normal engine. This is neither a sleep before commit nor an engine mock.

Acquire exact tools from crates.io with their published locks:

```sh
cargo install tauri-cli --version 2.12.1 --locked --root /private/tmp/rdd-spec-tools
cargo install wasm-bindgen-cli --version 0.2.129 --locked --root /private/tmp/rdd-spec-tools
```

The wasm-bindgen CLI's published lock contains a yanked `yoke-derive` version and two future-incompatibility warnings in build-tool transitive dependencies. The locked installation succeeded on the recorded stable toolchain; these are tool-acquisition limitations to revisit on upgrade, not silently updated dependencies.

Initial qualification stages are `python3 capture.py native`, `ui`, `package`, `sign`, `launch`; each stores the full stage output, exact command, exit and duration in `logs/`. The package is a local ad-hoc-signed `.app`, no service/account/notarization required by this Mac-only scope. It is instrumented qualification software, not a delivered Todo package. The Leptos caller encodes the current generated QueryRequest; the actual bundled WebView invokes Tauri; the native adapter calls a generated `ApplicationService` provider; that provider commits/reads embedded Turso and returns QueryResponse for WASM decoding. Other generated methods return explicit out-of-scope errors. A registered but unpermitted probe command must be denied before the successful call. Native `WebviewWindow::show()` and `set_focus()` must both return successfully before the PASS report; this qualifies those Tauri activation APIs without claiming the complete two-process protocol.

Read-only requalification from any working directory:

```sh
RDD_QUAL_TOOL_BIN=/private/tmp/rdd-spec-tools/bin \
RDD_QUAL_TARGET_DIR=/private/tmp/rdd-spec-qualification-target \
python3 experiments/spec-dependencies/recheck.py
```

`recheck.py` hashes immutable inputs, copies them to private temporary scratch, rebases the generated path dependency only in that copy, uses the unchanged source crate, builds with `--locked`, packages/signs/launches the same native/WASM specimen, verifies input hashes afterward, and prints scratch log paths and packaged binary hash. A shared target is a build cache, not frozen source/evidence; scratch output remains outside source. Exact tool-version parsing rejects near matches. GUI qualification needs the host's approved native execution permission. The current root can reuse `/private/tmp/rdd-spec-dependencies/tools/bin` and `/private/tmp/rdd-spec-dependencies/target` to avoid duplicating several GiB of cached builds.

Initial evidence includes a retained missing-icon build failure and the sandbox cache denial, corrected through a deterministic icon fixture and approved cache access. Root's first actual WebView observation showed only the document description and no body/PASS; this is a failed initial launch, consistent with omitted local fetch CSP allowance. The final CSP includes `connect-src 'self'`; final package runtime is recorded separately, and the initial observation is not counted as green.

**Historical measured result:** the prior `.app` launch exited **0** in **30.823 seconds**, including a deliberate 30-second observation hold. The independent root coordinator's actual CUA accessibility tree and screenshot showed the heading `Dependency qualification` and body `PASS packaged Rust WASM invoke + generated QueryRequest/QueryResponse + Turso commit`. The native report file contained the same body. The screenshot remains in the tool trace; no screenshot-file artifact is claimed. This result is preserved under `logs/historical-with-single-instance/` because independent review subsequently rejected that plugin. Current sources remove it. This historical result measures a local packaged call, not application latency or release acceptance.

**Current measured result:** the final package excludes the rejected single-instance plugin and requires `show()` and `set_focus()` success before reporting. It exited **0** in **30.369 seconds**, including the 30-second observation hold, with a newly created synthetic database and report. Both process stdout and that fresh report contained the exact PASS body above. `logs/qualified-source-hashes.json` binds the current native/WASM inputs and generated crate to the signed binary; `package-runtime-fixture.json` identifies the fresh fixture. The latest independent CUA selection displayed `pending`; it is **not** counted as a current visual PASS. The coordinator identified and terminated a separately launched unconfigured probe process. Current package qualification rests on the actual fresh subprocess/report and returned activation APIs, with the earlier visual result retained only as historical evidence. Read-only requalification reruns the actual current package before freeze.

## Alternatives, assumptions and release limits

The requirements mandate local `turso`: remote drivers, `libsql`, cloud replicas and a different engine would require an amendment. Raw `web-sys` could reduce dependency count, but would require hand-maintained event/state/DOM lifecycle machinery; Leptos CSR is the supported Tauri Rust integration with one Rust state owner and no routing/server surface. No requirement justifies a second persistence wrapper or ORM. Unicode16 is deliberately selected consistently; moving to Unicode17 requires a jointly updated normalization/folding provider and fixtures.

Reject `tauri-plugin-single-instance` 2.5.2 after source review (D10): its macOS global bundle socket does not implement the required account/data-location lease or acknowledged activation. The coordinator selects and independently qualifies a native account/data-directory `flock` descriptor held before database open, plus a private request/acknowledgment activation mailbox whose acknowledgment follows focus activation; see the coordinator's instance specification and `experiments/spec-instance/`. The dependency spike has one synthetic window and does not claim to verify that separate lifecycle protocol. No replacement third-party dependency is added beyond the already selected Darwin bindings and standard library.

Assumptions: functioning local OS/filesystem/SSD during abrupt process termination; single account/data location owner; no unsupported network filesystem. Narrow probes do not establish power-loss recovery, every storage failure, migration, full product performance, privacy, or accessibility. The reference-host and backup-filesystem evidence are owned by the coordinator. Specification freeze requires the final real package call and independent review; successful harness selftests alone are insufficient.
