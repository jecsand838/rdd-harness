"""PREPARED fixture reuse must preserve real transitions and physical isolation."""
from __future__ import annotations

import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import test_engine as engine_fixture
from tools.rdd.adapters import phase_branch
from tools.rdd.common import operation_lock


class FixtureReuseTests(unittest.TestCase):
    def owner(self):
        class Consumer(unittest.TestCase):
            pass
        self.addCleanup(Consumer.doClassCleanups)
        return Consumer

    def fixture(self):
        fixture = engine_fixture.EngineTests(methodName="runTest")
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def reuse(self, fixture, owner):
        # Before reuse exists, execute the original behavior to expose the
        # repeated real preparation, rather than an import/compilation failure.
        helper = getattr(fixture, "prepared_from_seed", None)
        return helper(owner) if helper else fixture.prepared()

    def files(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.rglob("*") if p.is_file()}

    def test_one_real_preparation_per_consuming_class(self):
        owner = self.owner()
        first, second = self.fixture(), self.fixture()
        original = engine_fixture.EngineTests.prepared
        calls = []
        def prepare(fixture):
            calls.append(fixture.root)
            return original(fixture)
        with patch.object(engine_fixture.EngineTests, "prepared", prepare):
            self.reuse(first, owner)
            self.reuse(second, owner)
        self.assertEqual(len(calls), 1, "A consuming class must prepare exactly one closed seed")
        self.assertEqual(first.c.state()["status"], "prepared")
        self.assertEqual(second.c.state()["status"], "prepared")

    def test_copy_equivalence_and_mutations_do_not_escape_a_clone(self):
        owner = self.owner()
        first, second = self.fixture(), self.fixture()
        self.reuse(first, owner)
        self.reuse(second, owner)
        seed = owner._prepared_fixture_seed
        baseline = self.files(seed.root)
        self.assertEqual(self.files(first.root), baseline)
        self.assertEqual(self.files(second.root), baseline)
        self.assertNotEqual(first.root, second.root)
        for name in ("config", "reqs", "spec", "plan", "c", "hub"):
            self.assertIsNot(getattr(first, name), getattr(second, name))
        from tools.rdd import engine
        self.assertIs(engine.GitHubAdapter(first.root), first.hub)
        self.assertIs(engine.GitHubAdapter(second.root), second.hub)
        for rel in (".git/objects", ".rdd/runtime/state.sqlite3"):
            self.assertFalse((first.root / rel).is_symlink())
        db = Path(".rdd/runtime/state.sqlite3")
        self.assertNotEqual((first.root / db).stat().st_ino, (second.root / db).stat().st_ino)
        first.spec["scenarios"][0]["expected"] = "Clone-local draft"
        first.hub.ready = False
        first.c.block("environment", "Clone-local diagnostic")
        (first.root / "modules/value.py").write_text("value = 'clone-local'\n")
        evidence = first.root / ".rdd/evidence/clone-local.txt"
        evidence.write_text("Clone-local evidence\n")
        first.commit("Clone-local source and ref")
        first.g("branch", "clone-local-ref")
        self.assertEqual(self.files(second.root), baseline)
        self.assertEqual(self.files(seed.root), baseline)
        self.assertEqual(second.c.state()["status"], "prepared")
        self.assertTrue(second.hub.ready)
        self.assertNotEqual(second.spec["scenarios"][0]["expected"], first.spec["scenarios"][0]["expected"])

    def test_clone_revalidates_frozen_preparation_and_really_opens_phase(self):
        fixture = self.fixture()
        self.reuse(fixture, self.owner())
        fixture.c.frozen()
        acceptance = fixture.c.stage_acceptance("preparation")
        self.assertEqual(acceptance["candidate"], fixture.c.stage_candidate("preparation"))
        self.assertEqual(set(acceptance["review_digests"]), {"semantic", "execution"})
        fixture.c.phase_begin("P01")
        fixture.live_review()
        self.assertEqual(fixture.c.state()["active_phase"], "P01")
        self.assertEqual(fixture.g("branch", "--show-current"), phase_branch("fixture-run", 1))

    def test_custom_inputs_refuse_reuse_and_default_prepared_still_executes(self):
        fixture = self.fixture()
        fixture.plan["tasks"][0]["scope"] = "large"
        with self.assertRaisesRegex(AssertionError, "custom"):
            fixture.prepared_from_seed(self.owner())
        with patch.object(fixture, "prepared_from_seed", side_effect=AssertionError("Unexpected reuse")):
            fixture.prepared()
        self.assertEqual(fixture.c.plan()["tasks"][0]["scope"], "large")

    def test_seed_rejects_open_tasks_worktrees_processes_and_sqlite_auxiliaries(self):
        fixture = self.fixture()
        self.reuse(fixture, self.owner())
        state = fixture.c.state()
        verify = engine_fixture.PreparedFixtureSeed.assert_seedable
        for suffix in ("-wal", "-shm", "-journal", ".lock"):
            path = fixture.root / (".rdd/runtime/state.sqlite3" + suffix)
            path.write_bytes(b"unfinished")
            try:
                with self.subTest(suffix=suffix), self.assertRaisesRegex(AssertionError, "closed"):
                    verify(fixture.root, state, [])
            finally:
                path.unlink()
        process = unittest.mock.Mock()
        process.poll.return_value = None
        with self.assertRaisesRegex(AssertionError, "process"):
            verify(fixture.root, state, [process])
        for change in (dict(status="implementing"), dict(active_phase="P01")):
            changed = {**state, **change}
            with self.subTest(change=change), self.assertRaises(AssertionError):
                verify(fixture.root, changed, [])
        for change in (dict(status="claimed"), dict(status="done"), dict(attempts=1), dict(worktree="worker")):
            changed = copy.deepcopy(state)
            changed["tasks"]["T001"].update(change)
            with self.subTest(task=change), self.assertRaises(AssertionError):
                verify(fixture.root, changed, [])
        fixture.g("worktree", "add", "-b", "seed-must-reject-worker", str(fixture.root / "worker"))
        with self.assertRaisesRegex(AssertionError, "worktree"):
            verify(fixture.root, state, [])

    def test_modified_seed_is_rejected_without_overwriting_consumer(self):
        owner = self.owner()
        first, second = self.fixture(), self.fixture()
        self.reuse(first, owner)
        seed = owner._prepared_fixture_seed
        (seed.root / "modules/value.py").write_text("Changed seed\n")
        before = self.files(second.root)
        with self.assertRaisesRegex(AssertionError, "immutable"):
            self.reuse(second, owner)
        self.assertEqual(self.files(second.root), before)

    def test_seed_topology_and_held_lock_tampering_preserve_consumer(self):
        owner = self.owner()
        first, second = self.fixture(), self.fixture()
        self.reuse(first, owner)
        seed = owner._prepared_fixture_seed
        before = self.files(second.root)
        foreign = second.root.parent / "foreign"
        foreign.mkdir()
        (foreign / "private.txt").write_text("Foreign bytes must not enter a clone\n")
        link = seed.root / "foreign-link"
        link.symlink_to(foreign, target_is_directory=True)
        try:
            with self.subTest(directory_symlink=True):
                with self.assertRaisesRegex(AssertionError, "immutable"):
                    seed.copy_into(second)
                self.assertTrue(self.files(second.root) == before, "Consumer changed after rejected topology tampering")
                self.assertFalse((second.root / "foreign-link").exists())
        finally:
            link.unlink()
        for rel in ("empty", ".rdd/runtime/controller.lock", ".rdd/runtime/state.sqlite3-wal", ".git/worktrees"):
            directory = seed.root / rel
            directory.mkdir()
            try:
                with self.subTest(directory=rel):
                    with self.assertRaisesRegex(AssertionError, "immutable"):
                        seed.copy_into(second)
                    self.assertTrue(self.files(second.root) == before, "Consumer changed after rejected topology tampering")
            finally:
                directory.rmdir()
        with operation_lock(seed.root):
            with self.assertRaisesRegex(AssertionError, "immutable"):
                seed.copy_into(second)
            self.assertTrue(self.files(second.root) == before, "Consumer changed after rejected lock tampering")
        (seed.root / ".rdd/runtime/controller.lock").unlink()

    def test_class_cleanup_discards_seed_reference_before_same_process_reuse(self):
        owner = self.owner()
        fixture = self.fixture()
        seeds = [unittest.mock.Mock(), unittest.mock.Mock()]
        files = engine_fixture.PreparedFixtureSeed.files
        with patch.object(engine_fixture, "PreparedFixtureSeed", side_effect=seeds) as build:
            build.files.side_effect = files
            fixture.prepared_from_seed(owner)
            owner.doClassCleanups()
            seeds[0].tmp.cleanup.assert_called_once_with()
            self.assertNotIn("_prepared_fixture_seed", owner.__dict__)
            fixture.prepared_from_seed(owner)
            self.assertEqual(build.call_count, 2)
            self.assertIs(owner._prepared_fixture_seed, seeds[1])


if __name__ == "__main__":
    unittest.main()
