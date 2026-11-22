"""The test sources of each stack, read as tokens for the stack rules (#1464).

A library with no command. It names the stacks of the standards, picks a
snapshot's test files by each stack's rules and lexes them, so a rule counts
code and never a comment or a string's contents.

A test file is named by its repository-relative POSIX path, suffix compared
exactly. Python: the file name matches `test*.py` or `*_test.py`, or is
`conftest.py`. C#: every `.cs` file, since the frameworks find tests by
attribute. JavaScript and TypeScript: the suffix is one of the stack rows'
suffixes, the name does not end `.d.ts`, and the name before the suffix ends
with `.test`, `.spec`, `-test` or `_test`, starts with `test-` or is `test`,
or a directory component is `__tests__` or `test`.

Tokens carry the text, the 1-based line, the 0-based column in characters and a
kind: `name`, `op`, `string`, `number` and, for Python only, `newline`,
`indent` and `dedent`. Comments and whitespace are never tokens. Python comes
from the standard tokenizer (`tokenize.TokenError` and `SyntaxError` give
`None`; f-string parts are `string` tokens); C# and JavaScript share one lexer
core. A string without interpolation is one `string` token with its raw text;
an interpolating string is one `string` token per literal run with the hole's
contents lexed as ordinary tokens between them. A JavaScript regex literal is
one token unless the previous token makes `/` a division, or ends right before
it with `<` (a JSX closing tag). A C# quote left open ends at its line; a
JavaScript quote left open is an operator token of its own and lexing goes on
right after it, so an apostrophe in JSX text hides no bracket after it. C# drops
a preprocessor line (`#region`, `#if`) through its end from the tokens and keeps
it, whitespace collapsed and a trailing `//` comment dropped, in
`TestFile.directives`.

`test_functions` is the one reader of test declarations: each test's line, body
tokens, declaration span and the header ranges (token-index ranges) of the
suites whose markers apply to it. The test name, decorators, attributes,
parameters and a JavaScript title are never in a body. Python: a `test*` def at
module level or directly in a class body, read from `ast` with every column
converted from UTF-8 bytes to characters before it meets a token; a file `ast`
refuses has none. JavaScript: a call whose callee chain has a test root and only
test modifiers (a suite root or `test.describe` and only suite modifiers makes a
suite), whose last function argument is the callback; with no function argument, the last
argument after the title that is no object literal, string or number (a named
function, a call) is the body; no callback and no such argument is a test with
no body. A `skip` or `fixme` call that states a condition, outside every test,
makes its enclosing suite's header range a scope of every test inside that
suite, or of every test of the file when it is in no suite. C#: a method whose run of attribute sections names a test
attribute; `class`, `record` and `struct` declarations are suites, headed from
their first attribute section. A C# body also holds each directive of
`TestFile.directives` between its braces, in order, so two bodies guarded by
different conditions are never the same body.
"""

import ast
import bisect
import io
import re
import tokenize
import warnings
from collections.abc import Sequence
from typing import NamedTuple

from agent_tools.delivery.never_rise import Snapshot

FAMILIES = ("python", "csharp", "javascript")

JS_TEST_ROOTS = ("it", "test", "specify", "xit", "xtest", "xspecify", "fit")
JS_SUITE_ROOTS = ("describe", "context", "suite", "xdescribe", "fdescribe", "xcontext", "xsuite")
CS_TEST_ATTRIBUTES = (
    "Fact", "Theory", "Test", "TestCase", "TestCaseSource", "TestMethod", "DataTestMethod",
    "SkippableFact", "SkippableTheory")
JS_TEST_MEMBERS = frozenset({
    "only", "skip", "todo", "concurrent", "sequential", "fails", "failing", "fixme", "skipIf",
    "runIf", "each"})
JS_SUITE_MEMBERS = frozenset({
    "only", "skip", "todo", "concurrent", "sequential", "shuffle", "skipIf", "runIf", "each"})
JS_ARGUMENT_MEMBERS = frozenset({"skipIf", "runIf", "each"})
JS_ANNOTATION_MEMBERS = frozenset({"skip", "fixme"})
CS_MODIFIERS = frozenset({
    "public", "internal", "private", "protected", "static", "sealed", "abstract", "partial",
    "unsafe", "readonly", "ref", "file", "new", "async", "virtual", "override", "extern"})
