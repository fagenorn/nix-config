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
"rejected" and its reset is unknown or still ahead. `state` is "out" when refused or any window is
out; "reset" when there is a window and every window has passed (or there is no window and the
report's reset has passed); else "ok"; a profile with no reading is "unknown" with every other member
null. `out_until` is the latest known reset among the out windows and, when refused, the report's
reset (null when none is known, or when not out); `next_reset` the earliest reset still ahead.

`capacity_view` returns `{"tight", "all_out", "resumes_at", "profiles": [<profile_capacity>]}` over
every named profile and every profile with a reading, sorted. `tight` is true when exactly one
profile has room (state "ok" or "reset") among at least two; `all_out` when there is a profile and
every one is out; `resumes_at` the earliest `out_until` then, null when none is known.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

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


def report_entries(report: dict, profile: str) -> list[tuple[str, None, dict]]:
    """The `capacity.reading` entry for a parsed report, plus a `capacity.stop` when it is a refusal."""
    entries: list[tuple[str, None, dict]] = [(READING, None, {**report, "profile": profile})]
    if _refusal(report):
        windows = report["windows"]
        name = report["binding"]
        if name is None:
            name = next((w for w in ("7d", "5h")
                         if windows.get(w, {}).get("status") == "rejected"), None)
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
    refused = reading.status == "rejected" and (reading.reset is None or now < reading.reset)
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
    if refused and reading.reset is not None:
        known_out.append(reading.reset)
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


def capacity_view(profiles: Iterable[str], state: CapacityState, now: float) -> dict:
    names = sorted(set(profiles) | set(state.readings))
    entries = [profile_capacity(name, state.readings.get(name), now) for name in names]
    room = sum(entry["state"] in ("ok", "reset") for entry in entries)
    all_out = bool(entries) and all(entry["state"] == "out" for entry in entries)
    until = [entry["out_until"] for entry in entries if entry["out_until"] is not None]
    return {
        "tight": room == 1 and len(entries) >= 2,
        "all_out": all_out,
        "resumes_at": min(until) if all_out and until else None,
        "profiles": entries,
    }


EMPTY = capacity_view((), CapacityState({}, {}), 0.0)
