"""Actual subprocess stdio tests; no model calls, config writes, or approval replies."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

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
