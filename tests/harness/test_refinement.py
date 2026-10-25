"""Focused conversational-refinement regressions through the controller boundary.

Run with ``python3 -m unittest discover -s tests/harness -p test_refinement.py -v``.
Fixtures are disposable repositories; no application run is created in the checkout.
"""
from pathlib import Path
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.rdd import artifacts
from tools.rdd.adapters import CommandResult
from tools.rdd.checks import platform_name
from tools.rdd.common import RddError, digest, event, file_hash, head, read_json, source_digest, write_json
from tools.rdd.engine import Controller
from tools.rdd.nodes import NODES


REPOSITORY = Path(__file__).resolve().parents[2]
SNAPSHOT = "docs/specs/refinement.json"
STATEMENT = "Keep at most 3 items, preserve insertion order, and never overwrite an existing item."


def build_fixture(root):
    """Return a started disposable harness for tests or a bounded Codex smoke."""
    for relative in (".codex", ".rdd/schemas"):
        shutil.copytree(REPOSITORY / relative, root / relative)
    shutil.copyfile(REPOSITORY / ".rdd/config.json", root / ".rdd/config.json")
    shutil.copyfile(REPOSITORY / ".gitignore", root / ".gitignore")
    (root / "requirements").mkdir()
    (root / "requirements/requirements.md").write_text(
        "# Fixture requirements\n\n**FR-001 Ordered items**\n"
        "The collection shall retain accepted items in insertion order.\n"
        "Acceptance: Reading retained items returns their original ordering.\n")
    write_json(root / ".rdd/run.json", {"schema_version": 1, "run_id": None})
    fixture = HarnessFixture(root)
    fixture.git("init", "-b", "test-refinement")
    fixture.git("config", "user.name", "Refinement test")
    fixture.git("config", "user.email", "refinement@example.invalid")
    fixture.commit("Disposable fixture")
    fixture.controller.start("regenerate", "refinement-test")
    return fixture


