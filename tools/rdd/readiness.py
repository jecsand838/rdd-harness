"""Declared check inputs and their phase/category-closed producer graph."""
from pathlib import Path

from .artifacts import CATEGORIES, ancestors, subset, unique
from .common import RddError, read_json, safe_path


def validate_resources(root: Path, spec: dict) -> None:
    resources = unique(spec["resources"], "resource")
    environments = unique(spec["environments"], "environment")
    checks = unique(spec["checks"], "check")
    for resource in resources.values():
        rid = resource["id"]
        if resource["availability"] == "implementation" and resource["kind"] != "repository":
            raise RddError(f"Resource {rid}: tools, hosts and external inputs cannot defer readiness to implementation", "specification")
        if resource.get("required_at") in {"specification", "preparation"} and resource["availability"] == "implementation":
            raise RddError(f"Resource {rid} is required before its implementation producer", "specification")
        subset(resource["environments"], environments, f"resource {rid} environments")
        subset(resource["probe_check_ids"], checks, f"resource {rid} probes")
        if resource["kind"] == "repository":
            if not resource["path"]:
                raise RddError(f"Repository resource {rid} has no path", "specification")
            safe_path(root, resource["path"], allow_missing=resource["availability"] != "baseline")
        if resource["kind"] == "tool" and (not resource["version"] or not resource["path"]):
            raise RddError(f"Tool {rid} needs an exact version pin and executable", "specification")
        if resource["kind"] == "external" and not resource["path"]:
            raise RddError(f"External input {rid} needs an exact acquisition destination", "specification")
        if resource["kind"] != "repository" and not resource["probe_check_ids"]:
            raise RddError(f"Resource {rid} needs an executable readiness probe", "specification")
        for cid in resource["probe_check_ids"]:
            if checks[cid]["kind"] != "readiness":
                raise RddError(f"Resource {rid} probe {cid} is not a readiness check", "specification")
            if checks[cid]["argv"][-1:] in (["--version"], ["-V"]):
                raise RddError(f"Resource {rid} requires a smoke experiment, not only a version command", "specification")
        if resource["probe_check_ids"] and not set(resource["environments"]) <= {e for c in resource["probe_check_ids"] for e in checks[c]["environments"]}:
            raise RddError(f"Resource {rid} probes omit required environments", "specification")
    for check in checks.values():
        cid = check["id"]
        subset(check["requires"], resources, f"check {cid} resources")
        subset(check["environments"], environments, f"check {cid} environments")
        if not check["environments"] or (check["kind"] != "manual" and not check["requires"]):
            raise RddError(f"Check {cid} needs complete execution environments and inputs", "specification")
        declared = {environments[e]["platform"] for e in check["environments"]}
        if "any" not in check["platforms"] and declared != set(check["platforms"]):
            raise RddError(f"Check {cid} environment/platform inventory differs", "specification")
        profiles = {environments[e]["host_profile"] for e in check["environments"]}
        if len(declared) != len(check["environments"]):
            raise RddError(f"Check {cid} must split ambiguous same-platform environments", "specification")
        if profiles != {check["host_profile"]}:
            raise RddError(f"Check {cid} has incompatible host profiles; split its execution checks", "specification")
        for rid in check["requires"]:
            if not set(check["environments"]) <= set(resources[rid]["environments"]):
                raise RddError(f"Check {cid} input {rid} is unavailable on its environments", "specification")
            if cid in spec.get("contract_check_ids", []) or cid in required_probe_ids(spec):
                if resources[rid]["availability"] == "implementation" or (
                        resources[rid]["kind"] == "external" and resources[rid].get("required_at") == "implementation"):
                    raise RddError(f"Qualification {cid} depends on future product input {rid}; qualify its acquisition protocol with a disposable input", "specification")


