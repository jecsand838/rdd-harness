"""Store lifecycle regressions with real SQLite and independent child writers."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from tools.rdd import common


CHILD_EDIT = """from pathlib import Path
import sys
from tools.rdd.common import Store
store = Store(Path(sys.argv[1]))
try:
    with store.edit('fixture') as state:
        state['child_writes'] += 1
        state['payload'] += 'y' * int(sys.argv[2])
finally:
    store.close()
"""


class FaultConnection:
    """Inject at SQL/close boundaries while retaining real transaction semantics."""
    def __init__(self, db, statement=None, error=None, *, rollback_error=None, close_error=None,
                 fetch_error=None, close_before_error=True):
        self.db = db
        self.statement = statement
        self.error = error
        self.rollback_error = rollback_error
        self.close_error = close_error
        self.fetch_error = fetch_error
        self.close_before_error = close_before_error
        self.statements = []
        self.closes = 0
        self.transaction_at_close = None

    @property
    def in_transaction(self):
        return self.db.in_transaction

    def execute(self, sql, *args):
        self.statements.append(sql)
        if sql.startswith("ROLLBACK") and self.rollback_error is not None:
            raise self.rollback_error
        if self.statement is not None and sql.startswith(self.statement):
            raise self.error
        cursor = self.db.execute(sql, *args)
        if sql.startswith("SELECT") and self.fetch_error is not None:
            return self
        return cursor

    def fetchone(self):
        raise self.fetch_error

    def close(self):
        self.closes += 1
        self.transaction_at_close = self.db.in_transaction
        if self.close_error is not None and not self.close_before_error:
            raise self.close_error
        self.db.close()
        if self.close_error is not None:
            raise self.close_error


class StoreTests(unittest.TestCase):
    def setUp(self):
        # Storage faults are isolated test invocations; production never resets
        # the process-local guard after a close whose release is unconfirmed.
        guard = patch.object(common, "_STORE_CLOSE_FAILURE", None, create=True)
        guard.start()
        self.addCleanup(guard.stop)
        directory = tempfile.TemporaryDirectory(prefix="rdd-store-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / ".rdd/runtime/state.sqlite3"
        self.store = common.Store(self.root)
        self.addCleanup(self.store.close)

    def seed(self):
        self.store.put(dict(id="fixture", child_writes=0, parent_writes=0, payload="x" * 10))

    def source_files(self):
        return {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns)
                for p in self.path.parent.iterdir()} if self.path.parent.exists() else {}

    def child_edit(self, growth):
        result = subprocess.run([sys.executable, "-c", CHILD_EDIT, str(self.root), str(growth)],
                                cwd=Path(__file__).resolve().parents[2], capture_output=True,
                                text=True, timeout=15, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def fresh_state(self):
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            return json.loads(db.execute("SELECT value FROM runs WHERE id='fixture'").fetchone()[0])

    @contextlib.contextmanager
    def close_fault_fixture(self, connect):
        with patch.object(common, "_STORE_CLOSE_FAILURE", None, create=True), \
             patch.object(common.sqlite3, "connect", side_effect=connect):
            yield

    def assert_storage_blocked_before_io(self, expected):
        other = common.Store(self.root / "other")
        operations = (lambda: common.Store.read(self.root, "fixture"), lambda: self.store.get("fixture"),
                      lambda: self.store.exists("fixture"), lambda: self.store.put(dict(id="other")),
                      lambda: self.enter_edit(self.store), lambda: other.get("fixture"),
                      lambda: other.exists("fixture"), lambda: other.put(dict(id="other")),
                      lambda: self.enter_edit(other))
        with patch.object(common, "file_hash", side_effect=AssertionError("Must refuse before source reads")), \
             patch.object(Path, "exists", side_effect=AssertionError("Must refuse before source inspection")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("Must refuse before filesystem writes")), \
             patch.object(common.sqlite3, "connect", side_effect=AssertionError("Must refuse before connect")):
            for operation in operations:
                with self.assertRaises(common.RddStorageError) as caught:
                    operation()
                self.assertIs(caught.exception, expected, "Retain the first uncertain-close diagnostic")

    def test_snapshot_between_growing_child_writes_preserves_next_parent_edit(self):
        self.seed()
        self.store.get("fixture")
        with self.store.edit("fixture") as state:
            state["parent_writes"] += 1
        for _ in range(2):
            common.Store.read(self.root, "fixture")
            self.child_edit(200000)
        try:
            with self.store.edit("fixture") as state:
                self.assertEqual(state["child_writes"], 2)
                state["parent_writes"] += 1
        except sqlite3.Error as exc:
            self.fail(f"Parent edit after snapshots and child commits must succeed: {exc}")
        self.store.close()
        state = self.fresh_state()
        self.assertEqual({k: v for k, v in state.items() if k != "payload"},
                         dict(id="fixture", child_writes=2, parent_writes=2))
        self.assertEqual(state["payload"], "x" * 10 + "y" * 400000)

    def test_snapshot_between_fixed_size_child_writes_does_not_lose_updates(self):
        self.seed()
        self.store.get("fixture")
        with self.store.edit("fixture") as state:
            state["parent_writes"] += 1
        for _ in range(2):
            common.Store.read(self.root, "fixture")
            self.child_edit(0)
            with self.store.edit("fixture") as state:
                state["parent_writes"] += 1
        self.store.close()
        state = self.fresh_state()
        self.assertEqual(state["child_writes"], 2, "All committed child increments must survive")
        self.assertEqual(state["parent_writes"], 3)
        self.assertEqual(state["payload"], "x" * 10)

    def test_constructor_and_close_own_no_connection_or_files(self):
        self.assertFalse(self.path.parent.exists())
        with patch.object(common.sqlite3, "connect", side_effect=AssertionError("close must not connect")):
            self.store.close()
            self.store.close()
        self.seed()
        self.store.close()
        self.assertEqual(self.store.get("fixture")["id"], "fixture")

    def test_put_configures_and_closes_one_local_connection(self):
        real_connect = sqlite3.connect
        opened = []
        def connect(*args, **kwargs):
            db = FaultConnection(real_connect(*args, **kwargs))
            opened.append((db, kwargs))
            return db
        with patch.object(common.sqlite3, "connect", side_effect=connect):
            self.seed()
        self.assertEqual(len(opened), 1)
        db, kwargs = opened[0]
        self.assertEqual(kwargs["timeout"], 30)
        self.assertEqual(kwargs["isolation_level"], None)
        self.assertIn("PRAGMA journal_mode=WAL", db.statements)
        self.assertIn("PRAGMA synchronous=FULL", db.statements)
        self.assertEqual(db.closes, 1)
        self.assertFalse(db.transaction_at_close)

    def test_edit_uses_one_connection_for_atomic_read_and_write(self):
        self.seed()
        real_connect = sqlite3.connect
        opened = []
        def connect(*args, **kwargs):
            db = FaultConnection(real_connect(*args, **kwargs))
            opened.append(db)
            return db
        with patch.object(common.sqlite3, "connect", side_effect=connect):
            with self.store.edit("fixture") as state:
                state["parent_writes"] = 1
        self.assertEqual(len(opened), 1)
        db = opened[0]
        self.assertIn("BEGIN IMMEDIATE", db.statements)
        self.assertEqual(sum(sql.startswith("SELECT") for sql in db.statements), 1)
        self.assertEqual(sum(sql.startswith("INSERT") for sql in db.statements), 1)
        self.assertEqual(db.statements[-1], "COMMIT")
        self.assertEqual(db.closes, 1)
        self.assertEqual(self.store.get("fixture")["parent_writes"], 1)

    def test_edit_sql_failures_close_and_preserve_original_state(self):
        self.seed()
        real_connect = sqlite3.connect
        for stage in ("PRAGMA journal_mode", "PRAGMA synchronous", "CREATE TABLE", "BEGIN", "SELECT", "INSERT", "COMMIT"):
            with self.subTest(stage=stage):
                failure = sqlite3.OperationalError("injected " + stage)
                failure.sqlite_errorcode = sqlite3.SQLITE_IOERR
                failure.sqlite_errorname = "SQLITE_IOERR"
                opened = []
                def connect(*args, **kwargs):
                    db = FaultConnection(real_connect(*args, **kwargs), stage, failure)
                    opened.append(db)
                    return db
                with patch.object(common.sqlite3, "connect", side_effect=connect):
                    with self.assertRaises(common.RddError) as caught:
                        with self.store.edit("fixture") as state:
                            state["parent_writes"] = 9
                error = caught.exception
                self.assertIsInstance(error, common.RddStorageError)
                self.assertEqual(error.kind, "environment")
                self.assertEqual(error.database_path, self.path)
                self.assertEqual(error.operation, "edit")
                self.assertEqual(error.sqlite_errorcode, sqlite3.SQLITE_IOERR)
                self.assertEqual(error.sqlite_errorname, "SQLITE_IOERR")
                self.assertIs(error.__cause__, failure)
                self.assertEqual(len(opened), 1, "Uncertain writes must never be retried")
                self.assertEqual(opened[0].closes, 1)
                self.assertEqual("ROLLBACK" in opened[0].statements, stage in ("SELECT", "INSERT", "COMMIT"))
                self.assertEqual(self.store.get("fixture")["parent_writes"], 0)

    def test_connection_open_failure_is_structured_and_not_retried(self):
        failure = sqlite3.OperationalError("cannot open database")
        with patch.object(common.sqlite3, "connect", side_effect=failure) as connect:
            with self.assertRaises(common.RddError) as caught:
                self.seed()
        self.assertIsInstance(caught.exception, common.RddStorageError)
        self.assertEqual(caught.exception.operation, "put")
        self.assertIs(caught.exception.__cause__, failure)
        self.assertEqual(connect.call_count, 1)
        self.seed()

    def test_body_failure_and_interrupt_survive_cleanup_failures(self):
        self.seed()
        real_connect = sqlite3.connect
        for failure in (ValueError("body failure"), KeyboardInterrupt("interrupt"), SystemExit(130)):
            with self.subTest(failure=type(failure).__name__):
                opened = []
                def connect(*args, **kwargs):
                    db = FaultConnection(real_connect(*args, **kwargs),
                                         rollback_error=sqlite3.OperationalError("rollback failed"),
                                         close_error=sqlite3.OperationalError("close failed"))
                    opened.append(db)
                    return db
                with self.close_fault_fixture(connect):
                    with self.assertRaises(type(failure)) as caught:
                        with self.store.edit("fixture") as state:
                            state["parent_writes"] = 8
                            raise failure
                self.assertIs(caught.exception, failure)
                cleanup = failure.rdd_storage_error
                self.assertIsInstance(cleanup, common.RddStorageError)
                self.assertEqual(cleanup.kind, "environment")
                self.assertIn("rollback failed", str(cleanup))
                self.assertNotIn("close failed", str(cleanup), "Keep the first cleanup diagnostic")
                self.assertEqual(opened[0].closes, 1)
                self.assertEqual(self.store.get("fixture")["parent_writes"], 0)

    def test_sql_error_survives_rollback_and_close_failures(self):
        self.seed()
        failure = sqlite3.OperationalError("commit failed")
        real_connect = sqlite3.connect
        opened = []
        def connect(*args, **kwargs):
            db = FaultConnection(real_connect(*args, **kwargs), "COMMIT", failure,
                                 rollback_error=sqlite3.OperationalError("rollback failed"),
                                 close_error=sqlite3.OperationalError("close failed"))
            opened.append(db)
            return db
        with self.close_fault_fixture(connect):
            with self.assertRaises(common.RddError) as caught:
                with self.store.edit("fixture") as state:
                    state["parent_writes"] = 8
        self.assertIs(caught.exception.__cause__, failure)
        self.assertEqual(opened[0].closes, 1)
        self.assertEqual(self.store.get("fixture")["parent_writes"], 0)

    def test_cleanup_signal_preserves_existing_diagnostic_and_successful_rollback(self):
        self.seed()
        real_connect = sqlite3.connect
        for existing in (False, True):
            with self.subTest(existing=existing):
                primary = ValueError("caller failure")
                if existing:
                    previous = common.RddStorageError("prior cleanup", self.path, OSError("first cleanup"))
                    primary.rdd_storage_error = previous
                opened = []
                close_error = sqlite3.OperationalError("close failed")
                def connect(*args, **kwargs):
                    db = FaultConnection(real_connect(*args, **kwargs), close_error=close_error)
                    opened.append(db)
                    return db
                with self.close_fault_fixture(connect):
                    with self.assertRaises(ValueError) as caught:
                        with self.store.edit("fixture") as state:
                            state["parent_writes"] = 8
                            raise primary
                self.assertIs(caught.exception, primary)
                if existing:
                    self.assertIs(primary.rdd_storage_error, previous)
                else:
                    self.assertIs(primary.rdd_storage_error.__cause__, close_error)
                self.assertEqual(opened[0].closes, 1)
                self.assertFalse(opened[0].transaction_at_close)
                self.assertEqual(self.store.get("fixture")["parent_writes"], 0)

    def test_missing_row_rolls_back_without_becoming_storage_error(self):
        self.seed()
        with self.assertRaises(common.RddError) as caught:
            with self.store.edit("absent"):
                self.fail("Missing row must not yield")
        self.assertNotIsInstance(caught.exception, common.RddStorageError)
        with self.store.edit("fixture") as state:
            state["parent_writes"] = 1

    def test_cursor_read_failure_is_storage_error_and_closes(self):
        self.seed()
        real_connect = sqlite3.connect
        for operation in (lambda: self.store.get("fixture"), lambda: self.enter_edit(self.store)):
            with self.subTest(operation=operation):
                failure = sqlite3.OperationalError("cursor read failed")
                opened = []
                def connect(*args, **kwargs):
                    db = FaultConnection(real_connect(*args, **kwargs), fetch_error=failure)
                    opened.append(db)
                    return db
                with patch.object(common.sqlite3, "connect", side_effect=connect):
                    with self.assertRaises(common.RddError) as caught:
                        operation()
                self.assertIsInstance(caught.exception, common.RddStorageError)
                self.assertIs(caught.exception.__cause__, failure)
                self.assertTrue(all(db.closes == 1 for db in opened))

    def test_close_failure_after_success_is_reported_without_retry(self):
        failure = sqlite3.OperationalError("close failed")
        real_connect = sqlite3.connect
        opened = []
        def connect(*args, **kwargs):
            db = FaultConnection(real_connect(*args, **kwargs), close_error=failure)
            opened.append(db)
            return db
        with self.close_fault_fixture(connect):
            with self.assertRaises(common.RddError) as caught:
                self.seed()
        self.assertIsInstance(caught.exception, common.RddStorageError)
        self.assertIs(caught.exception.__cause__, failure)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0].closes, 1)
        self.assertEqual(self.store.get("fixture")["id"], "fixture")

    def test_failed_close_blocks_all_storage_until_new_process(self):
        real_connect = sqlite3.connect
        for release_first in (False, True):
            with self.subTest(release_first=release_first):
                failure = sqlite3.OperationalError("unconfirmed handle release")
                opened = []
                def connect(*args, **kwargs):
                    db = FaultConnection(real_connect(*args, **kwargs), close_error=failure,
                                         close_before_error=release_first)
                    opened.append(db)
                    return db
                try:
                    with self.close_fault_fixture(connect):
                        with self.assertRaises(common.RddStorageError) as caught:
                            self.seed()
                        self.assertIs(caught.exception.__cause__, failure)
                        self.assertEqual(len(opened), 1)
                        self.assertEqual(opened[0].closes, 1)
                        if release_first:
                            with self.assertRaises(sqlite3.ProgrammingError):
                                opened[0].db.execute("SELECT 1")
                        else:
                            self.assertEqual(opened[0].db.execute("SELECT 1").fetchone(), (1,))
                        self.assert_storage_blocked_before_io(caught.exception)
                        child = """from pathlib import Path
