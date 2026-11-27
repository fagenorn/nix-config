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
from tests.test_engine_deliver import EngineProject, run_continued, shape, start_deliver, step
from tests.test_engine_session import (
    RESULT_LIMIT, RESULT_MISSING, RESULT_NORMAL, after, agent_step, canned_result, copy_roles,
    install_answers, one_step, write_procedures,
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
        self.assertIn(("unreadable_procedure", "deliver"),
                      [(r["defect"], r["procedure"]) for r in json.loads(done.stdout)["refusals"]])
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
        # The leader may linger as a zombie until init reaps it, and killpg then raises
        # PermissionError on macOS, so poll the zombie-aware liveness rather than the group.
        deadline = time.monotonic() + 5
        while process_alive(pid):
            self.assertLess(time.monotonic(), deadline, f"process {pid} is still alive")
            time.sleep(0.05)


class ResumeTest(unittest.TestCase):
    def setUp(self):
        self.project = EngineProject(self)
        self.project.env.pop("CLAUDE_ACCOUNT", None)
        copy_roles(self.project, "implementer")

    def hang(self) -> dict:
        return {"stdout": str(RESULT_NORMAL), "exit": "hang", "account": "p1"}

    def normal(self) -> dict:
        return {"stdout": str(RESULT_NORMAL), "exit": 0, "account": "p1"}

    def kill_during_hang(self, procedures: Path, log: Path, lines: int) -> None:
        running = start_deliver(self, self.project, procedures)
        wait_until(self, lambda: log.exists() and len(log.read_text().splitlines()) >= lines
                   and '"hang"' in log.read_text().splitlines()[lines - 1])
        hung = json.loads(log.read_text().splitlines()[lines - 1])["hang"]
        self.addCleanup(reap, hung["pid"])
        self.addCleanup(reap, hung["child"])
        running.kill()
        running.wait(10)

    def records(self, log: Path) -> list[dict]:
        return [json.loads(line) for line in log.read_text().splitlines()]

    def cut(self, run: Path, event: str, *, drop: tuple[str, ...] = (), nth: int = 1) -> int:
        """Cut the ledger right after the `nth` `event` line and delete the named files."""
        lines = (run / "events.jsonl").read_text().splitlines(keepends=True)
        cut = [i for i, line in enumerate(lines) if json.loads(line)["event"] == event][nth - 1] + 1
        (run / "events.jsonl").write_text("".join(lines[:cut]), encoding="utf-8")
        for name in drop:
            (run / name).unlink()
        return cut

    def delivered_once(self) -> tuple[Path, Path, Path, str]:
        log = install_answers(self.project, [self.normal(), self.normal()])
        procedures = one_step(self.project)
        first = self.project.deliver(procedures)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        (run,) = self.project.runs()
        return procedures, log, run, after(self.records(log)[0]["argv"], "--session-id")

    def entered(self, run: Path) -> list[int]:
        return [e["visit"] for e in self.project.events(run)
                if e["event"] == "step_entered" and e["step"] == "draft"]

    def test_a_run_killed_during_an_agent_step_resumes_its_recorded_session_once(self):
        log = install_answers(self.project, [self.hang(), self.normal()])
        procedures = one_step(self.project)
        self.kill_during_hang(procedures, log, 1)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "done")
        (run,) = self.project.runs()
        records = self.records(log)
        self.assertEqual(len(records), 2)
        session = after(records[0]["argv"], "--session-id")
        self.assertEqual(after(records[1]["argv"], "--resume"), session)
        self.assertNotIn("--session-id", records[1]["argv"])
        self.assertTrue(records[1]["announced"])
        self.assertEqual(records[1]["stdin"],
                         (run / "sessions/draft.1.continue-2.prompt.md").read_text())
        events = self.project.events(run)
        self.assertEqual(self.entered(run), [1])
        self.assertEqual([e["session"] for e in events if e["event"] == "session_starting"],
                         [session])
        self.assertEqual(run_continued(events), [])
        self.assertEqual([(e["step"], e["visit"], e["session"], e["attempt"])
                          for e in events if e["event"] == "session_resuming"],
                         [("draft", 1, session, 2)])
        self.assertEqual(len([e for e in events if e["event"] == "result_stored"
                              and (e["step"], e["visit"]) == ("draft", 1)]), 1)
        self.assertTrue((run / "results/draft.1.json").exists())
        self.assertFalse((run / "results/draft.2.json").exists())
        self.assertTrue((run / "sessions/draft.1.continue-2.json").exists())

    def test_a_resumed_visit_closes_the_usage_limit_wait_the_killed_engine_left_open(self):
        limit = {"stdout": str(RESULT_LIMIT), "exit": 1, "account": "p1"}
        log = install_answers(self.project, [limit, self.hang(), self.normal()])
        procedures = one_step(self.project)
        self.kill_during_hang(procedures, log, 2)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "done")
        (run,) = self.project.runs()
        events = self.project.events(run)
        self.assertEqual(run_continued(events), [])
        started = [e for e in events if e["event"] == "wait_started"]
        ended = [e for e in events if e["event"] == "wait_ended"]
        self.assertEqual([e["wait"] for e in started], ["usage-limit"])
        self.assertEqual([e["wait"] for e in ended], ["usage-limit"])
        self.assertLess(events.index(started[0]), events.index(ended[0]))
        self.assertLess(events.index(ended[0]),
                        next(i for i, e in enumerate(events) if e["event"] == "run_done"))
        self.assertIsNone(json.loads(self.project.status(1512).stdout)["wait"])
        (line,) = [entry for entry in history(self.project) if entry["run"] == run.name]
        (visit,) = [entry for entry in line["steps"] if entry["step"] == "draft"]
        self.assertIsNotNone(visit["waits"][0]["seconds"])

    def test_a_session_recorded_but_never_started_is_launched_with_its_recorded_id(self):
        procedures, log, run, session = self.delivered_once()
        cut = self.cut(run, "session_starting",
                       drop=("results/draft.1.json", "sessions/draft.1.json"))
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        records = self.records(log)
        self.assertEqual(len(records), 2)
        self.assertEqual(after(records[1]["argv"], "--session-id"), session)
        self.assertNotIn("--resume", records[1]["argv"])
        self.assertEqual(records[1]["stdin"], (run / "sessions/draft.1.prompt.md").read_text())
        events = self.project.events(run)[cut:]
        self.assertEqual(shape(events)[0], ("session_resuming", "draft", 1))
        self.assertFalse([e for e in events if e["event"] in ("step_entered", "run_continued")])

    def test_a_miss_on_the_continued_resume_is_no_reply_with_no_second_ask(self):
        log = install_answers(self.project, [
            self.hang(), {"stdout": str(RESULT_MISSING), "exit": 0, "account": "p1"}])
        procedures = one_step(self.project)
        self.kill_during_hang(procedures, log, 1)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertEqual(json.loads(done.stdout)["end"], "step-failed")
        (run,) = self.project.runs()
        self.assertEqual(len(self.records(log)), 2)
        self.assertEqual([e["outcome"] for e in self.project.events(run)
                          if e["event"] == "outcome_graded" and e["step"] == "draft"
                          and e["visit"] == 1], ["no-reply"])
        self.assertTrue((run / "sessions/draft.1.continue-2.json").exists())
        self.assertFalse((run / "sessions/draft.1.resume.json").exists())

    def denying(self, command: str, ident: str = "toolu_01") -> dict:
        path = self.project.tmp / f"denying-{ident}.json"
        path.write_bytes(canned_result(permission_denials=[
            {"tool_name": "Bash", "tool_use_id": ident, "tool_input": {"command": command}}]))
        return {"stdout": str(path), "exit": 0, "account": "p1"}

    def test_a_first_denial_on_the_continued_resume_is_asked_again_once(self):
        log = install_answers(self.project, [self.hang(), self.denying("rm x"), self.normal()])
        procedures = one_step(self.project)
        self.kill_during_hang(procedures, log, 1)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        records = self.records(log)
        self.assertEqual(len(records), 3)
        self.assertEqual(after(records[2]["argv"], "--resume"), after(records[0]["argv"], "--session-id"))
        (run,) = self.project.runs()
        (prompt,) = (run / "sessions").glob("*.denied.prompt.md")
        self.assertEqual(records[2]["stdin"], prompt.read_text())
        self.assertIn(repr("rm x"), prompt.read_text())
        self.assertNotIn("tool-denied", [e.get("stop") for e in self.project.events(run)])

    def test_a_second_denial_after_the_continued_reask_stops_at_tool_denied_naming_both(self):
        log = install_answers(self.project, [
            self.hang(), self.denying("git log | head"), self.denying("rm x", "toolu_02")])
        procedures = one_step(self.project)
        self.kill_during_hang(procedures, log, 1)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual(line["end"], "tool-denied")
        self.assertLess(line["detail"].index(repr("git log | head")), line["detail"].index(repr("rm x")))
        (run,) = self.project.runs()
        self.assertEqual(len(self.records(log)), 3)
        self.assertEqual(len(list((run / "sessions").glob("*.denied.prompt.md"))), 1)

    def test_a_continued_denial_reask_cut_short_names_both_calls_when_the_visit_continues_again(self):
        log = install_answers(self.project, [
            self.hang(), self.denying("git log | head"), self.hang(), self.denying("rm x", "toolu_02")])
        procedures = one_step(self.project)
        self.kill_during_hang(procedures, log, 1)
        self.kill_during_hang(procedures, log, 3)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual(line["end"], "tool-denied")
        self.assertEqual(len(self.records(log)), 4)
        self.assertLess(line["detail"].index(repr("git log | head")), line["detail"].index(repr("rm x")))

    def test_a_denial_reask_cut_short_names_both_calls_when_the_visit_continues(self):
        log = install_answers(self.project, [
            self.denying("git log | head"), self.hang(), self.denying("rm x", "toolu_02")])
        procedures = one_step(self.project)
        self.kill_during_hang(procedures, log, 2)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual(line["end"], "tool-denied")
        records = self.records(log)
        self.assertEqual(len(records), 3)
        self.assertEqual(after(records[2]["argv"], "--resume"),
                         after(records[0]["argv"], "--session-id"))
        self.assertLess(line["detail"].index(repr("git log | head")),
                        line["detail"].index(repr("rm x")))
        (run,) = self.project.runs()
        self.assertEqual(len(list((run / "sessions").glob("*.denied.prompt.md"))), 1)
        record = json.loads((run / "sessions/draft.1.continue-3.json").read_text())
        self.assertEqual([d["tool_input"]["command"] for d in record["denials"]], ["rm x"])

    def test_a_denial_reask_after_a_miss_cut_short_names_the_miss_resumes_denied_call(self):
        log = install_answers(self.project, [
            {"stdout": str(RESULT_MISSING), "exit": 0, "account": "p1"},
            self.denying("git log | head"), self.hang(), self.denying("rm x", "toolu_02")])
        procedures = one_step(self.project)
        self.kill_during_hang(procedures, log, 3)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual(line["end"], "tool-denied")
        self.assertEqual(len(self.records(log)), 4)
        self.assertLess(line["detail"].index(repr("git log | head")),
                        line["detail"].index(repr("rm x")))

    def test_a_run_killed_once_the_first_denial_was_saved_sends_the_reask_on_the_original_session(self):
        log = install_answers(self.project, [self.denying("git log | head"), self.normal(), self.normal()])
        procedures = one_step(self.project)
        first = self.project.deliver(procedures)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        (run,) = self.project.runs()
        retry = (run / "sessions/draft.1.denied.prompt.md").read_text()
        self.cut(run, "session_answered",
                 drop=("results/draft.1.json", "sessions/draft.1.denied.json"))
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        records = self.records(log)
        self.assertEqual(len(records), 3)
        self.assertEqual(after(records[2]["argv"], "--resume"), after(records[0]["argv"], "--session-id"))
        self.assertEqual(records[2]["stdin"], retry)
        self.assertIn(repr("git log | head"), retry)
        self.assertEqual(self.entered(run), [1])
        self.assertEqual(run_continued(self.project.events(run)), [])

    def test_a_run_killed_after_the_reask_was_announced_and_before_it_launched_sends_the_saved_reask(self):
        log = install_answers(self.project, [self.denying("git log | head"), self.normal(), self.normal()])
        procedures = one_step(self.project)
        first = self.project.deliver(procedures)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        (run,) = self.project.runs()
        retry = (run / "sessions/draft.1.denied.prompt.md").read_text()
        self.cut(run, "session_resuming",
                 drop=("results/draft.1.json", "sessions/draft.1.denied.json"))
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        records = self.records(log)
        self.assertEqual(len(records), 3)
        self.assertEqual(after(records[2]["argv"], "--resume"), after(records[0]["argv"], "--session-id"))
        self.assertEqual(records[2]["stdin"], retry)
        self.assertIn(repr("git log | head"), retry)
        self.assertEqual(self.entered(run), [1])
        self.assertEqual(run_continued(self.project.events(run)), [])

    def test_a_run_killed_after_the_reask_process_started_and_before_it_was_written_sends_the_saved_reask(self):
        log = install_answers(self.project, [self.denying("git log | head"), self.normal(), self.normal()])
        procedures = one_step(self.project)
        first = self.project.deliver(procedures)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        (run,) = self.project.runs()
        retry = (run / "sessions/draft.1.denied.prompt.md").read_text()
        self.cut(run, "process_started", nth=2,
                 drop=("results/draft.1.json", "sessions/draft.1.denied.json"))
        self.assertEqual(self.project.events(run)[-1]["event"], "process_started")
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        records = self.records(log)
        self.assertEqual(len(records), 3)
        self.assertEqual(after(records[2]["argv"], "--resume"), after(records[0]["argv"], "--session-id"))
        self.assertEqual(records[2]["stdin"], retry)
        self.assertIn(repr("git log | head"), retry)
        self.assertEqual(self.entered(run), [1])

    def test_a_run_killed_after_the_second_denial_was_saved_and_before_its_stop_was_recorded_stops_naming_both(self):
        log = install_answers(self.project, [
            self.denying("git log | head"), self.denying("rm x", "toolu_02"), self.normal()])
        procedures = one_step(self.project)
        first = self.project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        (run,) = self.project.runs()
        lines = (run / "events.jsonl").read_text().splitlines(keepends=True)
        self.assertEqual(json.loads(lines[-1])["event"], "stop_reached")
        (run / "events.jsonl").write_text("".join(lines[:-1]), encoding="utf-8")
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual((line["end"], line["need"]), ("tool-denied", "owner-decision"))
        self.assertLess(line["detail"].index(repr("git log | head")), line["detail"].index(repr("rm x")))
        self.assertEqual(len(self.records(log)), 2)  # nothing was launched again
        self.assertEqual(self.entered(run), [1])
        self.assertEqual(run_continued(self.project.events(run)), [])
        self.assertEqual([e["stop"] for e in self.project.events(run) if e["event"] == "stop_reached"],
                         ["tool-denied"])

    def second_denial_after_a_cut(self, event: str) -> None:
        log = install_answers(self.project, [
            self.denying("git log | head"), self.normal(), self.denying("rm x", "toolu_02")])
        procedures = one_step(self.project)
        first = self.project.deliver(procedures)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        (run,) = self.project.runs()
        self.cut(run, event, drop=("results/draft.1.json", "sessions/draft.1.denied.json"))
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        line = json.loads(done.stdout)
        self.assertEqual(line["end"], "tool-denied")
        records = self.records(log)
        self.assertEqual(len(records), 3)
        self.assertEqual(after(records[2]["argv"], "--resume"), after(records[0]["argv"], "--session-id"))
        self.assertLess(line["detail"].index(repr("git log | head")), line["detail"].index(repr("rm x")))
        self.assertEqual(len(list((run / "sessions").glob("*.denied.prompt.md"))), 1)

    def test_a_run_killed_once_the_first_denial_was_saved_and_denied_again_stops_at_tool_denied_naming_both(self):
        self.second_denial_after_a_cut("session_answered")

    def test_a_run_killed_after_the_reask_was_announced_and_denied_again_stops_at_tool_denied_naming_both(self):
        self.second_denial_after_a_cut("session_resuming")

    def test_a_run_killed_after_two_launches_were_announced_and_neither_started_sends_the_saved_reask(self):
        log = install_answers(self.project, [self.denying("git log | head"), self.normal(), self.normal()])
        procedures = one_step(self.project)
        first = self.project.deliver(procedures)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        (run,) = self.project.runs()
        retry = (run / "sessions/draft.1.denied.prompt.md").read_text()
        cut = self.cut(run, "session_resuming",
                       drop=("results/draft.1.json", "sessions/draft.1.denied.json"))
        lines = (run / "events.jsonl").read_text().splitlines(keepends=True)
        again = {**json.loads(lines[cut - 1]), "attempt": 3}
        with (run / "events.jsonl").open("a", encoding="utf-8") as events:
            events.write(json.dumps(again) + "\n")
        self.assertEqual([e["attempt"] for e in self.project.events(run) if e["event"] == "session_resuming"],
                         [2, 3])
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        records = self.records(log)
        self.assertEqual(len(records), 3)
        self.assertEqual(after(records[2]["argv"], "--resume"), after(records[0]["argv"], "--session-id"))
        self.assertEqual(records[2]["stdin"], retry)
        self.assertEqual(self.entered(run), [1])

    def test_a_denied_visit_whose_reask_was_cut_short_stores_the_turns_and_spend_of_every_launch(self):
        denied = self.project.tmp / "denied-counted.json"
        denied.write_bytes(canned_result(
            permission_denials=[{"tool_name": "Bash", "tool_use_id": "t", "tool_input": {"command": "rm x"}}],
            num_turns=3, total_cost_usd=0.1, duration_ms=1000,
            usage={"input_tokens": 1, "cache_creation_input_tokens": 2,
                   "cache_read_input_tokens": 3, "output_tokens": 4}))
        log = install_answers(self.project, [
            {"stdout": str(denied), "exit": 0, "account": "p1"}, self.hang(), self.normal()])
        procedures = one_step(self.project)
        self.kill_during_hang(procedures, log, 2)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (run,) = self.project.runs()
        (stored,) = [e for e in self.project.events(run) if e["event"] == "result_stored"
                     and (e["step"], e["visit"]) == ("draft", 1)]
        self.assertEqual(stored["turns"], 10)  # 3 turns refused, then the normal fixture's 7
        self.assertAlmostEqual(stored["spend_usd"], 0.5321)
        self.assertEqual(stored["tokens"], {"input": 12, "cache_write": 24, "cache_read": 36, "output": 48})
        self.assertAlmostEqual(stored["wall_seconds"], 13.345)

    def test_a_miss_then_a_denial_then_a_cut_reask_stores_the_use_of_every_launch(self):
        missed = self.project.tmp / "missed-counted.json"
        missed.write_bytes(canned_result(
            structured_output=..., num_turns=2, total_cost_usd=0.05, duration_ms=500,
            usage={"input_tokens": 1, "cache_creation_input_tokens": 1,
                   "cache_read_input_tokens": 1, "output_tokens": 1}))
        denied = self.project.tmp / "denied-counted.json"
        denied.write_bytes(canned_result(
            permission_denials=[{"tool_name": "Bash", "tool_use_id": "t", "tool_input": {"command": "rm x"}}],
            num_turns=3, total_cost_usd=0.1, duration_ms=1000,
            usage={"input_tokens": 1, "cache_creation_input_tokens": 2,
                   "cache_read_input_tokens": 3, "output_tokens": 4}))
        log = install_answers(self.project, [
            {"stdout": str(missed), "exit": 0, "account": "p1"},
            {"stdout": str(denied), "exit": 0, "account": "p1"}, self.hang(), self.normal()])
        procedures = one_step(self.project)
        self.kill_during_hang(procedures, log, 3)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (run,) = self.project.runs()
        (stored,) = [e for e in self.project.events(run) if e["event"] == "result_stored"
                     and (e["step"], e["visit"]) == ("draft", 1)]
        self.assertEqual(stored["turns"], 12)  # 2 + 3 + the normal fixture's 7
        self.assertAlmostEqual(stored["spend_usd"], 0.5821)
        self.assertEqual(stored["tokens"], {"input": 13, "cache_write": 25, "cache_read": 37, "output": 49})
        self.assertAlmostEqual(stored["wall_seconds"], 13.845)

    def test_a_second_interruption_resumes_again_under_the_next_attempt(self):
        log = install_answers(self.project, [self.hang(), self.hang(), self.normal()])
        procedures = one_step(self.project)
        self.kill_during_hang(procedures, log, 1)
        self.kill_during_hang(procedures, log, 2)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (run,) = self.project.runs()
        records = self.records(log)
        self.assertEqual(len(records), 3)
        session = after(records[0]["argv"], "--session-id")
        self.assertEqual([after(r["argv"], "--resume") for r in records[1:]], [session, session])
        events = self.project.events(run)
        self.assertEqual([e["attempt"] for e in events if e["event"] == "session_resuming"],
                         [2, 3])
        for attempt in (2, 3):
            self.assertTrue((run / f"sessions/draft.1.continue-{attempt}.prompt.md").exists())
        self.assertEqual(self.entered(run), [1])

    def faulted_then_normal(self, first: dict, code: int = 1) -> None:
        log = install_answers(self.project, [first, self.normal()])
        procedures = one_step(self.project)
        faulted = self.project.deliver(procedures)
        self.assertEqual(faulted.returncode, code, faulted.stdout + faulted.stderr)
        session = after(self.records(log)[0]["argv"], "--session-id")
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (run,) = self.project.runs()
        records = self.records(log)
        self.assertEqual(len(records), 2)
        self.assertIn("--session-id", records[1]["argv"])
        self.assertNotIn("--resume", records[1]["argv"])
        self.assertNotEqual(after(records[1]["argv"], "--session-id"), session)
        self.assertEqual(self.entered(run), [1, 2])
        self.assertEqual(len(run_continued(self.project.events(run))), 1)
        self.assertFalse([e for e in self.project.events(run) if e["event"] == "session_resuming"])

    def test_a_visit_that_faulted_with_no_structured_reply_is_entered_again_under_a_new_visit(self):
        empty = self.project.tmp / "empty.json"
        empty.write_bytes(b"")
        self.faulted_then_normal({"stdout": str(empty), "exit": 1, "account": "p1"})

    def test_a_visit_stopped_on_a_denied_shell_command_is_entered_again_under_a_new_visit(self):
        denied = self.denying("rm -rf x")
        log = install_answers(self.project, [denied, denied, self.normal()])
        procedures = one_step(self.project)
        first = self.project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        session = after(self.records(log)[0]["argv"], "--session-id")
        self.assertEqual(after(self.records(log)[1]["argv"], "--resume"), session)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (run,) = self.project.runs()
        records = self.records(log)
        self.assertEqual(len(records), 3)
        self.assertIn("--session-id", records[2]["argv"])
        self.assertNotIn("--resume", records[2]["argv"])
        self.assertNotEqual(after(records[2]["argv"], "--session-id"), session)
        self.assertEqual(self.entered(run), [1, 2])
        self.assertEqual(len(run_continued(self.project.events(run))), 1)
        resuming = [e for e in self.project.events(run) if e["event"] == "session_resuming"]
        self.assertEqual([e["visit"] for e in resuming], [1])

    def test_a_stale_earlier_result_still_rewinds_before_the_interrupted_session(self):
        log = install_answers(self.project, [self.hang(), self.normal()])
        procedures = write_procedures(self.project, [
            step("a", "count-a", "draft", holds="live"),
            agent_step("draft", "implementer", {"drafted": "done", "stuck": "needs-owner"})])
        self.kill_during_hang(procedures, log, 1)
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (run,) = self.project.runs()
        self.assertEqual(self.project.calls("a"), 2)
        records = self.records(log)
        self.assertNotEqual(after(records[1]["argv"], "--session-id"),
                            after(records[0]["argv"], "--session-id"))
        self.assertEqual(self.entered(run), [1, 2])

    def test_an_entered_visit_with_no_recorded_session_is_entered_again_under_a_new_visit(self):
        procedures, log, run, _ = self.delivered_once()
        self.cut(run, "step_entered", drop=("results/draft.1.json", "sessions/draft.1.json",
                                            "sessions/draft.1.system.md",
                                            "sessions/draft.1.prompt.md"))
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        records = self.records(log)
        self.assertIn("--session-id", records[1]["argv"])
        self.assertNotIn("--resume", records[1]["argv"])
        self.assertEqual(self.entered(run), [1, 2])
        self.assertEqual(len(run_continued(self.project.events(run))), 1)

    def test_a_visit_whose_result_is_stored_without_an_outcome_is_entered_again_under_a_new_visit(self):
        procedures, log, run, session = self.delivered_once()
        self.cut(run, "result_stored")
        lines = (run / "events.jsonl").read_text().splitlines()
        stored = json.loads(lines[-1])
        del stored["outcome"]
        lines[-1] = json.dumps(stored, sort_keys=True, separators=(",", ":"))
        (run / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        records = self.records(log)
        self.assertEqual(len(records), 2)
        self.assertNotEqual(after(records[1]["argv"], "--session-id"), session)
        self.assertNotIn("--resume", records[1]["argv"])
        self.assertEqual(self.entered(run), [1, 2])
        self.assertEqual(len(run_continued(self.project.events(run))), 1)
        self.assertTrue((run / "results/draft.2.json").exists())

    def test_a_visit_that_stopped_at_quota_wait_is_entered_again_under_a_new_visit(self):
        empty = self.project.tmp / "empty.json"
        empty.write_bytes(b"")
        all_out = {"stdout": str(empty), "exit": 75, "account": None,
                   "all_out": {"resumes_at": "2026-11-24T12:00:00Z"}}
        log = install_answers(self.project, [all_out, self.normal()])
        procedures = one_step(self.project)
        first = self.project.deliver(procedures)
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        self.assertEqual(json.loads(first.stdout)["end"], "quota-wait")
        session = after(self.records(log)[0]["argv"], "--session-id")
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        (run,) = self.project.runs()
        records = self.records(log)
        self.assertEqual(len(records), 2)
        self.assertNotEqual(after(records[1]["argv"], "--session-id"), session)
        self.assertNotIn("--resume", records[1]["argv"])
        self.assertEqual(self.entered(run), [1, 2])
        events = self.project.events(run)
        (continued,) = run_continued(events)
        at = events.index(continued)
        self.assertLess(max(i for i, e in enumerate(events) if e["event"] == "wait_started"), at)
        self.assertLess(max(i for i, e in enumerate(events)
                            if e["event"] == "stop_reached" and e["stop"] == "quota-wait"), at)
        self.assertFalse([e for e in events if e["event"] == "session_resuming"])

    def test_a_visit_that_stopped_by_request_is_entered_again_under_a_new_visit(self):
        procedures, log, run, session = self.delivered_once()
        self.cut(run, "session_starting", drop=("results/draft.1.json", "sessions/draft.1.json"))
        engine_ledger.append_event(run, {
            "event": "stop_reached", "at": rfc(datetime.now(timezone.utc)), "step": "draft",
            "stop": "stopped-by-request", "need": "retry"})
        done = self.project.deliver(procedures)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        records = self.records(log)
        self.assertNotEqual(after(records[1]["argv"], "--session-id"), session)
        self.assertNotIn("--resume", records[1]["argv"])
        self.assertEqual(self.entered(run), [1, 2])
        self.assertEqual(len(run_continued(self.project.events(run))), 1)


if __name__ == "__main__":
    unittest.main()
