"""Contract tests for the findings of the shipped review and fix steps.

Every review reply schema carries a closed `kind` and an optional `rule` on each
finding, a re-review finding may name the one it `restates`, and each of the
five fix steps returns the `declines` its re-review renders. The schemas are
parsed by the engine, so the wire values are asserted; the prompts are asserted
only for the placeholders and the kind strings they must carry.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path

from agent_tools.delivery import engine_graders, review_findings
from agent_tools.delivery.engine_graders import GRADERS
from agent_tools.delivery.engine_reply import cites_rules, without_unknown_rules
from agent_tools.delivery.review_findings import (
    DISPOSITIONS, KINDS, LANDING_REREVIEWS, Round, dispositions, usable)

TIER = "fast"

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCEDURES = REPO_ROOT / "python/agent_tools/delivery/procedures"
FIX_STEPS = ("lite-fix", "escalated-fix", "full-fix", "merge-fix", "ci-fix", "plan-revise")
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
                            ("full-rereview", "full-fix"), ("merge-rereview", "merge-fix"),
                            ("plan-rereview", "plan-revise")):
            with self.subTest(step=review):
                step, prompt = reviews[review]
                placeholder = "{{" + fix + ".declines}}"
                lines = [line for line in prompt.splitlines() if placeholder in line]
                self.assertEqual(len(lines), 1)
                self.assertEqual(len(re.findall(r"\{\{", lines[0])), 1)
                self.assertIn(f"{fix}.declines", step["in"])


IMPORTANT = {"severity": "important", "file": "a.py:1", "failing_input": "f('')", "summary": "s", "kind": "other"}
MINOR = dict(IMPORTANT, severity="minor")
FIX = {"status": "done", "start_head": "a" * 40, "commit": "b" * 40, "notes": "n", "tests": [], "declines": []}
DECLINED = dict(FIX, declines=[{"finding": "lite-review:1", "reason": "r"}])
PASS = {"verdict": "pass", "findings": []}
REVIEWED = ("lite-review", {"verdict": "findings", "findings": [IMPORTANT]})
RESTATING = {"verdict": "findings", "findings": [dict(IMPORTANT, restates="lite-review:1")]}
NEW = {"verdict": "findings", "findings": [IMPORTANT]}
STALE = {"verdict": "findings", "findings": [dict(IMPORTANT, restates="lite-review:99")]}
UNNAMED = {"verdict": "findings", "findings": [dict(IMPORTANT, file="", failing_input=" ")]}
ACCEPTANCE = [{"id": "AC1", "text": "t", "kind": "code", "result": "r"},
              {"id": "AC5", "text": "t", "kind": "evidence", "result": "r"}]
AMBIGUOUS = [*ACCEPTANCE, {"id": "AC5", "text": "t", "kind": "code", "result": "r"}]
BLANK_EVIDENCE = dict(IMPORTANT, file="", failing_input="", summary="AC5 has no evidence")
MINOR_RESTATING = {"verdict": "findings", "findings": [dict(MINOR, restates="lite-review:1")]}
EVIDENCE_RESTATING = {"verdict": "findings", "findings": [
    dict(IMPORTANT, summary="AC5 has no evidence", restates="lite-review:1")]}
MERGE = ("merge-review", {"verdict": "findings", "findings": [IMPORTANT]})
MERGED = Round((MERGE,), FIX, ("merge-rereview", PASS))
CASES = [
    ("fixed", [Round((REVIEWED,), FIX, ("lite-rereview", PASS))], [(1, "lite-review:1", "fixed")]),
    ("declined", [Round((REVIEWED,), DECLINED, ("lite-rereview", PASS))], [(1, "lite-review:1", "declined")]),
    ("filed", [Round((("lite-review", {"verdict": "pass", "findings": [MINOR]}),),
                     filed=frozenset({"lite-review:1"}))], [(1, "lite-review:1", "filed")]),
    ("dropped", [Round((("lite-review", {"verdict": "pass", "findings": [MINOR]}),))],
     [(1, "lite-review:1", "dropped")]),
    ("open", [Round((REVIEWED,))], [(1, "lite-review:1", "open")]),
    ("a declined finding the re-review restates stays open",
     [Round((REVIEWED,), DECLINED, ("lite-rereview", RESTATING))], [(1, "lite-review:1", "open")]),
    ("a new re-review finding is open", [Round((REVIEWED,), FIX, ("lite-rereview", NEW))],
     [(1, "lite-review:1", "fixed"), (1, "lite-rereview:1", "open")]),
    ("a restates that names nothing keeps the item", [Round((REVIEWED,), FIX, ("lite-rereview", STALE))],
     [(1, "lite-review:1", "fixed"), (1, "lite-rereview:1", "open")]),
    ("an unusable re-review closes nothing", [Round((REVIEWED,), FIX, ("lite-rereview", {}))],
     [(1, "lite-review:1", "open")]),
    ("a re-review with an unnamed blocking finding closes nothing",
     [Round((REVIEWED,), DECLINED, ("lite-rereview", UNNAMED))], [(1, "lite-review:1", "open")]),
    ("filed wins over fixed", [Round((REVIEWED,), FIX, ("lite-rereview", PASS), frozenset({"lite-review:1"}))],
     [(1, "lite-review:1", "filed")]),
    ("a minor finding is dropped even when declined",
     [Round((("lite-review", {"verdict": "findings", "findings": [MINOR]}),), DECLINED, ("lite-rereview", PASS))],
     [(1, "lite-review:1", "dropped")]),
    ("two reviews are named by their steps",
     [Round((("lite-review", {"verdict": "findings", "findings": [MINOR, IMPORTANT]}),
             ("lite-independent", {"verdict": "findings", "findings": [IMPORTANT]})),
            dict(FIX, declines=[{"finding": "lite-independent:1", "reason": "r"}]), ("lite-rereview", PASS))],
     [(1, "lite-review:1", "dropped"), (1, "lite-review:2", "fixed"), (1, "lite-independent:1", "declined")]),
    ("a name filed in one round is not filed in the next",
     [Round(MERGED.reviews, MERGED.fix, MERGED.rereview, frozenset({"merge-review:1"})), MERGED],
     [(1, "merge-review:1", "filed"), (2, "merge-review:1", "fixed")]),
    ("a merge re-review stopping on an unnamed blocker still names its findings",
     [Round((MERGE,), FIX, ("merge-rereview", {"verdict": "findings", "findings": [UNNAMED["findings"][0], NEW["findings"][0]]}))],
     [(1, "merge-review:1", "fixed"), (1, "merge-rereview:1", "open"), (1, "merge-rereview:2", "open")]),
    ("a minor finding restated as important keeps its blocking restatement",
     [Round((("lite-review", {"verdict": "findings", "findings": [MINOR]}),), FIX,
            ("lite-rereview", RESTATING))],
     [(1, "lite-review:1", "dropped"), (1, "lite-rereview:1", "open")]),
    ("a member with no reply contributes nothing", [Round((("lite-review", None),))], []),
    ("a re-review finding naming only an evidence criterion is dropped",
     [Round((REVIEWED,), FIX, ("lite-rereview", {"verdict": "findings", "findings": [BLANK_EVIDENCE]}),
            acceptance=ACCEPTANCE)],
     [(1, "lite-review:1", "fixed"), (1, "lite-rereview:1", "dropped")]),
    ("a review finding naming only an evidence criterion is dropped",
     [Round((("lite-review", {"verdict": "findings", "findings": [dict(IMPORTANT, summary="AC5 has no evidence")]}),),
            FIX, ("lite-rereview", PASS), acceptance=ACCEPTANCE)],
     [(1, "lite-review:1", "dropped")]),
    ("a code-criterion restatement of a finding dropped by kind keeps its own open disposition",
     [Round((("lite-review", {"verdict": "findings", "findings": [dict(IMPORTANT, summary="AC5 has no evidence")]}),),
            FIX, ("lite-rereview", {"verdict": "findings", "findings": [
                dict(IMPORTANT, summary="still unresolved: AC1 test fails on empty input",
                     restates="lite-review:1")]}),
            acceptance=ACCEPTANCE)],
     [(1, "lite-review:1", "dropped"), (1, "lite-rereview:1", "open")]),
    ("a minor restatement does not hold the blocker it restates open",
     [Round((REVIEWED,), FIX, ("lite-rereview", MINOR_RESTATING))],
     [(1, "lite-review:1", "fixed"), (1, "lite-rereview:1", "dropped")]),
    ("a landing re-review that stops on a minor restatement keeps the blocker open",
     [Round((MERGE,), FIX, ("merge-rereview", {"verdict": "findings", "findings": [
         dict(MINOR, restates="merge-review:1")]}))],
     [(1, "merge-review:1", "open")]),
    ("an evidence-worded restatement of a blocker is kept and holds the blocker open",
     [Round((REVIEWED,), FIX, ("lite-rereview", EVIDENCE_RESTATING), acceptance=ACCEPTANCE)],
     [(1, "lite-review:1", "open")]),
]


class DispositionTest(unittest.TestCase):
    def test_each_disposition_comes_from_the_stored_results_built_for_it(self):
        for label, rounds, expected in CASES:
            with self.subTest(label):
                self.assertEqual([(d.round, d.name, d.disposition) for d in dispositions(rounds)], expected)

    def test_every_declared_disposition_is_produced(self):
        self.assertEqual({d for _, _, expected in CASES for _, _, d in expected}, set(DISPOSITIONS))

    def test_usable_is_the_re_review_routes_own_rule(self):
        replies = [PASS, NEW, {"verdict": "findings", "findings": [MINOR]},
                   {"verdict": "findings", "findings": [dict(IMPORTANT, file="")]},
                   {"verdict": "findings", "findings": [dict(IMPORTANT, file="", failing_input="")]},
                   {"verdict": "findings", "findings": [dict(MINOR, file="", failing_input="")]},
                   {"verdict": "findings", "findings": [BLANK_EVIDENCE]},
                   {"verdict": "findings", "findings": [dict(BLANK_EVIDENCE, summary="AC1 has no evidence")]},
                   {"verdict": "findings", "findings": [dict(BLANK_EVIDENCE, summary="AC50 has no evidence")]},
                   {"verdict": "findings", "findings": [dict(BLANK_EVIDENCE, restates="lite-review:1")]},
                   {"verdict": "findings", "findings": [dict(BLANK_EVIDENCE, file="tests/AC5/p.py", summary="s")]}]
        for acceptance in (None, ACCEPTANCE, AMBIGUOUS):
            for reply in replies:
                with self.subTest(reply=reply, acceptance=acceptance):
                    members = {"implement.acceptance": acceptance} if acceptance is not None else {}
                    graded = GRADERS["direct-settled"].grade({"lite-rereview.verdict": reply["verdict"],
                                                              "lite-rereview.findings": reply["findings"],
                                                              **members})
                    self.assertIs(usable(reply, acceptance), graded != "unusable")
        self.assertTrue(usable({"verdict": "findings", "findings": [BLANK_EVIDENCE]}, ACCEPTANCE))
        self.assertFalse(usable({"verdict": "findings", "findings": [BLANK_EVIDENCE]}))
        self.assertFalse(usable({"verdict": "findings", "findings": [BLANK_EVIDENCE]}, AMBIGUOUS))
        for reply in ({}, None, {"verdict": "unavailable", "findings": []}, {"verdict": "pass", "findings": "x"}):
            with self.subTest(reply=reply):
                self.assertFalse(usable(reply))

    def test_the_merge_re_review_is_judged_by_the_landing_route_not_the_direct_one(self):
        landing = json.loads((PROCEDURES / "land-attempt.json").read_text("utf-8"))
        steps = {step["id"]: step for step in landing["steps"]}

        for name in LANDING_REREVIEWS:
            with self.subTest(step=name):
                self.assertEqual(steps[name]["outcome_from"], "verdict")
                self.assertNotIn("unusable", steps[name]["on"])
                self.assertEqual(steps[name]["on"]["findings"], "sync-review")
                self.assertIn("sync-review", landing["stops"])
        direct = json.loads((PROCEDURES / "direct.json").read_text("utf-8"))
        self.assertTrue(all(step["id"] not in LANDING_REREVIEWS for step in direct["steps"]))

    def test_the_copy_of_the_finding_name_rule_is_the_graders(self):
        for text in ("lite-review:1", "a:1", "A:1", "x:0", "x:", "AC5", "1:1", "-:1", "a-1:9", "see full-review:2 now",
                     "", "AC5:", ":3", "full-review:10", "é:1", "a:١"):
            with self.subTest(text=text):
                wanted = re.search(r"[a-z][a-z0-9-]*:[1-9][0-9]*", text) is not None
                self.assertIs(review_findings._restates_a_finding(text), wanted)
                self.assertIs(engine_graders._restates_a_finding(text), wanted)

    def test_the_disposition_module_reads_nothing(self):
        tree = ast.parse((PROCEDURES.parents[0] / "review_findings.py").read_text("utf-8"))
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}

        self.assertLessEqual(imported, {"__future__", "dataclasses", "typing", "collections.abc"})


class BlankingTest(unittest.TestCase):
    def test_a_made_up_rule_is_blanked_and_a_known_one_kept(self):
        reply = {"verdict": "findings", "findings": [
            {"kind": "other", "rule": "ZZ999"}, {"kind": "other", "rule": "B1"}, {"kind": "other"},
            {"kind": "other", "rule": "standard" + ":B1"}]}

        blanked = without_unknown_rules(reply, {"B1"})

        self.assertEqual([f.get("rule", "<absent>") for f in blanked["findings"]], ["", "B1", "<absent>", ""])
        self.assertEqual(blanked["verdict"], "findings")
        self.assertEqual(reply["findings"][0]["rule"], "ZZ999")

    def test_only_a_finding_with_a_non_empty_rule_cites_one(self):
        for reply in ({}, {"findings": []}, {"findings": "x"}, {"findings": [{"rule": ""}]},
                      {"findings": [{"kind": "other"}]}, {"findings": ["x"]}, None):
            with self.subTest(reply=reply):
                self.assertFalse(cites_rules(reply))
        self.assertTrue(cites_rules({"findings": [{"rule": "B1"}]}))

    def test_odd_shapes_pass_through_unchanged(self):
        self.assertEqual(without_unknown_rules({"findings": "x"}, set()), {"findings": "x"})
        self.assertEqual(without_unknown_rules({"findings": ["x", {"rule": 3}]}, set()),
                         {"findings": ["x", {"rule": 3}]})
        self.assertEqual(without_unknown_rules({"status": "done"}, set()), {"status": "done"})


if __name__ == "__main__":
    unittest.main()
