# The three RDD workflows

Follow these journeys in order to turn `requirements/requirements.md` into an accepted application. Complete [README setup](../../README.md#get-started) once. The [runtime guide](codex-runtime.md) owns native sessions and CI, the [artifact guide](artifact-guide.md) owns schemas/projections, and the [evidence guide](evidence-guide.md) owns receipts, RED, and review.

## Authority and state

Follow [AGENTS.md](../../AGENTS.md): requirements govern specifications/contracts, frozen specifications govern the plan, and the frozen plan governs implementation. A freeze records exact approved file identities. Comments project tasks. Use `./rdd status --brief` for progress and `./rdd status` or `workflow nodes` for detailed claims/history. Both status views retain exit 2 when blocked; parse their JSON without treating that exit as a failed observation. `./rdd --help` describes commands. Never edit state, locks, receipts, or unfinished markers to force progress.

Specification and preparation require independent semantic and execution reviews of the same candidate; implementation has continuous review and phase acceptance. The [workflow skills](../../.agents/skills/README.md) own agent responsibilities.

## Stage one: specification

**Purpose and prerequisites:** Resolve the product's behavior, domain ownership, contracts, verification oracles, and execution design before implementation. Start from the clean baseline established in README setup, with authorized requirements and available qualification environments.

```sh
./rdd workflow specification --mode regenerate
```

This launcher starts the run; the agent consumes that run rather than starting another. It refuses `main`, detached HEAD, or the wrong branch without changing your files. Optional [workflow permissions](codex-runtime.md#workflow-permissions) apply per session.

**Your involvement:** Answer consequential product and feasibility questions through [specification refinement](../../.agents/skills/rdd-spec-grill/SKILL.md); inspect the decisions and remaining blockers. An authorized draft input does not require an extra approval round solely for its label.

**Accepted outcome and recovery:** `specified` with committed frozen outputs and current independent approval. Missing semantics, incompatible contracts, or unavailable required evidence leaves the stage incomplete. Use [recovery](#repairs-and-interruptions) to continue the existing session; repeating `--mode regenerate` after freeze can create a fresh run.

<details>
<summary>Agent procedure</summary>

Agents use `workflow nodes` and `workflow next`, claim bounded writes with `workflow claim`, and submit hashed handoffs with `workflow record`. Acceptance nodes derive from freezes, gates, and seals. Use the [canonical specialist roster](codex-runtime.md#runtime-contract); keep a read-only reviewer alongside at most two authors and return upstream corrections to their owners.

[Live review](../../.agents/skills/phase-review/SKILL.md) compares specification with requirements, preparation with frozen specs/contracts, and implementation with the frozen plan/contracts. Observe coherent handoffs, integrations, and significant checks; retain revision-bound findings and independently verified resolutions. Specification and preparation require distinct semantic and execution sessions approving the same candidate with zero unresolved findings. Report filenames below are examples of actual reports, never supplied approvals.

For specification/preparation corrections: **claim with finding → edit → independent resolution → record → reviewer observes handoff**. Corrective claims permit only their declared writes; rejected records retain claims/outputs for retry. A claim does not resolve its finding.

Follow [specification-workflow](../../.agents/skills/specification-workflow/SKILL.md). Initialize only missing requirement-index/draft artifacts. S1 owns the structured inventory; S2–S4 verification design; S5 qualification; S6 the reconciled architecture, complete target tree, and exact contracts. [domain-boundaries](../../.agents/skills/domain-boundaries/SKILL.md) and [protobuf-contracts](../../.agents/skills/protobuf-contracts/SKILL.md) define ownership and qualification. Disposable providers/consumers qualify interfaces; they do not prove application behavior.

Record material direction with `spec refine`, resolve accepted choices' originating questions before affected claims/handoffs, and publish through artifact owners using the [snapshot procedure](artifact-guide.md#refinement-records). Freeze scenario/check meaning and qualify tooling/CI policy before downstream tasks are planned.

Commit the complete candidate. Claim S7, run `./rdd spec validate` and `./rdd readiness specification`, then record S7 with its actual hashed outputs and readiness evidence. Only after that handoff obtain both final perspectives and complete S8:

```sh
./rdd review record .rdd/runtime/spec-semantic-review.json
./rdd review record .rdd/runtime/spec-execution-review.json
./rdd spec freeze
```

After corrections, rerun affected checks and obtain both perspectives approving the same current candidate. Commit frozen outputs before preparation. Missing proof or exhausted budgets leaves the workflow incomplete.

</details>

## Stage two: preparation

**Purpose and prerequisites:** Turn the committed frozen solution/contracts into a fully groomed, executable backlog. Retain the recorded baseline branch and frozen authority.

```sh
./rdd workflow preparation
```

**Your involvement:** Supply required platform/account access and inspect blockers and the proposed phase outcomes. The agent must qualify actual runners, hosts, and evidence transfer rather than infer them from schemas.

**Accepted outcome and recovery:** `prepared` after materialization, commit/push, explicitly dispatched CI, imported evidence, readiness, both final reviews, and `gate preparation`. `preparing` means materialized, not accepted. Use [recovery](#repairs-and-interruptions) for interruption. Correct draft plan errors in place; a frozen design defect follows the [blocker/amendment route](#amendment-and-regeneration).

<details>
<summary>Agent procedure</summary>

Follow [preparation-workflow](../../.agents/skills/preparation-workflow/SKILL.md). Initialize the draft with `plan init` if missing. P0–P4 produce distinct immutable notes; P5 alone assembles the plan. Cover every actionable frozen file, exact write site, producer/input timing, behavior, and acceptance obligation using the [plan fields](artifact-guide.md#plan-manifest). Retained/generated files and directories keep explicit dispositions. Module-local checks need coverage independently of real provider/consumer proofs.

[plan-verticals](../../.agents/skills/plan-verticals/SKILL.md) establishes producer closure; [plan-phases](../../.agents/skills/plan-phases/SKILL.md) enforces dependency-closed phases and category order. Commit the complete plan, qualify it, and obtain both perspectives:

```sh
./rdd plan validate
./rdd readiness plan
./rdd review record .rdd/runtime/plan-semantic-review.json
./rdd review record .rdd/runtime/plan-execution-review.json
./rdd plan freeze
./rdd prepare
./rdd anchors verify
```

Inspect all actual packets, shells, sidecars, and the derived matrix under the [marker rules](artifact-guide.md#comments-shells-and-generated-files). No product implementation belongs in materialization. Commit and push that exact baseline, explicitly dispatch preparation CI, and import actual hosted/native receipts and raw logs using [CI policy](codex-runtime.md#ci-and-reference-platform-evidence). Baseline pushes alone do not run CI. Then run:

```sh
./rdd readiness preparation
./rdd review record .rdd/runtime/preparation-semantic-review.json
./rdd review record .rdd/runtime/preparation-execution-review.json
./rdd gate preparation
```

Both final reviewers inspect the committed materialization and actual evidence. Only a passing gate grants `prepared`.

</details>

## Stage three: implementation

**Purpose and prerequisites:** Implement the accepted plan without changing frozen contracts or acceptance meaning. Begin P01 at the accepted preparation commit; each later phase starts at the preceding sealed head.

```sh
./rdd workflow implementation
```

**Your involvement:** Submit `/goal ` followed by the objective printed by `./rdd goal` in the native session. Launching or sending an ordinary message does not activate Goal mode. Provide required manual/reference-host observations and resolve concrete access or product blockers.

**Accepted outcome and recovery:** Each phase has current checks/review and one verified sealed PR; the whole application requires [project completion](#project-completion). A launcher exit, exit code zero, or stopped Goal is not acceptance. For interruption preserve the session UUID and use [recovery](#repairs-and-interruptions).

<details>
<summary>Agent procedure</summary>

Follow [implementation-workflow](../../.agents/skills/implementation-workflow/SKILL.md) in the client's [native Goal](codex-runtime.md#native-goal-execution). Repeat this loop for each controller-selected phase, using actual IDs/sessions rather than these examples:

```sh
./rdd phase begin P01
./rdd next
./rdd task claim T001 --worker rdd_complex_implementor --session-id SESSION_ID --worktree
./rdd task integrate T001 --commit COMMIT_SHA
./rdd check CHECK_ID --expect fail --task T001
./rdd task complete T001 --evidence EVIDENCE_ID
```

Workers retain disjoint leases and all packets; integrate sequentially. Run **tests → deletion → modification → addition → documentation** in order. Test tasks need [behavioral RED](evidence-guide.md#behavioral-red), preserving independent oracles; permitted bootstrap scaffolding contains no product behavior. Missing tools, compilation failures, and skipped tests are not RED. Production tasks use `check --expect pass`. Commit controller-generated all-site cleanup before another claim/integration; reconcile interrupted cleanup without removing unfinished packets. No empty commit is needed when cleanup makes no diff.

At phase completion commit the candidate, run cumulative checks and required native/manual/reference evidence, then obtain exact-source independent review:

```sh
./rdd review record .rdd/runtime/phase-review.json
./rdd gate phase P01
./rdd stack publish P01
./rdd stack verify
./rdd phase seal P01
```

All project checks must be allocated to phases and run by the final cumulative gate. Later PRs target their sealed predecessor. Source changes invalidate affected evidence; preserve accepted heads/bases and never force-push or restack closed phases.

</details>

## Project completion

After all phases, run `./rdd gate project`. Acceptance requires `status=passed` and `application_complete=true`: complete frozen inputs, all canonical tasks evidenced, no outstanding primary/secondary packets or sidecars, every golden scenario explicitly executed and passing, required cumulative/platform/benchmark evidence, zero unresolved findings, sealed phases, and a currently verified PR stack. Aggregate GREEN cannot cover omitted, filtered, or skipped golden tests; historical seal reviews cannot clear later findings.

The gate writes `.rdd/evidence/project-validation.json`, `.rdd/evidence/project-validation.md`, and `.rdd/evidence/completed-run.json`. Archive these reports/checkpoint and follow the generated application's packaging instructions. Harness selftests cannot establish application acceptance.

## Repairs and interruptions

Record the native session UUID. [Native resume](codex-runtime.md#native-goal-execution) reopens that exact session; inspect its existing Goal before `/goal resume`. Repeating a workflow command opens another session. `./rdd resume` separately reconciles controller state; `resume --from CHECKPOINT` restores an export. Recover on the recorded baseline/phase branch, inspect dirty files before switching, and never reset or relocate accepted identities.

Before launching work that writes claimed artifacts, inspect the actual lease expiry and bound owned subprocesses to its remaining time. Recheck after approval waits, asynchronous waits and resume; stop and await owned writers before expiry or release. If expiry occurred, preserve late outputs and the incident, stop writes and use the applicable recovery path below. Reclaiming never retroactively authorizes late writes. Handoff rejection does not terminate arbitrary external processes.

For a worker interruption, preserve the worktree. Use `./rdd task release T002 --reason TEXT` only while the task is claimed and unintegrated; integrated work must complete or be repaired in place, without undoing its commits. Then inspect `resume` and `status`. Use `export-run` before moving a checkout; [retention guidance](evidence-guide.md#artifacts-and-retention) distinguishes exported state from separately preserved source/worktrees.

Within an open phase, `./rdd task reopen T002 --reason TEXT` corrects existing scope, including related tests, while preserving category/dependency order and write ownership. Recorded task-scoped finding IDs authorize intermediate corrections/completion; new findings need renewed enrollment and independent resolution remains required before acceptance. Global findings remain blockers. Reopening preflights packet restoration; commit reconciled packets before continuing. `anchors reconcile` repairs interrupted cleanup and consumed selectors without changing frozen ownership.

For storage errors preserve the database, WAL/journals, evidence, checkpoints, source, and worktrees. Stop uncertain writes; do not delete journals or assume integrity proves every update survived. Record blockers with `./rdd block --kind KIND --reason TEXT`. Specification/planning escapes require origin/detection stage, affected IDs, candidate identities, and evidence immediately; stop affected execution and require a preventive-control repair with a reproducing regression. Distinguish outages/permissions from defective execution design. Missing evidence is never an automatic skip.

For each blocker retain expected versus observed behavior, affected requirement/scenario/phase, exact source identity, reproduction and raw evidence. State why the next action is blocked, the smallest resolution and verifiable resume conditions; continue independent safe work. Use the supported kind from `./rdd block --help`; these notes support controller state rather than replace it.

Specification/preparation node release records the current claimed output hashes, including absence, without accepting the node. A reclaimed deletion needs uninterrupted owned, release-observed provenance back to a committed artifact or accepted deletion. Older releases lacking that observation remain historical evidence, not retroactive authorization; preserve blocked runs and use a new policy baseline for this repair. Normal leases, attempts, reviews and handoff validation still apply.

## Release after project acceptance

Keep accepted branches and PR bases intact. Create `codex/rdd-release/RUN_ID` at the project-accepted commit for a separate release PR into `main`, with the operator's exact policy/source pins required by [release CI](codex-runtime.md#ci-and-reference-platform-evidence). Merge/release requires separate authority. After merging, verify ancestry, identical tracked contents, and clean status; preserve accepted-phase and main-merge identities separately.

## Amendment and regeneration

Use [amend-requirements](../../.agents/skills/amend-requirements/SKILL.md) and `start --mode amend` for changed requirements or invalid accepted design/implementation claims. A frozen defect is a critical harness regression, including a sealed defect's closure failure; preserve its accepted obligations/history and follow the blocker procedure above. Compute downstream impact and retain valid artifacts. `regenerate` creates a fresh solution; application replacement remains explicit planned work. Neither mode permits deleting user data or rewriting sealed evidence.

## Workflow quality and research basis

Use the [artifact/schema guidance](artifact-guide.md) for current formats. Runs bind graph, refinement, and profile policy. Changed policy requires the recorded harness for continuation or a fresh reviewed baseline; never migrate approvals, alias historical roles, or backfill pins. Old artifacts remain inspect/export inputs. Start a fresh Codex session after profile changes. [Runtime](../../.rdd/sources/runtime.json) and [engineering](../../.rdd/sources/engineering.json) records retain research provenance.
