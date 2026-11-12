"""The console's sprints (#886, #887): a goal the owner states on the page, kept until it is withdrawn, and the brief a manager sends for it.

Five event kinds carry a sprint (`event_log.GOAL_STATED`, `GOAL_WITHDRAWN`, `BRIEF_SENT`,
`BRIEF_APPROVED`, `BRIEF_REPLIED`). All put the project id in the event's project column. A goal
row carries `{"sprint_id": <id>, "goal": <text>}` (a withdrawal repeats the stated text); the brief
rows carry

    brief.sent      {"sprint_id", "version": <int>, "goal": <str>, "brief": {<the five parts>}}
    brief.approved  {"sprint_id", "version": <int>, "goal": <str>}
    brief.replied   {"sprint_id", "version": <int>, "goal": <str>, "reply": <str>}

The log keeps all five indefinitely (`event_log.KEPT_KINDS`).

Three more kinds record the sprint's manager (#888), none of them kept (`event_log.MANAGER_STARTED`,
`MANAGER_FAILED`, `MANAGER_WAITING`; each with the project in its project column):

    manager.started  {"sprint_id", "profile": <str>, "session_name": <str>}
    manager.failed   {"sprint_id", "reason": <str>}
    manager.waiting  {"sprint_id", "until": <str> | null}

A sprint id is `secrets.token_hex(8)`: 16 lowercase hex characters (`SPRINT_ID`), the only form a
request may name and the file name of the sprint's secret.

The sprint's secret is `secrets.token_urlsafe(32)` plus one newline in
`<directory>/sprint-secrets/<sprint id>` (`SECRETS_DIR` beside the event log), the directory created
0700 and the file created once, 0600, with `O_EXCL`. Only `read_secret(directory, sprint_id)` reads it back, for the service's
check of a manager's secret: it validates the id (`ValueError` otherwise), returns the file text
with one trailing newline removed and `None` when the file does not exist; any other `OSError`
propagates. The secret appears in no row, view, stream frame, answer or stderr line.

The goal is the sent text with `str.strip()` applied (`checked_goal`). The refusals, in the order the
service applies them: `UNREGISTERED` (the service's check, not made here), `EMPTY` after stripping,
`TOO_LONG` over `MAX_GOAL_CHARS` code points after stripping. The stored goal is the stripped text.
`Refused` carries the one-line reason as `str(error)`.

`parse_goal(body)` reads the body of the goal write and returns `(project_id, goal)`; the goal may
be empty so the service can give the plain reason:

    {"project_id": "<project id>", "goal": "<text>"}

`parse_withdraw(body)` reads the body of the withdraw write and returns `(project_id, sprint_id)`:

    {"project_id": "<project id>", "sprint_id": "<16 lowercase hex>"}

`parse_retry(body)` reads the body of the manager retry write, the same shape as the withdraw's, and
returns `(project_id, sprint_id)`. `HAS_MANAGER`, `LAUNCHING` and `TOO_SOON` are the service's
retry refusals.

Both accept only a UTF-8 JSON object with exactly those keys; anything else, a repeated key, a
NaN or Infinity literal or nesting too deep to parse raises `ValueError`.

`sprint_states(events, states=None)` folds events into the open sprints keyed by sprint id: a
`goal.stated` event with a project, a string `sprint_id` and a string `goal` adds a `SprintState`
(`stated_seq` and `stated_at` are the event's `seq` and `at`); a `goal.withdrawn` with a string
`sprint_id` removes it; the brief rows and the manager rows below change an open sprint; every other
event and any malformed goal event changes nothing.
Registration events change nothing here: a goal row outlives the registration rows retention
removes, and the view alone shows sprints only under registered projects. Folding `a + b` equals
folding `b` onto the fold of `a`.

A brief is the five `PARTS`: `done` a text, `excluded`, `slices`, `risks` and `asks` each a list of
texts. `checked_brief(brief)` checks them in `PARTS` order and refuses with
`Refused("the brief has no <part>")` the first that is missing, of the wrong type or empty after
stripping; it returns a new dict of the five parts with every text stripped. `checked_reply(text)`
keeps the text exactly and refuses `EMPTY_REPLY` when its strip is empty, then `REPLY_TOO_LONG` over
`MAX_REPLY_CHARS` code points. `SecretRefused` (a `Refused`) is the service's refusal of a wrong
secret; it maps to 403.

`parse_brief_request(body)` reads the manager's body and returns `(sprint_id, secret, brief)`:

    {"sprint_id": "<16 lowercase hex>", "secret": "<string>", "brief": {<any subset of PARTS>}}

`parse_approve(body)` returns `(project_id, sprint_id, version)` and `parse_reply(body)` returns
`(project_id, sprint_id, version, reply)` from the page's bodies:

    {"project_id": "<project id>", "sprint_id": "<16 hex>", "version": <int >= 1, not a bool>}
    ... plus "reply": "<string>" for a reply

All three readers are as strict as the goal ones; an unknown brief key is a `ValueError`, a missing
one is not (the service answers it with the part).

The fold also keeps each open sprint's `Brief(version, parts, sent_at, decision, reply)`.
`brief.sent` changes an open sprint only when `version` is an int (not a bool) greater than the
folded brief's version (0 with none) and `brief` is a dict: the brief is then that version with
decision `NONE` and no reply. `brief.approved` and `brief.replied` apply only when the sprint is
open, has a brief, the version equals its version and its decision is `NONE`; approval sets
`APPROVED`, a reply (a string) sets `CHANGES` and the reply. A sprint whose brief is `APPROVED` is
`STARTING`, else `DRAFTING` (`SprintState.state`).

The fold also keeps each open sprint's `Manager(state, at, profile, session_name, reason, until)`,
`None` until a valid manager row arrives. A manager row changes only an open sprint (a row for a
sprint that is not folded changes nothing) and the latest valid row wins, whatever the earlier one
was; `Manager.at` is that row's `at`. `manager.started` is valid only with a string `profile` and a
string `session_name` (state `started`); `manager.failed` only with a string `reason` (`failed`);
`manager.waiting` only with an `until` key whose value is a string or null (`waiting`). A row that
is not valid changes nothing.

`manager_status(state, listed, now_ms, managers)` turns a sprint's manager into the view's
`(manager_state, manager_text, retry)`; its docstring holds the rules.

The view's `manager_state`, `manager_text` and `retry`, and the service's retry gate, are this
function's three results.

`withdrawn_ids(events, ids)` adds the `sprint_id` of every `goal.withdrawn` row with a string one.

`age_text(elapsed_ms)` is `stated just now` under a minute, `stated <m> min ago` under an hour,
`stated <h> h ago` under a day, else `stated 1 day ago` or `stated <d> days ago`; a negative count is
0. The module reads no clock and no environment; only the secret helpers touch the filesystem.
"""

