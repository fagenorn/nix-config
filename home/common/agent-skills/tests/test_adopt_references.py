"""Unit tables for `agent_tools.adopt_references` (#350 D2-D6, D11)."""

from __future__ import annotations

import dataclasses
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_tools import adopt_references
from agent_tools.adopt_links import Tree

PATHS = [".claude/specs/x.md", ".claude/specs/sub/s.md", ".claude/plans/y.md",
         ".claude/settings.json", ".out-of-scope/z.md", "docs/guide.txt",
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

    def test_an_occurrence_outside_the_closed_sets_raises(self):
        references = adopt_references.plan_references(
            {"tools/check.py": ".claude/specs/\n"}, PATHS, MOVES)
        (occurrence,) = references.occurrences
        self.assertEqual((occurrence.answers, occurrence.shape),
                         (ANSWERS_ALL, "line"))
        for changed, answer in (({"shape": None}, "extend"),
                                ({"shape": "block"}, "extend"),
                                ({"replacement": None}, "rewrite"),
                                ({"answers": ("append",)}, "append")):
            broken = adopt_references.References(
                references.texts,
                (dataclasses.replace(occurrence, **changed),))
            with self.subTest(changed=changed, answer=answer):
                with self.assertRaises(ValueError):
                    adopt_references.rewritten(
                        broken, {occurrence.subject: answer})

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

    def test_forced_colour_does_not_hide_the_candidates(self):
        git(self.root, "config", "color.ui", "always")
        self.assertEqual(self.subjects(["config/owners.txt"]),
                         [".claude/keep.json:1:10", "tools/check.py:1:29"])

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
