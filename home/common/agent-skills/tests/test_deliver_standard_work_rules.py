"""The suite holds `standard:P19` by reading every worker and Codex brief that deliver-standard.js builds.

Each implementer and reviewer brief states the edit-tool, scratch-directory, script-file and probe rules once;
each Codex review passes the probe rule on. Run: just agent-workflow-tests
"""

from __future__ import annotations

import unittest

from . import test_deliver_standard_program as program

TIER = "integration"

PROBE_RULE = (
    "A stress probe with large or deeply nested inputs fixes a finite cap on time and peak memory before it starts, starts at a size that fits in 1 GiB, grows in steps (for example doubling), measures time and peak memory at each step and stops before a step whose projected peak would exceed the cap or at the first step that grows faster than its input, never an unbounded loop or one giant input on a shared host. A test that proves a memory bound measures the peak at a small capped size (for example with tracemalloc at a nesting depth whose peak stays under a few hundred MiB) and passes only when that peak is within the claimed limit, never by running the large case."
)
EDIT_RULE = "Change files only with the Edit and Write tools, never with a shell heredoc or an inline interpreter writing them"
SCRIPT_RULE = ("run a one-off evaluation as a script file kept in that directory and run by path, never as an inline "
               "program handed to an interpreter on its command line or through a heredoc")
OPENERS = ("Change files only with", "put scratch and probe files in", "run a one-off evaluation as", "A stress probe")
WORK_ONLY = ("Work only in the worktree path you are given; the one exception is the job scratch directory your brief "
             "names, for scratch, probe and one-off script files.")
HARD = "Hard rules for this step"
WORKERS = {program.IMPL, program.REV, program.LITE}
CODEX = {"plan-codex", "direct-codex", "final-codex"}
DEFAULT_PLAN_DIR = "/r/.git/worktrees/w/deliver-standard"


def scratch_rule(directory):
    return f"put scratch and probe files in {directory} (create it with mkdir -p), never under /tmp"


def tool_rules(directory):
    return f"{EDIT_RULE}; {scratch_rule(directory)}; {SCRIPT_RULE}."


def assert_each_rule_once(case, prompt, directory, label):
    with case.subTest(label):
        for text in (EDIT_RULE, scratch_rule(directory), SCRIPT_RULE, PROBE_RULE, *OPENERS):
            case.assertEqual(prompt.count(text), 1, text)


class WorkRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = []
        for scenario in program.SCENARIOS:
            cont = (scenario.get("args") or {}).get("cont") or {}
            plan_dir = (cont.get("setup") or {}).get("plan_dir", DEFAULT_PLAN_DIR)
            cls.runs.append((plan_dir, program.run(**scenario)[1]))

    def test_every_implementer_and_reviewer_brief_states_the_tool_and_probe_rules(self):
        rounds = {program.REV: program.REVIEWER_ROUNDS + "\n", program.IMPL: program.IMPLEMENTER_ROUNDS + "\n"}
        stems = set()
        for plan_dir, calls in self.runs:
            directory = f"{plan_dir}/scratch"
            for call in calls:
                label, prompt, kind = call["label"], call["prompt"], call["agentType"]
                if kind in WORKERS:
                    stems.add(program.AgentTypeTest.stem_of(label))
                    head = rounds.get(kind, "") + tool_rules(directory) + "\n" + PROBE_RULE + "\n"
                    self.assertTrue(prompt.startswith(head), label)
                    assert_each_rule_once(self, prompt, directory, label)
                elif label not in CODEX:
                    for opener in OPENERS:
                        self.assertNotIn(opener, prompt, label)
        self.assertEqual(stems, {stem for stem, kinds in program.EXPECTED.items() if kinds & WORKERS})

    def test_every_codex_review_passes_the_probe_rule_to_codex(self):
        seen = {call["label"] for _, calls in self.runs for call in calls if call["label"] in CODEX}
        self.assertEqual(seen, CODEX)
        for _, calls in self.runs:
            for call in calls:
                if call["label"] not in CODEX:
                    continue
                with self.subTest(call["label"]):
                    self.assertEqual(call["prompt"].count(PROBE_RULE), 1)
                    self.assertEqual(call["prompt"].count("A stress probe"), 1)
                    for opener in OPENERS[:3]:
                        self.assertNotIn(opener, call["prompt"])

    def test_no_brief_tells_an_agent_to_edit_with_python(self):
        for _, calls in self.runs:
            for call in calls:
                with self.subTest(call["label"]):
                    self.assertNotIn("use python for edits", call["prompt"])
                    if HARD in call["prompt"]:
                        self.assertIn("Never sed -i.", call["prompt"])
                        self.assertNotIn("Never sed -i (", call["prompt"])

    def test_the_hard_rules_let_a_worker_use_the_named_scratch_directory(self):
        hard = set()
        for plan_dir, calls in self.runs:
            for call in calls:
                if HARD in call["prompt"]:
                    hard.add(call["label"])
                    self.assertEqual(call["prompt"].count(WORK_ONLY), 1, call["label"])
        self.assertIn("impl-1", hard)
        calls = self.runs[0][1]
        for label in ("impl-1", "review-1"):
            self.assertIn(f"put scratch and probe files in {DEFAULT_PLAN_DIR}/scratch ", program.prompt(calls, label))

    def test_a_rerun_review_carries_each_rule_once(self):
        calls = program.run_out(replies={"review-1": program.INCOMPLETE})["calls"]
        for label in ("review-1", "review-1-again"):
            prompt = program.prompt(calls, label)
            assert_each_rule_once(self, prompt, DEFAULT_PLAN_DIR + "/scratch", label)
            self.assertIn(f"put scratch and probe files in {DEFAULT_PLAN_DIR}/scratch ", prompt)

    def test_the_probe_rule_is_the_testing_standard_p19(self):
        lines = (program.REPO_ROOT / "docs/standards/testing.md").read_text(encoding="utf-8").splitlines()
        heading = "### P19. A stress probe grows in bounded steps"
        self.assertEqual(lines.count(heading), 1)
        body = [line for line in lines[lines.index(heading) + 1:] if line.strip()][0]
        self.assertEqual(body, PROBE_RULE + " ([issue 1859](https://github.com/fagenorn/nix-config/issues/1859))")
        texts = [path.read_text(encoding="utf-8").splitlines()
                 for path in (program.PROGRAM, program.PROGRAM.with_name("deliver-batch.js"))]
        for prefix in ("const PROBE_RULE = ", "const TOOL_RULES = ", "const WORKERS = "):
            found = [[line for line in text if line.startswith(prefix)] for text in texts]
            self.assertEqual([len(f) for f in found], [1, 1], prefix)
            self.assertEqual(found[0], found[1], prefix)


if __name__ == "__main__":
    unittest.main()