import json
import os
import re
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console.event_log import (BRIEF_APPROVED, BRIEF_REPLIED, BRIEF_SENT, GOAL_STATED,
                                           GOAL_WITHDRAWN, MANAGER_FAILED, MANAGER_STARTED,
                                           MANAGER_WAITING, Event)
from agent_tools.console.manager import (FAILED_TEXT, MISSING_TEXT, UNAVAILABLE_TEXT,
                                         WAITING_TEXT)

MAX_GOAL_CHARS = 2000
MAX_REPLY_CHARS = 2000
PARTS = ("done", "excluded", "slices", "risks", "asks")
NONE = "none"
APPROVED = "approved"
CHANGES = "changes"
WITHDRAWN = "withdrawn"
STARTING = "starting"
STARTING_TEXT = "starting"
NO_MANAGER_AFTER_MS = 120_000
DRAFTING = "drafting"
DRAFTING_TEXT = "drafting the brief"
NO_MANAGER_TEXT = "no manager has picked this up"
STARTED = "started"
FAILED = "failed"
WAITING = "waiting"
MISSING = "missing"
UNAVAILABLE = "unavailable"
SECRETS_DIR = "sprint-secrets"
SPRINT_ID = re.compile(r"[0-9a-f]{16}")

UNREGISTERED = "this project is not registered"
EMPTY = "write the goal first"
TOO_LONG = "a goal is at most 2000 characters"
NOT_OPEN = "this sprint is not open"
SECRET_REFUSED = "secret refused"
MISSING_PART = "the brief has no {part}"
NOT_WAITING = "this brief is not waiting for you"
REPLACED = "a newer brief replaced this one"
EMPTY_REPLY = "write the reply first"
REPLY_TOO_LONG = "a reply is at most 2000 characters"
UNKNOWN = "this sprint is not known"
HAS_MANAGER = "this sprint has a manager"
LAUNCHING = "a manager is starting for this sprint"
TOO_SOON = "retry is offered two minutes after the goal"

_MINUTE_MS = 60_000
_HOUR_MS = 3_600_000
_DAY_MS = 86_400_000


class Refused(Exception):
    """The write was not made; `str(error)` is the one-line reason."""


class SecretRefused(Refused):
    """The sprint's secret was wrong; the service answers 403."""


@dataclass(frozen=True)
class Brief:
    version: int
    parts: dict
    sent_at: str
    decision: str
    reply: str | None


@dataclass(frozen=True)
class Manager:
    state: str
    at: str
    profile: str | None = None
    session_name: str | None = None
    reason: str | None = None
    until: str | None = None


