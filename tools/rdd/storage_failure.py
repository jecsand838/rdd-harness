"""Run-bound terminal headless storage diagnostics, independent of SQLite."""
from __future__ import annotations

import contextlib
from contextvars import ContextVar
from datetime import datetime
import os
from pathlib import Path
import re
import uuid

from .common import RddError, RddStorageError, atomic_write, canonical, now, read_json, safe_path


_STAGES = {"preparation", "implementation"}
_FIELDS = {"schema_version", "run_id", "stage", "thread_id", "created_at", "operation",
           "database_path", "sqlite_errorcode", "sqlite_errorname", "error"}
_SCOPE: ContextVar[tuple[Path, str] | None] = ContextVar("rdd_headless_storage_scope", default=None)


@contextlib.contextmanager
def headless_scope(root: Path, stage: str):
    """Identify headless preflight without creating persistent runtime context."""
    if stage != "specification":
        _stage(stage)
    token = _SCOPE.set((root.resolve(), stage))
    try:
        yield
    finally:
        _SCOPE.reset(token)


class TerminalStorageFailure(RddError):
    """A marked run cannot resume; forensic reads remain available."""
    def __init__(self, run_id: str, failure_path: Path | str, detail: str | None = None):
        self.run_id = run_id
        self.failure_path = str(failure_path)
        self.restart_required = True
        message = (f"Critical headless storage failure for run {run_id}. Start a new run through all three "
                   f"workflows in a separate clean baseline; this run cannot resume. Diagnostic: {failure_path}")
        if detail:
            message += f". {detail}"
        super().__init__(message, "environment")


def preserve_primary_error(primary: BaseException, failure: BaseException, context: str) -> None:
    """Keep the first error while carrying a terminal cleanup failure to the CLI."""
    if getattr(failure, "restart_required", False) and not getattr(primary, "restart_required", False):
        primary.args = (f"{primary}. During {context}: {failure}",)
        for name in ("restart_required", "failure_path", "persistence_error"):
            if hasattr(failure, name):
                setattr(primary, name, getattr(failure, name))


def _run_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
        raise RddError("Storage failure run ID must be 1-64 plain letters, digits, dots, underscores or hyphens", "environment")
    return value


def _stage(value: str) -> str:
    if not isinstance(value, str) or value not in _STAGES:
        raise RddError("Headless storage context requires preparation or implementation", "environment")
    return value


def _thread(value: str | None) -> str | None:
    if value is not None and (not isinstance(value, str) or not value or len(value) > 256
                              or any(ord(char) < 32 for char in value)):
        raise RddError("Invalid headless thread ID", "environment")
    return value


def _failure_path(root: Path, run_id: str) -> Path:
    return safe_path(root, f".rdd/runtime/failures/{_run_id(run_id)}.json")


def _locator_id(root: Path) -> str | None:
    path = safe_path(root, ".rdd/run.json")
    if not path.exists():
        return None
    locator = read_json(path)
    if not isinstance(locator, dict):
        raise RddError("Invalid active run locator", "environment")
    return _run_id(locator["run_id"]) if locator.get("run_id") is not None else None


def register_headless(root: Path, run_id: str, stage: str, thread_id: str | None = None) -> None:
    """Record explicit stage context; ordinary Store operations never create it."""
    context = {"run_id": _run_id(run_id), "stage": _stage(stage), "thread_id": _thread(thread_id)}
    check_failure(root, run_id)
    atomic_write(safe_path(root, ".rdd/runtime/headless.json"), canonical(context) + b"\n")