def validate_producers(root: Path, spec: dict, plan: dict) -> None:
    resources = unique(spec["resources"], "resource")
    checks = unique(spec["checks"], "check")
    tasks = unique(plan["tasks"], "task")
    phases = {p["id"]: i for i, p in enumerate(plan["phases"])}
    graph = {t["id"]: t["depends_on"] for t in tasks.values()}
    producers = {}
    for producer in plan["resource_producers"]:
        rid = producer["resource"]
        if rid not in resources or rid in producers:
            raise RddError(f"Unknown or duplicate resource producer {rid}", "planning")
        producers[rid] = producer
        resource = resources[rid]
        subset(producer["checks"], checks, f"producer {rid} checks")
        expected = {"baseline": "baseline", "implementation": "task", "external": "external"}[resource["availability"]]
        if producer["kind"] != expected:
            raise RddError(f"Resource {rid} producer contradicts frozen availability", "planning")
        if producer["kind"] == "task":
            tid = producer["task"]
            if tid not in tasks or rid not in tasks[tid]["produces"]:
                raise RddError(f"Resource {rid} producer task does not produce it", "planning")
            if resource["kind"] != "repository" or resource["path"] not in tasks[tid]["writes"]:
                raise RddError(f"Resource {rid} producer lacks exact file ownership", "planning")
        elif producer["task"] is not None:
            raise RddError(f"Resource {rid} has a spurious task producer", "planning")
        if producer["kind"] == "external" and not producer["checks"]:
            raise RddError(f"External resource {rid} needs an exercised acquisition/transfer check", "planning")
    if set(producers) != set(resources):
        raise RddError("Every execution resource needs exactly one producer", "planning")

    def available(rid, consumer=None, phase=None):
        producer = producers[rid]
        if producer["kind"] != "task":
            return
        before = tasks[producer["task"]]
        if consumer is not None:
            if before["id"] == consumer["id"]:
                if consumer["category"] != "tests" or rid not in consumer["bootstrap_resources"]:
                    raise RddError(f"{rid}: own-task input requires an explicit test bootstrap", "planning")
            elif before["id"] not in ancestors(graph, consumer["id"]):
                raise RddError(f"{consumer['id']}: producer {before['id']} must be an explicit prerequisite before use", "planning")
            elif (phases[before["phase"]], CATEGORIES.index(before["category"])) > (phases[consumer["phase"]], CATEGORIES.index(consumer["category"])):
                raise RddError(f"{rid}: producer comes after its consumer", "planning")
        elif phases[before["phase"]] > phases[phase]:
            raise RddError(f"{rid}: future producer cannot support phase {phase}", "planning")

    for task in tasks.values():
        for field in ("requires", "produces", "bootstrap_resources"):
            subset(task[field], resources, f"{task['id']} {field}")
        if not set(task["bootstrap_resources"]) <= set(task["produces"]):
            raise RddError("Bootstrap resources must be owned outputs", "planning")
        for rid in task["produces"]:
            if producers[rid]["task"] != task["id"]:
                raise RddError(f"Ambiguous task producer for {rid}", "planning")
        required = set(task["requires"]) | {r for c in task["checks"] for r in checks[c]["requires"]}
        for rid in required:
            available(rid, consumer=task)
        for other in tasks.values():
            if other["category"] == "deletion" and set(other["writes"]) & {resources[r]["path"] for r in required}:
                if task["id"] not in ancestors(graph, other["id"]):
                    raise RddError(f"Deletion {other['id']} must follow last resource consumer {task['id']}", "planning")
    for phase in plan["phases"]:
        cumulative = set(spec.get("contract_check_ids", [])) | {c for p in plan["phases"] if phases[p["id"]] <= phases[phase["id"]] for c in p["checks"]}
        for cid in cumulative:
            for rid in checks[cid]["requires"]:
                available(rid, phase=phase["id"])
                for task in tasks.values():
                    if (task["category"] == "deletion" and resources[rid]["path"] in task["writes"]
                            and phases[task["phase"]] <= phases[phase["id"]]):
                        raise RddError(f"Deletion {task['id']} removes input {rid} needed by cumulative phase {phase['id']}", "planning")
    if "resource_uses" in plan:
        expected = set()
        for rid, resource in resources.items():
            if resource.get("required_at") == "preparation":
                expected.add((rid, "preparation", None))
        for task in tasks.values():
            required = set(task["requires"]) | {r for c in task["checks"] for r in checks[c]["requires"]}
            for rid in required:
                expected.add((rid, "task_red" if task["category"] == "tests" else "task_completion", task["id"]))
        for phase in plan["phases"]:
            cumulative = set(spec.get("contract_check_ids", [])) | {c for p in plan["phases"] if phases[p["id"]] <= phases[phase["id"]] for c in p["checks"]}
            expected.update((rid, "phase", phase["id"]) for cid in cumulative for rid in checks[cid]["requires"])
        project_checks = set(spec.get("contract_check_ids", []) + spec.get("project_check_ids", [])) | {c for p in plan["phases"] for c in p["checks"]}
        expected.update((rid, "project", None) for cid in project_checks for rid in checks[cid]["requires"])
        actual = [(u["resource"], u["consumer_kind"], u["consumer"]) for u in plan["resource_uses"]]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise RddError("Resource use timing must exactly cover preparation, RED/completion, cumulative phase and project consumers", "planning")
    validate_boundary_plan(spec, plan)


