"""The sprint screenshot set against a fixture console (#1086).

Run: just agent-workflow-tests
"""
import dataclasses
import http.client
import json
import os
import pwd
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent_tools.console import service

from . import accounts_sandbox
from . import console_screenshots as shots
from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)


def fixture_paths(fixture):
    paths = [value for field in dataclasses.fields(fixture) if field.name not in ("holding", "deaf", "activating")
             for value in ([getattr(fixture, field.name)] if field.name != "projects"
                           else list(fixture.projects))]
    return paths


def entries_of(view):
    for entry in view["entries"]:
        yield from (entry["projects"] if entry["type"] == "quiet_group" else [entry])


def all_sprints(view):
    found = []
    for project in entries_of(view):
        found.extend(project.get("sprints") or [])
        found.extend((project.get("finished_sprints") or {"sprints": []})["sprints"])
    return found


def fake_browser(present):
    class Page:
        def __init__(self):
            self.clicks = []
            self.waits = []
            self.reads = 0
            self.card = ()
            self.fills = []

        def goto(self, url):
            pass

        def wait_for_selector(self, selector):
            self.waits.append(selector)

        def query_selector(self, selector):
            return object() if selector in present else None

        def click(self, selector):
            self.clicks.append(selector)

        def fill(self, selector, text):
            self.fills.append((selector, text))

        def evaluate(self, expression, arg=None):
            if expression == shots.ASK_READING:
                self.reads += 1
                return list(shots.HEAD_ASK if shots.READING_PANEL in present else shots.OPEN_ASK)
            if expression == shots.READ_READING:
                self.reads += 1
                self.counted = arg
                return list(shots.READ_SHOWN)
            if expression == shots.THREAD_READING:
                self.reads += 1
                return list(shots.OPEN_THREAD if shots.ASK_FOLD in present else shots.BASE_THREAD)
            if expression == shots.GOAL_READING:
                self.reads += 1
                return list(shots.FILLED_GOAL)
            if expression == shots.ACTIVATION_READING:
                self.reads += 1
                return list(shots.ACTIVATION_SHOWN["activation-tooling"])
            if expression == shots.CARD_READING:
                self.reads += 1
                return list(self.card)
            if expression == shots.ACTS_ROW:
                return []
            if expression == shots.SCROLL_Y:
                return 0.0
            if expression == "document.documentElement.scrollWidth":
                return 480
            if expression == shots.SHORT_CONTROLS:
                return []
            return 0

        def screenshot(self, path, full_page):
            pass

        def close(self):
            pass

    page = Page()

    class Browser:
        def new_page(self, viewport):
            return page

    return Browser(), page


