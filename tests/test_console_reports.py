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
    BALL_TEXT, CHANGES, NOW_ANSWER_TEXT, NOW_BRIEF_TEXT, NOW_DECISION_TEXT, NOW_DRAFTING_TEXT,
    NOW_NO_PROGRESS_TEXT, NOW_PERMISSION_TEXT, NOW_QUOTA_TEXT, NOW_REFUSED_TEXT, NOW_STALLED_TEXT,
    NOW_STARTING_TEXT, NOW_STOPPING_TEXT, Question, refused_reason)

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
        for report in (REPORT, REPORT, {**REPORT, "phase": "done"}):
            self.assertEqual(self.report(svc, sid, secret, report)[0], 200)
        digest = view_of(svc)["digest"]
        prefix = "The sprint for owner/p01 changed to"
        self.assertEqual(
            [m["sentence"] for m in digest["recent"] + digest["earlier"]
             if m["sentence"].startswith(prefix)],
            [f"{prefix} done: {PARTS['title']}"])

    def test_a_refused_merge_reads_in_the_sprints_line_and_once_in_the_digest(self):
        svc = self.open()
        sid = self.started(svc)
        refused = {**REPORT, "status": "merge refused: required checks are not green",
                   "inbox": []}
        for _ in range(2):
            self.assertEqual(self.report(svc, sid, self.secret(sid), refused)[0], 200)
        view = view_of(svc)
        shown = next(s for e in view["entries"] for s in e["sprints"] if s["sprint_id"] == sid)
        self.assertEqual(shown["now_text"], "merge refused: required checks are not green")
        self.assertNotEqual(shown["ball"], "owner")
        digest = view["digest"]
        self.assertEqual(
            [m["sentence"] for m in digest["recent"] + digest["earlier"]
             if m["sentence"] == f"A merge in {PARTS['title']} was refused: "
                                 "required checks are not green"],
            [f"A merge in {PARTS['title']} was refused: required checks are not green"])

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
        self.assertEqual(shown["now_text"], "last seen building 1 of 7: Importer resumes")

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

    def test_a_failed_manager_launch_beats_the_freshness_of_the_goal(self):
        failed = with_manager(sprint(A), state="failed")
        shown = self.shown(failed, T0_MS + MIN)
        self.assertEqual((shown["manager_state"], shown["retry"]), ("failed", True))
        self.assertEqual((shown["ball"], shown["ball_text"]), ("owner", "waiting on you"))
        handed_off = self.shown(failed, T0_MS + MIN, manager_session("working"))
        self.assertEqual(handed_off["ball"], "manager")

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
            (reported(started(A), T0_MS), [], {}, "building 1 of 7: Importer resumes"),
        )
        for s, sessions, extra, text in table:
            with self.subTest(text=text, sessions=len(sessions)):
                shown = self.shown(s, now, *sessions, **extra)
                self.assertEqual(shown["now_text"], text)
                self.assertIn(shown["ball"], BALL_TEXT)
                self.assertEqual(shown["ball_text"], BALL_TEXT[shown["ball"]])

    def test_the_now_sentence_names_the_leading_stage_its_count_and_the_milestone(self):
        run = observed(reported(started(A), T0_MS, issues=((4, "queued"),)), T0_MS + MIN,
                       IssueStage(4, "building"))
        cases = (
            (reported(started(A), T0_MS, issues=((1, "building"), (2, "building"), (3, "queued"))),
             T0_MS + MIN, "building 2 of 3: Importer resumes"),
            (reported(started(A), T0_MS, issues=((1, "planning"), (2, "building"))),
             T0_MS + MIN, "building 1 of 2: Importer resumes"),
            (reported(started(A), T0_MS, issues=((1, "queued"), (2, "queued"))),
             T0_MS + MIN, "queued 2 of 2: Importer resumes"),
            (reported(started(A), T0_MS, issues=((1, "landed"), (2, "held"))),
             T0_MS + MIN, "landed 1 of 2: Importer resumes"),
            (reported(started(A), T0_MS, issues=()), T0_MS + MIN, "Importer resumes"),
            (run, T0_MS + 2 * MIN, "building 1 of 1: Importer resumes"),
        )
        for s, now, text in cases:
            with self.subTest(text=text):
                self.assertEqual(self.shown(s, now)["now_text"], text)

    def test_a_sprint_waiting_on_you_says_what_it_waits_for(self):
        question = Question(1, 0, iso(T0_MS), False, "Which store should the checkpoint use?",
                            "the first slice", ("the database", "a file"), "the database")
        cases = (
            (dataclasses.replace(reported(started(A), T0_MS), questions=(question,)), None,
             "waiting for your answer: Which store should the checkpoint use?"),
            (reported(started(A), T0_MS, inbox=(9,)),
             {("p00", "k9"): open_item("p00", "k9", 9)}, NOW_DECISION_TEXT),
            (dataclasses.replace(reported(started(A), T0_MS), stalled="launch failed"), None,
             NOW_STALLED_TEXT),
            (dataclasses.replace(reported(started(A), T0_MS), no_progress_at=iso(T0_MS)), None,
             NOW_NO_PROGRESS_TEXT),
        )
        for s, records, text in cases:
            with self.subTest(text=text):
                shown = self.shown(s, T0_MS + MIN, records=records)
                self.assertEqual((shown["ball"], shown["now_text"]), ("owner", text))

    def test_the_now_sentence_is_never_the_status_line_for_any_ball(self):
        status = "Working on ship the importer"
        s = reported(with_manager(started(A)), T0_MS, status=status)
        question = Question(1, 0, iso(T0_MS), False, "Which store should the checkpoint use?",
                            "the first slice", ("the database", "a file"), "the database")
        cases = (
            (self.shown(s, T0_MS + MIN), "manager"),
            (self.shown(s, PAST, manager_session("idle")), "nobody"),
            (self.shown(dataclasses.replace(s, questions=(question,)), T0_MS + MIN), "owner"),
        )
        for shown, ball in cases:
            with self.subTest(ball=ball):
                self.assertEqual(shown["ball"], ball)
                self.assertTrue(shown["now_text"])
                self.assertNotEqual(shown["now_text"], status)
                self.assertFalse(shown["now_text"].startswith("Working on"))

    def test_a_long_milestone_is_kept_whole(self):
        milestone = " ".join(["word"] * 80)
        s = reported(started(A), T0_MS)
        s = dataclasses.replace(s, report=dataclasses.replace(s.report, milestone=milestone))
        text = self.shown(s, T0_MS + MIN)["now_text"]
        self.assertEqual(text, "building 1 of 7: " + milestone)
        self.assertNotIn("\u2026", text)

    def test_an_ended_sprint_has_no_ball_and_no_now_sentence(self):
        stopped = dataclasses.replace(started(A), stopped_at=iso(T0_MS))
        for s in (stopped, closed(started(A), T0_MS, ((12, "landed"),))):
            with self.subTest(sprint=s):
                shown = self.shown(s, T0_MS + MIN)
                self.assertEqual((shown["ball"], shown["ball_text"], shown["now_text"]),
                                 (None, None, None))


