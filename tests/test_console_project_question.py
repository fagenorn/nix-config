"""The console's project question session (#1176): hook, launch, service and route.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from agent_tools.console import project_question, project_question_hook as hook
from agent_tools.project_contract import resolve_project
from agent_tools.system import siblings

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

DECLARED = (("just", "build"),)
ROUTES = (project_question.Route("nix-build", ("just", "build"), "/srv/p01"),)
ENVIRON = {"HOME": "/home/u", "PATH": "/bin"}
SUCCESS = (
    b'{"type":"result","subtype":"success","is_error":false,'
    b'"result":" Answer: it builds the hosts. "}'
)


def SNAPSHOT(read_only, cwd_of=lambda id: "/srv/p01", root="/srv/p01"):  # noqa: N802 -- a fixture
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
        }},
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
        ):
            rows.append((bash(command), DECLARED, lifecycle))
        rows.append((bash("git push"), (("git", "push"),), lifecycle))
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

    def test_with_no_declared_command_every_shell_command_is_denied(self):
        denied = ("deny", hook.NO_COMMANDS)
        self.assertEqual(hook.decide(bash("just build"), ()), denied)
        self.assertEqual(hook.decide(bash("ls"), ()), denied)
        self.assertEqual(hook.decide(tool("Read"), ()), ("allow", hook.ALLOWED))

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
        args = ['[["just","build"]]']
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

    def test_a_bad_argument_denies_everything(self):
        read = json.dumps(tool("Read", {"file_path": "/x"}))
        deep = "[" * 100000  # under the 128 KiB limit of one argv word
        for args, stdin_text in (
            ([], read),
            (["not json"], read),
            (['[["just","build"]]'], "{"),
            (['[["just","build"]]'], deep),
            ([deep], read),
        ):
            with self.subTest(args=args, stdin=stdin_text):
                done = self.run_hook(args, stdin_text)
                self.assertEqual(done.returncode, 0)
                self.assertEqual(json.loads(done.stdout), self.wire("deny", hook.MALFORMED))
                self.assertEqual(len(done.stdout.splitlines()), 1)


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
            routes, self.settings_dir)

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

    def test_the_launch_runs_sonnet_headless_in_the_root_under_the_chosen_profile(self):
        outcome = self.start(self.fake())

        argv, timeout, _cancel, kwargs = self.calls[0]
        self.assertEqual(argv, [
            "claude-account", "run", "-p", "--model", "sonnet", "--permission-mode", "dontAsk",
            "--setting-sources", "", "--strict-mcp-config", "--tools", "Read,Grep,Glob,Bash",
            "--output-format", "json", "--settings", str(self.ask.settings),
            project_question.prompt(self.ask.question, self.routes)])
        self.assertEqual(timeout, 300)
        self.assertEqual(kwargs["cwd"], str(self.root))
        self.assertEqual(kwargs["env"]["CLAUDE_ACCOUNT"], "work")
        self.assertTrue(kwargs["env"]["PATH"].startswith("/home/u/.agents/bin"))
        self.assertIs(kwargs["start_new_session"], True)
        self.assertEqual(outcome, project_question.Outcome("answered", answer="Answer: it builds the hosts."))

    def test_the_settings_file_denies_writes_and_lifecycle_verbs_and_blocks_on_hook_failure(self):
        self.start(self.fake())

        document = json.loads(self.settings["text"])
        self.assertEqual(document["permissions"], {
            "defaultMode": "dontAsk",
            "allow": ["Read", "Grep", "Glob", "Bash(just build)"],
            "deny": ["Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Agent",
                     "Bash(git push:*)", "Bash(gh pr create:*)", "Bash(gh pr merge:*)",
                     "Bash(git branch -d:*)", "Bash(gh release create:*)"],
        })
        hooks = document["hooks"]["PreToolUse"][0]["hooks"][0]
        self.assertEqual(document["hooks"], {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": hooks["command"], "timeout": 10, "onFailure": "block"}]}]})
        self.assertEqual(shlex.split(hooks["command"]), [
            *siblings.sibling_argv("console.project_question_hook"), '[["just","build"]]'])
        self.assertEqual(self.settings["mode"], 0o600)
        self.assertEqual(self.settings["parent_mode"], 0o700)
        self.assertFalse(self.ask.settings.exists())

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
                project_question.routes_of(path)

    def test_a_contract_with_no_read_only_command_gets_the_production_line(self):
        for snapshot in (SNAPSHOT([]), {**SNAPSHOT([]), "production": {"status": "none"}},
                         {**SNAPSHOT([]), "production": {"status": "not_declared"}}):
            self.assertEqual(project_question.read_only_routes(snapshot), ())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            ask = project_question.new_ask(
                "b" * 16, "owner/p01", str(root), "why?", "work", (), Path(directory) / "settings")
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
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob")
        self.assertIn("This project declares no read-only command, so production cannot be read", argv[-1])
        hook_command = seen["settings"]["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertEqual(shlex.split(hook_command)[-1], "[]")
        self.assertEqual(seen["settings"]["permissions"]["allow"], ["Read", "Grep", "Glob"])

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
            ("owner/p01", "why?"))
        for body in (b'{"project_id":"owner/p01"}', b'{"project_id":"","question":"q"}',
                     b'{"project_id":"p","question":1}',
                     b'{"project_id":"p","project_id":"q","question":"q"}', b"[1]"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                project_question.parse_request(body)

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

            routes = project_question.routes_of(str(link), resolve=resolve)
        self.assertEqual(seen, [str(link)])
        self.assertEqual(routes, (project_question.Route("nix-build", ("just", "build"), str(real)),))


if __name__ == "__main__":
    unittest.main()
