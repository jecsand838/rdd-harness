"""Three workflow commands; model execution proposes, controller evidence accepts."""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid
import unicodedata

from .common import (RddError, RddStorageError, atomic_write, clean, digest, file_hash, git, head, operation_lock,
                     read_json, safe_path, source_digest)
from .profiles import load_profiles
from .app_server import MAX_EVENT_BYTES, MAX_EVENT_COUNT, StaleRequestError
from .storage_failure import (TerminalStorageFailure, check_failure, headless_scope, record_failure,
                              register_headless, preserve_primary_error)

STAGES = ("specification", "preparation", "implementation")
READONLY_PURPOSES = {"live": "rdd_reviewer", "execution": "rdd_reviewer", "research": "rdd_researcher"}
GOAL_STATUSES = {"active", "paused", "blocked", "complete", "budgetLimited", "usageLimited"}
TOOL = "rdd_readonly_agent"
GUIDANCE = """The workflow runner owns execution and native Goal activation. Do not launch another
coordinator or ask the user for an orchestration prompt. Use rdd_readonly_agent for
ALL reviewer/researcher sessions: live is persistent, execution is a separate final
reviewer, research is bounded advice. Do not spawn these two roles as native children:
live parent permissions override their read-only defaults. Writable specialists use
exact native agent_type and fork_turns=none, within two author slots. Return source-linked
review records through the existing controller; the runner supplies actual session IDs.
The read-only tool cannot record reviews itself. Keep reviewers independent of authors.
Include relevant controller candidate/readiness/finding facts and source/evidence paths
in each bounded review prompt; read-only sessions cannot run writing controller commands.
Do not edit harness policy. Missing permissions, external evidence, user pauses or usage
limits are recoverable stops, never success. Finish only with controller acceptance.
"""
ENVELOPE = {"type": "object", "additionalProperties": False, "required": ["kind", "message", "questions"],
    "properties": {"kind": {"type": "string", "enum": ["questions", "progress", "stopped"]},
                   "message": {"type": "string"}, "questions": {"type": "array", "maxItems": 3,
                   "items": {"type": "string", "minLength": 1}}}}
DYNAMIC_TOOL = {"type": "function", "name": TOOL, "description":
    "Request a bounded, source-linked read-only review or research session. Trusted profiles fix all runtime permissions and settings.",
    "inputSchema": {"type": "object", "additionalProperties": False, "required": ["purpose", "prompt"],
                    "properties": {"purpose": {"type": "string", "enum": list(READONLY_PURPOSES)},
                                   "prompt": {"type": "string", "minLength": 1}}}, "deferLoading": False}


def launch_packet(controller, stage, mode=None):
    locator = controller.root / ".rdd/run.json"
    run_id = read_json(locator).get("run_id") if locator.is_file() else None
    objective = controller.goal() if stage == "implementation" else (
        "Complete preparation against the frozen specification and contracts through accepted gate preparation. "
        "Follow $preparation-workflow, with independent continuous review, real readiness evidence and committed materialization. "
        "Missing external evidence or permissions leaves this objective incomplete." if stage == "preparation" else None)
    return {"stage": stage, "run_id": run_id, "mode": mode,
            "requested_runtime": controller.profile_settings("rdd_coordinator"),
            "skill": f".agents/skills/{stage}-workflow/SKILL.md", "objective": objective,
            "prompt": f"Follow ${stage}-workflow and AGENTS.md using ./rdd. "
                f"Stage={stage}; run={run_id or 'fresh'}; requirements={controller.config['requirements']}. "
                "Complete this stage's artifacts, specialist handoffs, continuous and final independent reviews, "
                "checks, commits and acceptance. Stop before the next workflow. "
                "Controller workflow_result determines success; model prose does not. "
                + ("Ask only necessary specification questions via the typed questions envelope. "
                   "Otherwise keep working and return progress or stopped with an explicit reason. "
                   "Persist actual answers in the canonical specification/decision artifacts."
                   if stage == "specification" else "Execute headlessly; do not ask routine conversational questions.")}


def validate_runtime(controller, state):
    """Backend references are recovery hints, never evidence or portable sessions."""
    runtime = state.get("workflow_runtime", {})
    if not isinstance(runtime, dict) or set(runtime) - set(STAGES):
        raise RddError("Invalid workflow runtime stages")
    sessions = set()
    for stage, row in runtime.items():
        if not isinstance(row, dict) or set(row) - {"thread_id", "requested_runtime", "runtime", "last_turn", "goal", "connection", "readonly", "pending", "driver_paused"}:
            raise RddError("Invalid workflow runtime metadata")
        if row.get("requested_runtime") != controller.profile_settings("rdd_coordinator"):
            raise RddError("Workflow runtime profile identity changed")
        if row.get("connection") not in {"starting", "connected", "interrupted", "stopped", "accepted"}:
            raise RddError("Invalid workflow connection state")
        identity = row.get("runtime", {})
        if (not isinstance(identity, dict) or set(identity) != {"version", "executable", "executable_sha256"}
                or not all(isinstance(v, str) and v for v in identity.values())):
            raise RddError("Invalid workflow executable identity")
        entries = [(row, "rdd_coordinator")]
        readonly = row.get("readonly", {})
        if not isinstance(readonly, dict) or set(readonly) - set(READONLY_PURPOSES):
            raise RddError("Invalid read-only session purposes")
        for purpose, session in readonly.items():
            if not isinstance(session, dict) or set(session) - {"thread_id", "requested_runtime", "last_turn", "packet_digest", "callback_id"}:
                raise RddError("Invalid read-only session metadata")
            callback = session.get("callback_id")
            if callback is not None and (not isinstance(callback, str) or not 0 < len(callback) <= 200):
                raise RddError("Invalid read-only callback identity")
            if session.get("requested_runtime") != controller.profile_settings(READONLY_PURPOSES[purpose]):
                raise RddError("Read-only session profile changed")
            if session.get("packet_digest") is not None and (not isinstance(session["packet_digest"], str)
                    or len(session["packet_digest"]) != 64 or any(c not in "0123456789abcdef" for c in session["packet_digest"])):
                raise RddError("Invalid read-only packet identity")
            entries.append((session, READONLY_PURPOSES[purpose]))
        for session, _ in entries:
            tid = session.get("thread_id")
            if tid is not None:
                if not isinstance(tid, str) or not tid or len(tid) > 200 or tid in sessions:
                    raise RddError("Invalid or reused workflow thread identity")
                sessions.add(tid)
            turn = session.get("last_turn")
            if turn is not None and (not isinstance(turn, str) or not turn or len(turn) > 200):
                raise RddError("Invalid workflow turn identity")
        if "driver_paused" in row and type(row["driver_paused"]) is not bool:
            raise RddError("Invalid driver pause provenance")
        goal = row.get("goal")
        if goal is not None:
            if (stage == "specification" or not isinstance(goal, dict)
                    or goal.get("threadId") != row.get("thread_id")
                    or goal.get("objective") != launch_packet(controller, stage)["objective"]
                    or goal.get("status") not in GOAL_STATUSES
                    or type(goal.get("createdAt")) is not int
                    or (goal.get("tokenBudget") is not None and (type(goal["tokenBudget"]) is not int or goal["tokenBudget"] <= 0))
                    or any(type(goal.get(k)) is not int or goal[k] < 0 for k in ("tokensUsed", "timeUsedSeconds"))):
                raise RddError("Invalid recorded native Goal identity/accounting")
        pending = row.get("pending")
        if pending is not None and (not isinstance(pending, str) or len(pending) > 200):
            raise RddError("Invalid pending runtime operation")


