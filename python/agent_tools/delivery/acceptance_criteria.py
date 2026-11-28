"""The acceptance criteria of an issue body: a pure parser, so the engine's graders and the console read one text alike.

`acceptance_criteria(body)` is the checkbox lines of the first `Acceptance criteria` heading section of `body`
(a heading of any level, an optional trailing `:` or closing `#` marks, any case), outside fences (a fence closes
only on a line of its own delimiter character, at least as long as the one that opened it, with nothing after it
but spaces; an unclosed fence runs to the end; a fence opens and closes with up to three spaces of indent beyond
the content column of the list item enclosing it, so a fenced example nested under a checkbox is no criterion, a
fence may open right after a list marker (`- ~~~`) and then belongs to that item, and an open fence also ends at
the first non-blank line indented less than that column, as its list item does). A heading inside a list item
(indented to its content column) is part of that item and ends nothing; only a heading outside every list item
ends the section.

A criterion is `Criterion(index, ticked, kind, text, line)`, `kind` being a leading `[code]`, `[evidence]`,
`[human]` or `[note]` tag or None, and a checkbox line's bullet (`-`, `*` or `+`) may be followed by any run of
spaces or tabs. `ac_id` is the id a verify block's `ac` uses for a criterion: `AC` and its 1-based index.

The module imports nothing but `re` and `dataclasses`: the engine core's purity test pins that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FENCE_OPEN = re.compile(r"^([ \t]*)(`{3,}|~{3,})")
_LIST_ITEM = re.compile(r"^([ \t]*)(?:[-*+]|\d{1,9}[.)])([ \t]+)")
_FENCE_RUN = re.compile(r"(`{3,}|~{3,})")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_AC_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+Acceptance criteria\s*:?\s*#*\s*$", re.IGNORECASE)
_CRITERION = re.compile(r"^\s*[-*+][ \t]+\[( |x|X)\][ \t]+(.*)$")
_KIND = re.compile(r"\[(code|evidence|human|note)\]\s*(.*)$")


def _list_prefixes(line: str) -> tuple[list[int], str]:
    """The content column of each list marker that opens `line` (`- - x` has two), and the text after them."""
    columns: list[int] = []
    position = 0
    while True:
        item = _LIST_ITEM.match(line[position:])
        if not item:
            return columns, line[position:]
        position += item.end()
        columns.append(len(line[:position].expandtabs(4)))


def _fence(run: str, column: int) -> tuple[re.Pattern, int, int]:
    """A fence opened by `run` inside a container whose content column is `column`: its closer, the widest indent
    that closer may have and the column below which a line ends the fence."""
    return (re.compile(r"^([ \t]*)" + re.escape(run[0]) + "{" + str(len(run)) + r",}[ \t]*$"), column + 3, column)


@dataclass(frozen=True)
class Criterion:
    index: int
    ticked: bool
    kind: str | None
    text: str
    line: int


def acceptance_criteria(body: str) -> list[Criterion]:
    """The checkbox lines of the first `Acceptance criteria` section of an issue body, outside fences."""
    criteria: list[Criterion] = []
    inside = False
    fence: tuple[re.Pattern, int, int] | None = None
    containers: list[int] = []
    for number, raw in enumerate(body.split("\n")):
        line = raw.removesuffix("\r")
        indent = len(re.match(r"[ \t]*", line).group().expandtabs(4))
        if fence is not None:
            closer, limit, column = fence
            closing = closer.match(line)
            if line.strip() and indent < column:
                fence = None
            else:
                if closing and len(closing.group(1).expandtabs(4)) <= limit:
                    fence = None
                continue
        if line.strip():
            while containers and indent < containers[-1]:
                containers.pop()
        base = containers[-1] if containers else 0
        opened = _FENCE_OPEN.match(line)
        if opened and indent - base <= 3:
            run = opened.group(2)
            fence = _fence(run, base)
            continue
        columns, rest = _list_prefixes(line)
        containers.extend(columns)
        sheltered = _FENCE_RUN.match(rest) if columns else None
        if sheltered:
            fence = _fence(sheltered.group(1), columns[-1])
            continue
        if not inside:
            inside = bool(_AC_HEADING.match(line))
            continue
        if _HEADING.match(line) and not containers:
            break
        box = _CRITERION.match(line)
        if not box:
            continue
        rest = box.group(2)
        tagged = _KIND.match(rest)
        kind, rest = (tagged.group(1), tagged.group(2)) if tagged else (None, rest)
        criteria.append(Criterion(len(criteria) + 1, box.group(1) != " ", kind, " ".join(rest.split()), number))
    return criteria


def ac_id(criterion: Criterion) -> str:
    """The id a verify block's `ac` uses for the criterion: `AC` and its 1-based index."""
    return f"AC{criterion.index}"
