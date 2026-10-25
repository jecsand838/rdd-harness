# The three RDD workflows

The harness turns `requirements/requirements.md` into a frozen solution, a prepared plan, and accepted implementation evidence. The Todo application is not supplied by the boilerplate. Use the [README](../../README.md) for installation, [runtime guide](codex-runtime.md) for native agents and CI, [artifact guide](artifact-guide.md) for schemas/projections, and [evidence guide](evidence-guide.md) for receipts, RED and review.

## Authority and state

Follow [AGENTS.md](../../AGENTS.md). Requirements govern the solution/contracts, which govern the plan, which governs implementation. Comments project tasks; they do not own task state. `./rdd status` reports runtime truth; `./rdd --help` describes commands. On Windows use `python tools/rdd/cli.py` with the same arguments. Initialize a fresh checkout before reading status.

`./rdd workflow nodes` exposes the fixed S0–S8, P0–P8 and I0–I5 graph; `workflow next` selects eligible authoring nodes. Claim bounded writes with `workflow claim` and submit hashed outputs through `workflow record`. Acceptance nodes derive from existing freezes, gates and seals. Use the [canonical roster](codex-runtime.md#runtime-contract): S1 domain analyst, S2–S4 verification designer, S5 qualification engineer, S6 architect, P1–P5 planner; the coordinator cannot substitute for a specialist. Keep one independent reviewer alongside at most two authors.

Read [phase-review](../../.agents/skills/phase-review/SKILL.md) for live observation and final perspectives. Specification review compares with requirements; preparation with frozen specs/contracts; implementation with the frozen plan/contracts. Send coherent handoffs, integrations and significant check results. Findings retain exact revisions and independent resolution. Stage acceptance requires distinct semantic and execution sessions approving the same candidate with zero unresolved findings.

For specification/preparation corrections use **claim with finding → edit → reviewer resolves applicable findings → record → reviewer observes handoff**. An explicit corrective claim may address a global finding within its declared writes; it does not resolve the finding or authorize unrelated work. Rejected records retain their claims and outputs for retry. P0–P4 produce distinct immutable notes; P5 alone assembles `.rdd/plan/plan.json`. Return upstream corrections to their owners instead of modifying completed handoffs through a successor.

## Stage one: specification

Start once on a clean dedicated baseline; `main` is merge-only. Preserve the branch recorded by `start` throughout specification and preparation:

```sh
git fetch origin
git switch -c codex/todo-baseline origin/main
./rdd init
./rdd doctor
./rdd start --mode regenerate
./rdd requirements index
./rdd spec init
```

Use [specification-workflow](../../.agents/skills/specification-workflow/SKILL.md), or launch `./rdd workflow specification` for its stage prompt. [Workflow permissions](codex-runtime.md#workflow-permissions) describes the optional per-session permission setting. The controller refuses authoring on `main`, detached HEAD or the wrong branch without switching or discarding files.

Specification owns the complete target tree, domain inventory, scenarios, oracles, NFR protocols and executable qualification design. [domain-boundaries](../../.agents/skills/domain-boundaries/SKILL.md) owns S1/S6 reconciliation; [protobuf-contracts](../../.agents/skills/protobuf-contracts/SKILL.md) owns generation and qualification. Qualify protected tooling/CI policy before freeze. Application test code is planned later; its scenario/check meaning is frozen now. Qualification may use disposable providers and consumers, but does not claim application behavior.

Load [rdd-spec-grill](../../.agents/skills/rdd-spec-grill/SKILL.md) for consequential choices. Record material direction with `spec refine`; resolve an accepted choice's originating question before claiming or recording affected work. Genuinely unanswered questions may still require investigation. Publish decisions through their artifact owners and follow the [snapshot procedure](artifact-guide.md#refinement-records). Commit the complete candidate before readiness/review:

```sh
./rdd spec validate
./rdd readiness specification
./rdd review record .rdd/runtime/spec-semantic-review.json
./rdd review record .rdd/runtime/spec-execution-review.json
./rdd spec freeze
```

These filenames designate actual reports, not supplied approvals. Commit the frozen outputs before preparation. Missing platform evidence, unresolved semantics and incompatible contracts remain blockers; a draft label alone does not create another approval gate after the user has authorized the input.

## Stage two: preparation

Use [preparation-workflow](../../.agents/skills/preparation-workflow/SKILL.md). `./rdd plan init` creates a draft; P0–P4 record research, reuse, dependency and phase decisions in separate notes, and P5 writes the fully groomed plan. Every actionable frozen file needs task ownership. Retained/generated files and directories have their own dispositions. Module-local checks need task/phase coverage independently of real consumer/provider interaction proofs.

Use [plan-verticals](../../.agents/skills/plan-verticals/SKILL.md) and [plan-phases](../../.agents/skills/plan-phases/SKILL.md) for producer closure and strict category ordering. Complete every task packet, exact write site, baseline/producer input and acceptance obligation before freeze. The [artifact guide](artifact-guide.md#plan-manifest) defines the fields; the [evidence guide](evidence-guide.md#workflow-readiness-and-independent-review) defines readiness and final reviews. A prefreeze planning validation error leaves the draft correctable; frozen design defects require the blocker path.

Commit the plan, qualify the candidate and record both perspectives:

```sh
./rdd plan validate
./rdd readiness plan
./rdd review record .rdd/runtime/plan-semantic-review.json
./rdd review record .rdd/runtime/plan-execution-review.json
./rdd plan freeze
./rdd prepare
./rdd anchors verify
```

`prepare` enters `preparing`. Inspect the actual packets, shells and derived matrix, commit and push the exact baseline, then explicitly dispatch preparation CI; baseline pushes do not run CI:

```sh
gh workflow run preparation.yml --ref BASELINE_BRANCH -f candidate=FULL_SHA
./rdd readiness preparation
./rdd review record .rdd/runtime/preparation-semantic-review.json
./rdd review record .rdd/runtime/preparation-execution-review.json
./rdd gate preparation
```

The dispatch requires the recorded `codex/*-baseline` branch at that full SHA and the independently selected `RDD_PREPARATION_HARNESS_SHA`; import actual hosted/native prerequisite evidence before the final reviews. See [CI policy](codex-runtime.md#ci-and-reference-platform-evidence) and [branch rules](codex-runtime.md#stacked-pr-policy). Only a passing gate grants `prepared`. Materialization follows the [canonical marker rules](artifact-guide.md#comments-shells-and-generated-files), with safe sidecars for noncommentable/deleted targets and no product implementation.

## Stage three: implementation

Use [implementation-workflow](../../.agents/skills/implementation-workflow/SKILL.md). Retrieve `./rdd goal` and activate the client's [native Goal](codex-runtime.md#native-goal-execution). The controller remains the completion authority. Begin P01 at the accepted preparation commit; later phases begin at the preceding sealed head.

```sh
./rdd phase begin P01
./rdd next
./rdd task claim T001 --worker rdd_complex_implementor --session-id SESSION_ID --worktree
./rdd task integrate T001 --commit COMMIT_SHA
./rdd check CHECK_ID --expect fail --task T001
./rdd task complete T001 --evidence EVIDENCE_ID
```

IDs above illustrate syntax; use actual ready tasks and runtime sessions. Preserve disjoint leases and integrate sequentially. A worker's complete marker inventory is checked against its trusted leased baseline; the integrated checkout is checked against current state. Unrelated marker changes remain invalid.

All **tests → deletion → modification → addition → documentation** tasks run in order. [Behavioral RED](evidence-guide.md#behavioral-red) defines real assertions and permitted nonbehavioral bootstrap scaffolding. Missing tools or compiler failures never establish RED. Production tasks use `check --expect pass` and controller completion. Commit all-site marker cleanup before subsequent claims/integrations; if cleanup makes no diff, no empty commit is needed.

At phase completion, commit the candidate, run cumulative checks, obtain current independent review and execute:

```sh
./rdd review record .rdd/runtime/phase-review.json
./rdd gate phase P01
./rdd stack publish P01
./rdd stack verify
./rdd phase seal P01
```

All project check IDs must be allocated to phase checks, so the final cumulative gate runs them before sealing. Publication maintains one PR per phase; later PRs target their sealed predecessor. Source changes invalidate affected evidence. Preserve accepted bases/heads; never force-push or restack closed phases.

### Repairs and interruptions

`./rdd task reopen T002 --reason TEXT` permits a correction within the open phase's existing scope. Reopen related test tasks when needed. The repair sweep preserves category/dependency order, leases and write ownership. Existing task-scoped finding IDs authorize intermediate correction work and completion; independent resolution is still required before acceptance. A new finding requires renewed enrollment. Global implementation findings remain blockers.

Reopening preflights packet restoration before recording the transition. If an authorized edit consumed an inline selector, the controller uses its repair placement rule without changing frozen work ownership. Commit reconciled packets before continuing. `task complete` records completion before cleanup; `anchors reconcile` repairs interrupted cleanup. Never remove unfinished packets manually.

For worker interruption, preserve its worktree, use `task release T002 --reason TEXT`, then `./rdd resume` and `./rdd status`. Recover from the recorded baseline/phase branch; inspect dirty files before switching. Do not reset or relocate recorded identities. Use `export-run` before moving a checkout; [evidence retention](evidence-guide.md#artifacts-and-retention) distinguishes exported state from separately preserved source/worktrees.

Storage errors exit with an environment diagnostic. Preserve the database, WAL/journals, evidence, checkpoint and worktrees; do not retry uncertain writes or delete journals. SQLite operations close their own connections, reads inspect disposable DB/WAL snapshots under the process guard, and an unconfirmed close prevents further storage access in that process. Database integrity alone does not prove every update survived.

Record blockers through `./rdd block --kind KIND --reason TEXT`. Specification/planning escapes need origin/detection stage, affected IDs, candidate identities and evidence immediately; a reproducing regression is required to accept the preventive-control repair. Distinguish external outages/permissions from defective execution design. Sealed defects preserve closure history and require amendment; missing evidence is never an automatic skip.

After all phases, `./rdd gate project` requires the complete frozen baseline, task/marker reconciliation, explicit passing golden results, required cumulative/platform/benchmark evidence, current unresolved-finding check, sealed phases and verified PR stack. It writes the reports/checkpoint defined in the README. Historical seal reviews remain historical; a new finding cannot be hidden behind their old cursors.

## Release after project acceptance

Keep accepted branches and PR bases intact. Create `codex/rdd-release/RUN_ID` at the project-accepted commit for a separate release PR into `main`. The operator pins `RDD_RELEASE_POLICY_SHA` and `RDD_RELEASE_SOURCE_SHA`; [release CI](codex-runtime.md#ci-and-reference-platform-evidence) validates exact policy/source independently. Merge/release requires separate authority. After merging, verify ancestry, identical tracked contents and clean status; preserve accepted-phase and main-merge identities separately.

## Amendment and regeneration

Use [amend-requirements](../../.agents/skills/amend-requirements/SKILL.md) and `start --mode amend` for changed requirements or invalid accepted design/implementation claims. Preserve valid artifacts and compute downstream impact. `regenerate` creates a fresh solution, with application replacement still explicit planned work. Neither mode permits deleting user data or rewriting sealed evidence.

## Workflow quality and research basis

Specification/plan authoring uses schema v3; runtime/checkpoints use v2, and refinement uses v1. Runs bind graph, refinement and profile policy. Changed policies require the recorded harness for continuation or a fresh reviewed baseline; never migrate approvals, alias historical roles or backfill pins. Old specifications/plans remain inspect/export inputs. Start a fresh Codex session after profile changes. [Runtime source records](../../.rdd/sources/runtime.json) and [engineering sources](../../.rdd/sources/engineering.json) retain research provenance; harness tests do not establish Todo acceptance.
