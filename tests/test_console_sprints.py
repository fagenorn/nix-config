"""The console's sprints (#886): goal and withdraw bodies, the goal rules, the fold, the age, the secret.

Run: just agent-workflow-tests
"""

import json
import stat
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from agent_tools.console import event_log, manager, sprints
from agent_tools.console.deliveries import DELIVERY_GONE, DELIVERY_SEEN, IssueStage
from agent_tools.console.event_log import (BRIEF_APPROVED, BRIEF_REPLIED, BRIEF_SENT, GOAL_STATED,
                                           GOAL_WITHDRAWN, MANAGER_FAILED, MANAGER_STARTED,
                                           MANAGER_STOP_FAILED, MANAGER_STOPPED,
                                           MANAGER_WAITING, SPRINT_CLOSED,
                                           SPRINT_STOP_REQUESTED, SPRINT_REPORTED, Event)
from agent_tools.console.sprints import Closing, Observed, PendingStop, Report


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

def managed(seq, sprint_id, kind, **payload):
    return Event(seq, at(seq), kind, "p00", {"sprint_id": sprint_id, **payload})


class ManagerFoldTest(unittest.TestCase):
    def test_manager_rows_fold_onto_open_sprints(self):
        goal = stated(1, "p00", SID, "one")
        name = "p00 sprint " + SID

        def folded(*rows):
            return sprints.sprint_states([goal, *rows])[SID].manager

        started = managed(2, SID, MANAGER_STARTED, profile="work", session_name=name)
        self.assertEqual(folded(started), sprints.Manager("started", at(2), "work", name))
        failed = managed(3, SID, MANAGER_FAILED, reason="x")
        self.assertEqual(folded(started, failed), sprints.Manager("failed", at(3), reason="x"))
        waiting = managed(4, SID, MANAGER_WAITING, until="T")
        self.assertEqual(folded(started, failed, waiting),
                         sprints.Manager("waiting", at(4), until="T"))
        open_ended = managed(5, SID, MANAGER_WAITING, until=None)
        self.assertEqual(folded(started, failed, waiting, open_ended),
                         sprints.Manager("waiting", at(5), until=None))
        self.assertIsNone(sprints.sprint_states([goal])[SID].manager)

    def test_malformed_manager_rows_change_nothing(self):
        name = "p00 sprint " + SID
        base = [stated(1, "p00", SID, "one"),
                managed(2, SID, MANAGER_STARTED, profile="work", session_name=name)]
        bad = [managed(3, SID, MANAGER_STARTED, session_name=name),
               managed(4, SID, MANAGER_STARTED, profile="work", session_name=5),
               managed(5, SID, MANAGER_FAILED, reason=3),
               managed(6, SID, MANAGER_WAITING, until=5),
               managed(7, "fedcba9876543210", MANAGER_FAILED, reason="x")]
        self.assertEqual(sprints.sprint_states(base + bad), sprints.sprint_states(base))
        gone = [stated(1, "p00", SID, "one"), withdrawn(2, "p00", SID, "one")]
        late = managed(3, SID, MANAGER_FAILED, reason="x")
        self.assertEqual(sprints.sprint_states(gone + [late]), {})

    def test_folding_manager_rows_in_two_parts_equals_at_once(self):
        events = [stated(1, "p00", SID, "one"),
                  managed(2, SID, MANAGER_STARTED, profile="work", session_name="n"),
                  managed(3, SID, MANAGER_FAILED, reason="x"),
                  managed(4, SID, MANAGER_WAITING, until=None),
                  stated(5, "p00", "fedcba9876543210", "two"),
                  managed(6, "fedcba9876543210", MANAGER_FAILED, reason="y"),
                  withdrawn(7, "p00", "fedcba9876543210", "two")]
        whole = sprints.sprint_states(events)
        for cut in range(len(events) + 1):
            with self.subTest(cut=cut):
                self.assertEqual(
                    sprints.sprint_states(events[cut:], sprints.sprint_states(events[:cut])),
                    whole)

    def test_manager_kinds_are_not_kept(self):
        for kind in (MANAGER_STARTED, MANAGER_FAILED, MANAGER_WAITING):
            with self.subTest(kind=kind):
                self.assertNotIn(kind, event_log.KEPT_KINDS)
        self.assertEqual((MANAGER_STARTED, MANAGER_FAILED, MANAGER_WAITING),
                         ("manager.started", "manager.failed", "manager.waiting"))


