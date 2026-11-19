"""The owner port answers only the owner's own processes (#1294, ADR-console-076).

Run: just agent-workflow-tests
"""
import contextlib
import http.client
import inspect
import io
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_tools.console import peer, service, write_guard

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_briefs import PARTS

ROUTES_UNDER_TEST = sorted(service.ROUTES) + [service.PICTURE_PREFIX + "0" * 64, "/nowhere"]
NOT_OWNER = peer.NOT_OWNER_TEXT.encode() + b"\n"
UNREADABLE = peer.UNREADABLE_TEXT.encode() + b"\n"
REFUSED = (403, NOT_OWNER)
SESSION_START = support.hook_body("session start", cwd="/srv/p00")
PLATFORM_READER = sys.platform == "darwin" or sys.platform.startswith("linux")


def other(client, server):
    return (peer.Holder(4242, os.geteuid() + 1, "curl"),)


def owner_as(command):
    def reader(client, server):
        return (peer.Holder(4243, os.geteuid(), command),)
    return reader


def none_reader(client, server):
    return None


def raising_reader(client, server):
    raise RuntimeError("boom")


class Recording:
    def __init__(self, base):
        self.base = base
        self.calls = []

    def __call__(self, client, server):
        self.calls.append((client, server))
        return self.base(client, server)


class Switch:
    def __init__(self, reader):
        self.reader = reader

    def __call__(self, client, server):
        return self.reader(client, server)


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "state/console/events.sqlite3"
        self.registry = self.root / "state/fleet/registry.json"
        support.write_registry(self.registry, support.entries(2))

    def start(self, reader, **kwargs):
        return support.service(self, self.store, self.registry, peer_reader=reader, **kwargs)

    def raw(self, svc, method, path, headers=None, length=None, host=None):
        connection = http.client.HTTPConnection(*svc.address, timeout=5)
        try:
            connection.putrequest(method, path, skip_host=True)
            connection.putheader("Host", f"{svc.address[0]}:{svc.address[1]}" if host is None else host)
            for name, value in (headers or {}).items():
                connection.putheader(name, value)
            if length is not None:
                connection.putheader("Content-Length", str(length))
            connection.endheaders()
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def wire(self, address, request, shut=False, timeout=5.0):
        with socket.create_connection(address, timeout=timeout) as sock:
            sock.sendall(request)
            if shut:
                sock.shutdown(socket.SHUT_WR)
            chunks = []
            try:
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
            except TimeoutError:
                pass
            return b"".join(chunks)

    def unchanged(self, svc, action):
        rows, view = support.log_rows(self.store), svc.view_bytes
        result = action()
        self.assertEqual(support.log_rows(self.store), rows)
        self.assertEqual(svc.view_bytes, view)
        return result

    def wait_hook(self):
        deadline = time.monotonic() + 2.0
        rows = []
        while time.monotonic() < deadline:
            rows = [row for row in support.log_rows(self.store)
                    if row[2] == "session.hook" and row[3] == "owner/p00"
                    and json.loads(row[4])["event"] == "SessionStart"]
            if rows:
                break
            time.sleep(0.02)
        return rows


