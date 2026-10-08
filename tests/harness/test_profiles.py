"""Profile-policy contracts, using disposable copies of the real native configuration."""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from tools.rdd.common import RddError, file_hash
from tools.rdd.profiles import (
    IMPLEMENTOR_ROLES, IMPLEMENTOR_SCOPES, PROFILE_NAMES, WORKFLOW_AUTHOR_ROLES,
    load_profiles, profile_policy_digest, profile_settings,
)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rdd-profiles-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(Path(__file__).resolve().parents[2] / ".codex", self.root / ".codex")

    def path(self, role="rdd_complex_implementor"):
        return self.root / ".codex/agents" / f"{role}.toml"

    def replace(self, before, after, role="rdd_complex_implementor"):
        path = self.path(role)
        path.write_text(path.read_text().replace(before, after), encoding="utf-8")

    def rejects(self, text):
        with self.assertRaisesRegex(RddError, text) as error:
            load_profiles(self.root)
        self.assertEqual(error.exception.kind, "environment")

    def test_exact_roster_scope_and_requested_identity(self):
        profiles = load_profiles(self.root)
        self.assertEqual(tuple(profiles), PROFILE_NAMES)
        self.assertEqual(len(profiles), 10)
        self.assertEqual(IMPLEMENTOR_ROLES, ("rdd_complex_implementor", "rdd_light_implementor"))
        self.assertEqual(IMPLEMENTOR_SCOPES[IMPLEMENTOR_ROLES[0]], {"small", "large"})
        self.assertEqual(IMPLEMENTOR_SCOPES[IMPLEMENTOR_ROLES[1]], {"small"})
        self.assertEqual(set(WORKFLOW_AUTHOR_ROLES), set(PROFILE_NAMES) - set(IMPLEMENTOR_ROLES) - {"rdd_researcher", "rdd_reviewer"})
        identity = profile_settings(self.root, "rdd_complex_implementor")
        self.assertEqual(identity["profile_hash"], file_hash(self.path()))
        self.assertEqual(identity["model"], "gpt-6.1-sol")
        self.assertEqual(identity["effort"], "xhigh")
        self.assertNotIn("verified", identity)

    def test_missing_profile_rejected(self):
        self.path().unlink()
        self.rejects("Required file is missing")

    def test_malformed_and_duplicate_toml_keys_rejected(self):
        self.path().write_text('name="broken"\nname="duplicate"\n')
        self.rejects("Invalid RDD profile policy")

    def test_filename_name_mismatch_rejected(self):
        self.replace('name = "rdd_complex_implementor"', 'name = "rdd_light_implementor"')
        self.rejects("filename/name mismatch")

    def test_blank_instructions_rejected(self):
        path = self.path()
        path.write_text(path.read_text().split("developer_instructions =")[0] + 'developer_instructions = ""\n')
        self.rejects("invalid developer_instructions")

    def test_wrong_field_type_rejected(self):
        self.replace('model_reasoning_effort = "xhigh"', "model_reasoning_effort = 7")
        self.rejects("invalid model_reasoning_effort")

    def test_unknown_profile_setting_rejected_instead_of_ignored(self):
        with self.path().open("a") as output:
            output.write('\nunsupported_runtime_setting = "ignored?"\n')
        self.rejects("unsupported settings")

    def test_invalid_model_or_effort_rejected(self):
        self.replace('model = "gpt-6.1-sol"', 'model = "--injected"')
        self.rejects("invalid model/effort")

    def test_unknown_effort_rejected(self):
        self.replace('model_reasoning_effort = "xhigh"', 'model_reasoning_effort = "imaginary"')
        self.rejects("invalid model/effort")

    def test_readonly_profiles_must_remain_readonly(self):
        for role in ("rdd_researcher", "rdd_reviewer"):
            with self.subTest(role=role):
                self.replace('sandbox_mode = "read-only"', 'sandbox_mode = "workspace-write"', role)
                self.rejects("requires read-only")
                self.replace('sandbox_mode = "workspace-write"', 'sandbox_mode = "read-only"', role)

    def test_author_cannot_request_unbounded_sandbox(self):
        self.replace('sandbox_mode = "workspace-write"', 'sandbox_mode = "danger-full-access"')
        self.rejects("requires workspace-write")

    def test_canonical_symlink_rejected(self):
        profile = self.path()
        original = self.root / "actual.toml"
        profile.rename(original)
        try:
            profile.symlink_to(original)
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")
        self.rejects("Symlink")

    def test_native_defaults_must_match_profiles(self):
        config = self.root / ".codex/config.toml"
        config.write_text(config.read_text().replace('default_subagent_model = "gpt-6.1-sol"', 'default_subagent_model = "gpt-6-luna"'))
        self.rejects("configuration/profile drift")

    def test_native_author_slots_cannot_expand(self):
        config = self.root / ".codex/config.toml"
        config.write_text(config.read_text().replace("max_concurrent_threads_per_session = 3", "max_concurrent_threads_per_session = 4"))
        self.rejects("three child slots")

    def test_extra_custom_profile_is_not_rdd_authority(self):
        before = profile_policy_digest(self.root)
        extra = self.root / ".codex/agents/custom.toml"
        extra.write_text('name = "custom"\ndescription="Unrelated role"\n')
        self.assertNotIn("custom", load_profiles(self.root))
        self.assertEqual(before, profile_policy_digest(self.root))
        with self.assertRaisesRegex(RddError, "Unknown RDD role"):
            profile_settings(self.root, "custom")

    def test_second_file_cannot_redeclare_canonical_name(self):
        extra = self.root / ".codex/agents/duplicate.toml"
        extra.write_text('name = "rdd_reviewer"\n')
        self.rejects("name collision")

    def test_symlink_alias_cannot_redeclare_canonical_name(self):
        alias = self.root / ".codex/agents/alias.toml"
        try:
            alias.symlink_to(self.path("rdd_reviewer"))
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")
        self.rejects("name collision")

    def test_unrelated_in_repo_symlink_profile_remains_allowed(self):
        target = self.root / "custom.toml"
        target.write_text('name = "custom"\n')
        alias = self.root / ".codex/agents/custom.toml"
        try:
            alias.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")
        self.assertNotIn("custom", load_profiles(self.root))

    def test_profile_or_native_edits_change_identity(self):
        before = profile_policy_digest(self.root)
        with self.path().open("a") as output:
            output.write("\n# changed profile context\n")
        self.assertNotEqual(before, profile_policy_digest(self.root))
        before = profile_policy_digest(self.root)
        with (self.root / ".codex/config.toml").open("a") as output:
            output.write("\n# changed native context\n")
        self.assertNotEqual(before, profile_policy_digest(self.root))


if __name__ == "__main__":
    unittest.main()
