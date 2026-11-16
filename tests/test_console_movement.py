"""The console's movement readers (#1110): pull requests, branch reflogs, release transactions and the fold.

Run: just agent-workflow-tests
"""

import copy
import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from agent_tools.console import movement
from agent_tools.console.movement import (
    LocalReading, ProcessStat, ProjectMovement, PullMovement, PullRequest, SessionMovement,
    SessionReading, SessionTarget, descendant_cpu, process_table, read_sessions, session_output_ms)
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

    def test_the_production_transport_is_ended_in_flight_by_a_cancellation(self):
        with tempfile.TemporaryDirectory() as home:
            gh = Path(home, "gh")
            gh.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
            gh.chmod(0o755)
            asked = []

            def cancelled():
                asked.append(time.monotonic())
                return len(asked) > 2

            with mock.patch.dict(os.environ, {"PATH": home + os.pathsep + os.environ["PATH"]}):
                started = time.monotonic()
                with self.assertRaises(ForgeError) as caught:
                    movement.read_pulls("owner/p00", PATTERN, cancelled=cancelled)
            self.assertEqual(caught.exception.code, "cancelled")
            self.assertLess(time.monotonic() - started, 10)

    def test_only_a_check_still_queued_or_running_counts_however_many_have_finished(self):
        def running(check_runs, statuses=()):
            data = answer()
            node = nodes_of(data)[0]
            node["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"] = {
                "checkRunCountsByState": [{"state": s, "count": c} for s, c in check_runs],
                "statusContextCountsByState": [{"state": s, "count": c} for s, c in statuses]}
            return movement.pulls_from_answer(data, PATTERN)[0].running

        self.assertTrue(running([("SUCCESS", 100), ("IN_PROGRESS", 1)]))
        self.assertTrue(running([("SUCCESS", 100), ("QUEUED", 1)]))
        self.assertTrue(running([("SUCCESS", 100)], [("PENDING", 1)]))
        self.assertFalse(running([("SUCCESS", 150), ("FAILURE", 2), ("IN_PROGRESS", 0)]))
        # held on a person, such as a deployment environment's reviewer: not CI running
        self.assertFalse(running([("SUCCESS", 3), ("WAITING", 1)]))
        self.assertFalse(running([("WAITING", 1)], [("SUCCESS", 1)]))

    def test_the_query_asks_for_counts_by_state_not_a_page_of_contexts(self):
        self.assertIn("checkRunCountsByState", movement.PULLS_QUERY)
        self.assertIn("statusContextCountsByState", movement.PULLS_QUERY)
        self.assertNotIn("__typename", movement.PULLS_QUERY)

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
            "counts not a list": with_node(
                lambda n: contexts(n).update(checkRunCountsByState="x")),
            "count of no state": with_node(
                lambda n: contexts(n).update(statusContextCountsByState=[{"count": 1}])),
            "count not a number": with_node(
                lambda n: contexts(n).update(
                    checkRunCountsByState=[{"state": "QUEUED", "count": "1"}])),
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

    def test_a_rewritten_head_never_moves_a_pulls_commit_time_back(self):
        first = movement.merged(None, (PullRequest(40, frozenset({4}), False, 5000),), 6000,
                                LocalReading((), False))
        back = movement.merged(first, (PullRequest(40, frozenset({4}), False, 1000),), 7000,
                               LocalReading((), False))
        self.assertEqual(back.pulls[0].committed_ms, 5000)
        none = movement.merged(first, (PullRequest(40, frozenset({4}), False, None),), 8000,
                               LocalReading((), False))
        self.assertEqual(none.pulls[0].committed_ms, 5000)
        newer = movement.merged(back, (PullRequest(40, frozenset({4}), False, 9000),), 9500,
                                LocalReading((), False))
        self.assertEqual(newer.pulls[0].committed_ms, 9000)

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


