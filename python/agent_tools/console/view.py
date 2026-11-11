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

Ordering and folding: a project is active when `open_work > 0` and quiet
otherwise. Each group is sorted by newest `last_seq` first, then `project_id`.
The entries are the active projects, then the quiet projects, except that more
than `FOLD_AFTER` quiet projects are replaced by one `quiet_group` entry.

Wire format, one object:

    {"statement": {"inbox_items": 0, "headline": "Nothing needs you",
                   "sentence": "<sentence>"},
     "project_count": <int>,
     "entries": [<project entry> | <group entry>, ...]}

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


def derive_view(states: Iterable[ProjectState]) -> dict:
    states = list(states)
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
        "statement": {"inbox_items": 0, "headline": HEADLINE,
                      "sentence": _sentence(len(states))},
        "project_count": len(states),
        "entries": entries,
    }


def encode_view(view: Mapping) -> bytes:
    return json.dumps(view, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