import json, sys
from tools.rdd.common import Store
print(json.dumps(Store.read(Path(sys.argv[1]), 'fixture')))
"""
                        result = subprocess.run([sys.executable, "-c", child, str(self.root)],
                                                cwd=Path(__file__).resolve().parents[2], capture_output=True,
                                                text=True, timeout=15, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(json.loads(result.stdout),
                                         dict(id="fixture", child_writes=0, parent_writes=0, payload="x" * 10))
                finally:
                    for db in opened:
                        db.db.close()  # Test fixture owns the deliberately retained real handle.

    def test_close_before_release_preserves_body_failure_and_cleanup_signal(self):
        self.seed()
        real_connect = sqlite3.connect
        for primary in (ValueError("body failed"), KeyboardInterrupt("body interrupted")):
            with self.subTest(primary=type(primary).__name__):
                close_error = sqlite3.OperationalError("close failed before release")
                opened = []
                def connect(*args, **kwargs):
                    db = FaultConnection(real_connect(*args, **kwargs), close_error=close_error,
                                         close_before_error=False)
                    opened.append(db)
                    return db
                with self.close_fault_fixture(connect):
                    try:
                        with self.assertRaises(type(primary)) as caught:
                            with self.store.edit("fixture") as state:
                                state["parent_writes"] = 8
                                raise primary
                        self.assertIs(caught.exception, primary)
                        self.assertIs(primary.rdd_storage_error.__cause__, close_error)
                        self.assertEqual(opened[0].db.execute("SELECT 1").fetchone(), (1,))
                        self.assertFalse(opened[0].transaction_at_close, "Rollback completed before failed close")
                        self.assert_storage_blocked_before_io(primary.rdd_storage_error)
                    finally:
                        for db in opened:
                            db.db.close()
                self.assertEqual(self.store.get("fixture")["parent_writes"], 0)

    def test_close_interrupt_preserves_interrupt_and_blocks_storage(self):
        real_connect = sqlite3.connect
        interrupt = KeyboardInterrupt("close interrupted before release")
        opened = []
        def connect(*args, **kwargs):
            db = FaultConnection(real_connect(*args, **kwargs), close_error=interrupt,
                                 close_before_error=False)
            opened.append(db)
            return db
        with self.close_fault_fixture(connect):
            try:
                with self.assertRaises(KeyboardInterrupt) as caught:
                    self.seed()
                self.assertIs(caught.exception, interrupt)
                self.assertIs(interrupt.rdd_storage_error.__cause__, interrupt)
                self.assertEqual(opened[0].db.execute("SELECT 1").fetchone(), (1,))
                self.assert_storage_blocked_before_io(interrupt.rdd_storage_error)
            finally:
                for db in opened:
                    db.db.close()

    def test_filesystem_initialization_failure_is_structured(self):
        failure = PermissionError("cannot create runtime directory")
        with patch.object(Path, "mkdir", side_effect=failure), \
             patch.object(common.sqlite3, "connect", side_effect=AssertionError("Must not open")):
            with self.assertRaises(common.RddError) as caught:
                self.seed()
        self.assertIsInstance(caught.exception, common.RddStorageError)
        self.assertIs(caught.exception.__cause__, failure)
        self.assertFalse(self.path.parent.exists())

    def test_initialization_and_begin_interrupts_close_and_release_lock(self):
        self.seed()
        real_connect = sqlite3.connect
        for stage in ("PRAGMA journal_mode", "CREATE TABLE", "BEGIN"):
            with self.subTest(stage=stage):
                failure = KeyboardInterrupt("injected interrupt")
                opened = []
                def connect(*args, **kwargs):
                    db = FaultConnection(real_connect(*args, **kwargs), stage, failure)
                    opened.append(db)
                    return db
                with patch.object(common.sqlite3, "connect", side_effect=connect):
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        self.enter_edit(self.store)
                self.assertIs(caught.exception, failure)
                self.assertEqual(opened[0].closes, 1)
                self.assertNotIn("ROLLBACK", opened[0].statements)
                self.assertEqual(self.store.get("fixture")["parent_writes"], 0)

    def test_initialization_and_snapshot_connection_reentrancy_rejected_before_io(self):
        self.seed()
        real_connect = sqlite3.connect
        other = common.Store(self.root / "other")
        failures = []
        def connect(*args, **kwargs):
            with patch.object(common, "file_hash", side_effect=AssertionError("Must reject before IO")):
                try:
                    other.get("fixture")
                except common.RddError as exc:
                    failures.append(exc)
                else:
                    self.fail("Reentrant read must fail")
            return real_connect(*args, **kwargs)
        with patch.object(common.sqlite3, "connect", side_effect=connect):
            self.seed()
            self.store.get("fixture")
        self.assertEqual(len(failures), 2)
        self.assertTrue(all(not isinstance(exc, common.RddStorageError) for exc in failures))
        self.assertFalse(other.path.parent.exists())

    def test_reentrant_operations_across_stores_fail_before_file_io(self):
        self.seed()
        other = common.Store(self.root)
        self.addCleanup(other.close)
        with self.store.edit("fixture") as state:
            operations = (lambda: self.store.get("fixture"), lambda: common.Store.read(self.root, "fixture"),
                          lambda: other.exists("fixture"), lambda: other.put(dict(id="other")),
                          lambda: self.enter_edit(other))
            with patch.object(common, "file_hash", side_effect=AssertionError("Must reject before IO")), \
                 patch.object(common.sqlite3, "connect", side_effect=AssertionError("Must reject before connect")):
                for operation in operations:
                    with self.assertRaises(common.RddError) as caught:
                        operation()
                    self.assertNotIsInstance(caught.exception, common.RddStorageError)
                    self.assertIn("reentrant", str(caught.exception).lower())
            state["parent_writes"] = 1
        self.assertEqual(self.store.get("fixture")["parent_writes"], 1)

    @staticmethod
    def enter_edit(store):
        with store.edit("fixture"):
            pass

    def test_other_thread_waits_until_edit_closes(self):
        self.seed()
        started = threading.Event()
        finished = threading.Event()
        results = []
        def reader():
            started.set()
            try:
                results.append(common.Store.read(self.root, "fixture"))
            except BaseException as exc:
                results.append(exc)
            finally:
                finished.set()
        with self.store.edit("fixture") as state:
            thread = threading.Thread(target=reader)
            thread.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(finished.wait(0.1), "Reader must wait through transaction and close")
            state["parent_writes"] = 7
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]["parent_writes"], 7)

    def test_get_delegates_to_snapshot_read(self):
        expected = {"id": "fixture"}
        with patch.object(common.Store, "read", return_value=expected) as read:
            self.assertIs(self.store.get("fixture"), expected)
        read.assert_called_once_with(self.root, "fixture")

    def test_exists_missing_database_and_row_do_not_create_source_artifacts(self):
        self.assertFalse(self.store.exists("absent"))
        self.assertFalse(self.path.parent.exists())
        self.seed()
        before = self.source_files()
        self.assertFalse(self.store.exists("absent"))
        self.assertTrue(self.store.exists("fixture"))
        self.assertEqual(self.source_files(), before)

    def test_exists_filesystem_failure_is_structured(self):
        failure = PermissionError("cannot inspect database")
        with patch.object(Path, "exists", side_effect=failure):
            with self.assertRaises(common.RddError) as caught:
                self.store.exists("fixture")
        self.assertIsInstance(caught.exception, common.RddStorageError)
        self.assertEqual(caught.exception.operation, "exists")
        self.assertIs(caught.exception.__cause__, failure)

    def test_snapshot_preserves_database_and_wal_bytes_and_metadata(self):
        self.seed()
        # Child exits without closing: WAL has committed content and no active
        # connection in this process. Snapshot must recover only its own copy.
        child = """import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute('PRAGMA journal_mode=WAL')
