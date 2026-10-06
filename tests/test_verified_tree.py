"""verified-tree: a full verification pass recorded against the tree it saw (#263).

Each test drives `python -m agent_tools.verified_tree` in a throwaway git
repository, the way test_launch_commit.py drives its command (per D6).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
SCRUBBED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES")
IDS = ("nix-build", "agent-workflow-tests")


def verification_args(ids):
    return [arg for verification in ids for arg in ("--verification", verification)]


class VerifiedTreeTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name).resolve()
        self.repo = self.scratch / "repo"
        self.repo.mkdir()
        self.env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
        self.env.update(HERMETIC_GIT)
        self.git("init", "-q")
        self.git("config", "commit.gpgsign", "false")  # throwaway fixture repo
        (self.repo / ".gitignore").write_text("result\n")
        (self.repo / "src.py").write_text("x = 1\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_src.py").write_text("assert True\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, capture_output=True,
                              text=True, check=True, env=self.env).stdout.strip()

    def run_tool(self, *args, cwd=None, env=None):
        return subprocess.run([sys.executable, "-m", "agent_tools.verified_tree", *args],
                              cwd=cwd or self.repo, capture_output=True, text=True,
                              check=False, env=env or self.env)

    def check(self, ids=IDS, cwd=None):
        done = self.run_tool("check", *verification_args(ids), cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.count("\n"), 1, done.stdout)
        return json.loads(done.stdout)

    def record(self, tree, ids=IDS, cwd=None):
        return self.run_tool("record", "--tree", tree, *verification_args(ids), cwd=cwd)

    def record_path(self, cwd=None):
        return Path(self.git("rev-parse", "--absolute-git-dir", cwd=cwd)) / "verified-tree.json"

    def verify_and_record(self, ids=IDS, cwd=None):
        tree = self.check(ids, cwd=cwd)["tree"]
        done = self.record(tree, ids, cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, '{"recorded":true,"tree":"%s"}\n' % tree)
        return tree

    def test_no_record_is_unverified_and_names_the_head_tree(self):
        done = self.run_tool("check", *verification_args(IDS))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, '{"status":"unverified","tree":"%s"}\n'
                         % self.git("rev-parse", "HEAD^{tree}"))
        self.assertFalse(self.record_path().exists())

    def test_a_pass_is_recorded_and_then_verified(self):
        tree = self.verify_and_record()
        self.assertEqual(tree, self.git("rev-parse", "HEAD^{tree}"))
        self.assertEqual(json.loads(self.record_path().read_text()),
                         {"schema": "verified-tree/v1", "tree": tree, "verification": list(IDS)})
        self.assertEqual(self.check(), {"status": "verified", "tree": tree})

    def test_any_change_after_the_pass_is_unverified(self):
        changes = {
            "source edit": lambda: (self.repo / "src.py").write_text("x = 2\n"),
            "test edit": lambda: (self.repo / "tests/test_src.py").write_text("assert 1\n"),
            "new untracked file": lambda: (self.repo / "new.py").write_text("y = 1\n"),
            "deleted file": lambda: (self.repo / "src.py").unlink(),
        }
        for name, change in changes.items():
            with self.subTest(name):
                self.git("reset", "-q", "--hard")
                self.git("clean", "-qfd")
                tree = self.verify_and_record()
                change()
                answer = self.check()
                self.assertEqual(answer["status"], "unverified")
                self.assertNotEqual(answer["tree"], tree)

    def test_an_ignored_file_leaves_the_tree_verified(self):
        tree = self.verify_and_record()
        (self.repo / "result").write_text("build output\n")
        self.assertEqual(self.check(), {"status": "verified", "tree": tree})

    def test_a_different_verification_list_is_unverified(self):
        tree = self.verify_and_record()
        for ids in (("nix-build",), ("agent-workflow-tests", "nix-build"), (*IDS, "lint")):
            with self.subTest(ids=ids):
                self.assertEqual(self.check(ids), {"status": "unverified", "tree": tree})

    def test_a_mismatched_tree_is_refused_and_the_record_kept(self):
        tree = self.verify_and_record()
        before = self.record_path().read_bytes()
        (self.repo / "src.py").write_text("x = 3\n")
        current = self.check()["tree"]
        done = self.record(tree)
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertEqual(done.stdout,
                         '{"reason":"tree_changed","recorded":false,"tree":"%s"}\n' % current)
        self.assertEqual(self.record_path().read_bytes(), before)

    def test_a_refused_first_record_writes_no_file(self):
        stale = self.check()["tree"]
        (self.repo / "src.py").write_text("x = 4\n")
        self.assertEqual(self.record(stale).returncode, 3)
        self.assertFalse(self.record_path().exists())

    def test_an_uncommitted_verified_edit_stays_verified_once_committed(self):
        (self.repo / "src.py").write_text("x = 5\n")
        (self.repo / "added.py").write_text("z = 1\n")
        tree = self.verify_and_record()
        self.assertNotEqual(tree, self.git("rev-parse", "HEAD^{tree}"))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "fix")
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}"), tree)
        self.assertEqual(self.check(), {"status": "verified", "tree": tree})

    def test_neither_verb_touches_the_real_index(self):
        (self.repo / "src.py").write_text("x = 6\n")
        (self.repo / "new.py").write_text("n = 1\n")
        status = self.git("status", "--porcelain")
        index = Path(self.git("rev-parse", "--absolute-git-dir")) / "index"
        before = index.read_bytes()
        self.verify_and_record()
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(self.git("status", "--porcelain"), status)

    def test_the_record_lives_in_a_linked_worktrees_own_git_dir(self):
        linked = self.scratch / "linked"
        self.git("worktree", "add", "-q", "-b", "side", str(linked))
        tree = self.verify_and_record(cwd=linked)
        self.assertTrue(self.record_path(cwd=linked).is_file())
        self.assertFalse(self.record_path().exists())
        self.assertEqual(self.check(), {"status": "unverified", "tree": tree})
        self.assertEqual(self.check(cwd=linked), {"status": "verified", "tree": tree})

    def test_a_malformed_record_makes_check_exit_2(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        good = {"schema": "verified-tree/v1", "tree": tree, "verification": list(IDS)}
        cases = {
            "not json": "{",
            "duplicate key": '{"schema":"verified-tree/v1","schema":"verified-tree/v1",'
                             '"tree":"%s","verification":["nix-build"]}' % tree,
            "non-finite literal": '{"schema":"verified-tree/v1","tree":"%s",'
                                  '"verification":["nix-build"],"x":NaN}' % tree,
            "not an object": json.dumps([good]),
            "extra key": json.dumps({**good, "head": "x"}),
            "missing key": json.dumps({k: v for k, v in good.items() if k != "verification"}),
            "wrong schema": json.dumps({**good, "schema": "verified-tree/v2"}),
            "tree not a string": json.dumps({**good, "tree": 7}),
            "tree not hex": json.dumps({**good, "tree": "HEAD"}),
            "empty verification": json.dumps({**good, "verification": []}),
            "non-string id": json.dumps({**good, "verification": ["nix-build", 1]}),
            "empty id": json.dumps({**good, "verification": [""]}),
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.record_path().write_text(body)
                done = self.run_tool("check", *verification_args(IDS))
                self.assertEqual(done.returncode, 2, done.stdout)
                self.assertEqual(done.stdout, "")
                self.assertEqual(len(done.stderr.strip().splitlines()), 1, done.stderr)

    def test_outside_a_git_worktree_both_verbs_exit_2(self):
        outside = self.scratch / "outside"
        outside.mkdir()
        env = {**self.env, "GIT_CEILING_DIRECTORIES": str(self.scratch)}
        for argv in (("check", *verification_args(IDS)),
                     ("record", "--tree", "0" * 40, *verification_args(IDS))):
            with self.subTest(argv[0]):
                done = self.run_tool(*argv, cwd=outside, env=env)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")

    def test_usage_errors_exit_2(self):
        for argv in ((), ("check",), ("record", *verification_args(IDS)),
                     ("record", "--tree", "0" * 40), ("forget",)):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_tool(*argv).returncode, 2)


if __name__ == "__main__":
    unittest.main()
