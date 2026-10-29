---
document_id: TODO-REQ
title: Todo Application Requirements
version: 0.5.0
status: draft
date: 2026-10-27
canonical_path: requirements/requirements.md
requirement_revision: 5
requirement_priority: must
---

# Todo Application Requirements

## 1 Purpose and authority

This document defines release one of a personal desktop Todo application built with Rust, Tauri 2, and an embedded Turso database. The application helps one person capture work, identify outstanding tasks, record completion, and retain control of their data while working offline.

**Status:** Draft 0.5.0, developer-amended revision 5 baseline. The 51 active requirements have revision 5 and priority Must under the macOS scope in Section 6. Acceptance criteria are normative parts of their parent requirement. Numerical limits are proposed product targets, not measured claims about Rust, Tauri, or Turso.

Rust, Tauri 2, and embedded Turso are the requested technology constraints. The desktop platform matrix, Rust UI scope, feature boundaries, field limits, and performance budgets are explicit choices for this example. They can be amended before the requirements baseline is accepted.

The canonical repository document is `requirements/requirements.md`. A Word copy is a review rendering of the same content. Stable requirement IDs survive amendments; changed statements receive a new revision, and removed IDs are retired rather than reused. The requirements commit identifies the baseline consumed by specification.

Requirements describe required behavior, quality, and constraints. The specification workflow selects domain modules, interface operations, protobuf schemas, database structure, UI framework, and technical test designs. Preparation determines folders, tasks, verticals, and phases. Those downstream choices cannot change these requirements implicitly.

## 2 Product boundary

### Intended user and operating context

The user is one person operating the application under their own desktop operating-system account. Each operating-system account has one independent local task collection. The application is installed on a local disk and does not depend on a server or another running application.

### Included capabilities

- Create and edit tasks with a title, notes, and an optional due date.
- Mark tasks complete and reopen them.
- Permanently delete individual tasks after confirmation.
- Find tasks using status and due-date filters, literal text search, and deterministic ordering.
- Persist accepted changes across application restarts.
- Export and restore a complete local backup.
- Operate using a keyboard.
- Display actionable failures without silently replacing or discarding stored data.

### Excluded capabilities

Release one has no accounts or login, cloud synchronization, collaboration, multiple lists, tags, priorities, subtasks, recurring tasks, reminders, attachments, bulk editing, rich-text editing, or external integrations. Mobile applications, a browser-hosted edition, a network API, automatic updates, application-level encryption, and an application password are outside this baseline. The operating system provides account access control; a user-selected backup is unencrypted.

The application-facing API in the architectural constraints means the local boundary between the UI and native application operations. It does not imply a public HTTP or gRPC server.

## 3 Domain vocabulary and data rules

These rules define observable task semantics and are enforced by FR-004. They do not prescribe database columns or protobuf field names.

| Concept | Required meaning |
|---|---|
| Task identity | A stable, opaque identity unique within the collection. Editing or changing status preserves it. Identical titles and content are allowed on different tasks. |
| Title | Required plain text. Remove leading and trailing Unicode whitespace. The remaining value contains 1 to 200 Unicode scalar values and contains no line break or U+0000. Internal whitespace is preserved. |
| Notes | Optional plain text represented as an empty value when absent. Maximum 10,000 Unicode scalar values after converting CRLF and CR line endings to LF. Other whitespace is preserved. U+0000 is invalid. |
| Due date | Optional valid Gregorian calendar date, with a year from 0001 through 9999. It has no time of day or associated time-zone instant. Display and interchange use YYYY-MM-DD. |
| Status | Exactly one of Open or Completed. A newly created task is Open. |
| Created time | The UTC instant at which the task was first successfully stored; immutable for that task. |
| Updated time | Initially equal to created time; subsequently the UTC instant of the latest successful change to task content or status. Saving identical normalized values does not change this value. |
| Completed time | Absent for an Open task. Set to the completion instant when a task becomes Completed; cleared when reopened. |
| Today | The device's current local calendar date. Changing time zone can change Today but cannot change any stored due date. |
| Overdue | A task is Overdue exactly when it is Open, has a due date, and that date precedes Today. A Completed task is never Overdue. |
| Committed state | Task data successfully committed to the embedded database. Unsubmitted editor contents are a draft and are not committed state. |
| Supported capacity | At most 10,000 tasks, including both Open and Completed tasks. All field limits remain valid at this capacity. |

A Unicode scalar value is the counting unit, not a byte or a user-perceived character. For example, an emoji sequence can consume several scalar values. Storage preserves valid text other than the explicit title trimming and line-ending normalization above. Clock changes do not change task identity, and no requirement assumes that wall-clock timestamps always increase.

