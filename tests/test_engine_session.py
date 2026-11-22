"""Contract tests for the engine's session reading (`agent_tools.delivery.engine_session`, #1514).

Covers reading a role file, rendering a prompt, reading a session result, building the
launcher argv and starting one session.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_tools.delivery.engine_session import (
    NOT_STARTED, Reading, Role, RoleError, diagnostic, launch, launch_argv, read_result,
    read_role, render_prompt,
)

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / "home/common/claude-code/agents"
ZERO_TOKENS = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
DENIAL = {"tool_name": "Write", "tool_use_id": "toolu_01",
          "tool_input": {"file_path": "/etc/hosts"}}
RESULT = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 12345,
          "num_turns": 7, "result": "Status: stuck. I could not draft it.", "session_id": "x",
          "total_cost_usd": 0.4321,
          "usage": {"input_tokens": 11, "cache_creation_input_tokens": 22,
                    "cache_read_input_tokens": 33, "output_tokens": 44},
          "permission_denials": [DENIAL],
          "structured_output": {"status": "drafted", "summary": "s", "items": []}}


def raw(**overrides) -> bytes:
    document = dict(RESULT)
    document.update(overrides)
    return json.dumps({key: value for key, value in document.items()
                       if value is not ...}).encode()


class ReadResultTest(unittest.TestCase):
    def test_a_normal_result_gives_its_reply_prose_denials_and_measurements(self):
        self.assertEqual(read_result(json.dumps(RESULT).encode()), Reading(
            reply={"status": "drafted", "summary": "s", "items": []},
            prose="Status: stuck. I could not draft it.", denials=[DENIAL],
            subtype="success", wall_seconds=12.345, turns=7,
            tokens={"input": 11, "cache_write": 22, "cache_read": 33, "output": 44},
            spend_usd=0.4321))

    def test_no_structured_output_gives_no_reply_but_keeps_prose_and_measurements(self):
        reading = read_result(raw(structured_output=...))
        self.assertIsNone(reading.reply)
        self.assertEqual(reading.prose, "Status: stuck. I could not draft it.")
        self.assertEqual(reading.turns, 7)
        for value in (None, [1], "drafted"):
            with self.subTest(value=value):
                self.assertIsNone(read_result(raw(structured_output=value)).reply)

    def test_unreadable_stdout_reads_as_nothing(self):
        nothing = Reading(None, None, [], None, None, 0, dict(ZERO_TOKENS), 0)
        for stdout in (b"", b"not json", b"[1]", b'{"a":1,"a":2}',
                       b'{"num_turns":3,"num_turns":4}', b'{"num_turns":3,"total_cost_usd":NaN}'):
            with self.subTest(stdout=stdout):
                self.assertEqual(read_result(stdout), nothing)

    def test_nesting_too_deep_to_parse_reads_as_nothing(self):
        nothing = Reading(None, None, [], None, None, 0, dict(ZERO_TOKENS), 0)
        self.assertEqual(read_result(b"[" * 100000), nothing)

    def test_an_integer_too_large_for_a_float_reads_as_an_invalid_measurement(self):
        huge = b"1" + b"0" * 400
        reading = read_result(b'{"duration_ms": ' + huge + b', "total_cost_usd": ' + huge + b"}")
        self.assertEqual((reading.wall_seconds, reading.spend_usd), (None, 0))

    def test_invalid_measurements_read_as_zero(self):
        reading = read_result(raw(num_turns=True, total_cost_usd=-1, duration_ms=-5,
                                  usage={"input_tokens": "3"}))
        self.assertEqual((reading.turns, reading.spend_usd, reading.wall_seconds,
                          reading.tokens), (0, 0, None, ZERO_TOKENS))
        self.assertEqual(read_result(raw(num_turns=-1)).turns, 0)


def role_text(**fields: str) -> str:
    lines = {"name": None, "model": "opus", "effort": "high"}
    lines.update(fields)
    return "---\n" + "".join(f"{key}: {value}\n" for key, value in lines.items()
                             if value is not None) + "---\nBody.\n"


class RoleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def put(self, name: str, text: str) -> None:
        (self.directory / f"{name}.md").write_text(text, encoding="utf-8")

    def test_the_four_role_files_read_their_model_effort_tools_and_body(self):
        def listed(text: str, key: str):
            found = re.search(rf"^{key}: (.+)$", text, re.M)
            if found is None:
                return None
            return tuple(part.strip() for part in found.group(1).split(",") if part.strip())

        for name in ("planner", "implementer", "reviewer", "reviewer-lite"):
            shutil.copy(AGENTS / f"{name}.md", self.directory / f"{name}.md")
            text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
            with self.subTest(role=name):
                role = read_role(self.directory, name)
                self.assertEqual(role.name, name)
                self.assertEqual(role.model, re.search(r"^model: (.+)$", text, re.M).group(1))
                self.assertEqual(role.effort, re.search(r"^effort: (.+)$", text, re.M).group(1))
                self.assertEqual(role.tools, listed(text, "tools"))
                self.assertEqual(role.disallowed, listed(text, "disallowedTools"))
                self.assertEqual(role.body, text.partition("\n---\n")[2])
        self.assertIn("Agent(Explore)", read_role(self.directory, "planner").tools)
        implementer = read_role(self.directory, "implementer")
        self.assertIsNone(implementer.tools)
        self.assertTrue(implementer.disallowed)

    def test_a_role_file_that_cannot_give_a_role_is_refused(self):
        cases = {
            "a role outside the four": ("clerk", role_text()),
            "an absent file": ("planner", None),
            "no frontmatter": ("planner", "just text\n"),
            "no model": ("planner", role_text(model=None)),
            "an empty effort": ("planner", role_text(effort="")),
            "another role's name": ("planner", role_text(name="reviewer")),
            "tools with no name": ("planner", role_text(tools=",")),
            "not UTF-8": ("planner", None),
        }
        for label, (name, text) in cases.items():
            with self.subTest(label):
                for leftover in self.directory.iterdir():
                    leftover.unlink()
                if label == "not UTF-8":
                    (self.directory / f"{name}.md").write_bytes(b"---\nmodel: \xff\n---\n")
                elif text is not None:
                    self.put(name, text)
                with self.assertRaises(RoleError) as caught:
                    read_role(self.directory, name)
                self.assertIn(name, str(caught.exception))

    def test_a_role_value_that_would_put_a_forbidden_word_in_the_argv_is_refused(self):
        cases = (
            ("model", {"model": "--agent"}),
            ("effort", {"effort": "bypassPermissions"}),
            ("model", {"model": "opus --bare"}),
            ("tools", {"tools": "Read, --bare"}),
            ("disallowedTools", {"disallowedTools": "Write, --dangerously-skip-permissions"}),
            ("tools", {"tools": "Read,bypassPermissions"}),
            ("tools", {"tools": "Read, --setting-sources"}),
            ("effort", {"effort": "high medium"}),
        )
        for field, fields in cases:
            with self.subTest(fields=fields):
                self.put("planner", role_text(**fields))
                with self.assertRaises(RoleError) as caught:
                    read_role(self.directory, "planner")
                self.assertIn(field, str(caught.exception))
                self.assertIn("planner", str(caught.exception))
        self.put("planner", role_text(tools="Read, Bash(git status:*)"))
        self.assertEqual(read_role(self.directory, "planner").tools,
                         ("Read", "Bash(git status:*)"))


class PromptTest(unittest.TestCase):
    def test_placeholders_take_their_argument_words(self):
        self.assertEqual(
            render_prompt("Draft {{run.issue}} after {{ scope.items }}.",
                          (("run.issue", 1514), ("scope.items", ["a", "b"]))),
            'Draft 1514 after ["a","b"].')
        with self.assertRaises(ValueError):
            render_prompt("Use {{draft.summary}}.", ())


if __name__ == "__main__":
    unittest.main()


SCHEMA = {"type": "object", "required": ["verdict"],
          "properties": {"verdict": {"enum": ["approve", "revise"]}}}
SESSION = "0b0b8a8e-6f0e-4d47-9d6a-3f1f2b9c1a11"
SYSTEM = Path("/run/sessions/review.1.system.md")
REVIEWER = Role("reviewer", "opus", "high", ("Read", "Bash"), None, "body\n")
IMPLEMENTER = Role("implementer", "opus", "high", None, ("Workflow", "Artifact"), "")
NEVER = {"--agent", "--bare", "--setting-sources", "--dangerously-skip-permissions",
         "bypassPermissions"}
LAUNCHER_STANDIN = (
    "import subprocess,sys; subprocess.Popen([sys.executable, '-c', "
    "\"import os,sys,time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(60)\", "
    "sys.argv[1]]).wait()")


class LaunchArgvTest(unittest.TestCase):
    def test_the_argv_is_the_launcher_print_form_with_the_role_by_flags(self):
        self.assertEqual(launch_argv(REVIEWER, SCHEMA, SESSION, SYSTEM), (
            "claude-account", "run", "-p", "--output-format", "json", "--json-schema",
            '{"properties":{"verdict":{"enum":["approve","revise"]}},'
            '"required":["verdict"],"type":"object"}',
            "--session-id", "0b0b8a8e-6f0e-4d47-9d6a-3f1f2b9c1a11", "--strict-mcp-config",
            "--permission-mode", "dontAsk", "--model", "opus", "--effort", "high",
            "--tools", "Read,Bash", "--allowedTools", "Read,Bash",
            "--append-system-prompt-file", "/run/sessions/review.1.system.md"))

    def test_a_role_with_disallowed_tools_passes_only_disallowed_tools(self):
        argv = launch_argv(IMPLEMENTER, SCHEMA, SESSION, SYSTEM)
        self.assertNotIn("--tools", argv)
        self.assertNotIn("--allowedTools", argv)
        at = argv.index("--append-system-prompt-file")
        self.assertEqual(argv[at - 2:at], ("--disallowedTools", "Workflow,Artifact"))

    def test_no_argv_word_hands_the_session_an_agent_bare_or_bypass(self):
        for role in (REVIEWER, IMPLEMENTER):
            with self.subTest(role=role.name):
                argv = launch_argv(role, SCHEMA, SESSION, SYSTEM)
                self.assertTrue(NEVER.isdisjoint(argv))
                self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")

    def test_a_role_value_that_would_hand_over_control_is_refused(self):
        cases = {
            "model": Role("reviewer", "--agent", "high", None, None, ""),
            "effort": Role("reviewer", "opus", "bypassPermissions", None, None, ""),
            "tools": Role("reviewer", "opus", "high", ("Read", "--bare"), None, ""),
            "disallowed": Role("reviewer", "opus", "high", None,
                               ("--dangerously-skip-permissions",), ""),
        }
        for field, role in cases.items():
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    launch_argv(role, SCHEMA, SESSION, SYSTEM)


class LaunchTest(unittest.TestCase):
    def test_the_prompt_goes_on_stdin_in_the_given_directory(self):
        code = ("import json,os,sys; "
                "print(json.dumps({'cwd': os.getcwd(), 'stdin': sys.stdin.read()}))")
        pids: list[int] = []
        with tempfile.TemporaryDirectory() as directory:
            launched = launch([sys.executable, "-c", code], directory, "Draft 1514.",
                              on_start=pids.append)
            self.assertEqual(json.loads(launched.stdout), {
                "cwd": os.path.realpath(directory), "stdin": "Draft 1514."})
        self.assertEqual(launched.exit_code, 0)
        self.assertEqual(len(pids), 1)
        self.assertGreater(pids[0], 0)

    def test_the_launchers_stderr_is_captured_and_its_last_line_is_the_diagnostic(self):
        code = ("import sys; sys.stderr.write('first\\nclaude-account: no account \\'work\\'\\n'); "
                "sys.exit(1)")
        launched = launch([sys.executable, "-c", code], tempfile.gettempdir(), "",
                          on_start=lambda pid: None)
        self.assertEqual(launched.exit_code, 1)
        self.assertEqual(launched.stdout, b"")
        self.assertEqual(launched.stderr, b"first\nclaude-account: no account 'work'\n")
        self.assertEqual(diagnostic(launched.stderr), "claude-account: no account 'work'")
        self.assertEqual(diagnostic(b""), "")
        self.assertEqual(diagnostic(b"\n  \n"), "")
        self.assertEqual(diagnostic(b"a   b\n"), "a b")
        self.assertEqual(len(diagnostic(b"x" * 1000)), 300)

    def test_a_launcher_that_cannot_start_reports_127_and_never_calls_on_start(self):
        started: list[int] = []
        launched = launch(["/nonexistent/claude-account"], tempfile.gettempdir(), "p",
                          on_start=started.append)
        self.assertEqual((launched.exit_code, launched.stdout, launched.stderr),
                         (NOT_STARTED, b"", b""))
        self.assertEqual(started, [])

    def test_a_failing_on_start_ends_the_launchers_whole_group(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "child.pid"
            seen: dict[str, int] = {}

            def on_start(pid: int) -> None:
                seen["launcher"] = pid
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if pidfile.exists() and pidfile.read_text():
                        seen["child"] = int(pidfile.read_text())
                        break
                    time.sleep(0.05)
                raise RuntimeError("on_start failed")

            began = time.monotonic()
            try:
                with self.assertRaises(RuntimeError):
                    launch([sys.executable, "-c", LAUNCHER_STANDIN, str(pidfile)], directory,
                           "p", on_start=on_start)
                self.assertLess(time.monotonic() - began, 20)
                self.assertIn("child", seen)
                with self.assertRaises(ChildProcessError):
                    os.waitpid(seen["launcher"], os.WNOHANG)
                deadline = time.monotonic() + 5
                while True:
                    try:
                        os.kill(seen["child"], 0)
                    except ProcessLookupError:
                        break
                    if time.monotonic() > deadline:
                        self.fail("the launcher's child outlived the group kill")
                    time.sleep(0.05)
            finally:
                if "child" in seen:
                    try:
                        os.kill(seen["child"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass
