"""Stateless CI tests against isolated candidate and trusted-policy repositories."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from tools.rdd import artifacts, ci
from tools.rdd.adapters import run_argv
from tools.rdd.common import RddError, digest, file_hash, head, read_json, write_json


class VerifierSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.base = self.home / "baseline"
        self.candidate = self.home / "candidate"
        self.base.mkdir()
        self.output = self.home / "github-output"
        self.required = (".rdd/config.json", "tools/rdd/cli.py")
        for path in self.required:
            self.write(self.candidate, path)
        workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/rdd.yml").read_text(encoding="utf-8")
        self.selector = textwrap.dedent(workflow.split("python - <<'RDD_SELECT_VERIFIER'\n", 1)[1]
                                       .split("\n          RDD_SELECT_VERIFIER", 1)[0])

    def write(self, root, relative):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")

    def select(self, branch="codex/initialize-rdd-harness"):
        self.output.unlink(missing_ok=True)
        return run_argv([sys.executable, "-c", self.selector], self.home,
                        env={"GITHUB_OUTPUT": str(self.output), "RDD_HEAD_BRANCH": branch})

    def test_empty_base_uses_candidate_for_initial_import(self):
        result = self.select()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "root=candidate\n")

    def test_complete_base_is_selected_despite_candidate_policy_changes(self):
        for path in self.required:
            self.write(self.base, path)
        (self.candidate / ".rdd/config.json").write_text("changed candidate policy\n", encoding="utf-8")
        self.write(self.candidate, ".rdd/spec.lock.json")
        result = self.select("rdd/example/p01")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "root=baseline\n")

    def test_partial_base_cannot_bootstrap(self):
        for path in (*self.required, ".rdd/leftover", "tools/rdd/leftover"):
            with self.subTest(path=path):
                shutil.rmtree(self.base)
                self.base.mkdir()
                self.write(self.base, path)
                result = self.select()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("partial harness", result.stderr)
                self.assertFalse(self.output.exists())

    def test_each_candidate_freeze_prevents_bootstrap(self):
        for path in (".rdd/spec.lock.json", ".rdd/plan/plan.lock.json", ".rdd/prepared.json"):
            with self.subTest(path=path):
                self.write(self.candidate, path)
                result = self.select()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("cannot contain frozen", result.stderr)
                self.assertFalse(self.output.exists())
                (self.candidate / path).unlink()

    def test_phase_branch_cannot_bootstrap(self):
        for branch in ("rdd/example/p01", "rdd/malformed"):
            with self.subTest(branch=branch):
                result = self.select(branch)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("RDD phase branch", result.stderr)
                self.assertFalse(self.output.exists())

    def test_incomplete_candidate_cannot_bootstrap(self):
        for path in self.required:
            with self.subTest(path=path):
                (self.candidate / path).unlink()
                result = self.select()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("complete candidate harness", result.stderr)
                self.assertFalse(self.output.exists())
                self.write(self.candidate, path)


@unittest.skipUnless(shutil.which("git"), "Git is required for isolated CI candidate tests")
class CiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.base = self.home / "baseline"
        self.candidate = self.home / "candidate"
        self.base.mkdir()
        self.repo_source = Path(__file__).resolve().parents[2]
        self.commands = []
        self.config = {"schema_version": 1, "requirements": "requirements/requirements.md",
                       "limits": {"max_spec_words": 20000, "max_tasks": 500, "max_phases": 40},
                       "protected_prefixes": ["requirements/", "docs/specs/", "contracts/", "gen/", ".rdd/",
                                              ".agents/", ".codex/", ".github/", "tools/rdd/"],
                       "protected_files": ["AGENTS.md", "rdd"]}
        self.write(self.base, ".gitignore", ".rdd/runtime/\n.rdd/evidence/\n.rdd/run.json\n__pycache__/\n")
        self.write(self.base, "AGENTS.md", "Requirements govern the implementation.\n")
        self.write(self.base, "tools/rdd/policy.py", "# Fixture policy revision\n")
        write_json(self.base / ".rdd/config.json", self.config)
        for name in ("spec", "plan", "evidence"):
            destination = self.base / f".rdd/schemas/{name}.schema.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.repo_source / f".rdd/schemas/{name}.schema.json", destination)
        self.init_git(self.base)
        self.commit(self.base, "bootstrap")

    def write(self, root, relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def command(self, root, *args):
        result = run_argv(["git", *args], root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def init_git(self, root):
        self.command(root, "init", "-b", "main")
        self.command(root, "config", "core.autocrlf", "false")
        self.command(root, "config", "user.name", "RDD Test")
        self.command(root, "config", "user.email", "rdd-test@example.invalid")

    def commit(self, root, message):
        self.command(root, "add", ".")
        self.command(root, "commit", "-m", message)

    def clone(self):
        # Preserve the exact bytes recorded by the fixture's frozen artifacts.
        result = run_argv(["git", "clone", "-c", "core.autocrlf=false", "--no-hardlinks",
                           str(self.base), str(self.candidate)], self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.command(self.candidate, "config", "user.name", "RDD Test")
        self.command(self.candidate, "config", "user.email", "rdd-test@example.invalid")

    def check(self, name, kind="test", platforms=None, host_profile=None):
        return {"id": name, "kind": kind, "argv": ["{python}", "-c", "assert 2 + 2 == 4; print('checked')"],
                "cwd": ".", "timeout_seconds": 20, "platforms": platforms or ["any"],
                "red_pattern": "EXPECTED_BEHAVIORAL_FAILURE", "metrics": [], "host_profile": host_profile}

    def prepare(self, *, extras=None, ordinary_platforms=None, sidecar=False):
        self.write(self.base, "requirements/requirements.md",
                   "# Requirements\n\n**FR-001 First behavior**\nThe app shall do the first thing.\nAcceptance: Verify first behavior.\n\n"
                   "**FR-002 Second behavior**\nThe app shall do the second thing.\nAcceptance: Verify second behavior.\n")
        self.write(self.base, "docs/specs/application.md", "# Application\n\nFirst and second observable behavior and their contracts.\n")
        self.write(self.base, "contracts/example.proto", 'syntax = "proto3";\nmessage Example {}\n')
        self.write(self.base, "gen/example.rs", "pub struct Example;\n")
        requirement_digest = file_hash(self.base / "requirements/requirements.md")
        checks = [self.check("C-CONTRACT", "contract", ordinary_platforms),
                  self.check("C-FIRST", platforms=ordinary_platforms),
                  self.check("C-SECOND", platforms=ordinary_platforms)]
        checks += extras or []
        self.spec = {
            "schema_version": 1, "id": "spec-fixture", "requirements_digest": requirement_digest,
            "mode": "regenerate", "parent_spec_digest": None,
            "change_summary": "This is a deliberately minimal, executable controller test fixture.",
            "documents": ["docs/specs/application.md"], "decisions": [],
            "contract_files": ["contracts/example.proto"], "generated_files": ["gen/example.rs"],
            "contract_check_ids": ["C-CONTRACT"], "project_check_ids": ["C-FIRST", "C-SECOND"],
            "modules": [{"id": "example", "requirements": ["FR-001", "FR-002"],
                         "contract_paths": ["contracts/example.proto"], "owns_paths": ["modules/"], "depends_on": []}],
            "scenarios": [{"id": "S-FIRST", "requirements": ["FR-001"], "kind": "golden",
                           "description": "First behavior", "expected": "First expected output", "check_ids": ["C-FIRST"]},
                          {"id": "S-SECOND", "requirements": ["FR-002"], "kind": "golden",
                           "description": "Second behavior", "expected": "Second expected output", "check_ids": ["C-SECOND"]}],
            "checks": checks,
            "requirement_map": [{"requirement": "FR-001", "specifications": ["docs/specs/application.md"], "scenarios": ["S-FIRST"]},
                                {"requirement": "FR-002", "specifications": ["docs/specs/application.md"], "scenarios": ["S-SECOND"]}],
            "amendment": {"requirements": [], "paths": [], "rationale": ""},
        }
        write_json(self.base / ".rdd/spec.json", self.spec)
        spec_files = {path: file_hash(self.base / path) for path in (
            ".rdd/spec.json", "requirements/requirements.md", "docs/specs/application.md", "contracts/example.proto", "gen/example.rs")}
        self.spec_lock = {"schema_version": 1, "files": spec_files,
                          "requirements_digest": requirement_digest}
        self.spec_lock["digest"] = digest(self.spec_lock)
        write_json(self.base / ".rdd/spec.lock.json", self.spec_lock)
        tasks = []
        for number in (1, 2):
            tasks.append({"id": f"T{number:03d}", "title": f"Implement behavior {number}", "phase": f"P{number:02d}",
                          "category": "tests", "requirements": [f"FR-{number:03d}"],
                          "specifications": ["docs/specs/application.md"],
                          "depends_on": [] if number == 1 else ["T001"],
                          "writes": [f"tests/acceptance/behavior{number}.py"],
                          "checks": ["C-FIRST" if number == 1 else "C-SECOND"],
                          "acceptance": ["Expected behavior is verified"], "scope": "small",
                          "anchor": {"path": f"tests/acceptance/behavior{number}.py", "mode": "inline"}, "reuse": None})
        if sidecar:
            tasks[0]["anchor"]["mode"] = "sidecar"
        self.plan = {
            "schema_version": 1, "spec_digest": self.spec_lock["digest"],
            "phases": [{"id": "P01", "goal": "First behavior", "tasks": ["T001"],
                        "checks": ["C-FIRST"] + [item["id"] for item in extras or []],
                        "requirements_closed": ["FR-001"], "deliverables": ["tests/acceptance/behavior1.py"], "independent_evidence": ["First review"]},
                       {"id": "P02", "goal": "Second behavior", "tasks": ["T002"], "checks": ["C-SECOND"],
                        "requirements_closed": ["FR-002"], "deliverables": ["tests/acceptance/behavior2.py"], "independent_evidence": ["Second review"]}],
            "tasks": tasks, "verticals": [{"id": "V-FIRST-SECOND", "goal": "Both behaviors", "tasks": ["T001", "T002"]}],
            "target_paths": [task["writes"][0] for task in tasks],
            "shells": [{"path": task["writes"][0], "content": "# Implementation shell\n"} for task in tasks],
        }
        write_json(self.base / ".rdd/plan/plan.json", self.plan)
        matrix = self.write(self.base, ".rdd/plan/implementation-matrix.md", artifacts.implementation_matrix(self.plan))
        plan_files = {".rdd/plan/plan.json": file_hash(self.base / ".rdd/plan/plan.json")}
        self.plan_lock = {"schema_version": 1, "files": plan_files, "spec_digest": self.spec_lock["digest"]}
        self.plan_lock["digest"] = digest(self.plan_lock)
        write_json(self.base / ".rdd/plan/plan.lock.json", self.plan_lock)
        state = {"tasks": {task["id"]: {"status": "pending"} for task in tasks}}
        artifacts.materialize(self.base, self.plan, state)
        prepared = {"schema_version": 1, "run_id": "ci-fixture", "spec_digest": self.spec_lock["digest"],
                    "plan_digest": self.plan_lock["digest"],
                    "shell_hashes": {task["writes"][0]: file_hash(self.base / task["writes"][0]) for task in tasks},
                    "matrix_digest": file_hash(matrix)}
        prepared["digest"] = digest(prepared)
        write_json(self.base / ".rdd/prepared.json", prepared)
        # Check fixture semantics before exercising CI's post-implementation paths.
        reqs = artifacts.requirements(self.base, self.config["requirements"])
        artifacts.spec_validate(self.base, self.spec, reqs, self.config)
        artifacts.plan_validate(self.base, self.plan, self.spec, self.spec_lock, self.config)
        self.commit(self.base, "prepare fixture")

    def complete_phase(self, number):
        for task in self.plan["tasks"]:
            if int(task["phase"][1:]) <= number:
                artifacts.remove_anchor(self.candidate, task)
        self.commit(self.candidate, f"complete phase {number}")

    def execute(self, root, check, **kwargs):
        """Observe actual frozen-check execution without substituting its result."""
        from tools.rdd.checks import execute_check
        self.commands.append(check["id"])
        return execute_check(root, check, **kwargs)

    def verify(self, branch):
        with patch("tools.rdd.ci._execute", side_effect=self.execute):
            return ci.verify(self.candidate, self.base, branch)

    def test_bootstrap_is_explicitly_harness_only(self):
        self.clone()
        report = self.verify("main")
        self.assertEqual(report["status"], "harness_only")
        self.assertEqual(report["scope"], "bootstrap")
        self.assertFalse(report["application_complete"])
        self.assertEqual(self.commands, [])
        self.assertEqual(read_json(self.candidate / ".rdd/evidence/ci.json")["status"], "harness_only")

    def test_protected_change_fails_before_any_command(self):
        self.prepare()
        self.clone()
        self.complete_phase(1)
        self.write(self.candidate, "tools/rdd/policy.py", "# weaken the verifier\n")
        with self.assertRaisesRegex(RddError, "trusted policy"):
            self.verify("rdd/ci-fixture/p01")
        self.assertEqual(self.commands, [])
        self.assertEqual(read_json(self.candidate / ".rdd/evidence/ci.json")["status"], "failed")

    def test_untracked_protected_addition_cannot_hide_in_gitignore(self):
        self.clone()
        self.write(self.candidate, ".gitignore", ".codex/\n.rdd/evidence/\n")
        self.write(self.candidate, ".codex/injected.toml", 'model="unexpected"\n')
        with self.assertRaisesRegex(RddError, "trusted policy"):
            self.verify("main")
        self.assertEqual(self.commands, [])

    def test_candidate_cannot_remove_a_frozen_plan(self):
        self.prepare()
        self.clone()
        (self.candidate / ".rdd/plan/plan.lock.json").unlink()
        with self.assertRaises(RddError):
            self.verify("rdd/ci-fixture/p01")
        self.assertEqual(self.commands, [])

    def test_candidate_cannot_introduce_its_own_trusted_policy(self):
        self.clone()
        write_json(self.candidate / ".rdd/plan/plan.lock.json", {"digest": "0" * 64})
        with self.assertRaises(RddError):
            self.verify("main")
        self.assertEqual(self.commands, [])

    def test_inconsistent_freeze_digest_in_both_checkouts_is_rejected(self):
        self.prepare()
        self.spec_lock["digest"] = "0" * 64
        write_json(self.base / ".rdd/spec.lock.json", self.spec_lock)
        self.commit(self.base, "malformed trusted lock")
        self.clone()
        with self.assertRaisesRegex(RddError, "lock digest is inconsistent"):
            self.verify("main")
        self.assertEqual(self.commands, [])

    def test_matrix_corruption_in_trusted_preparation_is_rejected(self):
        self.prepare()
        self.write(self.base, ".rdd/plan/implementation-matrix.md", "# Incorrect matrix\n")
        self.commit(self.base, "malformed trusted preparation")
        self.clone()
        with self.assertRaisesRegex(RddError, "matrix changed after freeze"):
            self.verify("main")
        self.assertEqual(self.commands, [])

    def test_phase_checks_are_cumulative_and_reference_the_exact_head(self):
        self.prepare()
        self.clone()
        self.complete_phase(2)
        report = self.verify("rdd/ci-fixture/p02")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(self.commands, ["C-CONTRACT", "C-FIRST", "C-SECOND"])
        self.assertEqual(report["source_commit"], head(self.candidate))
        self.assertEqual(report["anchors"]["remaining"], 0)
        self.assertFalse(report["application_complete"])
        self.assertFalse(report["task_history_verified"])

    def test_prepared_main_checks_contracts_without_claiming_implementation(self):
        self.prepare()
        self.clone()
        report = self.verify("main")
        self.assertEqual(report["scope"], "prepared_baseline")
        self.assertEqual(report["status"], "harness_only")
        self.assertEqual(self.commands, ["C-CONTRACT"])
        self.assertEqual(report["anchors"]["remaining"], 2)

    def test_completed_sidecar_is_mutable_projection_and_future_anchor_survives(self):
        self.prepare(sidecar=True)
        self.clone()
        self.complete_phase(1)
        report = self.verify("rdd/ci-fixture/p01")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["anchors"]["remaining"], 1)

    def test_actual_failing_command_persists_failure_instead_of_green(self):
        failing = self.check("C-FAIL")
        failing["argv"] = ["{python}", "-c", "raise SystemExit(7)"]
        self.prepare(extras=[failing])
        self.clone()
        self.complete_phase(1)
        with self.assertRaisesRegex(RddError, "did not pass"):
            self.verify("rdd/ci-fixture/p01")
        receipt = read_json(self.candidate / ".rdd/evidence/ci.json")
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["checks"][-1]["returncode"], 7)

    def test_current_phase_marker_must_be_gone_and_future_marker_must_remain(self):
        self.prepare()
        self.clone()
        with self.assertRaisesRegex(RddError, "still has an anchor"):
            self.verify("rdd/ci-fixture/p01")
        self.complete_phase(2)
        with self.assertRaisesRegex(RddError, "requires exactly one anchor"):
            self.verify("rdd/ci-fixture/p01")
        self.assertEqual(self.commands, [])

    def test_wrong_run_unknown_phase_and_malformed_branch_are_rejected(self):
        self.prepare()
        self.clone()
        self.complete_phase(1)
        for branch in ("rdd/other/p01", "rdd/ci-fixture/p99", "rdd/ci-fixture/p001", "rdd/ci-fixture/no-phase"):
            with self.subTest(branch=branch), self.assertRaises(RddError):
                self.verify(branch)
        self.assertEqual(self.commands, [])

    def test_manual_and_reference_host_checks_remain_explicitly_pending_external(self):
        manual = self.check("C-MANUAL", "manual")
        manual["argv"] = []
        benchmark = self.check("C-REFERENCE", "benchmark", host_profile="qualified-desktop")
        benchmark["metrics"] = [{"name": "latency", "statistic": "p95", "limit": 200,
                                 "comparison": "lte", "minimum_samples": 100, "unit": "ms"}]
        self.prepare(extras=[manual, benchmark])
        self.clone()
        self.complete_phase(1)
        report = self.verify("rdd/ci-fixture/p01")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(self.commands, ["C-CONTRACT", "C-FIRST"])
        self.assertEqual([row["check_id"] for row in report["pending_external"]], ["C-MANUAL", "C-REFERENCE"])
        self.assertFalse(report["application_complete"])

    def test_no_platform_relevant_ordinary_check_cannot_turn_green(self):
        other = "windows" if ci._host_platform() != "windows" else "linux"
        manual = self.check("C-MANUAL", "manual")
        manual["argv"] = []
        self.prepare(extras=[manual], ordinary_platforms=[other])
        self.clone()
        self.complete_phase(1)
        with self.assertRaisesRegex(RddError, "No ordinary"):
            self.verify("rdd/ci-fixture/p01")
        self.assertEqual(self.commands, [])

    def test_red_or_stale_receipt_cannot_pass_ci(self):
        self.prepare()
        self.clone()
        self.complete_phase(1)
        for mutation in ("red", "stale"):
            def bad(root, check, **kwargs):
                receipt = self.execute(root, check, **kwargs)
                if mutation == "red":
                    receipt["outcome"] = "red"
                else:
                    receipt["source_commit"] = "0" * 40
                return receipt
            with self.subTest(mutation=mutation), patch("tools.rdd.ci._execute", side_effect=bad), self.assertRaises(RddError):
                ci.verify(self.candidate, self.base, "rdd/ci-fixture/p01")

    def test_commands_that_mutate_source_invalidate_the_ci_result(self):
        self.prepare()
        self.clone()
        self.complete_phase(1)
        def mutation(root, check, **kwargs):
            receipt = self.execute(root, check, **kwargs)
            self.write(root, "tests/acceptance/behavior1.py", "# Changed by test\n")
            return receipt
        with patch("tools.rdd.ci._execute", side_effect=mutation), self.assertRaises(RddError):
            ci.verify(self.candidate, self.base, "rdd/ci-fixture/p01")

    @unittest.skipIf(os.name == "nt", "Symlink creation needs extra privilege on Windows")
    def test_symlinked_policy_directory_is_rejected(self):
        self.clone()
        outside = self.home / "outside"
        outside.mkdir()
        (self.candidate / ".codex").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RddError):
            self.verify("main")
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()
