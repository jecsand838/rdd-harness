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
    def __init__(self, db, statement=None, error=None, *, rollback_error=None, close_error=None, fetch_error=None):
        self.db = db
        self.statement = statement
        self.error = error
        self.rollback_error = rollback_error
        self.close_error = close_error
        self.fetch_error = fetch_error
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
        self.db.close()
        if self.close_error is not None:
            raise self.close_error


class StoreTests(unittest.TestCase):
    def setUp(self):
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
        for _ in range(4):
            common.Store.read(self.root, "fixture")
            self.child_edit(0)
            with self.store.edit("fixture") as state:
                state["parent_writes"] += 1
        self.store.close()
        state = self.fresh_state()
        self.assertEqual(state["child_writes"], 4, "All committed child increments must survive")
        self.assertEqual(state["parent_writes"], 5)
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
                with patch.object(common.sqlite3, "connect", side_effect=connect):
                    with self.assertRaises(type(failure)) as caught:
                        with self.store.edit("fixture") as state:
                            state["parent_writes"] = 8
                            raise failure
                self.assertIs(caught.exception, failure)
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
        with patch.object(common.sqlite3, "connect", side_effect=connect):
            with self.assertRaises(common.RddError) as caught:
                with self.store.edit("fixture") as state:
                    state["parent_writes"] = 8
        self.assertIs(caught.exception.__cause__, failure)
        self.assertEqual(opened[0].closes, 1)
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
        with patch.object(common.sqlite3, "connect", side_effect=connect):
            with self.assertRaises(common.RddError) as caught:
                self.seed()
        self.assertIsInstance(caught.exception, common.RddStorageError)
        self.assertIs(caught.exception.__cause__, failure)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0].closes, 1)
        self.assertEqual(self.store.get("fixture")["id"], "fixture")

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
                self.assertTrue(opened)
                self.assertTrue(all(db.closes == 1 for db in opened))
                self.assertEqual(self.store.get("fixture")["id"], "fixture")

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


class TerminalStorageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="rdd-terminal-store-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.store = common.Store(self.root)
        self.store.put(dict(id="fixture", value=1))
        self.failure_path = self.root / ".rdd/runtime/failures/fixture.json"

    def context(self, *, context_id="fixture", locator_id="fixture"):
        common.write_json(self.root / ".rdd/run.json", dict(run_id=locator_id))
        common.write_json(self.root / ".rdd/runtime/headless.json",
                          dict(run_id=context_id, stage="implementation", thread_id="thread-fixture"))

    def record(self, **changes):
        record = dict(schema_version=1, run_id="fixture", stage="implementation", thread_id="thread-fixture",
                      created_at="2026-10-10T00:00:00Z", operation="edit", database_path=str(self.store.path),
                      sqlite_errorcode=sqlite3.SQLITE_CORRUPT, sqlite_errorname="SQLITE_CORRUPT",
                      error="first corrupt state")
        return {**record, **changes}

    def test_headless_storage_failure_records_terminal_diagnostic(self):
        self.context()
        failure = sqlite3.DatabaseError("corrupt state")
        failure.sqlite_errorcode = sqlite3.SQLITE_CORRUPT
        failure.sqlite_errorname = "SQLITE_CORRUPT"
        with patch.object(common.sqlite3, "connect", side_effect=failure):
            with self.assertRaises(common.RddStorageError) as caught:
                self.store.put(dict(id="fixture", value=2))
        error = caught.exception
        self.assertIs(error.__cause__, failure)
        self.assertTrue(getattr(error, "restart_required", False), "Headless storage failure must require a new run")
        self.assertEqual(Path(error.failure_path), self.failure_path)
        self.assertIn("critical", str(error).lower())
        self.assertIn("new run", str(error).lower())
        record = common.read_json(self.failure_path)
        self.assertEqual(record["sqlite_errorcode"], sqlite3.SQLITE_CORRUPT)
        self.assertEqual(record["thread_id"], "thread-fixture")

    def test_terminal_marker_rejects_mutations_before_sqlite(self):
        common.write_json(self.failure_path, self.record())
        with patch.object(common.sqlite3, "connect", side_effect=AssertionError("Mutation reached SQLite")):
            for operation in (lambda: self.store.put(dict(id="fixture", value=2)),
                              lambda: StoreTests.enter_edit(self.store)):
                with self.assertRaises(common.RddError) as caught:
                    operation()
                self.assertTrue(getattr(caught.exception, "restart_required", False))
                self.assertEqual(caught.exception.kind, "environment")

    def test_child_terminal_marker_rolls_back_already_open_parent_edit(self):
        from tools.rdd import storage_failure
        self.context()
        child = """from pathlib import Path
import sqlite3, sys
from tools.rdd.common import RddStorageError
from tools.rdd.storage_failure import record_failure
root = Path(sys.argv[1])
error = RddStorageError('read', root / '.rdd/runtime/state.sqlite3', sqlite3.DatabaseError('child failure'))
assert record_failure(root, error) is not None
"""
        with self.assertRaises(storage_failure.TerminalStorageFailure):
            with self.store.edit("fixture") as state:
                result = subprocess.run([sys.executable, "-c", child, str(self.root)],
                                        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
                                        timeout=10, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                state.update(id="unexpected", value=2)
        self.assertEqual(self.store.get("fixture"), dict(id="fixture", value=1))
        self.assertFalse(self.store.exists("unexpected"))

    def test_terminal_marker_after_put_write_rolls_back_before_commit(self):
        from tools.rdd import storage_failure
        self.context()
        real_connect = sqlite3.connect
        root, path = self.root, self.store.path
        opened = []
        class MarkingConnection(FaultConnection):
            def execute(self, sql, *args):
                cursor = super().execute(sql, *args)
                if sql.startswith("INSERT"):
                    error = common.RddStorageError("read", path, sqlite3.DatabaseError("concurrent child failure"))
                    storage_failure.record_failure(root, error)
                return cursor
        def connect(*args, **kwargs):
            db = MarkingConnection(real_connect(*args, **kwargs))
            opened.append(db)
            return db
        with patch.object(common.sqlite3, "connect", side_effect=connect):
            with self.assertRaises(storage_failure.TerminalStorageFailure):
                self.store.put(dict(id="fixture", value=2))
        self.assertEqual(len(opened), 1)
        self.assertIn("ROLLBACK", opened[0].statements)
        self.assertNotIn("COMMIT", opened[0].statements)
        self.assertEqual(opened[0].closes, 1)
        self.assertEqual(self.store.get("fixture"), dict(id="fixture", value=1))

    def test_no_context_or_mismatched_context_does_not_make_failure_terminal(self):
        for context_id in (None, "other"):
            with self.subTest(context_id=context_id):
                if context_id:
                    self.context(context_id=context_id)
                failure = sqlite3.OperationalError("write failed")
                with patch.object(common.sqlite3, "connect", side_effect=failure):
                    with self.assertRaises(common.RddStorageError) as caught:
                        self.store.put(dict(id="fixture", value=2))
                self.assertFalse(getattr(caught.exception, "restart_required", False))
                self.assertFalse(self.failure_path.exists())
        self.store.put(dict(id="fixture", value=3))

    def test_headless_snapshot_first_sqlite_error_cannot_disappear_on_retry(self):
        self.context()
        real_connect = sqlite3.connect
        failure = sqlite3.DatabaseError("first snapshot is corrupt")
        opened = []
        def connect(*args, **kwargs):
            db = FaultConnection(real_connect(*args, **kwargs), "SELECT" if not opened else None, failure)
            opened.append(db)
            return db
        with patch.object(common.sqlite3, "connect", side_effect=connect):
            with self.assertRaises(common.RddStorageError) as caught:
                self.store.get("fixture")
        self.assertIs(caught.exception.__cause__, failure)
        self.assertEqual(len(opened), 1)
        self.assertTrue(caught.exception.restart_required)

    def test_early_headless_scope_detects_first_failure_without_registering_context(self):
        from tools.rdd import storage_failure
        common.write_json(self.root / ".rdd/run.json", dict(run_id="fixture"))
        context = self.root / ".rdd/runtime/headless.json"
        real_connect = sqlite3.connect
        failure = sqlite3.DatabaseError("early snapshot failed")
        opened = []
        def connect(*args, **kwargs):
            db = FaultConnection(real_connect(*args, **kwargs), "SELECT" if not opened else None, failure)
            opened.append(db)
            return db
        with storage_failure.headless_scope(self.root, "preparation"):
            self.assertEqual(self.store.get("fixture")["value"], 1)
            self.assertFalse(context.exists())
            self.assertFalse(self.failure_path.exists())
            with patch.object(common.sqlite3, "connect", side_effect=connect):
                with self.assertRaises(common.RddStorageError) as caught:
                    self.store.get("fixture")
        self.assertIs(caught.exception.__cause__, failure)
        self.assertTrue(caught.exception.restart_required)
        self.assertEqual(len(opened), 1)
        self.assertEqual(common.read_json(self.failure_path)["stage"], "preparation")
        self.assertFalse(context.exists())

    def test_specification_scope_suppresses_stale_headless_context(self):
        from tools.rdd import storage_failure
        self.context()
        failure = sqlite3.OperationalError("specification storage failed")
        with storage_failure.headless_scope(self.root, "specification"), \
             patch.object(common.sqlite3, "connect", side_effect=failure):
            with self.assertRaises(common.RddStorageError) as caught:
                self.store.get("fixture")
        self.assertFalse(getattr(caught.exception, "restart_required", False))
        self.assertFalse(self.failure_path.exists())

    def test_headless_sqlite_cleanup_failure_preserves_primary_exception_and_marks_run(self):
        real_connect = sqlite3.connect
        for boundary, primary in ((boundary, kind("primary body failure"))
                                  for boundary in ("rollback", "close", "rollback+close")
                                  for kind in (ValueError, common.RddError)):
            with self.subTest(boundary=boundary, primary=type(primary).__name__):
                self.failure_path.unlink(missing_ok=True)
                self.context()
                diagnostic = "rollback failed" if boundary == "rollback+close" else boundary + " failed"
                failure = sqlite3.OperationalError(diagnostic)
                cause = RuntimeError("original cause")
                primary.__cause__ = cause
                def connect(*args, **kwargs):
                    options = ({"rollback_error": failure, "close_error": sqlite3.OperationalError("close failed")}
                               if boundary == "rollback+close" else {boundary + "_error": failure})
                    return FaultConnection(real_connect(*args, **kwargs), **options)
                with patch.object(common.sqlite3, "connect", side_effect=connect):
                    with self.assertRaises(type(primary)) as caught:
                        with self.store.edit("fixture"):
                            raise primary
                self.assertIs(caught.exception, primary)
                self.assertIs(caught.exception.__cause__, cause)
                self.assertTrue(getattr(primary, "restart_required", False), "Original error must retain terminal classification")
                self.assertEqual(primary.failure_path, str(self.failure_path))
                self.assertIn("primary body failure", str(primary))
                self.assertIn(diagnostic, str(primary))
                self.assertIn("new run", str(primary))
                if boundary == "rollback+close":
                    self.assertNotIn("close failed", str(primary), "First cleanup diagnostic must remain authoritative")
                self.assertTrue(self.failure_path.exists(), "SQLite cleanup failure must mark the headless run")
                self.assertIn(diagnostic, common.read_json(self.failure_path)["error"])

    def test_nonheadless_sqlite_cleanup_failure_does_not_annotate_primary(self):
        real_connect = sqlite3.connect
        primary = common.RddError("ordinary validation")
        def connect(*args, **kwargs):
            return FaultConnection(real_connect(*args, **kwargs),
                                   rollback_error=sqlite3.OperationalError("rollback failed"),
                                   close_error=sqlite3.OperationalError("close failed"))
        with patch.object(common.sqlite3, "connect", side_effect=connect):
            with self.assertRaises(common.RddError) as caught:
                with self.store.edit("fixture"):
                    raise primary
        self.assertIs(caught.exception, primary)
        self.assertFalse(getattr(primary, "restart_required", False))
        self.assertEqual(str(primary), "ordinary validation")
        self.assertFalse(self.failure_path.exists())

    def test_clean_headless_interrupt_remains_ordinary(self):
        self.context()
        failure = KeyboardInterrupt("ordinary interruption")
        with self.assertRaises(KeyboardInterrupt) as caught:
            with self.store.edit("fixture"):
                raise failure
        self.assertIs(caught.exception, failure)
        self.assertFalse(self.failure_path.exists())

    def test_reentrant_write_rejects_before_marker_file_io(self):
        from tools.rdd import storage_failure
        with self.store.edit("fixture"):
            with patch.object(storage_failure, "read_failure", side_effect=AssertionError("Reentrant marker IO")):
                with self.assertRaises(common.RddError) as caught:
                    self.store.put(dict(id="fixture", value=2))
        self.assertIn("reentrant", str(caught.exception).lower())

    def test_forensic_reads_and_separate_run_writes_remain_available(self):
        self.context()
        common.write_json(self.failure_path, self.record())
        before = self.store.path.read_bytes()
        self.assertEqual(self.store.get("fixture"), dict(id="fixture", value=1))
        self.assertTrue(self.store.exists("fixture"))
        self.assertEqual(self.store.path.read_bytes(), before)
        self.store.put(dict(id="separate", value=3))
        with self.store.edit("separate") as state:
            state["value"] = 4
        self.assertEqual(self.store.get("separate")["value"], 4)

    def test_registration_is_explicit_minimal_and_run_bound(self):
        from tools.rdd import storage_failure
        context = self.root / ".rdd/runtime/headless.json"
        self.assertFalse(context.exists(), "Ordinary Store calls must not register context")
        storage_failure.register_headless(self.root, "fixture", "preparation")
        self.assertEqual(common.read_json(context), dict(run_id="fixture", stage="preparation", thread_id=None))
        for run_id, stage in (("../escape", "preparation"), ("fixture", "specification")):
            with self.assertRaises(common.RddError):
                storage_failure.register_headless(self.root, run_id, stage)
        self.assertEqual(common.read_json(context)["stage"], "preparation")

    def test_explicit_failure_registration_needs_no_database_or_context(self):
        from tools.rdd import storage_failure
        root = self.root / "empty"
        error = common.RddStorageError("read", root / ".rdd/runtime/state.sqlite3", sqlite3.OperationalError("open failed"))
        with patch.object(common.sqlite3, "connect", side_effect=AssertionError("Must not access DB")):
            record = storage_failure.record_failure(root, error, run_id="fixture", stage="preparation")
            self.assertEqual(record, storage_failure.read_failure(root, "fixture"))
            with self.assertRaises(common.RddError) as caught:
                storage_failure.check_failure(root, "fixture")
        self.assertTrue(caught.exception.restart_required)
        self.assertFalse((root / ".rdd/runtime/state.sqlite3").exists())

    def test_first_record_is_preserved_and_shared_with_child_process(self):
        from tools.rdd import storage_failure
        self.context()
        first = common.RddStorageError("edit", self.store.path, sqlite3.OperationalError("first failure"))
        expected = storage_failure.record_failure(self.root, first)
        saved = self.failure_path.read_bytes()
        second = common.RddStorageError("put", self.store.path, sqlite3.OperationalError("second failure"))
        self.assertEqual(storage_failure.record_failure(self.root, second), expected)
        self.assertEqual(self.failure_path.read_bytes(), saved)
        child = """from pathlib import Path
import sys
from tools.rdd.storage_failure import check_failure
from tools.rdd.common import RddError
try:
    check_failure(Path(sys.argv[1]), 'fixture')
except RddError as error:
    assert error.restart_required
    assert 'new run' in str(error).lower()
else:
    raise AssertionError('Child did not see terminal marker')
"""
        result = subprocess.run([sys.executable, "-c", child, str(self.root)],
                                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
                                timeout=10, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_concurrent_first_records_publish_one_complete_diagnostic(self):
        from tools.rdd import storage_failure
        self.context()
        barrier = threading.Barrier(4)
        outcomes = []
        def writer(index):
            error = common.RddStorageError("edit", self.store.path, sqlite3.OperationalError(f"failure {index}"))
            barrier.wait(timeout=5)
            outcomes.append(storage_failure.record_failure(self.root, error))
        threads = [threading.Thread(target=writer, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcomes), 4)
        record = storage_failure.read_failure(self.root, "fixture")
        self.assertTrue(all(outcome == record for outcome in outcomes))
        self.assertIn(record["error"].split(": ")[-1], {f"failure {index}" for index in range(4)})

    def test_marker_write_failure_preserves_original_and_reports_persistence(self):
        from tools.rdd import storage_failure
        self.context()
        failure = sqlite3.OperationalError("original write failure")
        with patch.object(common.sqlite3, "connect", side_effect=failure), \
             patch.object(storage_failure, "atomic_write", side_effect=PermissionError("cannot persist marker")):
            with self.assertRaises(common.RddStorageError) as caught:
                self.store.put(dict(id="fixture", value=2))
        self.assertIs(caught.exception.__cause__, failure)
        self.assertTrue(caught.exception.restart_required)
        self.assertIn("cannot persist marker", caught.exception.persistence_error)
        self.assertIn("cannot persist marker", str(caught.exception))

    def test_repeated_recording_preserves_runtime_diagnostic_and_does_not_retry_write(self):
        from tools.rdd import storage_failure
        self.context()
        error = common.RddStorageError("edit", self.store.path, sqlite3.OperationalError("write failed"))
        with patch.object(storage_failure, "atomic_write", side_effect=PermissionError("marker failed")) as write:
            storage_failure.record_failure(self.root, error)
            error.args = (str(error) + "\nRuntime shutdown diagnostic",)
            storage_failure.record_failure(self.root, error, run_id="fixture", stage="implementation")
        self.assertEqual(write.call_count, 1)
        self.assertIn("Runtime shutdown diagnostic", str(error))

    def test_nonheadless_attempt_can_later_receive_explicit_headless_context(self):
        from tools.rdd import storage_failure
        error = common.RddStorageError("read", self.store.path, sqlite3.OperationalError("read failed"))
        self.assertIsNone(storage_failure.record_failure(self.root, error, stage="specification"))
        self.assertFalse(hasattr(error, "persistence_error"))
        self.assertIsNone(storage_failure.record_failure(self.root, error))
        self.assertFalse(getattr(error, "restart_required", False))
        self.assertIsNotNone(storage_failure.record_failure(self.root, error, run_id="fixture", stage="preparation"))
        self.assertTrue(error.restart_required)

    def test_invalid_or_partial_marker_fails_closed_without_writes(self):
        from tools.rdd import storage_failure
        self.failure_path.parent.mkdir(parents=True)
        for content in (b'{"schema_version":', common.canonical(self.record(run_id="other")),
                        common.canonical(self.record(sqlite_errorcode=True))):
            with self.subTest(content=content):
                self.failure_path.write_bytes(content)
                with patch.object(common.sqlite3, "connect", side_effect=AssertionError("Must not access DB")):
                    with self.assertRaises(common.RddError) as caught:
                        storage_failure.check_failure(self.root, "fixture")
                self.assertTrue(caught.exception.restart_required)
                self.assertEqual(self.failure_path.read_bytes(), content)

    def test_checkpoint_failure_validation_and_path_are_pure(self):
        from tools.rdd import storage_failure
        record = self.record()
        self.assertEqual(storage_failure.validate_failure(record, "fixture"), record)
        self.assertEqual(storage_failure.checkpoint_evidence_path("fixture"), ".rdd/evidence/storage-failures/fixture.json")
        for run_id in ("../escape", "", "a/b"):
            with self.assertRaises(common.RddError):
                storage_failure.checkpoint_evidence_path(run_id)
        with self.assertRaises(common.RddError):
            storage_failure.validate_failure({**record, "extra": True}, "fixture")


if __name__ == "__main__":
    unittest.main()
