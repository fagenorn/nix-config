"""The console's movement readers (#1110): pull requests, branch reflogs, release transactions and the fold.

Run: just agent-workflow-tests
"""

import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from agent_tools.console import movement
from agent_tools.console.movement import (
    LocalReading, ProjectMovement, PullMovement, PullRequest)
from agent_tools.system.forge_api import ForgeError
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

PATTERN = "issue-<num>-<slug>"
FIXTURE = Path(__file__).parent / "fixtures" / "console" / "forge-pulls.json"
REL = "rel_01890a5d-ac96-7abc-8def-0123456789ab"


def ms(text):
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def answer():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def nodes_of(data):
    return data["data"]["repository"]["pullRequests"]["nodes"]


READ = (PullRequest(40, frozenset({4}), True, ms("2026-11-12T09:00:00+00:00")),
        PullRequest(41, frozenset({5}), False, ms("2026-11-12T08:30:00+00:00")),
        PullRequest(42, frozenset({99}), True, ms("2026-11-12T08:00:00+00:00")))


class PullsTest(unittest.TestCase):
    def test_the_recorded_answer_reads_each_pulls_issues_checks_and_commit(self):
        self.assertEqual(movement.pulls_from_answer(answer(), PATTERN), READ)
        bare = movement.pulls_from_answer(answer(), None)
        self.assertEqual(bare[0].issues, frozenset())
        self.assertEqual(bare[1].issues, frozenset({5}))

    def test_a_read_is_one_call_asked_before_it_is_cancelled(self):
        calls = []

        def stub(argv):
            calls.append(argv)
            return answer()

        self.assertEqual(movement.read_pulls("owner/p00", PATTERN, call=stub), READ)
        self.assertEqual(calls, [movement.pulls_argv("owner/p00")])
        argv = calls[0]
        self.assertIn("owner=owner", argv)
        self.assertIn("name=p00", argv)
        query = [a for a in argv if a.startswith("query=")]
        self.assertEqual(len(query), 1)
        self.assertIn("pullRequests(states: OPEN, first: 50", query[0])
        with self.assertRaises(ForgeError) as caught:
            movement.read_pulls("owner/p00", PATTERN, call=stub, cancelled=lambda: True)
        self.assertEqual(caught.exception.code, "cancelled")
        self.assertEqual(len(calls), 1)

    def test_an_answer_of_another_shape_is_payload_invalid(self):
        def with_node(change):
            data = answer()
            change(nodes_of(data)[0])
            return data

        def contexts(node):
            return node["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]

        cases = {
            "empty": {},
            "no repository": {"data": {"repository": None}},
            "string number": with_node(lambda n: n.update(number="40")),
            "bad date": with_node(
                lambda n: n["commits"]["nodes"][0]["commit"].update(committedDate="not a date")),
            "contexts not a list": with_node(lambda n: contexts(n).update(nodes="x")),
        }
        for name, data in cases.items():
            with self.subTest(name):
                with self.assertRaises(ForgeError) as caught:
                    movement.pulls_from_answer(data, PATTERN)
                self.assertEqual(caught.exception.code, "payload_invalid")

    def test_a_body_names_an_issue_only_as_a_bare_hash_number(self):
        self.assertEqual(
            movement.body_issues("Fixes #12, see #3.\nowner/repo#6 abc#7 (#8)"),
            frozenset({12, 3, 8}))


class LocalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / ".git").mkdir()

    def reflog(self, branch, *times):
        path = self.root / ".git" / "logs" / "refs" / "heads" / branch
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(
            "0" * 40 + " " + "a" * 40 + f" A <a@b> {t} +0000\t{message}\n"
            for t, message in times), encoding="utf-8")

    def test_a_branch_of_an_issue_reads_its_last_reflog_time(self):
        self.reflog("issue-4-resume", (1800000000, "branch: Created from HEAD"),
                    (1800000600, "commit: resume"))
        self.reflog("team/issue-5-x", (1800000300, "branch: Created from HEAD"))
        path = self.root / ".git" / "logs" / "refs" / "heads" / "issue-6-y"
        path.write_text("garbage\n", encoding="utf-8")
        self.reflog("issue-4-again", (1800000100, "branch: Created from HEAD"))
        self.assertEqual(movement.branch_updates(str(self.root), PATTERN), ((4, 1800000600000),))
        self.assertEqual(movement.branch_updates(str(self.root), None), ())
        with tempfile.TemporaryDirectory() as bare:
            self.assertEqual(movement.branch_updates(bare, PATTERN), ())

    def state(self, text, name=REL):
        path = self.root / ".git" / "agent-release" / "store" / name / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_a_release_is_in_progress_only_in_a_known_live_state(self):
        root = str(self.root)
        self.assertEqual(movement.release_reading(root), (False, ()))
        for live in ("publishing", "recovering"):
            with self.subTest(live):
                self.state(json.dumps({"state": live}))
                self.assertEqual(movement.release_reading(root), (True, ()))
        for held in ("attention_required", "succeeded", "abandoned", "rolled_back", "failed"):
            with self.subTest(held):
                self.state(json.dumps({"state": held}))
                self.assertEqual(movement.release_reading(root), (False, ()))
        for bad in ('{"state": ""}', '{"state": "invalid"}', '{"state": 7}', "[]", "{not json"):
            with self.subTest(bad):
                self.state(bad)
                self.assertEqual(movement.release_reading(root), (False, (REL,)))

    def test_a_transaction_directory_with_no_state_is_skipped(self):
        (self.root / ".git" / "agent-release" / "store" / REL).mkdir(parents=True)
        self.assertEqual(movement.release_reading(str(self.root)), (False, ()))

    def test_only_transaction_directories_count(self):
        self.state(json.dumps({"state": "succeeded"}))
        self.state(json.dumps({"state": "publishing"}), "receipts")
        self.assertEqual(movement.release_reading(str(self.root)), (False, ()))

    def test_read_local_joins_the_branches_and_the_release(self):
        root = str(self.root)
        self.assertEqual(movement.read_local(root, PATTERN), LocalReading((), False, ()))
        self.state(json.dumps({"state": "publishing"}))
        self.assertEqual(movement.read_local(root, PATTERN), LocalReading((), True, ()))
        self.state(json.dumps({"state": "invalid"}))
        self.assertEqual(movement.read_local(root, PATTERN), LocalReading((), False, (REL,)))


