"""The console's engine runs: one reading per run, from the engine's own fold of its ledger.

The engine writes each run as a directory under the runs root: `run.json` (never changes), `events.jsonl`
(append-only; the engine cuts a torn tail and writes over it) and `lock` (the deliver process's
`{"pid","started"}`). This module reads them with no lock and writes nothing. Each poll lists the root with
`os.scandir`, which may be absent, and keeps the names that match the run id form and are directories.
It reads each `run.json` once per name and skips a run whose document has a `parent`. Per (project, issue)
it reads only the run with the greatest (`sequence`, name), which is the order the engine's `find_runs` uses.

`events.jsonl` is read by byte offset. Per run the reader keeps the inode, the offset just past the last
newline consumed and the events parsed so far, and never a partial tail. A torn tail stays unread until a
newline completes it, so a tail the engine cut and rewrote is read right. A different inode or a size below
the offset restarts at byte 0, a size equal to the offset opens nothing, and an absent file is no events.
A line the ledger refuses, or a `run.json` it refuses, names the run in `unreadable` and keeps the run's last
good events and state. A run directory that vanished leaves the states and the caches.

Each poll folds again with `engine_ledger.fold(run, events, alive, read_holder(run_dir))`; the console has no
fold of its own, so `engine status` and this view agree. The rules the readings follow:

- P1. The engine is the process in the run's `lock`, read with a plain open; it is not the fold's step process.
- P2. A live engine ends any step past its bound, so a live engine is moving and no step bound is read.
- P3. Waits are keyed by the ledger's `WAITS`; the `lock` wait keeps the sprint wording.
- P4. The reading is the first that holds of: done, stopped, not running (no live engine), waiting, moving.
- P5. Engine run states live in memory and are not logged; a restart reads each ledger once from its start.
- P6. The newest root run of each (project, issue) is shown once it entered a step; a done run or one stopped
  with need `nothing` leaves the page a day after its last event.
- P7. A fan-out reads `building task n of m` from the newest `call` event since the last step entered.
- P8. A stop reads `stopped at <name, hyphens as spaces>, needs <need words>`; a need but `nothing` counts in the heading.

No line says a run is quiet or stuck: a live engine is moving, whatever the time since its last event.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterable

from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.console import sprints
from agent_tools.delivery import engine_ledger
from agent_tools.delivery.engine_ledger import LedgerError, RunState

READINGS = ("moving", "waiting", "stopped", "not_running", "done")
WAIT_TEXT = {"usage-limit": "waiting out a usage limit",
             "host-slot": "waiting for a free session slot on this host",
             "lock": sprints.NOW_LOCK_TEXT}
NEED_TEXT = {"owner-decision": "your decision", "owner-look": "your look", "retry": "a retry",
             "nothing": "nothing"}
NOT_RUNNING_TEXT = "the engine is not running"
ENDED_SHOWN_MS = 24 * 60 * 60 * 1000
EVENTS_NAME = "events.jsonl"


def stage_text(state: RunState) -> str | None:
    """The stage in words, with the task of a fan-out; None before the first step."""
    if state.stage == "building" and state.fanout:
        return f"building task {state.fanout['task']} of {state.fanout['tasks']}"
    return state.stage


def reading(state: RunState) -> str:
    """One of `READINGS`: done, stopped, not running, waiting, then moving."""
    if state.done:
        return "done"
    if state.stop:
        return "stopped"
    if not state.engine_alive:
        return "not_running"
    return "waiting" if state.wait else "moving"


def line_text(state: RunState) -> str:
    """The run's one line; the run has a stage."""
    kind = reading(state)
    if kind == "done":
        return "done"
    if kind == "stopped":
        name = state.stop["name"].replace("-", " ")  # type: ignore[index]
        return f"stopped at {name}, needs {NEED_TEXT[state.stop['need']]}"  # type: ignore[index]
    if kind == "not_running":
        return f"{stage_text(state)}, {NOT_RUNNING_TEXT}"
    if kind == "waiting":
        return f"{stage_text(state)}, {WAIT_TEXT[state.wait['wait']]}"  # type: ignore[index]
    return f"{stage_text(state)}, moving"


def _ended(state: RunState, kind: str) -> bool:
    return kind == "done" or (kind == "stopped" and state.stop["need"] == "nothing")  # type: ignore[index]


def engine_entry(state: RunState, now_ms: int | None) -> dict | None:
    """The run's entry for the page; None before its first step, or a day after it ended."""
    if state.stage is None:
        return None
    kind = reading(state)
    if now_ms is not None and _ended(state, kind):
        last_ms = parse_rfc3339_utc(state.last_event).timestamp() * 1000  # type: ignore[arg-type]
        if now_ms - last_ms >= ENDED_SHOWN_MS:
            return None
    return {"run_id": state.run, "issue": state.issue, "stage": state.stage,
            "stage_text": stage_text(state), "reading": kind, "text": line_text(state),
            "wait_until": state.wait["until"] if kind == "waiting" and state.wait else None,
            "need": state.stop["need"] if kind == "stopped" else None,  # type: ignore[index]
            "last_event_at": state.last_event}


