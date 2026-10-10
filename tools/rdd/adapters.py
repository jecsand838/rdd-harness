"""Bounded, observable adapters for Codex, Git worktrees, and GitHub phase PRs.

Every command is an argv list. Nothing in requirements, a prompt, or a PR body is
evaluated by a shell. External success is always followed by evidence checks.
The controller owns run locks, schema baselines, and authorization policy.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .common import RddError
from .profiles import load_profiles


class RddAdapterError(RuntimeError):
    """A concrete external capability or evidence blocker."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    output_truncated: bool = False


def run_argv(
    argv: Sequence[str], cwd: str | Path, timeout: float = 120, *,
    input_text: str | None = None, stdout_path: str | Path | None = None,
    stderr_path: str | Path | None = None,
    on_stdout_line: Callable[[str], None] | None = None,
    env: Mapping[str, str] | None = None, max_capture_bytes: int = 4 * 1024 * 1024,
) -> CommandResult:
    """Run without a shell, drain both pipes, stream logs, and enforce a deadline.

    Captured output is bounded; optional files retain the complete stream. A
    timed-out POSIX process group is killed. Windows uses taskkill /T if present.
    Callbacks run on the stdout reader thread and must not invoke this runner.
    """
    if isinstance(argv, (str, bytes)) or not argv or any(
        not isinstance(x, str) or "\0" in x for x in argv
    ):
        raise RddAdapterError("invalid-argv", "Commands must be a nonempty argv list of strings without NUL.")
    if not math.isfinite(timeout) or timeout <= 0 or max_capture_bytes < 1:
        raise RddAdapterError("invalid-limit", "Timeout and capture limit must be positive and finite.")
    root = Path(cwd).resolve()
    if not root.is_dir():
        raise RddAdapterError("missing-cwd", f"Working directory does not exist: {root}")
    started = time.monotonic()
    merged_env = dict(os.environ)
    merged_env.update({"GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"})
    if env:
        merged_env.update(env)
    streams: dict[str, list[str]] = {"stdout": [], "stderr": []}
    sizes = {"stdout": 0, "stderr": 0}
    truncated = {"stdout": False, "stderr": False}
    reader_errors: list[BaseException] = []
    logs: dict[str, Any] = {}
    try:
        for name, path in (("stdout", stdout_path), ("stderr", stderr_path)):
            if path is not None:
                dest = Path(path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Never append to evidence from an earlier attempt.
                logs[name] = dest.open("x", encoding="utf-8", newline="")
        try:
            proc = subprocess.Popen(
                list(argv), cwd=root, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", bufsize=1, env=merged_env,
                shell=False, start_new_session=(os.name == "posix"),
            )
        except FileNotFoundError as exc:
            raise RddAdapterError("missing-tool", f"Executable not found: {argv[0]}") from exc
        except OSError as exc:
            raise RddAdapterError("spawn-failed", f"Could not start {argv[0]}: {exc}") from exc

        def read_pipe(name: str, pipe: Any) -> None:
            try:
                for line in pipe:
                    if name in logs:
                        logs[name].write(line)
                        logs[name].flush()
                    available = max_capture_bytes - sizes[name]
                    encoded = line.encode("utf-8")
                    if available > 0:
                        streams[name].append(encoded[:available].decode("utf-8", errors="replace"))
                        sizes[name] += min(len(encoded), available)
                    if len(encoded) > max(available, 0):
                        truncated[name] = True
                    if name == "stdout" and on_stdout_line:
                        try:
                            on_stdout_line(line)
                        except BaseException as exc:
                            # Keep draining the pipe so a failed observer cannot deadlock a worker.
                            reader_errors.append(exc)
            except BaseException as exc:
                reader_errors.append(exc)
            finally:
                pipe.close()

        def write_input() -> None:
            try:
                if input_text:
                    proc.stdin.write(input_text)
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        threads = [threading.Thread(target=read_pipe, args=(name, pipe), daemon=True)
                   for name, pipe in (("stdout", proc.stdout), ("stderr", proc.stderr))]
        threads.append(threading.Thread(target=write_input, daemon=True))
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            proc.wait(timeout=max(0.01, timeout - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "posix":
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                try:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, timeout=10, check=False, shell=False)
                except (OSError, subprocess.TimeoutExpired):
                    proc.kill()
            proc.wait(timeout=10)
        for thread in threads:
            thread.join(timeout=5)
        if any(thread.is_alive() for thread in threads):
            if os.name == "posix":
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for thread in threads:
                thread.join(timeout=1)
            raise RddAdapterError("stream-stuck", "A child retained a process pipe after the command ended.")
        if reader_errors:
            raise RddAdapterError("stream-failed", f"Could not record process output: {reader_errors[0]}")
        return CommandResult(tuple(argv), proc.returncode, "".join(streams["stdout"]),
                             "".join(streams["stderr"]), time.monotonic() - started,
                             timed_out, any(truncated.values()))
    finally:
        for log in logs.values():
            log.close()


def _checked(result: CommandResult, operation: str) -> CommandResult:
    if result.timed_out:
        raise RddAdapterError("timeout", f"{operation} exceeded its time budget.")
    if result.returncode != 0:
        detail = result.stderr.strip()[:1200] or result.stdout.strip()[:1200]
        raise RddAdapterError("command-failed", f"{operation} failed ({result.returncode}): {detail}")
    if result.output_truncated:
        raise RddAdapterError("truncated-output", f"{operation} exceeded its output capture budget.")
    return result


def _json_output(result: CommandResult, operation: str, *, allow_failure: bool = False) -> Any:
    if not allow_failure:
        _checked(result, operation)
    elif result.timed_out or result.output_truncated:
        raise RddAdapterError("inconclusive-output", f"{operation} timed out or its output was truncated.")
    try:
        return _strict_json(result.stdout)
    except (ValueError, TypeError) as exc:
        raise RddAdapterError("invalid-json", f"{operation} did not return valid JSON.") from exc


def _strict_json(text: str) -> Any:
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        answer = {}
        for key, value in rows:
            if key in answer:
                raise ValueError(f"Duplicate JSON key: {key}")
            answer[key] = value
        return answer
    def nonfinite(value: str) -> Any:
        raise ValueError(f"Nonfinite JSON number: {value}")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)


def _ref(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", value):
        raise RddAdapterError("invalid-ref", "A branch/ref must be a plain ref name, not an option or revision expression.")
    if any(x in value for x in ("..", "//", "/.", ".lock/")) or value.endswith(("/", ".", ".lock")):
        raise RddAdapterError("invalid-ref", "Invalid Git ref name.")
    return value


def _sha(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise RddAdapterError("invalid-sha", "Evidence requires a complete lowercase Git object ID.")
    return value


def phase_branch(run_id: str, phase: int) -> str:
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_id):
        raise RddAdapterError("invalid-run-id", "Run IDs use 1-64 letters, numbers, dots, underscores, or hyphens.")
    if isinstance(phase, bool) or not isinstance(phase, int) or not 1 <= phase <= 9999:
        raise RddAdapterError("invalid-phase", "Phase number must be an integer from 1 through 9999.")
    return _ref(f"rdd/{run_id}/p{phase:02d}")


class GitAdapter:
    def __init__(self, repo: str | Path, runner: Callable[..., CommandResult] = run_argv):
        self.repo = Path(repo).resolve()
        self.runner = runner

    def _git(self, *args: str, cwd: Path | None = None, timeout: float = 120) -> CommandResult:
        return self.runner(["git", *args], cwd=cwd or self.repo, timeout=timeout)

    def current_head(self, ref: str = "HEAD") -> str:
        result = _checked(self._git("rev-parse", "--verify", f"{_ref(ref)}^{{commit}}"), "Resolve Git commit")
        return _sha(result.stdout.strip())

    def status(self, path: str | Path | None = None) -> list[str]:
        result = _checked(self._git("status", "--porcelain=v1", "-z", "--untracked-files=all",
                                    cwd=Path(path).resolve() if path else None), "Read Git status")
        return [entry for entry in result.stdout.split("\0") if entry]

    def create_phase_branch(self, run_id: str, phase: int, base: str) -> str:
        branch = phase_branch(run_id, phase)
        base_sha = self.current_head(base)
        exists = self._git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
        if exists.returncode == 0:
            related = self._git("merge-base", "--is-ancestor", base_sha, branch)
            _checked(related, "Existing phase branch must descend from its recorded base")
            return branch
        if exists.returncode != 1:
            _checked(exists, "Check phase branch")
        _checked(self._git("branch", branch, base_sha), "Create phase branch")
        return branch

    def ensure_worktree(self, path: str | Path, branch: str, base: str) -> Path:
        branch = _ref(branch)
        base_sha = self.current_head(base)
        target = Path(path).absolute()
        if target.is_symlink():
            raise RddAdapterError("unsafe-worktree", "A worktree path must not be a symlink.")
        target = target.resolve()
        common = _checked(self._git("rev-parse", "--git-common-dir"), "Read repository identity").stdout.strip()
        common_path = (self.repo / common).resolve()
        if target.exists():
            if not target.is_dir() or any(target.iterdir()):
                # A nonempty path is reusable only when it is the exact expected worktree.
                actual = self._git("rev-parse", "--show-toplevel", cwd=target)
                if actual.returncode != 0 or Path(actual.stdout.strip()).resolve() != target:
                    raise RddAdapterError("occupied-worktree", f"Refusing to overwrite existing path: {target}")
                other = _checked(self._git("rev-parse", "--git-common-dir", cwd=target), "Read worktree repository").stdout.strip()
                if (target / other).resolve() != common_path:
                    raise RddAdapterError("wrong-repository", "Existing worktree belongs to another repository.")
                actual_branch = _checked(self._git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=target), "Read worktree branch").stdout.strip()
                if actual_branch != branch or self.status(target):
                    raise RddAdapterError("dirty-worktree", "Existing worktree has a different branch or uncommitted files; preserve it for recovery.")
                _checked(self._git("merge-base", "--is-ancestor", base_sha, "HEAD", cwd=target), "Validate worktree base")
                return target
        target.parent.mkdir(parents=True, exist_ok=True)
        exists = self._git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
        if exists.returncode == 0:
            _checked(self._git("merge-base", "--is-ancestor", base_sha, branch), "Validate existing branch base")
            _checked(self._git("worktree", "add", str(target), branch), "Create worktree")
        elif exists.returncode == 1:
            _checked(self._git("worktree", "add", "-b", branch, str(target), base_sha), "Create worktree and branch")
        else:
            _checked(exists, "Check worktree branch")
        return target


class GitHubAdapter:
    """One PR per run/phase. Publishing never force pushes, merges, or messages reviewers."""

    PR_FIELDS = "number,url,headRefName,headRefOid,baseRefName,baseRefOid,state,isDraft,isCrossRepository,body,reviewDecision,latestReviews,mergeable,mergeStateStatus,statusCheckRollup"

    def __init__(self, repo: str | Path, runner: Callable[..., CommandResult] = run_argv,
                 repository: str | None = None):
        self.repo = Path(repo).resolve()
        self.runner = runner
        self.git = GitAdapter(self.repo, runner)
        if repository is not None and not re.fullmatch(r"(?:[A-Za-z0-9.-]+/)?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise RddAdapterError("invalid-repository", "Repository must use OWNER/REPO or HOST/OWNER/REPO format.")
        self.repository = repository

    def _gh(self, *args: str) -> CommandResult:
        command = ["gh", *args]
        if self.repository:
            command += ["--repo", self.repository]
        return self.runner(command, cwd=self.repo, timeout=120)

    def _find(self, branch: str) -> list[dict[str, Any]]:
        result = _json_output(self._gh("pr", "list", "--state", "all", "--head", branch,
                                      "--limit", "100", "--json", self.PR_FIELDS), "Find phase pull request")
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise RddAdapterError("invalid-pr-list", "GitHub returned an invalid PR list.")
        # --head is a search filter: compare the field too and reject ambiguous results.
        return [item for item in result if item.get("headRefName") == branch]

    def preparation_status(self, run_url: str, candidate_sha: str, expected_harness_sha: str) -> dict[str, Any]:
        """Observe preparation success on GitHub, including the independent policy pin.

        Imported log provenance alone cannot establish that Actions ran. The
        workflow bytes must also match the pinned harness, so a candidate cannot
        replace verification with a successful no-op job.
        """
        _sha(candidate_sha)
        _sha(expected_harness_sha)
        if self.repository:
            parts = self.repository.split("/")
            host, owner, name = (["github.com", *parts] if len(parts) == 2 else parts)
        else:
            remote = _checked(self.git._git("remote", "get-url", "origin"), "Read preparation repository").stdout.strip()
            match = re.fullmatch(r"(?:https://|ssh://git@|git@)([A-Za-z0-9.-]+)[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", remote)
            if not match:
                raise RddAdapterError("invalid-repository", "Preparation requires an identified GitHub origin or configured repository.")
            host, owner, name = match.groups()
        prefix = f"https://{host}/{owner}/{name}/actions/runs/"
        match = re.fullmatch(re.escape(prefix) + r"([1-9][0-9]*)", run_url, re.IGNORECASE)
        if not match:
            raise RddAdapterError("invalid-run-url", "Preparation evidence must name a canonical Actions run in this repository.")
        run_id = int(match.group(1))

        def api(path: str) -> dict:
            # `gh api` has --hostname, not the --repo option of PR commands.
            response = _json_output(self.runner(["gh", "api", "--hostname", host, f"repos/{owner}/{name}/{path}"],
                                                cwd=self.repo, timeout=120), "Read preparation Actions evidence")
            if not isinstance(response, dict):
                raise RddAdapterError("invalid-actions-evidence", "GitHub returned malformed preparation evidence.")
            return response

        before = api(f"actions/runs/{run_id}")
        attempt = before.get("run_attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise RddAdapterError("invalid-actions-evidence", "Preparation run has no valid attempt identity.")
        jobs = api(f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
        variable = api("actions/variables/RDD_PREPARATION_HARNESS_SHA")
        workflow_path = ".github/workflows/preparation.yml"
        candidate_workflow = api(f"contents/{workflow_path}?ref={candidate_sha}")
        harness_workflow = api(f"contents/{workflow_path}?ref={expected_harness_sha}")
        after = api(f"actions/runs/{run_id}")
        blockers = []
        for field in ("head_sha", "path", "run_attempt", "status", "conclusion"):
            if before.get(field) != after.get(field):
                blockers.append(f"Preparation {field} changed while evidence was collected")
        repository = after.get("repository")
        if (after.get("id") != run_id or str(after.get("html_url", "")).lower() != run_url.lower()
                or not isinstance(repository, dict)
                or str(repository.get("full_name", "")).lower() != f"{owner}/{name}".lower()):
            blockers.append("Actions returned another repository or run identity")
        if after.get("head_sha") != candidate_sha:
            blockers.append("Preparation run does not target the exact materialized candidate")
        if after.get("path") != workflow_path or after.get("event") not in {"push", "workflow_dispatch"}:
            blockers.append("Preparation requires the registered workflow and event")
        if after.get("status") != "completed" or after.get("conclusion") != "success":
            blockers.append("Preparation Actions run has not completed successfully")
        if variable.get("name") != "RDD_PREPARATION_HARNESS_SHA" or variable.get("value") != expected_harness_sha:
            blockers.append("Preparation harness differs from the independently selected repository pin")
        if (not re.fullmatch(r"[0-9a-f]{40}", str(harness_workflow.get("sha")))
                or candidate_workflow.get("sha") != harness_workflow.get("sha")
                or any(value.get("type") != "file" or value.get("path") != workflow_path
                       for value in (candidate_workflow, harness_workflow))):
            blockers.append("Candidate preparation workflow differs from the trusted harness")
        observed = jobs.get("jobs")
        if (not isinstance(observed, list) or not observed or type(jobs.get("total_count")) is not int
                or jobs.get("total_count") != len(observed)
                or any(not isinstance(job, dict) for job in observed)):
            raise RddAdapterError("invalid-actions-evidence", "Preparation job inventory is missing, malformed or truncated.")
        if any(job.get("status") != "completed" or job.get("conclusion") != "success" for job in observed):
            blockers.append("Preparation contains a failed, pending or skipped job")
        proofs = [job for job in observed if str(job.get("name", "")).startswith("preparation (")]
        if not proofs or any(not isinstance(job.get("steps"), list) or not any(step.get("name") == "Verify committed preparation with trusted controller"
                                     and step.get("status") == "completed" and step.get("conclusion") == "success"
                                     for step in job.get("steps", []) if isinstance(step, dict)) for job in proofs):
            blockers.append("No successful trusted preparation check step for every declared job")
        return {"ready": not blockers, "url": run_url, "run_id": run_id, "attempt": attempt,
                "head_sha": after.get("head_sha"), "harness_sha": expected_harness_sha,
                "workflow_blob": candidate_workflow.get("sha"), "blockers": blockers,
                "jobs": [{key: job.get(key) for key in ("id", "name", "status", "conclusion")} for job in observed]}

    def publish_phase_pr(self, run_id: str, phase: int, base: str,
                         body_file: str | Path, title: str | None = None,
                         remote: str = "origin", *, expected_base_sha: str | None = None) -> dict[str, Any]:
        branch = phase_branch(run_id, phase)
        base = _ref(base)
        remote = _ref(remote)
        if "/" in remote or remote in (".", ".."):
            raise RddAdapterError("invalid-remote", "Use a named Git remote, not a path or URL.")
        marker = f"<!-- rdd:run={run_id} phase={phase} -->"
        if self.git.status():
            raise RddAdapterError("dirty-repository", "Commit phase files before publishing its PR.")
        head = self.git.current_head(branch)
        base_sha = self.git.current_head(base)
        if expected_base_sha is not None and base_sha != _sha(expected_base_sha):
            raise RddAdapterError("moved-base", "Local base moved from the recorded phase base; do not restack a sealed phase.")
        remote_base = _checked(self.git._git("ls-remote", "--heads", remote, f"refs/heads/{base}"), "Read remote stack base")
        remote_rows = [row.split() for row in remote_base.stdout.splitlines() if row.strip()]
        if len(remote_rows) != 1 or len(remote_rows[0]) != 2 or remote_rows[0][0] != base_sha:
            raise RddAdapterError("moved-remote-base", "Remote base is missing or differs from the recorded local base; revalidate before publishing.")
        _checked(self.git._git("merge-base", "--is-ancestor", base_sha, head), "Phase must descend from the stack base")
        existing = self._find(branch)
        if len(existing) > 1:
            raise RddAdapterError("duplicate-pr", "More than one PR exists for this phase branch.")
        if existing:
            pr = existing[0]
            if pr.get("baseRefName") != base or marker not in pr.get("body", ""):
                raise RddAdapterError("pr-identity-conflict", "Existing PR has a different base or run/phase marker.")
            if pr.get("state") != "OPEN":
                raise RddAdapterError("closed-phase-pr", "This phase already has a closed or merged PR; do not create another.")
        body_path = Path(body_file).resolve()
        if not body_path.is_file():
            raise RddAdapterError("missing-pr-body", "Write the phase PR body before publishing it.")
        body = body_path.read_text(encoding="utf-8")
        if marker not in body:
            body = f"{marker}\n\n{body}"
        _checked(self.git._git("push", "--set-upstream", remote,
                               f"refs/heads/{branch}:refs/heads/{branch}"), "Push phase branch")
        if not existing:
            fd, temporary = tempfile.mkstemp(prefix="rdd-pr-", suffix=".md")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                    handle.write(body)
                _checked(self._gh("pr", "create", "--head", branch, "--base", base,
                                  "--title", title or f"RDD {run_id}: phase {phase}",
                                  "--body-file", temporary), "Create phase pull request")
            finally:
                Path(temporary).unlink(missing_ok=True)
        # Retry after an uncertain network result finds the existing marker rather than
        # creating a duplicate. The controller holds a run lock around this operation.
        found = self._find(branch)
        if len(found) != 1:
            raise RddAdapterError("ambiguous-pr", "Expected exactly one published phase PR; inspect GitHub before retrying.")
        pr = found[0]
        if (pr.get("baseRefName") != base or pr.get("baseRefOid") != base_sha or pr.get("headRefOid") != head
                or marker not in pr.get("body", "") or pr.get("state") != "OPEN"):
            raise RddAdapterError("pr-mismatch", "Published PR does not match the expected phase, base, and commit.")
        return pr

    def phase_status(self, number: int, expected_head: str, expected_base: str,
                     required_checks: Sequence[str], *, expected_base_sha: str | None = None,
                     expected_head_branch: str | None = None,
                     review_evidence: Mapping[str, Any] | None = None,
                     require_github_approval: bool = False) -> dict[str, Any]:
        """Read readiness at exact head/base, rejecting absent/inconclusive evidence.

        A local review is accepted only as {passed: true, head_sha, reviewer,
        findings: []}; the controller must validate its provenance separately.
        A GitHub CHANGES_REQUESTED decision always vetoes local review evidence.
        """
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise RddAdapterError("invalid-pr-number", "PR number must be a positive integer.")
        _sha(expected_head)
        _ref(expected_base)
        if expected_base_sha is not None:
            _sha(expected_base_sha)
        if expected_head_branch is not None:
            _ref(expected_head_branch)
        if isinstance(required_checks, str) or not required_checks or any(
            not isinstance(name, str) or not name.strip() for name in required_checks
        ):
            raise RddAdapterError("missing-required-checks", "A phase needs an explicit nonempty required-check list.")
        before = _json_output(self._gh("pr", "view", str(number), "--json", self.PR_FIELDS), "Read phase PR")
        required = self._gh("pr", "checks", str(number), "--required", "--json", "name,state,bucket,link")
        server_checks = _json_output(required, "Read required GitHub checks", allow_failure=True)
        after = _json_output(self._gh("pr", "view", str(number), "--json", self.PR_FIELDS), "Confirm phase PR revision")
        if not isinstance(before, dict) or not isinstance(after, dict) or not isinstance(server_checks, list):
            raise RddAdapterError("invalid-pr-evidence", "GitHub returned malformed PR/check evidence.")
        blockers: list[str] = []
        if after.get("number") != number:
            blockers.append("GitHub returned a different or missing PR identity")
        for field in ("headRefOid", "baseRefOid", "baseRefName", "headRefName"):
            if before.get(field) != after.get(field):
                blockers.append(f"PR {field} changed while evidence was collected")
        if after.get("headRefOid") != expected_head:
            blockers.append("PR head differs from the validated phase commit")
        if after.get("baseRefName") != expected_base:
            blockers.append("PR base differs from the planned stack base")
        if expected_head_branch and after.get("headRefName") != expected_head_branch:
            blockers.append("PR head branch differs from the recorded phase branch")
        if expected_base_sha and after.get("baseRefOid") != expected_base_sha:
            blockers.append("PR base commit changed; revalidate the open phase")
        if after.get("state") != "OPEN" or after.get("isDraft") is not False:
            blockers.append("PR must be open and ready for review")
        if after.get("isCrossRepository") is not False:
            blockers.append("Cross-repository or unknown PR head is outside this harness policy")
        if after.get("mergeable") != "MERGEABLE":
            blockers.append("GitHub mergeability is not confirmed")
        if after.get("mergeStateStatus") not in ("CLEAN", "HAS_HOOKS"):
            blockers.append(f"GitHub merge state is {after.get('mergeStateStatus')}")
        if required.returncode != 0:
            blockers.append("The required-check command did not report success")
        for check in server_checks:
            if not isinstance(check, dict) or check.get("bucket") != "pass" or check.get("state") not in ("SUCCESS", "success"):
                blockers.append(f"Required GitHub check did not succeed: {check.get('name', '?') if isinstance(check, dict) else '?'}")
        rollup = after.get("statusCheckRollup")
        if not isinstance(rollup, list) or not rollup:
            blockers.append("No check results are attached to this PR revision")
            rollup = []
        for name in set(required_checks):
            matches = [item for item in rollup if isinstance(item, dict)
                       and (item.get("name") or item.get("context")) == name]
            if not matches:
                blockers.append(f"Required configured check is absent: {name}")
            for check in matches:
                success = (check.get("status") == "COMPLETED" and check.get("conclusion") == "SUCCESS") or check.get("state") == "SUCCESS"
                if not success:
                    blockers.append(f"Required configured check has not succeeded: {name}")
        decision = after.get("reviewDecision")
        latest = after.get("latestReviews") or []
        if not isinstance(latest, list) or any(not isinstance(item, dict) for item in latest):
            blockers.append("GitHub returned inconclusive review evidence")
            latest = []
        review_veto = decision == "CHANGES_REQUESTED" or any(
            isinstance(item, dict) and item.get("state") == "CHANGES_REQUESTED" for item in latest
        )
        if review_veto:
            blockers.append("GitHub review requests changes")
        github_review_ok = decision == "APPROVED" and any(
            isinstance(item, dict) and item.get("state") == "APPROVED"
            and isinstance(item.get("commit"), dict) and item["commit"].get("oid") == expected_head
            for item in latest
        )
        local_review_ok = bool(review_evidence and review_evidence.get("passed") is True
                               and review_evidence.get("head_sha") == expected_head
                               and isinstance(review_evidence.get("reviewer"), str)
                               and review_evidence.get("reviewer")
                               and review_evidence.get("findings") == [])
        if require_github_approval and not github_review_ok:
            blockers.append("A GitHub approval of this exact head is required")
        elif not github_review_ok and not local_review_ok:
            blockers.append("No passing independent review of this exact head is recorded")
        return {"ready": not blockers, "number": number, "url": after.get("url"),
                "head_sha": after.get("headRefOid"), "base_sha": after.get("baseRefOid"),
                "base_branch": after.get("baseRefName"), "blockers": blockers,
                "required_checks": list(required_checks), "server_required_checks": server_checks,
                "review_source": "github" if github_review_ok else "local" if local_review_ok else None}


def validate_structured_output(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any] | None = None,
                               path: str = "$") -> None:
    """Validate the closed JSON Schema subset used by bounded worker outputs.

    Unknown validation keywords fail closed. This is deliberately not advertised
    as a general JSON Schema implementation. The controller may inject its own
    validator into CodexAdapter.exec for a wider schema dialect.
    """
    root = root or schema
    if isinstance(schema, bool):
        if not schema:
            raise RddAdapterError("schema-mismatch", f"{path}: schema rejects this value")
        return
    allowed = {"$schema", "$id", "$defs", "definitions", "$ref", "title", "description", "default", "examples",
               "type", "properties", "required", "additionalProperties", "items", "minItems", "maxItems",
               "uniqueItems", "minLength", "maxLength", "pattern", "minimum", "maximum",
               "exclusiveMinimum", "exclusiveMaximum", "enum", "const", "anyOf", "oneOf", "allOf"}
    unknown = set(schema) - allowed
    if unknown:
        raise RddAdapterError("unsupported-schema", f"{path}: unsupported schema keywords {sorted(unknown)}")
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/"):
            raise RddAdapterError("unsupported-schema", "Only local JSON schema references are allowed.")
        target: Any = root
        try:
            for part in reference[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError) as exc:
            raise RddAdapterError("invalid-schema", f"Unresolved schema reference: {reference}") from exc
        validate_structured_output(value, target, root, path)
    for key in ("allOf", "anyOf", "oneOf"):
        if key not in schema:
            continue
        matches = 0
        for child in schema[key]:
            try:
                validate_structured_output(value, child, root, path)
                matches += 1
            except RddAdapterError as exc:
                if exc.code != "schema-mismatch":
                    raise
        if (key == "allOf" and matches != len(schema[key])) or (key == "anyOf" and matches == 0) or (key == "oneOf" and matches != 1):
            raise RddAdapterError("schema-mismatch", f"{path}: does not satisfy {key}")
    def fail(message: str) -> None:
        raise RddAdapterError("schema-mismatch", f"{path}: {message}")
    checks = {"null": value is None, "boolean": isinstance(value, bool),
              "integer": isinstance(value, int) and not isinstance(value, bool),
              "number": isinstance(value, (int, float)) and not isinstance(value, bool),
              "string": isinstance(value, str), "array": isinstance(value, list), "object": isinstance(value, dict)}
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if any(kind not in checks for kind in kinds):
            raise RddAdapterError("invalid-schema", f"{path}: unknown type")
        if not any(checks[kind] for kind in kinds):
            fail(f"expected {kinds}")
    if "enum" in schema and not any(type(value) is type(item) and value == item for item in schema["enum"]):
        fail("value is outside enum")
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        fail("value differs from const")
    if isinstance(value, dict):
        for field in schema.get("required", []):
            if field not in value:
                fail(f"missing required field {field}")
        properties = schema.get("properties", {})
        for field, item in value.items():
            if field in properties:
                validate_structured_output(item, properties[field], root, f"{path}.{field}")
            elif schema.get("additionalProperties") is False:
                fail(f"unexpected field {field}")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate_structured_output(item, schema["additionalProperties"], root, f"{path}.{field}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            fail("array length is out of bounds")
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            fail("array elements are not unique")
        for i, item in enumerate(value):
            if "items" in schema:
                validate_structured_output(item, schema["items"], root, f"{path}[{i}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", math.inf):
            fail("string length is out of bounds")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            fail("string does not match pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            fail("number must be finite")
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            fail("number is out of bounds")
        if value <= schema.get("exclusiveMinimum", -math.inf) or value >= schema.get("exclusiveMaximum", math.inf):
            fail("number is outside exclusive bounds")


def codex_config_string(value: str) -> str:
    """Encode one TOML basic-string CLI value without shell interpretation."""
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


class CodexAdapter:
    def __init__(self, repo: str | Path, binary: str = "codex", runner: Callable[..., CommandResult] = run_argv):
        self.repo = Path(repo).resolve()
        self.binary = binary
        self.runner = runner

    def doctor(self, models: Sequence[tuple[str, str]], *, refresh_catalog: bool = False,
               roles: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
        """Read client capabilities and authentication; never execute a model turn."""
        report: dict[str, Any] = {"ready": False, "blockers": [], "models": [], "catalog_scope": "refreshed" if refresh_catalog else "bundled"}
        try:
            if not models:
                raise RddAdapterError("missing-model-policy", "Doctor requires the explicit profile model/effort inventory.")
            version = _checked(self.runner([self.binary, "--version"], cwd=self.repo, timeout=15), "Read Codex version")
            report["version"] = version.stdout.strip()
            help_result = _checked(self.runner([self.binary, "exec", "--help"], cwd=self.repo, timeout=15), "Read Codex exec flags")
            for flag in ("--json", "--config", "--output-schema", "--output-last-message"):
                if flag not in help_result.stdout:
                    report["blockers"].append(f"Installed Codex lacks {flag}")
            args = [self.binary, "debug", "models"] + ([] if refresh_catalog else ["--bundled"])
            catalog = _json_output(self.runner(args, cwd=self.repo, timeout=45), "Read Codex model catalog")
            rows = catalog.get("models", []) if isinstance(catalog, dict) else catalog
            if not isinstance(rows, list):
                raise RddAdapterError("invalid-model-catalog", "Codex did not return a model list.")
            by_name = {item.get("slug", item.get("id")): item for item in rows if isinstance(item, dict)}
            for model, effort in dict.fromkeys(models):
                info = by_name.get(model, {})
                supported = [level.get("effort") if isinstance(level, dict) else level for level in info.get("supported_reasoning_levels", [])]
                ok = effort in supported
                assigned = sorted(role for role, settings in (roles or {}).items()
                                  if (settings["model"], settings["effort"]) == (model, effort))
                report["models"].append({"model": model, "effort": effort, "client_advertises": ok, "roles": assigned})
                if not ok:
                    affected = f" for {', '.join(assigned)}" if assigned else ""
                    report["blockers"].append(f"Client catalog does not advertise {model} with {effort}{affected}; configure an explicit supported choice")
            login = self.runner([self.binary, "login", "status"], cwd=self.repo, timeout=15)
            report["authenticated"] = login.returncode == 0 and not login.timed_out
            if not report["authenticated"]:
                report["blockers"].append("Codex authentication is unavailable; run codex login locally")
            report["account_access_verified"] = False
            report["account_access_note"] = "Catalog and login checks do not prove model entitlement; the first actual turn may report an access blocker. No fallback is automatic."
        except RddAdapterError as exc:
            report["blockers"].append(f"{exc.code}: {exc}")
        report["ready"] = not report["blockers"]
        return report

    def exec(self, prompt: str, schema_path: str | Path, run_dir: str | Path,
             role: str, *, timeout: float = 1800, sandbox: str | None = None,
             validator: Callable[[Any, Mapping[str, Any]], None] = validate_structured_output) -> dict[str, Any]:
        """Run one bounded worker turn, saving JSONL, stderr, output, and receipt.

        The App Server workflow runner owns persistent coordination and native
        Goals; this adapter serves optional bounded workers only.
        The caller supplies a fresh run_dir under the repository's runtime path.
        """
        if not isinstance(prompt, str) or not prompt.strip():
            raise RddAdapterError("empty-prompt", "A worker prompt must contain a concrete target.")
        try:
            profiles = load_profiles(self.repo)
            if role not in profiles:
                raise RddError(f"Unknown RDD role: {role}", "environment")
            profile = profiles[role]
            requested = {"role": role, "profile_path": profile["path"], "profile_hash": profile["hash"],
                         "model": profile["model"], "effort": profile["effort"], "sandbox": profile["sandbox"]}
        except RddError as exc:
            raise RddAdapterError("invalid-profile", str(exc)) from exc
        model, effort = profile["model"], profile["effort"]
        if sandbox is None:
            sandbox = profile["sandbox"]
        if sandbox not in ("read-only", "workspace-write") or (profile["sandbox"] == "read-only" and sandbox != "read-only"):
            raise RddAdapterError("invalid-sandbox", "A runtime override may restrict a profile to read-only, never expand its permissions.")
        requested["sandbox"] = sandbox
        schema_file = Path(schema_path).resolve()
        try:
            schema = _strict_json(schema_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RddAdapterError("invalid-schema", "The worker output schema is missing or invalid JSON.") from exc
        if not isinstance(schema, dict):
            raise RddAdapterError("invalid-schema", "The worker output schema must be a JSON object.")
        directory = Path(run_dir).absolute()
        if directory.is_symlink():
            raise RddAdapterError("unsafe-runtime-path", "Worker run directory must not be a symlink.")
        directory = directory.resolve()
        try:
            directory.relative_to(self.repo / ".rdd" / "runtime")
        except ValueError as exc:
            raise RddAdapterError("unsafe-runtime-path", "Worker receipts belong in .rdd/runtime under this repository.") from exc
        if directory.exists() and any(directory.iterdir()):
            raise RddAdapterError("reused-worker-directory", "Use a fresh worker attempt directory to prevent stale success evidence.")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
        snapshot = directory / "output.schema.json"
        snapshot.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        answer_path = directory / "answer.json"
        events: dict[str, Any] = {"session_id": None, "turn_completed": False, "stream_errors": []}

        def observe(line: str) -> None:
            try:
                event = _strict_json(line)
            except ValueError:
                events["stream_errors"].append("invalid JSONL event")
                return
            if not isinstance(event, dict):
                events["stream_errors"].append("non-object JSONL event")
                return
            kind = event.get("type")
            if kind == "thread.started":
                events["session_id"] = event.get("thread_id")
            if kind == "turn.completed":
                events["turn_completed"] = True
            if kind in ("error", "turn.failed"):
                events["stream_errors"].append(str(event.get("message") or event.get("error") or kind)[:1000])

        argv = [self.binary, "-a", "never", "exec", "--json", "--color", "never",
                "--model", model, "--config", f'model_reasoning_effort="{effort}"',
                "--config", "developer_instructions=" + codex_config_string(profile["developer_instructions"]),
                "--sandbox", sandbox, "--cd", str(self.repo),
                "--output-schema", str(snapshot), "--output-last-message", str(answer_path), "-"]
        receipt: dict[str, Any] = {"requested_runtime": requested, "status": "failed",
                                   "argv": argv, "session_id": None}
        try:
            result = self.runner(argv, cwd=self.repo, timeout=timeout, input_text=prompt,
                                 stdout_path=directory / "events.jsonl", stderr_path=directory / "stderr.log",
                                 on_stdout_line=observe)
            receipt.update({"returncode": result.returncode, "timed_out": result.timed_out,
                            "duration_seconds": result.duration_seconds, **events})
            if result.timed_out or result.returncode != 0:
                raise RddAdapterError("codex-failed", "Codex worker failed or timed out; inspect its persisted logs.")
            if not events["session_id"] or not events["turn_completed"] or events["stream_errors"]:
                raise RddAdapterError("incomplete-codex-stream", "Worker JSONL lacks an unambiguous completed turn and session identity.")
            if answer_path.is_symlink() or not answer_path.is_file():
                raise RddAdapterError("missing-worker-answer", "Codex did not write a final structured answer.")
            try:
                answer = _strict_json(answer_path.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise RddAdapterError("invalid-worker-answer", "Codex final answer is not valid JSON.") from exc
            validator(answer, schema)
            receipt["status"] = "completed"
            return {"answer": answer, "session_id": events["session_id"], "run_dir": str(directory),
                    "requested_runtime": requested, "receipt": receipt}
        except RddAdapterError as exc:
            receipt.update({"error_code": exc.code, "error": str(exc), **events})
            raise
        finally:
            (directory / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