For search comparison only, normalize query and candidate text to Unicode NFC and apply Unicode default case folding. Retain diacritics. Treat the query as one literal substring, without tokenization, regular expressions, fuzzy matching, or wildcards. The specification pins the Unicode data version and supplies fixtures; stored text is not rewritten by search.

## 4 Functional requirements

### Starting the application

**FR-001 Initialize a new collection**

On the first successful launch for an operating-system account without application data, the application shall initialize an empty collection and present a usable task view without requesting service credentials.

Acceptance: First launch with networking disabled reaches an empty view containing an available create action. A second launch loads the same collection.

**FR-002 Load the existing collection**

On subsequent launches, the application shall load the existing committed tasks with their identities and required fields intact.

Acceptance: Restart after creating Open and Completed tasks; compare all fields with the last acknowledged state when no operation was pending at exit. An interrupted or uncertain operation follows NFR-DATA-001. An unreadable existing database is handled under NFR-DATA-003 rather than treated as a first launch.

### Creating and editing tasks

**FR-003 Create a task**

The application shall allow the user to create one Open task from a valid title and optional notes and due date.

Acceptance: One successful submission creates exactly one new identity with the submitted normalized values and initial timestamps. Creating a second task with identical content produces a different identity.

**FR-004 Validate task data**

The application shall enforce every data rule in Section 3 for task creation, editing, and restoration without silently truncating input.

Acceptance: Values at the stated limits succeed; empty normalized titles, over-limit values, invalid dates, invalid status combinations, and a collection exceeding capacity are rejected. The error identifies the invalid field or capacity limit. Creation and editing retain entered values for correction; restoration leaves the selected file and collection unchanged and identifies the invalid record or document condition without requiring a backup editor.

**FR-005 Edit task content**

The application shall allow the user to change a selected task's title, notes, and due date while preserving its identity, created time, and completion status.

Acceptance: Change each field, clear both optional fields, save, and restart. Only the selected task changes. Editing a Completed task leaves it Completed and retains its completed time.

**FR-006 Protect unsaved input**

Before a user action would discard changed editor input, the application shall let the user retain the draft or explicitly discard it.

Acceptance: Switching tasks, starting another create action, cancelling an edited form, initiating restore, and normal window close all protect a changed draft. Retaining it cancels the attempted navigation. Explicit discard leaves committed data unchanged. Recovery of an unsubmitted draft after a crash is outside scope.

### Completing and deleting tasks

**FR-007 Complete a task**

The application shall allow the user to change an Open task to Completed while preserving its content, identity, and created time.

Acceptance: Completion sets its completed and updated times. The task leaves an Open-only view and appears in a Completed view. A repeated request to set an already Completed task to Completed has no additional effect.

**FR-008 Reopen a task**

The application shall allow the user to change a Completed task to Open while preserving its content, identity, and created time.

Acceptance: Reopening clears completed time and updates updated time. The task returns to an Open view and its Overdue state is recalculated. Reopening an already Open task has no additional effect.

**FR-009 Confirm permanent deletion**

The application shall permanently remove only the selected task after the user confirms a deletion prompt that identifies that task and states that deletion is permanent.

Acceptance: Cancelling changes nothing. Confirming removes the selected identity from every view and from a subsequently exported backup, including after restart. No other task with identical content is removed. A backup created before deletion can still contain the deleted task; secure erasure of storage media is not required.

### Finding and viewing tasks

**FR-010 Provide task views**

The application shall provide Open, Completed, and All status views in which each displayed task exposes its title, status, and due date when present, with an action to inspect and edit its notes.

Acceptance: The displayed identity set exactly matches the selected status view combined with the active query constraints. Every launch starts with Open, no search query, the Any date filter, and newest-created ordering; view preferences do not persist in release one.

**FR-011 Filter by due date**

The application shall provide Any, Today, Overdue, and No due date filters that combine with the status view and search query using logical AND.

Acceptance: Today matches tasks dated Today regardless of status; Overdue uses Section 3 and therefore returns no Completed tasks. No due date matches only absent dates. Any imposes no date restriction.

**FR-012 Search task text**

The application shall return tasks whose title or notes contain the search query under the comparison rules in Section 3 after trimming outer Unicode whitespace from the query.

Acceptance: Empty or whitespace-only queries impose no text restriction. Case-equivalent and canonically equivalent Unicode text matches, diacritics remain significant, notes-only matches are included, and literal punctuation has no special meaning. Searching never changes task data.

**FR-013 Order task results**

The application shall provide the following deterministic ordering choices for the current result set: newest created, oldest created, and earliest due date.

