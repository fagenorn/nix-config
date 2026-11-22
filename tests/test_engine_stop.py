"""Contract tests for the stop request of `engine stop` and the polled waits it ends (#1524).

A stop request is a file in the run directory bound to the lock holder it names; a command step or
a session polls it while its process group runs, and a request ends that group with `Stopped`.
Every case that starts a process runs the stand-in project command or a launcher stand-in.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.delivery import engine_commands, engine_session, engine_stop
from tests.test_engine_commands import project, table
from tests.test_engine_session import LAUNCHER_STANDIN

TIER = "integration"  # the polled cases start process groups

HOLDER = {"pid": 42, "started": "2026-11-22T00:00:00Z"}


def gone(test: unittest.TestCase, pid: int, *, group: bool = False, seconds: float = 5) -> None:
    deadline = time.monotonic() + seconds
    probe = os.killpg if group else os.kill
    while True:
        try:
            probe(pid, 0)
        except ProcessLookupError:
            return
        if time.monotonic() > deadline:
            test.fail(f"{'group' if group else 'process'} {pid} is still alive")
        time.sleep(0.05)


def reap(pid: int) -> None:
    for kill in (os.killpg, os.kill):
        try:
            kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def reap_from(pidfile: Path) -> None:
    try:
        reap(int(pidfile.read_text()))
    except (FileNotFoundError, ValueError):
        pass


class StopRequestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_a_request_answers_only_for_the_holder_it_names(self):
        directory = self.dir
        with self.subTest("no file"):
            self.assertFalse(engine_stop.requested(directory, HOLDER))
        engine_stop.write_request(directory, HOLDER)
        with self.subTest("written for the holder"):
            self.assertTrue(engine_stop.requested(directory, HOLDER))
        with self.subTest("another pid"):
            self.assertFalse(engine_stop.requested(directory, {**HOLDER, "pid": 43}))
        with self.subTest("another start"):
            self.assertFalse(engine_stop.requested(
                directory, {**HOLDER, "started": "2026-11-22T00:00:01Z"}))
        engine_stop.clear(directory)
        with self.subTest("cleared"):
            self.assertFalse(engine_stop.requested(directory, HOLDER))
            self.assertFalse(engine_stop.request_path(directory).exists())
            engine_stop.clear(directory)
        for label, text, holder in (
                ("not json", "not json", HOLDER),
                ("not an object", "[1]", HOLDER),
                ("duplicate key", '{"pid":42,"pid":42,"started":"2026-11-22T00:00:00Z"}', HOLDER),
                ("a bool pid", '{"pid": true, "started": "S"}', {"pid": 1, "started": "S"})):
            with self.subTest(label):
                engine_stop.request_path(directory).write_text(text)
                self.assertFalse(engine_stop.requested(directory, holder))

    def test_write_request_publishes_only_the_request_file(self):
        path = engine_stop.write_request(self.dir, {"pid": 7, "started": "2026-11-22T00:00:00Z"})
        self.assertEqual(path, engine_stop.request_path(self.dir))
        self.assertEqual(os.listdir(self.dir), ["stop-request"])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        document = json.loads(path.read_text())
        self.assertEqual(set(document), {"at", "pid", "started"})
        self.assertEqual((document["pid"], document["started"]), (7, "2026-11-22T00:00:00Z"))
        parse_rfc3339_utc(document["at"])
        engine_stop.write_request(self.dir, {"pid": 8, "started": "X"})
        self.assertEqual(os.listdir(self.dir), ["stop-request"])
        self.assertEqual(json.loads(path.read_text())["pid"], 8)


class StopPollTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.pidfile = self.dir / "grandchild"
        self.addCleanup(reap_from, self.pidfile)
        self.begun: float | None = None
        self.started: list[tuple[int, int]] = []

    def on_start(self, pid: int) -> None:
        self.addCleanup(reap, pid)
        self.started.append((pid, os.getpgid(pid)))
        self.begun = time.monotonic()

    def stop_soon(self) -> bool:
        return (self.begun is not None and self.pidfile.exists()
                and bool(self.pidfile.read_text()) and time.monotonic() - self.begun > 1)

    def hold(self, **keywords):
        entry = project("hold", str(self.pidfile), "0", cwd=self.tmp.name)
        began = time.monotonic()
        try:
            return engine_commands.run(table(hold=entry), "hold", None, (),
                                       on_start=self.on_start, **keywords)
        finally:
            self.elapsed = time.monotonic() - began

    def test_a_stop_ends_a_running_commands_whole_group(self):
        with self.assertRaises(engine_stop.Stopped):
            self.hold(stop=self.stop_soon)
        self.assertLess(self.elapsed, 10)
        self.assertEqual(len(self.started), 1)
        pid, pgid = self.started[0]
        self.assertEqual(pgid, pid)
        self.assertNotEqual(pgid, os.getpgrp())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        gone(self, int(self.pidfile.read_text()))

    def test_a_stop_ends_a_timed_command_before_its_timeout(self):
        with self.assertRaises(engine_stop.Stopped):
            self.hold(stop=self.stop_soon, timeout=60)
        self.assertLess(self.elapsed, 20)
        gone(self, int(self.pidfile.read_text()))

    def test_a_timed_command_polled_for_a_stop_still_times_out(self):
        ran = self.hold(stop=lambda: False, timeout=2)
        self.assertEqual(ran.outcome, engine_commands.TIMED_OUT)
        self.assertLess(self.elapsed, 20)
        self.assertIn(b"marker-hold", ran.stdout)
        gone(self, int(self.pidfile.read_text()))

    def test_a_command_polled_for_a_stop_runs_to_its_end_as_before(self):
        entry = project("verdict", "renewed", "0", cwd=self.tmp.name)
        for keywords in ({"timeout": 60}, {}):
            with self.subTest(**keywords):
                ran = engine_commands.run(
                    table(verdict=entry), "verdict", None, (("run.issue", 5),),
                    on_start=lambda pid: None, stop=lambda: False, **keywords)
                self.assertEqual(ran.stdout, b'{"argv":["5"],"verdict":"renewed"}\n')
                self.assertEqual(ran.stderr, b"")
                self.assertEqual((ran.outcome, ran.exit_code), ("renewed", 0))

    def test_a_stop_ends_a_running_sessions_whole_group(self):
        before = signal.getsignal(signal.SIGTERM)
        launcher: list[int] = []

        def on_start(pid: int) -> None:
            self.addCleanup(reap, pid)
            launcher.append(pid)

        def stop() -> bool:
            return self.pidfile.exists() and bool(self.pidfile.read_text())

        began = time.monotonic()
        with self.assertRaises(engine_stop.Stopped):
            engine_session.launch([sys.executable, "-c", LAUNCHER_STANDIN, str(self.pidfile)],
                                  self.tmp.name, "p", on_start=on_start, stop=stop)
        self.assertLess(time.monotonic() - began, 15)
        gone(self, launcher[0], group=True)
        gone(self, int(self.pidfile.read_text()))
        self.assertIs(signal.getsignal(signal.SIGTERM), before)

    def test_a_session_polled_for_a_stop_reads_its_whole_prompt(self):
        code = "import sys,time; time.sleep(1.5); data = sys.stdin.buffer.read(); print(len(data))"
        launched = engine_session.launch([sys.executable, "-c", code], self.tmp.name,
                                         "x" * 1_000_000, on_start=lambda pid: None,
                                         stop=lambda: False)
        self.assertEqual(launched.exit_code, 0)
        self.assertEqual(launched.stdout, b"1000000\n")


if __name__ == "__main__":
    unittest.main()
