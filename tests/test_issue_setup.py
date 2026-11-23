"""Contract tests for `issue-setup` (`agent_tools.delivery.issue_setup`).

The policy functions are imported; each command runs as a child process
(`python -m agent_tools.delivery.issue_setup`) against a real git project with a local bare
origin (the worktree commands) or a fake `gh` (the forge commands).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from agent_tools.delivery import issue_setup
from agent_tools.project_contract import resolve_project

from .forge_world import ForgeWorld
from .guard_policy_world import REPO_ROOT, GuardPolicyWorld, install_platform_manifest_in_environ

TIER = "integration"

setUpModule = install_platform_manifest_in_environ

SLUG = "example/setup"
BRANCH = "issue-7-x"
OPEN = {"state": "open", "labels": []}
MERGED = {"number": 9, "state": "MERGED", "headRefName": "x", "closingIssuesReferences": [{"number": 7}]}
MENTION = {"number": 9, "state": "MERGED", "headRefName": "x", "closingIssuesReferences": []}
ELSEWHERE = {"number": 11, "state": "OPEN", "headRefName": "other", "closingIssuesReferences": []}
OWN = {"number": 11, "state": "OPEN", "headRefName": BRANCH, "closingIssuesReferences": []}
LANE_BODY = "Fix `a/b.py`.\n\n## Acceptance criteria\n\n- [ ] [code] x\n"
ISSUE_READ = ["api", f"repos/{SLUG}/issues/7"]
OPEN_PULLS = ["api", "--paginate", "--slurp", f"repos/{SLUG}/pulls?state=open&per_page=100"]
COMMENTS = ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/7/comments?per_page=100"]
PR_LIST = ["pr", "list", "--repo", SLUG, "--state", "all", "--search", "7", "--json",
           "number,state,headRefName,closingIssuesReferences"]


def gh_only(forge: ForgeWorld, directory: Path) -> Path:
    """A directory holding only the fake `gh` of `forge`."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "gh"
    shutil.copy(forge.bin / "gh", target)
    target.chmod(0o755)
    return directory


class JudgeTest(unittest.TestCase):
    def test_each_gate_refuses_in_the_programs_order(self):
        rows = [
            ({"state": "closed", "labels": [{"name": "needs-verification"}]}, [], ("closed", None)),
            ({"state": "open", "labels": [{"name": "parked"}]}, [], ("parked", None)),
            ({"state": "open", "labels": [{"name": "needs-verification"}]}, [], ("parked", None)),
            (OPEN, [MERGED], ("duplicate", 9)),
            (OPEN, [MENTION], ("clear", None)),
            (OPEN, [ELSEWHERE], ("open-pr", 11)),
            (OPEN, [OWN], ("clear", None)),
            (OPEN, [MERGED, ELSEWHERE], ("duplicate", 9)),
            ({"state": "closed", "labels": [{"name": "parked"}]}, [ELSEWHERE], ("closed", None)),
        ]
        for issue, pulls, want in rows:
            with self.subTest(issue=issue, pulls=pulls):
                self.assertEqual(issue_setup.judge(issue, pulls, BRANCH, 7), want)

    def test_the_issue_text_holds_the_title_the_body_and_each_comment_in_order(self):
        self.assertEqual(
            issue_setup.issue_text({"title": "T", "body": "B"}, [{"body": "c1"}, {"body": "c2"}]),
            "# T\n\nB\n\n## Comment 1\n\nc1\n\n## Comment 2\n\nc2")
        self.assertEqual(issue_setup.issue_text({"title": "T", "body": None}, []), "# T\n\n")


def run_setup(env, *args):
    """The child process of `issue-setup <args>`: (exit status, the one JSON line it printed)."""
    done = subprocess.run([sys.executable, "-m", "agent_tools.delivery.issue_setup", *args],
                          capture_output=True, text=True, timeout=120, env=env,
                          cwd=env.get("HOME") or None)
    lines = done.stdout.splitlines()
    if len(lines) != 1:
        raise AssertionError(f"expected one stdout line, got {done.stdout!r} (stderr {done.stderr!r})")
    return done.returncode, json.loads(lines[0])


