"""`prompt_card`: the permission card, a held Bash prompt of a manager's session (#1424, P3, P4, P6, P9).

A manager's Bash call that the sprint's permit does not decide reaches the owner's console as a
card, not as a wait in a session list. The manager's `PermissionRequest` hook asks the console
(`ASK_PATH`) and then waits on it; the owner answers on the card (`ANSWER_PATH`); the hook prints
the client's decision. This module is the pure part: the rows, their fold, the rule for when a card
is open, the inbox entries and the strict wire shapes. It has no command and no I/O.

Rows. `event_log.PROMPT_ASKED` carries exactly `{sprint_id, session_id, command}` plus
`description` only when it is a str, under the sprint's project; `event_log.PROMPT_ANSWERED`
carries exactly `{prompt, answer}` (`prompt` is the asked row's `seq`, `answer` one of `ANSWERS`);
`event_log.PROMPT_CLOSED` carries exactly `{prompt, reason}`, `reason` in `CLOSE_REASONS`:
`expired` when the hook's hold ran out and `ended` when the console found the prompt no longer
held. `asked_row`, `answered_row` and `closed_row` build those rows. None is in `KEPT_KINDS`.

Fold (`prompts`). An asked row counts only with that exact payload shape, non-empty str ids, a
non-empty `command` of at most `MAX_COMMAND_CHARS` and a str project; it adds a `Prompt` that is
`OPEN`. An answered row counts only with exactly `{prompt, answer}` (a row with a `by` member
counts for nothing, so a guest answers nothing), naming a folded `OPEN` prompt, with `answer` in
`ANSWERS`; it sets `ALLOWED` or `REFUSED`. A closed row with exactly `{prompt, reason}`, `reason`
in `CLOSE_REASONS`, naming an `OPEN` prompt sets `CLOSED`. Every other row, and a second answer or
close, changes nothing. An asked row never changes another prompt: the prompts of one session
are held side by side, because a manager's workflow agents carry the manager's session id and
can each hold one (P9). `prompts` never mutates the mapping it is given, and folding all events
equals folding them onto an earlier fold.

Open rule (`open_prompts`, P6, P9). An `OPEN` prompt is shown only while the whole of it is still
true: its hold has not run out (`HOLD_SECONDS` after its `at`), the hook has been heard for this
very prompt within `CONTACT_SECONDS` (`contact` maps a prompt id to the console's millisecond of
the hook's last ask or wait for it and is kept in memory only, so a restarted console shows
nothing until the hook's next wait), its sprint is `active`, its session is the sprint's
manager session, and that session is known and not ended (a session removed after its end is
unknown, so a card never reappears). `POLL_SECONDS` is the hook's wait between polls, so
`CONTACT_SECONDS` is three polls.

Entries (`inbox_entries`). One `inbox_item` of reason `permission` per open prompt whose sprint is
known, keyed `permission/<id>`, with the sprint's title, the `HEADLINE`, `words` (the first line
of the manager's own description, cut to `MAX_WORDS_CHARS`, else `NO_WORDS`) and the command
verbatim.

Wire. `parse_ask` reads the hook's body: strict JSON (a repeated key and NaN are refused),
`phase` `ask` with exactly `{sprint_id, secret, phase, session_id, command}` and an optional
`description`, or `wait` and `close` with exactly `{sprint_id, secret, phase, session_id,
prompt}`. `parse_answer` reads the owner's `{prompt, answer}`. Any other shape is `ValueError`.
`hook_output` is the client's `PermissionRequest` decision as one JSON line.

Constants live here except the hold, the poll and the hook's timeout, which `manager` owns
(`PROMPT_HOLD_SECONDS`, `PROMPT_POLL_SECONDS`, `PROMPT_TIMEOUT`): `sprints` and `sprint` import
`manager`, so `manager` must never import this module, which imports `sprints`.

Imports. This module imports only `canonical`, `console.event_log`, `console.manager`,
`console.sessions` and `console.sprints`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console import event_log, manager
from agent_tools.console import sprints as sprint_module
from agent_tools.console.event_log import Event
from agent_tools.console.sessions import ENDED, SessionState, at_ms
from agent_tools.console.sprints import SprintState

ASK_PATH = "/api/permission-prompt"
ANSWER_PATH = "/api/permission-answer"

ALLOW = "allow"
REFUSE = "refuse"
ANSWERS = (ALLOW, REFUSE)
OPEN = "open"
ALLOWED = "allowed"
REFUSED = "refused"
CLOSED = "closed"
CLOSE_REASONS = ("expired", "ended")
PHASES = ("ask", "wait", "close")

HOLD_SECONDS = manager.PROMPT_HOLD_SECONDS
POLL_SECONDS = manager.PROMPT_POLL_SECONDS
CONTACT_SECONDS = 6
MAX_COMMAND_CHARS = 16384
MAX_WORDS_CHARS = 200

HEADLINE = "The manager of {title} asks to run a command"
NO_WORDS = "It did not say why."
NOT_OPEN = "This permission prompt is no longer open, so it takes no answer."
OWNER_REFUSED_TEXT = (
    "The owner refused this command on the console: do the step another way, or bring the "
    "choice to the owner with `sprint ask`, marking the question `owner_only`.")
EXPIRED_TEXT = (
    "Nobody answered this permission prompt on the console within ten minutes, so it was "
    "refused: do the step another way that needs no permission, or bring the choice to the "
    "owner with `sprint ask`, marking the question `owner_only`.")

_ASKED_KEYS = {"sprint_id", "session_id", "command"}
_ANSWERED_KEYS = {"prompt", "answer"}
_CLOSED_KEYS = {"prompt", "reason"}


class Refused(Exception):
    """The service's 409 words."""