def validate_boundary_plan(spec: dict, plan: dict) -> None:
    """Real adapter proofs become due only once their planned producers exist."""
    modules = {m["id"]: m for m in spec.get("modules", []) if "implementation_checks" in m}
    if not modules:
        return
    tasks = unique(plan["tasks"], "task")
    phases = {p["id"]: i for i, p in enumerate(plan["phases"])}
    proofs = {}
    checks = unique(spec["checks"], "check")
    resources = unique(spec["resources"], "resource")
    operations = {e["id"]: set(e.get("contract_operations", [])) for e in spec["solution_elements"]}
    for proof in plan["boundary_proofs"]:
        mid, operation = proof["module"], proof["operation"]
        if mid not in modules or operation in proofs:
            raise RddError(f"Unknown or duplicated module operation boundary proof {mid}:{operation}", "planning")
        proofs[operation] = proof
        if proof["first_phase"] not in phases:
            raise RddError(f"Module {mid} boundary proof has no first phase", "planning")
        expected = {c for group in modules[mid]["implementation_checks"].values() for c in group}
        if (not set(proof["checks"]) <= expected or any(not set(proof["checks"]) & set(group)
                for group in modules[mid]["implementation_checks"].values())):
            raise RddError(f"Module {mid} operation proof must cover every implementation proof role", "planning")
        due = next(p for p in plan["phases"] if p["id"] == proof["first_phase"])
        if not set(proof["checks"]) <= set(due["checks"]):
            raise RddError(f"Module {mid} real adapter checks must run in their first due phase", "planning")
        module_operations = {op for e in spec["solution_elements"] if e["module"] == mid
                             for op in e.get("contract_operations", [])}
        if operation not in module_operations:
            raise RddError(f"Module {mid} proof references an unowned contract operation", "planning")
        required_operations = {operation}
        for role in ("provider_tasks", "consumer_tasks", "adapter_tasks", "verification_tasks"):
            if not proof[role]:
                raise RddError(f"Module {mid} needs explicit {role}", "planning")
            subset(proof[role], tasks, f"module {mid} {role}")
            for tid in proof[role]:
                if phases[tasks[tid]["phase"]] > phases[proof["first_phase"]]:
                    raise RddError(f"Module {mid} boundary proof precedes its {role} producer {tid}", "planning")
                wanted = {"tests"} if role == "verification_tasks" else {"modification", "addition"}
                if tasks[tid]["category"] not in wanted:
                    raise RddError(f"Module {mid} {role} must name actual {'test' if role == 'verification_tasks' else 'production'} owners", "planning")
            covered = {op for tid in proof[role] for eid in tasks[tid]["solution_elements"] for op in operations[eid]}
            if not required_operations <= covered:
                raise RddError(f"Module {mid} {role} omits operation ownership: {sorted(required_operations - covered)}", "planning")
            role_ids = modules[mid]["implementation_checks"].get("provider" if role == "provider_tasks" else "consumer", [])
            if role == "verification_tasks":
                if any(not set(tasks[tid]["checks"]) & expected for tid in proof[role]):
                    raise RddError(f"Module {mid} verification task lacks its real boundary checks", "planning")
                continue
            dependencies = {resources[r]["path"] for c in role_ids for r in checks[c]["requires"]
                            if resources[r]["kind"] == "repository"}
            for tid in proof[role]:
                owned = set(tasks[tid]["writes"]) & dependencies
                if role == "provider_tasks":
                    owned = {p for p in owned if any(p == base or (base.endswith('/') and p.startswith(base))
                                                    for base in modules[mid]["owns_paths"])}
                if not owned:
                    raise RddError(f"Module {mid} {role} task {tid} has no real adapter source consumed by its checks", "planning")
        producer_phase = max(phases[tasks[t]["phase"]] for role in ("provider_tasks", "adapter_tasks") for t in proof[role])
        if phases[proof["first_phase"]] != producer_phase:
            raise RddError(f"Operation {operation} proofs cannot be deferred beyond its provider/adapter delivery phase", "planning")
    all_operations = {op for e in spec["solution_elements"] if e["module"] in modules for op in e.get("contract_operations", [])}
    if set(proofs) != all_operations:
        raise RddError("Every contract operation needs scheduled real provider, consumer, adapter and verification proofs", "planning")
    for mid, module in modules.items():
        if {c for p in proofs.values() if p["module"] == mid for c in p["checks"]} != {c for group in module["implementation_checks"].values() for c in group}:
            raise RddError(f"Module {mid} operation proofs omit frozen implementation checks", "planning")


