"""The console's account adder: create an account profile through the launcher's own add (#1027).

Name rule. `NAME` is `[a-z0-9_-]+`, used only with `fullmatch`, and `refusal(name)` is `DEFAULT`
(`default is not an account name`) when `name == "default"`, `INVALID` (`not an account name: use
a-z, 0-9, - and _`) when `NAME.fullmatch(name)` is None, else None. It accepts exactly the names the
launcher's `cmd_add` accepts, so a name the console passes is a name the launcher creates.
`already_exists(name)` is `account <name> already exists`, the text of a name that already has a
profile. `UNAVAILABLE` is `adding an account is not available on this host`.

Request. `parse_add_request(body)` takes a UTF-8 JSON object with exactly the member `name`, whose
value is a string (the empty string included: `refusal` judges the rule, so that an empty name is
answered as a refusal, not as a malformed request), and returns it. It raises `ValueError`
otherwise.

Adder. `Adder(command=("claude-account",), environ=None, timeout=ADD_TIMEOUT)` called with a name
first refuses a name that `refusal` refuses, with `ValueError`, before any process starts. It then
runs `[*command, "add", name]` with no shell, `stdin` from `DEVNULL`, `stdout` and `stderr` to
`DEVNULL`, `env=dict(environ)` when `environ` is given (else the console's own), and `timeout`
(`ADD_TIMEOUT`, 30 seconds). Exit 0 returns None. The launcher's `add` is the one implementation of
profile creation: nothing here makes a directory or a link.

Failures. A failed run raises `AddFailed(kind)`, `str(error) == kind`, `kind` one of `KINDS`:
`not_installed` (`FileNotFoundError`, or `PermissionError` on the executable), `timed_out`
(`subprocess.TimeoutExpired`), `unavailable` (any other `OSError`) and `failed` (a non-zero exit).
`not_listed` is raised by the console service when the profile does not appear in the listing after
a successful add.

Row. `added(profile)` is `("account.added", None, {"by": "owner", "profile": profile})`, one per
account the owner adds from the page; it raises `ValueError` when `refusal(profile)` is not None.
`ADDED` is `event_log.ACCOUNT_ADDED`. The kind is not in `KEPT_KINDS`.

Platform. `adder_for(platform)` is `Adder()` where `manager.supported(platform)`, else None.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping, Sequence

from agent_tools.console import event_log, manager

ADDED = event_log.ACCOUNT_ADDED
ADD_TIMEOUT = 30
NAME = re.compile(r"[a-z0-9_-]+")
INVALID = "not an account name: use a-z, 0-9, - and _"
DEFAULT = "default is not an account name"
UNAVAILABLE = "adding an account is not available on this host"
KINDS = ("not_installed", "timed_out", "failed", "unavailable", "not_listed")


def refusal(name: str) -> str | None:
    if name == "default":
        return DEFAULT
    if NAME.fullmatch(name) is None:
        return INVALID
    return None


def already_exists(name: str) -> str:
    return f"account {name} already exists"


def parse_add_request(body: bytes) -> str:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or set(value) != {"name"} or not isinstance(value["name"], str):
        raise ValueError("wrong members")
    return value["name"]


def added(profile: str) -> tuple[str, None, dict]:
    reason = refusal(profile)
    if reason is not None:
        raise ValueError(reason)
    return (ADDED, None, {"by": "owner", "profile": profile})


class AddFailed(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class Adder:
    def __init__(self, *, command: Sequence[str] = ("claude-account",),
                 environ: Mapping[str, str] | None = None, timeout: float = ADD_TIMEOUT):
        self._command = tuple(command)
        self._environ = environ
        self._timeout = timeout

    def __call__(self, name: str) -> None:
        reason = refusal(name)
        if reason is not None:
            raise ValueError(reason)
        env = dict(self._environ) if self._environ is not None else None
        try:
            done = subprocess.run([*self._command, "add", name], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                                  timeout=self._timeout, check=False)
        except subprocess.TimeoutExpired as error:
            raise AddFailed("timed_out") from error
        except (FileNotFoundError, PermissionError) as error:
            raise AddFailed("not_installed") from error
        except OSError as error:
            raise AddFailed("unavailable") from error
        if done.returncode != 0:
            raise AddFailed("failed")


def adder_for(platform: str) -> Adder | None:
    return Adder() if manager.supported(platform) else None
