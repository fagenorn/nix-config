"""The console's loopback service (#855): the log-backed state endpoint and the page.

Run: just agent-workflow-tests
"""
import contextlib
import http.client
import inspect
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import deliveries, service, sessions
from agent_tools.console.view import derive_view, encode_view, project_states

from . import console_test_support as support

PAGE_FILE = Path(__file__).resolve().parents[1] / "python/agent_tools/console/page.html"

ARMED = threading.Event()
HITS: list[tuple[str, str]] = []
WATCHER = "console-registry-watch"
AUDITED = {"open", "os.listdir", "os.scandir", "os.mkdir", "os.remove", "os.rename",
           "sqlite3.connect", "sqlite3.connect/handle", "subprocess.Popen", "os.system",
           "os.posix_spawn", "os.exec", "os.fork", "os.spawn"}


def _audit(event, args):
    if ARMED.is_set() and event in AUDITED:
        HITS.append((event, threading.current_thread().name))
        raise RuntimeError(f"audited event {event} while serving state")


sys.addaudithook(_audit)


@contextlib.contextmanager
def metadata_tripwires():
    """Record (never raise on) every filesystem metadata call made while ARMED off the watcher thread."""
    with contextlib.ExitStack() as stack:
        for name in ("stat", "lstat", "fstat", "access", "statvfs"):
            original = getattr(os, name)

            def wrapper(*args, _name=name, _original=original, **kwargs):
                if ARMED.is_set() and threading.current_thread().name != WATCHER:
                    HITS.append((f"os.{_name}", threading.current_thread().name))
                return _original(*args, **kwargs)

            stack.enter_context(mock.patch.object(os, name, wrapper))
        yield


class Tripwire:
    def __init__(self):
        self.touched = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError(f"the log was used: {name}")


def state_under_tripwires(svc):
    log = svc.log
    tripwire = Tripwire()
    svc.log = tripwire
    mocks = {name: mock.Mock(side_effect=AssertionError)
             for name in ("read_fleet", "project_states", "derive_view", "encode_view")}
    try:
        with contextlib.ExitStack() as stack:
            for name, replacement in mocks.items():
                stack.enter_context(mock.patch.object(service, name, replacement))
            stack.enter_context(metadata_tripwires())
            ARMED.set()
            try:
                status, _, body = support.request(svc.address, "GET", "/api/state")
            finally:
                ARMED.clear()
    finally:
        svc.log = log
    return status, body, tripwire.touched, mocks


SID = support.hook_cases()[0][1]["session_id"]


def wait_rows(store, kind, count):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        rows = [row for row in support.log_rows(store) if row[2] == kind]
        if len(rows) >= count:
            return rows
        time.sleep(0.02)
    raise AssertionError(f"fewer than {count} {kind} rows")


def listed(svc):
    """The state of every session the served view lists, by session id."""
    view = json.loads(svc.view_bytes)
    lines = []
    for entry in view["entries"]:
        for project in entry.get("projects", [entry]):
            lines.append(project["outside_sprints"])
    lines.extend(entry["outside_sprints"] for entry in view["unmanaged"])
    return {s["session_id"]: s["state"] for line in lines for s in line["sessions"]}


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.root = root
        self.store = root / "state/console/events.sqlite3"
        self.registry = root / "state/fleet/registry.json"
        self.sessions = root / "sessions"

    def start(self, items=None, **kwargs):
        if items is not None:
            support.write_registry(self.registry, items)
        return support.service(
            self, self.store, self.registry, session_dirs=[self.sessions], **kwargs)


