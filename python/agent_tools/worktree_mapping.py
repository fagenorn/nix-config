"""The #130 checklist C7 rule as code: every retained worktree has a strict-path ledger mapping.

A linked worktree is classified by the workflow ledgers (`.superpowers/workflows/*/state.json`)
that name its path as a whole JSON string, using the verdicts of a `workflow-state migrate`
dry run: `current` when any naming ledger is current (or migrated), else `migrate` when any is
migratable, else `refused-only` when ledgers name it but all are refused, else `unmapped`.
Only the verify runner's own temporary worktrees are left out (issue 585). Everything here is
read-only: `git --no-optional-locks`, no writes to a root.
"""
from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_tools import verify_exec

GIT_TIMEOUT = 120
CLASSES = ("current", "migrate", "refused-only", "unmapped")
_CURRENT = {"current", "migrated"}


class MappingError(Exception):
    """A git or ledger read failed; the message names the root and the cause."""


@dataclass(frozen=True)
class Worktree:
    path: str
    head: str | None
    branch: str | None
    locked: bool
    prunable: bool


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


def _encode(text: str) -> bytes:
    return text.encode("utf-8", "surrogateescape")


def list_worktrees(root: Path) -> list[Worktree]:
    """The linked worktrees of `root` (the main checkout, listed first, is skipped)."""
    try:
        done = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(root), "worktree", "list", "--porcelain", "-z"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise MappingError(f"{root}: git worktree list failed: {error}") from None
    out = _decode(done.stdout)
    if done.returncode != 0:
        detail = _decode(done.stderr).strip() or f"exit {done.returncode}"
        raise MappingError(f"{root}: git worktree list failed: {detail}")
    entries: list[Worktree] = []
    # `-z`: fields end in NUL and a worktree's block ends in an empty field, so a path is never
    # quoted by `core.quotePath` and may hold any byte but NUL.
    for block in out.split("\0\0"):
        path = head = branch = None
        locked = prunable = False
        for line in block.split("\0"):
            key, _, value = line.partition(" ")
            if key == "worktree":
                path = value
            elif key == "HEAD":
                # An unborn branch prints the all-zero id: the worktree has no HEAD commit.
                head = None if set(value) == {"0"} else value
            elif key == "branch":
                branch = value
            elif key == "locked":
                locked = True
            elif key == "prunable":
                prunable = True
        if path is not None:
            entries.append(Worktree(path, head, branch, locked, prunable))
    if not entries:
        raise MappingError(f"{root}: git worktree list printed no worktree")
    return entries[1:]


def is_runner_workspace(wt: Worktree) -> bool:
    """A detached worktree shaped like `verify_exec.workspace`'s, judged by its real path."""
    if wt.branch is not None:
        return False
    path = os.path.realpath(wt.path) if os.path.isdir(wt.path) else wt.path
    return verify_exec.is_workspace(path)


def _ledger_bytes(root: Path) -> dict[str, bytes]:
    base = root / ".superpowers" / "workflows"
    if not base.is_dir():
        return {}
    found: dict[str, bytes] = {}
    for state in sorted(base.glob("*/state.json")):
        try:
            found[state.parent.name] = state.read_bytes()
        except OSError as error:
            raise MappingError(f"{root}: cannot read {state}: {error}") from None
    return found


def _strings(node: object) -> Iterator[str]:
    """Every JSON string of `node`, object keys included."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)
    elif isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _strings(value)


def _names_path(data: bytes, names: set[str]) -> bool:
    """True when `data` holds one of `names` as a whole JSON string, however it is escaped."""
    needles = [b'"' + _encode(n) + b'"' for n in names]
    if any(n in data for n in needles):
        return True
    try:
        doc = json.loads(_decode(data))
    except ValueError:
        return False
    return any(text in names for text in _strings(doc))


def _matches(ledgers: Mapping[str, bytes], path: str) -> list[str]:
    names = {path}
    if os.path.isdir(path):
        names.add(os.path.realpath(path))
    return sorted(name for name, data in ledgers.items() if _names_path(data, names))


def ledger_matches(root: Path, path: str) -> list[str]:
    """Ledger names under `root` whose state names `path` (or its realpath) as a whole string."""
    return _matches(_ledger_bytes(root), path)


def classify(names: list[str], verdicts: Mapping[str, str]) -> str:
    """The C7 class of a path named by ledgers `names`; a ledger absent from `verdicts` is refused."""
    if not names:
        return "unmapped"
    seen = {verdicts.get(name, "refused") for name in names}
    if seen & _CURRENT:
        return "current"
    if "migrate" in seen:
        return "migrate"
    return "refused-only"


def verdicts_of(migrate_report: Mapping) -> dict[str, str]:
    ledgers = migrate_report.get("ledgers") if isinstance(migrate_report, Mapping) else None
    if not isinstance(ledgers, list):
        raise MappingError("migrate report has no ledgers list")
    out: dict[str, str] = {}
    for entry in ledgers:
        if (not isinstance(entry, Mapping) or not isinstance(entry.get("ledger"), str)
                or not isinstance(entry.get("verdict"), str)):
            raise MappingError("migrate report ledger entry has no ledger and verdict")
        out[entry["ledger"]] = entry["verdict"]
    return out


def classify_root(root: Path, migrate_report: Mapping) -> dict:
    verdicts = verdicts_of(migrate_report)
    worktrees = list_worktrees(root)
    ledgers = _ledger_bytes(root)
    excluded: list[str] = []
    counts = {name: 0 for name in CLASSES}
    paths: list[dict] = []
    for wt in worktrees:
        if is_runner_workspace(wt):
            excluded.append(wt.path)
            continue
        names = _matches(ledgers, wt.path)
        kind = classify(names, verdicts)
        counts[kind] += 1
        paths.append({"class": kind, "path": wt.path, "ledgers": names})
    if counts["unmapped"] or counts["refused-only"]:
        verdict = "red"
    elif counts["migrate"]:
        verdict = "human-pending"
    else:
        verdict = "green"
    return {"root": str(root), "worktrees": len(paths), "excluded": excluded,
            "counts": counts, "verdict": verdict, "paths": paths}
