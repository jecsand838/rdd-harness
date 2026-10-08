"""Durable authoring nodes and independent live observations exercise actual state."""
import copy
import unittest

import test_engine as fixture
from tools.rdd.common import RddError, digest, read_json, write_json


class WorkflowNodeTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.EngineTests(methodName="test_phase_cannot_begin_before_preparation")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.c, self.root = self.f.c, self.f.root
        self.f.live_review()

    def claim(self, node="S0", writes=None, **kwargs):
        return self.c.workflow_claim(node, "fixture-author", "rdd_coordinator", writes or ["docs/specs/fixture.md"], **kwargs)

    def record(self, node, claim):
        path = self.root / ".rdd/runtime/node-record.json"
        write_json(path, dict(schema_version=2, node=node, session_id=claim["session_id"], attempt=claim["attempt"],
            input_digest=claim["input_digest"], outputs=claim["writes"], evidence_ids=[]))
        return self.c.workflow_record(path)

    def test_dependency_order_and_derived_nodes_cannot_be_claimed(self):
        with self.assertRaisesRegex(RddError, "dependencies"):
            self.claim("S3")
        with self.assertRaisesRegex(RddError, "derives"):
            self.claim("S8")
        self.assertEqual(self.c.workflow_next()["ready"], ["S0"])
        self.f.node_complete("S0")
        self.assertEqual(self.c.workflow_next()["ready"], ["S1", "S2"])

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
        findings = [dict(id=f"F{i}", severity="medium", requirements=["FR-001"], tasks=[], path="docs/specs/fixture.md",
            message="The domain draft lacks independently verifiable ownership.", evidence="Controller fixture observation.", nodes=["S1"]) for i in (1, 2)]
        self.f.live_review(findings=findings)
        with self.assertRaisesRegex(RddError, "unresolved"):
            self.claim("S1")
        claim = self.claim("S1", finding="F1")["claim"]
        self.record("S1", claim)
        with self.assertRaisesRegex(RddError, "unresolved"):
            self.c.live_review_guard(final=True, cursor=len(self.c.state()["live_reviews"]))
        self.f.live_review(resolutions=[dict(finding_id=f"F{i}", evidence="Read the corrected ownership source and verified it against FR-001.") for i in (1, 2)])
        self.c.live_review_guard(final=True, cursor=len(self.c.state()["live_reviews"]))

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