Acceptance: Newest and oldest sort by created time in the named direction, then by the immutable identity in ascending canonical order. Earliest due date sorts dated tasks ascending, places undated tasks last, then uses created time descending and identity ascending. The specification defines the identity's canonical ordering once; all views use it consistently.

**FR-014 Show result and empty states**

The application shall display the number of matching tasks and distinguish an empty collection from a nonempty collection with no results under the current filters.

Acceptance: The displayed result count matches the filtered identity set after every successful change. The empty-collection state exposes task creation; the no-results state exposes a way to clear search and filters.

### Mutation feedback and coordination

**FR-016 Report persistence outcomes**

The application shall acknowledge a task mutation or restore as successfully saved only after that operation has successfully committed to persistent storage.

Acceptance: With commit deliberately paused, the UI shows a pending state rather than a success claim. After commit, the visible results reflect the committed change. Any optimistic display is visibly pending until acknowledgment.

**FR-017 Handle rejected and uncertain operations**

The application shall distinguish a confirmed rejected operation from an operation whose commit outcome is temporarily unknown, preserve available editor input, and give an actionable recovery message.

Acceptance: A rejected operation leaves the prior committed state unchanged and permits retry after correction. An uncertain outcome is not presented as success or as confirmed failure; the application reconciles it with stored state before permitting a retry that could duplicate or overwrite data. User messages do not expose a stack trace or raw SQL.

**FR-018 Prevent overlapping user mutations**

For one collection, the application shall permit at most one pending user mutation at a time and shall prevent repeated activation of that pending submission from producing additional mutations.

Acceptance: Repeated Save or completion activation during a delayed operation creates one effect. Conflicting mutation controls remain unavailable until the outcome is resolved. Once completed, a deliberate new create submission can create another task with identical content. Search and viewing remain available while a mutation is pending. Normal window close waits for the pending outcome to resolve and shows a waiting state; submitted input is not discarded as an unsubmitted draft. Forced termination remains covered by the failure model.

### Backup and restore

**FR-019 Export a complete backup**

The application shall allow the user to export a versioned UTF-8 JSON backup of one consistent committed collection state, including every task's identity, title, notes, due date, status, created time, updated time, and completed time, to a user-selected file.

Acceptance: Active filters do not limit the export. Unsubmitted drafts are excluded. The backup can be restored into a fresh application-data profile on the supported Mac after the source application exits, preserving task identity and field meaning independently of the source database. Today and Overdue are recalculated rather than stored as authoritative backup fields. The export UI identifies the file as containing unencrypted task data. The file format is finalized in specification.

**FR-020 Protect backup destinations**

The application shall preserve an existing destination file unless the user explicitly confirms replacement, and shall replace a confirmed destination only with a complete valid backup.

Acceptance: Cancellation and a confirmed failure before publication preserve the previous destination. An interruption or uncertain publication outcome leaves either the complete previous file or the complete new backup, never a partial replacement; the outcome is reconciled before retrying. A new incomplete file is not presented as a completed backup. Completion identifies the saved location. Destinations aliasing the application's database, recovery, migration, or diagnostic files are rejected. Unsupported destination storage that cannot meet the replacement guarantee is rejected before modifying an existing file.

**FR-021 Validate a restore candidate**

The application shall validate the entire selected backup before offering to replace the current collection.

Acceptance: Malformed JSON, unsupported format versions, missing required data, duplicate identities, invalid field values, inconsistent status timestamps, and capacity violations are rejected without changing the collection. A valid empty backup is supported.

**FR-022 Obtain restore confirmation**

The application shall require explicit confirmation that restoration will replace the entire current collection before applying a valid backup.

Acceptance: The confirmation identifies the selected file and states the existing and replacement task counts. It also states that restoration replaces rather than merges data. Cancelling preserves the current collection; a pending editor draft is protected by FR-006.

**FR-023 Restore the complete collection**

After confirmation, the application shall replace the collection with the validated backup as one atomic operation that preserves the backup's task identities and required field values.

Acceptance: A successful restore presents the restored collection using the default view. An interrupted restore leaves either the complete old collection or the complete restored collection, never a mixture. A Completed task keeps its original completed time; restoration does not restamp task history. Restoration applies exactly the validated candidate described in the confirmation; changed file contents require renewed validation and confirmation unless the retained, previously validated candidate is used.

### Application lifecycle and help

**FR-024 Limit the application to one instance**

Launching another instance for the same operating-system account and data location shall activate the existing application window and exit the new instance without opening a second independent database writer.

Acceptance: Sequential and simultaneous double launches produce one usable collection window and at most one database-owning application process. Unsaved input in the existing window is preserved.

