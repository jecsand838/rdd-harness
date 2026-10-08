"""Adversarial checks against actual subprocesses and isolated local Git repos.

These tests verify harness evidence semantics. They do not stand in for Cargo,
Buf, desktop, or reference-hardware verification of the generated application.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools.rdd import checks
from tools.rdd.common import (
    RddError, file_hash, git, head, read_json, source_digest, write_json,
)


REPO = Path(__file__).resolve().parents[2]
SPEC_DIGEST = "a" * 64
PLAN_DIGEST = "b" * 64
RED_MARKER = "FR_ASSERTION_expected_one_committed_task"


def metric_limit(**changes):
    value = {
        "name": "latency", "statistic": "p95", "comparison": "lte",
        "limit": 20, "unit": "ms", "minimum_samples": 20,
    }
    value.update(changes)
    return value


def payload(**changes):
    value = {
        "errors": 0,
        "environment": {"fixture": "synthetic-reference", "host_profile": "reference"},
        "samples": {"latency": list(range(1, 21))},
        "units": {"latency": "ms"},
    }
    value.update(changes)
    return value


@unittest.skipUnless(shutil.which("git"), "Git is required for source/evidence identity tests")
class CheckEvidenceTests(unittest.TestCase):
    def test_golden_results_require_every_scenario_once_with_pass(self):
        result_path = ".rdd/evidence/results/golden.json"
        valid = '{"scenarios":[{"id":"G1","outcome":"pass"},{"id":"G2","outcome":"pass"}]}'
        candidates = [valid, '{"scenarios":[{"id":"G1","outcome":"pass"}]}',
            valid.replace('"G2"', '"G1"'), valid.replace('"pass"', '"skip"', 1),
            valid.replace('"G2"', '"UNKNOWN"'), '{"scenarios":[],"scenarios":[]}',
            '{"scenarios":NaN}', ' ' * (4 * 1024 * 1024 + 1)]
        for index, value in enumerate(candidates):
            with self.subTest(index=index):
                # Keep the process argv bounded even for the oversized-output regression.
                expression = "' ' * (4 * 1024 * 1024 + 1)" if index == len(candidates) - 1 else repr(value)
                code = "from pathlib import Path; p=Path(" + repr(result_path) + "); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(" + expression + ",encoding='utf-8')"
                check = self.check(code, scenario_ids=["G1", "G2"], results_path=result_path)
                evidence = self.execute(check)
                self.assertEqual(evidence["outcome"], "pass" if index == 0 else "fail")
                if index == 0:
                    self.verify(evidence, check)
                else:
                    with self.assertRaises(RddError):
                        self.verify(evidence, check)

    def test_golden_result_file_is_removed_before_each_actual_execution(self):
        path = self.root / ".rdd/evidence/results/golden.json"
        write_json(path, {"scenarios": [{"id": "G1", "outcome": "pass"}]})
        check = self.check("print('No scenario executed')", scenario_ids=["G1"], results_path=path.relative_to(self.root).as_posix())
        evidence = self.execute(check)
        self.assertEqual(evidence["outcome"], "fail")
        self.assertFalse(path.exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        (self.root / ".rdd").mkdir()
        shutil.copytree(REPO / ".rdd/schemas", self.root / ".rdd/schemas")
        (self.root / "subject.py").write_text("value = 1\n", encoding="utf-8")
        (self.root / ".gitignore").write_text(".rdd/runtime/\n.rdd/evidence/\n", encoding="utf-8")
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "RDD Evidence Test")
        git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "isolated test baseline")

    def check(self, code="print('ok')", **changes):
        value = {
            "id": "C-TEST", "kind": "test", "argv": ["{python}", "-c", code],
            "cwd": ".", "timeout_seconds": 5, "platforms": ["any"],
            "host_profile": None, "red_pattern": RED_MARKER, "metrics": [],
        }
        value.update(changes)
        return value

    def benchmark(self, value=None, *, text=None, **changes):
        serialized = text if text is not None else json.dumps(payload() if value is None else value)
        check = self.check("print(" + repr(serialized) + ")", id="C-BENCH", kind="benchmark",
                           metrics=[metric_limit()], red_pattern="")
        check.update(changes)
        return check

    def execute(self, check, expectation="pass"):
        return checks.execute_check(
            self.root, check, phase="P01", task_id="T-001", expectation=expectation,
            spec_digest=SPEC_DIGEST, plan_digest=PLAN_DIGEST,
        )

    def verify(self, evidence, check, **changes):
        expected = {
            "commit": head(self.root), "sources": source_digest(self.root),
            "spec_digest": SPEC_DIGEST, "plan_digest": PLAN_DIGEST,
        }
        expected.update(changes)
        return checks.verify_receipt(self.root, evidence, check, **expected)

    def rewrite_log(self, evidence, mutate):
        changed = copy.deepcopy(evidence)
        path = self.root / changed["log_path"]
        log = read_json(path)
        mutate(log)
        write_json(path, log)
        changed["log_digest"] = file_hash(path)
        return changed

    def qualify_host(self):
        write_json(self.root / ".rdd/runtime/host.json", {
            "profile": "reference", "platform": checks.platform_name(),
            "qualification": {"protocol": "synthetic test fixture; not product benchmark evidence"},
        })

    def test_actual_behavioral_assertion_is_red(self):
        check = self.check("assert 0 == 1, " + repr(RED_MARKER))
        result = self.execute(check, "fail")
        self.assertEqual(result["outcome"], "red")
        self.assertGreater(result["returncode"], 0)
        self.assertIn("AssertionError", read_json(self.root / result["log_path"])["stderr"])

    def test_green_output_containing_red_marker_is_not_red(self):
        result = self.execute(self.check("print(" + repr(RED_MARKER) + ")"), "fail")
        self.assertEqual(result["outcome"], "fail")
        self.assertEqual(result["returncode"], 0)

    def test_real_syntax_and_import_failures_never_satisfy_red(self):
        programs = [
            "print(" + repr(RED_MARKER) + "); compile('def broken(', '<fixture>', 'exec')",
            "print(" + repr(RED_MARKER) + "); import rdd_deliberately_unavailable_module_903812",
        ]
        for code in programs:
            with self.subTest(code=code):
                result = self.execute(self.check(code), "fail")
                self.assertEqual(result["outcome"], "fail")
                self.assertGreater(result["returncode"], 0)

    def test_wrong_assertion_failure_is_not_red_for_this_scenario(self):
        result = self.execute(self.check("assert False, 'a different behavior failed'"), "fail")
        self.assertEqual(result["outcome"], "fail")

    def test_timed_out_process_is_not_red_even_after_marker(self):
        code = "import time; print(" + repr(RED_MARKER) + ", flush=True); time.sleep(30)"
        result = self.execute(self.check(code, timeout_seconds=0.2), "fail")
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("timed out", read_json(self.root / result["log_path"])["evaluation"])

    def test_truncated_capture_is_inconclusive_and_never_reloaded_unbounded(self):
        with patch.object(checks, "MAX_CAPTURE_BYTES", 32):
            result = self.execute(self.check("print('x' * 1000)"))
        self.assertEqual(result["outcome"], "fail")
        log = read_json(self.root / result["log_path"])
        self.assertLessEqual(len(log["stdout"].encode("utf-8")), 32)
        self.assertIn("capture budget", log["evaluation"])

    def test_red_requires_a_test_and_frozen_behavior_pattern(self):
        for changes in ({"kind": "build"}, {"red_pattern": ""}):
            with self.subTest(changes=changes), self.assertRaises(RddError):
                self.execute(self.check(**changes), "fail")

    def test_successful_command_that_mutates_source_has_invalid_receipt(self):
        code = "from pathlib import Path; Path('subject.py').write_text('value = 2\\n')"
        result = self.execute(self.check(code))
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["outcome"], "fail")
        self.assertIn("mutated source", read_json(self.root / result["log_path"])["evaluation"])

    def test_assertion_that_mutates_source_cannot_supply_red(self):
        code = "from pathlib import Path; Path('subject.py').write_text('value = 2\\n'); assert False, " + repr(RED_MARKER)
        result = self.execute(self.check(code), "fail")
        self.assertEqual(result["outcome"], "fail")

    def test_head_change_invalidates_even_unchanged_source(self):
        code = "import subprocess; subprocess.run(['git','commit','--allow-empty','-m','unexpected verifier commit'], check=True)"
        before = source_digest(self.root)
        result = self.execute(self.check(code))
        self.assertEqual(source_digest(self.root), before)
        self.assertEqual(result["outcome"], "fail")

    def test_nearest_rank_p95_uses_raw_samples_not_interpolation(self):
        values = payload(samples={"latency": [1000, *range(19, 0, -1)]})
        check = self.benchmark(values, metrics=[metric_limit(limit=19)])
        result = self.execute(check)
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["metrics"], {"latency.p95": 19.0})
        self.verify(result, check)

    def test_zero_exit_bad_benchmark_evidence_fails(self):
        cases = {
            "threshold": payload(samples={"latency": [21] * 20}),
            "wrong_units": payload(units={"latency": "s"}),
            "errors_present": payload(errors=1),
            "boolean_errors": payload(errors=False),
            "floating_errors": payload(errors=0.0),
            "too_few": payload(samples={"latency": list(range(19))}),
            "missing_metric": payload(samples={}),
            "sample_string": payload(samples={"latency": ["1"] * 20}),
            "sample_boolean": payload(samples={"latency": [True] * 20}),
            "nonfinite_nan": payload(samples={"latency": [float("nan")] * 20}),
            "nonfinite_infinity": payload(samples={"latency": [float("inf")] * 20}),
            "missing_environment": payload(environment={}),
            "samples_not_map": payload(samples=[1, 2, 3]),
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                result = self.execute(self.benchmark(value))
                self.assertEqual(result["returncode"], 0)
                self.assertEqual(result["outcome"], "fail")

    def test_ambiguous_duplicate_json_fields_are_rejected(self):
        text = json.dumps(payload())
        text = text.replace('"errors": 0', '"errors": 1, "errors": 0')
        result = self.execute(self.benchmark(text=text))
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["outcome"], "fail")

    def test_invalid_json_and_trailing_text_are_not_benchmark_results(self):
        for text in ("not JSON", json.dumps(payload()) + "\nall done"):
            with self.subTest(text=text):
                result = self.execute(self.benchmark(text=text))
                self.assertEqual(result["outcome"], "fail")

    def test_qualified_benchmark_wrong_root_shape_fails_without_crashing(self):
        self.qualify_host()
        result = self.execute(self.benchmark(text="[]", host_profile="reference"))
        self.assertEqual(result["outcome"], "fail")

    def test_valid_receipt_binds_exact_source_and_specification(self):
        check = self.check()
        evidence = self.execute(check)
        self.verify(evidence, check)
        for name, value in (
            ("check_id", "C-OTHER"), ("source_commit", "c" * 40),
            ("source_digest", "c" * 64), ("spec_digest", "c" * 64),
            ("plan_digest", "c" * 64), ("command", ["different-command"]),
        ):
            with self.subTest(field=name):
                forged = copy.deepcopy(evidence)
                forged[name] = value
                with self.assertRaises(RddError):
                    self.verify(forged, check)

    def test_uncommitted_source_change_makes_previous_receipt_stale(self):
        check = self.check()
        evidence = self.execute(check)
        (self.root / "subject.py").write_text("value = 2\n", encoding="utf-8")
        with self.assertRaisesRegex(RddError, "source_digest"):
            self.verify(evidence, check)

    def test_tampered_raw_log_is_rejected_by_digest(self):
        check = self.check()
        evidence = self.execute(check)
        (self.root / evidence["log_path"]).write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(RddError, "hash mismatch"):
            self.verify(evidence, check)

    def test_imported_log_size_is_bounded_before_parsing(self):
        check = self.check()
        evidence = self.execute(check)
        with patch.object(checks, "MAX_RECEIPT_LOG_BYTES", 16):
            with self.assertRaisesRegex(RddError, "size bound"):
                self.verify(evidence, check)

    def test_rehashed_malformed_log_is_validation_failure(self):
        check = self.check()
        evidence = self.execute(check)
        path = self.root / evidence["log_path"]
        path.write_text("not a JSON log", encoding="utf-8")
        evidence["log_digest"] = file_hash(path)
        with self.assertRaises(RddError):
            self.verify(evidence, check)

    def test_imported_red_rechecks_the_behavioral_assertion(self):
        check = self.check("assert False, " + repr(RED_MARKER))
        evidence = self.execute(check, "fail")
        self.verify(evidence, check, require_pass=False)
        forged = self.rewrite_log(evidence, lambda log: log.update(
            stderr="error[E0308]: incompatible type; " + RED_MARKER
        ))
        with self.assertRaisesRegex(RddError, "behavioral assertion"):
            self.verify(forged, check, require_pass=False)

    def test_forged_aggregate_is_recomputed_from_raw_samples(self):
        check = self.benchmark()
        evidence = self.execute(check)
        evidence["metrics"]["latency.p95"] = 0
        with self.assertRaisesRegex(RddError, "aggregate"):
            self.verify(evidence, check)

    def test_rehashed_log_command_must_match_frozen_command(self):
        check = self.benchmark()
        evidence = self.execute(check)
        forged = self.rewrite_log(evidence, lambda log: log.update(argv=["different-command"]))
        with self.assertRaises(RddError):
            self.verify(forged, check)

    def test_rehashed_raw_samples_cannot_hide_threshold_failure(self):
        check = self.benchmark()
        evidence = self.execute(check)
        forged = self.rewrite_log(evidence, lambda log: log.update(stdout=json.dumps(payload(samples={"latency": [200] * 20}))))
        with self.assertRaises(RddError):
            self.verify(forged, check)

    def test_rehashed_host_claim_must_match_qualified_profile(self):
        self.qualify_host()
        check = self.benchmark(host_profile="reference")
        evidence = self.execute(check)
        self.verify(evidence, check)

        def wrong_host(log):
            log["host"]["profile"] = "other-machine"

        forged = self.rewrite_log(evidence, wrong_host)
        with self.assertRaises(RddError):
            self.verify(forged, check)

    def test_rehashed_stdout_environment_must_match_profile(self):
        self.qualify_host()
        check = self.benchmark(host_profile="reference")
        evidence = self.execute(check)

        def wrong_environment(log):
            value = json.loads(log["stdout"])
            value["environment"]["host_profile"] = "other-machine"
            log["stdout"] = json.dumps(value)

        forged = self.rewrite_log(evidence, wrong_environment)
        with self.assertRaises(RddError):
            self.verify(forged, check)

    def test_missing_executable_is_environment_blocker(self):
        with self.assertRaises(RddError) as caught:
            self.execute(self.check(argv=[str(self.root / "unavailable-tool")]))
        self.assertEqual(caught.exception.kind, "environment")

    def test_wrong_native_platform_is_environment_blocker(self):
        current = checks.platform_name()
        required = next(name for name in ("windows", "macos", "linux") if name != current)
        with self.assertRaises(RddError) as caught:
            self.execute(self.check(platforms=[required]))
        self.assertEqual(caught.exception.kind, "environment")

    def test_unknown_host_platform_is_environment_blocker(self):
        with patch.object(checks.sys, "platform", "unrecognized-platform"):
            with self.assertRaises(RddError) as caught:
                checks.platform_name()
        self.assertEqual(caught.exception.kind, "environment")

    def test_missing_or_mismatched_host_qualification_blocks(self):
        check = self.benchmark(host_profile="reference")
        with self.assertRaises(RddError) as caught:
            self.execute(check)
        self.assertEqual(caught.exception.kind, "environment")
        for host in (
            {"profile": "wrong", "platform": checks.platform_name(), "qualification": "x"},
            {"profile": "reference", "platform": "wrong", "qualification": "x"},
            {"profile": "reference", "platform": checks.platform_name()},
        ):
            with self.subTest(host=host):
                write_json(self.root / ".rdd/runtime/host.json", host)
                with self.assertRaises(RddError) as caught:
                    self.execute(check)
                self.assertEqual(caught.exception.kind, "environment")

    def test_manual_check_cannot_be_satisfied_by_a_zero_exit_command(self):
        with self.assertRaises(RddError) as caught:
            self.execute(self.check(kind="manual"))
        self.assertEqual(caught.exception.kind, "environment")

    def test_manual_protocol_references_exact_frozen_check(self):
        check = self.check(id="C-MANUAL")
        evidence = self.execute(check)
        check["kind"] = "manual"
        evidence["origin"] = "manual"
        evidence["provenance"]["actor"] = "Synthetic fixture evaluator"
        report = {
            "decision": "pass", "protocol": f"spec:{SPEC_DIGEST}#check:C-MANUAL",
            "observations": ["Synthetic test fixture observation; no product claim."],
        }
        path = self.root / evidence["log_path"]
        write_json(path, report)
        evidence["log_digest"] = file_hash(path)
        self.verify(evidence, check)
        for reference in ("anything", "", " ", f"spec:{'c' * 64}#check:C-MANUAL",
                          f"spec:{SPEC_DIGEST}#check:C-OTHER"):
            with self.subTest(reference=reference):
                report["protocol"] = reference
                write_json(path, report)
                evidence["log_digest"] = file_hash(path)
                with self.assertRaises(RddError):
                    self.verify(evidence, check)

    def test_manual_observations_must_contain_written_findings(self):
        check = self.check(id="C-MANUAL")
        evidence = self.execute(check)
        check["kind"] = "manual"
        evidence["origin"] = "manual"
        evidence["provenance"]["actor"] = "Synthetic fixture evaluator"
        path = self.root / evidence["log_path"]
        for observations in ("", "   ", True, [], ["   "]):
            with self.subTest(observations=observations):
                write_json(path, {
                    "decision": "pass", "protocol": f"spec:{SPEC_DIGEST}#check:C-MANUAL",
                    "observations": observations,
                })
                evidence["log_digest"] = file_hash(path)
                with self.assertRaises(RddError):
                    self.verify(evidence, check)


class MetricEvaluationTests(unittest.TestCase):
    def test_a_benchmark_without_limits_cannot_pass_vacuously(self):
        with self.assertRaises(RddError):
            checks.evaluate_metrics({"metrics": []}, payload())

    def test_each_declared_metric_must_pass(self):
        check = {"metrics": [metric_limit(name="launch"), metric_limit(name="save")]}
        value = payload(samples={"launch": [1] * 20, "save": [500] * 20},
                        units={"launch": "ms", "save": "ms"})
        with self.assertRaises(RddError):
            checks.evaluate_metrics(check, value)

    def test_duplicate_statistic_cannot_silently_replace_an_aggregate(self):
        with self.assertRaises(RddError):
            checks.evaluate_metrics({"metrics": [metric_limit(), metric_limit()]}, payload())

    def test_nearest_rank_even_sample_median_and_other_statistics(self):
        value = payload(samples={"latency": [4, 1, 3, 2]})
        expected = {"p50": 2.0, "p95": 4.0, "min": 1.0, "max": 4.0, "mean": 2.5}
        for statistic, result in expected.items():
            with self.subTest(statistic=statistic):
                check = {"metrics": [metric_limit(statistic=statistic, minimum_samples=4)]}
                self.assertEqual(checks.evaluate_metrics(check, value), {f"latency.{statistic}": result})


if __name__ == "__main__":
    unittest.main()
