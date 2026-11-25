"""The manager contract sends what a manager writes for the owner to the plain-words rule.

Run: just agent-workflow-tests
"""
import unittest

from .test_console_sprint_command import run_sprint

TIER = "fast"


class ContractPlainWordsTest(unittest.TestCase):
    def test_the_contract_says_status_lines_cards_and_questions_follow_the_plain_words_rule(self):
        text = run_sprint("contract").stdout
        section = text.partition("\n## Writing for the owner\n")[2].partition("\n## ")[0]
        self.assertNotEqual(section, "")
        flat = " ".join(section.split())
        self.assertIn("every status line, card and question you write follows the plain-words rule", flat)
        self.assertIn("`docs/guides/write-for-the-owner.md`", flat)
        self.assertIn("`docs/guides/owner-words.md`", flat)


if __name__ == "__main__":
    unittest.main()