CS_SUITE_KEYWORDS = ("class", "record", "struct")
BRACKETS = {"(": ")", "[": "]", "{": "}"}


class Token(NamedTuple):
    text: str
    line: int
    column: int
    kind: str


class Stack(NamedTuple):
    prefix: str
    family: str
    suffixes: tuple[str, ...]


STACKS = (
    Stack("PY", "python", (".py",)),
    Stack("NET", "csharp", (".cs",)),
    Stack("NODE", "javascript", (".js", ".mjs", ".cjs", ".jsx")),
    Stack("TSR", "javascript", (".ts", ".tsx", ".mts", ".cts")),
)

JS_TEST_STEM_ENDINGS = (".test", ".spec", "-test", "_test")
JS_TEST_DIRECTORIES = frozenset({"__tests__", "test"})

REGEX_AFTER_WORDS = frozenset({
    "return", "typeof", "case", "do", "else", "in", "instanceof", "new", "delete", "void",
    "throw", "yield", "await"})
OPERATORS = (
    "===", "!==", "**=", "...",
    "==", "!=", "=>", "<=", ">=", "&&", "||", "??", "?.", "++", "--", "+=", "-=", "*=", "/=",
    "%=", "&=", "|=", "^=", "**", "::")

IDENTIFIER = re.compile(r"(?:[^\W\d]|\$)(?:\w|\$)*")
NUMBER = re.compile(
    r"0[xX][0-9a-fA-F_]+[A-Za-z]*|\.?\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?[A-Za-z_]*")
CSHARP_STRING_PREFIX = re.compile(r"[$@]*\"")
REGEX_FLAGS = re.compile(r"[A-Za-z]*")


def python_test_name(name: str) -> bool:
    return ((name.startswith("test") and name.endswith(".py"))
            or name.endswith("_test.py") or name == "conftest.py")


def javascript_test_path(path: str, name: str, suffix: str) -> bool:
    if name.endswith(".d.ts"):
        return False
    stem = name[:-len(suffix)]
    if (stem.endswith(JS_TEST_STEM_ENDINGS) or stem.startswith("test-") or stem == "test"):
        return True
    return any(part in JS_TEST_DIRECTORIES for part in path.split("/")[:-1])


def family_of(path: str) -> str | None:
    """The family of a test file by its stack's rules, `None` for any other path."""
    name = path.rsplit("/", 1)[-1]
    for stack in STACKS:
        for suffix in stack.suffixes:
            if not name.endswith(suffix):
                continue
            if stack.family == "python":
                return "python" if python_test_name(name) else None
            if stack.family == "csharp":
                return "csharp"
            return "javascript" if javascript_test_path(path, name, suffix) else None
    return None


PYTHON_KINDS = {
    tokenize.NAME: "name", tokenize.OP: "op", tokenize.NUMBER: "number",
    tokenize.STRING: "string", tokenize.FSTRING_START: "string",
    tokenize.FSTRING_MIDDLE: "string", tokenize.FSTRING_END: "string",
    tokenize.ERRORTOKEN: "op"}
PYTHON_MARKS = {
    tokenize.NEWLINE: ("<newline>", "newline"), tokenize.INDENT: ("<indent>", "indent"),
    tokenize.DEDENT: ("<dedent>", "dedent")}


def lex_python(text: str) -> list[Token] | None:
    tokens: list[Token] = []
    try:
        for item in tokenize.generate_tokens(io.StringIO(text).readline):
            line, column = item.start
            if item.type in PYTHON_MARKS:
                mark, kind = PYTHON_MARKS[item.type]
                tokens.append(Token(mark, line, column, kind))
            elif item.type in PYTHON_KINDS:
                tokens.append(Token(item.string, line, column, PYTHON_KINDS[item.type]))
    except (tokenize.TokenError, SyntaxError):
        return None
    return tokens


