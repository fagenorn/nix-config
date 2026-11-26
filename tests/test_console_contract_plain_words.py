"""The manager contract sends what a manager writes for the owner to the plain-words rule.

Run: just agent-workflow-tests
"""
import json
import re
import unittest

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_sprint_command import run_sprint

TIER = "fast"

# Internal words the owner does not know (docs/guides/owner-words.md), which the contract's own
# printed examples must not use unglossed: the examples are copied into what the owner reads.
UNGLOSSED = re.compile(r"\b(?:slices?|land(?:s|ed|ing)?|held|claims?|verif(?:y|ied))\b", re.IGNORECASE)


class ContractPlainWordsTest(unittest.TestCase):
    def test_the_contract_says_status_lines_cards_and_questions_follow_the_plain_words_rule(self):
        text = run_sprint("contract").stdout
        section = text.partition("\n## Writing for the owner\n")[2].partition("\n## ")[0]
        self.assertNotEqual(section, "")
        flat = " ".join(section.split())
        self.assertIn("every status line, card and question you write follows the plain-words rule", flat)
        self.assertIn("`docs/guides/write-for-the-owner.md`", flat)
        self.assertIn("`docs/guides/owner-words.md`", flat)

    def test_the_printed_examples_of_owner_copy_use_no_internal_word(self):
        text = run_sprint("contract").stdout
        report = json.loads(text.partition("```json\n")[2].partition("```")[0])
        copy = [report["status"], report["next"]]
        copy += re.findall(r"for example `([^`]*)`", text)
        self.assertGreaterEqual(len(copy), 3)
        for line in copy:
            with self.subTest(line=line):
                self.assertIsNone(UNGLOSSED.search(line))


if __name__ == "__main__":
    unittest.main()
