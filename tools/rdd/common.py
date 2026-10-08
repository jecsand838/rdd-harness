"""Small, strict primitives shared by the controller and CI entry point."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import subprocess
import tempfile
import time
from typing import Any, Iterator


class RddError(RuntimeError):
    def __init__(self, message: str, kind: str = "validation"):
        super().__init__(message)
        self.kind = kind


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


class Store:
    """One transactionally updated run record; WAL allows concurrent read-only progress."""
    def __init__(self, root: Path):
        self.path = root / ".rdd/runtime/state.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def get(self, run_id: str) -> dict:
        row = self.db.execute("SELECT value FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise RddError(f"No local state for {run_id}; use resume --from an exported checkpoint.", "environment")
        return json.loads(row[0])

    def put(self, state: dict) -> None:
        self.db.execute("INSERT INTO runs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                        (state["id"], canonical(state).decode()))

    @contextlib.contextmanager
    def edit(self, run_id: str) -> Iterator[dict]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            state = self.get(run_id)
            yield state
            self.put(state)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()


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
def operation_lock(root: Path):
    """Serialize CLI mutations across processes; OS releases the lock after crashes."""
    path = safe_path(root, ".rdd/runtime/controller.lock")
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
                raise RddError("Another controller mutation is running; read status and retry after it finishes", "environment") from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except BlockingIOError as exc:
                raise RddError("Another controller mutation is running; read status and retry after it finishes", "environment") from exc
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
