"""Owned Codex App Server stdio transport; workflow policy belongs to the caller."""
from __future__ import annotations

from collections import deque
import contextlib
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any

from .common import RddError, file_hash


QUALIFIED_VERSIONS = ("0.161.0", "0.162.1")
STARTUP_TIMEOUT = 60.0
SHUTDOWN_TIMEOUT = 6.0
MAX_LOG_BYTES = 4 * 1024 * 1024
MAX_FRAME_BYTES = 16 * 1024 * 1024
MAX_EVENT_COUNT = 4096
MAX_EVENT_BYTES = 16 * 1024 * 1024
MAX_PENDING_WRITES = 64
MAX_WRITE_BYTES = 32 * 1024 * 1024


class AppServer:
    """JSON-lines RPC with unchanged inherited environment and native config.

    Entering the context starts and initializes the server. Notifications and
    server requests retain arrival order, including requests the caller cannot
    authorize. No approval or tool request is answered automatically. Runtime
    identity describes the local executable, never backend model attestation.
    An argv prefix may be supplied as ``binary`` for a portable test launcher.
    """

    def __init__(self, root: str | Path, binary=None, log_dir: str | Path | None = None):
        self.root = Path(root).resolve()
        self.binary = binary
        self.log_dir = Path(log_dir).resolve() if log_dir is not None else None
        self.effective_config: dict[str, Any] = {}
        self.runtime_identity: dict[str, str] = {}
        self.log_truncated: set[str] = set()
        self.process: subprocess.Popen | None = None
        self.cleanup_error: str | None = None
        self._condition = threading.Condition()
        self._writes: queue.Queue = queue.Queue(maxsize=MAX_PENDING_WRITES + 1)
        self._write_count = 0
        self._write_bytes = 0
        self._events: deque[tuple[dict, int]] = deque()
        self._event_bytes = 0
        self._responses: dict[int, dict] = {}
        self._pending: set[int] = set()
        self._timed_out: set[int] = set()
        self._server_requests: set[int | str] = set()
        self._sequence = 0
        self._failure: str | None = None
        self._eof = False
        self._closed = False
        self._threads: list[threading.Thread] = []
        self._logs: dict[str, Any] = {}
        self._log_sizes: dict[str, int] = {}
        self._log_lock = threading.Lock()

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.close()
        except RddError:
            if exc_type is None:
                raise

    @staticmethod
    def _timeout(value, *, zero=False) -> float:
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or value < 0 or (value == 0 and not zero)):
            raise RddError("App Server timeout must be finite and positive", "environment")
        return float(value)

    @staticmethod
    def _remaining(deadline: float, operation: str) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RddError(f"App Server {operation} timed out", "environment")
        return remaining

    def _launch_options(self) -> dict:
        # No env/config/credential or permission-policy overrides.
        options = {"cwd": self.root, "stdin": subprocess.PIPE,
                   "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                   "bufsize": 0, "shell": False}
        if os.name == "posix":
            options["start_new_session"] = True
        elif os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        return options

    def _signal_owned(self, process, *, force: bool, deadline: float) -> None:
        if os.name == "posix":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif process.poll() is None:
            # Address only the process tree started by this instance.
            # Terminating the Windows parent first would lose /T's tree lookup.
            try:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, check=False, shell=False,
                               timeout=max(.01, deadline - time.monotonic()))
            except (OSError, subprocess.TimeoutExpired):
                process.kill()

    def _version(self, command: list[str], deadline: float) -> str:
        probe = None
        communication_failed = False
        try:
            probe = subprocess.Popen([*command, "--version"], **self._launch_options())
            output, stderr = probe.communicate(timeout=self._remaining(deadline, "startup"))
            self._log("stderr", stderr)
            if probe.returncode:
                raise RddError("Cannot determine Codex version; check the installed executable", "environment")
            match = re.fullmatch(rb"codex-cli ([0-9]+\.[0-9]+\.[0-9]+)\s*", output)
            if not match or match[1].decode("ascii") not in QUALIFIED_VERSIONS:
                raise RddError(f"App Server requires qualified codex-cli {' or '.join(QUALIFIED_VERSIONS)}; install a qualified release or qualify the installed runtime before retrying", "environment")
            return match[1].decode("ascii")
        except subprocess.TimeoutExpired:
            communication_failed = True
            raise RddError("App Server startup timed out determining Codex version", "environment") from None
        except OSError:
            raise RddError("Cannot execute Codex; check the executable and host permissions", "environment") from None
        finally:
            # A reaped parent can leave a descendant holding a captured pipe.
            if probe is not None and (communication_failed or probe.poll() is None):
                cleanup_deadline = time.monotonic() + SHUTDOWN_TIMEOUT
                self._signal_owned(probe, force=True, deadline=cleanup_deadline)
                try:
                    probe.wait(timeout=max(.01, cleanup_deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    raise RddError("Could not reap the owned Codex version process", "environment") from None
            if probe is not None:
                for pipe in (probe.stdin, probe.stdout, probe.stderr):
                    if pipe is not None:
                        pipe.close()

    def start(self):
        if self.process is not None or self._closed:
            raise RddError("App Server instances can be started only once", "environment")
        deadline = time.monotonic() + STARTUP_TIMEOUT
        try:
            if not self.root.is_dir():
                raise RddError("App Server working directory does not exist", "environment")
            command = ["codex"] if self.binary is None else ([os.fspath(self.binary)] if isinstance(self.binary, (str, os.PathLike)) else list(self.binary))
            if not command or any(not isinstance(part, str) or not part or "\0" in part for part in command):
                raise RddError("App Server requires a nonempty executable argv", "environment")
            executable = shutil.which(command[0])
            if executable is None:
                raise RddError(f"Codex executable not found; install qualified codex-cli {' or '.join(QUALIFIED_VERSIONS)} or supply its path", "environment")
            command[0] = str(Path(executable).resolve())
            if self.log_dir is None:
                self.log_dir = Path(tempfile.mkdtemp(prefix="rdd-app-server-"))
            self.log_dir.mkdir(parents=True, exist_ok=True)
            for name in ("stdin", "stdout", "stderr"):
                self._logs[name] = (self.log_dir / f"{name}.log").open("xb")
                self._log_sizes[name] = 0
            version = self._version(command, deadline)
            self.runtime_identity = {"version": version, "executable": command[0],
                                     "executable_sha256": file_hash(Path(command[0]))}
            self._remaining(deadline, "startup")
            self.process = subprocess.Popen([*command, "app-server", "--listen", "stdio://"], **self._launch_options())
            self._threads = [threading.Thread(target=target, name=f"rdd-app-server-{name}", daemon=True)
                             for name, target in (("stdout", self._read_stdout),
                                                  ("stderr", self._read_stderr),
                                                  ("stdin", self._write_stdin))]
            for thread in self._threads:
                thread.start()
            self.rpc("initialize", {"clientInfo": {"name": "rdd_workflow", "version": "0.1.0"},
                                    "capabilities": {"experimentalApi": True}},
                     timeout=self._remaining(deadline, "startup"))
            self._send({"method": "initialized", "params": {}}, deadline)
            result = self.rpc("config/read", {"cwd": str(self.root), "includeLayers": False},
                              timeout=self._remaining(deadline, "startup"))
            if not isinstance(result, dict) or not isinstance(result.get("config"), dict):
                raise RddError("App Server returned invalid effective configuration", "environment")
            self.effective_config = result["config"]
            return self
        except (OSError, TypeError, ValueError):
            with contextlib.suppress(RddError):
                self.close()
            raise RddError("Cannot start App Server; check its executable and diagnostic directory", "environment") from None
        except Exception:
            with contextlib.suppress(RddError):
                self.close()
            raise

    def _log(self, name: str, data: bytes) -> None:
        with self._log_lock:
            available = max(0, MAX_LOG_BYTES - self._log_sizes[name])
            if len(data) > available:
                self.log_truncated.add(name)
            if available:
                captured = data[:available]
                self._logs[name].write(captured)
                self._logs[name].flush()
                self._log_sizes[name] += len(captured)

    def _fail(self, reason: str) -> None:
        with self._condition:
            if self._failure is None:
                self._failure = reason
            self._condition.notify_all()

    def _check(self) -> None:
        if self._failure:
            raise RddError(self._failure, "environment")
        if self._closed or self.process is None:
            raise RddError("App Server is not running", "environment")
        if self._eof:
            raise RddError("App Server stdout EOF; inspect the bounded stderr log", "environment")

    def _read_stdout(self) -> None:
        try:
            while True:
                line = self.process.stdout.readline(MAX_FRAME_BYTES + 1)
                if not line:
                    break
                self._log("stdout", line)
                if len(line) > MAX_FRAME_BYTES or not line.endswith(b"\n"):
                    self._fail("App Server invalid or oversized JSON frame")
                    break
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeError, ValueError):
                    self._fail("App Server returned invalid UTF-8 JSON")
                    break
                if not isinstance(message, dict):
                    self._fail("App Server JSON message must be an object")
                    break
                with self._condition:
                    if "method" in message and isinstance(message["method"], str):
                        if "id" in message:
                            ident = message["id"]
                            if not isinstance(ident, (str, int)) or isinstance(ident, bool):
                                self._fail("App Server returned an invalid request ID")
                                break
                            self._server_requests.add(ident)
                        self._events.append((message, len(line)))
                        self._event_bytes += len(line)
                        if len(self._events) > MAX_EVENT_COUNT or self._event_bytes > MAX_EVENT_BYTES:
                            # Preserve every admitted frame, including this one.
                            # Stop reading explicitly rather than silently lose
                            # or coalesce notifications while another RPC waits.
                            self._fail("App Server event queue exceeded capacity; stop and reconnect")
                            break
                    elif ("id" in message and isinstance(message["id"], int)
                          and not isinstance(message["id"], bool)
                          and (("result" in message) != ("error" in message))):
                        ident = message["id"]
                        if ident in self._timed_out:
                            self._timed_out.remove(ident)
                        elif ident in self._pending and ident not in self._responses:
                            self._responses[ident] = message
                        else:
                            self._fail("App Server returned an uncorrelated response ID")
                            break
                    else:
                        self._fail("App Server returned an invalid RPC message")
                        break
                    self._condition.notify_all()
        except (OSError, ValueError):
            if not self._closed:
                self._fail("App Server stdout read or log failed")
        finally:
            self.process.stdout.close()
            with self._condition:
                self._eof = True
                self._condition.notify_all()

    def _read_stderr(self) -> None:
        try:
            while True:
                data = self.process.stderr.read(65536)
                if not data:
                    break
                self._log("stderr", data)
        except (OSError, ValueError):
            if not self._closed:
                self._fail("App Server stderr read or log failed")
        finally:
            self.process.stderr.close()

    def _write_stdin(self) -> None:
        while True:
            entry = self._writes.get()
            if entry is None:
                break
            data, finished = entry
            size = len(data)
            try:
                self._log("stdin", data)
                while data:
                    written = self.process.stdin.write(data)
                    if not written:
                        raise BrokenPipeError
                    data = data[written:]
            except (OSError, ValueError):
                if not self._closed:
                    self._fail("App Server stdin write or log failed")
                break
            finally:
                with self._condition:
                    self._write_count -= 1
                    self._write_bytes -= size
                    finished.set()
                    self._condition.notify_all()

    def _send(self, message: dict, deadline: float) -> None:
        try:
            data = json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
        except (TypeError, ValueError, UnicodeError):
            raise RddError("App Server request must contain valid UTF-8 JSON data", "environment") from None
        if len(data) > MAX_FRAME_BYTES:
            raise RddError("App Server request exceeds the JSON frame limit", "environment")
        with self._condition:
            self._check()
            if self._write_count >= MAX_PENDING_WRITES or self._write_bytes + len(data) > MAX_WRITE_BYTES:
                self._fail("App Server write queue exceeded capacity; stop and reconnect")
                raise RddError(self._failure, "environment")
            finished = threading.Event()
            self._write_count += 1
            self._write_bytes += len(data)
            self._writes.put_nowait((data, finished))
            while not finished.is_set():
                if self._failure:
                    raise RddError(self._failure, "environment")
                if self._closed:
                    raise RddError("App Server is not running", "environment")
                self._condition.wait(self._remaining(deadline, "write"))
            # A final response can arrive immediately before EOF. Let rpc read
            # that correlated response rather than replacing it with an EOF.
            if self._failure:
                raise RddError(self._failure, "environment")

    def rpc(self, method: str, params: dict, timeout: float = 60):
        deadline = time.monotonic() + self._timeout(timeout)
        if not isinstance(method, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", method):
            raise RddError("App Server RPC method is invalid", "environment")
        with self._condition:
            self._check()
            self._sequence += 1
            ident = self._sequence
            self._pending.add(ident)
        received = False
        try:
            self._send({"id": ident, "method": method, "params": params}, deadline)
            with self._condition:
                while ident not in self._responses:
                    self._check()
                    self._condition.wait(self._remaining(deadline, f"RPC {method}"))
                response = self._responses.pop(ident)
                received = True
                if "error" in response:
                    error = response["error"]
                    code = error.get("code") if isinstance(error, dict) else None
                    suffix = f" (code {code})" if isinstance(code, int) and not isinstance(code, bool) else ""
                    raise RddError(f"App Server RPC {method} failed{suffix}; inspect bounded diagnostics", "environment")
                return response["result"]
        finally:
            with self._condition:
                self._pending.discard(ident)
                if not received:
                    self._responses.pop(ident, None)
                    self._timed_out.add(ident)

    def next_event(self, timeout: float = 1):
        deadline = time.monotonic() + self._timeout(timeout, zero=True)
        with self._condition:
            while not self._events:
                self._check()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            message, size = self._events.popleft()
            self._event_bytes -= size
            return message

    def reply(self, request_id, result) -> None:
        with self._condition:
            self._check()
            if request_id not in self._server_requests:
                raise RddError("App Server reply requires an outstanding server request ID", "environment")
        self._send({"id": request_id, "result": result}, time.monotonic() + 60)
        with self._condition:
            self._server_requests.remove(request_id)

    def close(self) -> None:
        """Bounded cleanup independent of an expired operation/startup deadline."""
        if self._closed:
            return
        deadline = time.monotonic() + SHUTDOWN_TIMEOUT
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._writes.put(None)
        process = self.process
        if process is not None:
            if process.stdin is not None:
                with contextlib.suppress(OSError):
                    process.stdin.close()
            try:
                process.wait(timeout=min(.4, max(.01, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass
            readers = self._threads[:2]
            if process.poll() is None or any(thread.is_alive() for thread in readers):
                self._signal_owned(process, force=False, deadline=deadline)
                try:
                    process.wait(timeout=min(1, max(.01, deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    pass
            if process.poll() is None or any(thread.is_alive() for thread in readers):
                self._signal_owned(process, force=True, deadline=deadline)
            try:
                process.wait(timeout=max(.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                self.cleanup_error = "Could not reap the owned App Server process"
            for thread in self._threads:
                thread.join(timeout=max(0, deadline - time.monotonic()))
            if any(thread.is_alive() for thread in self._threads):
                self.cleanup_error = "Owned App Server stream threads did not stop within cleanup deadline"
        with self._log_lock:
            for stream in self._logs.values():
                stream.close()
        if self.cleanup_error:
            raise RddError(self.cleanup_error, "environment")