class ManagerStatusTest(unittest.TestCase):
    def test_the_manager_status_rule(self):
        t = at(1)
        t_ms = int(datetime.fromisoformat(t).timestamp() * 1000)
        started = sprints.Manager("started", t, "work", "n")
        failed = sprints.Manager("failed", t, reason="the directory is not trusted")
        waiting = sprints.Manager("waiting", t, until="U")
        brief = sprints.Brief(1, PARTS, t, "none", None)
        unavailable = ("unavailable", manager.UNAVAILABLE_TEXT, False)
        missing = ("missing", "the manager is not running", True)
        no_manager = ("none", sprints.NO_MANAGER_TEXT, True)
        later = sprints.Manager("started", at(5), "work", "n")
        later_ms = int(datetime.fromisoformat(at(5)).timestamp() * 1000)
        table = [
            ("started later than the goal, at the limit", later, None, False, later_ms + 120_000,
             True, ("started", None, False)),
            ("started at the limit", started, None, False, t_ms + 120_000, True,
             ("started", None, False)),
            ("started past the limit", started, None, False, t_ms + 120_001, True, missing),
            ("started, listed", started, None, True, t_ms + 600_000, True,
             ("started", None, False)),
            ("started, briefed", started, brief, False, t_ms + 600_000, True,
             ("started", None, False)),
            ("started, no clock", started, None, False, None, True, ("started", None, False)),
            ("failed", failed, None, False, t_ms, True,
             ("failed", "could not start a manager: the directory is not trusted", True)),
            ("waiting", waiting, None, False, t_ms, True,
             ("waiting", "waiting on quota until", True)),
            ("failed, listed", failed, None, True, t_ms, True,
             ("failed", "could not start a manager: the directory is not trusted", False)),
            ("failed, briefed", failed, brief, False, t_ms, True,
             ("failed", "could not start a manager: the directory is not trusted", False)),
            ("waiting, listed", waiting, None, True, t_ms, True,
             ("waiting", "waiting on quota until", False)),
            ("waiting, briefed", waiting, brief, False, t_ms, True,
             ("waiting", "waiting on quota until", False)),
            ("none past the limit", None, None, False, t_ms + 120_001, True, no_manager),
            ("none at the limit", None, None, False, t_ms + 120_000, True, ("none", None, False)),
            ("none, listed", None, None, True, t_ms + 600_000, True, ("none", None, False)),
            ("none, briefed", None, brief, False, t_ms + 600_000, True, ("none", None, False)),
            ("unavailable, none", None, None, False, t_ms + 600_000, False, unavailable),
            ("unavailable, failed", failed, None, False, t_ms, False, unavailable),
            ("unavailable, started", started, None, False, t_ms + 600_000, False, unavailable),
        ]
        for name, row, brief_, listed, now, managers, expected in table:
            with self.subTest(name):
                state = sprints.SprintState(SID, "p00", "one", 1, t, brief_, row)
                self.assertEqual(sprints.manager_status(state, listed, now, managers), expected)


class DocumentedTest(unittest.TestCase):
    def test_the_manager_rules_are_written_where_the_view_points(self):
        self.assertTrue((sprints.manager_status.__doc__ or "").strip())
        for name in ("manager_status", "manager.started", "manager.failed", "manager.waiting"):
            self.assertIn(name, sprints.__doc__)


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


CLOSING = {"summary": "The importer resumes after a crash.\nSecond line, see #12.",
           "issues": [{"issue": 13, "stage": "dropped"}, {"issue": 12, "stage": "landed"}],
           "differently": "Split the resume slice earlier."}


def closed(seq, sprint_id, closing):
    return Event(seq, at(seq), SPRINT_CLOSED, "owner/p00",
                 {"sprint_id": sprint_id, "goal": "one", "closing": closing})


def stop_requested(seq, sprint_id):
    return Event(seq, at(seq), SPRINT_STOP_REQUESTED, "owner/p00",
                 {"sprint_id": sprint_id, "goal": "one"})


def stopped(seq, sprint_id):
    return Event(seq, at(seq), MANAGER_STOPPED, "owner/p00", {"sprint_id": sprint_id})


def stop_failed(seq, sprint_id, reason):
    return Event(seq, at(seq), MANAGER_STOP_FAILED, "owner/p00",
                 {"sprint_id": sprint_id, "reason": reason})


