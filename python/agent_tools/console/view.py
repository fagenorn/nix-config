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

Ordering and folding: a project is active when `open_work > 0` or it has a
listed session, and quiet otherwise. Each group is sorted by newest `last_seq` first, then `project_id`.
The entries are the active projects, then the quiet projects, except that more
than `FOLD_AFTER` quiet projects are replaced by one `quiet_group` entry.

Wire format, one object:

    {"statement": {"inbox_items": 0, "headline": "Nothing needs you",
                   "sentence": "<sentence>"},
     "project_count": <int>,
     "entries": [<project entry> | <group entry>, ...],
     "unmanaged": [<unmanaged entry>, ...]}

A project entry is `{"type": "project", "project_id", "root", "quiet",
"open_work", "last_activity", "outside_sprints": <line>}`; a group entry is
`{"type": "quiet_group", "label": "<n> quiet projects", "count": <n>,
"projects": [<project entry>]}`. `project_count` counts registered projects
only. `unmanaged` is always present, possibly empty, sorted by `root`.

    <line> = {"label": "Outside sprints", "working": <int>, "waiting": <int>,
              "summary": "<text>", "sessions": [<session entry>, ...]}
    <session entry> = {"session_id", "name", "state", "state_text", "cwd"}
    <unmanaged entry> = {"type": "unmanaged", "root": "<repo>",
                         "label": "Not yet managed", "outside_sprints": <line>}

`working` counts working sessions and `waiting` counts those waiting for an
answer or a permission. `summary` joins, with ", ", the non-zero parts
"<n> working", "<n> waiting", "<n> stopped on a usage limit", "<n> idle", in
that order, and is "No sessions" with none. Sessions are ordered by state rank
(waiting_answer, waiting_permission, working, limit, idle), then newest
`last_seq`, then `session_id`; `name` is the session's name, else the first 8
characters of its id.
`encode_view` writes sorted keys, compact separators, non-ASCII kept, NaN
refused, no newline.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

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


def project_for(repo: str, states: Mapping[str, ProjectState]) -> str | None:
    matches = [project_id for project_id, state in states.items()
               if state.root == repo]
    return min(matches) if matches else None


def _session_entry(session: SessionState) -> dict:
    return {
        "session_id": session.session_id,
        "name": session.name or session.session_id[:8],
        "state": session.state,
        "state_text": STATE_TEXT[session.state],
        "cwd": session.cwd,
    }


def _line(sessions: Iterable[SessionState]) -> dict:
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
        "sessions": [_session_entry(s) for s in ordered],
    }


def _project_entry(state: ProjectState, sessions: Sequence[SessionState],
                   ) -> dict:
    return {
        "type": "project",
        "project_id": state.project_id,
        "root": state.root,
        "quiet": state.open_work == 0 and not sessions,
        "open_work": state.open_work,
        "last_activity": state.last_at,
        "outside_sprints": _line(sessions),
    }


def _sentence(count: int) -> str:
    if count == 0:
        return "No project is registered yet."
    noun = "project" if count == 1 else "projects"
    return f"{count} registered {noun}, and nothing is waiting on you."


def derive_view(states: Iterable[ProjectState],
                sessions: Iterable[SessionState] = ()) -> dict:
    states = list(states)
    by_id = {state.project_id: state for state in states}
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
    entries = [_project_entry(s, owned.get(s.project_id, ())) for s in active]
    quiet_entries = [_project_entry(s, ()) for s in quiet]
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
        "unmanaged": [
            {"type": "unmanaged", "root": root, "label": UNMANAGED_LABEL,
             "outside_sprints": _line(unmanaged[root])}
            for root in sorted(unmanaged)],
    }


def encode_view(view: Mapping) -> bytes:
    return json.dumps(view, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
