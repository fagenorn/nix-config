"""The comment reader of `agent_tools.delivery.comment_syntax` and the lint built on it.

Measures what each stack's lexer reads as a comment block: a comment inside a
string, a heredoc body or a block scalar is not one, a docstring is one block
bounded by its string literal, a run of own-line comments is one block and a
comment after code stands alone, and a file that cannot be lexed never raises.
"""

import unittest
import warnings

from agent_tools.delivery import comment_syntax
from agent_tools.delivery.comment_syntax import Block

TIER = "integration"


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
            Block(1, 1, ('"""doc"""',), False),
            Block(2, 7, tuple(f"# c{n}" for n in range(6)), False),
        ))
        self.assertEqual(
            comment_syntax.blocks("a.py", '"""é"""; x = 1\n'),
            (Block(1, 1, ('"""é"""',), False),))

    def test_a_block_scalar_with_chomping_keeps_its_indicator_comment(self):
        text = "key: |- # c\n  # content\nnext: 1\n"
        self.assertEqual(comment_syntax.blocks("a.yaml", text), (Block(1, 1, ("# c",), False),))

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

    def test_a_jsx_closing_tag_is_not_a_regex(self):
        self.assertEqual(
            comment_syntax.blocks("a.jsx", "const el = <p>ok</p>; // TODO\n"),
            (Block(1, 1, ("// TODO",), False),))

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


if __name__ == "__main__":
    unittest.main()
