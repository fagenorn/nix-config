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
PATTERN_EXCLUDE = (r'EXCLUDE = ["^var/", "^\\.claude/", "^\\.worktrees/"]'
                   + "\n")
POLICY_TEXTS = {
    ".claude/specs/tool.py":
        'SPEC = ".claude/specs/x.md"\nSKIP = (".claude",)\n',
    ".claude/specs/sub/data.json": '{"plan": ".claude/plans/y.md"}\n',
    "tools/check.py": EXEMPT,
}
POLICY_PATHS = PATHS + [".claude/specs/tool.py", ".claude/specs/sub/data.json"]
POLICY_MOVES = MOVES + [
    (".claude/specs/tool.py", SPECS + "/tool.py"),
    (".claude/specs/sub/data.json", SPECS + "/sub/data.json")]
POLICY_TREES = {
    source: (".out-of-scope" if source.startswith(".out-of-scope/")
             else "/".join(source.split("/")[:2]))
    for source, _ in POLICY_MOVES}
PY, JSON = ".claude/specs:.py", ".claude/specs:.json"


def trees(paths, moves):
    base, moved = Tree(paths), dict(moves)
    return base, Tree((base.paths - moved.keys()) | set(moved.values())), moved


def found(text, paths=PATHS, moves=MOVES):
    return adopt_references.plan_references(
        {"tools/check.py": text}, paths, moves, {}).occurrences


def offers(text, **kwargs):
    return [(o.literal, o.answers, o.additions, o.replacement)
            for o in found(text, **kwargs)]


def edit(text, *answers):
    references = adopt_references.plan_references(
        {"tools/check.py": text}, PATHS, MOVES, {})
    chosen = {o.subject: answer
              for o, answer in zip(references.occurrences, answers)}
    files = adopt_references.rewritten(references, chosen, {})
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


class PatternTest(unittest.TestCase):
    """#372 D6: a token the plain reading rejects is read as a pattern."""

    def test_a_pattern_splits_into_anchor_escape_prefix_path_and_tail(self):
        for token, expected in (
                (r"^\\.claude/", ("^", r"\\.", "", ".claude", "/")),
                (r"^\.claude/specs/x\.md",
                 ("^", r"\.", "", ".claude/specs/x.md", "")),
                (r"\.claude/specs", ("", r"\.", "", ".claude/specs", "")),
                (r"^/\.claude/", ("^", r"\.", "/", ".claude", "/")),
                ("^.claude/specs/.*", ("^", "", "", ".claude/specs", "/.*")),
                (r"^\.claude/[a-z]+/",
                 ("^", r"\.", "", ".claude", "/[a-z]+/")),
                (r"^\.claude\b/x", ("^", r"\.", "", "", r"\.claude\b/x")),
                (r"^\\.claude/a\.b", ("^", r"\\.", "", ".claude", r"/a\.b")),
                ("^", ("^", "", "", "", "")),
                (".claude/specs", None),
                ("docs/guide.txt", None)):
            with self.subTest(token=token):
                self.assertEqual(adopt_references.split_pattern(token),
                                 expected)

    def test_pattern_forms_keep_anchor_escape_and_tail(self):
        form = adopt_references.pattern_form
        self.assertEqual(form("^", r"\\.", "", SPECS, True, "/", False),
                         r"^\\.agents/artifacts/specs/")
        self.assertEqual(
            form("^", r"\.", "", SPECS + "/x.md", False, "", True),
            r"^\.agents/artifacts/specs/x\.md")
        self.assertEqual(form("^", "", "/", SPECS, True, "/.*", True),
                         "^/" + SPECS + "/.*")
        self.assertEqual(form("", r"\.", "", "new/x.json", False, "/", False),
                         r"new/x\.json")
        # A tail that is not carried for a path with several successors.
        self.assertIsNone(form("^", r"\.", "", SPECS, True, "/.*", False))
        # A successor outside letters, digits, `_`, `-`, `.` and `/`.
        self.assertIsNone(form("^", r"\.", "", "new/x+y.md", False, "", True))
        # `new/x` holds neither `^` nor `\.`: it would not read back.
        self.assertIsNone(form("", r"\.", "", "new/x", True, "", True))

    def test_a_pattern_spelling_is_an_occurrence_with_pattern_forms(self):
        for text, expected in (
                (PATTERN_EXCLUDE,
                 [(r"^\\.claude/", ("extend", "retain"),
                   (r"^\\.agents/artifacts/plans/",
                    r"^\\.agents/artifacts/specs/"), None)]),
                (r'X = "^\.claude/specs/x\.md"' + "\n",
                 [(r"^\.claude/specs/x\.md", ("rewrite", "retain"), (),
                   r"^\.agents/artifacts/specs/x\.md")]),
                (r'"\.claude/specs/"' + "\n",
                 [(r"\.claude/specs/", ANSWERS_ALL,
                   (r"\.agents/artifacts/specs/",),
                   r"\.agents/artifacts/specs/")]),
                ('"^.claude/plans/y.md"\n',
                 [("^.claude/plans/y.md", ANSWERS_ALL,
                   ("^" + PLANS + "/y.md",), "^" + PLANS + "/y.md")]),
                (r"^\.claude/specs/.*  @team" + "\n",
                 [(r"^\.claude/specs/.*", ("rewrite", "retain"), (),
                   r"^\.agents/artifacts/specs/.*")])):
            with self.subTest(text=text):
                self.assertEqual(offers(text), expected)

    def test_a_pattern_naming_nothing_moved_is_no_occurrence(self):
        for text in (r'"^\.claude/specs$"', '"^var/"', r'"^\.worktrees/"',
                     r"x = ^\.claude", r'"^docs/guide\.txt"',
                     r'"^\.claude\b/"', r'"^./\.claude/"'):
            with self.subTest(text=text):
                self.assertEqual(found(text + "\n"), ())

    def test_the_plain_reading_decides_when_it_yields_an_occurrence(self):
        paths = ["^gen/a.md", "gen/a.md", "tools/check.py"]
        moves = [("^gen/a.md", "out/a.md"), ("gen/a.md", "other/a.md")]
        self.assertEqual(
            offers('x = "^gen/a.md"\n', paths=paths, moves=moves),
            [("^gen/a.md", ("rewrite", "retain"), (), "out/a.md")])

    def test_a_successor_with_no_pattern_form_offers_retain_only(self):
        moves = [(".claude/specs/x.md", SPECS + "/x+y.md")] + MOVES[1:]
        self.assertEqual(
            offers(r'x = "^\.claude/specs/x\.md"' + "\n", moves=moves),
            [(r"^\.claude/specs/x\.md", ("retain",), (), None)])

    def test_answers_edit_a_pattern_spelling(self):
        self.assertEqual(edit(PATTERN_EXCLUDE, "extend"), (
            r'EXCLUDE = ["^var/", "^\\.claude/", '
            r'"^\\.agents/artifacts/plans/", "^\\.agents/artifacts/specs/", '
            r'"^\\.worktrees/"]' + "\n"))
        self.assertEqual(edit(r'X = "^\.claude/specs/x\.md"' + "\n",
                              "rewrite"),
                         r'X = "^\.agents/artifacts/specs/x\.md"' + "\n")


