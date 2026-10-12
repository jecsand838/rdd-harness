"""Exercise the workflow's selector and mandatory job aggregation as plain data."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]


def embedded_script(workflow, marker):
    text = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
    return textwrap.dedent(text.split(f"python - <<'{marker}'\n", 1)[1]
                           .split(f"\n          {marker}", 1)[0])


class WorkflowRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.base = self.home / "baseline"
        self.candidate = self.home / "candidate"
        self.output = self.home / "output"
        self.base.mkdir()
        self.git(self.base, "init", "-b", "main")
        self.git(self.base, "config", "user.name", "Test")
        self.git(self.base, "config", "user.email", "test@example.invalid")
        for path in (".rdd/config.json", "tools/rdd/cli.py", "README.md", "docs/harness/guide.md"):
            self.write(self.base, path)
        (self.base / ".rdd/config.json").write_text('{"protected_prefixes": [], "protected_files": []}\n')
        self.commit(self.base)
        self.base_sha = self.git(self.base, "rev-parse", "HEAD")
        self.git(self.home, "clone", "--no-hardlinks", str(self.base), str(self.candidate))
        self.git(self.candidate, "config", "user.name", "Test")
        self.git(self.candidate, "config", "user.email", "test@example.invalid")

    def git(self, root, *argv):
        result = subprocess.run(["git", *argv], cwd=root, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def write(self, root, path):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n", encoding="utf-8")

    def commit(self, root, stage=True):
        if stage:
            self.git(root, "add", ".")
        self.git(root, "commit", "--allow-empty", "-m", "fixture")

    def select(self, branch="feature/maintenance", **replacement):
        self.commit(self.candidate)
        self.output.unlink(missing_ok=True)
        environment = dict(os.environ, GITHUB_OUTPUT=str(self.output), GITHUB_EVENT_NAME="pull_request",
                           GITHUB_REPOSITORY="example/repo", RDD_HEAD_REPOSITORY="example/repo",
                           RDD_BASE_REPOSITORY="example/repo", RDD_BASE_BRANCH="main", RDD_HEAD_BRANCH=branch,
                           RDD_POLICY_SHA=self.base_sha, RDD_HEAD_SHA=self.git(self.candidate, "rev-parse", "HEAD"))
        environment.update(replacement)
        result = subprocess.run([sys.executable, "-c", embedded_script("rdd.yml", "RDD_SELECT_VERIFIER")],
                                cwd=self.home, env=environment, capture_output=True, text=True)
        outputs = dict(line.split("=", 1) for line in self.output.read_text().splitlines()) if self.output.exists() else {}
        return result, outputs

    def test_ordinary_maintenance_uses_linux_full_and_short_portability(self):
        self.write(self.candidate, "tools/rdd/changed.py")
        result, outputs = self.select()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs.get("mode"), "harness_maintenance")
        self.assertEqual(outputs.get("full"), "true")
        self.assertEqual(json.loads(outputs.get("full_matrix", "{}")), {"os": ["ubuntu-24.04"]})
        self.assertEqual(outputs.get("portability"), "true")
        self.assertEqual(outputs.get("trusted"), "true")
        self.assertEqual(outputs.get("controller"), "false")
        self.assertEqual(outputs.get("application_complete"), "false")

    def test_docs_only_and_main_push_are_lightweight(self):
        self.write(self.candidate, "docs/harness/new-guide.md")
        for event in ("pull_request", "push"):
            with self.subTest(event=event):
                result, outputs = self.select(GITHUB_EVENT_NAME=event, RDD_HEAD_BRANCH="main" if event == "push" else "feature/docs")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(outputs.get("lightweight"), "true")
                for key in ("full", "portability", "trusted", "controller"):
                    self.assertEqual(outputs.get(key), "false", key)

    def test_unknown_protected_and_instruction_paths_cannot_be_docs_only(self):
        for path in ("docs/harness/AGENTS.md", "docs/harness/SKILL.md", "docs/harness/config.json", "docs/specs/design.md",
                     "requirements/requirements.md", "contracts/example.proto", ".github/workflows/other.yml"):
            with self.subTest(path=path):
                self.write(self.candidate, path)
                result, outputs = self.select()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(outputs.get("lightweight"), "false")
                (self.candidate / path).unlink()

    def test_trusted_config_can_protect_otherwise_allowed_documentation(self):
        self.write(self.candidate, "docs/harness/new-guide.md")
        for key, paths in (("protected_prefixes", ["docs/harness/"]), ("protected_files", ["docs/harness/new-guide.md"])):
            with self.subTest(key=key):
                (self.base / ".rdd/config.json").write_text(json.dumps({key: paths}))
                result, outputs = self.select()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(outputs.get("lightweight"), "false")
        (self.base / ".rdd/config.json").write_text("not JSON")
        result, outputs = self.select()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs.get("lightweight"), "false")

    def test_both_rename_paths_must_be_documentation(self):
        self.git(self.candidate, "mv", "docs/harness/guide.md", "docs/harness/renamed.md")
        result, outputs = self.select()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs.get("lightweight"), "true")
        self.git(self.candidate, "mv", "docs/harness/renamed.md", "guide.md")
        result, outputs = self.select()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs.get("lightweight"), "false")

    def test_symlink_markdown_and_dangling_freeze_fail_closed(self):
        # Windows checks out mode120000 as a regular file without requiring link privileges.
        self.write(self.candidate, "docs/harness/link.md")
        blob = self.git(self.candidate, "hash-object", "-w", "docs/harness/link.md")
        self.git(self.candidate, "update-index", "--add", "--cacheinfo", f"120000,{blob},docs/harness/link.md")
        self.commit(self.candidate, stage=False)
        # Avoid restaging the regular Windows representation over the Git symlink mode.
        self.git(self.candidate, "config", "core.symlinks", "false")
        (self.candidate / "docs/harness/link.md").unlink()
        self.git(self.candidate, "checkout", "--", "docs/harness/link.md")
        result, outputs = self.select()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs.get("lightweight"), "false")
        try:
            (self.candidate / ".rdd/spec.lock.json").symlink_to("missing")
        except OSError:
            self.write(self.candidate, ".rdd/spec.lock.json")
        result, outputs = self.select()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(outputs.get("mode"), "harness_maintenance")
        self.assertEqual(outputs.get("controller"), "true")

    def test_partial_freeze_in_either_tree_and_phase_branch_cannot_use_maintenance(self):
        for root in (self.base, self.candidate):
            with self.subTest(root=root.name):
                self.write(root, ".rdd/spec.lock.json")
                result, outputs = self.select()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotEqual(outputs.get("mode"), "harness_maintenance")
                self.assertEqual(outputs.get("controller"), "true")
                (root / ".rdd/spec.lock.json").unlink()
        result, outputs = self.select("rdd/example/p01", RDD_BASE_BRANCH="codex/example-baseline")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs.get("controller"), "true")

    def test_dispatch_requires_exact_full_sha_and_selects_all_native_candidates(self):
        sha = self.git(self.candidate, "rev-parse", "HEAD")
        for input_sha, run_sha, ref in (("short", sha, "refs/heads/feature/test"),
                                        ("A" * 40, sha, "refs/heads/feature/test"),
                                        ("b" * 40, sha, "refs/heads/feature/test")):
            with self.subTest(input_sha=input_sha):
                result, _ = self.select(GITHUB_EVENT_NAME="workflow_dispatch", RDD_DISPATCH_CANDIDATE=input_sha,
                                        GITHUB_SHA=run_sha, GITHUB_REF=ref)
                self.assertNotEqual(result.returncode, 0)
        # select commits an empty fixture revision, so bind to its prospective HEAD explicitly.
        self.commit(self.candidate)
        sha = self.git(self.candidate, "rev-parse", "HEAD")
        result = subprocess.run([sys.executable, "-c", embedded_script("rdd.yml", "RDD_SELECT_VERIFIER")], cwd=self.home,
                                env=dict(os.environ, GITHUB_OUTPUT=str(self.output), GITHUB_EVENT_NAME="workflow_dispatch",
                                         RDD_DISPATCH_CANDIDATE=sha, GITHUB_SHA=sha, RDD_HEAD_SHA=sha,
                                         RDD_HEAD_BRANCH="feature/test", RDD_POLICY_SHA=self.base_sha), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        outputs = dict(line.split("=", 1) for line in self.output.read_text().splitlines())
        self.assertEqual(json.loads(outputs.get("full_matrix", "{}")), {"os": ["ubuntu-24.04", "macos-latest", "windows-latest"]})
        self.assertEqual(outputs.get("controller"), "false")


class WorkflowStructureTests(unittest.TestCase):
    def test_routing_does_not_remove_required_pr_targets_or_filter_paths(self):
        workflow = (ROOT / ".github/workflows/rdd.yml").read_text()
        self.assertIn("branches: [main, 'rdd/**', 'codex/*-baseline']", workflow)
        self.assertNotIn("paths:", workflow.split("permissions:", 1)[0])
        self.assertIn("branches: [main]\n", workflow)
        self.assertIn("timeout-minutes: 60", workflow)
        self.assertIn("timeout-minutes: 45", workflow)
        self.assertIn("selftest --suite portability --timings", workflow)
        self.assertIn("command += ['--suite', 'full', '--timings'", workflow)


class MandatoryJobTests(unittest.TestCase):
    def aggregate(self, needs):
        workflow = (ROOT / ".github/workflows/rdd.yml").read_text()
        self.assertIn("python - <<'RDD_VERIFY_JOBS'", workflow)
        return subprocess.run([sys.executable, "-c", embedded_script("rdd.yml", "RDD_VERIFY_JOBS")],
                              env=dict(os.environ, RDD_NEEDS=json.dumps(needs)), capture_output=True, text=True)

    def jobs(self, selected=("full", "portability", "trusted")):
        mapping = {"full": "harness", "portability": "portability", "lightweight": "lightweight",
                   "trusted": "trusted", "controller": "controller"}
        outputs = {flag: "true" if flag in selected else "false" for flag in mapping}
        return {"selection": {"result": "success", "outputs": outputs},
                **{job: {"result": "success" if flag in selected else "skipped"} for flag, job in mapping.items()}}

    def test_selected_jobs_must_all_succeed_and_only_unselected_can_skip(self):
        for selected in (("full", "portability", "trusted"), ("lightweight",), ("controller", "trusted"), ("full",)):
            with self.subTest(selected=selected):
                result = self.aggregate(self.jobs(selected))
                self.assertEqual(result.returncode, 0, result.stderr)
        for job, flag in (("harness", "full"), ("portability", "portability"), ("trusted", "trusted"),
                          ("lightweight", "lightweight"), ("controller", "controller")):
            for state in ("skipped", "cancelled", "failure", "", "unknown"):
                with self.subTest(job=job, state=state):
                    needs = self.jobs((flag,))
                    needs[job]["result"] = state
                    self.assertNotEqual(self.aggregate(needs).returncode, 0)
            needs = self.jobs((flag,))
            del needs[job]
            self.assertNotEqual(self.aggregate(needs).returncode, 0)

    def test_failed_selection_or_unselected_failure_cannot_pass(self):
        for state in ("failure", "skipped", "cancelled", ""):
            with self.subTest(selection=state):
                needs = self.jobs()
                needs["selection"]["result"] = state
                self.assertNotEqual(self.aggregate(needs).returncode, 0)
        for state in ("failure", "cancelled", "unknown", "success"):
            with self.subTest(unselected=state):
                needs = self.jobs()
                needs["controller"]["result"] = state
                self.assertNotEqual(self.aggregate(needs).returncode, 0)
        needs = self.jobs()
        needs["selection"]["outputs"]["controller"] = ""
        self.assertNotEqual(self.aggregate(needs).returncode, 0)

    def test_aggregate_needs_closes_over_every_lane_and_dispatch_name_is_distinct(self):
        workflow = (ROOT / ".github/workflows/rdd.yml").read_text()
        aggregate = workflow.split("\n  verify:\n", 1)[1]
        self.assertIn("needs: [selection, harness, portability, lightweight, trusted, controller]", aggregate)
        self.assertIn("'native qualification'", aggregate)
        self.assertIn("'harness diagnostics'", aggregate)
        self.assertIn("'verify'", aggregate)


class HistoricalSelftestTests(unittest.TestCase):
    def run_candidate(self, *, modern=False, exitcode=0, help_failure=False, marker="RDD_FULL_SELFTEST"):
        workflow = (ROOT / ".github/workflows/rdd.yml").read_text()
        self.assertTrue(f"python - <<'{marker}'" in workflow, "Selftest needs a bounded historical CLI wrapper")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cli = root / "tools/rdd/cli.py"
            cli.parent.mkdir(parents=True)
            cli.write_text(textwrap.dedent(f'''\
                import json, sys
                from pathlib import Path
                if '--help' in sys.argv:
                    print('usage: cli selftest [-h] {'--suite --timings' if modern else ''}')
                    raise SystemExit({1 if help_failure else 0})
                Path('argv.json').write_text(json.dumps(sys.argv[1:]))
                print('Ran 7 tests in 0.02s', file=sys.stderr)
                raise SystemExit({exitcode})
                '''))
            summary = root / "summary"
            result = subprocess.run([sys.executable, "-c", embedded_script("rdd.yml", marker)], cwd=root,
                                    env=dict(os.environ, GITHUB_STEP_SUMMARY=str(summary)), capture_output=True, text=True)
            args = json.loads((root / "argv.json").read_text()) if (root / "argv.json").exists() else None
            return result, args, summary.read_text() if summary.exists() else ""

    def test_old_full_cli_uses_plain_selftest_and_observed_summary(self):
        result, args, summary = self.run_candidate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(args, ["selftest"])
        self.assertIn("tests: 7", summary)
        self.assertIn("per-test timings unavailable", summary)
        self.assertIn("application_complete=false", summary)

    def test_modern_cli_receives_flags_and_test_failure_never_retries(self):
        result, args, _ = self.run_candidate(modern=True, exitcode=3)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(args, ["selftest", "--suite", "full", "--timings", ".rdd/evidence/selftest-full.json"])
        result, args, _ = self.run_candidate(exitcode=4)
        self.assertEqual(result.returncode, 4)
        self.assertEqual(args, ["selftest"])
        result, args, _ = self.run_candidate(help_failure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(args)

    def test_trusted_wrapper_uses_plain_cli_and_propagates_nonzero_exit(self):
        for exitcode in (0, 2):
            with self.subTest(exitcode=exitcode):
                result, args, summary = self.run_candidate(modern=True, exitcode=exitcode, marker="RDD_TRUSTED_SELFTEST")
                self.assertEqual(result.returncode, exitcode)
                self.assertEqual(args, ["selftest"])
                self.assertIn("Suite: full (trusted CLI)", summary)
                self.assertIn("tests: 7", summary)
                self.assertIn("duration:", summary)


if __name__ == "__main__":
    unittest.main()
