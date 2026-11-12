"""The console's sprints (#886): goal and withdraw bodies, the goal rules, the fold, the age, the secret.

Run: just agent-workflow-tests
"""

import json
import stat
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from agent_tools.console import sprints
from agent_tools.console.deliveries import DELIVERY_GONE, DELIVERY_SEEN, IssueStage
from agent_tools.console.event_log import (BRIEF_APPROVED, BRIEF_REPLIED, BRIEF_SENT, GOAL_STATED,
                                           GOAL_WITHDRAWN, SPRINT_REPORTED, Event)
from agent_tools.console.sprints import Observed, Report


class ParseTest(unittest.TestCase):
    def test_a_goal_body_is_a_project_and_a_text(self):
        self.assertEqual(
            sprints.parse_goal(b'{"project_id": "owner/p00", "goal": "make the importer resumable"}'),
            ("owner/p00", "make the importer resumable"))
        self.assertEqual(sprints.parse_goal(b'{"project_id": "owner/p00", "goal": ""}'),
                         ("owner/p00", ""))
        for body in (b"not json", b"[1]", b'{"project_id": "owner/p00"}',
                     b'{"project_id": "owner/p00", "goal": "g", "x": 1}',
                     b'{"project_id": "", "goal": "g"}',
                     b'{"project_id": 1, "goal": "g"}',
                     b'{"project_id": "owner/p00", "goal": null}',
                     b'{"project_id": "owner/p00", "goal": NaN}',
                     b'{"project_id": "a", "project_id": "b", "goal": "g"}',
                     b"\xff", b"[" * 100000):
            with self.subTest(body=body[:40]):
                with self.assertRaises(ValueError):
                    sprints.parse_goal(body)

    def test_a_withdraw_body_names_one_sprint_id(self):
        self.assertEqual(
            sprints.parse_withdraw(
                b'{"project_id": "owner/p00", "sprint_id": "0123456789abcdef"}'),
            ("owner/p00", "0123456789abcdef"))
        for sprint_id in ("../../etc/passwd", "0123456789ABCDEF", "0123456789abcde",
                          "0123456789abcdef0", "0123456789abcdef\n", 1):
            with self.subTest(sprint_id=sprint_id):
                body = json.dumps({"project_id": "owner/p00", "sprint_id": sprint_id}).encode()
                with self.assertRaises(ValueError):
                    sprints.parse_withdraw(body)
        for body in (b'{"project_id": "owner/p00", "sprint_id": "0123456789abcdef", "x": 1}',
                     b'{"project_id": "owner/p00"}'):
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    sprints.parse_withdraw(body)


SID = "0123456789abcdef"


