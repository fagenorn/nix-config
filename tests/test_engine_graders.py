"""Tests for the engine's graders (`agent_tools.delivery.engine_graders`): pure calls."""

from __future__ import annotations

import ast
import unittest
from collections.abc import Mapping
from pathlib import Path

from agent_tools.delivery import lane_rule
from agent_tools.delivery.engine_graders import GRADERS

TIER = "fast"

SHA = "a" * 40
NAMED = {"severity": "important", "file": "a.py", "failing_input": "", "summary": "s"}
UNNAMED = {"severity": "important", "file": "", "failing_input": "", "summary": "s"}
MINOR = {"severity": "minor", "file": "", "failing_input": "", "summary": "s"}
CRITERIA = [{"id": "AC1", "text": "t", "kind": "code", "result": "r"},
            {"id": "AC2", "text": "t", "kind": "human", "result": "r"}]
GRADED = [{"id": "AC1", "met": True, "evidence": "ran it"}]


def implemented(**over):
    reply = {"ineligible": False, "status": "done", "start_head": SHA, "commit": SHA,
             "acceptance": CRITERIA, "sensitive": False}
    reply.update(over)
    return {f"implement.{name}": value for name, value in reply.items()}


def tally(review, independent, *, verdict="pass", findings=(), acceptance=GRADED,
          escalate=None, ind_verdict="pass", ind_findings=()):
    results = {f"{review}.verdict": verdict, f"{review}.findings": list(findings),
               f"{review}.acceptance": acceptance,
               f"{independent}.verdict": ind_verdict, f"{independent}.findings": list(ind_findings),
               "implement.acceptance": CRITERIA}
    if escalate is not None:
        results[f"{review}.escalate"] = escalate
    return results


def lite(**kw):
    return tally("lite-review", "lite-independent", escalate=kw.pop("escalate", False), **kw)


def full(**kw):
    return tally("full-review", "full-independent", **kw)


def escalated(**kw):
    return tally("escalated", "lite-independent", **kw)


def fixed(**over):
    reply = {"status": "done", "start_head": SHA, "commit": SHA}
    reply.update(over)
    return {f"fix.{name}": value for name, value in reply.items()}


def settled(verdict, findings):
    return {"lite-rereview.verdict": verdict, "lite-rereview.findings": findings}


LANE_RESULTS = {"issue.body": "x\n\n## Acceptance criteria\n\n- [ ] a\n", "issue.marked": False,
                "issue.lane_paths": {"s": ["secrets/"]}}


