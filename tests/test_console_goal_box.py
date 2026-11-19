"""The goal box's count, its over-the-limit Send and its refusal that survives closing the box (#1214)."""

import json
import re
import unittest

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_controls import CONSOLE_URL, PAGE_STUBS, SETTLE, served
from .test_console_page import (
    FILLED, GOAL_ASK_FRAME, GOAL_FRAME, NOW_MS, START, box_open, full, goal_fail, goal_named,
    goals, has_class, nodes, render)

MANY_FRAME = {**GOAL_FRAME, "recent_projects": [f"owner/project-{i:02d}" for i in range(25)]}


def box_children(snap: dict) -> list[str]:
    """The `cls` of each direct child of the single goal-box node, in order."""
    (box,) = goal_named(snap, "goal-box")
    return [child["cls"] for child in box["children"]]


REFUSED = {"status": 409, "text": "this project is not registered\n"}
REFUSED_LINE = "Could not send: this project is not registered"


class GoalRefusalTest(unittest.TestCase):
    def test_a_refusal_survives_closing_and_reopening_the_box(self):
        closes = ({"key": "Escape"}, {"click": "goal-cancel"})
        for close in closes:
            with self.subTest(close=close):
                refused, closed, reopened, edited = render([
                    START, {"frame": GOAL_FRAME}, {"key": "g"},
                    {"input": {"cls": "goal-text", "value": "make it resumable"}},
                    {"respond": REFUSED}, {"click": "goal-send"}, {"snapshot": True},
                    close, {"snapshot": True},
                    {"key": "g"}, {"snapshot": True},
                    {"input": {"cls": "goal-text", "value": "make it fast"}}, {"snapshot": True},
                ])
                self.assertEqual(goal_fail(refused), [REFUSED_LINE])
                self.assertIs(box_open(closed), False)
                self.assertEqual(goal_fail(reopened), [REFUSED_LINE])
                (text,) = goal_named(reopened, "goal-text")
                self.assertEqual(text["value"], "make it resumable")
                self.assertEqual(goal_fail(edited), [])

    def test_the_refusal_sits_above_the_project_choice(self):
        (snap,) = render([
            START, {"frame": GOAL_FRAME}, {"key": "g"},
            {"input": {"cls": "goal-text", "value": "make it resumable"}},
            {"respond": REFUSED}, {"click": "goal-send"}, {"snapshot": True},
        ])
        kids = [cls.split() for cls in box_children(snap)]
        status = next(i for i, c in enumerate(kids) if "goal-status" in c)
        choice = next(i for i, c in enumerate(kids) if "goal-filter" in c)
        self.assertLess(status, choice)
        (box,) = goal_named(snap, "goal-box")
        held = box["children"][status]
        (fail,) = [n for n in nodes(held) if has_class(n, "fail")]
        self.assertEqual(full(fail), REFUSED_LINE)


def count_of(snap: dict) -> dict:
    """The single goal-count node of a snapshot."""
    (node,) = goal_named(snap, "goal-count")
    return node


def hint_of(snap: dict) -> str:
    (node,) = goal_named(snap, "goal-hint")
    return full(node)


def send_of(snap: dict) -> dict:
    (node,) = goal_named(snap, "goal-send")
    return node


def typed(text: str) -> list:
    return [START, {"frame": GOAL_FRAME}, {"key": "g"},
            {"input": {"cls": "goal-text", "value": text}}]


