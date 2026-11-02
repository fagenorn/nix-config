"""Contract tests for `skill-sections` (`agent_tools.skill_sections`, issue 505).

The command runs as `python -m agent_tools.skill_sections` under the caller's
`PYTHONPATH` (agent-helpers rule 5), over a fixture shaped like a skill file:
frontmatter, a level-1 title, `###` subsections, and `##` lines inside backtick
and tilde fences. Structural cases import `parse` and `resolve`.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.skill_sections import Document, Section, Unresolved, parse, resolve

OPENING = (
    "---\n"
    "name: demo\n"
    "description: A fixture shaped like a skill file.\n"
    "---\n"
    "\n"
    "# Demo\n"
    "\n"
    "Opening prose.\n"
    "\n"
)
INDEX = (
    "## Files beside this one\n"
    "- **`phase.md`** — Phase 6.\n"
    "\n"
)
PHASE_6 = (
    "## Phase 6 — Execute\n"
    "Run the plan.\n"
    "\n"
    "### Detail\n"
    "A subsection stays inside its section.\n"
    "\n"
    "````markdown\n"
    "```python\n"
    "## A template heading under a four-backtick fence\n"
    "```\n"
    "## A shorter backtick line did not close the fence\n"
    "````\n"
    "\n"
)
PHASE_60 = (
    "## Phase 60 — Later\n"
    "   ~~~text\n"
    "## A template heading under a tilde fence\n"
    "```\n"
    "## A backtick line does not close a tilde fence\n"
    "~~~\n"
    "\n"
)
NOTES = (
    "## Notes\n"
    "    ```\n"
    "Four spaces of indent open no fence.\n"
    "\n"
)
APPENDIX = (
    "# Appendix\n"
    "Text after a level-1 heading belongs to no section.\n"
    "\n"
)
TAIL = (
    "## Tail\n"
    "````\n"
    "## An unclosed fence runs to the end of the file\n"
    "no trailing newline"
)
DOCUMENT = OPENING + INDEX + PHASE_6 + PHASE_60 + NOTES + APPENDIX + TAIL
HEADINGS = ["Files beside this one", "Phase 6 — Execute", "Phase 60 — Later", "Notes", "Tail"]


class SkillSectionsCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.skill = self.write("SKILL.md", DOCUMENT.encode("utf-8"))

    def write(self, name: str, data: bytes) -> Path:
        path = self.directory / name
        path.write_bytes(data)
        return path

    def run_command(self, *argv: object) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "agent_tools.skill_sections", *map(str, argv)],
                              capture_output=True, timeout=60, check=False)

    def assert_prints(self, expected: bytes, *argv: object) -> None:
        result = self.run_command(*argv)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout, expected)
        self.assertEqual(result.stderr, b"")

    def assert_refuses(self, *argv: object) -> str:
        result = self.run_command(*argv)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertTrue(result.stderr)
        return result.stderr.decode("utf-8")

    def test_prints_the_named_sections_in_file_order_each_once(self):
        self.assert_prints((INDEX + NOTES).encode("utf-8"),
                           self.skill, "Notes", "Files beside this one", "Notes")

    def test_opening_prints_the_text_before_the_first_level_2_heading_first(self):
        self.assert_prints((OPENING + INDEX + PHASE_6).encode("utf-8"),
                           "--opening", self.skill, "Phase 6", "Files beside this one")

    def test_a_fenced_level_2_line_never_splits_a_section(self):
        self.assert_prints((PHASE_6 + PHASE_60).encode("utf-8"),
                           self.skill, "Phase 60 — Later", "Phase 6 — Execute")

    def test_a_level_1_heading_ends_a_section_and_an_unclosed_fence_runs_to_the_end(self):
        self.assert_prints((NOTES + TAIL).encode("utf-8"), self.skill, "Tail", "Notes")

    def test_a_short_name_selects_the_heading_it_prefixes_at_a_word_boundary(self):
        self.assert_prints(PHASE_6.encode("utf-8"), self.skill, "Phase 6")
        self.assert_prints(PHASE_60.encode("utf-8"), self.skill, "Phase 60")

    def test_section_bytes_are_printed_unchanged(self):
        crlf = self.write("crlf.md", b"## A\r\none\r\n## B  \r\ntwo\r\n")
        self.assert_prints(b"## B  \r\ntwo\r\n", crlf, "B")

    def test_unresolved_names_print_nothing_and_one_report_lists_the_headings(self):
        stderr = self.assert_refuses(self.skill, "Notes", "Phase", "Missing", "Phase", "Phase 7")
        self.assertEqual(stderr, (
            'skill-sections: ambiguous section "Phase" matches "Phase 6 — Execute", "Phase 60 — Later"\n'
            'skill-sections: unknown section "Missing"\n'
            'skill-sections: unknown section "Phase 7"\n'
            f"skill-sections: the ## headings of {self.skill}:\n"
            + "".join(f"## {heading}\n" for heading in HEADINGS)))

    def test_a_file_it_cannot_read_or_decode_exits_2(self):
        missing = self.directory / "missing.md"
        self.assertIn(f"skill-sections: cannot read {missing}: ", self.assert_refuses(missing, "Notes"))
        latin = self.write("latin.md", b"## Caf\xe9\n")
        self.assertEqual(self.assert_refuses(latin, "Caf"), f"skill-sections: {latin} is not UTF-8\n")

    def test_usage_errors_exit_2(self):
        self.assert_refuses(self.skill)
        self.assert_refuses("--opening", self.skill)
        self.assertIn("a section name is empty", self.assert_refuses(self.skill, "Notes", ""))


class ParseTest(unittest.TestCase):
    def test_a_document_is_its_opening_and_its_ordered_sections(self):
        self.assertEqual(parse(DOCUMENT), Document(OPENING, tuple(
            Section(heading, text) for heading, text in zip(HEADINGS, (INDEX, PHASE_6, PHASE_60, NOTES, TAIL)))))

    def test_a_document_without_level_2_headings_is_all_opening(self):
        self.assertEqual(parse("# Title\n\n### Sub\nBody\n"), Document("# Title\n\n### Sub\nBody\n", ()))

    def test_a_heading_text_is_the_rest_of_its_line_stripped(self):
        self.assertEqual([section.heading for section in parse("##   Spaced  out \r\n##\tTab\n").sections],
                         ["Spaced  out"])

    def test_only_a_line_feed_ends_a_line(self):
        for separator in (" ", "\x0c", "\r"):
            with self.subTest(separator=repr(separator)):
                text = f"## A\nbody{separator}## Ghost\n"
                self.assertEqual(parse(text), Document("", (Section("A", text),)))


class ResolveTest(unittest.TestCase):
    DOCUMENT = parse("## Notes\n## Notes on fences\n## Phase 6 — Execute\n## Phase 60 — Later\n"
                     "## Twice\n## Twice\n")

    def headings(self, *names: str) -> list[str]:
        return [section.heading for section in resolve(self.DOCUMENT, names)]

    def problems(self, *names: str) -> list[tuple]:
        with self.assertRaises(Unresolved) as raised:
            resolve(self.DOCUMENT, names)
        return [(problem.name, problem.kind, problem.candidates) for problem in raised.exception.problems]

    def test_an_exact_match_wins_over_a_prefix_match(self):
        self.assertEqual(self.headings("Notes"), ["Notes"])

    def test_a_prefix_selects_only_at_a_boundary_that_is_not_a_letter_or_digit(self):
        self.assertEqual(self.headings("Phase 6"), ["Phase 6 — Execute"])
        self.assertEqual(self.headings("Notes on"), ["Notes on fences"])
        self.assertEqual(self.problems("Note"), [("Note", "unknown", ())])

    def test_two_prefix_matches_or_two_exact_matches_are_ambiguous(self):
        self.assertEqual(self.problems("Phase", "Twice"), [
            ("Phase", "ambiguous", ("Phase 6 — Execute", "Phase 60 — Later")),
            ("Twice", "ambiguous", ("Twice", "Twice"))])

    def test_selection_is_in_file_order_with_each_section_once(self):
        self.assertEqual(self.headings("Phase 60", "Notes", "Phase 60"), ["Notes", "Phase 60 — Later"])

    def test_every_unresolved_name_is_reported_once_in_argument_order(self):
        self.assertEqual(self.problems("Zed", "Notes", "Phase", "Zed"), [
            ("Zed", "unknown", ()),
            ("Phase", "ambiguous", ("Phase 6 — Execute", "Phase 60 — Later"))])


if __name__ == "__main__":
    unittest.main()
