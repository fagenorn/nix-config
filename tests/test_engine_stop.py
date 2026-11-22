"""Contract tests for the stop request of `engine stop` and the polled waits it ends (#1524).

A stop request is a file in the run directory bound to the lock holder it names; a command step or
a session polls it while its process group runs, and a request ends that group with `Stopped`.
Every case that starts a process runs the stand-in project command or a launcher stand-in.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import io
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.delivery.engine_guard import Hook
from agent_tools.delivery import (
    engine, engine_commands, engine_ledger, engine_session, engine_shell, engine_stop,
)
from tests.engine_guards import standin_guard
from tests.test_engine_commands import project, table
from tests.test_engine_deliver import ANY_SENTENCE, EngineProject, step
from tests.test_engine_keep_alive import KEEP_ALIVE
from tests.test_engine_session import (
    LAUNCHER_STANDIN, RESULT_NORMAL, after, copy_roles, install_stub, one_step,
)

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

    def test_a_request_file_that_cannot_be_read_is_an_error_not_an_absent_request(self):
        engine_stop.request_path(self.dir).mkdir()  # reading a directory raises an OSError
        with self.assertRaises(OSError):
            engine_stop.requested(self.dir, HOLDER)

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
        self.allow = Hook(str(standin_guard(self.dir, "allow", "allow",
                                            str(self.dir / "allow.log"))), 5)

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
            return engine_commands.run(table(hold=entry), "hold", None, (), guard=self.allow,
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
                    guard=self.allow, on_start=lambda pid: None, stop=lambda: False, **keywords)
                self.assertEqual(ran.stdout, b'{"argv":["5"],"verdict":"renewed"}\n')
                self.assertEqual(ran.stderr, b"")
                self.assertEqual((ran.outcome, ran.exit_code), ("renewed", 0))

    def test_a_request_made_before_a_fast_command_ends_is_never_graded_past(self):
        entry = project("verdict", "renewed", "0", cwd=self.tmp.name)
        for keywords in ({}, {"timeout": 60}):
            with self.subTest("requested while it runs", **keywords):
                started: list[int] = []
                with self.assertRaises(engine_stop.Stopped):
                    engine_commands.run(
                        table(verdict=entry), "verdict", None, (("run.issue", 5),),
                        guard=self.allow, on_start=started.append, stop=lambda: bool(started),
                        **keywords)
                self.assertEqual(len(started), 1)
                gone(self, started[0], group=True)
            with self.subTest("requested before it starts", **keywords):
                started = []
                with self.assertRaises(engine_stop.Stopped):
                    engine_commands.run(
                        table(verdict=entry), "verdict", None, (("run.issue", 5),),
                        guard=self.allow, on_start=started.append, stop=lambda: True, **keywords)
                self.assertEqual(started, [])

    def test_a_request_made_before_a_fast_session_ends_is_never_graded_past(self):
        argv = [sys.executable, "-c", "pass"]
        started: list[int] = []
        with self.assertRaises(engine_stop.Stopped):
            engine_session.launch(argv, self.tmp.name, "p", on_start=started.append,
                                  stop=lambda: bool(started))
        self.assertEqual(len(started), 1)
        started.clear()
        with self.assertRaises(engine_stop.Stopped):
            engine_session.launch(argv, self.tmp.name, "p", on_start=started.append,
                                  stop=lambda: True)
        self.assertEqual(started, [])

    def test_a_stopped_session_does_not_wait_for_a_descendant_outside_its_group(self):
        code = ("import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', "
                "\"import os,sys,time; open(sys.argv[1], 'w').write(str(os.getpid())); "
                "time.sleep(60)\", sys.argv[1]], start_new_session=True); time.sleep(60)")
        timer = threading.Timer(10, reap_from, args=(self.pidfile,))  # frees the pipe if it hangs
        self.addCleanup(timer.cancel)
        timer.start()
        launcher: list[int] = []

        def on_start(pid: int) -> None:
            self.addCleanup(reap, pid)
            launcher.append(pid)

        began = time.monotonic()
        with self.assertRaises(engine_stop.Stopped):
            engine_session.launch([sys.executable, "-c", code, str(self.pidfile)], self.tmp.name,
                                  "p", on_start=on_start, stop=lambda: pid_in(self.pidfile))
        self.assertLess(time.monotonic() - began, 8, "the pipes' far end held the stop open")
        gone(self, launcher[0], group=True)

    def test_a_failing_on_start_does_not_wait_for_a_child_holding_the_pipe(self):
        entry = project("hold", str(self.pidfile), "0", cwd=self.tmp.name)
        timer = threading.Timer(10, reap_from, args=(self.pidfile,))  # frees the pipe if it hangs
        self.addCleanup(timer.cancel)
        timer.start()

        def refuse(pid: int) -> None:
            self.addCleanup(reap, pid)
            until(self, lambda: pid_in(self.pidfile), 8)
            raise OSError("the ledger refused the event")

        began = time.monotonic()
        with self.assertRaises(OSError):
            engine_commands.run(table(hold=entry), "hold", None, (), guard=self.allow,
                                on_start=refuse)
        self.assertLess(time.monotonic() - began, 8, "the child held the callback failure open")
        gone(self, int(self.pidfile.read_text()))

    def test_a_sigterm_to_the_engine_ends_a_running_commands_whole_group(self):
        entry = project("hold", str(self.pidfile), "0", cwd=self.tmp.name)

        def probe(signum, frame):
            raise RuntimeError("the SIGTERM reached the handler the command run left in place")

        before = signal.signal(signal.SIGTERM, probe)
        self.addCleanup(signal.signal, signal.SIGTERM, before)

        def on_start(pid: int) -> None:
            self.addCleanup(reap, pid)
            self.started.append((pid, os.getpgid(pid)))

            def terminate() -> None:
                until(self, lambda: pid_in(self.pidfile), 10)
                os.kill(os.getpid(), signal.SIGTERM)

            threading.Thread(target=terminate, daemon=True).start()

        with self.assertRaises(SystemExit) as raised:
            engine_commands.run(table(hold=entry), "hold", None, (), guard=self.allow,
                                on_start=on_start)
        self.assertEqual(raised.exception.code, 143)
        self.assertIs(signal.getsignal(signal.SIGTERM), probe)
        gone(self, self.started[0][0], group=True)
        gone(self, int(self.pidfile.read_text()))

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


def reap_recorded(engine_project: EngineProject) -> None:
    for run in engine_project.runs():
        for event in engine_project.events(run):
            if event["event"] == "process_started":
                reap(event["pid"])


def until(test: unittest.TestCase, predicate, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            test.fail("the condition did not come true in time")
        time.sleep(0.05)


def pid_in(path: Path) -> bool:
    return path.exists() and bool(path.read_text().strip())


class EngineStopTest(unittest.TestCase):
    def start(self, engine_project: EngineProject, procedures: Path, issue: int):
        argv, options = engine_project.command(
            "deliver", str(issue), "--procedures", str(procedures),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process = subprocess.Popen(argv, **options)
        self.addCleanup(process.communicate)
        self.addCleanup(reap_recorded, engine_project)
        self.addCleanup(process.kill)
        self.addCleanup(engine_project.release.write_text, "go", encoding="utf-8")
        return process

    def stop(self, engine_project: EngineProject, issue: int):
        argv, options = engine_project.command("stop", str(issue))
        return subprocess.run(argv, capture_output=True, timeout=60, **options)

    def started(self, engine_project: EngineProject, name: str) -> bool:
        runs = engine_project.runs()
        return len(runs) == 1 and any(
            e["event"] == "process_started" and e["step"] == name
            for e in engine_project.events(runs[0]))

    def ended_with_stop(self, engine_project: EngineProject, process, run: Path):
        began = time.monotonic()
        self.assertEqual(process.wait(15), 3)
        self.assertLess(time.monotonic() - began, 15)
        out, _ = process.communicate()
        (line,) = out.splitlines()
        result = json.loads(line)
        ANY_SENTENCE(self, result.pop("detail"))
        self.assertEqual(result, {"end": "stopped-by-request", "need": "retry",
                                  "run": run.name})
        self.assertFalse((run / "stop-request").exists())

    def test_engine_stop_ends_a_hanging_agent_step_with_the_stop_code(self):
        project_ = EngineProject(self)
        project_.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(project_, "implementer")
        log = install_stub(project_, RESULT_NORMAL, exit="hang")
        procedures = one_step(project_)
        running = self.start(project_, procedures, 1524)
        until(self, lambda: self.started(project_, "draft") and log.exists()
              and '"hang"' in log.read_text())
        (run,) = project_.runs()
        (record,) = [json.loads(line) for line in log.read_text().splitlines()]
        self.addCleanup(reap, record["hang"]["child"])
        holder = json.loads((run / "lock").read_text())
        stopped = self.stop(project_, 1524)
        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        (line,) = stopped.stdout.splitlines()
        answer = json.loads(line)
        ANY_SENTENCE(self, answer.pop("detail"))
        self.assertEqual(answer, {"issue": 1524, "process": {"pid": running.pid,
                                                              "started": holder["started"]},
                                  "requested": True, "run": run.name})
        self.ended_with_stop(project_, running, run)
        events = project_.events(run)
        last = events[-1]
        self.assertEqual((last["event"], last["step"], last["stop"], last["need"]),
                         ("stop_reached", "draft", "stopped-by-request", "retry"))
        kinds = {e["event"] for e in events}
        self.assertFalse(kinds & {"result_stored", "outcome_graded", "transition_taken"})
        self.assertEqual(list((run / "results").iterdir()), [])
        self.assertFalse((run / "sessions/draft.1.json").exists())
        (starting,) = [e for e in events if e["event"] == "session_starting"]
        self.assertEqual(starting["session"], after(record["argv"], "--session-id"))
        (process,) = [e for e in events if e["event"] == "process_started"]
        gone(self, process["pid"], group=True)
        gone(self, record["hang"]["child"])
        status = json.loads(project_.status(1524).stdout)
        self.assertEqual(status["stop"], {"name": "stopped-by-request", "need": "retry"})
        self.assertIs(status["done"], False)
        again = project_.deliver(procedures, issue=1524)
        self.assertEqual(again.returncode, 2, again.stdout + again.stderr)
        self.assertIn(run.name, again.stderr)

    def test_engine_stop_ends_a_hanging_command_step_and_its_group(self):
        project_ = EngineProject(self)
        procedures = project_.procedures([step("a", "standin-hold", "done")])
        running = self.start(project_, procedures, 1512)
        until(self, lambda: self.started(project_, "a") and pid_in(project_.hold))
        (run,) = project_.runs()
        self.addCleanup(reap, int(project_.hold.read_text()))
        stopped = self.stop(project_, 1512)
        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        self.ended_with_stop(project_, running, run)
        events = project_.events(run)
        self.assertEqual((events[-1]["event"], events[-1]["step"]), ("stop_reached", "a"))
        kinds = {e["event"] for e in events}
        self.assertFalse(kinds & {"result_stored", "outcome_graded", "transition_taken"})
        self.assertEqual(list((run / "results").iterdir()), [])
        (process,) = [e for e in events if e["event"] == "process_started"]
        gone(self, process["pid"], group=True)
        gone(self, int(project_.hold.read_text()))

    def test_engine_stop_during_a_keep_alive_ends_the_run_before_the_step(self):
        project_ = EngineProject(self)
        renewer = project_.tmp / "keep-alive.pid"
        project_.answer({"stdout": '{"verdict":"renewed"}', "sleep": 60, "exit": 0,
                         "pidfile": str(renewer)})
        procedures = project_.procedures(
            [step("a", "standin-record", "done", mutates=True)], keep_alive=KEEP_ALIVE)
        running = self.start(project_, procedures, 1512)
        until(self, lambda: pid_in(renewer))
        self.addCleanup(reap, int(renewer.read_text()))
        (run,) = project_.runs()
        stopped = self.stop(project_, 1512)
        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        self.ended_with_stop(project_, running, run)
        events = project_.events(run)
        kinds = {e["event"] for e in events}
        self.assertFalse(kinds & {"keep_alive_ran", "step_entered"})
        self.assertEqual((events[-1]["event"], events[-1]["step"]), ("stop_reached", "a"))
        self.assertFalse(project_.record.exists())
        gone(self, int(renewer.read_text()), group=True)

    def test_a_request_naming_an_engine_that_is_gone_does_not_stop_the_run(self):
        project_ = EngineProject(self)
        procedures = project_.procedures([step("a", "standin-block", "done")])
        running = self.start(project_, procedures, 1512)
        until(self, lambda: self.started(project_, "a"))
        (run,) = project_.runs()
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        engine_stop.write_request(run, {"pid": dead.pid, "started": "2026-01-01T00:00:00Z"})
        time.sleep(3)
        self.assertIsNone(running.poll())
        project_.release.write_text("go", encoding="utf-8")
        self.assertEqual(running.wait(60), 0)
        events = project_.events(run)
        self.assertEqual(events[-1]["event"], "run_done")
        self.assertNotIn("stop_reached", {e["event"] for e in events})

    def test_a_request_left_in_a_done_runs_directory_does_not_stop_the_next_deliver(self):
        project_ = EngineProject(self)
        first = project_.deliver(project_.procedures([step("a", "standin-json", "done")]))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        (old,) = project_.runs()
        holder = json.loads((old / "lock").read_text())
        engine_stop.write_request(old, holder)
        project_.answer({"stdout": "{}", "sleep": 2, "exit": 0})
        second = project_.deliver(project_.procedures([step("a", "standin-keep-alive", "done")]))
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["end"], "done")
        runs = project_.runs()
        self.assertEqual(len(runs), 2)
        (new,) = [run for run in runs if run != old]
        events = project_.events(new)
        self.assertNotIn("stop_reached", {e["event"] for e in events})
        self.assertEqual(events[-1]["event"], "run_done")
        self.assertTrue((old / "stop-request").exists())

    def test_the_request_is_cleared_only_after_the_stop_is_recorded(self):
        project_ = EngineProject(self)
        procedures = project_.procedures([step("a", "standin-hold", "done")])
        seen: list[tuple] = []
        real = engine_stop.clear

        def spy(run_dir):
            events = engine_ledger.replay(run_dir / "events.jsonl")
            seen.append((events[-1]["event"], (run_dir / "stop-request").exists()))
            real(run_dir)

        def request():
            until(self, lambda: bool(project_.runs()) and self.started(project_, "a"))
            run = project_.runs()[0]
            engine_stop.write_request(run, json.loads((run / "lock").read_text()))

        thread = threading.Thread(target=request)
        self.addCleanup(thread.join)
        self.addCleanup(lambda: pid_in(project_.hold) and reap(int(project_.hold.read_text())))
        self.addCleanup(reap_recorded, project_)
        thread.start()
        with project_.inside(), mock.patch.object(engine_stop, "clear", side_effect=spy):
            code, line = engine_shell.deliver(1512, procedures)
        self.assertEqual(code, engine_shell.EXIT_STOP)
        self.assertEqual(line["end"], "stopped-by-request")
        self.assertEqual(seen, [("stop_reached", True)])
        self.assertFalse((project_.runs()[0] / "stop-request").exists())

    def test_a_second_stop_racing_the_engines_stop_leaves_no_request_behind(self):
        project_ = EngineProject(self)
        procedures = project_.procedures([step("a", "standin-hold", "done")])
        real_clear, real_write = engine_stop.clear, engine_stop.write_request
        cleared = threading.Event()
        second: list[threading.Thread] = []
        late: list[int] = []

        def clear(run_dir):
            real_clear(run_dir)
            cleared.set()

        def write(run_dir, holder):
            if threading.current_thread() is second[0]:
                cleared.wait(2)  # without the lock the engine records, clears, then this writes
            return real_write(run_dir, holder)

        def second_caller():
            with contextlib.redirect_stdout(io.StringIO()):
                late.append(engine._stop_run(1512, None))

        def request():
            until(self, lambda: bool(project_.runs()) and self.started(project_, "a"))
            run = project_.runs()[0]
            real_write(run, json.loads((run / "lock").read_text()))
            second.append(threading.Thread(target=second_caller))
            second[0].start()

        first = threading.Thread(target=request)
        self.addCleanup(first.join)
        self.addCleanup(lambda: second and second[0].join())
        self.addCleanup(lambda: pid_in(project_.hold) and reap(int(project_.hold.read_text())))
        self.addCleanup(reap_recorded, project_)
        first.start()
        with project_.inside(), mock.patch.object(engine_stop, "clear", side_effect=clear), \
                mock.patch.object(engine_stop, "write_request", side_effect=write):
            code, line = engine_shell.deliver(1512, procedures)
            second[0].join(10)
        self.assertEqual((code, line["end"]), (engine_shell.EXIT_STOP, "stopped-by-request"))
        self.assertEqual(len(late), 1)
        self.assertFalse((project_.runs()[0] / "stop-request").exists())

    def test_engine_stop_with_no_running_run_leaves_no_file_and_says_so(self):
        with self.subTest("no run"):
            project_ = EngineProject(self)
            stopped = self.stop(project_, 1512)
            self.assertEqual(stopped.returncode, 1, stopped.stdout + stopped.stderr)
            (line,) = stopped.stdout.splitlines()
            answer = json.loads(line)
            ANY_SENTENCE(self, answer.pop("detail"))
            self.assertEqual(answer, {"issue": 1512, "process": None, "requested": False,
                                      "run": None})
            self.assertFalse((project_.world.home / ".agents/state/engine/runs").exists())
        with self.subTest("engine gone"):
            project_ = EngineProject(self)
            done = project_.deliver(project_.procedures([step("a", "standin-json", "done")]))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            (run,) = project_.runs()
            stopped = self.stop(project_, 1512)
            self.assertEqual(stopped.returncode, 1, stopped.stdout + stopped.stderr)
            answer = json.loads(stopped.stdout)
            ANY_SENTENCE(self, answer.pop("detail"))
            self.assertEqual(answer, {"issue": 1512, "process": None, "requested": False,
                                      "run": run.name})
            self.assertFalse((run / "stop-request").exists())

    def test_engine_stop_writes_the_request_and_signals_no_one(self):
        project_ = EngineProject(self)
        procedures = project_.procedures([step("a", "standin-json", "done")])
        run = engine_ledger.create_run(
            project="example/engine", issue=1512, procedure="deliver", procedures_dir=procedures,
            platform_revision="source", host="test", inputs={"issue": 1512},
            now=datetime.now(timezone.utc), root=project_.world.home / ".agents/state/engine/runs")
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        holder = {"pid": sleeper.pid, "started": "2026-11-22T00:00:00Z"}
        descriptor = os.open(run / "lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.write(descriptor, json.dumps(holder).encode("utf-8"))
        before = (run / "events.jsonl").read_bytes()
        began = time.monotonic()
        stopped = self.stop(project_, 1512)
        self.assertLess(time.monotonic() - began, 10)
        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        answer = json.loads(stopped.stdout)
        self.assertEqual(answer["process"], holder)
        self.assertIs(answer["requested"], True)
        request = json.loads((run / "stop-request").read_text())
        self.assertEqual((request["pid"], request["started"]), (holder["pid"], holder["started"]))
        self.assertIsNone(sleeper.poll())
        self.assertEqual((run / "events.jsonl").read_bytes(), before)

    def test_stop_takes_only_an_issue_and_a_project(self):
        parser = engine.build_parser()
        action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual({a.dest for a in action.choices["stop"]._actions},
                         {"help", "issue", "project"})
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(engine.main(["stop", "0"]), 2)
        self.assertEqual(len(errors.getvalue().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