class CLexer:
    """The lexer core C# and JavaScript share, one pass over the text."""

    def __init__(self, family: str, text: str):
        self.csharp = family == "csharp"
        self.text = text
        self.tokens: list[Token] = []
        self.starts = [0] + [i + 1 for i, c in enumerate(text) if c == "\n"]
        self.previous: Token | None = None
        self.previous_end = -1
        self.directives: list[Token] = []

    def emit(self, start: int, end: int, kind: str) -> None:
        line = bisect.bisect_right(self.starts, start) - 1
        token = Token(self.text[start:end], line + 1, start - self.starts[line], kind)
        self.tokens.append(token)
        self.previous = token
        self.previous_end = end

    def line_end(self, i: int) -> int:
        end = self.text.find("\n", i)
        return len(self.text) if end < 0 else end

    def directive(self, start: int, end: int) -> None:
        line = bisect.bisect_right(self.starts, start) - 1
        words = self.text[start:end].split("//", 1)[0].split()
        self.directives.append(
            Token(" ".join(words), line + 1, start - self.starts[line], "directive"))

    def run(self) -> list[Token]:
        self.scan(0, False)
        return self.tokens

    def scan(self, i: int, in_hole: bool) -> int:
        """Lex from `i`; in a hole return at its closing brace, else at the end."""
        text, depth = self.text, 0
        while i < len(text):
            char = text[i]
            if char.isspace():
                i += 1
            elif text.startswith("//", i):
                i = self.line_end(i)
            elif text.startswith("/*", i):
                end = text.find("*/", i + 2)
                i = len(text) if end < 0 else end + 2
            elif self.csharp and char == "#" and not text[
                    self.starts[bisect.bisect_right(self.starts, i) - 1]:i].strip():
                end = self.line_end(i)
                self.directive(i, end)
                i = end
            elif in_hole and char == "}" and depth == 0:
                return i
            else:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                i = self.token(i)
        return i

    def token(self, i: int) -> int:
        text, char = self.text, self.text[i]
        string_end = self.string(i)
        if string_end is not None:
            return string_end
        match = IDENTIFIER.match(text, i)
        if self.csharp and char == "@" and IDENTIFIER.match(text, i + 1):
            match = IDENTIFIER.match(text, i + 1)
        if match:
            self.emit(i, match.end(), "name")
            return match.end()
        match = NUMBER.match(text, i)
        if match:
            self.emit(i, match.end(), "number")
            return match.end()
        if char == "/" and not self.csharp and self.regex_allowed(i):
            end = self.regex_end(i)
            self.emit(i, end, "string")
            return end
        for operator in OPERATORS:
            if text.startswith(operator, i):
                self.emit(i, i + len(operator), "op")
                return i + len(operator)
        self.emit(i, i + 1, "op")
        return i + 1

    def regex_allowed(self, i: int) -> bool:
        previous = self.previous
        if previous is None:
            return True
        if previous.kind == "name":
            return previous.text in REGEX_AFTER_WORDS
        if previous.kind in ("number", "string"):
            return False
        if previous.text in (")", "]", "}"):
            return False
        return not (previous.text == "<" and self.previous_end == i)

    def regex_end(self, i: int) -> int:
        text, i, in_class = self.text, i + 1, False
        while i < len(text) and text[i] != "\n":
            char = text[i]
            if char == "\\" and i + 1 < len(text) and text[i + 1] != "\n":
                i += 2
                continue
            i += 1
            if char == "[":
                in_class = True
            elif char == "]":
                in_class = False
            elif char == "/" and not in_class:
                return REGEX_FLAGS.match(text, i).end()
        return i

    def string(self, i: int) -> int | None:
        text, char = self.text, self.text[i]
        if self.csharp:
            match = CSHARP_STRING_PREFIX.match(text, i)
            if match:
                return self.csharp_string(i, match.end() - 1)
            return self.quoted(i, "'") if char == "'" else None
        if char == "`":
            return self.interpolated(i, i + 1, "`", None, 0)
        return self.quoted(i, char) if char in "'\"" else None

    def quoted(self, start: int, quote: str) -> int:
        """A lenient quoted string: it ends at its closing quote or at its line.

        A JavaScript quote with no closing quote on its line is one operator token
        (an apostrophe in JSX text), never a string that swallows the line.
        """
        text, i = self.text, start + 1
        while i < len(text) and text[i] != "\n":
            if text[i] == "\\" and i + 1 < len(text) and text[i + 1] != "\n":
                i += 2
                continue
            i += 1
            if text[i - 1] == quote:
                self.emit(start, i, "string")
                return i
        if self.csharp:
            self.emit(start, i, "string")
            return i
        self.emit(start, start + 1, "op")
        return start + 1

    def csharp_string(self, start: int, quote_at: int) -> int:
        text = self.text
        prefix = text[start:quote_at]
        dollars, verbatim = prefix.count("$"), "@" in prefix
        count = 1
        while text.startswith('"', quote_at + count):
            count += 1
        if count >= 3 and not verbatim:
            return self.interpolated(start, quote_at + count, '"' * count, None, dollars)
        if count == 2 and not verbatim:
            self.emit(start, quote_at + 2, "string")
            return quote_at + 2
        if dollars or verbatim:
            return self.interpolated(start, quote_at + 1, '"', verbatim, dollars)
        return self.quoted(start, '"')

    def interpolated(self, start: int, i: int, closer: str, verbatim: bool | None,
                     dollars: int) -> int:
        """Emit the literal runs of a string and lex each hole between them.

        `verbatim` is `None` for a raw or template string (no quote escapes: a
        raw string ends at its `closer`, a template at the backtick).
        """
        text, piece = self.text, start
        template = closer == "`"
        raw = verbatim is None and not template
        while i < len(text):
            char = text[i]
            if template and char == "\\":
                i += 2
            elif template and text.startswith("${", i):
                i = self.hole(piece, i + 2)
                piece = i
                if i >= len(text):
                    return i
                i += 1
            elif template and char == "`":
                self.emit(piece, i + 1, "string")
                return i + 1
            elif not template and char == "{" and dollars:
                run = 1
                while text.startswith("{", i + run):
                    run += 1
                if run < dollars if raw else run % 2 == 0:
                    i += run
                    continue
                i = self.hole(piece, i + run)
                piece = i
                if i >= len(text):
                    return i
                i += 1
            elif not template and text.startswith(closer, i) and char == '"':
                if verbatim and text.startswith('""', i):
                    i += 2
                    continue
                if raw:
                    run = 0
                    while text.startswith('"', i + run):
                        run += 1
                    if run < len(closer):
                        i += run
                        continue
                self.emit(piece, i + len(closer), "string")
                return i + len(closer)
            elif char == "\n" and verbatim is False:
                break
            elif char == "\\" and verbatim is False and i + 1 < len(text):
                i += 2 if text[i + 1] != "\n" else 1
            else:
                i += 1
        self.emit(piece, min(i, len(text)), "string")
        return min(i, len(text))

    def hole(self, piece: int, after_opener: int) -> int:
        """Emit the piece up to a hole's opener, lex the hole, return its closing brace."""
        self.emit(piece, after_opener, "string")
        self.previous = None
        return self.scan(after_opener, True)


