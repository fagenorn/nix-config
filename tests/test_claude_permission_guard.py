import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SETTINGS_PATH = Path(os.environ["CLAUDE_SETTINGS_PATH"])
EXPECTED_ALLOW = [
    "Bash(git fetch:*)", "Bash(git status:*)", "Bash(git log:*)",
    "Bash(git diff:*)", "Bash(gh pr view:*)", "Bash(gh pr list:*)",
    "Bash(gh pr checks:*)", "Bash(gh issue view:*)", "Bash(gh issue list:*)",
    "Bash(git worktree add:*)", "Bash(git worktree list:*)",
    "Bash(git worktree remove:*)", "Bash(git worktree prune:*)",
    "Bash(git branch -d:*)", "Bash(gh pr merge:*)", "Agent",
]


class ClaudePermissionGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        cls.settings = settings
        matches = [
            entry
            for entry in settings.get("hooks", {}).get("PreToolUse", [])
            if entry.get("matcher") == "Bash"
        ]
        if len(matches) != 1:
            raise AssertionError(f"expected one Bash PreToolUse matcher, found {len(matches)}")
        command_hooks = [
            hook
            for hook in matches[0].get("hooks", [])
            if hook.get("type") == "command"
        ]
        if len(command_hooks) != 1:
            raise AssertionError(f"expected one command hook, found {command_hooks!r}")
        command_hook = command_hooks[0]
        if command_hook.get("timeout") != 30:
            raise AssertionError(f"expected hook timeout 30, found {command_hook.get('timeout')!r}")
        if command_hook.get("args", []) != []:
            raise AssertionError(f"registered hook must pass no args: {command_hook.get('args')!r}")
        command = command_hook.get("command")
        if not isinstance(command, str) or " " in command:
            raise AssertionError(f"registered command must be one argument-free path: {command!r}")
        override_flags = ("--git-bin", "--gh-bin", "--jq-bin", "--child-timeout-seconds")
        if any(flag in command for flag in override_flags):
            raise AssertionError(f"registered command contains a test override: {command!r}")
        cls.guard = Path(command)
        if not cls.guard.is_absolute() or not os.access(cls.guard, os.X_OK):
            raise AssertionError(f"guard is not an executable absolute path: {cls.guard}")

        cls.fixture_dir = tempfile.TemporaryDirectory()
        cls.fake_gh = Path(cls.fixture_dir.name) / "fake-gh"
        cls.fake_gh.write_text(f"""#!{sys.executable}
import os, sys, time
stage = "pr" if sys.argv[1:3] == ["pr", "view"] else "protection"
mode = os.environ.get(f"FAKE_{{stage.upper()}}_MODE", "ok")
if mode == "nonzero":
    print(f"fake {{stage}} failure", file=sys.stderr)
    raise SystemExit(9)
if mode == "timeout":
    time.sleep(2)
if mode == "invalid":
    print("{{")
    raise SystemExit(0)
default = ('{{"state":"OPEN","baseRefName":"main",'
           '"url":"https://github.com/fagenorn/nix-config/pull/1"}}'
           if stage == "pr" else
           '{{"required_status_checks":{{"contexts":["Nix Eval"]}},'
           '"enforce_admins":{{"enabled":true}}}}')
print(os.environ.get(f"FAKE_{{stage.upper()}}_JSON", default))
""", encoding="utf-8")
        cls.fake_gh.chmod(0o755)

    @classmethod
    def tearDownClass(cls):
        cls.fixture_dir.cleanup()

    def invoke_raw(self, raw, *guard_args, env=None):
        child_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
        child_env.update(env or {})
        return subprocess.run(
            [self.guard, *guard_args], input=raw, text=True, capture_output=True,
            timeout=5, check=False, env=child_env,
        )

    def invoke_command(self, command, *guard_args, env=None):
        return self.invoke_raw(
            json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
            *guard_args, env=env,
        )

    def test_generated_allow_surface_is_exact_and_ordered(self):
        self.assertEqual(EXPECTED_ALLOW, self.settings["permissions"]["allow"])

    def test_unrelated_bash_and_exact_branch_delete_pass(self):
        for command in ("git status --short", "git branch -d issue-30-safe"):
            with self.subTest(command=command):
                result = self.invoke_command(command)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_malformed_hook_input_fails_closed(self):
        cases = (
            "not-json", "[]", "{}",
            json.dumps({"tool_name": "Read", "tool_input": {"command": "git branch -d x"}}),
            json.dumps({"tool_name": "Bash", "tool_input": {"command": 3}}),
        )
        for raw in cases:
            with self.subTest(raw=raw):
                result = self.invoke_raw(raw)
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: invalid hook input:", result.stderr)

    def test_unsafe_branch_delete_shapes_fail_closed(self):
        cases = (
            "git branch -d -f topic", "git branch -d --force topic",
            "git branch -d one two", "git branch -d -bad",
            "git branch -d topic && true", "git branch -d topic; true",
            "git branch -d $(printf topic)", "git branch -d topic*",
            "command git branch -d topic", "git branch -d topic\ntrue",
        )
        for command in cases:
            with self.subTest(command=command):
                result = self.invoke_command(command)
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe branch deletion:", result.stderr)

    def test_unsafe_merge_shapes_fail_before_network(self):
        cases = (
            "gh pr merge --repo fagenorn/nix-config --merge --delete-branch",
            "gh pr merge topic --repo fagenorn/nix-config --merge --delete-branch",
            "gh pr merge https://github.com/fagenorn/nix-config/pull/1 --repo fagenorn/nix-config --merge --delete-branch",
            "gh pr merge 1 --repo someone/else --merge --delete-branch",
            "gh pr merge 1 -R fagenorn/nix-config --merge --delete-branch",
            "gh pr merge 1 --repo fagenorn/nix-config --admin --merge --delete-branch",
            "gh pr merge 1 --repo fagenorn/nix-config --squash --delete-branch",
            "gh pr merge 1 --repo fagenorn/nix-config --rebase --delete-branch",
            "gh pr merge 1 --repo fagenorn/nix-config --merge",
            "gh pr merge 1 --merge --repo fagenorn/nix-config --delete-branch",
            "gh pr merge $PR --repo fagenorn/nix-config --merge --delete-branch",
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch | true",
            'gh pr merge 1 --repo fagenorn/nix-config --merge --subject "bad $HOME" --delete-branch',
            'gh pr merge 1 --repo fagenorn/nix-config --merge --subject "bad `id`" --delete-branch',
            'gh pr merge 1 --repo fagenorn/nix-config --merge --subject "bad\\path" --delete-branch',
            'gh pr merge 1 --repo fagenorn/nix-config --merge --subject "bad "quote"" --delete-branch',
            'gh pr merge 1 --repo fagenorn/nix-config --merge --subject "bad\nline" --delete-branch',
        )
        for command in cases:
            with self.subTest(command=command):
                result = self.invoke_command(command)
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)

    def test_merge_dependency_and_predicate_failures_block(self):
        command = (
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch"
        )
        guard_args = (
            "--gh-bin", str(self.fake_gh), "--child-timeout-seconds", "0.5",
        )
        cases = (
            ({"FAKE_PR_MODE": "nonzero"}, "PR lookup"),
            ({"FAKE_PR_MODE": "timeout"}, "PR lookup"),
            ({"FAKE_PR_MODE": "invalid"}, "PR predicate"),
            ({"FAKE_PR_JSON": '{"state":"OPEN","baseRefName":"main","url":"https://github.com/other/repo/pull/1"}'}, "PR predicate"),
            ({"FAKE_PR_JSON": '{"state":"OPEN","baseRefName":"dev","url":"https://github.com/fagenorn/nix-config/pull/1"}'}, "PR predicate"),
            ({"FAKE_PR_JSON": '{"state":"CLOSED","baseRefName":"main","url":"https://github.com/fagenorn/nix-config/pull/1"}'}, "PR predicate"),
            ({"FAKE_PROTECTION_MODE": "nonzero"}, "protection lookup"),
            ({"FAKE_PROTECTION_MODE": "timeout"}, "protection lookup"),
            ({"FAKE_PROTECTION_MODE": "invalid"}, "protection predicate"),
            ({"FAKE_PROTECTION_JSON": '{"required_status_checks":{"contexts":[]},"enforce_admins":{"enabled":true}}'}, "protection predicate"),
            ({"FAKE_PROTECTION_JSON": '{"required_status_checks":{"contexts":["Nix Eval"]},"enforce_admins":{"enabled":false}}'}, "protection predicate"),
        )
        for env, reason in cases:
            with self.subTest(env=env):
                result = self.invoke_command(command, *guard_args, env=env)
                self.assertEqual(2, result.returncode)
                self.assertIn(f"lifecycle guard: {reason}", result.stderr)

    def test_merge_dependency_fixture_can_reach_acceptance(self):
        result = self.invoke_command(
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch",
            "--gh-bin", str(self.fake_gh), "--child-timeout-seconds", "0.5",
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_safe_rendered_subject_can_reach_acceptance(self):
        for subject in ("feature (#30) [guarded]*?~", "git branch -d"):
            with self.subTest(subject=subject):
                result = self.invoke_command(
                    'gh pr merge 1 --repo fagenorn/nix-config --merge '
                    f'--subject "{subject}" --delete-branch',
                    "--gh-bin", str(self.fake_gh), "--child-timeout-seconds", "0.5",
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_unexpected_dependency_exception_blocks(self):
        missing_jq = Path(self.fixture_dir.name) / "missing-jq"
        result = self.invoke_command(
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch",
            "--gh-bin", str(self.fake_gh), "--jq-bin", str(missing_jq),
            "--child-timeout-seconds", "0.5",
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("lifecycle guard: unexpected failure:", result.stderr)


if __name__ == "__main__":
    unittest.main()
