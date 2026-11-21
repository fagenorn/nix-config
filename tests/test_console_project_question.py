"""The console's project question session (#1176): hook, launch, service and route.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import contextlib
import dataclasses
import errno
import io
import json
import os
import random
import shlex
import subprocess
import sys
import shutil
import string
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import (
    account_remove, deliveries, event_log, project_question, project_question_hook as hook, question_records, service, sessions,
    signin, spend, sprints, view,
    write_guard)
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
            "gh release view v1.2.0 --repo owner/p01", "gh pr view 12 --repo owner/p01",
            "gh issue view 7 -R owner/p01", "gh run view 123 --repo=owner/p01 --log-failed",
            "gh release view v1.2.0 --repo owner/p01 --json body", "gh pr view 12 --repo owner/p01 --comments",
            "gh pr view --repo owner/p01 12 --json title",
            "gh run view --repo owner/p01 123 --attempt 2", "gh run view --repo owner/p01 123 -a 2",
            "gh run view 123 --repo owner/p01 --attempt 2", "gh run view 123 --repo owner/p01 -a 2",
            "gh run view --repo owner/p01 123 --job 9 --attempt 2",
"gh release list --repo owner/p01 --limit 100",
            "gh pr list --repo owner/p01 --state merged --search merged:2026-01-01..2026-01-31",
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
            "gh release view --repo owner/p01 -- v1",
            "gh release view v1 -- --repo owner/p01", "gh release view v1 v2 --repo owner/p01",
            "gh release view v1 --repo owner/p01 v2", "gh release view --repo owner/p01 v1 v2",
            "gh pr view 12 --repo owner/p01 13", "gh run view --repo owner/p01 123 --attempt 2 3",
            "gh run view 123 --repo owner/p01 --attempt 2 3",
"gh pr view 12 --repo other/repo",
            "gh pr view 12 --repo owner/p01x", "gh pr view 12 --repo", "gh pr view 12",
            "gh pr view 12 --state open", "gh issue view 7 --repo owner/p01 --repo owner/p01",
            "gh pr view 12 --repo owner/p01 --repo other/repo", "gh pr view 12 -R owner/p01 -R other/repo",
            "gh pr view 12/x --repo owner/p01", "gh pr view https://github.com/other/repo/pull/1 --repo owner/p01",
            "gh pr view 12 --repo owner/p01 --web", "gh pr view 12 --repo owner/p01 -w",
            "gh pr list 12 --repo owner/p01", "gh pr view -- 12 --repo owner/p01",
            "gh pr view 12 --repo owner/p01 | cat", "gh pr view 12 --repo owner/p01; rm x",
            "gh pr view 12 --repo owner/p01 && ls", "gh pr view 12 --repo owner/p01 > out",
            "gh pr view 12 --repo owner/p01\nls", "gh pr view $(echo 12) --repo owner/p01",
            "gh pr view 12 --repo owner/p01 `ls`",
            "gh pr view 12 --repo owner/p01 &", "gh pr view 12 --repo owner/p01 || ls",
            "gh pr view 12 --repo owner/p01 --jq .[0]",
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
        for command in ("(git log)", "(gh pr view 12 --repo owner/p01)", "$(git log)", "`git log`", "FOO=1 git log"):
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


def normjoin(text, base):
    """`hook._resolve` without symlink resolution: each alias spelling stays as written."""
    return os.path.normpath(os.path.join(base, os.path.expanduser(text)))


class HookConfinementTest(unittest.TestCase):
    """The hook confines reads of the console's state to the question's own records (#1271)."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.t = t = Path(directory.name).resolve()
        self.P = P = t / "state" / "console"
        self.S = S = P / "project-question-settings"
        S.mkdir(parents=True)
        (P / "events.sqlite3").write_text("log")
        (P / "page-token").write_text("token")
        self.R = S / "a.records.json"
        self.Q = S / "b.records.json"
        self.R.write_text("{}")
        self.Q.write_text("{}")
        self.root = root = t / "srv" / "p01"
        (root / "sub").mkdir(parents=True)
        (root / "flake.nix").write_text("{}")
        (root / "sub" / "a.nix").write_text("{}")
        (root / "docs").symlink_to(root / "sub")
        self.c = hook.parse_confinement(str(P), str(self.R))
        self.denied = ("deny", hook.RECORDS_DENIED.format(records=self.c.records))
        self.allowed = ("allow", hook.ALLOWED)

    def doc(self, name, tool_input, cwd=None):
        return {**tool(name, tool_input), "cwd": str(cwd or self.root)}

    def command(self, text, cwd=None):
        return {**bash(text), "cwd": str(cwd or self.root)}

    def test_read_grep_and_glob_reach_only_the_own_records_file(self):
        P, S, R, Q, t, root = self.P, self.S, self.R, self.Q, self.t, self.root
        for name, tool_input, expected in (
            ("Read", {"file_path": str(R)}, self.allowed),
            ("Grep", {"pattern": "x", "path": str(R)}, self.allowed),
            ("Read", {"file_path": str(root / "flake.nix")}, self.allowed),
            ("Grep", {"pattern": "x"}, self.allowed),
            ("Glob", {"pattern": "**/*.nix"}, self.allowed),
            ("Grep", {"pattern": "x", "path": str(root / "docs")}, self.allowed),
            ("Read", {"file_path": str(Q)}, self.denied),
            ("Read", {"file_path": str(P / "events.sqlite3")}, self.denied),
            ("Read", {"file_path": str(P / "page-token")}, self.denied),
            ("Read", {"file_path": "../../state/console/events.sqlite3"}, self.denied),
            ("Grep", {"pattern": "x", "path": str(S)}, self.denied),
            ("Grep", {"pattern": "x", "path": str(t)}, self.denied),
            ("Grep", {"pattern": "x", "path": "/"}, self.denied),
            ("Glob", {"pattern": str(P) + "/**/*.json"}, self.denied),
            ("Glob", {"path": str(root), "pattern": "../../state/console/**"}, self.denied),
            ("Glob", {"path": str(t), "pattern": "**/*.records.json"}, self.denied),
        ):
            with self.subTest(name=name, tool_input=tool_input):
                self.assertEqual(
                    hook.decide(self.doc(name, tool_input), DECLARED, None, self.c), expected)

    def test_writes_stay_write_denied_under_the_confinement(self):
        for name in ("Write", "Edit", "NotebookEdit"):
            for path in (self.R, self.Q):
                with self.subTest(name=name, path=path):
                    self.assertEqual(
                        hook.decide(
                            self.doc(name, {"file_path": str(path)}), DECLARED, None, self.c),
                        ("deny", hook.WRITE_DENIED.format(tool=name)))

    def test_an_admitted_command_naming_the_console_state_is_denied(self):
        denied = self.command("git diff --no-index ../../state/console/events.sqlite3 flake.nix")
        self.assertEqual(hook.decide(denied, DECLARED, None, self.c), self.denied)
        for text in ("git show HEAD", "git log --format=%H -n5", "just build"):
            with self.subTest(text):
                self.assertEqual(
                    hook.decide(self.command(text), DECLARED, None, self.c), self.allowed)

    def test_a_file_named_as_an_attached_option_value_is_denied(self):
        for text in (
            "git blame --contents=" + str(self.P / "page-token") + " flake.nix",
            "git blame --contents=../../state/console/events.sqlite3 flake.nix",
            "git blame --contents=" + str(self.Q) + " flake.nix",
            "git diff -O../../state/console/page-token",
            "git diff -O@../../state/console/page-token",
            "git blame -wS" + str(self.P / "page-token") + " flake.nix",
            "git blame -wS" + str(self.Q) + " flake.nix",
            "git log -wS../../state/console/events.sqlite3",
            "git blame -wS@../../state/console/page-token flake.nix",
        ):
            with self.subTest(text):
                self.assertEqual(
                    hook.decide(self.command(text), DECLARED, None, self.c), self.denied)
                self.assertEqual(hook.decide(self.command(text), DECLARED), self.allowed)

    def test_a_transcript_store_is_confined_like_the_console_state(self):
        home = self.t / "home"
        shared = home / ".claude" / "projects" / "-srv-p00"
        shared.mkdir(parents=True)
        transcript = shared / "session.jsonl"
        transcript.write_text("{}")
        profile = self.t / "accounts" / "profiles" / "p1"
        profile.mkdir(parents=True)
        (profile / "projects").symlink_to(home / ".claude" / "projects")
        environ = {"HOME": str(home), "CLAUDE_ACCOUNTS_DIR": str(self.t / "accounts"),
                   "CLAUDE_CONFIG_DIR": str(profile)}
        c = hook.parse_confinement(str(self.P), str(self.R), environ)
        for name, tool_input in (
            ("Read", {"file_path": str(transcript)}),
            ("Read", {"file_path": str(profile / "projects" / "-srv-p00" / "session.jsonl")}),
            ("Grep", {"pattern": "x", "path": str(home / ".claude" / "projects")}),
            ("Grep", {"pattern": "x", "path": str(profile)}),
            ("Grep", {"pattern": "x", "path": str(home)}),
            ("Glob", {"pattern": str(home / ".claude" / "projects" / "**" / "*.jsonl")}),
        ):
            with self.subTest(name=name, tool_input=tool_input):
                self.assertEqual(hook.decide(self.doc(name, tool_input), DECLARED, None, c),
                                 ("deny", hook.RECORDS_DENIED.format(records=c.records)))
        for text in ("git diff --no-index " + str(transcript) + " flake.nix",
                     "git blame -wS" + str(transcript) + " flake.nix"):
            with self.subTest(text):
                self.assertEqual(hook.decide(self.command(text), DECLARED, None, c),
                                 ("deny", hook.RECORDS_DENIED.format(records=c.records)))
        self.assertEqual(
            hook.decide(self.doc("Read", {"file_path": str(self.root / "flake.nix")}),
                        DECLARED, None, c), self.allowed)
        self.assertEqual(hook.decide(self.doc("Grep", {"pattern": "x"}), DECLARED, None, c),
                         self.allowed)

    def test_a_second_spelling_of_the_console_state_is_confined_by_identity(self):
        (self.t / "alias").symlink_to(self.t / "state")
        A = self.t / "alias" / "console"
        home = self.t / "home"
        (home / ".claude" / "projects" / "-srv-p00").mkdir(parents=True)
        (home / ".claude" / "projects" / "-srv-p00" / "session.jsonl").write_text("{}")
        (self.t / "homealias").symlink_to(home)
        c = hook.parse_confinement(str(self.P), str(self.R), {
            "HOME": str(home), "CLAUDE_ACCOUNTS_DIR": str(self.t / "accounts"),
            "CLAUDE_CONFIG_DIR": str(self.t / "absent")})
        denied = ("deny", hook.RECORDS_DENIED.format(records=c.records))
        records = A / "project-question-settings"
        with mock.patch.object(hook, "_resolve", normjoin):
            for name, tool_input, expected in (
                ("Read", {"file_path": str(records / "a.records.json")}, self.allowed),
                ("Read", {"file_path": str(self.root / "missing.nix")}, self.allowed),
                ("Read", {"file_path": str(records / "b.records.json")}, denied),
                ("Read", {"file_path": str(A / "page-token")}, denied),
                ("Read", {"file_path": str(self.t / "homealias" / ".claude" / "projects"
                                           / "-srv-p00" / "session.jsonl")}, denied),
                ("Grep", {"pattern": "x", "path": str(self.t / "alias")}, denied),
                ("Grep", {"pattern": "x", "path": str(self.t / "homealias")}, denied),
                ("Grep", {"pattern": "x", "path": str(records)}, denied),
                ("Glob", {"pattern": str(A) + "/**/*.json"}, denied),
            ):
                with self.subTest(name=name, tool_input=tool_input):
                    self.assertEqual(
                        hook.decide(self.doc(name, tool_input), DECLARED, None, c), expected)
            with self.subTest("git blame"):
                self.assertEqual(
                    hook.decide(self.command("git blame -wS" + str(records / "b.records.json")
                                             + " flake.nix"), DECLARED, None, c), denied)

    def test_a_case_alias_of_the_console_state_is_confined_like_its_own_spelling(self):
        def alias(p):
            return Path(str(p).replace("/state/console", "/STATE/Console"))

        if not (self.t / "STATE").exists():
            self.skipTest("the temporary volume is case-sensitive")
        for name, tool_input, expected in (
            ("Read", {"file_path": str(alias(self.R))}, self.allowed),
            ("Read", {"file_path": str(alias(self.Q))}, self.denied),
            ("Read", {"file_path": str(alias(self.P / "page-token"))}, self.denied),
            ("Grep", {"pattern": "x", "path": str(alias(self.S))}, self.denied),
            ("Grep", {"pattern": "x", "path": str(self.t / "STATE")}, self.denied),
            ("Glob", {"pattern": str(alias(self.P)) + "/**/*.json"}, self.denied),
        ):
            with self.subTest(name=name, tool_input=tool_input):
                self.assertEqual(
                    hook.decide(self.doc(name, tool_input), DECLARED, None, self.c), expected)
        with self.subTest("git blame"):
            self.assertEqual(
                hook.decide(self.command("git blame -wS" + str(alias(self.Q)) + " flake.nix"),
                            DECLARED, None, self.c), self.denied)
        with self.subTest("parser"):
            with self.assertRaises(ValueError):
                hook.parse_confinement(str(self.P), str(alias(self.P)))
        (self.root / "elsewhere").symlink_to(alias(self.S))
        self.assertEqual(
            hook.decide(self.doc("Grep", {"pattern": "x"}), DECLARED, None, self.c), self.denied)

    def test_an_identity_that_cannot_be_read_is_a_denial(self):
        (self.t / "alias").symlink_to(self.t / "state")
        real_stat = os.stat

        def broken(p, *args, **kwargs):
            if os.fspath(p) == str(self.P):
                raise OSError(errno.EIO, "Input/output error")
            return real_stat(p, *args, **kwargs)

        records = self.t / "alias" / "console" / "project-question-settings"
        with mock.patch.object(hook, "_resolve", normjoin), \
                mock.patch.object(hook.os, "stat", broken):
            self.assertEqual(
                hook.decide(self.doc("Read", {"file_path": str(records / "b.records.json")}),
                            DECLARED, None, self.c), ("deny", hook.MALFORMED))
        out = io.StringIO()
        with mock.patch.object(hook.os.path, "realpath", os.path.normpath), \
                mock.patch.object(hook.os, "stat", broken), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(
                    self.doc("Read", {"file_path": str(self.root / "flake.nix")})))), \
                contextlib.redirect_stdout(out):
            status = hook.main([json.dumps([list(argv) for argv in DECLARED]), REPO,
                                str(self.P), str(records / "a.records.json")])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out.getvalue()), hook.output("deny", hook.MALFORMED))

    def test_a_path_the_filesystem_cannot_resolve_is_not_a_denial(self):
        root = self.root
        (root / "loop").symlink_to("loop")
        (root / "sub" / "a").symlink_to("b")
        (root / "sub" / "b").symlink_to("a")
        long_name = root / ("x" * 5000)
        for name, tool_input in (
            ("Grep", {"pattern": "x"}),
            ("Glob", {"pattern": "**/*.nix"}),
            ("Read", {"file_path": str(root / "loop")}),
            ("Read", {"file_path": str(root / "sub" / "a")}),
            ("Read", {"file_path": str(long_name)}),
        ):
            with self.subTest(name=name, tool_input=tool_input):
                self.assertEqual(
                    hook.decide(self.doc(name, tool_input), DECLARED, None, self.c), self.allowed)

    def test_a_symlink_into_the_console_state_is_resolved(self):
        (self.root / "link").symlink_to(self.P)
        for name, tool_input in (
            ("Read", {"file_path": str(self.root / "link" / "events.sqlite3")}),
            ("Grep", {"pattern": "x", "path": str(self.root / "link")}),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    hook.decide(self.doc(name, tool_input), DECLARED, None, self.c), self.denied)

    def test_a_search_that_would_meet_the_console_state_later_is_denied(self):
        root = self.root
        (root / "sub" / "deep").mkdir()
        (root / "sub" / "deep" / "link").symlink_to(self.P)
        for name, tool_input in (
            ("Grep", {"pattern": "x"}),
            ("Grep", {"pattern": "x", "path": str(root / "sub")}),
            ("Glob", {"pattern": "*/*/link/*"}),
            ("Glob", {"pattern": "**/*.json"}),
            ("Glob", {"path": str(root), "pattern": "*/../../../state/console/*"}),
        ):
            with self.subTest(name=name, tool_input=tool_input):
                self.assertEqual(
                    hook.decide(self.doc(name, tool_input), DECLARED, None, self.c), self.denied)
        other = self.t / "other"
        other.mkdir()
        (other / "back").symlink_to(self.P)
        second = self.t / "srv" / "p02"
        second.mkdir()
        (second / "ext").symlink_to(other)
        for tool_input in ({"pattern": "x"}, {"pattern": "x", "glob": "../../state/**"}):
            with self.subTest(second=tool_input):
                self.assertEqual(
                    hook.decide(
                        self.doc("Grep", tool_input, cwd=second), DECLARED, None, self.c),
                    self.denied)
        clean = self.t / "srv" / "p03"
        clean.mkdir()
        for name, tool_input in (
            ("Grep", {"pattern": "x", "glob": "../../state/**"}),
            ("Glob", {"pattern": "*/../../../state/console/*"}),
        ):
            with self.subTest(clean=name):
                self.assertEqual(
                    hook.decide(self.doc(name, tool_input, cwd=clean), DECLARED, None, self.c),
                    self.denied)

    def test_a_brace_group_that_expands_to_a_parent_component_is_denied(self):
        for name, tool_input in (
            ("Glob", {"pattern": "{../..,x}/state/console/*"}),
            ("Glob", {"pattern": "{..,x}/{..,x}/state/console/*"}),
            ("Glob", {"pattern": "{.,x}{.,x}/{.,x}{.,x}/state/console/*"}),
            ("Glob", {"pattern": "*/{..,x}/{..,x}/{..,x}/state/console/*"}),
            ("Grep", {"pattern": "x", "glob": "{..,x}/{..,x}/state/**"}),
        ):
            with self.subTest(name=name, tool_input=tool_input):
                self.assertEqual(
                    hook.decide(self.doc(name, tool_input), DECLARED, None, self.c), self.denied)
        for name, tool_input in (
            ("Glob", {"pattern": "**/*.{nix,md}"}),
            ("Grep", {"pattern": "x", "glob": "*.{nix,md}"}),
        ):
            with self.subTest(name=name, tool_input=tool_input):
                self.assertEqual(
                    hook.decide(self.doc(name, tool_input), DECLARED, None, self.c), self.allowed)

    def test_a_search_walks_a_tree_reached_through_a_link_into_a_store(self):
        store = self.t / "store"
        (store / "closure").mkdir(parents=True)
        (store / "closure" / "back").symlink_to(self.P)
        (self.root / "result").symlink_to(store)
        tool_input = {"pattern": "x"}
        self.assertEqual(
            hook.decide(self.doc("Grep", tool_input), DECLARED, None, self.c), self.denied)
        (store / "closure" / "back").unlink()
        self.assertEqual(
            hook.decide(self.doc("Grep", tool_input), DECLARED, None, self.c), self.allowed)
        with mock.patch.object(hook, "WALK_LIMIT", 1):
            self.assertEqual(
                hook.decide(self.doc("Grep", tool_input), DECLARED, None, self.c),
                ("deny", hook.SEARCH_UNCHECKED.format(limit=1)))

    def test_a_search_denies_a_second_mount_of_the_console_state_by_identity(self):
        (self.root / "mnt").mkdir()
        real_stat = os.stat
        private = real_stat(self.P)

        def stat(path, *args, **kwargs):
            return private if str(path) == str(self.root / "mnt") else real_stat(path, *args, **kwargs)

        with mock.patch.object(hook.os, "stat", stat):
            self.assertEqual(
                hook.decide(self.doc("Grep", {"pattern": "x"}), DECLARED, None, self.c),
                self.denied)
        self.assertEqual(
            hook.decide(self.doc("Grep", {"pattern": "x"}), DECLARED, None, self.c), self.allowed)

    def test_a_separate_mount_of_the_records_directory_alone_is_confined_by_identity(self):
        # The settings directory holds every question's records; a mount of it has neither the private
        # directory nor a transcript store in its visible ancestry.
        (self.root / "mnt").mkdir()
        real_stat = os.stat
        settings = real_stat(self.S)

        def stat(path, *args, **kwargs):
            return settings if str(path) == str(self.root / "mnt") else real_stat(path, *args, **kwargs)

        with mock.patch.object(hook.os, "stat", stat):
            for name, tool_input in (
                ("Read", {"file_path": str(self.root / "mnt" / "b.records.json")}),
                ("Grep", {"pattern": "x"}),
                ("Grep", {"pattern": "x", "path": str(self.root / "mnt")}),
                ("Glob", {"pattern": "**/*.json"}),
            ):
                with self.subTest(name=name, tool_input=tool_input):
                    self.assertEqual(
                        hook.decide(self.doc(name, tool_input), DECLARED, None, self.c), self.denied)
            self.assertEqual(hook.decide(self.command("git blame -wS" + str(self.root / "mnt" / "b.records.json")
                                                      + " flake.nix"), DECLARED, None, self.c), self.denied)
        self.assertEqual(
            hook.decide(self.doc("Grep", {"pattern": "x"}), DECLARED, None, self.c), self.allowed)

    def test_a_search_with_a_directory_it_cannot_list_is_refused(self):
        real_scandir = os.scandir

        def scandir(path):
            if str(path) == str(self.root / "sub"):
                raise PermissionError(errno.EACCES, "denied")
            return real_scandir(path)

        with mock.patch.object(hook.os, "scandir", scandir):
            self.assertEqual(
                hook.decide(self.doc("Grep", {"pattern": "x"}), DECLARED, None, self.c),
                ("deny", hook.SEARCH_UNCHECKED.format(limit=hook.WALK_LIMIT)))

    def test_the_sessions_own_saved_tool_output_is_readable_and_no_other_sessions(self):
        home = self.t / "home"
        environ = {"HOME": str(home), "CLAUDE_ACCOUNTS_DIR": str(self.t / "accounts"),
                   "CLAUDE_CONFIG_DIR": str(self.t / "profile")}
        mine = self.t / "profile" / "projects" / "-srv-p01" / "sess-1" / "tool-results"
        theirs = self.t / "profile" / "projects" / "-srv-p01" / "sess-2" / "tool-results"
        for results in (mine, theirs):
            results.mkdir(parents=True)
            (results / "b1.txt").write_text("out")
        transcript = self.t / "profile" / "projects" / "-srv-p01" / "sess-1.jsonl"
        transcript.write_text("{}")
        c = hook.parse_confinement(str(self.P), str(self.R), environ)
        denied = ("deny", hook.RECORDS_DENIED.format(records=c.records))

        def decide(name, tool_input, session="sess-1"):
            return hook.decide({**self.doc(name, tool_input), "session_id": session}, DECLARED, None, c)

        for name, tool_input in (
            ("Read", {"file_path": str(mine / "b1.txt")}),
            ("Grep", {"pattern": "x", "path": str(mine)}),
            ("Glob", {"pattern": str(mine / "*.txt")}),
        ):
            with self.subTest(allowed=name):
                self.assertEqual(decide(name, tool_input), self.allowed)
        for name, tool_input, session in (
            ("Read", {"file_path": str(theirs / "b1.txt")}, "sess-1"),
            ("Read", {"file_path": str(mine / "b1.txt")}, "sess-2"),
            ("Read", {"file_path": str(mine / "b1.txt")}, "../sess-1"),
            ("Read", {"file_path": str(transcript)}, "sess-1"),
            ("Grep", {"pattern": "x", "path": str(mine.parent)}, "sess-1"),
            ("Grep", {"pattern": "x", "path": str(self.t / "profile" / "projects")}, "sess-1"),
        ):
            with self.subTest(denied=name, tool_input=tool_input, session=session):
                self.assertEqual(decide(name, tool_input, session), denied)
        no_session = hook.decide(self.doc("Read", {"file_path": str(mine / "b1.txt")}), DECLARED, None, c)
        self.assertEqual(no_session, denied)
        self.assertEqual(
            hook.decide({**self.command("git show HEAD"), "session_id": "sess-1"}, DECLARED, None, c),
            self.allowed)
        self.assertEqual(
            hook.decide({**self.command("git diff --no-index " + str(mine / "b1.txt") + " flake.nix"),
                         "session_id": "sess-1"}, DECLARED, None, c),
            self.allowed)

    def test_a_search_that_outruns_its_time_budget_is_refused(self):
        with mock.patch.object(hook, "WALK_SECONDS", -1.0):
            self.assertEqual(
                hook.decide(self.doc("Grep", {"pattern": "x"}), DECLARED, None, self.c),
                ("deny", hook.SEARCH_UNCHECKED.format(limit=hook.WALK_LIMIT)))

    def test_a_search_too_large_to_check_is_refused(self):
        with mock.patch.object(hook, "WALK_LIMIT", 2):
            self.assertEqual(
                hook.decide(self.doc("Grep", {"pattern": "x"}), DECLARED, None, self.c),
                ("deny", hook.SEARCH_UNCHECKED.format(limit=2)))
            self.assertEqual(
                hook.decide(
                    self.doc("Read", {"file_path": str(self.root / "flake.nix")}),
                    DECLARED, None, self.c),
                self.allowed)

    def test_without_a_confinement_reads_are_admitted_as_before(self):
        self.assertEqual(
            hook.decide(self.doc("Read", {"file_path": str(self.Q)}), DECLARED), self.allowed)

    def test_a_confinement_that_is_not_absolute_or_not_inside_is_refused(self):
        for private, records in (
            ("rel", str(self.R)),
            (str(self.P), str(self.t / "x.records.json")),
            (str(self.P), str(self.P)),
        ):
            with self.subTest(private=private, records=records):
                with self.assertRaises(ValueError):
                    hook.parse_confinement(private, records)
        (self.t / "alias").symlink_to(self.t / "state")
        with self.subTest("the directory itself under a second spelling"):
            with mock.patch.object(hook.os.path, "realpath", os.path.normpath):
                with self.assertRaises(ValueError):
                    hook.parse_confinement(str(self.P), str(self.t / "alias" / "console"))


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

    def test_the_module_takes_the_confinement_as_two_more_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            P = Path(directory).resolve() / "state" / "console"
            (P / "project-question-settings").mkdir(parents=True)
            R = P / "project-question-settings" / "a.records.json"
            Q = P / "project-question-settings" / "b.records.json"
            for path in (R, Q):
                path.write_text("{}")
            args = ['[["just","build"]]', "owner/p01", str(P), str(R)]
            done = self.run_hook(args, json.dumps(tool("Read", {"file_path": str(R)})))
            self.assertEqual(json.loads(done.stdout), self.wire("allow", hook.ALLOWED))
            done = self.run_hook(args, json.dumps(tool("Read", {"file_path": str(Q)})))
            self.assertEqual(
                json.loads(done.stdout),
                self.wire("deny", hook.RECORDS_DENIED.format(records=str(R))))
            done = self.run_hook(
                ['[["just","build"]]', "owner/p01", "rel", str(R)],
                json.dumps(tool("Read", {"file_path": str(R)})))
            self.assertEqual(json.loads(done.stdout), self.wire("deny", hook.MALFORMED))

    def test_the_module_confines_the_transcript_stores_of_its_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            t = Path(directory).resolve()
            P = t / "state" / "console"
            (P / "project-question-settings").mkdir(parents=True)
            R = P / "project-question-settings" / "a.records.json"
            R.write_text("{}")
            transcript = t / "home" / ".claude" / "projects" / "-srv-p00" / "s.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text("{}")
            done = subprocess.run(
                [sys.executable, "-m", "agent_tools.console.project_question_hook",
                 '[["just","build"]]', "owner/p01", str(P), str(R)],
                input=json.dumps(tool("Read", {"file_path": str(transcript)})),
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "HOME": str(t / "home"), "CLAUDE_CONFIG_DIR": str(t / "cfg"),
                     "CLAUDE_ACCOUNTS_DIR": str(t / "accounts")})
            self.assertEqual(
                json.loads(done.stdout),
                self.wire("deny", hook.RECORDS_DENIED.format(records=str(R))))

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


