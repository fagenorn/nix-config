"""Finding and rewriting `workflow-state progress` calls in a shell command (issue 424).

The lexer reads the subset of bash the rewrite needs: single and double quotes,
backslash escapes and line continuations, comments, the control and redirection
operators, and the IO-number rule (`2>&1`, `5>out`; only a `<`/`>`-led operator
takes one, so the `5` of `5&>out` stays a word, as in bash). It does not expand
anything. A heredoc, an unterminated quote, a trailing backslash, or a
double-quoted interior holding an unescaped `$(` or backtick (a substitution
the subset does not model, so a progress call inside it would go unseen) is
outside the subset, so the lexer returns `None` and the caller leaves the
command alone.

A rewrite deletes every spelling of `--context-tokens` from each progress
invocation (the full option, an unambiguous argparse abbreviation down to
`--context-t`, with `=` or with a separate value) and inserts one measured
`--context-tokens <n>`. It splices the original text, so every other byte
survives, and it is emitted only when `proved`: the rewritten command must lex
to exactly the original words minus the removed ones plus the inserted ones.
An invocation whose simple command ends at an opening `(` or backtick (as in
`--repo-root $(pwd)`) continues past a substitution the subset cannot see, and a
bare spelling followed by redirections and then a value-shaped word takes that
word as its value; both make the rewrite unprovable, so the command is left alone.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import NamedTuple

OPERATORS = ("&>>", "<<<", "<<-", "&&", "||", "|&", ";;", "&>", ">>", ">&", "<&", "<>",
             ">|", "<<", ";", "&", "|", "(", ")", "<", ">", "`")
HEREDOC_OPERATORS = ("<<", "<<-")
SEPARATORS = frozenset({"\n", ";", "&", "&&", "|", "||", "|&", ";;", "(", ")", "`"})
OPTION = "--context-tokens"
MINIMUM_SPELLING = "--context-t"
OPERATOR_START = ";&|()<>`"
OPENERS = ("(", "`")
BLANKS = " \t"
DOUBLE_QUOTE_ESCAPES = "$`\"\\"


class Token(NamedTuple):
    """`kind` is `"word"` or `"op"`; `start`/`end` index the command, `end` exclusive."""

    kind: str
    value: str
    start: int
    end: int


class Rewrite(NamedTuple):
    command: str
    proved: bool


def _operator_at(command: str, index: int) -> str:
    for operator in OPERATORS:
        if command.startswith(operator, index):
            return operator
    raise ValueError(f"no operator at {index}")  # every OPERATOR_START character leads one


class _Lexer:
    def __init__(self, command: str) -> None:
        self.command = command
        self.tokens: list[Token] = []
        self.chars: list[str] = []
        self.start: int | None = None  # where the word in progress began
        self.plain = True  # the word in progress has no quote or escape

    def begin(self, index: int) -> None:
        if self.start is None:
            self.start = index

    def append(self, text: str, index: int, *, quoted: bool = False) -> None:
        self.begin(index)
        self.chars.append(text)
        if quoted:
            self.plain = False

    def end_word(self, end: int) -> None:
        if self.start is not None:
            self.tokens.append(Token("word", "".join(self.chars), self.start, end))
        self.discard_word()

    def discard_word(self) -> None:
        self.chars, self.start, self.plain = [], None, True

    def lex(self) -> list[Token] | None:
        command, index = self.command, 0
        while index < len(command):
            char = command[index]
            if char in BLANKS:
                self.end_word(index)
                index += 1
            elif char == "\n":
                self.end_word(index)
                self.tokens.append(Token("op", "\n", index, index + 1))
                index += 1
            elif char == "#" and self.start is None:
                index = command.find("\n", index)
                if index < 0:
                    index = len(command)
            elif char in OPERATOR_START:
                index = self.operator(index)
                if index < 0:
                    return None
            elif char == "'":
                close = command.find("'", index + 1)
                if close < 0:
                    return None
                self.append(command[index + 1:close], index, quoted=True)
                index = close + 1
            elif char == '"':
                index = self.double_quoted(index)
                if index < 0:
                    return None
            elif char == "\\":
                if index + 1 >= len(command):
                    return None
                if command[index + 1] != "\n":
                    self.append(command[index + 1], index, quoted=True)
                index += 2
            else:
                self.append(char, index)
                index += 1
        self.end_word(len(command))
        return self.tokens

    def double_quoted(self, index: int) -> int:
        """Append the interior of the `"…"` opening at `index`; the next index, or -1.

        -1 also refuses an unescaped `$(` or backtick: the subset does not lex the
        substitution, and treating it as literal text would hide a progress call in it.
        """
        command = self.command
        self.begin(index)
        self.plain = False
        cursor = index + 1
        while cursor < len(command):
            char = command[cursor]
            if char == '"':
                return cursor + 1
            if char == "\\":
                if cursor + 1 >= len(command):
                    return -1
                following = command[cursor + 1]
                if following in DOUBLE_QUOTE_ESCAPES:
                    self.chars.append(following)
                elif following != "\n":
                    self.chars.append(char + following)
                cursor += 2
            elif char == "`" or command.startswith("$(", cursor):
                return -1
            else:
                self.chars.append(char)
                cursor += 1
        return -1

    def operator(self, index: int) -> int:
        """Emit the operator at `index`; the next index, or -1 for a heredoc."""
        operator = _operator_at(self.command, index)
        if operator in HEREDOC_OPERATORS:
            return -1
        word = "".join(self.chars)
        if (operator[0] in "<>" and self.start is not None and self.plain
                and word.isascii() and word.isdigit()):
            start = self.start
            operator = word + operator
            self.discard_word()
        else:
            start = index
            self.end_word(index)
        self.tokens.append(Token("op", operator, start, start + len(operator)))
        return start + len(operator)


def lex(command: str) -> list[Token] | None:
    """The words and operators of `command`, or `None` outside the supported subset.

    Outside the subset are a heredoc, an unterminated quote, a trailing backslash
    and a double-quoted interior with an unescaped `$(` or backtick.
    """
    return _Lexer(command).lex()


def simple_command_end(tokens: Sequence[Token], index: int) -> int:
    """The index of the first separator operator after `index`, else `len(tokens)`."""
    for position in range(index + 1, len(tokens)):
        if tokens[position].kind == "op" and tokens[position].value in SEPARATORS:
            return position
    return len(tokens)


def progress_starts(tokens: Sequence[Token]) -> list[int]:
    """Each index where a `workflow-state` word is followed by the word `progress`."""
    return [index for index in range(len(tokens) - 1)
            if tokens[index].kind == "word"
            and tokens[index].value.rsplit("/", 1)[-1] == "workflow-state"
            and tokens[index + 1].kind == "word" and tokens[index + 1].value == "progress"]


class Invocation(NamedTuple):
    """One `workflow-state` or `sdd-gate` command of a call (issue 432).

    `helper` is the last path component of the command word and `absolute` whether
    that word contains `/`. `subcommand` is the next word unless it starts with `-`.
    `options` maps every later `--` word of the simple command to its value: the text
    after `=`, else the following word unless that starts with `-`, else `None`.
    """

    helper: str
    subcommand: str | None
    options: dict[str, str | None]
    absolute: bool


def _option_value(word: str, following: Token | None) -> tuple[str, str | None]:
    name, equals, value = word.partition("=")
    if equals:
        return name, value
    if following is not None and following.kind == "word" and not following.value.startswith("-"):
        return name, following.value
    return name, None


def invocations(tokens: Sequence[Token]) -> list[Invocation]:
    """Each `workflow-state` or `sdd-gate` command word of `tokens` with its words."""
    found = []
    for index, token in enumerate(tokens):
        helper = token.value.rsplit("/", 1)[-1]
        if token.kind != "word" or helper not in ("workflow-state", "sdd-gate"):
            continue
        words = [(position, tokens[position]) for position in
                 range(index + 1, simple_command_end(tokens, index)) if tokens[position].kind == "word"]
        subcommand = None
        if words and words[0][0] == index + 1 and not words[0][1].value.startswith("-"):
            subcommand = words[0][1].value
        options = {}
        for position, word in words:
            if word.value.startswith("--"):
                following = tokens[position + 1] if position + 1 < len(tokens) else None
                name, value = _option_value(word.value, following)
                options[name] = value
        found.append(Invocation(helper, subcommand, options, "/" in token.value))
    return found


def registers_owner(tokens: Sequence[Token]) -> bool:
    """Whether a call makes its agent an owner of a phase gate.

    A `workflow-state progress` or `mark-progress`, or an `sdd-gate`, with an
    `--action-id` after it in the same simple command.
    """
    return any(item.options.get("--action-id") is not None for item in invocations(tokens)
               if item.helper == "sdd-gate"
               or (item.helper == "workflow-state" and item.subcommand in ("progress", "mark-progress")))


def _is_spelling(value: str) -> bool:
    name = value.partition("=")[0]
    return name.startswith(MINIMUM_SPELLING) and OPTION.startswith(name)


def _is_redirection(token: Token) -> bool:
    return token.kind == "op" and token.value not in SEPARATORS


def _ends_at_opener(tokens: Sequence[Token], start: int, end: int) -> bool:
    """Whether the simple command of the invocation at `start` ends at an opening operator.

    `(` always opens. A backtick closes when an odd number of backticks precede
    `start` (the invocation sits inside a backtick substitution) and opens otherwise.
    """
    if end >= len(tokens) or tokens[end].value not in OPENERS:
        return False
    if tokens[end].value == "(":
        return True
    preceding = sum(1 for token in tokens[:start] if token.kind == "op" and token.value == "`")
    return preceding % 2 == 0


def _value_after_redirection(tokens: Sequence[Token], index: int, end: int) -> bool:
    """Whether redirections start at `index` and a value-shaped word follows them before `end`.

    Bash takes `--context-tokens >/dev/null 5` as the option with the value `5`,
    which a removal of the bare spelling alone would strand as a positional word.
    """
    if index >= end or not _is_redirection(tokens[index]):
        return False
    while index < end and _is_redirection(tokens[index]):
        index += 2
    return (index < end and tokens[index].kind == "word"
            and not tokens[index].value.startswith("-"))


def _glued_to_operator(tokens: Sequence[Token], index: int) -> bool:
    """Whether deleting word `index` would fuse its text with a following opener or redirection.

    `$(…)` lexes as the word `$` then `(`; deleting the `$` would turn a command
    substitution into a subshell, deleting `--context-tokens=` before a backtick
    would leave the substitution standing alone as a new word, and `x<(…)` is a
    process substitution. A word glued to a closing or separating operator
    (`5;`, `5)`) loses nothing.
    """
    if index + 1 >= len(tokens):
        return False
    following = tokens[index + 1]
    return (following.kind == "op" and following.start == tokens[index].end
            and (following.value in OPENERS or _is_redirection(following)))


def _removals(tokens: Sequence[Token], start: int) -> tuple[set[int], bool]:
    """The word indices of one invocation's `--context-tokens` spellings, and whether provable."""
    end = simple_command_end(tokens, start + 1)
    removed: set[int] = set()
    if _ends_at_opener(tokens, start, end):
        return removed, False
    index = start + 2
    while index < end:
        token = tokens[index]
        if _is_redirection(token):
            index += 2
        elif token.kind == "word" and token.value == "--":
            break
        elif token.kind == "word" and _is_spelling(token.value):
            removed.add(index)
            if "=" not in token.value:
                following = tokens[index + 1] if index + 1 < len(tokens) else None
                if following is not None and following.kind == "op" and following.value in OPENERS:
                    return removed, False
                if _value_after_redirection(tokens, index + 1, end):
                    return removed, False
                if (index + 1 < end and following is not None and following.kind == "word"
                        and not following.value.startswith("-")):
                    removed.add(index + 1)
                    index += 1
            index += 1
        else:
            index += 1
    unprovable = any(_glued_to_operator(tokens, word) for word in removed)
    return removed, not unprovable


