"""Requirements traceability, artifact validation, dependency cuts, and task projection."""
from __future__ import annotations

from collections import Counter
import json
import io
import tokenize
from pathlib import Path
import re
from .common import RddError, digest, file_hash, inventory, read_json, safe_path, validate_artifact, atomic_write

CATEGORIES = ("tests", "deletion", "modification", "addition", "documentation")
REQ = re.compile(r"^\*\*((?:FR|NFR)-[A-Z0-9-]+)(?:\s+([^*]+))?\*\*\s*$", re.M)
SITE_MARKER = re.compile(r"RDD:(P[0-9]{2,3}):(tests|deletion|modification|addition|documentation):"
                         r"(V[0-9]{2,4}(?:\+V[0-9]{2,4})*):(T[0-9]{3,6}):(A[0-9]{2,4}) \| (.+)")
LEGACY_MARKER = re.compile(r"RDD:(P[0-9]{2,3}):(T[0-9]{3,6}) \[(tests|deletion|modification|addition|documentation)\] (.+)")
COMMENTS = {".rs": ("// ", ""), ".py": ("# ", ""), ".sh": ("# ", ""),
            ".toml": ("# ", ""), ".yaml": ("# ", ""), ".yml": ("# ", ""),
            ".md": ("<!-- ", " -->"), ".js": ("// ", ""), ".ts": ("// ", ""),
            ".tsx": ("// ", ""), ".css": ("/* ", " */"), ".html": ("<!-- ", " -->")}
INLINE_FORMATS = {".rs", ".py", ".md"}


def requirements(root: Path, rel: str) -> dict:
    path = safe_path(root, rel, allow_missing=False)
    content = path.read_text(encoding="utf-8")
    found = list(REQ.finditer(content))
    if not found:
        raise RddError("No requirement records found; use **FR-001 Title** / **NFR-TECH-001 Title** headings.")
    records = {}
    for i, match in enumerate(found):
        rid = match.group(1)
        if rid in records:
            raise RddError(f"Duplicate requirement ID {rid}")
        end = found[i+1].start() if i+1 < len(found) else len(content)
        block = content[match.end():end].split("\n## ", 1)[0].split("\n### ", 1)[0].strip()
        if not re.search(r"\bshall\b", block, re.I):
            raise RddError(f"{rid} has no normative shall statement")
        if "Acceptance:" not in block:
            raise RddError(f"{rid} has no Acceptance: paragraph")
        records[rid] = {"id": rid, "title": (match.group(2) or "").strip(), "digest": digest(block), "text": block}
    return {"schema_version": 1, "path": rel, "digest": file_hash(path), "records": records}


def unique(items: list[dict], label: str) -> dict[str, dict]:
    result = {}
    for item in items:
        if item["id"] in result:
            raise RddError(f"Duplicate {label} ID {item['id']}")
        result[item["id"]] = item
    return result


def subset(actual, allowed, label):
    missing = set(actual) - set(allowed)
    if missing:
        raise RddError(f"{label}: unknown references {sorted(missing)}")


def topological(graph: dict[str, list[str]]) -> list[str]:
    visited, active, order = set(), [], []
    def visit(node):
        if node in active:
            raise RddError("Dependency cycle: " + " -> ".join(active[active.index(node):] + [node]), "planning")
        if node in visited:
            return
        if node not in graph:
            raise RddError(f"Unknown dependency {node}", "planning")
        active.append(node)
        for dep in graph[node]:
            visit(dep)
        active.pop()
        visited.add(node)
        order.append(node)
    for node in sorted(graph):
        visit(node)
    return order


def ancestors(graph: dict[str, list[str]], node: str) -> set[str]:
    result = set()
    def add(n):
        for dep in graph[n]:
            if dep not in result:
                result.add(dep)
                add(dep)
    add(node)
    return result


def specification_refs(references, documents, label):
    for ref in references:
        if ref.split("#", 1)[0] not in documents:
            raise RddError(f"{label}: specification reference is not in document inventory: {ref}")


def boundary_check_ids(spec: dict, stage: str) -> list[str]:
    """Keep disposable qualification separate from real-adapter acceptance."""
    if stage not in {"qualification", "implementation"}:
        raise RddError(f"Unknown boundary proof stage {stage}")
    return sorted({cid for module in spec["modules"]
                   for ids in module[f"{stage}_checks"].values() for cid in ids})


