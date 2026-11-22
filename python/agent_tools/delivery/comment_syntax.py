"""Reads one file's comment blocks, with one small lexer per comment syntax.

Public names:

- `Block(first, last, texts, header)`: one comment block, 1-based first and last
  line, the comment text of each line `first..last`, and whether the block is in
  the file header (it ends before the file's first line of code; every block of
  a file with no code is header).
- `STACKS`: the comment syntaxes read here.
- `stack_of(path, text)`: the syntax a file is read in, or `None` when its name
  and shebang name none (such a file is not read, since a syntax must be known to
  count its comments).
- `blocks(path, text)`: the file's blocks sorted by first line, `()` for a file
  with no known syntax. It never raises on any string and emits no warning.

Lines are `text.split("\n")` with one trailing carriage return dropped each. A
line-1 shebang is neither a comment nor code. Text inside a string, a heredoc
body or a YAML block scalar is never a comment. Consecutive lines that each hold
only a line comment form one block; a blank line, a code line or a trailing
comment ends the run, and a comment after code is a block of one line whose text
runs from its marker to the line end.

A Python docstring (module, class, function) is one block bounded by its string
literal's columns, which the AST gives as UTF-8 byte offsets. A Python file that
does not tokenize or parse is read by a line fallback: a line whose left-stripped
form starts with `#` is an own-line comment. A YAML quote opens a scalar only
where a scalar starts, a shell `<<` inside arithmetic is a shift and not a
heredoc, and the justfile is read as shell.

JavaScript and TypeScript, C# and Nix are read by one character scanner with a
stack of frames: a string or template literal is a frame, and a `${` or an
interpolation hole pushes a code frame that its matching brace pops. A `/*`
block comment is one block from its opening line to its closing line, `//` and
`///` (and the Nix `#`) are line comments, and an unterminated block comment runs
to the last line. In JavaScript a `/` opens a regular expression only after a
token that cannot end an operand and never directly after `<` (a JSX closing
tag), and JSX element text reads as code.
"""

import ast
import functools
import io
import re
import tokenize
import warnings
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import NamedTuple


class Block(NamedTuple):
    first: int
    last: int
    texts: tuple[str, ...]
    header: bool


class _Raw(NamedTuple):
    first: int
    last: int
    texts: tuple[str, ...]
    own_line: bool
    kind: str


STACKS: tuple[str, ...] = ("python", "shell", "yaml", "just", "javascript", "csharp", "nix")

SUFFIX_STACKS = {
    ".py": "python", ".pyi": "python",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".ksh": "shell",
    ".yaml": "yaml", ".yml": "yaml",
    ".just": "just",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "javascript", ".mts": "javascript", ".cts": "javascript", ".tsx": "javascript",
    ".cs": "csharp", ".csx": "csharp",
    ".nix": "nix",
}
JUST_NAMES = frozenset({"justfile", "Justfile", ".justfile"})
SHELL_INTERPRETERS = frozenset({"sh", "bash", "zsh", "ksh", "dash"})
PYTHON_INTERPRETER = re.compile(r"python(3(\.\d+)?)?")
BLANKS = " \t\f\v\r"
_SKIPPED_TOKENS = frozenset({
    tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.ENCODING,
    tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER,
})


def stack_of(path: str, text: str) -> str | None:
    pure = PurePosixPath(path)
    if pure.name in JUST_NAMES:
        return "just"
    if pure.suffix:
        return SUFFIX_STACKS.get(pure.suffix.lower())
    first = text.split("\n", 1)[0].rstrip("\r")
    words = first[2:].split() if first.startswith("#!") else []
    if not words:
        return None
    program = PurePosixPath(words[0]).name
    if program == "env":
        program = next((PurePosixPath(w).name for w in words[1:] if not w.startswith("-")), "")
    if program in SHELL_INTERPRETERS:
        return "shell"
    return "python" if PYTHON_INTERPRETER.fullmatch(program) else None


def blocks(path: str, text: str) -> tuple[Block, ...]:
    stack = stack_of(path, text)
    return () if stack is None else _blocks(stack, text)


@functools.lru_cache(maxsize=4096)
def _blocks(stack: str, text: str) -> tuple[Block, ...]:
    lines = [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]
    lexer = _LEXERS[stack]
    raws, first_code = lexer(text, lines)
    return _assemble(raws, first_code)


