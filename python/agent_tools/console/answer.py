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

A prompt already answered with exactly the given `choices` is left alone: the tick returns without
an edit, so a retry of a tick whose reply was lost succeeds. A prompt answered with other choices
is still `Refused(ALREADY)`.

A forge error propagates unchanged. `Refused` carries the one-line reason as `str(error)`.

`with_retries(write, clock=, sleep=, on_retry=)` runs `write` again after a transport failure (#1075).
Only a `ForgeError` whose `transient` is true is retried; any other exception is raised on the attempt
it came from, unchanged. `started = clock()` is read once and every attempt runs inside
`forge_api.deadline(started + RETRY_BUDGET_SECONDS, clock)`, so no `gh` call of any attempt runs past
that deadline and the whole write, waits and calls together, ends within `RETRY_BUDGET_SECONDS` of its
start. After attempt `n` (1-based) fails, the loop raises when `RETRY_DELAYS` has no delay `n`; else
it computes `room = deadline - clock() - LAST_TRY_SECONDS`, raises when `room <= 0`, calls
`on_retry(n, error)` and sleeps `min(delay, room)`: the wait is clamped to the budget and a retry
keeps at least `LAST_TRY_SECONDS` for its own calls. A sleep that returns a truthy value ends the
retries. When the retries end, the last `ForgeError` itself is raised.

`tracker_words(error)` is the one plain sentence for a failed write, the first that applies:

1. the error is not a `ForgeError`: `UNEXPECTED_FAILURE`;
2. its detail carries an HTTP status 500 to 599: `FORGE_DOWN`;
3. it is transient (a timeout, a missed deadline or a connection failure): `NETWORK_DOWN`;
4. its code is `gh_missing`: `GH_MISSING`;
5. its status is 401 or 403: `NOT_SIGNED_IN`;
6. its status is 404: `NOT_FOUND`;
7. anything else: `NOT_TAKEN`.

No sentence carries raw tracker text.

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
from collections.abc import Callable, Sequence

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
RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 10.0)
RETRY_BUDGET_SECONDS: float = 30.0
LAST_TRY_SECONDS: float = 5.0
NETWORK_DOWN = "this computer could not reach GitHub. Check the network, then try again."
FORGE_DOWN = "GitHub had a problem and did not take the answer. Try again in a moment."
NOT_SIGNED_IN = ("gh is not signed in on this computer, or may not change this repository. "
                 "Sign it in with gh auth login, then try again.")
NOT_FOUND = "GitHub no longer finds this issue or its prompt. Open it on GitHub to answer."
GH_MISSING = ("gh is not installed on this computer. Install it and sign it in with gh auth login, "
              "then try again.")
NOT_TAKEN = "GitHub did not take the answer. Try again, or answer it on GitHub."
UNEXPECTED_FAILURE = "the console ran into a problem it did not expect. Try again, or answer it on GitHub."


class Refused(Exception):
    """The answer was not sent; `str(error)` is the one-line reason."""


def _reduced(questions: Sequence[dict]) -> list[tuple[str, list[str]]]:
    return [(q["question"], list(q["options"])) for q in questions]


def tracker_words(error: BaseException) -> str:
    if not isinstance(error, forge_api.ForgeError):
        return UNEXPECTED_FAILURE
    found = forge_api.HTTP_STATUS.search(error.detail)
    status = int(found[1]) if found else None
    if status is not None and 500 <= status <= 599:
        return FORGE_DOWN
    if error.transient:
        return NETWORK_DOWN
    if error.code == "gh_missing":
        return GH_MISSING
    if status in (401, 403):
        return NOT_SIGNED_IN
    if status == 404:
        return NOT_FOUND
    return NOT_TAKEN


def with_retries(write: Callable[[], None], *, clock: Callable[[], float],
                 sleep: Callable[[float], object],
                 on_retry: Callable[[int, forge_api.ForgeError], None] = lambda attempt, error: None) -> None:
    at = clock() + RETRY_BUDGET_SECONDS
    with forge_api.deadline(at, clock):
        attempt = 0
        while True:
            attempt += 1
            try:
                return write()
            except forge_api.ForgeError as error:
                if not error.transient or attempt > len(RETRY_DELAYS):
                    raise
                room = at - clock() - LAST_TRY_SECONDS
                if room <= 0:
                    raise
                on_retry(attempt, error)
                if sleep(min(RETRY_DELAYS[attempt - 1], room)):
                    raise


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
        verified = foa.verified_questions(marker)
        if len(verified) == len(choices) and all(
                0 <= choice < len(q["options"]) and q["chosen"] == q["options"][choice]
                for q, choice in zip(verified, choices)):
            return
        raise Refused(ALREADY)
    fm.edit(slug, comment_id, foa.tick_body(marker.body, choices))