**FR-025 Provide local help and application identity**

The application shall provide offline-accessible help describing task operations, date semantics, data and backup locations, restore replacement behavior, and its application version.

Acceptance: All help is available without network access. The displayed version identifies the installed release and matches the release evidence. Help states that permanent deletion has no built-in undo and that backups may contain previously deleted tasks.

## 5 Nonfunctional requirements

### Technology and architectural constraints

**NFR-TECH-001 Rust implementation scope**

All first-party business logic, application operations, persistence behavior, and UI state and event behavior shall be implemented in Rust using a stable Rust toolchain.

Acceptance: Source and build inspection confirms this scope. Declarative HTML and CSS, static assets, generated JavaScript or WebAssembly interop, and build or test tooling may use other formats or languages. The Rust frontend framework remains a specification decision.

**NFR-TECH-002 Tauri runtime**

The desktop application shall use the Tauri 2 major series as its native application runtime.

Acceptance: Dependency inspection and packaged execution verify Tauri 2. Running the UI in a standalone browser is insufficient evidence for the desktop application.

**NFR-TECH-003 Embedded Turso persistence**

The authoritative task store shall be a persistent local embedded Turso database accessed through the `turso` Rust crate described in the current official Rust quickstart.

Acceptance: Packaged operations use the actual embedded engine and survive restart from disk. No Turso Cloud account, authentication token, remote primary, database server, or in-memory-only store is required. Substitution with `libsql`, another SQL driver, or browser storage requires an explicit requirements amendment. [S1]

**NFR-TECH-004 Reproducible dependency selection**

The build shall pin the Rust toolchain, application dependencies, code generators, and required build tools to recorded compatible versions.

Acceptance: A clean checkout builds using the recorded versions and committed dependency locks. Before freezing contracts, specification qualifies the native runtime, embedded database, Rust frontend, and generated contracts together through native and UI builds, local API calls, and packaging on every supported platform. A dependency update reruns the relevant qualification and acceptance checks.

**NFR-ARCH-001 Contract enforced boundaries**

The module interfaces and local UI-facing application API identified by the specification shall have versioned Protobuf contracts with generated Rust bindings used to enforce their declared data shapes and operation signatures.

Acceptance: Contracts compile, generated bindings match their sources, and architecture checks reject bypasses of the approved boundaries. Behavioral acceptance still verifies validation, errors, and persistence semantics. Protobuf does not require network transport, and private functions do not each require a contract.

**NFR-ARCH-002 Controlled application access**

The UI shall perform task reads and mutations only through the approved application API, without direct database or arbitrary filesystem access.

Acceptance: Source and boundary checks establish the permitted call paths; direct attempts from the UI to read a database file or execute arbitrary SQL are denied. User-selected import and export operations remain available through approved native operations.

**NFR-MAINT-001 Justified production scope**

Every first-party production module and direct production dependency shall have a documented purpose traceable to an accepted requirement, and each business rule shall have one authoritative implementation.

Acceptance: The architecture inventory and review find no unreferenced speculative feature, duplicate authoritative rule, or unused production dependency. UI validation may repeat a rule for feedback only when the native implementation remains authoritative and consistency is verified. Generated bindings and necessary boundary mappings are not treated as accidental duplication.

### Platform support and offline behavior

**NFR-PLAT-001 Supported desktop packages**

The application shall install and execute on the supported macOS environments in Section 6 without requiring a Rust compiler, development server, Turso CLI, or standalone database service at runtime.

Acceptance: Installation into a clean local account or application-data profile and the packaged functional suite pass on the selected acceptance environment with development tools unavailable to the application process. Normal application use requires no administrator privileges. Documented operating-system WebView prerequisites may be installed as part of setup.

**NFR-OFF-001 Offline operation**

Every in-scope user operation shall remain available after installation when network access is unavailable.

Acceptance: Run create, edit, complete, reopen, delete, search, backup, restore, and help scenarios with runtime network access blocked. Installation prerequisites and operating-system-managed updates are outside this runtime test.

**NFR-PRIV-001 Local data and no outbound traffic**

The production application shall initiate no outbound network connections, including telemetry, crash uploads, remote fonts, update checks, or transmission of task data.

Acceptance: Process-attributed network observation during the complete acceptance workload records no application-initiated outbound connection. Tauri internal IPC and bundled-resource URLs that produce no network connection are permitted; this exception does not permit a local HTTP server or remote resources. Operating-system traffic is reported separately. Application resources needed for normal operation are bundled locally.

**NFR-PRIV-002 Data access scope**

