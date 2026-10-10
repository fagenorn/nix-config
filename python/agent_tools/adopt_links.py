"""A relative Markdown link and what it resolves to over a set of tracked paths.

This module owns the link model `adopt` uses to keep Markdown links resolving
across a move (#345): the grammar that finds a link target in a Markdown text
(`links`), the relativity test and the resolution of a target against a tree
of paths (`is_relative`, `resolve`), the mapping of each target onto its
successor and the re-emission of the target (`plan_link_rewrites`), and the
readers that feed it a tree's Markdown (`index_records`, `markdown_texts`,
`derive_link_rewrites`, over `adopt_inspection.tree_records`, which it
re-exports).

It is imported and never run. It reads blobs only through git, never the
working tree, and imports `adopt_inspection` and nothing that imports the
resolver (#345 D3, #148 D26). Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
import posixpath
from pathlib import Path
import re
from typing import Iterable
import urllib.parse

from agent_tools.adopt_inspection import (
    git_or_fail, is_secret_path, refuse, run_git, split_nul, tree_records)

MARKDOWN_SUFFIXES = (".md", ".markdown")
REGULAR_MODES = ("100644", "100755")

# The characters an angle-bracket target must percent-encode so the path part
# it emits neither gains a suffix nor changes what it decodes to (D18).
ANGLE_ESCAPED = "%#?<>\r\n"

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
REFERENCE = re.compile(
    r"^ {0,3}\[(?!\^)(?:[^\[\]\\]|\\.)+\]:[ \t]*"
    r"(?:<(?P<angle>[^<>\r]*)>|(?P<bare>[^\s<]\S*))(?:[ \t]+.*)?\r?$")


def is_markdown_path(path: str) -> bool:
    lowered = "".join(c.lower() if c.isascii() else c for c in path)
    return lowered.endswith(MARKDOWN_SUFFIXES)


def scanned(path: str, mode: str) -> bool:
    """Whether `adopt` reads the file for links (D2)."""
    return (mode in REGULAR_MODES and is_markdown_path(path)
            and not is_secret_path(path))


# --------------------------------------------------------------------------
# Grammar
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Link:
    start: int
    end: int
    target: str
    angle: bool


def _mask_code_spans(line: str) -> list[bool]:
    masked = [False] * len(line)
    i = 0
    while i < len(line):
        if line[i] != "`":
            i += 1
            continue
        j = i
        while j < len(line) and line[j] == "`":
            j += 1
        run = j - i
        k = j
        closed = -1
        while k < len(line):
            if line[k] != "`":
                k += 1
                continue
            m = k
            while m < len(line) and line[m] == "`":
                m += 1
            if m - k == run:
                closed = m
                break
            k = m
        if closed < 0:
            i = j
            continue
        for p in range(i, closed):
            masked[p] = True
        i = closed
    return masked


def _matching_bracket(line: str, masked: list[bool], opener: int) -> int:
    depth = 1
    j = opener + 1
    while j < len(line):
        if masked[j]:
            j += 1
            continue
        char = line[j]
        if char == "\\":
            j += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _skip_blanks(line: str, i: int) -> int:
    while i < len(line) and line[i] in " \t":
        i += 1
    return i


def _destination(line: str, i: int) -> tuple[int, int, bool, int] | None:
    """`(start, end, angle, next index)` of the destination at `i`, or None."""
    if i < len(line) and line[i] == "<":
        j = i + 1
        while j < len(line) and line[j] not in "<>":
            j += 1
        if j >= len(line) or line[j] != ">":
            return None
        return i + 1, j, True, j + 1
    depth = 0
    j = i
    while j < len(line):
        char = line[j]
        if char.isspace():
            break
        if char == "\\":
            j += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                break
            depth -= 1
        j += 1
    j = min(j, len(line))
    if depth != 0:
        return None
    return i, j, False, j


def _title_end(line: str, i: int) -> int | None:
    """The index after the title at `i`, or None when it never closes."""
    closer = {'"': '"', "'": "'", "(": ")"}[line[i]]
    j = i + 1
    while j < len(line):
        if line[j] == "\\":
            j += 2
            continue
        if line[j] == closer:
            return j + 1
        j += 1
    return None


def _inline_links(line: str, offset: int) -> list[Link]:
    masked = _mask_code_spans(line)
    covered: set[int] = set()
    found: list[Link] = []
    for i, char in enumerate(line):
        if char != "[" or masked[i] or i in covered:
            continue
        slashes = 0
        while i - slashes - 1 >= 0 and line[i - slashes - 1] == "\\":
            slashes += 1
        if slashes % 2:
            continue
        close = _matching_bracket(line, masked, i)
        if close < 0 or line[close + 1:close + 2] != "(":
            continue
        dest = _destination(line, _skip_blanks(line, close + 2))
        if dest is None:
            continue
        start, end, angle, k = dest
        k = _skip_blanks(line, k)
        if k < len(line) and line[k] in "\"'(":
            after = _title_end(line, k)
            if after is None:
                continue
            k = _skip_blanks(line, after)
        if line[k:k + 1] != ")":
            continue
        # The region from the opening `(` to the closing `)` holds the
        # destination and the title: no later opener inside it starts a link,
        # and a candidate whose region reaches into it is not one. The label
        # stays open, so an image inside link text is still found (D15).
        region = range(close + 1, k + 1)
        if any(p in covered for p in region):
            continue
        found.append(Link(offset + start, offset + end, line[start:end],
                          angle))
        covered.update(region)
    return found


def links(text: str) -> list[Link]:
    """Every link and reference definition in `text`, ordered by start."""
    found: list[Link] = []
    fence: tuple[str, int] | None = None
    offset = 0
    for line in text.split("\n"):
        here = offset
        offset += len(line) + 1
        if fence is not None:
            char, size = fence
            if re.match(" {0,3}" + re.escape(char) + "{%d,}[ \\t]*\\r?$" % size,
                        line):
                fence = None
            continue
        opening = _FENCE_OPEN.match(line)
        if opening and not (opening.group(1)[0] == "`"
                            and "`" in opening.group(2)):
            fence = (opening.group(1)[0], len(opening.group(1)))
            continue
        reference = REFERENCE.match(line)
        if reference:
            group = "angle" if reference.group("angle") is not None \
                else "bare"
            found.append(Link(here + reference.start(group),
                              here + reference.end(group),
                              reference.group(group), group == "angle"))
            continue
        found.extend(_inline_links(line, here))
    return sorted(found, key=lambda link: link.start)


def is_relative(target: str) -> bool:
    """Whether `target` names a path relative to its containing file (D3)."""
    return not (target == "" or target[0] in "#/" or _SCHEME.match(target)
                or "\\" in target)


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


class Tree:
    def __init__(self, paths: Iterable[str]) -> None:
        self.paths: frozenset[str] = frozenset(paths)
        directories = set()
        for path in self.paths:
            parts = path.split("/")
            for count in range(1, len(parts)):
                directories.add("/".join(parts[:count]))
        self.directories: frozenset[str] = frozenset(directories)


@dataclass(frozen=True)
class Resolved:
    path: str
    directory: bool


def _split_target(target: str) -> tuple[str, str]:
    cut = len(target)
    for mark in "?#":
        index = target.find(mark)
        if index >= 0:
            cut = min(cut, index)
    return target[:cut], target[cut:]


def resolve(container: str, target: str, tree: Tree) -> Resolved | None:
    """What a relative `target` in `container` names in `tree`, or None."""
    raw, _ = _split_target(target)
    path = urllib.parse.unquote(raw)
    joined = posixpath.normpath(
        posixpath.join(posixpath.dirname(container), path))
    if joined == ".." or joined.startswith("../"):
        return None
    if joined == ".":
        return Resolved("", True)
    if not path.endswith("/") and joined in tree.paths:
        return Resolved(joined, False)
    if joined in tree.directories:
        return Resolved(joined, True)
    return None


def broken_count(container: str, text: str, tree: Tree) -> int:
    return sum(1 for link in links(text)
               if is_relative(link.target)
               and resolve(container, link.target, tree) is None)


# --------------------------------------------------------------------------
# Mapping and re-emission
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RewrittenFile:
    source: str
    before: str
    after: str


@dataclass(frozen=True)
class LinkRewrites:
    summary: dict
    files: dict[str, RewrittenFile]


def angle_target(path: str) -> str:
    return "".join(f"%{ord(c):02X}" if c in ANGLE_ESCAPED else c
                   for c in path)


def _directory_successor(directory: str, base: Tree, after: Tree,
                         moved: dict[str, str]) -> str | None:
    """Where a directory's contents went, or None when they went apart."""
    if directory in after.directories:
        return directory
    prefixes = set()
    for member in base.paths:
        if not member.startswith(directory + "/"):
            continue
        tail = member[len(directory):]
        if member not in moved or not moved[member].endswith(tail):
            return None
        prefixes.add(moved[member][:-len(tail)])
    if len(prefixes) != 1:
        return None
    (prefix,) = prefixes
    return prefix or None


