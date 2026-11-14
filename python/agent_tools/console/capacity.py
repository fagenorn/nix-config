"""The console's capacity: what each profile's last limit reading says it has left (#860).

Nothing here reads a clock, a file or the environment: `now` is always an argument.

Events: the cache proxy reports one reading per reply that carried the unified limit headers.
`capacity.reading` (project `None`) has the payload

    {"profile": "<name>", "http_status": 429, "status": "rejected", "reset": 1794816000,
     "binding": "7d", "claim": "seven_day", "account": "<id>" | null, "session_id": "<id>" | null,
     "windows": {"7d": {"status": "rejected", "utilization": 1.0, "reset": 1794816000},
                 "5h": {"status": "allowed", "utilization": 0.0, "reset": 1794430800}}}

and `capacity.stop` (project `None`) is added beside it when the reply was a refusal
(`http_status` 429 with `status` "rejected"), with the payload `{"profile", "window", "reset"}`:
`window` is `binding` when set, else the first of "7d", "5h" whose window status is "rejected",
else null; `reset` is that window's reset when known, else the report's `reset`.

`parse_report` validates the proxy's report and returns only the members above, raising
`ValueError` when it is not one: an object; `http_status` an int in 100..599; `status` a token
(`^[a-z0-9_]{1,40}$`); `reset` an int with `0 < reset < 10**11`, or null; `binding` "5h", "7d" or
null; `claim` a token or null; `account` and `session_id` matching `^[A-Za-z0-9-]{1,64}$` or null;
`windows` an object of the keys "5h" and "7d", each `{"status": token | null, "utilization":
number with 0 <= u <= 10 and not a bool | null, "reset": int as above | null}`. Any other member,
anywhere, is dropped and never stored. These bounds are exactly those the proxy's producer
normalizes to, so every document it can produce passes unchanged.

`capacity_state` folds readings onto the last reading per profile and the account each profile was
last seen with (`accounts[account] = profile`, last wins); other kinds and malformed payloads are
ignored.

`profile_capacity` returns `{"profile", "state", "week_left", "five_hour_left", "next_reset",
"out_until", "read_at"}`, every time an ISO 8601 UTC string. A window's effective reset is its own
`reset` when known, else the reading's `reset` (a refused window that lost its own reset would
otherwise stay out forever, since no request is made while out). A window whose effective reset has
passed reads 100 left and is not out, never its stale utilization; otherwise its left is
`round(100 * max(0, 1 - utilization))`, null when the utilization is unknown, and it is out when its
status is "rejected" or its utilization is at least 1. The reading is refused when its status is
"rejected" and its refusal reset is unknown or still ahead; that reset is the report's `reset`, else
the reset of the window the refusal names (`binding`, else the first of "7d", "5h" that is
"rejected"), so a window that has reset clears a refusal whose top-level reset was lost. `state` is
"out" when refused or any window is out; "reset" when there is a window and every window has passed
(or there is no window and the report's reset has passed); else "ok"; a profile with no reading is
"unknown" with every other member null. `out_until` is the latest known reset among the out windows
and, when refused, the refusal reset (null when none is known, or when not out); `next_reset` the
earliest reset still ahead.

`capacity_view(profiles, state, now, signins=None, excluded=frozenset(), pinned=None)` returns `{"tight", "all_out", "resumes_at",
"no_reading", "profiles": [<profile_capacity>]}` over
exactly the named profiles, sorted: the configured ones, so a profile removed with
`claude-account rm` stops counting at once while its readings stay in the log and the fold. `tight`
is true when exactly one profile has room (state "ok" or "reset") among at least two and every
other profile is out, so a profile with no reading never makes it tight; `all_out` when there is a
profile and every one is out; `resumes_at` the earliest `out_until` then, null when none is known;
`no_reading` is "<n> with no reading yet" over the profiles in state "unknown", null when none.

Each profile entry also carries `"signin"` (#1010): `signin.profile_signin(signins.get(name), now)`
for the optional `signins` argument, the unknown sign-in when it is None or holds no entry for the
profile. A profile whose `signin["state"]` is "signed_out" is left out of the room count, the
no-reading count, `all_out`, `resumes_at` and `tight`, which are evaluated over the other entries
exactly as above (`tight` still needs at least two of them): its client cannot make a request, so
an old reading of it gives no room, and it is not a profile that merely has no reading. It stays in
`profiles`, its reading kept. Without `signins` every result is the same apart from that member.

Each entry also carries `"excluded"` (#1028): whether its name is in the optional `excluded`
collection, always present, after `"signin"`. An excluded profile is left out of the room count,
the no-reading count, `all_out`, `resumes_at` and `tight` as a signed-out entry is, and stays in
`profiles` with its reading and sign-in kept. Without `excluded` every result is the same apart
from that member.

Each entry also carries `"pinned"` (#1029): whether its name is the optional `pinned` name (the
owner's pin, ADR-console-023), always present, after `"excluded"`. It marks the entry for the
session-profile rule (`manager.session_profile`) and changes no aggregate: `tight`, `all_out`,
`resumes_at` and `no_reading` are the same with or without it.
"""

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from agent_tools.console import signin as signin_state
from agent_tools.console.event_log import Event

