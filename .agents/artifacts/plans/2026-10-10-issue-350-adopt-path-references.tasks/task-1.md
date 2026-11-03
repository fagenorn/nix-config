# Task 1: `adopt_references` — tokens, occurrences, successors, shapes and edits

**Files:**
- Create: `python/agent_tools/adopt_references.py`
- Modify: `python/agent_tools/adopt_links.py` (rename `_directory_successor` to `directory_successor`: its `def` and its one caller in `_successor`; nothing else)
- Modify: `justfile` (in the `agent-workflow-tests` recipe's file list, add the line `    home/common/agent-skills/tests/test_adopt_references.py \` directly after the `test_adopt_links.py` line)
- Test: `home/common/agent-skills/tests/test_adopt_references.py` (new)

**Interfaces:**
- Consumes: `adopt_links.Tree(paths)` (`.paths`, `.directories`), `adopt_links.is_markdown_path(path) -> bool`, `adopt_links.REGULAR_MODES`, `adopt_links.directory_successor(directory: str, base: Tree, after: Tree, moved: dict[str, str]) -> str | None` (renamed here); `adopt_inspection.tree_records(root, revision) -> list[tuple[path, mode, oid]]`, `blob_at(root, revision, relative) -> bytes | None`, `run_git(root, *args) -> tuple[int, bytes]`, `split_nul`, `is_secret_path`, `refuse`.
- Produces (`agent_tools.adopt_references`):
  - `ANSWERS = ("extend", "rewrite", "retain")`, `TOKEN_DELIMITERS = "\"'`,;:=()<>|&#!"`, `GLOB_CHARACTERS = "*?[{"`, `CARRIED_TAILS = ("", "/", "/**")`, `RECORD_HOMES = (".agents/artifacts/", ".agents/knowledge/archive/")`.
  - `Token` — frozen dataclass `(start: int, end: int, line: int, column: int, text: str)`; `start`/`end` are character offsets into the whole text, `line` and `column` 1-based, the column counted in characters from the line's start.
  - `tokens(text: str) -> list[Token]` — every maximal run of characters `c` with `not c.isspace() and c not in TOKEN_DELIMITERS`, in order; lines break at `\n` only (D3).
  - `split_token(token: str) -> tuple[str, str, str]` — `(prefix, path, tail)`: `prefix` is `"./"` if the token starts with it, else `"/"` if it starts with that, else `""`; `path` is the longest leading run of the remaining `/`-separated segments that are non-empty and hold no `GLOB_CHARACTERS` character, joined by `/`; `tail` is everything after it. `prefix + path + tail == token` always.
  - `successors(path: str, base: Tree, after: Tree, moved: dict[str, str]) -> tuple[bool, list[tuple[str, bool]]]` — `(single, [(successor, is_directory), ...])` (D4).
  - `carried_form(prefix: str, successor: str, is_directory: bool, tail: str, single: bool) -> str | None`.
  - `Occurrence` — frozen dataclass `(path: str, line: int, column: int, start: int, end: int, literal: str, answers: tuple[str, ...], additions: tuple[str, ...], replacement: str | None, shape: str | None)` with the property `subject -> str`, `f"{path}:{line}:{column}"`; `shape` is `"quoted"`, `"line"` or `None`.
  - `References` — frozen dataclass `(texts: dict[str, str], occurrences: tuple[Occurrence, ...])`: the base text of every file holding an occurrence, and the occurrences sorted by `(path, line, column)`.
  - `plan_references(texts: dict[str, str], paths: Iterable[str], moves: Iterable[tuple[str, str]]) -> References` — the pure core.
  - `summary(references: References, answers: dict[str, str]) -> list[dict]` — one row per occurrence in order: `{"subject", "path", "line", "column", "literal", "answers": list, "answer": answers.get(subject), "additions": list, "replacement"}` (D8).
  - `rewritten(references: References, answers: dict[str, str]) -> dict[str, tuple[str, str]]` — `path -> (before, after)` for every file with at least one `extend` or `rewrite` answer; raises `ValueError` for an answer the occurrence does not offer.
  - `derive_references(root: Path, revision: str, moves: Iterable[tuple[str, str]], excluded: Iterable[str]) -> References` — the git reader (D2).

**Invariants:**
- An occurrence is a token for which all hold (D3, D11): it contains `/`, or `start > 0`, `end < len(text)`, `text[start - 1] == text[end]` and that character is `"` or `'` (the token is the whole content of a quoted string); its `path` is non-empty and is in `base.paths` or `base.directories`; and some move source equals `path` or starts with `path + "/"`.
- `after = Tree((base.paths - moved.keys()) | set(moved.values()))`.
- `successors`: a `path` in `base.paths` is `(True, [(moved[path], False)])`. A directory not in `after.directories` whose `adopt_links.directory_successor` is not `None` is `(True, [(that, True)])`. Any other directory is `(False, found)` where `found` is the sorted distinct result of visiting each immediate child of the directory in `base`: a moved file contributes `(moved[child], False)`; a child directory that satisfies the single-successor rule contributes `(successor, True)`; any other child directory is visited the same way; an unmoved file contributes nothing.
- `carried_form`: with `single`, the form is `prefix + successor + tail`; otherwise it exists only when `tail in CARRIED_TAILS` and is `prefix + successor + (tail if is_directory else "")`. A form is returned only if `tokens(form)` is exactly one token spanning the whole form and `split_token(form)[1] == successor`; else `None`.
- Shapes (D6), over the occurrence's line `L` (the text between the surrounding `\n`s). *Quoted*: the token is the whole content of a quoted string; with `before = L[:open_quote].rstrip()` and `rest = L[close_quote + 1:].lstrip()`, `before` is empty, or ends in `[`, `{` or `,`, or ends in `(` whose immediately preceding character is absent or is neither alphanumeric nor one of `_`, `)`, `]`; and `rest` is empty or starts with `,`, `]`, `)` or `}`. *Line*: not quoted-shaped, and `L` is exactly `[ \t]*`, an optional `- `, the token optionally wrapped in one matching `"` or `'` pair, then only whitespace.
- Offered answers, in `ANSWERS` order (D5): `extend` when `shape` is not `None`, there is at least one successor and every successor has a carried form (`additions` is those forms in successor order, else `()`); `rewrite` when `single` and the form exists (`replacement` is it, else `None`); `retain` always.
- Edits (D6): quoted `extend` inserts `"".join(f", {q}{form}{q}" for form in additions)` at `end + 1` (`q` is the occurrence's quote). Line `extend` builds one copy of `L` per addition with the token replaced; when `L` is followed by `\n` it inserts `"".join(copy + "\n" ...)` directly after that `\n`, otherwise it inserts `"".join("\n" + copy ...)` at the end of the text. `rewrite` replaces `[start, end)` with `replacement`; `retain` edits nothing. A file's edits are `(start, end, text)` triples applied in descending `(start, end)` order.
- `derive_references`: no moves returns `References({}, ())` without running git. Otherwise one `git grep --no-color -I -l -z -F -e <segment>… <revision>` (D13) over the sorted distinct first path segments of the move sources; exit 1 is "no candidate", any other non-zero exit refuses `adopt_failure` / `adopt.git.failed`. Each `<revision>:<path>` result is kept only if its mode in `tree_records` is in `REGULAR_MODES`, it is not Markdown, not secret-shaped, not a move source, not under a `RECORD_HOMES` prefix and not in `excluded`; a secret-shaped path is dropped before any blob is read. Kept paths are read with `blob_at` and decoded as strict UTF-8, an undecodable one being skipped; the result is `plan_references(texts, <every tree path>, moves)`.
- The module reads nothing from the working tree and writes nothing.

- [ ] **Step 1: Write the failing tests**

Create `home/common/agent-skills/tests/test_adopt_references.py`:

```python
"""Unit tables for `agent_tools.adopt_references` (#350 D2-D6, D11)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_tools import adopt_references
from agent_tools.adopt_links import Tree

PATHS = [".claude/specs/x.md", ".claude/specs/sub/s.md", ".claude/plans/y.md",
         ".claude/skills.config.json", ".out-of-scope/z.md", "docs/guide.txt",
         "tools/check.py"]
MOVES = [(".claude/specs/x.md", ".agents/artifacts/specs/x.md"),
         (".claude/specs/sub/s.md", ".agents/artifacts/specs/sub/s.md"),
         (".claude/plans/y.md", ".agents/artifacts/plans/y.md"),
         (".out-of-scope/z.md", ".agents/knowledge/rejections/z.md")]
DISSOLVED_PATHS = [".claude/specs/x.md", ".claude/research/r.md",
                   ".claude/top.json"]
DISSOLVED_MOVES = [
    (".claude/specs/x.md", ".agents/artifacts/specs/x.md"),
    (".claude/research/r.md", ".agents/artifacts/specs/r.md"),
    (".claude/top.json", ".agents/knowledge/archive/adopted/.claude/top.json")]
PLANS, SPECS = ".agents/artifacts/plans", ".agents/artifacts/specs"
EXEMPT = 'EXEMPT = ("docs/archive/", ".claude/")\n'
ANSWERS_ALL = ("extend", "rewrite", "retain")


def trees(paths, moves):
    base, moved = Tree(paths), dict(moves)
    return base, Tree((base.paths - moved.keys()) | set(moved.values())), moved


def found(text, paths=PATHS, moves=MOVES):
    return adopt_references.plan_references(
        {"tools/check.py": text}, paths, moves).occurrences


def offers(text, **kwargs):
    return [(o.literal, o.answers, o.additions, o.replacement)
            for o in found(text, **kwargs)]


def edit(text, *answers):
    references = adopt_references.plan_references(
        {"tools/check.py": text}, PATHS, MOVES)
    chosen = {o.subject: answer
              for o, answer in zip(references.occurrences, answers)}
    files = adopt_references.rewritten(references, chosen)
    return files["tools/check.py"][1] if files else text


class TokenTest(unittest.TestCase):
    def test_tokens_carry_offsets_lines_and_columns(self):
        self.assertEqual(
            [(t.text, t.start, t.end, t.line, t.column)
             for t in adopt_references.tokens(EXEMPT)],
            [("EXEMPT", 0, 6, 1, 1), ("docs/archive/", 11, 24, 1, 12),
             (".claude/", 28, 36, 1, 29)])
        self.assertEqual(
            [(t.text, t.start, t.end, t.line, t.column)
             for t in adopt_references.tokens("a\n  b/c\n")],
            [("a", 0, 1, 1, 1), ("b/c", 4, 7, 2, 3)])

    def test_a_token_splits_into_prefix_path_and_tail(self):
        for token, expected in (
                (".claude/", ("", ".claude", "/")),
                (".claude", ("", ".claude", "")),
                ("/.claude/specs/**", ("/", ".claude/specs", "/**")),
                ("./.claude/specs/x.json", ("./", ".claude/specs/x.json", "")),
                (".claude/*.md", ("", ".claude", "/*.md")),
                ("*.md", ("", "", "*.md")),
                ("a//b", ("", "a", "//b")),
                ("/", ("/", "", "")),
                ("./", ("./", "", ""))):
            with self.subTest(token=token):
                self.assertEqual(adopt_references.split_token(token), expected)


class SuccessorTest(unittest.TestCase):
    def test_single_and_surviving_paths(self):
        base, after, moved = trees(PATHS, MOVES)
        for path, expected in (
                (".claude/specs/x.md", (True, [(SPECS + "/x.md", False)])),
                (".claude/specs", (True, [(SPECS, True)])),
                (".out-of-scope",
                 (True, [(".agents/knowledge/rejections", True)])),
                (".claude", (False, [(PLANS, True), (SPECS, True)])),
                ("docs", (False, []))):
            with self.subTest(path=path):
                self.assertEqual(adopt_references.successors(
                    path, base, after, moved), expected)

    def test_a_dissolved_directory_maps_to_its_moved_subtrees(self):
        base, after, moved = trees(DISSOLVED_PATHS, DISSOLVED_MOVES)
        archived = ".agents/knowledge/archive/adopted/.claude/top.json"
        self.assertEqual(
            adopt_references.successors(".claude", base, after, moved),
            (False, [(SPECS, True), (archived, False)]))
        self.assertEqual(
            offers("  - .claude/\n", paths=DISSOLVED_PATHS,
                   moves=DISSOLVED_MOVES),
            [(".claude/", ("extend", "retain"), (SPECS + "/", archived),
              None)])

    def test_carried_forms(self):
        form = adopt_references.carried_form
        self.assertEqual(form("/", SPECS, True, "/*.md", True),
                         "/" + SPECS + "/*.md")
        self.assertEqual(form("./", SPECS, True, "/**", False),
                         "./" + SPECS + "/**")
        self.assertEqual(form("", "new/x.json", False, "/", False),
                         "new/x.json")
        self.assertIsNone(form("", SPECS, True, "/*.md", False))
        self.assertIsNone(form("", "new/a b", True, "/", True))
        self.assertIsNone(form("", "new/x[1]", True, "", True))


class OccurrenceTest(unittest.TestCase):
    def test_the_motivating_tuple_is_one_occurrence(self):
        (occurrence,) = found(EXEMPT)
        self.assertEqual(occurrence, adopt_references.Occurrence(
            "tools/check.py", 1, 29, 28, 36, ".claude/",
            ("extend", "retain"), (PLANS + "/", SPECS + "/"), None, "quoted"))
        self.assertEqual(occurrence.subject, "tools/check.py:1:29")

    def test_text_that_is_not_a_whole_repository_path_is_no_occurrence(self):
        for text in ("# see docs for .claude details\n",
                     'URL = "https://example.com/.claude/specs"\n',
                     'p = "$ROOT/.claude/specs"\n',
                     'x = "docs"\n',
                     "x = .claudette/specs/\n",
                     "*.md\n"):
            with self.subTest(text=text):
                self.assertEqual(found(text), ())

    def test_offered_answers_follow_the_shape_and_the_successor(self):
        retain = ("retain",)
        for text, expected in (
                ("/.claude/specs/**  @team\n",
                 [("/.claude/specs/**", ("rewrite", "retain"), (),
                   "/" + SPECS + "/**")]),
                (".claude/specs/\n",
                 [(".claude/specs/", ANSWERS_ALL, (SPECS + "/",),
                   SPECS + "/")]),
                ('  - ".claude/"\n',
                 [(".claude/", ("extend", "retain"),
                   (PLANS + "/", SPECS + "/"), None)]),
                (".claude/*.md\n", [(".claude/*.md", retain, (), None)]),
                ('x = ".claude/specs/x.md"\n',
                 [(".claude/specs/x.md", ("rewrite", "retain"), (),
                   SPECS + "/x.md")]),
                ('skip(".claude/specs")\n',
                 [(".claude/specs", ("rewrite", "retain"), (), SPECS)]),
                ('os.path.join(".claude", "specs")\n',
                 [(".claude", retain, (), None)]),
                ('{"exclude": [".claude/specs"]}\n',
                 [(".claude/specs", ANSWERS_ALL, (SPECS,), SPECS)]),
                ("IGNORE=.claude/specs/ other\n",
                 [(".claude/specs/", ("rewrite", "retain"), (),
                   SPECS + "/")])):
            with self.subTest(text=text):
                self.assertEqual(offers(text), expected)


class EditTest(unittest.TestCase):
    def test_a_quoted_element_gains_elements_after_its_closing_quote(self):
        self.assertEqual(edit(EXEMPT, "extend"), (
            'EXEMPT = ("docs/archive/", ".claude/", '
            '".agents/artifacts/plans/", ".agents/artifacts/specs/")\n'))
        self.assertEqual(edit('EXCLUDE = [\n    ".claude/",\n]\n', "extend"), (
            'EXCLUDE = [\n    ".claude/", ".agents/artifacts/plans/", '
            '".agents/artifacts/specs/",\n]\n'))

    def test_a_line_element_gains_copied_lines(self):
        self.assertEqual(
            edit('paths:\n  - ".claude/"\n  - src/\n', "extend"),
            'paths:\n  - ".claude/"\n  - ".agents/artifacts/plans/"\n'
            '  - ".agents/artifacts/specs/"\n  - src/\n')
        self.assertEqual(edit(".claude/specs/", "extend"),
                         ".claude/specs/\n.agents/artifacts/specs/")

    def test_rewrite_replaces_the_token_and_retain_changes_nothing(self):
        self.assertEqual(edit("/.claude/specs/**  @team\n", "rewrite"),
                         "/.agents/artifacts/specs/**  @team\n")
        self.assertEqual(edit(EXEMPT, "retain"), EXEMPT)
        self.assertEqual(edit(EXEMPT), EXEMPT)

    def test_edits_in_one_file_apply_from_the_last_offset(self):
        self.assertEqual(
            edit(".claude/specs/\n.claude/plans/\n", "extend", "rewrite"),
            ".claude/specs/\n.agents/artifacts/specs/\n"
            ".agents/artifacts/plans/\n")

    def test_an_unoffered_answer_raises(self):
        with self.assertRaises(ValueError):
            edit(EXEMPT, "rewrite")

    def test_the_summary_rows(self):
        references = adopt_references.plan_references(
            {"tools/check.py": EXEMPT}, PATHS, MOVES)
        row = {"subject": "tools/check.py:1:29", "path": "tools/check.py",
               "line": 1, "column": 29, "literal": ".claude/",
               "answers": ["extend", "retain"], "answer": None,
               "additions": [PLANS + "/", SPECS + "/"], "replacement": None}
        self.assertEqual(adopt_references.summary(references, {}), [row])
        self.assertEqual(
            adopt_references.summary(
                references, {"tools/check.py:1:29": "extend"}),
            [{**row, "answer": "extend"}])
        self.assertEqual(references.texts, {"tools/check.py": EXEMPT})


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True,
        timeout=120,
        env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
                 GIT_CONFIG_SYSTEM=os.devnull,
                 GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                 GIT_COMMITTER_NAME="t",
                 GIT_COMMITTER_EMAIL="t@example.invalid"))


class DerivationTest(unittest.TestCase):
    FILES = {
        "tools/check.py": EXEMPT.encode(),
        ".claude/keep.json": b'{"dir": ".claude/specs"}\n',
        ".claude/specs/x.md": b"# x\n",
        ".claude/specs/data.txt": b".claude/specs/\n",
        ".claude/plans/y.md": b"# y\n",
        "config/owners.txt": b".claude/specs/\n",
        "notes.md": b"see .claude/specs/\n",
        ".env.ci": b".claude/specs/\n",
        "blob.bin": b"\x00.claude/specs/\n",
        "legacy.txt": b"caf\xe9 .claude/specs/\n",
        ".agents/artifacts/evidence/e.json": b'".claude/specs/"\n',
        ".agents/knowledge/archive/old.txt": b".claude/specs/\n",
    }
    MOVES = [(".claude/specs/x.md", SPECS + "/x.md"),
             (".claude/specs/data.txt", SPECS + "/data.txt"),
             (".claude/plans/y.md", PLANS + "/y.md")]

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        git(self.root, "init", "--quiet", "-b", "main")
        git(self.root, "config", "commit.gpgsign", "false")
        for path, data in self.FILES.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        git(self.root, "add", "-A", "-f")
        git(self.root, "commit", "--quiet", "-m", "fixture")

    def subjects(self, excluded=()):
        return [o.subject for o in adopt_references.derive_references(
            self.root, "HEAD", self.MOVES, excluded).occurrences]

    def test_only_scanned_files_yield_occurrences(self):
        self.assertEqual(self.subjects(["config/owners.txt"]),
                         [".claude/keep.json:1:10", "tools/check.py:1:29"])
        self.assertEqual(self.subjects(),
                         [".claude/keep.json:1:10", "config/owners.txt:1:1",
                          "tools/check.py:1:29"])

    def test_the_revision_is_read_not_the_working_tree(self):
        (self.root / "tools/check.py").write_text("nothing\n",
                                                  encoding="utf-8")
        self.assertIn("tools/check.py:1:29", self.subjects())

    def test_no_moves_is_no_reference(self):
        self.assertEqual(
            adopt_references.derive_references(self.root, "HEAD", [], []),
            adopt_references.References({}, ()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py`
Expected: FAIL — `ImportError: cannot import name 'adopt_references'`.

- [ ] **Step 3: Write the minimal implementation**

Rename `_directory_successor` to `directory_successor` in `adopt_links.py` (definition and its caller). Create `adopt_references.py` with the names in **Produces**, satisfying **Invariants**; a module docstring that states what the module owns, that it is imported and never run, reads blobs only through git and is standard library only; and one section per concern in this order: tokens, successors and carried forms, occurrences and shapes, edits, the pure core (`plan_references`, `summary`, `rewritten`), the git reader. Keep helper functions private (`_`-prefixed) unless named in **Produces**.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py home/common/agent-skills/tests/test_adopt_links.py`
Expected: OK, every test in both modules passing, no warnings (the `adopt_links` suite proves the rename changed no behaviour).

Run: `if git grep -q "_directory_successor" -- python/agent_tools; then exit 1; fi; grep -c "test_adopt_references.py" justfile`
Expected: exit 0 and `1`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_references.py python/agent_tools/adopt_links.py \
  home/common/agent-skills/tests/test_adopt_references.py justfile
git commit -m "feat(adopt): model path references in tracked tooling files (#350)"
```
