"""The console's plain questions for an adoption plan's open decisions (#1053).

The module under test is pure; it still binds the module fixtures every console test module binds.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import unittest

from agent_tools.console import plan_questions

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1053)

SECRET_WHY = (
    ".claude/secrets/key.md looks like a secret, so it cannot be answered here: remove it from the "
    "repository in its own commit, then register the repository again."
)
OUTSIDE_WHY = (
    ".claude/link.md points outside the repository, so it cannot be answered here: remove it from "
    "the repository in its own commit, then register the repository again."
)
NULL_PROJECT_WHY = (
    "The plan cannot tell which project this is, so it cannot be answered here: give the repository "
    "exactly one git remote, or write its project id in .agents/project.json, then register it again."
)
TAKEN_PROJECT_WHY = (
    "o/r is already registered for another checkout, so it cannot be answered here: write the "
    "intended project id in .agents/project.json, then register the repository again."
)
MOVES = "name paths this plan moves. Should they follow the move?"


def document(open_, path_references=(), reference_policies=()):
    return {
        "decisions": {"open": list(open_)},
        "path_references": list(path_references),
        "reference_policies": list(reference_policies),
    }


def candidate(subject, value):
    return {
        "id": "candidate-class", "subject": subject, "value": value,
        "basis": "b", "impact": "i", "recommendation": "r",
    }


REFERENCE_ROW = {
    "subject": "tools/a.json:3:7", "path": "tools/a.json", "line": 3, "literal": ".claude/specs",
    "additions": [".agents/artifacts/specs", ".agents/x"], "replacement": ".agents/artifacts/specs",
}
REFERENCE = {
    "id": "path-reference", "subject": "tools/a.json:3:7", "answers": ["extend", "rewrite", "retain"],
}
POLICY_ROW = {"subject": ".claude/notes:.py", "tree": ".claude/notes", "class": ".py"}


def policy(value, answers=("rewrite", "retain")):
    return {
        "id": "reference-policy", "subject": ".claude/notes:.py", "answers": list(answers),
        "value": value,
    }


def project_id(value):
    return {"id": "project-id", "subject": "", "value": value}


ONLY_ANSWER = "This is the only thing the adoption can do with this file."


class QuestionsTest(unittest.TestCase):
    def test_a_tracked_candidate_offers_the_archive(self):
        doc = document([candidate(".claude/odd.md", "archive-history")])
        self.assertEqual(
            plan_questions.questions(doc),
            [{
                "id": "candidate-class",
                "subject": ".claude/odd.md",
                "ask": "What should happen to .claude/odd.md? No rule covers this agent file.\n"
                       "This is the only thing the adoption can do with this file.",
                "options": [{
                    "value": "archive-history",
                    "label": "Archive it under .agents/knowledge/archive/adopted/",
                }],
                "recommended": None,
                "why": None,
            }],
        )

    def test_an_ignored_candidate_offers_to_keep_it(self):
        doc = document([candidate(".claude/odd.md", "retain-product")])
        self.assertEqual(
            plan_questions.questions(doc)[0]["options"],
            [{"value": "retain-product", "label": "Keep it where it is"}],
        )

    def test_a_secret_shaped_candidate_says_why_and_offers_nothing(self):
        question = plan_questions.questions(
            document([candidate(".claude/secrets/key.md", None)])
        )[0]
        self.assertEqual(question["options"], [])
        self.assertEqual(question["why"], SECRET_WHY)

    def test_a_candidate_outside_the_repository_says_why(self):
        question = plan_questions.questions(document([candidate(".claude/link.md", None)]))[0]
        self.assertEqual(question["options"], [])
        self.assertEqual(question["why"], OUTSIDE_WHY)

    def test_a_path_reference_offers_exactly_its_answers_in_order(self):
        question = plan_questions.questions(document([REFERENCE], [REFERENCE_ROW]))[0]
        self.assertEqual(
            question["ask"],
            "tools/a.json line 3 names .claude/specs, which this plan moves. "
            "Should it follow the move?",
        )
        self.assertEqual(
            question["options"],
            [
                {"value": "extend", "label": "Also name .agents/artifacts/specs and .agents/x"},
                {"value": "rewrite", "label": "Change it to .agents/artifacts/specs"},
                {"value": "retain", "label": "Leave it as it is"},
            ],
        )
        self.assertIsNone(question["recommended"])
        self.assertIsNone(question["why"])

    def test_a_path_reference_with_only_rewrite_and_retain(self):
        entry = {**REFERENCE, "answers": ["rewrite", "retain"]}
        question = plan_questions.questions(document([entry], [REFERENCE_ROW]))[0]
        self.assertEqual([o["value"] for o in question["options"]], ["rewrite", "retain"])

    def test_a_reference_policy_marks_its_recommendation(self):
        question = plan_questions.questions(document([policy("rewrite")], (), [POLICY_ROW]))[0]
        self.assertEqual(question["ask"], f"The .py files under .claude/notes {MOVES}")
        self.assertEqual(
            [o["label"] for o in question["options"]],
            ["Change every path that can follow the move (recommended)", "Leave these files as they are"],
        )
        self.assertEqual(question["recommended"], "rewrite")

    def test_a_reference_policy_with_no_recommendation_and_no_extension(self):
        row = {**POLICY_ROW, "class": "-"}
        question = plan_questions.questions(document([policy(None)], (), [row]))[0]
        self.assertTrue(question["ask"].startswith("The files with no extension under"))
        self.assertFalse(any("(recommended)" in o["label"] for o in question["options"]))
        self.assertIsNone(question["recommended"])

    def test_a_project_id_question_says_why(self):
        questions = [
            plan_questions.questions(document([project_id(value)]))[0] for value in (None, "o/r")
        ]
        self.assertEqual([q["ask"] for q in questions], ["Which project is this repository?"] * 2)
        self.assertEqual([q["options"] for q in questions], [[], []])
        self.assertEqual([q["why"] for q in questions], [NULL_PROJECT_WHY, TAKEN_PROJECT_WHY])

    def test_an_unknown_question_says_why(self):
        entry = {"id": "reference-format", "subject": "x"}
        question = plan_questions.questions(document([entry]))[0]
        self.assertEqual(question["ask"], "reference-format x")
        self.assertEqual(question["options"], [])
        self.assertEqual(question["why"], plan_questions.NO_ANSWER)

    def test_the_questions_keep_the_plans_order_and_why_is_set_exactly_without_options(self):
        entries = [
            candidate(".claude/odd.md", "archive-history"),
            candidate(".claude/secrets/key.md", None),
            REFERENCE,
            project_id(None),
        ]
        questions = plan_questions.questions(document(entries, [REFERENCE_ROW]))
        self.assertEqual(
            [q["subject"] for q in questions],
            [".claude/odd.md", ".claude/secrets/key.md", "tools/a.json:3:7", ""],
        )
        for question in questions:
            self.assertEqual(question["why"] is None, question["options"] != [])

    def test_a_sparse_document_does_not_raise(self):
        doc = {"decisions": {"open": [
            {"id": "project-id"},
            {"id": "path-reference", "subject": "s:1:1", "answers": ["retain"]},
        ]}}
        questions = plan_questions.questions(doc)
        self.assertEqual(len(questions), 2)
        self.assertEqual(
            questions[1]["ask"],
            "s:1:1 names a path this plan moves. Should it follow the move?\n" + ONLY_ANSWER,
        )

    def test_a_question_with_exactly_one_answer_says_so_and_one_with_two_does_not(self):
        one = [
            candidate(".claude/odd.md", "retain-product"),
            {**REFERENCE, "answers": ["retain"]},
            policy(None, ["retain"]),
        ]
        two = [{**REFERENCE, "answers": ["rewrite", "retain"]}, policy("rewrite")]
        for question in plan_questions.questions(document(one, [REFERENCE_ROW], [POLICY_ROW])):
            with self.subTest(subject=question["subject"]):
                self.assertEqual(len(question["options"]), 1)
                self.assertTrue(question["ask"].endswith("\n" + ONLY_ANSWER), question["ask"])
        for question in plan_questions.questions(document(two, [REFERENCE_ROW], [POLICY_ROW])):
            with self.subTest(subject=question["subject"]):
                self.assertNotIn(ONLY_ANSWER, question["ask"])
        for entry in (candidate(".claude/secrets/key.md", None), project_id(None)):
            self.assertNotIn(ONLY_ANSWER, plan_questions.questions(document([entry]))[0]["ask"])


class ParseTest(unittest.TestCase):
    def test_an_answer_body_is_parsed(self):
        body = (
            b'{"plan_id": "sha256:a", "id": "candidate-class", "subject": ".claude/odd.md", '
            b'"value": "archive-history"}'
        )
        self.assertEqual(
            plan_questions.parse_answer_request(body),
            ("sha256:a", "candidate-class", ".claude/odd.md", "archive-history"),
        )

    def test_other_bodies_raise(self):
        bodies = [
            b"[]",
            b"not json",
            b"\xff",
            b'{"plan_id": "p", "id": "i", "subject": "s"}',
            b'{"plan_id": "p", "id": "i", "subject": "s", "value": "v", "extra": "e"}',
            b'{"plan_id": "p", "id": "i", "subject": "s", "value": 1}',
            b'{"plan_id": "p", "id": "i", "subject": "", "value": "v"}',
            b'{"plan_id": "p", "id": "i", "subject": "a\\nb", "value": "v"}',
        ]
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(ValueError):
                plan_questions.parse_answer_request(body)


class RefusalTest(unittest.TestCase):
    def test_the_plans_own_refusals_read_in_plain_words(self):
        for repair in ("adopt.decisions.invalid_answer", "adopt.decisions.unmatched_answer"):
            error = {
                "code": "adopt_failure",
                "repair_id": repair,
                "violations": [{
                    "pointer": "/decisions/answered", "message": "the answer is not\n the one",
                }],
            }
            with self.subTest(repair=repair):
                self.assertEqual(
                    plan_questions.refusal_text(error),
                    "The plan refused that answer: the answer is not the one",
                )

    def test_any_other_error_is_not_made_again_in_its_message_never_its_code(self):
        error = {
            "code": "adopt_failure",
            "repair_id": "adopt.some.repair",
            "violations": [{"pointer": "/x", "message": "the store\n is unreadable"}],
        }
        self.assertEqual(
            plan_questions.refusal_text(error),
            "The plan was not made again: the store is unreadable",
        )
        for bare in (
            {"code": "adopt_failure", "repair_id": "adopt.internal", "violations": []},
            {"code": "adopt_failure"},
            {},
        ):
            with self.subTest(error=bare):
                self.assertEqual(plan_questions.refusal_text(bare), "The plan was not made again.")

    def test_a_failed_run_is_not_made_again_in_the_words_it_is_given(self):
        self.assertEqual(
            plan_questions.rerun_failed("it took too long and was stopped"),
            "The plan was not made again: it took too long and was stopped",
        )


if __name__ == "__main__":
    unittest.main()
