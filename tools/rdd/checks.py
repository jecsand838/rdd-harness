"""Execute frozen checks and independently evaluate their measurable evidence."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
import statistics
import sys
import uuid

from .adapters import RddAdapterError, _strict_json, run_argv
from .common import (RddError, atomic_write, canonical, file_hash, head, now,
                     read_json, safe_path, source_digest, validate_artifact, write_json)


MAX_CAPTURE_BYTES = 4 * 1024 * 1024
# Two captured streams can expand when JSON escapes control characters.
MAX_RECEIPT_LOG_BYTES = 64 * 1024 * 1024
_ENVIRONMENT_ERROR = re.compile(
    r"(?im)(ModuleNotFoundError|ImportError|SyntaxError|cannot find (?:module|crate)|"
    r"could not compile|error\[E\d+\]|command not found|No such file or directory)"
)


def manual_protocol_ref(spec_digest: str, check_id: str) -> str:
    """Identify the frozen check containing the human verification protocol."""
    return f"spec:{spec_digest}#check:{check_id}"


def _behavioral_red(check: dict, stdout: str, stderr: str, returncode: int) -> bool:
    if check["kind"] != "test" or not check["red_pattern"] or returncode <= 0:
        return False
    output = stdout + stderr
    if _ENVIRONMENT_ERROR.search(output):
        return False
    try:
        return re.search(check["red_pattern"], output) is not None
    except re.error as exc:
        raise RddError(f"Invalid frozen RED pattern for {check['id']}: {exc}") from exc


def _qualified_host(host: object, profile: str, platform: str, *, kind: str = "validation") -> None:
    if (not isinstance(host, dict) or host.get("profile") != profile
            or host.get("platform") != platform or not host.get("qualification")):
        raise RddError("Host qualification does not match the frozen check profile/platform", kind)


def _benchmark_payload(text: str) -> dict:
    try:
        payload = _strict_json(text)
    except (ValueError, TypeError) as exc:
        raise RddError(f"Benchmark output is not unambiguous finite JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RddError("Benchmark output must be a JSON object")
    return payload


def _matching_benchmark_host(check: dict, payload: dict) -> None:
    if check["host_profile"]:
        environment = payload.get("environment")
        if not isinstance(environment, dict) or environment.get("host_profile") != check["host_profile"]:
            raise RddError("Benchmark output does not identify its qualified host")


def _receipt_log(path: Path, expected_digest: str) -> dict:
    """Hash and parse the same bounded bytes, including for imported receipts."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_RECEIPT_LOG_BYTES + 1)
    except OSError as exc:
        raise RddError(f"Cannot read evidence log: {exc}") from exc
    if len(raw) > MAX_RECEIPT_LOG_BYTES:
        raise RddError("Evidence log exceeds the verification size bound")
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise RddError("Evidence log hash mismatch")
    try:
        log = _strict_json(raw.decode("utf-8"))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise RddError(f"Evidence log is not unambiguous finite JSON: {exc}") from exc
    if not isinstance(log, dict):
        raise RddError("Evidence log must be a JSON object")
    return log


def platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise RddError(f"Unsupported verification platform: {sys.platform}", "environment")


def command_argv(check: dict) -> list[str]:
    # Exactly one portable token; no environment interpolation or shell parsing.
    return [sys.executable if arg == "{python}" else arg for arg in check["argv"]]


def evaluate_metrics(check: dict, payload: dict) -> dict[str, float]:
    if not check.get("metrics"):
        raise RddError("A benchmark requires at least one frozen metric limit")
    if not isinstance(payload, dict) or type(payload.get("errors")) is not int or payload["errors"] != 0:
        raise RddError("Benchmark must report integer errors=0, raw samples, units, and environment")
    if not isinstance(payload.get("environment"), dict) or not payload["environment"]:
        raise RddError("Benchmark environment inventory is missing")
    if not isinstance(payload.get("samples"), dict) or not isinstance(payload.get("units"), dict):
        raise RddError("Benchmark samples and units must be maps")
    answer = {}
    for limit in check["metrics"]:
        name = limit["name"]
        samples = payload["samples"].get(name)
        if not isinstance(samples, list) or len(samples) < limit["minimum_samples"]:
            raise RddError(f"Benchmark {name} has too few samples")
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in samples):
            raise RddError(f"Benchmark {name} has nonfinite or nonnumeric samples")
        if payload["units"].get(name) != limit["unit"]:
            raise RddError(f"Benchmark {name} unit does not match frozen limit")
        values = sorted(samples)
        statistic = limit["statistic"]
        if statistic in {"p95", "p50"}:
            quantile = 0.95 if statistic == "p95" else 0.50
            measured = float(values[math.ceil(quantile * len(values)) - 1])
        elif statistic == "max":
            measured = float(max(values))
        elif statistic == "min":
            measured = float(min(values))
        elif statistic == "mean":
            measured = float(statistics.fmean(values))
        else:
            raise RddError(f"Unsupported statistic {statistic}")
        key = f"{name}.{statistic}"
        if key in answer:
            raise RddError(f"Duplicate benchmark limit {key}")
        answer[key] = measured
        if limit["comparison"] not in {"lte", "gte"}:
            raise RddError(f"Unsupported benchmark comparison {limit['comparison']}")
        passed = measured <= limit["limit"] if limit["comparison"] == "lte" else measured >= limit["limit"]
        if not passed:
            raise RddError(f"Benchmark {key}={measured} {limit['unit']} violates {limit['comparison']} {limit['limit']}")
    return answer


