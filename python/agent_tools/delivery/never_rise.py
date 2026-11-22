"""The never-rise comparison: does a branch hold more violations than its base?

This module is the comparison core of the never-rise check (#1455). It judges
the committed tree of the branch against the committed tree of its merge base
with the integration branch, once per enforcer, and reports each rule that rose.

Two revisions. The head is `HEAD`; the base is `git merge-base HEAD
refs/remotes/origin/<integration branch>`, never the integration tip, so work
that landed on the integration branch after the branch forked is not charged to
the branch. Only commits are read: an uncommitted or untracked file is never
judged, and a missing remote-tracking ref, a root that is no repository or any
failed git read is no verdict (`None`), never a pass.

Both sides are judged by the enforcers passed in, so a rule introduced by the
branch itself is measured on the base by the same code and passes while its
violations only persist. Each enforcer is a `rule` id and a `find` function
over a `Snapshot` (the revision, every tracked text file's line count and every
committed blob's bytes); it may emit only its own rule id, else the comparison
raises `ValueError`.

The comparison, per enforcer in the order given. A count rule (the default)
compares the project total: it rises when the branch has more violations than
the base, so a rename or a move that keeps the count passes and a rule at zero
rises from zero. `Rise.new` names the violations the branch added, the
multiset difference of `(path, line)` keys, branch minus base, in branch order.
A per-file rule (`per_file=True`) compares each branch violation with the
violation of the same file on the base, matched through git renames
(`diff-tree -M`): it rises for a violation whose matched base path has no
violation of that rule, or one whose measure is smaller: a violation's `measure`
when it carries one, else its `line`. A rename git pairs carries the source's
violation to the target unless the enforcer has a `carries` function and it
refuses the pair's bytes (old, new); a refused target is judged as if the base
held no violation for it. With `exempts_carried`, a rename the enforcer carries
never rises, whatever its measure: a move that only adds bytes the rule does not
judge (a header, a pointer line) cannot turn the rule red. A move git does not pair is a new file.

A `Verdict` also lists the blob paths the head adds over the base (`added`, a
rename target included), the renames git pairs (`renamed`, new path to old
path) and each pair's committed bytes (`rename_blobs`, base bytes of the source
and head bytes of the target).

Output line, one per violation: `Violation.text()` is the rule id, one space,
the repository-relative path escaped, a colon and the 1-based line. The escape
doubles a backslash, writes a newline, carriage return and tab as `\\n`, `\\r`
and `\\t`, any other C0 character and DEL as `\\xNN`, and the Unicode line
separators U+0085, U+2028 and U+2029 as `\\uNNNN`, so a path never splits one
violation across two physical lines.

Every git child is read-only, never fetches and is bounded by the caller's
`timeout`: it drops the variables that select a repository other than the one
under `root` (`SELECTION_VARIABLES`), sets `GIT_NO_LAZY_FETCH=1` so a partial
clone with a missing blob is no verdict instead of a network fetch, passes
`--no-color` so forced colour changes no path, and runs only `rev-parse`,
`merge-base`, `ls-tree`, `cat-file` and `diff-tree`. An argument git cannot be
given (a NUL in a branch name) is a failed read, never an error.

A file is text or binary by its committed bytes alone: a NUL among its first
8,000 bytes makes it binary, as git decides it for `grep -I`, whatever a
`diff` or `binary` attribute says, so no attribute hides a file from an
enforcer.
"""

import os
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from pathlib import Path
from typing import NamedTuple

REMOTE = "origin"
SELECTION_VARIABLES = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR")
TEXT_ESCAPES = {"\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t"}
UNICODE_LINE_SEPARATORS = ("\x85", " ", " ")
HEX = frozenset("0123456789abcdef")


def escape_path(path: str) -> str:
    """Escape a path so one violation stays on one physical line."""
    pieces = []
    for character in path:
        escape = TEXT_ESCAPES.get(character)
        if escape is not None:
            pieces.append(escape)
        elif character < " " or character == "\x7f":
            pieces.append(f"\\x{ord(character):02x}")
        elif character in UNICODE_LINE_SEPARATORS:
            pieces.append(f"\\u{ord(character):04x}")
        else:
            pieces.append(character)
    return "".join(pieces)


