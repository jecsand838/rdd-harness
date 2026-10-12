"""Suite selection, honest outcomes and timings for the offline harness runner."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from rdd import cli


class SelftestTests(unittest.TestCase):
    def test_suite_and_timing_options_are_accepted_and_full_is_default(self):
        parser = cli.parser()
        self.assertEqual(getattr(parser.parse_args(["selftest"]), "suite", None), "full")
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                args = parser.parse_args(["selftest", "--suite", "portability", "--timings", "timings.json"])
            except SystemExit as exc:
                self.fail(f"Selftest suite/timing options were rejected: {exc.code}")
        self.assertEqual(args.suite, "portability")
        self.assertEqual(args.timings, Path("timings.json"))

    def runner(self):
        from rdd import selftest
        return selftest

    def test_portability_selectors_discover_exact_49_tests_without_lifecycle_suite(self):
        runner = self.runner()
        root = Path(__file__).resolve().parents[2]
        suite = runner.load_suite(root, "portability")
        ids = [test.id() for test in runner.iter_tests(suite)]
        self.assertEqual(len(ids), 49)
        self.assertEqual(len(ids), len(set(ids)))
        allowed = ("test_portability.PortabilityTests.", "test_adapters.RunArgvTests.",
                   "test_adapters.GitAdapterTests.", "test_store.StoreTests.")
        wal = {"test_branch_guards.BranchGuardTests.test_preflight_reads_latest_committed_live_wal_without_changing_its_files",
               "test_branch_guards.BranchGuardTests.test_preflight_recovers_wal_without_shm_only_in_the_temporary_copy"}
        self.assertEqual({name for name in ids if not name.startswith(allowed)}, wal)

    def test_full_discovery_preserves_bare_fixture_imports_and_includes_new_regressions(self):
        runner = self.runner()
        suite = runner.load_suite(Path(__file__).resolve().parents[2], "full")
        discovered = [test.id() for test in runner.iter_tests(suite)]
        self.assertEqual(len(discovered), len(set(discovered)))
        ids = set(discovered)
        self.assertIn("test_engine.EngineTests.test_full_real_local_tdd_to_project_validation_with_fake_github", ids)
        self.assertIn("test_fixture_reuse.FixtureReuseTests.test_one_real_preparation_per_consuming_class", ids)
        self.assertIn("test_selftest.SelftestTests.test_suite_and_timing_options_are_accepted_and_full_is_default", ids)
        self.assertFalse(any("_FailedTest" in name for name in ids))

    def test_runner_executes_in_selected_root_and_restores_caller_directory(self):
        runner = self.runner()
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            class WorkingDirectory(unittest.TestCase):
                def test_directory(self):
                    self.assertEqual(Path.cwd(), root)
            with patch.object(runner, "load_suite", return_value=unittest.defaultTestLoader.loadTestsFromTestCase(WorkingDirectory)):
                report = runner.run(root, stream=io.StringIO())
            self.assertEqual(report["status"], "passed")
            self.assertEqual(Path.cwd(), previous)

    def test_timings_capture_each_test_and_real_failure_error_and_skip(self):
        runner = self.runner()
        class Samples(unittest.TestCase):
            def test_pass(self):
                self.assertTrue(True)
            def test_failure(self):
                with self.subTest(case="failure"):
                    self.fail("Observed assertion failure")
            def test_error(self):
                raise RuntimeError("Observed runtime error")
            @unittest.skip("Explicit sample skip")
            def test_skip(self):
                pass
            @unittest.expectedFailure
            def test_expected_failure(self):
                self.fail("Expected sample failure")
            @unittest.expectedFailure
            def test_unexpected_success(self):
                pass
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested/timings.json"
            with patch.object(runner, "load_suite", return_value=unittest.defaultTestLoader.loadTestsFromTestCase(Samples)):
                report = runner.run(Path(directory), "full", path, stream=io.StringIO())
            timings = json.loads(path.read_text())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["returncode"], 1)
        self.assertEqual(report["scope"], "harness_regression")
        self.assertFalse(report["application_complete"])
        self.assertEqual(timings["suite"], "full")
        self.assertEqual(timings["count"], 6)
        self.assertFalse(timings["successful"])
        self.assertEqual({row["outcome"] for row in timings["tests"]},
                         {"pass", "failure", "error", "skip", "expected_failure", "unexpected_success"})
        self.assertEqual(len({row["id"] for row in timings["tests"]}), 6)
        self.assertGreaterEqual(timings["duration_seconds"], sum(row["duration_seconds"] for row in timings["tests"]))

    def test_successful_portability_summary_and_cli_exit_codes(self):
        runner = self.runner()
        class Passing(unittest.TestCase):
            def test_pass(self):
                self.assertEqual(1, 1)
        with patch.object(runner, "load_suite", return_value=unittest.defaultTestLoader.loadTestsFromTestCase(Passing)):
            report = runner.run(Path.cwd(), "portability", stream=io.StringIO())
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["scope"], "harness_portability")
        self.assertEqual(report["tests_run"], 1)
        for status, code in (("passed", 0), ("failed", 1)):
            with self.subTest(status=status), patch.object(runner, "run", return_value={**report, "status": status, "returncode": code}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["selftest", "--suite", "portability"]), code)


if __name__ == "__main__":
    unittest.main()
