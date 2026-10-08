"""Draft qualification is real local execution; no other native OS is impersonated."""
from pathlib import Path
import unittest

import test_engine as engine_fixture
from tools.rdd.checks import platform_name
from tools.rdd.common import RddError, write_json


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = engine_fixture.EngineTests(methodName="test_phase_cannot_begin_before_preparation")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.c, self.root = self.fixture.c, self.fixture.root
        self.fixture.commit("Commit complete draft for native qualification")

    def test_draft_receipt_is_bound_and_reused_by_freeze(self):
        receipt = self.c.check("contract")
        self.assertEqual(receipt["outcome"], "pass")
        self.assertIsNone(receipt["phase"])
        self.assertIsNone(receipt["plan_digest"])
        self.assertFalse((self.root / ".rdd/spec.lock.json").exists())
        self.fixture.stage_ready("specification")
        self.c.spec_freeze()
        self.assertEqual(self.c.state()["spec_digest"], receipt["spec_digest"])
        self.assertEqual(len(self.c.state()["checks"]), 1)

    def test_transferred_local_receipt_requires_explicit_provenance_route(self):
        receipt = self.c.check("contract")
        path = self.root / ".rdd/runtime/transferred.json"
        write_json(path, receipt)
        with self.assertRaisesRegex(RddError, "local-host"):
            self.c.check_import(path)
        self.assertEqual(self.c.check_import(path, local_host=True)["status"], "imported")

    def test_spec_freeze_cannot_skip_another_required_native_platform(self):
        local = platform_name()
        other = "windows" if local != "windows" else "linux"
        spec = self.c.spec()
        spec["checks"][0]["platforms"] = [local, other]
        spec["environments"].append(dict(id="other", platform=other, host_profile=None))
        spec["checks"][0]["environments"].append("other")
        spec["resources"][0]["environments"].append("other")
        write_json(self.root / ".rdd/spec.json", spec)
        self.fixture.commit("Require both actual native qualification hosts")
        self.fixture.authoring_nodes("specification")
        with self.assertRaisesRegex(RddError, "Missing verification evidence"):
            self.c.readiness("specification")
        self.assertEqual(self.c.state()["status"], "specification")
        self.assertFalse((self.root / ".rdd/spec.lock.json").exists())
        self.assertEqual({r["platform"] for r in self.c.state()["checks"].values()}, {local})