READING = "capacity.reading"
STOP = "capacity.stop"
WINDOWS = ("5h", "7d")
MAX_RESET = 10**11
MAX_UTILIZATION = 10

_TOKEN = re.compile(r"[a-z0-9_]{1,40}")
_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


@dataclass(frozen=True)
class Reading:
    profile: str
    account: str | None
    session_id: str | None
    http_status: int
    status: str
    reset: int | None
    binding: str | None
    claim: str | None
    windows: dict
    seq: int
    at: str


@dataclass(frozen=True)
class CapacityState:
    readings: dict[str, Reading]
    accounts: dict[str, str]


def _token(value: object, name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and _TOKEN.fullmatch(value):
        return value
    raise ValueError(f"{name} is not a token")


def _identifier(value: object, name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and _ID.fullmatch(value):
        return value
    raise ValueError(f"{name} is not an identifier")


def _reset(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and 0 < value < MAX_RESET:
        return value
    raise ValueError(f"{name} is not a reset time")


def _utilization(value: object) -> float | None:
    if value is None:
        return None
    if (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 <= value <= MAX_UTILIZATION):
        return value
    raise ValueError("utilization is out of range")


def _window(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"window {name} is not an object")
    return {"status": _token(value.get("status"), f"{name} status"),
            "utilization": _utilization(value.get("utilization")),
            "reset": _reset(value.get("reset"), f"{name} reset")}


def parse_report(document: object) -> dict:
    """The whitelisted members of the proxy's report; `ValueError` when it is not one."""
    if not isinstance(document, dict):
        raise ValueError("a report is an object")
    http_status = document.get("http_status")
    if not isinstance(http_status, int) or isinstance(http_status, bool) \
            or not 100 <= http_status <= 599:
        raise ValueError("http_status is not an HTTP status")
    status = _token(document.get("status"), "status")
    if status is None:
        raise ValueError("status is required")
    binding = document.get("binding")
    if binding is not None and binding not in WINDOWS:
        raise ValueError("binding is not a window")
    windows = document.get("windows", {})
    if not isinstance(windows, dict):
        raise ValueError("windows is not an object")
    return {
        "http_status": http_status,
        "status": status,
        "reset": _reset(document.get("reset"), "reset"),
        "binding": binding,
        "claim": _token(document.get("claim"), "claim"),
        "account": _identifier(document.get("account"), "account"),
        "session_id": _identifier(document.get("session_id"), "session_id"),
        "windows": {name: _window(windows[name], name) for name in WINDOWS if name in windows},
    }


def _refusal(report: dict) -> bool:
    return report["http_status"] == 429 and report["status"] == "rejected"


def _stopped_window(binding: str | None, windows: dict) -> str | None:
    """The window a refusal names: `binding`, else the first of "7d", "5h" that is "rejected"."""
    if binding is not None:
        return binding
    return next((w for w in ("7d", "5h") if windows.get(w, {}).get("status") == "rejected"), None)


def report_entries(report: dict, profile: str) -> list[tuple[str, None, dict]]:
    """The `capacity.reading` entry for a parsed report, plus a `capacity.stop` when it is a refusal."""
    entries: list[tuple[str, None, dict]] = [(READING, None, {**report, "profile": profile})]
    if _refusal(report):
        windows = report["windows"]
        name = _stopped_window(report["binding"], windows)
        reset = windows.get(name, {}).get("reset") if name is not None else None
        if reset is None:
            reset = report["reset"]
        entries.append((STOP, None, {"profile": profile, "window": name, "reset": reset}))
    return entries


def capacity_state(events: Iterable[Event], state: CapacityState | None = None) -> CapacityState:
    readings = dict(state.readings) if state else {}
    accounts = dict(state.accounts) if state else {}
    for event in events:
        if event.kind != READING:
            continue
        profile = event.payload.get("profile")
        if not isinstance(profile, str) or not profile:
            continue
        try:
            report = parse_report(event.payload)
        except ValueError:
            continue
        readings[profile] = Reading(
            profile, report["account"], report["session_id"], report["http_status"],
            report["status"], report["reset"], report["binding"], report["claim"],
            report["windows"], event.seq, event.at)
        if report["account"] is not None:
            accounts[report["account"]] = profile
    return CapacityState(readings, accounts)


def _iso(seconds: int | None) -> str | None:
    return None if seconds is None else datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def profile_capacity(profile: str, reading: Reading | None, now: float) -> dict:
    if reading is None:
        return {"profile": profile, "state": "unknown", "week_left": None,
                "five_hour_left": None, "next_reset": None, "out_until": None, "read_at": None}
    left: dict[str, int | None] = {}
    resets: dict[str, int | None] = {}
    passed: dict[str, bool] = {}
    out_resets: list[int | None] = []
    for name, window in reading.windows.items():
        reset = window["reset"] if window["reset"] is not None else reading.reset
        utilization = window["utilization"]
        has_passed = reset is not None and now >= reset
        resets[name] = reset
        passed[name] = has_passed
        left[name] = 100 if has_passed else (
            None if utilization is None else round(100 * max(0.0, 1.0 - utilization)))
        if not has_passed and (window["status"] == "rejected"
                               or (utilization is not None and utilization >= 1.0)):
            out_resets.append(reset)
    stopped = reading.reset
    if stopped is None:
        name = _stopped_window(reading.binding, reading.windows)
        stopped = reading.windows.get(name, {}).get("reset") if name is not None else None
    refused = reading.status == "rejected" and (stopped is None or now < stopped)
    out = refused or bool(out_resets)
    if out:
        state = "out"
    elif passed and all(passed.values()):
        state = "reset"
    elif not passed and reading.reset is not None and now >= reading.reset:
        state = "reset"
    else:
        state = "ok"
    known_out = [r for r in out_resets if r is not None]
    if refused and stopped is not None:
        known_out.append(stopped)
    ahead = [r for r in (*resets.values(), reading.reset) if r is not None and r > now]
    return {
        "profile": profile,
        "state": state,
        "week_left": left.get("7d"),
        "five_hour_left": left.get("5h"),
        "next_reset": _iso(min(ahead)) if ahead else None,
        "out_until": _iso(max(known_out)) if out and known_out else None,
        "read_at": reading.at,
    }


def capacity_view(profiles: Iterable[str], state: CapacityState, now: float,
                  signins: Mapping[str, signin_state.SignIn] | None = None,
                  excluded: Collection[str] = frozenset(),
                  pinned: str | None = None) -> dict:
    names = sorted(set(profiles))
    signins = signins or {}
    entries = [{**profile_capacity(name, state.readings.get(name), now),
                "signin": signin_state.profile_signin(signins.get(name), now),
                "excluded": name in excluded,
                "pinned": name == pinned}
               for name in names]
    considered = [entry for entry in entries
                  if entry["signin"]["state"] != "signed_out" and not entry["excluded"]]
    room = sum(entry["state"] in ("ok", "reset") for entry in considered)
    unknown = sum(entry["state"] == "unknown" for entry in considered)
    all_out = bool(considered) and all(entry["state"] == "out" for entry in considered)
    until = [entry["out_until"] for entry in considered if entry["out_until"] is not None]
    return {
        "tight": len(considered) >= 2 and room == 1 and all(
            entry["state"] == "out" for entry in considered
            if entry["state"] not in ("ok", "reset")),
        "all_out": all_out,
        "resumes_at": min(until) if all_out and until else None,
        "no_reading": f"{unknown} with no reading yet" if unknown else None,
        "profiles": entries,
    }


EMPTY = capacity_view((), CapacityState({}, {}), 0.0)
