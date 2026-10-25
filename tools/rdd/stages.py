"""Revision-bound preimplementation readiness and two independent review perspectives."""
from pathlib import Path
import shutil
import tempfile
import re

from . import artifacts
from .checks import verify_receipt
from .common import (RddError, clean, digest, event, head, inventory, read_json, safe_path,
                     source_digest, validate_artifact, write_json)
from .readiness import (required_probe_ids, validate_producers, validate_resources, verify_resource_observations,
                        canonical_contract_check, verify_canonical_contract_receipts, verify_readiness_coverage)

STAGES = ("specification", "plan", "preparation")


class StageWorkflow:
    @staticmethod
    def validate_preparation_observation(report: dict, observed: dict, candidate: dict) -> None:
        from .ci_tools import RUNNERS
        run_id = observed.get("run_id")
        jobs = observed.get("jobs")
        if (observed.get("ready") is not True or observed.get("blockers") != []
                or observed.get("head_sha") != candidate["source_commit"]
                or observed.get("harness_sha") != report.get("harness_source")
                or not re.fullmatch(r"[0-9a-f]{40}", str(observed.get("harness_sha")))
                or observed.get("url") != report.get("run_url")
                or type(run_id) is not int or run_id < 1 or not observed["url"].endswith(f"/actions/runs/{run_id}")
                or type(observed.get("attempt")) is not int or observed["attempt"] < 1
                or not re.fullmatch(r"[0-9a-f]{40}", str(observed.get("workflow_blob")))
                or not isinstance(jobs, list) or not jobs
                or any(not isinstance(job, dict) or job.get("status") != "completed" or job.get("conclusion") != "success" for job in jobs)
                or not any(job.get("name") == f"preparation ({RUNNERS.get(report.get('platform'))})" for job in jobs)):
            raise RddError("Preparation GitHub observation has mismatched or incomplete candidate/pin/run/job identity", "review")

    def validate_stage_review_coverage(self, stage: str, review: dict, state: dict) -> None:
        spec = self.spec()
        declared = spec["author_sessions"] if stage == "specification" else self.plan()["author_sessions"]
        if not state.get("authors", {}).get(stage) or set(state["authors"][stage]) != set(declared):
            raise RddError("Register every actual stage author session and match the manifest", "review")
        expected = {"requirements": {r["requirement"] for r in spec["requirement_map"]},
                    "elements": {e["id"] for e in spec["solution_elements"]},
                    "scenarios": {s["id"] for s in spec["scenarios"]},
                    "checks": {c["id"] for c in spec["checks"]},
                    "tasks": set() if stage == "specification" else {t["id"] for t in self.plan()["tasks"]}}
        for field, ids in expected.items():
            if set(review["coverage"][field]) != ids:
                raise RddError(f"Stage review {field} coverage is incomplete or unknown", "review")

    def validate_stage_checkpoint(self, state: dict, checkpoint: dict) -> None:
        if state.get("workflow_version") != 2:
            raise RddError("Legacy checkpoints are read/export only; start a fresh v2 baseline")
        required = []
        if state.get("spec_digest"):
            required.append(("specification", state.get("spec_acceptance")))
        if state.get("plan_digest"):
            required.append(("plan", state.get("plan_acceptance")))
        status = state.get("resume_status") if state["status"] == "blocked" else state["status"]
        if status in {"prepared", "implementation", "complete"}:
            gate = state.get("preparation_gate")
            if not gate or gate.get("status") != "passed" or gate.get("application_complete") is not False:
                raise RddError("Checkpoint lacks accepted preparation gate")
            required.append(("preparation", gate))
        for stage, acceptance in required:
            if not isinstance(acceptance, dict) or not {"candidate", "readiness_digest", "review_digests"} <= acceptance.keys():
                raise RddError(f"Checkpoint lacks {stage} acceptance")
            candidate = acceptance["candidate"]
            if (not isinstance(candidate, dict) or candidate.get("run_id") != state["id"]
                    or candidate.get("stage") != stage
                    or candidate.get("digest") != digest({k: v for k, v in candidate.items() if k != "digest"})):
                raise RddError("Checkpoint stage candidate identity is invalid")
            if candidate.get("spec_digest") != state.get("spec_digest") or candidate.get("plan_digest") != (
                    None if stage == "specification" else state.get("plan_digest")):
                raise RddError("Checkpoint stage candidate differs from frozen baseline identities")
            ready = state.get("readiness", {}).get(stage, {})
            if (ready.get("candidate") != candidate or ready.get("status") != "passed"
                    or ready.get("digest") != acceptance["readiness_digest"]
                    or ready.get("digest") != digest({k: v for k, v in ready.items() if k != "digest"})):
                raise RddError("Checkpoint readiness identity is invalid")
            for eid in ready.get("evidence", []):
                if eid not in state["checks"] or ready.get("receipt_digests", {}).get(eid) != digest(state["checks"][eid]):
                    raise RddError("Checkpoint readiness receipt changed or is missing")
                receipt = state["checks"][eid]
                checks = artifacts.unique(self.spec()["checks"], "check")
                if receipt["check_id"] not in checks:
                    raise RddError("Checkpoint readiness check is unknown")
                raw = checkpoint["evidence"].get(receipt["log_path"])
                if raw is None:
                    raise RddError("Checkpoint lacks readiness raw evidence")
                # Verify staged bytes before importing anything into the run.
                with tempfile.TemporaryDirectory(prefix="rdd-receipt-preflight-") as directory:
                    scratch = Path(directory)
                    schema = scratch / ".rdd/schemas/evidence.schema.json"
                    schema.parent.mkdir(parents=True)
                    shutil.copyfile(self.root / ".rdd/schemas/evidence.schema.json", schema)
                    from .common import atomic_write, safe_path
                    atomic_write(safe_path(scratch, receipt["log_path"]), raw.encode("utf-8"))
                    verify_receipt(scratch, receipt, checks[receipt["check_id"]], commit=candidate["source_commit"],
                        sources=candidate["source_digest"], spec_digest=candidate["spec_digest"], plan_digest=candidate["plan_digest"])
            receipts = [state["checks"][eid] for eid in ready["evidence"]]
            verify_readiness_coverage(self.spec(), self.stage_check_ids(stage), receipts, require_ci=stage == "preparation")
            if stage == "preparation":
                from .adapters import _strict_json
                ci_platforms = {r["platform"] for r in receipts if r["origin"] == "ci"}
                runs = acceptance.get("ci_runs", {})
                if set(runs) != ci_platforms:
                    raise RddError("Checkpoint preparation lacks its observed CI runs")
                for platform, observed in runs.items():
                    raw = checkpoint["evidence"].get(observed["path"])
                    report = _strict_json(raw) if isinstance(raw, str) else {}
                    if (digest(report) != observed["report_digest"] or report.get("source_commit") != candidate["source_commit"]
                            or report.get("source_digest") != candidate["source_digest"] or report.get("platform") != platform
                            or report.get("status") != "passed" or observed.get("github", {}).get("ready") is not True):
                        raise RddError("Checkpoint preparation CI identity is invalid")
                    self.validate_preparation_observation(report, observed["github"], candidate)
            with tempfile.TemporaryDirectory(prefix="rdd-readiness-preflight-") as directory:
                scratch = Path(directory)
                from .common import atomic_write, safe_path
                for receipt in receipts:
                    atomic_write(safe_path(scratch, receipt["log_path"]), checkpoint["evidence"][receipt["log_path"]].encode("utf-8"))
                verify_canonical_contract_receipts(self.root, self.spec(), receipts, log_root=scratch)
                verify_resource_observations(scratch, self.spec(), receipts)
            reviews = state.get("stage_reviews", {}).get(stage, {})
            if set(reviews) != {"semantic", "execution"} or len({r.get("session_id") for r in reviews.values()}) != 2:
                raise RddError("Checkpoint lacks both independent review perspectives")
            authors = {s for sessions in state.get("authors", {}).values() for s in sessions}
            for perspective, review in reviews.items():
                validate_artifact(self.root, "stage-review", review)
                self.validate_stage_review_coverage(stage, review, state)
                self.validate_review_cursor(state, review["review_cursor"], "specification" if stage == "specification" else "preparation",
                    None, candidate["source_commit"], candidate["source_digest"])
                if (review["candidate"] != candidate or review["decision"] != "pass" or review["findings"]
                        or review["session_id"] in authors or review["reviewer"] != "rdd_reviewer"
                        or review["model"] != self.profile_settings("rdd_reviewer")["model"]
                        or acceptance["review_digests"].get(perspective) != digest(review)
                        or set(review["evidence_ids"]) != set(ready["evidence"])):
                    raise RddError("Checkpoint stage review is unresolved, stale, or not independent")

    def author_record(self, stage: str, session_id: str) -> dict:
        self.guard_source_write(baseline=True)
        self.guard_author_identity(session_id)
        if stage not in STAGES or not session_id.strip() or len(session_id) > 200:
            raise RddError("Author registration needs a stage and actual session identity")
        state = self.state()
        allowed = {"specification": {"specification"}, "plan": {"specified"}, "preparation": {"preparing"}}
        if state["status"] not in allowed[stage]:
            raise RddError("Authors may register only during the active authoring stage")
        authors = state.setdefault("authors", {}).setdefault(stage, [])
        if session_id not in authors:
            authors.append(session_id)
        event(state, "stage_author_registered", stage=stage, session_id=session_id)
        self.save(state)
        return {"stage": stage, "author_sessions": authors,
                "trust": "Session provenance is declared, not authenticated by this controller."}

    def stage_candidate(self, stage: str) -> dict:
        if stage not in STAGES:
            raise RddError("Unknown review stage")
        state = self.state()
        expected = {"specification": {"specification"}, "plan": {"specified"},
                    "preparation": {"preparing", "prepared"}}[stage]
        if state["status"] not in expected:
            raise RddError(f"{stage} candidate is unavailable in {state['status']}")
        if stage == "specification":
            self.spec_validate()
            sid, pid = self.spec_candidate_lock()["digest"], None
        else:
            self.plan_validate()
            sid = state["spec_digest"]
            pid = self.plan_candidate_lock()["digest"] if stage == "plan" else state["plan_digest"]
            if stage == "preparation":
                self.frozen()
                artifacts.anchors_verify(self.root, self.plan(), state)
        body = {"stage": stage, "run_id": state["id"], "source_commit": head(self.root),
                "source_digest": source_digest(self.root), "spec_digest": sid, "plan_digest": pid}
        return {**body, "digest": digest(body)}

    def stage_check_ids(self, stage: str) -> list[str]:
        spec = self.spec()
        plan = None if stage == "specification" else self.plan()
        return sorted(set(spec["contract_check_ids"] + required_probe_ids(spec, plan)))

    def readiness(self, stage: str) -> dict:
        self.guard_source_write(baseline=True)
        clean(self.root)
        candidate = self.stage_candidate(stage)
        state = self.state()
        spec = self.spec()
        self.require_workflow_node("S6" if stage == "specification" else "P5" if stage == "plan" else "P7")
        validate_resources(self.root, spec)
        canonical_contract_check(spec)
        if stage != "specification":
            validate_producers(self.root, spec, self.plan())
        proofs = self.ensure_checks(state, self.stage_check_ids(stage),
                                   candidate_spec_digest=candidate["spec_digest"],
                                   candidate_plan_digest=candidate["plan_digest"])
        if candidate != self.stage_candidate(stage):
            raise RddError("Readiness probes changed the candidate", "review")
        verify_resource_observations(self.root, spec, proofs)
        verify_readiness_coverage(spec, self.stage_check_ids(stage), proofs)
        verify_canonical_contract_receipts(self.root, spec, proofs)
        baseline_paths = [r["path"] for r in spec["resources"]
                          if r["kind"] == "repository" and r["availability"] == "baseline"]
        report = {"schema_version": 2, "candidate": candidate, "evidence": [p["id"] for p in proofs],
                  "receipt_digests": {p["id"]: digest(p) for p in proofs},
                  "baseline_inputs": inventory(self.root, baseline_paths), "status": "passed"}
        report["digest"] = digest(report)
        state.setdefault("readiness", {})[stage] = report
        write_json(self.root / f".rdd/evidence/readiness/{stage}-{candidate['digest']}.json", report)
        self.save(state)
        return report

    def current_readiness(self, stage: str, candidate: dict) -> dict:
        state = self.state()
        if stage == "specification":
            self.require_refinement(state)
        report = state.get("readiness", {}).get(stage)
        if not report or report["candidate"] != candidate or report["status"] != "passed":
            raise RddError(f"Exact-current-candidate {stage} readiness is required", "review")
        if report["digest"] != digest({k: v for k, v in report.items() if k != "digest"}):
            raise RddError("Readiness report digest changed", "review")
        if inventory(self.root, list(report["baseline_inputs"])) != report["baseline_inputs"]:
            raise RddError("Readiness baseline inputs changed", "review")
        checks = artifacts.unique(self.spec()["checks"], "check")
        covered = set()
        for eid in report["evidence"]:
            receipt = state["checks"].get(eid)
            if not receipt:
                raise RddError("Readiness evidence is missing", "review")
            if report["receipt_digests"].get(eid) != digest(receipt):
                raise RddError("Reviewed readiness receipt changed", "review")
            verify_receipt(self.root, receipt, checks[receipt["check_id"]],
                           commit=candidate["source_commit"], sources=candidate["source_digest"],
                           spec_digest=candidate["spec_digest"], plan_digest=candidate["plan_digest"])
            covered.add(receipt["check_id"])
        if covered != set(self.stage_check_ids(stage)):
            raise RddError("Readiness evidence inventory is incomplete", "review")
        verify_readiness_coverage(self.spec(), self.stage_check_ids(stage), [state["checks"][eid] for eid in report["evidence"]])
        verify_resource_observations(self.root, self.spec(), [state["checks"][eid] for eid in report["evidence"]])
        verify_canonical_contract_receipts(self.root, self.spec(), [state["checks"][eid] for eid in report["evidence"]])
        return report

    def stage_review_record(self, file: Path) -> dict:
        self.guard_source_write(baseline=True)
        clean(self.root)
        review = read_json(file)
        validate_artifact(self.root, "stage-review", review)
        stage = review["stage"]
        candidate = self.stage_candidate(stage)
        state, spec = self.state(), self.spec()
        self.live_review_guard(final=True, cursor=review["review_cursor"], stage="specification" if stage == "specification" else "preparation")
        if review["candidate"] != candidate:
            raise RddError("Review does not cover the exact current stage candidate", "review")
        if review["reviewer"] != "rdd_reviewer" or review["model"] != self.profile_settings("rdd_reviewer")["model"]:
            raise RddError("Stage review requires the configured independent reviewer", "review")
        self.validate_stage_review_coverage(stage, review, state)
        all_authors = {s for sessions in state.get("authors", {}).values() for s in sessions}
        if review["session_id"] in all_authors:
            raise RddError("Reviewer session must be distinct from authors", "review")
        readiness = self.current_readiness(stage, candidate)
        if set(review["evidence_ids"]) != set(readiness["evidence"]):
            raise RddError("Stage review must inspect the current readiness evidence", "review")
        history = state.setdefault("stage_review_history", [])
        history.append(review)
        state.setdefault("stage_reviews", {}).setdefault(stage, {})[review["perspective"]] = review
        path = f".rdd/evidence/reviews/{stage}-{review['perspective']}-{digest(review)}.json"
        write_json(self.root / path, review)
        event(state, "stage_review_recorded", stage=stage, perspective=review["perspective"], decision=review["decision"])
        self.save(state)
        self.record_final_findings(review, "specification" if stage == "specification" else "preparation")
        return {"stage": stage, "perspective": review["perspective"], "decision": review["decision"], "review_path": path}

    def stage_acceptance(self, stage: str) -> dict:
        clean(self.root)
        candidate = self.stage_candidate(stage)
        readiness = self.current_readiness(stage, candidate)
        reviews = self.state().get("stage_reviews", {}).get(stage, {})
        state = self.state()
        declared = self.spec()["author_sessions"] if stage == "specification" else self.plan()["author_sessions"]
        if set(state.get("authors", {}).get(stage, [])) != set(declared):
            raise RddError("Stage authors changed after review", "review")
        authors = {s for sessions in state.get("authors", {}).values() for s in sessions}
        if set(reviews) != {"semantic", "execution"}:
            raise RddError("Both semantic and execution independent reviews are required", "review")
        if len({r["session_id"] for r in reviews.values()}) != 2:
            raise RddError("The two independent perspectives need distinct reviewer sessions", "review")
        for review in reviews.values():
            self.live_review_guard(final=True, cursor=review["review_cursor"], stage="specification" if stage == "specification" else "preparation")
            if review["session_id"] in authors or review["model"] != self.profile_settings("rdd_reviewer")["model"] or review["reviewer"] != "rdd_reviewer":
                raise RddError("Stage review independence or configured identity changed", "review")
            if review["candidate"] != candidate:
                raise RddError("Stage review is stale", "review")
            if review["decision"] != "pass" or review["findings"]:
                raise RddError("Stage review has unresolved findings", "review")
            if set(review["evidence_ids"]) != set(readiness["evidence"]):
                raise RddError("Stage review readiness evidence is stale", "review")
        return {"candidate": candidate, "readiness_digest": readiness["digest"],
                "review_digests": {p: digest(r) for p, r in reviews.items()}}

    def gate_preparation(self) -> dict:
        self.guard_source_write(baseline=True)
        self.require_workflow_node("P7")
        acceptance = self.stage_acceptance("preparation")
        state, spec = self.state(), self.spec()
        # Every portable qualification must have actually run in CI at this exact
        # materialized revision. Native/profile checks remain required separately.
        checks = artifacts.unique(spec["checks"], "check")
        readiness = self.current_readiness("preparation", acceptance["candidate"])
        ci_receipts = {}
        for cid in self.stage_check_ids("preparation"):
            check = checks[cid]
            if check["host_profile"] or check["kind"] == "manual":
                continue
            envs = {e["id"]: e for e in spec["environments"]}
            platforms = {envs[e]["platform"] for e in check["environments"]}
            for platform in platforms:
                matching = [state["checks"][eid] for eid in readiness["evidence"]
                            if state["checks"][eid]["check_id"] == cid
                            and state["checks"][eid]["platform"] == platform
                            and state["checks"][eid]["origin"] == "ci"]
                if not matching:
                    raise RddError(f"Preparation needs actual exact-source CI evidence for {cid} on {platform}", "environment")
                ci_receipts.setdefault(platform, []).extend(matching)
        ci_runs = {}
        from .engine import GitHubAdapter
        from .adapters import RddAdapterError
        for platform, receipts in ci_receipts.items():
            path = f".rdd/evidence/preparation-ci/{platform}.json"
            report = read_json(safe_path(self.root, path, allow_missing=False))
            if (report.get("scope") != "preparation" or report.get("status") != "passed"
                    or report.get("application_complete") is not False or report.get("platform") != platform
                    or report.get("source_commit") != acceptance["candidate"]["source_commit"]
                    or report.get("source_digest") != acceptance["candidate"]["source_digest"]):
                raise RddError("Preparation CI report is stale or does not qualify this candidate/platform", "review")
            reported = {r["id"]: r for r in report.get("checks", [])}
            if any(reported.get(receipt["id"]) != receipt or receipt["provenance"]["run_url"] != report.get("run_url") for receipt in receipts):
                raise RddError("Preparation CI report does not contain the reviewed raw receipts", "review")
            try:
                observed = GitHubAdapter(self.root).preparation_status(report["run_url"], acceptance["candidate"]["source_commit"], report.get("harness_source"))
            except RddAdapterError as exc:
                raise RddError(str(exc), "environment") from exc
            if observed.get("ready") is not True:
                raise RddError("Preparation CI run is not ready: " + "; ".join(observed.get("blockers", [])), "environment")
            self.validate_preparation_observation(report, observed, acceptance["candidate"])
            ci_runs[platform] = {"path": path, "report_digest": digest(report), "github": observed}
        report = {"schema_version": 2, "status": "passed", "application_complete": False, "ci_runs": ci_runs, **acceptance}
        write_json(self.root / ".rdd/evidence/preparation-gate.json", report)
        state.update(status="prepared", preparation_gate=report)
        event(state, "preparation_gate_passed", candidate=acceptance["candidate"]["digest"])
        self.save(state)
        return report
