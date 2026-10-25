"""Specification/preparation regressions; all fixtures are disposable repositories."""
import copy
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from test_refinement import REPOSITORY, build_fixture
from tools.rdd import artifacts
from tools.rdd.common import RddError, write_json
from tools.rdd.nodes import NODES
from tools.rdd.readiness import validate_boundary_plan


def plan_for(spec):
    task = dict(id="T001", title="Implement items", objective="Preserve insertion order", phase="P01",
        category="addition", requirements=["FR-001"], specifications=["docs/specs/solution.md"],
        depends_on=[], writes=["modules/items.rs"], checks=["C-APP"], acceptance=["Ordered items"],
        scope="small", reuse=dict(capability_missing="Collection owner", candidates=[dict(path="modules/", reason="Absent")],
            why_not_extend="No implementation exists", duplication_check="No collection owner exists"),
        solution_elements=[e["id"] for e in spec["solution_elements"]], scenarios=["G01"], requires=[], produces=[], bootstrap_resources=[],
        sites=[dict(id="A01", path="modules/items.rs", mode="inline", primary=True,
                    placement=dict(kind="append", context=None), instructions="Implement the invariant owner")])
    return dict(schema_version=3, spec_digest="a" * 64, author_sessions=["planner"], tasks=[task],
        phases=[dict(id="P01", goal="Ordered items", tasks=["T001"], checks=["C-APP"], requirements_closed=["FR-001"],
                     deliverables=["modules/items.rs"], independent_evidence=["Verify inserted item order"])],
        verticals=[dict(id="V01", goal="Ordered items", tasks=["T001"])], target_paths=["modules/items.rs"],
        shells=[dict(path="modules/items.rs", content="// Collection owner\n")],
        element_coverage=[dict(element=e["id"], tasks=["T001"], checks=["C-APP"], baseline_evidence=None)
                          for e in spec["solution_elements"]], resource_producers=[], resource_uses=[], boundary_proofs=[], type_import_proofs=[])


class SpecificationPreparationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.fixture = build_fixture(self.root)
        self.addCleanup(self.fixture.controller.close)

    def cli_status(self, *arguments):
        result = subprocess.run([sys.executable, str(REPOSITORY / "tools/rdd/cli.py"),
            "--root", str(self.root), "status", *arguments], capture_output=True, text=True)
        self.assertTrue(result.stdout, result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_status_without_locator_is_read_only_but_invalid_locator_still_fails(self):
        locator = self.root / ".rdd/run.json"
        for contents, code in ((None, 0), ("{invalid", 1), ('{"run_id": null}', 0)):
            if contents is None:
                locator.unlink()
            else:
                locator.write_text(contents)
            before = {p: p.read_bytes() for p in (self.root / ".rdd").rglob("*") if p.is_file()}
            with self.subTest(locator=contents):
                actual_code, status = self.cli_status()
                self.assertEqual(actual_code, code, status)
                self.assertEqual(status["status"], "failed" if code else "not_started")
                if contents is None:
                    self.assertEqual(status["next"], "./rdd init")
                self.assertEqual({p: p.read_bytes() for p in (self.root / ".rdd").rglob("*") if p.is_file()}, before)

    def test_brief_status_preserves_runtime_truth_and_default_display(self):
        f, c = self.fixture, self.fixture.controller
        f.observe()
        f.claim("S0", ["docs/specs/intake.md"])
        for scenario in ("current", "stale", "blocked", "historical"):
            if scenario == "stale":
                f.text("docs/specs/intake.md", "Completed intake.\n")
                f.record("S0")
                f.text("docs/specs/intake.md", "Changed intake.\n")
            elif scenario == "blocked":
                c.block("environment", "Fixture status blocker")
            elif scenario == "historical":
                state = c.state(allow_blocked=True)
                state["workflow_graph_digest"] = "0" * 64
                state["agent_profile_digest"] = "1" * 64
                state["workflow_nodes"]["S0"]["claim"]["role"] = "historical-author"
                state["workflow_nodes"]["S0"]["claim"].pop("sources")
                c.store.put(state)  # Deliberate historical-policy fixture.
            before = c.state(allow_blocked=True)
            expected = copy.deepcopy(c.status())
            for row in expected["workflow_nodes"]["nodes"]:
                claims = ([row["claim"]] if "claim" in row else []) + [a["claim"] for a in row.get("attempts", [])]
                for claim in claims:
                    if "sources" in claim:
                        claim["source_file_count"] = len(claim.pop("sources"))
            with self.subTest(scenario=scenario):
                full_code, full = self.cli_status()
                self.assertEqual(full, expected, "Default display must remain compatible")
                brief_code, brief = self.cli_status("--brief")
                self.assertEqual((full_code, brief_code), (2, 2) if scenario in {"blocked", "historical"} else (0, 0))
                self.assertEqual({k: v for k, v in brief.items() if k not in {"workflow_nodes", "details"}},
                                 {k: v for k, v in full.items() if k != "workflow_nodes"})
                self.assertEqual({k: v for k, v in brief["workflow_nodes"].items() if k != "nodes"},
                                 {k: v for k, v in full["workflow_nodes"].items() if k != "nodes"})
                self.assertNotIn("attempts", brief["workflow_nodes"]["nodes"][0])
                self.assertEqual(brief["details"], ["./rdd status", "./rdd workflow nodes", "./rdd export-run FILE"])
                self.assertEqual([r["id"] for r in brief["workflow_nodes"]["nodes"]],
                                 [r["id"] for r in full["workflow_nodes"]["nodes"]])
                for row, original in zip(brief["workflow_nodes"]["nodes"], full["workflow_nodes"]["nodes"]):
                    self.assertEqual(row["status"], original["status"])
                    self.assertEqual(row["attempt_count"], len(original.get("attempts", [])))
                    self.assertFalse({"attempts", "outputs", "validator", "responsible_roles"} & row.keys())
                    if "claim" in original:
                        self.assertEqual(row["claim"], {k: v for k, v in original["claim"].items() if k != "inputs"})
                self.assertEqual(c.state(allow_blocked=True), before)

    def specification(self):
        self.fixture.begin_s6()
        self.fixture.controller.spec_snapshot("author-S6")
        return self.fixture.controller.spec()

    def test_only_p5_can_write_the_assembled_plan(self):
        c = self.fixture.controller
        write_json(self.root / ".rdd/spec.lock.json", {"files": {}})
        for node in ("P0", "P1", "P2", "P3", "P4"):
            with self.subTest(node=node), self.assertRaisesRegex(RddError, "permitted artifact"):
                c._validate_node_writes(node, [".rdd/plan/plan.json"])
            c._validate_node_writes(node, [f".rdd/plan/notes/{node}.md"])
        c._validate_node_writes("P5", [".rdd/plan/plan.json"])
        self.assertEqual(NODES["P5"]["validator"], "plan_validation")

    def test_golden_scenario_requires_a_functional_requirement(self):
        spec = self.specification()
        reqs = artifacts.requirements(self.root, "requirements/requirements.md")
        reqs["records"]["NFR-001"] = {"id": "NFR-001"}
        spec["scenarios"].append({**spec["scenarios"][0], "id": "G-NFR", "requirements": ["NFR-001"], "solution_elements": ["E-NFR"]})
        spec["requirement_map"].append(dict(requirement="NFR-001", specifications=["docs/specs/solution.md"], scenarios=["G-NFR"]))
        spec["solution_elements"].append(dict(id="E-NFR", kind="enabling", module=None, behavior="support",
            requirements=["NFR-001"], scenarios=["G-NFR"], specifications=["docs/specs/solution.md"]))
        spec["checks"][-1]["scenario_ids"].append("G-NFR")
        with self.assertRaisesRegex(RddError, "golden.*functional requirement"):
            artifacts.spec_validate(self.root, spec, reqs, self.fixture.controller.config)

    def test_every_actionable_frozen_file_needs_a_task(self):
        spec = self.specification()
        plan = plan_for(spec)
        validate = lambda: artifacts.plan_validate(self.root, plan, spec, {"digest": "a" * 64}, self.fixture.controller.config)
        validate()
        entry = dict(path="modules/omitted.rs", kind="file", owner="D-ITEMS", purpose="Frozen output", disposition="add")
        spec["target_tree"].append(entry)
        for disposition in ("add", "modify", "delete"):
            entry["disposition"] = disposition
            for listed in (False, True):
                plan["target_paths"] = ["modules/items.rs"] + ([entry["path"]] if listed else [])
                with self.subTest(disposition=disposition, listed=listed), self.assertRaisesRegex(RddError, "actionable frozen files"):
                    validate()
        for disposition in ("retain", "generated"):
            entry["disposition"] = disposition
            validate()
        entry.update(path="modules/helpers", kind="directory", disposition="add")
        plan["target_paths"] = ["modules/items.rs"]
        validate()
        spec["checks"].append({**spec["checks"][-1], "id": "C-PROJECT", "scenario_ids": []})
        spec["project_check_ids"].append("C-PROJECT")
        with self.assertRaisesRegex(RddError, "every project check"):
            validate()

    def test_isolated_module_checks_use_task_and_phase_inventories(self):
        spec = self.specification()
        plan = plan_for(spec)
        spec["resources"].append(dict(id="R-SOURCE", kind="repository", path="modules/items.rs", availability="implementation"))
        spec["checks"][-1]["requires"] = ["R-SOURCE"]
        test = {**plan["tasks"][0], "id": "T002", "category": "tests", "writes": ["tests/items.rs"]}
        plan["tasks"].insert(0, test)
        plan["phases"][0]["tasks"].insert(0, "T002")
        validate_boundary_plan(spec, plan, self.root)
        for field in ("phase", "test", "source"):
            broken = copy.deepcopy(plan)
            if field == "phase":
                broken["phases"][0]["checks"] = []
            elif field == "test":
                broken["tasks"][0]["checks"] = []
            else:
                broken["tasks"][1]["writes"] = ["modules/elsewhere.rs"]
            with self.subTest(field=field), self.assertRaisesRegex(RddError, "implementation checks"):
                validate_boundary_plan(spec, broken, self.root)

    def test_unanswered_investigation_remains_claimable_but_accepted_open_choice_blocks(self):
        f, c = self.fixture, self.fixture.controller
        f.question(nodes=["S0"])
        f.observe()
        f.claim("S0", ["docs/specs/intake.md"])
        f.decision(nodes=["S0"], provenance=dict(kind="choice", question="Q-LIMIT", revision=1, option="bounded",
                   turn="user:2", text="Use bounded", qualifications=""))
        f.text("docs/specs/intake.md", "Bounded investigation result\n")
        with self.assertRaisesRegex(RddError, "inputs changed|unresolved origin question"):
            f.record("S0")
        c.workflow_release("S0", "Retry after accepted answer")
        f.observe()
        before = c.state()
        with self.assertRaisesRegex(RddError, "unresolved origin question"):
            f.claim("S0", ["docs/specs/intake.md"])
        self.assertEqual(c.state(), before)
        f.question(revision=2, previous_revision=1, nodes=["S0"], status="resolved", decision={"id": "D-LIMIT", "revision": 1})
        f.observe()
        f.claim("S0", ["docs/specs/intake.md"])

    def test_reopen_projection_falls_back_only_for_missing_context_and_preflights(self):
        spec = self.specification()
        plan = plan_for(spec)
        task = plan["tasks"][0]
        task["sites"][0]["placement"] = dict(kind="after", context="// Initial shell")
        self.fixture.text("modules/items.rs", "pub struct Items;\n")
        state = {"tasks": {"T001": {"status": "todo"}}}
        with self.assertRaisesRegex(RddError, "found 0"):
            artifacts.materialize(self.root, plan, state, create_shells=False)
        for options in ({"repair_tasks": {"T999"}, "create_shells": False}, {"repair_tasks": {"T001"}}):
            with self.assertRaisesRegex(RddError, "Repair projection requires"):
                artifacts.materialize(self.root, plan, state, **options)
        plan["target_paths"].append("modules/absent/")
        artifacts.materialize(self.root, plan, state, create_shells=False, repair_tasks={"T001"}, preflight=True)
        self.assertEqual((self.root / "modules/items.rs").read_text(), "pub struct Items;\n")
        self.assertFalse((self.root / "modules/absent").exists())
        artifacts.materialize(self.root, plan, state, create_shells=False, repair_tasks={"T001"})
        artifacts.anchors_verify(self.root, plan, state)
        self.assertEqual(artifacts.parse_markers((self.root / "modules/items.rs").read_text(), "modules/items.rs")[0]["payload"]["task"], task)
        artifacts.remove_anchor(self.root, task, plan)
        self.fixture.text("modules/items.rs", "// Initial shell\n// Initial shell\n")
        with self.assertRaisesRegex(RddError, "found 2"):
            artifacts.materialize(self.root, plan, state, create_shells=False, repair_tasks={"T001"}, preflight=True)

    def test_matrix_derives_full_traceability(self):
        spec = self.specification()
        plan = plan_for(spec)
        spec["solution_elements"][1]["contract_operations"] = ["fixture.items.Store.Read"]
        self.assertIn("Specifications", artifacts.implementation_matrix(plan))
        matrix = artifacts.implementation_matrix(plan, spec)
        for expected in ("Specifications", "Elements", "Operations", "Scenarios", "Verticals", "Checks",
                         "docs/specs/solution.md", "B-STATE", "fixture.items.Store.Read", "G01", "V01", "C-APP"):
            self.assertIn(expected, matrix)