class ScreenshotFixtureTest(unittest.TestCase):
    def test_the_set_is_thirty_nine_states_at_two_widths(self) -> None:
        self.assertEqual(len(shots.STATES), 39)
        self.assertEqual(shots.STATES[-4:], ("sharing-panel", "sharing-off", "sharing-unreadable",
                                             "guest-page"))
        self.assertEqual(shots.STATES.index("manager-cannot-hear"),
                         shots.STATES.index("waiting-its-turn") + 1)
        self.assertEqual(shots.STATES[shots.STATES.index("inbox-card"):][:3],
                         ("inbox-card", "question-words", "question-refused"))
        self.assertEqual(shots.STATES.index("waiting-its-turn"),
                         shots.STATES.index("nothing-running") + 1)
        self.assertEqual(shots.STATES.index("failed-start"),
                         shots.STATES.index("desk-spend") + 1)
        self.assertEqual(shots.STATES[-21:-4], ("goal-open", "goal-near", "goal-over", "inbox-card",
                                              "question-words", "question-refused",
                                              "look-card", "look-moved", "look-failed",
                                              "accounts-panel", "ask-box", "questions-closed",
                                              "questions-open", "ask-goal", "question-read",
                                              "activation-tooling", "activation-host"))
        self.assertEqual(shots.STATES.index("tell-box-open"), shots.STATES.index("stuck") + 1)
        self.assertEqual(shots.WIDTHS, (1440, 480))

    def test_the_contract_docstring_counts_the_screens_and_files_the_set_writes(self) -> None:
        words = {20: "twenty", 21: "twenty-one", 22: "twenty-two", 23: "twenty-three",
                 24: "twenty-four", 25: "twenty-five", 26: "twenty-six",
                 27: "twenty-seven", 28: "twenty-eight", 29: "twenty-nine", 30: "thirty",
                 31: "thirty-one", 32: "thirty-two", 33: "thirty-three", 34: "thirty-four",
                 35: "thirty-five", 36: "thirty-six", 37: "thirty-seven",
                 38: "thirty-eight", 39: "thirty-nine"}
        files = len(shots.STATES) * len(shots.WIDTHS)
        doc = " ".join(shots.__doc__.split())
        self.assertIn(f"`STATES` names the {words[len(shots.STATES)]} screens", doc)
        self.assertIn(f"a full run writes {files} files", doc)

    def test_the_recipe_help_counts_the_files_a_full_run_writes(self) -> None:
        justfile = (Path(__file__).resolve().parent.parent / "justfile").read_text()
        count = len(shots.STATES) * len(shots.WIDTHS)
        self.assertIn(f"sprint states against a fixture console, {count} PNGs into out", justfile)

    def test_a_shot_with_jargon_or_a_clamped_sentence_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        code, text = run(lambda path: shots.Shot("stuck", 480, path, 480, 0, 1))
        self.assertEqual(code, 1)
        self.assertIn("jargon label", text)
        code, text = run(lambda path: shots.Shot("stuck", 480, path, 480, 1, 0))
        self.assertEqual(code, 1)
        self.assertIn("squeezes the now sentence", text)
        code, text = run(lambda path: shots.Shot("tell-box-open", 480, path, 480, 0, 0,
                                                 (False, None, None)))
        self.assertEqual(code, 1)
        self.assertIn("does not show the open Tell box", text)
        code, text = run(lambda path: shots.Shot("tell-box-open", 480, path, 480, 0, 0,
                                                 shots.OPEN_TELL))
        self.assertEqual(code, 0)

    def test_an_ask_box_shot_without_the_open_box_and_its_questions_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        phrase = "does not show the open Ask box"
        for ask in ((False, None, None), (True, None, shots.ASK_READ_LINE),
                    (True, "Working on it", None)):
            with self.subTest(ask=ask):
                code, text = run(lambda path: shots.Shot("ask-box", 480, path, 480, ask=ask))
                self.assertEqual(code, 1)
                self.assertIn(phrase, text)
        code, text = run(lambda path: shots.Shot("ask-box", 480, path, 480, ask=shots.OPEN_ASK))
        self.assertEqual(code, 0)
        code, text = run(lambda path: shots.Shot("ask-box", 480, path, 480, ask=shots.HEAD_ASK))
        self.assertEqual(code, 0)
        code, text = run(lambda path: shots.Shot("ask-box", 480, path, 480, ask=None))
        self.assertEqual(code, 0)
        self.assertNotIn(phrase, text)
        code, text = run(lambda path: shots.Shot("live-several", 480, path, 480,
                                                 ask=(False, None, None)))
        self.assertEqual(code, 0)

    def test_the_ask_box_shot_opens_owner_webs_box_only_on_a_page_that_has_one(self) -> None:
        field = 'li.asks[data-project="owner/web"] textarea.ask-text'

        panel = {shots.ASK_OPEN, shots.ASK_FOLD, shots.READING_PANEL}
        through_panel = [shots.ASK_OPEN, shots.ASK_FOLD, shots.thread_line("1177a1")]
        head = {shots.ASK_OPEN, shots.ASK_FOLD}
        opened = [shots.ASK_OPEN, shots.ASK_FOLD, *shots.ASK_THREADS]
        cases = (("head with the reading panel", "ask-box", panel, through_panel, shots.HEAD_ASK),
                 ("head", "ask-box", head | {"li.asks"}, opened, shots.OPEN_ASK),
                 # The page of #1178: the line holds the button and no li.asks exists until the box opens.
                 ("head, no Ask block before opening", "ask-box", head, opened, shots.OPEN_ASK),
                 # The page of #1177: li.asks holds the button and there is no fold.
                 ("base", "ask-box", {shots.ASK_OPEN, "li.asks"}, [shots.ASK_OPEN], shots.OPEN_ASK),
                 ("no Ask control", "ask-box", set(), [], None),
                 ("other state", "live-several", head, [], None))
        for name, state, present, clicks, ask in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                shot = shots._shoot(browser, "http://console.test/", state, 480, Path(tmp))
                self.assertEqual(page.clicks, clicks)
                self.assertEqual(shot.ask, ask)
                self.assertEqual(page.reads, 1 if ask else 0)
                self.assertEqual(field in page.waits, bool(clicks))

    def test_an_activation_shot_without_its_line_and_button_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        self.assertEqual(shots.ACTIVATION_SHOWN, {
            "activation-tooling": (
                "A change to the agent tooling merged at 125812581258 and is not active on this "
                "host.", 1),
            "activation-host": (
                "A change to the host configuration merged at 125812581258 and is not active on "
                "this host.", 1)})
        phrase = "does not show the activation line with its Activate button"
        for state, shown_ in shots.ACTIVATION_SHOWN.items():
            other = next(v for k, v in shots.ACTIVATION_SHOWN.items() if k != state)
            for line in ((None, 1), (shown_[0], 0), (shown_[0], 2), other,
                         ("A console change merged at 125812581258 is not active on this host.", 1)):
                with self.subTest(state=state, line=line):
                    code, text = run(lambda path: shots.Shot(state, 480, path, 480, activation=line))
                    self.assertEqual(code, 1)
                    self.assertIn(phrase, text)
            code, text = run(lambda path: shots.Shot(state, 480, path, 480, activation=shown_))
            self.assertEqual(code, 0)
            self.assertNotIn(phrase, text)
            self.assertEqual(shots.ACTIVATION_BASE, (None, 0))
            self.assertIs(shots.reads_other(), True)
            code, text = run(lambda path: shots.Shot(state, 480, path, 480,
                                                     activation=shots.ACTIVATION_BASE))
            self.assertEqual(code, 1)
            self.assertIn(phrase, text)
            with mock.patch.object(shots, "reads_other", return_value=False):
                code, text = run(lambda path: shots.Shot(state, 480, path, 480,
                                                         activation=shots.ACTIVATION_BASE))
                self.assertEqual(code, 0)
                self.assertNotIn(phrase, text)
                code, text = run(lambda path: shots.Shot(state, 480, path, 480, activation=shown_))
                self.assertEqual(code, 0)
        code, text = run(lambda path: shots.Shot("live-several", 480, path, 480,
                                                 activation=(None, 1)))
        self.assertEqual(code, 0)

    def test_the_activation_shots_read_the_line_only_in_their_own_states(self) -> None:
        for state, reads in (("activation-tooling", 1), ("activation-host", 1), ("live-several", 0)):
            with self.subTest(state), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(set())
                shot = shots._shoot(browser, "http://console.test/", state, 480, Path(tmp))
                self.assertEqual(page.reads, reads)
                self.assertEqual(shot.activation, tuple(
                    shots.ACTIVATION_SHOWN["activation-tooling"]) if reads else None)

    def test_an_ask_goal_shot_without_the_filled_box_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        self.assertIs(shots.FILLED_GOAL[3], True)
        self.assertEqual(shots.FILLED_GOAL[1],
                         shots.ASK_ANSWERED_QUESTION + "\n\n" + shots.ASK_ANSWER_SUMMARY)
        phrase = "does not show the goal box filled from the answer"
        text_ = shots.FILLED_GOAL[1]
        for goal in ((False, None, None, None), (True, "", "owner/web", True),
                     (True, text_, "owner/api", True),
                     (True, text_ + "\nRan: just build", "owner/web", True),
                     (True, text_, "owner/web", False)):
            with self.subTest(goal=goal):
                code, text = run(lambda path: shots.Shot("ask-goal", 480, path, 480, goal=goal))
                self.assertEqual(code, 1)
                self.assertIn(phrase, text)
        for goal in (shots.FILLED_GOAL, None):
            code, text = run(lambda path: shots.Shot("ask-goal", 480, path, 480, goal=goal))
            self.assertEqual(code, 0)
            self.assertNotIn(phrase, text)
        code, text = run(lambda path: shots.Shot("live-several", 480, path, 480,
                                                 goal=(False, None, None, None)))
        self.assertEqual(code, 0)

    def test_the_ask_goal_shot_clicks_make_it_a_goal_only_on_a_page_that_has_it(self) -> None:
        fold = [shots.ASK_FOLD, shots.ASK_THREADS[1]]
        through_panel = [shots.ASK_FOLD, shots.thread_line("1177a1"), "#reading button.ask-goal"]
        cases = (("head with the reading panel", "ask-goal",
                  {shots.READING_PANEL, shots.ASK_FOLD, "#reading button.ask-goal"},
                  through_panel, shots.FILLED_GOAL),
                 ("head", "ask-goal", {shots.ASK_FOLD, shots.ASK_GOAL}, [*fold, shots.ASK_GOAL],
                  shots.FILLED_GOAL),
                 ("base", "ask-goal", {shots.ASK_FOLD}, fold, None),
                 ("no fold", "ask-goal", set(), [], None),
                 ("other state", "live-several", {shots.ASK_FOLD, shots.ASK_GOAL}, [], None))
        for name, state, present, clicks, goal in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                shot = shots._shoot(browser, "http://console.test/", state, 480, Path(tmp))
                self.assertEqual(page.clicks, clicks)
                self.assertEqual(shot.goal, goal)
                self.assertEqual(page.reads, 1 if goal else 0)
                self.assertEqual("#goal .goal-box" in page.waits, goal is not None)

    def test_a_shot_with_ask_off_the_give_goal_row_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        code, text = run(lambda path: shots.Shot("questions-closed", 1440, path, 1440,
                                                 acts=("owner/api",)))
        self.assertEqual(code, 1)
        self.assertIn("puts Ask a question on another row than Give it a goal (owner/api)", text)
        code, text = run(lambda path: shots.Shot("questions-closed", 1440, path, 1440, acts=()))
        self.assertEqual(code, 0)

    def test_a_questions_open_shot_must_show_the_opened_thread(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        phrase = "does not show the opened thread"
        for thread in ((False, None, False), (True, None, True)):
            with self.subTest(thread=thread):
                code, text = run(lambda path: shots.Shot("questions-open", 480, path, 480,
                                                         thread=thread))
                self.assertEqual(code, 1)
                self.assertIn(phrase, text)
        for thread in (shots.OPEN_THREAD, shots.BASE_THREAD, None):
            with self.subTest(thread=thread):
                code, text = run(lambda path: shots.Shot("questions-open", 480, path, 480,
                                                         thread=thread))
                self.assertEqual(code, 0)
                self.assertNotIn(phrase, text)

    def test_the_questions_open_shot_opens_the_fold_only_on_a_page_that_has_it(self) -> None:
        newest = 'details[data-key="thread:owner/web:1178a2"] > summary'
        cases = (("head with the reading panel", {shots.ASK_FOLD, shots.READING_PANEL},
                  [shots.ASK_FOLD, shots.thread_line("1178a2")], shots.OPEN_THREAD),
                 ("head", {shots.ASK_FOLD}, [shots.ASK_FOLD, newest], shots.OPEN_THREAD),
                 ("base", set(), [], shots.BASE_THREAD))
        for name, present, clicks, thread in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                shot = shots._shoot(browser, "http://console.test/", "questions-open", 480,
                                    Path(tmp))
                self.assertEqual(page.clicks, clicks)
                self.assertEqual(shot.thread, thread)
                self.assertEqual(page.reads, 1)
        with tempfile.TemporaryDirectory() as tmp:
            browser, page = fake_browser({shots.ASK_FOLD})
            shot = shots._shoot(browser, "http://console.test/", "questions-closed", 480, Path(tmp))
            self.assertEqual(page.clicks, [])
            self.assertIsNone(shot.thread)
            self.assertEqual(shot.acts, ())

    def test_a_question_card_shot_without_its_pick_and_words_or_its_refusal_fails_the_command(
            self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        phrase = "does not show the question card"
        wrong = {"question-words": ((None, shots.LOOK_WORDS, True, None),
                                    ("Ask for changes", "", True, None),
                                    ("Ask for changes", shots.LOOK_WORDS, False, None),
                                    ("Ask for changes", shots.LOOK_WORDS, True, "Say what to change."),
                                    (None, None, None, None)),
                 "question-refused": (("Ask for changes", "", True, None),
                                      (None, "", True, "Say what to change."),
                                      ("Ask for changes", shots.LOOK_WORDS, True, "Say what to change."),
                                      (None, None, None, None))}
        right = {"question-words": ("Ask for changes", shots.LOOK_WORDS, True, None),
                 "question-refused": ("Ask for changes", "", True, "Say what to change.")}
        for state, readings in wrong.items():
            for card in readings:
                with self.subTest(state=state, card=card):
                    code, text = run(lambda path: shots.Shot(state, 480, path, 480, card=card))
                    self.assertEqual(code, 1)
                    self.assertIn(phrase, text)
            for card in (right[state], None):
                with self.subTest(state=state, card=card):
                    code, text = run(lambda path: shots.Shot(state, 480, path, 480, card=card))
                    self.assertEqual(code, 0)
                    self.assertNotIn(phrase, text)
        self.assertEqual((shots.WORDS_CARD, shots.REFUSED_CARD), (right["question-words"],
                                                                  right["question-refused"]))

    def test_the_question_card_shots_pick_ask_for_changes_and_type_or_send_only_on_a_page_with_the_words_box(
            self) -> None:
        empty = (None, None, None, None)
        third = ".lead ul.opts li:nth-child(3) button.opt"
        cases = (("question-words", {shots.WORDS_BOX}, [third], [(shots.WORDS_BOX, shots.LOOK_WORDS)],
                  shots.WORDS_CARD),
                 ("question-refused", {shots.WORDS_BOX}, [third, ".lead button.send"], [],
                  shots.REFUSED_CARD),
                 ("question-words", {shots.LOOK_OPTION}, [], [], None),
                 ("question-refused", {shots.LOOK_OPTION}, [], [], None),
                 ("question-words", set(), [], [], empty),
                 ("question-refused", set(), [], [], empty),
                 ("inbox-card", {shots.WORDS_BOX}, [], [], None))
        for state, present, clicks, fills, card in cases:
            for width in shots.WIDTHS:
                with self.subTest(state=state, present=bool(present), width=width), \
                        tempfile.TemporaryDirectory() as tmp:
                    browser, page = fake_browser(present)
                    page.card = card or ()
                    shot = shots._shoot(browser, "http://console.test/", state, width, Path(tmp))
                    self.assertEqual(page.clicks, clicks)
                    self.assertEqual(page.fills, fills)
                    self.assertEqual(shot.card, card)
                    self.assertEqual(page.reads, 1 if card and card != empty else 0)

    def test_the_look_check_question_is_seeded_with_needs_words_only_where_the_service_keeps_it(
            self) -> None:
        for kept in (True, False):
            with self.subTest(kept=kept), tempfile.TemporaryDirectory() as tmp:
                at = [""]
                log = shots.EventLog(Path(tmp) / "events.db", clock=lambda: at[0])
                with mock.patch.object(shots, "NEEDS_WORDS_KEPT", kept):
                    shots._Seed(log, at, 10000.0).sprint("owner/web", "t", started=1800,
                                                           look=True)
                (asked,) = [e for e in log.events() if e.kind == "questions.asked"]
                log.close()
                (question,) = asked.payload["questions"]
                self.assertEqual(question["options"], shots.LOOK_OPTIONS)
                self.assertEqual("needs_words" in question, kept)
        self.assertTrue(shots.NEEDS_WORDS_KEPT)

    def test_a_question_read_shot_that_does_not_read_the_answer_in_the_main_column_fails_the_command(
            self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        phrase = "does not show the answer in the main column"
        for reading in ((False, 1, True, True, 3), (True, 2, True, True, 3),
                        (True, 1, False, True, 3), (True, 1, True, False, 3),
                        (True, 1, True, True, 0)):
            with self.subTest(reading=reading):
                code, text = run(lambda path: shots.Shot("question-read", 480, path, 480,
                                                         reading=reading))
                self.assertEqual(code, 1)
                self.assertIn(phrase, text)
        for reading in (shots.READ_SHOWN, None):
            with self.subTest(reading=reading):
                code, text = run(lambda path: shots.Shot("question-read", 480, path, 480,
                                                         reading=reading))
                self.assertEqual(code, 0)
                self.assertNotIn(phrase, text)

    def test_the_question_read_shot_opens_the_thread_in_the_panel_only_on_a_page_that_has_it(
            self) -> None:
        cases = (("head", {shots.READING_PANEL, shots.ASK_FOLD},
                  [shots.ASK_FOLD, shots.thread_line("1226a1")], shots.READ_SHOWN),
                 ("base", {shots.ASK_FOLD},
                  [shots.ASK_FOLD, 'details[data-key="thread:owner/web:1226a1"] > summary'], None))
        for name, present, clicks, reading in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                shot = shots._shoot(browser, "http://console.test/", "question-read", 480,
                                    Path(tmp))
                self.assertEqual(page.clicks, clicks)
                self.assertEqual(shot.reading, reading)

    def test_the_question_read_shot_counts_the_question_it_was_given(self) -> None:
        browser, page = fake_browser({shots.READING_PANEL, shots.ASK_FOLD})
        with tempfile.TemporaryDirectory() as tmp:
            shots._shoot(browser, "http://console.test/", "question-read", 480, Path(tmp),
                         question="What is in production?")
        self.assertEqual(page.counted, "What is in production?")
        self.assertNotIn("What was done", shots.READ_READING)

    def test_a_real_answer_run_shoots_only_the_question_read_state_with_that_answer(self) -> None:
        def run(reading, jargon=0):
            calls = []

            def capture(out, states=shots.STATES, widths=shots.WIDTHS, **kwargs):
                calls.append({"states": tuple(states), **kwargs})
                return [shots.Shot("question-read", width, Path(out) / f"question-read-{width}.png",
                                   width, jargon=jargon, reading=reading) for width in widths]

            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", side_effect=capture), \
                    redirect_stdout(out):
                answer = Path(tmp) / "answer.txt"
                answer.write_text("Answer: plain", encoding="utf-8")
                code = shots.main(["--out", tmp, "--question", "Q?", "--answer-file", str(answer)])
            return code, out.getvalue(), calls

        phrase = "does not show the answer in the main column"
        code, text, calls = run((True, 1, False, False, 0), jargon=1)
        self.assertEqual(code, 0)
        self.assertNotIn(phrase, text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["states"], ("question-read",))
        self.assertEqual(calls[0]["read"], ("Q?", "Answer: plain"))
        code, text, _ = run(None)
        self.assertEqual(code, 0)
        code, text, _ = run((True, 2, False, False, 0))
        self.assertEqual(code, 1)
        self.assertIn(phrase, text)
        code, text, _ = run((False, 1, True, True, 3))
        self.assertEqual(code, 1)
        self.assertIn(phrase, text)
        for flags in (["--question", "Q?"], ["--answer-file", "x.txt"]):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as tmp, \
                    redirect_stdout(StringIO()), mock.patch("sys.stderr", new=StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    shots.main(["--out", tmp, *flags])
                self.assertEqual(raised.exception.code, 2)

    def test_a_real_answer_seeds_the_question_read_state_with_that_question_and_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now_s = time.time()
            fixture = shots.build_fixture(
                Path(tmp), "question-read", now_s,
                read=("Q?", "Answer: plain\nQuestion for you: none"))
            svc = shots.start_service(fixture, now_s)
            try:
                view = json.loads(svc.view_bytes)
            finally:
                svc.close()
        web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
        (thread,) = web["questions"]["threads"]
        (asked,) = thread["questions"]
        self.assertEqual(asked["question"], "Q?")
        self.assertEqual(asked["answer"], "plain")
        self.assertIsNone(asked["back_text"])

    def test_a_shot_with_a_short_control_fails_the_command(self) -> None:
        out = StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(shots, "capture", return_value=[
                    shots.Shot("live-several", 1440, Path(tmp) / "p.png", 1440,
                               short=("button.undo 24px",))]), \
                redirect_stdout(out):
            code = shots.main(["--out", tmp])
        self.assertEqual(code, 1)
        self.assertIn("has a control under 32 px", out.getvalue())
        self.assertIn("button.undo 24px", out.getvalue())

    def test_a_shot_not_taken_from_the_top_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        code, text = run(lambda path: shots.Shot("finished-list", 480, path, 480, 0, 0, None,
                                                 scroll_y=240.0))
        self.assertEqual(code, 1)
        self.assertIn("x.png is not taken from the top of the page", text)
        code, text = run(lambda path: shots.Shot("finished-list", 480, path, 480, 0, 0, None,
                                                 scroll_y=0.0))
        self.assertEqual(code, 0)
        self.assertNotIn("not taken from the top", text)

    def test_a_shot_scrolls_back_to_the_top_before_its_capture(self) -> None:
        def fake(reset_to):
            class Page:
                y = 0.0

                def __init__(self):
                    self.captured = []

                def goto(self, url):
                    pass

                def wait_for_selector(self, selector):
                    pass

                def click(self, selector):
                    self.y = 300.0

                def evaluate(self, expression):
                    if expression == shots.SCROLL_TOP:
                        self.y = reset_to
                        return None
                    if expression == shots.SCROLL_Y:
                        return self.y
                    if expression == "document.documentElement.scrollWidth":
                        return 480
                    if expression in (shots.SHORT_CONTROLS, shots.ACTS_ROW):
                        return []
                    return 0

                def screenshot(self, path, full_page):
                    self.captured.append((self.y, full_page))

                def close(self):
                    pass

            page = Page()

            class Browser:
                def new_page(self, viewport):
                    return page

            return Browser(), page

        for reset_to in (0.0, 40.0):
            with self.subTest(reset_to=reset_to), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake(reset_to)
                shot = shots._shoot(browser, "http://console.test/", "finished-list", 480,
                                    Path(tmp))
                self.assertEqual(page.captured, [(reset_to, True)])
                self.assertEqual(shot.scroll_y, reset_to)
                self.assertEqual(shot.scroll_y, page.captured[0][0])

    def test_the_goal_states_type_into_the_box_before_the_capture(self) -> None:
        calls: list[tuple[str, tuple]] = []

        class Page:
            def goto(self, url):
                calls.append(("goto", (url,)))

            def wait_for_selector(self, selector):
                calls.append(("wait_for_selector", (selector,)))

            def focus(self, selector):
                calls.append(("focus", (selector,)))

            def fill(self, selector, text):
                calls.append(("fill", (selector, text)))

            def click(self, selector):
                calls.append(("click", (selector,)))

            def evaluate(self, expression):
                if expression == shots.SCROLL_Y:
                    return 0.0
                if expression == "document.documentElement.scrollWidth":
                    return 480
                if expression in (shots.SHORT_CONTROLS, shots.ACTS_ROW):
                    return []
                return 0

            def screenshot(self, path, full_page):
                calls.append(("screenshot", (path, full_page)))

            def close(self):
                pass

        class Browser:
            def new_page(self, viewport):
                return Page()

        self.assertEqual(shots.GOAL_NEAR_CHARS, 1900)
        self.assertEqual(shots.GOAL_OVER_CHARS, 2100)
        for state, typed, over in (("goal-near", "x" * 1900, False),
                                   ("goal-over", "x" * 2100, True)):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                calls.clear()
                shots._shoot(Browser(), "http://console.test/", state, 480, Path(tmp))
                shot_at = next(i for i, c in enumerate(calls) if c[0] == "screenshot")
                before = calls[:shot_at]
                focus = ("focus", ("textarea.goal-text",))
                fill = ("fill", ("textarea.goal-text", typed))
                self.assertIn(focus, before)
                self.assertIn(fill, before)
                self.assertLess(before.index(focus), before.index(fill))
                self.assertNotIn(("click", ("button.goal-send",)), calls)
                hint = ("wait_for_selector", (".goal-hint:not(:empty)",))
                if over:
                    self.assertIn(hint, before)
                    self.assertLess(before.index(fill), before.index(hint))
                else:
                    self.assertNotIn(hint, calls)

    def test_the_guest_shot_goes_through_a_stand_in_serve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now_s = time.time()
            fixture = shots.build_fixture(Path(tmp).resolve(), "guest-page", now_s)
            svc = shots.start_service(
                fixture, now_s, guest_dir=support.guest_socket_path(self).parent.parent)
            serve = None
            try:
                serve = shots._Serve(shots.guest_door(svc))

                def get(address, path):
                    connection = http.client.HTTPConnection(*address, timeout=5)
                    try:
                        connection.request("GET", path)
                        response = connection.getresponse()
                        return response.status, response.read()
                    finally:
                        connection.close()

                status, body = get(serve.address, "/api/state")
                self.assertEqual(status, 200)
                state = json.loads(body)
                self.assertNotIn("sharing", state)
                self.assertIn("owner/web", body.decode())
                self.assertNotIn("owner/api", body.decode())
                status, body = get(serve.address, "/")
                self.assertEqual(status, 200)
                self.assertIn(service.DOOR_GUEST, body)
                status, body = get(svc.address, "/api/state")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["sharing"]["colleagues"],
                                 [{"login": shots.COLLEAGUE, "projects": ["owner/web"]}])
            finally:
                if serve is not None:
                    serve.close()
                svc.close()

    def test_the_sharing_shots_read_on_off_and_unreadable(self) -> None:
        cases = (("sharing-panel", True, True, shots.TAILNET, "unchecked"),
                 ("sharing-off", True, False, shots.TAILNET, "off"),
                 ("sharing-unreadable", False, True, None, "unreadable"))
        for state, readable, shared, tailnet, serve in cases:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                now_s = time.time()
                fixture = shots.build_fixture(Path(tmp).resolve(), state, now_s)
                svc = shots.start_service(
                    fixture, now_s, guest_dir=support.guest_socket_path(self).parent.parent,
                    tailnet_readable=readable)
                try:
                    connection = http.client.HTTPConnection(*svc.address, timeout=5)
                    try:
                        connection.request("GET", "/api/state")
                        sharing = json.loads(connection.getresponse().read())["sharing"]
                    finally:
                        connection.close()
                    self.assertEqual(sharing["shared"], shared)
                    self.assertEqual(sharing["tailnet"], tailnet)
                    self.assertEqual(sharing["state"], serve)
                finally:
                    svc.close()

    def test_the_harness_sends_each_door_its_own_headers(self) -> None:
        self.assertEqual(shots._guest_headers(("127.0.0.1", 9)), {"Host": shots.TAILNET})
        self.assertEqual(shots._guest_headers("/tmp/cg-x/g.sock"),
                         {"Host": "localhost", "X-Forwarded-Host": shots.TAILNET})

    def test_the_harness_opens_the_base_and_the_head_guest_door(self) -> None:
        def base(store, registry, *, port, guest_port=None, guest_token_path=None, **kwargs):
            pass

        folder = Path("/tmp/cg-x")
        self.assertEqual(shots.guest_door_kwargs(base, folder), {"guest_port": 0})
        self.assertEqual(shots.guest_door_kwargs(service.ConsoleService, folder),
                         {"guest_socket": folder / "guest" / "guest.sock"})
        tcp = shots._door_connection(("127.0.0.1", 9), 5)
        self.assertIsInstance(tcp, http.client.HTTPConnection)
        self.assertNotIsInstance(tcp, shots._UnixHTTPConnection)
        self.assertEqual((tcp.host, tcp.port), ("127.0.0.1", 9))
        self.assertIsInstance(shots._door_connection("/tmp/cg-x/g.sock", 5),
                              shots._UnixHTTPConnection)
        self.assertEqual(shots.guest_door(SimpleNamespace(guest_address=("127.0.0.1", 9))),
                         ("127.0.0.1", 9))
        self.assertEqual(
            shots.guest_door(SimpleNamespace(guest_socket="/tmp/g.sock", guest_address=None)),
            "/tmp/g.sock")

    def test_the_sharing_shot_opens_the_panel_only_where_the_page_has_one(self) -> None:
        for state in ("sharing-panel", "sharing-off", "sharing-unreadable"):
            for present, opens in (({"#sharing-open"}, True), (set(), False)):
                with self.subTest(state=state, opens=opens):
                    self.check_sharing_shot(state, present, opens)

    def check_sharing_shot(self, state: str, present: set, opens: bool) -> None:
        calls: list[tuple[str, tuple]] = []

        class Page:
            def goto(self, url):
                calls.append(("goto", (url,)))

            def wait_for_selector(self, selector):
                calls.append(("wait_for_selector", (selector,)))

            def query_selector(self, selector):
                return object() if selector in present else None

            def click(self, selector):
                calls.append(("click", (selector,)))

            def evaluate(self, expression, arg=None):
                if expression == shots.SCROLL_Y:
                    return 0.0
                if expression == "document.documentElement.scrollWidth":
                    return 480
                if expression in (shots.SHORT_CONTROLS, shots.ACTS_ROW):
                    return []
                return 0

            def screenshot(self, path, full_page):
                pass

            def close(self):
                pass

        class Browser:
            def new_page(self, viewport):
                return Page()

        with tempfile.TemporaryDirectory() as tmp:
            shots._shoot(Browser(), "http://console.test/", state, 480, Path(tmp))
        if not opens:
            self.assertNotIn(("click", ("#sharing-open",)), calls)
            self.assertNotIn(("wait_for_selector", ("#sharing:not([hidden])",)), calls)
            return
        click = calls.index(("click", ("#sharing-open",)))
        self.assertLess(click, calls.index(("wait_for_selector", ("#sharing:not([hidden])",))))

    def test_the_guest_shot_refuses_the_owner_page(self) -> None:
        door = "#console-door"
        for present, refused in (({door, "#capacity"}, True), ({door}, False)):
            with self.subTest(refused=refused), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                if refused:
                    with self.assertRaisesRegex(RuntimeError, "the guest shot is not the guest page"):
                        shots._shoot(browser, "http://console.test/", "guest-page", 480, Path(tmp))
                else:
                    shots._shoot(browser, "http://console.test/", "guest-page", 480, Path(tmp))
                self.assertIn("#top-who:not([hidden])", page.waits)

    def test_the_guest_shot_on_the_base_page_waits_for_no_guest_part(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser, page = fake_browser({"#capacity"})
            shots._shoot(browser, "http://console.test/", "guest-page", 480, Path(tmp))
        self.assertNotIn("#top-who:not([hidden])", page.waits)

    def test_every_fixture_path_is_temporary_and_never_a_real_one(self) -> None:
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        real_registry = real_home / ".agents" / "state" / "fleet" / "registry.json"
        protected = [*accounts_sandbox.real_accounts_dirs(), real_home / ".agents" / "state"]
        for state in shots.STATES:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = shots.build_fixture(root, state, time.time())
                paths = fixture_paths(fixture)
                for path in paths:
                    self.assertTrue(path.resolve().is_relative_to(root), path)
                self.assertFalse(accounts_sandbox.overlaps(paths, protected))
                self.assertNotEqual(fixture.registry.resolve(), real_registry.resolve())
                for value in shots.sandbox_environ(root).values():
                    self.assertTrue(Path(value).resolve().is_relative_to(root), value)
                self.assertEqual(
                    sorted(shots.sandbox_environ(root)),
                    ["CLAUDE_ACCOUNTS_DIR", "CLAUDE_CONFIG_DIR", "HOME", "XDG_CONFIG_HOME",
                     "XDG_STATE_HOME"])
                svc = shots.start_service(fixture, time.time())
                try:
                    self.assertEqual(svc.registry, fixture.registry)
                finally:
                    svc.close()

    def test_the_fixture_service_never_reads_a_real_keepalive_log(self) -> None:
        # On darwin the service's default ping log is under the real HOME; the fixture
        # must not read it, or today's real pings price as keepalive spend (#1135).
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as tmp:
            log = Path(home) / "Library/Logs/claude-cache-proxy.log"
            log.parent.mkdir(parents=True)
            log.write_text(json.dumps({
                "event": "ping", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "conversation": "real", "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 1000000}}) + "\n", encoding="utf-8")
            now_s = time.time()
            fixture = shots.build_fixture(Path(tmp), "finished-list", now_s)
            with mock.patch.dict(os.environ, {"HOME": home}), \
                    mock.patch.object(sys, "platform", "darwin"):
                svc = shots.start_service(fixture, now_s)
            try:
                days = json.loads(svc.view_bytes)["spend"]["days"]
            finally:
                svc.close()
            self.assertEqual([d["total"]["dollars"] for d in days if d["total"]["dollars"]], [])

    def test_each_look_state_carries_a_before_and_an_after_picture_the_console_serves(self) -> None:
        for state in ("look-card", "look-moved", "look-failed"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                now_s = time.time()
                fixture = shots.build_fixture(Path(tmp), state, now_s)
                svc = shots.start_service(fixture, now_s)
                try:
                    view = json.loads(svc.view_bytes)
                    pictures_dir = svc.pictures_dir
                finally:
                    svc.close()
                card = view["inbox"]["open"][0]
                self.assertEqual([p["pair"] for p in card["pictures"]], ["before", "after"])
                self.assertEqual(len({p["id"] for p in card["pictures"]}), 2)
                for picture in card["pictures"]:
                    data = (pictures_dir / picture["id"]).read_bytes()
                    self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_each_fixture_view_shows_its_state(self) -> None:
        for state in shots.STATES:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                now_s = time.time()
                fixture = shots.build_fixture(Path(tmp), state, now_s)
                launches: list = []
                svc = shots.start_service(fixture, now_s, launches)
                try:
                    view = json.loads(svc.view_bytes)
                finally:
                    svc.close()
                sprints = all_sprints(view)
                running = [s for s in sprints if s["ended_at"] is None]
                ended = [s for s in sprints if s["ended_at"] is not None]
                self.assertEqual(launches, [])
                for sprint in running:
                    if state == "failed-start":
                        continue
                    self.assertEqual(sprint["manager_state"], "started", sprint["title"])
                    self.assertIsNone(sprint["manager_text"], sprint["title"])
                    self.assertFalse(sprint["now_text"].startswith("Working on"), sprint["title"])
                    self.assertNotEqual(sprint["now_text"], sprint["title"])
                    self.assertNotEqual(sprint["now_text"], sprint["status"])
                    self.assertEqual(
                        [m for m in sprint["messages"]
                         if m["kind"] == "approved" and m["state"] == "picked_up"], [])
                latest = [s["messages"][-1] for s in running if s["messages"]]
                if state == "live-several":
                    self.assertEqual(len(running), 3)
                    self.assertEqual(
                        len({p["project_id"] for p in entries_of(view) if p.get("sprints")}), 2)
                    self.assertEqual({s["ball"] for s in running},
                                     {"manager", "owner", "nobody"})
                elif state == "waiting-on-you":
                    self.assertEqual([s["ball"] for s in running], ["owner"])
                    self.assertEqual(
                        running[0]["now_text"],
                        "waiting for your answer: Which store should the checkpoint use?")
                elif state == "stuck":
                    self.assertEqual([s["ball"] for s in running], ["nobody"])
                    self.assertEqual(running[0]["now_text"],
                                     "last seen building 1 of 2: the upload form")
                elif state == "manager-cannot-hear":
                    self.assertEqual([s["ball"] for s in running], ["owner"])
                    self.assertEqual(
                        running[0]["now_text"],
                        "the manager cannot hear the console: bring it back or drop the sprint")
                elif state == "tell-box-open":
                    self.assertEqual(len(running), 1)
                    self.assertEqual(running[0]["messages"], [])
                    self.assertIsInstance(running[0]["tell_text"], str)
                elif state == "message-sent":
                    self.assertEqual(len(running[0]["messages"]), 1)
                    self.assertEqual(latest[-1]["state"], "sent")
                elif state == "message-picked-up":
                    self.assertEqual(latest[-1]["state"], "picked_up")
                elif state == "message-replied":
                    self.assertEqual(latest[-1]["state"], "replied")
                    self.assertTrue(latest[-1]["new"])
                    self.assertIsInstance(view["new_replies_text"], str)
                elif state == "message-not-picked-up":
                    self.assertEqual(latest[-1]["state"], "not_picked_up")
                    self.assertTrue(latest[-1]["action_text"])
                elif state == "finished-list":
                    self.assertGreaterEqual(len(ended), 2)
                    self.assertTrue(any(s["closing"] for s in ended))
                elif state == "owner-check":
                    self.assertEqual([s["ball"] for s in running], ["manager"])
                    self.assertEqual(running[0]["now_text"], "building 1 of 3: the upload form")
                    self.assertEqual(
                        [c["text"] for c in running[0]["checks"]],
                        ["Your check: Do the before and after pictures read well?"])
                    self.assertEqual(view["statement"]["inbox_items"], 1)
                elif state == "nothing-running":
                    self.assertEqual(running, [])
                elif state == "failed-start":
                    (sprint,) = running
                    self.assertEqual(sprint["manager_state"], "failed")
                    self.assertTrue(sprint["retry"])
                    self.assertEqual(sprint["now_text"],
                                     "waiting for you: the manager failed to start")
                    (item,) = [i for i in view["inbox"]["open"]]
                    self.assertEqual(item["reason"], "failed_start")
                    self.assertEqual(item["last_reason"],
                                     "this account does not trust the project's folder")
                    self.assertNotIn("/home/", json.dumps(view))
                elif state == "waiting-its-turn":
                    self.assertEqual(
                        [(s["state"], s["ball"], s["now_text"]) for s in running],
                        [("on_track", "manager", "waiting its turn to merge")])
                    web = next(p for p in entries_of(view) if p.get("project_id") == "owner/web")
                    lone = next(d for s in web["outside_sprints"]["sessions"]
                                for d in s["deliveries"] if d["run_id"] == "wf_l1")
                    self.assertEqual(
                        (lone["quiet"], lone["moved_text"], lone["wait_text"]),
                        (False, "waiting its turn to merge", "waiting its turn to merge"))
                elif state in ("goal-open", "goal-near", "goal-over"):
                    other = shots.build_fixture(Path(tmp) / "other", "tell-box-open", now_s)
                    again = shots.start_service(other, now_s)
                    try:
                        self.assertEqual(
                            [s["title"] for s in running],
                            [s["title"] for s in all_sprints(json.loads(again.view_bytes))])
                    finally:
                        again.close()
                elif state == "inbox-card":
                    self.assertEqual(len(view["inbox"]["open"][0]["questions"][0]["options"]), 2)
                elif state in ("activation-tooling", "activation-host"):
                    self.assertEqual(running, [])
                    self.assertEqual(view["activation"], {
                        "text": shots.ACTIVATION_SHOWN[state][0],
                        "state": "pending", "commit": "1258" * 10,
                        "root": str(fixture.projects[1]), "activate": True})  # sorted: api
                    self.assertEqual(view["statement"]["inbox_items"], 0)
                elif state in ("question-words", "question-refused"):
                    (asked,) = view["inbox"]["open"]
                    (look,) = asked["questions"]
                    self.assertEqual(look["options"],
                                     ["Approve", "Approve with one fix", "Ask for changes"])
                    self.assertEqual(look["recommended_index"], 0)
                    self.assertEqual(look["needs_words_index"], [1, 2])
                elif state == "accounts-panel":
                    self.assertEqual(
                        sorted(e["profile"] for e in view["capacity"]["profiles"]),
                        ["work-main", "work-spare"])
                elif state in ("notices-fold", "notice-post-open"):
                    self.assertEqual(
                        sorted(s["title"] for s in running),
                        ["Add resumable uploads", "Fix the settings page"])
                    web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
                    self.assertTrue(web["notice_post"])
                    self.assertEqual(
                        [(n["poster"], n["kind"], n["text"], n["owner"]) for n in web["notices"]],
                        [("You", "heads-up", "routes are frozen until Friday", True),
                         ("Fix the settings page", "claim", "reworking the settings form",
                          False)])
                elif state in ("ask-box", "ask-goal"):
                    web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
                    threads = web["questions"]["threads"]
                    asked = [q for t in threads for q in t["questions"]]
                    self.assertEqual([len(t["questions"]) for t in threads], [1, 1])
                    self.assertEqual([q["state"] for q in asked], ["working", "answered"])
                    self.assertEqual([q["question"] for q in asked],
                                     [shots.ASK_WORKING_QUESTION, shots.ASK_ANSWERED_QUESTION])
                    self.assertEqual(asked[1]["read_text"], shots.ASK_READ_LINE)
                    self.assertEqual(asked[1]["ran_text"], "Ran: just build")
                    self.assertEqual(asked[1]["answer"], shots.ASK_ANSWER_SUMMARY)
                    self.assertLessEqual(len(shots.ASK_ANSWER_SUMMARY), 45)
                    self.assertEqual(view["statement"]["inbox_items"], 0)
                elif state == "question-read":
                    web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
                    threads = web["questions"]["threads"]
                    self.assertEqual([len(t["questions"]) for t in threads], [1])
                    asked = threads[0]["questions"][0]
                    self.assertEqual(asked["state"], "answered")
                    self.assertEqual(asked["question"], shots.READ_QUESTION)
                    self.assertGreaterEqual(len(asked["answer"]), 1200)
                    for marker in ("**", "\n- ", "`", "```",
                                   "\n" + shots.READ_FENCED_LINE + "\n"):
                        self.assertIn(marker, asked["answer"])
                    self.assertNotIn("--since=7.days", asked["read_text"])
                    self.assertEqual(len(shots.READ_CHOICES), 3)
                    self.assertEqual(asked["back_choices"], list(shots.READ_CHOICES))
                    self.assertTrue(asked["back_text"].startswith("Question for you: "))
                    self.assertEqual(running, [])
                elif state in ("questions-closed", "questions-open"):
                    web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
                    self.assertEqual(web["questions"]["count"], 2)
                    newest = web["questions"]["threads"][0]["questions"]
                    self.assertEqual([q["question"] for q in newest],
                                     [shots.THREAD_QUESTION, shots.FOLLOW_QUESTION])
                    self.assertEqual([q["state"] for q in newest], ["answered", "answered"])
                    self.assertEqual(newest[1]["read_text"], shots.FOLLOW_READ_LINE)
                    self.assertEqual(view["statement"]["inbox_items"], 0)
                    self.assertEqual(running, [])
                    self.assertTrue(all(p.get("quiet") for p in entries_of(view)))
                days = (view["spend"] or {"days": []})["days"]
                self.assertIsNotNone(view["spend"])
                if state == "desk-spend":
                    self.assertEqual(len(running), 1)
                    self.assertGreaterEqual(len(ended), 1)
                    self.assertLessEqual(
                        {running[0]["sprint_id"], ended[0]["sprint_id"]},
                        set().union(*(d["sprint"] for d in days[-7:])))
                    line = next(p for p in entries_of(view)
                                if p.get("project_id") == "owner/web")["outside_sprints"]
                    outside = {s["session_id"]: s for s in line["sessions"]}
                    self.assertEqual(
                        [d["run_id"] for d in outside["outside-1136"]["deliveries"]], ["wf_9"])
                    self.assertIn("wf_9", set().union(*(d["run"] for d in days[-7:])))
                    self.assertGreater(days[-1]["total"]["dollars"], 0)
                elif state == "spend-page":
                    self.assertGreater(days[-1]["total"]["dollars"], 0)
                    self.assertGreaterEqual(
                        sum(1 for d in days[-7:] if d["total"]["dollars"] > 0), 4)
                    self.assertGreaterEqual(
                        len(set().union(*(d["phase"] for d in days[-7:]))), 2)
                    self.assertIn(running[0]["sprint_id"],
                                  set().union(*(d["sprint"] for d in days[-7:])))
                else:
                    self.assertEqual(days[-1]["total"]["dollars"], 0)


class ScreenshotCaptureTest(unittest.TestCase):
    def test_the_command_writes_a_png_per_state_and_width_and_nothing_scrolls_sideways(self) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        with sync_playwright() as pw:
            try:
                pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"]).close()
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            taken = shots.capture(out)
            self.assertEqual([s for s in taken if s.width == 480 and s.scroll_width > 480], [])
            self.assertEqual([s for s in taken if s.squeezed], [])
            self.assertEqual([s for s in taken if s.jargon], [])
            self.assertEqual([(s.path.name, s.scroll_y) for s in taken if s.scroll_y != 0], [])
            self.assertEqual(
                [s.width for s in taken if s.state == "tell-box-open" and s.tell == shots.OPEN_TELL],
                list(shots.WIDTHS))
            self.assertEqual(
                [s for s in taken if s.state != "tell-box-open" and s.tell is not None], [])
            self.assertEqual(
                [s.width for s in taken if s.state == "ask-box" and s.ask == shots.OPEN_ASK],
                list(shots.WIDTHS))
            self.assertEqual([s for s in taken if s.state != "ask-box" and s.ask is not None], [])
            self.assertEqual(
                [s.width for s in taken if s.state == "ask-goal" and s.goal == shots.FILLED_GOAL],
                list(shots.WIDTHS))
            self.assertEqual([s for s in taken if s.state != "ask-goal" and s.goal is not None],
                             [])
            self.assertEqual(
                [s.width for s in taken
                 if s.state == "questions-open" and s.thread == shots.OPEN_THREAD],
                list(shots.WIDTHS))
            self.assertEqual([s for s in taken if s.acts != ()], [])
            self.assertEqual(shots.main(["--out", str(out)]), 0)
            names = sorted(p.name for p in out.iterdir())
            self.assertEqual(
                names, sorted(f"{s}-{w}.png" for s in shots.STATES for w in shots.WIDTHS))
            self.assertEqual(len(names), 2 * len(shots.STATES))
            for path in out.iterdir():
                self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


PAGE_HTML = Path(service.__file__).with_name("page.html")
INNER = "CONSOLE_PANEL_TEST_INNER"

# The same Nix expressions the `console-screenshots` recipe in the justfile builds its Python and browsers from.
NIX_PKGS = "(builtins.getFlake (toString ./.)).inputs.nixpkgs.legacyPackages.${builtins.currentSystem}"
NIX_PYTHON = f"({NIX_PKGS}).python3.withPackages (ps: [ ps.playwright ])"
NIX_BROWSERS = f"({NIX_PKGS}).playwright-driver.browsers"


def nix_out(expr: str) -> str | None:
    import subprocess
    done = subprocess.run(["nix", "--extra-experimental-features", "nix-command flakes", "build",
                           "--no-link", "--print-out-paths", "--impure", "--expr", expr],
                          cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True)
    return done.stdout.strip().splitlines()[-1] if done.returncode == 0 and done.stdout.strip() else None


def chromium_here() -> bool:
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        return False
    with sync_playwright() as pw:
        try:
            pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"]).close()
        except Error:
            return False
    return True


class PanelBackdropTest(unittest.TestCase):
    """The Accounts and Sharing panels leave no text beneath them (#1316).

    Required CI has no Playwright, so without a browser here the cases rerun themselves under the
    Python and browsers the screenshot recipe builds with Nix; they skip only where Nix is absent too.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.rerun = None
        if os.environ.get(INNER):
            if not chromium_here():
                raise RuntimeError("the nix-built browser environment cannot launch Chromium")
        elif not chromium_here():
            python, browsers = nix_out(NIX_PYTHON), nix_out(NIX_BROWSERS)
            if python is None or browsers is None:
                raise unittest.SkipTest("no Chromium and no Nix to build one with")
            cls.rerun = (f"{python}/bin/python3", browsers)

    def run_inner(self, name: str) -> None:
        import subprocess
        python, browsers = self.rerun
        root = Path(__file__).resolve().parent.parent
        env = {**os.environ, INNER: "1", "PLAYWRIGHT_BROWSERS_PATH": browsers,
               "PYTHONPATH": os.pathsep.join([str(root / "python"), str(root)])}
        done = subprocess.run([python, "-m", "unittest", f"tests.test_console_screenshots.PanelBackdropTest.{name}"],
                              cwd=root, env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("skipped", done.stderr)

    def read(self, htmls, expression):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                found = []
                for html in htmls:
                    page.set_content(html)
                    found.append(page.evaluate(expression))
                return found
            finally:
                browser.close()

    def test_every_panel_state_shows_its_own_panel_with_no_page_text_beneath_it(self) -> None:
        if self.rerun:
            return self.run_inner("test_every_panel_state_shows_its_own_panel_with_no_page_text_beneath_it")
        panels = ("accounts-panel", "sharing-panel", "sharing-off", "sharing-unreadable")
        with tempfile.TemporaryDirectory() as tmp:
            taken = shots.capture(Path(tmp) / "out", states=panels)
        self.assertEqual([(s.state, s.width) for s in taken],
                         [(state, width) for state in panels for width in shots.WIDTHS])
        self.assertEqual([(s.path.name, s.panel) for s in taken],
                         [(f"{s.state}-{s.width}.png", shots.PANEL_OF[s.state]) for s in taken])
        self.assertEqual([(s.path.name, s.beneath) for s in taken if s.beneath], [])

    def test_a_missing_panel_button_is_not_a_clear_band(self) -> None:
        if self.rerun:
            return self.run_inner("test_a_missing_panel_button_is_not_a_clear_band")
        self.assertEqual(self.read(["<p>no panel here</p>"], shots.OPEN_PANEL), [None])

    def test_the_band_probe_sees_text_through_a_transparent_backdrop_but_not_an_opaque_one(self) -> None:
        if self.rerun:
            return self.run_inner(
                "test_the_band_probe_sees_text_through_a_transparent_backdrop_but_not_an_opaque_one")
        page = ('<header><section class="acct-panel" style="position:fixed;top:0;left:0;width:300px;'
                'height:100px;background:#fff">panel</section></header>'
                '<p style="position:fixed;top:105px;left:10px;margin:0;line-height:20px">under the panel</p>')
        backdrop = '<div style="position:fixed;inset:0;background:{}"></div>'
        found = self.read([page, page + backdrop.format("transparent"),
                           page + backdrop.format("rgba(0,0,0,.6)"),
                           page + backdrop.format("#101018")], shots.PANEL_BENEATH)
        self.assertEqual(found, [["p: under the panel"], ["p: under the panel"],
                                 ["p: under the panel"], []])

    def test_a_goal_picker_left_open_under_a_panel_is_hidden_by_the_page_and_seen_by_the_probe(self) -> None:
        if self.rerun:
            return self.run_inner(
                "test_a_goal_picker_left_open_under_a_panel_is_hidden_by_the_page_and_seen_by_the_probe")
        from playwright.sync_api import sync_playwright
        picker = ("document.getElementById('goal').hidden = false;"
                  "document.getElementById('goal').insertAdjacentHTML('beforeend',"
                  "'<div class=goal-box>' + '<p>Pick a project</p>'.repeat(12) + '</div>');"
                  "document.getElementById('accounts').hidden = false;")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            try:
                page = browser.new_page(viewport={"width": 480, "height": 900})
                page.set_content(PAGE_HTML.read_text(encoding="utf-8"))
                page.evaluate(picker)
                hidden = page.evaluate(shots.PANEL_BENEATH)
                page.add_style_tag(content=".goal-box { visibility: visible !important; }")
                shown = page.evaluate(shots.PANEL_BENEATH)
            finally:
                browser.close()
        self.assertEqual((hidden, set(shown)), ([], {"p: Pick a project"}))


class ScreenshotReadingTest(unittest.TestCase):
    def read_pages(self, htmls, expression):
        """Load each markup alone in one 1440x900 Chromium page and return what `expression` reads."""
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                found = []
                for html in htmls:
                    page.set_content(html)
                    found.append(page.evaluate(expression))
                return found
            finally:
                browser.close()

    def test_the_jargon_count_counts_each_visible_review_phrase(self) -> None:
        samples = {
            "on track": "<p>The sprint for owner/p00 is now on track: x</p>",
            "stated": '<div id="projects"><span>stated <time>3 min ago</time></span></div>',
            "withdraw": '<div id="projects"><button>Withdraw</button></div>',
            "nudge": '<div id="projects"><p>Tell the manager again to nudge it.</p></div>',
            "stop or": '<div id="projects"><p>Stop or go</p></div>',
            "would do differently":
                '<div id="projects"><p>Would do differently: cut smaller slices</p></div>',
            "approval row": '<div id="projects"><ul><li class="message">'
                            '<span class="message-text">You: Approved version 2</span>'
                            '<span class="message-state">picked up</span></li></ul></div>'}
        counts = self.read_pages([f"<body>{html}</body>" for html in samples.values()],
                                 shots.JARGON_COUNT)
        for name, count in zip(samples, counts):
            with self.subTest(name):
                self.assertEqual(count, 1)

    def test_the_jargon_count_skips_the_owners_withdraw(self) -> None:
        owners = ('<body><div id="projects"><button class="notice-withdraw">Withdraw</button>'
                  '</div></body>')
        other = '<body><div id="projects"><button>Withdraw</button></div></body>'
        self.assertEqual(self.read_pages([owners, other], shots.JARGON_COUNT), [0, 1])

    def test_the_jargon_count_skips_hidden_text_and_the_new_words(self) -> None:
        html = ('<body><div id="projects"><details><summary>End the sprint</summary>'
                '<button>Drop the sprint</button>'
                '<p>withdraw nudge on track stated 3 min ago Stop or go Would do differently</p>'
                '</details><p style="display:none">Withdraw</p>'
                '<span>goal set <time>3 min ago</time></span><p><button>Stop and report</button></p>'
                '<p>Could not drop: no</p><p>Next time: cut smaller slices</p>'
                '<ul><li class="message"><span class="message-text">You: Approved version 2</span>'
                '<span class="message-state">sent just now</span></li></ul></div></body>')
        self.assertEqual(self.read_pages([html], shots.JARGON_COUNT), [0])

    def test_the_control_reading_flags_a_control_under_32_px(self) -> None:
        bodies = ['<button style="height:24px">a</button>',
                  '<button style="min-height:32px">b</button>',
                  '<button style="display:none;height:10px">c</button>',
                  '<input style="height:20px">',
                  '<button style="height:31.75px;padding:0;border:0">e</button>',
                  '<details><summary class="more-open btn-quiet" '
                  'style="display:block;height:24px">f</summary></details>']
        found = self.read_pages([f"<body>{html}</body>" for html in bodies], shots.SHORT_CONTROLS)
        self.assertEqual([len(f) for f in found], [1, 0, 0, 1, 1, 1])
        self.assertEqual(found[5], ["summary.more-open 24px"])

    def test_the_tell_reading_flags_an_overlapping_or_narrow_field(self) -> None:
        def layout(*, hint_first=False, field="width:100%"):
            hint = '<p class="tell-hint">hint</p>'
            label = ('<label class="tell-label" style="display:block">'
                     '<span style="display:block">Tell the manager</span>'
                     f'<textarea class="tell" style="display:block;{field};box-sizing:border-box">'
                     '</textarea></label>')
            body = (hint + label if hint_first else label + hint) + '<button class="tell-send">Send</button>'
            return ('<ul><li class="sprint" style="width:600px;padding:0 12px;list-style:none">'
                    f'<div class="sprint-tell">{body}</div></li></ul>')

        layouts = {"good": layout(), "hint above": layout(hint_first=True),
                   "narrow": layout(field="width:200px")}
        readings = self.read_pages(list(layouts.values()), shots.TELL_READING)
        for (name, _), reading in zip(layouts.items(), readings):
            with self.subTest(name):
                self.assertEqual(reading[:3], [True, "Send", "hint"])
                self.assertIs(reading[3], name == "good")

    def test_the_ask_reading_reads_the_open_box_and_its_questions(self) -> None:
        field = ('<div class="ask-box"><textarea class="ask-text" '
                 'style="width:300px;height:60px"></textarea></div>')

        def block(*, textarea=True, working_style=""):
            return ('<ul><li class="line asks" data-project="owner/web">'
                    + (field if textarea else '<div class="ask-box"></div>')
                    + '<ul class="ask-list"><li class="ask"' + working_style + '>'
                    '<p class="ask-question">Is the importer deployed on this host? '
                    '<time>just now</time></p><p class="ask-state">Working on it</p></li>'
                    '<li class="ask"><p class="ask-question">What does the build check? '
                    '<time>3 min ago</time></p><p class="ask-answer">It builds.</p>'
                    '<p class="ask-read">Read: flake.nix, lib/helpers.nix</p></li></ul>'
                    '</li></ul>')

        found = self.read_pages(
            [block(), block(textarea=False), block(working_style=' style="display:none"'),
             "<ul><li>nothing</li></ul>"], shots.ASK_READING)
        self.assertEqual(found, [
            list(shots.OPEN_ASK),
            [False, "Working on it", "Read: flake.nix, lib/helpers.nix"],
            [True, None, "Read: flake.nix, lib/helpers.nix"],
            [False, None, None]])

    def test_the_row_reading_flags_ask_below_give_goal(self) -> None:
        def line(wrapper_open="", wrapper_close="", project="owner/web"):
            return ('<ul><li class="line quiet" data-project="' + project + '">'
                    '<span class="line-acts"><button class="give-goal">Give it a goal</button>'
                    + wrapper_open + '<button class="ask-open">Ask a question</button>'
                    + wrapper_close + '</span></li></ul>')

        found = self.read_pages(
            [line(), line('<span style="display:block">', '</span>'),
             "<ul><li class=\"line\" data-project=\"owner/web\">"
             "<button class=\"give-goal\">Give it a goal</button></li></ul>"],
            shots.ACTS_ROW)
        self.assertEqual(found, [[], ["owner/web"], []])

    def test_the_thread_reading_reads_the_opened_thread(self) -> None:
        def page(*, open_fold=True, show_follow=True, rows=True):
            row = ('<li class="ask"><p class="ask-question">' + shots.FOLLOW_QUESTION
                   + ' <time>just now</time></p><p class="ask-read">' + shots.FOLLOW_READ_LINE
                   + '</p></li>')
            return ('<ul><li class="line questions"><details data-key="questions:owner/web"'
                    + (" open" if open_fold else "") + '><summary>Questions (2)</summary>'
                    '<ul class="ask-list">' + (row if rows else "") + '</ul>'
                    + ('<button class="follow-open">Ask a follow-up</button>' if show_follow else "")
                    + '</details></li></ul>')

        base = ('<ul><li class="line asks" data-project="owner/web"><ul class="ask-list">'
                '<li class="ask"><p class="ask-question">' + shots.FOLLOW_QUESTION
                + '</p><p class="ask-read">' + shots.FOLLOW_READ_LINE + '</p></li></ul></li></ul>')
        found = self.read_pages(
            [page(), page(open_fold=False), page(show_follow=False), page(rows=False), base,
             "<ul><li>nothing</li></ul>"], shots.THREAD_READING)
        self.assertEqual(found, [
            list(shots.OPEN_THREAD),
            [False, None, False],
            [True, shots.FOLLOW_READ_LINE, False],
            [True, None, True],
            list(shots.BASE_THREAD),
            [False, None, False]])

    def test_the_activation_reading_reads_the_line_and_its_visible_buttons(self) -> None:
        shown_ = shots.ACTIVATION_SHOWN["activation-host"]
        text_ = shown_[0]

        def work(*, style="", buttons=1, line=True):
            body = ('<p class="activation"' + (f' style="{style}"' if style else "") + '><span><span>'
                    + text_ + '</span></span>' + '<button class="activate btn-quiet">Activate</button>'
                    * buttons + '</p>') if line else "<p>nothing</p>"
            return '<section id="projects">' + body + '</section>'

        found = self.read_pages(
            [work(), work(buttons=0), work(buttons=2), work(style="display:none"), work(line=False)],
            shots.ACTIVATION_READING)
        self.assertEqual(found, [
            list(shown_), [text_, 0], [text_, 2], [None, 0], [None, 0]])

    def test_the_goal_reading_reads_the_filled_box(self) -> None:
        filled = shots.FILLED_GOAL[1]

        def goal(*, box_style="", area_style="height:200px;width:400px"):
            return ('<div id="goal"><div class="goal-in">'
                    f'<textarea class="goal-text" style="{area_style}">{filled}</textarea>'
                    f'<div class="goal-box" style="{box_style}">'
                    '<button class="goal-project" aria-pressed="false">owner/api</button>'
                    '<button class="goal-project" aria-pressed="true"> owner/web </button>'
                    '</div></div></div>')

        found = self.read_pages(
            [goal(), goal(box_style="display:none"),
             goal(area_style="height:22px;width:400px;overflow:auto"),
             "<ul><li>nothing</li></ul>"], shots.GOAL_READING)
        self.assertEqual(found, [
            list(shots.FILLED_GOAL),
            [False, filled, "owner/web", True],
            [True, filled, "owner/web", False],
            [False, None, None, None]])


if __name__ == "__main__":
    unittest.main()
