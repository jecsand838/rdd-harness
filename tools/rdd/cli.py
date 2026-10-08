"""Portable command-line entry point. See ./rdd --help and docs/harness/."""
from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdd.adapters import RddAdapterError
from rdd.common import RddError, operation_lock
from rdd.engine import Controller


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Requirements Driven Development: frozen artifacts, ordered tasks, phase gates and evidence.")
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2], help="Repository to operate on (default: this checkout)")
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize local Git/run directories without altering requirements")
    d = commands.add_parser("doctor", help="Report prerequisites without installing or logging in")
    d.add_argument("--full", action="store_true")
    s = commands.add_parser("start", help="Start an amend/regenerate run; preserve historical artifacts")
    s.add_argument("--mode", choices=("amend", "regenerate"), required=True)
    s.add_argument("--run-id")
    commands.add_parser("status", help="Read authoritative run state and exact source identity")
    r = commands.add_parser("requirements")
    r.add_argument("action", choices=("index",))
    for name in ("spec", "plan"):
        sub = commands.add_parser(name)
        sub.add_argument("action", choices=("init", "validate", "freeze"))
    commands.add_parser("prepare", help="Materialize only frozen shells, anchors and implementation matrix")
    commands.add_parser("next", help="List tasks eligible in the current phase and category")
    ph = commands.add_parser("phase")
    ph.add_argument("action", choices=("begin", "seal"))
    ph.add_argument("phase")
    tasks = commands.add_parser("task").add_subparsers(dest="action", required=True)
    claim = tasks.add_parser("claim")
    claim.add_argument("task")
    claim.add_argument("--worker", choices=("rdd_large", "rdd_small"), required=True)
    claim.add_argument("--session-id", help="Actual native agent/session ID when known; never reuse the reviewer ID")
    worktree = claim.add_mutually_exclusive_group()
    worktree.add_argument("--worktree", action="store_true", default=True, help="Create an isolated worktree (default)")
    worktree.add_argument("--no-worktree", action="store_false", dest="worktree", help="Advanced: caller supplies a separate branch/worktree; shared phase edits are rejected")
    integrate = tasks.add_parser("integrate")
    integrate.add_argument("task")
    integrate.add_argument("--commit", required=True)
    complete = tasks.add_parser("complete")
    complete.add_argument("task")
    complete.add_argument("--evidence")
    for name in ("release", "reopen"):
        sub = tasks.add_parser(name)
        sub.add_argument("task")
        sub.add_argument("--reason", required=True)
    ck = commands.add_parser("check", help="Execute a frozen check, or import an external receipt with its staged raw log")
    ck.add_argument("check_or_import")
    ck.add_argument("file", nargs="?", type=Path)
    ck.add_argument("--expect", choices=("pass", "fail"), default="pass")
    ck.add_argument("--task")
    ck.add_argument("--local-host", action="store_true", help="Import actual controller evidence transferred from a trusted native/reference host")
    a = commands.add_parser("anchors")
    a.add_argument("action", choices=("reconcile", "verify"))
    r = commands.add_parser("review")
    r.add_argument("action", choices=("record",))
    r.add_argument("file", type=Path)
    g = commands.add_parser("gate")
    g.add_argument("level", choices=("phase", "project"))
    g.add_argument("phase", nargs="?")
    stack = commands.add_parser("stack")
    stack.add_argument("action", choices=("publish", "verify"))
    stack.add_argument("phase", nargs="?")
    re = commands.add_parser("resume")
    re.add_argument("--from", dest="file", type=Path)
    export = commands.add_parser("export-run")
    export.add_argument("file", type=Path)
    block = commands.add_parser("block")
    block.add_argument("--kind", choices=("specification", "planning", "closure", "environment", "authorization", "budget", "review"), required=True)
    block.add_argument("--reason", required=True)
    commands.add_parser("goal", help="Print only the native /goal objective, guaranteed below 4,000 characters")
    wf = commands.add_parser("workflow", help="Open an interactive Codex workflow, or print its launch packet")
    wf.add_argument("stage", choices=("specification", "preparation", "implementation"))
    wf.add_argument("--mode", choices=("amend", "regenerate"))
    wf.add_argument("--print", action="store_true", dest="print_only", help="Show the launch packet; does not start Codex (an explicit --mode starts the requested run)")
    contract = commands.add_parser("contracts")
    contract.add_argument("action", choices=("check", "generate"))
    contract.add_argument("--bootstrap-lock", action="store_true", help="First qualification only: resolve missing Cargo.lock files")
    contract.add_argument("--target", action="append", default=[])
    contract.add_argument("--against", help="Buf breaking-check baseline input")
    commands.add_parser("selftest", help="Run the real offline controller/adapters regression suite; never claims app completion")
    ci = commands.add_parser("ci", help="Stateless trusted-baseline verification of a candidate checkout")
    ci.add_argument("--policy-root", type=Path)
    ci.add_argument("--branch")
    return p


