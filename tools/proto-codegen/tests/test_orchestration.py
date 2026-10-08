"""Stdlib-only safety tests for the contract controller helper.

Run: python3 -m unittest discover -s tools/proto-codegen/tests -v
Rust generation and compiler proofs require real Cargo and Buf; they are not
mocked into a passing integration result by this suite.
"""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("proto_traits", REPO / "tools/rdd/proto_traits.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class OrchestrationSafety(unittest.TestCase):
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
