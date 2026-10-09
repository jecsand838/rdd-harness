"""Preparation acceptance requires server-observed CI, not asserted run URLs."""
import copy
import json
from pathlib import Path
import unittest

from tools.rdd.adapters import CommandResult, GitHubAdapter, RddAdapterError

HEAD, HARNESS, BLOB = "a" * 40, "b" * 40, "c" * 40
URL = "https://github.com/example/rdd/actions/runs/123"
WORKFLOW = ".github/workflows/preparation.yml"


class ActionsFixture:
    def __init__(self):
        self.run = dict(id=123, html_url=URL, repository=dict(full_name="example/rdd"), head_sha=HEAD,
                        path=WORKFLOW, event="push", status="completed", conclusion="success", run_attempt=1)
        self.pin = dict(name="RDD_PREPARATION_HARNESS_SHA", value=HARNESS)
        self.candidate = dict(type="file", path=WORKFLOW, sha=BLOB)
        self.harness = copy.deepcopy(self.candidate)
        self.jobs = dict(total_count=1, jobs=[dict(id=10, name="preparation (macos-latest)",
                         status="completed", conclusion="success", steps=[dict(
                         name="Verify committed preparation with trusted controller", status="completed", conclusion="success")])])
        self.requests = []
        self.reads = 0
        self.rerun = False

    def __call__(self, argv, **kwargs):
        self.requests.append(argv)
        assert "--repo" not in argv, "gh api does not support --repo"
        endpoint = argv[-1]
        if endpoint.endswith("/actions/runs/123"):
            self.reads += 1
            value = copy.deepcopy(self.run)
            if self.rerun and self.reads > 1:
                value["run_attempt"] = 2
        elif "/jobs?" in endpoint:
            value = self.jobs
        elif "/variables/" in endpoint:
            value = self.pin
        elif endpoint.endswith(HEAD):
            value = self.candidate
        elif endpoint.endswith(HARNESS):
            value = self.harness
        else:
            raise AssertionError(endpoint)
        return CommandResult(tuple(argv), 0, json.dumps(value))


class PreparationActionsTests(unittest.TestCase):
    def setUp(self):
        self.server = ActionsFixture()
        self.adapter = GitHubAdapter(Path.cwd(), runner=self.server, repository="example/rdd")

    def observe(self):
        return self.adapter.preparation_status(URL, HEAD, HARNESS)

    def test_success_is_bound_to_candidate_policy_workflow_and_attempt(self):
        result = self.observe()
        self.assertTrue(result["ready"])
        self.assertEqual(result["head_sha"], HEAD)
        self.assertEqual(result["harness_sha"], HARNESS)
        self.assertEqual(result["workflow_blob"], BLOB)
        self.assertEqual(result["attempt"], 1)

    def test_run_url_cannot_point_to_another_repository_or_inject_an_endpoint(self):
        for url in (URL.replace("example/rdd", "other/rdd"), URL + "?head=" + HEAD, URL + "/../456"):
            with self.subTest(url=url), self.assertRaises(RddAdapterError):
                self.adapter.preparation_status(url, HEAD, HARNESS)
        self.assertEqual(self.server.requests, [])

    def test_wrong_candidate_workflow_or_operator_pin_is_not_acceptance(self):
        for target, field, value in (("run", "head_sha", "d" * 40), ("run", "path", ".github/workflows/other.yml"),
                                     ("candidate", "sha", "d" * 40), ("pin", "value", "e" * 40)):
            with self.subTest(target=target, field=field):
                self.setUp()
                getattr(self.server, target)[field] = value
                self.assertFalse(self.observe()["ready"])

    def test_green_run_with_skipped_or_absent_verifier_is_rejected(self):
        for condition in ("skipped_job", "skipped_step", "missing_step", "no_jobs"):
            with self.subTest(condition=condition):
                self.setUp()
                job = self.server.jobs["jobs"][0]
                if condition == "no_jobs":
                    self.server.jobs = dict(total_count=0, jobs=[])
                    with self.assertRaises(RddAdapterError):
                        self.observe()
                    continue
                if condition == "skipped_job":
                    job["conclusion"] = "skipped"
                elif condition == "skipped_step":
                    job["steps"][0]["conclusion"] = "skipped"
                else:
                    job["steps"] = []
                self.assertFalse(self.observe()["ready"])

    def test_failed_run_and_rerun_race_are_not_success(self):
        self.server.run["conclusion"] = "failure"
        self.assertFalse(self.observe()["ready"])
        self.setUp()
        self.server.rerun = True
        self.assertFalse(self.observe()["ready"])

    def test_malformed_repository_steps_and_inventory_fail_closed(self):
        self.server.run["repository"] = None
        self.assertFalse(self.observe()["ready"])
        self.setUp()
        self.server.jobs["jobs"][0]["steps"] = None
        self.assertFalse(self.observe()["ready"])
        self.setUp()
        self.server.jobs["total_count"] = True
        with self.assertRaises(RddAdapterError):
            self.observe()


if __name__ == "__main__":
    unittest.main()
