# Codex runtime, external adapters, and CI

This guide describes the harness runtime. Current measured client observations
and their primary sources are recorded in `.rdd/sources/runtime.json`; run
`./rdd doctor` to inspect the installed environment.

## Runtime contract

The three workflow commands execute through the repository's Python stdlib App Server runner. Codex produces and reviews artifacts; the deterministic controller owns durable state, task leases, evidence and acceptance. The coordinator is a canonical profile-applied session. Writable specialists use exact registered `agent_type` values, `fork_turns="none"` and bounded packets. Let profiles supply model and effort without overrides; changed profiles require a fresh runtime session.

The canonical roster is:

| Profile | Model / effort | Responsibility |
|---|---|---|
| `rdd_coordinator` | `gpt-6-astra` / `ultra` | Intake, transitions, integration and acceptance execution |
| `rdd_domain_analyst` | `gpt-6.1-sol` / `xhigh` | S1: subdomains, behaviors, invariants and ownership |
| `rdd_verification_designer` | `gpt-6.1-sol` / `xhigh` | S2–S4: constraints, independent oracles, scenarios and benchmarks |
| `rdd_qualification_engineer` | `gpt-6.1-sol` / `xhigh` | S5: disposable dependency, compiler, provisioning, host and transfer experiments |
| `rdd_contract_architect` | `gpt-6-astra` / `ultra` | Early boundary advice; S6 architecture, target tree, contracts and bindings |
| `rdd_task_planner` | `gpt-6.1-sol` / `xhigh` | P1–P5: groomed tasks, producer DAG, verticals, phases and sites |
| `rdd_complex_implementor` | `gpt-6.1-sol` / `xhigh` | Small or large leased implementation tasks |
| `rdd_light_implementor` | `gpt-6-luna` / `xhigh` | Small, unambiguous leased implementation tasks |
| `rdd_researcher` | `gpt-6.1-sol` / `xhigh` | Read-only evidence gathering and advice |
| `rdd_reviewer` | `gpt-6.1-sol` / `xhigh` | Read-only live review and independent final perspectives |

Keep at most two writable authors alongside one continuous reviewer. A distinct final execution reviewer or bounded researcher uses a released author slot. Read-only sessions are separate App Server threads managed by the runner; they do not add author capacity. Use bounded node/task packets and disjoint write ownership.

Canonical `.codex/agents/` TOMLs are the single authority for each role's instructions, model, effort and sandbox. The shared loader validates names, paths, required settings and read-only research/review permissions. `.codex/config.toml` retains native defaults checked against the coordinator and default complex implementor, plus the three-slot limit. Unrelated custom profiles receive no controller claim authority. Procedures stay in the existing skills.

Request exact named `agent_type` values for writable specialists. For every reviewer/researcher use the coordinator-only `rdd_readonly_agent` dynamic tool: `live` retains the continuous reviewer, `execution` supplies a distinct final reviewer, and `research` supplies bounded advice. Canonical profile instructions/model/effort are applied explicitly with read-only isolation. Native children inherit live parent permissions; the observed native reviewer child did not retain read-only policy. Profile-applied sessions are not native `agent_type` or backend-model attestation. The tool is not exposed recursively. Reviewers return source-linked JSON; only the coordinator writes and records it through the existing controller ledger. Read-only sessions cannot write files or execute writing controller commands. Do not treat the CLI's `--profile` option as custom-agent selection. Consult [custom-subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents) and the [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) when changing the installed client.

### Capability checks

`CodexAdapter.doctor()` checks executable/version, required flags, login and every distinct configured model/effort pair, with affected roles in its output. Catalog availability is advertised client support; it does not prove account entitlement. `account_access_verified` remains false until supported actual evidence exists. A model-access error blocks the role; the harness never silently substitutes a model or effort.

`requested_runtime` records the role, profile identity/hash, model, effort and sandbox requested by the controller. Keep these declarations distinct from observed session events, exit status and captured results. The JSONL stream supplies actual thread/turn events, not authenticated backend-model or effort attestation. A submitted `verified: true` or remembered session label cannot establish those observations.

