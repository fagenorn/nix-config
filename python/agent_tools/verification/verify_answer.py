"""The runner's single-prompt owner path (#863): answer one verification prompt from the console.

`answer_prompt(slug, issue, comment_id, answer, note=None, paid=False)` is the one write the console
page may make on a runner prompt, and it runs as the owner: every call goes through `forge_api`, which
drops `GITHUB_TOKEN` and `GH_TOKEN`, so it uses the owner's `gh auth login`. `verify_run.answer` stays
the only reader of what the owner said; this module only ticks the box that reader honours (or ends a
stale prompt, or posts a note) and never records a result. `verify_pending approve --all-live`
(`verify_run.approve_all_live`) remains the CLI's bulk path and is not touched.

A runner prompt is an `owner-action` marker of a `verify-*` reason that carries `block` and `check`
(`is_runner_prompt`); the decision marker of a batch carries neither and is not one. The answers each
reason takes (`ANSWERS`): a manual check (ASK) takes `passed`, `failed` or `note`; a verdict (DECISION)
takes `passed` or `failed`; an approval (APPROVE) takes `approve`; a stale check (STALE) takes `keep` or
`drop`; an act prompt (ACT) has no box and takes none.

The box each answer ticks: (ASK, passed) `Accept`, (ASK, failed) `Reject`, (DECISION, passed)
`Accept as passed`, (DECISION, failed) `Close as not verified`, (APPROVE, approve) `Run it`, (STALE,
drop) the `Accept without <host>` box. `keep` ends the stale prompt with an `end` marker `kept`, so the
runner never asks that stale identity again. A note is posted as a plain owner comment whose first line
is the fixed sentence of `note_body`, never a marker and, because a trusted non-marker comment holding a
`verify` fence becomes the held block, never one that matches `verify_block.FENCE`.

The checks, in order, each a `Refused` with its text as the reason, before the one write: the arguments
first (`ValueError`, before any call: `note` is given exactly when `answer` is `note` and is a non-blank
`str` of at most `MAX_NOTE_CHARS` characters); the parent issue (a reply that is not an object with a
string `state` is `ForgeError("payload_invalid")`; any state but `open` is `CLOSED`); the prompt, among
the `TRUSTED` (OWNER, MEMBER) comments only and live in that listing (`GONE`); the answer is one the
reason takes (`NOT_AN_ANSWER`); the prompt is not already `answered` (`ALREADY`); it is not `ambiguous`,
both boxes ticked, which the runner keeps pending and still needs the owner to untick one (`AMBIGUOUS`);
a paid approval carries `paid=True`, its typed confirmation (`PAID`); a note carries no `verify` fence
(`NOTE_BLOCK`). When the box to tick is missing from the body, the answer is `CHANGED` and nothing is
edited.
"""
from collections.abc import Sequence

from agent_tools.claims import forge_markers
from agent_tools.claims.forge_markers import Marker
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError
from agent_tools.verification import verify_issues, verify_owner
from agent_tools.verification.verify_block import FENCE
from agent_tools.verification.verify_owner import ACT, APPROVE, ASK, DECISION, STALE

TRUSTED: tuple[str, ...] = verify_issues.TRUSTED
ANSWERS: dict[str, tuple[str, ...]] = {ASK: ("passed", "failed", "note"), DECISION: ("passed", "failed"),
                                       APPROVE: ("approve",), STALE: ("keep", "drop"), ACT: ()}
KINDS = {ASK: "manual-check", ACT: "act", DECISION: "verdict", STALE: "stale-check", APPROVE: "approval"}
PAID_KIND = "paid-approval"
MAX_NOTE_CHARS = 600
KEPT = "kept"
CLOSED = "the issue is closed"
GONE = "the prompt is no longer open on the tracker"
NOT_AN_ANSWER = "this prompt does not take that answer"
ALREADY = "the prompt is already answered on the tracker"
CHANGED = "the prompt no longer carries that box"
PAID = "a paid check is approved only with its typed confirmation"
NOTE_BLOCK = "a note may not carry a verify block"
AMBIGUOUS = "both boxes are ticked on the tracker; untick one there"
# Which of `labels(prompt)` an answer ticks.
BOX_OF = {"passed": 0, "failed": 1, "approve": 0, "drop": 0}


class Refused(Exception):
    """The answer is not written; `str(error)` is the one-line reason."""


