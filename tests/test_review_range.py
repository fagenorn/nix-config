"""Contracts for the review-range decision helper (#264 D2, D3, D12).

Runs `python -m agent_tools.review_range` as a subprocess against scratch git
repositories under a TemporaryDirectory, as test_diff_scope.py's CLI layer does:
no network, and no repository but its own.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                     "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE")
KEYS = {"route", "reason", "final_review_head", "head", "review_base",
        "product_lines", "product_files"}


def git_env():
    env = dict(os.environ)
    for name in GIT_LOCATION_VARS:
        env.pop(name, None)
    # Absolute, so a helper run with its own temporary `cwd` still imports the
    # package under test (precedent: tests/promotion_test_support.py).
    if env.get("PYTHONPATH"):
        env["PYTHONPATH"] = os.pathsep.join(os.path.abspath(entry) for entry
                                            in env["PYTHONPATH"].split(os.pathsep))
    env.update({
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": "review-range-test",
        "GIT_AUTHOR_EMAIL": "review-range-test@example.invalid",
        "GIT_COMMITTER_NAME": "review-range-test",
        "GIT_COMMITTER_EMAIL": "review-range-test@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
    })
    return env


def lines(count):
    return "".join(f"{index}\n" for index in range(count))


class ReviewRangeTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.git("init", "-q", "-b", "main", ".")
        self.c0 = self.commit("base", {"a.txt": "one\ntwo\nthree\n"})
        self.git("checkout", "-q", "-b", "feature")

    def git(self, *arguments, check=True):
        completed = subprocess.run(["git", *arguments], cwd=self.root, env=git_env(),
                                   capture_output=True, text=True, check=False)
        if check and completed.returncode != 0:
            raise AssertionError(f"git {' '.join(arguments)}: {completed.stderr}")
        return completed.stdout.strip()

    def commit(self, message, files):
        for relative, text in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def run_helper(self, *arguments, cwd=None):
        return subprocess.run([sys.executable, "-m", "agent_tools.review_range", *arguments],
                              cwd=cwd or self.root, env=git_env(), capture_output=True,
                              check=False)

    def arguments(self, head, final_review_head=None, max_lines=1000, max_files=20, extra=()):
        argv = ["--integration-ref", "main", "--head", head,
                "--max-lines", str(max_lines), "--max-files", str(max_files), *extra]
        if final_review_head is not None:
            argv += ["--final-review-head", final_review_head]
        return argv

    def decide(self, *args, cwd=None, **kwargs):
        completed = self.run_helper(*self.arguments(*args, **kwargs), cwd=cwd)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, b"")
        self.assertTrue(completed.stdout.endswith(b"\n"))
        self.assertEqual(completed.stdout.count(b"\n"), 1)
        decision = json.loads(completed.stdout)
        self.assertEqual(set(decision), KEYS)
        return decision

    def full(self, reason, final_review_head, head, product=(None, None)):
        return {"route": "full", "reason": reason, "final_review_head": final_review_head,
                "head": head, "review_base": None,
                "product_lines": product[0], "product_files": product[1]}

    def sync_fixture(self):
        """R, then an integration commit P, a fix commit and a clean sync merge H."""
        r = self.commit("feature", {"src/x.py": lines(3)})
        self.git("checkout", "-q", "main")
        p = self.commit("integration", {"main.txt": lines(50)})
        self.git("checkout", "-q", "feature")
        self.commit("fix wave", {"src/x.py": lines(5)})
        self.git("merge", "-q", "--no-edit", "main")
        return r, p, self.git("rev-parse", "HEAD")

    def test_a_first_parent_final_review_head_within_the_gate_is_a_delta_from_it(self):
        r = self.commit("feature", {"src/x.py": lines(3)})
        h = self.commit("fix wave", {"src/x.py": lines(5)})
        self.assertEqual(self.decide(h, r), {
            "route": "delta", "reason": "within_gate", "final_review_head": r, "head": h,
            "review_base": r, "product_lines": 2, "product_files": 1})

    def test_root_names_the_work_tree_from_another_directory(self):
        r = self.commit("feature", {"src/x.py": lines(3)})
        h = self.commit("fix wave", {"src/x.py": lines(5)})
        with tempfile.TemporaryDirectory() as elsewhere:
            decision = self.decide(h, r, cwd=elsewhere, extra=("--root", str(self.root)))
        self.assertEqual((decision["route"], decision["review_base"]), ("delta", r))

    def test_no_final_review_head_is_full(self):
        h = self.commit("feature", {"src/x.py": lines(3)})
        self.assertEqual(self.decide(h), self.full("no_final_review_head", None, h))

    def test_a_non_ancestor_final_review_head_is_off_the_branch(self):
        self.git("checkout", "-q", "-b", "other", "main")
        r = self.commit("other", {"b.txt": "b\n"})
        self.git("checkout", "-q", "feature")
        h = self.commit("feature", {"src/x.py": lines(3)})
        self.assertEqual(self.decide(h, r),
                         self.full("final_review_head_not_on_branch", r, h))

    def test_an_unresolvable_final_review_head_is_off_the_branch(self):
        h = self.commit("feature", {"src/x.py": lines(3)})
        self.assertEqual(self.decide(h, "0" * 40),
                         self.full("final_review_head_not_on_branch", None, h))

    def test_a_head_reached_only_through_a_second_parent_is_off_the_branch(self):
        self.git("checkout", "-q", "-b", "reviewed", "main")
        r = self.commit("reviewed", {"src/x.py": lines(3)})
        self.git("checkout", "-q", "feature")
        self.commit("other line", {"b.txt": "b\n"})
        self.git("merge", "-q", "--no-ff", "--no-edit", "reviewed")
        h = self.git("rev-parse", "HEAD")
        self.git("merge-base", "--is-ancestor", r, h)
        self.assertEqual(self.decide(h, r),
                         self.full("final_review_head_not_on_branch", r, h))

    def test_an_over_gate_delta_is_full_with_its_measurement(self):
        r = self.commit("feature", {"src/x.py": lines(3)})
        h = self.commit("fix wave", {"src/x.py": lines(6)})
        self.assertEqual(self.decide(h, r, max_lines=2), self.full("over_gate", r, h, (3, 1)))
        self.assertEqual(self.decide(h, r, max_lines=3)["route"], "delta")
        h2 = self.commit("second file", {"src/y.py": "y\n"})
        self.assertEqual(self.decide(h2, r, max_files=1), self.full("over_gate", r, h2, (4, 2)))

    def test_no_change_since_the_final_review_head_is_empty(self):
        r = self.commit("feature", {"src/x.py": lines(3)})
        self.assertEqual(self.decide(r, r), {
            "route": "empty", "reason": "no_changes", "final_review_head": r, "head": r,
            "review_base": r, "product_lines": 0, "product_files": 0})

    def test_a_lockfile_only_delta_is_still_reviewed(self):
        r = self.commit("feature", {"src/x.py": lines(3)})
        h = self.commit("bump", {"flake.lock": "{}\n"})
        self.assertEqual(self.decide(h, r), {
            "route": "delta", "reason": "within_gate", "final_review_head": r, "head": h,
            "review_base": r, "product_lines": 0, "product_files": 0})

    def test_artifact_paths_are_excluded_from_the_delta_measurement(self):
        r = self.commit("feature", {"src/x.py": lines(3)})
        h = self.commit("docs", {"plans/p.md": lines(40), "src/x.py": lines(4)})
        self.assertEqual(self.decide(h, r, max_lines=1)["reason"], "over_gate")
        decision = self.decide(h, r, max_lines=1, extra=("--artifact-path", "plans/p.md"))
        self.assertEqual((decision["route"], decision["product_lines"], decision["product_files"]),
                         ("delta", 1, 1))

    def test_a_sync_merge_is_measured_against_the_synced_final_review_head(self):
        r, p, h = self.sync_fixture()
        first = self.decide(h, r)
        base = first["review_base"]
        self.assertEqual({k: v for k, v in first.items() if k != "review_base"}, {
            "route": "delta", "reason": "within_gate", "final_review_head": r, "head": h,
            "product_lines": 2, "product_files": 1})
        self.assertNotEqual(base, r)
        self.assertEqual(self.git("rev-list", "--parents", "-n", "1", base).split(), [base, r, p])
        self.assertEqual(self.git("log", "-1", "--format=%an|%ae|%at|%cn|%ce|%ct", base),
                         "review-range|review-range@invalid|0|review-range|review-range@invalid|0")
        self.assertEqual(self.decide(h, r), first)
        self.assertEqual(self.git("for-each-ref", "--contains", base), "")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("rev-parse", "HEAD"), h)

    def test_signing_configuration_does_not_reach_the_scratch_base(self):
        r, _p, h = self.sync_fixture()
        self.git("config", "commit.gpgsign", "true")
        self.git("config", "gpg.program", "false")
        self.assertEqual(self.decide(h, r)["route"], "delta")

    def test_a_non_sync_merge_is_full(self):
        r = self.commit("feature", {"src/x.py": lines(3)})
        self.git("checkout", "-q", "-b", "side")
        self.commit("side", {"side.txt": "s\n"})
        self.git("checkout", "-q", "feature")
        self.commit("more", {"src/x.py": lines(4)})
        self.git("merge", "-q", "--no-ff", "--no-edit", "side")
        h = self.git("rev-parse", "HEAD")
        self.assertEqual(self.decide(h, r), self.full("foreign_merge", r, h))

    def test_a_conflicting_reproduction_is_full(self):
        r = self.commit("feature", {"a.txt": "one\nFEATURE\nthree\n"})
        self.git("checkout", "-q", "main")
        self.commit("integration", {"a.txt": "one\nMAIN\nthree\n"})
        self.git("checkout", "-q", "feature")
        self.git("merge", "-q", "--no-edit", "main", check=False)
        (self.root / "a.txt").write_text("one\nRESOLVED\nthree\n", encoding="utf-8")
        self.git("add", "a.txt")
        self.git("commit", "-q", "--no-edit")
        h = self.git("rev-parse", "HEAD")
        self.assertEqual(self.decide(h, r), self.full("sync_not_reproducible", r, h))

    def assert_no_decision(self, completed):
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(completed.stdout, b"")
        self.assertTrue(completed.stderr.startswith(b"review-range: "), completed.stderr)
        self.assertEqual(completed.stderr.count(b"\n"), 1)

    def test_an_unresolvable_head_exits_1_with_no_decision(self):
        self.assert_no_decision(self.run_helper(*self.arguments("no-such-rev", self.c0)))

    def test_an_unresolvable_integration_ref_exits_1_with_no_decision(self):
        h = self.commit("feature", {"src/x.py": lines(3)})
        argv = self.arguments(h, self.c0)
        argv[argv.index("main")] = "no-such-ref"
        self.assert_no_decision(self.run_helper(*argv))

    def test_thresholds_are_required(self):
        h = self.commit("feature", {"src/x.py": lines(3)})
        completed = self.run_helper("--integration-ref", "main", "--head", h, "--max-files", "20")
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, b"")

    def test_the_parser_is_named_for_the_command(self):
        completed = self.run_helper("--help")
        self.assertEqual(completed.returncode, 0)
        self.assertTrue(completed.stdout.startswith(b"usage: review-range "), completed.stdout)


if __name__ == "__main__":
    unittest.main()
