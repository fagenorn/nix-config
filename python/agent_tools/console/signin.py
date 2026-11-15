"""The console's sign-in reader: whether each profile's client is signed in, and until when (#1010).

Command. `status_command()` is `claude-account run auth status --json`. The client answers with one
JSON object on stdout and exits 0 when signed in, 1 when not. The client's own login answers;
nothing here reads a credential, and nothing reads a clock (`now` is an argument).

Environment. `status_environment(profile, environ)` is `manager.client_environment(profile,
environ)` without `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN`, and with
`CLAUDE_CACHE_PROXY=0` (over any inherited value): the status command sends no request, so it must
not wait on, or be refused for, the cache proxy.

Runner. `read_status(probe, *, run, environ, timeout)` calls `run` once, by default
`manager.run_in_own_group`, never plain `subprocess.run`: in a new empty temporary directory
(`console-signin-*`, removed after the call), with no terminal (`stdin` and `stderr` to the null
device, `stdout` piped), in its own session, within `timeout` (`STATUS_TIMEOUT`, 30) seconds. When
`probe.stop` is set it is passed as `cancel=`, as `probe.run_probe` does. It opens no file of its
own besides the temporary directory.

Parse. `parse_status(returncode, stdout)` returns a `Status(state, ends_at, account)`. A return code that is
neither 0 nor 1 is `StatusFailed("exited")`. Otherwise stdout must decode as UTF-8 JSON to an
object whose `loggedIn` is a bool, else `unreadable`. `(0, loggedIn true)` is `signed_in`, its
`ends_at` None when `loginExpiresAt` is absent or null, else that string (a trailing `Z` read as
`+00:00`, an offset required) as `astimezone(utc).isoformat()`; any other value, or a string that
does not parse, is `unreadable`. `(1, loggedIn false)` is `signed_out` with `ends_at` None whatever
`loginExpiresAt` holds. `(0, false)` and `(1, true)` are `unreadable`. The address (the document's
top-level `email`) is kept as `account` for `(0, loggedIn true)` only when `valid_account(email)`
(#1036); an absent, null or invalid `email` leaves `account` None and never changes the state or
raises, and `signed_out` always has `account` None. Every other member (the organisation, the plan,
any token-shaped member) is dropped, never stored. `valid_account(value)` is True only for a `str` of
1 to `MAX_ACCOUNT_CHARS` (320) characters, each in 0x21 to 0x7E.

Failures are `StatusFailed(kind)` with `kind` one of `KINDS`, and `str(error) == kind`:
`not_installed` (`claude-account` is not on `PATH`), `timed_out`, `unavailable` (any other
`OSError`), `exited`, `unreadable`. `reader_for(platform)` is `read_status` where
`manager.supported(platform)`, else None.

Event. `entry(profile, status, folded=None, reading_seq=None)` is `("signin.reading", None,
{"profile", "state", "ends_at", "account", "account_seq"})`, `READING` being the kind. `account` is
`status.account` when the status is `signed_in`, the folded sign-in's `account` when the status is
`unknown` and there is a folded sign-in (a failed read does not forget the account), else None.
`account_seq` is where the profile's capacity readings begin for that account: on a switch it is
`reading_seq` (the profile's newest capacity reading's seq, 0 when there is none), else the folded
`account_seq` when it is not None, else 0. A switch is a non-None `account` that differs from the
folded sign-in's `account` when there is a folded sign-in and either its `account_seq` is not None
or its state is `signed_out`; a row from before #1036 (no `account_seq`) followed by a first account
is no switch, so the deploy invalidates no reading. Every row carries its own boundary. The kind is not in `KEPT_KINDS`, but retention leaves the newest row of each
profile in place (`event_log.SIGNIN_READING`): only changes are recorded, so an unchanged sign-in
would otherwise vanish once its one row aged out.

Fold. `signin_state(events, state=None)` returns `{profile: SignIn(state, ends_at, at, ever,
account, account_seq)}` from the `READING` events: only a payload with a non-empty string `profile`,
a `state` in `STATES`, an `ends_at` that is null or an ISO string carrying an offset, null unless the
state is `signed_in`, an `account` that is absent, null or a `valid_account` string while the state
is `signed_in` or `unknown`, and an `account_seq` that is absent, null or a non-bool `int` of at least
0, counts; any other payload is ignored. `account` and `account_seq` are the payload's values (None
when absent, so a row from before #1036 folds with both None); the fold detects nothing itself, so
the newest row alone, the one retention keeps, folds to the same `account` and `account_seq` as the
whole log. The last valid event per profile wins and `at` is its `at`.
`ever` is True once any valid reading of the profile was `signed_in` and never goes back to False:
each folded value's `ever` is the previous value's `ever` or whether this reading is `signed_in`.
Folding later events onto an earlier fold gives the fold of all of them.

Ask. `profile_signin(signin, now)` is `{"state", "ends_at", "days_left", "ask", "since",
"ever_signed_in"}`, `ever_signed_in` being, in every case, whether the sign-in is not None and
its `ever` is True or its state is `signed_in`. None and an `unknown` sign-in are `unknown`, with
the rest (but `ever_signed_in`) None and `ask` False. Signed out is `ask` True
with `since` the sign-in's `at`. Signed in with an end E (epoch seconds) has `days_left = max(0,
int((E - now) // 86400))` and `ask = E - now <= ASK_SECONDS` (259200, three days), `since` being
the ISO UTC time of `E - ASK_SECONDS` while asking, else None. Signed in without an end has
`days_left` None and `ask` False.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from agent_tools.console import manager, probe
from agent_tools.console.event_log import SIGNIN_READING, Event

READING = SIGNIN_READING
STATES = ("signed_in", "signed_out", "unknown")
STATUS_TIMEOUT = 30
MAX_ACCOUNT_CHARS = 320
ASK_SECONDS = 259200
KINDS = ("not_installed", "timed_out", "unavailable", "exited", "unreadable")

_DROPPED_ENV = ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


@dataclass(frozen=True)
class Status:
    state: str
    ends_at: str | None
    account: str | None = None


UNKNOWN = Status("unknown", None)


@dataclass(frozen=True)
class SignIn:
    state: str
    ends_at: str | None
    at: str
    ever: bool = False
    account: str | None = None
    account_seq: int | None = None


class StatusFailed(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def status_command() -> list[str]:
    return ["claude-account", "run", "auth", "status", "--json"]


def status_environment(profile: str, environ: Mapping[str, str]) -> dict[str, str]:
    env = manager.client_environment(profile, environ)
    for key in _DROPPED_ENV:
        env.pop(key, None)
    env["CLAUDE_CACHE_PROXY"] = "0"
    return env


def _offset_time(value: str) -> datetime | None:
    """The time `value` names, or None when it is not an ISO time that carries an offset."""
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def valid_account(value: object) -> bool:
    """True only for a `str` of 1 to `MAX_ACCOUNT_CHARS` characters, each printable ASCII."""
    return (isinstance(value, str) and 1 <= len(value) <= MAX_ACCOUNT_CHARS
            and all(0x21 <= ord(char) <= 0x7E for char in value))


def parse_status(returncode: int, stdout: bytes) -> Status:
    if returncode not in (0, 1):
        raise StatusFailed("exited")
    try:
        document = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise StatusFailed("unreadable") from error
    if not isinstance(document, dict) or not isinstance(document.get("loggedIn"), bool):
        raise StatusFailed("unreadable")
    logged_in = document["loggedIn"]
    if logged_in != (returncode == 0):
        raise StatusFailed("unreadable")
    if not logged_in:
        return Status("signed_out", None)
    email = document.get("email")
    account = email if valid_account(email) else None
    end = document.get("loginExpiresAt")
    if end is None:
        return Status("signed_in", None, account)
    parsed = _offset_time(end) if isinstance(end, str) else None
    if parsed is None:
        raise StatusFailed("unreadable")
    return Status("signed_in", parsed.astimezone(timezone.utc).isoformat(), account)


def read_status(one: probe.Probe, *, run=manager.run_in_own_group,
                environ: Mapping[str, str] = os.environ, timeout: float = STATUS_TIMEOUT) -> Status:
    env = status_environment(one.profile, environ)
    cancel = {} if one.stop is None else {"cancel": one.stop}
    with tempfile.TemporaryDirectory(prefix="console-signin-") as cwd:
        try:
            result = run(status_command(), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         start_new_session=True, timeout=timeout, check=False, **cancel)
        except FileNotFoundError as error:
            raise StatusFailed("not_installed") from error
        except subprocess.TimeoutExpired as error:
            raise StatusFailed("timed_out") from error
        except OSError as error:
            raise StatusFailed("unavailable") from error
    return parse_status(result.returncode, result.stdout or b"")


def reader_for(platform: str) -> Callable[[probe.Probe], Status] | None:
    return read_status if manager.supported(platform) else None


def entry(profile: str, status: Status, folded: SignIn | None = None,
          reading_seq: int | None = None) -> tuple[str, None, dict]:
    """The `signin.reading` entry for `status`, carrying the account and where its readings begin."""
    account = None
    if status.state == "signed_in":
        account = status.account
    elif status.state == "unknown" and folded is not None:
        account = folded.account
    switch = (account is not None and folded is not None and account != folded.account
              and (folded.account_seq is not None or folded.state == "signed_out"))
    if switch:
        account_seq = reading_seq if reading_seq is not None else 0
    elif folded is not None and folded.account_seq is not None:
        account_seq = folded.account_seq
    else:
        account_seq = 0
    return (READING, None, {"profile": profile, "state": status.state, "ends_at": status.ends_at,
                            "account": account, "account_seq": account_seq})


def _valid(payload: dict) -> bool:
    profile = payload.get("profile")
    if not isinstance(profile, str) or not profile:
        return False
    state = payload.get("state")
    if state not in STATES:
        return False
    account = payload.get("account")
    if account is not None and not (valid_account(account) and state in ("signed_in", "unknown")):
        return False
    seq = payload.get("account_seq")
    if seq is not None and (not isinstance(seq, int) or isinstance(seq, bool) or seq < 0):
        return False
    end = payload.get("ends_at")
    if end is None:
        return True
    return state == "signed_in" and isinstance(end, str) and _offset_time(end) is not None


def signin_state(events: Iterable[Event],
                 state: Mapping[str, SignIn] | None = None) -> dict[str, SignIn]:
    folded = dict(state) if state else {}
    for event in events:
        if event.kind != READING or not _valid(event.payload):
            continue
        payload = event.payload
        previous = folded.get(payload["profile"])
        ever = (previous is not None and previous.ever) or payload["state"] == "signed_in"
        folded[payload["profile"]] = SignIn(payload["state"], payload.get("ends_at"), event.at,
                                            ever, payload.get("account"),
                                            payload.get("account_seq"))
    return folded


def profile_signin(signin: SignIn | None, now: float) -> dict:
    ever = signin is not None and (signin.ever or signin.state == "signed_in")
    if signin is None or signin.state == "unknown":
        return {"state": "unknown", "ends_at": None, "days_left": None, "ask": False,
                "since": None, "ever_signed_in": ever}
    if signin.state == "signed_out":
        return {"state": "signed_out", "ends_at": None, "days_left": None, "ask": True,
                "since": signin.at, "ever_signed_in": ever}
    if signin.ends_at is None:
        return {"state": "signed_in", "ends_at": None, "days_left": None, "ask": False,
                "since": None, "ever_signed_in": ever}
    end = _offset_time(signin.ends_at).timestamp()
    ask = end - now <= ASK_SECONDS
    since = datetime.fromtimestamp(end - ASK_SECONDS, timezone.utc).isoformat() if ask else None
    return {"state": "signed_in", "ends_at": signin.ends_at,
            "days_left": max(0, int((end - now) // 86400)), "ask": ask, "since": since,
            "ever_signed_in": ever}