@dataclass(frozen=True)
class SprintState:
    sprint_id: str
    project_id: str
    goal: str
    stated_seq: int
    stated_at: str
    brief: Brief | None = None
    manager: Manager | None = None

    @property
    def state(self) -> str:
        if self.brief is not None and self.brief.decision == APPROVED:
            return STARTING
        return DRAFTING


def _object(body: bytes, keys: set[str], project: bool = True) -> dict:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the body is nested too deeply") from error
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"the body must be an object of {', '.join(sorted(keys))}")
    if project:
        project_id = value["project_id"]
        if not isinstance(project_id, str) or not project_id:
            raise ValueError("project_id must be a non-empty string")
    return value


def _sprint_id(value: object) -> str:
    if not isinstance(value, str) or SPRINT_ID.fullmatch(value) is None:
        raise ValueError("sprint_id must be 16 lowercase hex characters")
    return value


def _version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("version must be an integer of at least 1")
    return value


def parse_goal(body: bytes) -> tuple[str, str]:
    value = _object(body, {"project_id", "goal"})
    if not isinstance(value["goal"], str):
        raise ValueError("goal must be a string")
    return value["project_id"], value["goal"]


def parse_withdraw(body: bytes) -> tuple[str, str]:
    value = _object(body, {"project_id", "sprint_id"})
    return value["project_id"], _sprint_id(value["sprint_id"])


def parse_retry(body: bytes) -> tuple[str, str]:
    value = _object(body, {"project_id", "sprint_id"})
    return value["project_id"], _sprint_id(value["sprint_id"])


