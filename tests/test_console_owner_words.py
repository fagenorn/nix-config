"""The console's runtime copy of the owner glossary matches the docs table and flags what it should.

Run: just agent-workflow-tests
"""
import json
import unittest
from pathlib import Path

from agent_tools.console import owner_words
from agent_tools.delivery.routing import index_table

TIER = "fast"

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES = REPO_ROOT / "tests/fixtures/console/owner-words-cases.json"


def G(word):
    return dict(owner_words.GLOSSARY)[word]


class GlossaryTest(unittest.TestCase):
    def test_a_word_used_without_its_gloss_is_flagged_with_its_gloss(self):
        self.assertEqual(owner_words.unglossed("waiting on the land lock"), [("land lock", G("land lock"))])

    def test_the_glossary_copy_matches_the_docs_table(self):
        text = (REPO_ROOT / "docs/guides/owner-words.md").read_text(encoding="utf-8")
        rows = index_table(text)[1:]
        self.assertEqual([tuple(r) for r in rows], list(owner_words.GLOSSARY))
        self.assertEqual(len(owner_words.GLOSSARY), 12)

    def test_text_with_no_glossary_word_flags_nothing(self):
        self.assertEqual(owner_words.unglossed("two parts of the job are being built"), [])

    def test_a_word_matches_in_any_case(self):
        self.assertEqual(owner_words.unglossed("Waiting on the Land Lock"), [("land lock", G("land lock"))])
        self.assertEqual(owner_words.unglossed("the ci failed"), [("CI", G("CI"))])

    def test_a_word_inside_a_longer_word_is_not_flagged(self):
        self.assertEqual(owner_words.unglossed("a guardrail, a reclaim, decide, looked, held2"), [])

    def test_a_non_ascii_letter_or_space_never_folds_or_separates(self):
        self.assertEqual(owner_words.unglossed("İguard refused it"), [("guard", G("guard"))])
        self.assertEqual(owner_words.unglossed("looK at it"), [])
        self.assertEqual(owner_words.unglossed("the land lock"), [])

    def test_a_two_word_entry_matches_across_any_whitespace(self):
        self.assertEqual(owner_words.unglossed("the land \t\n lock"), [("land lock", G("land lock"))])

    def test_an_inflected_form_is_not_flagged(self):
        self.assertEqual(owner_words.unglossed("two slices, three pull requests, it looks fine, verified"), [])

    def test_a_word_glossed_in_the_same_text_is_not_flagged(self):
        text = "the land lock (" + G("land lock").upper().replace(" ", " \t ") + ")"
        self.assertEqual(owner_words.unglossed(text), [])
        self.assertEqual(
            owner_words.unglossed("the land lock and the rerun (" + G("land lock") + ")"),
            [("rerun", G("rerun"))],
        )

    def test_flags_come_in_glossary_order_once_each(self):
        self.assertEqual(
            owner_words.unglossed("rerun it, the pull request is held, rerun again"),
            [("held", G("held")), ("rerun", G("rerun")), ("pull request", G("pull request"))],
        )

    def test_unglossed_in_counts_a_word_once_across_texts(self):
        self.assertEqual(
            owner_words.unglossed_in(["rerun now", "the guard said no", "rerun later"]),
            [("guard", G("guard")), ("rerun", G("rerun"))],
        )
        self.assertEqual(owner_words.unglossed_in([]), [])

    def test_entries_is_the_wire_form_in_glossary_order(self):
        self.assertEqual(owner_words.entries(), [{"word": w, "gloss": g} for w, g in owner_words.GLOSSARY])

    def test_the_shared_cases_flag_what_the_case_file_says(self):
        cases = json.loads(CASES.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 9)
        for case in cases:
            with self.subTest(text=case["text"]):
                self.assertEqual([w for w, _ in owner_words.unglossed(case["text"])], case["flagged"])
