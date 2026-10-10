"""Render an sdd dispatch brief from a template's prompt body.

A template document holds exactly one unlabeled fenced block; the prompt body
is the text of that block after its `prompt: |` line, with the four-space
indent removed. The body names every value it takes as a bracketed capital
token (`TOKEN`), and a caller fills them all in one pass from a mapping that
holds exactly the template's token set.

The module only transforms text. It reads no file, so a caller passes the
template's text in.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

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