def stat(proc, pid, comm, ppid, ticks, start):
    directory = Path(proc) / str(pid)
    directory.mkdir(parents=True, exist_ok=True)
    zeros = ["0"] * 9 + [str(ticks), "0", "0", "0"] + ["0"] * 4 + [start, "0", "0"]
    (directory / "stat").write_text(f"{pid} ({comm}) S {ppid} " + " ".join(zeros), encoding="utf-8")


def fake_proc(root):
    proc = Path(root) / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self" / "stat").write_text("1 (x) S 0", encoding="utf-8")
    stat(proc, 100, "claude", 1, 90000, "1000")
    stat(proc, 200, "zsh", 100, 50, "2000")
    stat(proc, 300, "py ) (x", 200, 400, "3000")
    stat(proc, 400, "other", 1, 7, "4000")
    (proc / "500").mkdir()
    return proc


def write_at(path, seconds):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    os.utime(path, (seconds, seconds))


class SessionOutputTest(unittest.TestCase):
    def test_a_sessions_output_is_the_newest_jsonl_write_of_its_transcript_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a" / "projects", Path(tmp) / "b" / "projects"
            write_at(a / "-srv-p00" / "s1.jsonl", 1_800_000_000)
            write_at(a / "-srv-p00" / "s1" / "subagents" / "agent-x.jsonl", 1_800_000_100)
            write_at(a / "-srv-p00" / "s1" / "subagents" / "workflows" / "wf_1" / "agent-y.jsonl",
                     1_800_000_200)
            write_at(a / "-srv-p00" / "s1" / "tool-results" / "big.txt", 1_800_000_900)
            write_at(a / "-srv-p00" / "s2.jsonl", 1_800_000_800)
            write_at(b / "-other" / "s1.jsonl", 1_800_000_300)
            self.assertEqual(session_output_ms([a], "s1"), 1_800_000_200_000)
            self.assertEqual(session_output_ms([a, b], "s1"), 1_800_000_300_000)
            self.assertIsNone(session_output_ms([a], "s9"))
            for bad in ("../s1", "a/b", "", "s\x001", ".", ".."):
                self.assertIsNone(session_output_ms([a], bad), bad)
            self.assertIsNone(session_output_ms([Path(tmp) / "missing"], "s1"))


class ProcessTableTest(unittest.TestCase):
    def test_the_stat_helper_writes_proc5_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            stat(tmp, 300, "py ) (x", 200, 400, "3000")
            fields = (Path(tmp) / "300" / "stat").read_text().rsplit(")", 1)[1].split()
            self.assertEqual(fields[1], "200")
            self.assertEqual(fields[11], "400")
            self.assertEqual(fields[12:15], ["0", "0", "0"])
            self.assertEqual(fields[19], "3000")

    def test_a_session_reads_its_descendants_cpu_never_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = fake_proc(tmp)
            table = process_table(proc, clock_ticks=100)
            self.assertEqual(table[300], ProcessStat(200, "3000", 4000))
            self.assertEqual(descendant_cpu(table, 100),
                             (((200, "2000"), 500), ((300, "3000"), 4000)))
            self.assertEqual(descendant_cpu(table, 999), ())
            self.assertNotIn(500, table)
            empty = Path(tmp) / "empty"
            empty.mkdir()
            self.assertIsNone(process_table(empty, clock_ticks=100))
            stat(proc, 600, "a", 601, 1, "6000")
            stat(proc, 601, "b", 600, 1, "6010")
            table = process_table(proc, clock_ticks=100)
            self.assertEqual(descendant_cpu(table, 600), (((601, "6010"), 10),))

    def test_read_sessions_reads_output_and_cpu_once_per_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = fake_proc(tmp)
            projects = Path(tmp) / "projects"
            write_at(projects / "-srv-p00" / "s1.jsonl", 1_800_000_000)
            targets = (SessionTarget("s2", None, frozenset({"b"})),
                       SessionTarget("s1", 100, frozenset({"a"})),
                       SessionTarget("s3", 999, frozenset()))
            self.assertEqual(
                read_sessions([projects], targets, proc=proc, clock_ticks=100),
                (SessionReading("s1", frozenset({"a"}), 1_800_000_000_000,
                                (((200, "2000"), 500), ((300, "3000"), 4000))),
                 SessionReading("s2", frozenset({"b"}), None, None),
                 SessionReading("s3", frozenset(), None, None)))
            bare = read_sessions([projects], targets, proc=Path(tmp) / "empty", clock_ticks=100)
            self.assertEqual([r.cpu for r in bare], [None, None, None])


