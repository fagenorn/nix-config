"""Tests that the outline prompts state every rule the `outline-mapped` grader enforces (`engine_graders`)."""

from __future__ import annotations

import unittest

from agent_tools.delivery.engine_graders import GRADERS
from tests.engine_procedure_copies import PROCEDURES

TIER = "fast"

ISSUE = "# t\n\n## Acceptance criteria\n- [ ] [code] greet() returns the greeting\n- [ ] [code] `just lint` and `just test` pass\n"
SLICE = {"n": 1, "test": "t", "assertion": "a"}
CRITERIA = [{"id": "AC1", "slice": 1}, {"id": "AC2", "slice": 1}]


def grade(slices, criteria):
    return GRADERS["outline-mapped"].grade({"outline.slices": slices, "outline.criteria": criteria,
                                            "outline.issue_text": ISSUE})


def prompt(name: str) -> str:
    return " ".join((PROCEDURES / name).read_text("utf-8").split())


class OutlinePromptTest(unittest.TestCase):
    def test_the_grader_refuses_each_input_the_fix_prompt_must_teach(self):
        self.assertEqual(grade([SLICE], CRITERIA), "mapped")
        self.assertEqual(grade([dict(SLICE, n=3)], CRITERIA), "unmapped")
        self.assertEqual(grade([SLICE], [CRITERIA[0], dict(CRITERIA[0])]), "unmapped")
        self.assertEqual(grade([SLICE], [CRITERIA[0], {"id": "error path covered", "slice": 1}]), "unmapped")
        self.assertEqual(grade([SLICE], [CRITERIA[0]]), "unmapped")

    def test_the_fix_prompt_states_the_slice_numbering_the_grader_requires(self):
        text = prompt("outline-fix.md")
        self.assertIn("numbered 1, 2, 3 and so on in build order, each number once, with no gap", text)

    def test_the_fix_prompt_states_the_criterion_id_set_the_grader_requires(self):
        text = prompt("outline-fix.md")
        self.assertIn("each id AC<i> of the issue exactly once", text)
        self.assertIn("no id the issue does not have", text)
        self.assertIn("no criterion repeated", text)

    def test_the_first_prompt_does_not_tell_the_planner_to_drop_a_criterion_the_grader_requires(self):
        text = prompt("outline.md")
        self.assertNotIn("Return no criterion that only restates", text)
        self.assertIn("including one that only restates a declared verification command passing", text)


if __name__ == "__main__":
    unittest.main()