def _assemble(raws: list[_Raw], first_code: int | None) -> tuple[Block, ...]:
    """Merge adjacent own-line line comments and mark each block's header flag."""
    merged: list[_Raw] = []
    for raw in sorted(raws, key=lambda r: r.first):
        prev = merged[-1] if merged else None
        joins = (
            prev is not None and prev.kind == raw.kind == "line"
            and prev.own_line and raw.own_line and raw.first == prev.last + 1)
        if joins:
            merged[-1] = prev._replace(last=raw.last, texts=prev.texts + raw.texts)
        else:
            merged.append(raw)
    return tuple(
        Block(r.first, r.last, r.texts, first_code is None or r.last < first_code)
        for r in merged)


def _cut(line: str, start: int, end: int | None) -> str:
    """Slice a line by UTF-8 byte offsets, as the AST reports them."""
    try:
        return line.encode("utf-8", "surrogatepass")[start:end].decode("utf-8", "surrogatepass")
    except UnicodeError:
        return line[start:end]


def _python(text: str, lines: list[str]) -> tuple[list[_Raw], int | None]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
            tree = ast.parse(text)
    except (tokenize.TokenError, SyntaxError, ValueError, RecursionError):
        return _python_fallback(lines)
    raws, module_doc = _docstrings(tree, lines)
    first_code = None
    for token in tokens:
        row = token.start[0]
        if token.type == tokenize.COMMENT:
            if row == 1 and token.start[1] == 0 and token.string.startswith("#!"):
                continue
            own = token.line[:token.start[1]].strip() == ""
            raws.append(_Raw(row, row, (token.string.rstrip("\r"),), own, "line"))
        elif token.type in _SKIPPED_TOKENS or token.start == module_doc:
            continue
        elif first_code is None:
            first_code = row
    return raws, first_code


def _docstrings(tree: ast.AST, lines: list[str]) -> tuple[list[_Raw], tuple[int, int] | None]:
    raws = []
    module_doc = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        head = node.body[0] if node.body else None
        if not (isinstance(head, ast.Expr) and isinstance(head.value, ast.Constant)
                and isinstance(head.value.value, str)):
            continue
        if not 1 <= head.lineno <= head.end_lineno <= len(lines):
            continue
        texts = tuple(
            _cut(lines[row - 1],
                 head.col_offset if row == head.lineno else 0,
                 head.end_col_offset if row == head.end_lineno else None)
            for row in range(head.lineno, head.end_lineno + 1))
        raws.append(_Raw(head.lineno, head.end_lineno, texts, True, "block"))
        if isinstance(node, ast.Module):
            module_doc = (head.lineno, head.col_offset)
    return raws, module_doc


def _python_fallback(lines: list[str]) -> tuple[list[_Raw], int | None]:
    raws = []
    first_code = None
    for row, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if row == 1 and line.startswith("#!"):
            continue
        if stripped.startswith("#"):
            raws.append(_Raw(row, row, (stripped,), True, "line"))
        elif stripped.strip() and first_code is None:
            first_code = row
    return raws, first_code


_WORD_STOPS = " \t\n;&|()<>"