def required_probe_ids(spec: dict, plan: dict | None = None) -> list[str]:
    ids = {cid for resource in spec["resources"] if resource["availability"] != "implementation"
           for cid in resource["probe_check_ids"]}
    if plan:
        ids.update(cid for producer in plan["resource_producers"] if producer["kind"] != "task"
                   for cid in producer["checks"])
    return sorted(ids)


def verify_resource_observations(root: Path, spec: dict, receipts: list[dict]) -> None:
    """Probe logs contain measured identities; protocols remain independently reviewed."""
    from .adapters import _strict_json
    environments = unique(spec["environments"], "environment")
    for resource in spec["resources"]:
        if resource["availability"] == "implementation" or resource["kind"] == "repository":
            continue
        for environment in resource["environments"]:
            expected = environments[environment]
            found = False
            for receipt in receipts:
                if (receipt["check_id"] not in resource["probe_check_ids"] or receipt["platform"] != expected["platform"]
                        or receipt["provenance"]["host_profile"] != (expected["host_profile"] or "")):
                    continue
                log = read_json(safe_path(root, receipt["log_path"], allow_missing=False))
                try:
                    payload = _strict_json(log["stdout"])
                    observation = payload["resources"][resource["id"]]
                except (ValueError, KeyError, TypeError) as exc:
                    raise RddError(f"Readiness probe lacks measured resource {resource['id']}", "environment") from exc
                if (not isinstance(observation, dict) or observation.get("environment") != environment
                        or observation.get("version") != resource["version"]
                        or not isinstance(observation.get("observation"), str)
                        or not observation["observation"].strip()):
                    raise RddError(f"Readiness observation does not match {resource['id']} pin/environment/protocol", "environment")
                found = True
            if not found:
                raise RddError(f"Missing actual readiness probe for {resource['id']} on {environment}", "environment")


def canonical_contract_check(spec: dict) -> dict:
    """The protected driver is mandatory; author-selected contract labels cannot replace it."""
    for check in spec["checks"]:
        argv = check["argv"]
        if (check["id"] in spec["contract_check_ids"] and check["kind"] == "contract" and check["cwd"] == "."
                and argv[:2] == ["{python}", "tools/rdd/proto_traits.py"]):
            tail = argv[2:]
            if len(tail) % 2 or any(tail[i] != "--target" or not tail[i + 1] for i in range(0, len(tail), 2)):
                raise RddError("Canonical qualification accepts only explicit compile targets; generation and compatibility authority are controller-owned", "specification")
            return check
    raise RddError("Specification qualification requires the protected canonical Protobuf driver check", "specification")


