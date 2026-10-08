# RDD harness

A runnable, repository-local Requirements Driven Development harness for Codex. It turns a formal requirements document into a frozen solution, a dependency-ordered implementation backlog, and a verified stack of phase pull requests.

The included `requirements/requirements.md` is the supplied Rust Todo requirements document, preserved byte for byte. The Todo application is intentionally not implemented. Run the three workflows to generate it, then use amendment runs to maintain it.

The harness contains executable orchestration and validation, 24 original skills, five Codex roles, JSON artifact schemas, a Rust Protobuf service-trait generator, CI, and regression tests. There is no Python package installation: the controller uses Python 3.11+ standard-library modules.

## Quick start

Unzip the repository into its own directory. In a terminal:

```sh
cd rdd-harness
./rdd init
./rdd selftest
./rdd doctor --full
git add .
git commit -m "Initialize RDD harness and Todo requirements"
```

On Windows use `python tools/rdd/cli.py`, `rdd.cmd`, or `./rdd.ps1` in place of `./rdd`. If an extractor does not preserve the executable bit on Unix, use `python3 tools/rdd/cli.py` or `chmod +x rdd`.

`doctor --full` reports missing external prerequisites. Install the tools listed below and authenticate Codex/GitHub locally. A missing dependency is a concrete environment blocker, not a successful check. If Git has no author identity, configure your own repository-local name/email before the initial commit.

Create your GitHub repository, then connect it using your actual repository URL:

```sh
git remote add origin YOUR_GITHUB_REPOSITORY_URL
git push -u origin main
```

Run these in order:

```sh
./rdd workflow specification --mode regenerate
./rdd workflow preparation
git push origin main
./rdd workflow implementation
```

The first two commands launch interactive Codex with the relevant skill. Specification may ask architectural questions; preparation must return unresolved requirements/solution issues to specification. Each workflow commits its accepted baseline. Push the prepared baseline before implementation so the first phase PR has the correct remote base and CI can use the trusted frozen artifacts.

**Activate native goal mode for implementation.** The implementation launcher opens Codex and explains the handoff. In that Codex session, submit `/goal` followed by the exact output of:

```sh
./rdd goal
```

The objective is checked to be under 4,000 characters. The launcher does not pretend that an ordinary prompt or an invented `codex exec --goal` option activates native goal mode. You can also launch Codex yourself, invoke `$specification-workflow` and `$preparation-workflow` sequentially, then use the implementation objective with `/goal`.

To inspect a launch prompt, use `./rdd workflow STAGE --print`. An explicitly supplied `--mode` starts that requested run before printing the packet. `./rdd status` is always the place to read current state and source identities.

## Local prerequisites

| Dependency | Purpose |
| --- | --- |
| Python 3.11+ | Portable controller and offline regression suite; no third-party Python dependency |
| Git | Exact source identity, isolated worker worktrees, phase branches and checkpoint recovery |
| Codex CLI with native Goals and custom subagents | Interactive orchestration and multi-agent execution |
| Model/account access | `gpt-6-astra` at `ultra`, `gpt-6.1-sol` at `xhigh`, and `gpt-6-luna` at `xhigh`; no silent downgrade |
| GitHub CLI `gh` and an authenticated GitHub remote | One PR per phase, base/head checks, required CI status and stack verification |
| Rustup and the repository's pinned Rust toolchain | Rust generator, native code, Rust/WASM UI and future application checks |
| Buf CLI | Protobuf linting, descriptors and optional breaking checks |
| Native Tauri platform dependencies | Actual desktop build, integration and packaging checks on each supported OS |

`rust-toolchain.toml` pins Rust and includes `rustfmt`, `clippy`, and `wasm32-unknown-unknown`. The CI configuration pins its Buf setup and records actual tool versions. The embedded Turso dependency version, Rust UI framework, UI build tools and Tauri plugins are selected and locked during specification qualification against the supplied requirements. They are not silently predetermined as application code in this boilerplate.