class OccurrenceTest(unittest.TestCase):
    def test_the_motivating_tuple_is_one_occurrence(self):
        (occurrence,) = found(EXEMPT)
        self.assertEqual(occurrence, adopt_references.Occurrence(
            "tools/check.py", 1, 29, 28, 36, ".claude/",
            ("extend", "retain"), (PLANS + "/", SPECS + "/"), None, "quoted",
            "tools/check.py", None))
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
            {"tools/check.py": ".claude/specs/\n"}, PATHS, MOVES, {})
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
                        broken, {occurrence.subject: answer}, {})

    def test_the_summary_rows(self):
        references = adopt_references.plan_references(
            {"tools/check.py": EXEMPT}, PATHS, MOVES, {})
        row = {"subject": "tools/check.py:1:29", "path": "tools/check.py",
               "line": 1, "column": 29, "literal": ".claude/",
               "answers": ["extend", "retain"], "answer": None,
               "additions": [PLANS + "/", SPECS + "/"], "replacement": None,
               "target": "tools/check.py", "policy": None,
               "decided_by": None}
        self.assertEqual(adopt_references.summary(references, {}, {}), [row])
        self.assertEqual(
            adopt_references.summary(
                references, {"tools/check.py:1:29": "extend"}, {}),
            [{**row, "answer": "extend", "decided_by": "occurrence"}])
        self.assertEqual(references.texts, {"tools/check.py": EXEMPT})


