# Fresh Todo generation

This runbook targets [PR #12](https://github.com/jecsand838/rdd-harness/pull/12), commit `0965b710c2d42f822678460e5c18eb36859d05ca`: the PR #6 native workflows plus SQLite correctness and Codex CLI **0.162.1** support. PR #12 is not yet merged. All three workflows open the native Codex TUI; it handles conversation and approvals under your existing policy.

## 1. Create a fresh checkout

Use a new, unused directory. The example preserves any existing `rdd-todo-demo`; do not copy its run state, checkpoints or generated files into this checkout. These commands assume write access to the repository below.

```sh
cd ~ &&
git clone --branch codex/tui-first-workflows https://github.com/jecsand838/rdd-harness.git rdd-todo-demo-fresh &&
cd rdd-todo-demo-fresh &&
git switch -c "codex/todo-$(date +%Y%m%d-%H%M%S)-baseline" 0965b710c2d42f822678460e5c18eb36859d05ca &&
./rdd init &&
./rdd doctor --full
```

Stop if a command fails. If the destination already exists, choose another unused directory. Keep this dedicated baseline branch; do not author the run on `main`.

Resolve the [prerequisites](https://github.com/jecsand838/rdd-harness/blob/0965b710c2d42f822678460e5c18eb36859d05ca/README.md#prerequisites) until doctor reports `ready: true`: Python 3.11+, Git, authenticated Codex CLI 0.162.1 and `gh`, Git author identity, configured model access, Rust/Buf and required platform tools. Doctor checks advertised capabilities; it does not prove model entitlement or application acceptance.

Before preparation acceptance, the repository needs the [required-check configuration](https://github.com/jecsand838/rdd-harness/blob/0965b710c2d42f822678460e5c18eb36859d05ca/docs/harness/codex-runtime.md#stacked-pr-policy) and `RDD_PREPARATION_HARNESS_SHA` set to the independently reviewed harness revision. For this candidate, that full SHA is `0965b710c2d42f822678460e5c18eb36859d05ca`. The workflows may push the prepared baseline, create phase PRs and trigger CI. Required hosted, native and manual evidence must actually be available; missing evidence blocks acceptance.

## 2. Specification

```sh
./rdd workflow specification --mode regenerate
```

The command supplies the specification workflow instructions and uses [requirements/requirements.md](https://github.com/jecsand838/rdd-harness/blob/0965b710c2d42f822678460e5c18eb36859d05ca/requirements/requirements.md). Answer its specification questions and native approval prompts. Let it finish independent reviews, qualification, specification/contract freeze and the baseline commit. No separate startup prompt is needed.

After leaving the TUI, run `./rdd status`. Continue only when it reports `specified`, the accepted artifacts are committed, and no blockers remain. Save the native session ID for recovery.

## 3. Preparation

```sh
./rdd workflow preparation
```

The command supplies the preparation instructions. Let the session finish the groomed backlog, plan freeze, task packets, committed/pushed baseline, readiness evidence and final reviews. After leaving the TUI, check `./rdd status`: it must report `prepared`, established by a passing `gate preparation`. `preparing` means the handoff is still incomplete.

## 4. Implementation

```sh
./rdd workflow implementation
```

The session prints the exact objective from `./rdd goal`. Copy it into the TUI prefixed with `/goal ` and submit it. This is the one manual Goal activation step; an ordinary message does not activate Goal mode. You can also print the objective from a terminal in this checkout with `./rdd goal`.

Let the implementation workflow drive tasks, continuous review, phase gates and one PR per phase. Completion requires `./rdd gate project` to return `status=passed` and `application_complete=true`; preserve its report, checkpoint and package evidence. Use the generated build/install instructions for the accepted application. Merging PRs is a separate action.

## Interruptions and recovery

A workflow command returns the native process exit code: exit `0` alone does **not** mean RDD accepted the stage. Check controller state and gate results before advancing.

For an ordinary interruption, inspect `./rdd status` on the recorded baseline or active phase branch. Reopen the exact native session, replacing `SESSION_UUID` and the directory if necessary:

```sh
codex resume SESSION_UUID --cd /Users/connorsanders/rdd-todo-demo-fresh
```

Inspect an existing Goal before using `/goal resume`; do not submit a replacement objective to restart its accounting. Native [session resumption](https://learn.chatgpt.com/docs/cli/reference#codex-resume) and [Goal resumption](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex) are separate from `./rdd resume`, which reconciles controller state. Repeating a workflow command opens a new TUI session, not an automatic exact-session resume. In particular, repeating specification with `--mode regenerate` after freeze can start another run.

For storage errors, stop and preserve the database, WAL/journals, checkpoint, evidence and worktrees. Verify them before controller recovery; do not delete journals or repeatedly retry uncertain writes. Follow the existing [repair and recovery guidance](https://github.com/jecsand838/rdd-harness/blob/0965b710c2d42f822678460e5c18eb36859d05ca/docs/harness/workflow-guide.md#repairs-and-interruptions).

The [runtime guide](https://github.com/jecsand838/rdd-harness/blob/0965b710c2d42f822678460e5c18eb36859d05ca/docs/harness/codex-runtime.md#native-goal-execution) records the qualification limits: native launch and exact-session resume were exercised; full application acceptance and isolated reviewer permissions were not established. Reviewers must remain read-only, but a profile declaration alone does not prove sandbox isolation.
