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
`updated_at` both the event's time, and `answered_at` the event's time when the item is
answered, else null; `inbox.changed` (payload: the item) replaces the item and
`updated_at` but keeps `waiting_since` (an unknown key is treated as seen); its `answered_at`
is the event's time when the new item is answered and the old one was not, the old
`answered_at` when both are answered, null when the new item is not answered, so it moves only
when the item turns answered and a later change of any other member keeps it; `inbox.gone`
(payload `{"key"}`) removes the item; `project.unregistered` removes every item of that
project; an inbox event whose payload has no string `key` is ignored. `inbox.health`
(payload `{"ok": true}` or `{"ok": false, "read_at": <time of the last good read> | null}`)
is logged only when a project's tracker read changes between good and failed: `ok` true
folds to a read at the event's time, `ok` false to a failed read at `read_at`, a payload
whose `ok` is not a bool is ignored, `project.unregistered` removes the project's health.
Every inbox event also moves its registered project's last sequence and time.

Ordering and folding: a project is active when `open_work > 0`, it has a
listed session or it has a shown sprint, and quiet otherwise. Each group is sorted by newest `last_seq` first, then `project_id`.
The entries are the active projects, then the quiet projects, except that more
than `FOLD_AFTER` quiet projects are replaced by one `quiet_group` entry.

Wire format, one object:

    {"statement": {"inbox_items": <open items>, "headline": "<headline>",
                   "sentence": "<sentence>", "stale": <bool>},
     "capacity": {"tight": <bool>, "all_out": <bool>, "resumes_at": <ISO time> | null,
                  "no_reading": "<n> with no reading yet" | null,
                  "profiles": [<profile capacity>, ...]},
     "inbox": {"open": [<inbox item>, ...], "answered": [<inbox item>, ...]},
     "project_count": <int>,
     "entries": [<project entry> | <group entry>, ...],
     "unmanaged": [<unmanaged entry>, ...],
     "recent_projects": ["<project id>", ...],
     "digest": <digest> | null,
     "managers": <bool>,
     "unstopped": [{"project_id", "sprint_id", "goal", "text", "failed_at"}, ...]}

`digest` is what changed since the owner last looked (see `digest.py`):
`{"since": <last look> | null, "first_visit": <bool>, "recent": [<moment>, ...],
"earlier": [<moment>, ...], "omitted": <int>}` with a moment `{"at", "kind", "sentence"}`; it is
null when `derive_view` is given none.

