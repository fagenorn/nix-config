"""The suppression marker's count and listing (#1459, ADR-project-contract-017).

Measures, against real git worlds, that a reasoned marker naming an enforcer's rule
takes that rule's findings off the count on its line, that a marker with no reason
(or a bare one naming the rule) is counted as a violation of its own, that an
id-less marker counts under the rule whose finding sits on its line, and that the
never-rise verdict lists each reasoned suppression the branch adds, without failing
the check for it. `size-lint` prints the same count.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import context_map_lint, never_rise, rule_ids, standards_lint
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
PY = Enforcer("FX1", lambda snap: [
    Violation("FX1", p, 1) for p in sorted(snap.line_counts) if p.endswith(".py")])


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

    def test_a_marker_in_a_python_string_literal_is_no_marker(self):
        marker = suppress("FX1", "why")
        py_v = Violation("FX1", "a.py", 1)
        with self.subTest("string"):
            result, snapshot = self.counted_in({"a.py": 's = "# ' + marker + '"\n'}, PY)
            self.assertEqual((result, snapshot.suppressions), (([py_v], []), ()))
        with self.subTest("docstring"):
            result, snapshot = self.counted_in(
                {"a.py": 's = """\n# ' + marker + '\n"""\n'}, PY)
            self.assertEqual(snapshot.suppressions, ())
        with self.subTest("comment"):
            result, snapshot = self.counted_in({"a.py": "x = 1  # " + marker + "\n"}, PY)
            self.assertEqual(result, ([], []))
            self.assertEqual(snapshot.suppressions, (Suppression("FX1", "a.py", 1, "why"),))
        with self.subTest("comment after a string"):
            result, snapshot = self.counted_in(
                {"a.py": 's = "x"  # ' + marker + "\n"}, PY)
            self.assertEqual(result, ([], []))

    def test_a_marker_in_a_binary_file_is_not_read(self):
        _, snapshot = self.counted_in(
            {"a.bin": b"\0" + ("# " + suppress("FX1") + "\n").encode()})
        self.assertEqual(snapshot.suppressions, ())

    def test_a_suppression_prints_rule_path_line_and_reason(self):
        text = Suppression("FX1", "a\nb.py", 3, "why\tnot").text()
        self.assertEqual(text, "FX1 a\\nb.py:3 why\\tnot")
        self.assertEqual(len(text.splitlines()), 1)

    def test_a_bounded_listing_keeps_every_field(self):
        path = "/".join(["d" * 40] * 6) + "/new.py"
        text = Suppression("FX1", path, 1501, "r" * 300).text(200)
        self.assertLessEqual(len(text), 200)
        self.assertTrue(text.startswith("FX1 ..."), text)
        self.assertIn("/new.py:1501 rrrr", text)
        self.assertTrue(text.endswith("..."), text)
        self.assertEqual(
            Suppression("FX1", "a.py", 3, "why").text(200), "FX1 a.py:3 why")


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

    def test_a_bare_marker_of_a_rule_with_no_enforcer_rises(self):
        verdict = self.world({"a.bad": "x\n"}, {"c.txt": "# " + suppress("B1") + "\n"})
        self.assertEqual(
            verdict.rises, (Rise("B1", 0, 1, (Violation("B1", "c.txt", 1),)),))

    def test_an_existing_bare_marker_of_a_rule_with_no_enforcer_holds(self):
        verdict = self.world(
            {"c.txt": "# " + suppress("B1") + "\n"}, {"d.txt": "y\n"})
        self.assertEqual(verdict.rises, ())

    def test_an_added_suppression_above_an_equal_one_is_the_one_listed(self):
        reasoned = "x  # " + suppress("FX1", "generated fixture") + "\n"
        old = lines(39) + reasoned
        verdict = self.world({"b.txt": old}, {"b.txt": reasoned + old})
        self.assertEqual(
            verdict.suppressions, (Suppression("FX1", "b.txt", 1, "generated fixture"),))

    def test_an_old_suppression_shifted_by_an_insert_is_not_the_one_listed(self):
        reasoned = "x  # " + suppress("FX1", "generated fixture") + "\n"
        old = lines(39) + reasoned
        verdict = self.world({"b.txt": old}, {"b.txt": reasoned + "y\n" + old})
        self.assertEqual(
            verdict.suppressions, (Suppression("FX1", "b.txt", 1, "generated fixture"),))

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