Use qualified Codex CLI **0.161.0 or 0.162.1**. The runner rejects other versions, including prereleases, with an environment error until their protocol is qualified. This is an exact allowlist, not a minimum version. Authenticate and complete normal project trust setup locally. The stdio server inherits the environment, config and credentials unchanged; it supplies no approval-policy or approval-reviewer overrides. Startup has a 60-second deadline, UTF-8 reader/writer threads work without platform-specific pipe selectors, and shutdown has a separate bounded deadline for owned processes/groups. Diagnostics are capped and stderr is separate; `logs_truncated` identifies incomplete raw captures. Missing permission or an unsupported server approval/input request stops recoverably rather than granting itself approval.

## Workflow execution and native Goals

```sh
./rdd workflow specification
./rdd workflow preparation
./rdd workflow implementation
```

Specification uses ordinary turns with typed `questions`, `progress` and `stopped` envelopes. Only necessary specification questions are presented for actual answers. Preparation and implementation activate native Goals through App Server and execute headlessly. Native Goals own continuation; a client turn loop does not substitute for it. The implementation objective in `.rdd/goals/implementation.txt` stays under 4,000 characters; the skill supplies the detailed procedure. `./rdd goal` remains inspection of that objective.

Repeating a command resumes its recorded run and backend sessions. Accepted stages are rechecked and return without a new launch. An uncertain or missing session/Goal acknowledgement stops for diagnosis; recovery never replaces identities or resets accounting. Inherited approval settings remain unchanged on start/resume. Missing external evidence or permissions remains incomplete. `--print` is pure inspection for every stage, including an explicit `--mode`.

An incomplete run still requires its recorded harness revision/profile policy and executable path, SHA-256 and version. Adding another qualified version permits fresh runs; it does not migrate an existing session or its Goal accounting. This update changes the coordinator's version guidance and therefore its profile identity. Resume older runs with their recorded harness revision and runtime rather than applying this update to their frozen baseline.

