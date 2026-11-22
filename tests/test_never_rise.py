"""The comparison contract of `agent_tools.delivery.never_rise` (#1455).

Measures the comparison against real git worlds: each rule is counted on its own
on the merge base and on the head commit, and rises only when the branch count
exceeds the base count; a per-file rule rises for a file whose violation grew or
is new, following git renames; a new enforcer over existing violations passes;
only commits are read; no git child writes, fetches or follows an inherited
repository selection or forced colour; and a failed git read is no verdict.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import never_rise
from agent_tools.delivery.never_rise import (
    Enforcer, Rise, Snapshot, Violation)

TIER = "integration"

BAD = Enforcer("FX1", lambda snap: [
    Violation("FX1", p, 1) for p in sorted(snap.line_counts) if p.endswith(".bad")])
WORSE = Enforcer("FX3", lambda snap: [
    Violation("FX3", p, 1) for p in sorted(snap.line_counts) if p.endswith(".worse")])
LONG = Enforcer("FX2", lambda snap: [
    Violation("FX2", p, n) for p, n in sorted(snap.line_counts.items()) if n > 3],
    per_file=True)


def fixture_env(extra=None):
    env = {k: v for k, v in os.environ.items() if k not in never_rise.SELECTION_VARIABLES}
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "fixture", "GIT_COMMITTER_NAME": "fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid"})
    env.update(extra or {})
    return env


def git(root, *args, env=None):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60,
        check=True, env=env or fixture_env()).stdout


def repo(tmp):
    root = Path(tmp) / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    return root


def write(root, relative, text):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text)


def commit_all(root, message="commit"):
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def mark_base(root):
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return git(root, "rev-parse", "HEAD").strip()


def lines(count, prefix="line"):
    return "".join(f"{prefix} {n}\n" for n in range(count))


def recordings(root):
    return (git(root, "--no-optional-locks", "status", "--porcelain"),
            (Path(root) / ".git/index").stat().st_mtime_ns, git(root, "for-each-ref"))


def one_more_bad(root):
    """Base holds a.bad; the branch adds b.bad. Returns the base revision."""
    write(root, "a.bad", "x\n")
    commit_all(root)
    base = mark_base(root)
    write(root, "b.bad", "x\n")
    commit_all(root)
    return base


FIRST_RISES = (Rise("FX1", 1, 2, (Violation("FX1", "b.bad", 1),)),)


class NeverRiseTest(unittest.TestCase):
    def judge(self, root, enforcers=(BAD,)):
        return never_rise.judge(root, "main", list(enforcers), timeout=60)

    def test_one_more_violation_on_the_branch_fails_naming_the_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            base = one_more_bad(root)
            verdict = self.judge(root)
            self.assertEqual(verdict.rises, FIRST_RISES)
            self.assertEqual(verdict.merge_base, base)
            self.assertEqual(verdict.head, git(root, "rev-parse", "HEAD").strip())

    def test_the_same_count_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.bad", "x\n")
            commit_all(root)
            mark_base(root)
            write(root, "a.bad", "y\n")
            write(root, "c.txt", "z\n")
            commit_all(root)
            self.assertEqual(self.judge(root).rises, ())

    def test_fewer_violations_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.bad", "x\n")
            write(root, "b.bad", "x\n")
            commit_all(root)
            mark_base(root)
            git(root, "rm", "-q", "b.bad")
            commit_all(root)
            self.assertEqual(self.judge(root).rises, ())

    def test_each_rule_is_counted_on_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.bad", "x\n")
            write(root, "x.worse", "x\n")
            write(root, "y.worse", "x\n")
            commit_all(root)
            mark_base(root)
            write(root, "b.bad", "x\n")
            git(root, "rm", "-q", "y.worse")
            commit_all(root)
            self.assertEqual(self.judge(root, [BAD, WORSE]).rises, FIRST_RISES)

    def test_the_base_is_the_merge_base_not_the_integration_tip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.bad", "x\n")
            commit_all(root)
            base = git(root, "rev-parse", "HEAD").strip()
            git(root, "branch", "side")
            write(root, "b.bad", "x\n")
            commit_all(root)
            git(root, "checkout", "-q", "side")
            write(root, "c.bad", "x\n")
            commit_all(root)
            git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
            git(root, "checkout", "-q", "main")
            verdict = self.judge(root)
            self.assertEqual(verdict.merge_base, base)
            self.assertEqual(verdict.rises, FIRST_RISES)

    def test_a_rule_at_zero_rises_from_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "c.txt", "x\n")
            commit_all(root)
            mark_base(root)
            write(root, "a.bad", "x\n")
            commit_all(root)
            self.assertEqual(
                self.judge(root).rises, (Rise("FX1", 0, 1, (Violation("FX1", "a.bad", 1),)),))

    def test_a_renamed_violation_keeps_the_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.bad", "x\n")
            commit_all(root)
            mark_base(root)
            git(root, "mv", "a.bad", "d.bad")
            commit_all(root)
            self.assertEqual(self.judge(root).rises, ())

    def test_a_new_enforcer_with_existing_violations_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            for name in ("a.bad", "b.bad", "c.bad"):
                write(root, name, "x\n")
            commit_all(root)
            mark_base(root)
            write(root, "c.txt", "z\n")
            commit_all(root)
            self.assertEqual(self.judge(root).rises, ())

    def test_the_new_violations_name_only_the_added_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            one_more_bad(root)
            self.assertEqual(self.judge(root).rises[0].new, (Violation("FX1", "b.bad", 1),))

    def test_a_per_file_violation_that_grows_rises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "long.txt", lines(5))
            commit_all(root)
            mark_base(root)
            write(root, "long.txt", lines(6))
            commit_all(root)
            self.assertEqual(
                self.judge(root, [LONG]).rises,
                (Rise("FX2", 1, 1, (Violation("FX2", "long.txt", 6),)),))

    def test_a_per_file_violation_that_holds_passes(self):
        for case, text in (("same size", lines(5, "other")), ("smaller", lines(4))):
            with self.subTest(case), tempfile.TemporaryDirectory() as tmp:
                root = repo(tmp)
                write(root, "long.txt", lines(5))
                commit_all(root)
                mark_base(root)
                write(root, "long.txt", text)
                write(root, "unrelated.txt", "z\n")
                commit_all(root)
                self.assertEqual(self.judge(root, [LONG]).rises, ())

    def test_a_moved_per_file_violation_is_matched_to_its_source(self):
        for case, extra, rises in (
                ("unchanged", "", ()),
                ("grown", "one more\n", (Rise("FX2", 1, 1, (Violation("FX2", "moved.txt", 41),)),))):
            with self.subTest(case), tempfile.TemporaryDirectory() as tmp:
                root = repo(tmp)
                write(root, "long.txt", lines(40))
                commit_all(root)
                mark_base(root)
                git(root, "mv", "long.txt", "moved.txt")
                write(root, "moved.txt", lines(40) + extra)
                commit_all(root)
                self.assertEqual(self.judge(root, [LONG]).rises, rises)

    def test_a_move_git_does_not_pair_is_a_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "long.txt", lines(40, "before"))
            commit_all(root)
            mark_base(root)
            git(root, "rm", "-q", "long.txt")
            write(root, "other.txt", lines(40, "entirely different"))
            commit_all(root)
            self.assertEqual(
                self.judge(root, [LONG]).rises,
                (Rise("FX2", 1, 1, (Violation("FX2", "other.txt", 40),)),))

    def test_an_enforcer_emitting_another_rule_is_refused(self):
        snapshot = Snapshot("a" * 40, {"a": 1})
        stray = Enforcer("FX1", lambda snap: [Violation("FX9", "a", 1)])
        with self.assertRaises(ValueError):
            never_rise.compare(snapshot, snapshot, {}, [stray])

    def test_an_uncommitted_violation_is_not_judged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.txt", "x\n")
            commit_all(root)
            mark_base(root)
            write(root, "z.bad", "x\n")
            self.assertEqual(self.judge(root).rises, ())

    def test_judging_writes_nothing_to_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            one_more_bad(root)
            before = recordings(root)
            self.assertIsNotNone(self.judge(root))
            self.assertEqual(recordings(root), before)

    def test_a_partial_clone_missing_a_blob_is_no_verdict_and_fetches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "x.py", "x\n")
            commit_all(root)
            mark_base(root)
            bare = Path(tmp) / "bare.git"
            partial = Path(tmp) / "partial"
            git(root, "clone", "-q", "--bare", str(root), str(bare))
            git(bare, "config", "uploadpack.allowFilter", "true")
            git(Path(tmp), "clone", "-q", "--no-checkout", "--filter=blob:none",
                f"file://{bare}", str(partial))
            blob = git(partial, "rev-parse", "HEAD:x.py").strip()
            self.assertIsNone(never_rise.judge(partial, "main", [BAD], 60))
            probe = subprocess.run(
                ["git", "-C", str(partial), "cat-file", "-e", blob],
                env=fixture_env({"GIT_NO_LAZY_FETCH": "1"}), capture_output=True)
            self.assertNotEqual(probe.returncode, 0)

    def test_a_partial_clone_with_some_blobs_present_is_no_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.bad", "x\n")
            commit_all(root)
            base = mark_base(root)
            write(root, "b.bad", "padding line\n" * 200)
            commit_all(root)
            bare = Path(tmp) / "bare.git"
            partial = Path(tmp) / "partial"
            git(root, "clone", "-q", "--bare", str(root), str(bare))
            git(bare, "config", "uploadpack.allowFilter", "true")
            git(Path(tmp), "clone", "-q", "--no-checkout", "--filter=blob:limit=1k",
                f"file://{bare}", str(partial))
            git(partial, "update-ref", "refs/remotes/origin/main", base)
            present = git(partial, "rev-parse", "HEAD:a.bad").strip()
            missing = git(partial, "rev-parse", "HEAD:b.bad").strip()
            for blob, exit_code in ((present, 0), (missing, 1)):
                probe = subprocess.run(
                    ["git", "-C", str(partial), "cat-file", "-e", blob],
                    env=fixture_env({"GIT_NO_LAZY_FETCH": "1"}), capture_output=True)
                self.assertEqual(probe.returncode == 0, exit_code == 0)
            self.assertIsNone(never_rise.judge(partial, "main", [BAD], 60))

    def test_an_inherited_repository_selection_redirects_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "other"
            other.mkdir()
            git(other, "init", "-q", "-b", "main")
            write(other, "o.txt", "o\n")
            commit_all(other)
            before = recordings(other)
            selection = {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other),
                         "GIT_INDEX_FILE": str(other / ".git/index")}
            with mock.patch.dict(os.environ, selection):
                root = repo(tmp)
                one_more_bad(root)
                verdict = self.judge(root)
            self.assertEqual(verdict.rises, FIRST_RISES)
            self.assertEqual(verdict.head, git(root, "rev-parse", "HEAD").strip())
            self.assertEqual(recordings(other), before)

    def test_forced_colour_changes_no_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            git(root, "config", "color.ui", "always")
            write(root, "a.bad", "x\n")
            write(root, "long.txt", lines(40))
            commit_all(root)
            base = mark_base(root)
            write(root, "b.bad", "x\n")
            git(root, "mv", "long.txt", "moved.txt")
            commit_all(root)
            head = git(root, "rev-parse", "HEAD").strip()
            self.assertEqual(self.judge(root).rises, FIRST_RISES)
            snapshot = never_rise.read_snapshot(root, head, 60)
            self.assertEqual(
                dict(snapshot.line_counts), {"a.bad": 1, "b.bad": 1, "moved.txt": 40})
            self.assertEqual(
                never_rise.renames(root, base, head, 60), {"moved.txt": "long.txt"})

    def test_no_integration_ref_is_no_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.txt", "x\n")
            commit_all(root)
            self.assertIsNone(self.judge(root))
            self.assertIsNone(never_rise.revisions(root, "main", 60))

    def test_a_plain_directory_is_no_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self.judge(Path(tmp)))

    def test_the_snapshot_counts_lines_as_git_grep_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "x.py", "a\nb\nc")
            write(root, "y.py", "a\n")
            write(root, "z.py", "")
            write(root, "bin.dat", b"\0\1\2")
            commit_all(root)
            head = git(root, "rev-parse", "HEAD").strip()
            self.assertEqual(
                dict(never_rise.read_snapshot(root, head, 60).line_counts),
                {"x.py": 3, "y.py": 1})

    def test_a_violation_prints_rule_path_and_line(self):
        self.assertEqual(Violation("FX1", "a b/c.py", 7).text(), "FX1 a b/c.py:7")
        for path, expected in (
                ("a\nb.py", "FX1 a\\nb.py:7"), ("a\\b.py", "FX1 a\\\\b.py:7"),
                ("a\x1cb", "FX1 a\\x1cb:7"), ("a b", "FX1 a\\u2028b:7"),
                ("a\x85b\x7f", "FX1 a\\u0085b\\x7f:7")):
            with self.subTest(path=path):
                text = Violation("FX1", path, 7).text()
                self.assertEqual(text, expected)
                self.assertEqual(len(text.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
