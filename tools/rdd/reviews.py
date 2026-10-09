"""Continuous independent observations; final gates bind their complete cursor."""
from pathlib import Path

from .common import RddError, digest, event, head, read_json, safe_path, source_digest, validate_artifact, write_json


class ReviewStream:
    def record_final_findings(self, review: dict, stage: str, phase: str | None = None) -> None:
        """Final-review issues join the immutable repair ledger; later pass cannot erase them."""
        self.guard_run_policy()
        state = self.state(allow_blocked=True)
        findings = []
        for incoming in review["findings"]:
            finding = dict(incoming)
            finding.setdefault("nodes", ["S6" if stage == "specification" else "P5" if stage == "preparation" else "I2"])
            existing = state.get("live_findings", {}).get(finding["id"])
            if existing:
                if existing["finding"] != finding:
                    raise RddError("Final finding cannot overwrite a preserved live finding", "review")
            else:
                findings.append(finding)
        if not findings:
            return
        candidate = review.get("candidate", review)
        observation = {key: review[key] for key in ("model", "reviewer", "session_id", "summary")}
        observation.update(schema_version=2, kind="live", stage=stage, phase=phase,
            requirements_digest=state["requirements_digest"], spec_digest=state.get("spec_digest"), plan_digest=state.get("plan_digest"),
            source_commit=candidate["source_commit"], source_digest=candidate["source_digest"], findings=findings, resolutions=[])
        path = self.root / ".rdd/runtime/final-findings.json"
        write_json(path, observation)
        self.review_live_record(path)

    def review_stage(self, state: dict) -> str:
        status = state.get("resume_status") if state["status"] == "blocked" else state["status"]
        return ("specification" if status == "specification" else "preparation"
                if status in {"specified", "planned", "preparing", "prepared"} else "implementation")

    def guard_author_identity(self, session: str) -> None:
        state = self.state(allow_blocked=True)
        reviewers = {e["review"]["session_id"] for e in state.get("live_reviews", [])}
        reviewers.update(r["session_id"] for reviews in state.get("stage_reviews", {}).values() for r in reviews.values())
        reviewers.update(r["session_id"] for r in state.get("reviews", {}).values())
        if session in reviewers:
            raise RddError("A reviewer session cannot become an author in the same run", "review")

    def review_live_record(self, file: Path) -> dict:
        self.guard_v2()
        self.guard_run_policy()
        review = read_json(file)
        validate_artifact(self.root, "live-review", review)
        state = self.state(allow_blocked=True)
        if review["stage"] != self.review_stage(state) or review["phase"] != (
                state.get("active_phase") if review["stage"] == "implementation" else None):
            raise RddError("Live review stage/phase does not match active authority", "review")
        if review["source_commit"] != head(self.root) or review["source_digest"] != source_digest(self.root):
            raise RddError("Live observation is stale; review the actual current draft", "review")
        if (review["requirements_digest"] != state["requirements_digest"]
                or review["spec_digest"] != state.get("spec_digest") or review["plan_digest"] != state.get("plan_digest")):
            raise RddError("Live observation references different authority", "review")
        if review["reviewer"] != "rdd_reviewer" or review["model"] != self.profile_settings("rdd_reviewer")["model"]:
            raise RddError("Live review needs the configured independent reviewer", "review")
        authors = {s for sessions in state.get("authors", {}).values() for s in sessions}
        authors.update(t.get("session_id") for t in state["tasks"].values())
        if review["session_id"] in authors:
            raise RddError("Live reviewer cannot be an author or implementor", "review")
        if review["phase"] is not None and review["phase"] not in state["phases"]:
            raise RddError("Live review phase is unknown", "review")
        findings = state.setdefault("live_findings", {})
        sequence = len(state.setdefault("live_reviews", [])) + 1
        incoming = {finding["id"] for finding in review["findings"]}
        resolved = {resolution["finding_id"] for resolution in review["resolutions"]}
        if (len(incoming) != len(review["findings"]) or len(resolved) != len(review["resolutions"])
                or incoming & resolved):
            raise RddError("Live findings/resolutions need distinct stable identities")
        for finding in review["findings"]:
            if finding["id"] in findings:
                raise RddError("Preserve prior findings; use an independent resolution rather than overwriting them")
            if finding["path"]:
                safe_path(self.root, finding["path"])
            from .artifacts import subset
            from .nodes import NODES
            subset(finding.get("nodes", []), NODES, "live finding nodes")
            subset(finding["tasks"], state["tasks"], "live finding tasks")
            subset(finding["requirements"], read_json(self.root / ".rdd/requirements.index.json")["records"], "live finding requirements")
        for resolution in review["resolutions"]:
            if resolution["finding_id"] not in findings or findings[resolution["finding_id"]].get("resolution"):
                raise RddError("Resolution must identify an existing unresolved finding")
        for finding in review["findings"]:
            findings[finding["id"]] = {"finding": finding, "stage": review["stage"], "phase": review["phase"],
                "sequence": sequence, "reviewer_session": review["session_id"], "resolution": None}
        for resolution in review["resolutions"]:
            findings[resolution["finding_id"]]["resolution"] = {**resolution, "sequence": sequence,
                "source_commit": review["source_commit"], "source_digest": review["source_digest"], "reviewer_session": review["session_id"]}
        node_outputs = {n: r["output_digest"] for n, r in self._node_records(state).items()
                        if r["status"] == "complete" and "output_digest" in r}
        task_outputs = {tid: row["commit"] for tid, row in state["tasks"].items() if row["status"] == "done"}
        entry = {"sequence": sequence, "review": review, "node_outputs": node_outputs, "task_outputs": task_outputs}
        entry["digest"] = digest(entry)
        state["live_reviews"].append(entry)
        path = f".rdd/evidence/reviews/live-{sequence:05d}-{entry['digest']}.json"
        write_json(self.root / path, entry)
        event(state, "live_review_recorded", sequence=sequence, findings=sorted(incoming), resolved=sorted(resolved))
        self.save(state)
        return {"review_cursor": sequence, "path": path, "unresolved": [fid for fid, f in findings.items() if not f["resolution"]]}

    def live_review_guard(self, *, final: bool, cursor: int | None = None, stage: str | None = None,
                          node: str | None = None, correction: str | None = None, task: str | None = None,
                          repair_findings: frozenset[str] = frozenset()) -> None:
        state = self.state(allow_blocked=True)
        stage = stage or self.review_stage(state)
        reviews = state.get("live_reviews", [])
        relevant = [e for e in reviews if e["review"]["stage"] == stage
                    and (stage != "implementation" or e["review"]["phase"] == state.get("active_phase"))]
        if not relevant:
            raise RddError(f"A live independent reviewer must observe {stage} before work proceeds", "review")
        self.validate_review_stream(state)
        if final:
            unresolved = [fid for fid, row in state.get("live_findings", {}).items() if not row["resolution"]]
            if unresolved:
                raise RddError("Independent live findings remain unresolved: " + ", ".join(unresolved), "review")
        if final and cursor != len(reviews):
            raise RddError("Final review must include the latest continuous review cursor", "review")
        if final and (relevant[-1]["review"]["source_commit"] != head(self.root)
                      or relevant[-1]["review"]["source_digest"] != source_digest(self.root)):
            raise RddError("Final review requires a current live observation of the candidate", "review")
        if final:
            self.validate_review_cursor(state, cursor, stage, state.get("active_phase") if stage == "implementation" else None,
                                        head(self.root), source_digest(self.root))
        if correction:
            row = state.get("live_findings", {}).get(correction)
            if not row or row["resolution"] or not node or node not in row["finding"].get("nodes", []):
                raise RddError("Corrective claim must name an unresolved finding scoped to this node", "review")
        for fid, row in state.get("live_findings", {}).items():
            finding = row["finding"]
            if row["resolution"]:
                continue
            if correction and node in finding.get("nodes", []):
                continue
            if task and finding.get("tasks") and task not in finding["tasks"]:
                continue
            if not final and fid in repair_findings and task in finding.get("tasks", []):
                continue
            if node and finding.get("nodes") and node not in finding["nodes"]:
                continue
            if final or finding["severity"] in {"blocking", "high", "medium"}:
                raise RddError(f"Independent live finding {fid} remains unresolved", "review")

    def task_findings_at(self, state: dict, tid: str, cursor: int) -> list[str]:
        """Task-scoped findings unresolved at an immutable review-stream prefix."""
        phase = self.task(tid)["phase"]
        return sorted(fid for fid, row in state.get("live_findings", {}).items()
                      if row["stage"] == "implementation" and row["phase"] == phase
                      and tid in row["finding"]["tasks"] and row["sequence"] <= cursor
                      and (not row["resolution"] or row["resolution"]["sequence"] > cursor))

    def task_repair_authorization(self, state: dict, tid: str) -> frozenset[str]:
        """Bind repair IDs; the consuming live guard/checkpoint verifies the stream."""
        record = state["tasks"][tid]
        repairs = [e for e in state["events"] if e["action"] == "open_phase_repair" and e.get("task") == tid]
        if not repairs and "repair_findings" not in record:
            return frozenset()
        latest = repairs[-1] if repairs else {}
        ids, cursor = record.get("repair_findings"), latest.get("review_cursor")
        if (not isinstance(ids, list) or any(not isinstance(fid, str) for fid in ids)
                or ids != sorted(set(ids)) or latest.get("finding_ids") != ids
                or type(cursor) is not int or not 1 <= cursor <= len(state.get("live_reviews", []))):
            raise RddError("Task repair authorization is missing or differs from its repair event", "review")
        # Use list order: live-review events have their own sequence field.
        observed = 0
        for entry in state["events"]:
            if entry["action"] == "live_review_recorded":
                observed += 1
            if entry is latest:
                break
        if observed != cursor or ids != self.task_findings_at(state, tid, cursor):
            raise RddError("Task repair authorization differs from its scoped review prefix", "review")
        return frozenset(ids)

    def validate_review_stream(self, state: dict) -> None:
        reviews = state.get("live_reviews", [])
        expected = {}
        authors = {s for sessions in state.get("authors", {}).values() for s in sessions}
        authors.update(t.get("session_id") for t in state["tasks"].values())
        for sequence, entry in enumerate(reviews, 1):
            review = entry["review"]
            validate_artifact(self.root, "live-review", review)
            if entry["sequence"] != sequence or entry["digest"] != digest({k: v for k, v in entry.items() if k != "digest"}):
                raise RddError("Checkpoint live review stream identity is invalid")
            if (review["session_id"] in authors or review["reviewer"] != "rdd_reviewer"
                    or review["model"] != self.profile_settings("rdd_reviewer")["model"]
                    or review["requirements_digest"] != state["requirements_digest"]):
                raise RddError("Live reviewer provenance is no longer independent or valid", "review")
            for finding in review["findings"]:
                if finding["id"] in expected:
                    raise RddError("Checkpoint live finding history was overwritten")
                expected[finding["id"]] = {"finding": finding, "stage": review["stage"], "phase": review["phase"],
                    "sequence": sequence, "reviewer_session": review["session_id"], "resolution": None}
            for resolution in review["resolutions"]:
                fid = resolution["finding_id"]
                if fid not in expected or expected[fid]["resolution"]:
                    raise RddError("Checkpoint contains an unexplained live finding resolution")
                expected[fid]["resolution"] = {**resolution, "sequence": sequence, "source_commit": review["source_commit"],
                    "source_digest": review["source_digest"], "reviewer_session": review["session_id"]}
        if expected != state.get("live_findings", {}):
            raise RddError("Checkpoint live findings do not match their immutable observation history")

    def validate_review_cursor(self, state: dict, cursor: int, stage: str, phase: str | None,
                               commit: str, sources: str) -> None:
        """Historical acceptance binds its own stream prefix, never a later phase."""
        self.validate_review_stream(state)
        reviews = state.get("live_reviews", [])
        if type(cursor) is not int or not 1 <= cursor <= len(reviews):
            raise RddError("Final review cursor is missing from continuous history", "review")
        observation = reviews[cursor - 1]["review"]
        if (observation["stage"], observation["phase"], observation["source_commit"], observation["source_digest"]) != (stage, phase, commit, sources):
            raise RddError("Final review cursor does not identify its exact candidate observation", "review")
        unresolved = set()
        for entry in reviews[:cursor]:
            unresolved.update(f["id"] for f in entry["review"]["findings"])
            unresolved.difference_update(r["finding_id"] for r in entry["review"]["resolutions"])
        if unresolved:
            raise RddError("Final review cursor retains unresolved live findings", "review")
        prefix = "S" if stage == "specification" else "P" if stage == "preparation" else None
        if prefix:
            required = {node: row["output_digest"] for node, row in state.get("workflow_nodes", {}).items()
                        if node.startswith(prefix) and row["status"] == "complete"}
            if any(reviews[cursor - 1].get("node_outputs", {}).get(node) != output for node, output in required.items()):
                raise RddError("Final review cursor omits completed authoring node outputs", "review")

    def review_category_handoff(self, state: dict, task: dict) -> None:
        from .artifacts import CATEGORIES
        earlier = [row for row in self.plan()["tasks"] if row["phase"] == task["phase"]
                   and CATEGORIES.index(row["category"]) < CATEGORIES.index(task["category"])]
        observations = [entry for entry in state.get("live_reviews", [])
                        if entry["review"]["stage"] == "implementation" and entry["review"]["phase"] == task["phase"]]
        for row in earlier:
            record = state["tasks"][row["id"]]
            if record["status"] == "done" and not any(entry.get("task_outputs", {}).get(row["id"]) == record["commit"] for entry in observations):
                raise RddError(f"Live reviewer must observe completed {row['category']} integration before the category handoff", "review")
