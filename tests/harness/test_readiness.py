"""Readiness rejects missing execution inputs before product implementation."""
from pathlib import Path
import tempfile
import unittest

from tools.rdd.common import RddError
from tools.rdd.readiness import validate_resources, validate_producers


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "runner.py").write_text("assert 1 + 1 == 2\n", encoding="utf-8")
        self.spec = {"environments": [{"id": "local", "platform": "linux", "host_profile": None}],
            "resources": [{"id": "runner", "kind": "repository", "availability": "baseline",
                "path": "runner.py", "version": None, "probe_check_ids": [], "environments": ["local"]}],
            "checks": [{"id": "test", "kind": "test", "argv": ["python", "runner.py"],
                "cwd": ".", "requires": ["runner"], "environments": ["local"],
                "platforms": ["linux"], "host_profile": None}], "target_tree": []}
        self.plan = {"resource_producers": [{"resource": "runner", "kind": "baseline", "task": None, "checks": []}],
            "tasks": [{"id": "T001", "phase": "P01", "category": "tests", "depends_on": [],
                "writes": ["test.py"], "checks": ["test"], "requires": ["runner"], "produces": [], "bootstrap_resources": []}],
            "phases": [{"id": "P01", "checks": ["test"]}]}

    def test_missing_baseline_runner_is_not_ready(self):
        (self.root / "runner.py").unlink()
        with self.assertRaisesRegex(RddError, "runner"):
            validate_resources(self.root, self.spec)

    def test_missing_producer_fails(self):
        self.plan["resource_producers"] = []
        with self.assertRaisesRegex(RddError, "producer"):
            validate_producers(self.root, self.spec, self.plan)

    def test_late_runner_cannot_support_first_red(self):
        self.spec["resources"][0]["availability"] = "implementation"
        producer = dict(self.plan["tasks"][0], id="T002", category="addition", checks=[], requires=[],
                        writes=["runner.py"], produces=["runner"])
        self.plan["tasks"].append(producer)
        self.plan["resource_producers"][0].update(kind="task", task="T002")
        with self.assertRaisesRegex(RddError, "before|prerequisite"):
            validate_producers(self.root, self.spec, self.plan)

    def test_host_scope_must_cover_declared_check(self):
        self.spec["checks"][0]["platforms"] = ["windows"]
        with self.assertRaisesRegex(RddError, "platform"):
            validate_resources(self.root, self.spec)

    def test_tool_requires_pin_and_executable_probe(self):
        self.spec["resources"][0].update(kind="tool", path="python", version=None)
        with self.assertRaisesRegex(RddError, "pin|version"):
            validate_resources(self.root, self.spec)

    def test_valid_baseline_producer_is_closed(self):
        validate_resources(self.root, self.spec)
        validate_producers(self.root, self.spec, self.plan)


if __name__ == "__main__":
    unittest.main()


class BoundaryReadinessTests(unittest.TestCase):
    def setUp(self):
        import test_artifacts
        self.f = test_artifacts.Fixture(methodName="runTest")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_bootstrap_test_cannot_claim_production_provider_ownership(self):
        from tools.rdd.readiness import validate_boundary_plan
        self.f.plan["boundary_proofs"][0]["provider_tasks"] = ["T001"]
        with self.assertRaisesRegex(RddError, "production"):
            validate_boundary_plan(self.f.spec, self.f.plan)

    def test_unrelated_runner_write_cannot_claim_provider_ownership(self):
        from tools.rdd.readiness import validate_boundary_plan
        self.f.plan["tasks"][1]["writes"] = ["tests/unrelated_runner.py"]
        with self.assertRaisesRegex(RddError, "adapter source"):
            validate_boundary_plan(self.f.spec, self.f.plan)

    def test_second_operation_cannot_escape_role_and_due_phase_ownership(self):
        from tools.rdd.readiness import validate_boundary_plan
        self.f.spec["solution_elements"][1]["contract_operations"].append("fixture.v1.FixtureService.Unplanned")
        with self.assertRaisesRegex(RddError, "Every contract operation"):
            validate_boundary_plan(self.f.spec, self.f.plan)

    def test_arbitrary_success_command_cannot_qualify_canonical_contracts(self):
        from tools.rdd.readiness import canonical_contract_check
        with self.assertRaisesRegex(RddError, "protected canonical"):
            canonical_contract_check(self.f.spec)
        self.f.spec["checks"][0]["argv"] = ["{python}", "tools/rdd/proto_traits.py", "--write"]
        with self.assertRaisesRegex(RddError, "controller-owned"):
            canonical_contract_check(self.f.spec)

    def test_qualification_cannot_require_future_implementation_inputs(self):
        from tools.rdd.readiness import validate_resources
        self.f.spec["checks"][0]["requires"] = ["fixture-provider"]
        with self.assertRaisesRegex(RddError, "future product input"):
            validate_resources(self.f.root, self.f.spec)
