"""Canonical RDD roles and runtime settings; custom discovery grants no authority."""
from __future__ import annotations

from pathlib import Path
import re
import tomllib
from typing import Any

from .common import RddError, digest, file_hash, safe_path


PROFILE_NAMES = (
    "rdd_coordinator", "rdd_domain_analyst", "rdd_verification_designer",
    "rdd_qualification_engineer", "rdd_contract_architect", "rdd_task_planner",
    "rdd_complex_implementor", "rdd_light_implementor", "rdd_researcher",
    "rdd_reviewer",
)
IMPLEMENTOR_SCOPES = {
    "rdd_complex_implementor": frozenset({"small", "large"}),
    "rdd_light_implementor": frozenset({"small"}),
}
IMPLEMENTOR_ROLES = tuple(IMPLEMENTOR_SCOPES)
WORKFLOW_AUTHOR_ROLES = PROFILE_NAMES[:6]
_READ_ONLY = {"rdd_researcher", "rdd_reviewer"}
_PROFILE_KEYS = {"name", "description", "model", "model_reasoning_effort",
                 "sandbox_mode", "developer_instructions"}
_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}


def _read(root: Path, relative: str) -> tuple[Path, dict[str, Any]]:
    try:
        path = safe_path(root, relative, allow_missing=False)
        value = tomllib.loads(path.read_text(encoding="utf-8"))
        return path, value
    except (OSError, UnicodeError, ValueError, RddError) as exc:
        raise RddError(f"Invalid RDD profile policy {relative}: {exc}", "environment") from exc


def load_profiles(root: str | Path) -> dict[str, dict[str, Any]]:
    """Load the fixed roster and validate native defaults without mutating files."""
    root = Path(root).resolve()
    profiles = {}
    for role in PROFILE_NAMES:
        relative = f".codex/agents/{role}.toml"
        path, value = _read(root, relative)
        if set(value) != _PROFILE_KEYS:
            raise RddError(f"Profile {role} requires only {sorted(_PROFILE_KEYS)}; missing or unsupported settings cannot be applied consistently", "environment")
        if value["name"] != role:
            raise RddError(f"Profile filename/name mismatch: {relative}", "environment")
        for field in _PROFILE_KEYS:
            if not isinstance(value[field], str) or not value[field].strip() or "\x00" in value[field]:
                raise RddError(f"Profile {role} has invalid {field}", "environment")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value["model"]) or value["model_reasoning_effort"] not in _EFFORTS:
            raise RddError(f"Profile {role} has invalid model/effort settings", "environment")
        expected_sandbox = "read-only" if role in _READ_ONLY else "workspace-write"
        if value["sandbox_mode"] != expected_sandbox:
            raise RddError(f"Profile {role} requires {expected_sandbox} sandbox", "environment")
        profiles[role] = {
            "name": role, "model": value["model"], "effort": value["model_reasoning_effort"],
            "sandbox": value["sandbox_mode"], "description": value["description"],
            "developer_instructions": value["developer_instructions"],
            "path": relative, "hash": file_hash(path),
        }

    # Other custom roles are permitted. A second file naming an RDD role would
    # make native discovery ambiguous, even though it grants no controller rights.
    canonical_paths = {profile["path"] for profile in profiles.values()}
    for extra in sorted((root / ".codex/agents").glob("*.toml")):
        relative = extra.relative_to(root).as_posix()
        if relative in canonical_paths:
            continue
        source = relative
        if extra.is_symlink():
            try:
                source = extra.resolve(strict=True).relative_to(root).as_posix()
            except (OSError, ValueError) as exc:
                raise RddError(f"Unsafe custom profile symlink: {relative}", "environment") from exc
        try:
            _, value = _read(root, source)
        except RddError:
            continue  # Unrelated malformed profiles are not RDD policy inputs.
        if isinstance(value.get("name"), str) and value["name"] in profiles:
            raise RddError(f"Canonical RDD name collision in {relative}", "environment")

    _, native = _read(root, ".codex/config.toml")
    agents = native.get("agents", {})
    coordinator, implementor = profiles["rdd_coordinator"], profiles["rdd_complex_implementor"]
    if not isinstance(agents, dict) or agents.get("enabled") is not True or agents.get("max_concurrent_threads_per_session") != 3:
        raise RddError("Native RDD configuration requires enabled agents and three child slots", "environment")
    for actual, expected, label in (
        (native.get("model"), coordinator["model"], "coordinator model"),
        (native.get("model_reasoning_effort"), coordinator["effort"], "coordinator effort"),
        (native.get("sandbox_mode"), coordinator["sandbox"], "coordinator sandbox"),
        (agents.get("default_subagent_model"), implementor["model"], "default subagent model"),
        (agents.get("default_subagent_reasoning_effort"), implementor["effort"], "default subagent effort"),
    ):
        if actual != expected:
            raise RddError(f"Native configuration/profile drift: {label}", "environment")
    return profiles


def profile_settings(root: str | Path, role: str) -> dict[str, str]:
    """Requested identity, not an attestation of the runtime's backend settings."""
    profiles = load_profiles(root)
    if role not in profiles:
        raise RddError(f"Unknown RDD role: {role}", "environment")
    profile = profiles[role]
    return {"role": role, "profile_path": profile["path"], "profile_hash": profile["hash"],
            "model": profile["model"], "effort": profile["effort"], "sandbox": profile["sandbox"]}


def profile_policy_digest(root: str | Path) -> str:
    root = Path(root).resolve()
    profiles = load_profiles(root)
    native, _ = _read(root, ".codex/config.toml")
    return digest({"profiles": {role: profiles[role]["hash"] for role in PROFILE_NAMES},
                   "native_configuration": file_hash(native)})
