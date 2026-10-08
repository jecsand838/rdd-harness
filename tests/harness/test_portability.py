"""Actual process and persisted-byte regressions for non-UTF8/Windows hosts."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.rdd.adapters import run_argv
from tools.rdd.artifacts import materialize, placement_offset, remove_anchor
from tools.rdd.common import RddError, read_json, write_json

ROOT = Path(__file__).resolve().parents[2]


class PortabilityTests(unittest.TestCase):
    def test_overlapping_context_is_ambiguous_with_either_newline(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)), self.assertRaisesRegex(RddError, "found 2"):
                placement_offset(newline.join(["same", "same", "same", ""]),
                                 {"kind": "after", "context": "same\nsame"}, "work site")

    def test_projection_and_cleanup_preserve_existing_crlf_and_unicode_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "module.rs"
            original = '// café 日本語\r\npub fn item() {\r\n    // preserve\r\n}\r\n'.encode()
            source.write_bytes(original)
            task = {"id": "T001", "phase": "P01", "category": "modification",
                    "title": "Update the item owner", "writes": ["module.rs"],
                    "sites": [{"id": "A01", "path": "module.rs", "mode": "inline",
                               "primary": True, "instructions": "Extend this owner.",
                               "placement": {"kind": "before", "context": "pub fn item() {\n    // preserve\n}"}}]}
            plan = {"schema_version": 2, "tasks": [task], "shells": [],
                    "verticals": [{"id": "V01", "tasks": ["T001"]}], "target_paths": ["module.rs"]}
            state = {"tasks": {"T001": {"status": "pending"}}}
            materialize(root, plan, state)
            projected = source.read_bytes()
            self.assertNotIn(b"\n", projected.replace(b"\r\n", b""))
            materialize(root, plan, state)
            self.assertEqual(source.read_bytes(), projected)
            remove_anchor(root, task, plan)
            self.assertEqual(source.read_bytes(), original)

    def test_goal_survives_ascii_console_with_unicode_instructions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".rdd/goals").mkdir(parents=True)
            (root / ".rdd/config.json").write_bytes((ROOT / ".rdd/config.json").read_bytes())
            goal = "Verify café, 日本語 and 🚀 without changing the frozen boundary."
            (root / ".rdd/goals/implementation.txt").write_bytes(goal.encode("utf-8"))
            result = subprocess.run([sys.executable, str(ROOT / "tools/rdd/cli.py"),
                                     "--root", str(root), "goal"], capture_output=True,
                                    env={**os.environ, "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0"},
                                    timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
            self.assertEqual(result.stdout.decode("utf-8").strip(), goal)

    def test_evidence_bytes_are_utf8_lf_independent_of_host_newline(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "receipt.json"
            value = {"observation": "日本語 café\nsecond line", "count": 2}
            write_json(destination, value)
            raw = destination.read_bytes()
            self.assertNotIn(b"\r", raw)
            self.assertIn("日本語".encode(), raw)
            self.assertEqual(read_json(destination), value)

    def test_unicode_child_diagnostics_survive_log_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = "Boundary rejection: café 日本語 🚀"
            result = run_argv([sys.executable, "-c", "import sys; print(" + repr(text) +
                               "); print('declared error', file=sys.stderr)"], root,
                              env={"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                              stdout_path=root / "stdout.log", stderr_path=root / "stderr.log")
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), text)
            self.assertEqual((root / "stdout.log").read_bytes().decode().strip(), text)
            self.assertEqual((root / "stderr.log").read_text(encoding="utf-8").strip(), "declared error")


if __name__ == "__main__":
    unittest.main()
