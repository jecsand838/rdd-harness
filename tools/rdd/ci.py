"""Stateless CI verification using policy read from a separate trusted checkout.

CI can verify current source, anchors, and executable checks. It does not recreate
task/TDD history or certify manual and reference-device evidence. Those remain
the responsibility of the phase/project gates and their independent receipts.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
from typing import Any

from . import artifacts
from .common import (
    RddError, clean, digest, file_hash, git, head, now, read_json,
    safe_path, source_digest, validate_artifact, write_json,
)


_LOCKS = (".rdd/spec.lock.json", ".rdd/plan/plan.lock.json", ".rdd/prepared.json")
_FIXED_FILES = (".rdd/config.json", *_LOCKS, "AGENTS.md", "rdd", "rdd.cmd", "rdd.ps1")
_FIXED_PREFIXES = ("tools/rdd/", "tests/harness/", ".rdd/schemas/", ".codex/", ".agents/", ".github/")
_MUTABLE_PREFIXES = (".rdd/runtime/", ".rdd/evidence/", ".rdd/plan/anchors/")
_MUTABLE_FILES = {".rdd/run.json"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _host_platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    raise RddError(f"CI platform is not qualified: {sys.platform}", "environment")


def _ignored_projection(relative: str) -> bool:
    return (relative in _MUTABLE_FILES or relative.startswith(_MUTABLE_PREFIXES)
            or "__pycache__" in Path(relative).parts or relative.endswith((".pyc", ".pyo")))


def _policy_inventory(root: Path, config: dict) -> dict[str, str]:
    """Enumerate protected files including unexpected/untracked additions.

    Do not let a candidate .gitignore hide new policy files. Ignore only runtime,
    review evidence, task projections, and Python's derived bytecode caches.
    """
    prefixes = set(_FIXED_PREFIXES) | set(config.get("protected_prefixes", []))
    files = set(_FIXED_FILES) | set(config.get("protected_files", []))
    found: dict[str, str] = {}

    def inspect(relative: str) -> None:
        if _ignored_projection(relative):
            return
        path = safe_path(root, relative)
        if path.is_file():
            found[relative] = file_hash(path)
        elif path.exists() and not path.is_dir():
            raise RddError(f"Policy path must be a regular file: {relative}", "policy")

    for relative in files:
        inspect(relative)
    for prefix in prefixes:
        if not isinstance(prefix, str) or not prefix.endswith("/"):
            raise RddError(f"Protected prefixes must end in '/': {prefix!r}", "policy")
        base = safe_path(root, prefix)
        if not base.exists():
            continue
        if not base.is_dir():
            raise RddError(f"Protected prefix is not a directory: {prefix}", "policy")
        for directory, subdirs, names in os.walk(base, followlinks=False):
            # Reject symlink directories before pruning; normal mutable runtime
            # directories are excluded without inspecting their contents.
            keep = []
            for name in subdirs:
                path = Path(directory) / name
                relative = path.relative_to(root).as_posix() + "/"
                if _ignored_projection(relative):
                    continue
                safe_path(root, relative)
                keep.append(name)
            subdirs[:] = keep
            for name in names:
                relative = (Path(directory) / name).relative_to(root).as_posix()
                inspect(relative)
    return dict(sorted(found.items()))


def _assert_trusted_policy(root: Path, policy_root: Path, config: dict) -> dict[str, str]:
    trusted = _policy_inventory(policy_root, config)
    candidate = _policy_inventory(root, config)
    changed = sorted(path for path in set(trusted) | set(candidate)
                     if trusted.get(path) != candidate.get(path))
    if changed:
        raise RddError("Candidate changed trusted policy or frozen files: " + ", ".join(changed), "policy")
    return trusted


def _read_lock(root: Path, relative: str, required_manifest: str) -> dict:
    lock = read_json(safe_path(root, relative, allow_missing=False))
    if (not isinstance(lock, dict) or lock.get("schema_version") != 1
            or not isinstance(lock.get("digest"), str) or not _HEX64.fullmatch(lock["digest"])
            or not isinstance(lock.get("files"), dict) or not lock["files"]):
        raise RddError(f"Invalid freeze lock: {relative}", "policy")
    if required_manifest not in lock["files"]:
        raise RddError(f"Freeze lock does not include its canonical manifest: {required_manifest}", "policy")
    if lock["digest"] != digest({key: value for key, value in lock.items() if key != "digest"}):
        raise RddError(f"Freeze lock digest is inconsistent: {relative}", "policy")
    for path, expected in lock["files"].items():
        if not isinstance(expected, str) or not _HEX64.fullmatch(expected):
            raise RddError(f"Invalid locked file digest: {path}", "policy")
        actual = safe_path(root, path, allow_missing=False)
        if file_hash(actual) != expected:
            raise RddError(f"Frozen artifact changed: {path}", "specification")
    return lock


def _read_prepared(root: Path, spec_lock: dict, plan_lock: dict) -> dict:
    prepared = read_json(safe_path(root, ".rdd/prepared.json", allow_missing=False))
    required = {"schema_version", "run_id", "spec_digest", "plan_digest", "shell_hashes", "matrix_digest", "digest"}
    if not isinstance(prepared, dict) or not required <= set(prepared) or prepared.get("schema_version") != 1:
        raise RddError("Invalid preparation receipt", "policy")
    payload = {key: value for key, value in prepared.items() if key != "digest"}
    if digest(payload) != prepared["digest"]:
        raise RddError("Preparation receipt digest is inconsistent", "policy")
    if prepared["spec_digest"] != spec_lock["digest"] or prepared["plan_digest"] != plan_lock["digest"]:
        raise RddError("Preparation receipt targets another frozen specification or plan", "specification")
    if not isinstance(prepared["run_id"], str) or not prepared["run_id"]:
        raise RddError("Preparation receipt has no run identity", "policy")
    if not isinstance(prepared["shell_hashes"], dict):
        raise RddError("Preparation shell inventory is invalid", "policy")
    for path, expected in prepared["shell_hashes"].items():
        safe_path(root, path)
        if not isinstance(expected, str) or not _HEX64.fullmatch(expected):
            raise RddError(f"Invalid preparation shell digest: {path}", "policy")
    if not isinstance(prepared["matrix_digest"], str) or not _HEX64.fullmatch(prepared["matrix_digest"]):
        raise RddError("Preparation matrix digest is invalid", "policy")
    matrix = safe_path(root, ".rdd/plan/implementation-matrix.md", allow_missing=False)
    if file_hash(matrix) != prepared["matrix_digest"]:
        raise RddError("Preparation matrix changed after freeze", "policy")
    return prepared


def _selected_branch(root: Path, branch: str | None) -> str:
    return (branch or os.environ.get("GITHUB_HEAD_REF") or
            git(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)).strip()


def _selected_phase(root: Path, branch: str | None, plan: dict, run_id: str) -> tuple[str | None, str]:
    selected_branch = _selected_branch(root, branch)
    match = re.fullmatch(r"rdd/([A-Za-z0-9][A-Za-z0-9._-]{0,63})/p([0-9]{2,4})", selected_branch)
    if match:
        if match.group(1) != run_id:
            raise RddError("Phase branch belongs to a different prepared run", "policy")
        phase = f"P{int(match.group(2)):02d}"
        if selected_branch != f"rdd/{run_id}/p{int(match.group(2)):02d}":
            raise RddError("Phase branch name is not canonical", "policy")
    elif re.fullmatch(r"P[0-9]{2,3}", selected_branch):
        # Local explicit phase selection. GitHub supplies the actual branch name.
        phase = selected_branch
    elif selected_branch.startswith("rdd/"):
        raise RddError("Malformed phase branch name", "policy")
    else:
        phase = None
    if phase is not None and phase not in {item["id"] for item in plan["phases"]}:
        raise RddError(f"Phase {phase} is absent from the frozen plan", "planning")
    return phase, selected_branch


def _observed_anchor_boundary(root: Path, plan: dict) -> tuple[int, dict]:
    """Select CI coverage from marker shape, without asserting task history."""
    rank = {phase["id"]: i for i, phase in enumerate(plan["phases"])}
    matches = []
    last_error = None
    for boundary in range(-1, len(rank)):
        expectations = {
            task["id"]: {
                "status": "done" if rank[task["phase"]] <= boundary else "pending"
            }
            for task in plan["tasks"]
        }
        try:
            anchors = artifacts.anchors_verify(root, plan, {"tasks": expectations})
        except RddError as exc:
            last_error = exc
        else:
            matches.append((boundary, anchors))
    if len(matches) != 1:
        detail = f": {last_error}" if last_error is not None else ""
        raise RddError(
            "Anchors must match exactly one whole-phase prefix" + detail,
            "verification",
        ) from last_error
    return matches[0]


def _execute(root: Path, check: dict, **kwargs: Any) -> dict:
    # Keep the pure validation module importable before a process is requested.
    from .checks import execute_check
    return execute_check(root, check, **kwargs)


def _run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repository and run_id:
        return f"{server}/{repository}/actions/runs/{run_id}"
    return ""


def verify_preparation(root: Path, policy_root: Path, harness_source: str) -> dict:
    """Run preimplementation proofs with an independently pinned harness checkout.

    The caller supplies the operator pin; repository workflows take it from a
    repository variable, never from candidate manifests or workflow inputs.
    """
    from .engine import POLICY_PREFIXES, POLICY_FILES
    from .readiness import (required_probe_ids, validate_resources, validate_producers,
                            canonical_contract_check, verify_canonical_contract_receipts)
    root, policy_root = root.resolve(), policy_root.resolve()
    if root == policy_root or not _SHA.fullmatch(harness_source) or head(policy_root) != harness_source:
        raise RddError("Preparation CI needs a separate checkout of the exact trusted harness pin", "policy")
    if git(root, "merge-base", harness_source, "HEAD", check=False) != harness_source:
        raise RddError("Preparation candidate must descend from the trusted harness pin", "policy")
    clean(root)
    clean(policy_root)
    def harness_files(path):
        config = {"protected_prefixes": list(POLICY_PREFIXES), "protected_files": list(POLICY_FILES)}
        return {p: h for p, h in _policy_inventory(path, config).items()
                if p.startswith(POLICY_PREFIXES) or p in POLICY_FILES}
    trusted = harness_files(policy_root)
    if harness_files(root) != trusted:
        raise RddError("Preparation candidate changed the independently pinned harness", "policy")
    config = read_json(policy_root / ".rdd/config.json")
    spec, plan = read_json(root / ".rdd/spec.json"), read_json(root / ".rdd/plan/plan.json")
    if spec.get("schema_version") != 2 or plan.get("schema_version") != 2:
        raise RddError("Preparation CI requires a fresh v2 baseline", "policy")
    spec_lock = _read_lock(root, ".rdd/spec.lock.json", ".rdd/spec.json")
    plan_lock = _read_lock(root, ".rdd/plan/plan.lock.json", ".rdd/plan/plan.json")
    prepared = _read_prepared(root, spec_lock, plan_lock)
    artifacts.spec_validate(root, spec, artifacts.requirements(root, config["requirements"]), config)
    artifacts.plan_validate(root, plan, spec, spec_lock, config)
    validate_resources(root, spec)
    validate_producers(root, spec, plan)
    canonical = canonical_contract_check(spec)
    anchors = artifacts.anchors_verify(root, plan, {"tasks": {t["id"]: {"status": "pending"} for t in plan["tasks"]}})
    for path, expected in prepared["shell_hashes"].items():
        if file_hash(safe_path(root, path, allow_missing=False)) != expected:
            raise RddError(f"Prepared shell/projection changed: {path}", "policy")
    commit, sources = head(root), source_digest(root)
    platform = _host_platform()
    checks = artifacts.unique(spec["checks"], "check")
    selected = sorted(set(spec["contract_check_ids"] + required_probe_ids(spec, plan)))
    report = {"schema_version": 2, "scope": "preparation", "status": "failed", "application_complete": False,
              "source_commit": commit, "source_digest": sources, "harness_source": harness_source,
              "platform": platform, "run_url": _run_url(), "checks": [], "pending_external": [], "anchors": anchors}
    try:
        for cid in selected:
            check = checks[cid]
            envs = {e["id"]: e for e in spec["environments"]}
            if platform not in {envs[e]["platform"] for e in check["environments"]}:
                continue
            if check["host_profile"] or check["kind"] == "manual":
                report["pending_external"].append(cid)
                continue
            receipt = _execute(root, check, phase=None, task_id=None, expectation="pass",
                spec_digest=spec_lock["digest"], plan_digest=plan_lock["digest"], origin="ci",
                actor="github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "ci-controller", run_url=_run_url())
            report["checks"].append(receipt)
            if receipt["outcome"] != "pass":
                raise RddError(f"Preparation qualification failed: {cid}", "environment")
        if not report["checks"]:
            raise RddError("No required portable preparation checks ran on this platform", "environment")
        if any(r["check_id"] == canonical["id"] for r in report["checks"]):
            verify_canonical_contract_receipts(root, spec, report["checks"])
        if head(root) != commit or source_digest(root) != sources or harness_files(root) != trusted:
            raise RddError("Preparation candidate changed while CI ran", "policy")
        report["status"] = "passed"
        return report
    finally:
        write_json(root / ".rdd/evidence/preparation-ci.json", report)
        write_json(root / f".rdd/evidence/preparation-ci/{platform}.json", report)


def _release_identity(root: Path, policy_root: Path, branch: str | None,
                      policy_sha: str | None, source_sha: str | None) -> None:
    if not all(isinstance(value, str) and _SHA.fullmatch(value)
               for value in (policy_sha, source_sha)):
        raise RddError("Release policy and source pins must be paired full lowercase commit SHAs", "policy")
    if not isinstance(branch, str) or not re.fullmatch(r"codex/rdd-release/[A-Za-z0-9][A-Za-z0-9._-]{0,63}", branch):
        raise RddError("Release verification requires a canonical release branch", "policy")
    if policy_root == root:
        raise RddError("Release verification requires a separate prepared policy checkout", "policy")
    for checkout, pin, label in ((policy_root, policy_sha, "policy"), (root, source_sha, "source")):
        if Path(git(checkout, "rev-parse", "--show-toplevel")).resolve() != checkout:
            raise RddError(f"Release {label} must identify a repository checkout root", "policy")
        clean(checkout)
        if head(checkout) != pin:
            raise RddError(f"Release {label} pin does not match its checkout HEAD", "policy")
    if git(root, "merge-base", policy_sha, source_sha, check=False) != policy_sha:
        raise RddError("Release prepared policy commit must be an ancestor of the source pin", "policy")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
            raise RddError("Release pins are permitted only for a pull_request event", "policy")
        event = read_json(Path(os.environ.get("GITHUB_EVENT_PATH", "")))
        pr = event.get("pull_request", {}) if isinstance(event, dict) else {}
        repository = os.environ.get("GITHUB_REPOSITORY")
        if not isinstance(pr, dict):
            raise RddError("Release event has no pull request identity", "policy")
        source, base = pr.get("head"), pr.get("base")
        if (not isinstance(source, dict) or not isinstance(base, dict)
                or not isinstance(source.get("repo"), dict) or not isinstance(base.get("repo"), dict)
                or not repository or source["repo"].get("full_name") != repository
                or base["repo"].get("full_name") != repository
                or base.get("ref") != "main" or source.get("ref") != branch
                or source.get("sha") != source_sha):
            raise RddError("Release verification requires the exact same-repository release PR head targeting main", "policy")


def verify(root: Path, policy_root: Path | None = None, branch: str | None = None,
           release_policy: str | None = None, release_source: str | None = None) -> dict:
    """Verify one candidate without SQLite state; persist success or failure receipt.

    Ordinary policy comes from the PR base. Explicit paired release pins select
    an independently approved prepared policy checkout and exact candidate HEAD.
    Neither mode certifies task history or application completion.
    """
    root = root.resolve()
    policy_root = policy_root.resolve() if policy_root else root
    release = release_policy is not None or release_source is not None
    report: dict[str, Any] = {
        "schema_version": 1, "status": "failed", "scope": "unverified",
        "application_complete": False, "task_history_verified": False,
        "policy_source": "pinned_prepared_baseline" if release else
                         "separate_base" if policy_root != root else "same_checkout",
        "started_at": now(), "phase": None, "branch": branch, "checks": [],
        "observed_through_phase": None,
        "pending_external": [], "not_applicable_on_platform": [], "errors": [],
    }
    try:
        branch = _selected_branch(root, branch)
        if branch.startswith("codex/rdd-release/") and not release:
            raise RddError("Release branches require explicit paired policy and source pins", "policy")
        if release:
            _release_identity(root, policy_root, branch, release_policy, release_source)
            report.update({"release_policy": release_policy, "release_source": release_source})
        config = read_json(safe_path(policy_root, ".rdd/config.json", allow_missing=False))
        if not isinstance(config, dict):
            raise RddError("Trusted harness configuration must be an object", "policy")
        # This completes before selecting or executing any candidate command.
        protected = _assert_trusted_policy(root, policy_root, config)
        clean(root)
        report.update({"protected_digest": digest(protected), "source_commit": head(root),
                       "source_digest": source_digest(root), "policy_commit": head(policy_root),
                       "platform": _host_platform(), "run_url": _run_url()})
        policy_digest = source_digest(policy_root)
        trusted_locks = [safe_path(policy_root, path).is_file() for path in _LOCKS]
        candidate_locks = [safe_path(root, path).is_file() for path in _LOCKS]
        if not any(trusted_locks) and not any(candidate_locks):
            if release:
                raise RddError("Release verification requires a frozen prepared policy baseline", "policy")
            report.update({"status": "harness_only", "scope": "bootstrap",
                           "note": "No frozen implementation plan exists; only harness policy was verified."})
            return report
        if not all(trusted_locks) or not all(candidate_locks):
            raise RddError("Specification, plan, and preparation freezes must exist on both trusted base and candidate", "policy")

        spec_lock = _read_lock(root, ".rdd/spec.lock.json", ".rdd/spec.json")
        plan_lock = _read_lock(root, ".rdd/plan/plan.lock.json", ".rdd/plan/plan.json")
        prepared = _read_prepared(root, spec_lock, plan_lock)
        spec = read_json(safe_path(root, ".rdd/spec.json", allow_missing=False))
        plan = read_json(safe_path(root, ".rdd/plan/plan.json", allow_missing=False))
        if spec.get("schema_version") != 2 or plan.get("schema_version") != 2:
            raise RddError("Legacy baselines are read/export only; create a fresh reviewed v2 baseline", "policy")
        validate_artifact(root, "spec", spec)
        validate_artifact(root, "plan", plan)
        if (plan["spec_digest"] != spec_lock["digest"]
                or plan_lock.get("spec_digest") != spec_lock["digest"]):
            raise RddError("Plan references a different specification freeze", "specification")
        reqs = artifacts.requirements(root, config["requirements"])
        if spec_lock.get("requirements_digest") != reqs["digest"]:
            raise RddError("Requirements differ from their specification freeze", "specification")
        artifacts.spec_validate(root, spec, reqs, config)
        if release:
            # A final source checkout is not an approved prepared baseline, even
            # when its immutable freezes and preparation receipt are identical.
            trusted_spec_lock = _read_lock(policy_root, ".rdd/spec.lock.json", ".rdd/spec.json")
            trusted_plan_lock = _read_lock(policy_root, ".rdd/plan/plan.lock.json", ".rdd/plan/plan.json")
            trusted_prepared = _read_prepared(policy_root, trusted_spec_lock, trusted_plan_lock)
            trusted_spec = read_json(safe_path(policy_root, ".rdd/spec.json", allow_missing=False))
            trusted_plan = read_json(safe_path(policy_root, ".rdd/plan/plan.json", allow_missing=False))
            trusted_reqs = artifacts.requirements(policy_root, config["requirements"])
            artifacts.spec_validate(policy_root, trusted_spec, trusted_reqs, config)
            artifacts.plan_validate(policy_root, trusted_plan, trusted_spec, trusted_spec_lock, config)
            artifacts.anchors_verify(policy_root, trusted_plan, {
                "tasks": {task["id"]: {"status": "pending"} for task in trusted_plan["tasks"]}
            })
            for path, expected in trusted_prepared["shell_hashes"].items():
                if file_hash(safe_path(policy_root, path, allow_missing=False)) != expected:
                    raise RddError(f"Release policy preparation shell changed: {path}", "policy")
            if branch != f"codex/rdd-release/{prepared['run_id']}":
                raise RddError("Release branch must name the pinned prepared run", "policy")
        # Preparation already validated immutable dependency cuts. Repeating its
        # file-existence checks here would reject legitimate completed deletions.
        # The local run locator is intentionally ignored by Git. The frozen
        # preparation receipt supplies CI identity without a runtime database.
        phase, selected_branch = _selected_phase(root, branch, plan, prepared["run_id"])
        report.update({"run_id": prepared["run_id"], "phase": phase, "branch": selected_branch,
                       "spec_digest": spec_lock["digest"], "plan_digest": plan_lock["digest"]})
        phases = [item["id"] for item in plan["phases"]]
        rank = {value: i for i, value in enumerate(phases)}
        if phase:
            boundary = rank[phase]
            statuses = {task["id"]: {"status": "done" if rank[task["phase"]] <= boundary else "pending"}
                        for task in plan["tasks"]}
            report["anchors"] = artifacts.anchors_verify(root, plan, {"tasks": statuses})
        else:
            boundary, report["anchors"] = _observed_anchor_boundary(root, plan)
            if report["policy_commit"] != report["source_commit"]:
                base_boundary, _ = _observed_anchor_boundary(policy_root, plan)
                if boundary < base_boundary:
                    raise RddError(
                        "Candidate marker projection reduces CI coverage below the trusted base",
                        "verification",
                    )
        if release and (phase is not None or boundary != len(phases) - 1
                        or report["anchors"]["remaining"] != 0):
            raise RddError("Release source requires the completed full phase prefix with no remaining anchors", "verification")
        report["observed_through_phase"] = phases[boundary] if boundary >= 0 else None

        from .readiness import required_probe_ids, canonical_contract_check, verify_canonical_contract_receipts
        canonical = canonical_contract_check(spec)
        ordered_ids = list(spec["contract_check_ids"]) + required_probe_ids(spec, plan)
        for record in plan["phases"][:boundary + 1]:
            ordered_ids.extend(record["checks"])
        if boundary == len(phases) - 1:
            ordered_ids.extend(spec["project_check_ids"])
        checks = artifacts.unique(spec["checks"], "check")
        selected_ids = list(dict.fromkeys(ordered_ids))
        artifacts.subset(selected_ids, checks, "CI cumulative checks")
        report["scheduled_check_ids"] = selected_ids
        executable = []
        for check_id in selected_ids:
            check = checks[check_id]
            if "any" not in check["platforms"] and report["platform"] not in check["platforms"]:
                report["not_applicable_on_platform"].append(check_id)
                continue
            if check["kind"] == "manual" or check.get("host_profile"):
                report["pending_external"].append({"check_id": check_id, "kind": check["kind"],
                    "host_profile": check.get("host_profile"),
                    "reason": "Phase/project gates require separate exact-revision manual or qualified reference-host evidence."})
                continue
            executable.append(check)
        if not executable:
            raise RddError("No ordinary platform-relevant checks are executable; external evidence alone cannot make CI green", "environment")
        for check in executable:
            evidence = _execute(root, check, phase=phase, task_id=None, expectation="pass",
                                spec_digest=spec_lock["digest"], plan_digest=plan_lock["digest"],
                                origin="ci", actor="github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "ci-controller",
                                run_url=report["run_url"])
            report["checks"].append(evidence)
            if not isinstance(evidence, dict) or evidence.get("outcome") != "pass" or evidence.get("expectation") != "pass":
                raise RddError(f"CI check did not pass: {check['id']}", "verification")
            if (evidence.get("source_commit") != report["source_commit"]
                    or evidence.get("source_digest") != report["source_digest"]
                    or evidence.get("check_id") != check["id"]):
                raise RddError(f"CI check evidence is stale or mismatched: {check['id']}", "verification")
        if any(r["check_id"] == canonical["id"] for r in report["checks"]):
            verify_canonical_contract_receipts(root, spec, report["checks"])
        if head(root) != report["source_commit"] or source_digest(root) != report["source_digest"]:
            raise RddError("Candidate source changed while checks ran; rerun against a stable commit", "verification")
        if release:
            clean(root)
            clean(policy_root)
            if head(policy_root) != release_policy or source_digest(policy_root) != policy_digest:
                raise RddError("Pinned prepared policy changed while checks ran", "policy")
        # Detect policy changes even if a check tried to hide them behind ignores.
        after_policy = _assert_trusted_policy(root, policy_root, config)
        if after_policy != protected:
            raise RddError("Trusted policy changed while checks ran", "policy")
        scope = ("release_source" if release else "phase_cumulative" if phase else
                 "source_cumulative" if boundary >= 0 else "prepared_baseline")
        report.update({"status": "passed" if boundary >= 0 else "harness_only",
                       "scope": scope,
                       "note": "Marker shape selects CI coverage; it is not completion evidence. Task history, independent review, manual checks and reference-host qualification remain phase/project gate responsibilities."})
        return report
    except RddError as exc:
        report["errors"].append({"kind": exc.kind, "message": str(exc)})
        raise
    finally:
        report["finished_at"] = now()
        destination = safe_path(root, ".rdd/evidence/ci.json")
        write_json(destination, report)
