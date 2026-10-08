"""Adversarial harness tests. Fixtures do not implement or validate the Todo app."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tools.rdd.artifacts import (anchor_path, anchors_verify, materialize, marker_line,
    plan_validate, remove_anchor, requirements, shell_is_empty, spec_validate, topological)
from tools.rdd.common import (RddError, assert_inventory, file_hash, inventory,
    safe_path, source_digest, validate)

REPO = Path(__file__).resolve().parents[2]


def check(cid, kind="test", red=None):
    # A declaration for validator tests only; no subprocess ever executes it.
    return dict(id=cid, kind=kind, argv=["fixture-command-not-executed"], cwd=".",
                timeout_seconds=10, platforms=["any"], red_pattern=red,
                metrics=[], host_profile=None)


def task(tid, category, path, deps):
    return dict(id=tid, title=f"Implement fixture task {tid}", phase="P01",
        category=category, requirements=["FR-001"], specifications=["docs/specs/fixture.md"],
        depends_on=deps, writes=[path], checks=[] if category == "documentation" else ["behavior"],
        acceptance=["The accepted fixture behavior is observable."], scope="small",
        anchor=dict(path=path, mode="inline"),
        reuse=dict(capability_missing="A distinct fixture capability is absent.",
            candidates=[dict(path="modules/current.rs", reason="The inspected existing fixture owns a different invariant.")],
            why_not_extend="Extending the current owner would mix unrelated responsibilities.",
            duplication_check="The scoped search found only the existing distinct fixture.") if category == "addition" else None)


@unittest.skipUnless(shutil.which("git"), "Git is required for source identity fixtures")
class Fixture(unittest.TestCase):
    def setUp(self):
        override = os.environ.get("RDD_TEST_TMPDIR")
        temporary_root = Path(override or tempfile.gettempdir()).resolve()
        # Restricted hosts can fall back to cwd when system temp is unavailable.
        # Keep nested Git fixtures out of the repository's source/packaging scan.
        if not override and temporary_root.is_relative_to(REPO):
            temporary_root = REPO.parent
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="rdd-fixture-", dir=temporary_root)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        shutil.copytree(REPO / ".rdd/schemas", self.root / ".rdd/schemas")
        self.config = json.loads((REPO / ".rdd/config.json").read_text())
        self.write("requirements/requirements.md", "# Fixture requirements\n\n**FR-001 Preserve a value**\n\n"
            "The fixture shall preserve an accepted value.\n\nAcceptance: Read the accepted value after the operation.\n")
        self.write("docs/specs/fixture.md", "# Fixture specification\n\nOne owner preserves the accepted fixture value.\n")
        self.write("contracts/fixture/v1/fixture.proto", 'syntax = "proto3";\npackage fixture.v1;\nmessage Value { string text = 1; }\n')
        self.write("gen/fixture.rs", "// Generated fixture identity; not application code.\n")
        self.write("modules/current.rs", "// Existing fixture source.\n")
        self.reqs = requirements(self.root, "requirements/requirements.md")
        self.spec = dict(schema_version=1, id="fixture-spec", requirements_digest=self.reqs["digest"],
            mode="regenerate", parent_spec_digest=None, change_summary="A minimal isolated fixture for harness validation.",
            documents=["docs/specs/fixture.md"], decisions=[], contract_files=["contracts/fixture/v1/fixture.proto"],
            generated_files=["gen/fixture.rs"], contract_check_ids=["contract"], project_check_ids=["behavior"],
            modules=[dict(id="M1", requirements=["FR-001"], contract_paths=["contracts/fixture/v1/fixture.proto"],
                          owns_paths=["modules/current.rs"], depends_on=[])],
            scenarios=[dict(id="S1", requirements=["FR-001"], kind="golden",
                description="Accept and read a distinct fixture value.", expected="The accepted and read values agree.", check_ids=["behavior"])],
            checks=[check("contract", "contract"), check("behavior", red="EXPECTED_ASSERTION")],
            requirement_map=[dict(requirement="FR-001", specifications=["docs/specs/fixture.md"], scenarios=["S1"])],
            amendment=dict(requirements=[], paths=[], rationale=""))
        self.lock = dict(digest="a" * 64)
        tasks = [task("T001", "tests", "tests/behavior.py", []),
                 task("T002", "modification", "modules/current.rs", ["T001"]),
                 task("T003", "addition", "modules/new.rs", ["T002"]),
                 task("T004", "documentation", "docs/usage.md", ["T003"])]
        self.plan = dict(schema_version=1, spec_digest=self.lock["digest"], tasks=tasks,
            phases=[dict(id="P01", goal="The complete fixture behavior is available.", tasks=[t["id"] for t in tasks],
                checks=["behavior"], requirements_closed=["FR-001"], deliverables=["modules/new.rs"],
                independent_evidence=["Every prerequisite is in the baseline or this phase; future work is unnecessary."])],
            verticals=[dict(id="V1", goal="Preserve complete fixture behavior.", tasks=[t["id"] for t in tasks])],
            target_paths=[t["writes"][0] for t in tasks],
            shells=[dict(path=t["writes"][0], content="") for t in tasks if t["id"] != "T002"])
        self.state = dict(tasks={t["id"]: dict(status="pending") for t in tasks})

    def write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def vs(self):
        return spec_validate(self.root, self.spec, self.reqs, self.config)

    def vp(self):
        return plan_validate(self.root, self.plan, self.spec, self.lock, self.config)

    def split_phases(self):
        second = copy.deepcopy(self.plan["phases"][0])
        second.update(id="P02", tasks=["T003", "T004"], requirements_closed=["FR-001"])
        self.plan["phases"][0].update(tasks=["T001", "T002"], requirements_closed=[])
        self.plan["phases"].append(second)
        for t in self.plan["tasks"][2:]:
            t["phase"] = "P02"


class RequirementTests(Fixture):
    def test_exact_source_identity_and_normative_text(self):
        self.assertEqual(set(self.reqs["records"]), {"FR-001"})
        self.assertEqual(self.reqs["digest"], file_hash(self.root / "requirements/requirements.md"))
        self.assertIn("Acceptance:", self.reqs["records"]["FR-001"]["text"])

    def test_duplicate_and_incomplete_requirements_rejected(self):
        original = (self.root / "requirements/requirements.md").read_text()
        bad = [original + "\n**FR-001 Duplicate**\nThe fixture shall change.\nAcceptance: Observe it.\n",
               "**FR-001 Value**\nThe fixture may preserve a value.\nAcceptance: Read it.\n",
               "**FR-001 Value**\nThe fixture shall preserve a value.\n"]
        for content in bad:
            with self.subTest(content=content):
                self.write("requirements/requirements.md", content)
                with self.assertRaises(RddError):
                    requirements(self.root, "requirements/requirements.md")

    def test_shared_vocabulary_change_invalidates_old_spec(self):
        p = self.root / "requirements/requirements.md"
        p.write_text("A shared rule outside all ID blocks changed.\n\n" + p.read_text())
        changed = requirements(self.root, "requirements/requirements.md")
        self.assertNotEqual(changed["digest"], self.reqs["digest"])
        with self.assertRaisesRegex(RddError, "different requirements"):
            spec_validate(self.root, self.spec, changed, self.config)


class SpecificationTests(Fixture):
    def test_complete_spec_validates(self):
        self.assertEqual(self.vs()["requirements"], 1)

    def test_preparation_rejects_an_unowned_empty_shell(self):
        self.plan["target_paths"].append("modules/unowned.rs")
        self.plan["shells"].append({"path": "modules/unowned.rs", "content": ""})
        with self.assertRaisesRegex(RddError, "Every shell"):
            self.vp()

    def test_unknown_backlink_and_missing_golden_path_rejected(self):
        original = copy.deepcopy(self.spec)
        self.spec["scenarios"][0]["requirements"] = ["FR-UNKNOWN"]
        with self.assertRaisesRegex(RddError, "unknown references"):
            self.vs()
        self.spec = original
        self.spec["scenarios"][0]["kind"] = "negative"
        with self.assertRaisesRegex(RddError, "golden path"):
            self.vs()

    def test_module_cycle_rejected(self):
        second = copy.deepcopy(self.spec["modules"][0])
        second.update(id="M2", depends_on=["M1"])
        self.spec["modules"][0]["depends_on"] = ["M2"]
        self.spec["modules"].append(second)
        with self.assertRaisesRegex(RddError, "Dependency cycle"):
            self.vs()

    def test_check_declarations_cannot_omit_required_evaluation(self):
        original = copy.deepcopy(self.spec)
        cases = [(0, "kind", "test", "kind contract"),
                 (1, "kind", "manual", "cannot execute"),
                 (1, "red_pattern", "[", "Invalid RED pattern")]
        for pos, key, value, message in cases:
            with self.subTest(value=value):
                self.spec = copy.deepcopy(original)
                self.spec["checks"][pos][key] = value
                with self.assertRaisesRegex(RddError, message):
                    self.vs()
        self.spec = copy.deepcopy(original)
        self.spec["checks"].append(check("latency", "benchmark"))
        with self.assertRaisesRegex(RddError, "frozen metric limits"):
            self.vs()

    def test_generated_sources_cannot_overlap_canonical_contracts(self):
        self.spec["generated_files"] = self.spec["contract_files"].copy()
        with self.assertRaises(RddError):
            self.vs()

    def test_spec_word_budget_is_enforced(self):
        self.config["limits"]["max_spec_words"] = 5
        with self.assertRaisesRegex(RddError, "word budget"):
            self.vs()

    def test_contract_and_generated_sources_use_their_canonical_roots(self):
        original = copy.deepcopy(self.spec)
        self.write("modules/rogue.proto", 'syntax = "proto3";\nmessage Rogue {}\n')
        self.spec["contract_files"] = ["modules/rogue.proto"]
        self.spec["modules"][0]["contract_paths"] = ["modules/rogue.proto"]
        with self.assertRaises(RddError):
            self.vs()
        self.spec = original
        self.write("modules/rogue_generated.rs", "// wrongly placed output\n")
        self.spec["generated_files"] = ["modules/rogue_generated.rs"]
        with self.assertRaises(RddError):
            self.vs()


class GraphTests(Fixture):
    def test_valid_vertical_and_category_order(self):
        self.assertEqual(self.vp()["topological_order"], ["T001", "T002", "T003", "T004"])

    def test_cycle_and_unknown_producer_fail(self):
        for graph, message in [({"A": ["B"], "B": ["A"]}, "Dependency cycle"), ({"A": ["missing"]}, "Unknown dependency")]:
            with self.subTest(graph=graph), self.assertRaisesRegex(RddError, message):
                topological(graph)

    def test_addition_before_modification_in_same_phase_fails(self):
        self.plan["tasks"][1]["depends_on"] = ["T003"]
        self.plan["tasks"][2]["depends_on"] = ["T001"]
        with self.assertRaisesRegex(RddError, "Strict category cycle"):
            self.vp()

    def test_modification_before_deletion_in_same_phase_fails(self):
        self.plan["tasks"][2].update(category="deletion", reuse=None)
        with self.assertRaisesRegex(RddError, "Strict category cycle"):
            self.vp()

    def test_a_vertical_cannot_invent_a_missing_dependency(self):
        self.plan["tasks"][2]["depends_on"] = ["T001"]
        with self.assertRaisesRegex(RddError, "not an ordered prerequisite"):
            self.vp()

    def test_vertical_and_phase_membership_are_complete(self):
        original = copy.deepcopy(self.plan)
        self.plan["verticals"][0]["tasks"].pop()
        with self.assertRaisesRegex(RddError, "missing from verticals"):
            self.vp()
        self.plan = original
        self.plan["phases"][0]["tasks"].pop()
        with self.assertRaisesRegex(RddError, "membership mismatch"):
            self.vp()

    def test_every_requirement_needs_a_closure_phase(self):
        self.plan["phases"][0]["requirements_closed"] = []
        with self.assertRaisesRegex(RddError, "closure phase"):
            self.vp()

    def test_closure_requires_declared_check_coverage(self):
        self.plan["phases"][0]["checks"] = ["contract"]
        with self.assertRaisesRegex(RddError, "check coverage"):
            self.vp()

    def test_future_phase_dependency_fails(self):
        self.split_phases()
        self.plan["tasks"][1]["depends_on"] = ["T003"]
        self.plan["tasks"][2]["depends_on"] = ["T001"]
        with self.assertRaisesRegex(RddError, "future phase"):
            self.vp()

    def test_requirement_cannot_close_before_later_implementation(self):
        self.split_phases()
        self.plan["phases"][0]["requirements_closed"] = ["FR-001"]
        self.plan["phases"][1]["requirements_closed"] = []
        with self.assertRaisesRegex(RddError, "before its last implementation task"):
            self.vp()

    def test_additions_need_reuse_and_tests_need_red(self):
        self.plan["tasks"][2]["reuse"] = None
        with self.assertRaisesRegex(RddError, "reuse"):
            self.vp()
        self.plan["tasks"][2]["reuse"] = task("T003", "addition", "modules/new.rs", ["T002"])["reuse"]
        self.spec["checks"][1]["red_pattern"] = None
        with self.assertRaisesRegex(RddError, "behavioral RED"):
            self.vp()

    def test_frozen_contract_is_not_an_implementation_write_target(self):
        path = "contracts/fixture/v1/fixture.proto"
        self.plan["tasks"][1].update(writes=[path], anchor=dict(path=path, mode="sidecar"))
        self.plan["target_paths"].append(path)
        with self.assertRaisesRegex(RddError, "frozen/policy path"):
            self.vp()

    def test_missing_write_target_needs_explicit_shell(self):
        self.plan["shells"] = [s for s in self.plan["shells"] if s["path"] != "modules/new.rs"]
        with self.assertRaisesRegex(RddError, "explicit preparation shell"):
            self.vp()

    def test_json_requires_sidecar(self):
        self.plan["shells"] = [s for s in self.plan["shells"] if s["path"] != "docs/usage.md"]
        path = "app/capabilities.json"
        target = self.plan["tasks"][3]
        target.update(writes=[path], anchor=dict(path=path, mode="inline"))
        self.plan["target_paths"].append(path)
        self.plan["shells"].append(dict(path=path, content=""))
        with self.assertRaisesRegex(RddError, "sidecar"):
            self.vp()
        target["anchor"]["mode"] = "sidecar"
        self.vp()

    def test_preparation_shell_cannot_implement_behavior_before_tdd(self):
        shell = next(s for s in self.plan["shells"] if s["path"] == "modules/new.rs")
        shell["content"] = "pub fn production_behavior() -> bool { true }\n"
        with self.assertRaises(RddError):
            self.vp()

    def test_noncommentable_shell_must_stay_empty(self):
        path = "app/settings.json"
        self.plan["tasks"][3].update(writes=[path], anchor=dict(path=path, mode="sidecar"))
        self.plan["target_paths"].append(path)
        self.plan["shells"].append(dict(path=path, content='{"permissions":["all"]}\n'))
        with self.assertRaises(RddError):
            self.vp()

    def test_comment_shell_cannot_smuggle_behavior_between_comment_pairs(self):
        bad = [("ui/style.css", "/* note */ body { display: none; } /* end */\n"),
               ("ui/index.html", "<!-- note --><script>run()</script><!-- end -->\n"),
               ("ui/index.html", "<!-- note --!><script>run()</script><!-- end -->\n"),
               ("docs/user.md", "<!-- note -->actual output<!-- end -->\n")]
        for path, content in bad:
            with self.subTest(path=path):
                self.assertFalse(shell_is_empty(path, content))


class IdentityTests(Fixture):
    def test_repository_escape_and_git_paths_rejected(self):
        for rel in ("../outside", "modules/../../outside", "/absolute", ".git/config", "C:/outside", "a\\b"):
            with self.subTest(path=rel), self.assertRaises(RddError):
                safe_path(self.root, rel)

    def test_symlink_parent_is_not_a_writable_artifact(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        try:
            (self.root / "linked").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Host cannot create symlinks: {exc}")
        with self.assertRaisesRegex(RddError, "Symlink"):
            safe_path(self.root, "linked/value.rs")
        self.assertFalse((outside / "value.rs").exists())

    def test_frozen_hash_detects_edit_and_delete(self):
        baseline = inventory(self.root, ["contracts/fixture/v1/fixture.proto", "gen/fixture.rs"])
        self.write("gen/fixture.rs", "// Changed output\n")
        with self.assertRaisesRegex(RddError, "changed"):
            assert_inventory(self.root, baseline, "Contract baseline")
        (self.root / "gen/fixture.rs").unlink()
        with self.assertRaisesRegex(RddError, "changed"):
            assert_inventory(self.root, baseline, "Contract baseline")

    def test_receipt_creation_does_not_change_measured_source(self):
        before = source_digest(self.root)
        self.write(".rdd/evidence/receipt.json", '{"example":true}\n')
        self.write(".rdd/runtime/checkpoint.json", '{"example":true}\n')
        self.write(".rdd/run.json", '{"example":true}\n')
        self.assertEqual(source_digest(self.root), before)
        self.write("modules/current.rs", "// Source changed\n")
        self.assertNotEqual(source_digest(self.root), before)

    def test_schema_rejects_unknown_keys_and_bool_integer(self):
        for value, schema in [({"extra": True}, {"type": "object", "additionalProperties": False}), (True, {"type": "integer"})]:
            with self.subTest(value=value), self.assertRaises(RddError):
                validate(value, schema)

    def test_schema_version_constant_cannot_be_boolean_true(self):
        with self.assertRaises(RddError):
            validate(True, {"const": 1})

    def test_enum_and_nested_constants_keep_bool_separate_from_numbers(self):
        for value, schema in [(False, {"enum": [0, 1]}),
                              ({"version": True}, {"const": {"version": 1}}),
                              ([False], {"enum": [[0]]})]:
            with self.subTest(value=value), self.assertRaises(RddError):
                validate(value, schema)
        validate(1.0, {"const": 1})  # JSON Schema numbers compare by value.


class MarkerTests(Fixture):
    def test_materialization_is_idempotent_and_preserves_source(self):
        original = (self.root / "modules/current.rs").read_text()
        materialize(self.root, self.plan, self.state)
        before = {p: (self.root / p).read_text() for p in self.plan["target_paths"]}
        materialize(self.root, self.plan, self.state)
        self.assertEqual(before, {p: (self.root / p).read_text() for p in self.plan["target_paths"]})
        self.assertTrue((self.root / "modules/current.rs").read_text().startswith(original))
        self.assertEqual(anchors_verify(self.root, self.plan, self.state)["remaining"], 4)

    def test_erasing_marker_cannot_complete_task_and_reconcile_restores_it(self):
        materialize(self.root, self.plan, self.state)
        remove_anchor(self.root, self.plan["tasks"][0])
        with self.assertRaisesRegex(RddError, "exactly one anchor"):
            anchors_verify(self.root, self.plan, self.state)
        self.assertEqual(self.state["tasks"]["T001"]["status"], "pending")
        materialize(self.root, self.plan, self.state)
        self.assertEqual(anchors_verify(self.root, self.plan, self.state)["remaining"], 4)

    def test_duplicate_marker_is_rejected_without_rewriting_evidence(self):
        materialize(self.root, self.plan, self.state)
        t = self.plan["tasks"][0]
        p = self.root / anchor_path(t)
        p.write_text(p.read_text() + marker_line(t) + "\n")
        original = p.read_text()
        with self.assertRaisesRegex(RddError, "Duplicate anchor"):
            materialize(self.root, self.plan, self.state)
        self.assertEqual(p.read_text(), original)

    def test_wrong_phase_and_unknown_marker_are_detected(self):
        materialize(self.root, self.plan, self.state)
        p = self.root / "tests/behavior.py"
        p.write_text(p.read_text().replace("RDD:P01:T001", "RDD:P02:T001"))
        original = p.read_text()
        with self.assertRaisesRegex(RddError, "Orphaned or misplaced"):
            anchors_verify(self.root, self.plan, self.state)
        self.assertEqual(p.read_text(), original)
        p.write_text(original.replace("RDD:P02:T001", "RDD:P01:T999"))
        with self.assertRaisesRegex(RddError, "Orphaned or misplaced"):
            anchors_verify(self.root, self.plan, self.state)

    def test_done_task_cannot_retain_a_marker(self):
        materialize(self.root, self.plan, self.state)
        self.state["tasks"]["T001"]["status"] = "done"
        with self.assertRaisesRegex(RddError, "Completed task still has an anchor"):
            anchors_verify(self.root, self.plan, self.state)
        remove_anchor(self.root, self.plan["tasks"][0])
        self.assertEqual(anchors_verify(self.root, self.plan, self.state)["remaining"], 3)

    def test_t001_removal_preserves_t0010_and_source(self):
        short = task("T001", "tests", "tests/shared.py", [])
        long = task("T0010", "tests", "tests/shared.py", [])
        p = self.write("tests/shared.py", "value = 42\n" + marker_line(short) + "\n" + marker_line(long) + "\n")
        remove_anchor(self.root, short)
        self.assertEqual(p.read_text(), "value = 42\n" + marker_line(long) + "\n")

    def test_shared_marker_line_fails_without_deleting_another_task(self):
        first = task("T001", "tests", "tests/shared.py", [])
        second = task("T002", "tests", "tests/shared.py", [])
        original = marker_line(first) + " " + marker_line(second) + "\n"
        p = self.write("tests/shared.py", original)
        with self.assertRaisesRegex(RddError, "share one line"):
            remove_anchor(self.root, first)
        self.assertEqual(p.read_text(), original)

    def test_sidecar_preserves_empty_json_shell(self):
        t = task("T010", "addition", "app/settings.json", [])
        t["anchor"]["mode"] = "sidecar"
        plan = dict(tasks=[t], target_paths=["app/settings.json"], shells=[dict(path="app/settings.json", content="")])
        state = dict(tasks={"T010": dict(status="pending")})
        materialize(self.root, plan, state)
        self.assertEqual((self.root / "app/settings.json").read_text(), "")
        self.assertIn("RDD:P01:T010", (self.root / anchor_path(t)).read_text())
        self.assertEqual(anchors_verify(self.root, plan, state)["remaining"], 1)


if __name__ == "__main__":
    unittest.main()
