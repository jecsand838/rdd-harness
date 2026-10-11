"""Small, strict primitives shared by the controller and CI entry point."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
from typing import Any, Iterator


class RddError(RuntimeError):
    def __init__(self, message: str, kind: str = "validation"):
        super().__init__(message)
        self.kind = kind


class RddStorageError(RddError):
    """A local storage failure, distinct from controller validation failures."""
    def __init__(self, operation: str, path: Path, cause: sqlite3.Error | OSError):
        self.operation = operation
        self.database_path = path
        self.sqlite_errorcode = getattr(cause, "sqlite_errorcode", None)
        self.sqlite_errorname = getattr(cause, "sqlite_errorname", None)
        code = f" ({self.sqlite_errorname or self.sqlite_errorcode})" if self.sqlite_errorcode is not None else ""
        super().__init__(f"Local state {operation} failed for {path}{code}: {cause}", "environment")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    try:
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate key {key}")
                result[key] = value
            return result
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (OSError, ValueError) as exc:
        raise RddError(f"Cannot read JSON {path}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False).encode() + b"\n")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RddError(f"Refusing symlink destination: {path}")
    mode = stat.S_IMODE(path.stat().st_mode) if os.name == "posix" and path.exists() else None
    fd, name = tempfile.mkstemp(prefix=".rdd-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            if mode is not None:
                os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def safe_path(root: Path, relative: str, *, allow_missing: bool = True) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise RddError(f"Invalid repository path: {relative!r}")
    parts = PurePosixPath(relative)
    if (parts.is_absolute() or any(p.lower() == ".git" or p == ".." or ":" in p for p in parts.parts)
            or any(ord(c) < 32 for c in relative)
            or str(parts) != relative.rstrip("/")):
        raise RddError(f"Path escapes repository or targets Git internals: {relative}")
    target = root.joinpath(*parts.parts)
    cursor = root
    for part in parts.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RddError(f"Symlink paths are not writable artifact paths: {relative}")
    if not target.resolve().is_relative_to(root.resolve()):
        raise RddError(f"Path escapes repository: {relative}")
    if not allow_missing and not target.is_file():
        raise RddError(f"Required file is missing: {relative}")
    return target


def git(root: Path, *args: str, check: bool = True) -> str:
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RddError(f"Git failed: {exc}", "environment") from exc
    if check and p.returncode:
        raise RddError(f"git {' '.join(args)}: {p.stderr.strip()}", "environment")
    return p.stdout.strip() if "-z" not in args else p.stdout


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD")


def require_source_branch(root: Path, expected: str | None = None) -> str:
    """Check source-write identity without switching branches or creating runtime state."""
    branch = git(root, "branch", "--show-current")
    if not branch:
        raise RddError("Source writes require a named Git branch; detached HEAD is read-only. Create or switch deliberately to a dedicated baseline or recorded phase branch first.", "environment")
    if branch == "main":
        raise RddError("Source writes are disabled on main. Create or switch deliberately to a dedicated baseline or recorded phase branch first; existing files and run baselines are preserved.", "environment")
    if expected is not None and branch != expected:
        raise RddError(f"Source writes require the recorded branch {expected!r}; this checkout is on {branch!r}. Switch deliberately before retrying; the recorded baseline is preserved.", "environment")
    return branch


def clean(root: Path) -> None:
    dirty = git(root, "status", "--porcelain")
    if dirty:
        raise RddError("Commit or deliberately resolve working-tree changes first:\n" + dirty)


EXCLUDED_PREFIXES = (".rdd/runtime/", ".rdd/evidence/")
EXCLUDED_FILES = {".rdd/run.json"}


def inventory(root: Path, paths: list[str] | None = None) -> dict[str, str]:
    if paths is None:
        paths = sorted(set(p for p in git(root, "ls-files", "-c", "-o", "--exclude-standard", "-z").split("\0") if p))
        paths = [p for p in paths if not p.startswith(EXCLUDED_PREFIXES) and p not in EXCLUDED_FILES]
    result = {}
    for rel in sorted(set(paths)):
        path = safe_path(root, rel)
        if path.is_file():
            result[rel] = file_hash(path)
        elif path.exists():
            raise RddError(f"Expected a regular file: {rel}")
        else:
            result[rel] = "MISSING"
    return result


def source_digest(root: Path) -> str:
    return digest(inventory(root))


def assert_inventory(root: Path, expected: dict[str, str], label: str) -> None:
    actual = inventory(root, list(expected))
    changes = [p for p in expected if actual[p] != expected[p]]
    if changes:
        raise RddError(f"{label} changed: {', '.join(changes)}. Return to specification.", "specification")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


_STORE_LOCK = threading.RLock()
_STORE_ACTIVE = False


@contextlib.contextmanager
def _store_access(operation: str) -> Iterator[None]:
    """Do not copy source files while this process owns a SQLite handle."""
    global _STORE_ACTIVE
    with _STORE_LOCK:
        if _STORE_ACTIVE:
            raise RddError(f"Reentrant Store {operation} is not allowed during an active storage operation")
        _STORE_ACTIVE = True
        try:
            yield
        finally:
            _STORE_ACTIVE = False


@contextlib.contextmanager
def _store_connection(path: Path | str, database_path: Path, operation: str, **options) -> Iterator[sqlite3.Connection]:
    db = None
    failed = False
    try:
        try:
            db = sqlite3.connect(path, timeout=30, **options)
        except (OSError, sqlite3.Error) as exc:
            raise RddStorageError(operation, database_path, exc) from exc
        yield db
    except BaseException:
        failed = True
        raise
    finally:
        if db is not None:
            try:
                db.close()
            except BaseException as exc:
                if not failed:
                    if isinstance(exc, (OSError, sqlite3.Error)):
                        raise RddStorageError(operation, database_path, exc) from exc
                    raise


class Store:
    """Path-owning run store; each operation closes its own SQLite connection."""
    def __init__(self, root: Path):
        self.root = root
        self.path = root / ".rdd/runtime/state.sqlite3"

    @staticmethod
    def _execute(db, sql: str, parameters: tuple, path: Path, operation: str):
        try:
            return db.execute(sql, parameters)
        except (OSError, sqlite3.Error) as exc:
            raise RddStorageError(operation, path, exc) from exc

    @staticmethod
    def _row(db, run_id: str, path: Path, operation: str, *, existence: bool = False):
        sql = "SELECT 1 FROM runs WHERE id=?" if existence else "SELECT value FROM runs WHERE id=?"
        try:
            return Store._execute(db, sql, (run_id,), path, operation).fetchone()
        except (OSError, sqlite3.Error) as exc:
            raise RddStorageError(operation, path, exc) from exc

    @contextlib.contextmanager
    def _writer(self, operation: str) -> Iterator[sqlite3.Connection]:
        with _store_access(operation):
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise RddStorageError(operation, self.path, exc) from exc
            with _store_connection(self.path, self.path, operation, isolation_level=None) as db:
                for sql in ("PRAGMA journal_mode=WAL", "PRAGMA synchronous=FULL",
                            "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, value TEXT NOT NULL)"):
                    self._execute(db, sql, (), self.path, operation)
                yield db

    @staticmethod
    def _state(row, run_id: str) -> dict:
        if row is None:
            raise RddError(f"No local state for {run_id}; use resume --from an exported checkpoint.", "environment")
        return json.loads(row[0])

    def get(self, run_id: str) -> dict:
        return self.read(self.root, run_id)

    @staticmethod
    def _snapshot_row(path: Path, run_id: str, operation: str, *, existence: bool = False):
        """Copy raw DB/WAL bytes; SQLite touches only the disposable snapshot."""
        wal = path.with_name(path.name + "-wal")

        def inputs():
            return {p.name: file_hash(p) for p in (path, wal) if p == path or p.is_file()}

        failure = OSError("database changed during preflight")
        directory = None
        failed = False
        try:
            try:
                directory = tempfile.TemporaryDirectory(prefix="rdd-state-preflight-")
                snapshot = Path(directory.name)
                for _ in range(3):
                    try:
                        for previous in snapshot.iterdir():
                            previous.unlink()
                        before = inputs()
                        for name in before:
                            shutil.copyfile(path.parent / name, snapshot / name)
                        if before != inputs() or any(file_hash(snapshot / name) != value for name, value in before.items()):
                            failure = OSError("database changed during preflight")
                            continue
                        with _store_connection((snapshot / path.name).as_uri() + "?mode=ro", path, operation, uri=True) as db:
                            return Store._row(db, run_id, path, operation, existence=existence)
                    except (OSError, RddStorageError) as exc:
                        failure = exc
                if isinstance(failure, RddStorageError):
                    raise failure
                raise RddStorageError(operation, path, failure) from failure
            except OSError as exc:
                raise RddStorageError(operation, path, exc) from exc
        except BaseException:
            failed = True
            raise
        finally:
            if directory is not None:
                try:
                    directory.cleanup()
                except BaseException as exc:
                    if not failed:
                        if isinstance(exc, OSError):
                            raise RddStorageError(operation, path, exc) from exc
                        raise

    @staticmethod
    def read(root: Path, run_id: str) -> dict:
        """Read a stable DB/WAL copy without creating source auxiliary files."""
        with _store_access("read"):
            row = Store._snapshot_row(root / ".rdd/runtime/state.sqlite3", run_id, "read")
            return Store._state(row, run_id)

    def exists(self, run_id: str) -> bool:
        with _store_access("exists"):
            try:
                if not self.path.exists():
                    return False
            except OSError as exc:
                raise RddStorageError("exists", self.path, exc) from exc
            return self._snapshot_row(self.path, run_id, "exists", existence=True) is not None

    def _put(self, db, state: dict, operation: str) -> None:
        self._execute(db, "INSERT INTO runs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                      (state["id"], canonical(state).decode()), self.path, operation)

    def put(self, state: dict) -> None:
        with self._writer("put") as db:
            self._put(db, state, "put")

    @contextlib.contextmanager
    def edit(self, run_id: str) -> Iterator[dict]:
        with self._writer("edit") as db:
            try:
                self._execute(db, "BEGIN IMMEDIATE", (), self.path, "edit")
                row = self._row(db, run_id, self.path, "edit")
                state = self._state(row, run_id)
                yield state
                self._put(db, state, "edit")
                self._execute(db, "COMMIT", (), self.path, "edit")
            except BaseException:
                try:
                    if db.in_transaction:
                        db.execute("ROLLBACK")
                except BaseException:
                    pass  # Cleanup must preserve the original failure or interrupt.
                raise

    def close(self):
        """Compatibility no-op: no operation leaves a connection on this object."""


def event(state: dict, action: str, **fields) -> None:
    state.setdefault("events", []).append({"sequence": len(state.get("events", [])) + 1,
                                           "time": now(), "action": action, **fields})


_SCHEMA_KEYS = {"$schema", "$id", "$defs", "$ref", "title", "description", "type", "required",
                "properties", "additionalProperties", "items", "minItems", "maxItems", "uniqueItems",
                "minLength", "maxLength", "pattern", "enum", "const", "minimum", "maximum",
                "anyOf", "oneOf", "allOf", "default"}


def _json_equal(left: Any, right: Any) -> bool:
    """JSON equality keeps booleans distinct from numbers, including nested values."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) or isinstance(right, dict):
        return (isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys()
                and all(_json_equal(left[key], right[key]) for key in left))
    if isinstance(left, list) or isinstance(right, list):
        return (isinstance(left, list) and isinstance(right, list) and len(left) == len(right)
                and all(_json_equal(a, b) for a, b in zip(left, right)))
    return left == right


