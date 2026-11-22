"""Every rule heading of the three standards layers carries one stable id (#1438).

Measures acceptance criterion 1 (each rule of the bar, the stack shards and the
project shards is one `###` heading opening with one well-formed id, and the
standards README names one prefix per layer file) and criterion 2 (every
project rule is a heading with a `P` id, none a numbered list item).
"""

import re
import unittest
from pathlib import Path

from agent_tools.delivery.context_map_lint import MAP_BUDGET, TERM_DEF_RE, section, table_rows
from agent_tools.delivery.rule_ids import (
    layer_problems, numbered_items, prefix_table, rule_headings, sections)
from agent_tools.project_contract.adopt_links import links

REPO_ROOT = Path(__file__).resolve().parents[1]
GLOBAL = REPO_ROOT / "home/common/agent-skills/standards"
BAR = GLOBAL / "the-bar.md"
README = GLOBAL / "README.md"
PROJECT = REPO_ROOT / "docs/standards"

def link_destinations(body: str) -> list[str]:
    return [link.target for link in links(body)]


def layer_files() -> tuple[list, list, list]:
    table = prefix_table(README.read_text())
    bar = [("the-bar.md", table["the-bar.md"], BAR.read_text())]
    stacks = [(f"stacks/{path.name}", table[f"stacks/{path.name}"], path.read_text())
              for path in sorted((GLOBAL / "stacks").glob("*.md"))]
    project = [(f"docs/standards/{path.name}", table["docs/standards/"], path.read_text())
               for path in sorted(PROJECT.glob("*.md")) if path.name != "README.md"]
    return bar, stacks, project


def glossary_entries(text: str) -> dict[str, str]:
    """Term to its definition: the text after `**Term**:` up to the next term or heading.

    Every line starting `_Avoid_:` is dropped.
    """
    entries: dict[str, str] = {}
    marks = list(TERM_DEF_RE.finditer(text))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        heading = re.search(r"^#", text[mark.end():end], re.M)
        if heading:
            end = mark.end() + heading.start()
        lines = [line for line in text[mark.end():end].splitlines()
                 if not line.startswith("_Avoid_:")]
        entries[mark.group(1).strip()] = "\n".join(lines).strip()
    return entries


def id_count(files: list[tuple[str, str, str]]) -> int:
    return sum(len(rule_headings(text)[0]) for _, _, text in files)


