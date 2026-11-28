"""Tests for the engine's graders (`agent_tools.delivery.engine_graders`): pure calls."""

from __future__ import annotations

import ast
import unittest
from collections.abc import Mapping
from pathlib import Path

from agent_tools.delivery import acceptance_criteria, lane_rule
from agent_tools.delivery.engine_graders import GRADERS, NON_CODE_KINDS, dropped

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


def verify_fixed(**over):
    return {**fixed(), **{f"fix.{name}": value for name, value in over.items()}}


FAILING = {"id": "test", "status": "fail", "named": ["fixture/a.json", "fixture/b.json"]}


def narrowing(**over):
    results = {"fix-review.findings": [], "round.clean": True,
               "round.results": [{"id": "lint", "status": "pass"}, dict(FAILING)],
               "ws-check.whitespace_only": True, "ws-check.changed_paths": ["fixture/a.json"],
               "fix-review.whitespace_insignificant": True, "fix-review.whitespace_evidence": "only indentation"}
    results.update(over)
    return results


def again(results):
    """`results` with the fix review's members under the second ask's step id."""
    return {key.replace("fix-review.", "fix-review-again."): value for key, value in results.items()}


def settled(verdict, findings):
    return {"lite-rereview.verdict": verdict, "lite-rereview.findings": findings}


LANE_RESULTS = {"issue.body": "x\n\n## Acceptance criteria\n\n- [ ] a\n", "issue.marked": False,
                "issue.lane_paths": {"s": ["secrets/"]}}

OUTLINE_ISSUE = ("# t\n\nbody\n\n## Acceptance criteria\n\n- [ ] [code] one\n- [ ] [code] two\n\n"
                 "## Comment 1\n\n- [ ] [code] not a criterion\n")
COLON_ISSUE = "# t\n\nbody\n\n## Acceptance criteria:\n\n- [ ] [code] one\n"
TITLED_ISSUE = "# Acceptance criteria\n\nbody\n\n## Acceptance criteria\n\n- [ ] [code] one\n"
S1 = {"n": 1, "change": "c", "files": ["a.py"], "test": "t", "assertion": "a"}
S2 = dict(S1, n=2, change="d")


def mapping(slices, criteria, issue=OUTLINE_ISSUE, step="outline"):
    return {f"{step}.slices": slices, f"{step}.criteria": criteria, "plan-preflight.issue_text": issue}


def on(ids, slice_of=lambda i: 1):
    return [{"id": cid, "kind": "code", "slice": slice_of(i)} for i, cid in enumerate(ids, 1)]