The application shall keep its database and local diagnostics in the current account's application-data locations with permissions limited to that account and operating-system administrators, except for a user-selected backup destination.

Acceptance: A different unprivileged operating-system account cannot read those application-managed files. Application-exposed data operations accept only application-managed paths, specifically selected import or export files, and narrowly scoped temporary files required to complete those operations safely. Selection does not grant unrestricted access to the containing directory. Runtime reads of installed resources and operating-system libraries are permitted. This requirement does not claim protection against another process already running with the same user's privileges.

### Data integrity and recovery

**NFR-DATA-001 Durable acknowledged state**

After normal shutdown or abrupt termination under the process-failure model in Section 7, the collection shall reflect a valid sequential history containing every acknowledged mutation and restore in application order, subject to the superseding effects of later operations.

Acceptance: Compare reopened state with an independent ledger for create, edit, complete, reopen, delete, and restore. No acknowledged operation is omitted from the reconstructed history. A later edit, deletion, or restore may supersede earlier data; the one terminal unacknowledged operation may be wholly present or wholly absent. No partial operation is valid.

**NFR-DATA-002 Atomic state changes**

Every individual task mutation and whole-collection restore shall apply completely or leave the previous committed state intact.

Acceptance: Inject validation, storage, and process failures at the defined operation boundaries. No task has a mixture of old and new fields, and no restore exposes a mixture of the old and new collections. Rejected operations do not roll back unrelated earlier commits.

**NFR-DATA-003 Preserve inaccessible or incompatible storage**

When existing storage is inaccessible, corrupt, or has an unsupported format, the application shall stop normal task modification, preserve the original data files, and offer an actionable error with retry or exit.

Acceptance: Read-only, missing-permission, invalid-file, and newer-format fixtures cannot trigger automatic empty-database replacement, file deletion, or an unapproved schema downgrade. The requirement is to preserve available evidence and data, not to repair arbitrary corruption automatically.

**NFR-DATA-004 Safe data evolution**

From the second released data format onward, an upgrade shall preserve task identities and field meaning from the immediately previous released format and retain a recoverable prior dataset until migration succeeds.

Acceptance: Release one establishes versioned storage and backup fixtures and rejects unknown future versions. Each later applicable release tests upgrade, interrupted upgrade, and migration failure from its prior-format fixture. A failed migration leaves the prior dataset available for recovery without overwriting it with an empty collection.

### Responsiveness and supported capacity

**NFR-PERF-001 Task capacity**

The application shall correctly support 10,000 tasks, including valid maximum-length fields, and reject a create or restore that would exceed that count without losing existing data.

Acceptance: Boundary fixtures cover 9,999, 10,000, and 10,001 tasks and maximum field lengths. Removing a task at capacity permits creation again. Performance thresholds use the separate representative dataset in Section 6.

**NFR-PERF-002 Launch budget**

On each reference configuration, warm-cache launch shall reach a usable default task view at the 95th percentile within 2,000 milliseconds under protocol P1.

Acceptance: Every recorded launch is correct; the nearest-rank p95 for each platform meets the threshold. This is not a cold-boot or first-install launch guarantee.

**NFR-PERF-003 Interaction budgets**

Under protocol P2, create, edit, complete, reopen, and delete shall each complete at p95 within 200 milliseconds, and search, filter, and ordering changes shall each settle at p95 within 250 milliseconds.

Acceptance: Measure each operation class separately from the initiating UI action to the correct visible result; mutation timing includes persistence acknowledgment. Search timing includes any debounce. No platform or operation class is hidden by pooled statistics.

**NFR-PERF-004 Backup and restore budgets**

Under protocol P3, export and restore shall each complete at p95 within 5,000 milliseconds for the representative dataset.

Acceptance: Timing excludes user time in file selection and confirmation, includes serialization or validation and persistent completion, and includes the correct restored view. Every measured backup passes semantic round-trip comparison.

**NFR-PERF-005 Responsive pending states**

Any operation that remains pending for more than 500 milliseconds shall display an accessible busy state while the application continues to process viewing, focus, and window interactions.

Acceptance: A deliberately delayed storage operation shows feedback within 500 milliseconds and does not freeze the UI. Under that fixture, focus and window interactions respond within 250 milliseconds. Conflicting mutations remain blocked under FR-018.

### Security and accessible interaction

**NFR-SEC-001 Untrusted text and operation inputs**

The native application shall validate all externally supplied operation inputs, including UI commands and backup contents, independently of UI validation, and shall treat task and search text as non-executable data.

Acceptance: Direct boundary tests reject invalid values; SQL-shaped text cannot alter query structure; markup-shaped titles and notes display as text and cannot execute script or access native operations.

