"""The console's loopback service: the log-derived view and the desk page over HTTP.

The service binds `127.0.0.1` on one port (`DEFAULT_PORT`) and nothing else; no
parameter names a host. `Host` must be `127.0.0.1:<port>` or `localhost:<port>`
for the port actually bound, else the answer is `403` `text/plain`
`loopback only`.

Routes (every response carries `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`, and every one but the stream `Content-Length`):

    GET /           200 text/html; charset=utf-8, the page, with `Content-Security-Policy: CSP`
    GET /api/state  200 application/json, the encoded view (see `view.py`)
    GET /api/stream 200 text/event-stream; charset=utf-8, the update stream (below)
    POST /api/hooks 204, no body, a Claude Code hook's input (below)
    anything else   404
    other methods   405 with `Allow: GET` (`Allow: POST` on `/api/hooks`)

Only `POST /api/hooks` writes, and it appends session observations only. Its
checks run in this order, each refusal closing the connection: a loopback
`Host` (else 403 as above); no `Origin` header (a browser page sends one: 403
`text/plain` `origin refused`); a `Content-Type` whose media type is
`application/json` (else 415 `json only`); a `Content-Length` that is a
non-negative integer (else 411 `length required`) of at most `MAX_HOOK_BYTES`
(else 413 `too large`, the body unread). Then the body is read, the `204` is
written and flushed, and only then is the hook ingested (`ingest_hook`): the
session that sent it never waits for the log. The hook's time is taken from the
service clock before the `204`, not when the log row is written, so a session
that updates its registry record after the answer is newer than the hook. A body that is not UTF-8 JSON
is one stderr line `console: hook_unreadable <message>`; any other failure is
`console: hook_failed <Type>: <message>`; the handler never raises. An
ignored payload (an unknown event, a missing member) appends nothing. The
route carries no token: it records observations and answers nothing.

A state request reads only `view_bytes`, which is memory: no log access, no
registry read, no derivation, no file, no filesystem metadata call, no
subprocess. The view is rebuilt only by `refresh()`, which reads the fleet
registry, appends the difference to the event log and publishes the new view;
the page itself is read once, at import.

The stream carries `Connection: close` and no `Content-Length`. Its first frame is
the current view (the page takes its view from the stream alone, never from a
separate `/api/state` request that could answer after a newer frame); one frame
follows each later change of the view; a `: keepalive` comment follows
`KEEPALIVE_SECONDS` without one. A frame is

    event: view\\n
    data: <the bytes of /api/state>\\n
    \\n

A write error, or the service closing, ends the stream.

The registry is read, never written. An absent registry, or one that is not a
valid registry (unreadable, not UTF-8 or JSON, or a violation of
`agent_platform.validate_registry`), is not a reading: `refresh()` appends
nothing, so a registry that vanishes or is damaged never unregisters a project.
An unreadable one, as opposed to an absent one, writes one stderr line
`console: registry_unreadable <reason>`.

Registry changes are found by a watcher thread, `WATCH_THREAD`, started by
`start()`: every `poll_seconds` it takes the registry's `(st_mtime_ns, st_size,
st_ino)` (`None` when it cannot be read) and, when that differs from the last
one, calls `refresh()` and records it once that returns. A failing `refresh()` is
one stderr line `console: refresh_failed <Type>: <message>`; the loop goes on and
the signature is not recorded, so each later poll tries again (one line per
failed poll) until a refresh succeeds. A signature is sampled before the read it vouches for, so a
registry replaced between the two differs from the recorded signature and is
read again on the next poll.
The watcher only calls `os.stat`, so an idle service does no other I/O.

Sessions arrive by hooks and by a poll of the session registry (see
`sessions.py`). A hook is appended with its `repo` mapped by `repo_of` (the main
checkout of its `cwd` by default) and its `project` column set to the registered
project whose root is that repository, so the event is the project's activity.
`SESSION_THREAD`, started by `start()`, calls `poll_sessions()` every
`session_poll_seconds` (`SESSION_POLL_SECONDS`) over the directories
`session_dirs()` names, called on every poll: `default_session_dirs()` is
`$HOME/.claude/sessions` and the `sessions` directory of every profile under
`$CLAUDE_ACCOUNTS_DIR` (else `$HOME/.claude-accounts`). `poll_sessions` holds the
ingest lock from before it reads the registry until after it publishes, so no
hook is ingested between a reading and its application and an older reading
never overwrites a newer hook. An unchanged registry appends nothing. A failing
poll is one stderr line `console: session_poll_failed <Type>: <message>` and the
loop goes on.

Tracker (#859): when the service is given a `tracker`, a thread, `TRACKER_THREAD`, started by
`start()`, calls `poll_tracker()` at once and then every `tracker_seconds` (`TRACKER_SECONDS`,
two minutes). One poll reads the tracker, through `tracker(project_id, slug, cancelled=...)`, for
each registered project that is active (`inbox.is_active`: a log event or a git write within a
day) and has a GitHub checkout (`slug_of`), one project after another and never inside the ingest
lock; a project costs at most `inbox.MAX_CALLS` calls. The stop flag is checked between projects
and, through `cancelled`, before every page, so `close()` waits for at most the one `gh` call
already running and a read cancelled or finished after the stop appends and publishes nothing.
What a read finds is appended as the four inbox events (`inbox.seen`, `inbox.changed`,
`inbox.gone`, `inbox.health`; see `view.py`) and the view is published. A failed read is one
stderr line `console: tracker_failed <project_id> <Type>: <message>`; the project's items stay,
now marked stale, and only a change of read health is appended (`inbox.health`), so a failed read
stays stale across a restart. A read that ends after its project was unregistered appends
nothing. An exception escaping a poll is one stderr line
`console: tracker_poll_failed <Type>: <message>` and the loop goes on. Without a tracker no
thread starts and nothing is read.

Deliveries (#858): after each `poll_sessions()` the same thread calls `poll_deliveries()`, which
reads the run journals (see `deliveries.py`) of every folded session that is not ended and has a
repository, under the `projects` directory beside each of `session_dirs()`, outside the ingest
lock, and then appends `delivery.seen` and `delivery.gone` rows and publishes under it (every
poll publishes, so the minutes since a run moved advance; an unchanged view bumps no version). A
journal is read incrementally; one that was truncated or replaced is folded again from its start.
A run leaves only when its final record exists or its journal is confirmed absent (its listing
succeeded without it); a journal or a listing that cannot be read keeps the run's last
observation. A run that names no issue is not listed. A state request reads memory only. Stderr
lines: `console: delivery_poll_failed <Type>: <message>` (a poll that raised, once per failed
poll), `console: journal_unreadable <path> <reason>` (a journal or its final record turned
unreadable, again only after it read successfully in between) and `console: journals_unreadable
<session_id> <reason>` (a session's journal listing turned unreadable, likewise).

Construction order: bind the server (an `OSError` propagates and nothing else is
opened); open the event log; fold the projects, the sessions, the inbox, the read health and the
deliveries from it; publish the view; sample the registry's signature; `refresh()`;
`poll_sessions()`; `poll_deliveries()`. The
absent set starts empty, so a restart drops a session only after two polls miss
it. On any failure after the bind, what was opened is closed and the exception
re-raised. `start()` serves on a daemon thread named `console-http`; `close()`
sets the stop flag, then `closing`, wakes every waiter, joins the watcher, the session poll and the
tracker thread and tears the rest down; it is idempotent.
"""

