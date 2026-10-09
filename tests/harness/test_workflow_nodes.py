"""Durable authoring nodes and independent live observations exercise actual state."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_engine as fixture
from tools.rdd.common import RddError, digest, head, inventory, read_json, source_digest, write_json
from tools.rdd.nodes import NODES


class WorkflowNodeTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.EngineTests(methodName="test_phase_cannot_begin_before_preparation")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.c, self.root = self.f.c, self.f.root
        self.f.live_review()

    def claim(self, node="S0", writes=None, **kwargs):
        return self.c.workflow_claim(node, "fixture-author", NODES[node]["responsible_roles"][0], writes or ["docs/specs/fixture.md"], **kwargs)

    def record_file(self, node, claim):
        path = self.root / ".rdd/runtime/node-record.json"
        write_json(path, dict(schema_version=2, node=node, session_id=claim["session_id"], attempt=claim["attempt"],
            input_digest=claim["input_digest"], outputs=claim["writes"], evidence_ids=[]))
        return path

    def record(self, node, claim):
        return self.c.workflow_record(self.record_file(node, claim))

    def finding(self, finding_id, nodes, severity="medium", path="docs/specs/fixture.md"):
        return dict(id=finding_id, severity=severity, requirements=["FR-001"], tasks=[], path=path,
            message="The draft lacks independently verifiable ownership.",
            evidence="Independent controller fixture observation.", nodes=nodes)

    def snapshot(self):
        return dict(state=self.c.state(), head=head(self.root), sources=inventory(self.root),
            source_digest=source_digest(self.root), evidence={p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in (self.root / ".rdd/evidence").rglob("*") if p.is_file()})

    def assert_record_blocked(self, node, claim, finding_id):
        path = self.record_file(node, claim)
        before = self.snapshot()
        with self.assertRaisesRegex(RddError, finding_id + " remains unresolved") as caught:
            self.c.workflow_record(path)
        self.assertEqual(caught.exception.kind, "review")
        self.assertEqual(self.snapshot(), before)
        row = self.c.state()["workflow_nodes"][node]
        self.assertEqual(row["status"], "claimed")
        self.assertEqual(row["attempts"][-1]["status"], "claimed")
        self.assertEqual(row["claim"], claim)

    def resolve(self, *finding_ids):
        return self.f.live_review(resolutions=[dict(finding_id=finding_id,
            evidence="Read the corrected artifact and independently verified its ownership against FR-001.")
            for finding_id in finding_ids])

    def assert_record_needs_completed_observation(self, node, downstream, path):
        state = self.c.state()
        self.assertNotIn(node, state["live_reviews"][-1]["node_outputs"])
        with self.assertRaisesRegex(RddError, "omits completed authoring node outputs"):
            self.c.live_review_guard(final=True, cursor=len(state["live_reviews"]))
        with self.assertRaisesRegex(RddError, "observe completed dependency " + node):
            self.claim(downstream, writes=[path])
        self.f.live_review()
        state = self.c.state()
        self.assertEqual(state["live_reviews"][-1]["node_outputs"][node],
                         state["workflow_nodes"][node]["output_digest"])
        self.c.live_review_guard(final=True, cursor=len(state["live_reviews"]))
        self.assertEqual(self.claim(downstream, writes=[path])["node"], downstream)

    def test_late_specification_finding_blocks_record_without_mutation(self):
        self.f.node_complete("S0")
        path = "docs/specs/domain.md"
        claim = self.claim("S1", writes=[path])["claim"]
        self.f.write(path, "# Domain ownership\n\nFR-001 belongs to the fixture domain.\n")
        self.f.live_review(findings=[self.finding("LATE-SPEC", ["S1"], path=path)])
        self.assert_record_blocked("S1", claim, "LATE-SPEC")
        self.resolve("LATE-SPEC")
        self.assertEqual(self.record("S1", claim)["status"], "complete")
        row = self.c.state()["workflow_nodes"]["S1"]
        self.assertEqual(row["claim"], claim)
        self.assertEqual(row["outputs"], inventory(self.root, claim["writes"]))
        self.assertEqual(len(row["attempts"]), 1)
        self.assert_record_needs_completed_observation("S1", "S3", "docs/specs/scenarios.md")

    def test_late_preparation_finding_blocks_record_without_mutation(self):
        self.f.stage_ready("specification")
        self.c.spec_freeze()
        self.f.commit("Freeze specification for the preparation finding fixture")
        self.f.live_review()
        self.f.node_complete("P0")
        path = ".rdd/plan/notes/reuse.md"
        claim = self.claim("P1", writes=[path])["claim"]
        self.f.fwrite_node(path, "P1")
        self.f.live_review(findings=[self.finding("LATE-PREP", ["P1"], severity="blocking", path=path)])
        self.assert_record_blocked("P1", claim, "LATE-PREP")
        self.resolve("LATE-PREP")
        self.assertEqual(self.record("P1", claim)["status"], "complete")
        row = self.c.state()["workflow_nodes"]["P1"]
        self.assertEqual(row["claim"], claim)
        self.assertEqual(row["outputs"], inventory(self.root, claim["writes"]))
        self.assertEqual(len(row["attempts"]), 1)
        self.assert_record_needs_completed_observation("P1", "P2", ".rdd/plan/notes/research.md")

    def test_late_scoped_and_global_findings_block_correction_record(self):
        self.f.node_complete("S0")
        path = "docs/specs/domain.md"
        for scope, nodes in (("SCOPED", ["S1"]), ("GLOBAL", [])):
            with self.subTest(scope=scope):
                original, late = "ORIGINAL-" + scope, "LATE-" + scope
                self.f.live_review(findings=[self.finding(original, ["S1"], path=path)])
                claim = self.claim("S1", writes=[path], finding=original)["claim"]
                self.f.write(path, "# Corrected " + scope + " ownership\n\nFR-001 belongs to the fixture domain.\n")
                self.f.live_review(findings=[self.finding(late, nodes, severity="high", path=path)])
                self.resolve(original)
                self.assert_record_blocked("S1", claim, late)
                self.resolve(late)
                self.assertEqual(self.record("S1", claim)["status"], "complete")
                self.assertEqual(self.c.state()["workflow_nodes"]["S1"]["claim"], claim)

    def test_other_node_and_advisory_findings_do_not_block_record(self):
        self.f.node_complete("S0")
        claim = self.claim("S1")["claim"]
        findings = [self.finding("OTHER-NODE", ["S2"], severity="blocking"),
                    self.finding("LOW", ["S1"], severity="low"),
                    self.finding("INFO", [], severity="note")]
        self.f.live_review(findings=findings)
        self.assertEqual(self.record("S1", claim)["status"], "complete")
        self.assertEqual(self.c.state()["workflow_nodes"]["S1"]["claim"], claim)
        # Final acceptance still requires resolution of advisory and other-node findings.
        with self.assertRaisesRegex(RddError, "findings remain unresolved"):
            self.c.live_review_guard(final=True, cursor=len(self.c.state()["live_reviews"]))

    def test_cli_record_rejects_review_without_persisting_blocker_or_completion(self):
        path = "docs/specs/intake.md"
        claim = self.claim("S0", writes=[path])["claim"]
        self.f.write(path, "# Intake\n\nFR-001 requires an independently verified owner.\n")
        self.f.live_review(findings=[self.finding("LATE-CLI", ["S0"], severity="high", path=path)])
        record = self.record_file("S0", claim)
        before = self.snapshot()
        entry = Path(__file__).resolve().parents[2] / "tools/rdd/cli.py"
        argv = [sys.executable, str(entry), "--root", str(self.root), "workflow", "record", str(record)]
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["kind"], "review")
        self.assertEqual(response["status"], "blocked")
        self.assertIn("LATE-CLI remains unresolved", response["error"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.c.state()["status"], "specification")
        self.assertEqual(self.c.state()["blockers"], [])
        self.assertEqual(self.c.state()["workflow_nodes"]["S0"]["status"], "claimed")
        self.resolve("LATE-CLI")
        retried = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertEqual(json.loads(retried.stdout)["status"], "complete")
        self.assertEqual(self.c.state()["workflow_nodes"]["S0"]["claim"], claim)

    def test_claimed_correction_checkpoint_preserves_record_block(self):
        self.f.node_complete("S0")
        self.f.commit("Commit the correction checkpoint baseline")
        path = "docs/specs/domain.md"
        self.f.live_review(findings=[self.finding("RECOVERY", ["S1"], path=path)])
        claim = self.claim("S1", writes=[path], finding="RECOVERY")["claim"]
        self.f.write(path, "# Corrected ownership\n\nFR-001 belongs to the fixture domain.\n")
        self.f.commit("Preserve the unresolved correction draft")
        self.f.live_review()
        self.assert_record_blocked("S1", claim, "RECOVERY")
        before = self.snapshot()
        checkpoint = self.root / ".rdd/runtime/node-correction-checkpoint.json"
        self.c.export_run(checkpoint)
        saved = read_json(checkpoint)
        self.assertEqual(saved["state"], before["state"])
        self.assertEqual(saved["source_commit"], before["head"])
        self.assertEqual(saved["source_digest"], before["source_digest"])
        self.c.workflow_release("S1", "Preserve the correction before restoring the checkpoint")
        self.assertEqual(self.c.state()["workflow_nodes"]["S1"]["status"], "pending")
        self.c.resume(checkpoint)
        restored = self.snapshot()
        for field in ("workflow_nodes", "live_findings", "live_reviews", "checks", "blockers"):
            self.assertEqual(restored["state"][field], before["state"][field])
        self.assertEqual(restored["state"]["events"][:-1], before["state"]["events"])
        self.assertEqual(restored["state"]["events"][-1]["action"], "resumed")
        for field in ("head", "sources", "source_digest", "evidence"):
            self.assertEqual(restored[field], before[field])
        self.assert_record_blocked("S1", claim, "RECOVERY")
        self.resolve("RECOVERY")
        self.assertEqual(self.record("S1", claim)["status"], "complete")
        self.assertEqual(self.c.state()["workflow_nodes"]["S1"]["claim"], claim)

    def test_dependency_order_and_derived_nodes_cannot_be_claimed(self):
        with self.assertRaisesRegex(RddError, "dependencies"):
            self.claim("S3")
        with self.assertRaisesRegex(RddError, "derives"):
            self.claim("S8")
        self.assertEqual(self.c.workflow_next()["ready"], ["S0"])
        self.f.node_complete("S0")
        self.assertEqual(self.c.workflow_next()["ready"], ["S1", "S2"])

    def test_specialist_node_rejects_generic_coordinator(self):
        self.f.node_complete("S0")
        with self.assertRaisesRegex(RddError, "responsible roles"):
            self.c.workflow_claim("S1", "generic-author", "rdd_coordinator", ["docs/specs/domain.md"])

    def test_readonly_and_implementation_roles_cannot_author_workflow_nodes(self):
        for role in ("rdd_researcher", "rdd_reviewer", "rdd_complex_implementor", "rdd_light_implementor"):
            with self.subTest(role=role), self.assertRaisesRegex(RddError, "supported role"):
                self.c.workflow_claim("S0", "wrong-role-session", role, ["docs/specs/domain.md"])
        self.assertEqual(self.c.workflow_next()["ready"], ["S0"])

    def test_specialist_claim_pins_requested_runtime_and_rejects_forged_checkpoint(self):
        self.f.node_complete("S0")
        claim = self.claim("S1")["claim"]
        self.assertEqual(claim["role"], "rdd_domain_analyst")
        self.assertEqual(claim["requested_runtime"], self.c.profile_settings("rdd_domain_analyst"))
        self.record("S1", claim)
        state = self.c.state()
        self.c.validate_workflow_checkpoint(state)
        state["workflow_nodes"]["S1"]["claim"]["requested_runtime"]["model"] = "unobserved-model"
        state["workflow_nodes"]["S1"]["attempts"][-1]["claim"] = copy.deepcopy(state["workflow_nodes"]["S1"]["claim"])
        with self.assertRaisesRegex(RddError, "requested runtime"):
            self.c.validate_workflow_checkpoint(state)

    def test_cli_handoff_is_compact_and_preserves_canonical_claim(self):
        entry = Path(__file__).resolve().parents[2] / "tools/rdd/cli.py"

        def cli(*args):
            result = subprocess.run([sys.executable, str(entry), "--root", str(self.root), *args],
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)

        public = cli("workflow", "claim", "S0", "--session-id", "fixture-author",
                     "--role", "rdd_coordinator", "--write", "docs/specs/fixture.md")["claim"]
        canonical = self.c.state()["workflow_nodes"]["S0"]["claim"]
        self.assertNotIn("sources", public)
        self.assertGreater(public["source_file_count"], 0)
        self.assertEqual(public["source_file_count"], len(canonical["sources"]))
        for field in ("session_id", "attempt", "input_digest", "source_digest", "source_commit", "writes"):
            self.assertEqual(public[field], canonical[field])
        for output in (cli("workflow", "nodes"), cli("status")["workflow_nodes"]):
            node = next(row for row in output["nodes"] if row["id"] == "S0")
            self.assertNotIn("sources", node["claim"])
            self.assertNotIn("sources", node["attempts"][0]["claim"])
        self.assertEqual(self.c.state()["workflow_nodes"]["S0"]["claim"], canonical)
        # The exact compact receipt still supplies every field needed for record.
        self.record("S0", public)
        self.assertEqual(self.c.state()["workflow_nodes"]["S0"]["attempts"][0]["claim"], canonical)

    def test_dependent_handoff_needs_observation_and_siblings_can_share_it(self):
        claim = self.claim()["claim"]
        self.record("S0", claim)
        with self.assertRaisesRegex(RddError, "observe completed dependency"):
            self.claim("S1")
        self.f.live_review()
        self.claim("S1")
        self.claim("S2", writes=["docs/specs/parallel.md"])

    def test_claim_cannot_own_controller_state_or_overlapping_work(self):
        for path in (".rdd/run.json", ".rdd/prepared.json", ".rdd/requirements.index.json"):
            with self.subTest(path=path), self.assertRaisesRegex(RddError, "artifact paths"):
                self.claim(writes=[path])
        self.f.node_complete("S0")
        self.claim("S1")
        with self.assertRaisesRegex(RddError, "disjoint"):
            self.claim("S2")

    def test_undeclared_edits_and_changed_dependency_reject_output(self):
        claim = self.claim()["claim"]
        self.f.write("unexpected.txt", "Undeclared source mutation\n")
        with self.assertRaisesRegex(RddError, "outside its bounded claim"):
            self.record("S0", claim)
        (self.root / "unexpected.txt").unlink()
        self.record("S0", claim)
        self.f.write("docs/specs/fixture.md", "Changed baseline intake evidence\n")
        self.assertEqual(self.c._node_records(self.c.state())["S0"]["status"], "stale")
        with self.assertRaisesRegex(RddError, "dependencies"):
            self.claim("S1")

    def test_attempt_budget_preserves_history(self):
        for attempt in range(self.c.config["limits"]["max_attempts"]):
            self.assertEqual(self.claim()["claim"]["attempt"], attempt + 1)
            self.c.workflow_release("S0", "Preserve draft; qualification requires another experiment")
        with self.assertRaisesRegex(RddError, "budget"):
            self.claim()
        self.assertEqual(len(self.c.state()["workflow_nodes"]["S0"]["attempts"]), 3)

    def test_review_stage_and_author_collision_rejected(self):
        with self.assertRaisesRegex(RddError, "stage/phase"):
            self.f.live_review(stage="preparation")
        with self.assertRaisesRegex(RddError, "reviewer session"):
            self.c.author_record("specification", "fixture-live-reviewer")
        with self.assertRaisesRegex(RddError, "reviewer session"):
            self.c.workflow_claim("S0", "fixture-live-reviewer", "rdd_coordinator", ["docs/specs/fixture.md"])

    def test_two_findings_permit_scoped_correction_but_not_progression(self):
        self.f.node_complete("S0")
        findings = [self.finding(f"F{i}", ["S1"]) for i in (1, 2)]
        self.f.live_review(findings=findings)
        with self.assertRaisesRegex(RddError, "unresolved"):
            self.claim("S1")
        claim = self.claim("S1", finding="F1")["claim"]
        self.assertEqual(claim["finding"], "F1")
        self.assert_record_blocked("S1", claim, "F1")
        self.resolve("F1")
        self.assert_record_blocked("S1", claim, "F2")
        with self.assertRaisesRegex(RddError, "unresolved"):
            self.c.live_review_guard(final=True, cursor=len(self.c.state()["live_reviews"]))
        self.resolve("F2")
        self.assertEqual(self.record("S1", claim)["status"], "complete")
        self.assertEqual(self.c.state()["workflow_nodes"]["S1"]["claim"], claim)
        self.assertEqual(len(self.c.state()["workflow_nodes"]["S1"]["attempts"]), 1)
        self.assert_record_needs_completed_observation("S1", "S3", "docs/specs/scenarios.md")

    def test_checkpoint_rejects_node_history_and_review_cursor_tampering(self):
        self.f.node_complete("S0")
        state = self.c.state()
        self.c.validate_workflow_checkpoint(state)
        changed = copy.deepcopy(state)
        changed["workflow_nodes"]["S0"]["output_digest"] = "0" * 64
        with self.assertRaisesRegex(RddError, "output proof"):
            self.c.validate_workflow_checkpoint(changed)
        changed = copy.deepcopy(state)
        changed["live_reviews"][0]["review"]["summary"] += " changed"
        with self.assertRaisesRegex(RddError, "identity"):
            self.c.validate_review_stream(changed)
        changed = copy.deepcopy(state)
        changed["live_reviews"][0]["node_outputs"] = {"S0": "0" * 64}
        with self.assertRaisesRegex(RddError, "identity"):
            self.c.validate_review_stream(changed)

    def test_checkpoint_rejects_empty_completed_node_fabrication(self):
        self.f.node_complete("S0")
        state = self.c.state()
        row = state["workflow_nodes"]["S0"]
        row["outputs"] = {}
        row["output_digest"] = digest({})
        row["claim"]["writes"] = []
        row["attempts"][-1]["outputs"] = {}
        with self.assertRaises(RddError):
            self.c.validate_workflow_checkpoint(state)

    def test_checkpoint_cannot_rewind_observation_cursor_before_dependency(self):
        self.f.node_complete("S0")
        self.f.node_complete("S1")
        state = self.c.state()
        self.c.validate_workflow_checkpoint(state)
        row = state["workflow_nodes"]["S1"]
        row["claim"]["review_cursor"] = 1
        row["attempts"][-1]["claim"]["review_cursor"] = 1
        with self.assertRaisesRegex(RddError, "preceding live observation"):
            self.c.validate_workflow_checkpoint(state)


if __name__ == "__main__":
    unittest.main()
