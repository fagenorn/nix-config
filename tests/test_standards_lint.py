"""The citation form an enforcer uses to name a standard's rule (#1442).

Measures the form itself: `citations` finds each citation with its line and
whether its token is a well-formed rule id, a form glued to a word is no
citation, `prefix_of` reads the id's capital letters, and the standards README
states the form and gives the project shards the project prefix.
"""

import unittest
from pathlib import Path

from agent_tools.delivery.context_map_lint import CODE_RE, section, table_rows
from agent_tools.delivery.rule_ids import (
    CITATION, PROJECT_PREFIX, RULE_ID_HEADING, Citation, citations, prefix_of)

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "home/common/agent-skills/standards/README.md"
BAR = REPO_ROOT / "home/common/agent-skills/standards/the-bar.md"


def cite(token: str) -> str:
    """One citation of `token`, assembled so this file holds no literal citation."""
    return "standard" + ":" + token


class CitationFormTest(unittest.TestCase):
    def test_a_citation_is_found_with_its_line_and_token(self):
        text = "one\n# " + cite("B7") + " and " + cite("PY3") + "\n"

        found = citations(text)

        self.assertEqual(found, [Citation(2, "B7", True), Citation(2, "PY3", True)])

    def test_a_form_glued_to_a_word_is_no_citation(self):
        for text in ("non" + cite("B7"), "x_" + cite("B7"), "x-" + cite("B7"), "x1" + cite("B7")):
            with self.subTest(text=text):
                self.assertEqual(citations(text), [])

    def test_a_token_that_is_no_rule_id_is_malformed(self):
        for token in ("b7", "B07", "B7a", "B", "7"):
            with self.subTest(token=token):
                self.assertEqual(citations(cite(token)), [Citation(1, token, False)])

    def test_trailing_punctuation_ends_the_token(self):
        self.assertEqual(citations(cite("B7") + "."), [Citation(1, "B7", True)])
        self.assertEqual(citations("(" + cite("NET10") + ")"), [Citation(1, "NET10", True)])

    def test_prefix_of_reads_the_capital_letters(self):
        self.assertEqual([prefix_of(i) for i in ("P4", "PY3", "NET10", "B1")], ["P", "PY", "NET", "B"])


class ReadmeFormTest(unittest.TestCase):
    def test_the_readme_states_the_citation_form(self):
        block = section(README.read_text("utf-8"), "Rule ids")
        bar_ids = set()
        for line in BAR.read_text("utf-8").splitlines():
            match = RULE_ID_HEADING.match(line)
            if match and match["hashes"] == "###":
                bar_ids.add(match["prefix"] + match["number"])

        spans = [span for span in CODE_RE.findall(block)
                 if CITATION.fullmatch(span) and citations(span)[0].well_formed]

        self.assertTrue(spans)
        for span in spans:
            self.assertIn(citations(span)[0].token, bar_ids)

    def test_the_readme_gives_project_shards_the_project_prefix(self):
        rows = table_rows(section(README.read_text("utf-8"), "Rule ids"))

        row = next(r for r in rows if "docs/standards/" in CODE_RE.findall(r[0]))

        self.assertEqual(CODE_RE.findall(row[1])[0], PROJECT_PREFIX)


if __name__ == "__main__":
    unittest.main()
