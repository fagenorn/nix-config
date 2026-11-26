"""The repository head a head-held result is read against.

A command step that holds `head` records the head of the repository it ran in, only when the head is the
same before and after the step's process; `engine_core.reentry` then judges the stored result by comparing
that head with the repository's current one. `read_head` reads a head, `core_events` projects a run's ledger
events into the core's (an outcome event carrying the stored result's `head` and `repository`).

A command step may name a `repository`: one of its `in` paths, whose value is the checkout the step works in.
`checkout_of` returns that checkout, or raises `CheckoutRefused` when the value is not a string that is an
absolute path (the step is then refused and its command never starts). The step reads and records that
checkout's head instead of the project's, and its stored result names the checkout as `repository`;
`checkout_heads` reads the current head of every checkout a run's stored results name, so a continue judges
such a result by its own checkout's head. A checkout whose head moved while the step ran ends the step
`out-of-bounds` and records no head (the shell's `_head_moved`).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.delivery import engine_ledger

REPOSITORY_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                  "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE",
                  "GIT_PREFIX", "GIT_IMPLICIT_WORK_TREE")


class CheckoutRefused(Exception):
    """A step's `repository` value is not an absolute path; `str(error)` is the reason."""


def _load(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=reject_duplicate_keys,
                          parse_constant=reject_nonfinite_literal)
    if not isinstance(document, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return document


def core_events(run_dir: Path, ledger: list[dict],
                computed: frozenset[str] = frozenset()) -> list[dict]:
    """The core's events for a run's ledger events; every other ledger event is skipped.

    An `outcome_graded` of a step in `computed` (a group, graded by the core) is skipped.
    """
    heads = {(e["step"], e["visit"]): e for e in ledger if e["event"] == "result_stored"}
    stored = {key: e["result"] for key, e in heads.items()}
    events: list[dict] = []
    for event in ledger:
        if event["event"] == "step_entered":
            events.append({"type": "entered", "step": event["step"]})
        elif event["event"] == "run_continued":
            events.append({"type": "continued", "step": event.get("step"),
                           "visit": event.get("visit")})
        elif event["event"] == "outcome_graded" and event["step"] not in computed:
            relative = stored[(event["step"], event["visit"])]
            outcome = {"type": "outcome", "step": event["step"],
                       "outcome": event["outcome"], "result": _load(run_dir / relative)}
            for member in ("head", "repository"):
                if member in heads[(event["step"], event["visit"])]:
                    outcome[member] = heads[(event["step"], event["visit"])][member]
            events.append(outcome)
    return events


def read_head(root: str) -> str | None:
    """The full commit id `HEAD` names in `root`, or None when it cannot be read.

    The repository is the one `root` is in: a variable that selects another is not passed on.
    """
    environ = {key: value for key, value in os.environ.items() if key not in REPOSITORY_ENV}
    try:
        done = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=root, env=environ,
                              stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    head = done.stdout.strip()
    return head if done.returncode == 0 and engine_ledger.HEAD_RE.fullmatch(head) else None


def checkout_of(step: Mapping, args: Sequence[tuple[str, object]]) -> str | None:
    """The checkout the step's `repository` path names, None when it names none.

    Raises `CheckoutRefused` when the path's value is not a string that is an absolute path.
    """
    path = step.get("repository")
    if path is None:
        return None
    value = dict(args).get(path)
    if not (isinstance(value, str) and os.path.isabs(value)):
        raise CheckoutRefused(f"repository {path} is not an absolute path: {value!r}")
    return value


def checkout_heads(ledger: list[dict]) -> dict[str, str | None]:
    """The current head of every checkout the ledger's stored results name."""
    return {event["repository"]: read_head(event["repository"]) for event in ledger
            if event["event"] == "result_stored" and "repository" in event}
