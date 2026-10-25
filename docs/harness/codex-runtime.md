# Codex runtime, external adapters, and CI

This guide owns native runtime, adapter and CI policy. Use the [workflow guide](workflow-guide.md) for lifecycle commands and the [evidence guide](evidence-guide.md) for receipts and review. Measured client observations and primary sources live in [runtime.json](../../.rdd/sources/runtime.json). Run `./rdd doctor` against the installed environment.

## Runtime contract

The primary thread coordinates the three workflows; the deterministic controller validates transitions, state, evidence and PR operations. Native delegation selects the exact `agent_type` with `fork_turns="none"` and a bounded packet. Let the registered profile supply model/effort; reload changed profiles in a fresh session. The coordinator cannot replace a required specialist.

| Profile | Model / effort | Responsibility |
|---|---|---|
| `rdd_coordinator` | `gpt-6-astra` / `ultra` | Intake, transitions, integration and acceptance execution |
| `rdd_domain_analyst` | `gpt-6.1-sol` / `xhigh` | S1 domain inventory |
| `rdd_verification_designer` | `gpt-6.1-sol` / `xhigh` | S2–S4 goals, scenarios and benchmarks |
| `rdd_qualification_engineer` | `gpt-6.1-sol` / `xhigh` | S5 dependency, compiler, host and transfer experiments |
| `rdd_contract_architect` | `gpt-6-astra` / `ultra` | Early advice; S6 architecture, target tree and contracts |
| `rdd_task_planner` | `gpt-6.1-sol` / `xhigh` | P1–P5 tasks, DAG, verticals, phases and sites |
| `rdd_complex_implementor` | `gpt-6.1-sol` / `xhigh` | Small or large leased tasks |
| `rdd_light_implementor` | `gpt-6-luna` / `xhigh` | Small, unambiguous leased tasks |
| `rdd_researcher` | `gpt-6.1-sol` / `xhigh` | Read-only evidence gathering |
| `rdd_reviewer` | `gpt-6.1-sol` / `xhigh` | Read-only live and final review |

Canonical `.codex/agents/` TOMLs own role instructions, model, effort and sandbox. The loader checks them against native defaults in `.codex/config.toml`. Three child slots accommodate two authors and a continuous reviewer; a second final reviewer uses a released author slot. Unrelated custom profiles gain no claim authority. Procedures belong in skills.

Profile settings are requested configuration, not effective permission or backend attestation. Native children inherit live parent sandbox/approval overrides; inspect actual permissions and keep reviewers read-only. `--profile` is not custom-agent selection. Consult the [custom-agent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents) and [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) when changing the client.

### Capability checks

`CodexAdapter.doctor()` checks executable/version, launch/resume and bounded-exec flags, login, catalog support and every configured model/effort pair. Advertised support does not prove account entitlement; `account_access_verified` remains false without actual supporting evidence. Missing access blocks the role without substitution. The measured reference client is 0.162.1; the first client supporting Goals is not necessarily sufficient for the current roster. Install/authenticate through official instructions and honor local project trust.

`requested_runtime` records role/profile identity, model, effort and sandbox. JSONL thread/turn events, process exits and results are separate observations. A role label, `verified: true`, or remembered session ID cannot attest an unobserved backend.

## Native Goal execution

`CodexAdapter.native_argv` applies canonical coordinator settings and encoded TOML configuration, passing the prompt as one argument after `--`. It leaves approval policy to the runtime unless explicitly overridden. It creates no second workflow loop or session ledger.

After specification and preparation acceptance, run `./rdd goal`, open `./rdd workflow implementation`, and submit `/goal ` followed by the printed objective. The objective is under 4,000 characters; detailed procedure stays in the workflow skill. A launcher exit or Goal stop does not establish controller acceptance.

