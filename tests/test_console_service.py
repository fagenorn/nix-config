"""The console's loopback service (#855): the log-backed state endpoint and the page.

Run: just agent-workflow-tests
"""
import contextlib
import inspect
import io
import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import service
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


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.store = root / "state/console/events.sqlite3"
        self.registry = root / "state/fleet/registry.json"

    def start(self, items=None):
        if items is not None:
            support.write_registry(self.registry, items)
        return support.service(self, self.store, self.registry)


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
    def test_no_endpoint_changes_anything(self):
        svc = self.start(support.entries(1))
        rows = support.log_rows(self.store)
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            for path in ("/api/state", "/"):
                status, headers, _ = support.request(svc.address, method, path)
                self.assertEqual((method, path, status), (method, path, 405))
                self.assertEqual(headers["Allow"], "GET")
        self.assertEqual(support.log_rows(self.store), rows)


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


if __name__ == "__main__":
    unittest.main()
