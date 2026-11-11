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

Ordering and folding: a project is active when `open_work > 0` and quiet
otherwise. Each group is sorted by newest `last_seq` first, then `project_id`.
The entries are the active projects, then the quiet projects, except that more
than `FOLD_AFTER` quiet projects are replaced by one `quiet_group` entry.

Wire format, one object:

    {"statement": {"inbox_items": <open items>, "headline": "<headline>",
                   "sentence": "<sentence>", "stale": <bool>},
     "inbox": {"open": [<inbox item>, ...], "answered": [<inbox item>, ...]},
     "project_count": <int>,
     "entries": [<project entry> | <group entry>, ...]}

The headline is "1 thing needs you" or "<n> things need you" for open items, else
`STALE_HEADLINE` when a registered project's tracker cannot be read, else "Nothing needs
you". The sentence is `STALE_SENTENCE` naming those projects when any is stale, else
`NEEDS_SENTENCE` when something is open, else the registered-project count. `stale` is true
when any registered project's last read failed. An inbox item is the stored item plus
`{"type": "inbox_item", "waiting_since", "stale", "read_at"}`: `stale` is that project's
failed read, `read_at` the time of its last good read (the item's last update when the read
time is unknown). Only items of registered projects are shown. Open items are sorted by
most held work first, then `waiting_since`, then `key`; answered items are listed apart,
never counted, by `waiting_since` then `key`.

A project entry is `{"type": "project", "project_id", "root", "quiet",
"open_work", "last_activity"}`; a group entry is `{"type": "quiet_group",
"label": "<n> quiet projects", "count": <n>, "projects": [<project entry>]}`.
`encode_view` writes sorted keys, compact separators, non-ASCII kept, NaN
refused, no newline.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from agent_tools.console.event_log import Event

REGISTERED = "project.registered"
UNREGISTERED = "project.unregistered"
FOLD_AFTER = 3
HEADLINE = "Nothing needs you"
STALE_HEADLINE = "The tracker cannot be read"
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


def _project_entry(state: ProjectState) -> dict:
    return {
        "type": "project",
        "project_id": state.project_id,
        "root": state.root,
        "quiet": state.open_work == 0,
        "open_work": state.open_work,
        "last_activity": state.last_at,
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


def _headline(open_count: int, stale: bool) -> str:
    if open_count == 1:
        return "1 thing needs you"
    if open_count > 1:
        return f"{open_count} things need you"
    return STALE_HEADLINE if stale else HEADLINE


def derive_view(
    states: Iterable[ProjectState],
    records: Mapping[tuple[str, str], InboxRecord] | None = None,
    health: Mapping[str, ReadState] | None = None,
) -> dict:
    states = list(states)
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
    if stale_projects:
        sentence = STALE_SENTENCE.format(projects=", ".join(stale_projects))
    elif open_items:
        sentence = NEEDS_SENTENCE
    else:
        sentence = _sentence(len(states))
    active = _order(s for s in states if s.open_work > 0)
    quiet = _order(s for s in states if s.open_work == 0)
    entries = [_project_entry(s) for s in active]
    quiet_entries = [_project_entry(s) for s in quiet]
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
                                            bool(stale_projects)),
                      "sentence": sentence, "stale": bool(stale_projects)},
        "inbox": {"open": [_inbox_entry(r, health) for r in open_items],
                  "answered": [_inbox_entry(r, health) for r in answered]},
        "project_count": len(states),
        "entries": entries,
    }


def encode_view(view: Mapping) -> bytes:
    return json.dumps(view, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
