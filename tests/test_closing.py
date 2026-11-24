"""Contract tests for `closing` (`agent_tools.delivery.closing`).

Each call runs through `main` against a real git project with a local bare origin and a fake `gh`
(`ForgeWorld`): `read` and `issue` answer exact argv, `worktree`, `forward` and `branch` act on real
repositories. Nothing is forced, so each test also reads back what git or the forge holds.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

from agent_tools.delivery import closing

from .forge_world import ForgeWorld
from .test_landing import BODY, ISSUE, SLUG, LandingWorld

TIER = "integration"

ISSUE_READ = ["api", f"repos/{SLUG}/issues/{ISSUE}"]
PR_LIST = ["pr", "list", "--repo", SLUG, "--head", "issue-41-add-a-greeting", "--state", "merged",
           "--json", "number,mergeCommit,headRefOid"]
SHA = "1" * 40
# A `gh` that reads the issue from the store (so a close shows on the next read) and leaves every
# other call to the world's fake.
STORE_GH = """#!{python}
import json, os, sys
if sys.argv[1:] == {read!r}:
    state = json.loads(open(os.path.join(os.environ["FORGE_WORLD"], "store.json")).read())["issue_state"]
    sys.stdout.write(json.dumps({{"number": {issue}, "state": state["state"],
                                 "state_reason": state["state_reason"], "labels": []}}))
    sys.exit(0)
