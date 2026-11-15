"""The manager's report route (#890) and closing route (#892): POST /api/report, /api/close.

Run: just agent-workflow-tests
"""
import contextlib
import dataclasses
import io
import json
import unittest

from agent_tools.console import service, sprints
from agent_tools.console.deliveries import QUIET_AFTER_MS, IssueStage
from agent_tools.console.sprints import (
    BALL_TEXT, CHANGES, NOW_ANSWER_TEXT, NOW_BRIEF_TEXT, NOW_DRAFTING_TEXT, NOW_PERMISSION_TEXT,
    NOW_QUOTA_TEXT, NOW_STARTING_TEXT, NOW_STOPPING_TEXT)

from . import console_test_support as support
from .test_console_answer import view_of
from .test_console_briefs import GOAL_TEXT, JSON, PARTS
from .test_console_view import (
    A, MIN, NAME, T0_MS, briefed, closed, entry, iso, line, observed, open_item, out, reported,
    session, sprint, started, with_manager)
from .test_console_writes import Case
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

REPORT_PATH = "/api/report"
CLOSE_PATH = "/api/close"
URL = "https://github.com/owner/p00/milestone/3"
REPORT = {"status": "two slices are building", "phase": "running", "milestone": "Importer resumes",
          "tracker_url": URL,
          "issues": [{"issue": 13, "stage": "landed"}, {"issue": 12, "stage": "building"}],
          "inbox": [12], "next": "start the resume slice"}
CLOSING = {"summary": "Importer resumes after a crash\nwith detail",
           "issues": [{"issue": 12, "stage": "landed"}, {"issue": 13, "stage": "dropped"}],
           "differently": "cut smaller slices"}
CHECKED = {**REPORT, "issues": [{"issue": 12, "stage": "building"},
                                {"issue": 13, "stage": "landed"}]}