@dataclass(frozen=True)
class Prompt:
    prompt_id: int
    project_id: str
    sprint_id: str
    session_id: str
    command: str
    description: str | None
    at: str
    state: str


@dataclass(frozen=True)
class AskRequest:
    sprint_id: str
    secret: str
    phase: str
    session_id: str
    command: str | None
    description: str | None
    prompt: int | None


def _number(value: object) -> bool:
    return type(value) is int and value >= 1


def _text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _command(value: object) -> bool:
    return _text(value) and len(value) <= MAX_COMMAND_CHARS


def asked_row(project_id: str, sprint_id: str, session_id: str, command: str,
              description: str | None) -> tuple[str, str, dict]:
    payload = {"sprint_id": sprint_id, "session_id": session_id, "command": command}
    if isinstance(description, str):
        payload["description"] = description
    return event_log.PROMPT_ASKED, project_id, payload


def answered_row(project_id: str, prompt_id: int, answer: str) -> tuple[str, str, dict]:
    return event_log.PROMPT_ANSWERED, project_id, {"prompt": prompt_id, "answer": answer}


def closed_row(project_id: str, prompt_id: int, reason: str) -> tuple[str, str, dict]:
    return event_log.PROMPT_CLOSED, project_id, {"prompt": prompt_id, "reason": reason}


def prompts(events: Iterable[Event], state: Mapping[int, Prompt] | None = None) -> dict[int, Prompt]:
    """The prompts after `events` are folded onto `state`; `state` itself is never changed."""
    folded = dict(state or {})
    for event in events:
        payload = event.payload
        if not isinstance(payload, dict):
            continue
        if event.kind == event_log.PROMPT_ASKED:
            keys = set(payload)
            if keys != _ASKED_KEYS and keys != _ASKED_KEYS | {"description"}:
                continue
            description = payload.get("description")
            if "description" in payload and not isinstance(description, str):
                continue
            if (isinstance(event.project, str) and _text(payload["sprint_id"])
                    and _text(payload["session_id"]) and _command(payload["command"])):
                folded[event.seq] = Prompt(event.seq, event.project, payload["sprint_id"],
                                           payload["session_id"], payload["command"],
                                           description, event.at, OPEN)
        elif event.kind == event_log.PROMPT_ANSWERED:
            if set(payload) != _ANSWERED_KEYS or payload["answer"] not in ANSWERS:
                continue
            prompt = folded.get(payload["prompt"]) if _number(payload["prompt"]) else None
            if prompt is not None and prompt.state == OPEN:
                folded[prompt.prompt_id] = replace(
                    prompt, state=ALLOWED if payload["answer"] == ALLOW else REFUSED)
        elif event.kind == event_log.PROMPT_CLOSED:
            if set(payload) != _CLOSED_KEYS or payload["reason"] not in CLOSE_REASONS:
                continue
            prompt = folded.get(payload["prompt"]) if _number(payload["prompt"]) else None
            if prompt is not None and prompt.state == OPEN:
                folded[prompt.prompt_id] = replace(prompt, state=CLOSED)
    return folded


