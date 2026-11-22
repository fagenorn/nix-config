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
over a `Snapshot` (the revision and every tracked text file's line count); it
may emit only its own rule id, else the comparison raises `ValueError`.

The comparison, per enforcer in the order given. A count rule (the default)
compares the project total: it rises when the branch has more violations than
the base, so a rename or a move that keeps the count passes and a rule at zero
rises from zero. `Rise.new` names the violations the branch added, the
multiset difference of `(path, line)` keys, branch minus base, in branch order.
A per-file rule (`per_file=True`) compares each branch violation with the
violation of the same file on the base, matched through git renames
(`diff-tree -M`): it rises for a violation whose matched base path has no
violation of that rule, or one with a smaller `line`. A move git does not pair
is a new file.

Suppressions (#1459). A suppression marker (`agent_tools.delivery.rule_ids`) is read
from every text file at a revision into `Snapshot.suppressions`, in path then line
order. `counted(enforcer, snapshot)` is the count both sides of the comparison use,
returned as `(findings left, marker violations)`: a finding is dropped when a reasoned
marker naming the enforcer's rule sits on its `(path, line)`, and each marker that is
bare (no reason) and names the rule, or names no rule and sits on one of the rule's
findings, is one violation of the rule at the marker's own line. A marker naming
another rule, or none and off a finding, counts nothing. The count of a rule is the sum
of both lists, so deleting a reason, or adding a bare marker, rises. A per-file rule
compares the findings left as before and the marker violations as a count, so a bare
marker on a held finding rises though the finding itself held.

`Verdict.suppressions` lists each reasoned suppression the branch adds, by
`added_suppressions`: those of the branch not matched, as a multiset of `(rule, path,
reason)` with the path followed through git renames, by a reasoned suppression of the
base. It lists and never fails: a listed suppression raises no count. `Suppression.text()`
is `<rule> <path>:<line> <reason>` on one line, path and reason escaped as below.

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
from pathlib import Path
from typing import NamedTuple

from agent_tools.delivery import rule_ids

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

    def text(self) -> str:
        return f"{self.rule} {escape_path(self.path)}:{self.line}"


class Suppression(NamedTuple):
    rule: str | None
    path: str
    line: int
    reason: str

    @property
    def reasoned(self) -> bool:
        return rule_ids.is_reasoned(self.rule, self.reason)

    def text(self) -> str:
        return f"{self.rule} {escape_path(self.path)}:{self.line} {escape_path(self.reason)}"


class Snapshot(NamedTuple):
    revision: str
    line_counts: Mapping[str, int]
    suppressions: tuple[Suppression, ...] = ()


@dataclass(frozen=True)
class Enforcer:
    rule: str
    find: Callable[[Snapshot], list[Violation]]
    per_file: bool = False


class Rise(NamedTuple):
    rule: str
    base_count: int
    branch_count: int
    new: tuple[Violation, ...]


class Verdict(NamedTuple):
    merge_base: str
    head: str
    rises: tuple[Rise, ...]
    suppressions: tuple[Suppression, ...] = ()


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
    """Every text file's line count at a revision.

    Lines are counted as `git grep -c` counts them: the newline-terminated lines
    plus an unterminated last line, empty files not listed. A file with a NUL in
    its first `BINARY_PROBE_BYTES` bytes is binary and not listed; a submodule is
    no file. A blob that cannot be read is no snapshot.
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
    found: list[Suppression] = []
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
        if content and b"\0" not in content[:BINARY_PROBE_BYTES]:
            counts[path] = content.count(b"\n") + (0 if content.endswith(b"\n") else 1)
            if rule_ids.SUPPRESS.encode() in content:
                found.extend(
                    Suppression(m.rule, path, m.line, m.reason)
                    for m in rule_ids.markers(content.decode("utf-8", errors="replace")))
    found.sort(key=lambda s: (s.path, s.line))
    return Snapshot(revision, counts, tuple(found))


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


def counted(enforcer: Enforcer, snapshot: Snapshot) -> tuple[list[Violation], list[Violation]]:
    """The findings left after reasoned suppressions, and the violations of bare markers."""
    found = _found(enforcer, snapshot)
    suppressed = {(s.path, s.line) for s in snapshot.suppressions
                  if s.reasoned and s.rule == enforcer.rule}
    on_finding = {(v.path, v.line) for v in found}
    kept = [v for v in found if (v.path, v.line) not in suppressed]
    marked = [Violation(enforcer.rule, s.path, s.line) for s in snapshot.suppressions
              if not s.reasoned and (s.rule == enforcer.rule
                                     or (s.rule is None and (s.path, s.line) in on_finding))]
    return kept, marked


def _added(after: Sequence[Violation], before: Sequence[Violation]) -> list[Violation]:
    """The multiset difference of `(path, line)` keys, `after` minus `before`, in `after` order."""
    remaining = Counter((v.path, v.line) for v in before)
    new = []
    for violation in after:
        key = (violation.path, violation.line)
        if remaining[key] > 0:
            remaining[key] -= 1
        else:
            new.append(violation)
    return new


def compare(base: Snapshot, branch: Snapshot, renamed: Mapping[str, str],
            enforcers: Sequence[Enforcer]) -> tuple[Rise, ...]:
    """The rules whose branch violations rose over the base; pure."""
    rises = []
    for enforcer in enforcers:
        kept_before, marked_before = counted(enforcer, base)
        kept_after, marked_after = counted(enforcer, branch)
        before = len(kept_before) + len(marked_before)
        after = len(kept_after) + len(marked_after)
        new: list[Violation] = []
        if enforcer.per_file:
            base_lines = {v.path: v.line for v in kept_before}
            new = [v for v in kept_after
                   if base_lines.get(renamed.get(v.path, v.path), 0) < v.line]
            if len(marked_after) > len(marked_before):
                new += _added(marked_after, marked_before)
        elif after > before:
            new = _added(kept_after + marked_after, kept_before + marked_before)
        if new:
            rises.append(Rise(enforcer.rule, before, after, tuple(new)))
    return tuple(rises)


def added_suppressions(base: Snapshot, branch: Snapshot,
                       renamed: Mapping[str, str]) -> tuple[Suppression, ...]:
    """The reasoned suppressions the branch adds, those the base does not hold; pure."""
    held = Counter((s.rule, s.path, s.reason) for s in base.suppressions if s.reasoned)
    added = []
    for suppression in branch.suppressions:
        if not suppression.reasoned:
            continue
        key = (suppression.rule, renamed.get(suppression.path, suppression.path),
               suppression.reason)
        if held[key] > 0:
            held[key] -= 1
        else:
            added.append(suppression)
    return tuple(added)


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
    return Verdict(
        base, head, compare(base_snapshot, branch_snapshot, renamed, enforcers),
        added_suppressions(base_snapshot, branch_snapshot, renamed))
