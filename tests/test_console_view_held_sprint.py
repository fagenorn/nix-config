"""A held sprint is one derived desk card; the fixtures are those of `test_console_view`."""
import dataclasses
import unittest

from agent_tools.console import held_sprint, view
from agent_tools.console.sprints import Manager

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_engine_runs import LIVE
from .test_console_sprint_engine import engine_state
from .test_console_view import (
    A, MIN, R, T0, T0_MS, U, asked, check_item, derive_view, entry, iso, line, open_item, out,
    permission_item, reported, started, state, with_manager, working_session)

TIER = "fast"


class HeldSprintViewTest(unittest.TestCase):
    """A sprint holding unlanded work with nothing moving and nothing asked for an hour is one
    derived card (#1784); its ball, state and now-sentence stay as they were."""

    held = with_manager(reported(started(A), R, issues=((12, "landing"), (13, "landed")),
                                 status="the last slice waits on the lead's go"))
    since = "2026-11-12T10:01:00+00:00"

    @staticmethod
    def cards(shown):
        return [i for i in shown["inbox"]["open"] if i["reason"] == "held_sprint"]

    def test_a_sprint_holding_an_open_issue_with_nothing_moving_for_an_hour_is_one_card_with_its_last_status(self):
        now = R + 61 * MIN
        shown = line(self.held, now)
        self.assertEqual(shown["inbox"]["open"], [{
            "type": "inbox_item", "reason": "held_sprint", "key": "held-sprint/" + A,
            "project_id": "p00", "sprint_id": A, "title": "Ship the importer",
            "headline": "Ship the importer is holding work and has asked nobody for it",
            "last_status": "the last slice waits on the lead's go", "answered": False,
            "waiting_since": self.since}])
        self.assertEqual(shown["statement"]["inbox_items"], 1)
        self.assertEqual(shown["statement"]["headline"], "1 thing needs you")
        self.assertEqual(shown["statement"]["sentence"], held_sprint.SENTENCE)
        self.assertEqual(held_sprint.SENTENCE,
                         "Tell the manager what to do from its sprint, or drop the sprint.")
        self.assertEqual(entry(shown)["held_since"], self.since)
        self.assertEqual((entry(shown)["state"], entry(shown)["ball"]), ("quiet", "nobody"))

    def test_the_card_waits_for_a_full_hour_of_no_movement(self):
        early = line(self.held, R + 60 * MIN - 1)
        self.assertEqual(early["inbox"]["open"], [])
        self.assertEqual((entry(early)["state"], entry(early)["ball"]), ("quiet", "nobody"))
        self.assertEqual(len(self.cards(line(self.held, R + 60 * MIN))), 1)

    def test_a_moving_sprint_raises_no_card(self):
        now = R + 61 * MIN
        cases = {
            "working session": line(self.held, now, sessions=[working_session]),
            "moved a minute ago": line(dataclasses.replace(self.held, moved_ms=now - MIN), now),
            "reported five minutes ago": line(
                reported(self.held, now - 5 * MIN, issues=((12, "landing"), (13, "landed"))), now),
            "moved twenty minutes ago": line(
                dataclasses.replace(self.held, moved_ms=now - 20 * MIN), now),
        }
        for name, shown in cases.items():
            with self.subTest(name):
                self.assertEqual(shown["inbox"]["open"], [])
                self.assertIsNone(entry(shown)["held_since"])

    def test_an_open_card_or_question_clears_it(self):
        now = R + 61 * MIN
        stopped_run = engine_state("stopped.jsonl", LIVE, issue=12)
        cases = {
            "question": (line(asked(self.held), now), ["question", "question"]),
            "tracker item": (line(self.held, now, {("p00", "k1"): open_item("p00", "k1", 12)}),
                             None),
            "permission": (line(self.held, now, prompt_items=[permission_item()]),
                           ["permission"]),
            "progress": (line(dataclasses.replace(self.held, no_progress_at=iso(R + 40 * MIN)),
                              now), ["progress"]),
            "stall": (line(dataclasses.replace(self.held, stalled="r", stalled_at=iso(R + 40 * MIN)),
                           now), ["manager"]),
            "owner check card": (line(self.held, now, {("p00", "k1"): check_item("p00", "k1", 13, [])}),
                                 None),
            "stopped engine run": (line(self.held, now, engine_runs=[stopped_run]), None),
        }
        for name, (shown, reasons) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.cards(shown), [])
                if reasons is not None:
                    self.assertEqual([i["reason"] for i in shown["inbox"]["open"]], reasons)

    def test_a_stated_pause_or_a_wait_still_ahead_raises_none_and_a_passed_wait_raises_it(self):
        now = R + 61 * MIN

        def with_report(**kw):
            return dataclasses.replace(
                self.held, report=dataclasses.replace(self.held.report, **kw))

        for name, case in (("paused", with_report(paused="the lead paused it to free an account")),
                           ("wait ahead", with_report(wait_until=iso(R + 120 * MIN)))):
            with self.subTest(name):
                self.assertEqual(self.cards(line(case, now)), [])
        with self.subTest("wait passed"):
            self.assertEqual(
                len(self.cards(line(with_report(wait_until=iso(R + 30 * MIN)), now))), 1)

    def test_a_stopped_engine_run_is_the_one_thing_that_needs_the_owner(self):
        shown = line(self.held, R + 61 * MIN, engine_runs=[engine_state("stopped.jsonl", LIVE, issue=12)])
        self.assertEqual(self.cards(shown), [])
        self.assertIsNone(entry(shown)["held_since"])
        statement = shown["statement"]
        self.assertEqual((statement["inbox_items"], statement["headline"], statement["sentence"]),
                         (1, "1 thing needs you", view.ENGINE_SENTENCE))

    def test_an_owner_check_card_leaves_only_that_card_to_count(self):
        shown = line(self.held, R + 61 * MIN, {("p00", "k1"): check_item("p00", "k1", 13, [])})
        self.assertEqual(self.cards(shown), [])
        self.assertEqual(shown["statement"]["inbox_items"], 1)

    def test_a_stopping_sprint_raises_none(self):
        shown = line(dataclasses.replace(self.held, stop_at=T0), R + 61 * MIN)
        self.assertEqual(self.cards(shown), [])

    def test_a_sprint_with_no_unlanded_issue_raises_none(self):
        landed = with_manager(reported(started(A), R, issues=(
            (12, "landed"), (13, "held"), (14, "dropped"))))
        self.assertEqual(self.cards(line(landed, R + 61 * MIN)), [])
        self.assertEqual(self.cards(line(with_manager(started(A)), T0_MS + 120 * MIN)), [])

    def test_no_clock_raises_none(self):
        self.assertEqual(line(self.held, None)["inbox"]["open"], [])

    def test_held_cards_are_ordered_by_when_they_last_moved_after_the_progress_cards(self):
        B = "b" * 16
        C = "c" * 16
        older = with_manager(reported(started(B), R, issues=((21, "building"),),
                                      status="the second slice waits on a grant"))
        newer = dataclasses.replace(self.held, moved_ms=R + 10 * MIN)
        sprints = {A: newer, B: older}
        shown = derive_view([state("p00", 1)], sprints=sprints, now_ms=R + 80 * MIN)
        self.assertEqual([i["key"] for i in shown["inbox"]["open"]],
                         ["held-sprint/" + B, "held-sprint/" + A])
        self.assertEqual(shown["statement"]["inbox_items"], 2)
        stopped_one = dataclasses.replace(with_manager(reported(started(C), R)),
                                          no_progress_at=iso(R + 30 * MIN))
        shown = derive_view([state("p00", 1)], sprints={**sprints, C: stopped_one},
                            now_ms=R + 80 * MIN)
        self.assertEqual([i["reason"] for i in shown["inbox"]["open"]],
                         ["progress", "held_sprint", "held_sprint"])

    def test_the_held_sentence_is_used_only_when_held_cards_are_all_that_is_counted(self):
        shown = line(self.held, R + 61 * MIN, {("p00", "k9"): open_item("p00", "k9", 99)})
        self.assertEqual(shown["statement"]["inbox_items"], 2)
        self.assertEqual(shown["statement"]["sentence"], held_sprint.MIXED_SENTENCE)
        self.assertNotEqual(held_sprint.MIXED_SENTENCE, view.NEEDS_SENTENCE)
        self.assertNotIn("links to the tracker, where", held_sprint.MIXED_SENTENCE)

    def test_a_sprint_waiting_on_quota_raises_none_even_when_every_profile_is_out(self):
        now = R + 120 * MIN
        with self.subTest("own profile out"):
            shown = line(self.held, now, capacity=out())
            self.assertEqual(shown["inbox"]["open"], [])
            self.assertIsNone(entry(shown)["held_since"])
            self.assertEqual(entry(shown)["state"], "quota")
        with self.subTest("every profile out"):
            shown = line(self.held, now, capacity={**out(), "all_out": True})
            self.assertEqual(shown["inbox"]["open"], [])
            self.assertIsNone(entry(shown)["held_since"])
            statement = shown["statement"]
            self.assertEqual((statement["inbox_items"], statement["headline"], statement["sentence"]),
                             (0, view.ALL_OUT_HEADLINE, view.ALL_OUT_SENTENCE))
        with self.subTest("another profile out"):
            self.assertEqual(len(self.cards(line(self.held, now, capacity=out("home")))), 1)
        with self.subTest("a manager waiting on quota, every profile out"):
            waiting = dataclasses.replace(
                self.held, manager=Manager("waiting", T0, until=U, takeover=True))
            shown = line(waiting, now, capacity={**out(), "all_out": True})
            self.assertEqual(shown["inbox"]["open"], [])
            self.assertIsNone(entry(shown)["held_since"])
            self.assertEqual(shown["statement"]["headline"], view.ALL_OUT_HEADLINE)
        with self.subTest("a manager waiting on quota, no profile out"):
            waiting = dataclasses.replace(self.held, manager=Manager("waiting", T0, until=U))
            self.assertEqual(self.cards(line(waiting, now)), [])

