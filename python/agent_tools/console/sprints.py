"""The console's sprints (#886, #887): a goal the owner states on the page, kept until it is withdrawn, and the brief a manager sends for it.

Six event kinds carry a sprint (`event_log.GOAL_STATED`, `GOAL_WITHDRAWN`, `BRIEF_SENT`,
`BRIEF_APPROVED`, `BRIEF_REPLIED`, `SPRINT_REPORTED`). All put the project id in the event's project
column. A goal row carries `{"sprint_id": <id>, "goal": <text>}` (a withdrawal repeats the stated
text); the brief and report rows carry

    brief.sent      {"sprint_id", "version": <int>, "goal": <str>, "brief": {<the five parts>}}
    brief.approved  {"sprint_id", "version": <int>, "goal": <str>}
    brief.replied   {"sprint_id", "version": <int>, "goal": <str>, "reply": <str>}
    sprint.reported {"sprint_id", "goal": <str>, "report": {<the seven REPORT_MEMBERS>}}

The log keeps all six indefinitely (`event_log.KEPT_KINDS`).

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

Both accept only a UTF-8 JSON object with exactly those keys; anything else, a repeated key, a
NaN or Infinity literal or nesting too deep to parse raises `ValueError`.

`sprint_states(events, states=None)` folds events into the open sprints keyed by sprint id: a
`goal.stated` event with a project, a string `sprint_id` and a string `goal` adds a `SprintState`
(`stated_seq` and `stated_at` are the event's `seq` and `at`); a `goal.withdrawn` with a string
`sprint_id` removes it; every other event and any malformed goal event changes nothing.
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
`APPROVED`, a reply (a string) sets `CHANGES` and the reply. Every other row changes nothing. A
sprint whose brief is `APPROVED` is `STARTING`, else `DRAFTING` (`SprintState.state`).
`brief.approved` and `brief.replied`, when they apply, also set the brief's `decided_at` to the
event's `at`; a `brief.sent` brief has `decided_at` `None`.
`withdrawn_ids(events, ids)` adds the `sprint_id` of every `goal.withdrawn` row with a string one.

A report is what the approved sprint's manager says about the sprint. `parse_report_request(body)`
reads the manager's body and returns `(sprint_id, secret, report)`:

    {"sprint_id": "<16 lowercase hex>", "secret": "<string>",
     "report": {"status": "<one line>", "phase": "running", "milestone": "<one line>",
                "tracker_url": "https://<host>/<path>",
                "issues": [{"issue": 12, "stage": "building"}, {"issue": 13, "stage": "landed"}],
                "inbox": [12], "next": "<one line>"}}

It accepts only a UTF-8 JSON object of exactly `sprint_id`, `secret` and `report`, a valid sprint
id, a string secret and a `report` object whose keys are a subset of `REPORT_MEMBERS`; anything
else, a repeated key, a NaN literal or nesting too deep is `ValueError`. A missing member is not (the
service answers it with the member). `checked_report(report)` checks the members in `REPORT_MEMBERS`
order and refuses with `Refused("the report has no valid <member>")` the first that is missing or
invalid; right after a valid `status` it refuses `STATUS_NUMBER` when the stripped status matches
`#` and a digit. `status`, `milestone` and `next` are a one-line text (a string, non-empty after stripping,
no line break, at most `MAX_LINE_CHARS` code points after stripping); `phase` is one of
`REPORT_PHASES`; `tracker_url` is a string of at most `MAX_LINE_CHARS` code points starting with
`https://` whose every character is printable and not whitespace; `issues` is a list of at most
`MAX_REPORT_ISSUES` objects of exactly `issue` (an int, not a bool, at least 1) and `stage` (one of
`REPORT_STAGES`), no issue twice, possibly empty; `inbox` is a list of at most `MAX_REPORT_ISSUES`
ints (not bools) of at least 1, possibly empty. It returns a new dict of the seven members: texts
stripped, `issues` sorted by issue, `inbox` sorted without duplicates, `tracker_url` and `phase` as
given.

The fold keeps each open sprint's `Report(at, status, phase, milestone, tracker_url, issues, inbox,
next_step)`. `sprint.reported` changes an open sprint only when its brief is approved (`STARTING`)
and `checked_report` accepts a dict `report`; the report is then replaced (`at` is the event's `at`,
`issues` a tuple of `(issue, stage)`, `inbox` a tuple, `next_step` the `next` member) and the
sprint's observations are cleared. Every other report row changes nothing.

Observations: a `delivery.seen` row carries no sprint id and is read as the delivery fold reads it
(`deliveries.delivery_states` on that one row; a row that parses to nothing changes nothing). For
every open sprint of the row's project that has a report, a run that moved after the report
(`moved_ms` greater than the report's `at` in milliseconds) and carries a reported issue sets the
sprint's `moved_ms` to the larger of the kept one and the run's, and each of the run's stages for a
reported issue becomes that issue's `Observed(issue, moved_ms, session_id, run_id, stage)` when
`(moved_ms, session_id, run_id)` is at least the kept one's. `delivery.gone` changes nothing: the
last stage and movement outlive the run. `SprintState.observed` is ordered by issue. Folding `a + b`
equals folding `b` onto the fold of `a`.

`ago_text(elapsed_ms)` is `just now` under a minute, `<m> min ago` under an hour, `<h> h ago` under
a day, else `1 day ago` or `<d> days ago`; a negative count is 0. `age_text(elapsed_ms)` is `stated `
plus that. `progress_text(landed, total, in_delivery, queued, held)` is `<landed> of <total> landed`
followed by `, <n> in delivery`, `, <n> queued` and `, <n> held` for each non-zero count, in that
order. The view states and texts are the constants `ON_TRACK`, `WAITING`, `QUIET`, `CLOSING`,
`DONE` and their `_TEXT`; `CLOSED_OUT` is the view's stage for a run's `done` (not a report stage).
The module reads no clock and no environment; only the secret helpers touch the filesystem.
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
from agent_tools.console import deliveries
from agent_tools.console.deliveries import DELIVERY_SEEN
from agent_tools.console.event_log import (BRIEF_APPROVED, BRIEF_REPLIED, BRIEF_SENT, GOAL_STATED,
                                           GOAL_WITHDRAWN, SPRINT_REPORTED, Event)

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
REPORT_MEMBERS = ("status", "phase", "milestone", "tracker_url", "issues", "inbox", "next")
REPORT_PHASES = ("running", "closing", "done")
LANDED = "landed"
HELD = "held"
REPORT_STAGES = ("queued", "planning", "plan review", "building", "final review", "verifying",
                 "landing", "working", LANDED, HELD)
CLOSED_OUT = "closed out"
MAX_LINE_CHARS = 500
MAX_REPORT_ISSUES = 200
ON_TRACK = "on_track"
ON_TRACK_TEXT = "on track"
WAITING = "waiting"
WAITING_TEXT = "waiting on you ({n})"
QUIET = "quiet"
QUIET_TEXT = "quiet for {minutes} min \u2014 may be stuck"
CLOSING = "closing"
CLOSING_TEXT = "closing"
DONE = "done"
DONE_TEXT = "done"
SECRETS_DIR = "sprint-secrets"
SPRINT_ID = re.compile(r"[0-9a-f]{16}")

UNREGISTERED = "this project is not registered"
EMPTY = "write the goal first"
TOO_LONG = "a goal is at most 2000 characters"
NOT_OPEN = "this sprint is not open"
SECRET_REFUSED = "secret refused"
MISSING_PART = "the brief has no {part}"
REPORT_MEMBER = "the report has no valid {member}"
STATUS_NUMBER = "the status line names an issue number"
NOT_STARTED = "this sprint's brief is not approved"
NOT_WAITING = "this brief is not waiting for you"
REPLACED = "a newer brief replaced this one"
EMPTY_REPLY = "write the reply first"
REPLY_TOO_LONG = "a reply is at most 2000 characters"
UNKNOWN = "this sprint is not known"

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
    decided_at: str | None = None


@dataclass(frozen=True)
class Report:
    at: str
    status: str
    phase: str
    milestone: str
    tracker_url: str
    issues: tuple[tuple[int, str], ...]
    inbox: tuple[int, ...]
    next_step: str


@dataclass(frozen=True)
class Observed:
    issue: int
    moved_ms: int
    session_id: str
    run_id: str
    stage: deliveries.IssueStage


@dataclass(frozen=True)
class SprintState:
    sprint_id: str
    project_id: str
    goal: str
    stated_seq: int
    stated_at: str
    brief: Brief | None = None
    report: Report | None = None
    observed: tuple[Observed, ...] = ()
    moved_ms: int | None = None

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


def parse_brief_request(body: bytes) -> tuple[str, str, dict]:
    value = _object(body, {"sprint_id", "secret", "brief"}, project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    brief = value["brief"]
    if not isinstance(brief, dict) or not set(brief) <= set(PARTS):
        raise ValueError(f"brief must be an object of {', '.join(PARTS)}")
    return sprint_id, value["secret"], brief


def parse_report_request(body: bytes) -> tuple[str, str, dict]:
    value = _object(body, {"sprint_id", "secret", "report"}, project=False)
    sprint_id = _sprint_id(value["sprint_id"])
    if not isinstance(value["secret"], str):
        raise ValueError("secret must be a string")
    report = value["report"]
    if not isinstance(report, dict) or not set(report) <= set(REPORT_MEMBERS):
        raise ValueError(f"report must be an object of {', '.join(REPORT_MEMBERS)}")
    return sprint_id, value["secret"], report


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


def _line(value: object) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and "\n" not in value
            and "\r" not in value and len(value.strip()) <= MAX_LINE_CHARS)


def _number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _issue_row(row: object) -> bool:
    return (isinstance(row, dict) and set(row) == {"issue", "stage"} and _number(row["issue"])
            and row["stage"] in REPORT_STAGES)


def _valid_report_member(member: str, value: object) -> bool:
    if member in ("status", "milestone", "next"):
        return _line(value)
    if member == "phase":
        return value in REPORT_PHASES
    if member == "tracker_url":
        return (isinstance(value, str) and value.startswith("https://")
                and len(value) <= MAX_LINE_CHARS
                and all(char.isprintable() and not char.isspace() for char in value))
    if member == "issues":
        return (isinstance(value, list) and len(value) <= MAX_REPORT_ISSUES
                and all(_issue_row(row) for row in value)
                and len({row["issue"] for row in value}) == len(value))
    return isinstance(value, list) and len(value) <= MAX_REPORT_ISSUES and all(
        _number(item) for item in value)


def checked_report(report: dict) -> dict:
    for member in REPORT_MEMBERS:
        if not _valid_report_member(member, report.get(member)):
            raise Refused(REPORT_MEMBER.format(member=member))
        if member == "status" and re.search(r"#\d", report["status"].strip()):
            raise Refused(STATUS_NUMBER)
    return {"status": report["status"].strip(), "phase": report["phase"],
            "milestone": report["milestone"].strip(), "tracker_url": report["tracker_url"],
            "issues": sorted(({"issue": row["issue"], "stage": row["stage"]}
                              for row in report["issues"]), key=lambda row: row["issue"]),
            "inbox": sorted(set(report["inbox"])), "next": report["next"].strip()}


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
            return replace(state, brief=Brief(version, parts, event.at, NONE, None, None))
        return state
    if brief is None or version != brief.version or brief.decision != NONE:
        return state
    if event.kind == BRIEF_APPROVED:
        return replace(state, brief=replace(brief, decision=APPROVED, decided_at=event.at))
    reply = payload.get("reply")
    if isinstance(reply, str):
        return replace(state,
                       brief=replace(brief, decision=CHANGES, reply=reply, decided_at=event.at))
    return state


def _folded_report(state: SprintState, event: Event) -> SprintState:
    report = event.payload.get("report")
    if state.state != STARTING or not isinstance(report, dict):
        return state
    try:
        checked = checked_report(report)
    except Refused:
        return state
    return replace(state, observed=(), moved_ms=None,
                   report=Report(event.at, checked["status"], checked["phase"],
                                 checked["milestone"], checked["tracker_url"],
                                 tuple((row["issue"], row["stage"]) for row in checked["issues"]),
                                 tuple(checked["inbox"]), checked["next"]))


def _observed(folded: dict[str, SprintState], event: Event) -> None:
    runs = deliveries.delivery_states([event])
    for run in runs.values():
        for sprint_id, state in folded.items():
            report = state.report
            if state.project_id != event.project or report is None:
                continue
            if run.moved_ms <= int(datetime.fromisoformat(report.at).timestamp() * 1000):
                continue
            reported = {issue for issue, _ in report.issues}
            stages = [stage for stage in run.issues if stage.issue in reported]
            if not stages:
                continue
            kept = {item.issue: item for item in state.observed}
            for stage in stages:
                old = kept.get(stage.issue)
                if old is None or ((run.moved_ms, run.session_id, run.run_id)
                                   >= (old.moved_ms, old.session_id, old.run_id)):
                    kept[stage.issue] = Observed(stage.issue, run.moved_ms, run.session_id,
                                                 run.run_id, stage)
            folded[sprint_id] = replace(
                state, moved_ms=max(state.moved_ms or 0, run.moved_ms),
                observed=tuple(kept[issue] for issue in sorted(kept)))


def sprint_states(events: Iterable[Event],
                  states: Mapping[str, SprintState] | None = None) -> dict[str, SprintState]:
    folded = dict(states or {})
    for event in events:
        if event.kind == DELIVERY_SEEN:
            _observed(folded, event)
            continue
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
        elif event.kind == SPRINT_REPORTED and sprint_id in folded:
            folded[sprint_id] = _folded_report(folded[sprint_id], event)
    return folded


def withdrawn_ids(events: Iterable[Event], ids: frozenset[str] = frozenset()) -> frozenset[str]:
    withdrawn = set(ids)
    for event in events:
        sprint_id = event.payload.get("sprint_id")
        if event.kind == GOAL_WITHDRAWN and isinstance(sprint_id, str):
            withdrawn.add(sprint_id)
    return frozenset(withdrawn)


def ago_text(elapsed_ms: int) -> str:
    elapsed = max(elapsed_ms, 0)
    if elapsed < _MINUTE_MS:
        return "just now"
    if elapsed < _HOUR_MS:
        return f"{elapsed // _MINUTE_MS} min ago"
    if elapsed < _DAY_MS:
        return f"{elapsed // _HOUR_MS} h ago"
    days = elapsed // _DAY_MS
    return "1 day ago" if days == 1 else f"{days} days ago"


def age_text(elapsed_ms: int) -> str:
    return "stated " + ago_text(elapsed_ms)


def progress_text(landed: int, total: int, in_delivery: int, queued: int, held: int) -> str:
    text = f"{landed} of {total} landed"
    for count, label in ((in_delivery, "in delivery"), (queued, "queued"), (held, "held")):
        if count:
            text += f", {count} {label}"
    return text


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
