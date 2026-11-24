"""deliver-batch.js names CI as the full proof when a child verified before the pull request.

The batch has no Verify phase: its children verify, and its landing prompt carries their results as the pull request's
Evidence. Run: just agent-workflow-tests
"""

from __future__ import annotations

import unittest

from . import test_deliver_batch_program as batch
from . import test_deliver_standard_before_pull_request as standard

TIER = "integration"

SENTENCE = ("the verification above ran the pre-pull-request list, and CI on this pull request runs the full "
            "declared verification")
DECLARED = "Run the project's declared verification"
OPEN_PR = {"number": 41, "head_branch": "issue-1-x"}
BATCH_SETUP_READ = ("and verification_before_pull_request (only when bindings.workflow.verification_before_pull_request is a "
                    "list: for each of its ids {id, argv: its bindings.commands argv, cwd: its cwd relative to "
                    "project.root, . for the root}; omit it when the binding is absent or null).")
SET = {"setup": {"verification_before_pull_request": standard.LOCAL_ONE}}
CLEAN = {"status": "done", "conflicted": False, "head": batch.B, "notes": "ok"}
FOUND = batch.SyncFixRoundTest.FOUND


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


def lsweep(extra):
    """The two landing scenarios that reach every landing step that runs tests, each with `extra` merged into its patch."""
    sync = dict(patch={**batch.BEHIND, **extra},
                replies={"land-sync-1-1": batch.ABORTED, "land-sync-resolve-1-1": batch.SyncFixRoundTest.CONFLICTED,
                         "land-sync-review-1-1": FOUND})
    red = dict(patch={**batch.folded(batch.CI_RED), **extra},
               replies={"land-record-1-1": {"ok": True, "head": batch.FIX, "checks": dict(batch.CI_RED, head=batch.FIX)}})
    return [(sync, {"land-sync-1-1", "land-sync-resolve-1-1", "land-sync-review-1-1", "land-sync-fix-1-1",
                    "land-sync-rereview-1-1"}),
            (red, {"land-fix-1", "land-fix-review-1"})]


def sweep(extra):
    return [(want, *batch.run(**scenario)) for scenario, want in lsweep(extra)]


class SetBindingLandingTest(unittest.TestCase):
    """With the pre-pull-request list set, every landing step that runs tests names its commands, not the suite."""

    def test_with_the_binding_set_every_landing_step_that_runs_tests_names_its_commands(self):
        for want, _, calls, _ in sweep(SET):
            for label in want:
                self.assertIn(standard.LC, batch.prompt(calls, label), label)
            for call in calls:
                if call.get("agentType") == "reviewer":
                    self.assertEqual(call["prompt"].count(standard.REVIEW_TESTS), 1, call["label"])
            if "land-sync-resolve-1-1" in want:
                self.assertIn(standard.whole_set("the files you resolved by hand"),
                              batch.prompt(calls, "land-sync-resolve-1-1"))
                self.assertIn(standard.PUSH_SET, batch.prompt(calls, "land-sync-fix-1-1"))
            else:
                self.assertIn(standard.PUSH_SET, batch.prompt(calls, "land-fix-1"))

    def test_with_the_binding_set_no_landing_prompt_names_the_suite(self):
        for _, _, calls, _ in sweep(SET):
            for call in calls:
                for phrase in standard.OLD_PHRASES:
                    self.assertNotIn(phrase, call.get("prompt", ""), call["label"])

    def test_the_setup_reads_the_binding(self):
        _, calls, _ = batch.run()
        self.assertIn(BATCH_SETUP_READ, batch.prompt(calls, "setup"))
        schema = next(c for c in calls if c["label"] == "setup")["schema"]
        self.assertEqual(schema["properties"]["verification_before_pull_request"]["items"]["required"],
                         ["id", "argv", "cwd"])

    def test_a_clean_landing_sync_that_changes_no_pull_request_file_runs_no_tests(self):
        sentence = standard.sync_tests("/r/.wt/w-issue-1-x", "dev", batch.SHA)
        result, calls, _ = batch.run(patch={**batch.BEHIND, **SET}, replies={"land-sync-1-1": CLEAN})
        self.assertIn(sentence, batch.prompt(calls, "land-sync-1-1"))
        self.assertEqual(batch.row(result, 1)["outcome"], "landed")
        later = calls[[c["label"] for c in calls].index("land-sync-1-1") + 1:]
        self.assertEqual([c["label"] for c in later if c.get("agentType") == "implementer"], [])
        _, calls, _ = batch.run(patch=batch.BEHIND, replies={"land-sync-1-1": CLEAN})
        self.assertNotIn(sentence, batch.prompt(calls, "land-sync-1-1"))

    def test_with_the_binding_absent_every_landing_prompt_reads_as_before(self):
        for want, _, calls, _ in sweep({}):
            for call in calls:
                self.assertNotIn(standard.MARK, call.get("prompt", ""), call["label"])
                self.assertNotIn(standard.REVIEW_TESTS, call.get("prompt", ""), call["label"])
            if "land-sync-resolve-1-1" in want:
                for needle in batch.WHOLE_RUN:
                    self.assertIn(needle, batch.prompt(calls, "land-sync-resolve-1-1"))
            else:
                self.assertIn("(with none declared, any fast suite the project declares), not the declared verification,",
                              batch.prompt(calls, "land-fix-1"))

    def test_a_malformed_binding_leaves_every_landing_prompt_as_absent(self):
        absent = [{c["label"]: c.get("prompt") for c in calls} for _, _, calls, _ in sweep({})]
        for binding in ([], None, "lint", [{"id": "x"}]):
            with self.subTest(binding=binding):
                runs = sweep({"setup": {"verification_before_pull_request": binding}})
                for (_, result, calls, _), before in zip(runs, absent):
                    self.assertNotEqual(result.get("stage"), "setup")
                    self.assertEqual({c["label"]: c.get("prompt") for c in calls}, before)


if __name__ == "__main__":
    unittest.main()