def dispatch(c: Controller, a: argparse.Namespace):
    cmd = a.command
    if cmd == "init":
        return c.init()
    if cmd == "doctor":
        return c.doctor(a.full)
    if cmd == "start":
        return c.start(a.mode, a.run_id)
    if cmd == "status":
        return c.status()
    if cmd == "requirements":
        return c.requirements_index()
    if cmd in {"spec", "plan"}:
        return getattr(c, f"{cmd}_{a.action}")()
    if cmd == "prepare":
        return c.prepare()
    if cmd == "next":
        return c.next()
    if cmd == "phase":
        return getattr(c, "phase_" + a.action)(a.phase)
    if cmd == "task":
        if a.action == "claim":
            return c.task_claim(a.task, a.worker, a.worktree, a.session_id)
        if a.action == "integrate":
            return c.task_integrate(a.task, a.commit)
        if a.action == "complete":
            return c.task_complete(a.task, a.evidence)
        return getattr(c, "task_" + a.action)(a.task, a.reason)
    if cmd == "check":
        if a.check_or_import == "import":
            if not a.file:
                raise RddError("check import requires a receipt JSON file; stage its referenced log first")
            return c.check_import(a.file, a.local_host)
        if a.file:
            raise RddError("Unexpected check argument; executable inputs are frozen in the spec")
        if a.local_host:
            raise RddError("--local-host belongs to check import; local execution records its own provenance")
        return c.check(a.check_or_import, a.expect, a.task)
    if cmd == "anchors":
        return getattr(c, "anchors_" + a.action)()
    if cmd == "review":
        return c.review_record(a.file)
    if cmd == "gate":
        if a.level == "phase":
            if not a.phase:
                raise RddError("gate phase requires a phase ID")
            return c.gate_phase(a.phase)
        if a.phase:
            raise RddError("gate project takes no phase ID")
        return c.gate_project()
    if cmd == "stack":
        if a.action == "publish":
            if not a.phase:
                raise RddError("stack publish requires a phase ID")
            return c.stack_publish(a.phase)
        if a.phase:
            raise RddError("stack verify takes no phase ID")
        return c.stack_verify()
    if cmd == "resume":
        return c.resume(a.file)
    if cmd == "export-run":
        return c.export_run(a.file)
    if cmd == "block":
        return c.block(a.kind, a.reason)
    if cmd == "goal":
        return c.goal()
    if cmd == "workflow":
        return c.workflow(a.stage, a.mode)
    if cmd == "contracts":
        from rdd.proto_traits import run_contracts, ContractCheckError
        if a.action == "generate":
            state = c.state()
            if state["status"] != "specification":
                raise RddError("Generated contracts are writable only during specification; downstream drift is a blocker", "specification")
        elif a.bootstrap_lock:
            raise RddError("--bootstrap-lock belongs to contracts generate")
        try:
            return run_contracts(c.root, write=a.action == "generate", bootstrap_lock=a.bootstrap_lock,
                                 targets=tuple(a.target), against=a.against)
        except ContractCheckError as exc:
            raise RddError(str(exc), "environment" if exc.blocked else "specification") from exc
    if cmd == "selftest":
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(c.root / "tests/harness"),
                                 "-p", "test_*.py", "-v"], cwd=c.root)
        return {"status": "passed" if result.returncode == 0 else "failed", "scope": "harness_regression",
                "application_complete": False, "returncode": result.returncode}
    if cmd == "ci":
        from rdd.ci import verify
        return verify(c.root, a.policy_root, a.branch)
    raise RddError("Unhandled command")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if sys.version_info < (3, 11):
        print(json.dumps({"status": "blocked", "kind": "environment", "error": "Python 3.11+ is required"}))
        return 2
    controller = None
    try:
        controller = Controller(args.root)
        readonly = args.command in {"status", "doctor", "requirements", "next", "goal", "selftest", "ci"} or (
            args.command in {"spec", "plan", "anchors"} and args.action in {"validate", "verify"})
        with contextlib.nullcontext() if readonly else operation_lock(controller.root):
            result = dispatch(controller, args)
        if args.command == "goal":
            print(result)
            return 0
        if args.command == "workflow" and not args.print_only:
            if not shutil.which("codex"):
                raise RddError("codex is not on PATH. Install/authenticate the Codex CLI; use workflow --print to inspect the launch packet.", "environment")
            if not sys.stdin.isatty():
                raise RddError("Interactive Codex needs a terminal; use workflow --print to inspect the prompt and invoke it in your terminal.", "environment")
            if result["native_goal"]:
                print("After Codex opens, activate native goal mode with /goal and the output of ./rdd goal.\n")
            return subprocess.call(result["argv"], cwd=controller.root)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if isinstance(result, dict):
            if result.get("outcome") == "fail" or result.get("status") == "failed":
                return 1
            if result.get("status") == "blocked" or result.get("ready") is False:
                return 2
        return 0
    except (RddError, RddAdapterError) as exc:
        kind = getattr(exc, "kind", getattr(exc, "code", "environment"))
        # Frozen authority/phase drift cannot be silently repaired by an implementation agent.
        if controller and kind in {"specification", "planning", "closure"}:
            try:
                state = controller.state(allow_blocked=True)
                if state["status"] in {"prepared", "implementation", "complete"}:
                    controller.block(kind, str(exc))
            except (RddError, OSError):
                pass
        print(json.dumps({"status": "blocked" if kind != "validation" else "failed", "kind": kind, "error": str(exc)}, ensure_ascii=False))
        return 1 if kind == "validation" else 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "kind": "environment", "error": str(exc)}, ensure_ascii=False))
        return 2
    finally:
        if controller:
            controller.close()


if __name__ == "__main__":
    raise SystemExit(main())
