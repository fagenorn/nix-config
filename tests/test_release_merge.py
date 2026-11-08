"""Shared released-commit resolution (issue 582 P3). Run: just agent-workflow-tests"""
import ast
import inspect
import time
import unittest

from agent_tools import release_merge
from .actions_world import BASE_TIP, HEAD, MERGE, PR, PR_VIEW, SLUG, ActionsWorld, commit_argv


def parameters(candidate: dict) -> dict:
    return {"target": {"kind": "github_repository", "repository": SLUG, "branch": "main"},
            "candidate": candidate, "config": {}}


def merge_candidate() -> dict:
    return {"version": "v1.2.3", "commit": HEAD, "merge": {"pr": PR, "base_tip": BASE_TIP}}


class ReleasedCommitTest(unittest.TestCase):
    def setUp(self):
        self.world = ActionsWorld(self)

    def resolve(self, candidate: dict):
        return release_merge.released_commit(parameters(candidate), time.monotonic() + 30)

    def test_without_a_merge_the_candidate_commit_is_released_and_nothing_is_read(self):
        self.assertEqual(self.resolve({"commit": HEAD}), (HEAD, None, []))
        self.assertEqual(self.world.calls(), [])

    def test_a_merged_release_pr_releases_its_merge_commit(self):
        self.world.merged(parents=(BASE_TIP, HEAD))
        self.assertEqual(self.resolve(merge_candidate()),
                         (MERGE, None, [f"repos/{SLUG}/pulls/{PR}",
                                        f"repos/{SLUG}/git/commits/{MERGE}"]))
        self.assertEqual([c["argv"] for c in self.world.calls()], [PR_VIEW, commit_argv(MERGE)])

    def test_an_open_release_pr_is_absent_and_a_closed_one_diverges(self):
        self.world.merged(state="OPEN", oid=None)
        commit, failure, _ = self.resolve(merge_candidate())
        self.assertEqual((commit, failure["outcome"], failure["reason"]),
                         (None, "absent", "release_unmerged"))
        self.world.merged(state="CLOSED", oid=None)
        _, failure, _ = self.resolve(merge_candidate())
        self.assertEqual((failure["outcome"], failure["reason"]),
                         ("diverged", "release_merge_mismatch"))

    def test_the_module_imports_only_the_standard_library(self):
        tree = ast.parse(inspect.getsource(release_merge))
        names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for alias in node.names]
        names += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse([name for name in names if name and name.startswith("agent_tools")])
