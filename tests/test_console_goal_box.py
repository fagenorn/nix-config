"""The goal box's refusal sits under the field and survives closing the box (#1214)."""

import json
import re
import unittest

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_controls import CONSOLE_URL, PAGE_STUBS, SETTLE, served
from .test_console_page import (
    FILLED, GOAL_ASK_FRAME, GOAL_FRAME, NOW_MS, PAGE, START, box_open, full, goal_fail, goal_named,
    goals, has_class, nodes, render, style_rules)

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


def count_of(snap: dict) -> dict:
    """The single goal-count node of a snapshot."""
    (node,) = goal_named(snap, "goal-count")
    return node


def typed(text: str) -> list:
    return [START, {"frame": GOAL_FRAME}, {"key": "g"},
            {"input": {"cls": "goal-text", "value": text}}]


class GoalCountTest(unittest.TestCase):
    def test_the_count_sits_under_the_field(self):
        (snap,) = render([START, {"frame": GOAL_FRAME}, {"key": "g"}, {"snapshot": True}])
        self.assertEqual([c.split()[0] for c in box_children(snap)][:3],
                         ["goal-count", "goal-status", "goal-filter"])

    def test_the_count_reads_quiet_near_and_over(self):
        cases = (
            (0, {"goal-count"}, "0 / 2000"),
            (1800, {"goal-count"}, "1800 / 2000"),
            (1801, {"goal-count", "near"}, "1801 / 2000, 199 left"),
            (2000, {"goal-count", "near"}, "2000 / 2000, 0 left"),
            (2001, {"goal-count", "over"}, "2001 / 2000, 1 over the limit"),
        )
        steps = [START, {"frame": GOAL_FRAME}, {"key": "g"}]
        for n, _, _ in cases:
            steps += [{"input": {"cls": "goal-text", "value": "x" * n}}, {"snapshot": True}]
        snaps = render(steps)
        for (n, classes, text), snap in zip(cases, snaps, strict=True):
            with self.subTest(n=n):
                self.assertEqual(set(count_of(snap)["cls"].split()), classes)
                self.assertEqual(full(count_of(snap)), text)

    def test_the_count_matches_the_services_count(self):
        texts = (
            "  " + "\u00e9" * 5 + "  ",
            "\n\t make it resumable \u3000",
            "\u00a0na\u00efve caf\u00e9\u00a0",
            "e\u0301" * 3,
            "\U0001F680" * 3,
            " \x1fgoal\x85 ",
            "\ufeffgoal",
            "\U0001F680" * 2001,
        )
        for text in texts:
            with self.subTest(text=text[:12], length=len(text)):
                (snap,) = render(typed(text) + [{"snapshot": True}])
                shown = re.match(r"(\d+) / 2000", full(count_of(snap)))
                self.assertEqual(int(shown[1]), len(text.strip()))

    def test_make_it_a_goal_recounts_a_box_that_is_already_open(self):
        (snap,) = render([
            START, {"frame": GOAL_ASK_FRAME}, {"key": "g"},
            {"input": {"cls": "goal-text", "value": "draft"}},
            {"click": "ask-goal"}, {"snapshot": True}])
        (text,) = goal_named(snap, "goal-text")
        self.assertEqual(text["value"], FILLED)
        self.assertEqual(full(count_of(snap)), f"{len(FILLED)} / 2000")

    def test_the_page_refuses_exactly_what_the_service_refuses(self):
        kept = "\x1f" + "x" * 2000 + "\x1f"
        (snap,) = render(typed(kept) + [{"click": "goal-send"}, {"snapshot": True}])
        self.assertEqual(goal_fail(snap), [])
        (post,) = goals(snap)
        self.assertEqual(json.loads(post["body"])["goal"], kept)
        for label, text in (("refused", "\U0001F680" * 2001), ("refused at the edge", "x" * 2001)):
            with self.subTest(label):
                (snap,) = render(typed(text) + [{"click": "goal-send"}, {"snapshot": True}])
                self.assertEqual(goal_fail(snap), [TOO_LONG_LINE])
                self.assertEqual(goals(snap), [])
        with self.subTest("posted at the edge"):
            (snap,) = render(typed("x" * 2000 + "   ") + [{"click": "goal-send"}, {"snapshot": True}])
            self.assertEqual(goal_fail(snap), [])
            self.assertEqual(len(goals(snap)), 1)

    def test_the_count_follows_each_edit(self):
        snaps = render([
            START, {"frame": GOAL_FRAME}, {"key": "g"},
            {"input": {"cls": "goal-text", "value": "abc"}}, {"snapshot": True},
            {"input": {"cls": "goal-text", "value": "abcdef"}}, {"snapshot": True},
            {"frame": GOAL_FRAME}, {"snapshot": True},
            {"key": "Escape"}, {"key": "g"}, {"snapshot": True},
        ])
        self.assertEqual([full(count_of(s)) for s in snaps],
                         ["3 / 2000", "6 / 2000", "6 / 2000", "6 / 2000"])

    def test_the_count_marks_near_and_over_in_its_style(self):
        page = PAGE.read_text()
        style = page[page.index("<style>"):page.index("</style>")]
        rules = {}
        for selector, decls in style_rules(style[:style.index("@media")]):
            rules.setdefault(selector, {}).update(decls)
        self.assertEqual(rules[".goal-count"]["color"], "var(--ov2)")
        self.assertEqual(rules[".goal-count.near"]["color"], "var(--text)")
        self.assertEqual(rules[".goal-count.over"]["color"], "var(--red)")
        self.assertEqual(rules[".goal-count.over"]["font-weight"], "600")
        for selector, decls in rules.items():
            if selector.startswith(".goal-count"):
                for prop in ("width", "min-width", "flex-basis", "white-space"):
                    self.assertNotIn(prop, decls, selector)

    def test_an_over_long_paste_reads_over_and_send_refuses(self):
        pasted, sent = render(typed("x" * 2100) + [
            {"snapshot": True}, {"click": "goal-send"}, {"snapshot": True}])
        self.assertEqual(full(count_of(pasted)), "2100 / 2000, 100 over the limit")
        self.assertIn("over", count_of(pasted)["cls"].split())
        self.assertEqual(goal_fail(sent), [TOO_LONG_LINE])
        self.assertEqual(goals(sent), [])
        (text,) = goal_named(sent, "goal-text")
        self.assertEqual(text["value"], "x" * 2100)
        self.assertTrue(box_open(sent))


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
