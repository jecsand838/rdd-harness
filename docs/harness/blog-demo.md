# Generate the Todo app from a fresh checkout

Clone your fork and enter its clean checkout. Provide Python 3.11+, Git, qualified Codex CLI 0.161.0, the pinned Rust/Buf tools, authenticated Codex and `gh`, a writable `origin`, and the native/reference environments required by the solution. Configure Git identity, the trusted preparation CI pin and required checks using the [runtime guide](codex-runtime.md). Use the canonical [requirements](../../requirements/requirements.md).

Run each command to completion before the next:

```sh
./rdd workflow specification --mode regenerate
./rdd workflow preparation
./rdd workflow implementation
```

The first command creates a baseline branch and local run state when starting from clean `main`. Answer only the typed specification questions it presents. Preparation and implementation activate native Goals and execute headlessly. The runner supplies the instructions, session recovery and Goal lifecycle.

Exit `0` means the controller accepted that stage. Exit `1` means an invalid request or validation failure; `2` means incomplete or blocked; `130` means interrupted. Resolve the reported cause and repeat the same command to resume its recorded run/session. Missing approval, CI, native/manual evidence or backend sessions remains incomplete. `--print` inspects a packet without mutations or runtime launch.

Use `./rdd status` and `./rdd workflow nodes` to inspect progress. Preserve diagnostics and [checkpoints](workflow-guide.md#repairs-and-interruptions). Detailed task, review, CI and phase procedures stay in the [workflow guide](workflow-guide.md); all existing gates remain required.

Application completion requires `gate project` to return `status=passed` and `application_complete=true`. Keep its validation reports, completed-run checkpoint, raw evidence and package digests. Launch the accepted package using the build/install/run commands produced and verified by that run. PR merging and releases remain separate actions under the [release procedure](../../README.md#release-into-main).