def lex_file(family: str, text: str) -> tuple[list[Token], list[Token]] | None:
    """The tokens and the directive lines of `text`; `None` only when Python's tokenizer refuses."""
    if family == "python":
        tokens = lex_python(text)
        return None if tokens is None else (tokens, [])
    if family in ("csharp", "javascript"):
        lexer = CLexer(family, text)
        return lexer.run(), lexer.directives
    raise ValueError(f"unknown family {family!r}; expected one of {FAMILIES}")


def lex(family: str, text: str) -> list[Token] | None:
    """The tokens of `text` in `family`; `None` only when Python's tokenizer refuses."""
    lexed = lex_file(family, text)
    return None if lexed is None else lexed[0]


class TestFile(NamedTuple):
    __test__ = False

    path: str
    family: str
    text: str
    tokens: tuple[Token, ...]
    directives: tuple[Token, ...] = ()


def read_test_files(snapshot: Snapshot) -> list[TestFile]:
    """Every test file of the snapshot that decodes as UTF-8 and lexes, by path."""
    files = []
    for path in sorted(snapshot.texts):
        family = family_of(path)
        if family is None:
            continue
        try:
            text = snapshot.texts[path].decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        lexed = lex_file(family, text)
        if lexed is not None:
            files.append(TestFile(path, family, text, tuple(lexed[0]), tuple(lexed[1])))
    return files


class TestFunction(NamedTuple):
    __test__ = False

    line: int
    body: tuple[str, ...] | None
    span: tuple[int, int]
    scopes: tuple[tuple[int, int], ...]