Protoc is optional for the shipped generator: Buf produces a descriptor set, and Prost consumes it through `compile_fds`. The initial qualification resolves and commits real Cargo lockfiles; no lockfile or compiler output is fabricated in the archive.

Install Tauri platform prerequisites from its official guide. Configure any licensed/test-only macOS UI driver, manual accessibility evaluation, and performance reference machines required by the final specification. Default hosted CI is not a substitute for reference hardware or an actual screen-reader evaluation.

## What the three workflows do

| Workflow | Accepted output | Controller transition |
| --- | --- | --- |
| Specification | Requirement coverage, complete solution documents, scenarios, module ownership/dependency graph, public/local contracts, executable verification definitions and qualified generated types | `spec init` → `spec validate` → `spec freeze` |
| Preparation | Concrete target paths, task categories/write scopes, task DAG, verticals, dependency-closed phases, reuse decisions, phase checks, shells and inline/sidecar task projection | `plan init` → `plan validate` → `plan freeze` → `prepare` |
| Implementation | TDD changes, live independent review, cumulative exact-source evidence, one verified PR per phase, immutable phase seals and final project report | `phase begin` → tasks/checks/review → `gate phase` → `stack publish` → `phase seal` → `gate project` |

The model authors the reasoning and artifacts. The controller checks their structure, traceability, dependencies, source identity, task order, evidence and state transitions. It does not claim that a schema validator can judge every semantic requirement or replace an independent reviewer.

### Specification and Protobuf qualification

The specification workflow resolves ambiguity before freezing. It must derive every functional and non-functional obligation, including global data rules outside individual requirement IDs. Every functional requirement needs a golden path; negative, boundary, concurrency, fault, security, accessibility and benchmark coverage are added where required.

The included `contracts/rdd/v1/harness.proto` is a toolchain qualification fixture. It is not a preselected Todo domain model. The specification workflow adds the actual application schemas and includes their complete source/generated inventories in `.rdd/spec.json`.

First contract qualification within an active specification run:

```sh
./rdd contracts generate --bootstrap-lock --target wasm32-unknown-unknown
./rdd contracts check --target wasm32-unknown-unknown
```

Commit the resulting generator/generated-crate lockfiles and outputs before freezing. Keep `gen/rust/` absent or empty until first successful generation: the generator refuses to overwrite a nonempty directory it does not own.

The generator emits Rust messages and **local unary service traits** from Protobuf. Its checks compile both valid providers and an intentionally wrong signature that must be rejected by the compiler. Ordinary message generation alone would not enforce provider method signatures. Application architecture checks must additionally prove that real module providers and consumers use these generated boundaries; the generator cannot infer that from a `.proto` file.

Contracts and generated types are immutable downstream. Any needed signature/shape change returns to the specification workflow. No networking server is introduced merely to enforce an in-process boundary. Streaming interfaces require an explicit generator/specification amendment.

The supplied requirements also demand native/runtime/database/UI qualification before contract freeze. Register those real qualification commands among the specification's `contract_check_ids`, with their actual native `platforms`. After committing the complete draft, `./rdd check CHECK_ID` can execute these checks before a lock exists. The draft's prospective lock digest binds each receipt. Transfer the same Git draft and a run checkpoint to other native hosts, resume it there, and run their checks. Bring actual receipts/logs back with `./rdd check import FILE --local-host` (or the CI provenance route for a real CI runner). `spec freeze` requires every declared native platform, and a changed draft invalidates old qualification receipts.

### Tasks, verticals, and phases

Tasks carry stable IDs, requirements, solution references, exact file write sets, dependencies, acceptance statements and category. A vertical is an ordered chain of prerequisites in the task DAG. Every task belongs to at least one vertical, and each adjacent pair must be ordered by the dependency graph.