class PolicyTest(unittest.TestCase):
    """#372 D2-D5: targets, policy subjects, precedence, counts and edits."""

    def references(self):
        return adopt_references.plan_references(
            POLICY_TEXTS, POLICY_PATHS, POLICY_MOVES, POLICY_TREES)

    def policy_row(self, subject, recommended, occurrences, **changed):
        tree, _, file_class = subject.partition(":")
        return {"subject": subject, "tree": tree, "class": file_class,
                "recommended": recommended, "answer": None, "files": 1,
                "occurrences": occurrences, "rewritable": 1, "rewritten": 0,
                "retained": 0, "extended": 0, "open": occurrences,
                "overridden": 0, **changed}

    def test_the_class_of_a_file_name(self):
        for path, expected in (("a/b.py", ".py"), ("a/B.PY", ".py"),
                               ("a.tar.gz", ".gz"), ("a/.config.json", ".json"),
                               ("Makefile", "-"), (".envrc", "-"),
                               ("a.d/run", "-"), ("notes.", "-")):
            with self.subTest(path=path):
                self.assertEqual(adopt_references.file_class(path), expected)

    def test_the_recommendation_table_is_closed(self):
        recommended = adopt_references.recommended_answer
        for file_class in (".py", ".sh", ".bash", ".zsh", ".nix", ".yaml",
                           ".yml", ".toml", ".js", ".mjs", ".cjs", ".ts"):
            self.assertEqual(recommended(file_class), "rewrite", file_class)
        for file_class in (".json", ".jsonl", ".ndjson", ".csv", ".tsv",
                           ".txt", ".log"):
            self.assertEqual(recommended(file_class), "retain", file_class)
        for file_class in ("-", ".md", ".cfg", ".lock", ""):
            self.assertIsNone(recommended(file_class), file_class)
        self.assertEqual(adopt_references.POLICY_ANSWERS,
                         ("rewrite", "retain"))

    def test_targets_and_policy_subjects(self):
        self.assertEqual(
            [(o.subject, o.target, o.tree, o.policy)
             for o in self.references().occurrences],
            [(".claude/specs/sub/data.json:1:11", SPECS + "/sub/data.json",
              ".claude/specs", JSON),
             (".claude/specs/tool.py:1:9", SPECS + "/tool.py",
              ".claude/specs", PY),
             (".claude/specs/tool.py:2:10", SPECS + "/tool.py",
              ".claude/specs", PY),
             ("tools/check.py:1:29", "tools/check.py", None, None)])

    def test_a_moved_file_without_a_tree_raises(self):
        with self.assertRaises(ValueError):
            adopt_references.plan_references(
                POLICY_TEXTS, POLICY_PATHS, POLICY_MOVES, {})

    def test_effective_answers(self):
        data, spec, skip, exempt = self.references().occurrences
        self.assertEqual((spec.answers, skip.answers),
                         (("rewrite", "retain"), ("extend", "retain")))
        rewrite, retain = {PY: "rewrite"}, {PY: "retain"}
        for occurrence, answers, policies, expected in (
                (spec, {}, {}, (None, None)),
                (spec, {}, rewrite, ("rewrite", "policy")),
                (spec, {spec.subject: "retain"}, rewrite,
                 ("retain", "occurrence")),
                (spec, {spec.subject: "retain"}, {}, ("retain", "occurrence")),
                (skip, {}, rewrite, (None, None)),
                (skip, {}, retain, ("retain", "policy")),
                (skip, {skip.subject: "extend"}, rewrite,
                 ("extend", "occurrence")),
                (data, {}, rewrite, (None, None)),
                (exempt, {}, rewrite, (None, None)),
                (exempt, {exempt.subject: "extend"}, {},
                 ("extend", "occurrence"))):
            with self.subTest(subject=occurrence.subject, answers=answers,
                              policies=policies):
                self.assertEqual(adopt_references.effective_answer(
                    occurrence, answers, policies), expected)
        with self.assertRaises(ValueError):
            adopt_references.effective_answer(skip, {}, {PY: "extend"})

    def test_rows_carry_target_policy_and_what_decided(self):
        references = self.references()
        skip = references.occurrences[2].subject
        rows = adopt_references.summary(references, {skip: "extend"},
                                        {PY: "rewrite"})
        self.assertEqual(list(rows[0]), [
            "subject", "path", "line", "column", "literal", "answers",
            "answer", "additions", "replacement", "target", "policy",
            "decided_by"])
        self.assertEqual(
            [(row["subject"], row["answer"], row["decided_by"],
              row["target"], row["policy"]) for row in rows],
            [(".claude/specs/sub/data.json:1:11", None, None,
              SPECS + "/sub/data.json", JSON),
             (".claude/specs/tool.py:1:9", "rewrite", "policy",
              SPECS + "/tool.py", PY),
             (skip, "extend", "occurrence", SPECS + "/tool.py", PY),
             ("tools/check.py:1:29", None, None, "tools/check.py", None)])

    def test_policy_rows_count_each_class(self):
        references = self.references()
        _, spec, skip, _ = (o.subject for o in references.occurrences)
        rows = adopt_references.policy_summary
        data = self.policy_row(JSON, "retain", 1)
        self.assertEqual(rows(references, {}, {}),
                         [data, self.policy_row(PY, "rewrite", 2)])
        self.assertEqual(
            rows(references, {}, {PY: "rewrite"}),
            [data, self.policy_row(PY, "rewrite", 2, answer="rewrite",
                                   rewritten=1, open=1)])
        self.assertEqual(
            rows(references, {spec: "retain"}, {}),
            [data, self.policy_row(PY, "rewrite", 2, retained=1, open=1,
                                   overridden=1)])
        self.assertEqual(
            rows(references, {skip: "extend"},
                 {PY: "rewrite", JSON: "retain"}),
            [{**data, "answer": "retain", "retained": 1, "open": 0},
             self.policy_row(PY, "rewrite", 2, answer="rewrite", rewritten=1,
                             extended=1, open=0, overridden=1)])

    def test_a_moved_file_is_edited_under_its_target(self):
        references = self.references()
        skip = references.occurrences[2].subject
        before = POLICY_TEXTS[".claude/specs/tool.py"]
        self.assertEqual(
            adopt_references.rewritten(references, {}, {PY: "rewrite"}),
            {SPECS + "/tool.py": (before, (
                'SPEC = ".agents/artifacts/specs/x.md"\n'
                'SKIP = (".claude",)\n'))})
        self.assertEqual(
            adopt_references.rewritten(
                references, {skip: "extend"}, {PY: "rewrite"}),
            {SPECS + "/tool.py": (before, (
                'SPEC = ".agents/artifacts/specs/x.md"\n'
                'SKIP = (".claude", ".agents/artifacts/plans", '
                '".agents/artifacts/specs",)\n'))})
        self.assertEqual(
            adopt_references.rewritten(
                references, {}, {PY: "retain", JSON: "retain"}), {})
        with self.assertRaises(ValueError):
            adopt_references.rewritten(references, {skip: "rewrite"}, {})

    def test_a_path_two_files_are_left_at_is_contested_and_never_edited(self):
        shared = SPECS + "/check.py"
        occupied = ".agents/knowledge/rejections/z.py"
        texts = {
            ".claude/research/check.py": 'SPEC = ".claude/specs/x.md"\n',
            ".claude/specs/check.py": 'PLAN = ".claude/plans/y.md"\n',
            ".out-of-scope/z.py": 'PLAN = ".claude/plans/y.md"\n',
            occupied: 'SPEC = ".claude/specs/x.md"\n',
            ".claude/specs/tool.py": 'SPEC = ".claude/specs/x.md"\n',
        }
        moves = MOVES + [
            (".claude/research/check.py", shared),
            (".claude/specs/check.py", shared),
            (".out-of-scope/z.py", occupied),
            (".claude/specs/tool.py", SPECS + "/tool.py")]
        moved_trees = {
            source: (".out-of-scope" if source.startswith(".out-of-scope/")
                     else "/".join(source.split("/")[:2]))
            for source, _ in moves}
        references = adopt_references.plan_references(
            texts, PATHS + list(texts), moves, moved_trees)
        self.assertEqual(references.contested,
                         frozenset({shared, occupied}))
        self.assertEqual(
            [(o.path, o.target) for o in references.occurrences],
            [(occupied, occupied), (".claude/research/check.py", shared),
             (".claude/specs/check.py", shared),
             (".claude/specs/tool.py", SPECS + "/tool.py"),
             (".out-of-scope/z.py", occupied)])
        tool = (SPECS + "/tool.py", (
            texts[".claude/specs/tool.py"],
            'SPEC = ".agents/artifacts/specs/x.md"\n'))
        every = {o.subject: "rewrite" for o in references.occurrences}
        self.assertEqual(adopt_references.rewritten(references, every, {}),
                         dict([tool]))
        for path in texts:
            one = {o.subject: "rewrite" for o in references.occurrences
                   if o.path == path}
            with self.subTest(path=path):
                self.assertEqual(
                    adopt_references.rewritten(references, one, {}),
                    dict([tool]) if path == ".claude/specs/tool.py" else {})
        self.assertEqual(
            [(row["subject"], row["answer"], row["target"])
             for row in adopt_references.summary(references, every, {})],
            [(o.subject, "rewrite", o.target)
             for o in references.occurrences])

    def test_no_path_is_contested_when_each_file_has_its_own(self):
        self.assertEqual(self.references().contested, frozenset())
        self.assertEqual(adopt_references.References({}, ()).contested,
                         frozenset())

    def test_two_edited_files_at_one_uncontested_path_raise(self):
        references = self.references()
        data, spec, _, _ = references.occurrences
        merged = adopt_references.References(
            references.texts,
            (dataclasses.replace(data, target=spec.target), spec))
        with self.assertRaises(ValueError):
            adopt_references.rewritten(
                merged, {data.subject: "rewrite", spec.subject: "rewrite"},
                {})


