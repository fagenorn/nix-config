"""Render an sdd dispatch brief from a template's prompt body.

A template document holds exactly one unlabeled fenced block; the prompt body
is the text of that block after its `prompt: |` line, with the four-space
indent removed. The body names every value it takes as a bracketed capital
token (`TOKEN`), and a caller fills them all in one pass from a mapping that
holds exactly the template's token set.

The values a brief takes from outside the template come from three readers: a
plan-header reader (`plan_section`, `task_row`), a standards selector that
reads the layered standards documents (`select_standards`, `standards_value`)
and the lifecycle worker block (`worker_block`). `prompt_body`, `render`,
`plan_section`, `task_row` and `worker_block` transform text a caller passes
in; only `select_standards` and `standards_value` read files, read-only. Every
refusal is a `BriefError`.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

TOKEN = re.compile(r"\[[A-Z0-9_]+\]")

IMPLEMENTER_TEMPLATE = "implementer-prompt.md"
REVIEWER_TEMPLATE = "task-reviewer-prompt.md"

_PLAN_TOKENS = frozenset({
    "[PLAN_ROOT]", "[PLAN_ROOT_BYTES]", "[PLAN_TOTAL_BYTES]", "[PLAN_FILE_COUNT]",
    "[PLAN_LARGEST_MEMBER_BYTES]",
})
_SHARED_TOKENS = _PLAN_TOKENS | {
    "[BRIEF_FILE]", "[REPORT_FILE]", "[GLOBAL_CONSTRAINTS]", "[STANDARDS]", "[STACKS_DIR]",
}

IMPLEMENTER_TOKENS = _SHARED_TOKENS | {
    "[TASK_NUMBER]", "[TASK_NAME]", "[CONTEXT]", "[TEST_SEAMS]", "[LIFECYCLE_WORKER]",
}
REVIEWER_TOKENS = _SHARED_TOKENS | {
    "[BASE_SHA]", "[HEAD_SHA]", "[MANIFEST_ROOT]", "[ROOT_BYTES]", "[TOTAL_BYTES]",
    "[FILE_COUNT]", "[LARGEST_MEMBER_BYTES]",
}
OPTIONAL_TOKENS = frozenset({"[CONTEXT]", "[LIFECYCLE_WORKER]"})

_FENCE = "```"
_PROMPT_LINE = "prompt: |"
_INDENT = " " * 4


class BriefError(Exception):
    """A template, plan header or standards layer a brief cannot be rendered from.

    The message is one line.
    """


def prompt_body(template_text: str) -> str:
    """Return the prompt body of a template document, tokens still in place.

    The body is the lines of the one unlabeled fenced block after its single
    `prompt: |` line. A fence line (one starting with three backticks) opens a
    block when none is open and closes the open block otherwise; a block with
    an info string is skipped whatever it holds. Each body line loses its four
    leading spaces, and a whitespace-only line becomes empty. The result ends
    with exactly one newline.

    Raises `BriefError` unless there is exactly one unlabeled block and it is
    closed, exactly one line of it is `prompt: |`, at least one body line
    follows, the last body line is not empty, and every non-blank body line
    starts with four spaces.
    """
    unlabeled: list[list[str]] = []
    current: list[str] | None = None
    labeled = False
    for line in template_text.splitlines():
        if line.startswith(_FENCE):
            if current is None and not labeled:
                if line[len(_FENCE):].strip():
                    labeled = True
                else:
                    current = []
            else:
                if current is not None:
                    unlabeled.append(current)
                current = None
                labeled = False
        elif current is not None:
            current.append(line)
    if current is not None:
        raise BriefError("template: the unlabeled fenced block is not closed")
    if len(unlabeled) != 1:
        raise BriefError(
            f"template: expected exactly one unlabeled fenced block, found {len(unlabeled)}")
    block = unlabeled[0]
    starts = [index for index, line in enumerate(block) if line.strip() == _PROMPT_LINE]
    if len(starts) != 1:
        raise BriefError(
            f"template: expected exactly one `{_PROMPT_LINE}` line, found {len(starts)}")
    body: list[str] = []
    for index in range(starts[0] + 1, len(block)):
        line = block[index]
        if not line.strip():
            body.append("")
        elif line.startswith(_INDENT):
            body.append(line[len(_INDENT):])
        else:
            raise BriefError(
                f"template: block line {index + 1} is not indented by four spaces")
    if not body:
        raise BriefError("template: the prompt has no body line")
    if not body[-1]:
        raise BriefError("template: the last body line is empty")
    return "\n".join(body) + "\n"


def render(template_text: str, tokens: frozenset[str], values: Mapping[str, str]) -> str:
    """Fill a template's prompt body from `values` and return the brief.

    The tokens found in `prompt_body(template_text)` must equal `tokens`, and
    `values` must hold exactly those keys. A token in `OPTIONAL_TOKENS` must
    stand alone on one line, occurring once; when its value is empty, that
    line and an empty line right after it are removed. Any other token needs
    a non-empty value. All tokens are replaced in one pass and a value is
    inserted byte for byte, never scanned for tokens, so a value that spells a
    token or a backslash comes through unchanged.

    Raises `BriefError` for a template that is not a prompt body (see
    `prompt_body`), a token set that differs from the body's, a value set that
    differs from `tokens`, an optional token that does not stand alone, or an
    empty value for a required token.
    """
    body = prompt_body(template_text)
    present = set(TOKEN.findall(body))
    if present != tokens:
        raise BriefError("template drift: tokens in only one of the template and the "
                         f"expected set: {', '.join(sorted(present ^ tokens))}")
    if set(values) != tokens:
        raise BriefError("values differ from the tokens: "
                         f"{', '.join(sorted(set(values) ^ tokens))}")
    lines = body[:-1].split("\n")
    for token in sorted(tokens & OPTIONAL_TOKENS):
        if body.count(token) != 1 or token not in lines:
            raise BriefError(f"optional token {token} must stand alone on one line")
    for token in sorted(tokens - OPTIONAL_TOKENS):
        if values[token] == "":
            raise BriefError(f"required token {token} has an empty value")
    dropped: set[int] = set()
    for token in sorted(tokens & OPTIONAL_TOKENS):
        if values[token] == "":
            index = lines.index(token)
            dropped.add(index)
            if index + 1 < len(lines) and lines[index + 1] == "":
                dropped.add(index + 1)
    kept = "\n".join(line for index, line in enumerate(lines) if index not in dropped) + "\n"
    return TOKEN.sub(lambda match: values[match.group(0)], kept)


_TASK_INDEX = "## Task index"
_SEPARATOR = re.compile(r"\s+\u2014\s+")
_BACKTICKED = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_BAR = "the-bar.md"
_STANDARDS_INDEX = "README.md"
_GOVERNS = "governs"


@dataclass(frozen=True)
class TaskRow:
    """The title and touched paths of one row of a plan's Task index."""

    title: str
    paths: tuple[str, ...]


