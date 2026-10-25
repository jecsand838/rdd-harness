"""S1 allocations constrain the scenario handoff before S6 reconciliation."""
import copy
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

    def test_s6_cannot_change_accepted_s1_polarity(self):
        f = self.fixture
        f.begin_s6()
        spec = f.controller.spec()
        spec["solution_elements"][1]["behavior"] = "negative"
        with self.assertRaises(RddError):
            artifacts.domain_solution_validate(self.root, spec, artifacts.unique(spec["modules"], "module"),
                artifacts.unique(spec["solution_elements"], "element"))

    def trace_fixture(self):
        """Small independent oracle for the eight audited mismatching edges."""
        requirements = ["FR-002", "FR-004", "FR-005", "FR-006", "FR-010", "FR-017", "FR-018",
                        "FR-019", "FR-020", "FR-021", "FR-023", "FR-025"]
        reqs = dict(digest="a" * 64, records={rid: {} for rid in requirements + ["NFR-PERF-002", "NFR-QUAL-002"]})
        inventory = self.fixture.domain_inventory()
        inventory["requirements_digest"] = reqs["digest"]
        owner = inventory["domains"][0]
        owner["requirements"] = requirements
        owner["behaviors"] = [dict(id=eid, requirements=allocated, behavior="positive") for eid, allocated in (
            ("C_SNAPSHOT", ["FR-002", "FR-023"]), ("Q_DEFAULT", ["FR-010"]),
            ("W_BEGIN_EDIT", ["FR-006"]), ("W_EXPORT_INTENT", ["FR-020"]))]
        owner["invariants"] = [dict(id="I_DRAFT_PROTECTION", requirements=["FR-006"], behavior="positive")]
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
        # Genuine multi-requirement coverage intersects each linked row and remains valid.
        write_json(self.root / SCENARIOS, rows)
        artifacts.scenario_handoff_validate(self.root, reqs)

    def test_s3_schema_identity_and_coverage_failures_preserve_the_oracle(self):
        reqs, inventory, rows = self.trace_fixture()
        for change in ("unknown_requirement", "unknown_element", "duplicate_id", "duplicate_reference", "nfr_golden",
                       "missing_assertion", "missing_positive_fr", "union_gap"):
            broken = copy.deepcopy(rows)
            if change == "unknown_requirement":
                broken[0]["requirements"].append("FR-UNKNOWN")
            elif change == "unknown_element":
                broken[0]["solution_elements"].append("UNOWNED")
            elif change == "duplicate_id":
                broken.append(copy.deepcopy(broken[0]))
            elif change == "duplicate_reference":
                broken[0]["solution_elements"].append(broken[0]["solution_elements"][0])
            elif change == "nfr_golden":
                broken.append(dict(broken[0], id="G-NFR", requirements=["NFR-PERF-002"]))
            elif change == "missing_assertion":
                del broken[0]["verification_method"]
            else:
                restore = next(row for row in broken if row["id"] == "G-FR023-RESTORE")
                restore["solution_elements"].remove("C_SNAPSHOT")
                if change == "missing_positive_fr":
                    broken.append(dict(restore, id="N-SNAPSHOT", kind="negative", solution_elements=["C_SNAPSHOT"]))
            write_json(self.root / SCENARIOS, broken)
            with self.subTest(change=change), self.assertRaises(RddError):
                artifacts.scenario_handoff_validate(self.root, reqs)
        for row in rows:
            row["solution_elements"] = [eid for eid in row["solution_elements"] if eid != "C_SNAPSHOT"]
        rows.append(dict(rows[0], id="N-SNAPSHOT", kind="negative", requirements=["FR-002", "FR-023"],
                         solution_elements=["C_SNAPSHOT"]))
        write_json(self.root / SCENARIOS, rows)
        owner = inventory["domains"][0]
        for behavior in ("negative", "support"):
            owner["behaviors"][0]["behavior"] = behavior
            write_json(self.root / artifacts.DOMAIN_INVENTORY_PATH, inventory)
            artifacts.scenario_handoff_validate(self.root, reqs)
        (self.root / SCENARIOS).unlink()
        with self.assertRaises(RddError):
            artifacts.scenario_handoff_validate(self.root, reqs)

    def test_first_wave_positive_allocations_need_union_and_golden_coverage(self):
        reqs, inventory, rows = self.trace_fixture()
        for eid, allocated, kind, expected in (("C_VALIDATE", ["FR-019", "FR-023"], "negative", "missing golden"),
                                              ("B_EMPTY", ["FR-021", "FR-025"], None, "missing requirement")):
            changed = copy.deepcopy(inventory)
            changed["domains"][0]["behaviors"].append(dict(id=eid, requirements=allocated, behavior="positive"))
            scenarios = copy.deepcopy(rows)
            next(row for row in scenarios if allocated[0 if eid == "C_VALIDATE" else 1] in row["requirements"])["solution_elements"].append(eid)
            if kind:
                scenarios.append(dict(rows[0], id="N-VALIDATE", kind=kind, requirements=["FR-023"], solution_elements=[eid]))
            write_json(self.root / artifacts.DOMAIN_INVENTORY_PATH, changed)
            write_json(self.root / SCENARIOS, scenarios)
            with self.subTest(element=eid), self.assertRaisesRegex(RddError, expected):
                artifacts.scenario_handoff_validate(self.root, reqs)

    def test_s1_rejects_unknown_duplicate_and_out_of_owner_row_allocations(self):
        reqs, inventory, rows = self.trace_fixture()
        for change in ("unknown", "out_of_owner", "duplicate", "old_schema"):
            broken = copy.deepcopy(inventory)
            owner = broken["domains"][0]
            if change in {"unknown", "out_of_owner"}:
                owner["behaviors"][0]["requirements"] = ["FR-UNKNOWN" if change == "unknown" else "NFR-PERF-002"]
            elif change == "duplicate":
                owner["invariants"][0]["id"] = owner["behaviors"][0]["id"]
            else:
                broken["schema_version"] = 1
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
        write_json(self.root / ".rdd/spec.json", original)
        for eid in ("D-ITEMS", "B-STATE", "I-ORDER"):
            spec = copy.deepcopy(original)
            next(row for row in spec["solution_elements"] if row["id"] == eid)["scenarios"] = ["G01"] if eid == "D-ITEMS" else ["N01"]
            write_json(self.root / ".rdd/spec.json", spec)
            with self.subTest(reverse=eid), self.assertRaisesRegex(RddError, "reverse scenario"):
                c.spec_validate()
        write_json(self.root / ".rdd/spec.json", original)
        records = c._node_records(c.state())
        for change in ("hash", "digest", "document"):
            state, spec = copy.deepcopy(records), copy.deepcopy(original)
            if change == "hash":
                state["S3"]["outputs"][SCENARIOS] = "b" * 64
            elif change == "digest":
                state["S3"]["output_digest"] = "b" * 64
            elif change == "document":
                spec["documents"].remove(SCENARIOS)
            with self.subTest(provenance=change), self.assertRaises(RddError):
                artifacts.validate_accepted_domain_inventory(self.root, spec, state)
        for change in ("extra", "missing", "row"):
            spec = copy.deepcopy(original)
            if change == "extra":
                spec["scenarios"].append(dict(spec["scenarios"][0], id="NEW-S6"))
            elif change == "missing":
                spec["scenarios"].pop()
            else:
                spec["scenarios"][0]["expected"] = "A different independently plausible result"
            with self.subTest(stateless=change), self.assertRaisesRegex(RddError, "accepted S3 scenario catalog"):
                artifacts.spec_validate(self.root, spec, artifacts.requirements(self.root, "requirements/requirements.md"), c.config)
        reqs, inventory, rows = self.trace_fixture()
        elements = artifacts.inventory_elements(inventory)
        spec = dict(requirements_digest=reqs["digest"], requirement_map=[dict(requirement=rid) for rid in reqs["records"]],
                    domain_inventory=dict(path=artifacts.DOMAIN_INVENTORY_PATH, sha256=file_hash(self.root / artifacts.DOMAIN_INVENTORY_PATH)))
        modules = {"items": dict(requirements=inventory["domains"][0]["requirements"])}
        elements["W_BEGIN_EDIT"]["kind"] = "enabling"
        elements["C_SNAPSHOT"]["kind"] = elements["Q_DEFAULT"]["kind"] = elements["W_EXPORT_INTENT"]["kind"] = "enabling"
        artifacts.domain_solution_validate(self.root, spec, modules, elements)
        elements["W_BEGIN_EDIT"]["requirements"] = ["FR-005"]
        with self.assertRaisesRegex(RddError, "allocation or polarity"):
            artifacts.domain_solution_validate(self.root, spec, modules, elements)

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
