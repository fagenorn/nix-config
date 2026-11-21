"""The console's account remover: sign a profile out, then remove it through the launcher's rm (#1030).

Request. `parse_remove_request(body)` takes a UTF-8 JSON object whose members are exactly `profile`
and `typed`, both strings, and returns `(profile, typed)`. `profile` is non-empty and has no length
cap of its own (a profile name is bounded only by the service's request-body limit, as the
launcher's `valid_name` and `sessions.account_name` bound none); `typed` is any string, the empty
one included, because the service judges whether it matches. It raises `ValueError` otherwise.
`parse_signout_request(body)` takes a UTF-8 JSON object whose members are exactly `profile`, a
non-empty string, and returns it, else `ValueError` (#1345). `parse_guest_request(body)` takes one
whose members are exactly `account`, an `int` that is not a `bool` and is at least 1, and `ident`, a
non-empty string, and returns `(account, ident)`, else `ValueError`: a colleague names his account by
its pool number and the token his pool row carried (`guest.account_token`), never by a profile; the
number is recycled, so the token binds the request to the account he saw.

Texts. `UNAVAILABLE` is `removing an account is not available on this host`, `MISMATCH` is `the
typed name does not match`, `UNKNOWN` is `no such profile`, `running(profile)` is `a sign-in is
running for <profile>; cancel it first`, `busy(profile)` is `<profile> is still being read; try
again in a moment` (the drain of a probe or a client run under the profile already in flight
timed out) and `removing(profile)` is `<profile> is being removed` (a sign-in start refused during a
removal). `SIGNOUT_UNAVAILABLE` is `signing an account out is not available on this host`,
`NOT_COLLEAGUE` is `only an account a colleague added is signed out here` and `NOT_MOVED` is `the
account was signed out but a manager on it was not moved` (it names no profile).

Timeouts. `SIGNOUT_TIMEOUT` and `REMOVE_TIMEOUT` are 30 seconds each; `DRAIN_TIMEOUT` is 15 seconds,
what a removal waits for a probe or a client run under the profile already in flight (a manager
launch, nudge, wake, stop or sign-in status read).

Row. `removed(profile, outcome, kind, by="owner")` is `("account.removal", None, {"by": by, "profile":
profile, "outcome": outcome, "kind": kind})`, one per removal the owner or the colleague who added
the profile confirms (`by` is `owner` or a login with `event_log.normal_login(by) == by`, #1345). It
raises `ValueError` when `account_add.refusal(profile)` is not None, when `outcome` is not in
`OUTCOMES` (`removed`, `removed_signed_out_already`, `signout_failed`, `remove_failed`), when `kind`
is None for any outcome but `removed`, when `kind` is not None for `removed`, or when `by` is
neither `owner` nor a normal-form login (checked last). `REMOVAL` is
`event_log.ACCOUNT_REMOVAL`; the kind is not in `KEPT_KINDS`.

Sign-out. `signout_command()` is `["claude-account", "run", "auth", "logout"]`. `sign_out(one, *,
run, environ, timeout)` runs it once under the profile of the probe `one`: `env` is
`signin.status_environment(one.profile, environ)` (so `CLAUDE_ACCOUNT` is the profile,
`CLAUDE_CACHE_PROXY` is `0` and no `ANTHROPIC_API_KEY` is passed), `cwd` is a fresh temporary
directory named `console-signout-*` removed afterwards, `stdin`, `stdout` and `stderr` are
`DEVNULL`, `start_new_session` is true, `timeout` is `SIGNOUT_TIMEOUT` by default and `cancel` is
`one.stop` when that is not None. Exit 0 returns None. A failure raises `SignOutFailed(kind)`,
`str(error) == kind`, `kind` one of `SIGNOUT_KINDS`: `timed_out` (`subprocess.TimeoutExpired`),
`not_installed` (`FileNotFoundError` or `PermissionError`), `unavailable` (any other `OSError`) and
`exited` (a non-zero exit).

Remover. `Remover(command=("claude-account",), environ=None, timeout=REMOVE_TIMEOUT)` called with a
name first refuses a name that `account_add.refusal` refuses, with `ValueError`, before any process
starts. It then runs `[*command, "rm", name]` with no shell, `stdin`, `stdout` and `stderr` to
`DEVNULL`, `start_new_session`, `env=dict(environ)` when `environ` is given (else the console's own)
and `timeout`. Exit 0 returns None. The launcher's `rm` is the one implementation of removal:
nothing here deletes anything. A failure raises `RemoveFailed(kind)`, `str(error) == kind`, `kind`
one of `REMOVE_KINDS`: `not_installed`, `timed_out`, `unavailable`, `failed` (a non-zero exit); the
fifth, `still_listed`, is raised by the console service when the profile is still listed after a
successful rm, never here. `REMOVE_KINDS` also holds `stop_failed`, a removal whose move of the
managers on the profile could not stop one; `MoveFailed(kind)` carries it as `.kind`, as
`SignOutFailed` and `RemoveFailed` do.

Platform. `signer_out_for(platform)` is `sign_out` and `remover_for(platform)` is `Remover()` where
`manager.supported(platform)`, else None.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence

from agent_tools.console import account_add, event_log, manager, probe, signin

REMOVAL = event_log.ACCOUNT_REMOVAL
SIGNOUT_TIMEOUT = 30
REMOVE_TIMEOUT = 30
DRAIN_TIMEOUT = 15
UNAVAILABLE = "removing an account is not available on this host"
MISMATCH = "the typed name does not match"
UNKNOWN = "no such profile"
SIGNOUT_UNAVAILABLE = "signing an account out is not available on this host"
NOT_COLLEAGUE = "only an account a colleague added is signed out here"
NOT_MOVED = "the account was signed out but a manager on it was not moved"
OUTCOMES = ("removed", "removed_signed_out_already", "signout_failed", "remove_failed")
SIGNOUT_KINDS = ("not_installed", "timed_out", "unavailable", "exited")
REMOVE_KINDS = ("not_installed", "timed_out", "unavailable", "failed", "still_listed",
                "stop_failed")


def running(profile: str) -> str:
    return f"a sign-in is running for {profile}; cancel it first"


def busy(profile: str) -> str:
    return f"{profile} is still being read; try again in a moment"


def removing(profile: str) -> str:
    return f"{profile} is being removed"


def _object(body: bytes, members: set[str]) -> dict:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or set(value) != members:
        raise ValueError("wrong members")
    return value


def parse_signout_request(body: bytes) -> str:
    profile = _object(body, {"profile"})["profile"]
    if not isinstance(profile, str) or not profile:
        raise ValueError("wrong members")
    return profile


def parse_guest_request(body: bytes) -> tuple[int, str]:
    value = _object(body, {"account", "ident"})
    account, ident = value["account"], value["ident"]
    if (not isinstance(account, int) or isinstance(account, bool) or account < 1
            or not isinstance(ident, str) or not ident):
        raise ValueError("wrong members")
    return account, ident


def parse_remove_request(body: bytes) -> tuple[str, str]:
    value = _object(body, {"profile", "typed"})
    if (not isinstance(value["profile"], str) or not isinstance(value["typed"], str)
            or not value["profile"]):
        raise ValueError("wrong members")
    return value["profile"], value["typed"]


def removed(profile: str, outcome: str, kind: str | None,
            by: str = "owner") -> tuple[str, None, dict]:
    reason = account_add.refusal(profile)
    if reason is not None:
        raise ValueError(reason)
    if outcome not in OUTCOMES:
        raise ValueError("unknown outcome")
    if (kind is None) != (outcome == "removed"):
        raise ValueError("a kind belongs to every outcome but removed")
    if by != "owner" and event_log.normal_login(by) != by:
        raise ValueError("by is neither owner nor a login")
    return (REMOVAL, None, {"by": by, "profile": profile, "outcome": outcome, "kind": kind})


def signout_command() -> list[str]:
    return ["claude-account", "run", "auth", "logout"]


class SignOutFailed(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class RemoveFailed(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def sign_out(one: probe.Probe, *, run=manager.run_in_own_group,
             environ: Mapping[str, str] = os.environ, timeout: float = SIGNOUT_TIMEOUT) -> None:
    env = signin.status_environment(one.profile, environ)
    cancel = {} if one.stop is None else {"cancel": one.stop}
    cwd = tempfile.mkdtemp(prefix="console-signout-")
    try:
        result = run(signout_command(), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, timeout=timeout, **cancel)
    except subprocess.TimeoutExpired as error:
        raise SignOutFailed("timed_out") from error
    except (FileNotFoundError, PermissionError) as error:
        raise SignOutFailed("not_installed") from error
    except OSError as error:
        raise SignOutFailed("unavailable") from error
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    if result.returncode != 0:
        raise SignOutFailed("exited")


class MoveFailed(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class Remover:
    def __init__(self, *, command: Sequence[str] = ("claude-account",),
                 environ: Mapping[str, str] | None = None, timeout: float = REMOVE_TIMEOUT):
        self._command = tuple(command)
        self._environ = environ
        self._timeout = timeout

    def __call__(self, name: str) -> None:
        reason = account_add.refusal(name)
        if reason is not None:
            raise ValueError(reason)
        env = dict(self._environ) if self._environ is not None else None
        try:
            done = manager.run_in_own_group(
                [*self._command, "rm", name], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                start_new_session=True, timeout=self._timeout)
        except subprocess.TimeoutExpired as error:
            raise RemoveFailed("timed_out") from error
        except (FileNotFoundError, PermissionError) as error:
            raise RemoveFailed("not_installed") from error
        except OSError as error:
            raise RemoveFailed("unavailable") from error
        if done.returncode != 0:
            raise RemoveFailed("failed")


def signer_out_for(platform: str) -> Callable[[probe.Probe], None] | None:
    return sign_out if manager.supported(platform) else None


def remover_for(platform: str) -> Remover | None:
    return Remover() if manager.supported(platform) else None
