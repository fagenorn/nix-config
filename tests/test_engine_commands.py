"""Contract tests for the engine's command table and grading (`engine_commands`, #1512).

Platform ids run as their packaged sibling modules and project ids as their
snapshot argv; the stand-in script under tests/fixtures/engine-deliver stands
for a project command (agent-helpers rule 5).
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_commands
from agent_tools.delivery.engine_commands import (
    PLATFORM_MODULES, CommandTable, Invocation, UnknownCommand, argument, grade, run)
from agent_tools.delivery.procedure_check import load_commands
from agent_tools.system.siblings import sibling_argv

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
        with mock.patch.object(engine_commands.subprocess, "Popen", mock.Mock()) as popen:
            with self.assertRaises(UnknownCommand):
                run(table(), "no-such-command", None, (), on_start=on_start)
            popen.assert_not_called()
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


class GradeTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = directory.name

    def test_three_stand_ins_are_graded_by_verdict_or_by_exit_code(self):
        entries = {
            "says-failed": project("verdict", "failed", "0", cwd=self.tmp),
            "json-ok": project("json", "0", cwd=self.tmp),
            "silent-fail": project("silent", "3", cwd=self.tmp),
            "ok-at-one": project("verdict", "ok", "1", cwd=self.tmp),
        }
        commands = table(**entries)
        args = (("run.issue", 5),)
        failed = run(commands, "says-failed", None, args, on_start=lambda pid: None)
        self.assertEqual((failed.outcome, failed.exit_code, failed.result),
                         ("failed", 0, {"argv": ["5"], "verdict": "failed"}))
        ok = run(commands, "json-ok", None, args, on_start=lambda pid: None)
        self.assertEqual((ok.outcome, ok.exit_code, ok.result), ("ok", 0, {"argv": ["5"]}))
        silent = run(commands, "silent-fail", None, args, on_start=lambda pid: None)
        self.assertEqual((silent.outcome, silent.exit_code, silent.result), ("failed", 3, {}))
        one = run(commands, "ok-at-one", None, args, on_start=lambda pid: None)
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
        ran = run(table(record=entry), "record", None, (), on_start=pids.append)
        self.assertEqual(pids, [ran.result["pid"]])
        self.assertEqual(ran.result["cwd"], os.path.realpath(entry["cwd"]))
        self.assertGreaterEqual(ran.wall_seconds, 0)

    def test_an_executable_that_cannot_start_is_failed_and_reports_no_process(self):
        entry = {"argv": ["/nonexistent/engine-standin"], "cwd": self.tmp, "env": []}
        on_start = mock.Mock()
        ran = run(table(missing=entry), "missing", None, (), on_start=on_start)
        self.assertEqual((ran.outcome, ran.result, ran.exit_code), ("failed", {}, 127))
        on_start.assert_not_called()

    def test_a_failed_start_callback_kills_and_reaps_the_command(self):
        entry = project("block", os.path.join(self.tmp, "never-released"), cwd=self.tmp)
        pids: list[int] = []

        def refuse(pid: int) -> None:
            pids.append(pid)
            raise OSError("the ledger refused the event")

        with self.assertRaises(OSError):
            run(table(block=entry), "block", None, (), on_start=refuse)
        self.assertEqual(len(pids), 1)
        with self.assertRaises(ProcessLookupError):
            os.kill(pids[0], 0)

    def test_arguments_are_text_integers_and_compact_json(self):
        self.assertEqual(argument("a b"), "a b")
        self.assertEqual(argument(7), "7")
        self.assertEqual(argument(True), "true")
        self.assertEqual(argument({"b": 1, "a": [2]}), '{"a":[2],"b":1}')


if __name__ == "__main__":
    unittest.main()
