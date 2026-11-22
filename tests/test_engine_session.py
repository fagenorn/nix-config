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
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine, engine_ledger, engine_session, engine_shell
from agent_tools.delivery.engine_session import (
    NOT_STARTED, Reading, Role, RoleError, diagnostic, launch, launch_argv, read_result,
    read_role, render_prompt,
)
from tests.test_engine_deliver import EngineProject, shape

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / "home/common/claude-code/agents"
STUB = REPO_ROOT / "tests/fixtures/engine-session/claude_stub.py"
RESULT_NORMAL = REPO_ROOT / "tests/fixtures/engine-session/result-normal.json"
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
            "--tools", "Read,Bash", "--allowedTools", f"Read,{GIT_READ_ONLY}",
            "--disallowedTools", GIT_WRITING,
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


DRAFT_REPLY = {"type": "object",
               "properties": {"status": {"enum": ["drafted", "stuck"]},
                              "summary": {"type": "string"},
                              "items": {"type": "array", "items": {"type": "string"}}},
               "required": ["status", "summary", "items"]}
REVIEW_REPLY = {"type": "object",
                "properties": {"verdict": {"enum": ["approve", "revise"]},
                               "status": {"type": "string"}},
                "required": ["verdict", "status"]}
ROLE_NAMES = ("planner", "implementer", "reviewer", "reviewer-lite")


def install_stub(project: EngineProject, canned: Path | bytes, exit: int | str = 0,
                 diagnostic: str | None = None) -> Path:
    """Put the stand-in launcher first on the project's PATH; return the log it appends to."""
    log = project.tmp / "claude.log"
    if not isinstance(canned, Path):
        data, canned = canned, project.tmp / "canned.json"
        canned.write_bytes(data)
    diagnostic_path = "-"
    if diagnostic is not None:
        diagnostic_path = str(project.tmp / "diagnostic.txt")
        Path(diagnostic_path).write_text(diagnostic, encoding="utf-8")
    launcher = project.bin / "claude-account"
    launcher.write_text(f"#!/bin/sh\nexec {sys.executable} {STUB} {log} {canned} {exit} "
                        f"{diagnostic_path} \"$@\"\n", encoding="utf-8")
    launcher.chmod(0o755)
    return log


def copy_roles(project: EngineProject, *names: str) -> None:
    directory = project.world.home / ".claude/agents"
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy(AGENTS / f"{name}.md", directory / f"{name}.md")


def agent_step(id: str, role: str, on: dict, **members) -> dict:
    document = {"id": id, "stage": "building", "kind": "agent", "role": role,
                "prompt": "draft.md", "reply": "draft.reply.json", "outcome_from": "status",
                "in": ["run.issue"], "on": on}
    document.update(members)
    return document


def write_procedures(project: EngineProject, steps: list[dict], files: dict | None = None) -> Path:
    directory = project.procedures(steps)
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

    def test_the_session_is_recorded_before_its_process_starts(self):
        log = install_stub(self.project, RESULT_NORMAL)
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 0, done.stderr)
        run = self.run_dir()
        self.assertEqual(shape(self.project.events(run)), [
            ("step_entered", "draft", 1), ("session_starting", "draft", 1),
            ("process_started", "draft", 1), ("result_stored", "draft", 1),
            ("outcome_graded", "draft", 1), ("transition_taken", "draft", 1),
            ("run_done", None, None)])
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

        def checking(argv, cwd, prompt, *, on_start, stop=None):
            (run,) = project.runs()
            events = engine_ledger.replay(run / "events.jsonl")
            seen.append((events[-1]["event"], events[-1].get("session"),
                         [e["event"] for e in events], after(list(argv), "--session-id")))
            return real(argv, cwd, prompt, on_start=on_start, stop=stop)

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

    def test_prose_with_no_structured_output_gives_no_outcome_and_no_transition(self):
        install_stub(self.project, canned_result(
            structured_output=..., result="Status: drafted. Done."),
            diagnostic="claude-stub: the model answered in prose only\n")
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertIn("draft", done.stderr)
        self.assertIn("claude-stub: the model answered in prose only", done.stderr)
        run = self.run_dir()
        kinds = [e["event"] for e in self.project.events(run)]
        for kind in ("session_starting", "process_started"):
            self.assertIn(kind, kinds)
        for kind in ("result_stored", "outcome_graded", "transition_taken", "run_done",
                     "stop_reached"):
            self.assertNotIn(kind, kinds)
        self.assertFalse((run / "results/draft.1.json").exists())
        record = json.loads((run / "sessions/draft.1.json").read_text(encoding="utf-8"))
        self.assertEqual(record["prose"], "Status: drafted. Done.")

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
            "session": self.starting()["session"], "subtype": "success"})

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
        install_stub(self.project, b"", exit=1, diagnostic=(
            "claude-account: no account 'work' (create it: /account add work, "
            "or claude-account add work)\n"))
        done = self.project.deliver(one_step(self.project), issue=1514)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        for word in ("draft", "exit 1", "no account 'work'"):
            self.assertIn(word, done.stderr)

    def test_an_outcome_the_step_cannot_map_is_a_fault_after_its_result_is_stored(self):
        cases = {
            "maybe": ("maybe", {}),
            "not a string": (["drafted"], {}),
            "exhausted": ("exhausted", {
                "on": {"drafted": "done", "stuck": "needs-owner", "exhausted": "needs-owner"},
                "max_visits": 2}),
        }
        for name, (status, members) in cases.items():
            with self.subTest(name):
                project = EngineProject(self)
                project.env.pop("CLAUDE_ACCOUNT", None)
                copy_roles(project, "implementer")
                reply = {"status": status, "summary": "s", "items": []}
                install_stub(project, canned_result(structured_output=reply))
                done = project.deliver(one_step(project, **members), issue=1514)
                self.assertEqual(done.returncode, 1)
                self.assertEqual(done.stdout, "")
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertIn("draft", done.stderr)
                (run,) = project.runs()
                events = project.events(run)
                self.assertEqual(json.loads((run / "results/draft.1.json").read_text()), reply)
                self.assertEqual((events[-1]["event"], events[-1]["step"]),
                                 ("result_stored", "draft"))
                kinds = [e["event"] for e in events]
                self.assertNotIn("outcome_graded", kinds)
                self.assertNotIn("transition_taken", kinds)

    def test_a_reply_that_breaks_its_schema_is_a_fault_before_any_grade(self):
        cases = {"missing members": {"status": "drafted"},
                 "wrong member type": {"status": "drafted", "summary": 3, "items": []},
                 "wrong item type": {"status": "drafted", "summary": "s", "items": [1]}}
        for name, reply in cases.items():
            with self.subTest(name):
                project = EngineProject(self)
                project.env.pop("CLAUDE_ACCOUNT", None)
                copy_roles(project, "implementer")
                install_stub(project, canned_result(structured_output=reply))
                done = project.deliver(one_step(project), issue=1514)
                self.assertEqual(done.returncode, 1)
                self.assertEqual(done.stdout, "")
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertIn("draft", done.stderr)
                self.assertIn("schema", done.stderr)
                kinds = [e["event"] for e in project.events(project.runs()[0])]
                self.assertNotIn("outcome_graded", kinds)
                self.assertNotIn("transition_taken", kinds)
                self.assertNotIn("run_done", kinds)

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
        self.assertIn("run a procedure of command, agent and decide steps to done or a stop", text)
