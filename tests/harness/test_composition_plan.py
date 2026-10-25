"""Composition proof obligations use real source owners, without invented RPCs."""
import copy
from pathlib import Path
import tempfile
import unittest

from test_refinement import build_fixture
from test_specprep import plan_for
from tools.rdd import artifacts
from tools.rdd.common import RddError, file_hash, read_json, validate, write_json
from tools.rdd.engine import task_boundary_context
from tools.rdd.readiness import validate_boundary_plan, validate_producers, validate_resources


def build_composition_fixture(root):
    """Real v3 artifacts shared by specification and preparation regressions."""
    fixture = build_fixture(root)
    inventory = dict(schema_version=1, requirements_digest=fixture.controller.state()["requirements_digest"],
        domains=[dict(id="D-ITEMS", module="items", requirements=["FR-001"], behaviors=["B-STATE"], invariants=["I-ORDER"])],
        supporting_modules=[dict(id="S-APP", module="app", kind="orchestration", requirements=["FR-001"], behaviors=["B-INIT"])],
        interactions=[dict(id="I-WIRE", consumer="app", provider="items", kind="composition", requirements=["FR-001"], behaviors=[])])
    fixture.begin_s6(inventory=inventory)
    fixture.text("docs/specs/solution.md", (root / "docs/specs/solution.md").read_text() +
        "\nInitialization constructs and registers the generated-interface provider before ordered reads. "
        "Construction failure leaves dispatch unavailable and returns an initialization error.\n")
    fixture.controller.spec_snapshot("author-S6")
    spec = fixture.controller.spec()
    provider = spec["modules"][0]
    provider["public_exports"].append(dict(symbol="items::build", path="modules/items.rs", kind="construction",
        binding=None, specifications=["docs/specs/solution.md"]))
    consumer = copy.deepcopy(provider)
    consumer.update(id="app", owns_paths=["modules/app.rs", "tests/wiring.py"], depends_on=["items"], contract_package=None,
        provided_types=[], public_exports=[], contract_paths=[], generated_paths=[])
    for module, role, check in ((provider, "provider", "C-PROVIDER"), (consumer, "consumer", "C-CONSUMER")):
        for stage in ("qualification", "implementation"):
            module[stage + "_checks"] = {group: ["C-CONTRACTS" if stage == "qualification" else check]
                if group in {role, "dependency_direction", "compatibility", "semantics"} else []
                for group in module[stage + "_checks"]}
    spec["modules"].append(consumer)
    spec["solution_elements"].extend({**spec["solution_elements"][1], "id": eid, "module": "app", "scenarios": ["G-INIT", "G-INIT-FAIL"]}
                                      for eid in ("S-APP", "B-INIT"))
    for sid, kind, expected in (("G-INIT", "boundary", "Construction succeeds; registered dispatch reaches the generated provider"),
                               ("G-INIT-FAIL", "failure", "Construction failure returns initialization error; dispatch stays unavailable")):
        spec["scenarios"].append({**spec["scenarios"][0], "id": sid, "kind": kind, "description": "Initialize provider registration",
            "expected": expected, "solution_elements": ["S-APP", "B-INIT"], "preconditions": "No registered provider",
            "fixture": "Controlled constructor success or failure", "stimulus": "Initialize then dispatch a generated-interface query",
            "verification_method": "Assert registration visibility and initialization result independently"})
    spec["requirement_map"][0]["scenarios"].extend(["G-INIT", "G-INIT-FAIL"])
    spec["boundary_bindings"] = [dict(interaction="I-WIRE", operations=[], types=[], exports=["items::build"])]
    for rid, path in (("R-PROVIDER", "modules/items.rs"), ("R-CONSUMER", "modules/app.rs"), ("R-TEST", "tests/wiring.py")):
        spec["resources"].append({**spec["resources"][0], "id": rid, "path": path,
            "availability": "implementation" if rid == "R-TEST" else "baseline", "required_at": "implementation"})
        spec["target_tree"] = [row for row in spec["target_tree"] if row["path"] != path]
        spec["target_tree"].append(dict(path=path, kind="file", owner="D-ITEMS" if rid == "R-PROVIDER" else "S-APP",
            purpose="Composition source and evaluator", disposition="add" if rid == "R-TEST" else "modify"))
        if rid != "R-TEST":
            fixture.text(path, "// Baseline source for planned boundary adoption.\n")
    application = spec["checks"].pop()
    for cid, rid in (("C-PROVIDER", "R-PROVIDER"), ("C-CONSUMER", "R-CONSUMER")):
        spec["checks"].append({**application, "id": cid, "argv": ["{python}", "tests/wiring.py"],
            "requires": [rid, "R-TEST"], "red_pattern": "AssertionError: composition registration",
            "scenario_ids": [scenario["id"] for scenario in spec["scenarios"]],
            "results_path": ".rdd/evidence/results/" + cid + ".json"})
    spec["project_check_ids"] = ["C-PROVIDER", "C-CONSUMER"]
    for scenario in spec["scenarios"]:
        scenario["check_ids"] = spec["project_check_ids"]
    plan = plan_for(spec)
    template = plan["tasks"][0]
    plan["tasks"] = []
    for tid, category, path, elements in (("T003", "tests", "tests/wiring.py", ["S-APP", "B-INIT"]),
        ("T001", "modification", "modules/items.rs", ["D-ITEMS", "B-STATE", "I-ORDER"]),
        ("T002", "modification", "modules/app.rs", ["S-APP", "B-INIT"])):
        task = copy.deepcopy(template)
        task.update(id=tid, category=category, writes=[path], solution_elements=elements,
            scenarios=["G01"] if tid == "T001" else ["G-INIT", "G-INIT-FAIL"],
            checks=spec["project_check_ids"] if category == "tests" else [],
            depends_on=[] if tid == "T003" else [plan["tasks"][-1]["id"]],
            produces=["R-TEST"] if category == "tests" else [], bootstrap_resources=["R-TEST"] if category == "tests" else [])
        task["sites"][0]["path"] = path
        plan["tasks"].append(task)
    tids = [task["id"] for task in plan["tasks"]]
    plan["target_paths"] = [task["writes"][0] for task in plan["tasks"]]
    plan["shells"] = [dict(path="tests/wiring.py", content="# Composition evaluator\n")]
    plan["phases"][0].update(tasks=tids, checks=spec["project_check_ids"], deliverables=plan["target_paths"])
    plan["verticals"][0]["tasks"] = tids
    plan["element_coverage"] = [dict(element=element["id"], tasks=[task["id"] for task in plan["tasks"]
        if element["id"] in task["solution_elements"]], checks=spec["project_check_ids"], baseline_evidence=None)
        for element in spec["solution_elements"]]
    plan["resource_producers"] = [dict(resource=row["id"], kind="task" if row["id"] == "R-TEST" else "baseline",
        task="T003" if row["id"] == "R-TEST" else None, checks=[]) for row in spec["resources"]]
    plan["resource_uses"] = [dict(resource=row["id"], consumer_kind=kind, consumer=consumer)
        for row in spec["resources"] for kind, consumer in (("phase", "P01"), ("project", None))]
    plan["resource_uses"].extend(dict(resource=rid, consumer_kind="task_red", consumer="T003")
        for rid in ("R-PROVIDER", "R-CONSUMER", "R-TEST"))
    plan["boundary_proofs"] = [dict(interaction="I-WIRE", consumer="app", provider="items", export="items::build",
        first_phase="P01", checks=spec["project_check_ids"], provider_tasks=["T001"], consumer_tasks=["T002"], verification_tasks=["T003"])]
    return fixture, spec, plan


class CompositionFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixture, self.spec, self.plan = build_composition_fixture(self.root)
        self.addCleanup(self.fixture.controller.close)
        self.inventory = read_json(self.root / artifacts.DOMAIN_INVENTORY_PATH)
        self.proof = self.plan["boundary_proofs"][0]
        self.reqs = artifacts.requirements(self.root, "requirements/requirements.md")
        self.modules = artifacts.unique(self.spec["modules"], "module")
        self.elements = artifacts.unique(self.spec["solution_elements"], "element")
        self.checks = artifacts.unique(self.spec["checks"], "check")
        index = read_json(self.root / self.spec["contract_index_path"])["contract_index"]
        self.types = {entry["symbol"]: entry for entry in index["types"]}
        self.services, self.operations, self.service_owners = {}, {}, {}

    def save_inventory(self):
        write_json(self.root / artifacts.DOMAIN_INVENTORY_PATH, self.inventory)
        self.spec["domain_inventory"]["sha256"] = file_hash(self.root / artifacts.DOMAIN_INVENTORY_PATH)


class CompositionPlanTests(CompositionFixture):
    def validate(self):
        validate_boundary_plan(self.spec, self.plan, self.root)

    def test_complete_specification_to_preparation_handoff(self):
        config = self.fixture.controller.config
        reqs = artifacts.requirements(self.root, "requirements/requirements.md")
        artifacts.spec_validate(self.root, self.spec, reqs, config)
        artifacts.validate_accepted_domain_inventory(self.root, self.spec, self.fixture.controller.state()["workflow_nodes"])
        artifacts.plan_validate(self.root, self.plan, self.spec, {"digest": self.plan["spec_digest"]}, config)
        validate_resources(self.root, self.spec)
        validate_producers(self.root, self.spec, self.plan)

    def test_missing_composition_proof_is_rejected(self):
        self.plan["boundary_proofs"] = []
        with self.assertRaisesRegex(RddError, "composition.*missing"):
            self.validate()

    def test_worker_context_carries_frozen_exports_and_exact_proof_obligations(self):
        context = task_boundary_context(self.root, self.spec, self.plan, self.plan["tasks"][2])
        self.assertEqual(context["interactions"][0]["exports"], ["items::build"])
        self.assertEqual(context["modules"][0]["public_exports"], self.spec["modules"][0]["public_exports"])
        self.assertEqual(context.get("proofs"), [self.proof])

    def test_real_production_owners_and_baseline_provider_are_accepted(self):
        self.validate()
        self.proof["provider_tasks"] = []
        self.spec["resources"][1]["availability"] = "baseline"
        (self.root / "modules/items.rs").write_text("pub fn build() {}\n")
        self.validate()

    def test_composition_proof_schema_is_exclusive_and_preserves_callable_shape(self):
        schema = read_json(Path(__file__).resolve().parents[2] / ".rdd/schemas/plan.schema.json")
        proof_schema = schema["properties"]["boundary_proofs"]["items"]
        validate(self.proof, proof_schema, schema)
        call = {key: value for key, value in self.proof.items() if key != "export"}
        call.update(operation="items.v1.Items.Read", adapter_tasks=["T002"])
        validate(call, proof_schema, schema)
        for change in (dict(operation="items.v1.Items.Read"), dict(adapter_tasks=["T002"]), dict(consumer_tasks=[])):
            with self.subTest(change=change), self.assertRaises(RddError):
                validate({**self.proof, **change}, proof_schema, schema)
        with self.assertRaises(RddError):
            validate({**call, "provider_tasks": []}, proof_schema, schema)

    def test_baseline_provider_requires_existing_consumed_repository_source(self):
        self.proof["provider_tasks"] = []
        for defect in ("future", "missing", "unconsumed", "external"):
            with self.subTest(defect=defect):
                source = self.spec["resources"][1]
                source.update(availability="baseline", kind="repository")
                self.spec["checks"][1]["requires"] = ["R-PROVIDER", "R-TEST"]
                (self.root / "modules/items.rs").write_text("pub fn build() {}\n")
                if defect == "future":
                    source["availability"] = "implementation"
                elif defect == "missing":
                    (self.root / "modules/items.rs").unlink()
                elif defect == "unconsumed":
                    self.spec["checks"][1]["requires"] = ["R-TEST"]
                else:
                    source["kind"] = "external"
                with self.assertRaises(RddError):
                    self.validate()

    def test_each_selected_export_source_and_actual_consumer_are_required(self):
        baseline = copy.deepcopy((self.spec, self.plan))
        for defect in ("export_input", "export_owner", "consumer_input", "consumer_owner", "test_owner", "roles", "late_check", "late_test"):
            self.spec, self.plan = copy.deepcopy(baseline)
            proof = self.plan["boundary_proofs"][0]
            if defect == "export_input":
                self.spec["checks"][1]["requires"] = ["R-TEST"]
            elif defect == "export_owner":
                self.plan["tasks"][1]["writes"] = ["other.rs"]
            elif defect == "consumer_input":
                self.spec["checks"][2]["requires"] = ["R-PROVIDER", "R-TEST"]
            elif defect == "consumer_owner":
                self.plan["tasks"][2]["writes"] = ["modules/items.rs"]
            elif defect == "test_owner":
                self.plan["tasks"][0]["writes"] = ["unconsumed.rs"]
            elif defect == "roles":
                proof["checks"] = ["C-PROVIDER"]
            else:
                self.plan["phases"].append(dict(id="P02", checks=proof["checks"]))
                if defect == "late_check":
                    proof["first_phase"] = "P02"
                else:
                    self.plan["tasks"][0]["phase"] = "P02"
            with self.subTest(defect=defect), self.assertRaises(RddError):
                self.validate()

    def test_shared_provider_does_not_cover_second_consumer_or_selected_export(self):
        self.validate()
        self.inventory["supporting_modules"].append(dict(id="S-OTHER", module="other", kind="orchestration", requirements=["FR-001"], behaviors=["B-OTHER"]))
        self.inventory["interactions"].append(dict(id="I-OTHER", consumer="other", provider="items", kind="composition", requirements=["FR-001"], behaviors=[]))
        self.spec["modules"].append({**self.spec["modules"][1], "id": "other", "owns_paths": ["modules/other.rs"]})
        self.spec["boundary_bindings"].append(dict(interaction="I-OTHER", operations=[], types=[], exports=["items::build"]))
        self.save_inventory()
        with self.assertRaisesRegex(RddError, "composition.*missing"):
            self.validate()
        self.plan["boundary_proofs"].append({**self.proof, "interaction": "I-OTHER", "consumer": "other"})
        with self.assertRaisesRegex(RddError, "owned Rust boundary source"):
            self.validate()
        self.plan["boundary_proofs"].pop()
        self.spec["modules"].pop()
        self.inventory["supporting_modules"].pop()
        self.inventory["interactions"].pop()
        self.spec["boundary_bindings"].pop()
        self.save_inventory()
        self.spec["modules"][0]["owns_paths"].append("modules/wiring.rs")
        self.spec["modules"][0]["public_exports"].append(dict(symbol="items::wire", path="modules/wiring.rs", kind="wiring", binding=None, specifications=["docs/specs/solution.md"]))
        self.spec["boundary_bindings"][0]["exports"].append("items::wire")
        self.plan["boundary_proofs"].append({**self.proof, "export": "items::wire"})
        with self.assertRaises(RddError):
            self.validate()


if __name__ == "__main__":
    unittest.main()