class ClosingCheckTest(unittest.TestCase):
    def test_the_first_invalid_member_is_named(self):
        no_summary = "the closing report has no valid summary"
        no_issues = "the closing report has no valid issues"
        no_differently = "the closing report has no valid differently"
        number = "the summary's first line names an issue number"
        table = [
            ("missing summary", {k: v for k, v in CLOSING.items() if k != "summary"}, no_summary),
            ("blank summary", {**CLOSING, "summary": " \n "}, no_summary),
            ("long summary", {**CLOSING, "summary": "x" * 4001}, no_summary),
            ("long first line", {**CLOSING, "summary": "x" * 501}, no_summary),
            ("summary not a string", {**CLOSING, "summary": 5}, no_summary),
            ("issue number on the first line", {**CLOSING, "summary": "fixed #12"}, number),
            ("building stage", {**CLOSING, "issues": [{"issue": 12, "stage": "building"}]},
             no_issues),
            ("issue twice", {**CLOSING, "issues": [{"issue": 12, "stage": "landed"},
                                                   {"issue": 12, "stage": "dropped"}]}, no_issues),
            ("issue zero", {**CLOSING, "issues": [{"issue": 0, "stage": "landed"}]}, no_issues),
            ("issue true", {**CLOSING, "issues": [{"issue": True, "stage": "landed"}]},
             no_issues),
            ("extra issue key", {**CLOSING, "issues": [{"issue": 12, "stage": "landed",
                                                        "x": 1}]}, no_issues),
            ("issues not a list", {**CLOSING, "issues": "12"}, no_issues),
            ("too many issues", {**CLOSING, "issues": [{"issue": n, "stage": "landed"}
                                                       for n in range(1, 202)]}, no_issues),
            ("blank differently", {**CLOSING, "differently": "  "}, no_differently),
            ("missing differently", {k: v for k, v in CLOSING.items() if k != "differently"},
             no_differently),
            ("summary is checked before issues", {**CLOSING, "summary": "", "issues": 1},
             no_summary),
        ]
        for name, closing, reason in table:
            with self.subTest(name), self.assertRaises(sprints.Refused) as caught:
                sprints.checked_closing(closing, [])
            self.assertEqual(str(caught.exception), reason)
        second = {**CLOSING, "summary": "It resumes.\nFixed #12 on the way."}
        self.assertEqual(sprints.checked_closing(second, [])["summary"],
                         "It resumes.\nFixed #12 on the way.")

    def test_every_reported_issue_must_be_landed_held_or_dropped_even_when_stopping(self):
        def closing(*rows):
            return {**CLOSING, "summary": "  Done.  ", "differently": " Nothing. ",
                    "issues": [{"issue": n, "stage": stage} for n, stage in rows]}

        with self.assertRaises(sprints.Refused) as caught:
            sprints.checked_closing(closing((12, "landed")), [12, 13])
        self.assertEqual(str(caught.exception),
                         "an issue of this sprint is neither landed nor dropped")
        for rows in (((13, "dropped"), (12, "landed")), ((13, "dropped"), (12, "held"))):
            with self.subTest(rows=rows):
                self.assertEqual(
                    sprints.checked_closing(closing(*rows), [12, 13]),
                    {"summary": "Done.", "differently": "Nothing.",
                     "issues": [{"issue": 12, "stage": rows[1][1]},
                                {"issue": 13, "stage": "dropped"}]})

    def test_a_close_request_is_a_sprint_a_secret_and_a_closing(self):
        body = json.dumps({"sprint_id": SID, "secret": "s", "closing": CLOSING}).encode()
        self.assertEqual(sprints.parse_close_request(body), (SID, "s", CLOSING))
        partial = json.dumps({"sprint_id": SID, "secret": "s",
                              "closing": {"summary": "x"}}).encode()
        self.assertEqual(sprints.parse_close_request(partial), (SID, "s", {"summary": "x"}))
        for body in (
                json.dumps({"sprint_id": SID, "secret": "s", "closing": CLOSING, "x": 1}).encode(),
                json.dumps({"sprint_id": SID, "secret": "s",
                            "closing": {**CLOSING, "x": 1}}).encode(),
                json.dumps({"sprint_id": "nope", "secret": "s", "closing": CLOSING}).encode(),
                json.dumps({"sprint_id": SID, "secret": 5, "closing": CLOSING}).encode(),
                json.dumps({"sprint_id": SID, "secret": "s", "closing": [CLOSING]}).encode(),
                b'{"sprint_id": "' + SID.encode() + b'", "secret": "s", "secret": "t",'
                b' "closing": {}}'):
            with self.subTest(body=body[:40]), self.assertRaises(ValueError):
                sprints.parse_close_request(body)
        good = b'{"project_id": "owner/p00", "sprint_id": "0123456789abcdef"}'
        self.assertEqual(sprints.parse_stop(good), sprints.parse_withdraw(good))
        for bad in (b'{"project_id": "owner/p00", "sprint_id": "nope"}',
                    b'{"project_id": "owner/p00"}',
                    b'{"project_id": "owner/p00", "sprint_id": "0123456789abcdef", "x": 1}'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sprints.parse_stop(bad)


ONE_ISSUE = {**REPORT, "issues": [{"issue": 12, "stage": "building"}]}
LANDED_12 = {**CLOSING, "issues": [{"issue": 12, "stage": "landed"}]}


class ClosingFoldTest(unittest.TestCase):
    def test_a_closing_applies_only_to_an_approved_or_stopping_sprint(self):
        goal = stated(1, "owner/p00", SID, "one")
        self.assertIsNone(sprints.sprint_states([goal, closed(2, SID, LANDED_12)])[SID].closing)
        rows = [goal, sent(2, SID, 1, PARTS), approved(3, SID, 1), reported(4, SID, ONE_ISSUE)]
        not_12 = {**CLOSING, "issues": [{"issue": 13, "stage": "landed"}]}
        self.assertIsNone(sprints.sprint_states([*rows, closed(5, SID, not_12)])[SID].closing)
        folded = sprints.sprint_states([*rows, closed(5, SID, LANDED_12)])
        self.assertEqual(
            folded[SID].closing,
            Closing(at(5), LANDED_12["summary"], "The importer resumes after a crash.",
                    ((12, "landed"),), LANDED_12["differently"]))
        again = sprints.sprint_states([closed(6, SID, {**LANDED_12, "summary": "other"})], folded)
        self.assertEqual(again, folded)
        self.assertIsNone(sprints.sprint_states([*rows, closed(5, SID, 5)])[SID].closing)
        other = "fedcba9876543210"
        self.assertEqual(sprints.sprint_states([closed(6, other, LANDED_12)], folded), folded)
        empty = {**CLOSING, "issues": []}
        stopping = sprints.sprint_states([goal, stop_requested(2, SID), closed(3, SID, empty)])
        self.assertEqual(stopping[SID].closing.issues, ())
        self.assertEqual(stopping[SID].closing.at, at(3))

    def test_a_stopping_sprint_still_needs_every_reported_issue_in_its_closing(self):
        goal = stated(1, "owner/p00", SID, "one")
        rows = [goal, sent(2, SID, 1, PARTS), approved(3, SID, 1), reported(4, SID, ONE_ISSUE),
                stop_requested(5, SID)]
        empty = {**CLOSING, "issues": []}
        self.assertIsNone(sprints.sprint_states([*rows, closed(6, SID, empty)])[SID].closing)
        dropped = {**CLOSING, "issues": [{"issue": 12, "stage": "dropped"}]}
        state = sprints.sprint_states([*rows, closed(6, SID, dropped)])[SID]
        self.assertEqual(state.closing.issues, ((12, "dropped"),))


class StopFoldTest(unittest.TestCase):
    def test_a_stop_request_makes_one_stop_message(self):
        goal = stated(1, "owner/p00", SID, "one")
        state = sprints.sprint_states(
            [goal, stop_requested(2, SID), stop_requested(3, SID)])[SID]
        self.assertEqual(state.stop_at, at(2))
        self.assertEqual(state.messages,
                         (sprints.Message(2, "stop", at(2), None, sprints.STOP_TEXT),))
        self.assertEqual(sprints.STOP_TEXT,
                         "The owner stopped this sprint: finish what is mid-merge, start nothing "
                         "new, and send your closing report with sprint close.")
        rows = [goal, sent(2, SID, 1, PARTS), approved(3, SID, 1), reported(4, SID, ONE_ISSUE),
                closed(5, SID, LANDED_12), stop_requested(6, SID)]
        late = sprints.sprint_states(rows)[SID]
        self.assertIsNone(late.stop_at)
        self.assertEqual([m.kind for m in late.messages], ["approved"])
        self.assertEqual(sprints.sprint_states([stop_requested(2, "fedcba9876543210")]), {})

    def test_manager_stopped_rows_end_or_mark_a_stop(self):
        goal = stated(1, "owner/p00", SID, "one")
        stopping = [goal, stop_requested(2, SID)]

        def state(*rows):
            return sprints.sprint_states([*stopping, *rows])[SID]

        failed = state(stop_failed(3, SID, "no such session"))
        self.assertEqual((failed.stop_reason, failed.stop_failed_at, failed.stopped_at),
                         ("no such session", at(3), None))
        done = state(stop_failed(3, SID, "no such session"), stopped(4, SID))
        self.assertEqual((done.stopped_at, done.stop_reason, done.stop_failed_at),
                         (at(4), None, None))
        after = sprints.sprint_states([stop_failed(5, SID, "late"), stopped(6, SID)],
                                      sprints.sprint_states([*stopping, stopped(4, SID)]))
        self.assertEqual((after[SID].stopped_at, after[SID].stop_reason), (at(4), None))
        bare = sprints.sprint_states([goal, stopped(2, SID), stop_failed(3, SID, "x")])[SID]
        self.assertEqual(bare, sprints.sprint_states([goal])[SID])
        bad = state(Event(3, at(3), MANAGER_STOP_FAILED, "owner/p00",
                          {"sprint_id": SID, "reason": 5}))
        self.assertEqual((bad.stop_reason, bad.stop_failed_at), (None, None))
        self.assertIsNone(state().manager)

    def test_every_route_to_done_has_an_end_time(self):
        head = BASE[:3]
        done = {**REPORT, "phase": "done"}
        both = {**CLOSING, "issues": [{"issue": 12, "stage": "landed"},
                                      {"issue": 13, "stage": "landed"}]}

        def ended(*rows):
            return sprints.ended_at(sprints.sprint_states([*head, *rows])[SID])

        self.assertEqual(ended(reported(4, SID, done)), at(4))
        self.assertIsNone(ended(reported(4, SID, done), reported(5, SID, REPORT)))
        self.assertIsNone(ended(reported(4, SID, done), sent(5, SID, 2, PARTS)))
        self.assertEqual(ended(reported(4, SID, done), sent(5, SID, 2, PARTS), approved(6, SID, 2)),
                         at(4))
        self.assertEqual(ended(reported(4, SID, done), closed(5, SID, both)), at(5))
        self.assertEqual(ended(reported(4, SID, REPORT), closed(5, SID, both)), at(5))
        self.assertIsNone(ended(stop_requested(4, SID)))
        self.assertIsNone(ended(stop_requested(4, SID), reported(5, SID, done)))
        self.assertIsNone(ended(stop_requested(4, SID), reported(5, SID, done),
                                closed(6, SID, both)))
        self.assertEqual(ended(stop_requested(4, SID), reported(5, SID, done), stopped(6, SID)),
                         at(6))
        self.assertIsNone(sprints.ended_at(sprints.sprint_states(
            [stated(1, "owner/p00", SID, "one")])[SID]))
        done_first = [*head, reported(4, SID, done), stop_requested(5, SID)]
        self.assertIsNone(sprints.sprint_states(done_first)[SID].stop_at)

    def test_a_stop_is_due_after_ten_minutes_or_on_the_closing_and_retried_after_a_minute(self):
        base = sprints.SprintState(SID, "owner/p00", "one", 1, at(1))
        t = ms(2)
        stopping = replace(base, stop_at=at(2))
        self.assertFalse(sprints.stop_due(base, t + 10_000_000))
        self.assertFalse(sprints.stop_due(stopping, t + 599_999))
        self.assertTrue(sprints.stop_due(stopping, t + 600_000))
        closing = Closing(at(3), "s", "s", (), "d")
        with_closing = replace(stopping, closing=closing)
        self.assertTrue(sprints.stop_due(with_closing, t + 1))
        f = ms(4)
        failed = replace(with_closing, stop_failed_at=at(4), stop_reason="x")
        self.assertFalse(sprints.stop_due(failed, f + 59_999))
        self.assertTrue(sprints.stop_due(failed, f + 60_000))
        late = "2026-11-12T10:11:30.000000+00:00"
        waited = replace(stopping, stop_failed_at=late)
        self.assertFalse(sprints.stop_due(waited, t + 600_000))
        late_ms = int(datetime.fromisoformat(late).timestamp() * 1000)
        self.assertTrue(sprints.stop_due(waited, late_ms + 60_000))
        self.assertFalse(sprints.stop_due(replace(with_closing, stopped_at=at(5)), t + 10_000_000))
        self.assertEqual((sprints.STOP_WAIT_MS, sprints.STOP_RETRY_MS, sprints.STOP_SETTLE_MS,
                          sprints.FINISHED_AFTER_MS),
                         (600_000, 60_000, 30_000, 86_400_000))

    def test_a_stopping_or_stopped_sprint_offers_no_retry(self):
        t = at(1)
        now = ms(1) + sprints.NO_MANAGER_AFTER_MS + 1
        started = sprints.Manager("started", t, "work", "n")
        failed = sprints.Manager("failed", t, reason="x")
        base = sprints.SprintState(SID, "p00", "one", 1, t)
        missing = ("missing", manager.MISSING_TEXT)
        self.assertEqual(
            sprints.manager_status(replace(base, manager=started), False, now, True),
            (*missing, True))
        self.assertEqual(
            sprints.manager_status(replace(base, manager=started, stop_at=t), False, now, True),
            (*missing, False))
        self.assertFalse(sprints.manager_status(
            replace(base, manager=started, stopped_at=t), False, now, True)[2])
        self.assertTrue(sprints.manager_status(replace(base, manager=failed), False, now, True)[2])
        self.assertFalse(sprints.manager_status(
            replace(base, manager=failed, stop_at=t), False, now, True)[2])
        self.assertFalse(sprints.manager_status(
            replace(base, manager=failed, stopped_at=t), False, now, True)[2])


class PendingStopTest(unittest.TestCase):
    def test_a_withdrawal_pends_a_stop_until_one_succeeds(self):
        pend = PendingStop(SID, "owner/p00", "one", at(2))
        rows = [stated(1, "owner/p00", SID, "one"), withdrawn(2, "owner/p00", SID, "one")]
        self.assertEqual(sprints.pending_stops(rows), {SID: pend})
        failed = sprints.pending_stops([*rows, stop_failed(3, SID, "boom")])
        self.assertEqual(failed, {SID: replace(pend, reason="boom", failed_at=at(3))})
        self.assertEqual(sprints.pending_stops([*rows, stop_failed(3, SID, "boom"),
                                                stopped(4, SID)]), {})
        again = sprints.pending_stops([*rows, stop_failed(3, SID, "boom"),
                                       withdrawn(4, "owner/p00", SID, "two")])
        self.assertEqual(again, {SID: replace(pend, goal="two", at=at(4))})
        other = "fedcba9876543210"
        self.assertEqual(sprints.pending_stops([stop_failed(3, other, "x"), stopped(4, other)]),
                         {})
        noise = [Event(3, at(3), GOAL_WITHDRAWN, None, {"sprint_id": other, "goal": "x"}),
                 Event(4, at(4), GOAL_WITHDRAWN, "owner/p00", {"sprint_id": other}),
                 Event(5, at(5), GOAL_WITHDRAWN, "owner/p00", {"sprint_id": 5, "goal": "x"}),
                 Event(6, at(6), MANAGER_STOP_FAILED, "owner/p00",
                       {"sprint_id": SID, "reason": 5})]
        self.assertEqual(sprints.pending_stops([*rows, *noise]), {SID: pend})
        whole = sprints.pending_stops([*rows, stop_failed(3, SID, "boom"), stopped(4, SID),
                                       withdrawn(5, "owner/p00", other, "x")])
        events = [*rows, stop_failed(3, SID, "boom"), stopped(4, SID),
                  withdrawn(5, "owner/p00", other, "x")]
        for cut in range(len(events) + 1):
            with self.subTest(cut=cut):
                self.assertEqual(
                    sprints.pending_stops(events[cut:], sprints.pending_stops(events[:cut])),
                    whole)
        self.assertTrue(sprints.pending_due(pend, ms(2)))
        retried = replace(pend, failed_at=at(3))
        self.assertFalse(sprints.pending_due(retried, ms(3) + 59_999))
        self.assertTrue(sprints.pending_due(retried, ms(3) + 60_000))


class ClosingTextTest(unittest.TestCase):
    def test_the_closing_wording(self):
        self.assertEqual(sprints.closing_text(2, 0, 0), "2 landed")
        self.assertEqual(sprints.closing_text(1, 1, 1), "1 landed, 1 held for verification, 1 dropped")
        self.assertEqual(sprints.closing_text(0, 0, 2), "0 landed, 2 dropped")
        self.assertEqual(sprints.first_line("  \n first \nsecond"), "first")


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


def messaged(seq, sprint_id, text):
    return Event(seq, at(seq), event_log.SPRINT_MESSAGED, "owner/p00",
                 {"sprint_id": sprint_id, "goal": "one", "text": text})


def read_through(seq, sprint_id, through):
    return Event(seq, at(seq), event_log.SPRINT_READ, "owner/p00",
                 {"sprint_id": sprint_id, "through": through})


def answered(seq, sprint_id, message, reply):
    return Event(seq, at(seq), event_log.SPRINT_ANSWERED, "owner/p00",
                 {"sprint_id": sprint_id, "message": message, "reply": reply})


def nudged(seq, sprint_id, through, ok):
    payload = {"sprint_id": sprint_id, "through": through, "route": "relay", "ok": ok}
    if not ok:
        payload["reason"] = "no route"
    return Event(seq, at(seq), event_log.SPRINT_NUDGED, "owner/p00", payload)


def message_rows():
    return [stated(1, "owner/p00", SID, "one"), sent(2, SID, 1, PARTS),
            replied(3, SID, 1, "smaller slices"), sent(4, SID, 2, PARTS), approved(5, SID, 2),
            messaged(6, SID, "leave the importer's schema alone")]


def message_state_of(events):
    return sprints.sprint_states(events)[SID]


class MessageFoldTest(unittest.TestCase):
    def test_an_approval_a_change_request_and_a_text_each_become_one_message_in_order(self):
        state = message_state_of(message_rows())
        self.assertEqual(
            [(m.message_id, m.kind, m.version, m.text) for m in state.messages],
            [(3, "changes", 1, "smaller slices"), (5, "approved", 2, None),
             (6, "text", None, "leave the importer's schema alone")])
        self.assertEqual([sprints.message_state(m) for m in state.messages],
                         ["sent", "sent", "sent"])
        self.assertEqual([m.at for m in state.messages], [at(3), at(5), at(6)])

    def test_a_stale_or_repeated_decision_makes_no_message(self):
        base = [stated(1, "owner/p00", SID, "one"), sent(2, SID, 1, PARTS),
                sent(3, SID, 2, PARTS), approved(4, SID, 2)]
        stale = [approved(5, SID, 1), approved(6, SID, 2), replied(7, SID, 2, "late")]
        self.assertEqual([m.message_id for m in message_state_of(base + stale).messages], [4])

    def test_a_read_marks_messages_through_its_id_and_unread_returns_the_rest(self):
        state = message_state_of([*message_rows(), read_through(7, SID, 5)])
        self.assertEqual([m.read_at for m in state.messages], [at(7), at(7), None])
        self.assertEqual([m.message_id for m in sprints.unread(state)], [6])
        self.assertEqual([sprints.message_state(m) for m in state.messages],
                         ["read", "read", "sent"])

    def test_a_nudge_delivers_and_two_failures_in_a_row_are_unreachable(self):
        failing = [*message_rows(), nudged(7, SID, 6, False)]
        state = message_state_of(failing)
        self.assertEqual((state.failed_nudges, sprints.unreachable(state)), (1, False))
        state = message_state_of([*failing, nudged(8, SID, 6, False)])
        self.assertEqual((state.failed_nudges, sprints.unreachable(state)), (2, True))
        self.assertEqual(len(state.messages), 3)
        self.assertEqual((state.last_nudge_at, state.last_nudge_ok), (at(8), False))
        state = message_state_of([*failing, nudged(8, SID, 6, False), nudged(9, SID, 6, True)])
        self.assertEqual((state.failed_nudges, sprints.unreachable(state)), (0, False))
        self.assertEqual([m.delivered_at for m in state.messages], [at(9)] * 3)
        self.assertEqual([sprints.message_state(m) for m in state.messages], ["delivered"] * 3)
        self.assertEqual((state.last_nudge_at, state.last_nudge_ok), (at(9), True))
        state = message_state_of([*failing, read_through(8, SID, 6)])
        self.assertEqual(state.failed_nudges, 0)
        state = message_state_of([*message_rows(), nudged(7, SID, 5, True)])
        self.assertEqual([m.delivered_at for m in state.messages], [at(7), at(7), None])

    def test_an_answer_shows_under_its_message_and_the_latest_wins(self):
        state = message_state_of([*message_rows(), answered(7, SID, 6, "kept it"),
                                  answered(8, SID, 6, "kept the schema; moved the change"),
                                  answered(9, SID, 99, "nothing")])
        self.assertEqual([(m.reply, m.reply_at) for m in state.messages],
                         [(None, None), (None, None),
                          ("kept the schema; moved the change", at(8))])
        self.assertEqual(state.messages, message_state_of(
            [*message_rows(), answered(7, SID, 6, "kept it"),
             answered(8, SID, 6, "kept the schema; moved the change")]).messages)

    def test_the_managers_session_is_learned_from_its_seen_row(self):
        goal = stated(1, "owner/p01", SID, "one")

        def session_row(seq, project, name, session_id="s-1"):
            return Event(seq, at(seq), "session.seen", project,
                         {"session_id": session_id, "name": name, "cwd": "/x", "repo": None,
                          "state": "idle"})

        name = manager.session_name("owner/p01", SID)
        folded = sprints.sprint_states([goal, session_row(2, "owner/p01", name)])
        self.assertEqual(folded[SID].manager_session, "s-1")
        folded = sprints.sprint_states([goal, session_row(2, "owner/p01", name),
                                        session_row(3, "owner/p01", name, "s-2")])
        self.assertEqual(folded[SID].manager_session, "s-2")
        for row in (session_row(2, "owner/p02", name),
                    session_row(2, "owner/p01", manager.session_name("owner/p01",
                                                                     "fedcba9876543210")),
                    session_row(2, "owner/p01", manager.session_name("owner/p02", SID)),
                    session_row(2, "owner/p01", name + " x"),
                    session_row(2, "owner/p01", None),
                    session_row(2, "owner/p01", name, 5)):
            with self.subTest(row=row.payload):
                self.assertIsNone(sprints.sprint_states([goal, row])[SID].manager_session)

    def test_a_started_manager_forgets_the_session_of_the_manager_it_replaces(self):
        name = manager.session_name("owner/p01", SID)
        seen = Event(2, at(2), "session.seen", "owner/p01",
                     {"session_id": "s-1", "name": name, "cwd": "/x", "repo": None,
                      "state": "ended"})
        rows = [stated(1, "owner/p01", SID, "one"), seen,
                managed(3, SID, MANAGER_STARTED, profile="work", session_name=name)]
        self.assertIsNone(sprints.sprint_states(rows)[SID].manager_session)
        later = Event(4, at(4), "session.seen", "owner/p01",
                      {"session_id": "s-2", "name": name, "cwd": "/x", "repo": None,
                       "state": "idle"})
        self.assertEqual(sprints.sprint_states([*rows, later])[SID].manager_session, "s-2")

    def test_malformed_message_rows_change_nothing(self):
        base = message_rows()
        bad = [read_through(7, SID, True), read_through(7, SID, "6"),
               Event(7, at(7), event_log.SPRINT_MESSAGED, "owner/p00",
                     {"sprint_id": SID, "goal": "one", "text": 5}),
               Event(7, at(7), event_log.SPRINT_NUDGED, "owner/p00",
                     {"sprint_id": SID, "through": 6, "route": None, "ok": "yes"}),
               Event(7, at(7), event_log.SPRINT_NUDGED, "owner/p00",
                     {"sprint_id": SID, "through": True, "route": None, "ok": True}),
               answered(7, SID, True, "x"), answered(7, SID, 6, 5),
               messaged(7, "fedcba9876543210", "unknown sprint")]
        self.assertEqual(sprints.sprint_states(base + bad), sprints.sprint_states(base))

    def test_a_withdrawn_sprint_keeps_no_messages(self):
        events = [*message_rows(), withdrawn(7, "owner/p00", SID, "one"), messaged(8, SID, "x")]
        self.assertEqual(sprints.sprint_states(events), {})

    def test_message_folding_in_two_parts_equals_folding_at_once(self):
        events = [*message_rows(), nudged(7, SID, 6, False), read_through(8, SID, 5),
                  answered(9, SID, 6, "kept it")]
        whole = sprints.sprint_states(events)
        for cut in range(len(events) + 1):
            with self.subTest(cut=cut):
                self.assertEqual(
                    sprints.sprint_states(events[cut:], sprints.sprint_states(events[:cut])),
                    whole)

    def test_message_bodies_and_the_message_rule(self):
        secret_id = '"sprint_id": "0123456789abcdef"'
        self.assertEqual(
            sprints.parse_message(
                ('{"project_id": "owner/p00", ' + secret_id + ', "text": "hi"}').encode()),
            ("owner/p00", SID, "hi"))
        self.assertEqual(
            sprints.parse_inbox_request(('{' + secret_id + ', "secret": "k"}').encode()),
            (SID, "k"))
        self.assertEqual(
            sprints.parse_message_reply_request(
                ('{' + secret_id + ', "secret": "k", "message": 3, "reply": "ok"}').encode()),
            (SID, "k", 3, "ok"))
        for body in ('{"project_id": "owner/p00", %s}' % secret_id,
                     '{"project_id": "owner/p00", %s, "text": 5}' % secret_id,
                     '{"project_id": "owner/p00", %s, "text": "a", "x": 1}' % secret_id):
            with self.subTest(body=body), self.assertRaises(ValueError):
                sprints.parse_message(body.encode())
        for body in ('{%s}' % secret_id, '{%s, "secret": 5}' % secret_id,
                     '{%s, "secret": "k", "x": 1}' % secret_id):
            with self.subTest(body=body), self.assertRaises(ValueError):
                sprints.parse_inbox_request(body.encode())
        for message in ("0", "true", '"1"', "1.5", "-1"):
            body = '{%s, "secret": "k", "message": %s, "reply": "r"}' % (secret_id, message)
            with self.subTest(message=message), self.assertRaises(ValueError):
                sprints.parse_message_reply_request(body.encode())
        for body in ('{%s, "secret": "k", "message": 1}' % secret_id,
                     '{%s, "secret": "k", "message": 1, "reply": 2}' % secret_id,
                     '{%s, "secret": 7, "message": 1, "reply": "r"}' % secret_id):
            with self.subTest(body=body), self.assertRaises(ValueError):
                sprints.parse_message_reply_request(body.encode())
        for text, reason in (("  ", "write the message first"),
                             ("x" * 2001, "a message is at most 2000 characters")):
            with self.subTest(text=text[:5]), self.assertRaises(sprints.Refused) as caught:
                sprints.checked_message(text)
            self.assertEqual(str(caught.exception), reason)
        self.assertEqual(sprints.checked_message("  keep it  "), "  keep it  ")
        self.assertEqual(sprints.checked_message("x" * 2000), "x" * 2000)

    def test_a_message_has_its_wire_entry_and_constants(self):
        state = message_state_of(message_rows())
        self.assertEqual(sprints.inbox_entry(state.messages[0]),
                         {"id": 3, "kind": "changes", "version": 1, "text": "smaller slices",
                          "at": at(3)})
        self.assertEqual(sprints.inbox_entry(state.messages[1])["text"], None)
        self.assertEqual((sprints.UNREACHABLE_AFTER, sprints.UNREACHABLE_TEXT,
                          sprints.RENUDGE_AFTER_MS, sprints.UNKNOWN_MESSAGE),
                         (2, "manager not reachable", 60_000, "this message is not known"))


if __name__ == "__main__":
    unittest.main()