class RuleHeadingTest(unittest.TestCase):
    def test_an_id_heading_is_read(self):
        self.assertEqual(
            rule_headings("# T\n\nintro\n\n### B1. Defense in depth\n\nbody\n"),
            ([("B", 1, 5)], []))

    def test_a_heading_without_an_id_is_a_problem(self):
        problems = rule_headings("# T\n\n### Defense in depth\n")[1]
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("line 3:"))

    def test_other_heading_levels_are_problems(self):
        for heading in ("## B1. x", "#### B1. x", "# Second title"):
            with self.subTest(heading=heading):
                self.assertEqual(len(rule_headings(f"# T\n{heading}\n")[1]), 1)

    def test_two_ids_no_id_and_a_wrong_level_have_their_own_reasons(self):
        texts = ("# T\n### B1. B2. x\n", "# T\n### Defense in depth\n", "# T\n## B1. x\n")
        self.assertEqual([rule_headings(text)[1] for text in texts], [
            ["line 2: more than one id: ### B1. B2. x"],
            ["line 2: no well-formed id: ### Defense in depth"],
            ["line 2: a rule heading is ###: ## B1. x"]])

    def test_a_malformed_id_is_a_problem(self):
        for heading in ("### B01. x", "### b1. x", "### B1 x", "### B1. B2. x",
                        "### B1. Defense in depth — B2. Production-grade by default",
                        "### B1. a — B02. b"):
            with self.subTest(heading=heading):
                ids, problems = rule_headings(f"# T\n{heading}\n")
                self.assertEqual(len(problems), 1)
                self.assertEqual(ids, [])

    def test_a_rule_heading_with_no_body_is_a_problem(self):
        problems = layer_problems([("python", "PY", "# P\n### PY1. a\n\n### PY2. b\nbody\n")])
        self.assertEqual(len(problems), 1)
        self.assertIn("PY1", problems[0])

    def test_a_fenced_line_is_neither_a_heading_nor_an_item(self):
        text = "# T\n```sh\n# comment\n1. step\n```\n### B1. x\n"
        self.assertEqual(rule_headings(text)[1], [])
        self.assertEqual(numbered_items(text), [])

    def test_an_indented_heading_is_read_and_a_code_block_line_is_not(self):
        self.assertEqual(len(rule_headings("# T\n ### Missing ID\n")[1]), 1)
        self.assertEqual(len(rule_headings("# T\n   ### Missing ID\n")[1]), 1)
        self.assertEqual(rule_headings("# T\n    ### Missing ID\n"), ([], []))

    def test_a_heading_in_a_blockquote_or_a_list_item_is_read(self):
        for line in ("> ### Missing ID", "- ### Missing ID", "* ### Missing ID", "1. ### Missing ID",
                     "> > ### Missing ID", "  - ### Missing ID", ">### Missing ID"):
            with self.subTest(line=line):
                self.assertEqual(len(rule_headings(f"# T\n{line}\n")[1]), 1)
        self.assertEqual(rule_headings("# T\n> quoted prose # not a heading\n- item\n"), ([], []))

    def test_an_html_comment_block_hides_its_lines(self):
        text = "# T\n<!--\n### P1. x\nbody [a](../x.md)\n-->\n### P2. y\nbody\n"
        self.assertEqual(set(sections(text)), {"P2"})
        self.assertEqual(rule_headings(text)[0], [("P", 2, 6)])
        self.assertEqual(numbered_items("# T\n<!--\n1. step\n-->\n2. one\n"), [5])
        one_line = "# T\n<!-- ### P1. x -->\n### P2. y\nbody\n"
        self.assertEqual(set(sections(one_line)), {"P2"})
        fenced = "# T\n<!--\n```\n-->\n### P1. x\nbody\n```\n"
        self.assertEqual(sections(fenced), {"P1": "body\n"})

    def test_a_tilde_fence_hides_its_lines(self):
        text = "# T\n~~~md\n### P1. x\nbody\n~~~\n### P2. y\nbody\n"
        self.assertEqual(set(sections(text)), {"P2"})
        self.assertEqual(rule_headings(text)[0], [("P", 2, 6)])
        self.assertEqual(numbered_items("# T\n~~~\n1. step\n~~~\n"), [])

    def test_a_heading_on_a_list_item_continuation_line_is_read(self):
        for text in ("# T\n- a\n  - b\n\n    ### Missing ID\n", "# T\n- a\n\n  ### Missing ID\n",
                     "# T\n1. a\n\n   ### Missing ID\n", "# T\n- a\n  - b\n    - c\n\n      ### Missing ID\n",
                     "# T\n- a\n\n     ### Missing ID\n"):
            with self.subTest(text=text):
                self.assertEqual(len(rule_headings(text)[1]), 1)
        for text in ("# T\n- a\n\n      ### code in the item\n", "# T\n- a\n\n### P1. x\nbody\n",
                     "# T\n- a\n  - b\n\n  ### P1. x\nbody\n"):
            with self.subTest(text=text):
                self.assertEqual(rule_headings(text)[1], [])
        self.assertEqual(rule_headings("# T\n- a\n\n  ### P1. x\n  body\n")[0], [("P", 1, 4)])
        self.assertEqual(rule_headings("# T\n- a\n  ```\n  ### x\n  ```\n")[1], [])
        self.assertEqual(rule_headings("# T\n* * *\n\n    ### code\n"), ([], []))

    def test_a_fence_or_html_block_on_a_list_marker_line_hides_its_lines(self):
        for text in ("# T\n- ```\n  ### P1. x\n  body\n  ```\n", "# T\n1. ```\n   ### P1. x\n   body\n   ```\n",
                     "# T\n- <div>\n  ### P1. x\n  body\n", "# T\n- - ```\n    ### P1. x\n    ```\n"):
            with self.subTest(text=text):
                self.assertEqual(rule_headings(text), ([], []))
        text = "# T\n- ```\n  ### P1. x\n  ```\n\n### P2. y\nbody\n"
        self.assertEqual(rule_headings(text)[0], [("P", 2, 6)])

    def test_a_marker_that_cannot_interrupt_a_paragraph_opens_nothing(self):
        for text in ("# T\ntext\n2. ```\n   ### Missing\n", "# T\ntext\n2. <div>\n   ### Missing\n",
                     "# T\n- a\n  text\n  2. ```\n     ### Missing\n"):
            with self.subTest(text=text):
                self.assertEqual(len(rule_headings(text)[1]), 1)
        for text in ("# T\ntext\n1. ```\n   ### P1. x\n   ```\n", "# T\n1. a\n2. ```\n   ### P1. x\n   ```\n",
                     "# T\n\n2. ```\n   ### P1. x\n   ```\n"):
            with self.subTest(text=text):
                self.assertEqual(rule_headings(text), ([], []))

    def test_a_list_item_ends_over_an_open_fence_or_html_block(self):
        for text in ("# T\n- a\n  ```\nfoo\n### Missing\n", "# T\n- a\n  <!--\nfoo\n### Missing\n",
                     "# T\n- a\n  <div>\nfoo\n### Missing\n"):
            with self.subTest(text=text):
                self.assertEqual(len(rule_headings(text)[1]), 1)
        self.assertEqual(rule_headings("# T\n- a\n  ```\n  ### x\n\n  ```\n"), ([], []))

    def test_an_html_block_hides_its_lines(self):
        for opener, closer in (("<div>", "</div>"), ("<details>", "</details>"), ("<pre>", "</pre>"),
                               ("<DIV class=x>", "</DIV>"), ("<table>", "</table>"), ("</div>", ""),
                               ("<script>", "</script>"), ("<style>", "</style>"),
                               ("<textarea>", "</textarea>"), ("<?php", "?>"), ("<!DOCTYPE html", ">"),
                               ("<![CDATA[", "]]>"), ("<custom-tag>", ""), ("  <p>", "")):
            with self.subTest(opener=opener):
                text = f"# T\n{opener}\n### P1. x\nbody [a](../x.md)\n{closer}\n\n### P2. y\nbody\n"
                self.assertEqual(set(sections(text)), {"P2"})
                self.assertEqual(rule_headings(text)[0], [("P", 2, 7)])
                self.assertEqual(numbered_items(f"# T\n{opener}\n1. step\n{closer}\n\n2. one\n"), [6])

    def test_an_html_block_ends_where_commonmark_ends_it(self):
        one_line = "# T\n<pre>x</pre>\n### P1. x\nbody\n"
        self.assertEqual(set(sections(one_line)), {"P1"})
        after_blank = "# T\n<div>\nx\n\n### P1. x\nbody\n"
        self.assertEqual(set(sections(after_blank)), {"P1"})
        pre_runs_on = "# T\n<pre>\n\n### P1. x\nbody\n</pre>\n### P2. y\nbody\n"
        self.assertEqual(set(sections(pre_runs_on)), {"P2"})
        self.assertEqual(set(sections("# T\ntext\n<span>\n### P1. x\nbody\n")), {"P1"})
        self.assertEqual(set(sections("# T\n<span>x</span> y\n### P1. x\nbody\n")), {"P1"})
        self.assertEqual(set(sections("# T\n    <div>\n### P1. x\nbody\n")), {"P1"})
        self.assertEqual(set(sections("# T\ntext\n<divx>\n### P1. x\nbody\n")), {"P1"})

    def test_a_link_in_a_code_span_is_no_destination(self):
        self.assertEqual(link_destinations("a `[d](https://x/y)` b"), [])

    def test_numbered_items_are_found(self):
        self.assertEqual(numbered_items("# T\n\n1. **A.** a\n\n2. **B.** b\n"), [3, 5])

    def test_sections_split_at_every_heading(self):
        self.assertEqual(sections("# T\n### B1. a\none\n### B2. b\ntwo\n"),
                         {"B1": "one\n", "B2": "two\n"})

    def test_link_destinations_are_parsed(self):
        self.assertEqual(
            link_destinations("a ([d](https://x/issues/14170)) and [e](https://x/y)"),
            ["https://x/issues/14170", "https://x/y"])

    def test_a_duplicate_id_in_a_layer_is_a_problem(self):
        problems = layer_problems([("a", "P", "# A\n### P1. x\nbody\n"),
                                   ("b", "P", "# B\n### P1. y\nbody\n")])
        self.assertEqual(len(problems), 1)
        self.assertIn("P1", problems[0])

    def test_one_number_under_two_stack_prefixes_is_no_duplicate(self):
        self.assertEqual(
            layer_problems([("python", "PY", "# P\n### PY1. a\nbody\n"),
                            ("node", "NODE", "# N\n### NODE1. a\nbody\n")]),
            [])

    def test_a_wrong_prefix_or_an_empty_file_is_a_problem(self):
        self.assertEqual(
            len(layer_problems([("python", "PY", "# P\n### NET1. x\nbody\n")])), 1)
        self.assertEqual(len(layer_problems([("python", "PY", "# P\n\ntext\n")])), 1)

    def test_the_prefix_table_is_read(self):
        text = ("# S\n\n## Rule ids\n\n| Layer file | Prefix |\n|---|---|\n"
                "| `the-bar.md` | `B` |\n| the repo's `docs/standards/` shards | `P` |\n\n## Next\n")
        self.assertEqual(prefix_table(text), {"the-bar.md": "B", "docs/standards/": "P"})


