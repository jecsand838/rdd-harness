"""Fixed workflow graph. Implementation nodes project existing phase/task truth."""
from pathlib import Path
import copy
import hashlib
import math
import re
import subprocess
import time

from .common import RddError, digest, event, file_hash, git, head, inventory, read_json, safe_path, source_digest, validate_artifact
from .profiles import WORKFLOW_AUTHOR_ROLES
from .refinement import POLICY as REFINEMENT_POLICY, SNAPSHOT_PATH, closure, guard_choice_prerequisites, node_projection, validate_budget
from .artifacts import DOMAIN_INVENTORY_PATH, domain_inventory_validate, requirements

_SPEC = [
    ("S0", "Baseline intake", []), ("S1", "Domain modeling", ["S0"]),
    ("S2", "Goal and NFR modeling", ["S0"]), ("S3", "Golden scenarios and oracles", ["S1"]),
    ("S4", "Benchmarks and constraints", ["S2"]), ("S5", "Dependency, tool, host and transfer qualification", ["S1", "S2"]),
    ("S6", "Specification and canonical contract generation", ["S3", "S4", "S5"]),
    ("S7", "Candidate validation and readiness", ["S6"]), ("S8", "Independent reviews and specification freeze", ["S7"])]
_PREP = [
    ("P0", "Verify frozen specification, contracts and tree", []), ("P1", "High-level planning and reuse", ["P0"]),
    ("P2", "Task research and work sites", ["P1"]), ("P3", "Vertical dependency graph", ["P2"]),
    ("P4", "Dependency-closed phases and categories", ["P3"]), ("P5", "Fully groomed backlog and matrix", ["P4"]),
    ("P6", "Qualification, independent reviews and plan freeze", ["P5"]),
    ("P7", "Materialize and commit", ["P6"]), ("P8", "Final readiness, CI and preparation gate", ["P7"])]
_IMPL = [
    ("I0", "Native goal and phase entry", []), ("I1", "Executable tests and behavioral RED", ["I0"]),
    ("I2", "Ordered leased implementation", ["I1"]), ("I3", "Cumulative checks and phase review", ["I2"]),
    ("I4", "Verified phase PR and seal", ["I3"]), ("I5", "Project validation and checkpoint", ["I4"])]
NODES = {node: {"id": node, "title": title, "depends_on": deps, "stage": stage}
         for stage, rows in (("specification", _SPEC), ("preparation", _PREP), ("implementation", _IMPL))
         for node, title, deps in rows}
DERIVED = {"S8", "P6", "P7", "P8", *(node for node, _, _ in _IMPL)}


