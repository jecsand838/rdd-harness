"""Declared check inputs and their phase/category-closed producer graph."""
from pathlib import Path

from .artifacts import CATEGORIES, ancestors, subset, unique
from .common import RddError, read_json, safe_path

HOSTED_RUNNERS = {"linux": "ubuntu-24.04", "macos": "macos-latest", "windows": "windows-latest"}


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
    preparation_ci_pairs(spec, qualification_check_ids(spec))


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
    validate_boundary_plan(spec, plan, root)


def validate_boundary_plan(spec: dict, plan: dict, root: Path | None = None) -> None:
    """Schedule each frozen interaction against its actual source owners."""
    from .artifacts import load_domain_inventory
    if spec.get("schema_version") != 3 or plan.get("schema_version") != 3:
        raise RddError("Boundary preparation requires v3 specification and plan artifacts; preserve older baselines without conversion", "specification")
    inventory = load_domain_inventory(root or Path.cwd(), spec)
    interactions = unique(inventory["interactions"], "domain interaction")
    modules = unique(spec["modules"], "module")
    tasks = unique(plan["tasks"], "task")
    phases = {p["id"]: i for i, p in enumerate(plan["phases"])}
    checks = unique(spec["checks"], "check")
    resources = unique(spec["resources"], "resource")
    elements = unique(spec["solution_elements"], "solution element")
    operations = {eid: set(element.get("contract_operations", [])) for eid, element in elements.items()}
    bindings = {}
    expected_calls, expected_types, expected_exports = set(), set(), set()
    for binding in spec["boundary_bindings"]:
        iid = binding["interaction"]
        if iid not in interactions or iid in bindings:
            raise RddError(f"Unknown or duplicate frozen interaction binding {iid}", "specification")
        bindings[iid] = binding
        interaction = interactions[iid]
        identity = (iid, interaction["consumer"], interaction["provider"])
        if interaction["kind"] == "call":
            expected_calls.update((*identity, operation) for operation in binding["operations"])
        elif interaction["kind"] == "type_only":
            expected_types.update((*identity, symbol) for symbol in binding["types"])
        else:
            expected_exports.update((*identity, symbol) for symbol in binding["exports"])
    if set(bindings) != set(interactions):
        raise RddError("Every domain interaction needs an exact frozen boundary binding", "specification")
    all_operations = {operation for values in operations.values() for operation in values}
    if {identity[3] for identity in expected_calls} != all_operations:
        raise RddError("Every frozen contract operation needs an explicit callable interaction before preparation", "specification")

    module_checks = {mid: {cid for group in module["implementation_checks"].values() for cid in group}
                     for mid, module in modules.items()}
    scheduled = {mid: set() for mid in modules}
    actual_calls, actual_types, actual_exports = set(), set(), set()

    def owned_source(mid, path):
        return Path(path).suffix == ".rs" and any(
            path == base or (base.endswith("/") and path.startswith(base)) for base in modules[mid]["owns_paths"])

    def source_inputs(ids):
        return {resources[rid]["path"] for cid in ids for rid in checks[cid]["requires"]
                if resources[rid]["kind"] == "repository"}

    def validate_proof(proof, field, expected, actual):
        identity = (proof["interaction"], proof["consumer"], proof["provider"], proof[field])
        if identity not in expected or identity in actual:
            raise RddError(f"Unknown or duplicate {field} interaction boundary proof {identity}", "planning")
        actual.add(identity)
        iid, consumer, provider, symbol = identity
        label = f"Interaction {iid} {consumer}->{provider}:{symbol}"
        first_phase = proof["first_phase"]
        if first_phase not in phases:
            raise RddError(f"{label} has no first phase", "planning")
        provider_groups = modules[provider]["implementation_checks"]
        consumer_groups = {role: ids for role, ids in modules[consumer]["implementation_checks"].items()
                           if role != "provider"}
        groups = list(provider_groups.values()) + list(consumer_groups.values())
        expected_checks = {cid for group in groups for cid in group}
        selected = set(proof["checks"])
        subset(selected, checks, f"{label} checks")
        if not selected <= expected_checks or any(group and not selected & set(group) for group in groups):
            raise RddError(f"{label} must cover every applicable implementation proof role", "planning")
        due = next(phase for phase in plan["phases"] if phase["id"] == first_phase)
        if not selected <= set(due["checks"]):
            raise RddError(f"{label} real boundary checks must run in their first due phase", "planning")
        scheduled[provider].update(selected & module_checks[provider])
        scheduled[consumer].update(selected & module_checks[consumer])
        roles = (("provider_tasks", "consumer_tasks", "adapter_tasks", "verification_tasks") if field == "operation" else
                 ("provider_tasks", "consumer_tasks", "verification_tasks") if field == "export" else
                 ("consumer_tasks", "verification_tasks"))
        provider_inputs = source_inputs(selected & set(provider_groups["provider"]))
        if field == "operation":
            owned_operations = {operation for element in elements.values() if element["module"] == provider
                                for operation in element.get("contract_operations", [])}
            if symbol not in owned_operations or symbol not in modules[consumer]["consumed_operations"]:
                raise RddError(f"{label} contradicts frozen callable provider/consumer ownership", "planning")
        elif field == "type" and (symbol not in modules[provider]["provided_types"] or symbol not in modules[consumer]["consumed_types"]):
            raise RddError(f"{label} contradicts frozen type provider/consumer ownership", "planning")
        if field == "export":
            export = next((row for row in modules[provider]["public_exports"] if row["symbol"] == symbol), {})
            path = export.get("path", "")
            if (export.get("kind") not in {"construction", "wiring"} or export.get("binding") is not None
                    or not owned_source(provider, path) or path not in provider_inputs):
                raise RddError(f"{label} needs its frozen owned Rust export source consumed by provider checks", "planning")
            if proof["provider_tasks"]:
                if not any(path in tasks.get(tid, {}).get("writes", []) for tid in proof["provider_tasks"]):
                    raise RddError(f"{label} provider tasks omit its exact export source", "planning")
            elif not any(r["path"] == path and r["kind"] == "repository" and r["availability"] == "baseline"
                         for r in resources.values()) or not safe_path(root or Path.cwd(), path).is_file():
                raise RddError(f"{label} empty provider tasks need existing baseline repository export source", "planning")
        for role in roles:
            if not proof[role]:
                if field == "export" and role == "provider_tasks":
                    continue
                raise RddError(f"{label} needs explicit {role}", "planning")
            subset(proof[role], tasks, f"{label} {role}")
            for tid in proof[role]:
                task = tasks[tid]
                if task["phase"] not in phases or phases[task["phase"]] > phases[first_phase]:
                    raise RddError(f"{label} boundary proof precedes its {role} producer {tid}", "planning")
                wanted = {"tests"} if role == "verification_tasks" else {"modification", "addition"}
                if task["category"] not in wanted:
                    raise RddError(f"{label} {role} must name actual {'test' if role == 'verification_tasks' else 'production'} owners", "planning")
                subset(task["solution_elements"], elements, f"{label} task {tid} elements")
            if field == "operation":
                covered = {operation for tid in proof[role] for eid in tasks[tid]["solution_elements"]
                           for operation in operations[eid]}
                if symbol not in covered:
                    raise RddError(f"{label} {role} omits operation ownership", "planning")
            if role == "verification_tasks":
                if any(not set(tasks[tid]["checks"]) & selected for tid in proof[role]):
                    raise RddError(f"{label} verification task lacks its real boundary checks", "planning")
                if field == "export" and any(not set(tasks[tid]["writes"]) & source_inputs(set(tasks[tid]["checks"]) & selected)
                                              for tid in proof[role]):
                    raise RddError(f"{label} verification task has no owned input consumed by its boundary checks", "planning")
                continue
            provider_ids = selected & set(provider_groups["provider"])
            consumer_ids = selected & (set(provider_groups["consumer"]) | set(consumer_groups["consumer"]))
            if field == "export":
                consumer_ids = selected & set(consumer_groups["consumer"])
            role_ids = provider_ids if role == "provider_tasks" else consumer_ids
            if role == "adapter_tasks":
                role_ids |= provider_ids
            dependencies = source_inputs(role_ids)
            owners = {provider} if role == "provider_tasks" else {consumer}
            if role == "adapter_tasks":
                owners.add(provider)
            for tid in proof[role]:
                owned = {path for path in set(tasks[tid]["writes"]) & dependencies
                         if any(owned_source(mid, path) for mid in owners)}
                if not owned:
                    raise RddError(f"{label} {role} task {tid} has no owned Rust boundary source consumed by its checks", "planning")
        production_roles = roles[:-1]
        delivery_phase = max(phases[tasks[tid]["phase"]] for role in production_roles for tid in proof[role])
        if phases[first_phase] != delivery_phase:
            raise RddError(f"{label} proofs must run in its actual provider/consumer/adapter delivery phase", "planning")

    for proof in plan["boundary_proofs"]:
        if "export" in proof:
            validate_proof(proof, "export", expected_exports, actual_exports)
        else:
            validate_proof(proof, "operation", expected_calls, actual_calls)
    for proof in plan["type_import_proofs"]:
        validate_proof(proof, "type", expected_types, actual_types)
    if actual_calls != expected_calls:
        raise RddError(f"Every callable consumer/provider/operation interaction needs real boundary proofs; missing={sorted(expected_calls - actual_calls)}", "planning")
    if actual_types != expected_types:
        raise RddError(f"Every type import consumer/provider/type interaction needs real source proofs; missing={sorted(expected_types - actual_types)}", "planning")
    if actual_exports != expected_exports:
        raise RddError(f"Every composition consumer/provider/export interaction needs real source proofs; missing={sorted(expected_exports - actual_exports)}", "planning")
    for mid, expected in module_checks.items():
        # A local invariant owner needs real source/test evidence even without
        # an interaction. Reuse the phase/task inventories, never invent a call.
        for cid in expected - scheduled[mid]:
            due = next((phases[p["id"]] for p in plan["phases"] if cid in p["checks"]), None)
            if due is None:
                continue
            inputs = {path for path in source_inputs([cid]) if owned_source(mid, path)}
            available = {r["path"] for r in resources.values() if r["availability"] == "baseline"} | {
                path for t in tasks.values() if t["category"] in {"modification", "addition"}
                and phases[t["phase"]] <= due for path in t["writes"]}
            if inputs & available and any(t["category"] == "tests" and cid in t["checks"]
                                          and phases[t["phase"]] <= due for t in tasks.values()):
                scheduled[mid].add(cid)
        if scheduled[mid] != expected:
            raise RddError(f"Module {mid} omits frozen implementation checks: {sorted(expected - scheduled[mid])}", "planning")


