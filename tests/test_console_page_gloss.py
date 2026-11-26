"""The console page marks a flagged glossary word and shows its gloss on hover and on tap.

Run: just agent-workflow-tests
"""
import json
import unittest
from pathlib import Path

from agent_tools.console import owner_words

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_guest_page import GUEST, harness
from .test_console_page import (
    HEADSUP_W, PROGRESS, REPORTED, SPRINT, START, PageNoticeTest, frame, full, has_class, nodes, of_class,
    project, question, render, sprint_lines, view, with_notices, with_sprints)

TIER = "fast"

CASES = Path(__file__).resolve().parent / "fixtures/console/owner-words-cases.json"
GLOSS = owner_words.entries()
G = dict(owner_words.GLOSSARY)


def marks(node: dict) -> list:
    return [n for n in nodes(node) if has_class(n, "gloss")]


def texts(node: dict) -> list:
    return [full(n) for n in marks(node)]


def f(status: str) -> dict:
    return {**with_sprints([{**REPORTED, "status": status}]), "glossary": GLOSS}


def status_line(snap: dict) -> dict:
    (line,) = sprint_lines(snap)
    (status,) = of_class(line, "p", "report-status")
    return status


def gloss_texts(snap: dict) -> list:
    return [n for n in nodes(snap["projects"]) if has_class(n, "gloss-text")]


