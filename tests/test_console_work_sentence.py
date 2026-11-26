"""A sprint's now line names its work by issue title, and its grid has a legend.

Run: just agent-workflow-tests
"""

import dataclasses
import re
import unittest
from pathlib import Path

from agent_tools.console import deliveries
from agent_tools.console import sprints
from agent_tools.console.sprints import NOW_QUIET_TEXT, Question

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_briefs import PARTS
from .test_console_engine_runs import DEAD
from .test_console_sprint_engine import LIVE, engine_state
from .test_console_sprints import approved, at, ms, sent, seen, stated
from .test_console_sprints import reported as report_event
from .test_console_view import (
    A, MIN, R, SEVEN, closed, entry, idle_session, iso, line, reported, started, with_manager)

TIER = "fast"

T = {n: f"Title {chr(64 + n)}" for n in range(1, 8)}
IDLE = deliveries.NOW_IDLE_WORK_TEXT


def folded(*reports, runs=()):
    """The sprint state after real events: a goal, an approved brief, one report per row set, then `runs`."""
    events = [stated(1, "p00", A, "make the importer resumable"), sent(2, A, 1, PARTS), approved(3, A, 1)]
    for i, rows in enumerate(reports):
        events.append(report_event(4 + i, A, {
            "status": "two slices are building", "phase": "running", "milestone": "Importer resumes",
            "tracker_url": "https://github.com/owner/p00/milestone/3",
            "issues": [{"issue": n, "stage": s} for n, s in rows], "inbox": [],
            "next": "start the resume slice"}))
    events.extend(runs)
    return sprints.sprint_states(events)[A]


def view_of(it, now_ms, titles=T, **extra):
    return entry(line(it, now_ms, issue_titles={it.project_id: titles}, **extra))


def simple(issues, titles=T, now_ms=R + MIN, **extra):
    return view_of(reported(started(A), R, issues=issues), now_ms, titles, **extra)


FIRST = ((101, "building"), (102, "landing"), (103, "queued"))
SECOND = ((101, "building"), (102, "landed"), (103, "queued"))
TITLES = {101: "Resume a broken upload", 102: "Save a checkpoint per part", 103: "Show the retry button"}
SENTENCE = ("Working on Resume a broken upload. Just finished Save a checkpoint per part; "
            "next is Show the retry button.")


