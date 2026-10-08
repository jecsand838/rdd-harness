"""Branch rejection preserves source, ignored runtime bytes and dirty user inputs."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_engine as engine_fixture
from tools.rdd.common import RddError, Store, head, read_json, write_json
from tools.rdd.engine import Controller
from tools.rdd.proto_traits import ContractCheckError, run_contracts


class BranchGuardTests(unittest.TestCase):
    def setUp(self):
        self.f = engine_fixture.EngineTests(methodName="runTest")
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.c, self.root = self.f.c, self.f.root

    def snapshot(self):
        state = copy.deepcopy(self.c.state(allow_blocked=True))
        return {
            "files": {p.relative_to(self.root).as_posix(): p.read_bytes()
                      for p in self.root.rglob("*")
                      if p.is_file() and ".git" not in p.relative_to(self.root).parts},
            "state": state,
            "head": head(self.root),
            "branch": self.f.g("branch", "--show-current"),
            "dirty": self.f.g("status", "--porcelain"),
        }

    def rejected(self, operation):
        before = self.snapshot()
        with self.assertRaises(RddError) as caught:
            operation()
        self.assertEqual(caught.exception.kind, "environment")
        self.assertEqual(self.snapshot(), before)

    def cli(self, *args, root=None):
        entry = Path(__file__).resolve().parents[2] / "tools/rdd/cli.py"
        return subprocess.run([sys.executable, "-B", str(entry), "--root", str(root or self.root), *args],
                              capture_output=True, text=True, timeout=30)

    def dirty_input(self):
        path = self.root / "requirements/requirements.md"
        path.write_text(path.read_text() + "\nUser input awaiting a deliberate commit.\n")
        (self.root / "user-note.txt").write_text("Keep this untracked input.\n")

    def source_operations(self):
        return {
            "spec init": self.c.spec_init,
            "spec freeze": self.c.spec_freeze,
            "plan init": self.c.plan_init,
            "plan freeze": self.c.plan_freeze,
            "prepare": self.c.prepare,
            "phase begin": lambda: self.c.phase_begin("P01"),
            "task claim": lambda: self.c.task_claim("T001", "rdd_large"),
            "task integrate": lambda: self.c.task_integrate("T001", "0" * 40),
            "task complete": lambda: self.c.task_complete("T001"),
            "task reopen": lambda: self.c.task_reopen("T001", "Repair within the frozen scope"),
            "anchors reconcile": self.c.anchors_reconcile,
            "resume": self.c.resume,
            **{f"workflow {stage}": lambda stage=stage: self.c.workflow(stage)
               for stage in ("specification", "preparation", "implementation")},
        }

    def test_main_rejects_source_operations_before_validation_or_state_writes(self):
        self.f.prepared()
        self.f.g("switch", "main")
        self.dirty_input()
        for name, operation in self.source_operations().items():
            with self.subTest(operation=name):
                self.rejected(operation)
        self.rejected(lambda: self.c.start("regenerate", "main-must-not-start"))

    def test_detached_rejects_source_operations_and_retains_dirty_inputs(self):
        self.f.prepared()
        self.f.g("switch", "--detach", "HEAD")
        self.dirty_input()
        for name, operation in self.source_operations().items():
            with self.subTest(operation=name):
                self.rejected(operation)
        self.rejected(lambda: self.c.start("regenerate", "detached-must-not-start"))

    def test_wrong_named_baseline_rejects_all_existing_run_source_operations(self):
        self.f.prepared()
        self.f.g("switch", "-c", "codex/other-release")
        self.dirty_input()
        for name, operation in self.source_operations().items():
            with self.subTest(operation=name):
                self.rejected(operation)

    def test_first_phase_records_the_release_baseline_and_exact_prepared_commit(self):
        self.f.prepared()
        baseline = head(self.root)
        opened = self.c.phase_begin("P01")
        self.assertEqual(opened["base_branch"], "codex/test-baseline")
        self.assertEqual(opened["base_sha"], baseline)
        self.assertEqual(self.c.state()["base_branch"], "codex/test-baseline")
        self.assertEqual(self.f.g("branch", "--show-current"), opened["branch"])
        self.assertEqual(head(self.root), baseline)

    def test_completed_phase_identity_uses_phase_order_across_three_digit_ids(self):
        state = self.c.state()
        state["phases"] = {"P100": {"status": "sealed", "branch": "codex/test-baseline"},
                           "P99": {"status": "sealed", "branch": "codex/previous-phase"}}
        self.assertEqual(self.c.guard_source_write(state), "codex/test-baseline")

    def test_implementation_requires_recorded_phase_even_at_identical_head(self):
        self.f.opened()
        self.f.g("switch", "-c", "codex/phase-lookalike")
        for name in ("task claim", "task integrate", "task complete", "task reopen", "anchors reconcile", "resume", "workflow implementation"):
            with self.subTest(operation=name):
                self.rejected(self.source_operations()[name])

    def test_integration_requires_the_recorded_worker_branch_before_intent(self):
        self.f.opened()
        claim = self.c.task_claim("T001", "rdd_large")
        worker = self.root / claim["lease"]["worktree"]
        self.f.g("switch", "-c", "codex/worker-lookalike", root=worker)
        path = worker / "tests/behavior.py"
        path.write_text(engine_fixture.BEHAVIOR_TEST + "\n" + path.read_text())
        commit = self.f.commit("Worker submission from the wrong identity", root=worker)
        self.rejected(lambda: self.c.task_integrate("T001", commit))
        self.assertEqual(self.f.g("branch", "--show-current", root=worker), "codex/worker-lookalike")
        self.assertNotIn("integration", self.c.state()["tasks"]["T001"])

    def test_checkpoint_import_rejects_wrong_branch_before_restoring_evidence(self):
        self.f.prepared()
        checkpoint = self.root / ".rdd/runtime/branch-checkpoint.json"
        self.c.export_run(checkpoint)
        self.f.g("switch", "-c", "codex/checkpoint-lookalike")
        self.rejected(lambda: self.c.resume(checkpoint))

    def test_checkpoint_branch_identity_is_checked_before_fresh_store_creation(self):
        self.f.prepared()
        checkpoint = self.root / ".rdd/runtime/branch-checkpoint.json"
        self.c.export_run(checkpoint)
        self.c.close()
        self.c._store = None
        for suffix in ("", "-wal", "-shm"):
            (self.root / (".rdd/runtime/state.sqlite3" + suffix)).unlink(missing_ok=True)
        (self.root / ".rdd/run.json").unlink()
        self.f.g("switch", "-c", "codex/fresh-checkpoint-lookalike")
        files = {p.relative_to(self.root).as_posix(): p.read_bytes()
                 for p in self.root.rglob("*")
                 if p.is_file() and ".git" not in p.relative_to(self.root).parts}
        with self.assertRaises(RddError) as caught:
            self.c.resume(checkpoint)
        self.assertEqual(caught.exception.kind, "environment")
        self.assertEqual({p.relative_to(self.root).as_posix(): p.read_bytes()
                          for p in self.root.rglob("*")
                          if p.is_file() and ".git" not in p.relative_to(self.root).parts}, files)
        self.assertIsNone(self.c._store)

    def test_wrong_branch_preflight_does_not_create_auxiliary_files_for_closed_store(self):
        self.c.close()
        self.c._store = None
        self.f.g("switch", "-c", "codex/closed-store-lookalike")
        runtime = self.root / ".rdd/runtime"
        before = {p.relative_to(runtime).as_posix(): p.read_bytes()
                  for p in runtime.rglob("*") if p.is_file()}
        with self.assertRaises(RddError) as caught:
            self.c.guard_source_write()
        self.assertEqual(caught.exception.kind, "environment")
        self.assertEqual({p.relative_to(runtime).as_posix(): p.read_bytes()
                          for p in runtime.rglob("*") if p.is_file()}, before)
        self.assertIsNone(self.c._store)

    def test_preflight_reads_latest_committed_live_wal_without_changing_its_files(self):
        state = self.c.state()
        state["base_branch"] = "codex/latest-wal-baseline"
        self.c.save(state)
        before = self.snapshot()
        self.assertEqual(Store.read(self.root, state["id"])["base_branch"], "codex/latest-wal-baseline")
        with self.assertRaisesRegex(RddError, "latest-wal-baseline") as caught:
            self.c.guard_source_write()
        self.assertEqual(caught.exception.kind, "environment")
        self.assertEqual(self.snapshot(), before)

    def test_preflight_recovers_wal_without_shm_only_in_the_temporary_copy(self):
        state = self.c.state()
        state["base_branch"] = "codex/recovered-wal-baseline"
        self.c.close()
        self.c._store = None
        path = self.root / ".rdd/runtime/state.sqlite3"
        program = ("import os, sqlite3, sys\n"
                   "db = sqlite3.connect(sys.argv[1])\n"
                   "db.execute('UPDATE runs SET value=? WHERE id=?', (sys.argv[3], sys.argv[2]))\n"
                   "db.commit()\n"
                   "os._exit(0)\n")
        subprocess.run([sys.executable, "-B", "-c", program, str(path), state["id"], json.dumps(state)], check=True)
        path.with_name(path.name + "-shm").unlink()
        self.assertTrue(path.with_name(path.name + "-wal").is_file())
        runtime = path.parent
        before = {p.relative_to(runtime).as_posix(): p.read_bytes()
                  for p in runtime.rglob("*") if p.is_file()}
        self.assertEqual(Store.read(self.root, state["id"])["base_branch"], "codex/recovered-wal-baseline")
        with self.assertRaisesRegex(RddError, "recovered-wal-baseline") as caught:
            self.c.guard_source_write()
        self.assertEqual(caught.exception.kind, "environment")
        self.assertEqual({p.relative_to(runtime).as_posix(): p.read_bytes()
                          for p in runtime.rglob("*") if p.is_file()}, before)
        self.assertIsNone(self.c._store)

    def test_main_inspection_validation_and_no_mode_print_do_not_start_a_run(self):
        self.f.g("switch", "main")
        before = self.snapshot()
        self.assertEqual(self.c.status()["run_id"], "fixture-run")
        self.assertGreater(self.c.spec_validate()["scenarios"], 0)
        packet = self.c.workflow("specification", print_only=True)
        self.assertEqual(packet["stage"], "specification")
        self.assertEqual(self.snapshot(), before)
        self.rejected(lambda: self.c.workflow("specification", "regenerate", print_only=True))

    def test_main_origin_run_can_be_inspected_exported_and_archived_by_fresh_start(self):
        self.f.prepared()
        state = self.c.state()
        state["base_branch"] = "main"  # A historical run created by the old controller.
        self.c.save(state)
        self.rejected(self.c.prepare)
        self.assertEqual(self.c.status()["status"], "prepared")
        checkpoint = self.root / ".rdd/runtime/legacy-checkpoint.json"
        self.c.export_run(checkpoint)
        self.assertEqual(read_json(checkpoint)["state"]["base_branch"], "main")
        self.c.start("regenerate", "replacement-release-run")
        self.assertEqual(self.c.state()["base_branch"], "codex/test-baseline")
        archived = read_json(self.root / ".rdd/baselines/replacement-release-run/previous-run.json")
        self.assertEqual(archived["base_branch"], "main")

    def test_export_into_repository_source_is_guarded_but_runtime_export_is_available(self):
        self.f.g("switch", "main")
        self.rejected(lambda: self.c.export_run(self.root / "user-note.json"))
        checkpoint = self.root / ".rdd/runtime/inspect-main.json"
        self.c.export_run(checkpoint)
        self.assertEqual(read_json(checkpoint)["state"]["id"], "fixture-run")

    def test_controller_construction_does_not_create_runtime_before_main_rejection(self):
        with tempfile.TemporaryDirectory(prefix="rdd-branch-preflight-") as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            write_json(root / ".rdd/config.json", self.f.config)
            controller = Controller(root)
            self.addCleanup(controller.close)
            before = (root / ".rdd/config.json").read_bytes()
            with self.assertRaises(RddError) as caught:
                controller.start("regenerate", "not-started")
            self.assertEqual(caught.exception.kind, "environment")
            self.assertFalse((root / ".rdd/runtime").exists())
            self.assertIsNone(controller._store)
            self.assertEqual((root / ".rdd/config.json").read_bytes(), before)

    def test_cli_rejections_precede_operation_lock_and_preserve_full_runtime(self):
        self.f.prepared()
        for branch in ("main", "codex/cli-lookalike"):
            if branch == "main":
                self.f.g("switch", "main")
            else:
                self.f.g("switch", "codex/test-baseline")
                self.f.g("switch", "-c", branch)
            self.dirty_input()
            commands = (("spec", "init"), ("spec", "freeze"), ("plan", "init"), ("plan", "freeze"),
                        ("prepare",), ("contracts", "generate"), ("anchors", "reconcile"), ("resume",),
                        ("phase", "begin", "P01"), ("task", "complete", "T001"),
                        ("task", "integrate", "T001", "--commit", "0" * 40),
                        ("task", "reopen", "T001", "--reason", "Repair the frozen scope"),
                        ("workflow", "specification"), ("workflow", "preparation"),
                        ("export-run", str(self.root / "source-export.json")))
            for command in commands:
                with self.subTest(branch=branch, command=command):
                    before = self.snapshot()
                    result = self.cli(*command)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout)["kind"], "environment")
                    self.assertEqual(self.snapshot(), before)
            self.assertFalse((self.root / ".rdd/runtime/controller.lock").exists())

    def test_cli_no_mode_print_is_usable_on_main_without_runtime_creation(self):
        with tempfile.TemporaryDirectory(prefix="rdd-print-preflight-") as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            write_json(root / ".rdd/config.json", self.f.config)
            result = self.cli("workflow", "specification", "--print", root=root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["stage"], "specification")
            self.assertFalse((root / ".rdd/runtime").exists())
            result = self.cli("workflow", "specification", "--mode", "regenerate", "--print", root=root)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["kind"], "environment")
            self.assertFalse((root / ".rdd/runtime").exists())

    def test_explicit_print_mode_cannot_reuse_a_run_from_another_authoring_branch(self):
        self.f.g("switch", "-c", "codex/print-lookalike")
        self.rejected(lambda: self.c.workflow("specification", "regenerate", print_only=True))
        before = self.snapshot()
        result = self.cli("workflow", "specification", "--mode", "regenerate", "--print")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["kind"], "environment")
        self.assertEqual(self.snapshot(), before)

    def test_cli_malformed_checkpoint_fails_before_store_or_operation_lock_mutation(self):
        checkpoint = self.root / ".rdd/runtime/malformed-checkpoint.json"
        for content in ("{", json.dumps({"schema_version": 1}), "[]"):
            with self.subTest(content=content):
                checkpoint.write_text(content)
                before = self.snapshot()
                result = self.cli("resume", "--from", str(checkpoint))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["kind"], "validation")
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.root / ".rdd/runtime/controller.lock").exists())

    def test_resume_preflight_bounds_checkpoint_before_parsing_or_lock_creation(self):
        checkpoint = self.root / ".rdd/runtime/oversized-checkpoint.json"
        with checkpoint.open("wb") as stream:
            stream.truncate(128 * 1024 * 1024 + 1)
        before = copy.deepcopy(self.c.state())
        with patch("tools.rdd.engine.read_json") as parse:
            with self.assertRaises(RddError) as caught:
                self.c.guard_resume(checkpoint)
            parse.assert_not_called()
        self.assertEqual(caught.exception.kind, "budget")
        result = self.cli("resume", "--from", str(checkpoint))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["kind"], "budget")
        self.assertFalse((self.root / ".rdd/runtime/controller.lock").exists())
        self.assertEqual(self.c.state(), before)

    def test_direct_generation_rejects_wrong_baseline_and_frozen_spec_before_tools(self):
        self.f.g("switch", "-c", "codex/generator-lookalike")
        for frozen in (False, True):
            if frozen:
                self.f.g("switch", "codex/test-baseline")
                self.c.spec_freeze()
            before = self.snapshot()
            with patch("tools.rdd.proto_traits.shutil.which") as tool_lookup:
                with self.assertRaises(ContractCheckError) as caught:
                    run_contracts(self.root, write=True, bootstrap_lock=True)
                tool_lookup.assert_not_called()
            self.assertTrue(caught.exception.blocked)
            self.assertEqual(self.snapshot(), before)

    def test_direct_generation_in_a_frozen_clone_requires_checkpoint_or_new_run(self):
        self.f.prepared()
        with tempfile.TemporaryDirectory(prefix="rdd-frozen-clone-") as directory:
            clone = Path(directory) / "clone"
            subprocess.run(["git", "clone", "--quiet", "--no-local", "--branch", "codex/test-baseline",
                            str(self.root), str(clone)], check=True)
            self.assertFalse((clone / ".rdd/run.json").exists())
            self.assertFalse((clone / ".rdd/runtime").exists())
            before = {p.relative_to(clone).as_posix(): p.read_bytes()
                      for p in clone.rglob("*")
                      if p.is_file() and ".git" not in p.relative_to(clone).parts}
            with patch("tools.rdd.proto_traits.shutil.which") as tool_lookup:
                with self.assertRaisesRegex(ContractCheckError, "Restore its checkpoint or start a new specification run") as caught:
                    run_contracts(clone, write=True, bootstrap_lock=True)
                tool_lookup.assert_not_called()
            self.assertTrue(caught.exception.blocked)
            self.assertEqual({p.relative_to(clone).as_posix(): p.read_bytes()
                              for p in clone.rglob("*")
                              if p.is_file() and ".git" not in p.relative_to(clone).parts}, before)
            self.assertFalse((clone / ".rdd/runtime").exists())


if __name__ == "__main__":
    unittest.main()