import http.server
import json
import socketserver
import sys
import os
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from agent_tools.claims import owner_actions
from agent_tools.console import deliveries, inbox, sessions
from agent_tools.console.event_log import Event, EventLog, utc_now
from agent_tools.console.view import (
    ReadState, derive_view, encode_view, health_change, inbox_changes, inbox_records, project_for,
    project_states, read_states, registry_changes)
from agent_tools.project_contract import agent_platform
from agent_tools.system.forge_api import ForgeError

HOST = "127.0.0.1"
DEFAULT_PORT = 27184
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")
PAGE: bytes = Path(__file__).with_name("page.html").read_bytes()
BACKLOG = 16
POLL_SECONDS = 0.25
KEEPALIVE_SECONDS = 15.0
WATCH_THREAD = "console-registry-watch"
HOOK_PATH = "/api/hooks"
MAX_HOOK_BYTES = 8 * 1024 * 1024
SESSION_POLL_SECONDS = 5.0
SESSION_THREAD = "console-session-poll"
TRACKER_SECONDS = 120.0
TRACKER_THREAD = "console-tracker-poll"


def default_store() -> Path:
    return agent_platform.state_root() / "console" / "events.sqlite3"


def default_registry() -> Path:
    return agent_platform.registry_path()


def default_session_dirs() -> list[Path]:
    """Every directory a Claude Code session registers in: the default config and each profile."""
    home = Path.home()
    accounts = os.environ.get("CLAUDE_ACCOUNTS_DIR") or str(home / ".claude-accounts")
    return [home / ".claude" / "sessions",
            *sorted(Path(accounts).glob("profiles/*/sessions"))]


