"""Read-only helper regressions; protocol fakes do not attest native execution."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

import test_engine as fixture
from tools.rdd.common import RddError, RddStorageError, file_hash, operation_lock, read_json
from tools.rdd.profiles import load_profiles
from tools.rdd.review_runner import ReadonlyRunner
from tools.rdd.storage_failure import record_failure
from tools.rdd.workflow import TUI_VERSION, update_runtime


class FakeServer:
    """Minimal explicit protocol fake with durable exact-session history."""
    def __init__(self, root, log_dir=None):
        self.root = root
        self.effective_config = {"sandbox_mode": "workspace-write", "approval_policy": "on-request", "approvals_reviewer": "auto_review"}
        self.runtime_identity = {"version": TUI_VERSION, "executable": "fixture", "executable_sha256": "a" * 64}
        self.calls, self.events, self.threads = [], [], {}
        self.closed, self.overrides = False, {}
        self.on_turn = lambda tid, prompt: "Fixture observation; no acceptance is recorded."
        self.on_event = self.on_resume = self.fail_after_start = self.request = self.id_override = None

    def __enter__(self):
        self.closed = False
        return self

    def close(self):
        self.closed = True

    def rpc(self, method, params, timeout=60):
        self.calls.append((method, copy.deepcopy(params)))
        if method == "model/list":
            models = {}
            for profile in load_profiles(self.root).values():
                models.setdefault(profile["model"], set()).add(profile["effort"])
            return {"data": [{"model": model, "supportedReasoningEfforts": [{"reasoningEffort": effort} for effort in efforts]}
                             for model, efforts in models.items()]}
        if method == "account/read":
            return {"requiresOpenaiAuth": True, "account": {"type": "fixture"}}
        if method in {"thread/start", "thread/resume"}:
            tid = params.get("threadId") or self.id_override or str(uuid.uuid4())
            if method == "thread/resume" and tid not in self.threads:
                raise RddError("Fixture saved session unavailable", "environment")
            thread = self.threads.setdefault(tid, {"id": tid, "historyMode": "legacy", "turns": []})
            if method == "thread/resume" and self.on_resume:
                self.on_resume(thread)
            response = {"thread": copy.deepcopy(thread), "model": params["model"],
                        "reasoningEffort": params["config"]["model_reasoning_effort"],
                        "approvalPolicy": self.effective_config["approval_policy"],
                        "approvalsReviewer": self.effective_config["approvals_reviewer"], "sandbox": {"type": "readOnly"}}
            response.update(copy.deepcopy(self.overrides))
            if self.fail_after_start == method:
                raise RddError("Fixture lost start acknowledgement", "environment")
            return response
        if method == "turn/start":
            tid = params["threadId"]
            text = self.on_turn(tid, params["input"][0]["text"])
            turn = {"id": str(uuid.uuid4()), "status": "completed", "items": [{"type": "agentMessage", "phase": "final_answer", "text": text}]}
            self.threads[tid]["turns"].append(turn)
            if self.request:
                self.events.append({"id": 44, "method": self.request, "params": {"threadId": tid, "turnId": turn["id"]}})
            self.events.append({"method": "turn/completed", "params": {"threadId": tid, "turn": copy.deepcopy(turn)}})
            if self.fail_after_start == method:
                raise RddError("Fixture lost start acknowledgement", "environment")
            return {"turn": {"id": turn["id"], "status": "inProgress"}}
        if method == "turn/interrupt":
            return {}
        raise AssertionError(method)

    def next_event(self, timeout=1):
        if timeout and self.on_event:
            callback, self.on_event = self.on_event, None
            callback()
        return self.events.pop(0) if self.events else None


class ReadonlyRunnerTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.EngineTests(methodName="runTest")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.c, self.root = self.f.c, self.f.root
        self.stage, self.coordinator = "specification", str(uuid.uuid4())
        env = patch.dict(os.environ, CODEX_THREAD_ID=self.coordinator)
        env.start()
        self.addCleanup(env.stop)
        self.reset_server()
        self.prompt = self.f.write(".rdd/runtime/review-prompt.txt", "Review the current source and referenced evidence independently.\n")
        self.attach()

    def reset_server(self):
        self.server = FakeServer(self.root)
        self.runner = ReadonlyRunner(self.c, server_factory=lambda *a, **k: self.server, emit=lambda _: None)

    def attach(self, stage=None):
        if stage:
            self.stage = stage
            with self.c.store.edit(self.c.state(allow_blocked=True)["id"]) as state:
                state["workflow_runtime"] = {}
        update_runtime(self.c, self.stage, backend="tui", launch_id=str(uuid.uuid4()), thread_id=self.coordinator,
                       connection="connected", runtime=copy.deepcopy(self.server.runtime_identity),
                       requested_runtime=self.c.profile_settings("rdd_coordinator"))

    def run_review(self, purpose="live"):
        return self.runner.run(self.stage, purpose, self.prompt)

    def row(self, purpose="live"):
        return self.c.state(allow_blocked=True)["workflow_runtime"][self.stage]["readonly"][purpose]

    def count(self, method):
        return sum(call[0] == method for call in self.server.calls)

    def test_persistent_live_exact_resume_distinct_execution_and_unchanged_approvals(self):
        live = self.run_review()
        self.assertEqual(self.run_review(), live)
        self.assertEqual((self.count("thread/start"), self.count("thread/resume"), self.count("turn/start")), (1, 1, 1))
        self.prompt.write_text("Review current execution readiness.\n", encoding="utf-8")
        self.assertEqual(self.run_review()["session_id"], live["session_id"])
        self.assertNotEqual(self.run_review("execution")["session_id"], live["session_id"])
        for method, params in self.server.calls:
            if method in {"thread/start", "thread/resume"}:
                self.assertEqual(params["sandbox"], "read-only")
                self.assertEqual(params["model"], "gpt-6.1-sol")
                self.assertEqual(params["config"], {"model_reasoning_effort": "xhigh"})
                self.assertFalse(set(params) & {"approvalPolicy", "approvalsReviewer", "dynamicTools"})
                if method == "thread/start":
                    self.assertEqual(params["historyMode"], "legacy")
        self.assertTrue(self.server.closed)

    def test_research_uses_its_canonical_profile(self):
        result = self.run_review("research")
        self.assertEqual(result["requested_runtime"], self.c.profile_settings("rdd_researcher"))
        params = next(params for method, params in self.server.calls if method == "thread/start")
        self.assertEqual(params["developerInstructions"], load_profiles(self.root)["rdd_researcher"]["developer_instructions"])

    def test_connected_native_root_identity_is_required(self):
        for tid in (str(uuid.uuid4()), ""):
            with self.subTest(tid=tid), patch.dict(os.environ, CODEX_THREAD_ID=tid):
                with self.assertRaisesRegex(RddError, "connected native TUI"):
                    self.run_review()
        update_runtime(self.c, self.stage, connection="stopped")
        with self.assertRaisesRegex(RddError, "connected native TUI"):
            self.run_review()
        self.assertEqual(self.server.calls, [])

    def test_profile_permission_and_approval_mismatches_are_rejected(self):
        for overrides in ({"sandbox": {"type": "workspaceWrite"}}, {"approvalPolicy": "never"},
                          {"approvalsReviewer": "user"}, {"model": "gpt-6-astra"}, {"reasoningEffort": "low"}):
            with self.subTest(overrides=overrides):
                self.reset_server()
                update_runtime(self.c, self.stage, readonly={})
                self.server.overrides = overrides
                with self.assertRaisesRegex(RddError, "effective approval policy"):
                    self.run_review()
                self.assertEqual(self.count("turn/start"), 0)
                self.assertEqual(self.row()["pending"], "thread/start")
                self.assertTrue(self.server.closed)

    def test_fresh_and_saved_reviewer_reject_runtime_version_path_or_hash_drift(self):
        for saved in (False, True):
            for field, value in (("version", "0.161.0"), ("executable", "different-fixture-runtime"),
                                 ("executable_sha256", "b" * 64)):
                with self.subTest(saved=saved, field=field):
                    self.reset_server()
                    update_runtime(self.c, self.stage, readonly={})
                    if saved:
                        self.run_review()
                    before = self.c.state()
                    thread_calls = [(method, params) for method, params in self.server.calls if method in {"thread/start", "thread/resume"}]
                    self.server.runtime_identity[field] = value
                    with self.assertRaisesRegex(RddError, "runtime.*identity|executable.*identity"):
                        self.run_review()
                    self.assertEqual(self.c.state(), before)
                    self.assertEqual([(method, params) for method, params in self.server.calls if method in {"thread/start", "thread/resume"}], thread_calls)
                    self.assertTrue(self.server.closed)

    def test_lost_thread_and_turn_ack_never_replace_uncertain_work(self):
        for method in ("thread/start", "turn/start"):
            with self.subTest(method=method):
                self.reset_server()
                update_runtime(self.c, self.stage, readonly={})
                self.server.fail_after_start = method
                with self.assertRaisesRegex(RddError, "lost start acknowledgement"):
                    self.run_review()
                self.assertEqual(self.row()["pending"], method)
                before = copy.deepcopy(self.server.calls)
                with self.assertRaisesRegex(RddError, "acknowledgement is uncertain"):
                    self.run_review()
                self.assertEqual(self.server.calls, before)
                self.assertEqual(self.count(method), 1)

    def test_reused_turn_ack_keeps_pending_instead_of_implying_known_completion(self):
        self.run_review()
        previous_turn = self.row()["last_turn"]
        self.prompt.write_text("A second independent observation.\n", encoding="utf-8")
        original_rpc = self.server.rpc
        def reused_ack(method, params, timeout=60):
            response = original_rpc(method, params, timeout)
            if method == "turn/start":
                response["turn"]["id"] = previous_turn
            return response
        self.server.rpc = reused_ack
        with self.assertRaises(RddError):
            self.run_review()
        self.assertEqual(self.row()["pending"], "turn/start")
        self.assertEqual(self.row()["last_turn"], previous_turn)

    def test_malformed_session_response_is_a_preserved_environment_stop(self):
        self.server.overrides = {"thread": []}
        with self.assertRaises(RddError):
            self.run_review()
        self.assertEqual(self.row()["pending"], "thread/start")
        self.assertTrue(self.server.closed)

    def test_report_rejects_source_changed_during_review(self):
        self.server.on_event = lambda: self.f.write("modules/value.py", "def value():\n    return 84\n")
        with self.assertRaisesRegex(RddError, "snapshot changed"):
            self.run_review()
        self.assertEqual(self.count("turn/start"), 1)

    def test_report_rejects_raw_evidence_changed_during_review(self):
        evidence = self.f.write(".rdd/evidence/raw/current.json", "original evidence\n")
        with self.c.store.edit(self.c.state()["id"]) as state:
            state["fixture_evidence"] = ".rdd/evidence/raw/current.json"
        self.server.on_event = lambda: evidence.write_text("changed evidence\n", encoding="utf-8")
        with self.assertRaisesRegex(RddError, "snapshot changed"):
            self.run_review()

    def test_report_rejects_controller_state_changed_during_review(self):
        def change():
            with self.c.store.edit(self.c.state()["id"]) as state:
                state["fixture_observation"] = "changed"
        self.server.on_event = change
        with self.assertRaisesRegex(RddError, "snapshot changed"):
            self.run_review()

    def test_prompt_changed_during_review_rejects_report(self):
        self.server.on_event = lambda: self.prompt.write_text("A different requested review.\n", encoding="utf-8")
        with self.assertRaisesRegex(RddError, "snapshot changed"):
            self.run_review()

    def test_source_changed_before_new_turn_rejects_stale_input(self):
        self.run_review()
        self.prompt.write_text("Review again.\n", encoding="utf-8")
        self.server.on_resume = lambda thread: self.f.write("modules/value.py", "changed before submit\n")
        with self.assertRaisesRegex(RddError, "snapshot changed before"):
            self.run_review()
        self.assertEqual(self.count("turn/start"), 1)

    def test_local_snapshot_and_report_never_manufacture_acceptance_or_checkpoint(self):
        before, observed = self.c.state(), {}
        def review(tid, prompt):
            packet = json.loads(prompt.split("Snapshot:\n", 1)[1])
            path = self.root / packet["snapshot_path"]
            observed.update(packet=packet, snapshot=read_json(path))
            self.assertEqual(file_hash(path), packet["snapshot_sha256"])
            return "Fixture report."
        self.server.on_turn = review
        self.run_review()
        self.assertNotIn("workflow_runtime", observed["snapshot"]["controller_state"])
        expected = {k: v for k, v in before.items() if k != "workflow_runtime"}
        self.assertEqual(observed["snapshot"]["controller_state"], expected)
        self.assertEqual({k: v for k, v in self.c.state().items() if k != "workflow_runtime"}, expected)
        self.assertEqual(self.c.workflow_result("specification")["status"], "incomplete")

    def test_saved_snapshot_tampering_rejects_report(self):
        def review(tid, prompt):
            packet = json.loads(prompt.split("Snapshot:\n", 1)[1])
            (self.root / packet["snapshot_path"]).write_text("tampered", encoding="utf-8")
            return "Fixture report."
        self.server.on_turn = review
        with self.assertRaisesRegex(RddError, "snapshot changed"):
            self.run_review()

    def test_corrupted_resumed_history_cannot_repeat_unknown_work(self):
        edits = [lambda thread: thread.update(turns=[]),
                 lambda thread: thread["turns"].append({"id": str(uuid.uuid4()), "status": "completed", "items": []}),
                 lambda thread: thread["turns"][-1].update(itemsView="summary"),
                 lambda thread: thread["turns"].append(copy.deepcopy(thread["turns"][-1]))]
        for edit in edits:
            with self.subTest(edit=edit):
                self.reset_server()
                update_runtime(self.c, self.stage, readonly={})
                self.run_review()
                self.server.on_resume = edit
                with self.assertRaisesRegex(RddError, "history|saved last turn|unacknowledged turn"):
                    self.run_review()
                self.assertEqual(self.count("turn/start"), 1)

    def test_known_active_turn_resumes_exact_saved_turn_without_new_work(self):
        first = self.run_review()
        tid, turn = first["session_id"], self.row()["last_turn"]
        complete = copy.deepcopy(self.server.threads[tid]["turns"][-1])
        self.server.threads[tid]["turns"][-1].update(status="inProgress", items=[])
        self.server.on_event = lambda: self.server.events.append({"method": "turn/completed", "params": {"threadId": tid, "turn": complete}})
        self.assertEqual(self.run_review(), first)
        self.assertEqual(self.row()["last_turn"], turn)
        self.assertEqual(self.count("turn/start"), 1)

    def test_final_report_from_item_notification_survives_empty_completion_items(self):
        original_rpc = self.server.rpc
        def streamed_items(method, params, timeout=60):
            result = original_rpc(method, params, timeout)
            if method == "turn/start":
                completion = self.server.events.pop()
                tid, turn = completion["params"]["threadId"], completion["params"]["turn"]
                item = turn["items"][0]
                turn["items"] = []
                self.server.events.extend([
                    {"method": "item/completed", "params": {"threadId": tid, "turnId": turn["id"], "item": item}},
                    completion,
                ])
            return result
        self.server.rpc = streamed_items
        self.assertEqual(self.run_review()["report"], "Fixture observation; no acceptance is recorded.")

    def test_summary_completion_is_verified_by_exact_full_history_resume(self):
        original_rpc = self.server.rpc
        def summary_completion(method, params, timeout=60):
            result = original_rpc(method, params, timeout)
            if method == "turn/start":
                completion = self.server.events[-1]
                completion["params"]["turn"].update(itemsView="summary", items=[])
            return result
        self.server.rpc = summary_completion
        self.assertEqual(self.run_review()["report"], "Fixture observation; no acceptance is recorded.")
        resume = [params for method, params in self.server.calls if method == "thread/resume"]
        self.assertEqual(len(resume), 1)
        self.assertEqual(resume[0]["threadId"], self.row()["thread_id"])

    def test_known_active_turn_is_interrupted_if_resumed_permissions_are_invalid(self):
        result = self.run_review()
        self.server.threads[result["session_id"]]["turns"][-1].update(status="inProgress", items=[])
        self.server.overrides = {"sandbox": {"type": "workspaceWrite"}}
        with self.assertRaisesRegex(RddError, "effective approval policy"):
            self.run_review()
        self.assertEqual(self.count("turn/interrupt"), 1)
        self.assertEqual(self.count("turn/start"), 1)
        self.assertTrue(self.server.closed)

    def test_owned_shutdown_can_retry_exact_interrupted_turn_in_same_session(self):
        def stop():
            raise KeyboardInterrupt()
        self.server.on_event = stop
        with self.assertRaises(KeyboardInterrupt):
            self.run_review()
        saved = copy.deepcopy(self.row())
        self.assertEqual(self.count("turn/interrupt"), 1)
        self.assertTrue(self.server.closed)
        self.assertIsNone(saved["pending"])
        # Backend terminal history, rather than the local interruption request,
        # is the independent oracle that permits a new turn.
        self.server.threads[saved["thread_id"]]["turns"][-1].update(status="interrupted", items=[])
        self.server.events.clear()
        result = self.run_review()
        self.assertEqual(result["session_id"], saved["thread_id"])
        self.assertNotEqual(self.row()["last_turn"], saved["last_turn"])
        self.assertEqual((self.count("thread/start"), self.count("thread/resume"), self.count("turn/start")), (1, 1, 2))
        self.assertTrue(self.server.closed)

    def test_saved_failed_turn_does_not_start_replacement_work(self):
        result = self.run_review()
        self.server.threads[result["session_id"]]["turns"][-1].update(status="failed", items=[])
        with self.assertRaisesRegex(RddError, "did not complete"):
            self.run_review()
        self.prompt.write_text("Review a changed instruction.\n", encoding="utf-8")
        with self.assertRaisesRegex(RddError, "did not complete"):
            self.run_review()
        self.assertEqual((self.count("thread/start"), self.count("turn/start")), (1, 1))
        self.assertTrue(self.server.closed)

    def test_author_capacity_live_two_execution_one(self):
        with self.c.store.edit(self.c.state()["id"]) as state:
            state["workflow_nodes"] = {str(i): {"status": "claimed", "claim": {"session_id": f"author-{i}"}} for i in range(2)}
        self.run_review()
        with self.assertRaisesRegex(RddError, "Release an author slot"):
            self.run_review("execution")
        with self.c.store.edit(self.c.state()["id"]) as state:
            state["workflow_nodes"]["third"] = {"status": "claimed", "claim": {"session_id": "author-third"}}
        with self.assertRaisesRegex(RddError, "Release an author slot"):
            self.run_review()
        self.assertEqual(self.count("thread/start"), 1)

    def test_reviewer_cannot_reuse_author_identity(self):
        author = str(uuid.uuid4())
        with self.c.store.edit(self.c.state()["id"]) as state:
            state["authors"] = {self.stage: [author]}
        self.server.id_override = author
        with self.assertRaisesRegex(RddError, "independent of authors"):
            self.run_review()
        self.assertEqual(self.count("turn/start"), 0)

    def test_reviewer_lock_held_controller_lock_released_during_wait(self):
        def during_wait():
            with operation_lock(self.root):
                pass
            with self.assertRaisesRegex(RddError, "reviewer|review|read-only"):
                with operation_lock(self.root, reviewer=True):
                    pass
        self.server.on_event = during_wait
        self.run_review()
        with operation_lock(self.root, reviewer=True):
            pass

    def test_all_server_requests_rejected_without_reply_and_turn_interrupted(self):
        for method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/permissions/requestApproval", "item/tool/call", "item/tool/requestUserInput"):
            with self.subTest(method=method):
                self.reset_server()
                update_runtime(self.c, self.stage, readonly={})
                self.server.request = method
                with self.assertRaisesRegex(RddError, "no reply was sent"):
                    self.run_review()
                self.assertEqual(self.count("turn/interrupt"), 1)
                self.assertTrue(self.server.closed)

    def test_storage_failure_interrupts_closes_and_never_journals_after_failure(self):
        self.attach("preparation")
        writes, failed = [], []
        from tools.rdd import review_runner
        real_update = review_runner.update_runtime
        def update(*args, **kwargs):
            self.assertFalse(failed, "Database journal updated after terminal storage failure")
            writes.append(kwargs)
            return real_update(*args, **kwargs)
        def fail():
            failed.append(True)
            raise RddStorageError("fixture review read", self.root / ".rdd/runtime/state.sqlite3", OSError("fixture disk failure"))
        self.server.on_event = fail
        with patch("tools.rdd.review_runner.update_runtime", update):
            with self.assertRaises(RddStorageError) as observed:
                self.run_review()
        self.assertTrue(observed.exception.restart_required)
        self.assertEqual(read_json(Path(observed.exception.failure_path))["stage"], "preparation")
        self.assertEqual(self.count("turn/interrupt"), 1)
        self.assertTrue(self.server.closed)
        self.assertEqual(len(writes), 4)

    def test_existing_storage_failure_stops_before_database_or_backend_reads(self):
        self.attach("implementation")
        error = RddStorageError("fixture existing failure", self.root / ".rdd/runtime/state.sqlite3", OSError("fixture disk failure"))
        record_failure(self.root, error, stage="implementation", thread_id=self.coordinator)
        with patch.object(self.c, "state", side_effect=AssertionError("Database read after terminal failure")):
            with self.assertRaisesRegex(RddError, "Critical headless storage failure"):
                self.run_review()
        self.assertEqual(self.server.calls, [])

    def test_storage_marker_appearing_during_snapshot_stops_before_journal_read(self):
        self.attach("preparation")
        error = RddStorageError("fixture snapshot failure", self.root / ".rdd/runtime/state.sqlite3", OSError("fixture disk failure"))
        forbidden_reads = []
        original_state, original_snapshot = self.c.state, self.runner.snapshot
        def state(*args, **kwargs):
            if getattr(error, "restart_required", False):
                forbidden_reads.append(True)
            return original_state(*args, **kwargs)
        def snapshot(value):
            result = original_snapshot(value)
            record_failure(self.root, error, stage="preparation", thread_id=self.coordinator)
            return result
        with patch.object(self.c, "state", state), patch.object(self.runner, "snapshot", snapshot):
            with self.assertRaisesRegex(RddError, "Critical headless storage failure"):
                self.run_review()
        self.assertEqual(forbidden_reads, [])
        self.assertEqual(self.server.calls, [])

    def test_empty_or_overlong_prompt_cannot_start_session(self):
        for prompt in ("   ", "x" * (self.c.config["limits"]["max_packet_characters"] + 1)):
            with self.subTest(size=len(prompt)):
                self.prompt.write_text(prompt, encoding="utf-8")
                with self.assertRaisesRegex(RddError, "bounded packet limit"):
                    self.run_review()
        self.assertEqual(self.count("thread/start"), 0)
