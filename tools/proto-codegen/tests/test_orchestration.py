"""Stdlib-only safety tests for the contract controller helper.

Run: python3 -m unittest discover -s tools/proto-codegen/tests -v
Rust generation and compiler proofs require real Cargo and Buf; they are not
mocked into a passing integration result by this suite.
"""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("proto_traits", REPO / "tools/rdd/proto_traits.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class OrchestrationSafety(unittest.TestCase):
    def test_no_run_generation_rejects_each_frozen_artifact_before_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", "-b", "codex/test-baseline", str(root)], check=True)
            output = root / "gen/rust/binding.rs"
            output.parent.mkdir(parents=True)
            output.write_text("preserve generated output\n", encoding="utf-8")
            locator = root / ".rdd/run.json"
            for rel in (".rdd/spec.lock.json", ".rdd/plan/plan.lock.json", ".rdd/prepared.json"):
                frozen = root / rel
                frozen.parent.mkdir(parents=True, exist_ok=True)
                frozen.write_text("{}\n", encoding="utf-8")
                for no_run_locator in (False, True):
                    if no_run_locator:
                        locator.write_text('{"run_id": null}\n', encoding="utf-8")
                    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
                              if p.is_file() and ".git" not in p.relative_to(root).parts}
                    with self.subTest(frozen=rel, no_run_locator=no_run_locator), patch.object(MODULE.shutil, "which") as tool_lookup:
                        with self.assertRaisesRegex(MODULE.ContractCheckError, "frozen artifacts") as caught:
                            MODULE.run_contracts(root, write=True, bootstrap_lock=True)
                        self.assertTrue(caught.exception.blocked)
                        tool_lookup.assert_not_called()
                        self.assertEqual({p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
                                          if p.is_file() and ".git" not in p.relative_to(root).parts}, before)
                        self.assertFalse((root / ".rdd/runtime").exists())
                    with patch.object(MODULE.shutil, "which", return_value=None):
                        with self.assertRaisesRegex(MODULE.ContractCheckError, "missing contract prerequisites"):
                            MODULE.run_contracts(root)
                frozen.unlink()
                locator.unlink(missing_ok=True)

    def test_non_main_qualification_without_run_checks_prerequisites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", "-b", "codex/test-baseline", str(root)], check=True)
            with patch.object(MODULE.shutil, "which", return_value=None):
                with self.assertRaises(MODULE.ContractCheckError) as caught:
                    MODULE.run_contracts(root, write=True, bootstrap_lock=True)
            self.assertTrue(caught.exception.blocked)
            self.assertIn("missing contract prerequisites", str(caught.exception))
            self.assertFalse((root / ".rdd").exists())

    def test_direct_write_rejects_main_and_detached_before_tools_or_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Generator Fixture"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
            (root / "user.txt").write_text("preserve committed input\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "user.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "Initial fixture"], check=True)
            (root / "user.txt").write_text("preserve dirty input\n", encoding="utf-8")
            for detached in (False, True):
                if detached:
                    subprocess.run(["git", "-C", str(root), "switch", "-q", "--detach", "HEAD"], check=True)
                with self.subTest(detached=detached), patch.object(MODULE.shutil, "which") as tool_lookup:
                    with self.assertRaises(MODULE.ContractCheckError) as caught:
                        MODULE.run_contracts(root, write=True, bootstrap_lock=True)
                    self.assertTrue(caught.exception.blocked)
                    tool_lookup.assert_not_called()
                    self.assertEqual((root / "user.txt").read_text(), "preserve dirty input\n")
                    self.assertFalse((root / ".rdd").exists())

    def test_missing_compilers_is_blocked_not_passed(self):
        with patch.object(MODULE.shutil, "which", return_value=None):
            with self.assertRaises(MODULE.ContractCheckError) as caught:
                MODULE.run_contracts(REPO)
        self.assertTrue(caught.exception.blocked)
        self.assertIn("cargo", str(caught.exception))
        self.assertIn("buf", str(caught.exception))

    def test_read_only_check_cannot_bootstrap_locks(self):
        with patch.object(MODULE.shutil, "which", return_value="/fake/tool"):
            with self.assertRaisesRegex(MODULE.ContractCheckError, "requires --write"):
                MODULE.run_contracts(REPO, bootstrap_lock=True)

    def test_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(MODULE.ContractCheckError):
                MODULE._contained(root, root / ".." / "unowned")

    def test_symlink_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real").mkdir()
            try:
                (root / "link").symlink_to(root / "real", target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation is unavailable for this account")
            with self.assertRaises(MODULE.ContractCheckError):
                MODULE._contained(root, root / "link" / "output")

    def test_source_symlinks_are_rejected_before_buf_reads_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "schema.proto").write_text("syntax = \"proto3\";", encoding="utf-8")
            try:
                (root / "alias.proto").symlink_to(root / "schema.proto")
            except OSError:
                self.skipTest("symlink creation is unavailable for this account")
            with self.assertRaises(MODULE.ContractCheckError):
                MODULE._reject_source_symlinks(root)

    def test_publication_refuses_unowned_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, output, runtime = (root / name for name in ("candidate", "output", "runtime"))
            for path in (candidate, output, runtime):
                path.mkdir()
            (output / "user.txt").write_text("preserve", encoding="utf-8")
            with self.assertRaises(MODULE.ContractCheckError):
                MODULE._publish(candidate, output, runtime)
            self.assertEqual((output / "user.txt").read_text(), "preserve")

    def test_publication_restores_previous_tree_on_swap_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, output, runtime = (root / name for name in ("candidate", "output", "runtime"))
            for path in (candidate, output, runtime):
                path.mkdir()
            (output / ".rdd-generated.json").write_text("{}", encoding="utf-8")
            (output / "old.rs").write_text("old", encoding="utf-8")
            original = Path.rename

            def fail_candidate(path, target):
                if path == candidate:
                    raise OSError("simulated publication failure")
                return original(path, target)

            with patch.object(Path, "rename", fail_candidate):
                with self.assertRaises(OSError):
                    MODULE._publish(candidate, output, runtime)
            self.assertEqual((output / "old.rs").read_text(), "old")
            self.assertFalse((runtime / "previous-generated").exists())

    def test_ownership_checked_publication_preserves_candidate_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, output, runtime = (root / name for name in ("candidate", "output", "runtime"))
            candidate.mkdir()
            runtime.mkdir()
            (candidate / "binding.rs").write_text("generated", encoding="utf-8")
            expected = MODULE._files(candidate)
            MODULE._publish(candidate, output, runtime)
            self.assertEqual(MODULE._files(output), expected)
            self.assertFalse(candidate.exists())


if __name__ == "__main__":
    unittest.main()