def module_contracts_validate(root, spec, modules, elements, checks, docs):
    index_path = spec["contract_index_path"]
    if index_path not in spec["generated_files"]:
        raise RddError("Contract descriptor index must belong to exact generated inventory")
    path = safe_path(root, index_path, allow_missing=False)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise RddError("Descriptor index exceeds its 16 MiB validation bound")
    metadata = read_json(path)
    index = metadata.get("contract_index", {}) if isinstance(metadata, dict) else None
    if not isinstance(index, dict) or index.get("schema_version") != 1 or not isinstance(index.get("services"), list):
        raise RddError("Unsupported descriptor-derived contract index")
    source_hashes = index.get("source_hashes", {})
    if not isinstance(source_hashes, dict):
        raise RddError("Descriptor source hashes must be an object")
    sources = {p for p in spec["contract_files"] if p.endswith(".proto")}
    if set(source_hashes) != sources:
        raise RddError("Descriptor index source inventory differs from canonical Protobuf inventory")
    for rel, expected in source_hashes.items():
        if file_hash(safe_path(root, rel, allow_missing=False)) != expected:
            raise RddError(f"Descriptor index is stale for contract source {rel}")
    for key in ("binding_files", "support_files"):
        value = index.get(key)
        if not isinstance(value, list) or any(not isinstance(p, str) for p in value) or len(value) != len(set(value)):
            raise RddError(f"Descriptor {key} must be a unique list of paths")
    bindings, support = set(index["binding_files"]), set(index["support_files"])
    if bindings & support or bindings | support != set(spec["generated_files"]):
        raise RddError("Descriptor index generated inventory mismatch")
    shared = spec["shared_generated_files"]
    shared_paths = {entry["path"] for entry in shared}
    if len(shared_paths) != len(shared) or not support <= shared_paths or not shared_paths <= bindings | support:
        raise RddError("Shared generated support inventory must account for descriptor index support files")
    binding_sources = index.get("binding_sources", {})
    if not isinstance(binding_sources, dict) or set(binding_sources) != bindings or any(
            not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths)
            for paths in binding_sources.values()):
        raise RddError("Descriptor binding source provenance is incomplete")
    services, operations = {}, {}
    for service in index["services"]:
        if not isinstance(service, dict) or not isinstance(service.get("operations"), list):
            raise RddError("Descriptor service inventory must contain operation objects")
        symbol = service.get("symbol")
        if (not isinstance(symbol, str) or not symbol or symbol in services or not isinstance(service.get("source"), str)
                or service["source"] not in sources or not isinstance(service.get("generated_path"), str) or service["generated_path"] not in bindings):
            raise RddError("Descriptor index contains an invalid/duplicate service source or generated binding")
        services[symbol] = service
        for operation in service.get("operations", []):
            if not isinstance(operation, dict):
                raise RddError("Descriptor operation inventory must contain objects")
            oid = operation.get("symbol")
            if not isinstance(oid, str) or not oid or oid in operations or not oid.startswith(symbol + "."):
                raise RddError("Descriptor index contains an invalid/duplicate operation")
            oneofs = operation.get("response_oneofs")
            if not isinstance(oneofs, list) or any(not isinstance(o, dict) or not isinstance(o.get("fields"), list)
                    or any(not isinstance(field, str) for field in o["fields"]) or len(o["fields"]) != len(set(o["fields"])) for o in oneofs):
                raise RddError("Descriptor response outcome inventory is malformed")
            operations[oid] = (symbol, operation)
    if shared_paths & {service["generated_path"] for service in services.values()}:
        raise RddError("Public service bindings require module ownership rather than shared support")
    service_owners, generated = {}, set()
    qualification, implementation = set(), set()
    for module in modules.values():
        mid = module["id"]
        subset(module["provided_services"], services, f"Module {mid} provided services")
        subset(module["consumed_operations"], operations, f"Module {mid} consumed operations")
        subset(module["generated_paths"], bindings, f"Module {mid} generated bindings")
        specification_refs(module["adapter_error_specs"], docs, f"Module {mid} adapter errors")
        for symbol in module["provided_services"]:
            if symbol in service_owners:
                raise RddError(f"Service {symbol} has duplicate module providers")
            service_owners[symbol] = mid
        touched = set(module["provided_services"]) | {operations[o][0] for o in module["consumed_operations"]}
        if not touched:
            raise RddError(f"Module {mid} has no provided or consumed contract boundary")
        expected_paths = {path for path, paths in binding_sources.items() if set(paths) & set(module["contract_paths"])} - shared_paths
        if expected_paths != set(module["generated_paths"]):
            raise RddError(f"Module {mid} generated binding ownership differs from its descriptor sources")
        if any(services[s]["source"] not in module["contract_paths"] for s in touched):
            raise RddError(f"Module {mid} boundary source is absent from its contract_paths")
        generated.update(module["generated_paths"])
        for stage, group_ids in (("qualification", qualification), ("implementation", implementation)):
            for group, ids in module[f"{stage}_checks"].items():
                subset(ids, checks, f"Module {mid} {stage} {group}")
                group_ids.update(ids)
                if stage == "qualification" and any(checks[c]["kind"] != "contract" for c in ids):
                    raise RddError(f"Module {mid} qualification proofs must have kind contract")
                if stage == "implementation" and any(checks[c]["kind"] == "manual" for c in ids):
                    raise RddError(f"Module {mid} actual provider/consumer proofs must be executable")
    if set(service_owners) != set(services):
        raise RddError(f"Public generated services lack exact module ownership: {sorted(set(services) - set(service_owners))}")
    if generated & shared_paths or generated | (shared_paths & bindings) != bindings:
        raise RddError("Generated binding files lack module ownership")
    if not qualification <= set(spec["contract_check_ids"]):
        raise RddError("All module qualification proofs must be prefreeze contract checks")
    if implementation & (qualification | set(spec["contract_check_ids"])):
        raise RddError("Implementation boundary proofs cannot run as prefreeze qualification")
    for module in modules.values():
        for operation in module["consumed_operations"]:
            owner = service_owners[operations[operation][0]]
            if owner != module["id"] and owner not in module["depends_on"]:
                raise RddError(f"Module {module['id']} consumes {operation} against dependency direction")
    represented = set()
    for element in elements.values():
        if element["kind"] != "operation":
            continue
        subset(element["contract_operations"], operations, f"Operation {element['id']} contract symbols")
        for oid in element["contract_operations"]:
            service, operation = operations[oid]
            if service_owners[service] != element["module"]:
                raise RddError(f"Operation {element['id']} contract provider disagrees with its module")
            if not any(len(oneof.get("fields", [])) >= 2 for oneof in operation.get("response_oneofs", [])):
                raise RddError(f"Operation {oid} response requires a schema outcome oneof")
            represented.add(oid)
    if represented != set(operations):
        raise RddError(f"Generated public operations lack solution mappings: {sorted(set(operations) - represented)}")


def target_tree(root: Path, spec: dict) -> dict:
    """The frozen specification owns architecture paths; preparation selects within it."""
    elements = unique(spec["solution_elements"], "solution element")
    paths = {}
    for entry in spec["target_tree"]:
        rel = entry["path"].rstrip("/")
        safe_path(root, rel)
        if rel in paths:
            raise RddError(f"Duplicate target path/owner {rel}", "specification")
        if entry["kind"] == "file" and entry["path"].endswith("/"):
            raise RddError(f"File target cannot end with a directory separator: {rel}")
        if entry["owner"] not in elements:
            raise RddError(f"Target {rel} has an unknown solution owner {entry['owner']}")
        paths[rel] = entry
    for rel in paths:
        for ancestor in Path(rel).parents:
            if ancestor.as_posix() in paths and paths[ancestor.as_posix()]["kind"] != "directory":
                raise RddError(f"Target {rel} has a file ancestor {ancestor}", "specification")
    return paths


