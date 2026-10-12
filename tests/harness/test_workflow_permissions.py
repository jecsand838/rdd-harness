"""Per-launch permission choices preserve controller guards and profile authority."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

from rdd import cli
from rdd.common import RddError
from rdd.engine import Controller
from rdd.profiles import profile_policy_digest, profile_settings


STAGES = ("specification", "preparation", "implementation")


class WorkflowPermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rdd-workflow-permissions-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        shutil.copytree(REPO / ".codex", self.root / ".codex")
        (self.root / ".rdd").mkdir()
        shutil.copyfile(REPO / ".rdd/config.json", self.root / ".rdd/config.json")
        shutil.copytree(REPO / ".rdd/goals", self.root / ".rdd/goals")
        self.c = Controller(self.root)
        self.addCleanup(self.c.close)

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()
                and ".git" not in path.relative_to(self.root).parts}

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(REPO / "tools/rdd/cli.py"),
                               "--root", str(self.root), *args],
                              capture_output=True, text=True, timeout=15)

    def packet(self, stage, permission=None):
        args = cli.parser().parse_args(["workflow", stage, "--print"])
        # Exercise dispatch independently of parser support, including the pre-feature launcher.
        args.permission = permission
        with patch.object(self.c, "frozen", return_value=({}, {})), \
                patch.object(self.c, "state", return_value={"status": "prepared"}):
            return cli.dispatch(self.c, args)

    def test_dispatch_explicit_full_access_for_all_launch_stages(self):
        canonical = profile_settings(self.root, "rdd_coordinator")
        before = self.snapshot()
        policy = profile_policy_digest(self.root)
        for stage in STAGES:
            with self.subTest(stage=stage):
                packet = self.packet(stage, "full-access")
                self.assertEqual(packet["argv"][packet["argv"].index("--sandbox") + 1],
                                 "danger-full-access")
                self.assertEqual(packet["argv"][packet["argv"].index("--ask-for-approval") + 1], "never")
                self.assertEqual(packet["requested_runtime"],
                                 {**canonical, "sandbox": "danger-full-access", "approval_policy": "never"})
                self.assertEqual(packet["argv"][-2:], ["--", packet["prompt"]])
                self.assertEqual(packet["native_goal"], self.c.goal() if stage == "implementation" else None)
        self.assertEqual(profile_policy_digest(self.root), policy)
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(self.c._store)

    def test_dispatch_default_preserves_profile_packet_and_launch_arguments(self):
        canonical = profile_settings(self.root, "rdd_coordinator")
        for stage in STAGES:
            with self.subTest(stage=stage):
                packet = self.packet(stage)
                self.assertEqual(packet["requested_runtime"], canonical)
                self.assertEqual(packet["argv"][packet["argv"].index("--sandbox") + 1], canonical["sandbox"])
                self.assertNotIn("--ask-for-approval", packet["argv"])

    def test_parser_accepts_only_explicit_full_access_for_all_launch_stages(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                args = cli.parser().parse_args(["workflow", stage, "--permission=full-access", "--print"])
                self.assertEqual(args.permission, "full-access")
                self.assertTrue(args.print_only)
                self.assertIsNone(cli.parser().parse_args(["workflow", stage, "--print"]).permission)

    def test_cli_print_uses_full_access_without_starting_a_run_or_process(self):
        before = self.snapshot()
        result = self.run_cli("workflow", "specification", "--permission=full-access", "--print")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["requested_runtime"]["sandbox"], "danger-full-access")
        self.assertEqual(packet["requested_runtime"]["approval_policy"], "never")
        self.assertIsNone(packet["native_goal"])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / ".rdd/runtime").exists())

    def test_cli_invalid_or_irrelevant_permissions_fail_before_runtime_mutation(self):
        before = self.snapshot()
        commands = [("workflow", "specification", "--permission=" + value,
                     "--mode", "regenerate", "--print")
                    for value in ("", "workspace-write", "danger-full-access", "read-only", "default")]
        commands += [("workflow", action, "--permission=full-access", "--mode", "regenerate")
                     for action in ("nodes", "next", "claim", "record", "release")]
        commands.append(("goal", "--permission=full-access"))
        for command in commands:
            with self.subTest(command=command):
                result = self.run_cli(*command)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("--permission", result.stderr)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.root / ".rdd/runtime").exists())

    def test_irrelevant_option_is_rejected_before_controller_construction(self):
        with patch.object(cli, "Controller") as controller, \
                patch.object(cli, "require_source_branch") as branch, \
                patch.object(cli, "operation_lock") as lock, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--root", str(self.root), "workflow", "claim", "S0",
                          "--permission=full-access", "--mode", "regenerate"])
        self.assertEqual(caught.exception.code, 2)
        controller.assert_not_called()
        branch.assert_not_called()
        lock.assert_not_called()

    def test_direct_invalid_permission_precedes_guards_and_explicit_run_start(self):
        before = self.snapshot()
        for permission in ("", "workspace-write", "danger-full-access", "read-only", True, 42, []):
            with self.subTest(permission=permission), \
                    patch.object(self.c, "guard_workflow") as guard, \
                    patch.object(self.c, "start") as start:
                with self.assertRaisesRegex(RddError, "permission") as caught:
                    self.c.workflow("specification", "regenerate", print_only=True, permission=permission)
                self.assertEqual(caught.exception.kind, "validation")
                guard.assert_not_called()
                start.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(self.c._store)

    def test_full_access_cannot_bypass_main_branch_guard(self):
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)], check=True)
        before = self.snapshot()
        for stage in STAGES:
            with self.subTest(stage=stage):
                result = self.run_cli("workflow", stage, "--permission=full-access")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["kind"], "environment")
                with self.assertRaises(RddError) as caught:
                    self.c.workflow(stage, permission="full-access")
                self.assertEqual(caught.exception.kind, "environment")
                self.assertEqual(self.snapshot(), before)
                self.assertIsNone(self.c._store)

    def test_full_access_retains_frozen_contract_and_preparation_checks(self):
        before = self.snapshot()
        for stage in ("preparation", "implementation"):
            with self.subTest(stage=stage), patch.object(self.c, "frozen", side_effect=RddError("Frozen contract drift", "specification")):
                with self.assertRaisesRegex(RddError, "Frozen contract drift"):
                    self.c.workflow(stage, print_only=True, permission="full-access")
        with patch.object(self.c, "frozen", return_value=({}, {})), \
                patch.object(self.c, "state", return_value={"status": "preparing"}):
            with self.assertRaisesRegex(RddError, "completed preparation"):
                self.c.workflow("implementation", print_only=True, permission="full-access")
        self.assertEqual(self.snapshot(), before)

    def test_interactive_cli_passes_effective_arguments_to_subprocess(self):
        for stage in STAGES:
            for permission in (None, "full-access"):
                with self.subTest(stage=stage, permission=permission), \
                        patch.object(cli, "Controller", return_value=self.c), \
                        patch.object(cli, "require_source_branch"), \
                        patch.object(cli, "operation_lock", return_value=contextlib.nullcontext()), \
                        patch.object(self.c, "guard_workflow"), \
                        patch.object(self.c, "frozen", return_value=({}, {})), \
                        patch.object(self.c, "state", return_value={"status": "prepared"}), \
                        patch.object(cli.shutil, "which", return_value="codex"), \
                        patch.object(cli.sys.stdin, "isatty", return_value=True), \
                        patch.object(cli.subprocess, "call", return_value=17) as launch, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    args = ["--root", str(self.root), "workflow", stage]
                    if permission:
                        args.append("--permission=" + permission)
                    self.assertEqual(cli.main(args), 17)
                    argv = launch.call_args.args[0]
                    self.assertEqual(launch.call_args.kwargs, {"cwd": self.root})
                    self.assertEqual(argv[argv.index("--sandbox") + 1],
                                     "danger-full-access" if permission else "workspace-write")
                    if permission:
                        self.assertEqual(argv[argv.index("--ask-for-approval") + 1], "never")
                    else:
                        self.assertNotIn("--ask-for-approval", argv)
                    if stage == "implementation":
                        self.assertIn("/goal", output.getvalue())
                    self.assertNotIn("/goal", argv)


if __name__ == "__main__":
    unittest.main()
