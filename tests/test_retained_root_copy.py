"""The retained tier runs on a private copy of its root (#573): a commit to the original cannot void the run (RP11)."""
import os, subprocess, tempfile, unittest
from pathlib import Path

from agent_tools.retained_root_copy import copy_root
from tests.test_review_retained_full import root_state

EVIDENCE = ".superpowers/review-evidence/100"
ENV = dict(os.environ, GIT_AUTHOR_NAME="f", GIT_AUTHOR_EMAIL="f@x", GIT_COMMITTER_NAME="f",
           GIT_COMMITTER_EMAIL="f@x", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], env=ENV, check=True, capture_output=True,
                          text=True).stdout.strip()


class RetainedRootCopyTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="root-copy-"))
        self.addCleanup(subprocess.run, ["rm", "-rf", str(tmp)])
        self.source, self.dest = tmp / "source", tmp / "copy"
        git(tmp, "init", "-q", "-b", "main", str(self.source))
        (self.source / "a.txt").write_text("a")
        (self.source / ".gitignore").write_text(".superpowers/\n")
        (self.source / EVIDENCE / "direct-100-000002").mkdir(parents=True)
        (self.source / EVIDENCE / "direct-100-000002/manifest.json").write_text("{}")
        git(self.source, "add", "-A")
        git(self.source, "-c", "commit.gpgsign=false", "commit", "-qm", "base")
        self.base = git(self.source, "rev-parse", "HEAD")

    def test_copy_carries_commits_and_ignored_evidence(self):
        copy_root(self.source, self.dest, EVIDENCE)
        self.assertEqual(git(self.dest, "cat-file", "-t", self.base), "commit")
        self.assertEqual(git(self.dest, "rev-parse", "HEAD"), self.base)
        self.assertEqual((self.dest / EVIDENCE / "direct-100-000002/manifest.json").read_text(), "{}")

    def test_commit_to_the_original_does_not_move_the_copy(self):
        copy_root(self.source, self.dest, EVIDENCE)
        before = root_state(self.dest)
        (self.source / "b.txt").write_text("b")
        git(self.source, "add", "-A")
        git(self.source, "-c", "commit.gpgsign=false", "commit", "-qm", "concurrent")
        git(self.source, "branch", "other")
        self.assertEqual(root_state(self.dest), before)

    def test_missing_evidence_is_refused(self):
        with self.assertRaises(FileNotFoundError):
            copy_root(self.source, self.dest, "nope")


if __name__ == "__main__":
    unittest.main()