def verify_canonical_contract_receipts(root: Path, spec: dict, receipts: list[dict], *, log_root: Path | None = None) -> None:
    """Reconstruct generation/proof inventories from transferable raw driver output."""
    import hashlib
    import json
    from .adapters import _strict_json
    from .common import inventory
    check = canonical_contract_check(spec)
    metadata = read_json(safe_path(root, spec["contract_index_path"], allow_missing=False))
    index = metadata["contract_index"]
    services = {s["symbol"] for s in index["services"]}
    operations = {m["symbol"] for s in index["services"] for m in s["operations"]}
    selected = [r for r in receipts if r["check_id"] == check["id"]]
    if not selected:
        raise RddError("Missing actual canonical contract qualification receipt", "review")
    for receipt in selected:
        raw = read_json(safe_path(log_root or root, receipt["log_path"], allow_missing=False))
        try:
            report = _strict_json(raw["stdout"])
            generated = {"gen/rust/" + p: value for p, value in report["generated_files"].items()}
            negatives = {(n["operation"], n["defect"], n["diagnostic"]) for n in report["boundary_negative_proofs"]}
            expected_negative = {(op, defect, code) for op in operations for defect, code in (
                ("provider_request", "E0053"), ("provider_response", "E0271"), ("consumer_request", "E0308"), ("associated_error", "E0437"))}
            valid = (report["status"] == "passed" and report["write"] is False and not report["changed_files"]
                and report["descriptor_sha256"] == metadata["descriptor_sha256"]
                and set(report["qualified_services"]) == services and set(report["qualified_operations"]) == operations
                and set(report["targets"]) == {"host", *check["argv"][3::2]}
                and set(generated) == set(spec["generated_files"]) and inventory(root, list(generated)) == generated
                and report["boundary_provider"] == report["boundary_consumer"] == report["signature_positive"] == "passed"
                and report["dependency_direction_negative"] == "expected_E0432"
                and report["signature_negative"] == "expected_E0050" and negatives == expected_negative)
            steps = report["steps"]
            names = {step["name"] for step in steps}
            expected_steps = {"buf-version", "cargo-version", "buf-lint", "buf-build", "generate-contracts",
                              "compile-host", "signature-positive", "signature-negative",
                              "boundary-provider", "boundary-consumer", "boundary-dependency-negative"}
            expected_steps.update(f"boundary-negative-{i}" for i in range(len(expected_negative)))
            for i, _ in enumerate(check["argv"][3::2], 1):
                expected_steps.update({f"boundary-provider-target-{i}", f"boundary-consumer-target-{i}"})
                expected_steps.add(f"compile-target-{i}")
            valid = valid and expected_steps <= names and len(names) == len(steps)
            by_name = {step["name"]: step for step in steps}
            diagnostic_steps = [("signature-negative", "E0050"), ("boundary-dependency-negative", "E0432")]
            diagnostic_steps += [(f"boundary-negative-{i}", row["diagnostic"]) for i, row in enumerate(report["boundary_negative_proofs"])]
            valid = valid and len(report["boundary_negative_proofs"]) == len(expected_negative)
            for name, code in diagnostic_steps:
                step = by_name[name]
                valid = valid and step["expected_failure"] is True and code in step["stdout"] + step["stderr"]
            for step in steps:
                embedded = {"name": step["name"], "command": step["command"], "exit_code": step["exit_code"],
                            "expected_failure": step["expected_failure"], "stdout": step["stdout"], "stderr": step["stderr"],
                            "timed_out": False, "output_truncated": False}
                step_hash = hashlib.sha256((json.dumps(embedded, indent=2) + "\n").encode("utf-8")).hexdigest()
                valid = valid and step_hash == step["log_digest"] == step["sha256"]
                valid = valid and ((step["exit_code"] != 0) if step["expected_failure"] else step["exit_code"] == 0)
            if not valid:
                raise ValueError("descriptor, generated bytes, target, operation or diagnostic inventory mismatch")
        except (ValueError, KeyError, TypeError) as exc:
            raise RddError(f"Canonical contract qualification lacks exact transferable proof: {exc}", "review") from exc


def verify_readiness_coverage(spec: dict, ids: list[str], receipts: list[dict], *, require_ci: bool = False) -> None:
    checks = unique(spec["checks"], "check")
    environments = unique(spec["environments"], "environment")
    expected = {(cid, environments[env]["platform"]) for cid in ids for env in checks[cid]["environments"]}
    actual = {(r["check_id"], r["platform"]) for r in receipts}
    if actual != expected:
        raise RddError("Readiness receipts omit a required check/environment execution", "review")
    if require_ci:
        required_ci = {(cid, platform) for cid, platform in expected if not checks[cid]["host_profile"] and checks[cid]["kind"] != "manual"}
        observed_ci = {(r["check_id"], r["platform"]) for r in receipts if r["origin"] == "ci"}
        if not required_ci <= observed_ci:
            raise RddError("Preparation lacks actual exact-source CI coverage", "review")
