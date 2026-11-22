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
"""

import ast
import functools
import io
import re
import tokenize
import warnings
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


STACKS: tuple[str, ...] = ("python", "shell", "yaml", "just")

SUFFIX_STACKS = {
    ".py": "python", ".pyi": "python",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".ksh": "shell",
    ".yaml": "yaml", ".yml": "yaml",
    ".just": "just",
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
        elif c == "<" and text.startswith("<<", i) and not text.startswith("<<<", i):
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


_LEXERS = {"python": _python, "shell": _shell, "just": _shell, "yaml": _yaml}
