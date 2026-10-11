"""Public workflow execution cannot turn model/process success into acceptance."""
import copy
import unittest

import test_engine as fixture


class WorkflowResultTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.EngineTests(methodName="runTest")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.c = self.f.c

    def test_unaccepted_stage_is_readonly_and_incomplete(self):
        before = copy.deepcopy(self.c.state())
        result = self.c.workflow_result("specification")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(self.c.state(), before)

    def test_print_with_mode_cannot_start_or_replace_run(self):
        before = copy.deepcopy(self.c.state())
        packet = self.c.workflow("specification", "regenerate", print_only=True)
        self.assertEqual(packet["stage"], "specification")
        self.assertEqual(self.c.state(), before)

    def test_accepted_spec_survives_freeze_commit_and_detects_evidence_drift(self):
        self.f.stage_ready("specification")
        self.c.spec_freeze()
        self.f.commit("Commit accepted frozen specification")
        before = copy.deepcopy(self.c.state())
        result = self.c.workflow_result("specification")
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(self.c.state(), before)
        receipt = next(iter(before["checks"].values()))
        (self.f.root / receipt["log_path"]).write_text("corrupt\n", encoding="utf-8")
        self.assertEqual(self.c.workflow_result("specification")["status"], "failed")


class FakeServer:
    """Explicit isolated protocol fake; never claims native or hosted execution."""
    def __init__(self, root, log_dir=None):
        self.effective_config = dict(sandbox_mode="workspace-write", approval_policy="on-request", approvals_reviewer="user")
        self.runtime_identity = dict(version="0.161.0", executable="fixture", executable_sha256="a" * 64)
        self.calls, self.events, self.threads, self.goals = [], [], {}, {}
        self.materialized = set()
        self.on_turn = lambda thread, prompt: dict(kind="stopped", message="Fixture external evidence unavailable", questions=[])
        self.closed, self.goal_terminal = False, None
        self.fail_method = None
        self.sandbox_override = None

    def __enter__(self):
        return self

    def close(self):
        self.closed = True

    def rpc(self, method, params, timeout=60):
        from tools.rdd.common import RddError
        self.calls.append((method, copy.deepcopy(params)))
        if method == self.fail_method:
            raise RddError("Fixture backend unavailable", "environment")
        if method == "model/list":
            return dict(data=[dict(model=m, supportedReasoningEfforts=[dict(reasoningEffort=e)])
                             for m, e in (("gpt-6-astra", "ultra"), ("gpt-6.1-sol", "xhigh"), ("gpt-6-luna", "xhigh"))])
        if method == "account/read":
            return dict(requiresOpenaiAuth=True, account=dict(type="fixture"))
        if method in {"thread/start", "thread/resume"}:
            tid = params.get("threadId") or "fixture-thread-" + str(len(self.threads) + 1)
            if method == "thread/resume" and tid not in self.threads:
                raise RddError("Fixture backend session missing", "environment")
            thread = self.threads.setdefault(tid, dict(id=tid,
                historyMode=params.get("historyMode", "paginated"), turns=[]))
            return dict(thread=copy.deepcopy(thread), model=params["model"],
                reasoningEffort=params["config"]["model_reasoning_effort"], approvalPolicy="on-request", approvalsReviewer="user",
                sandbox=dict(type=self.sandbox_override or ("readOnly" if params["sandbox"] == "read-only" else "workspaceWrite")))
        if method == "thread/read":
            tid = params["threadId"]
            if tid not in self.threads:
                raise RddError("Fixture backend session missing", "environment")
            thread = copy.deepcopy(self.threads[tid])
            if params.get("includeTurns"):
                if tid not in self.materialized:
                    error = ("-32600 thread is not materialized yet" if thread.get("historyMode") == "legacy"
                             else "-32601 list_turns is not supported yet")
                    raise RddError("App Server thread/read failed: " + error, "environment")
            else:
                thread["turns"] = []
            return dict(thread=thread)
        if method == "turn/start":
            import json
            tid = params["threadId"]
            turn_id = "turn-" + str(len(self.threads[tid]["turns"]) + 1)
            value = self.on_turn(tid, params["input"][0]["text"])
            item = dict(type="agentMessage", text=json.dumps(value), phase="final_answer")
            turn = dict(id=turn_id, status="completed", items=[item])
            self.threads[tid]["turns"].append(turn)
            self.materialized.add(tid)
            self.events += [dict(method="turn/started", params=dict(threadId=tid, turn=dict(id=turn_id))),
                            dict(method="item/completed", params=dict(threadId=tid, turnId=turn_id, item=item)),
                            dict(method="turn/completed", params=dict(threadId=tid, turn=turn))]
            return dict(turn=dict(id=turn_id, status="inProgress"))
        if method == "thread/goal/set":
            tid = params["threadId"]
            value = self.goals.setdefault(tid, dict(threadId=tid, tokensUsed=0, timeUsedSeconds=0, createdAt=1, tokenBudget=None))
            value.update({k: v for k, v in params.items() if k != "threadId"})
            return dict(goal=copy.deepcopy(value))
        if method == "thread/goal/get":
            value = copy.deepcopy(self.goals.get(params["threadId"]))
            if value and self.goal_terminal:
                value["status"] = self.goal_terminal
            return dict(goal=value)
        if method == "turn/interrupt":
            return {}
        raise AssertionError(method)

    def next_event(self, timeout=1):
        return self.events.pop(0) if self.events else None

    def reply(self, request_id, result):
        self.calls.append(("reply", dict(id=request_id, result=result)))