Phases are sequential dependency cuts. A task cannot depend on a future phase, and a requirement cannot close before its final scoped task and complete scenario checks. The phase reviewer also verifies semantic independence: no future work is required for obligations being accepted now.

Within each open phase, task selection is strictly:

1. **Tests**: create actual failing behavioral assertions.
2. **Deletion**: remove obsolete implementation deliberately.
3. **Modification**: extend existing owners and behavior.
4. **Addition**: add a missing capability only after the frozen reuse analysis justifies it.
5. **Documentation**: reflect the accepted implementation and verified usage.

A dependency that conflicts with this order is rejected in planning. Move foundational prerequisites to an earlier phase or reformulate the test boundary; do not call a compilation failure a behavioral RED.

Preparation creates empty or comment-only shells. Tests-stage tasks may introduce test-only build fixtures and contract-consumer scaffolding required to make the first behavioral assertion execute. They cannot smuggle product behavior into preparation or label production implementation as test scaffolding.

Inline markers look like `// RDD:P01:T001 [tests] ...`. Noncommentable formats use `.rdd/plan/anchors/T001.md`. The frozen task manifest and transactional state are authoritative; comments are a projection. `anchors verify` catches missing, duplicate or misplaced markers. `anchors reconcile` performs recoverable projection cleanup; it never marks a task done merely because its comment disappeared.

### Implementation and live review

The coordinator uses `gpt-6-astra` / `ultra`. Large implementors and the independent reviewer use `gpt-6.1-sol` / `xhigh`; small implementors use `gpt-6-luna` / `xhigh`. At most two implementation leases run concurrently, leaving a subagent slot for live review.

Each worker receives a bounded packet and an isolated Git worktree. The controller only integrates a linear commit sequence that descends from the leased base and changes the declared files. Controller, requirements, specification, generated contracts, skill, CI and policy paths are protected from implementation tasks.

For example, the coordinator follows this pattern using real task/check IDs from the plan:

```sh
./rdd phase begin P01
./rdd next
./rdd task claim T001 --worker rdd_large --worktree
# Worker implements its scoped test task in the returned worktree and commits it.
./rdd task integrate T001 --commit FULL_WORKER_COMMIT_SHA
./rdd check THE_FROZEN_TEST_CHECK --expect fail --task T001
./rdd task complete T001 --evidence THE_RECORDED_EVIDENCE_ID
# Commit the controller's marker cleanup before the next claim/integration.
```

Test task completion checks the actual behavioral RED receipt. Other task completions record integration and ownership; they do not introduce per-task review gates. The live reviewer observes progress, sends corrections and provides the independent final phase review. The coordinator runs phase checks before that final review so the reviewer can assess real evidence; the gate rechecks freshness.

A completed task in the current open phase may be reopened for a scoped repair with `task reopen --reason`. Repair work uses the same category order and existing scope. A sealed phase cannot be reopened. A defect in a previously accepted obligation is a closure failure that starts a new requirements/specification amendment; this preserves the old run's failure history.

### Review gates and stacked PRs

At phase completion the candidate must be committed, task markers reconciled, cumulative checks passing, native/manual evidence present, and the independent review bound to the exact Git commit and source digest.

```sh
./rdd review record .rdd/runtime/phase-review.json
./rdd gate phase P01
./rdd stack publish P01
./rdd stack verify
./rdd phase seal P01
```

Each phase branch is `rdd/RUN_ID/pNN`. The first PR targets the committed preparation baseline branch. Each later PR targets the preceding sealed phase branch. Publication is idempotent and checks existing PRs in every state, branch identity and the recorded base SHA. The controller does not force-push or rewrite sealed branches.

The default completion policy is **ready**: every phase PR exists, is open and non-draft, has required CI checks passing at the exact accepted head, and has the independent review. An actual GitHub changes request vetoes readiness; an additional human approval can be required in `.rdd/config.json` before specification freeze. Repository rules may require more approvals independently.

