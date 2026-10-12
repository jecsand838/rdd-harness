"""Stateless CI tests against isolated candidate and trusted-policy repositories."""
from __future__ import annotations

import os
import json
import copy
from pathlib import Path
import shutil
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from tools.rdd import artifacts, ci
from tools.rdd.adapters import run_argv
from tools.rdd.checks import platform_name
from tools.rdd.common import RddError, digest, file_hash, head, read_json, write_json


class VerifierSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.base = self.home / "baseline"
        self.candidate = self.home / "candidate"
        self.base.mkdir()
        self.output = self.home / "github-output"
        self.required = (".rdd/config.json", "tools/rdd/cli.py")
        for path in self.required:
            self.write(self.candidate, path)
        workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/rdd.yml").read_text(encoding="utf-8")
        self.selector = textwrap.dedent(workflow.split("python - <<'RDD_SELECT_VERIFIER'\n", 1)[1]
                                       .split("\n          RDD_SELECT_VERIFIER", 1)[0])

    def write(self, root, relative):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")

    def select(self, branch="codex/initialize-rdd-harness", **environment):
        self.output.unlink(missing_ok=True)
        return run_argv([sys.executable, "-c", self.selector], self.home,
                        env={"GITHUB_OUTPUT": str(self.output), "RDD_HEAD_BRANCH": branch, **environment})

    def outputs(self):
        return dict(line.split("=", 1) for line in self.output.read_text(encoding="utf-8").splitlines())

    def test_empty_base_uses_candidate_for_initial_import(self):
        result = self.select()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.outputs()["root"], "candidate")
        self.assertEqual(self.outputs()["policy_root"], "candidate")

    def test_complete_base_is_selected_despite_candidate_policy_changes(self):
        for path in self.required:
            self.write(self.base, path)
        (self.candidate / ".rdd/config.json").write_text("changed candidate policy\n", encoding="utf-8")
        self.write(self.candidate, ".rdd/spec.lock.json")
        result = self.select("rdd/example/p01")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.outputs()["root"], "baseline")
        self.assertEqual(self.outputs()["policy_root"], "baseline")

    def test_partial_base_cannot_bootstrap(self):
        for path in (*self.required, ".rdd/leftover", "tools/rdd/leftover"):
            with self.subTest(path=path):
                shutil.rmtree(self.base)
                self.base.mkdir()
                self.write(self.base, path)
                result = self.select()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("partial harness", result.stderr)
                self.assertFalse(self.output.exists())

    def test_each_candidate_freeze_prevents_bootstrap(self):
        for path in (".rdd/spec.lock.json", ".rdd/plan/plan.lock.json", ".rdd/prepared.json"):
            with self.subTest(path=path):
                self.write(self.candidate, path)
                result = self.select()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("cannot contain frozen", result.stderr)
                self.assertFalse(self.output.exists())
                (self.candidate / path).unlink()

    def test_phase_branch_cannot_bootstrap(self):
        for branch in ("rdd/example/p01", "rdd/malformed"):
            with self.subTest(branch=branch):
                result = self.select(branch)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("RDD phase branch", result.stderr)
                self.assertFalse(self.output.exists())

    def test_incomplete_candidate_cannot_bootstrap(self):
        for path in self.required:
            with self.subTest(path=path):
                (self.candidate / path).unlink()
                result = self.select()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("complete candidate harness", result.stderr)
                self.assertFalse(self.output.exists())
                self.write(self.candidate, path)

    def release_environment(self):
        return {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REPOSITORY": "example/repo",
                "RDD_HEAD_REPOSITORY": "example/repo", "RDD_BASE_REPOSITORY": "example/repo",
                "RDD_BASE_BRANCH": "main", "RDD_HEAD_SHA": "b" * 40,
                "RDD_POLICY_SHA": "c" * 40,
                "RDD_RELEASE_POLICY_SHA": "a" * 40, "RDD_RELEASE_SOURCE_SHA": "b" * 40}

    def test_release_selects_base_code_and_pinned_policy_with_or_without_main_freezes(self):
        for path in self.required:
            self.write(self.base, path)
        for frozen_main in (False, True):
            with self.subTest(frozen_main=frozen_main):
                if frozen_main:
                    for path in (".rdd/spec.lock.json", ".rdd/plan/plan.lock.json", ".rdd/prepared.json"):
                        self.write(self.base, path)
                result = self.select("codex/rdd-release/example", **self.release_environment())
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = {"root": "baseline", "policy_root": "prepared-policy",
                    "policy_sha": "a" * 40, "release_policy": "a" * 40,
                    "release_source": "b" * 40, "prepared": "true"}
                self.assertEqual({key: self.outputs()[key] for key in expected}, expected)
                self.assertEqual(self.outputs()["controller"], "true")
                self.assertEqual(self.outputs()["full"], "true")
                self.assertEqual(json.loads(self.outputs()["full_matrix"]),
                                 {"os": ["ubuntu-24.04", "macos-latest", "windows-latest"]})

    def test_release_event_target_fork_and_pin_errors_cannot_fallback(self):
        for path in self.required:
            self.write(self.base, path)
        variants = {"push": {"GITHUB_EVENT_NAME": "push"},
                    "wrong target": {"RDD_BASE_BRANCH": "codex/example-baseline"},
                    "fork": {"RDD_HEAD_REPOSITORY": "fork/repo"},
                    "wrong base repository": {"RDD_BASE_REPOSITORY": "other/repo"},
                    "missing policy": {"RDD_RELEASE_POLICY_SHA": ""},
                    "missing source": {"RDD_RELEASE_SOURCE_SHA": ""},
                    "short policy": {"RDD_RELEASE_POLICY_SHA": "a" * 12},
                    "uppercase source": {"RDD_RELEASE_SOURCE_SHA": "B" * 40},
                    "stale source": {"RDD_RELEASE_SOURCE_SHA": "c" * 40}}
        for kind, replacement in variants.items():
            with self.subTest(kind=kind):
                result = self.select("codex/rdd-release/example", **(self.release_environment() | replacement))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.output.exists())
        result = self.select("codex/rdd-release/example/extra", **self.release_environment())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not canonical", result.stderr)

    def test_release_cannot_bootstrap_its_verifier(self):
        result = self.select("codex/rdd-release/example", **self.release_environment())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bootstrap is forbidden", result.stderr)

    def test_nonrelease_events_ignore_even_invalid_repository_release_pins(self):
        for path in self.required:
            self.write(self.base, path)
        for event, branch, target, source_repo in (
            ("push", "main", "", ""),
            ("push", "codex/example-baseline", "", ""),
            ("pull_request", "rdd/example/p01", "codex/example-baseline", "example/repo"),
            ("pull_request", "feature/example", "main", "fork/repo"),
        ):
            with self.subTest(event=event, branch=branch):
                environment = self.release_environment() | {"GITHUB_EVENT_NAME": event,
                    "RDD_BASE_BRANCH": target, "RDD_HEAD_REPOSITORY": source_repo,
                    "RDD_RELEASE_POLICY_SHA": "malformed", "RDD_RELEASE_SOURCE_SHA": "stale"}
                result = self.select(branch, **environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.outputs()["root"], "baseline")
                self.assertEqual(self.outputs()["policy_root"], "baseline")
                self.assertEqual(self.outputs()["release_policy"], "")
                self.assertEqual(self.outputs()["release_source"], "")
                self.assertEqual(self.outputs()["policy_sha"], environment["RDD_POLICY_SHA"])