class StateTest(Case):
    def test_the_state_endpoint_returns_the_registered_projects(self):
        items = support.entries(3)
        svc = self.start(items)
        status, headers, body = support.request(svc.address, "GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        view = json.loads(body)
        self.assertEqual(
            sorted(e["project_id"] for e in view["entries"] if e["type"] == "project"),
            sorted(e["project_id"] for e in items))
        self.assertEqual(
            body, encode_view(derive_view(project_states(svc.log.events()).values())))
        rows = support.log_rows(self.store)
        self.assertEqual([row[2] for row in rows], ["project.registered"] * 3)


class RestartTest(Case):
    def test_the_view_is_rebuilt_from_the_log_alone(self):
        items = support.entries(2)
        first = self.start(items)
        _, _, before = support.request(first.address, "GET", "/api/state")
        first.close()
        rows = support.log_rows(self.store)
        self.registry.unlink()
        second = support.service(self, self.store, self.registry)
        _, _, after = support.request(second.address, "GET", "/api/state")
        self.assertEqual(after, before)
        self.assertEqual(
            sorted(e["project_id"] for e in json.loads(after)["entries"]),
            sorted(e["project_id"] for e in items))
        self.assertEqual(support.log_rows(self.store), rows)

    def test_a_restart_over_an_unchanged_registry_appends_nothing(self):
        items = support.entries(2)
        self.start(items).close()
        rows = support.log_rows(self.store)
        self.start().close()
        self.assertEqual(support.log_rows(self.store), rows)


    def test_a_restart_keeps_sessions_until_two_polls_miss_them(self):
        first = self.start([{"project_id": "owner/p00", "root": "/srv/p00"}])
        status, _, _ = support.post_hook(first.address, support.hook_body("session start"))
        self.assertEqual(status, 204)
        wait_rows(self.store, "session.hook", 1)
        first.close()
        second = support.service(
            self, self.store, self.registry, session_dirs=[self.sessions],
            session_poll_seconds=3600)
        self.assertEqual(listed(second), {SID: "idle"})
        appended = second.poll_sessions()
        self.assertEqual([e.kind for e in appended], ["session.gone"])
        self.assertEqual(listed(second), {})


class AppendOnlyTest(Case):
    def test_every_operation_keeps_earlier_rows(self):
        previous = []

        def check():
            nonlocal previous
            rows = support.log_rows(self.store)
            self.assertEqual(rows[:len(previous)], previous)
            self.assertGreaterEqual(len(rows), len(previous))
            previous = rows
            return rows

        svc = self.start()
        check()
        items = support.entries(3)
        support.write_registry(self.registry, items[:2])
        svc.refresh()
        check()
        support.write_registry(self.registry, items)
        svc.refresh()
        check()
        items[0] = {**items[0], "root": "/srv/moved"}
        support.write_registry(self.registry, items)
        svc.refresh()
        check()
        del items[1]
        support.write_registry(self.registry, items)
        svc.refresh()
        check()
        self.registry.write_bytes(b"{not json")
        with contextlib.redirect_stderr(io.StringIO()):
            svc.refresh()
        check()
        self.registry.unlink()
        svc.refresh()
        check()
        for method, path in (("GET", "/"), ("GET", "/api/state"),
                             ("GET", "/missing"), ("POST", "/api/state")):
            support.request(svc.address, method, path)
        check()
        raw = sqlite3.connect(self.store)
        try:
            for statement in ("UPDATE events SET payload = '{}'", "DELETE FROM events"):
                with self.assertRaises(sqlite3.IntegrityError):
                    raw.execute(statement)
        finally:
            raw.close()
        check()
        svc.close()
        second = support.service(self, self.store, self.registry)
        check()
        support.write_registry(self.registry, [{"project_id": "owner/new", "root": "/srv/new"}])
        second.refresh()
        second.close()
        support.service(self, self.store, self.registry)
        rows = check()
        self.assertGreaterEqual(len(rows), 7)


class NoIoTest(Case):
    def setUp(self):
        super().setUp()
        self.svc = self.start(support.entries(2))
        support.request(self.svc.address, "GET", "/api/state")
        HITS.clear()

    def test_serving_state_touches_no_store_file_or_subprocess(self):
        expected = self.svc.view_bytes
        status, body, touched, mocks = state_under_tripwires(self.svc)
        self.assertEqual(status, 200)
        self.assertEqual(body, expected)
        self.assertEqual(HITS, [])
        self.assertEqual(touched, [])
        for replacement in mocks.values():
            replacement.assert_not_called()

    def test_a_handler_side_stat_fails_the_check(self):
        original = service.ConsoleService.__dict__["view_bytes"]
        stat_then_view = property(lambda self: (self.registry.exists(), original.fget(self))[1])
        with mock.patch.object(service.ConsoleService, "view_bytes", stat_then_view):
            status, _, _, _ = state_under_tripwires(self.svc)
        self.assertEqual(status, 200)
        names = [name for name, _ in HITS]
        self.assertIn("os.stat", names)
        self.assertNotEqual(
            [thread for name, thread in HITS if name == "os.stat"][0],
            threading.current_thread().name)


class LoopbackTest(Case):
    def test_the_service_binds_loopback_only(self):
        svc = self.start()
        self.assertEqual(svc.address[0], "127.0.0.1")
        self.assertGreater(svc.address[1], 0)
        self.assertNotIn("host", inspect.signature(service.ConsoleService).parameters)

    def test_a_foreign_host_header_is_refused(self):
        svc = self.start()
        status, headers, body = support.request(
            svc.address, "GET", "/api/state", host="attacker.example")
        self.assertEqual(status, 403)
        self.assertEqual(headers["Content-Type"], "text/plain")
        self.assertEqual(body, b"loopback only\n")
        status, _, _ = support.request(
            svc.address, "GET", "/api/state", host=f"localhost:{svc.address[1]}")
        self.assertEqual(status, 200)


class PageRouteTest(Case):
    def test_the_page_is_served_from_memory_with_its_policy(self):
        svc = self.start()
        status, headers, body = support.request(svc.address, "GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(body, PAGE_FILE.read_bytes())
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(headers["Content-Security-Policy"], service.CSP)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(int(headers["Content-Length"]), len(body))
        self.assertEqual(support.request(svc.address, "GET", "/missing")[0], 404)


class MethodTest(Case):
    def test_only_the_hook_route_takes_a_write(self):
        svc = self.start(support.entries(1))
        rows = support.log_rows(self.store)
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            for path in ("/api/state", "/"):
                status, headers, _ = support.request(svc.address, method, path)
                self.assertEqual((method, path, status), (method, path, 405))
                self.assertEqual(headers["Allow"], "GET")
        for method in ("GET", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            status, headers, _ = support.request(svc.address, method, "/api/hooks")
            self.assertEqual((method, status), (method, 405))
            self.assertEqual(headers["Allow"], "POST")
        self.assertEqual(support.log_rows(self.store), rows)


def git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True)


class HookTest(Case):
    ITEMS = [{"project_id": "owner/p00", "root": "/srv/p00"}]

    def test_each_hook_is_answered_204_with_no_body_and_recorded(self):
        svc = self.start(self.ITEMS)
        for name, payload, _ in support.hook_cases():
            status, headers, body = support.post_hook(svc.address, json.dumps(payload).encode())
            self.assertEqual((name, status, body), (name, 204, b""))
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        rows = wait_rows(self.store, "session.hook", 12)
        self.assertEqual({row[3] for row in rows}, {"owner/p00"})

    def test_the_answer_does_not_wait_for_the_log(self):
        svc = self.start(self.ITEMS)
        gate = threading.Event()
        real = svc.log.append

        def append(entries):
            gate.wait(5)
            return real(entries)

        with mock.patch.object(svc.log, "append", side_effect=append):
            t0 = time.monotonic()
            status, _, body = support.post_hook(svc.address, support.hook_body("finished turn"))
            elapsed = time.monotonic() - t0
            self.assertEqual((status, body), (204, b""))
            self.assertLess(elapsed, 1.0)
            gate.set()
            wait_rows(self.store, "session.hook", 1)

    def test_unknown_events_and_fields_are_accepted_and_ignored(self):
        svc = self.start(self.ITEMS)
        common = support.hook_cases()[0][1]
        status, _, _ = support.post_hook(
            svc.address, json.dumps({**common, "hook_event_name": "PreCompact"}).encode())
        self.assertEqual(status, 204)
        buffer = io.StringIO()
        with mock.patch.object(service.sys, "stderr", buffer):
            status, _, _ = support.post_hook(svc.address, b"{not json")
            self.assertEqual(status, 204)
            deadline = time.monotonic() + 1
            while "console: hook_unreadable" not in buffer.getvalue() \
                    and time.monotonic() < deadline:
                time.sleep(0.02)
        self.assertTrue(buffer.getvalue().startswith("console: hook_unreadable"),
                        buffer.getvalue())
        body = json.loads(support.hook_body("finished turn"))
        body["future_field"] = {"a": 1}
        status, _, _ = support.post_hook(svc.address, json.dumps(body).encode())
        self.assertEqual(status, 204)
        wait_rows(self.store, "session.hook", 1)
        time.sleep(0.2)
        rows = [row for row in support.log_rows(self.store) if row[2] == "session.hook"]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("future_field", json.loads(rows[0][4]))

    def test_a_browser_request_is_refused(self):
        svc = self.start(self.ITEMS)
        body = support.hook_body("finished turn")
        status, _, _ = support.post_hook(
            svc.address, body,
            {"Content-Type": "application/json", "Origin": "http://example.test"})
        self.assertEqual(status, 403)
        status, _, _ = support.post_hook(svc.address, body, {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        status, _, _ = support.post_hook(svc.address, body, host="evil.test")
        self.assertEqual(status, 403)
        status, _, _ = support.post_hook(
            svc.address, body, {"Content-Type": "Application/JSON; charset=utf-8"})
        self.assertEqual(status, 204)
        connection = http.client.HTTPConnection(*svc.address, timeout=5)
        try:
            connection.putrequest("POST", "/api/hooks")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(service.MAX_HOOK_BYTES + 1))
            connection.endheaders(b"x")
            self.assertEqual(connection.getresponse().status, 413)
        finally:
            connection.close()
        connection = http.client.HTTPConnection(*svc.address, timeout=5)
        try:
            connection.putrequest("POST", "/api/hooks")
            connection.putheader("Content-Type", "application/json")
            connection.endheaders()
            self.assertEqual(connection.getresponse().status, 411)
        finally:
            connection.close()
        wait_rows(self.store, "session.hook", 1)
        time.sleep(0.2)
        kinds = [row[2] for row in support.log_rows(self.store)]
        self.assertEqual(kinds.count("session.hook"), 1)
        self.assertEqual(kinds.count("project.registered"), 1)

    def test_a_worktree_session_is_listed_under_the_main_checkout(self):
        main, wt = self.root / "main", self.root / "wt"
        git("init", "-q", "-b", "main", str(main))
        git("-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t",
            "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "x")
        git("-C", str(main), "worktree", "add", "-q", str(wt), "-b", "wt")
        (wt / "sub").mkdir()
        svc = self.start([{"project_id": "owner/main", "root": os.path.realpath(main)}],
                         repo_of=sessions.main_checkout)
        status, _, _ = support.post_hook(
            svc.address, support.hook_body("session start", cwd=str(wt / "sub")))
        self.assertEqual(status, 204)
        deadline = time.monotonic() + 2
        seen, view, found = -1, None, []
        while not found and time.monotonic() < deadline:
            change = svc.wait_for_change(seen, 0.2)
            if change is not None:
                seen, raw = change
                view = json.loads(raw)
                found = [s for e in view["entries"] if e["project_id"] == "owner/main"
                         for s in e["outside_sprints"]["sessions"]]
        self.assertEqual([(s["cwd"], s["state"]) for s in found], [(str(wt / "sub"), "idle")])
        self.assertEqual(view["unmanaged"], [])

    def test_a_session_outside_any_repository_is_not_listed(self):
        plain = self.root / "plain"
        plain.mkdir()
        svc = self.start(self.ITEMS, repo_of=sessions.main_checkout)
        status, _, _ = support.post_hook(
            svc.address, support.hook_body("session start", cwd=str(plain)))
        self.assertEqual(status, 204)
        row = wait_rows(self.store, "session.hook", 1)[0]
        self.assertIsNone(json.loads(row[4])["repo"])
        self.assertIsNone(row[3])
        self.assertEqual(listed(svc), {})
        self.assertEqual(json.loads(svc.view_bytes)["unmanaged"], [])

    def test_a_hook_moves_the_projects_activity(self):
        svc = self.start(self.ITEMS)
        support.post_hook(svc.address, support.hook_body("finished turn"))
        row = wait_rows(self.store, "session.hook", 1)[0]
        entry = json.loads(svc.view_bytes)["entries"][0]
        self.assertEqual(entry["last_activity"], row[1])
        self.assertFalse(entry["quiet"])

    def test_the_default_session_directories_cover_every_profile(self):
        with tempfile.TemporaryDirectory() as raw:
            home, accounts = Path(raw) / "home", Path(raw) / "accounts"
            (accounts / "profiles/b/sessions").mkdir(parents=True)
            (accounts / "profiles/a/sessions").mkdir(parents=True)
            with mock.patch.dict(os.environ, {"HOME": str(home),
                                              "CLAUDE_ACCOUNTS_DIR": str(accounts)}):
                self.assertEqual(
                    service.default_session_dirs(),
                    [home / ".claude/sessions", accounts / "profiles/a/sessions",
                     accounts / "profiles/b/sessions"])
            fallback = home / ".claude-accounts"
            (fallback / "profiles/c/sessions").mkdir(parents=True)
            environment = {k: v for k, v in os.environ.items() if k != "CLAUDE_ACCOUNTS_DIR"}
            environment["HOME"] = str(home)
            with mock.patch.dict(os.environ, environment, clear=True):
                self.assertEqual(
                    service.default_session_dirs(),
                    [home / ".claude/sessions", fallback / "profiles/c/sessions"])

    def test_an_unchanged_registry_appends_nothing(self):
        support.write_session(self.sessions, pid=os.getpid(), session_id="s1",
                              cwd="/srv/p00", status="busy")
        svc = self.start(self.ITEMS)
        self.assertEqual(svc.poll_sessions(), [])
        rows = [row for row in support.log_rows(self.store) if row[2] == "session.seen"]
        self.assertEqual(len(rows), 1)

    def interleave(self, svc, hook):
        """Run one poll whose reading is followed, before its application, by a hook."""
        real = sessions.read_session_registry
        state = {}

        def reading(directories, *args, **kwargs):
            result = real(directories, *args, **kwargs)
            thread = threading.Thread(
                target=svc.ingest_hook, args=(support.hook_body(hook),))
            thread.start()
            thread.join(0.3)
            state["blocked"] = thread.is_alive()
            state["thread"] = thread
            return result

        with mock.patch.object(service.sessions, "read_session_registry", reading):
            svc.poll_sessions()
        state["thread"].join(2)
        self.assertFalse(state["thread"].is_alive())
        return state["blocked"]

    def stale_busy_session(self):
        support.write_session(
            self.sessions, pid=os.getpid(), session_id=SID, cwd="/srv/p00", status="busy",
            updated_at=int(time.time() * 1000) - 10000)
        svc = self.start(self.ITEMS, session_poll_seconds=3600)
        self.assertEqual(listed(svc), {SID: "working"})
        return svc

    def test_a_poll_reading_from_before_a_hook_does_not_overwrite_it(self):
        svc = self.stale_busy_session()
        self.assertTrue(self.interleave(svc, "permission prompt"))
        self.assertEqual(listed(svc), {SID: "waiting_permission"})
        self.assertEqual(len(wait_rows(self.store, "session.seen", 1)), 1)
        self.assertEqual(svc.poll_sessions(), [])
        self.assertEqual(listed(svc), {SID: "waiting_permission"})

    def test_a_reading_made_after_the_answer_is_newer_than_the_hook_it_followed(self):
        svc = self.start(self.ITEMS, clock=lambda: time.time() - 5)
        received = int((time.time() - 5) * 1000)
        gate = threading.Event()
        real = svc.log.append

        def append(entries):
            gate.wait(5)
            return real(entries)

        with mock.patch.object(svc.log, "append", side_effect=append):
            status, _, _ = support.post_hook(svc.address, support.hook_body("finished turn"))
            self.assertEqual(status, 204)
            support.write_session(
                self.sessions, pid=os.getpid(), session_id=SID, cwd="/srv/p00",
                status="busy", updated_at=received + 2000)
            gate.set()
            wait_rows(self.store, "session.hook", 1)
        self.assertEqual(listed(svc), {SID: "idle"})
        svc.poll_sessions()
        self.assertEqual(listed(svc), {SID: "working"})

    def test_an_unrelated_notification_does_not_hide_a_newer_reading(self):
        support.write_session(
            self.sessions, pid=os.getpid(), session_id=SID, cwd="/srv/p00", status="idle",
            updated_at=int(time.time() * 1000) - 10000)
        svc = self.start(self.ITEMS, session_poll_seconds=3600)
        support.write_session(self.sessions, pid=os.getpid(), session_id=SID, cwd="/srv/p00",
                              status="busy", updated_at=int(time.time() * 1000) - 5000)
        svc.ingest_hook(support.hook_body("other notification"))
        svc.poll_sessions()
        self.assertEqual(listed(svc), {SID: "working"})

    def test_a_registry_record_with_a_nul_in_its_directory_does_not_stop_the_service(self):
        support.write_session(self.sessions, pid=os.getpid(), session_id="bad",
                              cwd="/srv/p00\u0000x", status="busy")
        support.write_session(self.sessions, pid=os.getppid(), session_id="ok",
                              cwd="/srv/p00", status="idle")
        svc = self.start(self.ITEMS)
        svc.poll_sessions()
        self.assertEqual(listed(svc), {"ok": "idle"})

    def test_a_poll_reading_from_before_a_session_end_does_not_bring_it_back(self):
        svc = self.stale_busy_session()
        self.assertTrue(self.interleave(svc, "session end"))
        self.assertEqual(listed(svc), {})
        self.assertEqual(svc.poll_sessions(), [])
        self.assertEqual(listed(svc), {})
        (self.sessions / f"{os.getpid()}.json").unlink()
        svc.poll_sessions()
        svc.poll_sessions()
        gone = [row for row in support.log_rows(self.store) if row[2] == "session.gone"]
        self.assertEqual(len(gone), 1)


class ReadFleetTest(Case):
    def read(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            return service.read_fleet(self.registry), err.getvalue()

    def test_only_a_valid_registry_is_a_reading(self):
        self.assertEqual(self.read(), (None, ""))
        self.registry.parent.mkdir(parents=True)
        self.registry.write_bytes(b"{not json")
        entries, err = self.read()
        self.assertIsNone(entries)
        self.assertTrue(err.startswith("console: registry_unreadable"), err)
        self.registry.write_text(
            json.dumps({"schema_version": 1, "projects": [{"project_id": "x"}]}))
        entries, err = self.read()
        self.assertIsNone(entries)
        self.assertTrue(err.startswith("console: registry_unreadable"), err)
        support.write_registry(self.registry, [])
        self.assertEqual(self.read(), ([], ""))
        items = support.entries(2)
        support.write_registry(self.registry, items)
        self.assertEqual(self.read(), (items, ""))


class BindTest(Case):
    def test_a_taken_port_raises_before_the_log_opens(self):
        with socket.socket() as held:
            held.bind(("127.0.0.1", 0))
            held.listen()
            with self.assertRaises(OSError):
                service.ConsoleService(self.store, self.registry, port=held.getsockname()[1])
        self.assertFalse(self.store.exists())


class DeliveryTest(Case):
    SINGLE = Path(__file__).parent / "fixtures/console/journals/single.jsonl"

    def setUp(self):
        super().setUp()
        self.now = 1_800_000_000.0
        self.lines = self.SINGLE.read_text().splitlines(keepends=True)
        self.svc = self.start([{"project_id": "owner/p00", "root": "/srv/p00"}],
                              session_poll_seconds=3600, clock=lambda: self.now)
        body = support.hook_body("session start", cwd="/srv/p00")
        self.sid = json.loads(body)["session_id"]
        self.svc.ingest_hook(body)
        self.J = (self.root / "projects/-srv-p00" / self.sid
                  / "subagents/workflows/wf_t1/journal.jsonl")

    def write(self, n, start=0, mode="w"):
        self.J.parent.mkdir(parents=True, exist_ok=True)
        with open(self.J, mode) as handle:
            handle.write("".join(self.lines[start:n]))
        self.touch()

    def touch(self, path=None):
        os.utime(path or self.J, ns=(int(self.now * 1e9),) * 2)

    def runs(self, svc=None):
        view = json.loads((svc or self.svc).view_bytes)
        for entry in view["entries"]:
            for project in entry.get("projects", [entry]):
                if project["project_id"] == "owner/p00":
                    for s in project["outside_sprints"]["sessions"]:
                        if s["session_id"] == self.sid:
                            return s["deliveries"]
        raise AssertionError("session not listed")

    def rows(self, kind):
        return [row for row in support.log_rows(self.store) if row[2] == kind]

    def test_a_run_with_a_final_record_leaves_the_in_flight_list(self):
        self.write(10)
        self.svc.poll_deliveries()
        self.assertEqual(self.runs(), [{
            "run_id": "wf_t1", "quiet": False, "moved_text": "moved just now",
            "issues": [{"issue": 858, "stage": "building",
                        "stage_text": "building task 1 of 3"}]}])
        seen = self.rows("delivery.seen")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][3], "owner/p00")
        record = self.root / "projects/-srv-p00" / self.sid / "workflows/wf_t1.json"
        record.parent.mkdir(parents=True)
        record.write_text("{}")
        self.svc.poll_deliveries()
        self.assertEqual(self.runs(), [])
        gone = self.rows("delivery.gone")
        self.assertEqual(len(gone), 1)
        self.assertEqual(json.loads(gone[0][4]), {"run_id": "wf_t1", "session_id": self.sid})

    def test_an_unchanged_journal_appends_nothing(self):
        self.write(10)
        for _ in range(3):
            self.svc.poll_deliveries()
        self.assertEqual(len(self.rows("delivery.seen")), 1)
        self.write(14, 10, "a")
        self.svc.poll_deliveries()
        self.assertEqual(len(self.rows("delivery.seen")), 2)
        self.assertEqual(self.runs()[0]["issues"][0]["stage_text"], "building task 2 of 3")

    def test_a_quiet_run_reads_quiet_as_the_clock_moves(self):
        self.write(10)
        self.svc.poll_deliveries()
        self.now += 16 * 60
        self.svc.poll_deliveries()
        self.assertIs(self.runs()[0]["quiet"], True)
        self.assertEqual(self.runs()[0]["moved_text"], "quiet for 16 min")
        self.assertEqual(len(self.rows("delivery.seen")), 1)

    def test_a_run_naming_no_issue_is_not_listed(self):
        self.write(2)
        self.svc.poll_deliveries()
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.rows("delivery.seen"), [])

    def test_a_restart_over_an_unchanged_journal_appends_nothing(self):
        self.write(10)
        self.svc.poll_deliveries()
        self.svc.close()
        second = self.start(session_poll_seconds=3600, clock=lambda: self.now)
        self.assertEqual(self.runs(second)[0]["issues"][0]["stage_text"], "building task 1 of 3")
        self.assertEqual(len(self.rows("delivery.seen")), 1)

    def test_a_failing_delivery_poll_does_not_stop_the_session_poll(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            svc = self.start(session_poll_seconds=0.05)
            with mock.patch.object(svc, "poll_deliveries", side_effect=RuntimeError("boom")):
                deadline = time.monotonic() + 2
                line = "console: delivery_poll_failed RuntimeError: boom"
                while time.monotonic() < deadline and errors.getvalue().count(line) < 2:
                    time.sleep(0.02)
        self.assertGreaterEqual(errors.getvalue().count(line), 2)

    def test_a_truncated_journal_is_folded_again_from_its_start(self):
        self.write(14)
        self.svc.poll_deliveries()
        self.assertEqual(self.runs()[0]["issues"][0]["stage_text"], "building task 2 of 3")
        self.write(3)
        self.svc.poll_deliveries()
        self.assertEqual(self.runs()[0]["issues"],
                         [{"issue": 858, "stage": "planning", "stage_text": "planning"}])

    def test_a_replaced_journal_is_folded_again_from_its_start(self):
        self.write(14)
        self.svc.poll_deliveries()
        sibling = self.J.with_name("journal.next")
        sibling.write_text("".join(self.lines[:3]) + self.lines[0] * 200)
        self.assertGreater(sibling.stat().st_size, self.J.stat().st_size)
        os.replace(sibling, self.J)
        self.touch()
        self.svc.poll_deliveries()
        self.assertEqual(self.runs()[0]["issues"][0]["stage_text"], "planning")

    def test_an_unreadable_journal_keeps_its_run_until_it_reads_again(self):
        self.write(10)
        self.svc.poll_deliveries()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), mock.patch.object(
                self.svc._reader, "read",
                return_value=deliveries.Unreadable("PermissionError: denied")):
            self.svc.poll_deliveries()
            self.svc.poll_deliveries()
        self.assertEqual(self.runs()[0]["issues"][0]["stage_text"], "building task 1 of 3")
        self.assertEqual(self.rows("delivery.gone"), [])
        lines = [l for l in errors.getvalue().splitlines()
                 if l.startswith("console: journal_unreadable")]
        self.assertEqual(len(lines), 1)
        self.assertIn(str(self.J), lines[0])
        self.assertIn("PermissionError: denied", lines[0])
        self.write(14, 10, "a")
        self.svc.poll_deliveries()
        self.assertEqual(self.runs()[0]["issues"][0]["stage_text"], "building task 2 of 3")
        self.assertEqual(self.rows("delivery.gone"), [])

    def test_an_unreadable_listing_keeps_the_sessions_runs(self):
        self.write(10)
        self.svc.poll_deliveries()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), mock.patch(
                "agent_tools.console.deliveries.run_journals",
                return_value=deliveries.Unreadable("PermissionError: denied")):
            self.svc.poll_deliveries()
        self.assertEqual(self.runs()[0]["issues"][0]["stage_text"], "building task 1 of 3")
        self.assertEqual(self.rows("delivery.gone"), [])
        lines = [l for l in errors.getvalue().splitlines()
                 if l.startswith("console: journals_unreadable")]
        self.assertEqual(len(lines), 1)

    def test_a_session_id_with_a_nul_neither_blocks_the_polls_nor_the_start(self):
        self.write(10)
        bad = json.loads(support.hook_body("session start", cwd="/srv/p00"))
        bad["session_id"] = "a\x00b"
        self.svc.ingest_hook(json.dumps(bad).encode())
        self.assertIn("a\x00b", {s.session_id for s in self.svc._sessions.values()})
        self.svc.poll_deliveries()
        self.write(14, 10, "a")
        self.svc.poll_deliveries()
        self.assertEqual(self.runs()[0]["issues"][0]["stage_text"], "building task 2 of 3")
        self.assertEqual(len(self.rows("delivery.seen")), 2)
        self.svc.close()
        second = self.start(session_poll_seconds=3600, clock=lambda: self.now)
        self.assertEqual(self.runs(second)[0]["issues"][0]["stage_text"], "building task 2 of 3")

    def test_the_branch_pattern_of_a_session_repo_names_its_issues(self):
        patterns = {"/srv/p00": None}
        self.svc.close()
        svc = self.start(session_poll_seconds=3600, clock=lambda: self.now,
                         branch_pattern_of=lambda repo: patterns[repo])
        self.write(10)
        svc.poll_deliveries()
        self.assertEqual(self.runs(svc), [])
        patterns["/srv/p00"] = "issue-<num>-<slug>"
        svc.poll_deliveries()
        self.assertEqual(self.runs(svc)[0]["issues"][0]["stage_text"], "building task 1 of 3")


if __name__ == "__main__":
    unittest.main()