class Violation(NamedTuple):
    rule: str
    path: str
    line: int
    measure: int | None = None

    def magnitude(self) -> int:
        return self.line if self.measure is None else self.measure

    def text(self) -> str:
        return f"{self.rule} {escape_path(self.path)}:{self.line}"


class Snapshot(NamedTuple):
    revision: str
    line_counts: Mapping[str, int]
    blobs: Mapping[str, bytes] = MappingProxyType({})


@dataclass(frozen=True)
class Enforcer:
    rule: str
    find: Callable[[Snapshot], list[Violation]]
    per_file: bool = False
    carries: Callable[[bytes, bytes], bool] | None = None
    exempts_carried: bool = False


class Rise(NamedTuple):
    rule: str
    base_count: int
    branch_count: int
    new: tuple[Violation, ...]


class Verdict(NamedTuple):
    merge_base: str
    head: str
    rises: tuple[Rise, ...]
    added: tuple[str, ...] = ()
    renamed: Mapping[str, str] = MappingProxyType({})
    rename_blobs: Mapping[str, tuple[bytes, bytes]] = MappingProxyType({})


def _git(root: Path, args: Sequence[str], timeout: float | None,
         stdin: bytes | None = None) -> bytes | None:
    """Run one read-only git child; its stdout, or None when it did not succeed."""
    env = {k: v for k, v in os.environ.items() if k not in SELECTION_VARIABLES}
    env["GIT_NO_LAZY_FETCH"] = "1"
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, timeout=timeout, env=env,
            input=stdin)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def _revision(output: bytes | None) -> str | None:
    text = output.decode("ascii", errors="replace").strip() if output is not None else ""
    return text if len(text) == 40 and set(text) <= HEX else None


def revisions(root: Path, integration_branch: str, timeout: float | None) -> tuple[str, str] | None:
    """The merge base and the head, both 40-hex, or None."""
    head = resolve_commit(root, "HEAD", timeout)
    if head is None:
        return None
    base = _revision(_git(
        root, ["merge-base", head, f"refs/remotes/{REMOTE}/{integration_branch}"], timeout))
    return (base, head) if base is not None else None


def resolve_commit(root: Path, revision: str, timeout: float | None) -> str | None:
    """The 40-hex commit a revision names, or None; reads no object from a remote."""
    return _revision(_git(root, ["rev-parse", "--verify", f"{revision}^{{commit}}"], timeout))


def in_subdirectory(root: Path, timeout: float | None) -> bool:
    """True when `root` is a directory below the top level of its repository."""
    prefix = _git(root, ["rev-parse", "--show-prefix"], timeout)
    return prefix is not None and prefix.strip() != b""


BINARY_PROBE_BYTES = 8000


def read_snapshot(root: Path, revision: str, timeout: float | None) -> Snapshot | None:
    """Every text file's line count and every blob's bytes at a revision.

    Lines are counted as `git grep -c` counts them: the newline-terminated lines
    plus an unterminated last line, empty files not listed. A file with a NUL in
    its first `BINARY_PROBE_BYTES` bytes is binary and not counted; `blobs` holds
    every blob's bytes, empty and binary ones included; a submodule is no file. A blob that cannot be read is no snapshot.
    """
    listing = _git(root, ["ls-tree", "-r", "-z", "--full-tree", revision], timeout)
    if listing is None:
        return None
    paths: dict[str, str] = {}
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        meta, _, name = entry.partition(b"\t")
        _, kind, oid = meta.decode("ascii").split(" ")
        if kind == "blob":
            paths[os.fsdecode(name)] = oid
    if not paths:
        return Snapshot(revision, {})
    out = _git(root, ["cat-file", "--batch"], timeout,
               stdin="".join(f"{oid}\n" for oid in paths.values()).encode("ascii"))
    if out is None:
        return None
    counts: dict[str, int] = {}
    blobs: dict[str, bytes] = {}
    position = 0
    for path in paths:
        end = out.find(b"\n", position)
        header = out[position:end].split(b" ") if end >= 0 else []
        if len(header) != 3 or header[1] != b"blob":
            return None
        start = end + 1
        stop = start + int(header[2])
        content = out[start:stop]
        position = stop + 1
        blobs[path] = content
        if content and b"\0" not in content[:BINARY_PROBE_BYTES]:
            counts[path] = content.count(b"\n") + (0 if content.endswith(b"\n") else 1)
    return Snapshot(revision, counts, blobs)