def bracket_pairs(tokens: Sequence[Token]) -> dict[int, int]:
    """Each bracket operator's index to its partner's, both ways."""
    closers = {close: open_ for open_, close in BRACKETS.items()}
    pairs: dict[int, int] = {}
    stack: list[int] = []
    for i, token in enumerate(tokens):
        if token.kind != "op":
            continue
        if token.text in BRACKETS:
            stack.append(i)
        elif token.text in closers:
            for depth in range(len(stack) - 1, -1, -1):
                if tokens[stack[depth]].text == closers[token.text]:
                    pairs[stack[depth]] = i
                    pairs[i] = stack[depth]
                    del stack[depth:]
                    break
    return pairs


def texts_between(tokens: Sequence[Token], start: int, end: int) -> tuple[str, ...]:
    return tuple(token.text for token in tokens[start:end])


class PythonSource:
    """The `ast` of a Python test file, placed in its token list by character column."""

    def __init__(self, test_file: "TestFile", tree: ast.Module):
        self.tokens = test_file.tokens
        self.keys = [(token.line, token.column) for token in test_file.tokens]
        self.lines = test_file.text.split("\n")
        self.tree = tree

    def index(self, line: int, offset: int) -> int:
        """The first token at or after an `ast` position (its column is in UTF-8 bytes)."""
        text = self.lines[line - 1] if 0 < line <= len(self.lines) else ""
        column = len(text.encode("utf-8")[:offset].decode("utf-8", errors="ignore"))
        return bisect.bisect_left(self.keys, (line, column))

    def start(self, node: ast.AST) -> int:
        return self.index(node.lineno, node.col_offset)

    def end(self, node: ast.AST) -> int:
        return self.index(node.end_lineno, node.end_col_offset)

    def start_with_decorators(self, node: ast.AST) -> int:
        """The index of a statement's first token, its first decorator's `@` included."""
        decorators = getattr(node, "decorator_list", [])
        if not decorators:
            return self.start(node)
        at = self.start(decorators[0])
        return at - 1 if at and self.tokens[at - 1].text == "@" else at

    def first_on_line_of(self, node: ast.AST) -> int:
        decorators = getattr(node, "decorator_list", [])
        line = decorators[0].lineno if decorators else node.lineno
        return bisect.bisect_left(self.keys, (line, 0))

    def pytestmarks(self, body: list[ast.stmt]) -> list[tuple[int, int]]:
        marks = []
        for node in body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
            elif isinstance(node, ast.AnnAssign):
                target = node.target
            else:
                continue
            if isinstance(target, ast.Name) and target.id == "pytestmark":
                marks.append((self.start(node), self.end(node)))
        return marks

    def collect(self, nodes: list[ast.stmt], classes: list[tuple[int, int]],
                module_marks: list[tuple[int, int]], found: list[TestFunction]) -> None:
        for node in nodes:
            if isinstance(node, ast.ClassDef) and node.body:
                header = (self.first_on_line_of(node), self.start_with_decorators(node.body[0]))
                scopes = classes + [header] + self.pytestmarks(node.body)
                self.collect(node.body, scopes, module_marks, found)
            elif (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.name.startswith("test")):
                first = self.start_with_decorators(node.body[0])
                end = self.end(node)
                found.append(TestFunction(
                    node.lineno, texts_between(self.tokens, first, end),
                    (self.first_on_line_of(node), end), tuple(classes + module_marks)))


def python_tests(test_file: "TestFile") -> list[TestFunction]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(test_file.text)
    except (SyntaxError, ValueError, RecursionError):
        return []
    source = PythonSource(test_file, tree)
    found: list[TestFunction] = []
    source.collect(tree.body, [], source.pytestmarks(tree.body), found)
    return found


def javascript_chain(tokens: Sequence[Token], pairs: dict[int, int], i: int,
                     ) -> tuple[str, list[str], int] | None:
    """The root, members and call `(` index of the callee chain starting at token `i`."""
    if tokens[i].kind != "name" or (i and tokens[i - 1].text == "."):
        return None
    members: list[str] = []
    j = i + 1
    while j + 1 < len(tokens) and tokens[j].text == "." and tokens[j + 1].kind == "name":
        members.append(tokens[j + 1].text)
        j += 2
        if members[-1] in JS_ARGUMENT_MEMBERS and j < len(tokens) and tokens[j].text == "(":
            close = pairs.get(j)
            if close is not None and close + 1 < len(tokens) and (
                    tokens[close + 1].text in ("(", ".")):
                j = close + 1
    if j < len(tokens) and tokens[j].text == "(" and j in pairs:
        return tokens[i].text, members, j
    return None


