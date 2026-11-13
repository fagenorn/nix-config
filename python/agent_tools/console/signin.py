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

Parse. `parse_status(returncode, stdout)` returns a `Status(state, ends_at)`. A return code that is
neither 0 nor 1 is `StatusFailed("exited")`. Otherwise stdout must decode as UTF-8 JSON to an
object whose `loggedIn` is a bool, else `unreadable`. `(0, loggedIn true)` is `signed_in`, its
`ends_at` None when `loginExpiresAt` is absent or null, else that string (a trailing `Z` read as
`+00:00`, an offset required) as `astimezone(utc).isoformat()`; any other value, or a string that
does not parse, is `unreadable`. `(1, loggedIn false)` is `signed_out` with `ends_at` None whatever
`loginExpiresAt` holds. `(0, false)` and `(1, true)` are `unreadable`. Every other member (the
address, the organisation, the plan) is dropped, never stored.

Failures are `StatusFailed(kind)` with `kind` one of `KINDS`, and `str(error) == kind`:
`not_installed` (`claude-account` is not on `PATH`), `timed_out`, `unavailable` (any other
`OSError`), `exited`, `unreadable`. `reader_for(platform)` is `read_status` where
`manager.supported(platform)`, else None.

Event. `entry(profile, status)` is `("signin.reading", None, {"profile", "state", "ends_at"})`,
`READING` being the kind. The kind is not in `KEPT_KINDS`: retention removes it like any other row.

Fold. `signin_state(events, state=None)` returns `{profile: SignIn(state, ends_at, at)}` from the
`READING` events: only a payload with a non-empty string `profile`, a `state` in `STATES` and an
`ends_at` that is null or an ISO string carrying an offset, null unless the state is `signed_in`,
counts; any other payload is ignored. The last valid event per profile wins and `at` is its `at`.
Folding later events onto an earlier fold gives the fold of all of them.

Ask. `profile_signin(signin, now)` is `{"state", "ends_at", "days_left", "ask", "since"}`. None and
an `unknown` sign-in are `unknown`, with the rest None and `ask` False. Signed out is `ask` True
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
from agent_tools.console.event_log import Event

READING = "signin.reading"
STATES = ("signed_in", "signed_out", "unknown")
STATUS_TIMEOUT = 30
ASK_SECONDS = 259200
KINDS = ("not_installed", "timed_out", "unavailable", "exited", "unreadable")

_DROPPED_ENV = ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


@dataclass(frozen=True)
class Status:
    state: str
    ends_at: str | None


UNKNOWN = Status("unknown", None)


@dataclass(frozen=True)
class SignIn:
    state: str
    ends_at: str | None
    at: str


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
    end = document.get("loginExpiresAt")
    if end is None:
        return Status("signed_in", None)
    parsed = _offset_time(end) if isinstance(end, str) else None
    if parsed is None:
        raise StatusFailed("unreadable")
    return Status("signed_in", parsed.astimezone(timezone.utc).isoformat())


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


def entry(profile: str, status: Status) -> tuple[str, None, dict]:
    return (READING, None, {"profile": profile, "state": status.state, "ends_at": status.ends_at})


def _valid(payload: dict) -> bool:
    profile = payload.get("profile")
    if not isinstance(profile, str) or not profile:
        return False
    state = payload.get("state")
    if state not in STATES:
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
        folded[payload["profile"]] = SignIn(payload["state"], payload.get("ends_at"), event.at)
    return folded


def profile_signin(signin: SignIn | None, now: float) -> dict:
    if signin is None or signin.state == "unknown":
        return {"state": "unknown", "ends_at": None, "days_left": None, "ask": False,
                "since": None}
    if signin.state == "signed_out":
        return {"state": "signed_out", "ends_at": None, "days_left": None, "ask": True,
                "since": signin.at}
    if signin.ends_at is None:
        return {"state": "signed_in", "ends_at": None, "days_left": None, "ask": False,
                "since": None}
    end = _offset_time(signin.ends_at).timestamp()
    ask = end - now <= ASK_SECONDS
    since = datetime.fromtimestamp(end - ASK_SECONDS, timezone.utc).isoformat() if ask else None
    return {"state": "signed_in", "ends_at": signin.ends_at,
            "days_left": max(0, int((end - now) // 86400)), "ask": ask, "since": since}