SHELL = "tools/run.sh"
MOVED_SH = ".claude/specs/run.sh"
SH, SH_VARIABLE = ".claude/specs:.sh", ".claude/specs:.sh/variable"
JOINED = 'cat ".claude/plans/y.md"\ncat "$root/.claude/plans/y.md"\n'


def shell_found(text, path=SHELL):
    return adopt_references.plan_references(
        {path: text}, PATHS + [path], MOVES, {}).occurrences


def shell_offers(text, path=SHELL):
    return [(o.literal, o.answers, o.additions, o.replacement, o.variable)
            for o in shell_found(text, path)]


def moved_shell():
    return adopt_references.plan_references(
        {MOVED_SH: JOINED}, PATHS + [MOVED_SH],
        MOVES + [(MOVED_SH, SPECS + "/run.sh")], {MOVED_SH: ".claude/specs"})


class VariableReadingTest(unittest.TestCase):
    """#376 D6-D8, D10, D13: `$name/` and `${name}/` in shell files."""

    def test_a_variable_prefix_splits_into_variable_path_and_tail(self):
        for token, expected in (
                ("$root/.claude/specs/x.md",
                 ("$root/", ".claude/specs/x.md", "")),
                ("${ROOT}/.claude/specs/x.md",
                 ("${ROOT}/", ".claude/specs/x.md", "")),
                ("${ROOT}/.claude/notes/$run/out",
                 ("${ROOT}/", ".claude/notes", "/$run/out")),
                ("$_a1/.claude/*.md", ("$_a1/", ".claude", "/*.md")),
                ("$root/", ("$root/", "", "")),
                ("$a/$b/.claude/specs", ("$a/", "", "$b/.claude/specs"))):
            with self.subTest(token=token):
                self.assertEqual(adopt_references.split_variable(token),
                                 expected)
                self.assertEqual("".join(expected), token)

    def test_unread_forms_are_not_a_variable_prefix(self):
        for token in ("$1/.claude/specs", "$9a/.claude", "${}/.claude",
                      "${name:-x}/.claude/specs", "${name%/*}/.claude",
                      "x$root/.claude/specs", "$root.d/.claude/specs",
                      "$(pwd)/.claude", ".claude/specs", "/.claude/specs"):
            with self.subTest(token=token):
                self.assertIsNone(adopt_references.split_variable(token))

    def test_the_carried_form_keeps_the_variable_and_the_tail(self):
        form = adopt_references.variable_form
        self.assertEqual(form("$root/", SPECS + "/x.md", False, "", True),
                         "$root/" + SPECS + "/x.md")
        self.assertEqual(form("${ROOT}/", SPECS, True, "/$run/out", True),
                         "${ROOT}/" + SPECS + "/$run/out")
        self.assertEqual(form("$root/", SPECS, True, "/", False),
                         "$root/" + SPECS + "/")
        self.assertEqual(form("$root/", SPECS + "/x.md", False, "/", False),
                         "$root/" + SPECS + "/x.md")
        for args in (("$root/", SPECS, True, "/x*", False),
                     ("$root/", "a b/x.md", False, "", True),
                     ("$root/", "a/$b", False, "", True)):
            with self.subTest(args=args):
                self.assertIsNone(form(*args))

    def test_a_variable_occurrence_offers_rewrite_and_retain_never_extend(self):
        self.assertEqual(shell_offers('cat "$root/.claude/specs/x.md"\n'), [
            ("$root/.claude/specs/x.md", ("rewrite", "retain"), (),
             "$root/" + SPECS + "/x.md", True)])
        self.assertEqual(shell_offers('cat "${ROOT}/.claude/plans/y.md"\n'), [
            ("${ROOT}/.claude/plans/y.md", ("rewrite", "retain"), (),
             "${ROOT}/" + PLANS + "/y.md", True)])
        # Alone on its line: the plain reading would offer `extend` here.
        self.assertEqual(shell_offers('"$root/.claude/specs/"\n'), [
            ("$root/.claude/specs/", ("rewrite", "retain"), (),
             "$root/" + SPECS + "/", True)])
        self.assertEqual(shell_offers('".claude/specs/"\n')[0][1],
                         ANSWERS_ALL)
        # An ancestor whose directory survives the moves: `retain` only.
        self.assertEqual(shell_offers('cd "$root/.claude"\n'), [
            ("$root/.claude", ("retain",), (), None, True)])

    def test_unread_forms_are_no_occurrence(self):
        for text in ('cat "$1/.claude/specs/x.md"\n',
                     'cat "x$root/.claude/specs/x.md"\n',
                     'cat "${root:-.}/.claude/specs/x.md"\n',
                     'cat "${root%/*}/.claude/specs/x.md"\n',
                     'cat "$a/$b/.claude/specs/x.md"\n',
                     'cat "$root.d/.claude/specs/x.md"\n'):
            with self.subTest(text=text):
                self.assertEqual(shell_found(text), ())

    def test_tokens_the_earlier_readings_take_are_unchanged(self):
        self.assertEqual(shell_offers(
            'cat "$(git rev-parse --show-toplevel)/.claude/specs/x.md"\n'), [
            ("/.claude/specs/x.md", ("rewrite", "retain"), (),
             "/" + SPECS + "/x.md", False)])
        self.assertEqual(shell_offers('cat ".claude/specs/x.md"\n'), [
            (".claude/specs/x.md", ("rewrite", "retain"), (),
             SPECS + "/x.md", False)])
        self.assertEqual(
            [o.variable for o in shell_found(
                r'grep "^\.claude/specs/x\.md"' + "\n")], [False])

    def test_only_the_shell_classes_are_read(self):
        text = 'cat "$root/.claude/specs/x.md"\n'
        for path in ("tools/run.sh", "tools/run.bash", "tools/run.zsh",
                     "tools/RUN.SH"):
            with self.subTest(path=path):
                self.assertEqual(
                    [o.variable for o in shell_found(text, path)], [True])
        for path in ("tools/run.py", "tools/run", "tools/run.yaml"):
            with self.subTest(path=path):
                self.assertEqual(shell_found(text, path), ())
        self.assertEqual(adopt_references.SHELL_CLASSES,
                         (".sh", ".bash", ".zsh"))

    def test_the_class_and_policy_of_a_variable_occurrence(self):
        self.assertEqual(
            [(o.subject, o.variable, o.occurrence_class, o.policy, o.target)
             for o in moved_shell().occurrences],
            [(MOVED_SH + ":1:6", False, ".sh", SH, SPECS + "/run.sh"),
             (MOVED_SH + ":2:6", True, ".sh/variable", SH_VARIABLE,
              SPECS + "/run.sh")])
        (unmoved,) = shell_found('cat "$root/.claude/plans/y.md"\n')
        self.assertEqual((unmoved.occurrence_class, unmoved.policy),
                         (".sh/variable", None))

    def test_policies_partition_literal_and_variable_occurrences(self):
        references = moved_shell()
        _, joined = references.occurrences
        self.assertEqual(adopt_references.effective_answer(
            joined, {}, {SH: "rewrite"}), (None, None))
        self.assertEqual(adopt_references.effective_answer(
            joined, {}, {SH_VARIABLE: "rewrite"}), ("rewrite", "policy"))
        row = {"tree": ".claude/specs", "files": 1, "occurrences": 1,
               "rewritable": 1, "rewritten": 0, "retained": 0,
               "extended": 0, "open": 0, "overridden": 0}
        self.assertEqual(
            adopt_references.policy_summary(
                references, {}, {SH: "rewrite", SH_VARIABLE: "retain"}),
            [{**row, "subject": SH, "class": ".sh", "recommended": "rewrite",
              "answer": "rewrite", "rewritten": 1},
             {**row, "subject": SH_VARIABLE, "class": ".sh/variable",
              "recommended": None, "answer": "retain", "retained": 1}])
        rewritten = adopt_references.rewritten
        self.assertEqual(
            rewritten(references, {}, {SH: "rewrite", SH_VARIABLE: "rewrite"}),
            {SPECS + "/run.sh": (JOINED, (
                f'cat "{PLANS}/y.md"\ncat "$root/{PLANS}/y.md"\n'))})
        self.assertEqual(
            rewritten(references, {}, {SH: "rewrite", SH_VARIABLE: "retain"}),
            {SPECS + "/run.sh": (JOINED, (
                f'cat "{PLANS}/y.md"\ncat "$root/.claude/plans/y.md"\n'))})
        self.assertEqual(
            rewritten(references, {}, {SH: "retain", SH_VARIABLE: "retain"}),
            {})