def javascript_kind(root: str, members: list[str]) -> str | None:
    if root in JS_TEST_ROOTS and all(m in JS_TEST_MEMBERS for m in members):
        return "test"
    if root in JS_SUITE_ROOTS and all(m in JS_SUITE_MEMBERS for m in members):
        return "suite"
    if root == "test" and members[:1] == ["describe"] and all(
            m in JS_SUITE_MEMBERS for m in members[1:]):
        return "suite"
    return None


def javascript_function(tokens: Sequence[Token], pairs: dict[int, int], a: int, b: int,
                        ) -> tuple[int, int, int] | None:
    """`(header end, body start, body end)` when tokens `a..b` are a function expression."""
    i = a
    if tokens[i].text == "async" and i + 1 < b and tokens[i + 1].text != "=>":
        i += 1
    if tokens[i].text == "function":
        i += 1
        if i < b and tokens[i].text == "*":
            i += 1
        if i < b and tokens[i].kind == "name":
            i += 1
        if i >= b or i not in pairs:
            return None
        j = pairs[i] + 1
        while j < b and tokens[j].text != "{":
            j += 1
        if j < b and pairs.get(j) == b - 1:
            return j + 1, j + 1, b - 1
        return None
    if tokens[i].text == "(" and i in pairs:
        j = pairs[i] + 1
        if j < b and tokens[j].text == ":":
            while j < b and tokens[j].text != "=>":
                j = pairs[j] + 1 if j in pairs else j + 1
    elif tokens[i].kind == "name":
        j = i + 1
    else:
        return None
    if j >= b or tokens[j].text != "=>":
        return None
    if j + 1 < b and tokens[j + 1].text == "{" and pairs.get(j + 1) == b - 1:
        return j + 2, j + 2, b - 1
    return j + 1, j + 1, b


def top_level_arguments(tokens: Sequence[Token], pairs: dict[int, int], open_: int,
                        close: int) -> list[tuple[int, int]]:
    """The half-open token range of each non-empty top-level argument of a call."""
    found, start, i = [], open_ + 1, open_ + 1
    while i <= close:
        if i < close and i in pairs:
            i = pairs[i] + 1
            continue
        if i == close or tokens[i].text == ",":
            if start < i:
                found.append((start, i))
            start = i + 1
        i += 1
    return found


def javascript_callback(tokens: Sequence[Token], pairs: dict[int, int], open_: int,
                        close: int) -> tuple[int, int, int] | None:
    """The last top-level argument of the call that is a function, as `javascript_function`."""
    found = None
    for start, end in top_level_arguments(tokens, pairs, open_, close):
        found = javascript_function(tokens, pairs, start, end) or found
    return found


def javascript_reference(tokens: Sequence[Token], pairs: dict[int, int], open_: int,
                         close: int) -> tuple[int, int, int] | None:
    """The last argument after the title that names a body: no object literal, string or number."""
    found = None
    for start, end in top_level_arguments(tokens, pairs, open_, close)[1:]:
        literal = end - start == 1 and tokens[start].kind in ("string", "number")
        if not literal and tokens[start].text != "{":
            found = (start, start, end)
    return found


def javascript_annotation(tokens: Sequence[Token], pairs: dict[int, int], members: list[str],
                          open_: int, callback: tuple[int, int, int] | None) -> bool:
    """Whether a `skip` or `fixme` call states a condition, not a title and a callback."""
    if not members or members[-1] not in JS_ANNOTATION_MEMBERS:
        return False
    close, i = pairs[open_], open_ + 1
    while i < close and tokens[i].text != ",":
        i = pairs[i] + 1 if i in pairs else i + 1
    first = (open_ + 1, i)
    if first[1] - first[0] == 1 and tokens[first[0]].kind == "string":
        return False
    return callback is None or first[0] <= callback[1] < first[1]


