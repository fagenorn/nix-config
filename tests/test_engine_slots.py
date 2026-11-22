"""Contract tests for the engine's agent slots (#1522): `engine deliver` runs only on a host whose
declaration admits the engine route, and an agent session holds one counted slot of its run.

Each case runs `engine deliver` against the stand-in project command
(tests/fixtures/engine-deliver/standin.py) or, for an agent step, the stand-in launcher
(tests/fixtures/engine-slots/launcher.py), with the host declaration the case writes.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent_tools.delivery import engine_shell, engine_slots
from tests.test_engine_deliver import EngineProject, step
from tests.test_engine_session import agent_step, copy_roles, one_step, write_procedures

TIER = "integration"  # every case runs `engine deliver` against a stand-in

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "tests/fixtures/engine-slots/launcher.py"
HOLDER = REPO_ROOT / "tests/fixtures/engine-slots/holder.py"
CLAUDE_CODE = {"support": "supported", "agent_slots": 7}
ONE_SLOT = {"schema_version": 1,
            "routes": {"claude-code": CLAUDE_CODE,
                       "engine": {"support": "supported", "agent_slots": 1}}}
TWO_SLOTS = {"schema_version": 1,
             "routes": {"claude-code": CLAUDE_CODE,
                        "engine": {"support": "supported", "agent_slots": 2}}}


def install_launcher(project: EngineProject, mode: str) -> Path:
    """Put the stand-in launcher first on the project's PATH; return the log it appends to."""
    log = project.tmp / "launcher.log"
    launcher = project.bin / "claude-account"
    launcher.write_text(f"#!/bin/sh\nexec {sys.executable} {LAUNCHER} {log} {mode} \"$@\"\n",
                        encoding="utf-8")
    launcher.chmod(0o755)
    return log


def held_slots(run: Path) -> int:
    """The slot files of `run` that some descriptor holds, probed with a fresh open."""
    held = 0
    for path in sorted((run / "slots").glob("slot-*.lock")):
        descriptor = os.open(path, os.O_RDWR)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            held += 1
        finally:
            os.close(descriptor)
    return held


