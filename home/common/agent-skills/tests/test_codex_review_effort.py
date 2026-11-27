"""The Codex review effort is declared once (`agent_tools.delivery.codex_review_effort.EFFORT`).

Every copy agrees with it, a different declared value reaches every copy, and a copy that
disagrees is named.
"""

from pathlib import Path
import shutil
import tempfile
import unittest

from agent_tools.delivery import codex_review_effort, independent_review
from agent_tools.delivery.codex_review_effort import EFFORT, PATCH, SKILL

TIER = "fast"

REPO_ROOT = Path(__file__).parents[4]
OTHER = "medium" if EFFORT != "medium" else "low"


def copy_of_the_copies(test: unittest.TestCase) -> Path:
    root = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, root)
    for path in codex_review_effort._FILE_RULES:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / path, root / path)
    return root


class CodexReviewEffortTest(unittest.TestCase):
    def test_every_copy_agrees_with_the_declared_effort(self):
        self.assertEqual(codex_review_effort.disagreements(REPO_ROOT), [])

    def test_the_independent_review_reads_the_declared_effort(self):
        self.assertIs(independent_review.EFFORT, EFFORT)

    def test_a_different_declared_effort_reaches_every_copy(self):
        root = copy_of_the_copies(self)

        changed = codex_review_effort.write(root, OTHER)

        self.assertEqual(sorted(changed), sorted(codex_review_effort._FILE_RULES))
        self.assertEqual(codex_review_effort.disagreements(root, OTHER), [])
        self.assertEqual(sorted(codex_review_effort.disagreements(root, EFFORT)),
                         sorted(codex_review_effort._FILE_RULES))
        skill = (root / SKILL).read_text(encoding="utf-8")
        self.assertIn(f"--effort {OTHER} \\\n", skill)
        self.assertIn(f"`runtime.reasoningEffort` `{OTHER}`", skill)
        self.assertNotIn(f"--effort {EFFORT} ", skill)

    def test_a_copy_that_disagrees_is_named(self):
        for path in codex_review_effort._FILE_RULES:
            with self.subTest(path=path):
                root = copy_of_the_copies(self)
                (root / path).write_text(
                    codex_review_effort.render(
                        path, (root / path).read_text(encoding="utf-8"), OTHER),
                    encoding="utf-8")

                self.assertEqual(codex_review_effort.disagreements(root), [path])

    def test_the_patch_rewrite_stays_inside_the_reviewer_detach_test(self):
        root = copy_of_the_copies(self)
        before = (root / PATCH).read_text(encoding="utf-8")

        codex_review_effort.write(root, OTHER)

        after = (root / PATCH).read_text(encoding="utf-8")
        header = codex_review_effort._PATCH_HUNK_HEADER
        self.assertEqual(before.split(header, 1)[0], after.split(header, 1)[0])
        self.assertEqual(before.split(header, 1)[1].split("\ndiff --git ", 1)[1:],
                         after.split(header, 1)[1].split("\ndiff --git ", 1)[1:])

    def test_a_copy_missing_its_phrase_is_an_error_not_a_silent_skip(self):
        root = copy_of_the_copies(self)
        (root / SKILL).write_text("no effort here\n", encoding="utf-8")

        with self.assertRaises(codex_review_effort.CopyError):
            codex_review_effort.disagreements(root)


if __name__ == "__main__":
    unittest.main()