class LaunchCase(unittest.TestCase):
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


class LaunchTest(LaunchCase):
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

    def test_a_darwin_question_launches_the_linux_argv(self):
        outcome = self.start(self.fake(), platform="darwin")

        self.assertEqual(self.calls[0][0], project_question.launch_command(self.ask, "linux"))
        self.assertEqual(project_question.launch_command(self.ask, "darwin"),
                         project_question.launch_command(self.ask, "linux"))
        self.assertIsNone(project_question.launch_command(self.ask, "win32"))
        self.assertEqual(outcome, project_question.Outcome(
            "answered", answer="Answer: it builds the hosts."))

    def test_a_darwin_question_runs_no_linux_tool(self):
        forbidden = ("systemd-run", "systemctl", "/proc")
        self.start(self.fake(), platform="darwin")

        argv = self.calls[0][0]
        self.assertEqual(argv[0], "claude-account")
        self.assertFalse(any(word in element for word in forbidden for element in argv))
        document = json.loads(self.settings["text"])
        hook = shlex.split(document["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
        self.assertFalse(any(word in element for word in forbidden for element in hook))
        self.assertIs(self.calls[0][3]["start_new_session"], True)

    def test_each_failure_is_a_failed_outcome_with_its_reason(self):
        cancel = threading.Event()
        cases = [
            ("win32", {"platform": "win32", "run": self.fake()}, project_question.UNAVAILABLE_TEXT),
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
                if name in ("win32", "root"):
                    self.assertEqual(self.calls, [])


class RecordsLaunchTest(LaunchCase):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.t = Path(directory.name)
        self.state = self.t / "state" / "console"
        self.settings_dir = self.state / project_question.SETTINGS_DIR
        self.root = self.t / "srv" / "p01"
        self.root.mkdir(parents=True)
        self.records = '{\n "project_id": "owner/p01"\n}\n'
        self.routes = (project_question.Route("nix-build", ("just", "build"), str(self.root)),)
        self.ask = project_question.new_ask(
            "a" * 16, "owner/p01", str(self.root), "what costs the most?", "work", self.routes,
            self.settings_dir, session_id=SESSION_ID, records=self.records)
        self.seen = {}

    def capture(self, kwargs):
        path = project_question.records_path(self.ask)
        self.seen = {"text": path.read_text(), "mode": path.stat().st_mode & 0o777}

    def hook_words(self, document):
        return shlex.split(document["hooks"]["PreToolUse"][0]["hooks"][0]["command"])

    def test_the_prompt_names_the_records_file_and_what_it_holds(self):
        self.start(self.fake(act=self.capture))
        text = self.calls[0][0][-1]
        path = str(project_question.records_path(self.ask))
        self.assertIn(path, text)
        for part in (
            "spend over the last 30 days by day, delivery run, issue, phase and sprint",
            "its delivery runs with each issue's stage",
            "activation runs of it with how each ended and why",
            "its held checks",
            "Read it with Read, or Grep it",
            "why a delivery or production run failed",
            "name it under Read with the parts you read",
        ):
            with self.subTest(part):
                self.assertIn(part, text)
        self.assertNotIn(project_question.SECTIONS_TEXT.split("{")[0], text)
        self.assertEqual(
            text, project_question.prompt(self.ask.question, self.routes, records=path))
        self.assertLess(text.index(path), text.index(project_question.QUESTION_MARK))

    def test_the_prompt_gives_each_records_section_its_offset_and_limit(self):
        doc = {"project_id": "owner/p01", "written_at": "2026-11-17T08:00:30+00:00",
               "spend": None, "sprints": [], "deliveries": [], "activations": [],
               "held_checks": []}
        expected = set(doc) - {"project_id", "written_at"}
        text = question_records.encode(doc)
        self.ask = dataclasses.replace(self.ask, records=text)
        prompt_text = project_question.launch_command(self.ask, "linux")[-1]
        index = question_records.section_lines(text)
        self.assertEqual(set(index), expected)
        path = str(project_question.records_path(self.ask))
        for name in sorted(expected):
            offset, limit = index[name]
            with self.subTest(name):
                self.assertIn(f"{name} offset {offset} limit {limit}", prompt_text)
        self.assertIn(path + " (spend)", prompt_text)
        self.assertEqual(prompt_text, project_question.prompt(
            self.ask.question, self.routes, records=path,
            sections=question_records.section_lines(text)))

    def test_the_records_file_is_private_kept_for_an_answer_and_only_the_hook_words_change(self):
        self.start(self.fake(act=self.capture))
        self.assertEqual(self.seen, {"text": self.records, "mode": 0o600})
        self.assertEqual(project_question.records_path(self.ask).parent, self.ask.settings.parent)
        self.assertEqual(project_question.private_dir(self.ask), self.state)
        with_records = json.loads(self.settings["text"])
        self.ask = dataclasses.replace(self.ask, records=None)
        self.settings = {}
        self.start(self.fake())
        without = json.loads(self.settings["text"])
        self.assertEqual(with_records["permissions"], without["permissions"])
        self.assertEqual(
            self.hook_words(with_records),
            self.hook_words(without) + [
                str(self.state), str(project_question.records_path(self.ask))])
        self.assertFalse(project_question.records_path(self.ask).exists())
        self.assertFalse(self.ask.settings.exists())

    def test_the_records_file_of_an_answered_question_is_kept_private_and_any_other_outcome_removes_it(self):
        path = project_question.records_path(self.ask)
        self.assertEqual(self.start(self.fake()).outcome, project_question.ANSWERED)
        self.assertEqual((path.read_text(), path.stat().st_mode & 0o777), (self.records, 0o600))
        self.assertFalse(self.ask.settings.exists())
        for name, run in (("timed out", self.fake(error=subprocess.TimeoutExpired("claude", 1))),
                          ("failed exit", self.fake(code=1)), ("unreadable", self.fake(stdout=b"not json"))):
            with self.subTest(name):
                path.write_text("stale")
                self.assertNotEqual(self.start(run).outcome, project_question.ANSWERED)
                self.assertFalse(path.exists())
                self.assertFalse(self.ask.settings.exists())

    def test_writing_a_records_file_removes_the_kept_ones_older_than_ninety_days_only(self):
        self.settings_dir.mkdir(parents=True)
        now = time.time()
        old, fresh, other = (self.settings_dir / name for name in (
            "o" * 16 + project_question.RECORDS_SUFFIX, "f" * 16 + project_question.RECORDS_SUFFIX, "x.settings.json"))
        for path, age in ((old, 91 * 86400), (fresh, 89 * 86400), (other, 365 * 86400)):
            path.write_text("kept")
            os.utime(path, (now - age, now - age))
        self.start(self.fake())
        self.assertEqual((old.exists(), fresh.exists(), other.exists()), (False, True, True))
        self.assertTrue(project_question.records_path(self.ask).exists())

    def test_two_overlapping_questions_each_read_only_their_own_records(self):
        asks = {}
        for number, letter in ((0, "a"), (1, "b")):
            root = self.t / "srv" / f"p0{number}"
            root.mkdir(parents=True, exist_ok=True)
            asks[number] = project_question.new_ask(
                letter * 16, f"owner/p0{number}", str(root), "what costs the most?", "work",
                self.routes, self.settings_dir, session_id=SESSION_ID,
                records='{"project_id": "owner/p0%d"}\n' % number)
        first, second = asks[0], asks[1]
        decisions = {}

        def decide(own, other, name, tool_input):
            command = self.hook_words(json.loads(own.settings.read_text()))
            done = subprocess.run(
                command, input=json.dumps(
                    {"tool_name": name, "tool_input": tool_input, "cwd": own.root}),
                capture_output=True, text=True, timeout=30)
            result = json.loads(done.stdout)["hookSpecificOutput"]
            return result["permissionDecision"], result["permissionDecisionReason"]

        def inner(kwargs):
            for own, other in ((first, second), (second, first)):
                mine = str(project_question.records_path(own))
                theirs = project_question.records_path(other)
                self.assertEqual(Path(mine).read_text(), own.records)
                self.assertEqual(theirs.read_text(), other.records)
                refused = ("deny", hook.RECORDS_DENIED.format(records=os.path.realpath(mine)))
                decisions[own.question_id] = {
                    "own": decide(own, other, "Read", {"file_path": mine}),
                    "search": decide(own, other, "Grep", {"pattern": "x"}),
                    "other": decide(own, other, "Read", {"file_path": str(theirs)}),
                    "settings": decide(own, other, "Read", {"file_path": str(other.settings)}),
                    "glob": decide(
                        own, other, "Glob", {"pattern": str(self.settings_dir) + "/*"}),
                    "events": decide(
                        own, other, "Read", {"file_path": str(self.state / "events.sqlite3")}),
                    "write": decide(own, other, "Write", {"file_path": mine}),
                    "edit": decide(own, other, "Edit", {"file_path": mine}),
                    "refused": refused,
                }

        def outer(kwargs):
            project_question.run_question(
                second, None, platform="linux", run=self.fake_for(inner), environ=ENVIRON)

        project_question.run_question(
            first, None, platform="linux", run=self.fake_for(outer), environ=ENVIRON)
        for own in (first, second):
            seen = decisions[own.question_id]
            with self.subTest(own.question_id):
                self.assertEqual(seen["own"][0], "allow")
                self.assertEqual(seen["search"][0], "allow")
                for name in ("other", "settings", "glob", "events"):
                    self.assertEqual(seen[name], seen["refused"], name)
                for name in ("write", "edit"):
                    self.assertEqual(
                        seen[name],
                        ("deny", hook.WRITE_DENIED.format(tool=name.capitalize())), name)
            self.assertEqual(project_question.records_path(own).read_text(), own.records)
            self.assertFalse(own.settings.exists())

    def fake_for(self, act):
        def run(argv, *, timeout, cancel=None, **kwargs):
            act(kwargs)
            return subprocess.CompletedProcess(argv, 0, stdout=SUCCESS, stderr=None)
        return run

    def test_a_records_write_that_fails_is_a_failed_outcome_with_no_session(self):
        with mock.patch.object(
                project_question, "_write_records", side_effect=OSError(13, "Permission denied")):
            outcome = self.start(self.fake())
        self.assertEqual(
            outcome,
            project_question.Outcome(
                "failed", reason="cannot write the question's records: Permission denied"))
        self.assertEqual(self.calls, [])
        self.assertFalse(self.ask.settings.exists())

    def test_a_question_without_records_has_the_prompt_argv_and_hook_it_had(self):
        text = project_question.prompt("q", self.routes)
        self.assertEqual(text, project_question.prompt("q", self.routes, records=None))
        self.assertNotIn("console's own records", text)
        ask = self.make_ask(self.routes)
        self.assertEqual(
            project_question.launch_command(ask, "linux")[-1],
            project_question.prompt(ask.question, self.routes))
        self.assertEqual(
            project_question.hook_command(self.routes),
            project_question.hook_command(self.routes, None, None))


class PlatformTest(unittest.TestCase):
    def test_asker_for_each_platform(self):
        self.assertIs(project_question.asker_for("linux"), project_question.run_question)
        self.assertIs(project_question.asker_for("darwin"), project_question.run_question)
        self.assertIsNone(project_question.asker_for("win32"))


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

FAKE_CREDENTIALS = {
    "github": "gh" + "p_" + "a1b2c3" * 6,
    "github_pat": "github" + "_pat_" + "11ab" * 6,
    "hugging_face": "h" + "f_" + "abcd12" * 5,
    "sk_key": "s" + "k-ant-api03-" + "ab1x" * 8,
    "age_secret_key": "AGE-SECRET" + "-KEY-1" + "QZ7" * 18,
    "private_key_block": "-----BEGIN OPENSSH " + "PRIVATE KEY-----",
    "bearer": "Authorization: Bear" + "er " + "abcdefgh" * 3,
    "aws_key_id": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "slack": "xo" + "xb-" + "1234567890-abc",
    "gitlab": "gl" + "pat-" + "x1y2" * 5,
    "jwt": "ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0." + "dozjgNryP4J3jVmNHl0w5N",
    "assignment": "GH_TO" + "KEN=" + "abc123def456",
    "console_token": "Ab3dE5fG7hJ9kL1mN2pQr" + "-" + "s4T6uV8wX0yZ2aB4cD6eF",
    "base64_run": "Zx9Qw8Er7Ty6Ui5Op4" + "As3Df2Gh1Jk0LmNb",
}


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate(), "the condition did not become true within 5 s"


FENCED_ANSWER = "The answer shape now ends like this:\n```\nRead: flake.nix\nQuestion for you: none\n```"
FENCED = (
    "Answer: " + FENCED_ANSWER + "\nRead: git log --since=7.days\nRan: just build\n"
    "Question for you: none")


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

    def test_a_question_back_with_list_lines_carries_them_as_choices(self):
        text = ("Answer: The bill is unread.\nQuestion for you: Which export should I run?\n"
                "- The free summary\n* The paid export\n3. Neither")
        parts = project_question.answer_parts(text)
        self.assertEqual(parts.back, "Which export should I run?")
        self.assertEqual(parts.choices, ("The free summary", "The paid export", "Neither"))
        self.assertEqual(parts.answer, "The bill is unread.")

    def test_one_list_line_or_more_than_five_are_no_choices(self):
        six = "Which one?\n" + "".join(f"- c{i}\n" for i in range(6))
        for part in ("May I run it?\n- Yes", six, "- Yes\n- No"):
            with self.subTest(part=part):
                parts = project_question.answer_parts("Answer: a\nQuestion for you: " + part)
                self.assertEqual(parts.choices, ())
                self.assertEqual(parts.back, part.strip())

    def test_a_back_of_none_has_no_choices(self):
        parts = project_question.answer_parts("Answer: ok\nQuestion for you: none")
        self.assertIsNone(parts.back)
        self.assertEqual(parts.choices, ())

    def test_a_heading_like_line_inside_fenced_code_stays_in_its_part(self):
        parts = project_question.answer_parts(FENCED)
        self.assertEqual(parts.answer, FENCED_ANSWER)
        self.assertEqual(parts.read, "git log --since=7.days")
        self.assertEqual(parts.ran, "just build")
        self.assertIsNone(parts.back)

    def test_a_fence_opened_on_a_heading_line_is_closed_before_the_next_heading(self):
        parts = project_question.answer_parts(
            "Answer: ```\nnix build .#x\n```\nRead: flake.nix\nRan: just build\n"
            "Question for you: Which export should I run?\n- The free summary\n- The paid export")
        self.assertEqual(parts.answer, "```\nnix build .#x\n```")
        self.assertEqual(parts.read, "flake.nix")
        self.assertEqual(parts.ran, "just build")
        self.assertEqual(parts.back, "Which export should I run?")
        self.assertEqual(parts.choices, ("The free summary", "The paid export"))

    def test_an_unclosed_fence_keeps_the_rest_in_its_part(self):
        parts = project_question.answer_parts("Answer: See:\n```\nRead: x\nRan: y")
        self.assertEqual(parts.answer, "See:\n```\nRead: x\nRan: y")
        self.assertIsNone(parts.read)
        self.assertIsNone(parts.ran)

    def test_lead_names_the_formatting_subset_and_the_choice_shape(self):
        for phrase in ("**bold**", "`inline code`", "fenced code blocks",
                       "no headings, tables, links or HTML", "two to five answers",
                       'starting with "- "'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, project_question.LEAD)


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

    def test_a_deletion_row_drops_the_named_questions_of_its_project_only(self):
        rows = [_asked(1, "o/a", "q1"),
                _answered(2, "o/a", "q1", outcome="answered", answer="A"),
                _asked(3, "o/a", "q2", thread_id="q1"),
                _asked(4, "o/b", "q1"),
                _asked(5, "o/a", "q3"),
                _row(6, "project_question.deleted", "o/a",
                     {"question_ids": ["q1", "q2"], "thread_id": "q1"})]
        once = project_question.asked_questions(rows)
        batched = project_question.asked_questions(
            rows[3:], project_question.asked_questions(rows[:3]))
        self.assertEqual(once, batched)
        self.assertEqual([q.question_id for q in once["o/a"]], ["q3"])
        self.assertEqual([q.question_id for q in once["o/b"]], ["q1"])

    def test_a_malformed_deletion_row_drops_nothing(self):
        cases = (("o/a", {"question_ids": "q1"}), (None, {"question_ids": ["q1"]}),
                 ("o/a", {"question_ids": {"k": "q1"}}), ("o/a", {"question_ids": [1, None]}),
                 ("o/a", {}))
        for project, payload in cases:
            with self.subTest(project=project, payload=payload):
                rows = [_asked(1, "o/a", "q1"),
                        _row(2, "project_question.deleted", project, payload)]
                found = project_question.asked_questions(rows)
                self.assertEqual([q.question_id for q in found["o/a"]], ["q1"])

    def test_a_project_whose_every_question_is_deleted_has_no_entry(self):
        rows = [_asked(1, "o/a", "q1"),
                _row(2, "project_question.deleted", "o/a", {"question_ids": ["q1"]})]
        self.assertNotIn("o/a", project_question.asked_questions(rows))


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


class ThreadDeleteTest(unittest.TestCase):
    P = "owner/p01"

    def questions(self):
        return project_question.asked_questions([
            _asked(1, self.P, "q1"),
            _answered(2, self.P, "q1", outcome="answered", answer="A"),
            _asked(3, self.P, "q2", thread_id="q1"),
            _asked(4, self.P, "q3")])[self.P]

    def test_a_thread_names_its_questions_in_order(self):
        qs = self.questions()
        self.assertEqual(project_question.thread_question_ids(qs, "q1"), ("q1", "q2"))
        self.assertEqual(project_question.thread_question_ids(qs, "q3"), ("q3",))

    def test_an_unknown_thread_or_a_follow_up_id_is_refused(self):
        for thread_id in ("q2", "nope"):
            with self.subTest(thread_id=thread_id):
                with self.assertRaises(project_question.Refused) as caught:
                    project_question.thread_question_ids(self.questions(), thread_id)
                self.assertEqual(str(caught.exception), project_question.THREAD_UNKNOWN)


class DeleteRequestTest(unittest.TestCase):
    def test_a_delete_request_reads_exactly_the_project_and_the_thread(self):
        self.assertEqual(
            project_question.parse_delete_request(b'{"project_id":"o/a","thread_id":"q1"}'),
            ("o/a", "q1"))

    def test_any_other_delete_body_is_refused(self):
        bodies = (b'{"project_id":"o/a"}',
                  b'{"project_id":"o/a","thread_id":"q1","question":"x"}',
                  b'{"project_id":"","thread_id":"q1"}', b'{"project_id":"o/a","thread_id":""}',
                  b'{"project_id":"o/a","thread_id":3}', b'["o/a","q1"]',
                  b'{"project_id":"o/a","project_id":"o/b","thread_id":"q1"}',
                  b'{"project_id":"o/a","thread_id":NaN}', b"\xff", b"[" * 100000)
        for body in bodies:
            with self.subTest(body=body[:60]):
                with self.assertRaises(ValueError):
                    project_question.parse_delete_request(body)

    def test_the_working_refusal_names_no_question_text(self):
        self.assertEqual(project_question.THREAD_WORKING,
                         "this thread is still being answered: delete it once the answer is in")


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
            "When the question covers a time window, count every release, pull request or deploy "
            "dated inside it from the dates you read: raise the list limit (for example --limit) "
            "until a list returns fewer items than the limit, so you have read every item, never "
            "stop at a first page or an arbitrary limit and never stop at the first item older "
            "than the window, because gh lists by creation date and a release published or a "
            "pull request merged inside the window can have been created before it; when a list "
            "is too long to read whole, filter it by the date that counts (for example --search "
            "merged:2026-01-01..2026-01-31), and say in the answer where the count comes from.",
            'Format only with **bold**, list lines starting with "- ", `inline code` and fenced '
            "code blocks; use no headings, tables, links or HTML.",
        )
        for rule in rules:
            self.assertIn(rule, project_question.LEAD)
            self.assertLess(text.index(rule), text.index("Answer: <"))
        self.assertEqual(project_question.ANSWER_RULES, " ".join(rules) + " ")

    def test_the_prompt_names_reads_the_hook_admits(self):
        text = project_question.prompt("q", (), repo="owner/p01")
        examples = ("git log --since=7.days.ago --oneline", "git tag -l",
                    "gh pr list --repo owner/p01 --state merged --limit 30",
                    "gh release list --repo owner/p01 --limit 100",
                    "gh release view v1.2.0 --repo owner/p01",
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
                 "read_text", "ran_text", "unknown_text", "back_text", "back_choices",
                 "production_text", "request_key"}


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
        self.assertEqual(q1["back_choices"], [])
        self.assertIsNone(q4["back_choices"])
        self.assertIsNone(q2["back_choices"])
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

    def _only_question(self, answer):
        events = [_registered(1, self.P1), _asked(2, self.P1, "q1"),
                  _answered(3, self.P1, "q1", outcome="answered", answer=answer)]
        shown = view.derive_view(view.project_states(events).values(),
                                 project_questions=project_question.asked_questions(events))
        return shown["entries"][0]["questions"]["threads"][0]["questions"][0]

    def test_a_question_back_with_choices_reads_its_question_and_its_choices(self):
        question = self._only_question(
            "Answer: I cannot read the bill.\nQuestion for you: Which export should I run?\n"
            "- The free summary\n- The paid export")
        self.assertEqual(question["back_text"], "Question for you: Which export should I run?")
        self.assertEqual(question["back_choices"], ["The free summary", "The paid export"])

    def test_a_stored_answer_with_heading_like_code_lines_keeps_them_in_the_answer(self):
        question = self._only_question(FENCED)
        self.assertEqual(question["answer"], FENCED_ANSWER)
        self.assertEqual(question["read_text"], "Read: git log --since=7.days")
        self.assertEqual(question["ran_text"], "Ran: just build")
        self.assertIsNone(question["back_text"])

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

    def test_deleting_a_question_thread_neither_reorders_projects_nor_resets_their_untouched_age(self):
        events = [
            _registered(1, self.OLD),
            _registered(2, self.NEW),
            _asked(3, self.OLD, "q1"),
        ]
        before = view.project_states(events)
        deletion = [_row(4, event_log.PROJECT_QUESTION_DELETED, self.OLD,
                         {"question_ids": ["q1"], "thread_id": "q1"})]
        after = view.project_states(deletion, before)
        self.assertEqual(after, view.project_states(events + deletion))
        self.assertEqual(after, before)
        self.assertEqual((after[self.OLD].last_seq, after[self.OLD].last_at), (1, "2026-11-17T10:00:01Z"))
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


class CredentialShapeTest(unittest.TestCase):
    def test_each_known_prefix_and_key_shape_is_caught_by_its_own_shape_alone(self):
        for name, token in FAKE_CREDENTIALS.items():
            with self.subTest(name=name):
                text = f"why does {token} fail?"
                matched = [n for n, p in project_question.CREDENTIAL_SHAPES if p.search(text)]
                self.assertEqual(matched, [name])
                self.assertIs(project_question.credential_shaped(text), True)
        self.assertEqual([n for n, _ in project_question.CREDENTIAL_SHAPES], list(FAKE_CREDENTIALS))
        self.assertIsNotNone(write_guard._TOKEN.fullmatch(FAKE_CREDENTIALS["console_token"] + "\n"))

    def test_a_password_assignment_in_any_case_or_quoting_is_caught_by_the_assignment_shape_alone(self):
        for text in (
            '{"password":"example123"}',
            '{"password": "copper-harbor-lantern"}',
            "PASSWORD=copper-harbor-lantern",
            "password = copper-harbor-lantern",
            "db_password: copper-harbor-9",
            "'secret': 'lantern-harbor'",
        ):
            with self.subTest(text=text):
                matched = [n for n, p in project_question.CREDENTIAL_SHAPES if p.search(text)]
                self.assertEqual(matched, ["assignment"])
                self.assertIs(project_question.credential_shaped(text), True)

    def test_a_base64_run_is_a_path_only_when_every_slash_separated_part_is_a_word(self):
        key = "Ab3/Xy9Qw8Er7/Ty6Ui5Op4As3/Df2Gh1Jk0LmNb"
        self.assertEqual(key.count("/"), 3)
        self.assertEqual([n for n, p in project_question.CREDENTIAL_SHAPES if p.search(key)], ["base64_run"])
        self.assertIs(project_question.credential_shaped(f"key {key} here"), True)
        path = "ProjectQuestion2Test/ReadingPanel3View/DeleteThread4Case"
        self.assertIs(project_question.credential_shaped(path), False)
        self.assertIs(project_question.credential_shaped("console/" + path), False)

    def test_a_console_token_of_any_character_mix_is_caught(self):
        alphabet = string.ascii_letters + string.digits + "-_"
        generator = random.Random(1272)
        tokens = ["AbCd" * 10 + "EfG", "Ab" * 21 + "C"]
        tokens += ["".join(generator.choices(alphabet, k=43)) for _ in range(500)]
        for token in tokens:
            with self.subTest(token=token):
                self.assertIsNotNone(write_guard._TOKEN.fullmatch(token + "\n"))
                self.assertIs(project_question.credential_shaped(f"is {token} right?"), True)

    def test_ordinary_text_with_similar_words_is_not_credential_shaped(self):
        texts = (
            "how do I rotate the GitHub token in HF_TOKEN?",
            "what does the ghp_ prefix mean?",
            "where is the AGE-SECRET-KEY kept?",
            "is a Bearer token sent by gh?",
            "password: is one needed for the sops file?",
            "What does HF_TOKEN: required mean?",
            "is GH_TOKEN=$(gh auth token) safe here?",
            "what did commit 8d2074d161ce5682ca14e8466d58bd679a07d308 merge?",
            "why is /nix/store/0c9bx8w5l6s2a1k3mzj4q7v9y2r8d1fh-claude-code-2.1.0 rebuilt?",
            "why is /nix/store/0c9bx8w5l6s2a1k3mzj4q7v9y2r8d1fh-SDL2-2.30.0 rebuilt?",
            "session 123e4567-e89b-12d3-a456-426614174000 failed",
            "does sk-learn run here?",
            "what does docs/areas/console/adr/062-a-follow-up-carries-its-thread say?",
            "why does the hash sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU= mismatch?",
            "is narHash sha512-" + "Ab1Cd2Ef3Gh4" * 7 + "== stale?",
            "where is console/ProjectQuestion2Test/ReadingPanel3View/DeleteThread4Case defined?",
            "what does MAX_PROJECT_QUESTION_DELETE_BYTES limit?",
            "what does tests.test_console_project_question.QuestionDeleteServiceTest cover?",
            "where is ProjectQuestion2Test/ReadingPanel3View/DeleteThread4Case defined?",
            "what does the token: required mean and why is password: required?",
            "why is the secret=true flag set?",
        )
        for text in texts:
            with self.subTest(text=text):
                self.assertIs(project_question.credential_shaped(text), False)


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

    def shown(self, svc):
        return {p["project_id"]: p for p in _project_entries(json.loads(svc.view_bytes))}[WHY]


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
        self.assertEqual(event_log.SCHEMA_VERSION, 12)

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

    def test_a_credential_shaped_question_or_follow_up_is_refused_and_nothing_of_it_is_kept(self):
        svc = self.start()
        first = svc.ask_project_question(WHY, "what does the build check?")
        before = self.question_rows()
        asked_before = len(self.asked)
        token = FAKE_CREDENTIALS["hugging_face"]
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            for args in ((WHY, f"my key is {token}"), (WHY, f"and {token}?", first)):
                with self.subTest(args=len(args)):
                    with self.assertRaises(project_question.Refused) as caught:
                        svc.ask_project_question(*args)
                    self.assertEqual(str(caught.exception), project_question.CREDENTIAL)
        self.assertEqual(self.question_rows(), before)
        self.assertEqual(len(self.asked), asked_before)
        self.assertEqual(svc._project_questions_open, 0)
        self.assertNotIn(token, errors.getvalue())
        for path in self.store.parent.glob(self.store.name + "*"):
            self.assertNotIn(token.encode(), path.read_bytes())

    def test_a_credential_is_refused_before_every_other_refusal(self):
        token = FAKE_CREDENTIALS["github"]
        svc = self.start()
        before = self.question_rows()

        def refused(service, *args):
            with self.assertRaises(project_question.Refused) as caught:
                service.ask_project_question(*args)
            self.assertEqual(str(caught.exception), project_question.CREDENTIAL)
            self.assertEqual(self.question_rows(), before)
            self.assertEqual(len(self.asked), 0)

        with self.subTest(case="unregistered"):
            refused(svc, "owner/p99", f"key {token}")
        with self.subTest(case="too long"):
            refused(svc, WHY, "x" * 2001 + " " + token)
        with self.subTest(case="unknown thread"):
            refused(svc, WHY, f"and {token}", "nope")
        with self.subTest(case="stopping"):
            svc._stop.set()
            refused(svc, WHY, f"key {token}")
        svc.close()
        with self.subTest(case="unavailable"):
            none = self.start(project_asker=None)
            refused(none, WHY, f"key {token}")

    def test_a_follow_up_to_a_thread_that_holds_a_credential_is_refused(self):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        log = event_log.EventLog(self.store)
        try:
            log.append([
                (event_log.PROJECT_QUESTION_ASKED, WHY, {
                    "question_id": "q0", "question": "my key " + FAKE_CREDENTIALS["hugging_face"],
                    "profile": "work", "session_id": SESSION_ID}),
                (event_log.PROJECT_QUESTION_ANSWERED, WHY, {
                    "question_id": "q0", "outcome": "answered", "answer": "Answer: noted."}),
                (event_log.PROJECT_QUESTION_ASKED, WHY, {
                    "question_id": "q5", "question": "what runs?", "profile": "work",
                    "session_id": SESSION_ID}),
                (event_log.PROJECT_QUESTION_ANSWERED, WHY, {
                    "question_id": "q5", "outcome": "answered",
                    "answer": "Answer: it echoed " + FAKE_CREDENTIALS["github"]})])
        finally:
            log.close()
        svc = self.start()
        before = self.question_rows()
        for thread, text in (("q0", "and what about darwin?"), ("q5", "and darwin?")):
            with self.subTest(thread=thread):
                with self.assertRaises(project_question.Refused) as caught:
                    svc.ask_project_question(WHY, text, thread)
                self.assertEqual(str(caught.exception), project_question.THREAD_CREDENTIAL)
        self.assertEqual(self.asked, [])
        self.assertEqual(self.question_rows(), before)

    def test_questions_survive_a_restart(self):
        svc = self.start()
        svc.ask_project_question(WHY, "what does the build check?")
        svc.close()
        again = self.start()
        (question,) = [q for t in self.shown(again)["questions"]["threads"] for q in t["questions"]]
        self.assertEqual(question["state"], "answered")


def question_threads():
    return [t for t in threading.enumerate() if t.name == service.PROJECT_QUESTION_THREAD]


class QuestionRecordsServiceTest(QuestionCase):
    """The job gathers the asked project's own records once per accepted question (ADR-console-089)."""

    def seed(self):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        log = event_log.EventLog(self.store)
        run = {"session_id": "s-1", "run_id": "wf_a", "moved_ms": 1700000000000,
               "issues": [{"issue": 7, "stage": "building", "task": 2, "tasks": 3, "locking": False}]}
        other = {"session_id": "s-0", "run_id": "wf_b", "moved_ms": 1700000000000,
                 "issues": [{"issue": 9, "stage": "queued", "task": None, "tasks": None,
                             "locking": False}]}
        entries = [("project.registered", "owner/p01", {"root": "/srv/p01"}),
                   (deliveries.DELIVERY_SEEN, "owner/p01", run),
                   (deliveries.DELIVERY_SEEN, "owner/p00", other)]
        for root, commit in (("/srv/p01", "c" * 40), ("/srv/p00", "d" * 40)):
            entries.append((event_log.ACTIVATION_STARTED, None,
                            {"root": root, "commit": commit, "tree": "group:1"}))
            entries.append((event_log.ACTIVATION_FINISHED, None,
                            {"root": root, "commit": commit, "ok": False, "reason": "it exited 1",
                             "next_step": None}))
        log.append(entries)
        log.close()

    def arrange(self, with_spend=True, **kwargs):
        self.seed()
        svc = self.start(**kwargs)

        def sprint(sprint_id, project, goal, seq):
            return sprints.SprintState(sprint_id, project, goal, seq, f"2026-11-17T08:00:0{seq}+00:00")

        def held(project, issue):
            return view.InboxRecord(
                {"key": f"{project}#{issue}/1", "issue": issue, "reason": "verify-ask", "kind": "ask",
                 "question": "q", "detail": ""}, "2026-11-17T08:00:00+00:00", "2026-11-17T08:00:00+00:00")

        svc._sprints = {"1111111111111111": sprint("1111111111111111", "owner/p01", "g1. More.", 1),
                        "0000000000000000": sprint("0000000000000000", "owner/p00", "g0. More.", 2)}
        svc._inbox = {("owner/p01", "owner/p01#7/1"): held("owner/p01", 7),
                      ("owner/p00", "owner/p00#9/1"): held("owner/p00", 9)}
        if with_spend:
            tokens = lambda n: spend.Tokens(input=n).wire()
            svc._spend_view = {"approximate": False, "days": [{
                "day": "2026-11-17",
                "project": {"owner/p01": tokens(13), "owner/p00": tokens(905)},
                "project_items": {
                    "owner/p01": {"run": {"wf_a": {"implement": tokens(10)}},
                                  "sprint": {"1111111111111111": {"manager": tokens(3)}}},
                    "owner/p00": {"run": {"wf_a": {"plan": tokens(900)}, "wf_b": {"plan": tokens(5)}}}}}]}
        return svc

    def records_of(self, svc):
        before = len(self.asked)
        svc.ask_project_question(WHY, "what costs the most tokens per issue?")
        ask, _cancel = self.asked[before]
        return ask, json.loads(ask.records)

    def test_a_questions_session_reads_only_its_own_projects_records(self):
        svc = self.arrange()
        (rows_before) = len(self.question_rows())
        ask, records = self.records_of(svc)
        self.assertEqual(records["project_id"], WHY)
        self.assertEqual([d["run_id"] for d in records["deliveries"]], ["wf_a"])
        self.assertIs(records["deliveries"][0]["live"], False)
        self.assertEqual([(r["run_id"], r["tokens"]) for r in records["spend"]["runs"]], [("wf_a", 10)])
        self.assertEqual([i["issue"] for i in records["spend"]["issues"]], [7])
        self.assertEqual([s["sprint_id"] for s in records["sprints"]], ["1111111111111111"])
        self.assertEqual([s["sprint_id"] for s in records["spend"]["sprints"]], ["1111111111111111"])
        self.assertEqual([a["commit"] for a in records["activations"]], ["c" * 40])
        self.assertEqual([h["issue"] for h in records["held_checks"]], [7])
        for other in ("owner/p00", "wf_b", "0000000000000000", "/srv/p00", "d" * 40, "s-0"):
            self.assertNotIn(other, ask.records)
        self.assertEqual([r[0] for r in self.question_rows()][rows_before:], [ASKED, ANSWERED_KIND])
        self.assertEqual(len(self.question_rows()), rows_before + 2)

    def test_the_events_are_read_under_the_lock_that_guards_the_folded_state(self):
        svc = self.arrange()
        real = svc.log.events
        got = []

        def events():
            taken = []

            def take():
                taken.append(svc._ingest.acquire(timeout=0.3))
                if taken[0]:
                    svc._ingest.release()

            worker = threading.Thread(target=take)
            worker.start()
            worker.join()
            got.extend(taken)
            return real()

        with mock.patch.object(svc.log, "events", events):
            self.records_of(svc)
        self.assertTrue(got)
        self.assertFalse(any(got))

    def test_a_run_is_live_only_while_its_session_is_open_in_this_project(self):
        svc = self.arrange()
        open_session = sessions.SessionState(
            "s-1", "/srv/p01", "/srv/p01", sessions.WORKING, None, 1, "2026-11-17T08:00:01+00:00", None)
        svc._sessions = {"s-1": open_session}
        _ask, records = self.records_of(svc)
        self.assertIs(records["deliveries"][0]["live"], True)
        for name, change in (("ended", {"state": sessions.ENDED}),
                             ("moved to another project", {"repo": "/srv/p00"}),
                             ("no repository", {"repo": None})):
            with self.subTest(name):
                svc._sessions = {"s-1": dataclasses.replace(open_session, **change)}
                _ask, records = self.records_of(svc)
                self.assertIs(records["deliveries"][0]["live"], False)

    def test_a_question_before_the_first_spend_poll_gets_its_projects_spend(self):
        now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc).timestamp()
        sessions = self.store.parent.parent / "sessions"
        run = sessions.parent / "projects" / "-srv-p01" / "s-1" / "subagents" / "workflows" / "wf_a"
        run.mkdir(parents=True)
        journal = run / "journal.jsonl"
        journal.write_text(json.dumps(
            {"type": "started", "agentId": "a1", "label": "impl-1", "phase": "Tasks"}) + "\n")
        agent = run / "agent-a1.jsonl"
        agent.write_text(json.dumps(
            {"type": "assistant", "sessionId": "s-1", "cwd": "/srv/p01",
             "timestamp": "2026-11-17T10:00:00.000Z",
             "message": {"id": "msg_r1", "model": "claude-sonnet-4-6",
                         "usage": {"input_tokens": 40}}}) + "\n")
        for path in (journal, agent):
            os.utime(path, (now, now))
        svc = self.arrange(with_spend=False, session_dirs=[sessions], clock=lambda: now)
        _ask, records = self.records_of(svc)
        held = records["spend"]
        self.assertIsNotNone(held)
        self.assertEqual(held["days"][-1]["day"], "2026-11-17")
        self.assertEqual(held["days"][-1]["tokens"], 40)
        self.assertEqual([(r["run_id"], r["tokens"]) for r in held["runs"]], [("wf_a", 40)])
        self.assertEqual(held["runs"][0]["phases"]["implement"]["tokens"], 40)
        self.assertEqual(list(held["runs"][0]["days"]), ["2026-11-17"])
        self.assertEqual(held["runs"][0]["days"]["2026-11-17"]["tokens"], 40)
        self.assertEqual([i["issue"] for i in held["issues"]], [7])

    def test_the_jobs_spend_read_runs_under_the_spend_lock_and_only_without_a_view(self):
        svc = self.arrange(with_spend=False)
        held = []
        real = svc._spend.read

        def read(*args, **kwargs):
            held.append(svc._spend_lock.locked())
            return real(*args, **kwargs)

        with mock.patch.object(svc._spend, "read", side_effect=read):
            self.records_of(svc)
            self.records_of(svc)
        self.assertEqual(held, [True])

    def test_a_direct_poll_spend_runs_under_the_spend_lock(self):
        svc = self.arrange(with_spend=False)
        held = []
        real = svc._spend.read

        def read(*args, **kwargs):
            held.append(svc._spend_lock.locked())
            return real(*args, **kwargs)

        with mock.patch.object(svc._spend, "read", side_effect=read):
            svc.poll_spend()
        self.assertEqual(held, [True])

    def test_questions_started_together_before_the_first_poll_share_one_spend_read(self):
        threads = []

        def dispatch(job):
            thread = threading.Thread(target=job)
            threads.append(thread)
            thread.start()

        svc = self.arrange(with_spend=False, project_question_dispatch=dispatch)

        class Recording:
            lock = svc._spend_lock
            attempts = []
            both = threading.Event()

            def __enter__(self):
                self.attempts.append(1)
                if len(self.attempts) == 2:
                    self.both.set()
                self.lock.acquire()

            def __exit__(self, *exc):
                self.lock.release()

            def locked(self):
                return self.lock.locked()

        svc._spend_lock = Recording()
        entered, release = threading.Event(), threading.Event()
        reads = []
        real = svc._spend.read

        def read(*args, **kwargs):
            reads.append(1)
            if len(reads) == 1:
                entered.set()
                release.wait(5)
            return real(*args, **kwargs)

        with mock.patch.object(svc._spend, "read", side_effect=read):
            svc.ask_project_question(WHY, "what costs the most tokens per issue?")
            self.assertTrue(entered.wait(5))
            svc.ask_project_question("owner/p00", "what costs the most tokens per issue?")
            self.assertTrue(svc._spend_lock.both.wait(5))
            release.set()
            for thread in threads:
                thread.join(timeout=5)
        self.assertEqual(reads, [1])
        self.assertEqual(len(self.asked), 2)
        for ask, _cancel in self.asked:
            self.assertIsNotNone(json.loads(ask.records)["spend"])

    def test_a_spend_read_that_fails_leaves_null_spend_and_the_rest_written(self):
        svc = self.arrange(with_spend=False)
        stderr = io.StringIO()
        with mock.patch.object(svc._spend, "read", side_effect=OSError(5, "boom")), \
                contextlib.redirect_stderr(stderr):
            ask, records = self.records_of(svc)
        self.assertIsNone(records["spend"])
        self.assertTrue(records["deliveries"])
        self.assertTrue(any(line.startswith("console: spend_poll_failed OSError")
                            for line in stderr.getvalue().splitlines()))
        self.assertIs(ask, self.asked[-1][0])

    def test_a_cold_start_whose_transcript_root_cannot_be_listed_leaves_null_spend_not_zero_days(self):
        svc = self.arrange(with_spend=False)
        root = Path("/accounts/profiles/work")

        def denied(directory):
            raise PermissionError(13, "denied")

        svc._spend = spend.SpendReader(scandir=denied)
        stderr = io.StringIO()
        with mock.patch.object(svc, "_session_dirs", return_value=[root / "sessions"]), \
                contextlib.redirect_stderr(stderr):
            ask, records = self.records_of(svc)
        self.assertIsNone(records["spend"])
        self.assertIsNone(svc._spend_view)
        self.assertTrue(any(line.startswith("console: spend_poll_failed OSError")
                            for line in stderr.getvalue().splitlines()))
        self.assertTrue(records["deliveries"])

    def test_a_warm_service_whose_transcript_root_cannot_be_listed_keeps_its_spend_view(self):
        svc = self.arrange()
        before = svc._spend_view
        root = Path("/accounts/profiles/work")

        def denied(directory):
            raise PermissionError(13, "denied")

        svc._spend = spend.SpendReader(scandir=denied)
        with mock.patch.object(svc, "_session_dirs", return_value=[root / "sessions"]):
            svc.poll_spend()
        self.assertIsNotNone(svc._spend_view)

    def test_the_support_service_reads_no_host_ping_log(self):
        svc = self.arrange(with_spend=False)
        self.assertIsNot(svc._ping_log, spend.default_ping_log)
        self.assertIsNone(svc._ping_log())

    def test_records_that_cannot_be_gathered_answer_failed_without_a_session(self):
        svc = self.arrange()
        stderr = io.StringIO()
        with mock.patch("agent_tools.console.question_records.project_records",
                        side_effect=RuntimeError("boom")), contextlib.redirect_stderr(stderr):
            qid = svc.ask_project_question(WHY, "why?")
        self.assertEqual(self.asked, [])
        self.assertEqual(self.question_rows()[-1][2], {
            "question_id": qid, "outcome": "failed",
            "reason": "the console's records could not be gathered: RuntimeError: boom"})
        self.assertIn("console: project_question_records_failed " + qid, stderr.getvalue())
        self.assertEqual(svc._project_questions_open, 0)

    def test_a_checkout_taken_by_another_project_before_the_gathering_answers_failed(self):
        svc = self.arrange()
        gather = mock.Mock()
        real = svc._project_reach

        def reach(root):
            found = real(root)
            # Another project takes the root after the question was admitted and before its records are gathered.
            svc._states = {**svc._states, WHY: dataclasses.replace(svc._states[WHY], root="/srv/elsewhere")}
            return found

        svc._project_reach = reach
        stderr = io.StringIO()
        with mock.patch("agent_tools.console.question_records.project_records", gather), \
                contextlib.redirect_stderr(stderr):
            qid = svc.ask_project_question(WHY, "why?")
        gather.assert_not_called()
        self.assertEqual(self.asked, [])
        self.assertTrue(self.question_rows()[-1][2]["reason"].startswith(
            "the console's records could not be gathered: RuntimeError:"))
        self.assertIn("console: project_question_records_failed " + qid, stderr.getvalue())
        self.assertEqual(svc._project_questions_open, 0)

    def test_a_contract_that_cannot_be_resolved_gathers_no_records(self):
        def unreadable(root):
            raise ValueError("bad")

        svc = self.arrange(project_reach=unreadable)
        gather = mock.Mock()
        with mock.patch("agent_tools.console.question_records.project_records", gather), \
                contextlib.redirect_stderr(io.StringIO()):
            svc.ask_project_question(WHY, "why?")
        gather.assert_not_called()
        self.assertEqual(self.asked, [])
        self.assertTrue(self.question_rows()[-1][2]["reason"].startswith(
            "the project's contract could not be resolved"))


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
            "and which host is deployed?", ROUTES, follow_ask.thread, repo="owner/p01",
            records=str(project_question.records_path(follow_ask)),
            sections=question_records.section_lines(follow_ask.records)))
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


