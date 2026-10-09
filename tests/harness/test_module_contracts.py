"""Module boundary controls; these fixtures are not Todo acceptance evidence."""
import copy
import json
from tests.harness.test_artifacts import Fixture
from tools.rdd.artifacts import requirements, boundary_check_ids
from tools.rdd.common import RddError, file_hash
from tools.rdd.engine import policy_inventory


class ModuleCoverageTests(Fixture):
    def test_optional_buf_dependency_lock_presence_and_bytes_are_frozen(self):
        before = policy_inventory(self.root)
        self.assertEqual(before.get("buf.lock"), "MISSING", "optional dependency lock absence must be explicit")
        self.write(".gitignore", "buf.lock\n")
        self.write("buf.lock", "version: v2\ndeps: []\n")
        after = policy_inventory(self.root)
        self.assertEqual(after["buf.lock"], file_hash(self.root / "buf.lock"))
        self.assertNotEqual(before, after)
    def index(self, change):
        path = self.root / self.spec["contract_index_path"]
        metadata = json.loads(path.read_bytes())
        change(metadata["contract_index"])
        path.write_bytes((json.dumps(metadata) + "\n").encode("utf-8"))

    def consumer(self):
        module = copy.deepcopy(self.spec["modules"][0])
        module.update(id="M2",owns_paths=["aux/"],provided_services=[],consumed_operations=["fixture.v1.FixtureService.Preserve"])
        self.spec["modules"].append(module)
        element = copy.deepcopy(self.spec["solution_elements"][0])
        element.update(id="E-AUX",module="M2")
        self.spec["solution_elements"].append(element)
        self.spec["scenarios"][0]["solution_elements"].append("E-AUX")
        self.declare_path("aux/", owner="E-AUX", kind="directory", disposition="retain")
        return module

    def test_valid_spec_keeps_qualification_and_real_acceptance_separate(self):
        self.assertEqual(self.vs()["modules"],1)
        self.assertEqual(boundary_check_ids(self.spec,"qualification"),["contract"])
        self.assertEqual(boundary_check_ids(self.spec,"implementation"),["behavior","boundary"])
        with self.assertRaisesRegex(RddError,"Unknown boundary"):
            boundary_check_ids(self.spec,"anything")

    def test_malformed_generated_index_is_a_structured_validation_failure(self):
        self.index(lambda index:index.update(services=[None]))
        try:
            self.vs()
        except Exception as error:
            self.assertIsInstance(error,RddError,"untrusted generated metadata must not crash the controller")
        else:
            self.fail("malformed generated metadata was accepted")

    def test_missing_or_unknown_public_service_cannot_claim_boundary(self):
        for services, pattern in (([],"no provided or consumed"),(["unknown.v1.Service"],"unknown references")):
            self.spec["modules"][0]["provided_services"] = services
            with self.subTest(services=services), self.assertRaisesRegex(RddError,pattern):
                self.vs()

    def test_consumer_cannot_bypass_declared_dependency_direction(self):
        module = self.consumer()
        with self.assertRaisesRegex(RddError,"against dependency direction"):
            self.vs()
        module["depends_on"] = ["M1"]
        self.assertEqual(self.vs()["modules"],2)

    def test_duplicate_provider_is_rejected(self):
        module = self.consumer()
        module["provided_services"] = ["fixture.v1.FixtureService"]
        with self.assertRaisesRegex(RddError,"duplicate module providers"):
            self.vs()

    def test_future_real_adapter_check_cannot_be_prefreeze_qualification(self):
        self.spec["modules"][0]["implementation_checks"]["provider"] = ["contract"]
        with self.assertRaisesRegex(RddError,"cannot run as prefreeze"):
            self.vs()

    def test_qualification_check_must_be_in_frozen_contract_proofs(self):
        self.spec["modules"][0]["qualification_checks"]["provider"] = ["boundary"]
        with self.assertRaisesRegex(RddError,"qualification proofs must have kind contract"):
            self.vs()

    def test_every_approved_operation_needs_a_real_response_outcome_oneof(self):
        self.index(lambda index:index["services"][0]["operations"][0].update(response_oneofs=[]))
        with self.assertRaisesRegex(RddError,"schema outcome oneof"):
            self.vs()

    def test_index_rejects_stale_proto_bytes(self):
        source = self.root / self.spec["contract_files"][0]
        source.write_bytes(source.read_bytes()+b"\n// Changed contract bytes.\n")
        with self.assertRaisesRegex(RddError,"index is stale"):
            self.vs()

    def test_public_operation_surface_has_no_orphan_symbols(self):
        def add(index):
            operation = copy.deepcopy(index["services"][0]["operations"][0])
            operation["symbol"] = "fixture.v1.FixtureService.Orphan"
            index["services"][0]["operations"].append(operation)
        self.index(add)
        with self.assertRaisesRegex(RddError,"lack solution mappings"):
            self.vs()

    def test_non_operation_cannot_smuggle_public_symbols(self):
        self.spec["solution_elements"][0]["contract_operations"] = ["fixture.v1.FixtureService.Preserve"]
        with self.assertRaisesRegex(RddError,"Non-operation.*cannot declare"):
            self.vs()

    def test_generated_support_has_explicit_accounting(self):
        self.spec["shared_generated_files"] = []
        with self.assertRaisesRegex(RddError,"Shared generated support inventory"):
            self.vs()

    def test_module_cannot_claim_unrelated_binding_to_close_inventory(self):
        self.write("contracts/unrelated.proto", 'syntax = "proto3";\npackage unrelated.v1;\nmessage Unrelated {}\n')
        self.write("gen/unrelated.rs","// Generated unrelated fixture type.\n")
        self.spec["contract_files"].append("contracts/unrelated.proto")
        self.spec["generated_files"].append("gen/unrelated.rs")
        self.spec["modules"][0]["generated_paths"].append("gen/unrelated.rs")
        def add(index):
            index["source_hashes"]["contracts/unrelated.proto"] = file_hash(self.root / "contracts/unrelated.proto")
            index["binding_files"].append("gen/unrelated.rs")
            index["binding_sources"]["gen/unrelated.rs"] = ["contracts/unrelated.proto"]
        self.index(add)
        with self.assertRaisesRegex(RddError,"generated binding ownership differs"):
            self.vs()

    def test_module_requires_generated_binding_ownership(self):
        self.spec["modules"][0].pop("generated_paths")
        with self.assertRaisesRegex(RddError, "generated_paths|required"):
            self.vs()

    def test_operation_requires_descriptor_symbol_mapping(self):
        self.spec["solution_elements"][1].pop("contract_operations")
        with self.assertRaisesRegex(RddError, "contract_operations|required"):
            self.vs()

    def test_module_subdomains_cover_all_its_functional_requirements(self):
        self.write("requirements/requirements.md", (self.root / "requirements/requirements.md").read_text(encoding="utf-8")
            + "\n**FR-002 Preserve a second value**\nThe fixture shall preserve a second value.\nAcceptance: Read the value.\n")
        self.reqs = requirements(self.root, "requirements/requirements.md")
        self.spec["requirements_digest"] = self.reqs["digest"]
        self.spec["modules"][0]["requirements"].append("FR-002")
        module = copy.deepcopy(self.spec["modules"][0])
        module.update(id="M2", requirements=["FR-002"], owns_paths=["aux/"])
        self.spec["modules"].append(module)
        element = copy.deepcopy(self.spec["solution_elements"][0])
        element.update(id="E-AUX", module="M2", requirements=["FR-002"], scenarios=["S2"])
        self.spec["solution_elements"].append(element)
        scenario = copy.deepcopy(self.spec["scenarios"][0])
        scenario.update(id="S2", requirements=["FR-002"], solution_elements=["E-AUX"])
        self.spec["scenarios"].append(scenario)
        self.spec["checks"][1]["scenario_ids"].append("S2")
        self.spec["requirement_map"].append(dict(requirement="FR-002", specifications=self.spec["documents"], scenarios=["S2"]))
        self.declare_path("aux/", owner="E-AUX", kind="directory", disposition="retain")
        with self.assertRaisesRegex(RddError, "Module M1.*subdomain.*FR-002"):
            self.vs()