NOTES, NOTES_NEW = ".claude/notes", ".agents/artifacts/notes"
TOOL, TOOL_NEW = NOTES + "/tool", NOTES_NEW + "/tool"
DEPTH_PATHS = [TOOL + "/run.py", TOOL + "/pyproject.toml", TOOL + "/uv.lock",
               NOTES + "/data/x", "vendor/lib/m.py", ".claude/specs/x.md",
               "README.md"]
DEPTH_MOVES = [(TOOL + "/run.py", TOOL_NEW + "/run.py"),
               (TOOL + "/pyproject.toml", TOOL_NEW + "/pyproject.toml"),
               (TOOL + "/uv.lock", TOOL_NEW + "/uv.lock"),
               (NOTES + "/data/x", NOTES_NEW + "/data/x"),
               (".claude/specs/x.md", ".agents/artifacts/specs/x.md")]
DEPTH_TREES = {source: "/".join(source.split("/")[:2])
               for source, _ in DEPTH_MOVES}


def depth_found(texts, *, moves=DEPTH_MOVES, trees=DEPTH_TREES,
                paths=DEPTH_PATHS, scanned=None):
    return adopt_references.plan_references(
        scanned or {}, paths, moves, trees, depth_texts=texts).occurrences


def climbs(text, path=TOOL + "/pyproject.toml", **kwargs):
    return [(o.literal, o.answers, o.replacement, o.depth)
            for o in depth_found({path: text}, **kwargs)]


