"""The look-before-merge gate, end to end on a throwaway repository (issue 1142).

Proves, with the real delivery programs, the real lifecycle guard and the real
`look-approval` command on one world, that a marked issue's pull request is not
merged until the owner's recorded look names its head: a batch of one marked and
one unmarked issue lands the unmarked one only, the guard refuses a direct merge
of the marked one, a changes answer moves the head, an approval of the old head
is stale, and an approval of the new head posts and merges.

Run: just agent-workflow-tests
"""
import re
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

from .look_gate_world import (MARKED, PROGRAMS, REFUSAL, SLUG, LookGateWorld, StepFailure, mutant_guard,
                              play_scenario)
from .program_bridge import run_program

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "home/common/agent-skills/tests"))
from clerk_tools import outside_clerk_tools  # noqa: E402

WORDS = "make the \"heading\" bold:\nit costs $5 and `x` and 'y' \\ done \u00e9\n\n"


class LookGateEndToEndTest(unittest.TestCase):
    @staticmethod
    def open_marked_pull_request(world):
        """One commit on issue 11's branch through the actor's setup and impl-1 rows, and PR 111."""
        def ask(label, prompt=""):
            return world.actor({"type": "agent", "id": 1, "label": label, "program": "deliver-standard",
                                "issue": MARKED, "mode": "ship", "prompt": prompt, "schema": None,
                                "agentType": "clerk"})
        ask("setup")
        ask("impl-1")
        return ask("look-pr")["head"]

    def test_the_six_steps_hold_on_a_throwaway_repository(self):
        out = play_scenario(self)
        self.assertEqual(out["approve"]["result"]["stage"], "done")

    def fix_answer(self, world, action, labels, prompts, words=WORDS):
        """Run the owner's fix answer against the awaiting-look stop of `world`, recording each step's label and prompt."""
        def actor(message):
            labels.append(message["label"])
            prompts[message["label"]] = message["prompt"]
            return world.actor(message)

        return run_program(PROGRAMS / "deliver-standard.js", {
            "repo_root": str(world.clone), "issue": MARKED, "batch_id": "h1-20261116-1200", "mode": "ship",
            "cont": action["cont"], "look": {"answer": "fix", "head": action["head"], "words": words}}, actor)

    def test_a_fix_answer_records_the_owners_exact_words_with_the_clerks_tools_and_reaches_the_fix_round(self):
        out = play_scenario(self, through=2)
        world, action = out["world"], out["batch"]["result"]["owner_actions"][0]
        prompts, labels = {}, []
        run = self.fix_answer(world, action, labels, prompts)
        self.assertIsNone(run["error"])
        self.assertIn("look-post", labels)
        self.assertLess(labels.index("look-post"), labels.index("look-fix"))
        self.assertEqual(outside_clerk_tools(prompts["look-post"]), set())
        words_file = Path(shlex.split(re.search(r"--words-file ([^\n]*)", prompts["look-post"]).group(1))[0])
        self.assertEqual(words_file.read_bytes(), WORDS.encode("utf-8"))
        self.assertIn("answer=fix", str(world.look_comments()[-1]["body"]).split("\n", 1)[0])

    def test_a_failed_words_write_records_no_approval_and_runs_no_fix(self):
        out = play_scenario(self, through=2)
        world, action = out["world"], out["batch"]["result"]["owner_actions"][0]
        before = len(world.look_comments())
        world.break_decoder()
        prompts, labels = {}, []
        run = self.fix_answer(world, action, labels, prompts)
        self.assertIsNone(run["error"])
        self.assertEqual(run["result"]["stage"], "look-approve")
        self.assertIn("look-post", labels)
        for label in ("look-fix", "merge"):
            self.assertNotIn(label, labels)
        self.assertEqual(len(world.look_comments()), before, "a failed write still recorded an approval")

    def test_the_actor_merges_nothing_the_guard_refuses(self):
        world = LookGateWorld(self)
        head = self.open_marked_pull_request(world)
        main0 = world.origin_tip("main")
        reply = world.actor({
            "type": "agent", "id": 1, "label": "merge", "program": "deliver-standard",
            "issue": 11, "mode": "ship",
            "prompt": (f"Only when lock's verdict is already_held or moved, merge PR #111: run, "
                       f"alone and exactly: gh pr merge 111 --repo {SLUG} --merge "
                       f"--match-head-commit {head} --delete-branch\n"),
            "schema": None, "agentType": "clerk"})
        self.assertIs(reply["merged"], False)
        self.assertIn(REFUSAL.format(issue=11, short=head[:7]), reply["notes"])
        self.assertEqual(world.origin_tip("main"), main0)
        self.assertEqual(world.pr_of(11)["state"], "OPEN")

    def test_the_scenario_fails_when_the_look_refusal_is_removed(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        guard = mutant_guard(Path(tmp.name))
        self.assertEqual(guard.read_text().count("return None  # mutant (#1142)"), 1)
        with self.assertRaises(StepFailure) as caught:
            play_scenario(self, guard_source=guard, through=3)
        world = caught.exception.world
        command, code, stderr = world.guard_log[-1]
        self.assertEqual(caught.exception.step, 3)
        self.assertTrue(str(caught.exception).startswith("step 3: "))
        self.assertEqual(
            command, f"gh pr merge 111 --repo {SLUG} --merge --match-head-commit "
                     f"{world.pr_of(MARKED)['head']} --delete-branch")
        self.assertEqual(code, 0, f"the mutant guard did not admit the step-3 merge: exit {code}: {stderr}")
        sys.stderr.write(f"{caught.exception}\nexit {code}\n")


if __name__ == "__main__":
    unittest.main()