New sessions explicitly select `historyMode=legacy`. The runner uses the history returned by `thread/start` or `thread/resume`: a new thread cannot reliably serve `thread/read` with `includeTurns=true` before its first user message. On qualified CLI 0.161.0 this can return `-32600` (not materialized) or `-32601` (unsupported `list_turns`). Existing saved paginated sessions are preserved and may resume when the runtime supplies complete history; missing or partial history stops recovery without replacing the session. Local qualification verified same-ID recovery of an interrupted coordinator and empty reviewer, plus full-history reads after completed turns in both modes. This is a measured compatibility boundary, not a guarantee for other runtime versions; see the [App Server history contract](https://learn.chatgpt.com/docs/app-server#start-or-resume-a-thread).

Exit codes are `0` for controller-accepted stage (or successful print), `1` for invalid request/validation, `2` for incomplete/blocked, and `130` for interruption. Preparation still needs actual readiness/CI and both final reviews before `gate preparation`; implementation still needs all phase gates/seals/PRs and `gate project`. The [workflow guide](workflow-guide.md) keeps those procedures, and the [official Goals guide](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex) describes native Goal lifecycle.

### Qualification scope

The retained [Goal and Q&A findings](../../.rdd/evidence/runtime-qualification-20261009/live/FINAL_FINDINGS.json) independently observed typed answers, native automatic continuation, pause/interruption and same-thread accounting recovery. Its recovery included a client kickoff. That probe also found native reviewer child isolation failed under inherited parent permissions; its failure remains preserved.

The separate [read-only resolution findings](../../.rdd/evidence/runtime-qualification-20261009/reviewer-isolation/FINAL_FINDINGS.json) passed actual sandbox write denial, continuous snapshots across reconnect, a distinct final reviewer, and correlated coordinator dynamic-tool callbacks before and after resume. Its experimental registration uses `experimentalApi=true`, as described in the [App Server reference](https://learn.chatgpt.com/docs/app-server). Approval policy remained inherited on-request/user. Researcher inference and the execution/research callback purpose branches were not run. These are local ignored qualification receipts, with concise scope recorded in [runtime sources](../../.rdd/sources/runtime.json).

The subsequent [production transport and recovery probe](../../.rdd/evidence/runtime-qualification-20261009/production-smoke/FINAL_FINDINGS.json) exercised the shipped transport, runtime preflight and canonical coordinator session settings. Resuming the same paused Goal with a status-only activation started native work with zero client continuation turns, followed by another autonomous turn. Real local checks, stable objective/accounting, and bounded paused shutdown passed.

Codex **0.162.1** was separately qualified on macOS arm64 against its generated schema and the production transport/runner: typed specification questions and answers, native specialist delegation, explicit read-only reviewer write denial, correlated reviewer callbacks across reconnect, complete legacy/paginated history, and same-Goal automatic continuation with zero client continuation turns. Pause, interruption and accounting checks passed. An unused legacy thread was not persisted before its first message; recovery correctly returned an environment error without replacing its recorded identity. The matching regression preserves that refusal. Raw probes and failed diagnostic attempts remain local under `.rdd/evidence/runtime-qualification-01621/`; the concise version, executable identity and limits are recorded in [runtime sources](../../.rdd/sources/runtime.json).

These disposable probes qualify individual capabilities on the recorded host; they do not establish native end-to-end acceptance of the three public workflow commands or Todo behavior. Offline runner tests simulate external Codex/GitHub results, while stdio transport tests run deterministic local fake subprocesses. Required native, CI and product evidence remains separate. Requested model settings and catalog availability are not backend attestation.

## Bounded worker adapter

`CodexAdapter.exec()` remains an optional one-turn worker adapter, separate from the coordinator's App Server transport and native Goal execution. It resolves a canonical role, loads its developer instructions and builds an argv list equivalent to:

```text
codex -a never exec --json --color never --model MODEL
  --config model_reasoning_effort="EFFORT"
  --config developer_instructions="ENCODED_PROFILE_INSTRUCTIONS" --sandbox SANDBOX
  --cd REPOSITORY --output-schema SCHEMA --output-last-message ANSWER -
```

The adapter applies the profile’s supported model, effort, sandbox and `developer_instructions` settings; supplying only a model is insufficient. Configuration values are encoded as TOML values, not interpolated shell fragments. The prompt is supplied on stdin. The adapter keeps sandbox enforcement enabled;
an action that needs unavailable permission fails instead of prompting from a
headless subprocess. It never uses a shell to interpolate prompts, file names,
model IDs or PR text.

Every attempt uses a new directory below `.rdd/runtime/`. It contains the prompt,
schema snapshot, streaming `events.jsonl`, `stderr.log`, final `answer.json`, and a
`receipt.json` with requested profile settings, observed session ID and outcome. A deadline terminates the process
group. The result requires a completed event, session identity, no error event,
a zero process exit, and schema-valid output. The controller must still validate
the artifact's meaning, provenance and baseline: valid JSON is not implementation
evidence. See [Codex noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode).

Use a fresh bounded context packet when a target or baseline changes. Keep raw
logs out of version control; they may contain repository contents. Copy only
reviewed, relevant evidence summaries into the run's validation artifacts. On
resume, recover the run and inspect its current source digest before continuing.
A remembered session ID cannot override the repository baseline. Claims and reports remain declarations unless the runtime exposes corresponding evidence; the controller is not a session-authentication service.

### Python adapter interface

The external adapters in `tools/rdd/adapters.py` use only the Python standard library. They accept an injected
`runner(argv, cwd=..., timeout=..., **kwargs)` returning `CommandResult` for offline
testing. `RddAdapterError.code` distinguishes capability, malformed-evidence,
timeout, revision-mismatch and safety failures.

```python
from tools.rdd.adapters import CodexAdapter, GitAdapter, GitHubAdapter
from tools.rdd.common import validate

git = GitAdapter(repo)
branch = git.create_phase_branch(run_id, phase_number, base_branch)
worktree = git.ensure_worktree(worker_path, branch, base_branch)

worker = CodexAdapter(repo)
result = worker.exec(
    prompt, output_schema_path, fresh_runtime_attempt,
    role="rdd_complex_implementor", timeout=1800,
    validator=validate,
)
```

The controller normally wraps these operations with a run transaction and task
lease. Invoke its public commands during a workflow. Worktree reuse is allowed
only for the exact repository and branch with a clean working tree and the
expected base ancestry. Existing user files or dirty worktrees are preserved and
reported for deliberate recovery. No automatic reset, clean, force branch
replacement or force push is implemented.

## Stacked PR policy

The phase branch name is `rdd/RUN_ID/pNN`. Specification and preparation use a
dedicated `codex/*-baseline` branch; `main` is merge-only. Phase 1 targets that
recorded base branch;
each later phase targets its predecessor's branch. The body includes a stable
run/phase marker. `publish_phase_pr()` checks all PR states for this exact head
branch before creation and verifies the resulting head/base afterward. Repeating
publication updates the branch without creating another PR. A previously closed
or merged phase PR blocks publication of a replacement. The controller serializes
publication through its run lock.

PR descriptions are written to a real file and passed to `gh pr create` using
`--body-file`. The adapter never sends messages, requests reviewers, merges, closes
PRs, force-pushes, or restacks sealed phases. A changed or missing remote base
blocks publication. These rules follow the chosen `ready` completion policy: the
deliverable is a validated open stack. After project acceptance, the operator
publishes a separate release branch at the accepted final commit and merges one
release PR into `main`, preserving the stack and its accepted revisions.

`phase_status()` reads both PR metadata and required checks, then rereads the PR
revision to detect movement during collection. It verifies the expected complete
head SHA, recorded base SHA and branch, optionally the phase branch name, open
non-draft state, confirmed mergeability, every configured check, every reported
server-required check, and independent review evidence. Skipped, pending, absent,
unknown, truncated, or unreadable check results cannot produce readiness.

The configured required-check list must be nonempty. The supplied workflow exposes
the aggregate check **`verify`**. Configure GitHub branch rules to require this
check for `main`, the prepared baseline, and each exact sealed phase branch before
it becomes a successor's base. Do not protect active or future phase branches
with a wildcard rule that prevents their publication or repair. See
[protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
If `gh pr checks --required` cannot establish the server-required checks, inspect
the repository rules and CLI response; do not waive the controller check.

The normal solo-developer policy accepts an independent local review artifact
validated by the controller at the exact candidate head. The adapter's normalized
review input is:

```json
{
  "passed": true,
  "head_sha": "the-complete-current-git-object-id",
  "reviewer": "rdd_reviewer",
  "findings": []
}
```

That dictionary is not itself proof of review; the controller verifies the
underlying artifact and reviewer evidence before passing it. GitHub requests for
changes veto a local pass. `require_github_approval=True` additionally requires an
approval attached to the exact head. This supports teams without making a solo
repository owner self-approve a PR. See [`gh pr view`](https://cli.github.com/manual/gh_pr_view)
and [`gh pr checks`](https://cli.github.com/manual/gh_pr_checks).

## CI and reference-platform evidence

`.github/workflows/rdd.yml` tests the Python controller on Linux, macOS and
Windows and runs the frozen check inventory through the CI entry point. It uses
read-only repository permissions, pinned action commits, no application secrets,
and a `pull_request` trigger. There is no `pull_request_target` execution of
candidate code. A PR's head is checked explicitly; GitHub otherwise defaults to a
synthetic merge revision for this trigger, as described in its
[event documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request).

For an ordinary phase PR, the workflow checks out the candidate and its base into
sibling directories. It tests the trusted base controller, then invokes the **base
controller's** CLI with `--root candidate ci --policy-root baseline --branch
BRANCH`. The frozen verifier policy comes from that separate base checkout, so
editing the candidate CLI does not change the validator being executed. The
trusted phase base must already contain the harness and prepared plan. Push runs
on `main` and `codex/*-baseline` use their own revision as policy and provide
diagnostics. Phase branches produce the `verify` check only through the base-bound
PR run, avoiding a same-name
push/dispatch check with weaker provenance. Protect the workflow itself through
repository rules and review; a repository-contained verifier cannot establish
an external trust root for a workflow file it is allowed to replace.

A same-repository `codex/rdd-release/RUN_ID` PR targeting `main` uses a separate
release route. After project acceptance, the operator sets repository variables
`RDD_RELEASE_POLICY_SHA` to the committed prepared baseline and
`RDD_RELEASE_SOURCE_SHA` to the project-gated final commit. The workflow runs the
trusted `main` base controller with a third checkout at the approved policy SHA:

```text
python baseline/tools/rdd/cli.py --root candidate ci
  --policy-root prepared-policy --branch codex/rdd-release/RUN_ID
  --release-policy POLICY_SHA --release-source SOURCE_SHA
```

Both pins are required; the candidate, PR body and branch name cannot select
them. Before executing frozen checks, the verifier requires clean checkouts at
those exact revisions, prepared-baseline ancestry, intact frozen artifacts,
identical protected policy, a complete phase projection and no remaining anchors.
Missing, stale or unrelated pins fail explicitly. The selected prepared policy
also supplies the toolchain inventory. This route supports the first application
release and subsequent releases whose prepared policy differs from `main`.
The support change must be reviewed and installed on `main` before this route is
used; a release cannot bootstrap its own verifier.

The `verify` job succeeds only if all prerequisite jobs succeed. A canceled,
failed, or skipped prerequisite cannot become a green aggregate. Pinning actions
protects the selected dependency revision; it does not replace repository
branch protections or review of changes to the verifier and workflow itself.

Application build prerequisites and platform-specific command inventory must be
qualified and pinned during specification, with task producers/timing resolved during preparation. Before those artifacts
exist, CI validates the boilerplate/controller only. A materialized baseline remains `preparing` until its exact-source readiness/CI evidence and both independent review perspectives pass `gate preparation`. A prepared baseline checks
its contracts and pending task projections without claiming implementation. Phase
CI runs cumulative ordinary checks applicable to its platform. A complete source
revision, including a release or post-merge `main`, also runs every project check
applicable to that platform. A missing native dependency needed by those checks
is an environment blocker.

When the trusted baseline contains a frozen plan, `ci_tools.py` reads its declared
hosted tool resources, rejects conflicting pins and selects Python and Buf explicitly.
It installs the exact `rust-toolchain.toml` version, components and targets, plus
declared supported Cargo frontend tools (`cargo-tauri`, `trunk`, `wasm-bindgen`,
`wasm-pack`). Other tools require a qualified installed executable;
manifest text cannot supply arbitrary installer commands. Every installed version
is measured before checks run. The initial Rust pin is **1.99.0**, released on 2026-10-01 according
to the [official announcement](https://blog.rust-lang.org/2026/10/01/Rust-1.99.0/).
`rustfmt`, `clippy`, and `wasm32-unknown-unknown` support native Rust and the Rust
frontend requirement. A [Buf setup-only action](https://buf.build/docs/bsr/ci-cd/github-actions/#run-setup-only)
defaults to **Buf 1.73.0** unless the specification selects another exact version; its [official release](https://github.com/bufbuild/buf/releases/tag/v1.73.0)
is dated 2026-09-11. It publishes no schemas and writes no PR comments.

Linux uses Ubuntu 24.04 and installs the
[Tauri native build prerequisites](https://v2.tauri.app/start/prerequisites/#linux).
macOS and Windows use hosted native development images. The workflow records
actual installed versions and raw provisioning logs under
`.rdd/evidence/provisioning/`, bound to candidate, policy and verifier commits
and specification/plan file hashes. Failure preserves attempted command logs
and cannot emit successful tool evidence. CLI and hosted execution use explicit
UTF-8; persisted generated/evidence bytes use stable LF encoding.

The separate preparation workflow operates while the run is `preparing` using
the independently pinned `RDD_PREPARATION_HARNESS_SHA` verifier. It uploads
`preparation-ci.json`, check receipts and raw provisioning logs for transfer into
the run. Qualified native/manual observations remain separate from hosted results.
The harness PR matrix also tests the candidate controller and actual native/WASM
generator/compiler proofs on Linux, macOS and Windows; those results do not prove
Todo acceptance or replace trusted-base application CI.

The specification workflow must still qualify and record its selected frontend
builder, Tauri packaging commands, additional test tools, dependency locks, and
platform coverage. Add their required installation to the trusted baseline
before freezing policy. The harness cannot choose these application-specific
versions before the corresponding solution decisions exist. Hosted macOS does
not imply that an unavailable or licensed desktop automation driver is supplied;
choose a supported automation route or an explicit manual protocol in the
specification. Packaging/signing credentials and reference-device qualification
remain separate from this ordinary hosted CI setup.

Manual verification and checks requiring a qualified reference host are listed
under `pending_external` in the CI report. They are mandatory at the phase/project
gates through separate exact-revision evidence. Their presence does not make the
hosted CI subset fail or fabricate a hardware qualification. The CI report always
sets `application_complete: false`; successful CI alone cannot close a phase.
If no ordinary applicable check can run, CI blocks instead of returning a vacuous
pass. Artifacts include the CI index and each executed check's JSON receipt and
log so later validation can inspect the underlying evidence.

The Todo requirements specify reference devices, operating systems and benchmark
protocols. Hosted runner measurements are not substitutes for those results.
Run the actual frozen benchmark and accessibility protocols on qualified local
or controlled reference machines, and import their revision-bound evidence.
Do not expose a persistent self-hosted machine to unreviewed pull request code.
If a separate reference-runner workflow is later needed, select its policy and
runner environment during specification instead of silently changing the
performance requirement to fit convenient hosted hardware.

### Action revisions

| Action | Version | Pinned commit |
|---|---|---|
| checkout | 7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| setup-python | 7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| upload-artifact | 7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |
| buf-action | 1.5.0 | `8c6a16e16f12ba20b6470afa9c2ba9b5ba8c97c3` |

The pins were resolved from official release commit pages on 2026-10-07:
[checkout](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1),
[setup-python](https://github.com/actions/setup-python/commit/5fda3b95a4ea91299a34e894583c3862153e4b97),
[upload-artifact](https://github.com/actions/upload-artifact/commit/cf430e030ddbb5b0abf93d22962f4752f3646cd9),
[buf-action](https://github.com/bufbuild/buf-action/commit/8c6a16e16f12ba20b6470afa9c2ba9b5ba8c97c3).
Review release notes and rerun the controller tests when updating these pins.
The version/source manifest is `.rdd/sources/runtime.json`. Source inspection, offline protocol fixtures, actual compiler proofs and hosted results have different evidence scopes; retain the tested revision and observations for each.

## Offline verification

The adapter tests exercise real local subprocesses and Git worktrees plus injected
GitHub/Codex protocol fixtures. They cover command injection resistance, deadlines,
streaming, stale-output rejection, schema rejection, dirty-worktree preservation,
idempotent phase PR publication, moved bases, absent/skipped/pending checks,
independent-review requirements, and requests-for-changes vetoes.

```sh
python -m unittest discover -s tests/harness -p test_adapters.py
```

Run `./rdd selftest` for controller regressions. `RDD_CODEX_SMOKE` may point to the installed binary for the optional client-support smoke check; this exercises syntax/catalog support, not paid account entitlement. Compiler proofs and workflow evaluations remain separate from that smoke. Use system temporary directories normally; `RDD_TEST_TMPDIR` may select a private writable test directory when workspace synchronization would race with clean-tree checks. Preserve strict verification instead of weakening it for a synchronization layer.

Runs pin the exact workflow graph and canonical profile/native configuration digest. The controller checks both before continuing mutations, including checks, reviews, recovery and publication, before recording state or evidence. A mismatch is a policy compatibility failure, not a new historical blocker to write automatically. `status` and `export-run` preserve original role names and evidence. Continue historical work with its recorded harness revision, or start an explicit fresh baseline; no role aliases, pin backfills or approval migrations are applied.

Keep raw test logs and workflow evaluation results in ignored evidence directories or CI artifacts tied to the tested revision. Historical delivery snapshots live in Git history; a checked-in transcript cannot establish current acceptance. Seeded forward traces evaluate routing, handoff quality, defect detection and verified correction, following [evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices). Record elapsed time and available token usage without inventing unavailable observations.
