"""Fixed node authority, bounded parallelism and checkpoint handoff integrity."""
import copy
import unittest

import test_engine as fixture
from tools.rdd.common import RddError, digest


class NodeContractTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.EngineTests(methodName="test_phase_cannot_begin_before_preparation")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.c = self.f.c
        self.f.live_review()

    def claim(self, node, path):
        return self.c.workflow_claim(node, "fixture-author", "rdd_coordinator", [path])

    def test_role_and_output_family_are_node_specific(self):
        with self.assertRaisesRegex(RddError, "responsible roles"):
            self.c.workflow_claim("S0", "fixture-author", "rdd_researcher", ["docs/specs/intake.md"])
        self.f.node_complete("S0")
        with self.assertRaisesRegex(RddError, "artifact paths"):
            self.claim("S1", "contracts/unreviewed.proto")
        with self.assertRaisesRegex(RddError, "artifact paths"):
            self.claim("S2", "modules/application.rs")

    def test_third_ready_author_cannot_consume_reviewer_slot(self):
        for node in ("S0", "S1", "S2"):
            self.f.node_complete(node)
        self.claim("S3", "docs/specs/scenarios.md")
        self.claim("S4", "docs/specs/benchmarks.md")
        with self.assertRaisesRegex(RddError, "two authoring claims"):
            self.claim("S5", "docs/decisions/qualification.md")
        self.c.workflow_release("S4", "Preserve the benchmark draft while qualifying dependencies")
        self.claim("S5", "docs/decisions/qualification.md")

    def test_recomputed_input_hash_cannot_invent_a_dependency_handoff(self):
        for node in ("S0", "S1"):
            self.f.node_complete(node)
        state = copy.deepcopy(self.c.state())
        row = state["workflow_nodes"]["S1"]
        for claim in (row["claim"], row["attempts"][-1]["claim"]):
            claim["inputs"]["dependencies"]["S0"] = "0" * 64
            claim["input_digest"] = digest(claim["inputs"])
        row["input_digest"] = row["claim"]["input_digest"]
        with self.assertRaisesRegex(RddError, "prerequisite handoff"):
            self.c.validate_workflow_checkpoint(state)

    def test_checkpoint_rejects_undeclared_role_and_empty_source_inventory(self):
        self.f.node_complete("S0")
        for field, value in (("role", "unregistered"), ("sources", {}), ("expires", 0)):
            state = copy.deepcopy(self.c.state())
            row = state["workflow_nodes"]["S0"]
            for claim in (row["claim"], row["attempts"][-1]["claim"]):
                claim[field] = value
                if field == "sources":
                    claim["source_digest"] = digest(value)
            with self.subTest(field=field), self.assertRaisesRegex(RddError, "claim history"):
                self.c.validate_workflow_checkpoint(state)


if __name__ == "__main__":
    unittest.main()