**NFR-SEC-002 Restricted runtime privileges**

The release application shall load executable UI content only from bundled resources and expose only native capabilities and commands required by accepted features.

Acceptance: Permission and content-policy review plus denied-operation tests cover remote content, arbitrary shell execution, unrestricted file access, and undeclared commands. Generated WebAssembly support is allowed. Release packages exclude developer command mocks, test servers, and automation-only mutation interfaces. [S3] [S4]

**NFR-A11Y-001 Keyboard operation**

Every user operation shall be executable using a keyboard alone, with visible focus, a logical focus order, and no keyboard trap.

Acceptance: Complete all functional journeys without a pointing device. Modal interactions preserve focus within the active dialog and return it to a meaningful location when dismissed; focus is not hidden by application content. WCAG 2.2 criteria 2.1.1, 2.1.2, 2.4.3, 2.4.7, and 2.4.11 guide verification. [S5]

**NFR-A11Y-003 Visual readability**

The interface shall meet the contrast and resizing criteria specified here: at least 4.5:1 for normal text, 3:1 for large text, and 3:1 for meaningful control boundaries and state indicators, with all operations remaining usable at 200 percent text size.

Acceptance: Verify WCAG 2.2 criteria 1.4.3, 1.4.4, and 1.4.11, including their defined exceptions, at a 1280 by 720 logical-pixel window. Enlarged text does not clip essential content or make actions unreachable. These listed criteria do not constitute a claim of full WCAG conformance. [S5]

### Diagnostics and release evidence

**NFR-OBS-001 Useful private diagnostics**

The application shall record local diagnostic events for startup, storage failures, backup and restore outcomes, and migration outcomes without recording task titles, notes, due dates, search text, backup contents, or user-selected absolute paths.

Acceptance: Each event includes timestamp, severity, application version, operation category, correlation identifier, and a non-sensitive outcome or error code. A seeded sensitive-text suite finds none of its values in diagnostics. Total retained diagnostic files remain within 10 MiB and diagnostic write failure cannot corrupt or prevent a valid task operation.

**NFR-QUAL-001 Requirement verification**

The release evidence shall map every requirement ID to passing verification against the delivered revision, including successful behavior and the required negative, boundary, recovery, and performance cases.

Acceptance: Automated domain and boundary tests, actual embedded-Turso integration tests, packaged desktop acceptance, accessibility assessment, and benchmarks are recorded with their environments. Evidence distinguishes delivered packages from instrumented builds of the same revision. Instrumentation cannot substitute for installation, runtime restrictions, and normal user journeys in the delivered package. Mocks alone cannot satisfy persistence or packaged-platform requirements. A skipped or unexplained check is not a pass.

**NFR-QUAL-002 Maintainable release handoff**

The release shall include reproducible build and verification commands, local-user documentation, data-format compatibility notes, dependency inventory, and a project validation report identifying the delivered commit and package digests.

Acceptance: Another developer can build and run verification from a clean checkout using the documented prerequisites. The report links requirement results and benchmark outputs and records unresolved defects; no unresolved defect violating a Must requirement can be accepted as release complete.

## 6 Reference platforms and performance protocols

This section is normative through NFR-PLAT-001 and NFR-PERF-001 through NFR-PERF-005. The approved specification selects one acceptance environment meeting the platform matrix below and records its actual operating-system patch/build, WebView build, tool versions, hardware model, available RAM, virtualization details when applicable, fixture digest, and instrumentation before implementation. These details make the evidence reproducible; they do not restrict support to one OS patch, chip generation, or machine identity.

### Supported platform matrix

| Platform | Supported release and architecture | Reference hardware |
|---|---|---|
| macOS | macOS 26.x, arm64 (Apple silicon) | Apple silicon Mac with 32 GB RAM or greater and local SSD storage; a macOS VM must have at least 32 GB RAM allocated to the guest |

A physical Mac or a macOS VM on Apple silicon meeting this matrix is eligible for acceptance. Windows, Linux (including Ubuntu), macOS releases outside 26.x, Intel Macs, and environments below the RAM minimum are outside this baseline; their absence is not an application acceptance blocker. Native qualification, packaged functional tests, accessibility checks, and benchmarks are required on the selected acceptance environment. Installer format is selected in specification. Each benchmark uses the release package, an active 1280 by 720 logical-pixel window, AC power and normal performance mode on the physical host, at least 15 GiB free local storage, and no concurrent build or benchmark workload. Application data and backup destinations are on the same local SSD, including the backing storage for a VM. No network filesystem is supported for live database storage.

### Representative dataset D1