def signature(path: Path) -> tuple[int, int, int] | None:
    """What the registry file looks like now; None when it cannot be statted."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size, stat.st_ino


def read_fleet(path: Path) -> list[dict] | None:
    """The registered entries, or None when the registry is not a reading."""
    try:
        document = json.loads(Path(path).read_bytes().decode("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        return _unreadable(f"{type(error).__name__}: {error}")
    violations = agent_platform.validate_registry(document)
    if violations:
        first = violations[0]
        return _unreadable(f"{first['pointer']}: {first['message']}")
    return list(document["projects"])


def _unreadable(reason: str) -> None:
    print(f"console: registry_unreadable {reason}", file=sys.stderr)
    return None


class ConsoleServer(socketserver.ThreadingTCPServer):
    # Not http.server.HTTPServer, whose server_bind does a reverse lookup.
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = BACKLOG

    def __init__(self, port: int, console: "ConsoleService"):
        self.console = console
        super().__init__((HOST, port), ConsoleHandler)


class ConsoleHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        """Silenced: the service writes no access log."""

    def _send(self, status: int, content_type: str, body: bytes, *headers: tuple[str, str]):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _loopback(self) -> bool:
        port = self.server.server_address[1]
        if self.headers.get("Host") in (f"{HOST}:{port}", f"localhost:{port}"):
            return True
        self.close_connection = True
        self._send(403, "text/plain", b"loopback only\n", ("Connection", "close"))
        return False

    def _refuse(self, status: int, text: str):
        self.close_connection = True
        self._send(status, "text/plain", text.encode() + b"\n", ("Connection", "close"))

    def do_POST(self):
        if not self._loopback():
            return
        if self.path.split("?", 1)[0] != HOOK_PATH:
            return self._refuse_method()
        if self.headers.get("Origin") is not None:
            return self._refuse(403, "origin refused")
        media = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media != "application/json":
            return self._refuse(415, "json only")
        length = self.headers.get("Content-Length", "")
        if not (length.isascii() and length.isdigit()):
            return self._refuse(411, "length required")
        if int(length) > MAX_HOOK_BYTES:
            return self._refuse(413, "too large")
        console = self.server.console
        self.close_connection = True
        try:
            body = self.rfile.read(int(length))
            received = console.received_ms()
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
        except OSError:
            return
        try:
            console.ingest_hook(body, received)
        except ValueError as error:
            print(f"console: hook_unreadable {error}", file=sys.stderr)
        except Exception as error:
            print(f"console: hook_failed {type(error).__name__}: {error}", file=sys.stderr)

    def do_GET(self):
        if not self._loopback():
            return
        route = self.path.split("?", 1)[0]
        if route == "/":
            self._send(200, "text/html; charset=utf-8", PAGE,
                       ("Content-Security-Policy", CSP))
        elif route == "/api/state":
            self._send(200, "application/json", self.server.console.view_bytes)
        elif route == "/api/stream":
            self._stream()
        elif route == HOOK_PATH:
            self._refuse_method()
        else:
            self._send(404, "text/plain", b"not found\n")

    def _stream(self):
        console = self.server.console
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        seen = -1
        try:
            while not console.closing:
                change = console.wait_for_change(seen, KEEPALIVE_SECONDS)
                if change is None:
                    if console.closing:
                        return
                    self.wfile.write(b": keepalive\n\n")
                    continue
                seen, view = change
                self.wfile.write(b"event: view\ndata: " + view + b"\n\n")
        except OSError:
            return

    def _refuse_method(self):
        if not self._loopback():
            return
        self.close_connection = True
        allow = "POST" if self.path.split("?", 1)[0] == HOOK_PATH else "GET"
        self._send(405, "text/plain", b"method not allowed\n",
                   ("Allow", allow), ("Connection", "close"))

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _refuse_method


class ConsoleService:
    def __init__(self, store: Path, registry: Path, *, port: int = DEFAULT_PORT,
                 poll_seconds: float = POLL_SECONDS,
                 session_dirs: Callable[[], Iterable[Path]] = default_session_dirs,
                 session_poll_seconds: float = SESSION_POLL_SECONDS,
                 repo_of: Callable[[str], str | None] = sessions.main_checkout,
                 tracker: Callable[..., list[dict]] | None = None,
                 tracker_seconds: float = TRACKER_SECONDS,
                 slug_of: Callable[[str], str | None] = owner_actions.checkout_slug,
                 activity: Callable[[str], float | None] = inbox.local_activity,
                 clock: Callable[[], float] = time.time):
        self.registry = Path(registry)
        self._poll_seconds = poll_seconds
        self._session_dirs = session_dirs
        self._session_poll_seconds = session_poll_seconds
        self._repo_of = repo_of
        self._sessions: dict[str, sessions.SessionState] = {}
        self._absent: frozenset[str] = frozenset()
        self._deliveries: dict[tuple[str, str], deliveries.DeliveryState] = {}
        self._reader = deliveries.JournalReader()
        self._runs: dict[Path, deliveries.RunFold] = {}
        self._unreadable: set[str] = set()
        self._session_poller: threading.Thread | None = None
        self._tracker = tracker
        self._tracker_seconds = tracker_seconds
        self._slug_of = slug_of
        self._activity = activity
        self._clock = clock
        self._tracker_thread: threading.Thread | None = None
        self._closing = False
        self._stop = threading.Event()
        self._watcher: threading.Thread | None = None
        self._signature = None
        self.log: EventLog | None = None
        self._ingest = threading.Lock()
        self._published = threading.Condition()
        self._view = b""
        self._version = 0
        self._thread: threading.Thread | None = None
        self._closed = False
        self._server = ConsoleServer(port, self)
        try:
            self.log = EventLog(store)
            events = self.log.events()
            self._states = project_states(events)
            self._sessions = sessions.session_states(events)
            self._inbox = inbox_records(events)
            self._health = read_states(events)
            self._deliveries = deliveries.delivery_states(events)
            self._publish()
            self._signature = signature(self.registry)
            self.refresh()
            self.poll_sessions()
            self.poll_deliveries()
        except BaseException:
            if self.log is not None:
                self.log.close()
            self._server.server_close()
            raise

    @property
    def address(self) -> tuple[str, int]:
        return self._server.server_address[:2]

    @property
    def view_bytes(self) -> bytes:
        return self._view

    @property
    def version(self) -> int:
        return self._version

    @property
    def closing(self) -> bool:
        return self._closing

    def wait_for_change(self, seen: int, timeout: float) -> tuple[int, bytes] | None:
        """The newest (version, view) once its version exceeds `seen`; None on timeout or close."""
        with self._published:
            self._published.wait_for(lambda: self._version > seen or self._closing, timeout)
            if self._closing or self._version <= seen:
                return None
            return self._version, self._view

    def _publish(self) -> None:
        view = encode_view(derive_view(
            self._states.values(), self._inbox, self._health,
            sessions=self._sessions.values(), deliveries=self._deliveries,
            now_ms=int(self._clock() * 1000)))
        with self._published:
            if view != self._view:
                self._view = view
                self._version += 1
            self._published.notify_all()

    def refresh(self) -> list[Event]:
        """Append the difference between the registry and the log, and publish."""
        with self._ingest:
            entries = read_fleet(self.registry)
            if entries is None:
                return []
            appended = self.log.append(registry_changes(self._states, entries))
            if appended:
                self._fold(appended)
                self._publish()
            return appended

    def _apply(self, appended: list[Event]) -> None:
        self._fold(appended)
        self._publish()

    def received_ms(self) -> int:
        """The time, in epoch milliseconds, a hook is received; taken before it is answered."""
        return int(self._clock() * 1000)

    def ingest_hook(self, body: bytes, received_ms: int | None = None) -> list[Event]:
        """Append the session event a hook's input document describes; ValueError if unreadable."""
        if received_ms is None:
            received_ms = self.received_ms()
        document = json.loads(body.decode("utf-8"))
        with self._ingest:
            entry = sessions.hook_entry(document, self._repo_of, received_ms)
            if entry is None:
                return []
            kind, payload = entry
            repo = payload["repo"]
            project = None if repo is None else project_for(repo, self._states)
            appended = self.log.append([(kind, project, payload)])
            self._apply(appended)
            return appended

    def poll_sessions(self) -> list[Event]:
        """Append what the session registry shows that the folded sessions do not, and publish."""
        with self._ingest:
            observations = sessions.read_session_registry(self._session_dirs())

            def project_of(repo: str | None) -> str | None:
                return None if repo is None else project_for(repo, self._states)

            changes, absent = sessions.poll_changes(
                self._sessions, observations, self._absent, self._repo_of, project_of)
            appended = self.log.append(changes)
            self._absent = absent
            if appended:
                self._apply(appended)
            return appended

    def _warn_once(self, key: str, line: str) -> None:
        """Print `line` unless `key` is already unreadable; `_unreadable` is cleared by a good read."""
        if key not in self._unreadable:
            self._unreadable.add(key)
            print(line, file=sys.stderr)

    def poll_deliveries(self) -> list[Event]:
        """Append what the run journals of the live sessions show that the log does not, and publish."""
        folded = self._deliveries
        scanned = {sid: s for sid, s in self._sessions.items()
                   if s.state != sessions.ENDED and s.repo is not None}
        projects_dirs: list[Path] = []
        for directory in self._session_dirs():
            projects = Path(directory).parent / "projects"
            if projects not in projects_dirs:
                projects_dirs.append(projects)
        readings: dict[tuple[str, str], deliveries.DeliveryState] = {}
        runs: dict[Path, deliveries.RunFold] = {}
        for sid in sorted(scanned):
            listing = deliveries.run_journals(projects_dirs, sid)
            if isinstance(listing, deliveries.Unreadable):
                readings.update({k: v for k, v in folded.items() if k[0] == sid})
                runs.update({j: f for j, f in self._runs.items() if j.parents[3].name == sid})
                self._warn_once(f"listing {sid}",
                                f"console: journals_unreadable {sid} {listing.reason}")
                continue
            self._unreadable.discard(f"listing {sid}")
            for journal in listing:
                key = (sid, journal.parent.name)
                path = str(journal)
                final = deliveries.has_final_record(journal)
                if final is True:
                    self._reader.forget(journal)
                    self._unreadable.discard(path)
                    continue
                chunk = final if isinstance(final, deliveries.Unreadable) else self._reader.read(journal)
                if isinstance(chunk, deliveries.Unreadable):
                    if key in folded:
                        readings[key] = folded[key]
                    if journal in self._runs:
                        runs[journal] = self._runs[journal]
                    self._warn_once(path, f"console: journal_unreadable {path} {chunk.reason}")
                    continue
                self._unreadable.discard(path)
                if chunk is None:
                    continue
                fold = self._runs.get(journal)
                if fold is None or chunk.from_start:
                    fold = deliveries.RunFold()
                fold.apply(chunk.records)
                runs[journal] = fold
                issues = fold.issues()
                if issues:
                    readings[key] = deliveries.DeliveryState(sid, key[1], chunk.moved_ms, issues)
        for journal in self._runs.keys() - runs.keys():
            self._reader.forget(journal)
        self._runs = runs
        with self._ingest:
            def project_of(sid: str) -> str | None:
                repo = scanned[sid].repo
                return project_for(repo, self._states)

            appended = self.log.append(deliveries.delivery_changes(
                self._deliveries, readings, scanned, project_of))
            if appended:
                self._fold(appended)
            self._publish()
            return appended

    def _poll_loop(self) -> None:
        while not self._stop.wait(self._session_poll_seconds):
            try:
                self.poll_sessions()
            except Exception as error:
                print(f"console: session_poll_failed {type(error).__name__}: {error}",
                      file=sys.stderr)
            try:
                self.poll_deliveries()
            except Exception as error:
                print(f"console: delivery_poll_failed {type(error).__name__}: {error}",
                      file=sys.stderr)

    def _fold(self, appended: list[Event]) -> None:
        self._states = project_states(appended, self._states)
        self._sessions = sessions.session_states(appended, self._sessions)
        self._inbox = inbox_records(appended, self._inbox)
        self._health = read_states(appended, self._health)
        self._deliveries = deliveries.delivery_states(appended, self._deliveries)

    def poll_tracker(self) -> None:
        """One refresh of the inbox of every active project; see the module docstring."""
        if self._tracker is None:
            return
        now = self._clock()
        for project_id, state in sorted(dict(self._states).items()):
            if self._stop.is_set():
                return
            if not inbox.is_active(state.last_at, self._activity(state.root), now):
                continue
            slug = self._slug_of(state.root)
            if slug is None:
                continue
            try:
                items = self._tracker(project_id, slug, cancelled=self._stop.is_set)
            except ForgeError as error:
                if error.code == "cancelled" or self._stop.is_set():
                    return
                self._read_failed(project_id, error)
            except Exception as error:
                if self._stop.is_set():
                    return
                self._read_failed(project_id, error)
            else:
                if self._stop.is_set():
                    return
                self._read_succeeded(project_id, items)

    def _read_failed(self, project_id: str, error: Exception) -> None:
        print(f"console: tracker_failed {project_id} {type(error).__name__}: {error}", file=sys.stderr)
        with self._ingest:
            if project_id not in self._states:
                return
            previous = self._health.get(project_id)
            appended = self.log.append(health_change(
                self._health, project_id, False, previous.read_at if previous else None))
            self._fold(appended)
            self._publish()

    def _read_succeeded(self, project_id: str, items: list[dict]) -> None:
        with self._ingest:
            if project_id not in self._states:
                return
            appended = self.log.append([*inbox_changes(self._inbox, project_id, items),
                                        *health_change(self._health, project_id, True)])
            self._fold(appended)
            self._health[project_id] = ReadState(True, utc_now())
            self._publish()

    def _track(self) -> None:
        while True:
            try:
                self.poll_tracker()
            except Exception as error:
                print(f"console: tracker_poll_failed {type(error).__name__}: {error}", file=sys.stderr)
            if self._stop.wait(self._tracker_seconds):
                return

    def _watch(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            current = signature(self.registry)
            if current == self._signature:
                continue
            try:
                self.refresh()
            except Exception as error:
                print(f"console: refresh_failed {type(error).__name__}: {error}", file=sys.stderr)
            else:
                self._signature = current

    def start(self) -> None:
        self._watcher = threading.Thread(target=self._watch, name=WATCH_THREAD, daemon=True)
        self._watcher.start()
        self._session_poller = threading.Thread(
            target=self._poll_loop, name=SESSION_THREAD, daemon=True)
        self._session_poller.start()
        if self._tracker is not None:
            self._tracker_thread = threading.Thread(
                target=self._track, name=TRACKER_THREAD, daemon=True)
            self._tracker_thread.start()
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="console-http", daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        with self._published:
            self._closing = True
            self._published.notify_all()
        if self._watcher is not None:
            self._watcher.join()
        if self._session_poller is not None:
            self._session_poller.join()
        if self._tracker_thread is not None:
            self._tracker_thread.join()
        if self._thread is not None:
            self._server.shutdown()
        self._server.server_close()
        self.log.close()