class GraderTest(unittest.TestCase):
    GRADER_CASES = [
        ("outline-mapped", mapping([S1, S2], on(["AC1", "AC2"], lambda i: i)), "mapped"),
        ("outline-mapped", mapping([S1], on(["AC1", "AC2"], lambda i: i)), "unmapped"),
        ("outline-mapped", mapping([S1], [], issue=COLON_ISSUE), "unmapped"),
        ("outline-mapped", mapping([S1], on(["AC1"]), issue=COLON_ISSUE), "mapped"),
        ("outline-mapped", mapping([S1], [], issue=TITLED_ISSUE), "unmapped"),
        ("outline-mapped", mapping([S1], on(["AC1"]), issue=TITLED_ISSUE), "mapped"),
        ("outline-mapped", mapping([S1], [], issue="# t\n\nno criteria here\n"), "mapped"),
        ("outline-proven", {"outline.slices": [S1]}, "proven"),
        ("outline-proven", {"outline.slices": []}, "unproven"),
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
        ("outline-implemented", implemented(ineligible=True, status="blocked"), "ineligible"),
        ("outline-implemented", implemented(status="blocked"), "task"),
        ("outline-implemented", implemented(commit=""), "task"),
        ("outline-implemented", implemented(acceptance="none"), "task"),
        ("outline-implemented", implemented(acceptance=[]), "lite"),
        ("outline-implemented", implemented(acceptance=[], sensitive=True), "full"),
        ("outline-implemented", implemented(), "lite"),
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
        ("verify-fixed", verify_fixed(status="blocked", unrelated={"test": "t", "evidence": "e"}), "unrelated"),
        ("verify-fixed", verify_fixed(status="blocked", unrelated={"test": "t", "evidence": " "}), "not-done"),
        ("verify-fixed", verify_fixed(), "done"),
        ("verify-narrowing", narrowing(**{"fix-review.findings": [NAMED]}), "findings"),
        ("verify-narrowing", narrowing(**{"fix-review.findings": [UNNAMED]}), "unusable"),
        ("verify-narrowing", narrowing(**{"fix-review.findings": [UNNAMED, MINOR]}), "unusable"),
        ("verify-narrowing", narrowing(), "rerun-failed-only"),
        ("verify-narrowing", again(narrowing(**{"fix-review.findings": [UNNAMED]})), "unusable"),
        ("verify-narrowing", again(narrowing(**{"fix-review.findings": [NAMED]})), "findings"),
        ("verify-narrowing", again(narrowing()), "rerun-failed-only"),
        ("verify-narrowing", again(narrowing(**{"fix-review.whitespace_insignificant": False})), "rerun-all"),
        ("verify-narrowing", narrowing(**{"round.clean": False}), "rerun-all"),
        ("direct-settled", settled("findings", [MINOR]), "clean"),
        ("direct-settled", settled("findings", [NAMED]), "findings"),
        ("direct-settled", settled("findings", [UNNAMED]), "unusable"),
        ("plan-settled", settled("findings", []), "unusable"),
        ("plan-settled", settled("findings", [NAMED]), "findings"),
        ("plan-settled", settled("findings", [UNNAMED]), "unusable"),
        ("plan-settled", settled("pass", []), "clean"),
        ("plan-settled", settled("findings", [MINOR]), "clean"),
        ("lane-rule", LANE_RESULTS, "direct"),
        ("lane-rule", dict(LANE_RESULTS, **{"issue.marked": True}), "standard"),
    ]

    def test_the_narrowing_grader_reruns_all_when_any_one_condition_fails(self):
        grader = GRADERS["verify-narrowing"]
        no_pass = [dict(FAILING)]
        no_slot = [{"id": "lint", "status": "pass", "no_slot": True}, dict(FAILING)]
        unnamed = {"id": "test", "status": "fail"}
        broken = {
            "round.clean false": {"round.clean": False},
            "no pass result": {"round.results": no_pass},
            "a no_slot result": {"round.results": no_slot},
            "named empty": {"round.results": [{"id": "lint", "status": "pass"}, {**FAILING, "named": []}]},
            "named absent": {"round.results": [{"id": "lint", "status": "pass"}, unnamed]},
            "whitespace_only false": {"ws-check.whitespace_only": False},
            "whitespace_only 1": {"ws-check.whitespace_only": 1},
            "changed_paths empty": {"ws-check.changed_paths": []},
            "a path no failure named": {"ws-check.changed_paths": ["fixture/a.json", "fixture/c.json"]},
            "a path that differs by a leading space": {"ws-check.changed_paths": [" fixture/a.json"]},
            "not attested": {"fix-review.whitespace_insignificant": False},
            "blank evidence": {"fix-review.whitespace_evidence": "  "},
        }
        self.assertEqual(grader.grade(narrowing()), "rerun-failed-only")
        for label, over in broken.items():
            with self.subTest(label):
                self.assertEqual(grader.grade(narrowing(**over)), "rerun-all")

    def test_a_fix_review_with_a_blocking_finding_is_findings_whatever_its_verdict(self):
        grade = GRADERS["verify-narrowing"].grade
        important = {"severity": "important", "file": "a.py", "failing_input": "x", "summary": "s"}
        self.assertEqual(grade(narrowing(**{"fix-review.findings": [important]})), "findings")
        self.assertEqual(grade(narrowing(**{"fix-review.findings": [MINOR]})), "rerun-failed-only")
        self.assertEqual(grade(narrowing(**{"fix-review.findings": None})), "findings")

    def test_an_unrelated_reply_with_a_blank_test_is_not_unrelated(self):
        results = verify_fixed(status="blocked", unrelated={"test": "", "evidence": "e"})
        self.assertEqual(GRADERS["verify-fixed"].grade(results), "not-done")

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

    def test_a_heading_with_a_trailing_colon_opens_the_acceptance_criteria_section(self):
        for heading in ("## Acceptance criteria:", "### acceptance criteria :", "## Acceptance criteria: ##"):
            with self.subTest(heading=heading):
                body = f"## Problem\n\nx\n\n{heading}\n\n- [ ] [human] One\n"
                self.assertEqual([c.text for c in acceptance_criteria.acceptance_criteria(body)], ["One"])
        self.assertEqual(acceptance_criteria.acceptance_criteria("## Acceptance criteria: none\n\n- [ ] One\n"), [])

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


