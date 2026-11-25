"""Contract tests for the findings of the shipped review and fix steps (issue 1535).

Every review reply schema carries a closed `kind` and an optional `rule` on each
finding, a re-review finding may name the one it `restates`, and each of the
five fix steps returns the `declines` its re-review renders. The schemas are
parsed by the engine, so the wire values are asserted; the prompts are asserted
only for the placeholders and the kind strings they must carry.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agent_tools.delivery.review_findings import KINDS

TIER = "fast"

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCEDURES = REPO_ROOT / "python/agent_tools/delivery/procedures"
FIX_STEPS = ("lite-fix", "escalated-fix", "full-fix", "merge-fix", "ci-fix")
FINDINGS_PLACEHOLDER = re.compile(r"\{\{\s*[a-z-]+\.findings\s*\}\}")
DECLINES = {"type": "array", "items": {"type": "object", "properties": {
    "finding": {"type": "string"}, "reason": {"type": "string"}}, "required": ["finding", "reason"],
    "additionalProperties": False}}


def agent_steps():
    """Yield `(step, schema, prompt_text)` for every agent step of every shipped procedure."""
    for path in sorted(PROCEDURES.glob("*.json")):
        if path.name.endswith(".reply.json"):
            continue
        for step in json.loads(path.read_text("utf-8"))["steps"]:
            if step["kind"] == "agent":
                schema = json.loads((PROCEDURES / step["reply"]).read_text("utf-8"))
                yield step, schema, (PROCEDURES / step["prompt"]).read_text("utf-8")


def review_steps():
    return [(step, schema, prompt) for step, schema, prompt in agent_steps()
            if "findings" in schema["properties"]]


class ShippedSchemaTest(unittest.TestCase):
    def test_every_review_reply_schema_requires_a_closed_kind_and_allows_a_rule(self):
        reviews = review_steps()

        self.assertGreaterEqual({step["id"] for step, _, _ in reviews},
                                {"lite-review", "full-review", "escalated", "lite-rereview",
                                 "escalated-rereview", "full-rereview", "merge-review", "merge-rereview",
                                 "ci-review"})
        for step, schema, _ in reviews:
            with self.subTest(step=step["id"]):
                items = schema["properties"]["findings"]["items"]
                self.assertEqual(items["properties"]["kind"], {"enum": list(KINDS)})
                self.assertIn("kind", items["required"])
                self.assertEqual(items["properties"]["rule"], {"type": "string"})
                self.assertNotIn("rule", items["required"])

    def test_every_fix_step_requires_declines(self):
        steps = {}
        for step, schema, prompt in agent_steps():
            steps.setdefault(step["id"], []).append((step, schema, prompt))
        for name in FIX_STEPS:
            with self.subTest(step=name):
                self.assertEqual(len(steps[name]), 1)
                schema = steps[name][0][1]
                self.assertIn("declines", schema["required"])
                self.assertEqual(schema["properties"]["declines"], DECLINES)
        renders_findings = {step["id"] for step, schema, prompt in agent_steps()
                            if FINDINGS_PLACEHOLDER.search(prompt) and "findings" not in schema["properties"]}
        self.assertLessEqual(renders_findings, set(FIX_STEPS))

    def test_a_re_review_finding_may_name_the_finding_it_restates(self):
        schema = json.loads((PROCEDURES / "direct-rereview.reply.json").read_text("utf-8"))

        items = schema["properties"]["findings"]["items"]

        self.assertEqual(items["properties"]["restates"], {"type": "string"})
        self.assertNotIn("restates", items["required"])


class ShippedPromptTest(unittest.TestCase):
    def test_every_review_prompt_lists_the_closed_kinds(self):
        for step, _, prompt in review_steps():
            with self.subTest(step=step["id"]):
                for kind in KINDS:
                    self.assertIn(kind, prompt)
                self.assertIn("rule", prompt)

    def test_every_re_review_prompt_renders_its_fixs_declines(self):
        reviews = {step["id"]: (step, prompt) for step, _, prompt in review_steps()}
        for review, fix in (("lite-rereview", "lite-fix"), ("escalated-rereview", "escalated-fix"),
                            ("full-rereview", "full-fix"), ("merge-rereview", "merge-fix")):
            with self.subTest(step=review):
                step, prompt = reviews[review]
                placeholder = "{{" + fix + ".declines}}"
                lines = [line for line in prompt.splitlines() if placeholder in line]
                self.assertEqual(len(lines), 1)
                self.assertEqual(len(re.findall(r"\{\{", lines[0])), 1)
                self.assertIn(f"{fix}.declines", step["in"])


if __name__ == "__main__":
    unittest.main()