class MergeTest(unittest.TestCase):
    def first(self):
        return movement.merged(
            None, (PullRequest(40, frozenset({4}), True, 1), PullRequest(41, frozenset({5}), True, 3)),
            1000, LocalReading((), False))

    def test_a_pull_keeps_the_time_it_was_last_seen_running_even_once_gone(self):
        first = self.first()
        self.assertEqual(first, ProjectMovement(
            (PullMovement(40, frozenset({4}), 1000, 1), PullMovement(41, frozenset({5}), 1000, 3)),
            1000, (), None))
        second = movement.merged(first, (PullRequest(40, frozenset({4}), False, 2),), 2000,
                                 LocalReading(((4, 1500),), False))
        self.assertEqual(second, ProjectMovement(
            (PullMovement(40, frozenset({4}), 1000, 2), PullMovement(41, frozenset({5}), 1000, 3)),
            2000, ((4, 1500),), None))
        self.assertEqual(movement.merged(first, (), 9000, LocalReading((), False)).pulls, first.pulls)

    def test_a_failed_read_keeps_the_last_pulls_and_their_read_time(self):
        first = self.first()
        kept = movement.merged(first, None, 5000, LocalReading((), False))
        self.assertEqual(kept.pulls, first.pulls)
        self.assertEqual(kept.read_ms, 1000)
        self.assertEqual(movement.merged(None, None, 5000, LocalReading((), False)),
                         ProjectMovement())

    def test_a_release_keeps_the_time_it_was_last_seen_in_progress(self):
        a = movement.merged(None, None, 1000, LocalReading((), True))
        self.assertEqual(a.release_ms, 1000)
        self.assertEqual(movement.merged(a, None, 3000, LocalReading((), False)).release_ms, 1000)
        self.assertEqual(movement.merged(a, None, 3000, LocalReading((), True)).release_ms, 3000)
        self.assertEqual(
            movement.merged(a, None, 3000, LocalReading((), False, ("rel_x",))).release_ms, 1000)

    def test_a_deleted_branch_keeps_its_last_time(self):
        prev = movement.merged(None, None, 1000, LocalReading(((4, 1500), (5, 1600)), False))
        self.assertEqual(
            movement.merged(prev, None, 3000, LocalReading(((4, 1400), (6, 2000)), False)).branches,
            ((4, 1500), (5, 1600), (6, 2000)))


if __name__ == "__main__":
    unittest.main()