class GoalCountTest(unittest.TestCase):
    def test_the_count_sits_in_the_field_and_the_box_has_no_count_line(self):
        (snap,) = render([START, {"frame": GOAL_FRAME}, {"key": "g"}, {"snapshot": True}])
        (field,) = goal_named(snap, "goal-in")
        self.assertIn("goal-count", [c["cls"].split()[0] for c in field["children"]])
        (box,) = goal_named(snap, "goal-box")
        self.assertEqual([c.split()[0] for c in box_children(snap)],
                         ["goal-status", "goal-filter", "goal-projects", "goal-act"])
        self.assertEqual([n for n in nodes(box) if has_class(n, "goal-count")], [])

    def test_the_count_stays_silent_until_near_the_limit_then_changes_tone_over_it(self):
        cases = (
            (0, {"goal-count"}, ""),
            (1800, {"goal-count"}, ""),
            (1801, {"goal-count"}, "1801 / 2000"),
            (2000, {"goal-count"}, "2000 / 2000"),
            (2001, {"goal-count", "over"}, "2001 / 2000"),
        )
        steps = [START, {"frame": GOAL_FRAME}, {"key": "g"}]
        for n, _, _ in cases:
            steps += [{"input": {"cls": "goal-text", "value": "x" * n}}, {"snapshot": True}]
        snaps = render(steps)
        for (n, classes, text), snap in zip(cases, snaps, strict=True):
            with self.subTest(n=n):
                self.assertEqual(set(count_of(snap)["cls"].split()), classes)
                self.assertEqual(full(count_of(snap)), text)

    def test_over_the_limit_send_is_unavailable_and_one_hint_says_how_much_to_cut(self):
        cases = ((1900, "", None), (2000, "", None), (2001, "Cut 1 character to send", "true"),
                 (2100, "Cut 100 characters to send", "true"))
        steps = [START, {"frame": GOAL_FRAME}, {"key": "g"}]
        for n, _, _ in cases:
            steps += [{"input": {"cls": "goal-text", "value": "x" * n}}, {"snapshot": True}]
        for (n, hint, unavailable), snap in zip(cases, render(steps), strict=True):
            with self.subTest(n=n):
                self.assertEqual(hint_of(snap), hint)
                self.assertEqual(send_of(snap)["aria_disabled"], unavailable)
                self.assertIs(send_of(snap)["disabled"], False)
                self.assertEqual(goal_fail(snap), [])

    def test_the_count_matches_the_services_count(self):
        texts = (
            "  " + "\u00e9" * 1900 + "  ",
            "\n\t " + "x" * 1900 + " \u3000",
            "\u00a0" + "na\u00efve " * 301 + "\u00a0",
            "e\u0301" * 1900,
            "\U0001F680" * 1900,
            " \x1f" + "g" * 1900 + "\x85 ",
            "\ufeff" + "g" * 1900,
            "\U0001F680" * 2001,
        )
        for text in texts:
            with self.subTest(text=text.strip()[:6], length=len(text)):
                (snap,) = render(typed(text) + [{"snapshot": True}])
                shown = re.match(r"(\d+) / 2000", full(count_of(snap)))
                self.assertEqual(int(shown[1]), len(text.strip()))

    def test_make_it_a_goal_recounts_a_box_that_is_already_open(self):
        text = "w" * 1900
        (snap,) = render([
            START, {"frame": GOAL_ASK_FRAME}, {"click": "thread-open"}, {"key": "g"},
            {"input": {"cls": "goal-text", "value": text}},
            {"click": "ask-goal"}, {"snapshot": True}])
        (field,) = goal_named(snap, "goal-text")
        self.assertEqual(field["value"], FILLED)
        self.assertEqual(full(count_of(snap)), "")

    def test_the_page_never_sends_what_the_service_refuses_and_says_nothing_red(self):
        kept = "\x1f" + "x" * 2000 + "\x1f"
        (snap,) = render(typed(kept) + [{"click": "goal-send"}, {"snapshot": True}])
        self.assertEqual(goal_fail(snap), [])
        (post,) = goals(snap)
        self.assertEqual(json.loads(post["body"])["goal"], kept)
        for label, text in (("emoji", "\U0001F680" * 2001), ("edge", "x" * 2001)):
            with self.subTest(label):
                (snap,) = render(typed(text) + [{"click": "goal-send"}, {"snapshot": True}])
                self.assertEqual(goal_fail(snap), [])
                self.assertEqual(goals(snap), [])
                self.assertEqual(hint_of(snap), "Cut 1 character to send")
                (box,) = goal_named(snap, "goal-box")
                self.assertEqual([n for n in nodes(box) if has_class(n, "fail")], [])
        with self.subTest("posted at the edge"):
            (snap,) = render(typed("x" * 2000 + "   ") + [{"click": "goal-send"}, {"snapshot": True}])
            self.assertEqual(goal_fail(snap), [])
            self.assertEqual(len(goals(snap)), 1)

    def test_the_count_follows_each_edit_and_a_sent_goal_clears_it(self):
        snaps = render([
            START, {"frame": GOAL_FRAME}, {"key": "g"},
            {"input": {"cls": "goal-text", "value": "x" * 1900}}, {"snapshot": True},
            {"input": {"cls": "goal-text", "value": "x" * 2100}}, {"snapshot": True},
            {"input": {"cls": "goal-text", "value": "x" * 1950}}, {"snapshot": True},
            {"frame": GOAL_FRAME}, {"snapshot": True},
            {"key": "Escape"}, {"key": "g"}, {"snapshot": True},
            {"click": "goal-send"}, {"snapshot": True},
        ])
        self.assertEqual([full(count_of(s)) for s in snaps],
                         ["1900 / 2000", "2100 / 2000", "1950 / 2000", "1950 / 2000",
                          "1950 / 2000", ""])
        self.assertEqual([send_of(s)["aria_disabled"] for s in snaps[:5]],
                         [None, "true", None, None, None])
        self.assertIs(box_open(snaps[5]), False)

    def test_an_over_long_paste_keeps_the_text_and_the_box(self):
        pasted, sent = render(typed("x" * 2100) + [
            {"snapshot": True}, {"click": "goal-send"}, {"snapshot": True}])
        self.assertEqual(full(count_of(pasted)), "2100 / 2000")
        self.assertIn("over", count_of(pasted)["cls"].split())
        self.assertEqual(goal_fail(sent), [])
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

    def test_a_refusal_is_on_screen_in_the_box_and_again_after_a_reopen(self):
        browser = self.chromium()
        measure = """() => {
          const box = document.querySelector(".goal-box");
          const fail = document.querySelector(".goal-box .goal-status .fail");
          if (box === null || fail === null) return { box: box !== null, fail: false };
          const b = box.getBoundingClientRect(), f = fail.getBoundingClientRect();
          const hit = document.elementFromPoint(f.left + f.width / 2, f.top + f.height / 2);
          return { box: true, fail: true, text: fail.textContent.trim(),
                   shown: fail.getClientRects().length > 0 && f.width > 0 && f.height > 0
                          && getComputedStyle(fail).visibility !== "hidden",
                   inBox: f.top >= b.top && f.bottom <= b.bottom && f.left >= b.left && f.right <= b.right,
                   inViewport: f.top >= 0 && f.bottom <= innerHeight && f.left >= 0 && f.right <= innerWidth,
                   topmost: hit !== null && (hit === fail || fail.contains(hit)),
                   value: document.querySelector("textarea.goal-text").value };
        }"""
        step = "(step) => window.__step(step)"
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
                page.evaluate(step, {"frame": MANY_FRAME})
                page.evaluate(SETTLE)
                page.focus("textarea.goal-text")
                page.evaluate(SETTLE)
                for move in ({"input": {"cls": "goal-text", "value": "make it resumable"}},
                             {"respond": REFUSED}, {"click": "goal-send"}):
                    page.evaluate(step, move)
                    page.evaluate(SETTLE)
                refused = page.evaluate(measure)
                page.evaluate(step, {"key": "Escape"})
                page.evaluate(SETTLE)
                page.evaluate(step, {"key": "g"})
                page.evaluate(SETTLE)
                reopened = page.evaluate(measure)
                page.close()
                for label, state in (("refused", refused), ("reopened", reopened)):
                    with self.subTest(label):
                        self.assertEqual(state["text"], REFUSED_LINE)
                        for check in ("shown", "inBox", "inViewport", "topmost"):
                            self.assertTrue(state[check], check)
                        self.assertEqual(state["value"], "make it resumable")
                self.assertEqual(errors, [])

    def test_over_the_limit_nothing_moves_and_the_hint_sits_beside_send(self):
        browser = self.chromium()
        measure = """() => {
          const r = (sel) => { const b = document.querySelector(sel).getBoundingClientRect();
            return { left: b.left, right: b.right, top: b.top, bottom: b.bottom,
                     width: b.width, height: b.height }; };
          const shown = (sel) => { const n = document.querySelector(sel);
            return n.getClientRects().length > 0 && getComputedStyle(n).visibility !== "hidden"; };
          return { box: r(".goal-box"), field: r(".goal-in"), text: r("textarea.goal-text"),
                   send: r("button.goal-send"), hint: r(".goal-hint"), count: r(".goal-count"),
                   countShown: shown(".goal-count"), fails: document.querySelectorAll(".goal-box .fail").length,
                   color: getComputedStyle(document.querySelector(".goal-count")).color,
                   sendAria: document.querySelector("button.goal-send").getAttribute("aria-disabled"),
                   value: document.querySelector("textarea.goal-text").value.length,
                   scroll: document.documentElement.scrollWidth, inner: innerWidth };
        }"""
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
                seen = {}
                for n in (1800, 1900, 2100):
                    page.evaluate("(step) => window.__step(step)",
                                  {"input": {"cls": "goal-text", "value": "x" * n}})
                    page.evaluate(SETTLE)
                    seen[n] = page.evaluate(measure)
                page.evaluate("(step) => window.__step(step)", {"click": "goal-send"})
                page.evaluate(SETTLE)
                after = page.evaluate(measure)
                page.close()
                quiet, near, over = seen[1800], seen[1900], seen[2100]
                self.assertFalse(quiet["countShown"] and quiet["count"]["width"] > 0)
                for state in (near, over):
                    for part in ("box", "field", "text", "send"):
                        self.assertEqual(state[part], quiet[part], part)
                    self.assertEqual(state["scroll"], state["inner"])
                c, f, t = over["count"], over["field"], over["text"]
                self.assertTrue(over["countShown"])
                self.assertLessEqual(c["right"], f["right"])
                self.assertLessEqual(c["bottom"], f["bottom"])
                self.assertGreaterEqual(c["top"], t["bottom"])
                self.assertNotEqual(over["color"], near["color"])
                self.assertEqual(near["sendAria"], None)
                self.assertEqual(over["sendAria"], "true")
                h, s = over["hint"], over["send"]
                self.assertGreater(h["width"], 0)
                self.assertGreaterEqual(h["left"], s["right"])
                self.assertLess(abs((h["top"] + h["bottom"]) / 2 - (s["top"] + s["bottom"]) / 2), 4)
                self.assertLessEqual(h["right"], over["box"]["right"])
                self.assertEqual(over["fails"], 0)
                self.assertEqual(after["fails"], 0)
                self.assertEqual(after["value"], 2100)
                self.assertEqual(after["box"], over["box"])
                self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
