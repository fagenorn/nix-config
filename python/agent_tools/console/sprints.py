"""The console's sprints (#886): a goal the owner states on the page, kept until it is withdrawn.

Two event kinds carry a sprint (`event_log.GOAL_STATED`, `event_log.GOAL_WITHDRAWN`). Both put the
project id in the event's project column and carry the payload `{"sprint_id": <id>, "goal": <text>}`
(a withdrawal repeats the stated text). The log keeps both indefinitely (`event_log.KEPT_KINDS`).

A sprint id is `secrets.token_hex(8)`: 16 lowercase hex characters (`SPRINT_ID`), the only form a
request may name and the file name of the sprint's secret.

The sprint's secret is `secrets.token_urlsafe(32)` plus one newline in
`<directory>/sprint-secrets/<sprint id>` (`SECRETS_DIR` beside the event log), the directory created
0700 and the file created once, 0600, with `O_EXCL`. This slice never reads it back: it appears in
no row, view, stream frame, answer or stderr line.

The goal is the sent text with `str.strip()` applied (`checked_goal`). The refusals, in the order the
service applies them: `UNREGISTERED` (the service's check, not made here), `EMPTY` after stripping,
`TOO_LONG` over `MAX_GOAL_CHARS` code points after stripping. The stored goal is the stripped text.
`Refused` carries the one-line reason as `str(error)`.

`parse_goal(body)` reads the body of the goal write and returns `(project_id, goal)`; the goal may
be empty so the service can give the plain reason:

    {"project_id": "<project id>", "goal": "<text>"}

`parse_withdraw(body)` reads the body of the withdraw write and returns `(project_id, sprint_id)`:

    {"project_id": "<project id>", "sprint_id": "<16 lowercase hex>"}

Both accept only a UTF-8 JSON object with exactly those keys; anything else, a repeated key, a
NaN or Infinity literal or nesting too deep to parse raises `ValueError`.

`sprint_states(events, states=None)` folds events into the open sprints keyed by sprint id: a
`goal.stated` event with a project, a string `sprint_id` and a string `goal` adds a `SprintState`
(`stated_seq` and `stated_at` are the event's `seq` and `at`); a `goal.withdrawn` with a string
`sprint_id` removes it; every other event and any malformed goal event changes nothing.
Registration events change nothing here: a goal row outlives the registration rows retention
removes, and the view alone shows sprints only under registered projects. Folding `a + b` equals
folding `b` onto the fold of `a`.

`age_text(elapsed_ms)` is `stated just now` under a minute, `stated <m> min ago` under an hour,
`stated <h> h ago` under a day, else `stated 1 day ago` or `stated <d> days ago`; a negative count is
0. The module reads no clock and no environment; only the two secret helpers touch the filesystem.
"""

import json
import os
import re
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console.event_log import GOAL_STATED, GOAL_WITHDRAWN, Event

MAX_GOAL_CHARS = 2000
NO_MANAGER_AFTER_MS = 120_000
DRAFTING = "drafting"
DRAFTING_TEXT = "drafting the brief"
NO_MANAGER_TEXT = "no manager has picked this up"
SECRETS_DIR = "sprint-secrets"
SPRINT_ID = re.compile(r"[0-9a-f]{16}")

UNREGISTERED = "this project is not registered"
EMPTY = "write the goal first"
TOO_LONG = "a goal is at most 2000 characters"
NOT_OPEN = "this sprint is not open"

_MINUTE_MS = 60_000
_HOUR_MS = 3_600_000
_DAY_MS = 86_400_000


class Refused(Exception):
    """The write was not made; `str(error)` is the one-line reason."""


@dataclass(frozen=True)
class SprintState:
    sprint_id: str
    project_id: str
    goal: str
    stated_seq: int
    stated_at: str


def _object(body: bytes, keys: set[str]) -> dict:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the body is nested too deeply") from error
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"the body must be an object of {', '.join(sorted(keys))}")
    project_id = value["project_id"]
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id must be a non-empty string")
    return value


def parse_goal(body: bytes) -> tuple[str, str]:
    value = _object(body, {"project_id", "goal"})
    if not isinstance(value["goal"], str):
        raise ValueError("goal must be a string")
    return value["project_id"], value["goal"]


def parse_withdraw(body: bytes) -> tuple[str, str]:
    value = _object(body, {"project_id", "sprint_id"})
    sprint_id = value["sprint_id"]
    if not isinstance(sprint_id, str) or SPRINT_ID.fullmatch(sprint_id) is None:
        raise ValueError("sprint_id must be 16 lowercase hex characters")
    return value["project_id"], sprint_id


def checked_goal(text: str) -> str:
    goal = text.strip()
    if not goal:
        raise Refused(EMPTY)
    if len(goal) > MAX_GOAL_CHARS:
        raise Refused(TOO_LONG)
    return goal


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
    return folded


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
