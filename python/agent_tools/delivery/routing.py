"""The pure core of routing: which standards shards and records one change's paths reach.

A stack shard is chosen only by `STACK_SHARDS`, a project shard only by a `governs` glob of the
Layer-2 index, an area's record index only by a `governs` glob of the context map. Nothing here
touches a process, the network or the clock; callers hand over bytes and get numbers and names.
"""

from __future__ import annotations

import fnmatch
import posixpath
import re
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import NamedTuple

from agent_tools.delivery.context_map_lint import CODE_RE, LINK_RE, section, table_rows
from agent_tools.delivery.record_lint import is_record_path
from agent_tools.delivery.rule_ids import scan

BAR = "the-bar.md"
STACKS_DIR = "stacks"
LAYER2_DIR = "docs/standards"
LAYER2_INDEX = "docs/standards/README.md"
CONTEXT_MAP = "docs/CONTEXT-MAP.md"

STACK_SHARDS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    ".py": ("python.md",),
    "pyproject.toml": ("python.md",),
    ".js": ("node.md",),
    ".mjs": ("node.md",),
    "package.json": ("node.md",),
    ".ts": ("typescript-react.md",),
    ".tsx": ("typescript-react.md",),
    ".cs": ("dotnet-ai.md", "dotnet-data.md", "dotnet.md"),
    ".csproj": ("dotnet-ai.md", "dotnet-data.md", "dotnet.md"),
    ".slnx": ("dotnet-ai.md", "dotnet-data.md", "dotnet.md"),
})

RECORD_HEADER_RE = re.compile(r"\A#\s+(ADR-[a-z0-9][a-z0-9-]*-\d{3})\s+—\s+(\S.*?)\s*\Z")


class Platform(NamedTuple):
    directory: Path
    files: Mapping[str, bytes]


class Shard(NamedTuple):
    path: str
    globs: tuple[str, ...]


class Record(NamedTuple):
    id: str
    title: str
    path: str


class Area(NamedTuple):
    name: str
    globs: tuple[str, ...]
    records: tuple[Record, ...]


class Project(NamedTuple):
    files: Mapping[str, bytes]
    shards: tuple[Shard, ...]
    areas: tuple[Area, ...]


def stack_shards(path: str) -> tuple[str, ...]:
    pure = PurePosixPath(path)
    return STACK_SHARDS.get(pure.name) or STACK_SHARDS.get(pure.suffix.lower(), ())


def glob_matches(glob: str, path: str) -> bool:
    return fnmatch.fnmatchcase(path, glob)


def index_table(text: str) -> list[list[str]]:
    """The rows of the first run of rendered `|` lines, separator rows dropped, the header first.

    A line inside a fence or an HTML block (a comment included) is not rendered and breaks the run.
    """
    rows: list[list[str]] = []
    previous = None
    for number, line, _ in scan(text):
        line = line.strip()
        if not line.startswith("|") or (previous is not None and number != previous + 1):
            if rows:
                break
            continue
        previous = number
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not all(set(cell) <= set("-: ") for cell in cells):
            rows.append(cells)
    return rows


def is_input(path: str) -> bool:
    """True for a file `read_project` reads: the Layer-2 shards and index, the map, the records."""
    parts = path.split("/")
    shard = (len(parts) == 3 and path.startswith(LAYER2_DIR + "/") and path.endswith(".md"))
    return path == LAYER2_INDEX or shard or path == CONTEXT_MAP or is_record_path(path)


def load_platform(directory: Path) -> Platform:
    """The bar and every stack shard of a platform standards directory.

    Raises `ValueError` when the bar is not a regular file.
    """
    if not (directory / BAR).is_file():
        raise ValueError(f"no {BAR} in {directory}")
    files = {BAR: (directory / BAR).read_bytes()}
    for path in sorted((directory / STACKS_DIR).glob("*.md")):
        if path.is_file():
            files[f"{STACKS_DIR}/{path.name}"] = path.read_bytes()
    return Platform(directory, files)


def _text(files: Mapping[str, bytes], path: str) -> str:
    return files[path].decode("utf-8", errors="replace")


def _shards(files: Mapping[str, bytes]) -> tuple[Shard, ...]:
    if LAYER2_INDEX not in files:
        return ()
    rows = index_table(_text(files, LAYER2_INDEX))
    if not rows:
        return ()
    header = [cell.lower() for cell in rows[0]]
    if "governs" not in header:
        return ()
    column = header.index("governs")
    shards = []
    for row in rows[1:]:
        link = LINK_RE.search(row[0]) if row else None
        if not link or len(row) <= column:
            continue
        path = f"{LAYER2_DIR}/{link.group(1).removeprefix('./')}"
        if path in files:
            shards.append(Shard(path, tuple(CODE_RE.findall(row[column]))))
    return tuple(shards)


def _records(files: Mapping[str, bytes], directory: str) -> tuple[Record, ...]:
    records = []
    for path in sorted(files):
        if not (path.startswith(f"{directory}/adr/") and is_record_path(path)):
            continue
        first = _text(files, path).split("\n", 1)[0]
        match = RECORD_HEADER_RE.match(first)
        if match:
            records.append(Record(match.group(1), match.group(2), path))
    return tuple(records)


def _areas(files: Mapping[str, bytes]) -> tuple[Area, ...]:
    if CONTEXT_MAP not in files:
        return ()
    areas = []
    for row in table_rows(section(_text(files, CONTEXT_MAP), "Areas")):
        link = LINK_RE.search(row[1]) if len(row) >= 4 else None
        if not link:
            continue
        directory = posixpath.normpath(posixpath.join("docs", posixpath.dirname(link.group(1))))
        areas.append(Area(row[0], tuple(CODE_RE.findall(row[3])), _records(files, directory)))
    return tuple(areas)


def read_project(files: Mapping[str, bytes]) -> Project:
    """The shards and areas the project's input files declare; keys are repo-relative POSIX paths."""
    inputs = {path: content for path, content in files.items() if is_input(path)}
    return Project(inputs, _shards(inputs), _areas(inputs))


def index_line(record: Record) -> str:
    return f"{record.id} — {record.title}"


def index_bytes(areas: Iterable[Area]) -> int:
    return sum(len(index_line(r).encode("utf-8")) + 1 for area in areas for r in area.records)


def single_path_bytes(project: Project, platform: Platform, path: str) -> int:
    """The size of what one path routes: the bar, its stack and project shards, its areas' index.

    Raises `ValueError` for a routed stack file the platform lacks.
    """
    total = len(platform.files[BAR])
    for name in stack_shards(path):
        shard = platform.files.get(f"{STACKS_DIR}/{name}")
        if shard is None:
            raise ValueError(f"the platform has no {STACKS_DIR}/{name}")
        total += len(shard)
    total += sum(len(project.files[s.path]) for s in project.shards
                 if any(glob_matches(g, path) for g in s.globs))
    return total + index_bytes(a for a in project.areas if any(glob_matches(g, path) for g in a.globs))
