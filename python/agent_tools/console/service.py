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
    anything else   404
    other methods   405 with `Allow: GET`

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

Construction order: bind the server (an `OSError` propagates and nothing else is
opened); open the event log; fold it onto the project states, the inbox and the read health; publish the view;
sample the registry's signature; `refresh()`. On any failure after the bind, what was opened is closed and the
exception re-raised. `start()` serves on a daemon thread named `console-http`;
`close()` sets the stop flag, then `closing`, wakes every waiter, joins the watcher and the
tracker thread and tears the rest down; it is idempotent.
"""

import http.server
import json
import socketserver
import sys
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from agent_tools.claims import owner_actions
from agent_tools.console import inbox
from agent_tools.console.event_log import Event, EventLog, utc_now
from agent_tools.console.view import (
    ReadState, derive_view, encode_view, health_change, inbox_changes, inbox_records, project_states,
    read_states, registry_changes)
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
TRACKER_SECONDS = 120.0
TRACKER_THREAD = "console-tracker-poll"


def default_store() -> Path:
    return agent_platform.state_root() / "console" / "events.sqlite3"


def default_registry() -> Path:
    return agent_platform.registry_path()


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
        self._send(405, "text/plain", b"method not allowed\n",
                   ("Allow", "GET"), ("Connection", "close"))

    do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _refuse_method


class ConsoleService:
    def __init__(self, store: Path, registry: Path, *, port: int = DEFAULT_PORT,
                 poll_seconds: float = POLL_SECONDS,
                 tracker: Callable[..., list[dict]] | None = None,
                 tracker_seconds: float = TRACKER_SECONDS,
                 slug_of: Callable[[str], str | None] = owner_actions.checkout_slug,
                 activity: Callable[[str], float | None] = inbox.local_activity,
                 clock: Callable[[], float] = time.time):
        self.registry = Path(registry)
        self._poll_seconds = poll_seconds
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
            self._inbox = inbox_records(events)
            self._health = read_states(events)
            self._publish()
            self._signature = signature(self.registry)
            self.refresh()
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
        view = encode_view(derive_view(self._states.values(), self._inbox, self._health))
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

    def _fold(self, appended: list[Event]) -> None:
        self._states = project_states(appended, self._states)
        self._inbox = inbox_records(appended, self._inbox)
        self._health = read_states(appended, self._health)

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
        if self._tracker_thread is not None:
            self._tracker_thread.join()
        if self._thread is not None:
            self._server.shutdown()
        self._server.server_close()
        self.log.close()
