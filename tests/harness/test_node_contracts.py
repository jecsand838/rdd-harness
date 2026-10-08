"""Fixed node authority, bounded parallelism and checkpoint handoff integrity."""
import copy
import unittest

import test_engine as fixture
from tools.rdd.common import RddError, digest, write_json


class NodeContractTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.EngineTests(methodName="test_phase_cannot_begin_before_preparation")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.c = self.f.c
        self.f.live_review()

    def claim(self, node, path):
        return self.c.workflow_claim(node, "fixture-author", "rdd_coordinator", [path])

    def record(self, node, claim):
        path = self.f.root / ".rdd/runtime/node-retirement.json"
        write_json(path, dict(schema_version=2, node=node, attempt=claim["attempt"],
            session_id=claim["session_id"], input_digest=claim["input_digest"],
            outputs=claim["writes"], evidence_ids=[]))
        return self.c.workflow_record(path)

    def test_specification_can_retire_claimed_seed_contract_with_durable_proof(self):
        seed = "contracts/rdd/v1/harness.proto"
        self.f.write(seed, 'syntax = "proto3"; package rdd.v1; message Seed {}\n')
        self.f.write(".gitattributes", seed + " -text\n")
        (self.f.root / seed).write_bytes(b'syntax = "proto3";\r\npackage rdd.v1;\r\nmessage Seed {}\r\n')
        self.f.commit("Preserve the qualification seed before actual specification")
        for node in ("S0", "S1", "S2", "S3", "S4", "S5"):
            self.f.node_complete(node)
        claim = self.c.workflow_claim("S6", "fixture-author", "rdd_coordinator",
                                      [seed, ".rdd/spec.json"])["claim"]
        (self.f.root / seed).unlink()
        self.f.commit("Retire the seed in favor of the requirement-derived contract")
        self.assertEqual(self.record("S6", claim)["status"], "complete")
        state = self.c.state()
        self.assertEqual(state["workflow_nodes"]["S6"]["outputs"][seed], "MISSING")
        self.c.validate_workflow_checkpoint(state)
        checkpoint = self.f.root / ".rdd/runtime/retired-checkpoint.json"
        self.c.export_run(checkpoint)
        self.c.resume(checkpoint)
        self.assertEqual(self.c.state()["workflow_nodes"]["S6"]["outputs"][seed], "MISSING")
        self.f.write(seed, 'syntax = "proto3"; package rdd.v1; message Seed {}\n')
        self.assertEqual(self.c._node_records(self.c.state())["S6"]["status"], "stale")

    def test_missing_new_output_and_all_deleted_outputs_cannot_complete(self):
        self.f.write("docs/specs/retired.md", "A previously present authoring artifact.\n")
        self.f.commit("Record a prior authoring artifact")
        claim = self.c.workflow_claim("S0", "fixture-author", "rdd_coordinator",
            ["docs/specs/fixture.md", "docs/specs/never-created.md"])["claim"]
        with self.assertRaisesRegex(RddError, "missing output"):
            self.record("S0", claim)
        self.c.workflow_release("S0", "Preserve the unsuccessful missing-output attempt")
        claim = self.claim("S0", "docs/specs/retired.md")["claim"]
        (self.f.root / "docs/specs/retired.md").unlink()
        with self.assertRaisesRegex(RddError, "nonempty artifact"):
            self.record("S0", claim)

    def test_checkpoint_cannot_replace_an_uncreated_output_with_a_tombstone(self):
        self.f.node_complete("S0")
        state = copy.deepcopy(self.c.state())
        row = state["workflow_nodes"]["S0"]
        absent = "docs/specs/never-created.md"
        for claim in (row["claim"], row["attempts"][-1]["claim"]):
            if absent not in claim["writes"]:
                claim["writes"].append(absent)
        row["outputs"][absent] = "MISSING"
        row["attempts"][-1]["outputs"][absent] = "MISSING"
        row["output_digest"] = digest(row["outputs"])
        with self.assertRaisesRegex(RddError, "output proof"):
            self.c.validate_workflow_checkpoint(state)
        # Recomputing all self-reported source hashes cannot manufacture the
        # prior committed file that a retirement proof must corroborate.
        for claim in (row["claim"], row["attempts"][-1]["claim"]):
            claim["sources"][absent] = "a" * 64
            claim["source_digest"] = digest(claim["sources"])
        with self.assertRaisesRegex(RddError, "output proof"):
            self.c.validate_workflow_checkpoint(state)

    def test_tombstone_requires_nonempty_inventoried_previous_file(self):
        empty, ignored = "docs/specs/empty.md", "docs/specs/ignored.md"
        self.f.write(".git/info/exclude", ignored + "\n")
        self.f.write(empty, "")
        self.f.write(ignored, "An ignored source is not an inventoried handoff.\n")
        self.f.commit("Retain explicit baseline source inventory")
        for path in (empty, ignored):
            with self.subTest(path=path):
                claim = self.c.workflow_claim("S0", "fixture-author", "rdd_coordinator",
                    ["docs/specs/fixture.md", path])["claim"]
                (self.f.root / path).unlink()
                with self.assertRaisesRegex(RddError, "missing output"):
                    self.record("S0", claim)
                self.c.workflow_release("S0", "Preserve the invalid retirement attempt")

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
