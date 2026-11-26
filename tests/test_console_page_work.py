"""The page draws a sprint's work line and the legend beside its grid.

Run: just agent-workflow-tests
"""

import re
import unittest

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_guest_page import GUEST, page_of, sprint_text
from .test_console_page import (
    PAGE, REPORTED, SPRINT, START, full, has_class, nodes, render, sprint_lines, top, top_text, with_sprints)
from .test_console_view import A, MIN, T0_MS, entry as view_entry, line as view_line, reported, started
from .test_console_work_sentence import SECOND, FIRST, TITLES, folded

TIER = "fast"


def top_of(frame_sprint: dict) -> list:
    (snap,) = render([START, {"frame": with_sprints([frame_sprint])}, {"snapshot": True}])
    (row,) = sprint_lines(snap)
    return top(row)


def legend_texts(row_top: list) -> list:
    return [full(n) for n in row_top if has_class(n, "legend-item")]


class SprintWorkPageTest(unittest.TestCase):
    def test_the_progress_grid_carries_a_legend_in_counts_and_words(self) -> None:
        it = reported(started(A), T0_MS, issues=(
            (1, "landed"), (2, "building"), (3, "queued"), (4, "held"), (5, "landed")))
        sprint = view_entry(view_line(it, T0_MS + MIN))
        (snap,) = render([START, {"frame": with_sprints([sprint])}, {"snapshot": True}])
        (row,) = sprint_lines(snap)
        row_top = top(row)
        (legend,) = [n for n in row_top if has_class(n, "pip-legend")]
        self.assertEqual([n for n in row_top if has_class(n, "pip-count")], [])
        items = [c for c in legend["children"] if has_class(c, "legend-item")]
        self.assertEqual([full(c) for c in items],
                         ["2 done", "1 in work", "1 waiting to start", "1 waiting for a check"])
        self.assertEqual([c["children"][0]["cls"].split() for c in items],
                         [["pip", f"pip-{g}"] for g in ("landed", "delivery", "queued", "held")])
        (pips,) = [n for n in row_top if has_class(n, "pips")]
        total = 0
        for part in sprint["legend"]:
            made = [c for c in pips["children"] if has_class(c, f"pip-{part['group']}")]
            self.assertEqual(len(made), part["count"])
            total += len(made)
        self.assertEqual(total, len(pips["children"]))
        self.assertEqual(total, 5)

    def test_a_running_sprints_face_names_its_work_by_title_with_no_number_or_own_title(self) -> None:
        it = folded(FIRST, SECOND)
        titles = {it.project_id: TITLES}
        sprint = view_entry(view_line(it, T0_MS + MIN, issue_titles=titles))
        (snap,) = render([START, {"frame": with_sprints([sprint])}, {"snapshot": True}])
        (row,) = sprint_lines(snap)
        face = top_text(row)
        self.assertEqual([n for n in top(row) if has_class(n, "sp-now")], [])
        (work,) = [n for n in top(row) if has_class(n, "sp-work")]
        self.assertEqual([full(line) for line in work["children"]], [
            "Working on: \u201cResume a broken upload\u201d",
            "Just finished: \u201cSave a checkpoint per part\u201d",
            "Next: \u201cShow the retry button\u201d"])
        self.assertIsNone(re.search(r"#\d|\b10[123]\b", face))
        self.assertEqual(face.count(sprint["title"]), 1)
        self.assertEqual(legend_texts(top(row)), ["1 done", "1 in work", "1 waiting to start"])

    def test_each_part_is_its_own_line_with_its_title_set_apart_in_a_heavier_weight(self) -> None:
        it = folded(FIRST, SECOND)
        sprint = view_entry(view_line(it, T0_MS + MIN, issue_titles={it.project_id: TITLES}))
        row_top = top_of(sprint)
        (work,) = [n for n in row_top if has_class(n, "sp-work")]
        lines = work["children"]
        self.assertEqual([c["cls"] for c in lines], ["work-line"] * 3)
        self.assertEqual([[full(p) for p in c["children"]] for c in lines], [
            ["Working on: ", "\u201cResume a broken upload\u201d"],
            ["Just finished: ", "\u201cSave a checkpoint per part\u201d"],
            ["Next: ", "\u201cShow the retry button\u201d"]])
        for line in lines:
            label, title = line["children"]
            self.assertEqual((label["cls"], title["cls"]), ("", "work-title"))
        weight = re.search(r"^\.work-title\s*\{([^}]*)\}", PAGE.read_text(encoding="utf-8"), re.M)
        self.assertRegex(weight.group(1), r"font-weight:\s*[5-9]00")
        wait = {**REPORTED, "now_text": "waiting for CI on its pull request", "now_titled": False,
                "work_text": sprint["now_text"]}
        (work,) = [n for n in top_of(wait) if has_class(n, "sp-work")]
        self.assertEqual([c["cls"] for c in work["children"]], ["work-line"] * 3)

    def test_a_wait_shows_the_work_line_before_its_now_line_and_none_without_it(self) -> None:
        wait = {**REPORTED, "now_text": "waiting for CI on its pull request",
                "work_text": "Working on: \u201cResume a broken upload\u201d", "now_titled": False}
        order = [(n["cls"].split()[0], full(n)) for n in top_of(wait)
                 if has_class(n, "sp-work") or has_class(n, "sp-now")]
        self.assertEqual(order, [("sp-work", "Working on: \u201cResume a broken upload\u201d"),
                                 ("sp-now", "waiting for CI on its pull request")])
        empty = {**REPORTED, "work_text": None,
                 "progress": {"landed": 0, "in_delivery": 0, "queued": 0, "held": 0, "total": 0},
                 "progress_text": "0 done", "issues": [], "legend": []}
        for quiet in (SPRINT, {**REPORTED, "work_text": None}, empty):
            row_top = top_of(quiet)
            self.assertEqual([n for n in row_top if has_class(n, "sp-work")], [])
            self.assertEqual(legend_texts(row_top), [])

    def test_the_now_sentence_keeps_its_two_line_clamp_and_the_work_line_stays_on_one_line(self) -> None:
        css = PAGE.read_text(encoding="utf-8")
        self.assertNotIn(".sp-now.titled", css)
        for selector in (r"\.sp-now", r"\.work-line", r"\.work-title"):
            (body,) = re.findall(r"^" + selector + r"\s*\{([^}]*)\}", css, re.M)
            if selector == r"\.sp-now":
                self.assertRegex(body, r"-webkit-line-clamp:\s*2")
                self.assertRegex(body, r"overflow:\s*hidden")
            elif selector == r"\.work-line":
                self.assertRegex(body, r"display:\s*flex")
                self.assertRegex(body, r"white-space:\s*pre\b")
            else:
                self.assertRegex(body, r"overflow:\s*hidden")
                self.assertRegex(body, r"text-overflow:\s*ellipsis")
                self.assertRegex(body, r"min-width:\s*0")

    def test_a_guest_sees_a_title_as_the_tracker_wrote_it(self) -> None:
        titled = {**REPORTED, "now_text": "Working on: \u201cExport your settings\u201d", "now_titled": True,
                  "work_text": None}
        waiting = {**REPORTED, "now_text": "waiting for CI on its pull request", "now_titled": False,
                   "work_text": "Working on: \u201cExport your settings\u201d"}
        for sprint in (titled, waiting):
            snap = page_of(GUEST, [START, {"frame": with_sprints([sprint])}])
            face = sprint_text(snap)
            self.assertRegex(face, r"Working on:\s+\u201cExport your settings\u201d")
            self.assertNotIn("the owner's settings", face)


if __name__ == "__main__":
    unittest.main()
