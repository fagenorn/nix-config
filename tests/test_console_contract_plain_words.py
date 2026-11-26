"""The manager contract sends what a manager writes for the owner to the plain-words rule.

Run: just agent-workflow-tests
"""
import json
import re
import unittest

from agent_tools.console import owner_words

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
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

    def test_the_contract_states_the_one_rule(self):
        text = run_sprint("contract").stdout
        section = text.partition("\n## Writing for the owner\n")[2].partition("\n## ")[0]
        flat = " ".join(section.split())
        self.assertIn("a person who has never seen this system understands each sentence on its own", flat)
        self.assertIn("Never lean on a list of terms", flat)
        self.assertIn("rewrite that sentence with the words the warning gives", flat)
        self.assertIsNone(re.search(r"(?i)\bgloss", flat))

    def test_the_printed_examples_of_owner_copy_use_no_internal_word(self):
        text = run_sprint("contract").stdout
        blocks = re.findall(r"```json\n(.*?)\n\s*```", text, re.S)
        self.assertEqual(len(blocks), 2)
        report, closing = (json.loads(block) for block in blocks)
        copy = [report["status"], report["next"], closing["summary"], closing["differently"]]
        copy += re.findall(r"for example `([^`]*)`", text)
        self.assertGreaterEqual(len(copy), 5)
        for line in copy:
            with self.subTest(line=line):
                self.assertEqual([f.word for f in owner_words.found(line)], [])


if __name__ == "__main__":
    unittest.main()
