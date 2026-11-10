"""Contract tests for `issue-branch` (`agent_tools.issue_branch`, issue 748).

The policy functions are imported; the command runs as `python -m agent_tools.issue_branch`
against a git copy of the eval fixture project with a bare origin, a temporary HOME holding
the committed platform manifest, and a stub `gh` first on PATH (agent-helpers rule 5).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools import issue_branch

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
FIXTURE = REPO_ROOT / "home/common/agent-skills/evals/fixture-repo"
SLUG = "fixture/tinytask"
TWENTY_WORDS = ("Chat and invoke agent run events may never be emitted in production "
                "because the telemetry source name does not match")
SHORT = "chat-and-invoke-agent-run-events"
LONG_SLUG = "-".join(TWENTY_WORDS.lower().split())
GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false")
FAKE_GH = '''import json, os, sys
state = json.load(open(os.environ["FAKE_GH_STATE"]))
argv = sys.argv[1:]
issues = "repos/%s/issues/" % state["slug"]
pulls = "repos/%s/pulls?" % state["slug"]
if len(argv) == 2 and argv[0] == "api" and argv[1].startswith(issues):
    print(json.dumps({"number": int(argv[1][len(issues):]), "title": state["title"]}))
elif argv[:3] == ["api", "--paginate", "--slurp"] and len(argv) == 4 and argv[3].startswith(pulls):
    print(json.dumps([state["pulls"]]))
else:
    sys.stderr.write("gh: Not Found (HTTP 404): unexpected call %r\\n" % (argv,))
    sys.exit(1)
'''


def pull(number, branch):
    """One open same-repository pull request as the REST listing returns it."""
    return {"number": number, "updated_at": "2026-11-01T00:00:00Z",
            "head": {"ref": branch, "repo": {"full_name": SLUG}},
            "base": {"repo": {"full_name": SLUG}}}


class TitleSlugTest(unittest.TestCase):
    def test_a_twenty_word_title_keeps_six_words_within_forty_characters(self):
        self.assertEqual(len(TWENTY_WORDS.split()), 20)
        slug = issue_branch.title_slug(TWENTY_WORDS)
        self.assertEqual(slug, SHORT)
        self.assertLessEqual(len(slug), 40)

    def test_the_slug_is_cut_at_a_word_boundary(self):
        word = "Pneumonoultramicroscopicsilicovolcanoconiosisxyz"
        cases = {
            "Reconciliation orchestrator misclassifies a b": "reconciliation-orchestrator",
            f"{word} is long": word.lower()[:40],
            "Fix: the `cd <path> &&` habit (issue 12)!": "fix-the-cd-path-habit-issue",
            "Café über naïve": "cafe-uber-naive",
            "!!! ---": "untitled",
        }
        for title, want in cases.items():
            with self.subTest(title=title):
                got = issue_branch.title_slug(title)
                self.assertEqual(got, want)
                self.assertLessEqual(len(got), 40)


class SelectTest(unittest.TestCase):
    def pick(self, pattern, refs, pulls=None, issue=9, excluded=("main",)):
        derived = issue_branch.render(pattern, issue, SHORT)
        return issue_branch.select(derived, refs, pulls or {}, issue_branch.matcher(pattern, issue), excluded)

    def test_an_earlier_long_slug_branch_of_the_issue_is_adopted(self):
        refs = {"main": 300, "issue-9-" + LONG_SLUG: 100, "issue-94-other": 200, "issue-9": 250}
        self.assertEqual(self.pick("issue-<num>-<slug>", refs), "issue-9-" + LONG_SLUG)

    def test_the_derived_branch_outranks_an_open_pr_and_a_newer_branch(self):
        derived = "issue-9-" + SHORT
        refs = {derived: 100, "issue-9-old": 200, "issue-9-older": 50}
        self.assertEqual(self.pick("issue-<num>-<slug>", refs, {"issue-9-older": 4}), derived)

    def test_the_lowest_open_pr_outranks_a_newer_branch(self):
        refs = {"issue-9-newer": 200, "issue-9-older": 50, "issue-9-oldest": 10}
        pulls = {"issue-9-older": 7, "issue-9-oldest": 5, "issue-8-x": 1}
        self.assertEqual(self.pick("issue-<num>-<slug>", refs, pulls), "issue-9-oldest")

    def test_equal_dates_pick_the_smallest_name(self):
        self.assertEqual(self.pick("issue-<num>-<slug>", {"issue-9-b": 5, "issue-9-a": 5}), "issue-9-a")

    def test_with_no_candidate_the_derived_branch_is_new(self):
        self.assertEqual(self.pick("issue-<num>-<slug>", {"main": 900, "issue-94-x": 800}), "issue-9-" + SHORT)

    def test_a_slug_first_pattern_adopts_only_branches_of_its_issue(self):
        refs = {"main": 900, "other-12": 800, "x-19": 700, "fix-x-9": 100}
        self.assertEqual(self.pick("<slug>-<num>", refs), "fix-x-9")
        self.assertEqual(self.pick("<slug>-<num>", {"main": 900, "other-12": 800}), f"{SHORT}-9")

    def test_a_pattern_without_the_issue_number_adopts_no_other_branch(self):
        self.assertIsNone(issue_branch.matcher("feat/<slug>", 9))
        self.assertEqual(self.pick("feat/<slug>", {"main": 900, "feat/other": 800}), f"feat/{SHORT}")

    def test_an_adjacent_number_and_slug_adopt_no_other_branch(self):
        self.assertIsNone(issue_branch.matcher("fix-<slug><num>", 4))
        self.assertEqual(self.pick("fix-<slug><num>", {"fix-abc14": 9}, issue=4), f"fix-{SHORT}4")

    def test_the_integration_and_default_branches_are_never_adopted(self):
        refs = {"release-9": 900, "trunk-9": 800, "HEAD": 950}
        self.assertEqual(self.pick("<slug>-<num>", refs, excluded=("release-9", "trunk-9")), f"{SHORT}-9")


class IssueBranchCase(unittest.TestCase):
    """A git copy of the fixture project with a bare origin, a manifest HOME and a stub gh."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.home = base / "home"
        (self.home / ".agents" / "share").mkdir(parents=True)
        shutil.copy(MANIFEST, self.home / ".agents" / "share" / "platform-manifest.json")
        self.bin = base / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(f"#!{sys.executable}\n{FAKE_GH}", encoding="utf-8")
        gh.chmod(0o755)
        self.state = base / "gh-state.json"
        self.set_forge(TWENTY_WORDS, [])
        self.root = base / "project"
        shutil.copytree(FIXTURE, self.root)
        self.edit_contract(lambda c: c["bindings"]["tracker"].update({"kind": "github", "repo_slug": SLUG}))
        self.origin = base / "origin.git"
        self.git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.root, "init", "-q", "-b", "main")
        self.git(self.root, "remote", "add", "origin", str(self.origin))
        self.commit("main", "2026-01-01T00:00:00Z")

    def set_forge(self, title, pulls, slug=SLUG):
        self.state.write_text(json.dumps({"slug": slug, "title": title, "pulls": pulls}), encoding="utf-8")

    def edit_contract(self, change):
        path = self.root / ".agents" / "project.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        change(contract)
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    def git(self, cwd, *args, env=None):
        done = subprocess.run([*GIT, "-C", str(cwd), *args], capture_output=True, text=True, timeout=60,
                              env={**os.environ, "HOME": str(self.home), **(env or {})}, check=False)
        if done.returncode != 0:
            raise AssertionError(f"git {args} failed: {done.stderr}")
        return done.stdout

    def commit(self, branch, date, *, local=False, remote=True):
        """One commit on `branch` (made from main) at `date`; origin fetches it when `remote`,
        and the local branch stays only when `local`."""
        dated = {"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date}
        if branch != "main":
            self.git(self.root, "checkout", "-q", "-b", branch, "main")
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "--allow-empty", "-m", branch, env=dated)
        if remote:
            self.git(self.origin, "fetch", "-q", str(self.root), f"{branch}:{branch}")
        if branch != "main":
            self.git(self.root, "checkout", "-q", "main")
            if not local:
                self.git(self.root, "update-ref", "-d", f"refs/heads/{branch}")

    def issue_branch(self, issue=9):
        proc = subprocess.run(
            [sys.executable, "-m", "agent_tools.issue_branch", "--repo-root", str(self.root), "--issue", str(issue)],
            capture_output=True, text=True, timeout=120, cwd=str(self.home),
            env={**os.environ, "HOME": str(self.home), "FAKE_GH_STATE": str(self.state),
                 "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"})
        return proc.returncode, proc.stdout, proc.stderr

    def derived(self, issue=9):
        code, out, err = self.issue_branch(issue)
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertEqual(out.count("\n"), 1)
        return json.loads(out)

    def refused(self, exit_code):
        code, out, err = self.issue_branch()
        self.assertEqual((code, out), (exit_code, ""), err)
        return json.loads(err)["error"]["code"]


