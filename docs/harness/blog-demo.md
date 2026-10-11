# Generate the Todo app from a fresh checkout

Clone your fork and enter its clean checkout. Provide Python 3.11+, Git, macOS with qualified Codex CLI 0.162.1, the pinned Rust/Buf tools, authenticated Codex and `gh`, a writable `origin`, and the native/reference environments required by the solution. Configure Git identity, the trusted preparation CI pin and required checks using the [runtime guide](codex-runtime.md). Use the canonical [requirements](../../requirements/requirements.md).

Run each command to completion before the next:

```sh
./rdd workflow specification --mode regenerate
./rdd workflow preparation
./rdd workflow implementation
```

An unaccepted stage opens the native Codex TUI under the existing approval policy and supplies stage instructions automatically; accepted stages are rechecked without relaunch. Answer only necessary specification questions in the native TUI. Preparation proceeds interactively from its instructions without routine user prompts. The implementation command prints a short copy-ready `/goal` command referencing the complete objective in `.rdd/goals/implementation.txt`; paste it only when no Goal exists. On retry, inspect and resume the exact session and existing Goal; never use `--last`, create a replacement, or reset Goal accounting.

After leaving the TUI, the runner reads `workflow_result` without mutation to determine command status: exit `0` means the controller accepted that stage; exit `1` means an invalid request or validation failure; `2` means incomplete or blocked; `130` means interrupted. Resolve the reported cause and repeat the same command to resume its exact recorded session. Missing CI, native/manual evidence or backend sessions remains incomplete. `--print` inspects a packet without mutations or runtime launch.

Use `./rdd status` and `./rdd workflow nodes` to inspect progress. Preserve diagnostics and [checkpoints](workflow-guide.md#repairs-and-interruptions). Detailed task, review, CI and phase procedures stay in the [workflow guide](workflow-guide.md); all existing gates remain required.

Application completion requires `gate project` to return `status=passed` and `application_complete=true`. Keep its validation reports, completed-run checkpoint, raw evidence and package digests. Launch the accepted package using the build/install/run commands produced and verified by that run. PR merging and releases remain separate actions under the [release procedure](../../README.md#release-into-main).
