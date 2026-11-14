"""The owner stops a sprint and a withdrawal stops its manager (#892).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import sys
import time
from datetime import datetime, timezone
from unittest import mock

from agent_tools.console import console, manager, nudge, service, sessions, sprints
from agent_tools.console.event_log import EventLog

from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_briefs import GOAL_TEXT, JSON, PARTS
from .test_console_reports import REPORT
from .test_console_writes import Case
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

STOP = "/api/stop"
MESSAGE = "/api/message"
T0 = 1_800_000_000.0
FIRST = "s-1aaaaaaaa"


class StopServiceTest(Case):
    def setUp(self):
        super().setUp()
        support.write_registry(self.registry, support.entries(2))
        self.now = [T0]
        self.queued = support.Queued()
        self.listed = {}
        self.nudges = []
        self.nudge_failures = []
        self.stops = []
        self.failures = []
        self.lock_free = []

    def log_clock(self):
        return datetime.fromtimestamp(self.now[0], timezone.utc).isoformat(timespec="microseconds")

    def nudger(self, sent):
        self.nudges.append(sent)
        if self.nudge_failures:
            raise nudge.NudgeFailed(self.nudge_failures.pop(0))

    def stopper(self, session_id, profile):
        self.stops.append((session_id, profile))
        if self.failures:
            raise manager.StopFailed(self.failures.pop(0))

    def begin(self, **overrides):
        support.sign_in(self.store, "work")
        options = dict(
            launcher=support.Launches(), profile_dirs=[support.profile_dir(self.store, "work")],
            dispatch=lambda job: job(), nudger=self.nudger, listing=lambda: dict(self.listed),
            stopper=self.stopper, clock=lambda: self.now[0], log_clock=self.log_clock,
            session_poll_seconds=3600)
        return self.start(**{**options, **overrides})

    def drain(self):
        while self.queued.jobs:
            self.queued.run_next()

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def running(self, svc, session_id=FIRST):
        """A sprint whose manager is started, briefed, approved and listed."""
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        if svc._dispatch == self.queued:
            self.drain()
        svc.send_brief(sid, self.secret(sid), PARTS)
        svc.approve_brief("owner/p01", sid, 1)
        if svc._dispatch == self.queued:
            self.drain()
        self.listed[session_id] = sessions.Observation(
            session_id, "/srv/p01", 1, "idle", None, manager.session_name("owner/p01", sid), None,
            "work")
        return sid

    def stop(self, svc, sid, project_id="owner/p01", **body):
        payload = {"project_id": project_id, "sprint_id": sid, **body}
        return support.post_page(svc.address, STOP, self.own(svc, **JSON),
                                 json.dumps(payload).encode())

    def rows(self, kind):
        return [json.loads(row[4]) for row in support.log_rows(self.store) if row[2] == kind]

    def entry(self, svc, sid):
        for entry in view_of(svc)["entries"]:
            for project in entry["projects"] if entry["type"] == "quiet_group" else [entry]:
                finished = project["finished_sprints"]
                for sprint in [*project["sprints"], *(finished["sprints"] if finished else [])]:
                    if sprint["sprint_id"] == sid:
                        return sprint
        self.fail("no sprint entry")

    def project(self, svc, project_id="owner/p01"):
        for entry in view_of(svc)["entries"]:
            for project in entry["projects"] if entry["type"] == "quiet_group" else [entry]:
                if project["project_id"] == project_id:
                    return project
        self.fail("no project entry")

    def test_stop_sends_one_stop_message_and_a_second_stop_is_refused(self):
        svc = self.begin()
        sid = self.running(svc)
        self.assertEqual(self.stop(svc, sid)[::2], (204, b""))
        rows = support.log_rows(self.store)
        self.assertEqual(self.rows("sprint.stop_requested"), [{"sprint_id": sid, "goal": GOAL_TEXT}])
        kinds = [m["kind"] for m in self.entry(svc, sid)["messages"]]
        self.assertEqual(kinds.count("stop"), 1)
        (message,) = [m for m in self.entry(svc, sid)["messages"] if m["kind"] == "stop"]
        self.assertEqual(message["text"], sprints.STOP_TEXT)
        self.assertEqual(len(self.nudges), 1)
        got = self.stop(svc, sid)
        self.assertEqual((got[0], got[2]), (409, b"this sprint is already stopping\n"))
        self.assertEqual(support.log_rows(self.store), rows)
        self.assertEqual(self.stops, [])

    def test_without_a_closing_report_the_session_is_stopped_once_after_ten_minutes(self):
        svc = self.begin()
        sid = self.running(svc)
        self.stop(svc, sid)
        self.now[0] = T0 + 599.999
        svc.finish_stops()
        self.assertEqual(self.stops, [])
        self.now[0] = T0 + 600
        svc.finish_stops()
        self.assertEqual(self.stops, [(FIRST, "work")])
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        self.now[0] = T0 + 900
        svc.finish_stops()
        self.assertEqual(len(self.stops), 1)
        entry = self.entry(svc, sid)
        self.assertEqual((entry["state"], entry["state_text"]), ("stopped", "stopped by you"))
        self.assertIsNone(entry["closing"])

    def test_a_closing_report_stops_the_session_at_once_and_only_once(self):
        svc = self.begin()
        sid = self.running(svc)
        svc.send_report(sid, self.secret(sid), REPORT)
        self.stop(svc, sid)
        with self.assertRaises(sprints.Refused) as caught:
            svc.send_closing(sid, self.secret(sid), {
                "summary": "Stopped early", "issues": [], "differently": "ask sooner"})
        self.assertEqual(str(caught.exception), sprints.NOT_ENDED)
        self.assertEqual(self.rows("sprint.closed"), [])
        self.assertEqual(self.stops, [])
        svc.send_closing(sid, self.secret(sid), {
            "summary": "Stopped early", "differently": "ask sooner",
            "issues": [{"issue": 12, "stage": "dropped"}, {"issue": 13, "stage": "landed"}]})
        self.assertEqual(self.stops, [(FIRST, "work")])
        self.now[0] = T0 + 700
        svc.finish_stops()
        self.assertEqual(len(self.stops), 1)
        entry = self.entry(svc, sid)
        self.assertEqual((entry["state"], entry["state_text"]), ("stopped", "stopped by you"))
        self.assertEqual(entry["closing"]["first_line"], "Stopped early")

    def seen(self, svc, sid, state):
        """Fold one `session.seen` row of the sprint's manager at the controlled clock."""
        with svc._ingest:
            svc._apply(svc.log.append([("session.seen", "owner/p01", {
                "session_id": FIRST, "cwd": "/srv/p01", "repo": "/srv/p01", "state": state,
                "name": manager.session_name("owner/p01", sid)})]))

    def close_after_landing(self, svc, sid):
        """The last report said landing, then the manager sends its closing report (#980)."""
        svc.send_report(sid, self.secret(sid), REPORT)
        self.seen(svc, sid, "working")
        self.now[0] = T0 + 10
        svc.send_closing(sid, self.secret(sid), {
            "summary": "Importer resumes after a crash", "differently": "cut smaller slices",
            "issues": [{"issue": 12, "stage": "held"}, {"issue": 13, "stage": "landed"}]})

    def test_a_closing_report_stops_the_done_sprints_manager_once_its_turn_has_ended(self):
        svc = self.begin()
        sid = self.running(svc)
        self.close_after_landing(svc, sid)
        self.assertEqual(self.stops, [])
        self.now[0] = T0 + 11
        svc.finish_stops()
        self.assertEqual(self.stops, [])
        self.seen(svc, sid, "idle")
        svc.finish_stops()
        self.assertEqual(self.stops, [(FIRST, "work")])
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        for later in (20, 130, 4000):
            self.now[0] = T0 + later
            svc.finish_stops()
        self.assertEqual(len(self.stops), 1)
        self.assertEqual(len(self.rows("manager.stopped")), 1)
        self.assertEqual(self.entry(svc, sid)["state"], "done")

    def test_a_closing_report_stops_the_manager_two_minutes_after_it_at_the_latest(self):
        svc = self.begin()
        sid = self.running(svc)
        self.close_after_landing(svc, sid)
        self.now[0] = T0 + 10 + 119.999
        svc.finish_stops()
        self.assertEqual(self.stops, [])
        self.now[0] = T0 + 10 + 120
        svc.finish_stops()
        self.assertEqual(self.stops, [(FIRST, "work")])
        self.now[0] = T0 + 10 + 400
        svc.finish_stops()
        self.assertEqual(len(self.stops), 1)

    def test_a_turn_that_ended_before_the_closing_report_does_not_stop_the_manager_early(self):
        svc = self.begin()
        sid = self.running(svc)
        svc.send_report(sid, self.secret(sid), REPORT)
        self.seen(svc, sid, "idle")
        self.now[0] = T0 + 10
        svc.send_closing(sid, self.secret(sid), {
            "summary": "Importer resumes after a crash", "differently": "cut smaller slices",
            "issues": [{"issue": 12, "stage": "held"}, {"issue": 13, "stage": "landed"}]})
        self.now[0] = T0 + 11
        svc.finish_stops()
        self.assertEqual(self.stops, [])

    def test_a_done_sprints_stopped_manager_is_not_brought_back_and_a_restart_keeps_it(self):
        first = self.begin()
        sid = self.running(first)
        self.close_after_landing(first, sid)
        self.now[0] = T0 + 200
        first.finish_stops()
        self.assertEqual(len(self.stops), 1)
        self.listed.clear()
        self.nudges.clear()
        launches = len(self.rows("manager.started"))
        self.now[0] = T0 + 4000
        first.revive()
        first.nudge_idle()
        first.renudge()
        first.finish_stops()
        self.assertEqual(self.nudges, [])
        self.assertEqual(self.rows("manager.woken"), [])
        self.assertEqual(len(self.rows("manager.started")), launches)
        first.close()
        self.now[0] = T0 + 5000
        svc = self.begin()
        svc.finish_stops()
        svc.revive()
        self.assertEqual(len(self.stops), 1)
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        self.assertEqual(self.nudges, [])

    def hooked(self, svc, event, received, **extra):
        """Ingest one hook of the manager's session, received at `received` seconds after T0."""
        svc.ingest_hook(json.dumps({
            "hook_event_name": event, "session_id": FIRST, "cwd": "/srv/p01", **extra}).encode(),
            received_ms=int((T0 + received) * 1000))

    def test_an_idle_state_older_than_the_closing_does_not_stop_the_manager_when_it_is_ingested_late(self):
        svc = self.begin()
        sid = self.running(svc)
        svc.send_report(sid, self.secret(sid), REPORT)
        self.seen(svc, sid, "working")
        self.now[0] = T0 + 10
        svc.send_closing(sid, self.secret(sid), {
            "summary": "Importer resumes after a crash", "differently": "cut smaller slices",
            "issues": [{"issue": 12, "stage": "held"}, {"issue": 13, "stage": "landed"}]})
        self.now[0] = T0 + 11
        self.hooked(svc, "Stop", 5)
        svc.finish_stops()
        self.assertEqual(self.stops, [])
        self.hooked(svc, "Stop", 11)
        svc.finish_stops()
        self.assertEqual(self.stops, [(FIRST, "work")])

    def test_a_notification_that_keeps_the_idle_state_does_not_end_the_turn_after_the_closing(self):
        svc = self.begin()
        sid = self.running(svc)
        svc.send_report(sid, self.secret(sid), REPORT)
        self.seen(svc, sid, "idle")
        self.now[0] = T0 + 10
        svc.send_closing(sid, self.secret(sid), {
            "summary": "Importer resumes after a crash", "differently": "cut smaller slices",
            "issues": [{"issue": 12, "stage": "held"}, {"issue": 13, "stage": "landed"}]})
        self.now[0] = T0 + 11
        self.hooked(svc, "Notification", 11, notification_type="other")
        svc.finish_stops()
        self.assertEqual(self.stops, [])

    def test_a_restart_before_the_closing_stop_gives_a_late_listing_its_settle_window(self):
        first = self.begin()
        sid = self.running(first)
        self.close_after_landing(first, sid)
        self.now[0] = T0 + 11
        self.seen(first, sid, "idle")
        first.close()
        self.now[0] = T0 + 12
        self.listed.clear()
        svc = self.begin()
        svc.finish_stops()
        self.assertEqual(self.stops, [])
        self.assertEqual(self.rows("manager.stopped"), [])
        self.listed[FIRST] = sessions.Observation(
            FIRST, "/srv/p01", 1, "idle", None, manager.session_name("owner/p01", sid), None,
            "work")
        self.now[0] = T0 + 12 + sprints.STOP_SETTLE_MS / 1000
        svc.finish_stops()
        self.assertEqual(self.stops, [(FIRST, "work")])
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])

    def test_a_closed_sprints_manager_is_not_relaunched_by_a_reservation_that_was_already_made(self):
        launcher = support.Launches()
        svc = self.begin(launcher=launcher)
        sid = self.running(svc)
        svc.send_report(sid, self.secret(sid), REPORT)
        svc.send_closing(sid, self.secret(sid), {
            "summary": "Importer resumes after a crash", "differently": "cut smaller slices",
            "issues": [{"issue": 12, "stage": "held"}, {"issue": 13, "stage": "landed"}]})
        launcher.calls.clear()
        with svc._ingest:
            svc._apply(svc.log.append([("manager.failed", "owner/p01", {
                "sprint_id": sid, "goal": GOAL_TEXT, "reason": "boom", "takeover": True})]))
        self.assertIs(self.entry(svc, sid)["retry"], False)
        for token in (service._TakeoverReservation(), service._RetryReservation()):
            svc._launching[sid] = token
            svc._launch_reserved(sid)
        self.assertEqual(launcher.calls, [])
        with self.assertRaises(sprints.Refused):
            svc.retry_manager("owner/p01", sid)

    def test_a_failed_stop_is_shown_and_retried_after_a_minute(self):
        svc = self.begin()
        sid = self.running(svc)
        self.stop(svc, sid)
        self.failures = ["No job matching"]
        self.now[0] = T0 + 600
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            svc.finish_stops()
        self.assertEqual(len(self.stops), 1)
        self.assertEqual(self.rows("manager.stop_failed"),
                         [{"sprint_id": sid, "reason": "No job matching"}])
        self.assertEqual(self.rows("manager.stopped"), [])
        self.assertIn(f"console: manager_stop_failed {sid} No job matching\n", stderr.getvalue())
        entry = self.entry(svc, sid)
        self.assertEqual(entry["state"], "stopping")
        self.assertEqual(entry["stop_text"],
                         "could not stop the manager: No job matching; trying again")
        self.now[0] = T0 + 630
        svc.finish_stops()
        self.assertEqual(len(self.stops), 1)
        self.now[0] = T0 + 660
        svc.finish_stops()
        self.assertEqual(len(self.stops), 2)
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        entry = self.entry(svc, sid)
        self.assertEqual((entry["state"], entry["state_text"]), ("stopped", "stopped by you"))

    def test_the_stop_write_follows_the_page_write_rule(self):
        svc = self.begin()
        sid = self.running(svc)
        body = json.dumps({"project_id": "owner/p01", "sprint_id": sid}).encode()
        origin = f"http://127.0.0.1:{svc.address[1]}"
        refused = [
            ({"Origin": origin, **JSON}, b"token refused\n"),
            ({"Origin": origin, "X-Console-Token": "wrong", **JSON}, b"token refused\n"),
            ({"Origin": "http://evil.example", "X-Console-Token": self.token(), **JSON},
             b"origin refused\n"),
            ({"X-Console-Token": self.token(), **JSON}, b"origin refused\n"),
        ]
        for headers, text in refused:
            with self.subTest(headers=sorted(headers)):
                got = self.assert_unchanged(
                    svc, lambda: support.post_page(svc.address, STOP, headers, body))
                self.assertEqual((got[0], got[2]), (403, text))
        before = len(support.log_rows(self.store))
        self.assertEqual(support.post_page(svc.address, STOP, self.own(svc, **JSON), body)[::2],
                         (204, b""))
        self.assertEqual(len(support.log_rows(self.store)), before + 1 + len(
            [r for r in support.log_rows(self.store)[before:] if r[2] == "sprint.nudged"]))
        self.assertEqual(len(self.rows("sprint.stop_requested")), 1)
        self.assertIn(STOP, service.PAGE_WRITES)

    def test_stop_refusals_append_nothing(self):
        svc = self.begin()
        sid = self.running(svc)
        done = self.running(svc, "s-2bbbbbbbb")
        svc.send_closing(done, self.secret(done), {
            "summary": "All landed", "issues": [], "differently": "nothing"})
        reported = self.running(svc, "s-3cccccccc")
        svc.send_report(reported, self.secret(reported), {**REPORT, "phase": "done"})
        rows, version = support.log_rows(self.store), svc.version
        cases = [
            (self.stop(svc, "0123456789abcdef"), 409, b"this sprint is not open\n"),
            (self.stop(svc, sid, project_id="owner/p00"), 409, b"this sprint is not open\n"),
            (self.stop(svc, done), 409, b"this sprint has ended\n"),
            (self.stop(svc, reported), 409, b"this sprint has ended\n"),
            (self.stop(svc, sid, extra=1), 400, b"bad stop\n"),
        ]
        for got, status, text in cases:
            with self.subTest(text=text):
                self.assertEqual((got[0], got[2]), (status, text))
        self.assertEqual((support.log_rows(self.store), svc.version), (rows, version))
        got = support.request(svc.address, "GET", STOP)
        self.assertEqual((got[0], got[1]["Allow"]), (405, "POST"))

    def test_two_due_polls_dispatch_one_stop(self):
        svc = self.begin(dispatch=self.queued)
        sid = self.running(svc)
        self.stop(svc, sid)
        self.queued.run_next()
        self.now[0] = T0 + 600
        svc.finish_stops()
        svc.finish_stops()
        self.assertEqual(len(self.queued.jobs), 1)
        self.queued.run_next()
        self.assertEqual(self.stops, [(FIRST, "work")])

    def test_without_a_stopper_a_due_stop_is_recorded_without_a_call(self):
        svc = self.begin(stopper=None)
        sid = self.running(svc)
        self.stop(svc, sid)
        self.now[0] = T0 + 600
        svc.finish_stops()
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        self.assertEqual(self.stops, [])
        self.assertEqual(self.entry(svc, sid)["state_text"], "stopped by you")

    def test_the_poll_loop_finishes_due_stops(self):
        svc = self.begin(session_poll_seconds=0.05, dispatch=self.queued)
        sid = self.running(svc)
        self.stop(svc, sid)
        self.queued.run_next()
        self.now[0] += 600
        deadline = time.monotonic() + 10
        while not self.queued.jobs and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(self.queued.jobs), 1)

    def test_a_stop_never_holds_the_ingest_lock(self):
        svc = self.begin()
        sid = self.running(svc)
        self.stop(svc, sid)

        def probed(inner):
            def call(*args):
                free = svc._ingest.acquire(blocking=False)
                self.lock_free.append(free)
                if free:
                    svc._ingest.release()
                return inner(*args)
            return call

        svc._listing = probed(lambda: dict(self.listed))
        svc._stopper = probed(self.stopper)
        self.now[0] = T0 + 600
        svc.finish_stops()
        self.assertTrue(self.lock_free)
        self.assertEqual(set(self.lock_free), {True})
        self.assertEqual(self.stops, [(FIRST, "work")])
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])

    def test_a_stop_that_cannot_be_dispatched_is_a_failed_stop(self):
        svc = self.begin()
        sid = self.running(svc)
        self.stop(svc, sid)

        def broken(job):
            raise RuntimeError("no thread")

        inline = svc._dispatch
        svc._dispatch = broken
        self.now[0] = T0 + 600
        with contextlib.redirect_stderr(io.StringIO()):
            svc.finish_stops()
        self.assertEqual(self.rows("manager.stop_failed"), [{
            "sprint_id": sid, "reason": "the stop could not start: RuntimeError: no thread"}])
        self.assertNotIn(sid, svc._stopping)
        svc._dispatch = inline
        self.now[0] = T0 + 660
        svc.finish_stops()
        self.assertEqual(self.stops, [(FIRST, "work")])

    def test_main_passes_the_platform_stopper(self):
        recorded = {}

        class Stub:
            def __init__(self, *args, **kwargs):
                recorded.update(kwargs)
                raise OSError("x")

        with mock.patch("agent_tools.console.console.service.ConsoleService", Stub), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(console.main(["--port", "0"]), 1)
        self.assertIs(recorded["stopper"], manager.stopper_for(sys.platform))
        self.assertIs(manager.stopper_for("linux"), manager.stop_session)
        self.assertIsNone(manager.stopper_for("darwin"))

    def test_a_stop_and_a_nudge_never_overlap(self):
        svc = self.begin(dispatch=self.queued)
        sid = self.running(svc)
        self.stop(svc, sid)
        self.assertEqual(len(self.queued.jobs), 1)
        self.now[0] = T0 + 600
        svc.finish_stops()
        self.assertEqual(len(self.queued.jobs), 1)
        self.queued.run_next()
        svc.finish_stops()
        self.assertEqual(len(self.queued.jobs), 1)
        self.queued.run_next()
        self.assertEqual(self.stops, [(FIRST, "work")])
        second = self.running(svc, "s-2bbbbbbbb")
        self.stop(svc, second)
        self.queued.run_next()
        self.now[0] = T0 + 1200
        svc.finish_stops()
        self.assertEqual(len(self.queued.jobs), 1)
        svc.send_message("owner/p01", second, "status?")
        self.assertEqual(len(self.queued.jobs), 1)
        self.queued.run_next()
        self.assertEqual(self.stops, [(FIRST, "work"), ("s-2bbbbbbbb", "work")])
        self.assertEqual(self.queued.jobs, [])
        self.assertEqual(len(self.nudges), 2)

    def test_a_stopped_manager_is_never_woken_or_retried(self):
        first = self.begin()
        sid = first.state_goal("owner/p01", GOAL_TEXT)
        self.listed[FIRST] = sessions.Observation(
            FIRST, "/srv/p01", 1, "idle", None, manager.session_name("owner/p01", sid), None,
            "work")
        first.send_brief(sid, self.secret(sid), PARTS)
        first.approve_brief("owner/p01", sid, 1)
        self.nudges.clear()
        first.close()
        log = EventLog(self.store, clock=self.log_clock)
        log.append([("session.seen", "owner/p01", {
            "session_id": FIRST, "cwd": "/srv/p01", "repo": "/srv/p01", "state": "idle",
            "name": manager.session_name("owner/p01", sid)})])
        log.close()
        svc = self.begin()
        self.nudge_failures = ["busy"]
        self.stop(svc, sid)
        self.now[0] = T0 + 600
        svc.finish_stops()
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        self.listed = {}
        self.now[0] = T0 + 900
        svc.renudge()
        self.assertEqual(len(self.nudges), 1)
        rows = support.log_rows(self.store)
        got = support.post_page(svc.address, MESSAGE, self.own(svc, **JSON), json.dumps({
            "project_id": "owner/p01", "sprint_id": sid, "text": "status?"}).encode())
        self.assertEqual((got[0], got[2]), (409, b"this sprint has ended\n"))
        self.assertEqual(support.log_rows(self.store), rows)
        self.assertIs(self.entry(svc, sid)["retry"], False)

    def test_a_launch_not_yet_started_is_dropped_by_a_stop(self):
        launcher = support.Launches()
        svc = self.begin(dispatch=self.queued, launcher=launcher)
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        self.assertEqual(self.stop(svc, sid)[::2], (204, b""))
        self.queued.run_next()
        self.assertEqual(launcher.calls, [])
        self.assertEqual(self.rows("manager.started"), [])
        self.now[0] = T0 + 600
        svc.finish_stops()
        self.queued.run_next()
        self.assertEqual(self.stops, [])
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])

    def test_a_finished_stop_survives_retention_and_a_restart(self):
        first = self.begin()
        sid = self.running(first)
        self.stop(first, sid)
        self.now[0] = T0 + 600
        first.finish_stops()
        self.assertEqual(self.stops, [(FIRST, "work")])
        (row,) = [r for r in support.log_rows(self.store) if r[2] == "manager.stopped"]
        stopped_at = row[1]
        first.close()
        self.now[0] = T0 + 91 * 86400
        svc = self.begin()
        project = self.project(svc)
        self.assertEqual(project["sprints"], [])
        (entry,) = project["finished_sprints"]["sprints"]
        self.assertEqual((entry["sprint_id"], entry["state"], entry["ended_at"]),
                         (sid, "stopped", stopped_at))
        svc.finish_stops()
        self.assertEqual(len(self.stops), 1)
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])

    def test_a_stored_done_report_folds_into_finished_sprints_after_a_restart(self):
        first = self.begin()
        sid = self.running(first)
        reported = first.send_report(sid, self.secret(sid), {**REPORT, "phase": "done"})
        first.close()
        self.now[0] = T0 + 86399
        second = self.begin()
        self.assertEqual([s["sprint_id"] for s in self.project(second)["sprints"]], [sid])
        second.close()
        self.now[0] = T0 + 86400
        third = self.begin()
        project = self.project(third)
        self.assertEqual(project["sprints"], [])
        (entry,) = project["finished_sprints"]["sprints"]
        self.assertEqual((entry["sprint_id"], entry["state"], entry["ended_at"]),
                         (sid, "done", reported))