def _prior_artifact(root: Path, claim: dict, path: str, prior_attempts: list[dict]) -> bool:
    if claim["sources"].get(path, "MISSING") == "MISSING":
        for attempt in reversed(prior_attempts):
            if attempt.get("status") == "complete" and path in attempt.get("outputs", {}):
                return attempt["outputs"][path] == "MISSING"
    value = claim["sources"].get(path)
    if not re.fullmatch(r"[0-9a-f]{64}", str(value)):
        return False
    tree = git(root, "ls-tree", "-z", claim["source_commit"], "--", path, check=False)
    if not tree or tree.count("\0") != 1:
        return False
    metadata, name = tree[:-1].split("\t", 1)
    mode, kind, oid = metadata.split()
    if name != path or mode not in {"100644", "100755"} or kind != "blob":
        return False
    # Worktree/state hashes alone can be rewritten together. Corroborate the
    # prior artifact against its real committed bytes, without text decoding.
    try:
        blob = subprocess.run(["git", "-C", str(root), "cat-file", "blob", oid],
                              capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RddError(f"Cannot verify retired artifact: {exc}", "environment") from exc
    return bool(blob.returncode == 0 and blob.stdout and hashlib.sha256(blob.stdout).hexdigest() == value)

# Fixed contracts for the three graphs, not an extensible workflow language.
SPECIALIST_OWNERS = {
    "S1": "rdd_domain_analyst",
    "S2": "rdd_verification_designer", "S3": "rdd_verification_designer", "S4": "rdd_verification_designer",
    "S5": "rdd_qualification_engineer", "S6": "rdd_contract_architect",
    **dict.fromkeys(("P1", "P2", "P3", "P4", "P5"), "rdd_task_planner"),
}
_OUTPUTS = {
    "S0": "Requirements baseline, capabilities, authors and live reviewer intake",
    "S1": "Canonical docs/specs/domain-inventory.json: functional domains, invariant/behavior identities, typed supporting owners and directed call/type-only interactions",
    "S2": "NFR allocations, constraints, platform obligations and measurement needs",
    "S3": "Requirement-linked golden/negative/boundary scenarios and independent oracles",
    "S4": "Benchmark workloads, fixtures, thresholds, environments and evaluators",
    "S5": "Official dependency sources and reproducible interoperability/provisioning/transfer experiments",
    "S6": "Complete specification, target tree and canonical/generated contracts bound to the exact accepted S1 inventory",
    "S7": "Controller candidate validation and current executable readiness receipts",
    "S8": "Exact-candidate dual independent approvals and specification freeze",
    "P0": "Verified frozen specification, contracts, target tree and live reviewer",
    "P1": "Delivery outcomes and concrete reuse analysis",
    "P2": "Task scopes, work locations, boundary wiring and prerequisite producers",
    "P3": "Dependency DAG, shared ownership and ordered vertical memberships",
    "P4": "Sequential dependency-closed phases compatible with category order",
    "P5": "Fully hydrated backlog and complete implementation/verification matrix",
    "P6": "Plan qualification, dual independent approvals and freeze",
    "P7": "Committed verified materialization, packets, matrix and manifest",
    "P8": "Current preparation CI/readiness and final independent acceptance",
    "I0": "Native goal and phase opened from accepted preparation or sealed predecessor",
    "I1": "Accepted executable test tasks with actual behavioral RED",
    "I2": "Accepted leased tasks through category barriers and controller integration",
    "I3": "Cumulative evidence, independent phase review and passing phase gate",
    "I4": "Verified single phase PR and immutable seal",
    "I5": "Project acceptance, final validation and checkpoint",
}
for _node, _definition in NODES.items():
    _definition.update(
        responsible_roles=[SPECIALIST_OWNERS.get(_node, "rdd_coordinator")],
        max_parallel_authors=2,
        inputs=(["requirements", "capabilities", "live_review"] if _node.startswith("S")
                else ["frozen_specification", "frozen_contracts", "live_review"] if _node.startswith("P")
                else ["frozen_plan", "accepted_preparation_or_predecessor", "live_review"]),
        required_output=_OUTPUTS[_node],
        validator=("existing_acceptance_state" if _node in DERIVED else "specification_validation_and_readiness" if _node == "S7"
                   else "structured_domain_inventory_and_requirements_ownership" if _node == "S1"
                   else "specification_validation" if _node == "S6" else "plan_validation" if _node == "P5"
                   else "requirements_identity_and_bounded_artifact_handoff"),
        evidence=("controller_receipts" if _node in DERIVED or _node == "S7"
                  else "hashed_artifacts_and_registered_experiments; semantic review remains required"),
        retry_budget="limits.max_attempts",
        correction_destination=(_node if _node not in DERIVED else "S6" if _node == "S8"
                                else "P5" if _node in {"P6", "P7", "P8"} else "open_phase_scoped_repair"),
        write_prefixes=(["docs/specs/", "docs/decisions/"] if _node.startswith("S")
                        else [".rdd/plan/notes/"] if _node.startswith("P") else []),
        write_paths=[])
    if _node.startswith("S"):
        _definition["refinement_policy"] = REFINEMENT_POLICY
    if _node in {"S5", "S6"}:
        _definition["write_prefixes"] += [".rdd/sources/"]
        _definition["write_paths"] += ["buf.yaml", "buf.lock", "rust-toolchain.toml", "tools/proto-codegen/Cargo.lock"]
    if _node == "S6":
        _definition["write_prefixes"] += ["contracts/", "gen/"]
        _definition["write_paths"] += [".rdd/spec.json"]
    if _node == "P5":
        _definition["write_paths"] += [".rdd/plan/plan.json"]
    if _node in DERIVED:
        _definition["write_prefixes"], _definition["write_paths"] = [], []


class WorkflowNodes:
    def _validate_node_writes(self, node: str, writes: list[str]) -> None:
        definition = NODES[node]
        if not isinstance(writes, list) or not writes or any(not isinstance(path, str) for path in writes) or len(set(writes)) != len(writes):
            raise RddError("Node claims require a bounded unique write inventory")
        for path in writes:
            safe_path(self.root, path)
            if path == SNAPSHOT_PATH and node != "S6":
                raise RddError("Only S6 may materialize the refinement snapshot", "specification")
            if path == DOMAIN_INVENTORY_PATH and node != "S1":
                raise RddError("Only S1 may author or correct the canonical domain inventory", "specification")
            if path.endswith("/") or not (path.startswith(tuple(definition["write_prefixes"]))
                                         or path in definition["write_paths"]):
                raise RddError(f"Workflow node {node} writes must be exact permitted artifact paths")
        if node == "S1" and DOMAIN_INVENTORY_PATH not in writes:
            raise RddError("S1 must claim its canonical structured domain inventory", "specification")
        if node.startswith("P"):
            frozen = read_json(self.root / ".rdd/spec.lock.json")
            if set(writes) & set(frozen["files"]):
                raise RddError("Preparation cannot claim frozen specification or contract writes", "specification")

    def _node_input(self, state: dict, node: str, records: dict) -> dict:
        dependencies = {dep: records.get(dep, {}).get("output_digest") for dep in NODES[node]["depends_on"]}
        refinement = node_projection(self.root, state, node)
        validate_budget(self.config, refinement, packet=True)
        return {"refinement": refinement,
                "requirements_digest": state["requirements_digest"], "dependencies": dependencies,
                "requirements_source": file_hash(self.root / self.config["requirements"]),
                "spec_digest": state.get("spec_digest") if node.startswith("P") else None}

    def _node_records(self, state: dict) -> dict:
        records = copy.deepcopy(state.get("workflow_nodes", {}))
        for node, definition in NODES.items():
            if node in DERIVED:
                continue
            record = records.setdefault(node, {"status": "pending", "attempts": []})
            if record["status"] == "complete":
                if (inventory(self.root, list(record["outputs"])) != record["outputs"]
                        or any(records.get(dep, {}).get("status") != "complete" for dep in definition["depends_on"])
                        or (node == "S6" and read_json(self.root / SNAPSHOT_PATH)["closure_digest"]
                            != closure(self.root, state)["closure_digest"])
                        or record["input_digest"] != digest(self._node_input(state, node, records))):
                    record["status"] = "stale"
        derived = {"S8": state.get("spec_acceptance"), "P6": state.get("plan_acceptance"),
                   "P7": state.get("prepared_digest"), "P8": state.get("preparation_gate")}
        for node, proof in derived.items():
            records[node] = {"status": "complete" if proof else "pending", "output_digest": digest(proof) if proof else None,
                             "authority": {"S8": "spec freeze", "P6": "plan freeze", "P7": "prepare and commit", "P8": "gate preparation"}[node]}
        if derived["P7"]:
            from .common import git
            if git(self.root, "status", "--porcelain"):
                records["P7"]["status"] = "pending"
        phase = state.get("active_phase") or next((p for p in reversed(list(state.get("phases", {})))
                                                    if state["phases"][p].get("status") == "sealed"), None)
        pstate = state.get("phases", {}).get(phase, {})
        tasks = [] if not state.get("plan_digest") else [t for t in self.plan()["tasks"] if t["phase"] == phase]
        tests = [t for t in tasks if t["category"] == "tests"]
        truth = {"I0": bool(phase), "I1": bool(phase) and all(state["tasks"][t["id"]]["status"] == "done" and state["tasks"][t["id"]].get("red_evidence") for t in tests),
                 "I2": bool(tasks) and all(state["tasks"][t["id"]]["status"] == "done" for t in tasks),
                 "I3": bool(pstate.get("gate")), "I4": pstate.get("status") == "sealed", "I5": state["status"] == "complete"}
        for node, complete in truth.items():
            records[node] = {"status": "complete" if complete else "pending", "phase": phase,
                             "authority": "Existing task, phase, PR and project controller records"}
        return records

    def workflow_nodes(self) -> dict:
        state = self.state(allow_blocked=True)
        try:
            self.guard_run_policy(state)
        except RddError as exc:
            # Historical rows retain their original identities; no new graph is
            # projected onto old claims, including when new profiles are absent.
            return {"historical": True, "reason": str(exc), "graph_digest": state.get("workflow_graph_digest"),
                    "agent_profile_digest": state.get("agent_profile_digest"),
                    "nodes": [{"id": node, **row} for node, row in state.get("workflow_nodes", {}).items()]}
        records = self._node_records(state)
        return {"historical": False, "graph_digest": digest(NODES), "agent_profile_digest": state["agent_profile_digest"],
                "nodes": [{**definition, **records[node]} for node, definition in NODES.items()]}

    def workflow_next(self) -> dict:
        state = self.state()
        self.guard_run_policy(state)
        records = self._node_records(state)
        stage = "specification" if state["status"] == "specification" else "preparation" if state["status"] in {"specified", "planned", "preparing"} else "implementation"
        ready = [node for node, definition in NODES.items() if definition["stage"] == stage
                 and records[node]["status"] in {"pending", "stale"}
                 and all(records[dep]["status"] == "complete" for dep in definition["depends_on"])]
        return {"stage": stage, "ready": ready, "implementation_queue": self.next() if stage == "implementation" and state.get("active_phase") else None}

    def require_workflow_node(self, node: str) -> None:
        if self._node_records(self.state())[node]["status"] != "complete":
            raise RddError(f"Workflow node {node} is incomplete or its inputs changed", "planning")

    def workflow_claim(self, node: str, session_id: str, role: str, writes: list[str], finding: str | None = None) -> dict:
        self.guard_source_write(baseline=True)
        if node not in NODES or node in DERIVED:
            raise RddError("This node is unknown or derives from an existing controller command")
        expected_stage = "specification" if node.startswith("S") else "specified"
        if self.state()["status"] != expected_stage:
            raise RddError("Authoring node belongs to a different or already frozen stage", "specification" if node.startswith("S") else "planning")
        self.live_review_guard(final=False, node=node, correction=finding)
        self.guard_author_identity(session_id)
        if not session_id.strip() or role not in WORKFLOW_AUTHOR_ROLES:
            raise RddError("Node claims require the actual author session and supported role")
        definition = NODES[node]
        if role not in definition["responsible_roles"]:
            raise RddError(f"Node {node} requires one of its responsible roles: {definition['responsible_roles']}")
        if node not in self.workflow_next()["ready"] and not finding:
            raise RddError("Workflow node dependencies are not ready")
        self._validate_node_writes(node, writes)
        state = self.state()
        records = self._node_records(state)
        if sum(record.get("status") == "claimed" for record in records.values()) >= definition["max_parallel_authors"]:
            raise RddError("At most two authoring claims may run concurrently; retain the continuous reviewer slot")
        prior = records[node]
        if prior["status"] == "claimed":
            raise RddError("Release the existing node claim before retrying")
        if node == "S6" and set(prior.get("outputs", {})) - set(writes):
            raise RddError("S6 retries must retain the prior output inventory")
        if any(records[d]["status"] != "complete" for d in NODES[node]["depends_on"]):
            raise RddError("Workflow node dependencies are incomplete")
        observations = [entry for entry in state.get("live_reviews", [])
                        if entry["review"]["stage"] == NODES[node]["stage"]]
        for dependency in NODES[node]["depends_on"]:
            if not any(entry.get("node_outputs", {}).get(dependency) == records[dependency]["output_digest"] for entry in observations):
                raise RddError(f"Live reviewer must observe completed dependency {dependency} before its handoff to {node}", "review")
        if len(prior["attempts"]) >= self.config["limits"]["max_attempts"]:
            raise RddError("Workflow node attempt budget exhausted", "budget")
        for other in records.values():
            if other.get("status") == "claimed" and set(other["claim"]["writes"]) & set(writes):
                raise RddError("Workflow claims must have disjoint write ownership")
        inputs = self._node_input(state, node, records)
        guard_choice_prerequisites(self.root, state, inputs["refinement"])
        if any(s["observed"] != s["sha256"] for s in inputs["refinement"]["sources"]):
            raise RddError("Refinement prerequisite changed; resolve it before claiming work", "specification")
        if any(s["path"] in writes and not s["excerpt"] for s in inputs["refinement"]["sources"]):
            raise RddError("A mutable author output needs an exact excerpt source, not a whole-file prerequisite", "specification")
        sources = inventory(self.root)
        for source in inputs["refinement"]["sources"]:
            if source["path"] not in sources:
                raise RddError(f"Refinement source is absent from the claim inventory: {source['path']}", "specification")
        claim = {"session_id": session_id, "role": role, "requested_runtime": self.profile_settings(role),
                 "writes": writes, "attempt": len(prior["attempts"]) + 1,
                 "inputs": inputs, "input_digest": digest(inputs), "source_commit": head(self.root),
                 "source_digest": digest(sources), "sources": sources,
                 "concurrent_writes": sorted({p for r in records.values() if r.get("status") == "claimed" for p in r["claim"]["writes"]}),
                 "finding": finding, "review_cursor": len(state.get("live_reviews", [])),
                 "expires": time.time() + self.config["limits"]["lease_seconds"]}
        prior["attempts"].append({"claim": claim, "status": "claimed"})
        prior.update(status="claimed", claim=claim)
        state["workflow_nodes"] = {k: v for k, v in records.items() if k not in DERIVED}
        stage = "specification" if node.startswith("S") else "plan"
        authors = state.setdefault("authors", {}).setdefault(stage, [])
        if session_id not in authors:
            authors.append(session_id)
        event(state, "workflow_node_claimed", node=node, attempt=claim["attempt"], session=session_id, input_digest=claim["input_digest"])
        self.save(state)
        return {"node": node, "claim": claim, "correction_destination": definition["correction_destination"]}

    def workflow_record(self, file: Path) -> dict:
        self.guard_source_write(baseline=True)
        record = read_json(file)
        validate_artifact(self.root, "node-record", record)
        node = record["node"]
        if node not in NODES or node in DERIVED:
            raise RddError("Only claimed authoring nodes accept output records")
        state = self.state()
        if state["status"] != ("specification" if node.startswith("S") else "specified"):
            raise RddError("Cannot record authoring outputs after their stage froze")
        records = self._node_records(state)
        row = records[node]
        claim = row.get("claim", {})
        if row["status"] != "claimed" or any(record[k] != claim.get(k) for k in ("attempt", "session_id", "input_digest")):
            raise RddError("Node output does not match its current claim")
        if claim["expires"] < time.time():
            raise RddError("Workflow claim expired; preserve its output and release/retry", "budget")
        inputs = self._node_input(state, node, records)
        guard_choice_prerequisites(self.root, state, inputs["refinement"])
        if (digest(inputs) != claim["input_digest"]
                or any(records[d]["status"] != "complete" for d in NODES[node]["depends_on"])):
            raise RddError("Workflow node inputs changed during execution")
        self.live_review_guard(final=False, node=node)
        if set(record["outputs"]) != set(claim["writes"]):
            raise RddError("Node output inventory must exactly match its bounded claim")
        actual = inventory(self.root)
        changed = {p for p in set(actual) | set(claim["sources"]) if actual.get(p) != claim["sources"].get(p)}
        concurrent = {p for other, row in records.items() if other != node
                      for attempt in row.get("attempts", [])
                      if attempt["claim"]["expires"] >= claim["expires"]
                      for p in attempt["claim"]["writes"]}
        outside = changed - set(claim["writes"]) - concurrent - set(claim["concurrent_writes"])
        if outside:
            raise RddError("Node execution changed files outside its bounded claim: " + ", ".join(sorted(outside)))
        present_outputs = 0
        for path in record["outputs"]:
            output = safe_path(self.root, path)
            if not output.exists():
                if not _prior_artifact(self.root, claim, path, row["attempts"][:-1]):
                    raise RddError("Node missing output was not a previously present claimed artifact: " + path)
                # Canonical generation can retire the harness seed or obsolete
                # bindings. Preserve its absence in the same hashed inventory.
                continue
            if not output.is_file() or not output.stat().st_size:
                raise RddError("Node outputs must contain actual artifacts")
            present_outputs += 1
        if not present_outputs:
            raise RddError("Node completion requires at least one nonempty artifact, not only deletions")
        if node == "S0":
            index = read_json(self.root / ".rdd/requirements.index.json")
            if index["digest"] != state["requirements_digest"]:
                raise RddError("Baseline intake requirements index changed")
        if node == "S1":
            domain_inventory_validate(self.root, requirements(self.root, self.config["requirements"]))
        if node in {"S6", "S7"}:
            self.spec_validate()
        if node == "S7":
            ready = self.current_readiness("specification", self.stage_candidate("specification"))
            if set(record["evidence_ids"]) != set(ready["evidence"]):
                raise RddError("Readiness node must reference its actual controller proofs")
        if node.startswith("P"):
            self.frozen(planned=False)
        if node == "P5":
            self.plan_validate()
        for eid in record["evidence_ids"]:
            if eid not in state["checks"]:
                raise RddError("Node references unknown executable evidence")
        outputs = inventory(self.root, record["outputs"])
        row.update(status="complete", input_digest=claim["input_digest"], outputs=outputs,
                   output_digest=digest(outputs), source_commit=head(self.root), source_digest=source_digest(self.root))
        row["attempts"][-1].update(status="complete", outputs=outputs, evidence_ids=record["evidence_ids"])
        state["workflow_nodes"] = {k: v for k, v in records.items() if k not in DERIVED}
        event(state, "workflow_node_completed", node=node, attempt=claim["attempt"], outputs=outputs)
        self.save(state)
        return {"node": node, "status": "complete", "output_digest": row["output_digest"]}

    def workflow_release(self, node: str, reason: str) -> dict:
        self.guard_source_write(baseline=True)
        state = self.state(allow_blocked=True)
        row = state.get("workflow_nodes", {}).get(node)
        if not row or row["status"] != "claimed" or not reason.strip():
            raise RddError("Release requires a claimed node and reason")
        row["attempts"][-1].update(status="released", reason=reason)
        row["status"] = "pending"
        event(state, "workflow_node_released", node=node, reason=reason)
        self.save(state)
        return {"node": node, "status": "pending", "preserved_outputs": row["claim"]["writes"]}

    def validate_workflow_checkpoint(self, state: dict) -> None:
        self.guard_run_policy(state)
        if state.get("workflow_graph_digest") != digest(NODES):
            raise RddError("Checkpoint workflow graph differs from protected policy")
        references = [(e.get("node"), e.get("attempt"), e.get("session"))
                      for e in state.get("events", []) if e.get("action") == "workflow_node_claimed"]
        expected = [(node, a.get("claim", {}).get("attempt"), a.get("claim", {}).get("session_id"))
                    for node, row in state.get("workflow_nodes", {}).items() for a in row.get("attempts", [])]
        if len(references) != len(expected) or any(references.count(ref) != 1 for ref in expected):
            raise RddError("Checkpoint workflow claim references are missing or duplicated")
        for node, row in state.get("workflow_nodes", {}).items():
            if node not in NODES or node in DERIVED or row.get("status") not in {"pending", "claimed", "complete", "stale"}:
                raise RddError("Checkpoint contains an invalid authoring node")
            attempts = row.get("attempts", [])
            if row["status"] == "pending" and not attempts and "claim" not in row:
                continue
            if not attempts or len(attempts) > self.config["limits"]["max_attempts"]:
                raise RddError("Checkpoint workflow attempt history is invalid")
            for number, attempt in enumerate(attempts, 1):
                claim = attempt.get("claim", {})
                fields = {"session_id", "role", "requested_runtime", "writes", "attempt", "inputs", "input_digest", "source_commit", "source_digest",
                          "sources", "concurrent_writes", "finding", "review_cursor", "expires"}
                stage = "specification" if node.startswith("S") else "plan"
                if (set(claim) != fields or claim.get("attempt") != number
                        or claim.get("session_id") not in state.get("authors", {}).get(stage, [])
                        or claim.get("role") not in NODES[node]["responsible_roles"]
                        or not isinstance(claim.get("sources"), dict) or not claim.get("sources")
                        or claim.get("source_digest") != digest(claim.get("sources"))
                        or not isinstance(claim.get("expires"), (int, float)) or isinstance(claim.get("expires"), bool)
                        or not math.isfinite(claim["expires"]) or claim["expires"] <= 0
                        or not isinstance(claim.get("review_cursor"), int) or isinstance(claim.get("review_cursor"), bool)
                        or not 0 < claim["review_cursor"] <= len(state.get("live_reviews", []))
                        or not re.fullmatch(r"[0-9a-f]{40,64}", str(claim.get("source_commit")))
                        or attempt.get("status") not in {"claimed", "complete", "released"}):
                    raise RddError("Checkpoint node claim history is invalid")
                if claim["requested_runtime"] != self.profile_settings(claim["role"]):
                    raise RddError("Checkpoint node requested runtime differs from its pinned profile")
                self._validate_node_writes(node, claim["writes"])
                git(self.root, "cat-file", "-e", claim["source_commit"] + "^{commit}")
                for path, value in claim["sources"].items():
                    safe_path(self.root, path)
                    if value != "MISSING" and not re.fullmatch(r"[0-9a-f]{64}", str(value)):
                        raise RddError("Checkpoint node source inventory is invalid")
                inputs = claim["inputs"]
                matching_events = [i for i, e in enumerate(state.get("events", []))
                                   if e.get("action") == "workflow_node_claimed" and e.get("node") == node
                                   and e.get("attempt") == number and e.get("session") == claim["session_id"]]
                if len(matching_events) != 1 or state["events"][matching_events[0]].get("input_digest") != claim["input_digest"]:
                    raise RddError("Checkpoint node claim lacks its unique historical event")
                historical_refinement = node_projection(self.root, state, node, matching_events[0], claim["sources"])
                if (not isinstance(inputs, dict) or set(inputs) != {"refinement", "requirements_digest", "requirements_source", "dependencies", "spec_digest"}
                        or inputs["refinement"] != historical_refinement
                        or inputs["requirements_digest"] != state["requirements_digest"]
                        or not re.fullmatch(r"[0-9a-f]{64}", str(inputs["requirements_source"]))
                        or inputs["requirements_source"] != claim["sources"].get(self.config["requirements"])
                        or inputs["spec_digest"] != (state.get("spec_digest") if node.startswith("P") else None)
                        or not isinstance(inputs["dependencies"], dict) or set(inputs["dependencies"]) != set(NODES[node]["depends_on"])
                        or claim["input_digest"] != digest(inputs)):
                    raise RddError("Checkpoint node input identity is invalid")
                for dependency, identity in inputs["dependencies"].items():
                    prior = state.get("workflow_nodes", {}).get(dependency, {}).get("attempts", [])
                    if not any(a.get("status") == "complete" and a.get("outputs") and digest(a["outputs"]) == identity for a in prior) or not any(
                            e.get("action") == "workflow_node_completed" and e.get("node") == dependency
                            and digest(e.get("outputs")) == identity for e in state["events"][:matching_events[0]]):
                        raise RddError("Checkpoint node prerequisite handoff is missing")
                    if not any(entry["review"]["stage"] == NODES[node]["stage"]
                               and entry.get("node_outputs", {}).get(dependency) == identity
                               for entry in state["live_reviews"][:claim["review_cursor"]]):
                        raise RddError("Checkpoint node handoff lacks its preceding live observation")
                concurrent = claim["concurrent_writes"]
                if not isinstance(concurrent, list) or any(not isinstance(p, str) for p in concurrent) or len(concurrent) != len(set(concurrent)):
                    raise RddError("Checkpoint concurrent ownership is invalid")
                for path in concurrent:
                    safe_path(self.root, path)
                if attempt["status"] == "complete":
                    outputs = attempt.get("outputs", {})
                    if (not isinstance(outputs, dict) or set(outputs) != set(claim["writes"])
                            or not any(re.fullmatch(r"[0-9a-f]{64}", str(h)) for h in outputs.values())
                            or any(not re.fullmatch(r"[0-9a-f]{64}", str(h))
                                   and not (h == "MISSING" and _prior_artifact(self.root, claim, path, attempts[:number - 1]))
                                   for path, h in outputs.items())
                            or not isinstance(attempt.get("evidence_ids"), list)
                            or any(eid not in state.get("checks", {}) for eid in attempt["evidence_ids"])):
                        raise RddError("Checkpoint node output proof is invalid")
            if row.get("claim") != attempts[-1]["claim"]:
                raise RddError("Checkpoint current node claim differs from history")
            if row["status"] == "complete" and (attempts[-1]["status"] != "complete"
                    or row.get("outputs") != attempts[-1].get("outputs")
                    or row.get("output_digest") != digest(row.get("outputs"))
                    or row.get("input_digest") != row["claim"].get("input_digest")):
                raise RddError("Checkpoint completed node lacks its output proof")
        required = []
        if state.get("spec_digest"):
            required += [n for n, _, _ in _SPEC if n != "S8"]
        if state.get("plan_digest"):
            required += [n for n, _, _ in _PREP if n not in DERIVED]
        if any(state.get("workflow_nodes", {}).get(node, {}).get("status") != "complete" for node in required):
            raise RddError("Checkpoint accepted stage lacks completed workflow nodes")
