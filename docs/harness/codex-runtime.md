# Codex runtime, external adapters, and CI

Verified against primary documentation and the locally installed Codex CLI on
**2026-10-07**. This file describes the harness runtime, not Todo application code.

## Runtime contract

The normal execution surface is an interactive local Codex session opened in the
repository. Repository skills perform specification, preparation, and
implementation in sequence. The Python controller supplies validation, durable
state, task ownership, evidence, and PR lifecycle operations. Model reasoning is
responsible for producing and reviewing artifacts; the controller decides whether
the evidence permits a transition.

The configured coordinator is `gpt-6-astra` with `ultra`; `rdd_large` and
`rdd_reviewer` use `gpt-6.1-sol` with `xhigh`; `rdd_small` uses `gpt-6-luna` with
`xhigh`. `rdd_researcher` uses `gpt-6.1-sol` with `xhigh`. The primary thread normally
coordinates directly; `rdd_coordinator` is also available as an explicit role.
Three concurrent child slots leave room for two implementors and one live reviewer.
Use disjoint file leases for parallel writes. Extra speculation does not justify
extra agents.

`.codex/config.toml` sets project defaults. Each file in `.codex/agents/` declares a
`name`, `description`, and `developer_instructions`, together with explicit model
and effort values. Current Codex discovers these standalone project roles.
Consult the [official subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents)
and [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
when changing the installed client. Do not mix a legacy config example into this
format without verifying it against that client.

### What was actually verified

| Surface | Observed result |
|---|---|
| Local binary | `codex-cli 0.159.2` |
| Noninteractive flags | `--json`, `--output-schema`, `--output-last-message`, explicit model/config and sandbox flags |
| Bundled catalog | `gpt-6-astra/ultra`, `gpt-6.1-sol/xhigh`, and `gpt-6-luna/xhigh` advertised |
| Native Goal entry | Official `/goal` command documented; no `codex exec --goal` flag in local help |
| Paid model generation | Not executed while assembling the boilerplate |
| GitHub publication | Covered by offline adapter fixtures; no remote PR was created while assembling the boilerplate |

The bundled catalog verifies client syntax and advertised capabilities. It does
not prove that a particular account has access. `CodexAdapter.doctor()` checks
the executable, flags, catalog and login status. Its `account_access_verified`
field remains false. A later model access error is a blocker. The harness never
silently changes models or reasoning effort.

Install or update Codex using its official installation instructions, authenticate
locally, then run the repository doctor. A current client compatible with the
configuration above is required. The reference client is 0.159.2; the older
minimum version that introduced Goals does not establish support for all current
role/configuration features. Follow normal local project-trust prompts rather
than bypassing them.

## Native Goal execution

1. Complete `$specification-workflow` and `$preparation-workflow` in sequence.
2. Run `./rdd goal` to print `.rdd/goals/implementation.txt`.
3. Open Codex in the repository, or use `./rdd workflow implementation`.
4. Set the native Goal by entering `/goal ` followed by the printed objective.
5. Inspect progress with the controller and Codex subagent views. Resume an
   interrupted Goal with the native `/goal resume` command after checking state.

The file is a distribution convenience. The goal text itself is under 4,000
characters and is pasted as the native objective. The workflow skill contains
the detailed procedure and reads the canonical plan and state as needed. Do not
inline every requirement, specification, skill or task into the goal. The
[official Goals guide](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)
describes the lifecycle and completion-evidence model. A budget stop or pause is
not success. Missing benchmarks, model access, unresolved specs, and unavailable
PR evidence must remain visible blockers.

## Bounded worker adapter

`CodexAdapter.exec()` is an optional one-turn adapter for automation. It is not an
emulation of native Goals. It builds an argv list equivalent to:

```text
codex -a never exec --json --color never --model MODEL
  --config model_reasoning_effort="EFFORT" --sandbox workspace-write
  --cd REPOSITORY --output-schema SCHEMA --output-last-message ANSWER -
```

The prompt is supplied on stdin. The adapter keeps sandbox enforcement enabled;
an action that needs unavailable permission fails instead of prompting from a
headless subprocess. It never uses a shell to interpolate prompts, file names,
model IDs or PR text.

Every attempt uses a new directory below `.rdd/runtime/`. It contains the prompt,
schema snapshot, streaming `events.jsonl`, `stderr.log`, final `answer.json`, and a
`receipt.json` with the session ID and outcome. A deadline terminates the process
group. The result requires a completed event, session identity, no error event,
a zero process exit, and schema-valid output. The controller must still validate
the artifact's meaning, provenance and baseline: valid JSON is not implementation
evidence. See [Codex noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode).

Use a fresh bounded context packet when a target or baseline changes. Keep raw
logs out of version control; they may contain repository contents. Copy only
reviewed, relevant evidence summaries into the run's validation artifacts. On
resume, recover the run and inspect its current source digest before continuing.
A remembered session ID cannot override the repository baseline.

### Python adapter interface

All adapters use only the Python standard library. They accept an injected
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
    model="gpt-6.1-sol", effort="xhigh", timeout=1800,
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

The phase branch name is `rdd/RUN_ID/pNN`. Phase 1 targets the recorded base branch;
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
deliverable is a validated open stack. Merging the stack is a separate user action
that needs a deliberate strategy and fresh integration validation.

`phase_status()` reads both PR metadata and required checks, then rereads the PR
revision to detect movement during collection. It verifies the expected complete
head SHA, recorded base SHA and branch, optionally the phase branch name, open
non-draft state, confirmed mergeability, every configured check, every reported
server-required check, and independent review evidence. Skipped, pending, absent,
unknown, truncated, or unreadable check results cannot produce readiness.

The configured required-check list must be nonempty. The supplied workflow exposes
the aggregate check **`verify`**. Configure GitHub branch rules to require this
check for `main` and the phase branches. See [protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
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

For a PR, the workflow checks out the candidate and its base into sibling
directories. It tests the trusted base controller, then invokes the **base
controller's** CLI with `--root candidate ci --policy-root baseline --branch
BRANCH`. The frozen verifier policy comes from that separate base checkout, so
editing the candidate CLI does not change the validator being executed. The
trusted phase base must already contain the harness and prepared plan. Push runs
on `main` use their own revision as policy and provide diagnostics. Phase branches
produce the `verify` check only through the base-bound PR run, avoiding a same-name
push/dispatch check with weaker provenance. Protect the workflow itself through
repository rules and review; a repository-contained verifier cannot establish
an external trust root for a workflow file it is allowed to replace.

The `verify` job succeeds only if all prerequisite jobs succeed. A canceled,
failed, or skipped prerequisite cannot become a green aggregate. Pinning actions
protects the selected dependency revision; it does not replace repository
branch protections or review of changes to the verifier and workflow itself.

Application build prerequisites and platform-specific command inventory must be
qualified and pinned during specification/preparation. Before those artifacts
exist, CI validates the boilerplate/controller only. A prepared baseline checks
its contracts and pending task projections without claiming implementation. Phase
CI runs cumulative ordinary checks applicable to its platform. A missing native
dependency needed by those checks is an environment blocker.

When the trusted baseline contains a frozen plan, the supplied workflow installs
the exact version in its `rust-toolchain.toml`, including the listed components
and targets. The initial pin is **Rust 1.99.0**, released on 2026-10-01 according
to the [official announcement](https://blog.rust-lang.org/2026/10/01/Rust-1.99.0/).
`rustfmt`, `clippy`, and `wasm32-unknown-unknown` support native Rust and the Rust
frontend requirement. A [Buf setup-only action](https://buf.build/docs/bsr/ci-cd/github-actions/#run-setup-only)
installs **Buf 1.73.0**, whose [official release](https://github.com/bufbuild/buf/releases/tag/v1.73.0)
is dated 2026-09-11. It publishes no schemas and writes no PR comments.

Linux uses Ubuntu 24.04 and installs the
[Tauri native build prerequisites](https://v2.tauri.app/start/prerequisites/#linux).
macOS and Windows use hosted native development images. The workflow records
the actual Rust, Cargo, Buf, Python, and operating-system versions in
`.rdd/evidence/toolchain.json`; that receipt is included in the CI artifact.
These setup steps are conditional, so the unopened boilerplate runs its Python
selftests without downloading an application toolchain.

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
The version/source manifest is `.rdd/sources/runtime.json`. No GitHub Actions
job, Rust compilation, or paid model generation was run while assembling this
boilerplate; source inspection and offline controller tests establish a narrower
verification scope.

## Offline verification

The adapter tests exercise real local subprocesses and Git worktrees plus injected
GitHub/Codex protocol fixtures. They cover command injection resistance, deadlines,
streaming, stale-output rejection, schema rejection, dirty-worktree preservation,
idempotent phase PR publication, moved bases, absent/skipped/pending checks,
independent-review requirements, and requests-for-changes vetoes.

```sh
python -m unittest discover -s tests/harness -p test_adapters.py
```

To add a read-only smoke check of a locally installed Codex without authentication
or a paid model turn, set `RDD_CODEX_SMOKE` to its executable path before running
the same tests. The smoke reads version, exec help, and the bundled model catalog.
It was run successfully with Codex 0.159.2 while creating this boilerplate.