def javascript_tests(test_file: "TestFile") -> list[TestFunction]:
    tokens = test_file.tokens
    pairs = bracket_pairs(tokens)
    tests: list[tuple[int, tuple[str, ...] | None, tuple[int, int]]] = []
    bodies: list[tuple[int, int]] = []
    suites: list[tuple[tuple[int, int], tuple[int, int]]] = []
    annotations: list[tuple[int, int]] = []
    for i in range(len(tokens)):
        chain = javascript_chain(tokens, pairs, i)
        kind = javascript_kind(chain[0], chain[1]) if chain else None
        if chain is None or kind is None:
            continue
        close = pairs[chain[2]]
        callback = javascript_callback(tokens, pairs, chain[2], close)
        if kind == "suite" and callback:
            suites.append(((i, callback[0]), (callback[1], callback[2])))
        elif kind == "test" and javascript_annotation(tokens, pairs, chain[1], chain[2], callback):
            annotations.append((i, close + 1))
        elif kind == "test":
            callback = callback or javascript_reference(tokens, pairs, chain[2], close)
            body = texts_between(tokens, callback[1], callback[2]) if callback else None
            tests.append((tokens[i].line, body, (i, close + 1)))
            if callback:
                bodies.append((callback[1], callback[2]))
    tests = [t for t in tests if not any(a <= t[2][0] and t[2][1] <= b for a, b in bodies)]
    outside = [a for a in annotations if not any(x <= a[0] and a[1] <= y for x, y in bodies)]
    insides = [inside for _, inside in suites]
    return [TestFunction(line, body, span, tuple(
        header for header, inside in sorted(suites)
        if inside[0] <= span[0] and span[1] <= inside[1]) + conditions(outside, insides, span))
        for line, body, span in tests]