class ReportRouteTest(Case):
    def open(self):
        support.write_registry(self.registry, support.entries(2))
        return self.start()

    def started(self, svc):
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        svc.send_brief(sid, self.secret(sid), PARTS)
        svc.approve_brief("owner/p01", sid, 1)
        return sid

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def report(self, svc, sid, secret, report=REPORT, **headers):
        body = json.dumps({"sprint_id": sid, "secret": secret, "report": report}).encode()
        return support.post_page(svc.address, REPORT_PATH, {**JSON, **headers}, body)

    def refused(self, svc, action, status, text):
        got = self.assert_unchanged(svc, action)
        self.assertEqual((got[0], got[2]), (status, text + b"\n"))
        return got

    def test_a_report_with_the_secret_is_stored(self):
        svc = self.open()
        sid = self.started(svc)
        before = support.log_rows(self.store)
        version = svc.version
        got = self.report(svc, sid, self.secret(sid))
        self.assertGreater(svc.version, version)
        rows = support.log_rows(self.store)
        self.assertEqual(rows[:len(before)], before)
        self.assertEqual(len(rows), len(before) + 1)
        _, at, kind, project, payload = rows[-1]
        self.assertEqual((got[0], got[1]["Content-Type"], got[2]),
                         (200, "application/json", json.dumps({"at": at}, separators=(",", ":")).encode()))
        self.assertEqual((kind, project), ("sprint.reported", "owner/p01"))
        self.assertEqual(json.loads(payload), {
            "sprint_id": sid, "goal": GOAL_TEXT, "report": CHECKED})
        self.assertEqual(svc._sprints[sid].report.status, "two slices are building")

    def test_a_malformed_or_unauthorised_report_is_refused_and_appends_nothing(self):
        svc = self.open()
        sid = self.started(svc)
        other = self.started(svc)
        drafting = svc.state_goal("owner/p01", GOAL_TEXT)
        svc.send_brief(drafting, self.secret(drafting), PARTS)
        gone = svc.state_goal("owner/p01", GOAL_TEXT)
        former = self.secret(gone)
        svc.withdraw_goal("owner/p01", gone)
        right = self.secret(sid)
        without = {k: v for k, v in REPORT.items() if k != "next"}
        table = [
            ("wrong secret", sid, "A" * 43, REPORT, 403, b"secret refused"),
            ("another sprint's secret", sid, self.secret(other), REPORT, 403, b"secret refused"),
            ("empty secret", sid, "", REPORT, 403, b"secret refused"),
            ("unknown sprint", "f" * 16, right, REPORT, 409, b"this sprint is not open"),
            ("withdrawn sprint", gone, former, REPORT, 409, b"this sprint is not open"),
            ("drafting sprint", drafting, self.secret(drafting), REPORT, 409,
             b"this sprint's brief is not approved"),
            ("secret before members", sid, "A" * 43, without, 403, b"secret refused"),
            ("status names an issue", sid, right, {**REPORT, "status": "#12 is building"}, 409,
             b"the status line names an issue number"),
            ("tracker url", sid, right, {**REPORT, "tracker_url": "http://h/m"}, 409,
             b"the report has no valid tracker_url"),
            ("extra key", sid, right, {**REPORT, "colour": "red"}, 400, b"bad report"),
        ]
        for member in sprints.REPORT_MEMBERS:
            table.append((f"no {member}", sid, right,
                          {k: v for k, v in REPORT.items() if k != member}, 409,
                          f"the report has no valid {member}".encode()))
        for name, target, secret, report, status, text in table:
            with self.subTest(name):
                got = self.refused(svc, lambda: self.report(svc, target, secret, report),
                                   status, text)
                self.assertEqual(got[1]["Content-Type"], "text/plain")
                self.assertEqual(got[1]["Connection"], "close")
        valid = json.dumps({"sprint_id": sid, "secret": right, "report": REPORT}).encode()
        headers = [
            ("origin", {**JSON, "Origin": f"http://127.0.0.1:{svc.address[1]}"}, valid, 403,
             b"origin refused"),
            ("media", {"Content-Type": "text/plain"}, valid, 415, b"json only"),
            ("too large", JSON, b"x" * (service.MAX_REPORT_BYTES + 1), 413, b"too large"),
            ("not json", JSON, b"not json", 400, b"bad report"),
        ]
        for name, head, body, status, text in headers:
            with self.subTest(name):
                self.refused(svc, lambda: support.post_page(
                    svc.address, REPORT_PATH, head, body), status, text)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.report(svc, sid, "A" * 43)
        self.assertIn(f"console: report_refused {sid} secret refused", err.getvalue())
        self.assertNotIn("A" * 43, err.getvalue())
        self.assertNotIn(right, err.getvalue())

    def test_other_methods_on_the_report_route_are_refused(self):
        svc = self.open()
        for method in ("GET", "PUT", "DELETE"):
            with self.subTest(method=method):
                got = support.request(svc.address, method, REPORT_PATH)
                self.assertEqual((got[0], got[1]["Allow"]), (405, "POST"))

    def test_the_digest_says_when_the_reported_state_changes(self):
        svc = self.open()
        sid = self.started(svc)
        secret = self.secret(sid)
        for report in (REPORT, REPORT, {**REPORT, "phase": "closing"}):
            self.assertEqual(self.report(svc, sid, secret, report)[0], 200)
        digest = view_of(svc)["digest"]
        prefix = "The sprint for owner/p01 is now"
        self.assertEqual(
            [m["sentence"] for m in digest["recent"] + digest["earlier"]
             if m["sentence"].startswith(prefix)],
            [f"{prefix} closing: {PARTS['title']}", f"{prefix} on track: {PARTS['title']}"])

    def test_a_report_survives_a_restart(self):
        svc = self.open()
        sid = self.started(svc)
        self.assertEqual(self.report(svc, sid, self.secret(sid))[0], 200)
        last = support.log_rows(self.store)[-1]
        svc.close()
        second = self.start()
        self.assertEqual(support.log_rows(self.store)[-1], last)
        self.assertEqual(last[2], "sprint.reported")
        self.assertEqual(second._sprints[sid].report.status, "two slices are building")


