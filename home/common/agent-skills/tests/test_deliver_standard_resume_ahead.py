"""deliver-standard.js scenarios: a resumed delivery whose branch holds commits ahead of its base.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import unittest

from .test_deliver_standard_program import ARGS, BR, F, MARKED, PLAN, RESUME, SHA, bplan, labels, prompt, run, tasks

TIER = "integration"
AHEAD = "d" * 40
NONE = {"start_head": SHA, "commit": SHA}
BRANCH_FACTS = {"name": "cand", "current": "cand", "toplevel": "/r/.wt/cand", "common_dir": "/r/.git"}


class ResumeAheadTest(unittest.TestCase):
    """Tasks recorded done with no new commit end at no-changes only when the branch holds nothing ahead of its base."""

    def stopped(self, **kw):
        """The no-changes stop of a two-task plan whose tasks commit nothing, and the continuation it leaves."""
        result, _ = run(replies={"plan": dict(PLAN, tasks=tasks(2))}, patch={"impl-1": NONE, "impl-2": NONE, **kw})
        self.assertEqual(result["stage"], "no-changes")
        return result["cont"]

    def test_a_resume_whose_branch_is_ahead_of_its_base_reviews_without_redispatching_the_tasks(self):
        result, calls = run(args=dict(ARGS, cont=self.stopped()), patch={"setup": {"head": AHEAD}})
        got = labels(calls)
        self.assertEqual(result["stage"], "done")
        self.assertTrue(any(label.startswith("final-") for label in got), got)
        for label in ("plan", "impl-1", "impl-2"):
            self.assertNotIn(label, got)

    def test_a_resume_whose_branch_is_at_its_base_stays_at_no_changes(self):
        result, calls = run(args=dict(ARGS, cont=self.stopped()), patch={"setup": {"head": SHA}})
        self.assertEqual(result["stage"], "no-changes")
        self.assertEqual(labels(calls), ["setup"])

    def test_a_resume_that_read_no_head_does_not_pick_no_changes(self):
        result, calls = run(args=dict(ARGS, cont=self.stopped()), patch={"setup": {"head": ""}})
        self.assertNotEqual(result["stage"], "no-changes")
        self.assertEqual(result["stage"], "setup")
        self.assertEqual(result["missing"], ["head"])
        self.assertEqual(labels(calls), ["setup"])

    def test_a_declared_branch_with_a_ref_name_base_and_no_new_commit_stops_at_no_changes(self):
        """BR's base is the ref name origin/dev: it is never compared with a sha as a string."""
        self.assertEqual(BR["base"], "origin/dev")
        result, calls = run(replies={"plan": bplan()}, patch={"impl-1": NONE, "impl-2": {"start_head": BR["head"], "commit": BR["head"]}})
        self.assertEqual(result["stage"], "no-changes")
        self.assertFalse(any(label.startswith("final-") for label in labels(calls)), labels(calls))

    def test_a_declared_branch_moved_since_the_plan_is_ahead_and_goes_to_the_final_review(self):
        moved = "e" * 40
        stopped, _ = run(replies={"plan": bplan()}, patch={"impl-1": NONE, "impl-2": {"start_head": BR["head"], "commit": BR["head"]}})
        self.assertEqual(stopped["stage"], "no-changes")
        facts = [dict(BRANCH_FACTS, head=moved)]
        result, calls = run(args=dict(ARGS, cont=stopped["cont"]), patch={"setup": {"head": SHA, "branch_heads": facts}})
        self.assertEqual(result["stage"], "done")
        self.assertTrue(any(label.startswith("final-") for label in labels(calls)), labels(calls))


class LookFixAheadTest(unittest.TestCase):
    """A look fix made by an earlier attempt is read against the head the owner looked at."""

    def look_cont(self):
        result, _ = run(patch={"setup": {"look": MARKED}})
        self.assertEqual(result["stage"], "awaiting-look")
        return result["cont"]

    def test_a_look_fix_made_by_an_earlier_attempt_is_reviewed_and_pushed(self):
        patch = dict(RESUME, **{"setup": {"look": MARKED, "head": F}, "look-fix": {"start_head": F, "commit": F},
                                "verify": {"head": F}, "look-pr": {"head": F}})
        result, calls = run(args=dict(ARGS, cont=self.look_cont(), look={"answer": "changes", "words": "make the label bold"}), patch=patch)
        got = labels(calls)
        self.assertEqual(result["stage"], "awaiting-look")
        self.assertEqual(result["head"], F)
        self.assertEqual([l for l in got if l in ("look-fix", "look-fix-review", "verify", "look-pr")],
                         ["look-fix", "look-fix-review", "verify", "look-pr"])
        self.assertIn(f"git -C /r/.wt/w-issue-9-x diff {SHA}..{F}", prompt(calls, "look-fix-review"))

    def test_a_look_fix_with_the_branch_at_the_looked_at_head_still_stops(self):
        noop = dict(RESUME, **{"setup": {"look": MARKED, "head": SHA}, "look-fix": {"start_head": SHA, "commit": SHA}})
        result, calls = run(args=dict(ARGS, cont=self.look_cont(), look={"answer": "changes", "words": "make the label bold"}), patch=noop)
        self.assertEqual(result["stage"], "look-fix")
        for label in ("look-fix-review", "verify", "look-pr", "look-push", "merge"):
            self.assertNotIn(label, labels(calls))