class WithdrawStopTest(StopServiceTest):
    def withdraw(self, svc, sid, project_id="owner/p01"):
        return support.post_page(svc.address, "/api/withdraw", self.own(svc, **JSON),
                                 json.dumps({"project_id": project_id, "sprint_id": sid}).encode())

    def unstopped(self, svc):
        return view_of(svc)["unstopped"]

    def stored(self, kind):
        return [row for row in support.log_rows(self.store) if row[2] == kind]

    def withdrawing_launch(self, listed_in_launch):
        """A launcher that withdraws the sprint it launches; the service is `self.svc`."""
        self.during = []

        def launch(launched):
            self.svc.withdraw_goal("owner/p01", launched.sprint_id)
            self.during.append(list(self.stops))
            if listed_in_launch:
                self.listed[FIRST] = sessions.Observation(
                    FIRST, "/srv/p01", 1, "idle", None, launched.session_name, None, "work")

        return launch

    def test_withdrawing_stops_the_managers_session_exactly_once(self):
        svc = self.begin()
        sid = self.running(svc)
        self.nudges.clear()
        self.assertEqual(self.withdraw(svc, sid)[::2], (204, b""))
        self.assertEqual(self.stops, [(FIRST, "work")])
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        self.assertEqual(self.stored("manager.stopped")[0][3], "owner/p01")
        self.assertEqual(self.rows("sprint.stop_requested"), [])
        self.assertEqual(self.nudges, [])
        self.now[0] += 3600
        svc.finish_stops()
        self.assertEqual(len(self.stops), 1)

    def test_a_failed_withdrawal_stop_is_shown_and_retried(self):
        svc = self.begin()
        sid = self.running(svc)
        self.failures = ["No job matching"]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(self.withdraw(svc, sid)[::2], (204, b""))
        self.assertEqual(len(self.stops), 1)
        (row,) = self.stored("manager.stop_failed")
        self.assertIn(f"console: manager_stop_failed {sid} No job matching\n", stderr.getvalue())
        self.assertEqual(self.unstopped(svc), [{
            "project_id": "owner/p01", "sprint_id": sid, "goal": GOAL_TEXT,
            "text": "The manager of a withdrawn goal could not be stopped: No job matching; "
                    "trying again",
            "failed_at": row[1]}])
        self.now[0] = T0 + 59
        svc.finish_stops()
        self.assertEqual(len(self.stops), 1)
        self.now[0] = T0 + 60
        svc.finish_stops()
        self.assertEqual(len(self.stops), 2)
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        self.assertEqual(self.unstopped(svc), [])
        self.now[0] = T0 + 3600
        svc.finish_stops()
        self.assertEqual(len(self.stops), 2)

    def test_a_withdrawal_without_a_listed_session_records_a_stop_without_a_call(self):
        svc = self.begin()
        sid = self.running(svc)
        self.listed = {}
        self.now[0] = T0 + 31
        self.withdraw(svc, sid)
        self.assertEqual(self.stops, [])
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        self.assertEqual(self.unstopped(svc), [])

    def test_a_pending_withdrawal_stop_survives_a_restart(self):
        first = self.begin()
        sid = self.running(first)
        self.failures = ["No job matching"]
        with contextlib.redirect_stderr(io.StringIO()):
            self.withdraw(first, sid)
        first.close()
        self.now[0] = T0 + 60
        svc = self.begin()
        self.assertEqual(len(self.unstopped(svc)), 1)
        svc.finish_stops()
        self.assertEqual(len(self.stops), 2)
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        self.assertEqual(self.unstopped(svc), [])

    def test_a_withdrawal_recorded_before_this_change_is_stopped_on_start(self):
        sid = "0123456789abcdef"
        log = EventLog(self.store, clock=self.log_clock)
        log.append([("goal.stated", "owner/p01", {"sprint_id": sid, "goal": GOAL_TEXT})])
        log.append([("goal.withdrawn", "owner/p01", {"sprint_id": sid, "goal": GOAL_TEXT})])
        log.close()
        self.listed[FIRST] = sessions.Observation(
            FIRST, "/srv/p01", 1, "idle", None, manager.session_name("owner/p01", sid), None,
            "work")
        svc = self.begin()
        svc.finish_stops()
        self.assertEqual(self.stops, [(FIRST, "work")])
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])

    def test_without_a_stopper_a_withdrawal_appends_only_its_row(self):
        svc = self.begin(stopper=None)
        sid = self.running(svc)
        before = len(support.log_rows(self.store))
        self.withdraw(svc, sid)
        added = support.log_rows(self.store)[before:]
        self.assertEqual([row[2] for row in added], ["goal.withdrawn"])
        self.now[0] = T0 + 3600
        svc.finish_stops()
        self.assertEqual(len(support.log_rows(self.store)), before + 1)
        self.assertEqual(self.stops, [])

    def test_a_completed_withdrawal_stop_survives_retention_and_a_restart(self):
        first = self.begin()
        sid = self.running(first)
        self.withdraw(first, sid)
        self.assertEqual(len(self.stops), 1)
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        first.close()
        self.now[0] = T0 + 91 * 86400
        svc = self.begin()
        svc.finish_stops()
        self.assertEqual(len(self.stops), 1)
        self.assertEqual(len(self.rows("manager.stopped")), 1)
        self.assertEqual(self.unstopped(svc), [])

    def test_a_restart_after_a_withdrawal_keeps_the_grace_for_a_session_not_yet_listed(self):
        sid = "0123456789abcdef"
        log = EventLog(self.store, clock=self.log_clock)
        log.append([("goal.stated", "owner/p01", {"sprint_id": sid, "goal": GOAL_TEXT})])
        log.append([("goal.withdrawn", "owner/p01", {"sprint_id": sid, "goal": GOAL_TEXT})])
        log.close()
        self.now[0] = T0 + 5
        svc = self.begin()
        svc.finish_stops()
        self.assertEqual(self.stops, [])
        self.assertEqual(self.rows("manager.stopped"), [])
        self.now[0] = T0 + 10
        self.listed[FIRST] = sessions.Observation(
            FIRST, "/srv/p01", 1, "idle", None, manager.session_name("owner/p01", sid), None,
            "work")
        svc.finish_stops()
        self.assertEqual(self.stops, [(FIRST, "work")])
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])

    def test_a_withdrawal_during_a_launch_stops_the_session_the_launch_made(self):
        svc = self.begin(launcher=self.withdrawing_launch(True))
        self.svc = svc
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        self.assertEqual(self.during, [[]])
        self.assertEqual(self.stops, [])
        for kind in ("manager.stopped", "manager.stop_failed", "manager.started"):
            self.assertEqual(self.rows(kind), [])
        svc.finish_stops()
        self.assertEqual(self.stops, [(FIRST, "work")])
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])

    def test_a_poll_between_the_launch_record_and_its_settle_does_not_lose_the_stop(self):
        svc = self.begin(launcher=self.withdrawing_launch(False))
        self.svc = svc
        record = svc._record_launch

        def recorded(*args):
            record(*args)
            svc.finish_stops()

        svc._record_launch = recorded
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        self.assertEqual(self.stops, [])
        self.assertEqual(self.rows("manager.stopped"), [])
        self.now[0] = T0 + 10
        self.listed[FIRST] = sessions.Observation(
            FIRST, "/srv/p01", 1, "idle", None, manager.session_name("owner/p01", sid), None,
            "work")
        svc.finish_stops()
        self.assertEqual(self.stops, [(FIRST, "work")])
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])

    def test_a_session_listed_late_after_a_launch_is_still_stopped(self):
        svc = self.begin(launcher=self.withdrawing_launch(False))
        self.svc = svc
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        svc.finish_stops()
        self.assertEqual(self.stops, [])
        self.assertEqual(self.rows("manager.stopped"), [])
        self.now[0] = T0 + 10
        self.listed[FIRST] = sessions.Observation(
            FIRST, "/srv/p01", 1, "idle", None, manager.session_name("owner/p01", sid), None,
            "work")
        svc.finish_stops()
        self.assertEqual(self.stops, [(FIRST, "work")])
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        self.listed = {}
        self.now[0] = T0 + 100
        second = svc.state_goal("owner/p01", GOAL_TEXT)
        self.now[0] = T0 + 129.999
        svc.finish_stops()
        self.assertEqual(self.rows("manager.stopped"), [{"sprint_id": sid}])
        self.now[0] = T0 + 130
        svc.finish_stops()
        self.assertEqual(self.rows("manager.stopped"),
                         [{"sprint_id": sid}, {"sprint_id": second}])
        self.assertEqual(len(self.stops), 1)
