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


if __name__ == "__main__":
    unittest.main()
