# Task 1: The `skill-sections` command

Spec § Solution 1, § Decisions "The helper", § Test seams 1 and 4. Rests on D1, D2, D3 and D11. After this task, `skill-sections [--opening] <file> <section>...` is an `agent_tools` command with a launcher, a contract test file in `just agent-workflow-tests`, and a `## skill-sections` section in `python/README.md`. No skill text changes in this task.

**Files:**
- Create: `python/agent_tools/skill_sections.py`
- Create: `tests/test_skill_sections.py`
- Modify: `lib/agent-tools.nix` (one `commands` row)
- Modify: `justfile` (one `agent-workflow-tests` member)
- Modify: `python/README.md` (one new section)

**Interfaces:**
- Consumes: nothing from another task. Standard library only (`argparse`, `dataclasses`, `json`, `re`, `sys`, `pathlib`).
- Produces (Task 2 runs the command as `python -m agent_tools.skill_sections` and imports nothing):
  - `@dataclass(frozen=True) class Section`: `heading: str`, `text: str`.
  - `@dataclass(frozen=True) class Document`: `opening: str`, `sections: tuple[Section, ...]`.
  - `@dataclass(frozen=True) class Problem`: `name: str`, `kind: str` (`"unknown"` or `"ambiguous"`), `candidates: tuple[str, ...]`.
  - `class Unresolved(Exception)` with attribute `problems: tuple[Problem, ...]`.
  - `parse(text: str) -> Document`
  - `resolve(document: Document, names: Sequence[str]) -> tuple[Section, ...]`, raising `Unresolved`.
  - `main(argv: list[str] | None = None) -> int`, with `build_parser()` whose `prog` is `skill-sections`.
  - Command table row `skill-sections`, so the launcher is `~/.agents/bin/skill-sections`.

**Invariants:**
- For every document, `opening` plus every section's `text`, plus the lines that follow a level-1 heading after the first section, is the document, with nothing reordered or rewritten.
- Nothing reaches stdout unless every name resolves. On exit 2, stdout is empty.
- Each selected section is printed once, in file order, whatever the order or repetition of the names.
- Output bytes equal the file's bytes for the printed slices (CRLF, em dashes and a missing final newline included).

- [ ] **Step 1: Write the failing test**

Create `tests/test_skill_sections.py` with exactly this content:

```python
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
        for separator in (" ", "\x0c", "\r"):
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
```

- [ ] **Step 2: Run the test and watch it fail**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_skill_sections.py 2>&1 | tail -20'`
Expected: `FAILED (errors=1)`, the error being `ModuleNotFoundError: No module named 'agent_tools.skill_sections'`. Keep this output for Task 2's acceptance record.

- [ ] **Step 3: Write the minimal implementation**

Create `python/agent_tools/skill_sections.py`, a thin shell over `parse` and `resolve` (agent-helpers rule 2), standard library only. Its docstring and comments say what the code does at this commit and cite "issue 505 Dn", never a bare `Dn`; no `TODO`.