D1 contains exactly 10,000 tasks: 8,000 Open and 2,000 Completed. Titles contain 80 scalar values and notes 256 scalar values. At least ten percent of text values include non-ASCII characters. Due dates are distributed equally among absent, yesterday, today, and tomorrow relative to a fixed test date. Status and due-date distributions are independent. Creation timestamps include ties. Search fixtures include zero-match, one-match, and many-match queries, literal punctuation, case variants, and canonical Unicode equivalents. The fixture seed, generated content, expected identity sets, expected ordering, and digest are frozen in specification.

Correctness fixtures separately exercise all valid field limits, 10,000 tasks with maximum-length content, duplicate titles, invalid inputs, and backup failures. Include a legitimate clock correction where an updated timestamp precedes an earlier completion timestamp; no unstated chronological invariant may reject that task. The performance numbers do not promise the same latency for every maximum-length dataset.

### Measurement protocols

| Protocol | Workload and timing | Required sampling |
|---|---|---|
| P1 Launch | Start at application process creation; stop when the correct default D1 view is rendered and accepts input. Fully exit between launches. OS file caches are not cleared. | Five unmeasured warm-up launches, then 30 measured launches per platform. Report every sample, p50, p95, and maximum. |
| P2 Interactions | Time UI action to correct settled result. Mutations include commit acknowledgment; deletion starts after confirmation. Create begins with 9,999 D1-derived tasks; edit changes stored content; complete begins Open; reopen begins Completed; delete targets an existing task. Reset fixtures outside timing. | Ten warm-ups then 100 measured operations per class per platform. Include create, edit, complete, reopen, delete, search, status filter, date filter, and ordering classes. |
| P3 Backup | Export starts after file selection and any overwrite confirmation. Restore starts with selected file validation and pauses timing only for user confirmation; stop after commit and correct rendered results. Use two distinct datasets with D1's sizes and distributions but different identities and content, so a no-op restore cannot pass. | Three warm-ups then 30 measured exports and 30 measured restores per platform. Compare restored task fields and identities against the independent replacement fixture for each cycle. |

Use the nearest-rank percentile: sort n samples and select sample ceil(0.95 multiplied by n). Keep all valid measurements, including slow results. A measurement invalidated by an independently recorded environmental or instrumentation failure is labeled and rerun; threshold failures cannot be discarded as outliers. Any operation error fails correctness regardless of latency. If a specified reference environment is unavailable, its benchmark remains unverified rather than silently substituted.

## 7 Verification scope and failure model

The following verification families define minimum coverage to expand into detailed scenarios during specification. They are acceptance obligations, not an implementation backlog or a phase plan.

| Family | Requirement coverage | Minimum cases |
|---|---|---|
| V1 Task lifecycle | FR-001 through FR-009, FR-016 through FR-018 | Fresh profile, complete lifecycle, identical task content with distinct identities, exact limits, invalid data, discarded and retained drafts, repeated activation, confirmed and uncertain write outcomes. |
| V2 Query and calendar | FR-010 through FR-014 | Exact identity sets and sort order, AND combinations, notes-only search, Unicode and punctuation, null due dates, timestamp ties. |
| V3 Backup and lifecycle | FR-019 through FR-025 | Export with active filters, round trip into a fresh profile on the selected acceptance environment, overwrite cancellation and failure, invalid and empty backup, confirmation, atomic replacement, double launch, and offline help. |
| V4 Architecture and environment | NFR-TECH-001 through NFR-TECH-004, NFR-ARCH-001 through NFR-ARCH-002, NFR-MAINT-001, NFR-PLAT-001 | Source and dependency inspection, contract generation and boundary checks, clean builds, actual embedded database, justified module ownership, clean platform installation. |
| V5 Data and privacy | NFR-OFF-001, NFR-PRIV-001 through NFR-PRIV-002, NFR-DATA-001 through NFR-DATA-004, NFR-SEC-001 through NFR-SEC-002, NFR-OBS-001 | Network isolation and observation, account isolation, command abuse, untrusted text, abrupt termination, storage failure, unsupported format, applicable migration, and diagnostic redaction. |
| V6 Capacity and performance | NFR-PERF-001 through NFR-PERF-005 | Capacity and maximum-length correctness, P1 through P3 on the selected acceptance environment, delayed-operation responsiveness, and full raw results. |
| V7 Accessibility and handoff | NFR-A11Y-001 and NFR-A11Y-003, NFR-QUAL-001 through NFR-QUAL-002 | Keyboard journeys, specified contrast and resizing checks, complete requirement mapping, reproducible commands, and artifact identity. |

