"""Offline contract tests for external adapters; no model/API calls or PR writes."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import tomllib
import unittest

from tools.rdd.adapters import (
    CodexAdapter, CommandResult, GitAdapter, GitHubAdapter, RddAdapterError,
    phase_branch, run_argv, validate_structured_output,
)
from tools.rdd.profiles import load_profiles, profile_settings


HEAD = "a" * 40
BASE = "b" * 40
OTHER = "c" * 40


def result(argv, value="", code=0, stderr=""):
    return CommandResult(tuple(argv), code,
                         json.dumps(value) if not isinstance(value, str) else value, stderr)


def valid_pr():
    return {"number": 7, "url": "https://github.com/example/repo/pull/7",
            "headRefName": "rdd/run-1/p01", "headRefOid": HEAD,
            "baseRefName": "main", "baseRefOid": BASE, "state": "OPEN",
            "isDraft": False, "isCrossRepository": False,
            "body": "<!-- rdd:run=run-1 phase=1 -->\n\nA concrete phase description.",
            "reviewDecision": "", "latestReviews": [],
            "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [{"name": "rdd-verify", "status": "COMPLETED", "conclusion": "SUCCESS"}]}


def local_review():
    return {"passed": True, "head_sha": HEAD, "reviewer": "rdd_reviewer", "findings": []}


class FakeHub:
    def __init__(self, prs=None):
        self.prs = copy.deepcopy(prs if prs is not None else [valid_pr()])
        self.calls = []
        self.views = []
        self.checks = [{"name": "rdd-verify", "state": "SUCCESS", "bucket": "pass", "link": "https://example.invalid/check/1"}]
        self.checks_code = 0
        self.dirty = ""
        self.remote_base = BASE
        self.created_body = None

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[0] == "git":
            if argv[1] == "status":
                return result(argv, self.dirty)
            if argv[1] == "rev-parse":
                return result(argv, BASE if argv[-1].startswith("main") else HEAD)
            if argv[1] == "ls-remote":
                return result(argv, f"{self.remote_base}\trefs/heads/main\n")
            if argv[1] in ("merge-base", "push"):
                return result(argv)
        if argv[:3] == ["gh", "pr", "list"]:
            return result(argv, self.prs)
        if argv[:3] == ["gh", "pr", "view"]:
            return result(argv, self.views.pop(0) if self.views else self.prs[0])
        if argv[:3] == ["gh", "pr", "checks"]:
            return result(argv, self.checks, self.checks_code)
        if argv[:3] == ["gh", "pr", "create"]:
            self.created_body = Path(argv[argv.index("--body-file") + 1]).read_text(encoding="utf-8")
            self.prs = [valid_pr()]
            return result(argv, self.prs[0]["url"])
        raise AssertionError(f"Unexpected external command: {argv}")


class RunArgvTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_shell_metacharacters_are_plain_arguments(self):
        payload = "$(touch SHOULD_NOT_EXIST); `echo no`; $HOME"
        run = run_argv([sys.executable, "-c", "import sys;print(sys.argv[1])", payload], self.root)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(run.stdout.strip(), payload)
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())

    def test_rejects_command_string(self):
        with self.assertRaises(RddAdapterError) as error:
            run_argv("echo unsafe", self.root)
        self.assertEqual(error.exception.code, "invalid-argv")

    def test_missing_executable_is_a_named_blocker(self):
        with self.assertRaises(RddAdapterError) as error:
            run_argv([str(self.root / "unavailable")], self.root)
        self.assertEqual(error.exception.code, "missing-tool")

    def test_stdout_stderr_and_input_stream_without_deadlock(self):
        seen = []
        code = "import sys; t=sys.stdin.read(); print(t); print('diagnostic',file=sys.stderr)"
        run = run_argv([sys.executable, "-c", code], self.root, input_text="hello",
                       stdout_path=self.root / "events.jsonl", stderr_path=self.root / "stderr.log",
                       on_stdout_line=seen.append)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(seen, ["hello\n"])
        self.assertEqual((self.root / "stderr.log").read_text(), "diagnostic\n")

    def test_timeout_returns_partial_evidence(self):
        started = time.monotonic()
        run = run_argv([sys.executable, "-u", "-c", "import time; print('started'); time.sleep(30)"],
                       self.root, timeout=0.3)
        self.assertTrue(run.timed_out)
        self.assertIn("started", run.stdout)
        self.assertLess(time.monotonic() - started, 5)

    def test_capture_is_bounded_but_log_is_complete(self):
        run = run_argv([sys.executable, "-c", "print('x'*1000)"], self.root,
                       max_capture_bytes=100, stdout_path=self.root / "output.log")
        self.assertTrue(run.output_truncated)
        self.assertEqual(len(run.stdout), 100)
        self.assertEqual((self.root / "output.log").stat().st_size, 1001)

    def test_evidence_log_is_never_overwritten(self):
        log = self.root / "output.log"
        log.write_text("prior evidence")
        with self.assertRaises(FileExistsError):
            run_argv([sys.executable, "-c", "print('new')"], self.root, stdout_path=log)
        self.assertEqual(log.read_text(), "prior evidence")


@unittest.skipUnless(shutil.which("git"), "Git is needed for local worktree tests")
class GitAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name).resolve()
        self.root = self.parent / "repo"
        self.root.mkdir()
        self.addCleanup(self.temp.cleanup)
        for args in (["git", "init", "-b", "main"], ["git", "config", "user.name", "Harness Test"],
                     ["git", "config", "user.email", "harness@example.invalid"]):
            self.assertEqual(run_argv(args, self.root).returncode, 0)
        (self.root / "README.md").write_text("baseline\n")
        run_argv(["git", "add", "README.md"], self.root)
        self.assertEqual(run_argv(["git", "commit", "-m", "test baseline"], self.root).returncode, 0)
        self.git = GitAdapter(self.root)

    def test_phase_branch_is_idempotent_and_preserves_baseline(self):
        baseline = self.git.current_head()
        branch = self.git.create_phase_branch("run-1", 1, "main")
        self.assertEqual(branch, "rdd/run-1/p01")
        self.assertEqual(self.git.create_phase_branch("run-1", 1, "main"), branch)
        self.assertEqual(self.git.current_head(branch), baseline)

    def test_worktree_reuse_is_exact_and_dirty_work_is_preserved(self):
        path = self.parent / "worker"
        branch = phase_branch("run-1", 1)
        self.assertEqual(self.git.ensure_worktree(path, branch, "main"), path)
        self.assertEqual(self.git.ensure_worktree(path, branch, "main"), path)
        (path / "README.md").write_text("uncommitted user work\n")
        with self.assertRaises(RddAdapterError) as error:
            self.git.ensure_worktree(path, branch, "main")
        self.assertEqual(error.exception.code, "dirty-worktree")
        self.assertEqual((path / "README.md").read_text(), "uncommitted user work\n")

    def test_arbitrary_nonempty_directory_is_never_overwritten(self):
        path = self.parent / "user-files"
        path.mkdir()
        (path / "precious.txt").write_text("keep")
        with self.assertRaises(RddAdapterError):
            self.git.ensure_worktree(path, phase_branch("run-1", 1), "main")
        self.assertEqual((path / "precious.txt").read_text(), "keep")

    def test_rejects_revision_expressions_and_option_injection(self):
        for ref in ("--all", "main~1", "main;echo bad", "main^{tree}", "main..other"):
            with self.subTest(ref=ref), self.assertRaises(RddAdapterError):
                self.git.current_head(ref)


class GitHubAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.fake = FakeHub()
        self.adapter = GitHubAdapter(self.root, self.fake)
        self.body = self.root / "pr-body.md"
        self.body.write_text("Keep literal `code` and $(no shell).\nSecond paragraph.\n")

    def status(self, **kwargs):
        return self.adapter.phase_status(7, HEAD, "main", ["rdd-verify"],
                                         expected_base_sha=BASE, **kwargs)

    def test_passes_only_with_checks_and_exact_head_review(self):
        outcome = self.status(review_evidence=local_review())
        self.assertTrue(outcome["ready"], outcome)
        self.assertEqual(outcome["review_source"], "local")

    def test_no_review_is_not_ready(self):
        outcome = self.status()
        self.assertFalse(outcome["ready"])
        self.assertTrue(any("review" in item for item in outcome["blockers"]))

    def test_stale_local_review_is_not_ready(self):
        review = local_review()
        review["head_sha"] = OTHER
        self.assertFalse(self.status(review_evidence=review)["ready"])

    def test_github_changes_requested_vetoes_local_review(self):
        self.fake.prs[0]["reviewDecision"] = "CHANGES_REQUESTED"
        self.assertFalse(self.status(review_evidence=local_review())["ready"])

    def test_optional_github_approval_requires_review_on_exact_head(self):
        self.fake.prs[0]["reviewDecision"] = "APPROVED"
        self.fake.prs[0]["latestReviews"] = [{"state": "APPROVED", "commit": {"oid": OTHER}}]
        self.assertFalse(self.status(require_github_approval=True)["ready"])
        self.fake.prs[0]["latestReviews"][0]["commit"]["oid"] = HEAD
        self.assertTrue(self.status(require_github_approval=True)["ready"])

    def test_no_checks_is_not_success(self):
        self.fake.prs[0]["statusCheckRollup"] = []
        self.fake.checks = []
        self.assertFalse(self.status(review_evidence=local_review())["ready"])

    def test_missing_required_config_is_a_blocker(self):
        with self.assertRaises(RddAdapterError) as error:
            self.adapter.phase_status(7, HEAD, "main", [], review_evidence=local_review())
        self.assertEqual(error.exception.code, "missing-required-checks")

    def test_skipped_required_check_is_not_success(self):
        self.fake.prs[0]["statusCheckRollup"][0]["conclusion"] = "SKIPPED"
        self.fake.checks[0].update(bucket="skipping", state="SKIPPED")
        self.assertFalse(self.status(review_evidence=local_review())["ready"])

    def test_pending_required_check_is_not_success(self):
        self.fake.checks[0].update(bucket="pending", state="IN_PROGRESS")
        self.fake.checks_code = 8
        self.assertFalse(self.status(review_evidence=local_review())["ready"])

    def test_nonzero_check_command_cannot_pass_on_inconsistent_json(self):
        self.fake.checks_code = 1
        self.assertFalse(self.status(review_evidence=local_review())["ready"])

    def test_base_or_head_change_during_check_is_not_ready(self):
        first = valid_pr()
        second = valid_pr()
        second["baseRefOid"] = OTHER
        self.fake.views = [first, second]
        self.assertFalse(self.status(review_evidence=local_review())["ready"])

    def test_draft_or_unknown_mergeability_is_not_ready(self):
        self.fake.prs[0]["isDraft"] = True
        self.fake.prs[0]["mergeable"] = "UNKNOWN"
        self.assertFalse(self.status(review_evidence=local_review())["ready"])

    def test_create_uses_body_file_and_exact_phase_marker(self):
        self.fake.prs = []
        outcome = self.adapter.publish_phase_pr("run-1", 1, "main", self.body,
                                                expected_base_sha=BASE)
        self.assertEqual(outcome["number"], 7)
        self.assertIn("<!-- rdd:run=run-1 phase=1 -->", self.fake.created_body)
        self.assertIn("$(no shell)", self.fake.created_body)
        self.assertFalse(any("merge" in call or "--force" in call for call in self.fake.calls))

    def test_repeated_publish_does_not_create_another_pr(self):
        self.adapter.publish_phase_pr("run-1", 1, "main", self.body)
        self.adapter.publish_phase_pr("run-1", 1, "main", self.body)
        self.assertFalse(any(call[:3] == ["gh", "pr", "create"] for call in self.fake.calls))

    def test_closed_duplicate_or_wrong_marker_cannot_be_republished(self):
        for mutation in ("closed", "duplicate", "marker"):
            self.fake.prs = [valid_pr()]
            if mutation == "closed":
                self.fake.prs[0]["state"] = "CLOSED"
            elif mutation == "duplicate":
                self.fake.prs.append(valid_pr())
            else:
                self.fake.prs[0]["body"] = "another workflow"
            with self.subTest(mutation=mutation), self.assertRaises(RddAdapterError):
                self.adapter.publish_phase_pr("run-1", 1, "main", self.body)
        self.assertFalse(any(call[:2] == ["git", "push"] for call in self.fake.calls))

    def test_moved_remote_base_blocks_before_push(self):
        self.fake.remote_base = OTHER
        with self.assertRaises(RddAdapterError) as error:
            self.adapter.publish_phase_pr("run-1", 1, "main", self.body, expected_base_sha=BASE)
        self.assertEqual(error.exception.code, "moved-remote-base")
        self.assertFalse(any(call[:2] == ["git", "push"] for call in self.fake.calls))


class CodexAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        original = Path(__file__).resolve().parents[2]
        shutil.copytree(original / ".codex", self.root / ".codex")
        self.schema = self.root / "answer.schema.json"
        self.schema.write_text(json.dumps({"type": "object", "properties": {"done": {"type": "boolean"}},
                                           "required": ["done"], "additionalProperties": False}))
        self.answer = {"done": True}
        self.emit_complete = True
        self.emit_error = False
        self.calls = []

    def runner(self, argv, **kwargs):
        self.calls.append(list(argv))
        callback = kwargs["on_stdout_line"]
        events = [{"type": "thread.started", "thread_id": "session-123"}]
        if self.emit_complete:
            events.append({"type": "turn.completed", "usage": {"output_tokens": 10}})
        if self.emit_error:
            events.append({"type": "error", "message": "model unavailable"})
        lines = [json.dumps(event) + "\n" for event in events]
        for line in lines:
            callback(line)
        Path(kwargs["stdout_path"]).write_text("".join(lines))
        Path(kwargs["stderr_path"]).write_text("")
        output = Path(argv[argv.index("--output-last-message") + 1])
        output.write_text(json.dumps(self.answer))
        return result(argv)

    def execute(self, attempt="attempt-1"):
        return CodexAdapter(self.root, runner=self.runner).exec(
            "Implement the leased target.", self.schema, self.root / ".rdd/runtime" / attempt,
            "rdd_complex_implementor", timeout=60)

    def test_native_launch_applies_coordinator_instructions_without_approval_override(self):
        prompt = '--last; $(touch INJECTED); `echo no`; $HOME\nUnicode 🧪'
        argv = CodexAdapter(self.root, runner=self.runner).native_argv(prompt)
        coordinator = load_profiles(self.root)["rdd_coordinator"]
        self.assertEqual(argv[:3], ["codex", "--cd", str(self.root.resolve())])
        self.assertEqual(argv[argv.index("--model") + 1], "gpt-6-astra")
        self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
        config = {}
        for index, argument in enumerate(argv):
            if argument == "--config":
                config.update(tomllib.loads(argv[index + 1]))
        self.assertEqual(config, {"model_reasoning_effort": "ultra",
                                 "developer_instructions": coordinator["developer_instructions"]})
        self.assertEqual(argv[-2:], ["--", prompt])
        for option in ("-a", "--ask-for-approval", "--approve-for-me", "--last",
                       "--dangerously-bypass-approvals-and-sandbox", "--no-daemon", "--profile"):
            self.assertNotIn(option, argv)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / "INJECTED").exists())

    def test_native_resume_selects_the_exact_uuid(self):
        session_id = "01234567-89ab-4cde-8fab-0123456789ab"
        adapter = CodexAdapter(self.root, runner=self.runner)
        launch = adapter.native_argv("Continue the recorded workflow.")
        resumed = adapter.native_argv("Continue the recorded workflow.", session_id=session_id)
        self.assertEqual(resumed, ["codex", "resume", session_id, *launch[1:]])
        self.assertNotIn("--last", resumed)

    def test_native_full_access_changes_only_sandbox_and_approval(self):
        prompt = '--last; $(touch INJECTED); `echo no`; $HOME\nUnicode 🧪'
        adapter = CodexAdapter(self.root, runner=self.runner)
        default = adapter.native_argv(prompt)
        explicit = adapter.native_argv(prompt, permission="full-access")
        expected = list(default)
        expected[expected.index("--sandbox") + 1] = "danger-full-access"
        expected[-2:-2] = ["--ask-for-approval", "never"]
        self.assertEqual(explicit, expected)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / "INJECTED").exists())

    def test_native_full_access_resume_preserves_exact_session_selection(self):
        session_id = "01234567-89ab-4cde-8fab-0123456789ab"
        adapter = CodexAdapter(self.root, runner=self.runner)
        launch = adapter.native_argv("Continue the recorded workflow.", permission="full-access")
        resumed = adapter.native_argv("Continue the recorded workflow.", session_id=session_id,
                                      permission="full-access")
        self.assertEqual(resumed, ["codex", "resume", session_id, *launch[1:]])
        self.assertNotIn("--last", resumed)

    def test_native_permission_reaches_real_subprocess_without_shell_interpretation(self):
        receiver = self.root / "native_receiver.py"
        receiver.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
        prompt = '--last; $(touch INJECTED); `echo no`; $HOME\nUnicode 🧪'
        for permission in (None, "full-access"):
            with self.subTest(permission=permission):
                argv = CodexAdapter(self.root).native_argv(prompt, permission=permission)
                received = run_argv([sys.executable, str(receiver), *argv[1:]], self.root, timeout=10)
                self.assertEqual(received.returncode, 0, received.stderr)
                actual = json.loads(received.stdout)
                self.assertEqual(actual, argv[1:])
                self.assertEqual(actual[actual.index("--sandbox") + 1],
                                 "danger-full-access" if permission else "workspace-write")
                if permission:
                    self.assertEqual(actual[actual.index("--ask-for-approval") + 1], "never")
                else:
                    self.assertNotIn("--ask-for-approval", actual)
                self.assertEqual(actual[-2:], ["--", prompt])
        self.assertFalse((self.root / "INJECTED").exists())

    def test_native_launch_rejects_unsupported_permission_without_execution(self):
        for permission in ("", "workspace-write", "danger-full-access", "read-only", True, 42, []):
            with self.subTest(permission=permission), self.assertRaises(RddAdapterError) as error:
                CodexAdapter(self.root, runner=self.runner).native_argv("Continue", permission=permission)
            self.assertEqual(error.exception.code, "invalid-permission")
        self.assertEqual(self.calls, [])

    def test_native_resume_rejects_names_options_and_ambiguous_session_ids(self):
        for session_id in ("", "friendly-name", "--last", "../session", "session-123", 42):
            with self.subTest(session_id=session_id), self.assertRaises(RddAdapterError) as error:
                CodexAdapter(self.root, runner=self.runner).native_argv("Continue", session_id=session_id)
            self.assertEqual(error.exception.code, "invalid-session-id")
        self.assertEqual(self.calls, [])

    def test_native_launch_rejects_empty_or_nul_prompt(self):
        for prompt in ("", "  ", "text\0more", None):
            with self.subTest(prompt=prompt), self.assertRaises(RddAdapterError) as error:
                CodexAdapter(self.root, runner=self.runner).native_argv(prompt)
            self.assertEqual(error.exception.code, "empty-prompt")

    def capability_runner(self, models, *, omitted=None):
        help_text = {
            (): "--config --model --sandbox --cd",
            ("exec",): "--json --config --model --sandbox --cd --color --output-schema --output-last-message",
            ("resume",): "Usage: codex resume [OPTIONS] [SESSION_ID] [PROMPT]\n--config --model --sandbox --cd",
            ("debug", "models"): "--bundled",
        }
        if omitted:
            command, flag = omitted
            help_text[command] = help_text[command].replace(flag, "")

        def runner(argv, **kwargs):
            self.calls.append(list(argv))
            if "--version" in argv:
                return result(argv, "codex-cli 0.162.1")
            if argv[-1] == "--help":
                return result(argv, help_text[tuple(argv[1:-1])])
            if argv[1:3] == ["debug", "models"]:
                return result(argv, {"models": models})
            if argv[1:] == ["login", "status"]:
                return result(argv)
            raise AssertionError(f"Unexpected Codex capability command: {argv}")
        return runner

    def test_doctor_rejects_missing_native_or_resume_capabilities(self):
        models = [{"slug": "gpt-6-astra", "supported_reasoning_levels": [{"effort": "ultra"}]}]
        for command, flag in (((), "--config"), ((), "--sandbox"), (("resume",), "SESSION_ID"),
                              (("resume",), "--cd"), (("debug", "models"), "--bundled")):
            with self.subTest(command=command, flag=flag):
                runner = self.capability_runner(models, omitted=(command, flag))
                report = CodexAdapter(self.root, runner=runner).doctor([("gpt-6-astra", "ultra")])
                self.assertFalse(report["ready"], report)
                self.assertTrue(any(flag in blocker for blocker in report["blockers"]), report)

    def test_bounded_exec_persists_session_and_schema_valid_answer(self):
        outcome = self.execute()
        self.assertEqual(outcome["session_id"], "session-123")
        self.assertEqual(outcome["answer"], {"done": True})
        self.assertEqual(outcome["receipt"]["status"], "completed")
        self.assertIn("--json", self.calls[0])
        self.assertNotIn("--goal", self.calls[0])
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", self.calls[0])
        self.assertTrue((self.root / ".rdd/runtime/attempt-1/events.jsonl").exists())

    def test_bounded_exec_delivers_profile_instructions(self):
        profile = self.root / ".codex/agents/rdd_complex_implementor.toml"
        instructions = 'Bounded instructions with "quotes", \\backslash and\nUnicode 🧪; $(touch INJECTED); `echo no`; $HOME.\x7f'
        text = profile.read_text()
        profile.write_text(text[:text.index("developer_instructions =")] +
                           "developer_instructions = " + json.dumps(instructions, ensure_ascii=False).replace("\x7f", "\\u007f") + "\n")
        outcome = self.execute()
        applied = next(argument for argument in self.calls[0] if argument.startswith("developer_instructions="))
        self.assertEqual(tomllib.loads(applied)["developer_instructions"], instructions)
        self.assertEqual(outcome["requested_runtime"], profile_settings(self.root, "rdd_complex_implementor"))
        self.assertNotIn("observed_model", outcome["receipt"])
        self.assertFalse((self.root / "INJECTED").exists())

    def test_readonly_profile_cannot_gain_writes(self):
        with self.assertRaises(RddAdapterError) as error:
            CodexAdapter(self.root, runner=self.runner).exec(
                "Review", self.schema, self.root / ".rdd/runtime/unsafe",
                "rdd_reviewer", sandbox="workspace-write")
        self.assertEqual(error.exception.code, "invalid-sandbox")
        self.assertFalse((self.root / ".rdd/runtime/unsafe").exists())

    def test_writable_profile_can_be_restricted_to_readonly(self):
        outcome = CodexAdapter(self.root, runner=self.runner).exec(
            "Give bounded advice", self.schema, self.root / ".rdd/runtime/advice",
            "rdd_contract_architect", sandbox="read-only")
        self.assertEqual(outcome["requested_runtime"]["sandbox"], "read-only")
        self.assertEqual(self.calls[0][self.calls[0].index("--sandbox") + 1], "read-only")

    def test_real_subprocess_receives_exact_config_instructions(self):
        """Exercise argv transport and TOML parsing, without a paid model call."""
        receiver = self.root / "runtime_receiver.py"
        receiver.write_text('''import json, pathlib, sys, tomllib
args = sys.argv[1:]
config = {}
for index, argument in enumerate(args):
    if argument == "--config":
        config.update(tomllib.loads(args[index + 1]))
profile = tomllib.loads(pathlib.Path(".codex/agents/rdd_complex_implementor.toml").read_text())
correct = config.get("developer_instructions") == profile["developer_instructions"]
sys.stdin.read()
pathlib.Path(args[args.index("--output-last-message") + 1]).write_text(json.dumps({"done": correct}))
print(json.dumps({"type": "thread.started", "thread_id": "subprocess-session"}))
print(json.dumps({"type": "turn.completed"}))
''', encoding="utf-8")

        def subprocess_runner(argv, **kwargs):
            return run_argv([sys.executable, str(receiver), *argv[1:]], **kwargs)

        outcome = CodexAdapter(self.root, runner=subprocess_runner).exec(
            "User text cannot replace developer instructions", self.schema,
            self.root / ".rdd/runtime/process", "rdd_complex_implementor", timeout=10)
        self.assertTrue(outcome["answer"]["done"])
        self.assertEqual(outcome["session_id"], "subprocess-session")

    def test_unknown_role_is_rejected_before_writing_runtime(self):
        with self.assertRaises(RddAdapterError) as error:
            CodexAdapter(self.root, runner=self.runner).exec(
                "Target", self.schema, self.root / ".rdd/runtime/unknown", "custom_author")
        self.assertEqual(error.exception.code, "invalid-profile")
        self.assertFalse((self.root / ".rdd/runtime/unknown").exists())

    def test_reusing_a_worker_directory_cannot_reuse_old_answer(self):
        self.execute()
        with self.assertRaises(RddAdapterError) as error:
            self.execute()
        self.assertEqual(error.exception.code, "reused-worker-directory")

    def test_zero_exit_without_turn_completion_is_not_success(self):
        self.emit_complete = False
        with self.assertRaises(RddAdapterError):
            self.execute()
        receipt = json.loads((self.root / ".rdd/runtime/attempt-1/receipt.json").read_text())
        self.assertEqual(receipt["status"], "failed")

    def test_schema_mismatch_does_not_complete_worker(self):
        self.answer = {"done": "probably"}
        with self.assertRaises(RddAdapterError) as error:
            self.execute()
        self.assertEqual(error.exception.code, "schema-mismatch")

    def test_error_event_does_not_complete_worker_even_with_answer(self):
        self.emit_error = True
        with self.assertRaises(RddAdapterError):
            self.execute()

    def test_output_cannot_escape_runtime_directory(self):
        with self.assertRaises(RddAdapterError) as error:
            CodexAdapter(self.root, runner=self.runner).exec("target", self.schema,
                self.root / "public", "rdd_light_implementor")
        self.assertEqual(error.exception.code, "unsafe-runtime-path")

    def test_doctor_reports_client_support_without_claiming_entitlement(self):
        profiles = load_profiles(self.root)
        pairs = [(settings["model"], settings["effort"]) for settings in profiles.values()]
        doctor_runner = self.capability_runner([
            {"slug": model, "supported_reasoning_levels": [{"effort": effort}]}
            for model, effort in dict.fromkeys(pairs)
        ])
        report = CodexAdapter(self.root, runner=doctor_runner).doctor(pairs, roles=profiles)
        self.assertTrue(report["ready"])
        self.assertFalse(report["account_access_verified"])
        self.assertEqual(report["catalog_scope"], "bundled")
        self.assertEqual(len(report["models"]), 3)
        self.assertEqual(sorted(role for pair in report["models"] for role in pair["roles"]), sorted(profiles))

    def test_doctor_cannot_succeed_with_omitted_model_inventory(self):
        report = CodexAdapter(self.root, runner=self.runner).doctor([])
        self.assertFalse(report["ready"])
        self.assertIn("missing-model-policy", report["blockers"][0])
        self.assertEqual(self.calls, [])

    def test_doctor_reports_unsupported_pair_and_affected_roles(self):
        doctor_runner = self.capability_runner([])
        profiles = load_profiles(self.root)
        report = CodexAdapter(self.root, runner=doctor_runner).doctor(
            [("gpt-6.1-sol", "xhigh")], roles=profiles)
        self.assertFalse(report["ready"])
        self.assertIn("rdd_domain_analyst", report["blockers"][0])
        self.assertFalse(report["account_access_verified"])

    def test_doctor_default_or_other_model_effort_cannot_replace_required_pair(self):
        runner = self.capability_runner([
            {"slug": "gpt-6-astra", "default_reasoning_level": "ultra",
             "supported_reasoning_levels": [{"effort": "high"}]},
            {"slug": "other-model", "supported_reasoning_levels": [{"effort": "ultra"}]},
        ])
        report = CodexAdapter(self.root, runner=runner).doctor([("gpt-6-astra", "ultra")])
        self.assertFalse(report["ready"])
        self.assertFalse(report["models"][0]["client_advertises"])
        self.assertIn("gpt-6-astra with ultra", report["blockers"][0])

    def test_schema_unsupported_keywords_fail_closed(self):
        with self.assertRaises(RddAdapterError) as error:
            validate_structured_output("thing", {"type": "string", "format": "email"})
        self.assertEqual(error.exception.code, "unsupported-schema")


@unittest.skipUnless(os.environ.get("RDD_CODEX_SMOKE"), "Set RDD_CODEX_SMOKE to an installed Codex binary for the read-only smoke test")
class InstalledCodexSmokeTests(unittest.TestCase):
    def test_version_flags_and_bundled_catalog_without_auth_or_generation(self):
        binary = os.environ["RDD_CODEX_SMOKE"]
        root = Path(__file__).resolve().parents[2]
        version = run_argv([binary, "--version"], root, timeout=15)
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertRegex(version.stdout, r"codex-cli \d+\.\d+\.\d+")
        help_result = run_argv([binary, "exec", "--help"], root, timeout=15)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        for flag in ("--json", "--output-schema", "--output-last-message"):
            self.assertIn(flag, help_result.stdout)
        catalog = run_argv([binary, "debug", "models", "--bundled"], root, timeout=30)
        self.assertEqual(catalog.returncode, 0, catalog.stderr)
        self.assertFalse(catalog.output_truncated)
        models = {item["slug"]: item for item in json.loads(catalog.stdout)["models"]}
        for model, effort in {(settings["model"], settings["effort"]) for settings in load_profiles(root).values()}:
            self.assertIn(model, models)
            self.assertIn(effort, [item["effort"] for item in models[model]["supported_reasoning_levels"]])

    def test_native_launch_and_resume_flags_parse_without_starting_a_session(self):
        binary = os.environ["RDD_CODEX_SMOKE"]
        root = Path(__file__).resolve().parents[2]
        adapter = CodexAdapter(root, binary=binary)
        for permission in (None, "full-access"):
            for session_id in (None, "01234567-89ab-4cde-8fab-0123456789ab"):
                with self.subTest(permission=permission, session_id=session_id):
                    argv = adapter.native_argv("Read-only syntax check", session_id=session_id,
                                               permission=permission)
                    help_result = run_argv([*argv[:-2], "--help"], root, timeout=15)
                    self.assertEqual(help_result.returncode, 0, help_result.stderr)
                    if session_id:
                        self.assertIn("SESSION_ID", help_result.stdout)
                    for flag in ("--config", "--model", "--sandbox", "--cd"):
                        self.assertIn(flag, help_result.stdout)
                    if permission:
                        self.assertIn("--ask-for-approval", help_result.stdout)


if __name__ == "__main__":
    unittest.main()
