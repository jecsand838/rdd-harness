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
from rdd.common import RddError, RddStorageError, operation_lock, require_source_branch
from rdd.engine import Controller
from rdd.profiles import IMPLEMENTOR_ROLES, WORKFLOW_AUTHOR_ROLES, profile_policy_digest


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
    readiness = commands.add_parser("readiness", help="Execute exact-candidate preimplementation qualification")
    readiness.add_argument("stage", choices=("specification", "plan", "preparation"))
    author = commands.add_parser("author")
    author.add_argument("action", choices=("record",))
    author.add_argument("--stage", required=True, choices=("specification", "plan", "preparation"))
    author.add_argument("--session-id", required=True)
    commands.add_parser("next", help="List tasks eligible in the current phase and category")
    ph = commands.add_parser("phase")
    ph.add_argument("action", choices=("begin", "seal"))
    ph.add_argument("phase")
    tasks = commands.add_parser("task").add_subparsers(dest="action", required=True)
    claim = tasks.add_parser("claim")
    claim.add_argument("task")
    claim.add_argument("--worker", choices=IMPLEMENTOR_ROLES, required=True)
    claim.add_argument("--session-id", help="Required actual implementor session ID; never reuse the reviewer ID")
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
    g.add_argument("level", choices=("preparation", "phase", "project"))
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
    for field in ("requirement", "element", "task", "evidence"):
        block.add_argument("--" + field, action="append", default=[])
    commands.add_parser("goal", help="Print only the native /goal objective, guaranteed below 4,000 characters")
    wf = commands.add_parser("workflow", help="Open an interactive Codex workflow, or print its launch packet")
    wf.add_argument("stage", choices=("specification", "preparation", "implementation", "nodes", "next", "claim", "record", "release"))
    wf.add_argument("target", nargs="?")
    wf.add_argument("--session-id")
    wf.add_argument("--role", choices=WORKFLOW_AUTHOR_ROLES)
    wf.add_argument("--write", action="append", default=[])
    wf.add_argument("--reason")
    wf.add_argument("--finding", help="Unresolved live finding authorizing a scoped corrective retry")
    wf.add_argument("--mode", choices=("amend", "regenerate"))
    wf.add_argument("--permission", choices=("full-access",),
                    help="Use --permission full-access for an unrestricted sandbox and no approval prompts (launch stages only)")
    wf.add_argument("--print", action="store_true", dest="print_only", help="Show the launch packet; does not start Codex (an explicit --mode starts the requested run)")
    contract = commands.add_parser("contracts")
    contract.add_argument("action", choices=("check", "generate"))
    contract.add_argument("--bootstrap-lock", action="store_true", help="First qualification only: resolve missing Cargo.lock files")
    contract.add_argument("--target", action="append", default=[])
    contract.add_argument("--against", help="Buf breaking-check baseline input")
    commands.add_parser("selftest", help="Manually run the Rust generator unit tests; never runs in CI or claims app completion")
    ci = commands.add_parser("ci", help="Stateless trusted-baseline verification of a candidate checkout")
    ci.add_argument("--policy-root", type=Path)
    ci.add_argument("--branch")
    ci.add_argument("--preparation", action="store_true", help="Qualify a materialized v2 baseline against a separately pinned harness")
    ci.add_argument("--harness-source", help="Exact operator-selected trusted harness commit; required with --preparation")
    ci.add_argument("--release-policy", help="Exact operator-approved prepared policy commit (requires --release-source)")
    ci.add_argument("--release-source", help="Exact project-accepted release commit (requires --release-policy)")
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
    if cmd == "readiness":
        return c.readiness(a.stage)
    if cmd == "author":
        return c.author_record(a.stage, a.session_id)
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
        if a.level == "preparation":
            if a.phase:
                raise RddError("gate preparation takes no phase ID")
            return c.gate_preparation()
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
        return c.block(a.kind, a.reason, affected={"requirements": a.requirement, "elements": a.element, "tasks": a.task}, evidence=a.evidence)
    if cmd == "goal":
        return c.goal()
    if cmd == "workflow":
        if a.stage == "nodes":
            return c.workflow_nodes()
        if a.stage == "next":
            return c.workflow_next()
        if a.stage == "claim":
            if not a.target or not a.session_id or not a.role:
                raise RddError("workflow claim needs NODE, --session-id, --role and exact --write paths")
            return c.workflow_claim(a.target, a.session_id, a.role, a.write, a.finding)
        if a.stage == "record":
            if not a.target:
                raise RddError("workflow record needs an output record JSON file")
            return c.workflow_record(Path(a.target))
        if a.stage == "release":
            if not a.target or not a.reason:
                raise RddError("workflow release needs NODE and --reason")
            return c.workflow_release(a.target, a.reason)
        return c.workflow(a.stage, a.mode, print_only=a.print_only, permission=a.permission)
    if cmd == "contracts":
        from rdd.proto_traits import run_contracts, ContractCheckError
        if a.action == "generate":
            c.guard_source_write(baseline=True)
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
        cargo = shutil.which("cargo")
        if not cargo:
            raise RddError("Cargo is required for manual generator selftests", "environment")
        result = subprocess.run([cargo, "test", "--locked", "--manifest-path",
                                 str(c.root / "tools/proto-codegen/Cargo.toml")], cwd=c.root)
        return {"status": "passed" if result.returncode == 0 else "failed", "scope": "generator_unit_tests",
                "application_complete": False, "returncode": result.returncode}
    if cmd == "ci":
        from rdd.ci import verify, verify_preparation
        if a.preparation:
            if a.release_policy or a.release_source or not a.policy_root or not a.harness_source:
                raise RddError("Preparation CI requires separate --policy-root and --harness-source, without release flags")
            return verify_preparation(c.root, a.policy_root, a.harness_source)
        if a.harness_source:
            raise RddError("--harness-source requires --preparation")
        return verify(c.root, a.policy_root, a.branch,
                      release_policy=a.release_policy, release_source=a.release_source)
    raise RddError("Unhandled command")


