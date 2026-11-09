"""Offline tests for agent_tools.agent_gate_corpus: the issue 725 corpus and rubric.

Run: just agent-workflow-tests
"""

import json
import unittest
from pathlib import Path

from agent_tools import agent_gate_bundle as gate
from agent_tools import agent_gate_corpus as corpus

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests/fixtures/agent-gate-corpus/issue-725-r1.json"
SKILL_ROOTS = (REPO_ROOT / "home/common/agent-skills/skills",
               REPO_ROOT / "home/common/claude-code/skills")


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def row(case, failed=()):
    names = case.critical + case.noncritical
    return {"skill": case.skill, "id": case.eval_id,
            "asserts": [{"name": name, "pass": name not in failed} for name in names]}


def eval_case(skill, eval_id):
    for root in SKILL_ROOTS:
        path = root / skill / "evals/evals.json"
        if path.is_file():
            for case in json.loads(path.read_text(encoding="utf-8"))["evals"]:
                if case["id"] == eval_id:
                    return case
    raise AssertionError(f"no eval {skill} {eval_id}")


class CorpusPinTest(unittest.TestCase):
    def test_the_module_equals_the_pinned_fixture(self):
        pinned = fixture()
        pinned.pop("examples")
        self.assertEqual(corpus.corpus_document(), pinned)
        self.assertEqual(corpus.RUBRIC_VERSION, "issue-725-r1")
        self.assertEqual(corpus.RETIRED_SKILLS, ("from-issue", "sdd", "ship-issue"))
        self.assertEqual(corpus.RUBRIC_MAX, gate.RUBRIC_MAX)
        self.assertEqual(corpus.RUNNER, {"mode": "EVAL_TREE", "model": "sonnet",
                                         "trials_per_side": 3, "eval_max_usd": 2.5,
                                         "total_cap_usd": 60.0})

    def test_one_case_per_core_class(self):
        self.assertEqual(tuple(case.case_class for case in corpus.CORPUS), gate.CORE_CASE_CLASSES)

    def test_each_case_is_a_surviving_pipeline_eval_with_an_exact_partition(self):
        for case in corpus.CORPUS:
            with self.subTest(case=case.case_class):
                self.assertNotIn(case.skill, corpus.RETIRED_SKILLS)
                found = eval_case(case.skill, case.eval_id)
                self.assertEqual((found["name"], found["mode"]), (case.eval_name, "pipeline"))
                names = [check["name"] for check in found["asserts"]]
                self.assertEqual(sorted(names), sorted(case.critical + case.noncritical))
                self.assertFalse(set(case.critical) & set(case.noncritical))
                self.assertTrue(case.critical and case.noncritical)


class RubricTest(unittest.TestCase):
    def test_the_worked_examples(self):
        for index, example in enumerate(fixture()["examples"]):
            with self.subTest(example=index):
                case = corpus.corpus_case(example["case_class"])
                block = corpus.quality_block(
                    example["case_class"],
                    [row(case, failed) for failed in example["base"]],
                    [row(case, failed) for failed in example["candidate"]])
                self.assertEqual(block, example["expected"])
                diagnostics = []
                gate._validate_quality({"quality": block}, "$", diagnostics)
                self.assertEqual(diagnostics, [])

    def test_a_trial_score_is_the_noncritical_pass_share(self):
        case = corpus.corpus_case("routine-issue")
        self.assertEqual(corpus.score_trial(case, row(case)), 100.0)
        self.assertEqual(corpus.score_trial(case, row(case, case.noncritical[:2])), 60.0)
        self.assertEqual(corpus.score_trial(case, row(case, case.critical)), 100.0)

    def test_malformed_rows_are_refused(self):
        case = corpus.corpus_case("review-ship")
        good = row(case)
        bad = {
            "wrong skill": dict(good, skill="ship-issue"),
            "wrong id": dict(good, id=3),
            "missing assert": dict(good, asserts=good["asserts"][1:]),
            "extra assert": dict(good, asserts=good["asserts"] + [{"name": "x", "pass": True}]),
            "duplicate assert": dict(good, asserts=good["asserts"] + good["asserts"][:1]),
            "non-bool pass": dict(good, asserts=[dict(good["asserts"][0], **{"pass": 1})]
                                  + good["asserts"][1:]),
        }
        for label, value in bad.items():
            with self.subTest(label=label), self.assertRaises(corpus.CorpusError):
                corpus.quality_block("review-ship", [value] * 3, [good] * 3)

    def test_unpaired_or_empty_sides_and_unknown_classes_are_refused(self):
        case = corpus.corpus_case("fuzzy-design")
        for base, candidate in (([row(case)] * 3, [row(case)] * 2), ([], [])):
            with self.subTest(base=len(base), candidate=len(candidate)):
                with self.assertRaises(corpus.CorpusError):
                    corpus.quality_block("fuzzy-design", base, candidate)
        with self.assertRaises(corpus.CorpusError):
            corpus.corpus_case("repo-specific")


if __name__ == "__main__":
    unittest.main()