class CloseRouteTest(ReportRouteTest):
    def close(self, svc, sid, secret, closing=CLOSING, **headers):
        body = json.dumps({"sprint_id": sid, "secret": secret, "closing": closing}).encode()
        return support.post_page(svc.address, CLOSE_PATH, {**JSON, **headers}, body)

    def reported(self, svc):
        sid = self.started(svc)
        self.assertEqual(self.report(svc, sid, self.secret(sid))[0], 200)
        return sid

    def entry(self, svc, sid):
        view = view_of(svc)
        for project in view["entries"]:
            shown = list(project.get("sprints", ()))
            shown += (project.get("finished_sprints") or {}).get("sprints", [])
            for sprint in shown:
                if sprint["sprint_id"] == sid:
                    return sprint
        self.fail("the sprint is not in the view")

    def test_a_closing_report_is_accepted_only_when_every_issue_is_landed_or_dropped(self):
        svc = self.open()
        sid = self.reported(svc)
        secret = self.secret(sid)
        lone = {**CLOSING, "issues": [{"issue": 12, "stage": "landed"}]}
        building = {**CLOSING, "issues": [{"issue": 12, "stage": "landed"},
                                          {"issue": 13, "stage": "building"}]}
        for closing, text in ((lone, b"an issue of this sprint is neither landed nor dropped"),
                              (building, b"the closing report has no valid issues")):
            self.refused(svc, lambda: self.close(svc, sid, secret, closing), 409, text)
        before = support.log_rows(self.store)
        got = self.close(svc, sid, secret)
        rows = support.log_rows(self.store)
        self.assertEqual(rows[:len(before)], before)
        self.assertEqual(len(rows), len(before) + 1)
        _, at, kind, project, payload = rows[-1]
        self.assertEqual((got[0], got[1]["Content-Type"], got[2]),
                         (200, "application/json", json.dumps({"at": at}, separators=(",", ":")).encode()))
        self.assertEqual((kind, project), ("sprint.closed", "owner/p01"))
        self.assertEqual(json.loads(payload), {
            "sprint_id": sid, "goal": GOAL_TEXT,
            "closing": {"summary": "Importer resumes after a crash\nwith detail",
                        "issues": [{"issue": 12, "stage": "landed"},
                                   {"issue": 13, "stage": "dropped"}],
                        "differently": "cut smaller slices"}})
        shown = self.entry(svc, sid)
        self.assertEqual(shown["state"], "done")
        self.assertEqual((shown["closing"]["landed"], shown["closing"]["dropped"]), ([12], [13]))

    def test_close_refusals_append_nothing(self):
        svc = self.open()
        sid = self.reported(svc)
        drafting = svc.state_goal("owner/p01", GOAL_TEXT)
        svc.send_brief(drafting, self.secret(drafting), PARTS)
        right = self.secret(sid)
        table = [
            ("wrong secret", sid, "A" * 43, CLOSING, 403, b"secret refused"),
            ("unknown sprint", "f" * 16, right, CLOSING, 409, b"this sprint is not open"),
            ("drafting sprint", drafting, self.secret(drafting), CLOSING, 409,
             b"this sprint's brief is not approved"),
            ("extra key", sid, right, {**CLOSING, "colour": "red"}, 400, b"bad closing"),
            ("summary names an issue", sid, right, {**CLOSING, "summary": "#12 landed\nmore"}, 409,
             b"the summary's first line names an issue number"),
        ]
        for name, target, secret, closing, status, text in table:
            with self.subTest(name):
                got = self.refused(svc, lambda: self.close(svc, target, secret, closing),
                                   status, text)
                self.assertEqual(got[1]["Content-Type"], "text/plain")
                self.assertEqual(got[1]["Connection"], "close")
        self.refused(svc, lambda: self.close(
            svc, sid, right, Origin=f"http://127.0.0.1:{svc.address[1]}"), 403, b"origin refused")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.close(svc, sid, "A" * 43)
        self.assertIn(f"console: close_refused {sid} secret refused", err.getvalue())
        self.assertNotIn("A" * 43, err.getvalue())
        self.assertNotIn(right, err.getvalue())
        self.assertEqual(self.close(svc, sid, right)[0], 200)
        self.refused(svc, lambda: self.close(svc, sid, right), 409, b"this sprint has ended")
        self.assertNotIn(right, err.getvalue())

    def test_the_digest_says_the_closing_reports_first_line(self):
        svc = self.open()
        sid = self.reported(svc)
        self.assertEqual(self.close(svc, sid, self.secret(sid))[0], 200)
        digest = view_of(svc)["digest"]
        self.assertIn("The sprint for owner/p01 is done: Importer resumes after a crash",
                      [m["sentence"] for m in digest["recent"]])

    def test_other_methods_on_the_close_route_are_refused(self):
        svc = self.open()
        got = support.request(svc.address, "GET", CLOSE_PATH)
        self.assertEqual((got[0], got[1]["Allow"]), (405, "POST"))


PAST = T0_MS + QUIET_AFTER_MS + MIN
BUILDING = IssueStage(4, "building")


def manager_session(state):
    return session("s1", state, name=NAME)


