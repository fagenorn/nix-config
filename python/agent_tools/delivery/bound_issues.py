"""The filing pass: one tracker issue per out-of-bounds engine step and per over-wide role bound.

`file_pass(tracker, history, seen, lock, now)` reads the engine history (`history.jsonl`, one JSON
object per line) and files, for what the last `WINDOW_DAYS` days of it show, an issue for each step that
ended `out-of-bounds` and for each role whose recorded bounds are far above its largest use. It returns
the issues it filed, in filing order, as `Filed` values.

One pass at a time. The pass holds a blocking `fcntl.flock(LOCK_EX)` on `lock` from reading the history
through writing the seen file, so overlapping passes (`proof-run` daily, now and file) never both read an
empty tracker and file twice. The open issues are read once per pass, under the lock.

The window. Only a line whose `ended` is at or after `now - WINDOW_DAYS` days counts. A line that is not
a JSON object, lacks one of the eight history members, has an unreadable `ended` or a `steps` that is not
a list is skipped, and so is a step that is not an object or lacks the members it is judged by.

Out-of-bounds. Each step with `outcome == "out-of-bounds"` in a line of the window is one occurrence,
identified `<run>/<procedure>/<step>/<visit>`: the later line of a continued run repeats the earlier
line's visits, and that repeat is the same occurrence. An occurrence in the seen file is skipped. Of the
rest, the first of each `<procedure>.<step>` key in file order is a candidate, so `land.release` and
`close-out.release` are two keys. The issue is titled `Engine step <procedure>.<step> ended out-of-bounds`
and starts with `step_marker(procedure, step)`.

Wide bound. For each role present in the window, in sorted order, the bound judged is the `bounds`
recorded on a step of that role in the newest line (by `ended`, the later line of a tie) that records
one; the installed `engine_session.ROLE_BOUNDS` is never read. `largest` of each dimension in
`DIMENSIONS` is the maximum over every step of that role in the window. A dimension is over when
`bound > FACTOR * largest`, strictly; a role with no recorded bound, or no over dimension, files nothing.
The issue is titled `The <role> role's bounds are more than five times its largest use in 14 days`, starts
with `role_marker(role)` and lists one `- <dimension>: bound <b>, largest use <u>` line per over
dimension, each value written with `str()` of the stored number.

Dedup. A candidate whose marker is a whole line (trailing whitespace dropped) of an open issue's body files
nothing. The tracker's `trusted_writer()` is asked before anything is filed and a false answer raises
`Refusal`; a pass with no candidate does not ask. The seen file (`seen_path()`, JSON
`{"format": 1, "occurrences": [...]}`) is rewritten through a temporary file in its directory and
`os.replace` only after every candidate is filed, and then holds every occurrence id of the window; a
`create` that raises leaves it unchanged. A seen file that cannot be read counts as empty.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple, Protocol

from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.delivery import engine_housekeeping, engine_ledger
from agent_tools.delivery.cleanup_issue import Issue, Refusal

WINDOW_DAYS = 14
FACTOR = 5
DIMENSIONS = ("wall_seconds", "turns", "spend_usd")
SEEN_FORMAT = 1
OUT_OF_BOUNDS = "out-of-bounds"
WIDE_BOUND = "wide-bound"


def step_marker(procedure: str, step: str) -> str:
    return f"<!-- agent:out-of-bounds v1 step={procedure}.{step} -->"


def role_marker(role: str) -> str:
    return f"<!-- agent:wide-bound v1 role={role} -->"


class Tracker(Protocol):
    def trusted_writer(self) -> bool: ...

    def open_issues(self) -> list[Issue]: ...

    def create(self, title: str, body: str) -> int: ...


class Filed(NamedTuple):
    kind: str
    key: str
    issue: int


class _Candidate(NamedTuple):
    kind: str
    key: str
    marker: str
    title: str
    body: str


def seen_path() -> Path:
    return engine_housekeeping.engine_root() / "bound-issues-seen.json"


def lock_path() -> Path:
    return engine_housekeeping.engine_root() / "bound-issues.lock"


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _window(history: Path, now: datetime) -> list[tuple[datetime, dict]]:
    """The readable history lines that ended inside the window, in file order."""
    try:
        data = Path(history).read_bytes()
    except FileNotFoundError:
        return []
    earliest = now - timedelta(days=WINDOW_DAYS)
    found = []
    for raw in data.split(b"\n"):
        try:
            line = json.loads(raw.decode("utf-8"))
            if (not isinstance(line, dict) or line.get("format") != engine_housekeeping.HISTORY_FORMAT
                    or any(member not in line for member in engine_housekeeping.HISTORY_MEMBERS)
                    or not isinstance(line["steps"], list)):
                continue
            ended = parse_rfc3339_utc(line["ended"])
        except (ValueError, RecursionError):
            continue
        if ended >= earliest:
            found.append((ended, line))
    return found


def _steps(line: dict) -> list[dict]:
    return [each for each in line["steps"] if isinstance(each, dict)]


def _occurrence(line: dict, each: dict) -> tuple[str, str] | None:
    """The occurrence id and `<procedure>.<step>` key of an out-of-bounds step, `None` for any other."""
    procedure, name, visit = each.get("procedure"), each.get("step"), each.get("visit")
    if each.get("outcome") != OUT_OF_BOUNDS:
        return None
    if not (isinstance(procedure, str) and isinstance(name, str) and isinstance(visit, int)
            and not isinstance(visit, bool) and isinstance(line["run"], str)):
        return None
    return f"{line['run']}/{procedure}/{name}/{visit}", f"{procedure}.{name}"


def _out_of_bounds(window: list[tuple[datetime, dict]], seen: set[str]) -> tuple[list[_Candidate], set[str]]:
    candidates: dict[str, _Candidate] = {}
    occurrences: set[str] = set()
    for _, line in window:
        for each in _steps(line):
            found = _occurrence(line, each)
            if found is None:
                continue
            identity, key = found
            occurrences.add(identity)
            if identity in seen or key in candidates:
                continue
            procedure, name = key.split(".", 1)
            body = (f"{step_marker(procedure, name)}\n\n"
                    f"Run {line['run']} of {line['project']} on issue {line['issue']}, visit {each['visit']}, "
                    f"ended {line['ended']}: wall_seconds {each.get('wall_seconds')}, "
                    f"turns {each.get('turns')}, spend_usd {each.get('spend_usd')}.\n\n"
                    "## Acceptance criteria\n\n"
                    f"- [ ] [code] Step {key} fits its bounds in the next run that reaches it, or its "
                    "bound is changed by a reviewed change — measured: the engine history\n")
            candidates[key] = _Candidate(OUT_OF_BOUNDS, key, step_marker(procedure, name),
                                         f"Engine step {key} ended out-of-bounds", body)
    return list(candidates.values()), occurrences


def _recorded(each: dict) -> dict | None:
    bounds = each.get("bounds")
    if isinstance(bounds, dict) and all(_number(bounds.get(name)) for name in DIMENSIONS):
        return bounds
    return None


def _wide_bounds(window: list[tuple[datetime, dict]]) -> list[_Candidate]:
    largest: dict[str, dict[str, float]] = {}
    newest: dict[str, tuple[datetime, dict]] = {}
    for ended, line in window:
        for each in _steps(line):
            role = each.get("role")
            if not isinstance(role, str):
                continue
            uses = largest.setdefault(role, {})
            for name in DIMENSIONS:
                value = each.get(name)
                if _number(value) and (name not in uses or value > uses[name]):
                    uses[name] = value
            bounds = _recorded(each)
            if bounds is not None and (role not in newest or ended >= newest[role][0]):
                newest[role] = (ended, bounds)
    found = []
    for role in sorted(largest):
        if role not in newest:
            continue
        bounds = newest[role][1]
        over = [name for name in DIMENSIONS
                if name in largest[role] and bounds[name] > FACTOR * largest[role][name]]
        if not over:
            continue
        listed = "".join(f"- {name}: bound {bounds[name]}, largest use {largest[role][name]}\n"
                         for name in over)
        body = (f"{role_marker(role)}\n\n{listed}\n## Acceptance criteria\n\n"
                f"- [ ] [code] Each bound listed in engine_session.ROLE_BOUNDS for {role} is at most "
                "five times the largest use above — measured: a comparison of the table's value with "
                "the largest use the engine history shows in 14 days\n")
        found.append(_Candidate(WIDE_BOUND, role, role_marker(role),
                                f"The {role} role's bounds are more than five times its largest use "
                                f"in {WINDOW_DAYS} days", body))
    return found


def _read_seen(path: Path) -> set[str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return set()
    listed = data.get("occurrences") if isinstance(data, dict) else None
    return {each for each in listed if isinstance(each, str)} if isinstance(listed, list) else set()


def _write_seen(path: Path, occurrences: set[str]) -> None:
    engine_ledger.make_root(Path(path).parent)
    descriptor, temporary = tempfile.mkstemp(dir=Path(path).parent, prefix=f".{Path(path).name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"format": SEEN_FORMAT, "occurrences": sorted(occurrences)}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _listed(body: str, marker: str) -> bool:
    return any(each.rstrip() == marker for each in body.splitlines())


def file_pass(tracker: Tracker, history: Path, seen: Path, lock: Path, now: datetime) -> list[Filed]:
    """File what the window of `history` shows and the open issues do not already carry."""
    engine_ledger.make_root(Path(lock).parent)
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        window = _window(history, now)
        candidates, occurrences = _out_of_bounds(window, _read_seen(seen))
        candidates += _wide_bounds(window)
        filed: list[Filed] = []
        if candidates:
            if not tracker.trusted_writer():
                raise Refusal("the authenticated user is not a trusted writer of the tracker")
            bodies = [issue.body for issue in tracker.open_issues()]
            for candidate in candidates:
                if any(_listed(body, candidate.marker) for body in bodies):
                    continue
                filed.append(Filed(candidate.kind, candidate.key,
                                   tracker.create(candidate.title, candidate.body)))
        _write_seen(seen, occurrences)
        return filed
    finally:
        os.close(descriptor)
