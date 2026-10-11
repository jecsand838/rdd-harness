"""Native TUI lifecycle; only controller evidence establishes stage acceptance."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from .common import (RddError, RddStorageError, clean, git, operation_lock, read_json)
from .profiles import load_profiles
from .native_process import OwnedProcessTree, ProcessTable
from .storage_failure import (check_failure, headless_scope, record_failure,
                              register_headless, preserve_primary_error)

STAGES = ("specification", "preparation", "implementation")
READONLY_PURPOSES = {"live": "rdd_reviewer", "execution": "rdd_reviewer", "research": "rdd_researcher"}
TUI_VERSION = "0.162.1"
GOAL_STATUSES = {"active", "paused", "blocked", "complete", "budgetLimited", "usageLimited"}


def legacy_objective(controller, stage):
    # Retain the old checkpoint interpretation; never convert an old session.
    return controller.goal() if stage == "implementation" else (
        "Complete preparation against the frozen specification and contracts through accepted gate preparation. "
        "Follow $preparation-workflow, with independent continuous review, real readiness evidence and committed materialization. "
        "Missing external evidence or permissions leaves this objective incomplete.")


def launch_packet(controller, stage, mode=None):
    locator = controller.root / ".rdd/run.json"
    run_id = read_json(locator).get("run_id") if locator.is_file() else None
    objective = controller.goal() if stage == "implementation" else None
    return {"stage": stage, "run_id": run_id, "mode": mode,
            "requested_runtime": controller.profile_settings("rdd_coordinator"),
            "skill": f".agents/skills/{stage}-workflow/SKILL.md", "objective": objective,
            # Long native pastes are converted to ordinary messages/attachments.
            # Keep the qualified slash command short; the full objective stays canonical.
            "goal_command": ("/goal Follow $implementation-workflow and the complete objective in "
                ".rdd/goals/implementation.txt. Finish only when ./rdd gate project reports "
                "status=passed and application_complete=true.") if objective else None,
            "prompt": f"Follow ${stage}-workflow and AGENTS.md using ./rdd. "
                f"Stage={stage}; run={run_id or 'fresh'}; requirements={controller.config['requirements']}. "
                "Complete this stage's artifacts, specialist handoffs, continuous and final independent reviews, "
                "checks, commits and acceptance. Stop before the next workflow. "
                "Use ./rdd review run for isolated review/research, never native reviewer children. "
                "Controller evidence determines success, not prose or TUI exit. "
                + ("Ask necessary specification questions normally and persist actual decisions in specification artifacts."
                   if stage == "specification" else "Continue the approved work without routine orchestration questions; report concrete blockers.")}


def _uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def validate_runtime(controller, state):
    """Recovery references do not establish acceptance or make sessions portable."""
    runtime = state.get("workflow_runtime", {})
    if not isinstance(runtime, dict) or set(runtime) - set(STAGES):
        raise RddError("Invalid workflow runtime stages")
    sessions = set()
    for stage, row in runtime.items():
        if not isinstance(row, dict):
            raise RddError("Invalid workflow runtime metadata")
        tui = row.get("backend") == "tui"
        fields = ({"backend", "launch_id", "thread_id", "requested_runtime", "runtime", "connection", "readonly"}
                  if tui else {"thread_id", "requested_runtime", "runtime", "last_turn", "goal", "connection", "readonly", "pending", "driver_paused"})
        if set(row) - fields or (tui and not _uuid(row.get("launch_id"))):
            raise RddError("Invalid workflow runtime metadata")
        if row.get("requested_runtime") != controller.profile_settings("rdd_coordinator"):
            raise RddError("Workflow runtime profile identity changed")
        if row.get("connection") not in {"starting", "connected", "interrupted", "stopped", "accepted", "uncertain"}:
            raise RddError("Invalid workflow connection state")
        identity = row.get("runtime", {})
        if (not isinstance(identity, dict) or set(identity) != {"version", "executable", "executable_sha256"}
                or not all(isinstance(v, str) and v for v in identity.values())):
            raise RddError("Invalid workflow executable identity")
        if tui and (identity["version"] != TUI_VERSION or
                    (row.get("connection") in {"connected", "accepted"} and not row.get("thread_id"))):
            raise RddError("TUI session has no qualified runtime or attached identity")
        entries = [row]
        readonly = row.get("readonly", {})
        if not isinstance(readonly, dict) or set(readonly) - set(READONLY_PURPOSES):
            raise RddError("Invalid read-only session purposes")
        for purpose, session in readonly.items():
            allowed = {"thread_id", "requested_runtime", "last_turn", "packet_digest", "pending"} if tui else {
                "thread_id", "requested_runtime", "last_turn", "packet_digest", "callback_id"}
            if not isinstance(session, dict) or set(session) - allowed:
                raise RddError("Invalid read-only session metadata")
            if session.get("requested_runtime") != controller.profile_settings(READONLY_PURPOSES[purpose]):
                raise RddError("Read-only session profile changed")
            for key in ("pending", "callback_id"):
                value = session.get(key)
                if value is not None and (not isinstance(value, str) or not 0 < len(value) <= 200):
                    raise RddError("Invalid read-only pending identity")
            value = session.get("packet_digest")
            if value is not None and (not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
                raise RddError("Invalid read-only packet identity")
            entries.append(session)
        for session in entries:
            tid = session.get("thread_id")
            if tid is not None:
                if (not isinstance(tid, str) or not tid or len(tid) > 200 or tid in sessions
                        or (tui and not _uuid(tid))):
                    raise RddError("Invalid or reused workflow thread identity")
                sessions.add(tid)
            turn = session.get("last_turn")
            if turn is not None and (not isinstance(turn, str) or not turn or len(turn) > 200):
                raise RddError("Invalid workflow turn identity")
        if not tui:
            if "driver_paused" in row and type(row["driver_paused"]) is not bool:
                raise RddError("Invalid driver pause provenance")
            goal = row.get("goal")
            if goal is not None and (stage == "specification" or not isinstance(goal, dict)
                    or goal.get("threadId") != row.get("thread_id")
                    or goal.get("objective") != legacy_objective(controller, stage)
                    or goal.get("status") not in GOAL_STATUSES or type(goal.get("createdAt")) is not int
                    or (goal.get("tokenBudget") is not None and (type(goal["tokenBudget"]) is not int or goal["tokenBudget"] <= 0))
                    or any(type(goal.get(k)) is not int or goal[k] < 0 for k in ("tokensUsed", "timeUsedSeconds"))):
                raise RddError("Invalid recorded native Goal identity/accounting")
            pending = row.get("pending")
            if pending is not None and (not isinstance(pending, str) or len(pending) > 200):
                raise RddError("Invalid pending runtime operation")


def journal(controller, stage):
    check_failure(controller.root)
    return controller.state(allow_blocked=True).get("workflow_runtime", {}).get(stage, {})


def update_runtime(controller, stage, **changes):
    check_failure(controller.root)
    with operation_lock(controller.root):
        state = controller.state(allow_blocked=True)
        controller.guard_source_write(state)
        with controller.store.edit(state["id"]) as current:
            controller.guard_run_policy(current)
            current.setdefault("workflow_runtime", {}).setdefault(stage, {}).update(changes)
            validate_runtime(controller, current)


def preflight(server, root):
    """Non-inference capability reads before creating a branch, run or session."""
    profiles = load_profiles(root)
    config = server.effective_config
    if config.get("sandbox_mode") != "workspace-write":
        raise RddError("Coordinator requires configured workspace-write; effective policy was not changed", "environment")
    catalog, cursor, seen = {}, None, set()
    for _ in range(20):
        params = {"includeHidden": True, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        page = server.rpc("model/list", params)
        catalog.update({r["model"]: {e["reasoningEffort"] for e in r["supportedReasoningEfforts"]} for r in page["data"]})
        cursor = page.get("nextCursor")
        if not cursor:
            break
        if cursor in seen:
            raise RddError("Runtime model catalog pagination did not progress", "environment")
        seen.add(cursor)
    missing = [role for role, p in profiles.items() if p["effort"] not in catalog.get(p["model"], set())]
    if cursor or missing:
        raise RddError("Runtime does not advertise required model/effort profiles: " + ", ".join(missing), "environment")
    account = server.rpc("account/read", {"refreshToken": False})
    if account.get("requiresOpenaiAuth") and account.get("account") is None:
        raise RddError("Codex authentication is required; log in before starting the workflow", "environment")


def attach(controller, stage, launch_id):
    """First coordinator action: bind runtime-provided identity, not a supplied ID."""
    if stage not in STAGES or not _uuid(launch_id):
        raise RddError("workflow attach requires STAGE and its launch UUID", "environment")
    tid = os.environ.get("CODEX_THREAD_ID")
    if not _uuid(tid):
        raise RddError("workflow attach requires a native CODEX_THREAD_ID", "environment")
    check_failure(controller.root)
    controller.guard_source_write()
    with operation_lock(controller.root):
        state = controller.state(allow_blocked=True)
        controller.guard_run_policy(state)
        row = state.get("workflow_runtime", {}).get(stage, {})
        if (row.get("backend") != "tui" or row.get("launch_id") != launch_id
                or row.get("connection") != "starting" or (row.get("thread_id") and row["thread_id"] != tid)):
            raise RddError("TUI attachment does not match the pending launch and recorded session", "environment")
        # A copied old launch packet must not attach after its driver has gone.
        try:
            with operation_lock(controller.root, workflow=True):
                pass
        except RddError as exc:
            if str(exc) != "Another workflow driver is running":
                raise
        else:
            raise RddError("TUI launch no longer has an active driver", "environment")
        with controller.store.edit(state["id"]) as current:
            current["workflow_runtime"][stage].update(thread_id=tid, connection="connected")
            validate_runtime(controller, current)
        if stage != "specification":
            register_headless(controller.root, state["id"], stage, tid)
        return {"stage": stage, "run_id": state["id"], "thread_id": tid, "attached": True,
                "provenance": "Runtime-provided shell identity, not backend-model attestation."}


class NativeTui:
    """An owned foreground TUI process; no turn timeout or model event loop."""
    def preflight(self):
        self.table = ProcessTable.preflight()

    def run(self, argv, root, poll):
        process = tree = None
        fd, foreground = None, None
        try:
            if os.name == "posix":
                fd = sys.stdin.fileno()
                foreground = os.tcgetpgrp(fd)
            process = subprocess.Popen(argv, cwd=root, shell=False,
                **({"process_group": 0} if os.name == "posix" else {}))
            tree = OwnedProcessTree(process, self.table)
            if fd is not None:
                self.foreground(fd, process.pid)
                os.killpg(process.pid, signal.SIGCONT)
            while True:
                tree.observe()
                poll()
                try:
                    return process.wait(timeout=.2)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            primary = sys.exc_info()[1]
            try:
                if tree is not None:
                    tree.close()
                elif process is not None:
                    self._close_direct_child(process)
            except (RddError, OSError, subprocess.SubprocessError) as cleanup:
                if tree is not None and process is not None:
                    try:
                        if process.poll() is None:
                            self._close_direct_child(process)
                    except (RddError, OSError, subprocess.SubprocessError) as direct_cleanup:
                        cleanup.args = (f"{cleanup}. Direct TUI cleanup: {direct_cleanup}",)
                if primary is None:
                    raise
                primary.args = (f"{primary}. TUI cleanup: {cleanup}",)
            finally:
                cleanup_primary = sys.exc_info()[1] or primary
                if fd is not None and foreground is not None:
                    try:
                        self.foreground(fd, foreground)
                    except (OSError, ValueError) as cleanup:
                        if cleanup_primary is None:
                            raise
                        cleanup_primary.args = (f"{cleanup_primary}. Terminal restoration: {cleanup}",)

    @staticmethod
    def _close_direct_child(process):
        # Identity inspection can fail during construction or cleanup. An
        # unreaped direct Popen child cannot have its PID reused; Popen's signal
        # methods also check/reap an already-exited child before signaling.
        # No descendant/group ownership can be inferred without observation.
        process.terminate()
        try:
            process.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=.5)
            except subprocess.TimeoutExpired as exc:
                raise RddError('Direct TUI child did not exit within cleanup bound', 'environment') from exc

    @staticmethod
    def foreground(fd, group):
        previous = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        try:
            os.tcsetpgrp(fd, group)
        finally:
            signal.signal(signal.SIGTTOU, previous)



class WorkflowRunner:
    def __init__(self, controller, *, server_factory=None, tui=None, terminal=None, emit=None):
        from .app_server import AppServer
        self.c, self.root = controller, controller.root
        self.server_factory = server_factory or AppServer
        self.tui = tui or NativeTui()
        self.terminal = terminal or (lambda: sys.stdin.isatty() and sys.stdout.isatty())
        self.emit = emit or (lambda text: print(text, file=sys.stderr, flush=True))

    def recover(self):
        with operation_lock(self.root):
            state = self.c.state(allow_blocked=True)
            if state["status"] == "blocked" or any(t.get("integration", {}).get("status") == "pending"
                    or (t.get("status") == "claimed" and (t.get("lease_expires") or 0) < time.time()) for t in state["tasks"].values()):
                self.c.resume()
            for node, row in self.c.state().get("workflow_nodes", {}).items():
                if row.get("status") == "claimed" and row["claim"]["expires"] < time.time():
                    self.c.workflow_release(node, "Expired authoring lease recovered by workflow command; outputs and attempts preserved")

    def run(self, stage, mode=None):
        with headless_scope(self.root, stage):
            try:
                return self._run(stage, mode)
            except RddStorageError as exc:
                record_failure(self.root, exc, stage=stage)
                raise
            except KeyboardInterrupt as exc:
                if getattr(exc, "restart_required", False):
                    raise
                return {"stage": stage, "status": "incomplete", "interrupted": True,
                        "reason": "Interrupted; preserve the run and resume its recorded session"}

    def _run(self, stage, mode):
        check_failure(self.root)
        self.c.guard_workflow(stage, mode, print_only=True)
        result = self.c.workflow_result(stage)
        check_failure(self.root)
        if mode and result["run_id"] and self.c.state(allow_blocked=True)["mode"] != mode:
            raise RddError("Existing run mode differs; use explicit start for a new run", "environment")
        if result["status"] in {"passed", "failed"}:
            return result
        if not self.terminal():
            raise RddError("Workflow execution requires a terminal; rerun the same command in a terminal. --print is read-only", "environment")
        self.c.guard_workflow(stage, mode)
        if isinstance(self.tui, NativeTui):
            self.tui.preflight()
        row = journal(self.c, stage) if result["run_id"] else {}
        if row and (row.get("backend") != "tui" or not row.get("thread_id")):
            raise RddError("Historical or uncertain coordinator session cannot be replaced by a TUI launch; preserve it and use its matching harness", "environment")
        # Reuse the transport for metadata reads only. No coordinator thread/Goal RPCs.
        with self.server_factory(self.root) as server:
            preflight(server, self.root)
            identity = dict(server.runtime_identity)
            if identity["version"] != TUI_VERSION:
                raise RddError(f"TUI workflow requires qualified Codex {TUI_VERSION}", "environment")
            if row and row["runtime"] != identity:
                raise RddError("Recorded runtime identity differs; preserve the session and use the matching executable", "environment")
        with operation_lock(self.root, workflow=True):
            self.c.guard_workflow(stage, mode)
            result = self.c.workflow_result(stage)
            if result["status"] in {"passed", "failed"}:
                return result
            if result["run_id"] is None:
                with operation_lock(self.root):
                    if git(self.root, "branch", "--show-current") == "main":
                        git(self.root, "switch", "-c", f"codex/{uuid.uuid4().hex[:12]}-baseline")
                    self.c.init()
                    self.c.start(mode or "regenerate")
            self.recover()
            row = journal(self.c, stage)
            if row:
                validate_runtime(self.c, self.c.state())
                if row.get("backend") != "tui" or not row.get("thread_id") or row["runtime"] != identity:
                    raise RddError("Coordinator identity changed during preflight; preserve the run", "environment")
            packet = launch_packet(self.c, stage, mode)
            launch_id = str(uuid.uuid4())
            update_runtime(self.c, stage, backend="tui", launch_id=launch_id,
                requested_runtime=packet["requested_runtime"], runtime=identity,
                connection="starting", readonly=row.get("readonly", {}))
            if stage != "specification":
                register_headless(self.root, packet["run_id"], stage, row.get("thread_id"))
            prompt = (f"FIRST action, before authoring/delegation: ./rdd workflow attach {stage} --launch-id {launch_id}. "
                      "Run this in the repository root using the native shell environment; never invent or override CODEX_THREAD_ID. "
                      "If attachment fails, stop.\n" + packet["prompt"])
            if stage == "implementation":
                self.emit("Implementation Goal (copy into the TUI only when there is no existing Goal):\n\n" + packet["goal_command"] + "\n")
                prompt += ("\nAfter attachment, inspect the native Goal. If one exists, preserve its identity, objective, accounting and genuine user pause. "
                           "Otherwise show the following command and wait for the user to paste it; do not activate a Goal or begin implementation yourself:\n" + packet["goal_command"])
            profile = load_profiles(self.root)["rdd_coordinator"]
            argv = [identity["executable"], "--no-daemon", "--cd", str(self.root), "--model", profile["model"],
                    "--config", "model_reasoning_effort=" + json.dumps(profile["effort"]),
                    "--config", "developer_instructions=" + json.dumps(profile["developer_instructions"])]
            if row.get("thread_id"):
                argv += ["resume", row["thread_id"]]
            argv.append(prompt)
            failed = False
            try:
                code = self.tui.run(argv, self.root, lambda: check_failure(self.root))
                check_failure(self.root)
                bound = journal(self.c, stage)
                if bound.get("launch_id") != launch_id or bound.get("connection") != "connected":
                    update_runtime(self.c, stage, connection="uncertain")
                    raise RddError("TUI exited before verified attachment; launch outcome is uncertain. Preserve the run; no replacement session was started", "environment")
                result = self.c.workflow_result(stage)
                update_runtime(self.c, stage, connection="accepted" if result["status"] == "passed" else "stopped")
                return {**result, "thread_id": bound["thread_id"], "tui_exit_code": code,
                        **({"interrupted": True} if code in {130, -signal.SIGINT} else {})}
            except BaseException as exc:
                failed = isinstance(exc, RddStorageError) or getattr(exc, "restart_required", False)
                if isinstance(exc, RddStorageError):
                    record_failure(self.root, exc, stage=stage)
                if not failed:
                    try:
                        bound = journal(self.c, stage)
                        update_runtime(self.c, stage, connection=("interrupted" if isinstance(exc, KeyboardInterrupt)
                            and bound.get("connection") == "connected" else "stopped" if bound.get("connection") == "connected" else "uncertain"))
                    except BaseException as cleanup:
                        preserve_primary_error(exc, cleanup, "failure journal")
                        failed = True
                raise
            finally:
                if not failed:
                    check_failure(self.root)
                    try:
                        clean(self.root)
                        with operation_lock(self.root):
                            self.c.export_run(self.root / f".rdd/evidence/workflow-{stage}-checkpoint.json")
                    except RddStorageError:
                        raise
                    except (RddError, OSError) as exc:
                        if getattr(exc, "restart_required", False):
                            raise
                        # Dirty work is preserved; it is not a portable checkpoint.
