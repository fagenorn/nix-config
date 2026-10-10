"""A path reference in a tracked tooling file and the edit that keeps it true.

This module owns the model `adopt` uses to find a repository path written in
a tracked, non-Markdown text file that a relocation would leave pointing at a
path that moved (#350): the token grammar (`tokens`, `split_token`), the
successors of a referenced path and the carried form of a successor
(`successors`, `carried_form`), the occurrences with the shape of each and the
answers each offers (`Occurrence`, `plan_references`), the edits an answer
makes (`summary`, `rewritten`), and the reader that feeds the core a tree's
text through git (`derive_references`, over `adopt_inspection.tree_records`
and `blob_at`).

It is imported and never run. It reads blobs only through git, never the
working tree, writes nothing, and imports `adopt_inspection` and `adopt_links`
only. Standard library only; no per-language parser is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from agent_tools.adopt_inspection import (
    blob_at, is_secret_path, refuse, run_git, split_nul, tree_records)
from agent_tools.adopt_links import (
    REGULAR_MODES, Tree, directory_successor, is_markdown_path)

ANSWERS = ("extend", "rewrite", "retain")
TOKEN_DELIMITERS = "\"'`,;:=()<>|&#!"
GLOB_CHARACTERS = "*?[{"
CARRIED_TAILS = ("", "/", "/**")
# The paths whose files are records of what was, never read for references.
RECORD_HOMES = (".agents/artifacts/", ".agents/knowledge/archive/")

_QUOTES = "\"'"
_OPENING_BEFORE = "[{,"
_CLOSING_REST = ",])}"
_NOT_A_CALL_BEFORE = "_)]"


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
        return True, [(moved.get(path, path), False)]
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
    whole = tokens(form)
    if len(whole) != 1 or (whole[0].start, whole[0].end) != (0, len(form)):
        return None
    return form if split_token(form)[1] == successor else None


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

    @property
    def subject(self) -> str:
        return f"{self.path}:{self.line}:{self.column}"


@dataclass(frozen=True)
class References:
    texts: dict[str, str]
    occurrences: tuple[Occurrence, ...]


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


def _occurrence(path: str, text: str, token: Token, base: Tree, after: Tree,
                moved: dict[str, str], sources: tuple[str, ...]
                ) -> Occurrence | None:
    if "/" not in token.text and not _is_quoted(text, token):
        return None
    prefix, target, tail = split_token(token.text)
    if not target or (target not in base.paths
                      and target not in base.directories):
        return None
    if not any(s == target or s.startswith(target + "/") for s in sources):
        return None
    single, found = successors(target, base, after, moved)
    forms = [carried_form(prefix, successor, is_directory, tail, single)
             for successor, is_directory in found]
    shape = _shape(text, token)
    answers = []
    additions: tuple[str, ...] = ()
    replacement = None
    if shape is not None and forms and None not in forms:
        answers.append("extend")
        additions = tuple(forms)
    if single and forms and forms[0] is not None:
        answers.append("rewrite")
        replacement = forms[0]
    answers.append("retain")
    return Occurrence(path, token.line, token.column, token.start, token.end,
                      token.text, tuple(answers), additions, replacement,
                      shape)


# --------------------------------------------------------------------------
# Edits
# --------------------------------------------------------------------------


def _edit(text: str, occurrence: Occurrence, answer: str
          ) -> tuple[int, int, str]:
    if answer == "rewrite":
        return occurrence.start, occurrence.end, occurrence.replacement or ""
    if occurrence.shape == "quoted":
        quote = text[occurrence.start - 1]
        return occurrence.end + 1, occurrence.end + 1, "".join(
            f", {quote}{form}{quote}" for form in occurrence.additions)
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
                    moves: Iterable[tuple[str, str]]) -> References:
    """The occurrences of moved paths in `texts`, over the tree `paths`."""
    base, moved = Tree(paths), dict(moves)
    after = Tree((base.paths - moved.keys()) | set(moved.values()))
    sources = tuple(moved)
    held: dict[str, str] = {}
    found: list[Occurrence] = []
    for path in sorted(texts):
        text = texts[path]
        for token in tokens(text):
            occurrence = _occurrence(path, text, token, base, after, moved,
                                     sources)
            if occurrence is not None:
                held[path] = text
                found.append(occurrence)
    found.sort(key=lambda o: (o.path, o.line, o.column))
    return References(held, tuple(found))


def summary(references: References, answers: dict[str, str]) -> list[dict]:
    """One row per occurrence, in order, with the answer given to it."""
    return [{"subject": o.subject, "path": o.path, "line": o.line,
             "column": o.column, "literal": o.literal,
             "answers": list(o.answers), "answer": answers.get(o.subject),
             "additions": list(o.additions), "replacement": o.replacement}
            for o in references.occurrences]


def rewritten(references: References, answers: dict[str, str]
              ) -> dict[str, tuple[str, str]]:
    """`path -> (before, after)` for each file an `extend` or `rewrite` edits.

    Raises `ValueError` for an answer the occurrence does not offer.
    """
    edits: dict[str, list[tuple[int, int, str]]] = {}
    for occurrence in references.occurrences:
        answer = answers.get(occurrence.subject)
        if answer is None:
            continue
        if answer not in occurrence.answers:
            raise ValueError(
                f"{occurrence.subject}: {answer!r} is not offered")
        if answer != "retain":
            edits.setdefault(occurrence.path, []).append(
                _edit(references.texts[occurrence.path], occurrence, answer))
    files = {}
    for path, triples in edits.items():
        before = text = references.texts[path]
        for start, end, new in sorted(triples, key=lambda t: t[:2],
                                      reverse=True):
            text = text[:start] + new + text[end:]
        files[path] = (before, text)
    return files


# --------------------------------------------------------------------------
# Reading a tree's text through git
# --------------------------------------------------------------------------


def derive_references(root: Path, revision: str,
                      moves: Iterable[tuple[str, str]],
                      excluded: Iterable[str]) -> References:
    """The references `moves` leave in `revision`'s tracked text files."""
    moves = list(moves)
    if not moves:
        return References({}, ())
    sources = {source for source, _ in moves}
    segments = sorted({source.split("/")[0] for source in sources})
    code, out = run_git(root, "grep", "-I", "-l", "-z", "-F",
                        *[arg for segment in segments
                          for arg in ("-e", segment)], revision)
    if code == 1:
        return References({}, ())
    if code != 0:
        raise refuse("adopt_failure", "adopt.git.failed", "",
                     "a git inspection command did not succeed")
    records = tree_records(root, revision)
    modes = {path: mode for path, mode, _ in records}
    skipped = set(excluded) | sources
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
    return plan_references(texts, [path for path, _, _ in records], moves)