class ParseBriefTest(unittest.TestCase):
    def test_a_brief_request_is_a_sprint_a_secret_and_parts(self):
        body = json.dumps({"sprint_id": SID, "secret": "s3cret",
                           "brief": {"done": "x", "slices": ["a"]}}).encode()
        self.assertEqual(sprints.parse_brief_request(body),
                         (SID, "s3cret", {"done": "x", "slices": ["a"]}))
        good = {"sprint_id": SID, "secret": "s", "brief": {}}
        self.assertEqual(sprints.parse_brief_request(json.dumps(good).encode()), (SID, "s", {}))
        bad = [b"not json", b"[1]",
               json.dumps({**good, "extra": 1}).encode(),
               json.dumps({"sprint_id": SID, "brief": {}}).encode(),
               json.dumps({**good, "sprint_id": "../x"}).encode(),
               json.dumps({**good, "secret": 1}).encode(),
               json.dumps({**good, "brief": []}).encode(),
               json.dumps({**good, "brief": {"scope": "x"}}).encode(),
               ('{"sprint_id": "%s", "sprint_id": "%s", "secret": "s", "brief": {}}'
                % (SID, SID)).encode(),
               ('{"sprint_id": "%s", "secret": "s", "brief": {"done": NaN}}' % SID).encode()]
        for body in bad:
            with self.subTest(body=body[:50]):
                with self.assertRaises(ValueError):
                    sprints.parse_brief_request(body)

    def test_approve_and_reply_bodies(self):
        self.assertEqual(
            sprints.parse_approve(
                json.dumps({"project_id": "owner/p00", "sprint_id": SID, "version": 2}).encode()),
            ("owner/p00", SID, 2))
        self.assertEqual(
            sprints.parse_reply(json.dumps({"project_id": "owner/p00", "sprint_id": SID,
                                            "version": 1, "reply": "drop it"}).encode()),
            ("owner/p00", SID, 1, "drop it"))
        approve = {"project_id": "owner/p00", "sprint_id": SID, "version": 1}
        reply = {**approve, "reply": "r"}
        cases = [(sprints.parse_approve, {**approve, "version": True}),
                 (sprints.parse_approve, {**approve, "version": 0}),
                 (sprints.parse_approve, {**approve, "version": "1"}),
                 (sprints.parse_approve, {"project_id": "owner/p00", "sprint_id": SID}),
                 (sprints.parse_approve, {**approve, "extra": 1}),
                 (sprints.parse_approve, {**approve, "project_id": ""}),
                 (sprints.parse_reply, {**reply, "version": True}),
                 (sprints.parse_reply, {**reply, "version": 0}),
                 (sprints.parse_reply, {**reply, "version": "1"}),
                 (sprints.parse_reply, approve),
                 (sprints.parse_reply, {**reply, "extra": 1}),
                 (sprints.parse_reply, {**reply, "project_id": ""}),
                 (sprints.parse_reply, {**reply, "reply": None})]
        for parse, value in cases:
            with self.subTest(parse=parse.__name__, value=value):
                with self.assertRaises(ValueError):
                    parse(json.dumps(value).encode())


FULL = {"done": " ship it ", "excluded": ["x"], "slices": ["a", "b"], "risks": ["r"],
        "asks": ["q"]}


class CheckedBriefTest(unittest.TestCase):
    def test_the_first_missing_part_is_named(self):
        def without(*names):
            return {k: v for k, v in FULL.items() if k not in names}

        cases = [(without("done"), "done"), ({**FULL, "done": "  "}, "done"),
                 (without("excluded"), "excluded"), ({**FULL, "slices": []}, "slices"),
                 ({**FULL, "risks": [" "]}, "risks"), ({**FULL, "asks": "q"}, "asks"),
                 ({**FULL, "asks": [1]}, "asks"), (without("risks", "asks"), "risks")]
        for brief, part in cases:
            with self.subTest(part=part, brief=brief):
                with self.assertRaises(sprints.Refused) as caught:
                    sprints.checked_brief(brief)
                self.assertEqual(str(caught.exception), f"the brief has no {part}")
        self.assertEqual(sprints.checked_brief(FULL), {**FULL, "done": "ship it"})
        self.assertEqual(sprints.checked_brief({**FULL, "slices": [" a "]})["slices"], ["a"])

    def test_excluded_risks_and_asks_may_be_empty(self):
        self.assertEqual(sprints.MAY_BE_EMPTY, ("excluded", "risks", "asks"))
        for part in ("excluded", "risks", "asks"):
            with self.subTest(part=part):
                self.assertEqual(sprints.checked_brief({**FULL, part: []}),
                                 {**FULL, "done": "ship it", part: []})
        self.assertEqual(
            sprints.checked_brief({**FULL, "excluded": [], "risks": [], "asks": []}),
            {**FULL, "done": "ship it", "excluded": [], "risks": [], "asks": []})

    def test_an_empty_done_or_slices_or_a_wrong_type_is_still_refused(self):
        cases = [({**FULL, "slices": []}, "slices"), ({**FULL, "done": ""}, "done"),
                 ({**FULL, "excluded": None}, "excluded"), ({**FULL, "risks": "r"}, "risks"),
                 ({**FULL, "asks": {}}, "asks"), ({**FULL, "asks": [""]}, "asks"),
                 ({**FULL, "excluded": [" "]}, "excluded"),
                 ({k: v for k, v in FULL.items() if k != "asks"}, "asks"),
                 ({**FULL, "excluded": [], "slices": []}, "slices")]
        for brief, part in cases:
            with self.subTest(part=part, brief=brief):
                with self.assertRaises(sprints.Refused) as caught:
                    sprints.checked_brief(brief)
                self.assertEqual(str(caught.exception), f"the brief has no {part}")

    def test_a_reply_is_kept_exactly(self):
        text = "Drop slice 2.\nKeep the rest. "
        self.assertEqual(sprints.checked_reply(text), text)
        self.assertEqual(sprints.checked_reply("\u00e9" * 2000), "\u00e9" * 2000)
        with self.assertRaises(sprints.Refused) as caught:
            sprints.checked_reply(" \n")
        self.assertEqual(str(caught.exception), "write the reply first")
        with self.assertRaises(sprints.Refused) as caught:
            sprints.checked_reply("x" * 2001)
        self.assertEqual(str(caught.exception), "a reply is at most 2000 characters")


