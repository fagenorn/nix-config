"""The lane rule: which lane an issue takes to merge, from its body alone.

`choose(body, marked=, lane_paths=, given=)` returns `Lane(lane, reason)`; the first row that
matches wins: (1) a lane the caller `given`; (2) `marked` (a look marker) is standard; (3) no
lane paths (not a non-empty mapping of lists of str) is standard; (4) a named path under a lane
path set is standard, paths in body order, sets in sorted name order; (5) no acceptance
criteria, or over 3, is standard; (6) over 3 named files is standard; (7) else direct. The
caller reads the look marker, keeping this module out of `look_marker`'s import graph under the
engine size cap. A `body` that is not a str reads as "".

Named paths, line by line: a code span (one line) is a path when its stripped content is
`[A-Za-z0-9_.@+-]` segments joined by `/`, no leading `-`, no `.` or `..` segment, and holds a
`/` or ends in an extension. A bare token (the line without its spans, split on whitespace,
brackets, quotes and `,;*`, trailing `.:!?` stripped) needs a `/`, that shape (so no URL) and an
extension. Spans come first per line, then bare tokens; a repeat is skipped; a leading `./` and
a trailing `/` are removed. A file is a path written without a trailing `/` and ending in an
extension. Under a directory entry (ending in `/`): the directory or what starts with it; under
a file entry: it, or a bare name equal to its last segment. Acceptance criteria are the
checkbox items of every `Acceptance criteria` section, up to the next heading.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

MAX_FILES = 3
MAX_CRITERIA = 3
SHAPE = r"[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+-]+)*/?"
EXTENSION = r"[^/]+\.[A-Za-z][A-Za-z0-9]{0,9}"
SPAN = re.compile(r"(`+)(.+?)\1")
SEPARATORS = re.compile(r"[\s()\[\]<>\"',;*]+")
HEADING = re.compile(r"#{1,6}\s")
ACCEPTANCE = re.compile(r"#{1,6}\s+acceptance criteria\s*:?", re.IGNORECASE)
CHECKBOX = re.compile(r"\s{0,3}[-*+]\s+\[[ xX]\]\s")


@dataclass(frozen=True)
class Lane:
    lane: str
    reason: str


def _shaped(token: str) -> bool:
    return bool(re.fullmatch(SHAPE, token)) and token[0] != "-" and not {".", ".."} & set(token.split("/"))


def _extended(path: str) -> bool:
    return bool(re.fullmatch(EXTENSION, path.rsplit("/", 1)[-1]))


def _read(body: str) -> dict[str, bool]:  # each distinct normalized path, with whether it is a file
    found: dict[str, bool] = {}
    for line in body.splitlines():
        bare = [t.rstrip(".:!?") for t in SEPARATORS.split(SPAN.sub(" ", line))]
        tokens = [(m.group(2).strip(), True) for m in SPAN.finditer(line)] + [(t, False) for t in bare]
        for token, span in tokens:
            path = re.sub(r"^(\./)+", "", token)
            counts = ("/" in path or _extended(path)) if span else (
                "/" in path and _extended(path))
            if path and counts and _shaped(path):
                found.setdefault(path.removesuffix("/"), not path.endswith("/") and _extended(path))
    return found


def named_paths(body: str) -> tuple[str, ...]:
    return tuple(_read(body))


def criteria(body: str) -> int:
    """The checkbox items of every `Acceptance criteria` section."""
    count, inside = 0, False
    for line in body.splitlines():
        inside = bool(ACCEPTANCE.fullmatch(line.rstrip())) or inside and not HEADING.match(line)
        count += inside and bool(CHECKBOX.match(line))
    return count


def _under(path: str, lane_paths: Mapping[str, object]) -> str | None:
    for name in sorted(lane_paths):
        for entry in lane_paths[name]:
            if (path == entry[:-1] or path.startswith(entry)) if entry.endswith("/") else (
                    path == entry or ("/" not in path and path == entry.rsplit("/", 1)[-1])):
                return name
    return None


def choose(body: object, *, marked: bool, lane_paths: object, given: str | None = None) -> Lane:
    """The lane of the issue `body`, by the rule in the module docstring."""
    if given is not None:
        return Lane(given, "the caller gave the lane")
    if marked:
        return Lane("standard", "a look marker holds the merge for the owner's look")
    if not (isinstance(lane_paths, Mapping) and lane_paths and all(
            isinstance(v, (list, tuple)) and all(isinstance(e, str) for e in v) for v in lane_paths.values())):
        return Lane("standard", "the repository declares no lane paths")
    text = body if isinstance(body, str) else ""
    paths = _read(text)
    for path in paths:
        if (name := _under(path, lane_paths)) is not None:
            return Lane("standard", f"names {path}, under the {name} lane paths")
    n, files = criteria(text), sum(paths.values())
    if n == 0 or n > MAX_CRITERIA:
        return Lane("standard", f"acceptance criteria {n}, over the {MAX_CRITERIA} of the direct lane"
                    if n else "no acceptance criteria")
    if files > MAX_FILES:
        return Lane("standard", f"named files {files}, over the {MAX_FILES} of the direct lane")
    return Lane("direct", f"named files {files} of at most {MAX_FILES}, acceptance criteria {n} of at "
                          f"most {MAX_CRITERIA}, no look marker, no lane path")
