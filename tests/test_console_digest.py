"""The console digest: moments in plain sentences and the window they are shown in (#861).

Run: just agent-workflow-tests
"""
import json
import unittest
from datetime import datetime
from pathlib import Path

from agent_tools.claims import forge_owner_action as foa
from agent_tools.console.digest import (
    BRIEF_APPROVED_MOMENT, BRIEF_SENT_MOMENT, EARLIER_MAX, FIRST_VISIT, LOOKED, SHOWN,
    SPRINT_DONE_MOMENT, SPRINT_STATE_MOMENT, SPRINT_WITHDRAWN, Moment, digest, keep, last_looked,
    moments)
from agent_tools.console.event_log import (
    BRIEF_APPROVED, BRIEF_REPLIED, BRIEF_SENT, GOAL_STATED, GOAL_WITHDRAWN, MANAGER_FAILED,
    MANAGER_STALLED, MANAGER_STARTED, MANAGER_WOKEN, SPRINT_CLOSED, SPRINT_REPORTED,
    SPRINT_STOP_REQUESTED, Event)
from agent_tools.console.sessions import SessionState
from agent_tools.console.sprints import sprint_states
from agent_tools.console.view import InboxRecord

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "console" / "digest-events.json").read_text())["cases"]
NOW = datetime.fromisoformat("2026-11-11T12:00:00.000000+00:00")
LOOK = "2026-11-11T10:00:00.000000+00:00"


def at(minute, micro=0, hour=10):
    return f"2026-11-11T{hour:02d}:{minute:02d}:00.{micro:06d}+00:00"


def sentences(moment_dicts):
    return [m["sentence"] for m in moment_dicts]


class DigestTableTest(unittest.TestCase):
    def test_the_fixture_table(self):
        for case in CASES:
            with self.subTest(case["name"]):
                events = [Event(*row) for row in case["events"]]
                now = datetime.fromisoformat(case["now"])
                result = digest(moments(events, {}, {}), case["last_looked"], now)
                self.assertEqual(sentences(result["recent"]), case["recent"])
                self.assertEqual(sentences(result["earlier"]), case["earlier"])
                self.assertEqual(result["omitted"], case["omitted"])
                for moment in result["recent"] + result["earlier"]:
                    self.assertEqual(set(moment), {"at", "kind", "sentence"})