class TextClimbTest(unittest.TestCase):
    """#380 D1, D3, D4, D8: `../` climbs out of a moved file's tree."""

    def test_a_climb_splits_into_prefix_height_and_rest(self):
        split = adopt_references.split_climb
        for token, expected in (
                ("../x", ("", 1, "/x")), ("../../", ("", 2, "/")),
                ("../..", ("", 2, "")), ("./../x", ("./", 1, "/x")),
                ("./..", ("./", 1, "")),
                ("../../../vendor/lib", ("", 3, "/vendor/lib")),
                ("../a/./b", ("", 1, "/a/./b"))):
            with self.subTest(token=token):
                self.assertEqual(split(token), expected)
                self.assertEqual("".join((expected[0],
                                          "/".join([".."] * expected[1]),
                                          expected[2])), token)
        for token in ("..", "...", ".../x", "..x/y", "a/../b", "/../x",
                      "../a/../b", "x"):
            with self.subTest(token=token):
                self.assertIsNone(split(token))

    def test_the_shifted_form_keeps_prefix_and_rest(self):
        form = adopt_references.climb_form
        self.assertEqual(form("", 4, "/vendor/lib"), "../../../../vendor/lib")
        self.assertEqual(form("./", 1, ""), "./..")
        self.assertIsNone(form("", 0, "/x"))

    def test_a_climb_to_the_root_is_rewritten_one_level_deeper(self):
        self.assertEqual(climbs('lib = { path = "../../../vendor/lib" }\n'), [
            ("../../../vendor/lib", ("rewrite", "retain"),
             "../../../../vendor/lib", True)])
        self.assertEqual(climbs('p = "./../../../vendor/"\n'), [
            ("./../../../vendor/", ("rewrite", "retain"),
             "./../../../../vendor/", True)])

    def test_climbs_inside_the_tree_are_not_surfaced(self):
        for text in ('d = "../data/x"\n', 'd = "../../notes/data/x"\n',
                     'd = "./.."\n', 'd = "../x"\n'):
            with self.subTest(text=text):
                self.assertEqual(climbs(text), [])

    def test_a_landing_point_only_above_the_old_directory_is_retained(self):
        self.assertEqual(climbs('c = "../../settings.json"\n'), [
            ("../../settings.json", ("retain",), None, True)])

    def test_a_base_target_in_another_moved_tree_is_retained(self):
        self.assertEqual(climbs('s = "../../../.claude/specs/x.md"\n'), [
            ("../../../.claude/specs/x.md", ("retain",), None, True)])

    def test_bare_dots_are_no_climb(self):
        self.assertEqual(climbs('a = ".."\nb = HERE / ".." / ".."\n'), [])

    def test_a_same_depth_move_surfaces_nothing_new(self):
        moves = [(TOOL + "/pyproject.toml", "tools/notes/tool/pyproject.toml")]
        self.assertEqual(climbs('lib = { path = "../../../vendor/lib" }\n',
                                moves=moves), [])

    def test_a_same_depth_move_under_another_parent_is_retained(self):
        moves = [(TOOL + "/pyproject.toml", "tools/notes/tool/pyproject.toml")]
        self.assertEqual(climbs('c = "../../settings.json"\n', moves=moves), [
            ("../../settings.json", ("retain",), None, True)])

    def test_a_shallower_move_climbs_less(self):
        moves = [(TOOL + "/pyproject.toml", "notes/tool/pyproject.toml")]
        self.assertEqual(climbs('lib = "../../../vendor/lib"\n', moves=moves),
                         [("../../../vendor/lib", ("rewrite", "retain"),
                           "../../vendor/lib", True)])
        self.assertEqual(climbs('top = "../../../../up"\n', moves=moves),
                         [("../../../../up", ("rewrite", "retain"),
                           "../../../up", True)])

    def test_a_shallower_move_that_cannot_climb_less_is_retained(self):
        moves = [(TOOL + "/pyproject.toml", "pyproject.toml")]
        # P = .claude/notes/tool (depth 3), Q = "" (depth 0): delta -3.
        self.assertEqual(climbs('lib = "../../../vendor/lib"\n', moves=moves),
                         [("../../../vendor/lib", ("retain",), None, True)])

    def test_an_unmoved_or_unread_file_has_no_depth_occurrence(self):
        self.assertEqual(climbs('lib = "../../../vendor/lib"\n',
                                path="tools/a/b/c.toml",
                                paths=DEPTH_PATHS + ["tools/a/b/c.toml"]), [])

    def test_the_class_and_policy_of_a_depth_occurrence(self):
        texts = {TOOL + "/pyproject.toml": 'lib = "../../../vendor/lib"\n',
                 TOOL + "/uv.lock": 'source = "../../../vendor/lib"\n'}
        self.assertEqual(
            [(o.subject, o.occurrence_class, o.policy, o.target)
             for o in depth_found(texts)],
            [(TOOL + "/pyproject.toml:1:8", ".toml/depth",
              NOTES + ":.toml/depth", TOOL_NEW + "/pyproject.toml"),
             (TOOL + "/uv.lock:1:11", ".lock/depth", NOTES + ":.lock/depth",
              TOOL_NEW + "/uv.lock")])

    def test_the_depth_read_set_gets_the_depth_reading_only(self):
        text = 'lib = "../../../vendor/lib"\nspec = ".claude/specs/x.md"\n'
        path = TOOL + "/pyproject.toml"
        self.assertEqual([o.depth for o in depth_found({path: text})], [True])
        self.assertEqual(
            [(o.subject, o.depth) for o in depth_found(
                {path: text}, scanned={path: text})],
            [(path + ":1:8", True), (path + ":2:9", False)])
        self.assertEqual(
            [o.depth for o in adopt_references.plan_references(
                {path: text}, DEPTH_PATHS, DEPTH_MOVES,
                DEPTH_TREES).occurrences], [False])

    def test_an_archived_file_is_its_own_directory(self):
        path = ".claude/odd.toml"
        moves = [(path, ".agents/knowledge/archive/adopted/.claude/odd.toml")]
        self.assertEqual(
            climbs('a = "./../x"\nb = "../../y"\n', path=path, moves=moves,
                   trees={path: path}, paths=[path]),
            [("./../x", ("rewrite", "retain"), "./../../../../../x", True),
             ("../../y", ("rewrite", "retain"), "../../../../../../y", True)])

    def test_the_depth_policy_partitions_answers_and_edits(self):
        path = TOOL + "/pyproject.toml"
        text = 'lib = "../../../vendor/lib"\nspec = ".claude/specs/x.md"\n'
        refs = adopt_references.plan_references(
            {path: text}, DEPTH_PATHS, DEPTH_MOVES, DEPTH_TREES,
            depth_texts={path: text})
        toml, depth = NOTES + ":.toml", NOTES + ":.toml/depth"
        _, climb = sorted(refs.occurrences, key=lambda o: o.depth)
        self.assertEqual(adopt_references.effective_answer(
            climb, {}, {toml: "rewrite"}), (None, None))
        self.assertEqual(adopt_references.effective_answer(
            climb, {}, {depth: "rewrite"}), ("rewrite", "policy"))
        answers = {toml: "retain", depth: "rewrite"}
        self.assertEqual(
            [(row["subject"], row["class"], row["recommended"],
              row["rewritten"], row["retained"])
             for row in adopt_references.policy_summary(refs, {}, answers)],
            [(toml, ".toml", "rewrite", 0, 1),
             (depth, ".toml/depth", None, 1, 0)])
        self.assertEqual(
            adopt_references.rewritten(refs, {}, answers),
            {TOOL_NEW + "/pyproject.toml": (
                text, text.replace("../../../", "../../../../"))})
        self.assertEqual(adopt_references.rewritten(
            refs, {}, {toml: "retain", depth: "retain"}), {})


