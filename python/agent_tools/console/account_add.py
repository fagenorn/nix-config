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
`DEVNULL`, `env` the `environ` given (else the console's own) with `SKIP_TRUST_ENV` set to `1`, and `timeout`
(`ADD_TIMEOUT`, 30 seconds). `SKIP_TRUST_ENV` is `CLAUDE_ACCOUNT_SKIP_FOLDER_TRUST`: the launcher's
`add` then grants no folder trust itself, because the console grants every registered project after
the add, outside the timeout, and reads each grant back (#1078); the variable marks nothing
trusted. Exit 0 returns None. The launcher's `add` is the one implementation of
profile creation: nothing here makes a directory or a link.

Failures. A failed run raises `AddFailed(kind)`, `str(error) == kind`, `kind` one of `KINDS`:
`not_installed` (`FileNotFoundError`, or `PermissionError` on the executable), `timed_out`
(`subprocess.TimeoutExpired`), `unavailable` (any other `OSError`) and `failed` (a non-zero exit).
`not_listed` is raised by the console service when the profile does not appear in the listing after
a successful add.

Row. `added(profile, by="owner", identity=None)` is `("account.added", None, {"by": by, "profile": profile})`,
one per account the owner or a listed colleague adds from the page (#1343); `by` is `owner` or the colleague's
login (`event_log.normal_login(by) == by`), and it raises `ValueError` when `refusal(profile)` is not
None or `by` is neither. A row built with the default `by` is what it was before #1343. A colleague's row also
carries `"identity"` (a non-empty string, else `ValueError`; none for an owner's row) when the service gives
one: `identity(directory)` of the profile directory the add created.
`ADDED` is `event_log.ACCOUNT_ADDED`. The kind is not in `KEPT_KINDS`. `added_state(events, state=None)`
is `state` (default empty) united with the `payload["profile"]` of every `ADDED` event whose payload is
a dict with a string `profile` that `refusal` accepts, as a frozenset: the view's `accounts_added`
member, folded by the service and rebuilt from the retained log on a restart or a retention pass.
An invalid payload is ignored.

Owner. `owners_state(events, state=None)` is the profile -> colleague login map folded from
`account.added` and `account.removal` rows in order, onto a copy of `state` (never mutated): an
`account.added` row whose payload is a dict with a `profile` that `refusal` accepts and a string `by`
sets the owner to `by` when `normal_login(by) == by`, removes the profile when `by == "owner"`, and is
ignored otherwise; an `account.removal` row whose `outcome` is in `GONE_OUTCOMES` removes the profile
(the removal succeeded, so a later directory of that name, made by the launcher with no console row,
is not his), and any other outcome changes nothing; any other row is ignored. Folding later events
onto an earlier fold gives the fold of all of them. `GONE_OUTCOMES` is `event_log.ACCOUNT_GONE_OUTCOMES`,
the same two outcomes as `folder_trust.GONE_OUTCOMES` (folder_trust imports this module).

Identity. `identity(directory)` is `<inode>:<birth>` of the directory as `os.stat` reads it, `<birth>` being
its creation time in nanoseconds where the platform gives one (empty where it does not), and None when the
directory cannot be read. A profile name can be given to another directory (the owner removes a profile with
the CLI and makes one of that name), so ownership is the name together with this identity. The device number
is left out: it is not stable across a restart on every platform. `identities_state(events, state=None)` is the
profile -> identity map folded like `owners_state` (an `account.added` row whose `by` is a login and whose
`identity` is a non-empty string sets it, any other valid `account.added` row and a completed removal drop
it), onto a copy of `state`. A name owned with no identity (a row without one) is owned by name alone.

Guest add. `GUEST_PREFIX` is `colleague-` and `guest_name(taken)` is `colleague-<n>` for the smallest
`n >= 1` not among the `taken` names, a name `refusal` accepts: the console names a colleague's
profile, never the colleague. `parse_guest_add_request(body)` reads strict UTF-8 JSON (a repeated
key, `NaN` or nesting too deep is `ValueError`) whose value is an object of exactly the member
`consent`, a `bool` (not `1`, not `"true"`), and optionally `attempt`, a positive `int` (not a `bool`), and
returns `(consent, attempt)`, `attempt` None when absent; anything else is `ValueError`. An `attempt` is the
sign-in the page shows with no link yet: the add then only joins that one (#1343).

Platform. `adder_for(platform)` is `Adder()` where `manager.supported(platform)`, else None.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console import event_log, manager

ADDED = event_log.ACCOUNT_ADDED
REMOVAL = event_log.ACCOUNT_REMOVAL
GONE_OUTCOMES = event_log.ACCOUNT_GONE_OUTCOMES
GUEST_PREFIX = "colleague-"
ADD_TIMEOUT = 30
SKIP_TRUST_ENV = "CLAUDE_ACCOUNT_SKIP_FOLDER_TRUST"
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


def added(profile: str, by: str = "owner", identity: str | None = None) -> tuple[str, None, dict]:
    reason = refusal(profile)
    if reason is not None:
        raise ValueError(reason)
    if by != "owner" and event_log.normal_login(by) != by:
        raise ValueError("by is neither owner nor a login")
    payload = {"by": by, "profile": profile}
    if identity is not None:
        if not isinstance(identity, str) or not identity:
            raise ValueError("identity is not a non-empty string")
        payload["identity"] = identity
    return (ADDED, None, payload)


def identity(directory: Path) -> str | None:
    try:
        found = directory.stat()
    except OSError:
        return None
    born = getattr(found, "st_birthtime_ns", None)
    return f"{found.st_ino}:{'' if born is None else born}"


def added_state(events: Iterable[event_log.Event],
                state: frozenset[str] | None = None) -> frozenset[str]:
    names = set(state or ())
    for event in events:
        if event.kind != ADDED or not isinstance(event.payload, dict):
            continue
        profile = event.payload.get("profile")
        if isinstance(profile, str) and refusal(profile) is None:
            names.add(profile)
    return frozenset(names)


def owners_state(events: Iterable[event_log.Event],
                 state: Mapping[str, str] | None = None) -> dict[str, str]:
    owners = dict(state or {})
    for event in events:
        payload = event.payload
        if event.kind not in (ADDED, REMOVAL) or not isinstance(payload, dict):
            continue
        profile = payload.get("profile")
        if not isinstance(profile, str) or refusal(profile) is not None:
            continue
        if event.kind == REMOVAL:
            if payload.get("outcome") in GONE_OUTCOMES:
                owners.pop(profile, None)
            continue
        by = payload.get("by")
        if not isinstance(by, str):
            continue
        if by == "owner":
            owners.pop(profile, None)
        elif event_log.normal_login(by) == by:
            owners[profile] = by
    return owners


def identities_state(events: Iterable[event_log.Event],
                     state: Mapping[str, str] | None = None) -> dict[str, str]:
    identities = dict(state or {})
    for event in events:
        payload = event.payload
        if event.kind not in (ADDED, REMOVAL) or not isinstance(payload, dict):
            continue
        profile = payload.get("profile")
        if not isinstance(profile, str) or refusal(profile) is not None:
            continue
        if event.kind == REMOVAL:
            if payload.get("outcome") in GONE_OUTCOMES:
                identities.pop(profile, None)
            continue
        by = payload.get("by")
        if not isinstance(by, str) or not (by == "owner" or event_log.normal_login(by) == by):
            continue
        found = payload.get("identity")
        if by != "owner" and isinstance(found, str) and found:
            identities[profile] = found
        else:
            identities.pop(profile, None)
    return identities


def guest_name(taken: Collection[str]) -> str:
    number = 1
    while f"{GUEST_PREFIX}{number}" in taken:
        number += 1
    return f"{GUEST_PREFIX}{number}"


def parse_guest_add_request(body: bytes) -> tuple[bool, int | None]:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the body is nested too deeply") from error
    except UnicodeDecodeError as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or not {"consent"} <= set(value) <= {"consent", "attempt"}:
        raise ValueError("the body must be an object of a consent bool and at most an attempt")
    attempt = value.get("attempt")
    if type(value["consent"]) is not bool or ("attempt" in value and (
            type(attempt) is not int or attempt < 1)):
        raise ValueError("the body must be an object of a consent bool and at most an attempt")
    return value["consent"], attempt


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
        env = {**(os.environ if self._environ is None else self._environ), SKIP_TRUST_ENV: "1"}
        try:
            done = manager.run_in_own_group(
                [*self._command, "add", name], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                start_new_session=True, timeout=self._timeout)
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