class ApprovalTerminal:
    """Poll only an attached terminal; no input thread or persistent permission."""
    def __init__(self):
        self.buffer = ""
        self.extended_key = False

    def available(self):
        return sys.stdin.isatty() and sys.stderr.isatty()

    def reset(self):
        self.buffer = ""
        self.extended_key = False
        if not self.available():
            return
        if os.name == "nt":
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getwch()
        else:
            import termios
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)

    def show(self, text):
        print(text, file=sys.stderr, flush=True)

    def poll(self):
        if not self.available():
            raise EOFError
        if os.name == "nt":
            import msvcrt
            if not msvcrt.kbhit():
                return None
            char = msvcrt.getwch()
            if char == "\x03":
                raise KeyboardInterrupt
            if char == "\x1a":
                raise EOFError
            if self.extended_key:
                self.extended_key = False
                return None
            if char in ("\x00", "\xe0"):
                self.extended_key = True
                return None
            if char in ("\r", "\n"):
                msvcrt.putwch("\r"); msvcrt.putwch("\n")
                value, self.buffer = self.buffer, ""
                return value
            if char == "\b":
                if self.buffer:
                    self.buffer = self.buffer[:-1]
                    for c in "\b \b":
                        msvcrt.putwch(c)
            elif char.isprintable():
                if len(self.buffer) < 32:
                    self.buffer += char
                    msvcrt.putwch(char)
                else:
                    self.buffer = "invalid input"
            return None
        import select
        if not select.select([sys.stdin.fileno()], [], [], 0)[0]:
            return None
        data = os.read(sys.stdin.fileno(), 4096)
        if not data:
            raise EOFError
        self.buffer += data.decode(sys.stdin.encoding or "utf-8", errors="replace")
        if "\n" not in self.buffer:
            if len(self.buffer) > 4096:
                self.buffer = "invalid"
            return None
        value = self.buffer.split("\n", 1)[0]
        self.buffer = ""  # Never carry pasted answers into another request.
        return value

    def close(self):
        self.buffer = ""


def approval_text(value):
    """Keep action text visible without letting terminal escapes impersonate UI."""
    text = str(value)
    return "".join((c if c == "\n" or not unicodedata.category(c).startswith("C")
                    else "\\u%04x" % ord(c)) for c in text).replace("\n", "\n  | ")


