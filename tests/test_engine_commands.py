"""Contract tests for the engine's command table and grading (`engine_commands`, #1512).

Platform ids run as their packaged sibling modules and project ids as their
snapshot argv; the stand-in script under tests/fixtures/engine-deliver stands
for a project command (agent-helpers rule 5).
"""

from __future__ import annotations

import _thread
import ast
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_caps, engine_commands
from agent_tools.delivery.engine_commands import (
    PLATFORM_MODULES, CommandTable, Invocation, UnknownCommand, argument, command_text, grade,
    run)
from agent_tools.delivery.engine_guard import Hook, Unavailable, locate
from agent_tools.delivery.procedure_check import load_commands
from agent_tools.system.siblings import sibling_argv
from tests.engine_guards import (
    GUARD_NAME, STANDIN_GUARD, payloads, script, standin_guard, write_settings)

TIER = "fast"

REPO_ROOT = Path(__file__).resolve().parents[1]
STANDIN = REPO_ROOT / "tests/fixtures/engine-deliver/standin.py"


def project(*words: str, cwd: str = "/tmp") -> dict:
    return {"argv": [sys.executable, str(STANDIN), *words], "cwd": cwd, "env": []}


def table(**entries: dict) -> CommandTable:
    return CommandTable(PLATFORM_MODULES, entries, "/root")


class TableTest(unittest.TestCase):
    def test_a_platform_id_runs_as_its_sibling_module_with_its_subcommand_then_its_arguments(self):
        invocation = table().invocation(
            "forge-claim", "status", (("run.issue", 1512), ("run.repo", "o/r")))
        self.assertEqual(invocation, Invocation(
            (*sibling_argv("claims.forge_claim"), "status", "1512", "o/r"), "/root"))
        self.assertEqual(invocation.argv[0], sys.executable)

    def test_a_project_id_runs_its_snapshot_argv_in_its_cwd(self):
        entry = project("json", "0", cwd="/somewhere")
        invocation = table(**{"standin-json": entry}).invocation(
            "standin-json", None, (("run.issue", 7),))
        self.assertEqual(invocation.argv, (sys.executable, str(STANDIN), "json", "0", "7"))
        self.assertEqual(invocation.cwd, entry["cwd"])

    def test_the_platform_table_wins_over_a_project_id(self):
        invocation = table(**{"diff-scope": project("json", "0")}).invocation(
            "diff-scope", None, ())
        self.assertEqual(
            invocation, Invocation(tuple(sibling_argv("delivery.diff_scope")), "/root"))

    def test_an_id_in_neither_table_starts_no_process(self):
        on_start = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "guard.log"
            allow = Hook(str(standin_guard(Path(directory), "g", "allow", str(log))), 5)
            with mock.patch.object(engine_commands.subprocess, "Popen", mock.Mock()) as popen:
                with self.assertRaises(UnknownCommand):
                    run(table(), "no-such-command", None, (), guard=allow, on_start=on_start)
                popen.assert_not_called()
            self.assertFalse(log.exists())
        on_start.assert_not_called()
        with self.assertRaises(UnknownCommand):
            table(**{"standin-json": project("json", "0")}).invocation("standin-json", "x", ())

    def test_declarations_grade_project_ids_ok_or_failed_under_the_platform_table(self):
        declarations = table(**{"standin-json": project("json", "0"),
                                "diff-scope": project("json", "0"),
                                "forge-claim": project("json", "0")}).declarations()
        platform = load_commands()
        self.assertEqual(set(declarations), set(platform) | {"standin-json"})
        self.assertEqual(declarations["standin-json"].outcomes(None), ("ok", "failed"))
        self.assertIsNone(declarations["standin-json"].outcomes("x"))
        self.assertEqual(declarations["forge-claim"], platform["forge-claim"])
        self.assertEqual(declarations["diff-scope"], platform["diff-scope"])

    def test_a_project_id_the_platform_declares_without_a_table_row_is_a_runnable_project_id(self):
        self.assertIsNone(load_commands()["release"])
        built = table(release=project("json", "0"))
        self.assertEqual(built.declarations()["release"].outcomes(None), ("ok", "failed"))
        self.assertEqual(built.invocation("release", None, ()).argv[-2:], ("json", "0"))

    def test_from_snapshot_reads_the_commands_and_the_root(self):
        commands = {"a": {"argv": ["a"], "cwd": "/p", "env": []}}
        built = CommandTable.from_snapshot({
            "project": {"root": "/p", "id": "x", "name": "x"},
            "bindings": {"commands": commands}})
        self.assertEqual(built.root, "/p")
        self.assertEqual(built.project, commands)
        self.assertEqual(built.platform, PLATFORM_MODULES)

    def test_the_platform_modules_mirror_the_command_table_rows_of_every_declared_id(self):
        rows = dict(re.findall(r'^\s+"([a-z0-9-]+)" = "([a-z_.]+)";$',
                               (REPO_ROOT / "lib/agent-tools.nix").read_text("utf-8"), re.M))
        declared = {name for name, declaration in load_commands().items()
                    if declaration is not None}
        self.assertEqual(set(PLATFORM_MODULES), declared)
        for name in declared:
            self.assertEqual(PLATFORM_MODULES[name], rows[name])


class GuardTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)

    def test_a_refused_command_starts_no_process_and_carries_the_guard_text(self):
        d = self.tmp
        entry = project("record", str(d / "record.log"), cwd=str(d))
        guard = Hook(str(standin_guard(d, "g", "refuse", str(d / "guard.log"),
                                       "lifecycle guard: no.")), 5)
        on_start = mock.Mock()
        ran = run(table(record=entry), "record", None, (("run.issue", 7),),
                  guard=guard, on_start=on_start)
        self.assertEqual((ran.outcome, ran.result, ran.exit_code),
                         ("refused", {"reason": "lifecycle guard: no.", "verdict": "refused"},
                          None))
        on_start.assert_not_called()
        self.assertFalse((d / "record.log").exists())
        judged = table(record=entry).invocation("record", None, (("run.issue", 7),)).argv
        self.assertEqual(payloads(d / "guard.log")[0]["payload"]["tool_input"]["command"],
                         command_text(judged))

    def allow(self, name: str = "allow", log: str | None = None) -> Hook:
        return Hook(str(standin_guard(self.tmp, name, "allow", log or str(self.tmp / "g.log"))), 5)

    def test_command_text_writes_the_guards_accepted_spelling_and_splits_back(self):
        release = ["gh", "release", "create", "v1.0.0", "--repo", "o/r", "--verify-tag",
                   "--title", "v1.0.0", "--notes-file", "/tmp/n.md"]
        rows = [
            (release, 'gh release create v1.0.0 --repo o/r --verify-tag --title "v1.0.0" '
                      '--notes-file /tmp/n.md'),
            ([*release[:8], "Release 1.0", *release[9:]],
             'gh release create v1.0.0 --repo o/r --verify-tag --title "Release 1.0" '
             '--notes-file /tmp/n.md'),
            (["gh", "pr", "merge", "7", "--repo", "o/r", "--merge", "--subject", "Land",
              "--delete-branch"],
             'gh pr merge 7 --repo o/r --merge --subject "Land" --delete-branch'),
            ([*release[:8], "--body", *release[9:]],
             'gh release create v1.0.0 --repo o/r --verify-tag --title "--body" '
             '--notes-file /tmp/n.md'),
            (["x", "--title", "--title", "t"], 'x --title "--title" t'),
            (["git", "branch", "-d", "issue-7-topic"], "git branch -d issue-7-topic"),
            (["x", "a b'c"], 'x "a b\'c"'),
            (["x", ""], 'x ""'),
            (["x", 'say "hi"'], "x 'say \"hi\"'"),
            (["x", "a\\b"], "x 'a\\b'"),
            (["x", "$HOME"], "x '$HOME'"),
            (["x", "--title", "a $b"], "x --title 'a $b'"),
        ]
        for argv, text in rows:
            with self.subTest(argv=argv):
                self.assertEqual(command_text(argv), text)
                self.assertEqual(shlex.split(text), list(argv))

    def test_command_text_means_the_same_words_to_a_shell(self):
        argvs = [
            ["gh", "release", "create", "v1.0.0", "--repo", "o/r", "--verify-tag", "--title",
             "--body", "--notes-file", "/tmp/n.md"],
            ["gh", "pr", "merge", "7", "--repo", "o/r", "--merge", "--subject", "Land",
             "--delete-branch"],
            ["git", "branch", "-d", "issue-7-topic"],
            ["x", "--title", "--title", "t"],
            ["x", "a b'c"], ["x", ""], ["x", 'say "hi"'], ["x", "a\\b"], ["x", "$HOME"],
            ["x", "--title", "a $b"],
            ["x", "it's", "a\nb", "`id`", "!x", "*", "~", "--title", 'it\'s "q"'],
        ]
        for argv in argvs:
            with self.subTest(argv=argv):
                done = subprocess.run(
                    ["/bin/sh", "-c", "printf '%s\\0' " + command_text(argv[1:])],
                    capture_output=True, check=True)
                words = done.stdout.decode("utf-8").split("\0")
                self.assertEqual(words[:-1], argv[1:])

    def test_a_command_runs_marked_as_an_agent_session(self):
        d = self.tmp
        entry = {"argv": ["/bin/sh", "-c", 'printf %s "$CLAUDECODE" > "$0"', str(d / "marker")],
                 "cwd": str(d), "env": []}
        for value, expected in ((None, "1"), ("7", "7")):
            with self.subTest(value=value), mock.patch.dict(os.environ):
                os.environ.pop("CLAUDECODE", None)
                if value:
                    os.environ["CLAUDECODE"] = value
                (d / "marker").unlink(missing_ok=True)
                ran = run(table(mark=entry), "mark", None, (), guard=self.allow(),
                          on_start=lambda pid: None)
                self.assertEqual(ran.exit_code, 0)
                self.assertEqual((d / "marker").read_text(), expected)

    def test_a_text_that_does_not_split_back_to_its_argv_is_refused_before_the_guard(self):
        d = self.tmp
        on_start = mock.Mock()
        entry = project("record", str(d / "record.log"), cwd=str(d))
        with mock.patch("agent_tools.delivery.engine_commands.command_text",
                        return_value="echo other"):
            ran = run(table(record=entry), "record", None, (),
                      guard=self.allow(log=str(d / "guard.log")), on_start=on_start)
        self.assertEqual(ran.outcome, "refused")
        self.assertTrue(ran.result["reason"])
        self.assertIsNone(ran.exit_code)
        on_start.assert_not_called()
        self.assertEqual(payloads(d / "guard.log"), [])

    def test_an_allowed_command_runs_the_text_the_guard_judged(self):
        d = self.tmp
        entry = project("record", str(d / "record.log"), cwd=str(d))
        on_start = mock.Mock()
        ran = run(table(record=entry), "record", None, (("run.title", "a b'c"),),
                  guard=self.allow(log=str(d / "guard.log")), on_start=on_start)
        expected = [sys.executable, str(STANDIN), "record", str(d / "record.log"), "a b'c"]
        logged = payloads(d / "guard.log")
        self.assertEqual(len(logged), 1)
        command = logged[0]["payload"]["tool_input"]["command"]
        self.assertEqual(command, command_text(expected))
        self.assertEqual(shlex.split(command), expected)
        self.assertEqual(logged[0]["payload"]["cwd"], str(d))
        self.assertEqual(logged[0]["cwd"], os.path.realpath(d))
        lines = [json.loads(line) for line in (d / "record.log").read_text().splitlines()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["argv"], ["a b'c"])
        self.assertEqual(lines[0]["cwd"], os.path.realpath(d))
        on_start.assert_called_once_with(lines[0]["pid"])
        self.assertEqual(ran.outcome, "ok")

    def test_an_unavailable_guard_is_refused_and_starts_nothing(self):
        d = self.tmp
        guards = {
            "unavailable": Unavailable("The host settings name no lifecycle guard."),
            "arguments": locate(write_settings(
                d / "h1", str(d / f"x/bin/{GUARD_NAME}"), extra={"args": ["--x"]})),
            "nul": locate(write_settings(d / "h2", f"/g\x00x/bin/{GUARD_NAME}")),
            "other hook": locate(write_settings(d / "h3", str(script(
                d / "other-hook", sys.executable, str(STANDIN_GUARD), "allow",
                str(d / "other.log"))))),
            "nul hook": Hook("/bin/g\x00x", 5),
        }
        for name, guard in guards.items():
            with self.subTest(name):
                on_start = mock.Mock()
                entry = project("record", str(d / "record.log"), cwd=str(d))
                ran = run(table(record=entry), "record", None, (), guard=guard,
                          on_start=on_start)
                self.assertEqual(ran.outcome, "refused")
                self.assertTrue(ran.result["reason"])
                if isinstance(guard, Unavailable):
                    self.assertEqual(ran.result["reason"], guard.reason)
                self.assertIsNone(ran.exit_code)
                self.assertFalse((d / "record.log").exists())
                on_start.assert_not_called()
        self.assertEqual(payloads(d / "other.log"), [])


