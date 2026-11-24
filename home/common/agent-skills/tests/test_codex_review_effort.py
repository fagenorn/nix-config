"""No Codex review copy declares `--effort xhigh`: the review runs at effort high."""

from pathlib import Path
import unittest

TIER = "fast"

REPO_ROOT = Path(__file__).parents[4]
COLLABORATION = (
    REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/SKILL.md"
)


class CodexReviewEffortTest(unittest.TestCase):
    def test_no_codex_review_copy_declares_effort_xhigh(self):
        for path in (
            COLLABORATION,
            REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/evals/evals.json",
            REPO_ROOT / "python/agent_tools/delivery/independent_review.py",
        ):
            with self.subTest(path=path.name):
                self.assertNotIn("xhigh", path.read_text(encoding="utf-8"))

    def test_patched_plugin_reviewer_detach_test_declares_no_effort_xhigh(self):
        # The patch also carries a legitimate xhigh in the CLI usage
        # enumeration, so scope the search to the added reviewer-detach test.
        patch = (
            REPO_ROOT / "patches/agent-plugins/codex-plugin-cc.patch"
        ).read_text(encoding="utf-8")
        header = "diff --git a/tests/reviewer-detach.test.mjs b/tests/reviewer-detach.test.mjs\n"
        self.assertEqual(patch.count(header), 1)
        hunk = patch.split(header, 1)[1].split("\ndiff --git ", 1)[0]
        self.assertIn('"--effort", "high"', hunk)
        self.assertNotIn("xhigh", hunk)


if __name__ == "__main__":
    unittest.main()