For NFR-DATA-001 and NFR-DATA-002, the required process-failure model is abrupt termination of the application while the operating system, local filesystem, and storage device remain functioning. The harness records an independent acknowledgment ledger and forces termination before commit, while commit is pending, and after acknowledgment. For each mutation class and whole-collection restore, exercise each cut point 20 times per supported platform; all reopened states must satisfy the stated atomicity and durability rules. Use controlled fault injection and deterministic checkpoints to make cut points meaningful.

Power loss, operating-system failure, faulty storage hardware, external modification of the database, and a malicious process with the same account privileges are outside this verified failure model. The specification still selects documented durable database settings and does not infer local durability from Turso Cloud service guarantees. Backup safety includes export failure and interruption; backup restoration is tested independently of the source database.

The specification produces a complete requirement-to-scenario matrix and defines expected results before implementation. Successful golden paths alone are insufficient for the obligations above. An ambiguity that changes behavior or weakens a threshold is resolved in the requirements or specification baseline before preparation; it is not silently decided during implementation.

## 8 Release acceptance and amendment policy

Release acceptance requires every Must requirement to pass its declared verification on the delivered revision and required platforms. The final project validation report records the requirements baseline, approved specification baseline, tested commit, package identities, contract-generation checks, test results, benchmark samples, accessibility evidence, and any defects.

A numerical target, supported platform, functional behavior, or technology constraint changes only through a requirements amendment. An implementation limitation is evidence for a blocker, not permission to redefine success. Once an accepted baseline exists, a new feature or changed requirement retains stable traceability through its revised IDs and the downstream impact analysis.

For release one, migration from a previous application release is not applicable because no previous release exists; initial-format fixtures and rejection of unknown future formats remain required. No other verification family is implicitly optional.

## 9 Technology references

These references explain the selected technology constraints and verification guidance. They do not independently guarantee that the proposed application meets its requirements. Accessed 7 October 2026.

- **S1 Turso Rust quickstart:** https://docs.turso.tech/sdk/rust/quickstart. The current guide recommends the `turso` crate for local use and makes cloud synchronization optional. This document intentionally uses that route rather than a legacy remote-replica tutorial.
- **S2 Tauri frontend configuration:** https://v2.tauri.app/start/frontend/. Tauri supports packaged web content and Rust frontend options. This supports Rust UI behavior while allowing generated interop and leaving the framework choice to specification.
- **S3 Tauri capabilities:** https://v2.tauri.app/security/capabilities/. Capability scoping and native-side validation are separate concerns; both need explicit verification.
- **S4 Tauri content security policy:** https://v2.tauri.app/security/csp/. The policy must be configured for the actual packaged assets, including any required WebAssembly loading.
- **S5 Web Content Accessibility Guidelines 2.2:** https://www.w3.org/TR/WCAG22/. The identified criteria define the accessibility targets; this draft does not claim complete conformance.
- **S6 Turso multiprocess access:** https://docs.turso.tech/sql-reference/multiprocess-access. The current local engine defaults to one database-owning process; experimental multiprocess behavior is unnecessary for this scope.
- **S7 Turso Rust reference:** https://docs.turso.tech/sdk/rust/reference. Reference for local connections and transaction behavior to qualify during specification.

## 10 Revision record

| Version | Date | Change |
|---|---|---|
| 0.1.0 | 2026-10-07 | First proposed requirements baseline for the local Rust and Tauri Todo application with embedded Turso. |
| 0.2.0 | 2026-10-08 | Developer-authorized revision 2: restrict support and verification to the current macOS 26.7 / M3 Max / 128 GiB Mac; replace cross-platform backup verification with a fresh-profile round trip on that Mac. All 52 IDs, functional capabilities, performance thresholds and sampling, privacy, and accessibility obligations are retained within this platform scope. |
| 0.3.0 | 2026-10-11 | Developer-authorized revision 3: broaden support and acceptance to macOS 26.x on Apple silicon with at least 32 GB RAM, including qualifying macOS VMs. Specification records the selected acceptance environment for reproducibility. All 52 IDs, functional capabilities, performance thresholds and sampling, privacy, and accessibility obligations are retained within this broader platform scope. |
| 0.4.0 | 2026-10-25 | Developer-authorized revision 4: lower the Section 6 benchmark free-local-storage minimum from 20 GiB to 15 GiB. All other platform conditions, performance budgets, sampling, and verification obligations remain unchanged. |
| 0.5.0 | 2026-10-27 | Developer-authorized revision 5: retire and reserve FR-015 without renumbering FR-016 through FR-025; remove its refresh timing thresholds and the corresponding midnight, leap-day, time-zone-change, and suspend/resume verification cases. All unrelated requirements and rules remain unchanged. |