class QuestionDeleteServiceTest(QuestionCase):
    """The owner deletes a question thread; the log keeps a record of the ids and nothing of the text."""

    def test_deleting_a_thread_removes_its_text_from_the_log_and_the_view_and_keeps_a_text_free_record(self):
        svc = self.start()
        self.outcome = project_question.Outcome("answered", answer="Answer: FIRST-ANSWER-TEXT")
        first = svc.ask_project_question(WHY, "FIRST-QUESTION-TEXT?")
        self.outcome = project_question.Outcome("answered", answer="Answer: FOLLOW-ANSWER-TEXT")
        follow = svc.ask_project_question(WHY, "FOLLOW-QUESTION-TEXT?", first)
        self.outcome = project_question.Outcome("answered", answer="Answer: OTHER-ANSWER-TEXT")
        other = svc.ask_project_question(WHY, "OTHER-QUESTION-TEXT?")
        svc.delete_question_thread(WHY, first)
        rows = self.question_rows()
        self.assertEqual(rows[-1], (
            "project_question.deleted", WHY, {"question_ids": [first, follow], "thread_id": first}))
        self.assertEqual(
            [row for row in rows if row[2].get("question_id") in (first, follow)], [])
        self.assertEqual([row[0] for row in rows if row[2].get("question_id") == other],
                         [ASKED, ANSWERED_KIND])
        self.assertEqual([t["id"] for t in self.shown(svc)["questions"]["threads"]], [other])
        svc.close()
        gone = (b"FIRST-QUESTION-TEXT", b"FIRST-ANSWER-TEXT", b"FOLLOW-QUESTION-TEXT",
                b"FOLLOW-ANSWER-TEXT")
        for path in self.store.parent.glob(self.store.name + "*"):
            for text in gone:
                with self.subTest(path=path.name, text=text):
                    self.assertNotIn(text, path.read_bytes())
        restarted = self.start()
        self.assertEqual([t["id"] for t in self.shown(restarted)["questions"]["threads"]], [other])

    def test_a_delete_names_a_registered_project_and_one_of_its_threads(self):
        svc = self.start()
        first = svc.ask_project_question(WHY, "why?")
        follow = svc.ask_project_question(WHY, "and?", first)
        for project, thread, reason in (
                ("owner/p99", first, project_question.UNREGISTERED),
                (WHY, follow, project_question.THREAD_UNKNOWN),
                (WHY, "nope", project_question.THREAD_UNKNOWN)):
            with self.subTest(project=project, thread=thread):
                before = self.question_rows()
                with self.assertRaises(project_question.Refused) as caught:
                    svc.delete_question_thread(project, thread)
                self.assertEqual(str(caught.exception), reason)
                self.assertEqual(self.question_rows(), before)

    def test_a_thread_still_being_answered_is_deleted_only_once_its_answer_is_in(self):
        svc = self.start(project_question_dispatch=self.queued.append)
        try:
            first = svc.ask_project_question(WHY, "why?")
            before = self.question_rows()
            with self.assertRaises(project_question.Refused) as caught:
                svc.delete_question_thread(WHY, first)
            self.assertEqual(str(caught.exception), project_question.THREAD_WORKING)
            self.assertEqual(self.question_rows(), before)
            self.queued.pop()()
            svc.delete_question_thread(WHY, first)
            self.assertIsNone(self.shown(svc)["questions"])
        finally:
            while self.queued:
                self.queued.pop()()

    def test_a_question_left_working_by_a_crash_can_be_deleted(self):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        log = event_log.EventLog(self.store)
        try:
            log.append([(event_log.PROJECT_QUESTION_ASKED, WHY, {
                "question_id": "q0", "question": "LEFT-WORKING-TEXT", "profile": "work",
                "session_id": SESSION_ID})])
        finally:
            log.close()
        svc = self.start()
        svc.delete_question_thread(WHY, "q0")
        svc.close()
        for path in self.store.parent.glob(self.store.name + "*"):
            self.assertNotIn(b"LEFT-WORKING-TEXT", path.read_bytes())

    def test_a_follow_up_to_a_deleted_thread_is_refused(self):
        svc = self.start()
        first = svc.ask_project_question(WHY, "why?")
        svc.delete_question_thread(WHY, first)
        with self.assertRaises(project_question.Refused) as caught:
            svc.ask_project_question(WHY, "and?", first)
        self.assertEqual(str(caught.exception), project_question.THREAD_UNKNOWN)
        self.assertEqual(len(self.asked), 1)

    def test_a_keyed_question_replays_its_receipt_after_its_thread_is_deleted_and_a_restart(self):
        key = "0123456789abcdef" * 2
        svc = self.start()
        first = svc.ask_project_question(WHY, "q?", request_key=key)
        svc.delete_question_thread(WHY, first)
        self.assertEqual(svc.ask_project_question(WHY, "q?", request_key=key), first)
        with self.assertRaises(project_question.Refused) as caught:
            svc.ask_project_question(
                WHY, f"key {FAKE_CREDENTIALS['github']}", request_key=key)
        self.assertEqual(str(caught.exception), project_question.CREDENTIAL)
        self.assertEqual(len(self.asked), 1)
        rows = self.question_rows()
        self.assertIn(("project_question.keyed", WHY, {"request_key": key, "question_id": first}),
                      rows)
        self.assertNotIn(ASKED, [row[0] for row in rows])
        svc.close()
        restarted = self.start()
        self.assertEqual(restarted.ask_project_question(WHY, "q?", request_key=key), first)
        self.assertEqual(len(self.asked), 1)