@unittest.skipUnless(shutil.which("git"), "Git is required for isolated CI candidate tests")
class CiTests(unittest.TestCase):
    def setUp(self):
        actions = patch.dict(os.environ, {"GITHUB_ACTIONS": "false"})
        actions.start()
        self.addCleanup(actions.stop)
        # These controller fixtures execute arithmetic checks, with the external
        # compiler boundary supplied explicitly. The disposable real generator
        # suite exercises the canonical driver and receipt parser together.
        canonical = patch("tools.rdd.readiness.canonical_contract_check",
                          side_effect=lambda spec: next(check for check in spec["checks"]
                                                        if check["id"] == "C-CONTRACT"))
        receipts = patch("tools.rdd.readiness.verify_canonical_contract_receipts", return_value=None)
        canonical.start()
        receipts.start()
        self.addCleanup(canonical.stop)
        self.addCleanup(receipts.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.base = self.home / "baseline"
        self.candidate = self.home / "candidate"
        self.base.mkdir()
        self.repo_source = Path(__file__).resolve().parents[2]
        self.commands = []
        self.config = {"schema_version": 1, "requirements": "requirements/requirements.md",
                       "limits": {"max_spec_words": 20000, "max_tasks": 500, "max_phases": 40},
                       "protected_prefixes": ["requirements/", "docs/specs/", "contracts/", "gen/", ".rdd/",
                                              ".agents/", ".codex/", ".github/", "tools/rdd/"],
                       "protected_files": ["AGENTS.md", "rdd"]}
        self.write(self.base, ".gitignore", ".rdd/runtime/\n.rdd/evidence/\n.rdd/run.json\n__pycache__/\n")
        self.write(self.base, "AGENTS.md", "Requirements govern the implementation.\n")
        self.write(self.base, "tools/rdd/policy.py", "# Fixture policy revision\n")
        write_json(self.base / ".rdd/config.json", self.config)
        for name in ("spec", "plan", "evidence"):
            destination = self.base / f".rdd/schemas/{name}.schema.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.repo_source / f".rdd/schemas/{name}.schema.json", destination)
        self.init_git(self.base)
        self.commit(self.base, "bootstrap")

    def write(self, root, relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def command(self, root, *args):
        result = run_argv(["git", *args], root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def init_git(self, root):
        self.command(root, "init", "-b", "main")
        self.command(root, "config", "core.autocrlf", "false")
        self.command(root, "config", "user.name", "RDD Test")
        self.command(root, "config", "user.email", "rdd-test@example.invalid")

    def commit(self, root, message):
        self.command(root, "add", ".")
        self.command(root, "commit", "-m", message)

    def clone(self):
        # Preserve the exact bytes recorded by the fixture's frozen artifacts.
        result = run_argv(["git", "clone", "-c", "core.autocrlf=false", "--no-hardlinks",
                           str(self.base), str(self.candidate)], self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.command(self.candidate, "config", "user.name", "RDD Test")
        self.command(self.candidate, "config", "user.email", "rdd-test@example.invalid")

    def check(self, name, kind="test", platforms=None, host_profile=None):
        scenario = {"C-FIRST": "S-FIRST", "C-SECOND": "S-SECOND"}.get(name)
        return {"id": name, "kind": kind, "argv": ["{python}", "tools/ci_fixture_check.py", name],
                "cwd": ".", "timeout_seconds": 20, "platforms": platforms or ["any"],
                "red_pattern": "EXPECTED_BEHAVIORAL_FAILURE", "metrics": [], "host_profile": host_profile,
                "environments": ["local"], "requires": ["fixture-runner"], "scenario_ids": [scenario] if scenario else [],
                "results_path": f".rdd/evidence/results/{name}.json" if scenario else None}

    def prepare(self, *, extras=None, project_checks=None, ordinary_platforms=None, sidecar=False, extra_first_phase_task=False,
                readiness_probes=None):
        self.write(self.base, "requirements/requirements.md",
                   "# Requirements\n\n**FR-001 First behavior**\nThe app shall do the first thing.\nAcceptance: Verify first behavior.\n\n"
                   "**FR-002 Second behavior**\nThe app shall do the second thing.\nAcceptance: Verify second behavior.\n")
        self.write(self.base, "docs/specs/application.md", "# Application\n\nFirst and second observable behavior and their contracts.\n")
        self.write(self.base, "contracts/example.proto", 'syntax = "proto3";\npackage example.v1;\nmessage Example {}\n'
            'message Reply { oneof outcome { bool accepted = 1; string error = 2; } }\n'
            'service ExampleService { rpc First(Example) returns (Reply); rpc Second(Example) returns (Reply); }\n')
        self.write(self.base, "gen/example.rs", "pub struct Example;\n")
        self.write(self.base, "tools/ci_fixture_check.py", "import json,sys\nfrom pathlib import Path\n"
                   "cid = sys.argv[1]\nassert 2 + 2 == 4, 'EXPECTED_BEHAVIORAL_FAILURE'\n"
                   "if cid == 'C-FIRST':\n    assert 4 - 2 == 2, 'EXPECTED_BEHAVIORAL_FAILURE'\n    sid = 'S-FIRST'\n"
                   "elif cid == 'C-SECOND':\n    assert 6 - 3 == 3, 'EXPECTED_BEHAVIORAL_FAILURE'\n    sid = 'S-SECOND'\n"
                   "else:\n    sid = None\n"
                   "if sid:\n    path = Path('.rdd/evidence/results') / (cid + '.json')\n"
                   "    path.parent.mkdir(parents=True,exist_ok=True)\n"
                   "    path.write_text(json.dumps({'scenarios':[{'id':sid,'outcome':'pass'}]}),encoding='utf-8')\n"
                   "print('checked')\n")
        requirement_digest = file_hash(self.base / "requirements/requirements.md")
        checks = [self.check("C-CONTRACT", "contract", ordinary_platforms),
                  self.check("C-FIRST", platforms=ordinary_platforms),
                  self.check("C-SECOND", platforms=ordinary_platforms)]
        checks += extras or []
        checks += project_checks or []
        checks += readiness_probes or []
        self.spec = {
            "schema_version": 2, "author_sessions": ["ci-fixture-author"], "id": "spec-fixture", "requirements_digest": requirement_digest,
            "mode": "regenerate", "parent_spec_digest": None,
            "change_summary": "This is a deliberately minimal, executable controller test fixture.",
            "documents": ["docs/specs/application.md"], "decisions": [],
            "contract_files": ["contracts/example.proto"], "generated_files": ["gen/example.rs", "gen/metadata.json"],
            "contract_index_path": "gen/metadata.json", "shared_generated_files": [dict(path="gen/metadata.json",
                purpose="Descriptor index support for the isolated CI verifier fixture.")],
            "contract_check_ids": ["C-CONTRACT"],
            "project_check_ids": ["C-FIRST", "C-SECOND"] + [item["id"] for item in project_checks or []],
            "modules": [{"id": "example", "requirements": ["FR-001", "FR-002"],
                "contract_paths": ["contracts/example.proto"], "owns_paths": ["modules/"], "depends_on": [],
                "provided_services": ["example.v1.ExampleService"], "consumed_operations": [],
                "generated_paths": ["gen/example.rs"], "adapter_error_specs": ["docs/specs/application.md"],
                "qualification_checks": {g:["C-CONTRACT"] for g in ("provider","consumer","negative_signature","dependency_direction","compatibility")},
                "implementation_checks": {g:["C-FIRST","C-SECOND"] for g in ("provider","consumer","dependency_direction","compatibility","semantics")}}],
            "scenarios": [{"id": "S-FIRST", "requirements": ["FR-001"], "kind": "golden",
                           "solution_elements": ["E-DOMAIN", "E-FIRST", "E-TEST"],
                           "preconditions": "An isolated arithmetic fixture.", "fixture": "The value four.",
                           "stimulus": "Subtract two from four.", "verification_method": "Compare to the independently expected value two.",
                           "description": "First behavior", "expected": "First expected output", "check_ids": ["C-FIRST"]},
                          {"id": "S-SECOND", "requirements": ["FR-002"], "kind": "golden",
                           "solution_elements": ["E-DOMAIN", "E-SECOND", "E-TEST"],
                           "preconditions": "An isolated arithmetic fixture.", "fixture": "The value six.",
                           "stimulus": "Subtract three from six.", "verification_method": "Compare to the independently expected value three.",
                           "description": "Second behavior", "expected": "Second expected output", "check_ids": ["C-SECOND"]}],
            "checks": checks,
            "requirement_map": [{"requirement": "FR-001", "specifications": ["docs/specs/application.md"], "scenarios": ["S-FIRST"]},
                                {"requirement": "FR-002", "specifications": ["docs/specs/application.md"], "scenarios": ["S-SECOND"]}],
            "amendment": {"requirements": [], "paths": [], "rationale": ""},
            "solution_elements": [dict(id=eid,kind=kind,behavior="positive" if kind == "operation" else "support",
                requirements=reqs,scenarios=scenarios,specifications=["docs/specs/application.md"],module=module)
                for eid,kind,reqs,scenarios,module in (
                    ("E-DOMAIN","subdomain",["FR-001","FR-002"],["S-FIRST","S-SECOND"],"example"),
                    ("E-FIRST","operation",["FR-001"],["S-FIRST"],"example"),
                    ("E-SECOND","operation",["FR-002"],["S-SECOND"],"example"),
                    ("E-TEST","enabling",["FR-001","FR-002"],["S-FIRST","S-SECOND"],None))],
            "target_tree": [], "resources": [], "environments": [],
        }
        for element, method in ((self.spec["solution_elements"][1], "First"), (self.spec["solution_elements"][2], "Second")):
            element["contract_operations"] = ["example.v1.ExampleService." + method]
        self.write(self.base,"gen/metadata.json", json.dumps(dict(contract_index=dict(schema_version=1,
            source_hashes={"contracts/example.proto":file_hash(self.base / "contracts/example.proto")},
            binding_files=["gen/example.rs"],support_files=["gen/metadata.json"],
            binding_sources={"gen/example.rs":["contracts/example.proto"]},
            services=[dict(symbol="example.v1.ExampleService",source="contracts/example.proto",generated_path="gen/example.rs",
                operations=[dict(symbol="example.v1.ExampleService."+name,response_oneofs=[dict(name="outcome",fields=["accepted","error"])])
                            for name in ("First","Second")])]))))
        environments = {}
        for check in checks:
            check["environments"] = []
            for platform in ([platform_name()] if "any" in check["platforms"] else check["platforms"]):
                eid = f"env-{platform}-{check['host_profile'] or 'ordinary'}"
                environments[eid] = dict(id=eid,platform=platform,host_profile=check["host_profile"])
                check["environments"].append(eid)
        self.spec["environments"] = list(environments.values())
        self.spec["resources"] = [dict(id="fixture-runner",kind="repository",path="tools/ci_fixture_check.py",
            version=None,availability="baseline",required_at="specification",
            probe_check_ids=[check["id"] for check in readiness_probes or []],environments=list(environments))]
        for number,cid in ((1,"C-FIRST"),(2,"C-SECOND")):
            for role in ("provider","consumer"):
                path = f"modules/{role}{number}.py"
                self.write(self.base,path,f"# Explicit controller fixture {role} stub; no Todo behavior.\ndef boundary(value):\n    return None\n")
                rid = f"fixture-{role}{number}"
                self.spec["resources"].append(dict(id=rid,kind="repository",path=path,version=None,
                    availability="baseline",required_at="specification",probe_check_ids=[],environments=list(environments)))
                next(c for c in checks if c["id"] == cid)["requires"].append(rid)
        tasks = []
        for number in (1, 2):
            tasks.append({"id": f"T{number:03d}", "title": f"Implement behavior {number}", "phase": f"P{number:02d}",
                          "category": "tests", "requirements": [f"FR-{number:03d}"],
                          "specifications": ["docs/specs/application.md"],
                          "depends_on": [] if number == 1 else ["T001"],
                          "writes": [f"tests/acceptance/behavior{number}.py"],
                          "checks": ["C-FIRST" if number == 1 else "C-SECOND"],
                          "acceptance": ["Expected behavior is verified"], "scope": "small",
                          "objective": f"Assert independently specified fixture behavior {number}.",
                          "solution_elements": ["E-DOMAIN", "E-FIRST" if number == 1 else "E-SECOND", "E-TEST"],
                          "scenarios": ["S-FIRST" if number == 1 else "S-SECOND"],
                          "requires": ["fixture-runner"], "produces": [], "bootstrap_resources": [],
                          "sites": [dict(id="A01",path=f"tests/acceptance/behavior{number}.py",mode="inline",primary=True,
                              placement=dict(kind="append",context=None),instructions=f"Assert fixture behavior {number} here.")], "reuse": None})
        if sidecar:
            tasks[0]["sites"][0]["mode"] = "sidecar"
        if extra_first_phase_task:
            path = "tests/acceptance/behavior1_extra.py"
            tasks.append({**tasks[0], "id": "T003", "title": "Additional first behavior assertion",
                          "depends_on": ["T001"], "writes": [path],
                          "sites": [dict(id="A01",path=path,mode="inline",primary=True,
                              placement=dict(kind="append",context=None),instructions="Add the independently expected first behavior assertion.")]})
            tasks[1]["depends_on"] = ["T003"]
        for number in (1,2):
            verification = tasks[number-1]
            previous = "T003" if number == 1 and extra_first_phase_task else verification["id"]
            for index,role in enumerate(("provider","consumer")):
                path,tid = f"modules/{role}{number}.py", f"T{number*10+index:03d}"
                production = copy.deepcopy(verification)
                production.update(id=tid,title=f"Implement fixture {role} for operation {number}",
                    objective=f"Replace the explicit controller fixture {role} stub with its scoped adapter behavior.",
                    category="modification",depends_on=[previous],writes=[path])
                production["sites"][0].update(path=path,mode="inline",instructions=f"Implement the operation {number} {role} adapter here.")
                tasks.append(production)
                previous = tid
            if number == 1:
                tasks[1]["depends_on"] = [previous]
        first_phase_tasks = [task for task in tasks if task["phase"] == "P01"]
        second_phase_tasks = [task for task in tasks if task["phase"] == "P02"]
        self.spec["target_tree"] = [dict(path=task["writes"][0],kind="file",owner="E-DOMAIN" if task["category"] == "modification" else "E-TEST",
            purpose="An isolated executable fixture work site.",disposition="modify" if task["category"] == "modification" else "add") for task in tasks]
        self.spec["target_tree"] += [dict(path="modules/",kind="directory",owner="E-DOMAIN",
            purpose="The explicit fixture domain ownership boundary.",disposition="retain"),
            dict(path="tools/ci_fixture_check.py",kind="file",owner="E-TEST",
            purpose="The baseline assertion runner.",disposition="retain")]
        write_json(self.base / ".rdd/spec.json", self.spec)
        spec_files = {path: file_hash(self.base / path) for path in (
            ".rdd/spec.json", "requirements/requirements.md", "docs/specs/application.md", "contracts/example.proto", "gen/example.rs", "gen/metadata.json")}
        self.spec_lock = {"schema_version": 1, "files": spec_files,
                          "requirements_digest": requirement_digest}
        self.spec_lock["digest"] = digest(self.spec_lock)
        write_json(self.base / ".rdd/spec.lock.json", self.spec_lock)
        self.plan = {
            "schema_version": 2, "author_sessions": ["ci-fixture-author"], "spec_digest": self.spec_lock["digest"],
            "phases": [{"id": "P01", "goal": "First behavior", "tasks": [task["id"] for task in first_phase_tasks],
                        "checks": ["C-FIRST"] + [item["id"] for item in extras or []],
                        "requirements_closed": ["FR-001"], "deliverables": [task["writes"][0] for task in first_phase_tasks], "independent_evidence": ["First review"]},
                       {"id": "P02", "goal": "Second behavior", "tasks": [task["id"] for task in second_phase_tasks],
                        "checks": ["C-SECOND"] + [item["id"] for item in project_checks or []],
                        "requirements_closed": ["FR-002"], "deliverables": [task["writes"][0] for task in second_phase_tasks], "independent_evidence": ["Second review"]}],
            "tasks": tasks, "verticals": [{"id": "V01", "goal": "Both behaviors",
                                          "tasks": [task["id"] for task in first_phase_tasks + second_phase_tasks]}],
            "target_paths": [task["writes"][0] for task in tasks],
            "shells": [{"path": task["writes"][0], "content": "# Implementation shell\n"} for task in tasks if task["category"] == "tests"],
            "element_coverage": [dict(element=e["id"],tasks=[task["id"] for task in tasks if e["id"] in task["solution_elements"]],
                checks=sorted({cid for scenario in self.spec["scenarios"] if e["id"] in scenario["solution_elements"] for cid in scenario["check_ids"]}),
                baseline_evidence=None) for e in self.spec["solution_elements"]],
            "resource_producers": [dict(resource=r["id"],kind="baseline",task=None,checks=[]) for r in self.spec["resources"]],
            "resource_uses": [dict(resource=rid,consumer_kind="task_red" if task["category"] == "tests" else "task_completion",consumer=task["id"])
                for task in tasks for rid in next(c for c in checks if c["id"] == task["checks"][0])["requires"]]
                + [dict(resource=rid,consumer_kind="phase",consumer=f"P{number:02d}") for number in (1,2)
                   for rid in sorted({r for c in checks if c["id"] in {"C-CONTRACT","C-FIRST"} | ({"C-SECOND"} if number == 2 else set()) for r in c["requires"]})]
                + [dict(resource=r["id"],consumer_kind="project",consumer=None) for r in self.spec["resources"]],
            "boundary_proofs": [dict(module="example",operation="example.v1.ExampleService." + operation,first_phase=f"P{number:02d}",
                checks=[cid],provider_tasks=[f"T{number*10:03d}"],consumer_tasks=[f"T{number*10+1:03d}"],
                adapter_tasks=[f"T{number*10+1:03d}"],verification_tasks=[f"T{number:03d}"])
                for number,cid,operation in ((1,"C-FIRST","First"),(2,"C-SECOND","Second"))],
        }
        write_json(self.base / ".rdd/plan/plan.json", self.plan)
        matrix = self.write(self.base, ".rdd/plan/implementation-matrix.md", artifacts.implementation_matrix(self.plan))
        plan_files = {".rdd/plan/plan.json": file_hash(self.base / ".rdd/plan/plan.json")}
        self.plan_lock = {"schema_version": 1, "files": plan_files, "spec_digest": self.spec_lock["digest"]}
        self.plan_lock["digest"] = digest(self.plan_lock)
        write_json(self.base / ".rdd/plan/plan.lock.json", self.plan_lock)
        state = {"tasks": {task["id"]: {"status": "pending"} for task in tasks}}
        artifacts.materialize(self.base, self.plan, state)
        prepared = {"schema_version": 1, "run_id": "ci-fixture", "spec_digest": self.spec_lock["digest"],
                    "plan_digest": self.plan_lock["digest"],
                    "shell_hashes": {task["writes"][0]: file_hash(self.base / task["writes"][0]) for task in tasks},
                    "matrix_digest": file_hash(matrix)}
        prepared["digest"] = digest(prepared)
        write_json(self.base / ".rdd/prepared.json", prepared)
        # Check fixture semantics before exercising CI's post-implementation paths.
        reqs = artifacts.requirements(self.base, self.config["requirements"])
        artifacts.spec_validate(self.base, self.spec, reqs, self.config)
        artifacts.plan_validate(self.base, self.plan, self.spec, self.spec_lock, self.config)
        self.commit(self.base, "prepare fixture")

    def complete_phase(self, number):
        for task in self.plan["tasks"]:
            if int(task["phase"][1:]) <= number:
                artifacts.remove_anchor(self.candidate, task, self.plan)
        self.commit(self.candidate, f"complete phase {number}")

    def execute(self, root, check, **kwargs):
        """Observe actual frozen-check execution without substituting its result."""
        from tools.rdd.checks import execute_check
        self.commands.append(check["id"])
        return execute_check(root, check, **kwargs)

    def verify(self, branch):
        with patch("tools.rdd.ci._execute", side_effect=self.execute):
            return ci.verify(self.candidate, self.base, branch)

    def verify_release(self, **kwargs):
        values = {"branch": "codex/rdd-release/ci-fixture", "release_policy": head(self.base),
                  "release_source": head(self.candidate), "policy_root": self.base}
        values.update(kwargs)
        with patch("tools.rdd.ci._execute", side_effect=self.execute):
            return ci.verify(self.candidate, **values)

    def prepare_ci_candidate(self, **kwargs):
        """Pin a separate harness checkout before product fixture materialization."""
        self.harness_source = head(self.base)
        self.harness = self.home / "harness"
        result = run_argv(["git", "clone", "-c", "core.autocrlf=false", "--no-hardlinks",
                           str(self.base), str(self.harness)], self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.command(self.harness, "checkout", "--detach", self.harness_source)
        self.prepare(**kwargs)
        self.clone()
        self.assertEqual(self.command(self.candidate, "merge-base", self.harness_source, "HEAD"), self.harness_source)

    def verify_preparation(self, **kwargs):
        values = {"policy_root": self.harness, "harness_source": self.harness_source}
        values.update(kwargs)
        with patch("tools.rdd.ci._execute", side_effect=self.execute):
            return ci.verify_preparation(self.candidate, **values)

    def test_preparation_ci_runs_exact_declared_probes_and_persists_each_platform_report(self):
        platforms = ["linux", "macos", "windows"]
        probes = [self.check("C-READY-ALL", "readiness", platforms)]
        probes += [self.check("C-READY-" + platform.upper(), "readiness", [platform]) for platform in platforms]
        self.prepare_ci_candidate(ordinary_platforms=platforms, readiness_probes=probes)
        # Simulate selection/provenance only; the fixture commands really run on
        # this host. Hosted qualification supplies actual platform observations.
        for platform in platforms:
            with self.subTest(platform=platform), patch("tools.rdd.ci._host_platform", return_value=platform), \
                    patch("tools.rdd.checks.platform_name", return_value=platform):
                self.commands.clear()
                report = self.verify_preparation()
                expected = ["C-CONTRACT", "C-READY-ALL", "C-READY-" + platform.upper()]
                self.assertEqual(self.commands, expected)
                self.assertEqual([row["check_id"] for row in report["checks"]], expected)
                self.assertEqual({row["platform"] for row in report["checks"]}, {platform})
                self.assertEqual(report["status"], "passed")
                self.assertEqual(report["scope"], "preparation")
                self.assertEqual(report["source_commit"], head(self.candidate))
                self.assertEqual(report["harness_source"], self.harness_source)
                self.assertFalse(report["application_complete"])
                self.assertEqual(report["anchors"]["remaining"], len(self.plan["tasks"]))
                self.assertEqual(read_json(self.candidate / f".rdd/evidence/preparation-ci/{platform}.json"), report)
                self.assertEqual(read_json(self.candidate / ".rdd/evidence/preparation-ci.json"), report)

    def test_preparation_ci_rejects_pinned_harness_policy_mutation_before_checks(self):
        self.prepare_ci_candidate()
        self.write(self.candidate, "tools/rdd/policy.py", "# Mutated trusted harness policy\n")
        self.commit(self.candidate, "mutate preparation policy")
        with self.assertRaisesRegex(RddError, "independently pinned harness"):
            self.verify_preparation()
        self.assertEqual(self.commands, [])

    def test_preparation_ci_rejects_ignored_policy_addition_before_checks(self):
        self.write(self.base, ".gitignore", (self.base / ".gitignore").read_text(encoding="utf-8") + ".codex/injected.toml\n")
        self.commit(self.base, "ignore fixture injection path before pin")
        self.prepare_ci_candidate()
        self.write(self.candidate, ".codex/injected.toml", 'model="unexpected"\n')
        self.assertEqual(self.command(self.candidate, "status", "--porcelain"), "")
        with self.assertRaisesRegex(RddError, "independently pinned harness"):
            self.verify_preparation()
        self.assertEqual(self.commands, [])

    def test_preparation_ci_rejects_pin_checkout_and_candidate_ancestry_mismatches(self):
        self.prepare_ci_candidate()
        for override in ({"harness_source": head(self.candidate)}, {"policy_root": self.candidate}):
            with self.subTest(override=override), self.assertRaisesRegex(RddError, "separate checkout.*exact trusted harness pin"):
                self.verify_preparation(**override)
        # Create a clean, valid repository with different ancestry and retain the
        # trusted pin's object so merge-base executes without a missing-object error.
        self.command(self.candidate, "checkout", "--orphan", "unrelated-baseline")
        self.commit(self.candidate, "independent root candidate")
        with self.assertRaisesRegex(RddError, "descend from the trusted harness pin"):
            self.verify_preparation()
        self.assertEqual(self.commands, [])

    def test_preparation_ci_persists_failed_readiness_proof_for_its_platform(self):
        probe = self.check("C-READY-FAIL", "readiness")
        probe["argv"] = ["{python}", "-c", "raise SystemExit('PREPARATION_READINESS_FAILURE')"]
        self.prepare_ci_candidate(readiness_probes=[probe])
        with self.assertRaisesRegex(RddError, "Preparation qualification failed: C-READY-FAIL"):
            self.verify_preparation()
        report = read_json(self.candidate / f".rdd/evidence/preparation-ci/{platform_name()}.json")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.commands, ["C-CONTRACT", "C-READY-FAIL"])
        self.assertEqual(report["checks"][-1]["outcome"], "fail")
        raw = read_json(self.candidate / report["checks"][-1]["log_path"])
        self.assertIn("PREPARATION_READINESS_FAILURE", raw["stderr"])
        self.assertEqual(read_json(self.candidate / ".rdd/evidence/preparation-ci.json"), report)

    def test_bootstrap_is_explicitly_harness_only(self):
        self.clone()
        report = self.verify("main")
        self.assertEqual(report["status"], "harness_only")
        self.assertEqual(report["scope"], "bootstrap")
        self.assertFalse(report["application_complete"])
        self.assertEqual(self.commands, [])
        self.assertEqual(read_json(self.candidate / ".rdd/evidence/ci.json")["status"], "harness_only")

    def test_protected_change_fails_before_any_command(self):
        self.prepare()
        self.clone()
        self.complete_phase(1)
        self.write(self.candidate, "tools/rdd/policy.py", "# weaken the verifier\n")
        with self.assertRaisesRegex(RddError, "trusted policy"):
            self.verify("rdd/ci-fixture/p01")
        self.assertEqual(self.commands, [])
        self.assertEqual(read_json(self.candidate / ".rdd/evidence/ci.json")["status"], "failed")

    def test_untracked_protected_addition_cannot_hide_in_gitignore(self):
        self.clone()
        self.write(self.candidate, ".gitignore", ".codex/\n.rdd/evidence/\n")
        self.write(self.candidate, ".codex/injected.toml", 'model="unexpected"\n')
        with self.assertRaisesRegex(RddError, "trusted policy"):
            self.verify("main")
        self.assertEqual(self.commands, [])

    def test_candidate_cannot_remove_a_frozen_plan(self):
        self.prepare()
        self.clone()
        (self.candidate / ".rdd/plan/plan.lock.json").unlink()
        with self.assertRaises(RddError):
            self.verify("rdd/ci-fixture/p01")
        self.assertEqual(self.commands, [])

    def test_candidate_cannot_introduce_its_own_trusted_policy(self):
        self.clone()
        write_json(self.candidate / ".rdd/plan/plan.lock.json", {"digest": "0" * 64})
        with self.assertRaises(RddError):
            self.verify("main")
        self.assertEqual(self.commands, [])

    def test_inconsistent_freeze_digest_in_both_checkouts_is_rejected(self):
        self.prepare()
        self.spec_lock["digest"] = "0" * 64
        write_json(self.base / ".rdd/spec.lock.json", self.spec_lock)
        self.commit(self.base, "malformed trusted lock")
        self.clone()
        with self.assertRaisesRegex(RddError, "lock digest is inconsistent"):
            self.verify("main")
        self.assertEqual(self.commands, [])

    def test_matrix_corruption_in_trusted_preparation_is_rejected(self):
        self.prepare()
        self.write(self.base, ".rdd/plan/implementation-matrix.md", "# Incorrect matrix\n")
        self.commit(self.base, "malformed trusted preparation")
        self.clone()
        with self.assertRaisesRegex(RddError, "matrix changed after freeze"):
            self.verify("main")
        self.assertEqual(self.commands, [])

    def test_phase_checks_are_cumulative_and_reference_the_exact_head(self):
        self.prepare()
        self.clone()
        self.complete_phase(2)
        report = self.verify("rdd/ci-fixture/p02")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(self.commands, ["C-CONTRACT", "C-FIRST", "C-SECOND"])
        self.assertEqual(report["source_commit"], head(self.candidate))
        self.assertEqual(report["anchors"]["remaining"], 0)
        self.assertFalse(report["application_complete"])
        self.assertFalse(report["task_history_verified"])

    def test_prepared_main_checks_contracts_without_claiming_implementation(self):
        self.prepare()
        self.clone()
        report = self.verify("main")
        self.assertEqual(report["scope"], "prepared_baseline")
        self.assertEqual(report["status"], "harness_only")
        self.assertEqual(self.commands, ["C-CONTRACT"])
        self.assertEqual(report["anchors"]["remaining"], len(self.plan["tasks"]))
        self.assertIsNone(report["observed_through_phase"])
        self.assertFalse(report["application_complete"])
        self.assertFalse(report["task_history_verified"])

    def test_nonphase_prefixes_run_cumulative_checks_without_claiming_completion(self):
        self.prepare()
        self.clone()
        for number in (1, 2):
            self.complete_phase(number)
            expected_checks = ["C-CONTRACT", "C-FIRST"] + (["C-SECOND"] if number == 2 else [])
            for branch in ("main", "feature/example"):
                with self.subTest(phase=number, branch=branch):
                    self.commands.clear()
                    try:
                        report = self.verify(branch)
                    except RddError as exc:
                        self.fail(f"Whole-phase prefix rejected on {branch}: {exc}")
                    self.assertEqual(report["status"], "passed")
                    self.assertEqual(report["scope"], "source_cumulative")
                    self.assertEqual(report["observed_through_phase"], f"P{number:02d}")
                    self.assertEqual(report["branch"], branch)
                    self.assertIsNone(report["phase"])
                    self.assertEqual(report["scheduled_check_ids"], expected_checks)
                    self.assertEqual(self.commands, expected_checks)
                    self.assertEqual(report["source_commit"], head(self.candidate))
                    self.assertEqual(report["anchors"]["remaining"], sum(t["phase"] > f"P{number:02d}" for t in self.plan["tasks"]))
                    self.assertTrue(all(receipt["phase"] is None for receipt in report["checks"]))
                    self.assertFalse(report["application_complete"])
                    self.assertFalse(report["task_history_verified"])

    def test_nonphase_partial_phase_is_rejected_before_checks(self):
        self.prepare(extra_first_phase_task=True)
        self.clone()
        artifacts.remove_anchor(self.candidate, self.plan["tasks"][0], self.plan)
        self.commit(self.candidate, "remove only one of two first-phase markers")
        with self.assertRaisesRegex(RddError, "whole-phase prefix"):
            self.verify("main")
        self.assertEqual(self.commands, [])
        self.assertEqual(read_json(self.candidate / ".rdd/evidence/ci.json")["status"], "failed")

    def test_nonphase_gap_is_rejected_before_checks(self):
        self.prepare()
        self.clone()
        artifacts.remove_anchor(self.candidate, self.plan["tasks"][1], self.plan)
        self.commit(self.candidate, "remove later-phase marker while first remains")
        with self.assertRaisesRegex(RddError, "whole-phase prefix"):
            self.verify("main")
        self.assertEqual(self.commands, [])

    def test_nonphase_malformed_projections_are_rejected_before_checks(self):
        self.prepare()
        self.clone()
        first, second = self.plan["tasks"][:2]
        path = artifacts.anchor_path(first)
        original = (self.candidate / path).read_text(encoding="utf-8")
        variants = {
            "duplicate": artifacts.marker_line(first, plan=self.plan),
            "orphaned": '# RDD:P01:tests:V01:T999:A01 | {}',
            "misplaced": artifacts.marker_line(second, plan=self.plan),
        }
        for kind, marker in variants.items():
            with self.subTest(kind=kind):
                self.write(self.candidate, path, original + marker + "\n")
                self.commit(self.candidate, f"introduce {kind} marker")
                with self.assertRaisesRegex(RddError, "whole-phase prefix"):
                    self.verify("main")
                self.assertEqual(self.commands, [])

    def test_nonphase_candidate_cannot_reduce_coverage_below_integrated_base(self):
        self.prepare()
        first_phase = [t for t in self.plan["tasks"] if t["phase"] == "P01"]
        for task in first_phase:
            artifacts.remove_anchor(self.base, task, self.plan)
        self.commit(self.base, "integrate first-phase projection")
        self.clone()
        for task in first_phase:
            path = artifacts.anchor_path(task)
            text = (self.candidate / path).read_text(encoding="utf-8")
            self.write(self.candidate, path, text + artifacts.marker_line(task, plan=self.plan) + "\n")
        self.commit(self.candidate, "restore first-phase marker")
        with self.assertRaisesRegex(RddError, "reduces CI coverage below the trusted base"):
            self.verify("feature/rollback")
        self.assertEqual(self.commands, [])
        self.assertEqual(read_json(self.candidate / ".rdd/evidence/ci.json")["status"], "failed")

    def test_nonphase_candidate_can_preserve_or_advance_integrated_base_coverage(self):
        self.prepare()
        for task in self.plan["tasks"]:
            if task["phase"] == "P01":
                artifacts.remove_anchor(self.base, task, self.plan)
        self.commit(self.base, "integrate first-phase projection")
        self.clone()
        path = self.plan["tasks"][0]["writes"][0]
        self.write(self.candidate, path, "# Source change after first phase\n")
        self.commit(self.candidate, "change source without changing marker projection")
        self.assertNotEqual(head(self.candidate), head(self.base))
        for number in (1, 2):
            with self.subTest(phase=number):
                if number == 2:
                    self.complete_phase(number)
                self.commands.clear()
                report = self.verify("feature/advance")
                self.assertEqual(report["status"], "passed")
                self.assertEqual(report["observed_through_phase"], f"P{number:02d}")
                self.assertEqual(self.commands, ["C-CONTRACT", "C-FIRST"] + (["C-SECOND"] if number == 2 else []))

    def test_nonphase_same_sha_push_runs_all_cumulative_checks(self):
        self.prepare()
        for task in self.plan["tasks"]:
            artifacts.remove_anchor(self.base, task, self.plan)
        self.commit(self.base, "integrate all phase projections")
        self.clone()
        self.assertEqual(head(self.candidate), head(self.base))
        report = self.verify("main")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["scope"], "source_cumulative")
        self.assertEqual(report["observed_through_phase"], "P02")
        self.assertEqual(self.commands, ["C-CONTRACT", "C-FIRST", "C-SECOND"])
        self.assertIsNone(report["phase"])
        self.assertFalse(report["application_complete"])
        self.assertFalse(report["task_history_verified"])

    def test_completed_sidecar_is_mutable_projection_and_future_anchor_survives(self):
        self.prepare(sidecar=True)
        self.clone()
        self.complete_phase(1)
        for branch in ("rdd/ci-fixture/p01", "main"):
            with self.subTest(branch=branch):
                self.commands.clear()
                report = self.verify(branch)
                self.assertEqual(report["status"], "passed")
                self.assertEqual(report["anchors"]["remaining"], sum(t["phase"] == "P02" for t in self.plan["tasks"]))
                self.assertEqual(report["observed_through_phase"], "P01")
                self.assertEqual(self.commands, ["C-CONTRACT", "C-FIRST"])

    def test_actual_failing_command_persists_failure_instead_of_green(self):
        failing = self.check("C-FAIL")
        failing["argv"] = ["{python}", "-c", "raise SystemExit(7)"]
        self.prepare(extras=[failing])
        self.clone()
        self.complete_phase(1)
        for branch in ("rdd/ci-fixture/p01", "main"):
            with self.subTest(branch=branch):
                with self.assertRaisesRegex(RddError, "did not pass"):
                    self.verify(branch)
                receipt = read_json(self.candidate / ".rdd/evidence/ci.json")
                self.assertEqual(receipt["status"], "failed")
                self.assertEqual(receipt["checks"][-1]["returncode"], 7)

    def test_current_phase_marker_must_be_gone_and_future_marker_must_remain(self):
        self.prepare()
        self.clone()
        with self.assertRaisesRegex(RddError, "still has an anchor"):
            self.verify("rdd/ci-fixture/p01")
        self.complete_phase(2)
        with self.assertRaisesRegex(RddError, "requires exactly one anchor"):
            self.verify("rdd/ci-fixture/p01")
        self.assertEqual(self.commands, [])

    def test_wrong_run_unknown_phase_and_malformed_branch_are_rejected(self):
        self.prepare()
        self.clone()
        self.complete_phase(1)
        for branch in ("rdd/other/p01", "rdd/ci-fixture/p99", "rdd/ci-fixture/p001", "rdd/ci-fixture/no-phase"):
            with self.subTest(branch=branch), self.assertRaises(RddError):
                self.verify(branch)
        self.assertEqual(self.commands, [])

    def test_manual_and_reference_host_checks_remain_explicitly_pending_external(self):
        manual = self.check("C-MANUAL", "manual")
        manual["argv"] = []
        benchmark = self.check("C-REFERENCE", "benchmark", host_profile="qualified-desktop")
        benchmark["metrics"] = [{"name": "latency", "statistic": "p95", "limit": 200,
                                 "comparison": "lte", "minimum_samples": 100, "unit": "ms"}]
        self.prepare(extras=[manual, benchmark])
        self.clone()
        self.complete_phase(1)
        for branch in ("rdd/ci-fixture/p01", "main"):
            with self.subTest(branch=branch):
                self.commands.clear()
                report = self.verify(branch)
                self.assertEqual(report["status"], "passed")
                self.assertEqual(self.commands, ["C-CONTRACT", "C-FIRST"])
                self.assertEqual([row["check_id"] for row in report["pending_external"]], ["C-MANUAL", "C-REFERENCE"])
                self.assertFalse(report["application_complete"])
                self.assertFalse(report["task_history_verified"])

    def test_no_platform_relevant_ordinary_check_cannot_turn_green(self):
        other = "windows" if ci._host_platform() != "windows" else "linux"
        manual = self.check("C-MANUAL", "manual")
        manual["argv"] = []
        self.prepare(extras=[manual], ordinary_platforms=[other])
        self.clone()
        self.complete_phase(1)
        with self.assertRaisesRegex(RddError, "No ordinary"):
            self.verify("rdd/ci-fixture/p01")
        self.assertEqual(self.commands, [])

    def test_red_or_stale_receipt_cannot_pass_ci(self):
        self.prepare()
        self.clone()
        self.complete_phase(1)
        for mutation in ("red", "stale"):
            def bad(root, check, **kwargs):
                receipt = self.execute(root, check, **kwargs)
                if mutation == "red":
                    receipt["outcome"] = "red"
                else:
                    receipt["source_commit"] = "0" * 40
                return receipt
            with self.subTest(mutation=mutation), patch("tools.rdd.ci._execute", side_effect=bad), self.assertRaises(RddError):
                ci.verify(self.candidate, self.base, "rdd/ci-fixture/p01")

    def test_commands_that_mutate_source_invalidate_the_ci_result(self):
        self.prepare()
        self.clone()
        self.complete_phase(1)
        def mutation(root, check, **kwargs):
            receipt = self.execute(root, check, **kwargs)
            self.write(root, "tests/acceptance/behavior1.py", "# Changed by test\n")
            return receipt
        with patch("tools.rdd.ci._execute", side_effect=mutation), self.assertRaises(RddError):
            ci.verify(self.candidate, self.base, "rdd/ci-fixture/p01")

    def test_release_verifies_exact_completed_source_without_claiming_history(self):
        self.prepare(sidecar=True, project_checks=[self.check("C-PROJECT")])
        self.clone()
        self.complete_phase(2)
        report = self.verify_release()
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["scope"], "release_source")
        self.assertEqual(report["policy_source"], "pinned_prepared_baseline")
        self.assertEqual(report["release_policy"], head(self.base))
        self.assertEqual(report["release_source"], head(self.candidate))
        self.assertEqual(report["scheduled_check_ids"], ["C-CONTRACT", "C-FIRST", "C-SECOND", "C-PROJECT"])
        self.assertEqual(self.commands, report["scheduled_check_ids"])
        self.assertEqual(report["observed_through_phase"], "P02")
        self.assertEqual(report["anchors"]["remaining"], 0)
        self.assertIsNone(report["phase"])
        self.assertFalse(report["application_complete"])
        self.assertFalse(report["task_history_verified"])

    def test_release_does_not_read_candidate_run_locator_as_authority(self):
        self.prepare()
        self.clone()
        self.complete_phase(2)
        write_json(self.candidate / ".rdd/run.json", {"run_id": "other", "release_policy": "0" * 40,
                                                     "release_source": "0" * 40})
        report = self.verify_release()
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["run_id"], "ci-fixture")
        self.assertEqual(report["release_policy"], head(self.base))

    def test_release_partial_phase_cannot_run_checks(self):
        self.prepare(extra_first_phase_task=True)
        self.clone()
        artifacts.remove_anchor(self.candidate, self.plan["tasks"][0], self.plan)
        self.commit(self.candidate, "partial first release phase")
        with self.assertRaisesRegex(RddError, "whole-phase prefix"):
            self.verify_release()
        self.assertEqual(self.commands, [])

    def test_release_requires_paired_exact_pins_and_its_run_branch(self):
        self.prepare()
        self.clone()
        self.complete_phase(2)
        variants = [{"release_policy": None}, {"release_source": None},
                    {"release_policy": ""}, {"release_source": "b" * 12},
                    {"release_policy": "A" * 40}, {"release_policy": "0" * 40},
                    {"release_source": "0" * 40}, {"branch": "main"},
                    {"branch": "codex/rdd-release/other"},
                    {"branch": "codex/rdd-release/ci-fixture/extra"},
                    {"policy_root": self.candidate, "release_policy": head(self.candidate)}]
        for values in variants:
            with self.subTest(values=values), self.assertRaises(RddError):
                self.verify_release(**values)
            self.assertEqual(self.commands, [])
        with self.assertRaisesRegex(RddError, "explicit paired"):
            self.verify("codex/rdd-release/ci-fixture")

    def test_release_does_not_allow_bootstrap_or_partial_policy_freezes(self):
        self.clone()
        with self.assertRaisesRegex(RddError, "frozen prepared"):
            self.verify_release()
        self.assertEqual(self.commands, [])
        self.write(self.base, ".rdd/spec.lock.json", "{}\n")
        self.commit(self.base, "partial policy freeze")
        self.command(self.candidate, "pull", "--ff-only")
        with self.assertRaisesRegex(RddError, "freezes must exist"):
            self.verify_release()
        self.assertEqual(self.commands, [])

    def test_release_rejects_dirty_or_unrelated_policy_and_dirty_source(self):
        self.prepare()
        self.clone()
        self.complete_phase(2)
        for checkout in (self.base, self.candidate):
            with self.subTest(checkout=checkout):
                path = self.write(checkout, "uncommitted.txt", "uncommitted\n")
                with self.assertRaisesRegex(RddError, "working-tree changes"):
                    self.verify_release()
                path.unlink()
                self.assertEqual(self.commands, [])
        unrelated = self.home / "unrelated"
        self.command(self.home, "clone", "-c", "core.autocrlf=false", "--no-hardlinks", str(self.base), str(unrelated))
        self.command(unrelated, "config", "user.name", "RDD Test")
        self.command(unrelated, "config", "user.email", "rdd-test@example.invalid")
        self.command(unrelated, "checkout", "--orphan", "other-history")
        self.commit(unrelated, "unrelated policy root")
        with self.assertRaisesRegex(RddError, "ancestor"):
            self.verify_release(policy_root=unrelated, release_policy=head(unrelated))
        self.assertEqual(self.commands, [])

    def test_release_rejects_candidate_policy_changes_before_checks(self):
        self.prepare()
        self.clone()
        self.complete_phase(2)
        self.write(self.candidate, "tools/rdd/policy.py", "# Candidate policy rewrite\n")
        self.commit(self.candidate, "alter release policy")
        with self.assertRaisesRegex(RddError, "trusted policy"):
            self.verify_release()
        self.assertEqual(self.commands, [])

    def test_release_requires_full_completion_and_well_formed_anchors(self):
        self.prepare(extra_first_phase_task=True)
        self.clone()
        for boundary in (0, 1):
            with self.subTest(boundary=boundary):
                if boundary:
                    self.complete_phase(boundary)
                with self.assertRaisesRegex(RddError, "completed full phase prefix"):
                    self.verify_release()
                self.assertEqual(self.commands, [])
        artifacts.remove_anchor(self.candidate, self.plan["tasks"][1], self.plan)
        path = self.plan["tasks"][1]["writes"][0]
        self.write(self.candidate, path, "# RDD:P02:T999 [tests] Unknown task\n")
        self.commit(self.candidate, "orphaned release marker")
        with self.assertRaisesRegex(RddError, "whole-phase prefix"):
            self.verify_release()
        self.assertEqual(self.commands, [])

    def test_release_policy_must_be_the_prepared_baseline_not_completed_source(self):
        self.prepare()
        self.clone()
        self.complete_phase(2)
        completed_policy = self.home / "completed-policy"
        # Exercise the Windows checkout default without changing global user settings.
        checkout_config = self.write(self.home, "checkout.gitconfig", "[core]\n\tautocrlf = true\n")
        with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(checkout_config)}):
            self.command(self.home, "clone", "-c", "core.autocrlf=false", "--no-hardlinks",
                         str(self.candidate), str(completed_policy))
        with self.assertRaisesRegex(RddError, "requires exactly one anchor"):
            self.verify_release(policy_root=completed_policy, release_policy=head(completed_policy))
        self.assertEqual(self.commands, [])

    def test_release_policy_preparation_shells_must_match_their_receipt(self):
        self.prepare()
        path = self.plan["tasks"][0]["writes"][0]
        content = (self.base / path).read_text(encoding="utf-8")
        self.write(self.base, path, content + "# Changed after preparation\n")
        self.commit(self.base, "change prepared shell")
        self.clone()
        self.complete_phase(2)
        with self.assertRaisesRegex(RddError, "preparation shell changed"):
            self.verify_release()
        self.assertEqual(self.commands, [])

    def test_required_project_check_failure_blocks_release_and_ordinary_final_source(self):
        failing = self.check("C-PROJECT")
        failing["argv"] = ["{python}", "-c", "raise SystemExit(8)"]
        self.prepare(project_checks=[failing])
        self.clone()
        self.complete_phase(2)
        for mode in ("release", "ordinary"):
            with self.subTest(mode=mode):
                self.commands.clear()
                with self.assertRaisesRegex(RddError, "did not pass"):
                    self.verify_release() if mode == "release" else self.verify("main")
                report = read_json(self.candidate / ".rdd/evidence/ci.json")
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["checks"][-1]["check_id"], "C-PROJECT")
                self.assertEqual(report["checks"][-1]["returncode"], 8)
                self.assertEqual(self.commands, ["C-CONTRACT", "C-FIRST", "C-SECOND", "C-PROJECT"])

    def test_release_external_project_checks_remain_pending(self):
        manual = self.check("C-PROJECT-MANUAL", "manual")
        manual["argv"] = []
        self.prepare(project_checks=[manual])
        self.clone()
        self.complete_phase(2)
        report = self.verify_release()
        self.assertEqual(report["status"], "passed")
        self.assertEqual(self.commands, ["C-CONTRACT", "C-FIRST", "C-SECOND"])
        self.assertEqual([row["check_id"] for row in report["pending_external"]], [manual["id"]])
        self.assertFalse(report["application_complete"])

    def test_release_rechecks_policy_after_candidate_commands(self):
        self.prepare()
        self.clone()
        self.complete_phase(2)
        def mutate_policy(root, check, **kwargs):
            receipt = self.execute(root, check, **kwargs)
            self.write(self.base, "uncommitted.txt", "changed by test\n")
            return receipt
        with patch("tools.rdd.ci._execute", side_effect=mutate_policy), self.assertRaises(RddError):
            ci.verify(self.candidate, self.base, "codex/rdd-release/ci-fixture",
                      release_policy=head(self.base), release_source=head(self.candidate))

    def test_actions_release_verifier_checks_event_identity_independently(self):
        self.prepare()
        self.clone()
        self.complete_phase(2)
        event_path = self.home / "event.json"
        pr = {"head": {"ref": "codex/rdd-release/ci-fixture", "sha": head(self.candidate),
                       "repo": {"full_name": "example/repo"}},
              "base": {"ref": "main", "repo": {"full_name": "example/repo"}}}
        write_json(event_path, {"pull_request": pr})
        environment = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
                       "GITHUB_REPOSITORY": "example/repo", "GITHUB_EVENT_PATH": str(event_path)}
        with patch.dict(os.environ, environment):
            self.assertEqual(self.verify_release()["status"], "passed")
        self.commands.clear()
        for field, value in (("ref", "feature/other"), ("sha", "0" * 40),
                             ("repo", {"full_name": "fork/repo"}), ("repo", None)):
            with self.subTest(field=field, value=value):
                write_json(event_path, {"pull_request": {**pr, "head": {**pr["head"], field: value}}})
                with patch.dict(os.environ, environment), self.assertRaises(RddError):
                    self.verify_release()
                self.assertEqual(self.commands, [])
        write_json(event_path, {"pull_request": pr})
        with patch.dict(os.environ, environment | {"GITHUB_EVENT_NAME": "push"}), self.assertRaisesRegex(RddError, "pull_request"):
            self.verify_release()
        self.assertEqual(self.commands, [])

    @unittest.skipIf(os.name == "nt", "Symlink creation needs extra privilege on Windows")
    def test_symlinked_policy_directory_is_rejected(self):
        self.clone()
        outside = self.home / "outside"
        outside.mkdir()
        (self.candidate / ".codex").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RddError):
            self.verify("main")
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()
