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
The first line of the FIFO that passes is the browser link; a line that does not is dropped, with one
stderr line `console: signin_link_refused <profile>` and no part of the line.

The client also writes its manual link to its standard output (client 2.1.322, stdin not a terminal:
`If the browser didn't open, visit: <link>`, the link possibly wrapped in OSC 8 escapes). The runner
reads that output for the whole run, in lines of at most `MAX_OUTPUT_LINE` (16384) bytes (the rest of
a longer line is dropped, together with any token the limit cut in two), and `output_links(line)` lists each token of a line that starts at an
`https://` and runs to the next byte outside 0x21 to 0x7E, the ones that pass `valid_link`. The first
token whose route is `manual` is the run's manual link.

Route. `link_route(url)` classifies a link by its one `redirect_uri` query member, and never raises. The link
itself must be `https` with a host, else None. A host is loopback when it is in
`LOOPBACK_HOSTS` (`localhost`, `127.0.0.1`, `::1`) or an IP literal equal to `127.0.0.1` or `::1` in
any spelling (`0:0:0:0:0:0:0:1`). `("manual", None)` for an `https` return address on a host that is present and not
loopback, whose port is none or in 1 to 65535; `("loopback", port)` for an `http` one on a loopback
host, the port being the written one or 80 when none is written, in 1 to 65535; None for any other
link (no `redirect_uri` or two of them, another scheme or host, an unreadable port in the link's own
authority or in its return address, a URL that does not parse). A link of the browser hook that is None is handed out as `unknown`.
`forward_command(port, host)` is `ssh -N -L <port>:localhost:<port> <host>` for a port in 1 to 65535
and a host of letters, digits and hyphens that starts with a letter or digit, else None.
`default_host()` is the machine's short host name. `Link(url, route, port, forward)` is what
`wait_link` hands back: `route` one of `ROUTES` (`manual`, `loopback`, `unknown`), `port` and
`forward` set only for `loopback` (`forward` only when `forward_command` gives one).
`answer_members(link)` is `{"link", "route", "port", "forward"}` of a Link, all four None for None.
A manual link wins when the client offers one: `wait_link` answers as soon as the manual link is
known, or, when only the browser link arrived, once `manual_grace` (`MANUAL_GRACE`, 2.0) seconds have
passed since it did. A run has one answer: the first Link `wait_link` returns for it is returned
again by every later call, whatever the client prints afterwards. A call whose `link_wait` ends
while the browser link is still inside its grace keeps waiting until the grace ends (the page that
asked makes no second call), so the choice is never made early.

Code input. The client reads the code that the browser shows the owner from its standard input.
Host finding, anis-desktop, 2026-11-13, client 2.1.322, each run under a throwaway configuration
directory, nothing it printed shown. Every run saw the link (`link_seen`), `https` and `loopback`
(the return address `http://localhost:<port>/callback`) true. Pipe control (nothing written):
`alive_at_link` true, `alive_after_20s` true, output grew false, `tty_complaint` false. Pipe write
(`not-a-real-code` and a newline, no end of file): `alive_before_write` true, `reacted` true,
`rejected` true, `exited` false, `tty_complaint` false. Pty control: `alive_at_link` true,
`alive_after_20s` true, output grew false, `tty_complaint` false. Pty write (the text and a carriage
return): `alive_before_write` true, `reacted` true, `rejected` true, `exited` false, `tty_complaint`
false. Both modes read the code, so `CODE_INPUT` is `pipe`, the simpler one: no terminal. The pty
mode stays in `start_client` for a client that stops reading a pipe: `CODE_END` is the
line ending a code is submitted with (`\\n` on a pipe, `\\r` on a pty, whose default mode turns it
into `\\n` for a line reader). Client 2.1.322, from its binary: `auth login` writes its manual link
to stdout and reads `code#state` lines from stdin, so the owner's code box feeds the manual route
unchanged.