class GraderTest(unittest.TestCase):
    GRADER_CASES = [
        ("toy-tally", {"review-a.verdict": "approve", "review-b.verdict": "approve"}, "accept"),
        ("toy-tally", {"review-a.verdict": "approve", "review-b.verdict": "revise"}, "revise"),
        ("review-capability", {"contract.capabilities": {
            "review.code": {"state": "blocked"}, "review.plan": {"state": "available"}}}, "blocked"),
        ("review-capability", {"contract.capabilities": {
            "review.code": {"state": "unsupported"}, "review.plan": {"state": "blocked"}}}, "blocked"),
        ("review-capability", {"contract.capabilities": {
            "review.code": {"state": "available"}, "review.plan": {"state": "unsupported"}}}, "clear"),
        ("review-capability", {}, "clear"),
        ("direct-implemented", implemented(ineligible=True, status="blocked"), "ineligible"),
        ("direct-implemented", implemented(status="blocked"), "task"),
        ("direct-implemented", implemented(acceptance=[]), "task"),
        ("direct-implemented", implemented(sensitive=True), "full"),
        ("direct-implemented", implemented(), "lite"),
        ("direct-lite-tally", lite(verdict=None), "no-review"),
        ("direct-lite-tally", lite(findings=[UNNAMED]), "unusable"),
        ("direct-lite-tally", lite(escalate=True), "escalate"),
        ("direct-lite-tally", lite(ind_verdict="unavailable"), "codex-unavailable"),
        ("direct-lite-tally", lite(findings=[NAMED]), "findings"),
        ("direct-lite-tally", lite(findings=[MINOR]), "clean"),
        ("direct-full-tally", full(verdict=None), "no-review"),
        ("direct-full-tally", full(findings=[UNNAMED]), "unusable"),
        ("direct-full-tally", full(ind_verdict="unavailable"), "codex-unavailable"),
        ("direct-full-tally", full(ind_verdict="findings", ind_findings=[NAMED]), "findings"),
        ("direct-full-tally", full(), "clean"),
        ("direct-escalated-tally", escalated(findings=[UNNAMED]), "unusable"),
        ("direct-escalated-tally", escalated(ind_verdict="unavailable"), "codex-unavailable"),
        ("direct-escalated-tally", escalated(findings=[NAMED]), "findings"),
        ("direct-escalated-tally", escalated(), "clean"),
        ("direct-fixed", fixed(), "done"),
        ("direct-fixed", fixed(commit=""), "not-done"),
        ("direct-fixed", fixed(status="blocked"), "not-done"),
        ("direct-settled", settled("findings", [MINOR]), "clean"),
        ("direct-settled", settled("findings", [NAMED]), "findings"),
        ("direct-settled", settled("findings", [UNNAMED]), "unusable"),
        ("lane-rule", LANE_RESULTS, "direct"),
        ("lane-rule", dict(LANE_RESULTS, **{"issue.marked": True}), "standard"),
    ]

    def test_the_lane_rule_grader_reads_the_issue_step(self):
        grader = GRADERS["lane-rule"]
        self.assertEqual(grader.outcomes, ("direct", "standard"))
        body = "x\n\n## Acceptance criteria\n\n- [ ] a\n"
        paths = {"s": ["secrets/"]}

        def grade(**members):
            return grader.grade({"issue.body": body, "issue.marked": False, "issue.lane_paths": paths,
                                 **members})

        self.assertEqual(grade(), "direct")
        self.assertEqual(grade(**{"issue.marked": None}), "standard")
        self.assertEqual(grade(**{"issue.marked": True}), "standard")
        self.assertEqual(grade(**{"issue.lane_paths": None}), "standard")

    def test_each_grader_case_grades_its_outcome(self):
        for name, results, expected in self.GRADER_CASES:
            with self.subTest(name=name, results=results):
                self.assertEqual(GRADERS[name].grade(results), expected)

    def test_a_rule_a_kind_or_a_decline_never_changes_a_grade(self):
        review_graders = ("direct-lite-tally", "direct-full-tally", "direct-escalated-tally", "direct-settled")
        exercised = set()
        for name, results, expected in self.GRADER_CASES:
            if name in review_graders:
                carrying = {key: [{**item, "rule": "B1", "kind": "security", "restates": "lite-review:1"}
                                  if isinstance(item, Mapping) else item for item in value]
                            if key.endswith(".findings") and isinstance(value, list) else value
                            for key, value in results.items()}
            elif name == "direct-fixed":
                carrying = {**results, "fix.declines": [{"finding": "lite-review:1", "reason": "r"}]}
            else:
                continue
            with self.subTest(name=name, results=results):
                self.assertEqual(GRADERS[name].grade(carrying), expected)
                exercised.add(name)
        self.assertEqual(exercised, {*review_graders, "direct-fixed"})

    def test_every_declared_grader_outcome_is_produced(self):
        for name in GRADERS:
            with self.subTest(name=name):
                self.assertEqual({e for n, _, e in self.GRADER_CASES if n == name},
                                 set(GRADERS[name].outcomes))

    def test_the_lite_tally_counts_an_ungraded_code_criterion_as_a_finding(self):
        results = {"lite-review.verdict": "pass", "lite-review.findings": [],
                   "lite-review.acceptance": [{"id": "AC1", "met": True, "evidence": " "}],
                   "lite-review.escalate": False,
                   "lite-independent.verdict": "none", "lite-independent.findings": [],
                   "implement.acceptance": CRITERIA}
        self.assertEqual(GRADERS["direct-lite-tally"].grade(results), "findings")

    def test_the_tallies_keep_the_programs_order(self):
        rows = [
            ("direct-lite-tally", lite(verdict=None, ind_verdict="unavailable"), "no-review"),
            ("direct-lite-tally", lite(findings=[UNNAMED], ind_verdict="unavailable"), "unusable"),
            ("direct-lite-tally", lite(findings=[UNNAMED], escalate=True), "unusable"),
            ("direct-lite-tally", lite(escalate=True, ind_verdict="unavailable"), "escalate"),
            ("direct-full-tally", full(findings=[NAMED], ind_verdict=None), "codex-unavailable"),
        ]
        for name, results, expected in rows:
            with self.subTest(name=name, expected=expected, results=results):
                self.assertEqual(GRADERS[name].grade(results), expected)

    def test_a_minor_independent_finding_does_not_block(self):
        results = full(ind_verdict="findings", ind_findings=[MINOR])
        self.assertEqual(GRADERS["direct-full-tally"].grade(results), "clean")


