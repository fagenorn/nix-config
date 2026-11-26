"""The desk page's End the sprint fold inside the sprint's own fold.

Run: just agent-workflow-tests
"""

import re
import unittest
from pathlib import Path

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_page import (
    CLOSING, DETAIL_KEY, MORE_KEY, SPRINT, START, detail, full, has_class, in_line, more_fold,
    of_class, render, sprint_lines, visible, with_sprints)

TIER = "fast"  # the page harness under node and the standard library

PAGE = Path(__file__).resolve().parents[1] / "python/agent_tools/console/page.html"


class SprintEndFoldTest(unittest.TestCase):
    def test_end_the_sprint_sits_in_the_sprints_fold_apart_from_tell_the_manager(self) -> None:
        closed, opened, asked = render([
            START, {"frame": with_sprints([{**SPRINT, "stoppable": True}])}, {"snapshot": True},
            {"open": DETAIL_KEY}, {"open": MORE_KEY}, {"snapshot": True},
            {"click": "stop"}, {"snapshot": True},
        ])
        (closing,) = render([
            START, {"frame": with_sprints([{**SPRINT, "closing": CLOSING}])}, {"snapshot": True},
        ])
        (line,) = sprint_lines(closed)
        (acts,) = of_class(line, "div", "sprint-acts")
        self.assertEqual(of_class(acts, "details", "sprint-more"), [])
        self.assertEqual(len(of_class(acts, "button", "tell-open")), 1)
        fold = detail(line)
        last = fold["children"][-1]
        self.assertEqual((last["tag"], last["key"], has_class(last, "sprint-more")),
                         ("details", MORE_KEY, True))
        (summary,) = [c for c in last["children"] if c["tag"] == "summary"]
        self.assertEqual(full(summary), "End the sprint")
        self.assertEqual([n for n in visible(line) if has_class(n, "more-open")], [])
        (line,) = sprint_lines(opened)
        self.assertEqual(len(in_line(line, "button", "stop")), 1)
        self.assertEqual(len(in_line(line, "button", "withdraw")), 1)
        (line,) = sprint_lines(asked)
        self.assertEqual(len([c for c in line["children"] if has_class(c, "stop-ask")]), 1)
        self.assertEqual(of_class(detail(line), "span", "stop-ask"), [])
        self.assertEqual(len([c for c in line["children"] if has_class(c, "stop-confirm")]), 1)
        self.assertTrue(detail(line)["open"])
        self.assertTrue(more_fold(line)["open"])
        (line,) = sprint_lines(closing)
        fold = detail(line)
        self.assertNotEqual(of_class(fold, "div", "closing-report"), [])
        self.assertEqual(fold["children"][-1]["key"], MORE_KEY)

    def test_tell_the_manager_keeps_one_place_above_the_fold_and_the_stops_close_the_open_report(self) -> None:
        sprint = {**SPRINT, "stoppable": True, "tracker_url": "https://example.invalid/t/1"}
        closed, opened, ended = render([
            START, {"frame": with_sprints([sprint])}, {"snapshot": True},
            {"open": DETAIL_KEY}, {"snapshot": True},
            {"open": MORE_KEY}, {"snapshot": True},
        ])
        places = []
        for snap in (closed, opened, ended):
            (line,) = sprint_lines(snap)
            kids = line["children"]
            (acts,) = [c for c in kids if has_class(c, "sprint-acts")]
            (fold,) = [c for c in kids if has_class(c, "sprint-detail")]
            (status,) = [c for c in kids if has_class(c, "sp-head")]
            self.assertEqual(len(of_class(acts, "button", "tell-open")), 1)
            self.assertEqual(of_class(line, "details", "sprint-more")[0], fold["children"][-1])
            self.assertEqual(
                [c["tag"] for c in fold["children"][-2:]], ["a", "details"])
            self.assertTrue(has_class(fold["children"][-2], "tracker"))
            self.assertLess(kids.index(status), kids.index(acts))
            self.assertLess(kids.index(acts), kids.index(fold))
            places.append(kids.index(acts))
        self.assertEqual(len(set(places)), 1)

    def test_the_end_fold_is_set_apart_by_a_rule_and_clear_space(self) -> None:
        css = PAGE.read_text(encoding="utf-8")
        (rule,) = re.findall(r"^\.sprint-more \{([^}]*)\}", css, re.M)
        self.assertRegex(rule, r"border-top:\s*1px solid")
        self.assertRegex(rule, r"margin-top:\s*(1[2-9]|[2-9]\d)px")
        self.assertRegex(rule, r"padding-top:\s*(8|9|[1-9]\d)px")
