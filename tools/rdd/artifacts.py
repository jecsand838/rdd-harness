"""Requirements traceability, artifact validation, dependency cuts, and task projection."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from .common import RddError, digest, file_hash, inventory, read_json, safe_path, validate_artifact, atomic_write

CATEGORIES = ("tests", "deletion", "modification", "addition", "documentation")
REQ = re.compile(r"^\*\*((?:FR|NFR)-[A-Z0-9-]+)(?:\s+([^*]+))?\*\*\s*$", re.M)
MARKER = re.compile(r"RDD:(P\d{2,3}):(T\d{3,6})\b")
COMMENTS = {".rs": ("// ", ""), ".py": ("# ", ""), ".sh": ("# ", ""),
            ".toml": ("# ", ""), ".yaml": ("# ", ""), ".yml": ("# ", ""),
            ".md": ("<!-- ", " -->"), ".js": ("// ", ""), ".ts": ("// ", ""),
            ".tsx": ("// ", ""), ".css": ("/* ", " */"), ".html": ("<!-- ", " -->")}


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
    return {"requirements": len(req_ids), "modules": len(modules), "scenarios": len(scenarios), "checks": len(checks), "words": words}


def protected(rel: str, config: dict, spec: dict) -> bool:
    return (rel in config["protected_files"] or rel.startswith(tuple(config["protected_prefixes"]))
            or rel in spec["contract_files"] or rel in spec["generated_files"])


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
    for t in tasks.values():
        subset(t["requirements"], req_ids, t["id"])
        subset(t["checks"], checks, t["id"])
        if t["phase"] not in phases:
            raise RddError(f"Unknown phase for {t['id']}")
        for ref in t["specifications"]:
            if ref.split("#", 1)[0] not in spec["documents"] + spec["decisions"]:
                raise RddError(f"Unknown specification reference for {t['id']}: {ref}")
        for rel in t["writes"]:
            safe_path(root, rel)
            if protected(rel, config, spec):
                raise RddError(f"Task {t['id']} writes a frozen/policy path {rel}", "planning")
            if rel not in target:
                raise RddError(f"Task {t['id']} writes a file absent from target inventory: {rel}")
            if not (root / rel).is_file() and rel not in shells:
                raise RddError(f"Missing file {rel} needs an explicit preparation shell")
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
    return task["anchor"]["path"] if task["anchor"]["mode"] == "inline" else f".rdd/plan/anchors/{task['id']}.md"


def marker_line(task: dict) -> str:
    prefix, suffix = COMMENTS[Path(anchor_path(task)).suffix]
    title = task["title"].replace("\n", " ").replace("--", "-").replace("*/", "")
    return f"{prefix}RDD:{task['phase']}:{task['id']} [{task['category']}] {title} | requirements={','.join(task['requirements'])}{suffix}"


def materialize(root: Path, plan: dict, state: dict, *, create_shells: bool = True) -> list[str]:
    created = []
    for rel in plan["target_paths"]:
        if rel.endswith("/"):
            safe_path(root, rel).mkdir(parents=True, exist_ok=True)
    for shell in (plan["shells"] if create_shells else []):
        path = safe_path(root, shell["path"])
        if not path.exists():
            atomic_write(path, shell["content"].encode())
            created.append(shell["path"])
    for task in plan["tasks"]:
        if state["tasks"][task["id"]]["status"] != "done":
            path = safe_path(root, anchor_path(task))
            if (task["category"] == "deletion" and state["tasks"][task["id"]]["status"] == "integrated"
                    and not path.exists()):
                continue
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            matching = [m for m in MARKER.finditer(text) if m.group(2) == task["id"]]
            if len(matching) > 1:
                raise RddError(f"Duplicate anchor for {task['id']}")
            if not matching:
                atomic_write(path, (text + ("\n" if text and not text.endswith("\n") else "") + marker_line(task) + "\n").encode())
    return created


def remove_anchor(root: Path, task: dict) -> None:
    path = safe_path(root, anchor_path(task))
    if not path.exists():
        return  # A deletion task can remove its own inline anchor with the file.
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    identity = (task["phase"], task["id"])
    retained = []
    for line in lines:
        identities = [match.groups() for match in MARKER.finditer(line)]
        if identity in identities:
            # Match whole task IDs: T001 must never remove a T0010 marker.
            # A malformed shared marker line needs investigation, not data loss.
            if any(other != identity for other in identities):
                raise RddError(f"Multiple task anchors share one line in {anchor_path(task)}")
            continue
        retained.append(line)
    atomic_write(path, "".join(retained).encode())


def anchors_verify(root: Path, plan: dict, state: dict) -> dict:
    tasks = {t["id"]: t for t in plan["tasks"]}
    scan = {anchor_path(t) for t in plan["tasks"]}
    scan.update(t for t in plan["target_paths"] if not t.endswith("/"))
    occurrences = {}
    for rel in sorted(scan):
        path = safe_path(root, rel)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in MARKER.finditer(text):
            phase, tid = match.groups()
            if tid not in tasks or phase != tasks[tid]["phase"] or rel != anchor_path(tasks[tid]):
                raise RddError(f"Orphaned or misplaced anchor {phase}:{tid} in {rel}")
            occurrences.setdefault(tid, []).append(rel)
    for tid, task in tasks.items():
        status = state["tasks"][tid]["status"]
        count = len(occurrences.get(tid, []))
        if status == "done" and count:
            raise RddError(f"Completed task still has an anchor: {tid}")
        if status != "done" and count != 1:
            # A submitted deletion may already have removed the file, but is not completed by that alone.
            if task["category"] == "deletion" and status == "integrated" and count == 0:
                continue
            raise RddError(f"Unfinished task {tid} requires exactly one anchor; found {count}")
    return {"remaining": sum(len(v) for v in occurrences.values()), "orphaned": 0}


def implementation_matrix(plan: dict) -> str:
    lines = ["# Implementation matrix", "", "Generated from the frozen task manifest. Runtime status is reported by `./rdd status`.", "",
             "| Phase | Task | Category | Requirements | Writes | Dependencies |", "| --- | --- | --- | --- | --- | --- |"]
    for t in plan["tasks"]:
        lines.append("| " + " | ".join([t["phase"], t["id"], t["category"], ", ".join(t["requirements"]),
                                        ", ".join(t["writes"]), ", ".join(t["depends_on"]) or "None"]) + " |")
    return "\n".join(lines) + "\n"
