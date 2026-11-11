"""The console's view of the fleet: pure functions from events to what the page shows.

Nothing here reads a clock, a file or the environment. `project_states` folds
the event log onto per-project state; `registry_changes` turns a difference
between that state and the fleet registry into events to append; `derive_view`
orders and folds the state into the wire view; `encode_view` renders it as one
line of JSON.

Events: `project.registered` (payload `{"root": ...}`) sets a project, keeping
its open work; `project.unregistered` removes it; any other event that names a
project updates only that project's last sequence and time; an event naming no
project, or a project not registered, is ignored.

Sessions: only a listed session counts. A session that has ended (a tombstone)
or whose `repo` is `None` (outside any git repository) is not listed under any
project, makes no unmanaged entry and counts in no line. A listed session
belongs to the project whose `root` equals its `repo` (`project_for`), else to
the unmanaged entry for its `repo`. Sessions never touch the statement or
`project_count`: a waiting session is not an inbox item.

Inbox events name a project and carry the tracker's owner-action items. `inbox.seen`
(payload: an item, with its `key`) records the item with `waiting_since` and
`updated_at` both the event's time; `inbox.changed` (payload: the item) replaces the item and
`updated_at` but keeps `waiting_since` (an unknown key is treated as seen); `inbox.gone`
(payload `{"key"}`) removes the item; `project.unregistered` removes every item of that
project; an inbox event whose payload has no string `key` is ignored. `inbox.health`
(payload `{"ok": true}` or `{"ok": false, "read_at": <time of the last good read> | null}`)
is logged only when a project's tracker read changes between good and failed: `ok` true
folds to a read at the event's time, `ok` false to a failed read at `read_at`, a payload
whose `ok` is not a bool is ignored, `project.unregistered` removes the project's health.
Every inbox event also moves its registered project's last sequence and time.

Ordering and folding: a project is active when `open_work > 0` or it has a
listed session, and quiet otherwise. Each group is sorted by newest `last_seq` first, then `project_id`.
The entries are the active projects, then the quiet projects, except that more
than `FOLD_AFTER` quiet projects are replaced by one `quiet_group` entry.

Wire format, one object:

    {"statement": {"inbox_items": <open items>, "headline": "<headline>",
                   "sentence": "<sentence>", "stale": <bool>},
     "capacity": {"tight": <bool>, "all_out": <bool>, "resumes_at": <ISO time> | null,
                  "profiles": [<profile capacity>, ...]},
     "inbox": {"open": [<inbox item>, ...], "answered": [<inbox item>, ...]},
     "project_count": <int>,
     "entries": [<project entry> | <group entry>, ...],
     "unmanaged": [<unmanaged entry>, ...],
     "digest": <digest> | null}

`digest` is what changed since the owner last looked (see `digest.py`):
`{"since": <last look> | null, "first_visit": <bool>, "recent": [<moment>, ...],
"earlier": [<moment>, ...], "omitted": <int>}` with a moment `{"at", "kind", "sentence"}`; it is
null when `derive_view` is given none.

The headline is "1 thing needs you" or "<n> things need you" for open items, else
`ALL_OUT_HEADLINE` when every profile is out of usage, else `STALE_HEADLINE` when a registered
project's tracker cannot be read, else "Nothing needs you". The sentence is `ALL_OUT_SENTENCE`
when every profile is out of usage, else `STALE_SENTENCE` naming those projects when any is
stale, else `NEEDS_SENTENCE` when something is open, else the registered-project count. The
all-out promotion never changes `inbox_items`, and the statement keeps exactly its four keys.
`capacity` is the `capacity_view` the caller passes (`capacity.py` defines its members), else the
empty capacity, the same bytes as `capacity_view` over no profile. `stale` is true
when any registered project's last read failed. An inbox item is the stored item plus
`{"type": "inbox_item", "waiting_since", "stale", "read_at"}`: `stale` is that project's
failed read, `read_at` the time of its last good read (the item's last update when the read
time is unknown). Only items of registered projects are shown. Open items are sorted by
most held work first, then `waiting_since`, then `key`; answered items are listed apart,
never counted, by `waiting_since` then `key`.

A project entry is `{"type": "project", "project_id", "root", "quiet",
"open_work", "last_activity", "outside_sprints": <line>}`; a group entry is
`{"type": "quiet_group", "label": "<n> quiet projects", "count": <n>,
"projects": [<project entry>]}`. `project_count` counts registered projects
only. `unmanaged` is always present, possibly empty, sorted by `root`.

    <line> = {"label": "Outside sprints", "working": <int>, "waiting": <int>,
              "summary": "<text>", "sessions": [<session entry>, ...]}
    <session entry> = {"session_id", "name", "state", "state_text", "cwd",
                       "deliveries": [<delivery entry>, ...]}
    <delivery entry> = {"run_id", "quiet": <bool>, "moved_text": "<text>",
                        "issues": [{"issue": <int>, "stage", "stage_text"}, ...]}
    <unmanaged entry> = {"type": "unmanaged", "root": "<repo>",
                         "label": "Not yet managed", "outside_sprints": <line>}

`working` counts working sessions and `waiting` counts those waiting for an
answer or a permission. `summary` joins, with ", ", the non-zero parts
"<n> working", "<n> waiting", "<n> stopped on a usage limit", "<n> idle", in
that order, and is "No sessions" with none. Sessions are ordered by state rank
(waiting_answer, waiting_permission, working, limit, idle), then newest
`last_seq`, then `session_id`; `name` is the session's name, else the first 8
characters of its id.

`deliveries` (always present, possibly empty) are the in-flight workflow runs of that listed
session, from the delivery states `derive_view` is given: the states whose `session_id` equals the
session's id, newest `moved_ms` first, then `run_id`; each run's issues are ordered by number.
`quiet` and `moved_text` come from `moved_text(now_ms - moved_ms)`; `now_ms` is injected by the
caller (this module still reads no clock) and `None` counts as no time elapsed. The runs of an
ended or unlisted session appear nowhere, and they change no count, summary, order or the
statement. The word "stalled" is never written: a quiet run is only quiet.
`encode_view` writes sorted keys, compact separators, non-ASCII kept, NaN
refused, no newline.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from agent_tools.console.capacity import EMPTY
from agent_tools.console.deliveries import DeliveryState, moved_text, stage_text
from agent_tools.console.event_log import Event
from agent_tools.console.sessions import (
    ENDED,
    IDLE,
    LIMIT,
    STATE_TEXT,
    WAITING_ANSWER,
    WAITING_PERMISSION,
    WORKING,
    SessionState,
)

REGISTERED = "project.registered"
UNREGISTERED = "project.unregistered"
FOLD_AFTER = 3
HEADLINE = "Nothing needs you"
OUTSIDE_LABEL = "Outside sprints"
UNMANAGED_LABEL = "Not yet managed"

_RANK = {state: rank for rank, state in enumerate(
    (WAITING_ANSWER, WAITING_PERMISSION, WORKING, LIMIT, IDLE))}
_WAITING = (WAITING_ANSWER, WAITING_PERMISSION)
_SUMMARY_PARTS = (
    ("working", (WORKING,)),
    ("waiting", _WAITING),
    ("stopped on a usage limit", (LIMIT,)),
    ("idle", (IDLE,)),
)
STALE_HEADLINE = "The tracker cannot be read"
ALL_OUT_HEADLINE = "Every profile is out of usage"
ALL_OUT_SENTENCE = "Everything resumes at the earliest reset; nothing is asked of you."
NEEDS_SENTENCE = "Each one links to the tracker, where it is answered."
STALE_SENTENCE = ("The tracker could not be read for {projects}; "
                  "each item shows when it was last read.")
INBOX_SEEN = "inbox.seen"
INBOX_CHANGED = "inbox.changed"
INBOX_GONE = "inbox.gone"
INBOX_HEALTH = "inbox.health"


@dataclass(frozen=True)
class ProjectState:
    project_id: str
    root: str
    last_seq: int
    last_at: str
    open_work: int = 0


def project_states(
    events: Iterable[Event],
    states: Mapping[str, ProjectState] | None = None,
) -> dict[str, ProjectState]:
    result = dict(states or {})
    for event in events:
        project = event.project
        if event.kind == REGISTERED and project is not None:
            previous = result.get(project)
            result[project] = ProjectState(
                project, event.payload["root"], event.seq, event.at,
                previous.open_work if previous else 0)
        elif event.kind == UNREGISTERED:
            result.pop(project, None)
        elif project in result:
            result[project] = replace(
                result[project], last_seq=event.seq, last_at=event.at)
    return result


@dataclass(frozen=True)
class InboxRecord:
    item: dict
    waiting_since: str
    updated_at: str


@dataclass(frozen=True)
class ReadState:
    ok: bool
    read_at: str | None


def inbox_records(
    events: Iterable[Event],
    records: Mapping[tuple[str, str], InboxRecord] | None = None,
) -> dict[tuple[str, str], InboxRecord]:
    """Records keyed by (owning project, item key): item keys are global to a repository,
    and two registered projects can resolve to the same one."""
    result = dict(records or {})
    for event in events:
        if event.kind == UNREGISTERED:
            result = {k: record for k, record in result.items()
                      if k[0] != event.project}
            continue
        if event.kind not in (INBOX_SEEN, INBOX_CHANGED, INBOX_GONE):
            continue
        name = event.payload.get("key")
        if not isinstance(name, str) or event.project is None:
            continue
        key = (event.project, name)
        if event.kind == INBOX_GONE:
            result.pop(key, None)
        elif event.kind == INBOX_CHANGED and key in result:
            result[key] = replace(
                result[key], item=event.payload, updated_at=event.at)
        else:
            result[key] = InboxRecord(event.payload, event.at, event.at)
    return result


def inbox_changes(
    records: Mapping[tuple[str, str], InboxRecord],
    project_id: str,
    items: Sequence[dict],
) -> list[tuple[str, str, dict]]:
    changes: list[tuple[str, str, dict]] = []
    named = set()
    for item in sorted(items, key=lambda i: i["key"]):
        named.add(item["key"])
        record = records.get((project_id, item["key"]))
        if record is None:
            changes.append((INBOX_SEEN, project_id, item))
        elif record.item != item:
            changes.append((INBOX_CHANGED, project_id, item))
    changes.extend(
        (INBOX_GONE, project_id, {"key": key})
        for (owner, key) in sorted(records)
        if owner == project_id and key not in named)
    return changes


def read_states(
    events: Iterable[Event],
    health: Mapping[str, ReadState] | None = None,
) -> dict[str, ReadState]:
    result = dict(health or {})
    for event in events:
        if event.kind == UNREGISTERED:
            result.pop(event.project, None)
        elif event.kind == INBOX_HEALTH and event.project is not None:
            ok = event.payload.get("ok")
            if ok is True:
                result[event.project] = ReadState(True, event.at)
            elif ok is False:
                read_at = event.payload.get("read_at")
                result[event.project] = ReadState(
                    False, read_at if isinstance(read_at, str) else None)
    return result


def health_change(
    health: Mapping[str, ReadState],
    project_id: str,
    ok: bool,
    read_at: str | None = None,
) -> list[tuple[str, str, dict]]:
    known = health.get(project_id)
    if ok and (known is None or not known.ok):
        return [(INBOX_HEALTH, project_id, {"ok": True})]
    if not ok and (known is None or known.ok):
        return [(INBOX_HEALTH, project_id, {"ok": False, "read_at": read_at})]
    return []


def registry_changes(
    states: Mapping[str, ProjectState],
    entries: Sequence[Mapping[str, str]],
) -> list[tuple[str, str, dict]]:
    wanted = {entry["project_id"]: entry["root"] for entry in entries}
    changes: list[tuple[str, str, dict]] = [
        (REGISTERED, project_id, {"root": root})
        for project_id, root in sorted(wanted.items())
        if project_id not in states or states[project_id].root != root
    ]
    changes.extend((UNREGISTERED, project_id, {})
                   for project_id in sorted(states) if project_id not in wanted)
    return changes


def _order(states: Iterable[ProjectState]) -> list[ProjectState]:
    return sorted(states, key=lambda s: (-s.last_seq, s.project_id))


def project_for(repo: str, states: Mapping[str, ProjectState]) -> str | None:
    matches = [project_id for project_id, state in states.items()
               if state.root == repo]
    return min(matches) if matches else None


def _delivery_entry(state: DeliveryState, now_ms: int | None) -> dict:
    quiet, text = moved_text(0 if now_ms is None else now_ms - state.moved_ms)
    return {
        "run_id": state.run_id,
        "quiet": quiet,
        "moved_text": text,
        "issues": [
            {"issue": i.issue, "stage": i.stage, "stage_text": stage_text(i)}
            for i in sorted(state.issues, key=lambda i: i.issue)
        ],
    }


def _session_entry(session: SessionState,
                   deliveries: Mapping[str, Sequence[DeliveryState]],
                   now_ms: int | None) -> dict:
    runs = sorted(deliveries.get(session.session_id, ()),
                  key=lambda d: (-d.moved_ms, d.run_id))
    return {
        "session_id": session.session_id,
        "name": session.name or session.session_id[:8],
        "state": session.state,
        "state_text": STATE_TEXT[session.state],
        "cwd": session.cwd,
        "deliveries": [_delivery_entry(d, now_ms) for d in runs],
    }


def _line(sessions: Iterable[SessionState],
          deliveries: Mapping[str, Sequence[DeliveryState]],
          now_ms: int | None) -> dict:
    ordered = sorted(sessions, key=lambda s: (
        _RANK[s.state], -s.last_seq, s.session_id))
    summary = ", ".join(
        f"{n} {text}" for text, members in _SUMMARY_PARTS
        if (n := sum(s.state in members for s in ordered)))
    return {
        "label": OUTSIDE_LABEL,
        "working": sum(s.state == WORKING for s in ordered),
        "waiting": sum(s.state in _WAITING for s in ordered),
        "summary": summary or "No sessions",
        "sessions": [_session_entry(s, deliveries, now_ms) for s in ordered],
    }


def _project_entry(state: ProjectState, sessions: Sequence[SessionState],
                   deliveries: Mapping[str, Sequence[DeliveryState]],
                   now_ms: int | None) -> dict:
    return {
        "type": "project",
        "project_id": state.project_id,
        "root": state.root,
        "quiet": state.open_work == 0 and not sessions,
        "open_work": state.open_work,
        "last_activity": state.last_at,
        "outside_sprints": _line(sessions, deliveries, now_ms),
    }


def _sentence(count: int) -> str:
    if count == 0:
        return "No project is registered yet."
    noun = "project" if count == 1 else "projects"
    return f"{count} registered {noun}, and nothing is waiting on you."


def _inbox_entry(record: InboxRecord,
                 health: Mapping[str, ReadState]) -> dict:
    known = health.get(record.item["project_id"])
    stale = known is not None and not known.ok
    read_at = known.read_at if known is not None and known.read_at is not None \
        else record.updated_at
    return {**record.item, "type": "inbox_item",
            "waiting_since": record.waiting_since,
            "stale": stale, "read_at": read_at}


def _headline(open_count: int, stale: bool, all_out: bool) -> str:
    if open_count == 1:
        return "1 thing needs you"
    if open_count > 1:
        return f"{open_count} things need you"
    if all_out:
        return ALL_OUT_HEADLINE
    return STALE_HEADLINE if stale else HEADLINE


def derive_view(
    states: Iterable[ProjectState],
    records: Mapping[tuple[str, str], InboxRecord] | None = None,
    health: Mapping[str, ReadState] | None = None,
    sessions: Iterable[SessionState] = (),
    capacity: Mapping | None = None,
    digest: Mapping | None = None,
    deliveries: Mapping[tuple[str, str], DeliveryState] | None = None,
    now_ms: int | None = None,
) -> dict:
    states = list(states)
    capacity = EMPTY if capacity is None else capacity
    registered = {s.project_id for s in states}
    health = health or {}
    shown = [r for r in (records or {}).values()
             if r.item.get("project_id") in registered]
    open_items = sorted(
        (r for r in shown if not r.item["answered"]),
        key=lambda r: (-r.item["held_work"], r.waiting_since, r.item["key"],
                       r.item["project_id"]))
    answered = sorted(
        (r for r in shown if r.item["answered"]),
        key=lambda r: (r.waiting_since, r.item["key"], r.item["project_id"]))
    stale_projects = sorted(
        p for p in registered if p in health and not health[p].ok)
    all_out = bool(capacity["all_out"])
    if all_out:
        sentence = ALL_OUT_SENTENCE
    elif stale_projects:
        sentence = STALE_SENTENCE.format(projects=", ".join(stale_projects))
    elif open_items:
        sentence = NEEDS_SENTENCE
    else:
        sentence = _sentence(len(states))
    by_id = {state.project_id: state for state in states}
    runs: dict[str, list[DeliveryState]] = {}
    for delivery in (deliveries or {}).values():
        runs.setdefault(delivery.session_id, []).append(delivery)
    owned: dict[str, list[SessionState]] = {}
    unmanaged: dict[str, list[SessionState]] = {}
    for session in sessions:
        if session.state == ENDED or session.repo is None:
            continue
        project_id = project_for(session.repo, by_id)
        if project_id is None:
            unmanaged.setdefault(session.repo, []).append(session)
        else:
            owned.setdefault(project_id, []).append(session)

    def is_active(state: ProjectState) -> bool:
        return state.open_work > 0 or state.project_id in owned

    active = _order(s for s in states if is_active(s))
    quiet = _order(s for s in states if not is_active(s))
    entries = [_project_entry(s, owned.get(s.project_id, ()), runs, now_ms)
               for s in active]
    quiet_entries = [_project_entry(s, (), runs, now_ms) for s in quiet]
    if len(quiet_entries) <= FOLD_AFTER:
        entries.extend(quiet_entries)
    else:
        entries.append({
            "type": "quiet_group",
            "label": f"{len(quiet_entries)} quiet projects",
            "count": len(quiet_entries),
            "projects": quiet_entries,
        })
    return {
        "statement": {"inbox_items": len(open_items),
                      "headline": _headline(len(open_items),
                                            bool(stale_projects), all_out),
                      "sentence": sentence, "stale": bool(stale_projects)},
        "capacity": capacity,
        "inbox": {"open": [_inbox_entry(r, health) for r in open_items],
                  "answered": [_inbox_entry(r, health) for r in answered]},
        "project_count": len(states),
        "entries": entries,
        "unmanaged": [
            {"type": "unmanaged", "root": root, "label": UNMANAGED_LABEL,
             "outside_sprints": _line(unmanaged[root], runs, now_ms)}
            for root in sorted(unmanaged)],
        "digest": dict(digest) if digest is not None else None,
    }


def encode_view(view: Mapping) -> bytes:
    return json.dumps(view, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
