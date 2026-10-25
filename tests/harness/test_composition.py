"""Composition edges qualify wiring while preserving generated business boundaries."""
import copy
import unittest

from test_composition_plan import CompositionFixture
from tools.rdd import artifacts
from tools.rdd.common import RddError, read_json, validate

SOURCE = "docs/specs/solution.md"


class CompositionSpecificationTests(CompositionFixture):
    def bindings(self):
        self.save_inventory()
        artifacts.boundary_bindings_validate(self.root, self.spec, self.modules, self.elements, self.services,
            self.operations, self.types, self.service_owners, {"fixture.items.State": "items"}, {SOURCE})

    def contracts(self):
        self.save_inventory()
        artifacts.module_contracts_validate(self.root, self.spec, self.modules, self.elements, self.checks, {SOURCE})

    def test_composition_schema_and_lifecycle_owner_are_accepted(self):
        schema = read_json(self.root / ".rdd/schemas/spec.schema.json")
        validate(self.spec["boundary_bindings"], schema["properties"]["boundary_bindings"], schema)
        self.assertEqual(artifacts.domain_inventory_validate(self.root, self.reqs), self.inventory)
        artifacts.domain_solution_validate(self.root, self.spec, self.modules, self.elements)
        self.contracts()

    def test_composition_rejects_bad_owners_behavior_disguise_and_cycles(self):
        for change in ("domain", "adapter", "infrastructure", "presentation", "shared_types", "build", "no_lifecycle", "behavior", "cycle"):
            inventory = copy.deepcopy(self.inventory)
            if change == "domain":
                self.inventory["interactions"][0].update(consumer="items", provider="app")
            elif change in {"adapter", "infrastructure", "presentation", "shared_types", "build"}:
                self.inventory["supporting_modules"][0]["kind"] = change
            elif change == "no_lifecycle":
                self.inventory["supporting_modules"][0]["behaviors"] = []
            elif change == "behavior":
                self.inventory["interactions"][0]["behaviors"] = ["B-STATE"]
            else:
                self.inventory["interactions"].append(dict(id="I-BACK", consumer="items", provider="app",
                    kind="type_only", requirements=["FR-001"], behaviors=[]))
            with self.subTest(change=change), self.assertRaises(RddError):
                artifacts.domain_inventory_validate(self.root, self.reqs, self.inventory)
            self.inventory = inventory
        for kind, behavior in (("operation", "positive"), ("enabling", "positive")):
            self.elements["B-INIT"].update(kind=kind, behavior=behavior)
            with self.subTest(kind=kind), self.assertRaisesRegex(RddError, "lifecycle"):
                artifacts.domain_solution_validate(self.root, self.spec, self.modules, self.elements)

    def test_composition_exports_are_nonempty_owned_rust_wiring_of_real_interfaces(self):
        for change in ("empty", "hidden", "business", "descriptor", "path", "foreign_path", "spec", "empty_specs", "no_interface", "call", "type"):
            modules, bindings = copy.deepcopy(self.modules), copy.deepcopy(self.spec["boundary_bindings"])
            entry = next(entry for entry in self.modules["items"]["public_exports"] if entry["kind"] == "construction")
            if change in {"empty", "hidden"}:
                self.spec["boundary_bindings"][0]["exports"] = [] if change == "empty" else ["items::private"]
            elif change == "business":
                entry["kind"] = "operation"
            elif change == "descriptor":
                entry["binding"] = "fixture.items.State"
            elif change in {"path", "foreign_path"}:
                entry["path"] = "modules/items.txt" if change == "path" else "modules/app.rs"
                if change == "path":
                    self.modules["items"]["owns_paths"] = [entry["path"]]
            elif change in {"spec", "empty_specs"}:
                entry["specifications"] = ["docs/unfrozen.md"] if change == "spec" else []
            elif change == "no_interface":
                self.modules["items"]["provided_types"] = []
            else:
                self.spec["boundary_bindings"][0]["operations" if change == "call" else "types"] = ["fixture.items.State"]
            with self.subTest(change=change), self.assertRaises(RddError):
                self.bindings()
            self.modules, self.spec["boundary_bindings"] = modules, bindings
        self.bindings()
        self.modules["app"]["depends_on"] = []
        with self.assertRaisesRegex(RddError, "dependency inventory"):
            self.bindings()

    def test_composition_requires_both_proof_roles_without_dummy_signature_checks(self):
        self.contracts()
        for mid, group in (("app", "consumer"), ("items", "provider"), ("app", "dependency_direction"),
                           ("items", "compatibility"), ("app", "semantics")):
            for stage in ("qualification", "implementation"):
                if group not in self.modules[mid][f"{stage}_checks"]:
                    continue
                proof = self.modules[mid][f"{stage}_checks"].pop(group)
                self.modules[mid][f"{stage}_checks"][group] = []
                with self.subTest(module=mid, group=group, stage=stage), self.assertRaisesRegex(RddError, "actual boundary role"):
                    self.contracts()
                self.modules[mid][f"{stage}_checks"][group] = proof
        self.modules["app"]["qualification_checks"]["negative_signature"] = ["C-CONTRACTS"]
        with self.assertRaisesRegex(RddError, "actual boundary role"):
            self.contracts()

    def test_genuine_type_only_edges_remain_generated_and_exclusive(self):
        self.inventory["interactions"][0]["kind"] = "type_only"
        self.modules["app"].update(consumed_types=["fixture.items.State"])
        self.spec["boundary_bindings"][0].update(types=["fixture.items.State"], exports=[])
        self.bindings()
        self.spec["boundary_bindings"][0]["exports"] = ["items::build"]
        with self.assertRaisesRegex(RddError, "Type-only"):
            self.bindings()

    def test_genuine_call_keeps_descriptor_behavior_and_provider_mapping(self):
        operation = "fixture.items.Items.Read"
        self.services["fixture.items.Items"] = {}
        self.operations[operation] = ("fixture.items.Items", {})
        self.service_owners["fixture.items.Items"] = "items"
        self.modules["items"]["provided_services"] = ["fixture.items.Items"]
        self.modules["app"]["consumed_operations"] = [operation]
        self.elements["B-STATE"].update(kind="operation", contract_operations=[operation])
        self.inventory["interactions"].append(dict(id="I-READ", consumer="app", provider="items", kind="call",
            requirements=["FR-001"], behaviors=["B-STATE"]))
        binding = dict(interaction="I-READ", operations=[operation], types=[])
        self.spec["boundary_bindings"].append(binding)
        self.bindings()
        binding["exports"] = ["items::build"]
        with self.assertRaisesRegex(RddError, "Callable"):
            self.bindings()
        binding.pop("exports")
        self.service_owners["fixture.items.Items"] = "app"
        with self.assertRaisesRegex(RddError, "wrong operation provider"):
            self.bindings()


if __name__ == "__main__":
    unittest.main()