class HarnessFixture:
    """Small real-controller fixture, with only the external compiler runner mocked."""

    def __init__(self, root):
        self.root = root
        self.controller = Controller(root)

    def git(self, *arguments):
        return subprocess.run(["git", "-C", str(self.root), *arguments], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message="Fixture source"):
        self.git("add", ".")
        self.git("commit", "--allow-empty", "-m", message)

    def text(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def input_file(self, value, name="input.json"):
        path = self.root / ".rdd/runtime" / name
        write_json(path, value)
        return path

    def refine(self, operation, record, session="coordinator"):
        return self.controller.spec_refine(self.input_file({"schema_version": 1,
            "operation": operation, "session_id": session, "record": record}))

    def question(self, identity="Q-LIMIT", **changes):
        record = dict(id=identity, revision=1, previous_revision=None,
            issue="Which limit and ordering must retained items use?", material=True,
            requirements=["FR-001"], nodes=["S6"], options=[{"id": "bounded", "text": STATEMENT}])
        record.update(changes)
        self.refine("question", record)
        return record

    def decision(self, identity="D-LIMIT", **changes):
        record = dict(id=identity, revision=1, previous_revision=None,
            statement=STATEMENT, requirements=["FR-001"], nodes=["S6"],
            provenance={"kind": "direct", "turn": "user:1", "text": STATEMENT, "qualifications": ""})
        record.update(changes)
        self.refine("decision", record)
        return record

    def observe(self, findings=None, resolutions=None):
        c, state = self.controller, self.controller.state()
        report = dict(schema_version=2, kind="live", stage="specification", phase=None,
            model=c.profile_settings("rdd_reviewer")["model"], reviewer="rdd_reviewer",
            session_id="live-reviewer", summary="Synthetic independent observation of fixture source.",
            source_commit=head(self.root), source_digest=source_digest(self.root),
            requirements_digest=state["requirements_digest"], spec_digest=None, plan_digest=None,
            findings=findings or [], resolutions=resolutions or [])
        return c.review_live_record(self.input_file(report, "review.json"))

    def claim(self, node, writes):
        role = NODES[node]["responsible_roles"][0]
        session = "author-S0" if node == "S7" else "author-" + node
        return self.controller.workflow_claim(node, session, role, writes)["claim"]

    def record(self, node, evidence=None):
        claim = self.controller.state()["workflow_nodes"][node]["claim"]
        return self.controller.workflow_record(self.input_file({"schema_version": 2, "node": node,
            "attempt": claim["attempt"], "session_id": claim["session_id"],
            "input_digest": claim["input_digest"], "outputs": claim["writes"],
            "evidence_ids": evidence or []}, "node.json"))

    def begin_s6(self, extra_writes=()):
        """Reach the real S6 owner claim without bypassing node or reviewer guards."""
        c = self.controller
        c.spec_init()
        self.commit()
        self.observe()
        for node in ("S0", "S1", "S2", "S3", "S4", "S5"):
            path = "docs/specs/domain-inventory.json" if node == "S1" else f"docs/specs/{node}.md"
            self.claim(node, [path])
            if node == "S1":
                write_json(self.root / path, {"schema_version": 1,
                    "requirements_digest": c.state()["requirements_digest"],
                    "domains": [{"id": "D-ITEMS", "module": "items", "requirements": ["FR-001"],
                                 "behaviors": ["B-STATE"], "invariants": ["I-ORDER"]}],
                    "supporting_modules": [], "interactions": []})
            else:
                self.text(path, f"# {node} fixture evidence\n\nBounded artifact for real workflow tests.\n")
            self.record(node)
            self.observe()
        writes = [".rdd/spec.json", "docs/specs/solution.md", SNAPSHOT,
                  "contracts/items.proto", "gen/rust/items.rs", "gen/rust/.rdd-generated.json", *extra_writes]
        self.claim("S6", writes)
        self.write_spec()

    def write_spec(self):
        c = self.controller
        self.text("docs/specs/solution.md", "# Ordered collection\n\n" + STATEMENT + "\n")
        self.text("contracts/items.proto", 'syntax = "proto3"; package fixture.items; message State { repeated string items = 1; }\n')
        self.text("gen/rust/items.rs", "// Synthetic fixture binding; compiler execution is mocked.\npub struct State { pub items: Vec<String> }\n")
        metadata_path, binding = "gen/rust/.rdd-generated.json", "gen/rust/items.rs"
        write_json(self.root / metadata_path, {"descriptor_sha256": "a" * 64, "contract_index": {
            "schema_version": 1, "services": [], "source_hashes": {
                "contracts/items.proto": file_hash(self.root / "contracts/items.proto")},
            "binding_files": [binding], "support_files": [metadata_path],
            "binding_sources": {binding: ["contracts/items.proto"]}, "types": [{
                "symbol": "fixture.items.State", "kind": "message", "package": "fixture.items",
                "source": "contracts/items.proto", "generated_path": binding,
                "descriptor_source": "items.proto", "rust_type": "rdd_contracts::fixture::items::State"}]}})
        spec = c.spec()
        authors = c.state()["authors"]["specification"]
        source = "docs/specs/solution.md"
        spec.update(author_sessions=authors, change_summary="Synthetic collection specification for controller regression tests.",
            documents=[source, "docs/specs/domain-inventory.json", SNAPSHOT],
            contract_files=["contracts/items.proto"], generated_files=[binding, metadata_path], project_check_ids=["C-APP"],
            shared_generated_files=[{"path": metadata_path, "purpose": "Fixture descriptor metadata"}],
            domain_inventory={"path": "docs/specs/domain-inventory.json",
                "sha256": file_hash(self.root / "docs/specs/domain-inventory.json"),
                "s1_output_digest": c.state()["workflow_nodes"]["S1"]["output_digest"]},
            modules=[{"id": "items", "requirements": ["FR-001"], "owns_paths": ["modules/items.rs"],
                "contract_paths": ["contracts/items.proto"], "depends_on": [], "provided_services": [],
                "consumed_operations": [], "generated_paths": [binding], "adapter_error_specs": [source],
                "qualification_checks": {"provider": [], "consumer": [], "negative_signature": [],
                                         "dependency_direction": ["C-CONTRACTS"], "compatibility": ["C-CONTRACTS"]},
                "implementation_checks": {"provider": [], "consumer": [], "dependency_direction": ["C-APP"],
                                          "compatibility": ["C-APP"], "semantics": ["C-APP"]},
                "contract_package": "fixture.items", "provided_types": ["fixture.items.State"],
                "consumed_types": [], "public_exports": [{"symbol": "items::State", "path": "modules/items.rs",
                    "kind": "type", "binding": "fixture.items.State", "specifications": [source]}]}],
            solution_elements=[{"id": eid, "kind": kind, "requirements": ["FR-001"], "scenarios": ["G01"],
                                "specifications": [source], "module": "items", "behavior": behavior}
                               for eid, kind, behavior in (("D-ITEMS", "subdomain", "positive"),
                                   ("B-STATE", "enabling", "support"), ("I-ORDER", "invariant", "positive"))],
            target_tree=[{"path": "modules/items.rs", "kind": "file", "owner": "D-ITEMS",
                          "purpose": "Retained collection invariant owner", "disposition": "add"}],
            scenarios=[{"id": "G01", "requirements": ["FR-001"], "kind": "golden",
                "description": "Read inserted items in order", "expected": STATEMENT,
                "check_ids": ["C-APP"], "solution_elements": ["D-ITEMS", "B-STATE", "I-ORDER"],
                "preconditions": "An empty collection", "fixture": "Three distinct items",
                "stimulus": "Insert each item, then read the collection",
                "verification_method": "Assert the returned sequence equals the inserted sequence"}],
            requirement_map=[{"requirement": "FR-001", "specifications": [source], "scenarios": ["G01"]}],
            environments=[{"id": "E-HOST", "platform": platform_name(), "host_profile": None}],
            resources=[{"id": "R-REQ", "kind": "repository", "path": "requirements/requirements.md",
                "version": None, "probe_check_ids": [], "environments": ["E-HOST"],
                "availability": "baseline", "required_at": "specification"}])
        contract = spec["checks"][0]
        contract.update(environments=["E-HOST"], requires=["R-REQ"])
        spec["checks"].append({**contract, "id": "C-APP", "kind": "test",
            "argv": ["{python}", "tests/collection.py"], "scenario_ids": ["G01"],
            "results_path": ".rdd/evidence/results/collection.json"})
        write_json(self.root / ".rdd/spec.json", spec)

    def publish(self, decision="D-LIMIT", revision=1, publication_revision=1, path="docs/specs/solution.md", session="author-S6", text=STATEMENT):
        return self.refine("publish", {"decision": {"id": decision, "revision": revision},
            "revision": publication_revision, "previous_revision": publication_revision - 1 or None,
            "path": path, "text": text, "scenarios": ["G01"]}, session)

    def complete_s6(self):
        self.controller.spec_snapshot("author-S6")
        self.record("S6")
        self.observe()

    def compiler_result(self, argv, **unused):
        """Synthetic external tool output; receipt and acceptance validation stay real."""
        names = ("buf-version", "cargo-version", "buf-lint", "buf-build", "generate-contracts", "compile-host",
                 "signature-positive", "signature-negative", "boundary-provider", "boundary-consumer", "boundary-dependency-negative")
        steps = []
        for name in names:
            code = {"signature-negative": "E0050", "boundary-dependency-negative": "E0432"}.get(name, "")
            embedded = {"name": name, "command": ["fixture-compiler", name], "exit_code": int(bool(code)),
                        "expected_failure": bool(code), "stdout": code, "stderr": "", "timed_out": False, "output_truncated": False}
            hashed = hashlib.sha256((json.dumps(embedded, indent=2) + "\n").encode()).hexdigest()
            steps.append({**embedded, "log_digest": hashed, "sha256": hashed})
        report = {"status": "passed", "write": False, "changed_files": [], "descriptor_sha256": "a" * 64,
            "qualified_services": [], "qualified_operations": [], "targets": ["host"],
            "generated_files": {p.removeprefix("gen/rust/"): file_hash(self.root / p)
                                for p in self.controller.spec()["generated_files"]},
            "boundary_negative_proofs": [], "boundary_provider": "passed", "boundary_consumer": "passed",
            "signature_positive": "passed", "dependency_direction_negative": "expected_E0432",
            "signature_negative": "expected_E0050", "steps": steps}
        return CommandResult(tuple(argv), 0, json.dumps(report))

    def prepare_reviews(self):
        """Reach final review through actual readiness, with synthetic external compilation."""
        self.claim("S7", ["docs/specs/readiness.md"])
        self.text("docs/specs/readiness.md", "# Fixture readiness\n\nExternal compiler observations are synthetic test data.\n")
        self.commit()
        with patch("tools.rdd.checks.run_argv", side_effect=self.compiler_result):
            ready = self.controller.readiness("specification")
        self.record("S7", ready["evidence"])
        self.observe()
        return ready

    def review(self, perspective, session=None):
        c, spec = self.controller, self.controller.spec()
        report = {"schema_version": 2, "kind": "final", "stage": "specification", "perspective": perspective,
            "reviewer": "rdd_reviewer", "model": c.profile_settings("rdd_reviewer")["model"],
            "session_id": session or "final-" + perspective, "decision": "pass",
            "summary": "Synthetic independent final review of this exact fixture candidate.", "findings": [],
            "candidate": c.stage_candidate("specification"), "review_cursor": len(c.state()["live_reviews"]),
            "evidence_ids": c.state()["readiness"]["specification"]["evidence"],
            "coverage": {"requirements": ["FR-001"], "elements": [e["id"] for e in spec["solution_elements"]],
                         "scenarios": ["G01"], "checks": [c["id"] for c in spec["checks"]], "tasks": []}}
        return c.stage_review_record(self.input_file(report, "final-review.json"))


class RefinementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rdd-refinement-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixture = build_fixture(self.root)
        self.controller = self.fixture.controller
        self.addCleanup(self.controller.close)

    def reject_historical_publication(self, decision="D-LIMIT"):
        """A still-open historical claim cannot publish newly changed inputs."""
        path = self.root / ".rdd/runtime/checkpoint.json"
        self.controller.export_run(path)
        checkpoint = read_json(path)
        state = checkpoint["state"]
        self.controller.validate_checkpoint_state(state, checkpoint)
        claim = state["workflow_nodes"]["S6"]["claim"]
        publications = state["refinement"]["publications"]
        previous = max((p["revision"] for p in publications if p["decision"]["id"] == decision), default=0)
        publication = {"decision": {"id": decision, "revision": 1}, "revision": previous + 1,
            "previous_revision": previous or None, "path": "docs/specs/solution.md", "text": STATEMENT,
            "scenarios": ["G01"], "sha256": file_hash(self.root / "docs/specs/solution.md"),
            "claim": {"node": "S6", **{k: claim[k] for k in ("attempt", "session_id", "input_digest")}}}
        publications.append(publication)
        event(state, "refinement_recorded", collection="publications", index=len(publications) - 1,
              record_digest=digest(publication))
        with self.assertRaises(RddError):
            self.controller.validate_checkpoint_state(state, checkpoint)

    def test_start_exposes_current_refinement_completeness(self):
        status = self.controller.status()
        self.assertTrue("refinement" in status,
                      "A started run must expose its current clarification completeness")
        self.assertEqual(status["refinement"]["schema_version"], 1)
        self.assertEqual(status["refinement"]["unresolved"], [])

    def test_capture_truthful_provenance_and_restart_without_publication(self):
        f = self.fixture
        f.question()
        f.decision(provenance={"kind": "choice", "question": "Q-LIMIT", "revision": 1,
            "option": "bounded", "turn": "user:2", "text": "Use bounded, but never overwrite.",
            "qualifications": "but never overwrite"})
        f.decision("D-DIRECT", statement="Use the existing local collection only.",
            provenance={"kind": "direct", "turn": "user:3", "text": "Use the existing local collection only.",
                        "qualifications": "only"})
        excerpt = "The collection shall retain accepted items in insertion order."
        reference = {"path": "requirements/requirements.md", "text": excerpt,
                     "sha256": hashlib.sha256(excerpt.encode()).hexdigest()}
        f.decision("D-INHERITED", statement=excerpt, provenance={"kind": "inherited", **reference})
        authority = "The implementation owner may choose a private representation that preserves insertion ordering."
        f.text("docs/specs/delegation.md", "# Authorized discretion\n\n" + authority + "\n")
        delegated_reference = {"path": "docs/specs/delegation.md", "text": authority,
                               "sha256": hashlib.sha256(authority.encode()).hexdigest()}
        f.decision("D-DELEGATED", statement="Use a private sequence to preserve insertion ordering.",
            provenance={"kind": "delegated", "authority": delegated_reference,
            "scope": "Choose a private representation preserving insertion order.",
            "rationale": "A sequence preserves the requirement without new public behavior."})
        self.controller.close()
        restarted = Controller(self.root)
        self.addCleanup(restarted.close)
        status = restarted.status()["refinement"]
        self.assertFalse(status["ready"])
        self.assertEqual(status["unpublished"], ["D-DELEGATED", "D-DIRECT", "D-INHERITED", "D-LIMIT"])
        self.assertEqual(status["unresolved"], ["Q-LIMIT"])
        decisions = restarted.state()["refinement"]["decisions"]
        self.assertEqual([d["record"]["provenance"]["kind"] for d in decisions],
                         ["choice", "direct", "inherited", "delegated"])
        self.assertEqual(decisions[0]["record"]["provenance"]["qualifications"], "but never overwrite")

    def test_invalid_or_ambiguous_capture_keeps_material_question_open(self):
        f = self.fixture
        f.question()
        baseline = self.controller.state()["refinement"]
        for provenance in (
            {"kind": "choice", "question": "Q-MISSING", "revision": 1, "option": "bounded",
             "turn": "user:2", "text": "yes", "qualifications": ""},
            {"kind": "choice", "question": "Q-LIMIT", "revision": 1, "option": "missing",
             "turn": "user:2", "text": "yes", "qualifications": ""},
            {"kind": "direct", "turn": "user:2", "qualifications": ""},
            {"kind": "agent", "text": "The user probably agrees."},
        ):
            with self.subTest(provenance=provenance), self.assertRaises(RddError):
                f.decision(provenance=provenance)
            self.assertEqual(self.controller.state()["refinement"], baseline)
        self.assertEqual(self.controller.status()["refinement"]["unresolved"], ["Q-LIMIT"])
        with self.assertRaises(RddError):
            f.question("Q-STYLE", material=False, issue="Use shorter progress updates?")

    def test_question_revisions_reject_stale_choice_and_unbounded_deferral(self):
        f = self.fixture
        q = f.question()
        f.question(revision=2, previous_revision=1, issue="Which revised limit must retained items use?")
        with self.assertRaisesRegex(RddError, "superseded"):
            f.decision(provenance={"kind": "choice", "question": q["id"], "revision": 1,
                "option": "bounded", "turn": "user:2", "text": "Use bounded.", "qualifications": ""})
        with self.assertRaisesRegex(RddError, "deferral"):
            f.question("Q-DEFER", status="deferred")
        f.question("Q-DEFER", status="deferred", disposition="Private sequence representation remains the owner's discretion; insertion ordering is fixed.")
        self.assertEqual(self.controller.status()["refinement"]["unresolved"], ["Q-LIMIT"])

    def test_publication_uses_owner_claim_exact_statement_and_scenarios(self):
        f = self.fixture
        f.decision()
        f.begin_s6()
        for session, path, text in (
            ("coordinator", "docs/specs/solution.md", STATEMENT),
            ("author-S6", "docs/specs/S1.md", STATEMENT),
            ("author-S6", "docs/specs/solution.md", "Keep items."),
        ):
            with self.subTest(session=session, path=path), self.assertRaises(RddError):
                f.publish(session=session, path=path, text=text)
        claim_before = copy.deepcopy(self.controller.state()["workflow_nodes"]["S6"]["claim"])
        f.publish()
        self.assertEqual(self.controller.state()["workflow_nodes"]["S6"]["claim"], claim_before)
        original = (self.root / "docs/specs/S3.md").read_text()
        for revision, text in enumerate(("# Corrected S3\n\nConcrete scenario detail.\n", original), 1):
            finding = "F-S3-" + str(revision)
            f.observe([{"id": finding, "severity": "blocking", "requirements": ["FR-001"],
                "tasks": [], "nodes": ["S3"], "path": "docs/specs/S3.md", "message": "Correct scenario detail.",
                "evidence": "A concrete scenario detail needs independent correction."}])
            self.controller.workflow_claim("S3", "author-S3", "rdd_verification_designer",
                                           ["docs/specs/S3.md"], finding)
            f.text("docs/specs/S3.md", text)
            f.observe(resolutions=[{"finding_id": finding,
                "evidence": "Reviewer independently verified the exact scenario correction."}])
            f.record("S3")
            f.observe()
            if revision == 1:
                with self.assertRaisesRegex(RddError, "inputs changed"):
                    f.publish(publication_revision=2)
                self.reject_historical_publication()
            else:
                # Latest handoff identity is current again after an exact restoration.
                f.publish(publication_revision=2)
        f.complete_s6()
        self.assertTrue(self.controller.status()["refinement"]["ready"])
        self.assertEqual(self.controller.spec_validate()["requirements"], 1)
        pub = self.controller.state()["refinement"]["publications"][0]
        self.assertEqual(pub["text"], STATEMENT)
        self.assertEqual(pub["scenarios"], ["G01"])
        self.assertEqual(pub["claim"]["session_id"], "author-S6")

    def test_publication_missing_scenario_cannot_make_snapshot_ready(self):
        f = self.fixture
        f.decision()
        f.begin_s6()
        f.refine("publish", {"decision": {"id": "D-LIMIT", "revision": 1}, "revision": 1,
            "previous_revision": None, "path": "docs/specs/solution.md", "text": STATEMENT,
            "scenarios": ["UNKNOWN"]}, "author-S6")
        with self.assertRaisesRegex(RddError, "stale"):
            self.controller.spec_snapshot("author-S6")
        self.assertFalse((self.root / SNAPSHOT).exists())

    def test_unpublished_answer_and_snapshot_ownership_block_closure(self):
        f = self.fixture
        f.decision()
        f.begin_s6()
        with self.assertRaisesRegex(RddError, "S6"):
            self.controller.spec_snapshot("coordinator")
        with self.assertRaisesRegex(RddError, "unpublished"):
            self.controller.spec_snapshot("author-S6")
        self.assertFalse((self.root / SNAPSHOT).exists())

    def test_reviewer_is_only_resolver_for_linked_conflict(self):
        f = self.fixture
        f.observe([{"id": "F-LIMIT", "severity": "blocking", "requirements": ["FR-001"],
            "tasks": [], "nodes": ["S6"], "path": "", "message": "Conflicting capacity directions.",
            "evidence": "Two qualified directions disagree about the item limit."}])
        f.question(finding="F-LIMIT", status="resolved")
        self.assertEqual(self.controller.status()["refinement"]["unresolved"], ["Q-LIMIT"])
        f.observe(resolutions=[{"finding_id": "F-LIMIT", "evidence": "Independent reviewer verified that the canonical limit and ordering preserve the accepted direction."}])
        self.assertEqual(self.controller.status()["refinement"]["unresolved"], [])
        with self.assertRaisesRegex(RddError, "reviewer"):
            # A reviewer session cannot be registered as an author through refinement.
            f.refine("question", {"id": "Q-REVIEWER", "revision": 1, "previous_revision": None,
                "issue": "May I author this?", "material": True}, session="live-reviewer")

    def test_scoped_question_preserves_unrelated_completed_intake(self):
        f = self.fixture
        f.decision()
        f.begin_s6()
        original = copy.deepcopy(self.controller.state()["workflow_nodes"])
        state = self.controller.state()
        before = digest(self.controller._node_input(state, "S6", self.controller._node_records(state)))
        f.observe()
        state = self.controller.state()
        self.assertEqual(digest(self.controller._node_input(state, "S6", self.controller._node_records(state))), before)
        # A material S2 concern affects that owner, while S0 intake stays current.
        f.question("Q-S2", nodes=["S2"], status="deferred",
            disposition="Private measurement sample ordering remains free; the acceptance threshold is unchanged.")
        records = {row["id"]: row for row in self.controller.workflow_nodes()["nodes"]}
        self.assertEqual(records["S0"]["status"], "complete")
        self.assertEqual(records["S2"]["status"], "stale")
        self.assertEqual(self.controller.state()["workflow_nodes"]["S6"]["claim"], original["S6"]["claim"])
        self.assertEqual(len(records["S0"]["attempts"]), 1)

    def test_reopened_question_revision_invalidates_current_claim(self):
        f = self.fixture
        f.question(status="deferred", disposition="Private representation remains free; ordering is fixed.")
        f.begin_s6()
        f.question(revision=2, previous_revision=1, status="open")
        with self.assertRaisesRegex(RddError, "inputs changed"):
            f.record("S6")

    def test_review_resolution_preserves_current_correction_claim_inputs(self):
        f = self.fixture
        f.begin_s6()
        self.controller.workflow_release("S6", "Return for independently reviewed correction.")
        f.observe([{"id": "F-CORRECTION", "severity": "blocking", "requirements": ["FR-001"],
            "tasks": [], "nodes": ["S6"], "path": "docs/specs/solution.md", "message": "Verify the stated ordering.",
            "evidence": "A concrete ordering case needs an independent check."}])
        f.question(finding="F-CORRECTION", status="resolved")
        self.controller.workflow_claim("S6", "author-S6", "rdd_contract_architect",
            [".rdd/spec.json", "docs/specs/solution.md", SNAPSHOT,
             "contracts/items.proto", "gen/rust/items.rs", "gen/rust/.rdd-generated.json"], "F-CORRECTION")
        state = self.controller.state()
        before = digest(self.controller._node_input(state, "S6", self.controller._node_records(state)))
        f.observe(resolutions=[{"finding_id": "F-CORRECTION", "evidence": "Reviewer independently verified exact ordering against the accepted fixture requirement."}])
        state = self.controller.state()
        self.assertEqual(digest(self.controller._node_input(state, "S6", self.controller._node_records(state))), before)
        f.complete_s6()

    def test_late_material_decision_rejects_live_claim_output(self):
        f = self.fixture
        f.begin_s6()
        f.decision()
        with self.assertRaisesRegex(RddError, "inputs changed"):
            f.record("S6")
        with self.assertRaisesRegex(RddError, "inputs changed"):
            f.publish()
        self.reject_historical_publication()

    def test_supersession_narrowed_scope_and_transitive_prerequisites(self):
        f = self.fixture
        f.decision("D-A", nodes=["S2"])
        f.decision("D-B", nodes=["S3"], prerequisites=[{"id": "D-A", "revision": 1}])
        f.decision("D-C", nodes=["S6"], prerequisites=[{"id": "D-B", "revision": 1}])
        f.begin_s6()
        claim = self.controller.state()["workflow_nodes"]["S6"]["claim"]
        before = claim["input_digest"]
        f.decision("D-A", revision=2, previous_revision=1, nodes=["S5"], statement="Retain at most 2 items.")
        state = self.controller.state()
        records = self.controller._node_records(state)
        self.assertNotEqual(digest(self.controller._node_input(state, "S6", records)), before)
        self.assertEqual(records["S2"]["status"], "stale", "Narrowing scope cannot resurrect the prior affected owner")
        self.assertTrue({"D-B", "D-C"} <= set(self.controller.status()["refinement"]["stale"]))
        with self.assertRaisesRegex(RddError, "inputs changed"):
            f.record("S6")
        with self.assertRaisesRegex(RddError, "inputs changed"):
            f.publish(decision="D-C")
        self.reject_historical_publication("D-C")

    def test_source_freshness_propagates_through_multiple_prerequisites(self):
        f = self.fixture
        f.text("docs/specs/authority.md", "# Governing source\n\nThe collection stays local.\n")
        source = {"path": "docs/specs/authority.md", "sha256": file_hash(self.root / "docs/specs/authority.md")}
        f.decision("D-A", nodes=["S0"], sources=[source])
        f.decision("D-B", nodes=["S2"], prerequisites=[{"id": "D-A", "revision": 1}])
        f.decision("D-C", nodes=["S6"], prerequisites=[{"id": "D-B", "revision": 1}])
        f.begin_s6()
        state = self.controller.state()
        before = digest(self.controller._node_input(state, "S6", self.controller._node_records(state)))
        f.text(source["path"], "# Governing source\n\nThe collection is shared.\n")
        state = self.controller.state()
        after = digest(self.controller._node_input(state, "S6", self.controller._node_records(state)))
        self.assertNotEqual(after, before)
        self.assertTrue({"D-A", "D-B", "D-C"} <= set(self.controller.status()["refinement"]["stale"]))

    def test_question_only_source_is_frozen_and_stateless_validation_rechecks_it(self):
        f = self.fixture
        source_path = "docs/specs/question-authority.md"
        f.text(source_path, "# Governing evidence\n\nThe host's file paths stay local.\n")
        f.question(status="deferred", disposition="Private path layout remains free within the fixed local boundary.",
            sources=[{"path": source_path, "sha256": file_hash(self.root / source_path)}])
        retired = "docs/specs/retired-seed.md"
        f.text(retired, "# Obsolete specification seed\n")
        f.begin_s6([retired])
        (self.root / retired).unlink()
        f.complete_s6()
        f.commit()
        self.assertEqual(self.controller.state()["workflow_nodes"]["S6"]["outputs"][retired], "MISSING")
        claim = copy.deepcopy(self.controller.state()["workflow_nodes"]["S6"]["claim"])
        source_before = source_digest(self.root)
        f.question("Q-S7", nodes=["S7"], status="deferred",
            disposition="Readiness evidence formatting is discretionary; accepted behavior stays fixed.")
        self.assertEqual(source_digest(self.root), source_before)
        self.assertIn("S6", self.controller.workflow_next()["ready"],
                      "A late readiness-only question still needs an S6 snapshot refresh path")
        self.assertEqual(self.controller.state()["workflow_nodes"]["S6"]["claim"], claim)
        f.observe([{"id": "F-S7", "severity": "blocking", "requirements": ["FR-001"],
            "tasks": [], "nodes": ["S7"], "path": source_path, "message": "Confirm the local source boundary.",
            "evidence": "Readiness must independently verify the governing path remains local."}])
        f.question("Q-S7", revision=2, previous_revision=1, nodes=["S7"], status="resolved", finding="F-S7")
        with self.assertRaisesRegex(RddError, "output inventory"):
            f.claim("S6", [SNAPSHOT])
        refreshed = f.claim("S6", claim["writes"])
        f.observe(resolutions=[{"finding_id": "F-S7", "evidence": "Reviewer verified the source boundary and the retained discretion against the requirement."}])
        self.assertEqual(refreshed["input_digest"], claim["input_digest"],
                         "Snapshot refresh must preserve unrelated scoped owner inputs")
        f.complete_s6()
        checkpoint_path = self.root / ".rdd/runtime/checkpoint.json"
        self.controller.export_run(checkpoint_path)
        checkpoint = read_json(checkpoint_path)
        self.controller.validate_checkpoint_state(checkpoint["state"], checkpoint)
        for relative in ("contracts/items.proto", retired):
            with self.subTest(changed_output=relative):
                output = self.root / relative
                accepted = output.read_bytes() if output.exists() else None
                output.write_bytes((accepted or b"") + b"// Changed after snapshot refresh.\n")
                records = {row["id"]: row for row in self.controller.workflow_nodes()["nodes"]}
                self.assertEqual(records["S6"]["status"], "stale")
                if accepted is None:
                    output.unlink()
                else:
                    output.write_bytes(accepted)
        f.prepare_reviews()
        f.review("semantic")
        f.review("execution")
        self.assertEqual(self.controller.spec_freeze()["status"], "specified")
        self.assertIn(source_path, self.controller.spec_candidate_lock()["files"])
        f.text(source_path, "# Governing evidence\n\nThe host's paths are remote.\n")
        with self.assertRaises(RddError):
            artifacts.spec_validate(self.root, self.controller.spec(),
                artifacts.requirements(self.root, "requirements/requirements.md"), self.controller.config)

    def test_snapshot_bootstrap_bookkeeping_and_clean_candidate_freeze(self):
        f = self.fixture
        f.decision()
        f.begin_s6()
        f.publish()
        self.assertFalse((self.root / SNAPSHOT).exists())
        f.complete_s6()
        snapshot_bytes = (self.root / SNAPSHOT).read_bytes()
        ready = f.prepare_reviews()
        with self.assertRaisesRegex(RddError, "distinct from authors"):
            f.review("semantic", session="author-S6")
        f.review("semantic")
        with self.assertRaisesRegex(RddError, "Both semantic and execution"):
            self.controller.spec_freeze()
        f.review("execution", session="final-semantic")
        with self.assertRaisesRegex(RddError, "distinct reviewer sessions"):
            self.controller.spec_freeze()
        f.review("execution")
        self.assertEqual(self.controller.spec_freeze()["status"], "specified")
        self.assertEqual((self.root / SNAPSHOT).read_bytes(), snapshot_bytes)
        self.assertEqual(self.controller.state()["spec_acceptance"]["candidate"], ready["candidate"])
        self.assertEqual(self.controller.require_refinement()["closure_digest"], read_json(self.root / SNAPSHOT)["closure_digest"])

    def test_late_runtime_only_material_issue_rejects_current_readiness_and_freeze(self):
        f = self.fixture
        f.begin_s6()
        f.complete_s6()
        ready = f.prepare_reviews()
        f.review("semantic")
        f.review("execution")
        sources_before = source_digest(self.root)
        f.question("Q-LATE", issue="Can the required offline database safely recover from this newly observed interruption?",
                   requirements=[], nodes=[])
        self.assertEqual(source_digest(self.root), sources_before)
        for action in (self.controller.spec_validate, lambda: self.controller.current_readiness("specification", ready["candidate"]),
                       self.controller.spec_freeze):
            with self.subTest(action=action), self.assertRaisesRegex(RddError, "unresolved"):
                action()
        self.assertFalse((self.root / ".rdd/spec.lock.json").exists())

    def test_snapshot_cannot_be_its_own_governing_source(self):
        f = self.fixture
        f.begin_s6()
        self.controller.spec_snapshot("author-S6")
        for path in (SNAPSHOT, ".rdd/run.json"):
            with self.subTest(path=path), self.assertRaisesRegex(RddError, "cannot govern"):
                f.decision(sources=[{"path": path, "sha256": file_hash(self.root / path)}])
        snapshot = read_json(self.root / SNAPSHOT)
        self.assertEqual(snapshot["decisions"], [])

    def test_claim_requires_replayable_refinement_sources(self):
        for mode in ("full", "excerpt", "inherited", "delegated", "question", "prerequisite",
                     "late-ignore", "untracked", "force-tracked"):
            with self.subTest(mode=mode):
                root = self.root / mode
                f = build_fixture(root)
                c = f.controller
                self.addCleanup(c.close)
                path = "docs/specs/probe.md" if mode in {"late-ignore", "untracked"} else "docs/specs/probe.log"
                f.text(path, STATEMENT + "\n")
                source = {"path": path, "sha256": file_hash(root / path)}
                if mode in {"excerpt", "inherited", "delegated"}:
                    source.update(text=STATEMENT, sha256=hashlib.sha256(STATEMENT.encode()).hexdigest())
                if mode == "force-tracked":
                    f.git("add", "-f", "--", path)
                if mode == "question":
                    f.question(nodes=["S0"], sources=[source])
                elif mode == "inherited":
                    f.decision(nodes=["S0"], provenance={"kind": "inherited", **source})
                elif mode == "delegated":
                    f.decision(nodes=["S0"], provenance={"kind": "delegated", "authority": source,
                        "scope": "Choose private storage preserving ordering.",
                        "rationale": "Private representation preserves all accepted behavior."})
                elif mode == "prerequisite":
                    f.decision("D-SOURCE", nodes=["S2"], sources=[source])
                    f.decision(nodes=["S0"], prerequisites=[{"id": "D-SOURCE", "revision": 1}])
                else:
                    f.decision(nodes=["S0"], sources=[source])
                if mode == "late-ignore":
                    f.text(".git/info/exclude", "/" + path + "\n")
                f.observe()
                if mode not in {"untracked", "force-tracked"}:
                    before = c.state()
                    with self.assertRaisesRegex(RddError, "claim inventory.*docs/specs/probe"):
                        f.claim("S0", ["docs/specs/intake.md"])
                    self.assertEqual(c.state(), before, "Rejected claims must preserve capture without attempts or events")
                else:
                    claim = f.claim("S0", ["docs/specs/intake.md"])
                    self.assertEqual(claim["sources"][path], file_hash(root / path))
                    self.assertEqual(claim["source_digest"], digest(claim["sources"]))
                    f.text(".git/info/exclude", "/" + path + "\n")
                    f.commit()
                    checkpoint = root / ".rdd/runtime/checkpoint.json"
                    c.export_run(checkpoint)
                    c.resume(checkpoint)
                    self.assertEqual(c.state()["workflow_nodes"]["S0"]["claim"], claim,
                                     "Historical replay must retain its inventory after ignore rules change")

    def test_existing_domain_and_contract_validators_still_reject_violations(self):
        f = self.fixture
        f.begin_s6()
        self.controller.spec_snapshot("author-S6")
        original = self.controller.spec()
        mutations = (
            lambda s: s["solution_elements"].pop(),
            lambda s: s["modules"][0].update(provided_types=[]),
            lambda s: s["domain_inventory"].update(s1_output_digest="b" * 64),
        )
        for mutate in mutations:
            value = copy.deepcopy(original)
            mutate(value)
            write_json(self.root / ".rdd/spec.json", value)
            with self.subTest(mutation=mutate), self.assertRaises(RddError):
                self.controller.spec_validate()
        write_json(self.root / ".rdd/spec.json", original)

    def test_export_resume_retains_provenance_and_rejects_history_tampering(self):
        f = self.fixture
        governing = "The existing collection stays local to this user."
        f.text("docs/specs/solution.md", governing + "\n")
        f.decision(sources=[{"path": "docs/specs/solution.md", "text": governing,
                            "sha256": hashlib.sha256(governing.encode()).hexdigest()}])
        second = "Reject duplicate items without changing retained items."
        f.decision("D-DUPLICATES", statement=second,
            provenance={"kind": "direct", "turn": "user:2", "text": second, "qualifications": ""})
        f.begin_s6()
        f.text("docs/specs/solution.md", governing + "\n\n" + STATEMENT + "\n")
        f.publish()
        f.text("docs/specs/solution.md", governing + "\n\n" + STATEMENT + "\n\n" + second + "\n")
        f.publish(decision="D-DUPLICATES", text=second)
        self.assertEqual(self.controller.status()["refinement"]["stale"], [],
                         "Publishing a second decision preserves the first exact canonical statement")
        # A later authorized publication revision retains the earlier observed file identity.
        f.publish(publication_revision=2)
        f.complete_s6()
        self.assertTrue(self.controller.status()["refinement"]["ready"])
        f.commit()
        checkpoint_path = self.root / ".rdd/runtime/checkpoint.json"
        self.controller.export_run(checkpoint_path)
        checkpoint = read_json(checkpoint_path)
        self.controller.resume(checkpoint_path)
        self.assertEqual(self.controller.state()["refinement"], checkpoint["state"]["refinement"])
        publications = checkpoint["state"]["refinement"]["publications"]
        self.assertEqual(len(publications), 3)
        self.assertNotEqual(publications[0]["sha256"], publications[-1]["sha256"],
                            "Historical publication bytes may differ after another decision is published in the same file")
        self.assertNotEqual(checkpoint["state"]["workflow_nodes"]["S6"]["claim"]["sources"]["docs/specs/solution.md"],
                            file_hash(self.root / "docs/specs/solution.md"),
                            "A historical excerpt claim survives unrelated changes in its shared document")
        self.controller.validate_checkpoint_state(checkpoint["state"], checkpoint)
        for mode in ("missing_revision", "missing_event", "reordered_events", "omitted_input", "reordered_claim",
                     "omitted_excerpt_source", "missing_excerpt_source", "publication_after_completion"):
            bad = copy.deepcopy(checkpoint)
            state = bad["state"]
            if mode == "missing_revision":
                state["refinement"]["decisions"].clear()
            elif mode == "missing_event":
                state["events"] = [e for e in state["events"] if e.get("action") != "refinement_recorded"]
            elif mode == "reordered_events":
                indices = [i for i, e in enumerate(state["events"]) if e.get("action") == "refinement_recorded"]
                state["events"][indices[0]], state["events"][indices[-1]] = state["events"][indices[-1]], state["events"][indices[0]]
            elif mode == "omitted_input":
                claim = state["workflow_nodes"]["S6"]["attempts"][0]["claim"]
                claim["inputs"]["refinement"]["decisions"].clear()
                claim["input_digest"] = digest(claim["inputs"])
                state["workflow_nodes"]["S6"]["claim"] = copy.deepcopy(claim)
                state["workflow_nodes"]["S6"]["input_digest"] = claim["input_digest"]
                for event in state["events"]:
                    if event.get("action") == "workflow_node_claimed" and event.get("node") == "S6":
                        event["input_digest"] = claim["input_digest"]
            elif mode == "reordered_claim":
                claim_index = next(i for i, e in enumerate(state["events"]) if e.get("action") == "workflow_node_claimed" and e.get("node") == "S6")
                decision_index = next(i for i, e in enumerate(state["events"]) if e.get("action") == "refinement_recorded" and e.get("collection") == "decisions")
                state["events"][claim_index], state["events"][decision_index] = state["events"][decision_index], state["events"][claim_index]
            elif mode in {"omitted_excerpt_source", "missing_excerpt_source"}:
                claim = state["workflow_nodes"]["S6"]["attempts"][0]["claim"]
                if mode == "omitted_excerpt_source":
                    claim["sources"].pop("docs/specs/solution.md")
                else:
                    claim["sources"]["docs/specs/solution.md"] = "MISSING"
                claim["source_digest"] = digest(claim["sources"])
                state["workflow_nodes"]["S6"]["claim"] = copy.deepcopy(claim)
            else:
                index = max(i for i, e in enumerate(state["events"]) if e.get("action") == "refinement_recorded" and e.get("collection") == "publications")
                publication_event = state["events"].pop(index)
                terminal = next(i for i, e in enumerate(state["events"]) if e.get("action") == "workflow_node_completed" and e.get("node") == "S6")
                state["events"].insert(terminal + 1, publication_event)
            with self.subTest(mode=mode), self.assertRaises(RddError):
                self.controller.validate_checkpoint_state(state, bad)
        f.text("docs/specs/solution.md", "The collection is shared remotely.\n\n" + STATEMENT + "\n\n" + second + "\n")
        self.assertIn("D-LIMIT", self.controller.status()["refinement"]["stale"])

    def test_old_policy_is_inspectable_but_cannot_mutate_or_relabel_approvals(self):
        state = self.controller.state()
        state["workflow_graph_digest"] = "0" * 64
        self.controller.store.put(state)  # Deliberate historical-policy fixture.
        self.assertTrue(self.controller.status()["workflow_nodes"]["historical"])
        checkpoint = self.root / ".rdd/runtime/historical.json"
        self.controller.export_run(checkpoint)
        self.assertEqual(read_json(checkpoint)["state"]["workflow_graph_digest"], "0" * 64)
        with self.assertRaisesRegex(RddError, "earlier workflow"):
            self.fixture.question()

    def test_frozen_refinement_requires_amendment_and_archives_snapshot(self):
        f = self.fixture
        f.begin_s6()
        f.complete_s6()
        f.prepare_reviews()
        f.review("semantic")
        f.review("execution")
        self.controller.spec_freeze()
        f.commit()
        original = (self.root / SNAPSHOT).read_bytes()
        with self.assertRaisesRegex(RddError, "amendment"):
            f.question("Q-AFTER-FREEZE")
        self.controller.start("amend", "amended-fixture")
        archived = self.root / ".rdd/baselines/amended-fixture/previous" / SNAPSHOT
        self.assertEqual(archived.read_bytes(), original)
        self.assertEqual(self.controller.state()["refinement"]["decisions"], [])

    def test_cli_refinement_and_freeze_share_existing_mutation_lock(self):
        from tools.rdd.common import operation_lock
        f = self.fixture
        f.begin_s6()
        f.complete_s6()
        f.prepare_reviews()
        f.review("semantic")
        f.review("execution")
        packet = f.input_file({"schema_version": 1, "operation": "question", "session_id": "author-S0",
            "record": {"id": "Q-RACE", "revision": 1, "previous_revision": None,
                       "issue": "A newly discovered requirement conflict needs direction.", "material": True}})
        cli = [sys.executable, str(REPOSITORY / "tools/rdd/cli.py"), "--root", str(self.root)]
        with operation_lock(self.root):
            for command in (("spec", "refine", str(packet)), ("spec", "freeze")):
                result = subprocess.run(cli + list(command), capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("lock", result.stdout.lower())
        answer = subprocess.Popen(cli + ["spec", "refine", str(packet)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        freeze = subprocess.Popen(cli + ["spec", "freeze"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        answer_output = answer.communicate(timeout=30)
        freeze_output = freeze.communicate(timeout=30)
        self.assertEqual(sum(process.returncode == 0 for process in (answer, freeze)), 1,
                         repr((answer.returncode, answer_output, freeze.returncode, freeze_output)))
        state = self.controller.state(allow_blocked=True)
        if freeze.returncode == 0:
            self.assertTrue((self.root / ".rdd/spec.lock.json").is_file())
            self.assertEqual(state["refinement"]["questions"], [])
        else:
            self.assertFalse((self.root / ".rdd/spec.lock.json").exists())
            self.assertEqual([q["record"]["id"] for q in state["refinement"]["questions"]], ["Q-RACE"])

    def test_cli_question_choice_capture_returns_json_and_persists_once(self):
        f = self.fixture
        cli = [sys.executable, str(REPOSITORY / "tools/rdd/cli.py"), "--root", str(self.root), "spec", "refine"]
        question = {"id": "Q-CLI", "revision": 1, "previous_revision": None,
            "issue": "Which ordered capacity policy should be used?", "material": True,
            "options": [{"id": "bounded", "text": STATEMENT}], "recommended_option": "bounded"}
        decision = {"id": "D-CLI", "revision": 1, "previous_revision": None, "statement": STATEMENT,
            "provenance": {"kind": "choice", "question": "Q-CLI", "revision": 1, "option": "bounded",
                           "turn": "user:2", "text": "Use your recommendation.", "qualifications": ""}}
        for operation, record in (("question", question), ("decision", decision)):
            packet = f.input_file({"schema_version": 1, "operation": operation, "session_id": "coordinator", "record": record})
            result = subprocess.run(cli + [str(packet)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), {"operation": operation, "id": record["id"], "revision": 1, "status": "recorded"})
        state = self.controller.state()
        self.assertEqual(len(state["refinement"]["questions"]), 1)
        self.assertEqual(len(state["refinement"]["decisions"]), 1)
        self.assertEqual(sum(e.get("action") == "refinement_recorded" for e in state["events"]), 2)


if __name__ == "__main__":
    unittest.main()
