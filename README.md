# RDD harness

A repository-local **Requirements Driven Development (RDD)** harness for Codex. It turns formal requirements into a frozen solution, a scoped implementation plan, and a verified stack of phase pull requests, with evidence connecting the result back to the original requirements.

This repository includes the canonical [Rust Todo requirements](requirements/requirements.md), with developer-authorized amendments recorded in their revision history. The Todo application has **not been implemented**. The harness supplies the controller, agent skills, artifact schemas, contract generator, CI, and regression tests needed to develop it through the workflows below.

[Understand the workflow](#how-the-workflow-fits-together) · [Prerequisites](#prerequisites) · [Get started](#get-started) · [Recovery](#follow-progress-and-recover) · [Completion](#what-counts-as-complete) · [Guides](#important-files-and-guides)

## What is RDD?

RDD keeps product obligations connected to design decisions, implementation work, and measured results. Functional requirements describe what the application must do. Quality constraints describe properties such as reliability, performance, privacy, and accessibility. Both become explicit solution specifications, contracts, scenarios, and verification checks before application implementation begins.

The traceability chain is:

**Requirement ↔ subdomain/behavior ↔ scenario/check ↔ groomed task/work sites ↔ phase evidence and PR ↔ project validation**

A scenario describes the behavior or constraint to prove; a check supplies its executable test or evidence protocol. Tasks identify the exact work and allowed files. Phase review establishes whether that work satisfies the obligations being accepted. Final project validation combines the results across the whole application. A completed checklist or a model's success message cannot replace this evidence.

## How the workflow fits together

![Conceptual RDD flow: requirements become specifications and contracts, preparation organizes tasks into verticals and phases, and implementation repeats tests, tasks, and acceptance until project validation.](docs/harness/rdd-diagram.svg)

[Open the full RDD diagram](docs/harness/rdd-diagram.svg).

The diagram is conceptual; the controller and frozen artifacts define the operational rules. Its labels are outlined graphics, so the walkthrough below also describes the flow in text.

1. **Specification** derives every functional subdomain and behavior, the complete target folder system, contracts, golden scenarios and quality protocols. Research and real qualification establish execution feasibility. Two independent perspectives—semantic coverage and execution readiness—must approve the same candidate with zero unresolved findings before freeze.
2. **Preparation** fully grooms every task, producer/input dependency, phase, category, vertical and work site within the frozen solution. It creates safe comment-only shells, full primary task packets, linked local packets and the matrix. Materialization enters `preparing`; actual readiness/CI evidence and final two-perspective review must pass `gate preparation` before implementation.
3. **Implementation** works through the phased backlog. Tests and benchmarks are implemented according to the scoped phase tasks, followed by production changes, independent review, and acceptance checks. Each accepted phase gets a PR and seal; the project gate evaluates the final result.

| Stage | Input | Accepted output |
| --- | --- | --- |
| Specification | Canonical requirements and relevant existing code | Frozen solution and target-folder design, complete behavior/golden coverage, qualified contracts, execution prerequisites and two independent reviews |
| Preparation | Frozen solution and contracts | Fully hydrated backlog, producer closure, exact co-located work sites, phase/category/vertical projections, matrix and exact-source preparation gate |
| Implementation | Committed and pushed prepared baseline | Tested application changes, revision-bound evidence and independent reviews, one verified PR per phase, phase seals, and project validation |

**Frozen artifacts** are approved files whose exact identities are recorded by the controller. Downstream work must preserve that authority; changing a contract or acceptance meaning requires a new specification run. Generated Rust messages and local unary service traits enforce interface shapes, while application checks must also prove that real providers and consumers use those boundaries. The seed contract in this boilerplate qualifies the generator; it is not the Todo domain model or a requirement to add a network server.

A **vertical** is an ordered chain of dependent tasks toward a capability. A **phase** is a dependency-closed group of tasks: its accepted obligations may depend on earlier phases, but never on unfinished future work. An **acceptance gate** checks whether the current source, results, and review permit phase closure or project completion. See the [workflow guide](docs/harness/workflow-guide.md) for the detailed transitions.

## What the harness controls

Agents interpret requirements, research dependencies, author specifications and code, and review whether the result fulfills the intended behavior. The deterministic Python controller validates artifact structure, traceability, dependency order, task ownership, source identity, evidence, and state transitions. Structural validation supports semantic review; it cannot establish correctness by itself.

Named specialists own domain analysis, verification design, contract architecture, qualification and task planning. The [runtime roster](docs/harness/codex-runtime.md#runtime-contract) defines their assignments and models. `rdd_complex_implementor` handles large or small tasks; `rdd_light_implementor` handles small, unambiguous tasks. At most **two authors** run concurrently alongside a read-only live reviewer. Final independent review binds the exact candidate.

Workers receive bounded task packets and isolated Git worktrees with disjoint write scopes. The controller integrates committed work only from the leased base and declared files. Requirements, frozen artifacts, generated contracts, controller policy, skills, and CI cannot be rewritten by implementation tasks to weaken their own acceptance rules.

Within each phase, tasks follow this order:

**Tests → deletion → modification → addition → documentation**

Tests must first reach an actual failing behavioral assertion (RED). Missing tools, compiler errors, and skipped tests are not RED. Test-only scaffolding may make the assertion executable, but cannot supply product behavior. Additions need a frozen reuse analysis explaining why existing code cannot reasonably provide the capability.

Task markers such as `RDD:P01:tests:V01+V03:T001:A01` encode phase, classification, sorted verticals, task and work site. A full packet is co-located at the primary work site; secondary sites have local instructions and a primary reference. Noncommentable and deletion targets use adjacent sidecars. The plan and transactional state remain authoritative. Use controller commands to complete tasks and reconcile markers; never edit SQLite state, locks, receipts, or unfinished markers to force progress. Implementation review gates occur at phase completion, rather than after each task. Specification and preparation have their own two-perspective exit reviews. Frozen specification/planning defects discovered downstream are critical harness regressions: preserve evidence, repair the missing prevention and add a regression before a fresh trial.

## Prerequisites

The controller uses the Python standard library; no Python package installation is needed. Python and Git are enough for initialization and offline harness tests. The full workflows also need the tools and access below.

| Prerequisite | Purpose |
| --- | --- |
| Python 3.11+ and Git | Controller, regression suite, exact source identities, branches, and isolated worktrees |
| Qualified Codex CLI 0.162.1 with the native TUI, App Server, native Goals and custom subagents | Workflow execution and configured agent roles |
| Model/account access | The Astra/ultra, Sol/xhigh, and Luna/xhigh settings listed above; no silent model downgrade |
| GitHub CLI `gh` and a writable GitHub `origin` remote | Phase PR publication, required checks, and stack verification |
| Rustup with the [pinned Rust toolchain](rust-toolchain.toml) | Rust compiler, `rustfmt`, `clippy`, and `wasm32-unknown-unknown` for native and Rust/WASM work |
| Buf CLI | Protobuf linting, descriptors, and contract verification |
| Native Tauri development tools for each required OS | Actual desktop build, integration, and packaging qualification |

Authenticate Codex and GitHub locally before starting development, and configure your own Git author identity. `doctor --full` inspects tool availability, client capabilities, and authentication. Advertised model support **does not prove account entitlement**: the doctor always reports `account_access_verified=false` because it performs no paid model invocation. Actual access is established when the model is used. Missing tools or model access are blockers, not permission to substitute a different configuration.

The [runtime guide](docs/harness/codex-runtime.md) links installation references and explains the pinned CI tools. Specification selects and qualifies the application dependency versions, Rust UI framework, build tools, and platform testing route. Protoc is optional for the shipped generator because Buf emits descriptors that Prost can consume directly. Reference-device benchmarks and manual accessibility checks still require the actual specified environments; ordinary hosted CI does not replace them.

## Get started

Clone your repository or fork using its actual URL and enter a clean checkout. Authenticate Codex and GitHub locally, configure your Git author identity and writable `origin`, and provide the [required tools and evidence access](#prerequisites). Then run these commands in order, allowing each to finish:

```sh
./rdd workflow specification
./rdd workflow preparation
./rdd workflow implementation
```

When no run exists, specification starts a fresh regenerate run; a clean checkout on `main` gets its dedicated baseline branch and local run state. For an unaccepted stage, its command opens the qualified Codex 0.162.1 TUI under the existing approval policy and supplies stage instructions automatically; accepted stages are rechecked without relaunch. Specification asks only necessary questions in the native TUI. Preparation works interactively from its instructions, without routine user prompts. The implementation command prints the exact copy-ready `/goal` text; paste it only when no Goal exists. On retry, inspect and resume the exact recorded session and existing Goal. Never select `--last`, replace a session or Goal, or reset its accounting. For all launched stages, the first TUI action attaches with `./rdd workflow attach STAGE --launch-id UUID`, where UUID is the random launch nonce in the supplied instructions. Attach reads `CODEX_THREAD_ID` from the TUI environment and binds both; that runtime-derived thread ID is observed provenance, not authentication or backend attestation.

After the TUI exits, the runner obtains a read-only `workflow_result`; that result determines the command exit status. A command returns success only after the controller verifies that stage's acceptance. Preparation still requires committed and pushed materialization, actual preparation CI, required external evidence, and both final review perspectives before `gate preparation`. Implementation still requires every phase gate, verified PR and seal, then `gate project`. Missing tools, evidence or backend sessions leave the command incomplete. Follow the [workflow guide](docs/harness/workflow-guide.md) for detailed obligations and the [short playbook](docs/harness/blog-demo.md) for a fresh checkout.

| Exit | Meaning |
| --- | --- |
| `0` | Controller-accepted stage; for `--print`, successful inspection only |
| `1` | Invalid request or failed validation |
| `2` | Incomplete or blocked workflow; preserve diagnostics and resolve the cause |
| `130` | Interrupted workflow; preserve the recorded session and rerun the same command |

Repeating a workflow command opens the TUI for the recorded run and resumes the exact session. An already accepted stage is checked and returned without another launch. If an implementation Goal exists, inspect and resume that Goal; do not create a replacement or select the last Goal. The runner never resets an uncertain session or Goal accounting to imply progress. An explicit workflow `--mode` must match the existing run. Use the explicit new-run procedure below for an intentional amendment or replacement.

To inspect a launch packet without starting the TUI or changing branch, run state, Goals or files:

```sh
./rdd workflow specification --print
```

`--print` is pure for all three stages, including when `--mode` is supplied. Use `./rdd --help`, `./rdd selftest` and `./rdd doctor --full` for inspection. `./rdd init` remains available for initializing local state before standalone `status` commands; a workflow command handles fresh-run initialization itself. Harness selftests do not prove Todo acceptance.

On Windows, replace `./rdd` with `python tools/rdd/cli.py`, `rdd.cmd` in Command Prompt, or `./rdd.ps1` in PowerShell, keeping the same arguments. On Unix, `python3 tools/rdd/cli.py` also works if executable permissions were not preserved. Archives require their own Git repository, initial committed source and a named authoring branch before workflow execution.

`main` remains the merge-only release branch. The shipped CI verifies pushes to `codex/*-baseline` and phase PRs targeting those branches or `rdd/**`. Other branch naming patterns need a reviewed CI filter change before specification freeze. Source authoring on detached HEAD or a branch other than the recorded baseline/phase is refused. Configure the exact trusted preparation policy pin and required checks as described in the [runtime guide](docs/harness/codex-runtime.md#stacked-pr-policy).

## Follow progress and recover

Use `./rdd status` for the current run, active phase, tasks, blockers, and exact source identity. During an active run, preserve a checkpoint before moving or discarding the checkout:

```sh
./rdd export-run .rdd/evidence/run-checkpoint.json
```

After resolving an interruption, return to the recorded baseline or phase branch and rerun the same workflow command. It reconciles resumable controller state and resumes the exact recorded session; for implementation, inspect the current Goal and resume it without using `--last`. Standalone controller recovery remains available with:

```sh
./rdd resume
```

Worker branches and worktrees survive release and lease expiry. Interrupted integration is reconciled against the submitted commit; unresolved cherry-pick conflicts require deliberate resolution or abort before resume. An environment or review blocker can resume after its cause is fixed. Authority, planning, sealed-phase, and controller-limit blockers require a new specification run.

To restore on another machine, transfer the Git repository at the checkpoint's exact revision and source contents plus the exported checkpoint. Preserve outstanding worker branches separately, then run:

```sh
./rdd resume --from PATH_TO_RUN_CHECKPOINT.json
```

TUI sessions belong to the configured local runtime; a checkpoint does not create or transfer them. A missing or uncertain session stops recoverably instead of being replaced. Runtime state and evidence are ignored by Git, so pushing source alone does not transfer them. The checkpoint carries run state and raw check logs; imports verify source/lock identity and log hashes. See [recovery procedures](docs/harness/workflow-guide.md#repairs-and-interruptions) and the [evidence guide](docs/harness/evidence-guide.md) for the full process.

An older run whose baseline was recorded as `main` remains inspectable/exportable. Preserve its source and checkpoint, then start a fresh run on a dedicated baseline; do not edit recorded branch identities to move it. Branch refusals preserve dirty work and do not automatically switch, stash, reset, or rewrite artifacts.

For an intentional requirements change or a sealed design/implementation defect, preserve the prior checkpoint, commit authorized requirements edits and use `./rdd start --mode amend` from the selected baseline. Then run the three workflow commands on that new run. The amendment records impact and preserves unaffected work and history. Use explicit `start --mode regenerate` for a new full solution when a run already exists: it archives prior active artifacts, while replacement application work remains explicitly planned. Repeating a workflow command never starts that replacement run. An open-phase repair can use existing scoped tasks; a sealed phase cannot be reopened. See [amendment and regeneration](docs/harness/workflow-guide.md#amendment-and-regeneration).

## What counts as complete?

### Phase readiness and project acceptance

A phase closes only when its committed source has completed tasks, reconciled markers, passing cumulative checks, required native/manual evidence, and an independent review of that exact revision. The coordinator gates the phase, publishes its PR, verifies the stack, and seals it. The first PR targets the preparation baseline branch; each later PR targets its preceding sealed phase branch.

The default PR completion policy is **ready**: open, non-draft, reviewed, and passing required checks at the accepted head. GitHub changes requests veto readiness; additional human approval can be configured before specification freeze. Keep the stack unmerged while the run is active. The controller does not force-push or silently restack sealed phases.

Only `./rdd gate project` returning **`status: passed` and `application_complete: true`** establishes application completion. It requires all canonical tasks done, no remaining task markers, every phase sealed, the stack currently verified, and all required cumulative/project tests, benchmarks, and platform/observer evidence. It writes:

- `.rdd/evidence/project-validation.json`: source identities, requirement coverage, checks, metrics, reviews, and PRs.
- `.rdd/evidence/project-validation.md`: readable acceptance report.
- `.rdd/evidence/completed-run.json`: portable checkpoint with run state and raw check logs.

A paused Goal, a worker's prose, or passing harness tests cannot establish project acceptance. PR merging and release publishing are separate developer actions after validation.

### Release into main

After project acceptance, archive the reports/checkpoint and keep the phase stack intact. Create one `codex/rdd-release/<run-id>` branch at the accepted application commit and open a PR into `main`. The operator sets `RDD_RELEASE_POLICY_SHA` to the first phase's recorded prepared-base commit and `RDD_RELEASE_SOURCE_SHA` to the project-accepted head through repository Actions variables. Release CI requires both exact pins, uses the verifier from `main` with the separately pinned prepared policy, and rejects incomplete or changed source. Only merge after successful checks and normal review. No specification/preparation-only PR is needed on `main`. Use the delivered build/install/run instructions to launch the accepted package.

### What CI proves

CI runs on Linux, macOS, and Windows, with the aggregate check named **`verify`**. A phase PR uses the trusted base controller and policy to validate the candidate. The initial frozen specification/preparation baseline lives on its dedicated branch; an implementation PR cannot replace its own frozen policy to grant itself permission. The explicit release route uses operator-pinned policy while retaining the controller from the PR's `main` base.

Preparation has its own CI route while the run is `preparing`: pin the trusted harness commit in the repository variable `RDD_PREPARATION_HARNESS_SHA`, then push the exact materialized `codex/*-baseline` commit. Import its raw evidence before `gate preparation`; hosted success cannot replace qualified-host/manual proof. See the [workflow guide](docs/harness/workflow-guide.md#stage-two-preparation). Harness maintenance PRs also run the candidate selftests and actual native/WASM contract compiler proofs on the supported OS matrix.

Before a frozen application plan exists, CI reports `harness_only` with `application_complete=false`. An intact prepared baseline verifies contracts and pending markers. A phase PR runs cumulative ordinary checks for the applicable native platform. Manual checks and reference-host benchmarks remain pending external evidence, required at the local phase/project gates.

On nonphase branches, CI accepts only markers matching a complete phase prefix and selects cumulative checks through that boundary, including project checks at the final boundary. It reports `observed_through_phase`, using `source_cumulative` scope when phases have been completed in the source projection, or `release_source` for explicit release verification. `phase` remains `null`, and both `task_history_verified` and `application_complete` remain `false`. A separate trusted base prevents reduced coverage; a same-revision push check cannot detect rollback against an earlier revision. Marker inference selects checks without proving task history, phase seals, reviews, or project acceptance.

Protect the verification workflow and policy through repository rules and review. The harness trusts its local controller and evidence observers; it is not a sandbox against someone who can rewrite the verifier or state. See the [security model](docs/harness/security-model.md) for the trust boundary and the [runtime guide](docs/harness/codex-runtime.md#ci-and-reference-platform-evidence) for CI and native evidence requirements.

## Important files and guides

| Path | What belongs here |
| --- | --- |
| [requirements/requirements.md](requirements/requirements.md) | Canonical product obligations |
| `docs/specs/`, `docs/decisions/`, `.rdd/spec.json` | Solution and decisions produced by specification |
| `contracts/`, `gen/` | Canonical Protobuf contracts and qualified generated outputs |
| `.rdd/plan/`, `.rdd/prepared.json` | Frozen tasks, verticals, phases, matrix, markers, and preparation receipt |
| `modules/`, `apps/`, `tests/`, `benchmarks/` | Future Rust Todo application and its verification; `tests/harness/` already tests the controller |
| `.rdd/run.json`, `.rdd/runtime/`, `.rdd/evidence/` | Ignored local run locator, transactional state, and verification results |
| `.rdd/baselines/` | Historical baseline artifact copies |
| [.agents/skills/](.agents/skills/README.md), [.codex/agents/](.codex/agents/) | Workflow/supporting skills and Codex roles |
| [tools/rdd/](tools/rdd/), [tools/proto-codegen/](tools/proto-codegen/) | Python controller and Rust contract generator |
| [.rdd/config.json](.rdd/config.json), [AGENTS.md](AGENTS.md) | Controller policy and repository authority rules |

For deeper work, use the existing guides:

- [Workflow guide](docs/harness/workflow-guide.md): stage procedures, task integration, review, repair, and recovery.
- [Fresh local playbook](docs/harness/blog-demo.md): setup, the three workflows, acceptance and packaged-app handoff.
- [Artifact guide](docs/harness/artifact-guide.md): manifests, schemas, frozen identities, and authoring boundaries.
- [Evidence guide](docs/harness/evidence-guide.md): real check receipts, native/manual imports, metrics, and provenance.
- [Codex runtime guide](docs/harness/codex-runtime.md): client setup, Goals, adapters, PR policy, and CI.
- [Security model](docs/harness/security-model.md): trusted components and limits of verification.
- [Skill guide](.agents/skills/README.md): the three primary workflows and supporting skills.

Adjust protected harness policy, tools, models, or skills through deliberate review before specification freeze, and run `./rdd selftest` after harness changes. During implementation, those frozen rules remain part of the acceptance authority.