`parse(text)`:
1. Split `text` into lines after each `\n` only, never with `str.splitlines` (D11). The last line may lack a `\n`; an empty remainder after a final `\n` is no line. For each line, `body` is the line without its trailing `\n`.
2. Keep the fence state: `None`, or the fence character and its run length.
   - Inside a fence: the line closes it when `body` with one trailing `\r` removed fully matches `` ` {0,3}(`{3,}|~{3,})[ \t]*` ``, the run's character is the fence's and the run is at least as long. The line stays in the current part either way.
   - Outside a fence: when `body` matches `` ` {0,3}(`{3,}|~{3,})` `` at its start, whatever follows, it opens a fence of that character and run length. Otherwise, when `body` starts with `## `, it starts a new section whose heading is `body[3:].strip()`. Otherwise, when it starts with `# ` and a section already exists, it ends the current section, and it and the lines up to the next section belong to no part. Before the first section, a `# ` line stays in the opening.
3. Every other line joins the current part (the opening, the current section, or no part). `Document.opening` is the opening's lines joined, and each `Section.text` is its lines joined, the heading line first.

`resolve(document, names)`:
1. Visit each distinct name once, in argument order. Its exact matches are the sections whose heading equals it. With none, its prefix matches are the sections whose heading starts with it, is longer, and whose character right after the name is not `str.isalnum()`.
2. One match selects that section. More than one is `Problem(name, "ambiguous", <the matches' headings in file order>)`. None is `Problem(name, "unknown", ())`.
3. Any problem raises `Unresolved(tuple(problems))`, problems in argument order. Otherwise return the selected sections in file order, each once.

`main(argv)`:
1. `build_parser()`: `argparse.ArgumentParser(prog="skill-sections")` with `--opening` (`store_true`), the positional `file`, and the positional `section` with `nargs="+"`. A missing file or section is argparse's usage error, exit 2.
2. An empty name is `parser.error("a section name is empty")`, exit 2.
3. Read `Path(file).read_bytes()` and decode it with `decode("utf-8")`. An `OSError` writes `skill-sections: cannot read <file>: <error.strerror or error>` and exits 2. A `UnicodeDecodeError` writes `skill-sections: <file> is not UTF-8` and exits 2. `<file>` is the argument as given.
4. On `Unresolved`, write the report (D11) to stderr and exit 2. The report is one line per problem: `skill-sections: unknown section <q(name)>`, or `skill-sections: ambiguous section <q(name)> matches <q(candidate)>, <q(candidate)>…` with the candidates joined by `", "`. Then `skill-sections: the ## headings of <file>:`, then `## <heading>` for each section in file order. Every line ends in `\n`, and `q` is `json.dumps(value, ensure_ascii=False)`.
5. Otherwise build the opening (only with `--opening`) followed by each selected section's text, then write `output.encode("utf-8")` to `sys.stdout.buffer` and flush it (D11). Return 0. End the module with `if __name__ == "__main__": sys.exit(main())`.

Wire the command:
- `lib/agent-tools.nix`: add the row `"skill-sections"` to `commands` right after `"skill-lint"`. The table stays alphabetical.
- `justfile`: in `agent-workflow-tests`, add the member line `    tests/test_skill_sections.py \` right after `    tests/test_lane_triage.py \`.
- `python/README.md`: insert this section, followed by one blank line, before the line `` ## `agent-workflow-tests` runner ``. Every sentence must stay true of the code at this commit. Where one is not, rewrite the sentence from the code; never let it describe intended behaviour:

```markdown
## `skill-sections`

`skill-sections [--opening] <file> <section>...` (issue 505; source entry `python -m agent_tools.skill_sections`) prints named `##` sections of a Markdown skill file and writes no file. Outside a fenced code block, a line starting `## ` is a level-2 heading and a line starting `# ` a level-1 heading. A fence opens on a line indented at most three spaces that starts with three or more backticks or tildes, and closes on a line indented at most three spaces holding only a run of the same character at least as long, then whitespace; an unclosed fence runs to the end of the file. A section is its heading line and every line after it up to the next level-1 or level-2 heading or the end of the file, so a `###` heading stays inside it, and the opening is everything before the first level-2 heading, frontmatter included. A heading's text is the rest of its line after `## `, stripped. A name selects the one heading whose text equals it; with none, the one heading whose text starts with the name followed by a character that is not a letter or digit, so `Phase 6` selects `Phase 6 — Execute` and never `Phase 60`. A name that selects nothing is unknown, and one with two exact matches, or no exact match and two prefix matches, is ambiguous. Every name is resolved before anything is printed. On success the command writes to stdout the opening (with `--opening`) and then each selected section once, in file order, as the file's own bytes, and exits 0. Any unknown or ambiguous name exits 2 with nothing on stdout and one stderr report: a line per unresolved name, in argument order, `skill-sections: unknown section "<name>"` or `skill-sections: ambiguous section "<name>" matches "<heading>", "<heading>"…`, with each value JSON-quoted, then `skill-sections: the ## headings of <file>:` and a `## <heading>` line for each heading in file order. A file it cannot read (`skill-sections: cannot read <file>: <reason>`) or decode as UTF-8 (`skill-sections: <file> is not UTF-8`), no section argument, and an empty name also exit 2 with nothing on stdout.
```

The section names no caller: Task 2 points `home/common/agent-skills/README.md` at the command when the resume entry starts running it.

- [ ] **Step 4: Verify**

1. Run the Step 2 command. Expected: `Ran 18 tests` and `OK`.
2. Run `git add python/agent_tools/skill_sections.py tests/test_skill_sections.py` before building: the flake reads only files git tracks, so an unstaged new module fails the launcher's module assertion.
3. Run (timeout 3600 s, about 80 s warm): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`. Expected: exit 0.
4. Smoke-test the built launcher (timeout 60 s):
   ```bash
   bash -c 'hm=$(nix-store --query --requisites ./result | grep -- "-home-manager-files$") && "$hm/.agents/bin/skill-sections" home/common/agent-skills/skills/from-issue/SKILL.md "Phase 6" | head -1'
   ```
   Expected: `## Phase 6 — Execute`. A missing launcher or another first line means the row or the module is wrong.
5. Run `if grep -n "TODO\|FIXME" python/agent_tools/skill_sections.py tests/test_skill_sections.py; then exit 1; fi`. Expected: exit 0, no output.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/skill_sections.py tests/test_skill_sections.py lib/agent-tools.nix justfile python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(agent-tools): add skill-sections for issue 505" -m "Co-Authored-By: <session trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":1,"records":[{"bounds":[{"added_lines":220,"boundary":"all","deleted_lines":0,"record_bytes":10240,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r1a","last_task":1,"owner":1,"path":"python/agent_tools/skill_sections.py"},{"bounds":[{"added_lines":240,"boundary":"all","deleted_lines":0,"record_bytes":12288,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r1b","last_task":1,"owner":1,"path":"tests/test_skill_sections.py"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":1,"record_bytes":2048,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1c","last_task":1,"owner":1,"path":"lib/agent-tools.nix"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":1,"record_bytes":2048,"support":{"covers":["r1d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1d","last_task":1,"owner":1,"path":"justfile"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":2,"record_bytes":16384,"support":{"covers":["r1e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1e","last_task":1,"owner":1,"path":"python/README.md"}]}}
```