PR merging and release publishing remain separate developer actions. Keep the stack unmerged while the run is active so the recorded bases remain stable. After final project validation, merge with your normal stack-aware process. A moved base or rewritten closed branch is reported as a blocker, not silently restacked.

### CI and external evidence

The workflow runs on Linux, macOS and Windows. The aggregate required check is named `verify`. It loads the controller and policy from the trusted base checkout, compares protected inventories and frozen locks before executing candidate checks, and publishes check receipts and raw logs.

Before an application plan exists, CI explicitly reports `harness_only` and `application_complete=false`. A prepared baseline verifies its contracts and pending anchors. A phase PR executes the cumulative ordinary checks applicable to that native platform. Manual checks and reference-host benchmarks are listed as pending external evidence; they are enforced by the local phase/project gate and are never converted into hosted-CI success claims.

On nonphase branches, CI accepts only a marker projection matching one complete phase prefix and runs the cumulative ordinary checks through that prefix. It reports `observed_through_phase` and uses `source_cumulative` scope when a phase prefix is present; `phase` remains `null`, and both `task_history_verified` and `application_complete` remain `false`. A separate trusted base prevents the candidate from reducing this coverage. This projection selects checks; it does not prove task completion, phase seals, review, or project acceptance. Push verification uses the pushed revision for both checkouts, so it cannot independently detect coverage rollback relative to an earlier revision.

Protect the verification workflow and policy paths with repository review/rules, or an externally required workflow. A repository-local harness is not a security sandbox against a malicious actor who can rewrite its verifier, forge observers, or modify the local state database. Read `docs/harness/security-model.md` for the exact trust boundary.

The first specification/preparation baseline must be deliberately committed to the trusted base branch. An implementation PR cannot introduce, replace or remove its own frozen policy to grant itself permission.

## Amendments and regeneration

For an amendment, edit the canonical requirements under your direction, commit that edit, and run:

```sh
./rdd workflow specification --mode amend
./rdd workflow preparation
git push origin YOUR_BASELINE_BRANCH
./rdd workflow implementation
```

The controller compares the previous requirements index, preserves prior artifacts/run history, and requires a frozen impact analysis and bounded affected paths. Global glossary/data-rule changes conservatively expand requirement impact. The new plan may only modify the approved impact surface. Unaffected code is preserved.

A regenerate run archives prior artifacts and clears the prior solution/plan artifacts for regeneration. It does **not** blindly delete application source. If existing code must be replaced, the new plan schedules explicit deletion/modification/addition tasks. This preserves reviewability and data safety.

Regenerate changes the design baseline. Amend changes a defined part of that baseline. Both are new runs with their own phase seals; neither edits the historical meaning of a closed phase.

## Recovery and completion

```sh
./rdd status
./rdd export-run .rdd/evidence/run-checkpoint.json
./rdd resume
```

SQLite transactions persist task state, attempt budgets and leases. CLI mutations are serialized by an OS lock, while read-only status remains available to the live reviewer. Worker branches/worktrees survive release and lease expiry. An interrupted integration records its intent before cherry-picking; recovery compares the actual result with the leased submission. Conflicts require explicit resolution or abort before resumption and are not discarded automatically.

To move a run, transfer the Git repository at the exact checkpoint commit plus the exported checkpoint. Recreate/preserve any outstanding worker branches separately. Then:

```sh
./rdd resume --from PATH_TO_RUN_CHECKPOINT.json
```

Imports verify source/lock identity, evidence paths and raw-log hashes. Checkpoints and local observer identities are trusted records, not cryptographic attestations. Environment/review blockers may resume after their underlying cause is fixed; authority, planning, closed-phase and exhausted-budget blockers require a new specification run.

Final completion is accepted only when:

```sh
./rdd gate project
```

returns `status: passed` and `application_complete: true`. This requires all canonical tasks done, zero remaining task markers, every phase sealed, the entire stack currently verified, all cumulative/project tests and independently evaluated benchmarks passing, and current evidence for every required platform/observer.

