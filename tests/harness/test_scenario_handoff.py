"""S1 allocations constrain the scenario handoff before S6 reconciliation."""
import copy
from contextlib import nullcontext
import unittest

from test_refinement import HarnessTestCase
from tools.rdd import artifacts
from tools.rdd.common import RddError, file_hash, write_json


SCENARIOS = "docs/specs/scenarios.json"


class ScenarioHandoffTests(HarnessTestCase):
    def test_arbitrary_nonempty_s3_artifact_is_rejected_before_handoff(self):
        f, c = self.fixture, self.fixture.controller
        c.spec_init()
        f.commit()
        f.observe()
        for node, path in (("S0", "docs/specs/intake.md"), ("S1", artifacts.DOMAIN_INVENTORY_PATH)):
            f.claim(node, [path])
            if node == "S1":
                write_json(self.root / path, f.domain_inventory())
            else:
                f.text(path, "Intake source is present.\n")
            f.record(node)
            f.observe()
        f.claim("S3", [SCENARIOS])
        f.text(SCENARIOS, "Arbitrary nonempty output has no scenarios or assertions.\n")
        before = c.state()
        with self.assertRaises(RddError):
            f.record("S3")
        self.assertEqual(c.state(), before)

    def test_s6_cannot_change_accepted_s1_allocations_or_polarity(self):
        reqs, inventory, rows = self.trace_fixture()
        elements = artifacts.inventory_elements(inventory)
        spec = dict(requirements_digest=reqs["digest"], requirement_map=[dict(requirement=rid) for rid in reqs["records"]],
                    domain_inventory=dict(path=artifacts.DOMAIN_INVENTORY_PATH, sha256=file_hash(self.root / artifacts.DOMAIN_INVENTORY_PATH)))
        modules = {"items": dict(requirements=inventory["domains"][0]["requirements"])}
        for element in elements.values():
            if element["kind"] == "behavior":
                element["kind"] = "enabling"
        artifacts.domain_solution_validate(self.root, spec, modules, elements)
        for field, value in (("behavior", "negative"), ("requirements", ["FR-005"])):
            changed = copy.deepcopy(elements)
            changed["W_BEGIN_EDIT"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(RddError, "allocation or polarity"):
                artifacts.domain_solution_validate(self.root, spec, modules, changed)

    def trace_fixture(self):
        """Small independent oracle for the eight audited mismatching edges."""
        assertions = {
            "FR-002": ("G-SNAPSHOT", "Read an immutable committed snapshot"),
            "FR-004": ("G-CREATE", "Create an accepted task"),
            "FR-005": ("G-FR005-EDIT", "Save changes to an already selected task"),
            "FR-006": ("G-DRAFT", "Protect unsubmitted text and establish the edit baseline"),
            "FR-010": ("G-QUERY", "Display the defined default query"),
            "FR-017": ("G-FR017-REJECTED", "Retain the draft after a rejected submitted mutation"),
            "FR-018": ("G-FR018-CLOSE", "Close with submitted pending or uncertain work"),
            "FR-019": ("G-FR019-EXPORT", "Write an export to a new destination file"),
            "FR-020": ("G-OVERWRITE", "Cancel and confirm overwriting an existing destination"),
            "FR-021": ("G-EMPTY", "Validate a complete empty restore candidate"),
            "FR-023": ("G-FR023-RESTORE", "Restore the validated snapshot and reconcile state"),
            "FR-025": ("G-FR025-HELP", "Display local help while retaining the current window state")}
        reqs = dict(digest="a" * 64, records={rid: {} for rid in list(assertions) + ["NFR-PERF-002", "NFR-QUAL-002"]})
        inventory = self.fixture.domain_inventory()
        inventory["requirements_digest"] = reqs["digest"]
        owner = inventory["domains"][0]
        owner["requirements"] = list(assertions)
        owner["behaviors"] = [dict(id=eid, requirements=allocated, behavior="positive") for eid, allocated in (
            ("C_SNAPSHOT", ["FR-002", "FR-023"]), ("Q_DEFAULT", ["FR-010"]),
            ("W_BEGIN_EDIT", ["FR-006"]), ("W_EXPORT_INTENT", ["FR-020"]))]
        owner["invariants"] = [dict(id="I_DRAFT_PROTECTION", requirements=["FR-006"], behavior="positive")]
        elements = artifacts.inventory_elements(inventory)
        rows = []
        for rid, (sid, assertion) in assertions.items():
            rows.append(dict(self.fixture.scenarios()[0], id=sid, requirements=[rid], description=assertion,
                expected=assertion, solution_elements=[eid for eid, row in elements.items() if rid in row["requirements"]]))
        for sid, extra in (("G-FR017-REJECTED", ["FR-004"]),
                           ("G-FR023-RESTORE", ["FR-019", "FR-021"]),
                           ("G-FR025-HELP", ["NFR-QUAL-002"])):
            next(row for row in rows if row["id"] == sid)["requirements"].extend(extra)
        rows.append(dict(rows[0], id="M-P1", kind="benchmark", requirements=["FR-002", "NFR-PERF-002"],
                         expected="Measure default data load at the prescribed workload"))
        write_json(self.root / artifacts.DOMAIN_INVENTORY_PATH, inventory)
        write_json(self.root / SCENARIOS, rows)
        return reqs, inventory, rows

    def test_each_of_eight_audited_edges_requires_requirement_intersection(self):
        reqs, inventory, rows = self.trace_fixture()
        artifacts.scenario_handoff_validate(self.root, reqs)
        edges = (("C_SNAPSHOT", "G-FR019-EXPORT"), ("Q_DEFAULT", "G-FR023-RESTORE"), ("Q_DEFAULT", "M-P1"),
                 ("W_BEGIN_EDIT", "G-FR005-EDIT"), ("W_EXPORT_INTENT", "G-FR019-EXPORT"),
                 ("I_DRAFT_PROTECTION", "G-FR017-REJECTED"), ("I_DRAFT_PROTECTION", "G-FR018-CLOSE"),
                 ("I_DRAFT_PROTECTION", "G-FR025-HELP"))
        for eid, sid in edges:
            broken = copy.deepcopy(rows)
            next(row for row in broken if row["id"] == sid)["solution_elements"].append(eid)
            write_json(self.root / SCENARIOS, broken)
            with self.subTest(element=eid, scenario=sid), self.assertRaisesRegex(RddError, "no shared requirement"):
                artifacts.scenario_handoff_validate(self.root, reqs)

    def test_s3_schema_identity_and_coverage_failures_preserve_the_oracle(self):
        reqs, inventory, rows = self.trace_fixture()
        restore = next(i for i, row in enumerate(rows) if row["id"] == "G-FR023-RESTORE")
        changes = {
            "unknown_requirement": lambda rows: rows[0]["requirements"].append("FR-UNKNOWN"),
            "unknown_element": lambda rows: rows[0]["solution_elements"].append("UNOWNED"),
            "duplicate_id": lambda rows: rows.append(copy.deepcopy(rows[0])),
            "duplicate_reference": lambda rows: rows[0]["solution_elements"].append(rows[0]["solution_elements"][0]),
            "nfr_golden": lambda rows: rows.append(dict(rows[0], id="G-NFR", requirements=["NFR-PERF-002"])),
            "missing_assertion": lambda rows: rows[0].pop("verification_method"),
            "union_gap": lambda rows: rows[restore]["solution_elements"].remove("C_SNAPSHOT"),
            "missing_positive_fr": lambda rows: rows.append(dict(rows[restore], id="N-SNAPSHOT", kind="negative",
                                                                  solution_elements=["C_SNAPSHOT"]))}
        for change, mutate in changes.items():
            broken = copy.deepcopy(rows)
            if change == "missing_positive_fr":
                changes["union_gap"](broken)
            mutate(broken)
            write_json(self.root / SCENARIOS, broken)
            with self.subTest(change=change), self.assertRaises(RddError):
                artifacts.scenario_handoff_validate(self.root, reqs)
        (self.root / SCENARIOS).unlink()
        with self.assertRaises(RddError):
            artifacts.scenario_handoff_validate(self.root, reqs)

    def test_positive_allocations_need_linked_golden_and_union_coverage(self):
        reqs, inventory, rows = self.trace_fixture()
        nfr, extra = "NFR-PERF-002", "NFR-QUAL-002"
        cases = ((["FR-019", "FR-023"], ["FR-019"], ["FR-023"], "positive", "missing golden"),
                 (["FR-021", "FR-025"], ["FR-025"], [], "positive", "missing requirement"),
                 ([nfr], [], [nfr], "positive", "missing golden"),
                 ([nfr, extra], ["FR-019", nfr], [extra], "positive", None),
                 (["FR-019", nfr], ["FR-019"], [nfr], "positive", None),
                 ([nfr], [], [nfr], "negative", None),
                 ([nfr], [], [nfr], "support", None),
                 (["FR-019"], [], ["FR-019"], "negative", None),
                 (["FR-019"], [], ["FR-019"], "support", None))
        for allocated, golden, other, behavior, expected in cases:
            changed, scenarios = copy.deepcopy(inventory), copy.deepcopy(rows)
            changed["supporting_modules"] = [dict(id="UI", module="ui", kind="presentation", requirements=allocated,
                behaviors=[dict(id="UI.Accessible", requirements=allocated, behavior=behavior)])]
            for kind, requirements in (("golden", golden), ("benchmark", other)):
                if requirements:
                    scenarios.append(dict(rows[0], id="UI-" + kind, kind=kind, requirements=requirements,
                                          solution_elements=["UI", "UI.Accessible"]))
            write_json(self.root / artifacts.DOMAIN_INVENTORY_PATH, changed)
            write_json(self.root / SCENARIOS, scenarios)
            expectation = self.assertRaisesRegex(RddError, expected) if expected else nullcontext()
            with self.subTest(allocated=allocated, golden=golden, behavior=behavior), expectation:
                artifacts.scenario_handoff_validate(self.root, reqs)

    def test_s1_rejects_unknown_duplicate_and_out_of_owner_row_allocations(self):
        reqs, inventory, rows = self.trace_fixture()
        changes = {"unknown": lambda value: value["domains"][0]["behaviors"][0].update(requirements=["FR-UNKNOWN"]),
                   "out_of_owner": lambda value: value["domains"][0]["behaviors"][0].update(requirements=["NFR-PERF-002"]),
                   "duplicate": lambda value: value["domains"][0]["invariants"][0].update(id=value["domains"][0]["behaviors"][0]["id"]),
                   "old_schema": lambda value: value.update(schema_version=1)}
        for change, mutate in changes.items():
            broken = copy.deepcopy(inventory)
            mutate(broken)
            with self.subTest(change=change), self.assertRaises(RddError):
                artifacts.domain_inventory_validate(self.root, reqs, broken)

    def test_s6_preserves_allocations_reciprocity_and_all_accepted_scenario_fields(self):
        f, c = self.fixture, self.fixture.controller
        rows = f.scenarios()
        rows.append(dict(rows[0], id="N01", kind="negative", solution_elements=["D-ITEMS"]))
        f.begin_s6(scenarios=rows)
        c.spec_snapshot("author-S6")
        original = c.spec()
        c.spec_validate()
        for field in original["scenarios"][0]:
            spec = copy.deepcopy(original)
            value = spec["scenarios"][0][field]
            spec["scenarios"][0][field] = value + ["UNACCEPTED"] if isinstance(value, list) else value + " changed"
            write_json(self.root / ".rdd/spec.json", spec)
            with self.subTest(field=field), self.assertRaises(RddError):
                c.spec_validate()
        for eid in ("D-ITEMS", "B-STATE", "I-ORDER"):
            spec = copy.deepcopy(original)
            next(row for row in spec["solution_elements"] if row["id"] == eid)["scenarios"] = ["G01"] if eid == "D-ITEMS" else ["N01"]
            write_json(self.root / ".rdd/spec.json", spec)
            with self.subTest(reverse=eid), self.assertRaisesRegex(RddError, "reverse scenario"):
                c.spec_validate()
        records = c._node_records(c.state())
        changes = {"hash": lambda state, spec: state["S3"]["outputs"].update({SCENARIOS: "b" * 64}),
                   "digest": lambda state, spec: state["S3"].update(output_digest="b" * 64),
                   "document": lambda state, spec: spec["documents"].remove(SCENARIOS)}
        for change, mutate in changes.items():
            state, spec = copy.deepcopy(records), copy.deepcopy(original)
            mutate(state, spec)
            with self.subTest(provenance=change), self.assertRaises(RddError):
                artifacts.validate_accepted_domain_inventory(self.root, spec, state)
        changes = {"extra": lambda spec: spec["scenarios"].append(dict(spec["scenarios"][0], id="NEW-S6")),
                   "missing": lambda spec: spec["scenarios"].pop(),
                   "row": lambda spec: spec["scenarios"][0].update(expected="A different independently plausible result")}
        for change, mutate in changes.items():
            spec = copy.deepcopy(original)
            mutate(spec)
            with self.subTest(stateless=change), self.assertRaisesRegex(RddError, "accepted S3 scenario catalog"):
                artifacts.spec_validate(self.root, spec, artifacts.requirements(self.root, "requirements/requirements.md"), c.config)
        nfr = "NFR-UI-001"
        spec = copy.deepcopy(original)
        spec["solution_elements"].append(dict(id="UI.Accessible", module=None, kind="enabling", behavior="positive",
            requirements=[nfr], scenarios=["A01"], specifications=[]))
        spec["scenarios"].append(dict(rows[0], id="A01", kind="accessibility", requirements=[nfr],
                                     solution_elements=["UI.Accessible"]))
        checks = artifacts.unique(spec["checks"], "check")
        checks["C-APP"]["scenario_ids"].append("A01")
        with self.assertRaisesRegex(RddError, "Positive enabling UI.Accessible: missing golden"):
            artifacts.solution_validate(self.root, spec, {"FR-001", nfr}, artifacts.unique(spec["modules"], "module"),
                artifacts.unique(spec["scenarios"], "scenario"), checks, spec["documents"])
        spec["scenarios"][0]["solution_elements"].append("UI.Accessible")
        spec["scenarios"][0]["requirements"].append(nfr)
        spec["solution_elements"][-1]["scenarios"].append("G01")
        artifacts.solution_validate(self.root, spec, {"FR-001", nfr}, artifacts.unique(spec["modules"], "module"),
            artifacts.unique(spec["scenarios"], "scenario"), checks, spec["documents"])

    def test_s3_is_the_sole_owner_of_the_required_scenario_artifact(self):
        c = self.fixture.controller
        for node in ("S0", "S1", "S2", "S4", "S5", "S6", "S7"):
            with self.subTest(node=node), self.assertRaisesRegex(RddError, "Only S3"):
                c._validate_node_writes(node, [SCENARIOS])
        with self.assertRaisesRegex(RddError, "S3 must claim"):
            c._validate_node_writes("S3", ["docs/specs/arbitrary.md"])
        c._validate_node_writes("S3", [SCENARIOS])


if __name__ == "__main__":
    unittest.main()