class GoalRuleTest(unittest.TestCase):
    def test_the_goal_rules(self):
        self.assertEqual(sprints.checked_goal("  make it  \n"), "make it")
        self.assertEqual(sprints.checked_goal("x" * 2000), "x" * 2000)
        self.assertEqual(sprints.checked_goal(" " + "x" * 2000 + " "), "x" * 2000)
        for text in ("é" * 2000, "\U0001F600" * 2000):
            self.assertEqual(sprints.checked_goal(text), text)
        for text in ("", " \n\t "):
            with self.subTest(text=text):
                with self.assertRaises(sprints.Refused) as caught:
                    sprints.checked_goal(text)
                self.assertEqual(str(caught.exception), "write the goal first")
        with self.assertRaises(sprints.Refused) as caught:
            sprints.checked_goal("x" * 2001)
        self.assertEqual(str(caught.exception), "a goal is at most 2000 characters")


def at(seq):
    return f"2026-11-12T10:0{seq}:00.000000+00:00"


def stated(seq, project, sprint_id, goal):
    return Event(seq, at(seq), GOAL_STATED, project, {"sprint_id": sprint_id, "goal": goal})


def withdrawn(seq, project, sprint_id, goal):
    return Event(seq, at(seq), GOAL_WITHDRAWN, project, {"sprint_id": sprint_id, "goal": goal})


class FoldTest(unittest.TestCase):
    def test_a_stated_goal_is_a_sprint_until_withdrawn(self):
        events = [stated(1, "owner/p00", "aaaaaaaaaaaaaaaa", "one"),
                  stated(2, "owner/p01", "bbbbbbbbbbbbbbbb", "two"),
                  withdrawn(3, "owner/p01", "bbbbbbbbbbbbbbbb", "two")]
        expected = {"aaaaaaaaaaaaaaaa":
                    sprints.SprintState("aaaaaaaaaaaaaaaa", "owner/p00", "one", 1, at(1))}
        self.assertEqual(sprints.sprint_states(events), expected)
        first = sprints.sprint_states(events[:2])
        self.assertEqual(sprints.sprint_states(events[2:], first), expected)

    def test_malformed_goal_rows_and_other_kinds_change_nothing(self):
        events = [
            stated(1, "owner/p00", "aaaaaaaaaaaaaaaa", "one"),
            Event(2, at(2), GOAL_STATED, None, {"sprint_id": "bbbbbbbbbbbbbbbb", "goal": "x"}),
            Event(3, at(3), GOAL_STATED, "owner/p00", {"goal": "x"}),
            Event(4, at(4), GOAL_STATED, "owner/p00", {"sprint_id": "cccccccccccccccc", "goal": 5}),
            Event(5, at(5), GOAL_WITHDRAWN, "owner/p00", {"sprint_id": 5, "goal": "x"}),
            Event(6, at(6), "project.unregistered", "owner/p00", {}),
        ]
        self.assertEqual(
            sprints.sprint_states(events),
            {"aaaaaaaaaaaaaaaa":
             sprints.SprintState("aaaaaaaaaaaaaaaa", "owner/p00", "one", 1, at(1))})


