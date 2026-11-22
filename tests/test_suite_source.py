"""The test sources `agent_tools.delivery.suite_source` reads for the stack rules (#1464).

Measures the library against source text: each family lexes to tokens with
comments and whitespace dropped and strings kept whole (an interpolating string
split around its holes, whose contents are lexed as ordinary tokens), regex
literals, JSX closing tags, operators, C# string forms and preprocessor lines
are read as the stack's language defines them, and Python's refusal is no
token list; a path is a test file by its stack's rules; every stack shard
prefix of the standards has a registry row; a snapshot yields its decoded,
lexed test files in path order; and each family's test declarations yield their
line, body tokens, span and enclosing suite headers.
"""

import unittest
from pathlib import Path

from agent_tools.delivery import rule_ids
from agent_tools.delivery.never_rise import Snapshot
from agent_tools.delivery.suite_source import (
    STACKS, TestFile, Token, attribute_sections, family_of, lex, read_test_files,
    test_functions)

TIER = "fast"

REPO_ROOT = Path(__file__).resolve().parents[1]
STANDARDS_README = REPO_ROOT / "home/common/agent-skills/standards/README.md"
BACKTICK = "`"


def texts(family: str, source: str) -> list[str]:
    return [token.text for token in lex(family, source)]


class LexTest(unittest.TestCase):
    def test_each_family_lexes_without_comments_and_whitespace_keeping_strings_whole(self):
        python = texts("python", 'a = "it.skip(" # self.skipTest()\nb\n')
        javascript = lex("javascript", "a = 'x' // it.skip(\n/* xit( */ b")
        csharp = texts("csharp", 'var s = @"a""b"; // [Ignore]')

        self.assertEqual(python, ["a", "=", '"it.skip("', "<newline>", "b", "<newline>"])
        self.assertEqual([t.text for t in javascript], ["a", "=", "'x'", "b"])
        self.assertEqual(javascript[-1].line, 2)
        self.assertEqual(csharp, ["var", "s", "=", '@"a""b"', ";"])

    def test_a_template_literal_hole_is_lexed_as_tokens_between_its_literal_pieces(self):
        template = f"f({BACKTICK}a${{ {{b: 1}}.b }}c{BACKTICK})"
        plain = f"x = {BACKTICK}ran ${{e.argv.join(' ')}}{BACKTICK}"
        commented = f"x = {BACKTICK}ran ${{e.argv /* c */ .join(' ')}}{BACKTICK}"
        other = f"x = {BACKTICK}ran ${{e.argv.join(',')}}{BACKTICK}"

        self.assertEqual(texts("javascript", template), [
            "f", "(", f"{BACKTICK}a${{", "{", "b", ":", "1", "}", ".", "b",
            f"}}c{BACKTICK}", ")"])
        self.assertEqual(texts("javascript", commented), [
            "x", "=", f"{BACKTICK}ran ${{", "e", ".", "argv", ".", "join", "(", "' '", ")",
            f"}}{BACKTICK}"])
        self.assertEqual(texts("javascript", plain), texts("javascript", commented))
        self.assertNotEqual(texts("javascript", other), texts("javascript", commented))

    def test_a_regex_literal_is_one_token_and_division_is_an_operator(self):
        self.assertEqual(texts("javascript", "x = /[/{]'/g; y = a / b; z = {}/2"), [
            "x", "=", "/[/{]'/g", ";", "y", "=", "a", "/", "b", ";",
            "z", "=", "{", "}", "/", "2"])

    def test_an_unterminated_quote_ends_at_its_line(self):
        tokens = lex("javascript", "<p>Don't</p>\n}")

        self.assertEqual(tokens[-1], Token("}", 2, 0, "op"))

    def test_csharp_interpolated_raw_and_char_literals(self):
        source = '$"{a["k"]}" """x " y""" ' + "'\\''"

        tokens = lex("csharp", source)

        self.assertEqual([t.text for t in tokens], [
            '$"{', "a", "[", '"k"', "]", '}"', '"""x " y"""', "'\\''"])
        self.assertEqual([t.kind for t in tokens], [
            "string", "name", "op", "string", "op", "string", "string", "string"])

    def test_multi_character_operators_are_one_token(self):
        for family in ("javascript", "csharp"):
            with self.subTest(family=family):
                self.assertEqual(texts(family, "a == b => c != d = e"), [
                    "a", "==", "b", "=>", "c", "!=", "d", "=", "e"])

    def test_a_python_file_the_tokenizer_refuses_is_none(self):
        self.assertIsNone(lex("python", 'x = """open\n'))

    def test_an_unknown_family_is_refused(self):
        with self.assertRaises(ValueError):
            lex("ruby", "x")

    def test_a_jsx_closing_tag_is_operators_and_keeps_every_bracket(self):
        source = ("it('a', () => { render(<p>hi</p>) })\n"
                  "it.skip('b', () => { render(<p>x</p>) })")

        tokens = lex("javascript", source)

        render = ["{", "render", "(", "<", "p", ">"]
        closing = ["<", "/", "p", ">", ")", "}", ")"]
        self.assertEqual([t.text for t in tokens],
                         ["it", "(", "'a'", ",", "(", ")", "=>"] + render + ["hi"] + closing
                         + ["it", ".", "skip", "(", "'b'", ",", "(", ")", "=>"] + render + ["x"]
                         + closing)
        self.assertEqual([t.line for t in tokens if t.text == "skip"], [2])

    def test_an_unterminated_regex_literal_ends_at_its_line(self):
        tokens = lex("javascript", "x = /ab\ny")

        self.assertEqual([t.text for t in tokens], ["x", "=", "/ab", "y"])
        self.assertEqual(tokens[-1].line, 2)

    def test_csharp_preprocessor_lines_are_dropped(self):
        source = ('public class T {\n#region Skipped\n[Fact(Skip = "x")]\n#endregion\n}')

        self.assertEqual(texts("csharp", source), [
            "public", "class", "T", "{", "[", "Fact", "(", "Skip", "=", '"x"', ")", "]", "}"])
        self.assertIn("#", texts("javascript", "#region Skipped"))


