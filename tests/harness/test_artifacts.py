"""Adversarial harness tests. Fixtures do not implement or validate the Todo app."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from tools.rdd.artifacts import (anchor_path, anchors_verify, materialize, marker_line,
    anchor_paths, parse_markers, plan_validate, remove_anchor, requirements, shell_is_empty, spec_validate, topological)
from tools.rdd.checks import platform_name
from tools.rdd.common import (RddError, assert_inventory, atomic_write, file_hash, inventory,
    safe_path, source_digest, validate)

REPO = Path(__file__).resolve().parents[2]


def check(cid, kind="test", red=None):
    # A declaration for validator tests only; no subprocess ever executes it.
    return dict(id=cid, kind=kind, argv=["fixture-command-not-executed"], cwd=".",
                timeout_seconds=10, platforms=["any"], red_pattern=red,
                metrics=[], host_profile=None, environments=["local"], requires=[],
                scenario_ids=["S1"] if cid == "behavior" else [],
                results_path=".rdd/evidence/results/behavior.json" if cid == "behavior" else None)


def task(tid, category, path, deps):
    return dict(id=tid, title=f"Implement fixture task {tid}",
        objective="Establish the specified fixture behavior with its planned acceptance evidence.", phase="P01",
        category=category, requirements=["FR-001"], specifications=["docs/specs/fixture.md"],
        depends_on=deps, writes=[path], checks=[] if category == "documentation" else ["behavior"],
        acceptance=["The accepted fixture behavior is observable."], scope="small",
        sites=[dict(id="A01", path=path, mode="sidecar" if category == "deletion" else "inline", primary=True,
            placement=dict(kind="append", context=None), instructions="Implement the scoped fixture change here.")],
        solution_elements=["E-DOMAIN", "E-OP", "E-SUPPORT"], scenarios=["S1"],
        requires=[], produces=[], bootstrap_resources=[],
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
        # Fixture receipts bind exact bytes across parent/worker checkouts on every OS.
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=self.root, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        shutil.copytree(REPO / ".rdd/schemas", self.root / ".rdd/schemas")
        self.config = json.loads((REPO / ".rdd/config.json").read_text())
        self.write("requirements/requirements.md", "# Fixture requirements\n\n**FR-001 Preserve a value**\n\n"
            "The fixture shall preserve an accepted value.\n\nAcceptance: Read the accepted value after the operation.\n")
        self.write("docs/specs/fixture.md", "# Fixture specification\n\nOne owner preserves the accepted fixture value.\n")
        self.write("contracts/fixture/v1/fixture.proto", 'syntax = "proto3";\npackage fixture.v1;\nmessage Value { string text = 1; }\n'
            'message Reply { oneof outcome { string accepted = 1; string error = 2; } }\nservice FixtureService { rpc Preserve(Value) returns (Reply); }\n')
        self.write("gen/fixture.rs", "// Generated fixture identity; not application code.\n")
        self.write("modules/current.rs", "// Existing fixture source.\n")
        self.reqs = requirements(self.root, "requirements/requirements.md")
        self.spec = dict(schema_version=2, author_sessions=["fixture-author"], id="fixture-spec", requirements_digest=self.reqs["digest"],
            mode="regenerate", parent_spec_digest=None, change_summary="A minimal isolated fixture for harness validation.",
            documents=["docs/specs/fixture.md"], decisions=[], contract_files=["contracts/fixture/v1/fixture.proto"],
            generated_files=["gen/fixture.rs", "gen/metadata.json"], contract_index_path="gen/metadata.json",
            shared_generated_files=[dict(path="gen/metadata.json", purpose="Generated descriptor-index support for the validator fixture.")],
            contract_check_ids=["contract"], project_check_ids=["behavior"],
            modules=[dict(id="M1", requirements=["FR-001"], contract_paths=["contracts/fixture/v1/fixture.proto"],
                owns_paths=["modules/"], depends_on=[], provided_services=["fixture.v1.FixtureService"], consumed_operations=[],
                generated_paths=["gen/fixture.rs"], adapter_error_specs=["docs/specs/fixture.md"],
                qualification_checks={g:["contract"] for g in ("provider","consumer","negative_signature","dependency_direction","compatibility")},
                implementation_checks={**{g:["boundary"] for g in ("provider","consumer","dependency_direction","compatibility")}, "semantics":["behavior"]})],
            scenarios=[dict(id="S1", requirements=["FR-001"], kind="golden",
                solution_elements=["E-DOMAIN", "E-OP", "E-SUPPORT"], preconditions="The fixture is isolated.",
                fixture="A distinct input value.", stimulus="Accept and read the value.",
                verification_method="Compare to the independently specified input value.", description="Accept and read a distinct fixture value.", expected="The accepted and read values agree.", check_ids=["behavior"])],
            checks=[check("contract", "contract"), check("behavior", red="EXPECTED_ASSERTION"), check("boundary")],
            requirement_map=[dict(requirement="FR-001", specifications=["docs/specs/fixture.md"], scenarios=["S1"])],
            amendment=dict(requirements=[], paths=[], rationale=""),
            solution_elements=[dict(id=eid, kind=kind, behavior="positive" if kind == "operation" else "support", requirements=["FR-001"], scenarios=["S1"],
                specifications=["docs/specs/fixture.md"], module=None if eid == "E-SUPPORT" else "M1")
                for eid, kind in (("E-DOMAIN", "subdomain"), ("E-OP", "operation"), ("E-SUPPORT", "enabling"))],
            target_tree=[], resources=[],
            environments=[dict(id="local", platform=platform_name(), host_profile=None)])
        self.spec["solution_elements"][1]["contract_operations"] = ["fixture.v1.FixtureService.Preserve"]
        self.spec["resources"] = [dict(id="fixture-"+role,kind="repository",path=path,version=None,
            availability="implementation",required_at="implementation",probe_check_ids=[],environments=["local"])
            for role,path in (("provider","modules/current.rs"),("consumer","modules/new.rs"))]
        self.spec["checks"][2]["requires"] = ["fixture-provider","fixture-consumer"]
        self.write("gen/metadata.json", json.dumps(dict(contract_index=dict(schema_version=1,
            source_hashes={"contracts/fixture/v1/fixture.proto": file_hash(self.root / "contracts/fixture/v1/fixture.proto")},
            binding_files=["gen/fixture.rs"], support_files=["gen/metadata.json"],
            binding_sources={"gen/fixture.rs":["contracts/fixture/v1/fixture.proto"]},
            services=[dict(symbol="fixture.v1.FixtureService", source="contracts/fixture/v1/fixture.proto", generated_path="gen/fixture.rs",
                operations=[dict(symbol="fixture.v1.FixtureService.Preserve", response_oneofs=[dict(name="outcome",fields=["accepted","error"])])])]))))
        self.lock = dict(digest="a" * 64)
        tasks = [task("T001", "tests", "tests/behavior.py", []),
                 task("T002", "modification", "modules/current.rs", ["T001"]),
                 task("T003", "addition", "modules/new.rs", ["T002"]),
                 task("T004", "documentation", "docs/usage.md", ["T003"])]
        tasks[1]["produces"] = ["fixture-provider"]
        tasks[2]["produces"] = ["fixture-consumer"]
        self.plan = dict(schema_version=2, author_sessions=["fixture-author"], spec_digest=self.lock["digest"], tasks=tasks,
            phases=[dict(id="P01", goal="The complete fixture behavior is available.", tasks=[t["id"] for t in tasks],
                checks=["behavior","boundary"], requirements_closed=["FR-001"], deliverables=["modules/new.rs"],
                independent_evidence=["Every prerequisite is in the baseline or this phase; future work is unnecessary."])],
            verticals=[dict(id="V01", goal="Preserve complete fixture behavior.", tasks=[t["id"] for t in tasks])],
            target_paths=[t["writes"][0] for t in tasks],
            shells=[dict(path=t["writes"][0], content="# Fixture preparation shell\n" if t["writes"][0].endswith(".py")
                else "<!-- Fixture preparation shell -->\n" if t["writes"][0].endswith(".md")
                else "// Fixture preparation shell\n") for t in tasks if t["id"] != "T002"],
            element_coverage=[dict(element=e["id"], tasks=[t["id"] for t in tasks],
                checks=["behavior"], baseline_evidence=None) for e in self.spec["solution_elements"]],
            resource_producers=[dict(resource="fixture-"+role,kind="task",task=tid,checks=[])
                for role,tid in (("provider","T002"),("consumer","T003"))],
            resource_uses=[dict(resource="fixture-"+role,consumer_kind=kind,consumer="P01" if kind == "phase" else None)
                for role in ("provider","consumer") for kind in ("phase","project")],
            boundary_proofs=[dict(module="M1",operation="fixture.v1.FixtureService.Preserve",first_phase="P01",checks=["behavior","boundary"],
                provider_tasks=["T002"],consumer_tasks=["T003"],adapter_tasks=["T003"],verification_tasks=["T001"])])
        self.spec["target_tree"] = [dict(path=p, kind="file", owner="E-DOMAIN" if p.startswith("modules/") else "E-SUPPORT",
            purpose="A fixture work site.", disposition="modify" if p == "modules/current.rs" else "add")
            for p in self.plan["target_paths"]]
        self.spec["target_tree"].append(dict(path="modules/",kind="directory",owner="E-DOMAIN",
            purpose="The domain module ownership boundary.",disposition="retain"))
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

    def declare_path(self, path, disposition="add", owner=None, kind="file"):
        owner = owner or ("E-DOMAIN" if path.startswith("modules/") else "E-SUPPORT")
        self.spec["target_tree"].append(dict(path=path, kind=kind, owner=owner,
            purpose="An explicitly approved fixture target.", disposition=disposition))

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

    def test_scenario_backlink_cannot_be_omitted_from_requirement_map(self):
        orphan = copy.deepcopy(self.spec["scenarios"][0])
        orphan["id"] = "S2"
        self.spec["scenarios"].append(orphan)
        with self.assertRaisesRegex(RddError, "reverse scenario coverage"):
            self.vs()

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
        self.plan["tasks"][2]["sites"][0]["mode"] = "sidecar"
        next(e for e in self.spec["target_tree"] if e["path"] == "modules/new.rs")["disposition"] = "delete"
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
        self.plan["tasks"][1].update(writes=[path], sites=[dict(id="A01",path=path,mode="sidecar",primary=True,placement=dict(kind="append",context=None),instructions="Update this fixture file.")])
        self.plan["target_paths"].append(path)
        self.declare_path(path,disposition="modify")
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
        target.update(writes=[path], sites=[dict(id="A01",path=path,mode="inline",primary=True,placement=dict(kind="append",context=None),instructions="Update this fixture file.")])
        self.plan["target_paths"].append(path)
        self.declare_path(path)
        with self.assertRaisesRegex(RddError, "sidecar"):
            self.vp()
        target["sites"][0]["mode"] = "sidecar"
        self.vp()

    def test_preparation_shell_cannot_implement_behavior_before_tdd(self):
        shell = next(s for s in self.plan["shells"] if s["path"] == "modules/new.rs")
        shell["content"] = "pub fn production_behavior() -> bool { true }\n"
        with self.assertRaises(RddError):
            self.vp()

    def test_noncommentable_shell_must_stay_empty(self):
        path = "app/settings.json"
        self.plan["tasks"][3].update(writes=[path], sites=[dict(id="A01",path=path,mode="sidecar",primary=True,placement=dict(kind="append",context=None),instructions="Update this fixture file.")])
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


class V2CoverageTests(Fixture):
    def test_every_module_requires_a_functional_subdomain(self):
        module = copy.deepcopy(self.spec["modules"][0])
        module.update(id="M-AUX",owns_paths=["aux/"])
        self.spec["modules"].append(module)
        self.spec["solution_elements"].append(dict(id="E-AUX",kind="enabling",behavior="support",
            requirements=["FR-001"],scenarios=["S1"],specifications=self.spec["documents"],module="M-AUX"))
        self.spec["scenarios"][0]["solution_elements"].append("E-AUX")
        self.spec["target_tree"].append(dict(path="aux/",kind="directory",owner="E-AUX",
            purpose="A module without a functional subdomain.",disposition="retain"))
        with self.assertRaisesRegex(RddError,"Module M-AUX.*functional subdomain"):
            self.vs()

    def test_module_path_ownership_cannot_drift_from_frozen_tree(self):
        self.spec["modules"][0]["owns_paths"].append("modules/omitted.rs")
        with self.assertRaisesRegex(RddError, "ownership.*frozen target tree"):
            self.vs()

    def test_module_owner_cannot_claim_another_modules_path(self):
        module = copy.deepcopy(self.spec["modules"][0])
        module.update(id="M2", owns_paths=["modules/current.rs"])
        self.spec["modules"].append(module)
        subdomain = copy.deepcopy(self.spec["solution_elements"][0])
        subdomain.update(id="E-SECOND-DOMAIN", module="M2")
        self.spec["solution_elements"].append(subdomain)
        self.spec["scenarios"][0]["solution_elements"].append("E-SECOND-DOMAIN")
        self.spec["solution_elements"][1]["module"] = "M2"
        with self.assertRaisesRegex(RddError,"disagrees with target owner"):
            self.vs()

    def test_positive_operation_needs_golden_for_each_requirement(self):
        self.write("requirements/requirements.md", (self.root / "requirements/requirements.md").read_text()
            + "\n**FR-002 Preserve another value**\nThe fixture shall preserve another value.\nAcceptance: Read it.\n")
        self.reqs = requirements(self.root,"requirements/requirements.md")
        self.spec["requirements_digest"] = self.reqs["digest"]
        self.spec["modules"][0]["requirements"].append("FR-002")
        second = copy.deepcopy(self.spec["scenarios"][0])
        second.update(id="S2",requirements=["FR-002"],solution_elements=["E-DOMAIN"])
        negative = copy.deepcopy(second)
        negative.update(id="S-NEG",kind="negative",solution_elements=["E-OP"])
        self.spec["scenarios"] += [second,negative]
        self.spec["requirement_map"].append(dict(requirement="FR-002",specifications=self.spec["documents"],scenarios=["S2","S-NEG"]))
        self.spec["solution_elements"][0]["requirements"].append("FR-002")
        self.spec["solution_elements"][0]["scenarios"].append("S2")
        self.spec["solution_elements"][1]["requirements"].append("FR-002")
        self.spec["solution_elements"][1]["scenarios"].append("S-NEG")
        self.spec["checks"][1]["scenario_ids"].append("S2")
        with self.assertRaisesRegex(RddError,"Positive operation.*missing golden"):
            self.vs()

    def test_positive_invariant_cannot_borrow_an_unlinked_requirement_golden(self):
        negative = copy.deepcopy(self.spec["scenarios"][0])
        negative.update(id="S-INVARIANT-NEG",kind="negative",solution_elements=["E-INVARIANT"])
        self.spec["scenarios"].append(negative)
        self.spec["requirement_map"][0]["scenarios"].append(negative["id"])
        self.spec["solution_elements"].append(dict(id="E-INVARIANT",kind="invariant",behavior="positive",
            requirements=["FR-001"],scenarios=[negative["id"]],specifications=self.spec["documents"],module="M1"))
        # FR-001 retains S1's golden path, but this observable invariant has only
        # its own negative scenario and must not inherit another element's proof.
        with self.assertRaisesRegex(RddError,"Positive invariant.*missing golden"):
            self.vs()
        self.spec["solution_elements"][-1]["scenarios"].append("S1")
        self.spec["scenarios"][0]["solution_elements"].append("E-INVARIANT")
        self.assertEqual(self.vs()["solution_elements"], 4)

    def test_complete_v2_spec_and_plan_validate(self):
        self.assertEqual(self.vs()["solution_elements"], 3)
        self.assertEqual(self.vp()["tasks"], 4)

    def test_solution_element_reverse_links_and_normative_refs(self):
        original = copy.deepcopy(self.spec)
        for mutate, message in (
            (lambda: self.spec["scenarios"][0]["solution_elements"].remove("E-OP"), "reverse.*element"),
            (lambda: self.spec["solution_elements"][1].update(scenarios=[]), "constraint|array|reverse"),
            (lambda: self.spec["solution_elements"][1].update(module="unknown"), "unknown module"),
            (lambda: self.spec["solution_elements"][1].update(specifications=["docs/missing.md"]), "specification reference"),
        ):
            with self.subTest(message=message):
                self.spec = copy.deepcopy(original)
                mutate()
                with self.assertRaisesRegex(RddError, message):
                    self.vs()

    def test_functional_requirement_needs_subdomain_owner(self):
        self.spec["solution_elements"][0]["kind"] = "enabling"
        with self.assertRaisesRegex(RddError, "functional owner"):
            self.vs()

    def test_target_tree_rejects_duplicate_owner_and_file_ancestry(self):
        original = copy.deepcopy(self.spec)
        for row in (copy.deepcopy(self.spec["target_tree"][0]),
                    dict(path="modules/current.rs/child.rs", kind="file", owner="E-OP",
                         purpose="Invalid child of a file.", disposition="add")):
            with self.subTest(path=row["path"]):
                self.spec = copy.deepcopy(original)
                self.spec["target_tree"].append(row)
                with self.assertRaisesRegex(RddError, "Duplicate target|file ancestor"):
                    self.vs()

    def test_preparation_cannot_invent_target_outside_frozen_tree(self):
        self.spec["target_tree"] = [e for e in self.spec["target_tree"] if e["path"] != "docs/usage.md"]
        with self.assertRaisesRegex(RddError, "frozen target tree"):
            self.vp()

    def test_element_coverage_is_complete_and_bidirectional(self):
        original = copy.deepcopy(self.plan)
        for mutate, message in (
            (lambda: self.plan["element_coverage"].pop(), "element coverage"),
            (lambda: self.plan["element_coverage"][0]["tasks"].pop(), "Task.*element coverage"),
            (lambda: self.plan["tasks"][0].update(scenarios=["unknown"]), "unknown references"),
        ):
            with self.subTest(message=message):
                self.plan = copy.deepcopy(original)
                mutate()
                with self.assertRaisesRegex(RddError, message):
                    self.vp()

    def test_each_write_needs_a_site_and_one_primary(self):
        task = self.plan["tasks"][1]
        task["writes"].append("modules/second.rs")
        self.plan["target_paths"].append("modules/second.rs")
        self.plan["shells"].append(dict(path="modules/second.rs",content="// Planned shell\n"))
        self.declare_path("modules/second.rs")
        with self.assertRaisesRegex(RddError, "Every write.*site"):
            self.vp()
        second = copy.deepcopy(task["sites"][0])
        second.update(id="A02",path="modules/second.rs")
        task["sites"].append(second)
        with self.assertRaisesRegex(RddError, "exactly one primary"):
            self.vp()
        second["primary"] = False
        self.vp()

    def test_duplicate_sites_and_sidecar_collisions_rejected(self):
        task = self.plan["tasks"][1]
        task["sites"].append(copy.deepcopy(task["sites"][0]))
        with self.assertRaisesRegex(RddError, "Duplicate.*site"):
            self.vp()
        task["sites"].pop()
        task["sites"][0]["mode"] = "sidecar"
        self.write("modules/current.rs.rdd.md", "A real document.\n")
        with self.assertRaisesRegex(RddError, "sidecar.*collision"):
            self.vp()

    def test_commentable_new_target_requires_nonempty_comment_shell(self):
        self.plan["shells"][0]["content"] = ""
        with self.assertRaisesRegex(RddError, "comment-only shell"):
            self.vp()

    def test_absent_noncommentable_target_is_reserved_only_by_sidecar(self):
        task = self.plan["tasks"][3]
        old = task["writes"][0]
        task["writes"] = ["app/settings.json"]
        task["sites"][0].update(path="app/settings.json",mode="sidecar")
        self.plan["target_paths"].remove(old)
        self.plan["target_paths"].append("app/settings.json")
        self.plan["shells"] = [s for s in self.plan["shells"] if s["path"] != old]
        self.declare_path("app/settings.json")
        self.vp()
        materialize(self.root,self.plan,self.state)
        self.assertFalse((self.root / "app/settings.json").exists())
        self.assertTrue((self.root / "app/settings.json.rdd.md").is_file())

    def test_golden_scenario_requires_declared_check_observations(self):
        self.spec["checks"][1]["scenario_ids"] = []
        with self.assertRaisesRegex(RddError,"golden.*observation"):
            self.vs()


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


@unittest.skipUnless(os.name == "posix", "POSIX file modes are required")
class AtomicWriteTests(Fixture):
    def test_replacement_preserves_existing_mode(self):
        for mode in (0o755, 0o640):
            with self.subTest(mode=oct(mode)):
                path = self.write("existing", "original\n")
                path.chmod(mode)
                atomic_write(path, b"replacement\n")
                self.assertEqual(path.read_bytes(), b"replacement\n")
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)

    def test_new_file_remains_restrictive_under_permissive_umask(self):
        path = self.root / "new"
        previous_umask = os.umask(0)
        try:
            atomic_write(path, b"new\n")
        finally:
            os.umask(previous_umask)
        self.assertEqual(path.read_bytes(), b"new\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_fchmod_failure_preserves_original_and_cleans_temporary_file(self):
        path = self.write("existing", "original\n")
        path.chmod(0o755)
        with patch("tools.rdd.common.os.fchmod", side_effect=OSError("injected fchmod failure")):
            with self.assertRaisesRegex(OSError, "injected fchmod failure"):
                atomic_write(path, b"replacement\n")
        self.assertEqual(path.read_bytes(), b"original\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755)
        self.assertEqual(list(self.root.glob(".rdd-write-*")), [])

    def test_symlink_destinations_are_refused(self):
        target = self.write("target", "original\n")
        target.chmod(0o755)
        for name in ("target", "missing"):
            with self.subTest(target=name):
                link = self.root / (name + "-link")
                link.symlink_to(self.root / name)
                with self.assertRaisesRegex(RddError, "Refusing symlink"):
                    atomic_write(link, b"replacement\n")
                self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_bytes(), b"original\n")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)
        self.assertFalse((self.root / "missing").exists())
        self.assertEqual(list(self.root.glob(".rdd-write-*")), [])


class MarkerTests(Fixture):
    def test_whole_marker_line_inside_multiline_literals_is_rejected(self):
        t = self.plan["tasks"][1]
        rust_marker = marker_line(t,plan=self.plan)
        py_task = self.plan["tasks"][0]
        python_marker = marker_line(py_task,plan=self.plan)
        cases = [("modules/current.rs", 'const VALUE: &str = r###"\n' + rust_marker + '\n"###;\n'),
                 ("modules/current.rs", 'const VALUE: &str = "\n' + rust_marker + '\n";\n'),
                 ("modules/current.rs", '/* outer /* inner */\n' + rust_marker + '\n*/\n'),
                 ("tests/behavior.py", 'value = """\n' + python_marker + '\n"""\n')]
        for rel,text in cases:
            with self.subTest(path=rel), self.assertRaisesRegex(RddError,"code/string context"):
                parse_markers(text,rel)

    def test_markdown_fence_and_unsupported_inline_formats_use_sidecars(self):
        t = self.plan["tasks"][3]
        line = marker_line(t,plan=self.plan)
        with self.assertRaisesRegex(RddError,"code/string context"):
            parse_markers("```text\n"+line+"\n```\n","docs/usage.md")
        t["writes"] = ["app/settings.toml"]
        t["sites"][0]["path"] = t["writes"][0]
        with self.assertRaisesRegex(RddError,"use an adjacent sidecar"):
            marker_line(t,plan=self.plan)

    def test_sidecar_is_removed_only_after_last_registered_task_packet(self):
        first = self.plan["tasks"][1]
        second = self.plan["tasks"][2]
        first["sites"][0]["mode"] = "sidecar"
        second["writes"] = first["writes"].copy()
        second["sites"][0].update(path=first["writes"][0],mode="sidecar")
        materialize(self.root,self.plan,self.state)
        sidecar = self.root / anchor_path(first)
        remove_anchor(self.root,first,self.plan)
        self.assertTrue(sidecar.is_file())
        self.assertEqual([m["task"] for m in parse_markers(sidecar.read_text(),anchor_path(first))],["T003"])
        remove_anchor(self.root,second,self.plan)
        self.assertFalse(sidecar.exists())

    def test_every_site_projects_full_primary_packet_and_local_link(self):
        t = self.plan["tasks"][1]
        t["writes"].append("modules/second.rs")
        self.plan["target_paths"].append("modules/second.rs")
        self.plan["shells"].append(dict(path="modules/second.rs",content="// Planned secondary work.\n"))
        self.declare_path("modules/second.rs")
        t["sites"].append(dict(id="A02",path="modules/second.rs",mode="inline",primary=False,
            placement=dict(kind="append",context=None),instructions="Apply the accompanying fixture change here."))
        self.vp()
        materialize(self.root,self.plan,self.state)
        self.assertEqual(anchors_verify(self.root,self.plan,self.state)["remaining"],5)
        primary = parse_markers((self.root / anchor_path(t)).read_text(),anchor_path(t))[0]["payload"]
        self.assertEqual(primary["task"]["writes"],t["writes"])
        self.assertEqual(primary["task"]["acceptance"],t["acceptance"])
        self.assertEqual(primary["task"]["sites"],t["sites"])
        local = parse_markers((self.root / "modules/second.rs").read_text(),"modules/second.rs")[0]["payload"]
        self.assertEqual(local["primary_site"],"modules/current.rs#A01")
        self.assertNotIn("task",local)
        remove_anchor(self.root,t,self.plan)
        for rel in anchor_paths(t):
            self.assertNotIn("RDD:",(self.root / rel).read_text())

    def test_multiple_sites_in_same_file_have_distinct_exact_identities(self):
        t = self.plan["tasks"][1]
        t["sites"].append(dict(t["sites"][0],id="A02",primary=False))
        materialize(self.root,self.plan,self.state)
        p = self.root / anchor_path(t)
        self.assertEqual(len(parse_markers(p.read_text(),anchor_path(t))),2)
        remove_anchor(self.root,t,self.plan)
        self.assertEqual(p.read_text(),"// Existing fixture source.\n")

    def test_vertical_membership_is_sorted_and_derived_from_inventory(self):
        self.plan["verticals"] += [dict(id="V03",goal="A shared later fixture vertical.",tasks=["T002"])]
        line = marker_line(self.plan["tasks"][1],plan=self.plan)
        self.assertIn("RDD:P01:modification:V01+V03:T002:A01",line)
        self.plan["verticals"].reverse()
        self.assertEqual(marker_line(self.plan["tasks"][1],plan=self.plan),line)

    def test_before_after_placement_is_unique_and_idempotent(self):
        t = self.plan["tasks"][1]
        p = self.write("modules/current.rs","// Before\nfn value() {}\n// After\n")
        t["sites"][0]["placement"] = dict(kind="before",context="fn value() {}")
        t["sites"].append(dict(t["sites"][0],id="A02",primary=False,placement=dict(kind="after",context="fn value() {}")))
        materialize(self.root,self.plan,self.state)
        text = p.read_text()
        self.assertLess(text.index(":A01 |"),text.index("\nfn value() {}\n"))
        self.assertGreater(text.index(":A02 |"),text.index("\nfn value() {}\n"))
        materialize(self.root,self.plan,self.state)
        self.assertEqual(p.read_text(),text)
        remove_anchor(self.root,t,self.plan)
        self.assertEqual(p.read_text(),"// Before\nfn value() {}\n// After\n")

    def test_ambiguous_placement_fails_before_modifying_any_file(self):
        t = self.plan["tasks"][1]
        p = self.write("modules/current.rs","fn value() {}\nfn value() {}\n")
        t["sites"][0]["placement"] = dict(kind="before",context="fn value() {}")
        original = p.read_bytes()
        with self.assertRaisesRegex(RddError,"exactly one complete source region"):
            materialize(self.root,self.plan,self.state)
        self.assertEqual(p.read_bytes(),original)
        self.assertFalse((self.root / "tests/behavior.py").exists())

    def test_payload_comment_terminators_and_fake_prefix_are_losslessly_escaped(self):
        t = self.plan["tasks"][3]
        instructions = 'Close --> then --!> and */ and RDD:P01:tests:V01:T999:A01.\nNew line.'
        t["sites"][0]["instructions"] = instructions
        t["acceptance"] = [instructions]
        line = marker_line(t,plan=self.plan)
        self.assertEqual(line.count("-->"),1)
        self.assertNotIn("--!>",line)
        self.assertNotIn("*/",line)
        self.assertEqual(line.count("RDD:"),1)
        parsed = parse_markers(line,"docs/usage.md")
        self.assertEqual(parsed[0]["payload"]["instructions"],instructions)
        materialize(self.root,self.plan,self.state)
        anchors_verify(self.root,self.plan,self.state)

    def test_wrong_category_vertical_site_and_payload_are_rejected(self):
        materialize(self.root,self.plan,self.state)
        t = self.plan["tasks"][1]
        p = self.root / anchor_path(t)
        original = p.read_text()
        for before,after in ((":modification:",":addition:"),(":V01:",":V99:"),
                             (":A01 |",":A09 |"),("Establish the specified fixture behavior","Invent a different fixture behavior")):
            with self.subTest(replacement=after):
                p.write_text(original.replace(before,after))
                with self.assertRaisesRegex(RddError,"Orphaned or misplaced"):
                    anchors_verify(self.root,self.plan,self.state)
                unchanged = p.read_bytes()
                with self.assertRaises(RddError):
                    remove_anchor(self.root,t,self.plan)
                self.assertEqual(p.read_bytes(),unchanged)
        p.write_text(original)

    def test_marker_inside_code_is_rejected_and_never_removed(self):
        t = self.plan["tasks"][0]
        original = 'value = "' + marker_line(t, plan=self.plan) + '"\n'
        p = self.write(anchor_path(t), original)
        with self.assertRaisesRegex(RddError, "Malformed.*marker"):
            remove_anchor(self.root, t, self.plan)
        self.assertEqual(p.read_text(), original)

    def test_malformed_marker_prefix_is_not_silently_ignored(self):
        materialize(self.root, self.plan, self.state)
        p = self.root / anchor_path(self.plan["tasks"][0])
        p.write_text(p.read_text() + "# RDD:P01:TYPO unfinished work\n")
        with self.assertRaisesRegex(RddError, "Malformed.*marker"):
            anchors_verify(self.root, self.plan, self.state)

    @unittest.skipUnless(os.name == "posix", "POSIX script execution is required")
    def test_anchor_updates_preserve_executable_script(self):
        t = task("T010", "modification", "scripts/fixture.py", [])
        plan = dict(schema_version=2,tasks=[t], verticals=[dict(id="V01",tasks=[t["id"]])], target_paths=t["writes"], shells=[])
        self.plan = plan
        state = dict(tasks={t["id"]: dict(status="pending")})
        original = "#!/usr/bin/env python3\nprint('fixture-runnable')\n"
        marker = marker_line(t, plan=self.plan) + "\n"
        for operation in ("materialize", "remove_anchor"):
            with self.subTest(operation=operation):
                path = self.write(t["sites"][0]["path"], original + (marker if operation == "remove_anchor" else ""))
                path.chmod(0o755)
                if operation == "materialize":
                    materialize(self.root, plan, state)
                    self.assertEqual(path.read_text(), original + marker)
                else:
                    remove_anchor(self.root, t, self.plan)
                    self.assertEqual(path.read_text(), original)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755)
                result = subprocess.run([str(path)], check=True, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.stdout, "fixture-runnable\n")

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
        remove_anchor(self.root, self.plan["tasks"][0], self.plan)
        with self.assertRaisesRegex(RddError, "exactly one anchor"):
            anchors_verify(self.root, self.plan, self.state)
        self.assertEqual(self.state["tasks"]["T001"]["status"], "pending")
        materialize(self.root, self.plan, self.state)
        self.assertEqual(anchors_verify(self.root, self.plan, self.state)["remaining"], 4)

    def test_duplicate_marker_is_rejected_without_rewriting_evidence(self):
        materialize(self.root, self.plan, self.state)
        t = self.plan["tasks"][0]
        p = self.root / anchor_path(t)
        p.write_text(p.read_text() + marker_line(t, plan=self.plan) + "\n")
        original = p.read_text()
        with self.assertRaisesRegex(RddError, "Duplicate anchor"):
            materialize(self.root, self.plan, self.state)
        self.assertEqual(p.read_text(), original)

    def test_wrong_phase_and_unknown_marker_are_detected(self):
        materialize(self.root, self.plan, self.state)
        p = self.root / "tests/behavior.py"
        p.write_text(p.read_text().replace("RDD:P01:tests:V01:T001:A01", "RDD:P02:tests:V01:T001:A01"))
        original = p.read_text()
        with self.assertRaisesRegex(RddError, "Orphaned or misplaced"):
            anchors_verify(self.root, self.plan, self.state)
        self.assertEqual(p.read_text(), original)
        p.write_text(original.replace("RDD:P02:tests:V01:T001:A01", "RDD:P01:tests:V01:T999:A01"))
        with self.assertRaisesRegex(RddError, "Orphaned or misplaced"):
            anchors_verify(self.root, self.plan, self.state)

    def test_done_task_cannot_retain_a_marker(self):
        materialize(self.root, self.plan, self.state)
        self.state["tasks"]["T001"]["status"] = "done"
        with self.assertRaisesRegex(RddError, "Completed task still has an anchor"):
            anchors_verify(self.root, self.plan, self.state)
        remove_anchor(self.root, self.plan["tasks"][0], self.plan)
        self.assertEqual(anchors_verify(self.root, self.plan, self.state)["remaining"], 3)

    def test_t001_removal_preserves_t0010_and_source(self):
        short = task("T001", "tests", "tests/shared.py", [])
        long = task("T0010", "tests", "tests/shared.py", [])
        plan = dict(tasks=[short,long],verticals=[dict(id="V01",tasks=[short["id"],long["id"]])])
        p = self.write("tests/shared.py", "value = 42\n" + marker_line(short, plan=plan) + "\n" + marker_line(long, plan=plan) + "\n")
        remove_anchor(self.root, short, plan)
        self.assertEqual(p.read_text(), "value = 42\n" + marker_line(long, plan=plan) + "\n")

    def test_shared_marker_line_fails_without_deleting_another_task(self):
        first = task("T001", "tests", "tests/shared.py", [])
        second = task("T002", "tests", "tests/shared.py", [])
        plan = dict(tasks=[first,second],verticals=[dict(id="V01",tasks=[first["id"],second["id"]])])
        original = marker_line(first, plan=plan) + " " + marker_line(second, plan=plan) + "\n"
        p = self.write("tests/shared.py", original)
        with self.assertRaisesRegex(RddError, "share one line"):
            remove_anchor(self.root, first, plan)
        self.assertEqual(p.read_text(), original)

    def test_sidecar_preserves_empty_json_shell(self):
        t = task("T010", "addition", "app/settings.json", [])
        t["sites"][0]["mode"] = "sidecar"
        plan = dict(schema_version=2,tasks=[t],verticals=[dict(id="V01",tasks=[t["id"]])], target_paths=["app/settings.json"], shells=[])
        self.plan = plan
        state = dict(tasks={"T010": dict(status="pending")})
        materialize(self.root, plan, state)
        self.assertFalse((self.root / "app/settings.json").exists())
        self.assertIn("RDD:P01:addition:V01:T010:A01", (self.root / anchor_path(t)).read_text())
        self.assertEqual(anchors_verify(self.root, plan, state)["remaining"], 1)


if __name__ == "__main__":
    unittest.main()