PARTS = {"done": "d", "excluded": ["x"], "slices": ["a"], "risks": ["r"], "asks": ["q"]}


def sent(seq, sprint_id, version, parts):
    return Event(seq, at(seq), BRIEF_SENT, "owner/p00",
                 {"sprint_id": sprint_id, "version": version, "goal": "one", "brief": parts})


def approved(seq, sprint_id, version):
    return Event(seq, at(seq), BRIEF_APPROVED, "owner/p00",
                 {"sprint_id": sprint_id, "version": version, "goal": "one"})


def replied(seq, sprint_id, version, text):
    return Event(seq, at(seq), BRIEF_REPLIED, "owner/p00",
                 {"sprint_id": sprint_id, "version": version, "goal": "one", "reply": text})


class BriefFoldTest(unittest.TestCase):
    def test_a_brief_waits_then_is_approved(self):
        goal = stated(1, "owner/p00", SID, "one")
        state = sprints.sprint_states([goal, sent(2, SID, 1, PARTS)])[SID]
        self.assertEqual(state.brief, sprints.Brief(1, PARTS, at(2), "none", None))
        self.assertEqual(state.state, "drafting")
        state = sprints.sprint_states([goal, sent(2, SID, 1, PARTS), approved(3, SID, 1)])[SID]
        self.assertEqual(state.brief, sprints.Brief(1, PARTS, at(2), "approved", None, at(3)))
        self.assertEqual(state.state, "starting")
        self.assertIsNone(sprints.sprint_states([goal])[SID].brief)
        self.assertEqual(sprints.sprint_states([goal])[SID].state, "drafting")

    def test_a_newer_brief_replaces_and_stale_decisions_change_nothing(self):
        goal = stated(1, "owner/p00", SID, "one")
        two = {**PARTS, "done": "d2"}

        def brief(events):
            return sprints.sprint_states([goal, *events])[SID].brief

        first = [sent(2, SID, 1, PARTS), replied(3, SID, 1, "no")]
        self.assertEqual(brief(first), sprints.Brief(1, PARTS, at(2), "changes", "no", at(3)))
        second = [*first, sent(4, SID, 2, two)]
        self.assertEqual(brief(second), sprints.Brief(2, two, at(4), "none", None))
        self.assertEqual(brief([*second, approved(5, SID, 1)]), brief(second))
        self.assertEqual(brief([*second, sent(5, SID, 2, PARTS)]), brief(second))
        decided = [*second, approved(5, SID, 2)]
        self.assertEqual(brief(decided), sprints.Brief(2, two, at(4), "approved", None, at(5)))
        self.assertEqual(brief([*decided, replied(6, SID, 2, "late")]), brief(decided))
        self.assertEqual(brief([*decided, approved(6, SID, 2)]), brief(decided))

    def test_malformed_brief_rows_change_nothing(self):
        base = [stated(1, "owner/p00", SID, "one"), sent(2, SID, 1, PARTS)]
        other = "fedcba9876543210"
        bad = [sent(3, other, 1, PARTS), sent(4, SID, True, PARTS), sent(5, SID, "1", PARTS),
               sent(6, SID, 2, []),
               Event(7, at(7), BRIEF_REPLIED, "owner/p00", {"sprint_id": SID, "version": 1}),
               Event(8, at(8), BRIEF_REPLIED, "owner/p00",
                     {"sprint_id": SID, "version": 1, "reply": 5}),
               approved(9, SID, True), approved(10, other, 1)]
        self.assertEqual(sprints.sprint_states(base + bad), sprints.sprint_states(base))

    def test_a_withdrawn_sprint_takes_no_brief(self):
        events = [stated(1, "owner/p00", SID, "one"), withdrawn(2, "owner/p00", SID, "one"),
                  sent(3, SID, 1, PARTS)]
        self.assertEqual(sprints.sprint_states(events), {})

    def test_folding_in_two_parts_equals_folding_at_once(self):
        events = [stated(1, "owner/p00", SID, "one"), sent(2, SID, 1, PARTS),
                  replied(3, SID, 1, "no"), sent(4, SID, 2, PARTS), approved(5, SID, 2),
                  stated(6, "owner/p01", "fedcba9876543210", "two"),
                  withdrawn(7, "owner/p01", "fedcba9876543210", "two")]
        whole = sprints.sprint_states(events)
        for cut in range(len(events) + 1):
            with self.subTest(cut=cut):
                self.assertEqual(
                    sprints.sprint_states(events[cut:], sprints.sprint_states(events[:cut])),
                    whole)