def solution_validate(root, spec, req_ids, modules, scenarios, checks, docs):
    elements = unique(spec["solution_elements"], "solution element")
    for element in elements.values():
        eid = element["id"]
        if element["kind"] == "operation" and not element.get("contract_operations"):
            raise RddError(f"Operation {eid} requires contract_operations descriptor mapping")
        if element["kind"] != "operation" and "contract_operations" in element:
            raise RddError(f"Non-operation {eid} cannot declare contract_operations")
        subset(element["requirements"], req_ids, f"solution element {eid}")
        subset(element["scenarios"], scenarios, f"solution element {eid}")
        specification_refs(element["specifications"], docs, eid)
        if element["module"] is not None and element["module"] not in modules:
            raise RddError(f"Solution element {eid}: unknown module {element['module']}")
        if element["kind"] in {"subdomain", "operation", "invariant"} and element["module"] is None:
            raise RddError(f"Domain solution element {eid} requires a module owner")
        if element["module"] is not None and not set(element["requirements"]) <= set(modules[element["module"]]["requirements"]):
            raise RddError(f"Solution element {eid} exceeds its module requirement scope")
        if set(element["scenarios"]) != {s["id"] for s in scenarios.values() if eid in s["solution_elements"]}:
            raise RddError(f"Solution element {eid}: reverse scenario/element coverage mismatch")
        if any(not set(scenarios[s]["requirements"]) & set(element["requirements"]) for s in element["scenarios"]):
            raise RddError(f"Solution element {eid}: scenario has no shared requirement")
        covered = {rid for sid in element["scenarios"] for rid in scenarios[sid]["requirements"]}
        if not set(element["requirements"]) <= covered:
            raise RddError(f"Solution element {eid}: missing requirement scenario coverage")
        if element["behavior"] == "positive":
            golden = {rid for sid in element["scenarios"] if scenarios[sid]["kind"] == "golden"
                      for rid in scenarios[sid]["requirements"]}
            if not {rid for rid in element["requirements"] if rid.startswith("FR-")} <= golden:
                raise RddError(f"Positive {element['kind']} {eid}: missing golden scenario for its requirements")
    for scenario in scenarios.values():
        subset(scenario["solution_elements"], elements, f"scenario {scenario['id']}")
    for rid in req_ids:
        if rid.startswith("FR-") and not any(e["kind"] == "subdomain" and rid in e["requirements"] for e in elements.values()):
            raise RddError(f"{rid}: missing functional owner")
    observed = set()
    for check in checks.values():
        subset(check["scenario_ids"], scenarios, f"check {check['id']} scenario observations")
        for sid in check["scenario_ids"]:
            if check["id"] not in scenarios[sid]["check_ids"]:
                raise RddError(f"Check {check['id']}: scenario observation lacks check backlink {sid}")
        if check["scenario_ids"] and check["kind"] != "manual" and check["results_path"] is None:
            raise RddError(f"Check {check['id']}: scenario observations require a results_path")
        if check["results_path"] is not None:
            safe_path(root, check["results_path"])
            if not check["results_path"].startswith(".rdd/evidence/results/"):
                raise RddError(f"Check {check['id']}: results_path must be under .rdd/evidence/results/")
        observed.update(check["scenario_ids"])
    missing = {s["id"] for s in scenarios.values() if s["kind"] == "golden"} - observed
    if missing:
        raise RddError(f"Missing golden scenario observation checks: {sorted(missing)}")
    paths = target_tree(root, spec)
    claims = []
    for module in modules.values():
        mid = module["id"]
        if not any(element["module"] == mid and element["kind"] == "subdomain"
                   and any(rid.startswith("FR-") for rid in element["requirements"]) for element in elements.values()):
            raise RddError(f"Module {mid} requires a functional subdomain derived from functional requirements")
        covered = {rid for element in elements.values() if element["module"] == mid and element["kind"] == "subdomain"
                   for rid in element["requirements"] if rid.startswith("FR-")}
        missing = {rid for rid in module["requirements"] if rid.startswith("FR-")} - covered
        if missing:
            raise RddError(f"Module {mid} functional subdomains omit requirements {sorted(missing)}")
        if not any(element["module"] == mid for element in elements.values()):
            raise RddError(f"Module {mid} has no represented solution element")
        for rel in module["owns_paths"]:
            key = rel.rstrip("/")
            if key not in paths:
                raise RddError(f"Module {mid} ownership is absent from frozen target tree: {rel}")
            entry = paths[key]
            if elements[entry["owner"]]["module"] != mid:
                raise RddError(f"Module {mid} disagrees with target owner for {rel}")
            claims.append((key, entry["kind"], mid))
    for index, (path, kind, owner) in enumerate(claims):
        for other, other_kind, other_owner in claims[index+1:]:
            if owner != other_owner and (path == other or (kind == "directory" and other.startswith(path + "/"))
                    or (other_kind == "directory" and path.startswith(other + "/"))):
                raise RddError(f"Overlapping module ownership for {path} and {other}")
    for path, entry in paths.items():
        mid = elements[entry["owner"]]["module"]
        if mid is not None and not any(owner == mid and (path == claim or kind == "directory" and path.startswith(claim + "/"))
                                       for claim, kind, owner in claims):
            raise RddError(f"Target {path} is absent from its module {mid} ownership")
    module_contracts_validate(root, spec, modules, elements, checks, docs)
    return elements


