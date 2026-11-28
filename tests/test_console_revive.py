"""Which step brings a gone manager back (#893).

Run: just agent-workflow-tests
"""

import unittest
from datetime import datetime, timezone

from agent_tools.console import event_log, revive, sprints
from agent_tools.console.deliveries import DeliveryState, IssueStage
from agent_tools.console.event_log import (MANAGER_FAILED, MANAGER_STARTED, MANAGER_WAITING,
                                           Event)
from agent_tools.delivery.engine_ledger import RunState
from tests.test_console_sprints import CLOSING, PARTS, REPORT, SID
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

NAME = "p00 sprint " + SID
BASE = int(datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
DAY = 86_400_000


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


class Rows:
    """Builds rows with a clock in milliseconds and ever-rising seqs."""

    def __init__(self):
        self.seq = 10

    def row(self, ms, kind, payload):
        self.seq += 1
        return Event(self.seq, iso(ms), kind, "p00", {"sprint_id": SID, **payload})

    def goal(self):
        return Event(1, iso(BASE - 1000), event_log.GOAL_STATED, "p00",
                     {"sprint_id": SID, "goal": "one"})

    def brief(self, decision="approved"):
        if decision is None:
            return []
        rows = [Event(2, iso(BASE - 900), event_log.BRIEF_SENT, "owner/p00",
                      {"sprint_id": SID, "version": 1, "goal": "one", "brief": PARTS})]
        if decision == "approved":
            rows.append(Event(3, iso(BASE - 800), event_log.BRIEF_APPROVED, "owner/p00",
                              {"sprint_id": SID, "version": 1, "goal": "one"}))
        elif decision == "changes":
            rows.append(Event(3, iso(BASE - 800), event_log.BRIEF_REPLIED, "owner/p00",
                              {"sprint_id": SID, "version": 1, "goal": "one", "reply": "no"}))
        return rows

    def started(self, ms, **payload):
        return self.row(ms, MANAGER_STARTED,
                        {"profile": "work", "session_name": NAME, **payload})

    def listed(self, ms):
        self.seq += 1
        return Event(self.seq, iso(ms), "session.seen", "p00",
                     {"session_id": "s-1", "cwd": "/r", "repo": "/r", "state": "idle",
                      "name": NAME})

    def woken(self, ms, ok=True, back=None, reason=None):
        payload = {"session_id": "s-1", "ok": ok, "goal": "one"}
        if back is not None:
            payload["back"] = back
        if reason is not None:
            payload["reason"] = reason
        return self.row(ms, event_log.MANAGER_WOKEN, payload)

    def report(self, phase="running", issues=None):
        self.seq += 1
        report = {**REPORT, "phase": phase}
        if issues is not None:
            report["issues"] = issues
        return Event(self.seq, iso(BASE + 1), event_log.SPRINT_REPORTED, "o/a",
                     {"sprint_id": SID, "goal": "g", "report": report})


def fold(rows):
    return sprints.sprint_states(rows)[SID]


def engine_run(issue, project="p00", engine_alive=True, **members):
    values = dict(run=f"run-{issue}", project=project, issue=issue, stage="building", step=None,
                  wait=None, stop=None, done=False, last_event=None, process=None, alive=False,
                  engine_alive=engine_alive)
    values.update(members)
    return RunState(**values)


def with_rows(build, session=True, phase="running"):
    rows = Rows()
    events = [rows.goal(), *rows.brief(), rows.started(BASE), rows.report(phase)]
    if session:
        events.append(rows.listed(BASE + 1))
    events.extend(build(rows))
    return fold(events)


class WorkTest(unittest.TestCase):
    def test_work_is_the_shown_state_without_the_clock(self):
        def sprint(decision, phase=None):
            rows = Rows()
            events = [rows.goal(), *rows.brief(decision)]
            if phase:
                events.append(rows.report(phase))
            return fold(events)

        table = [("no brief", sprint(None), 0, True),
                 ("brief waiting", sprint("none"), 0, False),
                 ("changes asked", sprint("changes"), 0, True),
                 ("approved, no report", sprint("approved"), 0, True),
                 ("running", sprint("approved", "running"), 0, True),
                 ("running, waiting on the owner", sprint("approved", "running"), 1, False),
                 ("closing", sprint("approved", "closing"), 0, False),
                 ("done", sprint("approved", "done"), 0, False)]
        for name, state, waiting, expected in table:
            with self.subTest(name):
                self.assertIs(revive.has_work(state, waiting), expected)


class NextStepTest(unittest.TestCase):
    def test_the_first_step_is_a_wake_exactly_two_minutes_after_the_manager_was_last_listed(self):
        state = with_rows(lambda rows: [])
        self.assertIsNone(revive.next_step(state, 0, BASE, BASE + 119_999, True))
        self.assertEqual(revive.next_step(state, 0, BASE, BASE + 120_000, True), "wake")

    def test_the_gone_clock_starts_at_the_latest_of_listed_manager_row_and_last_revival(self):
        state = with_rows(lambda rows: [])
        listed = BASE + 500_000
        self.assertIsNone(revive.next_step(state, 0, listed, listed + 119_999, True))
        self.assertEqual(revive.next_step(state, 0, listed, listed + 120_000, True), "wake")
        woken = BASE + 900_000
        state = with_rows(lambda rows: [rows.woken(woken, back=True)])
        self.assertIsNone(revive.next_step(state, 0, listed, woken + 119_999, True))
        self.assertEqual(revive.next_step(state, 0, listed, woken + 120_000, True), "wake")

    def test_no_step_for_a_sprint_without_work_however_long_gone(self):
        later = BASE + 10 * DAY
        table = [("brief waiting", lambda: _drafting(), 0),
                 ("waiting on the owner", lambda: with_rows(lambda rows: []), 1),
                 ("closing", lambda: with_rows(lambda rows: [], phase="closing"), 0),
                 ("done", lambda: with_rows(lambda rows: [], phase="done"), 0)]
        for name, build, waiting in table:
            with self.subTest(name):
                self.assertIsNone(revive.next_step(build(), waiting, BASE, later, True))

    def test_no_step_for_a_first_launch_waiting_or_failed_manager_or_none(self):
        later = BASE + 10 * DAY
        table = {"waiting": lambda rows: [rows.row(BASE + 5, MANAGER_WAITING, {"until": None})],
                 "failed": lambda rows: [rows.row(BASE + 5, MANAGER_FAILED, {"reason": "x"})]}
        for name, build in table.items():
            with self.subTest(name):
                state = with_rows(build)
                self.assertIsNone(revive.next_step(state, 0, BASE, later, True))
        rows = Rows()
        state = fold([rows.goal(), *rows.brief(), rows.report()])
        self.assertIsNone(state.manager)
        self.assertIsNone(revive.next_step(state, 0, BASE, later, True))

    def test_a_takeover_that_waits_for_quota_is_tried_again_after_until(self):
        wait = BASE + 1_000_000
        state = with_rows(lambda rows: [rows.row(wait, MANAGER_WAITING,
                                                 {"until": iso(wait + 600_000), "takeover": True})])
        self.assertIsNone(revive.next_step(state, 0, BASE, wait + 120_000, True))
        self.assertIsNone(revive.next_step(state, 0, BASE, wait + 599_999, True))
        self.assertEqual(revive.next_step(state, 0, BASE, wait + 600_000, True), "takeover")
        self.assertEqual(revive.counted(state, wait + 600_000), 0)
        state = with_rows(lambda rows: [rows.row(wait, MANAGER_WAITING,
                                                 {"until": None, "takeover": True})])
        self.assertEqual(revive.next_step(state, 0, BASE, wait + 120_000, True), "takeover")

    def test_an_unknown_session_or_no_waker_means_a_takeover(self):
        state = with_rows(lambda rows: [], session=False)
        self.assertEqual(revive.next_step(state, 0, BASE, BASE + 120_000, True), "takeover")
        state = with_rows(lambda rows: [])
        self.assertEqual(revive.next_step(state, 0, BASE, BASE + 120_000, False), "takeover")

    def test_no_step_while_the_no_progress_item_is_open_until_it_is_continued(self):
        later = BASE + 10 * DAY
        held = with_rows(lambda rows: [
            rows.row(BASE + 10, event_log.MANAGER_NO_PROGRESS, {"goal": "one", "status": None})])
        self.assertIsNotNone(held.no_progress_at)
        self.assertIsNone(revive.next_step(held, 0, BASE, later, True))
        self.assertIsNone(revive.next_step(held, 0, BASE, later, False))
        state = with_rows(lambda rows: [
            rows.row(BASE + 10, event_log.MANAGER_NO_PROGRESS, {"goal": "one", "status": None}),
            rows.row(BASE + 20, event_log.SPRINT_CONTINUED, {"goal": "one"})])
        self.assertIsNone(state.no_progress_at)
        self.assertEqual(revive.next_step(state, 0, BASE, later, True), "wake")

    def test_a_wake_is_not_sent_while_the_managers_account_is_out(self):
        state = with_rows(lambda rows: [])
        later = BASE + 120_000
        self.assertEqual(revive.next_step(state, 0, BASE, later, True), "wake")
        self.assertIsNone(revive.next_step(state, 0, BASE, later, True, out=True))
        self.assertEqual(
            revive.next_step(state, 0, BASE, later, True, out=True, room_elsewhere=True), "takeover")
        self.assertEqual(
            revive.next_step(state, 0, BASE, later, True, out=False, room_elsewhere=True), "wake")
        state = with_rows(lambda rows: [], session=False)
        self.assertEqual(revive.next_step(state, 0, BASE, later, True, out=True), "takeover")

    def test_two_failed_wakes_in_a_row_mean_a_takeover(self):
        table = [
            ("two failed wakes", lambda r: [r.woken(BASE + 10, ok=False, reason="x"),
                                            r.woken(BASE + 20, ok=False, reason="x")], "takeover"),
            ("two wakes never seen back", lambda r: [r.woken(BASE + 10), r.woken(BASE + 20)],
             "takeover"),
            ("failed then back", lambda r: [r.woken(BASE + 10, ok=False, reason="x"),
                                            r.woken(BASE + 20, back=True)], "wake"),
            ("one failed wake", lambda r: [r.woken(BASE + 10, ok=False, reason="x")], "wake")]
        for name, build, expected in table:
            with self.subTest(name):
                state = with_rows(build)
                self.assertEqual(revive.next_step(state, 0, BASE, BASE + 10 * 60_000, True),
                                 expected)

    def test_a_failed_takeover_is_followed_by_a_takeover(self):
        state = with_rows(lambda r: [r.row(BASE + 10, MANAGER_FAILED,
                                           {"reason": "boom", "takeover": True})])
        self.assertEqual(revive.next_step(state, 0, BASE, BASE + 10 * 60_000, True), "takeover")

    def test_three_counted_bring_backs_within_the_hour_mean_a_stall(self):
        last = BASE + 3_000_000

        def three(first):
            return lambda r: [r.woken(first, back=True), r.woken(BASE + 2_000_000, back=True),
                              r.woken(last, back=True)]

        state = with_rows(three(BASE + 1_000_000))
        self.assertEqual(revive.next_step(state, 0, BASE, last + 120_000, True), "stall")
        self.assertEqual(revive.counted(state, last + 120_000), 3)
        state = with_rows(three(BASE + 10))
        now = BASE + 10 + 3_600_001 + 120_000
        self.assertEqual(revive.next_step(state, 0, BASE, now, True), "wake")
        state = with_rows(lambda r: [r.woken(BASE + 10, ok=False, reason="x"),
                                     r.woken(BASE + 20, ok=False, reason="x"),
                                     r.woken(BASE + 30, ok=False, reason="x")])
        self.assertEqual(revive.next_step(state, 0, BASE, BASE + 600_000, True), "takeover")

    def test_a_stalled_sprint_takes_no_step(self):
        state = with_rows(lambda r: [r.row(BASE + 10, event_log.MANAGER_STALLED, {"reason": "r"})])
        self.assertIsNone(revive.next_step(state, 0, BASE, BASE + 10 * DAY, True))

    def test_the_stall_reason_is_the_last_failure_or_gone_again(self):
        state = with_rows(lambda r: [r.woken(BASE + 10, back=True),
                                     r.woken(BASE + 20, ok=False, reason="No conversation")])
        self.assertEqual(revive.stall_reason(state), "No conversation")
        state = with_rows(lambda r: [r.woken(BASE + 10, ok=False, reason="x"),
                                     r.woken(BASE + 20, back=True)])
        self.assertEqual(revive.stall_reason(state), revive.GONE_AGAIN_TEXT)
        self.assertEqual(revive.GONE_AGAIN_TEXT,
                         "the manager stopped again after it was brought back")


class UnheldTest(unittest.TestCase):
    def test_a_takeover_names_each_in_work_delivery_no_live_session_holds(self):
        rows = Rows()
        stages = [(12, "building"), (13, "landed"), (14, "planning"), (15, "queued"),
                  (16, "verifying"), (17, "held"), (18, "working"), (19, "building"),
                  (20, "final review"), (21, "building"), (22, "building"), (23, "building")]
        state = fold([rows.goal(), *rows.brief(), rows.started(BASE),
                      rows.report(issues=[{"issue": n, "stage": s} for n, s in stages])])
        runs = [DeliveryState("s-gone", "r-1", 1, (IssueStage(12, "building"),), project="p00"),
                DeliveryState("s-live", "r-2", 1, (IssueStage(14, "planning"),), project="p00"),
                DeliveryState("s-live", "r-3", 1, (IssueStage(16, "verifying"),), project="p01"),
                DeliveryState("s-live", "r-4", 1, (IssueStage(18, "building"),), project=None)]
        live = {"s-live"}
        engine = [engine_run(19), engine_run(20, project="p01"),
                  engine_run(21, engine_alive=False), engine_run(22, done=True),
                  engine_run(23, wait={"wait": "usage-limit", "until": None})]
        found = revive.unheld(state, runs, live, engine)
        block = revive.unheld_block(state, found)
        self.assertEqual(found, (12, 16, 18, 20, 21, 22))
        self.assertEqual(block, revive.UNHELD_HEAD + "\n- issue 12 at stage building"
                         "\n- issue 16 at stage verifying\n- issue 18 at stage working"
                         "\n- issue 20 at stage final review\n- issue 21 at stage building"
                         "\n- issue 22 at stage building\n" + revive.UNHELD_TAIL)
        self.assertNotIn("The goal: ", block)
        self.assertEqual(revive.unheld(state, runs, live), (12, 16, 18, 19, 20, 21, 22, 23))

    def test_a_sprint_with_no_report_or_no_unheld_issue_carries_no_block(self):
        rows = Rows()
        no_report = fold([rows.goal(), *rows.brief(), rows.started(BASE)])
        held = fold([rows.goal(), *rows.brief(), rows.started(BASE), rows.report()])
        runs = [DeliveryState("s-live", "r-1", 1, (IssueStage(12, "building"),), project="p00")]
        live = {"s-live"}
        self.assertEqual(revive.unheld(no_report, runs, live), ())
        self.assertEqual(revive.unheld(held, runs, live), ())
        self.assertEqual(revive.unheld_block(held, ()), "")
        self.assertEqual(revive.unheld_block(held, (99,)), "")

    def test_the_block_constants_are_the_prompt_texts(self):
        self.assertEqual(revive.UNHELD_HEAD, "No running session holds these deliveries any more, "
                         "though your sprint lists them as in work:")
        self.assertEqual(revive.UNHELD_LINE, "- issue {issue} at stage {stage}")
        self.assertEqual(revive.UNHELD_TAIL,
                         "Before anything else, name each of them in your next report: say in its "
                         "status line, in plain words and without their numbers, that they stopped, "
                         "and in its next step how you resume each one.")
        self.assertNotRegex(revive.UNHELD_TAIL, r"#\d")


class RetryTest(unittest.TestCase):
    def test_a_stalled_sprint_offers_retry_while_no_manager_is_listed(self):
        state = with_rows(lambda r: [r.row(BASE + 10, event_log.MANAGER_STALLED, {"reason": "r"})])
        now = BASE + 20
        self.assertEqual(sprints.manager_status(state, False, now, True),
                         ("stalled", "managers keep failing: r", True))
        self.assertEqual(sprints.manager_status(state, True, now, True),
                         ("stalled", "managers keep failing: r", False))
        self.assertEqual(sprints.manager_status(state, False, now, False)[0], "unavailable")

    def test_a_takeover_failed_or_waiting_row_offers_retry_with_a_brief(self):
        cases = {"failed": (MANAGER_FAILED, {"reason": "boom"}),
                 "waiting": (MANAGER_WAITING, {"until": None})}
        for name, (kind, payload) in cases.items():
            with self.subTest(name):
                takeover = with_rows(lambda r: [r.row(BASE + 10, kind,
                                                      {**payload, "takeover": True})])
                self.assertIs(sprints.manager_status(takeover, False, BASE + 20, True)[2], True)
                self.assertIs(sprints.manager_status(takeover, True, BASE + 20, True)[2], False)
                first = with_rows(lambda r: [r.row(BASE + 10, kind, payload)])
                self.assertIsNotNone(first.brief)
                self.assertIs(sprints.manager_status(first, False, BASE + 20, True)[2], False)

    def test_a_closed_sprint_never_offers_retry_whatever_its_manager_row_says(self):
        cases = {"failed": (MANAGER_FAILED, {"reason": "boom", "takeover": True}),
                 "waiting": (MANAGER_WAITING, {"until": None, "takeover": True})}
        for name, (kind, payload) in cases.items():
            with self.subTest(name):
                closed = with_rows(lambda r: [
                    r.row(BASE + 10, kind, payload),
                    r.row(BASE + 11, event_log.SPRINT_CLOSED, {"goal": "one", "closing": CLOSING})])
                self.assertIsNotNone(closed.closing)
                self.assertIs(sprints.manager_status(closed, False, BASE + 20, True)[2], False)


def _drafting():
    rows = Rows()
    return fold([rows.goal(), *rows.brief("none"), rows.started(BASE)])


if __name__ == "__main__":
    unittest.main()
