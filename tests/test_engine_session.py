"""Contract tests for the engine's session reading (`agent_tools.delivery.engine_session`, #1514).

Covers reading a role file, rendering a prompt, reading a session result, building the
launcher argv, starting one session and `engine deliver` running agent steps against a
stand-in launcher (tests/fixtures/engine-session/claude_stub.py).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from agent_tools.delivery import (
    engine, engine_ledger, engine_session, engine_shell, procedure_check,
)
from agent_tools.delivery.engine_session import (
    NOT_STARTED, ROLE_BOUNDS, Answer, Bounds, Reading, Role, RoleError, diagnostic, launch,
    launch_argv, read_answer, read_result, read_role, render_prompt,
)
from tests.test_engine_deliver import EngineProject, shape

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / "home/common/claude-code/agents"
STUB = REPO_ROOT / "tests/fixtures/engine-session/claude_stub.py"
LAUNCHER_SOURCE = REPO_ROOT / "home/common/claude-code/accounts/bin/claude-account"
RESULT_NORMAL = REPO_ROOT / "tests/fixtures/engine-session/result-normal.json"
RESULT_MISSING = REPO_ROOT / "tests/fixtures/engine-session/result-missing.json"
RESULT_INVALID = REPO_ROOT / "tests/fixtures/engine-session/result-invalid.json"
SETTINGS_GUARDED = REPO_ROOT / "tests/fixtures/engine-session/settings-guarded.json"
SETTINGS_UNGUARDED = REPO_ROOT / "tests/fixtures/engine-session/settings-unguarded.json"
RESULT_LIMIT = REPO_ROOT / "tests/fixtures/engine-session/result-limit.json"
RESULT_API_ERROR = REPO_ROOT / "tests/fixtures/engine-session/result-api-error.json"
RESULT_MAX_TURNS = REPO_ROOT / "tests/fixtures/engine-session/result-max-turns.json"
RESULT_MAX_BUDGET = REPO_ROOT / "tests/fixtures/engine-session/result-max-budget.json"
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
            spend_usd=0.4321, is_result=True))

    def test_no_structured_output_gives_no_reply_but_keeps_prose_and_measurements(self):
        reading = read_result(raw(structured_output=...))
        self.assertIsNone(reading.reply)
        self.assertEqual(reading.prose, "Status: stuck. I could not draft it.")
        self.assertEqual(reading.turns, 7)
        for value in (None, [1], "drafted"):
            with self.subTest(value=value):
                self.assertIsNone(read_result(raw(structured_output=value)).reply)

    def test_an_integral_number_written_as_a_float_reads_as_an_integer(self):
        reading = read_result(b'{"type":"result","structured_output":{"n":2.0,"m":2.5,"k":1e2}}')
        self.assertEqual(reading.reply, {"n": 2, "m": 2.5, "k": 100})
        self.assertIs(type(reading.reply["n"]), int)
        self.assertIs(type(read_result(b'{"structured_output":{"n":true}}').reply["n"]), bool)

    def test_is_error_is_read_only_when_it_is_the_boolean_true(self):
        self.assertTrue(read_result(raw(is_error=True)).is_error)
        for value in (False, "true", 1, None):
            with self.subTest(value=value):
                self.assertFalse(read_result(raw(is_error=value)).is_error)

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

    def test_a_limit_result_reads_as_a_usage_limit(self):
        reading = read_result(RESULT_LIMIT.read_bytes())
        self.assertEqual(reading.api_failure, "usage-limit")
        self.assertIsNone(reading.reply)

    def test_a_result_that_is_no_error_has_no_api_failure(self):
        self.assertIsNone(read_result(json.dumps(RESULT).encode()).api_failure)
        self.assertIsNone(read_result(raw(is_error=True)).api_failure)
        self.assertIsNone(read_result(raw(is_error=True, api_error_status=True)).api_failure)
        self.assertIsNone(read_result(raw(api_error="usage_limit_reached",
                                          api_error_status=429)).api_failure)

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


GIT_READ_ONLY = ("Bash(git diff:*),Bash(git log:*),Bash(git show:*),Bash(git status:*),"
                 "Bash(git rev-parse:*),Bash(git ls-files:*),Bash(git blame:*),"
                 "Bash(git merge-base:*)")
# `git diff`, `git log` and `git show` all write a file given `--output=<file>`; the prefix
# patterns above would preapprove that, so these deny rules (checked first) refuse it.
GIT_WRITING = ("Bash(git diff*--output*),Bash(git log*--output*),Bash(git show*--output*)")


class LaunchArgvTest(unittest.TestCase):
    def test_bash_is_never_preapproved_as_a_whole(self):
        role = Role("reviewer", "opus", "high", ("Read", "Bash", "Skill"), None, "")
        argv = launch_argv(role, SCHEMA, SESSION, SYSTEM)
        self.assertEqual(after(list(argv), "--tools"), "Read,Bash,Skill")
        allowed = after(list(argv), "--allowedTools").split(",")
        self.assertNotIn("Bash", allowed)
        self.assertEqual(allowed, ["Read", *GIT_READ_ONLY.split(","), "Skill"])

    def test_the_git_commands_that_write_a_file_through_output_are_denied(self):
        argv = launch_argv(REVIEWER, SCHEMA, SESSION, SYSTEM)
        self.assertEqual(after(list(argv), "--disallowedTools"), GIT_WRITING)

    def test_the_output_denial_joins_a_roles_own_disallowed_tools_and_needs_bash(self):
        both = Role("reviewer", "opus", "high", ("Read", "Bash"), ("Write",), "")
        self.assertEqual(after(list(launch_argv(both, SCHEMA, SESSION, SYSTEM)),
                               "--disallowedTools"), f"Write,{GIT_WRITING}")
        no_shell = Role("reviewer", "opus", "high", ("Read",), None, "")
        self.assertNotIn("--disallowedTools", launch_argv(no_shell, SCHEMA, SESSION, SYSTEM))

    def test_the_argv_is_the_launcher_print_form_with_the_role_by_flags(self):
        self.assertEqual(launch_argv(REVIEWER, SCHEMA, SESSION, SYSTEM), (
            "claude-account", "run", "-p", "--output-format", "json", "--json-schema",
            '{"properties":{"verdict":{"enum":["approve","revise"]}},'
            '"required":["verdict"],"type":"object"}',
            "--session-id", "0b0b8a8e-6f0e-4d47-9d6a-3f1f2b9c1a11", "--strict-mcp-config",
            "--permission-mode", "dontAsk", "--model", "opus", "--effort", "high",
            "--max-turns", "150", "--max-budget-usd", "15.00",
            "--tools", "Read,Bash", "--allowedTools", f"Read,{GIT_READ_ONLY}",
            "--disallowedTools", GIT_WRITING,
            "--append-system-prompt-file", "/run/sessions/review.1.system.md"))

    def test_a_resume_names_the_session_by_resume_and_never_session_id(self):
        first = list(launch_argv(REVIEWER, SCHEMA, SESSION, SYSTEM))
        again = list(launch_argv(REVIEWER, SCHEMA, SESSION, SYSTEM, resume=True))
        self.assertEqual(after(again, "--resume"), SESSION)
        self.assertNotIn("--session-id", again)
        at = first.index("--session-id")
        self.assertEqual(first[:at] + ["--resume", SESSION] + first[at + 2:], again)

    def test_the_role_bounds_table_is_the_issue_table(self):
        self.assertEqual(dict(ROLE_BOUNDS), {
            "planner": Bounds(1800, 150, 15.0), "implementer": Bounds(3600, 300, 20.0),
            "reviewer": Bounds(1800, 150, 15.0), "reviewer-lite": Bounds(900, 80, 3.0)})
        self.assertEqual(set(ROLE_BOUNDS), set(procedure_check.ROLES))

    def test_a_role_with_no_bounds_is_refused(self):
        with self.assertRaises(RoleError):
            launch_argv(Role("stranger", "opus", "high", None, None, ""), SCHEMA, SESSION, SYSTEM)

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

    def test_the_session_environment_drops_only_the_config_dir(self):
        given = {"HOME": "/h", "PATH": "/p", "CLAUDE_CONFIG_DIR": "/c"}
        self.assertEqual(engine_session.session_environment(given), {
            "HOME": "/h", "PATH": "/p", "CLAUDE_ACCOUNT_HOST_SETTINGS": "required"})
        self.assertEqual(given["CLAUDE_CONFIG_DIR"], "/c")
        code = ("import json,os; print(json.dumps([os.environ.get(k) for k in "
                "('CLAUDE_CONFIG_DIR', 'ENGINE_PROBE', 'CLAUDE_ACCOUNT_HOST_SETTINGS')]))")
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
                os.environ, {"CLAUDE_CONFIG_DIR": "/c", "ENGINE_PROBE": "kept"}):
            launched = launch([sys.executable, "-c", code], directory, "",
                              on_start=lambda pid: None)
        self.assertEqual(json.loads(launched.stdout), [None, "kept", "required"])

    def test_a_given_env_is_the_launchers_whole_environment(self):
        env = {"PATH": os.environ["PATH"], "X_ANSWER": "1"}
        launched = launch(["env"], tempfile.gettempdir(), "", on_start=lambda pid: None, env=env)
        lines = launched.stdout.decode().splitlines()
        self.assertIn("X_ANSWER=1", lines)
        self.assertFalse([line for line in lines if line.startswith("HOME=")])

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

    def test_a_launcher_that_cannot_start_reports_127_with_the_oserror_and_never_calls_on_start(self):
        for name, argv, cwd, word in (
                ("missing launcher", ["/nonexistent/claude-account"], tempfile.gettempdir(),
                 "/nonexistent/claude-account"),
                ("invalid cwd", [sys.executable, "-c", "pass"], "/nonexistent/directory",
                 "/nonexistent/directory")):
            with self.subTest(name):
                started: list[int] = []
                launched = launch(argv, cwd, "p", on_start=started.append)
                self.assertEqual((launched.exit_code, launched.stdout), (NOT_STARTED, b""))
                self.assertIn("No such file or directory", diagnostic(launched.stderr))
                self.assertIn(word, diagnostic(launched.stderr))
                self.assertEqual(started, [])

    def test_a_sigterm_during_the_spawn_still_ends_the_launchers_group_and_restores_the_handler(self):
        real = subprocess.Popen
        pids: list[int] = []
        started: list[int] = []

        def spawn_then_term(*args, **kwargs):
            child = real(*args, **kwargs)
            pids.append(child.pid)
            os.kill(os.getpid(), signal.SIGTERM)
            return child

        def kill_group() -> None:
            for pid in pids:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        self.addCleanup(kill_group)
        before = lambda signum, frame: None  # noqa: E731
        outer = signal.signal(signal.SIGTERM, before)
        self.addCleanup(signal.signal, signal.SIGTERM, outer)
        with mock.patch.object(engine_session.subprocess, "Popen", spawn_then_term):
            with self.assertRaises(SystemExit) as raised:
                launch([sys.executable, "-c", "import time; time.sleep(60)"],
                       tempfile.gettempdir(), "p", on_start=started.append, timeout=30)
        self.assertEqual(raised.exception.code, 143)
        self.assertEqual(started, [])
        self.assertIs(signal.getsignal(signal.SIGTERM), before)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.killpg(pids[0], 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        self.fail("the launcher's group outlived the engine's SIGTERM")

    def test_a_sigterm_to_the_engine_ends_the_launchers_whole_group_and_restores_the_handler(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "child.pid"
            seen: dict[str, int] = {}
            before = signal.getsignal(signal.SIGTERM)

            def on_start(pid: int) -> None:
                seen["launcher"] = pid

                def terminate() -> None:
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        if pidfile.exists() and pidfile.read_text():
                            seen["child"] = int(pidfile.read_text())
                            break
                        time.sleep(0.05)
                    os.kill(os.getpid(), signal.SIGTERM)

                threading.Thread(target=terminate, daemon=True).start()

            try:
                with self.assertRaises(SystemExit) as raised:
                    launch([sys.executable, "-c", LAUNCHER_STANDIN, str(pidfile)], directory,
                           "p", on_start=on_start)
                self.assertEqual(raised.exception.code, 143)
                self.assertIn("child", seen)
                self.assertIs(signal.getsignal(signal.SIGTERM), before)
                deadline = time.monotonic() + 5
                while True:
                    try:
                        os.kill(seen["child"], 0)
                    except ProcessLookupError:
                        break
                    if time.monotonic() > deadline:
                        self.fail("the launcher's child outlived the SIGTERM")
                    time.sleep(0.05)
            finally:
                if "child" in seen:
                    try:
                        os.kill(seen["child"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass

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


    def test_a_launcher_past_its_timeout_gets_sigterm_and_its_grace_before_sigkill(self):
        code = ("import signal, sys, time; "
                "signal.signal(signal.SIGTERM, lambda s, f: open(sys.argv[1], 'w').write('term')); "
                "print('ready', flush=True); time.sleep(60)")
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "marker"
            seen: list[int] = []
            began = time.monotonic()
            with mock.patch.object(engine_session, "GRACE_SECONDS", 2):
                launched = launch([sys.executable, "-c", code, str(marker)], directory, "p",
                                  on_start=seen.append, timeout=1)
            elapsed = time.monotonic() - began
            self.assertTrue(launched.timed_out)
            self.assertEqual(marker.read_text(encoding="utf-8"), "term")
            self.assertGreaterEqual(elapsed, 1 + 2 - 0.25)
            self.assertLess(elapsed, 1 + 2 + engine_session.DRAIN_SECONDS + 5)
            with self.assertRaises(ProcessLookupError):
                os.kill(seen[0], 0)

    def test_time_spent_recording_the_start_counts_against_the_wall_bound(self):
        launched = launch([sys.executable, "-c", "import time; time.sleep(1.5); print('{}')"],
                          tempfile.gettempdir(), "p", on_start=lambda pid: time.sleep(1.2),
                          timeout=1)
        self.assertIs(launched.timed_out, True)

    def test_a_stalled_start_callback_cannot_keep_the_group_past_its_wall_bound(self):
        code = "import sys, time\nwhile True:\n    open(sys.argv[1], 'a').write('x')\n    time.sleep(0.05)\n"
        with tempfile.TemporaryDirectory() as directory:
            beat = Path(directory) / "beat"
            sizes: list[tuple[int, int]] = []

            def stalled(pid: int) -> None:
                time.sleep(2.5)
                before = beat.stat().st_size
                time.sleep(0.5)
                sizes.append((before, beat.stat().st_size))

            launched = launch([sys.executable, "-c", code, str(beat)], directory, "p",
                              on_start=stalled, timeout=1)
        self.assertIs(launched.timed_out, True)
        self.assertEqual(sizes[0][0], sizes[0][1], "the group still ran while on_start stalled")

    def test_an_untimed_launch_is_not_timed_out(self):
        launched = launch([sys.executable, "-c", "import sys; print(sys.stdin.read())"],
                          tempfile.gettempdir(), "word", on_start=lambda pid: None)
        self.assertIs(launched.timed_out, False)
        self.assertEqual(launched.stdout, b"word\n")


class ReadAnswerTest(unittest.TestCase):
    def read(self, text: str | None) -> Answer:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answer.json"
            if text is not None:
                path.write_text(text, encoding="utf-8")
            return read_answer(path)

    def test_anything_but_the_two_exact_forms_is_no_answer(self):
        nothing = Answer(None, False, None)
        for text in (None, "", "not json", "[1]", '{"account":""}', '{"account":1}',
                     '{"account":"a","x":1}', '{"account":"a","account":"b"}',
                     '{"all_out":true,"resumes_at":"soon"}', '{"all_out":true}',
                     '{"all_out":false,"resumes_at":null}', '{"all_out":1,"resumes_at":null}',
                     '{"all_out":true,"resumes_at":null,"account":"a"}', "{}"):
            with self.subTest(text=text):
                self.assertEqual(self.read(text), nothing)

    def test_the_two_valid_forms_give_their_values(self):
        self.assertEqual(self.read('{"account":"p1"}'), Answer("p1", False, None))
        self.assertEqual(self.read('{"all_out":true,"resumes_at":null}'),
                         Answer(None, True, None))
        self.assertEqual(self.read('{"all_out":true,"resumes_at":"2030-03-17T17:46:40Z"}'),
                         Answer(None, True, "2030-03-17T17:46:40Z"))


DRAFT_REPLY = {"type": "object",
               "properties": {"status": {"enum": ["drafted", "stuck"]},
                              "summary": {"type": "string"},
                              "items": {"type": "array", "items": {"type": "string"}}},
               "required": ["status", "summary", "items"],
               "additionalProperties": False}
REVIEW_REPLY = {"type": "object",
                "properties": {"verdict": {"enum": ["approve", "revise"]},
                               "status": {"type": "string"}},
                "required": ["verdict", "status"],
                "additionalProperties": False}
ROLE_NAMES = ("planner", "implementer", "reviewer", "reviewer-lite")


def install_stub(project: EngineProject, canned: Path | bytes, exit: int | str = 0,
                 diagnostic: str | None = None, resumed: Path | bytes | None = None,
                 hold: Path | None = None) -> Path:
    """Put the stand-in launcher first on the project's PATH; return the log it appends to.

    `resumed` is what the stub prints instead of `canned` when it is launched with `--resume`.
    """
    log = project.tmp / "claude.log"
    if not isinstance(canned, Path):
        data, canned = canned, project.tmp / "canned.json"
        canned.write_bytes(data)
    resumed_path = "-"
    if resumed is not None:
        resumed_path = str(resumed)
        if not isinstance(resumed, Path):
            resumed_path = str(project.tmp / "resumed.json")
            Path(resumed_path).write_bytes(resumed)
    diagnostic_path = "-"
    if diagnostic is not None:
        diagnostic_path = str(project.tmp / "diagnostic.txt")
        Path(diagnostic_path).write_text(diagnostic, encoding="utf-8")
    launcher = project.bin / "claude-account"
    launcher.write_text(f"#!/bin/sh\nexec {sys.executable} {STUB} {log} {canned} {resumed_path} "
                        f"{exit} {diagnostic_path} {hold if hold else '-'} \"$@\"\n", encoding="utf-8")
    launcher.chmod(0o755)
    return log


def install_answers(project: EngineProject, entries: list[dict]) -> Path:
    """Put a launcher stand-in that answers each launch from `entries`; return its log."""
    canned = project.tmp / "stub.answers.json"
    canned.write_text(json.dumps(entries), encoding="utf-8")
    return install_stub(project, canned)


def copy_roles(project: EngineProject, *names: str) -> None:
    directory = project.world.home / ".claude/agents"
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy(AGENTS / f"{name}.md", directory / f"{name}.md")


def agent_step(id: str, role: str, on: dict, **members) -> dict:
    on = {**on}
    on.setdefault("out-of-bounds", "needs-owner")
    document = {"id": id, "stage": "building", "kind": "agent", "role": role, "holds": "run",
                "prompt": "draft.md", "reply": "draft.reply.json", "outcome_from": "status",
                "in": ["run.issue"], "on": {"no-reply": "step-failed", **on}}
    document.update(members)
    return document


def write_procedures(project: EngineProject, steps: list[dict], files: dict | None = None,
                     stops: dict | None = None) -> Path:
    directory = project.procedures(
        steps, stops=stops or {"needs-owner": {"need": "owner-decision", "reenter": steps[0]["id"]},
                               "step-failed": {"need": "retry", "reenter": steps[0]["id"]}})
    for name, text in (files or {"draft.md": "Draft issue {{run.issue}}.\n",
                                 "draft.reply.json": json.dumps(DRAFT_REPLY)}).items():
        (directory / name).write_text(text, encoding="utf-8")
    return directory


def one_step(project: EngineProject, **members) -> Path:
    on = members.pop("on", {"drafted": "done", "stuck": "needs-owner"})
    return write_procedures(project, [agent_step("draft", "implementer", on, **members)])


def canned_result(**overrides) -> bytes:
    document = json.loads(RESULT_NORMAL.read_text(encoding="utf-8"))
    document.update(overrides)
    return json.dumps({key: value for key, value in document.items()
                       if value is not ...}).encode()


def after(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def frontmatter(text: str, field: str) -> str | None:
    found = re.search(rf"^{field}: (.+)$", text, re.M)
    return found.group(1) if found else None


def names(value: str) -> str:
    return ",".join(part.strip() for part in value.split(","))


class DeliverSessionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.project = EngineProject(self)
        self.project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(self.project, *ROLE_NAMES)

    def log(self, log: Path) -> list[dict]:
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def run_dir(self) -> Path:
        (run,) = self.project.runs()
        return run

    def starting(self, step: str = "draft") -> dict:
        (event,) = [e for e in self.project.events(self.run_dir())
                    if e["event"] == "session_starting" and e["step"] == step]
        return event

    def test_each_role_file_reaches_the_stub_by_flags_and_never_as_agent_bare_or_bypass(self):
        project = self.project
        log = install_stub(project, RESULT_NORMAL)
        roles = ROLE_NAMES
        steps = [agent_step(name[0] if name != "reviewer-lite" else "l", name,
                            {"drafted": nxt, "stuck": "needs-owner"})
                 for name, nxt in zip(roles, ("i", "r", "l", "done"))]
        procedures = write_procedures(project, steps)
        nested = project.root / "nested"
        nested.mkdir()
        done = project.deliver(procedures, issue=1514, cwd=nested)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["detail"],
                         "The deliver procedure reached done after 4 step visits.")
        lines = self.log(log)
        self.assertEqual(len(lines), 4)
        starting = [e for e in project.events(self.run_dir()) if e["event"] == "session_starting"]
        self.assertEqual([e["role"] for e in starting], list(roles))
        ids = []
        for line, event, role in zip(lines, starting, roles):
            argv = line["argv"]
            text = (AGENTS / f"{role}.md").read_text(encoding="utf-8")
            self.assertEqual(argv[:3], ["run", "-p", "--output-format"])
            self.assertEqual(argv[3], "json")
            self.assertEqual(json.loads(after(argv, "--json-schema")), DRAFT_REPLY)
            session = after(argv, "--session-id")
            self.assertEqual(uuid.UUID(session).version, 4)
            self.assertEqual(session, event["session"])
            ids.append(session)
            self.assertEqual(after(argv, "--permission-mode"), "dontAsk")
            self.assertIn("--strict-mcp-config", argv)
            self.assertEqual(line["cwd"], os.path.realpath(project.root))
            self.assertEqual(line["stdin"], "Draft issue 1514.\n")
            self.assertEqual(after(argv, "--model"), frontmatter(text, "model"))
            self.assertEqual(after(argv, "--effort"), frontmatter(text, "effort"))
            tools = frontmatter(text, "tools")
            if role == "implementer":
                self.assertNotIn("--tools", argv)
                self.assertNotIn("--allowedTools", argv)
                self.assertEqual(after(argv, "--disallowedTools"),
                                 names(frontmatter(text, "disallowedTools")))
            else:
                self.assertEqual(after(argv, "--tools"), names(tools))
                self.assertEqual(after(argv, "--allowedTools"),
                                 names(tools).replace("Bash", GIT_READ_ONLY))
                if "Bash" in tools:
                    self.assertEqual(after(argv, "--disallowedTools"), GIT_WRITING)
                else:
                    self.assertNotIn("--disallowedTools", argv)
            self.assertEqual(Path(after(argv, "--append-system-prompt-file")).read_text(
                encoding="utf-8"), text.partition("\n---\n")[2])
            for word in ("--agent", "--bare", "--setting-sources",
                         "--dangerously-skip-permissions", "bypassPermissions"):
                self.assertNotIn(word, argv)
            self.assertEqual(event["account"], "console")
        self.assertEqual(len(set(ids)), 4)

    def test_each_role_reaches_the_stub_with_its_turn_and_spend_bounds(self):
        project = self.project
        log = install_stub(project, RESULT_NORMAL)
        steps = [agent_step(name[0] if name != "reviewer-lite" else "l", name,
                            {"drafted": nxt, "stuck": "needs-owner"})
                 for name, nxt in zip(ROLE_NAMES, ("i", "r", "l", "done"))]
        procedures = write_procedures(project, steps)
        done = project.deliver(procedures, issue=1520)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = self.log(log)
        self.assertEqual(len(lines), 4)
        expected = (("150", "15.00"), ("300", "20.00"), ("150", "15.00"), ("80", "3.00"))
        for line, pair in zip(lines, expected):
            argv = line["argv"]
            self.assertEqual((after(argv, "--max-turns"), after(argv, "--max-budget-usd")), pair)
            self.assertEqual(argv.count("--max-turns"), 1)
            self.assertEqual(argv.count("--max-budget-usd"), 1)

    def test_the_session_is_recorded_before_its_process_starts(self):
        log = install_stub(self.project, RESULT_NORMAL)
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 0, done.stderr)
        run = self.run_dir()
        self.assertEqual(shape(self.project.events(run)), [
            ("step_entered", "draft", 1), ("session_starting", "draft", 1),
            ("process_started", "draft", 1), ("session_answered", "draft", 1),
            ("result_stored", "draft", 1), ("outcome_graded", "draft", 1),
            ("transition_taken", "draft", 1), ("run_done", None, None)])
        (line,) = self.log(log)
        self.assertTrue(line["announced"])
        self.assertEqual((run / "sessions/draft.1.prompt.md").read_text(encoding="utf-8"),
                         line["stdin"])

    def test_the_session_is_on_disk_before_launch_is_called(self):
        project = self.project
        install_stub(project, RESULT_NORMAL)
        procedures = one_step(project)
        real = engine_session.launch
        seen: list[tuple] = []

        def checking(argv, cwd, prompt, *, on_start, **options):
            self.assertEqual(options["timeout"], 3600)
            (run,) = project.runs()
            events = engine_ledger.replay(run / "events.jsonl")
            seen.append((events[-1]["event"], events[-1].get("session"),
                         [e["event"] for e in events], after(list(argv), "--session-id")))
            return real(argv, cwd, prompt, on_start=on_start, **options)

        with project.inside(), mock.patch.object(engine_session, "launch", side_effect=checking):
            code, line = engine_shell.deliver(1514, procedures)
        self.assertEqual(code, 0, line)
        (last, session, events, asked) = seen[0]
        self.assertEqual(len(seen), 1)
        self.assertEqual(last, "session_starting")
        self.assertEqual(session, asked)
        self.assertNotIn("process_started", events)

    def test_the_outcome_is_the_structured_reply_and_prose_naming_another_changes_nothing(self):
        with self.subTest("outcome_from status"):
            project = EngineProject(self)
            project.env.pop("CLAUDE_ACCOUNT", None)
            copy_roles(project, "implementer")
            install_stub(project, RESULT_NORMAL)
            done = project.deliver(one_step(project), issue=1514)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads(done.stdout)["end"], "done")
            (run,) = project.runs()
            events = project.events(run)
            graded = [e for e in events if e["event"] == "outcome_graded"]
            taken = [e for e in events if e["event"] == "transition_taken"]
            self.assertEqual(graded[0]["outcome"], "drafted")
            self.assertEqual(taken[0]["to"], "done")
            self.assertEqual(json.loads((run / "results/draft.1.json").read_text()),
                             {"status": "drafted", "summary": "a short draft", "items": ["a"]})
        with self.subTest("outcome_from verdict"):
            project = EngineProject(self)
            project.env.pop("CLAUDE_ACCOUNT", None)
            copy_roles(project, "reviewer")
            install_stub(project, canned_result(
                structured_output={"verdict": "revise", "status": "approve"},
                result="Verdict: approve."), exit=1)
            steps = [agent_step("review", "reviewer", {"approve": "done", "revise": "needs-owner"},
                                prompt="review.md", reply="review.reply.json",
                                outcome_from="verdict")]
            procedures = write_procedures(project, steps, {
                "review.md": "Review {{run.issue}}.\n",
                "review.reply.json": json.dumps(REVIEW_REPLY)})
            done = project.deliver(procedures, issue=1514)
            self.assertEqual(done.returncode, 3, done.stderr)
            self.assertEqual(json.loads(done.stdout)["end"], "needs-owner")
            events = project.events(project.runs()[0])
            self.assertEqual([e["outcome"] for e in events if e["event"] == "outcome_graded"],
                             ["revise"])
            self.assertEqual([e["to"] for e in events if e["event"] == "transition_taken"],
                             ["needs-owner"])

    def test_the_result_event_carries_the_canned_measurements_and_the_step_its_denials(self):
        install_stub(self.project, RESULT_NORMAL)
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 0, done.stderr)
        run = self.run_dir()
        (stored,) = [e for e in self.project.events(run) if e["event"] == "result_stored"]
        self.assertEqual(stored["wall_seconds"], 12.345)
        self.assertEqual(stored["turns"], 7)
        self.assertEqual(stored["tokens"],
                         {"input": 11, "cache_write": 22, "cache_read": 33, "output": 44})
        self.assertEqual(stored["spend_usd"], 0.4321)
        self.assertEqual(json.loads((run / "sessions/draft.1.json").read_text(encoding="utf-8")), {
            "denials": [{"tool_name": "Write", "tool_use_id": "toolu_01",
                         "tool_input": {"file_path": "/etc/hosts"}}],
            "exit_code": 0, "prose": "Status: stuck. I could not draft it.",
            "problem": None, "session": self.starting()["session"], "subtype": "success"})

    def capped_procedures(self) -> Path:
        copy_roles(self.project, "implementer")
        step = agent_step("draft", "implementer", {"drafted": "done", "stuck": "needs-owner",
                                                   "out-of-bounds": "step-failed"})
        return write_procedures(self.project, [step], stops={
            "needs-owner": {"need": "owner-decision", "reenter": "draft"},
            "step-failed": {"need": "retry", "reenter": "draft"}})

    def test_a_turn_cap_or_a_spend_cap_is_out_of_bounds_naming_the_bound_with_no_second_session(self):
        for fixture, bound, turns, spend in ((RESULT_MAX_TURNS, "turns", 300, 1.25),
                                             (RESULT_MAX_BUDGET, "spend", 42, 20.01)):
            with self.subTest(bound=bound):
                self.setUp()
                log = install_stub(self.project, fixture, exit=1)
                done = self.project.deliver(self.capped_procedures(), issue=1520)
                self.assertEqual(done.returncode, 3, done.stderr)
                self.assertEqual(json.loads(done.stdout)["end"], "step-failed")
                self.assertEqual(json.loads(done.stdout)["need"], "retry")
                run = self.run_dir()
                self.assertEqual(json.loads((run / "results/draft.1.json").read_text(
                    encoding="utf-8")), {"bound": bound})
                events = self.project.events(run)
                (stored,) = [e for e in events if e["event"] == "result_stored"]
                self.assertEqual((stored["turns"], stored["spend_usd"], stored["wall_seconds"]),
                                 (turns, spend, 54.321))
                self.assertEqual(stored["tokens"],
                                 {"input": 1, "cache_write": 2, "cache_read": 3, "output": 4})
                self.assertEqual([e["outcome"] for e in events if e["event"] == "outcome_graded"],
                                 ["out-of-bounds"])
                self.assertEqual([e["to"] for e in events if e["event"] == "transition_taken"],
                                 ["step-failed"])
                (line,) = log.read_text(encoding="utf-8").splitlines()
                self.assertNotIn("--resume", line)
                self.assertNotIn("--continue", line)

    def test_a_session_past_a_shortened_wall_bound_ends_with_its_child_as_out_of_bounds(self):
        project = self.project
        hold = project.tmp / "hold.pids"
        log = install_stub(project, RESULT_NORMAL, hold=hold)
        procedures = self.capped_procedures()
        bounds = {**engine_session.ROLE_BOUNDS, "implementer": engine_session.Bounds(3, 300, 20.0)}
        began = time.monotonic()
        with project.inside(), mock.patch.object(engine_session, "ROLE_BOUNDS", bounds):
            code, line = engine_shell.deliver(1520, procedures)
        elapsed = time.monotonic() - began
        pids: list[int] = []
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not pids:
            pids = [int(word) for word in hold.read_text(encoding="utf-8").split()] \
                if hold.exists() else []
            time.sleep(0.05)
        self.assertEqual(len(pids), 2)
        for pid in pids:
            self.addCleanup(self.kill_quietly, pid)
        self.assertEqual((code, line["end"]), (3, "step-failed"), line)
        self.assertLess(elapsed, 30)
        run = self.run_dir()
        self.assertEqual(json.loads((run / "results/draft.1.json").read_text(
            encoding="utf-8")), {"bound": "wall-time"})
        events = project.events(run)
        (stored,) = [e for e in events if e["event"] == "result_stored"]
        self.assertGreaterEqual(stored["wall_seconds"], 3)
        self.assertLess(stored["wall_seconds"], 30)
        self.assertEqual([e["outcome"] for e in events if e["event"] == "outcome_graded"],
                         ["out-of-bounds"])
        self.assertEqual(len([e for e in events if e["event"] == "process_started"]), 1)
        self.assertLessEqual(len(self.log(log)), 1)
        deadline = time.monotonic() + 5
        for pid in pids:
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                if time.monotonic() > deadline:
                    self.fail(f"process {pid} outlived the wall-time ending")
                time.sleep(0.05)

    @staticmethod
    def kill_quietly(pid: int) -> None:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def test_a_capped_session_denied_a_shell_command_is_still_out_of_bounds(self):
        document = json.loads(RESULT_MAX_TURNS.read_text(encoding="utf-8"))
        document["permission_denials"] = [{"tool_name": "Bash", "tool_use_id": "toolu_03",
                                           "tool_input": {"command": "make build"}}]
        install_stub(self.project, json.dumps(document).encode("utf-8"), exit=1)
        done = self.project.deliver(self.capped_procedures(), issue=1520)
        self.assertEqual(done.returncode, 3, done.stderr)
        run = self.run_dir()
        self.assertEqual(json.loads((run / "results/draft.1.json").read_text(
            encoding="utf-8")), {"bound": "turns"})

    def test_a_session_ending_with_an_error_subtype_that_is_no_cap_is_still_a_fault(self):
        document = json.loads(RESULT_MAX_TURNS.read_text(encoding="utf-8"))
        document["subtype"] = "error_during_execution"
        install_stub(self.project, json.dumps(document).encode("utf-8"), exit=1)
        done = self.project.deliver(self.capped_procedures(), issue=1520)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(len(done.stderr.strip().splitlines()), 1)
        self.assertEqual([e for e in self.project.events(self.run_dir())
                          if e["event"] == "outcome_graded"], [])

    def test_a_denied_shell_command_is_a_fault_not_a_graded_reply(self):
        denial = {"tool_name": "Bash", "tool_use_id": "toolu_02",
                  "tool_input": {"command": "PYTHONPATH=python python3 -m unittest tests.test_x"}}
        install_stub(self.project, canned_result(
            structured_output={"verdict": "approve"}, permission_denials=[denial]))
        steps = [agent_step("review", "reviewer", {"approve": "done", "revise": "needs-owner"},
                            prompt="review.md", reply="review.reply.json",
                            outcome_from="verdict")]
        procedures = write_procedures(self.project, steps, {
            "review.md": "Review {{run.issue}}.\n",
            "review.reply.json": json.dumps(REVIEW_REPLY)})
        done = self.project.deliver(procedures, issue=1514)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        for word in ("review", "python3 -m unittest tests.test_x"):
            self.assertIn(word, done.stderr)
        run = self.run_dir()
        kinds = [e["event"] for e in self.project.events(run)]
        for kind in ("result_stored", "outcome_graded", "transition_taken", "run_done"):
            self.assertNotIn(kind, kinds)
        record = json.loads((run / "sessions/review.1.json").read_text(encoding="utf-8"))
        self.assertEqual(record["denials"], [denial])

    def test_a_result_without_its_duration_records_the_engines_measure(self):
        install_stub(self.project, canned_result(duration_ms=...))
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 0, done.stderr)
        (stored,) = [e for e in self.project.events(self.run_dir())
                     if e["event"] == "result_stored"]
        self.assertIsInstance(stored["wall_seconds"], float)
        self.assertTrue(0 < stored["wall_seconds"] < 120, stored["wall_seconds"])

    def test_an_account_override_is_the_account_asked(self):
        self.project.env["CLAUDE_ACCOUNT"] = "work"
        install_stub(self.project, RESULT_NORMAL)
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.starting()["account"], "work")

    def test_an_unknown_account_is_one_fault_line_with_the_launchers_reason(self):
        self.project.env["CLAUDE_ACCOUNT"] = "work"
        log = install_stub(self.project, b"", exit=1, diagnostic=(
            "claude-account: no account 'work' (create it: /account add work, "
            "or claude-account add work)\n"))
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        for word in ("draft", "exit 1", "no account 'work'"):
            self.assertIn(word, done.stderr)
        self.assertEqual(len(self.log(log)), 1)

    def kinds(self, project: EngineProject | None = None) -> list[str]:
        project = project or self.project
        return [e["event"] for e in project.events(project.runs()[0])]

    def test_a_host_without_the_guard_hook_starts_no_run_and_with_it_starts(self):
        guarded = json.loads(SETTINGS_GUARDED.read_text(encoding="utf-8"))
        filtered = json.loads(SETTINGS_GUARDED.read_text(encoding="utf-8"))
        filtered["hooks"]["PreToolUse"][0]["hooks"][0]["if"] = "Bash(git push *)"
        cases = {"unguarded": SETTINGS_UNGUARDED.read_text(encoding="utf-8"),
                 "switch on": json.dumps({**guarded, "disableAllHooks": True}),
                 "filtered": json.dumps(filtered),
                 "guarded": SETTINGS_GUARDED.read_text(encoding="utf-8")}
        for name, text in cases.items():
            with self.subTest(name):
                project = EngineProject(self)
                project.env.pop("CLAUDE_ACCOUNT", None)
                copy_roles(project, "implementer")
                log = install_stub(project, RESULT_NORMAL)
                project.use_settings_text(text)
                done = project.deliver(one_step(project), issue=1514)
                if name == "guarded":
                    self.assertEqual(done.returncode, 0, done.stderr)
                    self.assertEqual(json.loads(done.stdout)["end"], "done")
                    self.assertEqual(len(self.log(log)), 1)
                    continue
                self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
                self.assertEqual(done.stdout, "")
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertIn("lifecycle guard", done.stderr)
                self.assertEqual(project.runs(), [])
                self.assertFalse((project.world.home / ".agents/state/engine/runs").exists())
                self.assertFalse(log.exists())
                if name == "switch on":
                    self.assertIn("disableAllHooks", done.stderr)
                if name == "filtered":
                    self.assertIn("if filter", done.stderr)

    def test_the_real_launcher_starts_a_session_only_on_the_host_settings(self):
        for name in ("linked", "default", "divergent", "divergent, not required"):
            with self.subTest(name):
                project = EngineProject(self)
                project.env.pop("CLAUDE_ACCOUNT", None)
                copy_roles(project, "implementer")
                launcher = project.bin / "claude-account"
                launcher.write_text(f"#!/bin/sh\nexec bash {LAUNCHER_SOURCE} \"$@\"\n",
                                    encoding="utf-8")
                launcher.chmod(0o755)
                log = project.tmp / "claude.log"
                client = project.tmp / "client"
                client.write_text(f"#!/bin/sh\nexec {sys.executable} {STUB} {log} "
                                  f"{RESULT_NORMAL} - 0 - - \"$@\"\n", encoding="utf-8")
                client.chmod(0o755)
                project.env.update(CLAUDE_BIN=str(client),
                                   CLAUDE_ACCOUNTS_DIR=str(project.tmp / "accounts"),
                                   CLAUDE_CACHE_PROXY="0")
                project.env.pop("CLAUDE_CONFIG_DIR", None)
                profile = project.tmp / "accounts/profiles/acct"
                profile.mkdir(parents=True)
                project.env["CLAUDE_ACCOUNT"] = "default" if name == "default" else "acct"
                if name.startswith("divergent"):
                    (profile / "settings.json").write_text("{}", encoding="utf-8")
                if name == "divergent, not required":
                    done = subprocess.run(
                        [str(launcher), "run", "--version"], capture_output=True, timeout=60,
                        stdin=subprocess.DEVNULL,
                        env={k: v for k, v in project.env.items()
                             if k != "CLAUDE_ACCOUNT_HOST_SETTINGS"})
                    self.assertEqual(done.returncode, 0, done.stderr)
                    lines = self.log(log)
                    self.assertEqual(len(lines), 1)
                    self.assertEqual(lines[0]["config_dir"], str(profile))
                    continue
                done = project.deliver(one_step(project), issue=1514)
                if name == "divergent":
                    self.assertEqual(done.returncode, 1, done.stderr)
                    self.assertEqual(done.stdout, "")
                    self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                    self.assertIn("no structured reply", done.stderr)
                    self.assertIn("lifecycle guard", done.stderr)
                    self.assertFalse(log.exists())
                    self.assertEqual((profile / "settings.json").read_text(encoding="utf-8"),
                                     "{}")
                    continue
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(json.loads(done.stdout)["end"], "done")
                lines = self.log(log)
                self.assertEqual(len(lines), 1)
                self.assertEqual(lines[0]["host_settings"], "required")
                if name == "linked":
                    self.assertEqual(lines[0]["config_dir"], str(profile))
                    self.assertTrue(os.path.samefile(
                        Path(lines[0]["config_dir"]) / "settings.json",
                        project.world.home / ".claude/settings.json"))
                else:
                    self.assertIsNone(lines[0]["config_dir"])

    def test_a_caller_config_dir_never_reaches_a_session(self):
        custom = self.project.tmp / "custom"
        custom.mkdir()
        (custom / "settings.json").write_text("{}", encoding="utf-8")
        self.project.env["CLAUDE_CONFIG_DIR"] = str(custom)
        log = install_stub(self.project, RESULT_MISSING, resumed=canned_result(
            structured_output={"status": "drafted", "summary": "s", "items": []}))
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = self.log(log)
        self.assertEqual(len(lines), 2)
        self.assertEqual([line["config_dir"] for line in lines], [None, None])
        self.assertEqual([line["host_settings"] for line in lines], ["required", "required"])
        self.assertIn("--resume", lines[1]["argv"])

    def test_a_missing_answer_then_a_valid_one_resumes_the_same_session_once(self):
        log = install_stub(self.project, RESULT_MISSING, resumed=canned_result(
            structured_output={"status": "stuck", "summary": "s", "items": []}))
        procedures = one_step(self.project)
        done = self.project.deliver(procedures, issue=1514)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "needs-owner")
        first, second = self.log(log)
        run = self.run_dir()
        session = after(first["argv"], "--session-id")
        self.assertNotIn("--resume", first["argv"])
        self.assertEqual(after(second["argv"], "--resume"), session)
        self.assertNotIn("--session-id", second["argv"])
        swapped = list(first["argv"])
        swapped[swapped.index("--session-id")] = "--resume"
        self.assertEqual(second["argv"], swapped)
        self.assertTrue(second["announced"])
        self.assertEqual(second["stdin"],
                         (run / "sessions/draft.1.resume.prompt.md").read_text(encoding="utf-8"))
        self.assertNotEqual(second["stdin"], first["stdin"])
        events = self.project.events(run)
        self.assertEqual(shape(events), [
            ("step_entered", "draft", 1), ("session_starting", "draft", 1),
            ("process_started", "draft", 1), ("session_answered", "draft", 1),
            ("session_resuming", "draft", 1), ("process_started", "draft", 1),
            ("session_answered", "draft", 1), ("result_stored", "draft", 1),
            ("outcome_graded", "draft", 1), ("transition_taken", "draft", 1),
            ("stop_reached", "draft", None)])
        self.assertEqual(self.kinds().count("step_entered"), 1)
        self.assertEqual(json.loads((run / "results/draft.1.json").read_text()),
                         {"status": "stuck", "summary": "s", "items": []})
        self.assertFalse((run / "results/draft.2.json").exists())

    def test_two_misses_give_no_reply_and_the_step_failed_stop_after_two_invocations(self):
        log = install_stub(self.project, RESULT_MISSING, resumed=canned_result(
            structured_output=..., result="Status: still prose.", duration_ms=1000, num_turns=2,
            total_cost_usd=0.1,
            usage={"input_tokens": 1, "cache_creation_input_tokens": 2,
                   "cache_read_input_tokens": 3, "output_tokens": 4}))
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 3, done.stderr)
        stopped = json.loads(done.stdout)
        self.assertEqual((stopped["end"], stopped["need"]), ("step-failed", "retry"))
        first, second = self.log(log)
        run = self.run_dir()
        self.assertEqual(after(second["argv"], "--resume"), after(first["argv"], "--session-id"))
        events = self.project.events(run)
        (graded,) = [e for e in events if e["event"] == "outcome_graded"]
        (taken,) = [e for e in events if e["event"] == "transition_taken"]
        self.assertEqual((graded["outcome"], taken["to"]), ("no-reply", "step-failed"))
        self.assertEqual(json.loads((run / "results/draft.1.json").read_text()), {})
        for name, prose in (("draft.1.json", "Status: drafted. Done."),
                            ("draft.1.resume.json", "Status: still prose.")):
            record = json.loads((run / "sessions" / name).read_text(encoding="utf-8"))
            self.assertEqual((record["prose"], record["problem"]),
                             (prose, "no structured_output"))
        (stored,) = [e for e in events if e["event"] == "result_stored"]
        self.assertAlmostEqual(stored["wall_seconds"], 13.345)
        self.assertEqual(stored["turns"], 9)
        self.assertEqual(stored["tokens"], {"input": 12, "cache_write": 24, "cache_read": 36,
                                            "output": 48})
        self.assertAlmostEqual(stored["spend_usd"], 0.5321)

    def test_the_clients_structured_output_retries_exhausted_is_a_miss(self):
        exhausted = canned_result(
            structured_output=..., subtype="error_max_structured_output_retries", is_error=True,
            terminal_reason="structured_output_retry_exhausted", result="Status: drafted.")
        log = install_stub(self.project, exhausted, exit=1)
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "step-failed")
        first, second = self.log(log)
        self.assertNotIn("--resume", first["argv"])
        self.assertEqual(after(second["argv"], "--resume"), after(first["argv"], "--session-id"))
        graded = [e for e in self.project.events(self.run_dir()) if e["event"] == "outcome_graded"]
        self.assertEqual([e["outcome"] for e in graded], ["no-reply"])
        with self.subTest("then valid"):
            project = EngineProject(self)
            project.env.pop("CLAUDE_ACCOUNT", None)
            copy_roles(project, "implementer")
            log = install_stub(project, exhausted, exit=1, resumed=canned_result(
                structured_output={"status": "drafted", "summary": "s", "items": []}))
            done = project.deliver(one_step(project), issue=1514)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads(done.stdout)["end"], "done")
            self.assertEqual(len(self.log(log)), 2)

    def test_a_reply_that_breaks_its_schema_is_a_miss_though_the_client_returned_it(self):
        exhausted = {"on": {"drafted": "done", "stuck": "needs-owner", "exhausted": "needs-owner"},
                     "max_visits": 2}
        cases = {
            "extra member": (RESULT_INVALID, {}),
            "value outside the enum": (canned_result(structured_output={
                "status": "maybe", "summary": "s", "items": []}), {}),
            "missing members": (canned_result(structured_output={"status": "drafted"}), {}),
            "wrong member type": (canned_result(structured_output={
                "status": "drafted", "summary": 3, "items": []}), {}),
            "wrong item type": (canned_result(structured_output={
                "status": "drafted", "summary": "s", "items": [1]}), {}),
            "not a string": (canned_result(structured_output={
                "status": ["drafted"], "summary": "s", "items": []}), {}),
            "exhausted": (canned_result(structured_output={
                "status": "exhausted", "summary": "s", "items": []}), exhausted),
        }
        for name, (canned, members) in cases.items():
            with self.subTest(name):
                project = EngineProject(self)
                project.env.pop("CLAUDE_ACCOUNT", None)
                copy_roles(project, "implementer")
                log = install_stub(project, canned)
                done = project.deliver(one_step(project, **members), issue=1514)
                self.assertEqual(done.returncode, 3, done.stderr)
                self.assertEqual(json.loads(done.stdout)["end"], "step-failed")
                self.assertEqual(len(self.log(log)), 2)
                graded = [e for e in project.events(project.runs()[0])
                          if e["event"] == "outcome_graded"]
                self.assertEqual([e["outcome"] for e in graded], ["no-reply"])

    def test_a_usable_first_answer_launches_once(self):
        log = install_stub(self.project, RESULT_NORMAL, resumed=RESULT_MISSING)
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.log(log)), 1)
        self.assertNotIn("session_resuming", self.kinds())

    def test_a_result_that_is_not_a_success_and_has_no_reply_is_a_fault_with_no_resume(self):
        for subtype in ("error_during_execution",):
            with self.subTest(subtype):
                project = EngineProject(self)
                project.env.pop("CLAUDE_ACCOUNT", None)
                copy_roles(project, "implementer")
                log = install_stub(project, canned_result(
                    structured_output=..., subtype=subtype, is_error=True), exit=1)
                done = project.deliver(one_step(project), issue=1514)
                self.assertEqual(done.returncode, 1)
                self.assertEqual(done.stdout, "")
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertIn("draft", done.stderr)
                self.assertEqual(len(self.log(log)), 1)
                self.assertNotIn("session_resuming", self.kinds(project))

    def test_a_success_flagged_as_an_error_with_no_reply_is_a_fault_not_a_miss(self):
        log = install_stub(self.project, canned_result(structured_output=..., is_error=True),
                           exit=1, diagnostic="client failed\n")
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertIn("draft", done.stderr)
        self.assertEqual(len(self.log(log)), 1)
        kinds = self.kinds()
        for kind in ("session_resuming", "result_stored", "outcome_graded"):
            self.assertNotIn(kind, kinds)

    def test_a_success_flagged_as_an_error_is_a_fault_on_the_resume_too(self):
        log = install_stub(self.project, RESULT_MISSING,
                           resumed=canned_result(structured_output=..., is_error=True), exit=0)
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(len(self.log(log)), 2)
        self.assertNotIn("outcome_graded", self.kinds())

    def test_an_integral_float_answer_for_an_integer_member_is_a_usable_reply(self):
        schema = {**DRAFT_REPLY, "properties": {**DRAFT_REPLY["properties"],
                                                "n": {"type": "integer"}},
                  "required": [*DRAFT_REPLY["required"], "n"]}
        procedures = write_procedures(
            self.project, [agent_step("draft", "implementer",
                                      {"drafted": "done", "stuck": "needs-owner"})],
            {"draft.md": "Draft issue {{run.issue}}.\n", "draft.reply.json": json.dumps(schema)})
        log = install_stub(self.project, RESULT_MISSING, resumed=canned_result(
            structured_output={"status": "drafted", "summary": "s", "items": [], "n": 2.0}))
        done = self.project.deliver(procedures, issue=1514)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.log(log)), 2)
        stored = json.loads((self.run_dir() / "results/draft.1.json").read_text())
        self.assertEqual(stored, {"status": "drafted", "summary": "s", "items": [], "n": 2})
        self.assertIs(type(stored["n"]), int)
        self.assertEqual([e["outcome"] for e in self.project.events(self.run_dir())
                          if e["event"] == "outcome_graded"], ["drafted"])

    def test_settings_that_lose_the_guard_during_a_run_stop_the_resume(self):
        project = self.project
        install_stub(project, RESULT_MISSING, resumed=RESULT_NORMAL)
        procedures = one_step(project)
        real = engine_session.launch
        launches: list[list[str]] = []

        def losing(argv, cwd, prompt, *, on_start, **options):
            launches.append(list(argv))
            launched = real(argv, cwd, prompt, on_start=on_start, **options)
            project.use_settings_text(json.dumps({"hooks": {"PreToolUse": []}}))
            return launched

        with project.inside(), mock.patch.object(engine_session, "launch", side_effect=losing):
            with self.assertRaises(engine_shell.Fault) as caught:
                engine_shell.deliver(1514, procedures)
        self.assertEqual(len(launches), 1)
        self.assertIn("lifecycle guard", str(caught.exception))
        self.assertIn("draft", str(caught.exception))
        self.assertEqual(self.kinds().count("process_started"), 1)
        self.assertNotIn("outcome_graded", self.kinds())

    def test_settings_that_lose_the_guard_during_a_run_stop_the_next_agent_step(self):
        project = self.project
        install_stub(project, RESULT_NORMAL)
        procedures = write_procedures(project, [
            agent_step("draft", "implementer", {"drafted": "second", "stuck": "needs-owner"}),
            agent_step("second", "implementer", {"drafted": "done", "stuck": "needs-owner"})])
        real = engine_session.launch
        launches: list[list[str]] = []

        def losing(argv, cwd, prompt, *, on_start, **options):
            launches.append(list(argv))
            launched = real(argv, cwd, prompt, on_start=on_start, **options)
            project.use_settings_text(json.dumps({"hooks": {"PreToolUse": []}}))
            return launched

        with project.inside(), mock.patch.object(engine_session, "launch", side_effect=losing):
            with self.assertRaises(engine_shell.Fault) as caught:
                engine_shell.deliver(1514, procedures)
        self.assertEqual(len(launches), 1)
        self.assertIn("second", str(caught.exception))
        self.assertNotIn("process_started", [
            e["event"] for e in self.project.events(self.run_dir()) if e["step"] == "second"])

    def test_an_object_that_is_not_a_result_is_a_fault_with_no_resume(self):
        log = install_stub(self.project, canned_result(type="assistant", structured_output=...))
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertIn("draft", done.stderr)
        self.assertEqual(len(self.log(log)), 1)
        kinds = self.kinds()
        for kind in ("session_resuming", "result_stored", "outcome_graded"):
            self.assertNotIn(kind, kinds)

    def test_a_denied_shell_command_on_the_resume_is_a_fault(self):
        denial = {"tool_name": "Bash", "tool_use_id": "t", "tool_input": {"command": "rm -rf x"}}
        log = install_stub(self.project, RESULT_MISSING,
                           resumed=canned_result(permission_denials=[denial]))
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertIn("draft", done.stderr)
        self.assertEqual(len(self.log(log)), 2)
        self.assertNotIn("outcome_graded", self.kinds())

    def test_the_resume_is_on_disk_before_its_launch(self):
        project = self.project
        install_stub(project, RESULT_MISSING, resumed=canned_result(
            structured_output={"status": "drafted", "summary": "s", "items": []}))
        procedures = one_step(project)
        real = engine_session.launch
        seen: list[tuple] = []

        def checking(argv, cwd, prompt, *, on_start, **options):
            (run,) = project.runs()
            last = engine_ledger.replay(run / "events.jsonl")[-1]
            seen.append((last["event"], last.get("session"), list(argv)))
            return real(argv, cwd, prompt, on_start=on_start, **options)

        with project.inside(), mock.patch.object(engine_session, "launch", side_effect=checking):
            code, line = engine_shell.deliver(1514, procedures)
        self.assertEqual(code, 0, line)
        self.assertEqual(len(seen), 2)
        last, session, argv = seen[1]
        self.assertEqual(last, "session_resuming")
        self.assertEqual(session, after(argv, "--resume"))

    def test_a_role_file_that_does_not_read_refuses_the_run_before_any_session(self):
        for name in ("no file", "a model that is an option"):
            with self.subTest(name):
                project = EngineProject(self)
                project.env.pop("CLAUDE_ACCOUNT", None)
                if name != "no file":
                    copy_roles(project, "implementer")
                    path = project.world.home / ".claude/agents/implementer.md"
                    path.write_text(re.sub(r"^model: .*$", "model: --dangerously-skip-permissions",
                                           path.read_text(encoding="utf-8"), flags=re.M),
                                    encoding="utf-8")
                log = install_stub(project, RESULT_NORMAL)
                done = project.deliver(one_step(project), issue=1514)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertEqual(done.stdout, "")
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertIn("implementer", done.stderr)
                self.assertEqual(project.runs(), [])
                self.assertFalse(log.exists())

    def test_the_deliver_help_names_agent_steps(self):
        text = " ".join(engine.build_parser().format_help().split())
        self.assertIn(
            "run a procedure of command, agent, decide, group and call steps to done or a stop",
            text)