def _successor(resolved: Resolved, base: Tree, after: Tree,
               moved: dict[str, str], deleted: set[str]) -> str | None:
    if not resolved.directory:
        if resolved.path in moved:
            return moved[resolved.path]
        return None if resolved.path in deleted else resolved.path
    if resolved.path == "":
        return ""
    return _directory_successor(resolved.path, base, after, moved)


def _emitted(link: Link, resolved: Resolved, successor: str,
             container_after: str) -> str | None:
    """The new target text, or None when the link already resolves right."""
    raw, suffix = _split_target(link.target)
    here = posixpath.dirname(container_after)
    if posixpath.normpath(posixpath.join(here, urllib.parse.unquote(raw))) \
            == (successor or "."):
        return None
    rel = posixpath.relpath(successor or ".", here or ".")
    if raw.startswith("./") and rel != "." and not rel.startswith("../"):
        rel = "./" + rel
    if resolved.directory and raw.endswith("/"):
        rel += "/"
    if link.angle:
        # `quote` encodes a bare target's `:`, but an angle target keeps it
        # raw, so a first segment like `urn:x.md` would read as a URL scheme
        # and stop counting as relative; `./` keeps it a path.
        if _SCHEME.match(rel):
            rel = "./" + rel
        return angle_target(rel) + suffix
    return urllib.parse.quote(rel, safe="/") + suffix


