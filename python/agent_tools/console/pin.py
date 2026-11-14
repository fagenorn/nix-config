"""The owner's pin of one profile as the console's choice of a new session (#1029, ADR-console-023).

Row. `entry(profile, pinned)` is `("profile.pin", None, {"profile", "pinned"})`, `KIND` being the
kind (`event_log.PROFILE_PIN`). One row records one change: `pinned` true makes the profile the
console's choice of a session's profile, false lifts the pin.

Fold. `pinned_profile(events, pinned=None)` returns the one pinned profile, or None, from the `KIND`
events folded in order onto `pinned`. A payload whose `profile` is a non-empty string and whose
`pinned` is a bool (an integer is not one) is valid; any other kind or payload is ignored. A valid
true row sets the pin to its profile, moving any earlier pin; a valid false row clears the pin only
when its profile is the pinned one, else it changes nothing. Folding later events onto an earlier
fold gives the fold of all of them.

Launches under the pin. `pin_launches(events, state=None)` returns a `PinLaunches(pinned, seen,
launched, awaiting)` folded in order onto `state`: a `KIND` row moves `pinned` by the rule above; a
`session.hook` or `session.seen` row whose `session_id` is a string not yet in `seen` is the
session's start: it adds the session to `seen` and, while `pinned` is not None, to `awaiting` as
`(session, pinned)`; a `session.seen` or `session.profile` row whose `session_id` is in `awaiting`
and whose payload `profile` is a string removes it from `awaiting` and adds that profile to
`launched` when it equals the pin the session started under (a `session.hook` row carries no
profile); a later row of a session already in `seen` starts nothing; a `manager.started` row whose
payload `profile` is a string equal to the current `pinned` adds it to `launched`. Every other row
adds nothing, so a session that started before the pin is never a launch under it. `launched` only grows, and folding later events
onto an earlier state gives the fold of all of them. It is the evidence the host check reads (P9):
it cannot tell whether the pin had room, nor whether a launch used `CLAUDE_ACCOUNT`.

Parse. `parse_request(body)` returns `(profile, pinned)` from a request body that is UTF-8 JSON for
an object whose keys are exactly `profile` and `pinned`, `profile` a non-empty string of at most
`MAX_PROFILE` (128) characters and `pinned` a bool; anything else raises `ValueError`.

Refusal. `Refused` is raised by the service with one of `UNKNOWN` (no such profile), `EXCLUDED`
(the profile is excluded), `ALREADY_PINNED` or `NOT_PINNED`.

Note. `note(pinned, capacity, chosen)` is None when `pinned` is None; otherwise `{"profile", "in_effect",
"reason", "until", "instead"}` for the capacity entry named `pinned` (None when absent). `in_effect`
is whether that entry exists and `manager.has_room` holds. In effect, `reason`, `until` and
`instead` are None. Otherwise `instead` is `chosen` and `reason` is, first match winning,
`NOT_LISTED` (no entry), `EXCLUDED_NOW` (the entry is excluded), `SIGNED_OUT` (its sign-in is
`signed_out`), `OUT` (its state is `out`; `until` is then its `out_until`) or `NO_READING`; `until`
is None except for `OUT`.

Retention. The kind is not in `KEPT_KINDS`, but the retention pass leaves, whatever its age, the
newest valid pinning row when no later row unpins the same profile (`event_log.EventLog.retain`):
by the fold's own validity rule, so the folded pin is the same before and after a pass.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from agent_tools.console import manager
from agent_tools.console.event_log import (
    MANAGER_STARTED, PROFILE_PIN, SESSION_HOOK, SESSION_PROFILE, SESSION_SEEN, Event)

KIND = PROFILE_PIN
MAX_PROFILE = 128
UNKNOWN = "no such profile"
EXCLUDED = "excluded; include it first"
ALREADY_PINNED = "already pinned"
NOT_PINNED = "not pinned"
OUT = "out of allowance"
SIGNED_OUT = "signed out"
NO_READING = "no reading yet"
EXCLUDED_NOW = "excluded"
NOT_LISTED = "not a listed account"


class Refused(Exception):
    pass


@dataclass(frozen=True)
class PinLaunches:
    pinned: str | None
    seen: frozenset[str]
    launched: frozenset[str]
    awaiting: frozenset[tuple[str, str]] = frozenset()


def entry(profile: str, pinned: bool) -> tuple[str, None, dict]:
    return (KIND, None, {"profile": profile, "pinned": pinned})


def _valid(payload: dict) -> bool:
    profile = payload.get("profile")
    return (isinstance(profile, str) and bool(profile)
            and isinstance(payload.get("pinned"), bool))


def _moved(pinned: str | None, event: Event) -> str | None:
    if event.kind != KIND or not _valid(event.payload):
        return pinned
    payload = event.payload
    if payload["pinned"]:
        return payload["profile"]
    return None if payload["profile"] == pinned else pinned


def pinned_profile(events: Iterable[Event], pinned: str | None = None) -> str | None:
    for event in events:
        pinned = _moved(pinned, event)
    return pinned


def pin_launches(events: Iterable[Event], state: PinLaunches | None = None) -> PinLaunches:
    pinned, seen, launched, awaiting = (
        (None, frozenset(), frozenset(), frozenset()) if state is None
        else (state.pinned, state.seen, state.launched, state.awaiting))
    seen, launched, awaiting = set(seen), set(launched), dict(awaiting)
    for event in events:
        if event.kind == KIND:
            pinned = _moved(pinned, event)
            continue
        profile = event.payload.get("profile")
        if event.kind == MANAGER_STARTED:
            if pinned is not None and isinstance(profile, str) and profile == pinned:
                launched.add(profile)
            continue
        if event.kind not in (SESSION_HOOK, SESSION_SEEN, SESSION_PROFILE):
            continue
        session = event.payload.get("session_id")
        if not isinstance(session, str):
            continue
        if event.kind != SESSION_PROFILE and session not in seen:
            seen.add(session)
            if pinned is not None:
                awaiting[session] = pinned
        if isinstance(profile, str) and event.kind != SESSION_HOOK:
            under = awaiting.pop(session, None)
            if under is not None and profile == under:
                launched.add(profile)
    return PinLaunches(pinned, frozenset(seen), frozenset(launched),
                       frozenset(awaiting.items()))


def parse_request(body: bytes) -> tuple[str, bool]:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("the request is not UTF-8 JSON") from error
    if not isinstance(data, dict) or set(data) != {"profile", "pinned"}:
        raise ValueError("the request names exactly a profile and pinned")
    profile = data["profile"]
    if not isinstance(profile, str) or not profile or len(profile) > MAX_PROFILE:
        raise ValueError("the profile is not a name of at most 128 characters")
    if not isinstance(data["pinned"], bool):
        raise ValueError("pinned is not a bool")
    return profile, data["pinned"]


def note(pinned: str | None, capacity: Mapping, chosen: str | None) -> dict | None:
    if pinned is None:
        return None
    found = next((e for e in capacity["profiles"] if e["profile"] == pinned), None)
    if found is not None and manager.has_room(found):
        return {"profile": pinned, "in_effect": True, "reason": None, "until": None,
                "instead": None}
    until = None
    if found is None:
        reason = NOT_LISTED
    elif found.get("excluded"):
        reason = EXCLUDED_NOW
    elif (found.get("signin") or {}).get("state") == "signed_out":
        reason = SIGNED_OUT
    elif found["state"] == "out":
        reason, until = OUT, found.get("out_until")
    else:
        reason = NO_READING
    return {"profile": pinned, "in_effect": False, "reason": reason, "until": until,
            "instead": chosen}
