"""Stage acceptance must be earned at the exact candidate, never asserted by prose."""
import copy
import unittest
from unittest.mock import patch

import test_engine as engine_fixture
from tools.rdd.common import RddError, digest, read_json, write_json


class StageGateTests(unittest.TestCase):
    def setUp(self):
        self.f = engine_fixture.EngineTests(methodName="test_phase_cannot_begin_before_preparation")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.c, self.root = self.f.c, self.f.root

    def test_freeze_requires_real_readiness(self):
        self.f.commit("Commit candidate without qualification")
        with self.assertRaisesRegex(RddError, "readiness|Workflow node"):
            self.c.spec_freeze()
        self.assertFalse((self.root / ".rdd/spec.lock.json").exists())

    def test_two_review_perspectives_required(self):
        self.f.commit("Commit candidate")
        self.c.author_record("specification", "fixture-author")
        self.f.authoring_nodes("specification")
        ready = self.c.readiness("specification")
        self.f.node_complete("S7", ready["evidence"])
        with self.assertRaisesRegex(RddError, "Both semantic and execution"):
            self.c.spec_freeze()

    def test_review_stale_after_same_bytes_new_commit(self):
        self.f.stage_ready("specification")
        self.f.g("commit", "--allow-empty", "-m", "New identity")
        with self.assertRaisesRegex(RddError, "current-candidate"):
            self.c.spec_freeze()

    def test_every_unresolved_finding_blocks_freeze(self):
        self.f.stage_ready("specification")
        review = copy.deepcopy(self.c.state()["stage_reviews"]["specification"]["semantic"])
        review["findings"] = [dict(id="F1", severity="low", requirements=["FR-001"], tasks=[],
            path="docs/specs/fixture.md", message="A real unresolved minor finding.", evidence="Explicit fixture finding.")]
        path = self.root / ".rdd/runtime/changed-review.json"
        write_json(path, review)
        self.c.review_record(path)
        self.assertIn("F1", self.c.state()["live_findings"])
        with self.assertRaisesRegex(RddError, "unresolved"):
            self.c.spec_freeze()
        review["findings"] = []
        review["review_cursor"] = len(self.c.state()["live_reviews"])
        write_json(path, review)
        with self.assertRaisesRegex(RddError, "unresolved"):
            self.c.review_record(path)

    def test_author_change_after_review_invalidates_approval(self):
        self.f.stage_ready("specification")
        with self.assertRaisesRegex(RddError, "reviewer session"):
            self.c.author_record("specification", "fixture-semantic")

    def test_same_reviewer_cannot_supply_both_perspectives(self):
        self.f.stage_ready("specification")
        review = copy.deepcopy(self.c.state()["stage_reviews"]["specification"]["execution"])
        review["session_id"] = "fixture-semantic"
        path = self.root / ".rdd/runtime/changed-review.json"
        write_json(path, review)
        self.c.review_record(path)
        with self.assertRaisesRegex(RddError, "distinct reviewer"):
            self.c.spec_freeze()

    def test_materialization_is_not_implementation_readiness(self):
        self.f.stage_ready("specification")
        frozen = self.c.spec_freeze()
        self.f.commit("Freeze fixture specification")
        self.c.plan_init()
        self.f.plan["spec_digest"] = frozen["spec_digest"]
        write_json(self.root / ".rdd/plan/plan.json", self.f.plan)
        self.f.stage_ready("plan")
        self.c.plan_freeze()
        self.assertEqual(self.c.prepare()["status"], "preparing")
        self.f.commit("Materialize candidate")
        with self.assertRaisesRegex(RddError, "preparation"):
            self.c.phase_begin("P01")
        self.f.stage_ready("preparation")
        with self.assertRaisesRegex(RddError, "actual exact-source CI"):
            self.c.gate_preparation()
        self.f.stage_ready("preparation", ci=True)
        with patch.object(self.f.hub, "preparation_status", return_value={"ready": False, "blockers": ["Actual CI run failed"]}):
            with self.assertRaisesRegex(RddError, "CI run is not ready"):
                self.c.gate_preparation()
        self.assertEqual(self.c.state()["status"], "preparing")

    def test_legacy_run_stays_read_only(self):
        state = self.c.state()
        state.pop("workflow_version")
        self.c.store.put(state)  # Deliberate legacy fixture, not workflow execution.
        before = self.c.state(allow_blocked=True)
        with self.assertRaisesRegex(RddError, "Legacy"):
            self.c.spec_init()
        self.assertEqual(self.c.state(allow_blocked=True), before)
        self.assertEqual(self.c.status()["status"], "specification")
        self.c.export_run(self.root / ".rdd/evidence/legacy-export.json")

    def test_checkpoint_cannot_rebind_reviewed_candidate_to_another_spec(self):
        self.f.stage_ready("specification")
        self.c.spec_freeze()
        path = self.root / ".rdd/evidence/checkpoint.json"
        self.c.export_run(path)
        checkpoint = read_json(path)
        state = checkpoint["state"]
        acceptance = state["spec_acceptance"]
        candidate = acceptance["candidate"]
        candidate["spec_digest"] = "0" * 64
        candidate["digest"] = digest({k: v for k, v in candidate.items() if k != "digest"})
        ready = state["readiness"]["specification"]
        ready["candidate"] = candidate
        ready["digest"] = digest({k: v for k, v in ready.items() if k != "digest"})
        acceptance["readiness_digest"] = ready["digest"]
        for perspective, review in state["stage_reviews"]["specification"].items():
            review["candidate"] = candidate
            acceptance["review_digests"][perspective] = digest(review)
        with self.assertRaisesRegex(RddError, "frozen baseline"):
            self.c.validate_checkpoint_state(state, checkpoint)

    def test_checkpoint_cannot_erase_review_coverage_and_rehash(self):
        self.f.stage_ready("specification")
        self.c.spec_freeze()
        path = self.root / ".rdd/evidence/checkpoint.json"
        self.c.export_run(path)
        checkpoint = read_json(path)
        state = checkpoint["state"]
        self.c.validate_checkpoint_state(state, checkpoint)
        for perspective, review in state["stage_reviews"]["specification"].items():
            review["coverage"] = {field: [] for field in review["coverage"]}
            state["spec_acceptance"]["review_digests"][perspective] = digest(review)
        with self.assertRaisesRegex(RddError, "coverage is incomplete"):
            self.c.validate_checkpoint_state(state, checkpoint)

    def test_preparation_checkpoint_binds_archived_github_identities(self):
        self.f.prepared()
        path = self.root / ".rdd/evidence/checkpoint.json"
        self.c.export_run(path)
        checkpoint = read_json(path)
        self.c.validate_checkpoint_state(checkpoint["state"], checkpoint)
        for field, value in (("head_sha", "0" * 40), ("harness_sha", "1" * 40), ("attempt", None), ("url", "https://github.com/other/repo/actions/runs/2")):
            changed = copy.deepcopy(checkpoint)
            for row in changed["state"]["preparation_gate"]["ci_runs"].values():
                row["github"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(RddError, "GitHub observation"):
                self.c.validate_checkpoint_state(changed["state"], changed)

    def test_specification_defect_in_preparation_is_critical_and_preserved(self):
        self.f.stage_ready("specification")
        self.c.spec_freeze()
        result = self.c.block("specification", "A missing failure outcome escaped specification review.",
            affected=dict(requirements=["FR-001"], elements=["E-OP"], tasks=[]), evidence=["docs/specs/fixture.md"])
        escape = result["blocker"]["escape"]
        self.assertEqual((escape["severity"], escape["origin_stage"], escape["detected_stage"]),
                         ("critical", "specification", "preparation"))
        self.assertTrue((self.root / escape["evidence"][-1]).is_file())
        self.assertEqual(self.c.state(allow_blocked=True)["status"], "blocked")
        self.assertIn("preventive control", result["next"])

    def test_invalid_escape_ids_write_no_diagnostic_artifact(self):
        self.f.stage_ready("specification")
        self.c.spec_freeze()
        with self.assertRaisesRegex(RddError, "unknown references"):
            self.c.block("specification", "Defect with an invalid affected ID.",
                affected=dict(requirements=["FR-UNKNOWN"], elements=[], tasks=[]))
        self.assertFalse((self.root / ".rdd/evidence/escapes").exists())

    def test_frozen_stage_cannot_be_reopened_by_corrective_node_claim(self):
        self.f.stage_ready("specification")
        self.c.spec_freeze()
        self.f.live_review(findings=[dict(id="ESCAPE", severity="blocking", requirements=["FR-001"], tasks=[],
            path="docs/specs/fixture.md", message="A frozen specification omission.", evidence="Observed after freeze.", nodes=["S6"])])
        with self.assertRaisesRegex(RddError, "already frozen"):
            self.c.workflow_claim("S6", "fixture-author", "rdd_coordinator", [".rdd/spec.json"], finding="ESCAPE")


if __name__ == "__main__":
    unittest.main()
