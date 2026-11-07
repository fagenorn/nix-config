"""The owner-prompt vocabulary of issue 631: the reasons, the check boxes, and when a prompt is settled.

A prompt is an `owner-action` marker the runner posts for a check only the owner can answer. This
module names the reasons and box labels, reads the boxes a prompt carries, finds the prompts of one
identity (an ended prompt still counts as posted) and says why a live prompt is settled. It runs no
process, reads no clock and calls no forge: every function takes the markers it judges.
"""
import re
from collections.abc import Collection, Iterable, Mapping

from agent_tools import forge_claim, forge_markers, verify_issues
from agent_tools.forge_markers import Marker

KIND = forge_claim.OWNER_ACTION_KIND
LABEL = forge_claim.OWNER_ACTION
ASK, APPROVE, ACT, DECISION, STALE = "ask", "approve", "act", "decision", "stale-check"
REASONS = (ASK, APPROVE, ACT, DECISION, STALE)
ACCEPT, REJECT = "Accept", "Reject"
RUN_IT = "Run it"
PASSED, NOT_VERIFIED = "Accept as passed", "Close as not verified"


def box(label: str, ticked: bool = False) -> str:
    """One check box line of a prompt."""
    return f"- [{'x' if ticked else ' '}] {label}"


def ticked(marker: Marker, label: str) -> bool:
    """Whether some line of the prompt after its marker line is the box `label`, ticked."""
    pattern = re.compile(rf"\s*[-*] \[[xX]\] {re.escape(label)}\s*")
    return any(pattern.fullmatch(text) for text in marker.body.split("\n")[1:])


def answer(marker: Marker, yes: str, no: str | None = None) -> str | None:
    """`"ambiguous"` when both boxes are ticked, `"yes"` or `"no"` when exactly one is, else None."""
    said_yes = ticked(marker, yes)
    said_no = no is not None and ticked(marker, no)
    if said_yes and said_no:
        return "ambiguous"
    if said_yes:
        return "yes"
    return "no" if said_no else None


def same_identity(markers: Iterable[Marker], match: Mapping[str, str]) -> list[Marker]:
    """Every prompt, live or ended, whose fields contain every `match` pair, ascending id."""
    return sorted((m for m in markers if m.kind == KIND
                   and all(m.fields.get(k) == v for k, v in match.items())),
                  key=lambda m: m.comment_id)


def prompts(markers: Iterable[Marker], reason: str, block: str, check: int) -> list[Marker]:
    """The prompts of `reason` posted for the check of block version `block`, live or ended."""
    return same_identity(markers, {"reason": reason, "block": block, "check": str(check)})


def live_prompts(markers: Iterable[Marker], reasons: Collection[str], block: str, check: int) -> list[Marker]:
    """The live prompts of any of `reasons` for the check of block version `block`, ascending id."""
    markers = list(markers)
    return sorted((m for m in markers if m.kind == KIND and m.fields.get("reason") in reasons
                   and m.fields.get("block") == block and m.fields.get("check") == str(check)
                   and forge_markers.is_live(m, markers)), key=lambda m: m.comment_id)


def answered(markers: Iterable[Marker], prompt: Marker) -> bool:
    """Whether a live result of the prompt's check names the prompt as the owner's answer."""
    markers = list(markers)
    return any(m.kind == verify_issues.RESULT and m.fields.get("block") == prompt.fields.get("block")
               and m.fields.get("check") == prompt.fields.get("check")
               and m.fields.get("owner") == str(prompt.comment_id) and forge_markers.is_live(m, markers)
               for m in markers)


def settle_reason(prompt: Marker, markers: Iterable[Marker], held_key: str | None,
                  final: Collection[str]) -> str | None:
    """Why the live `prompt` is settled, or None while it stands."""
    markers = list(markers)
    if held_key is not None and prompt.fields.get("block") != held_key:
        return "superseded"
    if prompt.fields.get("reason") == ASK:
        if answered(markers, prompt):
            return "answered"
        latest = verify_issues.latest_result(markers, prompt.fields["block"], int(prompt.fields["check"]))
        if latest is not None and latest.fields.get("state") in final:
            return "resolved"
    return None
