"""The comments the jargon check touched stay within the comment cap, B19 (120 characters a line).

Run: just agent-workflow-tests
"""
import unittest
from pathlib import Path

from agent_tools.delivery import comment_lint
from agent_tools.delivery.never_rise import Snapshot

TIER = "fast"

REPO_ROOT = Path(__file__).resolve().parents[1]
# The B19 violations each file already held on the merge base: a count that may fall and never rise.
BASE_COUNT = {"tests/fixtures/console/page-harness.js": 4, "tests/test_console_page.py": 2}


class CommentWidthTest(unittest.TestCase):
    def test_the_page_test_and_its_harness_add_no_comment_over_the_cap(self):
        contents = {path: (REPO_ROOT / path).read_bytes() for path in BASE_COUNT}
        found = comment_lint.enforcers(None)[1].find(Snapshot("a" * 40, {}, contents=contents))
        for path, base in BASE_COUNT.items():
            with self.subTest(path=path):
                self.assertLessEqual(len([v for v in found if v.path == path]), base)


if __name__ == "__main__":
    unittest.main()
