"""The suite holds `standard:P19` by reading every worker brief that deliver-batch.js builds for a landing or a train.

Each implementer and reviewer brief states the edit-tool, scratch-directory, script-file and probe rules once.
Run: just agent-workflow-tests
"""

from __future__ import annotations

import re
import unittest

from . import test_deliver_batch_program as batch
from . import test_deliver_standard_work_rules as rules

TIER = "integration"

WORKERS = {batch.IMPL, batch.REV}
LIFECYCLE = re.compile(r"never after cd &&: git -C (.+?) push origin ")


def scratch_under(w):
    return f"the deliver-standard/scratch directory under the git dir that git -C {w} rev-parse --absolute-git-dir prints"


class BatchWorkRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calls = batch.all_calls()

    def worktree_of(self, call):
        found = LIFECYCLE.search(call["prompt"]).group(1)
        if call["label"].startswith("train-build-"):
            self.assertEqual(found, "<the scratch worktree>")
        else:
            self.assertRegex(found, r"/r/\.wt/w-issue-\d+-x")
        return found

    def test_every_landing_implementer_and_reviewer_brief_states_the_tool_and_probe_rules(self):
        stems = set()
        for call in self.calls:
            label, prompt = call["label"], call["prompt"]
            if call["agentType"] in WORKERS:
                stems.add(batch.AgentTypeTest.stem_of(label))
                w = self.worktree_of(call)
                head = rules.tool_rules(scratch_under(w)) + "\n" + rules.PROBE_RULE + "\n"
                self.assertTrue(prompt.startswith(head), label)
                rules.assert_each_rule_once(self, prompt, scratch_under(w), label)
            else:
                for opener in rules.OPENERS:
                    self.assertNotIn(opener, prompt, label)
        self.assertEqual(stems, {stem for stem, kinds in batch.EXPECTED.items() if kinds & WORKERS})

    def test_no_brief_tells_an_agent_to_edit_with_python(self):
        for call in self.calls:
            with self.subTest(call["label"]):
                self.assertNotIn("use python for edits", call["prompt"])
                if rules.HARD in call["prompt"]:
                    self.assertIn("Never sed -i.", call["prompt"])

    def test_the_hard_rules_let_a_worker_use_the_named_scratch_directory(self):
        hard = [c for c in self.calls if rules.HARD in c["prompt"]]
        for call in hard:
            self.assertEqual(call["prompt"].count(rules.WORK_ONLY), 1, call["label"])
        self.assertTrue([c for c in hard if c["agentType"] == batch.IMPL])
        for call in self.calls:
            if call["agentType"] in WORKERS:
                named = "put scratch and probe files in " + scratch_under(self.worktree_of(call)) + " "
                self.assertIn(named, call["prompt"], call["label"])

    def test_a_rerun_review_carries_each_rule_once(self):
        out = batch.run_full(patch=batch.BEHIND, replies={
            "land-sync-1-1": batch.ABORTED, "land-sync-resolve-1-1": batch.SyncFixRoundTest.CONFLICTED,
            "land-sync-review-1-1": [{"verdict": "incomplete", "findings": []}, {"verdict": "pass", "findings": []}]})
        for label in ("land-sync-review-1-1", "land-sync-review-1-1-again"):
            rules.assert_each_rule_once(self, batch.prompt(out["calls"], label), scratch_under(batch.WT1), label)


if __name__ == "__main__":
    unittest.main()
