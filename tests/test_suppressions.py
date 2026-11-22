"""The suppression marker's count and listing (#1459, ADR-project-contract-017).

Measures, against real git worlds, that a reasoned marker naming an enforcer's rule
takes that rule's findings off the count on its line, that a marker with no reason
(or a bare one naming the rule) is counted as a violation of its own, that an
id-less marker counts under the rule whose finding sits on its line, and that the
never-rise verdict lists each reasoned suppression the branch adds, without failing
the check for it. `size-lint` prints the same count.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import never_rise
from agent_tools.delivery.never_rise import (
    Enforcer, Rise, Suppression, Violation, counted)

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]

BAD = Enforcer("FX1", lambda snap: [
    Violation("FX1", p, 1) for p in sorted(snap.line_counts) if p.endswith(".bad")])
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


def suppress(token, reason=""):
    return "suppress" + "-standard:" + token + (" " + reason if reason else "")


def snapshot_of(root):
    return never_rise.read_snapshot(root, git(root, "rev-parse", "HEAD").strip(), timeout=60)


v = Violation("FX1", "a.bad", 1)


class SuppressionCountTest(unittest.TestCase):
    def counted_in(self, files, enforcer=BAD):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            for name, text in files.items():
                write(root, name, text)
            commit_all(root)
            snapshot = snapshot_of(root)
            return counted(enforcer, snapshot), snapshot

    def test_a_reasoned_suppression_on_a_violating_line_is_not_counted(self):
        result, snapshot = self.counted_in(
            {"a.bad": "x  # " + suppress("FX1", "generated fixture") + "\n"})
        self.assertEqual(result, ([], []))
        self.assertEqual(
            snapshot.suppressions, (Suppression("FX1", "a.bad", 1, "generated fixture"),))

    def test_the_same_line_without_its_reason_is_counted(self):
        result, _ = self.counted_in({"a.bad": "x  # " + suppress("FX1") + "\n"})
        self.assertEqual(result, ([v], [v]))

    def test_the_same_line_without_its_id_is_counted_under_the_findings_rule(self):
        result, _ = self.counted_in({"a.bad": "x  # " + suppress("", "generated fixture") + "\n"})
        self.assertEqual(result, ([v], [v]))

    def test_a_marker_with_no_id_and_no_finding_counts_nothing(self):
        result, _ = self.counted_in({"a.ok": "# " + suppress("", "why") + "\n"})
        self.assertEqual(result, ([], []))

    def test_a_bare_marker_naming_the_rule_counts_off_a_finding(self):
        result, _ = self.counted_in({"a.ok": "# " + suppress("FX1") + "\n"})
        self.assertEqual(result, ([], [Violation("FX1", "a.ok", 1)]))

    def test_a_suppression_of_another_rule_suppresses_nothing(self):
        result, _ = self.counted_in({"a.bad": "x  # " + suppress("FX9", "other rule") + "\n"})
        self.assertEqual(result, ([v], []))

    def test_a_comment_closer_is_no_reason(self):
        with self.subTest("html"):
            result, _ = self.counted_in({"a.bad": "<!-- " + suppress("FX1") + " -->\n"})
            self.assertEqual(result, ([v], [v]))
        with self.subTest("block"):
            result, snapshot = self.counted_in(
                {"a.bad": "/* " + suppress("FX1", "generated") + " */\n"})
            self.assertEqual(result, ([], []))
            self.assertEqual(snapshot.suppressions[0].reason, "generated")

    def test_a_marker_glued_to_a_word_is_no_marker(self):
        result, snapshot = self.counted_in({"a.bad": "x" + suppress("FX1", "why") + "\n"})
        self.assertEqual(snapshot.suppressions, ())
        self.assertEqual(result, ([v], []))

    def test_a_marker_in_a_binary_file_is_not_read(self):
        _, snapshot = self.counted_in(
            {"a.bin": b"\0" + ("# " + suppress("FX1") + "\n").encode()})
        self.assertEqual(snapshot.suppressions, ())

    def test_a_suppression_prints_rule_path_line_and_reason(self):
        text = Suppression("FX1", "a\nb.py", 3, "why\tnot").text()
        self.assertEqual(text, "FX1 a\\nb.py:3 why\\tnot")
        self.assertEqual(len(text.splitlines()), 1)


class NeverRiseSuppressionTest(unittest.TestCase):
    def judge(self, root, enforcers=(BAD,)):
        return never_rise.judge(root, "main", list(enforcers), timeout=60)

    def world(self, base, branch, enforcers=(BAD,), after=None):
        """Commit `base`, mark it, commit `branch`, and judge."""
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            for name, text in base.items():
                write(root, name, text)
            commit_all(root)
            mark_base(root)
            for name, text in branch.items():
                write(root, name, text)
            if after is not None:
                after(root)
            commit_all(root)
            return self.judge(root, enforcers)

    def test_a_branch_adding_a_bare_suppression_fails(self):
        w = Violation("FX1", "b.bad", 1)
        verdict = self.world({"a.bad": "x\n"}, {"b.bad": "x  # " + suppress("FX1") + "\n"})
        self.assertEqual(verdict.rises, (Rise("FX1", 1, 3, (w, w)),))
        self.assertEqual(verdict.suppressions, ())

    def test_a_branch_adding_a_reasoned_suppression_passes_and_lists_it(self):
        verdict = self.world(
            {"a.bad": "x\n"}, {"b.bad": "x  # " + suppress("FX1", "generated fixture") + "\n"})
        self.assertEqual(verdict.rises, ())
        self.assertEqual(
            verdict.suppressions, (Suppression("FX1", "b.bad", 1, "generated fixture"),))
        self.assertEqual(
            [s.text() for s in verdict.suppressions], ["FX1 b.bad:1 generated fixture"])

    def test_deleting_the_reason_fails(self):
        w = Violation("FX1", "b.bad", 1)
        verdict = self.world(
            {"b.bad": "x  # " + suppress("FX1", "generated fixture") + "\n"},
            {"b.bad": "x  # " + suppress("FX1") + "\n"})
        self.assertEqual(verdict.rises, (Rise("FX1", 0, 2, (w, w)),))

    def test_an_existing_bare_marker_holds(self):
        verdict = self.world(
            {"b.bad": "x  # " + suppress("FX1") + "\n"}, {"c.txt": "y\n"})
        self.assertEqual(verdict.rises, ())

    def test_a_suppression_held_on_the_base_is_not_listed(self):
        reasoned = "x  # " + suppress("FX1", "generated fixture") + "\n"
        verdict = self.world(
            {"b.bad": reasoned}, {"b.bad": reasoned + "more\n", "c.txt": "y\n"})
        self.assertEqual(verdict.suppressions, ())
        self.assertEqual(verdict.rises, ())

    def test_a_moved_suppression_is_not_listed(self):
        body = "x  # " + suppress("FX1", "generated fixture") + "\n" + lines(20)
        verdict = self.world(
            {"src/b.bad": body}, {},
            after=lambda root: (
                (root / "dst").mkdir(), git(root, "mv", "src/b.bad", "dst/b.bad")))
        self.assertEqual(verdict.suppressions, ())
        self.assertEqual(verdict.rises, ())

    def test_a_listed_suppression_off_a_finding_does_not_fail(self):
        verdict = self.world({"a.bad": "x\n"}, {"c.txt": "# " + suppress("FX1", "why") + "\n"})
        self.assertEqual(verdict.rises, ())
        self.assertEqual(len(verdict.suppressions), 1)

    def test_a_bare_marker_on_a_held_per_file_violation_rises(self):
        verdict = self.world(
            {"f.txt": "l1\nl2\nl3\nl4\nl5\n"},
            {"f.txt": "l1\nl2\nl3\nl4\nl5  # " + suppress("FX2") + "\n"},
            enforcers=(LONG,))
        self.assertEqual(
            verdict.rises, (Rise("FX2", 1, 2, (Violation("FX2", "f.txt", 5),)),))


class SizeLintSuppressionTest(unittest.TestCase):
    def test_size_lint_omits_a_suppressed_file_and_prints_a_bare_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            write(root, "a.py", "x = 1\n" * 1500 + "x = 1  # " + suppress("B17", "generated table") + "\n")
            write(root, "b.py", "x = 1\n" * 1500 + "# " + suppress("B17") + "\n")
            commit_all(root)
            done = subprocess.run(
                [sys.executable, "-m", "agent_tools.delivery.size_lint", "--repo-root", str(root)],
                capture_output=True, text=True, timeout=60,
                env=fixture_env({"PYTHONPATH": str(REPO_ROOT / "python")}))
        self.assertEqual((done.returncode, done.stdout), (1, "B17 b.py:1501\nB17 b.py:1501\n"))


if __name__ == "__main__":
    unittest.main()
