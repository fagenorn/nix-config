"""The owner's exclusion of a profile from the console's automatic choice (#1028).

Row. `entry(profile, excluded)` is `("profile.exclusion", None, {"profile", "excluded"})`, `KIND`
being the kind (`event_log.PROFILE_EXCLUSION`). One row records one change: `excluded` true takes
the profile out of the console's choice of a session's profile, false puts it back.

Fold. `excluded_profiles(events, excluded=frozenset())` returns the set of excluded profiles from the
`KIND` events, folded in order onto `excluded`: a payload whose `profile` is a non-empty string and
whose `excluded` is a bool (an integer is not one) adds the profile when true and removes it when
false; any other kind or payload is ignored. The last valid row of each profile wins. Folding later
events onto an earlier fold gives the fold of all of them.

Parse. `parse_request(body)` returns `(profile, excluded)` from a request body that is UTF-8 JSON
for an object whose keys are exactly `profile` and `excluded`, `profile` a non-empty string of at
most `MAX_PROFILE` (128) characters and `excluded` a bool; anything else raises `ValueError`.

Refusal. `Refused` is raised by the service with one of `UNKNOWN` (no such profile),
`ALREADY_EXCLUDED` or `ALREADY_INCLUDED`.

Retention. The kind is not in `KEPT_KINDS`, but the retention pass leaves the newest valid row of
each profile in place, whatever its age, when that row excludes the profile
(`event_log.EventLog.retain`): by the fold's own validity rule, so the folded set is the same before
and after a pass.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from agent_tools.console.event_log import PROFILE_EXCLUSION, Event

KIND = PROFILE_EXCLUSION
MAX_PROFILE = 128
UNKNOWN = "no such profile"
ALREADY_EXCLUDED = "already excluded"
ALREADY_INCLUDED = "already included"


class Refused(Exception):
    pass


def entry(profile: str, excluded: bool) -> tuple[str, None, dict]:
    return (KIND, None, {"profile": profile, "excluded": excluded})


def _valid(payload: dict) -> bool:
    profile = payload.get("profile")
    return (isinstance(profile, str) and bool(profile)
            and isinstance(payload.get("excluded"), bool))


def excluded_profiles(events: Iterable[Event],
                      excluded: frozenset[str] = frozenset()) -> frozenset[str]:
    folded = set(excluded)
    for event in events:
        if event.kind != KIND or not _valid(event.payload):
            continue
        payload = event.payload
        if payload["excluded"]:
            folded.add(payload["profile"])
        else:
            folded.discard(payload["profile"])
    return frozenset(folded)


def parse_request(body: bytes) -> tuple[str, bool]:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("the request is not UTF-8 JSON") from error
    if not isinstance(data, dict) or set(data) != {"profile", "excluded"}:
        raise ValueError("the request names exactly a profile and excluded")
    profile = data["profile"]
    if not isinstance(profile, str) or not profile or len(profile) > MAX_PROFILE:
        raise ValueError("the profile is not a name of at most 128 characters")
    if not isinstance(data["excluded"], bool):
        raise ValueError("excluded is not a bool")
    return profile, data["excluded"]
