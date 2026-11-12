"""The console's sprints (#886): goal and withdraw bodies, the goal rules, the fold, the age, the secret.

Run: just agent-workflow-tests
"""

import json
import stat
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import sprints
from agent_tools.console.event_log import GOAL_STATED, GOAL_WITHDRAWN, Event


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