class IssueBranchCommandTest(IssueBranchCase):
    def test_a_fresh_run_readopts_an_existing_long_slug_branch(self):
        long = "issue-9-" + LONG_SLUG
        self.commit(long, "2026-02-01T00:00:00Z")
        self.assertEqual(self.derived(), {
            "adopted": True, "branch": long, "derived": "issue-9-" + SHORT,
            "worktree_path": str(self.root / ".worktrees" / f"worktree-{long}")})

    def test_a_local_only_branch_is_readopted_too(self):
        long = "issue-9-" + LONG_SLUG
        self.commit(long, "2026-02-01T00:00:00Z", local=True, remote=False)
        self.assertEqual(self.derived()["branch"], long)

    def test_an_open_pr_head_outranks_a_newer_branch_of_the_issue(self):
        long = "issue-9-" + LONG_SLUG
        self.commit(long, "2026-02-01T00:00:00Z")
        self.commit("issue-9-newer", "2026-03-01T00:00:00Z")
        self.set_forge(TWENTY_WORDS, [pull(41, long)])
        self.assertEqual(self.derived()["branch"], long)

    def test_with_no_earlier_branch_the_short_branch_is_derived(self):
        self.commit("issue-94-other", "2026-03-01T00:00:00Z")
        out = self.derived()
        self.assertEqual((out["branch"], out["adopted"]), ("issue-9-" + SHORT, False))
        self.assertEqual(out["worktree_path"], str(self.root / ".worktrees" / f"worktree-issue-9-{SHORT}"))

    def test_a_slug_first_pattern_never_adopts_the_newest_branch(self):
        self.edit_contract(lambda c: c["bindings"]["vcs"].update({"branch_pattern": "<slug>-<num>"}))
        self.commit("main", "2026-04-01T00:00:00Z")
        self.commit("other-12", "2026-03-01T00:00:00Z")
        self.assertEqual(self.derived()["branch"], f"{SHORT}-9")

    def test_a_tracker_other_than_github_is_refused(self):
        self.edit_contract(lambda c: c["bindings"]["tracker"].update({"kind": "none"}))
        self.assertEqual(self.refused(2), "tracker_unsupported")

    def test_a_project_without_a_contract_is_resolver_refused(self):
        (self.root / ".agents" / "project.json").unlink()
        self.assertEqual(self.refused(2), "resolver_refused")

    def test_a_forge_failure_exits_one(self):
        self.set_forge(TWENTY_WORDS, [], slug="someone/else")
        self.assertEqual(self.refused(1), "forge_failed")


if __name__ == "__main__":
    unittest.main()
