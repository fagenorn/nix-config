"""Contract tests for a continued engine run that cannot be resumed as it was: a run whose
procedure copy is in a format the engine does not read ends `superseded`, and the same
`engine deliver` call opens a new run from the current procedures.

The hermetic project, the stand-in command and the shared step helpers come from
tests/test_engine_deliver.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_ledger, engine_stop
from tests.process_liveness import process_alive
from tests.test_engine_continue import gated
from tests.test_engine_deliver import EngineProject, run_continued, start_deliver, step
from tests.test_engine_session import (
    RESULT_NORMAL, copy_roles, install_answers, one_step,
)
from tests.test_engine_stop import gone, reap

TIER = "integration"  # every case runs `engine deliver` against the stand-in command


def seed(project: EngineProject, procedures: Path, token: str) -> Path:
    root = project.world.home / ".agents/state/engine/runs"
    return engine_ledger.create_run(
        project="example/engine", issue=1512, procedure="deliver",
        procedures_dir=procedures, platform_revision="source", host="test",
        inputs={"issue": 1512}, now=datetime(2026, 11, 21, tzinfo=timezone.utc),
        token=token, root=root)


def history(project: EngineProject) -> list[dict]:
    path = project.world.home / ".agents/state/engine/history.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def rewrite(path: Path, **members) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    document.update(members)
    path.write_text(json.dumps(document), encoding="utf-8")


def wait_until(test: unittest.TestCase, predicate, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            test.fail("the condition did not hold in time")
        time.sleep(0.05)


def rfc(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def orphan_sleeper(test: unittest.TestCase, ignore_term: bool = False) -> int:
    """Start a sleeper in its own session whose parent has exited, so init reaps it; return its pid.

    The pid is returned once the sleeper has installed its signal disposition.
    """
    ignore = "signal.signal(signal.SIGTERM, signal.SIG_IGN); " if ignore_term else ""
    sleeper = f"import signal,time; {ignore}print('ready',flush=True); time.sleep(60)"
    starter = ("import subprocess,sys; "
               f"p=subprocess.Popen([sys.executable,'-c',{sleeper!r}],start_new_session=True,"
               "stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL); "
               "p.stdout.readline(); print(p.pid)")
    out = subprocess.run([sys.executable, "-c", starter], capture_output=True, text=True,
                         check=True).stdout
    pid = int(out)
    test.addCleanup(reap, pid)
    return pid


class SupersededTest(unittest.TestCase):
    def test_a_copy_in_a_format_the_engine_does_not_read_ends_superseded_and_the_same_call_opens_a_new_run(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-record", "done")])
        future = project.procedures([step("a", "standin-record", "done")])
        rewrite(future / "deliver.json", format=2)
        old = seed(project, future, "aaaa")
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual(line["end"], "done")
        self.assertNotEqual(line["run"], old.name)
        self.assertEqual(len(project.runs()), 2)
        self.assertEqual([(e["event"], e["step"], e["stop"], e["need"])
                          for e in project.events(old)],
                         [("stop_reached", "deliver", "superseded", "nothing")])
        (new,) = [run for run in project.runs() if run != old]
        self.assertEqual(project.events(new)[-1]["event"], "run_done")
        self.assertTrue(project.record.exists())
        lines = [entry for entry in history(project) if entry["run"] == old.name]
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["end"], lines[0]["need"]), ("superseded", "nothing"))

    def test_a_superseded_run_is_never_continued_again_and_names_its_last_entered_step(self):
        project = EngineProject(self)
        procedures = gated(project)
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        (old,) = project.runs()
        rewrite(old / "procedure/deliver.json", format=2)
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        self.assertEqual(project.events(old)[-1]["stop"], "superseded")
        self.assertEqual(project.events(old)[-1]["step"], "g")
        self.assertNotEqual(json.loads(second.stdout)["run"], old.name)
        (project.tmp / "gate-open").write_text("", encoding="utf-8")
        third = project.deliver(procedures)
        self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
        self.assertEqual(json.loads(third.stdout)["run"], json.loads(second.stdout)["run"])
        self.assertEqual(len(project.runs()), 2)
        (new,) = [run for run in project.runs() if run != old]
        self.assertEqual(len(run_continued(project.events(new))), 1)

    def test_a_copy_that_differs_only_in_content_is_continued(self):
        project = EngineProject(self)
        procedures = gated(project)
        first = project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        (old,) = project.runs()
        path = old / "procedure/deliver.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        for item in document["steps"]:
            if item["id"] == "d":
                item["stage"] = "building"
        path.write_text(json.dumps(document), encoding="utf-8")
        second = project.deliver(procedures)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(json.loads(second.stdout)["run"], old.name)
        self.assertEqual(len(project.runs()), 1)
        events = project.events(old)
        self.assertFalse([e for e in events if e.get("stop") == "superseded"])
        self.assertEqual(len(run_continued(events)), 1)

    def test_a_copy_that_does_not_parse_is_refused_and_nothing_is_written(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-record", "done")])
        old = seed(project, procedures, "aaaa")
        (old / "procedure/deliver.json").write_bytes(b"not json")
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertEqual((old / "events.jsonl").read_bytes(), b"")
        self.assertEqual(project.runs(), [old])


class LeftoverTest(unittest.TestCase):
    def hung_run(self):
        """Start a delivery whose agent session hangs, then kill the engine; return what is left."""
        project = EngineProject(self)
        project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(project, "implementer")
        log = install_answers(project, [
            {"stdout": str(RESULT_NORMAL), "exit": "hang", "account": "p1"},
            {"stdout": str(RESULT_NORMAL), "exit": 0, "account": "p1"}])
        procedures = one_step(project)
        running = start_deliver(self, project, procedures)
        wait_until(self, lambda: log.exists() and '"hang"' in log.read_text())
        hung = json.loads(log.read_text().splitlines()[0])["hang"]
        self.addCleanup(reap, hung["pid"])
        self.addCleanup(reap, hung["child"])
        running.kill()
        running.wait(10)
        return project, procedures, log, hung

    def test_a_leftover_session_group_is_ended_before_the_continued_run_launches_again(self):
        project, procedures, log, hung = self.hung_run()
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        records = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[1]["hung_alive"], [{"child": False, "pid": False}])
        self.assertFalse(process_alive(hung["pid"]))
        self.assertFalse(process_alive(hung["child"]))

    def test_a_live_process_with_the_recorded_pid_but_another_start_time_is_left_alone(self):
        project, procedures, log, hung = self.hung_run()
        reap(hung["pid"])
        reap(hung["child"])
        gone(self, hung["pid"])
        gone(self, hung["child"])
        decoy = orphan_sleeper(self)
        (run,) = project.runs()
        now = datetime.now(timezone.utc)
        engine_ledger.append_event(run, {
            "event": "process_started", "at": rfc(now), "step": "draft", "visit": 1,
            "pid": decoy, "started": rfc(engine_stop.process_started_at(decoy) - timedelta(hours=1))})
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(process_alive(decoy))

    def test_a_superseded_runs_leftover_group_is_ended_before_the_new_run(self):
        project = EngineProject(self)
        procedures = project.procedures([step("a", "standin-record", "done")])
        future = project.procedures([step("a", "standin-record", "done")])
        rewrite(future / "deliver.json", format=2)
        old = seed(project, future, "aaaa")
        decoy = orphan_sleeper(self)
        now = datetime.now(timezone.utc)
        engine_ledger.append_event(old, {"event": "step_entered", "at": rfc(now), "step": "a",
                                         "visit": 1, "stage": "setup"})
        engine_ledger.append_event(old, {
            "event": "process_started", "at": rfc(now), "step": "a", "visit": 1, "pid": decoy,
            "started": rfc(engine_stop.process_started_at(decoy))})
        done = project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        gone(self, decoy)
        last = project.events(old)[-1]
        self.assertEqual((last["event"], last["stop"], last["step"]),
                         ("stop_reached", "superseded", "a"))


class StartTimeTest(unittest.TestCase):
    def test_the_start_time_is_read_in_utc_and_matches_only_within_the_slack(self):
        before = datetime.now(timezone.utc).replace(microsecond=0)
        pid = orphan_sleeper(self)
        after_ = datetime.now(timezone.utc)
        with mock.patch.dict(os.environ, {"TZ": "America/New_York"}):
            at = engine_stop.process_started_at(pid)
        self.assertIsNotNone(at)
        self.assertLessEqual(before - timedelta(seconds=1), at)
        self.assertLessEqual(at, after_ + timedelta(seconds=1))
        self.assertTrue(engine_stop.same_process(pid, rfc(at)))
        self.assertTrue(engine_stop.same_process(pid, rfc(at + timedelta(seconds=3))))
        self.assertFalse(engine_stop.same_process(pid, rfc(at - timedelta(hours=1))))
        self.assertFalse(engine_stop.same_process(pid, "not a time"))
        reap(pid)
        gone(self, pid)
        self.assertFalse(engine_stop.same_process(pid, rfc(at)))
        self.assertIsNone(engine_stop.process_started_at(pid))

    def test_a_leftover_that_ignores_sigterm_is_killed_after_the_grace(self):
        pid = orphan_sleeper(self, ignore_term=True)
        began = time.monotonic()
        engine_stop.end_leftover(pid)
        self.assertLess(time.monotonic() - began, 2 * engine_stop.LEFTOVER_GRACE_SECONDS + 2)
        gone(self, pid, group=True)


if __name__ == "__main__":
    unittest.main()
