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

`with_retries(write, clock=, sleep=, on_retry=)` runs `write` again after a transport failure (#1075) and
returns what the attempt that succeeded returned (#1110).
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

`look_head(slug, pr)` (#1260) reads pull request `pr` once (`forge_api.api_get("repos/<slug>/pulls/<pr>")`) and
returns `("merged", sha)` when `merged` is true, else `("open", sha)` or `("closed", sha)` from `state`; `sha` is
`head.sha` and must be 40 lowercase hex, and any other shape is `ForgeError("payload_invalid", ...)`.
`record_look(slug, issue, pr, head, message)` writes the owner's look approval of `head` on issue `issue` and
returns its comment id. It lists the issue's trusted markers (`look_marker.TRUSTED`); a live `look` marker whose
`issue`, `pr`, `head`, `answer=approved` and `message` all equal the given ones is returned and nothing is posted,
so a retry after a lost reply posts no second marker, and one a trusted end marker withdrew is settled too: the
retry never undoes a withdrawal. Otherwise it reads the pull request once more (`look_head`): one that is not open
(`LookMoved`, a `Refused` carrying `LOOK_CLOSED`) or not at `head` (`LookMoved` carrying `LOOK_MOVED`; `state` and
`found` are what it is) is not approved, so no attempt posts a stale approval. `end_look(slug, issue, comment_id)` ends a
look approval the console posted for a head that then moved: it lists the trusted markers and, when `comment_id` is
one of them and still live, posts the trusted `end` marker (`reason=head-moved`) naming it, so no later head can pass the
merge guard on that approval; an approval already ended is left alone. Then it posts `look_marker.approval_body(issue, pr, head,
"approved", message)` and lists the trusted markers again: the new comment must be among them, else
`Refused(LOOK_UNTRUSTED)` (GitHub took it, but not as the owner or a member, so the merge would not count it).

`answer_criterion(slug, issue, index, answer, version=, note=)` (#1113) answers one review item of a held
issue, as the owner (`forge_api.run_gh` drops the tokens). `answer` is `passed` (tick the criterion) or
`note` (post `review_note_body(slug, issue, index, note)` and tick nothing); `version` is the
`inbox.criterion_version` the owner read. The checks run in this order, each refusal before any write:

1. The arguments: `answer` is in `inbox.REVIEW_ANSWERS`, a note is given exactly when `answer` is `note`,
   a note is a non-blank string of at most `verify_answer.MAX_NOTE_CHARS` characters (else `ValueError`),
   and a note matching `verify_answer.FENCE` is `Refused(verify_answer.NOTE_BLOCK)`. No call is made yet.
2. From here to the write the read-modify-write of the issue body is serialized per repository and issue in
   this process (an approval PATCHes the whole body, so two approvals of different criteria that read the
   same body would erase each other). The issue is read with `forge_api.api_get`; a reply without a
   string `state`, a `body` that is neither a string nor null, or `labels` that are not a list of objects is `ForgeError("payload_invalid", ...)`;
   a `state` other than `open` is `Refused(CLOSED)`.
3. The issue must carry `inbox.HELD_LABEL` and its `author_association` must be in `verify_answer.TRUSTED`,
   else `Refused(REVIEW_GONE)`.
4. The criterion `index` of `inbox.acceptance_criteria` must exist and be `human`, else `REVIEW_GONE`.
5. Its `inbox.criterion_version` must equal `version`, else `Refused(REVIEW_EDITED)`.
6. A criterion already ticked: `passed` returns with no write, `note` is `Refused(REVIEW_ALREADY)`.
7. Another unticked criterion whose kind is outside `inbox.MET_KINDS` is `Refused(REVIEW_GONE)`.
8. The comments of the issue are read again (`forge_markers.list_comments`), because the card was built at the
   inbox poll and a runner may have posted since: a live runner prompt (`inbox.live_prompts` of the trusted
   markers) or a verify block check for the criterion (`verify_answer.held_acs`) is `Refused(REVIEW_GONE)`,
   so the inbox's rule that a runner prompt or a block check keeps its own card holds at the write too.
9. `passed` writes one PATCH of the issue body in which only that line's first `[ ]` became `[x]` (the body
   is split and rejoined on `\n`, so every other byte, a `\r` included, is kept); `note` posts one comment.

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
import threading
from collections.abc import Callable, Sequence
from typing import TypeVar

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.claims import forge_markers as fm
from agent_tools.claims import forge_owner_action as foa
from agent_tools.console import inbox
from agent_tools.delivery import look_marker
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
REVIEW_GONE = "this criterion is no longer an open owner review on the tracker"
REVIEW_EDITED = "the criterion changed on the tracker since you read it"
REVIEW_ALREADY = "the criterion is already ticked on the tracker"
CHECK_ANSWERS = ("passed", "failed", "note", "approve", "keep", "drop")
MAX_CONFIRM_CHARS = 200
T = TypeVar("T")
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
LOOK_MOVED = ("Nothing was recorded: the pull request is now at {found}, not at {head}, the head "
              "these pictures show. The manager will send the new pictures.")
LOOK_CLOSED = "Nothing was recorded: the pull request is {state}."
LOOK_APPROVES = ("Choosing \"{option}\" records your approval of {head}, pull request #{pr}, on "
                 "issue #{issue}.")
LOOK_RECORDING = "Recording your approval of {head} on issue #{issue}."
LOOK_UNTRUSTED = ("GitHub took the approval, but not as the repository's owner or a member, so the "
                  "merge would not count it. Sign gh in as the owner, then Retry.")
LOOK_INTERRUPTED = "The console stopped before it recorded the approval. Retry to record it."
LOOK_NO_REPOSITORY = ("The console cannot tell this project's GitHub repository, so nothing was "
                      "recorded.")
LOOK_ENDED_REASON = "head-moved"
LOOK_SENDING = "this approval is already being recorded"
LOOK_NOT_PENDING = "this approval is not waiting to be recorded"


class Refused(Exception):
    """The answer was not sent; `str(error)` is the one-line reason."""


class LookMoved(Refused):
    """The pull request is closed, merged or at another head than the card's: nothing was recorded.

    `state` is what the pull request is (`open`, `closed` or `merged`), `found` the head it has.
    """

    def __init__(self, state: str, found: str, head: str):
        super().__init__(LOOK_CLOSED.format(state=state) if state != "open"
                         else LOOK_MOVED.format(found=found[:7], head=head[:7]))
        self.state, self.found = state, found


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


def with_retries(write: Callable[[], T], *, clock: Callable[[], float],
                 sleep: Callable[[float], object],
                 on_retry: Callable[[int, forge_api.ForgeError], None] = lambda attempt, error: None) -> T:
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


def look_head(slug: str, pr: int) -> tuple[str, str | None]:
    pull = forge_api.api_get(f"repos/{slug}/pulls/{pr}")
    head = pull.get("head") if isinstance(pull, dict) else None
    sha = head.get("sha") if isinstance(head, dict) else None
    state = pull.get("state") if isinstance(pull, dict) else None
    if (not isinstance(sha, str) or not look_marker.HEAD_PATTERN.fullmatch(sha)
            or state not in ("open", "closed") or not isinstance(pull.get("merged"), bool)):
        raise forge_api.ForgeError("payload_invalid", f"pull request {pr} has no readable state and head")
    return ("merged" if pull["merged"] else state), sha


def record_look(slug: str, issue: int, pr: int, head: str, message: str) -> int:
    wanted = {"issue": str(issue), "pr": str(pr), "head": head, "answer": "approved",
              "message": message}
    markers = fm.list_markers(slug, issue, look_marker.TRUSTED)
    for marker in markers:
        if (marker.kind == look_marker.KIND
                and all(marker.fields.get(key) == value for key, value in wanted.items())):
            return marker.comment_id
    state, found = look_head(slug, pr)
    if state != "open" or found != head:
        raise LookMoved(state, found, head)
    posted = fm.post(slug, issue, look_marker.approval_body(issue, pr, head, "approved", message))
    if not any(marker.comment_id == posted for marker in fm.list_markers(slug, issue, look_marker.TRUSTED)):
        raise Refused(LOOK_UNTRUSTED)
    return posted


def end_look(slug: str, issue: int, comment_id: int) -> None:
    """End the look approval `comment_id` with a trusted `end` marker, unless it is already ended.

    The tracker offers no way to read the head and post the approval in one step, so an approval
    posted for a head that then moved is withdrawn here: no later head that keeps the approved
    changes can pass the merge guard on it (#1260)."""
    markers = fm.list_markers(slug, issue, look_marker.TRUSTED)
    target = next((marker for marker in markers if marker.comment_id == comment_id), None)
    if target is not None and fm.is_live(target, markers):
        fm.end(slug, issue, comment_id, LOOK_ENDED_REASON)


def review_note_body(slug: str, issue: int, index: int, note: str) -> str:
    """The comment that carries an owner's note on criterion `index` of `issue`."""
    return (f"Owner's note on acceptance criterion {index} of https://github.com/{slug}/issues/{issue}, "
            f"not yet approved, sent from the console:\n\n{note}")


_CRITERION_LOCKS: dict[tuple[str, int], threading.Lock] = {}
_CRITERION_LOCKS_GUARD = threading.Lock()


def _criterion_lock(slug: str, issue: int) -> threading.Lock:
    """The lock that serializes every body edit of one issue of one repository in this process."""
    with _CRITERION_LOCKS_GUARD:
        return _CRITERION_LOCKS.setdefault((slug, issue), threading.Lock())


def answer_criterion(slug: str, issue: int, index: int, answer: str, *, version: str,
                     note: str | None = None) -> None:
    if answer not in inbox.REVIEW_ANSWERS or (answer == "note") != (note is not None):
        raise ValueError("answer is passed, or note with a note")
    if note is not None:
        if (not isinstance(note, str) or not note.strip()
                or len(note) > verify_answer.MAX_NOTE_CHARS):
            raise ValueError(f"note must be a non-blank string of at most {verify_answer.MAX_NOTE_CHARS} characters")
        if verify_answer.FENCE.search(note.replace("\r\n", "\n")):
            raise Refused(verify_answer.NOTE_BLOCK)
    with _criterion_lock(slug, issue):
        parent = forge_api.api_get(f"repos/{slug}/issues/{issue}")
        if (not isinstance(parent, dict) or not isinstance(parent.get("state"), str)
                or not isinstance(parent.get("body"), (str, type(None)))
                or not isinstance(parent.get("labels"), list)
                or not all(isinstance(label, dict) for label in parent["labels"])):
            raise forge_api.ForgeError("payload_invalid", f"issue {issue} has no readable state, body or labels")
        if parent["state"] != "open":
            raise Refused(CLOSED)
        if (inbox.HELD_LABEL not in [label.get("name") for label in parent["labels"]]
                or parent.get("author_association") not in verify_answer.TRUSTED):
            raise Refused(REVIEW_GONE)
        body = parent["body"] or ""
        criteria = inbox.acceptance_criteria(body)
        criterion = next((c for c in criteria if c.index == index), None)
        if criterion is None or criterion.kind != "human":
            raise Refused(REVIEW_GONE)
        if inbox.criterion_version(issue, criterion) != version:
            raise Refused(REVIEW_EDITED)
        if criterion.ticked:
            if answer == "passed":
                return
            raise Refused(REVIEW_ALREADY)
        if criterion not in inbox.review_criteria(criteria):
            raise Refused(REVIEW_GONE)
        trusted = [c for c in fm.list_comments(slug, issue)
                   if c.get("author_association") in verify_answer.TRUSTED]
        markers = [m for m in (fm.parse(c) for c in trusted) if m is not None]
        asked = verify_answer.held_acs([(c["id"], c["author_association"], c["body"]) for c in trusted
                                        if isinstance(c.get("id"), int) and isinstance(c.get("body"), str)])
        if inbox.live_prompts(markers) or criterion not in inbox.review_criteria(criteria, asked):
            raise Refused(REVIEW_GONE)
        if answer == "passed":
            lines = body.split("\n")
            lines[criterion.line] = lines[criterion.line].replace("[ ]", "[x]", 1)
            forge_api.run_gh(["api", "-X", "PATCH", f"repos/{slug}/issues/{issue}", "-f", "body=" + "\n".join(lines)])
        else:
            fm.post(slug, issue, review_note_body(slug, issue, index, note))