class SuppressionLintTest(unittest.TestCase):
    PLATFORM_README = (
        "# Standards\n\n## Rule ids\n\n| Layer file | Prefix |\n|---|---|\n"
        "| `the-bar.md` | `B` |\n| the repo's `docs/standards/` shards | `P` |\n")
    BAR = "# The bar\n\n### B1. One\n\nBody.\n\n### B2. Two\n\nBody.\n"

    def lint_root(self, files, *, project_shards=None, init=True, untracked=None):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        platform = tmp / "platform"
        write(platform, "README.md", self.PLATFORM_README)
        write(platform, "the-bar.md", self.BAR)
        root = tmp / "root"
        root.mkdir()
        for name, text in files.items():
            write(root, name, text)
        if project_shards:
            index = "# Project standards\n\n| Shard | governs | Gist |\n|---|---|---|\n"
            for name, text in project_shards.items():
                write(root, "docs/standards/" + name, text)
                index += f"| [{name}]({name}) | `x/**` | Shard. |\n"
            write(root, "docs/standards/README.md", index)
        if init:
            git(root, "init", "-q", "-b", "main")
            git(root, "add", "-A")
        for name, text in (untracked or {}).items():
            write(root, name, text)
        return root, platform

    def run_lint(self, root, platform, *extra):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.standards_lint",
             "--repo-root", str(root), "--platform-standards", str(platform), *extra],
            capture_output=True, text=True, timeout=120,
            env=fixture_env({"PYTHONPATH": str(REPO_ROOT / "python")}))

    def outcome(self, done):
        return done.returncode, done.stdout

    def test_a_suppression_naming_an_id_in_no_layer_fails_the_lint(self):
        root, platform = self.lint_root(
            {"src/a.py": "x = 1  # " + suppress("Z9", "no such rule") + "\n"})
        self.assertEqual(
            self.outcome(self.run_lint(root, platform)),
            (1, "src/a.py:1: suppresses Z9, which is in no applicable layer\n"))

    def test_a_bare_marker_naming_an_unknown_id_fails_too(self):
        root, platform = self.lint_root({"src/a.py": "# " + suppress("Z9") + "\n"})
        self.assertEqual(
            self.outcome(self.run_lint(root, platform)),
            (1, "src/a.py:1: suppresses Z9, which is in no applicable layer\n"))

    def test_a_marker_with_no_id_is_no_lint_problem(self):
        root, platform = self.lint_root({
            "src/a.py": "# " + suppress("", "why") + "\n# " + suppress("b17", "why") + "\n"})
        self.assertEqual(self.outcome(self.run_lint(root, platform)), (0, ""))

    def test_a_suppressed_id_resolves_against_its_own_layer(self):
        root, platform = self.lint_root(
            {"src/a.py": "".join("# " + suppress(t, "r") + "\n" for t in ("P1", "P2", "B1", "B9"))},
            project_shards={"a.md": "# A\n\n### P1. One\n\nBody.\n\n### B9. Shadow\n\nBody.\n"})
        done = self.run_lint(root, platform)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(
            [l for l in done.stdout.splitlines() if l.startswith("src/a.py:")],
            ["src/a.py:2: suppresses P2, which is in no applicable layer",
             "src/a.py:4: suppresses B9, which is in no applicable layer"])

    def test_an_untracked_file_is_not_read(self):
        root, platform = self.lint_root(
            {}, untracked={"src/b.py": "# " + suppress("Z9", "r") + "\n"})
        self.assertEqual(self.outcome(self.run_lint(root, platform)), (0, ""))

    def test_a_root_that_is_no_repository_reads_no_file(self):
        root, platform = self.lint_root(
            {"src/a.py": "# " + suppress("Z9", "r") + "\n"}, init=False)
        self.assertEqual(self.outcome(self.run_lint(root, platform)), (0, ""))

    def test_a_repository_git_cannot_list_exits_2(self):
        root, platform = self.lint_root({}, init=False)
        write(root, ".git", "gitdir: " + str(root.parent / "missing") + "\n")
        done = self.run_lint(root, platform)
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertTrue(done.stderr.startswith("standards-lint: "), done.stderr)

    def test_a_binary_tracked_file_is_not_read(self):
        root, platform = self.lint_root(
            {"src/a.bin": b"\0" + ("# " + suppress("Z9", "r") + "\n").encode()})
        self.assertEqual(self.outcome(self.run_lint(root, platform)), (0, ""))

    def test_the_index_prints_the_reasoned_suppressions_of_each_rule(self):
        root, platform = self.lint_root({
            "src/a.py": ("x = 1  # " + suppress("B1", "generated") + "\ny = 2  # "
                         + suppress("B1") + "\n"),
            "notes/x.md": "<!-- " + suppress("B2", "vendored table") + " -->\n"})
        done = self.run_lint(root, platform, "--index")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(done.stdout.splitlines(), [
            "B1. One", "  reasoned suppressions: 1", "B2. Two", "  reasoned suppressions: 1",
            "judged rules: 2", "enforcers citing nothing: 0"])

    def test_the_index_prints_zero_and_totals_several_under_one_rule(self):
        root, platform = self.lint_root({
            "src/a.py": ("x = 1  # " + suppress("B1", "first") + "\ny = 2  # "
                         + suppress("B1", "second") + "\n")})
        done = self.run_lint(root, platform, "--index")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(done.stdout.splitlines(), [
            "B1. One", "  reasoned suppressions: 2", "B2. Two", "  reasoned suppressions: 0",
            "judged rules: 2", "enforcers citing nothing: 0"])

    def test_a_project_suppression_is_credited_to_the_project_rule(self):
        root, platform = self.lint_root(
            {"src/a.py": "# " + suppress("P1", "r") + "\n"},
            project_shards={"a.md": "# A\n\n### P1. One\n\nBody.\n"})
        done = self.run_lint(root, platform, "--index")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(done.stdout.splitlines(), [
            "B1. One", "  reasoned suppressions: 0", "B2. Two", "  reasoned suppressions: 0",
            "P1. One", "  reasoned suppressions: 1", "judged rules: 3",
            "enforcers citing nothing: 0"])

    def test_a_conflicted_file_is_counted_once(self):
        root, platform = self.lint_root({}, init=False)
        git(root, "init", "-q", "-b", "main")
        marker = "# " + suppress("B1", "kept") + "\n"
        write(root, "src/a.py", marker + "x = 0\n")
        commit_all(root, "base")
        git(root, "checkout", "-q", "-b", "side")
        write(root, "src/a.py", marker + "x = 1\n")
        commit_all(root, "side")
        git(root, "checkout", "-q", "main")
        write(root, "src/a.py", marker + "x = 2\n")
        commit_all(root, "main")
        merge = subprocess.run(
            ["git", "-C", str(root), "merge", "side"], capture_output=True, text=True,
            env=fixture_env())
        self.assertEqual(merge.returncode, 1, merge.stdout + merge.stderr)
        self.assertEqual(len(git(root, "ls-files", "-u").splitlines()), 3)
        done = self.run_lint(root, platform, "--index")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(done.stdout.splitlines()[:2], ["B1. One", "  reasoned suppressions: 1"])

    def test_a_tracked_directory_replaced_by_a_symlink_is_not_followed(self):
        root, platform = self.lint_root({"d/a.py": "x = 1\n"})
        outside = root.parent / "outside"
        write(outside, "a.py", "# " + suppress("Z9", "r") + "\n")
        shutil.rmtree(root / "d")
        os.symlink(outside, root / "d")
        self.assertEqual(self.outcome(self.run_lint(root, platform)), (0, ""))

    def test_a_marker_in_a_python_string_literal_is_not_read(self):
        root, platform = self.lint_root(
            {"src/a.py": 's = "# ' + suppress("Z9", "r") + '"\n'})
        self.assertEqual(self.outcome(self.run_lint(root, platform)), (0, ""))

    def test_the_lint_function_fails_an_unknown_suppressed_id(self):
        root, platform = self.lint_root(
            {"src/a.py": "x = 1  # " + suppress("Z9", "no such rule") + "\n"})
        self.assertEqual(
            standards_lint.lint(root, platform),
            ["src/a.py:1: suppresses Z9, which is in no applicable layer"])


class SuppressionDocsTest(unittest.TestCase):
    README = REPO_ROOT / "home/common/agent-skills/standards/README.md"

    def test_the_readme_states_the_suppression_form(self):
        block = context_map_lint.section(self.README.read_text("utf-8"), "Rule ids")
        self.assertTrue(any(
            span.startswith(rule_ids.SUPPRESS)
            for span in context_map_lint.CODE_RE.findall(block)))


if __name__ == "__main__":
    unittest.main()