def required_probe_ids(spec: dict, plan: dict | None = None) -> list[str]:
    ids = {cid for resource in spec["resources"] if resource["availability"] != "implementation"
           for cid in resource["probe_check_ids"]}
    if plan:
        ids.update(cid for producer in plan["resource_producers"] if producer["kind"] != "task"
                   for cid in producer["checks"])
    return sorted(ids)


def qualification_check_ids(spec: dict, plan: dict | None = None) -> list[str]:
    return sorted(set(spec["contract_check_ids"] + required_probe_ids(spec, plan)))


def preparation_ci_pairs(spec: dict, ids: list[str]) -> set[tuple[str, str]]:
    environments = unique(spec["environments"], "environment")
    pairs = {(check["id"], environments[env]["platform"]) for check in spec["checks"]
             if check["id"] in ids and not check["host_profile"] and check["kind"] != "manual"
             for env in check["environments"]}
    if not pairs or {platform for _, platform in pairs} - HOSTED_RUNNERS.keys():
        raise RddError("Required portable preparation checks need supported hosted platforms", "specification")
    return pairs


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


def verify_readiness_coverage(spec: dict, ids: list[str], receipts: list[dict], *, require_ci: bool = False) -> set[tuple[str, str]]:
    checks = unique(spec["checks"], "check")
    environments = unique(spec["environments"], "environment")
    expected = {(cid, environments[env]["platform"]) for cid in ids for env in checks[cid]["environments"]}
    actual = {(r["check_id"], r["platform"]) for r in receipts}
    if actual != expected:
        raise RddError("Readiness receipts omit a required check/environment execution", "review")
    required_ci = preparation_ci_pairs(spec, ids) if require_ci else set()
    if require_ci:
        observed_ci = {(r["check_id"], r["platform"]) for r in receipts if r["origin"] == "ci"}
        if not required_ci <= observed_ci:
            raise RddError("Preparation lacks actual exact-source CI coverage", "review")
    return required_ci