URL = "https://github.com/owner/p00/milestone/3"
REPORT = {"status": "two slices are building", "phase": "running", "milestone": "Importer resumes",
          "tracker_url": URL,
          "issues": [{"issue": 12, "stage": "building"}, {"issue": 13, "stage": "landed"}],
          "inbox": [12], "next": "start the resume slice"}


def reported(seq, sprint_id, report):
    return Event(seq, at(seq), SPRINT_REPORTED, "o/a",
                 {"sprint_id": sprint_id, "goal": "g", "report": report})


class ReportParseTest(unittest.TestCase):
    def test_a_report_request_is_a_sprint_a_secret_and_a_report(self):
        body = json.dumps({"sprint_id": SID, "secret": "s", "report": REPORT}).encode()
        self.assertEqual(sprints.parse_report_request(body), (SID, "s", REPORT))

        def bodies(**changes):
            return json.dumps({"sprint_id": SID, "secret": "s", "report": REPORT,
                               **changes}).encode()

        for bad in (bodies(extra=1),
                    json.dumps({"sprint_id": SID, "secret": "s"}).encode(),
                    bodies(sprint_id="ABC"), bodies(secret=5), bodies(report=[]),
                    bodies(report={**REPORT, "colour": "red"}),
                    b'{"sprint_id": "' + SID.encode() + b'", "secret": "a", "secret": "b", '
                    b'"report": {}}',
                    b'{"sprint_id": "' + SID.encode() + b'", "secret": "s", "report": NaN}'):
            with self.subTest(body=bad[:60]):
                with self.assertRaises(ValueError):
                    sprints.parse_report_request(bad)

    def test_the_first_invalid_member_is_named(self):
        for member in sprints.REPORT_MEMBERS:
            with self.subTest(missing=member):
                report = {k: v for k, v in REPORT.items() if k != member}
                with self.assertRaises(sprints.Refused) as caught:
                    sprints.checked_report(report)
                self.assertEqual(str(caught.exception), f"the report has no valid {member}")
        many = [{"issue": n, "stage": "queued"} for n in range(1, 202)]
        table = (("status", ""), ("status", "   "), ("status", "a\nb"), ("status", "x" * 501),
                 ("status", 5), ("phase", "paused"), ("milestone", ""),
                 ("tracker_url", "http://h/m"), ("tracker_url", "https://h/a b"),
                 ("tracker_url", ""), ("issues", {}),
                 ("issues", [{"issue": 0, "stage": "queued"}]),
                 ("issues", [{"issue": True, "stage": "queued"}]),
                 ("issues", [{"issue": 1, "stage": "stuck"}]),
                 ("issues", [{"issue": 1, "stage": "queued", "x": 1}]),
                 ("issues", [{"issue": 1, "stage": "queued"}, {"issue": 1, "stage": "held"}]),
                 ("issues", many), ("inbox", [0]), ("inbox", [True]), ("inbox", "1"),
                 ("inbox", list(range(1, 202))), ("next", ""))
        for member, value in table:
            with self.subTest(member=member, value=str(value)[:30]):
                with self.assertRaises(sprints.Refused) as caught:
                    sprints.checked_report({**REPORT, member: value})
                self.assertEqual(str(caught.exception), f"the report has no valid {member}")
        with self.assertRaises(sprints.Refused) as caught:
            sprints.checked_report({**REPORT, "phase": "paused", "next": ""})
        self.assertEqual(str(caught.exception), "the report has no valid phase")

    def test_a_status_naming_an_issue_number_is_refused(self):
        for status in ("#12 is building", "building #3"):
            with self.subTest(status=status):
                with self.assertRaises(sprints.Refused) as caught:
                    sprints.checked_report({**REPORT, "status": status})
                self.assertEqual(str(caught.exception), sprints.STATUS_NUMBER)
        for status in ("building 12 of 20", "the C# port"):
            with self.subTest(status=status):
                self.assertEqual(sprints.checked_report({**REPORT, "status": status})["status"],
                                 status)
        with self.assertRaises(sprints.Refused) as caught:
            sprints.checked_report({**REPORT, "status": "#1", "phase": "paused"})
        self.assertEqual(str(caught.exception), sprints.STATUS_NUMBER)

    def test_a_checked_report_is_stripped_and_sorted(self):
        report = {**REPORT, "status": " a ", "milestone": " m ", "next": " n ",
                  "issues": [{"issue": 5, "stage": "queued"}, {"issue": 2, "stage": "held"}],
                  "inbox": [4, 1, 4]}
        self.assertEqual(
            sprints.checked_report(report),
            {"status": "a", "phase": "running", "milestone": "m", "tracker_url": URL,
             "issues": [{"issue": 2, "stage": "held"}, {"issue": 5, "stage": "queued"}],
             "inbox": [1, 4], "next": "n"})