def validate_failure(record: dict, run_id: str) -> dict:
    """Validate a runtime/checkpoint diagnostic without reading or writing files."""
    _run_id(run_id)
    if (not isinstance(record, dict) or set(record) != _FIELDS
            or type(record.get("schema_version")) is not int or record["schema_version"] != 1
            or record.get("run_id") != run_id):
        raise RddError("Invalid or mismatched terminal storage failure record", "environment")
    _stage(record["stage"])
    _thread(record["thread_id"])
    for field in ("operation", "database_path", "error"):
        value = record[field]
        if not isinstance(value, str) or not value or "\x00" in value:
            raise RddError(f"Invalid storage failure {field}", "environment")
    if (record["sqlite_errorcode"] is not None
            and (type(record["sqlite_errorcode"]) is not int or record["sqlite_errorcode"] < 0)):
        raise RddError("Invalid storage failure SQLite code", "environment")
    if record["sqlite_errorname"] is not None and (not isinstance(record["sqlite_errorname"], str)
                                                  or not record["sqlite_errorname"]):
        raise RddError("Invalid storage failure SQLite name", "environment")
    try:
        datetime.strptime(record["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError) as exc:
        raise RddError("Invalid storage failure creation time", "environment") from exc
    return record


def read_failure(root: Path, run_id: str) -> dict | None:
    """Return a validated marker; any existing invalid marker fails closed."""
    run_id = _run_id(run_id)
    intended = root / f".rdd/runtime/failures/{run_id}.json"
    try:
        path = _failure_path(root, run_id)
        if not path.exists():
            return None
        return validate_failure(read_json(path), run_id)
    except (RddError, OSError) as exc:
        raise TerminalStorageFailure(run_id, intended, f"Failure diagnostic is unreadable or invalid: {exc}") from exc


def check_failure(root: Path, run_id: str | None = None) -> None:
    """Refuse a marked run without accessing SQLite or modifying files."""
    run_id = _locator_id(root) if run_id is None else _run_id(run_id)
    if run_id is not None and read_failure(root, run_id) is not None:
        raise TerminalStorageFailure(run_id, _failure_path(root, run_id))


def checkpoint_evidence_path(run_id: str) -> str:
    return f".rdd/evidence/storage-failures/{_run_id(run_id)}.json"


def _registered_context(root: Path, run_id: str | None, thread_id: str | None):
    path = safe_path(root, ".rdd/runtime/headless.json")
    if not path.exists():
        return None
    context = read_json(path)
    if not isinstance(context, dict) or set(context) != {"run_id", "stage", "thread_id"}:
        raise RddError("Invalid headless storage context", "environment")
    context_id = _run_id(context["run_id"])
    if context_id != _locator_id(root) or (run_id is not None and context_id != _run_id(run_id)):
        return None
    return context_id, _stage(context["stage"]), _thread(thread_id if thread_id is not None else context["thread_id"])


def _context(root: Path, run_id: str | None, stage: str | None, thread_id: str | None):
    if stage == "specification":
        return None
    if stage is not None:
        stage = _stage(stage)
        run_id = _locator_id(root) if run_id is None else _run_id(run_id)
        return (run_id, stage, _thread(thread_id)) if run_id is not None else None
    scope = _SCOPE.get()
    if scope is not None and scope[0] == root.resolve():
        if scope[1] == "specification":
            return None
        locator_id = _locator_id(root)
        if locator_id is None or (run_id is not None and locator_id != _run_id(run_id)):
            return None
        if thread_id is None:
            try:
                registered = _registered_context(root, locator_id, None)
                if registered is not None and registered[1] == scope[1]:
                    thread_id = registered[2]
            except (RddError, OSError):
                pass  # Valid in-memory stage context does not require this optional file.
        return locator_id, scope[1], _thread(thread_id)
    return _registered_context(root, run_id, thread_id)


def record_failure(root: Path, error: RddStorageError, *, run_id: str | None = None,
                   stage: str | None = None, thread_id: str | None = None) -> dict | None:
    """Annotate the original error and best-effort publish the first diagnostic."""
    if getattr(error, "_storage_failure_attempted", False):
        return error._storage_failure_record
    try:
        context = _context(root, run_id, stage, thread_id)
    except BaseException as exc:
        error.persistence_error = str(exc)
        return None
    if context is None:
        return None
    run_id, stage, thread_id = context
    original = getattr(error, "_original_storage_message", str(error))
    error._original_storage_message = original
    error.restart_required = True
    error.failure_path = str(root / f".rdd/runtime/failures/{run_id}.json")
    error._storage_failure_record = None
    error._storage_failure_attempted = True
    record = None
    temporary = None
    try:
        path = _failure_path(root, run_id)
        record = read_failure(root, run_id)
        if record is None:
            candidate = validate_failure({"schema_version": 1, "run_id": run_id, "stage": stage,
                "thread_id": thread_id, "created_at": now(), "operation": error.operation,
                "database_path": str(error.database_path), "sqlite_errorcode": error.sqlite_errorcode,
                "sqlite_errorname": error.sqlite_errorname, "error": original}, run_id)
            temporary = safe_path(root, f".rdd/runtime/failures/.{run_id}-{uuid.uuid4().hex}.tmp")
            atomic_write(temporary, canonical(candidate) + b"\n")
            try:
                os.link(temporary, path)  # Publish complete bytes exactly once, across processes.
            except FileExistsError:
                pass
            record = read_failure(root, run_id)
    except BaseException as exc:
        error.persistence_error = str(exc)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except BaseException as exc:
                if not getattr(error, "persistence_error", None):
                    error.persistence_error = str(exc)
        detail = str(TerminalStorageFailure(run_id, error.failure_path))
        if getattr(error, "persistence_error", None):
            detail += f". Failure diagnostic could not be persisted: {error.persistence_error}"
        error.args = (f"{original}\n{detail}",)
        error._storage_failure_record = record
    return record