class _Shell:
    """A character scanner over normalized text; see the module docstring for the states."""

    def __init__(self, text: str):
        self.text = text
        self.n = len(text)
        self.i = 0
        self.row = 1
        self.line_start = 0
        self.has_code = False
        self.cmd_start = True
        self.first_code: int | None = None
        self.raws: list[_Raw] = []
        self.queue: list[tuple[str, bool]] = []

    def code(self) -> None:
        self.has_code = True
        if self.first_code is None:
            self.first_code = self.row

    def newline(self) -> None:
        self.row += 1
        self.line_start = self.i
        self.has_code = False
        self.cmd_start = True

    def escape(self) -> None:
        self.code()
        newline = self.text.startswith("\n", self.i + 1)
        self.i += 2
        if newline:
            self.newline()

    def scan(self) -> tuple[list[_Raw], int | None]:
        state, depth, back = "normal", 0, "normal"
        text = self.text
        while self.i < self.n:
            c = text[self.i]
            if c == "\n":
                self.i += 1
                self.newline()
                if state == "normal" and self.queue:
                    self.skip_heredocs()
            elif state == "normal":
                state, depth = self.normal(c)
                back = "normal"
            elif state == "arith":
                state, depth, back = self.arith(c, depth)
            else:
                state = self.quoted(c, state, back)
        return self.raws, self.first_code

    def normal(self, c: str) -> tuple[str, int]:
        text, i = self.text, self.i
        if c in BLANKS:
            self.i += 1
        elif c == "\\":
            self.escape()
            self.cmd_start = False
        elif c == "#" and (i == self.line_start or text[i - 1] in " \t;&|()\f\v"):
            self.comment()
        elif c in "'\"":
            return self.enter("sq" if c == "'" else "dq", 1)
        elif text.startswith("$((", i):
            return self.enter("arith", 3, 2)
        elif text.startswith("$'", i):
            return self.enter("ansi", 2)
        elif c == "(" and self.cmd_start and text.startswith("((", i):
            return self.enter("arith", 2, 2)
        elif text.startswith("<<<", i):
            self.code()
            self.i += 3
            self.cmd_start = False
        elif text.startswith("<<", i):
            self.heredoc()
        elif c in ";&|(":
            self.code()
            self.i += 1
            self.cmd_start = True
        else:
            self.code()
            self.i += 1
            self.cmd_start = False
        return "normal", 0

    def enter(self, state: str, width: int, depth: int = 0) -> tuple[str, int]:
        self.code()
        self.i += width
        self.cmd_start = False
        return state, depth

    def comment(self) -> None:
        end = self.text.find("\n", self.i)
        end = self.n if end < 0 else end
        shebang = self.row == 1 and self.i == 0 and self.text.startswith("#!")
        if not shebang:
            self.raws.append(
                _Raw(self.row, self.row, (self.text[self.i:end],), not self.has_code, "line"))
        self.i = end

    def quoted(self, c: str, state: str, back: str) -> str:
        if c not in BLANKS:
            self.code()
        if c == "\\" and state != "sq":
            self.escape()
        else:
            self.i += 1
            if c == ("\"" if state == "dq" else "'"):
                return back
        return state

    def arith(self, c: str, depth: int) -> tuple[str, int, str]:
        state, back = "arith", "arith"
        if c in "'\"":
            state = "sq" if c == "'" else "dq"
        elif c == "\\":
            self.escape()
            return state, depth, back
        elif c in "()":
            depth += 1 if c == "(" else -1
            state = "arith" if depth > 0 else "normal"
        if c not in BLANKS:
            self.code()
        self.i += 1
        return state, depth, back

    def heredoc(self) -> None:
        j = self.i + 2
        tabs = self.text.startswith("-", j)
        j += tabs
        while j < self.n and self.text[j] in " \t":
            j += 1
        word, end = self.word(j)
        self.code()
        self.cmd_start = False
        if word:
            self.queue.append((word, tabs))
            self.i = end
        else:
            self.i += 2

    def word(self, j: int) -> tuple[str, int]:
        text, out = self.text, []
        while j < self.n and text[j] not in _WORD_STOPS:
            ch = text[j]
            if ch in "'\"":
                close, newline = text.find(ch, j + 1), text.find("\n", j + 1)
                if close < 0 or 0 <= newline < close:
                    return "", j
                out.append(text[j + 1:close])
                j = close + 1
            elif ch == "\\" and j + 1 < self.n and text[j + 1] != "\n":
                out.append(text[j + 1])
                j += 2
            elif ch == "\\":
                return "", j
            else:
                out.append(ch)
                j += 1
        return "".join(out), j

    def skip_heredocs(self) -> None:
        for delimiter, tabs in self.queue:
            while self.i < self.n:
                end = self.text.find("\n", self.i)
                end = self.n if end < 0 else end
                line = self.text[self.i:end]
                self.i = min(end + 1, self.n)
                self.newline()
                if (line.lstrip("\t") if tabs else line) == delimiter:
                    break
        self.queue.clear()


def _shell(text: str, lines: list[str]) -> tuple[list[_Raw], int | None]:
    return _Shell("\n".join(lines)).scan()