def ms(seq):
    return int(datetime.fromisoformat(at(seq)).timestamp() * 1000)


def seen(seq, run_id, moved_ms, issues, project="owner/p00", session_id="s1"):
    return Event(seq, at(seq), DELIVERY_SEEN, project,
                 {"session_id": session_id, "run_id": run_id, "moved_ms": moved_ms,
                  "issues": [{"issue": n, "stage": s, "task": None, "tasks": None}
                             for n, s in issues]})


def gone(seq, run_id):
    return Event(seq, at(seq), DELIVERY_GONE, "owner/p00", {"session_id": "s1", "run_id": run_id})


BASE = [stated(1, "owner/p00", SID, "one"), sent(2, SID, 1, PARTS), approved(3, SID, 1),
        reported(4, SID, REPORT)]
OBSERVED_ROWS = BASE + [seen(5, "wf_a", ms(4) + 60_000, ((12, "final review"), (99, "queued"))),
                        gone(6, "wf_a"),
                        seen(7, "wf_b", ms(4) + 30_000, ((12, "building"),)),
                        seen(8, "wf_a", ms(4) + 90_000, ((12, "done"),)),
                        reported(9, SID, REPORT)]


class ReportFoldTest(unittest.TestCase):
    def test_a_report_applies_only_to_an_approved_sprint(self):
        rows = [stated(1, "owner/p00", SID, "one"), reported(2, SID, REPORT)]
        self.assertIsNone(sprints.sprint_states(rows)[SID].report)
        rows += [sent(3, SID, 1, PARTS), reported(4, SID, REPORT)]
        self.assertIsNone(sprints.sprint_states(rows)[SID].report)
        rows += [approved(5, SID, 1), reported(6, SID, REPORT)]
        expected = Report(at(6), "two slices are building", "running", "Importer resumes", URL,
                          ((12, "building"), (13, "landed")), (12,), "start the resume slice")
        self.assertEqual(sprints.sprint_states(rows)[SID].report, expected)
        other = "fedcba9876543210"
        rows += [reported(7, other, REPORT), withdrawn(8, "owner/p00", other, "x"),
                 reported(9, other, REPORT)]
        folded = sprints.sprint_states(rows)
        self.assertEqual(set(folded), {SID})
        for bad in ({k: v for k, v in REPORT.items() if k != "next"}, [REPORT]):
            with self.subTest(bad=str(bad)[:30]):
                self.assertEqual(
                    sprints.sprint_states([reported(7, SID, bad)], folded)[SID].report, expected)

    def test_a_later_report_replaces_the_earlier(self):
        rows = BASE[:3] + [reported(4, SID, REPORT), reported(5, SID, {**REPORT, "phase": "closing"})]
        report = sprints.sprint_states(rows)[SID].report
        self.assertEqual((report.at, report.phase), (at(5), "closing"))

    def test_a_decision_records_its_time(self):
        goal = stated(1, "owner/p00", SID, "one")
        self.assertIsNone(sprints.sprint_states([goal, sent(2, SID, 1, PARTS)])[SID].brief.decided_at)
        decided = sprints.sprint_states([goal, sent(2, SID, 1, PARTS), approved(5, SID, 1)])
        self.assertEqual(decided[SID].brief.decided_at, at(5))
        replied_state = sprints.sprint_states([goal, sent(2, SID, 1, PARTS),
                                               replied(4, SID, 1, "no")])
        self.assertEqual(replied_state[SID].brief.decided_at, at(4))

    def test_report_folding_in_two_parts_equals_folding_at_once(self):
        for rows in (BASE[:3] + [reported(4, SID, REPORT)], OBSERVED_ROWS):
            whole = sprints.sprint_states(rows)
            for cut in range(len(rows) + 1):
                with self.subTest(rows=len(rows), cut=cut):
                    self.assertEqual(
                        sprints.sprint_states(rows[cut:], sprints.sprint_states(rows[:cut])),
                        whole)


