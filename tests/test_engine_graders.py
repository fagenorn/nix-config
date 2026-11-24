"""Tests for the engine's graders (`agent_tools.delivery.engine_graders`): pure calls."""

from __future__ import annotations

import unittest

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
    ]

    def test_each_grader_case_grades_its_outcome(self):
        for name, results, expected in self.GRADER_CASES:
            with self.subTest(name=name, results=results):
                self.assertEqual(GRADERS[name].grade(results), expected)

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


if __name__ == "__main__":
    unittest.main()