class SprintBallViewTest(unittest.TestCase):
    def shown(self, state, now_ms, *sessions, **extra):
        return entry(line(state, now_ms, sessions=list(sessions), **extra))

    def test_an_on_track_report_with_an_idle_manager_and_nothing_moved_reads_nothing_running(self):
        s = reported(with_manager(started(A)), T0_MS)
        shown = self.shown(s, PAST, manager_session("idle"))
        self.assertEqual((shown["ball"], shown["ball_text"]),
                         ("nobody", "nothing running, may be stuck"))
        self.assertNotEqual(shown["state_text"], "on track")
        self.assertEqual(shown["now_text"], "two slices are building")

    def test_a_working_manager_session_reads_manager_working_past_the_threshold(self):
        s = reported(with_manager(started(A)), T0_MS)
        shown = self.shown(s, PAST, manager_session("working"))
        self.assertEqual((shown["ball"], shown["ball_text"]), ("manager", "manager working"))

    def test_a_delivery_run_that_moved_recently_reads_manager_working(self):
        for moved_ms, ball in ((PAST - MIN, "manager"), (T0_MS, "nobody")):
            with self.subTest(moved_ms=moved_ms):
                s = observed(reported(started(A), T0_MS), moved_ms, BUILDING)
                self.assertEqual(self.shown(s, PAST, manager_session("idle"))["ball"], ball)

    def test_movement_inside_the_threshold_reads_manager_working(self):
        s = reported(started(A), T0_MS)
        for now, ball in ((T0_MS + QUIET_AFTER_MS - 1, "manager"), (T0_MS + QUIET_AFTER_MS, "nobody")):
            with self.subTest(now=now):
                self.assertEqual(self.shown(s, now)["ball"], ball)

    def test_waiting_on_the_owner_wins_over_a_working_manager(self):
        working = manager_session("working")
        stalled = dataclasses.replace(started(A), stalled="launch failed")
        idle = dataclasses.replace(reported(started(A), T0_MS), no_progress_at=iso(T0_MS))
        cases = (
            (reported(started(A), T0_MS, inbox=(9,)), {("p00", "k9"): open_item("p00", "k9", 9)}),
            (briefed(sprint(A)), None),
            (stalled, None),
            (idle, None),
        )
        for s, records in cases:
            with self.subTest(sprint=s):
                shown = self.shown(s, T0_MS + MIN, working, records=records)
                self.assertEqual((shown["ball"], shown["ball_text"]), ("owner", "waiting on you"))
        self.assertEqual(self.shown(briefed(sprint(A)), T0_MS + MIN)["now_text"], NOW_BRIEF_TEXT)

    def test_a_manager_waiting_in_its_terminal_is_waiting_on_you(self):
        s = reported(with_manager(started(A)), T0_MS)
        answer = self.shown(s, T0_MS + MIN, manager_session("waiting_answer"))
        self.assertEqual((answer["ball"], answer["ball_text"], answer["now_text"]),
                         ("owner", "waiting on you", NOW_ANSWER_TEXT))
        permission = self.shown(s, PAST, manager_session("waiting_permission"),
                                session("s2", "working", name=NAME))
        self.assertEqual((permission["ball"], permission["now_text"]),
                         ("owner", NOW_PERMISSION_TEXT))
        self.assertEqual(self.shown(s, PAST, manager_session("waiting_answer"))["ball"], "owner")

    def test_each_now_sentence_rule(self):
        now = T0_MS + MIN
        stopping = dataclasses.replace(reported(started(A), T0_MS), stop_at=iso(T0_MS))
        waiting = manager_session("waiting_answer")
        table = (
            (sprint(A), [], {}, NOW_DRAFTING_TEXT),
            (briefed(sprint(A), decision=CHANGES), [], {}, NOW_DRAFTING_TEXT),
            (briefed(sprint(A)), [], {}, NOW_BRIEF_TEXT),
            (started(A), [], {}, NOW_STARTING_TEXT),
            (with_manager(started(A)), [], {"capacity": out()}, NOW_QUOTA_TEXT),
            (stopping, [], {}, NOW_STOPPING_TEXT),
            (stopping, [waiting], {}, NOW_STOPPING_TEXT),
            (reported(started(A), T0_MS), [], {}, "two slices are building"),
        )
        for s, sessions, extra, text in table:
            with self.subTest(text=text, sessions=len(sessions)):
                shown = self.shown(s, now, *sessions, **extra)
                self.assertEqual(shown["now_text"], text)
                self.assertIn(shown["ball"], BALL_TEXT)
                self.assertEqual(shown["ball_text"], BALL_TEXT[shown["ball"]])

    def test_an_ended_sprint_has_no_ball_and_no_now_sentence(self):
        stopped = dataclasses.replace(started(A), stopped_at=iso(T0_MS))
        for s in (stopped, closed(started(A), T0_MS, ((12, "landed"),))):
            with self.subTest(sprint=s):
                shown = self.shown(s, T0_MS + MIN)
                self.assertEqual((shown["ball"], shown["ball_text"], shown["now_text"]),
                                 (None, None, None))
