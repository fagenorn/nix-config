"""The comment reader of `agent_tools.delivery.comment_syntax` and the lint built on it.

Measures what each stack's lexer reads as a comment block: a comment inside a
string, a heredoc body or a block scalar is not one, a docstring is one block
bounded by its string literal, a run of own-line comments is one block and a
comment after code stands alone, and a file that cannot be lexed never raises.

The suite holds `standard:B18`, `standard:B19` and `standard:B20`, the comment rules, by
running their enforcers (`agent_tools.delivery.comment_lint`) over a fixture per stack,
over hand-built snapshots and over real git worlds, so the rule index lists this suite.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

from agent_tools.delivery import comment_lint, comment_syntax, never_rise, rule_ids
from agent_tools.delivery.comment_syntax import Block
from agent_tools.delivery.never_rise import Rise, Snapshot, Violation
from tests.test_never_rise import commit_all, fixture_env, git, mark_base, repo, write

TIER = "integration"

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests/fixtures/comment-lint"
BAR = REPO_ROOT / "home/common/agent-skills/standards/the-bar.md"
REPOSITORY = "fixture-owner/fixture-repo"

COMMON = [("B18", 13), ("B18", 15), ("B19", 23), ("B19", 32), ("B20", 34)]
EXPECTED = {
    "module.py": [("B18", 13), ("B18", 15), ("B19", 23), ("B19", 32), ("B19", 39), ("B20", 34)],
    "module.mjs": COMMON,
    "module.ts": COMMON,
    "Module.cs": COMMON,
    "default.nix": [("B18", 14), ("B18", 16), ("B19", 24), ("B19", 33), ("B20", 35)],
    "script.sh": COMMON + [("B20", 39)],
    "workflow.yaml": COMMON + [("B20", 40)],
    "justfile": COMMON,
}


def cite(token: str) -> str:
    return "standard" + ":" + token


def lines(*rows: str) -> str:
    return "\n".join(rows) + "\n"


class CommentSyntaxTest(unittest.TestCase):
    def test_each_hash_stack_reads_its_comments_and_skips_its_strings(self):
        python = lines(
            "#!/usr/bin/env python3",
            '"""Module doc."""',
            "import os",
            "",
            "# one",
            "# two",
            'x = "# not a comment"  # trailing',
            "",
            "",
            "def f():",
            '    """Doc line one.',
            "",
            "    Doc line three.",
            '    """',
            "    return 1",
        )
        shell = lines(
            "#!/bin/sh",
            "# header line",
            "set -eu",
            """echo "# no" '# no' x#y ${#x}  # yes""",
            "cat <<EOF",
            "# in heredoc",
            "EOF",
            "# after",
        )
        just = lines("# Build it.", "build:", '  echo "# no"  # yes', "  # body comment")
        yaml = lines(
            "# Header.",
            "on: push  # trailing",
            "jobs:",
            "  a:",
            "    run: |",
            "      # shell comment in a block scalar",
            '      echo "#x"',
            '    name: "# quoted"',
            "# end",
        )
        cases = (
            ("python", "tool.py", python, (
                Block(2, 2, ('"""Module doc."""',), True),
                Block(5, 6, ("# one", "# two"), False),
                Block(7, 7, ("# trailing",), False),
                Block(11, 14, ('"""Doc line one.', "", "    Doc line three.", '    """'), False),
            )),
            ("shell", "run.sh", shell, (
                Block(2, 2, ("# header line",), True),
                Block(4, 4, ("# yes",), False),
                Block(8, 8, ("# after",), False),
            )),
            ("just", "justfile", just, (
                Block(1, 1, ("# Build it.",), True),
                Block(3, 3, ("# yes",), False),
                Block(4, 4, ("# body comment",), False),
            )),
            ("yaml", "ci.yaml", yaml, (
                Block(1, 1, ("# Header.",), True),
                Block(2, 2, ("# trailing",), False),
                Block(9, 9, ("# end",), False),
            )),
        )
        for stack, path, text, expected in cases:
            with self.subTest(stack=stack):
                self.assertEqual(comment_syntax.blocks(path, text), expected)

    def test_a_blank_line_splits_a_run_and_a_trailing_comment_stands_alone(self):
        text = "x = 1\n# a\n# b\n\n# c\ny = 2  # d\n# e\n"
        self.assertEqual(comment_syntax.blocks("a.py", text), (
            Block(2, 3, ("# a", "# b"), False),
            Block(5, 5, ("# c",), False),
            Block(6, 6, ("# d",), False),
            Block(7, 7, ("# e",), False),
        ))

    def test_a_python_file_that_does_not_tokenize_is_read_line_by_line(self):
        self.assertEqual(
            comment_syntax.blocks("a.py", "x = (\n# c\n"), (Block(2, 2, ("# c",), False),))

    def test_reading_python_emits_no_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            found = comment_syntax.blocks("a.py", 'x = "\\d"\n# c\n')
        self.assertEqual(caught, [])
        self.assertEqual(found, (Block(2, 2, ("# c",), False),))

    def test_a_quoted_or_dashed_heredoc_delimiter_hides_its_body(self):
        text = "cat <<-'END'\n\t# no\n\tEND\n# yes\n"
        self.assertEqual(comment_syntax.blocks("a.sh", text), (Block(4, 4, ("# yes",), False),))

    def test_an_arithmetic_shift_is_not_a_heredoc(self):
        text = "mask=$((1 << 4))\n# a\n(( mask <<= 1 ))\n# b\necho 4\n"
        self.assertEqual(comment_syntax.blocks("a.sh", text), (
            Block(2, 2, ("# a",), False),
            Block(4, 4, ("# b",), False),
        ))

    def test_a_shift_after_a_reserved_word_is_not_a_heredoc(self):
        for first in ("if (( mask << 1 )); then", "while (( mask << 1 )); do", "! (( mask << 1 ))"):
            with self.subTest(first=first):
                text = first + "\n# TODO\nfi\n"
                self.assertEqual(
                    comment_syntax.blocks("a.sh", text), (Block(2, 2, ("# TODO",), False),))

    def test_a_here_string_queues_no_heredoc(self):
        for first in ('read -r a <<< "$x"', "cat <<<EOF", 'jq . <<<"$EVAL"'):
            with self.subTest(first=first):
                text = first + "\n# c\necho\n"
                self.assertEqual(
                    comment_syntax.blocks("a.sh", text), (Block(2, 2, ("# c",), False),))

    def test_an_apostrophe_inside_a_plain_scalar_opens_no_quote(self):
        text = "- name: Download this run's suite timing\n  # TODO later\n  run: echo it's\n# end\n"
        self.assertEqual(comment_syntax.blocks("a.yaml", text), (
            Block(2, 2, ("# TODO later",), False),
            Block(4, 4, ("# end",), False),
        ))

    def test_a_docstring_s_text_stops_at_its_closing_quotes(self):
        text = '"""doc"""; value = "TODO #12"\n' + "".join(f"# c{n}\n" for n in range(6))
        self.assertEqual(comment_syntax.blocks("a.py", text), (
            Block(1, 1, ('"""doc"""',), True),
            Block(2, 7, tuple(f"# c{n}" for n in range(6)), False),
        ))
        self.assertEqual(
            comment_syntax.blocks("a.py", '"""é"""; x = 1\n'),
            (Block(1, 1, ('"""é"""',), True),))

    def test_a_block_scalar_with_chomping_keeps_its_indicator_comment(self):
        text = "key: |- # c\n  # content\nnext: 1\n"
        self.assertEqual(comment_syntax.blocks("a.yaml", text), (Block(1, 1, ("# c",), False),))

    def test_a_block_scalar_ends_where_the_indentation_falls_below_its_content(self):
        text = "run: |\n    echo hi\n\n    # inside\n  # TODO\nnext: 1\n"
        self.assertEqual(comment_syntax.blocks("a.yaml", text), (Block(5, 5, ("# TODO",), False),))

    def test_a_file_with_no_code_is_all_header(self):
        self.assertEqual(comment_syntax.blocks("a.yaml", "# a\n\n# b\n"), (
            Block(1, 1, ("# a",), True),
            Block(3, 3, ("# b",), True),
        ))

    def test_the_stack_comes_from_the_name_or_the_shebang(self):
        table = (
            ("a.py", "", "python"),
            ("a.PYI", "", "python"),
            ("a.bash", "", "shell"),
            ("a.yml", "", "yaml"),
            ("justfile", "", "just"),
            (".justfile", "", "just"),
            ("x.just", "", "just"),
            ("bin/tool", "#!/usr/bin/env bash", "shell"),
            ("bin/tool", "#!/usr/bin/env -S python3.13 -I", "python"),
            ("bin/tool", "#!/bin/dash", "shell"),
            ("bin/data", "plain", None),
            ("README.md", "# Title", None),
            ("module.py.fixture", "", None),
        )
        for path, first, expected in table:
            with self.subTest(path=path, first=first):
                self.assertEqual(comment_syntax.stack_of(path, first + "\n"), expected)
        self.assertEqual(comment_syntax.blocks("README.md", "# Title\n"), ())

    def test_no_hash_lexer_raises_on_unbalanced_text(self):
        texts = ("'", '"', "$'", "<<", "<<EOF\n", "key: |\n", '"""', "#", "\r\n#x\r\n", "")
        for path in ("a.py", "a.sh", "justfile", "a.yaml"):
            for text in texts:
                with self.subTest(path=path, text=text):
                    self.assertIsInstance(comment_syntax.blocks(path, text), tuple)


    def test_each_c_family_and_nix_stack_reads_its_comments_and_skips_its_strings(self):
        javascript = lines(
            "#!/usr/bin/env node",
            "// header",
            """const a = "// no"; const b = '/* no */';""",
            "const t = `x ${ \"/*\" } // no`; // yes",
            "const r = /\\/\\/ no/g; /* one",
            "two */ f();",
        )
        typescript = lines(
            "/**", " * Header doc.", " */", "export type A = { b: string }; // yes")
        csharp = lines(
            "// header",
            'var a = "// no"; var b = @"C:\\ ""/* no */""";',
            'var c = """',
            "    // raw no",
            '    """; /// yes',
            "char d = '/'; /* x */ int e;",
        )
        nix = lines(
            "# header",
            "{ pkgs, ... }:",
            "let",
            '  a = "# no ${ "/* no */" }";',
            "  b = ''",
            "    # no, inside an indented string",
            "    ''${x} '''",
            "  ''; # yes",
            "  /* block */ c = 1;",
            "in a",
        )
        cases = (
            ("javascript", "tool.mjs", javascript, (
                Block(2, 2, ("// header",), True),
                Block(4, 4, ("// yes",), False),
                Block(5, 6, ("/* one", "two */"), False),
            )),
            ("typescript", "mod.ts", typescript, (
                Block(1, 3, ("/**", " * Header doc.", " */"), True),
                Block(4, 4, ("// yes",), False),
            )),
            ("csharp", "Mod.cs", csharp, (
                Block(1, 1, ("// header",), True),
                Block(5, 5, ("/// yes",), False),
                Block(6, 6, ("/* x */",), False),
            )),
            ("nix", "default.nix", nix, (
                Block(1, 1, ("# header",), True),
                Block(8, 8, ("# yes",), False),
                Block(9, 9, ("/* block */",), False),
            )),
        )
        for stack, path, text, expected in cases:
            with self.subTest(stack=stack):
                self.assertEqual(comment_syntax.blocks(path, text), expected)

    def test_a_division_is_not_a_regex(self):
        self.assertEqual(
            comment_syntax.blocks("a.js", "const x = a / b; // yes\n"),
            (Block(1, 1, ("// yes",), False),))

    def test_a_postfix_increment_before_a_division_is_not_a_regex(self):
        for text in ("const half = i++ / 2; // TODO\n", "const half = i-- / 2; // TODO\n"):
            with self.subTest(text=text):
                self.assertEqual(
                    comment_syntax.blocks("a.js", text), (Block(1, 1, ("// TODO",), False),))

    def test_a_typescript_non_null_assertion_before_a_division_is_not_a_regex(self):
        for text in (
            "const half = value! / 2; // TODO\n",
            "const half = (a + b)! / 2; // TODO\n",
            "const half = xs[0]! / 2; // TODO\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    comment_syntax.blocks("a.ts", text), (Block(1, 1, ("// TODO",), False),))

    def test_a_logical_not_before_a_regex_literal_is_still_a_regex(self):
        self.assertEqual(
            comment_syntax.blocks("a.js", "const no = !/a\\/\\/b/.test(s); // TODO\n"),
            (Block(1, 1, ("// TODO",), False),))

    def test_a_jsx_closing_tag_is_not_a_regex(self):
        self.assertEqual(
            comment_syntax.blocks("a.jsx", "const el = <p>ok</p>; // TODO\n"),
            (Block(1, 1, ("// TODO",), False),))

    def test_a_jsx_self_closing_slash_after_an_attribute_expression_is_not_a_regex(self):
        for text in (
            "const el = <Foo bar={x} />; // TODO\n",
            "const el = <Foo {...props} />; // TODO\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    comment_syntax.blocks("a.tsx", text), (Block(1, 1, ("// TODO",), False),))

    def test_a_csharp_interpolation_lexes_its_nested_string(self):
        for text in (
            'var s = $"{Get("/* TODO */")}"; // yes\n',
            'var r = $$"""{{Get("// no")}} {x}"""; // yes\n',
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    comment_syntax.blocks("a.cs", text), (Block(1, 1, ("// yes",), False),))

    def test_a_nested_template_hides_its_comment_markers(self):
        for text in (
            'const s = `${ `${ "//" }` } /*`; // yes\n',
            'const s = `${ "`" } /*`; // yes\n',
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    comment_syntax.blocks("a.js", text), (Block(1, 1, ("// yes",), False),))

    def test_a_nix_indented_string_keeps_its_escapes_and_holes(self):
        for text in (
            "x = ''\n  ''${\"# no\"}\n'';  # yes\n",
            "x = ''\n  ${ \"''\" } # no\n'';  # yes\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    comment_syntax.blocks("a.nix", text), (Block(3, 3, ("# yes",), False),))

    def test_an_unterminated_block_comment_runs_to_the_last_line(self):
        self.assertEqual(
            comment_syntax.blocks("a.js", "x();\n/* a\nb\n"),
            (Block(2, 4, ("/* a", "b", ""), False),))

    def test_adjacent_line_comments_of_both_forms_are_one_run(self):
        self.assertEqual(
            comment_syntax.blocks("a.cs", "int a;\n/// doc\n// more\n"),
            (Block(2, 3, ("/// doc", "// more"), False),))

    def test_the_new_suffixes_name_their_stacks(self):
        table = (
            ("a.js", "javascript"), ("a.cjs", "javascript"), ("a.jsx", "javascript"),
            ("a.mts", "javascript"), ("a.cts", "javascript"), ("a.tsx", "javascript"),
            ("a.csx", "csharp"), ("a.nix", "nix"),
        )
        for path, expected in table:
            with self.subTest(path=path):
                self.assertEqual(comment_syntax.stack_of(path, "\n"), expected)
        self.assertEqual(
            comment_syntax.STACKS,
            ("python", "shell", "yaml", "just", "javascript", "csharp", "nix"))

    def test_no_c_family_or_nix_lexer_raises_on_unbalanced_text(self):
        texts = (
            "/*", "'", '"', "`", "`${", "/", '@"', '"""', "''", "${", "}", "''$", "")
        for path in ("a.mjs", "a.cs", "a.nix"):
            for text in texts:
                with self.subTest(path=path, text=text):
                    self.assertIsInstance(comment_syntax.blocks(path, text), tuple)


def run_command(*arguments, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "agent_tools.delivery.comment_lint", *arguments],
        capture_output=True, text=True, timeout=60, env=fixture_env(), cwd=cwd)


class FixtureTest(unittest.TestCase):
    def test_each_stack_fixture_prints_its_violations_and_nothing_else(self):
        fixtures = sorted(FIXTURES.glob("*.fixture"))
        self.assertEqual({f.name.removesuffix(".fixture") for f in fixtures}, set(EXPECTED))
        for fixture in fixtures:
            target = fixture.name.removesuffix(".fixture")
            with self.subTest(fixture=target), tempfile.TemporaryDirectory() as tmp:
                root = repo(tmp)
                shutil.copyfile(fixture, root / target)
                commit_all(root)
                done = run_command("--repo-root", str(root), "--repository", REPOSITORY)
                lines = "".join(f"{rule} {target}:{line}\n" for rule, line in EXPECTED[target])
                self.assertEqual((done.returncode, done.stdout), (1, lines), done.stderr)
                rules = {"module.py": ["B18", "B18", "B19", "B19", "B19", "B20"],
                         "script.sh": ["B18", "B18", "B19", "B19", "B20", "B20"],
                         "workflow.yaml": ["B18", "B18", "B19", "B19", "B20", "B20"]}
                self.assertEqual(
                    sorted(rule for rule, _ in EXPECTED[target]),
                    rules.get(target, ["B18", "B18", "B19", "B19", "B20"]))

    def test_every_covered_stack_has_a_fixture(self):
        found = {}
        for fixture in FIXTURES.glob("*.fixture"):
            target = fixture.name.removesuffix(".fixture")
            found[target] = comment_syntax.stack_of(target, fixture.read_text("utf-8"))
        self.assertEqual(set(found.values()), set(comment_syntax.STACKS))
        self.assertIn("module.mjs", found)
        self.assertIn("module.ts", found)


class BarRuleTest(unittest.TestCase):
    def test_the_bar_holds_the_three_comment_rules_and_not_the_old_sentence(self):
        text = BAR.read_text("utf-8")
        found = rule_ids.sections(text)
        self.assertLessEqual({"B18", "B19", "B20"}, set(found))
        self.assertNotIn("the code already says what", text)
        self.assertTrue("TODO" in found["B20"] and "FIXME" in found["B20"])
        self.assertTrue("TODO" not in found["B2"] and "FIXME" not in found["B2"])
        link = "https://github.com/fagenorn/nix-config/issues/1420"
        clauses = {
            "B18": ("does not restate the code", "name an issue or pull request",
                    "a decision-record id", "the condition for removing it"),
            "B19": ("at most five lines", "at most 120 characters",
                    "a module docstring or file header is exempt"),
            "B20": ("`TODO`", "`FIXME`"),
        }
        for rule, wanted in clauses.items():
            self.assertIn(link, found[rule], rule)
            for clause in wanted:
                with self.subTest(rule=rule, clause=clause):
                    self.assertIn(clause, found[rule])

    def test_the_rule_ids_are_rules_of_the_bar(self):
        found = rule_ids.sections(BAR.read_text("utf-8"))
        rules = tuple(enforcer.rule for enforcer in comment_lint.enforcers(None))
        self.assertEqual(rules, ("B18", "B19", "B20"))
        for rule in rules:
            self.assertIn(rule, found)


class ReferenceTest(unittest.TestCase):
    def test_a_slash_comment_delimiter_does_not_hide_a_shorthand(self):
        for text in ("//#12", "///#12", "/*#12*/", "// #12"):
            with self.subTest(text=text):
                self.assertTrue(comment_lint.references(text, REPOSITORY))

    def test_each_issue_or_pull_request_form_is_a_reference(self):
        forms = (
            "# see #12", "# (issue 608)", "# issues 1412 and 1414", "# Issue #3", "# PR 1618",
            "# PR #7", "# pull request 9", "# GH-4",
            "# https://github.com/fixture-owner/fixture-repo/pull/15",
            "# fixture-owner/fixture-repo#5",
            "# HTTPS://WWW.GITHUB.COM/Fixture-Owner/Fixture-Repo/issues/1",
            "# https://github.com/upstream/GH-42/issues/7 see #12",
        )
        for text in forms:
            with self.subTest(text=text):
                self.assertTrue(comment_lint.references(text, REPOSITORY))

    def test_other_text_is_not_a_reference(self):
        plain = (
            "# ADR-delivery-015 D3", "# " + cite("B12"), "# noqa: E501",
            "# https://github.com/upstream/project/issues/42 (drop once fixed)",
            "# https://github.com/upstream/GH-42/issues/7", "# https://example.com/docs#12",
            "// &#123;", "# color #fff", "# 12 steps", "# prefix#12", "# the issue at hand",
        )
        for text in plain:
            with self.subTest(text=text):
                self.assertFalse(comment_lint.references(text, REPOSITORY))

    def test_without_a_repository_only_the_shorthand_forms_count(self):
        own = "# https://github.com/fixture-owner/fixture-repo/pull/15"
        self.assertFalse(comment_lint.references(own, None))
        self.assertTrue(comment_lint.references("# see #12", None))


def snapshot(**contents):
    files = {path.replace("__", "."): text.encode() for path, text in contents.items()}
    return Snapshot("a" * 40, {}, contents=files)


def found(rule, snap):
    enforcer = next(e for e in comment_lint.enforcers(None) if e.rule == rule)
    return enforcer.find(snap)


def hash_lines(*rows):
    return "\n".join(rows) + "\n"


class RuleTest(unittest.TestCase):
    def test_a_header_is_exempt_from_length_but_not_from_references_or_markers(self):
        wide = "w" * 124 + " #12"
        doc = hash_lines('"""Header one.', "Header two.", wide, "Header four.", "TODO five",
                         "Header six.", 'Header seven."""', "x = 1")
        snap = snapshot(a__py=doc)
        self.assertEqual(found("B18", snap), [Violation("B18", "a.py", 3)])
        self.assertEqual(found("B19", snap), [])
        self.assertEqual(found("B20", snap), [Violation("B20", "a.py", 5)])

    def test_a_module_docstring_sharing_its_closing_line_with_code_is_header(self):
        doc = '"""one\ntwo\nthree\nfour\nfive\nsix"""; import os\n'
        self.assertTrue(comment_syntax.blocks("a.py", doc)[0].header)
        self.assertEqual(found("B19", snapshot(a__py=doc)), [])

    def test_a_byte_order_mark_does_not_hide_a_python_trailing_comment(self):
        snap = snapshot(a__py="\ufeffx = 1  # TODO\n")
        self.assertEqual(found("B20", snap), [Violation("B20", "a.py", 1)])

    def test_five_lines_and_120_characters_pass_and_six_and_121_fail(self):
        text = hash_lines(
            "x=1", *["# five"] * 5, "y=2", *["# six"] * 6, "z=3", "# " + "q" * 118, "w=4",
            "# " + "q" * 119)
        self.assertEqual(
            found("B19", snapshot(a__sh=text)),
            [Violation("B19", "a.sh", 8), Violation("B19", "a.sh", 17)])

    def test_a_long_block_with_a_long_first_line_is_one_violation(self):
        text = hash_lines("x=1", "# " + "z" * 119, *["# row"] * 5)
        self.assertEqual(found("B19", snapshot(a__sh=text)), [Violation("B19", "a.sh", 2)])

    def test_a_long_trailing_comment_line_counts(self):
        text = hash_lines("x = 1", "y = 2  # " + "z" * 112)
        self.assertEqual(found("B19", snapshot(a__py=text)), [Violation("B19", "a.py", 2)])

    def test_a_line_with_two_references_is_one_violation(self):
        text = hash_lines("x = 1", "# #1 and #2")
        self.assertEqual(found("B18", snapshot(a__py=text)), [Violation("B18", "a.py", 2)])

    def test_a_marker_in_a_string_is_not_counted(self):
        snap = snapshot(a__py='x = "TODO #12"\n')
        self.assertEqual((found("B18", snap), found("B20", snap)), ([], []))

    def test_an_uncovered_file_is_not_read(self):
        snap = Snapshot("a" * 40, {}, contents={"notes.md": b"# TODO #12\n"})
        for rule in ("B18", "B19", "B20"):
            self.assertEqual(found(rule, snap), [], rule)


class NeverRiseCommentTest(unittest.TestCase):
    def judge(self, base, branch):
        with tempfile.TemporaryDirectory() as tmp:
            root = repo(tmp)
            for path, text in base.items():
                write(root, path, text)
            commit_all(root)
            mark_base(root)
            for path, text in branch.items():
                write(root, path, text)
            commit_all(root)
            enforcers = list(comment_lint.enforcers(REPOSITORY))
            return never_rise.judge(root, "main", enforcers, timeout=60)

    def test_a_branch_adding_a_todo_comment_rises_on_b20(self):
        verdict = self.judge({"a.py": "x = 1\n"}, {"a.py": "x = 1\n# TODO: finish\n"})
        self.assertEqual(verdict.rises, (Rise("B20", 0, 1, (Violation("B20", "a.py", 2),)),))

    def test_a_branch_adding_an_issue_reference_rises_on_b18(self):
        verdict = self.judge({"a.py": "x = 1\n"}, {"a.py": "x = 1\n# fixes #12\n"})
        self.assertEqual(verdict.rises, (Rise("B18", 0, 1, (Violation("B18", "a.py", 2),)),))

    def test_existing_comments_are_carried_by_the_merge_base(self):
        base = {"a.py": "x = 1\n# fixes #12\n# TODO: x\n"}
        self.assertEqual(self.judge(base, {"b.py": "y = 2\n"}).rises, ())

    def test_a_removed_reference_does_not_hide_a_new_todo(self):
        verdict = self.judge({"a.py": "x = 1\n# fixes #12\n"}, {"a.py": "x = 1\n# TODO: x\n"})
        self.assertEqual([rise.rule for rise in verdict.rises], ["B20"])


class CommandTest(unittest.TestCase):
    def committed(self, tmp, text):
        root = repo(tmp)
        write(root, "a.py", text)
        commit_all(root)
        return root

    def test_a_clean_tree_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.committed(tmp, "x = 1  # why\n")
            done = run_command("--repo-root", str(root))
            self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_violations_print_in_rule_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.committed(tmp, "x = 1\n# TODO #12\n")
            done = run_command("--repo-root", str(root))
            self.assertEqual((done.returncode, done.stdout), (1, "B18 a.py:2\nB20 a.py:2\n"))

    def test_a_bad_repository_or_a_relative_root_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.committed(tmp, "x = 1\n")
            for arguments in (("--repo-root", str(root), "--repository", "nope"),
                              ("--repo-root", "repo")):
                with self.subTest(arguments=arguments):
                    done = run_command(*arguments)
                    self.assertEqual((done.returncode, done.stdout), (2, ""))
                    self.assertTrue(done.stderr.startswith("comment-lint: "), done.stderr)

    def test_the_command_is_a_row_of_the_command_table(self):
        table = (REPO_ROOT / "lib/agent-tools.nix").read_text("utf-8")
        self.assertIn('"comment-lint" = "delivery.comment_lint";', table)
        verdicts = REPO_ROOT / "python/agent_tools/delivery/command_verdicts.json"
        self.assertIsNone(json.loads(verdicts.read_text("utf-8"))["comment-lint"])


if __name__ == "__main__":
    unittest.main()