def spec_validate(root: Path, spec: dict, reqs: dict, config: dict) -> dict:
    validate_artifact(root, "spec", spec)
    if spec["requirements_digest"] != reqs["digest"]:
        raise RddError("Specification targets different requirements bytes", "specification")
    modules = unique(spec["modules"], "module")
    scenarios = unique(spec["scenarios"], "scenario")
    checks = unique(spec["checks"], "check")
    req_ids = set(reqs["records"])
    docs = spec["documents"] + spec["decisions"]
    if len(set(docs)) != len(docs):
        raise RddError("Specification document inventories overlap or contain duplicates")
    for rel in spec["documents"]:
        if not rel.startswith("docs/specs/"):
            raise RddError(f"Solution documents belong under docs/specs/: {rel}")
    for rel in spec["decisions"]:
        if not rel.startswith("docs/decisions/"):
            raise RddError(f"Decision documents belong under docs/decisions/: {rel}")
    words = 0
    for rel in docs:
        p = safe_path(root, rel, allow_missing=False)
        words += len(p.read_text(encoding="utf-8").split())
        if p.stat().st_size == 0:
            raise RddError(f"Empty specification artifact {rel}")
    if words > config["limits"]["max_spec_words"]:
        raise RddError("Specification exceeds configured word budget; remove duplication or amend budget explicitly")
    for rel in spec["contract_files"] + spec["generated_files"]:
        safe_path(root, rel, allow_missing=False)
    if any(not p.startswith("contracts/") for p in spec["contract_files"]):
        raise RddError("Canonical contract sources belong under contracts/")
    if any(not p.startswith("gen/") for p in spec["generated_files"]):
        raise RddError("Generated contract outputs belong under gen/")
    if not any(p.endswith(".proto") for p in spec["contract_files"]):
        raise RddError("Specification must include actual protobuf sources")
    if set(spec["contract_files"]) & set(spec["generated_files"]):
        raise RddError("Contract source and generated inventories overlap")
    for m in modules.values():
        subset(m["requirements"], req_ids, f"module {m['id']}")
        subset(m["contract_paths"], spec["contract_files"], f"module {m['id']} contracts")
        for rel in m["owns_paths"]:
            safe_path(root, rel)
    topological({m["id"]: m["depends_on"] for m in modules.values()})
    for c in checks.values():
        safe_path(root, c["cwd"])
        if c["kind"] != "manual" and not c["argv"]:
            raise RddError(f"Executable check {c['id']} has no argv")
        if c["kind"] == "manual" and c["argv"]:
            raise RddError(f"Manual check {c['id']} cannot execute a command")
        if c["argv"] and c["argv"][0] in {"true", "echo", "printf", "false"}:
            raise RddError(f"Check {c['id']} uses a vacuous executable")
        if c["red_pattern"]:
            try:
                re.compile(c["red_pattern"])
            except re.error as exc:
                raise RddError(f"Invalid RED pattern for {c['id']}: {exc}") from exc
        if c["kind"] == "benchmark" and not c["metrics"]:
            raise RddError(f"Benchmark {c['id']} requires frozen metric limits")
        if c["kind"] != "benchmark" and c["metrics"]:
            raise RddError(f"Metrics only belong on benchmark checks: {c['id']}")
    subset(spec["contract_check_ids"] + spec["project_check_ids"], checks, "specification checks")
    if any(checks[c]["kind"] != "contract" for c in spec["contract_check_ids"]):
        raise RddError("Contract proofs must have kind contract")
    for s in scenarios.values():
        subset(s["requirements"], req_ids, f"scenario {s['id']}")
        subset(s["check_ids"], checks, f"scenario {s['id']} checks")
    mapping = {}
    for row in spec["requirement_map"]:
        rid = row["requirement"]
        if rid in mapping:
            raise RddError(f"Duplicate traceability row {rid}")
        subset(row["scenarios"], scenarios, rid)
        for reference in row["specifications"]:
            if reference.split("#", 1)[0] not in docs:
                raise RddError(f"{rid}: specification reference is not in document inventory: {reference}")
        if any(rid not in scenarios[s]["requirements"] for s in row["scenarios"]):
            raise RddError(f"{rid}: scenario does not link back to requirement")
        if rid.startswith("FR-") and not any(scenarios[s]["kind"] == "golden" for s in row["scenarios"]):
            raise RddError(f"{rid}: missing golden path")
        mapping[rid] = row
    if set(mapping) != req_ids:
        raise RddError(f"Requirement coverage mismatch; missing={sorted(req_ids-set(mapping))}, extra={sorted(set(mapping)-req_ids)}")
    for rid, row in mapping.items():
        if set(row["scenarios"]) != {s["id"] for s in scenarios.values() if rid in s["requirements"]}:
            raise RddError(f"{rid}: reverse scenario coverage mismatch")
    result = {"requirements": len(req_ids), "modules": len(modules), "scenarios": len(scenarios), "checks": len(checks), "words": words}
    if spec["schema_version"] == 2:
        result["solution_elements"] = len(solution_validate(root, spec, req_ids, modules, scenarios, checks, docs))
    return result


def protected(rel: str, config: dict, spec: dict) -> bool:
    return (rel in config["protected_files"] or rel.startswith(tuple(config["protected_prefixes"]))
            or rel in spec["contract_files"] or rel in spec["generated_files"])


def task_sites(task: dict) -> list[dict]:
    if "sites" in task:
        return task["sites"]
    return [dict(task["anchor"], id="A01", primary=True,
                 placement=dict(kind="append", context=None), instructions=task["title"])]


def site_path(task: dict, site: dict) -> str:
    if site["mode"] == "inline":
        return site["path"]
    return site["path"] + ".rdd.md" if "sites" in task else f".rdd/plan/anchors/{task['id']}.md"


def anchor_paths(task: dict) -> list[str]:
    return sorted({site_path(task, site) for site in task_sites(task)})


def placement_offset(text: str, placement: dict, label: str) -> int:
    context = placement["context"]
    if placement["kind"] == "append":
        if context is not None:
            raise RddError(f"{label}: append placement cannot have context")
        return len(text)
    if not context or not context.strip():
        raise RddError(f"{label}: before/after placement requires nonempty unique context")
    # Match logical lines while retaining byte-identical source line endings.
    # Lookahead detects overlapping regions too (A/A/A contains A/A twice).
    context = context.replace("\r\n", "\n").rstrip("\r\n")
    pattern = r"\r?\n".join(re.escape(line) for line in context.split("\n"))
    positions = [(match.start(), match.start() + len(match.group(1)))
                 for match in re.finditer("(?=(" + pattern + "))", text)
                 if (match.start() == 0 or text[match.start()-1] == "\n")
                 and (match.start() + len(match.group(1)) == len(text)
                      or text.startswith(("\n", "\r\n"), match.start() + len(match.group(1))))]
    if len(positions) != 1:
        raise RddError(f"{label}: placement context must identify exactly one complete source region; found {len(positions)}")
    start, end = positions[0]
    if placement["kind"] == "before":
        return start
    return end + (2 if text.startswith("\r\n", end) else 1) if end < len(text) else end


