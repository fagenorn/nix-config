"""The action a question card may carry, which the owner's approval lets a manager run.

A question of a round may carry `"action": {"command": <str>, "approve": <str>}`. `sprints.checked_questions`
asks `refusal` for each, which returns the refusal's text or None, in this order: `ACTION_SHAPE` (not an
object of exactly `command` and `approve`, both strings), `ACTION_COMMAND` (the command not 1 to
`MAX_ACTION_CHARS` characters, with a space at either end or a character of Unicode category Cc, Cf, Zl or
Zp: a line break, a tab, a C1 control, a bidi override or isolate and U+2028 included), `ACTION_PERMIT_VERB`
(`permit.mentions` accepts the command), `ACTION_APPROVE` (`approve` whose strip equals no stripped option),
`ACTION_APPROVE_WORDS` (that option is in `needs_words`), `ACTION_OWNER_ONLY` (the question is not
`owner_only`) and `ACTION_WITH_LOOK` (the question also has a `look`). The checked question carries
`"action"` (`{"command", "approve"}`, the command verbatim, `approve` stripped) only when the round gave one,
and the fold makes it `Question.action`, a `QuestionAction`.

A `permit.judged` row of a folded sprint sets `Question.action_used_at` to the row's `at` (`folded_use`)
only when its `verb` is `action`, its `decision` is `allow` and its `target` is exactly `{"round",
"index"}`, both ints and not bools, naming an answered question of that sprint that has an `action` and no
`action_used_at` yet; every other such row changes nothing.

The hook asks `POST /api/permit` with a signed body that carries no secret and no command text, which
`ActionPermitRequest` holds once `permit_request` has checked it: `command_sha256` and `auth` are 64
lowercase hex characters and `nonce` is 32, beside the ids `sprints.parse_permit_request` checks.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from agent_tools.console import permit

if TYPE_CHECKING:
    from agent_tools.console.event_log import Event
    from agent_tools.console.sprints import SprintState

MAX_ACTION_CHARS = 4096
ACTION_SHAPE = "question {n}'s action must be an object of exactly command and approve, both strings"
ACTION_COMMAND = ("question {n}'s action command must be one line of 1 to 4096 characters with no "
                  "control, bidirectional, invisible or line-separator character and no space at "
                  "either end")
ACTION_PERMIT_VERB = ("question {n}'s action is a merge, rerun or release, which runs only under "
                      "the permit's own rules")
ACTION_APPROVE = "question {n}'s action approve must be the exact text of one option"
ACTION_APPROVE_WORDS = ("question {n}'s action approve option cannot need words: choosing it is "
                        "the approval")
ACTION_OWNER_ONLY = "question {n} names an action, so it must be owner_only"
ACTION_WITH_LOOK = "question {n} cannot carry both a look and an action"
_HIDDEN = frozenset({"Cc", "Cf", "Zl", "Zp"})
_HEX32 = re.compile(r"[0-9a-f]{32}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
PERMIT_KEYS = {"sprint_id", "phase", "session_id", "tool_use_id", "command_sha256", "nonce", "auth"}


@dataclass(frozen=True)
class QuestionAction:
    command: str
    approve: str


@dataclass(frozen=True)
class ActionPermitRequest:
    sprint_id: str
    phase: str
    session_id: str
    tool_use_id: str
    digest: str
    nonce: str
    auth: str
    signed: bytes


def _hidden(command: str) -> bool:
    """A control, format (bidi and zero-width), line or paragraph separator character: one the card
    would reorder, break or hide, so the owner would approve other than the bytes that run."""
    return any(unicodedata.category(char) in _HIDDEN for char in command)


def refusal(n: int, question: dict, options: list[str], needs_words: list[str]) -> str | None:
    """The text that refuses question `n`'s `action`, or None when it may stand or the question has none."""
    if "action" not in question:
        return None
    action = question["action"]
    if (not isinstance(action, dict) or set(action) != {"command", "approve"}
            or not all(isinstance(action[key], str) for key in action)):
        return ACTION_SHAPE.format(n=n)
    command, approve = action["command"], action["approve"].strip()
    if not 1 <= len(command) <= MAX_ACTION_CHARS or command != command.strip() or _hidden(command):
        return ACTION_COMMAND.format(n=n)
    if permit.mentions(command):
        return ACTION_PERMIT_VERB.format(n=n)
    if approve not in options:
        return ACTION_APPROVE.format(n=n)
    if approve in needs_words:
        return ACTION_APPROVE_WORDS.format(n=n)
    if question.get("owner_only") is not True:
        return ACTION_OWNER_ONLY.format(n=n)
    if "look" in question:
        return ACTION_WITH_LOOK.format(n=n)
    return None


def _int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def folded_use(state: SprintState, event: Event) -> SprintState:
    payload = event.payload
    target = payload.get("target")
    if (payload.get("verb") != permit.ACTION or payload.get("decision") != permit.ALLOW
            or not isinstance(target, dict) or set(target) != {"round", "index"}
            or not _int(target["round"]) or not _int(target["index"])):
        return state
    key = (target["round"], target["index"])
    return replace(state, questions=tuple(
        replace(question, action_used_at=event.at)
        if (question.round_id, question.index) == key and question.answer is not None
        and question.action is not None and question.action_used_at is None else question
        for question in state.questions))


def permit_request(value: dict, ids: tuple[str, str, str, str]) -> ActionPermitRequest:
    """The signed action body `value` (exactly `PERMIT_KEYS`) with its checked `ids`."""
    for name, pattern, size in (("command_sha256", _HEX64, 64), ("nonce", _HEX32, 32), ("auth", _HEX64, 64)):
        if not isinstance(value[name], str) or pattern.fullmatch(value[name]) is None:
            raise ValueError(f"{name} must be {size} lowercase hex characters")
    return ActionPermitRequest(*ids, value["command_sha256"], value["nonce"], value["auth"],
                               permit.signed_bytes(value))