RUN = TOOL + "/run.py"
BOUND = "HERE = Path(__file__).resolve().parent\n"


def chains(text, **kwargs):
    return [(o.subject, o.literal, o.answers, o.replacement)
            for o in depth_found({RUN: text}, **kwargs)]


def heights(text):
    return [height for _, _, height in adopt_references.python_climbs(text)]


class PythonClimbTest(unittest.TestCase):
    """#380 D2: parent-count chains anchored at the file's own location."""

    def test_anchored_chains_and_their_heights(self):
        for text, expected in (
                ("R = Path(__file__).parents[3]\n", [3]),
                ("R = pathlib.Path(__file__).resolve().parent.parent\n", [1]),
                ("R = Path(__file__).absolute().parent.parents[1]\n", [2]),
                (BOUND + "R = HERE.parents[2]\n", [0, 3]),
                ("F: Path = Path(__file__)  # me\nR = F.parent.parent\n", [1]),
                ("R = Path(__file__).parents[2].joinpath('x')\n", [2])):
            with self.subTest(text=text):
                self.assertEqual(heights(text), expected)
        for text in ("R = os.path.dirname(os.path.dirname(__file__))\n",
                     "R = Path.cwd().parents[2]\n",
                     "R = Path(__file__).parents[i]\n",
                     "R = Path(__file__).parents[1].parent\n",
                     "R = Path(__file__).parent.parents[i]\n",
                     "R = Path(__file__) .parent\n",
                     "R = MyPath(__file__).parent\n",
                     "R = x.Path(__file__).parent\n",
                     "R = Path(__file__)\n"):
            with self.subTest(text=text):
                self.assertEqual(heights(text), [])

    def test_only_a_name_never_rebound_is_followed(self):
        for text, expected in (
                ("HERE = Path(__file__).parent\nHERE = Path('.')\n"
                 "R = HERE.parents[2]\n", [0]),
                (BOUND + 'HERE /= "/fixed/a/b/c"\nROOT = HERE.parents[2]\n',
                 [0]),
                (BOUND + "for HERE in xs:\n    pass\nR = HERE.parents[2]\n",
                 [0]),
                (BOUND + "def f():\n    HERE = 1\nR = HERE.parents[2]\n",
                 [0]),
                ("def f():\n    HERE = Path(__file__).parent\n"
                 "    return HERE.parents[2]\n", [0]),
                (BOUND + "ROOT = HERE.parents[2]\nX = ROOT.parent\n", [0, 3]),
                ("UP = Path(__file__).parents[2]\nX = UP.parent\n", [2]),
                (BOUND + "R = self.HERE.parents[2]\nS = MYHERE.parent\n",
                 [0]),
                ("here = Path(__file__).parent\ndef f(here):\n"
                 "    return here.parent\n", [0]),
                (BOUND + "def m(self, HERE):\n"
                 "    return HERE.parent.parent\n", [0]),
                (BOUND + "F = lambda HERE: HERE.parents[1]\n", [0])):
            with self.subTest(text=text):
                self.assertEqual(heights(text), expected)

    def test_a_chain_to_the_root_is_rewritten(self):
        text = (BOUND + "ROOT = HERE.parents[2]\n"
                "UP = Path(__file__).parent.parent.parent.parent\n")
        self.assertEqual(chains(text), [
            (RUN + ":2:12", ".parents[2]", ("rewrite", "retain"),
             ".parents[3]"),
            (RUN + ":3:20", ".parent.parent.parent.parent",
             ("rewrite", "retain"), ".parent.parent.parent.parent.parent")])

    def test_crlf_line_ends_read_like_lf(self):
        crlf = (BOUND + "ROOT = HERE.parents[2]\n").replace("\n", "\r\n")
        self.assertEqual(heights(crlf), [0, 3])
        self.assertEqual(chains(crlf), [
            (RUN + ":2:12", ".parents[2]", ("rewrite", "retain"),
             ".parents[3]")])
        refs = adopt_references.plan_references(
            {RUN: crlf}, DEPTH_PATHS, DEPTH_MOVES, DEPTH_TREES,
            depth_texts={RUN: crlf})
        self.assertEqual(
            adopt_references.rewritten(
                refs, {}, {NOTES + ":.py/depth": "rewrite"}),
            {TOOL_NEW + "/run.py": (
                crlf, crlf.replace(".parents[2]", ".parents[3]"))})

    def test_chains_inside_the_tree_are_not_surfaced(self):
        self.assertEqual(chains(BOUND + "NOTES = HERE.parent\n"
                                "T = Path(__file__).parents[1]\n"), [])

    def test_a_landing_point_only_above_the_old_directory_is_retained(self):
        self.assertEqual(chains("C = Path(__file__).parents[2]\n"), [
            (RUN + ":1:19", ".parents[2]", ("retain",), None)])

    def test_a_shallower_move_that_cannot_climb_less_is_retained(self):
        text = (BOUND + "R = HERE.parents[2]\n"
                "S = Path(__file__).parent.parent.parent.parent\n")
        self.assertEqual(chains(text, moves=[(RUN, "run.py")]), [
            (RUN + ":2:9", ".parents[2]", ("retain",), None),
            (RUN + ":3:19", ".parent.parent.parent.parent",
             ("rewrite", "retain"), ".parent")])

    def test_only_python_files_are_read_for_chains(self):
        path = TOOL + "/run.sh"
        self.assertEqual(depth_found(
            {path: "R = Path(__file__).parents[2]\n"},
            moves=DEPTH_MOVES + [(path, TOOL_NEW + "/run.sh")],
            trees={**DEPTH_TREES, path: NOTES},
            paths=DEPTH_PATHS + [path]), ())

    def test_a_chain_overlapping_a_token_occurrence_is_dropped(self):
        text = ("HERE = Path(__file__).parent\n"
                "Y = .claude/specs/x.md+HERE.parents[2]\n")
        self.assertEqual(
            [(o.subject, o.depth)
             for o in depth_found({RUN: text}, scanned={RUN: text})],
            [(RUN + ":2:5", False)])
        self.assertEqual([o.subject for o in depth_found({RUN: text})],
                         [RUN + ":2:28"])

    def test_a_chain_inside_a_text_climb_is_dropped(self):
        text = BOUND + 'S = "../../../HERE.parents[2]"\n'
        self.assertEqual(chains(text), [
            (RUN + ":2:6", "../../../HERE.parents[2]", ("rewrite", "retain"),
             "../../../../HERE.parents[2]")])
        refs = adopt_references.plan_references(
            {RUN: text}, DEPTH_PATHS, DEPTH_MOVES, DEPTH_TREES,
            depth_texts={RUN: text})
        self.assertEqual(
            adopt_references.rewritten(
                refs, {}, {NOTES + ":.py/depth": "rewrite"}),
            {TOOL_NEW + "/run.py": (
                text, text.replace("../../../", "../../../../"))})


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

    TREES = {".claude/specs/x.md": ".claude/specs",
             ".claude/specs/data.txt": ".claude/specs",
             ".claude/plans/y.md": ".claude/plans"}

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
            self.root, "HEAD", self.MOVES, excluded, self.TREES).occurrences]

    def test_only_scanned_files_yield_occurrences(self):
        self.assertEqual(self.subjects(["config/owners.txt"]),
                         [".claude/keep.json:1:10",
                          ".claude/specs/data.txt:1:1", "tools/check.py:1:29"])
        self.assertEqual(self.subjects(),
                         [".claude/keep.json:1:10",
                          ".claude/specs/data.txt:1:1", "config/owners.txt:1:1",
                          "tools/check.py:1:29"])

    def test_forced_colour_does_not_hide_the_candidates(self):
        git(self.root, "config", "color.ui", "always")
        self.assertEqual(self.subjects(["config/owners.txt"]),
                         [".claude/keep.json:1:10",
                          ".claude/specs/data.txt:1:1", "tools/check.py:1:29"])

    def test_the_revision_is_read_not_the_working_tree(self):
        (self.root / "tools/check.py").write_text("nothing\n",
                                                  encoding="utf-8")
        self.assertIn("tools/check.py:1:29", self.subjects())

    def test_no_moves_is_no_reference(self):
        self.assertEqual(
            adopt_references.derive_references(self.root, "HEAD", [], [], {}),
            adopt_references.References({}, ()))