def execute_check(root: Path, check: dict, *, phase: str | None, task_id: str | None,
                  expectation: str, spec_digest: str, plan_digest: str | None,
                  origin: str = "local", actor: str = "controller", run_url: str = "") -> dict:
    if expectation not in {"pass", "fail"}:
        raise RddError("Check expectation must be pass or fail")
    platform = platform_name()
    if "any" not in check["platforms"] and platform not in check["platforms"]:
        raise RddError(f"{check['id']} must run on {check['platforms']}; current host is {platform}", "environment")
    if check["kind"] == "manual":
        raise RddError(f"{check['id']} needs an explicit qualified manual receipt; use check import", "environment")
    if expectation == "fail" and (check["kind"] != "test" or not check["red_pattern"]):
        raise RddError("RED evidence requires a test with a frozen behavioral assertion pattern")
    host = None
    if check["host_profile"]:
        host_path = root / ".rdd/runtime/host.json"
        if not host_path.is_file():
            raise RddError(f"Check needs qualified host profile {check['host_profile']}; see benchmarks/README.md", "environment")
        host = read_json(host_path)
        _qualified_host(host, check["host_profile"], platform, kind="environment")
    commit, before = head(root), source_digest(root)
    eid = "E" + uuid.uuid4().hex
    rel = f".rdd/evidence/checks/{eid}.log"
    stdout_path = safe_path(root, f".rdd/runtime/checks/{eid}.stdout")
    stderr_path = safe_path(root, f".rdd/runtime/checks/{eid}.stderr")
    started = now()
    try:
        result = run_argv(command_argv(check), cwd=safe_path(root, check["cwd"]),
                          timeout=check["timeout_seconds"], stdout_path=stdout_path,
                          stderr_path=stderr_path, max_capture_bytes=MAX_CAPTURE_BYTES)
    except RddAdapterError as exc:
        raise RddError(str(exc), "environment") from exc
    # The runner streams complete raw files separately, but parsing and receipt
    # construction must use its bounded in-memory capture. Never reload an
    # arbitrarily large child-produced file after output_truncated is set.
    stdout, stderr = result.stdout, result.stderr
    detail = ""
    metrics = {}
    outcome = "fail"
    if result.timed_out:
        detail = "Command timed out; this is never behavioral RED."
    elif result.output_truncated:
        detail = "Command output exceeded the capture budget; evidence is inconclusive."
    elif source_digest(root) != before or head(root) != commit:
        detail = "Verification command mutated source or HEAD; receipt is invalid."
    elif expectation == "fail":
        # A compiler/parser failure is not an unimplemented behavioral assertion.
        if _behavioral_red(check, stdout, stderr, result.returncode):
            outcome = "red"
        else:
            detail = "Expected the frozen behavioral assertion to fail; infrastructure/compile failure or a green run is not RED."
    elif result.returncode == 0:
        if check["kind"] == "benchmark":
            try:
                payload = _benchmark_payload(stdout)
                measured = evaluate_metrics(check, payload)
                _matching_benchmark_host(check, payload)
                metrics = measured
                outcome = "pass"
            except (RddError, ValueError, TypeError) as exc:
                detail = str(exc)
        else:
            outcome = "pass"
    else:
        detail = f"Command returned {result.returncode}."
    log = {"schema_version": 1, "argv": check["argv"], "stdout": stdout,
           "stderr": stderr, "evaluation": detail, "host": host}
    log_path = safe_path(root, rel)
    atomic_write(log_path, canonical(log) + b"\n")
    evidence = {"schema_version": 1, "id": eid, "check_id": check["id"], "phase": phase,
                "task_id": task_id, "source_commit": commit, "source_digest": before,
                "spec_digest": spec_digest, "plan_digest": plan_digest,
                "command": check["argv"], "platform": platform, "started_at": started,
                "finished_at": now(), "returncode": result.returncode,
                "expectation": expectation, "outcome": outcome, "log_path": rel,
                "log_digest": file_hash(log_path), "origin": origin,
                "provenance": {"actor": actor, "run_url": run_url,
                               "host_profile": check["host_profile"] or ""}, "metrics": metrics}
    validate_artifact(root, "evidence", evidence)
    write_json(root / f".rdd/evidence/checks/{eid}.json", evidence)
    return evidence