Resume the exact native session with `codex resume SESSION_UUID --cd REPOSITORY`, inspect its Goal, then use `/goal resume` when appropriate. Explicit resume requires a canonical UUID, reapplies coordinator settings and never selects `--last`. `./rdd resume` recovers controller state; it does not select a native session. Measured launch/resume observations in the source record do not prove Goal execution, isolated reviewer permissions or application acceptance. See the [CLI resume reference](https://learn.chatgpt.com/docs/cli/reference#codex-resume) and [Goals guide](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex).

### Workflow permissions

Each interactive launcher accepts a per-session `--permission full-access`:

```sh
./rdd workflow specification --mode regenerate --permission full-access
./rdd workflow preparation --permission full-access
./rdd workflow implementation --permission full-access
```

The option selects `--sandbox danger-full-access --ask-for-approval never`; it does not change the canonical model/effort or profile identity. `requested_runtime` records the requested override. Omission retains normal launch behavior; no previous override is remembered. Controller ownership, frozen inputs and acceptance rules still apply.

Inspect launch arguments without starting a run by omitting `--mode`:

```sh
./rdd workflow specification --permission full-access --print
```

An explicit mode may start a run even with `--print`. Graph commands reject this permission option. `./rdd goal` only prints; Goal execution uses the implementation session's permissions. To reopen a full-access session directly, explicitly select its UUID and settings:

```sh
codex resume SESSION_UUID --cd REPOSITORY --sandbox danger-full-access --ask-for-approval never
```

## Bounded worker adapter

`CodexAdapter.exec()` is an optional one-turn adapter, not Goal emulation. It loads a canonical profile, encodes supported settings as TOML, supplies the prompt on stdin, and invokes `codex -a never exec` with JSON events, explicit cwd, output schema and result path. It never interpolates prompts, filenames, model IDs or PR text through a shell. Its `-a never` prevents headless approval prompts while retaining the profile sandbox; unavailable permission fails.

Each attempt creates an ignored runtime directory containing the prompt, schema snapshot, `events.jsonl`, `stderr.log`, `answer.json` and receipt. A deadline terminates the process group. Success requires a completed event, observed session identity, no error event, zero exit and schema-valid output. The controller still validates meaning, provenance and baseline; valid JSON is not implementation evidence. See [noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode).

Use fresh bounded context when the target/baseline changes. Raw logs can contain repository content; retain them outside version control and copy only reviewed relevant summaries into authority artifacts. Resume from current controller/source state, not remembered session labels.

### Python adapter interface

Adapters use the standard library and accept an injected `runner(argv, cwd=..., timeout=..., **kwargs)` returning `CommandResult`. `RddAdapterError.code` distinguishes capability, malformed evidence, timeout, revision and safety failures. Workflows use public controller commands to retain locking and lease checks.

Reuse worktrees only for the exact repository/branch with clean state and expected base ancestry. Preserve dirty work/user files for deliberate recovery. The adapters implement no automatic reset, clean, force branch replacement or force push.

## Stacked PR policy

Phase branches are `rdd/RUN_ID/pNN`. P01 targets the recorded `codex/*-baseline`; later PRs target the preceding sealed branch. Publication reconciles all PR states for the exact head using a stable run/phase marker, verifies head/base, and reuses the same PR. A closed/merged PR or missing/moved remote base blocks replacement. The run lock serializes publication.

Descriptions use a real `--body-file`. The adapter does not send messages, request reviewers, merge/close PRs, force-push or restack seals. The supported completion policy is `ready`: accepted open PRs, with a separate operator-authorized release after project acceptance.

`phase_status()` reads PR metadata/checks and rereads revision to detect movement. It requires exact head/base SHA and branch, open non-draft state, confirmed mergeability, every configured and server-required check, and independent review. Pending, skipped, absent, unknown, truncated or unreadable results cannot establish readiness. GitHub change requests veto a local pass; optional GitHub approval must bind the exact head.

Require the nonempty aggregate **`verify`** check on `main`, the prepared baseline, and each exact sealed predecessor before a successor uses it. Do not wildcard-protect active/future phase branches so they cannot publish or repair. If `gh pr checks --required` cannot establish server rules, inspect configuration instead of waiving validation. See [branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches), [`gh pr view`](https://cli.github.com/manual/gh_pr_view), and [`gh pr checks`](https://cli.github.com/manual/gh_pr_checks).

## CI and reference-platform evidence

`.github/workflows/rdd.yml` selects one verification route. All routes retain read-only permissions, pinned actions and explicit PR-head checkout, with no application secrets or privileged `pull_request_target` execution. Pushes do not launch CI. Protect the workflow through independent repository rules/review; an editable verifier cannot establish its own external trust root.

| Route | Trusted policy and checks |
|---|---|
| Unfrozen harness maintenance into `main` | Candidate harness regression suite; neither checkout may have any freeze artifact; phase/release branches excluded |
| Frozen phase PR | Separate base controller and prepared policy; cumulative ordinary checks applicable to each declared hosted platform |
| Release PR | Trusted `main` controller plus separately pinned prepared policy/source; complete source and project checks |
| Preparation dispatch | Independently pinned harness; exact committed materialization and prerequisite proofs |

Partial freezes or verifier failures never fall back to maintenance. `verify` requires successful selection and every selected job to succeed; only explicitly unselected jobs may be skipped. Harness CI and stateless application CI always report `application_complete=false`.

Ordinary phase verification uses sibling candidate/base checkouts:

```text
python baseline/tools/rdd/cli.py --root candidate ci --policy-root baseline --branch BRANCH
```

A same-repository `codex/rdd-release/RUN_ID` PR into `main` requires operator-set repository variables `RDD_RELEASE_POLICY_SHA` (prepared baseline) and `RDD_RELEASE_SOURCE_SHA` (project-accepted head). Candidate files, PR text and branch names cannot select these pins. The trusted verifier must already be installed on `main`:

```text
python baseline/tools/rdd/cli.py --root candidate ci
  --policy-root prepared-policy --branch codex/rdd-release/RUN_ID
  --release-policy POLICY_SHA --release-source SOURCE_SHA
```

Before frozen checks, require clean exact revisions, prepared-baseline ancestry, intact frozen artifacts, identical protected policy, complete phase projection and no remaining anchors. Stale/unrelated/missing pins fail. The prepared policy supplies toolchain inventory. This verifies source, not new native/manual acceptance; preserve original acceptance evidence.

Before a plan exists, stateless `./rdd ci` reports `harness_only`. A prepared baseline verifies contracts/pending projections without claiming implementation. On nonphase branches, only a complete phase prefix may select checks; reports use `source_cumulative` or explicit `release_source`, `observed_through_phase`, `phase: null`, and `task_history_verified: false`. Final source boundaries include project checks. Marker inference never proves task history, seals or reviews; there is no post-merge verification run.

Frozen checks determine hosted environments. `ci_tools.py` rejects conflicting tool pins, selects Python/Buf, installs the exact Rust toolchain/components/targets and declared supported Cargo frontend tools (`cargo-tauri`, `trunk`, `wasm-bindgen`, `wasm-pack`), and measures installed versions. Other tools require qualified installed executables; manifests cannot inject installer commands. Initial pins are in `rust-toolchain.toml` and the workflows; release/source observations remain in the runtime source record rather than a second prose version table.

Linux uses Ubuntu 24.04 with [Tauri prerequisites](https://v2.tauri.app/start/prerequisites/#linux); macOS/Windows use native hosted images. Qualification must establish the actual frontend builder, packaging, dependency locks, automation route and additional tools before policy freeze. Hosted macOS does not supply every licensed desktop driver. Signing credentials and reference-device qualification remain separate. Buf runs setup-only, publishing no schemas or PR comments.

Provisioning evidence binds commands, measured versions and raw logs to candidate/policy/verifier commits and specification/plan hashes. Failed attempts retain logs without successful tool evidence. CLI/hosted execution uses explicit UTF-8 and stable LF output.

Preparation CI is dispatch-only while the run is `preparing`:

```sh
gh workflow run preparation.yml --ref YOUR_BASELINE_BRANCH -f candidate=FULL_MATERIALIZATION_SHA
```

`RDD_PREPARATION_HARNESS_SHA` independently pins its verifier. The selected single-component `codex/*-baseline` branch must resolve to the supplied full SHA; tags and mismatches fail before provisioning. Branch-grouped concurrency supersedes older dispatch attempts. Transfer `preparation-ci.json`, check receipts and raw provisioning logs into the run; obtain both final review perspectives before `gate preparation`.

Manual/reference-host checks appear in `pending_external` and remain mandatory at local gates. Hosted subsets may pass while those observations are pending; absent ordinary applicable checks cannot yield a vacuous pass. Artifacts contain the CI index and every executed check's receipt/log. [Evidence transfer](evidence-guide.md#check-receipts-and-ci-transfer) defines their import and provenance verification.

The Todo reference devices, benchmark and accessibility protocols require actual qualified environments. Hosted measurements cannot substitute. Do not expose a persistent self-hosted machine to unreviewed PR code; select any future reference-runner route during specification.

### Action revisions

Executable pins live in [rdd.yml](../../.github/workflows/rdd.yml) and [preparation.yml](../../.github/workflows/preparation.yml). Review upstream changes and the measured runtime source record when updating them. Pins complement repository protection; they do not replace it.

## Harness verification

Run every Python harness regression with `python3 -m unittest discover -s tests/harness -p 'test_*.py' -v` (use `python` on Windows/CI). The maintenance lane uses the same discovery pattern. Refinement, specification/preparation and runtime tests use disposable repositories; individual tests identify substituted compiler/platform/remote prerequisites. Passing them is controller evidence, not Todo acceptance or proof of conversational understanding. Exercise the real native workflow separately.

`./rdd selftest` retains manual Rust generator unit tests; CI does not invoke this command. Application contract checks still compile descriptors/bindings and positive/negative provider-consumer proofs. All frozen application checks remain mandatory.

Runs pin graph, refinement and profile/native policy before mutations, checks, review, recovery and publication. A mismatch requires the recorded harness or a fresh reviewed run; status/export preserve original identities without aliases, pin backfills or migrated approvals. Keep raw test logs/evaluation results in ignored evidence or CI artifacts bound to source. Historical transcripts cannot establish current acceptance; record measured elapsed/token usage without inventing unavailable observations.
