"""The done-for-now heading of the view: its working count, sentence and next expected time (#1810); the fixtures are those of `test_console_view`."""
import dataclasses
import unittest
from datetime import datetime

from agent_tools.console.view import ReadState, derive_view

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_view import A, MIN, R, closed, iso, open_item, reported, started, state, stopped

TIER = "fast"


class DoneForNowViewTest(unittest.TestCase):
    def waiting(self, sid, until_ms):
        return self.waiting_at(sid, iso(until_ms))

    def waiting_at(self, sid, until):
        it = reported(started(sid), R)
        return dataclasses.replace(it, report=dataclasses.replace(it.report, wait_until=until))

    def test_with_nothing_open_the_statement_says_the_owner_is_done_for_now(self):
        B = "b" * 16
        result = derive_view([state("p00", 1)],
                             sprints={A: reported(started(A), R), B: reported(started(B), R)},
                             now_ms=R + MIN)
        self.assertEqual(result["statement"], {
            "inbox_items": 0, "headline": "You're done for now",
            "sentence": "2 sprints are working; we'll put anything that needs you here.",
            "stale": False})
        self.assertEqual(set(result["statement"]), {"inbox_items", "headline", "sentence", "stale"})

    def test_the_working_count_reads_only_running_sprints(self):
        B, C = "b" * 16, "c" * 16
        running = reported(started(A), R)
        table = {
            "one running": (
                [state("p00", 1)], {A: running}, R + MIN, "You're done for now",
                "1 sprint is working; we'll put anything that needs you here."),
            "closed and stopping sprints are not working": (
                [state("p00", 1)],
                {A: running,
                 B: closed(reported(started(B), R), R + 2 * MIN, ((12, "landed"),)),
                 C: stopped(reported(started(C), R), R + 2 * MIN)},
                R + 3 * MIN, "You're done for now",
                "1 sprint is working; we'll put anything that needs you here."),
            "no sprint": (
                [state("p00", 1)], {}, R + MIN, "You're done for now",
                "No sprint is working; we'll put anything that needs you here."),
            "no project": ([], {}, R + MIN, "Nothing needs you", "No project is registered yet."),
        }
        for name, (states, sprints, now_ms, headline, sentence) in table.items():
            with self.subTest(name):
                shown = derive_view(states, sprints=sprints, now_ms=now_ms)["statement"]
                self.assertEqual((shown["headline"], shown["sentence"]), (headline, sentence))

    def test_the_done_for_now_view_names_the_earliest_stated_wait(self):
        B = "b" * 16
        result = derive_view(
            [state("p00", 1)],
            sprints={A: self.waiting(A, R + 120 * MIN), B: self.waiting(B, R + 60 * MIN)},
            now_ms=R + MIN)
        self.assertEqual(result["next_expected"], iso(R + 60 * MIN))
        self.assertEqual(result["statement"]["headline"], "You're done for now")

    def test_waits_inside_one_millisecond_compare_at_full_precision(self):
        B = "b" * 16
        stamp = datetime.fromisoformat(iso(R + 60 * MIN))
        late, early = (stamp.replace(microsecond=micro).isoformat() for micro in (900, 100))
        result = derive_view(
            [state("p00", 1)],
            sprints={A: self.waiting_at(A, late), B: self.waiting_at(B, early)}, now_ms=R + MIN)
        self.assertEqual(result["next_expected"], early)

    def test_next_expected_is_null_unless_the_owner_is_done_for_now(self):
        paused = reported(started(A), R)
        paused = dataclasses.replace(
            paused, report=dataclasses.replace(paused.report, paused="the vendor answers tomorrow"))
        ahead = self.waiting(A, R + 60 * MIN)
        table = {
            "the wait has passed": dict(
                states=[state("p00", 1)], sprints={A: ahead}, now_ms=R + 61 * MIN),
            "a pause": dict(states=[state("p00", 1)], sprints={A: paused}, now_ms=R + MIN),
            "an open item": dict(
                states=[state("p00", 1)], sprints={A: ahead}, now_ms=R + MIN,
                records={("p00", "k1"): open_item("p00", "k1", 1)}),
            "a stale tracker": dict(
                states=[state("p00", 1)], sprints={A: ahead}, now_ms=R + MIN,
                health={"p00": ReadState(False, None)}),
            "no sprint": dict(states=[state("p00", 1)]),
        }
        for name, kwargs in table.items():
            with self.subTest(name):
                shown = derive_view(kwargs.pop("states"), **kwargs)
                self.assertIsNone(shown["next_expected"])