class DigestTest(unittest.TestCase):
    def test_a_first_visit_covers_eight_hours(self):
        made = [Moment(1, "2026-11-11T03:59:59.999999+00:00", "k", "a"),
                Moment(2, "2026-11-11T04:00:00.000000+00:00", "k", "b"),
                Moment(3, "2026-11-11T04:00:00.000001+00:00", "k", "c"),
                Moment(4, "2026-11-11T11:59:00.000000+00:00", "k", "d")]
        result = digest(made, None, NOW)
        self.assertIsNone(result["since"])
        self.assertIs(result["first_visit"], True)
        self.assertEqual(sentences(result["recent"]), ["d", "c"])
        self.assertEqual(FIRST_VISIT.total_seconds(), 8 * 3600)

    def test_a_returning_visit_says_since_when(self):
        made = [Moment(1, LOOK, "k", "at the look"), Moment(2, at(0, 1), "k", "after")]
        result = digest(made, LOOK, NOW)
        self.assertEqual(result["since"], LOOK)
        self.assertIs(result["first_visit"], False)
        self.assertEqual(sentences(result["recent"]), ["after"])

    def test_the_digest_is_capped_with_the_rest_earlier(self):
        made = [Moment(n, at(n % 60, hour=10 + n // 60), "k", f"m{n}") for n in range(1, 61)]
        result = digest(made, LOOK, NOW)
        self.assertEqual((SHOWN, EARLIER_MAX), (5, 50))
        self.assertEqual(sentences(result["recent"]), [f"m{n}" for n in range(60, 55, -1)])
        self.assertEqual(sentences(result["earlier"]), [f"m{n}" for n in range(55, 5, -1)])
        self.assertEqual(result["omitted"], 5)

    def test_equal_times_put_the_higher_sequence_first(self):
        made = [Moment(2, at(5), "k", "two"), Moment(9, at(5), "k", "nine"),
                Moment(4, at(6), "k", "later"), Moment(3, at(5), "k", "three")]
        result = digest(made, LOOK, NOW)
        self.assertEqual(sentences(result["recent"]), ["later", "nine", "three", "two"])

    def test_the_last_look_is_the_newest_look(self):
        t1, t2 = at(1), at(2)
        events = [Event(1, t1, LOOKED, None, {}), Event(2, at(1, 5), "project.registered", "p", {}),
                  Event(3, t2, LOOKED, None, {})]
        self.assertEqual(last_looked(events), t2)
        self.assertEqual(last_looked([], "x"), "x")
        self.assertIsNone(last_looked([Event(1, t1, "project.registered", "p", {})], None))

    def test_moments_read_the_state_before_each_event(self):
        before = SessionState("s1", "/srv/p00", "/srv/p00", "limit", "deliver", 1, at(0), None)
        sessions = {"s1": before}
        event = Event(2, at(1), "session.seen", "owner/p00",
                      {"session_id": "s1", "cwd": "/srv/p00", "repo": "/srv/p00", "state": "working"})
        found = moments([event], sessions, {})
        self.assertEqual([(m.kind, m.sentence) for m in found],
                         [("resumed", "A session in owner/p00 resumed work.")])
        self.assertEqual(sessions, {"s1": before})

    def test_an_inbox_moment_names_no_issue_and_heads_a_decision_by_its_question(self):
        def asked(text):
            return {"question": text, "options": ["a", "b"], "chosen": None,
                    "recommended": None}

        payload = {"key": "k", "project_id": "owner/p00", "issue": 7, "reason": "decision",
                   "question": foa.SENTENCES["decision"],
                   "questions": [asked("Which database?"), asked("Which port?")],
                   "answered": False}
        events = [Event(1, at(5), "inbox.seen", "owner/p00", payload),
                  Event(2, at(6), "inbox.changed", "owner/p00", {**payload, "answered": True})]
        self.assertEqual([m.sentence for m in moments(events, {}, {})],
                         ["owner/p00 needs you: Which database?",
                          "owner/p00 was answered: Which database?"])

    def test_a_session_moment_names_no_session_and_no_path(self):
        def seen(seq, project, sid, repo, name):
            return Event(seq, at(seq), "session.seen", project,
                         {"session_id": sid, "cwd": repo, "repo": repo, "state": "working",
                          "name": name})

        def stopped(seq, project, sid, repo):
            return Event(seq, at(seq), "session.hook", project,
                         {"event": "StopFailure", "session_id": sid, "cwd": repo, "repo": repo,
                          "error": "rate_limit"})

        events = [
            seen(1, "owner/p00", "aaaaaaaa-1111", "/srv/p00", "deliver"),
            stopped(2, "owner/p00", "aaaaaaaa-1111", "/srv/p00"),
            seen(3, None, "cccccccc-3333", "/srv/elsewhere", "stray-session"),
            stopped(4, None, "cccccccc-3333", "/srv/elsewhere"),
            Event(5, at(5), "session.gone", None, {"session_id": "cccccccc-3333"})]
        said = [m.sentence for m in moments(events, {}, {})]
        self.assertEqual(said, ["A session in owner/p00 stopped on a usage limit.",
                                "A session in elsewhere stopped on a usage limit.",
                                "A session in elsewhere ended."])
        for sentence in said:
            for leaked in ("deliver", "stray-session", "aaaaaaaa", "cccccccc", "/srv"):
                self.assertNotIn(leaked, sentence)

    def test_a_session_named_for_a_sprint_adds_no_moment(self):
        manager = "owner/p00 sprint 0123456789abcdef"

        def seen(seq, sid, state="working", **named):
            return Event(seq, at(seq), "session.seen", "owner/p00" if seq == 1 else None,
                         {"session_id": sid, "cwd": "/srv/p00", "repo": "/srv/p00",
                          "state": state, **named})

        def gone(seq, sid):
            return Event(seq, at(seq), "session.gone", None, {"session_id": sid})

        events = [
            seen(1, "m1", name=manager),
            Event(2, at(2), "session.hook", "owner/p00",
                  {"event": "StopFailure", "session_id": "m1", "cwd": "/srv/p00",
                   "repo": "/srv/p00", "error": "rate_limit"}),
            seen(3, "m1"),
            gone(4, "m1"),
            seen(5, "n1", name="owner/p00 sprint 0123"), gone(6, "n1"),
            seen(7, "w1", name="deliver"), gone(8, "w1"),
            seen(9, "u1"), gone(10, "u1"),
            seen(11, "x1", name=manager + " extra"), gone(12, "x1")]
        found = moments(events, {}, {})
        ended = "A session in p00 ended."
        self.assertEqual([(m.seq, m.kind, m.sentence) for m in found],
                         [(6, "session_ended", ended), (8, "session_ended", ended),
                          (10, "session_ended", ended), (12, "session_ended", ended)])

    def test_keep_drops_moments_at_or_before_the_start(self):
        made = [Moment(1, at(0), "k", "before"), Moment(2, at(1), "k", "at"),
                Moment(3, at(1, 1), "k", "after")]
        self.assertEqual([m.sentence for m in keep(made, at(1))], ["after"])
        self.assertEqual([m.sentence for m in keep(made, "2026-11-11T12:01:00.000000+02:00")], ["after"])

    def test_a_withdrawal_is_a_digest_moment(self):
        goal = {"sprint_id": "a" * 16, "goal": "make the importer resumable"}
        found = moments([
            Event(1, at(1), GOAL_STATED, "owner/p00", goal),
            Event(2, at(2), GOAL_WITHDRAWN, "owner/p00", goal),
            Event(3, at(3), GOAL_WITHDRAWN, "owner/p00", {"sprint_id": "b" * 16}),
            Event(4, at(4), GOAL_WITHDRAWN, None, {"sprint_id": "c" * 16, "goal": "g"})], {}, {})
        self.assertEqual(found, [Moment(2, at(2), SPRINT_WITHDRAWN,
                                        "The goal for owner/p00 was withdrawn: make the importer resumable")])

    def test_a_brief_arriving_and_approved_are_moments(self):
        sid, goal = "a" * 16, "make the importer resumable"
        row = {"sprint_id": sid, "goal": goal}
        found = moments([
            Event(1, at(1), GOAL_STATED, "owner/p00", row),
            Event(2, at(2), BRIEF_SENT, "owner/p00", {**row, "version": 1, "brief": {}}),
            Event(3, at(3), BRIEF_REPLIED, "owner/p00", {**row, "version": 1, "reply": "smaller"}),
            Event(4, at(4), BRIEF_SENT, "owner/p00", {**row, "version": 2, "brief": {}}),
            Event(5, at(5), BRIEF_APPROVED, "owner/p00", {**row, "version": 2}),
            Event(6, at(6), BRIEF_SENT, "owner/p00", {**row, "version": True, "brief": {}}),
            Event(7, at(7), BRIEF_SENT, "owner/p00", {"sprint_id": sid, "version": 3}),
            Event(8, at(8), BRIEF_SENT, None, {**row, "version": 3, "brief": {}})], {}, {})
        self.assertEqual(found, [
            Moment(2, at(2), BRIEF_SENT_MOMENT,
                   "A brief for owner/p00 arrived, version 1: make the importer resumable"),
            Moment(4, at(4), BRIEF_SENT_MOMENT,
                   "A brief for owner/p00 arrived, version 2: make the importer resumable"),
            Moment(5, at(5), BRIEF_APPROVED_MOMENT,
                   "The brief for owner/p00 was approved, version 2: make the importer resumable")])

    def test_a_wake_that_ran_and_a_takeover_that_started_each_say_one_sentence(self):
        sid = "a" * 16
        rows = [
            Event(1, at(1), GOAL_STATED, "owner/p00", {"sprint_id": sid, "goal": "g"}),
            Event(2, at(2), MANAGER_STARTED, "owner/p00", {
                "sprint_id": sid, "profile": "work", "session_name": "n"}),
            Event(3, at(3), MANAGER_WOKEN, "owner/p00", {
                "sprint_id": sid, "ok": True, "goal": "g", "session_id": "s-1"}),
            Event(4, at(4), MANAGER_STARTED, "owner/p00", {
                "sprint_id": sid, "takeover": True, "goal": "g", "profile": "work",
                "session_name": "n"})]
        self.assertEqual([(m.kind, m.sentence) for m in moments(rows, {}, {})][-2:], [
            ("manager_restarted", "The manager of g was restarted"),
            ("manager_takeover", "A new manager took over g")])

    def test_failed_bring_backs_and_a_stall_say_nothing(self):
        sid = "a" * 16
        rows = [
            Event(1, at(1), GOAL_STATED, "owner/p00", {"sprint_id": sid, "goal": "g"}),
            Event(2, at(2), MANAGER_STARTED, "owner/p00", {
                "sprint_id": sid, "profile": "work", "session_name": "n", "goal": "g"})]
        self.assertEqual(moments(rows, {}, {}), [])
        rows += [
            Event(3, at(3), MANAGER_WOKEN, "owner/p00", {
                "sprint_id": sid, "ok": False, "goal": "g", "session_id": "s-1",
                "reason": "r"}),
            Event(4, at(4), MANAGER_FAILED, "owner/p00", {
                "sprint_id": sid, "takeover": True, "goal": "g", "reason": "r"}),
            Event(5, at(5), MANAGER_STALLED, "owner/p00", {
                "sprint_id": sid, "goal": "g", "reason": "r"})]
        self.assertEqual(moments(rows, {}, {}), [])

    def test_a_sprint_state_sentence_only_when_the_reported_state_changes(self):
        sid, goal = "a" * 16, "make the importer resumable"
        row = {"sprint_id": sid, "goal": goal}
        report = {"status": "two slices are building", "phase": "running",
                  "milestone": "Importer resumes",
                  "tracker_url": "https://github.com/owner/p00/milestone/3",
                  "issues": [{"issue": 12, "stage": "building"}], "inbox": [12],
                  "next": "start the resume slice"}

        def reported(seq, phase, sprint_id=sid):
            return Event(seq, at(seq), SPRINT_REPORTED, "owner/p00", {
                "sprint_id": sprint_id, "goal": goal, "report": {**report, "phase": phase}})

        rows = [
            Event(1, at(1), GOAL_STATED, "owner/p00", row),
            Event(2, at(2), BRIEF_SENT, "owner/p00", {
                **row, "version": 1,
                "brief": {"done": "d", "excluded": ["x"], "slices": ["a"], "risks": ["r"],
                          "asks": ["q"]}}),
            Event(3, at(3), BRIEF_APPROVED, "owner/p00", {**row, "version": 1}),
            reported(4, "running"), reported(5, "running"), reported(6, "closing"),
            reported(7, "closing"), reported(8, "done"), reported(9, "paused"),
            reported(10, "running", "b" * 16)]

        def said(found):
            return [m for m in found if m.kind == SPRINT_STATE_MOMENT]

        def moment(seq, text):
            return Moment(seq, at(seq), "sprint_state",
                          f"The sprint for owner/p00 is now {text}: {goal}")

        self.assertEqual(said(moments(rows, {}, {})), [
            moment(4, "on track"), moment(6, "closing"), moment(8, "done")])
        self.assertEqual(said(moments(rows[4:], {}, {}, sprints=sprint_states(rows[:4]))), [
            moment(6, "closing"), moment(8, "done")])

    def test_a_closing_report_is_a_moment_with_its_first_line(self):
        goal = "make the importer resumable"
        brief = {"done": "d", "excluded": ["x"], "slices": ["a"], "risks": ["r"], "asks": ["q"]}
        report = {"status": "one slice is building", "phase": "running",
                  "milestone": "Importer resumes",
                  "tracker_url": "https://github.com/owner/p00/milestone/3",
                  "issues": [{"issue": 12, "stage": "building"}], "inbox": [],
                  "next": "start the resume slice"}

        def closing(seq, sid, issue, summary):
            return Event(seq, at(seq), SPRINT_CLOSED, "owner/p00", {
                "sprint_id": sid, "goal": goal, "closing": {
                    "summary": summary, "issues": [{"issue": issue, "stage": "landed"}],
                    "differently": "cut smaller slices"}})

        def opened(seq, sid):
            row = {"sprint_id": sid, "goal": goal}
            return [Event(seq, at(seq), GOAL_STATED, "owner/p00", row),
                    Event(seq + 1, at(seq + 1), BRIEF_SENT, "owner/p00",
                          {**row, "version": 1, "brief": brief}),
                    Event(seq + 2, at(seq + 2), BRIEF_APPROVED, "owner/p00",
                          {**row, "version": 1}),
                    Event(seq + 3, at(seq + 3), SPRINT_REPORTED, "owner/p00",
                          {**row, "report": report})]

        a, b, c = "a" * 16, "b" * 16, "c" * 16
        rows = (opened(1, a) + opened(5, b) + opened(9, c) + [
            closing(13, a, 12, "Importer resumes after a crash\nmore"),
            closing(14, a, 12, "Second closing"),
            closing(15, c, 13, "Does not cover the reported issue"),
            Event(16, at(16), SPRINT_STOP_REQUESTED, "owner/p00", {"sprint_id": b, "goal": goal}),
            closing(17, b, 12, "Stopped early")])
        found = [m for m in moments(rows, {}, {}) if m.kind == SPRINT_DONE_MOMENT]
        self.assertEqual(found, [Moment(
            13, at(13), SPRINT_DONE_MOMENT,
            "The sprint for owner/p00 is done: Importer resumes after a crash")])

    def test_a_sprint_sentence_follows_the_shown_state_not_the_phase(self):
        sid, goal = "a" * 16, "make the importer resumable"
        row = {"sprint_id": sid, "goal": goal}
        report = {"status": "one slice is building", "phase": "running",
                  "milestone": "Importer resumes",
                  "tracker_url": "https://github.com/owner/p00/milestone/3",
                  "issues": [{"issue": 12, "stage": "building"}], "inbox": [],
                  "next": "start the resume slice"}

        def reported(seq, phase):
            return Event(seq, at(seq), SPRINT_REPORTED, "owner/p00", {
                "sprint_id": sid, "goal": goal, "report": {**report, "phase": phase}})

        rows = [
            Event(1, at(1), GOAL_STATED, "owner/p00", row),
            Event(2, at(2), BRIEF_SENT, "owner/p00", {
                **row, "version": 1,
                "brief": {"done": "d", "excluded": ["x"], "slices": ["a"], "risks": ["r"],
                          "asks": ["q"]}}),
            Event(3, at(3), BRIEF_APPROVED, "owner/p00", {**row, "version": 1}),
            reported(4, "running"), reported(5, "closing"), reported(6, "running"),
            reported(7, "done")]
        open_item = InboxRecord(
            {"project_id": "owner/p00", "issue": 12, "key": "k", "answered": False},
            at(0), at(0))
        waiting = {("owner/p00", "k"): open_item}
        found = [(m.seq, m.sentence) for m in moments(rows, {}, waiting)
                 if m.kind == SPRINT_STATE_MOMENT]
        self.assertEqual(found, [
            (4, f"The sprint for owner/p00 is now waiting on you (1): {goal}"),
            (7, f"The sprint for owner/p00 is now done: {goal}")])


if __name__ == "__main__":
    unittest.main()
