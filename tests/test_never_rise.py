"""The comparison contract of `agent_tools.delivery.never_rise` (#1455).

Measures the comparison against real git worlds: each rule is counted on its own
on the merge base and on the head commit, and rises only when the branch count
exceeds the base count; a per-file rule rises for a file whose violation grew or
is new, following git renames; a new enforcer over existing violations passes;
only commits are read; no git child writes, fetches or follows an inherited
repository selection or forced colour; and a failed git read is no verdict.

The suite holds `standard:B17`, the 1,500-line size rule, by judging its enforcer
`agent_tools.delivery.size_lint` against real git worlds, so the rule index lists
this enforcer.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import never_rise, rule_ids, size_lint
from agent_tools.delivery.never_rise import (
    Enforcer, Rise, Snapshot, Violation)

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]
BAR = REPO_ROOT / "home/common/agent-skills/standards/the-bar.md"

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

    def test_a_diff_attribute_does_not_change_which_files_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, ".gitattributes", "hidden.py -diff\nbinary.py binary\nforced.dat diff\n")
            write(root, "hidden.py", lines(5))
            write(root, "binary.py", lines(4))
            write(root, "forced.dat", b"a\0b\n")
            write(root, "plain.py", lines(3))
            commit_all(root)
            head = git(root, "rev-parse", "HEAD").strip()
            self.assertEqual(
                dict(never_rise.read_snapshot(root, head, 60).line_counts),
                {".gitattributes": 3, "hidden.py": 5, "binary.py": 4, "plain.py": 3})

    def test_an_integration_branch_git_cannot_be_given_is_no_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            one_more_bad(root)
            self.assertIsNone(never_rise.judge(root, "ma\0in", [BAD], 60))
            self.assertIsNone(never_rise.revisions(root, "ma\0in", 60))

    def test_the_merge_base_belongs_to_the_head_that_was_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.txt", "x\n")
            commit_all(root)
            fork = git(root, "rev-parse", "HEAD").strip()
            git(root, "branch", "other")
            write(root, "b.txt", "x\n")
            commit_all(root)
            mark_base(root)
            git(root, "checkout", "-q", "-b", "feature", fork)
            write(root, "c.txt", "x\n")
            commit_all(root)
            first = git(root, "rev-parse", "HEAD").strip()
            git(root, "checkout", "-q", "other")
            git(root, "reset", "-q", "--hard", "main")
            real_run = subprocess.run
            moves = []

            def run_then_move_head(command, *args, **kwargs):
                done = real_run(command, *args, **kwargs)
                if not moves and "rev-parse" in command and any(
                        str(arg).startswith("HEAD") for arg in command):
                    moves.append(real_run(
                        ["git", "-C", str(root), "checkout", "-q", "other"],
                        env=fixture_env(), capture_output=True, check=True))
                return done
            git(root, "checkout", "-q", "feature")
            with mock.patch.object(never_rise.subprocess, "run", run_then_move_head):
                pair = never_rise.revisions(root, "main", 60)
            self.assertEqual(len(moves), 1)
            self.assertEqual(pair, (fork, first))

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

    def test_an_enforcer_that_cannot_judge_is_raised_not_passed(self):
        def find(snapshot):
            raise never_rise.EnforcerFailed("fx", "broken")
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            one_more_bad(root)
            broken = Enforcer("FX9", find)
            with self.assertRaises(never_rise.EnforcerFailed) as caught:
                self.judge(root, (BAD, broken))
            self.assertEqual(caught.exception.enforcer, "fx")
            self.assertEqual(caught.exception.reason, "broken")
            self.assertEqual(str(caught.exception), "fx: broken")

    def test_an_enforcer_whose_history_read_fails_is_no_verdict(self):
        def find(snapshot):
            raise never_rise.HistoryUnavailable()
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            one_more_bad(root)
            unreadable = Enforcer("FX8", find)
            self.assertIsNone(self.judge(root, (BAD, unreadable)))


def committed_snapshot(root):
    return never_rise.read_snapshot(root, never_rise.resolve_commit(root, "HEAD", 60), 60)


class SnapshotFilesTest(unittest.TestCase):
    def test_a_snapshot_reads_the_committed_bytes_not_the_working_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "pkg/a.py", "one\n")
            commit_all(root)
            write(root, "pkg/a.py", "two\n")
            snap = committed_snapshot(root)
            self.assertEqual(never_rise.read_files(snap, ["pkg/a.py"]), {"pkg/a.py": b"one\n"})
            self.assertEqual(snap.root, root)
            self.assertEqual(set(snap.files), {"pkg/a.py"})

    def test_a_symlink_is_counted_but_is_no_file_to_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.py", "x = 1\n")
            os.symlink("a.py", root / "link.py")
            commit_all(root)
            snap = committed_snapshot(root)
            with self.assertRaises(ValueError):
                never_rise.read_files(snap, ["link.py"])
            self.assertIn("link.py", snap.line_counts)
            self.assertNotIn("link.py", snap.files)

    def test_an_empty_file_is_a_file_with_no_line_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "pyproject.toml", "")
            write(root, "m.py", "x = 1\n")
            write(root, "b.bin", b"\0x")
            commit_all(root)
            snap = committed_snapshot(root)
            self.assertIn("pyproject.toml", snap.files)
            self.assertNotIn("pyproject.toml", snap.line_counts)
            self.assertNotIn("b.bin", snap.files)
            self.assertNotIn("b.bin", snap.line_counts)
            self.assertEqual(never_rise.read_files(snap, ["pyproject.toml"]),
                             {"pyproject.toml": b""})

    def test_a_hand_built_snapshot_reads_nothing(self):
        with self.assertRaises(ValueError):
            never_rise.read_files(Snapshot("a" * 40, {"a": 1}), ["a"])
        self.assertEqual(never_rise.read_files(Snapshot("a" * 40, {"a": 1}), []), {})

    def test_reading_files_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.py", "one\n")
            commit_all(root)
            snap = committed_snapshot(root)
            before = recordings(root)
            never_rise.read_files(snap, ["a.py"])
            self.assertEqual(recordings(root), before)

    def test_a_malformed_batch_is_history_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.py", "one\n")
            commit_all(root)
            snap = committed_snapshot(root)
            oid = snap.files["a.py"]
            other = "f" * 40
            answers = {
                "child failed": None,
                "another oid": f"{other} blob 4\none\n\n".encode(),
                "size not digits": f"{oid} blob x\none\n\n".encode(),
                "payload short": f"{oid} blob 9\none\n".encode(),
                "no terminator": f"{oid} blob 4\none\nX".encode(),
                "missing": f"{oid} missing\n".encode(),
                "not a blob": f"{oid} tree 4\none\n\n".encode(),
                "trailing bytes": f"{oid} blob 4\none\n\nextra".encode()}
            for name, answer in answers.items():
                with self.subTest(name):
                    with mock.patch.object(never_rise, "_git", return_value=answer):
                        with self.assertRaises(never_rise.HistoryUnavailable):
                            never_rise.read_files(snap, ["a.py"])
            self.assertEqual(never_rise.read_files(snap, ["a.py"]), {"a.py": b"one\n"})


def numbered(count):
    return "".join(f"{i}\n" for i in range(count))


class SizeRuleTest(unittest.TestCase):
    def judge(self, root):
        return never_rise.judge(root, "main", [size_lint.ENFORCER], timeout=60)

    def branch_over(self, base_files, change):
        """Commit `base_files` as the base, apply `change(root)` on the branch, judge."""
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            for path, count in base_files.items():
                write(root, path, numbered(count))
            write(root, "README", "x\n")
            commit_all(root)
            mark_base(root)
            change(root)
            commit_all(root)
            return self.judge(root).rises

    def test_an_over_budget_file_that_grows_fails(self):
        rises = self.branch_over(
            {"src/big.py": 1600}, lambda root: write(root, "src/big.py", numbered(1601)))
        self.assertEqual(rises, (Rise("B17", 1, 1, (Violation("B17", "src/big.py", 1601),)),))

    def test_an_over_budget_file_that_shrinks_passes(self):
        self.assertEqual(self.branch_over(
            {"src/big.py": 1600}, lambda root: write(root, "src/big.py", numbered(1599))), ())

    def test_an_over_budget_file_that_is_unchanged_passes(self):
        self.assertEqual(self.branch_over(
            {"src/big.py": 1600}, lambda root: write(root, "src/other.py", "x\n")), ())

    def test_growing_from_1400_to_1500_passes(self):
        self.assertEqual(self.branch_over(
            {"src/big.py": 1400}, lambda root: write(root, "src/big.py", numbered(1500))), ())

    def test_a_new_1501_line_file_fails(self):
        rises = self.branch_over(
            {}, lambda root: write(root, "src/new.py", numbered(1501)))
        self.assertEqual(rises, (Rise("B17", 0, 1, (Violation("B17", "src/new.py", 1501),)),))

    def test_an_extensionless_script_is_judged(self):
        for path, text in (
                ("bin/tool", "#!/bin/sh\n" + numbered(1500)),
                ("data/zshrc/common/50-fragment", numbered(1501))):
            with self.subTest(path=path):
                rises = self.branch_over({}, lambda root: write(root, path, text))
                self.assertEqual(rises, (Rise("B17", 0, 1, (Violation("B17", path, 1501),)),))

    def test_a_diff_attribute_does_not_hide_a_new_oversize_file(self):
        def add(root):
            write(root, ".gitattributes", "src/*.py -diff\n*.dat binary\n")
            write(root, "src/new.py", numbered(1501))
            write(root, "src/new.dat", numbered(1501))
        rises = self.branch_over({}, add)
        self.assertEqual(len(rises), 1)
        self.assertEqual(
            rises[0].new,
            (Violation("B17", "src/new.dat", 1501), Violation("B17", "src/new.py", 1501)))

    def test_a_long_document_or_data_file_is_not_judged(self):
        for path in ("docs/long.md", "data/table.json", "LICENSE"):
            with self.subTest(path=path):
                self.assertEqual(self.branch_over(
                    {}, lambda root: write(root, path, numbered(2000))), ())

    def test_a_moved_over_budget_file_that_holds_passes(self):
        self.assertEqual(self.branch_over(
            {"src/big.py": 1600}, lambda root: git(root, "mv", "src/big.py", "src/moved.py")), ())

    def test_a_moved_over_budget_file_that_grows_fails(self):
        def move_and_grow(root):
            git(root, "mv", "src/big.py", "src/moved.py")
            write(root, "src/moved.py", numbered(1601))
        rises = self.branch_over({"src/big.py": 1600}, move_and_grow)
        self.assertEqual(len(rises), 1)
        self.assertEqual(rises[0].new, (Violation("B17", "src/moved.py", 1601),))


class SizeLintOutputTest(unittest.TestCase):
    def run_command(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.size_lint", *arguments],
            capture_output=True, text=True, timeout=60, env=fixture_env())

    def committed(self, tmp, files):
        root = repo(tmp)
        for path, count in files.items():
            write(root, path, numbered(count))
        commit_all(root)
        return root

    def test_each_violation_prints_rule_path_and_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.committed(tmp, {"a.py": 1501, "b/c.py": 1502, "d.py": 10, "e.md": 2000})
            done = self.run_command("--repo-root", str(root))
            self.assertEqual((done.returncode, done.stdout), (1, "B17 a.py:1501\nB17 b/c.py:1502\n"))
        with tempfile.TemporaryDirectory() as tmp:
            root = self.committed(tmp, {"d.py": 10})
            done = self.run_command("--repo-root", str(root))
            self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_a_path_with_a_line_break_prints_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.committed(tmp, {"x\ny.py": 1501})
            done = self.run_command("--repo-root", str(root))
            self.assertEqual((done.returncode, done.stdout), (1, "B17 x\\ny.py:1501\n"))

    def test_a_subdirectory_root_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.committed(tmp, {"a.py": 1501, "docs/standards/s.md": 3})
            done = self.run_command("--repo-root", str(root / "docs/standards"))
            self.assertEqual((done.returncode, done.stdout), (2, ""))
            self.assertTrue(done.stderr.startswith("size-lint: "), done.stderr)

    def test_resolving_a_revision_fetches_nothing_in_a_partial_clone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "x.py", "x\n")
            commit_all(root)
            bare = Path(tmp) / "bare.git"
            partial = Path(tmp) / "partial"
            git(root, "clone", "-q", "--bare", str(root), str(bare))
            git(bare, "config", "uploadpack.allowFilter", "true")
            git(Path(tmp), "clone", "-q", "--no-checkout", "--filter=blob:none",
                f"file://{bare}", str(partial))
            blob = git(partial, "rev-parse", "HEAD:x.py").strip()
            self.assertIsNone(size_lint.resolve(partial, blob))
            probe = subprocess.run(
                ["git", "-C", str(partial), "cat-file", "-e", blob],
                env=fixture_env({"GIT_NO_LAZY_FETCH": "1"}), capture_output=True)
            self.assertNotEqual(probe.returncode, 0)

    def test_a_relative_root_exits_2(self):
        done = self.run_command("--repo-root", "repo")
        self.assertEqual(done.returncode, 2)
        self.assertTrue(done.stderr.startswith("size-lint: "))
        with tempfile.TemporaryDirectory() as tmp:
            root = self.committed(tmp, {"a.py": 1501})
            done = subprocess.run(
                [sys.executable, "-m", "agent_tools.delivery.size_lint", "--repo-root", "."],
                capture_output=True, text=True, timeout=60, env=fixture_env(), cwd=root)
            self.assertEqual((done.returncode, done.stdout), (2, ""))

    def test_the_rule_id_is_a_rule_of_the_bar(self):
        self.assertIn(size_lint.RULE_ID, rule_ids.sections(BAR.read_text(encoding="utf-8")))

    def test_the_command_is_a_row_of_the_command_table(self):
        table = (REPO_ROOT / "lib/agent-tools.nix").read_text("utf-8")
        self.assertIn('"size-lint" = "delivery.size_lint";', table)


if __name__ == "__main__":
    unittest.main()