class PageGlossTest(unittest.TestCase):
    def test_a_flagged_word_in_the_status_line_shows_its_gloss_on_hover_and_tap(self) -> None:
        before, after = render([
            START, {"frame": f("waiting on the land lock")}, {"snapshot": True}, {"click": "gloss"},
            {"snapshot": True}])
        status = status_line(before)
        self.assertEqual(full(status), "waiting on the land lock")
        (mark,) = marks(status)
        self.assertEqual(mark["tag"], "button")
        self.assertEqual(full(mark), "land lock")
        self.assertEqual(mark["title"], G["land lock"])
        self.assertEqual(mark["expanded"], "false")
        self.assertEqual(gloss_texts(before), [])
        status = status_line(after)
        (mark,) = marks(status)
        self.assertEqual(mark["expanded"], "true")
        kids = status["children"]
        shown = kids[kids.index(mark) + 1]
        self.assertTrue(has_class(shown, "gloss-text"))
        self.assertEqual(shown["tag"], "span")
        self.assertEqual(full(shown), " (" + G["land lock"] + ")")

    def test_a_second_tap_closes_the_gloss(self) -> None:
        (snap,) = render([
            START, {"frame": f("waiting on the land lock")}, {"click": "gloss"}, {"click": "gloss"},
            {"snapshot": True}])
        (mark,) = marks(status_line(snap))
        self.assertEqual(mark["expanded"], "false")
        self.assertEqual(gloss_texts(snap), [])

    def test_an_open_gloss_stays_open_across_an_unchanged_redraw(self) -> None:
        (snap,) = render([
            START, {"frame": f("waiting on the land lock")}, {"click": "gloss"},
            {"frame": f("waiting on the land lock")}, {"snapshot": True}])
        (mark,) = marks(status_line(snap))
        self.assertEqual(mark["expanded"], "true")
        self.assertEqual(len(gloss_texts(snap)), 1)

    def test_a_replacement_report_with_another_word_at_the_same_place_starts_closed(self) -> None:
        (snap,) = render([
            START, {"frame": f("guard said no")}, {"click": "gloss"}, {"frame": f("rerun said no")},
            {"snapshot": True}])
        (mark,) = marks(status_line(snap))
        self.assertEqual(full(mark), "rerun")
        self.assertEqual(mark["expanded"], "false")
        self.assertEqual(gloss_texts(snap), [])

    def test_the_page_marks_the_shared_cases_as_python_flags_them(self) -> None:
        cases = json.loads(CASES.read_text(encoding="utf-8"))
        sprints = [{**REPORTED, "sprint_id": f"s{i}", "title": f"Case {i}", "status": case["text"]}
                   for i, case in enumerate(cases)]
        (snap,) = render([START, {"frame": {**with_sprints(sprints), "glossary": GLOSS}},
                          {"snapshot": True}])
        lines = {n["key"]: n for n in nodes(snap["projects"]) if n["key"] and n["key"].startswith("sprint:")}
        for i, case in enumerate(cases):
            with self.subTest(text=case["text"]):
                (status,) = [s for s in nodes(lines["sprint:s%d" % i]) if has_class(s, "report-status")]
                shown = []
                for text in texts(status):
                    flat = " ".join(text.split()).lower()
                    shown += [w for w, _ in owner_words.GLOSSARY if " ".join(w.split()).lower() == flat]
                self.assertEqual([w for w, _ in owner_words.GLOSSARY if w in shown], case["flagged"])
                self.assertEqual(full(status), case["text"])

    def test_a_glossed_or_inflected_word_is_not_marked(self) -> None:
        text = "two slices wait on the land lock (" + G["land lock"] + ")"
        (snap,) = render([START, {"frame": f(text)}, {"snapshot": True}])
        status = status_line(snap)
        self.assertEqual(marks(status), [])
        self.assertEqual(full(status), text)

    def test_a_question_marks_its_ask_and_context_and_glosses_an_option_beside_it(self) -> None:
        item = question(0, "May I rerun the check?", ["Wait", "Ask the CI"], "Wait",
                        context="The land lock is held by another sprint.")
        qf = {**frame([item]), "glossary": GLOSS}
        (snap,) = render([START, {"frame": qf}, {"snapshot": True}])
        tree = snap["inbox"]
        (headline,) = [n for n in nodes(tree) if n["tag"] == "h2" and has_class(n, "q")]
        (mark,) = marks(headline)
        self.assertEqual(full(mark), "rerun")
        self.assertEqual(mark["title"], G["rerun"])
        self.assertEqual(full(headline), "May I rerun the check?")
        (context,) = of_class(tree, "p", "context")
        self.assertEqual(texts(context), ["land lock", "held"])
        buttons = [n for n in nodes(tree) if n["tag"] == "button" and has_class(n, "opt")]
        self.assertEqual([marks(b) for b in buttons], [[], []])
        (row,) = [n for n in nodes(tree) if n["tag"] == "li" and "Ask the CI" in full(n)]
        (box,) = [n for n in nodes(row) if has_class(n, "opt-glosses")]
        (ci,) = marks(box)
        self.assertEqual(full(ci), "CI")
        self.assertEqual(ci["title"], G["CI"])
        every = marks(tree)
        opened, sent = render([
            START, {"frame": qf}, {"click": "opt", "nth": 1}, {"click": "gloss", "nth": every.index(ci)},
            {"snapshot": True}, {"respond": {"status": 204, "text": ""}}, {"click": "send"},
            {"clock": 5000}, {"snapshot": True}])
        (shown,) = [n for n in nodes(opened["inbox"]) if has_class(n, "gloss-text")]
        self.assertEqual(full(shown), " (" + G["CI"] + ")")
        (post,) = [p for p in sent["posts"] if p["url"] == "/api/round-answer"]
        self.assertEqual(json.loads(post["body"])["choice"], item["questions"][0]["options"].index("Ask the CI"))

    def test_each_ask_of_a_several_question_card_is_marked(self) -> None:
        item = question(0, "May I rerun the check?", ["yes", "no"], "yes")
        item["questions"] = [
            item["questions"][0],
            {"question": "Is the guard right?", "options": ["yes", "no"], "chosen": None,
             "recommended": None, "recommended_index": None}]
        (snap,) = render([START, {"frame": {**frame([item]), "glossary": GLOSS}}, {"snapshot": True}])
        (abox,) = of_class(snap["inbox"], "div", "abox")
        self.assertEqual([texts(n) for n in of_class(abox, "p", "meta")], [["rerun"], ["guard"]])

    def test_a_question_on_the_sprint_line_marks_its_flagged_word(self) -> None:
        now = "waiting for your answer: May I rerun the check?"
        sprint = {**SPRINT, "now_text": now, "now_until": None}
        (snap,) = render([START, {"frame": {**with_sprints([sprint]), "glossary": GLOSS}},
                          {"snapshot": True}])
        (line,) = sprint_lines(snap)
        (shown,) = of_class(line, "p", "sp-now")
        self.assertEqual(texts(shown), ["rerun"])
        self.assertEqual(full(shown), now)
        self.assertEqual(shown["title"], now)

    def test_a_notice_marks_its_flagged_word(self) -> None:
        p0 = with_notices(project(0, []), {**HEADSUP_W, "text": "the guard refuses a push"})
        (snap,) = render([PageNoticeTest.begin, {"frame": {**view([p0]), "glossary": GLOSS}},
                          {"open": "notices:owner/p00"}, {"snapshot": True}])
        (words,) = of_class(snap["projects"], "p", "notice-words")
        (mark,) = marks(words)
        self.assertEqual(full(mark), "guard")
        self.assertEqual(mark["title"], G["guard"])
        self.assertEqual(full(words), "the guard refuses a push")

    def test_the_progress_card_marks_its_last_status(self) -> None:
        card = {**PROGRESS, "last_status": "waiting on the land lock"}
        (snap,) = render([START, {"frame": {**frame([card]), "glossary": GLOSS}}, {"snapshot": True}])
        (reason,) = [n for n in nodes(snap["inbox"]) if n["tag"] == "span" and has_class(n, "reason")]
        self.assertEqual(texts(reason), ["land lock"])

    def test_the_guest_page_keeps_the_mark_and_its_gloss(self) -> None:
        first, second = harness([
            START, {"frame": f("waiting on the land lock")}, {"snapshot": True}, {"click": "gloss"},
            {"snapshot": True}], GUEST)
        status = status_line(first)
        self.assertEqual(full(status), "waiting on the land lock")
        self.assertEqual(texts(status), ["land lock"])
        self.assertEqual(len(gloss_texts(second)), 1)
        self.assertEqual(second["posts"], [])


if __name__ == "__main__":
    unittest.main()