_BLOCK_SCALAR = re.compile(r"(?<=[:\-?])[ \t]+[|>][1-9+\-]{0,2}$")
_INDICATOR = re.compile(r"[-?](?=[ \t])[ \t]*")


def _block_base(line: str) -> int:
    """The column a block scalar's content must be indented beyond."""
    col = len(line) - len(line.lstrip(" "))
    while match := _INDICATOR.match(line, col):
        if line[match.end():].startswith(("|", ">")):
            break
        col = match.end()
    return col


class _YamlLine:
    """One line's scan outside a block scalar: quotes carry over between lines."""

    def __init__(self, line: str, quote: str | None):
        self.line = line
        self.quote = quote
        self.has_code = False
        self.comment_at: int | None = None

    def scan(self) -> None:
        line, n, i = self.line, len(self.line), 0
        at_start, flow = self.quote is None, 0
        while i < n:
            c = line[i]
            if self.quote:
                i = self.in_quote(i)
                continue
            if c in " \t":
                i += 1
                continue
            if c == "#" and (not self.has_code or line[i - 1] in " \t"):
                self.comment_at = i
                return
            self.has_code = True
            nxt = line[i + 1] if i + 1 < n else " "
            if c in "'\"" and at_start:
                self.quote = c
                at_start = False
                i = self.in_quote(i + 1)
                continue
            if (c in "-?" and at_start and nxt in " \t") or (c == ":" and nxt in " \t"):
                at_start = True
            elif c in "[{" and at_start:
                flow += 1
            elif c == "," and flow > 0:
                at_start = True
            else:
                at_start = False
                if c in "]}" and flow > 0:
                    flow -= 1
            i += 1

    def in_quote(self, i: int) -> int:
        """Consume quoted text from `i`; return the index after the closing quote or the line end."""
        line, n, quote = self.line, len(self.line), self.quote
        while i < n:
            c = line[i]
            if c not in " \t":
                self.has_code = True
            if quote == '"' and c == "\\":
                i += 2
            elif c == quote and quote == "'" and line.startswith("''", i):
                i += 2
            elif c == quote:
                self.quote = None
                return i + 1
            else:
                i += 1
        return n


def _yaml(text: str, lines: list[str]) -> tuple[list[_Raw], int | None]:
    raws: list[_Raw] = []
    first_code = None
    quote = None
    block_base = None
    for row, line in enumerate(lines, 1):
        blank = not line.strip()
        if block_base is not None:
            if blank or len(line) - len(line.lstrip(" ")) > block_base:
                if not blank and first_code is None:
                    first_code = row
                continue
            block_base = None
        scan = _YamlLine(line, quote)
        scan.scan()
        quote = scan.quote
        if scan.has_code and first_code is None:
            first_code = row
        if scan.comment_at is not None:
            raws.append(_Raw(row, row, (line[scan.comment_at:],), not scan.has_code, "line"))
        body = line if scan.comment_at is None else line[:scan.comment_at]
        if quote is None and _BLOCK_SCALAR.search(body.rstrip()):
            block_base = _block_base(line)
    return raws, first_code


@dataclass
class _Frame:
    """One lexing context: code at the top or in a hole, or a string being read."""

    kind: str
    quote: str = ""
    multiline: bool = False
    verbatim: bool = False
    quotes: int = 0
    braces: int = 0
    close: int = 1
    depth: int = 0


_WORD = re.compile(r"[\w$]+")
_NIX_ID = re.compile(r"[A-Za-z_][\w'-]*")
_REGEX_AFTER = frozenset("(,=:[!&|?{};+-*%<>~^")
_REGEX_KEYWORDS = frozenset(
    "return typeof case do else in of new delete void throw yield await instanceof".split())