class LiveStandardsTest(unittest.TestCase):
    def test_the_readme_names_one_prefix_per_layer_file(self):
        table = prefix_table(README.read_text())
        self.assertEqual(
            set(table),
            {"the-bar.md", "docs/standards/"}
            | {f"stacks/{path.name}" for path in (GLOBAL / "stacks").glob("*.md")})
        self.assertEqual(len(set(table.values())), len(table))
        self.assertEqual(table["the-bar.md"], "B")
        self.assertEqual(table["docs/standards/"], "P")
        self.assertEqual(table["stacks/python.md"], "PY")
        self.assertEqual(table["stacks/dotnet.md"], "NET")

    def test_every_rule_heading_in_the_three_layers_carries_one_id(self):
        bar, stacks, project = layer_files()
        self.assertEqual(layer_problems(bar) + layer_problems(stacks) + layer_problems(project), [])
        self.assertGreaterEqual(id_count(bar), 15)
        self.assertGreaterEqual(id_count(stacks), 32)
        self.assertGreaterEqual(id_count(project), 13)

    def test_every_project_rule_is_a_heading_with_a_p_id(self):
        found: set[str] = set()
        bodies: dict[str, str] = {}
        for path in sorted(PROJECT.glob("*.md")):
            if path.name == "README.md":
                continue
            text = path.read_text()
            self.assertEqual(numbered_items(text), [], path.name)
            found |= set(sections(text))
            bodies |= sections(text)
        wanted = {f"P{n}" for n in range(1, 14)}
        self.assertLessEqual(wanted, found)
        for name in sorted(wanted):
            with self.subTest(rule=name):
                self.assertRegex(bodies[name], r"\]\([^)\s]+\)")
        helpers = sections((PROJECT / "agent-helpers.md").read_text())
        guard = "home/common/claude-code/lifecycle_guard.py"
        self.assertIn(guard, helpers["P8"])
        self.assertEqual([name for name, body in helpers.items() if guard in body], ["P8"])

    def test_the_bar_holds_the_test_run_isolation_rule(self):
        link = "https://github.com/fagenorn/nix-config/issues/1417"
        found = {name: body for name, body in sections(BAR.read_text()).items()
                 if link in link_destinations(body)}
        self.assertEqual(list(found), ["B16"])
        self.assertEqual(link_destinations(found["B16"]), [link])
        for clause in ("creates what it uses", "removes it when it ends",
                       "takes no fixed port", "leaves nothing behind"):
            with self.subTest(clause=clause):
                self.assertIn(clause, found["B16"])
        prose = re.sub(r"\(?\[[^\]]*\]\([^)]*\)\)?", "", found["B16"])
        self.assertIn(len(re.findall(r"[.!?](?:\s|$)", prose)), (1, 2))


class GlossaryTest(unittest.TestCase):
    def test_glossary_entries_drop_the_avoid_line(self):
        self.assertEqual(
            glossary_entries("**A**:\nDef a.\n_Avoid_: x\n\n**B**:\n_Avoid_: y\n\n## Next\n"),
            {"A": "Def a.", "B": ""})

    def test_the_delivery_glossary_defines_the_three_terms(self):
        terms = {"Standard", "Enforcer", "Judged rule"}
        glossary = (REPO_ROOT / "docs/areas/delivery/CONTEXT.md").read_text()
        entries = glossary_entries(glossary)
        map_text = (REPO_ROOT / "docs/CONTEXT-MAP.md").read_text()
        rows = [row[:2] for row in table_rows(section(map_text, "Terms"))]
        self.assertLessEqual(terms, {t.strip() for t in TERM_DEF_RE.findall(glossary)})
        for term in sorted(terms):
            with self.subTest(term=term):
                self.assertTrue(entries[term])
                self.assertEqual(rows.count([term, "Delivery"]), 1)
        self.assertLessEqual(len(map_text.splitlines()), MAP_BUDGET)


if __name__ == "__main__":
    unittest.main()
