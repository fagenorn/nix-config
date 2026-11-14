"""The console's sign-in runner: run a profile's own client login with no terminal and hand back its link (#1026).

Command. `login_command()` is `claude-account run auth login`. The client's own login answers; nothing
here reads or writes a credential. The sign-in reader of `signin.py` (#1010) stays the only thing that
says whether a profile is signed in: a run ending is only the cue to read again.

Environment. `login_environment(profile, environ, browser)` is `signin.status_environment(profile,
environ)` (the client environment without `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY` and
`ANTHROPIC_AUTH_TOKEN`, with `CLAUDE_CACHE_PROXY=0`) plus `BROWSER=browser`.

Link. The client opens its sign-in address by running `$BROWSER <address>`. `BROWSER` is the absolute
path of a `browser` script in the run's directory, a `#!/bin/sh` script whose only command writes its
first argument and a newline into the `link` FIFO beside it. The console opens that FIFO for reading,
without blocking, before it starts the client. `valid_link(text)` is true for text that starts with
`https://`, is at most `MAX_LINK_CHARS` (4096) characters long and has only characters 0x21 to 0x7E.
The first line that passes is the run's link; a line that does not is dropped, with one stderr line
`console: signin_link_refused <profile>` and no part of the line.

Code input. The client reads the code that the browser shows the owner from its standard input.
Host finding, anis-desktop, 2026-11-13, client 2.1.322, each run under a throwaway configuration
directory, nothing it printed shown. Every run saw the link (`link_seen`), `https` and `loopback`
(the return address `http://localhost:<port>/callback`) true. Pipe control (nothing written):
`alive_at_link` true, `alive_after_20s` true, output grew false, `tty_complaint` false. Pipe write
(`not-a-real-code` and a newline, no end of file): `alive_before_write` true, `reacted` true,
`rejected` true, `exited` false, `tty_complaint` false. Pty control: `alive_at_link` true,
`alive_after_20s` true, output grew false, `tty_complaint` false. Pty write (the text and a carriage
return): `alive_before_write` true, `reacted` true, `rejected` true, `exited` false, `tty_complaint`
false. Both modes read the code, so `CODE_INPUT` is `pipe`, the simpler one: no terminal, no output to
drain. The pty mode stays in `start_client` for a client that stops reading a pipe: `CODE_END` is the
line ending a code is submitted with (`\\n` on a pipe, `\\r` on a pty, whose default mode turns it
into `\\n` for a line reader).

Runs. `SignIns` holds at most one live run per profile. `start(profile)` returns `Started(run, True)`
for a new client, `Started(run, False)` with the live run's serial when the profile already runs,
and never waits for the link. A run's serial is a per-`SignIns` count starting at 1, one per client.
The client is spawned in a new session (its pid is its process-group id), in a fresh
`console-login-*` directory (mode 0700) holding only the `browser` script (0700) and the `link` FIFO
(0600); one daemon watcher thread per run reads the FIFO (and a pty master, discarding it) until the
client exits. `wait_link(profile)` waits at most `link_wait` seconds (`LINK_WAIT`, 15), or until the
run ends, and returns the link or None. `send_code(profile, code)` and `cancel(profile)` of a profile
with no live run raise `NotRunning`; a write the live client's input refuses raises its `OSError`
unchanged, so the caller can tell it from a missing run. The write never blocks and never holds the
runner's lock: the client's input is non-blocking, and a code (at most `MAX_CODE_CHARS` plus the line
ending, under the pipe's atomic size) the input has no room for raises `BlockingIOError` at once, so
a client that stopped reading cannot hold up `cancel`, `expire` or any other call. `running()` is the profiles with a live run.

Deadline. `expire()` kills every run with `clock() - started >= deadline` (`LOGIN_DEADLINE`, 600
seconds) and returns their profiles, sorted; a younger run is untouched. The caller calls it on a
timer; nothing here keeps time of its own.

Ends. At every end (the client exits, `cancel`, the deadline) the whole process group is killed with
SIGKILL, even after a natural exit (the account wrapper waits for its client child, as
`manager.run_in_own_group` records), the FIFO and a pty master are closed, the directory is removed,
the profile leaves `running()`, and only then `on_end(profile, run, end, returncode)` is called
once, `end` being one of `ENDS`: `cancelled` or `timed_out` when the run was marked so before the
client exited, else `exited`. `close()` kills every live run, joins every watcher and calls no
`on_end`. `start` fails with `StartFailed(kind)`, `str(error) == kind`: `not_installed` (the client
is not on `PATH`) or `unavailable` (any other `OSError`); the directory is removed and nothing
stays in `running()`.

Rows. `acted(profile, action, outcome)` is `("signin.acted", None, {"by": "owner", "profile",
"action", "outcome"})`, `action` one of `ACTIONS` and `outcome` one of `START_OUTCOMES` for `start`,
`sent` for `code`, `cancelled` for `cancel`. `ended(profile, outcome, attempt)` is `("signin.ended",
None, {"profile", "outcome", "attempt"})`, `outcome` one of `OUTCOMES`, `attempt` the sequence
number of the run's `signin.acted` start row (a positive `int`, never a `bool`). Both raise
`ValueError` otherwise. Neither kind is in `KEPT_KINDS`, and neither carries a link or a code.

Fold. `ended_state(events, state=None)` returns `{profile: Ended(outcome, at, attempt)}` from the
`ENDED` events: only a payload with a non-empty string `profile`, an `outcome` in `OUTCOMES` and a
positive `int` `attempt` counts; the event with the highest `attempt` per profile wins, the later
one among equal attempts, and `at` is its `at`, so an older attempt's late row never replaces a
newer attempt's result. Folding
later events onto an earlier fold gives the fold of all of them.

Requests. `parse_profile_request(body)` takes a UTF-8 JSON object with exactly the member `profile`,
a non-empty string, and returns it. `parse_code_request(body)` takes exactly `profile` (as above) and
`code`, a string of 1 to `MAX_CODE_CHARS` (512) characters each in 0x21 to 0x7E, and returns
`(profile, code)`. Both raise `ValueError` otherwise.

Secrecy. No return value, exception message or stderr line carries a link or a code, and neither is
stored or logged: the link lives in memory for the run, the code goes to the client's input and
nowhere else. `runs_for(platform)` is `SignIns` where `manager.supported(platform)`, else None.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import pty
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from agent_tools.console import manager, signin
from agent_tools.console.event_log import SIGNIN_ACTED, SIGNIN_ENDED, Event

ACTED = SIGNIN_ACTED
ENDED = SIGNIN_ENDED
LOGIN_DEADLINE = 600
LINK_WAIT = 15
MAX_LINK_CHARS = 4096
MAX_CODE_CHARS = 512
ACTIONS = ("start", "code", "cancel")
START_OUTCOMES = ("started", "running", "failed")
OUTCOMES = ("signed_in", "failed", "timed_out", "cancelled")
ENDS = ("exited", "timed_out", "cancelled")
CODE_INPUT = "pipe"
CODE_END = {"pipe": "\n", "pty": "\r"}
POLL_SECONDS = 0.1

_ACTION_OUTCOMES = {"start": START_OUTCOMES, "code": ("sent",), "cancel": ("cancelled",)}


def login_command() -> list[str]:
    return ["claude-account", "run", "auth", "login"]


def login_environment(profile: str, environ: Mapping[str, str], browser: str) -> dict[str, str]:
    env = signin.status_environment(profile, environ)
    env["BROWSER"] = browser
    return env


def _printable(text: str) -> bool:
    return all(0x21 <= ord(char) <= 0x7E for char in text)


def valid_link(text: str) -> bool:
    return text.startswith("https://") and len(text) <= MAX_LINK_CHARS and _printable(text)


def _object(body: bytes, members: set[str]) -> dict:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or set(value) != members:
        raise ValueError("wrong members")
    profile = value["profile"]
    if not isinstance(profile, str) or not profile:
        raise ValueError("bad profile")
    return value


def parse_profile_request(body: bytes) -> str:
    return _object(body, {"profile"})["profile"]


def parse_code_request(body: bytes) -> tuple[str, str]:
    value = _object(body, {"profile", "code"})
    code = value["code"]
    if not isinstance(code, str) or not 1 <= len(code) <= MAX_CODE_CHARS or not _printable(code):
        raise ValueError("bad code")
    return value["profile"], code


def acted(profile: str, action: str, outcome: str) -> tuple[str, None, dict]:
    if action not in ACTIONS or outcome not in _ACTION_OUTCOMES[action]:
        raise ValueError("bad sign-in action")
    return (ACTED, None, {"by": "owner", "profile": profile, "action": action,
                          "outcome": outcome})


def _attempt(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def ended(profile: str, outcome: str, attempt: int) -> tuple[str, None, dict]:
    if outcome not in OUTCOMES or not _attempt(attempt):
        raise ValueError("bad sign-in end")
    return (ENDED, None, {"profile": profile, "outcome": outcome, "attempt": attempt})


@dataclass(frozen=True)
class Ended:
    outcome: str
    at: str
    attempt: int


def _valid_end(payload: dict) -> bool:
    profile = payload.get("profile")
    return (isinstance(profile, str) and bool(profile) and payload.get("outcome") in OUTCOMES
            and _attempt(payload.get("attempt")))


def ended_state(events: Iterable[Event],
                state: Mapping[str, Ended] | None = None) -> dict[str, Ended]:
    folded = dict(state) if state else {}
    for event in events:
        if event.kind != ENDED or not _valid_end(event.payload):
            continue
        payload = event.payload
        held = folded.get(payload["profile"])
        if held is None or payload["attempt"] >= held.attempt:
            folded[payload["profile"]] = Ended(payload["outcome"], event.at, payload["attempt"])
    return folded


@dataclass(frozen=True)
class Started:
    run: int
    fresh: bool


class StartFailed(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class NotRunning(Exception):
    pass


class Client(Protocol):
    pid: int

    def send(self, line: str) -> None: ...

    def wait(self) -> int: ...

    def kill_group(self) -> None: ...

    def drain(self) -> int | None: ...


class _Client:
    """The spawned client: its input is a pipe, or the master of a pseudo-terminal."""

    def __init__(self, process: subprocess.Popen, master: int | None):
        self._process = process
        self._master = master
        self._input_lock = threading.Lock()
        self.pid = process.pid

    def send(self, line: str) -> None:
        data = (line + CODE_END[CODE_INPUT]).encode("ascii")
        with self._input_lock:
            if self._master is not None:
                fd = self._master
            elif self._process.stdin is None or self._process.stdin.closed:
                raise BrokenPipeError("the client's input is closed")
            else:
                fd = self._process.stdin.fileno()
            os.set_blocking(fd, False)
            if os.write(fd, data) != len(data):
                raise BlockingIOError(errno.EAGAIN, "the client's input is full")

    def wait(self) -> int:
        code = self._process.wait()
        with self._input_lock:
            if self._process.stdin is not None:
                with contextlib.suppress(OSError):
                    self._process.stdin.close()
        return code

    def kill_group(self) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(self.pid, signal.SIGKILL)

    def drain(self) -> int | None:
        return self._master


def start_client(argv: list[str], *, cwd: str, env: Mapping[str, str]) -> Client:
    if CODE_INPUT == "pipe":
        process = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True,
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        return _Client(process, None)
    master, slave = pty.openpty()
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True,
                                   stdin=slave, stdout=slave, stderr=slave)
    except BaseException:
        os.close(master)
        raise
    finally:
        os.close(slave)
    return _Client(process, master)


class _Run:
    def __init__(self, profile: str, serial: int, directory: str, reader: int, holder: int,
                 client: Client, started: float):
        self.profile = profile
        self.serial = serial
        self.directory = directory
        self.reader = reader
        self.holder = holder
        self.client = client
        self.started = started
        self.link: str | None = None
        self.linked = threading.Event()
        self.exited = threading.Event()
        self.returncode: int | None = None
        self.end: str | None = None
        self.closed = False
        self.thread: threading.Thread | None = None
        self.waiter: threading.Thread | None = None


class SignIns:
    def __init__(self, *, on_end: Callable[[str, int, str, int | None], None],
                 spawn=start_client, environ: Mapping[str, str] = os.environ,
                 clock: Callable[[], float] = time.monotonic, deadline: float = LOGIN_DEADLINE,
                 link_wait: float = LINK_WAIT):
        self._on_end = on_end
        self._spawn = spawn
        self._environ = environ
        self._clock = clock
        self._deadline = deadline
        self._link_wait = link_wait
        self._lock = threading.Lock()
        self._runs: dict[str, _Run] = {}
        self._serial = 0

    def start(self, profile: str) -> Started:
        with self._lock:
            live = self._runs.get(profile)
            if live is not None:
                return Started(live.serial, False)
            directory = tempfile.mkdtemp(prefix="console-login-")
            reader = holder = None
            try:
                fifo = os.path.join(directory, "link")
                browser = os.path.join(directory, "browser")
                try:
                    os.mkfifo(fifo, 0o600)
                    with open(browser, "w", encoding="utf-8") as script:
                        script.write("#!/bin/sh\nprintf '%s\\n' \"$1\" > "
                                     f"{shlex.quote(fifo)}\n")
                    os.chmod(browser, 0o700)
                    reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
                    holder = os.open(fifo, os.O_WRONLY)
                except OSError as error:
                    raise StartFailed("unavailable") from error
                try:
                    client = self._spawn(login_command(), cwd=directory,
                                         env=login_environment(profile, self._environ, browser))
                except FileNotFoundError as error:
                    raise StartFailed("not_installed") from error
                except OSError as error:
                    raise StartFailed("unavailable") from error
            except BaseException:
                for fd in (reader, holder):
                    if fd is not None:
                        os.close(fd)
                shutil.rmtree(directory, ignore_errors=True)
                raise
            self._serial += 1
            run = _Run(profile, self._serial, directory, reader, holder, client, self._clock())
            self._runs[profile] = run
            run.waiter = threading.Thread(target=self._wait, args=(run,), daemon=True,
                                          name=f"console-signin-wait-{profile}")
            run.thread = threading.Thread(target=self._watch, args=(run,), daemon=True,
                                          name=f"console-signin-{profile}")
            run.waiter.start()
            run.thread.start()
            return Started(run.serial, True)

    def wait_link(self, profile: str) -> str | None:
        with self._lock:
            run = self._runs.get(profile)
        if run is None:
            return None
        run.linked.wait(self._link_wait)
        return run.link

    def send_code(self, profile: str, code: str) -> None:
        with self._lock:
            run = self._runs.get(profile)
            if run is None or run.exited.is_set():
                raise NotRunning(profile)
        run.client.send(code)

    def cancel(self, profile: str) -> None:
        with self._lock:
            run = self._runs.get(profile)
            if run is None:
                raise NotRunning(profile)
            self._mark(run, "cancelled")

    def expire(self) -> list[str]:
        expired = []
        with self._lock:
            now = self._clock()
            for profile, run in self._runs.items():
                if now - run.started >= self._deadline and run.end is None:
                    self._mark(run, "timed_out")
                    expired.append(profile)
        return sorted(expired)

    def running(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._runs)

    def close(self) -> None:
        with self._lock:
            runs = list(self._runs.values())
            for run in runs:
                run.closed = True
                run.client.kill_group()
        for run in runs:
            run.thread.join()

    def _mark(self, run: _Run, end: str) -> None:
        if run.end is None:
            run.end = end
        run.client.kill_group()

    def _wait(self, run: _Run) -> None:
        try:
            run.returncode = run.client.wait()
        except Exception:
            run.returncode = None
        run.exited.set()

    def _watch(self, run: _Run) -> None:
        pending = b""
        fds = [run.reader]
        drain = run.client.drain()
        if drain is not None:
            fds.append(drain)

        def take(fd: int) -> None:
            nonlocal pending
            try:
                data = os.read(fd, 4096)
            except BlockingIOError:
                return
            except OSError:
                data = b""
            if not data:
                if fd in fds and fd != run.reader:
                    fds.remove(fd)
                return
            if fd != run.reader or run.link is not None:
                return
            pending += data
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                self._line(run, line[:MAX_LINK_CHARS + 1])
                if run.link is not None:
                    pending = b""
                    return
            pending = pending[:MAX_LINK_CHARS + 1]

        while not run.exited.is_set():
            ready, _, _ = select.select(fds, [], [], POLL_SECONDS)
            for fd in ready:
                take(fd)
        take(run.reader)
        run.waiter.join()
        run.client.kill_group()
        with self._lock:
            for fd in (run.reader, run.holder, drain):
                if fd is not None:
                    with contextlib.suppress(OSError):
                        os.close(fd)
            shutil.rmtree(run.directory, ignore_errors=True)
            if self._runs.get(run.profile) is run:
                del self._runs[run.profile]
            end = run.end or "exited"
            closed = run.closed
        run.linked.set()
        if not closed:
            self._on_end(run.profile, run.serial, end, run.returncode)

    def _line(self, run: _Run, raw: bytes) -> None:
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError:
            text = ""
        if valid_link(text):
            run.link = text
            run.linked.set()
        else:
            print(f"console: signin_link_refused {run.profile}", file=sys.stderr)


def runs_for(platform: str) -> type[SignIns] | None:
    return SignIns if manager.supported(platform) else None