The headline is "1 thing needs you" or "<n> things need you" for open items (a waiting brief is one,
see below), else
`ALL_OUT_HEADLINE` when every profile is out of usage, else `STALE_HEADLINE` when a registered
project's tracker cannot be read, else "Nothing needs you". The sentence is `ALL_OUT_SENTENCE`
when every profile is out of usage, else `STALE_SENTENCE` naming those projects when any is
stale, else `BRIEF_SENTENCE` when any brief is open, else `MANAGER_SENTENCE` when a sprint is
stalled, else `CHOOSE_SENTENCE` when an open item is a
decision with questions (the page can
answer it), else `ANSWER_SENTENCE` when an open item has answers (a verification prompt the page
can answer), else `NEEDS_SENTENCE` when something is open, else the registered-project count. The
all-out promotion never changes `inbox_items`, and the statement keeps exactly its four keys.
`capacity` is the `capacity_view` the caller passes (`capacity.py` defines its members), else the
empty capacity, the same bytes as `capacity_view` over no profile. `stale` is true
when any registered project's last read failed. An inbox item is every stored member
except `question`, plus `{"type": "inbox_item", "waiting_since", "stale", "read_at",
"headline", "more_questions", "answered_at"}`: `stale` is that project's failed read, `read_at`
the time of its last good read (the item's last update when the read time is unknown),
`headline` and `more_questions` come from `item_headline` (the first question of an item that
has questions and the count of the others; `UNREAD_DECISION` for a decision with none; else
the stored `question`), and `answered_at` is the record's (null while open). The stored
`question` is no wire member (a decision's is a fixed sentence). Only items of
registered projects are shown. Open tracker items are sorted by most held work first, then
`waiting_since`, then `key`; answered items are listed apart, never counted, by
`waiting_since` then `key`.

A waiting brief (a shown sprint whose `brief` is not None and whose decision is `none`) is one
entry of `inbox.open`, before every tracker item, ordered by `waiting_since` then `sprint_id`, and
counts in `inbox_items` and the headline. Its entry is

    {"type": "inbox_item", "reason": "brief", "key": "brief/<sprint id>", "project_id",
     "sprint_id", "goal", "version": <int>, "brief": {"done", "excluded", "slices", "risks",
     "asks"}, "answered": false, "waiting_since": "<time the brief was sent>"}

A stalled sprint (a shown sprint whose `stalled` is not None, `sprints.py`) is one entry of
`inbox.open`, after the briefs and before every tracker item, ordered by `waiting_since` then
`sprint_id`, and counts in `inbox_items` and the headline. Its entry is

    {"type": "inbox_item", "reason": "manager", "key": "manager/<sprint id>", "project_id",
     "sprint_id", "goal", "headline": "managers keep failing on <goal>", "last_reason": <str>,
     "answered": false, "waiting_since": "<time the sprint stalled>"}

`MANAGER_SENTENCE` says what the page offers. The sentence precedence is all out, stale, briefs, stalls,
then the existing ones. A restart or a takeover adds no item, only a stall does.

`BRIEF_SENTENCE` ("Press Enter to approve the brief, or write a reply to ask for changes.") says
what the page offers. An approved or changes-asked brief is no inbox item; only registered
projects' briefs appear, as for sprints.

A project entry is `{"type": "project", "project_id", "root", "quiet",
"open_work", "last_activity", "sprints": [<sprint entry>, ...],
"finished_sprints": null | {"label": "Finished sprints", "count": <int>,
"sprints": [<sprint entry>, ...]}, "outside_sprints": <line>}`; a group entry is
`{"type": "quiet_group", "label": "<n> quiet projects", "count": <n>,
"projects": [<project entry>]}`. `project_count` counts registered projects
only. `unmanaged` is always present, possibly empty, sorted by `root`.

    <sprint entry> = {"type": "sprint", "sprint_id", "goal",
                      "state": "drafting" | "starting" | "on_track" | "waiting" | "quiet"
                               | "closing" | "done" | "stopping" | "stopped",
                      "state_text": "<text>", "stated_at", "age_text", "manager_text": <text> | null,
                      "manager_state": "none" | "started" | "missing" | "failed" | "waiting"
                                       | "stalled" | "unavailable",
                      "manager_until": "<time>" | null, "retry": <bool>,
                      "progress": {"landed", "in_delivery", "queued", "held", "total"} | null,
                      "progress_text": "<text>" | null,
                      "status": "<status line>" | null, "status_at": "<report time>" | null,
                      "next": "<text>" | null, "milestone": "<text>" | null,
                      "tracker_url": "<url>" | null,
                      "issues": [{"issue": <int>, "stage": "<stage>", "stage_text": "<text>"}, ...],
                      "waiting": <int>,
                      "sessions": [<session entry>, ...],
                      "messages": [<message entry>, ...],
                      "reach_text": "manager not reachable" | null,
                      "stoppable": <bool>, "ended_at": "<time>" | null,
                      "stop_text": "<text>" | null,
                      "closing": null | {"at", "summary", "first_line", "differently",
                                         "landed": [<int>], "held": [<int>], "dropped": [<int>],
                                         "counts_text": "<text>"}}
    <message entry> = {"id": <int>, "kind": "approved" | "changes" | "text" | "stop",
                       "version": <int> | null, "text": <str> | null, "at": "<time>",
                       "state": "sent" | "delivered" | "read",
                       "state_text": "sent" | "delivered" | "read",
                       "read_at": "<time>" | null, "reply": <str> | null,
                       "reply_at": "<time>" | null}
    <line> = {"label": "Outside sprints", "working": <int>, "waiting": <int>,
              "summary": "<text>", "sessions": [<session entry>, ...]}
    <session entry> = {"session_id", "name", "state", "state_text", "cwd",
                       "deliveries": [<delivery entry>, ...]}
    <delivery entry> = {"run_id", "quiet": <bool>, "moved_text": "<text>",
                        "summary": "<one sentence>", "moved_at": "<ISO time>",
                        "issues": [{"issue": <int>, "stage", "stage_text"}, ...]}
    <unmanaged entry> = {"type": "unmanaged", "root": "<repo>", "name": "<name>",
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
`quiet` and `moved_text` come from `moved_text(now_ms - moved_ms)`; `summary` is the run as one
sentence, `run_summary(issues, moved_text)`: "<n> issue(s) in delivery: <count> <stage>, ...,
<moved_text>" with the stages in a fixed order and no issue number, or "No issue in delivery yet,
<moved_text>" with none; `moved_at` is the journal's last movement as an ISO UTC time, which lets
the page age the sentence's end itself. An unmanaged entry's `name` is the last segment of its `root` (the root
itself when it has none). `now_ms` is injected by the
caller (this module still reads no clock) and `None` counts as no time elapsed. The runs of an
ended or unlisted session appear nowhere, and they change no count, summary, order or the
statement. The word "stalled" is never written: a quiet run is only quiet.
`sprints` (always present, possibly empty) are the open sprints `derive_view` is given whose
`project_id` is that project, newest `stated_seq` first; a sprint of a project that is not
registered appears nowhere and changes no count, order or statement. `age_text` is
`age_text(elapsed)`, where `elapsed` is `now_ms` minus the stated time (`None` counts as no time
elapsed). A project with a shown sprint is never quiet and never folded into the quiet group.

A shown sprint reads its manager's latest report (`SprintState.report`); with none, `progress`,
`progress_text`, `status`, `status_at`, `next`, `milestone` and `tracker_url` are null,
`issues` is `[]` and `waiting` is 0. Each reported issue, ordered by number, has an effective
`stage`: the report's own when it is `landed` or `held` (an outcome the manager reported is kept
against any run), else the stage of the sprint's observation of that issue (`SprintState.observed`),
where a run's `done` reads `closed out` and any other run stage is that stage with its
`stage_text`, else the report's stage. `progress` counts the effective stages: `landed`, `held`,
`queued`, `in_delivery` (every other stage, `closed out` included) and `total`;
`progress_text` is `progress_text` of those counts. Observations come only from the sprint's fold,
never from the `deliveries` mapping: a run leaves that mapping once its final record exists, while
the fold keeps its last stage and movement, so they outlive the run. `waiting` is the number of
open inbox items of registered projects whose project is the sprint's and whose issue is one of the
report's issues or its `inbox` numbers. Movement is the latest of the approval time (`decided_at`,
else the brief's sent time), the report's time and the fold's `moved_ms`; `quiet_elapsed` is
`now_ms` minus it, computed only for an approved brief and only when `now_ms` is not None (else 0).
The state is the first that holds: `stopped_at` is set, `stopped` ("stopped by you"); `stop_at` is
set, `stopping` ("stopping"); the sprint has a closing, `done`; the brief is not approved,
`drafting` ("drafting the brief");
the report's phase is `done`, `done`; `waiting` is above 0, `waiting` ("waiting on you (<n>)");
`quiet_elapsed` reaches `QUIET_AFTER_MS`, `quiet` ("quiet for <n> min \u2014 may be stuck"); the
phase is `closing`, `closing`; no report, `starting`; else `on_track` ("on track").
`status_at` is the report's own time, which the page words against its own clock.
`ended_at` is `sprints.ended_at` for every route to done (a stop, a closing, or a latest report of
phase `done`), so the `done` state and `ended_at` never disagree; `stoppable` is true exactly when
the sprint has no stop request, is not stopped and has not ended; `stop_text` is `STOP_FAILED_TEXT`
over `stop_reason` while that is set and the sprint is not stopped, else null; `closing` lists the
closing report's issue numbers by stage, ascending, and `counts_text` is `closing_text` of their
counts.
A sprint is finished when it has ended and `now_ms` (not None) is at least `FINISHED_AFTER_MS` past
`ended_at`. Finished sprints leave `sprints` for the project's `finished_sprints` (same order;
null with none): only a sprint that is not finished makes a project active, blocks `quiet` or puts
its brief in the inbox, and a quiet project's entry still carries its `finished_sprints`. A
finished sprint's manager session renders inside it, not in `outside_sprints`.
`unstopped` (always present) lists each pending stop of a registered project that has a `reason`,
ordered by `(failed_at, sprint_id)`, with `text` `UNSTOPPED_TEXT` over that reason; `derive_view`
reads them from its `pending` argument (default none).
`manager_state`, `manager_text` and `retry` are all `sprints.manager_status` (its docstring holds
the rules, so the view and the service's retry agree) over the sprint, whether it has a listed
session of its own (below) and `now_ms`; `manager_until` is the `until` of a `waiting` manager, else
null. `derive_view(..., managers=False)` is a host that cannot start managers: every sprint is
`unavailable` with `UNAVAILABLE_TEXT` and no retry, and the view's top-level `managers` is the flag
(default true).
A listed session of the sprint's project whose name is `manager.session_name(project_id,
sprint_id)` is one of that sprint's `sessions` (ordered and shaped as in the line), not of the
project's `outside_sprints`, and is counted in none of its numbers or its summary; inside a sprint
a session waiting for an answer or a permission reads "waiting for an answer" or "waiting for a
permission".
`messages` are the `SHOWN_MESSAGES` (10) newest of the sprint's messages (`SprintState.messages`),
oldest first; `state` and `state_text` are `sprints.message_state` (the page adds no colour to
them). `reach_text` is `UNREACHABLE_TEXT` once `sprints.unreachable` holds, else null; it never
changes `retry` and never hides a message.
`recent_projects` is every registered project id, newest `last_seq` first, then `project_id`
(always present, possibly empty); it derives from the states alone.
`encode_view` writes sorted keys, compact separators, non-ASCII kept, NaN
refused, no newline.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import PurePosixPath

from agent_tools.console.capacity import EMPTY
from agent_tools.console.deliveries import (
    DONE as RUN_DONE,
    QUEUED,
    QUIET_AFTER_MS,
    DeliveryState,
    moved_text,
    run_summary,
    stage_text,
)
from agent_tools.console.event_log import Event
from agent_tools.console.manager import session_name
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
from agent_tools.console.sprints import (
    APPROVED,
    CLOSED_OUT,
    CLOSING,
    CLOSING_TEXT,
    DONE,
    DONE_TEXT,
    DRAFTING,
    DRAFTING_TEXT,
    DROPPED,
    FINISHED_AFTER_MS,
    HELD,
    LANDED,
    NONE,
    ON_TRACK,
    ON_TRACK_TEXT,
    QUIET,
    QUIET_TEXT,
    STARTING,
    STARTING_TEXT,
    STOP_FAILED_TEXT,
    STOPPED,
    STOPPED_TEXT,
    STOPPING,
    STOPPING_TEXT,
    UNSTOPPED_TEXT,
    WAITING,
    WAITING_TEXT,
    UNREACHABLE_TEXT,
    Closing,
    Message,
    PendingStop,
    SprintState,
    age_text,
    closing_text,
    ended_at,
    manager_status,
    message_state,
    progress_text,
    unreachable,
)

SHOWN_MESSAGES = 10
REGISTERED = "project.registered"
UNREGISTERED = "project.unregistered"
FOLD_AFTER = 3
HEADLINE = "Nothing needs you"
OUTSIDE_LABEL = "Outside sprints"
FINISHED_LABEL = "Finished sprints"
UNMANAGED_LABEL = "Not yet managed"

_RANK = {state: rank for rank, state in enumerate(
    (WAITING_ANSWER, WAITING_PERMISSION, WORKING, LIMIT, IDLE))}
_WAITING = (WAITING_ANSWER, WAITING_PERMISSION)
_SPRINT_STATE_TEXT = {**STATE_TEXT, WAITING_ANSWER: "waiting for an answer",
                      WAITING_PERMISSION: "waiting for a permission"}
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
BRIEF_SENTENCE = "Press Enter to approve the brief, or write a reply to ask for changes."
MANAGER_SENTENCE = "Try again to start a new manager, or withdraw the sprint."
CHOOSE_SENTENCE = "Choose an option with its number and press Enter, or answer on the tracker."
ANSWER_SENTENCE = "Answer it here, or on the tracker."
STALE_SENTENCE = ("The tracker could not be read for {projects}; "
                  "each item shows when it was last read.")
UNREAD_DECISION = "A decision waits on the tracker, but its questions could not be read."
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
    answered_at: str | None = None


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
            record = result[key]
            if event.payload.get("answered") is not True:
                answered_at = None
            elif record.item.get("answered") is True:
                answered_at = record.answered_at
            else:
                answered_at = event.at
            result[key] = replace(
                record, item=event.payload, updated_at=event.at, answered_at=answered_at)
        else:
            answered = event.payload.get("answered") is True
            result[key] = InboxRecord(
                event.payload, event.at, event.at, event.at if answered else None)
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


def repo_name(root: str) -> str:
    """A repository's name: the last segment of its path, or the path itself when it has none."""
    return PurePosixPath(root).name or root


def _delivery_entry(state: DeliveryState, now_ms: int | None) -> dict:
    quiet, text = moved_text(0 if now_ms is None else now_ms - state.moved_ms)
    return {
        "run_id": state.run_id,
        "quiet": quiet,
        "moved_text": text,
        "summary": run_summary(state.issues, text),
        "moved_at": datetime.fromtimestamp(state.moved_ms / 1000, timezone.utc).isoformat(),
        "issues": [
            {"issue": i.issue, "stage": i.stage, "stage_text": stage_text(i)}
            for i in sorted(state.issues, key=lambda i: i.issue)
        ],
    }


def _session_entry(session: SessionState,
                   deliveries: Mapping[str, Sequence[DeliveryState]],
                   now_ms: int | None,
                   texts: Mapping[str, str] = STATE_TEXT) -> dict:
    runs = sorted(deliveries.get(session.session_id, ()),
                  key=lambda d: (-d.moved_ms, d.run_id))
    return {
        "session_id": session.session_id,
        "name": session.name or session.session_id[:8],
        "state": session.state,
        "state_text": texts[session.state],
        "cwd": session.cwd,
        "deliveries": [_delivery_entry(d, now_ms) for d in runs],
    }


def _ordered(sessions: Iterable[SessionState]) -> list[SessionState]:
    return sorted(sessions, key=lambda s: (_RANK[s.state], -s.last_seq, s.session_id))


def _line(sessions: Iterable[SessionState],
          deliveries: Mapping[str, Sequence[DeliveryState]],
          now_ms: int | None) -> dict:
    ordered = _ordered(sessions)
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


def _millis(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def _effective_stages(state: SprintState) -> list[tuple[int, str, str]]:
    seen = {item.issue: item.stage for item in state.observed}
    rows = []
    for issue, stage in sorted(state.report.issues):
        run = seen.get(issue)
        if stage in (LANDED, HELD) or run is None:
            rows.append((issue, stage, stage))
        elif run.stage == RUN_DONE:
            rows.append((issue, CLOSED_OUT, CLOSED_OUT))
        else:
            rows.append((issue, run.stage, stage_text(run)))
    return rows


def sprint_waiting(state: SprintState, records: Iterable[InboxRecord]) -> int:
    """How many of `records` (open items) wait on an issue the sprint's report names."""
    report = state.report
    named = set() if report is None else {issue for issue, _ in report.issues} | set(report.inbox)
    return sum(r.item.get("issue") in named for r in records)


def sprint_state(state: SprintState, now_ms: int | None, waiting: int) -> tuple[str, str]:
    """The sprint's one shown state and its text; with `now_ms` None the sprint is never quiet."""
    brief, report = state.brief, state.report
    if state.stopped_at is not None:
        return STOPPED, STOPPED_TEXT
    if state.stop_at is not None:
        return STOPPING, STOPPING_TEXT
    if state.closing is not None:
        return DONE, DONE_TEXT
    if brief is None or brief.decision != APPROVED:
        return DRAFTING, DRAFTING_TEXT
    if report is not None and report.phase == DONE:
        return DONE, DONE_TEXT
    if waiting:
        return WAITING, WAITING_TEXT.format(n=waiting)
    quiet_elapsed = 0
    if now_ms is not None:
        moves = [_millis(brief.decided_at or brief.sent_at)]
        if report is not None:
            moves.append(_millis(report.at))
        if state.moved_ms is not None:
            moves.append(state.moved_ms)
        quiet_elapsed = now_ms - max(moves)
    if quiet_elapsed >= QUIET_AFTER_MS:
        return QUIET, QUIET_TEXT.format(minutes=quiet_elapsed // 60_000)
    if report is not None and report.phase == CLOSING:
        return CLOSING, CLOSING_TEXT
    if report is None:
        return STARTING, STARTING_TEXT
    return ON_TRACK, ON_TRACK_TEXT


def _message_entry(message: Message) -> dict:
    shown = message_state(message)
    return {"id": message.message_id, "kind": message.kind, "version": message.version,
            "text": message.text, "at": message.at, "state": shown, "state_text": shown,
            "read_at": message.read_at, "reply": message.reply, "reply_at": message.reply_at}


def _closing_entry(closing: Closing) -> dict:
    by_stage = {stage: sorted(issue for issue, row in closing.issues if row == stage)
                for stage in (LANDED, HELD, DROPPED)}
    return {"at": closing.at, "summary": closing.summary, "first_line": closing.first_line,
            "differently": closing.differently, "landed": by_stage[LANDED],
            "held": by_stage[HELD], "dropped": by_stage[DROPPED],
            "counts_text": closing_text(len(by_stage[LANDED]), len(by_stage[HELD]),
                                        len(by_stage[DROPPED]))}


def _finished(state: SprintState, now_ms: int | None) -> bool:
    ended = ended_at(state)
    return (ended is not None and now_ms is not None
            and now_ms - _millis(ended) >= FINISHED_AFTER_MS)


def _sprint_entry(state: SprintState, now_ms: int | None, managers: bool,
                  sessions: Sequence[SessionState],
                  deliveries: Mapping[str, Sequence[DeliveryState]],
                  records: Sequence[InboxRecord] = ()) -> dict:
    stated_ms = _millis(state.stated_at)
    elapsed = 0 if now_ms is None else now_ms - stated_ms
    report = state.report
    stages = [] if report is None else _effective_stages(state)
    waiting = sprint_waiting(state, records)
    counts = {
        "landed": sum(stage == LANDED for _, stage, _ in stages),
        "in_delivery": sum(stage not in (LANDED, HELD, QUEUED) for _, stage, _ in stages),
        "queued": sum(stage == QUEUED for _, stage, _ in stages),
        "held": sum(stage == HELD for _, stage, _ in stages),
        "total": len(stages),
    }
    manager_state, manager_text, retry = manager_status(state, bool(sessions), now_ms, managers)
    name, text = sprint_state(state, now_ms, waiting)
    ended = ended_at(state)
    return {
        "type": "sprint",
        "sprint_id": state.sprint_id,
        "goal": state.goal,
        "state": name,
        "state_text": text,
        "stated_at": state.stated_at,
        "age_text": age_text(elapsed),
        "manager_text": manager_text,
        "manager_state": manager_state,
        "manager_until": (state.manager.until
                          if manager_state == WAITING and state.manager is not None else None),
        "retry": retry,
        "progress": None if report is None else counts,
        "progress_text": None if report is None else progress_text(
            counts["landed"], counts["total"], counts["in_delivery"], counts["queued"],
            counts["held"]),
        "status": None if report is None else report.status,
        "status_at": None if report is None else report.at,
        "next": None if report is None else report.next_step,
        "milestone": None if report is None else report.milestone,
        "tracker_url": None if report is None else report.tracker_url,
        "issues": [{"issue": issue, "stage": stage, "stage_text": text}
                   for issue, stage, text in stages],
        "waiting": waiting,
        "sessions": [_session_entry(s, deliveries, now_ms, _SPRINT_STATE_TEXT)
                     for s in _ordered(sessions)],
        "messages": [_message_entry(m) for m in state.messages[-SHOWN_MESSAGES:]],
        "reach_text": UNREACHABLE_TEXT if unreachable(state) else None,
        "stoppable": (state.stop_at is None and state.stopped_at is None and ended is None),
        "ended_at": ended,
        "stop_text": (STOP_FAILED_TEXT.format(reason=state.stop_reason)
                      if state.stop_reason is not None and state.stopped_at is None else None),
        "closing": None if state.closing is None else _closing_entry(state.closing),
    }


def _project_entry(state: ProjectState, sessions: Sequence[SessionState],
                   deliveries: Mapping[str, Sequence[DeliveryState]],
                   now_ms: int | None,
                   sprints: Sequence[SprintState] = (),
                   managers: bool = True,
                   sprint_sessions: Mapping[str, Sequence[SessionState]] | None = None,
                   records: Sequence[InboxRecord] = (),
                   finished: Sequence[SprintState] = ()) -> dict:
    def entries(group: Sequence[SprintState]) -> list[dict]:
        return [_sprint_entry(s, now_ms, managers, (sprint_sessions or {}).get(s.sprint_id, ()),
                              deliveries, records) for s in group]

    return {
        "type": "project",
        "project_id": state.project_id,
        "root": state.root,
        "quiet": state.open_work == 0 and not sessions and not sprints,
        "open_work": state.open_work,
        "last_activity": state.last_at,
        "sprints": entries(sprints),
        "finished_sprints": (None if not finished else
                             {"label": FINISHED_LABEL, "count": len(finished),
                              "sprints": entries(finished)}),
        "outside_sprints": _line(sessions, deliveries, now_ms),
    }


def _sentence(count: int) -> str:
    if count == 0:
        return "No project is registered yet."
    noun = "project" if count == 1 else "projects"
    return f"{count} registered {noun}, and nothing is waiting on you."


def item_headline(item: Mapping) -> tuple[str, int]:
    questions = item.get("questions")
    if questions:
        return questions[0]["question"], len(questions) - 1
    if item.get("reason") == "decision":
        return UNREAD_DECISION, 0
    return item.get("question", ""), 0


def _inbox_entry(record: InboxRecord,
                 health: Mapping[str, ReadState]) -> dict:
    known = health.get(record.item["project_id"])
    stale = known is not None and not known.ok
    read_at = known.read_at if known is not None and known.read_at is not None \
        else record.updated_at
    headline, more = item_headline(record.item)
    return {**{k: v for k, v in record.item.items() if k != "question"},
            "type": "inbox_item", "waiting_since": record.waiting_since,
            "stale": stale, "read_at": read_at, "headline": headline,
            "more_questions": more, "answered_at": record.answered_at}


def _brief_entry(sprint: SprintState) -> dict:
    brief = sprint.brief
    return {"type": "inbox_item", "reason": "brief", "key": f"brief/{sprint.sprint_id}",
            "project_id": sprint.project_id, "sprint_id": sprint.sprint_id,
            "goal": sprint.goal, "version": brief.version, "brief": brief.parts,
            "answered": False, "waiting_since": brief.sent_at}


def _stall_entry(sprint: SprintState) -> dict:
    return {"type": "inbox_item", "reason": "manager", "key": f"manager/{sprint.sprint_id}",
            "project_id": sprint.project_id, "sprint_id": sprint.sprint_id, "goal": sprint.goal,
            "headline": f"managers keep failing on {sprint.goal}", "last_reason": sprint.stalled,
            "answered": False, "waiting_since": sprint.stalled_at}


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
    sprints: Mapping[str, SprintState] | None = None,
    managers: bool = True,
    pending: Mapping[str, PendingStop] | None = None,
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
    drafted: dict[str, list[SprintState]] = {}
    finished: dict[str, list[SprintState]] = {}
    for sprint in sorted((sprints or {}).values(),
                         key=lambda s: (-s.stated_seq, s.sprint_id)):
        if sprint.project_id in registered:
            kept = finished if _finished(sprint, now_ms) else drafted
            kept.setdefault(sprint.project_id, []).append(sprint)

    briefs = sorted((s for group in drafted.values() for s in group
                     if s.brief is not None and s.brief.decision == NONE),
                    key=lambda s: (s.brief.sent_at, s.sprint_id))
    stalls = sorted((s for group in drafted.values() for s in group if s.stalled is not None),
                    key=lambda s: (s.stalled_at, s.sprint_id))
    open_count = len(briefs) + len(stalls) + len(open_items)
    all_out = bool(capacity["all_out"])
    if all_out:
        sentence = ALL_OUT_SENTENCE
    elif stale_projects:
        sentence = STALE_SENTENCE.format(projects=", ".join(stale_projects))
    elif briefs:
        sentence = BRIEF_SENTENCE
    elif stalls:
        sentence = MANAGER_SENTENCE
    elif any(r.item["reason"] == "decision" and r.item["questions"] for r in open_items):
        sentence = CHOOSE_SENTENCE
    elif any(r.item.get("answers") for r in open_items):
        sentence = ANSWER_SENTENCE
    elif open_count:
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

    in_sprint: dict[str, list[SessionState]] = {}
    for project_id in sorted({*drafted, *finished}):
        for sprint in drafted.get(project_id, []) + finished.get(project_id, []):
            name = session_name(project_id, sprint.sprint_id)
            mine = [s for s in owned.get(project_id, ()) if s.name == name]
            if mine:
                in_sprint[sprint.sprint_id] = mine
                owned[project_id] = [s for s in owned[project_id] if s.name != name]

    def is_active(state: ProjectState) -> bool:
        return (state.open_work > 0 or bool(owned.get(state.project_id))
                or state.project_id in drafted)

    active = _order(s for s in states if is_active(s))
    quiet = _order(s for s in states if not is_active(s))
    open_by_project: dict[str, list[InboxRecord]] = {}
    for record in open_items:
        open_by_project.setdefault(record.item["project_id"], []).append(record)
    entries = [_project_entry(s, owned.get(s.project_id, ()), runs, now_ms,
                              drafted.get(s.project_id, ()), managers, in_sprint,
                              open_by_project.get(s.project_id, ()),
                              finished.get(s.project_id, ()))
               for s in active]
    quiet_entries = [_project_entry(s, (), runs, now_ms, (), managers, in_sprint,
                                    finished=finished.get(s.project_id, ()))
                     for s in quiet]
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
        "statement": {"inbox_items": open_count,
                      "headline": _headline(open_count, bool(stale_projects), all_out),
                      "sentence": sentence, "stale": bool(stale_projects)},
        "capacity": capacity,
        "inbox": {"open": [_brief_entry(s) for s in briefs] + [_stall_entry(s) for s in stalls]
                          + [_inbox_entry(r, health) for r in open_items],
                  "answered": [_inbox_entry(r, health) for r in answered]},
        "project_count": len(states),
        "entries": entries,
        "unmanaged": [
            {"type": "unmanaged", "root": root, "name": repo_name(root),
             "label": UNMANAGED_LABEL,
             "outside_sprints": _line(unmanaged[root], runs, now_ms)}
            for root in sorted(unmanaged)],
        "recent_projects": [s.project_id for s in _order(states)],
        "digest": dict(digest) if digest is not None else None,
        "managers": managers,
        "unstopped": [
            {"project_id": stop.project_id, "sprint_id": stop.sprint_id, "goal": stop.goal,
             "text": UNSTOPPED_TEXT.format(reason=stop.reason), "failed_at": stop.failed_at}
            for stop in sorted(
                (p for p in (pending or {}).values()
                 if p.reason is not None and p.project_id in registered),
                key=lambda p: (p.failed_at, p.sprint_id))],
    }


def encode_view(view: Mapping) -> bytes:
    return json.dumps(view, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