def _splice(command: str, deletions: list[tuple[int, int]], insertions: dict[int, str]) -> str:
    events = sorted([(start, 1, end) for start, end in deletions]
                    + [(at, 0, text) for at, text in insertions.items()])
    pieces, cursor = [], 0
    for at, kind, payload in events:
        pieces.append(command[cursor:at])
        if kind == 0:
            pieces.append(payload)
            cursor = at
        else:
            cursor = max(cursor, payload)
    pieces.append(command[cursor:])
    return "".join(pieces)


def _insertion(command: str, offset: int, measured: int) -> str:
    text = f" {OPTION} {measured}"
    if offset < len(command) and command[offset] not in " \t\n":
        text += " "
    return text


def rewrite_progress(command: str, tokens: Sequence[Token], measured: int | None) -> Rewrite:
    """`command` with each progress invocation carrying `measured` (or no) `--context-tokens`."""
    removed: set[int] = set()
    insertions: dict[int, str] = {}
    inserted_after: set[int] = set()
    for start in progress_starts(tokens):
        invocation, provable = _removals(tokens, start)
        if not provable:
            return Rewrite(command, False)
        removed |= invocation
        if measured is not None:
            offset = tokens[start + 1].end
            insertions[offset] = _insertion(command, offset, measured)
            inserted_after.add(start + 1)
    deletions = [(tokens[word - 1].end, tokens[word].end) for word in sorted(removed)]
    result = _splice(command, deletions, insertions)
    expected: list[tuple[str, str]] = []
    for position, token in enumerate(tokens):
        if position not in removed:
            expected.append((token.kind, token.value))
        if position in inserted_after:
            expected += [("word", OPTION), ("word", str(measured))]
    return Rewrite(result, proved(result, expected))


def proved(rewritten: str, expected: Sequence[tuple[str, str]]) -> bool:
    """Whether `rewritten` lexes to exactly the `(kind, value)` pairs in `expected`."""
    tokens = lex(rewritten)
    return tokens is not None and [(token.kind, token.value) for token in tokens] == list(expected)


def mentions_progress(command: str) -> bool:
    return re.search(r"workflow-state\s+progress(?![\w-])", command) is not None