def sites_validate(root, task, target, shells, plan, config, spec):
    sites = unique(task["sites"], f"site for {task['id']}")
    if sum(site["primary"] for site in sites.values()) != 1:
        raise RddError(f"Task {task['id']} requires exactly one primary site")
    if {site["path"] for site in sites.values()} != set(task["writes"]):
        raise RddError(f"Every write for {task['id']} requires at least one site within its declared writes")
    for site in sites.values():
        path = safe_path(root, site["path"])
        rel = site_path(task, site)
        safe_path(root, rel)
        if protected(rel, config, spec):
            raise RddError(f"Site {task['id']}:{site['id']} writes a frozen/policy path {rel}")
        if site["mode"] == "inline" and Path(site["path"]).suffix not in COMMENTS:
            raise RddError(f"Task {task['id']} needs a sidecar for this file format")
        if site["mode"] == "inline" and Path(site["path"]).suffix not in INLINE_FORMATS:
            raise RddError(f"Inline marker lexical safety is unsupported for {site['path']}; use an adjacent sidecar")
        if task["category"] == "deletion" and site["mode"] != "sidecar":
            raise RddError(f"Deletion {task['id']} requires an adjacent sidecar")
        if site["mode"] == "sidecar":
            if rel in target or rel in shells:
                raise RddError(f"Adjacent sidecar path collision: {rel}")
            sidecar = safe_path(root, rel)
            if sidecar.exists():
                text = sidecar.read_text(encoding="utf-8")
                parsed = parse_markers(text, rel)
                recognized = {item["line_number"] for item in parsed}
                if any(line.strip() and index not in recognized for index, line in enumerate(text.splitlines())):
                    raise RddError(f"Adjacent sidecar path collision with an existing file: {rel}")
                expected = {marker_line(t, s, plan) for t in plan["tasks"] for s in task_sites(t)
                            if site_path(t, s) == rel}
                if any(item["line"] not in expected for item in parsed):
                    raise RddError(f"Adjacent sidecar path collision with an unknown marker: {rel}")
            if site["placement"]["kind"] != "append":
                raise RddError(f"Sidecar {rel} requires append placement")
        text = path.read_text(encoding="utf-8") if path.is_file() and site["mode"] == "inline" else ""
        # Existing marker payloads must not count as copies of the context selector.
        if text:
            text = "\n".join(line for line in text.splitlines() if "RDD:" not in line)
        placement_offset(text, site["placement"], f"Site {task['id']}:{site['id']}")


def element_coverage_validate(plan, spec, tasks, checks):
    elements = unique(spec["solution_elements"], "solution element")
    scenarios = unique(spec["scenarios"], "scenario")
    rows = {}
    for row in plan["element_coverage"]:
        eid = row["element"]
        if eid in rows:
            raise RddError(f"Duplicate element coverage row {eid}")
        subset([eid], elements, "element coverage")
        subset(row["tasks"], tasks, f"element coverage {eid}")
        subset(row["checks"], checks, f"element coverage {eid}")
        rows[eid] = row
    if set(rows) != set(elements):
        raise RddError(f"Incomplete element coverage; missing {sorted(set(elements)-set(rows))}")
    for task in tasks.values():
        subset(task["solution_elements"], elements, task["id"])
        subset(task["scenarios"], scenarios, task["id"])
        if not set(task["requirements"]) <= {r for eid in task["solution_elements"] for r in elements[eid]["requirements"]}:
            raise RddError(f"Task {task['id']} requirements exceed its solution elements")
        if not set(task["scenarios"]) <= {s for eid in task["solution_elements"] for s in elements[eid]["scenarios"]}:
            raise RddError(f"Task {task['id']} scenarios exceed its solution elements")
    scheduled = {c for phase in plan["phases"] for c in phase["checks"]}
    for eid, row in rows.items():
        actual = {t["id"] for t in tasks.values() if eid in t["solution_elements"]}
        if set(row["tasks"]) != actual:
            raise RddError(f"Task/element coverage mismatch for {eid}")
        if not actual and not row["baseline_evidence"]:
            raise RddError(f"Element {eid} needs planned tasks or explicit baseline evidence")
        required = {c for sid in elements[eid]["scenarios"] for c in scenarios[sid]["check_ids"]}
        if not required <= set(row["checks"]) or not set(row["checks"]) <= scheduled:
            raise RddError(f"Element {eid} lacks planned scenario check coverage")
        if actual and not set(elements[eid]["scenarios"]) <= {s for tid in actual for s in tasks[tid]["scenarios"]}:
            raise RddError(f"Element {eid} lacks task scenario coverage")


