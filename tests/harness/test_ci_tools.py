"""Declared CI inputs must provision the measured tool, never an arbitrary command."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.rdd.adapters import CommandResult
from tools.rdd.ci_tools import preparation_matrix, provision, tool_plan


class ToolProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".rdd").mkdir()
        (self.root / "rust-toolchain.toml").write_text('[toolchain]\nchannel="1.99.0"\n')

    def spec(self, resources):
        data = {"environments": [{"id": "CI", "platform": "windows", "host_profile": None},
                                 {"id": "REF", "platform": "windows", "host_profile": "Reference PC"}],
                "resources": [{"id": f"TOOL{i}", "kind": "tool", "path": name,
                               "version": version, "environments": [environment]}
                              for i, (name, version, environment) in enumerate(resources)]}
        (self.root / ".rdd/spec.json").write_text(json.dumps(data), encoding="utf-8")

    def test_conflicting_alias_pins_cannot_select_accidentally_cached_python(self):
        self.spec([("python", "3.11.9", "CI"), ("python3", "3.12.8", "CI")])
        with self.assertRaisesRegex(ValueError, "Conflicting Python"):
            tool_plan(self.root, "windows")

    def test_declared_rust_must_match_toolchain(self):
        self.spec([("cargo", "1.98.0", "CI")])
        with self.assertRaisesRegex(ValueError, "conflicts with rust-toolchain"):
            tool_plan(self.root, "windows")

    def test_manifest_cannot_supply_an_installer_command_or_version_expression(self):
        for name, version in (("python;touch injected", "3.11.9"),
                              ("../python", "3.11.9"), ("python", ">=3.11")):
            with self.subTest(name=name, version=version):
                self.spec([(name, version, "CI")])
                with self.assertRaises(ValueError):
                    tool_plan(self.root, "windows")

    def test_qualified_host_does_not_claim_hosted_provisioning(self):
        self.spec([("python", "3.11.9", "CI"), ("python", "3.12.8", "REF")])
        self.assertEqual(tool_plan(self.root, "windows")["python"], "3.11.9")

    def test_preparation_selects_only_declared_hosted_environments(self):
        self.spec([])
        self.assertEqual(preparation_matrix(self.root), {"include": [{"platform": "windows", "os": "windows-latest"}]})
        path = self.root / ".rdd/spec.json"
        data = json.loads(path.read_bytes())
        data["environments"] = [data["environments"][1]]
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "at least one supported"):
            preparation_matrix(self.root)

    def test_wrong_installed_version_fails_and_preserves_bound_attempt(self):
        self.spec([("buf", "1.73.0", "CI")])
        evidence = self.root / "evidence"
        def runner(argv, *args, **kwargs):
            output = "1.72.0\n" if argv[-1] == "--version" else "installed\n"
            Path(kwargs["stdout_path"]).write_bytes(output.encode())
            Path(kwargs["stderr_path"]).write_bytes(b"")
            return CommandResult(tuple(argv), 0, output)
        with patch("tools.rdd.ci_tools.git", return_value="a" * 40), \
             patch("tools.rdd.ci_tools.shutil.which", return_value="buf"), \
             patch("tools.rdd.ci_tools.run_argv", side_effect=runner):
            with self.assertRaisesRegex(ValueError, "Measured buf does not match"):
                provision(self.root, tool_plan(self.root, "windows"), evidence)
        receipt = json.loads((evidence / "commands.json").read_bytes())
        self.assertEqual(receipt["identities"]["candidate_commit"], "a" * 40)
        self.assertEqual(len(receipt["identities"]["spec_file_sha256"]), 64)
        self.assertEqual((evidence / "02-stdout.log").read_bytes(), b"1.72.0\n")
        self.assertFalse((evidence / "tools.json").exists())

    def test_failed_installer_does_not_emit_success_receipt(self):
        with patch("tools.rdd.ci_tools.git", return_value="a" * 40), \
             patch("tools.rdd.ci_tools.run_argv", return_value=CommandResult(("rustup",), 1, "", "offline")):
            with self.assertRaisesRegex(ValueError, "Provisioning failed"):
                provision(self.root, tool_plan(self.root, "windows"), self.root / "evidence")
        self.assertFalse((self.root / "evidence/tools.json").exists())


if __name__ == "__main__":
    unittest.main()