def project_lines(states: Iterable[RunState], now_ms: int | None) -> dict[str, list[dict]]:
    """Each project's shown entries in (issue, run id) order; a project with none is absent."""
    lines: dict[str, list[dict]] = {}
    for state in states:
        entry = engine_entry(state, now_ms)
        if entry is not None:
            lines.setdefault(state.project, []).append(entry)
    for entries in lines.values():
        entries.sort(key=lambda entry: (entry["issue"], entry["run_id"]))
    return lines


@dataclass(frozen=True)
class EnginePoll:
    """The states of one poll, by (project, issue), and the `(run id, reason)` of each run it could not read."""

    states: tuple[RunState, ...]
    unreadable: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _Tail:
    inode: int
    offset: int
    events: tuple[dict, ...]


def _open_binary(path: Path) -> BinaryIO:
    return open(path, "rb")


def _reason(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"


class EngineRuns:
    def __init__(self, root: Path, alive: Callable[[int, str], bool] = engine_ledger.process_alive,
                 opener: Callable[[Path], BinaryIO] = _open_binary):
        self._root, self._alive, self._opener = Path(root), alive, opener
        self._documents: dict[str, dict] = {}
        self._tails: dict[str, _Tail] = {}
        self._states: dict[str, RunState] = {}

    def poll(self) -> EnginePoll:
        names = self._names()
        unreadable: list[tuple[str, str]] = []
        self._documents = {name: doc for name, doc in self._documents.items() if name in names}
        newest: dict[tuple[str, int], tuple[tuple[int, str], str]] = {}
        for name in names:
            document = self._document(name, unreadable)
            if document is None or engine_ledger.PARENT_MEMBER in document:
                continue
            key = (document["project"], document["issue"])
            order = (document["sequence"], name)
            if key not in newest or order > newest[key][0]:
                newest[key] = (order, name)
        chosen = {name for _, name in newest.values()}
        for cache in (self._tails, self._states):
            for name in [name for name in cache if name not in chosen]:
                del cache[name]
        for name in sorted(chosen):
            self._fold(name, unreadable)
        states = sorted((self._states[name] for name in chosen if name in self._states),
                        key=lambda state: (state.project, state.issue))
        return EnginePoll(tuple(states), tuple(sorted(unreadable)))

    def _names(self) -> list[str]:
        try:
            with os.scandir(self._root) as entries:
                return sorted(entry.name for entry in entries
                              if engine_ledger.RUN_ID_RE.match(entry.name) and entry.is_dir())
        except FileNotFoundError:
            return []

    def _document(self, name: str, unreadable: list[tuple[str, str]]) -> dict | None:
        if name not in self._documents:
            try:
                document = engine_ledger.read_run(self._root / name)
            except LedgerError as error:
                if (self._root / name).is_dir():
                    unreadable.append((name, str(error)))
                return None
            if engine_ledger.RUN_ID_RE.match(name).group(1) != str(document["issue"]):  # type: ignore[union-attr]
                return None
            self._documents[name] = document
        return self._documents[name]

    def _fold(self, name: str, unreadable: list[tuple[str, str]]) -> None:
        run_dir = self._root / name
        try:
            events = self._events(name, run_dir / EVENTS_NAME)
        except (LedgerError, OSError) as error:
            unreadable.append((name, _reason(error) if isinstance(error, OSError) else str(error)))
            return
        self._states[name] = engine_ledger.fold(self._documents[name], events, self._alive,
                                                engine_ledger.read_holder(run_dir))

    def _events(self, name: str, path: Path) -> tuple[dict, ...]:
        try:
            stat = os.stat(path)
        except FileNotFoundError:
            self._tails.pop(name, None)
            return ()
        known = self._tails.get(name)
        if known is None or known.inode != stat.st_ino or stat.st_size < known.offset:
            known = _Tail(stat.st_ino, 0, ())
        if stat.st_size == known.offset:
            self._tails[name] = known
            return known.events
        with self._opener(path) as handle:
            handle.seek(known.offset)
            data = handle.read(stat.st_size - known.offset)
        end = data.rfind(b"\n") + 1
        parsed = tuple(engine_ledger.parse_event_line(part) for part in data[:end].split(b"\n")[:-1])
        tail = _Tail(stat.st_ino, known.offset + end, known.events + parsed)
        self._tails[name] = tail
        return tail.events
