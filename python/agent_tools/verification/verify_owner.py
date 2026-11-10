"""The owner-prompt vocabulary of issue 631: the reasons, the check boxes, and when a prompt is settled.

A prompt is an `owner-action` marker the runner posts for a check only the owner can answer. This
module names the reasons and box labels, reads the boxes a prompt carries, finds the prompts of one
identity (an ended prompt still counts as posted) and says why a live prompt is settled. It runs no
process, reads no clock and calls no forge: every function takes the markers it judges.

Each prompt is an `owner-action` marker (`reason` `verify-ask`, `verify-approve`, `verify-act`,
`verify-decision` or `verify-stale-check`, with `block` and `check`), posted once per identity
ever, ended prompts included (plan D1), with its boxes (plan D5). Who honours a tick, how an
approve prompt is bound to its command by the `run` digest and consumed once, by the named host
only, through a `verify-run consumed=<id>` marker, and how a changed command is ended `changed` and
asked again are plan D2 and D3; approval lifts only the effects gate (D4). The outcomes, `rejected`
included, and the rule that only the owner's recorded answer or a final state settles a prompt are
D6; `act` is D10. A pass writes a `verify-seen` report marker for its host, and stale-check reads
it: a concrete host only, after 7 days, with the `unresolved` and `silent` causes and the `last`
report date (D7).

The sweep of `verify_run` (it ends the prompts the freshly read held block no longer needs and
keeps the `owner-action` label while one live marker stands) counts only a trusted (`OWNER` or
`MEMBER`) author's marker, leaves every other `owner-action` marker live and never touches
`agent:human-required` (D8). A decision whose post was lost is posted by the next pass (D13), and
`--report` touches nothing (D12). `apply_labels` removes a label an answered prompt `clears`.
"""
import hashlib
import json
import re
from collections.abc import Collection, Iterable, Mapping
from datetime import datetime, timedelta, timezone

from agent_tools.verification import verify_issues
from agent_tools.claims import forge_claim, forge_markers
from agent_tools.claims.forge_markers import Marker

KIND = forge_claim.OWNER_ACTION_KIND
LABEL = forge_claim.OWNER_ACTION
# Every reason carries the `verify-` prefix so it never names an `owner-action` reason of another writer
# (`forge_owner_action.REASONS`, issue 636, posts `decision` markers with no `block` or `check`).
ASK, APPROVE, ACT = "verify-ask", "verify-approve", "verify-act"
DECISION, STALE = "verify-decision", "verify-stale-check"
REASONS = (ASK, APPROVE, ACT, DECISION, STALE)
ACCEPT, REJECT = "Accept", "Reject"
RUN_IT = "Run it"
PASSED, NOT_VERIFIED = "Accept as passed", "Close as not verified"
STALE_AGE = timedelta(days=7)
SEEN = "verify-seen"
REPORTS = (verify_issues.RESULT, verify_issues.DUE, verify_issues.WINDOW, SEEN)


def waive_label(host: str) -> str:
    """The box of a stale-check prompt that accepts the check without `host`."""
    return f"Accept without {host}"


def last_seen(markers: Iterable[Marker], host: str) -> datetime | None:
    """When `host` last reported on this issue, or None when no report marker names it.

    Only the report kinds count: a lease, a consumption or an owner action says nothing about the
    host. A `verify-seen` marker also counts its `on` day, at 00:00 UTC."""
    seen: list[datetime] = []
    for m in markers:
        if m.kind in REPORTS and m.fields.get("host") == host:
            seen.append(m.updated_at)
            if m.kind == SEEN:
                try:
                    seen.append(datetime.strptime(m.fields.get("on", ""), "%Y-%m-%d").replace(tzinfo=timezone.utc))
                except ValueError:
                    pass
    return max(seen, default=None)


def last_report(markers: Iterable[Marker], host: str) -> str:
    """`last_seen` as a date, or `never`."""
    seen = last_seen(markers, host)
    return "never" if seen is None else f"{seen:%Y-%m-%d}"


def box(label: str, ticked: bool = False) -> str:
    """One check box line of a prompt."""
    return f"- [{'x' if ticked else ' '}] {label}"


def ticked(marker: Marker, label: str) -> bool:
    """Whether some line of the prompt after its marker line is the box `label`, ticked."""
    pattern = re.compile(rf"\s*[-*] \[[xX]\] {re.escape(label)}\s*")
    return any(pattern.fullmatch(text) for text in marker.body.split("\n")[1:])


def tick(body: str, label: str) -> str | None:
    """`body` with the first unticked box `label` after its marker line ticked, or None when there is none.

    Every other character is left as it was."""
    pattern = re.compile(rf"\s*[-*] \[ \] {re.escape(label)}\s*")
    lines = body.split("\n")
    for index in range(1, len(lines)):
        if pattern.fullmatch(lines[index]):
            lines[index] = lines[index].replace("[ ]", "[x]", 1)
            return "\n".join(lines)
    return None


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


def run_digest(run: Mapping, command: Mapping | None) -> str:
    """A short digest of the `run` a check names and the contract command entry it resolves to."""
    text = json.dumps({"run": run, "command": command}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def consumed(markers: Iterable[Marker], prompt_id: int) -> bool:
    """Whether a `verify-run` marker, live or ended, records the approve prompt `prompt_id` as consumed."""
    return any(m.kind == verify_issues.RUN and m.fields.get("consumed") == str(prompt_id) for m in markers)


def settle_reason(prompt: Marker, markers: Iterable[Marker], held_key: str | None,
                  final: Collection[str]) -> str | None:
    """Why the live `prompt` is settled, or None while it stands."""
    markers = list(markers)
    if held_key is not None and prompt.fields.get("block") != held_key:
        return "superseded"
    if prompt.fields.get("reason") in (ASK, DECISION, STALE):
        if answered(markers, prompt):
            return "answered"
        latest = verify_issues.latest_result(markers, prompt.fields["block"], int(prompt.fields["check"]))
        if latest is not None and latest.fields.get("state") in final:
            return "resolved"
    if prompt.fields.get("reason") in (APPROVE, ACT):
        if prompt.fields.get("reason") == APPROVE and consumed(markers, prompt.comment_id):
            return "consumed"
        latest = verify_issues.latest_result(markers, prompt.fields["block"], int(prompt.fields["check"]))
        if latest is not None and latest.fields.get("state") in final:
            return "resolved"
    return None
