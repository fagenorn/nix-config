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
- `goal.withdrawn` (`event_log.GOAL_WITHDRAWN`, `sprints.py`): the owner withdrew a sprint's goal.
- `brief.sent`, `brief.approved` (`event_log.BRIEF_SENT`, `BRIEF_APPROVED`, `sprints.py`): a
  manager's brief arrived, or the owner approved it. `brief.replied` says nothing.
- `sprint.reported` (`event_log.SPRINT_REPORTED`, `sprints.py`): a manager's report of its sprint.
  It speaks only when the sprint fold accepted it and the sprint's shown state (`view.sprint_state`,
  the open inbox items counted as the page counts them, never quiet: no clock is read) differs
  from the one before the report; a refused, ignored or state-repeating report says nothing.
- `question.answered` (`event_log.QUESTION_ANSWERED`, `sprints.py`): the owner answered a manager's
  question. It speaks only when its `differs` is `True`, so an answer that took the recommendation
  says nothing, and nothing else about a round (asking it, answering the others) speaks.

Every other kind says nothing, `goal.stated` included, delivery runs (`delivery.seen`, `delivery.gone`)
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

A session whose known name fully matches `sprints.MANAGER_SESSION_NAME` (`<project> sprint <16
lowercase hex>`, made by `manager.session_name`) makes no session moment, because what a sprint did
is said by its brief, report and withdrawal lines (#922).

Sentences (exact). `<headline>` is the first question of an item that has
questions, else the stored question (`view.item_headline`, so a decision never
reads its fixed boilerplate); `<where>` is the event's project, else the last
path segment of the session's repository (`view.repo_name`); a session with no
repository makes no moment. No sentence names an issue, a session or a path.

    inbox_appeared   <project_id> needs you: <headline>
    inbox_answered   <project_id> was answered: <headline>
    limit_stop       A session in <where> stopped on a usage limit.
    resumed          A session in <where> resumed work.
    session_ended    A session in <where> ended.
    sprint_withdrawn The goal for <project_id> was withdrawn: <goal>
    brief_sent       A brief for <project_id> arrived, version <n>: <goal>
    brief_approved   The brief for <project_id> was approved, version <n>: <goal>
    sprint_state     The sprint for <project_id> is now <the sprint's shown state>: <goal>
    answer_differs   An answer for <project_id> went against the recommendation, <recommended>: <question>

An inbox payload needs `project_id` (str), `issue` (int, not bool) and
`question` (str). A withdrawal needs the event's project (str) and a payload `goal` (str); it
reads no state, the row carries the goal. A brief event makes a moment only when its project is a
`str`, its payload `version` an `int` (not a bool) and `goal` a `str`; it reads no state either.
An answer event makes a moment only when its project is a `str`, its payload `question` and
`recommended` are `str` and `differs` is `True`; it reads no state either. A sprint report is judged against the folded sprints before it
(`moments` folds its own copy of the optional `sprints` argument with
`sprints.sprint_states`), and the sentence's goal is the sprint's.

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

from agent_tools.console.event_log import (
    BRIEF_APPROVED, BRIEF_SENT, GOAL_WITHDRAWN, QUESTION_ANSWERED, SPRINT_REPORTED, Event)
from agent_tools.console.sessions import (
    ENDED, GONE, HOOK, LIMIT, SEEN, WORKING, SessionState, session_states)
from agent_tools.console.sprints import MANAGER_SESSION_NAME, SprintState, sprint_states
from agent_tools.console.view import (
    INBOX_CHANGED, INBOX_SEEN, InboxRecord, inbox_records, item_headline, repo_name,
    sprint_state, sprint_waiting)

LOOKED = "page.looked"
FIRST_VISIT = timedelta(hours=8)
SHOWN = 5
EARLIER_MAX = 50

INBOX_APPEARED = "inbox_appeared"
INBOX_ANSWERED = "inbox_answered"
LIMIT_STOP = "limit_stop"
RESUMED = "resumed"
SESSION_ENDED = "session_ended"
SPRINT_WITHDRAWN = "sprint_withdrawn"
BRIEF_SENT_MOMENT = "brief_sent"
BRIEF_APPROVED_MOMENT = "brief_approved"
SPRINT_STATE_MOMENT = "sprint_state"
ANSWER_DIFFERS = "answer_differs"


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
    if isinstance(session.name, str) and MANAGER_SESSION_NAME.fullmatch(session.name):
        return None
    if session.repo is None:
        return None
    where = event.project or repo_name(session.repo)
    words = {LIMIT_STOP: "stopped on a usage limit", RESUMED: "resumed work",
             SESSION_ENDED: "ended"}[kind]
    return kind, f"A session in {where} {words}."


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
    project_id = fields[0]
    headline = item_headline(event.payload)[0]
    answered = event.payload.get("answered")
    if event.kind == INBOX_SEEN and answered is False:
        return INBOX_APPEARED, f"{project_id} needs you: {headline}"
    if event.kind == INBOX_SEEN and answered is True:
        return INBOX_ANSWERED, f"{project_id} was answered: {headline}"
    if (event.kind == INBOX_CHANGED and answered is True and before is not None
            and before.item.get("answered") is False):
        return INBOX_ANSWERED, f"{project_id} was answered: {headline}"
    return None


def _brief_moment(event: Event) -> tuple[str, str] | None:
    version, goal = event.payload.get("version"), event.payload.get("goal")
    if (not isinstance(event.project, str) or not isinstance(version, int)
            or isinstance(version, bool) or not isinstance(goal, str)):
        return None
    if event.kind == BRIEF_SENT:
        return (BRIEF_SENT_MOMENT,
                f"A brief for {event.project} arrived, version {version}: {goal}")
    return (BRIEF_APPROVED_MOMENT,
            f"The brief for {event.project} was approved, version {version}: {goal}")


def _answer_moment(event: Event) -> tuple[str, str] | None:
    question, recommended = event.payload.get("question"), event.payload.get("recommended")
    if (not isinstance(event.project, str) or not isinstance(question, str)
            or not isinstance(recommended, str) or event.payload.get("differs") is not True):
        return None
    return (ANSWER_DIFFERS, f"An answer for {event.project} went against the recommendation, "
                            f"{recommended}: {question}")


def _report_moment(event: Event, before: Mapping[str, SprintState],
                   after: Mapping[str, SprintState],
                   records: Mapping[tuple[str, str], InboxRecord]) -> tuple[str, str] | None:
    sprint_id = event.payload.get("sprint_id")
    if not isinstance(sprint_id, str) or sprint_id not in after or sprint_id not in before:
        return None
    old, new = before[sprint_id], after[sprint_id]
    if new.report is None:
        return None
    open_items = [r for r in records.values()
                  if r.item.get("project_id") == new.project_id and not r.item.get("answered")]
    waiting = sprint_waiting(new, open_items)
    # The clock is not read here, so a sprint going quiet is never a change of state.
    was = sprint_state(old, None, sprint_waiting(old, open_items))
    now = sprint_state(new, None, waiting)
    if was[0] == now[0]:
        return None
    return (SPRINT_STATE_MOMENT,
            f"The sprint for {event.project} is now {now[1]}: {new.goal}")


def moments(
    events: Iterable[Event],
    sessions: Mapping[str, SessionState],
    records: Mapping[tuple[str, str], InboxRecord],
    sprints: Mapping[str, SprintState] | None = None,
) -> list[Moment]:
    states, held, folded = dict(sessions), dict(records), dict(sprints or {})
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
        elif event.kind in (BRIEF_SENT, BRIEF_APPROVED):
            said = _brief_moment(event)
        elif event.kind == QUESTION_ANSWERED:
            said = _answer_moment(event)
        elif event.kind == GOAL_WITHDRAWN:
            goal = payload.get("goal") if isinstance(payload, dict) else None
            if isinstance(event.project, str) and isinstance(goal, str):
                said = (SPRINT_WITHDRAWN,
                        f"The goal for {event.project} was withdrawn: {goal}")
        previous, folded = folded, sprint_states([event], folded)
        if event.kind == SPRINT_REPORTED:
            said = _report_moment(event, previous, folded, held)
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
