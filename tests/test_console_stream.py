"""The console's update stream, registry watcher and command (#855).

Run: just agent-workflow-tests
"""
import http.client
import io
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import service

from . import console_test_support as support

REPO_ROOT = Path(__file__).resolve().parents[1]
FRAME_PREFIX = b"data: "


def open_stream(test, svc):
    connection = http.client.HTTPConnection(*svc.address, timeout=3)
    test.addCleanup(connection.close)
    connection.request("GET", "/api/stream")
    return connection.getresponse()


def next_frame(response) -> bytes:
    """The next view frame's raw lines, keepalive comments skipped."""
    while True:
        line = response.readline()
        if line.startswith(b": keepalive"):
            response.readline()
            continue
        if not line:
            return b""
        lines = [line]
        while lines[-1] not in (b"\n", b""):
            lines.append(response.readline())
        return b"".join(lines)


def next_view(response) -> dict:
    frame = next_frame(response)
    data = [line for line in frame.split(b"\n") if line.startswith(FRAME_PREFIX)]
    return json.loads(data[0][len(FRAME_PREFIX):])


def next_view_listing(response, project_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        view = next_view(response)
        if project_id in json.dumps(view):
            return view
    raise AssertionError(f"no frame listed {project_id}")


class StreamTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.store = root / "state/console/events.sqlite3"
        self.registry = root / "state/fleet/registry.json"

    def start(self, count):
        support.write_registry(self.registry, support.entries(count))
        return support.service(self, self.store, self.registry)

    def test_a_registry_change_reaches_the_stream_within_one_second(self):
        svc = self.start(2)
        response = open_stream(self, svc)
        next_view(response)
        t0 = time.monotonic()
        support.write_registry(self.registry, support.entries(3))
        next_view_listing(response, "owner/p02")
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_the_stream_opens_with_the_current_view(self):
        svc = self.start(2)
        response = open_stream(self, svc)
        self.assertEqual(response.status, 200)
        headers = dict(response.getheaders())
        self.assertEqual(headers["Content-Type"], "text/event-stream; charset=utf-8")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Connection"], "close")
        self.assertNotIn("Content-Length", headers)
        _, _, state = support.request(svc.address, "GET", "/api/state")
        self.assertEqual(response.readline(), b"event: view\n")
        self.assertEqual(response.readline(), b"data: " + state + b"\n")
        self.assertEqual(response.readline(), b"\n")

    def test_a_refresh_that_changes_nothing_sends_nothing(self):
        svc = self.start(2)
        response = open_stream(self, svc)
        next_view(response)
        v0 = svc.version
        support.write_registry(self.registry, support.entries(2))
        self.assertEqual(svc.refresh(), [])
        self.assertEqual(svc.version, v0)
        self.assertIsNone(svc.wait_for_change(v0, timeout=1.0))
        support.write_registry(self.registry, support.entries(3))
        view = next_view(response)
        self.assertIn("owner/p02", json.dumps(view))

    def test_a_registry_change_during_startup_is_not_lost(self):
        support.write_registry(self.registry, support.entries(2))
        real = service.read_fleet
        calls = []

        def wrapper(path):
            fleet = real(path)
            if not calls:
                calls.append(path)
                support.write_registry(self.registry, support.entries(3))
            return fleet

        with mock.patch.object(service, "read_fleet", side_effect=wrapper):
            svc = support.service(self, self.store, self.registry)
        self.assertNotIn(b"owner/p02", svc.view_bytes)
        deadline = time.monotonic() + 2.0
        seen = svc.version - 1
        while b"owner/p02" not in svc.view_bytes and time.monotonic() < deadline:
            got = svc.wait_for_change(seen, timeout=0.5)
            if got is not None:
                seen = got[0]
        self.assertIn(b"owner/p02", svc.view_bytes)

    def test_a_failed_refresh_is_retried_until_it_succeeds(self):
        svc = self.start(2)
        real = svc.log.append
        failing = [True]

        def append(entries):
            if failing[0]:
                raise sqlite3.OperationalError("database is locked")
            return real(entries)

        stderr = io.StringIO()
        with mock.patch.object(svc.log, "append", side_effect=append), \
                mock.patch.object(sys, "stderr", stderr):
            support.write_registry(self.registry, support.entries(3))
            deadline = time.monotonic() + 3
            while "refresh_failed" not in stderr.getvalue() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertIn("console: refresh_failed OperationalError", stderr.getvalue())
            self.assertNotIn(b"owner/p02", svc.view_bytes)
            failing[0] = False
            seen = svc.version
            deadline = time.monotonic() + 3
            while b"owner/p02" not in svc.view_bytes and time.monotonic() < deadline:
                got = svc.wait_for_change(seen, timeout=0.5)
                if got is not None:
                    seen = got[0]
        self.assertIn(b"owner/p02", svc.view_bytes)

    def test_streaming_and_watching_keep_earlier_rows(self):
        svc = self.start(2)
        before = support.log_rows(self.store)
        response = open_stream(self, svc)
        next_view(response)
        support.write_registry(self.registry, support.entries(3))
        next_view_listing(response, "owner/p02")
        support.write_registry(self.registry, [support.entries(3)[0], support.entries(3)[2]])
        deadline = time.monotonic() + 3
        while b"owner/p01" in svc.view_bytes and time.monotonic() < deadline:
            next_view(response)
        self.assertNotIn(b"owner/p01", svc.view_bytes)
        after = support.log_rows(self.store)
        self.assertEqual(after[:len(before)], before)
        self.assertEqual(len(after), len(before) + 2)

    def test_closing_the_service_ends_open_streams(self):
        svc = self.start(2)
        response = open_stream(self, svc)
        next_view(response)
        svc.close()
        self.assertEqual(response.readline(), b"")


def run_console(home, *args):
    env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(REPO_ROOT / "python")}
    return subprocess.Popen(
        [sys.executable, "-m", "agent_tools.console.console", *args],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


class CommandTest(unittest.TestCase):
    def home(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_the_command_serves_on_loopback(self):
        home = self.home()
        support.write_registry(home / ".agents/state/fleet/registry.json", support.entries(2))
        process = run_console(home, "--port", "0")
        self.addCleanup(process.kill)
        self.addCleanup(process.stdout.close)
        self.addCleanup(process.stderr.close)
        line = process.stdout.readline()
        match = re.fullmatch(r"console: serving http://127\.0\.0\.1:(\d+)/\n", line)
        self.assertIsNotNone(match, line)
        status, _, body = support.request(("127.0.0.1", int(match.group(1))), "GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertIn(b"owner/p00", body)
        self.assertIn(b"owner/p01", body)
        self.assertTrue((home / ".agents/state/console/events.sqlite3").exists())
        process.send_signal(15)
        self.assertEqual(process.wait(timeout=5), 0)

    def test_a_taken_port_exits_1(self):
        home = self.home()
        with socket.socket() as held:
            held.bind(("127.0.0.1", 0))
            held.listen()
            port = held.getsockname()[1]
            process = run_console(home, "--port", str(port))
            self.addCleanup(process.stdout.close)
            self.addCleanup(process.stderr.close)
            self.assertEqual(process.wait(timeout=10), 1)
            self.assertTrue(
                process.stderr.read().startswith(f"console: cannot listen on 127.0.0.1:{port}"))

    def test_help_names_the_command(self):
        home = self.home()
        process = run_console(home, "--help")
        self.addCleanup(process.stdout.close)
        self.addCleanup(process.stderr.close)
        self.assertEqual(process.wait(timeout=10), 0)
        self.assertTrue(process.stdout.read().startswith("usage: console "))


if __name__ == "__main__":
    unittest.main()