def plan_validate(root: Path, plan: dict, spec: dict, lock: dict, config: dict) -> dict:
    validate_artifact(root, "plan", plan)
    if plan["spec_digest"] != lock["digest"]:
        raise RddError("Plan targets a different specification freeze", "specification")
    tasks, phases = unique(plan["tasks"], "task"), unique(plan["phases"], "phase")
    checks = unique(spec["checks"], "check")
    req_ids = {row["requirement"] for row in spec["requirement_map"]}
    if len(tasks) > config["limits"]["max_tasks"] or len(phases) > config["limits"]["max_phases"]:
        raise RddError("Plan exceeds configured task or phase budget")
    phase_ids = list(phases)
    if phase_ids != [f"P{i:02d}" for i in range(1, len(phases)+1)]:
        raise RddError("Phases must be sequential P01, P02, ... in document order", "planning")
    rank = {p: i for i, p in enumerate(phases)}
    target = set(plan["target_paths"])
    for rel in target:
        safe_path(root, rel)
    shells = {}
    for shell in plan["shells"]:
        if shell["path"] in shells:
            raise RddError(f"Duplicate shell {shell['path']}")
        shells[shell["path"]] = shell
        if shell["path"] not in target:
            raise RddError(f"Shell is absent from target inventory: {shell['path']}")
        if protected(shell["path"], config, spec):
            raise RddError(f"Preparation cannot create a shell over frozen/policy path {shell['path']}")
        if not shell_is_empty(shell["path"], shell["content"]):
            raise RddError(f"Shell {shell['path']} contains behavior; preparation permits empty or comment-only shells")
    graph = {t["id"]: t["depends_on"] for t in tasks.values()}
    order = topological(graph)
    declared_writes = {p for task in tasks.values() for p in task["writes"]}
    unowned_shells = set(shells) - declared_writes
    if unowned_shells:
        raise RddError("Every shell needs an implementation task; unowned shells: " + ", ".join(sorted(unowned_shells)))
    if plan["schema_version"] == 2 and spec.get("schema_version") != 2:
        raise RddError("A v2 plan requires a v2 frozen specification; create a fresh reviewed baseline", "specification")
    approved = target_tree(root, spec) if plan["schema_version"] == 2 else None
    if approved is not None:
        if spec["schema_version"] != 2:
            raise RddError("A v2 plan requires a v2 frozen specification")
        for rel in target:
            if rel.rstrip("/") not in approved:
                raise RddError(f"Preparation path is absent from frozen target tree: {rel}", "specification")
        element_coverage_validate(plan, spec, tasks, checks)
    for t in tasks.values():
        subset(t["requirements"], req_ids, t["id"])
        subset(t["checks"], checks, t["id"])
        if t["phase"] not in phases:
            raise RddError(f"Unknown phase for {t['id']}")
        for ref in t["specifications"]:
            if ref.split("#", 1)[0] not in spec["documents"] + spec["decisions"]:
                raise RddError(f"Unknown specification reference for {t['id']}: {ref}")
        if approved is not None:
            sites_validate(root, t, target, shells, plan, config, spec)
        for rel in t["writes"]:
            safe_path(root, rel)
            if protected(rel, config, spec):
                raise RddError(f"Task {t['id']} writes a frozen/policy path {rel}", "planning")
            if rel not in target:
                raise RddError(f"Task {t['id']} writes a file absent from target inventory: {rel}")
            if approved is not None:
                entry = approved[rel.rstrip("/")]
                if entry["kind"] != "file" or entry["owner"] not in t["solution_elements"]:
                    raise RddError(f"Task {t['id']} write does not match frozen target owner/kind: {rel}")
                if entry["disposition"] in {"retain", "generated"}:
                    raise RddError(f"Task {t['id']} cannot write frozen {entry['disposition']} target {rel}")
                if (entry["disposition"] == "delete") != (t["category"] == "deletion"):
                    raise RddError(f"Task {t['id']} deletion category disagrees with frozen target disposition {rel}")
                if Path(rel).suffix not in COMMENTS:
                    if rel in shells:
                        raise RddError(f"Noncommentable target {rel} must remain absent; use only an adjacent sidecar")
                    continue
                if rel in shells and not shells[rel]["content"].strip():
                    raise RddError(f"New commentable target {rel} requires a real comment-only shell")
            if not (root / rel).is_file() and rel not in shells and t["category"] != "deletion":
                raise RddError(f"Missing file {rel} needs an explicit preparation shell")
        if approved is None:
            if t["anchor"]["path"] not in t["writes"]:
                raise RddError(f"Task {t['id']} anchor must identify one of its declared write files")
            if t["anchor"]["mode"] == "inline" and Path(t["anchor"]["path"]).suffix not in COMMENTS:
                raise RddError(f"Task {t['id']} needs a sidecar for this file format")
        if t["category"] == "tests" and not any(checks[c]["red_pattern"] for c in t["checks"]):
            raise RddError(f"Test task {t['id']} needs a behavioral RED check")
        if t["category"] == "addition" and t["reuse"] is None:
            raise RddError(f"Addition {t['id']} lacks examined reuse candidates and rationale")
        for dep in t["depends_on"]:
            before = tasks[dep]
            if rank[before["phase"]] > rank[t["phase"]]:
                raise RddError(f"{t['id']} depends on a future phase task {dep}", "planning")
            if before["phase"] == t["phase"] and CATEGORIES.index(before["category"]) > CATEGORIES.index(t["category"]):
                raise RddError(f"Strict category cycle: {dep} ({before['category']}) before {t['id']} ({t['category']}); move the prerequisite to an earlier phase", "planning")
    listed, closure = [], {}
    cumulative_checks = set()
    for pid, phase in phases.items():
        for rel in phase["deliverables"]:
            safe_path(root, rel)
            if rel not in target:
                raise RddError(f"Phase {pid} deliverable is absent from target inventory: {rel}")
        subset(phase["tasks"], tasks, pid)
        subset(phase["checks"], checks, pid)
        subset(phase["requirements_closed"], req_ids, pid)
        if set(phase["tasks"]) != {t["id"] for t in tasks.values() if t["phase"] == pid}:
            raise RddError(f"Phase/task membership mismatch for {pid}")
        listed += phase["tasks"]
        cumulative_checks.update(phase["checks"])
        for tid in phase["tasks"]:
            if not set(tasks[tid]["checks"]) <= cumulative_checks:
                raise RddError(f"{tid}: phase lacks declared check coverage")
        for rid in phase["requirements_closed"]:
            if rid in closure:
                raise RddError(f"Requirement {rid} closes more than once")
            if any(rank[t["phase"]] > rank[pid] and rid in t["requirements"] for t in tasks.values()):
                raise RddError(f"{rid} closes before its last implementation task", "planning")
            scenario_checks = {c for s in spec["scenarios"] if rid in s["requirements"] for c in s["check_ids"]}
            if not scenario_checks <= cumulative_checks:
                raise RddError(f"{rid} closes without all scenario checks")
            closure[rid] = pid
    if set(closure) != req_ids:
        raise RddError(f"Every requirement needs one closure phase; missing {sorted(req_ids-set(closure))}")
    if any(n != 1 for n in Counter(listed).values()):
        raise RddError("A task is assigned more than once")
    covered = set()
    unique(plan["verticals"], "vertical")
    for vertical in plan["verticals"]:
        subset(vertical["tasks"], tasks, vertical["id"])
        covered.update(vertical["tasks"])
        for before, after in zip(vertical["tasks"], vertical["tasks"][1:]):
            if before not in ancestors(graph, after):
                raise RddError(f"Vertical {vertical['id']}: {before} is not an ordered prerequisite of {after}")
    if covered != set(tasks):
        raise RddError(f"Tasks missing from verticals: {sorted(set(tasks)-covered)}")
    if not set(spec["project_check_ids"]) <= cumulative_checks:
        raise RddError("Phases do not schedule every project check")
    return {"tasks": len(tasks), "phases": len(phases), "verticals": len(plan["verticals"]), "topological_order": order}


def shell_is_empty(path: str, content: str) -> bool:
    """Preparation creates no executable behavior, including in test shells."""
    if not content.strip():
        return True
    suffix = Path(path).suffix
    if suffix not in COMMENTS:
        return False
    before, after = (part.strip() for part in COMMENTS[suffix])
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith(before):
            return False
        if after:
            body = stripped[len(before):]
            close = body.find(after)
            # Only one whole comment per line is allowed. Matching just the
            # outer prefix/suffix would permit executable text between comments.
            if close < 0 or body[close + len(after):].strip():
                return False
            # HTML also recognizes malformed --!> closes; keep its comments
            # within the strict syntax instead of depending on parser recovery.
            if before == "<!--" and "--" in body[:close]:
                return False
    return True


def anchor_path(task: dict) -> str:
    return site_path(task, next(site for site in task_sites(task) if site["primary"]))


def task_verticals(plan: dict, task: dict) -> list[str]:
    return sorted(v["id"] for v in plan["verticals"] if task["id"] in v["tasks"])


def marker_payload(task: dict, site: dict) -> dict:
    primary = next(s for s in task_sites(task) if s["primary"])
    payload = dict(instructions=site["instructions"], path=site["path"],
                   primary_site=site_path(task, primary) + "#" + primary["id"])
    if site["primary"]:
        payload["task"] = task
    return payload