class _Scan:
    """A character scanner over normalized text; subclasses add one language's tokens."""

    def __init__(self, text: str):
        self.text = text
        self.n = len(text)
        self.i = 0
        self.row = 1
        self.has_code = False
        self.first_code: int | None = None
        self.raws: list[_Raw] = []
        self.stack = [_Frame("code")]
        self.prev = ""
        self.strings = {"str": self.plain}

    def adv(self, k: int, code: bool = True) -> None:
        for ch in self.text[self.i:self.i + k]:
            if ch == "\n":
                self.row += 1
                self.has_code = False
            elif code and ch not in BLANKS:
                self.has_code = True
                if self.first_code is None:
                    self.first_code = self.row
            self.i += 1

    def scan(self) -> tuple[list[_Raw], int | None]:
        if self.text.startswith("#!"):
            self.adv(self.line_end() - self.i, False)
        while self.i < self.n:
            frame = self.stack[-1]
            c = self.text[self.i]
            if frame.kind in ("code", "hole"):
                self.code(frame, c)
            else:
                self.strings[frame.kind](frame, c)
        return self.raws, self.first_code

    def line_end(self) -> int:
        end = self.text.find("\n", self.i)
        return self.n if end < 0 else end

    def line_comment_here(self, c: str) -> bool:
        return self.text.startswith("//", self.i)

    def code(self, frame: _Frame, c: str) -> None:
        if c in BLANKS or c == "\n":
            self.adv(1, False)
        elif self.text.startswith("/*", self.i):
            self.block_comment()
        elif self.line_comment_here(c):
            self.line_comment()
        elif c == "{":
            frame.depth += 1
            self.punct(c)
        elif c == "}":
            self.close_brace(frame, c)
        else:
            self.token(c)

    def token(self, c: str) -> None:
        self.punct(c)

    def punct(self, c: str) -> None:
        self.adv(1)
        self.prev = c

    def line_comment(self) -> None:
        end = self.line_end()
        self.raws.append(
            _Raw(self.row, self.row, (self.text[self.i:end],), not self.has_code, "line"))
        self.adv(end - self.i, False)

    def block_comment(self) -> None:
        close = self.text.find("*/", self.i + 2)
        stop = self.n if close < 0 else close + 2
        first, chunk = self.row, self.text[self.i:stop]
        self.adv(stop - self.i, False)
        self.raws.append(_Raw(first, self.row, tuple(chunk.split("\n")), False, "block"))

    def close_brace(self, frame: _Frame, c: str) -> None:
        closer = "}" * frame.close
        if frame.kind == "hole" and frame.depth == 0 and self.text.startswith(closer, self.i):
            self.adv(frame.close)
            self.stack.pop()
        else:
            frame.depth = max(0, frame.depth - 1)
            self.punct(c)

    def push(self, frame: _Frame, width: int) -> None:
        self.stack.append(frame)
        self.adv(width)
        if frame.kind == "hole":
            self.prev = "{"

    def pop(self) -> None:
        self.stack.pop()
        self.prev = "str"

    def plain(self, frame: _Frame, c: str) -> None:
        """A quoted string with backslash escapes; it ends at its quote or at the line end."""
        if c == "\\":
            self.adv(2)
        elif c == frame.quote:
            self.adv(1)
            self.pop()
        elif c == "\n" and not frame.multiline:
            self.pop()
        elif c == "$" and frame.multiline and self.text.startswith("${", self.i):
            self.push(_Frame("hole"), 2)
        else:
            self.adv(1)


class _JavaScript(_Scan):
    def __init__(self, text: str):
        super().__init__(text)
        self.strings["tpl"] = self.template

    def token(self, c: str) -> None:
        if c in "'\"":
            self.push(_Frame("str", quote=c), 1)
        elif c == "`":
            self.push(_Frame("tpl"), 1)
        elif c == "/" and self.regex_allowed():
            self.regex()
        elif match := _WORD.match(self.text, self.i):
            self.adv(match.end() - self.i)
            self.prev = match.group()
        else:
            self.punct(c)

    def regex_allowed(self) -> bool:
        if self.i > 0 and self.text[self.i - 1] == "<" and self.prev == "<":
            return False
        if self.prev == "}" and self.text.startswith("/>", self.i):
            return False
        return self.prev == "" or self.prev in _REGEX_AFTER or self.prev in _REGEX_KEYWORDS

    def regex(self) -> None:
        text, j, in_class = self.text, self.i + 1, False
        while j < self.n and text[j] != "\n":
            ch = text[j]
            if ch == "\\":
                j += 1 if text[j + 1:j + 2] == "\n" else 2
                continue
            if ch == "[":
                in_class = True
            elif ch == "]":
                in_class = False
            elif ch == "/" and not in_class:
                j += 1
                break
            j += 1
        self.adv(min(j, self.n) - self.i)
        self.prev = "str"

    def template(self, frame: _Frame, c: str) -> None:
        if c == "\\":
            self.adv(2)
        elif c == "`":
            self.adv(1)
            self.pop()
        elif c == "$" and self.text.startswith("${", self.i):
            self.push(_Frame("hole"), 2)
        else:
            self.adv(1)


