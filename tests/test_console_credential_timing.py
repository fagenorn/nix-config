"""The console's credential check stays fast on a 96 KiB answer (#1726), whatever its shape.

Run: just agent-workflow-tests
"""

import time
import unittest

from agent_tools.console import project_question

GITHUB_TOKEN = "gh" + "p_" + "a1b2c3" * 6
SIZE = 96 * 1024
PROSE = "This answer reads src/foo/bar.py and explains why the build passes. "


class CredentialTimingTest(unittest.TestCase):
    def test_a_96_kib_answer_is_checked_in_under_50_ms_whatever_its_shape(self):
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
                started = time.perf_counter()
                found = project_question.credential_shaped(text)
                elapsed = time.perf_counter() - started
                self.assertIs(found, name == "prose then a token")
                self.assertLess(elapsed, 0.05)


if __name__ == "__main__":
    unittest.main()