Runs. `SignIns` holds at most one live run per profile. `start(profile)` returns `Started(run, True)`
for a new client, `Started(run, False)` with the live run's serial when the profile already runs,
and never waits for the link. A run's serial is a per-`SignIns` count starting at 1, one per client.
The client is spawned in a new session (its pid is its process-group id), in a fresh
`console-login-*` directory (mode 0700) holding only the `browser` script (0700) and the `link` FIFO
(0600); one daemon watcher thread per run reads the FIFO and the client's output until the client
exits. `wait_link(profile)` waits at most `link_wait` seconds (`LINK_WAIT`, 15) plus the rest of a
grace already running, or until the run ends or the Route rule above answers, and returns a `Link` or None. `SignIns` takes `manual_grace`
(`MANUAL_GRACE`) and `host` (the name `forward_command` names, `default_host()` when None). `send_code(profile, code)` and `cancel(profile)` of a profile
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

Rows. `acted(profile, action, outcome, by="owner")` is `("signin.acted", None, {"by": by, "profile",
"action", "outcome"})` (`by` is `owner` or a colleague's login, `event_log.normal_login(by) == by`,
else `ValueError`, #1343), `action` one of `ACTIONS` and `outcome` one of `START_OUTCOMES` for `start`,
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
`(profile, code)`. Both raise `ValueError` otherwise. A colleague's bodies name no profile (#1343):
`parse_guest_code_request(body)` takes strict UTF-8 JSON (a repeated key or `NaN` is `ValueError`)
of exactly `code`, under the same code rule, and returns it; `parse_guest_cancel_request(body)` takes
exactly the empty object and returns None. `guest_answer_members(link)` is exactly `{"link", "route"}`:
both None for no link, the url and route for `manual` and `unknown`, and `{"link": None, "route":
"loopback"}` for a loopback link, whose return address is the owner's host's loopback that a colleague's
browser cannot reach (ADR-console-080 D3).

Secrecy. No return value, exception message or stderr line carries a link or a code, and neither is
stored or logged: the link lives in memory for the run, the code goes to the client's input and
nowhere else. The client's output is read into memory only: no byte of it is printed or stored, and
a candidate that does not parse is dropped silently. `runs_for(platform)` is `SignIns` where `manager.supported(platform)`, else None.
"""

from __future__ import annotations

import contextlib
import errno
import ipaddress
import json
import os
import pty
import re
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.console import manager, signin
from agent_tools.console.event_log import SIGNIN_ACTED, SIGNIN_ENDED, Event, normal_login

ACTED = SIGNIN_ACTED
ENDED = SIGNIN_ENDED
LOGIN_DEADLINE = 600
LINK_WAIT = 15
MAX_LINK_CHARS = 4096
MAX_OUTPUT_LINE = 16384
MANUAL_GRACE = 2.0
ROUTES = ("manual", "loopback", "unknown")
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")
_LOOPBACK_ADDRESSES = (ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1"))
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


def _loopback(host: str | None) -> bool:
    if host is None:
        return False
    if host in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host) in _LOOPBACK_ADDRESSES
    except ValueError:
        return False


def link_route(url: str) -> tuple[str, int | None] | None:
    try:
        link = urlsplit(url)
        link.port  # noqa: B018 -- raises ValueError for an authority that cannot be read
        if link.scheme != "https" or not link.hostname:
            return None
        values = parse_qs(link.query, keep_blank_values=True).get("redirect_uri")
        if values is None or len(values) != 1:
            return None
        target = urlsplit(values[0])
        host = target.hostname
        port = target.port
        if target.scheme == "http" and _loopback(host):
            if port is None:
                port = 80
            return ("loopback", port) if 1 <= port <= 65535 else None
        if target.scheme == "https" and host and not _loopback(host):
            return ("manual", None) if port is None or 1 <= port <= 65535 else None
    except ValueError:
        return None
    return None


def output_links(line: bytes) -> list[str]:
    links = []
    for piece in re.split(rb"[^\x21-\x7e]+", line):
        start = piece.find(b"https://")
        if start < 0:
            continue
        token = piece[start:].decode("ascii")
        if valid_link(token):
            links.append(token)
    return links


def forward_command(port: int, host: str) -> str | None:
    if 1 <= port <= 65535 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", host):
        return f"ssh -N -L {port}:localhost:{port} {host}"
    return None


def default_host() -> str:
    return socket.gethostname().split(".")[0]


@dataclass(frozen=True)
class Link:
    url: str
    route: str
    port: int | None
    forward: str | None


def answer_members(link: Link | None) -> dict[str, object]:
    if link is None:
        return {"link": None, "route": None, "port": None, "forward": None}
    return {"link": link.url, "route": link.route, "port": link.port, "forward": link.forward}


def guest_answer_members(link: Link | None) -> dict[str, object]:
    if link is None:
        return {"link": None, "route": None}
    if link.route == "loopback":
        return {"link": None, "route": "loopback"}
    return {"link": link.url, "route": link.route}


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
    return value["profile"], _code(value["code"])


def _code(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_CODE_CHARS or not _printable(value):
        raise ValueError("bad code")
    return value


def _guest_object(body: bytes, members: set[str]) -> dict:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except RecursionError as error:
        raise ValueError("the body is nested too deeply") from error
    except UnicodeDecodeError as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or set(value) != members:
        raise ValueError("wrong members")
    return value


def parse_guest_code_request(body: bytes) -> str:
    return _code(_guest_object(body, {"code"})["code"])


def parse_guest_cancel_request(body: bytes) -> None:
    _guest_object(body, set())


def acted(profile: str, action: str, outcome: str, by: str = "owner") -> tuple[str, None, dict]:
    if action not in ACTIONS or outcome not in _ACTION_OUTCOMES[action]:
        raise ValueError("bad sign-in action")
    if by != "owner" and normal_login(by) != by:
        raise ValueError("by is neither owner nor a login")
    return (ACTED, None, {"by": by, "profile": profile, "action": action,
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

    def output(self) -> int | None: ...

    def close_output(self) -> None: ...


class _Client:
    """The spawned client: its input is a pipe, or the master of a pseudo-terminal."""

    def __init__(self, process: subprocess.Popen, master: int | None):
        self._process = process
        self._master = master
        self._output_closed = False
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

    def output(self) -> int | None:
        if self._master is not None:
            return self._master
        return None if self._process.stdout is None else self._process.stdout.fileno()

    def close_output(self) -> None:
        with contextlib.suppress(OSError):
            if self._master is not None:
                if not self._output_closed:
                    self._output_closed = True
                    os.close(self._master)
            elif self._process.stdout is not None:
                self._process.stdout.close()


def start_client(argv: list[str], *, cwd: str, env: Mapping[str, str]) -> Client:
    if CODE_INPUT == "pipe":
        process = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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
        self.fifo_link: str | None = None
        self.fifo_at: float | None = None
        self.manual: str | None = None
        self.chosen: Link | None = None
        self.done = False
        self.cond = threading.Condition()
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
                 link_wait: float = LINK_WAIT, manual_grace: float = MANUAL_GRACE,
                 host: str | None = None):
        self._on_end = on_end
        self._spawn = spawn
        self._environ = environ
        self._clock = clock
        self._deadline = deadline
        self._link_wait = link_wait
        self._manual_grace = manual_grace
        self._host = default_host() if host is None else host
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

    def wait_link(self, profile: str) -> Link | None:
        with self._lock:
            run = self._runs.get(profile)
        if run is None:
            return None
        give_up = time.monotonic() + self._link_wait
        with run.cond:
            while run.chosen is None:
                now = time.monotonic()
                if run.manual is not None or run.done:
                    break
                grace = None
                if run.fifo_link is not None:
                    grace = run.fifo_at + self._manual_grace - now
                    if grace <= 0:
                        break
                # Inside a grace the deadline does not apply: the grace ends the wait.
                if grace is None and now >= give_up:
                    break
                run.cond.wait(give_up - now if grace is None else grace)
            if run.chosen is None:
                run.chosen = self._pick(run)
            return run.chosen

    def _pick(self, run: _Run) -> Link | None:
        if run.manual is not None:
            return Link(run.manual, "manual", None, None)
        if run.fifo_link is None:
            return None
        route = link_route(run.fifo_link)
        if route is not None and route[0] == "loopback":
            return Link(run.fifo_link, "loopback", route[1],
                        forward_command(route[1], self._host))
        return Link(run.fifo_link, "unknown", None, None)

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
        output = run.client.output()
        try:
            self._read(run, output)
        finally:
            run.client.kill_group()
            run.waiter.join()
            run.client.close_output()
            with self._lock:
                for fd in (run.reader, run.holder):
                    with contextlib.suppress(OSError):
                        os.close(fd)
                shutil.rmtree(run.directory, ignore_errors=True)
                if self._runs.get(run.profile) is run:
                    del self._runs[run.profile]
                end = run.end or "exited"
                closed = run.closed
            with run.cond:
                run.done = True
                run.cond.notify_all()
            if not closed:
                self._on_end(run.profile, run.serial, end, run.returncode)

    def _read(self, run: _Run, output: int | None) -> None:
        fifo_lines = _Lines(MAX_LINK_CHARS + 1)
        output_lines = _Lines(MAX_OUTPUT_LINE)
        fds = [run.reader]
        if output is not None:
            fds.append(output)

        def take(fd: int) -> None:
            try:
                data = os.read(fd, 65536)
            except BlockingIOError:
                return
            except OSError:
                data = b""
            if fd == run.reader:
                if data and run.fifo_link is None:
                    for line in fifo_lines.feed(data):
                        self._fifo_line(run, line)
                        if run.fifo_link is not None:
                            break
                return
            if not data:
                fds.remove(fd)
                self._output_lines(run, output_lines.rest())
                return
            self._output_lines(run, output_lines.feed(data))

        while not run.exited.is_set():
            ready, _, _ = select.select(fds, [], [], POLL_SECONDS)
            ready.sort(key=lambda fd: fd == run.reader)
            for fd in ready:
                take(fd)
        for _ in range(256):
            ready, _, _ = select.select(fds, [], [], 0)
            if not ready:
                break
            ready.sort(key=lambda fd: fd == run.reader)
            for fd in ready:
                take(fd)
        if output in fds:
            self._output_lines(run, output_lines.rest())

    def _fifo_line(self, run: _Run, raw: bytes) -> None:
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError:
            text = ""
        if not valid_link(text):
            print(f"console: signin_link_refused {run.profile}", file=sys.stderr)
            return
        with run.cond:
            run.fifo_link = text
            run.fifo_at = time.monotonic()
            if run.manual is None and link_route(text) == ("manual", None):
                run.manual = text
            run.cond.notify_all()

    def _output_lines(self, run: _Run, lines: list[bytes]) -> None:
        for line in lines:
            if run.manual is not None:
                return
            try:
                for token in output_links(line):
                    if link_route(token) == ("manual", None):
                        with run.cond:
                            run.manual = token
                            run.cond.notify_all()
                        break
            except Exception:
                continue


_TOKEN_BYTES = bytes(range(0x21, 0x7F))
_TOKEN = re.compile(rb"[\x21-\x7e]")


class _Lines:
    """Split a byte stream into lines of at most `limit` bytes; the rest of a longer line is dropped."""

    def __init__(self, limit: int):
        self._limit = limit
        self._tail = b""
        self._skipping = False

    def feed(self, data: bytes) -> list[bytes]:
        lines = []
        while data:
            head, newline, data = data.partition(b"\n")
            if self._skipping:
                self._skipping = not newline
                continue
            self._tail += head
            if len(self._tail) > self._limit:
                lines.append(self._cut(self._tail))
                self._tail = b""
                self._skipping = not newline
            elif newline:
                lines.append(self._tail)
                self._tail = b""
        return lines

    def _cut(self, tail: bytes) -> bytes:
        """The first `limit` bytes of `tail`, less a token the limit cut in two."""
        line = tail[:self._limit]
        if not (_TOKEN.match(tail[self._limit - 1:self._limit])
                and _TOKEN.match(tail[self._limit:self._limit + 1])):
            return line
        return line.rstrip(_TOKEN_BYTES)

    def rest(self) -> list[bytes]:
        tail, self._tail = self._tail, b""
        return [tail] if tail else []


def runs_for(platform: str) -> type[SignIns] | None:
    return SignIns if manager.supported(platform) else None
