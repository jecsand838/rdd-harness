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
from tools.rdd.checks import execute_check, platform_name


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
import json
results = Path(".rdd/evidence/results/behavior.json")
results.parent.mkdir(parents=True, exist_ok=True)
results.write_text(json.dumps({"scenarios": [{"id": "S1", "outcome": "pass"}]}), encoding="utf-8")
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

    def preparation_status(self, run_url, candidate_sha, expected_harness_sha):
        from tools.rdd.ci_tools import RUNNERS
        return dict(ready=True, url=run_url, run_id=1, head_sha=candidate_sha, harness_sha=expected_harness_sha,
                    attempt=1, workflow_blob="f" * 40, blockers=[],
                    jobs=[dict(id=1, name=f"preparation ({RUNNERS[platform_name()]})", status="completed", conclusion="success")])


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
        self.spec["modules"][0]["owns_paths"] = ["modules/value.py", "modules/extension.py", "modules/obsolete.py"]
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
        self.plan["shells"] = [dict(path=p, content="<!-- Fixture shell -->\n" if p.endswith(".md") else "# Fixture shell\n") for p in ("tests/behavior.py", "modules/extension.py", "docs/usage.md")]
        self.spec["environments"][0]["platform"] = platform_name()
        self.spec["target_tree"] = [dict(path=p, kind="file", owner="E-DOMAIN" if p.startswith("modules/") else "E-SUPPORT",
            purpose="A fixture work site.", disposition="delete" if "obsolete" in p else "modify" if p == "modules/value.py" else "add")
            for p in self.plan["target_paths"]]
        self.spec["resources"] = [dict(id="probe", kind="repository", availability="baseline", required_at="specification",
            path="tools/fixture_proto_probe.py", version=None, probe_check_ids=[], environments=["local"]),
            dict(id="runner", kind="repository", availability="implementation", required_at="implementation",
            path="tests/behavior.py", version=None, probe_check_ids=[], environments=["local"])]
        self.spec["resources"] += [dict(id="fixture-" + role, kind="repository", availability="implementation",
            required_at="implementation", path=path, version=None, probe_check_ids=[], environments=["local"])
            for role, path in (("provider", "modules/value.py"), ("consumer", "modules/extension.py"))]
        self.spec["checks"][2]["argv"] = ["{python}", "-B", "-c", "import runpy; assert runpy.run_path('modules/value.py')['value']() == 42; assert runpy.run_path('modules/extension.py')['label']() == 'fixture'"]
        self.spec["checks"][0]["requires"] = ["probe"]
        self.spec["checks"][1]["requires"] = ["runner"]
        tasks[0]["produces"] = ["runner"]
        tasks[0]["bootstrap_resources"] = ["runner"]
        tasks[2]["produces"] = ["fixture-provider"]
        tasks[3]["produces"] = ["fixture-consumer"]
        self.plan["resource_producers"] = [dict(resource="probe", kind="baseline", task=None, checks=[]),
            dict(resource="runner", kind="task", task="T001", checks=[]),
            dict(resource="fixture-provider", kind="task", task="T003", checks=[]),
            dict(resource="fixture-consumer", kind="task", task="T004", checks=[])]
        self.plan["boundary_proofs"][0].update(provider_tasks=["T003"], consumer_tasks=["T004"],
            adapter_tasks=["T003", "T004"], verification_tasks=["T001"], operation="fixture.v1.FixtureService.Preserve")
        self.plan["resource_uses"] = [dict(resource="runner", consumer_kind="task_red" if t["category"] == "tests" else "task_completion", consumer=t["id"])
            for t in tasks if t["checks"]]
        self.plan["resource_uses"] += [dict(resource=r, consumer_kind=k, consumer="P01" if k == "phase" else None)
            for r in ("runner", "probe", "fixture-provider", "fixture-consumer") for k in ("phase", "project")]
        self.plan["element_coverage"] = [dict(element=e["id"], tasks=[t["id"] for t in tasks], checks=["behavior"], baseline_evidence=None)
            for e in self.spec["solution_elements"]]
        self.hub = FakeGitHub()
        self.hub_patch = patch("tools.rdd.engine.GitHubAdapter", lambda root: self.hub)
        self.hub_patch.start()
        self.addCleanup(self.hub_patch.stop)
        # Explicit external compiler boundary fake. The actual protected driver,
        # descriptor proof parser and Rust compilation have their own real tests.
        for symbol in ("canonical_contract_check", "verify_canonical_contract_receipts"):
            compiler_patch = patch("tools.rdd.stages." + symbol)
            compiler_patch.start()
            self.addCleanup(compiler_patch.stop)
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

    def live_review(self, **changes):
        state = self.c.state(allow_blocked=True)
        stage = self.c.review_stage(state)
        record = dict(schema_version=2, kind="live", stage=stage,
            phase=state.get("active_phase") if stage == "implementation" else None,
            source_commit=head(self.root), source_digest=source_digest(self.root),
            requirements_digest=state["requirements_digest"], spec_digest=state.get("spec_digest"), plan_digest=state.get("plan_digest"),
            model=self.c.profile_settings("rdd_reviewer")["model"], reviewer="rdd_reviewer", session_id="fixture-live-reviewer",
            summary="Independent controller fixture observation of current work and authority.", findings=[], resolutions=[])
        record.update(changes)
        path = self.root / ".rdd/runtime/live-review.json"
        write_json(path, record)
        return self.c.review_record(path)

    def node_complete(self, node, evidence=()):
        from tools.rdd.nodes import NODES
        output = f".rdd/plan/notes/{node}.md" if node.startswith("P") else "docs/specs/fixture.md"
        if node.startswith("P") and not (self.root / output).is_file():
            self.fwrite_node(output, node)
        claim = self.c.workflow_claim(node, "fixture-author", NODES[node]["responsible_roles"][0], [output])["claim"]
        record = dict(schema_version=2, node=node, attempt=claim["attempt"], session_id=claim["session_id"],
            input_digest=claim["input_digest"], outputs=claim["writes"], evidence_ids=list(evidence))
        path = self.root / ".rdd/runtime/node.json"
        write_json(path, record)
        self.c.workflow_record(path)
        self.live_review()

    def fwrite_node(self, output, node):
        self.write(output, f"# {node} controller fixture evidence\n\nThe frozen fixture work sites, input producers, categories and phase dependency closure are represented in .rdd/plan/plan.json.\n")

    def authoring_nodes(self, stage):
        self.live_review()
        wanted = [f"S{i}" for i in range(7)] if stage == "specification" else [f"P{i}" for i in range(6)] if stage == "plan" else []
        for node in wanted:
            if self.c._node_records(self.c.state())[node]["status"] != "complete":
                self.node_complete(node)

    def stage_ready(self, stage, *, ci=False):
        if self.g("status", "--porcelain"):
            self.commit("Commit exact " + stage + " candidate")
        self.c.author_record(stage, "fixture-author")
        self.authoring_nodes(stage)
        if self.g("status", "--porcelain"):
            self.commit("Commit authoring node evidence")
        if ci:
            candidate = self.c.stage_candidate(stage)
            receipts = []
            for cid in self.c.stage_check_ids(stage):
                check_def = next(c for c in self.c.spec()["checks"] if c["id"] == cid)
                receipt = execute_check(self.root, check_def, phase=None, task_id=None, expectation="pass",
                    spec_digest=candidate["spec_digest"], plan_digest=candidate["plan_digest"], origin="ci",
                    actor="explicit-fixture-ci-boundary", run_url="https://github.com/fixture/repo/actions/runs/1")
                path = self.root / ".rdd/runtime/ci-receipt.json"
                write_json(path, receipt)
                self.c.check_import(path)
                receipts.append(receipt)
            write_json(self.root / f".rdd/evidence/preparation-ci/{platform_name()}.json", dict(
                scope="preparation", status="passed", application_complete=False, source_commit=candidate["source_commit"],
                source_digest=candidate["source_digest"], platform=platform_name(), harness_source=head(self.root),
                run_url="https://github.com/fixture/repo/actions/runs/1", checks=receipts))
        readiness = self.c.readiness(stage)
        if stage == "specification" and self.c._node_records(self.c.state())["S7"]["status"] != "complete":
            self.node_complete("S7", readiness["evidence"])
        cursor = self.live_review()["review_cursor"]
        for perspective in ("semantic", "execution"):
            spec = self.c.spec()
            record = dict(schema_version=2, kind="final", review_cursor=cursor, stage=stage, perspective=perspective,
                candidate=self.c.stage_candidate(stage), reviewer="rdd_reviewer",
                model=self.c.profile_settings("rdd_reviewer")["model"], session_id="fixture-"+perspective,
                decision="pass", summary="Explicit independent fixture review for controller transition testing.",
                evidence_ids=readiness["evidence"], findings=[], coverage=dict(
                    requirements=[r["requirement"] for r in spec["requirement_map"]],
                    elements=[e["id"] for e in spec["solution_elements"]], scenarios=[s["id"] for s in spec["scenarios"]],
                    checks=[c["id"] for c in spec["checks"]],
                    tasks=[] if stage == "specification" else [t["id"] for t in self.c.plan()["tasks"]]))
            path = self.root / ".rdd/runtime/stage-review.json"
            write_json(path, record)
            self.c.review_record(path)
        return readiness

    def prepared(self):
        self.stage_ready("specification")
        result = self.c.spec_freeze()
        self.plan["spec_digest"] = result["spec_digest"]
        self.commit("Freeze fixture specification")
        self.c.plan_init()
        write_json(self.root / ".rdd/plan/plan.json", self.plan)
        self.stage_ready("plan")
        self.c.plan_freeze()
        self.c.prepare()
        self.commit("Commit fixture preparation")
        self.stage_ready("preparation", ci=True)
        self.c.gate_preparation()

    def opened(self):
        self.prepared()
        self.c.phase_begin("P01")
        self.live_review()

    def submit(self, tid, changes):
        claim = self.c.task_claim(tid, "rdd_complex_implementor", worktree=True, session_id=f"worker-{tid}")
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
        self.live_review()
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
        cursor = self.live_review()["review_cursor"]
        record = dict(schema_version=1, kind="final", review_cursor=cursor, phase="P01", source_commit=head(self.root),
            source_digest=source_digest(self.root), model=self.c.profile_settings("rdd_reviewer")["model"],
            reviewer="rdd_reviewer", session_id="independent-reviewer-fixture", decision="pass",
            summary="An independent fixture review covers the exact current phase behavior and evidence.",
            checks_reviewed=["behavior", "contract", "boundary"], findings=[])
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

    def test_large_scope_requires_complex_profile_before_a_lease_is_created(self):
        self.plan["tasks"][0]["scope"] = "large"
        self.opened()
        for role in ("rdd_light_implementor", "rdd_large", "rdd_small", "rdd_task_planner"):
            before = self.c.state()
            with self.subTest(role=role), self.assertRaises(RddError):
                self.c.task_claim("T001", role, worktree=False, session_id="misrouted-worker")
            self.assertEqual(self.c.state(), before)
        result = self.c.task_claim("T001", "rdd_complex_implementor", worktree=False, session_id="complex-worker")
        self.assertEqual(result["requested_runtime"], self.c.profile_settings("rdd_complex_implementor"))

    def test_small_scope_accepts_light_profile_and_retains_requested_identity(self):
        self.opened()
        result = self.c.task_claim("T001", "rdd_light_implementor", worktree=False, session_id="light-worker")
        self.assertEqual(result["requested_runtime"], self.c.profile_settings("rdd_light_implementor"))
        self.assertEqual(self.c.state()["tasks"]["T001"]["requested_runtime"], result["requested_runtime"])

    def test_two_phases_are_sequential_and_second_pr_targets_first_branch(self):
        foundation = check("foundation", red="AssertionError: EXPECTED_ASSERTION")
        foundation["argv"] = ["{python}", "-B", "tests/foundation.py"]
        foundation["requires"] = ["foundation-runner"]
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
        second.update(id="P02", tasks=["T004", "T005", "T006"], checks=["behavior", "boundary"],
                      requirements_closed=["FR-001"], deliverables=["modules/extension.py", "docs/usage.md"],
                      goal="The fixture extension and complete observable behavior are available.")
        self.plan["phases"] = [first, second]
        self.plan["verticals"][0]["tasks"] = [t["id"] for t in tasks]
        self.plan["target_paths"] = [t["writes"][0] for t in tasks]
        self.plan["shells"] = [dict(path=p, content="<!-- Fixture shell -->\n" if p.endswith(".md") else "# Fixture shell\n") for p in
                               ("tests/foundation.py", "tests/behavior.py", "modules/extension.py", "docs/usage.md")]
        self.spec["target_tree"].append(dict(path="tests/foundation.py", kind="file", owner="E-SUPPORT", purpose="Foundation assertion.", disposition="add"))
        self.spec["resources"].append(dict(self.spec["resources"][1], id="foundation-runner", path="tests/foundation.py"))
        tasks[0]["produces"] = tasks[0]["bootstrap_resources"] = ["foundation-runner"]
        tasks[3]["produces"] = tasks[3]["bootstrap_resources"] = ["runner"]
        tasks[2]["produces"] = ["fixture-provider"]
        tasks[4]["produces"] = ["fixture-consumer"]
        self.plan["resource_producers"][1]["task"] = "T004"
        self.plan["resource_producers"][3]["task"] = "T005"
        self.plan["boundary_proofs"][0].update(first_phase="P02", consumer_tasks=["T005"], adapter_tasks=["T003", "T005"], verification_tasks=["T004"])
        self.plan["resource_producers"].append(dict(resource="foundation-runner", kind="task", task="T001", checks=[]))
        for coverage in self.plan["element_coverage"]:
            coverage["tasks"] = [t["id"] for t in tasks]
        self.plan["resource_uses"] = [dict(resource="foundation-runner" if t in tasks[:3] else "runner", consumer_kind="task_red" if t["category"] == "tests" else "task_completion", consumer=t["id"])
            for t in tasks if t["checks"]]
        self.plan["resource_uses"] += [dict(resource=r, consumer_kind="phase", consumer=phase)
            for phase, resources in (("P01", ["probe", "foundation-runner"]), ("P02", ["probe", "foundation-runner", "runner", "fixture-provider", "fixture-consumer"])) for r in resources]
        self.plan["resource_uses"] += [dict(resource=r, consumer_kind="project", consumer=None) for r in ("probe", "foundation-runner", "runner", "fixture-provider", "fixture-consumer")]
        write_json(self.root / ".rdd/spec.json", self.spec)
        self.prepared()
        with self.assertRaisesRegex(RddError, "sequentially"):
            self.c.phase_begin("P02")
        first_branch = self.c.phase_begin("P01")["branch"]
        self.live_review()
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
        self.live_review()
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
        self.review(phase="P02", checks_reviewed=["foundation", "behavior", "contract", "boundary"])
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
            self.c.task_claim("T003", "rdd_complex_implementor", worktree=True, session_id="early-worker")
        with self.assertRaisesRegex(RddError, "integrated task"):
            self.c.task_complete("T001")

    def test_category_handoff_requires_live_observation_without_task_approval(self):
        self.opened()
        red = self.red_task()
        self.c.task_complete("T001", red["id"])
        self.commit("Preserve accepted RED and controller cleanup")
        with self.assertRaisesRegex(RddError, "observe completed tests integration"):
            self.c.task_claim("T002", "rdd_complex_implementor", session_id="deletion-worker")
        self.live_review()  # An observation carries no approval/pass field.
        self.assertEqual(self.c.task_claim("T002", "rdd_complex_implementor", session_id="deletion-worker")["task"], "T002")

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
        self.c.task_claim("T001", "rdd_complex_implementor", worktree=True, session_id="same-session")
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
