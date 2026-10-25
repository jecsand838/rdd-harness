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

| Stage | Authoritative procedure | Accepted output |
| --- | --- | --- |
| Specification | [Specification workflow](docs/harness/workflow-guide.md#stage-one-specification) | Frozen solution, contracts, scenarios and qualified execution prerequisites |
| Preparation | [Preparation workflow](docs/harness/workflow-guide.md#stage-two-preparation) | Fully groomed plan and materialized baseline accepted by `gate preparation` |
| Implementation | [Implementation workflow](docs/harness/workflow-guide.md#stage-three-implementation) | Verified application evidence, one sealed PR per phase and project validation |

**Frozen artifacts** are approved files whose exact identities are recorded by the controller. Downstream work must preserve that authority; changing a contract or acceptance meaning requires a new specification run. Generated Rust messages and local unary service traits enforce interface shapes, while application checks must also prove that real providers and consumers use those boundaries. The seed contract in this boilerplate qualifies the generator; it is not the Todo domain model or a requirement to add a network server.

A **vertical** is an ordered chain of dependent tasks toward a capability. A **phase** is a dependency-closed group of tasks: its accepted obligations may depend on earlier phases, but never on unfinished future work. An **acceptance gate** checks whether the current source, results, and review permit phase closure or project completion. See the [workflow guide](docs/harness/workflow-guide.md) for the detailed transitions.

## What the harness controls

Agents interpret requirements, research dependencies, author specifications and code, and review whether the result fulfills the intended behavior. The deterministic Python controller validates artifact structure, traceability, dependency order, task ownership, source identity, evidence, and state transitions. Structural validation supports semantic review; it cannot establish correctness by itself.

The [runtime roster](docs/harness/codex-runtime.md#runtime-contract) defines specialist ownership and model settings. The [workflow guide](docs/harness/workflow-guide.md#authority-and-state) defines bounded claims, continuous independent review and handoff rules. Use the controller for state transitions; do not edit SQLite state, locks, receipts or unfinished task markers to force progress.

Implementation follows **tests → deletion → modification → addition → documentation**. Its [execution procedure](docs/harness/workflow-guide.md#stage-three-implementation) defines behavioral RED, permitted scaffolding, leased worktrees, integration and phase gates. [Reuse analysis](.agents/skills/reuse-analysis/SKILL.md) is required before additions.

## Prerequisites

The controller uses the Python standard library; no Python package installation is needed. Python and Git are enough for initialization and offline harness tests. The full workflows also need the tools and access below.

| Prerequisite | Purpose |
| --- | --- |
| Python 3.11+ and Git | Controller, regression suite, exact source identities, branches, and isolated worktrees |
| Codex CLI with native Goals and custom subagents | Interactive workflows and configured agent roles |
| Model/account access | The Astra/ultra, Sol/xhigh, and Luna/xhigh settings listed above; no silent model downgrade |
| GitHub CLI `gh` and a writable GitHub `origin` remote | Phase PR publication, required checks, and stack verification |
| Rustup with the [pinned Rust toolchain](rust-toolchain.toml) | Rust compiler, `rustfmt`, `clippy`, and `wasm32-unknown-unknown` for native and Rust/WASM work |
| Buf CLI | Protobuf linting, descriptors, and contract verification |
| Native Tauri development tools for each required OS | Actual desktop build, integration, and packaging qualification |

Authenticate Codex and GitHub locally before starting development, and configure your own Git author identity. `doctor --full` inspects tool availability, client capabilities, and authentication. Advertised model support **does not prove account entitlement**: the doctor always reports `account_access_verified=false` because it performs no paid model invocation. Actual access is established when the model is used. Missing tools or model access are blockers, not permission to substitute a different configuration.

The [runtime guide](docs/harness/codex-runtime.md) links installation references and explains the pinned CI tools. Specification selects and qualifies the application dependency versions, Rust UI framework, build tools, and platform testing route. Protoc is optional for the shipped generator because Buf emits descriptors that Prost can consume directly. Reference-device benchmarks and manual accessibility checks still require the actual specified environments; ordinary hosted CI does not replace them.

## Get started

### Initialize and inspect without starting development

Clone your repository or fork using its actual URL, then initialize local state:

```sh
git clone YOUR_GITHUB_REPOSITORY_URL rdd-harness
cd rdd-harness
git switch -c codex/todo-baseline origin/main
./rdd init
./rdd status
./rdd --help
./rdd doctor --full
```

Run `init` before `status` on a fresh clone: Git does not carry the ignored local run locator. These commands initialize or inspect the harness; **they do not start an RDD development run**.

On a fresh checkout, `init` reports `initialized`; `status` reports `not_started` until a run is created.

On Windows, replace `./rdd` with `python tools/rdd/cli.py`, `rdd.cmd` in Command Prompt, or `./rdd.ps1` in PowerShell, keeping the same arguments. On Unix, `python3 tools/rdd/cli.py` also works if a file extractor did not preserve executable permissions.


If starting from an archive rather than a clone, extract it into its own directory, initialize Git on a named authoring branch with `git init -b codex/todo-baseline`, and run `./rdd init` there. After configuring your Git identity, make the initial source commit and connect a writable `origin` remote if one does not already exist. Clones already have history and a remote; they do not need an extra initialization commit.

For safe launch-prompt inspection, follow [workflow permissions](docs/harness/codex-runtime.md#workflow-permissions); omit `--mode` to avoid starting a run.

### Start development deliberately

Use a clean dedicated baseline such as `codex/todo-baseline`; `main` is merge-only. Complete and commit each workflow before starting the next. Follow the [workflow guide](docs/harness/workflow-guide.md#stage-one-specification) for the stage commands, and [preparation acceptance](docs/harness/workflow-guide.md#stage-two-preparation) for the required push, explicit CI dispatch, independent reviews and gate. Baseline pushes alone do not run CI.

Launch sessions with `./rdd workflow specification --mode regenerate`, then `./rdd workflow preparation`, then `./rdd workflow implementation` as their prerequisites are accepted. Each launch accepts `--permission full-access`; [workflow permissions](docs/harness/codex-runtime.md#workflow-permissions) defines its per-session effect. For implementation, submit `/goal` with the objective printed by `./rdd goal`; launching the session does not activate native Goal mode.

## Follow progress and recover

Use `./rdd status` for runtime truth. Before moving or discarding a checkout, export its state with `./rdd export-run .rdd/evidence/run-checkpoint.json`; Git does not carry ignored runtime evidence. Preserve the exact source revision and worker branches separately.

Return to the recorded baseline or phase branch and use `./rdd resume`, or `./rdd resume --from PATH_TO_RUN_CHECKPOINT.json` to restore an export. Follow [repairs and interruptions](docs/harness/workflow-guide.md#repairs-and-interruptions) for leases, integration conflicts, blockers and historical-run restrictions, and the [evidence guide](docs/harness/evidence-guide.md) for checkpoint contents. Recovery never rewrites recorded authority to match a different checkout.

For requirements changes or sealed defects, follow [amendment and regeneration](docs/harness/workflow-guide.md#amendment-and-regeneration). Repairs within an open phase use its existing scoped tasks.

## What counts as complete?

### Phase readiness and project acceptance

The [phase acceptance procedure](docs/harness/workflow-guide.md#stage-three-implementation) defines closure evidence. The [stacked PR policy](docs/harness/codex-runtime.md#stacked-pr-policy) defines verified open PRs, base identities and review rules. Keep the accepted stack intact until project acceptance.

Only `./rdd gate project` returning **`status: passed` and `application_complete: true`** establishes application completion. It requires all canonical tasks done, no remaining task markers, every phase sealed, the stack currently verified, and all required cumulative/project tests, benchmarks, and platform/observer evidence. It writes:

- `.rdd/evidence/project-validation.json`: source identities, requirement coverage, checks, metrics, reviews, and PRs.
- `.rdd/evidence/project-validation.md`: readable acceptance report.
- `.rdd/evidence/completed-run.json`: portable checkpoint with run state and raw check logs.

A paused Goal, a worker's prose, or passing harness tests cannot establish project acceptance. PR merging and release publishing are separate developer actions after validation.

### Release into main

After project acceptance, archive the reports/checkpoint and keep the phase stack intact. Create one `codex/rdd-release/<run-id>` branch at the accepted application commit and open a PR into `main`. The operator sets `RDD_RELEASE_POLICY_SHA` to the first phase's recorded prepared-base commit and `RDD_RELEASE_SOURCE_SHA` to the project-accepted head through repository Actions variables. Release CI requires both exact pins, uses the verifier from `main` with the separately pinned prepared policy, and rejects incomplete or changed source. Only merge after successful checks and normal review. No specification/preparation-only PR is needed on `main`. The [runtime guide](docs/harness/codex-runtime.md#ci-and-reference-platform-evidence) defines release verification.

### What CI proves

Ordinary unfrozen harness-maintenance PRs run the [focused refinement suite](docs/harness/codex-runtime.md#harness-verification). Frozen phase and release PRs use trusted policy; preparation uses explicit dispatch. The required `verify` job requires every selected job to succeed. See [CI and reference-platform evidence](docs/harness/codex-runtime.md#ci-and-reference-platform-evidence) for route selection, policy pins and platform obligations.

Harness tests and stateless CI do not establish application acceptance; `application_complete` remains false. The [security model](docs/harness/security-model.md) explains the controller's local trust boundary.

## Important files and guides

Use the [repository responsibility map](docs/harness/artifact-guide.md#repository-responsibility-map) for artifact locations and ownership. [AGENTS.md](AGENTS.md) defines repository authority, [.rdd/config.json](.rdd/config.json) configures the controller, and [tools/proto-codegen/](tools/proto-codegen/) contains the Rust contract generator.

For deeper work, use the existing guides:

- [Workflow guide](docs/harness/workflow-guide.md): stage procedures, task integration, review, repair, and recovery.
- [Manual blog demo](docs/harness/blog-demo.md): complete generation, progress, verification, release PR and packaged-app walkthrough.
- [Artifact guide](docs/harness/artifact-guide.md): manifests, schemas, frozen identities, and authoring boundaries.
- [Evidence guide](docs/harness/evidence-guide.md): real check receipts, native/manual imports, metrics, and provenance.
- [Codex runtime guide](docs/harness/codex-runtime.md): client setup, Goals, adapters, PR policy, and CI.
- [Security model](docs/harness/security-model.md): trusted components and limits of verification.
- [Skill guide](.agents/skills/README.md): the three primary workflows and supporting skills.

Adjust protected harness policy, tools, models, or skills through deliberate review before specification freeze. During implementation, those frozen rules remain part of the acceptance authority.