class QuestionRequestKeyTest(QuestionCase):
    """A request may carry a key the console asks once per project (ADR-console-089 D9)."""

    KEY = "0123456789abcdef" * 2

    def test_a_keyed_body_is_parsed_and_a_bad_key_is_refused(self):
        def body(**extra):
            return json.dumps({"project_id": "p", "question": "q", **extra}).encode()
        self.assertEqual(project_question.parse_keyed_request(body(request_key=self.KEY)),
                         ("p", "q", None, self.KEY))
        self.assertEqual(project_question.parse_request(body(request_key=self.KEY)), ("p", "q", None))
        for key in (self.KEY[:31], self.KEY.upper(), 12, None):
            with self.subTest(key=key), self.assertRaises(ValueError):
                project_question.parse_keyed_request(body(request_key=key))

    def test_a_credential_under_a_known_request_key_is_refused(self):
        svc = self.start()
        first = svc.ask_project_question(WHY, "q?", request_key=self.KEY)
        before = self.question_rows()
        with self.assertRaises(project_question.Refused) as caught:
            svc.ask_project_question(WHY, f"key {FAKE_CREDENTIALS['github']}",
                                     request_key=self.KEY)
        self.assertEqual(str(caught.exception), project_question.CREDENTIAL)
        self.assertNotEqual(first, "")
        self.assertEqual(self.question_rows(), before)
        self.assertEqual(len(self.asked), 1)

    def test_a_repeated_key_asks_once(self):
        svc = self.start()
        first = svc.ask_project_question(WHY, "q?", request_key=self.KEY)
        second = svc.ask_project_question(WHY, "q?", request_key=self.KEY)
        self.assertEqual(first, second)
        self.assertEqual(len(self.asked), 1)
        asked, keyed, answered = self.question_rows()
        self.assertEqual((asked[0], asked[2]["request_key"], answered[0]),
                         ("project_question.asked", self.KEY, "project_question.answered"))
        self.assertEqual((keyed[0], keyed[1], keyed[2]), (
            "project_question.keyed", WHY, {"request_key": self.KEY, "question_id": first}))
        shown = {p["project_id"]: p for p in _project_entries(json.loads(svc.view_bytes))}[WHY]
        (question,) = [q for t in shown["questions"]["threads"] for q in t["questions"]
                       if q["id"] == first]
        self.assertEqual(question["request_key"], self.KEY)

    def test_a_resent_keyed_follow_up_is_the_same_question(self):
        held = []
        svc = self.start(project_question_dispatch=held.append)
        try:
            first = svc.ask_project_question(WHY, "q?")
            held.pop()()
            follow = svc.ask_project_question(WHY, "and?", thread_id=first, request_key=self.KEY)
            again = svc.ask_project_question(WHY, "and?", thread_id=first, request_key=self.KEY)
            self.assertEqual(again, follow)
            self.assertEqual((len(held), len(self.asked), svc._project_questions_open), (1, 1, 1))
        finally:
            while held:
                held.pop()()
        self.assertEqual((len(self.asked), svc._project_questions_open), (2, 0))

    def test_the_same_key_on_another_project_is_its_own_question(self):
        svc = self.start()
        one = svc.ask_project_question("owner/p00", "q?", request_key=self.KEY)
        two = svc.ask_project_question("owner/p01", "q?", request_key=self.KEY)
        self.assertNotEqual(one, two)
        self.assertEqual(len(self.asked), 2)

    def test_a_key_still_finds_its_question_after_retention_removed_the_asked_row(self):
        now = [T0]
        svc = self.start(**_clocks(now))
        first = svc.ask_project_question(WHY, "q?", request_key=self.KEY)
        now[0] = T0 + 91 * 86400
        self.assertGreaterEqual(svc.retain(), 2)
        self.assertEqual([row[0] for row in self.question_rows()], ["project_question.keyed"])
        self.assertEqual(svc._project_questions, {})
        again = svc.ask_project_question(WHY, "q?", request_key=self.KEY)
        self.assertEqual(again, first)
        self.assertEqual(len(self.asked), 1)
        svc.close()
        restarted = self.start(**_clocks(now))
        self.assertEqual(restarted.ask_project_question(WHY, "q?", request_key=self.KEY), first)
        other = restarted.ask_project_question("owner/p00", "q?", request_key=self.KEY)
        self.assertNotEqual(other, first)
        self.assertEqual(len(self.asked), 2)

    def test_the_receipt_does_not_move_its_project_in_the_desk(self):
        svc = self.start()
        before = svc._states[WHY].last_seq
        svc.ask_project_question(WHY, "q?", request_key=self.KEY)
        rows = support.log_rows(self.store)
        keyed = [row for row in rows if row[2] == "project_question.keyed"]
        self.assertEqual(len(keyed), 1)
        self.assertEqual(svc._states[WHY].last_seq, before)

    def test_the_route_passes_the_request_key(self):
        svc = self.start()
        payload = json.dumps(
            {"project_id": WHY, "question": "why?", "request_key": self.KEY}).encode()
        status, _, body = support.post_page(
            svc.address, QUESTION_ROUTE, self.own(svc, **JSON), payload)
        self.assertEqual((status, body), (204, b""))
        asked = self.question_rows()[0]
        self.assertEqual((asked[0], asked[2]["request_key"]), ("project_question.asked", self.KEY))

    def test_a_question_without_a_key_has_the_row_it_had(self):
        svc = self.start()
        svc.ask_project_question(WHY, "q?")
        self.assertEqual(set(self.question_rows()[0][2]),
                         {"question_id", "question", "profile", "session_id"})


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

    def test_the_route_refuses_a_credential_with_409_and_keeps_nothing(self):
        svc = self.start()
        token = FAKE_CREDENTIALS["github"]
        body = {"project_id": WHY, "question": f"why does {token} fail?"}
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            got = self.assert_unchanged(svc, lambda: self.post(svc, body, self.own(svc, **JSON)))
        self.assertEqual((got[0], got[2]), (409, (project_question.CREDENTIAL + "\n").encode()))
        self.assertEqual(self.asked, [])
        self.assertEqual(
            errors.getvalue(), f"console: project_question_refused {project_question.CREDENTIAL}\n")
        self.assertNotIn(token, errors.getvalue())

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


