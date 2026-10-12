"""Path references in tracked tooling files, found and edited (#350).

This module provides what a relocation needs to find a repository path written
in a tracked, non-Markdown text file that would be left pointing at a path
that moved: the token grammar (`tokens`, `split_token`, `split_pattern`,
`split_variable`, `split_climb`), the successors of a referenced path and the
carried form of a successor (`successors`, `carried_form`, `pattern_form`,
`variable_form`, `climb_form`), the occurrences, each with its shape, the
answers it offers, the path its edit lands at and, for a file the plan moves,
the policy that can answer it (`Occurrence`, `plan_references`),
the class of a file name and the answer recommended for it (`file_class`,
`recommended_answer`), the answer that decides an occurrence
(`effective_answer`), the reports of the occurrences and of the policies
(`summary`, `policy_summary`) and the edits the answers make (`rewritten`), and
the reader that feeds the core a tree's text through git (`derive_references`,
over `adopt_inspection.tree_records` and `blob_at`).

A file the plan moves is read at its base path and edited at its destination:
an occurrence's `path` and `subject` are the base path, its `target` is where
the plan leaves the file. An answer is the occurrence's own, or else the one
given to its policy, `<tree>:<class>`, the moved tree and the class of the
file name; `effective_answer` is the one place that precedence is decided.
A path the moves would leave more than one file at is `contested`, and no edit
is made at it: `rewritten` returns no file for such a path.

A token is read as a plain path first (`split_token`). Only when that reading
names no moved path is it read a second time as a regular-expression spelling
(`split_pattern`, for a token that starts with `^` or holds `\\.`), and the
forms offered for it keep its anchor, escape and tail (`pattern_form`). In a
file of a shell class (`SHELL_CLASSES`, decided by the base path), a token
neither reading makes an occurrence is read a third time as a `$name/` or
`${name}/` prefix and a path (`split_variable`); the occurrence it makes offers
`rewrite` and `retain` only, keeps the variable and the tail in the form it
rewrites to (`variable_form`), and belongs to the `<tree>:<class>/variable`
policy, never to the `<tree>:<class>` one.

A file the plan moves and that is in the depth read set (`depth_texts`) is read
a fourth time, for the `../` climbs that leave its moved tree (`split_climb`).
A climb is an occurrence when it ends at a proper ancestor of the tree's root,
or above the repository root, the same climb from the destination ends
elsewhere, and its target text is not inside the tree, which moves with the
file. It belongs to the `<tree>:<class>/depth` policy, never to the
`<tree>:<class>` one. It offers `rewrite` (the climb shifted by the depth
delta, `climb_form`) and `retain` when it ends above the repository root or at
an ancestor of the destination's directory, its target is no moved path and the
shifted climb is valid, and `retain` alone otherwise.

In a file whose base path has class `.py`, the depth reading also takes the
parent-count chains of `python_climbs`, as climbs with no target text. An
anchor is `Path(__file__)` or `pathlib.Path(__file__)` not preceded by an
identifier character or `.`, with at most one `.resolve()` or `.absolute()`;
or a name bound at column 0 by `NAME = <that>` or `NAME = <that>.parent`
(with an optional `: Path` annotation, a trailing comment and a CRLF line
end) and bound nowhere else in the file, at any indentation, by assignment,
`for`, `as`, `del`, `global`, `nonlocal` or a keyword argument; a use of the
name is the name preceded by neither an identifier character nor `.` and not
followed by one. A chain is zero or more `.parent` then at most one
`.parents[N]` with `N` a decimal literal, at least one of them, with no
whitespace; it climbs the offset (-1 from the file itself, 0 from its
directory) plus one per `.parent` plus `N + 1` levels. It is an
occurrence under the rules of a text climb; its rewrite is the chain with `N`
(or the number of `.parent`s, which stays at least one) moved by the depth
delta (`shift_chain`). Not read: `os.path` calls, `Path.cwd()`, a name chained
from another name, a binding inside a function or class, a name bound more
than once, a chain continued by `.parent` after its end, a chain with
whitespace or a non-literal index, and a chain overlapping a text climb or an
occurrence another reading made in the file.

It is imported and never run. It reads blobs only through git, never the
working tree, writes nothing, and imports `adopt_inspection` and `adopt_links`
only. Standard library only; no per-language parser is used.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable, Iterable, Mapping

from agent_tools.adopt_inspection import (
    blob_at, is_secret_path, refuse, run_git, split_nul, tree_records)
from agent_tools.adopt_links import (
    REGULAR_MODES, Tree, directory_successor, is_markdown_path)

ANSWERS = ("extend", "rewrite", "retain")
POLICY_ANSWERS = ("rewrite", "retain")
REWRITE_CLASSES = (".py", ".sh", ".bash", ".zsh", ".nix", ".yaml", ".yml",
                   ".toml", ".js", ".mjs", ".cjs", ".ts")
SHELL_CLASSES = (".sh", ".bash", ".zsh")
RETAIN_CLASSES = (".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".txt",
                  ".log")
TOKEN_DELIMITERS = "\"'`,;:=()<>|&#!"
GLOB_CHARACTERS = "*?[{"
PATTERN_ESCAPES = ("\\\\.", "\\.")
CARRIED_TAILS = ("", "/", "/**")
# The paths whose files are records of what was, never read for references.
RECORD_HOMES = (".agents/artifacts/", ".agents/knowledge/archive/")

_QUOTES = "\"'"
_VARIABLE_PREFIX = re.compile(
    r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})/")
_PATTERN_SAFE = re.compile(r"[A-Za-z0-9_./-]+")
_OPENING_BEFORE = "[{,"
_CLOSING_REST = ",])}"
_NOT_A_CALL_BEFORE = "_)]"
_FILE_ANCHOR = (r"(?:pathlib\.)?Path\(__file__\)"
                r"(?:\.resolve\(\)|\.absolute\(\))?")
_DIRECT_ANCHOR = re.compile(r"(?<![\w.])" + _FILE_ANCHOR)
_CHAIN = re.compile(r"((?:\.parent(?!\w))*)(?:\.parents\[(\d+)\])?")
# `\r?` keeps the binding of a CRLF file, whose `\r` the decode leaves.
_BINDING = re.compile(
    r"^([A-Za-z_]\w*)[ \t]*(?::[ \t]*(?:pathlib\.)?Path[ \t]*)?=[ \t]*"
    + _FILE_ANCHOR + r"(\.parent)?[ \t]*(?:#[^\r\n]*)?\r?$", re.MULTILINE)


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    line: int
    column: int
    text: str


def tokens(text: str) -> list[Token]:
    """Every maximal run of non-space, non-delimiter characters, in order.

    `start` and `end` are character offsets into `text`; `line` and `column`
    are 1-based, a line ending at `\\n` only and the column counted in
    characters from the line's start.
    """
    found: list[Token] = []
    line, line_start, start = 1, 0, None
    for index, char in enumerate(text + "\n"):
        inside = not char.isspace() and char not in TOKEN_DELIMITERS
        if inside and start is None:
            start = index
        elif not inside and start is not None:
            found.append(Token(start, index, line, start - line_start + 1,
                               text[start:index]))
            start = None
        if char == "\n":
            line += 1
            line_start = index + 1
    return found


def split_token(token: str) -> tuple[str, str, str]:
    """`(prefix, path, tail)` of a token; their concatenation is the token.

    The path is the longest leading run of `/`-separated segments that are
    non-empty and hold no glob character.
    """
    prefix = "./" if token.startswith("./") else \
        "/" if token.startswith("/") else ""
    rest = token[len(prefix):]
    count = 0
    for segment in rest.split("/"):
        if not segment or any(c in GLOB_CHARACTERS for c in segment):
            break
        count += 1
    path = "/".join(rest.split("/")[:count])
    return prefix, path, rest[len(path):]


def split_pattern(token: str) -> tuple[str, str, str, str, str] | None:
    """`(anchor, escape, prefix, path, tail)` of a pattern spelling, or None.

    A pattern spelling starts with `^` or holds an escaped dot (`\\.`, or
    `\\\\.` as a TOML or JSON string spells it); one escape is chosen for the
    whole token. The path is the longest leading run of `/`-separated segments
    that decode, by replacing the escape with `.`, to a non-empty segment
    holding no glob character and no backslash; `anchor + prefix + <the raw
    text the path was decoded from> + tail` is the token.
    """
    escape = next((e for e in PATTERN_ESCAPES if e in token), "")
    if not token.startswith("^") and not escape:
        return None
    anchor = "^" if token.startswith("^") else ""
    rest = token[len(anchor):]
    prefix = "/" if rest.startswith("/") else ""
    rest = rest[len(prefix):]
    raw = rest.split("/")
    decoded = [segment.replace(escape, ".") if escape else segment
               for segment in raw]
    count = 0
    for segment in decoded:
        if (not segment or "\\" in segment
                or any(c in GLOB_CHARACTERS for c in segment)):
            break
        count += 1
    return (anchor, escape, prefix, "/".join(decoded[:count]),
            rest[len("/".join(raw[:count])):])


def split_variable(token: str) -> tuple[str, str, str] | None:
    """`(variable, path, tail)` of a `$name/` or `${name}/` token, or None.

    `variable` is the prefix with its `/`, and `variable + path + tail` is the
    token. The path is the longest run of `/`-separated segments after it that
    are non-empty and hold neither a glob character nor a `$`.
    """
    match = _VARIABLE_PREFIX.match(token)
    if match is None:
        return None
    variable, rest = match.group(), token[match.end():]
    count = 0
    for segment in rest.split("/"):
        if (not segment or "$" in segment
                or any(c in GLOB_CHARACTERS for c in segment)):
            break
        count += 1
    path = "/".join(rest.split("/")[:count])
    return variable, path, rest[len(path):]


def split_climb(token: str) -> tuple[str, int, str] | None:
    """`(prefix, height, rest)` of a `../` climb token, or None.

    `prefix` is `./` or empty, `height` the number of leading `..` segments
    (at least one) and `rest` the text after the last of them, empty or
    starting with `/`, so that `prefix + "/".join([".."] * height) + rest` is
    the token. A token with no `/`, or whose rest holds a `..` segment, is no
    climb.
    """
    if "/" not in token:
        return None
    prefix = "./" if token.startswith("./") else ""
    segments = token[len(prefix):].split("/")
    height = 0
    while height < len(segments) and segments[height] == "..":
        height += 1
    if height == 0 or ".." in segments[height:]:
        return None
    rest = "/" + "/".join(segments[height:]) if height < len(segments) else ""
    return prefix, height, rest


def climb_form(prefix: str, height: int, rest: str) -> str | None:
    """The climb of `height` levels that keeps `prefix` and `rest`, or None
    when `height` is below one."""
    if height < 1:
        return None
    return prefix + "/".join([".."] * height) + rest


# --------------------------------------------------------------------------
# Successors and carried forms
# --------------------------------------------------------------------------


def _moved_directory(directory: str, base: Tree, after: Tree,
                     moved: dict[str, str]) -> str | None:
    """The one place a directory that left the tree went, when there is one."""
    if directory in after.directories:
        return None
    return directory_successor(directory, base, after, moved)


def _visit(directory: str, base: Tree, after: Tree, moved: dict[str, str],
           found: set[tuple[str, bool]]) -> None:
    for child in base.paths:
        if child.rpartition("/")[0] == directory and child in moved:
            found.add((moved[child], False))
    for child in base.directories:
        if child.rpartition("/")[0] != directory:
            continue
        successor = _moved_directory(child, base, after, moved)
        if successor is not None:
            found.add((successor, True))
        else:
            _visit(child, base, after, moved, found)


def successors(path: str, base: Tree, after: Tree, moved: dict[str, str]
               ) -> tuple[bool, list[tuple[str, bool]]]:
    """`(single, [(successor, is_directory), ...])` for a referenced path."""
    if path in base.paths:
        return True, [(moved[path], False)]
    successor = _moved_directory(path, base, after, moved)
    if successor is not None:
        return True, [(successor, True)]
    found: set[tuple[str, bool]] = set()
    _visit(path, base, after, moved, found)
    return False, sorted(found)


def carried_form(prefix: str, successor: str, is_directory: bool, tail: str,
                 single: bool) -> str | None:
    """The token that keeps `prefix`, `tail` and shape on `successor`."""
    if single:
        form = prefix + successor + tail
    elif tail in CARRIED_TAILS:
        form = prefix + successor + (tail if is_directory else "")
    else:
        return None
    if not _is_one_token(form):
        return None
    return form if split_token(form)[1] == successor else None


def pattern_form(anchor: str, escape: str, prefix: str, successor: str,
                 is_directory: bool, tail: str, single: bool) -> str | None:
    """The pattern spelling that keeps anchor, escape and tail on `successor`.

    None when `successor` holds a character a pattern would need to escape
    beyond the dot, when `tail` is not carried, and when the spelling would not
    be read back by `split_pattern` as `successor`.
    """
    if not _PATTERN_SAFE.fullmatch(successor):
        return None
    if single:
        carried = tail
    elif tail in CARRIED_TAILS:
        carried = tail if is_directory else ""
    else:
        return None
    form = anchor + prefix + (successor.replace(".", escape) if escape
                              else successor) + carried
    if not _is_one_token(form):
        return None
    read = split_pattern(form)
    return form if read is not None and read[3] == successor else None


def variable_form(variable: str, successor: str, is_directory: bool,
                  tail: str, single: bool) -> str | None:
    """The `variable`-joined token that keeps `tail` and shape on `successor`.

    None when `tail` is not carried and when the spelling would not be read
    back by `split_variable` as `successor`.
    """
    if single:
        carried = tail
    elif tail in CARRIED_TAILS:
        carried = tail if is_directory else ""
    else:
        return None
    form = variable + successor + carried
    if not _is_one_token(form):
        return None
    read = split_variable(form)
    return form if read is not None and read[1] == successor else None


def _is_one_token(form: str) -> bool:
    whole = tokens(form)
    return len(whole) == 1 and (whole[0].start, whole[0].end) == (0, len(form))


# --------------------------------------------------------------------------
# Classes and recommendations
# --------------------------------------------------------------------------


def file_class(path: str) -> str:
    """The lower-cased extension of a file name with its dot, or `-`.

    A name with no dot, a leading dot only (`.envrc`) or a trailing dot
    (`notes.`) has no class.
    """
    name = path.rpartition("/")[2]
    stem, dot, extension = name.rpartition(".")
    return "." + extension.lower() if dot and stem and extension else "-"


def recommended_answer(file_class: str) -> str | None:
    """The policy answer printed for a class, or None when none is given."""
    if file_class in REWRITE_CLASSES:
        return "rewrite"
    if file_class in RETAIN_CLASSES:
        return "retain"
    return None


# --------------------------------------------------------------------------
# Occurrences and shapes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Occurrence:
    path: str
    line: int
    column: int
    start: int
    end: int
    literal: str
    answers: tuple[str, ...]
    additions: tuple[str, ...]
    replacement: str | None
    shape: str | None
    target: str
    tree: str | None
    variable: bool = False
    depth: bool = False

    @property
    def subject(self) -> str:
        return f"{self.path}:{self.line}:{self.column}"

    @property
    def occurrence_class(self) -> str:
        """The file's class, `<file class>/depth` for a climb or
        `<file class>/variable` for a variable-joined occurrence; a file class
        never holds `/`, so no suffix collides with a class."""
        klass = file_class(self.path)
        if self.depth:
            return klass + "/depth"
        return klass + "/variable" if self.variable else klass

    @property
    def policy(self) -> str | None:
        """`<tree>:<occurrence class>` for a file the plan moves, else None."""
        if self.tree is None:
            return None
        return f"{self.tree}:{self.occurrence_class}"


@dataclass(frozen=True)
class References:
    """The texts that hold an occurrence by base path, the occurrences, and
    the paths the moves would leave more than one file at (`contested`)."""
    texts: dict[str, str]
    occurrences: tuple[Occurrence, ...]
    contested: frozenset[str] = frozenset()


def _line_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    return line_start, len(text) if line_end < 0 else line_end


def _is_quoted(text: str, token: Token) -> bool:
    return (token.start > 0 and token.end < len(text)
            and text[token.start - 1] == text[token.end]
            and text[token.end] in _QUOTES)


def _shape(text: str, token: Token) -> str | None:
    line_start, line_end = _line_bounds(text, token.start, token.end)
    line = text[line_start:line_end]
    if _is_quoted(text, token):
        before = line[:token.start - 1 - line_start].rstrip()
        rest = line[token.end + 1 - line_start:].lstrip()
        opens = (not before or before[-1] in _OPENING_BEFORE
                 or (before[-1] == "(" and not _follows_a_name(before[:-1])))
        if opens and (not rest or rest[0] in _CLOSING_REST):
            return "quoted"
    whole = re.compile(r"[ \t]*(?:- )?([\"']?)" + re.escape(token.text)
                       + r"\1\s*")
    return "line" if whole.fullmatch(line) else None


def _follows_a_name(before: str) -> bool:
    """Whether a `(` after `before` opens a call rather than a group."""
    return bool(before) and (before[-1].isalnum()
                             or before[-1] in _NOT_A_CALL_BEFORE)


def _names_moved(target: str, base: Tree, sources: tuple[str, ...]) -> bool:
    return bool(target) and (target in base.paths
                             or target in base.directories) and any(
        s == target or s.startswith(target + "/") for s in sources)


def _reading(token: str, base: Tree, sources: tuple[str, ...], shell: bool
             ) -> tuple[str, Callable[[str, bool, bool], str | None],
                        bool] | None:
    """`(path, form, variable)` of the first reading of `token` that names a
    moved path.

    `form(successor, is_directory, single)` is the spelling of a successor that
    keeps the token's shape. The plain reading decides alone whenever it names
    a moved path; the pattern reading is consulted only when it does not, and
    the variable reading, for a `shell` file only, when neither does (`variable`
    is true for it alone).
    """
    prefix, target, tail = split_token(token)
    if _names_moved(target, base, sources):
        def plain(successor: str, is_directory: bool, single: bool
                  ) -> str | None:
            return carried_form(prefix, successor, is_directory, tail, single)
        return target, plain, False
    pattern = split_pattern(token)
    if pattern is not None and _names_moved(pattern[3], base, sources):
        anchor, escape, pattern_prefix, pattern_target, pattern_tail = pattern

        def spelled(successor: str, is_directory: bool, single: bool
                    ) -> str | None:
            return pattern_form(anchor, escape, pattern_prefix, successor,
                                is_directory, pattern_tail, single)
        return pattern_target, spelled, False
    joined = split_variable(token) if shell else None
    if joined is None or not _names_moved(joined[1], base, sources):
        return None
    variable, joined_target, joined_tail = joined

    def carried(successor: str, is_directory: bool, single: bool
                ) -> str | None:
        return variable_form(variable, successor, is_directory, joined_tail,
                             single)
    return joined_target, carried, True


def _occurrence(path: str, text: str, token: Token, base: Tree, after: Tree,
                moved: dict[str, str], sources: tuple[str, ...], target: str,
                tree: str | None, shell: bool) -> Occurrence | None:
    if "/" not in token.text and not _is_quoted(text, token):
        return None
    reading = _reading(token.text, base, sources, shell)
    if reading is None:
        return None
    referenced, form, variable = reading
    single, found = successors(referenced, base, after, moved)
    forms = [form(successor, is_directory, single)
             for successor, is_directory in found]
    shape = _shape(text, token)
    answers = []
    additions: tuple[str, ...] = ()
    replacement = None
    if not variable and shape is not None and forms and None not in forms:
        answers.append("extend")
        additions = tuple(forms)
    if single and forms and forms[0] is not None:
        answers.append("rewrite")
        replacement = forms[0]
    answers.append("retain")
    return Occurrence(path, token.line, token.column, token.start, token.end,
                      token.text, tuple(answers), additions, replacement,
                      shape, target, tree, variable)


# --------------------------------------------------------------------------
# Depth
# --------------------------------------------------------------------------


def _depth_of(directory: str) -> int:
    return len(directory.split("/")) if directory else 0


def _landing(directory: str, height: int) -> tuple[str, int]:
    """`(place, above)` of a climb of `height` levels from `directory`.

    `place` is the directory reached and `above` how many levels the climb
    goes past the repository root, which it then lands on.
    """
    depth = _depth_of(directory)
    if height <= depth:
        return "/".join(directory.split("/")[:depth - height]), 0
    return "", height - depth


def _is_ancestor(ancestor: str, path: str) -> bool:
    """Whether `ancestor` is `path` or a directory above it; the root is `""`."""
    return not ancestor or path == ancestor or path.startswith(ancestor + "/")


def _position(text: str, start: int) -> tuple[int, int]:
    """The 1-based `(line, column)` of the offset `start`, counted as `tokens`
    counts them."""
    line_start = text.rfind("\n", 0, start) + 1
    return text.count("\n", 0, start) + 1, start - line_start + 1


def _chain_at(text: str, at: int) -> tuple[int, int, int | None] | None:
    """`(end, parents, index)` of the `.parent` / `.parents[N]` chain that
    starts at `at`, or None when there is none or `.parent` continues it."""
    match = _CHAIN.match(text, at)
    end = match.end()
    if end == at or text.startswith(".parent", end):
        return None
    index = match.group(2)
    return end, len(match.group(1)) // len(".parent"), (
        None if index is None else int(index))


def _rebinds(name: str, text: str) -> int:
    """How many times `name` is bound in `text`, at any indentation: by plain,
    annotated, augmented or `:=` assignment, a keyword argument, or `for`,
    `as`, `del`, `global` or `nonlocal`."""
    escaped = re.escape(name)
    assigned = re.findall(
        r"(?<![\w.])" + escaped + r"[ \t]*(?:(?::[^=\n]*)?=(?!=)"
        r"|(?:[-+*/%@&|^:]|//|\*\*|>>|<<)=)", text)
    named = re.findall(
        r"(?<![\w.])(?:for|as|del|global|nonlocal)[ \t]+" + escaped
        + r"(?!\w)", text)
    return len(assigned) + len(named)


def python_climbs(text: str) -> list[tuple[int, int, int]]:
    """`(start, end, height)` of every chain in `text` anchored at the file's
    own location, sorted by `start`; `text[start:end]` is the chain after its
    anchor.

    An anchor is `Path(__file__)` (or `pathlib.Path(__file__)`), with at most
    one `.resolve()` or `.absolute()`, and stands for the file; or a name bound
    at column 0 to it, which stands for the file, or to its `.parent`, which
    stands for its directory, and rebound nowhere else in the file. A chain is
    `.parent`s then at most one `.parents[N]`, at least one of them, and
    `height` is the levels it climbs from the file's directory: the file's
    anchor offsets it by -1, the directory's by 0.
    """
    found = []

    def add(anchor_end: int, offset: int) -> None:
        chain = _chain_at(text, anchor_end)
        if chain is not None:
            end, parents, index = chain
            found.append((anchor_end, end, offset + parents
                          + (0 if index is None else index + 1)))

    for anchor in _DIRECT_ANCHOR.finditer(text):
        add(anchor.end(), -1)
    for binding in _BINDING.finditer(text):
        name = binding.group(1)
        if _rebinds(name, text) != 1:
            continue
        offset = 0 if binding.group(2) else -1
        for use in re.finditer(r"(?<![\w.])" + re.escape(name) + r"(?!\w)",
                               text):
            add(use.end(), offset)
    return sorted(found)


def shift_chain(chain: str, delta: int) -> str | None:
    """`chain` climbing `delta` levels more, or None when it cannot: the
    `.parents[N]` index moves with the `.parent`s kept, and a chain of
    `.parent`s alone keeps at least one."""
    match = _CHAIN.fullmatch(chain)
    parents, index = match.group(1), match.group(2)
    if index is not None:
        shifted = int(index) + delta
        return None if shifted < 0 else f"{parents}.parents[{shifted}]"
    count = len(parents) // len(".parent") + delta
    return ".parent" * count if count >= 1 else None


def _depth_occurrences(path: str, text: str, base: Tree,
                       sources: tuple[str, ...], target: str, tree: str,
                       taken: Iterable[Occurrence]) -> list[Occurrence]:
    """The `../` climbs of `text` that the move to `target` leaves landing
    elsewhere, in text order.

    `P` and `Q` are the directories of the file before and after the move and
    `R` is the root of its tree; a file the plan archives has no tree of its
    own, so its directory stands for it. A climb is an occurrence when it ends
    at a proper ancestor of `R` (or above the repository root) and the same
    climb from `Q` ends elsewhere, unless its base target is inside `R`, which
    moves with the file. `rewrite` is offered when the climb ends at an
    ancestor of `Q` or above the root, its base target is no moved path and
    the shifted climb is valid.

    In a `.py` file the chains of `python_climbs` are read too, as climbs with
    no target text; one overlapping an occurrence in `taken`, which the other
    readings made in the same file, or a text climb accepted here is dropped.
    """
    old_dir, new_dir = path.rpartition("/")[0], target.rpartition("/")[0]
    root = tree if path.startswith(tree + "/") else old_dir
    delta = _depth_of(new_dir) - _depth_of(old_dir)

    def consider(start: int, end: int, height: int, rest: str | None,
                 shift: Callable[[int], str | None]) -> Occurrence | None:
        """`rest` is the text climb's rest, or None for a climb with no
        target text; `shift(delta)` is the shifted form or None."""
        landing = _landing(old_dir, height)
        if landing == _landing(new_dir, height):
            return None
        place, above = landing
        if not above and (place == root or not _is_ancestor(place, root)):
            return None
        moved_target = False
        if rest is not None and not above:
            segments = [s for s in (place + "/" + rest).split("/")
                        if s not in ("", ".")]
            base_target = "/".join(segments)
            if _is_ancestor(root, base_target):
                return None
            moved_target = _names_moved(base_target, base, sources)
        replacement = None
        if (above or _is_ancestor(place, new_dir)) and not moved_target:
            replacement = shift(delta)
        line, column = _position(text, start)
        return Occurrence(
            path, line, column, start, end, text[start:end],
            ("rewrite", "retain") if replacement is not None
            else ("retain",), (), replacement, None, target, tree, False, True)

    found = []
    for token in tokens(text):
        climb = split_climb(token.text)
        if climb is None:
            continue
        prefix, height, rest = climb
        occurrence = consider(
            token.start, token.end, height, rest,
            lambda d, p=prefix, h=height, r=rest: climb_form(p, h + d, r))
        if occurrence is not None:
            found.append(occurrence)
    if file_class(path) == ".py":
        claimed = [*taken, *found]
        for start, end, height in python_climbs(text):
            if any(start < o.end and o.start < end for o in claimed):
                continue
            occurrence = consider(
                start, end, height, None,
                lambda d, chain=text[start:end]: shift_chain(chain, d))
            if occurrence is not None:
                found.append(occurrence)
    return found


# --------------------------------------------------------------------------
# Edits
# --------------------------------------------------------------------------


def _edit(text: str, occurrence: Occurrence, answer: str
          ) -> tuple[int, int, str]:
    """The `(start, end, new)` splice an `extend` or `rewrite` answer makes.

    Raises `ValueError` for any other answer, a `rewrite` with no
    replacement, and an `extend` whose shape is neither `quoted` nor `line`.
    """
    if answer == "rewrite":
        if occurrence.replacement is None:
            raise ValueError(
                f"{occurrence.subject}: rewrite has no replacement")
        return occurrence.start, occurrence.end, occurrence.replacement
    if answer != "extend":
        raise ValueError(f"{occurrence.subject}: {answer!r} makes no edit")
    if occurrence.shape == "quoted":
        quote = text[occurrence.start - 1]
        return occurrence.end + 1, occurrence.end + 1, "".join(
            f", {quote}{form}{quote}" for form in occurrence.additions)
    if occurrence.shape != "line":
        raise ValueError(
            f"{occurrence.subject}: extend has no shape "
            f"{occurrence.shape!r}")
    line_start, line_end = _line_bounds(text, occurrence.start, occurrence.end)
    line = text[line_start:line_end]
    copies = [line[:occurrence.start - line_start] + form
              + line[occurrence.end - line_start:]
              for form in occurrence.additions]
    if line_end < len(text):
        return line_end + 1, line_end + 1, "".join(c + "\n" for c in copies)
    return line_end, line_end, "".join("\n" + c for c in copies)


# --------------------------------------------------------------------------
# The pure core
# --------------------------------------------------------------------------


def plan_references(texts: dict[str, str], paths: Iterable[str],
                    moves: Iterable[tuple[str, str]],
                    trees: Mapping[str, str],
                    depth_texts: Mapping[str, str] | None = None
                    ) -> References:
    """The occurrences of moved paths in `texts`, over the tree `paths`.

    `texts` is keyed by base path. `trees` maps each moved file to the tree
    its policy is named for; a moved file with no entry raises `ValueError`.
    `depth_texts`, keyed by base path as well, is read by the depth reading
    alone and only for a moved file; a path in both maps gets every reading.
    `contested` holds every path more than one file of the tree is left at:
    the destination of two moves, or of one move and a file that stays.
    """
    base, moved = Tree(paths), dict(moves)
    after = Tree((base.paths - moved.keys()) | set(moved.values()))
    landings = Counter(moved.get(path, path)
                       for path in base.paths | moved.keys())
    contested = frozenset(path for path, count in landings.items()
                          if count > 1)
    sources = tuple(moved)
    depth_texts = depth_texts or {}
    held: dict[str, str] = {}
    found: list[Occurrence] = []
    for path in sorted(set(texts) | set(depth_texts)):
        text = texts[path] if path in texts else depth_texts[path]
        target = moved.get(path, path)
        tree = None
        if path in moved:
            if path not in trees:
                raise ValueError(f"{path}: a moved file has no tree")
            tree = trees[path]
        shell = file_class(path) in SHELL_CLASSES
        occurrences = []
        if path in texts:
            for token in tokens(text):
                occurrence = _occurrence(path, text, token, base, after,
                                         moved, sources, target, tree, shell)
                if occurrence is not None:
                    occurrences.append(occurrence)
        if path in depth_texts and tree is not None:
            occurrences += _depth_occurrences(path, text, base, sources,
                                              target, tree, occurrences)
        if occurrences:
            held[path] = text
            found += occurrences
    found.sort(key=lambda o: (o.path, o.line, o.column))
    return References(held, tuple(found), contested)


def effective_answer(occurrence: Occurrence, answers: Mapping[str, str],
                     policies: Mapping[str, str]
                     ) -> tuple[str | None, str | None]:
    """`(answer, decided_by)` of an occurrence; `(None, None)` when open.

    The occurrence's own answer decides first (`occurrence`). Otherwise the
    answer given to its policy decides (`policy`) when the occurrence offers
    it. Raises `ValueError` for a policy answer outside `POLICY_ANSWERS`.
    """
    own = answers.get(occurrence.subject)
    if own is not None:
        return own, "occurrence"
    policy = occurrence.policy
    if policy is not None and policy in policies:
        value = policies[policy]
        if value not in POLICY_ANSWERS:
            raise ValueError(f"{policy}: {value!r} is not a policy answer")
        if value in occurrence.answers:
            return value, "policy"
    return None, None


def summary(references: References, answers: Mapping[str, str],
            policies: Mapping[str, str]) -> list[dict]:
    """One row per occurrence, in order, with the answer that decides it."""
    rows = []
    for o in references.occurrences:
        answer, decided_by = effective_answer(o, answers, policies)
        rows.append({
            "subject": o.subject, "path": o.path, "line": o.line,
            "column": o.column, "literal": o.literal,
            "answers": list(o.answers), "answer": answer,
            "additions": list(o.additions), "replacement": o.replacement,
            "target": o.target, "policy": o.policy,
            "decided_by": decided_by})
    return rows


def policy_summary(references: References, answers: Mapping[str, str],
                   policies: Mapping[str, str]) -> list[dict]:
    """One row per policy that has an occurrence, sorted by subject.

    `files` counts distinct base paths, `rewritable` the occurrences that
    offer `rewrite`, `rewritten`, `retained` and `extended` those decided by
    that answer, `open` those no answer decides and `overridden` those their
    own answer decides.
    """
    grouped: dict[str, list[tuple[Occurrence, str | None, str | None]]] = {}
    for o in references.occurrences:
        if o.policy is not None:
            grouped.setdefault(o.policy, []).append(
                (o, *effective_answer(o, answers, policies)))
    rows = []
    for subject, members in sorted(grouped.items()):
        first = members[0][0]
        decided = [answer for _, answer, _ in members]
        klass = first.occurrence_class
        rows.append({
            "subject": subject, "tree": first.tree, "class": klass,
            "recommended": recommended_answer(klass),
            "answer": policies.get(subject),
            "files": len({o.path for o, _, _ in members}),
            "occurrences": len(members),
            "rewritable": sum("rewrite" in o.answers for o, _, _ in members),
            "rewritten": decided.count("rewrite"),
            "retained": decided.count("retain"),
            "extended": decided.count("extend"),
            "open": decided.count(None),
            "overridden": sum(by == "occurrence" for _, _, by in members)})
    return rows


def rewritten(references: References, answers: Mapping[str, str],
              policies: Mapping[str, str]) -> dict[str, tuple[str, str]]:
    """`target -> (before, after)` for each file an answer edits.

    `before` is the base text, edited by base offsets; the key is where the
    plan leaves the file. A file whose text is unchanged is not returned, and
    neither is one whose target is in `references.contested`: its answers are
    still checked, and no edit is made at a path another file is also left
    at. Raises `ValueError` for an own answer the occurrence does not offer,
    for an offered one it cannot carry out (a `rewrite` with no replacement,
    an `extend` with no `quoted` or `line` shape, or an answer outside
    `ANSWERS`), and for two edited files with one target that is not
    contested.
    """
    edits: dict[str, list[tuple[int, int, str]]] = {}
    targets: dict[str, str] = {}
    for occurrence in references.occurrences:
        own = answers.get(occurrence.subject)
        if own is not None and own not in occurrence.answers:
            raise ValueError(f"{occurrence.subject}: {own!r} is not offered")
        answer, _ = effective_answer(occurrence, answers, policies)
        if answer is None or answer == "retain":
            continue
        triple = _edit(references.texts[occurrence.path], occurrence, answer)
        if occurrence.target in references.contested:
            continue
        targets[occurrence.path] = occurrence.target
        edits.setdefault(occurrence.path, []).append(triple)
    files: dict[str, tuple[str, str]] = {}
    for path, triples in edits.items():
        before = text = references.texts[path]
        for start, end, new in sorted(triples, key=lambda t: t[:2],
                                      reverse=True):
            text = text[:start] + new + text[end:]
        if text == before:
            continue
        if targets[path] in files:
            raise ValueError(
                f"{targets[path]!r} is the target of two edited files")
        files[targets[path]] = (before, text)
    return files


# --------------------------------------------------------------------------
# Reading a tree's text through git
# --------------------------------------------------------------------------


def derive_references(root: Path, revision: str,
                      moves: Iterable[tuple[str, str]],
                      excluded: Iterable[str],
                      trees: Mapping[str, str]) -> References:
    """The references `moves` leave in `revision`'s tracked text files.

    A file the moves carry is read like any other, at its base path; a record
    home is tested against that base path. `trees` names the tree of each
    moved file (see `plan_references`).
    """
    moves = list(moves)
    if not moves:
        return References({}, ())
    sources = {source for source, _ in moves}
    segments = sorted({source.split("/")[0] for source in sources})
    code, out = run_git(root, "grep", "--no-color", "-I", "-l", "-z", "-F",
                        *[arg for segment in segments
                          for arg in ("-e", segment)], revision)
    if code == 1:
        return References({}, ())
    if code != 0:
        raise refuse("adopt_failure", "adopt.git.failed", "",
                     "a git inspection command did not succeed")
    records = tree_records(root, revision)
    modes = {path: mode for path, mode, _ in records}
    skipped = set(excluded)
    texts: dict[str, str] = {}
    for result in split_nul(out):
        path = result.removeprefix(revision + ":")
        if (modes.get(path) not in REGULAR_MODES or is_markdown_path(path)
                or is_secret_path(path) or path in skipped
                or path.startswith(RECORD_HOMES)):
            continue
        data = blob_at(root, revision, path)
        if data is None:
            continue
        try:
            texts[path] = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return plan_references(texts, [path for path, _, _ in records], moves,
                           trees)
