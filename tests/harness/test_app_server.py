"""Actual subprocess stdio tests; no model calls, config writes, or approval replies."""
from __future__ import annotations

import io
import json
import os
import queue
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tools.rdd.app_server import AppServer
from tools.rdd.common import RddError, file_hash


FAKE_SERVER = r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path
options = json.loads(Path("fixture.json").read_text(encoding="utf-8"))
if "--version" in sys.argv:
    if options.get("version_hang"):
        time.sleep(60)
    if options.get("version_orphan"):
        program = 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)'
        child = subprocess.Popen([sys.executable, "-u", "-c", program])
        Path("version-child.json").write_text(json.dumps({"pid": child.pid, "group": os.getpgrp()}), encoding="utf-8")
    print("codex-cli " + options.get("version", "0.161.0"), flush=True)
    raise SystemExit(0)
def send(value):
    sys.stdout.buffer.write((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
def result(request, value):
    send({"id": request["id"], "result": value})
pending = []
for line in sys.stdin.buffer:
    request = json.loads(line.decode("utf-8"))
    with Path("transcript.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(request, ensure_ascii=False) + "\n")
    method = request.get("method")
    if method == "initialize":
        if options.get("initialize_hang"):
            time.sleep(60)
        result(request, {"userAgent": "fake qualified server"})
    elif method == "initialized":
        pass
    elif method == "config/read":
        result(request, {"config": {"approval_policy": "on-request", "sandbox_mode": "workspace-write", "approvals_reviewer": "user", "sentinel": "unchanged"}})
        if options.get("no_read"):
            time.sleep(60)
    elif method == "echo":
        result(request, request["params"])
    elif method == "inspect":
        result(request, {"argv": sys.argv[1:], "cwd": os.getcwd(), "sentinel": os.environ.get("RDD_TRANSPORT_SENTINEL")})
    elif method == "interleaved":
        send({"method": "item/updated", "params": {"text": "雪🌱", "ordinal": 1}})
        send({"id": "approval-雪", "method": "item/commandExecution/requestApproval", "params": {"command": "do not approve"}})
        send({"method": "item/updated", "params": {"text": "雪🌱", "ordinal": 2}})
        result(request, {"done": True})
    elif method == "frames":
        for frame in request["params"]["frames"]:
            send(frame)
        result(request, {"done": True})
        if request["params"].get("exit"):
            raise SystemExit(0)
    elif method == "reply-observed":
        result(request, {"reply": last_reply})
    elif method == "paired":
        pending.append(request)
        if len(pending) == 2:
            for item in reversed(pending):
                result(item, item["params"])
            pending = []
    elif method == "slow":
        time.sleep(.15)
        result(request, {"late": True})
    elif method == "error":
        send({"id": request["id"], "error": {"code": -32602, "message": "secret-error-token", "data": "private"}})
        sys.stderr.buffer.write(b"secret-stderr-token\n")
        sys.stderr.buffer.flush()
    elif method == "eof":
        sys.stderr.buffer.write(b"secret-stderr-token\n")
        sys.stderr.buffer.flush()
        raise SystemExit(9)
    elif method == "result-eof":
        send({"method": "item/updated", "params": {"before_exit": True}})
        result(request, {"complete": True})
        raise SystemExit(0)
    elif method == "orphan":
        program = 'import json,os,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print(json.dumps({"method":"child/ready","params":{"pid":os.getpid()}}),flush=True);time.sleep(60)'
        child = subprocess.Popen([sys.executable, "-u", "-c", program])
        result(request, {"child": child.pid})
        raise SystemExit(0)
    elif method == "invalid-json":
        sys.stdout.buffer.write(b"secret-invalid-token\n")
        sys.stdout.buffer.flush()
    elif method == "flood":
        sys.stderr.buffer.write(b"x" * 8192)
        sys.stderr.buffer.flush()
        result(request, {"done": True})
    elif method == "event-flood":
        for ordinal in range(1, 31):
            send({"method": "item/updated", "params": {"ordinal": ordinal, "text": "雪" * request["params"].get("size", 0)}})
        result(request, {"done": True})
    elif method == "hang":
        if os.name == "posix":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        result(request, {"pid": os.getpid()})
        time.sleep(60)
    elif method is None:
        last_reply = request
    else:
        result(request, None)
'''



class TransportProbe:
    """Run the real reader/writer over controllable byte streams."""

    def __init__(self, root, partial_size=None, pause_log=False, reply_timeout=None):
        self.log_started = threading.Event()
        self.release_log = threading.Event()
        self.partial_size = partial_size
        self.wire = bytearray()
        self.incoming = queue.Queue()
        self.started = threading.Event()
        self.release = threading.Event()
        self.frames = []
        probe = self
        class LoggedServer(AppServer):
            def _log(server, name, data):
                super()._log(name, data)
                if pause_log and name == "stdin":
                    probe.log_started.set()
                    if not probe.release_log.wait(3):
                        raise OSError("test stdin log was not released")

            def _send_bytes(server, data, deadline, *, request_id=None, request=None):
                if reply_timeout is not None and request is not None:
                    deadline = min(deadline, time.monotonic() + reply_timeout)
                return super()._send_bytes(data, deadline, request_id=request_id, request=request)
        self.server = LoggedServer(root)
        self.server._logs = {name: io.BytesIO() for name in ("stdin", "stdout", "stderr")}
        self.server._log_sizes = {name: 0 for name in self.server._logs}
        self.server.process = SimpleNamespace(stdin=self, stdout=self)
        self.threads = [threading.Thread(target=target, daemon=True)
                        for target in (self.server._read_stdout, self.server._write_stdin)]
        for thread in self.threads:
            thread.start()

    def readline(self, limit):
        return self.incoming.get(timeout=3)

    def write(self, data):
        if not self.started.is_set():
            self.started.set()
            if not self.release.wait(3):
                raise OSError("test writer was not released")
        data = data if self.partial_size is None else data[:self.partial_size]
        self.wire.extend(data)
        while b"\n" in self.wire:
            line, _, rest = self.wire.partition(b"\n")
            self.frames.append(json.loads(line.decode("utf-8")))
            self.wire[:] = rest
        return len(data)

    def close(self):
        self.release_log.set()
        self.release.set()
        self.incoming.put(b"")

    def feed(self, message):
        with self.server._condition:
            count = len(self.server._events)
            self.incoming.put((json.dumps(message) + "\n").encode("utf-8"))
            deadline = time.monotonic() + 1
            while len(self.server._events) == count and not self.server._failure:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError("transport reader did not admit frame")
                self.server._condition.wait(remaining)

    def finish(self):
        with self.server._condition:
            self.server._closed = True
            self.server._condition.notify_all()
        self.server._writes.put_nowait(None)
        self.close()
        for thread in self.threads:
            thread.join(timeout=2)
        if any(thread.is_alive() for thread in self.threads):
            raise AssertionError("transport probe thread did not stop")


class AppServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rdd-app-server-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.binary = self.root / "fake_server.py"
        self.binary.write_text(FAKE_SERVER, encoding="utf-8")
        self.options()
        self.log_dir = self.root / ".rdd/evidence/transport"

    def options(self, **value):
        (self.root / "fixture.json").write_text(json.dumps(value), encoding="utf-8")

    def server(self):
        return AppServer(self.root, binary=[sys.executable, "-u", str(self.binary)], log_dir=self.log_dir)

    def transcript(self):
        return [json.loads(line) for line in (self.root / "transcript.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_utf8_round_trip_and_inherited_config(self):
        config = self.root / ".codex/config.toml"
        config.parent.mkdir()
        config.write_text('approval_policy = "on-request"\n', encoding="utf-8")
        before = config.read_bytes()
        payload = {"text": "é雪🌱", "count": 3}
        with patch.dict(os.environ, {"RDD_TRANSPORT_SENTINEL": "雪"}):
            for version in ("0.161.0", "0.162.1"):
                with self.subTest(version=version):
                    self.options(version=version)
                    self.log_dir = self.root / ".rdd/evidence" / version
                    offset = len(self.transcript()) if (self.root / "transcript.jsonl").exists() else 0
                    with self.server() as server:
                        self.assertEqual(server.rpc("echo", payload), payload)
                        inspected = server.rpc("inspect", {})
                        self.assertEqual(inspected, {"argv": ["app-server", "--listen", "stdio://"], "cwd": str(self.root), "sentinel": "雪"})
                        self.assertEqual(server.effective_config, {"approval_policy": "on-request", "sandbox_mode": "workspace-write", "approvals_reviewer": "user", "sentinel": "unchanged"})
                        self.assertEqual(server.runtime_identity["version"], version)
                        self.assertEqual(server.runtime_identity["executable_sha256"], file_hash(Path(sys.executable).resolve()))
                    self.assertEqual(config.read_bytes(), before)
                    requests = self.transcript()[offset:]
                    self.assertEqual([item["method"] for item in requests[:3]], ["initialize", "initialized", "config/read"])
                    self.assertTrue(requests[0]["params"]["capabilities"]["experimentalApi"])
                    self.assertEqual(requests[2]["params"], {"cwd": str(self.root), "includeLayers": False})
                    self.assertNotIn("id", requests[1])

    def test_interleaved_events_and_unknown_approval_retained_in_order(self):
        with self.server() as server:
            self.assertEqual(server.rpc("interleaved", {}), {"done": True})
            first = server.next_event(0)
            request = server.next_event(0)
            second = server.next_event(0)
            self.assertEqual(first["params"], {"text": "雪🌱", "ordinal": 1})
            self.assertEqual(request["id"], "approval-雪")
            self.assertEqual(request["method"], "item/commandExecution/requestApproval")
            self.assertEqual(second["params"]["ordinal"], 2)
            self.assertIsNone(server.next_event(.02))
            self.assertFalse(any("result" in item and item.get("id") == "approval-雪" for item in self.transcript()))

    def test_explicit_correlated_reply(self):
        with self.server() as server:
            server.rpc("interleaved", {})
            server.next_event(0)
            request = server.next_event(0)
            server.reply(request["id"], {"decision": "decline"})
            observed = server.rpc("reply-observed", {})
            self.assertEqual(observed["reply"], {"id": "approval-雪", "result": {"decision": "decline"}})

    def approval(self, ident="approval-current", **params):
        return {"id": ident, "method": "item/fileChange/requestApproval",
                "params": {"threadId": "thread-a", "turnId": "turn-a", "itemId": "item-a", **params}}

    def probe(self, **kwargs):
        probe = TransportProbe(self.root, **kwargs)
        self.addCleanup(probe.finish)
        return probe

    def run_background(self, operation):
        errors = []
        def call():
            try:
                operation()
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=call, daemon=True)
        thread.start()
        return thread, errors

    def wait_writes(self, server, count):
        deadline = time.monotonic() + 1
        with server._condition:
            while server._write_count != count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.fail(f"writer count did not become {count}")
                server._condition.wait(remaining)

    def test_resolved_request_retires_before_queued_events_are_consumed(self):
        request = self.approval()
        with self.server() as server:
            server.rpc("frames", {"frames": [request, {"method": "serverRequest/resolved",
                       "params": {"threadId": "thread-a", "requestId": request["id"]}}]})
            with self.assertRaisesRegex(RddError, "outstanding"):
                server.reply(request["id"], {"decision": "decline"})
            self.assertEqual(server.next_event(0), request)
            self.assertEqual(server.next_event(0)["method"], "serverRequest/resolved")
        self.assertFalse(any(item.get("id") == request["id"] for item in self.transcript()))

    def test_terminal_events_retire_only_correlated_requests_before_consumption(self):
        terminal_events = [
            {"method": "turn/completed", "params": {"threadId": "thread-a", "turn": {"id": "turn-a", "status": "interrupted"}}},
            {"method": "turn/completed", "params": {"threadId": "thread-a", "turn": {"id": "turn-a", "status": "failed"}}},
            {"method": "item/completed", "params": {"threadId": "thread-a", "turnId": "turn-a", "item": {"id": "item-a"}}},
        ]
        for index, terminal in enumerate(terminal_events):
            with self.subTest(terminal=terminal):
                self.log_dir = self.root / ".rdd/evidence" / f"terminal-{index}"
                request = self.approval()
                other = self.approval("other", turnId="turn-b")
                with self.server() as server:
                    server.rpc("frames", {"frames": [request, other, terminal]})
                    with self.assertRaisesRegex(RddError, "outstanding"):
                        server.reply(request["id"], {"decision": "decline"})
                    server.reply(other["id"], {"decision": "decline"})
                    self.assertEqual(server.rpc("reply-observed", {})["reply"]["id"], "other")

    def test_duplicate_outstanding_server_request_id_fails_closed(self):
        request = self.approval()
        with self.server() as server:
            with self.assertRaisesRegex(RddError, "duplicate.*request ID"):
                server.rpc("frames", {"frames": [request, self.approval(command="different")]})
            self.assertEqual(server.next_event(0), request)
            with self.assertRaises(RddError):
                server.reply(request["id"], {"decision": "decline"})

    def test_reply_is_atomically_single_use_during_blocked_write(self):
        probe = self.probe()
        request = self.approval()
        probe.feed(request)
        first, first_errors = self.run_background(lambda: probe.server.reply(request["id"], {"decision": "decline"}))
        self.assertTrue(probe.started.wait(1))
        second, second_errors = self.run_background(lambda: probe.server.reply(request["id"], {"decision": "decline"}))
        second.join(timeout=.1)
        probe.release.set()
        first.join(timeout=1)
        second.join(timeout=1)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(first_errors, [])
        self.assertEqual(probe.frames, [{"id": request["id"], "result": {"decision": "decline"}}])
        self.assertEqual(len(second_errors), 1)
        self.assertIsInstance(second_errors[0], RddError)

    def test_expired_queued_write_is_never_transmitted_later(self):
        probe = self.probe()
        holding, errors = self.run_background(lambda: probe.server._send({"method": "holding"}, time.monotonic() + 2))
        self.assertTrue(probe.started.wait(1))
        with self.assertRaisesRegex(RddError, "timed out"):
            probe.server._send({"id": "expired-approval", "result": {"decision": "accept"}}, time.monotonic() + .03)
        probe.release.set()
        holding.join(timeout=1)
        self.wait_writes(probe.server, 0)
        self.assertEqual(errors, [])
        self.assertEqual(probe.frames, [{"method": "holding"}])
        probe.server._send({"method": "current"}, time.monotonic() + 1)
        self.assertEqual(probe.frames[-1], {"method": "current"})

    def test_write_timeout_after_delivery_started_poisons_connection(self):
        probe = self.probe()
        timed_out, errors = self.run_background(lambda: probe.server._send({"method": "possibly-partial"}, time.monotonic() + .03))
        self.assertTrue(probe.started.wait(1))
        timed_out.join(timeout=1)
        self.assertEqual(len(errors), 1)
        self.assertIn("timed out", str(errors[0]))
        probe.release.set()
        self.wait_writes(probe.server, 0)
        with self.assertRaisesRegex(RddError, "timed out|reconnect"):
            probe.server._send({"method": "never-retry"}, time.monotonic() + 1)
        self.assertFalse(any(frame.get("method") == "never-retry" for frame in probe.frames))

    def test_partial_delivery_timeout_never_retries_remaining_bytes(self):
        probe = self.probe(partial_size=8)
        timed_out, errors = self.run_background(lambda: probe.server._send({"method": "partial-frame"}, time.monotonic() + .03))
        self.assertTrue(probe.started.wait(1))
        timed_out.join(timeout=1)
        self.assertEqual(len(errors), 1)
        self.assertIn("timed out", str(errors[0]))
        probe.release.set()
        self.wait_writes(probe.server, 0)
        self.assertEqual(probe.frames, [])
        self.assertEqual(probe.wire, b'{"method')
        with self.assertRaisesRegex(RddError, "timed out|reconnect"):
            probe.server.request_pending("anything")
        with self.assertRaisesRegex(RddError, "timed out|reconnect"):
            probe.server.request_snapshot("anything")

    def test_outstanding_request_metadata_bytes_remain_bounded_after_events_drained(self):
        with patch("tools.rdd.app_server.MAX_EVENT_BYTES", 512):
            with self.server() as server:
                first = self.approval("first", reason="x" * 180)
                server.rpc("frames", {"frames": [first]})
                self.assertEqual(server.next_event(0), first)
                with self.assertRaisesRegex(RddError, "request.*capacity"):
                    server.rpc("frames", {"frames": [self.approval("second", reason="x" * 180)]})

    def test_item_context_bytes_remain_bounded_after_events_drained(self):
        def started(ident):
            return {"method": "item/started", "params": {"threadId": "thread-a", "turnId": "turn-a",
                    "item": {"id": ident, "type": "agentMessage", "text": "x" * 200}}}
        with patch("tools.rdd.app_server.MAX_EVENT_BYTES", 450):
            with self.server() as server:
                first = started("first")
                server.rpc("frames", {"frames": [first]})
                self.assertEqual(server.next_event(0), first)
                with self.assertRaisesRegex(RddError, "context.*capacity"):
                    server.rpc("frames", {"frames": [started("second")]})

    def test_resolution_cancels_reply_waiting_behind_other_write(self):
        probe = self.probe()
        holding, hold_errors = self.run_background(lambda: probe.server._send({"method": "holding"}, time.monotonic() + 2))
        self.assertTrue(probe.started.wait(1))
        request = self.approval()
        probe.feed(request)
        replying, errors = self.run_background(lambda: probe.server.reply(request["id"], {"decision": "accept"}))
        self.wait_writes(probe.server, 2)
        probe.feed({"method": "serverRequest/resolved", "params": {"requestId": request["id"], "threadId": "thread-a"}})
        probe.release.set()
        holding.join(timeout=1)
        replying.join(timeout=1)
        self.assertFalse(replying.is_alive())
        self.assertEqual(hold_errors, [])
        self.assertEqual(probe.frames, [{"method": "holding"}])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RddError)

    def test_expected_request_is_immutable_and_reused_id_requires_new_content(self):
        request = self.approval(reason="original")
        with self.server() as server:
            self.assertTrue(callable(getattr(server, "request_pending", None)), "transport must expose pending request comparison")
            server.rpc("frames", {"frames": [request]})
            observed = server.next_event(0)
            observed["params"]["reason"] = "modified by caller"
            self.assertTrue(server.request_pending(request["id"], expected=request))
            self.assertFalse(server.request_pending(request["id"], expected=observed))
            with self.assertRaisesRegex(RddError, "outstanding|match"):
                server.reply(request["id"], {"decision": "accept"}, expected=observed)
            server.reply(request["id"], {"decision": "decline"}, expected=request)
            self.assertFalse(server.request_pending(request["id"]))
            newer = self.approval(reason="new request")
            server.rpc("frames", {"frames": [newer]})
            self.assertFalse(server.request_pending(request["id"], expected=request))
            self.assertTrue(server.request_pending(newer["id"], expected=newer))
            with self.assertRaisesRegex(RddError, "outstanding|match"):
                server.reply(request["id"], {"decision": "accept"}, expected=request)
            server.reply(newer["id"], {"decision": "decline"}, expected=newer)

    def test_connection_eof_and_close_retire_pending_server_requests(self):
        for mode in ("eof", "close"):
            with self.subTest(mode=mode):
                self.log_dir = self.root / ".rdd/evidence" / mode
                server = self.server()
                with server:
                    self.assertTrue(callable(getattr(server, "request_pending", None)), "transport must expose request lifetime")
                    request = self.approval()
                    server.rpc("frames", {"frames": [request], "exit": mode == "eof"})
                    if mode == "eof":
                        server.process.wait(timeout=1)
                        deadline = time.monotonic() + 1
                        with server._condition:
                            while not server._eof and time.monotonic() < deadline:
                                server._condition.wait(.01)
                    else:
                        server.close()
                    with self.assertRaisesRegex(RddError, "EOF|not running"):
                        server.request_pending(request["id"], expected=request)
                    with self.assertRaisesRegex(RddError, "EOF|not running"):
                        server.request_snapshot(request["id"], expected=request)
                    self.assertEqual(server._server_requests, {})
                    self.assertEqual(server.next_event(0), request)

    def test_patch_snapshot_is_copied_and_revision_rejects_stale_answer(self):
        request = self.approval()
        item = {"id": "item-a", "type": "fileChange", "changes": [{"path": "a.txt", "diff": "old"}]}
        started = {"method": "item/started", "params": {"threadId": "thread-a", "turnId": "turn-a", "item": item}}
        with self.server() as server:
            self.assertTrue(callable(getattr(server, "request_snapshot", None)), "transport must snapshot latest correlated context")
            server.rpc("frames", {"frames": [started, request]})
            before = server.request_snapshot(request["id"], expected=request)
            self.assertEqual(before["item"], item)
            before["item"]["changes"][0]["diff"] = "caller mutation"
            self.assertEqual(server.request_snapshot(request["id"], expected=request)["item"], item)
            changed = [{"path": "a.txt", "diff": "new"}]
            server.rpc("frames", {"frames": [{"method": "item/fileChange/patchUpdated", "params": {"threadId": "thread-a", "turnId": "turn-a", "itemId": "item-a", "changes": changed}}]})
            after = server.request_snapshot(request["id"], expected=request)
            self.assertNotEqual(after["revision"], before["revision"])
            self.assertEqual(after["item"]["changes"], changed)
            with self.assertRaisesRegex(RddError, "context|revision"):
                server.reply(request["id"], {"decision": "accept"}, expected=request, revision=before["revision"])
            server.reply(request["id"], {"decision": "decline"}, expected=request, revision=after["revision"])

    def test_incomplete_patch_update_invalidates_old_cached_content(self):
        for index, changes in enumerate(({}, {"changes": None}, {"changes": "unknown"}, {"changes": {"path": "a.txt"}})):
            with self.subTest(changes=changes):
                self.log_dir = self.root / ".rdd/evidence" / f"incomplete-patch-{index}"
                request = self.approval()
                item = {"id": "item-a", "type": "fileChange", "changes": [{"path": "a.txt", "diff": "old patch"}]}
                with self.server() as server:
                    server.rpc("frames", {"frames": [
                        {"method": "item/started", "params": {"threadId": "thread-a", "turnId": "turn-a", "item": item}}, request]})
                    before = server.request_snapshot(request["id"], expected=request)
                    server.rpc("frames", {"frames": [{"method": "item/fileChange/patchUpdated", "params": {
                        "threadId": "thread-a", "turnId": "turn-a", "itemId": "item-a", **changes}}]})
                    after = server.request_snapshot(request["id"], expected=request)
                    self.assertIsNone(after["item"], "unknown replacement patch must not reuse the old displayed patch")
                    self.assertNotEqual(after["revision"], before["revision"])
                    with self.assertRaisesRegex(RddError, "context|revision"):
                        server.reply(request["id"], {"decision": "accept"}, expected=request, revision=before["revision"])
                    self.assertTrue(server.request_pending(request["id"], expected=request))

    def test_resolution_for_other_thread_is_protocol_failure_not_progress(self):
        request = self.approval()
        with self.server() as server:
            server.rpc("frames", {"frames": [request]})
            with self.assertRaisesRegex(RddError, "uncorrelated.*resolution"):
                server.rpc("frames", {"frames": [{"method": "serverRequest/resolved", "params": {
                    "threadId": "unrelated-thread", "requestId": request["id"]}}]})
            with self.assertRaisesRegex(RddError, "uncorrelated.*resolution"):
                server.request_pending(request["id"], expected=request)
            with self.assertRaisesRegex(RddError, "uncorrelated.*resolution"):
                server.request_snapshot(request["id"], expected=request)
            with self.assertRaisesRegex(RddError, "uncorrelated.*resolution"):
                server.reply(request["id"], {"decision": "accept"}, expected=request)
        self.assertFalse(any(item.get("id") == request["id"] and "result" in item for item in self.transcript()))

    def test_patch_change_cancels_admitted_reply_before_writer_starts(self):
        probe = self.probe()
        self.assertTrue(callable(getattr(probe.server, "request_snapshot", None)), "transport must snapshot pending request context")
        request = self.approval()
        probe.feed({"method": "item/started", "params": {"threadId": "thread-a", "turnId": "turn-a", "item": {"id": "item-a", "type": "fileChange", "changes": []}}})
        probe.feed(request)
        snapshot = probe.server.request_snapshot(request["id"], expected=request)
        holding, hold_errors = self.run_background(lambda: probe.server._send({"method": "holding"}, time.monotonic() + 2))
        self.assertTrue(probe.started.wait(1))
        replying, errors = self.run_background(lambda: probe.server.reply(request["id"], {"decision": "accept"}, expected=request, revision=snapshot["revision"]))
        self.wait_writes(probe.server, 2)
        probe.feed({"method": "item/fileChange/patchUpdated", "params": {"threadId": "thread-a", "turnId": "turn-a", "itemId": "item-a", "changes": [{"path": "a", "diff": "changed"}]}})
        probe.release.set()
        holding.join(timeout=1)
        replying.join(timeout=1)
        self.assertFalse(replying.is_alive())
        self.assertEqual(hold_errors, [])
        self.assertEqual(probe.frames, [{"method": "holding"}])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RddError)
        refreshed = probe.server.request_snapshot(request["id"], expected=request)
        self.assertNotEqual(refreshed["revision"], snapshot["revision"])
        self.assertEqual(refreshed["item"]["changes"], [{"path": "a", "diff": "changed"}])
        probe.server.reply(request["id"], {"decision": "decline"}, expected=request, revision=refreshed["revision"])
        self.assertEqual(probe.frames[-1], {"id": request["id"], "result": {"decision": "decline"}})

    def test_logger_barrier_revalidates_reply_before_any_transmission(self):
        for invalidation in ("patch", "resolved-reused-id"):
            with self.subTest(invalidation=invalidation):
                probe = self.probe(pause_log=True)
                request = self.approval()
                probe.feed({"method": "item/started", "params": {"threadId": "thread-a", "turnId": "turn-a",
                            "item": {"id": "item-a", "type": "fileChange", "changes": []}}})
                probe.feed(request)
                snapshot = probe.server.request_snapshot(request["id"], expected=request)
                replying, errors = self.run_background(lambda: probe.server.reply(
                    request["id"], {"decision": "accept"}, expected=request, revision=snapshot["revision"]))
                self.assertTrue(probe.log_started.wait(1))
                self.assertFalse(probe.started.is_set(), "the barrier must precede every stdin byte")
                if invalidation == "patch":
                    probe.feed({"method": "item/fileChange/patchUpdated", "params": {"threadId": "thread-a",
                                "turnId": "turn-a", "itemId": "item-a", "changes": [{"path": "a", "diff": "new"}]}})
                else:
                    probe.feed({"method": "serverRequest/resolved", "params": {
                                "threadId": "thread-a", "requestId": request["id"]}})
                    probe.feed(self.approval(reason="new request with reused ID"))
                probe.release.set()
                probe.release_log.set()
                replying.join(timeout=1)
                self.wait_writes(probe.server, 0)
                self.assertFalse(replying.is_alive())
                self.assertEqual(len(errors), 1, "invalidation after logging must never send the old approval")
                self.assertIsInstance(errors[0], RddError)
                self.assertRegex(str(errors[0]), "context|outstanding|delivery started")
                self.assertEqual(probe.frames, [])
                self.assertFalse(probe.started.is_set())
                with self.assertRaises(RddError):
                    probe.server.request_snapshot(request["id"], expected=request)

    def test_context_change_during_partial_reply_poisons_without_retry(self):
        probe = self.probe(partial_size=8)
        request = self.approval()
        probe.feed({"method": "item/started", "params": {"threadId": "thread-a", "turnId": "turn-a",
                    "item": {"id": "item-a", "type": "fileChange", "changes": []}}})
        probe.feed(request)
        snapshot = probe.server.request_snapshot(request["id"], expected=request)
        replying, errors = self.run_background(lambda: probe.server.reply(
            request["id"], {"decision": "accept"}, expected=request, revision=snapshot["revision"]))
        self.assertTrue(probe.started.wait(1))
        probe.feed({"method": "item/fileChange/patchUpdated", "params": {"threadId": "thread-a",
                    "turnId": "turn-a", "itemId": "item-a", "changes": [{"path": "a", "diff": "new"}]}})
        probe.release.set()
        replying.join(timeout=1)
        self.wait_writes(probe.server, 0)
        self.assertFalse(replying.is_alive())
        self.assertEqual(len(errors), 1, "context invalidation during delivery must not report successful old approval")
        self.assertIsInstance(errors[0], RddError)
        self.assertRegex(str(errors[0]), "context.*delivery started")
        self.assertEqual(probe.frames, [])
        self.assertEqual(len(probe.wire), 8)
        with self.assertRaisesRegex(RddError, "context.*delivery started"):
            probe.server.request_snapshot(request["id"], expected=request)
        with self.assertRaisesRegex(RddError, "context.*delivery started"):
            probe.server.reply(request["id"], {"decision": "accept"}, expected=request)

    def test_safely_stale_reply_uses_distinct_rdd_error_subclass(self):
        request = self.approval()
        with self.server() as server:
            server.rpc("frames", {"frames": [request]})
            with self.assertRaises(RddError) as mismatch:
                server.reply(request["id"], {"decision": "accept"}, expected=self.approval(reason="wrong original"))
            self.assertEqual(type(mismatch.exception).__name__, "StaleRequestError")
            server.rpc("frames", {"frames": [{"method": "serverRequest/resolved", "params": {
                "threadId": "thread-a", "requestId": request["id"]}}]})
            with self.assertRaises(RddError) as resolved:
                server.reply(request["id"], {"decision": "accept"}, expected=request)
            self.assertEqual(type(resolved.exception).__name__, "StaleRequestError")

    def test_queued_reply_timeout_is_fatal_error_not_safely_stale(self):
        probe = self.probe(reply_timeout=.03)
        holding, hold_errors = self.run_background(lambda: probe.server._send({"method": "holding"}, time.monotonic() + 2))
        self.assertTrue(probe.started.wait(1))
        request = self.approval()
        probe.feed(request)
        with self.assertRaisesRegex(RddError, "timed out") as expired:
            probe.server.reply(request["id"], {"decision": "accept"}, expected=request)
        self.assertNotEqual(type(expired.exception).__name__, "StaleRequestError")
        self.assertFalse(probe.server.request_pending(request["id"], expected=request))
        probe.release.set()
        holding.join(timeout=1)
        self.wait_writes(probe.server, 0)
        self.assertEqual(hold_errors, [])
        self.assertEqual(probe.frames, [{"method": "holding"}])

    def test_queued_resolution_cancellation_is_distinct_safely_stale_error(self):
        probe = self.probe()
        holding, hold_errors = self.run_background(lambda: probe.server._send({"method": "holding"}, time.monotonic() + 2))
        self.assertTrue(probe.started.wait(1))
        request = self.approval()
        probe.feed(request)
        replying, errors = self.run_background(lambda: probe.server.reply(request["id"], {"decision": "accept"}, expected=request))
        self.wait_writes(probe.server, 2)
        probe.feed({"method": "serverRequest/resolved", "params": {"threadId": "thread-a", "requestId": request["id"]}})
        probe.release.set()
        holding.join(timeout=1)
        replying.join(timeout=1)
        self.assertEqual(hold_errors, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RddError)
        self.assertEqual(type(errors[0]).__name__, "StaleRequestError")
        self.assertEqual(probe.frames, [{"method": "holding"}])

    def test_out_of_order_responses_keep_request_correlation(self):
        results = {}
        errors = []
        with self.server() as server:
            def call(index):
                try:
                    results[index] = server.rpc("paired", {"index": index}, timeout=2)
                except Exception as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=call, args=(index,)) for index in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(results, {0: {"index": 0}, 1: {"index": 1}})

    def test_rpc_error_is_safe_and_recoverable(self):
        with self.server() as server:
            with self.assertRaisesRegex(RddError, "-32602") as failure:
                server.rpc("error", {})
            self.assertEqual(failure.exception.kind, "environment")
            self.assertNotIn("secret", str(failure.exception))
            self.assertEqual(server.rpc("echo", {"still": "connected"}), {"still": "connected"})
        self.assertIn(b"secret-stderr-token", (self.log_dir / "stderr.log").read_bytes())

    def test_eof_and_invalid_json_have_safe_failures(self):
        for method, expected in (("eof", "EOF"), ("invalid-json", "JSON")):
            with self.subTest(method=method):
                self.log_dir = self.root / ".rdd/evidence" / method
                with self.server() as server:
                    with self.assertRaisesRegex(RddError, expected) as failure:
                        server.rpc(method, {}, timeout=1)
                    self.assertNotIn("secret", str(failure.exception))

    def test_timeout_does_not_misroute_late_response(self):
        with self.server() as server:
            with self.assertRaisesRegex(RddError, "timed out"):
                server.rpc("slow", {}, timeout=.02)
            self.assertEqual(server.rpc("echo", {"current": True}, timeout=1), {"current": True})

    def test_response_and_events_survive_immediate_eof(self):
        with self.server() as server:
            self.assertEqual(server.rpc("result-eof", {}), {"complete": True})
            self.assertEqual(server.next_event(1), {"method": "item/updated", "params": {"before_exit": True}})
            with self.assertRaisesRegex(RddError, "EOF"):
                server.next_event(1)

    def test_shutdown_reaps_owned_process_with_separate_budget(self):
        server = self.server()
        with server:
            server.rpc("hang", {})
            started = time.monotonic()
        self.assertLess(time.monotonic() - started, 7)
        self.assertIsNotNone(server.process.poll())
        self.assertFalse(any(thread.is_alive() for thread in server._threads))
        server.close()

    @unittest.skipUnless(os.name == "posix", "POSIX owned-process-group cleanup")
    def test_owned_group_cleanup_after_parent_exit_with_descendant_pipe(self):
        server = self.server()
        with server:
            reply = server.rpc("orphan", {})
            self.assertEqual(server.next_event(1)["params"]["pid"], reply["child"])
            server.process.wait(timeout=1)
        self.assertFalse(any(thread.is_alive() for thread in server._threads))
        self.assertIsNone(server.cleanup_error)

    def test_unsupported_version_fails_before_starting_server(self):
        for index, version in enumerate(("0.162.0", "0.163.0", "0.161.0-preview.1", "0.162.1-preview.1",
                                         "0.162.1+metadata", "0.162", "v0.162.1", "00.162.1",
                                         "0.162.1\nextra output")):
            with self.subTest(version=version):
                self.options(version=version)
                self.log_dir = self.root / ".rdd/evidence" / str(index)
                server = self.server()
                with self.assertRaisesRegex(RddError, "qualified") as failure:
                    with server:
                        self.fail("Unsupported runtime accepted")
                self.assertEqual(failure.exception.kind, "environment")
                for supported in ("0.161.0", "0.162.1"):
                    self.assertIn(supported, str(failure.exception))
                self.assertIsNone(server.process)
                self.assertFalse((self.root / "transcript.jsonl").exists())

    def test_missing_executable_lists_qualified_versions(self):
        with patch("tools.rdd.app_server.shutil.which", return_value=None):
            with self.assertRaisesRegex(RddError, "executable not found") as failure:
                with self.server():
                    self.fail("Missing executable accepted")
        self.assertEqual(failure.exception.kind, "environment")
        for supported in ("0.161.0", "0.162.1"):
            self.assertIn(supported, str(failure.exception))
        self.assertFalse((self.root / "transcript.jsonl").exists())

    def test_version_probe_hang_uses_startup_budget_and_reaps(self):
        self.options(version_hang=True)
        with patch("tools.rdd.app_server.STARTUP_TIMEOUT", .2):
            started = time.monotonic()
            with self.assertRaisesRegex(RddError, "startup timed out"):
                with self.server():
                    self.fail("Hanging version probe accepted")
            self.assertLess(time.monotonic() - started, 4)

    @unittest.skipUnless(os.name == "posix", "POSIX owned-process-group cleanup")
    def test_version_parent_exit_still_terminates_owned_descendant(self):
        self.options(version_orphan=True)
        child = None
        try:
            with patch("tools.rdd.app_server.STARTUP_TIMEOUT", .2):
                with self.assertRaisesRegex(RddError, "startup timed out"):
                    with self.server():
                        self.fail("Version descendant accepted")
            child = json.loads((self.root / "version-child.json").read_text())
            stopped = False
            deadline = time.monotonic() + .5
            while time.monotonic() < deadline:
                try:
                    os.kill(child["pid"], 0)
                except ProcessLookupError:
                    stopped = True
                    break
                time.sleep(.01)
            self.assertTrue(stopped, "version descendant remains alive after timed-out parent exit")
        finally:
            if child is None and (self.root / "version-child.json").exists():
                child = json.loads((self.root / "version-child.json").read_text())
            if child is not None:
                try:
                    os.killpg(child["group"], signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_event_queue_flood_fails_without_coalescing_admitted_events(self):
        # All decoded events, including the frame crossing the limit, remain
        # retrievable. Further reading stops with an explicit capacity failure.
        with patch("tools.rdd.app_server.MAX_EVENT_COUNT", 4, create=True):
            with self.server() as server:
                with self.assertRaisesRegex(RddError, "event queue.*capacity"):
                    server.rpc("event-flood", {})
                events = [server.next_event(0) for _ in range(5)]
                self.assertEqual([event["params"]["ordinal"] for event in events], [1, 2, 3, 4, 5])
                with self.assertRaisesRegex(RddError, "capacity"):
                    server.next_event(0)

    def test_event_queue_byte_limit_is_explicit_and_retains_frame(self):
        with patch("tools.rdd.app_server.MAX_EVENT_BYTES", 100, create=True):
            with self.server() as server:
                with self.assertRaisesRegex(RddError, "event queue.*capacity"):
                    server.rpc("event-flood", {"size": 100})
                self.assertEqual(server.next_event(0)["params"], {"ordinal": 1, "text": "雪" * 100})

    def test_outgoing_queue_byte_limit_stops_without_sending_request(self):
        with patch("tools.rdd.app_server.MAX_WRITE_BYTES", 1024):
            with self.server() as server:
                with self.assertRaisesRegex(RddError, "write queue.*capacity"):
                    server.rpc("echo", {"text": "x" * 2000})
        self.assertFalse(any(item.get("method") == "echo" for item in self.transcript()))

    def test_blocked_writer_pending_count_limit_is_recoverable(self):
        self.options(no_read=True)
        errors = []
        with patch("tools.rdd.app_server.MAX_PENDING_WRITES", 2):
            with self.server() as server:
                def call():
                    try:
                        server.rpc("echo", {"text": "x" * 1000000}, timeout=2)
                    except RddError as exc:
                        errors.append(exc)
                threads = [threading.Thread(target=call) for _ in range(2)]
                for thread in threads:
                    thread.start()
                # The in-flight blocked write counts alongside queued writes.
                deadline = time.monotonic() + 1
                with server._condition:
                    while server._write_count != 2 and time.monotonic() < deadline:
                        server._condition.wait(.01)
                    self.assertEqual(server._write_count, 2)
                with self.assertRaisesRegex(RddError, "write queue.*capacity"):
                    server.rpc("echo", {}, timeout=1)
                for thread in threads:
                    thread.join(timeout=1)
                self.assertFalse(any(thread.is_alive() for thread in threads))
                self.assertEqual(len(errors), 2)
                self.assertTrue(all("capacity" in str(error) for error in errors))

    def test_startup_deadline_and_blocked_stdin_are_bounded(self):
        self.options(initialize_hang=True)
        with patch("tools.rdd.app_server.STARTUP_TIMEOUT", .2):
            started = time.monotonic()
            with self.assertRaisesRegex(RddError, "timed out"):
                with self.server():
                    self.fail("Hanging startup accepted")
            self.assertLess(time.monotonic() - started, 4)
        self.options(no_read=True)
        self.log_dir = self.root / ".rdd/evidence/blocked-stdin"
        with self.server() as server:
            started = time.monotonic()
            with self.assertRaisesRegex(RddError, "timed out"):
                server.rpc("echo", {"large": "x" * 2000000}, timeout=.05)
            self.assertLess(time.monotonic() - started, .5)

    def test_logs_are_bounded_and_stderr_is_separate(self):
        with patch("tools.rdd.app_server.MAX_LOG_BYTES", 512):
            with self.server() as server:
                self.assertEqual(server.rpc("flood", {}), {"done": True})
            self.assertIn("stderr", getattr(server, "log_truncated", set()))
        self.assertEqual((self.log_dir / "stderr.log").stat().st_size, 512)
        for path in self.log_dir.iterdir():
            self.assertLessEqual(path.stat().st_size, 512)
        self.assertNotIn(b"x" * 512, (self.log_dir / "stdout.log").read_bytes())


if __name__ == "__main__":
    unittest.main()