class WorktreeTest(unittest.TestCase):
    def setUp(self):
        self.world = GuardPolicyWorld(self)
        self.root = self.world.project(SLUG, SLUG, register=False)
        worktree = resolve_project.resolve(str(self.root))["bindings"]["vcs"]["worktree"]
        self.path = self.root / worktree["root"] / (worktree["prefix"] + BRANCH)
        self.env = self.world.env

    def call(self, sub, *, path=None, branch=BRANCH):
        return run_setup(self.env, sub, "--repo-root", str(self.root), "--branch", branch,
                         "--worktree-path", str(path or self.path))

    def git(self, *args, root=None):
        return self.world.git(root or self.root, *args)

    def make(self):
        code, made = self.call("worktree")
        self.assertEqual((code, made["verdict"]), (0, "made"), made)
        return made

    def test_worktree_makes_the_branch_from_the_integration_branch_when_nothing_exists(self):
        made = self.make()
        self.assertEqual(self.git("branch", "--show-current", root=self.path).strip(), BRANCH)
        tip = self.git("rev-parse", "origin/main").strip()
        self.assertEqual((made["head"], made["base_sha"]), (tip, tip))
        self.assertEqual(made["branch"], BRANCH)
        self.assertEqual(made["status"], "")

    def test_worktree_adopts_an_existing_clean_worktree_on_the_branch(self):
        made = self.make()
        code, again = self.call("worktree")
        self.assertEqual((code, again["verdict"], again["head"]), (0, "adopted", made["head"]))
        listed = [line for line in self.git("worktree", "list", "--porcelain").splitlines()
                  if line == f"worktree {os.path.realpath(self.path)}"]
        self.assertEqual(len(listed), 1)

    def test_worktree_reports_dirty_and_leaves_the_change(self):
        self.make()
        (self.path / "scratch.txt").write_text("keep\n", encoding="utf-8")
        code, dirty = self.call("worktree")
        self.assertEqual((code, dirty["verdict"]), (0, "dirty"))
        self.assertIn("scratch.txt", dirty["status"])
        self.assertTrue((self.path / "scratch.txt").exists())

    def test_worktree_refuses_a_path_on_another_branch_as_mismatch(self):
        self.git("worktree", "add", "-b", "other", str(self.path), "origin/main")
        for sub in ("worktree-check", "worktree"):
            with self.subTest(sub=sub):
                code, report = self.call(sub)
                self.assertEqual((code, report["verdict"]), (0, "mismatch"), report)
        self.assertEqual(self.git("branch", "--show-current", root=self.path).strip(), "other")

    def test_worktree_refuses_the_branch_checked_out_at_another_path_as_mismatch(self):
        elsewhere = self.root.parent / "elsewhere"
        self.git("worktree", "add", "-b", BRANCH, str(elsewhere), "origin/main")
        for sub in ("worktree-check", "worktree"):
            with self.subTest(sub=sub):
                code, report = self.call(sub)
                self.assertEqual((code, report["verdict"]), (0, "mismatch"), report)
        self.assertFalse(self.path.exists())
        blocks = self.git("worktree", "list", "--porcelain").split("\n\n")
        holders = [b.splitlines()[0] for b in blocks if f"branch refs/heads/{BRANCH}" in b]
        self.assertEqual(holders, [f"worktree {os.path.realpath(elsewhere)}"])

    def test_a_clean_detached_head_at_the_tip_is_mismatch_while_the_branch_is_checked_out_elsewhere(self):
        elsewhere = self.root.parent / "elsewhere"
        self.git("worktree", "add", "-b", BRANCH, str(elsewhere), "origin/main")
        self.git("worktree", "add", "--detach", str(self.path), BRANCH)
        for sub in ("worktree-check", "worktree"):
            with self.subTest(sub=sub):
                code, report = self.call(sub)
                self.assertEqual((code, report["verdict"]), (0, "mismatch"), report)
                self.assertIn("elsewhere", report["detail"])
        with self.assertRaises(subprocess.CalledProcessError):
            self.git("symbolic-ref", "-q", "HEAD", root=self.path)

    def test_worktree_check_reports_a_clean_detached_head_at_the_tip_as_absent_and_leaves_it_detached(self):
        self.make()
        self.git("checkout", "--detach", root=self.path)
        code, report = self.call("worktree-check")
        self.assertEqual((code, report["verdict"]), (0, "absent"))
        with self.assertRaises(subprocess.CalledProcessError):
            self.git("symbolic-ref", "-q", "HEAD", root=self.path)
        code, report = self.call("worktree")
        self.assertEqual((code, report["verdict"]), (0, "adopted"))
        self.assertEqual(self.git("branch", "--show-current", root=self.path).strip(), BRANCH)
        self.git("checkout", "--detach", root=self.path)
        self.git("commit", "--allow-empty", "-m", "x", root=self.path)
        code, report = self.call("worktree-check")
        self.assertEqual((code, report["verdict"]), (0, "mismatch"))

    def test_worktree_adopts_a_remote_only_branch(self):
        self.git("push", "origin", f"origin/main:refs/heads/{BRANCH}")
        advanced = self.world.advance(self.root, BRANCH)
        code, report = self.call("worktree")
        self.assertEqual((code, report["verdict"], report["head"]), (0, "adopted", advanced))
        self.assertEqual(self.git("branch", "--show-current", root=self.path).strip(), BRANCH)

    def test_worktree_reattaches_a_clean_detached_head_at_the_branch_tip(self):
        self.make()
        self.git("checkout", "--detach", root=self.path)
        code, report = self.call("worktree")
        self.assertEqual((code, report["verdict"]), (0, "adopted"))
        self.assertEqual(self.git("branch", "--show-current", root=self.path).strip(), BRANCH)

    def test_a_blocked_path_is_an_error_and_registers_no_worktree(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("in the way\n", encoding="utf-8")
        code, report = self.call("worktree")
        self.assertEqual((code, report["verdict"]), (1, "error"))
        self.assertNotIn(f"worktree {os.path.realpath(self.path)}",
                         self.git("worktree", "list", "--porcelain").splitlines())

    def test_worktree_check_is_absent_before_and_adopted_after(self):
        code, report = self.call("worktree-check")
        self.assertEqual((code, report["verdict"]), (0, "absent"))
        self.assertEqual(self.git("branch", "--list", BRANCH).strip(), "")
        self.make()
        code, report = self.call("worktree-check")
        self.assertEqual((code, report["verdict"]), (0, "adopted"))


class ForgeCommandTest(unittest.TestCase):
    def setUp(self):
        self.world = GuardPolicyWorld(self)
        self.root = self.world.project(SLUG, SLUG, register=False)
        self.forge = ForgeWorld(self)
        gh_dir = gh_only(self.forge, self.world.tmp / "gh-only")
        env = {**self.world.env, "PATH": f"{gh_dir}{os.pathsep}{self.world.env['PATH']}",
               "FORGE_WORLD": str(self.forge.state)}
        for name in ("GITHUB_TOKEN", "GH_TOKEN"):
            env.pop(name, None)
        self.env = env

    def register_reads(self, issue, pulls=()):
        self.forge.respond_json("gh", ISSUE_READ, issue)
        self.forge.respond_json("gh", OPEN_PULLS, [[]])
        self.forge.respond_json("gh", PR_LIST, list(pulls))
        self.forge.respond_json("gh", COMMENTS, [[]])

    def preflight(self):
        return run_setup(self.env, "preflight", "--repo-root", str(self.root), "--issue", "7")

    def test_preflight_prints_the_branch_and_clear_for_an_open_issue(self):
        self.register_reads({"number": 7, "title": "Add a greeting", "body": "Say hi.", "state": "open",
                             "labels": []})
        code, report = self.preflight()
        self.assertEqual((code, report["verdict"]), (0, "clear"), (report, self.forge.calls()))
        self.assertEqual(report["branch"], "issue-7-add-a-greeting")
        self.assertTrue(report["worktree_path"].endswith("/.worktrees/worktree-issue-7-add-a-greeting"))
        self.assertEqual(report["integration_branch"], "main")
        self.assertIn("Say hi.", report["issue_text"])

    def test_preflight_refuses_a_closed_issue_with_closed(self):
        self.register_reads({"number": 7, "title": "Add a greeting", "body": "", "state": "closed",
                             "labels": []})
        code, report = self.preflight()
        self.assertEqual((code, report["verdict"]), (0, "closed"))

    def test_a_forge_failure_is_an_error_with_its_transient_flag(self):
        self.forge.respond("gh", ISSUE_READ, exit=1, stderr="gh: Bad Gateway (HTTP 502)")
        code, report = self.preflight()
        self.assertEqual((code, report["verdict"], report["transient"]), (1, "error", True))

    def test_read_prints_the_issue_text(self):
        self.forge.comment_store(SLUG, 7, [{"id": 1, "body": "c1", "created_at": "2026-11-06T10:00:00Z",
                                            "updated_at": "2026-11-06T10:00:00Z"}], labels=[])
        self.forge.respond_json("gh", ISSUE_READ, {"number": 7, "title": "T", "body": "B"})
        code, report = run_setup(self.env, "read", "--repo", SLUG, "--issue", "7")
        self.assertEqual((code, report["verdict"]), (0, "read"), report)
        self.assertTrue(report["text"].endswith("## Comment 1\n\nc1"), report["text"])

    def lane(self, body, lane_paths=None):
        if lane_paths is not None:
            target = self.root / ".github" / "lane-paths.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(lane_paths))
        self.forge.respond_json("gh", ISSUE_READ, {"number": 7, "title": "T", "body": body})
        code, report = run_setup(self.env, "lane", "--repo-root", str(self.root), "--repo", SLUG,
                                 "--issue", "7")
        return code, report.get("verdict"), report.get("reason")

    def test_lane_prints_the_rules_lane_and_reason(self):
        paths = {"version": 1, "sets": {"secrets": ["secrets/"]}}
        self.assertEqual(self.lane(LANE_BODY, paths),
                         (0, "direct", "named files 1 of at most 3, acceptance criteria 1 of at most 3, "
                                       "no look marker, no lane path"))

    def test_lane_without_a_lane_paths_file_is_standard(self):
        self.assertEqual(self.lane(LANE_BODY), (0, "standard", "the repository declares no lane paths"))

    def test_lane_reads_the_look_marker(self):
        marker = "- [ ] [human] before merge: the text \u2014 measured: the owner, on the pull request\n"
        paths = {"version": 1, "sets": {"secrets": ["secrets/"]}}
        self.assertEqual(self.lane(LANE_BODY + marker, paths),
                         (0, "standard", "a look marker holds the merge for the owner's look"))

    def test_lane_paths_refuses_a_malformed_file(self):
        def read(text=None):
            root = self.world.tmp / "lane-root"
            shutil.rmtree(root, ignore_errors=True)
            (root / ".github").mkdir(parents=True)
            if text is not None:
                (root / ".github" / "lane-paths.json").write_text(text)
            return issue_setup.lane_paths(str(root))

        def file(version=1, sets=None, **extra):
            return json.dumps({"version": version, "sets": {"a": ["x/"]} if sets is None else sets, **extra})

        self.assertEqual(read(file()), {"a": ["x/"]})
        bad = {"no file": None, "version 2": file(2), "version true": file(True),
               "extra key": file(extra=1), "empty sets": file(sets={}),
               "set name": file(sets={"A": ["x/"]}), "absolute": file(sets={"a": ["/abs"]}),
               "dotdot": file(sets={"a": ["a/../b"]}), "space": file(sets={"a": ["a b"]}),
               "empty set": file(sets={"a": []}), "not json": "not json",
               "null": "null", "number": "1", "list of keys": '["version", "sets"]', "nested list": "[[1]]"}
        for name, text in bad.items():
            with self.subTest(name):
                self.assertIsNone(read(text))

    def test_the_shipped_lane_paths_file_declares_guard_release_and_secrets(self):
        paths = issue_setup.lane_paths(str(REPO_ROOT))
        self.assertEqual(sorted(paths), ["guard", "release", "secrets"])
        self.assertIn("secrets/", paths["secrets"])

    def test_note_posts_the_evidence_as_one_comment(self):
        self.forge.comment_store(SLUG, 7, labels=[])
        code, report = run_setup(self.env, "note", "--repo", SLUG, "--issue", "7",
                                 "--evidence", "Already fixed at main.")
        self.assertEqual((code, report["verdict"]), (0, "posted"), report)
        self.assertEqual([c["body"] for c in self.forge.stored()], ["Already fixed at main."])
        self.assertEqual(report["comment_id"], self.forge.stored()[0]["id"])

    def test_a_missing_flag_is_a_usage_error(self):
        code, report = run_setup(self.env, "read", "--repo", SLUG)
        self.assertEqual((code, report["verdict"], report["error"]), (2, "error", "usage"))
        code, report = run_setup(self.env, "lane", "--repo", SLUG, "--issue", "7")
        self.assertEqual((code, report["verdict"], report["error"]), (2, "error", "usage"))


if __name__ == "__main__":
    unittest.main()