class DepthDerivationTest(unittest.TestCase):
    """#380 D7: the depth reading's own read set, beside the first-segment
    prefilter's."""

    FILES = {
        ".claude/specs/tool/run.py": b"ROOT = Path(__file__).parents[2]\n",
        ".claude/specs/tool/both.toml":
            b'lib = "../../../vendor/lib"\nspec = ".claude/plans/y.md"\n',
        ".claude/specs/tool/notes.md": b"[up](../../../README.md)\n",
        ".claude/specs/tool/blob.bin": b"\x00../../../x\n",
        ".claude/specs/tool/.env.ci": b"../../../x\n",
        ".claude/specs/tool/dots.txt": b"see ../../../README.md\n",
        ".claude/plans/y.md": b"# y\n",
        ".claude/odd.py": b"UP = Path(__file__).parents[1]\n",
        "tools/up.py": b"ROOT = Path(__file__).parents[1]\nX = '../x/y'\n",
        "README.md": b"# r\n",
    }
    MOVES = [(p, p.replace(".claude/specs", SPECS, 1)) for p in (
        ".claude/specs/tool/run.py", ".claude/specs/tool/both.toml",
        ".claude/specs/tool/notes.md", ".claude/specs/tool/blob.bin",
        ".claude/specs/tool/.env.ci", ".claude/specs/tool/dots.txt")] + [
        (".claude/plans/y.md", ".agents/artifacts/plans/y.md"),
        (".claude/odd.py", ".agents/knowledge/archive/adopted/.claude/odd.py")]
    TREES = {**{s: "/".join(s.split("/")[:2]) for s, _ in MOVES},
             ".claude/odd.py": ".claude/odd.py"}

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        git(self.root, "init", "--quiet", "-b", "main")
        git(self.root, "config", "commit.gpgsign", "false")
        for path, data in self.FILES.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        git(self.root, "add", "-A", "-f")
        git(self.root, "commit", "--quiet", "-m", "fixture")

    def found(self, excluded=(), moves=None, trees=None):
        return [(o.subject, o.depth)
                for o in adopt_references.derive_references(
                    self.root, "HEAD", self.MOVES if moves is None else moves,
                    excluded, self.TREES if trees is None else trees
                ).occurrences]

    def test_moved_text_files_holding_a_climb_are_read(self):
        self.assertEqual(self.found(), [
            (".claude/odd.py:1:20", True),
            (".claude/specs/tool/both.toml:1:8", True),
            (".claude/specs/tool/both.toml:2:9", False),
            (".claude/specs/tool/dots.txt:1:5", True),
            (".claude/specs/tool/run.py:1:22", True)])

    def test_excluded_files_are_not_read(self):
        self.assertEqual(self.found([".claude/specs/tool/run.py"]), [
            (".claude/odd.py:1:20", True),
            (".claude/specs/tool/both.toml:1:8", True),
            (".claude/specs/tool/both.toml:2:9", False),
            (".claude/specs/tool/dots.txt:1:5", True)])

    def test_a_move_no_file_names_is_still_read_for_climbs(self):
        # No blob holds `tools`, so the first-segment prefilter finds nothing.
        self.assertEqual(
            self.found(moves=[("tools/up.py", "lib/tools/up.py")],
                       trees={"tools/up.py": "tools"}),
            [("tools/up.py:1:22", True), ("tools/up.py:2:6", True)])


if __name__ == "__main__":
    unittest.main()
