"""Runtime regressions with real Git/SQLite/review and behavioral RED receipts.

The small runtime fixture seeds the frozen-stage prerequisite; it does not claim
end-to-end specification/preparation qualification or live GitHub observations.
"""
from pathlib import Path
import copy
import tempfile
import unittest
from unittest.mock import patch

from test_refinement import build_fixture
from tools.rdd import artifacts
from tools.rdd.common import RddError, head, source_digest
from tools.rdd.engine import Controller


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rdd-runtime-")
        self.addCleanup(temporary.cleanup)
        self.f = build_fixture(Path(temporary.name))
        self.c, self.root = self.f.controller, self.f.root
        self.addCleanup(self.c.close)

    def observe(self, tasks=(), nodes=(), identity=None, resolutions=()):
        state = self.c.state()
        finding = dict(id=identity, severity="high", requirements=["FR-001"], tasks=list(tasks),
                       nodes=list(nodes), path="", message="Fixture correction is required.",
                       evidence="Independent fixture observation.")
        report = dict(schema_version=2, kind="live", stage=self.c.review_stage(state),
            phase=state["active_phase"], model=self.c.profile_settings("rdd_reviewer")["model"],
            reviewer="rdd_reviewer", session_id="runtime-reviewer", summary="Independent fixture runtime observation.",
            source_commit=head(self.root), source_digest=source_digest(self.root),
            requirements_digest=state["requirements_digest"], spec_digest=state.get("spec_digest"),
            plan_digest=state.get("plan_digest"), findings=[finding] if identity else [],
            resolutions=[dict(finding_id=fid, evidence="Reviewer independently verified the complete correction.")
                         for fid in resolutions])
        return self.c.review_live_record(self.f.input_file(report))

    def runtime(self, categories=("modification", "modification"), context=None):
        tasks = [dict(id=f"T{i:03}", phase="P01", category=category, scope="small", title="Repair fixture behavior",
            requirements=["FR-001"], writes=[f"modules/item{i}.py"], checks=["C-APP"], depends_on=[],
            sites=[dict(id="A01", primary=True, mode="inline", path=f"modules/item{i}.py",
                        placement=dict(kind="before" if context else "append", context=context), instructions="Repair behavior.")])
                 for i, category in enumerate(categories, 1)]
        self.plan = dict(tasks=tasks, phases=[dict(id="P01", checks=["C-APP"], tasks=[t["id"] for t in tasks])],
                         verticals=[dict(id="V01", tasks=[t["id"] for t in tasks])],
                         target_paths=[t["writes"][0] for t in tasks], shells=[])
        check = dict(id="C-APP", kind="test", argv=["{python}", tasks[0]["writes"][0]], cwd=".",
                     platforms=["any"], timeout_seconds=10, host_profile=None, red_pattern="AssertionError: required order",
                     scenario_ids=[], results_path=None)
        self.spec = dict(checks=[check], contract_files=[], generated_files=[], contract_check_ids=[],
                         project_check_ids=["C-APP"], requirement_map=[], scenarios=[])
        for method, value in (("frozen", None), ("plan", self.plan), ("spec", self.spec)):
            prerequisite = patch.object(self.c, method, return_value=value)
            prerequisite.start()
            self.addCleanup(prerequisite.stop)
        # Only packet context is synthetic; leasing, ownership and integration remain real.
        packet_context = patch("tools.rdd.engine.task_boundary_context", return_value={})
        packet_context.start()
        self.addCleanup(packet_context.stop)
        state = self.c.state()
        state.update(status="implementation", active_phase="P01", spec_digest="a" * 64, plan_digest="b" * 64, prepared_digest="c" * 64,
                     tasks={t["id"]: dict(status="todo", attempts=0, evidence=[], commit=None, session_id=None) for t in tasks},
                     phases={"P01": dict(status="active", branch="test-refinement", gate=None, review=None)})
        self.c.save(state)
        for task in tasks:
            self.f.text(task["writes"][0], (context or "# Original fixture behavior") + "\n")
        artifacts.materialize(self.root, self.plan, state, create_shells=False)
        self.f.commit()
        self.observe()
        return tasks

    def claim(self, tid):
        return self.c.task_claim(tid, "rdd_complex_implementor", session_id="worker-" + tid)["lease"]

    def submit(self, task, lease, behavior="# Revised fixture behavior\n"):
        worker = self.root / lease["worktree"]
        path = worker / task["writes"][0]
        path.write_text(path.read_text() + behavior)
        self.f.git("-C", str(worker), "add", ".")
        self.f.git("-C", str(worker), "commit", "-m", "Isolated fixture correction")
        return self.f.git("-C", str(worker), "rev-parse", "HEAD")

    def test_global_finding_needs_explicit_bounded_correction_claim(self):
        self.c.spec_init()
        self.f.commit()
        self.observe(identity="F-GLOBAL")
        with self.assertRaises(RddError):
            self.f.claim("S0", ["docs/specs/intake.md"])
        claim = self.c.workflow_claim("S0", "author-S0", "rdd_coordinator", ["docs/specs/intake.md"], "F-GLOBAL")
        self.assertEqual(claim["claim"]["finding"], "F-GLOBAL")
        self.assertIsNone(self.c.state()["live_findings"]["F-GLOBAL"]["resolution"])
        self.observe(identity="F-UNRELATED")
        with self.assertRaisesRegex(RddError, "F-UNRELATED"):
            self.c.live_review_guard(final=False, node="S0", correction="F-GLOBAL")
        with self.assertRaises(RddError):
            self.c.workflow_claim("S0", "other-author", "rdd_coordinator", ["requirements/requirements.md"], "F-GLOBAL")

    def parallel_cleanup(self, after_integration):
        first, second = self.runtime()
        a = self.claim(first["id"])
        if not after_integration:
            b = self.claim(second["id"])
        self.c.task_integrate(first["id"], self.submit(first, a))
        if after_integration:
            b = self.claim(second["id"])
        submission = self.submit(second, b)
        self.c.task_complete(first["id"])
        self.f.commit("Peer marker cleanup")
        self.assertEqual(self.c.task_integrate(second["id"], submission)["status"], "integrated")
        self.assertEqual(artifacts.anchors_verify(self.root, self.plan, self.c.state())["remaining"], 1)

    def test_parallel_lease_before_peer_integration_survives_cleanup(self):
        self.parallel_cleanup(False)

    def test_parallel_lease_after_peer_integration_survives_cleanup(self):
        self.parallel_cleanup(True)

    def test_worker_cannot_remove_peer_marker(self):
        first, second = self.runtime()
        lease = self.claim(first["id"])
        worker = self.root / lease["worktree"]
        artifacts.remove_anchor(worker, second, self.plan)
        submission = self.submit(first, lease)
        with self.assertRaisesRegex(RddError, "outside its lease"):
            self.c.task_integrate(first["id"], submission)
        self.assertEqual(self.c.state()["tasks"][first["id"]]["status"], "claimed")

    def complete_selector(self, replacement):
        task = self.runtime(("modification",), context="# Original selector")[0]
        lease = self.claim(task["id"])
        path = self.root / lease["worktree"] / task["writes"][0]
        path.write_text(path.read_text().replace("# Original selector\n", replacement))
        self.c.task_integrate(task["id"], self.submit(task, lease))
        self.c.task_complete(task["id"])
        self.f.commit("Completed selector replacement")
        return task

    def test_reopen_projection_failure_is_recoverable_after_restart(self):
        task = self.complete_selector("# Replacement behavior\n")
        materialize = artifacts.materialize
        def interrupt(*args, **kwargs):
            if not kwargs.get("preflight"):
                raise OSError("Injected interruption after durable repair event")
            return materialize(*args, **kwargs)
        with patch("tools.rdd.artifacts.materialize", side_effect=interrupt):
            with self.assertRaises(OSError):
                self.c.task_reopen(task["id"], "Repair completed behavior")
        restarted = Controller(self.root)
        self.addCleanup(restarted.close)
        with patch.object(restarted, "frozen"), patch.object(restarted, "plan", return_value=self.plan):
            self.assertEqual(restarted.anchors_reconcile()["remaining"], 1)
        self.assertEqual(self.c.state()["tasks"][task["id"]]["status"], "todo")

    def test_reopen_ambiguous_selector_preserves_state_and_source(self):
        task = self.complete_selector("# Original selector\n# Original selector\n")
        before, source = self.c.state(), (self.root / task["writes"][0]).read_bytes()
        with self.assertRaisesRegex(RddError, "found 2"):
            self.c.task_reopen(task["id"], "Ambiguous placement must fail before mutation")
        self.assertEqual(self.c.state(), before)
        self.assertEqual((self.root / task["writes"][0]).read_bytes(), source)

    def test_new_task_cannot_use_repair_projection_fallback(self):
        task = self.runtime(("modification",), context="# Original selector")[0]
        artifacts.remove_anchor(self.root, task, self.plan)
        self.f.text(task["writes"][0], "# Selector is absent before any attempt\n")
        before = self.c.state()
        with self.assertRaisesRegex(RddError, "found 0"):
            self.c.anchors_reconcile()
        self.assertEqual(self.c.state(), before)

    def test_completed_projection_flag_requires_historical_completion(self):
        task = self.complete_selector("# Replacement behavior\n")
        self.c.task_reopen(task["id"], "Bounded completed-task repair")
        state = self.c.state()
        state["events"] = [e for e in state["events"] if e["action"] != "task_completed"]
        with self.assertRaisesRegex(RddError, "prior completion event"):
            self.c.task_repair_authorization(state, task["id"])

    def test_finding_remains_open_through_regression_red_and_code_completion(self):
        test, code = self.runtime(("tests", "modification"))
        for task in (test, code):
            lease = self.claim(task["id"])
            behavior = 'assert False, "required order"\n' if task is test else "# Code correction\n"
            self.c.task_integrate(task["id"], self.submit(task, lease, behavior))
            if task is test:
                self.assertEqual(self.c.check("C-APP", "fail", test["id"])["outcome"], "red")
            self.c.task_complete(task["id"])
            self.f.commit("Controller marker cleanup")
            self.observe()
        self.observe(tasks=[test["id"], code["id"]], identity="F-ORDER")
        for task in (test, code):
            self.c.task_reopen(task["id"], "Enroll bounded regression/code repair")
        self.f.commit("Project repair packets")
        with self.assertRaises(RddError):
            self.claim(code["id"])
        for task in (test, code):
            lease = self.claim(task["id"])
            self.c.task_integrate(task["id"], self.submit(task, lease))
            if task is test:
                self.assertEqual(self.c.check("C-APP", "fail", test["id"])["outcome"], "red")
            self.c.task_complete(task["id"])
            self.f.commit("Controller repair marker cleanup")
            self.observe()
        self.assertEqual(self.c.state()["tasks"][code["id"]]["status"], "done")
        self.assertIsNone(self.c.state()["live_findings"]["F-ORDER"]["resolution"])
        with self.assertRaisesRegex(RddError, "findings.*unresolved"):
            self.c.live_review_guard(final=True, cursor=len(self.c.state()["live_reviews"]))
        self.observe(resolutions=["F-ORDER"])
        self.c.live_review_guard(final=True, cursor=len(self.c.state()["live_reviews"]))

    def test_project_rejects_late_finding_without_rewriting_sealed_history(self):
        tasks = self.runtime()
        state = self.c.state()
        for task in tasks:
            state["tasks"][task["id"]]["status"] = "done"
            artifacts.remove_anchor(self.root, task, self.plan)
        state["phases"]["P01"].update(status="sealed", head=head(self.root), seal={"accepted": True})
        state["active_phase"] = None
        self.c.save(state)
        self.f.commit("Sealed fixture source")
        state = self.c.state()
        state["phases"]["P01"]["head"] = head(self.root)
        self.c.save(state)
        seal = copy.deepcopy(state["phases"]["P01"])
        self.observe(identity="F-LATE")
        # Ignore unrelated external/check publication; the current finding guard stays real.
        with patch.object(self.c, "gate_current"), patch.object(self.c, "ensure_checks", return_value=[]), \
                patch.object(self.c, "stack_verify", return_value={"ready": True, "pending_phases": [], "pull_requests": []}), \
                patch.object(self.c, "export_run"):
            with self.assertRaisesRegex(RddError, "findings.*unresolved"):
                self.c.gate_project()
            self.assertFalse((self.root / ".rdd/evidence/project-validation.json").exists())
            self.assertEqual(self.c.state()["phases"]["P01"], seal)
            self.observe(resolutions=["F-LATE"])
            self.assertTrue(self.c.gate_project()["application_complete"])

    def test_final_cumulative_checks_include_scheduled_project_checks(self):
        self.runtime()
        self.assertLessEqual(set(self.spec["project_check_ids"]), set(self.c.cumulative_checks("P01")))


if __name__ == "__main__":
    unittest.main()