def verify_receipt(root: Path, evidence: dict, check: dict, *, commit: str,
                   sources: str, spec_digest: str, plan_digest: str | None,
                   require_pass: bool = True) -> None:
    validate_artifact(root, "evidence", evidence)
    expected = {"check_id": check["id"], "source_commit": commit, "source_digest": sources,
                "spec_digest": spec_digest, "plan_digest": plan_digest, "command": check["argv"]}
    for key, value in expected.items():
        if evidence[key] != value:
            raise RddError(f"Receipt {evidence['id']} has stale or mismatched {key}")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", evidence["source_commit"]):
        raise RddError("Receipt requires a full Git commit hash")
    if require_pass and (evidence["outcome"] != "pass" or evidence["expectation"] != "pass" or evidence["returncode"] != 0):
        raise RddError(f"Receipt {evidence['id']} is not a passing check")
    if "any" not in check["platforms"] and evidence["platform"] not in check["platforms"]:
        raise RddError("Receipt is from the wrong native platform")
    if evidence["provenance"]["host_profile"] != (check["host_profile"] or ""):
        raise RddError("Receipt host profile mismatch")
    if not evidence["log_path"].startswith(".rdd/evidence/"):
        raise RddError("Evidence logs must be staged inside .rdd/evidence/")
    log_path = safe_path(root, evidence["log_path"], allow_missing=False)
    log = _receipt_log(log_path, evidence["log_digest"])
    if evidence["origin"] == "ci" and not evidence["provenance"]["run_url"].startswith("https://github.com/"):
        raise RddError("CI evidence needs its actual GitHub Actions run URL")
    if check["kind"] == "manual":
        if evidence["origin"] != "manual" or not evidence["provenance"]["actor"]:
            raise RddError("Manual checks require an identified human evaluator")
        observations = log.get("observations")
        meaningful_observations = (
            isinstance(observations, str) and bool(observations.strip())
        ) or (
            isinstance(observations, list) and bool(observations)
            and all(isinstance(item, str) and bool(item.strip()) for item in observations)
        )
        if log.get("decision") != "pass" or not meaningful_observations:
            raise RddError("Manual evidence needs a passing decision and nonempty written observations")
        expected_protocol = manual_protocol_ref(spec_digest, check["id"])
        if log.get("protocol") != expected_protocol:
            raise RddError(f"Manual evidence protocol must reference the frozen check as {expected_protocol}")
    else:
        if log.get("schema_version") != 1 or log.get("argv") != check["argv"]:
            raise RddError("Evidence log command does not match the frozen check")
        if not isinstance(log.get("stdout"), str) or not isinstance(log.get("stderr"), str):
            raise RddError("Evidence log stdout/stderr must be strings")
        if not isinstance(log.get("evaluation"), str):
            raise RddError("Evidence log is missing its recorded evaluation")
        if evidence["outcome"] in {"pass", "red"} and log["evaluation"]:
            raise RddError("Passing or RED receipt contradicts a failed/inconclusive log evaluation")
        if check["host_profile"]:
            _qualified_host(log.get("host"), check["host_profile"], evidence["platform"])
        if evidence["outcome"] == "red":
            if evidence["expectation"] != "fail" or not _behavioral_red(
                check, log["stdout"], log["stderr"], evidence["returncode"]
            ):
                raise RddError("Imported RED receipt lacks its frozen failing behavioral assertion")
        if check["kind"] == "benchmark" and require_pass:
            payload = _benchmark_payload(log["stdout"])
            measured = evaluate_metrics(check, payload)
            _matching_benchmark_host(check, payload)
            if measured != evidence["metrics"]:
                raise RddError("Reported benchmark aggregates differ from independently evaluated raw samples")
