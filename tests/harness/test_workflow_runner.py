"""Public workflow execution cannot turn model/process success into acceptance."""
import copy
import unittest

import test_engine as fixture


class WorkflowResultTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.EngineTests(methodName="runTest")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.c = self.f.c

    def test_unaccepted_stage_is_readonly_and_incomplete(self):
        before = copy.deepcopy(self.c.state())
        result = self.c.workflow_result("specification")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(self.c.state(), before)

    def test_print_with_mode_cannot_start_or_replace_run(self):
        before = copy.deepcopy(self.c.state())
        packet = self.c.workflow("specification", "regenerate", print_only=True)
        self.assertEqual(packet["stage"], "specification")
        self.assertEqual(self.c.state(), before)

    def test_accepted_spec_survives_freeze_commit_and_detects_evidence_drift(self):
        self.f.stage_ready("specification")
        self.c.spec_freeze()
        self.f.commit("Commit accepted frozen specification")
        before = copy.deepcopy(self.c.state())
        result = self.c.workflow_result("specification")
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(self.c.state(), before)
        receipt = next(iter(before["checks"].values()))
        (self.f.root / receipt["log_path"]).write_text("corrupt\n", encoding="utf-8")
        self.assertEqual(self.c.workflow_result("specification")["status"], "failed")


class WorkflowEvidenceTests(WorkflowResultTests):


    def accepted_spec(self):
        self.f.stage_ready("specification")
        self.c.spec_freeze()
        self.f.commit("Accepted fixture specification")


    def test_storage_failure_cannot_be_reported_as_failed_acceptance(self):
        import sqlite3
        from unittest.mock import patch
        from tools.rdd.common import RddStorageError
        error = RddStorageError("read", self.c.store.path, sqlite3.DatabaseError("fixture malformed"))
        with patch.object(self.c, "state", side_effect=error):
            with self.assertRaises(RddStorageError) as caught:
                self.c.workflow_result("specification")
        self.assertIs(caught.exception, error)


    def test_storage_failure_in_check_save_cannot_become_missing_evidence(self):
        import sqlite3
        from unittest.mock import patch
        from tools.rdd.common import RddStorageError
        state = self.c.state()
        before = copy.deepcopy(state)
        error = RddStorageError("put", self.c.store.path, sqlite3.DatabaseError("fixture malformed"))
        receipt = dict(id="fixture-receipt", outcome="pass")
        with patch("tools.rdd.engine.execute_check", return_value=receipt) as check, \
                patch.object(self.c, "save", side_effect=error) as save:
            with self.assertRaises(RddStorageError) as caught:
                self.c.ensure_checks(state, ["contract"], candidate_spec_digest="fixture-spec")
        self.assertIs(caught.exception, error)
        check.assert_called_once()
        save.assert_called_once()
        self.assertEqual(self.c.state(), before)

    def test_acceptance_and_checkpoint_preserve_crlf_raw_evidence_bytes(self):
        from unittest.mock import patch
        from tools.rdd.common import atomic_write, read_json
        def crlf_log(path, data):
            atomic_write(path, data.replace(b"\n", b"\r\n") if path.suffix == ".log" else data)
        with patch("tools.rdd.checks.atomic_write", crlf_log):
            self.accepted_spec()
        self.assertEqual(self.c.workflow_result("specification")["status"], "passed")
        path = self.f.root / ".rdd/evidence/crlf-checkpoint.json"
        self.c.export_run(path)
        exported = read_json(path)
        for receipt in self.c.state()["checks"].values():
            raw = (self.f.root / receipt["log_path"]).read_bytes()
            self.assertIn(b"\r\n", raw)
            self.assertEqual(exported["evidence"][receipt["log_path"]].encode("utf-8"), raw)
        self.c.resume(path)
        self.assertEqual(self.c.workflow_result("specification")["status"], "passed")
