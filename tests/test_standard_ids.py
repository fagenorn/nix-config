"""Every rule heading of the three standards layers carries one stable id (#1438).

Measures acceptance criterion 1 (each rule of the bar, the stack shards and the
project shards is one `###` heading opening with one well-formed id, and the
standards README names one prefix per layer file) and criterion 2 (every
project rule is a heading with a `P` id, none a numbered list item).
"""

import re
import unittest
from pathlib import Path

from agent_tools.delivery.context_map_lint import CODE_RE, section, table_rows
from agent_tools.delivery.rule_ids import RULE_ID_HEADING

REPO_ROOT = Path(__file__).resolve().parents[1]
GLOBAL = REPO_ROOT / "home/common/agent-skills/standards"
BAR = GLOBAL / "the-bar.md"
README = GLOBAL / "README.md"
PROJECT = REPO_ROOT / "docs/standards"

SECOND_ID = re.compile(r"(?<![A-Za-z0-9])[A-Z]+[0-9]+\.(?=\s|$)")
HEADING_LINE = re.compile(r"^#{1,6}(\s|$)")
NUMBERED_ITEM = re.compile(r"^[0-9]+\. ")


def unfenced(text: str):
    """`(line number, line)` of every line outside a ``` fence, fence lines excluded."""
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            yield number, line


def rule_match(line: str):
    """The id match of a well-formed rule heading, else None."""
    found = RULE_ID_HEADING.match(line)
    if found and found["hashes"] == "###" and not SECOND_ID.search(found["title"]):
        return found
    return None


def rule_headings(text: str) -> tuple[list[tuple[str, int, int]], list[str]]:
    ids: list[tuple[str, int, int]] = []
    problems: list[str] = []
    seen_heading = False
    for number, line in unfenced(text):
        if not HEADING_LINE.match(line):
            continue
        first, seen_heading = not seen_heading, True
        if first and line.startswith("# "):
            continue
        found = rule_match(line)
        if found:
            ids.append((found["prefix"], int(found["number"]), number))
        else:
            reason = "not a rule heading with one well-formed id"
            problems.append(f"line {number}: {reason}: {line}")
    return ids, problems


def sections(text: str) -> dict[str, str]:
    """Rule id to the body between its heading and the next heading of any level."""
    bodies: dict[str, list[str]] = {}
    current = None
    for _, line in unfenced(text):
        if HEADING_LINE.match(line):
            found = rule_match(line)
            current = f"{found['prefix']}{found['number']}" if found else None
            if current:
                bodies[current] = []
        elif current:
            bodies[current].append(line)
    return {key: "".join(f"{line}\n" for line in lines) for key, lines in bodies.items()}


def link_destinations(body: str) -> list[str]:
    return re.findall(r"\]\(([^)\s]+)\)", body)


def numbered_items(text: str) -> list[int]:
    return [number for number, line in unfenced(text) if NUMBERED_ITEM.match(line)]


def layer_problems(files: list[tuple[str, str, str]]) -> list[str]:
    problems: list[str] = []
    seen: dict[tuple[str, int], str] = {}
    for label, expected, text in files:
        ids, bad = rule_headings(text)
        problems += [f"{label}: {problem}" for problem in bad]
        if not ids and not bad:
            problems.append(f"{label}: no rule heading")
        for prefix, number, line in ids:
            name = f"{prefix}{number}"
            if prefix != expected:
                problems.append(f"{label}: line {line}: {name} should carry the prefix {expected}")
            if (prefix, number) in seen:
                problems.append(f"{label}: line {line}: {name} repeats the id in {seen[(prefix, number)]}")
            seen.setdefault((prefix, number), label)
        for name, body in sections(text).items():
            if not body.strip():
                problems.append(f"{label}: {name} has no body")
    return problems


def prefix_table(readme_text: str) -> dict[str, str]:
    table: dict[str, str] = {}
    for cells in table_rows(section(readme_text, "Rule ids")):
        keys, values = CODE_RE.findall(cells[0]), CODE_RE.findall(cells[1])
        if keys and values:
            table[keys[0]] = values[0]
    return table


def layer_files() -> tuple[list, list, list]:
    table = prefix_table(README.read_text())
    bar = [("the-bar.md", table["the-bar.md"], BAR.read_text())]
    stacks = [(f"stacks/{path.name}", table[f"stacks/{path.name}"], path.read_text())
              for path in sorted((GLOBAL / "stacks").glob("*.md"))]
    project = [(f"docs/standards/{path.name}", table["docs/standards/"], path.read_text())
               for path in sorted(PROJECT.glob("*.md")) if path.name != "README.md"]
    return bar, stacks, project


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


if __name__ == "__main__":
    unittest.main()