ACCEPTANCE = [{"id": "AC1", "text": "t", "kind": "code", "result": "r"},
              {"id": "AC5", "text": "t", "kind": "evidence", "result": "r"}]
EVIDENCE = {"severity": "important", "file": "python/x.py:340", "failing_input": "gh pr list",
            "summary": "AC5 is evidence-kind and still has no evidence", "kind": "other", "restates": "AC5"}
NAMED_KIND = dict(NAMED, kind="other")


def rereview(findings, acceptance=ACCEPTANCE, verdict="findings"):
    results = {"full-rereview.verdict": verdict, "full-rereview.findings": findings}
    if acceptance is not None:
        results["implement.acceptance"] = acceptance
    return results


def graded(results):
    return GRADERS["direct-settled"].grade(results), GRADERS["direct-settled"].drops(results)


class DropTest(unittest.TestCase):
    def test_a_re_review_finding_naming_only_an_evidence_criterion_settles_clean_and_is_listed(self):
        results = rereview([EVIDENCE])

        grade = GRADERS["direct-settled"].grade(results)
        drops = GRADERS["direct-settled"].drops(results)

        self.assertEqual(grade, "clean")
        self.assertEqual(drops, ({"finding": "full-rereview:1", "criteria": ["AC5"]},))
        self.assertEqual(results["full-rereview.findings"], [EVIDENCE])

    def test_a_finding_that_names_a_code_criterion_an_unknown_kind_or_nothing_is_kept(self):
        both = dict(EVIDENCE, summary="AC5 and AC1 lack evidence")
        other = [{"id": "AC5", "text": "t", "kind": "other", "result": "r"}]
        no_kind = [{"id": "AC5", "text": "t", "result": "r"}]
        rows = [("code named", rereview([both]), "findings"),
                ("unknown kind", rereview([EVIDENCE], other), "findings"),
                ("no kind", rereview([EVIDENCE], no_kind), "findings"),
                ("no criterion", rereview([NAMED]), "findings")]
        for label, results, expected in rows:
            with self.subTest(label):
                self.assertEqual(graded(results), (expected, ()))

    def test_an_id_matches_only_as_a_whole_token(self):
        acceptance = [{"id": "AC2", "text": "t", "kind": "evidence", "result": "r"}]
        kept = dict(EVIDENCE, summary="AC20 is unmet", restates="")
        self.assertEqual(graded(rereview([kept], acceptance)), ("findings", ()))
        for summary in ("AC2.", "(AC2) is unmet", "AC2, then more","AC20 and AC2 differ"):
            with self.subTest(summary=summary):
                found = dict(EVIDENCE, summary=summary, restates="")
                self.assertEqual(graded(rereview([found], acceptance)),
                                 ("clean", ({"finding": "full-rereview:1", "criteria": ["AC2"]},)))
        for summary in ("AC2x", "_AC2", "1AC2"):
            with self.subTest(summary=summary):
                found = dict(EVIDENCE, summary=summary, restates="")
                self.assertEqual(graded(rereview([found], acceptance)), ("findings", ()))

    def test_the_restates_and_the_summary_name_a_criterion(self):
        quiet = dict(EVIDENCE, restates="", summary="s", failing_input="x", file="a.py")
        for member in ("restates", "summary"):
            with self.subTest(member=member):
                finding = dict(quiet, **{member: "see AC5"})
                self.assertEqual(graded(rereview([finding])),
                                 ("clean", ({"finding": "full-rereview:1", "criteria": ["AC5"]},)))

    def test_a_file_or_a_failing_input_never_names_a_criterion(self):
        quiet = dict(EVIDENCE, restates="", summary="s", failing_input="x", file="a.py")
        for member, text in (("file", "tests/AC5/parser.py:8"), ("failing_input", "parse('AC5')")):
            with self.subTest(member=member):
                finding = dict(quiet, **{member: text})
                self.assertEqual(graded(rereview([finding])), ("findings", ()))

    def test_a_finding_restating_an_earlier_finding_is_kept_whatever_criterion_it_names(self):
        for restates in ("full-review:1", "full-independent:2", "escalated:3"):
            for extra in ({}, {"file": "tests/AC5/parser.py:8"}, {"kind": "security", "failing_input": "AC5"}):
                with self.subTest(restates=restates, extra=extra):
                    finding = dict(EVIDENCE, restates=restates, summary="still unresolved: AC5 crashes", **extra)
                    self.assertEqual(graded(rereview([finding])), ("findings", ()))
        for tally, build in (("direct-full-tally", full), ("direct-lite-tally", lite)):
            with self.subTest(tally=tally):
                finding = dict(EVIDENCE, restates="full-review:1", summary="AC5 still crashes")
                results = {**build(acceptance=GRADED, verdict="findings", findings=[finding]),
                           "implement.acceptance": ACCEPTANCE}
                self.assertEqual(GRADERS[tally].grade(results), "findings")
                self.assertEqual(GRADERS[tally].drops(results), ())

    def test_an_id_declared_with_two_kinds_is_ambiguous_and_its_findings_are_kept(self):
        code = {"id": "AC5", "text": "t", "kind": "code", "result": "r"}
        evidence = {"id": "AC5", "text": "t", "kind": "evidence", "result": "r"}
        for label, acceptance in (("code first", [code, evidence]), ("evidence first", [evidence, code]),
                                  ("evidence code evidence", [evidence, code, evidence])):
            with self.subTest(label):
                self.assertEqual(graded(rereview([EVIDENCE], acceptance)), ("findings", ()))
        same = graded(rereview([EVIDENCE], [evidence, dict(evidence, text="again")]))
        self.assertEqual(same, ("clean", ({"finding": "full-rereview:1", "criteria": ["AC5"]},)))

    def test_an_id_outside_the_acceptance_names_nothing_and_no_acceptance_drops_nothing(self):
        unknown = dict(EVIDENCE, summary="AC9 unmet", restates="AC9")
        self.assertEqual(graded(rereview([unknown])), ("findings", ()))
        self.assertEqual(graded(rereview([EVIDENCE], None)), ("findings", ()))
        self.assertEqual(graded(rereview([EVIDENCE], "AC5")), ("findings", ()))
        plan = {"plan-review.verdict": "findings", "plan-review.findings": [EVIDENCE]}
        self.assertEqual(GRADERS["plan-settled"].drops(plan), ())
        self.assertEqual(GRADERS["plan-settled"].grade(plan), "findings")

    def test_a_minor_finding_naming_only_an_evidence_criterion_is_listed_too(self):
        minor = dict(EVIDENCE, severity="minor")
        self.assertEqual(graded(rereview([minor])),
                         ("clean", ({"finding": "full-rereview:1", "criteria": ["AC5"]},)))

    def test_a_dropped_finding_is_never_unusable(self):
        blank = dict(EVIDENCE, file="", failing_input="", restates="")
        self.assertEqual(graded(rereview([blank]))[0], "clean")
        self.assertEqual(graded(rereview([blank], None))[0], "unusable")

    def test_a_drop_names_its_place_in_the_unfiltered_list(self):
        results = rereview([NAMED_KIND, EVIDENCE])
        self.assertEqual(graded(results),
                         ("findings", ({"finding": "full-rereview:2", "criteria": ["AC5"]},)))

    def test_the_criteria_of_a_drop_follow_the_acceptance_order(self):
        acceptance = [{"id": "AC7", "text": "t", "kind": "human", "result": "r"},
                      {"id": "AC5", "text": "t", "kind": "evidence", "result": "r"}]
        finding = dict(EVIDENCE, summary="AC5 and AC7", restates="")
        self.assertEqual(graded(rereview([finding], acceptance))[1],
                         ({"finding": "full-rereview:1", "criteria": ["AC7", "AC5"]},))

    def test_the_tallies_filter_both_the_review_and_the_independent_review(self):
        for name, build, review, independent in (
                ("direct-full-tally", full, "full-review", "full-independent"),
                ("direct-lite-tally", lite, "lite-review", "lite-independent"),
                ("direct-escalated-tally", escalated, "escalated", "lite-independent")):
            for label, kw, step in (("review", dict(verdict="findings", findings=[EVIDENCE]), review),
                                    ("independent", dict(ind_verdict="findings", ind_findings=[EVIDENCE]),
                                     independent)):
                with self.subTest(name=name, label=label):
                    results = {**build(acceptance=GRADED, **kw), "implement.acceptance": ACCEPTANCE}
                    self.assertEqual(GRADERS[name].grade(results), "clean")
                    self.assertEqual(GRADERS[name].drops(results),
                                     ({"finding": f"{step}:1", "criteria": ["AC5"]},))

    def test_a_finding_of_a_kind_other_than_other_is_a_code_defect_whatever_criterion_it_names(self):
        for kind in ("security", "edge-or-failure-path", "weak-test", "missing-test", "contract-mismatch",
                     "stale-docs", "concurrency", "plan-step-not-executable"):
            finding = {"severity": "critical", "kind": kind, "file": "fixture/farewell.py:2",
                       "failing_input": "farewell('$(rm -rf ~)')",
                       "summary": "new defect: farewell shells out; AC5's evidence run does not exercise it"}
            with self.subTest(kind=kind):
                self.assertEqual(graded(rereview([finding])), ("findings", ()))
                results = {**full(acceptance=GRADED, verdict="findings", findings=[finding]),
                           "implement.acceptance": ACCEPTANCE}
                self.assertEqual(GRADERS["direct-full-tally"].grade(results), "findings")
                self.assertEqual(GRADERS["direct-full-tally"].drops(results), ())

    def test_a_finding_restating_a_dropped_finding_is_dropped_with_its_criteria(self):
        review = [NAMED_KIND, dict(EVIDENCE, restates="")]
        for restates in ("full-review:2", "see full-review:2 and AC5"):
            with self.subTest(restates=restates):
                results = {**rereview([dict(EVIDENCE, restates=restates, summary="AC5 still has no evidence")]),
                           "full-review.findings": review}
                self.assertEqual(graded(results), ("clean", ({"finding": "full-rereview:1", "criteria": ["AC5"]},)))
        unnamed = dict(EVIDENCE, restates="full-review:2", summary="still unresolved")
        results = {**rereview([unnamed]), "full-review.findings": review, "full-independent.findings": []}
        self.assertEqual(graded(results), ("clean", ({"finding": "full-rereview:1", "criteria": ["AC5"]},)))

    def test_a_finding_restating_a_kept_or_unknown_finding_is_kept(self):
        review = [NAMED_KIND, dict(EVIDENCE, restates="")]
        for label, restates, earlier in (
                ("a kept finding", "full-review:1", review),
                ("a place past the list", "full-review:3", review),
                ("place 0", "full-review:0", review),
                ("a place too long to count", "full-review:" + "9" * 5000, review),
                ("a step not read", "full-independent:2", review),
                ("a list that is no list", "full-review:2", "x"),
                ("a finding that is no mapping", "full-review:2", [1, "x"]),
                ("one dropped and one kept", "full-review:2 full-review:1", review),
                ("a dropped finding that restates", "full-review:3",
                 [*review, dict(EVIDENCE, restates="full-review:2")])):
            with self.subTest(label):
                results = {**rereview([dict(EVIDENCE, restates=restates, summary="still unresolved")]),
                           "full-review.findings": earlier}
                self.assertEqual(graded(results), ("findings", ()))

    def test_a_restatement_naming_a_code_criterion_or_of_another_kind_is_kept_though_its_original_is_dropped(self):
        review = [dict(EVIDENCE, restates="")]
        for label, extra in (("code criterion", {"summary": "AC1 test fails on empty input"}),
                             ("security", {"kind": "security"})):
            with self.subTest(label):
                finding = dict(EVIDENCE, restates="full-review:1", **{"summary": "AC5 unmet", **extra})
                results = {**rereview([finding]), "full-review.findings": review}
                self.assertEqual(graded(results), ("findings", ()))

    def test_the_earlier_findings_a_settled_step_reads_are_never_listed_as_its_drops(self):
        results = {**rereview([dict(EVIDENCE, restates="full-review:1", summary="AC5")]),
                   "full-review.findings": [dict(EVIDENCE, restates="")],
                   "full-independent.findings": [dict(EVIDENCE, restates="")]}
        self.assertEqual(graded(results)[1], ({"finding": "full-rereview:1", "criteria": ["AC5"]},))
        reversed_order = {"full-review.findings": results["full-review.findings"], **results}
        self.assertEqual(graded(reversed_order), graded(results))

    def test_only_the_four_review_graders_drop(self):
        self.assertEqual({n for n, g in GRADERS.items() if g.drops is dropped},
                         {"direct-lite-tally", "direct-escalated-tally", "direct-full-tally", "direct-settled"})
        self.assertEqual(NON_CODE_KINDS, ("evidence", "human", "note"))
        self.assertEqual(GRADERS["lane-rule"].drops({}), ())


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