class QuestionDeleteRouteTest(QuestionCase):
    def post(self, svc, body, headers):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        return support.post_page(svc.address, service.PROJECT_QUESTION_DELETE_PATH, headers, payload)

    def test_the_delete_route_deletes_with_204_and_refuses_what_it_cannot_read(self):
        svc = self.start()
        first = svc.ask_project_question(WHY, "why?")
        cases = (
            ({"project_id": WHY}, 400, b"bad delete\n"),
            ({"project_id": WHY, "thread_id": first, "x": 1}, 400, b"bad delete\n"))
        for body, status, text in cases:
            with self.subTest(body=body):
                got = self.assert_unchanged(
                    svc, lambda: self.post(svc, body, self.own(svc, **JSON)))
                self.assertEqual((got[0], got[2]), (status, text))
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            got = self.assert_unchanged(svc, lambda: self.post(
                svc, {"project_id": WHY, "thread_id": "nope"}, self.own(svc, **JSON)))
        self.assertEqual((got[0], got[2]),
                         (409, (project_question.THREAD_UNKNOWN + "\n").encode()))
        self.assertEqual(errors.getvalue(),
                         f"console: project_question_delete_refused {project_question.THREAD_UNKNOWN}\n")
        status, _, body = self.post(
            svc, {"project_id": WHY, "thread_id": first}, self.own(svc, **JSON))
        self.assertEqual((status, body), (204, b""))
        self.assertIsNone(self.shown(svc)["questions"])

    def test_the_delete_route_is_an_owner_only_page_write_that_takes_only_post(self):
        svc = self.start()
        route = service.PROJECT_QUESTION_DELETE_PATH
        self.assertIn(route, service.PAGE_WRITES)
        self.assertIn(route, service.OWNER_ONLY)
        self.assertNotIn(route, service.GUEST_WRITES)
        for method in ("GET", "PUT", "DELETE"):
            with self.subTest(method=method):
                status, headers, _ = support.request(svc.address, method, route)
                self.assertEqual((status, headers["Allow"]), (405, "POST"))
        first = svc.ask_project_question(WHY, "why?")
        origin = f"http://127.0.0.1:{svc.address[1]}"
        got = self.assert_unchanged(svc, lambda: self.post(
            svc, {"project_id": WHY, "thread_id": first}, {"Origin": origin, **JSON}))
        self.assertEqual((got[0], got[2]), (403, b"token refused\n"))