def plan_link_rewrites(texts: dict[str, str], paths: Iterable[str],
                       moves: Iterable[tuple[str, str]],
                       deleted: Iterable[str]) -> LinkRewrites:
    base = Tree(paths)
    moved = dict(moves)
    gone = set(deleted)
    after = Tree((base.paths - moved.keys() - gone) | set(moved.values()))
    counts = {"inbound": 0, "outbound": 0}
    named: dict[str, set[str]] = {"inbound": set(), "outbound": set()}
    unrewritable: set[tuple[str, str]] = set()
    broken = 0
    files: dict[str, RewrittenFile] = {}
    for source, text in sorted(texts.items()):
        container_after = moved.get(source, source)
        direction = "outbound" if source in moved else "inbound"
        replacements: list[tuple[Link, str]] = []
        for link in links(text):
            if not is_relative(link.target):
                continue
            resolved = resolve(source, link.target, base)
            if resolved is None:
                broken += 1
                continue
            successor = _successor(resolved, base, after, moved, gone)
            if successor is None:
                unrewritable.add((source, link.target))
                continue
            new = _emitted(link, resolved, successor, container_after)
            if new is not None:
                replacements.append((link, new))
        if not replacements:
            continue
        rewritten = text
        for link, new in reversed(replacements):
            rewritten = rewritten[:link.start] + new + rewritten[link.end:]
        files[container_after] = RewrittenFile(source, text, rewritten)
        counts[direction] += len(replacements)
        named[direction].add(container_after)
    summary = {
        "inbound": {"links": counts["inbound"],
                    "files": sorted(named["inbound"])},
        "outbound": {"links": counts["outbound"],
                     "files": sorted(named["outbound"])},
        "unrewritable": [{"path": path, "target": target}
                         for path, target in sorted(unrewritable)],
        "already_broken": broken}
    return LinkRewrites(summary, files)


# --------------------------------------------------------------------------
# Reading a tree's Markdown through git
# --------------------------------------------------------------------------


def index_records(root: Path) -> list[tuple[str, str, str]]:
    """`(path, mode, object id)` for every stage-0 index entry, sorted."""
    records = []
    for record in split_nul(git_or_fail(root, "ls-files", "-s", "-z")):
        head, _, path = record.partition("\t")
        fields = head.split()
        if len(fields) != 3 or not path:
            raise refuse("adopt_failure", "adopt.git.unparseable_index", "",
                         "a tracked index record could not be read")
        if fields[2] == "0":
            records.append((path, fields[0], fields[1]))
    return sorted(records)


def _blobs(root: Path, object_ids: list[str]) -> dict[str, bytes]:
    code, out = run_git(root, "cat-file", "--batch",
                        input="".join(f"{oid}\n"
                                      for oid in object_ids).encode())
    failure = refuse("adopt_failure", "adopt.git.failed", "",
                     "a git inspection command did not succeed")
    if code != 0:
        raise failure
    blobs: dict[str, bytes] = {}
    position = 0
    for oid in object_ids:
        end = out.find(b"\n", position)
        if end < 0:
            raise failure
        header = out[position:end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise failure
        try:
            size = int(header[2])
        except ValueError:
            raise failure from None
        start = end + 1
        if len(out) < start + size + 1 or out[start + size:start + size + 1] \
                != b"\n":
            raise failure
        blobs[oid] = out[start:start + size]
        position = start + size + 1
    return blobs


def markdown_texts(root: Path,
                   records: list[tuple[str, str, str]]) -> dict[str, str]:
    """Each scanned record's blob as strict UTF-8; undecodable ones omitted."""
    wanted = [(path, oid) for path, mode, oid in records
              if scanned(path, mode)]
    if not wanted:
        return {}
    blobs = _blobs(root, sorted({oid for _, oid in wanted}))
    texts = {}
    for path, oid in wanted:
        try:
            texts[path] = blobs[oid].decode("utf-8")
        except UnicodeDecodeError:
            continue
    return texts


def derive_link_rewrites(root: Path, revision: str,
                         moves: Iterable[tuple[str, str]],
                         deleted: Iterable[str],
                         excluded: Iterable[str]) -> LinkRewrites:
    """The link rewrites `moves` and `deleted` cause over `revision`'s tree."""
    records = tree_records(root, revision)
    texts = markdown_texts(root, records)
    for path in set(excluded):
        texts.pop(path, None)
    return plan_link_rewrites(texts, [path for path, _, _ in records],
                              moves, deleted)