def is_runner_prompt(marker: Marker) -> bool:
    """Whether `marker` is an owner prompt of the runner: a `verify-*` reason with `block` and `check`."""
    return (marker.kind == verify_owner.KIND and marker.fields.get("reason") in verify_owner.REASONS
            and "block" in marker.fields and "check" in marker.fields)


def is_paid(marker: Marker) -> bool:
    """Whether `marker` is an approval of a paid check."""
    return marker.fields.get("reason") == APPROVE and marker.fields.get("effects") == "paid"


def kind_of(marker: Marker) -> str:
    """The console's name for the prompt: `paid-approval` for a paid one, else its reason's kind."""
    return PAID_KIND if is_paid(marker) else KINDS[marker.fields["reason"]]


def labels(marker: Marker) -> tuple[str, ...]:
    """The runner's own answer boxes of the prompt."""
    reason = marker.fields.get("reason")
    if reason == ASK:
        return verify_owner.ACCEPT, verify_owner.REJECT
    if reason == DECISION:
        return verify_owner.PASSED, verify_owner.NOT_VERIFIED
    if reason == APPROVE:
        return (verify_owner.RUN_IT,)
    if reason == STALE:
        return (verify_owner.waive_label(marker.fields.get("host", "")),)
    return ()


def ambiguous(marker: Marker) -> bool:
    """Whether both boxes of the prompt are ticked, which the runner keeps pending."""
    boxes = labels(marker)
    return len(boxes) == 2 and verify_owner.answer(marker, *boxes) == "ambiguous"


def answered(marker: Marker, markers: Sequence[Marker]) -> bool:
    """Whether the prompt already carries the owner's answer; an ambiguous prompt does not."""
    reason = marker.fields.get("reason")
    if reason == ACT:
        return False
    if reason == APPROVE:
        return verify_owner.ticked(marker, verify_owner.RUN_IT) or verify_owner.consumed(markers, marker.comment_id)
    return verify_owner.answer(marker, *labels(marker)) in ("yes", "no")


def note_body(slug: str, issue: int, comment_id: int, note: str) -> str:
    """The comment that carries an owner's note on prompt `comment_id`."""
    return (f"Owner's note on https://github.com/{slug}/issues/{issue}#issuecomment-{comment_id}, "
            f"sent from the console:\n\n{note}")


def _check_arguments(answer: str, note: str | None) -> None:
    if (answer == "note") != (note is not None):
        raise ValueError("a note is given exactly when the answer is note")
    if note is not None and (not isinstance(note, str) or not note.strip() or len(note) > MAX_NOTE_CHARS):
        raise ValueError(f"a note is a non-blank string of at most {MAX_NOTE_CHARS} characters")


def answer_prompt(slug: str, issue: int, comment_id: int, answer: str, *,
                  note: str | None = None, paid: bool = False) -> None:
    """Write the owner's `answer` to prompt `comment_id` of `issue`: one tick, one `end` or one note."""
    _check_arguments(answer, note)
    parent = forge_api.api_get(f"repos/{slug}/issues/{issue}")
    if not isinstance(parent, dict) or not isinstance(parent.get("state"), str):
        raise ForgeError("payload_invalid", "issue reply has no state")
    if parent["state"] != "open":
        raise Refused(CLOSED)
    markers = forge_markers.list_markers(slug, issue, TRUSTED)
    prompt = next((m for m in markers if m.comment_id == comment_id), None)
    if prompt is None or not is_runner_prompt(prompt) or not forge_markers.is_live(prompt, markers):
        raise Refused(GONE)
    if answer not in ANSWERS[prompt.fields["reason"]]:
        raise Refused(NOT_AN_ANSWER)
    if answered(prompt, markers):
        raise Refused(ALREADY)
    if ambiguous(prompt):
        raise Refused(AMBIGUOUS)
    if is_paid(prompt) and answer == "approve" and not paid:
        raise Refused(PAID)
    if answer == "note":
        body = note_body(slug, issue, comment_id, note)
        if FENCE.search(body.replace("\r\n", "\n").replace("\r", "\n")):
            raise Refused(NOTE_BLOCK)
        forge_markers.post(slug, issue, body)
    elif answer == "keep":
        forge_markers.end(slug, issue, comment_id, KEPT)
    else:
        ticked = verify_owner.tick(prompt.body, labels(prompt)[BOX_OF[answer]])
        if ticked is None:
            raise Refused(CHANGED)
        forge_markers.edit(slug, comment_id, ticked)
