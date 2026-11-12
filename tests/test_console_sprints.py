"""The console's sprints (#886): goal and withdraw bodies, the goal rules, the fold, the age, the secret.

Run: just agent-workflow-tests
"""

import json
import stat
import tempfile
import unittest
from pathlib import Path

from datetime import datetime

from agent_tools.console import event_log, manager, sprints
from agent_tools.console.event_log import (BRIEF_APPROVED, BRIEF_REPLIED, BRIEF_SENT, GOAL_STATED,
                                           GOAL_WITHDRAWN, MANAGER_FAILED, MANAGER_STARTED,
                                           MANAGER_WAITING, Event)


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
        self.assertEqual(state.brief, sprints.Brief(1, PARTS, at(2), "approved", None))
        self.assertEqual(state.state, "starting")
        self.assertIsNone(sprints.sprint_states([goal])[SID].brief)
        self.assertEqual(sprints.sprint_states([goal])[SID].state, "drafting")

    def test_a_newer_brief_replaces_and_stale_decisions_change_nothing(self):
        goal = stated(1, "owner/p00", SID, "one")
        two = {**PARTS, "done": "d2"}

        def brief(events):
            return sprints.sprint_states([goal, *events])[SID].brief

        first = [sent(2, SID, 1, PARTS), replied(3, SID, 1, "no")]
        self.assertEqual(brief(first), sprints.Brief(1, PARTS, at(2), "changes", "no"))
        second = [*first, sent(4, SID, 2, two)]
        self.assertEqual(brief(second), sprints.Brief(2, two, at(4), "none", None))
        self.assertEqual(brief([*second, approved(5, SID, 1)]), brief(second))
        self.assertEqual(brief([*second, sent(5, SID, 2, PARTS)]), brief(second))
        decided = [*second, approved(5, SID, 2)]
        self.assertEqual(brief(decided), sprints.Brief(2, two, at(4), "approved", None))
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
            ("waiting", waiting, None, True, t_ms, True,
             ("waiting", "waiting on quota until", True)),
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
