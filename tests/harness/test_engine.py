"""Real local state/Git/TDD lifecycle tests with explicit external boundary fakes.

The Protobuf command below is a labelled controller-fixture stand-in; real
contract generation is tested separately. GitHub is mocked and receives no API
calls. Python fixture behavior is actually executed for RED and GREEN evidence.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from test_artifacts import Fixture, check, task
from tools.rdd.common import RddError, head, read_json, source_digest, write_json
from tools.rdd.engine import Controller


BEHAVIOR_TEST = '''import importlib.util
from pathlib import Path

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

value = load("fixture_value", "modules/value.py")
assert value.value() == 42, "EXPECTED_ASSERTION: value is unavailable or incorrect"
extension = load("fixture_extension", "modules/extension.py")
assert extension.label() == "fixture", "EXPECTED_ASSERTION: extension label is incorrect"
assert not Path("modules/obsolete.py").exists(), "EXPECTED_ASSERTION: obsolete fixture remains"
print("Fixture behavioral assertions passed")
'''


class FakeGitHub:
    """An explicit no-network fake for controller transitions, not adapter tests."""
    def __init__(self):
        self.ready = True
        self.published = []
        self.observed = []

    def publish_phase_pr(self, run_id, phase, base, body_path, **kwargs):
        self.published.append(dict(run_id=run_id, phase=phase, base=base,
                                   body=Path(body_path).read_text(), options=kwargs))
        return dict(number=phase, url=f"https://example.invalid/fixture/pull/{phase}")

    def phase_status(self, number, sha, base, checks, **kwargs):
        self.observed.append(dict(number=number, sha=sha, base=base, checks=checks, options=kwargs))
        return dict(ready=self.ready, blockers=[] if self.ready else ["Required fixture CI is pending"],
                    number=number, url=f"https://example.invalid/fixture/pull/{number}",
                    head_sha=sha, state="OPEN")


class EngineTests(Fixture):
    def setUp(self):
        super().setUp()
        self.write(".gitignore", ".rdd/runtime/\n.rdd/evidence/\n.rdd/run.json\n__pycache__/\n*.pyc\n.rsync-tmp/\n")
        self.write(".rdd/config.json", json.dumps(self.config))
        self.write("modules/value.py", "def value():\n    return None\n")
        self.write("modules/obsolete.py", "legacy_value = 1\n")
        self.write("tools/fixture_proto_probe.py", "from pathlib import Path\n"
            "assert Path('contracts/fixture/v1/fixture.proto').is_file()\n"
            "assert Path('gen/fixture.rs').is_file()\n"
            "print('MOCK PROTO COMPILER: controller lifecycle fixture only')\n")
        self.spec["modules"][0]["owns_paths"] = ["modules/value.py", "modules/extension.py"]
        self.spec["checks"][0]["argv"] = ["{python}", "-B", "tools/fixture_proto_probe.py"]
        self.spec["checks"][1]["argv"] = ["{python}", "-B", "tests/behavior.py"]
        self.spec["checks"][1]["red_pattern"] = "AssertionError: EXPECTED_ASSERTION"
        self.spec["scenarios"][0]["expected"] = "The fixture value is 42 and its extension label is fixture."
        tasks = [task("T001", "tests", "tests/behavior.py", []),
                 task("T002", "deletion", "modules/obsolete.py", ["T001"]),
                 task("T003", "modification", "modules/value.py", ["T002"]),
                 task("T004", "addition", "modules/extension.py", ["T003"]),
                 task("T005", "documentation", "docs/usage.md", ["T004"])]
        self.plan["tasks"] = tasks
        self.plan["phases"][0].update(tasks=[t["id"] for t in tasks], deliverables=["modules/value.py", "modules/extension.py", "docs/usage.md"])
        self.plan["verticals"][0]["tasks"] = [t["id"] for t in tasks]
        self.plan["target_paths"] = [t["writes"][0] for t in tasks]
        self.plan["shells"] = [dict(path=p, content="") for p in ("tests/behavior.py", "modules/extension.py", "docs/usage.md")]
        self.hub = FakeGitHub()
        self.hub_patch = patch("tools.rdd.engine.GitHubAdapter", lambda root: self.hub)
        self.hub_patch.start()
        self.addCleanup(self.hub_patch.stop)
        self.c = Controller(self.root)
        self.addCleanup(self.c.close)
        self.c.init()
        self.g("config", "user.name", "RDD Engine Fixture")
        self.g("config", "user.email", "fixture@example.invalid")
        self.commit("Initial controller fixture")
        self.g("switch", "-c", "codex/test-baseline")
        self.c.start("regenerate", "fixture-run")
        self.c.spec_init()
        self.spec["id"] = "fixture-run"
        write_json(self.root / ".rdd/spec.json", self.spec)

    def g(self, *args, root=None):
        proc = subprocess.run(["git", *args], cwd=root or self.root, check=False,
                              text=True, capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0, f"git {args}: {proc.stderr}")
        return proc.stdout.strip()

    def commit(self, message, root=None):
        self.g("add", "-A", root=root)
        self.g("commit", "-q", "-m", message, root=root)
        return self.g("rev-parse", "HEAD", root=root)

    def prepared(self):
        result = self.c.spec_freeze()
        self.plan["spec_digest"] = result["spec_digest"]
        self.commit("Freeze fixture specification")
        self.c.plan_init()
        write_json(self.root / ".rdd/plan/plan.json", self.plan)
        self.c.plan_freeze()
        self.c.prepare()
        self.commit("Commit fixture preparation")

    def opened(self):
        self.prepared()
        self.c.phase_begin("P01")

    def submit(self, tid, changes):
        claim = self.c.task_claim(tid, "rdd_large", worktree=True, session_id=f"worker-{tid}")
        worker = self.root / claim["lease"]["worktree"]
        for rel, content in changes.items():
            p = worker / rel
            if content is None:
                p.unlink()
                continue
            prior = p.read_text() if p.exists() else ""
            markers = [line for line in prior.splitlines() if "RDD:P" in line]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content + ("\n" if content and not content.endswith("\n") else "")
                         + "".join(line + "\n" for line in markers))
        sha = self.commit(f"Fixture submission {tid}", root=worker)
        return self.c.task_integrate(tid, sha)

    def finish(self, tid, evidence_id=None):
        result = self.c.task_complete(tid, evidence_id)
        if self.g("status", "--porcelain"):
            # An inline deletion already removed its marker in the submitted commit.
            self.commit(f"Record fixture marker cleanup {tid}")
        return result

    def red_task(self, program=BEHAVIOR_TEST):
        self.submit("T001", {"tests/behavior.py": program})
        return self.c.check("behavior", "fail", "T001")

    def implement_all(self):
        red = self.red_task()
        self.assertEqual(red["outcome"], "red")
        self.finish("T001", red["id"])
        changes = [("T002", {"modules/obsolete.py": None}),
                   ("T003", {"modules/value.py": "def value():\n    return 42\n"}),
                   ("T004", {"modules/extension.py": 'def label():\n    return "fixture"\n'}),
                   ("T005", {"docs/usage.md": "# Fixture usage\n\nRead the preserved fixture value and extension label.\n"})]
        for tid, files in changes:
            self.submit(tid, files)
            self.finish(tid)

    def review(self, **changes):
        record = dict(schema_version=1, phase="P01", source_commit=head(self.root),
            source_digest=source_digest(self.root), model=self.config["models"]["reviewer"]["model"],
            reviewer="rdd_reviewer", session_id="independent-reviewer-fixture", decision="pass",
            summary="An independent fixture review covers the exact current phase behavior and evidence.",
            checks_reviewed=["behavior", "contract"], findings=[])
        record.update(changes)
        path = self.root / ".rdd/runtime/review.json"
        write_json(path, record)
        return self.c.review_record(path)

    def test_full_real_local_tdd_to_project_validation_with_fake_github(self):
        self.opened()
        self.implement_all()
        self.assertEqual(self.c.anchors_verify()["remaining"], 0)
        self.review()
        gate = self.c.gate_phase("P01")
        self.assertEqual(gate["status"], "passed")
        self.c.stack_publish("P01")
        self.assertEqual(self.hub.published[0]["base"], "codex/test-baseline")
        self.assertTrue(self.c.stack_verify()["ready"])
        self.assertEqual(self.c.phase_seal("P01")["status"], "sealed")
        report = self.c.gate_project()
        self.assertTrue(report["application_complete"])
        saved = read_json(self.root / report["report"])
        self.assertEqual(saved["tasks_completed"], 5)
        self.assertEqual(saved["remaining_anchors"], 0)
        self.assertEqual(saved["source_commit"], head(self.root))
        self.assertEqual(self.c.status()["status"], "complete")

    def test_phase_cannot_begin_before_preparation(self):
        with self.assertRaises(RddError):
            self.c.phase_begin("P01")

    def test_two_phases_are_sequential_and_second_pr_targets_first_branch(self):
        foundation = check("foundation", red="AssertionError: EXPECTED_ASSERTION")
        foundation["argv"] = ["{python}", "-B", "tests/foundation.py"]
        self.spec["checks"].append(foundation)
        write_json(self.root / ".rdd/spec.json", self.spec)
        tasks = [task("T001", "tests", "tests/foundation.py", []),
                 task("T002", "deletion", "modules/obsolete.py", ["T001"]),
                 task("T003", "modification", "modules/value.py", ["T002"]),
                 task("T004", "tests", "tests/behavior.py", ["T003"]),
                 task("T005", "addition", "modules/extension.py", ["T004"]),
                 task("T006", "documentation", "docs/usage.md", ["T005"])]
        for t in tasks[:3]:
            t["checks"] = ["foundation"]
        for t in tasks[3:]:
            t["phase"] = "P02"
        self.plan["tasks"] = tasks
        first = copy.deepcopy(self.plan["phases"][0])
        first.update(tasks=["T001", "T002", "T003"], checks=["foundation"],
                     requirements_closed=[], deliverables=["modules/value.py"],
                     goal="The core fixture value is available; extension remains unavailable.")
        second = copy.deepcopy(first)
        second.update(id="P02", tasks=["T004", "T005", "T006"], checks=["behavior"],
                      requirements_closed=["FR-001"], deliverables=["modules/extension.py", "docs/usage.md"],
                      goal="The fixture extension and complete observable behavior are available.")
        self.plan["phases"] = [first, second]
        self.plan["verticals"][0]["tasks"] = [t["id"] for t in tasks]
        self.plan["target_paths"] = [t["writes"][0] for t in tasks]
        self.plan["shells"] = [dict(path=p, content="") for p in
                               ("tests/foundation.py", "tests/behavior.py", "modules/extension.py", "docs/usage.md")]
        self.prepared()
        with self.assertRaisesRegex(RddError, "sequentially"):
            self.c.phase_begin("P02")
        first_branch = self.c.phase_begin("P01")["branch"]
        with self.assertRaisesRegex(RddError, "Seal the current phase"):
            self.c.phase_begin("P02")
        basic_program = BEHAVIOR_TEST.split('extension = load', 1)[0]
        self.submit("T001", {"tests/foundation.py": basic_program})
        red = self.c.check("foundation", "fail", "T001")
        self.assertEqual(red["outcome"], "red")
        self.finish("T001", red["id"])
        self.submit("T002", {"modules/obsolete.py": None})
        self.finish("T002")
        self.submit("T003", {"modules/value.py": "def value():\n    return 42\n"})
        self.finish("T003")
        self.review(checks_reviewed=["foundation", "contract"])
        self.c.gate_phase("P01")
        self.c.stack_publish("P01")
        self.c.phase_seal("P01")
        first_sha = head(self.root)
        opened = self.c.phase_begin("P02")
        self.assertEqual(opened["base_branch"], first_branch)
        self.assertEqual(opened["base_sha"], first_sha)
        # Fixture capability discovery has an explicit unavailable result so
        # absence of the optional extension is an assertion, not an import error.
        program = BEHAVIOR_TEST.replace(
            'extension = load("fixture_extension", "modules/extension.py")\nassert extension.label() == "fixture",',
            'extension = load("fixture_extension", "modules/extension.py")\n'
            'label = extension.label() if callable(getattr(extension, "label", None)) else None\n'
            'assert label == "fixture",')
        self.submit("T004", {"tests/behavior.py": program})
        red = self.c.check("behavior", "fail", "T004")
        self.assertEqual(red["outcome"], "red")
        self.finish("T004", red["id"])
        self.submit("T005", {"modules/extension.py": 'def label():\n    return "fixture"\n'})
        self.finish("T005")
        self.submit("T006", {"docs/usage.md": "# Fixture usage\n\nBoth fixture capabilities are available.\n"})
        self.finish("T006")
        self.review(phase="P02", checks_reviewed=["foundation", "behavior", "contract"])
        self.c.gate_phase("P02")
        self.c.stack_publish("P02")
        self.assertEqual(self.hub.published[1]["base"], first_branch)
        self.assertEqual(self.hub.published[1]["options"]["expected_base_sha"], first_sha)
        self.c.phase_seal("P02")
        self.assertTrue(self.c.gate_project()["application_complete"])

    def test_frozen_contract_edits_and_added_boundaries_are_rejected(self):
        self.prepared()
        p = self.root / "contracts/fixture/v1/fixture.proto"
        original = p.read_text()
        p.write_text(original + "// changed contract\n")
        with self.assertRaisesRegex(RddError, "changed"):
            self.c.frozen()
        p.write_text(original)
        self.write("contracts/fixture/v1/new.proto", 'syntax = "proto3";\n')
        with self.assertRaisesRegex(RddError, "inventory"):
            self.c.frozen()

    def test_frozen_policy_change_is_rejected(self):
        self.prepared()
        self.write(".rdd/schemas/spec.schema.json", '{}\n')
        with self.assertRaises(RddError):
            self.c.frozen()

    def test_category_barrier_prevents_early_production_claim(self):
        self.opened()
        self.assertEqual([t["id"] for t in self.c.next()["ready"]], ["T001"])
        with self.assertRaisesRegex(RddError, "not ready"):
            self.c.task_claim("T003", "rdd_large", worktree=True)
        with self.assertRaisesRegex(RddError, "integrated task"):
            self.c.task_complete("T001")

    def test_green_test_cannot_be_used_as_red_evidence(self):
        self.opened()
        receipt = self.red_task('print("No failing fixture assertions")\n')
        self.assertNotEqual(receipt["outcome"], "red")
        with self.assertRaisesRegex(RddError, "behavioral RED"):
            self.c.task_complete("T001", receipt["id"])

    def test_missing_module_is_not_behavioral_red(self):
        self.opened()
        receipt = self.red_task('import deliberately_missing_fixture_module\nassert False, "EXPECTED_ASSERTION"\n')
        self.assertNotEqual(receipt["outcome"], "red")
        with self.assertRaisesRegex(RddError, "behavioral RED"):
            self.c.task_complete("T001", receipt["id"])

    def test_gate_rejects_incomplete_phase(self):
        self.opened()
        with self.assertRaisesRegex(RddError, "Every task"):
            self.c.gate_phase("P01")

    def test_review_session_cannot_be_an_implementor(self):
        self.opened()
        self.c.task_claim("T001", "rdd_large", worktree=True, session_id="same-session")
        with self.assertRaisesRegex(RddError, "distinct"):
            self.review(session_id="same-session")

    def test_review_must_cover_current_commit_and_all_checks(self):
        self.opened()
        for changes in (dict(source_commit="a" * 40), dict(source_digest="b" * 64), dict(checks_reviewed=["contract"])):
            with self.subTest(changes=changes), self.assertRaises(RddError):
                self.review(**changes)

    def test_repaired_source_invalidates_prior_review(self):
        self.opened()
        self.implement_all()
        self.review()
        self.write("modules/value.py", "def value():\n    return 43\n")
        self.commit("Simulate a changed candidate after review")
        with self.assertRaisesRegex(RddError, "independent phase review"):
            self.c.gate_phase("P01")

    def test_open_phase_repair_returns_to_tests_and_invalidates_gate(self):
        self.opened()
        self.implement_all()
        self.review()
        self.c.gate_phase("P01")
        self.c.task_reopen("T003", "Repair existing fixture behavior")
        self.c.task_reopen("T001", "Add regression assertion for the same accepted scope")
        self.commit("Record fixture repair markers")
        self.assertEqual([t["id"] for t in self.c.next()["ready"]], ["T001"])
        self.assertIsNone(self.c.state()["phases"]["P01"]["gate"])
        self.assertNotIn("P01", self.c.state()["reviews"])

    def test_pending_ci_does_not_seal_a_phase(self):
        self.opened()
        self.implement_all()
        self.review()
        self.c.gate_phase("P01")
        self.c.stack_publish("P01")
        self.hub.ready = False
        with self.assertRaisesRegex(RddError, "not ready"):
            self.c.phase_seal("P01")
        self.assertEqual(self.c.state()["phases"]["P01"]["status"], "gated")

    def test_sealed_phase_cannot_be_reopened(self):
        self.opened()
        self.implement_all()
        self.review()
        self.c.gate_phase("P01")
        self.c.stack_publish("P01")
        self.c.phase_seal("P01")
        with self.assertRaises(RddError):
            self.c.task_reopen("T003", "Invalid attempt to rewrite a sealed phase")
        with self.assertRaises(RddError):
            self.c.phase_begin("P01")
        self.assertEqual(self.c.state()["phases"]["P01"]["status"], "sealed")


if __name__ == "__main__":
    unittest.main()
