"""The goal box's refusal sits under the field and survives closing the box (#1214)."""

import unittest

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_controls import CONSOLE_URL, PAGE_STUBS, SETTLE, served
from .test_console_page import (
    GOAL_FRAME, NOW_MS, START, box_open, full, goal_fail, goal_named, goals, has_class, nodes,
    render)

TOO_LONG_LINE = "Could not send: a goal is at most 2000 characters"
MANY_FRAME = {**GOAL_FRAME, "recent_projects": [f"owner/project-{i:02d}" for i in range(25)]}


def box_children(snap: dict) -> list[str]:
    """The `cls` of each direct child of the single goal-box node, in order."""
    (box,) = goal_named(snap, "goal-box")
    return [child["cls"] for child in box["children"]]


class GoalRefusalTest(unittest.TestCase):
    def test_a_refusal_survives_closing_and_reopening_the_box(self):
        closes = ({"key": "Escape"}, {"click": "goal-cancel"})
        for close in closes:
            with self.subTest(close=close):
                refused, closed, reopened, edited = render([
                    START, {"frame": GOAL_FRAME}, {"key": "g"},
                    {"input": {"cls": "goal-text", "value": "x" * 2001}},
                    {"click": "goal-send"}, {"snapshot": True},
                    close, {"snapshot": True},
                    {"key": "g"}, {"snapshot": True},
                    {"input": {"cls": "goal-text", "value": "x" * 10}}, {"snapshot": True},
                ])
                self.assertEqual(goal_fail(refused), [TOO_LONG_LINE])
                self.assertIs(box_open(closed), False)
                self.assertEqual(goal_fail(reopened), [TOO_LONG_LINE])
                (text,) = goal_named(reopened, "goal-text")
                self.assertEqual(text["value"], "x" * 2001)
                self.assertEqual(goals(reopened), [])
                self.assertEqual(goal_fail(edited), [])
        with self.subTest(close="a service refusal"):
            (snap,) = render([
                START, {"frame": GOAL_FRAME}, {"key": "g"},
                {"input": {"cls": "goal-text", "value": "make it resumable"}},
                {"respond": {"status": 409, "text": "this project is not registered\n"}},
                {"click": "goal-send"}, {"key": "Escape"}, {"key": "g"}, {"snapshot": True},
            ])
            self.assertEqual(goal_fail(snap), ["Could not send: this project is not registered"])
            self.assertEqual(len(goals(snap)), 1)

    def test_the_refusal_sits_above_the_project_choice(self):
        (snap,) = render([
            START, {"frame": GOAL_FRAME}, {"key": "g"},
            {"input": {"cls": "goal-text", "value": "x" * 2001}},
            {"click": "goal-send"}, {"snapshot": True},
        ])
        kids = [cls.split() for cls in box_children(snap)]
        status = next(i for i, c in enumerate(kids) if "goal-status" in c)
        choice = next(i for i, c in enumerate(kids) if "goal-filter" in c)
        self.assertLess(status, choice)
        (box,) = goal_named(snap, "goal-box")
        held = box["children"][status]
        (fail,) = [n for n in nodes(held) if has_class(n, "fail")]
        self.assertEqual(full(fail), TOO_LONG_LINE)


class GoalRefusalChromiumTest(unittest.TestCase):
    def chromium(self):
        """A launched Chromium; the test is skipped when playwright or Chromium is missing."""
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        pw = sync_playwright().start()
        self.addCleanup(pw.stop)
        try:
            browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        except Error as err:
            self.skipTest(f"no Chromium to launch: {err}")
        self.addCleanup(browser.close)
        return browser

    def test_the_refusal_is_in_view_beside_the_field(self):
        browser = self.chromium()
        for width in (1440, 480):
            with self.subTest(width=width):
                page = browser.new_page(viewport={"width": width, "height": 900})
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                page.route(f"{CONSOLE_URL}/**", served)
                page.add_init_script(PAGE_STUBS)
                page.clock.set_fixed_time(NOW_MS)
                page.goto(CONSOLE_URL + "/")
                page.evaluate(SETTLE)
                page.evaluate("(step) => window.__step(step)", {"frame": MANY_FRAME})
                page.evaluate(SETTLE)
                page.focus("textarea.goal-text")
                page.evaluate(SETTLE)
                page.evaluate("(step) => window.__step(step)",
                              {"input": {"cls": "goal-text", "value": "x" * 2100}})
                page.evaluate(SETTLE)
                page.evaluate("(step) => window.__step(step)", {"click": "goal-send"})
                page.evaluate(SETTLE)
                fail = page.locator(".goal-status .fail")
                self.assertEqual(fail.count(), 1)
                self.assertTrue(fail.is_visible())
                rects = page.evaluate("""() => {
                  const box = (sel) => document.querySelector(sel).getBoundingClientRect();
                  const f = box(".goal-status .fail"), t = box("textarea.goal-text");
                  return { fail: { top: f.top, bottom: f.bottom, width: f.width,
                                   height: f.height }, textBottom: t.bottom,
                           inner: innerHeight };
                }""")
                page.close()
                f = rects["fail"]
                self.assertGreater(f["width"], 0)
                self.assertGreater(f["height"], 0)
                self.assertGreaterEqual(f["top"], 0)
                self.assertLessEqual(f["bottom"], rects["inner"])
                gap = f["top"] - rects["textBottom"]
                self.assertTrue(0 <= gap <= 80, f"refusal starts {gap}px below the field")
                self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
