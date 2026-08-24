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
    "Bash(git push:*)", "Bash(gh pr create:*)",
    "Bash(git branch -d:*)", "Bash(gh pr merge:*)", "Agent",
]

# Stand-in for `gh`. Answers the two lookups the guard makes for any slug and
# any protected branch, so the merge path can be exercised in every fixture
# repository. FAKE_<STAGE>_MODE injects failures; FAKE_<STAGE>_JSON overrides
# the payload.
FAKE_GH_SCRIPT = '''
import os
import sys
import time

# The guard must scrub the gh-recognised token variables from its lookups (the
# harness token is narrower than the keyring credential). Refusing to answer
# when one is visible makes every merge-path test double as that assertion.
for name in ("GITHUB_TOKEN", "GH_TOKEN"):
    if name in os.environ:
        print("fake gh saw " + name + " in its environment", file=sys.stderr)
        raise SystemExit(64)

argv = sys.argv[1:]
stage = None
number = ""
slug = ""
branch = ""
if (
    len(argv) == 7
    and argv[0:2] == ["pr", "view"]
    and argv[3] == "--repo"
    and argv[5] == "--json"
    and argv[6] == "state,baseRefName,url"
):
    stage, number, slug, branch = "pr", argv[2], argv[4], "main"
elif len(argv) == 2 and argv[0] == "api":
    parts = argv[1].split("/")
    if (
        len(parts) == 6
        and parts[0] == "repos"
        and parts[3] == "branches"
        and parts[5] == "protection"
    ):
        stage = "protection"
        slug = parts[1] + "/" + parts[2]
        branch = parts[4]
if stage is None:
    print("unexpected fake-gh argv: " + repr(argv), file=sys.stderr)
    raise SystemExit(64)

mode = os.environ.get("FAKE_" + stage.upper() + "_MODE", "ok")
if mode == "nonzero":
    print("fake " + stage + " failure", file=sys.stderr)
    raise SystemExit(9)
if mode == "timeout":
    time.sleep(2)
if mode == "invalid":
    print("{")
    raise SystemExit(0)

if stage == "pr":
    default = (
        '{"state":"OPEN","baseRefName":"' + branch + '",'
        '"url":"https://github.com/' + slug + "/pull/" + number + '"}'
    )
else:
    default = (
        '{"required_status_checks":{"contexts":["Nix Eval"]},'
        '"enforce_admins":{"enabled":true}}'
    )
print(os.environ.get("FAKE_" + stage.upper() + "_JSON", default))
'''


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
        cls.fake_gh.write_text(f"#!{sys.executable}\n" + FAKE_GH_SCRIPT, encoding="utf-8")
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

    def invoke_command_in(self, command, cwd, *guard_args, env=None):
        return self.invoke_raw(
            json.dumps({
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(cwd),
            }),
            *guard_args, env=env,
        )

    def run_guard(self, command, cwd=None, env=None, guard_args=None):
        """Invoke the guard with the fake `gh` wired in by default."""
        if guard_args is None:
            guard_args = ("--gh-bin", str(self.fake_gh))
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
        if cwd is not None:
            payload["cwd"] = str(cwd)
        return self.invoke_raw(json.dumps(payload), *guard_args, env=env)

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

    def test_heredoc_and_quoted_mentions_pass_in_own_repo(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        for command in (
            "cat > notes.md <<'EOF'\nrun gh pr merge 5 later\ngit push origin main\nEOF\n",
            'echo "docs say gh pr create --repo x"',
            "true # gh pr merge 9 --repo fagenorn/nix-config --merge --delete-branch",
            "workflow-state finish --notes 'blocked, cannot gh pr merge yet'",
            "rg -n 'git branch -d' docs/",
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(0, result.returncode, (command, result.stderr))

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
            "git push -u origin topic && rm -rf /",       # chained second command is fine BUT
        ):
            with self.subTest(command=bad):
                result = self.run_guard(bad, cwd=repo)
                if bad.endswith("rm -rf /"):
                    self.assertEqual(0, result.returncode, result.stderr)
                else:
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
        # `unsetGithubToken` repositories run the merge as
        # `unset GITHUB_TOKEN && gh pr merge ...` so gh falls back to the
        # keyring credential; exactly that literal prefix is grammatical.
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
        # The real-world shape that motivated the prefix: a nodocom ship-issue
        # merge onto the declared integration branch `dev`. The integration
        # base is exempt from the protection demand, so the protection stage is
        # poisoned here to prove the guard never even consults it.
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        result = self.run_guard(
            "unset GITHUB_TOKEN && gh pr merge 42 --repo elevenyellow/nodocom "
            "--merge --delete-branch",
            cwd=repo,
            env={"FAKE_PR_JSON":
                 '{"state":"OPEN","baseRefName":"dev",'
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
            "FAKE_PR_JSON": '{"state":"OPEN","baseRefName":"dev",'
                            '"url":"https://github.com/elevenyellow/nodocom/pull/7"}',
        }
        allowed = self.run_guard(merge, cwd=repo, env=dev_pr)
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        main_pr = {
            "FAKE_PROTECTION_MODE": "nonzero",
            "FAKE_PR_JSON": '{"state":"OPEN","baseRefName":"main",'
                            '"url":"https://github.com/elevenyellow/nodocom/pull/7"}',
        }
        blocked = self.run_guard(merge, cwd=repo, env=main_pr)
        self.assertEqual(2, blocked.returncode)
        self.assertIn("protection lookup failed", blocked.stderr)

    def test_prefixed_merge_near_misses_fail_closed(self):
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        merge = "gh pr merge 1 --repo fagenorn/nix-config --merge --delete-branch"
        for command in (
            f"unset PATH && {merge}",                               # wrong variable
            f"unset GITHUB_TOKEN GH_TOKEN && {merge}",              # extra variable
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


if __name__ == "__main__":
    unittest.main()
