"""The #130 checklist C7 rule as code: every retained worktree has a strict-path ledger mapping.

A linked worktree is classified by the workflow ledgers (`.superpowers/workflows/*/state.json`)
that name its path as a whole JSON string, using the verdicts of a `workflow-state migrate`
dry run: `current` when any naming ledger is current (or migrated), else `migrate` when any is
migratable, else `refused-only` when ledgers name it but all are refused, else `unmapped`.
Only the verify runner's own temporary worktrees are left out (issue 585). Everything here is
read-only: `git --no-optional-locks`, no writes to a root.
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
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
            ["git", "--no-optional-locks", "-C", str(root), "worktree", "list", "--porcelain"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise MappingError(f"{root}: git worktree list failed: {error}") from None
    out = _decode(done.stdout)
    if done.returncode != 0:
        detail = _decode(done.stderr).strip() or f"exit {done.returncode}"
        raise MappingError(f"{root}: git worktree list failed: {detail}")
    entries: list[Worktree] = []
    for block in out.split("\n\n"):
        path = head = branch = None
        locked = prunable = False
        for line in block.split("\n"):
            key, _, value = line.partition(" ")
            if key == "worktree":
                path = value
            elif key == "HEAD":
                head = value
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


def _matches(ledgers: Mapping[str, bytes], path: str) -> list[str]:
    needles = [b'"' + _encode(path) + b'"']
    if os.path.isdir(path):
        needles.append(b'"' + _encode(os.path.realpath(path)) + b'"')
    return sorted({name for name, data in ledgers.items() if any(n in data for n in needles)})


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