def _section_lines(plan_text: str, heading: str) -> list[str]:
    """Return the lines after the one line equal to `heading`, up to the next `## ` line."""
    lines = plan_text.splitlines()
    starts = [index for index, line in enumerate(lines) if line == heading]
    if len(starts) != 1:
        raise BriefError(f"plan: expected exactly one `{heading}` line, found {len(starts)}")
    body: list[str] = []
    for line in lines[starts[0] + 1:]:
        if line.startswith("## "):
            break
        body.append(line)
    return body


def plan_section(plan_text: str, heading: str) -> str:
    """Return the body of the plan section whose heading line equals `heading`.

    The body is the lines after that line up to the next line starting with
    `## `, or the end. Empty lines (whitespace-only ones too) are dropped from
    both ends, the rest is joined with `"\\n"` and there is no final newline;
    a section with no content gives `""`.

    Raises `BriefError` unless exactly one line equals `heading`.
    """
    body = _section_lines(plan_text, heading)
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body)


def task_row(plan_text: str, number: int) -> TaskRow:
    """Return the title and touched paths of task `number` from the Task index.

    Only the lines of the one `## Task index` section are searched, and
    exactly one of them may start `Task <number>` followed by whitespace and
    an em dash. The row's fields are split on a spaced em dash: the title is
    the text from the first separator to the third-from-last, so it may hold a
    spaced em dash itself, and the files field is the text up to the
    second-from-last. The paths are every backticked span of the files field,
    in order.

    Raises `BriefError` unless the plan has exactly one Task index, exactly
    one row for `number`, and at least four separators in that row.
    """
    pattern = re.compile(rf"^Task {re.escape(str(number))}\s+\u2014")
    rows = [line for line in _section_lines(plan_text, _TASK_INDEX) if pattern.match(line)]
    if len(rows) != 1:
        raise BriefError(f"plan: expected exactly one Task index row for task {number}, "
                         f"found {len(rows)}")
    row = rows[0]
    separators = list(_SEPARATOR.finditer(row))
    if len(separators) < 4:
        raise BriefError(f"plan: the Task index row for task {number} has "
                         f"{len(separators)} separators, expected at least 4")
    title = row[separators[0].end():separators[-3].start()]
    files = row[separators[-3].end():separators[-2].start()]
    return TaskRow(title, tuple(_BACKTICKED.findall(files)))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise BriefError(f"standards: cannot read {path}: {error.__class__.__name__}") from error


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _governed_documents(entry: Path, touched: Sequence[str]) -> list[Path]:
    """Return the documents of a standards directory whose `governs` globs match `touched`."""
    index = entry / _STANDARDS_INDEX
    if not index.is_file():
        return []
    lines = _read_text(index).splitlines()
    header = next((number for number, line in enumerate(lines)
                   if line.startswith("|") and _GOVERNS in _cells(line)), None)
    if header is None:
        return []
    column = _cells(lines[header]).index(_GOVERNS)
    root = entry.resolve()
    selected: list[Path] = []
    for line in lines[header + 1:]:
        if not line.startswith("|"):
            break
        cells = _cells(line)
        if all(set(cell) <= set("-: ") for cell in cells):
            continue
        if column >= len(cells):
            raise BriefError(f"standards: a row of {index} has no `{_GOVERNS}` cell")
        link = _LINK.search(line)
        if link is None:
            raise BriefError(f"standards: a row of {index} holds no link")
        target = entry / link.group(1)
        resolved = target.resolve()
        if not resolved.is_file() or not resolved.is_relative_to(root):
            raise BriefError(f"standards: {index} links {link.group(1)}, "
                             f"which is not a file inside {entry}")
        globs = _BACKTICKED.findall(cells[column])
        if any(fnmatch.fnmatchcase(path, glob) for glob in globs for path in touched):
            selected.append(Path(os.path.abspath(target)))
    return selected