def active(sprint: SprintState) -> bool:
    return sprint.state == sprint_module.STARTING and sprint_module.takes_notices(sprint)


def open_prompts(prompts: Mapping[int, Prompt], now_ms: int,
                 sprints: Mapping[str, SprintState], sessions: Mapping[str, SessionState],
                 contact: Mapping[int, int]) -> list[Prompt]:
    """The prompts a card is shown for at `now_ms`, ascending by id."""
    found = []
    for prompt in sorted(prompts.values(), key=lambda prompt: prompt.prompt_id):
        if prompt.state != OPEN:
            continue
        asked_ms = at_ms(prompt.at)
        if asked_ms is None or asked_ms <= now_ms - HOLD_SECONDS * 1000:
            continue
        heard = contact.get(prompt.prompt_id)
        if type(heard) is not int or heard <= now_ms - CONTACT_SECONDS * 1000:
            continue
        sprint = sprints.get(prompt.sprint_id)
        if sprint is None or not active(sprint) or prompt.session_id != sprint.manager_session:
            continue
        held = sessions.get(prompt.session_id)
        if held is None or held.state == ENDED:
            continue
        found.append(prompt)
    return found


def words(description: str | None) -> str:
    """The first line of the manager's own description, cut to `MAX_WORDS_CHARS`."""
    lines = description.strip().splitlines() if isinstance(description, str) else []
    first = lines[0].strip() if lines else ""
    if not first:
        return NO_WORDS
    if len(first) > MAX_WORDS_CHARS:
        return first[:MAX_WORDS_CHARS - 1] + "…"
    return first


def inbox_entries(open: Sequence[Prompt], sprints: Mapping[str, SprintState]) -> list[dict]:
    """One `inbox_item` of reason `permission` per open prompt whose sprint is known."""
    entries = []
    for prompt in open:
        sprint = sprints.get(prompt.sprint_id)
        if sprint is None:
            continue
        title = sprint_module.sprint_title(sprint)
        entries.append({
            "type": "inbox_item", "reason": "permission", "key": f"permission/{prompt.prompt_id}",
            "project_id": prompt.project_id, "sprint_id": prompt.sprint_id,
            "prompt": prompt.prompt_id, "title": title, "headline": HEADLINE.format(title=title),
            "words": words(prompt.description), "command": prompt.command, "answered": False,
            "waiting_since": prompt.at})
    return entries


def _decoded(body: bytes) -> dict:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the body is nested too deeply") from error
    if not isinstance(value, dict):
        raise ValueError("the body must be a JSON object")
    return value


def parse_ask(body: bytes) -> AskRequest:
    value = _decoded(body)
    phase = value.get("phase")
    keys = {"sprint_id", "secret", "phase", "session_id"}
    if phase == "ask":
        keys |= {"command"}
        if "description" in value:
            keys |= {"description"}
    elif phase in ("wait", "close"):
        keys |= {"prompt"}
    else:
        raise ValueError("phase must be ask, wait or close")
    if set(value) != keys:
        raise ValueError(f"the body must be an object of exactly {', '.join(sorted(keys))}")
    if not all(_text(value[key]) for key in ("sprint_id", "secret", "session_id")):
        raise ValueError("sprint_id, secret and session_id must be non-empty strings")
    if phase == "ask":
        if not _command(value["command"]):
            raise ValueError(f"command must be 1 to {MAX_COMMAND_CHARS} characters")
        description = value.get("description")
        if "description" in value and not isinstance(description, str):
            raise ValueError("description must be a string")
        return AskRequest(value["sprint_id"], value["secret"], phase, value["session_id"],
                          value["command"], description, None)
    if not _number(value["prompt"]):
        raise ValueError("prompt must be a number of 1 or more")
    return AskRequest(value["sprint_id"], value["secret"], phase, value["session_id"],
                      None, None, value["prompt"])


def parse_answer(body: bytes) -> tuple[int, str]:
    value = _decoded(body)
    if set(value) != _ANSWERED_KEYS:
        raise ValueError("the body must be an object of exactly answer, prompt")
    if not _number(value["prompt"]) or value["answer"] not in ANSWERS:
        raise ValueError("the prompt or the answer is not valid")
    return value["prompt"], value["answer"]


def hook_output(behavior: str, message: str | None = None) -> str:
    """The client's `PermissionRequest` decision, one JSON line."""
    decision = {"behavior": behavior}
    if behavior == "deny":
        decision["message"] = message
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                              "decision": decision}})