def kill_quietly(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def wait_for(test: unittest.TestCase, condition, message: str, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    test.fail(message)


class RouteRefusalTest(unittest.TestCase):
    def test_deliver_refuses_each_route_the_declaration_does_not_admit(self) -> None:
        cases = (
            ("missing", None, "declaration_missing"),
            ("invalid", "{", "declaration_invalid"),
            ("unsupported",
             {"schema_version": 1,
              "routes": {"claude-code": CLAUDE_CODE, "engine": {"support": "unsupported"}}},
             "declared_unsupported"),
            ("undeclared",
             {"schema_version": 1,
              "routes": {"claude-code": CLAUDE_CODE, "codex": {"support": "unsupported"}}},
             "route_undeclared"),
        )
        for label, value, code in cases:
            with self.subTest(label):
                project = EngineProject(self)
                project.declare(value)
                procedures = project.procedures([step("a", "standin-record", "done")])
                done = project.deliver(procedures)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertEqual(done.stdout, "")
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertTrue(done.stderr.startswith(f"engine: {code}:"), done.stderr)
                self.assertEqual(project.runs(), [])
                self.assertFalse(project.record.exists())
                self.assertFalse((project.world.home / ".agents/state/engine/runs").exists())

    def test_a_declaration_admitting_the_engine_route_runs(self) -> None:
        project = EngineProject(self)
        project.declare({"schema_version": 1,
                         "routes": {"engine": {"support": "supported", "agent_slots": 1}}})
        done = project.deliver(project.procedures([step("a", "standin-json", "done")]))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(project.runs()), 1)


class SlotWaitTest(unittest.TestCase):
    def test_a_launch_with_every_slot_held_waits_then_launches_once_one_is_freed(self) -> None:
        project = EngineProject(self)
        project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(project, "implementer")
        project.declare(ONE_SLOT)
        log = install_launcher(project, "reply")
        procedures = write_procedures(project, [
            step("a", "standin-block", "b"), step("b", "standin-json", "draft"),
            agent_step("draft", "implementer", {"drafted": "done", "stuck": "needs-owner"})])
        argv, options = project.command("deliver", "1512", "--procedures", str(procedures),
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process = subprocess.Popen(argv, **options)
        self.addCleanup(process.communicate)  # cleanups run last-in first: kill, then reap
        self.addCleanup(process.kill)

        def started() -> bool:
            runs = project.runs()
            return bool(runs) and any(
                e["event"] == "process_started" and e["step"] == "a"
                for e in project.events(runs[0]))

        wait_for(self, started, "the run never started its first step")
        (run,) = project.runs()
        ready = project.tmp / "ready"
        holder = subprocess.Popen([sys.executable, str(HOLDER), str(run / "slots"), "0",
                                   str(ready)])
        self.addCleanup(holder.wait)  # cleanups run last-in first: kill, then reap
        self.addCleanup(holder.kill)
        wait_for(self, ready.exists, "the holder never took the slot")
        project.release.write_text("go", encoding="utf-8")
        wait_for(self, lambda: any(e["event"] == "wait_started" for e in project.events(run)),
                 "the run never waited for a slot")
        time.sleep(1.0)
        waiting = project.events(run)
        status = project.status(1512)
        launched = log.exists()
        holder.send_signal(signal.SIGKILL)
        holder.wait()
        stdout, stderr = process.communicate(timeout=60)

        self.assertEqual([e for e in waiting if e["event"] == "session_starting"], [])
        self.assertFalse(launched)
        names = [(e["event"], e.get("step")) for e in waiting]
        self.assertLess(names.index(("transition_taken", "b")), names.index(("wait_started", None)))
        (started_wait,) = [e for e in waiting if e["event"] == "wait_started"]
        self.assertEqual({k: v for k, v in started_wait.items() if k != "at"},
                         {"event": "wait_started", "wait": "host-slot", "until": None})
        self.assertEqual(status.returncode, 0, status.stderr)
        state = json.loads(status.stdout)
        self.assertEqual(state["wait"], {"wait": "host-slot", "since": started_wait["at"],
                                         "until": None})
        self.assertEqual(state["step"], "draft")

        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)["end"], "done")
        events = project.events(run)
        self.assertEqual(len([e for e in events if e["event"] == "wait_started"]), 1)
        (ended,) = [e for e in events if e["event"] == "wait_ended"]
        self.assertEqual(ended["wait"], "host-slot")
        order = [(e["event"], e.get("step")) for e in events]
        self.assertLess(order.index(("wait_started", None)), order.index(("wait_ended", None)))
        self.assertLess(order.index(("wait_ended", None)),
                        order.index(("session_starting", "draft")))
        self.assertLess(order.index(("session_starting", "draft")),
                        order.index(("process_started", "draft")))
        lines = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["held"] for line in lines], [1])


