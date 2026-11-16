"""What each owner check of a held block waits for (issue 1129).

A verification block is held until its checks answer. The runner posts an owner prompt only for
a check that is due, so a check that is not due has no prompt and no card; this module reads the
held block itself and says, per owner check, what it is waiting for. It reads only the context it
is given (the caller's `clock`, `reads_host=False`, `cancelled`), reads no clock of its own and
writes nothing.

Which checks wait. Only an owner check: `verify_exec.gate(check, ()).reason` is one of
`verify_run.OWNER_GATES`. A check the runner may run unattended, or one stopped at
`command_not_verification`, never yields a `Wait`: the unattended rule of
ADR-verification-003 is reused, not restated. A check with a live result yields nothing.
A live or paid check with a `command` run is assumed approvable: whether the command is a verification
command is a fact of the project contract, which the console never reads, so the line may name a
prompt the runner will refuse (`command_not_verification`).

The prompted rule (P1). A check is prompted when it has a live `ask`, `act` or `approve` prompt
(`ASKING`); a `stale` or `decision` prompt is a card of its own that asks the owner something else
and never makes the check prompted. The runner prompts a check only once `evaluate_when` reads it due,
and a met `not_before` or a dated window stays met (both date from fixed times), so a prompt means
due. A prompted check is never evaluated: no clock read, no forge read. It goes straight to the
wording rule.

The reading of an unprompted check (P9) is `verify_facts.evaluate_wait`, which reads every member
and dates a wait only when every unmet member is dated, by the latest date. `Due.reason` is
normalised: `not_before` stays; `window_not_open` with a date is `window`, without one it is
`not_released` when `days_after.event` is `released`, else `not_deployed`; `window_opening`
stays; `not_released` stays; `revision_unknown`, `revision_unpushed` and `not_deployed` are
`not_deployed`; `ci_not_passed` stays; anything else is `unknown`. `until` is set only for the
dated reasons (`DATED`).

The wording rule (P2). When the check's text (its `run.ask`, else `run.act`) states a wait
(`states_wait`) and its `when` has neither `not_before` nor `days_after`, the wait lives only in
the wording and the reason is `no_when`, prompted or not, and before any reading: no member of
`when` is evaluated, so a release that does not exist yet does not hide the missing field.
Otherwise a prompted check yields nothing and an unprompted one that is due yields `due` (P3: the
runner has not prompted it yet).

A `forge_api.ForgeError` from one check's evaluation yields `unknown` for that check and
evaluation goes on; one with code `cancelled` propagates. A check whose shape makes evaluation
raise `KeyError`, `TypeError` or `ValueError` is skipped.

`held_waits(nodes, slug, default_branch, clock, cancelled)` is the console's entry: it selects the
held block from GraphQL comment nodes and reads its waits; with no block it returns `(None, [])`
and never calls `clock`. A block the runner would refuse (`verify_block.lint_block` not ok, which
the runner reports as `block_invalid` and never prompts) also yields `(None, [])`: a wait for a
check the runner will not prompt could never come true. The console has no checkout, so the lint
runs with `StructuralReferences`, which accepts every command and script reference; the lint then
judges the block's shape only, and a reference the runner finds absent is not seen here.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_tools.system import forge_api
from agent_tools.verification import (verify_block, verify_exec, verify_facts, verify_issues, verify_owner,
                                      verify_run)

HELD_LABEL = verify_run.NEEDS
WAIT_REASONS = ("not_before", "window", "window_opening", "not_released", "not_deployed", "ci_not_passed",
                "unknown", "no_when", "due")
DATED = ("not_before", "window")
ASKING = (verify_owner.ASK, verify_owner.ACT, verify_owner.APPROVE)

NUMBER = r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fourteen|thirty)"
UNIT = r"(?:hours?|days?|weeks?|months?)"
WAIT_WORDING = re.compile(
    rf"\b{NUMBER}\s+{UNIT}\s+(?:after|from|since|past|following)\b"
    rf"|\b(?:after|in|wait(?:ing)?(?:\s+for)?)\s+{NUMBER}\s+{UNIT}\b"
    r"|\b(?:not\s+before|no\s+earlier\s+than|wait(?:ing)?\s+until)\b",
    re.IGNORECASE)

_NORMAL = {"not_before": "not_before", "window_opening": "window_opening", "not_released": "not_released",
           "revision_unknown": "not_deployed", "revision_unpushed": "not_deployed",
           "not_deployed": "not_deployed", "ci_not_passed": "ci_not_passed"}


@dataclass(frozen=True)
class Wait:
    check: int
    ac: str
    reason: str
    until: datetime | None
    prompted: bool
    text: str


class StructuralReferences:
    """The lint's lookups without a repository: every reference resolves, so only the shape is judged."""

    def command(self, command_id: str) -> str:
        return "present"

    def script(self, path: str, sha: str) -> tuple[str, str]:
        return "present", "present"

    def flake(self, merge: str) -> tuple[str, str] | None:
        return None


def states_wait(text: str) -> bool:
    """Whether the wording of a check says it waits for a time."""
    return WAIT_WORDING.search(text) is not None


def _reason(due: verify_facts.Due, when: dict) -> str:
    if due.reason == "window_not_open":
        if due.until is not None:
            return "window"
        return "not_released" if when["days_after"]["event"] == "released" else "not_deployed"
    return _NORMAL.get(due.reason, "unknown")


def _wait(index: int, check: dict, held: verify_issues.Held, ctx: verify_facts.Context) -> Wait | None:
    run = check.get("run") or {}
    text = run.get("ask") or run.get("act") or ""
    prompted = bool(verify_owner.live_prompts(held.markers, ASKING, held.key, index))
    when = check["when"]
    if states_wait(text) and "not_before" not in when and "days_after" not in when:
        return Wait(index, check["ac"], "no_when", None, prompted, text)
    if prompted:
        return None
    try:
        due = verify_facts.evaluate_wait(when, held.block["merge"], ctx)
    except forge_api.ForgeError as error:
        if error.code == "cancelled":
            raise
        return Wait(index, check["ac"], "unknown", None, prompted, text)
    if due.due:
        return Wait(index, check["ac"], "due", None, prompted, text)
    reason = _reason(due, when)
    return Wait(index, check["ac"], reason, due.until if reason in DATED else None, prompted, text)


def owner_waits(held: verify_issues.Held, ctx: verify_facts.Context) -> list[Wait]:
    """The wait of every owner check of `held` that has one, ordered by check index."""
    waits = []
    for index, check in enumerate(held.block["checks"]):
        try:
            if verify_exec.gate(check, ()).reason not in verify_run.OWNER_GATES:
                continue
            if verify_issues.latest_result(held.markers, held.key, index) is not None:
                continue
            found = _wait(index, check, held, ctx)
        except (KeyError, TypeError, ValueError):
            continue
        if found is not None:
            waits.append(found)
    return waits


def held_waits(nodes: list, slug: str, default_branch: str, clock: Callable[[], datetime],
               cancelled: Callable[[], bool] = lambda: False) -> tuple[verify_issues.Held | None, list[Wait]]:
    """The held block of an issue's GraphQL comment `nodes` and its owner checks' waits."""
    held = verify_issues.select(verify_issues.comments_from_graphql(nodes))
    if held is None or not isinstance(held.block, dict):
        return None, []
    if not verify_block.lint_block(held.block, refs=StructuralReferences())["ok"]:
        return None, []
    ctx = verify_facts.Context(slug, Path("/"), default_branch, {}, held.markers, clock=clock,
                               reads_host=False, cancelled=cancelled)
    return held, owner_waits(held, ctx)