class _CSharp(_Scan):
    def __init__(self, text: str):
        super().__init__(text)
        self.strings["cs"] = self.literal

    def token(self, c: str) -> None:
        if c == "'":
            self.push(_Frame("str", quote=c), 1)
        elif c in "$@\"" and self.open_literal():
            return
        else:
            self.punct(c)

    def open_literal(self) -> bool:
        text, j, dollars, verbatim = self.text, self.i, 0, False
        while j < self.n and text[j] in "$@":
            dollars += text[j] == "$"
            verbatim = verbatim or text[j] == "@"
            j += 1
        if j >= self.n or text[j] != '"':
            return False
        quotes = self.run('"', j)
        raw = quotes >= 3 and not verbatim
        frame = _Frame(
            "cs", verbatim=verbatim, quotes=quotes if raw else 0,
            braces=(dollars if raw else min(dollars, 1)))
        self.push(frame, j - self.i + (quotes if raw else 1))
        return True

    def run(self, ch: str, j: int) -> int:
        end = j
        while end < self.n and self.text[end] == ch:
            end += 1
        return end - j

    def literal(self, frame: _Frame, c: str) -> None:
        if c == "{" and frame.braces:
            self.hole(frame)
        elif frame.quotes:
            self.raw_literal(frame, c)
        elif c == '"' and frame.verbatim and self.text.startswith('""', self.i):
            self.adv(2)
        elif c == '"':
            self.adv(1)
            self.pop()
        elif c == "\\" and not frame.verbatim:
            self.adv(2)
        elif c == "\n" and not frame.verbatim:
            self.pop()
        else:
            self.adv(1)

    def raw_literal(self, frame: _Frame, c: str) -> None:
        if c != '"':
            self.adv(1)
            return
        quotes = self.run('"', self.i)
        self.adv(quotes)
        if quotes >= frame.quotes:
            self.pop()

    def hole(self, frame: _Frame) -> None:
        if frame.quotes:
            braces = self.run("{", self.i)
            if braces < frame.braces:
                self.adv(braces)
                return
            self.adv(braces - frame.braces)
        elif self.text.startswith("{{", self.i):
            self.adv(2)
            return
        self.push(_Frame("hole", close=frame.braces), frame.braces)


class _Nix(_Scan):
    def __init__(self, text: str):
        super().__init__(text)
        self.strings["ind"] = self.indented

    def line_comment_here(self, c: str) -> bool:
        return c == "#"

    def token(self, c: str) -> None:
        if c == '"':
            self.push(_Frame("str", quote=c, multiline=True), 1)
        elif self.text.startswith("''", self.i):
            self.push(_Frame("ind"), 2)
        elif match := _NIX_ID.match(self.text, self.i):
            self.adv(match.end() - self.i)
        else:
            self.punct(c)

    def indented(self, frame: _Frame, c: str) -> None:
        text, i = self.text, self.i
        if c == "'" and text.startswith("''", i):
            after = text[i + 2:i + 3]
            if after in ("'", "$"):
                self.adv(3)
            elif after == "\\":
                self.adv(4)
            else:
                self.adv(2)
                self.pop()
        elif c == "$" and text.startswith("${", i):
            self.push(_Frame("hole"), 2)
        else:
            self.adv(1)


def _javascript(text: str, lines: list[str]) -> tuple[list[_Raw], int | None]:
    return _JavaScript("\n".join(lines)).scan()


def _csharp(text: str, lines: list[str]) -> tuple[list[_Raw], int | None]:
    return _CSharp("\n".join(lines)).scan()


def _nix(text: str, lines: list[str]) -> tuple[list[_Raw], int | None]:
    return _Nix("\n".join(lines)).scan()


_LEXERS = {
    "python": _python, "shell": _shell, "just": _shell, "yaml": _yaml,
    "javascript": _javascript, "csharp": _csharp, "nix": _nix,
}