class WorkflowRunner:
    def __init__(self, controller, *, server_factory=None, ask=input, emit=print, approval_terminal=None):
        if server_factory is None:
            from .app_server import AppServer
            server_factory = AppServer
        self.c, self.root = controller, controller.root
        self.server_factory, self.ask, self.emit = server_factory, ask, emit
        self.server = None
        self.active = {}
        self.completed = {}
        self.messages = {}
        self.loaded = set()
        self.stage = None
        self.thread_id = None
        self.readonly_busy = False
        self.diagnostics = None
        self.storage_failed = False
        self.approval_terminal = approval_terminal if approval_terminal is not None else ApprovalTerminal()
        self.approvals = {}
        self.approval_display = None
        self.approval_busy = False
        self.deferred_readonly = deque()
        self.deferred_readonly_bytes = 0
        self.session_roles = {}
        self.session_cwds = {}

    def journal(self):
        return self.c.state(allow_blocked=True).get("workflow_runtime", {}).get(self.stage, {})

    def update(self, **changes):
        try:
            check_failure(self.root)
            with operation_lock(self.root):
                state = self.c.state(allow_blocked=True)
                self.c.guard_source_write(state)
                with self.c.store.edit(state["id"]) as current:
                    self.c.guard_run_policy(current)
                    row = current.setdefault("workflow_runtime", {}).setdefault(self.stage, {})
                    row.update(changes)
                    validate_runtime(self.c, current)
        except BaseException as exc:
            if isinstance(exc, RddStorageError):
                self.storage_failed = True
                record_failure(self.root, exc, stage=self.stage, thread_id=self.thread_id)
            elif getattr(exc, "restart_required", False):
                self.storage_failed = True
            raise

    def session_params(self, role, tid=None):
        profile = load_profiles(self.root)[role]
        params = {"cwd": str(self.root), "model": profile["model"],
                  "config": {"model_reasoning_effort": profile["effort"]},
                  "sandbox": profile["sandbox"], "developerInstructions": profile["developer_instructions"]}
        if role == "rdd_coordinator":
            params["developerInstructions"] += "\n" + GUIDANCE
            if tid is None:
                params["dynamicTools"] = [DYNAMIC_TOOL]
        if tid:
            params["threadId"] = tid
        else:
            params["historyMode"] = "legacy"
        return params

    @staticmethod
    def session_history(thread, tid, *, fresh=False, last_turn=None):
        # Existing paginated sessions can resume with full history on the
        # qualified runtime. Never replace them or reinterpret omitted history.
        modes = {"legacy"} if fresh else {"legacy", "paginated"}
        turns = thread.get("turns")
        if (thread.get("id") != tid or thread.get("historyMode") not in modes
                or not isinstance(turns, list)
                or any(not isinstance(t, dict) or not t.get("id")
                       or t.get("status") not in {"inProgress", "completed", "interrupted", "failed"}
                       or not isinstance(t.get("items"), list)
                       or (t["status"] != "inProgress" and t.get("itemsView", "full") != "full")
                       for t in turns)):
            raise RddError("Runtime did not return supported complete thread history; preserve the saved session and diagnostics", "environment")
        if last_turn and not any(t["id"] == last_turn for t in turns):
            raise RddError("Runtime history omits the saved last turn; preserve the session instead of repeating work", "environment")
        return turns

    def open_session(self, role, tid=None):
        response = self.server.rpc("thread/resume" if tid else "thread/start", self.session_params(role, tid))
        observed = response.get("thread", {}).get("id")
        profile = load_profiles(self.root)[role]
        expected_sandbox = "readOnly" if profile["sandbox"] == "read-only" else "workspaceWrite"
        config = self.server.effective_config
        # Defaults here are protocol defaults, not replacements passed to Codex.
        if (not observed or (tid and observed != tid) or response.get("model") != profile["model"]
                or response.get("reasoningEffort") != profile["effort"]
                or response.get("sandbox", {}).get("type") != expected_sandbox
                or response.get("approvalPolicy") != config.get("approval_policy", "on-request")
                or response.get("approvalsReviewer") != (config.get("approvals_reviewer") or "user")):
            raise RddError("App Server did not preserve requested profile/sandbox and effective approval policy", "environment")
        self.session_history(response["thread"], observed, fresh=tid is None)
        self.loaded.add(observed)
        self.session_roles[observed] = role
        self.session_cwds[observed] = str(self.root)
        return observed, response["thread"]

    def result(self):
        return self.c.workflow_result(self.stage)

    def preflight(self):
        """Read effective capabilities before creating a branch, run or thread."""
        config = self.server.effective_config
        if config.get("sandbox_mode") != "workspace-write":
            raise RddError("Coordinator requires its configured workspace-write sandbox; effective policy was not changed", "environment")
        profiles = load_profiles(self.root)
        catalog, cursor, seen = {}, None, set()
        for _ in range(20):
            params = {"includeHidden": True, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            page = self.server.rpc("model/list", params)
            catalog.update({row["model"]: {e["reasoningEffort"] for e in row["supportedReasoningEfforts"]} for row in page["data"]})
            cursor = page.get("nextCursor")
            if not cursor:
                break
            if cursor in seen:
                raise RddError("Runtime model catalog pagination did not progress", "environment")
            seen.add(cursor)
        missing = [role for role, p in profiles.items() if p["effort"] not in catalog.get(p["model"], set())]
        if cursor or missing:
            raise RddError("Runtime does not advertise required model/effort profiles: " + ", ".join(missing), "environment")
        account = self.server.rpc("account/read", {"refreshToken": False})
        if account.get("requiresOpenaiAuth") and account.get("account") is None:
            raise RddError("Codex authentication is required; authenticate locally and retry", "environment")
        # Catalog support is not inference/backend attestation. No startup request
        # can grant itself approval or cause bootstrap before the driver sees it.
        for _ in range(1000):
            message = self.server.next_event(timeout=0)
            if message is None:
                return
            self.observe(message)
            self.approval_tick()
        raise RddError("Runtime startup event stream did not quiesce", "environment")

    def pending_diagnostic(self, message):
        if self.diagnostics:
            params = message.get("params")
            params = params if isinstance(params, dict) else {}
            raw = json.dumps(message, ensure_ascii=False).encode("utf-8")
            record = {"method": message.get("method"), "request_id": message["id"],
                      "thread_id": params.get("threadId"), "turn_id": params.get("turnId"),
                      "request_digest": digest(message), "truncated": len(raw) > 65536,
                      "request": raw[:65536].decode("utf-8", errors="ignore")}
            atomic_write(self.diagnostics / "pending-request.json", json.dumps(record).encode("utf-8"))

    def approval_role(self, tid, seen=None):
        if not isinstance(tid, str) or not tid:
            raise RddError("Approval lacks a runtime thread identity", "environment")
        if tid == self.thread_id:
            self.session_cwds[tid] = str(self.root)
            return "rdd_coordinator"
        if tid in self.session_roles:
            role = self.session_roles[tid]
            if load_profiles(self.root)[role]["sandbox"] == "read-only":
                raise RddError("Approval cannot escalate a read-only reviewer or researcher", "environment")
            return role
        seen = set() if seen is None else seen
        if tid in seen or len(seen) >= 20:
            raise RddError("Approval has unverified runtime ancestry", "environment")
        seen.add(tid)
        # Metadata-only reads avoid the qualified runtime's fresh-history gap.
        thread = self.server.rpc("thread/read", {"threadId": tid, "includeTurns": False}).get("thread", {})
        source = thread.get("source", {})
        sub = source.get("subAgent", {}) if isinstance(source, dict) else {}
        spawn = sub.get("thread_spawn", {}) if isinstance(sub, dict) else {}
        role = thread.get("agentRole") or spawn.get("agent_role")
        parent = thread.get("parentThreadId") or spawn.get("parent_thread_id")
        profiles = load_profiles(self.root)
        if (thread.get("id") != tid or role not in profiles or role == "rdd_coordinator"
                or profiles[role]["sandbox"] != "workspace-write"
                or not isinstance(thread.get("cwd"), str) or not thread["cwd"]):
            raise RddError("Approval requires a verified writable specialist; unrelated/read-only sessions are blocked", "environment")
        self.approval_role(parent, seen)
        self.session_roles[tid], self.session_cwds[tid] = role, thread["cwd"]
        return role

    def approval_details(self, message, snapshot):
        params, method = message.get("params"), message["method"]
        common = {"threadId", "turnId", "itemId", "reason", "startedAtMs"}
        fields = ({"kind", "command", "cwd", "commandActions", "environmentId", "approvalId",
                   "availableDecisions", "additionalPermissions", "networkApprovalContext",
                   "proposedExecpolicyAmendment", "proposedNetworkPolicyAmendments"}
                  if method == "item/commandExecution/requestApproval" else {"grantRoot"})
        if not isinstance(params, dict) or set(params) - common - fields:
            scope = sorted(set(params) - common - fields) if isinstance(params, dict) else ["invalid params"]
            raise RddError("Unsupported approval fields: " + approval_text(", ".join(scope)), "environment")
        tid, turn, item_id = (params.get(key) for key in ("threadId", "turnId", "itemId"))
        if any(not isinstance(v, str) or not v for v in (tid, turn, item_id)):
            raise RddError("Approval lacks thread/turn/item identity", "environment")
        if self.active.get(tid) != turn:
            raise RddError("Approval is not for an active owned turn", "environment")
        role = self.approval_role(tid)
        item = snapshot.get("item")
        if (not isinstance(item, dict) or item.get("id") != item_id
                or item.get("status") != "inProgress"):
            raise RddError("Approval lacks complete correlated item context", "environment")
        if len(json.dumps([message, item], ensure_ascii=False).encode("utf-8")) > 65536:
            raise RddError("Approval details exceed the complete display limit; cannot approve truncated content", "environment")
        reason = params.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise RddError("Invalid approval reason", "environment")
        cwd = params.get("cwd") if params.get("cwd") is not None else item.get("cwd", self.session_cwds.get(tid))
        if not isinstance(cwd, str) or not cwd:
            raise RddError("Approval lacks a verified working directory", "environment")
        lines = [f"{self.stage}: permission required by {role}",
                 "Thread: " + approval_text(tid) + "; turn: " + approval_text(turn) + "; item: " + approval_text(item_id),
                 "Working directory:\n  | " + approval_text(cwd),
                 "Reason:\n  | " + approval_text(reason or "Not supplied by the runtime")]
        if method == "item/commandExecution/requestApproval":
            if params.get("kind", "command") != "command":
                raise RddError("Unsupported approval scope: terminal input (writeStdin)", "environment")
            if params.get("additionalPermissions"):
                raise RddError("Unsupported approval scope: additionalPermissions " + approval_text(json.dumps(params["additionalPermissions"])), "environment")
            if params.get("environmentId") not in (None, "local"):
                raise RddError("Unsupported approval environment: " + approval_text(params["environmentId"]), "environment")
            command = params.get("command") if params.get("command") is not None else item.get("command")
            if (item.get("type") != "commandExecution" or not isinstance(command, str) or not command
                    or not isinstance(item.get("command"), str) or command != item["command"]
                    or item.get("cwd") != cwd):
                raise RddError("Approval command or working directory mismatches its correlated item", "environment")
            lines += ["Command:\n  | " + approval_text(command)]
            network = params.get("networkApprovalContext")
            if network is not None:
                if (not isinstance(network, dict) or set(network) != {"host", "protocol"}
                        or not isinstance(network.get("host"), str) or not network["host"]
                        or network.get("protocol") not in {"http", "https", "socks5Tcp", "socks5Udp"}):
                    raise RddError("Unsupported or incomplete network approval context", "environment")
                lines += ["Network destination: " + approval_text(network["protocol"] + "://" + network["host"]),
                          "This request may release already queued connections to this destination; no future rule is granted."]
            choices = params.get("availableDecisions")
            if choices is None:
                choices = ["accept", "decline", "cancel"]
            if not isinstance(choices, list) or not choices:
                raise RddError("Approval has no supported decision list", "environment")
        else:
            if params.get("grantRoot") is not None:
                raise RddError("Unsupported approval scope: session-wide file grantRoot " + approval_text(params["grantRoot"]), "environment")
            changes = item.get("changes")
            if item.get("type") != "fileChange" or not isinstance(changes, list) or not changes:
                raise RddError("File approval lacks complete correlated patch context", "environment")
            for change in changes:
                kind = change.get("kind") if isinstance(change, dict) else None
                if (not isinstance(kind, dict) or kind.get("type") not in {"add", "delete", "update"}
                        or not isinstance(change.get("path"), str) or not change["path"]
                        or not isinstance(change.get("diff"), str)
                        or (kind.get("move_path") is not None and not isinstance(kind["move_path"], str))):
                    raise RddError("File approval has incomplete patch details", "environment")
                lines += ["File " + kind["type"] + ": " + approval_text(change["path"])]
                if kind.get("move_path") is not None:
                    lines += ["Move destination: " + approval_text(kind["move_path"])]
                lines += ["Patch:\n  | " + approval_text(change["diff"])]
            choices = ["accept", "decline", "cancel"]
        allowed = {v for v in choices if isinstance(v, str) and v in {"accept", "decline", "cancel"}}
        menu = (["[a] Approve once"] if "accept" in allowed else []) + (["[d] Deny and continue"] if "decline" in allowed else []) + ["[s] Stop workflow (default)"]
        return "\n".join(lines + [" / ".join(menu) + "; press Enter to submit:"]), allowed

    def approval_tick(self):
        if self.approval_busy:
            return
        self.approval_busy = True
        try:
            for ident, message in list(self.approvals.items()):
                if not self.server.request_pending(ident, expected=message):
                    self.approvals.pop(ident)
            if not self.approvals:
                if self.approval_display is not None:
                    self.approval_terminal.reset()
                self.approval_display = None
                return
            check_failure(self.root)
            ident, message = next(iter(self.approvals.items()))
            snapshot = self.server.request_snapshot(ident, expected=message)
            if snapshot is None:
                return
            text, allowed = self.approval_details(message, snapshot)
            if not self.approval_terminal.available():
                raise RddError(text + "\nHuman approval requires an attached terminal. Rerun the same workflow command in a terminal; no piped answer or saved approval will be used.", "environment")
            display = (ident, snapshot["revision"], digest(snapshot["item"]))
            if display != self.approval_display:
                self.approval_terminal.reset()
                self.approval_terminal.show(text)
                self.approval_display = display
            try:
                answer = self.approval_terminal.poll()
            except EOFError:
                answer = "s"
            if answer is None:
                return
            choice = answer.strip().lower() or "s"
            if choice == "s":
                # Stopping is not approval of an action. Do not dispatch a
                # potentially long reviewer callback or discard EOF on drift.
                check_failure(self.root)
                current = self.server.request_snapshot(ident, expected=message)
                if current == snapshot and "cancel" in allowed:
                    check_failure(self.root)
                    self.server.reply(ident, {"decision": "cancel"}, expected=message, revision=snapshot["revision"])
                raise RddError("Approval cancelled; workflow stopped recoverably. Rerun the same command when ready.", "environment")
            # Fake transports and real queued lifecycle events are reconciled
            # before the final atomic snapshot check. Never use a stale answer.
            for _ in range(1000):
                event = self.server.next_event(timeout=0)
                if event is None:
                    break
                self.observe(event)
            else:
                raise RddError("Approval event stream did not quiesce", "environment")
            check_failure(self.root)
            current = self.server.request_snapshot(ident, expected=message)
            if current is None or current != snapshot:
                self.approval_display = None
                self.approval_terminal.reset()
                return
            self.approval_details(message, current)
            decision = {"a": "accept", "d": "decline"}.get(choice)
            if decision not in allowed:
                self.approval_terminal.reset()
                self.approval_terminal.show("Choose only an offered option.\n" + text)
                return
            if self.stage != "specification":
                goal = self.observed_goal(allow_absent=True)
                if goal and goal.get("status") != "active":
                    raise RddError("Native Goal is " + str(goal.get("status")) + "; pending approval was not granted", "environment")
            if decision in allowed:
                check_failure(self.root)
                try:
                    self.server.reply(ident, {"decision": decision}, expected=message, revision=snapshot["revision"])
                except StaleRequestError:
                    # Only a definitely-unsent stale answer can be presented
                    # again. Timeouts/disconnects must stop even if retired.
                    self.approval_display = None
                    return
            self.approvals.pop(ident, None)
            self.approval_display = None
            self.approval_terminal.reset()
        except OSError as exc:
            raise RddError("Approval terminal unavailable; workflow stopped. A decision may already have been sent; inspect diagnostics before retrying: " + str(exc), "environment") from exc
        finally:
            self.approval_busy = False

    def observe(self, message):
        method, params = message.get("method"), message.get("params", {})
        if "id" in message and method:
            if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
                self.pending_diagnostic(message)
                if message["id"] in self.approvals:
                    raise RddError("Duplicate outstanding approval request", "environment")
                self.approvals[message["id"]] = message
                return
            if (method != "item/tool/call" or params.get("tool") != TOOL
                    or params.get("threadId") != self.thread_id or params.get("namespace") not in {None, ""}):
                self.pending_diagnostic(message)
                raise RddError(f"Runtime request {method} needs human approval or unsupported input; its scope is not supported", "environment")
            self.validate_readonly_call(message)
            if self.approval_busy or self.approvals or self.deferred_readonly:
                self.defer_readonly(message)
            else:
                self.readonly_call(message)
            return
        tid = params.get("threadId")
        if method == "turn/started":
            self.active[tid] = params["turn"]["id"]
        elif method == "turn/completed":
            turn = params["turn"]
            self.completed[(tid, turn["id"])] = turn
            self.active.pop(tid, None)
        elif method == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
            self.messages.setdefault((tid, params.get("turnId")), []).append(params["item"])
        if tid == self.thread_id and method in {"turn/started", "turn/completed"}:
            self.update(last_turn=params["turn"]["id"])
            self.emit(f"{self.stage}: {method} {params['turn']['id']}")

    def pump(self, seconds=1):
        timeout = (0 if self.deferred_readonly and not (self.readonly_busy or self.approvals)
                   else min(seconds, .1) if self.approvals else seconds)
        message = self.server.next_event(timeout=timeout)
        if message is not None:
            self.observe(message)
        self.approval_tick()
        self.dispatch_readonly()

    def defer_readonly(self, message):
        size = len(json.dumps(message, ensure_ascii=False).encode("utf-8"))
        if any(queued["id"] == message["id"] for queued, _ in self.deferred_readonly):
            raise RddError("Duplicate deferred read-only request", "environment")
        if len(self.deferred_readonly) >= MAX_EVENT_COUNT or self.deferred_readonly_bytes + size > MAX_EVENT_BYTES:
            raise RddError("Deferred read-only requests exceeded capacity; stop and reconnect", "environment")
        self.deferred_readonly.append((message, size))
        self.deferred_readonly_bytes += size

    def dispatch_readonly(self):
        # Run only from the normal pump, after approval reconciliation returns.
        # A review's nested pump can service approvals without starting a second review.
        if self.approval_busy or self.readonly_busy or self.approvals or not self.deferred_readonly:
            return
        # Goal/metadata RPCs can queue another human request after reconciliation.
        # Keep the FIFO in place so new callbacks cannot bypass older entries.
        for _ in range(1000):
            event = self.server.next_event(timeout=0)
            if event is None:
                break
            self.observe(event)
            if self.approvals:
                return
        else:
            raise RddError("Read-only dispatch event stream did not quiesce", "environment")
        while self.deferred_readonly:
            check_failure(self.root)
            message, size = self.deferred_readonly.popleft()
            self.deferred_readonly_bytes -= size
            if self.server.request_pending(message["id"], expected=message):
                self.readonly_call(message)
                return

    def wait_turn(self, tid, turn, timeout=900):
        until = time.monotonic() + timeout
        while (tid, turn) not in self.completed:
            if time.monotonic() >= until:
                raise RddError("Runtime turn deadline exceeded; same-session recovery is required", "environment")
            self.pump()
        value = self.completed[(tid, turn)]
        if value.get("status") != "completed":
            raise RddError(f"Runtime turn ended {value.get('status')}; controller acceptance remains incomplete", "environment")
        items = self.messages.get((tid, turn), value.get("items", []))
        finals = [x["text"] for x in items if x.get("type") == "agentMessage" and x.get("phase") != "commentary"]
        return finals[-1] if finals else ""

    def start_turn(self, tid, prompt, schema=None):
        params = {"threadId": tid, "input": [{"type": "text", "text": prompt}]}
        if schema:
            params["outputSchema"] = schema
        response = self.server.rpc("turn/start", params)
        turn = response["turn"]["id"]
        self.active[tid] = turn
        return turn

    def validate_readonly_call(self, message):
        args = message["params"].get("arguments")
        callback = message["params"].get("callId")
        if (self.readonly_busy or not isinstance(args, dict) or set(args) != {"purpose", "prompt"}
                or not isinstance(callback, str) or not 0 < len(callback) <= 200
                or args.get("purpose") not in READONLY_PURPOSES or not isinstance(args.get("prompt"), str)
                or not 0 < len(args["prompt"]) <= self.c.config["limits"]["max_packet_characters"]):
            raise RddError("Invalid or recursive read-only agent request", "environment")
        return args, callback

    def readonly_call(self, message):
        args, callback = self.validate_readonly_call(message)
        check_failure(self.root)
        if not self.server.request_pending(message["id"], expected=message):
            return
        purpose, role = args["purpose"], READONLY_PURPOSES[args["purpose"]]
        state = self.c.state(allow_blocked=True)
        authors = sum(row.get("status") == "claimed" for row in state.get("workflow_nodes", {}).values())
        authors += sum(row.get("status") == "claimed" for row in state["tasks"].values())
        if authors > (2 if purpose == "live" else 1):
            raise RddError("Release an author slot before requesting a second reviewer or researcher", "environment")
        self.readonly_busy = True
        try:
            sessions = self.journal().get("readonly", {})
            session = sessions.get(purpose)
            if session is not None and not session.get("thread_id"):
                raise RddError("Read-only session creation was interrupted; preserve diagnostics, do not replace its identity", "environment")
            if session is None:
                sessions[purpose] = {"requested_runtime": self.c.profile_settings(role)}
                self.update(readonly=sessions)
            tid = session.get("thread_id") if session else None
            if tid not in self.loaded:
                tid, thread = self.open_session(role, tid)
                old = self.session_history(thread, tid, last_turn=sessions[purpose].get("last_turn"))
                sessions[purpose]["thread_id"] = tid
                self.update(readonly=sessions)
            else:
                thread = self.server.rpc("thread/read", {"threadId": tid, "includeTurns": True})["thread"]
                old = self.session_history(thread, tid, last_turn=sessions[purpose].get("last_turn"))
            packet = {"run_id": state["id"], "stage": self.stage, "source_commit": head(self.root),
                      "source_digest": source_digest(self.root), "review_cursor": len(state.get("live_reviews", [])),
                      "controller_digest": digest({k: v for k, v in state.items() if k != "workflow_runtime"}),
                      "evidence_digest": self.evidence_identity(state),
                      "spec_digest": state.get("spec_digest"), "plan_digest": state.get("plan_digest"),
                      "instruction": args["prompt"]}
            prompt = ("Read-only RDD snapshot. Inspect referenced source and raw evidence independently. "
                "Do not write files, run writing controller commands, spawn agents, request escalation or send external messages. "
                "Return the requested review record as text, with actual session_id=" + tid + ". "
                "The coordinator records it through the existing controller. Snapshot:\n" + json.dumps(packet))
            if len(prompt) > self.c.config["limits"]["max_packet_characters"]:
                raise RddError("Read-only snapshot exceeds bounded packet limit", "environment")
            # Reconcile any previous callback before starting another review. A lost
            # reply must not silently create a replacement reviewer or concurrent turn.
            last = old[-1] if old else None
            text = None
            replay = (sessions[purpose].get("callback_id") == callback
                      and sessions[purpose].get("packet_digest") == digest(packet)
                      and last and sessions[purpose].get("last_turn") == last["id"])
            if last and last.get("status") == "inProgress":
                self.active[tid] = last["id"]
                completed_text = self.wait_turn(tid, last["id"])
                if replay:
                    text = completed_text
            elif last and last.get("status") == "completed" and replay:
                text = "\n".join(i["text"] for i in last.get("items", []) if i.get("type") == "agentMessage" and i.get("phase") != "commentary")
            if text is None:
                check_failure(self.root)
                if not self.server.request_pending(message["id"], expected=message):
                    return
                sessions[purpose]["packet_digest"] = digest(packet)
                sessions[purpose]["callback_id"] = callback
                self.update(readonly=sessions)
                turn = self.start_turn(tid, prompt)
                sessions[purpose]["last_turn"] = turn
                self.update(readonly=sessions)
                text = self.wait_turn(tid, turn)
            if len(text) > self.c.config["limits"]["max_packet_characters"]:
                raise RddError("Read-only report exceeds bounded packet limit", "environment")
            result = {"session_id": tid, "requested_runtime": self.c.profile_settings(role),
                      "snapshot_digest": digest(packet), "report": text,
                      "provenance": "Profile-applied read-only App Server session; no backend-model attestation."}
            check_failure(self.root)
            if self.server.request_pending(message["id"], expected=message):
                try:
                    self.server.reply(message["id"], {"contentItems": [{"type": "inputText", "text": json.dumps(result)}], "success": True}, expected=message)
                except StaleRequestError:
                    pass  # Preserve the completed review; never send it to a retired/reused request.
        finally:
            self.readonly_busy = False

    def evidence_identity(self, state):
        """Bind review snapshots to referenced raw evidence, including absent files."""
        paths = set()
        def collect(value):
            if isinstance(value, dict):
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
            elif isinstance(value, str) and value.startswith(".rdd/evidence/"):
                paths.add(value)
        collect({k: v for k, v in state.items() if k != "workflow_runtime"})
        evidence = {}
        for rel in sorted(paths):
            path = safe_path(self.root, rel)
            evidence[rel] = file_hash(path) if path.is_file() else None
        return digest(evidence)

    def recover(self):
        with operation_lock(self.root):
            state = self.c.state(allow_blocked=True)
            if state["status"] == "blocked" or any(t.get("integration", {}).get("status") == "pending"
                    or (t.get("status") == "claimed" and (t.get("lease_expires") or 0) < time.time()) for t in state["tasks"].values()):
                self.c.resume()
            for node, row in self.c.state().get("workflow_nodes", {}).items():
                if row.get("status") == "claimed" and row["claim"]["expires"] < time.time():
                    self.c.workflow_release(node, "Expired authoring lease recovered by workflow command; outputs and attempts preserved")

    def specification(self, thread, packet):
        row = self.journal()
        turns = thread.get("turns", [])
        last = turns[-1] if turns else None
        if last and last.get("status") == "completed":
            finals = [i.get("text", "") for i in last.get("items", []) if i.get("type") == "agentMessage" and i.get("phase") != "commentary"]
            try:
                if finals and json.loads(finals[-1]).get("kind") == "stopped":
                    last = None  # An explicit new command retries the known stop in this same session.
            except (ValueError, AttributeError):
                pass
        if last and last.get("status") == "inProgress":
            self.active[self.thread_id] = last["id"]
            self.update(last_turn=last["id"], pending=None)
            text = self.wait_turn(self.thread_id, last["id"])
            last = {"status": "completed", "items": [{"type": "agentMessage", "text": text}]}
        prompt = packet["prompt"]
        unchanged, previous = 0, None
        while True:
            if last and last.get("status") == "completed":
                text = "\n".join(i["text"] for i in last.get("items", []) if i.get("type") == "agentMessage" and i.get("phase") != "commentary")
                last = None
            else:
                self.update(pending="turn/start")
                turn = self.start_turn(self.thread_id, prompt, ENVELOPE)
                self.update(last_turn=turn, pending=None)
                text = self.wait_turn(self.thread_id, turn)
            result = self.result()
            if result["status"] in {"passed", "failed", "blocked"}:
                return result
            identity = digest({"source": source_digest(self.root), "state": {k: v for k, v in self.c.state().items() if k != "workflow_runtime"}})
            unchanged = unchanged + 1 if identity == previous else 0
            previous = identity
            try:
                from .common import validate
                envelope = json.loads(text)
                validate(envelope, ENVELOPE)
                if (envelope["kind"] == "questions") != bool(envelope["questions"]):
                    raise ValueError("Questions must occur only in a questions envelope")
            except (ValueError, RddError, TypeError):
                unchanged += 1
                envelope = {"kind": "progress", "message": "Return the required questions/progress/stopped envelope.", "questions": []}
            if unchanged >= self.c.config["limits"]["max_attempts"]:
                return {**result, "reason": "Repeated unchanged or malformed progress; same session preserved for diagnosis"}
            if envelope["kind"] == "stopped":
                return {**result, "reason": envelope["message"]}
            if envelope["kind"] == "questions":
                answers = []
                for question in envelope["questions"]:
                    self.emit(question)
                    try:
                        answer = self.ask("> ")
                    except EOFError as exc:
                        raise RddError("Specification needs an actual answer; rerun this command with input available", "environment") from exc
                    if not answer.strip():
                        raise RddError("An empty answer is not specification approval; rerun to answer", "environment")
                    answers.append({"question": question, "answer": answer})
                prompt = "Actual specification answers; record decisions and continue:\n" + json.dumps(answers)
            else:
                prompt = "Controller acceptance is incomplete. Continue the remaining workflow obligations. " + envelope["message"]

    def observed_goal(self, *, allow_absent=False, timeout=60):
        current = self.server.rpc("thread/goal/get", {"threadId": self.thread_id}, timeout=timeout).get("goal")
        check_failure(self.root)
        stored = self.journal().get("goal")
        if current is None:
            if allow_absent and stored is None:
                return None
            raise RddError("Recorded native Goal is unavailable; preserve accounting and session", "environment")
        if (not isinstance(current, dict) or current.get("threadId") != self.thread_id
                or current.get("objective") != launch_packet(self.c, self.stage)["objective"]
                or current.get("status") not in GOAL_STATUSES
                or type(current.get("createdAt")) is not int
                or (current.get("tokenBudget") is not None and (type(current["tokenBudget"]) is not int or current["tokenBudget"] <= 0))
                or any(type(current.get(k)) is not int or current[k] < 0 for k in ("tokensUsed", "timeUsedSeconds"))
                or (stored and (current.get("createdAt") != stored.get("createdAt")
                    or current.get("tokenBudget") != stored.get("tokenBudget")
                    or any(current[k] < stored[k] for k in ("tokensUsed", "timeUsedSeconds"))))):
            raise RddError("Native Goal identity/accounting changed or regressed; preserve last valid record", "environment")
        return current

    def goal(self, packet):
        stored = self.journal().get("goal")
        current = self.observed_goal(allow_absent=True)
        if current:
            if current.get("objective") != packet["objective"]:
                raise RddError("Stored native Goal objective differs; do not replace or reset it", "environment")
            if current.get("status") == "paused" and self.journal().get("driver_paused"):
                # A new invocation authorizes retry of our interruption, never a user pause.
                self.server.rpc("thread/goal/set", {"threadId": self.thread_id, "status": "active"})
                current = self.observed_goal()
            self.update(goal=current, pending=None, driver_paused=False)
        elif stored:
            raise RddError("Recorded native Goal is unavailable; accounting must not be reset", "environment")
        elif self.journal().get("pending"):
            raise RddError("Goal activation had an uncertain outcome; inspect this session rather than repeat its initial turn", "environment")
        else:
            # Write intent before either operation; uncertain acknowledgements require inspection.
            self.update(pending="goal/start")
            turn = self.start_turn(self.thread_id, packet["prompt"])
            self.update(last_turn=turn)
            self.server.rpc("thread/goal/set", {"threadId": self.thread_id, "objective": packet["objective"], "status": "active"})
            current = self.observed_goal()
            if current.get("objective") != packet["objective"] or current.get("status") != "active":
                raise RddError("Native Goal activation was not observed", "environment")
            self.update(goal=current, pending=None)
        previous, unchanged, last_checked = None, 0, 0
        last_activity = time.monotonic()
        seen = set()
        while True:
            if time.monotonic() - last_checked >= 2:
                result = self.result()
                if result["status"] in {"passed", "failed", "blocked"}:
                    if result["status"] == "passed" and current.get("status") == "active":
                        self.server.rpc("thread/goal/set", {"threadId": self.thread_id, "status": "complete"})
                        self.update(goal=self.observed_goal())
                    return result
                current = self.observed_goal()
                self.update(goal=current)
                last_checked = time.monotonic()
            if current.get("status") != "active":
                return {**result, "reason": "Native Goal is " + str(current.get("status")) + "; controller acceptance is incomplete"}
            before = len(self.completed)
            self.pump()
            if self.active or len(self.completed) != before:
                last_activity = time.monotonic()
            if time.monotonic() - last_activity > 60:
                return {**result, "reason": "Native Goal did not continue while idle; same-session diagnostic required"}
            for key in list(self.completed):
                if key[0] != self.thread_id or key in seen:
                    continue
                seen.add(key)
                identity = digest({"source": source_digest(self.root), "state": {k: v for k, v in self.c.state().items() if k != "workflow_runtime"}})
                unchanged = unchanged + 1 if identity == previous else 0
                previous = identity
                if unchanged >= self.c.config["limits"]["max_attempts"]:
                    return {**result, "reason": "Native Goal repeated unchanged work; session preserved"}
            # Never send a client continuation turn here: native Goals own continuation.

    def shutdown(self):
        self.deferred_readonly.clear()
        self.deferred_readonly_bytes = 0
        if not self.server:
            return
        # Independent cleanup deadlines, including after the execution deadline expired.
        failure = None
        try:
            check_failure(self.root)
        except TerminalStorageFailure as exc:
            # A child process (or cleanup behind another exception) may have
            # discovered the failure. No journal access is safe after that.
            self.storage_failed = True
            failure = exc
        try:
            if self.thread_id and self.stage != "specification":
                try:
                    # Pausing must not depend on an intact journal, even if the
                    # storage failure is first discovered during cleanup.
                    goal = self.server.rpc("thread/goal/get", {"threadId": self.thread_id}, timeout=5).get("goal")
                    if goal and goal.get("threadId") == self.thread_id and goal.get("status") == "active":
                        self.server.rpc("thread/goal/set", {"threadId": self.thread_id, "status": "paused"}, timeout=5)
                        if not self.storage_failed:
                            paused = self.observed_goal(timeout=5)
                            self.update(goal=paused, driver_paused=True)
                except RddStorageError as exc:
                    self.storage_failed = True
                    record_failure(self.root, exc, stage=self.stage, thread_id=self.thread_id)
                    failure = exc
                except BaseException as exc:
                    if getattr(exc, "restart_required", False):
                        self.storage_failed = True
                        failure = exc
                    elif not isinstance(exc, RddError):
                        raise
            for tid, turn in list(self.active.items()):
                try:
                    self.server.rpc("turn/interrupt", {"threadId": tid, "turnId": turn}, timeout=5)
                except RddError:
                    pass
        finally:
            try:
                self.server.close()
            except (RddError, OSError) as exc:
                if not self.storage_failed:
                    failure = failure or exc
            # A child can report failure after the entry guard, even when no
            # active Goal required a journal update. Check after owned cleanup.
            try:
                check_failure(self.root)
            except TerminalStorageFailure as exc:
                self.storage_failed = True
                if not getattr(failure, "restart_required", False):
                    failure = exc
        self.approvals.clear()
        self.approval_display = None
        try:
            self.approval_terminal.close()
        except OSError as exc:
            failure = failure or RddError("Approval terminal cleanup failed: " + str(exc), "environment")
        if failure:
            raise failure

    def run(self, stage, mode=None):
        self.stage = stage
        self.storage_failed = False
        self.approvals.clear()
        self.approval_display = None
        self.deferred_readonly.clear()
        self.deferred_readonly_bytes = 0
        self.session_roles.clear()
        self.session_cwds.clear()
        try:
            check_failure(self.root)
            # Scope early read-only preflight errors without writing context on
            # an otherwise mutation-free failed preflight.
            with headless_scope(self.root, stage):
                return self._run(stage, mode)
        except RddStorageError as exc:
            # Includes read-only entry checks and final export, before/after the
            # execution try/finally. Never depend on the failed DB for identity.
            self.storage_failed = True
            record_failure(self.root, exc, stage=stage, thread_id=self.thread_id)
            raise

    def _run(self, stage, mode=None):
        self.c.guard_workflow(stage, mode, print_only=True)
        result = self.result()
        if mode and result["run_id"] and self.c.state(allow_blocked=True)["mode"] != mode:
            raise RddError("Existing run mode differs; use explicit start for an intentional new run", "environment")
        if result["status"] in {"passed", "failed"}:
            return result
        self.c.guard_workflow(stage, mode)
        # Runtime preflight uses disposable diagnostics and must precede branch/run mutation.
        directory = Path(tempfile.mkdtemp(prefix="rdd-workflow-diagnostics-"))
        self.diagnostics = directory
        server = self.server_factory(self.root, log_dir=directory)
        self.server = server
        try:
            server.__enter__()
            self.preflight()
            with operation_lock(self.root, workflow=True):
                try:
                    self.c.guard_workflow(stage, mode)
                    result = self.result()  # Another completed driver may have run during preflight.
                    if result["status"] in {"passed", "failed"}:
                        return result
                    if result["run_id"] is None:
                        with operation_lock(self.root):
                            if git(self.root, "branch", "--show-current") == "main":
                                git(self.root, "switch", "-c", "codex/" + uuid.uuid4().hex[:10] + "-baseline")
                            self.c.init()
                            self.c.start(mode or "regenerate")
                    self.recover()
                    self.c.guard_workflow(stage, mode)
                    packet = launch_packet(self.c, stage, mode)
                    if stage != "specification":
                        register_headless(self.root, packet["run_id"], stage)
                    row = self.journal()
                    if row:
                        validate_runtime(self.c, self.c.state())
                        if not row.get("thread_id"):
                            raise RddError("Session creation acknowledgement is missing; preserve diagnostics instead of replacing it", "environment")
                        if row["runtime"] != server.runtime_identity:
                            raise RddError("Recorded runtime differs; resume with the qualified executable", "environment")
                    else:
                        self.update(connection="starting", requested_runtime=packet["requested_runtime"],
                                    runtime=server.runtime_identity, readonly={})
                    self.thread_id, thread = self.open_session("rdd_coordinator", row.get("thread_id"))
                    if stage != "specification":
                        register_headless(self.root, packet["run_id"], stage, self.thread_id)
                    self.session_history(thread, self.thread_id, last_turn=row.get("last_turn"))
                    self.update(thread_id=self.thread_id, connection="connected")
                    if row:
                        for turn in thread.get("turns", []):
                            if turn.get("status") == "inProgress":
                                self.active[self.thread_id] = turn["id"]
                        if row.get("pending") and not thread.get("turns") and not row.get("goal"):
                            raise RddError("Interrupted runtime request has uncertain outcome; inspect recorded session before retrying", "environment")
                    result = self.specification(thread, packet) if stage == "specification" else self.goal(packet)
                    self.update(connection="accepted" if result["status"] == "passed" else "stopped")
                    return {**result, "diagnostics": str(directory), "logs_truncated": sorted(getattr(server, "log_truncated", []))}
                except BaseException as exc:
                    if isinstance(exc, RddStorageError):
                        self.storage_failed = True
                        record_failure(self.root, exc, stage=stage, thread_id=self.thread_id)
                    elif getattr(exc, "restart_required", False):
                        self.storage_failed = True
                    if not self.storage_failed and isinstance(exc, (RddError, KeyboardInterrupt)) and self.thread_id:
                        try:
                            self.update(connection="interrupted" if isinstance(exc, KeyboardInterrupt) else "stopped")
                        except BaseException as cleanup:
                            if getattr(cleanup, "restart_required", False):
                                self.storage_failed = True
                                preserve_primary_error(exc, cleanup, "failure journal")
                            elif isinstance(exc, KeyboardInterrupt) or isinstance(cleanup, RddStorageError) or not isinstance(cleanup, RddError):
                                raise
                    if not self.storage_failed and isinstance(exc, KeyboardInterrupt):
                        return {"stage": stage, "status": "incomplete", "interrupted": True, "reason": "Interrupted; session preserved", "diagnostics": str(directory)}
                    raise
                finally:
                    primary = sys.exc_info()[1]
                    try:
                        self.shutdown()
                    except BaseException as cleanup:
                        if primary is None or (not isinstance(cleanup, RddError) and not getattr(cleanup, "restart_required", False)):
                            raise
                        preserve_primary_error(primary, cleanup, "shutdown")
                    if self.thread_id and not self.storage_failed:
                        try:
                            clean(self.root)
                            with operation_lock(self.root):
                                self.c.export_run(self.root / f".rdd/evidence/workflow-{stage}-checkpoint.json")
                        except RddStorageError:
                            self.storage_failed = True
                            raise
                        except (RddError, OSError) as exc:
                            if getattr(exc, "restart_required", False):
                                self.storage_failed = True
                                raise
                            pass  # Uncommitted work remains in place; never manufacture a portable checkpoint.
        except RddError as exc:
            truncated = sorted(getattr(server, "log_truncated", []))
            if isinstance(exc, RddStorageError) or getattr(exc, "restart_required", False):
                exc.args = (f"{exc}. Runtime diagnostics: {directory}; truncated logs: {truncated}",)
                raise
            raise RddError(f"{exc}. Runtime diagnostics: {directory}; truncated logs: {truncated}", exc.kind) from exc
        except KeyboardInterrupt as exc:
            if getattr(exc, "restart_required", False):
                raise
            return {"stage": stage, "status": "incomplete", "interrupted": True,
                    "reason": "Interrupted during runtime preflight; run was not started", "diagnostics": str(directory)}
        finally:
            primary = sys.exc_info()[1]
            try:
                server.close()
            except (RddError, OSError):
                if not isinstance(primary, RddStorageError) and not getattr(primary, "restart_required", False):
                    raise
