import ast
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest

from agent_tools.claims import forge_land_lock as land_lock
from agent_tools.claims import forge_markers
from agent_tools.delivery import look_marker

from .guard_fake_gh import FAKE_DERIVE_SCRIPT, FAKE_GH_SCRIPT, FAKE_GIT_SCRIPT
from .guard_land_check import write_land_bin, write_land_gh
from .guard_policy_world import GuardPolicyWorld
from .guard_sandbox_git import SandboxGit


SETTINGS_PATH = Path(os.environ["CLAUDE_SETTINGS_PATH"])
BASE_POLICY_PATH = Path(os.environ["CLAUDE_GUARD_BASE_POLICY_PATH"])
NODO = "elevenyellow/nodocom"
# The phrase every refusal by the lifecycle allowlist grammar carries (issue 418).
GRAMMAR = "a lifecycle verb runs only alone"
NODO_ROW = {"default_branch": "main", "integration_branch": "dev", "required_checks": [],
            "evidence": {}}
PROD = "acme/deployer"
PRODUCTION = {
    "changes": [{"id": "deploy", "argv": ["just", "switch"]},
                {"id": "kube-apply", "argv": ["/usr/local/bin/kubectl"]},
                {"id": "deploy-script", "argv": ["./scripts/deploy.sh"]}],
    "read_only": [{"id": "check", "argv": ["just", "build"]},
                  {"id": "kube-read", "argv": ["kubectl", "get"]}],
    "release_profile": "forge-main",
}
PROD_ROW = {"default_branch": "main", "integration_branch": "main", "required_checks": [],
            "evidence": {}, "production": PRODUCTION}
TOOL_PRODUCTION = {**PRODUCTION, "key_files": ["deploy/*.yaml", "ops/runbook.ipynb"],
                   "mcp_tools": ["mcp__deployer__apply"]}
TOOL_ROW = {**PROD_ROW, "production": TOOL_PRODUCTION}
MCP_APPLY = "mcp__deployer__apply"
EDIT_TOOLS = (("Edit", "file_path"), ("Write", "file_path"), ("MultiEdit", "file_path"),
              ("NotebookEdit", "notebook_path"))
ABSENT = object()
EXPECTED_ALLOW = [
    "Bash(git fetch:*)", "Bash(git status:*)", "Bash(git log:*)",
    "Bash(git diff:*)", "Bash(gh pr view:*)", "Bash(gh pr list:*)",
    "Bash(gh pr checks:*)", "Bash(gh issue view:*)", "Bash(gh issue list:*)",
    "Bash(git worktree add:*)", "Bash(git worktree list:*)",
    "Bash(git worktree remove:*)", "Bash(git worktree prune:*)",
    "Bash(git push:*)", "Bash(gh pr create:*)",
    "Bash(git branch -d:*)", "Bash(gh pr merge:*)",
    "Bash(artifact-budget:*)", "Bash(~/.agents/bin/artifact-budget:*)",
    "Bash(forge-issue:*)", "Bash(~/.agents/bin/forge-issue:*)", "Agent",
]

GUARD_SOURCE = Path(__file__).resolve().parents[1] / "home/common/claude-code/lifecycle_guard.py"


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
        guards = [hook for hook in command_hooks if str(hook.get("command", "")).endswith(
            "/bin/claude-bash-lifecycle-guard")]
        if len(command_hooks) != 1 or len(guards) != 1:
            raise AssertionError(f"expected exactly the guard, found {command_hooks!r}")
        command_hook = guards[0]
        if command_hook.get("timeout") != 30:
            raise AssertionError(f"expected hook timeout 30, found {command_hook.get('timeout')!r}")
        if command_hook.get("args", []) != []:
            raise AssertionError(f"registered hook must pass no args: {command_hook.get('args')!r}")
        command = command_hook.get("command")
        if not isinstance(command, str) or " " in command:
            raise AssertionError(f"registered command must be one argument-free path: {command!r}")
        override_flags = ("--git-bin", "--gh-bin", "--jq-bin", "--child-timeout-seconds",
                          "--derive-timeout-seconds")
        if any(flag in command for flag in override_flags):
            raise AssertionError(f"registered command contains a test override: {command!r}")
        cls.guard = Path(command)
        if not cls.guard.is_absolute() or not os.access(cls.guard, os.X_OK):
            raise AssertionError(f"guard is not an executable absolute path: {cls.guard}")

        cls.fixture_dir = tempfile.TemporaryDirectory()
        cls.fake_gh = Path(cls.fixture_dir.name) / "fake-gh"
        cls.fake_gh.write_text(f"#!{sys.executable}\n" + FAKE_GH_SCRIPT, encoding="utf-8")
        cls.fake_gh.chmod(0o755)
        rows_path = Path(cls.fixture_dir.name) / "derive-rows.json"
        rows_path.write_text(json.dumps({NODO: NODO_ROW}), encoding="utf-8")
        cls.fake_derive = Path(cls.fixture_dir.name) / "fake-derive"
        cls.fake_derive.write_text(
            f"#!{sys.executable}\n" + FAKE_DERIVE_SCRIPT.replace("@ROWS@", repr(str(rows_path))),
            encoding="utf-8")
        cls.fake_derive.chmod(0o755)
        # The look check (issue 1138): the source-run judge, standing in for the
        # store script the wrapper names with `--look-bin`.
        cls.look_bin = Path(cls.fixture_dir.name) / "look-bin"
        cls.look_bin.write_text(
            f"#!{sys.executable}\n"
            "import os\nimport sys\n"
            f"os.environ['PYTHONPATH'] = {str(Path(__file__).resolve().parents[1] / 'python')!r}\n"
            "os.execv(sys.executable, [sys.executable, '-m', 'agent_tools.delivery.look_approval',"
            " 'judge', *sys.argv[1:]])\n",
            encoding="utf-8")
        cls.look_bin.chmod(0o755)
        cls.land_bin = write_land_bin(Path(cls.fixture_dir.name), write_land_gh(Path(cls.fixture_dir.name)))
        # The registered wrapper names the store base policy and the compiled policy
        # of this host, which no test may read: every invocation passes the built base
        # policy and a fixture compiled policy (`cls.policy`, one row for Nodo) as later
        # arguments.
        cls.base_policy = json.loads(BASE_POLICY_PATH.read_text(encoding="utf-8"))
        cls.fake_git = Path(cls.fixture_dir.name) / "fake-git"
        cls.fake_git.write_text(
            f"#!{sys.executable}\n"
            + FAKE_GIT_SCRIPT.replace("@GIT@", repr(cls.base_policy["git_bin"])),
            encoding="utf-8")
        cls.fake_git.chmod(0o755)
        cls.policy = cls.write_policy(derived_repositories={NODO: NODO_ROW}, derivation={})

    @classmethod
    def tearDownClass(cls):
        cls.fixture_dir.cleanup()

    @classmethod
    def write_policy(cls, **members):
        """A compiled policy file: no rows and a null derivation, `members` replaced
        (ABSENT removes one)."""
        return cls._write_fixture({"derived_repositories": {}, "derivation": None, **members})

    @classmethod
    def write_base(cls, **members):
        """A base policy file: the built base policy with `members` replaced (ABSENT removes one)."""
        return cls._write_fixture({**cls.base_policy, **members})

    @classmethod
    def _write_fixture(cls, document):
        document = {key: value for key, value in document.items() if value is not ABSENT}
        handle, name = tempfile.mkstemp(dir=cls.fixture_dir.name, suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(document, stream)
        return Path(name)

    def invoke_raw(self, raw, *guard_args, env=None, timeout=5):
        if "--base-policy" not in guard_args:
            guard_args = (*guard_args, "--base-policy", str(BASE_POLICY_PATH))
        if "--policy" not in guard_args:
            guard_args = (*guard_args, "--policy", str(self.policy))
        if "--derive-bin" not in guard_args:
            guard_args = (*guard_args, "--derive-bin", str(self.fake_derive))
        if "--look-bin" not in guard_args:
            guard_args = (*guard_args, "--look-bin", str(self.look_bin))
        if "--land-bin" not in guard_args:
            guard_args = (*guard_args, "--land-bin", str(self.land_bin))
        child_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
        child_env.update(env or {})
        return subprocess.run(
            [self.guard, *guard_args], input=raw, text=True, capture_output=True,
            timeout=timeout, check=False, env=child_env,
        )

    def invoke_command(self, command, *guard_args, env=None):
        return self.invoke_raw(
            json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
            *guard_args, env=env,
        )

    def invoke_command_in(self, command, cwd, *guard_args, env=None):
        return self.invoke_raw(
            json.dumps({
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(cwd),
            }),
            *guard_args, env=env,
        )

    def run_guard(self, command, cwd=None, env=None, guard_args=None, timeout=5):
        """Invoke the guard with the fake `gh` wired in by default."""
        if guard_args is None:
            guard_args = ("--gh-bin", str(self.fake_gh))
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
        if cwd is not None:
            payload["cwd"] = str(cwd)
        return self.invoke_raw(json.dumps(payload), *guard_args, env=env, timeout=timeout)

    def rows_env(self, rows):
        """Env making the stub row check answer from `rows` (slug -> row)."""
        handle, name = tempfile.mkstemp(dir=self.fixture_dir.name, suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(rows, stream)
        return {"FAKE_DERIVE_ROWS": name}

    def assert_row_check_killed(self, pidfile):
        pid = int(pidfile.read_text(encoding="utf-8"))
        give_up = time.monotonic() + 5
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            if time.monotonic() > give_up:
                self.fail(f"row-check grandchild {pid} outlived the verdict")
            time.sleep(0.1)

    def make_repo(self, origin, default_branch="main"):
        """A throwaway git repo whose origin remote is `origin`.

        `default_branch` becomes origin/HEAD, which is what the guard reads to
        learn the integration branch; pass None to leave it unresolvable.
        """
        root = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        argv_list = [
            ["git", "init", "--quiet"],
            ["git", "remote", "add", "origin", origin],
        ]
        if default_branch is not None:
            argv_list.append([
                "git", "symbolic-ref", "refs/remotes/origin/HEAD",
                f"refs/remotes/origin/{default_branch}",
            ])
        for argv in argv_list:
            subprocess.run(argv, cwd=root, check=True, capture_output=True)
        return root

    def test_generated_allow_surface_is_exact_and_ordered(self):
        self.assertEqual(EXPECTED_ALLOW, self.settings["permissions"]["allow"])

    def test_the_guard_is_registered_for_bash_file_edits_and_mcp_tools(self):
        def matches(matcher, name):
            # Claude Code's documented matcher rule (hooks.md, "Matcher patterns").
            if re.fullmatch(r"[A-Za-z0-9_\- ,|]*", matcher):
                return name in {part.strip() for part in re.split(r"[|,]", matcher)}
            return re.search(matcher, name) is not None

        entries = self.settings["hooks"]["PreToolUse"]
        self.assertEqual(
            ["Bash", "Edit|Write|MultiEdit|NotebookEdit", "^mcp__"],
            [entry["matcher"] for entry in entries],
        )
        for entry in entries:
            self.assertEqual(
                [{"type": "command", "command": str(self.guard), "timeout": 30}],
                entry["hooks"],
            )
        edits = entries[1]["matcher"]
        self.assertEqual(
            {"Edit", "Write", "MultiEdit", "NotebookEdit"},
            {
                name
                for name in (
                    "Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "Bash", "Edits",
                )
                if matches(edits, name)
            },
        )
        mcp = entries[2]["matcher"]
        for name in ("mcp__deployer__apply", "mcp__plugin_x_y__z"):
            self.assertTrue(matches(mcp, name), name)
        for name in ("Read", "Bash", "xmcp__a__b"):
            self.assertFalse(matches(mcp, name), name)

    def test_bash_timeout_ceiling_is_raised_and_the_default_left_alone(self):
        # #261 D2: an explicit foreground timeout must be able to cover the
        # longest verification command; the 120 s default stays the host's.
        env = self.settings.get("env", {})
        self.assertEqual(env.get("BASH_MAX_TIMEOUT_MS"), "3600000")
        self.assertGreaterEqual(int(env["BASH_MAX_TIMEOUT_MS"]), 30 * 60 * 1000)
        self.assertNotIn("BASH_DEFAULT_TIMEOUT_MS", env)
        self.assertEqual(env.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"), "1")

    def test_unrelated_bash_and_exact_branch_delete_pass(self):
        for command in ("git status --short", "git branch -d issue-30-safe"):
            with self.subTest(command=command):
                result = self.invoke_command(command)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_single_command_lifecycle_calls_pass_the_guard(self):
        for command in (
            "artifact-budget validate-report --boundary producer --input - <<'JSON'\n{}\nJSON",
            "forge-issue create --repo octo/widgets --title Wire --body-file /tmp/body.md "
            "--blocked-by 555 --blocks 689",
        ):
            with self.subTest(command=command.split()[0]):
                result = self.invoke_command(command)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_malformed_hook_input_fails_closed(self):
        cases = (
            "not-json", "[]", "{}",
            json.dumps({"tool_name": "Read", "tool_input": {"command": "git branch -d x"}}),
            json.dumps({"tool_name": "Bash", "tool_input": {"command": 3}}),
            json.dumps({"tool_name": "Edit", "tool_input": {}}),
            json.dumps({"tool_name": "Write", "tool_input": {"file_path": 3}}),
            json.dumps({"tool_name": "Edit", "tool_input": {"file_path": ""}}),
            json.dumps({"tool_name": "NotebookEdit", "tool_input": {"file_path": "/x.ipynb"}}),
            json.dumps({"tool_name": "MultiEdit", "tool_input": "x"}),
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

    def test_heredoc_and_quoted_mentions_pass_in_own_repo(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "cat > notes.md <<'EOF'\nrun gh pr merge 5 later\ngit push origin main\nEOF\n",
            'echo "docs say gh pr create --repo x"',
            "true # gh pr merge 9 --repo fagenorn/nix-config --merge --delete-branch",
            "artifact-budget check --kind handoff --root 'blocked, cannot gh pr merge yet' --format json",
            "rg -n 'git branch -d' docs/",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_a_label_addition_gets_no_special_treatment(self):
        retired = "-".join(("instruction", "budget", "raise"))
        elsewhere = self.make_repo("https://github.com/someoneelse/tool.git")
        for label in ("bug", retired, retired.upper()):
            for command in (
                f"gh pr edit 1 --add-label {label}",
                f"gh issue edit 23 --add-label={label}",
                f"gh pr edit 1 --add-label 'bug,{label}'",
                f"x=$(gh pr edit 1 --add-label {label})",
                f"gh pr edit $(gh pr view --json number | jq -r .number) --add-label {label}",
                f"sh -c 'gh pr edit 1 --add-label {label}'",
                f'result="$(gh pr edit 1 --add-label {label})"',
            ):
                with self.subTest(command=command):
                    result = self.run_guard(command)
                    self.assertEqual(0, result.returncode, (command, result.stderr))
                    self.assertNotIn("label edit", result.stderr)
        result = self.invoke_command_in(f"gh pr edit 1 --add-label {retired}", elsewhere)
        self.assertEqual(0, result.returncode, result.stderr)

    # ------------------------------------------------------------------
    # Adversarial table. Each case is one class of "the guard's parser and
    # the shell disagree". Every command below really runs a guarded verb, so
    # none of them may exit 0 unless its grammar legitimately passes.
    # ------------------------------------------------------------------

    def test_heredoc_declared_before_a_separator_guards_the_rest_of_the_line(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            ": <<EOF; git push --force origin main\nEOF\n",
            ": <<EOF && git push --force origin main\nEOF\n",
            ": <<EOF | git push --force origin main\nEOF\n",
            "cat <<EOF; gh pr merge 107 --repo someoneelse/tool --merge --delete-branch\nEOF\n",
            ": <<EOF; git branch -d main\nEOF\n",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, (command, result.stdout))
        # The body itself is still inert: here the verb is genuinely inside it.
        inert = self.run_guard(
            "cat <<EOF; true\ngit push --force origin main\nEOF\n", cwd=repo)
        self.assertEqual(0, inert.returncode, inert.stderr)

    def test_unnormalisable_heredoc_delimiter_fails_closed(self):
        # Issue 651: bash reads `<<$'EOF'` (and `<<$"EOF"`) as ending at the line
        # `EOF`, while a guard that keeps the `$` waits for `$EOF` and so would skip
        # every line in between unjudged. Any delimiter the guard cannot normalise
        # exactly as the shell does makes the whole command unparseable: a lifecycle
        # verb or a detaching word anywhere in its raw text is refused.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        there = self.make_repo("git@github.com:fagenorn/nix-config.git")
        create = ("gh pr create --repo fagenorn/nix-config --base main --head topic "
                  "--title t --body b")
        openers = ("cat <<$'EOF'", 'cat <<$"EOF"', "cat <<-$'EOF'")
        for opener in openers:
            for operation, line in (
                ("push", "git push origin topic"),
                ("PR creation", create),
                ("push", f"cd {there} && git push origin topic"),
            ):
                # The shell ends the body at `EOF` and runs `line`; a guard reading
                # the delimiter as `$EOF` would skip to the last line.
                command = f"{opener}\nbody\nEOF\n{line}\n$EOF\n"
                with self.subTest(command=command):
                    result = self.run_guard(command, cwd=repo)
                    self.assertEqual(2, result.returncode, (command, result.stderr))
                    self.assertIn(f"lifecycle guard: unsafe {operation}:", result.stderr)
                    self.assertIn(GRAMMAR, result.stderr)
            command = f"{opener}\nbody\nEOF\nnohup sleep 9 &\n$EOF\n"
            with self.subTest(command=command):
                self.assert_detaching_refusal(self.run_guard(command), "nohup", command)
        # Mixed quoting, escapes and a bare `$` are not normalised either (D3).
        for opener in ("cat <<\\EOF", "cat <<E'OF'", "cat <<'E'\"OF\"", "cat <<\"E\"OF",
                       'cat <<"E\\OF"', "cat <<$EOF", "cat <<E`x`OF"):
            command = f"{opener}\nbody\nEOF\ngit push origin topic\n"
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn("lifecycle guard: unsafe push:", result.stderr)
        # Fail closed (D2): a verb genuinely inside such a body is refused too.
        command = "cat <<$'EOF'\ngit push origin topic\nEOF\n"
        result = self.run_guard(command, cwd=repo)
        self.assertEqual(2, result.returncode, (command, result.stderr))
        self.assertIn("lifecycle guard: unsafe push:", result.stderr)
        # With no verb, label or detaching word the command still passes.
        for command in ("cat <<$'EOF'\nhello\nEOF\n", "cat <<\\EOF\nhello\nEOF\n"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        # The normalisable spellings keep their inert plain-text bodies.
        for opener in ("cat <<EOF", "cat <<'EOF'", 'cat <<"EOF"', "cat <<-EOF", "cat << 'EOF'"):
            command = f"{opener}\ngit push origin topic\nEOF\n"
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_expanding_heredoc_body_fails_closed(self):
        # Issue 651 (D6): under a bare-word delimiter the shell runs `$(…)` and
        # backtick substitutions in the body and joins a backslash-newline before
        # matching the closing line, so such a body is not inert. A body holding
        # `$`, a backtick or a backslash there makes the command unparseable.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "cat <<EOF\n$(git push --force origin main)\nEOF\n",
            "cat <<EOF\n`git push --force origin main`\nEOF\n",
            "cat <<-EOF\n\t$(git push --force origin main)\n\tEOF\n",
            "cat << EOF\nx ${y:-$(git push --force origin main)}\nEOF\n",
            # bash joins `EO\` + `F` into the closing line `EOF` and runs the push;
            # a guard matching raw lines would skip to the last `EOF`.
            "cat <<EOF\nEO\\\nF\ngit push --force origin main\nEOF\n",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn("lifecycle guard: unsafe push:", result.stderr)
        command = "cat <<EOF\n$(nohup sleep 9 &)\nEOF\n"
        self.assert_detaching_refusal(self.run_guard(command), "nohup", command)
        # A quoted delimiter expands nothing: the same bodies stay inert.
        for opener in ("cat <<'EOF'", 'cat <<"EOF"'):
            for body in ("$(git push --force origin main)",
                         "`git push --force origin main`"):
                command = f"{opener}\n{body}\nEOF\n"
                with self.subTest(command=command):
                    result = self.run_guard(command, cwd=repo)
                    self.assertEqual(0, result.returncode, (command, result.stderr))
        # An expanding body with no verb, label or detaching word still passes.
        for command in ("cat <<EOF\n$HOME and `date`\nEOF\n", "cat <<EOF\na\\\nb\nEOF\n"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_namespaced_ref_spellings_of_the_default_branch_block(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "git push origin refs/heads/main",
            "git push -u origin refs/heads/main",
            "git push origin heads/main",
            "git push origin remotes/origin/main",
            "git push origin tags/v1",
            "git push origin HEAD",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn("lifecycle guard: unsafe push:", result.stderr)
        ok = self.run_guard("git push -u origin issue-101-topic", cwd=repo)
        self.assertEqual(0, ok.returncode, ok.stderr)

    def test_shell_equivalent_spellings_are_adjudicated(self):
        # Every command here pushes the default branch, so a legitimate pass is
        # impossible: exit 0 would mean the guard simply failed to see the verb.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "(git push origin main)",                             # subshell
            "{ git push origin main; }",                          # group
            "if true; then git push origin main; fi",             # then
            "for x in a; do git push origin main; done",          # do
            "while true; do git push origin main; done",          # while/do
            "case x in a) git push origin main;; esac",           # case arm
            "! git push origin main",                             # negation
            "time git push origin main",                          # time keyword
            "git  push origin main",                              # double space
            "git\tpush origin main",                              # tab
            '"git" push origin main',                             # quoted word
            "x=$(git push origin main)",                          # substitution
            "`git push origin main`",                             # backticks
            "xargs git push origin main",                         # argv runner
            "timeout 5 git push origin main",                     # argv runner
            "nice git push origin main",                          # argv runner
            "env -i git push origin main",                        # env options
            "env FOO=bar git push origin main",                   # env assignment
            "sudo -u anis git push origin main",                  # sudo options
            "eval 'git push origin main'",                        # evaluator
            "sh -c 'git push origin main'",                       # evaluator
            "bash -c 'gh pr merge 1 --repo someoneelse/tool --merge --delete-branch'",
            'echo "unterminated ; git push origin main',           # unparseable
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)

    def test_other_label_edits_and_mentions_pass(self):
        for command in (
            "gh pr edit 1 --add-label bug",
            'gh issue edit 23 34 --add-label "bug,help wanted"',
            "xargs gh pr edit 1 --add-label bug",
            "sh -c 'gh pr edit 1 --add-label bug'",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def assert_detaching_refusal(self, result, word, command):
        self.assertEqual(2, result.returncode, (command, result.stderr))
        self.assertIn(
            f"lifecycle guard: detaching command `{word}` refused:", result.stderr,
            command,
        )
        self.assertIn("run_in_background", result.stderr, command)
        self.assertNotIn("launch-" "scope", result.stderr, command)

    def test_detaching_words_are_refused_globally(self):
        # Every form below makes the shell run a detaching word (or hands it to
        # source the guard cannot parse), so exit 0 means the guard missed it.
        # No cwd: the refusal is global and needs no repository.
        templates = (
            "W x", "W x &", "(W x)", "{ W x; }", "`W x`", "y=$(W x)", "$(W)",
            "case a in a) W x;; esac", "! W x", "time W x",
            "if true; then W x; fi", "for i in a; do W x; done",
            "true && W x", "x & W", '"W" x', "/usr/bin/W x",
            "command W x", "builtin W x", "exec W x", "env W x", "env -i W x",
            "env FOO=bar W x", "sudo W x", "sudo -E W x",
            "eval 'W x'", "sh -c 'W x'", 'bash -c "W x"', "zsh -c 'W x'",
            "dash -c 'W x'", "ksh -c 'W x'", "/bin/sh -c 'W x &'",   # per D6
            'echo "$(W x &)"', 'echo "`W x`"',                     # per D3
            'echo "unterminated ; W x',                              # unparseable
            ">log 2>&1 W x &", "2>&1 W x", "</dev/null W x", "> log W x",
            ">> log 2>&1 W x", "&>log W x", "FOO=bar >log W x",       # redirections
            "sudo -u anis W x", "sudo -g wheel W x", "sudo -u anis -E W x",
            "exec -a foo W x", "env -u FOO W x", "env -C /tmp W x",
            "env -S -i W x", "sudo -E -u anis env -u FOO W x",         # option args
            "W>/dev/null sleep 60 &", "W</dev/null x", "W>&2", "W>log x",
            "W>>log x", "sudo>/dev/null W x", "sudo -u >log anis W x",  # attached
            "env -u || W x", "sudo -u; W x", "exec -a && W x",          # separators
            "env -u FOO 2>&1 W x",
            "env -S 'W x'", "env --split-string='W x'", 'env -S"W x"',
            "env --split-string 'W x'", "env -iS 'W x'",                # split-string
            "X='>' W x &", "exec -a 'worker>' W x", "X=1> out W x",
            "X='>' sh -c 'W x'", "sudo -u 'a>' W x",                    # quoted `>`
        )
        for word in ("nohup", "setsid", "disown"):
            for template in templates:
                command = template.replace("W", word)
                with self.subTest(command=command):
                    self.assert_detaching_refusal(
                        self.run_guard(command), word, command)
        # The issue's AC1 forms verbatim, and the deliberate over-refusal of D3.
        for command, word in (
            ("nohup x &", "nohup"), ("(setsid x)", "setsid"),
            ("env nohup x", "nohup"), ("$(disown)", "disown"),
            ("sh -c 'nohup x'", "nohup"), ("x & disown", "disown"),
            ("sh -c 'cat nohup.out'", "nohup"),
            ("sh -c 'setsid a; nohup b'", "setsid"),               # earliest, per D6
        ):
            with self.subTest(command=command):
                self.assert_detaching_refusal(self.run_guard(command), word, command)

    def test_glued_operator_forms_hide_no_detaching_word(self):
        """Issue 656: a quoted operator glued to an unquoted one after a wrapper
        option (`env -u '>'>/dev/null nohup x`) hid the command word from the
        token scan, while bash and zsh run it. The raw-text check refuses them
        without reading shell syntax."""
        for word in ("nohup", "setsid", "disown"):
            for template in (
                "env -u '>'>/dev/null W x", "sudo -u '>'>/dev/null W x",
                "env -u '<'</dev/null W", "sudo -u '<'</dev/null W",
                "env -u '>'>>log W x &", 'env -u "<"</dev/null W x',
                "sudo -u '>'>/dev/null env -u '<'</dev/null W x",
            ):
                command = template.replace("W", word)
                with self.subTest(command=command):
                    self.assert_detaching_refusal(self.run_guard(command), word, command)

    def test_a_detaching_word_anywhere_in_the_raw_text_is_refused(self):
        """Issue 656 (D2, D3, D5): the check reads text, not shell syntax. A whole
        word, in any case, is refused wherever it stands, and so is one rebuilt by
        the deletion copy. The earliest hit in the raw text is named."""
        for command, word in (
            # Mentions the token scan let through, refused now (D5).
            ('echo "nohup"', "nohup"),
            ('echo "run nohup x & later"', "nohup"),
            ("cat > notes.md <<'EOF'\nnohup x &\nsetsid y\ndisown\nEOF\n", "nohup"),
            ("cat <<'EOF'\n$(nohup sleep 9 &)\nEOF\n", "nohup"),
            ("true # nohup x & disown", "nohup"),
            ("make > nohup.out 2>&1", "nohup"),
            ("tail -f nohup.out", "nohup"),
            ("sudo -u anis ls nohup.out", "nohup"),
            ("sudo -u >log anis ls nohup", "nohup"),
            ("make 2>&1 >nohup.out", "nohup"),
            ("ls >nohup.out", "nohup"),
            ("X=> nohup.out echo hi", "nohup"),
            ("env -u '>' echo nohup.out", "nohup"),
            ("git commit -m 'refuse nohup'", "nohup"),
            # Argv runners, an accepted residual of the token scan (D5).
            ("xargs nohup x", "nohup"),
            ("timeout 5 setsid x", "setsid"),
            ("find . -exec disown {} +", "disown"),
            # Rebuilt by the deletion copy (D3).
            ("no''hup sleep 9 &", "nohup"),
            ('se"t"sid x', "setsid"),
            ("dis\\own", "disown"),
            ("n\\ohup x", "nohup"),
            ("no\\\nhup x", "nohup"),
            ("$'nohup' x", "nohup"),
            ("no$''hup sleep 999 &", "nohup"),
            ('no$""hup x', "nohup"),
            ("no{,}hup x", "nohup"),
            ("{no,}hup x", "nohup"),
            ("no{h,}up x", "nohup"),
            ("set{,}sid x", "setsid"),
            # An attached option value a program runs (D2: `c` or `s` before).
            ("env -Snohup\\ x", "nohup"),
            ("env -iSsetsid", "setsid"),
            ("su -cdisown", "disown"),
            # Any case (D2): a case-insensitive file system runs /usr/bin/NOHUP.
            ("NOHUP x &", "nohup"),
            ("/usr/bin/SetSid x", "setsid"),
            ("Disown", "disown"),
            # ASCII bounds (D2): a Unicode case fold is not a letter.
            ("echo nohup\u0130", "nohup"),
            ("echo \u212anohup", "nohup"),
            # Raw text: a quote beside the word bounds it, though the shell would
            # glue the two (`anohup`); refusing it costs nothing.
            ("echo 'a'nohup", "nohup"),
            # Punctuation other than `-` bounds a word.
            ("echo x=setsid", "setsid"),
            ("ls dir/nohup.d", "nohup"),
            # A default-value expansion expands to the literal word when its
            # variable is unset, though a `-` stands before the word.
            ("${x:-nohup} sleep 999 &", "nohup"),
            ("${x-nohup} sleep 999 &", "nohup"),
            ("${1:-setsid} x", "setsid"),
            ("${x:-${y-disown}}", "disown"),
            # The variable may be a special parameter or carry a subscript, and
            # the default word may be rebuilt by quotes, a backslash or braces.
            ("${@:-nohup} sleep 999 &", "nohup"),
            ("${*-nohup} sleep 999 &", "nohup"),
            ("${a[0]:-nohup} sleep 999 &", "nohup"),
            ("unset a; ${a[0]:-nohup} sleep 60 &", "nohup"),
            ("${x:-no''hup} sleep 999 &", "nohup"),
            ("${x-no\\hup} sleep 999 &", "nohup"),
            ("${x:-no{,}hup} sleep 999 &", "nohup"),
            ("${a[i-1]:-nohup} sleep 999 &", "nohup"),
            ("${x:-no$''hup} sleep 999 &", "nohup"),
            # ...including before its first letter.
            ("${x:-'n'ohup} sleep 999 &", "nohup"),
            ("${x:-\"n\"ohup} sleep 999 &", "nohup"),
            ("${x:-\\no\\hup} sleep 999 &", "nohup"),
            ("${x:-''n''ohup} sleep 999 &", "nohup"),
            ("${@:-'n'ohup} sleep 999 &", "nohup"),
            ("${x:-'s'etsid} sleep 999 &", "setsid"),
            ("${x:-\"d\"isown}", "disown"),
            ("${x:-$\"n\"ohup} sleep 999 &", "nohup"),
            ("unset a; ${a[0]:-'n'ohup} sleep 60 &", "nohup"),
            ("${x:-no\\\nhup} sleep 999 &", "nohup"),
            ("no\\\nhup sleep 999 &", "nohup"),
            # A positional or empty special parameter glued before the word
            # expands to nothing in the Bash tool.
            ("$1nohup sleep 999 &", "nohup"),
            ("$@setsid x", "setsid"),
            ("$!disown", "disown"),
            # The earliest hit is named.
            ("echo setsid; nohup x", "setsid"),
            ("echo DISOWN nohup", "disown"),
        ):
            with self.subTest(command=command):
                self.assert_detaching_refusal(self.run_guard(command), word, command)

    def test_text_without_a_whole_detaching_word_passes(self):
        """Issue 656 (D2): a word only counts when no ASCII letter, digit, `_` or
        `-` touches it (a `c` or `s` before excepted), so these hold none, and a
        trailing `&` is not detaching."""
        for command in (
            "a & b & wait",
            "sleep 1 &",
            "ls nohupx",
            "echo my_setsid_helper",
            "cat disown2.txt",
            "echo unohup",
            "echo no hup",
            "echo SETSIDE",
            "echo Knohup",
            "ls my-nohup",
            "echo issue-7-refuse-nohup-x",
            "echo nohup-",
            "echo ${x:-my-nohup}",
            "echo ${x}-nohup-y",
            "echo $12nohup",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_slugged_lifecycle_names_pass(self):
        """Issue 656 (D2, D5): branch and worktree names are slugged from issue
        titles with `-`, so a title naming a detaching word must not make its
        branch's push, deletion or worktree calls detaching."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        worktree = "/tmp/x/.worktrees/worktree-issue-700-detect-nohup-assembled-at-run-time"
        for command in (
            "git push -u origin issue-700-detect-nohup-assembled-at-run-time",
            "git push origin issue-701-refuse-setsid-and-disown",
            "git branch -d issue-702-refuse-nohup",
            f"git -C {worktree} status --short",
            f"cd {worktree} && git status --short",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_read_only_mentions_of_a_detaching_word_pass(self):
        """Issue 656 allowlist (D4): the word is admitted only as the search pattern
        of one plain grep or rg call whose options are all enumerated, or inside a
        quoted title or body of one gh issue/pr create/comment call (after the
        sanctioned scrub prelude or none), read in the issue-418 word grammar."""
        for command in (
            "grep nohup log",
            "grep -n -e nohup -e setsid home/common/claude-code/README.md",
            "grep -rn --include '*.md' disown docs",
            "grep --exclude-dir=.git -rn setsid home",
            "rg -n 'setsid|disown' docs/",
            "rg -n -g '*.md' nohup docs/",
            "rg --regexp=nohup -t py .",
            "rg -- nohup docs",
            'rg -i "NOHUP" tests',
            "gh issue comment 656 --repo fagenorn/nix-config "
            "--body 'never nohup; use run_in_background'",
            "gh issue create --repo fagenorn/nix-config --title 'setsid refusal' "
            '--body "disown is refused too"',
            "gh pr comment 657 --repo fagenorn/nix-config -b 'nohup'",
            "gh issue create --repo fagenorn/nix-config -t 'nohup' "
            "-b 'first line\nsetsid on the second'",
            "unset GITHUB_TOKEN && gh issue comment 700 --repo fagenorn/nix-config "
            "--body 'nohup refusal notes'",
            "unset GITHUB_TOKEN GH_TOKEN && gh issue create --repo fagenorn/nix-config "
            "--title 'detect setsid assembled at run time' --body 'disown too'",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        # A PR creation holding the word in its quoted text, with a slugged head
        # and with or without the scrub, is admitted outright: it
        # clears the detaching check and the lifecycle grammar.
        repo = self.make_repo("https://github.com/fagenorn/argus.git")
        create = ('gh pr create --repo fagenorn/argus --base main '
                  '--head issue-700-refuse-nohup '
                  '--title "fix: refuse nohup" --body "setsid and disown too"')
        draft = create.replace("--repo fagenorn/argus", "--repo fagenorn/argus --draft")
        for command in (create, "unset GITHUB_TOKEN && " + create,
                        draft, "unset GITHUB_TOKEN && " + draft):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_detaching_mentions_outside_the_allowlist_are_refused(self):
        """Issue 656 allowlist (D4): near misses of the two admitted forms."""
        for command, word in (
            ("grep nohup log; nohup x", "nohup"),
            ("grep nohup log && nohup x", "nohup"),
            ("grep nohup log | sh", "nohup"),
            ("grep nohup $(setsid x)", "nohup"),
            ("grep x nohup.out", "nohup"),              # a path, not the pattern
            ("grep -e x nohup", "nohup"),               # a path once -e names the pattern
            ("rg -e x nohup", "nohup"),
            ("grep -A nohup x log", "nohup"),           # an option's value
            ("grep --include=nohup x .", "nohup"),
            ("grep -f patterns nohup", "nohup"),        # patterns from a file
            ("grep --file=patterns nohup", "nohup"),
            ("grep -rf patterns nohup", "nohup"),       # a cluster with an unlisted letter
            ("grep -esnohup log", "nohup"),             # attached -e is not enumerated
            ("rg --files nohup", "nohup"),              # no pattern at all
            ("rg --type-list nohup", "nohup"),
            ("rg -r nohup x .", "nohup"),               # a replacement, not a pattern
            ("rg -z nohup x", "nohup"),                 # rg runs decompressors
            ("grep -e nohup -A", "nohup"),              # a value option missing its value
            ("grep 'no''hup' log", "nohup"),            # glued quotes leave the grammar
            ("rg --pre nohup x .", "nohup"),            # rg runs --pre's value
            ("rg --pre=nohup x .", "nohup"),
            ("rg --hostname-bin=setsid x", "setsid"),
            ("rg --pre-glob '*' --pre=disown x", "disown"),
            ("FOO=1 grep nohup log", "nohup"),
            ("command grep nohup log", "nohup"),
            ("/usr/bin/grep nohup log", "nohup"),
            ("egrep nohup log", "nohup"),
            ("'grep' nohup log", "nohup"),              # the program word must be plain
            ("unset GITHUB_TOKEN && grep nohup log", "nohup"),  # no prelude for search
            ("gh issue comment 1 --body nohup", "nohup"),           # unquoted text
            ("gh issue comment 1 -- --body 'nohup'", "nohup"),      # options ended
            ("gh issue comment 1 --body='nohup'", "nohup"),         # not enumerated
            ("gh issue comment 1 --repo 'nohup/x' --body b", "nohup"),
            ("gh issue comment 1 --body 'x' --edit-last 'nohup'", "nohup"),
            ("gh issue edit 1 --body 'nohup'", "nohup"),
            ("gh issue comment 1 --body-file nohup.md", "nohup"),
            ("gh issue comment 1 --body 'x'; nohup y", "nohup"),
            ('gh issue comment 1 --body "$(nohup x)"', "nohup"),
            ("gh api repos/x/issues -f body='nohup'", "nohup"),
            ("unset PATH && gh issue comment 1 --body 'nohup'", "nohup"),
            ("unset GITHUB_TOKEN GITHUB_TOKEN && gh issue comment 1 --body 'nohup'", "nohup"),
            ("env -u GITHUB_TOKEN gh issue comment 1 --body 'nohup'", "nohup"),
            ("cd /tmp && gh issue comment 1 --body 'nohup'", "nohup"),
            ("unset GITHUB_TOKEN && gh issue comment 1 --body 'x' && nohup y", "nohup"),
            ("echo 'nohup'", "nohup"),
        ):
            with self.subTest(command=command):
                self.assert_detaching_refusal(self.run_guard(command), word, command)

    def test_mutants_of_the_detaching_check_are_caught(self):
        """Issue 656 mutation check (D8): each seam of the raw-text check, broken in
        a copy of the guard source, gives at least one row a different valid
        outcome (an admission, or a detaching refusal), while the unmutated copy
        gives every row its expected one. A crash or another refusal never counts.
        The copy runs as the wrapper runs the guard; no row holds a
        repository-bound verb, so the compiled policy is never opened."""
        source = (Path(__file__).resolve().parents[1]
                  / "home/common/claude-code/lifecycle_guard.py").read_text(encoding="utf-8")
        anchor = '\nif __name__ == "__main__":'
        self.assertEqual(1, source.count(anchor))
        rows = (
            ("nohup x", "refuse"),
            ("echo 'a'nohup", "refuse"),
            ("no''hup x", "refuse"),
            ("no$''hup x", "refuse"),
            ("no{,}hup x", "refuse"),
            ("NOHUP x", "refuse"),
            ("echo \u212anohup", "refuse"),
            ("env -Snohup\\ x", "refuse"),
            ("su -cnohup x", "refuse"),
            ("echo nohup", "refuse"),
            ("echo issue-7-refuse-nohup-x", "admit"),
            ("grep nohup log", "admit"),
            ("unset GITHUB_TOKEN && gh issue comment 1 --repo fagenorn/nix-config "
             "--body 'nohup'", "admit"),
            ("sleep 1 &", "admit"),
            ("${x:-nohup} y", "refuse"),
            ("${a[0]:-no''hup} y", "refuse"),
            ("${x:-'n'ohup} y", "refuse"),
            ("$1nohup y", "refuse"),
            ("no\\\nhup y", "refuse"),
            ("echo ${x}-nohup", "admit"),
        )
        flags = "re.IGNORECASE | re.ASCII"
        mutants = {
            "control": "",
            "no-normalisation": "detaching_normalised = lambda command: command\n",
            "no-dollar-quote-deletion":
                "DETACHING_DELETED = re.compile(DETACHING_DELETED.pattern.split('|', 1)[1])\n",
            "no-brace-deletion":
                "DETACHING_DELETED = re.compile("
                "DETACHING_DELETED.pattern.replace('{},', ''))\n",
            "normalised-text-only":
                "detaching_texts = lambda command: (detaching_normalised(command),)\n",
            "case-sensitive":
                "DETACHING_PATTERN = re.compile(DETACHING_PATTERN.pattern, re.ASCII)\n",
            "unicode-bounds":
                "DETACHING_PATTERN = re.compile(DETACHING_PATTERN.pattern, re.IGNORECASE)\n",
            "dash-bounds-a-word":
                "DETACHING_PATTERN = re.compile("
                f"DETACHING_PATTERN.pattern.replace('_-]', '_]'), {flags})\n",
            "no-attached-option-bound":
                "DETACHING_PATTERN = re.compile("
                f"DETACHING_PATTERN.pattern.replace('|(?<=[cs])', ''), {flags})\n",
            "no-default-pattern":
                "DETACHING_DEFAULT_PATTERN = re.compile(r'(?!)')\n",
            "no-default-word-rebuild":
                "DETACHING_DEFAULT_PATTERN = re.compile(r'\\$\\{[A-Za-z0-9_]*:?-(' "
                "+ '|'.join(DETACHING_WORDS) + r')(?![A-Za-z0-9_-])', "
                f"{flags})\n",
            "no-default-leading-junk":
                "DETACHING_DEFAULT_PATTERN = re.compile("
                "DETACHING_DEFAULT_PATTERN.pattern.replace(':?-(' + DETACHING_JUNK, ':?-(', 1), "
                f"{flags})\n",
            "no-positional-bound":
                "DETACHING_PATTERN = re.compile("
                f"DETACHING_PATTERN.pattern.replace('|(?<=\\\\$[0-9!@*])', ''), {flags})\n",
            "no-backslash-newline-deletion":
                "detaching_normalised = lambda command: "
                "DETACHING_DELETED.sub('', command)\n",
            "allow-every-mention": "detaching_mention_allowed = lambda command: True\n",
            "allow-no-mention": "detaching_mention_allowed = lambda command: False\n",
        }

        def outcome(result):
            if result.returncode == 0:
                return "admit"
            if (result.returncode == 2
                    and "lifecycle guard: detaching command `" in result.stderr):
                return "refuse"
            return f"invalid: exit {result.returncode}: {result.stderr[-300:]}"

        directory = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        expected = [want for _, want in rows]
        for name, override in mutants.items():
            path = directory / f"{name}.py"
            path.write_text(source.replace(anchor, "\n" + override + anchor, 1),
                            encoding="utf-8")
            outcomes = []
            for command, _ in rows:
                result = subprocess.run(
                    [sys.executable, "-I", str(path),
                     "--base-policy", str(BASE_POLICY_PATH),
                     "--policy", str(directory / "absent-policy.json"),
                     "--derive-bin", "/usr/bin/false"],
                    input=json.dumps({"tool_name": "Bash",
                                      "tool_input": {"command": command}}),
                    text=True, capture_output=True, timeout=10, check=False,
                )
                outcomes.append(outcome(result))
            with self.subTest(mutant=name):
                if name == "control":
                    self.assertEqual(expected, outcomes)
                else:
                    caught = [
                        command for (command, want), got in zip(rows, outcomes)
                        if got in ("admit", "refuse") and got != want
                    ]
                    self.assertTrue(caught, (name, list(zip(expected, outcomes))))

    def test_mutants_of_the_transmit_and_push_url_checks_are_caught(self):
        """Issue 655 AC5: each seam of the transmit recognition, the command-option
        and assignment checks and the push URL check (each lookup-failure branch
        included), broken in a copy of the guard source, gives at least one row a
        different valid outcome (an admission, or an `unsafe push:` refusal), while
        the unmutated copy gives every row its expected one. A crash or another
        refusal never counts."""
        source = GUARD_SOURCE.read_text(encoding="utf-8")
        anchor = '\nif __name__ == "__main__":'
        self.assertEqual(1, source.count(anchor))
        topic = "issue-655-topic"
        force = "git push --force origin main"
        other = "git@github.com:fagenorn/guard-elsewhere.git"
        repos = {
            None: None,
            "plain": self.push_url_repo(),
            "pushurl": self.push_url_repo(("remote.origin.pushurl", other)),
            "pushInsteadOf": self.push_url_repo(
                ("url.git@github.com:someoneelse/.pushInsteadOf", "git@github.com:fagenorn/")),
            "second pushurl": self.push_url_repo(
                ("remote.origin.pushurl", "git@github.com:fagenorn/nix-config.git"),
                ("remote.origin.pushurl", other)),
        }
        # (command, repository, FAKE_PUSH_URL_MODE or None, expected outcome)
        rows = (
            ("git -c core.pager=cat diff", None, None, "refuse"),
            (f"git p origin {topic}", None, None, "refuse"),
            (f"git send-pack git@github.com:fagenorn/nix-config.git {topic}", None, None,
             "refuse"),
            (f"git subtree push --prefix=x origin {topic}", None, None, "refuse"),
            (f"git-push origin {topic}", None, None, "refuse"),
            (f"git $(printf p) origin {topic}", None, None, "refuse"),
            (f"git add`echo -x` origin {topic}", None, None, "refuse"),
            (f"xargs git p origin {topic}", None, None, "refuse"),
            (f"timeout 5 git p origin {topic}", None, None, "refuse"),
            (f"sh -c 'git p origin {topic}'", None, None, "refuse"),
            ("git rebase --exec true HEAD~1", None, None, "refuse"),
            (f"=git p origin {topic}", None, None, "refuse"),
            (f"hash g=/usr/bin/git; g p origin {topic}", None, None, "refuse"),
            (f"echo p origin {topic} | xargs git", None, None, "refuse"),
            (f"$(echo git) p origin {topic}", None, None, "refuse"),
            (f'"$(which git)" p origin {topic}', None, None, "refuse"),
            (f"echo p origin {topic} | {{ true; xargs git; }}", None, None, "refuse"),
            ("{ xargs git; } <<< 'push --force origin main'", None, None, "refuse"),
            (f"echo p origin {topic} |\nxargs git", None, None, "refuse"),
            ("exec < args.txt; xargs git", None, None, "refuse"),
            (f'echo p origin {topic} | xargs "$(which git)"', None, None, "refuse"),
            (f"echo p origin {topic} | xargs ${{G:-git}}", None, None, "refuse"),
            (f"sh -c 'echo p origin {topic} | {{ true; xargs git; }}'", None, None, "refuse"),
            (f"G=$(which git); $G p origin {topic}", None, None, "refuse"),
            ('git rebase "${X:---exec=sh /tmp/p.sh}" HEAD~1', None, None, "refuse"),
            ("git rebase $(echo HEAD) --exec 'sh /tmp/p.sh'", None, None, "refuse"),
            (f"sh -c 'G=git; $G p origin {topic}'", None, None, "refuse"),
            (f"sh -c 'git -C \"/tmp status\" p origin {topic}'", None, None, "refuse"),
            (f"git fetch --upload-pack='{force} #' .", None, None, "refuse"),
            ("git grep -O'sh /tmp/p.sh' x", None, None, "refuse"),
            (f"GIT_SEQUENCE_EDITOR='{force}; true' git rebase -i HEAD~1", None, None,
             "refuse"),
            ("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.fsmonitor "
             "GIT_CONFIG_VALUE_0=/tmp/p.sh git status", None, None, "refuse"),
            ("PATH=/tmp/x:$PATH git log", None, None, "refuse"),
            (f"export PAGER='{force}'; git log", None, None, "refuse"),
            ("git status --short", None, None, "admit"),
            ("git --no-pager log --oneline -1", None, None, "admit"),
            ("git rebase origin/main", None, None, "admit"),
            ("echo `which git`", None, None, "admit"),
            ("which git", None, None, "admit"),
            ("echo a | xargs git status", None, None, "admit"),
            ('echo "$(which git)" | cat', None, None, "admit"),
            ("echo $(git rev-parse HEAD) x", None, None, "admit"),
            ("=git status", None, None, "admit"),
            ("hash g=/usr/bin/git; g status", None, None, "admit"),
            ("sh -c 'git -C \"/tmp status\" status'", None, None, "admit"),
            ("GIT_TRACE=1 git status", None, None, "admit"),
            ("sh -c 'git log --oneline'", None, None, "admit"),
            (f"git push origin {topic}", "plain", None, "admit"),
            (f"git push origin {topic}", "pushurl", None, "refuse"),
            (f"git push origin {topic}", "pushInsteadOf", None, "refuse"),
            (f"git push origin {topic}", "second pushurl", None, "refuse"),
            (f"git push origin {topic}", "plain", "timeout", "refuse"),
            (f"git push origin {topic}", "plain", "nonzero", "refuse"),
            (f"git push origin {topic}", "plain", "empty", "refuse"),
        )
        lookup_block = (
            "    if child.returncode != 0 or not urls:\n"
            "        return PUSH_URL_UNRESOLVED\n"
        )
        mutants = {
            "control": "",
            "config-option-admitted": "GIT_GLOBAL_OPTIONS = {**GIT_GLOBAL_OPTIONS, '-c': 1}\n",
            "alias-admitted": "GIT_LOCAL_SUBCOMMANDS = GIT_LOCAL_SUBCOMMANDS | {'p'}\n",
            "send-pack-admitted":
                "GIT_LOCAL_SUBCOMMANDS = GIT_LOCAL_SUBCOMMANDS | {'send-pack'}\n",
            "subtree-admitted": "GIT_LOCAL_SUBCOMMANDS = GIT_LOCAL_SUBCOMMANDS | {'subtree'}\n",
            "dashed-admitted": "dashed_git_program = lambda name: False\n",
            "uncertain-admitted": "GIT_UNCERTAIN_PROBLEM = None\n",
            "every-operator-opens":
                "opening_operator = lambda tokens, index, operator: True\n",
            "no-operator-opens": "opening_operator = lambda tokens, index, operator: False\n",
            "argument-position-unjudged": (
                "git_argument_problem = lambda program, words, truncation, tail=(), "
                "fed=False: None\n"),
            "equals-expansion-unread": (
                '    if value.startswith("="):\n        value = value[1:]\n', ""),
            "hashed-names-unread": "git_command_names = lambda token_lists: set()\n",
            "piped-git-admitted": "GIT_FED_PROBLEM = None\n",
            "pipe-feeds-only-the-next-segment": (
                "fed = redirected or any(pipe_in(run) for run in runs[:position])",
                "fed = redirected or (position > 0 and pipe_in(runs[position - 1]))"),
            "redirection-feeds-only-its-own-segment": (
                "    redirected = any(",
                "    redirected = False and any("),
            "raw-pipe-feeds-only-the-next-piece": (
                "fed or any(pipe_in(run) for run in parts[1:position:2])",
                "fed or (position > 0 and pipe_in(parts[position - 1]))"),
            "braced-default-position-unread": (
                "fed=fed and not flags[word_start])", "fed=fed and not flags[index])"),
            "quoted-substitution-needs-a-following-word": (
                "or (not fed and (index + 1 >= len(tokens) or tokens[index + 1][1]))",
                "or index + 1 >= len(tokens) or tokens[index + 1][1]"),
            "substitution-output-admitted": (
                "bare_git_supplies_command = lambda tokens, index, cut_at, run: False\n"),
            "quoted-substitution-admitted":
                "quoted_substitution_runs_git = lambda tokens, index, fed=False: False\n",
            "substitution-assignment-unread":
                "substitution_yields_git = lambda tokens, position, assigned: False\n",
            "tail-unscanned": (
                "git_command_option(subcommand, list(words[index + 1:]) + list(tail))",
                "git_command_option(subcommand, list(words[index + 1:]))"),
            "embedded-options-unread": (
                'if word[position] == "-" and word[position - 1] in ":=+?-"',
                'if False and word[position] == "-" and word[position - 1] in ":=+?-"'),
            "raw-names-unread": "raw_git_names = lambda pieces: set()\n",
            "raw-quote-aware-reading-dropped": (
                "            readings.append([value for value, is_operator in tokens "
                "if not is_operator])\n", ""),
            "evaluator-text-unjudged":
                "transmit_in_raw_text = lambda text, names=(), depth=0, fed=False: False\n",
            "command-options-unjudged": "git_command_option = lambda subcommand, words: None\n",
            "short-command-options-dropped": (
                "GIT_COMMAND_OPTIONS = {k: frozenset(o for o in v if o.startswith('--'))"
                " for k, v in GIT_COMMAND_OPTIONS.items()}\n"),
            "upload-pack-dropped": (
                "GIT_COMMAND_OPTIONS = {k: v - {'--upload-pack'}"
                " for k, v in GIT_COMMAND_OPTIONS.items()}\n"),
            "assignments-unjudged": "git_assignment_problem = lambda names, strict: None\n",
            "prefix-allowlist-loosened":
                "GIT_ASSIGNMENT_ALLOWED = GIT_ASSIGNMENT_ALLOWED | {'PATH'}\n",
            "command-variables-dropped": "GIT_COMMAND_VARIABLES = frozenset()\n",
            "no-push-url-check": "push_url_problem = lambda context: None\n",
            "first-push-url-only":
                "PUSH_URL_LOOKUP = tuple(w for w in PUSH_URL_LOOKUP if w != '--all')\n",
            "fetch-url-only":
                "PUSH_URL_LOOKUP = tuple(w for w in PUSH_URL_LOOKUP if w != '--push')\n",
            "lookup-timeout-admitted": "PUSH_URL_TIMEOUT = None\n",
            "lookup-oserror-admitted": (
                "    except OSError:\n        return PUSH_URL_UNRESOLVED\n",
                "    except OSError:\n        return None\n"),
            "lookup-nonzero-admitted": (
                lookup_block, "    if not urls:\n        return PUSH_URL_UNRESOLVED\n"),
            "lookup-empty-admitted": (
                lookup_block,
                "    if child.returncode != 0:\n        return PUSH_URL_UNRESOLVED\n"),
        }

        def outcome(result):
            if result.returncode == 0:
                return "admit"
            if result.returncode == 2 and "lifecycle guard: unsafe push: " in result.stderr:
                return "refuse"
            return f"invalid: exit {result.returncode}: {result.stderr[-300:]}"

        def oserror_outcome(text, path):
            # The one branch no CLI run reaches alone (Task 3): call the copy's function.
            module = types.ModuleType(f"mutant_{path.stem.replace('-', '_')}")
            module.__file__ = str(path)
            exec(compile(text, str(path), "exec"), module.__dict__)
            context = types.SimpleNamespace(
                git_bin=str(directory / "no-such-git"), cwd=str(repos["plain"]),
                timeout=5, repository="fagenorn/nix-config")
            problem = module.push_url_problem(context)
            return "admit" if problem is None else "refuse"

        directory = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        expected = [want for *_, want in rows] + ["refuse"]
        base_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
        for name, mutation in mutants.items():
            if isinstance(mutation, tuple):
                old, new = mutation
                self.assertEqual(1, source.count(old), (name, "replacement must match once"))
                text = source.replace(old, new, 1)
            else:
                text = source.replace(anchor, "\n" + mutation + anchor, 1)
            path = directory / f"{name}.py"
            path.write_text(text, encoding="utf-8")
            outcomes = []
            for command, repo, mode, _ in rows:
                payload = {"tool_name": "Bash", "tool_input": {"command": command}}
                if repos[repo] is not None:
                    payload["cwd"] = str(repos[repo])
                argv = [sys.executable, "-I", str(path),
                        "--base-policy", str(BASE_POLICY_PATH),
                        "--policy", str(directory / "absent-policy.json"),
                        "--derive-bin", "/usr/bin/false"]
                env = dict(base_env)
                if mode is not None:
                    argv += ["--git-bin", str(self.fake_git), "--child-timeout-seconds", "0.5"]
                    env["FAKE_PUSH_URL_MODE"] = mode
                result = subprocess.run(
                    argv, input=json.dumps(payload), env=env,
                    text=True, capture_output=True, timeout=10, check=False,
                )
                outcomes.append(outcome(result))
            outcomes.append(oserror_outcome(text, path))
            labels = [command for command, *_ in rows] + ["push_url_problem with no git"]
            with self.subTest(mutant=name):
                if name == "control":
                    self.assertEqual(expected, outcomes)
                else:
                    caught = [
                        label for label, want, got in zip(labels, expected, outcomes)
                        if got in ("admit", "refuse") and got != want
                    ]
                    self.assertTrue(caught, (name, list(zip(labels, expected, outcomes))))

    def test_detaching_refusal_precedes_the_push_grammar(self):
        # AC3: still refused, now for detaching rather than as a push.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        result = self.run_guard("nohup git push origin main", cwd=repo)
        self.assert_detaching_refusal(result, "nohup", "nohup git push origin main")
        self.assertNotIn("unsafe push", result.stderr)
        # D1: the check runs before the base policy loads. The registered wrapper
        # forwards "$@", so a later --base-policy overrides the store base policy.
        bad_policy = ("--base-policy", "/nonexistent/lifecycle-guard-base-policy.json")
        refused = self.invoke_command("setsid x", *bad_policy)
        self.assert_detaching_refusal(refused, "setsid", "setsid x")
        control = self.invoke_command("true", *bad_policy)
        self.assertEqual(2, control.returncode)
        self.assertIn("lifecycle guard: invalid policy:", control.stderr)

    def test_whitespace_normalisation_still_accepts_a_valid_push(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in ("git  push -u origin topic", "git\tpush origin topic"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_push_grammar_accepts_only_plain_nondefault_branch(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        ok = self.run_guard("git push -u origin worktree-issue-101-quota", cwd=repo)
        self.assertEqual(0, ok.returncode, ok.stderr)
        self.assertEqual(0, self.run_guard("git push origin topic", cwd=repo).returncode)
        for bad in (
            "git push origin main",                       # default branch
            "git push --force origin topic",              # force
            "git push origin :topic",                     # delete refspec
            "git push origin +topic",                     # force refspec
            "git push upstream topic",                    # foreign remote
            "git push --mirror origin",                   # mirror
            "git push origin --delete topic",             # branch deletion
            "git push origin --tags",                     # tags
            "git push -u origin topic extra",             # extra refspec
            "git push origin $(evil)",                    # command substitution
            "git push",                                   # implicit remote
            "git push -u origin topic && rm -rf /",       # chained (issue 418 grammar)
        ):
            with self.subTest(command=bad):
                result = self.run_guard(bad, cwd=repo)
                self.assertEqual(2, result.returncode, bad)
                self.assertIn("lifecycle guard: unsafe push:", result.stderr)

    def test_push_outside_fagenorn_blocks(self):
        repo = self.make_repo("git@github.com:someoneelse/tool.git")
        result = self.run_guard("git push -u origin topic", cwd=repo)
        self.assertEqual(2, result.returncode)
        self.assertIn("outside standing authorization", result.stderr)

    def test_push_fails_closed_without_a_resolvable_default_branch(self):
        repo = self.make_repo("git@github.com:fagenorn/argus.git", default_branch=None)
        result = self.run_guard("git push -u origin topic", cwd=repo)
        self.assertEqual(2, result.returncode)
        self.assertIn("default branch", result.stderr)

    def test_pr_create_grammar_and_base_check(self):
        repo = self.make_repo("https://github.com/fagenorn/argus.git")
        ok = self.run_guard(
            'gh pr create --repo fagenorn/argus --base main --head issue-7-fix '
            '--title "fix: guard" --body "Closes #7"', cwd=repo)
        self.assertEqual(0, ok.returncode, ok.stderr)
        for bad in (
            # wrong repo
            'gh pr create --repo fagenorn/nix-config --base main --head t --title "x" --body "y"',
            # wrong base
            'gh pr create --repo fagenorn/argus --base release --head t --title "x" --body "y"',
            # unsafe title
            'gh pr create --repo fagenorn/argus --base main --head t --title "$(pwn)" --body "y"',
            # unsafe body
            'gh pr create --repo fagenorn/argus --base main --head t --title "x" --body "`id`"',
            # head is the base
            'gh pr create --repo fagenorn/argus --base main --head main --title "x" --body "y"',
            # wrong shape
            'gh pr create --repo fagenorn/argus --base main --head t --fill',
            # extra flag
            'gh pr create --repo fagenorn/argus --base main --head t --title "x" --body "y" --draft',
            # flag order
            'gh pr create --base main --repo fagenorn/argus --head t --title "x" --body "y"',
        ):
            with self.subTest(command=bad):
                result = self.run_guard(bad, cwd=repo)
                self.assertEqual(2, result.returncode, bad)
                self.assertIn("lifecycle guard: unsafe PR creation:", result.stderr)

    def test_pr_create_takes_an_optional_draft_flag(self):
        """Issue 671: `--draft` stands after `--repo <slug>` in both creation forms,
        with and without the token-scrub prefix; it stays refused anywhere else."""
        repo = self.make_repo("https://github.com/fagenorn/argus.git")
        head = "--base main --head issue-7-fix"
        inline = '--title "fix: guard" --body "Closes #7"'
        for command in (
            f"gh pr create --repo fagenorn/argus --draft {head} {inline}",
            f"unset GITHUB_TOKEN && gh pr create --repo fagenorn/argus --draft {head} {inline}",
            f"env -u GITHUB_TOKEN gh pr create --repo fagenorn/argus --draft {head} {inline}",
            f"gh pr create --repo fagenorn/argus --draft {head} --title t --body-file /tmp/n.md",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, result.stderr)
        for bad in (
            f"gh pr create --repo fagenorn/argus {head} {inline} --draft",
            f"gh pr create --repo fagenorn/argus {head} --draft {inline}",
            f"gh pr create --draft --repo fagenorn/argus {head} {inline}",
            f"gh pr create --repo fagenorn/argus --draft --draft {head} {inline}",
            f"gh pr create --repo fagenorn/argus --draft=true {head} {inline}",
        ):
            with self.subTest(command=bad):
                result = self.run_guard(bad, cwd=repo)
                self.assertEqual(2, result.returncode, bad)
                self.assertIn("lifecycle guard: unsafe PR creation:", result.stderr)

    def test_pr_create_body_file_must_be_outside_the_working_tree(self):
        """Issue 386: the PR is born with its notes via --body-file, from a path outside the tree."""
        repo = self.make_repo("https://github.com/fagenorn/argus.git")
        outside = os.path.join(tempfile.gettempdir(), "release-body-386.md")
        form = ('gh pr create --repo fagenorn/argus --base main --head issue-7-fix '
                '--title "fix: guard" --body-file {}')
        ok = self.run_guard(form.format(outside), cwd=repo)
        self.assertEqual(0, ok.returncode, ok.stderr)
        scrubbed = self.run_guard("unset GITHUB_TOKEN && " + form.format(outside), cwd=repo)
        self.assertEqual(0, scrubbed.returncode, scrubbed.stderr)
        for bad, problem in (
            (form.format(os.path.join(repo, "notes.md")), "inside the working tree"),
            (form.format(os.path.join(repo, "sub", "..", "notes.md")), "absolute path"),
            (form.format("notes.md"), "absolute path"),
            (form.format("'/tmp/a;b.md'"), "absolute path"),
            (form.format("'/tmp/a b.md'"), "absolute path"),
            (form.format("/tmp/$HOME.md"), "`$` outside quotes"),
            (form.format("/tmp/x/../../etc/passwd"), "absolute path"),
            (form.format(outside) + ' --body "y"', "out of place"),
        ):
            with self.subTest(command=bad):
                result = self.run_guard(bad, cwd=repo)
                self.assertEqual(2, result.returncode, bad)
                self.assertIn("lifecycle guard: unsafe PR creation:", result.stderr)
                self.assertIn(problem, result.stderr)

    def test_pr_create_body_file_safety_branches_each_refuse(self):
        """Issue 386: each safety branch of the placement check refuses on its own.

        Every row passes the path-spelling rule, so only the named branch can
        refuse it: removing that branch from the guard turns its row red.
        """
        repo = self.make_repo("https://github.com/fagenorn/argus.git")
        form = ('gh pr create --repo fagenorn/argus --base main --head issue-7-fix '
                '--title "fix: guard" --body-file {}')
        outside = os.path.join(tempfile.gettempdir(), "release-body-386.md")
        link = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "repo-link"
        link.symlink_to(repo, target_is_directory=True)
        rows = [
            # Fail closed: in the .git directory the origin and default branch
            # resolve but there is no working tree to check the path against.
            ("no working tree", form.format(outside), repo / ".git",
             "cannot resolve the working tree"),
            # realpath: a symlink outside the tree that points into it.
            ("symlink into the tree", form.format(link / "notes.md"), repo,
             "inside the working tree"),
            # Another segment could create or relink the file before gh reads it.
            # The allowlist grammar (issue 418) refuses every such segment but a
            # leading cd, which only the placement check refuses.
            ("cd before", "cd {} && {}".format(repo, form.format(outside)), repo,
             "whole command"),
            ("ln before", "ln -sfn {}/notes.md {} && {}".format(
                repo, outside, form.format(outside)), repo, "&&` before the verb"),
            ("after a semicolon", "true; " + form.format(outside), repo,
             "`;` outside quotes"),
            ("piped stdin", "cat {}/notes.md | {}".format(
                repo, form.format("/dev/stdin")), repo, "`|` outside quotes"),
            ("followed by", form.format(outside) + " || true", repo, "`|` outside quotes"),
            # Device and process files read whatever the shell wired to them.
            ("/dev/stdin", form.format("/dev/stdin"), repo, "device or process file"),
            ("/dev/fd/0", form.format("/dev/fd/0"), repo, "device or process file"),
            ("/proc fd", form.format("/proc/self/fd/0"), repo,
             "device or process file"),
            # One segment can still redirect or expand through an unquoted title.
            ("title redirect", form.format("/tmp/b.md").replace(
                '"fix: guard"', "x<{}/notes.md".format(repo)), repo,
             "`<` outside quotes"),
            ("title brace expansion", form.format(outside).replace(
                '"fix: guard"', "{x,--base,release}"), repo, "`{` outside quotes"),
        ]
        respelled = str(repo).swapcase()
        if os.path.exists(respelled) and respelled != str(repo):
            # Case fold: on a case-insensitive volume the respelled repo is the repo.
            rows.append(("respelled case", form.format(
                os.path.join(respelled, "notes.md")), repo, "inside the working tree"))
            rows.append(("respelled /dev", form.format("/DEV/stdin"), repo,
                         "device or process file"))
        elif sys.platform == "darwin":
            self.fail("expected a case-insensitive temporary volume on macOS")
        for name, command, cwd, problem in rows:
            with self.subTest(row=name):
                result = self.run_guard(command, cwd=cwd)
                self.assertEqual(2, result.returncode, command)
                self.assertIn("lifecycle guard: unsafe PR creation:", result.stderr)
                self.assertIn(problem, result.stderr)

    def test_pr_create_outside_fagenorn_blocks(self):
        repo = self.make_repo("git@github.com:someoneelse/tool.git")
        result = self.run_guard(
            'gh pr create --repo someoneelse/tool --base main --head t '
            '--title "x" --body "y"', cwd=repo)
        self.assertEqual(2, result.returncode)
        self.assertIn("outside standing authorization", result.stderr)

    def test_merge_validates_in_every_fagenorn_repo_and_blocks_elsewhere(self):
        argus = self.make_repo("git@github.com:fagenorn/argus.git")
        merge = "gh pr merge 107 --repo fagenorn/argus --merge --delete-branch"
        good = self.run_guard(merge, cwd=argus)
        self.assertEqual(0, good.returncode, good.stderr)
        foreign = self.make_repo("git@github.com:someoneelse/tool.git")
        blocked = self.run_guard(
            "gh pr merge 1 --repo someoneelse/tool --merge --delete-branch", cwd=foreign)
        self.assertEqual(2, blocked.returncode)
        self.assertIn("outside standing authorization", blocked.stderr)

    def test_merge_guard_validates_other_fagenorn_repos(self):
        # The merge grammar is templated on the detected repository, so a
        # fagenorn-owned repo other than nix-config is validated, not deferred.
        elsewhere = self.make_repo("https://github.com/fagenorn/argus.git")
        allowed = self.run_guard(
            "gh pr merge 107 --repo fagenorn/argus --merge --delete-branch", cwd=elsewhere)
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        for command in (
            "gh pr merge 107 --repo fagenorn/argus --squash",
            "gh pr merge 107 --repo fagenorn/nix-config --merge --delete-branch",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=elsewhere)
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)

    def test_merge_guard_still_blocks_inside_its_own_repository(self):
        for origin in (
            "https://github.com/fagenorn/nix-config.git",
            "git@github.com:fagenorn/nix-config.git",
        ):
            with self.subTest(origin=origin):
                result = self.run_guard(
                    "gh pr merge 1 --repo someone/else --merge --delete-branch",
                    cwd=self.make_repo(origin),
                )
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)

    def test_merge_guard_fails_closed_when_repository_is_unknown(self):
        plain = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        for cwd in (plain, self.make_repo("https://example.invalid/x/y.git")):
            with self.subTest(cwd=str(cwd)):
                result = self.run_guard(
                    "gh pr merge 1 --repo someone/else --merge --delete-branch", cwd=cwd
                )
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)

    def test_merge_guard_fails_closed_without_a_cwd(self):
        result = self.run_guard(
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch")
        self.assertEqual(2, result.returncode)
        self.assertIn("outside standing authorization", result.stderr)

    def test_branch_delete_guard_stays_global(self):
        elsewhere = self.make_repo("https://github.com/fagenorn/argus.git")
        blocked = self.invoke_command_in("git branch -d topic; true", elsewhere)
        self.assertEqual(2, blocked.returncode)
        self.assertIn("lifecycle guard: unsafe branch deletion:", blocked.stderr)
        allowed = self.invoke_command_in("git branch -d issue-30-safe", elsewhere)
        self.assertEqual(0, allowed.returncode, allowed.stderr)

    def test_unsafe_merge_shapes_fail_before_network(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
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
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)

    def test_merge_dependency_and_predicate_failures_block(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        command = (
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch"
        )
        guard_args = (
            "--gh-bin", str(self.fake_gh), "--child-timeout-seconds", "0.5",
        )
        cases = (
            ({"FAKE_PR_MODE": "nonzero"}, "PR lookup", "fake pr failure"),
            ({"FAKE_PR_MODE": "timeout"}, "PR lookup", None),
            ({"FAKE_PR_MODE": "invalid"}, "PR predicate", "parse error"),
            ({"FAKE_PR_JSON": '{"state":"OPEN","baseRefName":"main","url":"https://github.com/other/repo/pull/1"}'}, "PR predicate", None),
            ({"FAKE_PR_JSON": '{"state":"OPEN","baseRefName":"dev","url":"https://github.com/fagenorn/nix-config/pull/1"}'}, "PR predicate", None),
            ({"FAKE_PR_JSON": '{"state":"CLOSED","baseRefName":"main","url":"https://github.com/fagenorn/nix-config/pull/1"}'}, "PR predicate", None),
            ({"FAKE_PROTECTION_MODE": "nonzero"}, "protection lookup", "fake protection failure"),
            ({"FAKE_PROTECTION_MODE": "timeout"}, "protection lookup", None),
            ({"FAKE_PROTECTION_MODE": "invalid"}, "protection predicate", "parse error"),
            ({"FAKE_PROTECTION_JSON": '{"required_status_checks":{"contexts":[]},"enforce_admins":{"enabled":true}}'}, "protection predicate", None),
            ({"FAKE_PROTECTION_JSON": '{"required_status_checks":{"contexts":["Nix Eval"]},"enforce_admins":{"enabled":false}}'}, "protection predicate", None),
        )
        for env, reason, diagnostic in cases:
            with self.subTest(env=env):
                result = self.run_guard(command, cwd=repo, env=env, guard_args=guard_args)
                self.assertEqual(2, result.returncode)
                self.assertIn(f"lifecycle guard: {reason}", result.stderr)
                if diagnostic is not None:
                    self.assertIn(diagnostic, result.stderr)

    def test_merge_dependency_fixture_can_reach_acceptance(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        result = self.run_guard(
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch",
            cwd=repo,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_merge_accepts_the_exact_unset_token_prefix(self):
        # A resolved exhaustive credential-name list yields the merge prefix
        # `unset GITHUB_TOKEN && gh pr merge ...` so gh falls back to the
        # keyring credential; that prefix is one of the accepted scrub spellings.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "unset GITHUB_TOKEN && gh pr merge 1 --repo fagenorn/nix-config "
            "--merge --delete-branch",
            "unset GITHUB_TOKEN && gh pr merge 1 --repo fagenorn/nix-config "
            '--merge --subject "feature (#30)" --delete-branch',
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_prefixed_merge_reaches_acceptance_on_the_integration_base(self):
        # The real-world shape that motivated the prefix: a nodocom ship-stage
        # merge onto the declared integration branch `dev`. The integration
        # base is exempt from the protection demand, so the protection stage is
        # poisoned here to prove the guard never even consults it.
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        result = self.run_guard(
            "unset GITHUB_TOKEN && gh pr merge 42 --repo elevenyellow/nodocom "
            "--merge --delete-branch",
            cwd=repo,
            env={"FAKE_PR_JSON":
                 '{"state":"OPEN","mergeStateStatus":"CLEAN","baseRefName":"dev","headRefName":"issue-42-topic",'
                 '"url":"https://github.com/elevenyellow/nodocom/pull/42"}',
                 "FAKE_PROTECTION_MODE": "nonzero"},
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_merge_protection_demand_follows_the_base_branch(self):
        # In a repository with a declared integration base, a PR into that base
        # merges without forge protection, while a PR into the default branch
        # still demands it — the exemption follows the base, not the repo.
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 7 --repo elevenyellow/nodocom --merge --delete-branch"
        dev_pr = {
            "FAKE_PROTECTION_MODE": "nonzero",
            "FAKE_PR_JSON": '{"state":"OPEN","mergeStateStatus":"CLEAN","baseRefName":"dev","headRefName":"issue-7-topic",'
                            '"url":"https://github.com/elevenyellow/nodocom/pull/7"}',
        }
        allowed = self.run_guard(merge, cwd=repo, env=dev_pr)
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        main_pr = {
            "FAKE_PROTECTION_MODE": "nonzero",
            "FAKE_PR_JSON": '{"state":"OPEN","mergeStateStatus":"CLEAN","baseRefName":"main","headRefName":"issue-7-topic",'
                            '"url":"https://github.com/elevenyellow/nodocom/pull/7"}',
        }
        blocked = self.run_guard(merge, cwd=repo, env=main_pr)
        self.assertEqual(2, blocked.returncode)
        self.assertIn("protection lookup failed", blocked.stderr)

    # ------------------------------------------------------------------
    # Production rules (issue 1149)
    # ------------------------------------------------------------------

    SECOND = "acme/second"
    SECOND_ROW = {**PROD_ROW, "production": {
        "changes": [{"id": "ship", "argv": ["just", "switch"]}], "read_only": [],
        "release_profile": "second-release"}}
    QUIET = "acme/quiet"
    QUIET_ROW = {**PROD_ROW, "production": {"changes": [], "read_only": [],
                                            "release_profile": "p"}}
    DEPLOY = "changes the production of acme/deployer (production rule deploy)"

    def production_args(self, rows):
        return ("--gh-bin", str(self.fake_gh), "--policy",
                str(self.write_policy(derived_repositories=rows, derivation={})))

    def test_a_declared_production_command_is_refused_in_every_spelling(self):
        """AC1: a declared command is refused in every spelling the guard reads."""
        guard_args = self.production_args({NODO: NODO_ROW, PROD: PROD_ROW})
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        rules = {
            self.DEPLOY: (
                "just switch", "just switch mbp", "just --justfile justfile switch",
                "/run/current-system/sw/bin/just switch", "env FOO=1 just switch",
                "command just switch", "sudo -u root just switch", "exec just switch",
                "timeout 600 just switch", "echo just switch", '"just" switch',
                "j\"us\"t sw'itch'", "just \\\nswitch", "(just switch)", "{ just switch; }",
                "true && just switch", "x=$(just switch)", "just $(printf switch)",
                'echo "$(just switch)"', "sh -c 'just switch'", '/bin/bash -c "just switch"',
                "eval 'ju''st sw''itch'", "env -S 'just switch'",
                "env --split-string='just switch'", "just switch 'unterminated",
                "echo 'just switch' | sh", "just build switch",
                "release transaction preview --repo-root . --title x; just switch"),
            "(production rule kube-apply)": (
                "sh -c 'kubectl get pods'", "timeout 600 kubectl apply -f x",
                "echo apply | xargs kubectl",
                "release transaction preview --repo-root . --commit abc123 "
                '--version v1.2.3 --title "$(kubectl apply -f x)"',
                "release transaction run --repo-root . --confirm tok && kubectl apply -f x"),
            "(production rule deploy-script)": (
                "./scripts/deploy.sh", "scripts/deploy.sh --dry-run",
                "env FOO=1 ./scripts/deploy.sh", "timeout 60 ./scripts/deploy.sh",
                "bash scripts/deploy.sh"),
        }
        for needle, commands in rules.items():
            for command in commands:
                with self.subTest(command=command):
                    result = self.run_guard(command, cwd=prod, guard_args=guard_args)
                    self.assertEqual(2, result.returncode, (command, result.stderr))
                    self.assertIn(needle, result.stderr)

    @staticmethod
    def redirection_heredocs():
        """Issue 1173: a heredoc whose quoted delimiter holds a redirection operator. The
        body's first line is the delimiter as the operator rewrite would leave it, so a
        reader that rewrites the delimiter closes the body there, and its apostrophe then
        pairs with the quote in the trailing comment."""
        return tuple(
            f"cat <<'{delimiter}' >/dev/null\n{early}\ndon't\n{delimiter}\njust switch # '"
            for delimiter, early in (("X>", "X&>"), ("X>&", "X>"), ("X<&", "X<"),
                                     ("X>|", "X>"))) + (
            # A later expanding body the scan cannot read leaves the earlier bodies
            # unrewritten too: the whole remainder goes to the raw-text reading.
            "cat <<'X>' <<EOF >/dev/null\nX&>\nEOF\ndon't\nX>\n$?\nEOF\njust switch # '",)

    def test_a_production_command_hidden_by_a_runner_a_redirection_or_a_quoting_is_refused(self):
        """AC1 review findings: shell text behind a runner, a leading redirection, an ANSI-C
        quoted word and a continued directory name never hide a declared command."""
        guard_args = self.production_args({NODO: NODO_ROW, PROD: PROD_ROW})
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        elsewhere = self.make_repo("git@github.com:fagenorn/tool.git")
        rules = {
            self.DEPLOY: (
                "timeout 600 sh -c 'just switch'", "devenv shell -- bash -c 'just switch'",
                "echo x | xargs sh -c 'just switch'", "nix-shell --run 'just switch'",
                "watch 'just switch'", "flock /tmp/l -c 'just switch'",
                "timeout 5 env -S 'just switch'", "timeout 5 env -Sjust switch",
                "nice -n 5 /bin/zsh -c 'just switch'",
                "find . -exec sh -c 'just switch' ';'", ">/dev/null sh -c 'just switch'",
                "$'just' switch", "just $'switch'", "$\"just\" switch", "ju$'st' switch",
                "env FOO=1 $'just' switch",
                "echo $'it\\'s ready'; just switch  # don't skip",
                "cat <<EOF >/dev/null\ndon't\nEOF\necho $'it\\'s'; just switch # don't",
                "echo \\ #; just switch", "ls My\\ #2; just switch", "echo \\\t#; just switch",
                *self.redirection_heredocs()),
            "(production rule kube-apply)": (
                "nix develop -c bash -c 'kubectl apply -f x'",
                "timeout 5 bash -c 'kubectl apply -f x'", "$'kubectl' apply -f x",
                "printf $'can\\'t wait\\n' && kubectl apply -f x  # don't forget",
                ">| /tmp/x kubectl apply", "echo \\ #; kubectl apply"),
            "(production rule deploy-script)": (
                ">/dev/null ./scripts/deploy.sh", "2>/dev/null ./scripts/deploy.sh",
                "> /dev/null ./scripts/deploy.sh", ">>log.txt 2>&1 ./scripts/deploy.sh",
                "</dev/null ./scripts/deploy.sh", "2>&1 env FOO=1 ./scripts/deploy.sh",
                ">|/dev/null ./scripts/deploy.sh", "2>|/dev/null ./scripts/deploy.sh"),
        }
        for needle, commands in rules.items():
            for command in commands:
                with self.subTest(command=command):
                    result = self.run_guard(command, cwd=prod, guard_args=guard_args)
                    self.assertEqual(2, result.returncode, (command, result.stderr))
                    self.assertIn(needle, result.stderr)
        for command in ("c\\\nd %s && just switch" % prod, "cd\\\n %s && just switch" % prod):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=elsewhere, guard_args=guard_args)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn(self.DEPLOY, result.stderr)
        for command in ("timeout 600 sh -c 'just build'", "2>&1 just build",
                        ">/dev/null git add scripts/deploy.sh", "timeout 5 echo hello world",
                        "echo $'x' just", "echo \\\\ #; just switch"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=prod, guard_args=guard_args)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_a_production_command_is_refused_when_the_repository_lookup_fails(self):
        """AC3 review finding: a lookup that times out is not an unregistered repository."""
        guard_args = (*self.production_args({PROD: PROD_ROW}), "--child-timeout-seconds", "0.3")
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        slow = Path(self.fixture_dir.name) / "slow-git"
        slow.write_text("#!/bin/sh\nexec sleep 3\n", encoding="utf-8")
        slow.chmod(0o755)
        refused = self.run_guard("just switch", cwd=prod,
                                 guard_args=(*guard_args, "--git-bin", str(slow)))
        self.assertEqual(2, refused.returncode, refused.stderr)
        self.assertIn("repository lookup timed out", refused.stderr)
        passed = self.run_guard("true", cwd=prod,
                                guard_args=(*guard_args, "--git-bin", str(slow)))
        self.assertEqual(0, passed.returncode, passed.stderr)

    def test_a_deeply_nested_compiled_policy_refuses_no_call(self):
        """AC3 review finding: a compiled policy json cannot load contributes no row and
        never makes an ordinary command exit 2."""
        deep = Path(self.fixture_dir.name) / "deep.json"
        deep.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        for command in ("true", "just switch"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=prod, guard_args=(
                    "--gh-bin", str(self.fake_gh), "--policy", str(deep)))
                self.assertEqual(0, result.returncode, result.stderr)

    def test_the_production_refusal_is_one_sentence_naming_the_rule_profile_and_route(self):
        """AC4: the refusal is one line naming the argv, the project, the rule, the profile
        and the release route."""
        guard_args = self.production_args({NODO: NODO_ROW, PROD: PROD_ROW})
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        tail = (", so it runs only through the release profile forge-main with release "
                "transaction preview and release transaction run.\n")
        for command, shown, rule in (
                ("just switch", "just switch", "deploy"),
                ("kubectl apply -f deploy.yaml", "/usr/local/bin/kubectl", "kube-apply")):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=prod, guard_args=guard_args)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual(
                    f"lifecycle guard: `{shown}` changes the production of {PROD} "
                    f"(production rule {rule}){tail}", result.stderr)

    def test_a_rule_the_console_activates_is_refused_naming_the_consoles_activate(self):
        """Issue 1193: the rule named by `console_activation` is approved through the
        console's Activate; every other rule keeps the release-profile sentence."""
        console_row = {**PROD_ROW, "production": {**PRODUCTION, "console_activation": "deploy"}}
        guard_args = self.production_args({NODO: NODO_ROW, PROD: console_row})
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        result = self.run_guard("just switch", cwd=prod, guard_args=guard_args)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual(
            "lifecycle guard: `just switch` changes the production of acme/deployer "
            "(production rule deploy), so it runs only through the console's Activate, "
            "on the line that says a console change is not active on this host.\n",
            result.stderr)
        other = self.run_guard("kubectl apply -f deploy.yaml", cwd=prod, guard_args=guard_args)
        self.assertEqual(2, other.returncode, other.stderr)
        self.assertEqual(
            "lifecycle guard: `/usr/local/bin/kubectl` changes the production of "
            "acme/deployer (production rule kube-apply), so it runs only through the "
            "release profile forge-main with release transaction preview and release "
            "transaction run.\n", other.stderr)

    def test_declared_read_only_routes_and_the_release_route_pass_the_production_rules(self):
        """AC2: a read-only route, the release route and a mere mention pass."""
        guard_args = self.production_args({NODO: NODO_ROW, PROD: PROD_ROW})
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        preview = "release transaction preview --repo-root . --commit abc123 --version v1.2.3"
        for command in (
                "just build", "just build mbp", "env FOO=1 just build", "sh -c 'just build'",
                "kubectl get pods", "timeout 5 kubectl get pods -A",
                f"{preview} --title 'ship just switch'",
                "release transaction run --repo-root . --confirm tok",
                "release transaction run --repo-root . --commit " + "a" * 40
                + " --version v1.2.0 --title 'v1.2.0 notes' --notes-file /tmp/n"
                " --confirm tag:0123456789ab --confirm github-release:0123456789ab",
                'echo "just switch"', "git commit -m 'run just switch later'",
                "cat > notes.md <<'EOF'\njust switch\nEOF\n", "true # just switch",
                "cat <<'EOF' >/dev/null\nbody\nEOF\njust build",
                "cat <<'X>' >/dev/null\nX&>\nX>\njust build # '",
                "just switcher", "just build switchboard",
                "git add scripts/deploy.sh", "cat scripts/deploy.sh",
                "git diff -- scripts/deploy.sh", "git add kubectl",
                f"{preview} --title kubectl", f'{preview} --title "kubectl"',
                "release transaction run --repo-root . --confirm tok --title deploy.sh"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=prod, guard_args=guard_args)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_a_production_command_counts_only_where_it_runs_not_where_it_is_mentioned(self):
        """Issue 1192: words inside one quoted argument, a comment or an
        exactly-read heredoc body are a mention, wherever the rest of the command reads a
        shell, while shell code, an executed substitution and unparseable text still count."""
        guard_args = self.production_args({NODO: NODO_ROW, PROD: PROD_ROW})
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        mentions = (
            "printf '%s\\n' 'run just switch later' > note.txt",
            "cat > note.txt <<EOF\nrun just switch later\nEOF\n",
            "cat > note.txt <<'EOF'\nrun just switch later\nEOF\n",
            "true # run just switch later",
            "printf '%s\\n' 'run kubectl later' > note.txt",
            "printf '%s\\n' 'run just switch later' > note.txt; sh -c 'true'",
            "bash -c true && git commit -m 'run just switch later'",
            "eval true; echo 'just switch' # just switch",
            "env -S 'true'; printf '%s\\n' 'run just switch later' > note.txt",
            "echo 'run kubectl later' > note.txt; timeout 5 bash -c 'true'",
            "devenv shell -- git commit -m 'run just switch later'",
            "timeout 5 echo 'run just switch later'",
            "xargs printf '%s\\n' 'run just switch later'",
            "echo 'just switch <<'; sh -c true",
            'echo "run just switch later <<"; sh -c true',
        )
        runs = (
            "sh -c 'just switch'", "printf '%s\\n' 'a note' > note.txt; sh -c 'just switch'",
            "echo 'a note'; eval 'just switch'", "echo 'a note' && env -S 'just switch'",
            "echo 'a note'; echo $(just switch)", "echo 'a note'; echo `just switch`",
            'echo "a note"; echo "$(just switch)"', "echo 'a note'; just switch 'unterminated",
            "echo 'just switch' | sh", "echo 'just switch' | cat | bash",
            "echo 'just switch' |& sh", "bash <<EOF\njust switch\nEOF\n",
            "sh <<<'just switch'", "cat <<EOF\n$(just switch)\nEOF\n",
            "cat <<EOF >/dev/null\nnote\nEOF\nsh -c 'just switch'",
            "echo 'a note'; timeout 5 sh -c 'just switch'", "watch 'just switch'",
            "echo 'a note'; nix-shell --run 'just switch'",
            "printf '%s\\n' 'run kubectl later' > note.txt; sh -c 'kubectl apply -f x'",
            "echo 'a note'; just switch",
            "cmd='just switch'; eval \"$cmd\"", "c='just switch'\nsh -c \"$c\"",
            "export C='kubectl apply -f x' && bash -c \"$C\"", "echo 'just switch' > f && bash < f",
            "echo 'just switch' > f && bash f", "echo 'just switch' > f; sh -c 'bash f'",
            "echo 'just switch' | { true; sh; }", "echo 'just switch' | (true; sh)",
            "timeout 5 flock /tmp/deploy.lock -c 'just switch'",
            "eval $(true; printf '%s' 'just switch')",
            "devenv shell 'just switch'", "devenv shell -- 'just switch'",
            "timeout 5 devenv shell 'just switch'",
        )
        for command in mentions:
            with self.subTest(mention=command):
                result = self.run_guard(command, cwd=prod, guard_args=guard_args)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        for command in runs:
            with self.subTest(run=command):
                result = self.run_guard(command, cwd=prod, guard_args=guard_args)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn("changes the production of acme/deployer", result.stderr)

    def test_production_rules_hold_only_in_their_project_s_checkout(self):
        """AC3: a repository with no rule, an empty `changes`, or no cwd is never refused."""
        rows = {NODO: NODO_ROW, PROD: PROD_ROW, self.QUIET: self.QUIET_ROW}
        guard_args = self.production_args(rows)
        for slug in ("fagenorn/tool", NODO, self.QUIET):
            repo = self.make_repo(f"git@github.com:{slug}.git")
            for command in ("just switch", "kubectl apply -f x"):
                with self.subTest(slug=slug, command=command):
                    result = self.run_guard(command, cwd=repo, guard_args=guard_args)
                    self.assertEqual(0, result.returncode, result.stderr)
        result = self.invoke_command("just switch", *guard_args)
        self.assertEqual(0, result.returncode, result.stderr)
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        control = self.run_guard("just switch", cwd=prod, guard_args=guard_args)
        self.assertEqual(2, control.returncode, control.stderr)

    def test_a_directory_change_judges_every_project_declaring_the_production_command(self):
        """AC1, D7: a command that may change directory is judged against every declaring row,
        the cwd row first, then by sorted slug."""
        guard_args = self.production_args({PROD: PROD_ROW, self.SECOND: self.SECOND_ROW})
        tool = self.make_repo("git@github.com:fagenorn/tool.git")
        second = self.make_repo(f"git@github.com:{self.SECOND}.git")
        alone = self.run_guard("just switch", cwd=tool, guard_args=guard_args)
        self.assertEqual(0, alone.returncode, alone.stderr)
        for command in (
                "cd . && just switch", "pushd /tmp && just switch",
                "sh -c 'cd /tmp; just switch'", ">/dev/null cd /tmp && just switch",
                "2>/dev/null cd /tmp && just switch", "cd>/dev/null /tmp && just switch",
                "builtin cd /tmp && just switch", 'echo "$(cd /tmp; just switch)"',
                "x=$(cd /tmp && just switch)"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=tool, guard_args=guard_args)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn(self.DEPLOY, result.stderr)
        for command in ("cd . && just switch", "just switch"):
            with self.subTest(command=command, cwd="second"):
                result = self.run_guard(command, cwd=second, guard_args=guard_args)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn("changes the production of acme/second (production rule ship)",
                              result.stderr)

    def test_the_first_declared_production_rule_names_the_refusal(self):
        """D7: inside a row the first rule in `changes` order that hits names the refusal."""
        guard_args = self.production_args({NODO: NODO_ROW, PROD: PROD_ROW})
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        result = self.run_guard("kubectl apply; just switch", cwd=prod, guard_args=guard_args)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn(self.DEPLOY, result.stderr)

    OWN = "fagenorn/nix-config"
    RERUN_ROW = {**PROD_ROW, "production": {
        "changes": [{"id": "deploy-rerun", "argv": ["gh", "run", "rerun"]}], "read_only": [],
        "release_profile": "forge-main"}}
    RERUN = "changes the production of acme/deployer (production rule deploy-rerun)"

    def test_a_rerun_naming_a_projects_own_repository_is_judged_by_that_projects_rules(self):
        """Issue 1375: a `--repo` rerun is judged only against the project that repository
        names, so another project's rerun rule never refuses a pull-request check rerun."""
        guard_args = self.production_args({self.OWN: NODO_ROW, PROD: self.RERUN_ROW})
        own = self.make_repo(f"git@github.com:{self.OWN}.git")
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        for cwd in (own, prod):
            for command in (
                    f"gh run rerun 123 --failed --repo {self.OWN}",
                    f"gh run rerun 123 --failed -R {self.OWN}",
                    f"gh run rerun 123 --repo={self.OWN} --failed",
                    f"gh run rerun 123 --repo github.com/{self.OWN}",
                    f"cd /tmp && gh run rerun 123 --failed --repo {self.OWN}"):
                with self.subTest(cwd=cwd.name, command=command):
                    result = self.run_guard(command, cwd=cwd, guard_args=guard_args)
                    self.assertEqual(0, result.returncode, result.stderr)

    def test_a_rerun_naming_a_project_that_declares_reruns_is_refused_from_any_directory(self):
        """Issue 1375: the named project's rule refuses, whichever checkout the call runs in."""
        guard_args = self.production_args({self.OWN: NODO_ROW, PROD: self.RERUN_ROW})
        own = self.make_repo(f"git@github.com:{self.OWN}.git")
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        other = self.make_repo("git@github.com:fagenorn/tool.git")
        for cwd in (own, prod, other):
            for command in (
                    f"gh run rerun 9 --failed --repo {PROD}", f"gh run rerun 9 -R {PROD}",
                    f"gh run rerun 9 --repo={PROD}", f"gh run rerun 9 --repo github.com/{PROD}",
                    f"gh run rerun 9 --repo {PROD.upper()}",
                    f"gh run rerun 1 --repo {self.OWN} && gh run rerun 2 --repo {PROD}"):
                with self.subTest(cwd=cwd.name, command=command):
                    result = self.run_guard(command, cwd=cwd, guard_args=guard_args)
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn(self.RERUN, result.stderr)
        self.assertIn(
            "so it runs only through the release profile forge-main with release "
            "transaction preview and release transaction run.",
            self.run_guard(f"gh run rerun 9 --repo {PROD}", cwd=own,
                           guard_args=guard_args).stderr)

    def test_every_way_gh_reads_a_repository_flag_names_the_project_the_guard_judges(self):
        """Issue 1375 A2: a short flag group (`-dR`), `-R=...`, a redirection glued to the
        value and a later unnamed rerun never hide the project a rerun names."""
        guard_args = self.production_args({self.OWN: NODO_ROW, PROD: self.RERUN_ROW})
        own = self.make_repo(f"git@github.com:{self.OWN}.git")
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        other = self.make_repo("git@github.com:fagenorn/tool.git")
        for cwd in (own, prod, other):
            for command in (
                    f"gh run rerun 9 --repo {self.OWN} -dR {PROD}",
                    f"gh run rerun 9 --repo {self.OWN} -dR{PROD}",
                    f"gh run rerun 9 --repo {self.OWN} -R={PROD}",
                    f"gh run rerun 9 --repo {self.OWN} -dR={PROD}",
                    f"gh run rerun 9 --repo {PROD}>rerun.log",
                    f"gh run rerun 9 --repo {PROD} 2>&1",
                    f"gh run rerun 9 >rerun.log --repo {PROD}",
                    f"gh run rerun 9 --repo >rerun.log {PROD}",
                    f"gh run rerun 1 --repo {PROD} && gh run rerun 2",
                    f"gh run rerun 2 && gh run rerun 1 --repo {PROD}"):
                with self.subTest(cwd=cwd.name, command=command):
                    result = self.run_guard(command, cwd=cwd, guard_args=guard_args)
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn(self.RERUN, result.stderr)

    def test_a_repository_flag_inside_an_option_value_names_no_repository(self):
        """Issue 1375 I1: the word after a value-taking option is its value, so a job value
        that spells `--repo=...` never selects another project's rule."""
        guard_args = self.production_args({self.OWN: NODO_ROW, PROD: self.RERUN_ROW})
        own = self.make_repo(f"git@github.com:{self.OWN}.git")
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        other = self.make_repo("git@github.com:fagenorn/tool.git")
        for cwd in (own, prod, other):
            for command in (
                    f"gh run rerun 5 --repo {self.OWN} --job '--repo={PROD}'",
                    f"gh run rerun 5 --repo {self.OWN} --job --repo={PROD}",
                    f"gh run rerun 5 --repo {self.OWN} -j '-R{PROD}'",
                    f"gh run rerun 5 --repo {self.OWN} --job='--repo={PROD}'",
                    f"gh run rerun 5 --repo {self.OWN} -jR{PROD}",
                    f"gh run rerun 123 -dR {self.OWN}",
                    f"gh run rerun 123 -dR{self.OWN} --failed"):
                with self.subTest(cwd=cwd.name, command=command):
                    result = self.run_guard(command, cwd=cwd, guard_args=guard_args)
                    self.assertEqual(0, result.returncode, result.stderr)

    def test_a_rerun_the_guard_cannot_read_exactly_is_judged_by_the_checkout_and_its_names(self):
        """Issue 1375 review: an expansion or glob anywhere in the run, a command
        substitution, a redirection glued to the flag, an unknown flag or a wildcard in the
        value may hide a later repository flag, so the checkout is judged too and every
        repository the words name is judged."""
        guard_args = self.production_args({self.OWN: NODO_ROW, PROD: self.RERUN_ROW})
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        for command in (
                f"X='-R {PROD}'; gh run rerun 9 --repo {self.OWN} $X",
                f"gh run rerun 9 --repo {self.OWN} $(echo -R) {PROD}",
                f"gh run rerun 9 --repo {self.OWN} `echo -R {PROD}`",
                f"gh run rerun 9 --repo {self.OWN} ./x*",
                f"gh run rerun 9 --repo {self.OWN} --json -R {PROD}",
                f"gh run rerun 9 --repo {self.OWN} --unknown -R {PROD}",
                f"gh run rerun 9 --repo {self.OWN} -x -R {PROD}",
                "gh run rerun 123 --repo acme/dep*",
                "gh run rerun 123 --repo 'acme/dep*'",
                f"gh run rerun 9 extra --repo {self.OWN} -R {PROD}"):
            with self.subTest(cwd="deployer", command=command):
                result = self.run_guard(command, cwd=prod, guard_args=guard_args)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn(self.RERUN, result.stderr)
        other = self.make_repo("git@github.com:fagenorn/tool.git")
        for command in (
                f"gh run rerun $(echo 9) --repo {PROD}", f"gh run rerun `echo 9` --repo {PROD}",
                f"gh run rerun 123 --repo>/dev/null {PROD}",
                f"gh run rerun 123 --repo>>/dev/null {PROD}",
                f"gh run rerun 123 --repo{chr(60)}/dev/null {PROD}",
                f"gh run rerun 9 --repo {self.OWN} $X --repo {PROD}"):
            with self.subTest(cwd="other", command=command):
                result = self.run_guard(command, cwd=other, guard_args=guard_args)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn(self.RERUN, result.stderr)

    def test_a_verb_whose_flags_the_guard_does_not_model_is_judged_by_the_checkout(self):
        """Issue 1375 review: only the rerun flag grammar is modelled, so a later `-R` that
        gh reads in another verb's grammar (`--json` is boolean, `-e` takes a value, `--comment`
        takes a value) is never narrowed away from the checkout's rules."""
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        for argv, command in (
                (["gh", "workflow", "run"],
                 f"echo '{{}}' | gh workflow run deploy.yml --repo {self.OWN} --json -R {PROD}"),
                (["gh", "secret", "set"],
                 f"gh secret set K -R {PROD} -e --repo={self.OWN}"),
                (["gh", "issue", "close"],
                 f"gh issue close 5 --comment '--repo={self.OWN}' --repo {PROD}")):
            row = {**PROD_ROW, "production": {
                "changes": [{"id": "deploy-verb", "argv": argv}], "read_only": [],
                "release_profile": "forge-main"}}
            guard_args = self.production_args({self.OWN: NODO_ROW, PROD: row})
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=prod, guard_args=guard_args)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("(production rule deploy-verb)", result.stderr)

    def test_a_rerun_that_names_no_repository_keeps_the_checkout_judgement(self):
        """Issue 1375: only an explicit `--repo` on a parsed run narrows the rules; every
        other reading keeps judging by the checkout, so a hidden or unnamed rerun still
        refuses in the declaring project's checkout."""
        guard_args = self.production_args({self.OWN: NODO_ROW, PROD: self.RERUN_ROW})
        own = self.make_repo(f"git@github.com:{self.OWN}.git")
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        for command in (
                "gh run rerun 9", f"sh -c 'gh run rerun 9 --repo {self.OWN}'",
                'gh run rerun 9 --repo "$TARGET"', f"echo 'gh run rerun 9 --repo {self.OWN}' | sh"):
            with self.subTest(cwd="deployer", command=command):
                result = self.run_guard(command, cwd=prod, guard_args=guard_args)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn(self.RERUN, result.stderr)
        for command in ("gh run rerun 9", f"sh -c 'gh run rerun 9 --repo {self.OWN}'"):
            with self.subTest(cwd="own", command=command):
                result = self.run_guard(command, cwd=own, guard_args=guard_args)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_a_bad_compiled_policy_adds_no_production_refusal(self):
        """AC3: a compiled policy that does not load never refuses a command."""
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        held = Path(self.fixture_dir.name)
        broken = held / "broken.json"
        broken.write_text("{", encoding="utf-8")
        bad_argv = {**PRODUCTION, "changes": [{"id": "deploy", "argv": []}]}
        for name, path in (
                ("missing", held / "absent.json"), ("not json", broken),
                ("a bad row", self.write_policy(
                    derived_repositories={PROD: PROD_ROW, NODO: {**NODO_ROW, "owner": "x"}},
                    derivation={})),
                ("a bad production", self.write_policy(
                    derived_repositories={PROD: {**PROD_ROW, "production": bad_argv}},
                    derivation={})),
                *((f"console_activation {value!r}", self.write_policy(
                    derived_repositories={PROD: {**PROD_ROW, "production": {
                        **PRODUCTION, "console_activation": value}}},
                    derivation={})) for value in ("", "check", 1))):
            for command in ("true", "just switch"):
                with self.subTest(policy=name, command=command):
                    result = self.run_guard(
                        command, cwd=prod,
                        guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(path)))
                    self.assertEqual(0, result.returncode, result.stderr)

    def test_a_production_refusal_runs_no_row_check(self):
        """D3: the row check never confirms a production refusal."""
        guard_args = self.production_args({NODO: NODO_ROW, PROD: PROD_ROW})
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        log = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "derive.log"
        result = self.run_guard("just switch", cwd=prod, guard_args=guard_args,
                                env={"FAKE_DERIVE_LOG": str(log)})
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertFalse(log.exists())

    def test_a_compiled_production_rule_round_trips_through_the_guard(self):
        """AC1, AC2: the compiler's `production` member is what the guard refuses."""
        def declare(contract):
            contract["production"] = {
                "none": False,
                "changes": {"commands": ["nix-activate"], "key_files": [], "mcp_tools": []},
                "read_only": {"commands": ["nix-build"], "mcp_tools": []},
                "release_profile": "github-release",
                "console_activation": "nix-activate"}

        world = GuardPolicyWorld(self)
        world.project("fixture/prodfix", "fagenorn/prodfix", mutate=declare)
        code, report, stderr = world.compile(base=BASE_POLICY_PATH)
        self.assertEqual((0, ["fagenorn/prodfix"]), (code, report["derived"]), stderr)
        repo = self.make_repo("git@github.com:fagenorn/prodfix.git")
        guard_args = ("--gh-bin", str(self.fake_gh), "--policy", str(world.output),
                      "--derive-bin", str(world.row_check()))
        refused = self.run_guard("just switch", cwd=repo, guard_args=guard_args, timeout=60)
        self.assertEqual(2, refused.returncode, refused.stderr)
        self.assertEqual(
            "lifecycle guard: `just switch` changes the production of fagenorn/prodfix "
            "(production rule nix-activate), so it runs only through the console's Activate, "
            "on the line that says a console change is not active on this host.\n",
            refused.stderr)
        allowed = self.run_guard("just build", cwd=repo, guard_args=guard_args, timeout=60)
        self.assertEqual(0, allowed.returncode, allowed.stderr)

    # ------------------------------------------------------------------
    # Issue 1150: the guard also judges file-edit and MCP tool calls. A declared
    # production MCP tool is refused by name; a write to a declared key file is
    # refused in the checkout that declares it.
    # ------------------------------------------------------------------

    def run_tool(self, tool_name, tool_input, cwd=None, guard_args=None):
        payload = {"tool_name": tool_name, "tool_input": tool_input}
        if cwd is not None:
            payload["cwd"] = str(cwd)
        if guard_args is None:
            guard_args = ("--gh-bin", str(self.fake_gh))
        return self.invoke_raw(json.dumps(payload), *guard_args)

    def tool_args(self, rows):
        return self.production_args(rows)

    def tool_rows(self):
        return {NODO: NODO_ROW, PROD: TOOL_ROW}

    def test_a_write_to_a_declared_key_file_is_refused_for_every_edit_tool(self):
        """A write to a declared key file is refused, in every spelling of the path."""
        guard_args = self.tool_args(self.tool_rows())
        glob_rows = {PROD: {**PROD_ROW, "production": {
            **TOOL_PRODUCTION, "key_files": ["deploy/[!a].yaml"]}}}
        glob_args = self.tool_args(glob_rows)
        text = f"is a key file of {PROD} (key file glob "

        def refused(tool, field, path, *more, cwd=None, args=guard_args):
            result = self.run_tool(tool, {field: str(path)}, cwd=cwd, guard_args=args)
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertIn(text, result.stderr)
            for expected in more:
                self.assertIn(expected, result.stderr)

        prod = self.make_repo(f"git@github.com:{PROD}.git")
        for tool, field in EDIT_TOOLS:
            with self.subTest(tool=tool):
                refused(tool, field, prod / "deploy/prod.yaml")
        with self.subTest(case="directories absent"):
            refused("Write", "file_path", prod / "deploy/new/dir/x.yaml")
        with self.subTest(case="notebook"):
            refused("NotebookEdit", "notebook_path", prod / "ops/runbook.ipynb")
        with self.subTest(case="relative path"):
            refused("Edit", "file_path", "deploy/prod.yaml", cwd=prod)
        with self.subTest(case="dot dot"):
            refused("Edit", "file_path", prod / "src/../deploy/prod.yaml")
        with self.subTest(case="alias into the checkout"):
            alias = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "alias"
            alias.symlink_to(prod)
            refused("Edit", "file_path", alias / "deploy/prod.yaml")
        with self.subTest(case="symlink reaching a key file"):
            repo = self.make_repo(f"git@github.com:{PROD}.git")
            (repo / "deploy").mkdir()
            (repo / "deploy/prod.yaml").write_text("x", encoding="utf-8")
            (repo / "notes.yaml").symlink_to("deploy/prod.yaml")
            refused("Edit", "file_path", repo / "notes.yaml")
        with self.subTest(case="key file that is a symlink to another file"):
            repo = self.make_repo(f"git@github.com:{PROD}.git")
            (repo / "deploy").mkdir()
            (repo / "config").mkdir()
            (repo / "config/live.yaml").write_text("x", encoding="utf-8")
            (repo / "deploy/prod.yaml").symlink_to("../config/live.yaml")
            refused("Edit", "file_path", repo / "deploy/prod.yaml",
                    "`deploy/prod.yaml` is a key file")
        with self.subTest(case="key file symlink reached through a directory symlink"):
            repo = self.make_repo(f"git@github.com:{PROD}.git")
            (repo / "deploy").mkdir()
            (repo / "config").mkdir()
            (repo / "config/live.yaml").write_text("x", encoding="utf-8")
            (repo / "deploy/prod.yaml").symlink_to("../config/live.yaml")
            (repo / "links").symlink_to("deploy")
            refused("Edit", "file_path", repo / "links/prod.yaml",
                    "`deploy/prod.yaml` is a key file")
        with self.subTest(case="directory symlink inside the checkout"):
            repo = self.make_repo(f"git@github.com:{PROD}.git")
            (repo / "notebooks").mkdir()
            (repo / "ops").symlink_to("notebooks")
            refused("NotebookEdit", "notebook_path", repo / "ops/runbook.ipynb",
                    "(key file glob ops/runbook.ipynb)")
        with self.subTest(case="glob matches exactly"):
            repo = self.make_repo(f"git@github.com:{PROD}.git")
            refused("Write", "file_path", repo / "deploy/A.yaml",
                    "(key file glob deploy/[!a].yaml)", args=glob_args)

    def test_a_file_a_project_did_not_declare_is_written_freely(self):
        guard_args = self.tool_args(self.tool_rows())
        glob_args = self.tool_args({PROD: {**PROD_ROW, "production": {
            **TOOL_PRODUCTION, "key_files": ["deploy/[!a].yaml"]}}})
        bare_args = self.tool_args({PROD: PROD_ROW})
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        other = self.make_repo("git@github.com:fagenorn/tool.git")
        outside = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        for tool, field in EDIT_TOOLS:
            for name, path, args in (
                    ("undeclared file", prod / "README.md", guard_args),
                    ("near miss", prod / "deploy.yaml", guard_args),
                    ("another checkout", other / "deploy/prod.yaml", guard_args),
                    ("outside any checkout", outside / "deploy/prod.yaml", guard_args),
                    ("no cwd", "deploy/prod.yaml", guard_args),
                    ("no key files", prod / "deploy/prod.yaml", bare_args),
                    ("exact glob", prod / "deploy/a.yaml", glob_args)):
                with self.subTest(tool=tool, case=name):
                    result = self.run_tool(tool, {field: str(path)}, guard_args=args)
                    self.assertEqual(0, result.returncode, result.stderr)

    def test_a_declared_production_mcp_tool_is_refused_wherever_it_is_called(self):
        guard_args = self.tool_args(self.tool_rows())
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        other = self.make_repo("git@github.com:fagenorn/tool.git")
        for name, cwd in (("declaring cwd", prod), ("other cwd", other), ("no cwd", None)):
            with self.subTest(case=name):
                result = self.run_tool(MCP_APPLY, {}, cwd=cwd, guard_args=guard_args)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn(f"changes the production of {PROD} (production MCP tool)",
                              result.stderr)
        # File order lists acme/deployer first; the refusal names the slug that sorts first.
        both = self.tool_args({PROD: TOOL_ROW, "acme/alpha": TOOL_ROW})
        result = self.run_tool(MCP_APPLY, {}, cwd=other, guard_args=both)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("changes the production of acme/alpha (production MCP tool)",
                      result.stderr)
        self.assertNotIn("acme/deployer", result.stderr)

    def test_an_mcp_tool_not_declared_as_changing_passes(self):
        guard_args = self.tool_args(self.tool_rows())
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        for name in ("mcp__deployer__status", "mcp__other__apply", "mcp__deployer__apply_all",
                     "mcp__plugin_x_deployer__apply"):
            with self.subTest(tool=name):
                result = self.run_tool(name, {}, cwd=prod, guard_args=guard_args)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_a_bad_compiled_policy_blocks_no_edit_and_no_mcp_call(self):
        """AC3: a compiled policy that does not load never refuses a tool call."""
        held = Path(self.fixture_dir.name)
        broken = held / "broken-tools.json"
        broken.write_text("{", encoding="utf-8")
        deep = held / "deep-tools.json"
        deep.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        policies = (
            ("missing", held / "absent-tools.json"), ("not json", broken),
            ("a bad row", self.write_policy(
                derived_repositories={PROD: TOOL_ROW, NODO: {**NODO_ROW, "owner": "x"}},
                derivation={})),
            ("a bad key file", self.write_policy(
                derived_repositories={PROD: {**PROD_ROW, "production": {
                    **TOOL_PRODUCTION, "key_files": [""]}}}, derivation={})),
            ("deeply nested", deep))
        for name, path in policies:
            args = ("--gh-bin", str(self.fake_gh), "--policy", str(path))
            for tool, field in EDIT_TOOLS:
                with self.subTest(policy=name, tool=tool):
                    result = self.run_tool(
                        tool, {field: str(prod / "deploy/prod.yaml")}, guard_args=args)
                    self.assertEqual(0, result.returncode, result.stderr)
            with self.subTest(policy=name, tool=MCP_APPLY):
                result = self.run_tool(MCP_APPLY, {}, guard_args=args)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_an_ordinary_edit_or_mcp_call_starts_no_child(self):
        log = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "git.log"
        logging_git = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "git"
        logging_git.write_text(
            f"#!/bin/sh\necho \"$*\" >> '{log}'\nexec '{self.base_policy['git_bin']}' \"$@\"\n",
            encoding="utf-8")
        logging_git.chmod(0o755)
        guard_args = (*self.tool_args(self.tool_rows()), "--git-bin", str(logging_git))
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        for tool, tool_input, code in (
                ("Edit", {"file_path": str(prod / "README.md")}, 0),
                ("Write", {"file_path": str(prod / "src/x.py")}, 0),
                ("mcp__other__x", {}, 0), (MCP_APPLY, {}, 2)):
            with self.subTest(tool=tool):
                result = self.run_tool(tool, tool_input, guard_args=guard_args)
                self.assertEqual(code, result.returncode, result.stderr)
                self.assertFalse(log.exists())
        result = self.run_tool("Edit", {"file_path": str(prod / "deploy/prod.yaml")},
                               guard_args=guard_args)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertTrue(log.exists())

    def test_a_key_file_write_is_refused_when_the_checkout_lookup_fails(self):
        slow = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "git"
        slow.write_text("#!/bin/sh\nexec sleep 3\n", encoding="utf-8")
        slow.chmod(0o755)
        guard_args = (*self.tool_args(self.tool_rows()), "--git-bin", str(slow),
                      "--child-timeout-seconds", "0.3")
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        result = self.run_tool("Edit", {"file_path": str(prod / "deploy/prod.yaml")},
                               guard_args=guard_args)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("repository lookup timed out", result.stderr)
        result = self.run_tool("Edit", {"file_path": str(prod / "README.md")},
                               guard_args=guard_args)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_a_key_file_write_is_refused_when_git_fails_without_naming_no_repository(self):
        """A nonzero `rev-parse` that is not git's "not a git repository" (dubious ownership,
        a malformed config) is a failed lookup, never an outside-a-checkout answer."""
        guard_args_base = self.tool_args(self.tool_rows())
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        real = self.base_policy["git_bin"]
        for label, stderr in (
                ("dubious ownership", "fatal: detected dubious ownership in repository"),
                ("malformed config", "fatal: bad config line 1 in file .git/config")):
            with self.subTest(label=label):
                failing = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "git"
                failing.write_text(
                    "#!/bin/sh\ncase \"$*\" in\n"
                    f"  *rev-parse*) echo '{stderr}' >&2; exit 128;;\nesac\n"
                    f"exec '{real}' \"$@\"\n", encoding="utf-8")
                failing.chmod(0o755)
                args = (*guard_args_base, "--git-bin", str(failing))
                result = self.run_tool("Edit", {"file_path": str(prod / "deploy/prod.yaml")},
                                       guard_args=args)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("repository lookup failed (exit 128)", result.stderr)
                result = self.run_tool("Edit", {"file_path": str(prod / "README.md")},
                                       guard_args=args)
                self.assertEqual(0, result.returncode, result.stderr)
        with self.subTest(label="a directory in no checkout"):
            bare = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
            result = self.run_tool("Edit", {"file_path": str(bare / "deploy/prod.yaml")},
                                   guard_args=guard_args_base)
            self.assertEqual(0, result.returncode, result.stderr)

    def test_a_key_file_behind_a_directory_symlink_leaving_the_checkout_is_refused(self):
        guard_args = self.tool_args(self.tool_rows())
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        outside = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        (prod / "deploy").symlink_to(outside, target_is_directory=True)
        for tool, field in EDIT_TOOLS:
            with self.subTest(tool=tool):
                result = self.run_tool(tool, {field: str(prod / "deploy/prod.yaml")},
                                       guard_args=guard_args)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn(f"`deploy/prod.yaml` is a key file of {PROD}", result.stderr)

    def test_the_base_policy_is_read_only_for_a_key_file_candidate(self):
        broken = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "base.json"
        broken.write_text("{", encoding="utf-8")
        guard_args = (*self.tool_args(self.tool_rows()), "--base-policy", str(broken))
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        result = self.run_tool("Edit", {"file_path": str(prod / "README.md")},
                               guard_args=guard_args)
        self.assertEqual(0, result.returncode, result.stderr)
        result = self.run_tool(MCP_APPLY, {}, guard_args=guard_args)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("(production MCP tool)", result.stderr)
        result = self.run_tool("Edit", {"file_path": str(prod / "deploy/prod.yaml")},
                               guard_args=guard_args)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("lifecycle guard: invalid policy:", result.stderr)

    def test_the_key_file_and_mcp_refusals_are_one_sentence(self):
        guard_args = self.tool_args(self.tool_rows())
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        result = self.run_tool("Edit", {"file_path": str(prod / "deploy/prod.yaml")},
                               guard_args=guard_args)
        self.assertEqual(
            f"lifecycle guard: `deploy/prod.yaml` is a key file of {PROD} "
            "(key file glob deploy/*.yaml), so it changes only through the release profile "
            "forge-main with release transaction preview and release transaction run.\n",
            result.stderr)
        result = self.run_tool(MCP_APPLY, {}, guard_args=guard_args)
        self.assertEqual(
            f"lifecycle guard: `mcp__deployer__apply` changes the production of {PROD} "
            "(production MCP tool), so it runs only through the release profile "
            "forge-main with release transaction preview and release transaction run.\n",
            result.stderr)

    def test_a_compiled_key_file_and_mcp_tool_round_trip_through_the_guard(self):
        """The issue's demo: the compiler's row drives the refusals."""
        def declare(contract):
            contract["production"] = {
                "none": False,
                "changes": {"commands": ["nix-activate"], "key_files": ["deploy/*.yaml"],
                            "mcp_tools": ["mcp__deployer__apply"]},
                "read_only": {"commands": ["nix-build"],
                              "mcp_tools": ["mcp__deployer__status"]},
                "release_profile": "github-release"}

        world = GuardPolicyWorld(self)
        world.project("fixture/prodfix", "fagenorn/prodfix", mutate=declare)
        code, report, stderr = world.compile(base=BASE_POLICY_PATH)
        self.assertEqual((0, ["fagenorn/prodfix"]), (code, report["derived"]), stderr)
        repo = self.make_repo("git@github.com:fagenorn/prodfix.git")
        guard_args = ("--gh-bin", str(self.fake_gh), "--policy", str(world.output),
                      "--derive-bin", str(world.row_check()))
        refused = self.invoke_raw(json.dumps({
            "tool_name": "Edit", "tool_input": {"file_path": str(repo / "deploy/prod.yaml")}}),
            *guard_args, timeout=60)
        self.assertEqual(2, refused.returncode, refused.stderr)
        self.assertEqual(
            "lifecycle guard: `deploy/prod.yaml` is a key file of fagenorn/prodfix "
            "(key file glob deploy/*.yaml), so it changes only through the release profile "
            "github-release with release transaction preview and release transaction run.\n",
            refused.stderr)
        refused = self.invoke_raw(json.dumps({"tool_name": MCP_APPLY, "tool_input": {}}),
                                  *guard_args, timeout=60)
        self.assertEqual(2, refused.returncode, refused.stderr)
        self.assertIn("fagenorn/prodfix", refused.stderr)
        for tool, tool_input in (("mcp__deployer__status", {}),
                                 ("Edit", {"file_path": str(repo / "README.md")})):
            with self.subTest(tool=tool):
                allowed = self.invoke_raw(
                    json.dumps({"tool_name": tool, "tool_input": tool_input}),
                    *guard_args, timeout=60)
                self.assertEqual(0, allowed.returncode, allowed.stderr)

    def test_a_key_file_differing_only_in_case_follows_the_file_system(self):
        guard_args = self.tool_args(self.tool_rows())
        prod = self.make_repo(f"git@github.com:{PROD}.git")
        (prod / "deploy").mkdir()
        (prod / "deploy/prod.yaml").write_text("x", encoding="utf-8")
        probe = Path(self.fixture_dir.name) / "CaseProbe"
        probe.write_text("x", encoding="utf-8")
        insensitive = Path(self.fixture_dir.name, "caseprobe").exists()
        first = self.run_tool("Edit", {"file_path": str(prod / "DEPLOY/Prod.YAML")},
                              guard_args=guard_args)
        second = self.run_tool("Write", {"file_path": str(prod / "Deploy/new.yaml")},
                               guard_args=guard_args)
        if insensitive:
            self.assertEqual(2, first.returncode, first.stderr)
            self.assertIn(f"`deploy/prod.yaml` is a key file of {PROD}", first.stderr)
            self.assertEqual(2, second.returncode, second.stderr)
            self.assertIn(f"`deploy/new.yaml` is a key file of {PROD}", second.stderr)
        else:
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(0, second.returncode, second.stderr)

    # ------------------------------------------------------------------
    # Release arm: the declared integration branch promoted into the default
    # branch. Its head is permanent, so the merge omits `--delete-branch`, and
    # the guard demands exactly that PR shape plus a fully green rollup.
    # ------------------------------------------------------------------

    # The PR head commit a merge may pin (issue 402 D10), which must be the PR's
    # headRefOid (issue 476 D3): the fake gh's default head and RELEASE_PR's.
    HEAD_SHA = "d4d9acc0505c73305b3e0ced029db43100bc0e8a"
    # A well-spelled commit that is no fixture PR's head.
    OTHER_SHA = "0123456789abcdef0123456789abcdef01234567"

    RELEASE_PR = {
        "state": "OPEN",
        "baseRefName": "main",
        "headRefName": "dev",
        "headRefOid": HEAD_SHA,
        "mergeStateStatus": "CLEAN",
        "url": "https://github.com/elevenyellow/nodocom/pull/1484",
        "statusCheckRollup": [
            {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SKIPPED"},
            {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "NEUTRAL"},
            {"__typename": "StatusContext", "state": "SUCCESS"},
        ],
        "isCrossRepository": False,
    }

    def release_env(self, **overrides):
        pr = dict(self.RELEASE_PR)
        pr.update(overrides)
        # Protection is poisoned on purpose: the release arm must never consult it.
        return {"FAKE_PR_JSON": json.dumps(pr), "FAKE_PROTECTION_MODE": "nonzero"}

    def test_release_merge_omits_delete_branch_for_integration_into_default(self):
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        for command in (
            "gh pr merge 1484 --repo elevenyellow/nodocom --merge",
            "unset GITHUB_TOKEN && gh pr merge 1484 --repo elevenyellow/nodocom --merge",
            "unset GITHUB_TOKEN && gh pr merge 1484 --repo elevenyellow/nodocom --merge "
            '--subject "merge: dev — showcases, engine roll (dev → main)"',
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo, env=self.release_env())
                self.assertEqual(0, result.returncode, result.stderr)

    def test_release_merge_arm_requires_exactly_integration_into_default(self):
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 7 --repo elevenyellow/nodocom --merge"
        tail = "may be omitted only when merging dev into main; this PR merges {} into {}"
        for head, base, problem, forms in (
            # A feature branch into either base: the text refusal names the missing flag.
            ("issue-7-topic", "main", "missing --delete-branch: it " + tail, True),
            ("issue-7-topic", "dev", "missing --delete-branch: it " + tail, True),
            # A permanent head fits no arm: a state refusal, no accepted forms.
            ("main", "dev", "--delete-branch " + tail, False),
        ):
            with self.subTest(head=head, base=base):
                result = self.run_guard(
                    merge, cwd=repo, env=self.release_env(headRefName=head, baseRefName=base))
                self.assertEqual(2, result.returncode, result.stderr)
                line = self.refusal_line(result)
                self.assertTrue(
                    line.startswith("lifecycle guard: unsafe merge: " + problem.format(head, base)),
                    line)
                self.assertEqual(forms, "; accepted: " in line, line)
        # The feature arm is untouched: the same feature PR still merges into
        # the integration branch when it says --delete-branch.
        allowed = self.run_guard(
            merge + " --delete-branch", cwd=repo,
            env=self.release_env(headRefName="issue-7-topic", baseRefName="dev"))
        self.assertEqual(0, allowed.returncode, allowed.stderr)

    def test_release_merge_arm_needs_a_declared_integration_base(self):
        # Without a declared integration branch there is no permanent head to
        # spare; the arm is refused before any forge lookup (poisoned to prove it).
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "gh pr merge 1 --repo fagenorn/nix-config --merge",
            'gh pr merge 1 --repo fagenorn/nix-config --merge --subject "x"',
            "unset GITHUB_TOKEN && gh pr merge 1 --repo fagenorn/nix-config --merge",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo, env={"FAKE_PR_MODE": "nonzero"})
                self.assertEqual(2, result.returncode)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)
                self.assertIn("declared integration branch", result.stderr)

    def test_release_merge_arm_judges_each_check_by_its_latest_run(self):
        """Issue 1374: a superseded red run does not block the release arm, but a red or
        pending latest run, a tie and an unstamped run still do."""
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 1484 --repo elevenyellow/nodocom --merge"
        early, late = "2026-11-20T09:00:00Z", "2026-11-20T09:30:00Z"

        def run(name, conclusion, started=None, status="COMPLETED", workflow=None):
            entry = {"__typename": "CheckRun", "name": name, "status": status,
                     "conclusion": conclusion}
            if started is not None:
                entry["startedAt"] = started
            if workflow is not None:
                entry["workflowName"] = workflow
            return entry

        green = [{"__typename": "StatusContext", "context": "deploy", "state": "SUCCESS"}]
        for rollup in (
            [run("build", "FAILURE", early), run("build", "SUCCESS", late)] + green,
            [run("build", "SUCCESS", late), run("build", "CANCELLED", early)] + green,
            [run("build", None, early, "IN_PROGRESS"), run("build", "SUCCESS", late)] + green,
            [{"__typename": "StatusContext", "context": "deploy", "state": "FAILURE",
              "startedAt": early}, run("build", "SUCCESS", late),
             {"__typename": "StatusContext", "context": "deploy", "state": "SUCCESS",
              "startedAt": late}],
            [run("build", "FAILURE", early, workflow="ci"),
             run("build", "SUCCESS", late, workflow="ci")] + green,
        ):
            with self.subTest(admitted=rollup):
                result = self.run_guard(
                    merge, cwd=repo, env=self.release_env(statusCheckRollup=rollup))
                self.assertEqual(0, result.returncode, result.stderr)
        for rollup in (
            [run("build", "SUCCESS", early), run("build", "FAILURE", late)] + green,
            [run("build", "FAILURE", late), run("build", "SUCCESS", early)] + green,
            [run("build", "SUCCESS", early), run("build", None, late, "IN_PROGRESS")] + green,
            [run("build", "FAILURE", late), run("build", "SUCCESS", late)] + green,
            [run("build", "FAILURE"), run("build", "SUCCESS", late)] + green,
            [run("build", "FAILURE", "yesterday"), run("build", "SUCCESS", late)] + green,
            [run("build", "FAILURE", early), run("build", "SUCCESS", "yesterday")] + green,
            [run("build", "FAILURE", early), run("build", "SUCCESS", late),
             run("lint", "FAILURE", early)] + green,
            # A queued re-run: gh exports a run not yet started with the zero time.
            [run("build", "SUCCESS", early),
             run("build", None, "0001-01-01T00:00:00Z", "QUEUED")] + green,
            [run("build", "SUCCESS", early),
             run("build", "", "0001-01-01T00:00:00Z", "QUEUED")] + green,
            # Two workflows publishing one check name never supersede each other.
            [run("build", "FAILURE", early, workflow="ci"),
             run("build", "SUCCESS", late, workflow="nightly")] + green,
            [run("build", "SUCCESS", late, workflow="nightly"),
             run("build", "FAILURE", early, workflow="ci")] + green,
            # An impossible calendar date is unreadable, so it supersedes nothing.
            [run("build", "FAILURE", early), run("build", "SUCCESS", "2026-99-01T00:00:00Z")]
            + green,
            [run("build", "FAILURE", early), run("build", "SUCCESS", "2026-02-30T00:00:00Z")]
            + green,
        ):
            with self.subTest(refused=rollup):
                result = self.run_guard(
                    merge, cwd=repo, env=self.release_env(statusCheckRollup=rollup))
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("check rollup is not entirely green", result.stderr)

    def test_release_merge_arm_blocks_unless_every_check_is_green(self):
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 1484 --repo elevenyellow/nodocom --merge"
        green = self.RELEASE_PR["statusCheckRollup"]
        for rollup in (
            [],
            None,
            "green",
            [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}],
            [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "CANCELLED"}],
            [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "TIMED_OUT"}],
            [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}],
            [{"__typename": "StatusContext", "state": "PENDING"}],
            [{"__typename": "StatusContext", "state": "FAILURE"}],
            green + [{"__typename": "CheckRun", "status": "QUEUED", "conclusion": None}],
        ):
            with self.subTest(rollup=rollup):
                result = self.run_guard(
                    merge, cwd=repo, env=self.release_env(statusCheckRollup=rollup))
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("check rollup is not entirely green", result.stderr)
        absent = dict(self.RELEASE_PR)
        del absent["statusCheckRollup"]
        result = self.run_guard(
            merge, cwd=repo,
            env={"FAKE_PR_JSON": json.dumps(absent), "FAKE_PROTECTION_MODE": "nonzero"})
        self.assertEqual(2, result.returncode)
        self.assertIn("check rollup is not entirely green", result.stderr)

    def test_release_merge_arm_keeps_the_open_pr_predicate(self):
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 1484 --repo elevenyellow/nodocom --merge"
        for overrides in (
            {"state": "MERGED"},
            {"url": "https://github.com/other/repo/pull/1484"},
        ):
            with self.subTest(overrides=overrides):
                result = self.run_guard(merge, cwd=repo, env=self.release_env(**overrides))
                self.assertEqual(2, result.returncode)
                self.assertIn("PR predicate failed", result.stderr)

    def test_merge_takes_an_optional_head_commit_flag(self):
        """Issue 402 AC1, D10: `--match-head-commit <40 lowercase hex>` stands after
        `--subject` and before `--delete-branch`, optional in both arms."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        sha = self.HEAD_SHA
        merge = "gh pr merge 2342 --repo fagenorn/nix-config --merge"
        feature_into_dev = {"FAKE_PR_JSON": json.dumps({
            "state": "OPEN", "baseRefName": "dev", "headRefName": "issue-2342-topic",
            "headRefOid": sha, "mergeStateStatus": "CLEAN",
            "url": f"https://github.com/{NODO}/pull/2342", "statusCheckRollup": []})}
        for command, cwd, env in (
            (f"{merge} --match-head-commit {sha} --delete-branch", repo, None),
            (f'{merge} --subject "feature (#402)" --match-head-commit {sha} --delete-branch',
             repo, None),
            (f"unset GITHUB_TOKEN && {merge} --match-head-commit {sha} --delete-branch",
             repo, None),
            (f"env -u GITHUB_TOKEN {merge} --match-head-commit {sha} --delete-branch",
             repo, None),
            (f"gh pr merge 2342 --repo {NODO} --merge --match-head-commit {sha} --delete-branch",
             nodo, feature_into_dev),
            (f"gh pr merge 1484 --repo {NODO} --merge --match-head-commit {sha}",
             nodo, self.release_env()),
            (f'gh pr merge 1484 --repo {NODO} --merge --subject "merge: dev (dev → main)" '
             f"--match-head-commit {sha}", nodo, self.release_env()),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=cwd, env=env)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        for command in (
            f"{merge} --match-head-commit {sha[:39]} --delete-branch",           # 39 characters
            f"{merge} --match-head-commit {sha}0 --delete-branch",               # 41 characters
            f"{merge} --match-head-commit {sha.upper()} --delete-branch",        # uppercase
            f"{merge} --match-head-commit={sha} --delete-branch",                # attached value
            f'{merge} --match-head-commit {sha} --subject "x" --delete-branch',  # before --subject
            f"{merge} --delete-branch --match-head-commit {sha}",                # after --delete-branch
            f"{merge} --match-head-commit --delete-branch",                      # no value
            f"{merge} --match-head-commit {sha} {sha} --delete-branch",          # two values
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)

    def test_prefixed_merge_near_misses_fail_closed(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        merge = "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch"
        for command in (
            f"unset PATH && {merge}",                               # wrong variable
            f"unset GITHUB_TOKEN; {merge}",                         # wrong separator
            f"unset GITHUB_TOKEN &&{merge}",                        # missing space
            f"unset  GITHUB_TOKEN && {merge}",                      # doubled space
            f"unset GITHUB_TOKEN && unset GITHUB_TOKEN && {merge}", # doubled prefix
            f"unset GITHUB_TOKEN && {merge} && true",               # trailing chain
            f"true && unset GITHUB_TOKEN && {merge}",               # leading chain
            f"FOO=bar unset GITHUB_TOKEN && {merge}",               # leading assignment
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn("lifecycle guard: unsafe merge:", result.stderr)

    def test_credential_scrub_prefix_forms_and_wrapper_near_misses(self):
        """Issue 400 AC1, D1, D13: either scrub-prefix spelling reaches every verb's
        grammar; any other wrapper reaches the grammar too and is refused there."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        push = "git push origin issue-400-topic"
        merge = "gh pr merge 2342 --repo fagenorn/nix-config --merge --delete-branch"
        create = ('gh pr create --repo fagenorn/nix-config --base main '
                  '--head issue-400-topic --title "x" --body "y"')
        release = ('gh release create v1.2.3 --repo fagenorn/nix-config --verify-tag '
                   '--title "v1.2.3" --notes-file /tmp/n.md')
        for command in (
            f"env -u GITHUB_TOKEN {push}",
            "unset GH_TOKEN && git push -u origin issue-400-topic",
            f"env -u GITHUB_TOKEN {merge}",
            f"env -u GH_TOKEN {merge}",
            f"env -u GITHUB_TOKEN -u GH_TOKEN {merge}",
            f"unset GITHUB_TOKEN GH_TOKEN && {merge}",
            f"unset GH_TOKEN GITHUB_TOKEN && {merge}",
            f"env -u GH_TOKEN -u GITHUB_TOKEN {push}",
            f"env -u GITHUB_TOKEN {create}",
            f"env -u GITHUB_TOKEN {release}",
            f"unset GH_TOKEN && {release}",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        prefix = "unaccepted credential-scrub prefix"
        # The allowlist grammar (issue 418) refuses every wrapper other than one
        # scrub spelling before the verb's own grammar reads it.
        before = "before the verb; " + GRAMMAR
        for command, reason in (
            (f"true && env -u GH_TOKEN {push}", f"unsafe push: `true &&` {before}"),
            (f"env -u PATH {push}", f"unsafe push: `env -u PATH` {before}"),
            (f"env FOO=1 {push}", f"unsafe push: `env FOO=1` {before}"),
            (f"env -i {push}", f"unsafe push: `env -i` {before}"),
            (f"env -u GITHUB_TOKEN -i {push}", f"unsafe push: `-i` {before}"),
            (f"env --unset=GITHUB_TOKEN {push}",
             f"unsafe push: `env --unset=GITHUB_TOKEN` {before}"),
            (f"sudo -u x {push}", f"unsafe push: `sudo -u x` {before}"),
            (f"env -u GITHUB_TOKEN -u GITHUB_TOKEN {push}",   # repeated name
             f"unsafe push: `-u GITHUB_TOKEN` {before}"),
            (f"env -uGITHUB_TOKEN {push}",                    # attached
             f"unsafe push: `env -uGITHUB_TOKEN` {before}"),
            (f"env -u GITHUB_TOKEN -- {push}", f"unsafe push: `--` {before}"),
            (f"env env -u GITHUB_TOKEN {push}",               # second env
             f"unsafe push: `env env -u GITHUB_TOKEN` {before}"),
            (f"env -u GITHUB_TOKEN env {push}", f"unsafe push: `env` {before}"),
            (f"env -u GITHUB_TOKEN  {push}",                  # double space
             f"unsafe push: {prefix} `env -u GITHUB_TOKEN` (doubled space)"),
            (f"env -u GITHUB_TOKEN {merge}; echo x",
             f"unsafe merge: `;` outside quotes; {GRAMMAR}"),
            (f"env -u GITHUB_TOKEN -u GITHUB_TOKEN {merge}",
             f"unsafe merge: `-u GITHUB_TOKEN` {before}"),
            (f"unset GITHUB_TOKEN GITHUB_TOKEN && {merge}",
             f"unsafe merge: `unset GITHUB_TOKEN GITHUB_TOKEN &&` {before}"),
            (f"env  -u GITHUB_TOKEN {merge}",
             f"unsafe merge: {prefix} `env -u GITHUB_TOKEN` (doubled space)"),
            (f"env -u GITHUB_TOKEN  {merge}",
             f"unsafe merge: {prefix} `env -u GITHUB_TOKEN` (doubled space)"),
            ("env -u GITHUB_TOKEN git branch -d issue-400-topic",
             "unsafe branch deletion: branch deletion takes no credential-scrub prefix"),
            ("unset GITHUB_TOKEN && git branch -d issue-400-topic",
             "unsafe branch deletion: branch deletion takes no credential-scrub prefix"),
            # The wrapper's option argument is consumed, so `sh` is the command word.
            ("sudo -u root sh -c 'git push origin issue-400-topic'",
             f"unsafe push: `sudo -u root` is not a lifecycle verb; {GRAMMAR}"),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: {reason}", result.stderr)

    def test_merge_lookups_drop_env_github_tokens(self):
        # Deterministic version of the fake gh's env check: inject both tokens
        # into the guard's own environment and require acceptance anyway.
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        result = self.run_guard(
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch",
            cwd=repo,
            env={"GITHUB_TOKEN": "github_pat_fake", "GH_TOKEN": "gho_fake"},
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_safe_rendered_subject_can_reach_acceptance(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for subject in ("feature (#30) [guarded]*?~", "git branch -d"):
            with self.subTest(subject=subject):
                result = self.run_guard(
                    "gh pr merge 1 --repo fagenorn/nix-config --merge "
                    f'--subject "{subject}" --delete-branch',
                    cwd=repo,
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_unexpected_dependency_exception_blocks(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        missing_jq = Path(self.fixture_dir.name) / "missing-jq"
        result = self.run_guard(
            "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch",
            cwd=repo,
            guard_args=(
                "--gh-bin", str(self.fake_gh), "--jq-bin", str(missing_jq),
                "--child-timeout-seconds", "0.5",
            ),
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("lifecycle guard: unexpected failure:", result.stderr)

    # ------------------------------------------------------------------
    # Mergeability (issue 476): each merge arm, after its own shape judgment
    # and before its first gate, refuses a PR behind its base and then a
    # --match-head-commit that is not the PR's head commit.
    # ------------------------------------------------------------------

    BEHIND = ("the PR is behind its base {base}; repair: sync the branch with {base}, "
              "push it and wait for its required checks before merging")

    def mergeability_paths(self):
        """The three paths the check binds (issue 476 D1), each (name, cwd, command, facts,
        env): `command` takes the optional `--match-head-commit` group through `{pin}`,
        and `facts` is a PR payload every check passes."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        clean = {"headRefOid": self.HEAD_SHA, "mergeStateStatus": "CLEAN"}
        return (
            ("feature into main", repo,
             "gh pr merge 1 --repo fagenorn/nix-config --merge{pin} --delete-branch",
             {"state": "OPEN", "baseRefName": "main", "headRefName": "issue-1-topic",
              "url": "https://github.com/fagenorn/nix-config/pull/1", **clean}, {}),
            ("feature into dev", nodo,
             f"gh pr merge 7 --repo {NODO} --merge{{pin}} --delete-branch",
             {"state": "OPEN", "baseRefName": "dev", "headRefName": "issue-7-topic",
              "url": f"https://github.com/{NODO}/pull/7", **clean},
             {"FAKE_PROTECTION_MODE": "nonzero"}),
            ("release", nodo, f"gh pr merge 1484 --repo {NODO} --merge{{pin}}",
             dict(self.RELEASE_PR), {"FAKE_PROTECTION_MODE": "nonzero"}),
        )

    def test_a_wrong_head_commit_is_refused_naming_the_pr_head(self):
        """Issue 476 AC1, D3, D5: on every path the check binds, a --match-head-commit
        that is not the PR's headRefOid is refused with the actual head; the PR's own head
        passes."""
        for name, cwd, command, facts, env in self.mergeability_paths():
            env = {**env, "FAKE_PR_JSON": json.dumps(facts)}
            with self.subTest(path=name, pin="the PR head"):
                result = self.run_guard(
                    command.format(pin=f" --match-head-commit {self.HEAD_SHA}"), cwd=cwd, env=env)
                self.assertEqual(0, result.returncode, result.stderr)
            with self.subTest(path=name, pin="another commit"):
                line = self.refusal_line(self.run_guard(
                    command.format(pin=f" --match-head-commit {self.OTHER_SHA}"), cwd=cwd,
                    env=env))
                self.assertEqual(
                    f"lifecycle guard: unsafe merge: --match-head-commit {self.OTHER_SHA} is not "
                    f"the PR head commit {self.HEAD_SHA}; merge only a head you reviewed", line)

    def test_a_pr_behind_its_base_is_refused_naming_the_sync(self):
        """Issue 476 AC2, D1, D2, D5: on every path the check binds, a BEHIND PR is refused
        with the sync recovery, ahead of the head comparison; other merge states pass."""
        for name, cwd, command, facts, env in self.mergeability_paths():
            behind = {**env, "FAKE_PR_JSON": json.dumps({**facts, "mergeStateStatus": "BEHIND"})}
            for pin in ("", f" --match-head-commit {self.HEAD_SHA}",
                        f" --match-head-commit {self.OTHER_SHA}"):
                with self.subTest(path=name, pin=pin):
                    line = self.refusal_line(self.run_guard(
                        command.format(pin=pin), cwd=cwd, env=behind))
                    self.assertEqual("lifecycle guard: unsafe merge: "
                                     + self.BEHIND.format(base=facts["baseRefName"]), line)
            for state in ("UNKNOWN", "BLOCKED", "DIRTY", "UNSTABLE"):
                with self.subTest(path=name, state=state):
                    result = self.run_guard(
                        command.format(pin=f" --match-head-commit {self.HEAD_SHA}"), cwd=cwd,
                        env={**env, "FAKE_PR_JSON": json.dumps(
                            {**facts, "mergeStateStatus": state})})
                    self.assertEqual(0, result.returncode, result.stderr)

    def test_an_arm_refusal_comes_before_the_mergeability_check(self):
        """Issue 476 D1: a PR whose head no arm admits keeps its arm refusal, whatever its
        merge state and head commit."""
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        env = {"FAKE_PROTECTION_MODE": "nonzero", "FAKE_PR_JSON": json.dumps({
            "state": "OPEN", "baseRefName": "dev", "headRefName": "main",
            "headRefOid": self.HEAD_SHA, "mergeStateStatus": "BEHIND",
            "url": f"https://github.com/{NODO}/pull/7", "statusCheckRollup": []})}
        merge = f"gh pr merge 7 --repo {NODO} --merge --match-head-commit {self.OTHER_SHA}"
        for command, problem in (
            (merge + " --delete-branch", "--delete-branch would delete the permanent branch main"),
            (merge, "--delete-branch may be omitted only when merging dev into main; this PR "
                    "merges main into dev"),
        ):
            with self.subTest(command=command):
                line = self.refusal_line(self.run_guard(command, cwd=nodo, env=env))
                self.assertEqual(f"lifecycle guard: unsafe merge: {problem}", line)

    def test_the_release_mergeability_check_precedes_the_rollup_predicate(self):
        """Issue 476 D1 (Phase-5 review PR476-S1): on the release arm the mergeability
        refusal wins over a rollup that is not entirely green."""
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        failing = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]
        merge = f"gh pr merge 1484 --repo {NODO} --merge"
        for label, rollup in (("empty", []), ("failing", failing)):
            for check, command, change, problem in (
                ("behind", merge, {"mergeStateStatus": "BEHIND"},
                 self.BEHIND.format(base="main")),
                ("wrong head", f"{merge} --match-head-commit {self.OTHER_SHA}", {},
                 f"--match-head-commit {self.OTHER_SHA} is not the PR head commit "
                 f"{self.HEAD_SHA}; merge only a head you reviewed"),
            ):
                with self.subTest(rollup=label, check=check):
                    line = self.refusal_line(self.run_guard(command, cwd=nodo, env=self.release_env(
                        statusCheckRollup=rollup, **change)))
                    self.assertEqual(f"lifecycle guard: unsafe merge: {problem}", line)

    def test_an_unreadable_merge_state_or_head_commit_is_refused(self):
        """Issue 476 D4: a fact the check needs and cannot read fails closed; without
        --match-head-commit the head commit is neither read nor demanded."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        merge = "gh pr merge 1 --repo fagenorn/nix-config --merge"
        bare = f"{merge} --delete-branch"
        pinned = f"{merge} --match-head-commit {self.HEAD_SHA} --delete-branch"
        facts = {"state": "OPEN", "baseRefName": "main", "headRefName": "issue-1-topic",
                 "headRefOid": self.HEAD_SHA, "mergeStateStatus": "CLEAN",
                 "url": "https://github.com/fagenorn/nix-config/pull/1"}

        def env(**change):
            payload = {key: value for key, value in {**facts, **change}.items()
                       if value is not ABSENT}
            return {"FAKE_PR_JSON": json.dumps(payload)}

        state, head = "cannot read the PR merge state", "cannot read the PR head commit"
        for label, command, change, problem in (
            ("state missing", pinned, {"mergeStateStatus": ABSENT}, state),
            ("state null", bare, {"mergeStateStatus": None}, state),
            ("state number", bare, {"mergeStateStatus": 7}, state),
            ("state empty", bare, {"mergeStateStatus": ""}, state),
            ("head missing", pinned, {"headRefOid": ABSENT}, head),
            ("head null", pinned, {"headRefOid": None}, head),
            ("head short", pinned, {"headRefOid": self.HEAD_SHA[:7]}, head),
            ("head uppercase", pinned, {"headRefOid": self.HEAD_SHA.upper()}, head),
        ):
            with self.subTest(fact=label):
                line = self.refusal_line(self.run_guard(command, cwd=repo, env=env(**change)))
                self.assertEqual(f"lifecycle guard: unsafe merge: {problem}", line)
        for label, change in (("missing", {"headRefOid": ABSENT}),
                              ("short", {"headRefOid": self.HEAD_SHA[:7]})):
            with self.subTest(head=label, pin="none"):
                result = self.run_guard(bare, cwd=repo, env=env(**change))
                self.assertEqual(0, result.returncode, result.stderr)

    # ------------------------------------------------------------------
    # The plan-gated merge floor (issue 552): a feature merge into the default
    # branch of a repository whose forge cannot protect it is judged on the PR's
    # own rollup against the checks its confirmed derived row declares.
    # ------------------------------------------------------------------

    PLAN_GATED_MESSAGE = ("Upgrade to GitHub Pro or make this repository public to enable "
                          "this feature.")
    FLOOR = "acme/floor"
    STAGED = "acme/staged"
    BUILD = "CI / build (unit + forced)"
    LINT = "lint"
    FLOOR_ROWS = {
        FLOOR: {"default_branch": "main", "integration_branch": "main",
                "required_checks": [BUILD, LINT], "evidence": {}},
        STAGED: {"default_branch": "main", "integration_branch": "dev",
                 "required_checks": [BUILD, LINT], "evidence": {}},
    }
    UNPROTECTED = ("lifecycle guard: unsafe merge: main cannot be protected on this "
                   "repository's plan")
    LOOKUP_FAILED = "lifecycle guard: protection lookup failed: stderr="

    @staticmethod
    def check_run(name, status="COMPLETED", conclusion="SUCCESS", started=None,
                  workflow=None):
        entry = {"__typename": "CheckRun", "name": name, "status": status,
                 "conclusion": conclusion}
        if started is not None:
            entry["startedAt"] = started
        if workflow is not None:
            entry["workflowName"] = workflow
        return entry

    @staticmethod
    def status_context(context, state="SUCCESS", started=None):
        entry = {"__typename": "StatusContext", "context": context, "state": state}
        if started is not None:
            entry["startedAt"] = started
        return entry

    def floor_merge(self, rollup, slug=None, base="main", pin=True, rows=None, env=None,
                    guard_args=()):
        """A feature merge of PR 9 into `base` of `slug` (FLOOR) whose rollup is `rollup`
        (ABSENT drops the member), judged by the rows of `rows` (FLOOR_ROWS) as compiled and
        confirmed, against the plan-gated protection answer unless `env` replaces it."""
        slug = slug or self.FLOOR
        rows = self.FLOOR_ROWS if rows is None else rows
        policy = self.write_policy(derivation={}, derived_repositories=rows)
        facts = {"state": "OPEN", "baseRefName": base, "headRefName": "issue-9-topic",
                 "headRefOid": self.HEAD_SHA, "mergeStateStatus": "CLEAN",
                 "url": f"https://github.com/{slug}/pull/9", "statusCheckRollup": rollup}
        if rollup is ABSENT:
            del facts["statusCheckRollup"]
        pinned = f" --match-head-commit {self.HEAD_SHA}" if pin else ""
        return self.run_guard(
            f"gh pr merge 9 --repo {slug} --merge{pinned} --delete-branch",
            cwd=self.make_repo(f"git@github.com:{slug}.git"),
            guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(policy), *guard_args),
            env={**self.rows_env(rows), "FAKE_PROTECTION_MODE": "http_error",
                 "FAKE_PR_JSON": json.dumps(facts), **(env or {})})

    def test_the_floor_allows_a_merge_whose_declared_checks_are_green(self):
        """Issue 552 D2, D3: every declared check named and green allows the merge;
        SKIPPED and NEUTRAL count, so does a green StatusContext, and an entry naming no
        declared check is ignored."""
        for rollup in (
            [self.check_run(self.BUILD), self.check_run(self.LINT)],
            [self.check_run(self.BUILD, conclusion="SKIPPED"), self.status_context(self.LINT)],
            [self.check_run("optional", conclusion="FAILURE"),
             self.check_run(self.BUILD, conclusion="NEUTRAL"),
             self.status_context("deploy", state="PENDING"), self.check_run(self.LINT)],
        ):
            with self.subTest(rollup=rollup):
                result = self.floor_merge(rollup)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_the_floor_refuses_naming_its_first_failure(self):
        """Issue 552 D3, D7, D11, D12: the head flag, then a readable rollup, then each
        declared check in row order; each refusal names only its problem."""
        build, lint = self.check_run(self.BUILD), self.status_context(self.LINT)
        missing = f"{self.UNPROTECTED}, and the declared required check {self.BUILD} is missing "
        not_green = f"{self.UNPROTECTED}, and the declared required check {{}} is not green ({{}})"
        unreadable = "lifecycle guard: unsafe merge: cannot read the PR check rollup"
        cases = (
            ("no head flag", [build, lint], False, f"{self.UNPROTECTED}, so the merge must "
             "carry --match-head-commit with the reviewed PR head"),
            ("missing", [lint], True, missing + "from the PR's check rollup"),
            ("empty", [], True, missing + "from the PR's check rollup"),
            ("pending", [self.check_run(self.BUILD, "IN_PROGRESS", None), lint], True,
             not_green.format(self.BUILD, "CheckRun IN_PROGRESS/none")),
            ("no conclusion", [{"__typename": "CheckRun", "name": self.BUILD,
                                "status": "QUEUED"}, lint], True,
             not_green.format(self.BUILD, "CheckRun QUEUED/none")),
            ("failed", [self.check_run(self.BUILD, conclusion="FAILURE"), lint], True,
             not_green.format(self.BUILD, "CheckRun COMPLETED/FAILURE")),
            ("pending status", [build, self.status_context(self.LINT, "PENDING")], True,
             not_green.format(self.LINT, "StatusContext PENDING")),
            ("red duplicate", [build, self.check_run(self.BUILD, conclusion="CANCELLED"), lint],
             True, not_green.format(self.BUILD, "CheckRun COMPLETED/CANCELLED")),
            ("row order", [self.status_context(self.LINT, "FAILURE"),
                           self.check_run(self.BUILD, conclusion="FAILURE")], True,
             not_green.format(self.BUILD, "CheckRun COMPLETED/FAILURE")),
            ("escaped", [self.check_run(self.BUILD, "IN\nPROGRESS", None), lint], True,
             not_green.format(self.BUILD, "CheckRun IN\\nPROGRESS/none")),
            ("absent", ABSENT, True, unreadable),
            ("null", None, True, unreadable),
            ("a string", "green", True, unreadable),
            ("an entry that is not an object", [build, self.LINT], True, unreadable),
            ("a CheckRun without a name", [build, lint, {"__typename": "CheckRun",
                                                         "status": "COMPLETED",
                                                         "conclusion": "SUCCESS"}], True,
             unreadable),
            ("a StatusContext without a context", [build, lint, {
                "__typename": "StatusContext", "state": "SUCCESS"}], True, unreadable),
            ("a name that is not a string", [build, lint, self.check_run(7)], True, unreadable),
            ("another typename", [build, lint, {"__typename": "Commit", "name": self.LINT}],
             True, unreadable),
        )
        for name, rollup, pin, line in cases:
            with self.subTest(case=name):
                self.assertEqual(line, self.refusal_line(self.floor_merge(rollup, pin=pin)))

    EARLY = "2026-11-20T09:00:00Z"
    LATE = "2026-11-20T09:30:00Z"

    def test_the_floor_judges_each_declared_check_by_its_latest_run(self):
        """Issue 1374: a failed run a later run of the same check superseded does not
        refuse, whichever order the rollup lists them in, and a status context is judged
        the same way."""
        lint = self.status_context(self.LINT)
        for name, rollup in (
            ("failed then green", [
                self.check_run(self.BUILD, conclusion="FAILURE", started=self.EARLY),
                self.check_run(self.BUILD, started=self.LATE), lint]),
            ("green listed first", [
                self.check_run(self.BUILD, started=self.LATE),
                self.check_run(self.BUILD, conclusion="CANCELLED", started=self.EARLY), lint]),
            ("pending then green", [
                self.check_run(self.BUILD, "IN_PROGRESS", None, started=self.EARLY),
                self.check_run(self.BUILD, started=self.LATE), lint]),
            ("status context", [
                self.check_run(self.BUILD),
                self.status_context(self.LINT, "FAILURE", started=self.EARLY),
                self.status_context(self.LINT, started=self.LATE)]),
            ("same workflow", [
                self.check_run(self.BUILD, conclusion="FAILURE", started=self.EARLY,
                               workflow="ci"),
                self.check_run(self.BUILD, started=self.LATE, workflow="ci"), lint]),
        ):
            with self.subTest(case=name):
                result = self.floor_merge(rollup)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_the_floor_refuses_a_check_whose_latest_run_is_not_green(self):
        """Issue 1374: the latest run decides, so a red or pending latest run refuses
        even after an earlier green one, and a tie or an unstamped run is never
        superseded."""
        lint = self.status_context(self.LINT)
        not_green = f"{self.UNPROTECTED}, and the declared required check {self.BUILD} is not green ("
        for name, rollup, observed in (
            ("green then failed", [
                self.check_run(self.BUILD, started=self.EARLY),
                self.check_run(self.BUILD, conclusion="FAILURE", started=self.LATE), lint],
             "CheckRun COMPLETED/FAILURE"),
            ("failed listed last", [
                self.check_run(self.BUILD, conclusion="FAILURE", started=self.LATE),
                self.check_run(self.BUILD, started=self.EARLY), lint],
             "CheckRun COMPLETED/FAILURE"),
            ("green then pending", [
                self.check_run(self.BUILD, started=self.EARLY),
                self.check_run(self.BUILD, "IN_PROGRESS", None, started=self.LATE), lint],
             "CheckRun IN_PROGRESS/none"),
            ("same start", [
                self.check_run(self.BUILD, conclusion="FAILURE", started=self.LATE),
                self.check_run(self.BUILD, started=self.LATE), lint],
             "CheckRun COMPLETED/FAILURE"),
            ("failed run without a start", [
                self.check_run(self.BUILD, conclusion="FAILURE"),
                self.check_run(self.BUILD, started=self.LATE), lint],
             "CheckRun COMPLETED/FAILURE"),
            ("failed run with an unreadable start", [
                self.check_run(self.BUILD, conclusion="FAILURE", started="yesterday"),
                self.check_run(self.BUILD, started=self.LATE), lint],
             "CheckRun COMPLETED/FAILURE"),
            ("later run with an unreadable start", [
                self.check_run(self.BUILD, conclusion="FAILURE", started=self.EARLY),
                self.check_run(self.BUILD, started="yesterday"), lint],
             "CheckRun COMPLETED/FAILURE"),
            ("queued re-run with the zero start", [
                self.check_run(self.BUILD, started=self.EARLY),
                self.check_run(self.BUILD, "QUEUED", None, started="0001-01-01T00:00:00Z"),
                lint],
             "CheckRun QUEUED/none"),
            ("failed run of another workflow", [
                self.check_run(self.BUILD, conclusion="FAILURE", started=self.EARLY,
                               workflow="ci"),
                self.check_run(self.BUILD, started=self.LATE, workflow="nightly"), lint],
             "CheckRun COMPLETED/FAILURE"),
            ("later run with an impossible date", [
                self.check_run(self.BUILD, conclusion="FAILURE", started=self.EARLY),
                self.check_run(self.BUILD, started="2026-99-01T00:00:00Z"), lint],
             "CheckRun COMPLETED/FAILURE"),
            ("later run with a day the month lacks", [
                self.check_run(self.BUILD, conclusion="FAILURE", started=self.EARLY),
                self.check_run(self.BUILD, started="2026-02-30T00:00:00Z"), lint],
             "CheckRun COMPLETED/FAILURE"),
        ):
            with self.subTest(case=name):
                self.assertEqual(
                    not_green + observed + ")", self.refusal_line(self.floor_merge(rollup)))

    def test_readable_protection_governs_a_repository_with_declared_checks(self):
        """Issue 552 D2: a protection read that exits 0 runs today's predicate, and the
        declared checks are not consulted."""
        allowed = self.floor_merge([], env={"FAKE_PROTECTION_MODE": "ok"})
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        refused = self.floor_merge(
            [self.check_run(self.BUILD), self.check_run(self.LINT)],
            env={"FAKE_PROTECTION_MODE": "ok", "FAKE_PROTECTION_JSON": (
                '{"required_status_checks":{"contexts":[]},"enforce_admins":{"enabled":true}}')})
        self.assertTrue(self.refusal_line(refused).startswith(
            "lifecycle guard: protection predicate failed"), refused.stderr)

    def test_every_other_protection_answer_keeps_its_refusal(self):
        """Issue 552 D2, AC2: with declared checks and a green rollup, every answer but the
        plan-gated one keeps the refusal it gets without the floor."""
        green = [self.check_run(self.BUILD), self.check_run(self.LINT)]
        docs = "https://docs.github.com/rest/branches/branch-protection#get-branch-protection"

        def body(message, status):
            return json.dumps({"message": message, "documentation_url": docs,
                               "status": status}, separators=(",", ":"))

        for name, env, prefix in (
            ("nonzero", {"FAKE_PROTECTION_MODE": "nonzero"}, "fake protection failure"),
            ("404", {"FAKE_PROTECTION_JSON": body("Branch not protected", "404")},
             "gh: Branch not protected (HTTP 404); stdout="),
            ("admin 403", {"FAKE_PROTECTION_JSON": body("Must have admin rights to "
                                                         "Repository.", "403")},
             "gh: Must have admin rights to Repository. (HTTP 403); stdout="),
            ("rate limit 403", {"FAKE_PROTECTION_JSON": body("API rate limit exceeded for "
                                                              "user ID 1.", "403")},
             "gh: API rate limit exceeded for user ID 1. (HTTP 403); stdout="),
            ("numeric status", {"FAKE_PROTECTION_JSON": body(self.PLAN_GATED_MESSAGE, 403)},
             "gh: HTTP 403; stdout="),
            ("not JSON", {"FAKE_PROTECTION_JSON": self.PLAN_GATED_MESSAGE},
             "gh: HTTP 403; stdout=Upgrade to GitHub Pro"),
        ):
            with self.subTest(answer=name):
                line = self.refusal_line(self.floor_merge(green, env=env))
                self.assertTrue(line.startswith(self.LOOKUP_FAILED + prefix), line)
        timed_out = self.floor_merge(green, env={"FAKE_PROTECTION_MODE": "timeout"},
                                     guard_args=("--child-timeout-seconds", "0.5"))
        self.assertEqual("lifecycle guard: protection lookup timed out",
                         self.refusal_line(timed_out))

    def test_the_plan_gated_answer_without_declared_checks_keeps_its_refusal(self):
        """Issue 552 D2, D7: a row declaring no check, a literal integration row and a
        repository with no row keep today's refusal of the plan-gated answer."""
        gated = (f"{self.LOOKUP_FAILED}gh: {self.PLAN_GATED_MESSAGE} (HTTP 403); "
                 f'stdout={{"message":"{self.PLAN_GATED_MESSAGE}"')
        green = [self.check_run(self.BUILD), self.check_run(self.LINT)]
        literal = "fagenorn/literal-floor"
        base = self.write_base(integration_bases={literal: "dev"})
        for name, slug, rows, args in (
            ("no declared check", self.FLOOR,
             {self.FLOOR: {**self.FLOOR_ROWS[self.FLOOR], "required_checks": []}}, ()),
            ("a literal integration row", literal, {}, ("--base-policy", str(base))),
            ("no row", "fagenorn/tool", {}, ()),
        ):
            with self.subTest(case=name):
                line = self.refusal_line(
                    self.floor_merge(green, slug=slug, rows=rows, guard_args=args))
                self.assertTrue(line.startswith(gated), line)

    def test_declared_checks_leave_the_integration_base_and_the_release_arm_alone(self):
        """Issue 552 D2, AC2: with checks declared, a feature merge into the declared
        integration base stays exempt, and the release arm keeps its own rollup gate."""
        exempt = self.floor_merge([], slug=self.STAGED, base="dev")
        self.assertEqual(0, exempt.returncode, exempt.stderr)
        policy = self.write_policy(derivation={}, derived_repositories=self.FLOOR_ROWS)
        release = self.run_guard(
            f"gh pr merge 1 --repo {self.STAGED} --merge",
            cwd=self.make_repo(f"git@github.com:{self.STAGED}.git"),
            guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(policy)),
            env={**self.rows_env(self.FLOOR_ROWS), **self.release_env(
                url=f"https://github.com/{self.STAGED}/pull/1",
                statusCheckRollup=[self.check_run("unrelated")])})
        self.assertEqual(0, release.returncode, release.stderr)

    # ------------------------------------------------------------------
    # Forge adapter arms (#124): the tag push and the release creation the
    # github-release profile invokes, plus the permanent-branch repair (#116 D5).
    # ------------------------------------------------------------------

    SPELLINGS = json.loads((Path(__file__).parent / "fixtures/forge-adapter-spellings.json")
                           .read_text(encoding="utf-8"))
    CANONICAL_SLUG = SPELLINGS["canonical"]["slug"]
    REPOSITORY_CLASSES = (  # (class, slug, authorized, env), D22
        ("default-only", "fagenorn/nix-config", True, {}),
        ("distinct-integration", "elevenyellow/nodocom", True, {}),
        ("protection-inaccessible", "fagenorn/nix-config", True, {"FAKE_PROTECTION_MODE": "nonzero"}),
        ("other-owner", "someone-else/nix-config", False, {}),
    )

    def tagged_repo(self, slug, tag="v1.2.3", annotated=True):
        repo = self.make_repo(f"git@github.com:{slug}.git")
        # Signing is switched off: a host's tag.gpgsign would turn the lightweight tag
        # into a signed annotated one and demand a message.
        identity = ["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
        subprocess.run([*identity, "commit", "--quiet", "--allow-empty", "-m", "init"],
                       cwd=repo, check=True, capture_output=True)
        argv = [*identity, "tag"]
        argv += ["-a", tag, "-m", "release"] if annotated else [tag]
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
        return repo

    def test_every_adapter_spelling_is_an_allowed_row(self):
        """AC4, D12: one fixture drives the adapter suite and this table. Issue 554 D5: the
        merge row is admitted only as the release arm's integration-into-default merge."""
        commit = self.SPELLINGS["canonical"]["commit"]
        for name, slug, authorized, env in self.REPOSITORY_CLASSES:
            repo = self.tagged_repo(slug)
            env = {**env, "FAKE_PR_JSON": json.dumps({
                **self.RELEASE_PR, "headRefOid": commit,
                "url": f"https://github.com/{slug}/pull/336"})}
            for row in self.SPELLINGS["rows"]:
                raw = row["raw"].replace(self.CANONICAL_SLUG, slug)
                with self.subTest(repository=name, row=row["id"]):
                    result = self.run_guard(raw, cwd=repo, env=env)
                    if row["id"] == "pr_merge.merge":
                        expect_allowed = name == "distinct-integration"
                    else:
                        expect_allowed = authorized or row["kind"] == "read"
                    self.assertEqual(0 if expect_allowed else 2, result.returncode, result.stderr)

    def test_the_adapter_sync_spellings_are_judged_per_repository_class(self):
        """Issue 845, #124 D12/D22: the fixture's sync rows, which the forge suite renders, meet
        the real guard here. The sync branch push is a feature push, admitted in every
        authorized class; the pull request into `dev` is admitted only where `dev` is the
        declared integration branch, which is the one class a release syncs in."""
        for name, slug, authorized, env in self.REPOSITORY_CLASSES:
            repo = self.tagged_repo(slug)
            for row in self.SPELLINGS["sync"]["rows"]:
                raw = row["raw"].replace(self.CANONICAL_SLUG, slug)
                with self.subTest(repository=name, row=row["id"]):
                    result = self.run_guard(raw, cwd=repo, env=env)
                    if row["id"] == "sync_pr.create":
                        expect_allowed = name == "distinct-integration"
                    else:
                        expect_allowed = authorized or row["kind"] == "read"
                    self.assertEqual(0 if expect_allowed else 2, result.returncode, result.stderr)
        self.assertEqual(
            sorted(row["id"] for row in self.SPELLINGS["sync"]["rows"] if row["kind"] == "mutation"),
            ["sync_branch.push", "sync_pr.create"])

    def test_the_adapter_merge_spelling_refuses_its_near_misses(self):
        """Issue 554 D5: only the exact rendered spelling passes the release arm."""
        commit = self.SPELLINGS["canonical"]["commit"]
        row = next(r for r in self.SPELLINGS["rows"] if r["id"] == "pr_merge.merge")
        good = row["raw"].replace(self.CANONICAL_SLUG, NODO)
        repo = self.tagged_repo(NODO)
        env = {"FAKE_PR_JSON": json.dumps({**self.RELEASE_PR, "headRefOid": commit,
                                           "url": f"https://github.com/{NODO}/pull/336"})}
        self.assertEqual(0, self.run_guard(good, cwd=repo, env=env).returncode)
        for label, command in (
                ("admin", good + " --admin"), ("auto", good.replace(" --merge", " --auto --merge")),
                ("squash", good.replace("--merge", "--squash")), ("rebase", good.replace("--merge", "--rebase")),
                ("delete-branch", good + " --delete-branch"),
                ("reordered", f"gh pr merge 336 --merge --repo {NODO} --match-head-commit {commit}"),
                ("short sha", good.replace(commit, commit[:7])),
                ("no repo", good.replace(f" --repo {NODO}", "")), ("trailing", good + " extra")):
            with self.subTest(label):
                self.assertEqual(2, self.run_guard(command, cwd=repo, env=env).returncode)

    # Remote branch deletion (issue 458): the push verb's third form.

    def test_remote_branch_deletion_arm(self):
        """Issue 458 D1, D2: `git push origin --delete refs/heads/<branch>` deletes a
        feature branch in an authorized repository and never a permanent branch."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        form = "git push origin --delete refs/heads/<branch>"
        delete = "git push origin --delete refs/heads/issue-458-topic"
        for command, cwd in (
            (delete, repo),
            ("unset GITHUB_TOKEN && " + delete, repo),
            ("env -u GITHUB_TOKEN " + delete, repo),
            (f"git -C {repo} push origin --delete refs/heads/issue-458-topic",
             self.fixture_dir.name),
            (delete, nodo),
        ):
            with self.subTest(command=command, cwd=cwd):
                result = self.run_guard(command, cwd=cwd)
                self.assertEqual(0, result.returncode, result.stderr)
        for command, cwd, problem in (
            ("git push origin --delete refs/heads/main", repo,
             "refusing to delete the permanent branch main"),
            ("git push origin --delete refs/heads/main", nodo,
             "refusing to delete the permanent branch main"),
            ("git push origin --delete refs/heads/dev", nodo,
             "refusing to delete the permanent branch dev"),
        ):
            with self.subTest(command=command, cwd=cwd):
                line = self.refusal_line(self.run_guard(command, cwd=cwd))
                self.assertEqual(f"lifecycle guard: unsafe push: {problem}", line)
        for command, problem in (
            ("git push origin --delete issue-458-topic", "missing refs/heads/<branch>"),
            ("git push origin --delete refs/tags/v1.2.3", "missing refs/heads/<branch>"),
            ("git push origin --delete refs/heads/a refs/heads/b",
             "unexpected refs/heads/b at the end"),
            ("git push -u origin --delete refs/heads/issue-458-topic", "missing <branch>"),
            ("git push --delete origin refs/heads/issue-458-topic", "--delete is out of place"),
            ("git push origin -d refs/heads/issue-458-topic", "unknown flag -d"),
            ("git push origin --delete refs/heads/", "branch name must not be empty"),
            ("git push origin --delete refs/heads/refs/heads/x",
             "namespaced ref refs/heads/x is not accepted; name the branch directly"),
        ):
            with self.subTest(command=command):
                line = self.refusal_line(self.run_guard(command, cwd=repo))
                self.assertTrue(line.startswith(
                    f"lifecycle guard: unsafe push: {problem}; accepted: "), line)
                self.assertIn("; or " + form + "; optional prefix: ", line)
        outsider = self.make_repo("git@github.com:someoneelse/tool.git")
        line = self.refusal_line(self.run_guard(delete, cwd=outsider))
        self.assertEqual("lifecycle guard: unsafe push: repository someoneelse/tool is "
                         "outside standing authorization", line)
        unresolved = self.make_repo("git@github.com:fagenorn/argus.git", default_branch=None)
        line = self.refusal_line(self.run_guard(delete, cwd=unresolved))
        self.assertEqual("lifecycle guard: unsafe push: cannot resolve the repository "
                         "default branch", line)

    def test_the_remote_deletion_form_deletes_only_the_named_branch(self):
        """Issue 458 D1, D5: run by git against a local bare remote that holds a branch
        and a tag of one name, the ship stage's filled spelling deletes the branch alone."""
        form = next(form for form in self.SHAPES["skill_forms"]
                    if form["id"] == "branch.remote")
        command = self.shape_command(form["template"])
        name = self.SHAPES["values"]["<branch>"]
        base = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        remote, work = base / "remote.git", base / "work"
        sandbox = SandboxGit(base)

        def git(*argv, cwd=work):
            return sandbox.git(*argv, cwd=cwd)

        sandbox.run(["git", "init", "--quiet", "--bare", str(remote)])
        work.mkdir()
        git("init", "--quiet")
        git("remote", "add", "origin", str(remote))
        git("commit", "--quiet", "--allow-empty", "-m", "init")
        git("tag", name)
        sandbox.push(work, "origin", f"HEAD:refs/heads/{name}", f"refs/tags/{name}")
        sandbox.run(shlex.split(command), cwd=work)
        self.assertEqual("", git("ls-remote", "--heads", "origin", name))
        self.assertIn(f"refs/tags/{name}", git("ls-remote", "--tags", "origin", name))

    def push_url_repo(self, *config):
        """A fagenorn/nix-config fixture repository with each (key, value) of `config`
        added to its local git config, in order (issue 655)."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for key, value in config:
            subprocess.run(["git", "config", "--add", key, value], cwd=repo, check=True,
                           capture_output=True)
        return repo

    def test_a_push_whose_effective_push_url_names_another_repository_is_refused(self):
        """Issue 655 AC3, D3, D10: every push arm resolves origin's push URLs as git
        does (pushurl, insteadOf, pushInsteadOf) and refuses unless each names the
        repository the guard judged."""
        topic = "issue-655-topic"
        here = "fagenorn/nix-config"
        other = "git@github.com:fagenorn/guard-elsewhere.git"
        refused = {
            "pushurl": (self.push_url_repo(("remote.origin.pushurl", other)), other),
            "pushInsteadOf": (
                self.push_url_repo(("url.git@github.com:someoneelse/.pushInsteadOf",
                                    "git@github.com:fagenorn/")),
                "git@github.com:someoneelse/nix-config.git"),
            "second pushurl": (
                self.push_url_repo(("remote.origin.pushurl", f"git@github.com:{here}.git"),
                                   ("remote.origin.pushurl", other)),
                other),
            "not github": (self.push_url_repo(("remote.origin.pushurl", "/tmp/elsewhere.git")),
                           "/tmp/elsewhere.git"),
        }
        for name, (repo, url) in refused.items():
            for command in (f"git push origin {topic}", f"git push -u origin {topic}",
                            f"git push origin --delete refs/heads/{topic}",
                            f"git -C {repo} push origin {topic}",
                            f"cd {repo} && git push origin {topic}"):
                with self.subTest(case=name, command=command):
                    result = self.run_guard(command, cwd=repo)
                    self.assertEqual(2, result.returncode, command)
                    self.assertIn(
                        f"lifecycle guard: unsafe push: origin's push URL {url} "
                        f"does not name {here}", result.stderr)
                    self.assertNotIn("; accepted: ", result.stderr)
        # The tag arm, and a push judged in a -C directory from a clean cwd.
        tagged = self.tagged_repo(here)
        subprocess.run(["git", "config", "remote.origin.pushurl", other], cwd=tagged,
                       check=True, capture_output=True)
        clean = self.make_repo(f"git@github.com:{here}.git")
        for command, cwd in (("git push origin refs/tags/v1.2.3", tagged),
                             (f"git -C {refused['pushurl'][0]} push origin {topic}", clean)):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=cwd)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"unsafe push: origin's push URL {other} does not name {here}",
                              result.stderr)
        # A text refusal keeps its precedence and its accepted forms.
        result = self.run_guard(f"git push --force origin {topic}",
                                cwd=refused["pushurl"][0])
        self.assertEqual(2, result.returncode)
        self.assertIn("; accepted: ", result.stderr)
        self.assertNotIn("push URL", result.stderr)
        # Push URLs that name this repository in another spelling pass.
        for name, repo in (
            ("clean", clean),
            ("pushurl https", self.push_url_repo(
                ("remote.origin.pushurl", f"https://github.com/{here}"))),
            ("pushInsteadOf same repository", self.push_url_repo(
                ("url.https://github.com/fagenorn/.pushInsteadOf", "git@github.com:fagenorn/"))),
        ):
            with self.subTest(case=name):
                result = self.run_guard(f"git push origin {topic}", cwd=repo)
                self.assertEqual(0, result.returncode, (name, result.stderr))

    def test_push_url_lookup_failures_are_refused(self):
        """Issue 655 AC4, D10: a push-URL lookup that times out, exits non-zero,
        prints nothing, or whose git cannot start refuses the push as a state
        refusal (no accepted forms); the same fake git passes a lookup it does not
        disturb."""
        topic = "issue-655-topic"
        repo = self.push_url_repo()
        guard_args = ("--gh-bin", str(self.fake_gh), "--git-bin", str(self.fake_git),
                      "--child-timeout-seconds", "0.5")
        for mode, reason in (("timeout", "push URL lookup timed out"),
                             ("nonzero", "cannot resolve origin's push URL"),
                             ("empty", "cannot resolve origin's push URL")):
            for command in (f"git push origin {topic}",
                            f"git push origin --delete refs/heads/{topic}"):
                with self.subTest(mode=mode, command=command):
                    result = self.run_guard(command, cwd=repo, guard_args=guard_args,
                                            env={"FAKE_PUSH_URL_MODE": mode})
                    self.assertEqual(2, result.returncode, (mode, result.stderr))
                    self.assertIn(f"lifecycle guard: unsafe push: {reason}", result.stderr)
                    self.assertNotIn("; accepted: ", result.stderr)
        result = self.run_guard(f"git push origin {topic}", cwd=repo, guard_args=guard_args)
        self.assertEqual(0, result.returncode, result.stderr)
        # A git that cannot start: no CLI run reaches this branch alone (the same git
        # resolves the repository first), so the source's function is called directly.
        spec = importlib.util.spec_from_file_location("lifecycle_guard_source", GUARD_SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        context = types.SimpleNamespace(
            git_bin=str(Path(self.fixture_dir.name) / "no-such-git"), cwd=str(repo),
            timeout=5, repository="fagenorn/nix-config")
        self.assertEqual("cannot resolve origin's push URL", module.push_url_problem(context))

    # Guarded command shapes (#351): the forms a delivery spells and the dressed
    # shapes agents reach for, from the fixture this suite alone reads.
    SHAPES = json.loads((Path(__file__).parent / "fixtures/guarded-command-shapes.json")
                        .read_text(encoding="utf-8"))
    TOKEN_PREFIX = "unset GITHUB_TOKEN && "
    ENV_TOKEN_PREFIX = "env -u GITHUB_TOKEN "

    def test_guard_docstring_names_only_readers_of_the_shape_fixture(self):
        """The guard docstring may credit a test file with reading the shape fixture only
        if that file mentions it (a rename once left a check that no longer existed)."""
        readme = ast.get_docstring(ast.parse(GUARD_SOURCE.read_text(encoding="utf-8")))
        fixture = "guarded-command-shapes.json"
        start = readme.index(f"The shape fixture `tests/fixtures/{fixture}`")
        sentence = readme[start:readme.index("`form_values`", start)]
        named = re.findall(r"[\w/.-]*test_\w+\.py", sentence)
        self.assertTrue(named, "the guard docstring sentence names no reading suite")
        for name in named:
            candidates = [Path(__file__).parent.parent / name,
                          Path(__file__).parent.parent / "tests" / name]
            path = next((c for c in candidates if c.is_file()), None)
            if path is None:
                path = next(Path(__file__).parent.parent.rglob(Path(name).name), None)
            self.assertIsNotNone(path, f"{name} does not exist")
            self.assertIn(fixture, path.read_text(encoding="utf-8"), f"{name} never reads {fixture}")

    def shape_command(self, template):
        for placeholder, value in self.SHAPES["values"].items():
            template = template.replace(placeholder, value)
        return template

    def assert_shape_verdict(self, command, repo, label, verdict):
        result = self.run_guard(command, cwd=repo)
        self.assertEqual(verdict["exit"], result.returncode, (command, result.stderr))
        if verdict["exit"] == 2:
            self.assertIn(f"lifecycle guard: unsafe {label}:", result.stderr)
            self.assertIn(verdict["reason"], result.stderr)
            self.assertIn("; accepted: ", result.stderr)

    def test_every_guarded_command_shape_gets_its_verdict(self):
        """#351 AC3, D6: the skill's literal forms and the refused dressed shapes."""
        slug = self.SHAPES["values"]["<resolved-repository>"]
        repo = self.make_repo(f"git@github.com:{slug}.git")
        forms = {form["id"]: form for form in self.SHAPES["skill_forms"]}
        for form in forms.values():
            command = self.shape_command(form["template"])
            for variant, text in (("bare", command), ("prefixed", self.TOKEN_PREFIX + command),
                                  ("env_prefixed", self.ENV_TOKEN_PREFIX + command)):
                with self.subTest(form=form["id"], variant=variant):
                    self.assert_shape_verdict(text, repo, form["label"], form[variant])
        for shape in self.SHAPES["refused_shapes"]:
            command = (shape["before"] + self.shape_command(forms[shape["form"]]["template"])
                       + shape["after"])
            with self.subTest(shape=shape["id"]):
                self.assert_shape_verdict(
                    command, repo, shape["label"], {"exit": 2, "reason": shape["reason"]})

    def test_every_invocation_shape_gets_its_verdict(self):
        """Issue 400 D10: the guard-only invocation shapes, read from their one home."""
        slug = self.SHAPES["values"]["<resolved-repository>"]
        repo = self.make_repo(f"git@github.com:{slug}.git")
        for shape in self.SHAPES["invocation_shapes"]:
            command = self.shape_command(shape["template"]).replace(
                "<repository-root>", str(repo))
            with self.subTest(shape=shape["id"]):
                self.assert_shape_verdict(command, repo, shape["label"], shape["verdict"])

    # ------------------------------------------------------------------
    # Accepted forms (issue 402 D3, D6, D7, D8, D13): a refusal that lies in the
    # command's text prints the forms that would pass where it was printed.
    # ------------------------------------------------------------------

    FORM_VALUES = SHAPES["form_values"]
    PREFIX_CLAUSE = ("; optional prefix: env -u GITHUB_TOKEN -u GH_TOKEN | "
                     "unset GITHUB_TOKEN && | env -u GITHUB_TOKEN")

    def refusal_line(self, result):
        """The guard's one refusal line; the call must have exited 2."""
        self.assertEqual(2, result.returncode, result.stderr)
        lines = [line for line in result.stderr.splitlines()
                 if line.startswith("lifecycle guard: ")]
        self.assertEqual(1, len(lines), result.stderr)
        return lines[0]

    def accepted_clause(self, line):
        """(forms, prefixes) a refusal line prints: the forms split at `; or `, each
        trailing note dropped; each prefix with the space that joins it to a command."""
        self.assertIn("; accepted: ", line)
        clause = line.split("; accepted: ", 1)[1]
        forms_text, _, prefix_text = clause.partition("; optional prefix: ")
        forms = [re.sub(r" \([^()]*\)$", "", form) for form in forms_text.split("; or ")]
        prefixes = [spelling + " " for spelling in prefix_text.split(" | ")] if prefix_text else []
        return forms, prefixes

    def form_spellings(self, form):
        """Every spelling of `form`, one per subset of its `[...]` groups, filled from
        form_values; no placeholder may survive the fill."""
        parts = re.split(r"(\[[^\[\]]*\])", form)
        groups = [index for index, part in enumerate(parts) if part.startswith("[")]
        spellings = []
        for mask in range(1 << len(groups)):
            kept = "".join(
                (part[1:-1] if (mask >> groups.index(index)) & 1 else "")
                if index in groups else part
                for index, part in enumerate(parts)
            )
            spelling = " ".join(kept.split())
            for placeholder, value in self.FORM_VALUES.items():
                spelling = spelling.replace(placeholder, value)
            self.assertNotRegex(spelling, r"<[^<>\s]+>")
            spellings.append(spelling)
        return spellings

    def assert_forms_pass(self, line, cwd, label):
        """Every spelling of every form `line` prints exits 0 in `cwd`, bare and behind
        each printed prefix, with PR facts that fit the form's merge arm."""
        forms, prefixes = self.accepted_clause(line)
        for form in forms:
            for spelling in self.form_spellings(form):
                release_arm = (spelling.startswith("gh pr merge ")
                               and not spelling.endswith(" --delete-branch"))
                env = self.release_env() if release_arm else None
                for text in [spelling] + [prefix + spelling for prefix in prefixes]:
                    with self.subTest(label=label, form=text):
                        result = self.run_guard(text, cwd=cwd, env=env)
                        self.assertEqual(0, result.returncode, (text, result.stderr))

    def test_every_printed_form_is_allowed_where_printed(self):
        """Issue 402 AC3, D13: each operation's whole table, printed in the fixture
        repository, in a Nodo-row repository and with no context, and the forms the
        AC2 refusals print, filled from form_values, pass where they were printed."""
        fixture_slug = self.FORM_VALUES["<slug>"]
        fixture = self.tagged_repo(fixture_slug)
        nodo = self.tagged_repo(NODO)

        def provoking(slug):
            return {
                "push": "git push --force origin issue-402-topic",
                "PR creation": f"gh pr create --repo {slug} --draft",
                "merge": f"gh pr merge 402 --repo {slug} --squash",
                "release creation": f"gh release create v1.2.3 --repo {slug} --draft",
                "branch deletion": "git branch -d --force issue-402-topic",
            }

        recognition = {label: "xargs " + command
                       for label, command in provoking(fixture_slug).items()}
        one_each = {"push": 3, "PR creation": 2, "merge": 1, "release creation": 1,
                    "branch deletion": 1}
        covered = set()
        for name, cwd, commands, counts in (
            ("fixture", fixture, provoking(fixture_slug), one_each),
            ("nodo", nodo, provoking(NODO), {**one_each, "PR creation": 4, "merge": 2}),
            ("no context", fixture, recognition, one_each),
        ):
            for label, command in commands.items():
                with self.subTest(context=name, label=label):
                    line = self.refusal_line(self.run_guard(command, cwd=cwd))
                    self.assertTrue(line.startswith(f"lifecycle guard: unsafe {label}: "), line)
                    forms, _ = self.accepted_clause(line)
                    self.assertEqual(counts[label], len(forms), line)
                    self.assert_forms_pass(line, cwd, label)
                    covered.add(label)
        self.assertEqual({"push", "PR creation", "merge", "release creation",
                          "branch deletion"}, covered)
        feature_into_dev = {"FAKE_PR_JSON": json.dumps({
            "state": "OPEN", "baseRefName": "dev", "headRefName": "issue-2342-topic",
            "url": f"https://github.com/{NODO}/pull/2342", "statusCheckRollup": []})}
        for label, cwd, command, env, count in (
            ("merge", nodo,
             f"gh pr merge 2342 --repo {NODO} --merge --match-head-commit {self.HEAD_SHA}",
             feature_into_dev, 1),
            ("push", fixture,
             "unset GITHUB_TOKEN; git push -q origin HEAD:issue-402-topic 2>&1 | tail -2",
             None, 3),
        ):
            with self.subTest(context="AC2", label=label):
                line = self.refusal_line(self.run_guard(command, cwd=cwd, env=env))
                forms, _ = self.accepted_clause(line)
                self.assertEqual(count, len(forms), line)
                self.assert_forms_pass(line, cwd, label)

    def test_text_refusals_list_the_forms_their_facts_admit(self):
        """Issue 402 D6, D7, D8, D9: the forms follow the context and, after the PR
        lookup, the arm the PR admits; branch deletion prints no prefix clause."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        feature = ('gh pr merge <n> --repo {slug} --merge [--subject "<subject>"] '
                   "[--match-head-commit <sha>] --delete-branch")
        release = ('gh pr merge <n> --repo {slug} --merge [--subject "<subject>"] '
                   "[--match-head-commit <sha>] (only dev into main)")
        create = ("gh pr create --repo {slug} [--draft] --base {base} --head <branch> "
                  '--title "<title>" --body "<body>"')
        create_file = ("gh pr create --repo {slug} [--draft] --base {base} --head <branch> "
                       '--title "<title>" --body-file <path>')
        push = ("git push origin refs/tags/<vX.Y.Z>; or git push [-u] origin <branch>; "
                "or git push origin --delete refs/heads/<branch>")

        def pr(head, base):
            return {"FAKE_PR_JSON": json.dumps({
                "state": "OPEN", "baseRefName": base, "headRefName": head,
                "url": f"https://github.com/{NODO}/pull/7", "statusCheckRollup": []}),
                "FAKE_PROTECTION_MODE": "nonzero"}

        for command, cwd, env, forms in (
            ("gh pr merge 7 --repo fagenorn/nix-config --squash", repo, None,
             feature.format(slug="fagenorn/nix-config")),
            (f"gh pr merge 7 --repo {NODO} --squash", nodo, None,
             feature.format(slug=NODO) + "; or " + release.format(slug=NODO)),
            ("xargs gh pr merge 7", repo, None, feature.format(slug="<slug>")),
            ("gh pr create --repo fagenorn/nix-config --draft", repo, None,
             create.format(slug="fagenorn/nix-config", base="main") + "; or "
             + create_file.format(slug="fagenorn/nix-config", base="main")),
            (f"gh pr create --repo {NODO} --draft", nodo, None,
             create.format(slug=NODO, base="dev") + "; or "
             + create.format(slug=NODO, base="main") + "; or "
             + create_file.format(slug=NODO, base="dev") + "; or "
             + create_file.format(slug=NODO, base="main")),
            ("xargs gh pr create", repo, None, create.format(slug="<slug>", base="<base>")
             + "; or " + create_file.format(slug="<slug>", base="<base>")),
            ("/usr/bin/git push origin issue-402-topic", repo, None, push),
            # After the lookup the release form on a feature PR lists the feature arm,
            (f"gh pr merge 7 --repo {NODO} --merge", nodo, pr("issue-7-topic", "dev"),
             feature.format(slug=NODO)),
            # and --delete-branch on the integration-into-default PR the release arm.
            (f"gh pr merge 7 --repo {NODO} --merge --delete-branch", nodo, pr("dev", "main"),
             release.format(slug=NODO)),
        ):
            with self.subTest(command=command):
                line = self.refusal_line(self.run_guard(command, cwd=cwd, env=env))
                self.assertTrue(line.endswith("; accepted: " + forms + self.PREFIX_CLAUSE), line)
        # D9: an invocation form is refused by the allowlist grammar (issue 418),
        # which names the grammar, then the clause.
        line = self.refusal_line(self.run_guard("/usr/bin/git push origin x", cwd=repo))
        self.assertIn(GRAMMAR, line)
        self.assertIn("; accepted: ", line)
        # No arm remains for a permanent head that neither arm admits.
        for command in (f"gh pr merge 7 --repo {NODO} --merge --delete-branch",
                        f"gh pr merge 7 --repo {NODO} --merge"):
            with self.subTest(command=command, head="main", base="dev"):
                line = self.refusal_line(self.run_guard(command, cwd=nodo, env=pr("main", "dev")))
                self.assertNotIn("accepted:", line)
        line = self.refusal_line(self.run_guard("git branch -d --force issue-402-topic"))
        self.assertTrue(line.endswith("; accepted: git branch -d <branch>"), line)

    def test_state_refusals_print_no_accepted_forms(self):
        """Issue 402 D3: a refusal of the repository or forge state names only its
        problem, since no spelling would pass there."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        foreign = self.make_repo("git@github.com:someoneelse/tool.git")
        lightweight = self.tagged_repo("fagenorn/nix-config", tag="v2.0.0", annotated=False)
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        merge = "gh pr merge 2342 --repo fagenorn/nix-config --merge --delete-branch"
        for command, cwd, env, problem in (
            ("git push origin issue-402-topic", foreign, None,
             "unsafe push: repository someoneelse/tool is outside standing authorization"),
            ("git push origin main", repo, None,
             "unsafe push: refusing to push the default branch main"),
            ("git push origin refs/tags/v2.0.0", lightweight, None,
             "unsafe push: v2.0.0 is not an existing annotated tag"),
            ('gh pr create --repo fagenorn/nix-config --base main --head main --title "x" '
             '--body "y"', repo, None, "unsafe PR creation: head and base must differ"),
            (merge, repo, {"FAKE_PR_MODE": "nonzero"}, "PR lookup failed"),
            (merge, repo, {"FAKE_PROTECTION_MODE": "nonzero"}, "protection lookup failed"),
            (f"gh pr merge 1484 --repo {NODO} --merge", nodo,
             self.release_env(statusCheckRollup=[]),
             "unsafe merge: the PR's check rollup is not entirely green"),
            (merge.replace(" --delete-branch", f" --match-head-commit {self.OTHER_SHA} "
                           "--delete-branch"), repo, None,
             f"unsafe merge: --match-head-commit {self.OTHER_SHA} is not the PR head commit "
             f"{self.HEAD_SHA}; merge only a head you reviewed"),
            (merge, repo, {"FAKE_PR_JSON": json.dumps({
                "state": "OPEN", "baseRefName": "main", "headRefName": "issue-2342-topic",
                "headRefOid": self.HEAD_SHA, "mergeStateStatus": "BEHIND",
                "url": "https://github.com/fagenorn/nix-config/pull/2342"})},
             "unsafe merge: the PR is behind its base main; repair: sync the branch with main, "
             "push it and wait for its required checks before merging"),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=cwd, env=env)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: {problem}", result.stderr)
                self.assertNotIn("accepted:", result.stderr)
                self.assertNotIn("optional prefix:", result.stderr)

    def test_the_retro_commands_name_their_problem_and_cure(self):
        """Issue 402 AC2: the #2342 merge names the missing --delete-branch and prints
        the feature form, which, filled in, passes; the #2268 push names its first
        character outside the allowlist grammar (issue 418)."""
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        feature_into_dev = {"FAKE_PR_JSON": json.dumps({
            "state": "OPEN", "baseRefName": "dev", "headRefName": "issue-2342-topic",
            "headRefOid": self.HEAD_SHA, "mergeStateStatus": "CLEAN",
            "url": f"https://github.com/{NODO}/pull/2342", "statusCheckRollup": []}),
            "FAKE_PROTECTION_MODE": "nonzero"}
        merge = f"gh pr merge 2342 --repo {NODO} --merge --match-head-commit {self.HEAD_SHA}"
        line = self.refusal_line(self.run_guard(merge, cwd=nodo, env=feature_into_dev))
        self.assertEqual(
            "lifecycle guard: unsafe merge: missing --delete-branch: it may be omitted only "
            "when merging dev into main; this PR merges issue-2342-topic into dev; accepted: "
            f'gh pr merge <n> --repo {NODO} --merge [--subject "<subject>"] '
            "[--match-head-commit <sha>] --delete-branch" + self.PREFIX_CLAUSE, line)
        filled = self.run_guard(merge + " --delete-branch", cwd=nodo, env=feature_into_dev)
        self.assertEqual(0, filled.returncode, filled.stderr)
        line = self.refusal_line(self.run_guard(
            "unset GITHUB_TOKEN; git push -q origin HEAD:issue-402-topic 2>&1 | tail -2",
            cwd=repo))
        self.assertTrue(line.startswith(
            f"lifecycle guard: unsafe push: `;` outside quotes; {GRAMMAR}"), line)
        self.assertTrue(line.endswith(
            "; accepted: git push origin refs/tags/<vX.Y.Z>; or git push [-u] origin "
            "<branch>; or git push origin --delete refs/heads/<branch>"
            + self.PREFIX_CLAUSE), line)

    def test_a_merge_behind_the_two_name_env_prefix_passes_and_its_misspelling_names_the_form_flag_and_prefix(self):
        """Issue 1592: the two-name `env -u` spelling passes, and the refusal of the
        same merge without `--delete-branch` prints that spelling first."""
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        feature_into_dev = {"FAKE_PR_JSON": json.dumps({
            "state": "OPEN", "baseRefName": "dev", "headRefName": "issue-2342-topic",
            "headRefOid": self.HEAD_SHA, "mergeStateStatus": "CLEAN",
            "url": f"https://github.com/{NODO}/pull/2342", "statusCheckRollup": []}),
            "FAKE_PROTECTION_MODE": "nonzero"}
        prefix = "env -u GITHUB_TOKEN -u GH_TOKEN "
        merge = f"gh pr merge 2342 --repo {NODO} --merge --match-head-commit {self.HEAD_SHA}"
        passed = self.run_guard(prefix + merge + " --delete-branch", cwd=nodo,
                                env=feature_into_dev)
        self.assertEqual(0, passed.returncode, passed.stderr)
        line = self.refusal_line(self.run_guard(prefix + merge, cwd=nodo,
                                                env=feature_into_dev))
        self.assertEqual(
            "lifecycle guard: unsafe merge: missing --delete-branch: it may be omitted only "
            "when merging dev into main; this PR merges issue-2342-topic into dev; accepted: "
            f'gh pr merge <n> --repo {NODO} --merge [--subject "<subject>"] '
            "[--match-head-commit <sha>] --delete-branch; optional prefix: "
            "env -u GITHUB_TOKEN -u GH_TOKEN | unset GITHUB_TOKEN && | env -u GITHUB_TOKEN",
            line)

    def test_a_merge_text_refusal_keeps_its_first_problem_and_names_the_missing_flag(self):
        """Issue 1592: a merge's text refusal appends `; missing <flag>` for a flag every
        merge form requires and the words lack, unless the problem already names it."""
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        feature_into_dev = {"FAKE_PR_JSON": json.dumps({
            "state": "OPEN", "baseRefName": "dev", "headRefName": "issue-2342-topic",
            "headRefOid": self.HEAD_SHA, "mergeStateStatus": "CLEAN",
            "url": f"https://github.com/{NODO}/pull/2342", "statusCheckRollup": []}),
            "FAKE_PROTECTION_MODE": "nonzero"}
        tail = ("; optional prefix: env -u GITHUB_TOKEN -u GH_TOKEN | unset GITHUB_TOKEN && "
                "| env -u GITHUB_TOKEN")
        head = f"--match-head-commit {self.HEAD_SHA} --delete-branch"
        for command, start in (
            (f"env -u GITHUB_TOKEN -u GH_TOKEN gh pr merge 2342 --repo {NODO} --merg {head}",
             "lifecycle guard: unsafe merge: unknown flag --merg; missing --merge; accepted: "),
            (f"env  -u GITHUB_TOKEN gh pr merge 2342 --repo {NODO} {head}",
             "lifecycle guard: unsafe merge: unaccepted credential-scrub prefix "
             "`env -u GITHUB_TOKEN` (doubled space); missing --merge; accepted: "),
            (f"env -u PATH gh pr merge 2342 --repo {NODO} {head}",
             "lifecycle guard: unsafe merge: `env -u PATH` before the verb; missing --merge; "
             + GRAMMAR),
            (f"gh pr merge 2342 --repo {NODO} {head}",
             "lifecycle guard: unsafe merge: missing --merge; accepted: "),
            # A flag spelled as another flag's value is not the flag.
            (f'gh pr merge 2342 --repo {NODO} --merg --subject "--merge" {head}',
             "lifecycle guard: unsafe merge: unknown flag --merg; missing --merge; accepted: "),
            # Nor is it when the value-taking flag is one the form table does not spell.
            (f'gh pr merge 2342 --repo {NODO} --body "--merge" {head}',
             "lifecycle guard: unsafe merge: unknown flag --body; missing --merge; accepted: "),
            (f'gh pr merge 2342 --repo {NODO} -t "--merge" {head}',
             "lifecycle guard: unsafe merge: unknown flag -t; missing --merge; accepted: "),
            # Nor is a word after `--`, which ends the options.
            (f"gh pr merge 2342 --repo {NODO} -- --merge {head}",
             "lifecycle guard: unsafe merge: unknown flag --; missing --merge; accepted: "),
        ):
            with self.subTest(command=command):
                line = self.refusal_line(self.run_guard(command, cwd=nodo,
                                                        env=feature_into_dev))
                self.assertTrue(line.startswith(start), line)
                # The allowlist-grammar refusal builds no repository context.
                slug = "<slug>" if GRAMMAR in start else NODO
                self.assertIn("; accepted: gh pr merge <n> --repo " + slug, line)
                self.assertTrue(line.endswith(tail), line)
                if command.startswith("gh pr merge"):
                    self.assertNotIn("missing --merge; missing", line)

    def test_refusals_name_the_first_problem(self):
        """Issue 402 D4, D5, D16: one row per named problem class, each followed by the
        accepted forms; the first problem that applies is the one named."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        sha = self.HEAD_SHA
        merge = "gh pr merge 2342 --repo fagenorn/nix-config --merge"
        create = "gh pr create --repo fagenorn/nix-config --base"
        release = ("gh release create v1.2.3 --repo fagenorn/nix-config --verify-tag "
                   '--title "v1.2.3" --notes-file')
        for command, label, problem in (
            # 1. A credential-scrub prefix attempt.
            ("env -u PATH git push origin issue-402-topic", "push",
             "`env -u PATH` before the verb; " + GRAMMAR),
            (f"env  -u GITHUB_TOKEN {merge} --delete-branch", "merge",
             "unaccepted credential-scrub prefix `env -u GITHUB_TOKEN` (doubled space)"),
            ("env -u GITHUB_TOKEN -i git push origin issue-402-topic", "push",
             "`-i` before the verb; " + GRAMMAR),
            ("env -u GITHUB_TOKEN git branch -d issue-402-topic", "branch deletion",
             "branch deletion takes no credential-scrub prefix"),
            # 2. A character outside the allowlist grammar (issue 418), shown itself.
            ("git push origin $(printf issue-402-topic)", "push",
             "`$` outside quotes; " + GRAMMAR),
            ("git branch -d issue-402-topic\ntrue", "branch deletion",
             "`\\n` outside quotes; " + GRAMMAR),
            (f"{merge} --delete-branch | cat", "merge", "`|` outside quotes; " + GRAMMAR),
            # 4. A wrapper.
            ("sudo -u x git push origin issue-402-topic", "push",
             "`sudo -u x` before the verb; " + GRAMMAR),
            ("command git branch -d issue-402-topic", "branch deletion",
             "`command` before the verb; " + GRAMMAR),
            # 5. A git -C directory that is not a plain word.
            (f'git -C "{repo}" push origin issue-402-topic', "push",
             f'`git -C "{repo}"` is not a lifecycle verb; ' + GRAMMAR),
            # 6. An unknown flag.
            ("git push --force origin issue-402-topic", "push", "unknown flag --force"),
            (f"{merge} --admin --delete-branch", "merge", "unknown flag --admin"),
            # 7. Structure, at the furthest point any form reached.
            ("gh pr merge 2342 --repo fagenorn/nix-config --delete-branch", "merge",
             "missing --merge"),
            ("gh pr merge --repo fagenorn/nix-config --merge --delete-branch", "merge",
             "missing <n>"),
            (f"{merge} --match-head-commit --delete-branch", "merge", "missing <sha>"),
            (release.replace("release create", "release new") + " /tmp/n.md",
             "release creation", "`gh release new` is not a lifecycle verb; " + GRAMMAR),
            ('gh pr create --base main --repo fagenorn/nix-config --head issue-402-topic '
             '--title "x" --body "y"', "PR creation", "--base is out of place"),
            (f"{merge} --delete-branch --match-head-commit {sha}", "merge",
             "--match-head-commit is out of place"),
            ("git branch -d issue-402-topic extra", "branch deletion",
             "unexpected extra at the end"),
            # 8. Exact spelling.
            (f"{merge} --subject 'x' --delete-branch", "merge",
             "spell the merge exactly as the accepted form: single spaces, free text in "
             "double quotes"),
            # Slot values, with the value.
            ("git push origin HEAD:issue-402-topic", "push",
             "refspec HEAD:issue-402-topic is not accepted; name the branch alone"),
            ("git push origin +issue-402-topic", "push",
             "force-push refspec +issue-402-topic is not accepted"),
            ("git push origin heads/main", "push",
             "namespaced ref heads/main is not accepted; name the branch directly"),
            ("git push origin -topic", "push", "branch -topic must not begin with a dash"),
            ("git push origin refs/tags/v1.2", "push", "tag v1.2 is not a vMAJOR.MINOR.PATCH tag"),
            (f'{create} release --head issue-402-topic --title "x" --body "y"', "PR creation",
             "--base release is not one of main"),
            (f'{create} main --head issue-402-topic --title "$(id)" --body "y"', "PR creation",
             "`$` inside double quotes; " + GRAMMAR),
            ("gh pr merge 0 --repo fagenorn/nix-config --merge --delete-branch", "merge",
             "PR number 0 is not a positive decimal number"),
            ("gh pr merge 2342 --repo fagenorn/other --merge --delete-branch", "merge",
             "--repo fagenorn/other is not the current repository fagenorn/nix-config"),
            (f'{merge} --subject "bad $HOME" --delete-branch', "merge",
             "`$` inside double quotes; " + GRAMMAR),
            (f"{merge} --match-head-commit {sha.upper()} --delete-branch", "merge",
             f"--match-head-commit {sha.upper()} is not 40 lowercase hexadecimal characters"),
            (f"{release} notes.md", "release creation",
             "--notes-file notes.md is not an absolute path without whitespace or "
             "shell-active characters"),
            ("git branch -d -topic", "branch deletion", "branch -topic must not begin with a dash"),
            # The release arm where no integration branch is declared.
            (merge, "merge", "missing --delete-branch: it may be omitted only in a repository "
                             "with a declared integration branch"),
        ):
            with self.subTest(command=command):
                line = self.refusal_line(self.run_guard(command, cwd=repo))
                self.assertIn(f"lifecycle guard: unsafe {label}: {problem}", line)
                self.assertIn("; accepted: ", line)

    def test_a_refused_value_with_a_newline_stays_on_one_line(self):
        """Issue 402 D18: an interpolated value is shown escaped, so a quoted
        `--head` holding a newline still refuses on exactly one stderr line."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        command = ('gh pr create --repo fagenorn/nix-config --base main '
                   '--head "a\nb" --title "t" --body "b"')
        result = self.run_guard(command, cwd=repo)
        self.assertEqual(result.returncode, 2)
        lines = result.stderr.splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        self.assertIn("lifecycle guard: unsafe PR creation: head ", lines[0])
        self.assertIn("a\\nb", lines[0])
        self.assertIn("; accepted: ", lines[0])

    def test_a_refused_word_with_a_newline_stays_on_one_line(self):
        """Issue 402 D18: a word the structure steps name is shown escaped too, so a
        quoted unknown flag holding a newline refuses on exactly one stderr line."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command, problem in (
            ('gh pr merge 2342 --repo fagenorn/nix-config --merge "--x\ny" --delete-branch',
             "unknown flag --x\\ny"),
            ('gh pr create --repo fagenorn/nix-config --base main --head t --title "t" '
             '--body "b" "a\nb"', "unexpected a\\nb at the end"),
            ('sudo -u "x\ny" gh pr merge 2342 --repo fagenorn/nix-config --merge --delete-branch',
             '`sudo -u "x\\ny"` before the verb; ' + GRAMMAR),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(result.returncode, 2)
                lines = result.stderr.splitlines()
                self.assertEqual(len(lines), 1, result.stderr)
                self.assertIn(f": {problem}", lines[0])
                self.assertIn("; accepted: ", lines[0])

    def test_raw_text_sites_match_verb_words_in_order(self):
        """Issue 400 D5, D12: text the guard cannot tokenise as a command is refused
        when a verb's words occur in it in order, the first matched by basename."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        # Finding the verb puts the command under the allowlist grammar (issue 418),
        # which refuses it before the evaluator, env -S or parse refusal is reached.
        for command, label in (
            ("sh -c 'git -C /tmp/x push origin issue-400-topic'", "push"),
            ("eval git\\ push origin issue-400-topic", "push"),
            ("bash -c 'gh --repo fagenorn/nix-config pr merge 1'", "merge"),
            ('echo "unterminated ; git -C /tmp/x push origin issue-400-topic', "push"),
            ("env -S git push origin issue-400-topic", "push"),
            ("env -u FOO -S 'gh release create v1.2.3'", "release creation"),
            ("sh -c \"g''it push origin issue-400-topic\"", "push"),
            ("eval g\\it push origin issue-400-topic", "push"),
            ('env -S "gi\\t push origin issue-400-topic"', "push"),
            # D5 accepts that words in order are enough, adjacent or not.
            ('sh -c "git log; echo push"', "push"),
            # D17: a verb's words as one substring are refused too, as at base
            # 336d9e05, so an expansion default or a bundled option cannot hide it.
            ('eval "${CMD:-git push origin main}"', "push"),
            ('sh -c "${X:-gh pr merge 1}"', "merge"),
            ('sh -c "git branch -df x"', "branch deletion"),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: unsafe {label}: ", result.stderr)
                self.assertIn(GRAMMAR, result.stderr)
        for command in ("sh -c 'git log --oneline'", "env -S 'git status'",
                        "eval 'git fetch origin'"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_recognition_reads_through_global_options_and_paths(self):
        """Issue 400 AC3, D3, D4, D6: a guarded verb behind git global options, gh
        flags or a program path is adjudicated; unguarded invocations still pass."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        # Finding the verb puts the command under the allowlist grammar (issue 418),
        # which refuses it before the recognition refusal is reached.
        for command, label in (
            ("git -C 'two words' push origin issue-400-topic", "push"),
            ("git -C ~/worktree push origin issue-400-topic", "push"),
            ("git -C $(pwd) push origin issue-400-topic", "push"),
            # D17: a separator inside the substitution does not end the run.
            ("git -C $(pwd | cat) push origin issue-400-topic", "push"),
            # D18: a substitution or expansion inside an option's value ends the
            # run before the verb; the walk cannot bound a non `-C` option's value.
            ("git -c core.hooksPath=$(printf /dev/null) push origin main", "push"),
            ("git -c k=${X} push origin main", "push"),
            ("git -C /tmp/x -c k=`printf v` branch -d issue-400-topic", "branch deletion"),
            ("gh pr --repo $(printf fagenorn/nix-config) merge 1 --merge", "merge"),
            ("gh --repo $(printf fagenorn/nix-config) pr merge 1 --merge", "merge"),
            ("gh -R `printf x` release create v1.2.3", "release creation"),
            ("gh $(printf pr) merge 1 --merge", "merge"),
            # D19: an evaluator or env -S segment still recognises a run that
            # continues into a later segment.
            ("git -C $(sh -c pwd | cat) push origin main", "push"),
            ("git -c k=$(env -S pwd | cat) push origin main", "push"),
            ("gh pr --repo $(sh -c 'printf x' | cat) merge 1 --merge", "merge"),
            ("git -C /tmp/x -c a=b push origin issue-400-topic", "push"),
            ("git --no-pager branch -d issue-400-topic", "branch deletion"),
            ("/usr/bin/git branch -d issue-400-topic", "branch deletion"),
            ("/opt/homebrew/bin/gh release create v1.2.3 --repo fagenorn/nix-config "
             '--verify-tag --title "t" --notes-file /tmp/n.md', "release creation"),
            ("gh -R fagenorn/nix-config pr create --repo fagenorn/nix-config --base main "
             '--head t --title "x" --body "y"', "PR creation"),
            ("xargs git -C /tmp/x push origin issue-400-topic", "push"),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: unsafe {label}: ", result.stderr)
                self.assertIn(GRAMMAR, result.stderr)
        for command in (
            "git -C /tmp status --short",
            "git -C /tmp/x log --grep push",
            "git --no-pager log --oneline",
            "/usr/bin/git status",
            "gh pr view 1 --json mergeable",
            "gh pr list --state merged",
            "gh -R fagenorn/nix-config pr view 1",
            # D18 reads on only while the verb is uncertain.
            "git -C /tmp/x log $(printf HEAD)",
            "git log --format=$(printf %H) -1",
            "gh pr view $(printf 1) --json url",
            "gh -R fagenorn/nix-config pr view $(printf 1)",
            "git log $(sh -c pwd | cat) -1",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_git_invocations_that_could_transmit_refs_are_refused(self):
        """Issue 655 AC1, D2, D4-D9: a git invocation that could transmit refs and is
        not an admitted lifecycle form is refused as a push before any repository
        lookup, in each spelling the issue names and in every position the shell
        runs it from; local subcommands still pass."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        # A configured alias resolving to push: refused by name, never by reading it.
        subprocess.run(["git", "config", "alias.p", "push"], cwd=repo, check=True,
                       capture_output=True)
        topic = "issue-655-topic"
        url = "git@github.com:fagenorn/nix-config.git"
        unknown = ("is not a known local git subcommand; an alias, a git-* program "
                   "or a transport could transmit refs")
        evaluator = "shell source passed to an evaluator cannot be validated"
        split = "command text handed to env -S cannot be validated"
        uncertain = "the git invocation continues past a shell substitution or grouping"
        for command, reason in (
            (f"git -c alias.p=push p origin {topic}", "git global option -c is not accepted"),
            (f"git --config-env=alias.p=PUSH p origin {topic}",
             "git global option --config-env=alias.p=PUSH is not accepted"),
            ("git -c core.pager=cat diff", "git global option -c is not accepted"),
            ("git --exec-path=/tmp status",
             "git global option --exec-path=/tmp is not accepted"),
            (f"git p origin {topic}", f"git p {unknown}"),
            (f"git -C {repo} p origin {topic}", f"git p {unknown}"),
            (f"git status; git p origin {topic}", f"git p {unknown}"),
            (f"x=$(git p origin {topic})", f"git p {unknown}"),
            (f"git send-pack {url} {topic}", f"git send-pack {unknown}"),
            (f"git http-push https://example.invalid/x.git {topic}",
             f"git http-push {unknown}"),
            (f"git subtree push --prefix=x origin {topic}", f"git subtree {unknown}"),
            ("git submodule foreach true", f"git submodule {unknown}"),
            ("git bisect run true", f"git bisect {unknown}"),
            (f"git-push origin {topic}",
             "the git program git-push runs a git subcommand directly"),
            (f"/usr/libexec/git-core/git-push origin {topic}",
             "the git program git-push runs a git subcommand directly"),
            (f"/usr/libexec/git-core/git-send-pack {url} {topic}",
             "the git program git-send-pack runs a git subcommand directly"),
            (f"git $(printf p) origin {topic}", uncertain),
            ("git -C $(pwd) status", uncertain),
            (f"git add`echo -x` origin {topic}", uncertain),
            # D7: an argument position is judged by the same rule, whatever the runner.
            (f"xargs git p origin {topic}", f"git p {unknown}"),
            (f"timeout 5 git p origin {topic}", f"git p {unknown}"),
            (f"nice git p origin {topic}", f"git p {unknown}"),
            (f"find . -name x -exec git p origin {topic} +", f"git p {unknown}"),
            (f"xargs git send-pack {url} {topic}", f"git send-pack {unknown}"),
            (f"xargs git -c alias.p=push p origin {topic}",
             "git global option -c is not accepted"),
            (f"xargs git-push origin {topic}",
             "the git program git-push runs a git subcommand directly"),
            # D7: the accepted mention false positives.
            ("echo git p", f"git p {unknown}"),
            ("rg -n git README.md", f"git README.md {unknown}"),
            # D7: evaluator and env -S text, judged on its raw words.
            (f"eval git p origin {topic}", evaluator),
            (f"sh -c 'git p origin {topic}'", evaluator),
            (f"bash -c 'cd /tmp && git p origin {topic}'", evaluator),
            (f"sh -c '${{G:-git}} p origin {topic}'", evaluator),
            (f"sh -c \"g''it p origin {topic}\"", evaluator),
            (f"sh -c 'git send-pack {url} {topic}'", evaluator),
            (f"bash -c 'git -c alias.p=push p origin {topic}'", evaluator),
            (f"sh -c 'git-send-pack {url} {topic}'", evaluator),
            (f"env -S 'git p origin {topic}'", split),
            # A token-level refusal inside an evaluator segment reports the evaluator.
            ("eval git -C $(pwd) status", evaluator),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: unsafe push: {reason}", result.stderr)
                self.assertIn("; accepted: git push ", result.stderr)
                self.assertNotIn(GRAMMAR, result.stderr)
        for command in (
            "git status --short",
            f"git -C {repo} status",
            "git --no-pager log --oneline -1",
            "git --git-dir=.git log -1",
            "git --git-dir .git --work-tree . status",
            "git log $(printf HEAD) -1",
            "(git status)",
            "`git status`",
            "echo $(git rev-parse HEAD)",
            "echo $(which git)",
            "echo `which git`",
            "which git",
            "git rebase origin/main",
            "git rebase -i origin/main",
            "git fetch origin",
            "git worktree list",
            "git branch -D issue-655-old",
            "git config --get user.name",
            "git commit -m 'subtree push notes'",
            "git",
            "git --version",
            "/usr/bin/git status",
            "xargs git status",
            "timeout 5 git log -1",
            "echo 'git p'",
            "rg -n '[g]it' README.md",
            "grep -rn 'git send-pack' docs",
            "sh -c 'git status'",
            "env -S 'git status'",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))


    def test_command_running_git_options_and_environment_are_refused(self):
        """Issue 655 AC2, D11, D12: an allowlisted subcommand carrying an option whose
        value git runs as a command, and an assignment that hands git a command or
        other configuration, are refused as a push in every position; local
        spellings still pass."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        runs = "can run a command the guard cannot judge"
        assigns = "can make git run a command or read other configuration"
        evaluator = "shell source passed to an evaluator cannot be validated"
        force = "git push --force origin main"
        for command, reason in (
            (f"git fetch --upload-pack='{force} #' .",
             f"git fetch --upload-pack={force} # {runs}"),
            ("git fetch --upload=/tmp/p.sh .", f"git fetch --upload=/tmp/p.sh {runs}"),
            ("git pull --upload-pack=/tmp/p.sh origin main",
             f"git pull --upload-pack=/tmp/p.sh {runs}"),
            ("git ls-remote --upload-pack=/tmp/p.sh .",
             f"git ls-remote --upload-pack=/tmp/p.sh {runs}"),
            ("git ls-remote -u /tmp/p.sh .", f"git ls-remote -u {runs}"),
            ("git clone -u /tmp/p.sh . /tmp/x", f"git clone -u {runs}"),
            ("git clone -c core.fsmonitor=/tmp/p.sh . /tmp/x", f"git clone -c {runs}"),
            ("git clone --config=core.pager=x . /tmp/x",
             f"git clone --config=core.pager=x {runs}"),
            ("git clone --template=/tmp/t . /tmp/x", f"git clone --template=/tmp/t {runs}"),
            ("git init --template=/tmp/t /tmp/x", f"git init --template=/tmp/t {runs}"),
            ("git archive --remote=. --exec=/tmp/p.sh HEAD",
             f"git archive --exec=/tmp/p.sh {runs}"),
            ("git grep -O'sh /tmp/p.sh' x", f"git grep -Osh /tmp/p.sh {runs}"),
            ("git rebase --exec true HEAD~1", f"git rebase --exec {runs}"),
            ("git rebase -ix true HEAD~1", f"git rebase -ix {runs}"),
            ("git rebase --exe=true HEAD~1", f"git rebase --exe=true {runs}"),
            ("xargs git fetch --upload-pack=/tmp/p.sh .",
             f"git fetch --upload-pack=/tmp/p.sh {runs}"),
            ("sh -c 'git fetch --upload-pack=/tmp/p.sh .'", evaluator),
            # D12 (a): an assignment prefix of a git word must be allowlisted.
            (f"GIT_SEQUENCE_EDITOR='{force}; true' git rebase -i HEAD~1",
             f"the assignment GIT_SEQUENCE_EDITOR= {assigns}"),
            ("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.fsmonitor "
             "GIT_CONFIG_VALUE_0=/tmp/p.sh git status",
             f"the assignment GIT_CONFIG_COUNT= {assigns}"),
            ("GIT_CONFIG_PARAMETERS=\"'core.pager=x'\" git log",
             f"the assignment GIT_CONFIG_PARAMETERS= {assigns}"),
            ("env GIT_SSH_COMMAND=/tmp/p.sh git fetch origin",
             f"the assignment GIT_SSH_COMMAND= {assigns}"),
            ("GIT_EXEC_PATH=/tmp/x git status", f"the assignment GIT_EXEC_PATH= {assigns}"),
            ("PATH=/tmp/x:$PATH git log", f"the assignment PATH= {assigns}"),
            ("HOME=/tmp/h git log", f"the assignment HOME= {assigns}"),
            ("timeout 5 env GIT_EDITOR=/tmp/p.sh git commit",
             f"the assignment GIT_EDITOR= {assigns}"),
            # D12 (b): anywhere in the command.
            (f"export GIT_PAGER='{force}'; git log",
             f"the assignment GIT_PAGER= {assigns}"),
            (f"export PAGER='{force}'; git log", f"the assignment PAGER= {assigns}"),
            ("EDITOR=/tmp/p.sh; git commit", f"the assignment EDITOR= {assigns}"),
            ("sh -c 'GIT_PAGER=/tmp/p.sh git log'", evaluator),
            # The append spelling `NAME+=value` is an assignment too.
            (f"GIT_SEQUENCE_EDITOR+='{force}; true' git rebase -i HEAD~1",
             f"the assignment GIT_SEQUENCE_EDITOR= {assigns}"),
            (f"export GIT_PAGER+='{force}'; git log",
             f"the assignment GIT_PAGER= {assigns}"),
            ("GIT_SSH_COMMAND+=/tmp/p.sh git fetch origin",
             f"the assignment GIT_SSH_COMMAND= {assigns}"),
            ("env GIT_SSH_COMMAND+=/tmp/p.sh git fetch origin",
             f"the assignment GIT_SSH_COMMAND= {assigns}"),
            ("sh -c 'GIT_PAGER+=x git log'", evaluator),
            ("bash -c \"export GIT_SEQUENCE_EDITOR+=x; git rebase -i HEAD~1\"",
             evaluator),
            ("echo \"$(GIT_PAGER=/tmp/p.sh git log)\"",
             "a command substitution inside a quoted word cannot be validated"),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: unsafe push: {reason}", result.stderr)
                self.assertIn("; accepted: git push ", result.stderr)
        for command in (
            "git fetch origin",
            "git pull --ff-only origin main",
            "git ls-remote --heads origin",
            "git clone --depth 1 --quiet . /tmp/x",
            "git init --quiet /tmp/x",
            "git archive -o /tmp/a.tar HEAD",
            "git grep -n foo",
            "git rebase -i origin/main",
            "git rebase --empty=drop origin/main",
            "GIT_TRACE=1 git status",
            "GIT_AUTHOR_DATE=2026-01-01 git commit -m x",
            "LC_ALL=C git log -1",
            "env -u GITHUB_TOKEN git status",
            "export FOO=1; git status",
            "GIT_TRACE+=1 git status",
            "LC_ALL+=C git log -1",
            "echo $GIT_PAGER",
            "PYTHONPATH=python python3 -c pass",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_transmit_rule_reads_substitutions_spellings_and_stdin(self):
        """Issue 655 D2 and D7 review: a git word the shell runs from inside a
        double-quoted substitution, spelled `$'git'`, `git` plus a line
        continuation, `${G:-git}` or through an assigned variable, or handed to an
        evaluator on stdin or in a heredoc, is judged like a plain git word."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        subprocess.run(["git", "config", "alias.p", "push"], cwd=repo, check=True,
                       capture_output=True)
        topic = "issue-655-topic"
        unknown = ("is not a known local git subcommand; an alias, a git-* program "
                   "or a transport could transmit refs")
        evaluator = "shell source passed to an evaluator cannot be validated"
        quoted = "a command substitution inside a quoted word cannot be validated"
        for command, reason in (
            (f'echo "$(git p origin {topic})"', quoted),
            (f'x="$(git p origin {topic})"', quoted),
            (f'echo "`git p origin {topic}`"', quoted),
            (f"$'git' p origin {topic}", f"git p {unknown}"),
            (f"git\\\n p origin {topic}", f"git p {unknown}"),
            (f"${{G:-git}} p origin {topic}", f"git p {unknown}"),
            (f"G=git; $G p origin {topic}", f"git p {unknown}"),
            (f"G=/usr/bin/git; ${{G}} p origin {topic}", f"git p {unknown}"),
            (f"export G=git; \"$G\" p origin {topic}", f"git p {unknown}"),
            (f"G=git; \"${{G}}\" p origin {topic}", f"git p {unknown}"),
            (f"G=git; \"${{G:-x}}\" p origin {topic}", f"git p {unknown}"),
            (f"\"${{X:-git}}\" p origin {topic}", f"git p {unknown}"),
            (f"echo 'git p origin {topic}' | sh", evaluator),
            (f"sh <<'EOF'\ngit p origin {topic}\nEOF", evaluator),
            (f"sh -c 'git\\\n p origin {topic}'", evaluator),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: unsafe push: {reason}", result.stderr)
                self.assertNotIn(GRAMMAR, result.stderr)
        for command in (
            'echo "$(git status)"',
            'x="$(git rev-parse HEAD)"',
            'echo "`git status`"',
            "$'git' status",
            "git\\\n status",
            "${G:-git} status",
            "G=git; $G status",
            "G=x; $G p origin t",
            "G=x; \"${G}\" p origin t",
            "G=git; \"${G}\" status",
            "echo 'git status' | sh",
            "sh <<'EOF'\ngit status\nEOF",
            "sh -c 'git\\\n status'",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))
    def test_transmit_rule_reads_zsh_names_pipes_substitution_output_and_evaluator_text(self):
        """Issue 655 final review: a git word spelled `=git` (zsh) or by a name
        `hash`/`alias` binds to git, a git word that takes its subcommand from a pipe
        or a redirection, a git word that is the output of a substitution, an
        option hidden in an expansion or after a substitution, and evaluator text
        that assigns the command word or quotes a global-option operand are judged
        like a plain git word; the mention forms still pass."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        subprocess.run(["git", "config", "alias.p", "push"], cwd=repo, check=True,
                       capture_output=True)
        topic = "issue-655-topic"
        force = "git push --force origin main"
        unknown = ("is not a known local git subcommand; an alias, a git-* program "
                   "or a transport could transmit refs")
        evaluator = "shell source passed to an evaluator cannot be validated"
        uncertain = "the git invocation continues past a shell substitution or grouping"
        fed = "a git word with no subcommand reads its subcommand from a pipe or redirection"
        option = "can run a command the guard cannot judge"
        for command, reason in (
            (f"=git p origin {topic}", f"git p {unknown}"),
            ("=git push --force origin main", f"git push {unknown}"),
            (f"xargs =git p origin {topic}", f"git p {unknown}"),
            ("hash g=/usr/bin/git; g push --force origin main", f"git push {unknown}"),
            (f"hash g=/usr/bin/git; g p origin {topic}", f"git p {unknown}"),
            (f"hash -p /usr/bin/git g; g p origin {topic}", f"git g {unknown}"),
            (f"alias g=git; g p origin {topic}", f"git p {unknown}"),
            (f"echo p origin {topic} | xargs git", fed),
            ("echo push --force origin main | xargs git", fed),
            (f"printf 'p\\0origin\\0{topic}' | xargs -0 git", fed),
            (f"echo p | xargs git -C {repo}", fed),
            (f"xargs <args.txt git", fed),
            (f"echo p origin {topic} | {{ true; xargs git; }}", fed),
            (f"{{ xargs git; }} <<< 'push --force origin main'", fed),
            (f"while read -r a; do xargs git; done <<EOF\nx\np origin {topic}\nEOF", fed),
            (f"echo p origin {topic} | if true; then xargs git; fi", fed),
            (f"echo p origin {topic} |\nxargs git", fed),
            (f"echo p origin {topic} | \\\nxargs git", fed),
            ("exec < args.txt; xargs git", fed),
            (f"echo p origin {topic} | xargs ${{G:-git}}", fed),
            (f"echo p origin {topic} | xargs ${{G-git}}", fed),
            (f"echo p origin {topic} | xargs ${{G:=git}}", fed),
            (f'echo p origin {topic} | xargs "$(which git)"', uncertain),
            (f'echo p origin {topic} | xargs "`which git`"', uncertain),
            (f'echo p origin {topic} | xargs "$(command -v git)"', uncertain),
            (f"$(echo git) p origin {topic}", uncertain),
            (f"`echo git` p origin {topic}", uncertain),
            (f"xargs $(echo git) p origin {topic}", uncertain),
            (f"$(echo git; true) p origin {topic}", uncertain),
            (f'"$(which git)" push --force origin main', uncertain),
            (f'"$(which git)" p origin {topic}', uncertain),
            (f"G=$(which git); $G p origin {topic}", f"git p {unknown}"),
            (f'G="$(command -v git)"; "$G" p origin {topic}', f"git p {unknown}"),
            ("git rebase \"${X:---exec=git push --force origin HEAD:main}\" HEAD~1", option),
            (f"git rebase $(echo HEAD) --exec '{force}'", option),
            (f"git fetch $(git remote) --upload-pack='{force}'", option),
            (f"sh -c 'G=git; $G -c alias.p=push p --force origin main'", evaluator),
            (f"sh -c 'G=git; $G p origin {topic}'", evaluator),
            (f"G=git; sh -c '$G p origin {topic}'", evaluator),
            (f"sh -c 'hash g=/usr/bin/git; g p origin {topic}'", evaluator),
            (f"sh -c 'echo p origin {topic} | xargs git'", evaluator),
            (f"sh -c 'echo p origin {topic} | {{ true; xargs git; }}'", evaluator),
            (f"echo p | sh -c 'xargs git'", evaluator),
            (f"sh -c 'git -C \"/tmp status\" p origin {topic}'", evaluator),
            (f"bash -c \"git -C '/tmp status' p origin {topic}\"", evaluator),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn("lifecycle guard: unsafe push: ", result.stderr)
                self.assertIn(reason, result.stderr)
                self.assertNotIn(GRAMMAR, result.stderr)
        for command in (
            "which git",
            "brew install git",
            "echo $(which git)",
            'echo "$(which git)"',
            'x="$(which git)" y',
            "git log $(printf HEAD) -1",
            "echo $(git rev-parse HEAD) x",
            'cd "$(git rev-parse --show-toplevel)" && ls',
            "git rebase origin/main",
            "git rebase $(git merge-base HEAD origin/main) HEAD~1",
            "git rebase --onto origin/main HEAD~2 HEAD~1",
            "git fetch origin --depth=-1",
            "git clone --depth 1 --quiet . /tmp/x",
            "=git status",
            "xargs git status",
            "echo a | xargs git status",
            "echo a | xargs git -C /tmp status",
            "echo a | { true; xargs git status; }",
            'echo "$(which git)" | cat',
            "echo $(which git) | cat",
            "which git | cat",
            "echo a | grep -v b",
            "hash g=/usr/bin/git; g status",
            "G=$(which git); $G status",
            'G="$(which git)"; "$G" status',
            "sh -c 'G=git; $G status'",
            "sh -c 'git -C \"/tmp status\" status'",
            "sh -c 'echo a | xargs git status'",
            "sh -c 'git log --oneline'",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_git_dash_c_is_judged_against_its_target_repository(self):
        """Issue 400 AC2, D7, D8: `git -C <dir>` builds the push's repository context
        from <dir> joined to the payload cwd, one context per distinct directory."""
        here = self.make_repo("git@github.com:fagenorn/nix-config.git")
        there = self.make_repo("git@github.com:fagenorn/guard-fixture.git",
                               default_branch="trunk")
        foreign = self.make_repo("git@github.com:someoneelse/tool.git")
        tagged = self.tagged_repo("fagenorn/guard-fixture")
        # A repository directory whose basename is `git` (issue 400 D15).
        named = there.parent / "git"
        named.symlink_to(there)
        feature = "issue-400-topic"
        for command, cwd in (
            (f"git -C {there} push origin {feature}", here),
            (f"git -C {there} push origin main", here),
            (f"git -C {here} push origin {feature}", foreign),
            (f"git -C {there.name} push origin {feature}", there.parent),
            (f"git -C {tagged} push origin refs/tags/v1.2.3", here),
            (f"env -u GH_TOKEN git -C {there} push origin {feature}", here),
            (f"git -C {there.name} branch -d {feature}", None),
            (f"git -C {named} push origin {feature}", here),
        ):
            with self.subTest(command=command, cwd=cwd):
                result = self.run_guard(command, cwd=cwd)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        unknown = "unsafe push: repository unknown is outside standing authorization"
        grammar = "unsafe push: git -C takes one unquoted directory word followed by a single space"
        for command, cwd, reason in (
            (f"git -C {there} push origin trunk", here,
             "unsafe push: refusing to push the default branch trunk"),
            (f"git -C {foreign} push origin {feature}", here,
             "unsafe push: repository someoneelse/tool is outside standing authorization"),
            (f"git -C {there.name} push origin {feature}", None, unknown),
            (f"git -C {there}/missing push origin {feature}", here, unknown),
            # A second push is refused by the allowlist grammar (issue 418).
            (f"git -C {there} push origin main; git push origin trunk", here,
             f"unsafe push: `;` outside quotes; {GRAMMAR}"),
            (f"git -C {there} push origin main; git push origin main", here,
             f"unsafe push: `;` outside quotes; {GRAMMAR}"),
            (f"git push origin trunk; git -C {there} push origin trunk", here,
             f"unsafe push: `;` outside quotes; {GRAMMAR}"),
            (f"git -C {here} push origin refs/tags/v1.2.3", tagged,
             "unsafe push: v1.2.3 is not an existing annotated tag"),
            (f'git -C "{there}" push origin {feature}', here,
             f'unsafe push: `git -C "{there}"` is not a lifecycle verb; {GRAMMAR}'),
            (f"git -C {there}  push origin {feature}", here, grammar),
        ):
            with self.subTest(command=command, cwd=cwd):
                result = self.run_guard(command, cwd=cwd)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: {reason}", result.stderr)

    def test_a_push_or_pr_creation_after_cd_is_judged_against_that_directory(self):
        """Issue 418 D1-D3: one leading `cd <absolute dir> && ` moves a push's or PR
        creation's repository context to <dir>; any other directory change refuses."""
        here = self.make_repo("git@github.com:fagenorn/nix-config.git")
        there = self.make_repo("git@github.com:fagenorn/guard-fixture.git",
                               default_branch="trunk")
        foreign = self.make_repo("git@github.com:someoneelse/tool.git")
        feature = "issue-418-topic"
        create = ("gh pr create --repo fagenorn/guard-fixture --base trunk "
                  f'--head {feature} --title "x" --body "y"')
        for command, cwd in (
            (f"cd {there} && git push origin {feature}", here),
            (f"cd {there} && git push -u origin main", here),
            (f"cd {there} && {create}", here),
            (f"cd {there} && {create}", foreign),
            (f"unset GITHUB_TOKEN && cd {there} && git push origin {feature}", here),
            (f"cd {there} && env -u GITHUB_TOKEN git push origin {feature}", here),
            (f"cd {there.parent} && git -C {there.name} push origin {feature}", here),
            (f"cd {there} && git -C {here} push origin {feature}", foreign),
            (f"cd {there}/ && git push origin {feature}", None),
            # No repository-bound verb: nothing to judge.
            (f"cd {foreign} && ls", here),
            # A word that merely looks like a zsh special assignment, in argument
            # position, is data (final review of issue 418).
            ('gh pr create --repo fagenorn/nix-config --base main --head topic '
             '--title "options=fast" --body "y"', here),
            ('gh pr create --repo fagenorn/nix-config --base main --head topic '
             '--title "x" --body "functions=y"', here),
        ):
            with self.subTest(command=command, cwd=cwd):
                result = self.run_guard(command, cwd=cwd)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        for command, cwd, reason in (
            (f"cd {there} && git push origin trunk", here,
             "unsafe push: refusing to push the default branch trunk"),
            (f"cd {here} && git push origin main", there,
             "unsafe push: refusing to push the default branch main"),
            (f"cd {foreign} && git push origin {feature}", here,
             "unsafe push: repository someoneelse/tool is outside standing authorization"),
            (f"cd {foreign} && {create}", there,
             "unsafe PR creation: repository someoneelse/tool is outside standing authorization"),
            (f"cd {there} && " + create.replace('--body "y"', "--body-file /tmp/notes-418.md"),
             here, "unsafe PR creation: --body-file is accepted only when the PR creation "
                   "is the whole command"),
            # Merge and branch deletion keep their whole-command refusal.
            (f"cd {there} && gh pr merge 1 --repo fagenorn/guard-fixture --merge "
             "--delete-branch", there, "unsafe merge: forbidden character `&`"),
            (f"cd {there} && git branch -d {feature}", there,
             "unsafe branch deletion: forbidden character `&`"),
        ):
            with self.subTest(command=command, cwd=cwd):
                result = self.run_guard(command, cwd=cwd)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn(f"lifecycle guard: {reason}", result.stderr)
        unresolved = "the directory the verb runs in cannot be resolved"
        for label, command in (
            ("push", f"cd {there.name} && git push origin {feature}"),
            ("push", f"cd {there}/../{there.name} && git push origin {feature}"),
            ("push", f"cd {there} || git push origin {feature}"),
            ("push", f"cd {there}; git push origin {feature}"),
            ("push", f"cd {there}  && git push origin {feature}"),
            ("push", f"cd -P {there} && git push origin {feature}"),
            ("push", f'cd "{there}" && git push origin {feature}'),
            ("push", f"cd ~ && git push origin {feature}"),
            ("push", f"cd && git push origin {feature}"),
            ("push", f"pushd {there} && git push origin {feature}"),
            # Any backslash-newline continuation leaves the directory unresolved: an
            # apostrophe in a comment or a here-document body opens no quote in the
            # shell, so no quote tracking is trusted to join it (review of issue 418).
            ("push", f"cd\\\n {there} && git push origin {feature}"),
            ("push", f"c\\\nd {there} && git push origin trunk"),
            ("push", f"c\\\nd {foreign} && git push origin {feature}"),
            ("push", f"true # it's\nc\\\nd {there} && git push origin trunk"),
            ("push", f"cat <<EOF\nit's\nEOF\nc\\\nd {there} && git push origin trunk"),
            ("PR creation", f"true # it's\nc\\\nd {there} && {create}"),
            ("PR creation", f"cat <<EOF\nit's\nEOF\nc\\\nd {there} && {create}"),
            ("PR creation", f"c\\\nd {there} && {create}"),
            ("push", f"pu\\\nshd {there} && git push origin {feature}"),
            # A builtin, reserved word or zsh special-hash assignment can run a
            # directory change in the shell itself (final review of issue 418).
            ("push", f"trap 'cd {there}' DEBUG; git push origin trunk"),
            ("push", f"trap 'cd {there}' DEBUG\ngit push origin trunk"),
            ("push", f"trap 'cd {there}' ERR; false; git push origin trunk"),
            ("push", f"builtin trap 'cd {there}' DEBUG; git push origin trunk"),
            ("push", f"\"tr\"ap 'cd {there}' DEBUG; git push origin trunk"),
            ("push", f"functions[g]='cd {foreign}'; g && git push origin {feature}"),
            ("push", f"functions=(g 'cd {foreign}'); g && git push origin {feature}"),
            ("push", f"noglob cd {there} && git push origin trunk"),
            ("push", f"nocorrect cd {there} && git push origin trunk"),
            ("push", f"- cd {there} && git push origin trunk"),
            ("push", f"repeat 1 cd {there}; git push origin trunk"),
            ("push", f"mapfile -C 'cd {there} #' -c 1 x </dev/null; git push origin trunk"),
            ("push", f"alias g='cd {there}'; g; git push origin trunk"),
            ("push", 'eval "$(printf c)d ' + f'{there}"; git push origin trunk'),
            ("push", f"source {there}/env.sh; git push origin trunk"),
            ("push", f"emulate zsh -c 'cd {there}'; git push origin trunk"),
            ("PR creation", f"trap 'cd {there}' DEBUG; {create}"),
            ("PR creation", f"trap 'cd {there}' ERR; false; {create}"),
            ("PR creation", f"noglob cd {there} && {create}"),
            # A zsh glob qualifier runs code while the shell itself expands a
            # builtin's words or an array assignment (final review of issue 418).
            ("push", f"echo /(e:'cd {there}':); git push origin trunk"),
            ("push", f": /(e:'cd {foreign}':); git push origin {feature}"),
            ("push", f"print /(e{{cd {there}}}); git push origin trunk"),
            ("push", f"echo /(e.'c\"\"d {there}'.); git push origin trunk"),
            ("push", f"X=(/(e:'cd {there}':)); git push origin trunk"),
            ("push", f"X='/(e:cd {there}:)'; echo ${{~X}}; git push origin trunk"),
            ("PR creation", f"echo /(e:'cd {there}':) && {create}"),
            ("push", f"cd {there} && c\\\nd {here} && git push origin {feature}"),
            # A quote's span ends where the shell ends it, so a continuation after it
            # still splits the directory word (final review of issue 418).
            ("push", "echo \"'\" && c\\\nd " + f"{there} && git push origin trunk"),
            ("push", "echo \"'\"; c\\\nd " + f"{there} && git push origin trunk"),
            ("push", "echo \"'\"\nc\\\nd " + f"{there} && git push origin trunk"),
            ("push", 'echo "a\\\nb" && c\\\nd ' + f"{there} && git push origin trunk"),
            ("push", 'echo "\\"\'" && c\\\nd ' + f"{there} && git push origin trunk"),
            ("push", f"popd && git push origin {feature}"),
            ("push", f"chdir {there} && git push origin {feature}"),
            ("push", f"builtin cd {there} && git push origin {feature}"),
            ("push", f"cd {there} && cd {here} && git push origin {feature}"),
            ("push", f"cd {there} && true && git push origin {feature}"),
            ("push", f"git push origin {feature}; cd {there}"),
            ("push", f"while true; do git push origin {feature}; cd {there}; done"),
            ("push", f"(cd {there}) && git push origin {feature}"),
            ("push", f"eval 'cd {there}' && git push origin {feature}"),
            # Redirections before or attached to the directory word (review R1).
            ("push", f">/dev/null cd {there} && git push origin trunk"),
            ("push", f"> /dev/null cd {there} && git push origin trunk"),
            ("push", f"2>/dev/null cd {there} && git push origin trunk"),
            ("push", f"cd>/dev/null {there} && git push origin trunk"),
            ("push", f"cd {there} >/dev/null && git push origin {feature}"),
            ("push", f"cd {there} 2>&1 && git push origin {feature}"),
            # Chained redirections: a trailing operator takes the next word as its
            # target, so the directory word is still at a command position (final
            # review of issue 418).
            ("push", f">/dev/null> /dev/null cd {there} && git push origin trunk"),
            ("push", f">/dev/null>/dev/null cd {there} && git push origin trunk"),
            ("push", f">/dev/null>> /dev/null cd {there} && git push origin trunk"),
            ("push", f"X=1>/dev/null> /dev/null cd {there} && git push origin trunk"),
            ("PR creation", f">/dev/null> /dev/null cd {there} && {create}"),
            # zsh's clobber operators `>!` and `>>!` take a target too (final review
            # of issue 418, second round).
            ("push", f">! /dev/null cd {there} && git push origin trunk"),
            ("push", f">>! /dev/null cd {there} && git push origin trunk"),
            ("push", f">/dev/null>! /dev/null cd {there} && git push origin trunk"),
            ("push", f">/dev/null>>! /dev/null cd {there} && git push origin trunk"),
            ("push", f"X=1>! /dev/null cd {there} && git push origin trunk"),
            ("push", f">&! /dev/null cd {there} && git push origin trunk"),
            ("PR creation", f">/dev/null>! /dev/null cd {there} && {create}"),
            # A special-hash assignment at a command position still refuses.
            ("push", f"options[autocd]=on; git push origin {feature}"),
            ("push", f"X=1 options[autocd]=on; git push origin {feature}"),
            ("push", f"options=on; git push origin {feature}"),
            ("push", f"X=1 aliases=x; git push origin {feature}"),
            # Expansions that run a directory word (review R2).
            ("push", f"eval '${{CMD:-cd {there}}}' && git push origin trunk"),
            ("push", f"${{CMD:-cd}} {there} && git push origin trunk"),
            ("push", f"X=cd; $X {there} && git push origin trunk"),
            ("push", f"true $(cd {there}) && git push origin trunk"),
            # Wrapper options that set the directory.
            ("push", f"env -C {there} git push origin trunk"),
            ("push", f"env --chdir={there} git push origin trunk"),
            ("push", f"cd {there} && env -C {here} git push origin main"),
            ("PR creation", f"cd {there} && {create} && git push origin {feature}"),
            ("PR creation", f"cd {there.name} && {create}"),
            ("PR creation", f"popd && {create}"),
            ("PR creation", f">/dev/null cd {there} && {create}"),
            ("PR creation", f"cd>/dev/null {there} && {create}"),
            ("PR creation", f"eval '${{CMD:-cd {there}}}' && {create}"),
            ("PR creation", f"${{CMD:-cd}} {there} && {create}"),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=here)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                # The allowlist grammar now refuses most of these before any
                # directory is resolved; the rest keep the unresolved refusal.
                self.assertIn(f"lifecycle guard: unsafe {label}: ", result.stderr)
                self.assertTrue(unresolved in result.stderr or GRAMMAR in result.stderr,
                                result.stderr)
                self.assertIn("; accepted: ", result.stderr)

    def test_a_redirection_closed_by_a_spaced_bang_hides_no_directory_change_or_detaching_word(self):
        """Final review of issue 418, third round: in `>& ! cd <dir>` the `!` is the
        redirection's target, so `cd` (or `nohup`) is the command word. Only a `!`
        glued to the `&` closes zsh's `>&!`."""
        here = self.make_repo("git@github.com:fagenorn/nix-config.git")
        there = self.make_repo("git@github.com:fagenorn/guard-fixture.git",
                               default_branch="trunk")
        create = ("gh pr create --repo fagenorn/guard-fixture --base trunk "
                  "--head issue-418-topic --title t --body b")
        for label, command in (
            ("push", f">& ! cd {there} && git push origin trunk"),
            ("push", f"2>& ! cd {there} && git push origin trunk"),
            ("PR creation", f">& ! cd {there} && {create}"),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=here)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn(f"lifecycle guard: unsafe {label}: ", result.stderr)
        for command, word in (
            (">& ! nohup sleep 999", "nohup"),
            ("2>& ! setsid x", "setsid"),
            (">&! /dev/null nohup x", "nohup"),
            # A quoted `>` before zsh's glued `>&!`: one reading must take both
            # (review of the issue 418 allowlist).
            ("A='>' >&! t nohup sleep 1", "nohup"),
            ("A='>' 2>&! t setsid sleep 1", "setsid"),
            ("A='>' >&! t disown", "disown"),
        ):
            with self.subTest(command=command):
                self.assert_detaching_refusal(self.run_guard(command), word, command)

    def test_mixed_quoted_and_unquoted_redirections_hide_no_detaching_word(self):
        """Final review of issue 418, fourth round: a bare operator at the end of a
        word is a redirection or a quoted character, and each such word is read on
        its own. `X=> /dev/null` redirects, `>'log>'` is a quoted target, so in
        `X=> /dev/null >'log>' nohup x` the word `nohup` is the command."""
        for command, word in (
            ("X=> /dev/null >'log>' nohup sleep 999", "nohup"),
            ("X=> /dev/null >'log>' setsid sleep 999", "setsid"),
            ("X=> /dev/null >'log>' disown", "disown"),
            ("X='>' >/dev/null >'log>' nohup sleep 999", "nohup"),
            ("X=> t Y=> u >'log>' nohup x", "nohup"),
            ("X=> /dev/null Y='>' nohup x", "nohup"),
            # A quoted wrapper-option argument that starts with an operator is
            # the argument, not a redirection (final review, fifth round).
            ("env -u '>' nohup sleep 999", "nohup"),
            ("env -u '>x' nohup sleep 999", "nohup"),
            ("sudo -u '>' nohup x", "nohup"),
            ("env -u '>' setsid x", "setsid"),
            ("env -u '>x' disown", "disown"),
        ):
            with self.subTest(command=command):
                self.assert_detaching_refusal(self.run_guard(command), word, command)

    def test_lifecycle_verbs_are_admitted_only_in_the_allowed_grammar(self):
        """Issue 418 allowlist: a command holding a lifecycle verb is admitted only as
        [scrub && ][cd <dir> && ]<verb> <args> (or git -C <dir> push|branch -d), every
        word plain or quoted, before any other judgement."""
        here = self.make_repo("git@github.com:fagenorn/nix-config.git")
        there = self.make_repo("git@github.com:fagenorn/guard-fixture.git",
                               default_branch="trunk")
        sha = self.HEAD_SHA
        slug = "fagenorn/nix-config"
        topic = "issue-418-topic"
        create = f"gh pr create --repo {slug} --base main --head {topic}"
        merge = f"gh pr merge 418 --repo {slug} --merge"
        # Every form the shipped skills, deliver-standard and the forge adapter emit.
        for command, cwd in (
            (f"git -C {here} push origin {topic}", there),                   # deliver-*
            (f"git push origin {topic}", here),                               # the ship stage
            (f"git push -u origin {topic}", here),                            # the ship stage
            (f"git push origin --delete refs/heads/{topic}", here),           # the ship stage
            (f"git branch -d {topic}", here),                                 # the ship stage
            (f"git -C {here} branch -d {topic}", there),                      # deliver-standard
            (f"unset GITHUB_TOKEN && {create} --title 'Fix the guard' "
             "--body 'Why\n\nIt mattered.\n\nCloses #418'", here),            # deliver-*
            (f"unset GITHUB_TOKEN GH_TOKEN && {create} --title 't' --body 'b'", here),
            (f"{create} --title 'Fix (#418)' --body 'Closes #418'", here),    # no prefix
            (f'{create} --title "Fix the guard" --body "## Why\n\nCloses #418"', here),
            (f"unset GITHUB_TOKEN && {merge} --match-head-commit {sha} --delete-branch", here),
            (f"{merge} --match-head-commit {sha} --delete-branch", here),     # deliver-*
            (f'{merge} --subject "Fix the guard (#418)" --match-head-commit {sha} '
             "--delete-branch", here),                                        # the ship stage
            (f"cd {there} && git push origin {topic}", here),
            (f"unset GITHUB_TOKEN && cd {here} && {create} --title t --body b", there),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=cwd)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        for label, command in (
            # Operators, chains and redirections.
            ("push", f"git status && git push origin {topic}"),
            ("push", f"true && git push origin {topic}"),
            ("push", f"echo cd {there} && git push origin {topic}"),
            ("push", f"git push origin {topic}; echo done"),
            ("push", f"git push origin {topic} | cat"),
            ("push", f"git push origin {topic} || true"),
            ("push", f"git push origin {topic} &"),
            ("push", f"git push origin {topic} >/dev/null"),
            ("push", f"git push origin {topic} 2>&1"),
            ("push", f"git push origin {topic} </dev/null"),
            ("push", f"(git push origin {topic})"),
            ("push", f"{{ git push origin {topic}; }}"),
            ("push", f"! git push origin {topic}"),
            ("push", f"git push origin {topic}\necho done"),
            ("push", f"git push origin {topic} # comment"),
            ("push", f"cd {there}; git push origin {topic}"),
            ("push", f"cd {there} && cd {here} && git push origin {topic}"),
            ("push", f"cd {there} && true && git push origin {topic}"),
            ("push", f"true && env -u GH_TOKEN git push origin {topic}"),
            ("push", f"git push origin {topic} && echo \"cd {there}\""),
            ("push", f"true && echo ok && git push origin {topic}"),
            ("push", f"echo aliases=x && git push origin {topic}"),
            # Expansions, quoting and glob characters outside the plain-word set.
            ("push", "git push origin $BRANCH"),
            ("push", "git push origin `echo x`"),
            ("push", f"git push origin {topic}\\"),
            ("push", "git push origin ${B:-x}"),
            ("push", "git push origin x*"),
            ("push", "git push origin x?"),
            ("push", "git push origin [x]"),
            ("push", "git push origin ~x"),
            ("push", "git push origin =git"),
            ("push", f"git push origin {topic}'x'"),
            ("push", f"git push origin \"{topic}\"x"),
            ("push", f"cd ~ && git push origin {topic}"),
            ("push", f"cd '{there}' && git push origin {topic}"),
            ("push", f"cd \"{there}\" && git push origin {topic}"),
            ("PR creation", f"{create} --title 'a' --body 'unterminated"),
            ("PR creation", f'{create} --title "a$b" --body b'),
            ("PR creation", f'{create} --title "a`b`" --body b'),
            ("PR creation", f'{create} --title "a\\b" --body b'),
            ("PR creation", f'{create} --title "a!b" --body b'),
            ("PR creation", f"{create} --title='x' --body b"),
            # Words before the verb other than one scrub prefix and one cd.
            ("push", f"X=1 git push origin {topic}"),
            ("push", f"command git push origin {topic}"),
            ("push", f"noglob git push origin {topic}"),
            ("push", f"env -C {there} git push origin {topic}"),
            ("push", f"sudo -u x git push origin {topic}"),
            ("push", f"/usr/bin/git push origin {topic}"),
            ("push", f"git -c x=y push origin {topic}"),
            ("PR creation", f"cd {here} && unset GITHUB_TOKEN && {create} --title t --body b"),
            ("PR creation", f"unset PATH && {create} --title t --body b"),
            ("merge", f"unset GITHUB_TOKEN; {merge} --delete-branch"),
            ("release creation", f"gh release new v1.2.3 --repo {slug} --verify-tag "
                                 "--title v --notes-file /tmp/n.md && true"),
            ("branch deletion", f"git branch -d {topic} && git branch -d other"),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=here)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn(f"lifecycle guard: unsafe {label}: ", result.stderr)
                self.assertIn(GRAMMAR, result.stderr)
                self.assertIn("; accepted: ", result.stderr)

    def test_pr_creation_and_merge_are_judged_against_the_repository_they_name(self):
        """Issue 418 D4-D7: a `--repo` slug with a derived row, other than the
        directory's repository, is judged from that row, never from the directory."""
        here = self.make_repo("git@github.com:fagenorn/nix-config.git")
        plain = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        create = ('gh pr create --repo {slug} --base {base} --head issue-418-topic '
                  '--title "x" --body "y"')
        merge = "gh pr merge 418 --repo {slug} --merge --delete-branch"
        for command, cwd, env in (
            (create.format(slug=NODO, base="dev"), here, {}),
            (create.format(slug=NODO, base="main"), here, {}),
            ("unset GITHUB_TOKEN && " + create.format(slug=NODO, base="dev"), here, {}),
            (create.format(slug=NODO, base="dev"), plain, {}),
            (create.format(slug=NODO, base="dev"), None, {}),
            (f"cd {here} && " + create.format(slug=NODO, base="dev"), plain, {}),
            (merge.format(slug=NODO), here, {}),
            ("unset GITHUB_TOKEN && " + merge.format(slug=NODO), None, {}),
            (f"gh pr merge 1484 --repo {NODO} --merge", here, self.release_env()),
        ):
            with self.subTest(command=command, cwd=cwd):
                result = self.run_guard(command, cwd=cwd, env=env)
                self.assertEqual(0, result.returncode, (command, result.stderr))
        unconfirmed = (f"repository {NODO}: the row check did not confirm its derived "
                       "policy row: unavailable (registry_invalid)")
        for command, cwd, env, reason in (
            (create.format(slug=NODO, base="release"), here, {},
             "unsafe PR creation: --base release is not one of dev, main"),
            (create.format(slug=NODO, base="dev"), here, {"FAKE_DERIVE_MODE": "unavailable"},
             f"unsafe PR creation: {unconfirmed}"),
            (merge.format(slug=NODO), here, {"FAKE_DERIVE_MODE": "unavailable"},
             f"unsafe merge: {unconfirmed}"),
            (create.format(slug=NODO, base="dev").replace('--body "y"',
                                                          "--body-file /tmp/notes-418.md"),
             here, {}, "unsafe PR creation: cannot resolve the working tree to check "
                       "--body-file against"),
            # No row: the directory's refusal stands.
            (create.format(slug="fagenorn/argus", base="main"), here, {},
             "unsafe PR creation: --repo fagenorn/argus is not the current repository "
             "fagenorn/nix-config"),
            (merge.format(slug="fagenorn/argus"), here, {},
             "unsafe merge: --repo fagenorn/argus is not the current repository "
             "fagenorn/nix-config"),
            (merge.format(slug="elevenyellow/other"), None, {},
             "unsafe merge: repository unknown is outside standing authorization"),
            # Release creation stays judged against the directory.
            (f'gh release create v1.2.3 --repo {NODO} --verify-tag --title "v1.2.3" '
             "--notes-file /tmp/notes.md", here, {},
             f"unsafe release creation: --repo {NODO} is not the current repository "
             "fagenorn/nix-config"),
        ):
            with self.subTest(command=command, cwd=cwd):
                result = self.run_guard(command, cwd=cwd, env=env)
                self.assertEqual(2, result.returncode, (command, result.stderr))
                self.assertIn(f"lifecycle guard: {reason}", result.stderr)
        # The named repository's row is checked once and the directory's context, which
        # has no row here, runs none.
        log = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "derive.log"
        result = self.run_guard(create.format(slug=NODO, base="dev"),
                                cwd=here, env={"FAKE_DERIVE_LOG": str(log)})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"{NODO}\n", log.read_text(encoding="utf-8"))
        # The reverse direction: a slug with no row, named from a checkout that has
        # one, keeps that checkout's refusal after its own row check.
        log.unlink()
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        result = self.run_guard(create.format(slug="fagenorn/nix-config", base="main"),
                                cwd=nodo, env={"FAKE_DERIVE_LOG": str(log)})
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("lifecycle guard: unsafe PR creation: --repo fagenorn/nix-config is "
                      f"not the current repository {NODO}", result.stderr)
        self.assertEqual(f"{NODO}\n", log.read_text(encoding="utf-8"))

    def test_tag_push_near_misses_are_refused(self):
        repo = self.tagged_repo("fagenorn/nix-config")
        lightweight = self.tagged_repo("fagenorn/nix-config", tag="v2.0.0", annotated=False)
        for command, cwd in (
                ("git push origin refs/tags/v2.0.0", lightweight),
                ("git push origin refs/tags/v1.2", repo),
                ("git push origin refs/tags/release-1", repo),
                ("git push origin refs/heads/v1.2.3", repo),
                ("git push origin +refs/tags/v1.2.3", repo),
                ("git push origin refs/tags/v1.2.3 extra", repo),
                ("git push --force origin refs/tags/v1.2.3", repo),
                ("git push origin refs/tags/v9.9.9", repo)):
            with self.subTest(command=command):
                self.assertEqual(2, self.run_guard(command, cwd=cwd).returncode)
        other = self.tagged_repo("someone-else/nix-config")
        self.assertEqual(2, self.run_guard("git push origin refs/tags/v1.2.3", cwd=other).returncode)

    def test_release_create_near_misses_are_refused(self):
        repo = self.tagged_repo("fagenorn/nix-config")
        base = 'gh release create v1.2.3 --repo fagenorn/nix-config --verify-tag --title "v1.2.3 — r" --notes-file /tmp/n.md'
        self.assertEqual(0, self.run_guard(base, cwd=repo).returncode)
        self.assertEqual(0, self.run_guard("unset GITHUB_TOKEN && " + base, cwd=repo).returncode)
        for command in (
                base.replace(" --verify-tag", ""),
                base.replace("--verify-tag --title", "--title").replace("/tmp/n.md", "/tmp/n.md --verify-tag"),
                base.replace("--verify-tag", "--target main"),
                base.replace("--repo fagenorn/nix-config", "--repo fagenorn/other"),
                base.replace('"v1.2.3 — r"', '"v1.2.3 $(id)"'),
                base.replace("/tmp/n.md", "notes.md"),
                base + "; true",
                "true; " + base,
                base + " && true",
                base.replace("create v1.2.3", "create 1.2.3"),
                # `gh release new` is gh's alias of `create`
                "gh release new v1.2.3 --repo someone-else/x --target main --draft",
                base.replace("release create", "release new")):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)

    def test_feature_arm_never_deletes_a_permanent_branch(self):
        """#116 D5: dev -> main and main -> dev both refuse --delete-branch."""
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 7 --repo elevenyellow/nodocom --merge --delete-branch"
        for head, base in (("dev", "main"), ("main", "dev")):
            with self.subTest(head=head, base=base):
                env = {"FAKE_PR_JSON": json.dumps({
                    "state": "OPEN", "baseRefName": base, "headRefName": head,
                    "url": "https://github.com/elevenyellow/nodocom/pull/7",
                    "statusCheckRollup": []})}
                result = self.run_guard(merge, cwd=repo, env=env)
                self.assertEqual(2, result.returncode)
                self.assertIn("permanent branch", result.stderr)

    def test_feature_arm_refuses_an_uncertain_head(self):
        """The head is the thing --delete-branch deletes: unreadable means refused."""
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 7 --repo elevenyellow/nodocom --merge --delete-branch"
        base = {"state": "OPEN", "baseRefName": "dev",
                "url": "https://github.com/elevenyellow/nodocom/pull/7", "statusCheckRollup": []}
        for label, extra in (("missing", {}), ("null", {"headRefName": None}),
                             ("empty", {"headRefName": ""}), ("number", {"headRefName": 7})):
            with self.subTest(head=label):
                env = {"FAKE_PR_JSON": json.dumps({**base, **extra}),
                       "FAKE_PROTECTION_MODE": "nonzero"}
                result = self.run_guard(merge, cwd=repo, env=env)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("cannot read the PR head branch", result.stderr)

    # ------------------------------------------------------------------
    # Policy trust split (issue 377) and derived rows (issue 126): the base
    # policy, the compiled file the hook reads, and the rows a registered
    # project is judged by.
    # ------------------------------------------------------------------

    COMPILED_ROW_SHAPES = {
        "derived_repositories is a list": {"derived_repositories": []},
        "derived key is not a slug": {"derived_repositories": {"nodocom": NODO_ROW}},
        "row is not an object": {"derived_repositories": {NODO: "dev"}},
        "row lacks evidence": {"derived_repositories": {
            NODO: {"default_branch": "main", "integration_branch": "dev",
                   "required_checks": []}}},
        "row has an extra member": {"derived_repositories": {NODO: {**NODO_ROW, "owner": "x"}}},
        "empty branch": {"derived_repositories": {NODO: {**NODO_ROW, "integration_branch": ""}}},
        "branch is not a ref name": {
            "derived_repositories": {NODO: {**NODO_ROW, "default_branch": "main; true"}}},
        "branch is not a string": {"derived_repositories": {NODO: {**NODO_ROW, "default_branch": None}}},
        "evidence is not an object": {"derived_repositories": {NODO: {**NODO_ROW, "evidence": []}}},
        "the schema-2 row shape": {"derived_repositories": {
            NODO: {"default_branch": "main", "integration_branch": "dev", "evidence": {}}}},
        "required_checks is null": {"derived_repositories": {
            NODO: {**NODO_ROW, "required_checks": None}}},
        "required_checks is not a list": {"derived_repositories": {
            NODO: {**NODO_ROW, "required_checks": "CI"}}},
        "a required check is empty": {"derived_repositories": {
            NODO: {**NODO_ROW, "required_checks": ["CI", ""]}}},
        "a required check is not a string": {"derived_repositories": {
            NODO: {**NODO_ROW, "required_checks": ["CI", 7]}}},
        "a required check repeats": {"derived_repositories": {
            NODO: {**NODO_ROW, "required_checks": ["CI", "CI"]}}},
        "derivation is a list": {"derived_repositories": {NODO: NODO_ROW}, "derivation": []},
        "production is null": {"derived_repositories": {NODO: {**NODO_ROW, "production": None}}},
        "production is a list": {"derived_repositories": {NODO: {**NODO_ROW, "production": []}}},
        "production lacks release_profile": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {"changes": [], "read_only": []}}}},
        "production has an extra member": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {**PRODUCTION, "owner": []}}}},
        "production key_files is not a list": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {**TOOL_PRODUCTION, "key_files": "deploy/*.yaml"}}}},
        "a key file glob is empty": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {**TOOL_PRODUCTION, "key_files": [""]}}}},
        "a key file glob is not a string": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {**TOOL_PRODUCTION, "key_files": [7]}}}},
        "production mcp_tools is not a list": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {
                **TOOL_PRODUCTION, "mcp_tools": "mcp__deployer__apply"}}}},
        "an MCP tool is not an mcp__ name": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {**TOOL_PRODUCTION, "mcp_tools": ["deploy"]}}}},
        "an MCP tool names a server only": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {**TOOL_PRODUCTION, "mcp_tools": ["mcp__deployer"]}}}},
        "production changes is not a list": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {**PRODUCTION, "changes": {}}}}},
        "production read_only is not a list": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {**PRODUCTION, "read_only": "just build"}}}},
        "a production command lacks argv": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {**PRODUCTION, "changes": [{"id": "deploy"}]}}}},
        "a production command has an extra member": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {
                **PRODUCTION,
                "changes": [{"id": "deploy", "argv": ["just"], "cwd": "."}]}}}},
        "a production id is empty": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {
                **PRODUCTION, "changes": [{"id": "", "argv": ["just", "switch"]}]}}}},
        "a production argv is empty": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {
                **PRODUCTION, "changes": [{"id": "deploy", "argv": []}]}}}},
        "a production argv is a string": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {
                **PRODUCTION, "changes": [{"id": "deploy", "argv": "just switch"}]}}}},
        "a production argv word is empty": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {
                **PRODUCTION, "read_only": [{"id": "check", "argv": ["just", ""]}]}}}},
        "a production argv word is not a string": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {
                **PRODUCTION, "read_only": [{"id": "check", "argv": ["just", 7]}]}}}},
        "release_profile is empty": {"derived_repositories": {
            NODO: {**NODO_ROW, "production": {**PRODUCTION, "release_profile": ""}}}},
        "missing derivation": {"derived_repositories": {NODO: NODO_ROW}, "derivation": ABSENT},
        "an extra member": {"derived_repositories": {NODO: NODO_ROW}, "grants": []},
    }

    @staticmethod
    def installed_launcher(command):
        """The launcher of this checkout's flake output `packages.<system>.agent-platform`, the package every host installs, so a hook pinned to an older package revision differs."""
        system = {("Darwin", "arm64"): "aarch64-darwin", ("Linux", "x86_64"): "x86_64-linux"}[
            (platform.system(), platform.machine())]
        root = Path(__file__).resolve().parents[1]
        done = subprocess.run(
            ["nix", "--extra-experimental-features", "nix-command flakes", "eval", "--raw",
             f"{root}#packages.{system}.agent-platform.launchers.{command}"],
            capture_output=True, text=True, timeout=600, check=False)
        if done.returncode != 0:
            raise AssertionError(f"nix eval of the {command} launcher failed:\n{done.stderr[-4000:]}")
        return done.stdout

    def test_built_base_policy_holds_exactly_the_five_trusted_members(self):
        """Issue 377 R1, R5; issue 384 D3: the store file holds the trusted members and no
        literal integration row, since every repository with one is a registered project."""
        self.assertEqual({"authorized_owners", "integration_bases", "git_bin", "gh_bin", "jq_bin"},
                         set(self.base_policy))
        self.assertEqual(["fagenorn"], self.base_policy["authorized_owners"])
        self.assertEqual({}, self.base_policy["integration_bases"])
        for member, name in (("git_bin", "git"), ("gh_bin", "gh"), ("jq_bin", "jq")):
            self.assertRegex(self.base_policy[member], rf"^/nix/store/[^/]+/bin/{name}$")
        source = Path(__file__).resolve().parents[1] / "home/common/claude-code/default.nix"
        text = source.read_text(encoding="utf-8")
        self.assertEqual([], [name for name in ("elevenyellow", "fagenorn/arcwave")
                              if name in text])

    def test_registered_hook_names_the_base_policy_compiled_policy_and_row_check(self):
        wrapper = self.guard.read_text(encoding="utf-8")
        self.assertRegex(wrapper, r'--base-policy /nix/store/\S+-claude-bash-lifecycle-guard-'
                                  r'base-policy\.json --policy /\S+/\.agents/state/guard/'
                                  r'policy\.json --derive-bin /nix/store/\S+-claude-guard-'
                                  r'row-check --land-bin /nix/store/\S+-claude-guard-land-check "\$@"\n')
        self.assertIn(f"--base-policy {BASE_POLICY_PATH} ", wrapper)
        row_check = Path(wrapper.split("--derive-bin ", 1)[1].split(" ", 1)[0])
        script = row_check.read_text(encoding="utf-8")
        self.assertRegex(script, r'\A#!/nix/store/\S+/bin/\S+ -p\nunset BASH_ENV ENV\n')
        self.assertRegex(script, r'export PATH="/nix/store/\S+-git-[^:"]+/bin:')
        self.assertIn(f'exec {self.installed_launcher("guard-policy")} derive "$@"\n', script)
        launcher = Path(script.split("exec ", 1)[1].split(" ", 1)[0])
        self.assertRegex(launcher.read_text(encoding="utf-8"), r'\A#!/nix/store/\S+/bin/\S+ -p\n')

    def test_a_compiled_policy_cannot_add_an_owner(self):
        """Issue 377 criterion 1, R1: an owner in the compiled policy grants nothing."""
        repo = self.make_repo("git@github.com:intruder/tool.git")
        for name, policy in (
            ("beside the rows", self.write_policy(authorized_owners=["intruder"])),
            ("as the seven-member shape", self.write_policy(
                **{**self.base_policy, "authorized_owners": ["fagenorn", "intruder"]})),
        ):
            args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
            for label, command in (
                ("push", "git push -u origin topic"),
                ("PR creation", 'gh pr create --repo intruder/tool --base main --head t '
                                '--title "x" --body "y"'),
                ("merge", "gh pr merge 7 --repo intruder/tool --merge --delete-branch"),
                ("release creation", 'gh release create v1.2.3 --repo intruder/tool '
                                     '--verify-tag --title "v1.2.3" --notes-file notes.md'),
            ):
                with self.subTest(policy=name, verb=label):
                    result = self.run_guard(command, cwd=repo, guard_args=args)
                    self.assertEqual(2, result.returncode, command)
                    self.assertIn(f"lifecycle guard: unsafe {label}: repository intruder/tool "
                                  "is outside standing authorization", result.stderr)

    def test_a_compiled_policy_cannot_substitute_the_tools(self):
        """Issue 377 criterion 2, R1: no program the compiled policy names is ever run.

        The fake `gh` comes from a fixture base policy, never `--gh-bin`: an override
        takes precedence over every policy value, so it would hide a guard that took
        `gh_bin` from the compiled policy."""
        base = self.write_base(gh_bin=str(self.fake_gh))
        markers = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        tools = {}
        for member in ("git_bin", "gh_bin", "jq_bin"):
            tool = markers / member
            tool.write_text(f"#!/bin/sh\ntouch {markers / (member + '.ran')}\nexit 0\n",
                            encoding="utf-8")
            tool.chmod(0o755)
            tools[member] = str(tool)
        tampered = self.write_policy(derived_repositories={NODO: NODO_ROW}, derivation={},
                                     **tools)
        repo = self.make_repo("git@github.com:fagenorn/tool.git")
        for command in ("git push -u origin topic",
                        "gh pr merge 7 --repo fagenorn/tool --merge --delete-branch"):
            with self.subTest(command=command):
                untampered = self.run_guard(command, cwd=repo,
                                            guard_args=("--base-policy", str(base)))
                self.assertEqual(0, untampered.returncode, untampered.stderr)
                result = self.run_guard(command, cwd=repo, guard_args=(
                    "--base-policy", str(base), "--policy", str(tampered)))
                self.assertEqual((0, untampered.stderr), (result.returncode, result.stderr))
        self.assertEqual([], sorted(path.name for path in markers.glob("*.ran")))

    def test_a_row_beside_a_literal_integration_base_is_refused(self):
        """Issue 377 D5: the compiled policy cannot recast a literal repository."""
        slug = "fagenorn/literal-fixture"
        base = self.write_base(integration_bases={slug: "dev"})
        policy = self.write_policy(derivation={}, derived_repositories={
            slug: {"default_branch": "trunk", "integration_branch": "release",
                   "required_checks": [], "evidence": {}}})
        args = ("--gh-bin", str(self.fake_gh), "--base-policy", str(base),
                "--policy", str(policy))
        repo = self.make_repo(f"git@github.com:{slug}.git")
        for label, command in (
            ("push", "git push -u origin topic"),
            ("PR creation", f'gh pr create --repo {slug} --base release --head t '
                            '--title "x" --body "y"'),
            ("merge", f"gh pr merge 7 --repo {slug} --merge --delete-branch"),
        ):
            with self.subTest(verb=label):
                result = self.run_guard(command, cwd=repo, guard_args=args)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(
                    f"lifecycle guard: unsafe {label}: repository {slug} has both a literal "
                    "integration base and a derived policy row; repair: run claude-guard-policy",
                    result.stderr)
        literal_only = self.run_guard("git push -u origin topic", cwd=repo, guard_args=(
            "--gh-bin", str(self.fake_gh), "--base-policy", str(base)))
        self.assertEqual(0, literal_only.returncode, literal_only.stderr)

    def test_a_row_carrying_production_rules_loads_and_the_row_check_ignores_them(self):
        """Issue 1149 D2: a derived row may carry `production`; the row check compares the
        branches and required checks only, so a row check answering without it still agrees."""
        policy = self.write_policy(
            derived_repositories={NODO: {**NODO_ROW, "production": PRODUCTION}}, derivation={})
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        result = self.run_guard("git push -u origin topic", cwd=nodo, guard_args=(
            "--gh-bin", str(self.fake_gh), "--policy", str(policy)))
        self.assertEqual(0, result.returncode, result.stderr)

    def test_a_row_carrying_key_files_and_mcp_tools_loads(self):
        """Issue 1150 D1: a derived row's `production` may also carry `key_files` and
        `mcp_tools`; the file still loads, so a Nodo push passes."""
        policy = self.write_policy(
            derived_repositories={NODO: {**NODO_ROW, "production": TOOL_PRODUCTION}},
            derivation={})
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        result = self.run_guard("git push -u origin topic", cwd=nodo, guard_args=(
            "--gh-bin", str(self.fake_gh), "--policy", str(policy)))
        self.assertEqual(0, result.returncode, result.stderr)

    def test_a_bad_compiled_policy_contributes_no_row(self):
        """Issue 377 D4, R4: the whole file is dropped and nothing the base allows is blocked."""
        fixtures = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        (fixtures / "directory").mkdir()
        (fixtures / "not-json.json").write_text("{", encoding="utf-8")
        unreadable = self.write_policy(derived_repositories={NODO: NODO_ROW}, derivation={})
        unreadable.chmod(0)
        # A FIFO with no writer would block a plain open, and /dev/zero never ends, so
        # each must be refused by its file type before a read; the oversized file is a
        # valid policy for Nodo padded past the 1 MiB cap with trailing whitespace.
        os.mkfifo(fixtures / "fifo.json")
        (fixtures / "zero.json").symlink_to("/dev/zero")
        oversized = self.write_policy(derived_repositories={NODO: NODO_ROW}, derivation={})
        with oversized.open("a", encoding="utf-8") as stream:
            stream.write(" " * (1 << 20))
        shapes = {
            "missing": fixtures / "absent.json",
            "a directory": fixtures / "directory",
            "unreadable": unreadable,
            "not JSON": fixtures / "not-json.json",
            "a FIFO": fixtures / "fifo.json",
            "a link to /dev/zero": fixtures / "zero.json",
            "over the size cap": oversized,
            "the seven-member shape": self.write_policy(
                **{**self.base_policy, "derived_repositories": {NODO: NODO_ROW},
                   "derivation": {}}),
            **{name: self.write_policy(**members)
               for name, members in self.COMPILED_ROW_SHAPES.items()},
        }
        literal = self.make_repo("git@github.com:fagenorn/tool.git")
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        for name, path in shapes.items():
            with self.subTest(policy=name):
                args = ("--gh-bin", str(self.fake_gh), "--policy", str(path))
                self.assertEqual(0, self.invoke_command("true", *args).returncode)
                allowed = self.run_guard("git push -u origin topic", cwd=literal, guard_args=args)
                self.assertEqual(0, allowed.returncode, allowed.stderr)
                refused = self.run_guard("git push -u origin topic", cwd=nodo, guard_args=args)
                self.assertEqual(2, refused.returncode)
                self.assertIn(f"lifecycle guard: unsafe push: repository {NODO} is outside "
                              "standing authorization; the compiled policy contributed no row: ",
                              refused.stderr)
                self.assertIn("; repair: run claude-guard-policy", refused.stderr)
        control = self.run_guard("git push -u origin topic", cwd=nodo)
        self.assertEqual(0, control.returncode, control.stderr)

    def test_a_bad_base_policy_blocks_every_call(self):
        """Issue 377 R4: the store file is an installation defect, so even `true` is refused."""
        fixtures = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        (fixtures / "not-json.json").write_text("{", encoding="utf-8")
        unreadable = self.write_base()
        unreadable.chmod(0)
        shapes = {
            "missing": fixtures / "absent.json",
            "a directory": fixtures,
            "unreadable": unreadable,
            "not JSON": fixtures / "not-json.json",
            "a missing member": self.write_base(jq_bin=ABSENT),
            "an extra member": self.write_base(grants=[]),
            "the #375 seven-member shape": self.write_base(derived_repositories={},
                                                           derivation=None),
            "owners is not a list": self.write_base(authorized_owners="fagenorn"),
            "an empty integration base": self.write_base(integration_bases={"a/b": ""}),
            "a relative tool": self.write_base(git_bin="git"),
        }
        for name, path in shapes.items():
            with self.subTest(base=name):
                result = self.invoke_command("true", "--base-policy", str(path))
                self.assertEqual(2, result.returncode, name)
                self.assertIn("lifecycle guard: invalid policy:", result.stderr)
        control = self.invoke_command("true", "--base-policy", str(self.write_base()))
        self.assertEqual(0, control.returncode, control.stderr)

    def test_the_compiled_policy_is_opened_after_the_detaching_check(self):
        """Issue 1149 D4. The compiled path is a FIFO whose writer waits in `open`, which
        returns once any reader opens the FIFO, so an open by the guard shows as that `open`
        returning. Every call past the detaching check opens the compiled policy for the
        production rules; only a repository-bound verb, the push here, runs the row check."""
        repo = self.make_repo("https://github.com/fagenorn/argus.git")
        for command, status, opens in (("true", 0, True),
                                       ("git branch -d issue-30-safe", 0, True),
                                       ("setsid x", 2, False),
                                       ("git push -u origin topic", 0, True)):
            with self.subTest(command=command):
                fifo = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "policy.json"
                os.mkfifo(fifo)
                opened = threading.Event()

                def wait_for_a_reader(fifo=fifo, opened=opened):
                    os.close(os.open(fifo, os.O_WRONLY))
                    opened.set()

                writer = threading.Thread(target=wait_for_a_reader, daemon=True)
                writer.start()
                try:
                    result = self.invoke_command_in(command, repo, "--gh-bin", str(self.fake_gh),
                                                    "--policy", str(fifo))
                    self.assertEqual(status, result.returncode, result.stderr)
                    self.assertEqual(opens, opened.wait(1))
                finally:
                    release = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
                    writer.join(5)
                    os.close(release)

    def test_base_policy_alone_loads_and_authorizes_no_nodo_verb(self):
        base = ("--gh-bin", str(self.fake_gh), "--policy", str(self.write_policy()))
        self.assertEqual(0, self.invoke_command("true", *base).returncode)
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        refused = self.run_guard("git push -u origin topic", cwd=repo, guard_args=base)
        self.assertEqual(2, refused.returncode)
        self.assertIn(f"repository {NODO} is outside standing authorization", refused.stderr)
        allowed = self.run_guard("git push -u origin topic", cwd=repo)
        self.assertEqual(0, allowed.returncode, allowed.stderr)

    def test_derived_row_never_authorizes_its_owner_s_other_repositories(self):
        """R2, D3: the row is keyed by the exact repository."""
        sibling = self.make_repo("git@github.com:elevenyellow/other.git")
        for label, command in (
            ("push", "git push -u origin topic"),
            ("PR creation", 'gh pr create --repo elevenyellow/other --base main --head t '
                            '--title "x" --body "y"'),
            ("merge", "gh pr merge 7 --repo elevenyellow/other --merge --delete-branch"),
            ("release creation", 'gh release create v1.2.3 --repo elevenyellow/other '
                                 '--verify-tag --title "v1.2.3" --notes-file notes.md'),
        ):
            with self.subTest(verb=label):
                result = self.run_guard(command, cwd=sibling)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: unsafe {label}: repository elevenyellow/other "
                              "is outside standing authorization", result.stderr)

    def test_derived_repository_is_refused_when_origin_head_differs_from_its_row(self):
        """R6, D8: every repository-bound verb, with a reason naming both branches."""
        for live, named in (("trunk", "trunk"), (None, "no branch")):
            repo = self.make_repo(f"git@github.com:{NODO}.git", default_branch=live)
            for label, command in (
                ("push", "git push -u origin topic"),
                ("PR creation", f'gh pr create --repo {NODO} --base dev --head t '
                                '--title "x" --body "y"'),
                ("merge", f"gh pr merge 7 --repo {NODO} --merge --delete-branch"),
                ("release creation", f'gh release create v1.2.3 --repo {NODO} '
                                     '--verify-tag --title "v1.2.3" --notes-file notes.md'),
            ):
                with self.subTest(origin_head=live, verb=label):
                    result = self.run_guard(command, cwd=repo)
                    self.assertEqual(2, result.returncode, command)
                    self.assertIn(
                        f"lifecycle guard: unsafe {label}: repository {NODO}: origin/HEAD "
                        f"names {named}, its derived policy row names main", result.stderr)
            # Branch deletion is not repository-bound and stays judged on its grammar.
            self.assertEqual(0, self.run_guard("git branch -d topic", cwd=repo).returncode)

    def test_literal_owner_does_not_bypass_the_derived_row_check(self):
        """R6, D8: a derived row is checked even when the owner is a literal authorized owner."""
        slug = "fagenorn/nix-config"
        policy = self.write_policy(derivation={}, derived_repositories={
            slug: {"default_branch": "main", "integration_branch": "main",
                   "required_checks": [], "evidence": {}}})
        self.assertIn("fagenorn", self.base_policy["authorized_owners"])
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
        repo = self.make_repo(f"git@github.com:{slug}.git", default_branch="trunk")
        for label, command in (
            ("push", "git push -u origin topic"),
            ("PR creation", f'gh pr create --repo {slug} --base trunk --head t '
                            '--title "x" --body "y"'),
            ("merge", f"gh pr merge 7 --repo {slug} --merge --delete-branch"),
        ):
            with self.subTest(verb=label):
                result = self.run_guard(command, cwd=repo, guard_args=args)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(
                    f"lifecycle guard: unsafe {label}: repository {slug}: origin/HEAD "
                    "names trunk, its derived policy row names main", result.stderr)

    def test_single_branch_derived_row_keeps_the_default_branch_only_rule(self):
        policy = self.write_policy(derivation={}, derived_repositories={
            "acme/tool": {"default_branch": "main", "integration_branch": "main",
                          "required_checks": [], "evidence": {}}})
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
        env = self.rows_env({"acme/tool": {"default_branch": "main",
                                           "integration_branch": "main",
                                           "required_checks": [], "evidence": {}}})
        repo = self.make_repo("git@github.com:acme/tool.git")
        create = 'gh pr create --repo acme/tool --base {} --head t --title "x" --body "y"'
        self.assertEqual(
            0, self.run_guard(create.format("main"), cwd=repo, guard_args=args,
                              env=env).returncode)
        self.assertEqual(
            2, self.run_guard(create.format("dev"), cwd=repo, guard_args=args,
                              env=env).returncode)
        release_arm = self.run_guard(
            "gh pr merge 1 --repo acme/tool --merge", cwd=repo, guard_args=args,
            env={**env, "FAKE_PR_MODE": "nonzero"})
        self.assertEqual(2, release_arm.returncode)
        self.assertIn("declared integration branch", release_arm.stderr)

    def test_a_compiled_policy_round_trips_through_the_guard(self):
        """D10: the compiler's file is the guard's input, so the schema cannot drift."""
        world = GuardPolicyWorld(self)
        world.project("nodocom", NODO, integration_branch="dev", publication_free=True,
                      override=True)
        code, report, stderr = world.compile(base=BASE_POLICY_PATH)
        self.assertEqual((0, [NODO]), (code, report["derived"]), stderr)
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(world.output),
                "--derive-bin", str(world.row_check()), "--derive-timeout-seconds", "25")
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        allowed = self.run_guard(
            f'gh pr create --repo {NODO} --base dev --head issue-7-topic '
            '--title "x" --body "y"', cwd=repo, guard_args=args, timeout=60)
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        sibling = self.make_repo("git@github.com:elevenyellow/other.git")
        refused = self.run_guard("git push -u origin topic", cwd=sibling, guard_args=args,
                                 timeout=60)
        self.assertEqual(2, refused.returncode)
        self.assertIn("outside standing authorization", refused.stderr)
        forged = json.loads(world.output.read_text(encoding="utf-8"))
        forged["derived_repositories"]["acme/forged"] = {
            "default_branch": "main", "integration_branch": "main", "required_checks": [],
            "evidence": {}}
        forged_args = (*args, "--policy", str(self.write_policy(**forged)))
        forged_repo = self.make_repo("git@github.com:acme/forged.git")
        refused = self.run_guard("git push -u origin topic", cwd=forged_repo,
                                 guard_args=forged_args, timeout=60)
        self.assertEqual(2, refused.returncode)
        self.assertIn("repository acme/forged: the row check did not confirm its derived policy "
                      "row: refused (no registered project derives it); repair: run "
                      "claude-guard-policy", refused.stderr)

    def test_an_arcwave_shaped_project_is_judged_by_its_compiled_row(self):
        """Issue 384 D4: a registered project with integration branch `dev` needs no literal.
        Compiled against the built base policy it is derived, not refused, and the guard
        adjudicates its feature and release arms through the confirmed row."""
        slug = "fagenorn/arcwave"
        world = GuardPolicyWorld(self)
        world.project("arcwave", slug, integration_branch="dev", publication_free=True)
        code, report, stderr = world.compile(base=BASE_POLICY_PATH)
        self.assertEqual((0, [slug], []), (code, report["derived"], report["refused"]), stderr)
        row = world.policy()["derived_repositories"][slug]
        self.assertEqual(("main", "dev"), (row["default_branch"], row["integration_branch"]))
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(world.output),
                "--derive-bin", str(world.row_check()), "--derive-timeout-seconds", "25")
        repo = self.make_repo(f"git@github.com:{slug}.git")
        create = self.run_guard(
            f'gh pr create --repo {slug} --base dev --head issue-7-topic '
            '--title "x" --body "y"', cwd=repo, guard_args=args, timeout=60)
        self.assertEqual(0, create.returncode, create.stderr)
        feature_pr = json.dumps({"state": "OPEN", "baseRefName": "dev",
                                 "headRefName": "issue-7-topic",
                                 "mergeStateStatus": "CLEAN",
                                 "url": f"https://github.com/{slug}/pull/7"})
        feature = self.run_guard(
            f"gh pr merge 7 --repo {slug} --merge --delete-branch", cwd=repo, guard_args=args,
            env={"FAKE_PR_JSON": feature_pr, "FAKE_PROTECTION_MODE": "nonzero"}, timeout=60)
        self.assertEqual(0, feature.returncode, feature.stderr)
        release = f"gh pr merge 1 --repo {slug} --merge"
        url = f"https://github.com/{slug}/pull/1"
        green = self.run_guard(release, cwd=repo, guard_args=args, timeout=60,
                               env=self.release_env(url=url))
        self.assertEqual(0, green.returncode, green.stderr)
        red = self.run_guard(release, cwd=repo, guard_args=args, timeout=60,
                             env=self.release_env(url=url, statusCheckRollup=[
                                 {"__typename": "CheckRun", "status": "COMPLETED",
                                  "conclusion": "FAILURE"}]))
        self.assertEqual(2, red.returncode, red.stderr)
        self.assertIn("check rollup is not entirely green", red.stderr)
        unrelated = self.make_repo("git@github.com:acme/unrelated.git")
        refused = self.run_guard("git push -u origin topic", cwd=unrelated, guard_args=args,
                                 timeout=60)
        self.assertEqual(2, refused.returncode)
        self.assertIn("repository acme/unrelated is outside standing authorization",
                      refused.stderr)

    def test_an_argus_shaped_project_merges_under_the_plan_gated_floor(self):
        """Issue 552 AC1, D8: a registered project whose forge cannot protect its default
        branch, and whose own contract declares its CI check, is judged by the floor through
        its compiled and confirmed row, and no central policy table names it."""
        slug = "fagenorn/argus"
        check = "memory foundation (unit + forced checks)"
        world = GuardPolicyWorld(self)
        world.project("argus", slug, publication_free=True, mutate=lambda contract: (
            contract["bindings"]["vcs"]["merge"].update(required_checks=[check])))
        code, report, stderr = world.compile(base=BASE_POLICY_PATH)
        self.assertEqual((0, [slug], []), (code, report["derived"], report["refused"]), stderr)
        row = world.policy()["derived_repositories"][slug]
        self.assertEqual(("main", "main", [check]), (
            row["default_branch"], row["integration_branch"], row["required_checks"]))
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(world.output),
                "--derive-bin", str(world.row_check()), "--derive-timeout-seconds", "25")
        repo = self.make_repo(f"git@github.com:{slug}.git")
        merge = (f"unset GITHUB_TOKEN && gh pr merge 9 --repo {slug} --merge --subject "
                 f'"feat: memory foundation (#9)" --match-head-commit {self.HEAD_SHA} '
                 "--delete-branch")

        def merged(rollup, mode="http_error"):
            facts = {"state": "OPEN", "baseRefName": "main", "headRefName": "issue-9-topic",
                     "headRefOid": self.HEAD_SHA, "mergeStateStatus": "CLEAN",
                     "url": f"https://github.com/{slug}/pull/9", "statusCheckRollup": rollup}
            return self.run_guard(merge, cwd=repo, guard_args=args, timeout=60, env={
                "FAKE_PR_JSON": json.dumps(facts), "FAKE_PROTECTION_MODE": mode})

        allowed = merged([self.check_run(check)])
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        floor = f"{self.UNPROTECTED}, and the declared required check {check} "
        self.assertEqual(floor + "is missing from the PR's check rollup",
                         self.refusal_line(merged([self.check_run("CI / lint")])))
        self.assertEqual(floor + "is not green (CheckRun COMPLETED/FAILURE)",
                         self.refusal_line(merged([self.check_run(check,
                                                                  conclusion="FAILURE")])))
        self.assertTrue(self.refusal_line(merged([self.check_run(check)], mode="nonzero"))
                        .startswith(self.LOOKUP_FAILED + "fake protection failure"))
        root = Path(__file__).resolve().parents[1]
        central = (BASE_POLICY_PATH, root / "home/common/claude-code/default.nix",
                   root / "home/common/claude-code/lifecycle_guard.py")
        self.assertEqual([], [str(path) for path in central
                              if "argus" in path.read_text(encoding="utf-8").lower()])

    def test_a_compiled_policy_loads_whatever_branch_names_the_fleet_carries(self):
        """The compiler and the loader agree on names: one the loader refuses costs its
        project a row, and every row the compiler does write loads."""
        world = GuardPolicyWorld(self)
        world.project("nodocom", NODO, integration_branch="dev", publication_free=True,
                      override=True)
        world.project("fixture/wide", "acme/wide_1.x", integration_branch="release/1.x_y-z")
        world.project("fixture/plus", "acme/plus", integration_branch="dev+ci")
        code, report, stderr = world.compile(base=BASE_POLICY_PATH)
        self.assertEqual((1, ["acme/wide_1.x", NODO]), (code, report["derived"]), stderr)
        self.assertEqual([("fixture/plus", "name_unsupported")],
                         [(r["project_id"], r["reason_code"]) for r in report["refused"]])
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(world.output),
                "--derive-bin", str(world.row_check()), "--derive-timeout-seconds", "25")
        loaded = self.invoke_command("true", "--policy", str(world.output))
        self.assertEqual(0, loaded.returncode, loaded.stderr)
        wide = self.make_repo("git@github.com:acme/wide_1.x.git")
        allowed = self.run_guard(
            'gh pr create --repo acme/wide_1.x --base release/1.x_y-z --head issue-7-topic '
            '--title "x" --body "y"', cwd=wide, guard_args=args, timeout=60)
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        plus = self.make_repo("git@github.com:acme/plus.git")
        refused = self.run_guard("git push -u origin topic", cwd=plus, guard_args=args,
                                 timeout=60)
        self.assertEqual(2, refused.returncode)
        self.assertIn("repository acme/plus is outside standing authorization", refused.stderr)

    FOUR_VERBS = (
        ("push", "git push -u origin topic"),
        ("PR creation", 'gh pr create --repo {slug} --base {base} --head t '
                        '--title "x" --body "y"'),
        ("merge", "gh pr merge 7 --repo {slug} --merge --delete-branch"),
        ("release creation", 'gh release create v1.2.3 --repo {slug} --verify-tag '
                             '--title "v1.2.3" --notes-file notes.md'),
    )

    def assert_unconfirmed(self, slug, why, base="main", exact=True, **run):
        """Every repository-bound verb on `slug` is refused for `why`; `exact=False` checks
        only the text up to `why`, for a reason that ends in an OS message."""
        repo = self.make_repo(f"git@github.com:{slug}.git")
        for label, template in self.FOUR_VERBS:
            with self.subTest(slug=slug, verb=label):
                result = self.run_guard(template.format(slug=slug, base=base), cwd=repo, **run)
                self.assertEqual(2, result.returncode, result.stderr)
                expected = (f"lifecycle guard: unsafe {label}: repository {slug}: the row check "
                            f"did not confirm its derived policy row: {why}")
                if exact:
                    expected += "; repair: run claude-guard-policy"
                self.assertIn(expected, result.stderr)
                self.assertNotIn("transient", result.stderr)

    def test_a_row_for_an_unregistered_repository_is_refused_at_use(self):
        """Issue 377 criterion 3, R2, R3."""
        slug = "acme/forged"
        policy = self.write_policy(derivation={}, derived_repositories={
            NODO: NODO_ROW,
            slug: {"default_branch": "main", "integration_branch": "main",
                   "required_checks": [], "evidence": {}}})
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(policy))
        self.assert_unconfirmed(slug, "refused (no registered project derives it)",
                                guard_args=args)

    def refused_report(self, *refusals):
        """The environment of a row check that answers `refused` with `refusals`,
        each a `(reason_code, detail)` pair; `ABSENT` leaves the detail out."""
        items = [{"project_id": "p", "root": "/p", "reason_code": code,
                  **({} if detail is ABSENT else {"detail": detail})}
                 for code, detail in refusals]
        return {"FAKE_DERIVE_MODE": "refused_code", "FAKE_DERIVE_REFUSED": json.dumps(items)}

    def test_a_failed_remote_or_provider_read_says_what_failed_and_is_transient(self):
        """Issue 844 AC2: `provider_unproven` and `fetch_failed` carry the failed read's
        detail, on one line and bounded, and the rerun remedy instead of the policy
        repair. The verb is refused all the same."""
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        head = ("lifecycle guard: unsafe push: repository elevenyellow/nodocom: the row check "
                "did not confirm its derived policy row: refused (")
        unreachable = ("gh api repos/elevenyellow/nodocom failed: exit 1: "
                       "connect: network is unreachable")
        for refusals, shown in (
                ([("provider_unproven", unreachable)], f"provider_unproven: {unreachable}"),
                ([("fetch_failed", "x")], "fetch_failed: x"),
                ([("fetch_failed", "one"), ("provider_unproven", "two")],
                 "fetch_failed: one, provider_unproven: two"),
                ([("provider_unproven", "a\nlifecycle guard: allowed\x1b[2K\r\u2028b")],
                 "provider_unproven: a\\nlifecycle guard: allowed\\x1b[2K\\r\\u2028b"),
                ([("provider_unproven", "a" * 5000)], "provider_unproven: " + "a" * 240),
                ([("provider_unproven", "\n" * 5000)], "provider_unproven: " + "\\n" * 120),
                ([("provider_unproven", "")], "provider_unproven"),
                ([("provider_unproven", ABSENT)], "provider_unproven"),
                ([("provider_unproven", 7)], "provider_unproven"),
                ([("fetch_failed", ["x"])], "fetch_failed")):
            with self.subTest(refusals=refusals):
                result = self.run_guard("git push -u origin topic", cwd=repo,
                                        env=self.refused_report(*refusals))
                self.assertEqual(
                    head + shown + "); transient: rerun the command", self.refusal_line(result))
                self.assertNotIn("claude-guard-policy", result.stderr)

    def test_a_refusal_with_any_other_reason_code_keeps_the_policy_repair(self):
        """Issue 844: every other reason code prints what it printed, detail left out,
        also beside a transient one."""
        for refusals, shown in (
                ([("branch_mismatch", "secret detail")], "branch_mismatch"),
                ([("provider_unproven", "secret detail"), ("identity_mismatch", "more")],
                 "provider_unproven, identity_mismatch")):
            with self.subTest(refusals=refusals):
                self.assert_unconfirmed(NODO, f"refused ({shown})",
                                        env=self.refused_report(*refusals))

    def test_a_row_whose_branches_differ_from_the_derivation_is_refused(self):
        """Issue 377 R3, D2: a forged integration branch never widens a target."""
        forged = self.write_policy(derivation={}, derived_repositories={
            NODO: {**NODO_ROW, "integration_branch": "evil"}})
        self.assert_unconfirmed(
            NODO, "it derives main and dev, the row names main and evil", base="evil",
            guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(forged)))
        literal = "fagenorn/tool"
        widened = self.write_policy(derivation={}, derived_repositories={
            literal: {"default_branch": "main", "integration_branch": "dev",
                      "required_checks": [], "evidence": {}}})
        self.assert_unconfirmed(
            literal, "it derives main and main, the row names main and dev", base="dev",
            guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(widened)),
            env=self.rows_env({literal: {"default_branch": "main", "integration_branch": "main",
                                         "required_checks": [], "evidence": {}}}))

    def test_a_row_whose_required_checks_differ_from_the_derivation_is_refused(self):
        """Issue 552 D5: the row check confirms the declared checks as lists, order
        included, and a derived report whose checks are not a list of strings is
        unreadable."""
        slug = "acme/checks"
        derived = {"default_branch": "main", "integration_branch": "main",
                   "required_checks": ["CI", "lint"], "evidence": {}}
        env = self.rows_env({slug: derived})
        confirmed = self.write_policy(derivation={}, derived_repositories={slug: derived})
        args = ("--gh-bin", str(self.fake_gh), "--policy", str(confirmed))
        allowed = self.run_guard("git push -u origin topic", guard_args=args, env=env,
                                 cwd=self.make_repo(f"git@github.com:{slug}.git"))
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        for compiled, named in ((["lint"], '["lint"]'), (["lint", "CI"], '["lint","CI"]'),
                                ([], "[]")):
            policy = self.write_policy(derivation={}, derived_repositories={
                slug: {**derived, "required_checks": compiled}})
            self.assert_unconfirmed(
                slug, f'it derives required checks ["CI","lint"], the row names {named}',
                env=env, guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(policy)))
        for reported in (ABSENT, None, "CI", ["CI", 7]):
            row = {key: value for key, value in {**derived, "required_checks": reported}.items()
                   if value is not ABSENT}
            self.assert_unconfirmed(slug, "unreadable report (exit 0)", guard_args=args,
                                    env=self.rows_env({slug: row}))

    def test_a_failing_row_check_refuses_with_no_fallback(self):
        """Issue 377 R2, D3."""
        for mode, why in (("unavailable", "unavailable (registry_invalid)"),
                          ("garbage", "unreadable report (exit 0)"),
                          ("badbytes", "unreadable report (exit 0)")):
            self.assert_unconfirmed(NODO, why, env={"FAKE_DERIVE_MODE": mode})
        absent = Path(self.fixture_dir.name) / "absent-row-check"
        self.assert_unconfirmed(NODO, "could not start (", exact=False, guard_args=(
            "--gh-bin", str(self.fake_gh), "--derive-bin", str(absent)))

    def test_a_row_check_past_its_bound_is_killed_with_its_process_group(self):
        """Issue 377 D6: a grandchild of the row check never outlives the verdict."""
        pidfile = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "pid"
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        result = self.run_guard(
            "git push -u origin topic", cwd=repo,
            guard_args=("--gh-bin", str(self.fake_gh), "--derive-timeout-seconds", "2"),
            env={"FAKE_DERIVE_MODE": "hang", "FAKE_DERIVE_PIDFILE": str(pidfile)})
        self.assertEqual(2, result.returncode, result.stderr)
        line = self.refusal_line(result)
        self.assertTrue(line.endswith("the row check did not confirm its derived policy row: "
                                      "timed out; transient: rerun the command"), line)
        self.assertNotIn("claude-guard-policy", line)
        self.assert_row_check_killed(pidfile)

    def test_the_invocation_deadline_bounds_the_row_check_and_every_later_child(self):
        """Issue 377 R6, D10, D12 (slow by design; the two cases share one 27 s wait).

        `hung`: a row check that outlives a 60-second bound is killed inside 27 s.
        `exhausted`: a row check that confirms Nodo's row 25 s in leaves less than one
        5-second child bound, so the push is refused before its next child."""
        pidfile = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "pid"
        repo = self.make_repo(f"git@github.com:{NODO}.git")
        args = ("--gh-bin", str(self.fake_gh), "--derive-timeout-seconds", "60")
        started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            hung = pool.submit(
                self.run_guard, "git push -u origin topic", cwd=repo, timeout=40,
                guard_args=args,
                env={"FAKE_DERIVE_MODE": "hang", "FAKE_DERIVE_PIDFILE": str(pidfile)})
            exhausted = pool.submit(
                self.run_guard, "git push -u origin topic-a",
                cwd=repo, timeout=40, guard_args=args,
                env={"FAKE_DERIVE_MODE": "slow", "FAKE_DERIVE_UNTIL": str(time.time() + 25)})
            hung, exhausted = hung.result(), exhausted.result()
        elapsed = time.monotonic() - started
        self.assertEqual(2, hung.returncode, hung.stderr)
        self.assertTrue(self.refusal_line(hung).endswith(
            "the row check did not confirm its derived policy row: timed out; "
            "transient: rerun the command"), hung.stderr)
        self.assertEqual(2, exhausted.returncode, exhausted.stderr)
        self.assertIn("lifecycle guard: unsafe push: the 27-second invocation deadline leaves "
                      "too little time for the next check, so it was not started",
                      exhausted.stderr)
        self.assertEqual(1, exhausted.stderr.count("lifecycle guard:"), exhausted.stderr)
        self.assertNotIn("transient", exhausted.stderr)
        self.assertGreater(elapsed, 20)
        self.assertLess(elapsed, 29)
        self.assert_row_check_killed(pidfile)

    def test_the_row_check_runs_once_and_only_for_a_repository_with_a_row(self):
        """Issue 377 section 3: no row, no check and no network read."""
        log = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "derive.log"
        env = {"FAKE_DERIVE_LOG": str(log)}
        literal = self.make_repo("git@github.com:fagenorn/tool.git")
        self.assertEqual(0, self.run_guard("git push -u origin topic", cwd=literal,
                                           env=env).returncode)
        self.assertFalse(log.exists())
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        result = self.run_guard("git push -u origin topic-a", cwd=nodo, env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"{NODO}\n", log.read_text(encoding="utf-8"))

    def test_hostile_interpreter_environment_is_ignored(self):
        # Each plant exits 0 before the guard can judge: a BASH_ENV file that the
        # wrapper's bash would source, a `json` package reached through PYTHONPATH,
        # and a .pth line reached through NIX_PYTHONPATH, which nixpkgs'
        # sitecustomize honours even under -I. Seeing any one would turn a refusal
        # into an allow, so the registered hook must ignore all three.
        hostile = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
        (hostile / "bash_env").write_text("exit 0\n", encoding="utf-8")
        (hostile / "json").mkdir()
        (hostile / "json" / "__init__.py").write_text(
            "import os\nos._exit(0)\n", encoding="utf-8"
        )
        (hostile / "hostile.pth").write_text("import os; os._exit(0)\n", encoding="utf-8")
        result = self.invoke_command(
            "git branch -d -f topic",
            env={
                "BASH_ENV": str(hostile / "bash_env"),
                "PYTHONPATH": str(hostile),
                "NIX_PYTHONPATH": str(hostile),
            },
        )
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("lifecycle guard: unsafe branch deletion:", result.stderr)

    def test_the_row_check_never_sees_a_hostile_shell_environment(self):
        """Issue 377: a BASH_ENV file or an exported bash function that prints a forged
        `derived` report must not confirm a forged row. `built` is the store row check run
        over an empty fixture fleet; `plain bash` is a bash row check that would honour
        both, so it shows that the guard drops them from the row check's environment."""
        world = GuardPolicyWorld(self)
        wrapper = self.guard.read_text(encoding="utf-8")
        built = Path(wrapper.split("--derive-bin ", 1)[1].split(" ", 1)[0])
        bash = built.read_text(encoding="utf-8").splitlines()[0][2:].split()[0]
        plain = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "plain-bash-row-check"
        plain.write_text(f'#!{bash}\nexec {self.fake_derive} "$@"\n', encoding="utf-8")
        plain.chmod(0o755)
        slug = "acme/forged"
        row = {"default_branch": "main", "integration_branch": "main", "required_checks": [],
               "evidence": {}}
        report = json.dumps({"schema_version": 1, "repository": slug, "outcome": "derived",
                             "row": row, "refused": [], "cause": None})
        forge = f"printf '%s\\n' {shlex.quote(report)}; builtin exit 0"
        bash_env = Path(tempfile.mkdtemp(dir=self.fixture_dir.name)) / "bash_env"
        bash_env.write_text(forge + "\n", encoding="utf-8")
        policy = self.write_policy(derived_repositories={slug: row}, derivation={})
        repo = self.make_repo(f"git@github.com:{slug}.git")
        fleet = {name: world.env[name] for name in ("HOME", "GIT_CONFIG_GLOBAL",
                                                     "GIT_CONFIG_SYSTEM")}
        for name, derive_bin, env in (("built", built, fleet), ("plain bash", plain, {})):
            for plant in ({"BASH_ENV": str(bash_env)},
                          {"BASH_FUNC_exec%%": f"() {{ {forge}; }}"},
                          {"BASH_FUNC_unset%%": f"() {{ {forge}; }}"}):
                with self.subTest(row_check=name, plant=sorted(plant)[0]):
                    result = self.run_guard(
                        "git push -u origin topic", cwd=repo, env={**env, **plant}, timeout=60,
                        guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(policy),
                                    "--derive-bin", str(derive_bin),
                                    "--derive-timeout-seconds", "25"))
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn(f"lifecycle guard: unsafe push: repository {slug}: the row "
                                  "check did not confirm its derived policy row: ",
                                  result.stderr)


    def test_push_hooks_cannot_be_skipped_or_redirected_in_plain_form(self):
        """Issue 672 D8: the pre-push hook is authoritative, so the text guard refuses
        skipping it (--no-verify) and repointing core.hooksPath in plain form."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "git push --no-verify origin issue-672-topic",
            "git push origin issue-672-topic --no-verify",
            "git push -n origin issue-672-topic",
            "git -C /tmp/x push --no-verify origin issue-672-topic",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn("lifecycle guard: unsafe push: ", result.stderr)
        for command in (
            "git config core.hooksPath /dev/null",
            "git config --global core.hooksPath /tmp/h",
            "git config --local --unset core.hooksPath",
            "git -C /tmp/x config CORE.HOOKSPATH /tmp/h",
            "git config set core.hooksPath /tmp/h",
            "git config --get core.hooksPath",
            "true && git config core.hooksPath=/tmp/h",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn("would change which hook judges a push", result.stderr)
        for command in ("git config user.name x", "git config --get core.hooksPathX",
                        "git config alias.lg log"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

    def test_the_agent_session_marker_cannot_be_cleared_in_plain_form(self):
        """Issue 672 D3: the pre-push hook judges a push only in an agent session
        (CLAUDECODE), so the text guard refuses every plain way to clear it."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "unset CLAUDECODE; G=g; H=it; $G$H push origin main",
            "unset CLAUDECODE", "unset -v CLAUDECODE", "export CLAUDECODE=",
            "CLAUDECODE= make", "CLAUDECODE=0 make", "export -n CLAUDECODE",
            "declare +x CLAUDECODE", "typeset +x CLAUDECODE",
            "env -u CLAUDECODE make", "env -uCLAUDECODE make",
            "env --unset=CLAUDECODE make", "env -i make", "env - make",
            "env -vuCLAUDECODE ./push.sh", "env -0uCLAUDECODE ./push.sh",
            "env --unse=CLAUDECODE ./push.sh", "env -v -u CLAUDECODE make",
            "env -vu CLAUDECODE make", "env --unset CLAUDECODE make",
            "env --uns CLAUDECODE make",
            "env --ignore-environment make", "env -iv make", "exec -c make",
            "true && unset CLAUDECODE",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)
                self.assertIn("would hide the agent session from the pre-push hook",
                              result.stderr)
        for command in (
            "sh -c 'unset CLAUDECODE; make'", "sh -c 'env -i ./push.sh'",
            "bash -c 'exec -c ./push.sh'", "sh -c 'env - make release'",
            "sh -c 'env --ignore-environment make'",
            "sh -c 'env -vuCLAUDECODE ./push.sh'",
            "sh -c 'env --unse=CLAUDECODE ./push.sh'",
            "sh -c 'true; env -0u CLAUDECODE ./push.sh'",
        ):
            with self.subTest(command=command):
                refused = self.run_guard(command, cwd=repo)
                self.assertEqual(2, refused.returncode, (command, refused.stderr))
        for command in ("echo $CLAUDECODE", "env FOO=1 make", "env -u FOO make",
                        "printenv HOME", "make CLAUDE=1", "env -vu FOO make",
                        "env --unse=FOO make",
                        "sh -c 'env -u FOO make'", "sh -c 'env FOO=1 make'"):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))


    # ------------------------------------------------------------------
    # Look gate (issue 1138): a merge of a pull request whose issues carry a
    # look marker waits for the owner's approval of its head.
    # ------------------------------------------------------------------

    LOOK_HEAD = "1a2b3c4" + "d" * 33
    LOOK_BODY = (
        "## Acceptance criteria\n\n"
        "- [ ] [human] before merge: the settings page at 390 px "
        "\u2014 measured: the owner, on the console\n"
    )
    LOOK_MARKED = {"1200": {"body": LOOK_BODY}}
    LOOK_MERGE = "gh pr merge 1300 --repo fagenorn/nix-config --merge --delete-branch"
    LOOK_SUBJECT_MERGE = (
        'gh pr merge 1300 --repo fagenorn/nix-config --merge --subject "Fix #1200 layout" '
        "--delete-branch")
    LOOK_PINNED = (
        "gh pr merge 1300 --repo fagenorn/nix-config --merge "
        f"--match-head-commit {LOOK_HEAD} --delete-branch")
    LOOK_UNPINNED_REFUSAL = (
        "lifecycle guard: unsafe merge: issue 1200 awaits the owner's look, so the merge must "
        f"carry --match-head-commit {LOOK_HEAD}, the head the owner approved")
    LOOK_REFUSAL = (
        "lifecycle guard: unsafe merge: issue 1200 needs the owner's look before merge, "
        "and head 1a2b3c4 has no recorded approval; ask the owner and record the answer"
    )

    def look_comment(self, cid, issue=1200, pr=1300, head=LOOK_HEAD, answer="approved",
                     association="OWNER"):
        return {
            "id": cid,
            "body": look_marker.approval_body(issue, pr, head, answer, f"m{cid}"),
            "updated_at": "2026-11-16T10:00:00Z",
            "author_association": association,
        }

    def look_end_comment(self, cid, of, association="OWNER"):
        return {
            "id": cid,
            "body": forge_markers.end_body(of, "withdrawn"),
            "updated_at": "2026-11-16T10:00:00Z",
            "author_association": association,
        }

    @staticmethod
    def look_pr_json(body="", linked=(), title="Page"):
        """The PR lookup's answer: title, body and linked issue numbers."""
        return json.dumps({
            "title": title,
            "body": body,
            "closingIssuesReferences": [
                {"url": n if isinstance(n, str)
                 else f"https://github.com/fagenorn/nix-config/issues/{n}"}
                for n in linked],
        })

    @staticmethod
    def look_commit_pages(commits):
        """The commit listing's answer: the messages in pages of 100, one entry each."""
        entries = [{"sha": f"{i:040x}", "commit": {"message": line}}
                   for i, line in enumerate(commits)]
        return json.dumps([entries[start:start + 100] for start in range(0, len(entries), 100)]
                          or [[]])

    def look_env(self, issues, body="", branch="issue-1200-page", head=LOOK_HEAD,
                 base="main", slug="fagenorn/nix-config", number=1300, commits=(), linked=(),
                 title="Page"):
        pr = {
            "state": "OPEN",
            "baseRefName": base,
            "headRefName": branch,
            "mergeStateStatus": "CLEAN",
            "url": f"https://github.com/{slug}/pull/{number}",
            "statusCheckRollup": [
                {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}],
        }
        if head is not None:
            pr["headRefOid"] = head
        return {
            "FAKE_PR_JSON": json.dumps(pr),
            "FAKE_BODY_JSON": self.look_pr_json(body, linked, title),
            "FAKE_COMMITS_JSON": self.look_commit_pages(commits),
            "FAKE_ISSUES": json.dumps(issues),
        }

    def look_repo(self):
        return self.make_repo("git@github.com:fagenorn/nix-config.git")

    def marked_with(self, *comments, **env):
        return self.look_env({"1200": {"body": self.LOOK_BODY, "comments": list(comments)}}, **env)

    def assert_look_refusal(self, result, refusal=None):
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn(refusal or self.LOOK_REFUSAL, result.stderr.splitlines())

    def test_a_large_pull_request_reads_every_commit_page(self):
        env = self.look_env(
            self.LOOK_MARKED, branch="topic", body="Page change",
            commits=["Routine change"] * 149 + ["Fix #1200 layout"] + ["Routine change"] * 44)
        result = self.run_guard(self.LOOK_MERGE, self.look_repo(), env)
        self.assert_look_refusal(result)

    def test_a_pull_request_of_many_commits_settling_no_marked_issue_merges(self):
        for count in (100, 194, 249):
            with self.subTest(commits=count):
                env = self.look_env(
                    self.LOOK_MARKED, branch="topic", body="Page change",
                    commits=["Routine change"] * count)
                result = self.run_guard(self.LOOK_MERGE, self.look_repo(), env)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_a_194_commit_pull_request_of_a_marked_issue_is_judged_like_a_small_one(self):
        repo = self.look_repo()
        for count in (1, 194):
            with self.subTest(commits=count):
                bare = self.look_env(self.LOOK_MARKED, commits=["Routine change"] * count)
                approved = self.marked_with(
                    self.look_comment(10), commits=["Routine change"] * count)
                first = self.run_guard(self.LOOK_MERGE, repo, bare)
                second = self.run_guard(self.LOOK_PINNED, repo, approved)
                self.assert_look_refusal(first)
                self.assertEqual(0, second.returncode, second.stderr)
                self.assertEqual("", second.stderr)

    def test_a_pull_request_past_the_commit_limit_is_refused_naming_its_count(self):
        env = self.look_env(
            self.LOOK_MARKED, branch="topic", body="Page change",
            commits=["Routine change"] * 250)
        result = self.run_guard(self.LOOK_MERGE, self.look_repo(), env)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn(
            "lifecycle guard: unsafe merge: cannot read every commit of the PR: GitHub listed "
            "250 commits, its limit, so a later commit may settle an issue unseen",
            result.stderr.splitlines())
        self.assertNotIn("PR body", result.stderr)

    def test_a_marked_issue_without_an_approval_refuses_the_merge(self):
        result = self.run_guard(self.LOOK_MERGE, self.look_repo(), self.look_env(self.LOOK_MARKED))
        self.assert_look_refusal(result)

    def test_the_look_gate_refuses_each_unapproved_shape(self):
        repo = self.look_repo()
        other = {"7": {"body": ""}, "1200": {"body": self.LOOK_BODY}}
        by_reference = lambda text: self.look_env(  # noqa: E731
            other, body=text, branch="issue-7-page")
        nodo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        cases = {
            "an older head": (repo, self.LOOK_MERGE,
                              self.marked_with(self.look_comment(10, head="e" * 40))),
            "a collaborator": (repo, self.LOOK_MERGE, self.marked_with(
                self.look_comment(10, association="COLLABORATOR"))),
            "a contributor": (repo, self.LOOK_MERGE, self.marked_with(
                self.look_comment(10, association="CONTRIBUTOR"))),
            "only changes": (repo, self.LOOK_MERGE, self.marked_with(
                self.look_comment(10, answer="changes"))),
            "changes after approved": (repo, self.LOOK_MERGE, self.marked_with(
                self.look_comment(10), self.look_comment(11, answer="changes"))),
            "an approval on another issue": (repo, self.LOOK_MERGE, self.look_env(
                {"7": {"body": "", "comments": [self.look_comment(10, issue=7)]},
                 "1200": {"body": self.LOOK_BODY}},
                body="Refs #1200", branch="issue-7-page")),
            "an approval naming another PR": (repo, self.LOOK_MERGE, self.marked_with(
                self.look_comment(10, pr=999))),
            "a Refs-only reference": (repo, self.LOOK_MERGE, by_reference("Refs #1200")),
            "Closes with a colon": (repo, self.LOOK_MERGE, by_reference("Closes: #1200")),
            "upper-case Fixes": (repo, self.LOOK_MERGE, by_reference("FIXES #1200")),
            "a slug-qualified reference": (
                repo, self.LOOK_MERGE, by_reference("resolves fagenorn/nix-config#1200")),
            "a closing keyword in a commit message": (repo, self.LOOK_MERGE, self.look_env(
                self.LOOK_MARKED, branch="topic", body="Page change",
                commits=("Fix #1200 layout",))),
            "a closing keyword in the PR title": (repo, self.LOOK_MERGE, self.look_env(
                self.LOOK_MARKED, branch="topic", body="Page change",
                title="Fix #1200 layout")),
            "a closing keyword in --subject": (repo, self.LOOK_SUBJECT_MERGE, self.look_env(
                self.LOOK_MARKED, branch="topic", body="Page change")),
            "a closing keyword in the head branch name": (repo, self.LOOK_MERGE, self.look_env(
                self.LOOK_MARKED, branch="fix#1200-page", body="Page change")),
            "a Development link": (repo, self.LOOK_MERGE, self.look_env(
                self.LOOK_MARKED, branch="1200-page", body="Page change", linked=(1200,))),
            "an ended approval": (repo, self.LOOK_MERGE, self.marked_with(
                self.look_comment(10), self.look_end_comment(11, 10))),
            "an integration base": (
                nodo, "gh pr merge 1300 --repo elevenyellow/nodocom --merge --delete-branch",
                {**self.marked_with(base="dev", slug="elevenyellow/nodocom"),
                 "FAKE_PROTECTION_MODE": "nonzero"}),
        }
        for name, (cwd, command, env) in cases.items():
            with self.subTest(case=name):
                self.assert_look_refusal(self.run_guard(command, cwd, env))

    def test_an_admin_merge_of_a_marked_issue_is_refused(self):
        result = self.run_guard(
            "gh pr merge 1300 --repo fagenorn/nix-config --admin --merge --delete-branch",
            self.look_repo(), self.look_env(self.LOOK_MARKED))
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertTrue(result.stderr.startswith("lifecycle guard: unsafe merge:"), result.stderr)

    def test_a_failed_look_lookup_refuses(self):
        repo = self.look_repo()
        broken = Path(self.fixture_dir.name) / "broken-look-bin"
        broken.write_text("#!/bin/sh\necho '{'\n", encoding="utf-8")
        broken.chmod(0o755)
        marked = self.look_env(self.LOOK_MARKED)
        unreadable_commits = "lifecycle guard: unsafe merge: cannot read the PR commits"
        cases = (
            ({"FAKE_ISSUE_MODE": "nonzero"}, None,
             "lifecycle guard: issue 1200 lookup failed:"),
            ({"FAKE_COMMENTS_MODE": "nonzero"}, None,
             "lifecycle guard: issue 1200 comment lookup failed:"),
            ({"FAKE_BODY_MODE": "nonzero"}, None, "lifecycle guard: PR body lookup failed:"),
            ({"FAKE_ISSUE_MODE": "invalid"}, None,
             "lifecycle guard: unsafe merge: cannot read issue 1200"),
            ({"FAKE_COMMENTS_MODE": "invalid"}, None,
             "lifecycle guard: unsafe merge: cannot read the comments of issue 1200"),
            ({"FAKE_ISSUE_JSON": '{"number": 1200}'}, None,
             "lifecycle guard: unsafe merge: cannot read issue 1200"),
            ({"FAKE_BODY_JSON": "{}"}, None,
             "lifecycle guard: unsafe merge: cannot read the PR body"),
            ({"FAKE_BODY_JSON": '{"title": "", "body": "", "commits": []}'}, None,
             "lifecycle guard: unsafe merge: cannot read the PR body"),
            ({"FAKE_BODY_JSON":
              '{"title": "", "body": "", "commits": [], "closingIssuesReferences": [{}]}'},
             None, "lifecycle guard: unsafe merge: cannot read the PR body"),
            ({"FAKE_BODY_JSON": '{"body": "", "commits": [], "closingIssuesReferences": []}'},
             None, "lifecycle guard: unsafe merge: cannot read the PR body"),
            ({"FAKE_BODY_JSON":
              '{"title": null, "body": "", "commits": [], "closingIssuesReferences": []}'},
             None, "lifecycle guard: unsafe merge: cannot read the PR body"),
            ({"FAKE_COMMITS_MODE": "nonzero"}, None, "lifecycle guard: PR commit lookup failed:"),
            ({"FAKE_COMMITS_MODE": "timeout"},
             ("--gh-bin", str(self.fake_gh), "--child-timeout-seconds", "0.5"),
             "lifecycle guard: PR commit lookup timed out"),
            ({"FAKE_COMMITS_MODE": "invalid"}, None, unreadable_commits),
            ({"FAKE_COMMITS_JSON": "[{}]"}, None, unreadable_commits),
            ({"FAKE_COMMITS_JSON": "[[1]]"}, None, unreadable_commits),
            ({"FAKE_COMMITS_JSON": '[[{"sha": "x"}]]'}, None, unreadable_commits),
            ({"FAKE_COMMITS_JSON": '[[{"commit": {"message": null}}]]'}, None,
             unreadable_commits),
            ({}, ("--gh-bin", str(self.fake_gh), "--look-bin", str(broken)),
             "lifecycle guard: look check failed:"),
        )
        for extra, guard_args, prefix in cases:
            with self.subTest(prefix=prefix):
                result = self.run_guard(self.LOOK_MERGE, repo, {**marked, **extra},
                                        guard_args=guard_args)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertTrue(result.stderr.startswith(prefix), result.stderr)

    def test_a_trusted_approval_of_the_current_head_admits(self):
        repo = self.look_repo()
        for association in ("OWNER", "MEMBER"):
            with self.subTest(association=association):
                result = self.run_guard(self.LOOK_PINNED, repo, self.marked_with(
                    self.look_comment(10, association=association)))
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("", result.stderr)

    def test_unmarked_issues_merge_as_before(self):
        repo = self.look_repo()
        plain = "- [ ] [human] the owner likes the colours \u2014 measured: the owner"
        cases = {
            "an unmarked human criterion": self.look_env(
                {"7": {"body": ""}, "8": {"body": plain}},
                body="Closes #8", branch="issue-7-page"),
            "another repository's issue": self.look_env(
                self.LOOK_MARKED, body="Closes other/repo#1200", branch="topic"),
            "no issue at all": self.look_env(self.LOOK_MARKED, branch="topic"),
            "another repository's commit reference": self.look_env(
                self.LOOK_MARKED, branch="topic", commits=("Fix other/repo#1200",)),
            "another repository's link": self.look_env(
                self.LOOK_MARKED, branch="topic",
                linked=("https://github.com/other/repo/issues/1200",)),
        }
        for name, env in cases.items():
            with self.subTest(case=name):
                result = self.run_guard(self.LOOK_MERGE, repo, env)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_the_look_demo_refuses_admits_and_refuses_again(self):
        repo = self.look_repo()
        refused = self.run_guard(self.LOOK_MERGE, repo, self.look_env(self.LOOK_MARKED))
        self.assert_look_refusal(refused)
        approved = self.run_guard(self.LOOK_PINNED, repo, self.marked_with(self.look_comment(10)))
        self.assertEqual(0, approved.returncode, approved.stderr)
        moved = self.run_guard(
            self.LOOK_PINNED.replace(self.LOOK_HEAD, "f" * 40), repo,
            self.marked_with(self.look_comment(10), head="f" * 40))
        self.assert_look_refusal(moved, self.LOOK_REFUSAL.replace("1a2b3c4", "fffffff"))

    # ------------------------------------------------------------------
    # A kept look approval (issue 1211): an approval of an earlier head holds for
    # the current head while no commit after it changed the look files.
    # ------------------------------------------------------------------

    LOOK_BASE = "b" * 40
    LOOK_APPROVED = "5" * 40
    LOOK_T = "6" * 40
    LOOK_X = "8" * 40
    LOOK_F = "9" * 40
    LOOK_F1 = "4" * 40
    LOOK_FORK = "3" * 40
    PAGE = "python/agent_tools/console/page.html"
    INBOX = "python/agent_tools/console/inbox.py"
    TESTF = "tests/test_console_page.py"
    DOC = "docs/x.md"
    CONSOLE_SET = '{"version": 1, "sets": {"console": ["python/agent_tools/console/**"]}}'

    @staticmethod
    def look_edit(name, tag="e"):
        return {"filename": name, "status": "modified",
                "patch": f"@@ -1,2 +1,2 @@\n {name} line 0\n-{name} old\n+{name} {tag}"}

    def look_compare(self, files=(), status="ahead", commits=()):
        listed = []
        for entry in files:
            if isinstance(entry, dict):
                listed.append(entry)
            elif isinstance(entry, tuple):
                listed.append(self.look_edit(*entry))
            else:
                listed.append(self.look_edit(entry))
        return {"status": status, "files": listed, "total_commits": len(commits),
                "commits": [{"sha": sha, "parents": [{"sha": q} for q in parents]}
                            for sha, parents in commits]}

    def look_world(self, after, ah_files, extra=()):
        base, approved, head = self.LOOK_BASE, self.LOOK_APPROVED, self.LOOK_HEAD
        compares = {
            f"{base}...{approved}": self.look_compare(
                [self.PAGE], commits=[(approved, [self.LOOK_FORK])]),
            f"{approved}...{head}": self.look_compare(ah_files),
            f"{base}...{head}": self.look_compare(
                commits=[(approved, [self.LOOK_FORK])] + list(after)),
        }
        for a, b, files in extra:
            compares[f"{a}...{b}"] = self.look_compare(files)
        return compares

    def look_carry_env(self, comments, compares, look_files=None, **env):
        return {**self.marked_with(*comments),
                "FAKE_COMPARES": json.dumps(compares),
                "FAKE_LOOK_FILES": json.dumps(
                    {self.LOOK_BASE: self.CONSOLE_SET} if look_files is None else look_files),
                **env}

    def test_a_kept_look_approval_admits_a_later_head(self):
        repo = self.look_repo()
        a, h, x, t = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_X, self.LOOK_T
        page, inbox, testf, doc = self.PAGE, self.INBOX, self.TESTF, self.DOC
        cases = {
            "a test-only commit": self.look_world([(h, [a])], [testf]),
            "a clean merge of main": self.look_world(
                [(h, [a, x])], [doc],
                extra=[(a, x, [doc]), (x, a, [page]), (x, h, [page])]),
            "a clean merge where main and the pull request edited different parts of page.html":
                self.look_world(
                    [(h, [a, x])], [(page, "x")],
                    extra=[(a, x, [(page, "x")]), (x, a, [(page, "a")]), (x, h, [(page, "a")])]),
            "a clean merge that brings a look change from main": self.look_world(
                [(h, [a, x])], [inbox],
                extra=[(a, x, [inbox]), (x, a, [page]), (x, h, [page])]),
            "both": self.look_world(
                [(t, [a]), (h, [t, x])], [inbox, testf],
                extra=[(a, t, [testf]), (t, x, [inbox]), (x, t, [page]), (t, h, [inbox]),
                       (x, h, [page, testf])]),
        }
        for name, compares in cases.items():
            with self.subTest(case=name):
                result = self.run_guard(
                    self.LOOK_PINNED, repo,
                    self.look_carry_env([self.look_comment(10, head=a)], compares))
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("", result.stderr)

    def test_a_kept_look_approval_still_needs_the_pinned_head(self):
        a, h, x, t = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_X, self.LOOK_T
        compares = self.look_world(
            [(t, [a]), (h, [t, x])], [self.INBOX, self.TESTF],
            extra=[(a, t, [self.TESTF]), (t, x, [self.INBOX]), (x, t, [self.PAGE]),
                   (t, h, [self.INBOX]), (x, h, [self.PAGE, self.TESTF])])
        result = self.run_guard(
            self.LOOK_MERGE, self.look_repo(),
            self.look_carry_env([self.look_comment(10, head=a)], compares))
        self.assert_look_refusal(result, self.LOOK_UNPINNED_REFUSAL)

    def test_the_look_gate_refuses_each_shape_a_kept_approval_does_not_cover(self):
        repo = self.look_repo()
        a, h, x, t = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_X, self.LOOK_T
        page, inbox, testf, doc, base = self.PAGE, self.INBOX, self.TESTF, self.DOC, self.LOOK_BASE
        approved = [self.look_comment(10, head=a)]
        world = self.look_world
        incomplete = world([(h, [a])], [testf])
        incomplete[f"{base}...{h}"]["total_commits"] += 1
        diverged = world([(h, [a])], [testf])
        diverged[f"{a}...{h}"]["status"] = "diverged"
        forced = world([(h, [a])], [testf])
        del forced[f"{a}...{h}"]
        many = world([(h, [a])], [testf])
        many[f"{a}...{h}"] = self.look_compare([f"tests/t{n}.py" for n in range(300)])
        weird = world([(h, [a])], [testf])
        weird[f"{a}...{h}"] = self.look_compare([{"filename": testf, "status": "weird"}])
        empty = world([(h, [a])], [testf])
        empty[f"{a}...{h}"] = {}
        outside = world([(h, [a])], [testf])
        outside[f"{base}...{a}"] = self.look_compare(
            [doc], commits=[(a, [self.LOOK_FORK])])
        plain = world([(h, [a])], [testf])
        unknown = '{"version": 1, "sets": {"console": ["python/agent_tools/console/**"]}, "x": 1}'
        cases = {
            "a look file changed": (approved, world([(h, [a])], [page]), {}),
            "an edit moved within a look file": (approved, world(
                [(t, [a]), (h, [t])], [page], extra=[(a, t, [page]), (t, h, [page])]), {}),
            "a conflict resolved inside a look file": (approved, world(
                [(h, [a, x])], [(page, "r")],
                extra=[(a, x, [(page, "x")]), (x, a, [(page, "a")]), (x, h, [(page, "r")])]), {}),
            "an edit inside a merge": (approved, world(
                [(h, [a, x])], [doc, page],
                extra=[(a, x, [doc]), (x, a, [page]), (x, h, [page])]), {}),
            "a merge that drops main's look edit": (approved, world(
                [(h, [a, x])], [doc],
                extra=[(a, x, [inbox, doc]), (x, a, [page]), (x, h, [page, inbox])]), {}),
            "a look edit and its revert": (approved, world(
                [(t, [a]), (h, [t])], [testf],
                extra=[(a, t, [page]), (t, h, [(page, "revert"), testf])]), {}),
            "incomplete commits under an unchanged look diff": (approved, incomplete, {}),
            "an approved head the head does not contain": (approved, diverged, {}),
            "a force-push": (approved, forced, {}),
            "a failed comparison": (approved, plain, {"FAKE_COMPARE_MODE": "nonzero"}),
            "an unreadable comparison": (approved, plain, {"FAKE_COMPARE_MODE": "invalid"}),
            "a comparison of 300 files": (approved, many, {}),
            "an unknown file status": (approved, weird, {}),
            "a compare answering an empty object": (approved, empty, {}),
            "a failed base read": (approved, plain, {"FAKE_BRANCH_MODE": "nonzero"}),
            "no declared set": (approved, plain, {"look_files": {}}),
            "an unreadable set file": (approved, plain, {"look_files": {base: "{"}}),
            "a set with an unknown field": (approved, plain, {"look_files": {base: unknown}}),
            "a change outside every set": (approved, outside, {}),
            "a later changes answer": ([
                self.look_comment(10, head=a),
                self.look_comment(11, head=x, answer="changes")], plain, {}),
            "an untrusted approval": ([
                self.look_comment(10, head=a, association="COLLABORATOR")], plain, {}),
        }
        for name, (comments, compares, extra) in cases.items():
            with self.subTest(case=name):
                result = self.run_guard(
                    self.LOOK_PINNED, repo, self.look_carry_env(comments, compares, **extra))
                self.assert_look_refusal(result)

    LOOK_DIGEST = hashlib.sha256(("a" * 64 + "\n" + "c" * 64).encode()).hexdigest()

    def look_pics_comment(self, cid, head):
        return {"id": cid,
                "body": look_marker.approval_body(
                    1200, 1300, head, "approved", f"m{cid}", pictures=self.LOOK_DIGEST),
                "updated_at": "2026-11-16T10:00:00Z", "author_association": "OWNER"}

    def look_carry_comment(self, cid, a, h, pictures=LOOK_DIGEST, association="OWNER"):
        return {"id": cid, "body": look_marker.carry_body(1200, 1300, a, h, pictures),
                "updated_at": "2026-11-16T10:00:00Z", "author_association": association}

    def merges_world(self, after):
        base, a, h = self.LOOK_BASE, self.LOOK_APPROVED, self.LOOK_HEAD
        return {
            f"{base}...{a}": self.look_compare([self.PAGE], commits=[(a, [self.LOOK_FORK])]),
            f"{a}...{h}": self.look_compare([self.DOC]),
            f"{base}...{h}": self.look_compare(commits=[(a, [self.LOOK_FORK])] + list(after)),
        }

    def test_a_carried_look_approval_admits_a_head_that_only_merged_main(self):
        repo = self.look_repo()
        a, h, x, t = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_X, self.LOOK_T
        comments = [self.look_pics_comment(10, a), self.look_carry_comment(11, a, h)]
        for name, after in {"one merge": [(h, [a, x])],
                            "two merges": [(t, [a, x]), (h, [t, self.LOOK_F])]}.items():
            with self.subTest(case=name):
                result = self.run_guard(
                    self.LOOK_PINNED, repo,
                    self.look_carry_env(comments, self.merges_world(after), look_files={}))
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("", result.stderr)

    def look_files_line(self, cid, a, h, association="OWNER"):
        return {"id": cid, "body": look_marker.carry_body(1200, 1300, a, h, None),
                "updated_at": "2026-11-16T10:00:00Z", "author_association": association}

    def files_carry_world(self, after, b_h_files=(), a_h_files=()):
        base, a, h = self.LOOK_BASE, self.LOOK_APPROVED, self.LOOK_HEAD
        return {
            f"{base}...{a}": self.look_compare([self.DOC], commits=[(a, [self.LOOK_FORK])]),
            f"{a}...{h}": self.look_compare(a_h_files or [self.DOC]),
            f"{base}...{h}": self.look_compare(
                b_h_files or [self.DOC], commits=[(a, [self.LOOK_FORK])] + list(after)),
        }

    def test_a_look_files_carry_admits_a_pictureless_approval_across_main_merges(self):
        a, h, x = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_X
        comments = [self.look_comment(10, head=a), self.look_files_line(11, a, h)]
        result = self.run_guard(
            self.LOOK_PINNED, self.look_repo(),
            self.look_carry_env(comments, self.files_carry_world([(h, [a, x])])))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)

    def test_the_look_gate_refuses_each_shape_a_look_files_carry_does_not_cover(self):
        repo = self.look_repo()
        a, h, x = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_X
        plain, line = self.look_comment(10, head=a), self.look_files_line(11, a, h)
        merged = self.files_carry_world([(h, [a, x])])
        cases = {
            "no line": ([plain], merged, None),
            "B...H also listing a look file": (
                [plain, line], self.files_carry_world([(h, [a, x])], b_h_files=[self.DOC, self.PAGE]), None),
            "a merge that brought a look file in": (
                [plain, line], self.files_carry_world([(h, [a, x])], a_h_files=[self.DOC, self.PAGE]), None),
            "a one-parent commit": ([plain, line], self.files_carry_world([(h, [a])]), None),
            "a collaborator's line": (
                [plain, self.look_files_line(11, a, h, association="COLLABORATOR")], merged, None),
            "a line that was ended": ([plain, line, self.look_end_comment(12, of=11)], merged, None),
            "an absent set file": ([plain, line], merged, {}),
        }
        for name, (comments, compares, look_files) in cases.items():
            with self.subTest(case=name):
                result = self.run_guard(
                    self.LOOK_PINNED, repo,
                    self.look_carry_env(comments, compares, look_files=look_files))
                self.assert_look_refusal(result)

    def test_a_line_that_does_not_carry_still_admits_a_head_the_look_files_keep(self):
        a, h, t = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_T
        compares = self.merges_world([(t, [a]), (h, [t])])
        compares[f"{a}...{t}"] = self.look_compare([self.DOC])
        compares[f"{t}...{h}"] = self.look_compare([self.DOC])
        comments = [self.look_pics_comment(10, a), self.look_carry_comment(11, a, h)]
        result = self.run_guard(
            self.LOOK_PINNED, self.look_repo(), self.look_carry_env(comments, compares))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)

    def test_the_look_gate_refuses_each_shape_a_carry_does_not_cover(self):
        repo = self.look_repo()
        a, h, x, t = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_X, self.LOOK_T
        pics, line = self.look_pics_comment(10, a), self.look_carry_comment(11, a, h)
        merged = self.merges_world([(h, [a, x])])
        diverged = self.merges_world([(h, [a, x])])
        diverged[f"{a}...{h}"]["status"] = "diverged"
        cases = {
            "no carry line": ([pics], merged),
            "a line whose digest differs": ([pics, self.look_carry_comment(
                11, a, h, hashlib.sha256(("b" * 64).encode()).hexdigest())], merged),
            "an approval without pictures": ([self.look_comment(10, head=a), line], merged),
            "a line naming another head": ([pics, self.look_carry_comment(11, a, t)], merged),
            "a line naming another approved head": ([pics, self.look_carry_comment(11, x, h)], merged),
            "a one-parent commit": ([pics, line], self.merges_world([(h, [a])])),
            "a pull request commit as second parent": (
                [pics, line], self.merges_world([(t, [a]), (h, [t, a])])),
            "a merge of an earlier pull request merge": (
                [pics, line], self.merges_world([(t, [a, x]), (self.LOOK_F, [t, x]), (h, [self.LOOK_F, t])])),
            "a line by a collaborator": (
                [pics, self.look_carry_comment(11, a, h, association="COLLABORATOR")], merged),
            "a line that was ended": ([pics, line, self.look_end_comment(12, of=11)], merged),
            "A...H diverged": ([pics, line], diverged),
            "a later changes answer": (
                [pics, line, self.look_comment(12, head=x, answer="changes")], merged),
        }
        for name, (comments, compares) in cases.items():
            with self.subTest(case=name):
                result = self.run_guard(
                    self.LOOK_PINNED, repo,
                    self.look_carry_env(comments, compares, look_files={}))
                self.assert_look_refusal(result)

    def test_a_pictured_approval_is_kept_by_no_look_file_rule_without_its_carry_line(self):
        # Issue 1566 review: the owner looked at pictures, so a head the look files alone would keep needs the carry line.
        repo = self.look_repo()
        a, h, x = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_X
        cases = {
            "a non-merge commit outside the look files": self.look_world([(h, [a])], [self.TESTF]),
            "a clean merge of main": self.look_world(
                [(h, [a, x])], [self.DOC], extra=[(a, x, [self.DOC]), (x, a, [self.PAGE]), (x, h, [self.PAGE])]),
        }
        for name, compares in cases.items():
            with self.subTest(case=name):
                plain = self.run_guard(
                    self.LOOK_PINNED, repo, self.look_carry_env([self.look_comment(10, head=a)], compares))
                self.assertEqual(0, plain.returncode, plain.stderr)
                pictured = self.run_guard(
                    self.LOOK_PINNED, repo, self.look_carry_env([self.look_pics_comment(10, a)], compares))
                self.assert_look_refusal(pictured)

    def test_a_carried_head_still_needs_the_pinned_head(self):
        a, h, x = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_X
        comments = [self.look_pics_comment(10, a), self.look_carry_comment(11, a, h)]
        result = self.run_guard(
            self.LOOK_MERGE, self.look_repo(),
            self.look_carry_env(comments, self.merges_world([(h, [a, x])]), look_files={}))
        self.assert_look_refusal(result, self.LOOK_UNPINNED_REFUSAL)

    def test_a_worded_fix_admits_one_look_commit(self):
        repo = self.look_repo()
        a, h, f, f1 = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_F, self.LOOK_F1
        page, testf = self.PAGE, self.TESTF

        def fix(head=a):
            return {"id": 10,
                    "body": look_marker.approval_body(
                        1200, 1300, head, "fix", "m10", words="make the heading bold"),
                    "updated_at": "2026-11-16T10:00:00Z", "author_association": "OWNER"}

        world = self.look_world
        admitted = world([(f, [a]), (h, [f])], [page, testf],
                         extra=[(a, f, [page]), (f, h, [testf])])
        refused = {
            "a second look commit": (fix(), world(
                [(f1, [a]), (f, [f1]), (h, [f])], [page],
                extra=[(a, f1, [page]), (f1, f, [page]), (f, h, [testf])])),
            "two look commits on a side branch merged in": (fix(), world(
                [(f1, [a]), (f, [f1]), (h, [a, f])], [page])),
            "a fix with no look commit": (fix(), world(
                [(f, [a]), (h, [f])], [testf], extra=[(a, f, [testf]), (f, h, [testf])])),
            "a fix answer naming the current head": (fix(h), world([(h, [a])], [testf])),
        }
        result = self.run_guard(
            self.LOOK_PINNED, repo, self.look_carry_env([fix()], admitted))
        self.assertEqual(0, result.returncode, result.stderr)
        for name, (comment, compares) in refused.items():
            with self.subTest(case=name):
                self.assert_look_refusal(self.run_guard(
                    self.LOOK_PINNED, repo, self.look_carry_env([comment], compares)))

    def gh_log(self, path):
        text = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
        return [json.loads(line) for line in text.splitlines()]

    def test_a_pull_request_cannot_change_its_look_files(self):
        a, h, base = self.LOOK_APPROVED, self.LOOK_HEAD, self.LOOK_BASE
        shrunk = '{"version": 1, "sets": {"console": ["python/agent_tools/console/*.py"]}}'
        compares = {
            f"{base}...{a}": self.look_compare(
                [self.PAGE, "python/agent_tools/console/view.py"],
                commits=[(a, [self.LOOK_FORK])]),
            f"{a}...{h}": self.look_compare([self.PAGE, ".github/look-files.json"]),
            f"{base}...{h}": self.look_compare(commits=[(a, [self.LOOK_FORK]), (h, [a])]),
        }
        look_files = {base: self.CONSOLE_SET, h: shrunk, "main": shrunk,
                      "issue-1200-page": shrunk}
        log = Path(self.fixture_dir.name) / "gh-log-pull-request-files"
        log.unlink(missing_ok=True)
        result = self.run_guard(
            self.LOOK_PINNED, self.look_repo(),
            self.look_carry_env([self.look_comment(10, head=a)], compares, look_files,
                                FAKE_GH_LOG=str(log)))
        self.assert_look_refusal(result)
        argvs = self.gh_log(log)
        contents = [argv for argv in argvs if "contents/" in argv[-1]]
        self.assertEqual(1, len(contents), argvs)
        self.assertTrue(contents[0][-1].endswith("?ref=" + base), contents)
        compared = [argv[-1] for argv in argvs if "/compare/" in argv[-1]]
        self.assertTrue(compared)
        for path in compared:
            self.assertRegex(path.split("/compare/")[1], r"[0-9a-f]{40}\.\.\.[0-9a-f]{40}")

    def test_the_look_carry_reads_only_what_its_grammar_allows(self):
        repo = self.look_repo()
        a, base = self.LOOK_APPROVED, self.LOOK_BASE
        compare = {"status": "ahead", "files": []}
        answers = {f"{base}...{n:040x}": compare for n in range(4)}
        cases = {
            "a path outside the grammar": ('["pulls/1300/merge"]', lambda argvs: [
                x for x in argvs if x[-1].endswith("pulls/1300/merge")], 0, None),
            "more reads than the limit": (
                "[f'compare/{n:040x}...{n:040x}' for n in range(49)]",
                lambda argvs: [x for x in argvs if "/compare/" in x[-1]], 0, None),
            "a judge that keeps asking": (
                "[f'compare/{BASE}...{len(reads):040x}']",
                lambda argvs: [x for x in argvs if "/compare/" in x[-1]],
                2, 4),
            "a contents path at another ref": (
                "[f\"contents/.github/look-files.json?ref={'c' * 40}\"]",
                lambda argvs: [x for x in argvs if "contents/" in x[-1]], 0, None),
        }
        for name, (need, pick, expected, runs) in cases.items():
            with self.subTest(case=name):
                directory = Path(tempfile.mkdtemp(dir=self.fixture_dir.name))
                counter, log = directory / "runs", directory / "gh-log"
                stub = directory / "stub-look-bin"
                stub.write_text(
                    f"#!{sys.executable}\n"
                    "import json, sys\n"
                    "payload = json.load(sys.stdin)\n"
                    f"open({str(counter)!r}, 'a').write('run\\n')\n"
                    "carry = payload.get('carry') or {}\n"
                    f"BASE = carry.get('base', {base!r})\n"
                    "reads = carry.get('reads', {})\n"
                    "print(json.dumps({'verdict': 'refuse', 'issue': 1200, 'covers': ['x'],\n"
                    f"    'candidates': [{{'issue': 1200, 'head': {a!r}, 'answer': 'approved'}}],\n"
                    f"    'need': {need}}}))\n"
                    "sys.exit(1)\n", encoding="utf-8")
                stub.chmod(0o755)
                env = {**self.marked_with(self.look_comment(10, head=a)),
                       "FAKE_COMPARES": json.dumps(answers), "FAKE_GH_LOG": str(log)}
                result = self.run_guard(
                    self.LOOK_PINNED, repo, env,
                    guard_args=("--gh-bin", str(self.fake_gh), "--look-bin", str(stub)))
                self.assert_look_refusal(result)
                self.assertEqual(expected, len(pick(self.gh_log(log))))
                if runs is not None:
                    self.assertEqual(runs, len(counter.read_text().splitlines()))

    def test_the_guard_and_the_reader_share_the_carry_constants(self):
        spec = importlib.util.spec_from_file_location("lifecycle_guard_look", GUARD_SOURCE)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        self.assertEqual(look_marker.LOOK_FILES_PATH, guard.LOOK_FILES_PATH)
        self.assertEqual(look_marker.CARRY_RUNS, guard.LOOK_CARRY_RUNS)
        self.assertEqual(look_marker.READ_LIMIT, guard.LOOK_READ_LIMIT)

    RELEASE_MERGE = "gh pr merge 1484 --repo elevenyellow/nodocom --merge"

    def test_the_release_arm_meets_the_look_gate(self):
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        env = {**self.release_env(), "FAKE_BODY_JSON": self.look_pr_json("Closes #1200"),
               "FAKE_ISSUES": json.dumps(self.LOOK_MARKED)}
        result = self.run_guard(self.RELEASE_MERGE, repo, env)
        self.assert_look_refusal(
            result, self.LOOK_REFUSAL.replace("1a2b3c4", self.HEAD_SHA[:7]))

    def test_a_marked_issue_with_an_unreadable_head_refuses(self):
        result = self.run_guard(
            self.LOOK_MERGE, self.look_repo(), self.look_env(self.LOOK_MARKED, head=None))
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("lifecycle guard: unsafe merge: cannot read the PR head commit",
                      result.stderr.splitlines())

    def test_a_merge_without_a_look_bin_refuses(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": self.LOOK_MERGE},
                   "cwd": str(self.look_repo())}
        child_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_")}
        child_env.update(self.look_env(self.LOOK_MARKED))
        result = subprocess.run(
            [sys.executable, "-I", str(GUARD_SOURCE), "--base-policy", str(BASE_POLICY_PATH),
             "--policy", str(self.policy), "--derive-bin", str(self.fake_derive),
             "--gh-bin", str(self.fake_gh)],
            input=json.dumps(payload), text=True, capture_output=True, timeout=5,
            check=False, env=child_env)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual("lifecycle guard: look check failed: no --look-bin was given\n",
                         result.stderr)

    def test_registered_hook_names_the_look_check(self):
        wrapper = self.guard.read_text(encoding="utf-8")
        self.assertRegex(wrapper, r"lifecycle_guard\.py --look-bin /nix/store/\S+-claude-guard-"
                                  r"look-check --base-policy ")
        look_check = Path(wrapper.split("--look-bin ", 1)[1].split(" ", 1)[0])
        script = look_check.read_text(encoding="utf-8")
        self.assertRegex(script, r"\A#!/nix/store/\S+/bin/\S+ -p\nunset BASH_ENV ENV\n")
        self.assertIn(f'exec {self.installed_launcher("look-approval")} judge "$@"\n', script)

    def test_registered_hook_names_the_land_check(self):
        wrapper = self.guard.read_text(encoding="utf-8")
        land_check = Path(wrapper.split("--land-bin ", 1)[1].split(" ", 1)[0])
        self.assertRegex(str(land_check), r"/nix/store/\S+-claude-guard-land-check\Z")
        script = land_check.read_text(encoding="utf-8")
        self.assertRegex(script, r"\A#!/nix/store/\S+/bin/\S+ -p\nunset BASH_ENV ENV\n")
        self.assertIn('export PATH="', script)
        self.assertIn(f'exec {self.installed_launcher("forge-claim")} land permit "$@"\n', script)

    def test_a_merge_not_holding_the_land_lease_is_refused_naming_its_condition(self):
        head, other = "d4d9acc0505c73305b3e0ced029db43100bc0e8a", "e" * 40
        merge = f"gh pr merge 1 --repo fagenorn/nix-config --merge --match-head-commit {head} --delete-branch"
        unpinned = "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch"
        lock, limit = land_lock.lock_ref("main"), land_lock.LEASE_LAPSE - land_lock.MERGE_MARGIN
        now = int(time.time())

        def lease(pr, sha, ago):
            return land_lock.lease_prefix("main") + f"{now - ago}-{pr}-{now - ago}", sha

        def refs(*pairs, mode=""):
            return {"FAKE_LAND_REFS": json.dumps(dict(pairs)), "FAKE_LAND_NOW": str(now),
                    "FAKE_LAND_MODE": mode}

        at_lock = f"the land lock {lock} is at {other[:7]}, not at the head {head[:7]} of pull request 1"
        refused = "lifecycle guard: unsafe merge: the PR does not hold the land lease: "
        for name, command, env, line in (
            ("taken over", merge, refs((lock, other), lease(9, other, 0)),
             refused + at_lock + "; pull request 9 holds it under a lease"),
            ("lock elsewhere", merge, refs((lock, other)), refused + at_lock),
            ("lease at another head", merge, refs((lock, head), lease(1, other, 9)),
             refused + f"the newest land lease of pull request 1 is at {other[:7]}, not at its head {head[:7]}"),
            ("lease lapsed", merge, refs((lock, head), (land_lock.lease_prefix("main") + f"{now - 900}-1-{now - limit}", head)),
             refused + f"the newest land lease of pull request 1 last beat {limit} s ago, "
                       f"and a merge needs a beat under {limit} s"),
            ("unpinned under a lock", unpinned, refs((lock, head)),
             refused + f"the land lock {lock} is held, so the merge must carry --match-head-commit {head}"),
            ("forge failure", merge, refs((lock, head), mode="fail"), None),
            ("no lock", merge, refs(), ""),
            ("no lock, unpinned", unpinned, refs(), ""),
            ("holder with no lease", merge, refs((lock, head)), ""),
            ("holder with a fresh lease", merge, refs((lock, head), lease(1, head, 0)), ""),
        ):
            with self.subTest(name):
                result = self.run_guard(
                    command, self.make_repo("git@github.com:fagenorn/nix-config.git"), env, timeout=60)
                if line is None:
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertTrue(result.stderr.startswith("lifecycle guard: land check failed: "), result.stderr)
                else:
                    self.assertEqual((2 if line else 0, line + "\n" if line else ""),
                                     (result.returncode, result.stderr))

    def test_the_merge_commit_text_reaches_the_look_gate_on_the_release_arm(self):
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        marked = {"FAKE_ISSUES": json.dumps(self.LOOK_MARKED)}
        subject = f'{self.RELEASE_MERGE} --subject "Closes #1200"'
        refusal = self.LOOK_REFUSAL.replace("1a2b3c4", self.HEAD_SHA[:7])
        by_subject = {**self.release_env(), **marked,
                      "FAKE_BODY_JSON": self.look_pr_json("Release")}
        by_title = {**self.release_env(), **marked,
                    "FAKE_BODY_JSON": self.look_pr_json("Release", title="Closes #1200")}
        for name, command, env in (("subject", subject, by_subject),
                                   ("title", self.RELEASE_MERGE, by_title)):
            with self.subTest(text=name):
                self.assert_look_refusal(self.run_guard(command, repo, env), refusal)
        other = f'{self.RELEASE_MERGE} --subject "Closes other/repo#1200"'
        result = self.run_guard(other, repo, by_subject)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_a_marked_release_with_a_matching_approval_admits(self):
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        issues = {"1200": {"body": self.LOOK_BODY, "comments": [
            self.look_comment(10, issue=1200, pr=1484, head=self.HEAD_SHA)]}}
        env = {**self.release_env(), "FAKE_BODY_JSON": self.look_pr_json("Closes #1200"),
               "FAKE_ISSUES": json.dumps(issues)}
        result = self.run_guard(
            f"{self.RELEASE_MERGE} --match-head-commit {self.HEAD_SHA}", repo, env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)

    def test_an_approved_marked_merge_without_match_head_commit_refuses(self):
        approved = self.marked_with(self.look_comment(10))
        for name, command, repo, env in (
            ("feature arm", self.LOOK_MERGE, self.look_repo(), approved),
            ("with a subject", self.LOOK_MERGE.replace(
                "--merge", '--merge --subject "page (#1300)"'), self.look_repo(), approved),
        ):
            with self.subTest(arm=name):
                self.assert_look_refusal(
                    self.run_guard(command, repo, env), self.LOOK_UNPINNED_REFUSAL)
        release_issues = {"1200": {"body": self.LOOK_BODY, "comments": [
            self.look_comment(10, issue=1200, pr=1484, head=self.HEAD_SHA)]}}
        release_env = {**self.release_env(), "FAKE_BODY_JSON": self.look_pr_json("Closes #1200"),
                       "FAKE_ISSUES": json.dumps(release_issues)}
        result = self.run_guard(
            self.RELEASE_MERGE, self.make_repo("git@github.com:elevenyellow/nodocom.git"),
            release_env)
        self.assert_look_refusal(
            result, self.LOOK_UNPINNED_REFUSAL.replace(self.LOOK_HEAD, self.HEAD_SHA))

    def test_every_github_closing_form_reaches_the_look_gate(self):
        repo = self.look_repo()
        forms = (
            "Fix #1200", "Fixed #1200", "Closed #1200", "Close #1200", "Resolve #1200",
            "Resolved #1200", "closes: #1200",
            "Closes https://github.com/fagenorn/nix-config/issues/1200",
            "fixes fagenorn/nix-config#1200")
        for form in forms:
            with self.subTest(form=form):
                env = self.look_env(self.LOOK_MARKED, body=f"Settles it.\n{form}", branch="topic")
                self.assert_look_refusal(self.run_guard(self.LOOK_MERGE, repo, env))

    def test_another_repositorys_issue_url_is_ignored(self):
        env = self.look_env(
            self.LOOK_MARKED, branch="topic",
            body="Closes https://github.com/other/repo/issues/1200")
        result = self.run_guard(self.LOOK_MERGE, self.look_repo(), env)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
