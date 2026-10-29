# Solution and interface specification

Requirements revision 5, [S1 ownership and behavior](domain-model.md), [inventory](domain-inventory.json), [S2 constraints](constraints.md), [S3 oracles](scenarios.json), [S4 protocols](benchmarks.md) and [S5 qualification](dependencies.md) govern. The manifest binds their exact interfaces, targets and executable inputs. This amendment corrects preparation routing without changing product semantics.

## Ownership and layout

One native Cargo package contains four distinct functional modules, native support and composition; a separate Leptos CSR package owns Rust/WASM presentation. Both consume the standalone generated crate, excluded from the outer workspace. Private implementations and executable import/call allowlists enforce boundaries; `pub(crate)` alone cannot. Checks reject unauthorized methods, sibling internals, UI storage access and business calls disguised as construction.

Functional packages are `todo.<owner>.v1`; native_api, storage, selected_files, desktop and diagnostics also provide generated services. UI, composition and build_support have no RPCs. `service` exports expose generated traits; `construct` takes application identity as `&'static str`, then cloneable generated dependencies in lexical owner order, returning `Result<impl GeneratedService + Clone, OwnerFailure>`. Invalid identity/setup fails without partial registration. Clones share ownership; final drop releases resources. Concrete structs, connections, descriptors and private domain types remain private.

Composition invokes only its nine approved exports. Platform wiring is exactly `native_api::wire<D, W>(identity: &'static str, builder: tauri::Builder<tauri::Wry>, diagnostics: D, workspace: W) -> Result<tauri::Builder<tauri::Wry>, native_api::Failure>` with cloneable, static DiagnosticsService/WorkspaceService bounds. It privately constructs Invoke, registers `todo_invoke` and returns the builder. Identity-derived configuration performs no data access or business operation. Workspace owns startup/admission.

Native providers accept owned requests and return `Send` futures with `Send + Sync` providers; consumers are concrete/generic. Native_api may privately erase an owned async dispatch closure for Tauri's non-generic managed command. Its callback maps all nine InvokeRequest action variants to matching workspace RPCs and Reply variants. Boundary serialization occurs at this UI/native crossing; local business calls use generated values directly. Operation permission includes its descriptor-reachable request/response members, not calls to services owning nested messages. Other semantic imports require explicit type-only bindings. Consumer qualification constructs all nine actions.

## Data and validation

