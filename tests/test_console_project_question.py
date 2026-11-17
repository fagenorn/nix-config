"""The console's project question session (#1176): hook, launch, service and route.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import shutil
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import (
    account_remove, event_log, project_question, project_question_hook as hook, service, signin, sprints,
    view)
from agent_tools.project_contract import resolve_project
from agent_tools.system import siblings

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_account_service import Listing
from .test_console_writes import Case

DECLARED = (("just", "build"),)
REPO = "owner/p01"
GIT_READ_RULES = [
    "Bash(git log:*)", "Bash(git show:*)", "Bash(git diff:*)", "Bash(git status:*)",
    "Bash(git blame:*)", "Bash(git ls-files:*)", "Bash(git tag:*)"]
ROUTES = (project_question.Route("nix-build", ("just", "build"), "/srv/p01"),)
GITHUB = {"kind": "github", "cli": "gh", "repo_slug": "owner/p01",
          "credential_env": {"unset_before_invocation": []}}
REACH = project_question.Reach(ROUTES, "owner/p01")
ENVIRON = {"HOME": "/home/u", "PATH": "/bin"}
SESSION_ID = "0b5c8f9e-1d2a-4c3b-9e8f-7a6b5c4d3e2f"
SUCCESS = (
    b'{"type":"result","subtype":"success","is_error":false,'
    b'"result":" Answer: it builds the hosts. "}'
)


def SNAPSHOT(read_only, cwd_of=lambda id: "/srv/p01", root="/srv/p01", tracker=None):  # noqa: N802 -- a fixture
    return {
        "project": {"root": root, "id": "owner/p01", "name": "p01"},
        "production": {
            "status": "declared",
            "changes": {"commands": ["nix-activate"], "key_files": [], "mcp_tools": []},
            "read_only": {"commands": read_only, "mcp_tools": []},
            "release_profile": "github-release",
        },
        "bindings": {"commands": {
            "nix-build": {"argv": ["just", "build"], "cwd": cwd_of("nix-build"), "env": []},
            "nix-activate": {"argv": ["just", "switch"], "cwd": "/srv/p01", "env": []},
            "sub-check": {"argv": ["./check"], "cwd": "/srv/p01/sub", "env": []},
            "piped": {"argv": ["sh", "-c", "a|b"], "cwd": "/srv/p01", "env": []},
            "dev-read": {"argv": ["devenv", "shell", "--", "railway", "status"],
                         "cwd": cwd_of("dev-read"), "env": []},
        }, **({"tracker": tracker} if tracker is not None else {})},
    }


def bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def tool(name, tool_input=None):
    return {"tool_name": name, "tool_input": tool_input or {}}


class HookTableTest(unittest.TestCase):
    def test_the_hook_admits_reads_and_bare_declared_commands_and_denies_the_rest(self):
        allow = ("allow", hook.ALLOWED)
        lifecycle = ("deny", hook.LIFECYCLE_DENIED)
        undeclared = ("deny", hook.COMMAND_DENIED.format(commands="just build"))
        rows = [
            (tool("Read", {"file_path": "/srv/p01/README.md"}), DECLARED, allow),
            (tool("Grep", {"pattern": "x"}), DECLARED, allow),
            (tool("Glob", {"pattern": "**/*.nix"}), DECLARED, allow),
            (bash("just build"), DECLARED, allow),
            (bash("  just   build  "), DECLARED, allow),
        ]
        for name in ("Edit", "Write", "NotebookEdit"):
            rows.append((tool(name), DECLARED, ("deny", hook.WRITE_DENIED.format(tool=name))))
        for command in (
            "git push origin main",
            "gh pr create --title t --body b",
            "gh pr merge 7 --merge",
            "git branch -d topic",
            "gh release create v1.0.0",
            "just build && git push",
            "git -C . push origin main",
            "/usr/bin/git push origin main",
            "git -c core.x=y push",
            "git --git-dir=.git push",
            "git --git-dir .git push",
            "/usr/local/bin/gh pr create --title t",
            "gh pr -R owner/repo merge 7",
            "gh --repo owner/repo release create v1",
            "git -C . branch -d topic",
        ):
            rows.append((bash(command), DECLARED, lifecycle))
        rows.append((bash("git push"), (("git", "push"),), lifecycle))
        rows.append((bash("git -C . push origin main"), (("git", "-C", ".", "push", "origin", "main"),),
                     lifecycle))
        rows.append((bash("/usr/bin/git push origin main"),
                     (("/usr/bin/git", "push", "origin", "main"),), lifecycle))
        for command in ("just switch", "just", "just build extra", "cat README.md", "FOO=1 just build"):
            rows.append((bash(command), DECLARED, undeclared))
        for command in (
            "just build | cat",
            "just build > out.txt",
            "just build 2>&1",
            "just build < in.txt",
            "just build; rm -rf x",
            "just build && echo ok",
            "just build || true",
            "just build &",
            "(just build)",
            "$(just build)",
            "`just build`",
            "just build\nrm x",
            "'just' build",
            "just\nbuild",
            "just\tbuild",
            "just\rbuild",
            "just build\n",
        ):
            rows.append((bash(command), DECLARED, undeclared))
        for name in ("WebFetch", "Task", "Agent", "mcp__github__create_issue"):
            rows.append((tool(name), DECLARED, ("deny", hook.TOOL_DENIED.format(tool=name))))
        for document, allowed, expected in rows:
            with self.subTest(document):
                self.assertEqual(hook.decide(document, allowed), expected)

    def test_with_no_declared_command_only_the_git_reads_run(self):
        denied = ("deny", hook.NO_COMMANDS)
        self.assertEqual(hook.decide(bash("just build"), ()), denied)
        self.assertEqual(hook.decide(bash("ls"), ()), denied)
        self.assertEqual(hook.decide(tool("Read"), ()), ("allow", hook.ALLOWED))
        self.assertEqual(hook.decide(bash("git log --oneline"), ()), ("allow", hook.ALLOWED))
        self.assertEqual(
            hook.decide(bash("gh pr list --repo owner/p01"), ()), ("deny", hook.reads_denied(None)))

    def test_the_hook_admits_the_git_and_gh_reads_of_the_projects_own_repository(self):
        allow = ("allow", hook.ALLOWED)
        for command in (
            "git log", "git log --since=7.days.ago --oneline", "git log -n 20 --stat",
            "git show abc123 --stat", "git diff main..HEAD --stat", "git status",
            "git status --short", "git blame -- README.md", "git ls-files", "git tag",
            "git tag -l", "git tag --list v1.0", "git tag -l --sort=-creatordate -n3",
            "gh pr list --repo owner/p01 --state merged --limit 30",
            "gh pr list --repo=owner/p01",
            "gh pr view --repo owner/p01 12 --comments",
            "gh pr view -R owner/p01 12",
            "gh release list --repo owner/p01",
            "gh release view --repo owner/p01 v1.2.0",
            "gh issue list --repo owner/p01 --state closed",
            "gh issue view --repo owner/p01 7",
            "gh run list --repo owner/p01 --limit 10",
            "gh run view --repo owner/p01 123 --log-failed",
            "gh pr list --repo owner/p01 --search merged",
        ):
            with self.subTest(command):
                self.assertEqual(hook.decide(bash(command), DECLARED, repo=REPO), allow)
        self.assertEqual(hook.decide(bash("git log"), (), repo=None), allow)
        self.assertEqual(hook.decide(bash("just build"), DECLARED, repo=REPO), allow)

    def test_the_hook_denies_git_and_gh_writes_other_repositories_and_compositions(self):
        reads = ("deny", hook.reads_denied(REPO))
        undeclared = ("deny", hook.COMMAND_DENIED.format(commands="just build"))
        lifecycle = ("deny", hook.LIFECYCLE_DENIED)
        rows = []
        for command in (
            "git commit -m x", "git checkout main", "git reset --hard", "git fetch", "git pull",
            "git stash", "git config user.name", "git branch topic",
            "git tag v9", "git tag -d v1", "git tag -l -d v1", "git tag -ld", "git tag -a v9 -m x",
            "git tag -f v1",
            "git tag --format -l v9", "git tag --sort=refname --format -l v9",
            "git tag --format --list v9 HEAD", "git tag -l --sort",
            "git log --output=/tmp/x", "git diff --output /tmp/x", "git log --outp=/tmp/x",
            "git diff --ext-diff",
            "git -C /other log", "git -c core.pager=x log", "git --git-dir=/x log",
            "git --no-pager log",
            "/usr/bin/git log", "/usr/bin/gh pr list --repo owner/p01",
            "gh pr list", "gh pr list --state open", "gh pr list --repo other/repo",
            "gh pr list --repo=owner/p01x",
            "gh pr list --repo owner/p01 --repo other/repo",
            "gh pr list --repo owner/p01 -R owner/p01", "gh pr list -R other/repo",
            "gh pr list -Rowner/p01", "gh pr list --repo=other/repo", "gh pr list --repo owner/p01x",
            "gh pr list --repo Owner/p01", "gh pr list --repo",
            "gh pr view --repo owner/p01 https://github.com/other/repo/pull/1",
            "gh pr list --repo owner/p01 --head feature/x",
            "gh pr list --search --repo=owner/p01",
            "gh release view -- --repo=owner/p01",
            "gh pr view 12 --repo owner/p01",
            "gh release view --repo owner/p01 -- v1",
            "gh pr list --repo owner/p01 --repo owner",
            "gh pr list --repo owner/p01 -R owner",
            "gh pr view --repo owner/p01 1 -cRowner",
            "gh pr view --repo owner/p01 1 --web", "gh pr view --repo owner/p01 1 -w",
            "gh pr view --repo owner/p01 1 -cw",
            "gh issue create --repo owner/p01 --title t",
            "gh issue comment 1 --repo owner/p01 --body b",
            "gh issue close 1 --repo owner/p01", "gh pr checkout 1 --repo owner/p01",
            "gh pr review 1 --repo owner/p01 --approve",
            "gh release delete v1 --repo owner/p01", "gh release download v1 --repo owner/p01",
            "gh run rerun 1 --repo owner/p01", "gh run cancel 1 --repo owner/p01",
            "gh api repos/owner/p01", "gh -R owner/p01 pr list", "gh pr -R owner/p01 list",
            "git log | cat", "git log > out.txt", "git log; rm -rf x", "git log && echo ok",
            "git log || true", "git log &", "git log\nrm x", "git\tlog", "git log\n",
            "git log --format='%h'", "git diff HEAD~3",
            "gh pr list --repo owner/p01 | cat", "gh pr list --repo owner/p01 --jq .[0]",
        ):
            rows.append((command, REPO, reads))
        for command in ("(git log)", "$(git log)", "`git log`", "FOO=1 git log"):
            rows.append((command, REPO, undeclared))
        for command in ("gh pr merge 1 --repo owner/p01", "gh release create v1 --repo owner/p01",
                        "gh pr create --repo owner/p01 --title t", "git push"):
            rows.append((command, REPO, lifecycle))
        for command in ("gh pr list --repo owner/p01", "gh release list --repo owner/p01"):
            rows.append((command, None, ("deny", hook.reads_denied(None))))
        for command, repo, expected in rows:
            with self.subTest(command=command, repo=repo):
                self.assertEqual(hook.decide(bash(command), DECLARED, repo=repo), expected)
        self.assertNotEqual(hook.reads_denied(None), hook.reads_denied(REPO))
        self.assertIn("owner/p01", hook.reads_denied(REPO))
        self.assertNotIn("owner/p01", hook.reads_denied(None))

    def test_parse_repo_accepts_only_a_slug_or_nothing(self):
        self.assertIsNone(hook.parse_repo(""))
        self.assertEqual(hook.parse_repo("owner/p01"), "owner/p01")
        self.assertEqual(hook.parse_repo("fagenorn/nix-config"), "fagenorn/nix-config")
        for text in ("owner", "owner/p01/x", "-x/y", "owner/p 01", "a/b;c",
                     "https://github.com/a/b", "/p01"):
            with self.subTest(text):
                with self.assertRaises(ValueError):
                    hook.parse_repo(text)

    def test_a_malformed_call_is_denied(self):
        for document in (
            None,
            [],
            {},
            {"tool_name": ""},
            {"tool_name": "Bash"},
            {"tool_name": "Bash", "tool_input": {"command": 3}},
        ):
            with self.subTest(document):
                self.assertEqual(hook.decide(document, DECLARED), ("deny", hook.MALFORMED))

    def test_parse_allowed_accepts_only_lists_of_word_lists(self):
        self.assertEqual(hook.parse_allowed('[["just","build"]]'), (("just", "build"),))
        self.assertEqual(hook.parse_allowed("[]"), ())
        for text in ("{}", "[[]]", '[["just",""]]', "[[1]]", "nope"):
            with self.subTest(text):
                with self.assertRaises(ValueError):
                    hook.parse_allowed(text)


class HookProcessTest(unittest.TestCase):
    def run_hook(self, args, stdin_text):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.console.project_question_hook", *args],
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def wire(self, decision, reason):
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        }

    def test_the_module_prints_the_decision_in_the_client_format(self):
        args = ['[["just","build"]]', "owner/p01"]
        done = self.run_hook(args, json.dumps(bash("just build")))
        self.assertEqual(done.returncode, 0)
        self.assertEqual(json.loads(done.stdout), self.wire("allow", hook.ALLOWED))
        done = self.run_hook(args, json.dumps({"tool_name": "Write", "tool_input": {}}))
        self.assertEqual(json.loads(done.stdout), self.wire("deny", hook.WRITE_DENIED.format(tool="Write")))
        done = self.run_hook(args, json.dumps(bash("just\nbuild")))
        self.assertEqual(
            json.loads(done.stdout),
            self.wire("deny", hook.COMMAND_DENIED.format(commands="just build")),
        )
        done = self.run_hook(args, json.dumps(bash("gh pr list --repo owner/p01")))
        self.assertEqual(json.loads(done.stdout), self.wire("allow", hook.ALLOWED))
        done = self.run_hook(
            ['[["just","build"]]', ""], json.dumps(bash("gh pr list --repo owner/p01")))
        self.assertEqual(json.loads(done.stdout), self.wire("deny", hook.reads_denied(None)))

    def test_a_bad_argument_denies_everything(self):
        read = json.dumps(tool("Read", {"file_path": "/x"}))
        deep = "[" * 100000  # under the 128 KiB limit of one argv word
        for args, stdin_text in (
            ([], read),
            (["not json", "owner/p01"], read),
            (['[["just","build"]]', "owner/p01"], "{"),
            (['[["just","build"]]', "owner/p01"], deep),
            ([deep, "owner/p01"], read),
            (['[["just","build"]]'], read),
            (['[["just","build"]]', "owner/p01", "extra"], read),
            (['[["just","build"]]', "not-a-slug"], read),
        ):
            with self.subTest(args=args, stdin=stdin_text):
                done = self.run_hook(args, stdin_text)
                self.assertEqual(done.returncode, 0)
                self.assertEqual(json.loads(done.stdout), self.wire("deny", hook.MALFORMED))
                self.assertEqual(len(done.stdout.splitlines()), 1)
        done = self.run_hook(['[["just","build"]]', "owner/p01"], read)
        self.assertEqual(json.loads(done.stdout), self.wire("allow", hook.ALLOWED))


class LaunchTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "root"
        self.root.mkdir()
        self.settings_dir = Path(directory.name) / "state" / project_question.SETTINGS_DIR
        self.routes = (project_question.Route("nix-build", ("just", "build"), str(self.root)),)
        self.ask = self.make_ask(self.routes)
        self.calls = []
        self.settings = {}

    def make_ask(self, routes, root=None):
        return project_question.new_ask(
            "a" * 16, "owner/p01", str(root or self.root), "what does the build check?", "work",
            routes, self.settings_dir, session_id=SESSION_ID)

    def fake(self, stdout=SUCCESS, code=0, error=None, stderr=b"", act=None):
        def run(argv, *, timeout, cancel=None, **kwargs):
            self.calls.append((argv, timeout, cancel, kwargs))
            path = self.ask.settings
            if path.exists():
                self.settings = {
                    "text": path.read_text(),
                    "mode": path.stat().st_mode & 0o777,
                    "parent_mode": path.parent.stat().st_mode & 0o777,
                }
            if act is not None:
                act(kwargs)
            if error is not None:
                raise error
            if stderr:
                kwargs["stderr"].write(stderr)
            return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr=None)
        return run

    def start(self, run, ask=None, cancel=None, platform="linux"):
        return project_question.run_question(
            ask or self.ask, cancel, platform=platform, run=run, environ=ENVIRON)

    def test_a_session_with_a_repository_passes_it_to_its_hook_and_settings(self):
        ask = project_question.new_ask(
            "a" * 16, "owner/p01", str(self.root), "what shipped?", "work", self.routes,
            self.settings_dir, session_id=SESSION_ID, repo="owner/p01")
        self.ask = ask
        self.start(self.fake(), ask=ask)
        document = json.loads(self.settings["text"])
        self.assertEqual(
            shlex.split(document["hooks"]["PreToolUse"][0]["hooks"][0]["command"])[-1], "owner/p01")
        self.assertIn("Bash(gh pr list:*)", document["permissions"]["allow"])
        self.assertIsNone(self.make_ask(self.routes).repo)

    def test_the_launch_runs_sonnet_headless_in_the_root_under_the_chosen_profile(self):
        outcome = self.start(self.fake())

        argv, timeout, _cancel, kwargs = self.calls[0]
        self.assertEqual(argv, [
            "claude-account", "run", "-p", "--model", "sonnet", "--session-id", SESSION_ID,
            "--permission-mode", "dontAsk", "--setting-sources", "", "--strict-mcp-config", "--tools", "Read,Grep,Glob,Bash",
            "--output-format", "json", "--settings", str(self.ask.settings),
            project_question.prompt(self.ask.question, self.routes)])
        self.assertEqual(timeout, 300)
        self.assertEqual(kwargs["cwd"], str(self.root))
        self.assertEqual(kwargs["env"]["CLAUDE_ACCOUNT"], "work")
        self.assertTrue(kwargs["env"]["PATH"].startswith("/home/u/.agents/bin"))
        self.assertIs(kwargs["start_new_session"], True)
        self.assertEqual(outcome, project_question.Outcome("answered", answer="Answer: it builds the hosts."))

    def test_the_session_environment_drops_repository_selection_and_the_declared_credentials(self):
        ask = project_question.new_ask(
            "a" * 16, "owner/p01", str(self.root), "what shipped?", "work", self.routes,
            self.settings_dir, session_id=SESSION_ID, repo="owner/p01", unset=("GH_TOKEN", "GITHUB_TOKEN"))
        environ = {**ENVIRON, "GIT_DIR": "/other/.git", "GIT_WORK_TREE": "/other",
                   "GIT_INDEX_FILE": "/other/index", "GH_TOKEN": "stale", "GITHUB_TOKEN": "stale",
                   "KEEP": "1"}
        self.ask = ask
        project_question.run_question(ask, platform="linux", run=self.fake(), environ=environ)
        env = self.calls[0][3]["env"]
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GH_TOKEN", "GITHUB_TOKEN"):
            with self.subTest(name):
                self.assertNotIn(name, env)
        self.assertEqual((env["KEEP"], env["CLAUDE_ACCOUNT"]), ("1", "work"))

    def test_a_credential_declared_for_unsetting_stays_when_the_contract_declares_none(self):
        environ = {**ENVIRON, "GH_TOKEN": "mine"}
        project_question.run_question(self.ask, platform="linux", run=self.fake(), environ=environ)
        self.assertEqual(self.calls[0][3]["env"]["GH_TOKEN"], "mine")

    def test_reach_carries_the_credentials_the_contract_unsets_before_invocation(self):
        tracker = {**GITHUB, "credential_env": {"unset_before_invocation": ["GH_TOKEN", "GITHUB_TOKEN"]}}
        reach = project_question.reach_of("/srv/p01", resolve=lambda p: SNAPSHOT([], tracker=tracker))
        self.assertEqual(reach.unset, ("GH_TOKEN", "GITHUB_TOKEN"))
        for name, snapshot in (("none", SNAPSHOT([], tracker=GITHUB)), ("no tracker", SNAPSHOT([])),
                               ("not a list", SNAPSHOT([], tracker={**GITHUB, "credential_env": {
                                   "unset_before_invocation": "GH_TOKEN"}}))):
            with self.subTest(name):
                self.assertEqual(project_question.credential_unset(snapshot), ())

    def test_each_question_gets_its_own_uuid_session_id(self):
        a, b = project_question.new_session_id(), project_question.new_session_id()
        self.assertNotEqual(a, b)
        self.assertEqual(uuid.UUID(a).version, 4)
        self.assertEqual(str(uuid.UUID(a)), a)

    def test_the_settings_file_denies_writes_and_lifecycle_verbs_and_blocks_on_hook_failure(self):
        self.start(self.fake())

        document = json.loads(self.settings["text"])
        self.assertEqual(document["permissions"], {
            "defaultMode": "dontAsk",
            "allow": ["Read", "Grep", "Glob", "Bash(just build)", *GIT_READ_RULES],
            "deny": ["Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Agent",
                     "Bash(git push:*)", "Bash(gh pr create:*)", "Bash(gh pr merge:*)",
                     "Bash(git branch -d:*)", "Bash(gh release create:*)"],
        })
        hooks = document["hooks"]["PreToolUse"][0]["hooks"][0]
        self.assertEqual(document["hooks"], {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": hooks["command"], "timeout": 10, "onFailure": "block"}]}]})
        self.assertEqual(shlex.split(hooks["command"]), [
            *siblings.sibling_argv("console.project_question_hook"), '[["just","build"]]', ""])
        self.assertEqual(self.settings["mode"], 0o600)
        self.assertEqual(self.settings["parent_mode"], 0o700)
        self.assertFalse(self.ask.settings.exists())

    def test_a_repository_adds_its_gh_reads_to_the_settings_and_the_hook(self):
        document = project_question.settings_document(self.routes, "owner/p01")
        self.assertEqual(document["permissions"]["allow"][-8:], [
            "Bash(gh pr list:*)", "Bash(gh pr view:*)", "Bash(gh release list:*)",
            "Bash(gh release view:*)", "Bash(gh issue list:*)", "Bash(gh issue view:*)",
            "Bash(gh run list:*)", "Bash(gh run view:*)"])
        command = document["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertEqual(shlex.split(command)[-2:], ['[["just","build"]]', "owner/p01"])
        allow = project_question.settings_document(self.routes)["permissions"]["allow"]
        self.assertFalse([rule for rule in allow if rule.startswith("Bash(gh")])
        self.assertEqual(project_question.tools(()), "Read,Grep,Glob,Bash")

    def test_a_session_past_the_time_cap_is_timed_out(self):
        outcome = self.start(self.fake(error=subprocess.TimeoutExpired(["claude-account"], 300)))

        self.assertEqual(outcome, project_question.Outcome(
            "timed_out", reason="the session did not answer within 300 s"))
        self.assertFalse(self.ask.settings.exists())

    def test_each_failure_is_a_failed_outcome_with_its_reason(self):
        cancel = threading.Event()
        cases = [
            ("darwin", {"platform": "darwin", "run": self.fake()}, project_question.UNAVAILABLE_TEXT),
            ("root", {"run": self.fake(), "ask": self.make_ask(self.routes, self.root / "missing")},
             f"the project root {self.root / 'missing'} is not a directory"),
            ("missing binary", {"run": self.fake(error=FileNotFoundError())},
             "claude-account is not installed"),
            ("stderr", {"run": self.fake(code=1, stderr=b"first\n\nboom\n")}, "boom"),
            ("exit", {"run": self.fake(code=2)}, "the session exited 2"),
            ("not json", {"run": self.fake(stdout=b"not json")}, project_question.UNREADABLE_TEXT),
            ("is_error", {"run": self.fake(stdout=b'{"is_error":true,"result":"Credit balance is too low"}')},
             "Credit balance is too low"),
            ("cancel", {"run": self.fake(code=-9, act=lambda kwargs: cancel.set()), "cancel": cancel},
             project_question.STOPPED_TEXT),
        ]
        for name, kwargs, reason in cases:
            with self.subTest(name):
                self.calls.clear()
                outcome = self.start(**kwargs)
                self.assertEqual(outcome, project_question.Outcome("failed", reason=reason))
                self.assertFalse(self.ask.settings.exists())
                if name in ("darwin", "root"):
                    self.assertEqual(self.calls, [])


class DevenvRouteTest(unittest.TestCase):
    def roots(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        (base / "with_env").mkdir()
        (base / "with_env" / "devenv.nix").write_text("{}\n")
        (base / "plain").mkdir()
        (base / "dir_env" / "devenv.nix").mkdir(parents=True)
        return [str(base / name) for name in ("with_env", "plain", "dir_env")]

    def routes_in(self, root):
        return project_question.read_only_routes(
            SNAPSHOT(["nix-build", "dev-read"], cwd_of=lambda id: root, root=root))

    def test_a_declared_command_runs_inside_devenv_when_the_root_has_devenv_nix(self):
        with_env, plain, dir_env = self.roots()
        wrapped = (
            project_question.Route("nix-build", ("devenv", "shell", "--", "just", "build"), with_env),
            project_question.Route("dev-read", ("devenv", "shell", "--", "railway", "status"), with_env))
        self.assertEqual(self.routes_in(with_env), wrapped)
        bare = lambda root: (
            project_question.Route("nix-build", ("just", "build"), root),
            project_question.Route("dev-read", ("devenv", "shell", "--", "railway", "status"), root))
        self.assertEqual(self.routes_in(plain), bare(plain))
        self.assertEqual(self.routes_in(dir_env), bare(dir_env))

    def test_a_devenv_route_is_what_the_hook_and_settings_admit(self):
        routes = self.routes_in(self.roots()[0])
        allowed = [list(route.argv) for route in routes]
        self.assertIn("Bash(devenv shell -- just build)",
                      project_question.settings_document(routes)["permissions"]["allow"])
        self.assertEqual(hook.decide(bash("devenv shell -- just build"), allowed),
                         ("allow", hook.ALLOWED))
        self.assertEqual(hook.decide(bash("just build"), allowed)[0], "deny")
        self.assertIn("devenv shell -- just build", project_question.prompt("q", routes))


class NoProductionTest(unittest.TestCase):
    def test_read_only_routes_resolve_ids_to_argv(self):
        expected = (project_question.Route("nix-build", ("just", "build"), "/srv/p01"),)
        self.assertEqual(project_question.read_only_routes(SNAPSHOT(["nix-build", "ghost"])), expected)
        self.assertEqual(
            project_question.read_only_routes(SNAPSHOT(["nix-build", "ghost"], root="/srv/p01/")), expected)

    def test_a_route_declared_for_another_directory_or_with_a_composed_argv_is_not_offered(self):
        self.assertEqual(
            project_question.read_only_routes(SNAPSHOT(["sub-check", "piped", "nix-build"])),
            (project_question.Route("nix-build", ("just", "build"), "/srv/p01"),))
        self.assertEqual(
            project_question.read_only_routes(
                SNAPSHOT(["nix-build"], cwd_of=lambda id: "/srv/p01/sub")), ())

    def test_an_unresolvable_contract_raises_instead_of_answering_no_routes(self):
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaises(resolve_project.ContractError):
                project_question.reach_of(path)

    def test_a_contract_with_no_read_only_command_gets_the_production_line(self):
        for snapshot in (SNAPSHOT([]), {**SNAPSHOT([]), "production": {"status": "none"}},
                         {**SNAPSHOT([]), "production": {"status": "not_declared"}}):
            self.assertEqual(project_question.read_only_routes(snapshot), ())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            ask = project_question.new_ask(
                "b" * 16, "owner/p01", str(root), "why?", "work", (), Path(directory) / "settings",
                session_id=SESSION_ID)
            seen = {}

            def run(argv, *, timeout, cancel=None, **kwargs):
                seen["argv"] = argv
                seen["settings"] = json.loads(ask.settings.read_text())
                return subprocess.CompletedProcess(argv, 0, stdout=SUCCESS, stderr=None)

            outcome = project_question.run_question(
                ask, None, platform="linux", run=run, environ=ENVIRON)
        self.assertEqual(
            outcome.answer, "Answer: it builds the hosts.\n" + project_question.NO_PRODUCTION_LINE)
        argv = seen["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob,Bash")
        self.assertIn("This project declares no read-only command, so production cannot be read", argv[-1])
        hook_command = seen["settings"]["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertEqual(shlex.split(hook_command)[-2:], ["[]", ""])
        self.assertEqual(seen["settings"]["permissions"]["allow"],
                         ["Read", "Grep", "Glob", *GIT_READ_RULES])

    def test_declared_routes_get_no_production_line(self):
        self.assertNotIn(project_question.NO_PRODUCTION_LINE, project_question.answer_text("Answer: x", ROUTES))
        self.assertIn(
            "Commands you may run, each exactly as written and alone: just build.",
            project_question.prompt("why?", ROUTES))

    def test_a_question_is_checked_and_parsed(self):
        self.assertEqual(project_question.checked_question("  why?  "), "why?")
        for text, reason in (("", project_question.EMPTY), ("   ", project_question.EMPTY),
                             ("x" * 2001, project_question.TOO_LONG)):
            with self.assertRaises(project_question.Refused) as caught:
                project_question.checked_question(text)
            self.assertEqual(str(caught.exception), reason)
        self.assertEqual(
            project_question.parse_request(b'{"project_id":"owner/p01","question":"why?"}'),
            ("owner/p01", "why?", None))
        for body in (b'{"project_id":"owner/p01"}', b'{"project_id":"","question":"q"}',
                     b'{"project_id":"p","question":1}',
                     b'{"project_id":"p","project_id":"q","question":"q"}', b"[1]"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                project_question.parse_request(body)

    def test_a_request_may_name_its_thread(self):
        parse = project_question.parse_request
        self.assertEqual(parse(b'{"project_id":"p","question":"q"}'), ("p", "q", None))
        self.assertEqual(parse(b'{"project_id":"p","question":"q","thread_id":"t1"}'),
                         ("p", "q", "t1"))
        for body in (b'{"project_id":"p","question":"q","thread_id":""}',
                     b'{"project_id":"p","question":"q","thread_id":3}',
                     b'{"project_id":"p","question":"q","x":1}'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse(body)

    def test_reach_names_the_routes_and_the_github_repository_of_the_contract(self):
        self.assertEqual(
            project_question.reach_of("/srv/p01", resolve=lambda p: SNAPSHOT(["nix-build"], tracker=GITHUB)),
            project_question.Reach(ROUTES, "owner/p01"))
        for name, snapshot in (
                ("no tracker", SNAPSHOT([])),
                ("another kind", SNAPSHOT([], tracker={**GITHUB, "kind": "none"})),
                ("no owner", SNAPSHOT([], tracker={**GITHUB, "repo_slug": "owner"})),
                ("not a string", SNAPSHOT([], tracker={**GITHUB, "repo_slug": 3})),
                ("not a slug", SNAPSHOT([], tracker={**GITHUB, "repo_slug": "a/b;c"})),
                ("empty", {})):
            with self.subTest(name):
                self.assertIsNone(project_question.repo_slug(snapshot))

    def test_routes_compare_each_cwd_with_the_resolved_root_not_the_given_path(self):
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real"
            real.mkdir()
            link = Path(directory) / "link"
            os.symlink(real, link)
            seen = []

            def resolve(path):
                seen.append(path)
                return SNAPSHOT(["nix-build"], cwd_of=lambda id: str(real), root=str(real))

            reach = project_question.reach_of(str(link), resolve=resolve)
        self.assertEqual(seen, [str(link)])
        self.assertEqual(
            reach.routes, (project_question.Route("nix-build", ("just", "build"), str(real)),))
        self.assertIsNone(reach.repo)


if __name__ == "__main__":
    unittest.main()


ASKED = "project_question.asked"
ANSWERED_KIND = "project_question.answered"
QUESTION_ROUTE = "/api/project-question"
JSON = {"Content-Type": "application/json"}
WHY = "owner/p01"


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate(), "the condition did not become true within 5 s"


class AnswerPartsTest(unittest.TestCase):
    def test_each_heading_of_the_prompt_shape_is_its_own_part(self):
        text = ("Answer: It builds the hosts.\nRead: flake.nix, lib/helpers.nix\nRan: just build\n"
                "Could not find out: none\nQuestion for you: None.")
        self.assertEqual(
            project_question.answer_parts(text),
            project_question.AnswerParts("It builds the hosts.", "flake.nix, lib/helpers.nix",
                                         "just build", None, None, None))

    def test_an_answer_of_none_keeps_its_text_while_other_parts_of_none_are_empty(self):
        parts = project_question.answer_parts("Answer: None.\nRead: None.\nQuestion for you: none")
        self.assertEqual(parts.answer, "None.")
        self.assertIsNone(parts.read)
        self.assertIsNone(parts.back)
        self.assertEqual(project_question.answer_parts("None.").answer, "None.")

    def test_a_heading_only_unicode_case_folding_matches_is_not_a_heading(self):
        parts = project_question.answer_parts("An\u017fwer: ok\nRead: flake.nix")
        self.assertEqual(parts.answer, "An\u017fwer: ok")
        self.assertEqual(parts.read, "flake.nix")

    def test_a_part_runs_on_until_the_next_heading(self):
        parts = project_question.answer_parts("Answer: first\nsecond line\nread: none")
        self.assertEqual(parts.answer, "first\nsecond line")
        self.assertIsNone(parts.read)

    def test_the_production_line_is_its_own_part(self):
        text = project_question.answer_text("Answer: from the code only\nRan: none", ())
        parts = project_question.answer_parts(text)
        self.assertEqual(parts.production, project_question.NO_PRODUCTION_LINE)
        self.assertEqual(parts.answer, "from the code only")
        self.assertIsNone(parts.ran)

    def test_a_text_with_no_heading_is_the_answer(self):
        self.assertEqual(project_question.answer_parts("It builds."),
                         project_question.AnswerParts("It builds.", None, None, None, None, None))

    def test_a_question_back_is_kept(self):
        parts = project_question.answer_parts(
            "Answer: I cannot read the bill.\nQuestion for you: May I run the paid billing export?")
        self.assertEqual(parts.back, "May I run the paid billing export?")
        self.assertEqual(parts.answer, "I cannot read the bill.")

    def test_lead_names_every_heading(self):
        for _, label in project_question.HEADINGS:
            with self.subTest(label=label):
                self.assertIn(label + ": <", project_question.LEAD)
        self.assertEqual([key for key, _ in project_question.HEADINGS],
                         ["answer", "read", "ran", "unknown", "back"])


def _row(seq, kind, project, payload):
    return event_log.Event(seq, f"2026-11-17T10:00:{seq:02d}Z", kind, project, payload)


def _asked(seq, project, question_id, question="what?", **extra):
    return _row(seq, event_log.PROJECT_QUESTION_ASKED, project,
                {"question_id": question_id, "question": question, **extra})


def _answered(seq, project, question_id, **payload):
    return _row(seq, event_log.PROJECT_QUESTION_ANSWERED, project,
                {"question_id": question_id, **payload})


class QuestionFoldTest(unittest.TestCase):
    P1 = "owner/p01"

    def rows(self):
        return [
            _asked(2, self.P1, "q1"),
            _answered(3, self.P1, "q1", outcome="answered", answer="Answer: ok"),
            _asked(4, self.P1, "q2"),
            _answered(5, self.P1, "q2", outcome="timed_out",
                      reason="the session did not answer within 300 s"),
            _asked(6, self.P1, "q3"),
            _answered(7, self.P1, "q3", outcome="failed", reason="claude-account is not installed"),
            _asked(8, self.P1, "q4"),
        ]

    def test_each_state_is_read_from_the_rows(self):
        rows = self.rows()
        result = project_question.asked_questions(rows)
        q1, q2, q3, q4 = result[self.P1]
        self.assertEqual([(q.question_id, q.state) for q in result[self.P1]],
                         [("q1", "answered"), ("q2", "timed_out"), ("q3", "failed"),
                          ("q4", "working")])
        self.assertEqual(q1.answer, "Answer: ok")
        self.assertEqual(q1.answered_at, rows[1].at)
        self.assertEqual(q2.reason, "the session did not answer within 300 s")
        self.assertIsNone(q4.answered_at)

    def test_strays_and_repeats_are_ignored(self):
        clean = [_asked(2, self.P1, "q1"),
                 _answered(4, self.P1, "q1", outcome="answered", answer="Answer: ok")]
        noisy = [clean[0],
                 _answered(3, self.P1, "nope", outcome="answered", answer="x"),
                 clean[1],
                 _answered(5, self.P1, "q1", outcome="failed", reason="late"),
                 _answered(6, "owner/p02", "q1", outcome="answered", answer="x"),
                 _asked(7, None, "q9"),
                 _asked(8, self.P1, "q8", question=7),
                 _asked(9, self.P1, "q1", question="again")]
        self.assertEqual(project_question.asked_questions(noisy),
                         project_question.asked_questions(clean))
        self.assertEqual(project_question.asked_questions(noisy)[self.P1][0].state, "answered")

    def test_an_unreadable_or_unknown_outcome_is_failed(self):
        rows = [_asked(2, self.P1, "q1"), _answered(3, self.P1, "q1", outcome="answered"),
                _asked(4, self.P1, "q2"), _answered(5, self.P1, "q2", outcome="lost", reason=3)]
        q1, q2 = project_question.asked_questions(rows)[self.P1]
        self.assertEqual((q1.state, q1.reason), ("failed", project_question.UNREADABLE_TEXT))
        self.assertEqual((q2.state, q2.reason), ("failed", None))

    def test_folding_in_two_batches_equals_folding_once(self):
        rows = self.rows()
        rows.append(_asked(9, self.P1, "q5", thread_id="q1"))
        first = project_question.asked_questions(rows[:4])
        before = dict(first)
        self.assertEqual(project_question.asked_questions(rows[4:], first),
                         project_question.asked_questions(rows))
        self.assertEqual(first, before)


def _ids(found):
    return [[q.question_id for q in thread] for thread in found]


class ThreadFoldTest(unittest.TestCase):
    P1 = "owner/p01"

    def fold(self, rows):
        return project_question.asked_questions(rows)[self.P1]

    def test_a_follow_up_joins_the_thread_it_names(self):
        rows = [_asked(2, self.P1, "q1"),
                _answered(3, self.P1, "q1", outcome="answered", answer="Answer: a"),
                _asked(4, self.P1, "q2", thread_id="q1"),
                _answered(5, self.P1, "q2", outcome="answered", answer="Answer: b"),
                _asked(6, self.P1, "q3")]
        folded = self.fold(rows)
        self.assertEqual(_ids(project_question.threads(folded)), [["q3"], ["q1", "q2"]])
        self.assertEqual([q.thread_id for q in folded], ["q1", "q1", "q3"])

    def test_a_follow_up_naming_a_follow_up_joins_that_thread(self):
        rows = [_asked(2, self.P1, "q1"), _asked(3, self.P1, "q2", thread_id="q1"),
                _asked(4, self.P1, "q3", thread_id="q2")]
        self.assertEqual(_ids(project_question.threads(self.fold(rows))), [["q1", "q2", "q3"]])

    def test_a_thread_id_that_names_nothing_here_starts_its_own_thread(self):
        rows = [_asked(2, "owner/p02", "q1"),
                _asked(3, self.P1, "a", thread_id="gone"),
                _asked(4, self.P1, "b", thread_id=7),
                _asked(5, self.P1, "c", thread_id=""),
                _asked(6, self.P1, "d", thread_id="q1")]
        folded = self.fold(rows)
        self.assertEqual([(q.question_id, q.thread_id) for q in folded],
                         [("a", "a"), ("b", "b"), ("c", "c"), ("d", "d")])
        self.assertEqual(_ids(project_question.threads(folded)), [["d"], ["c"], ["b"], ["a"]])

    def test_threads_are_newest_first_by_their_last_question(self):
        rows = [_asked(2, self.P1, "q1"), _asked(4, self.P1, "q2"),
                _asked(6, self.P1, "q3", thread_id="q1")]
        self.assertEqual(_ids(project_question.threads(self.fold(rows))), [["q1", "q3"], ["q2"]])


class FollowUpTest(unittest.TestCase):
    P1 = "owner/p01"

    def answered(self, answer="Answer: a", **extra):
        rows = [_asked(2, self.P1, "q1"),
                _answered(3, self.P1, "q1", outcome="answered", answer=answer), *extra.get("rows", [])]
        return project_question.asked_questions(rows)[self.P1]

    def test_follow_up_returns_the_threads_turns_in_order(self):
        folded = project_question.asked_questions([
            _asked(2, self.P1, "q1"),
            _answered(3, self.P1, "q1", outcome="answered", answer="Answer: a"),
            _asked(4, self.P1, "q2", thread_id="q1"),
            _answered(5, self.P1, "q2", outcome="answered", answer="Answer: b")])[self.P1]
        Turn = project_question.Turn
        self.assertEqual(project_question.follow_up(folded, "q1", "and then?"),
                         (Turn("what?", "Answer: a"), Turn("what?", "Answer: b")))

    def test_follow_up_refuses_an_unknown_an_unanswered_or_a_too_long_thread(self):
        def thread(*rows):
            return project_question.asked_questions(list(rows))[self.P1]

        answered = [_asked(2, self.P1, "q1"),
                    _answered(3, self.P1, "q1", outcome="answered", answer="Answer: a")]
        cases = (
            ("nope", thread(*answered), project_question.THREAD_UNKNOWN),
            ("q2", thread(*answered, _asked(4, self.P1, "q2", thread_id="q1")),
             project_question.THREAD_UNKNOWN),
            ("q1", thread(_asked(2, self.P1, "q1")), project_question.THREAD_UNANSWERED),
            ("q1", thread(_asked(2, self.P1, "q1"), _answered(3, self.P1, "q1", outcome="failed")),
             project_question.THREAD_UNANSWERED),
            ("q1", thread(_asked(2, self.P1, "q1"), _answered(3, self.P1, "q1", outcome="timed_out")),
             project_question.THREAD_UNANSWERED),
            ("q1", thread(*answered, _asked(4, self.P1, "q2", thread_id="q1")),
             project_question.THREAD_UNANSWERED),
            ("q1", self.answered("Answer: " + "x" * project_question.MAX_THREAD_BYTES),
             project_question.THREAD_TOO_LONG),
        )
        for thread_id, folded, reason in cases:
            with self.subTest(thread_id=thread_id, reason=reason):
                with self.assertRaises(project_question.Refused) as caught:
                    project_question.follow_up(folded, thread_id, "why?")
                self.assertEqual(str(caught.exception), reason)

    def test_the_bound_counts_utf8_bytes(self):
        long = self.answered("\u00e9" * (project_question.MAX_THREAD_BYTES // 2))
        with self.assertRaises(project_question.Refused) as caught:
            project_question.follow_up(long, "q1", "why?")
        self.assertEqual(str(caught.exception), project_question.THREAD_TOO_LONG)
        short = self.answered("x" * 1000)
        self.assertEqual(len(project_question.follow_up(short, "q1", "why?")), 1)


class AnswerRulesTest(unittest.TestCase):
    def test_the_prompt_leads_with_the_direct_answer_in_plain_terms(self):
        text = project_question.prompt(
            "what was done in the last 7 days and what is in production?", ROUTES, repo="owner/p01")
        rules = (
            "Lead with the direct answer in two or three sentences, in the owner's plain business "
            "terms, then at most a short list of five lines.",
            "When the question asks what is live or in production, say what is live first.",
            "Use no decision-record jargon: no ADR numbers, decision ids or internal terms unless "
            "the owner asks for them.",
            "Answer from the project's history, its pull requests and releases and its declared "
            "production read, not from its decision records alone.",
            "If a command you run fails, say plainly in the answer which command failed and what "
            "it printed.",
        )
        for rule in rules:
            self.assertIn(rule, project_question.LEAD)
            self.assertLess(text.index(rule), text.index("Answer: <"))
        self.assertEqual(project_question.ANSWER_RULES, " ".join(rules) + " ")

    def test_the_prompt_names_reads_the_hook_admits(self):
        text = project_question.prompt("q", (), repo="owner/p01")
        examples = ("git log --since=7.days.ago --oneline", "git tag -l",
                    "gh pr list --repo owner/p01 --state merged --limit 30",
                    "gh release list --repo owner/p01")
        for example in examples:
            self.assertIn(example, text)
            self.assertEqual(hook.decide(bash(example), (), repo="owner/p01"),
                             ("allow", hook.ALLOWED))
        bare = project_question.prompt("q", ())
        self.assertIn("gh cannot be used: this project's contract names no GitHub repository.", bare)
        self.assertNotIn("gh pr list", bare)
        self.assertIn("This project declares no read-only command, so production cannot be read",
                      text)

    def test_the_launch_passes_the_rules_and_the_repository_to_the_session(self):
        ask = project_question.new_ask(
            "a" * 16, "owner/p01", "/srv/p01", "what is live?", "work", ROUTES, Path("/tmp/s"),
            session_id=SESSION_ID, repo="owner/p01")
        argv = project_question.launch_command(ask, "linux")
        self.assertEqual(argv[-1], project_question.prompt("what is live?", ROUTES, repo="owner/p01"))
        self.assertIn("gh pr list --repo owner/p01", argv[-1])
        self.assertIn(project_question.ANSWER_RULES, argv[-1])


class ThreadPromptTest(unittest.TestCase):
    def test_a_follow_up_prompt_puts_its_thread_before_the_question(self):
        turns = (project_question.Turn("what does the build check?", "Answer: it builds."),)
        mark = project_question.QUESTION_MARK
        self.assertEqual(
            project_question.prompt("and darwin?", ROUTES, turns),
            project_question.prompt("and darwin?", ROUTES).replace(
                mark, project_question.THREAD_LEAD
                + "Earlier question: what does the build check?\nEarlier answer: Answer: it builds.\n\n"
                + mark))
        self.assertEqual(project_question.prompt("x", ROUTES, ()), project_question.prompt("x", ROUTES))

    def test_a_threads_launch_differs_only_in_its_prompt(self):
        turns = (project_question.Turn("what does the build check?", "Answer: it builds."),)

        def make(**extra):
            return project_question.new_ask(
                "a" * 16, "owner/p01", "/srv/p01", "and darwin?", "work", ROUTES, Path("/tmp/s"),
                session_id=SESSION_ID, **extra)

        with_, without = make(thread=turns), make()
        a = project_question.launch_command(with_, "linux")
        b = project_question.launch_command(without, "linux")
        self.assertEqual(a[:-1], b[:-1])
        self.assertNotEqual(a[-1], b[-1])
        self.assertEqual(with_.thread, turns)
        self.assertEqual(without.thread, ())


def _registered(seq, project):
    return _row(seq, "project.registered", project, {"root": "/srv/" + project.split("/")[1]})


def _project_entries(shown):
    return [project for entry in shown["entries"]
            for project in (entry["projects"] if entry["type"] == "quiet_group" else [entry])]


QUESTION_KEYS = {"id", "question", "asked_at", "state", "state_text", "answered_at", "answer",
                 "read_text", "ran_text", "unknown_text", "back_text", "production_text"}


class QuestionViewTest(unittest.TestCase):
    P1 = "owner/p01"

    def test_a_projects_view_carries_each_question_state_and_adds_nothing_to_the_count(self):
        events = [
            _registered(1, self.P1),
            _asked(2, self.P1, "q1", "what does the build check?"),
            _answered(3, self.P1, "q1", outcome="answered", answer=(
                "Answer: It builds the hosts.\nRead: flake.nix\nRan: just build\n"
                "Could not find out: which host is deployed\nQuestion for you: none")),
            _asked(4, self.P1, "q2"),
            _answered(5, self.P1, "q2", outcome="timed_out",
                      reason="the session did not answer within 300 s"),
            _asked(6, self.P1, "q3"),
            _answered(7, self.P1, "q3", outcome="failed", reason="claude-account is not installed"),
            _asked(8, self.P1, "q4", "where is the retry decided?"),
        ]
        states = view.project_states(events).values()
        shown = view.derive_view(states, project_questions=project_question.asked_questions(events))
        bare = view.derive_view(view.project_states(events).values())
        self.assertEqual(shown["statement"], bare["statement"])
        self.assertEqual(shown["inbox"], bare["inbox"])
        self.assertEqual(shown["statement"]["inbox_items"], 0)
        entry = shown["entries"][0]
        threads = entry["questions"]["threads"]
        self.assertEqual(entry["questions"]["count"], 4)
        self.assertEqual([t["id"] for t in threads], ["q4", "q3", "q2", "q1"])
        self.assertEqual([len(t["questions"]) for t in threads], [1, 1, 1, 1])
        self.assertEqual([t["follow_up"] for t in threads], [False, False, False, True])
        questions = [q for t in threads for q in t["questions"]]
        self.assertEqual([q["id"] for q in questions], ["q4", "q3", "q2", "q1"])
        self.assertEqual([q["state"] for q in questions],
                         ["working", "failed", "timed_out", "answered"])
        q4, q3, q2, q1 = questions
        self.assertEqual(q1["answer"], "It builds the hosts.")
        self.assertEqual(q1["read_text"], "Read: flake.nix")
        self.assertEqual(q1["ran_text"], "Ran: just build")
        self.assertEqual(q1["unknown_text"], "Could not find out: which host is deployed")
        self.assertIsNone(q1["back_text"])
        self.assertIsNone(q1["production_text"])
        self.assertEqual(q1["state_text"], "Answered")
        self.assertEqual(q1["answered_at"], events[2].at)
        self.assertEqual(q2["state_text"], "Timed out: the session did not answer within 300 s")
        self.assertIsNone(q2["answer"])
        self.assertEqual(q3["state_text"], "Could not answer: claude-account is not installed")
        self.assertEqual(q4["state_text"], "Working on it")
        self.assertIsNone(q4["answered_at"])
        self.assertEqual(q4["question"], "where is the retry decided?")
        self.assertEqual(q4["asked_at"], events[7].at)
        for question in questions:
            self.assertEqual(set(question), QUESTION_KEYS)
        self.assertIs(entry["quiet"], True)
        self.assertIsNone(bare["entries"][0]["questions"])

    def test_a_question_back_and_the_production_line_read_as_their_own_lines(self):
        answer = project_question.answer_text(
            "Answer: I cannot read the bill.\nQuestion for you: May I run the paid billing export?", ())
        events = [_registered(1, self.P1), _asked(2, self.P1, "q1"),
                  _answered(3, self.P1, "q1", outcome="answered", answer=answer)]
        shown = view.derive_view(view.project_states(events).values(),
                                 project_questions=project_question.asked_questions(events))
        question = shown["entries"][0]["questions"]["threads"][0]["questions"][0]
        self.assertEqual(question["back_text"],
                         "Question for you: May I run the paid billing export?")
        self.assertEqual(question["production_text"], project_question.NO_PRODUCTION_LINE)
        self.assertEqual(question["answer"], "I cannot read the bill.")

    def test_a_project_in_a_quiet_group_carries_its_questions(self):
        events = [_registered(n, f"owner/p0{n}") for n in range(1, 6)]
        events.append(_asked(6, "owner/p03", "q1"))
        shown = view.derive_view(view.project_states(events).values(),
                                 project_questions=project_question.asked_questions(events))
        self.assertEqual([e["type"] for e in shown["entries"]], ["quiet_group"])
        by_id = {p["project_id"]: p["questions"] for p in _project_entries(shown)}
        self.assertEqual([q["state"] for t in by_id.pop("owner/p03")["threads"]
                          for q in t["questions"]], ["working"])
        self.assertEqual(list(by_id.values()), [None] * 4)


class QuestionActivityTest(unittest.TestCase):
    OLD, NEW = "owner/p01", "owner/p02"

    def test_a_question_or_follow_up_neither_reorders_projects_nor_resets_their_untouched_age(self):
        events = [
            _registered(1, self.OLD),
            _asked(2, self.OLD, "q1"),
            _answered(3, self.OLD, "q1", outcome="answered", answer="Answer: a"),
            _registered(4, self.NEW),
        ]
        before = view.project_states(events)
        follow_up = [
            _asked(5, self.OLD, "q2", thread_id="q1"),
            _answered(6, self.OLD, "q2", outcome="answered", answer="Answer: b"),
        ]
        after = view.project_states(follow_up, before)
        self.assertEqual(after, view.project_states(events + follow_up))
        self.assertEqual(after, before)
        order = [e["project_id"] for e in _project_entries(view.derive_view(after.values()))]
        self.assertEqual(order, [self.NEW, self.OLD])


class QuestionThreadViewTest(unittest.TestCase):
    P1 = "owner/p01"

    def test_a_projects_threads_are_a_closed_fold_newest_first_that_adds_nothing_to_the_count(self):
        events = [
            _registered(1, self.P1),
            _asked(2, self.P1, "q1"),
            _answered(3, self.P1, "q1", outcome="answered", answer="Answer: a"),
            _asked(4, self.P1, "q2"),
            _answered(5, self.P1, "q2", outcome="answered", answer="Answer: b"),
            _asked(6, self.P1, "q3", thread_id="q1"),
            _answered(7, self.P1, "q3", outcome="answered", answer="Answer: c"),
            _asked(8, self.P1, "q4", thread_id="q2"),
        ]
        shown = view.derive_view(view.project_states(events).values(),
                                 project_questions=project_question.asked_questions(events))
        bare = view.derive_view(view.project_states(events).values())
        self.assertEqual(shown["statement"], bare["statement"])
        self.assertEqual(shown["inbox"], bare["inbox"])
        self.assertEqual(shown["statement"]["inbox_items"], 0)
        self.assertEqual([e["project_id"] for e in shown["entries"]],
                         [e["project_id"] for e in bare["entries"]])
        entry = shown["entries"][0]
        self.assertIs(entry["quiet"], True)
        questions = entry["questions"]
        self.assertEqual((questions["label"], questions["count"]), ("Questions", 2))
        threads = questions["threads"]
        self.assertEqual([t["id"] for t in threads], ["q2", "q1"])
        self.assertEqual([[x["id"] for x in t["questions"]] for t in threads],
                         [["q2", "q4"], ["q1", "q3"]])
        self.assertEqual([t["follow_up"] for t in threads], [False, True])
        for thread in threads:
            self.assertEqual(set(thread), {"id", "questions", "follow_up"})
            for question in thread["questions"]:
                self.assertEqual(set(question), QUESTION_KEYS)
        self.assertIsNone(bare["entries"][0]["questions"])


class QuestionCase(Case):
    """A service whose question session is a stub: the asker records each call and returns an outcome."""

    def setUp(self):
        super().setUp()
        self.outcome = project_question.Outcome("answered", answer="Answer: it builds.")
        self.raises = None
        self.asked = []
        self.queued = []
        self.calls = []
        self.profiles = self.store.parent.parent / "accounts" / "profiles"
        patcher = mock.patch.object(
            project_question, "new_session_id", create=True, return_value=SESSION_ID)
        patcher.start()
        self.addCleanup(patcher.stop)

    def asker(self, ask, cancel):
        self.asked.append((ask, cancel))
        if self.raises is not None:
            raise self.raises
        return self.outcome

    def start(self, **kwargs):
        support.write_registry(self.registry, support.entries(2))
        support.sign_in(self.store, "work")
        defaults = {
            "profile_dirs": [support.profile_dir(self.store, "work")],
            "session_poll_seconds": 3600, "project_asker": self.asker,
            "project_reach": lambda root: REACH,
            "project_question_dispatch": lambda job: job()}
        for name, value in defaults.items():
            kwargs.setdefault(name, value)
        return super().start(**kwargs)

    def start_removal(self, **kwargs):
        support.profile_dir(self.store, "work")
        kwargs.setdefault("profile_dirs", Listing(self.profiles))
        kwargs.setdefault("signin_reader", lambda one: signin.Status("signed_in", None))
        kwargs.setdefault("signer_out", lambda one: self.calls.append(("signout", one.profile)))
        kwargs.setdefault("account_remover", self.remover)
        kwargs.setdefault("choice_file", self.profiles.parent / "chosen-profile")
        return self.start(**kwargs)

    def remover(self, name):
        self.calls.append(("rm", name))
        shutil.rmtree(self.profiles / name)

    def question_rows(self):
        return [(row[2], row[3], json.loads(row[4])) for row in support.log_rows(self.store)
                if row[2].startswith("project_question.")]


class QuestionServiceTest(QuestionCase):
    def test_asking_appends_a_question_row_then_exactly_one_answer_row_per_outcome(self):
        svc = self.start()
        cases = (
            (project_question.Outcome("answered", answer="Answer: x"), None,
             {"outcome": "answered", "answer": "Answer: x"}),
            (project_question.Outcome("failed", reason="boom"), None,
             {"outcome": "failed", "reason": "boom"}),
            (project_question.Outcome("timed_out", reason="the session did not answer within 300 s"),
             None, {"outcome": "timed_out",
                    "reason": "the session did not answer within 300 s"}),
            (None, RuntimeError("down"), {"outcome": "failed", "reason": "RuntimeError: down"}))
        for outcome, raises, tail in cases:
            with self.subTest(tail=tail):
                self.outcome, self.raises = outcome, raises
                before = len(self.question_rows())
                qid = svc.ask_project_question(WHY, " why? ")
                self.assertEqual(self.question_rows()[before:], [
                    (ASKED, WHY, {"question_id": qid, "question": "why?", "profile": "work",
                                    "session_id": SESSION_ID}),
                    (ANSWERED_KIND, WHY, {"question_id": qid, **tail})])
                self.assertEqual(svc._project_questions_open, 0)

    def test_the_session_gets_the_chosen_profile_the_root_and_the_routes(self):
        svc = self.start()
        svc.ask_project_question(WHY, "why?")
        (ask, cancel), = self.asked
        self.assertEqual((ask.profile, ask.root, ask.routes, ask.question),
                         ("work", "/srv/p01", ROUTES, "why?"))
        self.assertEqual(ask.repo, "owner/p01")
        self.assertEqual(ask.unset, ())
        self.assertEqual(ask.settings.parent, self.store.with_name("project-question-settings"))
        self.assertIs(cancel, svc._stop)
        self.assertEqual(ask.session_id, SESSION_ID)
        self.assertEqual(self.question_rows()[0][2]["session_id"], ask.session_id)

    def test_the_sessions_ask_carries_the_credentials_the_reach_unsets(self):
        reach = project_question.Reach(ROUTES, "owner/p01", ("GH_TOKEN",))
        svc = self.start(project_reach=lambda root: reach)
        svc.ask_project_question(WHY, "why?")
        (ask, _cancel), = self.asked
        self.assertEqual(ask.unset, ("GH_TOKEN",))

    def test_a_questions_transcript_is_spent_under_its_project_and_the_questions_aspect(self):
        now = 1_800_000_000.0
        today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        sessions = self.store.parent.parent / "sessions"
        svc = self.start(session_dirs=[sessions], clock=lambda: now)
        svc.ask_project_question(WHY, "why?")
        path = sessions.parent / "projects" / "-srv-p01" / f"{SESSION_ID}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {"type": "assistant", "sessionId": SESSION_ID, "cwd": "/srv/p01",
                "timestamp": f"{today}T10:00:00.000Z",
                "message": {"id": "msg_q1", "model": "claude-sonnet-4-6",
                            "usage": {"input_tokens": 40}}}
        path.write_text(json.dumps(line) + "\n")
        os.utime(path, (now, now))
        svc.poll_spend()
        day = json.loads(svc.view_bytes)["spend"]["days"][-1]
        self.assertEqual({k: t["input"] for k, t in day["aspect"].items()}, {"questions": 40})
        self.assertEqual(day["project"][WHY]["input"], 40)
        self.assertEqual(set(day["account"]), {"work"})

    def test_nothing_reaches_the_tracker(self):
        def refuse(name):
            def double(*args, **kwargs):
                self.calls.append(name)
                raise AssertionError(name)
            return double
        svc = self.start(tracker=refuse("tracker"), tick=refuse("tick"),
                         owner_path=refuse("owner_path"), criterion_path=refuse("criterion_path"),
                         slug_of=lambda root: None)
        for outcome, raises in ((project_question.Outcome("answered", answer="Answer: x"), None),
                                (project_question.Outcome("failed", reason="boom"), None),
                                (project_question.Outcome("timed_out", reason="late"), None),
                                (None, RuntimeError("down"))):
            self.outcome, self.raises = outcome, raises
            svc.ask_project_question(WHY, "why?")
        self.assertEqual(self.calls, [])

    def test_refusals_append_nothing(self):
        cases = (
            ({}, "owner/p99", "why?", "this project is not registered"),
            ({}, WHY, "   ", "write the question first"),
            ({}, WHY, "x" * 2001, "a question is at most 2000 characters"),
            ({"project_asker": None}, WHY, "why?", "questions are not available on this host yet"),
            ({"profile_dirs": []}, WHY, "why?", "no account can take a question now"))
        for kwargs, project, text, reason in cases:
            with self.subTest(reason=reason):
                svc = self.start(**kwargs)
                before = self.question_rows()
                with self.assertRaises(project_question.Refused) as caught:
                    svc.ask_project_question(project, text)
                self.assertEqual(str(caught.exception), reason)
                self.assertEqual(self.question_rows(), before)
                self.assertEqual(self.asked, [])
                self.assertEqual(svc._project_questions_open, 0)
                svc.close()

    def test_a_dispatch_that_fails_still_answers_the_question_once(self):
        def dispatch(job):
            raise RuntimeError("no thread")
        svc = self.start(project_question_dispatch=dispatch)
        with self.assertRaises(RuntimeError):
            svc.ask_project_question(WHY, "why?")
        (asked, project, payload), (answered, _, tail) = self.question_rows()
        self.assertEqual((asked, project, answered), (ASKED, WHY, ANSWERED_KIND))
        self.assertEqual(tail, {"question_id": payload["question_id"], "outcome": "failed",
                                "reason": "RuntimeError: no thread"})
        self.assertEqual(self.asked, [])
        self.assertEqual(svc._project_questions_open, 0)

    def test_a_default_dispatch_that_cannot_start_a_thread_leaves_close_working(self):
        svc = self.start(project_question_dispatch=None)
        with mock.patch.object(threading.Thread, "start",
                               side_effect=RuntimeError("can't start new thread")):
            with self.assertRaises(RuntimeError):
                svc.ask_project_question(WHY, "why?")
        self.assertEqual(svc._project_question_workers, [])
        self.assertEqual(svc._project_questions_open, 0)
        svc.close()
        self.assertEqual([row[0] for row in self.question_rows()][-1:], [ANSWERED_KIND])

    def test_an_unresolvable_contract_is_a_failed_answer_and_starts_no_session(self):
        error = resolve_project.ContractError(
            "resolver_failure", "resolver.internal",
            [{"pointer": "", "message": "the resolver failed unexpectedly"}])

        def routes(root):
            raise error
        svc = self.start(project_reach=routes)
        qid = svc.ask_project_question(WHY, "why?")
        self.assertEqual(self.asked, [])
        self.assertEqual(self.question_rows()[-1], (ANSWERED_KIND, WHY, {
            "question_id": qid, "outcome": "failed",
            "reason": project_question.CONTRACT_UNREADABLE.format(
                detail="ContractError: " + str(error))}))

    def test_the_question_kinds_are_not_kept(self):
        self.assertEqual(event_log.PROJECT_QUESTION_ASKED, ASKED)
        self.assertEqual(event_log.PROJECT_QUESTION_ANSWERED, ANSWERED_KIND)
        self.assertNotIn(ASKED, event_log.KEPT_KINDS)
        self.assertNotIn(ANSWERED_KIND, event_log.KEPT_KINDS)
        self.assertEqual(event_log.SCHEMA_VERSION, 10)

    def shown(self, svc):
        return {p["project_id"]: p for p in _project_entries(json.loads(svc.view_bytes))}[WHY]

    def test_the_published_view_shows_the_question_working_then_answered(self):
        held = []
        svc = self.start(project_question_dispatch=held.append)
        try:
            before = json.loads(svc.view_bytes)["statement"]
            svc.ask_project_question(WHY, "what does the build check?")
            (question,) = [q for t in self.shown(svc)["questions"]["threads"] for q in t["questions"]]
            self.assertEqual((question["state"], question["question"]),
                             ("working", "what does the build check?"))
            self.assertEqual(json.loads(svc.view_bytes)["statement"], before)
            held.pop()()
            (question,) = [q for t in self.shown(svc)["questions"]["threads"] for q in t["questions"]]
            self.assertEqual((question["state"], question["answer"]), ("answered", "it builds."))
            self.assertEqual(json.loads(svc.view_bytes)["statement"], before)
        finally:
            while held:
                held.pop()()

    def test_questions_survive_a_restart(self):
        svc = self.start()
        svc.ask_project_question(WHY, "what does the build check?")
        svc.close()
        again = self.start()
        (question,) = [q for t in self.shown(again)["questions"]["threads"] for q in t["questions"]]
        self.assertEqual(question["state"], "answered")


def question_threads():
    return [t for t in threading.enumerate() if t.name == service.PROJECT_QUESTION_THREAD]


class QuestionLifecycleTest(QuestionCase):
    def test_an_orderly_stop_records_the_running_questions_answer_once(self):
        entered = threading.Event()

        def asker(ask, cancel):
            entered.set()
            cancel.wait(10)
            time.sleep(0.2)
            return project_question.Outcome("failed", reason=project_question.STOPPED_TEXT)
        svc = self.start(project_question_dispatch=None, project_asker=asker)
        record = svc._record_project_answer

        def record_then_linger(*args):
            record(*args)
            time.sleep(0.3)  # the worker outlives its answer: only a join waits for it
        svc._record_project_answer = record_then_linger
        qid = svc.ask_project_question(WHY, "why?")
        self.assertTrue(entered.wait(10))
        svc.close()
        self.assertEqual(self.question_rows(), [
            (ASKED, WHY, {"question_id": qid, "question": "why?", "profile": "work",
                                    "session_id": SESSION_ID}),
            (ANSWERED_KIND, WHY, {"question_id": qid, "outcome": "failed",
                                  "reason": project_question.STOPPED_TEXT})])
        self.assertEqual(question_threads(), [])

    def test_a_question_accepted_before_a_stop_and_not_yet_dispatched_is_answered_before_the_log_closes(self):
        svc = self.start(project_question_dispatch=self.queued.append)
        qid = svc.ask_project_question(WHY, "why?")
        closer = threading.Thread(target=svc.close)
        closer.start()
        try:
            wait_until(svc._stop.is_set)
            closer.join(2)  # past the server's 0.5 s shutdown poll: only the drain still holds it
            self.assertTrue(closer.is_alive())
        finally:
            self.queued[0]()
        closer.join(10)
        self.assertFalse(closer.is_alive())
        self.assertEqual(self.asked, [])
        self.assertEqual(self.question_rows(), [
            (ASKED, WHY, {"question_id": qid, "question": "why?", "profile": "work",
                                    "session_id": SESSION_ID}),
            (ANSWERED_KIND, WHY, {"question_id": qid, "outcome": "failed",
                                  "reason": project_question.STOPPED_TEXT})])

    def test_a_question_asked_while_the_console_stops_is_refused_and_appends_nothing(self):
        svc = self.start(project_question_dispatch=self.queued.append)
        svc.ask_project_question(WHY, "why?")
        closer = threading.Thread(target=svc.close)
        closer.start()
        try:
            wait_until(svc._stop.is_set)
            with self.assertRaises(project_question.Refused) as caught:
                svc.ask_project_question(WHY, "again?")
            self.assertEqual(str(caught.exception), "the console is stopping")
            self.assertEqual([kind for kind, _, _ in self.question_rows()], [ASKED])
        finally:
            for job in list(self.queued):
                job()
        closer.join(10)
        self.assertFalse(closer.is_alive())
        self.assertEqual(len(self.queued), 1)

    def test_concurrent_questions_are_each_answered_once_on_stop(self):
        entered = []
        barrier = threading.Barrier(2, timeout=10)

        def asker(ask, cancel):
            entered.append(ask.question_id)
            barrier.wait()
            cancel.wait(10)
            return project_question.Outcome("failed", reason=project_question.STOPPED_TEXT)
        svc = self.start(project_question_dispatch=None, project_asker=asker)
        ids = []
        askers = [threading.Thread(target=lambda text=text: ids.append(
            svc.ask_project_question(WHY, text))) for text in ("one?", "two?")]
        for each in askers:
            each.start()
        for each in askers:
            each.join(10)
        wait_until(lambda: len(entered) == 2 and barrier.n_waiting == 0)
        svc.close()
        rows = self.question_rows()
        self.assertEqual(len(ids), 2)
        self.assertEqual(sorted(p["question_id"] for k, _, p in rows if k == ASKED), sorted(ids))
        self.assertEqual(sorted(p["question_id"] for k, _, p in rows if k == ANSWERED_KIND),
                         sorted(ids))
        self.assertEqual(len(rows), 4)
        self.assertEqual(question_threads(), [])

    def test_a_removal_waits_for_a_running_question_and_is_refused_while_it_runs(self):
        entered, gate = threading.Event(), threading.Event()

        def asker(ask, cancel):
            entered.set()
            gate.wait(10)
            return project_question.Outcome("answered", answer="Answer: x")
        self.addCleanup(gate.set)
        svc = self.start_removal(
            project_asker=asker,
            project_question_dispatch=lambda job: threading.Thread(target=job).start())
        qid = svc.ask_project_question(WHY, "why?")
        self.assertTrue(entered.wait(10))
        with mock.patch.object(account_remove, "DRAIN_TIMEOUT", 0.2):
            with self.assertRaises(sprints.Refused) as caught:
                svc.remove_account("work", "work")
        self.assertEqual(str(caught.exception), account_remove.busy("work"))
        self.assertEqual(self.calls, [])
        gate.set()
        wait_until(lambda: [k for k, _, _ in self.question_rows()] == [ASKED, ANSWERED_KIND])
        self.assertEqual(self.question_rows()[-1][2],
                         {"question_id": qid, "outcome": "answered", "answer": "Answer: x"})

    def test_a_queued_question_whose_profile_is_removed_fails_without_a_session(self):
        for name, reason in (
                ("marked", "work is being removed"),
                ("gone", "the account work was removed before the session started")):
            with self.subTest(name):
                self.calls.clear()
                self.queued.clear()
                self.asked.clear()
                support.profile_dir(self.store, "work")
                if name == "marked":
                    def signer_out(one):
                        self.calls.append(("signout", one.profile))
                        self.queued[0]()
                    svc = self.start_removal(project_question_dispatch=self.queued.append,
                                             signer_out=signer_out)
                else:
                    svc = self.start_removal(project_question_dispatch=self.queued.append)
                qid = svc.ask_project_question(WHY, "why?")
                svc.remove_account("work", "work")
                if name == "gone":
                    self.assertFalse((self.profiles / "work").exists())
                    self.queued[0]()
                self.assertEqual(self.asked, [])
                answered = [p for k, _, p in self.question_rows()
                            if k == ANSWERED_KIND and p["question_id"] == qid]
                self.assertEqual(answered, [{"question_id": qid, "outcome": "failed",
                                             "reason": reason}])
                svc.close()


T0 = 1_767_225_600.0


def _clocks(now):
    """The service clock and the log clock, both reading the one-element list `now`."""
    return {"clock": lambda: now[0],
            "log_clock": lambda: datetime.fromtimestamp(now[0], timezone.utc).isoformat(
                timespec="microseconds")}


def _thread_ids(svc):
    return [[q.question_id for q in thread]
            for thread in project_question.threads(svc._project_questions[WHY])]


class QuestionThreadServiceTest(QuestionCase):
    def test_a_follow_up_is_recorded_under_its_thread_and_launched_with_its_context_and_the_same_settings(self):
        svc = self.start()
        first = svc.ask_project_question(WHY, "what does the build check?")
        follow = svc.ask_project_question(WHY, " and which host is deployed? ", thread_id=first)
        self.assertEqual(self.question_rows()[-2:], [
            (ASKED, WHY, {"question_id": follow, "question": "and which host is deployed?",
                          "profile": "work", "session_id": SESSION_ID, "thread_id": first}),
            (ANSWERED_KIND, WHY, {"question_id": follow, "outcome": "answered",
                                  "answer": "Answer: it builds."})])
        self.assertNotIn("thread_id", self.question_rows()[0][2])
        (first_ask, _), (follow_ask, cancel) = self.asked
        self.assertEqual(follow_ask.thread,
                         (project_question.Turn("what does the build check?", "Answer: it builds."),))
        self.assertEqual(first_ask.thread, ())
        self.assertIs(cancel, svc._stop)
        self.assertEqual((follow_ask.profile, follow_ask.root, follow_ask.routes),
                         ("work", "/srv/p01", ROUTES))
        self.assertEqual(project_question.settings_document(follow_ask.routes),
                         project_question.settings_document(first_ask.routes))

        def strip(argv):
            argv = list(argv[:-1])
            for flag in ("--session-id", "--settings"):
                argv[argv.index(flag) + 1] = None
            return argv

        follow_argv = project_question.launch_command(follow_ask, "linux")
        self.assertEqual(strip(follow_argv),
                         strip(project_question.launch_command(first_ask, "linux")))
        for flag, value in (("--model", "sonnet"), ("--permission-mode", "dontAsk"),
                            ("--setting-sources", "")):
            self.assertEqual(follow_argv[follow_argv.index(flag) + 1], value)
        self.assertEqual(follow_argv[-1], project_question.prompt(
            "and which host is deployed?", ROUTES, follow_ask.thread, repo="owner/p01"))
        self.assertIn("Earlier question: what does the build check?\n"
                      "Earlier answer: Answer: it builds.\n", follow_argv[-1])
        self.assertEqual(_thread_ids(svc), [[first, follow]])

    def test_a_follow_up_to_an_unknown_unanswered_or_too_long_thread_is_refused_and_appends_nothing(self):
        held = []
        svc = self.start(project_question_dispatch=held.append)
        try:
            working = svc.ask_project_question(WHY, "still going?")  # its job stays held
            self.outcome = project_question.Outcome("failed", reason="boom")
            failed = svc.ask_project_question(WHY, "will fail?")
            held.pop()()
            self.outcome = project_question.Outcome(
                "answered", answer="Answer: " + "x" * project_question.MAX_THREAD_BYTES)
            long = svc.ask_project_question(WHY, "will be long?")
            held.pop()()
            cases = (("nope", project_question.THREAD_UNKNOWN),
                     (working, project_question.THREAD_UNANSWERED),
                     (failed, project_question.THREAD_UNANSWERED),
                     (long, project_question.THREAD_TOO_LONG))
            for thread_id, reason in cases:
                with self.subTest(thread_id=thread_id, reason=reason):
                    rows, asked, open_ = (self.question_rows(), len(self.asked),
                                          svc._project_questions_open)
                    with self.assertRaises(project_question.Refused) as caught:
                        svc.ask_project_question(WHY, "more?", thread_id=thread_id)
                    self.assertEqual(str(caught.exception), reason)
                    self.assertEqual((self.question_rows(), len(self.asked),
                                      svc._project_questions_open), (rows, asked, open_))
            with self.subTest(order="unregistered"):
                rows = self.question_rows()
                with self.assertRaises(project_question.Refused) as caught:
                    svc.ask_project_question("owner/p99", "more?", thread_id=working)
                self.assertEqual(str(caught.exception), project_question.UNREGISTERED)
                self.assertEqual(self.question_rows(), rows)
        finally:
            while held:
                held.pop()()

    def test_a_follow_up_survives_a_restart_in_its_thread(self):
        svc = self.start()
        first = svc.ask_project_question(WHY, "what does the build check?")
        follow = svc.ask_project_question(WHY, "and darwin?", thread_id=first)
        svc.close()
        again = self.start()
        self.assertEqual(_thread_ids(again), [[first, follow]])

    def test_after_retention_a_thread_is_admitted_and_grouped_as_a_restart_would(self):
        now = [T0]
        svc = self.start(**_clocks(now))
        first = svc.ask_project_question(WHY, "what does the build check?")
        now[0] = T0 + 45 * 86400
        follow = svc.ask_project_question(WHY, "and darwin?", thread_id=first)
        now[0] = T0 + 91 * 86400
        removed = svc.retain()
        self.assertGreaterEqual(removed, 2)
        self.assertEqual(_thread_ids(svc), [[follow]])
        rows, asked, open_ = self.question_rows(), len(self.asked), svc._project_questions_open
        with self.assertRaises(project_question.Refused) as caught:
            svc.ask_project_question(WHY, "more?", thread_id=first)
        self.assertEqual(str(caught.exception), project_question.THREAD_UNKNOWN)
        self.assertEqual((self.question_rows(), len(self.asked), svc._project_questions_open),
                         (rows, asked, open_))
        more = svc.ask_project_question(WHY, "more?", thread_id=follow)
        svc.close()
        again = self.start(**_clocks(now))
        self.assertEqual(_thread_ids(again), [[follow, more]])
        with self.assertRaises(project_question.Refused) as caught:
            again.ask_project_question(WHY, "more?", thread_id=first)
        self.assertEqual(str(caught.exception), project_question.THREAD_UNKNOWN)


class QuestionRouteTest(QuestionCase):
    def post(self, svc, body, headers):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        return support.post_page(svc.address, QUESTION_ROUTE, headers, payload)

    def test_the_route_refuses_without_the_token_or_origin_and_appends_nothing(self):
        svc = self.start()
        body = {"project_id": WHY, "question": "why?"}
        origin = f"http://127.0.0.1:{svc.address[1]}"
        cases = (
            ({"Origin": origin, **JSON}, b"token refused\n"),
            (self.own(svc, Origin="http://example.test", **JSON), b"origin refused\n"),
            ({"X-Console-Token": self.token(), **JSON}, b"origin refused\n"))
        for headers, text in cases:
            with self.subTest(text=text):
                got = self.assert_unchanged(svc, lambda: self.post(svc, body, headers))
                self.assertEqual((got[0], got[2]), (403, text))
        self.assertEqual(self.asked, [])

    def test_the_route_refuses_an_unregistered_project_and_appends_nothing(self):
        svc = self.start()
        cases = (
            ({"project_id": "owner/p99", "question": "why?"}, 409,
             b"this project is not registered\n"),
            (b'{"project_id":"owner/p01"}', 400, b"bad question\n"),
            ({"project_id": WHY, "question": ""}, 409, b"write the question first\n"))
        for body, status, text in cases:
            with self.subTest(text=text):
                got = self.assert_unchanged(
                    svc, lambda: self.post(svc, body, self.own(svc, **JSON)))
                self.assertEqual((got[0], got[2]), (status, text))
        self.assertEqual(self.asked, [])

    def test_a_question_from_the_page_is_answered_into_the_log(self):
        svc = self.start()
        status, _, body = self.post(
            svc, {"project_id": WHY, "question": "what does the build check?"},
            self.own(svc, **JSON))
        self.assertEqual((status, body), (204, b""))
        asked, answered = self.question_rows()[-2:]
        self.assertEqual((asked[0], asked[1], answered[0], answered[1]),
                         (ASKED, WHY, ANSWERED_KIND, WHY))

    def test_a_follow_up_from_the_page_names_its_thread(self):
        svc = self.start()
        self.post(svc, {"project_id": WHY, "question": "what does the build check?"},
                  self.own(svc, **JSON))
        first = self.question_rows()[0][2]["question_id"]
        status, _, body = self.post(
            svc, {"project_id": WHY, "question": "and then?", "thread_id": first},
            self.own(svc, **JSON))
        self.assertEqual((status, body), (204, b""))
        asked = [row for row in self.question_rows() if row[0] == ASKED][-1]
        self.assertEqual(asked[2]["thread_id"], first)
        cases = (
            ({"project_id": WHY, "question": "x", "thread_id": ""}, 400, b"bad question\n"),
            ({"project_id": WHY, "question": "x", "thread_id": 3}, 400, b"bad question\n"),
            ({"project_id": WHY, "question": "x", "thread_id": "nope"}, 409,
             (project_question.THREAD_UNKNOWN + "\n").encode()))
        for body, status, text in cases:
            with self.subTest(thread_id=body["thread_id"]):
                got = self.assert_unchanged(
                    svc, lambda: self.post(svc, body, self.own(svc, **JSON)))
                self.assertEqual((got[0], got[2]), (status, text))

    def test_the_route_is_a_page_write_that_takes_only_post(self):
        svc = self.start()
        self.assertIn(QUESTION_ROUTE, service.PAGE_WRITES)
        for method in ("GET", "PUT", "DELETE"):
            with self.subTest(method=method):
                status, headers, _ = support.request(svc.address, method, QUESTION_ROUTE)
                self.assertEqual((status, headers["Allow"]), (405, "POST"))
