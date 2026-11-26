"""The console's credential check stays fast on a 96 KiB answer, whatever its shape.

The time is the CPU time of the calling thread (`time.thread_time()`), the best of
several calls, so a loaded runner descheduling the thread cannot fail it (#1835). The
bound sits well above a linear check's cost and well below a quadratic one's.

Run: just agent-workflow-tests
"""

import time
import unittest

from agent_tools.console import project_question

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"

GITHUB_TOKEN = "gh" + "p_" + "a1b2c3" * 6
SIZE = 96 * 1024
PROSE = "This answer reads src/foo/bar.py and explains why the build passes. "
CPU_BOUND_SECONDS = 0.1
CALLS = 5


def best_cpu_seconds(check, text, calls=CALLS):
    """The least CPU time of the calling thread over `calls` calls of `check(text)`, and its last answer."""
    best = None
    found = None
    for _ in range(calls):
        started = time.thread_time()
        found = check(text)
        elapsed = time.thread_time() - started
        best = elapsed if best is None else min(best, elapsed)
    return best, found


def quadratic_check(text):
    """A credential check that rescans the rest of the answer from every position."""
    for start in range(len(text)):
        text.count("ab", start)
    return False


class CredentialTimingTest(unittest.TestCase):
    def assert_checked_in_time(self, check, text, calls=CALLS):
        """Fail unless the best CPU time of `check(text)` is under the bound; return its answer."""
        elapsed, found = best_cpu_seconds(check, text, calls)
        self.assertLess(elapsed, CPU_BOUND_SECONDS)
        return found

    def test_a_96_kib_answer_is_checked_in_under_100_ms_of_cpu_whatever_its_shape(self):
        answers = {
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
        for name, text in answers.items():
            with self.subTest(name=name):
                self.assertLessEqual(len(text), SIZE + len(GITHUB_TOKEN))
                found = self.assert_checked_in_time(project_question.credential_shaped, text)
                self.assertIs(found, name == "prose then a token")

    def test_a_quadratic_check_fails_the_timing_assertion_on_the_same_answers(self):
        with self.assertRaises(AssertionError):
            self.assert_checked_in_time(quadratic_check, "token=" * (SIZE // 6), calls=1)


if __name__ == "__main__":
    unittest.main()
