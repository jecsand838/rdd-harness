"""Persistent RDD state machine. Models author artifacts; this controller checks transitions."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

from . import artifacts
from .stages import StageWorkflow
from .reviews import ReviewStream
from .nodes import WorkflowNodes, NODES
from .refinement import RefinementWorkflow, new_state as refinement_state, validate_state as validate_refinement, POLICY as REFINEMENT_POLICY
from .profiles import IMPLEMENTOR_SCOPES, load_profiles, profile_policy_digest, profile_settings
from .readiness import validate_resources, validate_producers, required_probe_ids
from .adapters import CodexAdapter, GitAdapter, GitHubAdapter, RddAdapterError, validate_native_permission
from .checks import execute_check, platform_name, verify_receipt
from .common import (EXCLUDED_FILES, EXCLUDED_PREFIXES, RddError, RddStorageError, Store, assert_inventory, atomic_write, clean, digest, event,
                     file_hash, git, head, inventory, now, read_json, safe_path,
                     require_source_branch, source_digest, validate_artifact, write_json)

POLICY_PREFIXES = (".agents/", ".codex/", ".github/", "tools/rdd/", "tools/proto-codegen/", "tests/harness/",
                   ".rdd/schemas/", ".rdd/templates/", ".rdd/goals/")
POLICY_FILES = {".rdd/config.json", "AGENTS.md", "rdd", "rdd.cmd", "rdd.ps1", "buf.yaml", "buf.lock",
                "buf.gen.yaml", "rust-toolchain.toml", ".gitignore", ".gitattributes"}


def policy_inventory(root: Path) -> dict:
    selected = {p: h for p, h in inventory(root).items() if p.startswith(POLICY_PREFIXES) or p in POLICY_FILES}
    # Optional generator/dependency inputs freeze their absence as well as
    # their bytes, independently of candidate ignore rules.
    selected.update(inventory(root, list(POLICY_FILES)))
    return selected


def lock_value(files: dict, **metadata) -> dict:
    body = {"schema_version": 1, "files": files, **metadata}
    return {**body, "digest": digest(body)}


def verify_lock(root: Path, rel: str) -> dict:
    lock = read_json(safe_path(root, rel, allow_missing=False))
    if lock.get("digest") != digest({k: v for k, v in lock.items() if k != "digest"}):
        raise RddError(f"Invalid lock digest: {rel}", "specification")
    assert_inventory(root, lock["files"], rel)
    return lock


def task_boundary_context(root: Path, spec: dict, plan: dict, task: dict) -> dict:
    """Project the existing frozen ownership map into the bounded worker packet."""
    inventory = artifacts.load_domain_inventory(root, spec)
    selected = {element["module"] for element in spec["solution_elements"]
                if element["id"] in task["solution_elements"] and element["module"] is not None}
    for proof in plan["boundary_proofs"] + plan["type_import_proofs"]:
        if any(task["id"] in proof.get(role, []) for role in
               ("provider_tasks", "consumer_tasks", "adapter_tasks", "verification_tasks")):
            selected.update((proof["consumer"], proof["provider"]))
    interactions = {row["id"]: row for row in inventory["interactions"]
                    if row["consumer"] in selected or row["provider"] in selected}
    interfaces = selected | {row[key] for row in interactions.values() for key in ("consumer", "provider")}
    return {"inventory": spec["domain_inventory"], "specification": ".rdd/spec.json",
            "owners": [row for row in inventory["domains"] + inventory["supporting_modules"]
                       if row["module"] in interfaces],
            "modules": [{key: module[key] for key in ("id", "owns_paths", "contract_package", "public_exports",
                         "provided_services", "consumed_operations", "provided_types", "consumed_types")}
                        for module in spec["modules"] if module["id"] in interfaces],
            "interactions": [{**interactions[binding["interaction"]], **binding}
                             for binding in spec["boundary_bindings"] if binding["interaction"] in interactions]}


class Controller(StageWorkflow, ReviewStream, WorkflowNodes, RefinementWorkflow):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.config = read_json(self.root / ".rdd/config.json")
        self._store = None

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = Store(self.root)
        return self._store

    def close(self):
        if self._store is not None:
            self._store.close()

    def guard_v2(self) -> None:
        locator = self.root / ".rdd/run.json"
        if locator.is_file():
            run_id = read_json(locator).get("run_id")
            if run_id and Store.read(self.root, run_id).get("workflow_version") != 2:
                raise RddError("Legacy runs are read/export only. Preserve history and start a fresh isolated baseline using the current specification schema.", "environment")

    def profile_settings(self, role: str) -> dict:
        return profile_settings(self.root, role)

    def guard_run_policy(self, state: dict | None = None) -> None:
        """Refuse historical continuation before any write, without migrating history."""
        if state is None:
            locator = self.root / ".rdd/run.json"
            run_id = read_json(locator).get("run_id") if locator.is_file() else None
            if not run_id:
                return
            state = Store.read(self.root, run_id)
        if not isinstance(state, dict):
            raise RddError("Run policy requires a valid recorded state", "environment")
        if state.get("workflow_version") != 2:
            raise RddError("Legacy runs are read/export only. Preserve history and start a fresh isolated baseline using the current specification schema.", "environment")
        if (state.get("workflow_version") != 2 or state.get("workflow_graph_digest") != digest(NODES)
                or state.get("agent_profile_digest") != profile_policy_digest(self.root)
                or not isinstance(state.get("refinement"), dict)
                or state["refinement"].get("policy") != REFINEMENT_POLICY):
            raise RddError("This run belongs to an earlier workflow/profile policy. Inspect/export it, recover with its recorded source revision and matching harness, or start a fresh reviewed run.", "environment")

    def guard_source_write(self, state: dict | None = None, *, baseline: bool = False) -> str:
        """Admit only the recorded authoring/implementation checkout before writes."""
        require_source_branch(self.root)
        if state is None:
            locator = read_json(self.root / ".rdd/run.json")
            if not locator.get("run_id"):
                raise RddError("No active run. Start with ./rdd start --mode regenerate.")
            state = Store.read(self.root, locator["run_id"])
        self.guard_run_policy(state)
        base = state.get("base_branch")
        if not isinstance(base, str) or not base or base == "main":
            raise RddError("This run has no writable authoring baseline. Inspect/export it, then start a fresh amend/regenerate run on a dedicated baseline branch; its recorded baseline cannot be rewritten.", "environment")
        expected = base
        if not baseline:
            pid = state.get("active_phase")
            phases = state.get("phases")
            if not isinstance(phases, dict) or any(not isinstance(p, dict) for p in phases.values()):
                raise RddError("The run has no valid recorded phase identities. Preserve its state and inspect the checkpoint before retrying.", "environment")
            if pid:
                if not isinstance(pid, str) or pid not in phases:
                    raise RddError("The run has no valid recorded active phase identity. Preserve its state and inspect the checkpoint before retrying.", "environment")
                expected = phases[pid].get("branch")
            else:
                opened = [(key, p) for key, p in phases.items() if p.get("status") != "pending"]
                if opened:
                    if any(not re.fullmatch(r"P[0-9]{2,3}", key) for key, _ in opened):
                        raise RddError("The run has invalid recorded phase IDs. Preserve its state and inspect the checkpoint before retrying.", "environment")
                    expected = max(opened, key=lambda row: int(row[0][1:]))[1].get("branch")
        if not isinstance(expected, str) or not expected:
            raise RddError("The run has no recorded branch for this write. Preserve its state and inspect the checkpoint before retrying.", "environment")
        return require_source_branch(self.root, expected)

    def state(self, *, allow_blocked: bool = False) -> dict:
        locator = read_json(self.root / ".rdd/run.json")
        if not locator.get("run_id"):
            raise RddError("No active run. Start with ./rdd start --mode regenerate.")
        state = Store.read(self.root, locator["run_id"])
        if state.get("workflow_graph_digest") == digest(NODES):
            validate_refinement(self.root, state, self.config)
        if not allow_blocked and any(not b["resolved"] for b in state["blockers"]):
            raise RddError("Run is blocked. Read ./rdd status; resolve environment/review issues with resume, or start a new specification run for authority/closure changes.", "environment")
        return state

    def save(self, state: dict) -> None:
        self.guard_run_policy(state)
        self.store.put(state)
        write_json(self.root / ".rdd/run.json", {"schema_version": 1, "run_id": state["id"],
                   "status": state["status"], "baseline": f".rdd/baselines/{state['id']}"})

    def spec(self) -> dict:
        return read_json(self.root / ".rdd/spec.json")

    def plan(self) -> dict:
        return read_json(self.root / ".rdd/plan/plan.json")

    def frozen(self, *, planned: bool = True) -> tuple[dict, dict | None]:
        state = self.state()
        self.guard_run_policy(state)
        spec_lock = verify_lock(self.root, ".rdd/spec.lock.json")
        if spec_lock["digest"] != state.get("spec_digest"):
            raise RddError("Active run/specification identity mismatch", "specification")
        actual_policy = policy_inventory(self.root)
        if actual_policy != state["policy_inventory"]:
            raise RddError("Controller, skill, workflow, or policy inventory changed after specification freeze", "specification")
        full = inventory(self.root)
        actual_boundaries = {p: h for p, h in full.items() if p.startswith(("contracts/", "gen/"))}
        expected_boundaries = {p: h for p, h in spec_lock["files"].items() if p.startswith(("contracts/", "gen/"))}
        if actual_boundaries != expected_boundaries:
            raise RddError("Contract/generated inventory added, deleted, or changed after freeze", "specification")
        plan_lock = None
        if planned:
            plan_lock = verify_lock(self.root, ".rdd/plan/plan.lock.json")
            if plan_lock["digest"] != state.get("plan_digest") or plan_lock["spec_digest"] != spec_lock["digest"]:
                raise RddError("Active run/plan identity mismatch", "specification")
            if (self.root / ".rdd/prepared.json").is_file():
                prepared = read_json(self.root / ".rdd/prepared.json")
                if prepared.get("digest") != state.get("prepared_digest") or prepared["digest"] != digest({k: v for k, v in prepared.items() if k != "digest"}):
                    raise RddError("Preparation receipt changed", "specification")
                if file_hash(self.root / ".rdd/plan/implementation-matrix.md") != prepared["matrix_digest"]:
                    raise RddError("Frozen implementation matrix changed", "specification")
        return spec_lock, plan_lock

    def init(self) -> dict:
        self.guard_v2()
        self.guard_run_policy()
        profile_policy_digest(self.root)
        if git(self.root, "rev-parse", "--show-toplevel", check=False) != str(self.root):
            git(self.root, "init", "-b", "main")
        for rel in (".rdd/runtime", ".rdd/evidence", ".rdd/plan/anchors", ".rdd/baselines"):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        if not (self.root / ".rdd/run.json").is_file():
            write_json(self.root / ".rdd/run.json", {"schema_version": 1, "run_id": None, "status": "not_started"})
        reqs = artifacts.requirements(self.root, self.config["requirements"])
        return {"status": "initialized", "requirements": len(reqs["records"]), "requirements_digest": reqs["digest"],
                "next": "Commit the boilerplate with your Git identity; run ./rdd doctor --full, then ./rdd workflow specification."}

    def doctor(self, full: bool = False) -> dict:
        profiles = load_profiles(self.root)
        roles = {role: (p["model"], p["effort"]) for role, p in profiles.items()}
        tools = {name: shutil.which(name) for name in ("git", "codex", "gh", "cargo", "rustc", "buf", "protoc")}
        result = {"python": sys.version.split()[0], "python_supported": sys.version_info >= (3, 11),
                  "tools": tools, "profiles": {role: self.profile_settings(role) for role in profiles},
                  "requirements": len(artifacts.requirements(self.root, self.config["requirements"])["records"]),
                  "application_generated": (self.root / ".rdd/spec.lock.json").is_file(),
                  "notes": ["Client/catalog support is not account entitlement.",
                            "Platform packaging and reference-device qualification are application checks specified by the first workflow."]}
        if full:
            codex = tools["codex"]
            if codex:
                result["codex"] = CodexAdapter(self.root, binary=codex).doctor(sorted(set(roles.values())), roles=profiles)
            else:
                result["codex"] = {"status": "blocked", "reason": "codex is not on PATH"}
            if tools["gh"]:
                from .adapters import run_argv
                auth = run_argv(["gh", "auth", "status"], cwd=self.root)
                result["github_auth"] = {"ready": auth.returncode == 0, "detail": "Authenticated" if auth.returncode == 0 else "Run gh auth login locally"}
            result["missing"] = [name for name, path in tools.items() if not path and name != "protoc"]
            result["optional_tools"] = {"protoc": "Buf emits descriptors; the shipped generator uses compile_fds and does not require protoc."}
        result["ready"] = bool(result["python_supported"] and tools["git"] and (not full or not result["missing"]))
        if full:
            result["ready"] = bool(result["ready"] and result.get("codex", {}).get("ready", False)
                                   and result.get("github_auth", {}).get("ready", False))
            result["account_access_verified"] = False
        return result

    def start(self, mode: str, run_id: str | None = None) -> dict:
        self.guard_v2()
        baseline_branch = require_source_branch(self.root)
        profiles_digest = profile_policy_digest(self.root)
        if mode not in {"regenerate", "amend"}:
            raise RddError("Run mode must be regenerate or amend")
        clean(self.root)
        run_id = run_id or time.strftime("R%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:6]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_id):
            raise RddError("Run ID must be 1-64 plain letters, digits, dots, underscores or hyphens")
        existing = self.store.exists(run_id)
        if existing or (self.root / f".rdd/baselines/{run_id}").exists():
            raise RddError("Run ID is already in use")
        locator = read_json(self.root / ".rdd/run.json")
        previous = None
        if locator.get("run_id"):
            previous = self.store.get(locator["run_id"])
            if any(t["status"] in {"claimed", "integrated"} for t in previous.get("tasks", {}).values()):
                raise RddError("Release/integrate active leases and complete or release integrated work before starting another run")
        old_spec_path = self.root / ".rdd/spec.json"
        old_lock_path = self.root / ".rdd/spec.lock.json"
        old_spec = read_json(old_spec_path) if old_spec_path.is_file() else None
        old_lock = read_json(old_lock_path) if old_lock_path.is_file() else None
        if mode == "amend" and not old_lock:
            raise RddError("Amendment requires a previous frozen specification")
        reqs = artifacts.requirements(self.root, self.config["requirements"])
        reqs["document"] = (self.root / self.config["requirements"]).read_text(encoding="utf-8")
        prior_path = self.root / ".rdd/requirements.index.json"
        prior = read_json(prior_path) if prior_path.is_file() else None
        old_records = (prior or {}).get("records", {})
        current = reqs["records"]
        changed = sorted(rid for rid in current.keys() | old_records.keys()
                         if current.get(rid, {}).get("digest") != old_records.get(rid, {}).get("digest"))
        # Global glossary/data rules are normative too; conservatively expand impact when context changed.
        def context(index):
            text = index.get("document", "")
            for record in index.get("records", {}).values():
                text = text.replace(record["text"], "")
            return text
        if prior and context(prior) != context(reqs):
            changed = sorted(current.keys() | old_records.keys())
        base_dir = self.root / f".rdd/baselines/{run_id}"
        base_dir.mkdir(parents=True)
        archive_paths = {p for p in inventory(self.root) if p.startswith(("docs/specs/", "docs/decisions/", "contracts/", "gen/", ".rdd/plan/"))}
        archive_paths.update(p for p in (".rdd/spec.json", ".rdd/spec.lock.json", ".rdd/prepared.json", ".rdd/requirements.index.json") if (self.root / p).is_file())
        for rel in sorted(archive_paths):
            dest = base_dir / "previous" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_path(self.root, rel, allow_missing=False), dest)
        inputs = base_dir / "inputs"
        inputs.mkdir()
        shutil.copyfile(self.root / self.config["requirements"], inputs / "requirements.md")
        if previous:
            write_json(base_dir / "previous-run.json", previous)
        if mode == "regenerate" and old_spec:
            for rel in old_spec["documents"] + old_spec["decisions"] + old_spec["contract_files"] + old_spec["generated_files"]:
                if not rel.startswith(("docs/specs/", "docs/decisions/", "contracts/", "gen/")):
                    raise RddError("Previous specification contains an unsafe artifact inventory")
                if rel.startswith("contracts/rdd/") or Path(rel).name == "README.md":
                    continue
                safe_path(self.root, rel).unlink(missing_ok=True)
            old_spec_path.unlink(missing_ok=True)
        # Only derived planning artifacts are cleared. Existing application code remains for planned edits.
        for rel in (".rdd/spec.lock.json", ".rdd/plan/plan.json", ".rdd/plan/plan.lock.json",
                    ".rdd/plan/implementation-matrix.md", ".rdd/prepared.json"):
            (self.root / rel).unlink(missing_ok=True)
        for p in (self.root / ".rdd/plan/anchors").glob("T*.md"):
            p.unlink()
        # Old inline projections are removed using their prior exact task definitions, never broad text replacement.
        previous_plan = base_dir / "previous/.rdd/plan/plan.json"
        if previous_plan.is_file():
            for task in read_json(previous_plan)["tasks"]:
                artifacts.remove_anchor(self.root, task)
        state = {"workflow_version": 2, "workflow_graph_digest": digest(NODES), "agent_profile_digest": profiles_digest,
                 "workflow_nodes": {}, "refinement": refinement_state(), "id": run_id, "mode": mode, "status": "specification", "created_at": now(),
                 "base_commit": head(self.root), "base_branch": baseline_branch,
                 "parent_spec_digest": old_lock["digest"] if old_lock else None,
                 "requirements_digest": reqs["digest"], "changed_requirements": changed,
                 "policy_inventory": {}, "tasks": {}, "phases": {}, "active_phase": None,
                 "checks": {}, "reviews": {}, "blockers": [], "events": []}
        write_json(self.root / ".rdd/requirements.index.json", reqs)
        event(state, "run_started", mode=mode)
        self.save(state)
        return {"run_id": run_id, "mode": mode, "changed_requirements": changed,
                "next": "Author or amend the solution with specification-workflow; validate and freeze it."}

    def requirements_index(self) -> dict:
        reqs = artifacts.requirements(self.root, self.config["requirements"])
        return {"path": reqs["path"], "digest": reqs["digest"], "count": len(reqs["records"]),
                "requirements": [{"id": r["id"], "title": r["title"]} for r in reqs["records"].values()]}

    def spec_init(self) -> dict:
        self.guard_source_write(baseline=True)
        state = self.state()
        if state["status"] != "specification":
            raise RddError("Specifications can only be authored in specification workflow", "specification")
        path = self.root / ".rdd/spec.json"
        if path.exists():
            return {"path": ".rdd/spec.json", "status": "existing", "next": "Amend the existing manifest; initialization never overwrites it."}
        spec = {"schema_version": 3, "author_sessions": [],
                "domain_inventory": {"path": "docs/specs/domain-inventory.json", "sha256": "", "s1_output_digest": ""},
                "boundary_bindings": [], "contract_index_path": "gen/rust/.rdd-generated.json", "shared_generated_files": [], "solution_elements": [], "target_tree": [], "resources": [], "environments": [], "id": state["id"], "requirements_digest": state["requirements_digest"],
                "mode": state["mode"], "parent_spec_digest": state["parent_spec_digest"], "change_summary": "",
                "documents": ["docs/specs/refinement.json"], "decisions": [], "contract_files": [], "generated_files": [],
                "contract_check_ids": ["C-CONTRACTS"], "project_check_ids": [], "modules": [], "scenarios": [],
                "checks": [{"id": "C-CONTRACTS", "kind": "contract", "argv": ["{python}", "tools/rdd/proto_traits.py"],
                            "cwd": ".", "timeout_seconds": 1800, "platforms": ["any"], "red_pattern": None,
                            "metrics": [], "host_profile": None, "environments": [], "requires": [], "scenario_ids": [], "results_path": None}], "requirement_map": [],
                "amendment": {"requirements": state["changed_requirements"] if state["mode"] == "amend" else [],
                              "paths": [], "rationale": ""}}
        write_json(path, spec)
        return {"path": ".rdd/spec.json", "status": "authoring_template", "valid": False,
                "next": "Fill every field and linked artifact; template emptiness is intentional and cannot freeze."}

    def spec_validate(self) -> dict:
        state, spec = self.state(), self.spec()
        reqs = artifacts.requirements(self.root, self.config["requirements"])
        if spec["mode"] != state["mode"] or spec["parent_spec_digest"] != state["parent_spec_digest"]:
            raise RddError("Specification mode/parent does not match active run", "specification")
        if reqs["digest"] != state["requirements_digest"]:
            raise RddError("Requirements changed after run start; start a new specification run", "specification")
        self.guard_run_policy(state)
        self.require_refinement(state)
        result = artifacts.spec_validate(self.root, spec, reqs, self.config)
        artifacts.validate_accepted_domain_inventory(self.root, spec, self._node_records(state))
        validate_resources(self.root, spec)
        if state["mode"] == "amend":
            if not set(state["changed_requirements"]) <= set(spec["amendment"]["requirements"]):
                raise RddError("Amendment impact omits changed requirements", "specification")
            if not spec["amendment"]["paths"] or len(spec["amendment"]["rationale"]) < 20:
                raise RddError("Amendment needs bounded impact paths and a reasoned impact analysis")
            for rel in spec["amendment"]["paths"]:
                safe_path(self.root, rel)
        return result

    def spec_freeze(self) -> dict:
        self.guard_source_write(baseline=True)
        state = self.state()
        if state["status"] != "specification":
            raise RddError("Specification is already frozen; use a new specification run", "specification")
        result = self.spec_validate()
        spec = self.spec()
        lock = self.spec_candidate_lock()
        self.require_workflow_node("S7")
        acceptance = self.stage_acceptance("specification")
        proofs = self.ensure_checks(state, spec["contract_check_ids"], candidate_spec_digest=lock["digest"])
        state["spec_acceptance"] = acceptance
        assert_inventory(self.root, lock["files"], "Specification freeze inputs")
        write_json(self.root / ".rdd/spec.lock.json", lock)
        state.update(status="specified", spec_digest=lock["digest"], policy_inventory=policy_inventory(self.root))
        state["checks"].update({r["id"]: r for r in proofs})
        event(state, "specification_frozen", digest=lock["digest"], contract_proofs=[r["id"] for r in proofs])
        self.save(state)
        return {"status": "specified", "spec_digest": lock["digest"], **result,
                "next": "Commit the specification baseline; run preparation-workflow."}

    def spec_candidate_lock(self) -> dict:
        """Identity of a complete draft for native qualification before freezing."""
        state, spec = self.state(), self.spec()
        paths = set(spec["documents"] + spec["decisions"] + spec["contract_files"] + spec["generated_files"])
        refinement = self.require_refinement(state)["snapshot"]
        paths.update(s["path"] for s in refinement["question_sources"])
        paths.update(s["path"] for d in refinement["decisions"] for s in d["sources"])
        paths.update({self.config["requirements"], ".rdd/spec.json", ".rdd/requirements.index.json"})
        paths.update(p for p in inventory(self.root) if p.startswith(("contracts/", "gen/", ".rdd/sources/")))
        qualification = set(spec["contract_check_ids"] + required_probe_ids(spec))
        inputs = {rid for check in spec["checks"] if check["id"] in qualification for rid in check["requires"]}
        paths.update(r["path"] for r in spec["resources"] if r["id"] in inputs and r["kind"] == "repository"
                     and r["availability"] == "baseline")
        policy = policy_inventory(self.root)
        paths.update(policy)
        return lock_value(inventory(self.root, list(paths)), requirements_digest=state["requirements_digest"])

    def plan_init(self) -> dict:
        self.guard_source_write(baseline=True)
        self.frozen(planned=False)
        path = self.root / ".rdd/plan/plan.json"
        if path.exists():
            return {"path": ".rdd/plan/plan.json", "status": "existing"}
        write_json(path, {"schema_version": 3, "author_sessions": [], "boundary_proofs": [], "type_import_proofs": [], "element_coverage": [], "resource_producers": [], "resource_uses": [], "spec_digest": self.state()["spec_digest"], "phases": [],
                          "tasks": [], "verticals": [], "target_paths": [], "shells": []})
        return {"path": ".rdd/plan/plan.json", "status": "authoring_template", "valid": False}

    def plan_validate(self) -> dict:
        lock, _ = self.frozen(planned=False)
        result = artifacts.plan_validate(self.root, self.plan(), self.spec(), lock, self.config)
        validate_producers(self.root, self.spec(), self.plan())
        if self.state()["mode"] == "amend":
            impact = self.spec()["amendment"]["paths"]
            for task in self.plan()["tasks"]:
                if any(not any(path == scope or (scope.endswith("/") and path.startswith(scope)) for scope in impact) for path in task["writes"]):
                    raise RddError(f"Amendment task {task['id']} writes outside frozen impact paths", "specification")
        return result

    def plan_candidate_lock(self) -> dict:
        paths = [".rdd/plan/plan.json"] + [p for p in inventory(self.root) if p.startswith(".rdd/plan/notes/")]
        return lock_value(inventory(self.root, paths), spec_digest=self.state()["spec_digest"])

    def plan_freeze(self) -> dict:
        self.guard_source_write(baseline=True)
        state = self.state()
        if state["status"] != "specified":
            raise RddError("Plan can be frozen only after specification and before preparation")
        result = self.plan_validate()
        plan = self.plan()
        self.require_workflow_node("P5")
        acceptance = self.stage_acceptance("plan")
        lock = self.plan_candidate_lock()
        state["plan_acceptance"] = acceptance
        write_json(self.root / ".rdd/plan/plan.lock.json", lock)
        state.update(status="planned", plan_digest=lock["digest"])
        state["tasks"] = {t["id"]: {"status": "todo", "attempts": 0, "worker": None, "session_id": None,
                                      "lease_expires": None, "worktree": None, "commit": None, "evidence": []}
                          for t in plan["tasks"]}
        state["phases"] = {p["id"]: {"status": "pending"} for p in plan["phases"]}
        event(state, "plan_frozen", digest=lock["digest"])
        self.save(state)
        return {"status": "planned", "plan_digest": lock["digest"], **result}

    def prepare(self) -> dict:
        self.guard_source_write(baseline=True)
        self.frozen()
        state = self.state()
        if state["status"] in {"preparing", "prepared"}:
            artifacts.anchors_verify(self.root, self.plan(), state)
            return {"status": state["status"], "idempotent": True}
        if state["status"] != "planned":
            raise RddError("Preparation requires a frozen plan and cannot rerun over implementation")
        spec, plan = self.spec(), self.plan()
        local_contracts = []
        for check in spec["checks"]:
            if check["id"] in spec["contract_check_ids"]:
                if "any" not in check["platforms"] and platform_name() not in check["platforms"]:
                    continue  # All native qualification was required at freeze; reproduce the unchanged contracts on this host.
                receipt = execute_check(self.root, check, phase=None, task_id=None, expectation="pass",
                                        spec_digest=state["spec_digest"], plan_digest=state["plan_digest"])
                local_contracts.append(check["id"])
                state["checks"][receipt["id"]] = receipt
                if receipt["outcome"] != "pass":
                    self.save(state)
                    raise RddError(f"Contract preparation proof failed: {check['id']}", "specification")
        if not local_contracts:
            raise RddError("Preparation must run on a host with at least one applicable frozen contract compilation check", "environment")
        self.frozen()
        created = artifacts.materialize(self.root, plan, state)
        matrix = artifacts.implementation_matrix(plan, spec)
        atomic_write(self.root / ".rdd/plan/implementation-matrix.md", matrix.encode())
        body = {"schema_version": 1, "run_id": state["id"], "spec_digest": state["spec_digest"],
                "plan_digest": state["plan_digest"], "shell_hashes": inventory(self.root, created),
                "matrix_digest": file_hash(self.root / ".rdd/plan/implementation-matrix.md")}
        prepared = {**body, "digest": digest(body)}
        write_json(self.root / ".rdd/prepared.json", prepared)
        state.update(status="preparing", prepared_digest=prepared["digest"])
        event(state, "prepared", created=created)
        self.save(state)
        artifacts.anchors_verify(self.root, plan, state)
        return {"status": "preparing", "created_shells": created, "tasks": len(plan["tasks"]),
                "next": "Commit materialized artifacts; run preparation readiness, both reviews, then gate preparation."}

    def status(self) -> dict:
        locator_path = self.root / ".rdd/run.json"
        try:
            locator_path.lstat()
        except FileNotFoundError:
            return {"status": "not_started", "next": "./rdd init"}
        locator = read_json(locator_path)
        if not locator.get("run_id"):
            return {"status": "not_started", "next": "./rdd workflow specification"}
        state = self.state(allow_blocked=True)
        counts = {s: sum(t["status"] == s for t in state["tasks"].values()) for s in ("todo", "claimed", "integrated", "done")}
        return {"run_id": state["id"], "mode": state["mode"], "status": state["status"],
                "source_commit": head(self.root), "source_digest": source_digest(self.root),
                "active_phase": state["active_phase"], "tasks": counts, "phases": state["phases"],
                "blockers": [b for b in state["blockers"] if not b["resolved"]],
                "spec_digest": state.get("spec_digest"), "plan_digest": state.get("plan_digest"),
                "workflow_nodes": self.workflow_nodes(), "review_cursor": len(state.get("live_reviews", [])),
                "refinement": self.refinement_status(state) if state.get("workflow_graph_digest") == digest(NODES) else {"historical": True},
                "last_events": state["events"][-8:]}

    def active(self, state: dict) -> str:
        pid = state["active_phase"]
        if not pid or state["phases"][pid]["status"] not in {"active", "gated"}:
            raise RddError("There is no open implementation phase")
        if git(self.root, "branch", "--show-current") != state["phases"][pid]["branch"]:
            raise RddError("The checkout is not on the recorded active phase branch", "environment")
        return pid

    def phase_begin(self, phase: str) -> dict:
        self.guard_source_write()
        self.frozen()
        clean(self.root)
        state, plan = self.state(), self.plan()
        if state["status"] not in {"prepared", "implementation"}:
            raise RddError("Phase implementation requires a committed preparation baseline")
        pids = [p["id"] for p in plan["phases"]]
        if phase not in pids:
            raise RddError("Unknown phase")
        if state["active_phase"]:
            if state["active_phase"] == phase:
                self.active(state)
                return {"phase": phase, "status": state["phases"][phase]["status"], "idempotent": True}
            raise RddError("Seal the current phase before opening another")
        pending = next((p for p in pids if state["phases"][p]["status"] != "sealed"), None)
        if phase != pending or state["phases"][phase]["status"] != "pending":
            raise RddError("Phases open sequentially, and a sealed phase cannot reopen", "closure")
        index = pids.index(phase)
        if index:
            prior = state["phases"][pids[index - 1]]
            base_branch, base_sha = prior["branch"], prior["head"]
            if head(self.root) != base_sha or head_ref(self.root, base_branch) != base_sha:
                raise RddError("Prior sealed phase moved; preserve its revision and start an amendment if repair is needed", "closure")
        else:
            gate = state.get("preparation_gate")
            if not gate or gate["candidate"]["source_commit"] != head(self.root) or gate["candidate"]["source_digest"] != source_digest(self.root):
                raise RddError("First phase requires exact-source accepted preparation gate", "review")
            if any(gate.get(k) != v for k, v in self.stage_acceptance("preparation").items()):
                raise RddError("Preparation gate differs from current independently reviewed evidence", "review")
            base_branch, base_sha = state["base_branch"], head(self.root)
            if git(self.root, "branch", "--show-current") != base_branch:
                raise RddError("First phase must branch from the recorded preparation baseline branch")
        branch = GitAdapter(self.root).create_phase_branch(state["id"], index + 1, base_sha)
        if head_ref(self.root, branch) != base_sha:
            raise RddError("Pending phase branch already contains commits. Preserve it and reconcile the prior run; do not skip its changes by resetting the phase start.", "closure")
        git(self.root, "switch", branch)
        state["phases"][phase] = {"status": "active", "branch": branch, "base_branch": base_branch,
                                    "base_sha": base_sha, "start_sha": head(self.root), "gate": None,
                                    "pr": None, "review": None, "head": None}
        state.update(status="implementation", active_phase=phase)
        event(state, "phase_opened", phase=phase, branch=branch, base=base_sha)
        self.save(state)
        return {"phase": phase, "branch": branch, "base_branch": base_branch, "base_sha": base_sha,
                "next": "./rdd next"}

    def eligible(self, state: dict) -> list[dict]:
        pid = self.active(state)
        tasks = [t for t in self.plan()["tasks"] if t["phase"] == pid]
        unfinished = [t for t in tasks if state["tasks"][t["id"]]["status"] != "done"]
        if not unfinished:
            return []
        category = min((t["category"] for t in unfinished), key=artifacts.CATEGORIES.index)
        return [t for t in unfinished if t["category"] == category and state["tasks"][t["id"]]["status"] == "todo"
                and all(state["tasks"][dep]["status"] == "done" for dep in t["depends_on"])]

    def guard_task_order(self, state: dict, task: dict) -> None:
        """An existing lease cannot bypass dependencies or a reopened category."""
        unfinished = [t for t in self.plan()["tasks"] if t["phase"] == task["phase"]
                      and state["tasks"][t["id"]]["status"] != "done"]
        if (any(artifacts.CATEGORIES.index(t["category"]) < artifacts.CATEGORIES.index(task["category"])
                for t in unfinished)
                or any(state["tasks"][dep]["status"] != "done" for dep in task["depends_on"])):
            raise RddError("Task is not ready in the active phase/category/dependency order")

    def next(self) -> dict:
        self.frozen()
        state = self.state()
        pid = self.active(state)
        ready = self.eligible(state)
        active_tasks = [{"id": tid, **task} for tid, task in state["tasks"].items() if task["status"] in {"claimed", "integrated"}]
        return {"phase": pid, "ready": [{"id": t["id"], "category": t["category"], "scope": t["scope"],
                                          "title": t["title"], "writes": t["writes"]} for t in ready],
                "in_progress": active_tasks,
                "next": "Claim dependency-ready tasks with disjoint write sets" if ready else
                        "Integrate/complete active work, or run cumulative checks and independent phase review"}

    def task(self, tid: str) -> dict:
        tasks = artifacts.unique(self.plan()["tasks"], "task")
        if tid not in tasks:
            raise RddError(f"Unknown task {tid}")
        return tasks[tid]

    def invalidate(self, state: dict, phase: str) -> None:
        state["phases"][phase]["gate"] = None
        state["phases"][phase]["review"] = None
        state["phases"][phase]["status"] = "active"
        state["reviews"].pop(phase, None)

    def task_claim(self, tid: str, worker: str, worktree: bool = True, session_id: str | None = None) -> dict:
        self.guard_source_write()
        self.frozen()
        if not isinstance(session_id, str) or not session_id.strip():
            raise RddError("Task claims require the actual implementor --session-id; lease labels are not session provenance")
        task, state = self.task(tid), self.state()
        self.live_review_guard(final=False, stage="implementation", task=tid,
            repair_findings=self.task_repair_authorization(state, tid))
        self.guard_author_identity(session_id)
        clean(self.root)
        pid = self.active(state)
        self.review_category_handoff(state, task)
        if worker not in IMPLEMENTOR_SCOPES:
            raise RddError("Implementation workers are rdd_complex_implementor or rdd_light_implementor")
        if task["scope"] not in IMPLEMENTOR_SCOPES[worker]:
            raise RddError("Large scope tasks require the complex implementor role")
        requested_runtime = self.profile_settings(worker)
        with self.store.edit(state["id"]) as state:
            if tid not in {t["id"] for t in self.eligible(state)}:
                raise RddError("Task is not ready in the active phase/category/dependency order")
            live = [self.task(i) for i, t in state["tasks"].items() if t["status"] in {"claimed", "integrated"}]
            if len(live) >= 2:
                raise RddError("Two implementors are already active; reserve the third subagent slot for live review")
            if any(set(task["writes"]) & set(other["writes"]) for other in live):
                raise RddError("Task write set overlaps a live lease")
            record = state["tasks"][tid]
            if record["attempts"] >= self.config["limits"]["max_attempts"]:
                raise RddError("Task attempt budget exhausted; report the concrete blocker", "budget")
            attempt = record["attempts"] + 1
            branch = f"rdd/{state['id']}/{tid.lower()}-a{attempt}"
            path = f".rdd/runtime/worktrees/{state['id']}/{tid}-a{attempt}"
            authors = state.setdefault("authors", {}).setdefault("implementation", [])
            for author in (record.get("session_id"), session_id):
                if author and author not in authors:
                    authors.append(author)
            record.update(status="claimed", attempts=attempt, worker=worker, requested_runtime=requested_runtime,
                          session_id=session_id,
                          lease_expires=time.time() + self.config["limits"]["lease_seconds"],
                          base_commit=head(self.root), branch=branch, worktree=path if worktree else None,
                          evidence=[], commit=None)
            self.invalidate(state, pid)
            event(state, "task_claimed", task=tid, worker=worker, attempt=attempt)
        state = self.store.get(state["id"])
        record = state["tasks"][tid]
        if worktree:
            try:
                GitAdapter(self.root).ensure_worktree(self.root / record["worktree"], record["branch"], record["base_commit"])
            except BaseException:
                # Lease remains explicit; release never removes a dirty/partially-created worktree.
                event(state, "worktree_creation_incomplete", task=tid)
                self.save(state)
                raise
        spec = self.spec()
        reqs = read_json(self.root / ".rdd/requirements.index.json")
        packet = {"run_id": state["id"], "phase": pid, "task": task, "lease": record,
                  "spec_digest": state["spec_digest"], "plan_digest": state["plan_digest"],
                  "requirements": [reqs["records"][r] for r in task["requirements"]],
                  "contract_files": spec["contract_files"], "generated_files": spec["generated_files"],
                  "boundary_context": task_boundary_context(self.root, spec, self.plan(), task),
                  "instructions": ["Read AGENTS.md and only the relevant skills/frozen solution sections.",
                                   "Follow domain-boundaries and boundary_context for owned modules, permitted calls/types and frozen public exports.",
                                   "Edit only task.writes; preserve task markers until controller completion.",
                                   "Do not change requirements, contracts, generated types, tests' intended outcomes, or harness policy.",
                                   "Commit the isolated implementation; return its complete SHA and evidence to the coordinator.",
                                   "Specification ambiguity is a blocker. Review happens at phase completion, not per task."]}
        packet_text = json.dumps(packet, indent=2, ensure_ascii=False)
        if len(packet_text) > self.config["limits"]["max_packet_characters"]:
            packet["requirements"] = [{"id": r, "source": self.config["requirements"]} for r in task["requirements"]]
            packet_text = json.dumps(packet, indent=2, ensure_ascii=False)
        if len(packet_text) > self.config["limits"]["max_packet_characters"]:
            raise RddError("Task packet exceeds bounded context budget; release and reduce task scope through preparation", "budget")
        packet_path = f".rdd/runtime/packets/{state['id']}/{tid}-a{record['attempts']}.json"
        atomic_write(self.root / packet_path, packet_text.encode() + b"\n")
        return {"task": tid, "worker": worker, "packet": packet_path, "lease": record,
                "requested_runtime": requested_runtime}

    def task_integrate(self, tid: str, commit: str) -> dict:
        self.guard_source_write()
        self.frozen()
        clean(self.root)
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            raise RddError("Integration requires a complete commit SHA")
        task, state = self.task(tid), self.state()
        pid = self.active(state)
        record = state["tasks"][tid]
        if task["phase"] != pid or record["status"] != "claimed":
            raise RddError("Task must have an active lease in the current phase")
        if record["lease_expires"] < time.time():
            raise RddError("Lease expired. Resume/release preserves work; claim a fresh attempt before integrating.", "budget")
        self.guard_task_order(state, task)
        self.live_review_guard(final=False, stage="implementation", task=tid,
            repair_findings=self.task_repair_authorization(state, tid))
        base = record["base_commit"]
        if git(self.root, "merge-base", base, commit) != base:
            raise RddError("Submitted commit is not descended from the leased base")
        commits = git(self.root, "rev-list", "--reverse", f"{base}..{commit}").splitlines()
        if not commits:
            raise RddError("Task submission contains no commit")
        if git(self.root, "merge-base", "HEAD", commit) == commit:
            raise RddError("Worker submission is already on the coordinator branch. Implement in the leased isolated worktree; preserve and inspect the current commits before retrying.")
        merges = git(self.root, "rev-list", "--merges", f"{base}..{commit}")
        if merges:
            raise RddError("Worker submissions must be a linear commit sequence")
        changed = [p for p in git(self.root, "diff", "--name-only", "--no-renames", "-z", base, commit).split("\0") if p]
        if not changed or not set(changed) <= set(task["writes"]):
            raise RddError(f"Submission changed paths outside its lease: {sorted(set(changed)-set(task['writes']))}")
        for p in changed:
            if artifacts.protected(p, self.config, self.spec()):
                raise RddError("Worker changed a frozen contract or harness policy", "specification")
        if record["worktree"]:
            worker_root = safe_path(self.root, record["worktree"])
            require_source_branch(worker_root, record["branch"])
            clean(worker_root)
            if head(worker_root) != commit:
                raise RddError("Worktree HEAD differs from submitted commit")
            projection_state = copy.deepcopy(state)
            plan = self.plan()
            # A parallel lease retains packets committed at its own base, even
            # after the coordinator completes and cleans up another task.
            for peer in plan["tasks"]:
                if projection_state["tasks"][peer["id"]]["status"] == "done" and any(
                        artifacts.marker_line(peer, site, plan) in
                        git(self.root, "show", f"{base}:{artifacts.site_path(peer, site)}", check=False).splitlines()
                        for site in artifacts.task_sites(peer)):
                    projection_state["tasks"][peer["id"]]["status"] = "integrated"
            projection_state["tasks"][tid]["status"] = "integrated"
            artifacts.anchors_verify(worker_root, plan, projection_state)
        record["integration"] = {"before": head(self.root), "submission": commit, "commits": commits, "status": "pending"}
        event(state, "integration_started", task=tid, submission=commit)
        self.save(state)  # Intent precedes the external side effect; resume reconciles interruptions.
        try:
            git(self.root, "cherry-pick", *commits)
        except RddError as exc:
            self.block("environment", "Integration conflict/interruption for " + tid + ": " + str(exc))
            raise
        state = self.state()
        record = state["tasks"][tid]
        record.update(status="integrated", commit=head(self.root), lease_expires=None)
        record["integration"]["status"] = "complete"
        record["submission"] = commit
        self.invalidate(state, pid)
        event(state, "task_integrated", task=tid, commit=record["commit"])
        self.save(state)
        self.frozen()
        artifacts.anchors_verify(self.root, self.plan(), state)
        return {"task": tid, "status": "integrated", "commit": record["commit"],
                "next": "Record behavioral RED for test tasks, then task complete. Completion has no review gate."}

    def check(self, cid: str, expectation: str = "pass", tid: str | None = None) -> dict:
        self.guard_v2()
        self.guard_run_policy()
        clean(self.root)
        state, spec = self.state(), self.spec()
        checks = artifacts.unique(spec["checks"], "check")
        if cid not in checks:
            raise RddError("Unknown frozen check")
        if state["status"] == "specification":
            self.spec_validate()
            if cid not in self.stage_check_ids("specification") or expectation != "pass" or tid:
                raise RddError("Before freeze, only declared contract/native qualification checks may run; no implementation task exists yet")
            pid, spec_id, plan_id = None, self.spec_candidate_lock()["digest"], None
        elif state["status"] in {"specified", "planned", "preparing", "prepared"}:
            stage = "plan" if state["status"] == "specified" else "preparation"
            if cid not in self.stage_check_ids(stage) or expectation != "pass" or tid:
                raise RddError("Before implementation only qualification/readiness evidence may run")
            candidate = self.stage_candidate(stage)
            pid, spec_id, plan_id = None, candidate["spec_digest"], candidate["plan_digest"]
        else:
            self.frozen()
            pid, spec_id, plan_id = self.active(state), state["spec_digest"], state["plan_digest"]
        if tid:
            task = self.task(tid)
            if task["phase"] != pid or cid not in task["checks"] or state["tasks"][tid]["status"] != "integrated":
                raise RddError("Task evidence must target an integrated current-phase task and its frozen check")
        if expectation == "fail" and (not tid or self.task(tid)["category"] != "tests"):
            raise RddError("Behavioral RED belongs to the integrated tests task")
        evidence = execute_check(self.root, checks[cid], phase=pid, task_id=tid, expectation=expectation,
                                spec_digest=spec_id, plan_digest=plan_id)
        with self.store.edit(state["id"]) as latest:
            latest["checks"][evidence["id"]] = evidence
            if tid:
                latest["tasks"][tid]["evidence"].append(evidence["id"])
            event(latest, "check_finished", check=cid, outcome=evidence["outcome"], evidence=evidence["id"])
        return evidence

    def check_import(self, file: Path, local_host: bool = False) -> dict:
        self.guard_v2()
        self.guard_run_policy()
        clean(self.root)
        state, evidence = self.state(), read_json(file)
        validate_artifact(self.root, "evidence", evidence)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", evidence["id"]):
            raise RddError("Evidence ID must be a safe filename identifier")
        checks = artifacts.unique(self.spec()["checks"], "check")
        if evidence["check_id"] not in checks:
            raise RddError("Imported receipt references unknown check")
        if state["status"] == "specification":
            self.spec_validate()
            if evidence["check_id"] not in self.stage_check_ids("specification"):
                raise RddError("Before freeze, imported evidence must qualify a declared contract/native check")
            pid, spec_id, plan_id = None, self.spec_candidate_lock()["digest"], None
        elif state["status"] in {"specified", "preparing", "prepared"}:
            stage = "plan" if state["status"] == "specified" else "preparation"
            if evidence["check_id"] not in self.stage_check_ids(stage):
                raise RddError("Imported preimplementation evidence must qualify declared readiness")
            candidate = self.stage_candidate(stage)
            pid, spec_id, plan_id = None, candidate["spec_digest"], candidate["plan_digest"]
        else:
            self.frozen()
            pid, spec_id, plan_id = self.active(state), state["spec_digest"], state["plan_digest"]
        if evidence["phase"] not in {None, pid}:
            raise RddError("Imported evidence is for a different phase")
        if evidence["origin"] == "local" and not local_host:
            raise RddError("A receipt transferred from another local/native host requires --local-host and its actual raw log; otherwise execute the check here")
        verify_receipt(self.root, evidence, checks[evidence["check_id"]], commit=head(self.root),
                       sources=source_digest(self.root), spec_digest=spec_id, plan_digest=plan_id)
        previous = state["checks"].get(evidence["id"])
        if previous is not None and previous != evidence:
            raise RddError("Evidence IDs are immutable; a changed receipt needs a new ID")
        state["checks"][evidence["id"]] = evidence
        write_json(self.root / f".rdd/evidence/checks/{evidence['id']}.json", evidence)
        event(state, "external_receipt_imported", evidence=evidence["id"], provenance=evidence["provenance"], local_host_transfer=local_host)
        self.save(state)
        return {"status": "imported", "evidence": evidence["id"], "trust": "Explicit provenance assertion; hashes establish identity, not remote attestation."}

    def task_complete(self, tid: str, evidence_id: str | None = None) -> dict:
        self.guard_source_write()
        self.frozen()
        clean(self.root)
        state, task = self.state(), self.task(tid)
        pid = self.active(state)
        record = state["tasks"][tid]
        if task["phase"] != pid or record["status"] != "integrated":
            raise RddError("Only an integrated task in the open phase can complete")
        self.guard_task_order(state, task)
        self.live_review_guard(final=False, stage="implementation", task=tid,
            repair_findings=self.task_repair_authorization(state, tid))
        if task["category"] == "tests":
            ids = [evidence_id] if evidence_id else record["evidence"]
            evidence = [state["checks"][eid] for eid in ids if eid in state["checks"]]
            checks = artifacts.unique(self.spec()["checks"], "check")
            valid = []
            for receipt in evidence:
                if receipt["task_id"] == tid and receipt["outcome"] == "red" and receipt["expectation"] == "fail":
                    verify_receipt(self.root, receipt, checks[receipt["check_id"]], commit=head(self.root),
                                   sources=source_digest(self.root), spec_digest=state["spec_digest"],
                                   plan_digest=state["plan_digest"], require_pass=False)
                    valid.append(receipt["id"])
            if not valid:
                raise RddError("Test task completion needs current behavioral RED evidence, not a compile failure or a green test")
            record["red_evidence"] = valid
        artifacts.anchors_verify(self.root, self.plan(), state)
        record.update(status="done", completed_at=now())
        self.invalidate(state, pid)
        event(state, "task_completed", task=tid, submission=record.get("submission"))
        self.save(state)  # Anchor cleanup is a recoverable projection, never the authority.
        artifacts.remove_anchor(self.root, task, self.plan())
        return {"task": tid, "status": "done", "next": "Commit the controller's marker cleanup before claiming or integrating more work."}

    def task_release(self, tid: str, reason: str) -> dict:
        self.guard_run_policy()
        state, task = self.state(allow_blocked=True), self.task(tid)
        if task["phase"] != state["active_phase"] or state["tasks"][tid]["status"] not in {"claimed", "integrated"}:
            raise RddError("Only active claimed/integrated work can be released")
        record = state["tasks"][tid]
        if record["status"] == "integrated":
            raise RddError("Integrated work must complete or be repaired in place; release does not undo commits")
        event(state, "task_released", task=tid, reason=reason, preserved_worktree=record["worktree"])
        record.update(status="todo", lease_expires=None)
        self.save(state)
        return {"task": tid, "status": "todo", "preserved_worktree": record["worktree"]}

    def task_reopen(self, tid: str, reason: str) -> dict:
        self.guard_source_write()
        self.frozen()
        state, task = self.state(), self.task(tid)
        pid = self.active(state)
        if task["phase"] != pid or state["phases"][task["phase"]]["status"] == "sealed":
            raise RddError("A sealed phase cannot be reopened; start a specification amendment", "closure")
        record = state["tasks"][tid]
        self.validate_review_stream(state)
        cursor = len(state.get("live_reviews", []))
        ids = self.task_findings_at(state, tid, cursor)
        if record["status"] != "done" and (not record["attempts"] or not ids):
            raise RddError("In-progress repair requires a prior attempt and unresolved task-scoped findings", "review")
        for peer_id, peer in state["tasks"].items():
            if peer_id == tid or peer["status"] not in {"claimed", "integrated"}:
                continue
            peer_task = self.task(peer_id)
            if record["status"] == "done" or (peer_task["phase"], peer_task["category"]) != (pid, task["category"]):
                raise RddError("Finish or release live work before starting a repair sweep")
        self.live_review_guard(final=False, stage="implementation", task=tid, repair_findings=frozenset(ids))
        from_status = record["status"]
        if record["status"] != "claimed":
            record.update(status="todo", evidence=[], lease_expires=None)
            record.pop("red_evidence", None)
        record["repair_findings"] = ids
        self.invalidate(state, pid)
        event(state, "open_phase_repair", task=tid, reason=reason, finding_ids=ids, review_cursor=cursor, from_status=from_status)
        if record["status"] == "todo":
            artifacts.materialize(self.root, self.plan(), state, create_shells=False,
                                  repair_tasks=self.repair_projection_tasks(state), preflight=True)
        self.save(state)
        if record["status"] == "todo":
            self.anchors_reconcile()
        return {"task": tid, "status": record["status"], "finding_ids": ids,
                "scope": "Existing frozen task only; repair selection obeys the same category order."}

    def repair_projection_tasks(self, state: dict) -> frozenset[str]:
        repairs = {e["task"]: e for e in state["events"] if e["action"] == "open_phase_repair"}
        tasks = frozenset(tid for tid, entry in repairs.items()
                          if entry.get("from_status") == "done" and state["tasks"][tid]["status"] == "todo")
        for tid in tasks:
            self.task_repair_authorization(state, tid)
        return tasks

    def anchors_reconcile(self) -> dict:
        self.guard_source_write()
        self.frozen()
        state, plan = self.state(), self.plan()
        for task in plan["tasks"]:
            if state["tasks"][task["id"]]["status"] == "done":
                artifacts.remove_anchor(self.root, task, plan)
        artifacts.materialize(self.root, plan, state, create_shells=False, repair_tasks=self.repair_projection_tasks(state))
        return artifacts.anchors_verify(self.root, plan, state)

    def anchors_verify(self) -> dict:
        self.frozen()
        return artifacts.anchors_verify(self.root, self.plan(), self.state())

    def cumulative_checks(self, phase: str) -> list[str]:
        ids = set(self.spec()["contract_check_ids"])
        for row in self.plan()["phases"]:
            ids.update(row["checks"])
            if row["id"] == phase:
                return sorted(ids)
        raise RddError("Unknown phase")

    def ensure_checks(self, state: dict, ids: list[str], *, candidate_spec_digest: str | None = None, candidate_plan_digest: str | None = None) -> list[dict]:
        self.guard_run_policy(state)
        checks = artifacts.unique(self.spec()["checks"], "check")
        spec_id = candidate_spec_digest or state["spec_digest"]
        plan_id = candidate_plan_digest if candidate_spec_digest else state["plan_digest"]
        commit, sources = head(self.root), source_digest(self.root)
        local = platform_name()
        accepted, missing = [], []
        for cid in ids:
            check = checks[cid]
            environments = {e["id"]: e for e in self.spec().get("environments", [])}
            platforms = sorted({environments[e]["platform"] for e in check.get("environments", [])}) or (["any"] if "any" in check["platforms"] else check["platforms"])
            for platform in platforms:
                receipt = None
                candidates = sorted(state["checks"].values(), key=lambda r: (r["origin"] == "ci", r["finished_at"], r["id"]), reverse=True)
                for candidate in candidates:
                    if candidate["check_id"] != cid or (platform != "any" and candidate["platform"] != platform):
                        continue
                    try:
                        verify_receipt(self.root, candidate, check, commit=commit, sources=sources,
                                       spec_digest=spec_id, plan_digest=plan_id)
                        receipt = candidate
                        break
                    except RddError:
                        continue
                if receipt is None and platform in {"any", local} and check["kind"] != "manual":
                    try:
                        receipt = execute_check(self.root, check, phase=state["active_phase"], task_id=None,
                                                expectation="pass", spec_digest=spec_id, plan_digest=plan_id)
                        state["checks"][receipt["id"]] = receipt
                        self.save(state)
                        if receipt["outcome"] != "pass":
                            raise RddError(f"Check {cid} failed. Read {receipt['log_path']}")
                    except RddStorageError:
                        raise
                    except RddError as exc:
                        if getattr(exc, "rdd_storage_error", None) is not None:
                            raise
                        if exc.kind != "environment":
                            raise
                        missing.append({"check": cid, "platform": platform, "reason": str(exc)})
                        continue
                if receipt is None:
                    missing.append({"check": cid, "platform": platform,
                                    "reason": "Import exact-source CI/manual evidence from its actual qualified platform"})
                else:
                    accepted.append(receipt)
        if missing:
            raise RddError("Missing verification evidence: " + json.dumps(missing), "environment")
        if head(self.root) != commit or source_digest(self.root) != sources:
            raise RddError("Source changed while verifying; rerun checks and independent review")
        return accepted

    def review_record(self, file: Path) -> dict:
        self.guard_run_policy()
        if read_json(file).get("kind") == "live":
            return self.review_live_record(file)
        if "stage" in read_json(file):
            return self.stage_review_record(file)
        self.frozen()
        clean(self.root)
        state, review = self.state(), read_json(file)
        validate_artifact(self.root, "review", review)
        pid = self.active(state)
        self.live_review_guard(final=True, cursor=review["review_cursor"], stage="implementation")
        if review["phase"] != pid or review["source_commit"] != head(self.root) or review["source_digest"] != source_digest(self.root):
            raise RddError("Review does not cover the exact current phase/source revision")
        if review["reviewer"] != "rdd_reviewer" or review["model"] != self.profile_settings("rdd_reviewer")["model"]:
            raise RddError("Final phase review must use the configured independent reviewer role/model")
        worker_sessions = {t["session_id"] for t in state["tasks"].values() if t["session_id"]}
        worker_sessions.update(s for authors in state.get("authors", {}).values() for s in authors)
        if not review["session_id"] or review["session_id"] in worker_sessions:
            raise RddError("Reviewer session must be distinct from implementor sessions")
        if not set(self.cumulative_checks(pid)) <= set(review["checks_reviewed"]):
            raise RddError("Review omits cumulative phase verification obligations")
        known_reqs = {r["requirement"] for r in self.spec()["requirement_map"]}
        for finding in review["findings"]:
            artifacts.subset(finding["requirements"], known_reqs, "review finding requirements")
            artifacts.subset(finding["tasks"], state["tasks"], "review finding tasks")
            if finding["path"]:
                safe_path(self.root, finding["path"])
        state["reviews"][pid] = review
        state["phases"][pid]["review"] = digest(review)
        state["phases"][pid]["gate"] = None
        path = f".rdd/evidence/reviews/{pid}-{review['source_commit']}.json"
        write_json(self.root / path, review)
        event(state, "phase_review_recorded", phase=pid, decision=review["decision"], session=review["session_id"])
        self.save(state)
        self.record_final_findings(review, "implementation", pid)
        return {"phase": pid, "decision": review["decision"], "review_path": path}

    def current_review(self, state: dict, phase: str, commit: str, sources: str) -> dict:
        review = state["reviews"].get(phase)
        if not review or review["source_commit"] != commit or review["source_digest"] != sources:
            raise RddError("An exact-current-source independent phase review is required", "review")
        if state["phases"][phase]["status"] == "sealed":
            self.validate_review_cursor(state, review["review_cursor"], "implementation", phase, commit, sources)
        else:
            self.live_review_guard(final=True, cursor=review["review_cursor"], stage="implementation")
        if review["decision"] != "pass" or any(f["severity"] in {"blocking", "high", "medium"} for f in review["findings"]):
            raise RddError("Independent review has unresolved blocking/high/medium findings", "review")
        return review

    def phase_scope(self, state: dict, phase: str) -> None:
        plan = self.plan()
        row = next(p for p in plan["phases"] if p["id"] == phase)
        tasks = [self.task(tid) for tid in row["tasks"]]
        allowed = {p for t in tasks for p in t["writes"]}
        allowed.update(p for t in tasks for p in artifacts.anchor_paths(t))
        base = state["phases"][phase]["start_sha"]
        changed = {p for p in git(self.root, "diff", "--name-only", "--no-renames", "-z", base, "HEAD").split("\0") if p}
        if not changed <= allowed:
            raise RddError("Phase changed unplanned paths: " + ", ".join(sorted(changed - allowed)), "planning")
        for rel in row["deliverables"]:
            path = safe_path(self.root, rel)
            deletion = any(t["category"] == "deletion" and rel in t["writes"] for t in tasks)
            if not path.exists():
                if deletion:
                    continue
                raise RddError(f"Phase deliverable is missing: {rel}")
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = None
                if content is not None and artifacts.shell_is_empty(rel, content):
                    raise RddError(f"Phase deliverable is still an empty/comment-only shell: {rel}")

    def gate_phase(self, phase: str) -> dict:
        self.frozen()
        clean(self.root)
        state = self.state()
        if self.active(state) != phase:
            raise RddError("Only the active phase can be gated")
        tasks = [t for t in self.plan()["tasks"] if t["phase"] == phase]
        if any(state["tasks"][t["id"]]["status"] != "done" for t in tasks):
            raise RddError("Every task in the phase must be complete before its review gate")
        self.anchors_verify()
        self.phase_scope(state, phase)
        commit, sources = head(self.root), source_digest(self.root)
        review = self.current_review(state, phase, commit, sources)
        receipts = self.ensure_checks(state, self.cumulative_checks(phase))
        self.frozen()
        report = {"schema_version": 1, "phase": phase, "status": "passed", "source_commit": commit,
                  "source_digest": sources, "spec_digest": state["spec_digest"], "plan_digest": state["plan_digest"],
                  "review_digest": digest(review), "evidence": [r["id"] for r in receipts],
                  "requirements_closed": next(p for p in self.plan()["phases"] if p["id"] == phase)["requirements_closed"],
                  "created_at": now()}
        write_json(self.root / f".rdd/evidence/phases/{phase}-gate.json", report)
        state["phases"][phase].update(status="gated", gate=report, head=commit)
        event(state, "phase_gate_passed", phase=phase, source_commit=commit)
        self.save(state)
        return report

    def gate_current(self, state: dict, phase: str) -> dict:
        gate = state["phases"][phase].get("gate")
        if not gate or gate["source_commit"] != head(self.root) or gate["source_digest"] != source_digest(self.root):
            raise RddError("Phase gate is absent or stale; run exact-source checks and review again")
        return gate

    def stack_publish(self, phase: str) -> dict:
        self.frozen()
        clean(self.root)
        state = self.state()
        if self.active(state) != phase:
            raise RddError("Publish only the active gated phase")
        gate = self.gate_current(state, phase)
        p = state["phases"][phase]
        row = next(p for p in self.plan()["phases"] if p["id"] == phase)
        body = "\n".join([f"## {phase}: {row['goal']}", "", "### Requirement coverage", "",
                           ", ".join(row["requirements_closed"]) or "Foundational dependencies; later phases close the requirements.",
                           "", "### Behavior and validation", "", *["- " + t["title"] for t in self.plan()["tasks"] if t["phase"] == phase],
                           "", f"Accepted source: `{gate['source_commit']}`.", f"Specification: `{state['spec_digest']}`.",
                           f"Plan: `{state['plan_digest']}`.", "", "Cumulative checks: " + ", ".join(self.cumulative_checks(phase)),
                           "", "The local run export contains raw check logs, metrics and independent review. CI publishes its separate exact-source artifacts.",
                           "", "This phase is ready only when required CI checks and independent review pass at this exact revision.", ""])
        body_path = self.root / f".rdd/runtime/prs/{phase}.md"
        atomic_write(body_path, body.encode())
        result = GitHubAdapter(self.root).publish_phase_pr(state["id"], int(phase[1:]), p["base_branch"], body_path,
                      title=f"RDD {phase}: {row['goal'][:180]}", remote=self.config["github"]["remote"], expected_base_sha=p["base_sha"])
        p["pr"] = result
        event(state, "phase_pr_published", phase=phase, pr=result)
        self.save(state)
        return result

    def phase_pr_status(self, state: dict, phase: str) -> dict:
        p = state["phases"][phase]
        if not p.get("pr") or not p.get("head"):
            raise RddError(f"Phase {phase} has no published gated PR")
        review = self.current_review(state, phase, p["head"], p["gate"]["source_digest"])
        number = p["pr"].get("number")
        if not number:
            raise RddError("PR publication did not return its number")
        return GitHubAdapter(self.root).phase_status(int(number), p["head"], p["base_branch"],
                self.config["github"]["required_checks"], expected_base_sha=p["base_sha"], expected_head_branch=p["branch"],
                review_evidence={"passed": True, "head_sha": p["head"], "reviewer": review["reviewer"], "findings": []},
                require_github_approval=self.config["github"]["require_approval"])

    def stack_verify(self) -> dict:
        self.frozen()
        state = self.state()
        result = []
        for phase, row in state["phases"].items():
            if row.get("pr"):
                if head_ref(self.root, row["branch"]) != row["head"]:
                    raise RddError(f"Published/sealed local branch moved: {phase}", "closure")
                result.append({"phase": phase, **self.phase_pr_status(state, phase)})
        passed = bool(result) and all(r["ready"] for r in result)
        return {"ready": passed, "completion_policy": "ready", "pull_requests": result,
                "pending_phases": [p for p, row in state["phases"].items() if not row.get("pr")]}

    def phase_seal(self, phase: str) -> dict:
        self.frozen()
        clean(self.root)
        state = self.state()
        if self.active(state) != phase:
            raise RddError("Only the active phase can close")
        gate = self.gate_current(state, phase)
        status = self.phase_pr_status(state, phase)
        if not status["ready"]:
            raise RddError("Phase PR is not ready: " + json.dumps(status["blockers"]), "review")
        seal = {"schema_version": 1, "phase": phase, "source_commit": gate["source_commit"],
                "source_digest": gate["source_digest"], "gate_digest": digest(gate), "pr": status, "sealed_at": now()}
        write_json(self.root / f".rdd/evidence/phases/{phase}-seal.json", seal)
        state["phases"][phase].update(status="sealed", seal=seal)
        state["active_phase"] = None
        event(state, "phase_sealed", phase=phase, commit=gate["source_commit"])
        self.save(state)
        return {"phase": phase, "status": "sealed", "source_commit": gate["source_commit"],
                "next": "Begin the next phase, or run gate project if every phase is sealed."}

    def gate_project(self) -> dict:
        self.frozen()
        clean(self.root)
        state, plan, spec = self.state(), self.plan(), self.spec()
        self.validate_review_stream(state)
        if any(not row["resolution"] for row in state.get("live_findings", {}).values()):
            raise RddError("Independent live findings remain unresolved", "review")
        if not state["phases"] or any(p["status"] != "sealed" for p in state["phases"].values()):
            raise RddError("Every phase must be sealed before project completion")
        if any(t["status"] != "done" for t in state["tasks"].values()):
            raise RddError("Some canonical tasks remain unfinished")
        if self.anchors_verify()["remaining"]:
            raise RddError("Inline/sidecar tasks remain")
        final = list(state["phases"])[-1]
        if head(self.root) != state["phases"][final]["head"]:
            raise RddError("Checkout must be at the final sealed phase revision", "closure")
        self.gate_current(state, final)
        receipts = self.ensure_checks(state, sorted(set(spec["project_check_ids"] + self.cumulative_checks(final))))
        stack = self.stack_verify()
        if not stack["ready"] or stack["pending_phases"]:
            raise RddError("The complete stack is not currently ready: " + json.dumps(stack), "review")
        report = {"schema_version": 1, "status": "passed", "application_complete": True,
                  "run_id": state["id"], "source_commit": head(self.root), "source_digest": source_digest(self.root),
                  "requirements_digest": state["requirements_digest"], "spec_digest": state["spec_digest"],
                  "plan_digest": state["plan_digest"], "prepared_digest": state["prepared_digest"],
                  "requirements": spec["requirement_map"], "tasks_completed": len(plan["tasks"]),
                  "remaining_anchors": 0, "phases": state["phases"], "stack": stack,
                  "evidence": receipts, "reviews": state["reviews"], "created_at": now(),
                  "completion_policy": "All phase PRs open, non-draft, exact-head reviewed and required checks successful; merging is separate.",
                  "trust_boundary": "Local controller and imported observers are trusted; hashes bind identity, not truthfulness. See security-model.md."}
        observed = {sid: receipt["id"] for receipt in receipts
                    for sid in next(c for c in spec["checks"] if c["id"] == receipt["check_id"]).get("scenario_ids", [])}
        golden = {s["id"] for s in spec["scenarios"] if s["kind"] == "golden"}
        if not golden <= observed.keys():
            raise RddError("Project lacks actual passing evidence for every golden scenario", "closure")
        report["golden_results"] = {sid: observed[sid] for sid in sorted(golden)}
        write_json(self.root / ".rdd/evidence/project-validation.json", report)
        md = ["# Project validation", "", f"Run `{state['id']}` passed the frozen project obligations.", "",
              f"Accepted Git revision: `{report['source_commit']}`.", f"Source digest: `{report['source_digest']}`.", "",
              f"Requirements covered: {len(spec['requirement_map'])}. Tasks complete: {len(plan['tasks'])}. Remaining task anchors: 0.",
              "", "## Pull request stack", "", "| Phase | PR | Revision |", "| --- | --- | --- |"]
        for item in stack["pull_requests"]:
            phase = item["phase"]
            md.append(f"| {phase} | {item.get('url', state['phases'][phase]['pr'].get('url', 'See JSON'))} | {state['phases'][phase]['head']} |")
        md += ["", "## Evidence", "", "The JSON report contains exact-source check receipts, raw-log references, metrics, requirement mapping and review identities.",
               "", "PRs are ready for the developer's merge procedure. No merge or release is implied by this report.", ""]
        atomic_write(self.root / ".rdd/evidence/project-validation.md", "\n".join(md).encode())
        state.update(status="complete", project_validation={"path": ".rdd/evidence/project-validation.json", "digest": digest(report)})
        event(state, "project_validated", commit=report["source_commit"])
        self.save(state)
        self.export_run(self.root / ".rdd/evidence/completed-run.json")
        return {"status": "passed", "application_complete": True, "run_id": state["id"],
                "report": ".rdd/evidence/project-validation.json", "readable_report": ".rdd/evidence/project-validation.md",
                "checkpoint": ".rdd/evidence/completed-run.json", "source_commit": report["source_commit"]}

    def block(self, kind: str, reason: str, *, affected: dict | None = None, evidence: list[str] | None = None) -> dict:
        self.guard_run_policy()
        state = self.state(allow_blocked=True)
        blocker = {"schema_version": 1, "run_id": state["id"], "kind": kind, "reason": reason,
                   "created_at": now(), "resolved": False}
        status = state.get("resume_status") if state["status"] == "blocked" else state["status"]
        detection = "implementation" if status in {"implementation", "complete"} else "preparation"
        escaped = (kind in {"specification", "planning"} and detection == "implementation") or (
            kind == "specification" and status in {"specified", "planned", "preparing", "prepared"})
        if escaped:
            blocker["escape"] = {"severity": "critical", "detected_stage": detection,
                "origin_stage": "preparation" if kind == "planning" else kind, "source_commit": head(self.root), "source_digest": source_digest(self.root),
                "spec_digest": state.get("spec_digest"), "plan_digest": state.get("plan_digest"),
                "affected": affected or {"requirements": [], "elements": [], "tasks": []},
                "evidence": evidence or [], "diagnostic": reason}
            validate_artifact(self.root, "blocker", blocker)
            known = {"requirements": {r["requirement"] for r in self.spec()["requirement_map"]},
                     "elements": {e["id"] for e in self.spec()["solution_elements"]}, "tasks": set(state["tasks"])}
            for field, ids in blocker["escape"]["affected"].items():
                artifacts.subset(ids, known[field], f"escaped defect affected {field}")
            path = f".rdd/evidence/escapes/{uuid.uuid4().hex}.json"
            write_json(self.root / path, blocker["escape"])
            blocker["escape"]["evidence"] = list(blocker["escape"]["evidence"]) + [path]
        validate_artifact(self.root, "blocker", blocker)
        if state["status"] != "blocked":
            state["resume_status"] = state["status"]
        state["status"] = "blocked"
        state["blockers"].append(blocker)
        event(state, "blocked", kind=kind, reason=reason)
        write_json(self.root / ".rdd/evidence/blocker.json", blocker)
        self.save(state)
        return {"status": "blocked", "blocker": blocker,
                "next": ("Critical upstream harness regression: preserve this run, reproduce the escaped defect, repair its preventive control and start a fresh reviewed baseline."
                         if escaped else "Return to specification for authority/closure issues; fix external environment then resume for environment/review issues.")}

    def guard_export(self, path: Path) -> None:
        """Source-visible export destinations need the same branch preflight."""
        if path.resolve().is_relative_to(self.root):
            rel = path.resolve().relative_to(self.root).as_posix()
            if not rel.startswith(EXCLUDED_PREFIXES) and rel not in EXCLUDED_FILES:
                self.guard_source_write()

    def export_run(self, path: Path) -> dict:
        self.guard_export(path)
        state = self.state(allow_blocked=True)
        if state.get("workflow_graph_digest") == digest(NODES):
            validate_refinement(self.root, state, self.config)
        evidence = {}
        for receipt in state["checks"].values():
            log = safe_path(self.root, receipt["log_path"], allow_missing=False)
            if file_hash(log) != receipt["log_digest"]:
                raise RddError("Cannot export a run with changed evidence logs")
            if log.stat().st_size > 16 * 1024 * 1024:
                raise RddError("One evidence log exceeds the 16 MiB export budget", "budget")
            evidence[receipt["log_path"]] = log.read_text(encoding="utf-8")
        reports = [".rdd/evidence/project-validation.json", ".rdd/evidence/project-validation.md"]
        reports.extend(row["path"] for row in state.get("preparation_gate", {}).get("ci_runs", {}).values())
        for rel in reports:
            if (self.root / rel).is_file():
                evidence[rel] = (self.root / rel).read_text(encoding="utf-8")
        checkpoint = {"schema_version": 1, "source_commit": head(self.root), "source_digest": source_digest(self.root),
                      "state": state, "evidence": evidence,
                      "baseline": {"spec_digest": state.get("spec_digest"), "plan_digest": state.get("plan_digest"),
                                   "prepared_digest": state.get("prepared_digest")}}
        validate_artifact(self.root, "checkpoint", checkpoint)
        if len(json.dumps(checkpoint)) > 128 * 1024 * 1024:
            raise RddError("Run export exceeds 128 MiB; retain the local evidence directory and split raw datasets outside log receipts", "budget")
        write_json(path, checkpoint)
        return {"path": str(path), "run_id": state["id"], "sha256": file_hash(path),
                "contains": "Run state, raw check logs and final reports; source and frozen baseline remain in Git."}

    def guard_resume(self, file: Path | None = None) -> dict | None:
        """Bound and validate checkpoint identity before runtime/lock creation."""
        require_source_branch(self.root)
        if not file:
            self.guard_source_write()
            return None
        if file.stat().st_size > 128 * 1024 * 1024:
            raise RddError("Checkpoint exceeds import size budget", "budget")
        self.guard_run_policy()
        checkpoint = read_json(file)
        validate_artifact(self.root, "checkpoint", checkpoint)
        self.guard_source_write(checkpoint["state"])
        return checkpoint

    def resume(self, file: Path | None = None) -> dict:
        checkpoint = self.guard_resume(file)
        if file:
            clean(self.root)
            if checkpoint["source_commit"] != head(self.root) or checkpoint["source_digest"] != source_digest(self.root):
                raise RddError("Checkout must match the checkpoint's exact commit and source digest before restoring")
            state = checkpoint["state"]
            self.validate_checkpoint_state(state, checkpoint)
            # Validate every destination and hash before writing any imported evidence.
            for rel, content in checkpoint["evidence"].items():
                if not isinstance(content, str) or not rel.startswith(".rdd/evidence/"):
                    raise RddError("Checkpoint evidence has an unsafe path or nontext content")
                safe_path(self.root, rel)
            for receipt in state["checks"].values():
                content = checkpoint["evidence"].get(receipt["log_path"])
                if content is None:
                    raise RddError("Checkpoint lacks a referenced evidence log")
                import hashlib
                if hashlib.sha256(content.encode()).hexdigest() != receipt["log_digest"]:
                    raise RddError("Checkpoint evidence log digest mismatch")
            for rel, content in checkpoint["evidence"].items():
                atomic_write(safe_path(self.root, rel), content.encode())
            self.save(state)
        state = self.state(allow_blocked=True)
        validate_refinement(self.root, state, self.config)
        self.validate_workflow_checkpoint(state)
        permanent = [b for b in state["blockers"] if not b["resolved"] and b["kind"] not in {"environment", "review"}]
        if permanent:
            raise RddError("This run has authority, phase-closure, or budget blockers. Preserve the evidence and start the specification workflow for a new amendment/regenerate run.", permanent[0]["kind"])
        if git(self.root, "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD", check=False):
            raise RddError("An interrupted cherry-pick remains. Resolve its conflicts and continue it, or explicitly abort it, before resume.", "environment")
        for blocker in state["blockers"]:
            if not blocker["resolved"]:
                blocker["resolved"] = True
        if state["status"] == "blocked":
            state["status"] = state.pop("resume_status", "implementation")
        for tid, record in state["tasks"].items():
            intent = record.get("integration", {})
            if intent.get("status") == "pending":
                current = head(self.root)
                if current == intent["before"]:
                    record.pop("integration", None)
                else:
                    changed = {p for p in git(self.root, "diff", "--name-only", "--no-renames", "-z", intent["before"], "HEAD").split("\0") if p}
                    expected = set(self.task(tid)["writes"])
                    same = not git(self.root, "diff", "--name-only", intent["submission"], "HEAD", "--", *sorted(expected))
                    if not changed <= expected or not same:
                        raise RddError("Interrupted integration cannot be reconciled to the leased submission. Preserve all commits and inspect the diff.", "environment")
                    record.update(status="integrated", commit=current, submission=intent["submission"], lease_expires=None)
                    intent["status"] = "complete"
                    event(state, "integration_recovered", task=tid, commit=current)
            if record["status"] == "claimed" and record["lease_expires"] < time.time():
                record.update(status="todo", lease_expires=None)
                event(state, "lease_expired", task=tid, preserved_worktree=record["worktree"])
        event(state, "resumed")
        self.save(state)
        if state.get("spec_digest"):
            self.frozen(planned=bool(state.get("plan_digest")))
        if state.get("prepared_digest"):
            self.anchors_reconcile()
        return self.status()

    def validate_checkpoint_state(self, state: dict, checkpoint: dict) -> None:
        self.guard_run_policy(state)
        required = {"id", "mode", "status", "tasks", "phases", "checks", "reviews", "blockers", "events",
                    "requirements_digest", "policy_inventory", "active_phase"}
        if not isinstance(state, dict) or not required <= state.keys():
            raise RddError("Checkpoint run record is incomplete")
        validate_refinement(self.root, state, self.config)
        if state.get("spec_digest"):
            self.require_refinement(state)
        self.validate_stage_checkpoint(state, checkpoint)
        self.validate_review_stream(state)
        self.validate_workflow_checkpoint(state)
        if not isinstance(state["id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", state["id"]):
            raise RddError("Checkpoint run ID is invalid")
        if state["mode"] not in {"regenerate", "amend"}:
            raise RddError("Checkpoint mode is invalid")
        if state["status"] not in {"specification", "specified", "planned", "preparing", "prepared", "implementation", "blocked", "complete"}:
            raise RddError("Checkpoint run status is invalid")
        if state["requirements_digest"] != file_hash(self.root / self.config["requirements"]):
            raise RddError("Checkpoint requirements differ from repository")
        for field, rel in (("spec_digest", ".rdd/spec.lock.json"), ("plan_digest", ".rdd/plan/plan.lock.json")):
            if state.get(field):
                lock = verify_lock(self.root, rel)
                if lock["digest"] != state[field] or checkpoint["baseline"].get(field) != state[field]:
                    raise RddError("Checkpoint frozen baseline mismatch")
        if state.get("spec_digest") and state["policy_inventory"] != policy_inventory(self.root):
            raise RddError("Checkpoint policy differs from repository")
        if state.get("prepared_digest"):
            prepared = read_json(self.root / ".rdd/prepared.json")
            if (checkpoint["baseline"].get("prepared_digest") != state["prepared_digest"]
                    or prepared.get("digest") != state["prepared_digest"]
                    or prepared["digest"] != digest({k: v for k, v in prepared.items() if k != "digest"})
                    or prepared.get("run_id") != state["id"]
                    or prepared.get("spec_digest") != state.get("spec_digest")
                    or prepared.get("plan_digest") != state.get("plan_digest")):
                raise RddError("Checkpoint preparation baseline mismatch")
            if file_hash(self.root / ".rdd/plan/implementation-matrix.md") != prepared["matrix_digest"]:
                raise RddError("Checkpoint preparation matrix mismatch")
        elif checkpoint["baseline"].get("prepared_digest"):
            raise RddError("Checkpoint has an unexplained preparation identity")
        if state.get("plan_digest"):
            plan = self.plan()
            if set(state["tasks"]) != {t["id"] for t in plan["tasks"]} or set(state["phases"]) != {p["id"] for p in plan["phases"]}:
                raise RddError("Checkpoint task/phase inventory differs from frozen plan")
            for tid, task in state["tasks"].items():
                if (task.get("status") not in {"todo", "claimed", "integrated", "done"}
                        or type(task.get("attempts")) is not int or task["attempts"] < 0):
                    raise RddError("Checkpoint task status is invalid")
                self.task_repair_authorization(state, tid)
                worker = task.get("worker")
                claimed_before = task["attempts"] > 0 or task["status"] != "todo"
                if claimed_before or worker is not None or task.get("requested_runtime") is not None:
                    scope = next(t["scope"] for t in plan["tasks"] if t["id"] == tid)
                    if (worker not in IMPLEMENTOR_SCOPES or scope not in IMPLEMENTOR_SCOPES[worker]
                            or task.get("requested_runtime") != self.profile_settings(worker)):
                        raise RddError("Checkpoint task requested runtime differs from its pinned implementor profile")
                worktree = task.get("worktree")
                if worktree:
                    if not worktree.startswith(".rdd/runtime/worktrees/"):
                        raise RddError("Checkpoint has an unsafe worktree path")
                    safe_path(self.root, worktree)
            for phase, record in state["phases"].items():
                if record.get("status") not in {"pending", "active", "gated", "sealed"}:
                    raise RddError("Checkpoint phase status is invalid")
                if record["status"] == "sealed" and (not record.get("gate") or not record.get("seal") or not record.get("pr")):
                    raise RddError("Checkpoint claims a sealed phase without its gate/seal/PR evidence")
            if state["active_phase"] is not None and state["active_phase"] not in state["phases"]:
                raise RddError("Checkpoint active phase is unknown")
        if state["status"] == "complete":
            if (not state["tasks"] or not state["phases"] or state["active_phase"] is not None
                    or any(t["status"] != "done" for t in state["tasks"].values())
                    or any(p["status"] != "sealed" for p in state["phases"].values())):
                raise RddError("Checkpoint claims completion with unfinished tasks or unsealed phases")
            validation = state.get("project_validation", {})
            path = validation.get("path")
            if path != ".rdd/evidence/project-validation.json" or path not in checkpoint["evidence"]:
                raise RddError("Completed checkpoint lacks its project validation report")
            from .adapters import _strict_json
            report = _strict_json(checkpoint["evidence"][path])
            if (digest(report) != validation.get("digest") or report.get("status") != "passed"
                    or report.get("application_complete") is not True or report.get("run_id") != state["id"]
                    or report.get("source_commit") != checkpoint["source_commit"]
                    or report.get("source_digest") != checkpoint["source_digest"]
                    or report.get("spec_digest") != state.get("spec_digest")
                    or report.get("plan_digest") != state.get("plan_digest")):
                raise RddError("Completed checkpoint project validation identity mismatch")
        for eid, receipt in state["checks"].items():
            validate_artifact(self.root, "evidence", receipt)
            if eid != receipt["id"] or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", eid):
                raise RddError("Checkpoint evidence ID mismatch")
            if not receipt["log_path"].startswith(".rdd/evidence/"):
                raise RddError("Checkpoint receipt has an unsafe log path")
            safe_path(self.root, receipt["log_path"])
        for review in state["reviews"].values():
            validate_artifact(self.root, "review", review)
        for blocker in state["blockers"]:
            validate_artifact(self.root, "blocker", blocker)

    def goal(self) -> str:
        text = (self.root / ".rdd/goals/implementation.txt").read_text(encoding="utf-8").strip()
        if not text or len(text) >= 4000:
            raise RddError("Implementation goal must contain 1-3999 characters")
        return text

    def guard_workflow(self, stage: str, mode: str | None = None, *, print_only: bool = False) -> None:
        """Preflight a workflow before the CLI takes its mutation lock."""
        if print_only and not mode:
            return
        require_source_branch(self.root)
        profile_policy_digest(self.root)
        if stage == "specification":
            locator = read_json(self.root / ".rdd/run.json")
            state = Store.read(self.root, locator["run_id"]) if locator.get("run_id") else None
            if state and (not mode or (state["status"] == "specification" and state["mode"] == mode)):
                self.guard_source_write(state, baseline=True)
        else:
            self.guard_source_write(baseline=stage == "preparation")

    def workflow(self, stage: str, mode: str | None = None, *, print_only: bool = False,
                 permission: str | None = None) -> dict:
        if stage not in {"specification", "preparation", "implementation"}:
            raise RddError("Unknown workflow")
        try:
            validate_native_permission(permission)
        except RddAdapterError as exc:
            raise RddError(str(exc)) from exc
        self.guard_workflow(stage, mode, print_only=print_only)
        if stage == "specification" and mode:
            locator = read_json(self.root / ".rdd/run.json")
            state = Store.read(self.root, locator["run_id"]) if locator.get("run_id") else None
            if not state or state["status"] != "specification" or state["mode"] != mode:
                self.start(mode)
        if stage == "preparation":
            self.frozen(planned=False)
        if stage == "implementation":
            self.frozen()
            if self.state()["status"] not in {"prepared", "implementation", "complete"}:
                raise RddError("Implementation workflow requires completed preparation")
        prompt = (f"Use ${stage}-workflow. Read AGENTS.md first. Work in this repository using ./rdd. "
                  "Requirements are authoritative. Follow domain-boundaries for the accepted S1 inventory, distinct functional module owners and every internal call/type-only binding. Include relevant inventory and frozen interface identities in dispatch packets. Complete the workflow's real artifacts and verification; do not declare success from prose. ")
        if stage == "specification":
            prompt += (f"The requested run mode is {mode or 'regenerate if no prior frozen baseline; otherwise ask the user to choose amend or regenerate'}. "
                       "Ask and resolve architectural or directional questions here. Do not implement the Todo application in this workflow.")
        elif stage == "preparation":
            prompt += "Produce frozen tasks, verticals, dependency-closed phases, matrix, shells and anchors; preserve all frozen contracts. Commit the prepared baseline."
        else:
            prompt += ("This session will use native goal mode. Print the exact output of ./rdd goal and ask the developer to submit it with /goal. "
                       "Do not claim that a normal prompt activated native goal mode. Once the goal is active, follow implementation-workflow through project validation.")
        requested_runtime = self.profile_settings("rdd_coordinator")
        if permission:
            requested_runtime.update(sandbox="danger-full-access", approval_policy="never")
        return {"stage": stage, "prompt": prompt,
                "requested_runtime": requested_runtime,
                "argv": CodexAdapter(self.root).native_argv(prompt, permission=permission),
                "native_goal": self.goal() if stage == "implementation" else None}


def head_ref(root: Path, ref: str) -> str:
    return GitAdapter(root).current_head(ref)