def workflow_display(value):
    """Keep CLI handoffs bounded; full claim inventories remain in run exports."""
    if isinstance(value, list):
        return [workflow_display(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == "claim" and isinstance(item, dict) and isinstance(item.get("sources"), dict):
            item = {**{k: v for k, v in item.items() if k != "sources"},
                    "source_file_count": len(item["sources"])}
        result[key] = workflow_display(item)
    return result


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    arg_parser = parser()
    args = arg_parser.parse_args(argv)
    if args.command == "workflow" and args.permission is not None and args.stage not in {
            "specification", "preparation", "implementation"}:
        arg_parser.error("--permission is only valid for workflow specification, preparation, or implementation")
    if sys.version_info < (3, 11):
        print(json.dumps({"status": "blocked", "kind": "environment", "error": "Python 3.11+ is required"}))
        return 2
    controller = None
    try:
        source_write = args.command in {"start", "prepare", "resume", "phase"} or (
            args.command in {"spec", "plan"} and args.action in {"init", "freeze"}) or (
            args.command == "contracts" and args.action == "generate") or (
            args.command == "anchors" and args.action == "reconcile") or (
            args.command == "task" and args.action in {"claim", "integrate", "complete", "reopen"}) or (
            args.command == "workflow" and args.stage not in {"nodes", "next"} and (not args.print_only or args.mode is not None))
        if source_write:
            # Refuse before constructing runtime state or acquiring a write lock.
            require_source_branch(args.root)
        controller = Controller(args.root)
        legacy_readonly = args.command in {"status", "doctor", "requirements", "export-run", "selftest"} or (
            args.command == "workflow" and ((args.print_only and args.mode is None) or args.stage == "nodes"))
        if not legacy_readonly:
            controller.guard_v2()
        if args.command == "workflow" and args.stage in {"specification", "preparation", "implementation"}:
            controller.guard_workflow(args.stage, args.mode, print_only=args.print_only)
        elif args.command == "resume":
            controller.guard_resume(args.file)
        elif args.command == "export-run":
            controller.guard_export(args.file)
        elif source_write and args.command != "start":
            controller.guard_source_write(baseline=args.command in {"spec", "plan", "prepare", "contracts"})
        readonly = args.command in {"status", "doctor", "requirements", "next", "goal", "selftest", "ci"} or (
            args.command in {"spec", "plan", "anchors"} and args.action in {"validate", "verify"}) or (
            args.command == "workflow" and ((args.print_only and args.mode is None) or args.stage in {"nodes", "next"}))
        if args.command in {"start", "init"}:
            profile_policy_digest(controller.root)
            if args.command == "init":
                controller.guard_run_policy()
        elif not readonly and args.command != "export-run" and not (
                args.command == "workflow" and args.stage in {"specification", "preparation", "implementation"}):
            controller.guard_run_policy()
        with contextlib.nullcontext() if readonly else operation_lock(controller.root):
            result = dispatch(controller, args)
        if args.command == "goal":
            print(result)
            return 0
        if args.command == "workflow" and args.stage in {"specification", "preparation", "implementation"} and not args.print_only:
            if not shutil.which("codex"):
                raise RddError("codex is not on PATH. Install/authenticate the Codex CLI; use workflow --print to inspect the launch packet.", "environment")
            if not sys.stdin.isatty():
                raise RddError("Interactive Codex needs a terminal; use workflow --print to inspect the prompt and invoke it in your terminal.", "environment")
            if result["native_goal"]:
                print("After Codex opens, activate native goal mode with /goal and the output of ./rdd goal.\n")
            return subprocess.call(result["argv"], cwd=controller.root)
        displayed = workflow_display(result) if args.command == "status" or (
            args.command == "workflow" and args.stage in {"nodes", "claim"}) else result
        print(json.dumps(displayed, indent=2, ensure_ascii=False))
        if isinstance(result, dict):
            if result.get("outcome") == "fail" or result.get("status") == "failed":
                return 1
            if result.get("status") == "blocked" or result.get("ready") is False:
                return 2
        return 0
    except (RddError, RddAdapterError) as exc:
        kind = getattr(exc, "kind", getattr(exc, "code", "environment"))
        storage_error = exc if isinstance(exc, RddStorageError) else getattr(exc, "rdd_storage_error", None)
        # Frozen authority/phase drift cannot be silently repaired by an implementation agent.
        if not storage_error and controller and kind in {"specification", "planning", "closure"}:
            try:
                state = controller.state(allow_blocked=True)
                if state["status"] in {"specified", "planned", "preparing", "prepared", "implementation", "complete"} and (
                        kind != "planning" or state.get("plan_digest")):
                    controller.block(kind, str(exc))
            except (RddError, OSError) as blocker_error:
                storage_error = (blocker_error if isinstance(blocker_error, RddStorageError)
                                 else getattr(blocker_error, "rdd_storage_error", None))
        detail = str(exc)
        if storage_error:
            kind = "environment"
            if storage_error is not exc:
                detail += "; " + str(storage_error)
        print(json.dumps({"status": "blocked" if kind != "validation" else "failed", "kind": kind, "error": detail}, ensure_ascii=False))
        return 1 if kind == "validation" else 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        detail = str(exc)
        if getattr(exc, "rdd_storage_error", None) is not None:
            detail += "; " + str(exc.rdd_storage_error)
        print(json.dumps({"status": "blocked", "kind": "environment", "error": detail}, ensure_ascii=False))
        return 2
    finally:
        if controller:
            controller.close()


if __name__ == "__main__":
    raise SystemExit(main())