def renames(root: Path, base: str, head: str, timeout: float | None) -> dict[str, str] | None:
    """Each path git pairs as a rename from base to head, new path to old path."""
    out = _git(root, ["diff-tree", "--no-color", "-r", "-z", "-M", "--diff-filter=R",
                      "--name-status", base, head], timeout)
    if out is None:
        return None
    tokens = [os.fsdecode(token) for token in out.split(b"\0") if token]
    return {tokens[i + 2]: tokens[i + 1] for i in range(0, len(tokens) - 2, 3)}


def _found(enforcer: Enforcer, snapshot: Snapshot) -> list[Violation]:
    found = enforcer.find(snapshot)
    for violation in found:
        if violation.rule != enforcer.rule:
            raise ValueError(
                f"enforcer {enforcer.rule} emitted a violation of rule {violation.rule}")
    return found


def _is_carried(enforcer: Enforcer, base: Snapshot, branch: Snapshot,
                renamed: Mapping[str, str], violation: Violation) -> bool:
    source = renamed.get(violation.path)
    return source is not None and (enforcer.carries is None or enforcer.carries(
        base.blobs.get(source, b""), branch.blobs.get(violation.path, b"")))


def _base_measure(enforcer: Enforcer, base: Snapshot, branch: Snapshot,
                  renamed: Mapping[str, str], base_measure: Mapping[str, int],
                  violation: Violation) -> int:
    source = renamed.get(violation.path)
    if source is None:
        return base_measure.get(violation.path, 0)
    if enforcer.carries is not None and not enforcer.carries(
            base.blobs.get(source, b""), branch.blobs.get(violation.path, b"")):
        return 0
    return base_measure.get(source, 0)


def compare(base: Snapshot, branch: Snapshot, renamed: Mapping[str, str],
            enforcers: Sequence[Enforcer]) -> tuple[Rise, ...]:
    """The rules whose branch violations rose over the base; pure."""
    rises = []
    for enforcer in enforcers:
        before = _found(enforcer, base)
        after = _found(enforcer, branch)
        if enforcer.per_file:
            base_measure = {v.path: v.magnitude() for v in before}
            new = [v for v in after
                   if not (enforcer.exempts_carried
                           and _is_carried(enforcer, base, branch, renamed, v))
                   and _base_measure(enforcer, base, branch, renamed, base_measure, v)
                   < v.magnitude()]
        elif len(after) > len(before):
            remaining = Counter((v.path, v.line) for v in before)
            new = []
            for violation in after:
                key = (violation.path, violation.line)
                if remaining[key] > 0:
                    remaining[key] -= 1
                else:
                    new.append(violation)
        else:
            new = []
        if new:
            rises.append(Rise(enforcer.rule, len(before), len(after), tuple(new)))
    return tuple(rises)


def judge(root: Path, integration_branch: str, enforcers: Sequence[Enforcer],
          timeout: float | None) -> Verdict | None:
    """Compare the head with the merge base; None when any git read fails."""
    pair = revisions(root, integration_branch, timeout)
    if pair is None:
        return None
    base, head = pair
    base_snapshot = read_snapshot(root, base, timeout)
    branch_snapshot = read_snapshot(root, head, timeout)
    renamed = renames(root, base, head, timeout)
    if base_snapshot is None or branch_snapshot is None or renamed is None:
        return None
    added = tuple(sorted(set(branch_snapshot.blobs) - set(base_snapshot.blobs)))
    rename_blobs = {new: (base_snapshot.blobs.get(old, b""), branch_snapshot.blobs.get(new, b""))
                    for new, old in renamed.items()}
    return Verdict(base, head,
                   compare(base_snapshot, branch_snapshot, renamed, enforcers),
                   added, renamed, rename_blobs)