os.execv({fake!r}, [{fake!r}, *sys.argv[1:]])
"""


def call(env: dict, *args: str) -> tuple[int, dict]:
    """`closing.main(args)` under `env`: (exit status, the one JSON line printed)."""
    out = StringIO()
    with mock.patch.dict(os.environ, env), redirect_stdout(out):
        status = closing.main(list(args))
    lines = out.getvalue().splitlines()
    if len(lines) != 1:
        raise AssertionError(f"expected one stdout line, got {out.getvalue()!r}")
    return status, json.loads(lines[0])


class IssueTest(unittest.TestCase):
    def test_issue_closes_an_open_issue_only_when_its_criteria_close_it(self):
        forge = ForgeWorld(self)
        forge.comment_store(SLUG, ISSUE, [], labels=[])
        directory = forge.state.parent / "store-gh"
        directory.mkdir()
        wrapper = directory / "gh"
        wrapper.write_text(STORE_GH.format(python=sys.executable, read=ISSUE_READ, issue=ISSUE,
                                           fake=str(forge.bin / "gh")), encoding="utf-8")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        env = {"PATH": str(directory), "FORGE_WORLD": str(forge.state)}

        def issue(closes: str) -> tuple[int, dict]:
            return call(env, "issue", "--repo", SLUG, "--issue", str(ISSUE), "--closes", closes)

        self.assertEqual(issue("false"), (0, {"verdict": "open-criteria"}))
        self.assertEqual(forge.issue()["state"], "open")
        self.assertEqual(forge.argvs("gh"), [])
        self.assertEqual(issue("true"), (0, {"verdict": "closed"}))
        self.assertEqual((forge.issue()["state"], forge.issue()["state_reason"]), ("closed", "completed"))
        self.assertEqual(issue("true"), (0, {"verdict": "closed"}))
        closes = [argv for argv in forge.argvs("gh") if argv[:3] == ["api", "-X", "PATCH"]]
        self.assertEqual(len(closes), 1, closes)


class GitTest(unittest.TestCase):
    def setUp(self):
        self.landing = LandingWorld(self)
        self.world = self.landing.world
        self.root = self.landing.fixture.root
        self.env = self.landing.env

    def call(self, *args: str) -> tuple[int, dict]:
        return call(self.env, *args)

    def git(self, *args: str, root=None) -> str:
        return self.world.git(root or self.root, *args).strip()


class WorktreeTest(GitTest):
    def test_a_clean_worktree_is_removed_and_a_dirty_one_is_kept(self):
        path = self.landing.worktree()
        args = ("worktree", "--repo-root", str(self.root), "--worktree-path")
        (path / "scratch.txt").write_text("kept\n", encoding="utf-8")
        self.assertEqual(self.call(*args, str(path)), (0, {"verdict": "dirty"}))
        self.assertTrue((path / "scratch.txt").is_file())
        (path / "scratch.txt").unlink()
        self.assertEqual(self.call(*args, str(path)), (0, {"verdict": "removed"}))
        self.assertFalse(path.exists())
        self.assertEqual(self.call(*args, str(path)), (0, {"verdict": "removed"}))
        self.assertEqual(self.call(*args, str(self.root.parent / "nowhere")), (0, {"verdict": "removed"}))


class ForwardTest(GitTest):
    def forward(self) -> tuple[int, dict]:
        return self.call("forward", "--repo-root", str(self.root), "--integration-branch", "main")

    def test_forward_fast_forwards_only_a_clean_checkout_on_the_integration_branch(self):
        before = self.git("rev-parse", "main")
        advanced = self.world.advance(self.root, "main")
        self.git("checkout", "--quiet", "-b", "elsewhere")
        self.assertEqual(self.forward(), (0, {"verdict": "skipped"}))
        self.assertEqual(self.git("rev-parse", "main"), before)
        self.assertEqual(self.git("rev-parse", "origin/main"), advanced)

        self.git("checkout", "--quiet", "main")
        (self.root / "README.md").write_text("changed\n", encoding="utf-8")
        self.assertEqual(self.forward(), (0, {"verdict": "skipped"}))
        self.assertEqual(self.git("rev-parse", "main"), before)

        self.git("checkout", "--quiet", "--", "README.md")
        (self.root / "untracked.txt").write_text("not tracked\n", encoding="utf-8")
        self.assertEqual(self.forward(), (0, {"verdict": "forwarded"}))
        self.assertEqual((self.git("rev-parse", "main"), self.git("rev-parse", "origin/main")),
                         (advanced, advanced))
        self.assertEqual(self.forward(), (0, {"verdict": "forwarded"}))


class BranchTest(GitTest):
    def test_branch_reads_gone_or_kept(self):
        args = ("branch", "--repo-root", str(self.root), "--branch")
        self.assertEqual(self.call(*args, "main"), (0, {"verdict": "kept"}))
        self.assertEqual(self.call(*args, "issue-41-x"), (0, {"verdict": "gone"}))
        self.git("branch", "issue-41-x")
        self.assertEqual(self.call(*args, "issue-41-x"), (0, {"verdict": "kept"}))
        self.git("branch", "-d", "issue-41-x")
        self.assertEqual(self.call(*args, "issue-41-x"), (0, {"verdict": "gone"}))


class ReadTest(GitTest):
    def read(self, *extra: str) -> tuple[int, dict]:
        return self.call("read", "--repo-root", str(self.root), "--issue", str(ISSUE), "--repo", SLUG, *extra)

    def test_read_answers_merged_with_the_placement_and_the_criteria(self):
        forge = self.landing.forge
        forge.respond_json("gh", PR_LIST, [{"number": 7, "mergeCommit": {"oid": SHA}}])
        status, merged = self.read()
        place = {"branch": "issue-41-add-a-greeting",
                 "worktree_path": str(self.landing.fixture.worktree_root
                                      / (self.landing.fixture.worktree_prefix + "issue-41-add-a-greeting")),
                 "integration_branch": "main"}
        self.assertEqual((status, merged), (0, {"verdict": "merged", **place, "closes": True,
                                                "pr": 7, "merge_commit": SHA}))
        forge.respond_json("gh", ISSUE_READ, {"number": ISSUE, "title": "Add a greeting", "state": "open",
                                              "labels": [], "body": BODY.replace("[code]", "[human]")})
        self.assertEqual(self.read()[1]["closes"], False)
        forge.respond_json("gh", PR_LIST, [])
        self.assertEqual(self.read(), (0, {"verdict": "unmerged"}))

    def test_read_given_a_head_settles_only_on_a_merged_pull_request_with_that_head(self):
        forge = self.landing.forge
        other, head = "b" * 40, "c" * 40
        earlier = {"number": 7, "mergeCommit": {"oid": SHA}, "headRefOid": other}
        forge.respond_json("gh", PR_LIST, [earlier])
        self.assertEqual(self.read("--head", head), (0, {"verdict": "unmerged"}))
        self.assertEqual(self.read()[1]["pr"], 7)
        later = {"number": 9, "mergeCommit": {"oid": SHA}, "headRefOid": head}
        forge.respond_json("gh", PR_LIST, [later, earlier])
        status, merged = self.read("--head", head)
        self.assertEqual((status, merged["verdict"], merged["pr"]), (0, "merged", 9))
        forge.respond_json("gh", PR_LIST, [{"number": 9, "mergeCommit": {"oid": SHA}}])
        self.assertEqual(self.read("--head", head), (0, {"verdict": "unmerged"}))


if __name__ == "__main__":
    unittest.main()