def parse_brief_request(body: bytes) -> tuple[str, str, dict]:
    value = _object(body, {"sprint_id", "secret", "brief"}, project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    brief = value["brief"]
    if not isinstance(brief, dict) or not set(brief) <= set(PARTS):
        raise ValueError(f"brief must be an object of {', '.join(PARTS)}")
    return sprint_id, value["secret"], brief


def parse_approve(body: bytes) -> tuple[str, str, int]:
    value = _object(body, {"project_id", "sprint_id", "version"})
    return value["project_id"], _sprint_id(value["sprint_id"]), _version(value["version"])


def parse_reply(body: bytes) -> tuple[str, str, int, str]:
    value = _object(body, {"project_id", "sprint_id", "version", "reply"})
    if not isinstance(value["reply"], str):
        raise ValueError("reply must be a string")
    return (value["project_id"], _sprint_id(value["sprint_id"]), _version(value["version"]),
            value["reply"])


def checked_goal(text: str) -> str:
    goal = text.strip()
    if not goal:
        raise Refused(EMPTY)
    if len(goal) > MAX_GOAL_CHARS:
        raise Refused(TOO_LONG)
    return goal


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def checked_brief(brief: dict) -> dict:
    checked: dict = {}
    for part in PARTS:
        value = brief.get(part)
        if part == "done":
            if not _text(value):
                raise Refused(MISSING_PART.format(part=part))
            checked[part] = value.strip()
        else:
            if not isinstance(value, list) or not value or not all(_text(item) for item in value):
                raise Refused(MISSING_PART.format(part=part))
            checked[part] = [item.strip() for item in value]
    return checked


def checked_reply(text: str) -> str:
    if not text.strip():
        raise Refused(EMPTY_REPLY)
    if len(text) > MAX_REPLY_CHARS:
        raise Refused(REPLY_TOO_LONG)
    return text


def _folded_brief(state: SprintState, event: Event) -> SprintState:
    payload = event.payload
    version = payload.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        return state
    brief = state.brief
    if event.kind == BRIEF_SENT:
        parts = payload.get("brief")
        if isinstance(parts, dict) and version > (brief.version if brief else 0):
            return replace(state, brief=Brief(version, parts, event.at, NONE, None))
        return state
    if brief is None or version != brief.version or brief.decision != NONE:
        return state
    if event.kind == BRIEF_APPROVED:
        return replace(state, brief=replace(brief, decision=APPROVED))
    reply = payload.get("reply")
    if isinstance(reply, str):
        return replace(state, brief=replace(brief, decision=CHANGES, reply=reply))
    return state


def _folded_manager(state: SprintState, event: Event) -> SprintState:
    payload = event.payload
    if event.kind == MANAGER_STARTED:
        profile, name = payload.get("profile"), payload.get("session_name")
        if isinstance(profile, str) and isinstance(name, str):
            return replace(state, manager=Manager(STARTED, event.at, profile, name))
    elif event.kind == MANAGER_FAILED:
        reason = payload.get("reason")
        if isinstance(reason, str):
            return replace(state, manager=Manager(FAILED, event.at, reason=reason))
    elif event.kind == MANAGER_WAITING and "until" in payload:
        until = payload["until"]
        if until is None or isinstance(until, str):
            return replace(state, manager=Manager(WAITING, event.at, until=until))
    return state


def sprint_states(events: Iterable[Event],
                  states: Mapping[str, SprintState] | None = None) -> dict[str, SprintState]:
    folded = dict(states or {})
    for event in events:
        sprint_id = event.payload.get("sprint_id")
        if not isinstance(sprint_id, str):
            continue
        if event.kind == GOAL_STATED:
            goal = event.payload.get("goal")
            if event.project is not None and isinstance(goal, str):
                folded[sprint_id] = SprintState(sprint_id, event.project, goal, event.seq,
                                                event.at)
        elif event.kind == GOAL_WITHDRAWN:
            folded.pop(sprint_id, None)
        elif event.kind in (BRIEF_SENT, BRIEF_APPROVED, BRIEF_REPLIED) and sprint_id in folded:
            folded[sprint_id] = _folded_brief(folded[sprint_id], event)
        elif event.kind in (MANAGER_STARTED, MANAGER_FAILED, MANAGER_WAITING) \
                and sprint_id in folded:
            folded[sprint_id] = _folded_manager(folded[sprint_id], event)
    return folded


def withdrawn_ids(events: Iterable[Event], ids: frozenset[str] = frozenset()) -> frozenset[str]:
    withdrawn = set(ids)
    for event in events:
        sprint_id = event.payload.get("sprint_id")
        if event.kind == GOAL_WITHDRAWN and isinstance(sprint_id, str):
            withdrawn.add(sprint_id)
    return frozenset(withdrawn)


def age_text(elapsed_ms: int) -> str:
    elapsed = max(elapsed_ms, 0)
    if elapsed < _MINUTE_MS:
        return "stated just now"
    if elapsed < _HOUR_MS:
        return f"stated {elapsed // _MINUTE_MS} min ago"
    if elapsed < _DAY_MS:
        return f"stated {elapsed // _HOUR_MS} h ago"
    days = elapsed // _DAY_MS
    return "stated 1 day ago" if days == 1 else f"stated {days} days ago"


def _ms(time: str) -> int:
    return int(datetime.fromisoformat(time).timestamp() * 1000)


def manager_status(state: SprintState, listed: bool, now_ms: int | None,
                   managers: bool) -> tuple[str, str | None, bool]:
    """Return `(manager_state, manager_text, retry)` for one open sprint.

    `listed` is whether the sprint has a listed session of its own and `now_ms` is the clock in
    milliseconds (`None` counts as no time elapsed). The rules, first match wins:

    - `managers` false (a host that cannot start managers): `unavailable`, `UNAVAILABLE_TEXT`, no
      retry.
    - The sprint is overdue when `now_ms` is more than `NO_MANAGER_AFTER_MS` past its start time, it
      has no brief and it has no listed session. The start time is `Manager.at` of a `started`
      manager and the stated time (`stated_at`) otherwise.
    - No manager row: `none`, with `NO_MANAGER_TEXT` and retry when overdue, else no text, no retry.
    - `started`: `missing`, `MISSING_TEXT` and retry when overdue, else `started`, no text, no retry.
    - `failed`: `failed`, `"<FAILED_TEXT>: <reason>"` and retry.
    - `waiting`: `waiting`, `WAITING_TEXT` and retry.
    """
    if not managers:
        return UNAVAILABLE, UNAVAILABLE_TEXT, False
    manager = state.manager
    since = state.stated_at if manager is None or manager.state != STARTED else manager.at
    overdue = (now_ms is not None and now_ms - _ms(since) > NO_MANAGER_AFTER_MS
               and state.brief is None and not listed)
    if manager is None:
        return (NONE, NO_MANAGER_TEXT, True) if overdue else (NONE, None, False)
    if manager.state == STARTED:
        return (MISSING, MISSING_TEXT, True) if overdue else (STARTED, None, False)
    if manager.state == FAILED:
        return FAILED, f"{FAILED_TEXT}: {manager.reason}", True
    return WAITING, WAITING_TEXT, True


def new_sprint_id() -> str:
    return secrets.token_hex(8)


def _checked_id(sprint_id: str) -> None:
    if SPRINT_ID.fullmatch(sprint_id) is None:
        raise ValueError("sprint_id must be 16 lowercase hex characters")


def create_secret(directory: Path, sprint_id: str) -> Path:
    _checked_id(sprint_id)
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / sprint_id
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(secrets.token_urlsafe(32) + "\n")
    return path


def remove_secret(directory: Path, sprint_id: str) -> None:
    _checked_id(sprint_id)
    (Path(directory) / sprint_id).unlink(missing_ok=True)


def read_secret(directory: Path, sprint_id: str) -> str | None:
    _checked_id(sprint_id)
    try:
        text = (Path(directory) / sprint_id).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return text.removesuffix("\n")