db.execute('UPDATE runs SET value=? WHERE id=?', ('{"id":"fixture","value":42}', 'fixture'))
os._exit(0)
"""
        result = subprocess.run([sys.executable, "-c", child, str(self.path)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.path.with_name(self.path.name + "-shm").unlink(missing_ok=True)
        self.assertTrue(self.path.with_name(self.path.name + "-wal").exists())
        before = self.source_files()
        self.assertEqual(common.Store.read(self.root, "fixture")["value"], 42)
        self.assertEqual(self.store.get("fixture")["value"], 42)
        self.assertTrue(self.store.exists("fixture"))
        self.assertEqual(self.source_files(), before)

    def test_snapshot_query_closes_on_failure_and_interrupt(self):
        self.seed()
        real_connect = sqlite3.connect
        for failure in (sqlite3.OperationalError("read failed"), KeyboardInterrupt("read interrupted")):
            with self.subTest(failure=type(failure).__name__):
                opened = []
                def connect(*args, **kwargs):
                    db = FaultConnection(real_connect(*args, **kwargs), "SELECT", failure)
                    opened.append(db)
                    return db
                expected = common.RddError if isinstance(failure, sqlite3.Error) else type(failure)
                with patch.object(common.sqlite3, "connect", side_effect=connect):
                    with self.assertRaises(expected) as caught:
                        common.Store.read(self.root, "fixture")
                if isinstance(failure, sqlite3.Error):
                    self.assertIsInstance(caught.exception, common.RddStorageError)
                    self.assertIs(caught.exception.__cause__, failure)
                else:
                    self.assertIs(caught.exception, failure)
                self.assertEqual(len(opened), 1, "Do not retry SQLite read failures")
                self.assertTrue(all(db.closes == 1 for db in opened))
                self.assertEqual(self.store.get("fixture")["id"], "fixture")

    def test_snapshot_close_failure_is_not_retried(self):
        self.seed()
        before = self.source_files()
        failure = sqlite3.OperationalError("snapshot close failed")
        real_connect = sqlite3.connect
        opened = []
        def connect(*args, **kwargs):
            db = FaultConnection(real_connect(*args, **kwargs), close_error=failure)
            opened.append(db)
            return db
        with self.close_fault_fixture(connect):
            with self.assertRaises(common.RddStorageError) as caught:
                self.store.get("fixture")
        self.assertIs(caught.exception.__cause__, failure)
        self.assertEqual(len(opened), 1, "Close uncertainty must not open another handle")
        self.assertEqual(opened[0].closes, 1)
        self.assertEqual(self.source_files(), before)

    def test_unstable_snapshot_is_bounded_and_never_queries_mixed_bytes(self):
        self.seed()
        before = self.source_files()
        real_hash = common.file_hash
        source_hashes = []
        def changing_hash(path):
            if path == self.path:
                source_hashes.append(path)
                return str(len(source_hashes))
            return real_hash(path)
        with patch.object(common, "file_hash", side_effect=changing_hash), \
             patch.object(common.sqlite3, "connect", side_effect=AssertionError("Never query an unstable copy")):
            with self.assertRaises(common.RddStorageError) as caught:
                self.store.get("fixture")
        self.assertIn("database changed during preflight", str(caught.exception))
        self.assertEqual(len(source_hashes), 6, "Three before/after comparisons bound copy retries")
        self.assertEqual(self.source_files(), before)

    def test_reader_waits_through_writer_connection_close(self):
        started = threading.Event()
        finished = threading.Event()
        results = []
        threads = []
        real_connect = sqlite3.connect
        def reader():
            started.set()
            try:
                results.append(self.store.get("fixture"))
            except BaseException as exc:
                results.append(exc)
            finally:
                finished.set()
        case = self
        class WaitingClose(FaultConnection):
            def close(self):
                thread = threading.Thread(target=reader)
                threads.append(thread)
                thread.start()
                case.assertTrue(started.wait(2))
                case.assertFalse(finished.wait(0.1), "Read must wait while close still owns the handle")
                super().close()
        def connect(*args, **kwargs):
            db = real_connect(*args, **kwargs)
            return WaitingClose(db) if Path(args[0]) == self.path else db
        with patch.object(common.sqlite3, "connect", side_effect=connect):
            self.seed()
            threads[0].join(5)
        self.assertFalse(threads[0].is_alive())
        self.assertEqual(results, [dict(id="fixture", child_writes=0, parent_writes=0, payload="x" * 10)])

    def assert_snapshot_cleanup_preserves(self, failure):
        self.seed()
        real_connect = sqlite3.connect
        opened = []
        cleanup_calls = []
        class FailingCleanup(tempfile.TemporaryDirectory):
            def cleanup(self):
                super().cleanup()
                cleanup_calls.append(self.name)
                raise PermissionError("snapshot cleanup failed")
        def connect(*args, **kwargs):
            db = FaultConnection(real_connect(*args, **kwargs), "SELECT", failure)
            opened.append(db)
            return db
        expected = common.RddStorageError if isinstance(failure, sqlite3.Error) else type(failure)
        with patch.object(common.tempfile, "TemporaryDirectory", FailingCleanup), \
             patch.object(common.sqlite3, "connect", side_effect=connect):
            with self.assertRaises(expected) as caught:
                self.store.get("fixture")
        if isinstance(failure, sqlite3.Error):
            self.assertEqual(caught.exception.sqlite_errorcode, failure.sqlite_errorcode)
            self.assertEqual(caught.exception.sqlite_errorname, failure.sqlite_errorname)
            self.assertIs(caught.exception.__cause__, failure)
        else:
            self.assertIs(caught.exception, failure)
            self.assertIn("snapshot cleanup failed", str(failure.rdd_storage_error))
        self.assertEqual(len(cleanup_calls), 1)
        self.assertTrue(opened)
        self.assertTrue(all(db.closes == 1 for db in opened))
        self.assertEqual(self.store.get("fixture")["id"], "fixture")

    def test_snapshot_cleanup_failure_preserves_sqlite_failure(self):
        failure = sqlite3.DatabaseError("injected corrupt snapshot")
        failure.sqlite_errorcode = sqlite3.SQLITE_CORRUPT
        failure.sqlite_errorname = "SQLITE_CORRUPT"
        self.assert_snapshot_cleanup_preserves(failure)

    def test_snapshot_cleanup_failure_preserves_interrupt(self):
        self.assert_snapshot_cleanup_preserves(KeyboardInterrupt("snapshot interrupted"))


if __name__ == "__main__":
    unittest.main()