PROCESS_ATTRS = ("exec", "spawn", "posix_spawn", "system", "popen", "fork")


def _callee(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_callee(node.value)}.{node.attr}"
    return node.id if isinstance(node, ast.Name) else "?"


def _is_process_call(callee: str) -> bool:
    head, _, attr = callee.partition(".")
    if head in ("subprocess", "pty", "multiprocessing"):
        return True
    return head == "os" and attr.startswith(PROCESS_ATTRS)


def spawn_sites(sources: dict[str, str]) -> list[tuple[str, str, str]]:
    """Each process-starting call (and each import that could hide one) of every module."""
    found: list[tuple[str, int, str, str]] = []

    def visit(module: str, node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                else function
            if isinstance(child, ast.Call) and _is_process_call(_callee(child.func)):
                found.append((module, child.lineno, function, _callee(child.func)))
            elif isinstance(child, ast.ImportFrom):
                for alias in child.names:
                    if child.module == "subprocess" or (
                            child.module == "os" and alias.name.startswith(PROCESS_ATTRS)):
                        found.append((module, child.lineno, "<import>",
                                      f"from {child.module} import {alias.name}"))
            elif isinstance(child, ast.Import):
                for alias in child.names:
                    root = alias.name.split(".")[0]
                    if root in ("pty", "multiprocessing") or (
                            root == "subprocess" and alias.asname):
                        found.append((module, child.lineno, "<import>", alias.name))
            visit(module, child, inner)

    for module in sorted(sources):
        visit(module, ast.parse(sources[module]), "<module>")
    return [(module, function, callee) for module, _, function, callee in sorted(found)]


def unguarded_launches(source: str) -> list[int]:
    """The lines of `engine_session.launch` calls whose first argument is not `launch_argv(...)`."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _callee(node.func) == "engine_session.launch":
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Call)
                    and _callee(first.func) == "engine_session.launch_argv"):
                lines.append(node.lineno)
    return lines


def unguarded_in(sources: dict[str, str]) -> dict[str, list[int]]:
    """The unguarded `engine_session.launch` lines of every module, by module."""
    return {name: lines for name, source in sources.items()
            if (lines := unguarded_launches(source))}


class SpawnSiteTest(unittest.TestCase):
    def sources(self) -> dict[str, str]:
        package = Path(engine_commands.__file__).parent
        return {path.name: path.read_text(encoding="utf-8")
                for path in engine_caps.engine_modules(package)}

    def test_only_the_command_guard_and_session_modules_start_processes(self):
        sources = self.sources()
        expected = [("engine_commands.py", "run", "subprocess.Popen"),
                    ("engine_guard.py", "_descendants", "subprocess.run"),
                    ("engine_guard.py", "judge", "subprocess.Popen"),
                    ("engine_session.py", "launch", "subprocess.Popen")]
        self.assertEqual(spawn_sites(sources), expected)
        self.assertEqual(unguarded_in(sources), {})
        plants = {
            "a second Popen in run": ("engine_commands.py", lambda text: text.replace(
                "    text = command_text(invocation.argv)\n",
                '    subprocess.Popen(["true"])\n    text = command_text(invocation.argv)\n', 1)),
            "a new function running a process": ("engine_commands.py", lambda text: text
                + '\n\ndef extra():\n    subprocess.run(["true"])\n'),
            "a from-import of Popen": ("engine_shell.py", lambda text: text.replace(
                "import socket\n", "import socket\nfrom subprocess import Popen\n", 1)),
        }
        for name, (module, change) in plants.items():
            with self.subTest(name):
                planted = {**sources, module: change(sources[module])}
                self.assertNotEqual(planted[module], sources[module])
                self.assertNotEqual(spawn_sites(planted), expected)
        for module in ("engine_shell.py", "engine_commands.py", "engine_core.py"):
            with self.subTest(f"a launch with a literal argv in {module}"):
                planted = {**sources, module: sources[module] + (
                    '\n\ndef extra(root, prompt, started):\n'
                    '    engine_session.launch(["x"], root, prompt, on_start=started)\n')}
                self.assertEqual(list(unguarded_in(planted)), [module])


class GradeTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = directory.name
        self.allow = Hook(str(standin_guard(Path(self.tmp), "allow", "allow",
                                            os.path.join(self.tmp, "allow.log"))), 5)

    def test_three_stand_ins_are_graded_by_verdict_or_by_exit_code(self):
        entries = {
            "says-failed": project("verdict", "failed", "0", cwd=self.tmp),
            "json-ok": project("json", "0", cwd=self.tmp),
            "silent-fail": project("silent", "3", cwd=self.tmp),
            "ok-at-one": project("verdict", "ok", "1", cwd=self.tmp),
        }
        commands = table(**entries)
        args = (("run.issue", 5),)
        failed = run(commands, "says-failed", None, args, guard=self.allow, on_start=lambda pid: None)
        self.assertEqual((failed.outcome, failed.exit_code, failed.result),
                         ("failed", 0, {"argv": ["5"], "verdict": "failed"}))
        ok = run(commands, "json-ok", None, args, guard=self.allow, on_start=lambda pid: None)
        self.assertEqual((ok.outcome, ok.exit_code, ok.result), ("ok", 0, {"argv": ["5"]}))
        silent = run(commands, "silent-fail", None, args, guard=self.allow, on_start=lambda pid: None)
        self.assertEqual((silent.outcome, silent.exit_code, silent.result), ("failed", 3, {}))
        one = run(commands, "ok-at-one", None, args, guard=self.allow, on_start=lambda pid: None)
        self.assertEqual((one.outcome, one.exit_code), ("ok", 1))

    def test_grade_reads_only_a_strict_json_object(self):
        cases = [
            ((b'{"verdict":"x","verdict":"y"}', 0), ("ok", {})),
            ((b"[1]", 1), ("failed", {})),
            ((b'{"verdict": 5}', 0), ("ok", {"verdict": 5})),
            ((b'{"verdict": ""}', 2), ("failed", {"verdict": ""})),
            ((b"not json", 0), ("ok", {})),
            ((b'{"a": NaN}', 0), ("ok", {})),
            ((b"\xff", 0), ("ok", {})),
            ((b' {"verdict":"stale"}\n', 1), ("stale", {"verdict": "stale"})),
        ]
        for (stdout, code), expected in cases:
            with self.subTest(stdout=stdout, code=code):
                self.assertEqual(grade(stdout, code), expected)

    def test_on_start_receives_the_command_pid_and_the_cwd_is_honoured(self):
        log = Path(self.tmp) / "log"
        entry = project("record", str(log), cwd=self.tmp)
        pids: list[int] = []
        ran = run(table(record=entry), "record", None, (), guard=self.allow, on_start=pids.append)
        self.assertEqual(pids, [ran.result["pid"]])
        self.assertEqual(ran.result["cwd"], os.path.realpath(entry["cwd"]))
        self.assertGreaterEqual(ran.wall_seconds, 0)

    def test_an_executable_that_cannot_start_is_failed_and_reports_no_process(self):
        entry = {"argv": ["/nonexistent/engine-standin"], "cwd": self.tmp, "env": []}
        on_start = mock.Mock()
        ran = run(table(missing=entry), "missing", None, (), guard=self.allow, on_start=on_start)
        self.assertEqual((ran.outcome, ran.result, ran.exit_code), ("failed", {}, 127))
        on_start.assert_not_called()

    def test_a_failed_start_callback_kills_and_reaps_the_command(self):
        entry = project("block", os.path.join(self.tmp, "never-released"), cwd=self.tmp)
        pids: list[int] = []

        def refuse(pid: int) -> None:
            pids.append(pid)
            raise OSError("the ledger refused the event")

        with self.assertRaises(OSError):
            run(table(block=entry), "block", None, (), guard=self.allow, on_start=refuse)
        self.assertEqual(len(pids), 1)
        with self.assertRaises(ProcessLookupError):
            os.kill(pids[0], 0)

    def test_a_command_past_its_timeout_is_killed_with_its_group_and_keeps_its_output(self):
        pidfile = os.path.join(self.tmp, "grandchild")
        entry = project("hold", pidfile, "0", cwd=self.tmp)
        pids: list[int] = []
        started = time.monotonic()
        ran = run(table(hold=entry), "hold", None, (), guard=self.allow, on_start=pids.append, timeout=2)
        elapsed = time.monotonic() - started
        self.assertEqual(ran.outcome, "timeout")
        self.assertEqual(ran.outcome, engine_commands.TIMED_OUT)
        self.assertEqual(ran.result, {})
        self.assertNotEqual(ran.exit_code, 0)
        self.assertLess(elapsed, 20, "a grandchild held the pipes open")
        self.assertIn(b"marker-hold", ran.stdout)
        self.assertIn(b"marker-hold-err", ran.stderr)
        self.assertNotIn(b"marker-hold-err", ran.stdout)
        self.assertEqual(len(pids), 1)
        with self.assertRaises(ProcessLookupError):
            os.kill(pids[0], 0)
        grandchild = int(Path(pidfile).read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            self.fail("the grandchild outlived the timeout")

    def test_an_interrupted_timed_run_kills_its_group_before_the_interrupt_propagates(self):
        pidfile = os.path.join(self.tmp, "grandchild")
        entry = project("hold", pidfile, "0", cwd=self.tmp)
        pids: list[int] = []
        interrupt = threading.Timer(1.5, _thread.interrupt_main)
        interrupt.start()
        self.addCleanup(interrupt.cancel)
        with self.assertRaises(KeyboardInterrupt):
            run(table(hold=entry), "hold", None, (), guard=self.allow, on_start=pids.append, timeout=60)
        grandchild = int(Path(pidfile).read_text())
        deadline = time.monotonic() + 5
        for pid in (pids[0], grandchild):
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail(f"process {pid} outlived the interrupted run")

    def test_a_descendant_that_left_the_group_cannot_hold_the_run_open(self):
        pidfile = os.path.join(self.tmp, "grandchild")

        def kill_escapee() -> None:
            try:
                os.kill(int(Path(pidfile).read_text()), signal.SIGKILL)
            except (ProcessLookupError, FileNotFoundError, ValueError):
                pass

        self.addCleanup(kill_escapee)
        entry = project("hold", pidfile, "1", cwd=self.tmp)
        started = time.monotonic()
        ran = run(table(hold=entry), "hold", None, (), guard=self.allow, on_start=lambda pid: None, timeout=2)
        elapsed = time.monotonic() - started
        self.assertEqual(ran.outcome, "timeout")
        self.assertLess(elapsed, 20, "a descendant outside the group held the pipes open")
        self.assertIn(b"marker-hold", ran.stdout)

    def test_a_finished_command_carries_what_it_printed(self):
        entry = project("verdict", "renewed", "0", cwd=self.tmp)
        for options in ({"timeout": 60}, {}):
            with self.subTest(options=options):
                ran = run(table(says=entry), "says", None, (("run.issue", 5),),
                          guard=self.allow, on_start=lambda pid: None, **options)
                self.assertEqual(ran.stdout, b'{"argv":["5"],"verdict":"renewed"}\n')
                self.assertEqual(ran.stderr, b"")
                self.assertEqual((ran.outcome, ran.exit_code), ("renewed", 0))

    def test_arguments_are_text_integers_and_compact_json(self):
        self.assertEqual(argument("a b"), "a b")
        self.assertEqual(argument(7), "7")
        self.assertEqual(argument(True), "true")
        self.assertEqual(argument({"b": 1, "a": [2]}), '{"a":[2],"b":1}')


if __name__ == "__main__":
    unittest.main()
