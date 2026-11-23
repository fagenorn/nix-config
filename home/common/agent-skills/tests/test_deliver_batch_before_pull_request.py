"""deliver-batch.js names CI as the full proof when a child verified before the pull request.

The batch has no Verify phase: its children verify, and its landing prompt carries their results as the pull request's
Evidence. Run: just agent-workflow-tests
"""

from __future__ import annotations

import unittest

from . import test_deliver_batch_program as batch

TIER = "integration"

SENTENCE = ("the verification above ran the pre-pull-request list, and CI on this pull request runs the full "
            "declared verification")
DECLARED = "Run the project's declared verification"
OPEN_PR = {"number": 41, "head_branch": "issue-1-x"}


def ready_child(scope=None):
    child = {"stage": "ready", "head": batch.SHA, "branch": "issue-1-x", "worktree": "/r/.wt/w-issue-1-x",
             "verify": [{"id": "lint", "status": "pass", "summary": "ok"},
                        {"id": "test-touched", "status": "pass", "summary": "ok"}],
             "tasks": [{"n": 1}], "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
             "cont": {"setup": {"holder": "h1/b1"}, "lane": "standard"}}
    if scope is not None:
        child["verify_scope"] = scope
    return child


class PrePullRequestEvidenceTest(unittest.TestCase):
    def landing(self, scope):
        _, calls, _ = batch.run(children={"1": ready_child(scope)})
        return calls, batch.prompt(calls, "land-pr-1")

    def test_a_child_verified_before_the_pull_request_names_ci_as_the_full_proof(self):
        _, text = self.landing("before_pull_request")
        self.assertIn(SENTENCE, text)
        self.assertIn("test-touched", text)

    def test_an_absent_scope_adds_no_ci_sentence_and_the_batch_runs_no_verification(self):
        calls, text = self.landing(None)
        self.assertNotIn(SENTENCE, text)
        self.assertIn("test-touched", text)
        self.assertEqual([c["label"] for c in calls if DECLARED in c.get("prompt", "")], [])

    def test_the_batch_runs_no_verification_with_the_scope_set(self):
        calls, _ = self.landing("before_pull_request")
        self.assertEqual([c["label"] for c in calls if DECLARED in c.get("prompt", "")], [])

    def test_a_readopted_pull_request_adds_no_ci_sentence(self):
        _, calls, _ = batch.run(patch={"facts-1": {"open_pr": OPEN_PR}})
        self.assertIn("readopt-1", batch.labels(calls))
        self.assertNotIn("child-1", batch.labels(calls))
        self.assertNotIn(SENTENCE, batch.prompt(calls, "land-pr-1"))


if __name__ == "__main__":
    unittest.main()