class OutlineGraderTest(unittest.TestCase):
    def mapped(self, slices, criteria, **kw):
        return GRADERS["outline-mapped"].grade(mapping(slices, criteria, **kw))

    def test_outline_mapped_refuses_a_criterion_that_names_no_slice(self):
        self.assertEqual(self.mapped([S1], on(["AC1", "AC2"], lambda i: i)), "unmapped")
        self.assertEqual(self.mapped([S1], on(["AC1", "AC2"])), "mapped")

    def test_outline_mapped_refuses_an_issue_criterion_the_outline_omits(self):
        self.assertEqual(self.mapped([S1], on(["AC1"])), "unmapped")
        self.assertEqual(self.mapped([S1], on(["AC1", "AC2", "AC3"])), "unmapped")
        self.assertEqual(self.mapped([S1], on(["AC1", "AC1"])), "unmapped")
        self.assertEqual(self.mapped([S1], on(["ac1", "ac2"])), "mapped")

    def test_outline_mapped_refuses_slices_that_share_a_number_or_leave_build_order(self):
        both = on(["AC1", "AC2"])
        self.assertEqual(self.mapped([S1, dict(S2, n=1)], both), "unmapped")
        self.assertEqual(self.mapped([S2, S1], both), "unmapped")
        self.assertEqual(self.mapped([S1, S2], both), "mapped")

    def test_outline_mapped_reads_any_step_by_suffix(self):
        self.assertEqual(self.mapped([S1], on(["AC1", "AC2"]), step="outline-revise"), "mapped")

    def test_outline_mapped_refuses_a_bool_slice_and_non_lists(self):
        self.assertEqual(self.mapped([S1], on(["AC1", "AC2"], lambda i: True)), "unmapped")
        self.assertEqual(self.mapped([S1], None), "unmapped")
        self.assertEqual(self.mapped(None, on(["AC1", "AC2"])), "unmapped")
        self.assertEqual(self.mapped([dict(S1, n=True)], on(["AC1", "AC2"])), "unmapped")

    def test_outline_mapped_needs_an_empty_criteria_list_for_an_issue_with_none(self):
        self.assertEqual(self.mapped([S1], [], issue="# t\n\nbody\n"), "mapped")
        self.assertEqual(self.mapped([S1], on(["AC1"]), issue="# t\n\nbody\n"), "unmapped")

    def test_outline_proven_needs_a_test_and_an_assertion_on_every_slice(self):
        grade = GRADERS["outline-proven"].grade

        def proven(slices):
            return grade({"outline.slices": slices})

        self.assertEqual(proven([dict(S1, test="  ")]), "unproven")
        self.assertEqual(proven([dict(S1, assertion="")]), "unproven")
        self.assertEqual(proven([]), "unproven")
        self.assertEqual(proven([S1, dict(S1, n=2, assertion=None), ]), "unproven")
        self.assertEqual(proven([S1, S2]), "proven")

    def test_the_outline_graders_declare_their_outcomes(self):
        self.assertEqual(GRADERS["outline-mapped"].outcomes, ("mapped", "unmapped"))
        self.assertEqual(GRADERS["outline-proven"].outcomes, ("proven", "unproven"))


if __name__ == "__main__":
    unittest.main()
