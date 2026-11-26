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

A step may also name a `base`: one of its `in` paths, whose value is a branch of the `origin` remote. The step
then holds for the checkout's `Mark` (its head and the merge base of that head with `refs/remotes/origin/<branch>`,
recorded as `base`, `{ref, sha}`): the base moving while the step ran ends it as the head does, `checkout_bases`
reads the current merge base of every checkout a stored result names a base for (a continue judges that result
stale when it differs or was never recorded), and a result is reused only at the same merge base. A merge base
that cannot be read leaves the step unreused and its result without `base`.

Reuse: such a step never mutates, so its result is a function of the command, its arguments and the checkout's
mark. Every `result_stored` of the step carries its `reuse_key` (the command, subcommand and arguments as
compact sorted JSON, never the step id). Before the command starts the shell reads the checkout's mark and
`settle`s it: `reusable` searches the delivery's runs (`engine_ledger.delivery_runs` of the root run) for a
stored result with the same `reuse_key`, the same `head` and `base` and the outcome `ok`, the last one in walk
order winning, and a `LedgerError`, `OSError` or `ValueError` anywhere in the search is a miss. A hit is accepted
only when the mark read again after the search is the same one; otherwise the visit ends as a head that moved
while the command ran. An accepted hit stores its document again, naming where it came from in `reused_from`, and
no process starts.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Mapping, NamedTuple, Sequence

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
            for member in ("head", "repository", "base"):
                if member in heads[(event["step"], event["visit"])]:
                    outcome[member] = heads[(event["step"], event["visit"])][member]
            events.append(outcome)
    return events


def _commit(root: str, *words: str) -> str | None:
    """The full commit id the Git read `words` prints in `root`, or None when it cannot be read.

    The repository is the one `root` is in: a variable that selects another is not passed on.
    """
    environ = {key: value for key, value in os.environ.items() if key not in REPOSITORY_ENV}
    try:
        done = subprocess.run(["git", *words], cwd=root, env=environ,
                              stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    found = done.stdout.strip()
    return found if done.returncode == 0 and engine_ledger.HEAD_RE.fullmatch(found) else None


def read_head(root: str) -> str | None:
    """The full commit id `HEAD` names in `root`, or None when it cannot be read."""
    return _commit(root, "rev-parse", "--verify", "--quiet", "HEAD")


class Mark(NamedTuple):
    """What a checkout's result holds for: its head and, for a step naming a `base`, that merge base."""

    head: str | None
    base: dict | None


def read_mark(root: str, ref: str | None = None) -> Mark:
    """The head of `root` and, when `ref` is given and shares history with it, the merge base."""
    head = read_head(root)
    sha = None if ref is None or head is None else _commit(root, "merge-base", ref, "HEAD")
    return Mark(head, None if sha is None else {"ref": ref, "sha": sha})


def base_of(step: Mapping, args: Sequence[tuple[str, object]]) -> str | None:
    """The `origin` remote-tracking ref of the step's `base` branch, None when it names none.

    Raises `CheckoutRefused` when the path's value is not a non-empty string that is no option.
    """
    path = step.get("base")
    if path is None:
        return None
    value = dict(args).get(path)
    if not (isinstance(value, str) and value and not value.startswith("-")):
        raise CheckoutRefused(f"base {path} is not a branch name: {value!r}")
    return f"refs/remotes/origin/{value}"


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


def checkout_bases(ledger: list[dict]) -> dict[str, str | None]:
    """The current merge base of every checkout the ledger's stored results name a base for."""
    return {event["repository"]: _commit(event["repository"], "merge-base", event["base"]["ref"], "HEAD")
            for event in ledger if event["event"] == "result_stored" and "base" in event}


def reuse_key(action) -> str:
    """The command, subcommand and arguments of a `RunCommand`, as compact sorted JSON."""
    return json.dumps([action.command, action.subcommand, [[path, value] for path, value in action.args]],
                      sort_keys=True, separators=(",", ":"))


class Hit(NamedTuple):
    """A stored result found for reuse: the run id, step and visit that stored it, and its document."""

    run: str
    step: str
    visit: int
    result: dict


class Settled(NamedTuple):
    """`settle`'s answer: the checkout's mark (no head when unreadable), the hit, and whether the mark moved."""

    mark: Mark
    hit: Hit | None
    moved: bool


def reusable(root: Path, key: str, mark: Mark) -> Hit | None:
    """The last stored `ok` result of `key` at `mark` in the delivery's runs, None when there is none."""
    try:
        found = None
        for run_dir in engine_ledger.delivery_runs(root):
            for event in engine_ledger.replay(run_dir / "events.jsonl"):
                if (event["event"] == "result_stored" and event.get("reuse_key") == key
                        and event.get("head") == mark.head and event.get("base") == mark.base
                        and event.get("outcome") == "ok"):
                    found = (run_dir, event)
        if found is None:
            return None
        run_dir, event = found
        return Hit(run_dir.name, event["step"], event["visit"], _load(run_dir / event["result"]))
    except (engine_ledger.LedgerError, OSError, ValueError):
        return None


def settle(root: Path, key: str, checkout: str, ref: str | None = None) -> Settled:
    """The checkout's mark and the stored result reusable at it, the mark read again once the search is done."""
    mark = read_mark(checkout, ref)
    if mark.head is None or (ref is not None and mark.base is None):
        return Settled(mark, None, False)
    hit = reusable(root, key, mark)
    if hit is not None and read_mark(checkout, ref) != mark:
        return Settled(mark, None, True)
    return Settled(mark, hit, False)
