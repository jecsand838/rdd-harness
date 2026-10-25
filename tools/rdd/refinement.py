"""Versioned material choices, canonical publication and scoped freshness.

This is a bounded extension of the existing run record, not a second workflow or
approval ledger. Reviewer finding status remains owned by the review stream.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import re
import time

from .common import RddError, canonical, digest, event, file_hash, read_json, safe_path, write_json

SNAPSHOT_PATH = "docs/specs/refinement.json"
POLICY = digest({"refinement": 1, "provenance": "declared-evidence", "inputs": "operative-scoped-v1",
                 "history": "event-array-prefix-v2", "publication": "one-canonical-v1", "snapshot": "s6-closure-output-v1"})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
_SHA = re.compile(r"[0-9a-f]{64}")


def _error(message):
    raise RddError("Refinement: " + message, "specification")


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or set(value) - set(required) - set(optional):
        _error("invalid or unknown record fields")


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        _error(label + " needs precise nonempty text")


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _error("invalid stable identity")


def _revision(value):
    if type(value) is not int or value < 1:
        _error("revision must be a positive integer")


def _ref(value):
    _keys(value, ("id", "revision"))
    _id(value["id"])
    _revision(value["revision"])


def _strings(value, label):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value) or len(value) != len(set(value)):
        _error(label + " must be unique strings")


def _source(root, value):
    _keys(value, ("path", "sha256"), ("text",))
    safe_path(root, value["path"])
    if value["path"] == SNAPSHOT_PATH or value["path"].startswith((".rdd/runtime/", ".rdd/evidence/")) or value["path"] == ".rdd/run.json":
        _error("snapshots and runtime receipts cannot govern refinement")
    if not isinstance(value["sha256"], str) or not _SHA.fullmatch(value["sha256"]):
        _error("source needs its exact SHA256")
    if "text" in value:
        _text(value["text"], "source excerpt")
        if hashlib.sha256(value["text"].encode()).hexdigest() != value["sha256"]:
            _error("source excerpt digest differs")


def _observed(root, source):
    path = safe_path(root, source["path"])
    if "text" in source:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return "MISSING"
        return source["sha256"] if text.count(source["text"]) == 1 else "CHANGED"
    return file_hash(path) if path.is_file() else "MISSING"


def _sources(row):
    result = list(row.get("sources", []))
    provenance = row.get("provenance", {})
    if provenance.get("kind") == "inherited":
        result.append({k: provenance[k] for k in ("path", "sha256", "text")})
    if provenance.get("kind") == "delegated":
        result.append(provenance["authority"])
    return result


def new_state():
    return {"schema_version": 1, "policy": POLICY, "questions": [], "decisions": [], "publications": []}


def _latest(rows):
    return {row["id"]: row for row in rows}


def _find(rows, reference):
    return next((r for r in rows if r["id"] == reference["id"] and r["revision"] == reference["revision"]), None)


def _question(root, row):
    _keys(row, ("id", "revision", "previous_revision", "issue", "material", "sources", "requirements", "nodes",
                "status", "options", "recommended_option", "disposition", "decision", "finding"))
    _text(row["issue"], "question")
    if row["material"] is not True or not isinstance(row["status"], str) or row["status"] not in {"open", "resolved", "deferred"}:
        _error("invalid question materiality/status")
    if not isinstance(row["disposition"], str) or not isinstance(row["options"], list):
        _error("invalid question disposition/options")
    options = []
    for option in row["options"]:
        _keys(option, ("id", "text"))
        _id(option["id"])
        _text(option["text"], "option")
        options.append(option["id"])
    if len(options) != len(set(options)):
        _error("duplicate displayed option")
    if row["recommended_option"] is not None and row["recommended_option"] not in options:
        _error("recommendation must bind a displayed option")
    if row["decision"] is not None:
        _ref(row["decision"])
    if row["finding"] is not None:
        _id(row["finding"])
    if row["status"] == "deferred" and not row["disposition"].strip():
        _error("deferral requires allowed discretion and its obligations-preserving rationale")
    if row["status"] == "resolved" and not (row["decision"] or row["finding"]):
        _error("resolved question must reference accepted decision or reviewer finding")


def _decision(root, row):
    _keys(row, ("id", "revision", "previous_revision", "statement", "sources", "requirements", "nodes", "prerequisites", "provenance"))
    _text(row["statement"], "accepted meaning")
    if not isinstance(row["prerequisites"], list):
        _error("invalid decision prerequisites")
    for reference in row["prerequisites"]:
        _ref(reference)
        if reference["id"] == row["id"]:
            _error("decision cannot depend on itself")
    if len({r["id"] for r in row["prerequisites"]}) != len(row["prerequisites"]):
        _error("duplicate decision prerequisite")
    provenance = row["provenance"]
    kind = provenance.get("kind") if isinstance(provenance, dict) else None
    fields = {"choice": ("kind", "question", "revision", "option", "turn", "text", "qualifications"),
              "direct": ("kind", "turn", "text", "qualifications"),
              "inherited": ("kind", "path", "sha256", "text"),
              "delegated": ("kind", "authority", "scope", "rationale")}
    if not isinstance(kind, str) or kind not in fields:
        _error("acceptance needs truthful choice, direct, inherited or delegated provenance")
    _keys(provenance, fields[kind])
    if kind in {"direct", "choice"}:
        for key in ("turn", "text"):
            _text(provenance[key], "actual user " + key)
        if not isinstance(provenance["qualifications"], str):
            _error("qualifications must be preserved text")
    if kind == "choice":
        _id(provenance["question"])
        _id(provenance["option"])
        _revision(provenance["revision"])
    if kind == "inherited":
        _source(root, {k: provenance[k] for k in ("path", "sha256", "text")})
    if kind == "delegated":
        _source(root, provenance["authority"])
        _text(provenance["scope"], "authorized scope")
        _text(provenance["rationale"], "technical rationale")


def validate_budget(config, value, *, packet=False):
    # Count JSON tokens as well as prose; compact JSON must not bypass budgets.
    encoded = canonical(value).decode()
    if packet and len(encoded) > config["limits"]["max_packet_characters"]:
        raise RddError("Refinement record exceeds configured packet budget", "budget")
    if len(re.findall(r"\w+|[^\w\s]", encoded)) > config["limits"]["max_spec_words"]:
        raise RddError("Refinement exceeds configured specification content budget", "budget")


def _history(state):
    """Validate and locate immutable revisions using event array order, not sequence."""
    refinement = state["refinement"]
    if any(not isinstance(refinement.get(name), list) for name in ("questions", "decisions", "publications")):
        _error("invalid immutable history inventory")
    if not isinstance(state.get("events"), list) or any(not isinstance(e, dict) for e in state["events"]):
        _error("invalid audit history")
    positions = {}
    counts = {name: 0 for name in ("questions", "decisions", "publications")}
    for position, entry in enumerate(state.get("events", [])):
        if entry.get("action") != "refinement_recorded":
            continue
        name, index = entry.get("collection"), entry.get("index")
        if not isinstance(name, str) or name not in counts or type(index) is not int or index != counts[name] or index >= len(refinement[name]):
            _error("omitted, duplicated or reordered revision event")
        record = refinement[name][index]
        if entry.get("record_digest") != digest(record):
            _error("revision event differs from immutable evidence")
        positions[(name, index)] = position
        counts[name] += 1
    if any(counts[name] != len(refinement[name]) for name in counts):
        _error("revision history lacks its audit events")
    return positions


def validate_state(root, state, config):
    value = state.get("refinement")
    _keys(value, ("schema_version", "policy", "questions", "decisions", "publications"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["policy"] != POLICY:
        _error("unsupported refinement policy; preserve history and use its matching harness")
    positions = _history(state)
    requirement_ids = set(read_json(root / ".rdd/requirements.index.json")["records"])
    from .nodes import NODES
    for name, validator in (("questions", _question), ("decisions", _decision)):
        rows = value[name]
        seen = {}
        for index, entry in enumerate(rows):
            _keys(entry, ("record", "session_id"))
            _text(entry["session_id"], "declared author session")
            if entry["session_id"] not in state.get("authors", {}).get("specification", []):
                _error("refinement actor is absent from the existing author inventory")
            row = entry["record"]
            validator(root, row)
            _id(row["id"])
            _revision(row["revision"])
            previous = seen.get(row["id"], 0)
            if (row["revision"] != previous + 1 or (row["previous_revision"] is not None if not previous else
                    type(row["previous_revision"]) is not int or row["previous_revision"] != previous)):
                _error("revision history is not an ordered immutable chain")
            seen[row["id"]] = row["revision"]
            _strings(row["requirements"], "requirements")
            _strings(row["nodes"], "affected nodes")
            if set(row["requirements"]) - requirement_ids or set(row["nodes"]) - set(NODES):
                _error("unknown affected requirement/node")
            if not isinstance(row["sources"], list):
                _error("invalid source inventory")
            for source in _sources(row):
                _source(root, source)
            if len({digest(s) for s in row["sources"]}) != len(row["sources"]):
                _error("duplicate source reference")
            before = positions[(name, index)]
            available_decisions = [e["record"] for j, e in enumerate(value["decisions"])
                                   if positions[("decisions", j)] < before]
            if name == "questions":
                if row["decision"] and not _find(available_decisions, row["decision"]):
                    _error("question resolution lacks its preceding accepted revision")
                if row["finding"] and (row["finding"] not in state.get("live_findings", {}) or not any(
                        e.get("action") == "live_review_recorded" and row["finding"] in e.get("findings", [])
                        for e in state["events"][:before])):
                    _error("question references a reviewer finding that was not recorded before it")
                if row["finding"] and row["status"] == "open" and any(
                        e.get("action") == "live_review_recorded" and row["finding"] in e.get("resolved", [])
                        for e in state["events"][:before]):
                    _error("an open question cannot reuse an already resolved reviewer finding; record the new concern")
            else:
                for reference in row["prerequisites"]:
                    if not _find(available_decisions, reference) or _latest(available_decisions)[reference["id"]]["revision"] != reference["revision"]:
                        _error("decision prerequisite was missing or superseded before acceptance")
                provenance = row["provenance"]
                if provenance["kind"] == "choice":
                    questions = [e["record"] for j, e in enumerate(value["questions"])
                                 if positions[("questions", j)] < before]
                    question = _find(questions, {"id": provenance["question"], "revision": provenance["revision"]})
                    if not question or not any(o["id"] == provenance["option"] for o in question["options"]):
                        _error("acceptance does not bind a displayed question and option revision")
                    if _latest(questions)[question["id"]]["revision"] != question["revision"]:
                        _error("acceptance selected a superseded displayed question")
    publications = value["publications"]
    seen = {}
    for index, pub in enumerate(publications):
        _publication(root, pub)
        reference = pub["decision"]
        previous = seen.get(reference["id"], 0)
        if (pub["revision"] != previous + 1 or (pub["previous_revision"] is not None if not previous else
                type(pub["previous_revision"]) is not int or pub["previous_revision"] != previous)):
            _error("publication revision history is invalid")
        seen[reference["id"]] = pub["revision"]
        decisions = [e["record"] for j, e in enumerate(value["decisions"])
                     if positions[("decisions", j)] < positions[("publications", index)]]
        decision = _find(decisions, reference)
        if not decision or _latest(decisions)[reference["id"]]["revision"] != reference["revision"]:
            _error("canonical publication selected a missing or superseded accepted revision")
        if decision["statement"] != pub["text"]:
            _error("canonical statement differs from accepted operative meaning")
        claim = _publication_claim(state, pub)
        matching = [i for i, e in enumerate(state.get("events", [])) if e.get("action") == "workflow_node_claimed"
                    and e.get("node") == pub["claim"]["node"] and e.get("attempt") == claim["attempt"]
                    and e.get("session") == claim["session_id"]]
        publication_position = positions[("publications", index)]
        if len(matching) != 1 or matching[0] >= publication_position:
            _error("publication lacks its preceding unique author claim")
        if any(e.get("node") == pub["claim"]["node"] and e.get("action") in
               {"workflow_node_released", "workflow_node_completed", "workflow_node_claimed"}
               for e in state["events"][matching[0] + 1:publication_position]):
            _error("publication was recorded outside its active author claim interval")
        dependencies = {}
        for entry in state["events"][:publication_position]:
            if entry.get("action") == "workflow_node_completed" and entry.get("node") in NODES[pub["claim"]["node"]]["depends_on"]:
                dependencies[entry["node"]] = digest(entry.get("outputs"))
        if (not isinstance(claim.get("inputs"), dict) or not isinstance(claim.get("sources"), dict)
                or claim["inputs"].get("dependencies") != dependencies
                or claim["inputs"].get("refinement") != node_projection(
                    root, state, pub["claim"]["node"], publication_position, claim["sources"])):
            _error("publication author claim inputs changed before publication")
    validate_budget(config, value)
    return positions


def _publication(root, pub):
    _keys(pub, ("decision", "revision", "previous_revision", "path", "text", "scenarios", "sha256", "claim"))
    _ref(pub["decision"])
    _revision(pub["revision"])
    _text(pub["text"], "canonical statement")
    safe_path(root, pub["path"])
    if pub["path"] == SNAPSHOT_PATH or not pub["path"].startswith(("docs/specs/", "docs/decisions/")):
        _error("canonical publication must be a specification section or ADR, never the snapshot")
    _strings(pub["scenarios"], "publication scenario links")
    if not isinstance(pub["claim"], dict) or not isinstance(pub["claim"].get("node"), str):
        _error("publication needs a valid author node")
    from .nodes import NODES, DERIVED
    if pub["claim"]["node"] not in NODES or not pub["claim"]["node"].startswith("S") or pub["claim"]["node"] in DERIVED:
        _error("publication needs a specification author node")
    if not isinstance(pub["sha256"], str) or not _SHA.fullmatch(pub["sha256"]):
        _error("publication needs exact output hash")
    _keys(pub["claim"], ("node", "attempt", "session_id", "input_digest"))
    _revision(pub["claim"]["attempt"])
    _text(pub["claim"]["session_id"], "publication author session")
    if not isinstance(pub["claim"]["input_digest"], str) or not _SHA.fullmatch(pub["claim"]["input_digest"]):
        _error("publication needs exact claim inputs")


def _publication_claim(state, pub):
    binding = pub["claim"]
    row = state.get("workflow_nodes", {}).get(binding["node"], {})
    matching = [a["claim"] for a in row.get("attempts", []) if a.get("claim", {}).get("attempt") == binding["attempt"]]
    if len(matching) != 1:
        _error("publication author claim is missing")
    claim = matching[0]
    if any(claim.get(k) != binding[k] for k in ("session_id", "attempt", "input_digest")) or pub["path"] not in claim["writes"]:
        _error("publication does not belong to its declared bounded author claim")
    return claim


def _rows(state, name, position=None):
    if position is None:
        return [entry["record"] for entry in state["refinement"][name]]
    positions = _history(state)
    return [entry["record"] for i, entry in enumerate(state["refinement"][name]) if positions[(name, i)] < position]


def _operative_question(row):
    # Explicit question revisions govern work; review-stream resolution does not
    # mutate these records and therefore cannot self-stale a corrective claim.
    return {key: row[key] for key in ("id", "revision", "issue", "material", "sources", "requirements", "nodes", "options", "recommended_option")}


def node_projection(root, state, node, position=None, sources=None):
    """Compact governing identities; evidence text stays in the canonical history."""
    questions = _rows(state, "questions", position)
    decisions = _rows(state, "decisions", position)
    def relevant(rows, identity):
        # Retain prior scopes so narrowing cannot resurrect old work.
        return any(not r["nodes"] or node in r["nodes"] for r in rows if r["id"] == identity)
    q = [r for identity, r in _latest(questions).items() if relevant(questions, identity)]
    current = _latest(decisions)
    selected = {identity for identity in current if relevant(decisions, identity)}
    pending = list(selected)
    while pending:
        for reference in current[pending.pop()]["prerequisites"]:
            if reference["id"] not in selected:
                selected.add(reference["id"])
                pending.append(reference["id"])
    d = [current[identity] for identity in sorted(selected)]
    observed = {}
    for row in q + d:
        for source in _sources(row):
            if position is not None:
                actual = (sources or {}).get(source["path"], "MISSING")
                if "text" in source and _SHA.fullmatch(str(actual)):
                    actual = source["sha256"]
            else:
                actual = _observed(root, source)
            identity = digest(source)
            observed[identity] = {"source_digest": identity, "path": source["path"], "sha256": source["sha256"],
                                  "excerpt": "text" in source, "observed": actual}
    return {"policy": POLICY,
            "questions": [{"id": r["id"], "revision": r["revision"], "operative_digest": digest(_operative_question(r))}
                          for r in sorted(q, key=lambda r: r["id"])],
            "decisions": [{"id": r["id"], "revision": r["revision"], "operative_digest": digest(r)} for r in d],
            "sources": [observed[key] for key in sorted(observed)]}


def closure(root, state, spec=None):
    """Current material completeness; does not include receipts or lifecycle fields."""
    value = state["refinement"]
    questions = _latest([r["record"] for r in value["questions"]])
    decisions = _latest([r["record"] for r in value["decisions"]])
    publications = {p["decision"]["id"]: p for p in value["publications"]}
    unresolved, unpublished, stale = [], [], []
    for identity, question in questions.items():
        finding = state.get("live_findings", {}).get(question["finding"]) if question["finding"] else None
        decision = question["decision"]
        unresolved_choice = (not finding.get("resolution") if finding is not None else
                             question["status"] == "open" or
                             (decision and decisions[decision["id"]]["revision"] != decision["revision"]))
        if question["material"] and unresolved_choice:
            unresolved.append(identity)
        if any(_observed(root, s) != s["sha256"] for s in question["sources"]):
            stale.append("question:" + identity)
    projected = []
    scenarios = {s["id"]: s for s in (spec or {}).get("scenarios", [])}
    for identity, decision in decisions.items():
        if any(decisions[r["id"]]["revision"] != r["revision"] for r in decision["prerequisites"]) or any(
                _observed(root, source) != source["sha256"] for source in _sources(decision)):
            stale.append(identity)
        pub = publications.get(identity)
        if not pub or pub["decision"]["revision"] != decision["revision"]:
            unpublished.append(identity)
            pub = None
        elif spec is not None:
            path = safe_path(root, pub["path"])
            if pub["path"] not in spec.get("documents", []) + spec.get("decisions", []):
                stale.append(identity)
            try:
                text = path.read_text(encoding="utf-8")
                if text.count(pub["text"]) != 1:
                    stale.append(identity)
            except (OSError, UnicodeError):
                stale.append(identity)
            if (not pub["scenarios"] or set(pub["scenarios"]) - set(scenarios)
                    or not set(decision["requirements"]) <= {r for sid in pub["scenarios"] if sid in scenarios for r in scenarios[sid]["requirements"]}):
                stale.append(identity)
        # Publication records retain the observed output hash; closure checks canonical text.
        # Other sections of the same document may evolve in later authorized claims.
        projected.append({"id": identity, "revision": decision["revision"], "statement_digest": digest(decision["statement"]),
                          "provenance_digest": digest(decision["provenance"]), "sources": _sources(decision),
                          "requirements": decision["requirements"], "nodes": decision["nodes"],
                          "prerequisites": decision["prerequisites"], "publication": pub})
    # Supersession and stale governing evidence propagate through prerequisites.
    changed = True
    while changed:
        changed = False
        for identity, decision in decisions.items():
            if identity not in stale and any(r["id"] in stale for r in decision["prerequisites"]):
                stale.append(identity)
                changed = True
    body = {"schema_version": 1, "policy": POLICY, "run_id": state["id"], "requirements_digest": state["requirements_digest"],
            "question_sources": sorted({digest(s): s for q in questions.values() for s in q["sources"]}.values(), key=digest),
            "questions_digest": digest([{**q, "finding_resolved": bool(state.get("live_findings", {}).get(q["finding"], {}).get("resolution"))}
                                         for q in questions.values()]),
            "decisions": sorted(projected, key=lambda r: r["id"])}
    return {"snapshot": {**body, "closure_digest": digest(body)}, "schema_version": 1,
            "questions": len(questions), "decisions": len(decisions), "unresolved": sorted(set(unresolved)),
            "unpublished": sorted(set(unpublished)), "stale": sorted(set(stale)),
            "ready": not (unresolved or unpublished or stale), "closure_digest": digest(body)}


def validate_snapshot(root, value, reqs=None, spec=None):
    """Stateless source/candidate proof, also usable by trusted CI without runtime."""
    _keys(value, ("schema_version", "policy", "run_id", "requirements_digest", "questions_digest", "question_sources", "decisions", "closure_digest"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["policy"] != POLICY:
        _error("snapshot policy differs")
    _id(value["run_id"])
    for key in ("requirements_digest", "questions_digest", "closure_digest"):
        if not isinstance(value[key], str) or not _SHA.fullmatch(value[key]):
            _error("invalid snapshot digest")
    if value["closure_digest"] != digest({k: v for k, v in value.items() if k != "closure_digest"}):
        _error("snapshot closure digest differs")
    if reqs is not None and value["requirements_digest"] != reqs["digest"]:
        _error("snapshot requirements differ")
    if spec is not None and value["run_id"] != spec["id"]:
        _error("snapshot belongs to another specification")
    if not isinstance(value["decisions"], list) or not isinstance(value["question_sources"], list):
        _error("invalid snapshot decision/source inventory")
    for source in value["question_sources"]:
        _source(root, source)
        if _observed(root, source) != source["sha256"]:
            _error("snapshot question source changed")
    seen = set()
    for row in value["decisions"]:
        _keys(row, ("id", "revision", "statement_digest", "provenance_digest", "sources", "requirements", "nodes", "prerequisites", "publication"))
        _id(row["id"])
        _revision(row["revision"])
        if row["id"] in seen:
            _error("duplicate snapshot decision")
        seen.add(row["id"])
        for key in ("statement_digest", "provenance_digest"):
            if not isinstance(row[key], str) or not _SHA.fullmatch(row[key]):
                _error("invalid snapshot operative identity")
        _strings(row["requirements"], "snapshot requirements")
        _strings(row["nodes"], "snapshot nodes")
        if reqs is not None and set(row["requirements"]) - set(reqs["records"]):
            _error("snapshot refers to unknown requirements")
        from .nodes import NODES
        if any(n not in NODES for n in row["nodes"]):
            _error("snapshot refers to unknown affected nodes")
        if not isinstance(row["sources"], list) or not isinstance(row["prerequisites"], list):
            _error("invalid snapshot prerequisites")
        for reference in row["prerequisites"]:
            _ref(reference)
        for source in row["sources"]:
            _source(root, source)
            if _observed(root, source) != source["sha256"]:
                _error("snapshot governing source changed")
        pub = row["publication"]
        _publication(root, pub)
        if pub["decision"] != {"id": row["id"], "revision": row["revision"]} or digest(pub["text"]) != row["statement_digest"]:
            _error("snapshot publication differs from accepted revision")
        try:
            text = safe_path(root, pub["path"], allow_missing=False).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            _error("cannot read canonical publication: " + str(exc))
        if text.count(pub["text"]) != 1:
            _error("canonical published output changed")
        if spec is not None:
            scenarios = {s["id"]: s for s in spec["scenarios"]}
            if (pub["path"] not in spec["documents"] + spec["decisions"] or not pub["scenarios"]
                    or set(pub["scenarios"]) - set(scenarios)
                    or not set(row["requirements"]) <= {r for sid in pub["scenarios"] if sid in scenarios for r in scenarios[sid]["requirements"]}):
                _error("snapshot publication lacks its inventoried home or requirement-linked scenarios")
    for row in value["decisions"]:
        for reference in row["prerequisites"]:
            if not _find(value["decisions"], reference):
                _error("snapshot decision prerequisite was superseded")
    return value


class RefinementWorkflow:
    def spec_refine(self, file: Path):
        self.guard_source_write(baseline=True)
        state = self.state()
        if state["status"] != "specification" or state.get("spec_digest"):
            _error("frozen choices require a new amendment specification run")
        try:
            input_size = file.stat().st_size
        except OSError as exc:
            raise RddError("Cannot read refinement input: " + str(exc)) from exc
        if input_size > self.config["limits"]["max_packet_characters"]:
            raise RddError("Refinement input exceeds configured packet budget", "budget")
        request = read_json(file)
        _keys(request, ("schema_version", "operation", "session_id", "record"))
        if type(request["schema_version"]) is not int or request["schema_version"] != 1 or not isinstance(request["operation"], str) or request["operation"] not in {"question", "decision", "publish"}:
            _error("unsupported mutation")
        _text(request["session_id"], "actual author session")
        self.guard_author_identity(request["session_id"])
        validate_budget(self.config, request, packet=True)
        state = copy.deepcopy(state)
        operation, row = request["operation"], copy.deepcopy(request["record"])
        if not isinstance(row, dict):
            _error("mutation needs a record")
        if operation in {"question", "decision"}:
            defaults = {"sources": [], "requirements": [], "nodes": []}
            defaults.update({"status": "open", "options": [], "recommended_option": None, "disposition": "", "decision": None, "finding": None}
                            if operation == "question" else {"prerequisites": []})
            for key, value in defaults.items():
                row.setdefault(key, value)
            name = "questions" if operation == "question" else "decisions"
            entry = {"record": row, "session_id": request["session_id"]}
        else:
            _keys(row, ("decision", "revision", "previous_revision", "path", "text", "scenarios"))
            _ref(row["decision"])
            claims = [(n, r) for n, r in state.get("workflow_nodes", {}).items()
                      if n.startswith("S") and r.get("status") == "claimed" and r.get("claim", {}).get("session_id") == request["session_id"]
                      and row["path"] in r["claim"]["writes"]]
            if len(claims) != 1:
                _error("publication needs its current matching specialist author claim")
            node, claimed = claims[0]
            claim = claimed["claim"]
            if claim["expires"] < time.time() or claim["input_digest"] != digest(self._node_input(state, node, self._node_records(state))):
                _error("publication author claim expired or its inputs changed")
            path = safe_path(self.root, row["path"], allow_missing=False)
            _text(row["text"], "canonical statement")
            try:
                output_text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise RddError("Cannot read canonical publication: " + str(exc)) from exc
            if output_text.count(row["text"]) != 1:
                _error("canonical output must contain the exact accepted statement once")
            row.update(sha256=file_hash(path), claim={"node": node, **{k: claim[k] for k in ("attempt", "session_id", "input_digest")}})
            name, entry = "publications", row
        index = len(state["refinement"][name])
        state["refinement"][name].append(entry)
        event(state, "refinement_recorded", collection=name, index=index, record_digest=digest(entry))
        authors = state.setdefault("authors", {}).setdefault("specification", [])
        if request["session_id"] not in authors:
            authors.append(request["session_id"])
        validate_state(self.root, state, self.config)
        # Capture validates currently cited evidence; historical entries are retained inline.
        if operation != "publish" and any(_observed(self.root, s) != s["sha256"] for s in _sources(row)):
            _error("accepted source does not match its cited revision")
        self.save(state)
        return {"operation": operation, "id": row["decision"]["id"] if operation == "publish" else row["id"],
                "revision": row["revision"], "status": "recorded"}

    def refinement_status(self, state):
        result = closure(self.root, state, self.spec() if (self.root / ".rdd/spec.json").is_file() else None)
        return {k: v for k, v in result.items() if k != "snapshot"}

    def require_refinement(self, state=None, *, snapshot=True):
        state = state or self.state()
        validate_state(self.root, state, self.config)
        spec = self.spec()
        result = closure(self.root, state, spec)
        if not result["ready"]:
            _error("material choices remain unresolved, unpublished or stale: " + str({k: result[k] for k in ("unresolved", "unpublished", "stale")}))
        if SNAPSHOT_PATH not in spec["documents"]:
            _error("prelist the refinement snapshot in spec.documents")
        if snapshot:
            actual = read_json(safe_path(self.root, SNAPSHOT_PATH, allow_missing=False))
            validate_snapshot(self.root, actual, spec=spec)
            if actual != result["snapshot"]:
                _error("snapshot differs from current runtime closure; materialize it under S6")
        return result

    def spec_snapshot(self, session_id):
        self.guard_source_write(baseline=True)
        state = self.state()
        if state["status"] != "specification" or state.get("spec_digest"):
            _error("frozen snapshots require an amendment specification run")
        row = state.get("workflow_nodes", {}).get("S6", {})
        claim = row.get("claim", {})
        if (row.get("status") != "claimed" or claim.get("session_id") != session_id
                or SNAPSHOT_PATH not in claim.get("writes", []) or claim.get("expires", 0) < time.time()
                or claim.get("input_digest") != digest(self._node_input(state, "S6", self._node_records(state)))):
            _error("snapshot needs the current S6 session, attempt and claimed output path")
        result = self.require_refinement(state, snapshot=False)
        path = safe_path(self.root, SNAPSHOT_PATH)
        write_json(path, result["snapshot"])
        self.require_refinement(state)
        return {"path": SNAPSHOT_PATH, "sha256": file_hash(path), "closure_digest": result["closure_digest"], "status": "ready"}