def conditions(annotations: list[tuple[int, int]], insides: list[tuple[int, int]],
               span: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    """The condition calls outside every test that disable the test at `span`.

    An annotation belongs to the smallest suite body holding it, else to the file; it
    disables each test inside that suite, each test of the file in the second case.
    """
    found = []
    for annotation in annotations:
        holding = [b for b in insides if b[0] <= annotation[0] and annotation[1] <= b[1]]
        owner = min(holding, key=lambda b: b[1] - b[0]) if holding else None
        if owner is None or (owner[0] <= span[0] and span[1] <= owner[1]):
            found.append(annotation)
    return tuple(found)


def attribute_sections(tokens: Sequence[Token]) -> list[tuple[int, int]]:
    """The half-open token range of each C# attribute section, `[` through its `]`."""
    pairs = bracket_pairs(tokens)
    sections: list[tuple[int, int]] = []
    for i, token in enumerate(tokens):
        if token.text != "[" or token.kind != "op" or i not in pairs:
            continue
        if sections and i < sections[-1][1]:
            continue
        previous = tokens[i - 1].text if i else ";"
        if previous in (";", "{", "}") or (sections and sections[-1][1] == i):
            sections.append((i, pairs[i] + 1))
    return sections


def attribute_names(tokens: Sequence[Token], section: tuple[int, int]) -> list[str]:
    """The names a section applies, by last segment without a trailing `Attribute`."""
    names: list[str] = []
    expecting, depth, i, end = True, 0, section[0] + 1, section[1] - 1
    while i < end:
        token = tokens[i]
        if token.kind == "op":
            depth += token.text in BRACKETS
            depth -= token.text in BRACKETS.values()
            expecting = expecting or (token.text == "," and depth == 0)
        elif expecting and depth == 0 and token.kind == "name":
            if i + 1 < end and tokens[i + 1].text == ":":
                i += 2
                continue
            name = token.text
            while i + 2 < end and tokens[i + 1].text == "." and tokens[i + 2].kind == "name":
                name = tokens[i + 2].text
                i += 2
            names.append(name[:-9] if name.endswith("Attribute") and len(name) > 9 else name)
            expecting = False
        i += 1
    return names


def csharp_method(tokens: Sequence[Token], pairs: dict[int, int], start: int,
                  ) -> tuple[int, tuple[int, int], int] | None:
    """`(name index, body range, end)` of the method declared from token `start`."""
    i, count = start, len(tokens)
    while i < count:
        token = tokens[i]
        if token.kind == "op" and token.text == "(":
            before = tokens[i - 1]
            if before.text == ">" or (before.kind == "name" and before.text not in CS_MODIFIERS):
                break
        if token.kind == "op" and token.text in ("{", "}", ";", "=", "=>"):
            return None
        opens = token.kind == "op" and token.text in ("(", "[") and i in pairs
        i = pairs[i] + 1 if opens else i + 1
    else:
        return None
    name = i - 1
    if tokens[name].text == ">":
        depth = 0
        while name > start:
            depth += tokens[name].text == ">"
            depth -= tokens[name].text == "<"
            name -= 1
            if depth == 0:
                break
    j = pairs.get(i, count) + 1
    while j < count and tokens[j].text not in ("{", "=>", ";"):
        j = pairs[j] + 1 if tokens[j].text in ("(", "[") and j in pairs else j + 1
    if j >= count or tokens[j].text == ";":
        return None
    if tokens[j].text == "{":
        return (name, (j + 1, pairs[j]), pairs[j] + 1) if j in pairs else None
    k = j + 1
    while k < count and tokens[k].text != ";":
        opens = tokens[k].kind == "op" and tokens[k].text in BRACKETS and k in pairs
        k = pairs[k] + 1 if opens else k + 1
    return (name, (j + 1, k), k + 1) if k < count else None


def csharp_suites(tokens: Sequence[Token], pairs: dict[int, int],
                  sections: list[tuple[int, int]]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """`(header range, body range)` of each `class`, `record` or `struct` declaration."""
    section_ending = {end: start for start, end in sections}
    suites = []
    for k, token in enumerate(tokens):
        if token.kind != "name" or token.text not in CS_SUITE_KEYWORDS:
            continue
        if token.text != "record" and k and tokens[k - 1].text == "record":
            continue
        j = k + 1
        if token.text == "record" and j < len(tokens) and tokens[j].text in ("class", "struct"):
            j += 1
        if j >= len(tokens) or tokens[j].kind != "name" or tokens[j].text == "where":
            continue
        first = k
        while first and tokens[first - 1].text in CS_MODIFIERS:
            first -= 1
        while first in section_ending:
            first = section_ending[first]
        if first and tokens[first - 1].text not in (";", "{", "}"):
            continue
        while j < len(tokens) and tokens[j].text not in ("{", ";"):
            j = pairs[j] + 1 if tokens[j].text in ("(", "[") and j in pairs else j + 1
        if j < len(tokens) and tokens[j].text == "{" and j in pairs:
            suites.append(((first, j + 1), (j + 1, pairs[j])))
    return suites


def csharp_body(test_file: "TestFile", body: tuple[int, int]) -> tuple[str, ...]:
    """The body tokens of a C# method with each directive line between its first and last token."""
    tokens = test_file.tokens
    inside = [(token.line, token.column, token.text) for token in tokens[body[0]:body[1]]]
    if test_file.directives:
        low = (tokens[body[0] - 1].line, tokens[body[0] - 1].column)
        high = (tokens[body[1]].line, tokens[body[1]].column) if body[1] < len(tokens) else None
        inside += [(d.line, d.column, d.text) for d in test_file.directives
                   if low < (d.line, d.column) and (high is None or (d.line, d.column) < high)]
    return tuple(text for _, _, text in sorted(inside))


def csharp_tests(test_file: "TestFile") -> list[TestFunction]:
    tokens = test_file.tokens
    pairs = bracket_pairs(tokens)
    sections = attribute_sections(tokens)
    suites = csharp_suites(tokens, pairs, sections)
    runs: list[list[tuple[int, int]]] = []
    for section in sections:
        if runs and runs[-1][-1][1] == section[0]:
            runs[-1].append(section)
        else:
            runs.append([section])
    found = []
    for run in runs:
        if not any(name in CS_TEST_ATTRIBUTES for s in run for name in attribute_names(tokens, s)):
            continue
        method = csharp_method(tokens, pairs, run[-1][1])
        if method is None:
            continue
        name, body, end = method
        span = (run[0][0], end)
        found.append(TestFunction(
            tokens[name].line, csharp_body(test_file, body), span, tuple(
                header for header, inside in sorted(suites)
                if inside[0] <= span[0] and span[1] <= inside[1])))
    return found


def test_functions(test_file: TestFile) -> list[TestFunction]:
    """Every test the file declares by its family's rules, ordered by where it starts."""
    readers = {"python": python_tests, "csharp": csharp_tests, "javascript": javascript_tests}
    if test_file.family not in readers:
        raise ValueError(f"unknown family {test_file.family!r}; expected one of {FAMILIES}")
    return sorted(readers[test_file.family](test_file), key=lambda f: f.span[0])
