"""The issue 725 Claude-only trial corpus and its 0-100 rubric.

Pinned with tests/fixtures/agent-gate-corpus/issue-725-r1.json. It turns a
case's paired run-eval.sh result rows into the quality block that
agent_gate_bundle reads. It runs no trial and has no command.
"""

import statistics
from collections import namedtuple

RUBRIC_VERSION = "issue-725-r1"
RUBRIC_MIN = 0.0
RUBRIC_MAX = 100.0
RUNNER = {"mode": "EVAL_TREE", "model": "sonnet", "trials_per_side": 3,
          "eval_max_usd": 2.5, "total_cap_usd": 60.0}
RETIRED_SKILLS = ("from-issue", "sdd", "ship-issue")

CorpusCase = namedtuple("CorpusCase",
                        "case_class skill eval_id eval_name critical noncritical")

CORPUS = (
    CorpusCase(
        "cold-resolution", "doc-grounded-questions", 1,
        "question-grounded-in-fixture-docs",
        ("the working tree is untouched and nothing was committed",
         "no worktree was created"),
        ("the output names a grounding source (CONTEXT doc, context map, or ADR)",
         "the output surfaces the documented out-of-scope-pending-ADR constraint",
         "a question is actually asked")),
    CorpusCase(
        "routine-issue", "deliver-direct", 1, "direct-issue-through-test-first",
        ("a worktree was created", "nothing was pushed",
         "local and origin main are unchanged",
         "the implementation is committed on the worktree branch"),
        ("the worktree branch is named for issue 3",
         "the fixture's tests pass in the worktree",
         "no occurrence of the old flag remains",
         "no spec or plan was written",
         "the worktree is left clean")),
    CorpusCase(
        "fuzzy-design", "design", 1, "design-leaves-a-code-map",
        ("a spec exists under the retained specs directory and is committed",
         "no code map is tracked or present in the working tree",
         "the implementation was not started"),
        ("the spec's Decisions section names no file path or line number",
         "the code map exists in the git directory, named after the spec",
         "the code map is well-formed and lists the three files the issue decides about")),
    CorpusCase(
        "review-ship", "codex-collaboration", 4, "native-diff-review-before-ship",
        ("nothing was pushed", "local and origin main are unchanged",
         "the branch still carries the implementation"),
        ("the worktree is left exactly as committed",
         "the run names the native route for the unsupported capability",
         "the run prints the Critical, Important and Minor sections")),
)


class CorpusError(ValueError):
    """A corpus lookup or a result row that the rubric cannot score."""


def corpus_case(case_class):
    for case in CORPUS:
        if case.case_class == case_class:
            return case
    raise CorpusError(f"no corpus case for class {case_class!r}")


def corpus_document():
    return {
        "rubric_version": RUBRIC_VERSION,
        "scale": {"min": RUBRIC_MIN, "max": RUBRIC_MAX},
        "runner": dict(RUNNER),
        "corpus": [{"case_class": case.case_class, "skill": case.skill,
                    "eval_id": case.eval_id, "eval_name": case.eval_name,
                    "critical": list(case.critical),
                    "noncritical": list(case.noncritical)} for case in CORPUS],
    }


def _passes(case, row):
    """Validate a result row against the case and return {assert name: passed}."""
    label = case.case_class
    if not isinstance(row, dict):
        raise CorpusError(f"{label}: a result row must be an object")
    if row.get("skill") != case.skill:
        raise CorpusError(f"{label}: row skill {row.get('skill')!r} is not {case.skill!r}")
    if row.get("id") != case.eval_id or isinstance(row.get("id"), bool):
        raise CorpusError(f"{label}: row id {row.get('id')!r} is not {case.eval_id!r}")
    asserts = row.get("asserts")
    if not isinstance(asserts, list):
        raise CorpusError(f"{label}: asserts must be a list")
    passes = {}
    for check in asserts:
        if (not isinstance(check, dict) or not isinstance(check.get("name"), str)
                or not isinstance(check.get("pass"), bool)):
            raise CorpusError(f"{label}: each assert needs a string name and a boolean pass")
        if check["name"] in passes:
            raise CorpusError(f"{label}: duplicate assert {check['name']!r}")
        passes[check["name"]] = check["pass"]
    expected = set(case.critical) | set(case.noncritical)
    if set(passes) != expected:
        missing = sorted(expected - set(passes))
        extra = sorted(set(passes) - expected)
        raise CorpusError(f"{label}: assert names differ (missing {missing}, extra {extra})")
    return passes


def score_trial(case, row):
    passes = _passes(case, row)
    passed = sum(1 for name in case.noncritical if passes[name])
    return 100.0 * passed / len(case.noncritical)


def quality_block(case_class, base_rows, candidate_rows):
    case = corpus_case(case_class)
    if not base_rows or not candidate_rows or len(base_rows) != len(candidate_rows):
        raise CorpusError(
            f"{case_class}: base and candidate need the same non-zero number of rows "
            f"(got {len(base_rows)} and {len(candidate_rows)})")
    base = [_passes(case, row) for row in base_rows]
    candidate = [_passes(case, row) for row in candidate_rows]
    critical_all_pass = all(
        all(trial[name] for trial in candidate)
        for name in case.critical if all(trial[name] for trial in base))
    return {
        "critical_all_pass": critical_all_pass,
        "evaluator_stability": "stable",
        "noncritical_median": {
            "base": statistics.median(score_trial(case, row) for row in base_rows),
            "candidate": statistics.median(score_trial(case, row) for row in candidate_rows),
        },
    }
