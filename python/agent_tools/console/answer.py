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
"""

from collections.abc import Sequence

from agent_tools.claims import forge_markers as fm
from agent_tools.claims import forge_owner_action as foa
from agent_tools.system import forge_api

NOT_OPEN = "this is not an open decision prompt"
CHOOSE = "choose one option under each question"
SENDING = "an answer to this prompt is already being sent"
CLOSED = "the issue or pull request is closed"
GONE = "the prompt is no longer open on the tracker"
CHANGED = "the prompt changed on the tracker"
ALREADY = "the prompt is already answered on the tracker"


class Refused(Exception):
    """The answer was not sent; `str(error)` is the one-line reason."""


def _reduced(questions: Sequence[dict]) -> list[tuple[str, list[str]]]:
    return [(q["question"], list(q["options"])) for q in questions]


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