def validate(value: Any, schema: dict, root_schema: dict | None = None, location: str = "$") -> None:
    """Strict JSON Schema subset used by the shipped schemas; unsupported keywords fail closed."""
    root_schema = root_schema or schema
    unknown = set(schema) - _SCHEMA_KEYS
    if unknown:
        raise RddError(f"Unsupported schema keywords at {location}: {sorted(unknown)}")
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise RddError("Only local schema references are supported")
        node = root_schema
        for part in ref[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        validate(value, node, root_schema, location)
    for key in ("allOf", "anyOf", "oneOf"):
        if key in schema:
            passed = 0
            for choice in schema[key]:
                try:
                    validate(value, choice, root_schema, location)
                    passed += 1
                except RddError:
                    pass
            if ((key == "allOf" and passed != len(schema[key])) or
                    (key == "anyOf" and passed == 0) or (key == "oneOf" and passed != 1)):
                raise RddError(f"{location}: {key} constraint failed")
    expected = schema.get("type")
    predicates = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
                  "string": lambda x: isinstance(x, str), "integer": lambda x: type(x) is int,
                  "number": lambda x: type(x) in (int, float), "boolean": lambda x: type(x) is bool,
                  "null": lambda x: x is None}
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        if not any(predicates[t](value) for t in types):
            raise RddError(f"{location}: expected {expected}")
    if "const" in schema and not _json_equal(value, schema["const"]):
        raise RddError(f"{location}: expected constant {schema['const']!r}")
    if "enum" in schema and not any(_json_equal(value, item) for item in schema["enum"]):
        raise RddError(f"{location}: must be one of {schema['enum']}")
    if isinstance(value, dict):
        missing = set(schema.get("required", [])) - value.keys()
        if missing:
            raise RddError(f"{location}: missing {sorted(missing)}")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, val in value.items():
            if key in props:
                validate(val, props[key], root_schema, f"{location}.{key}")
            elif extra is False:
                raise RddError(f"{location}: unknown field {key}")
            elif isinstance(extra, dict):
                validate(val, extra, root_schema, f"{location}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            raise RddError(f"{location}: array size out of bounds")
        if schema.get("uniqueItems") and len({canonical(v) for v in value}) != len(value):
            raise RddError(f"{location}: duplicate array entries")
        if "items" in schema:
            for i, item in enumerate(value):
                validate(item, schema["items"], root_schema, f"{location}[{i}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            raise RddError(f"{location}: string length out of bounds")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise RddError(f"{location}: pattern mismatch")
    if type(value) in (int, float):
        if value < schema.get("minimum", -float("inf")) or value > schema.get("maximum", float("inf")):
            raise RddError(f"{location}: numeric value out of bounds")


def validate_artifact(root: Path, name: str, value: Any) -> None:
    validate(value, read_json(root / f".rdd/schemas/{name}.schema.json"))


@contextlib.contextmanager
def operation_lock(root: Path, *, workflow: bool = False):
    """Serialize CLI mutations across processes; OS releases the lock after crashes."""
    path = safe_path(root, ".rdd/runtime/workflow.lock" if workflow else ".rdd/runtime/controller.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError as exc:
                raise RddError("Another workflow driver is running" if workflow else "Another controller mutation is running; read status and retry after it finishes", "environment") from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except BlockingIOError as exc:
                raise RddError("Another workflow driver is running" if workflow else "Another controller mutation is running; read status and retry after it finishes", "environment") from exc
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()
