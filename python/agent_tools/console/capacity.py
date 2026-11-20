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

`capacity_state` folds readings onto the last reading per profile (`readings`), the newest reading
per profile and proxy account id (`kept[profile][account]`, the id None among them), and the
profile each id was last seen with (`accounts[account] = profile`, last wins); other kinds and
malformed payloads are ignored. `CapacityState(readings, accounts)` leaves `kept` empty, and a
profile then holds only its last reading.

`profile_capacity` returns `{"profile", "state", "week_left", "five_hour_left", "week_reset",
"five_hour_reset", "next_reset", "out_until", "read_at"}`, every time an ISO 8601 UTC string.
`week_reset` and `five_hour_reset` are each window's effective reset (below) while it is still
ahead, else null (also when the window is absent from the reading); the owner's page does not draw
them, the guest pool does (#1341). A window's effective reset is its own
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
and, when refused, the refusal reset (null when none is known, when an out window's own reset is
unknown, since the account is then out past every known reset, when the refusal's own reset is
unknown, or when not out); `next_reset` the
earliest reset still ahead.

`left_candidate(state, profile, folded)` is the reading the profile took under the account it is
about to leave (`signin.entry`'s `left_seq` and `reading_account`): the oldest reading it holds above
the folded `account_seq` that does not carry the folded `left_reading` id (skipped only while the
folded `left_account` differs from its `account`), else None.

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
Each entry also carries three members after `"pinned"` (#1036), always present, in this order.
`"account"` is the account name the entry's sign-in reading holds when its state is "signed_in" or
"unknown" (a failed status read does not forget it), else None. `"same_account_as"` is the sorted names of the other entries with the same non-null
account, `[]` when none. `"duplicate_of"` is, for every entry of an account shared by two or more
entries other than the counted one, the counted entry's name, else None. A profile's reading counts
only when it was taken under its current account: of the readings the profile holds (`kept` and
the last) a reading is dropped when its sign-in has an `account_seq` and the reading's `seq` is
not above it (a profile that switched account has no reading until its next one), or when the
sign-in names a `left_account` other than its account and the reading carries the proxy account id
`left_reading` (a late reply of the account it left), shared account or not; the profile's counted
reading is the newest left. A reading that was taken under the account a profile left (the
reading with that id, or with `seq` equal to `account_seq` when the id is None) belongs to that
`left_account`, whichever profile has it now. The account's reading is the newest, by `seq`, of
the counted readings of all of the group's entries, excluded and pinned ones included, and the
readings left under it by profiles that moved away, and every entry of the group takes its
capacity members from it, so which profile took the reading
never decides what the account has left. The counted entry is the minimum by (excluded, not
pinned, name); choosing it never changes the reading, it only decides which profile is launched and
drawn. Every aggregate is evaluated over the entries that are not signed out, not excluded and not
a duplicate, so one account's allowance is counted once.
"""

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
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
    kept: dict[str, dict[str | None, Reading]] = field(default_factory=dict)


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
    kept = {name: dict(held) for name, held in state.kept.items()} if state else {}
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
        kept.setdefault(profile, {})[report["account"]] = readings[profile]
        if report["account"] is not None:
            accounts[report["account"]] = profile
    return CapacityState(readings, accounts, kept)


def _iso(seconds: int | None) -> str | None:
    return None if seconds is None else datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def profile_capacity(profile: str, reading: Reading | None, now: float) -> dict:
    if reading is None:
        return {"profile": profile, "state": "unknown", "week_left": None,
                "five_hour_left": None, "week_reset": None, "five_hour_reset": None,
                "next_reset": None, "out_until": None, "read_at": None}
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
    week_reset, five_hour_reset = (
        _iso(r) if r is not None and r > now else None for r in (resets.get("7d"), resets.get("5h")))
    known_out = [r for r in out_resets if r is not None]
    if refused and stopped is not None:
        known_out.append(stopped)
    ahead = [r for r in (*resets.values(), reading.reset) if r is not None and r > now]
    return {
        "profile": profile,
        "state": state,
        "week_left": left.get("7d"),
        "five_hour_left": left.get("5h"),
        "week_reset": week_reset,
        "five_hour_reset": five_hour_reset,
        "next_reset": _iso(min(ahead)) if ahead else None,
        "out_until": (_iso(max(known_out))
                      if out and known_out and None not in out_resets
                      and not (refused and stopped is None) else None),
        "read_at": reading.at,
    }


def _pool(state: CapacityState, name: str) -> list[Reading]:
    """Every reading the profile holds: its newest per proxy account id, and its last."""
    pool = list(state.kept.get(name, {}).values())
    last = state.readings.get(name)
    if last is not None and all(held.seq != last.seq for held in pool):
        pool.append(last)
    return pool


def left_candidate(state: CapacityState, name: str,
                   folded: signin_state.SignIn | None) -> Reading | None:
    """The reading the profile took under the account it is about to leave, else None.

    The oldest of the readings it holds above the folded sign-in's `account_seq` and not carrying
    its `left_reading` id while that left account is not the one it is on again (a left account it
    has signed back in to is inactive, so its id skips nothing): the profile was on that account
    when the boundary was set, so its first reading after it was taken there, while a newer one
    may already be the next account's (the account changed before the status was read).
    """
    boundary = (folded.account_seq or 0) if folded is not None else 0
    left = _left(folded)
    skip = left[1] if left is not None else None
    return min((r for r in _pool(state, name)
                if r.seq > boundary and (skip is None or r.account != skip)),
               key=lambda r: r.seq, default=None)


def _left(one: signin_state.SignIn | None) -> tuple[str, str | None] | None:
    """The account the profile left and the proxy account id its readings carried, else None."""
    if one is None or one.left_account is None or one.left_account == one.account:
        return None
    return one.left_account, one.left_reading


def _current(reading: Reading, one: signin_state.SignIn | None,
             left: tuple[str, str | None] | None) -> bool:
    """Whether the reading was taken under the profile's current account."""
    if one is not None and one.account_seq is not None and reading.seq <= one.account_seq:
        return False
    return not (left is not None and left[1] is not None and reading.account == left[1])


def _of_left(reading: Reading, one: signin_state.SignIn, left: tuple[str, str | None]) -> bool:
    """Whether the reading was taken under the account the profile left."""
    if left[1] is not None:
        return reading.account == left[1]
    return reading.seq == one.account_seq


def capacity_view(profiles: Iterable[str], state: CapacityState, now: float,
                  signins: Mapping[str, signin_state.SignIn] | None = None,
                  excluded: Collection[str] = frozenset(),
                  pinned: str | None = None) -> dict:
    names = sorted(set(profiles))
    signins = signins or {}
    counted: dict[str, Reading | None] = {}
    left_readings: dict[str, list[Reading]] = {}
    entries = []
    for name in names:
        one = signins.get(name)
        left = _left(one)
        pool = _pool(state, name)
        counted[name] = max((r for r in pool if _current(r, one, left)), key=lambda r: r.seq,
                            default=None)
        if left is not None:
            left_readings.setdefault(left[0], []).extend(
                r for r in pool if _of_left(r, one, left))
        entries.append({**profile_capacity(name, counted[name], now),
                        "signin": signin_state.profile_signin(one, now),
                        "excluded": name in excluded,
                        "pinned": name == pinned,
                        "account": one.account if one is not None
                        and one.state in ("signed_in", "unknown") else None,
                        "same_account_as": [],
                        "duplicate_of": None})
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        if entry["account"] is not None:
            groups.setdefault(entry["account"], []).append(entry)
    for account, group in groups.items():
        held = [counted[e["profile"]] for e in group if counted[e["profile"]] is not None]
        held.extend(left_readings.get(account, ()))
        newest = max(held, key=lambda r: r.seq) if held else None
        keeper = min(group, key=lambda e: (e["excluded"], not e["pinned"], e["profile"]))
        for entry in group:
            entry.update(profile_capacity(entry["profile"], newest, now))
            entry["same_account_as"] = sorted(e["profile"] for e in group if e is not entry)
            if entry is not keeper:
                entry["duplicate_of"] = keeper["profile"]
    considered = [entry for entry in entries
                  if entry["signin"]["state"] != "signed_out" and not entry["excluded"]
                  and entry["duplicate_of"] is None]
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
