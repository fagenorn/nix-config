"""The desk page's done-for-now heading and the finished line's wrap-up (#1810); the fixtures are those of `test_console_page`."""
import unittest

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_page import (
    CLOSING, DONE_SPRINT, NOW_MS, START, ended_sprint, full, has_class, HOUR_MS, nodes, of_class,
    render, render_page, view, visible_text, with_sprints)

TIER = "fast"


DONE = {
    "inbox_items": 0,
    "headline": "You're done for now",
    "sentence": "2 sprints are working; we'll put anything that needs you here.",
    "stale": False,
}


class PageDoneForNowTest(unittest.TestCase):
    def test_the_done_for_now_heading_names_the_next_expected_time(self) -> None:
        statement = render_page(
            {**view([]), "statement": DONE, "next_expected": "2026-11-13T09:30:00+00:00"}, NOW_MS
        )["statement"]
        (h1,) = [n for n in nodes(statement) if n["tag"] == "h1"]
        self.assertEqual(full(h1), "You're done for now")
        (line,) = [n for n in nodes(statement) if has_class(n, "next-expected")]
        self.assertEqual(line["text"], "Next update expected Fri 09:30")
        self.assertEqual(len([n for n in nodes(line) if n["tag"] == "time"]), 1)

    def test_no_next_expected_line_without_a_time_or_with_an_open_item(self) -> None:
        cases = {
            "null time": {**view([]), "statement": DONE, "next_expected": None},
            "no key": {**view([]), "statement": DONE},
            "open item": {
                **view([]),
                "statement": {**DONE, "inbox_items": 1, "headline": "1 thing needs you"},
                "next_expected": "2026-11-13T09:30:00+00:00",
            },
        }
        for name, data in cases.items():
            with self.subTest(name):
                statement = render_page(data, NOW_MS)["statement"]
                self.assertEqual([n for n in nodes(statement) if has_class(n, "next-expected")], [])
                self.assertNotIn("Next update expected", full(statement))


class PageFinishedWrapUpTest(unittest.TestCase):
    def test_a_finished_line_shows_its_wrap_up_before_it_opens(self) -> None:
        (snap,) = render([
            START, {"frame": with_sprints([DONE_SPRINT])}, {"open": "finished"},
            {"snapshot": True},
        ])
        (row,) = of_class(snap["projects"], "li", "finished-line")
        (summary,) = [n for n in nodes(row) if n["tag"] == "summary"]
        self.assertEqual([full(n) for n in of_class(summary, "span", "wrap-up")],
                         ["Importer resumes after a crash"])
        self.assertEqual([full(n) for n in of_class(summary, "span", "outcome")],
                         ["1 landed, 1 dropped"])
        (ended,) = of_class(summary, "span", "ended")
        self.assertEqual([n["title"] for n in nodes(ended) if n["tag"] == "time"], ["2026-11-12 11:00"])
        self.assertTrue(has_class(summary["children"][-1], "wrap-up"))
        shown = visible_text(snap["projects"])
        self.assertIn(CLOSING["first_line"], shown)
        self.assertNotIn(CLOSING["summary"], shown)

    def test_a_finished_line_without_a_closing_first_line_has_no_wrap_up(self) -> None:
        cases = {
            "stopped by the owner": ended_sprint("d", 3 * HOUR_MS, None, "stopped by you"),
            "no first line": ended_sprint("e", 3 * HOUR_MS, {**CLOSING, "first_line": None}),
        }
        for name, sprint in cases.items():
            with self.subTest(name):
                (snap,) = render([START, {"frame": with_sprints([sprint])},
                                  {"open": "finished"}, {"snapshot": True}])
                (row,) = of_class(snap["projects"], "li", "finished-line")
                (summary,) = [n for n in nodes(row) if n["tag"] == "summary"]
                self.assertEqual(of_class(summary, "span", "wrap-up"), [])

    def test_a_finished_line_counts_its_dropped_issues_even_when_none_were_dropped(self) -> None:
        cases = {
            "2 landed": ({"landed": [12, 14], "held": [], "dropped": []}, "2 landed, 0 dropped"),
            "held": ({"landed": [12], "held": [15], "dropped": []},
                     "1 landed, 1 held for verification, 0 dropped"),
        }
        for name, (stages, text) in cases.items():
            sprint = {**DONE_SPRINT, "closing": {**CLOSING, **stages, "counts_text": text.replace(", 0 dropped", "")}}
            with self.subTest(name):
                (snap,) = render([START, {"frame": with_sprints([sprint])}, {"open": "finished"},
                                  {"snapshot": True}])
                (row,) = of_class(snap["projects"], "li", "finished-line")
                self.assertEqual([full(n) for n in of_class(row, "span", "outcome")], [text])
