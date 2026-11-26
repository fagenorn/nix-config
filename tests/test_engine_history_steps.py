"""Contract tests for the per-step measurements of the engine run history and its child and fault lines.

A history step carries its role, turns, start-up, procedure and (history only) the bounds of its role; a
child run and a run that faults each append a line of their own.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_commands, engine_ledger, engine_session, engine_shell
from agent_tools.delivery.bound_issues import file_pass
from agent_tools.delivery.engine_housekeeping import history_line
from tests.engine_fixture import AdoptedFixtures
from tests.test_bound_issues import FakeTracker
from tests.engine_stubbed_world import StubbedRun
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_deliver import EngineProject, step
from tests.test_engine_fanout import FAN, child as fan_child, fan_children

TIER = "integration"  # the last cases run the engine

FIXTURES = AdoptedFixtures()
RUN = {"run": "1519-20261121T160000Z-a1b2", "project": "example/engine", "issue": 1519,
       "procedure": "direct"}
ENDED = datetime(2026, 11, 21, 17, tzinfo=timezone.utc)
ZERO = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
DRAFT_TOKENS = {"input": 10, "cache_write": 1, "cache_read": 2, "output": 3}


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def never(pid: int, started: str) -> bool:
    return False


def at(clock: str) -> str:
    return f"2026-11-21T{clock}Z"


def entered(name: str, clock: str, visit: int = 1) -> dict:
    return {"event": "step_entered", "at": at(clock), "step": name, "visit": visit, "stage": "building"}


def starting(name: str, clock: str, role: str = "implementer") -> dict:
    return {"event": "session_starting", "at": at(clock), "step": name, "visit": 1,
            "session": f"s-{name}", "role": role, "account": "console"}


def started(name: str, clock: str) -> dict:
    return {"event": "process_started", "at": at(clock), "step": name, "visit": 1, "pid": 4242,
            "started": at(clock)}


def answered(name: str, clock: str, attempt: int) -> dict:
    return {"event": "session_answered", "at": at(clock), "step": name, "visit": 1,
            "session": f"s-{name}", "attempt": attempt, "account": "console"}


def resuming(name: str, clock: str, attempt: int) -> dict:
    return {"event": "session_resuming", "at": at(clock), "step": name, "visit": 1,
            "session": f"s-{name}", "attempt": attempt}


def waiting(clock: str, wait: str) -> dict:
    return {"event": "wait_started", "at": at(clock), "wait": wait, "until": None}


def waited(clock: str, wait: str) -> dict:
    return {"event": "wait_ended", "at": at(clock), "wait": wait}


def result(name: str, clock: str, wall: float, *, turns: int = 12, startup: float | None = None,
           tokens: dict | None = None, spend: float = 1.5) -> dict:
    event = {"event": "result_stored", "at": at(clock), "step": name, "visit": 1,
             "result": f"results/{name}.1.json", "wall_seconds": wall, "turns": turns,
             "tokens": tokens or DRAFT_TOKENS, "spend_usd": spend}
    if startup is not None:
        event["startup_seconds"] = startup
    return event


def graded(name: str, clock: str, outcome: str = "ok") -> dict:
    return {"event": "outcome_graded", "at": at(clock), "step": name, "visit": 1, "outcome": outcome}


def steps_of(events: list[dict]) -> list[dict]:
    for event in events:
        engine_ledger.validate_event(event)
    return history_line(engine_ledger.fold(RUN, events, never), ENDED)["steps"]


class StartUpTest(unittest.TestCase):
    def test_a_usage_limit_retry_keeps_the_answering_launch_start_up_whatever_the_wait(self):
        summary = steps_of([
            entered("implement", "16:00:00"), waiting("16:00:01", "host-slot"),
            waited("16:00:21", "host-slot"), starting("implement", "16:00:21"),
            started("implement", "16:00:22"), answered("implement", "16:00:40", 1),
            waiting("16:00:40", "usage-limit"), resuming("implement", "16:00:41", 2),
            started("implement", "16:00:41"), answered("implement", "16:03:41", 2),
            waited("16:03:41", "usage-limit"),
            result("implement", "16:03:42", 170.0, startup=9.5), graded("implement", "16:03:42"),
            {"event": "run_done", "at": at("16:03:43")}])[0]

        self.assertEqual(summary["startup_seconds"], 9.5)
        self.assertEqual(summary["role"], "implementer")
        self.assertEqual(summary["turns"], 12)
        self.assertEqual(summary["procedure"], "direct")
        self.assertEqual(summary["bounds"], {"wall_seconds": 3600, "turns": 300, "spend_usd": 20.0})
        self.assertEqual(summary["waits"], [{"wait": "host-slot", "seconds": 20.0},
                                            {"wait": "usage-limit", "seconds": 181.0}])

    def test_an_api_retry_pause_is_not_start_up(self):
        summary = steps_of([
            entered("implement", "16:00:00"), starting("implement", "16:00:01"),
            started("implement", "16:00:02"), answered("implement", "16:00:10", 1),
            resuming("implement", "16:00:40", 2), started("implement", "16:00:40"),
            answered("implement", "16:01:00", 2), result("implement", "16:01:01", 58.0, startup=1.5),
            graded("implement", "16:01:01"), {"event": "run_done", "at": at("16:01:02")}])[0]

        self.assertEqual(summary["startup_seconds"], 1.5)

    def test_interleaved_group_members_keep_their_own_start_up(self):
        steps = steps_of([
            entered("lite-review", "16:00:00"), entered("lite-independent", "16:00:00"),
            starting("lite-review", "16:00:01", "reviewer-lite"),
            starting("lite-independent", "16:00:01", "reviewer-lite"),
            waiting("16:00:05", "usage-limit"),
            result("lite-review", "16:00:10", 8.0, startup=3.0), waited("16:00:20", "usage-limit"),
            result("lite-independent", "16:00:30", 25.0, startup=5.0),
            {"event": "run_done", "at": at("16:00:31")}])
        by_name = {summary["step"]: summary for summary in steps}

        self.assertEqual(by_name["lite-review"]["startup_seconds"], 3.0)
        self.assertEqual(by_name["lite-independent"]["startup_seconds"], 5.0)

    def test_start_up_is_the_launch_wall_minus_the_client_duration(self):
        def reading(wall: float | None) -> engine_session.Reading:
            return engine_session.Reading(None, None, [], None, wall, 0, dict(ZERO), 0.0)

        launched = engine_session.Launched(0, b"", b"", 50.0)
        self.assertEqual(engine_session.startup_seconds(launched, reading(42.0)), 8.0)
        self.assertIsNone(engine_session.startup_seconds(launched, reading(None)))
        self.assertIsNone(engine_session.startup_seconds(
            engine_session.Launched(0, b"", b"", 50.0, True), reading(42.0)))
        self.assertEqual(engine_session.startup_seconds(launched, reading(51.0)), 0.0)

    def test_a_command_visit_has_turns_but_no_role_start_up_or_bounds(self):
        summary = steps_of([
            entered("a", "16:00:00"), started("a", "16:00:01"),
            result("a", "16:00:09", 8.0, turns=0, tokens=ZERO, spend=0), graded("a", "16:00:09"),
            {"event": "run_done", "at": at("16:00:10")}])[0]

        self.assertEqual((summary["role"], summary["startup_seconds"], summary["bounds"]),
                         (None, None, None))
        self.assertEqual(summary["turns"], 0)


def history(home: Path) -> list[dict]:
    path = home / ".agents/state/engine/history.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class ChildLineTest(unittest.TestCase):
    def test_each_child_run_appends_its_history_line_and_the_agent_step_carries_its_measurements(self):
        run = StubbedRun(self, fixtures=FIXTURES)

        done = run.deliver()

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        root = run.runs()[0]
        tree = [root]
        for directory in tree:
            tree.extend(run.children(directory))
        lines = history(run.world.home)
        self.assertEqual({line["run"] for line in lines}, {directory.name for directory in tree})
        self.assertEqual(next(line for line in lines if line["run"] == root.name)["end"], "done")
        direct = next(directory for directory in tree
                      if json.loads((directory / "run.json").read_text("utf-8"))["procedure"] == "direct")
        implement = next(s for line in lines if line["run"] == direct.name
                         for s in line["steps"] if s["step"] == "implement")
        self.assertEqual(implement["procedure"], "direct")
        self.assertIsInstance(implement["role"], str)
        self.assertIsInstance(implement["turns"], int)
        self.assertIsInstance(implement["startup_seconds"], float)
        self.assertGreaterEqual(implement["startup_seconds"], 0)
        self.assertIsInstance(implement["bounds"], dict)
        stored = next(e for e in run.events(direct) if e["event"] == "result_stored" and e["step"] == "implement")
        self.assertIn("startup_seconds", stored)


class FaultLineTest(unittest.TestCase):
    def test_a_command_out_of_bounds_with_no_transition_records_a_fault_line(self):
        project = EngineProject(self)
        procedures = project.procedures(
            [step("a", "standin-block", None, on={"ok": "done", "failed": "needs-owner",
                                                  "refused": "needs-owner"})],
            stops={"needs-owner": {"need": "owner-decision", "reenter": "a"},
                   "step-failed": {"need": "retry", "reenter": "a"}})

        with project.inside(), mock.patch.object(engine_commands, "PROJECT_WALL_SECONDS", 1):
            with self.assertRaises(engine_shell.Fault):
                engine_shell.deliver(1520, procedures)

        lines = history(project.world.home)
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["run"], lines[0]["end"], lines[0]["need"]),
                         (project.runs()[0].name, "fault", None))
        self.assertEqual([s["outcome"] for s in lines[0]["steps"]], ["out-of-bounds"])

    def test_a_faulted_out_of_bounds_command_files_one_issue_over_two_passes(self):
        project = EngineProject(self)
        procedures = project.procedures(
            [step("a", "standin-block", None, on={"ok": "done", "failed": "needs-owner",
                                                  "refused": "needs-owner"})],
            stops={"needs-owner": {"need": "owner-decision", "reenter": "a"},
                   "step-failed": {"need": "retry", "reenter": "a"}})
        with project.inside(), mock.patch.object(engine_commands, "PROJECT_WALL_SECONDS", 1):
            with self.assertRaises(engine_shell.Fault):
                engine_shell.deliver(1520, procedures)
        tracker = FakeTracker()
        with tempfile.TemporaryDirectory() as scratch:
            seen, lock = Path(scratch) / "seen.json", Path(scratch) / "pass.lock"
            history_file = project.world.home / ".agents/state/engine/history.jsonl"
            now = datetime.now(timezone.utc)

            first = file_pass(tracker, history_file, seen, lock, now)
            second = file_pass(tracker, history_file, seen, lock, now)

        self.assertEqual([item.kind for item in first], ["out-of-bounds"])
        self.assertEqual(second, [])
        self.assertEqual(len(tracker.created), 1)

    def test_a_walk_that_raises_a_core_error_records_a_fault_line_for_the_root_run(self):
        project = EngineProject(self)

        faulted = project.deliver(project.procedures(FAN("standin-items-object", 2),
                                                     children=fan_children()), issue=1517)

        self.assertEqual(faulted.returncode, 1, faulted.stdout + faulted.stderr)
        lines = history(project.world.home)
        self.assertEqual([(line["run"], line["end"]) for line in lines],
                         [(project.runs()[0].name, "fault")])

    def test_a_child_whose_walk_raises_a_core_error_records_a_fault_line_of_its_own(self):
        project = EngineProject(self)
        inner = FAN("standin-items-object", 1)
        inner[1]["procedure"] = "grand"
        inner[0]["on"] = {"ok": "fan", "failed": "child-stop", "refused": "child-stop"}
        inner[1]["on"] = {"done": "done", "child-stop": "child-stop"}
        children = {"fan-child": fan_child(inner), "grand": fan_children()["fan-child"]}

        faulted = project.deliver(project.procedures(FAN("standin-items", 1), children=children),
                                  issue=1517)

        self.assertEqual(faulted.returncode, 1, faulted.stdout + faulted.stderr)
        ends = {line["run"]: line["end"] for line in history(project.world.home)}
        middle = next(run for run in project.runs()
                      if json.loads((run / "run.json").read_text("utf-8"))["procedure"] == "fan-child")
        self.assertEqual(ends[middle.name], "fault")


if __name__ == "__main__":
    unittest.main()
