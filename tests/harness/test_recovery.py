"""Recovery and amendment checks with real local Git and controller state.

Reuses EngineTests' fixture helpers through composition, never its test methods.
Its explicitly labelled Protobuf/GitHub fakes are controller boundaries, not proof
that Rust contracts compile or that a remote PR was created.
"""
from __future__ import annotations

import copy
import shutil
import unittest
from unittest.mock import patch

import test_engine as engine_fixture
from tools.rdd import engine
from tools.rdd.common import RddError, head, inventory, read_json, write_json


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = engine_fixture.EngineTests(methodName="runTest")
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.root = self.f.root

    def completed(self):
        f = self.f
        f.opened()
        f.implement_all()
        f.review()
        f.c.gate_phase("P01")
        f.c.stack_publish("P01")
        f.c.phase_seal("P01")
        return f.c.gate_project()

    def export(self):
        path = self.root / ".rdd/runtime/recovery-checkpoint.json"
        self.f.c.export_run(path)
        return path

    def empty_runtime_store(self):
        """Simulate a fresh local Store without altering source or frozen artifacts."""
        self.f.c.close()
        for suffix in ("", "-wal", "-shm"):
            (self.root / (".rdd/runtime/state.sqlite3" + suffix)).unlink(missing_ok=True)
        shutil.rmtree(self.root / ".rdd/evidence", ignore_errors=True)
        (self.root / ".rdd/run.json").unlink(missing_ok=True)
        self.f.c = engine.Controller(self.root)
        self.addCleanup(self.f.c.close)

    def assert_no_import(self):
        self.assertFalse(self.f.c.store.exists("fixture-run"))
        self.assertFalse((self.root / ".rdd/run.json").exists())
        self.assertFalse(any((self.root / ".rdd/evidence").rglob("*")))

    def submission(self):
        claim = self.f.c.task_claim("T001", "rdd_complex_implementor", session_id="recovery-worker")
        worker = self.root / claim["lease"]["worktree"]
        path = worker / "tests/behavior.py"
        path.write_text(engine_fixture.BEHAVIOR_TEST + "\n" + path.read_text())
        sha = self.f.commit("Recovery fixture behavioral test", root=worker)
        return claim, worker, sha

    def interrupt_integration(self, sha, *, after_pick):
        real_git = engine.git

        def interrupted(root, *args, **kwargs):
            if args and args[0] == "cherry-pick":
                if after_pick:
                    real_git(root, *args, **kwargs)
                raise KeyboardInterrupt("Simulated controller interruption")
            return real_git(root, *args, **kwargs)

        with patch("tools.rdd.engine.git", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.f.c.task_integrate("T001", sha)

    def amend(self, *, paths=None):
        """Begin a changed-requirement run; return a complete amended manifest."""
        self.f.prepared()
        parent = self.f.c.state()["spec_digest"]
        path = self.root / "requirements/requirements.md"
        path.write_text(path.read_text().replace("preserve an accepted value", "durably preserve an accepted value"))
        self.f.commit("Change the fixture requirement")
        result = self.f.c.start("amend", "fixture-amend")
        self.assertEqual(result["changed_requirements"], ["FR-001"])
        spec = self.f.c.spec()
        spec.update(id="fixture-amend", mode="amend", parent_spec_digest=parent,
                    requirements_digest=self.f.c.state()["requirements_digest"],
                    change_summary="Amend the preserved value's durability requirement.")
        spec["amendment"] = dict(requirements=["FR-001"],
            paths=paths or ["modules/", "tests/", "docs/usage.md"],
            rationale="The changed persistence rule affects its owner, behavioral tests and usage guidance.")
        write_json(self.root / ".rdd/spec.json", spec)
        return spec, parent

    def test_completed_checkpoint_restores_raw_logs_and_reports_into_fresh_store(self):
        report = self.completed()
        checkpoint = self.export()
        saved = read_json(checkpoint)
        original_head = head(self.root)
        self.empty_runtime_store()
        result = self.f.c.resume(checkpoint)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.f.c.state()["checks"], saved["state"]["checks"])
        self.assertEqual(self.f.c.state()["phases"]["P01"]["status"], "sealed")
        for rel, content in saved["evidence"].items():
            self.assertEqual((self.root / rel).read_text(), content)
        self.assertTrue(read_json(self.root / report["report"])["application_complete"])
        self.assertEqual(head(self.root), original_head)
        self.assertEqual(self.f.c.anchors_verify()["remaining"], 0)

    def test_claimed_and_released_task_cannot_drop_or_forge_runtime_identity(self):
        self.f.opened()
        c = self.f.c
        untouched = read_json(self.export())
        c.validate_checkpoint_state(untouched["state"], untouched)
        c.task_claim("T001", "rdd_complex_implementor", worktree=False, session_id="actual-fixture-worker")
        for release in (False, True):
            if release:
                c.task_release("T001", "Preserve the attempted work")
            original = read_json(self.export())
            c.validate_checkpoint_state(original["state"], original)
            for field, value in (("worker", None), ("worker", "rdd_large"), ("requested_runtime", None),
                                 ("requested_runtime", {"role": "rdd_complex_implementor", "verified": True})):
                changed = copy.deepcopy(original)
                changed["state"]["tasks"]["T001"][field] = value
                with self.subTest(released=release, field=field, value=value), self.assertRaisesRegex(RddError, "requested runtime"):
                    c.validate_checkpoint_state(changed["state"], changed)
            changed = copy.deepcopy(original)
            task = changed["state"]["tasks"]["T001"]
            task.pop("worker")
            task.pop("requested_runtime")
            with self.assertRaisesRegex(RddError, "requested runtime"):
                c.validate_checkpoint_state(changed["state"], changed)

    def test_export_rejects_changed_raw_log_without_creating_checkpoint(self):
        self.f.prepared()
        receipt = next(iter(self.f.c.state()["checks"].values()))
        log = self.root / receipt["log_path"]
        log.write_text(log.read_text() + "\nchanged")
        dest = self.root / ".rdd/runtime/rejected-export.json"
        with self.assertRaisesRegex(RddError, "changed evidence logs"):
            self.f.c.export_run(dest)
        self.assertFalse(dest.exists())

    def test_raw_log_tampering_is_rejected_before_any_import_write(self):
        self.f.prepared()
        path = self.export()
        checkpoint = read_json(path)
        receipt = next(iter(checkpoint["state"]["checks"].values()))
        checkpoint["evidence"][receipt["log_path"]] += "\nchanged"
        checkpoint["evidence"][".rdd/evidence/must-not-be-written.txt"] = "sentinel"
        write_json(path, checkpoint)
        self.empty_runtime_store()
        with self.assertRaisesRegex(RddError, "digest mismatch|hash mismatch"):
            self.f.c.resume(path)
        self.assert_no_import()

    def test_import_rejects_changed_preparation_baseline_before_any_write(self):
        self.f.prepared()
        path = self.export()
        checkpoint = read_json(path)
        checkpoint["baseline"]["prepared_digest"] = "0" * 64
        write_json(path, checkpoint)
        self.empty_runtime_store()
        with self.assertRaises(RddError):
            self.f.c.resume(path)
        self.assert_no_import()

    def test_import_cannot_turn_pending_tasks_into_a_completed_run(self):
        self.f.prepared()
        path = self.export()
        checkpoint = read_json(path)
        checkpoint["state"]["status"] = "complete"
        write_json(path, checkpoint)
        self.empty_runtime_store()
        with self.assertRaises(RddError):
            self.f.c.resume(path)
        self.assert_no_import()

    def test_expired_lease_preserves_dirty_work_and_claims_a_distinct_attempt(self):
        self.f.opened()
        claim = self.f.c.task_claim("T001", "rdd_complex_implementor", session_id="expired-worker")
        worker = self.root / claim["lease"]["worktree"]
        draft = worker / "tests/behavior.py"
        content = "# Valuable unfinished test work\n" + draft.read_text()
        draft.write_text(content)
        state = self.f.c.state()
        state["tasks"]["T001"]["lease_expires"] = 0
        self.f.c.save(state)
        before = head(self.root)
        self.f.c.resume()
        self.assertEqual(self.f.c.state()["tasks"]["T001"]["status"], "todo")
        self.assertEqual(draft.read_text(), content)
        self.assertEqual(head(self.root), before)
        next_claim = self.f.c.task_claim("T001", "rdd_complex_implementor", session_id="fresh-worker")
        self.assertEqual(next_claim["lease"]["attempts"], 2)
        self.assertNotEqual(next_claim["lease"]["worktree"], claim["lease"]["worktree"])
        self.assertEqual(draft.read_text(), content)
        self.assertTrue(self.f.g("status", "--porcelain", root=worker))

    def test_released_and_expired_attempts_can_enroll_without_losing_work(self):
        self.f.opened()
        c = self.f.c
        for expired in (False, True):
            claim = c.task_claim("T001", "rdd_complex_implementor", session_id=f"repair-author-{expired}")
            worker = self.root / claim["lease"]["worktree"]
            path = worker / "tests/behavior.py"
            path.write_text("# Uncommitted valuable correction\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
            content = path.read_bytes()
            self.f.live_review(findings=[self.f.finding(f"F-{expired}")])
            if expired:
                state = c.state()
                state["tasks"]["T001"]["lease_expires"] = 0
                c.save(state)
                c.resume()
            else:
                c.task_release("T001", "Preserve the interrupted attempt")
            result = c.task_reopen("T001", "Enroll the attempted task for a scoped correction")
            self.assertIn(f"F-{expired}", result["finding_ids"])
            self.assertEqual(c.state()["tasks"]["T001"]["attempts"], claim["lease"]["attempts"])
            self.assertEqual(path.read_bytes(), content)
            self.assertTrue(self.f.g("status", "--porcelain", root=worker))
        final = c.task_claim("T001", "rdd_complex_implementor", session_id="final-repair-author")
        self.assertEqual(final["lease"]["attempts"], 3)
        self.assertNotEqual(final["lease"]["worktree"], claim["lease"]["worktree"])

    def test_repair_authorization_checkpoint_roundtrip_and_tampering(self):
        self.f.opened()
        c = self.f.c
        c.task_claim("T001", "rdd_complex_implementor", session_id="repair-author")
        self.f.live_review(findings=[self.f.finding(), self.f.finding("OTHER", ("T003",)),
                                     self.f.finding("GLOBAL", (), "low")])
        c.task_reopen("T001", "Enroll the exact reviewed assertion")
        path = self.export()
        checkpoint = read_json(path)
        self.empty_runtime_store()
        c = self.f.c
        c.resume(path)
        self.assertEqual(c.state()["tasks"]["T001"]["repair_findings"], ["F1"])
        # Later reviews do not invalidate the old prefix or expand its permission.
        self.f.live_review(findings=[self.f.finding("NEW")])
        self.f.live_review(resolutions=[dict(finding_id="F1", evidence="Verified the correction in the current fixture.")])
        current = read_json(self.export())
        c.validate_checkpoint_state(current["state"], current)
        for case in ("invented", "missing-event", "missing-list", "mismatch", "unscoped", "other-task",
                     "future-finding", "wrong-cursor", "already-resolved"):
            changed = copy.deepcopy(current)
            state = changed["state"]
            record = state["tasks"]["T001"]
            repair = next(e for e in reversed(state["events"]) if e["action"] == "open_phase_repair")
            if case == "missing-event":
                state["events"].remove(repair)
            elif case == "missing-list":
                record.pop("repair_findings")
            elif case == "mismatch":
                record["repair_findings"] = []
            elif case == "wrong-cursor":
                repair["review_cursor"] = True
            elif case == "already-resolved":
                state["events"].remove(repair)
                state["events"].append(repair)
                repair["review_cursor"] = len(state["live_reviews"])
            else:
                fid = {"invented": "INVENTED", "unscoped": "GLOBAL", "other-task": "OTHER",
                       "future-finding": "NEW"}[case]
                record["repair_findings"] = repair["finding_ids"] = [fid]
            with self.subTest(case=case), self.assertRaisesRegex(RddError, "repair authorization"):
                c.validate_checkpoint_state(state, changed)
        # Reject import before writing either state or exported evidence.
        write_json(path, changed)
        self.empty_runtime_store()
        with self.assertRaisesRegex(RddError, "repair authorization"):
            self.f.c.resume(path)
        self.assert_no_import()

    def test_unattempted_task_and_invented_live_repair_cannot_gain_exemptions(self):
        self.f.opened()
        c = self.f.c
        self.f.live_review(findings=[self.f.finding()])
        self.f.assert_transition_rejected(lambda: c.task_reopen("T001", "Not an attempted repair"), "prior attempt")
        state = c.state()
        state["tasks"]["T001"]["repair_findings"] = ["F1"]
        c.save(state)  # Deliberately corrupt the mutable list, with no repair event.
        self.f.assert_transition_rejected(
            lambda: c.task_claim("T001", "rdd_complex_implementor", session_id="invented-repair"), "repair authorization")

    def regenerate_fixture(self):
        """Re-prepare the same isolated tasks under a new run identity."""
        spec = self.f.c.spec()
        self.f.c.start("regenerate", "fixture-next")
        archive = self.root / ".rdd/baselines/fixture-next/previous"
        for rel in spec["documents"] + spec["contract_files"] + spec["generated_files"]:
            shutil.copyfile(archive / rel, self.root / rel)
        spec.update(id="fixture-next", parent_spec_digest=self.f.c.state()["parent_spec_digest"])
        write_json(self.root / ".rdd/spec.json", spec)
        self.f.opened()

    def test_new_run_preserves_prior_worktree_and_packet(self):
        self.f.opened()
        first = self.f.c.task_claim("T001", "rdd_complex_implementor", session_id="fixture-worker")
        worker = self.root / first["lease"]["worktree"]
        draft = worker / "tests/behavior.py"
        content = "# Preserve this unfinished work\n" + draft.read_text()
        draft.write_text(content)
        packet = (self.root / first["packet"]).read_bytes()
        self.f.c.task_release("T001", "Preserve work before regeneration")
        self.regenerate_fixture()
        second = self.f.c.task_claim("T001", "rdd_complex_implementor", session_id="fixture-worker")
        self.assertEqual(second["lease"]["attempts"], 1)
        self.assertNotEqual(first["lease"]["worktree"], second["lease"]["worktree"])
        self.assertNotEqual(first["packet"], second["packet"])
        self.assertTrue((self.root / second["lease"]["worktree"] / ".git").is_file())
        self.assertEqual(read_json(self.root / second["packet"])["run_id"], "fixture-next")
        self.assertEqual(draft.read_text(), content)
        self.assertEqual((self.root / first["packet"]).read_bytes(), packet)

    def test_new_run_preserves_packets_without_worktrees(self):
        self.f.opened()
        first = self.f.c.task_claim("T001", "rdd_complex_implementor", worktree=False, session_id="fixture-worker")
        packet = (self.root / first["packet"]).read_bytes()
        self.f.c.task_release("T001", "Preserve packet before regeneration")
        self.regenerate_fixture()
        second = self.f.c.task_claim("T001", "rdd_complex_implementor", worktree=False, session_id="fixture-worker")
        self.assertEqual(second["lease"]["attempts"], 1)
        self.assertIsNone(second["lease"]["worktree"])
        self.assertNotEqual(first["packet"], second["packet"])
        self.assertEqual((self.root / first["packet"]).read_bytes(), packet)

    def test_checkpoint_accepts_historical_worktree_path(self):
        self.f.opened()
        claim = self.f.c.task_claim("T001", "rdd_complex_implementor", session_id="fixture-worker")
        legacy = ".rdd/runtime/worktrees/T001-a1"
        if claim["lease"]["worktree"] != legacy:
            self.f.g("worktree", "move", claim["lease"]["worktree"], legacy)
        state = self.f.c.state()
        state["tasks"]["T001"]["worktree"] = legacy
        self.f.c.save(state)
        checkpoint = self.export()
        self.empty_runtime_store()
        self.f.c.resume(checkpoint)
        restored = self.f.c.state()["tasks"]["T001"]
        self.assertEqual(restored["worktree"], legacy)
        self.assertEqual(restored["status"], "claimed")
        self.assertEqual(self.f.g("branch", "--show-current", root=self.root / legacy), claim["lease"]["branch"])

    def test_interrupted_integration_before_pick_can_resume_and_retry(self):
        self.f.opened()
        _, worker, sha = self.submission()
        before = head(self.root)
        self.interrupt_integration(sha, after_pick=False)
        self.assertEqual(self.f.c.state()["tasks"]["T001"]["integration"]["status"], "pending")
        self.f.c.resume()
        record = self.f.c.state()["tasks"]["T001"]
        self.assertEqual(record["status"], "claimed")
        self.assertNotIn("integration", record)
        self.assertEqual(head(self.root), before)
        self.assertEqual(head(worker), sha)
        self.assertEqual(self.f.c.task_integrate("T001", sha)["status"], "integrated")

    def test_interrupted_integration_after_pick_recovers_without_duplicate_commit(self):
        self.f.opened()
        _, _, sha = self.submission()
        self.interrupt_integration(sha, after_pick=True)
        picked = head(self.root)
        self.f.c.resume()
        record = self.f.c.state()["tasks"]["T001"]
        self.assertEqual(record["status"], "integrated")
        self.assertEqual(record["commit"], picked)
        self.assertEqual(record["submission"], sha)
        self.assertEqual(record["integration"]["status"], "complete")
        self.assertEqual(head(self.root), picked)
        self.assertTrue(any(e["action"] == "integration_recovered" for e in self.f.c.state()["events"]))

    def test_ambiguous_interrupted_integration_rejects_and_preserves_commits(self):
        self.f.opened()
        _, worker, sha = self.submission()
        self.interrupt_integration(sha, after_pick=True)
        self.f.write("docs/unleased.md", "Unrelated coordinator change to preserve.\n")
        changed = self.f.commit("Preserve unrelated coordinator work")
        with self.assertRaisesRegex(RddError, "cannot be reconciled"):
            self.f.c.resume()
        self.assertEqual(head(self.root), changed)
        self.assertEqual(head(worker), sha)
        self.assertEqual(self.f.c.state()["tasks"]["T001"]["integration"]["status"], "pending")

    def test_amendment_requires_exact_parent_and_changed_requirement_impact(self):
        spec, parent = self.amend()
        archived = self.root / ".rdd/baselines/fixture-amend/previous/.rdd/spec.lock.json"
        self.assertEqual(read_json(archived)["digest"], parent)
        self.assertTrue((self.root / "docs/specs/fixture.md").is_file())
        original = copy.deepcopy(spec)
        for field, value in (("parent_spec_digest", "0" * 64), ("amendment", {**spec["amendment"], "requirements": []})):
            with self.subTest(field=field):
                changed = copy.deepcopy(original)
                changed[field] = value
                write_json(self.root / ".rdd/spec.json", changed)
                with self.assertRaises(RddError):
                    self.f.c.spec_freeze()
                self.assertFalse((self.root / ".rdd/spec.lock.json").exists())
        write_json(self.root / ".rdd/spec.json", original)
        self.f.stage_ready("specification")
        result = self.f.c.spec_freeze()
        self.assertEqual(result["status"], "specified")
        self.assertNotEqual(result["spec_digest"], parent)

    def test_amendment_plan_cannot_expand_outside_frozen_impact_paths(self):
        self.amend(paths=["modules/value.py"])
        self.f.stage_ready("specification")
        frozen = self.f.c.spec_freeze()
        self.f.c.plan_init()
        plan = copy.deepcopy(self.f.plan)
        plan["spec_digest"] = frozen["spec_digest"]
        write_json(self.root / ".rdd/plan/plan.json", plan)
        with self.assertRaisesRegex(RddError, "outside frozen impact"):
            self.f.c.plan_freeze()
        self.assertFalse((self.root / ".rdd/plan/plan.lock.json").exists())

    def test_regenerate_archives_derived_artifacts_and_preserves_application_source(self):
        self.f.prepared()
        old_spec = self.f.c.spec()
        original = {rel: (self.root / rel).read_bytes() for rel in old_spec["documents"] + old_spec["contract_files"] + old_spec["generated_files"]}
        self.f.c.start("regenerate", "fixture-regenerated")
        for rel, content in original.items():
            self.assertEqual((self.root / ".rdd/baselines/fixture-regenerated/previous" / rel).read_bytes(), content)
            self.assertFalse((self.root / rel).exists())
        self.assertEqual((self.root / "modules/value.py").read_text(), "def value():\n    return None\n")
        self.assertTrue((self.root / "modules/obsolete.py").exists())
        self.assertFalse((self.root / ".rdd/spec.lock.json").exists())
        self.assertFalse((self.root / ".rdd/plan/plan.json").exists())
        self.assertEqual(self.f.c.spec_init()["status"], "authoring_template")
        self.assertEqual(self.f.c.spec()["mode"], "regenerate")

    def test_detached_head_start_rejection_preserves_existing_frozen_baseline(self):
        self.f.prepared()
        before = inventory(self.root)
        self.f.g("checkout", "--detach", "HEAD")
        with self.assertRaisesRegex(RddError, "named Git branch"):
            self.f.c.start("regenerate", "must-not-start")
        self.assertEqual(inventory(self.root), before)
        self.assertFalse((self.root / ".rdd/baselines/must-not-start").exists())


if __name__ == "__main__":
    unittest.main()
