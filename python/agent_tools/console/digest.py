"""The console's digest (#861): what changed since the owner last looked, in plain sentences.

Pure: nothing here reads a clock, a file or the environment. `now` and the
previous state are arguments.

Event kinds read:

- `page.looked` (`LOOKED`, project null, payload `{}`): one look at the page. The
  last one, by its `at`, is the last look (`last_looked`).
- `session.hook`, `session.seen`, `session.gone` (`sessions.py`): a session's
  state changes.
- `inbox.seen`, `inbox.changed` (`view.py`, `inbox.py`): an item appears or is
  answered.

Every other kind says nothing, delivery runs (`delivery.seen`, `delivery.gone`)
included: the console has no delivery moments yet, and #878 adds them from
those rows. An event whose payload lacks a required member says nothing.

A moment is made once, when its event is folded, against the session and inbox
state before that event (`moments`), so the same events always give the same
moments. Transitions:

- `limit_stop`: the state after is `limit` and the state before was not;
- `resumed`: the state before was `limit` and the state after is `working`;
- `session_ended`: the state after is `ended` and the session was known and not
  ended, or a `session.gone` of a known session that was not ended (an ended
  session that then goes says it once);
- `inbox_appeared`: `inbox.seen` with `answered` false;
- `inbox_answered`: `inbox.seen` with `answered` true, or `inbox.changed` from a
  known unanswered record to `answered` true. Anything else about the inbox says
  nothing.

Sentences (exact). `<name>` is the session's name, else the first 8 characters
of its id; `<where>` is the event's project, else the session's repository; a
session with no repository makes no moment.

    inbox_appeared   <project_id> #<issue> needs you: <question>
    inbox_answered   <project_id> #<issue> was answered.
    limit_stop       <name> stopped on a usage limit in <where>.
    resumed          <name> resumed work in <where>.
    session_ended    <name> ended in <where>.

An inbox payload needs `project_id` (str), `issue` (int, not bool) and
`question` (str).

The window (`window_start`, `keep`): moments strictly after the last look, so a
moment exactly at the look is not shown; with no look stored (a first visit),
strictly after `now` minus `FIRST_VISIT`. Times are compared as parsed
datetimes.

The wire object (`digest`):

    {"since": <last look> | null, "first_visit": <bool>,
     "recent": [<moment>], "earlier": [<moment>], "omitted": <int>}

with `<moment> = {"at", "kind", "sentence"}`, newest first by `(at, seq)`.
`recent` holds at most `SHOWN`, `earlier` the next at most `EARLIER_MAX`, and
`omitted` counts the rest; `since` is null on a first visit, so the clock alone
never changes the object except when a moment leaves a first-visit window.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from agent_tools.console.event_log import Event
from agent_tools.console.sessions import (
    ENDED, GONE, HOOK, LIMIT, SEEN, WORKING, SessionState, session_states)
from agent_tools.console.view import INBOX_CHANGED, INBOX_SEEN, InboxRecord, inbox_records

LOOKED = "page.looked"
FIRST_VISIT = timedelta(hours=8)
SHOWN = 5
EARLIER_MAX = 50

INBOX_APPEARED = "inbox_appeared"
INBOX_ANSWERED = "inbox_answered"
LIMIT_STOP = "limit_stop"
RESUMED = "resumed"
SESSION_ENDED = "session_ended"


@dataclass(frozen=True)
class Moment:
    seq: int
    at: str
    kind: str
    sentence: str


def last_looked(events: Iterable[Event], previous: str | None = None) -> str | None:
    result = previous
    for event in events:
        if event.kind == LOOKED:
            result = event.at
    return result


def _time(at: str) -> datetime:
    return datetime.fromisoformat(at)


def _session_moment(event: Event, before: SessionState | None,
                    after: SessionState | None) -> tuple[str, str] | None:
    if event.kind == GONE:
        if before is None or before.state == ENDED:
            return None
        kind, session = SESSION_ENDED, before
    elif after is None:
        return None
    else:
        known = before is not None
        if after.state == LIMIT and not (known and before.state == LIMIT):
            kind = LIMIT_STOP
        elif known and before.state == LIMIT and after.state == WORKING:
            kind = RESUMED
        elif after.state == ENDED and known and before.state != ENDED:
            kind = SESSION_ENDED
        else:
            return None
        session = after
    if session.repo is None:
        return None
    name = session.name or session.session_id[:8]
    where = event.project or session.repo
    words = {LIMIT_STOP: "stopped on a usage limit in", RESUMED: "resumed work in",
             SESSION_ENDED: "ended in"}[kind]
    return kind, f"{name} {words} {where}."


def _inbox_fields(payload: object) -> tuple[str, int, str] | None:
    if not isinstance(payload, dict):
        return None
    project_id, issue, question = (
        payload.get("project_id"), payload.get("issue"), payload.get("question"))
    if (not isinstance(project_id, str) or not isinstance(issue, int)
            or isinstance(issue, bool) or not isinstance(question, str)):
        return None
    return project_id, issue, question


def _inbox_moment(event: Event, before: InboxRecord | None) -> tuple[str, str] | None:
    fields = _inbox_fields(event.payload)
    if fields is None:
        return None
    project_id, issue, question = fields
    answered = event.payload.get("answered")
    if event.kind == INBOX_SEEN and answered is False:
        return INBOX_APPEARED, f"{project_id} #{issue} needs you: {question}"
    if event.kind == INBOX_SEEN and answered is True:
        return INBOX_ANSWERED, f"{project_id} #{issue} was answered."
    if (event.kind == INBOX_CHANGED and answered is True and before is not None
            and before.item.get("answered") is False):
        return INBOX_ANSWERED, f"{project_id} #{issue} was answered."
    return None


def moments(
    events: Iterable[Event],
    sessions: Mapping[str, SessionState],
    records: Mapping[tuple[str, str], InboxRecord],
) -> list[Moment]:
    states, held = dict(sessions), dict(records)
    found = []
    for event in events:
        said = None
        payload = event.payload
        if event.kind in (HOOK, SEEN, GONE):
            session_id = payload.get("session_id") if isinstance(payload, dict) else None
            before = states.get(session_id) if isinstance(session_id, str) else None
            states = session_states([event], states)
            after = states.get(session_id) if isinstance(session_id, str) else None
            said = _session_moment(event, before, after)
        elif event.kind in (INBOX_SEEN, INBOX_CHANGED):
            key = payload.get("key") if isinstance(payload, dict) else None
            before = held.get((event.project, key))
            held = inbox_records([event], held)
            said = _inbox_moment(event, before)
        if said is not None:
            found.append(Moment(event.seq, event.at, said[0], said[1]))
    return found


def window_start(last: str | None, now: datetime) -> str:
    if last is not None:
        return last
    return (now - FIRST_VISIT).astimezone(timezone.utc).isoformat(timespec="microseconds")


def keep(moments: Iterable[Moment], start: str) -> list[Moment]:
    begin = _time(start)
    return [m for m in moments if _time(m.at) > begin]


def _wire(moment: Moment) -> dict:
    return {"at": moment.at, "kind": moment.kind, "sentence": moment.sentence}


def digest(moments: Iterable[Moment], last: str | None, now: datetime) -> dict:
    shown = sorted(keep(moments, window_start(last, now)),
                   key=lambda m: (_time(m.at), m.seq), reverse=True)
    return {
        "since": last,
        "first_visit": last is None,
        "recent": [_wire(m) for m in shown[:SHOWN]],
        "earlier": [_wire(m) for m in shown[SHOWN:SHOWN + EARLIER_MAX]],
        "omitted": max(0, len(shown) - SHOWN - EARLIER_MAX),
    }