class SelectionTest(unittest.TestCase):
    def test_test_files_are_selected_by_their_stacks_rules(self):
        paths = [
            "tests/test_a.py", "pkg/a_test.py", "conftest.py", "src/helpers.py", "src/Foo.cs",
            "web/b.test.ts", "web/b.spec.tsx", "web/__tests__/c.js", "test/c.mjs",
            "web/run-test.cjs", "src/app.ts", "types/x.d.ts", "tests/fixtures/page.js",
            "README.md"]

        self.assertEqual({path: family_of(path) for path in paths}, {
            "tests/test_a.py": "python", "pkg/a_test.py": "python", "conftest.py": "python",
            "src/helpers.py": None, "src/Foo.cs": "csharp", "web/b.test.ts": "javascript",
            "web/b.spec.tsx": "javascript", "web/__tests__/c.js": "javascript",
            "test/c.mjs": "javascript", "web/run-test.cjs": "javascript", "src/app.ts": None,
            "types/x.d.ts": None, "tests/fixtures/page.js": None, "README.md": None})

    def test_every_stack_shard_prefix_has_a_row(self):
        table = rule_ids.prefix_table(STANDARDS_README.read_text(encoding="utf-8"))

        self.assertEqual({prefix for key, prefix in table.items() if key.startswith("stacks/")},
                         {stack.prefix for stack in STACKS})

    def test_read_test_files_yields_decoded_lexed_test_files_in_path_order(self):
        texts_by_path = {
            "tests/test_b.py": b"x = 1\n", "tests/test_a.py": b"y\n", "src/a.py": b"z\n",
            "tests/test_bad.py": b"\xff\xfe", "tests/test_tok.py": b'x = """\n'}
        snapshot = Snapshot("a" * 40, {path: 1 for path in texts_by_path}, texts_by_path)

        files = read_test_files(snapshot)

        self.assertEqual([f.path for f in files], ["tests/test_a.py", "tests/test_b.py"])
        self.assertEqual(files[0].family, "python")
        self.assertEqual(files[0].text, "y\n")


def test_file(family: str, source: str) -> TestFile:
    return TestFile("t", family, source, tuple(lex(family, source)))


def declared(family: str, source: str) -> list[tuple[int, tuple[str, ...] | None]]:
    return [(f.line, f.body) for f in test_functions(test_file(family, source))]


def range_texts(file: TestFile, bounds: tuple[int, int]) -> list[str]:
    return [file.tokens[i].text for i in range(*bounds)]


RUN = ("run", "(", ")", ";")
CS_RUN = ("Run", "(", ")", ";")