class OtherUserTest(Case):
    def test_another_users_connection_is_refused_on_every_route(self):
        svc = self.start(other)
        host = f"{svc.address[0]}:{svc.address[1]}"
        headers = {"Content-Type": "application/json", "Origin": f"http://{host}",
                   "X-Console-Token": svc.page_token}
        for route in ROUTES_UNDER_TEST:
            for method in ("GET", "POST", "PUT", "TRACE", "PROPFIND"):
                with self.subTest(route=route, method=method):
                    got = self.unchanged(
                        svc, lambda: self.raw(svc, method, route, headers=headers, length=100))
                    self.assertEqual((got[0], got[2]), REFUSED)
                    self.assertTrue(got[1]["Content-Type"].startswith("text/plain"))
                    self.assertEqual(got[1]["Connection"], "close")

    def test_the_hook_route_refuses_another_user_before_its_body(self):
        svc = self.start(other)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            got, got2 = self.unchanged(svc, lambda: (
                support.post_hook(svc.address, SESSION_START),
                support.post_reading(svc.address, b"{}")))
        self.assertEqual((got[0], got[2]), REFUSED)
        self.assertEqual((got2[0], got2[2]), REFUSED)
        self.assertEqual(self.wait_hook(), [])
        self.assertEqual(errors.getvalue().splitlines(), ["console: peer_refused other_user"] * 2)

    def test_valid_credentials_do_not_pass_for_another_user(self):
        switch = Switch(owner_as("python3"))
        svc = self.start(switch)
        sid = svc.state_goal("owner/p00", "a goal")
        secret = (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")
        switch.reader = other
        host = f"{svc.address[0]}:{svc.address[1]}"

        def attempts():
            looked = support.post_page(
                svc.address, "/api/looked",
                {"Origin": f"http://{host}", "X-Console-Token": svc.page_token})
            brief = support.post_page(
                svc.address, "/api/brief", {"Content-Type": "application/json"},
                json.dumps({"sprint_id": sid, "secret": secret, "brief": PARTS}).encode())
            return looked, brief

        for got in self.unchanged(svc, attempts):
            self.assertEqual((got[0], got[2]), REFUSED)

    def test_the_peer_check_comes_before_the_host_and_header_checks(self):
        svc = self.start(other)
        for got in (
                self.raw(svc, "GET", "/api/state", host="attacker.example"),
                self.raw(svc, "GET", "/api/state",
                         headers={"Tailscale-User-Login": "x@example.invalid"})):
            self.assertEqual((got[0], got[2]), REFUSED)

    def test_a_refused_peer_gets_no_interim_continue(self):
        svc = self.start(other)
        host = f"{svc.address[0]}:{svc.address[1]}".encode()
        request = (b"POST /api/looked HTTP/1.1\r\nHost: " + host + b"\r\nExpect: 100-continue\r\n"
                   b"Content-Type: application/json\r\nContent-Length: 2\r\n\r\n")
        answer = self.wire(svc.address, request)
        self.assertTrue(answer.split(b"\r\n", 1)[0].startswith(b"HTTP/1.1 403"), answer)
        self.assertNotIn(b"100 Continue", answer)
        self.assertTrue(answer.endswith(NOT_OWNER))
        owned = self.start(owner_as("python3"))
        host = f"{owned.address[0]}:{owned.address[1]}".encode()
        request = (b"POST /api/looked HTTP/1.1\r\nHost: " + host + b"\r\nExpect: 100-continue\r\n"
                   b"Content-Type: application/json\r\nContent-Length: 2\r\n\r\n")
        answer = self.wire(owned.address, request, timeout=1.0)
        self.assertEqual(answer.split(b"\r\n", 1)[0], b"HTTP/1.1 100 Continue")


class OwnerTest(Case):
    def test_the_owners_connection_is_admitted_on_every_route(self):
        svc = self.start(owner_as("Google Chrome"))
        for route in ROUTES_UNDER_TEST:
            if route == service.STREAM_PATH:
                continue
            for method in ("GET", "POST"):
                with self.subTest(route=route, method=method):
                    got = self.raw(svc, method, route, length=0)
                    self.assertNotIn(got[2], (NOT_OWNER, UNREADABLE))
        got = self.raw(svc, "GET", "/")
        self.assertEqual((got[0], got[2]), (
            200, service.PAGE.replace(write_guard.TOKEN_SLOT, svc.page_token.encode())))
        self.assertEqual(support.post_hook(svc.address, SESSION_START)[0], 204)
        self.assertEqual(len(self.wait_hook()), 1)
        connection = http.client.HTTPConnection(*svc.address, timeout=5)
        self.addCleanup(connection.close)
        connection.request("GET", service.STREAM_PATH)
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertTrue(response.getheader("Content-Type").startswith("text/event-stream"))

    def test_an_owner_sshd_forward_is_admitted(self):
        svc = self.start(owner_as("sshd-session"))
        host = f"{svc.address[0]}:{svc.address[1]}"
        got = self.raw(svc, "GET", "/")
        self.assertEqual((got[0], got[2]), (
            200, service.PAGE.replace(write_guard.TOKEN_SLOT, svc.page_token.encode())))
        before = [row for row in support.log_rows(self.store) if row[2] == "page.looked"]
        got = support.post_page(
            svc.address, "/api/looked",
            {"Origin": f"http://{host}", "X-Console-Token": svc.page_token})
        self.assertEqual(got[0], 204)
        after = [row for row in support.log_rows(self.store) if row[2] == "page.looked"]
        self.assertEqual(len(after), len(before) + 1)

    def test_the_reader_is_asked_about_the_connecting_end(self):
        rec = Recording(owner_as("python3"))
        svc = self.start(rec)
        conn = http.client.HTTPConnection(*svc.address, timeout=5)
        self.addCleanup(conn.close)
        conn.connect()
        sockname = conn.sock.getsockname()[:2]
        conn.request("GET", "/api/state")
        conn.getresponse().read()
        self.assertEqual(rec.calls, [(sockname, svc.address)])
        client, server = rec.calls[0]
        self.assertEqual([type(client[0]), type(client[1]), type(server[0]), type(server[1])],
                         [str, int, str, int])

    def test_one_lookup_per_connection(self):
        rec = Recording(owner_as("python3"))
        svc = self.start(rec)
        statuses = []
        conn = http.client.HTTPConnection(*svc.address, timeout=5)
        self.addCleanup(conn.close)
        for _ in range(2):
            conn.request("GET", "/api/state")
            response = conn.getresponse()
            response.read()
            statuses.append(response.status)
        second = http.client.HTTPConnection(*svc.address, timeout=5)
        self.addCleanup(second.close)
        second.request("GET", "/api/state")
        response = second.getresponse()
        response.read()
        statuses.append(response.status)
        self.assertEqual(len(rec.calls), 2)
        self.assertEqual(statuses, [200, 200, 200])

    @unittest.skipUnless(PLATFORM_READER, "no platform peer reader")
    def test_a_half_closed_owner_connection_keeps_its_answer(self):
        svc = self.start(peer.reader_for(sys.platform))
        host = f"{svc.address[0]}:{svc.address[1]}".encode()
        answer = self.wire(
            svc.address,
            b"GET /api/state HTTP/1.1\r\nHost: " + host + b"\r\nConnection: close\r\n\r\n",
            shut=True)
        self.assertTrue(answer.startswith(b"HTTP/1.1 200"), answer)
        self.assertNotIn(NOT_OWNER, answer)


class UnreadableTest(Case):
    def test_an_unreadable_connection_is_refused(self):
        for name, reader in (("none", none_reader), ("raising", raising_reader), ("absent", None)):
            svc = self.start(reader)
            for route in ROUTES_UNDER_TEST:
                for method in ("GET", "POST"):
                    with self.subTest(reader=name, route=route, method=method):
                        errors = io.StringIO()
                        with contextlib.redirect_stderr(errors):
                            got = self.unchanged(
                                svc, lambda: self.raw(svc, method, route, length=100))
                        self.assertEqual((got[0], got[2]), (403, UNREADABLE))
                        self.assertEqual(errors.getvalue().splitlines(),
                                         ["console: peer_refused unreadable"])


class BoundedLookupsTest(Case):
    def test_lookups_beyond_the_bound_fail_closed_without_running(self):
        import threading
        entered, release, running = threading.Event(), threading.Event(), []

        def blocking(client, server):
            running.append(client)
            entered.set()
            release.wait(5)
            return (peer.Holder(4243, os.geteuid(), "python3"),)

        svc = self.start(blocking, peer_lookups=1)
        self.addCleanup(release.set)
        first = http.client.HTTPConnection(*svc.address, timeout=10)
        self.addCleanup(first.close)
        first.request("GET", "/api/state")
        self.assertTrue(entered.wait(5))
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            got = self.raw(svc, "GET", "/api/state")
        self.assertEqual((got[0], got[2]), (403, UNREADABLE))
        self.assertEqual(errors.getvalue().splitlines(), ["console: peer_refused unreadable"])
        self.assertEqual(len(running), 1)
        release.set()
        self.assertEqual(first.getresponse().status, 200)
        self.assertEqual(self.raw(svc, "GET", "/api/state")[0], 200)


class GuestPortTest(Case):
    def test_the_guest_port_is_not_peer_checked(self):
        rec = Recording(other)
        svc = self.start(rec, guest_port=0)
        host = "desk.invented-tailnet.ts.net"
        connection = http.client.HTTPConnection(*svc.guest_address, timeout=5)
        try:
            connection.putrequest("GET", "/api/whoami", skip_host=True)
            connection.putheader("Host", host)
            connection.endheaders()
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 200)
        finally:
            connection.close()
        answer = self.wire(
            svc.guest_address,
            b"POST /api/looked HTTP/1.1\r\nHost: " + host.encode() + b"\r\nExpect: 100-continue\r\n"
            b"Content-Type: application/json\r\nContent-Length: 2\r\n\r\n", timeout=1.0)
        self.assertNotIn(NOT_OWNER, answer)
        self.assertEqual(answer.split(b"\r\n", 1)[0], b"HTTP/1.1 100 Continue")
        self.assertEqual(rec.calls, [])


class DefaultsTest(Case):
    def test_the_owner_is_the_services_own_uid(self):
        self.assertIs(inspect.signature(service.ConsoleService).parameters["peer_reader"].default,
                      peer.reader_for(sys.platform))
        self.assertEqual(self.start(owner_as("python3")).owner_uid, os.geteuid())
        svc = self.start(owner_as("python3"), owner_uid=os.geteuid() + 1)
        got = self.raw(svc, "GET", "/")
        self.assertEqual((got[0], got[2]), REFUSED)

    @unittest.skipUnless(PLATFORM_READER, "no platform peer reader")
    def test_the_real_reader_admits_this_process(self):
        svc = service.ConsoleService(self.store, self.registry, port=0)
        svc.start()
        self.addCleanup(svc.close)
        self.assertEqual(support.request(svc.address, "GET", "/api/state")[0], 200)


if __name__ == "__main__":
    unittest.main()
