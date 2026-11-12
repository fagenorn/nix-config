"""The console's answer to a decision prompt, written on the tracker (#862, ADR-console-010).

`tick_on_tracker(slug, issue, comment_id, questions, choices)` ticks one box per question of the
prompt comment `comment_id` of issue or pull request `issue` and writes nothing else (no label, no
comment). It runs as the owner: `forge_api.run_gh` drops `GITHUB_TOKEN` and `GH_TOKEN`, so `gh`
uses only the credential of `gh auth login`.

The tick is checked against the tracker as it is now, in this order:

1. The parent is read with `forge_api.api_get("repos/<slug>/issues/<issue>")` (that endpoint answers
   for a pull request too). A reply that is not an object with a string `state` is
   `ForgeError("payload_invalid", ...)`; a `state` other than `open` is `Refused(CLOSED)`, before any
   comment is read or edited: the inbox reads open parents only, so a parent closed since the last
   poll must not be ticked.
2. The trusted owner-action markers of the issue are listed (`forge_markers.list_markers` with
   `forge_owner_action.TRUSTED`). The comment must be a live `owner-action` marker of reason
   `decision`, else `Refused(GONE)`; its verified questions, reduced to `(question, options)`, must
   equal the given questions reduced the same way, else `Refused(CHANGED)`; it must not already be
   answered, else `Refused(ALREADY)`.
3. `forge_markers.edit` is called exactly once with `forge_owner_action.tick_body(body, choices)`.

A forge error propagates unchanged. `Refused` carries the one-line reason as `str(error)`.

`parse_request(body)` reads the page's request body, the one body of `POST /api/answer`
(`service.py`), sent as `Content-Type: application/json` and at most `service.MAX_ANSWER_BYTES`
long:

    {"project_id": "<project id>", "key": "<inbox item key>", "choices": [<0-based option index per question>, ...]}

and returns `(project_id, key, choices)`. It accepts only a UTF-8 JSON object with exactly the keys
`project_id` and `key` (non-empty strings) and `choices` (a list of 1 to `forge_owner_action.MAX_ITEMS`
integers, none a boolean, each at least 0); anything else, a repeated key included, raises `ValueError`.

`parse_check_request(body)` reads the body of `POST /api/check-answer` (#863), the answer to one
verification prompt of the runner, sent the same way and at most as long:

    {"project_id": "<project id>", "key": "<inbox item key>", "answer": "<word>", "version": "<item version>",
     "note": "<text>"?, "confirm": "<text>"?}

and returns `(project_id, key, answer, version, note, confirm)`, where `note` and `confirm` are None when absent.
It accepts only a UTF-8 JSON object whose keys include `project_id`, `key` and `answer` and lie within
those five, so a key that is a list, or any further member, is refused: no body answers more than one
item. `project_id`, `key` and `version` are non-empty strings and `answer` is one of `CHECK_ANSWERS`. `note` is present
exactly when `answer` is `note`, a string that is not blank and has at most
`verify_answer.MAX_NOTE_CHARS` characters; `confirm` is optional, a string of at most `MAX_CONFIRM_CHARS`
characters. Anything else, a repeated key included, raises `ValueError`.
"""

import json
from collections.abc import Sequence

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.claims import forge_markers as fm
from agent_tools.claims import forge_owner_action as foa
from agent_tools.system import forge_api
from agent_tools.verification import verify_answer

NOT_OPEN = "this is not an open decision prompt"
CHOOSE = "choose one option under each question"
SENDING = "an answer to this prompt is already being sent"
CLOSED = "the issue or pull request is closed"
GONE = "the prompt is no longer open on the tracker"
CHANGED = "the prompt changed on the tracker"
ALREADY = "the prompt is already answered on the tracker"
NOT_AN_ANSWER = "this item does not take that answer"
CONFIRM = "type the issue reference exactly to approve this check"
CHECK_ANSWERS = ("passed", "failed", "note", "approve", "keep", "drop")
MAX_CONFIRM_CHARS = 200


class Refused(Exception):
    """The answer was not sent; `str(error)` is the one-line reason."""


def _reduced(questions: Sequence[dict]) -> list[tuple[str, list[str]]]:
    return [(q["question"], list(q["options"])) for q in questions]


def parse_request(body: bytes) -> tuple[str, str, list[int]]:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the answer is nested too deeply") from error
    if not isinstance(value, dict) or set(value) != {"project_id", "key", "choices"}:
        raise ValueError("the answer must be an object of project_id, key and choices")
    project_id, key, choices = value["project_id"], value["key"], value["choices"]
    for name, text in (("project_id", project_id), ("key", key)):
        if not isinstance(text, str) or not text:
            raise ValueError(f"{name} must be a non-empty string")
    if (not isinstance(choices, list) or not 1 <= len(choices) <= foa.MAX_ITEMS
            or any(isinstance(c, bool) or not isinstance(c, int) or c < 0 for c in choices)):
        raise ValueError("choices must be a list of non-negative integers, one per question")
    return project_id, key, choices


def parse_check_request(body: bytes) -> tuple[str, str, str, str, str | None, str | None]:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the answer is nested too deeply") from error
    required = {"project_id", "key", "answer", "version"}
    if not isinstance(value, dict) or not required <= set(value) <= required | {"note", "confirm"}:
        raise ValueError("the answer must be an object of project_id, key, answer, version, note and confirm")
    project_id, key, word = value["project_id"], value["key"], value["answer"]
    version = value["version"]
    for name, text in (("project_id", project_id), ("key", key), ("version", version)):
        if not isinstance(text, str) or not text:
            raise ValueError(f"{name} must be a non-empty string")
    if word not in CHECK_ANSWERS:
        raise ValueError("answer is not one of " + ", ".join(CHECK_ANSWERS))
    note, confirm = value.get("note"), value.get("confirm")
    if (word == "note") != ("note" in value):
        raise ValueError("a note is given exactly when the answer is note")
    if "note" in value and (not isinstance(note, str) or not note.strip()
                            or len(note) > verify_answer.MAX_NOTE_CHARS):
        raise ValueError(f"note must be a non-blank string of at most {verify_answer.MAX_NOTE_CHARS} characters")
    if "confirm" in value and (not isinstance(confirm, str) or len(confirm) > MAX_CONFIRM_CHARS):
        raise ValueError(f"confirm must be a string of at most {MAX_CONFIRM_CHARS} characters")
    return project_id, key, word, version, note, confirm


def tick_on_tracker(slug: str, issue: int, comment_id: int, questions: list[dict],
                    choices: list[int]) -> None:
    parent = forge_api.api_get(f"repos/{slug}/issues/{issue}")
    if not isinstance(parent, dict) or not isinstance(parent.get("state"), str):
        raise forge_api.ForgeError("payload_invalid", f"issue {issue} has no readable state")
    if parent["state"] != "open":
        raise Refused(CLOSED)
    markers = fm.list_markers(slug, issue, foa.TRUSTED)
    marker = next((m for m in markers if m.comment_id == comment_id), None)
    if (marker is None or marker.kind != foa.KIND or marker.fields.get("reason") != "decision"
            or not fm.is_live(marker, markers)):
        raise Refused(GONE)
    if _reduced(foa.verified_questions(marker)) != _reduced(questions):
        raise Refused(CHANGED)
    if foa.answered(marker):
        raise Refused(ALREADY)
    fm.edit(slug, comment_id, foa.tick_body(marker.body, choices))