def payload_json(payload: dict) -> str:
    # Escape comment terminators and marker prefixes without changing decoded data.
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            .replace("--", "\\u002d\\u002d").replace("*/", "\\u002a/").replace("RDD:", "RDD\\u003a"))


def marker_line(task: dict, site: dict | None = None, plan: dict | None = None) -> str:
    site = site or next(s for s in task_sites(task) if s["primary"])
    prefix, suffix = COMMENTS[Path(site_path(task, site)).suffix]
    if "sites" not in task:
        title = task["title"].replace("\n", " ").replace("--", "-").replace("*/", "")
        return f"{prefix}RDD:{task['phase']}:{task['id']} [{task['category']}] {title} | requirements={','.join(task['requirements'])}{suffix}"
    if Path(site_path(task, site)).suffix not in INLINE_FORMATS:
        raise RddError(f"Inline marker lexical safety is unsupported for {site_path(task, site)}; use an adjacent sidecar")
    if plan is None:
        raise RddError("V2 marker projection requires its canonical vertical inventory")
    verticals = task_verticals(plan, task)
    if not verticals or any(not re.fullmatch(r"V[0-9]{2,4}", v) for v in verticals):
        raise RddError(f"Task {task['id']} has invalid or missing canonical vertical membership")
    return (f"{prefix}RDD:{task['phase']}:{task['category']}:{'+'.join(verticals)}:{task['id']}:{site['id']} | "
            + payload_json(marker_payload(task, site)) + suffix)


def _comment_lines(text: str, suffix: str) -> set[int]:
    """Bounded supported source lexing; other formats use adjacent Markdown sidecars."""
    if suffix == ".py":
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
            if any(token.type == tokenize.ERRORTOKEN and token.string.strip() for token in tokens):
                raise RddError("Cannot establish Python marker lexical context in an invalid token region")
            return {token.start[0]-1 for token in tokens
                    if token.type == tokenize.COMMENT and token.start[1] == 0}
        except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
            raise RddError(f"Cannot establish Python marker lexical context: {exc}") from exc
    if suffix == ".md":
        comments, fence, html = set(), None, False
        for index, line in enumerate(text.splitlines()):
            match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
            if match and not html:
                token, trailing = match.groups()
                if fence is None:
                    fence = token
                elif token[0] == fence[0] and len(token) >= len(fence) and not trailing.strip():
                    fence = None
                continue
            if fence is not None:
                continue
            if not html and line.startswith("<!-- "):
                comments.add(index)
            for token in re.findall(r"<!--|-->", line):
                html = token == "<!--"
        if fence is not None or html:
            raise RddError("Cannot establish marker lexical context in an unclosed Markdown code/comment region")
        return comments
    if suffix != ".rs":
        raise RddError("Inline marker lexical safety is unsupported; use an adjacent sidecar")
    comments, index, line, column = set(), 0, 0, 0
    state, delimiter, depth = "code", "", 0
    while index < len(text):
        current = text[index]
        if state == "raw":
            if text.startswith(delimiter, index):
                index += len(delimiter); column += len(delimiter); state = "code"
                continue
        elif state == "string":
            if current == "\\":
                if index + 1 < len(text) and text[index+1] == "\n":
                    line += 1; column = 0
                else:
                    column += 2
                index += 2
                continue
            if current == '"':
                state = "code"
        elif state == "block":
            if text.startswith("/*", index):
                depth += 1; index += 2; column += 2
                continue
            if text.startswith("*/", index):
                depth -= 1; index += 2; column += 2
                if depth == 0:
                    state = "code"
                continue
        else:
            if text.startswith("//", index):
                if column == 0:
                    comments.add(line)
                end = text.find("\n", index)
                if end < 0:
                    break
                index = end  # Process the newline normally.
                current = "\n"
            elif text.startswith("/*", index):
                state, depth = "block", 1; index += 2; column += 2
                continue
            else:
                raw = re.match(r'(?:br|cr|r)(#*)"', text[index:]) if index == 0 or not (text[index-1].isalnum() or text[index-1] == "_") else None
                char = re.match(r"'(?:[^'\\\n]|\\(?:.|u\{[0-9a-fA-F_]+\}))'", text[index:])
                if raw:
                    delimiter = '"' + raw.group(1); state = "raw"
                    index += raw.end(); column += raw.end()
                    continue
                if char:
                    index += char.end(); column += char.end()
                    continue
                if current == '"':
                    state = "string"
        if current == "\n":
            line += 1; column = 0
        else:
            column += 1
        index += 1
    if state != "code":
        raise RddError(f"Cannot establish Rust marker lexical context in an unclosed {state}")
    return comments


def parse_markers(text: str, rel: str) -> list[dict]:
    """Recognize complete canonical comment lines, rejecting all marker-like code/data."""
    result = []
    eligible = _comment_lines(text, Path(rel).suffix) if "RDD:" in text else set()
    for index, line in enumerate(text.splitlines()):
        if "RDD:" not in line:
            continue
        if index not in eligible:
            raise RddError(f"Malformed task marker in code/string context {rel}:{index+1}")
        comment = COMMENTS.get(Path(rel).suffix)
        if comment is None:
            raise RddError(f"Malformed task marker in noncommentable file {rel}:{index+1}")
        prefix, suffix = comment
        if not line.startswith(prefix) or (suffix and not line.endswith(suffix)):
            raise RddError(f"Malformed task marker in {rel}:{index+1}")
        body = line[len(prefix):len(line)-len(suffix) if suffix else None]
        if line.count("RDD:") != 1:
            raise RddError(f"Multiple task anchors share one line in {rel}:{index+1}")
        match = SITE_MARKER.fullmatch(body)
        if match:
            phase, category, vertical_text, tid, sid, encoded = match.groups()
            verticals = vertical_text.split("+")
            try:
                payload = json.loads(encoded)
            except (ValueError, TypeError) as exc:
                raise RddError(f"Malformed task marker payload in {rel}:{index+1}") from exc
            if (not isinstance(payload, dict) or payload_json(payload) != encoded
                    or verticals != sorted(set(verticals))):
                raise RddError(f"Malformed noncanonical task marker in {rel}:{index+1}")
        else:
            legacy = LEGACY_MARKER.fullmatch(body)
            if legacy is None:
                raise RddError(f"Malformed task marker in {rel}:{index+1}")
            phase, tid, category, payload = legacy.groups()
            verticals, sid = [], "A01"
        result.append(dict(phase=phase, category=category, verticals=verticals, task=tid, site=sid,
                           payload=payload, line=line, line_number=index))
    return result


