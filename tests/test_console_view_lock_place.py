"""The sprint's now-sentence names its place in the land queue; the fixtures are those of `test_console_view`."""
import unittest

from agent_tools.console import view

from .test_console_view import MIN, SprintWaitViewTest, moving

TIER = "fast"


class LockPlaceViewTest(SprintWaitViewTest):
    def test_a_lock_wait_with_a_known_place_names_its_position(self):
        now = self.now
        shown = self.shown(moving(locks=((4, now - MIN),), positions=((4, 2), (9, 1))))
        self.assertEqual(shown["now_text"], "waiting its turn to merge, position 2")
        both = self.shown(moving(locks=((4, now - MIN),), positions=((4, 3), (5, 2), (9, 1))))
        self.assertEqual(both["now_text"], "waiting its turn to merge, position 2")
        self.assertEqual(view.fresh_wait(view.WaitSignals(lock_ms=now - MIN, lock_position=2), now),
                         "waiting its turn to merge, position 2")

    def test_a_lock_wait_with_no_known_place_reads_as_before(self):
        now = self.now
        self.assertEqual(view.fresh_wait(view.WaitSignals(lock_ms=now - MIN), now),
                         "waiting its turn to merge")
        self.assertEqual(self.shown(moving(locks=((4, now - MIN),), positions=((9, 1),)))["now_text"],
                         "waiting its turn to merge")
        ahead = view.WaitSignals(ci_ms=now - MIN, lock_ms=now - MIN, lock_position=2)
        self.assertEqual(view.fresh_wait(ahead, now), "waiting for CI on its pull request")


def load_tests(loader, tests, pattern):
    """Only the tests above: the inherited ones run in their own module."""
    return unittest.TestSuite(
        LockPlaceViewTest(name) for name in (
            "test_a_lock_wait_with_a_known_place_names_its_position",
            "test_a_lock_wait_with_no_known_place_reads_as_before"))