class SprintWorkSentenceTest(unittest.TestCase):
    def test_a_sprint_reads_now_just_finished_and_next_by_issue_title(self):
        it = folded(FIRST, SECOND)
        shown = view_of(it, ms(5) + MIN, TITLES)
        self.assertEqual(shown["now_text"], SENTENCE)
        self.assertIs(shown["now_titled"], True)
        self.assertIsNone(shown["work_text"])
        self.assertIsNone(re.search(r"\d", shown["now_text"]))
        self.assertNotIn("Ship the importer", shown["now_text"])
        self.assertNotIn("Importer resumes", shown["now_text"])
        self.assertEqual(shown["legend"], [{"group": "landed", "count": 1, "text": "1 done"},
                                           {"group": "delivery", "count": 1, "text": "1 in work"},
                                           {"group": "queued", "count": 1, "text": "1 waiting to start"}])
        self.assertEqual(shown["progress_text"], "1 done, 1 in work, 1 waiting to start")

    def test_an_issue_with_no_known_title_is_counted_not_named(self):
        self.assertEqual(entry(line(reported(started(A), R, issues=SEVEN), R + MIN))["now_text"],
                         "Working on 2 issues.")
        self.assertEqual(entry(line(reported(started(A), R, issues=((4, "building"),)), R + MIN))["now_text"],
                         "Working on 1 issue.")

    def test_more_than_two_in_work_names_two_and_counts_the_rest(self):
        three = ((1, "building"), (2, "verifying"), (3, "landing"))
        self.assertEqual(simple(three)["now_text"], "Working on Title A, Title B and 1 more.")
        self.assertEqual(simple(three, {2: "Title B"})["now_text"], "Working on Title B and 2 more.")
        self.assertEqual(simple(three[:2])["now_text"], "Working on Title A and Title B.")

    def test_just_finished_is_what_the_latest_report_moved_to_landed(self):
        it = folded(((1, "building"), (2, "verifying"), (3, "queued")),
                    ((1, "landed"), (2, "landed"), (3, "queued")))
        self.assertEqual(it.report.finished, (1, 2))
        self.assertEqual(view_of(it, ms(5) + MIN)["now_text"],
                         "Just finished Title A and Title B; next is Title C.")
        after = folded(((1, "building"), (2, "verifying"), (3, "queued")),
                       ((1, "landed"), (2, "landed"), (3, "queued")),
                       ((1, "landed"), (2, "landed"), (3, "building")))
        self.assertEqual(view_of(after, ms(6) + MIN)["now_text"],
                         "Working on Title C. Just finished Title A and Title B.")
        single = folded(((1, "landed"), (2, "queued")))
        self.assertEqual(single.report.finished, ())
        self.assertEqual(view_of(single, ms(4) + MIN)["now_text"], "Next is Title B.")
        added = folded(((1, "building"), (2, "queued")), ((1, "building"), (2, "queued"), (4, "landed")))
        self.assertNotIn(4, added.report.finished)

    def test_a_later_run_movement_does_not_replace_just_finished(self):
        runs = (seen(6, "wf_c", ms(5) + 30_000, [(101, "building")], project="p00"),
                seen(7, "wf_d", ms(5) + 40_000, [(103, "planning")], project="p00"))
        it = folded(FIRST, SECOND, runs=runs)
        self.assertEqual(it.report.finished, (102,))
        self.assertEqual({o.issue for o in it.observed}, {101, 103})
        self.assertIn("Just finished Save a checkpoint per part", view_of(it, ms(7) + MIN, TITLES)["now_text"])

    def test_next_is_the_lowest_numbered_queued_issue(self):
        queued = ((5, "queued"), (6, "queued"))
        self.assertEqual(simple(queued)["now_text"], "Next is Title E.")
        self.assertEqual(simple(queued, {6: "Title F"})["now_text"], IDLE)

    def test_an_issue_the_engine_is_building_is_in_work_not_next(self):
        it = reported(with_manager(started(A)), R, issues=((1, "building"), (2, "queued"), (3, "queued")))
        got = view_of(it, R + 40 * MIN, sessions=[idle_session],
                      engine_runs=[engine_state("sprint-moving.jsonl", LIVE, issue=2)])
        self.assertEqual(got["now_text"], "Working on Title A and Title B. Next is Title C.")
        self.assertEqual({row["group"]: row["count"] for row in got["legend"]}, {"delivery": 2, "queued": 1})
        stage = {row["issue"]: row["stage"] for row in got["issues"]}[2]
        self.assertNotIn(stage, ("landed", "held", "queued"))

    def test_a_dead_engine_does_not_turn_a_queued_issue_into_work(self):
        it = reported(with_manager(started(A)), R, issues=((1, "building"), (2, "queued"), (3, "queued")))
        got = view_of(it, R + 40 * MIN, sessions=[idle_session],
                      engine_runs=[engine_state("sprint-moving.jsonl", DEAD, issue=2)])
        self.assertEqual(got["now_text"], "last seen working on Title A. Next is Title B.")
        self.assertEqual({row["group"]: row["count"] for row in got["legend"]}, {"delivery": 1, "queued": 2})
        self.assertEqual({row["issue"]: row["stage"] for row in got["issues"]}[2], "queued")

    def test_a_closed_out_run_is_in_work_on_the_line_and_in_the_legend(self):
        runs = (seen(5, "wf_c", ms(4) + 30_000, [(1, "done")], project="p00"),)
        it = folded(((1, "building"), (2, "queued")), runs=runs)
        got = view_of(it, ms(5) + MIN)
        self.assertEqual({row["issue"]: row["stage"] for row in got["issues"]}[1], "closed out")
        self.assertEqual(got["now_text"], "Working on Title A. Next is Title B.")
        self.assertEqual(it.report.finished, ())
        self.assertEqual([row["text"] for row in got["legend"]], ["1 in work", "1 waiting to start"])

    def test_a_quiet_sprint_reads_last_seen_and_its_work(self):
        it = folded(FIRST, SECOND)
        got = view_of(it, ms(5) + 20 * MIN, TITLES)
        self.assertEqual(got["now_text"], "last seen working on Resume a broken upload. "
                         "Just finished Save a checkpoint per part; next is Show the retry button.")
        self.assertIs(got["now_titled"], True)
        self.assertIsNone(got["work_text"])

    def test_a_wait_keeps_its_words_and_the_work_moves_to_work_text(self):
        it = folded(FIRST, SECOND)
        it = dataclasses.replace(it, questions=(
            Question(1, 0, iso(R), False, "Which store?", "ctx", ("a", "b"), "a"),))
        got = view_of(it, ms(5) + MIN, TITLES)
        self.assertEqual(got["now_text"], "waiting for your answer: Which store?")
        self.assertIs(got["now_titled"], False)
        self.assertEqual(got["work_text"], SENTENCE)

    def test_a_title_naming_an_issue_or_the_sprint_is_counted_not_named(self):
        titles = {1: "ship  the Importer", 2: "Upload 3 files at once", 3: "Follow up on #12"}
        got = simple(((1, "building"), (2, "building"), (3, "queued")), titles)
        self.assertEqual(got["now_text"], "Working on Upload 3 files at once and 1 more.")
        self.assertEqual(deliveries.shown_title("  Save a\ncheckpoint ", "x"), "Save a checkpoint")
        self.assertIsNone(deliveries.shown_title("Fix #4", "x"))
        self.assertIsNone(deliveries.shown_title("Ship the importer", "Ship the importer"))

    def test_titles_of_another_project_name_nothing(self):
        got = entry(line(reported(started(A), R, issues=SEVEN), R + MIN, issue_titles={"p01": T}))
        self.assertEqual(got["now_text"], "Working on 2 issues.")

    def test_the_legend_counts_done_in_work_waiting_to_start_and_waiting_for_a_check(self):
        rows = SEVEN[:6] + ((7, "held"),)
        got = simple(rows)
        self.assertEqual(got["legend"], [
            {"group": "landed", "count": 3, "text": "3 done"},
            {"group": "delivery", "count": 2, "text": "2 in work"},
            {"group": "queued", "count": 1, "text": "1 waiting to start"},
            {"group": "held", "count": 1, "text": "1 waiting for a check"}])
        self.assertEqual(got["progress_text"], "3 done, 2 in work, 1 waiting to start, 1 waiting for a check")
        self.assertEqual(deliveries.progress_text(
            {"landed": 1, "in_delivery": 0, "queued": 0, "held": 3, "total": 4}), "1 done, 3 waiting for a check")
        self.assertEqual(deliveries.progress_text(
            {"landed": 0, "in_delivery": 0, "queued": 0, "held": 0, "total": 0}), "0 done")

    def test_a_drafting_or_ended_sprint_has_no_work_or_legend(self):
        ended = closed(reported(started(A), R), R + MIN, ((12, "landed"),))
        for it in (started(A), ended):
            got = view_of(it, R + 2 * MIN)
            self.assertEqual((got["work_text"], got["legend"], got["now_titled"]), (None, None, False))
        empty = simple(())
        self.assertEqual((empty["now_text"], empty["legend"], empty["progress_text"]), (IDLE, [], "0 done"))


class ServiceSizeTest(unittest.TestCase):
    def test_the_service_module_does_not_grow_past_its_size_at_the_merge_base(self):
        """B17: the module was over 1,500 lines at the merge base, so it may not grow."""
        path = Path(__file__).parent.parent / "python" / "agent_tools" / "console" / "service.py"
        self.assertLessEqual(len(path.read_text(encoding="utf-8").splitlines()), 11341)


if __name__ == "__main__":
    unittest.main()
