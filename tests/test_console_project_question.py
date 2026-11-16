"""The console's project question session (#1176): hook, launch, service and route.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from agent_tools.console import project_question_hook as hook

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

DECLARED = (("just", "build"),)


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
        for args, stdin_text in (([], read), (["not json"], read), (['[["just","build"]]'], "{")):
            with self.subTest(args=args, stdin=stdin_text):
                done = self.run_hook(args, stdin_text)
                self.assertEqual(done.returncode, 0)
                self.assertEqual(json.loads(done.stdout), self.wire("deny", hook.MALFORMED))
                self.assertEqual(len(done.stdout.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
