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
from types import SimpleNamespace
from unittest import mock

from agent_tools.console import manager, revive_check
from agent_tools.console.manager import StopFailed
from agent_tools.console.revive_check import GOAL
from agent_tools.console.sessions import Observation
from tests.test_console_manager_check import Time
from tests.test_console_message_check import serve
from tests.test_verify_checks import committed_mode

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-manager-revive"
SID = "a" * 16
STATED = "2026-11-12T10:00:00+00:00"
T0 = datetime.fromisoformat(STATED).timestamp()
NAME = manager.session_name("owner/p01", SID)


def listed(session_id):
    return {session_id: Observation(session_id, "/srv/p01", 1, "idle", None, NAME, None, "work")}


GONE = {}


def view(*, sprint=True, state="on_track", status=None, text=None, brief=None, managers=True,
         manager_state="started"):
    row = {"sprint_id": SID, "goal": GOAL, "stated_at": STATED, "state": state, "status": status,
           "manager_state": manager_state, "manager_text": text}
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

    def remove(self, session_id, profile):
        self.events.append(("remove", session_id, profile))
        self.removals.append(session_id)

    def run_check(self, views, readings, *, saved=None, url=None, budget="2000", now=None,
                  command="start", token=True):
        self.events = []
        if url is None:
            url = serve(self, views, self.events)
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

    def result(self):
        return json.loads(self.result_file.read_text())

    def test_the_wrapper_runs_the_module_and_is_executable(self):
        text = (ROOT / WRAPPER).read_text()
        self.assertTrue(text.startswith("#!/bin/sh"))
        self.assertIn("agent_tools.console.revive_check", text)
        self.assertEqual(committed_mode(WRAPPER), "100755")

    def test_a_full_run_states_approves_stops_waits_removes_and_finds_a_successor(self):
        code, out = self.run_check(SCRIPT, [
            (None, listed("s-1")), (None, GONE), (130, listed("s-1")), (None, GONE),
            (None, listed("s-2"))])
        self.assertEqual((code, out), (0, {"back_seconds": 130, "status": "met",
                                           "successor": True}))
        self.assertEqual(self.paths(), ["/api/goal", "/api/approve", "/api/withdraw"])
        self.assertEqual(self.posts("/api/approve"),
                         [{"project_id": "owner/p01", "sprint_id": SID, "version": 1}])
        self.assertEqual(self.stops(), ["s-1", "s-2"])
        self.assertEqual(self.removals, ["s-1"])
        self.assertIn(("remove", "s-1", "work"), self.events)
        self.assertFalse(self.state_file.exists())
        self.assertEqual(self.result(), {"back_seconds": 130, "status": "met"})

    def test_a_slow_return_still_meets_start(self):
        code, out = self.run_check(SCRIPT, [
            (None, listed("s-1")), (181, listed("s-1")), (None, GONE), (None, listed("s-2"))])
        self.assertEqual((code, out["back_seconds"], out["status"]), (0, 181, "met"))

    def test_a_manager_that_never_returns_is_not_met_after_the_return_limit(self):
        code, out = self.run_check(SCRIPT, [(None, listed("s-1")), (None, GONE)])
        self.assertEqual(code, 1)
        self.assertEqual(out, {"back_seconds": None, "status": "not_met",
                               "reason": "the manager did not come back within 600 s of the stop"})
        self.assertEqual(self.result(), out)
        self.assertEqual(len(self.posts("/api/withdraw")), 1)
        self.assertFalse(self.state_file.exists())

    def test_the_return_limit_holds_across_resumed_runs(self):
        code, out = self.run_check(SCRIPT, [(None, listed("s-1")), (300, GONE)], budget="200")
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

    def test_no_successor_within_the_limit_is_not_met(self):
        code, out = self.run_check(SCRIPT, [
            (None, listed("s-1")), (20, listed("s-1")), (None, GONE)])
        self.assertEqual((code, out["status"], out["back_seconds"]), (1, "not_met", 20))
        self.assertEqual(out["reason"], "no new manager within 900 s of the removal")
        self.assertEqual(self.removals, ["s-1"])
        self.assertEqual(self.result()["back_seconds"], 20)

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

    def test_the_removed_session_coming_back_is_not_met(self):
        code, out = self.run_check(SCRIPT, [
            (None, listed("s-1")), (10, listed("s-1")), (None, GONE), (None, listed("s-1"))])
        self.assertEqual((code, out["status"], out["reason"]),
                         (1, "not_met", "the removed session came back"))

    def test_a_spent_budget_keeps_the_state_and_the_next_run_resumes_the_phase(self):
        code, out = self.run_check(SCRIPT, [(None, listed("s-1")), (None, GONE)], budget="40")
        self.assertEqual((code, out), (75, {"phase": "back", "sprint_id": SID,
                                            "status": "waiting"}))
        self.assertEqual(json.loads(self.state_file.read_text())["phase"], "back")
        code, out = self.run_check([view()], [
            (20, listed("s-1")), (None, GONE), (None, listed("s-2"))], now=self.stop_time + 40)
        self.assertEqual((code, out["status"], out["successor"]), (0, "met", True))
        self.assertEqual(self.posts("/api/goal"), [])
        self.assertEqual(self.posts("/api/approve"), [])
        self.assertEqual(self.removals, ["s-1"])
        self.assertFalse(self.state_file.exists())

    def test_a_failed_stop_in_the_finish_is_not_yet_and_retried(self):
        self.failing = {"s-2": 1}
        readings = [(None, listed("s-1")), (20, listed("s-1")), (None, GONE),
                    (None, listed("s-2"))]
        code, out = self.run_check(SCRIPT, readings)
        self.assertEqual((code, out), (75, {
            "reason": "the test manager is not stopped yet: the stop failed", "sprint_id": SID,
            "status": "waiting"}))
        self.assertEqual(self.posts("/api/withdraw"), [])
        self.assertTrue(self.state_file.exists())
        self.assertFalse(self.result_file.exists())
        code, out = self.run_check([view()], [(None, listed("s-2"))])
        self.assertEqual((code, out), (0, {"back_seconds": 20, "status": "met",
                                           "successor": True}))
        self.assertEqual(self.stops(), ["s-2"])
        self.assertEqual(len(self.posts("/api/withdraw")), 1)
        self.assertEqual(self.paths(), ["/api/withdraw"])
        self.assertFalse(self.state_file.exists())

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

    def test_default_remove_names_the_short_id_under_the_sessions_profile(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0)

        revive_check.default_remove("0123456789abcdef-0123", "work", run=run,
                                    environ={"HOME": "/home/u", "PATH": "/bin"})
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["claude-account", "run", "rm", "01234567"])
        self.assertEqual(kwargs["env"]["CLAUDE_ACCOUNT"], "work")
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 60)

    def test_a_failed_removal_raises_its_one_line_reason(self):
        def failing(argv, **kwargs):
            kwargs["stderr"].write(b"first\nno such session\n\n")
            return SimpleNamespace(returncode=1)

        with self.assertRaisesRegex(StopFailed, "no such session"):
            revive_check.default_remove("0123456789abcdef", "work", run=failing, environ={})
        with self.assertRaisesRegex(StopFailed, "the removal exited 3"):
            revive_check.default_remove("0123456789abcdef", "work", environ={},
                                        run=lambda argv, **kw: SimpleNamespace(returncode=3))
        for error, text in ((FileNotFoundError(), "claude-account is not installed"),
                            (subprocess.TimeoutExpired("rm", 60),
                             "the removal did not return within 60 s")):
            with self.subTest(text), self.assertRaisesRegex(StopFailed, text):
                revive_check.default_remove("0123456789abcdef", "work", environ={},
                                            run=mock.Mock(side_effect=error))

    def test_an_off_loopback_url_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            revive_check.main(["start", "--project", "x", "--url", "http://example.com"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