def reading(cpu, sprints=("a",), output=None, sid="s1"):
    return SessionReading(sid, frozenset(sprints), output, cpu)


def local_of(*readings, at=None):
    return LocalReading((), False, (), tuple(readings), at)


class SessionFoldTest(unittest.TestCase):
    def test_cpu_moves_a_session_only_after_a_second_used_between_two_readings(self):
        prev = None
        steps = [
            (1000, (((200, "2000"), 500),), None),
            (2000, (((200, "2000"), 1490),), None),
            (3000, (((200, "2000"), 2490),), 3000),
            (4000, (((200, "2000"), 2490),), 3000),
            (5000, (((200, "2000"), 2490), ((201, "2100"), 1000)), 5000),
            (6000, (), 5000),
            (7000, None, 5000),
            (8000, (((202, "2200"), 5000),), 5000),
        ]
        for now, cpu, check in steps:
            prev = movement.merged(prev, None, now, local_of(reading(cpu)))
            got = prev.sessions[0]
            self.assertEqual((got.session_id, got.sprint_id), ("s1", "a"))
            self.assertEqual(got.check_ms, check, now)
        self.assertEqual(prev.sessions[0].cpu, (((202, "2200"), 5000),))
        none = movement.merged(prev, None, 9000, local_of(reading(None)))
        self.assertIsNone(none.sessions[0].cpu)
        self.assertEqual(none.sessions[0].check_ms, 5000)
        again = movement.merged(prev, None, 9000, local_of(reading((((202, "2200"), 7000),)), at=8500))
        self.assertEqual(again.sessions[0].check_ms, 8500)
        self.assertEqual(again.sessions[0].read_ms, 8500)

    def test_output_never_moves_back_and_an_absent_association_is_kept(self):
        first = movement.merged(None, None, 6000, local_of(
            reading(None, ("a",), 5000), reading(None, ("b",), 100, "s2")))
        self.assertEqual(first.sessions, (SessionMovement("s1", "a", 5000, None, None, 6000),
                                          SessionMovement("s2", "b", 100, None, None, 6000)))
        second = movement.merged(first, None, 7000, local_of(reading(None, ("c",), 9000)))
        self.assertEqual(second.sessions, (
            SessionMovement("s1", "a", 5000, None, None, 6000),
            SessionMovement("s1", "c", 9000, None, None, 7000),
            SessionMovement("s2", "b", 100, None, None, 6000)))
        third = movement.merged(second, None, 8000, local_of(
            reading(None, ("a", "c"), 4000), at=7900))
        self.assertIn(SessionMovement("s1", "a", 5000, None, None, 7900), third.sessions)
        self.assertEqual(movement.merged(first, None, 8000, LocalReading((), False)).sessions,
                         first.sessions)
        self.assertEqual(movement.merged(None, None, 1, local_of(
            reading(None, (), 5, "s9"))).sessions, ())

    def test_a_session_that_left_a_sprint_keeps_its_last_times_there(self):
        prev = None
        for t, sprints, c in ((1000, ("a",), 0), (2000, ("a",), 5000),
                              (3000, ("b",), 10000), (4000, ("b",), 15000)):
            prev = movement.merged(prev, None, t, local_of(
                reading((((200, "2000"), c),), sprints, t)))
        self.assertEqual(prev.sessions, (
            SessionMovement("s1", "a", 2000, 2000, (((200, "2000"), 5000),), 2000),
            SessionMovement("s1", "b", 4000, 4000, (((200, "2000"), 15000),), 4000)))


if __name__ == "__main__":
    unittest.main()