def select_standards(global_dir: Path, entries: Sequence[Path], touched: Sequence[str]) -> list[Path]:
    """Return the standards documents a task over `touched` is bound by, first layer first.

    The first document is always `global_dir / "the-bar.md"`. Each entry, in
    the order given, then contributes: a regular file, whole; a directory,
    the documents linked by the rows of the table in its `README.md` whose
    header has a `governs` column and one of whose backticked globs matches a
    touched repository-relative path under `fnmatch.fnmatchcase`. A directory
    without a `README.md` or without such a table contributes nothing. Every
    table row is checked, matching or not. Paths are absolute and normalized
    but symlinks are left unresolved; a document already listed is not listed
    again. Nothing is written.

    Raises `BriefError` for a missing `the-bar.md`, an entry that is neither a
    regular file nor a directory, an unreadable `README.md`, and a table row
    with no `governs` cell, no Markdown link, or a link that is not a regular
    file inside the directory.
    """
    bar = global_dir / _BAR
    if not bar.is_file():
        raise BriefError(f"standards: {bar} is not a file")
    documents = [Path(os.path.abspath(bar))]
    for entry in entries:
        if entry.is_file():
            chosen = [Path(os.path.abspath(entry))]
        elif entry.is_dir():
            chosen = _governed_documents(entry, touched)
        else:
            raise BriefError(f"standards: {entry} is neither a file nor a directory")
        documents.extend(path for path in chosen if path not in documents)
    return documents


def standards_value(documents: Sequence[Path]) -> str:
    """Return the `[STANDARDS]` value: each document under a `Source: <path>` line.

    A block is the source line, an empty line and the document's strict UTF-8
    text without its trailing newlines; blocks are joined with an empty line
    and the value has no final newline.

    Raises `BriefError` for a document that cannot be read or decoded.
    """
    blocks = []
    for path in documents:
        text = _read_text(path).rstrip("\n")
        blocks.append(f"Source: {path}\n\n{text}")
    return "\n\n".join(blocks)


def worker_block(repo_root: str, run_id: str, worker_id: str) -> str:
    """Return the three lines that bind a dispatched worker to its lifecycle launch.

    The `Lifecycle worker:` line carrying the three flags, then the sentence
    that runs each long command through `launch-scope exec` and the sentence
    that creates scratch directories under the `launch-scope scratch` path,
    joined with a newline.
    """
    flags = f"--repo-root {repo_root} --run-id {run_id} --worker-id {worker_id}"
    return "\n".join([
        f"Lifecycle worker: {flags}",
        "Run each long command, every verification command included, as "
        f"`launch-scope exec {flags} -- <argv>`, still in the foreground.",
        "Create every scratch directory or scratch worktree under the path that "
        f"`launch-scope scratch {flags}` prints."])