class ObservedFoldTest(unittest.TestCase):
    def test_a_run_seen_after_the_report_is_kept_until_the_next_report(self):
        def fold(count):
            state = sprints.sprint_states(OBSERVED_ROWS[:count])[SID]
            return state.observed, state.moved_ms

        self.assertEqual(fold(4), ((), None))
        first = Observed(12, ms(4) + 60_000, "s1", "wf_a", IssueStage(12, "final review"))
        self.assertEqual(fold(5), ((first,), ms(4) + 60_000))
        self.assertEqual(fold(6), ((first,), ms(4) + 60_000))
        self.assertEqual(fold(7), ((first,), ms(4) + 60_000))
        observed, moved = fold(8)
        self.assertEqual(observed[0].stage, IssueStage(12, "done"))
        self.assertEqual((len(observed), moved), (1, ms(4) + 90_000))
        self.assertEqual(fold(9), ((), None))
        tied = sprints.sprint_states(BASE + [seen(5, "wf_a", ms(4) + 60_000, ((12, "building"),)),
                                             seen(6, "wf_a", ms(4) + 60_000, ((12, "verifying"),))])
        self.assertEqual(tied[SID].observed[0].stage, IssueStage(12, "verifying"))

    def test_only_runs_of_the_sprints_project_that_moved_after_the_report_count(self):
        late = {**seen(5, "wf_a", ms(4) + 60_000, ((12, "building"),)).payload}
        malformed = Event(5, at(5), DELIVERY_SEEN, "owner/p00", {**late, "moved_ms": "x"})
        for row in (seen(5, "wf_a", ms(4) + 60_000, ((12, "building"),), project="owner/p01"),
                    seen(5, "wf_a", ms(4), ((12, "building"),)),
                    seen(5, "wf_a", ms(4) + 60_000, ((99, "building"),)), malformed):
            with self.subTest(row=row.payload):
                state = sprints.sprint_states(BASE + [row])[SID]
                self.assertEqual((state.observed, state.moved_ms), ((), None))
        early = BASE[:3] + [seen(4, "wf_a", ms(3) + 1, ((12, "building"),)), reported(5, SID, REPORT)]
        state = sprints.sprint_states(early)[SID]
        self.assertEqual((state.observed, state.moved_ms), ((), None))