PATHS = {"guard": ["home/x/lifecycle_guard.py"], "release": ["rel/"], "secrets": ["secrets/"]}
DIRECT_REASON = "named files {f} of at most 3, acceptance criteria {n} of at most 3, no look marker, no lane path"
THREE = ["a/one.py", "a/two.py", "three.js"]
FOUR = ["a/1.py", "a/2.py", "a/3.py", "a/4.py"]


def issue_body(files, n):
    return ("Change " + ", ".join(f"`{f}`" for f in files) + ".\n\n## Acceptance criteria\n\n"
            + "".join(f"- [ ] [code] c{i}\n" for i in range(n)))


class LaneRuleTest(unittest.TestCase):
    def lane(self, body, *, marked=False, lane_paths=PATHS, given=None):
        chosen = lane_rule.choose(body, marked=marked, lane_paths=lane_paths, given=given)
        return chosen.lane, chosen.reason

    def test_the_rule_table(self):
        rows = [
            (THREE, 3, False, ("direct", DIRECT_REASON.format(f=3, n=3))),
            (FOUR, 3, False, ("standard", "named files 4, over the 3 of the direct lane")),
            (THREE, 4, False, ("standard", "acceptance criteria 4, over the 3 of the direct lane")),
            (THREE, 3, True, ("standard", "a look marker holds the merge for the owner's look")),
            (["lifecycle_guard.py"], 1,
             False, ("standard", "names lifecycle_guard.py, under the guard lane paths")),
            (["rel/x.py"], 1, False, ("standard", "names rel/x.py, under the release lane paths")),
            (["secrets/secrets.yaml"], 1,
             False, ("standard", "names secrets/secrets.yaml, under the secrets lane paths")),
        ]
        for files, n, marked, expected in rows:
            with self.subTest(files=files, n=n, marked=marked):
                self.assertEqual(self.lane(issue_body(files, n), marked=marked), expected)

    def test_no_criteria_or_no_lane_paths_is_standard(self):
        self.assertEqual(self.lane(issue_body(["a/one.py"], 0)), ("standard", "no acceptance criteria"))
        for paths in (None, {}, {"x": "secrets/"}, {"x": [1]}):
            with self.subTest(paths=paths):
                self.assertEqual(self.lane(issue_body(["a/one.py"], 1), lane_paths=paths),
                                 ("standard", "the repository declares no lane paths"))

    def test_a_given_lane_wins(self):
        self.assertEqual(self.lane(issue_body(FOUR, 3), given="direct"),
                         ("direct", "the caller gave the lane"))
        self.assertEqual(self.lane(issue_body(THREE, 3), given="standard"),
                         ("standard", "the caller gave the lane"))

    def test_named_paths_read_code_spans_and_slashed_bare_files(self):
        body = ("See `a/b.py` and a/b.py. Also https://x.org/r/blob/main/c.py, and/or `issue.text` "
                "`--repo` `lane`\n- [ ] [code] `d/`\n")
        self.assertEqual(lane_rule.named_paths(body), ("a/b.py", "issue.text", "d"))
        self.assertEqual(lane_rule.named_paths("Edit `./secrets/secrets.yaml` and ./a/b.py, not ../c/d.py or `./`"),
                         ("secrets/secrets.yaml", "a/b.py"))
        self.assertEqual(lane_rule.choose("Edit `./secrets/secrets.yaml`\n\n## Acceptance criteria\n- [ ] x\n",
                                          marked=False, lane_paths={"secrets": ["secrets/"]}).lane, "standard")

    def test_criteria_count_only_the_acceptance_section(self):
        body = ("## Demo\n- [ ] x\n## Acceptance criteria\n- [ ] a\n- [x] b\n* [ ] c\n"
                "## Blocked by\n- [ ] d\n")
        self.assertEqual(lane_rule.criteria(body), 3)

    def test_the_rule_module_imports_nothing_of_the_delivery_package(self):
        tree = ast.parse(Path(lane_rule.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "a relative import")
                self.assertFalse((node.module or "").startswith("agent_tools.delivery"), node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(alias.name.startswith("agent_tools.delivery"), alias.name)


if __name__ == "__main__":
    unittest.main()
