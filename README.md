# RDD harness

A repository-local **Requirements Driven Development (RDD)** harness for Codex. It connects formal requirements to a frozen solution, an implementation plan, and a verified stack of phase pull requests.

The repository supplies [Rust Todo requirements](requirements/requirements.md), the controller, agent skills, contracts tooling, and verification infrastructure. **The Todo application has not been implemented.**

## What is RDD?

RDD makes functional behavior and quality constraints explicit before implementation, then keeps their evidence connected: **requirement ↔ subdomain/behavior ↔ scenario/check ↔ task/work sites ↔ phase evidence and PR ↔ project validation**. Checklists and agent success messages cannot replace measured results and independent review.

## How the workflow fits together

![Conceptual RDD flow: requirements become specifications and contracts, preparation organizes tasks into verticals and phases, and implementation repeats tests, tasks, and acceptance until project validation.](docs/harness/rdd-diagram.svg)

[Open the full diagram](docs/harness/rdd-diagram.svg). The controller and frozen artifacts define the operational rules; the three journeys below explain the diagram's outlined labels in text.

| Start here | Accepted output |
| --- | --- |
| [1. Specification](docs/harness/workflow-guide.md#stage-one-specification) | Frozen solution, contracts, scenarios, and qualified execution prerequisites |
| [2. Preparation](docs/harness/workflow-guide.md#stage-two-preparation) | Fully groomed plan and materialized baseline accepted by `gate preparation` |
| [3. Implementation](docs/harness/workflow-guide.md#stage-three-implementation) | Sealed phase PRs and application evidence accepted by `gate project` |

## What the harness controls

Agents interpret requirements, author artifacts and code, and review behavior. The deterministic controller validates structure, traceability, ownership, source identities, evidence, and transitions. Structural validation supports semantic review. [AGENTS.md](AGENTS.md) and the [workflow guide](docs/harness/workflow-guide.md#authority-and-state) define authority; use controller commands to change state.

## Prerequisites

Python 3.11+ and Git support initialization and offline harness tests without Python packages. Full workflows also need authenticated Codex with native Goals/custom subagents and access to the [configured models](docs/harness/codex-runtime.md#runtime-contract), GitHub CLI `gh` with a writable `origin`, Rustup with the [pinned toolchain](rust-toolchain.toml), Buf, and the native Tauri tools for each required OS.

Configure your Git author identity and authenticate locally. `doctor --full` checks availability and client capabilities; advertised models do not prove account entitlement. Missing access blocks the required role. The [runtime guide](docs/harness/codex-runtime.md) owns installation references, capability limits, and CI tools. Specification qualifies application dependencies and actual platform, benchmark, and accessibility environments.

## Get started

### Initialize and inspect without starting development

Clone your own repository or fork using its actual URL, then run this setup once:

```sh
git clone YOUR_GITHUB_REPOSITORY_URL rdd-harness
cd rdd-harness
git switch -c codex/todo-baseline origin/main
./rdd init
./rdd status
./rdd --help
./rdd doctor --full
```

Git does not carry the ignored local run locator. On a fresh clone, `init` reports `initialized` and `status` reports `not_started`; setup does not start development. Use a clean dedicated `codex/*-baseline` branch; `main` is merge-only. For an archive, initialize Git on that named branch, commit the source, and connect a writable `origin`, then use the `rdd` commands above.

On Windows, replace `./rdd` with `python tools/rdd/cli.py`, `rdd.cmd`, or `./rdd.ps1` with the same arguments. On Unix, `python3 tools/rdd/cli.py` also works if executable permissions were lost.

### Start development deliberately

Follow the three [workflow journeys](docs/harness/workflow-guide.md#stage-one-specification) in order, accepting and committing each stage before the next. They own launch commands, user decisions, and accepted outcomes. [Workflow permissions](docs/harness/codex-runtime.md#workflow-permissions) explains per-session full access and safe prompt inspection; an explicit `--mode` can start a run even with `--print`.

## Follow progress and recover

Use `./rdd status` for runtime truth. Before moving a checkout, export with `./rdd export-run .rdd/evidence/run-checkpoint.json` and preserve source, branches, and worktrees separately. The [recovery procedure](docs/harness/workflow-guide.md#repairs-and-interruptions) distinguishes native session/Goal recovery from controller `resume`, and covers interrupted tasks, storage failures, and blockers. For changed requirements or sealed defects, use [amendment and regeneration](docs/harness/workflow-guide.md#amendment-and-regeneration).

## What counts as complete?

### Phase readiness and project acceptance

Only `./rdd gate project` returning **`status=passed` and `application_complete=true`** establishes application completion. The [project completion procedure](docs/harness/workflow-guide.md#project-completion) defines required tasks, explicit golden results, cumulative/platform evidence, sealed phases, verified PR stack, and final artifacts. A stopped Goal or passing harness tests cannot establish acceptance.

### Release into main

Preserve the accepted phase stack and archive its reports/checkpoint. [Release after project acceptance](docs/harness/workflow-guide.md#release-after-project-acceptance) uses a separate release PR into `main`; merging and publishing remain separate developer actions.

### What CI proves

[CI and reference-platform evidence](docs/harness/codex-runtime.md#ci-and-reference-platform-evidence) defines maintenance, preparation, phase, and release routes, exact policy pins, and required checks. Hosted CI cannot replace specified native/manual/reference evidence. Harness tests do not establish Todo acceptance; see the [security model](docs/harness/security-model.md) for trust limits.

## Important files and guides

The [artifact guide](docs/harness/artifact-guide.md#repository-responsibility-map) maps files and ownership. Use the [workflow guide](docs/harness/workflow-guide.md) for stage procedures, [evidence guide](docs/harness/evidence-guide.md) for receipts/reviews, [runtime guide](docs/harness/codex-runtime.md) for agents/CI, and [skill guide](.agents/skills/README.md) for specialized procedures. Adjust protected harness policy through review before specification freeze; downstream work preserves its frozen authority.