[S1's accepted core](domain-model.md#accepted-core) defines normalization, identities, dates, timestamps and backup syntax. Collection converts admitted or untrusted persisted values into private validated types; storage owns raw row shapes without reverse imports. Complete drafts replace all three editable fields: absent due date clears it, but absent draft rejects. Raw editor input remains exact.

Required messages, timestamps and action/outcome unions must be present; unknown/zero selectors, invalid nanos and malformed UUIDs reject. Unknown protobuf fields grant no permission. Backup parsing streams UTF-8/JSON, rejects malformed surrogate escapes and enforces S1's document rules; collection validates task values and capacity. Selected-file reads use bounded chunks. No transport/document cap excludes valid maximum-content collections or equivalent JSON whitespace/escaping. Allocation/IO exhaustion fails actionably before mutation, never truncates.

## Collection and storage operations

S1's behavior table and directed interactions specify operation rights and transitions. ReadSnapshot exposes an immutable committed revision even during writes; ValidateImport normalizes without persistence; Replace revalidates under its atomic revision check. No-op edits/status preserve timestamps and revision.

Create allocates UUID only for the admitted operation. Sample UTC at successful transaction final-write preparation; failed attempts establish no history. Workspace supplies unique operation IDs. Storage atomically records effect, revision and durable receipt/fingerprint. Reused IDs with different content reject; matching retries resolve receipts without reexecution. No-op acknowledgments record outcomes without changing task fields/revision. Reconciliation may omit superseded content; workspace re-queries current state.

Storage Open/Read/Commit/Outcome use parameterized raw operations. Commit serializes typed put/remove/replace with expected revision and acknowledges only durable completion. Use qualified WAL/synchronous FULL, account-private local files and one owning process. Dropped/canceled transactions must finish rollback before subsequent access. Definite precommit failures reject; dispatch uncertainty persists until receipt/state reconciliation. Revision exhaustion fails before mutation without wrapping. Inaccessible/corrupt/future-format preservation and release-one format policy follow S1 and S2.

## Workspace and query

Workspace obtains desktop instance admission before collection Open. Secondary launch activates the existing window and exits without database access. UpdateDraft retains raw input; Navigate records select/new/cancel/restore/close/delete/clear/activate intent. Dirty navigation produces an unpredictable 128-bit, one-use handle scoped to native session, intent and candidate. Retain/discard/cancel follow S1; unknown, consumed, canceled or foreign handles reject.

Submit validates session, activation and action, reserving the shared mutation/restore slot before dispatch and returning pending state. A deliberate later Create gets a fresh activation. ReadState polls and reconciles; admitted work runs off the UI event loop. IPC waiter cancellation neither cancels it nor releases the slot. Pending feedback, rejection/input retention, uncertain retry, close waiting and post-restore defaults follow S1/S2.

EvaluateView validates selectors, samples authoritative Today through query's private native date reader, and returns ordered rows plus both counts from one committed revision. Correctness builds may inject private readers; delivered builds expose no clock command. Desktop events route entry callbacks through native_api to workspace, with no reverse desktop business dependency. Bundled help/version and presentation accessibility remain their S1 owners' responsibilities.

## Backup and selected files

S1 defines complete export snapshots, destination consent, immutable restore candidates, revision-bound renewed consent and atomic replacement. BeginExport selects a file and snapshot; its offer identifies unencrypted content and overwrite need. FinishExport cancel preserves destination; confirm binds selected identity and starts publication. BeginRestore follows draft protection. FinishRestore cancellation disposes its handle; confirmation consumes it only after a definite outcome, retaining uncertain correlation until reconciliation. Export uncertainty resolves before another publication attempt. File labels may reach UI, never diagnostics.

Select grants a scoped opaque file capability. Probe compares resolved paths and identities against all managed database/recovery/migration/diagnostic files, rejecting symlink/hardlink aliases. Publish begin creates a unique private adjacent temporary; append writes bounded chunks; finish verifies length/digest, flushes/synchronizes, rechecks destination identity/consent and atomically renames on qualified local same-filesystem storage. Prepublication failure preserves the old file. Interruption reconciliation accepts only complete old/new hashes. Cleanup removes owned temporaries/consumed grants, never the destination; unsupported guarantees reject before overwrite.

## Errors, diagnostics and verification

Generated responses carry schema-owned success/failure; empty outcomes never mean success. Native adapter failures separately cover decoding, denied invocation, canceled waiter, unavailable lifecycle and absent/mismatched response. Capabilities precede dispatch. Native/WASM tests cover missing nested values/outcomes, defaults and unknown enums. Collection field/record errors propagate without SQL, traces or payload echoes. Diagnostic Emit accepts severity/category/correlation/numeric outcome; diagnostics validates codes, adds timestamp/version and applies S1's privacy, retention and nonblocking rules.

All 24 product checks retain exact S3 backlinks/results paths. Real runners, providers/consumers, composition/type-import/bypass proofs, packages and independent rendered/input-ready oracles are implementation-produced. Preparation schedules actual-source proofs at first delivery and cumulatively. Disposable qualification executes no product scenarios. Every product check reports all assigned S3 outcomes; omitted/filtered scenarios fail despite process success.

## Qualification order and reproduction

The [S5 portable route](dependencies.md#portable-preparation-route-d-prep-route-revision-1) governs both fixture checks and their exact 17 resources. Hosted preparation additionally provisions Rust/components/WASM and Buf through the fixed trusted workflow; local Python reproduction is not hosted acquisition evidence. All other checks retain macos-reference obligations.

Run native checks from the committed candidate. `C-READY-TOOLS` verifies official tool identities and native/WASM smoke. Retained installations/caches retain historical provisioning scope; missing installations require actual empty-home provisioning. SDK/OS are measured supplied inputs. `tools.json` pins the resolved runtime WebKit plist/build for fresh host measurement. Launch checks through outer `provision.py --exec ./rdd ...`; frozen argv never nests a mutating controller. Builds use separate Cargo homes, pinned CLIs and compiler-library lookup without modifying the qualified installation.

| Check | Proof and order |
|---|---|
| C-QUAL-CONTRACTS | Protected comparison of nine schemas, generator/locks and exact generated bytes; native/WASM providers/consumers and intended request/response/signature/error rejection. |
| C-QUAL-BOUNDARIES | Disposable typed construction, registration/invocation, final resource release, forbidden calls/private exports/wrong-provider rejection; no claim of real adoption or comprehensive indirect bypass proof. |
| C-QUAL-FIXTURES; C-READY-FIXTURE-TOOLS | Frozen D1 byte/oracle reproduction and complete Unicode inputs; readiness also observes dedicated Python. |
| C-QUAL-NATIVE | Retained native-v3 source/lock and 29 archive identities rebuilt; CLI publication/alias/interruption/instance probes run. Historical GUI observations remain separate. |
| C-QUAL-JOINT | After tools, copy carrier/current generated crate to owned scratch; record warmed-cache scope, compile native/WASM, store/reopen, produce app/DMG and preserve artifacts. Host check observes canonical ReadHelp IPC and synthetic marker. |
| C-READY-HOST | Fresh host/account-denial/network-sensitivity controls and exact-package observer trust/actions; no benchmark readiness claim. |
| C-READY-TRANSFER | After clean commit/host checks, export checkpoint outside the running controller; two clean same-host clones resume, execute fixture proof and import its genuine receipt/hashed log using `--local-host`. |

The host prelude writes actual `.rdd/runtime/host.json`. `observer/fresh_identity.py` prepares a separate helper with explicit target path/hash/bundle substitutions, never trust or actions. Preserve the historical helper. Only an identical rebuilt target permits reuse of its existing binding; otherwise require new identity review and actual trust. Parent-authorized GUI observations must be fresh. `.rdd/runtime/s6/observer-authorized.json` binds observer, target, binding and action paths/hashes; host.py rehashes them and verifies current trust and joint-package membership.

Launch one watched installed process with `RDD_QUALIFICATION_DATA` pointing to a new owned database. Establish persisted READY through Persist, normal Quit and reopen; observe canonical Invoke with no COMMITTED marker before timed action. Bind observations to that PID; preserve wrong-process/data observations separately. After Quit verify exit without relaunching. The frozen observer/host scripts define geometry, marker and timing assertions; synthetic markers do not replace product rendering/input-ready oracles.

Before transfer run `./rdd export-run .rdd/runtime/s6/transfer/checkpoint.json`. S7 obtains current registered receipts. Preserve old evidence and bytes; clone-cache experiments stay in this rehearsal's ignored evidence and are labeled warmed-cache feasibility. Bound writers by actual leases/disk predictions and retain the 2-GiB reserve. Product benchmarks separately require all S4 conditions, including 15 GiB free and no concurrent builds.
