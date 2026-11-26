"""The console's credential check stays fast on a 96 KiB answer, whatever its shape.

The time is the CPU time of the calling thread (`time.thread_time()`), the best of
several calls, so a loaded runner descheduling the thread cannot fail it. The
bound is below a quadratic check's cost and, by the figures the suite logs, at
least 5 times the linear check's cost on a hosted runner. That margin is read
from the log, not asserted, so a slower runner cannot fail a correct check
that is still under the bound.

Run: just agent-workflow-tests
"""

import contextlib
import io
import sys
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


def report(label, seconds):
    """Write one measured figure to stderr, which the suite runner prints for a passing member too."""
    print(f"credential timing: {label} {seconds:.3f} s (bound {CPU_BOUND_SECONDS} s)",
          file=sys.stderr, flush=True)


class CredentialTimingTest(unittest.TestCase):
    def assert_checked_in_time(self, check, text, calls=CALLS, figures=None):
        """Fail unless every call answers correctly and the best CPU time of `check(text)` is under the bound.

        Each answer is checked outside its timed interval, so a fast wrong call cannot set the
        minimum. The best time goes to `figures` before the bound is asserted.
        """
        expected = holds_a_token(text)
        best = None
        for _ in range(calls):
            started = time.thread_time()
            found = check(text)
            elapsed = time.thread_time() - started
            self.assertIs(found, expected)
            best = elapsed if best is None else min(best, elapsed)
        if figures is not None:
            figures.append(best)
        self.assertLess(best, CPU_BOUND_SECONDS)

    def check_every_shape(self, check, shapes, calls=CALLS):
        """Run the timing assertion for `check` over each named shape and log the slowest best time."""
        figures = []
        try:
            for name, text in shapes.items():
                with self.subTest(name=name):
                    self.assertLessEqual(len(text), SIZE + len(GITHUB_TOKEN))
                    self.assert_checked_in_time(check, text, calls=calls, figures=figures)
        finally:
            if figures:
                report("linear check, slowest shape's best of five", max(figures))

    def test_a_96_kib_answer_is_checked_in_under_1_s_of_cpu_whatever_its_shape(self):
        self.check_every_shape(project_question.credential_shaped, answers())

    def test_a_correct_check_costing_a_quarter_second_is_under_the_bound(self):
        def quarter_second_check(text):
            until = time.thread_time() + 0.25
            while time.thread_time() < until:
                pass
            return holds_a_token(text)

        shapes = {"prose": answers()["prose"]}
        self.check_every_shape(quarter_second_check, shapes, calls=1)

    def test_a_quadratic_check_fails_the_timing_assertion_on_every_answer_shape(self):
        figures = []
        try:
            for name, text in answers().items():
                with self.subTest(name=name):
                    with self.assertRaisesRegex(AssertionError, "not less than"):
                        self.assert_checked_in_time(quadratic_check, text, calls=1, figures=figures)
        finally:
            if figures:
                report("quadratic stub, fastest shape's single call", min(figures))

    def test_a_measured_figure_is_written_to_stderr_with_its_label_and_the_bound(self):
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            report("linear check", 0.0194)
        self.assertEqual(captured.getvalue(), "credential timing: linear check 0.019 s (bound 1.0 s)\n")

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