class MergeRefusedViewTest(unittest.TestCase):
    REFUSAL = "merge refused: required checks are not green"

    def shown(self, state, now_ms, *sessions, **extra):
        return entry(line(state, now_ms, sessions=list(sessions), **extra))

    def test_a_refused_merge_reads_merge_refused_with_its_reason_and_the_ball_off_owner(self):
        s = reported(with_manager(started(A)), T0_MS, status=self.REFUSAL)
        shown = self.shown(s, T0_MS + MIN)
        self.assertEqual(shown["now_text"], "merge refused: required checks are not green")
        self.assertEqual((shown["ball"], shown["ball_text"]), ("manager", "manager working"))
        self.assertNotEqual(shown["ball"], "owner")
        self.assertEqual(shown["waiting"], 0)
        self.assertEqual(shown["state_text"], "on track")
        self.assertEqual(shown["status"], self.REFUSAL)

    def test_a_later_report_without_the_refusal_clears_the_sentence(self):
        refused = reported(started(A), T0_MS, status=self.REFUSAL)
        later = reported(refused, T0_MS + MIN)
        self.assertEqual(self.shown(refused, T0_MS + MIN)["now_text"], self.REFUSAL)
        self.assertEqual(self.shown(later, T0_MS + 2 * MIN)["now_text"],
                         "building 1 of 7: Importer resumes")

    def test_a_run_that_closes_out_never_clears_the_refusal(self):
        refused = reported(started(A), T0_MS, status=self.REFUSAL)
        building = observed(refused, T0_MS + MIN, IssueStage(4, "building"))
        closed_out = observed(refused, T0_MS + MIN, IssueStage(4, "done"))
        self.assertEqual(self.shown(building, T0_MS + 2 * MIN)["now_text"], self.REFUSAL)
        self.assertEqual(self.shown(closed_out, T0_MS + 2 * MIN)["now_text"], self.REFUSAL)

    def test_the_refusal_marker_is_case_blind_and_needs_a_reason_at_the_start(self):
        table = (
            ("Merge refused: the pull request is behind its base",
             "merge refused: the pull request is behind its base"),
            ("MERGE REFUSED:   checks are red", "merge refused: checks are red"),
            ("merge refused:", "building 1 of 7: Importer resumes"),
            ("two slices building, merge refused: checks are red",
             "building 1 of 7: Importer resumes"),
        )
        for status, now_text in table:
            with self.subTest(status=status):
                s = reported(started(A), T0_MS, status=status)
                self.assertEqual(self.shown(s, T0_MS + MIN)["now_text"], now_text)
        self.assertEqual(refused_reason("merge refused:  checks are red"), "checks are red")
        self.assertIsNone(refused_reason("merge refused:"))
        self.assertEqual(NOW_REFUSED_TEXT, "merge refused: {reason}")

    def test_a_quiet_refusal_takes_the_last_seen_prefix_and_never_hides_an_owner_wait(self):
        s = reported(with_manager(started(A)), T0_MS, status=self.REFUSAL)
        shown = self.shown(s, PAST, manager_session("idle"))
        self.assertEqual(shown["ball"], "nobody")
        self.assertEqual(shown["now_text"], "last seen " + self.REFUSAL)
        q = Question(1, 0, iso(T0_MS), False, "Which store should the checkpoint use?",
                     "the first slice", ("the database", "a file"), "the database")
        shown = self.shown(dataclasses.replace(s, questions=(q,)), T0_MS + MIN)
        self.assertEqual((shown["ball"], shown["now_text"]), (
            "owner", "waiting for your answer: Which store should the checkpoint use?"))