class SlotCountTest(unittest.TestCase):
    def test_deliver_holds_the_slot_that_is_free_of_the_declared_two(self) -> None:
        project = EngineProject(self)
        project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(project, "implementer")
        project.declare(TWO_SLOTS)
        log = install_launcher(project, "reply")
        procedures = write_procedures(project, [
            step("a", "standin-block", "b"), step("b", "standin-json", "draft"),
            agent_step("draft", "implementer", {"drafted": "done", "stuck": "needs-owner"})])
        argv, options = project.command("deliver", "1512", "--procedures", str(procedures),
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process = subprocess.Popen(argv, **options)
        self.addCleanup(process.communicate)  # cleanups run last-in first: kill, then reap
        self.addCleanup(process.kill)
        wait_for(self, lambda: bool(project.runs()) and any(
            e["event"] == "process_started" and e["step"] == "a"
            for e in project.events(project.runs()[0])), "the run never started its first step")
        (run,) = project.runs()
        holders = []
        for index in (0, 1):
            ready = project.tmp / f"ready-{index}"
            holder = subprocess.Popen([sys.executable, str(HOLDER), str(run / "slots"),
                                       str(index), str(ready)])
            self.addCleanup(holder.wait)
            self.addCleanup(holder.kill)
            wait_for(self, ready.exists, f"the holder never took slot {index}")
            holders.append(holder)
        project.release.write_text("go", encoding="utf-8")
        wait_for(self, lambda: any(e["event"] == "wait_started" for e in project.events(run)),
                 "the run never waited for a slot")
        holders[1].send_signal(signal.SIGKILL)
        holders[1].wait()
        wait_for(self, lambda: any(e["event"] == "process_started" and e["step"] == "draft"
                                   for e in project.events(run)),
                 "the run did not launch on the freed slot")
        stdout, stderr = process.communicate(timeout=60)
        held_by_holder = held_slots(run)
        holders[0].send_signal(signal.SIGKILL)
        holders[0].wait()

        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual([json.loads(line)["held"]
                          for line in log.read_text(encoding="utf-8").splitlines()], [2])
        self.assertEqual(held_by_holder, 1)


class SlotReleaseTest(unittest.TestCase):
    def deliver_with(self, mode: str):
        project = EngineProject(self)
        project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(project, "implementer")
        log = install_launcher(project, mode)
        procedures = one_step(project)
        with project.inside():
            if mode in ("reply", "orphan", "pipes"):
                code, _ = engine_shell.deliver(1512, procedures)
                self.assertEqual(code, 0)
            else:
                with self.assertRaises(engine_shell.Fault):
                    engine_shell.deliver(1512, procedures)
        pid_file = Path(f"{log}.orphan.pid")
        if pid_file.exists():
            self.addCleanup(kill_quietly, int(pid_file.read_text(encoding="utf-8")))
        (run,) = project.runs()
        lines = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["held"] for line in lines], [1])
        self.assertEqual(held_slots(run), 0)
        self.assertEqual([e for e in project.events(run) if e["event"] == "wait_started"], [])
        return log

    def test_a_slot_is_free_after_a_reply_a_missing_answer_and_a_killed_process(self) -> None:
        for mode in ("reply", "prose", "kill"):
            with self.subTest(mode):
                self.deliver_with(mode)

    def test_a_process_the_session_leaves_behind_holds_no_slot(self) -> None:
        log = self.deliver_with("orphan")
        os.kill(int(Path(f"{log}.orphan.pid").read_text(encoding="utf-8")), 0)

    def test_a_slot_is_free_when_a_process_left_behind_keeps_the_output_pipes_open(self) -> None:
        for mode in ("pipes", "killpipes"):
            with self.subTest(mode):
                started = time.monotonic()
                self.deliver_with(mode)
                self.assertLess(time.monotonic() - started, 30)


class HoldTest(unittest.TestCase):
    def test_hold_takes_only_the_declared_slots_and_reports_one_wait(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        calls: list[str] = []
        entered = threading.Event()
        taken: list[int] = []

        def third() -> None:
            with engine_slots.hold(root, 2, on_wait=lambda: calls.append("wait"),
                                   on_waited=lambda: calls.append("waited")) as index:
                taken.append(index)
                entered.set()

        with engine_slots.hold(root, 2, on_wait=lambda: calls.append("wait"),
                               on_waited=lambda: calls.append("waited")) as first:
            with engine_slots.hold(root, 2, on_wait=lambda: calls.append("wait"),
                                   on_waited=lambda: calls.append("waited")) as second:
                self.assertEqual({first, second}, {0, 1})
                self.assertEqual(calls, [])
                thread = threading.Thread(target=third)
                thread.start()
                wait_for(self, lambda: calls == ["wait"], "the third hold never waited", 5)
                time.sleep(0.5)
                self.assertEqual(calls, ["wait"])
                self.assertFalse(entered.is_set())
            self.assertTrue(entered.wait(5))
        thread.join(5)
        self.assertEqual(calls, ["wait", "waited"])
        self.assertEqual(sorted(p.name for p in engine_slots.slot_dir(root).iterdir()),
                         ["slot-0.lock", "slot-1.lock"])