Outputs:

- `.rdd/evidence/project-validation.json`: requirement coverage, exact source/baselines, checks, metrics, reviews and PR identities.
- `.rdd/evidence/project-validation.md`: readable acceptance report.
- `.rdd/evidence/completed-run.json`: portable run state and raw-log checkpoint.

Evidence and runtime state are ignored by Git to avoid a tested revision invalidating itself when its receipt is written. Export them before discarding the working checkout. The controller's source digest covers tracked and nonignored source files; generated build caches, runtime, evidence and the active run locator are outside it. Build inputs must not be hidden in ignored locations.

## Repository map

| Path | Responsibility |
| --- | --- |
| `requirements/requirements.md` | Canonical supplied requirements |
| `docs/specs/`, `docs/decisions/` | Solution and approved decisions produced by specification |
| `contracts/`, `gen/` | Canonical schemas and qualified generated outputs |
| `modules/`, `apps/` | Future language-appropriate application structure |
| `tests/acceptance/`, `tests/integration/` | Future requirement and real-boundary verification |
| `tests/harness/` | Existing harness regression tests |
| `benchmarks/` | Future workload implementations; raw-metric and host-qualification guidance |
| `.rdd/schemas/`, `.rdd/plan/` | Machine formats and the frozen implementation plan |
| `.rdd/run.json` | Ignored active run/baseline locator, included inactive in the archive |
| `.rdd/evidence/`, `.rdd/runtime/` | Revision-bound reports, transactional state and checkpoints |
| `.rdd/baselines/` | Versioned historical artifact copies |
| `.agents/skills/` | Three workflows and supporting skills |
| `.codex/agents/` | Worker, reviewer, researcher and coordinator roles |
| `.github/workflows/` | Trusted verification and native platform matrix |
| `tools/rdd/`, `rdd` | Executable controller and CLI |
| `tools/proto-codegen/` | Rust message and local service-trait generator |
| `AGENTS.md` | Compact authority and navigation instructions |

## Skill inventory

| Group | Skills |
| --- | --- |
| Primary workflows | `specification-workflow`, `preparation-workflow`, `implementation-workflow` |
| Planning and integrity | `research-dependencies`, `domain-boundaries`, `plan-verticals`, `plan-phases`, `reuse-analysis`, `amend-requirements`, `context-integrity`, `phase-review` |
| Rust and platform | `rust-domain-types`, `rust-async-tokio`, `rust-testing`, `tauri-application`, `tauri-commands-events`, `turso-embedded`, `protobuf-contracts` |
| Development operations | `create-module`, `create-api`, `create-ui-page`, `observability`, `documentation`, `create-test-suite` |

Each skill includes original examples and official-source references. The Tauri material covers Rust/WASM UI, commands versus events/channels, boundary validation, capabilities/CSP, platform packaging and listener lifetimes. Turso means the current embedded `turso` crate requested in the supplied requirements, with locally qualified transactions, migrations and backup/restore behavior.

## Further documentation and validation scope

Read `docs/harness/workflow-guide.md`, `artifact-guide.md`, `evidence-guide.md`, `codex-runtime.md`, and `security-model.md`. `docs/harness/validation.md` records what was actually exercised while this archive was built.

The offline tests execute real Python processes, Git worktrees, state transitions, RED/GREEN assertions, metric evaluation and recovery. External GitHub/model operations use explicit fixtures where noted. Actual contract compilation needs Rust and Buf; live model invocation needs account entitlement; production Todo validation only exists after the three workflows have generated and tested that application. The harness reports missing evidence as a blocker.

## Refining the harness

Before specification freeze, adjust protected controller policy, budgets, tool versions, models/roles, checks and skills through deliberate review. Run `./rdd selftest` after changes. The configuration, schemas, roles, skills, verifier and generated contracts become part of the frozen authority for an implementation run; implementation tasks cannot silently change their own acceptance rules.
