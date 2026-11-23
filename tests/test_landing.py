"""Contract tests for `landing` (`agent_tools.delivery.landing`).

Each reading runs through `main` against a real git project with a local bare origin and a fake
`gh` (`ForgeWorld`): the pull-request readings answer exact argv, `prepare` and `pushed` read real
repositories. No reading changes anything.
"""

from __future__ import annotations

import json
import os
import shlex
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_commands, landing
from agent_tools.verification import verified_tree

from .engine_fixture import FixtureProject
from .forge_world import ForgeWorld
from .guard_policy_world import GuardPolicyWorld
from .test_issue_setup import gh_only

TIER = "integration"

SLUG = "example/fixture"
ISSUE = 41
BODY = "## Acceptance criteria\n\n- [ ] [code] greet() returns the greeting\n"
SHA = "1" * 40
OTHER = "2" * 40
PULL_LIST = ["pr", "list", "--repo", SLUG, "--head", "issue-41-x", "--state", "open", "--json",
             "number,headRefOid,baseRefName,url"]
PULL_VIEW = ["pr", "view", "7", "--repo", SLUG, "--json", "state,headRefOid,mergeCommit"]


def criteria(*lines: str) -> str:
    return "Intro.\n\n## Acceptance criteria\n\n" + "\n".join(lines) + "\n\n## Notes\n\n- [ ] [human] later\n"


class LandingWorld:
    """The fixture project, its fake forge and an environment that reaches both."""

    def __init__(self, test: unittest.TestCase, title: str = "Add a greeting") -> None:
        self.test = test
        self.world = GuardPolicyWorld(test)
        self.fixture = FixtureProject(test, self.world, slug=SLUG)
        self.forge = ForgeWorld(test)
        issue = {"number": ISSUE, "title": title, "state": "open", "labels": [], "body": BODY}
        self.forge.respond_json("gh", ["api", f"repos/{SLUG}/issues/{ISSUE}"], issue)
        self.forge.respond_json("gh", ["api", "--paginate", "--slurp",
                                       f"repos/{SLUG}/pulls?state=open&per_page=100"], [[]])
        tmp = self.world.tmp / "landing"
        tmp.mkdir()
        self.env = {**self.world.env, "FORGE_WORLD": str(self.forge.state),
                    "VERIFY_SLOT_DIR": str(tmp / "slots"),
                    "PATH": os.pathsep.join([str(gh_only(self.forge, tmp / "gh")),
                                             self.world.env["PATH"]])}

    def call(self, *args: str) -> tuple[int, dict]:
        """`main(args)` under this world's environment: (exit status, the one JSON line printed)."""
        out = StringIO()
        with mock.patch.dict(os.environ, self.env), redirect_stdout(out):
            status = landing.main(list(args))
        lines = out.getvalue().splitlines()
        self.test.assertEqual(len(lines), 1, out.getvalue())
        return status, json.loads(lines[0])

    def prepare(self) -> tuple[int, dict]:
        return self.call("prepare", "--repo-root", str(self.fixture.root), "--issue", str(ISSUE),
                         "--repo", SLUG)

    def worktree(self) -> Path:
        """Add the issue's worktree on its branch from `origin/main`."""
        with mock.patch.dict(os.environ, self.env):
            place = landing.placement(str(self.fixture.root), ISSUE)
        self.world.git(self.fixture.root, "worktree", "add", "--no-track", "-b", place["branch"],
                       place["worktree_path"], "origin/main")
        return Path(place["worktree_path"])

    def commit(self, root: Path, name: str) -> str:
        (root / name).write_text(f"{name}\n", encoding="utf-8")
        self.world.git(root, "add", name)
        self.world.git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                       "commit", "--quiet", "-m", name)
        return self.world.git(root, "rev-parse", "HEAD").strip()


class PrepareTest(unittest.TestCase):
    def test_prepare_answers_ready_with_the_verified_head_only_for_the_recorded_tree(self):
        land = LandingWorld(self)
        worktree = land.worktree()
        with mock.patch.dict(os.environ, land.env):
            status, verified = verified_tree.run(worktree)
        self.assertEqual((status, verified["verdict"]), (0, "passed"), verified)
        code, ready = land.prepare()
        self.assertEqual((code, ready["verdict"]), (0, "ready"), ready)
        self.assertEqual(ready["head"], land.world.git(worktree, "rev-parse", "HEAD").strip())
        self.assertIs(ready["closes"], True)
        self.assertEqual(ready["body"], "Closes #41. Delivered by the engine.")
        self.assertEqual((ready["integration_branch"], ready["title"]), ("main", "Add a greeting"))
        land.commit(worktree, "more.txt")
        code, moved = land.prepare()
        self.assertEqual((code, moved["verdict"]), (0, "unverified"), moved)

    def test_prepare_is_unverified_for_a_dirty_worktree_of_the_recorded_tree(self):
        land = LandingWorld(self)
        worktree = land.worktree()
        with mock.patch.dict(os.environ, land.env):
            verified_tree.run(worktree)
        (worktree / "stray.txt").write_text("x\n", encoding="utf-8")
        self.assertEqual(land.prepare()[1]["verdict"], "unverified")

    def test_prepare_ignores_git_variables_naming_another_repository(self):
        land = LandingWorld(self)
        worktree = land.worktree()
        land.commit(worktree, "unverified.txt")
        other = land.fixture.root
        with mock.patch.dict(os.environ, land.env):
            tree = verified_tree.current_tree(other)
            record = verified_tree.record_path(other)
        record.write_text(json.dumps({"schema": verified_tree.SCHEMA, "tree": tree,
                                      "verification": ["x"]}) + "\n", encoding="utf-8")
        land.env = {**land.env, "GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}
        code, answer = land.prepare()
        self.assertEqual((code, answer["verdict"]), (0, "unverified"), answer)
        self.assertEqual(answer["head"], land.world.git(worktree, "rev-parse", "HEAD").strip())

    def test_the_criteria_close_only_when_every_open_criterion_is_code(self):
        rows = {
            "all code": (criteria("- [ ] [code] a", "- [x] [code] b"), True),
            "code and note": (criteria("- [ ] [code] a", "- [ ] [note] b"), True),
            "one evidence": (criteria("- [ ] [code] a", "- [ ] [evidence] b"), False),
            "one human": (criteria("- [ ] [code] a", "- [ ] [human] b"), False),
            "one untagged": (criteria("- [ ] [code] a", "- [ ] b"), False),
            "star bullet human": (criteria("- [ ] [code] a", "* [ ] [human] b"), False),
            "plus bullet evidence": (criteria("- [ ] [code] a", "+ [ ] [evidence] b"), False),
            "star bullet code": (criteria("* [ ] [code] a", "+ [x] [note] b"), True),
            "no section": ("Intro.\n\n- [ ] [code] a\n", False),
            "no criterion line": (criteria("prose only"), False),
        }
        for name, (body, want) in rows.items():
            with self.subTest(name):
                self.assertIs(landing.criteria_close(body), want)

    def test_the_title_and_body_hold_no_shell_active_character(self):
        land = LandingWorld(self, title="Say \"hi\" to $USER `now`! \\ ok\n  again")
        worktree = land.worktree()
        with mock.patch.dict(os.environ, land.env):
            verified_tree.run(worktree)
        _, ready = land.prepare()
        self.assertEqual(ready["title"], "Say hi to USER now ok again")
        argv = ["gh", "pr", "create", "--repo", SLUG, "--base", "main", "--head", ready["branch"],
                "--title", ready["title"], "--body", ready["body"]]
        self.assertEqual(shlex.split(engine_commands.command_text(argv)), argv)


class PushedTest(unittest.TestCase):
    def test_pushed_compares_origins_branch_with_the_head(self):
        land = LandingWorld(self)
        root = land.fixture.root
        land.world.git(root, "branch", "issue-41-x", "main")
        land.world.git(root, "push", "--quiet", "origin", "issue-41-x")
        head = land.world.git(root, "rev-parse", "issue-41-x").strip()

        def pushed(branch: str, sha: str) -> tuple[int, dict]:
            return land.call("pushed", "--repo-root", str(root), "--branch", branch, "--head", sha)

        self.assertEqual(pushed("issue-41-x", head), (0, {"verdict": "pushed"}))
        remote = land.world.advance(root, "issue-41-x")
        self.assertEqual(pushed("issue-41-x", head), (0, {"verdict": "head-moved", "remote": remote}))
        self.assertEqual(pushed("issue-41-absent", head), (0, {"verdict": "absent"}))


class PullTest(unittest.TestCase):
    def test_pull_finds_the_one_open_pull_request_into_the_integration_branch(self):
        forge = ForgeWorld(self)
        entry = {"number": 7, "headRefOid": SHA, "baseRefName": "main", "url": "https://x/pull/7"}
        args = ("pull", "--repo", SLUG, "--branch", "issue-41-x", "--integration-branch", "main")
        for name, listing, want in (
                ("one", [entry], {"verdict": "open", "pr": 7, "head": SHA, "url": "https://x/pull/7"}),
                ("none", [], {"verdict": "absent"}),
                ("another base", [{**entry, "baseRefName": "release"}], {"verdict": "absent"})):
            with self.subTest(name):
                forge.respond_json("gh", PULL_LIST, listing)
                out = StringIO()
                with redirect_stdout(out):
                    status = landing.main(list(args))
                self.assertEqual((status, json.loads(out.getvalue())), (0, want))
        forge.respond_json("gh", PULL_LIST, [entry, {**entry, "number": 8}])
        out = StringIO()
        with redirect_stdout(out):
            status = landing.main(list(args))
        self.assertEqual((status, json.loads(out.getvalue())["verdict"]), (1, "error"))


class MergedTest(unittest.TestCase):
    def test_merged_reads_the_merge_commit(self):
        forge = ForgeWorld(self)
        args = ("merged", "--repo", SLUG, "--pr", "7", "--head", SHA)
        for name, view, want in (
                ("merged", {"state": "MERGED", "headRefOid": SHA, "mergeCommit": {"oid": OTHER}},
                 {"verdict": "merged", "merge_commit": OTHER, "head": SHA}),
                ("open", {"state": "OPEN", "headRefOid": SHA, "mergeCommit": None},
                 {"verdict": "open", "head": SHA})):
            with self.subTest(name):
                forge.respond_json("gh", PULL_VIEW, view)
                out = StringIO()
                with redirect_stdout(out):
                    status = landing.main(list(args))
                self.assertEqual((status, json.loads(out.getvalue())), (0, want))


if __name__ == "__main__":
    unittest.main()