class WorkflowExecutionTests(WorkflowResultTests):
    def setUp(self):
        super().setUp()
        from tools.rdd.workflow import WorkflowRunner
        self.f.write(".rdd/goals/implementation.txt", "Complete the synthetic fixture through verified project acceptance.\n")
        self.server = FakeServer(self.f.root)
        self.runner = WorkflowRunner(self.c, server_factory=lambda *a, **k: self.server, emit=lambda text: None)

    def snapshot(self):
        from tools.rdd.common import inventory, head
        return (copy.deepcopy(self.c.state(allow_blocked=True)), inventory(self.f.root), head(self.f.root))

    def accepted_spec(self):
        self.f.stage_ready("specification")
        self.c.spec_freeze()
        self.f.commit("Accepted fixture specification")

    def test_new_coordinator_and_readonly_sessions_request_legacy_history(self):
        self.runner.server = self.server
        for role in ("rdd_coordinator", "rdd_reviewer"):
            with self.subTest(role=role):
                tid, thread = self.runner.open_session(role)
                method, params = self.server.calls[-1]
                self.assertEqual(method, "thread/start")
                self.assertEqual(params.get("historyMode"), "legacy")
                self.assertEqual(thread["historyMode"], "legacy")
                self.assertEqual(self.server.threads[tid]["historyMode"], "legacy")

    def test_session_start_rejects_unconfirmed_legacy_history_before_turn(self):
        from tools.rdd.common import RddError
        self.runner.server = self.server
        original = self.server.rpc
        for role in ("rdd_coordinator", "rdd_reviewer"):
            for mode in (None, "paginated", "unsupported"):
                with self.subTest(role=role, mode=mode):
                    def rpc(method, params, timeout=60):
                        value = original(method, params, timeout)
                        if method == "thread/start":
                            if mode is None:
                                value["thread"].pop("historyMode", None)
                            else:
                                value["thread"]["historyMode"] = mode
                        return value
                    self.server.rpc = rpc
                    with self.assertRaisesRegex(RddError, "history"):
                        self.runner.open_session(role)
        self.assertFalse(any(method == "turn/start" for method, _ in self.server.calls))

    def test_saved_paginated_session_resumes_without_new_identity_or_turn(self):
        import json
        tid, turn_id = "saved-coordinator", "saved-question"
        envelope = dict(kind="questions", message="Saved clarification", questions=["Color?"])
        self.server.threads[tid] = dict(id=tid, historyMode="paginated", turns=[dict(
            id=turn_id, status="completed", items=[dict(type="agentMessage", phase="final_answer",
            text=json.dumps(envelope))])])
        self.server.materialized.add(tid)
        self.runner.stage = "specification"
        self.runner.update(thread_id=tid, last_turn=turn_id, connection="interrupted", readonly={},
            requested_runtime=self.c.profile_settings("rdd_coordinator"), runtime=self.server.runtime_identity)
        self.runner.ask = lambda *a: (_ for _ in ()).throw(KeyboardInterrupt())
        run_id = self.c.state()["id"]
        result = self.runner.run("specification")
        self.assertTrue(result["interrupted"])
        self.assertEqual(self.c.state()["id"], run_id)
        row = self.c.state()["workflow_runtime"]["specification"]
        self.assertEqual((row["thread_id"], row["last_turn"]), (tid, turn_id))
        resumes = [p for m, p in self.server.calls if m == "thread/resume"]
        self.assertEqual([p["threadId"] for p in resumes], [tid])
        self.assertFalse(any(m == "thread/read" and p.get("includeTurns") for m, p in self.server.calls))
        self.assertFalse(any(m in {"thread/start", "turn/start", "thread/goal/set"} for m, _ in self.server.calls))

    def test_resume_without_verified_history_preserves_session_and_goal_accounting(self):
        from tools.rdd.common import RddError
        from tools.rdd.workflow import launch_packet
        self.accepted_spec()
        tid, turn_id = "saved-goal-coordinator", "saved-goal-turn"
        self.server.threads[tid] = dict(id=tid, historyMode="paginated", turns=[dict(
            id=turn_id, status="completed", items=[])])
        self.server.materialized.add(tid)
        self.runner.stage = "preparation"
        goal = dict(threadId=tid, objective=launch_packet(self.c, "preparation")["objective"],
            status="paused", tokensUsed=37, timeUsedSeconds=8, createdAt=1, tokenBudget=None)
        self.server.goals[tid] = copy.deepcopy(goal)
        self.runner.update(thread_id=tid, last_turn=turn_id, goal=goal, connection="stopped", readonly={},
            requested_runtime=self.c.profile_settings("rdd_coordinator"), runtime=self.server.runtime_identity)
        run_id = self.c.state()["id"]
        original = self.server.rpc
        for missing in (None, "not-a-turn-list", "incomplete", "unavailable", "empty", "older-only"):
            with self.subTest(history=missing):
                def rpc(method, params, timeout=60):
                    value = original(method, params, timeout)
                    if method == "thread/resume":
                        if missing is None:
                            value["thread"].pop("turns")
                        elif missing == "incomplete":
                            value["thread"]["turns"][0]["itemsView"] = "not-full"
                        elif missing == "unavailable":
                            raise RddError("Saved thread history unavailable", "environment")
                        elif missing == "empty":
                            value["thread"]["turns"] = []
                        elif missing == "older-only":
                            value["thread"]["turns"] = [dict(id="older-turn", status="completed", items=[])]
                        else:
                            value["thread"]["turns"] = missing
                    return value
                self.server.rpc = rpc
                with self.assertRaisesRegex(RddError, "history"):
                    self.runner.run("preparation")
                row = self.c.state()["workflow_runtime"]["preparation"]
                self.assertEqual(self.c.state()["id"], run_id)
                self.assertEqual((row["thread_id"], row["last_turn"]), (tid, turn_id))
                self.assertEqual(row["goal"], goal)
                self.assertEqual(self.server.goals[tid], goal)
        self.assertFalse(any(m in {"thread/start", "turn/start", "thread/goal/set"} for m, _ in self.server.calls))

    def test_missing_runtime_fails_before_any_mutation(self):
        from tools.rdd.common import RddError
        before = self.snapshot()
        self.runner.server_factory = lambda *a, **k: (_ for _ in ()).throw(RddError("Missing runtime", "environment"))
        with self.assertRaisesRegex(RddError, "Missing runtime"):
            self.runner.run("specification", "regenerate")
        self.assertEqual(before, self.snapshot())

    def test_preflight_interruption_preserves_state_and_closes_runtime(self):
        before = self.snapshot()
        self.server.rpc = lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt())
        result = self.runner.run("specification")
        self.assertTrue(result["interrupted"])
        self.assertEqual(before, self.snapshot())
        self.assertTrue(self.server.closed)

    def test_fresh_main_bootstraps_only_after_preflight_and_reentry_keeps_run(self):
        import subprocess
        import tempfile
        from pathlib import Path
        from tools.rdd.common import RddError, git, inventory
        from tools.rdd.engine import Controller
        from tools.rdd.workflow import WorkflowRunner
        with tempfile.TemporaryDirectory(prefix="rdd-fresh-workflow-") as directory:
            root = Path(directory) / "fixture"
            subprocess.run(["git", "clone", "-q", "--no-hardlinks", "-b", "main", str(self.f.root), str(root)], check=True)
            controller = Controller(root)
            self.addCleanup(controller.close)
            server = FakeServer(root)
            runner = WorkflowRunner(controller, server_factory=lambda *a, **k: server, emit=lambda _: None)
            before = inventory(root)
            server.fail_method = "model/list"
            with self.assertRaisesRegex(RddError, "unavailable"):
                runner.run("specification", "regenerate")
            self.assertEqual(git(root, "branch", "--show-current"), "main")
            self.assertEqual(inventory(root), before)
            self.assertFalse((root / ".rdd/run.json").exists())
            server.fail_method = None
            result = runner.run("specification", "regenerate")
            self.assertEqual(result["status"], "incomplete")
            branch = git(root, "branch", "--show-current")
            self.assertRegex(branch, r"^codex/[0-9a-f]+-baseline$")
            run_id = controller.state()["id"]
            runner.run("specification", "regenerate")
            self.assertEqual(controller.state()["id"], run_id)
            self.assertEqual(git(root, "branch", "--show-current"), branch)
            self.assertEqual(len([1 for m, _ in server.calls if m == "thread/start"]), 1)

    def test_specification_interrupt_preserves_question_and_same_session(self):
        self.server.on_turn = lambda *a: dict(kind="questions", message="Need a color", questions=["Color?"])
        self.runner.ask = lambda *a: (_ for _ in ()).throw(KeyboardInterrupt())
        result = self.runner.run("specification")
        self.assertTrue(result["interrupted"])
        tid = self.runner.thread_id
        self.assertEqual(self.c.state()["workflow_runtime"]["specification"]["connection"], "interrupted")
        self.runner.ask = lambda *a: "amber"
        self.server.on_turn = lambda *a: dict(kind="stopped", message="Evidence unavailable", questions=[])
        result = self.runner.run("specification")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(self.runner.thread_id, tid)
        self.assertEqual(len([1 for m, _ in self.server.calls if m == "thread/start"]), 1)

    def test_accepted_stage_does_not_require_runtime_or_replace_run(self):
        self.accepted_spec()
        before = self.snapshot()
        self.runner.server_factory = lambda *a, **k: self.fail("Accepted reentry must not launch")
        self.assertEqual(self.runner.run("specification", "regenerate")["status"], "passed")
        self.assertEqual(before, self.snapshot())

    def test_later_environment_blocker_does_not_reopen_accepted_upstream_stages(self):
        self.f.prepared()
        self.c.phase_begin("P01")
        self.c.block("environment", "Fixture native host unavailable")
        before = self.snapshot()
        self.runner.server_factory = lambda *a, **k: self.fail("Accepted upstream stage must not launch")
        for stage in ("specification", "preparation"):
            result = self.runner.run(stage)
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual(len(result["blockers"]), 1)
        self.assertEqual(before, self.snapshot())
        self.c.block("specification", "Fixture frozen authority is invalid")
        self.assertEqual(self.c.workflow_result("specification")["status"], "blocked")

    def test_real_answer_continues_same_session_until_real_acceptance(self):
        seen = []
        self.runner.ask = lambda question: "amber"
        def turn(thread, prompt):
            seen.append((thread, prompt))
            if len(seen) == 1:
                return dict(kind="questions", message="Color needs clarification", questions=["Which color?"])
            self.assertIn('"answer": "amber"', prompt)
            self.accepted_spec()
            return dict(kind="progress", message="Specification accepted", questions=[])
        self.server.on_turn = turn
        result = self.runner.run("specification", "regenerate")
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0][0], seen[1][0])
        self.assertEqual(len([x for x in self.server.calls if x[0] == "thread/start"]), 1)
        self.assertTrue(self.server.closed)

    def test_done_prose_cannot_establish_acceptance(self):
        self.server.on_turn = lambda *a: dict(kind="stopped", message="All done, everything passed", questions=[])
        result = self.runner.run("specification")
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(self.c.state().get("spec_digest"))

    def test_repeated_unchanged_progress_is_bounded(self):
        self.server.on_turn = lambda *a: dict(kind="progress", message="Still working", questions=[])
        result = self.runner.run("specification")
        self.assertEqual(result["status"], "incomplete")
        self.assertLessEqual(len([x for x in self.server.calls if x[0] == "turn/start"]), 4)
        self.assertIn("unchanged", result["reason"])

    def test_resume_uses_exact_session_and_missing_session_stops(self):
        from tools.rdd.common import RddError
        self.runner.run("specification")
        tid = self.c.state()["workflow_runtime"]["specification"]["thread_id"]
        self.server.threads.clear()
        with self.assertRaisesRegex(RddError, "session missing"):
            self.runner.run("specification")
        starts = [x for x in self.server.calls if x[0] == "thread/start"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(self.c.state()["workflow_runtime"]["specification"]["thread_id"], tid)

    def test_qualified_version_change_cannot_migrate_saved_runtime_or_goal(self):
        from tools.rdd.common import RddError
        from tools.rdd.workflow import launch_packet
        self.accepted_spec()
        self.runner.stage, self.runner.server = "preparation", self.server
        self.runner.update(connection="stopped", requested_runtime=self.c.profile_settings("rdd_coordinator"),
                           runtime=self.server.runtime_identity, readonly={})
        tid, _ = self.runner.open_session("rdd_coordinator")
        goal = dict(threadId=tid, objective=launch_packet(self.c, "preparation")["objective"],
                    status="paused", tokensUsed=37, timeUsedSeconds=8, createdAt=1, tokenBudget=None)
        self.server.goals[tid] = copy.deepcopy(goal)
        self.runner.update(thread_id=tid, goal=goal)
        before = self.snapshot()
        self.server.calls.clear()
        self.server.runtime_identity["version"] = "0.162.1"
        with self.assertRaisesRegex(RddError, "Recorded runtime differs") as failure:
            self.runner.run("preparation")
        self.assertEqual(failure.exception.kind, "environment")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.server.goals[tid], goal)
        self.assertFalse(any(m in {"thread/start", "thread/resume", "turn/start", "thread/goal/set"}
                             for m, _ in self.server.calls))
        self.assertTrue(self.server.closed)

    def test_approval_request_is_never_answered(self):
        from tools.rdd.common import RddError
        self.server.events.append(dict(id=37, method="item/commandExecution/requestApproval", params={}))
        with self.assertRaisesRegex(RddError, "human approval"):
            self.runner.run("specification")
        self.assertFalse(any(method == "reply" for method, _ in self.server.calls))
        self.assertFalse(any(method == "thread/start" for method, _ in self.server.calls))

    def test_readonly_call_has_distinct_reviewer_sessions_and_unchanged_policy(self):
        from tools.rdd.workflow import TOOL
        # Establish the run-scoped coordinator journal through the real runner.
        self.runner.run("specification")
        for index, purpose in enumerate(("live", "live", "execution")):
            self.runner.observe(dict(id=index, method="item/tool/call", params=dict(callId=str(index),
                tool=TOOL, threadId=self.runner.thread_id, namespace=None,
                arguments=dict(purpose=purpose, prompt="Inspect docs/specs/fixture.md against FR-001"))))
        sessions = self.c.state()["workflow_runtime"]["specification"]["readonly"]
        self.assertNotEqual(sessions["live"]["thread_id"], sessions["execution"]["thread_id"])
        starts = [params for method, params in self.server.calls if method == "thread/start"]
        self.assertEqual(len(starts), 3)
        for params in starts:
            self.assertNotIn("approvalPolicy", params)
            self.assertNotIn("approvalsReviewer", params)
        for params in starts[1:]:
            self.assertEqual(params["sandbox"], "read-only")
            self.assertNotIn("dynamicTools", params)
        for tid in (sessions["live"]["thread_id"], sessions["execution"]["thread_id"]):
            calls = [(m, p) for m, p in self.server.calls if p.get("threadId") == tid]
            first_turn = next(i for i, (m, _) in enumerate(calls) if m == "turn/start")
            self.assertFalse(any(m == "thread/read" and p.get("includeTurns")
                                 for m, p in calls[:first_turn]))
        self.assertEqual(len([1 for method, _ in self.server.calls if method == "reply"]), 3)

    def test_inherited_write_sandbox_is_rejected_before_reviewer_turn(self):
        from tools.rdd.common import RddError
        from tools.rdd.workflow import TOOL
        self.runner.run("specification")
        self.server.sandbox_override = "workspaceWrite"
        turns = len([1 for method, _ in self.server.calls if method == "turn/start"])
        with self.assertRaisesRegex(RddError, "profile/sandbox"):
            self.runner.observe(dict(id=1, method="item/tool/call", params=dict(tool=TOOL,
                callId="review-1", threadId=self.runner.thread_id, arguments=dict(purpose="live", prompt="Inspect source"))))
        self.assertEqual(turns, len([1 for method, _ in self.server.calls if method == "turn/start"]))

    def test_readonly_replay_recovers_only_same_callback_and_current_evidence(self):
        from tools.rdd.workflow import TOOL
        self.runner.run("specification")
        def observe(callback):
            self.runner.observe(dict(id=callback, method="item/tool/call", params=dict(
                tool=TOOL, callId=callback, threadId=self.runner.thread_id,
                arguments=dict(purpose="live", prompt="Inspect readiness evidence"))))
        def turns():
            return len([1 for m, p in self.server.calls if m == "turn/start" and p["threadId"] != self.runner.thread_id])
        observe("first")
        self.assertEqual(turns(), 1)
        observe("first")  # A lost reply on an already-loaded session also replays.
        self.assertEqual(turns(), 1)
        reviewer = self.c.state()["workflow_runtime"]["specification"]["readonly"]["live"]["thread_id"]
        self.server.threads[reviewer]["historyMode"] = "paginated"
        self.runner.loaded.clear()  # Same callback after transport reconnection.
        observe("first")
        self.assertEqual(turns(), 1)
        self.assertEqual(self.c.state()["workflow_runtime"]["specification"]["readonly"]["live"]["thread_id"], reviewer)
        self.assertEqual(len([1 for m, _ in self.server.calls if m == "thread/start"]), 2)
        observe("second")  # A new observation never reuses an old report.
        self.assertEqual(turns(), 2)
        self.f.stage_ready("specification")
        observe("second")  # Changed controller receipt state invalidates replay.
        self.assertEqual(turns(), 3)
        receipt = next(iter(self.c.state()["checks"].values()))
        (self.f.root / receipt["log_path"]).write_text("changed raw evidence", encoding="utf-8")
        observe("second")
        self.assertEqual(turns(), 4)

    def test_readonly_history_cannot_drop_the_recorded_turn_or_replace_reviewer(self):
        from tools.rdd.common import RddError
        from tools.rdd.workflow import TOOL
        self.runner.run("specification")
        message = dict(id="review", method="item/tool/call", params=dict(
            tool=TOOL, callId="review", threadId=self.runner.thread_id,
            arguments=dict(purpose="live", prompt="Inspect recovery evidence")))
        self.runner.observe(message)
        saved = copy.deepcopy(self.c.state()["workflow_runtime"]["specification"]["readonly"])
        tid = saved["live"]["thread_id"]
        original = self.server.rpc
        starts = len([1 for m, _ in self.server.calls if m == "thread/start"])
        turns = len([1 for m, _ in self.server.calls if m == "turn/start"])
        for reconnect in (False, True):
            for history in ([], [dict(id="older-turn", status="completed", items=[])]):
                with self.subTest(reconnect=reconnect, history=history):
                    if reconnect:
                        self.runner.loaded.clear()
                    def rpc(method, params, timeout=60):
                        value = original(method, params, timeout)
                        if method in {"thread/read", "thread/resume"} and params["threadId"] == tid:
                            value["thread"]["turns"] = copy.deepcopy(history)
                        return value
                    self.server.rpc = rpc
                    with self.assertRaisesRegex(RddError, "history"):
                        self.runner.observe(message)
                    self.assertEqual(self.c.state()["workflow_runtime"]["specification"]["readonly"], saved)
                    self.assertEqual(len([1 for m, _ in self.server.calls if m == "thread/start"]), starts)
                    self.assertEqual(len([1 for m, _ in self.server.calls if m == "turn/start"]), turns)

    def test_saved_empty_reviewer_missing_backend_cannot_be_replaced(self):
        from tools.rdd.common import RddError
        from tools.rdd.workflow import TOOL
        self.server.runtime_identity["version"] = "0.162.1"
        self.runner.run("specification")
        tid, thread = self.runner.open_session("rdd_reviewer")
        self.assertEqual(thread["historyMode"], "legacy")
        self.assertEqual(thread["turns"], [])
        self.runner.update(readonly={"live": dict(thread_id=tid,
                           requested_runtime=self.c.profile_settings("rdd_reviewer"))})
        before = self.snapshot()
        self.server.threads.pop(tid)
        self.runner.loaded.clear()
        self.server.calls.clear()
        message = dict(id="review", method="item/tool/call", params=dict(
            tool=TOOL, callId="review", threadId=self.runner.thread_id,
            arguments=dict(purpose="live", prompt="Inspect recovery evidence")))
        with self.assertRaisesRegex(RddError, "backend session missing") as failure:
            self.runner.observe(message)
        self.assertEqual(failure.exception.kind, "environment")
        self.assertEqual(before, self.snapshot())
        self.assertEqual([m for m, _ in self.server.calls], ["thread/resume"])
        self.assertEqual(self.server.calls[0][1]["threadId"], tid)
        self.assertFalse(self.runner.readonly_busy)

    def test_late_approval_preserves_context_even_after_log_truncation(self):
        from tools.rdd.common import RddError, read_json
        def turn(*args):
            self.server.log_truncated = {"stdout"}
            self.server.events.append(dict(id=88, method="item/commandExecution/requestApproval",
                params=dict(threadId=self.runner.thread_id, turnId="turn-1", command="git commit", reason="Protected Git metadata")))
            return dict(kind="progress", message="waiting", questions=[])
        self.server.on_turn = turn
        with self.assertRaisesRegex(RddError, "truncated logs.*stdout"):
            self.runner.run("specification")
        record = read_json(self.runner.diagnostics / "pending-request.json")
        self.assertEqual(record["request_id"], 88)
        self.assertIn("git commit", record["request"])
        self.assertFalse(record["truncated"])
        self.assertFalse(any(m == "reply" for m, _ in self.server.calls))
        self.assertEqual(len([1 for m, _ in self.server.calls if m == "turn/start"]), 1)

    def test_runtime_checkpoint_rejects_reused_review_session(self):
        from tools.rdd.common import RddError
        from tools.rdd.workflow import validate_runtime
        self.runner.run("specification")
        state = copy.deepcopy(self.c.state())
        row = state["workflow_runtime"]["specification"]
        row["readonly"] = {"live": dict(thread_id=row["thread_id"], requested_runtime=self.c.profile_settings("rdd_reviewer"))}
        with self.assertRaisesRegex(RddError, "reused"):
            validate_runtime(self.c, state)

    def test_driver_lock_excludes_duplicate_but_allows_controller_mutation(self):
        from tools.rdd.common import operation_lock, RddError
        with operation_lock(self.f.root, workflow=True):
            with operation_lock(self.f.root):
                pass
            with self.assertRaisesRegex(RddError, "workflow driver"):
                with operation_lock(self.f.root, workflow=True):
                    pass

    def test_blocked_specification_cannot_launch_implementation(self):
        from tools.rdd.common import RddError
        self.c.block("environment", "Fixture missing tool")
        before = self.snapshot()
        with self.assertRaisesRegex(RddError, "accepted preparation"):
            self.runner.run("implementation")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.server.calls, [])

    def test_preparation_runs_headlessly_to_real_local_gate_with_fake_external_evidence(self):
        from tools.rdd.common import write_json
        self.accepted_spec()
        def turn(thread, prompt):
            self.f.plan["spec_digest"] = self.c.state()["spec_digest"]
            self.c.plan_init()
            write_json(self.f.root / ".rdd/plan/plan.json", self.f.plan)
            self.f.stage_ready("plan")
            self.c.plan_freeze()
            self.c.prepare()
            self.f.commit("Materialized fixture")
            self.f.stage_ready("preparation", ci=True)  # Explicit fixture CI/GitHub adapters.
            self.c.gate_preparation()
            return dict(kind="progress", message="accepted", questions=[])
        self.server.on_turn = turn
        self.runner.ask = lambda *a: self.fail("Preparation must not request routine input")
        result = self.runner.run("preparation")
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(len([1 for m, _ in self.server.calls if m == "turn/start"]), 1)
        self.assertEqual(self.server.goals[self.runner.thread_id]["status"], "complete")

    def test_implementation_uses_real_fixture_tasks_and_gates_without_client_continuations(self):
        self.f.prepared()
        def turn(thread, prompt):
            self.c.phase_begin("P01")
            self.f.live_review()
            self.f.implement_all()
            self.f.review()
            self.c.gate_phase("P01")
            self.c.stack_publish("P01")  # Fake GitHub boundary; no external publication.
            self.c.phase_seal("P01")
            self.c.gate_project()
            return dict(kind="progress", message="accepted", questions=[])
        self.server.on_turn = turn
        self.runner.ask = lambda *a: self.fail("Implementation must not request routine input")
        result = self.runner.run("implementation")
        self.assertEqual(result["status"], "passed", result)
        self.assertTrue(result["application_complete"])
        self.assertEqual(len([1 for m, _ in self.server.calls if m == "turn/start"]), 1)
        before = self.snapshot()
        for stage in ("specification", "preparation", "implementation"):
            self.assertEqual(self.runner.run(stage)["status"], "passed")
        self.assertEqual(before, self.snapshot())
        receipt = next(r for r in self.c.state()["checks"].values() if r["check_id"] == "behavior" and r["outcome"] == "pass")
        (self.f.root / receipt["log_path"]).unlink()
        self.assertEqual(self.c.workflow_result("implementation")["status"], "failed")

    def test_goal_completion_without_acceptance_is_not_success(self):
        self.accepted_spec()
        original = self.server.rpc
        seen = 0
        def rpc(method, params, timeout=60):
            nonlocal seen
            value = original(method, params, timeout)
            if method == "thread/goal/get" and value.get("goal"):
                seen += 1
                if seen >= 2:
                    value["goal"]["status"] = "complete"
            return value
        self.server.rpc = rpc
        result = self.runner.run("preparation")
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("complete", result["reason"])
        self.assertNotIn("preparation_gate", self.c.state())

    def test_existing_user_paused_goal_is_not_reactivated(self):
        from tools.rdd.workflow import launch_packet
        self.accepted_spec()
        self.runner.stage = "preparation"
        self.runner.server = self.server
        self.runner.update(connection="connected", requested_runtime=self.c.profile_settings("rdd_coordinator"),
                           runtime=self.server.runtime_identity, readonly={})
        tid, _ = self.runner.open_session("rdd_coordinator")
        self.runner.thread_id = tid
        goal = dict(threadId=tid, objective=launch_packet(self.c, "preparation")["objective"],
                    status="paused", tokensUsed=37, timeUsedSeconds=8, createdAt=1, tokenBudget=None)
        self.server.goals[tid] = goal
        self.runner.update(thread_id=tid, goal=goal)
        result = self.runner.run("preparation")
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(any(m in {"thread/goal/set", "turn/start"} for m, _ in self.server.calls))
        self.assertEqual(self.server.goals[tid]["tokensUsed"], 37)
        calls = len(self.server.calls)
        self.assertEqual(self.runner.run("preparation")["status"], "incomplete")
        self.assertFalse(any(m in {"thread/goal/set", "turn/start"} for m, _ in self.server.calls[calls:]))
        self.assertEqual(self.server.goals[tid], goal)
        self.assertFalse((self.f.root / ".rdd/runtime/failures/fixture-run.json").exists())

    def test_corrupt_prerequisite_evidence_stops_before_runtime_and_mutation(self):
        from tools.rdd.common import RddError
        self.accepted_spec()
        receipt = next(iter(self.c.state()["checks"].values()))
        (self.f.root / receipt["log_path"]).write_text("corrupt", encoding="utf-8")
        before = self.snapshot()
        with self.assertRaises(RddError):
            self.runner.run("preparation")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.server.calls, [])

    def test_midrun_missing_goal_preserves_accounting_and_cannot_recreate(self):
        from tools.rdd.common import RddError
        self.accepted_spec()
        original, reads = self.server.rpc, 0
        def rpc(method, params, timeout=60):
            nonlocal reads
            value = original(method, params, timeout)
            if method == "thread/goal/get" and value.get("goal"):
                reads += 1
                if reads > 1:
                    return dict(goal=None)
            return value
        self.server.rpc = rpc
        with self.assertRaisesRegex(RddError, "unavailable"):
            self.runner.run("preparation")
        recorded = copy.deepcopy(self.c.state()["workflow_runtime"]["preparation"]["goal"])
        self.assertEqual(recorded["status"], "active")
        with self.assertRaisesRegex(RddError, "unavailable"):
            self.runner.run("preparation")
        self.assertEqual(self.c.state()["workflow_runtime"]["preparation"]["goal"], recorded)
        self.assertEqual(len([1 for m, p in self.server.calls if m == "thread/goal/set" and "objective" in p]), 1)
        self.assertEqual(len([1 for m, _ in self.server.calls if m == "turn/start"]), 1)

    def test_goal_observation_rejects_regression_without_overwriting_record(self):
        from tools.rdd.common import RddError
        from tools.rdd.workflow import launch_packet
        self.accepted_spec()
        self.runner.stage, self.runner.server = "preparation", self.server
        self.runner.update(connection="connected", requested_runtime=self.c.profile_settings("rdd_coordinator"),
                           runtime=self.server.runtime_identity, readonly={})
        tid, _ = self.runner.open_session("rdd_coordinator")
        self.runner.thread_id = tid
        goal = dict(threadId=tid, objective=launch_packet(self.c, "preparation")["objective"],
                    status="active", tokensUsed=37, timeUsedSeconds=8, createdAt=1, tokenBudget=None)
        self.runner.update(thread_id=tid, goal=goal)
        for field, invalid in (("tokensUsed", 36), ("timeUsedSeconds", 7), ("createdAt", 2), ("tokenBudget", 100)):
            with self.subTest(field=field):
                self.server.goals[tid] = {**goal, field: invalid}
                with self.assertRaisesRegex(RddError, "identity/accounting"):
                    self.runner.observed_goal()
                self.assertEqual(self.c.state()["workflow_runtime"]["preparation"]["goal"], goal)
        self.server.goals[tid] = {**goal, "tokensUsed": 38}
        self.assertEqual(self.runner.observed_goal()["tokensUsed"], 38)

    def test_checkpoint_roundtrip_preserves_runtime_references(self):
        from tools.rdd.common import read_json
        self.runner.run("specification")
        self.f.commit("Checkpoint fixture draft")
        path = self.f.root / ".rdd/evidence/runtime-checkpoint.json"
        self.c.export_run(path)
        before = read_json(path)["state"]["workflow_runtime"]
        self.c.resume(path)
        self.assertEqual(self.c.state()["workflow_runtime"], before)

    def test_journal_updates_preserve_real_child_controller_mutations(self):
        from pathlib import Path
        import subprocess
        import sys
        entry = Path(__file__).resolve().parents[2] / "tools/rdd/cli.py"
        self.runner.stage = "specification"
        self.runner.update(connection="starting", readonly={}, runtime=self.server.runtime_identity,
                           requested_runtime=self.c.profile_settings("rdd_coordinator"))
        for session in ("child-author-one", "child-author-two"):
            self.runner.journal()  # Previously dropped the persistent parent's SQLite lock.
            child = subprocess.run([sys.executable, "-B", str(entry), "--root", str(self.f.root),
                "author", "record", "--stage", "specification", "--session-id", session],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        self.runner.update(connection="stopped")
        state = self.c.state()
        self.assertEqual(state["authors"]["specification"], ["child-author-one", "child-author-two"])
        self.assertEqual(state["workflow_runtime"]["specification"]["connection"], "stopped")

    def test_storage_failure_in_readonly_callback_does_not_retry_or_replace_checkpoint(self):
        import sqlite3
        from unittest.mock import patch
        from tools.rdd.common import RddError, RddStorageError
        checkpoint = self.f.root / ".rdd/evidence/workflow-specification-checkpoint.json"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(b"preserved checkpoint\n")
        error = RddStorageError("begin", self.c.store.path, sqlite3.DatabaseError("fixture malformed"))
        seen = {}

        def callback_failure(thread, packet):
            seen["state"] = copy.deepcopy(self.c.state())
            self.runner.active[self.runner.thread_id] = "active-fixture-turn"
            with patch.object(self.c.store, "edit", side_effect=error) as edit:
                try:
                    self.runner.readonly_call(dict(id=7, params=dict(callId="failing-review",
                        arguments=dict(purpose="live", prompt="Review fixture handoff"))))
                finally:
                    seen["edits"] = edit.call_count

        def close_failure():
            self.server.closed = True
            raise RddError("secondary runtime cleanup failure", "environment")

        with patch.object(self.runner, "specification", side_effect=callback_failure), \
                patch.object(self.c, "export_run") as export, \
                patch.object(self.server, "close", side_effect=close_failure):
            with self.assertRaisesRegex(RddStorageError, "fixture malformed") as caught:
                self.runner.run("specification")
        self.assertIs(caught.exception, error)
        export.assert_not_called()
        self.assertEqual(seen["edits"], 1)
        self.assertEqual(self.c.state(), seen["state"])
        self.assertEqual(checkpoint.read_bytes(), b"preserved checkpoint\n")
        self.assertTrue(self.runner.storage_failed)
        self.assertTrue(self.server.closed)
        self.assertTrue(any(m == "turn/interrupt" for m, _ in self.server.calls))
        self.assertFalse(any(m == "reply" for m, _ in self.server.calls))

    def test_storage_failure_shutdown_pauses_goal_without_database_access(self):
        from unittest.mock import patch
        self.runner.server, self.runner.stage = self.server, "preparation"
        self.runner.thread_id, self.runner.storage_failed = "saved-thread", True
        self.runner.active = {"saved-thread": "saved-turn"}
        goal = dict(threadId="saved-thread", objective="Keep saved objective", status="active",
                    tokensUsed=123, timeUsedSeconds=45, createdAt=1, tokenBudget=1000)
        self.server.goals["saved-thread"] = copy.deepcopy(goal)
        with patch.object(self.c, "state", side_effect=AssertionError("No storage access in cleanup")), \
                patch.object(self.runner, "update", side_effect=AssertionError("No cleanup journal write")):
            self.runner.shutdown()
        self.assertEqual(self.server.goals["saved-thread"], {**goal, "status": "paused"})
        self.assertTrue(self.server.closed)
        self.assertEqual([m for m, _ in self.server.calls],
                         ["thread/goal/get", "thread/goal/set", "turn/interrupt"])

    def terminal_headless_failure(self, stage, *, cleanup=None):
        """Fail after activation, when native Goal accounting is already durable."""
        import sqlite3
        from unittest.mock import patch
        from tools.rdd.common import RddError, RddStorageError
        if stage == "preparation":
            self.accepted_spec()
        else:
            self.f.prepared()
        original_rpc, original_result = self.server.rpc, self.runner.result
        error = RddStorageError("read", self.c.store.path, sqlite3.DatabaseError("terminal fixture fault"))
        observed = {}

        def accounted_rpc(method, params, timeout=60):
            if self.runner.storage_failed and cleanup == "missing-goal" and method == "thread/goal/get":
                self.server.calls.append((method, copy.deepcopy(params)))
                return dict(goal=None)
            if self.runner.storage_failed and cleanup == "pause-failure" and method == "thread/goal/set":
                self.server.calls.append((method, copy.deepcopy(params)))
                raise RddError("secondary Goal cleanup failure", "environment")
            value = original_rpc(method, params, timeout)
            if method == "thread/goal/set" and "objective" in params:
                self.server.goals[params["threadId"]].update(tokensUsed=123, timeUsedSeconds=45)
            return value

        def failed_result():
            if self.runner.thread_id in self.server.goals:
                observed["state"] = copy.deepcopy(self.c.state())
                observed["goal"] = copy.deepcopy(self.server.goals[self.runner.thread_id])
                raise error
            return original_result()

        self.server.rpc = accounted_rpc
        checkpoint = self.f.root / f".rdd/evidence/workflow-{stage}-checkpoint.json"
        checkpoint.write_bytes(b"preserved prior checkpoint\n")
        with patch.object(self.runner, "result", side_effect=failed_result), \
                patch.object(self.c, "export_run") as export:
            with self.assertRaises(RddStorageError) as caught:
                self.runner.run(stage)
        self.assertIs(caught.exception, error)
        export.assert_not_called()
        self.assertEqual(self.c.state(allow_blocked=True), observed["state"])
        expected_status = "paused" if cleanup is None else "active"
        self.assertEqual(self.server.goals[self.runner.thread_id], {**observed["goal"], "status": expected_status})
        self.assertEqual(checkpoint.read_bytes(), b"preserved prior checkpoint\n")
        self.assertTrue(self.server.closed)
        observed["error"] = error
        return observed

    def assert_terminal_retry(self, stage, observed):
        from unittest.mock import patch
        from tools.rdd.common import RddError, read_json
        from tools.rdd.engine import Controller
        from tools.rdd.workflow import WorkflowRunner
        run_id = observed["state"]["id"]
        marker = self.f.root / f".rdd/runtime/failures/{run_id}.json"
        self.assertTrue(marker.is_file(), "A storage abort must survive a new process outside SQLite")
        saved = read_json(marker)
        self.assertEqual(saved["run_id"], run_id)
        self.assertEqual(saved["stage"], stage)
        self.assertEqual(saved["thread_id"], self.runner.thread_id)
        before = self.snapshot()
        marker_bytes = marker.read_bytes()
        fresh = Controller(self.f.root)
        self.addCleanup(fresh.close)
        with patch.object(fresh, "save") as save, patch.object(fresh, "export_run") as export, \
                patch.object(fresh, "workflow_result") as acceptance:
            factory = unittest.mock.Mock(side_effect=AssertionError("Terminal retry must stop before runtime"))
            runner = WorkflowRunner(fresh, server_factory=factory, emit=lambda text: None)
            with self.assertRaises(RddError) as caught:
                runner.run(stage)
            self.assertEqual(caught.exception.kind, "environment")
            self.assertRegex(str(caught.exception), "fresh|new|terminal")
            factory.assert_not_called()
            save.assert_not_called()
            export.assert_not_called()
            acceptance.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(marker.read_bytes(), marker_bytes)
        if "goal" in observed:
            self.assertEqual(self.server.goals[self.runner.thread_id], {**observed["goal"], "status": "paused"})

    def test_preparation_storage_abort_survives_shutdown_and_fresh_runner_retry(self):
        self.assert_terminal_retry("preparation", self.terminal_headless_failure("preparation"))

    def test_implementation_storage_abort_survives_shutdown_and_fresh_runner_retry(self):
        self.assert_terminal_retry("implementation", self.terminal_headless_failure("implementation"))

    def test_storage_abort_preserves_primary_when_goal_disappears_during_cleanup(self):
        observed = self.terminal_headless_failure("preparation", cleanup="missing-goal")
        self.assertEqual(self.c.state(allow_blocked=True), observed["state"])
        self.assertTrue((self.f.root / ".rdd/runtime/failures/fixture-run.json").is_file())
        self.assertEqual(len([p for m, p in self.server.calls if m == "thread/goal/set"]), 1)

    def test_storage_abort_preserves_primary_when_goal_pause_fails(self):
        observed = self.terminal_headless_failure("preparation", cleanup="pause-failure")
        self.assertEqual(self.c.state(allow_blocked=True), observed["state"])
        self.assertTrue((self.f.root / ".rdd/runtime/failures/fixture-run.json").is_file())

    def test_storage_abort_preserves_primary_when_terminal_marker_write_fails(self):
        from unittest.mock import patch
        from tools.rdd.storage_failure import atomic_write
        def marker_fault(path, data):
            if path.parent.name == "failures":
                raise OSError("marker disk full")
            return atomic_write(path, data)
        with patch("tools.rdd.storage_failure.atomic_write", side_effect=marker_fault):
            observed = self.terminal_headless_failure("preparation")
        self.assertEqual(self.c.state(allow_blocked=True), observed["state"])
        self.assertTrue(observed["error"].restart_required)
        self.assertIn("marker disk full", str(observed["error"]))
        self.assertFalse((self.f.root / ".rdd/runtime/failures/fixture-run.json").exists())

    def test_early_storage_abort_prevents_runtime_and_persists_terminal_identity(self):
        import sqlite3
        from unittest.mock import patch
        from tools.rdd.common import RddStorageError
        self.accepted_spec()
        before = self.snapshot()
        error = RddStorageError("read", self.c.store.path, sqlite3.DatabaseError("early fixture fault"))
        with patch.object(self.c, "guard_workflow", side_effect=error):
            with self.assertRaises(RddStorageError) as caught:
                self.runner.run("preparation")
        self.assertIs(caught.exception, error)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.server.calls, [])
        self.assert_terminal_retry("preparation", dict(state=before[0]))

    def test_real_child_controller_storage_failure_stops_parent_before_goal_activation(self):
        from pathlib import Path
        import subprocess
        import sys
        from tools.rdd.common import RddError, read_json
        self.accepted_spec()
        observed = {}
        script = """from pathlib import Path
import sqlite3, sys
from unittest.mock import patch
from tools.rdd.engine import Controller
from tools.rdd.common import RddStorageError
c = Controller(Path(sys.argv[1]))
try:
    with patch('tools.rdd.common.sqlite3.connect', side_effect=sqlite3.DatabaseError('child fixture fault')):
        c.state()
except RddStorageError as error:
    print(str(error))
    sys.exit(2)
sys.exit(0)
"""

        def child_failure(thread, prompt):
            observed["state"] = copy.deepcopy(self.c.state())
            child = subprocess.run([sys.executable, "-B", "-c", script, str(self.f.root)],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
            self.assertEqual(child.returncode, 2, child.stdout + child.stderr)
            self.assertIn("child fixture fault", child.stdout)
            marker = self.f.root / ".rdd/runtime/failures/fixture-run.json"
            self.assertTrue(marker.is_file(), "A real child must communicate the terminal failure through shared evidence")
            self.assertEqual(read_json(marker)["stage"], "preparation")
            return dict(kind="stopped", message="Child storage failure", questions=[])

        self.server.on_turn = child_failure
        with self.assertRaises(RddError) as caught:
            self.runner.run("preparation")
        self.assertEqual(caught.exception.kind, "environment")
        self.assertTrue(getattr(caught.exception, "restart_required", False))
        self.assertEqual(self.c.state(allow_blocked=True), observed["state"])
        self.assertFalse(any(m == "thread/goal/set" for m, _ in self.server.calls))
        self.assertTrue(self.server.closed)

    def shutdown_child_failure_race(self, primary=None, *, publication="pause-journal"):
        """Publish after shutdown's first guard at a deterministic cleanup cut."""
        import sqlite3
        from unittest.mock import patch
        from tools.rdd.common import RddError, RddStorageError
        from tools.rdd.storage_failure import TerminalStorageFailure, record_failure
        self.accepted_spec()
        original_update = self.runner.update
        original_close = self.server.close
        observed = {}

        def goal_then_stop(packet):
            status = "paused" if publication == "close" else "active"
            goal = dict(threadId=self.runner.thread_id, objective=packet["objective"], status=status,
                tokensUsed=123, timeUsedSeconds=45, createdAt=1, tokenBudget=None)
            self.server.goals[self.runner.thread_id] = copy.deepcopy(goal)
            self.runner.active[self.runner.thread_id] = "cleanup-active-turn"
            self.runner.update(goal=goal)
            observed["goal"] = goal
            if primary is not None:
                raise primary
            return self.c.workflow_result("preparation")

        def publish_child_marker():
            self.assertFalse(self.runner.storage_failed)
            observed["state"] = copy.deepcopy(self.c.state(allow_blocked=True))
            observed["edits"] = edit.call_count
            fault = RddStorageError("read", self.c.store.path, sqlite3.DatabaseError("child shutdown race"))
            record_failure(self.f.root, fault, run_id=observed["state"]["id"],
                stage="preparation", thread_id=self.runner.thread_id)
            marker = self.f.root / ".rdd/runtime/failures/fixture-run.json"
            observed["marker"] = marker.read_bytes()

        def publish_before_pause_journal(**changes):
            if publication == "pause-journal" and changes.get("driver_paused"):
                publish_child_marker()
            return original_update(**changes)

        def close():
            original_close()
            if publication == "close" and "marker" not in observed:
                publish_child_marker()

        with patch.object(self.runner, "goal", side_effect=goal_then_stop), \
                patch.object(self.runner, "update", side_effect=publish_before_pause_journal), \
                patch.object(self.server, "close", side_effect=close), \
                patch.object(self.c.store, "edit", wraps=self.c.store.edit) as edit, \
                patch.object(self.c, "export_run") as export:
            with self.assertRaises(RddError) as caught:
                self.runner.run("preparation")
            export.assert_not_called()
            self.assertEqual(edit.call_count, observed["edits"])
        if primary is None:
            self.assertIsInstance(caught.exception, TerminalStorageFailure)
        else:
            self.assertIs(caught.exception, primary)
            self.assertIn("primary ordinary failure", str(caught.exception))
        self.assertTrue(caught.exception.restart_required)
        self.assertTrue(self.runner.storage_failed)
        self.assertTrue(self.server.closed)
        self.assertTrue(any(m == "turn/interrupt" for m, _ in self.server.calls))
        self.assertEqual(self.server.goals[self.runner.thread_id], {**observed["goal"], "status": "paused"})
        self.assertEqual(self.c.state(allow_blocked=True), observed["state"])
        self.assertEqual((self.f.root / ".rdd/runtime/failures/fixture-run.json").read_bytes(), observed["marker"])

    def test_shutdown_propagates_child_marker_published_after_initial_guard(self):
        self.shutdown_child_failure_race()

    def test_shutdown_child_marker_preserves_primary_nonstorage_error_as_terminal(self):
        from tools.rdd.common import RddError
        self.shutdown_child_failure_race(RddError("primary ordinary failure", "environment"))

    def test_shutdown_propagates_child_marker_during_close_without_active_goal(self):
        self.shutdown_child_failure_race(publication="close")

    def tagged_cleanup_failure(self, primary, *, stopped_update=False):
        """Use real Store rollback/cleanup to tag an unrelated primary error."""
        import sqlite3
        from unittest.mock import patch
        from tools.rdd import common, storage_failure
        self.accepted_spec()
        original_update = self.runner.update
        original_connect = common.sqlite3.connect
        original_write = storage_failure.atomic_write
        cause = ValueError("original primary cause")
        primary.__cause__ = cause
        observed = {}
        diagnostic = "fixture stopped journal SQLite fault" if stopped_update else "fixture SQLite cleanup fault"
        checkpoint = self.f.root / ".rdd/evidence/workflow-preparation-checkpoint.json"
        checkpoint.write_bytes(b"preserved tagged-error checkpoint\n")

        class CloseFault:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def execute(self, sql, *args, **kwargs):
                if stopped_update and sql == "BEGIN IMMEDIATE":
                    raise sqlite3.DatabaseError(diagnostic)
                return self.connection.execute(sql, *args, **kwargs)

            def close(self):
                self.connection.close()
                if not stopped_update:
                    raise sqlite3.DatabaseError(diagnostic)

        def connect(*args, **kwargs):
            return CloseFault(original_connect(*args, **kwargs))

        def marker_write(path, data):
            if path.parent.name == "failures":
                raise OSError("fixture marker publication failed")
            return original_write(path, data)

        def fail_goal(packet):
            goal = dict(threadId=self.runner.thread_id, objective=packet["objective"], status="active",
                tokensUsed=123, timeUsedSeconds=45, createdAt=1, tokenBudget=None)
            self.server.goals[self.runner.thread_id] = copy.deepcopy(goal)
            self.runner.active[self.runner.thread_id] = "tagged-active-turn"
            self.runner.update(goal=goal)
            observed["state"] = copy.deepcopy(self.c.state(allow_blocked=True))
            observed["goal"] = goal
            if stopped_update:
                self.assertFalse(getattr(primary, "restart_required", False))
                raise primary
            try:
                with patch("tools.rdd.common.sqlite3.connect", side_effect=connect), \
                        patch("tools.rdd.storage_failure.atomic_write", side_effect=marker_write):
                    with self.c.store.edit(observed["state"]["id"]):
                        raise primary
            finally:
                observed["edits"] = edit.call_count

        def update(**changes):
            if stopped_update and changes.get("connection") == "stopped":
                try:
                    with patch("tools.rdd.common.sqlite3.connect", side_effect=connect), \
                            patch("tools.rdd.storage_failure.atomic_write", side_effect=marker_write):
                        return original_update(**changes)
                finally:
                    observed["edits"] = edit.call_count
            return original_update(**changes)

        with patch.object(self.runner, "goal", side_effect=fail_goal), \
                patch.object(self.runner, "update", side_effect=update), \
                patch.object(self.c.store, "edit", wraps=self.c.store.edit) as edit, \
                patch.object(self.c, "export_run") as export:
            with self.assertRaises(type(primary)) as caught:
                self.runner.run("preparation")
            self.assertIs(caught.exception, primary)
            self.assertTrue(primary.restart_required, "Real SQLite cleanup must tag the original primary")
            self.assertIn("fixture marker publication failed", primary.persistence_error)
            self.assertIn("tagged primary body failure", str(primary))
            self.assertIn(diagnostic, str(primary))
            self.assertIn("fixture marker publication failed", str(primary))
            self.assertIs(primary.__cause__, cause)
            self.assertEqual(edit.call_count, observed["edits"], "No journal write is safe after failed SQLite cleanup")
            export.assert_not_called()
        self.assertTrue(self.runner.storage_failed)
        self.assertTrue(self.server.closed)
        self.assertEqual(self.server.goals[self.runner.thread_id], {**observed["goal"], "status": "paused"})
        self.assertTrue(any(m == "turn/interrupt" for m, _ in self.server.calls))
        self.assertEqual(self.c.state(allow_blocked=True), observed["state"])
        self.assertEqual(checkpoint.read_bytes(), b"preserved tagged-error checkpoint\n")
        self.assertFalse((self.f.root / ".rdd/runtime/failures/fixture-run.json").exists())

    def test_tagged_rdd_error_stops_storage_after_marker_publication_failure(self):
        from tools.rdd.common import RddError
        self.tagged_cleanup_failure(RddError("tagged primary body failure", "environment"))

    def test_tagged_value_error_stops_storage_after_marker_publication_failure(self):
        self.tagged_cleanup_failure(ValueError("tagged primary body failure"))

    def test_tagged_keyboard_interrupt_stops_storage_after_marker_publication_failure(self):
        self.tagged_cleanup_failure(KeyboardInterrupt("tagged primary body failure"))

    def test_stopped_update_storage_failure_tags_original_rdd_error_without_marker(self):
        from tools.rdd.common import RddError
        self.tagged_cleanup_failure(RddError("tagged primary body failure", "environment"), stopped_update=True)

    def test_storage_failure_cannot_be_reported_as_failed_acceptance(self):
        import sqlite3
        from unittest.mock import patch
        from tools.rdd.common import RddStorageError
        error = RddStorageError("read", self.c.store.path, sqlite3.DatabaseError("fixture malformed"))
        with patch.object(self.c, "state", side_effect=error):
            with self.assertRaises(RddStorageError) as caught:
                self.c.workflow_result("specification")
        self.assertIs(caught.exception, error)

    def test_storage_failure_during_shutdown_still_pauses_and_closes(self):
        import sqlite3
        from unittest.mock import patch
        from tools.rdd.common import RddStorageError
        self.runner.server, self.runner.stage = self.server, "preparation"
        self.runner.thread_id = "saved-thread"
        self.runner.active = {"saved-thread": "saved-turn"}
        self.server.goals["saved-thread"] = dict(threadId="saved-thread", status="active")
        error = RddStorageError("read", self.c.store.path, sqlite3.DatabaseError("fixture malformed"))
        with patch.object(self.c, "state", side_effect=error), patch.object(self.runner, "update") as update:
            with self.assertRaises(RddStorageError) as caught:
                self.runner.shutdown()
        self.assertIs(caught.exception, error)
        update.assert_not_called()
        self.assertTrue(self.runner.storage_failed)
        self.assertTrue(self.server.closed)
        self.assertEqual(self.server.goals["saved-thread"]["status"], "paused")
        self.assertTrue(any(m == "turn/interrupt" for m, _ in self.server.calls))
        self.assert_terminal_retry("preparation", dict(state=self.c.state(allow_blocked=True)))

    def test_storage_failure_in_checkpoint_export_is_not_silenced(self):
        import sqlite3
        from unittest.mock import patch
        from tools.rdd.common import RddStorageError
        self.f.commit("Clean fixture for shutdown export")
        error = RddStorageError("read", self.c.store.path, sqlite3.DatabaseError("fixture malformed"))
        with patch.object(self.c, "export_run", side_effect=error) as export:
            with self.assertRaises(RddStorageError) as caught:
                self.runner.run("specification")
        self.assertIs(caught.exception, error)
        export.assert_called_once()
        self.assertTrue(self.runner.storage_failed)
        self.assertTrue(self.server.closed)

    def test_storage_failure_in_check_save_cannot_become_missing_evidence(self):
        import sqlite3
        from unittest.mock import patch
        from tools.rdd.common import RddStorageError
        state = self.c.state()
        before = copy.deepcopy(state)
        error = RddStorageError("put", self.c.store.path, sqlite3.DatabaseError("fixture malformed"))
        receipt = dict(id="fixture-receipt", outcome="pass")
        with patch("tools.rdd.engine.execute_check", return_value=receipt) as check, \
                patch.object(self.c, "save", side_effect=error) as save:
            with self.assertRaises(RddStorageError) as caught:
                self.c.ensure_checks(state, ["contract"], candidate_spec_digest="fixture-spec")
        self.assertIs(caught.exception, error)
        check.assert_called_once()
        save.assert_called_once()
        self.assertEqual(self.c.state(), before)

    def test_acceptance_and_checkpoint_preserve_crlf_raw_evidence_bytes(self):
        from unittest.mock import patch
        from tools.rdd.common import atomic_write, read_json
        def crlf_log(path, data):
            atomic_write(path, data.replace(b"\n", b"\r\n") if path.suffix == ".log" else data)
        with patch("tools.rdd.checks.atomic_write", crlf_log):
            self.accepted_spec()
        self.assertEqual(self.c.workflow_result("specification")["status"], "passed")
        path = self.f.root / ".rdd/evidence/crlf-checkpoint.json"
        self.c.export_run(path)
        exported = read_json(path)
        for receipt in self.c.state()["checks"].values():
            raw = (self.f.root / receipt["log_path"]).read_bytes()
            self.assertIn(b"\r\n", raw)
            self.assertEqual(exported["evidence"][receipt["log_path"]].encode("utf-8"), raw)
        self.c.resume(path)
        self.assertEqual(self.c.workflow_result("specification")["status"], "passed")