def _scan_markers(root: Path, plan: dict) -> dict:
    expected = {(task["id"], site["id"]): (site_path(task, site), marker_line(task, site, plan))
                for task in plan["tasks"] for site in task_sites(task)}
    scan = {path for path, _ in expected.values()}
    scan.update(path for path in plan.get("target_paths", []) if not path.endswith("/"))
    found = {}
    for rel in sorted(scan):
        path = safe_path(root, rel)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            if b"RDD:" in path.read_bytes():
                raise RddError(f"Malformed task marker in binary target {rel}")
            continue  # Binary target bytes are preserved; its adjacent sidecar is text.
        for item in parse_markers(text, rel):
            key = (item["task"], item["site"])
            if key not in expected or expected[key] != (rel, item["line"]):
                raise RddError(f"Orphaned or misplaced anchor {item['phase']}:{item['task']}:{item['site']} in {rel}")
            if key in found:
                raise RddError(f"Duplicate anchor/site for {item['task']}:{item['site']} in {rel}")
            found[key] = item
    return found


def materialize(root: Path, plan: dict, state: dict, *, create_shells: bool = True) -> list[str]:
    found = _scan_markers(root, plan)  # Validate before changing any file.
    created = []
    updates = {}
    for shell in (plan["shells"] if create_shells else []):
        path = safe_path(root, shell["path"])
        if not path.exists():
            if plan.get("schema_version") == 2 and Path(shell["path"]).suffix not in COMMENTS:
                raise RddError(f"Noncommentable target {shell['path']} must remain absent; use only an adjacent sidecar")
            updates[shell["path"]] = shell["content"]
            created.append(shell["path"])
    for task in plan["tasks"]:
        if state["tasks"][task["id"]]["status"] == "done":
            continue
        for site in task_sites(task):
            key = (task["id"], site["id"])
            if key in found:
                continue
            rel = site_path(task, site)
            path = safe_path(root, rel)
            if (task["category"] == "deletion" and site["mode"] == "inline"
                    and state["tasks"][task["id"]]["status"] == "integrated" and not path.exists()):
                continue
            if site["mode"] == "inline" and not path.exists() and rel not in updates:
                raise RddError(f"Missing inline work site requires an explicit preparation shell: {rel}")
            text = updates.get(rel, path.read_bytes().decode("utf-8") if path.exists() else "")
            if site["mode"] == "sidecar" and text:
                parsed = parse_markers(text, rel)
                recognized = {p["line_number"] for p in parsed}
                if any(line.strip() and i not in recognized for i, line in enumerate(text.splitlines())):
                    raise RddError(f"Adjacent sidecar path collision: {rel}")
            offset = placement_offset(text, site["placement"], f"Site {task['id']}:{site['id']}")
            first_newline = re.search(r"\r?\n", text)
            newline = first_newline.group() if first_newline else "\n"
            lead = newline if offset and text[offset-1] != "\n" else ""
            updates[rel] = text[:offset] + lead + marker_line(task, site, plan) + newline + text[offset:]
    for rel in plan["target_paths"]:
        if rel.endswith("/"):
            safe_path(root, rel).mkdir(parents=True, exist_ok=True)
    for rel, text in updates.items():
        atomic_write(safe_path(root, rel), text.encode("utf-8"))
    return created


def remove_anchor(root: Path, task: dict, plan: dict | None = None) -> None:
    if plan is not None:
        _scan_markers(root, plan)
    updates = {}
    own_sites = {site["id"]: site for site in task_sites(task)}
    for rel in anchor_paths(task):
        path = safe_path(root, rel)
        if not path.exists():
            continue
        text = path.read_bytes().decode("utf-8")
        parsed = parse_markers(text, rel)
        removed = set()
        for item in parsed:
            if item["task"] != task["id"]:
                continue
            site = own_sites.get(item["site"])
            if (site is None or site_path(task, site) != rel or item["phase"] != task["phase"]
                    or item["category"] != task["category"]):
                raise RddError(f"Orphaned or misplaced anchor for {task['id']} in {rel}")
            if "sites" in task and item["payload"] != marker_payload(task, site):
                raise RddError(f"Altered task marker payload for {task['id']}:{site['id']} in {rel}")
            if plan is not None or "sites" not in task:
                if item["line"] != marker_line(task, site, plan):
                    raise RddError(f"Altered task marker metadata for {task['id']}:{site['id']} in {rel}")
            if item["site"] in removed:
                raise RddError(f"Duplicate anchor/site for {task['id']}:{site['id']} in {rel}")
            removed.add(item["site"])
        indices = {item["line_number"] for item in parsed if item["task"] == task["id"]}
        updates[rel] = "".join(line for index, line in enumerate(text.splitlines(keepends=True)) if index not in indices)
    for rel, text in updates.items():
        path = safe_path(root, rel)
        is_sidecar = any(site["mode"] == "sidecar" and site_path(task, site) == rel for site in task_sites(task))
        if is_sidecar and not text.strip():
            path.unlink()
        else:
            atomic_write(path, text.encode("utf-8"))


def anchors_verify(root: Path, plan: dict, state: dict) -> dict:
    found = _scan_markers(root, plan)
    for task in plan["tasks"]:
        status = state["tasks"][task["id"]]["status"]
        for site in task_sites(task):
            present = (task["id"], site["id"]) in found
            if status == "done" and present:
                raise RddError(f"Completed task still has an anchor: {task['id']}:{site['id']}")
            if status != "done" and not present:
                if (task["category"] == "deletion" and status == "integrated" and site["mode"] == "inline"
                        and not safe_path(root, site["path"]).exists()):
                    continue
                raise RddError(f"Unfinished task {task['id']} requires exactly one anchor at site {site['id']}; found 0")
    return {"remaining": len(found), "orphaned": 0}


def implementation_matrix(plan: dict) -> str:
    lines = ["# Implementation matrix", "", "Generated from the frozen task manifest. Runtime status is reported by `./rdd status`.", "",
             "| Phase | Task | Category | Requirements | Writes | Dependencies |", "| --- | --- | --- | --- | --- | --- |"]
    for t in plan["tasks"]:
        lines.append("| " + " | ".join([t["phase"], t["id"], t["category"], ", ".join(t["requirements"]),
                                        ", ".join(t["writes"]), ", ".join(t["depends_on"]) or "None"]) + " |")
    return "\n".join(lines) + "\n"