class TestFunctionsTest(unittest.TestCase):
    def test_each_familys_test_functions_yield_their_body_tokens_and_line(self):
        python = ("class T(unittest.TestCase):\n    def test_a(self):\n"
                  "        x = 1  # note\n        self.assertEqual(x, 1)\n")
        javascript = "it('a', () => {\n  expect(1).toBe(1); // c\n});\n"
        csharp = "[Fact]\npublic void A() { Assert.True(true); }\n"

        self.assertEqual(declared("python", python), [(2, (
            "x", "=", "1", "<newline>", "self", ".", "assertEqual", "(", "x", ",", "1", ")"))])
        self.assertEqual(declared("javascript", javascript), [(1, (
            "expect", "(", "1", ")", ".", "toBe", "(", "1", ")", ";"))])
        self.assertEqual(declared("csharp", csharp), [(2, (
            "Assert", ".", "True", "(", "true", ")", ";"))])

    def test_python_tests_are_test_named_defs_at_module_or_class_level(self):
        source = ("def helper():\n    pass\nasync def test_b():\n    pass\n"
                  "def test_outer():\n    def test_inner():\n        pass\n"
                  "class A:\n    class B:\n        def test_c(self):\n            pass\n")

        self.assertEqual([line for line, _ in declared("python", source)], [3, 5, 10])

    def test_python_indentation_is_part_of_the_body_and_its_width_is_not(self):
        inside = declared("python", "def test_a():\n    if a:\n        x()\n        y()\n")
        after = declared("python", "def test_a():\n    if a:\n        x()\n    y()\n")
        method = declared(
            "python", "class A:\n    def test_a(self):\n        if a:\n"
            "            x()\n            y()\n")

        self.assertNotEqual(inside[0][1], after[0][1])
        self.assertEqual(inside[0][1], method[0][1])

    def test_a_python_body_with_non_ascii_text_ends_at_its_last_token(self):
        plain = "def test_a(self):\n    self.assertEqual(s, \"\u00e9\")\n"
        noted = "def test_a(self):\n    self.assertEqual(s, \"\u00e9\")  # note\n"
        expected = ("self", ".", "assertEqual", "(", "s", ",", '"\u00e9"', ")")

        self.assertEqual(declared("python", plain), [(1, expected)])
        self.assertEqual(declared("python", noted), [(1, expected)])

    def test_javascript_declarations_with_and_without_a_callback(self):
        source = "\n".join([
            "test.concurrent('a', async () => { run(); })",
            'it.only("b", function () { run(); })',
            "specify('c', done => { run(); })",
            "it('d', () => expect(1).toBe(1))",
            "describe('s', () => {",
            "  test('e', async (): Promise<void> => { run(); })",
            "})",
            "fit('f', () => { run(); })",
            "xit('g', () => { run(); })",
            "test.skipIf(x)('h', () => { run(); })",
            "it('i')",
            "it.todo('j')",
            "test.describe('s', () => {})",
            "test.beforeEach(() => {})",
            "test.step('k', () => {})"])

        self.assertEqual(declared("javascript", source), [
            (1, RUN), (2, RUN), (3, RUN),
            (4, ("expect", "(", "1", ")", ".", "toBe", "(", "1", ")")),
            (6, RUN), (8, RUN), (9, RUN), (10, RUN), (11, None), (12, None)])

    def test_csharp_attributes_and_expression_bodies(self):
        source = "\n".join([
            "public class T {", "#region Skipped", "[Fact]", "public void A() { Run(); }",
            "#endregion", "[Theory]", "[InlineData(1)]",
            "public async Task B(int x) => await Run(x);", '[Test, Category("x")]',
            "public void C() { Run(); }", "[TestMethod]", "public void D() { Run(); }",
            "[Xunit.Fact]", "public void E() { Run(); }", "[InlineData(1)]",
            "public void F() { Run(); }", "public void H() { Run(); }", "[Fact]",
            "public void G<T>() where T : new() { Run(); }", "}"])

        self.assertEqual(declared("csharp", source), [
            (4, CS_RUN), (8, ("await", "Run", "(", "x", ")")), (10, CS_RUN), (12, CS_RUN),
            (14, CS_RUN), (19, CS_RUN)])

    def test_a_python_file_ast_cannot_parse_has_no_test_functions(self):
        self.assertEqual(declared("python", "def test_a(self):\n    return = 1\n"), [])

    def test_spans_and_scopes_cover_each_declaration_and_its_suite_headers(self):
        python = test_file("python", "\n".join([
            "pytestmark = 2", '@unittest.skip("x")', "class A(unittest.TestCase):",
            "    pytestmark = 1", "    @dec", "    def test_a(self):", "        pass", ""]))
        javascript = test_file("javascript", "describe.skip('s', () => {\n"
                               "  it('a', () => { run(); })\n})")
        csharp = test_file("csharp", '[TestFixture, Ignore("x")]\npublic class C {\n[Test]\n'
                           "public void A() { Run(); }\n}")

        [py], [js], [cs] = (test_functions(f) for f in (python, javascript, csharp))

        self.assertIn("dec", range_texts(python, py.span))
        self.assertIn("pass", range_texts(python, py.span))
        self.assertNotIn("pytestmark", range_texts(python, py.span))
        self.assertEqual([range_texts(python, r) for r in py.scopes], [[
            "@", "unittest", ".", "skip", "(", '"x"', ")", "<newline>", "class", "A", "(",
            "unittest", ".", "TestCase", ")", ":", "<newline>", "<indent>"],
            ["pytestmark", "=", "1"], ["pytestmark", "=", "2"]])
        self.assertEqual(range_texts(javascript, js.span), [
            "it", "(", "'a'", ",", "(", ")", "=>", "{", "run", "(", ")", ";", "}", ")"])
        self.assertEqual([range_texts(javascript, r) for r in js.scopes], [[
            "describe", ".", "skip", "(", "'s'", ",", "(", ")", "=>", "{"]])
        self.assertEqual(range_texts(csharp, cs.span), [
            "[", "Test", "]", "public", "void", "A", "(", ")", "{", "Run", "(", ")", ";", "}"])
        self.assertEqual([range_texts(csharp, r) for r in cs.scopes], [[
            "[", "TestFixture", ",", "Ignore", "(", '"x"', ")", "]", "public", "class", "C",
            "{"]])

    def test_attribute_sections_open_only_at_declaration_positions(self):
        tokens = lex("csharp", "var a = b[0]; [Fact] void A() {}")

        [(start, end)] = attribute_sections(tokens)

        self.assertEqual([t.text for t in tokens[start:end]], ["[", "Fact", "]"])


if __name__ == "__main__":
    unittest.main()