class WithdrawnTest(unittest.TestCase):
    def test_withdrawn_ids(self):
        a, b = "aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"
        events = [stated(1, "owner/p00", a, "one"), stated(2, "owner/p00", b, "two"),
                  withdrawn(3, "owner/p00", a, "one"),
                  Event(4, at(4), GOAL_WITHDRAWN, "owner/p00", {"sprint_id": 5})]
        self.assertEqual(sprints.withdrawn_ids(events), frozenset({a}))
        self.assertEqual(sprints.withdrawn_ids(events[3:], frozenset({b})), frozenset({b}))
        self.assertEqual(sprints.withdrawn_ids(events[2:], frozenset({b})), frozenset({a, b}))


class AgeTest(unittest.TestCase):
    def test_the_age_wording(self):
        for elapsed, text in ((-5, "stated just now"), (0, "stated just now"),
                              (59_999, "stated just now"), (60_000, "stated 1 min ago"),
                              (3_599_999, "stated 59 min ago"), (3_600_000, "stated 1 h ago"),
                              (86_399_999, "stated 23 h ago"), (86_400_000, "stated 1 day ago"),
                              (172_800_000, "stated 2 days ago")):
            with self.subTest(elapsed=elapsed):
                self.assertEqual(sprints.age_text(elapsed), text)

    def test_the_ago_and_progress_wording(self):
        for elapsed, text in ((-5, "just now"), (0, "just now"), (59_999, "just now"),
                              (60_000, "1 min ago"), (3_599_999, "59 min ago"),
                              (3_600_000, "1 h ago"), (86_400_000, "1 day ago"),
                              (172_800_000, "2 days ago")):
            with self.subTest(elapsed=elapsed):
                self.assertEqual(sprints.ago_text(elapsed), text)
        self.assertEqual(sprints.progress_text(3, 7, 2, 2, 0),
                         "3 of 7 landed, 2 in delivery, 2 queued")
        self.assertEqual(sprints.progress_text(0, 0, 0, 0, 0), "0 of 0 landed")
        self.assertEqual(sprints.progress_text(1, 4, 0, 0, 3), "1 of 4 landed, 3 held")
        self.assertEqual(sprints.QUIET_TEXT.format(minutes=16), "quiet for 16 min \u2014 may be stuck")


class SecretTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name) / "console" / "sprint-secrets"

    def test_a_secret_is_created_once_owner_only(self):
        path = sprints.create_secret(self.directory, "0123456789abcdef")
        self.assertEqual(path, self.directory / "0123456789abcdef")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        content = path.read_text(encoding="utf-8")
        self.assertRegex(content, r"^[A-Za-z0-9_-]{43}\n$")
        with self.assertRaises(FileExistsError):
            sprints.create_secret(self.directory, "0123456789abcdef")
        self.assertEqual(path.read_text(encoding="utf-8"), content)
        other = sprints.create_secret(self.directory, "fedcba9876543210")
        self.assertNotEqual(other.read_text(encoding="utf-8"), content)

    def test_read_secret_returns_the_created_value(self):
        path = sprints.create_secret(self.directory, SID)
        self.assertEqual(sprints.read_secret(self.directory, SID),
                         path.read_text(encoding="utf-8").removesuffix("\n"))
        self.assertIsNone(sprints.read_secret(self.directory, "fedcba9876543210"))
        with self.assertRaises(ValueError):
            sprints.read_secret(self.directory, "../x")

    def test_a_malformed_id_touches_nothing(self):
        with self.assertRaises(ValueError):
            sprints.create_secret(self.directory, "../x")
        with self.assertRaises(ValueError):
            sprints.remove_secret(self.directory, "../x")
        self.assertFalse(self.directory.exists())

    def test_remove_secret_removes_and_tolerates_absence(self):
        path = sprints.create_secret(self.directory, "0123456789abcdef")
        sprints.remove_secret(self.directory, "0123456789abcdef")
        self.assertFalse(path.exists())
        sprints.remove_secret(self.directory, "0123456789abcdef")

    def test_new_sprint_ids_are_sixteen_hex_and_differ(self):
        first, second = sprints.new_sprint_id(), sprints.new_sprint_id()
        for sprint_id in (first, second):
            self.assertIsNotNone(sprints.SPRINT_ID.fullmatch(sprint_id))
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
