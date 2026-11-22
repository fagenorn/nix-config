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
it with `<` (a JSX closing tag). A quote left open ends at its line. C# drops a
preprocessor line (`#region`, `#if`) through its end.
"""

import bisect
import io
import re
import tokenize
from typing import NamedTuple

from agent_tools.delivery.never_rise import Snapshot

FAMILIES = ("python", "csharp", "javascript")


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

    def emit(self, start: int, end: int, kind: str) -> None:
        line = bisect.bisect_right(self.starts, start) - 1
        token = Token(self.text[start:end], line + 1, start - self.starts[line], kind)
        self.tokens.append(token)
        self.previous = token
        self.previous_end = end

    def line_end(self, i: int) -> int:
        end = self.text.find("\n", i)
        return len(self.text) if end < 0 else end

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
                i = self.line_end(i)
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
        """A lenient quoted string: it ends at its closing quote or at its line."""
        text, i = self.text, start + 1
        while i < len(text) and text[i] != "\n":
            if text[i] == "\\" and i + 1 < len(text) and text[i + 1] != "\n":
                i += 2
                continue
            i += 1
            if text[i - 1] == quote:
                break
        self.emit(start, i, "string")
        return i

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


def lex(family: str, text: str) -> list[Token] | None:
    """The tokens of `text` in `family`; `None` only when Python's tokenizer refuses."""
    if family == "python":
        return lex_python(text)
    if family in ("csharp", "javascript"):
        return CLexer(family, text).run()
    raise ValueError(f"unknown family {family!r}; expected one of {FAMILIES}")


class TestFile(NamedTuple):
    __test__ = False

    path: str
    family: str
    text: str
    tokens: tuple[Token, ...]


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
        tokens = lex(family, text)
        if tokens is not None:
            files.append(TestFile(path, family, text, tuple(tokens)))
    return files
