"""Rendering contract of `agent_tools.sdd_brief` (issue 353, spec D5).

The rendering functions are imported (agent-helpers rule 5). The shipped
templates are rendered and compared with a body this file derives on its own;
no test holds a copy of their prose (rule 6).
"""
from __future__ import annotations

from pathlib import Path
import unittest

from agent_tools import sdd_brief
from agent_tools.sdd_brief import BriefError

REPO_ROOT = Path(__file__).resolve().parents[1]
SDD = REPO_ROOT / "home/common/agent-skills/skills/sdd"
TOKENS = frozenset({"[BRIEF_FILE]", "[CONTEXT]", "[REPORT_FILE]"})
VALUES = {"[BRIEF_FILE]": "/w/brief.md", "[REPORT_FILE]": "/w/report.md", "[CONTEXT]": "ctx"}
HEADER = ("Subagent:", '  description: "x"', "  prompt: |")
BODY = ("    Read [BRIEF_FILE] then [REPORT_FILE].", "", "    [CONTEXT]", "   ",
        "    Verdict: [Approved | Needs fixes]", "      indented")
RENDERED = ("Read /w/brief.md then /w/report.md.\n\nctx\n\n"
            "Verdict: [Approved | Needs fixes]\n  indented\n")


def template(*body, header=HEADER):
    return "\n".join(["# Fixture", "", "Outside [NOT_A_SLOT].", "", "```", *header, *body,
                      "```", "", "After.", ""])


def independent_body(text):
    """The fence lines after `prompt: |`, their first four characters removed (spec seam 2)."""
    lines = text.split("\n")
    opening, closing = [i for i, line in enumerate(lines) if line.startswith("```")]
    start = next(i for i in range(opening, closing) if lines[i].strip() == "prompt: |")
    return "\n".join(line[4:] for line in lines[start + 1:closing]) + "\n"


class RenderTest(unittest.TestCase):
    def test_the_body_is_dedented_and_filled(self):
        self.assertEqual(sdd_brief.render(template(*BODY), TOKENS, VALUES), RENDERED)

    def test_prompt_body_keeps_the_tokens(self):
        self.assertEqual(
            sdd_brief.prompt_body(template(*BODY)),
            "Read [BRIEF_FILE] then [REPORT_FILE].\n\n[CONTEXT]\n\n"
            "Verdict: [Approved | Needs fixes]\n  indented\n")

    def test_a_value_is_inserted_verbatim_and_never_rescanned(self):
        values = {**VALUES, "[BRIEF_FILE]": "[REPORT_FILE] \\1 $x", "[CONTEXT]": "a\n[BRIEF_FILE]"}
        self.assertEqual(
            sdd_brief.render(template(*BODY), TOKENS, values),
            "Read [REPORT_FILE] \\1 $x then /w/report.md.\n\na\n[BRIEF_FILE]\n\n"
            "Verdict: [Approved | Needs fixes]\n  indented\n")

    def test_an_empty_optional_value_removes_its_line_and_the_empty_line_after(self):
        self.assertEqual(
            sdd_brief.render(template(*BODY), TOKENS, {**VALUES, "[CONTEXT]": ""}),
            "Read /w/brief.md then /w/report.md.\n\nVerdict: [Approved | Needs fixes]\n  indented\n")

    def test_an_empty_optional_value_keeps_a_following_text_line(self):
        body = ("    [CONTEXT]", "    Read [BRIEF_FILE] then [REPORT_FILE].")
        self.assertEqual(
            sdd_brief.render(template(*body), TOKENS, {**VALUES, "[CONTEXT]": ""}),
            "Read /w/brief.md then /w/report.md.\n")

    def test_a_labeled_fence_is_not_the_prompt(self):
        text = template(*BODY) + "\n```python\nprint('[ZED]')\n```\n"
        self.assertEqual(sdd_brief.render(text, TOKENS, VALUES), RENDERED)

    def test_every_other_shape_is_refused(self):
        good = template(*BODY)
        cases = {
            "no fence": ("# T\n\nno fence\n", TOKENS, VALUES),
            "two unlabeled fences": (good + "\n```\nmore\n```\n", TOKENS, VALUES),
            "unclosed fence": (good.replace("```\n\nAfter.\n", "\nAfter.\n"), TOKENS, VALUES),
            "no prompt line": (template(*BODY, header=("Subagent:",)), TOKENS, VALUES),
            "two prompt lines": (template("    prompt: |", *BODY), TOKENS, VALUES),
            "under-indented line": (template(*BODY, "  short"), TOKENS, VALUES),
            "last body line empty": (template(*BODY, ""), TOKENS, VALUES),
            "unknown token": (template(*BODY, "    [ZED]"), TOKENS, VALUES),
            "token missing from the template": (
                good, TOKENS | {"[BASE_SHA]"}, {**VALUES, "[BASE_SHA]": "x"}),
            "value missing": (good, TOKENS, {"[BRIEF_FILE]": "b", "[CONTEXT]": "c"}),
            "extra value": (good, TOKENS, {**VALUES, "[ZED]": "z"}),
            "empty required value": (good, TOKENS, {**VALUES, "[BRIEF_FILE]": ""}),
            "optional token sharing its line": (
                template("    Read [BRIEF_FILE] then [REPORT_FILE].", "    Context: [CONTEXT]"),
                TOKENS, VALUES),
        }
        for name, (text, tokens, values) in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(BriefError):
                    sdd_brief.render(text, tokens, values)


class ShippedTemplateTest(unittest.TestCase):
    def test_the_token_sets_are_the_spec_table(self):
        plan = {"[PLAN_ROOT]", "[PLAN_ROOT_BYTES]", "[PLAN_TOTAL_BYTES]", "[PLAN_FILE_COUNT]",
                "[PLAN_LARGEST_MEMBER_BYTES]"}
        both = plan | {"[BRIEF_FILE]", "[REPORT_FILE]", "[GLOBAL_CONSTRAINTS]", "[STANDARDS]",
                       "[STACKS_DIR]"}
        self.assertEqual(sdd_brief.IMPLEMENTER_TOKENS, both | {
            "[TASK_NUMBER]", "[TASK_NAME]", "[CONTEXT]", "[TEST_SEAMS]", "[LIFECYCLE_WORKER]"})
        self.assertEqual(sdd_brief.REVIEWER_TOKENS, both | {
            "[BASE_SHA]", "[HEAD_SHA]", "[MANIFEST_ROOT]", "[ROOT_BYTES]", "[TOTAL_BYTES]",
            "[FILE_COUNT]", "[LARGEST_MEMBER_BYTES]"})
        self.assertEqual(sdd_brief.OPTIONAL_TOKENS, {"[CONTEXT]", "[LIFECYCLE_WORKER]"})

    def test_filling_each_token_with_itself_reproduces_the_prompt_body(self):
        for name, tokens in ((sdd_brief.IMPLEMENTER_TEMPLATE, sdd_brief.IMPLEMENTER_TOKENS),
                             (sdd_brief.REVIEWER_TEMPLATE, sdd_brief.REVIEWER_TOKENS)):
            with self.subTest(template=name):
                text = (SDD / name).read_text(encoding="utf-8")
                self.assertEqual(sdd_brief.render(text, tokens, {token: token for token in tokens}),
                                 independent_body(text))


if __name__ == "__main__":
    unittest.main()
