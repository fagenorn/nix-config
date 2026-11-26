"""The console's credential check stays fast on a 96 KiB answer, whatever its shape.

The time is the CPU time of the calling thread (`time.thread_time()`), the best of
several calls, so a loaded runner descheduling the thread cannot fail it. The
bound is at least 5 times the linear check's cost on a hosted runner and below
a quadratic one's.

Run: just agent-workflow-tests
"""

import time
import unittest
from pathlib import Path

from agent_tools.console import project_question
from agent_tools.delivery import comment_lint
from agent_tools.delivery.never_rise import Snapshot

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"

GITHUB_TOKEN = "gh" + "p_" + "a1b2c3" * 6
SIZE = 96 * 1024
PROSE = "This answer reads src/foo/bar.py and explains why the build passes. "
CPU_BOUND_SECONDS = 1.0
CALLS = 5


def answers():
    """Every answer shape, by name: the shared fixture table both tests run over."""
    return {
        "prose": PROSE * (SIZE // len(PROSE) + 1),
        "prose then a token": (PROSE * (SIZE // len(PROSE)))[:SIZE] + GITHUB_TOKEN,
        "one long lowercase run": "ab12" * (SIZE // 4),
        "dotted words": "a." * (SIZE // 2),
        "hyphenated words": "a-" * (SIZE // 2),
        "repeated jwt head": "eyJaaaaaaaa-" * (SIZE // 12),
        "repeated lowercase words": "aaaaaaaa" * (SIZE // 8),
        "repeated assignment name": "token=" * (SIZE // 6),
        "repeated dotted assignment name": "token." * (SIZE // 6),
        "many short path parts": "aaa/" * (SIZE // 4),
        "many mixed path parts": "Ab1/" * (SIZE // 4),
        "long padded run": "Aa1" * 11 + "=" * (SIZE - 33),
    }


def holds_a_token(text):
    """The credential answer for a fixture, independent of the code under test."""
    return GITHUB_TOKEN in text


def quadratic_check(text):
    """A correct credential check that first rescans the rest of the answer from every position."""
    for start in range(len(text)):
        text[start:].upper().lower()
    return holds_a_token(text)


class CredentialTimingTest(unittest.TestCase):
    def assert_checked_in_time(self, check, text, calls=CALLS):
        """Fail unless every call answers correctly and the best CPU time of `check(text)` is under the bound.

        The answer of each call is checked outside its timed interval, so a fast wrong call
        cannot set the minimum while a slow right one satisfies the correctness assertion.
        """
        expected = holds_a_token(text)
        best = None
        for _ in range(calls):
            started = time.thread_time()
            found = check(text)
            elapsed = time.thread_time() - started
            self.assertIs(found, expected)
            best = elapsed if best is None else min(best, elapsed)
        self.assertLess(best, CPU_BOUND_SECONDS)

    def test_a_96_kib_answer_is_checked_in_under_1_s_of_cpu_whatever_its_shape(self):
        for name, text in answers().items():
            with self.subTest(name=name):
                self.assertLessEqual(len(text), SIZE + len(GITHUB_TOKEN))
                self.assert_checked_in_time(project_question.credential_shaped, text)

    def test_a_quadratic_check_fails_the_timing_assertion_on_every_answer_shape(self):
        for name, text in answers().items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(AssertionError, "not less than"):
                    self.assert_checked_in_time(quadratic_check, text, calls=1)

    def test_this_file_s_comments_carry_no_issue_reference_length_or_marker_violation(self):
        path = Path(__file__)
        snapshot = Snapshot("a" * 40, {}, contents={path.name: path.read_bytes()})
        for enforcer in comment_lint.enforcers(None):
            with self.subTest(rule=enforcer.rule):
                self.assertEqual(enforcer.find(snapshot), [])

    def test_a_fast_wrong_call_cannot_set_the_minimum_for_a_slow_right_one(self):
        calls = []

        def wrong_then_right(text):
            calls.append(None)
            if len(calls) == 1:
                return False
            return holds_a_token(text)

        with self.assertRaisesRegex(AssertionError, "False is not True"):
            self.assert_checked_in_time(wrong_then_right, answers()["prose then a token"])


if __name__ == "__main__":
    unittest.main()
