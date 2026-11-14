"""The host check that a gone manager is brought back (#893).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import socket
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from agent_tools.console import manager, revive_check
from agent_tools.console.manager import StopFailed
from agent_tools.console.revive_check import GOAL
from agent_tools.console.sessions import Observation
from tests.test_console_manager_check import Time
from tests.test_console_message_check import serve
from tests.test_verify_checks import committed_mode
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-manager-revive"
SID = "a" * 16
STATED = "2026-11-12T10:00:00+00:00"
T0 = datetime.fromisoformat(STATED).timestamp()
NAME = manager.session_name("owner/p01", SID)
OLD = "b" * 16
LEGACY = {"project": "owner/p01", "sprint_id": OLD, "phase": "successor",
          "approved_versions": [1], "first_session": "s-0", "first_profile": "work",
          "stopped_at": T0, "back_seconds": 120, "removed_at": T0 + 200}
CLEARED = {"project": "owner/p01", "names": [NAME], "profiles": ["work"]}


def listed(session_id):
    return {session_id: Observation(session_id, "/srv/p01", 1, "idle", None, NAME, None, "work")}


GONE = {}


def old_listed():
    return {"s-0": Observation("s-0", "/srv/p01", 1, "idle", None,
                               manager.session_name("owner/p01", OLD), None, "work")}


def view(*, sprint=True, state="on_track", status=None, text=None, brief=None, managers=True,
         manager_state="started", messages=None, reach_text=None):
    row = {"sprint_id": SID, "goal": GOAL, "stated_at": STATED, "state": state, "status": status,
           "manager_state": manager_state, "manager_text": text,
           "messages": messages or [], "reach_text": reach_text}
    items = [] if brief is None else [{"key": "brief/" + SID, "version": brief,
                                       "waiting_since": STATED}]
    return {"managers": managers,
            "entries": [{"type": "project", "project_id": "owner/p01",
                         "sprints": [row] if sprint else []}],
            "inbox": {"open": items, "answered": []}}


class Readings:
    """The registry: each call returns the next reading (the last repeats). A step `(offset,
    mapping)` first sets the clock `offset` seconds after the stop; `(None, mapping)` leaves it."""

    def __init__(self, test, *steps):
        self.test, self.steps, self.calls = test, list(steps), 0

    def __call__(self):
        offset, mapping = self.steps[min(self.calls, len(self.steps) - 1)]
        if offset is not None and self.calls < len(self.steps):
            self.test.time.now = self.test.stop_time + offset
        self.calls += 1
        return mapping


def steps(*mappings):
    return [(None, m) for m in mappings]


def text(state):
    return {"id": 9, "kind": "text", "text": revive_check.MESSAGE, "state": state}


READ = view(messages=[text("read")])
SENT = view(messages=[text("sent")])
SCRIPT = [view(sprint=False), view(state="drafting", brief=1), view(state="drafting", brief=1),
          view()]


class ReviveCheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.dir)])
        self.state_file = self.dir / "checks" / "state.json"
        self.result_file = self.dir / "checks" / "result.json"
        self.token_file = self.dir / "token"
        self.token_file.write_text("tok\n")
        self.failing = {}
        self.failing_removes = {}
        self.slow = {}
        self.removals = []
        self.stop_time = None
        self.time = Time(T0)

    def stop(self, session_id, profile):
        self.events.append(("stop", session_id, profile))
        if self.stop_time is None:
            self.stop_time = self.time.now
        if self.failing.get(session_id):
            self.failing[session_id] -= 1
            raise StopFailed("the stop failed")
        self.time.now += self.slow.get(session_id, 0)

    def remove(self, session_id, profile):
        self.events.append(("remove", session_id, profile))
        if self.failing_removes.get(session_id):
            self.failing_removes[session_id] -= 1
            raise manager.RemoveFailed("the removal failed")
        self.removals.append(session_id)

    def run_check(self, views, readings, *, saved=None, url=None, budget="2000", now=None,
                  command="start", token=True, statuses=None):
        self.events = []
        if url is None:
            url = serve(self, views, self.events, statuses)
        if saved is not None:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(saved))
        if not token:
            self.token_file.unlink()
        if now is not None:
            self.time.now = now
        registry = Readings(self, *readings)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = revive_check.main(
                [command, "--project", "owner/p01", "--url", url, "--state-file",
                 str(self.state_file), "--result-file", str(self.result_file),
                 "--token-file", str(self.token_file), "--budget", budget],
                registry=registry, stop=self.stop, remove=self.remove,
                clock=self.time.clock, sleep=self.time.sleep)
        return code, json.loads(out.getvalue())

    def timing(self, deadline=None):
        out = io.StringIO()
        argv = ["timing", "--result-file", str(self.result_file)]
        if deadline:
            argv += ["--deadline", str(deadline)]
        with contextlib.redirect_stdout(out):
            code = revive_check.main(argv)
        return code, json.loads(out.getvalue())

    def posts(self, path):
        return [event[2] for event in self.events if event[0] == "post" and event[1] == path]

    def paths(self):
        return [event[1] for event in self.events if event[0] == "post"]

    def stops(self):
        return [event[1] for event in self.events if event[0] == "stop"]

    def removes(self):
        return [e for e in self.events if e[0] == "remove"]

    def finish_events(self):
        return [(e[0], e[1]) for e in self.events
                if e[0] in ("stop", "remove") or (e[0] == "post" and e[1] == "/api/withdraw")]

    def result(self):
        return json.loads(self.result_file.read_text())

    def test_the_wrapper_runs_the_module_and_is_executable(self):
        text = (ROOT / WRAPPER).read_text()
        self.assertTrue(text.startswith("#!/bin/sh"))
        self.assertIn("agent_tools.console.revive_check", text)
        self.assertEqual(committed_mode(WRAPPER), "100755")

    def test_the_removed_session_back_under_the_sprints_name_reading_a_message_is_met(self):
        code, out = self.run_check(SCRIPT + [SENT, READ], [
            (None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, GONE),
            (None, listed("s-1"))])
        self.assertEqual((code, out), (0, {"after_removal": "same", "back_seconds": 130,
                                           "status": "met"}))
        self.assertEqual(self.paths(),
                         ["/api/goal", "/api/approve", "/api/message", "/api/withdraw"])
        self.assertEqual(self.posts("/api/approve"),
                         [{"project_id": "owner/p01", "sprint_id": SID, "version": 1}])
        self.assertEqual(self.posts("/api/message"), [
            {"project_id": "owner/p01", "sprint_id": SID, "text": revive_check.MESSAGE}])
        self.assertEqual(self.removals, ["s-1", "s-1"])
        self.assertIn(("remove", "s-1", "work"), self.events)
        self.assertFalse(self.state_file.exists())
        self.assertEqual(self.result(), {"back_seconds": 130, "status": "met", "cleared": CLEARED})

    def test_a_new_manager_under_the_sprints_name_reading_a_message_is_met(self):
        code, out = self.run_check(SCRIPT + [SENT, READ], [
            (None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, GONE),
            (None, listed("s-2"))])
        self.assertEqual((code, out), (0, {"after_removal": "new", "back_seconds": 130,
                                           "status": "met"}))
        self.assertEqual(len(self.posts("/api/message")), 1)
        self.assertEqual(self.stops(), ["s-1", "s-2"])

    def test_a_slow_return_still_meets_start(self):
        code, out = self.run_check(SCRIPT + [READ], [
            (None, listed("s-1")), (181, listed("s-1")), (None, GONE), (None, listed("s-2"))])
        self.assertEqual((code, out["back_seconds"], out["status"]), (0, 181, "met"))

    def test_a_manager_that_never_returns_is_not_met_after_the_return_limit(self):
        code, out = self.run_check(SCRIPT, [(None, listed("s-1")), (None, GONE)])
        self.assertEqual(code, 1)
        self.assertEqual(out, {"back_seconds": None, "status": "not_met",
                               "reason": "the manager did not come back within 600 s of the stop"})
        self.assertEqual(self.result(), {**out, "cleared": CLEARED})
        self.assertEqual(len(self.posts("/api/withdraw")), 1)
        self.assertFalse(self.state_file.exists())

    def test_a_session_listed_again_after_the_return_limit_is_not_met(self):
        code, out = self.run_check(SCRIPT, [(None, listed("s-1")), (700, listed("s-1"))])
        self.assertEqual((code, out["status"], out["back_seconds"]), (1, "not_met", None))
        self.assertEqual(out["reason"], "the manager did not come back within 600 s of the stop")
        self.assertEqual(self.removals, ["s-1"])

    def test_the_return_limit_holds_across_resumed_runs(self):
        code, out = self.run_check(SCRIPT, [(None, listed("s-1")), (300, GONE)], budget="250")
        self.assertEqual((code, out["phase"], out["status"]), (75, "back", "waiting"))
        saved = json.loads(self.state_file.read_text())
        self.assertEqual(saved["stopped_at"], self.stop_time)
        posted = len(self.posts("/api/goal"))
        code, out = self.run_check([view()], [(None, GONE)], now=self.stop_time + 601,
                                   budget="30")
        self.assertEqual((code, out["status"]), (1, "not_met"))
        self.assertEqual(out["reason"], "the manager did not come back within 600 s of the stop")
        self.assertEqual(self.posts("/api/goal"), [])
        self.assertEqual(posted, 1)
        self.assertFalse(self.state_file.exists())

    def test_a_late_on_track_stops_nothing_so_the_return_time_is_not_the_next_runs_gap(self):
        late = [view(state="drafting", brief=1)] * 26 + [view()]
        code, out = self.run_check([view(sprint=False), *late], steps(listed("s-1")), budget="300")
        self.assertEqual((code, out["phase"], out["status"]), (75, "stop", "waiting"))
        self.assertEqual(self.stops(), [])
        self.assertEqual(json.loads(self.state_file.read_text())["stopped_at"], None)
        code, out = self.run_check([view(), READ], [
            (None, listed("s-1")), (130, listed("s-1")), (None, GONE), (None, listed("s-2"))],
            now=self.time.now + 900, budget="300")
        self.assertEqual((code, out["back_seconds"], out["status"]), (0, 130, "met"))
        self.assertEqual(self.timing(), (0, {"back_seconds": 130, "status": "met"}))

    def test_no_manager_under_the_sprints_name_within_the_limit_is_not_met(self):
        code, out = self.run_check(SCRIPT, [
            (None, listed("s-1")), (20, listed("s-1")), (None, GONE)])
        self.assertEqual((code, out["status"], out["back_seconds"], out["reason"]), (
            1, "not_met", 20, "no manager under the sprint's name within 900 s of the removal"))
        self.assertEqual(self.removals, ["s-1"])
        self.assertEqual(self.result()["back_seconds"], 20)
        self.assertEqual(self.posts("/api/message"), [])

    def test_a_manager_listed_after_the_relist_limit_is_not_met(self):
        code, out = self.run_check(SCRIPT, [
            (None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, GONE),
            (1100, listed("s-2"))])
        self.assertEqual((code, out["status"], out["back_seconds"]), (1, "not_met", 130))
        self.assertEqual(
            out["reason"], "no manager under the sprint's name within 900 s of the removal")

    def test_a_message_left_unread_past_the_limit_is_not_met(self):
        code, out = self.run_check(SCRIPT + [SENT], [
            (None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, GONE),
            (None, listed("s-1"))])
        self.assertEqual((code, out["reason"]), (1, "the message was not read within 600 s"))
        self.assertEqual(len(self.posts("/api/message")), 1)
        self.assertEqual(len(self.posts("/api/withdraw")), 1)

    def test_an_unreachable_manager_is_not_met(self):
        code, out = self.run_check(
            SCRIPT + [view(messages=[text("sent")], reach_text="manager not reachable")], [
                (None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, GONE),
                (None, listed("s-2"))])
        self.assertEqual((code, out["reason"]), (1, "manager not reachable"))

    def test_a_refused_message_is_not_met(self):
        code, out = self.run_check(SCRIPT + [READ], [
            (None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, GONE),
            (None, listed("s-2"))], statuses={"/api/message": [409]})
        self.assertEqual((code, out["reason"]), (1, "the console refused the message: 409"))

    def test_an_unanswered_message_post_is_sent_again_on_the_next_poll(self):
        code, out = self.run_check(SCRIPT + [READ], [
            (None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, GONE),
            (None, listed("s-2"))], statuses={"/api/message": ["drop", 204]})
        self.assertEqual((code, out), (0, {"after_removal": "new", "back_seconds": 130,
                                           "status": "met"}))
        self.assertEqual(self.posts("/api/message"), [
            {"project_id": "owner/p01", "sprint_id": SID, "text": revive_check.MESSAGE}] * 2)

    def test_a_stalled_sprint_is_not_met(self):
        code, out = self.run_check(
            [view(sprint=False), view(state="drafting", manager_state="stalled",
                                      text="managers keep failing: x")], steps(GONE))
        self.assertEqual((code, out["status"], out["reason"]),
                         (1, "not_met", "managers keep failing: x"))
        self.assertEqual(len(self.posts("/api/withdraw")), 1)
        self.assertEqual(self.removals, [])

    def test_a_gone_sprint_is_not_met(self):
        code, out = self.run_check(SCRIPT[:3] + [view(sprint=False)], steps(GONE))
        self.assertEqual((code, out["reason"]), (1, "the sprint is gone"))

    def test_a_spent_budget_keeps_the_state_and_the_next_run_resumes_the_phase(self):
        code, out = self.run_check(SCRIPT, [(None, listed("s-1")), (None, GONE)], budget="40")
        self.assertEqual((code, out), (75, {"phase": "back", "sprint_id": SID,
                                            "status": "waiting"}))
        self.assertEqual(json.loads(self.state_file.read_text())["phase"], "back")
        code, out = self.run_check([SENT], [
            (20, listed("s-1")), (None, GONE), (None, listed("s-1"))],
            now=self.stop_time + 40, budget="12")
        self.assertEqual((code, out), (75, {"phase": "read", "sprint_id": SID,
                                            "status": "waiting"}))
        self.assertIsNotNone(json.loads(self.state_file.read_text())["messaged_at"])
        self.assertEqual(len(self.posts("/api/message")), 1)
        code, out = self.run_check([READ], [(None, listed("s-1"))])
        self.assertEqual((code, out["status"], out["after_removal"]), (0, "met", "same"))
        self.assertEqual(self.posts("/api/message"), [])
        self.assertEqual(self.posts("/api/goal"), [])
        self.assertEqual(self.posts("/api/approve"), [])
        self.assertEqual(self.removals, ["s-1", "s-1"])
        self.assertFalse(self.state_file.exists())

    def test_a_failed_stop_in_the_finish_is_not_yet_and_retried(self):
        self.failing = {"s-2": 1}
        readings = [(None, listed("s-1")), (20, listed("s-1")), (None, GONE),
                    (None, listed("s-2"))]
        code, out = self.run_check(SCRIPT + [READ], readings)
        self.assertEqual((code, out), (75, {
            "reason": "the test manager is not stopped yet: the stop failed", "sprint_id": SID,
            "status": "waiting"}))
        self.assertEqual(self.posts("/api/withdraw"), [])
        self.assertTrue(self.state_file.exists())
        self.assertFalse(self.result_file.exists())
        code, out = self.run_check([READ], [(None, listed("s-2"))])
        self.assertEqual((code, out), (0, {"after_removal": "new", "back_seconds": 20,
                                           "status": "met"}))
        self.assertEqual(self.stops(), ["s-2"])
        self.assertEqual(self.removals[-1], "s-2")
        self.assertEqual(len(self.posts("/api/withdraw")), 1)
        self.assertEqual(self.paths(), ["/api/withdraw"])
        self.assertFalse(self.state_file.exists())

    def discarded_run(self, saved):
        self.result_file.parent.mkdir(parents=True, exist_ok=True)
        self.result_file.write_text(json.dumps({"back_seconds": 120, "status": "met"}))
        code, out = self.run_check(SCRIPT + [SENT, READ], [(None, GONE),
            (None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, GONE),
            (None, listed("s-1"))], saved=saved)
        self.assertEqual((code, out), (0, {"after_removal": "same", "back_seconds": 130,
                                           "status": "met"}))
        self.assertEqual(self.paths(), ["/api/withdraw", "/api/goal", "/api/approve",
                                        "/api/message", "/api/withdraw"])
        self.assertEqual(self.posts("/api/withdraw")[0],
                         {"project_id": "owner/p01", "sprint_id": OLD})
        self.assertEqual(len(self.posts("/api/message")), 1)
        self.assertEqual(self.result(), {"back_seconds": 130, "status": "met", "cleared": CLEARED})
        self.assertFalse(self.state_file.exists())

    def test_a_saved_success_of_the_previous_check_is_discarded_and_a_fresh_check_runs(self):
        self.discarded_run({**LEGACY, "outcome": {"code": 0, "reason": None}})

    def test_a_saved_successor_phase_of_the_previous_check_is_discarded_and_a_fresh_check_runs(
            self):
        self.discarded_run(LEGACY)

    def test_a_failed_cleanup_of_the_previous_checks_state_is_not_yet_and_keeps_it(self):
        self.failing = {"s-0": 1}
        code, out = self.run_check([view()], [(None, old_listed())], saved=LEGACY)
        self.assertEqual((code, out), (75, {
            "reason": "the test manager is not stopped yet: the stop failed", "sprint_id": OLD,
            "status": "waiting"}))
        self.assertEqual(self.stops(), ["s-0"])
        self.assertEqual(self.paths(), [])
        self.assertEqual(json.loads(self.state_file.read_text()), LEGACY)

    def test_the_finish_removes_the_replacement_and_not_the_first_session_again(self):
        code, out = self.run_check(SCRIPT + [SENT, READ], [
            (None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, GONE),
            (None, listed("s-2"))])
        self.assertEqual((code, out), (0, {"after_removal": "new", "back_seconds": 130,
                                           "status": "met"}))
        self.assertEqual(self.removals, ["s-1", "s-2"])
        self.assertEqual(self.finish_events()[-3:], [
            ("stop", "s-2"), ("remove", "s-2"), ("post", "/api/withdraw")])
        self.assertEqual(self.result()["cleared"], CLEARED)

    def test_a_manager_that_never_returns_has_its_stopped_session_removed(self):
        code, out = self.run_check(SCRIPT, [(None, listed("s-1")), (None, GONE)])
        self.assertEqual(code, 1)
        self.assertEqual(self.removals, ["s-1"])
        self.assertLess(self.events.index(("remove", "s-1", "work")),
                        self.finish_index("/api/withdraw"))

    def finish_index(self, path):
        return next(i for i, e in enumerate(self.events) if e[0] == "post" and e[1] == path)

    def test_a_retry_after_one_removal_succeeded_removes_only_the_one_that_failed(self):
        self.failing_removes = {"s-3": 1}
        code, out = self.run_check(SCRIPT, [(None, listed("s-1")), (None, GONE),
                                            (700, listed("s-3"))])
        self.assertEqual((code, out), (75, {
            "reason": "the test manager's session is not removed yet: the removal failed",
            "sprint_id": SID, "status": "waiting"}))
        self.assertEqual(self.removals, ["s-1"])
        self.assertEqual(self.posts("/api/withdraw"), [])
        saved = json.loads(self.state_file.read_text())
        self.assertIsNone(saved["removed_at"])
        self.assertEqual(saved["outcome"], {"code": 1, "reason": revive_check.NO_RETURN_TEXT})
        self.assertEqual(saved["stopped"], [
            {"session_id": "s-1", "profile": "work", "removed": True},
            {"session_id": "s-3", "profile": "work"}])
        code, out = self.run_check([view()], [(None, GONE)])
        self.assertEqual((code, out["status"], out["reason"]),
                         (1, "not_met", revive_check.NO_RETURN_TEXT))
        self.assertEqual(self.removes(), [("remove", "s-3", "work")])
        self.assertEqual(self.removals, ["s-1", "s-3"])
        self.assertEqual(self.paths(), ["/api/withdraw"])
        self.assertFalse(self.state_file.exists())
        self.assertEqual(self.result()["cleared"], CLEARED)

    def test_a_session_stopped_in_the_removal_phase_is_removed_at_the_finish_under_its_profile(
            self):
        both = {**listed("s-1"),
                "s-9": Observation("s-9", "/srv/p01", 2, "idle", None, NAME, None, "p2")}
        code, out = self.run_check(SCRIPT + [SENT, READ], [
            (None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, both),
            (None, listed("s-2")), (None, GONE)])
        self.assertEqual((code, out), (0, {"after_removal": "new", "back_seconds": 130,
                                           "status": "met"}))
        self.assertIn(("stop", "s-9", "p2"), self.events)
        removed = self.events.index(("remove", "s-9", "p2"))
        self.assertGreater(removed, next(i for i, e in enumerate(self.events)
                                         if e[0] == "post" and e[1] == "/api/message"))
        self.assertLess(removed, self.finish_index("/api/withdraw"))
        self.assertEqual(self.removals, ["s-1", "s-9"])
        self.assertEqual(self.result()["cleared"], {
            "project": "owner/p01", "names": [NAME], "profiles": ["p2", "work"]})

    def test_a_failed_removal_keeps_the_outcome_and_the_next_run_removes_the_recorded_session(
            self):
        self.failing_removes = {"s-2": 1}
        readings = [(None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, GONE),
                    (None, listed("s-2"))]
        code, out = self.run_check(SCRIPT + [SENT, READ], readings)
        self.assertEqual((code, out), (75, {
            "reason": "the test manager's session is not removed yet: the removal failed",
            "sprint_id": SID, "status": "waiting"}))
        self.assertEqual(self.posts("/api/withdraw"), [])
        self.assertFalse(self.result_file.exists())
        saved = json.loads(self.state_file.read_text())
        self.assertEqual(saved["outcome"], {"code": 0, "reason": None})
        self.assertEqual(saved["stopped"], [
            {"session_id": "s-1", "profile": "work", "removed": True},
            {"session_id": "s-2", "profile": "work"}])
        code, out = self.run_check([READ], [(None, GONE)])
        self.assertEqual((code, out), (0, {"after_removal": "new", "back_seconds": 130,
                                           "status": "met"}))
        self.assertEqual(self.stops(), [])
        self.assertEqual(self.removes(), [("remove", "s-2", "work")])
        self.assertEqual(self.paths(), ["/api/withdraw"])
        self.assertFalse(self.state_file.exists())

    def test_a_removal_with_no_time_left_is_left_to_the_next_run_with_the_stop_recorded(self):
        self.slow = {"s-2": 2000}
        readings = [(None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, GONE),
                    (None, listed("s-2"))]
        code, out = self.run_check(SCRIPT + [SENT, READ], readings)
        self.assertEqual((code, out), (75, {
            "reason": "the test manager's session is not removed yet: " + manager.OUT_OF_TIME_TEXT,
            "sprint_id": SID, "status": "waiting"}))
        self.assertNotIn(("remove", "s-2", "work"), self.events)
        self.assertEqual(self.posts("/api/withdraw"), [])
        saved = json.loads(self.state_file.read_text())
        self.assertEqual(saved["stopped"][-1], {"session_id": "s-2", "profile": "work"})
        self.assertEqual(saved["outcome"], {"code": 0, "reason": None})
        self.slow = {}
        code, out = self.run_check([READ], [(None, GONE)])
        self.assertEqual(code, 0)
        self.assertEqual(self.removes(), [("remove", "s-2", "work")])
        self.assertEqual(len(self.posts("/api/withdraw")), 1)

    def test_a_running_check_from_before_the_record_has_its_first_session_removed_once(self):
        saved = {"project": "owner/p01", "sprint_id": SID, "phase": "read",
                 "approved_versions": [1], "first_session": "s-1", "first_profile": "work",
                 "stopped_at": T0, "back_seconds": 130, "removed_at": T0 + 200,
                 "after_removal": "new", "messaged_at": T0 + 300}
        code, out = self.run_check([READ], [(None, listed("s-2"))], saved=saved, now=T0 + 310)
        self.assertEqual((code, out["status"]), (0, "met"))
        self.assertEqual(self.removals, ["s-2"])
        self.assertEqual(self.result()["cleared"], CLEARED)
        saved = {**saved, "removed_at": None, "phase": "back", "after_removal": None,
                 "messaged_at": None}
        code, out = self.run_check([view()], [(None, GONE)], saved=saved, now=T0 + 700)
        self.assertEqual((code, out["reason"]), (1, revive_check.NO_RETURN_TEXT))
        self.assertEqual(self.removals[-1:], ["s-1"])

    def test_the_previous_checks_cleanup_removes_what_it_stops_before_it_withdraws(self):
        self.run_check([view()], [(None, old_listed())], saved=LEGACY, budget="5")
        self.assertEqual(self.finish_events()[:3], [
            ("stop", "s-0"), ("remove", "s-0"), ("post", "/api/withdraw")])
        self.assertEqual(self.posts("/api/withdraw")[0], {"project_id": "owner/p01",
                                                          "sprint_id": OLD})

    def test_preconditions_post_nothing(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed = f"http://127.0.0.1:{probe.getsockname()[1]}"
        cases = [("not_running", closed, None, True, 75), ("not_deployed", None, {}, True, 75),
                 ("managers_unavailable", None, view(managers=False), True, 1),
                 ("no_token", None, view(sprint=False), False, 75)]
        for status, url, body, token, code in cases:
            with self.subTest(status=status):
                self.token_file.write_text("tok\n")
                got = self.run_check([body], steps(listed("s-1")), url=url, token=token)
                self.assertEqual(got, (code, {"status": status}))
                self.assertFalse(self.state_file.exists())
                if url is None:
                    self.assertEqual(self.paths(), [])
                self.assertEqual(self.stops(), [])

    def test_timing_reports_the_back_time_against_180_seconds(self):
        self.result_file.parent.mkdir(parents=True)
        cases = [({"back_seconds": 180, "status": "met"}, 0,
                  {"back_seconds": 180, "status": "met"}),
                 ({"back_seconds": 181, "status": "met"}, 1,
                  {"back_seconds": 181, "reason": "slow", "status": "not_met"}),
                 ({"back_seconds": None, "status": "not_met"}, 1,
                  {"back_seconds": None, "reason": "slow", "status": "not_met"})]
        for document, code, printed in cases:
            with self.subTest(document=document):
                self.result_file.write_text(json.dumps(document))
                before = self.result_file.read_text()
                self.assertEqual(self.timing(), (code, printed))
                self.assertEqual(self.result_file.read_text(), before)
        self.result_file.unlink()
        self.assertEqual(self.timing(), (75, {"status": "no_result"}))
        self.assertFalse(self.result_file.exists())

    def test_a_fresh_start_deletes_the_previous_result(self):
        self.result_file.parent.mkdir(parents=True)
        self.result_file.write_text(json.dumps({"back_seconds": 5, "status": "met"}))
        code, out = self.run_check([view(sprint=False), view(state="drafting")],
                                   steps(GONE), budget="5")
        self.assertEqual((code, out["status"]), (75, "waiting"))
        self.assertFalse(self.result_file.exists())
        self.assertEqual(self.timing(), (75, {"status": "no_result"}))

    def test_an_off_loopback_url_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            revive_check.main(["start", "--project", "x", "--url", "http://example.com"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
