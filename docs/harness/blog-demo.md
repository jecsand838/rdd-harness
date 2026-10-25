# Manual RDD demonstration

Use a fresh clone of your own writable repository on a dedicated `codex/*-baseline` branch. Follow the [README setup](../../README.md#get-started), resolve `doctor --full` prerequisites and configure the [required branch checks](codex-runtime.md#stacked-pr-policy). Keep the independently reviewed harness SHA for `RDD_PREPARATION_HARNESS_SHA`; actual model access, required platforms and manual/reference evidence must be available.

Run the three sessions in sequence:

```sh
./rdd workflow specification --mode regenerate --permission full-access
./rdd workflow preparation --permission full-access
./rdd workflow implementation --permission full-access
```

Leave each session only after inspecting its controller outcome. Specification must reach `specified` with committed frozen outputs; preparation must reach `prepared`, not `preparing`. Preparation includes committed/pushed materialization, [explicit CI dispatch](workflow-guide.md#stage-two-preparation), actual receipts and both final reviews. Baseline pushes do not start CI.

The implementation launcher prints the objective from `./rdd goal`. Submit it in the TUI prefixed with `/goal `; launching or sending an ordinary message does not activate Goal mode. Completion requires `gate project` to return `status=passed` and `application_complete=true`. Preserve its checkpoint/report and follow the generated application packaging instructions. Merging/releasing is separate.

## Interruptions and recovery

Exit code zero alone is not stage acceptance. Record the native session UUID and reopen that exact session through [native resume](codex-runtime.md#native-goal-execution); its permission settings are explicit per session. Inspect the existing Goal before `/goal resume`. `./rdd resume` separately reconciles controller state.

Repeating a workflow command opens another native session; it does not select the interrupted one. Repeating specification with `--mode regenerate` after freeze can start a new run. Recover on the recorded baseline/phase branch and preserve dirty work. For storage failures preserve DB/WAL/journals, checkpoints, evidence and worktrees before following the [recovery procedure](workflow-guide.md#repairs-and-interruptions).

The [runtime source record](../../.rdd/sources/runtime.json) distinguishes measured launch/resume from unestablished Goal execution, reviewer isolation and application acceptance. Read-only reviewer behavior remains required even when the runtime does not attest isolation.
