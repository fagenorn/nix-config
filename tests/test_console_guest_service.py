"""The guest door of the console service (#1237): the guest port, its route table, scoped reads.

Run: just agent-workflow-tests
"""
import ast
import contextlib
import http.client
import inspect
import io
import json
import os
import queue
import signal
import socket
import subprocess
import tempfile
import time
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

from agent_tools.console import console, guest, serve_probe_check, service, write_guard
from agent_tools.console.activation import Activation
from agent_tools.console.event_log import (
    SHARING_COLLEAGUE, SHARING_TAILNET, EventLog)

from . import console_test_support as support
from .console_test_support import PIXEL, WIDE
from .test_console_stream import next_frame
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
TAILNET = "desk.invented-tailnet.ts.net"
OTHER_HOST = "other.invented-tailnet.ts.net"
COLLEAGUE = "colleague@example.invalid"
STRANGER = "stranger@example.invalid"
FORGED = "forged-probe@example.invalid"
JSON = {"Content-Type": "application/json"}
GOAL = "make the importer resumable"
PARTS = {"title": "Importer resumes after a crash",
         "done": "the importer resumes after a crash", "excluded": ["no new formats"],
         "slices": ["checkpoint", "resume"], "risks": ["partial writes"],
         "asks": ["which store?"]}

TABLE = {
    "/api/looked": "owner", "/api/answer": "owner", "/api/check-answer": "owner",
    "/api/goal": "owner", "/api/withdraw": "owner", "/api/approve": "owner",
    "/api/reply": "owner", "/api/retry-manager": "owner", "/api/message": "owner",
    "/api/stop": "owner", "/api/round-answer": "owner", "/api/continue": "owner",
    "/api/exclusion": "owner", "/api/pin": "owner", "/api/signin": "owner",
    "/api/signin-code": "owner", "/api/signin-cancel": "owner", "/api/signin-link": "owner",
    "/api/account-add": "owner", "/api/account-remove": "owner",
    "/api/register-project": "owner", "/api/plan-answer": "owner",
    "/api/plan-approve": "owner", "/api/adoption-register": "owner", "/api/plan-defer": "owner",
    "/api/register-confirm": "owner", "/api/trust-check": "owner",
    "/api/register-cancel": "owner", "/api/owner-notice": "owner",
    "/api/owner-notice-withdraw": "owner", "/api/project-question": "owner",
    "/api/activate": "owner", "/api/share-tailnet": "owner", "/api/share-colleague": "owner",
    "/api/share-remove": "owner", "/api/look-retry": "owner",
    "/api/brief": "owner", "/api/report": "owner", "/api/close": "owner", "/api/inbox": "owner",
    "/api/message-reply": "owner", "/api/recap": "owner", "/api/ask": "owner",
    "/api/withdraw-question": "owner", "/api/notice": "owner", "/api/notices": "owner",
    "/api/withdraw-notice": "owner", "/api/picture": "owner",
    "/api/hooks": "owner", "/api/readings": "owner", "/spend": "owner",
    "/api/sprint-status": "owner", "/api/profile": "owner", "/api/excluded": "owner",
    "/": "guest", "/api/state": "guest", "/api/stream": "guest", "/api/whoami": "guest",
    "/api/picture/": "guest",
}


def dispatch_violations(source: str, names: Mapping[str, object],
                        routes: frozenset[str]) -> tuple[int, list[str]]:
    """The route comparisons of the handler classes in `source`, and those not registered."""
    violations: list[str] = []
    checked = 0

    def registered(value: object) -> bool:
        if isinstance(value, str):
            return value in routes
        if isinstance(value, (frozenset, set, tuple, dict)):
            return all(member in routes for member in value)
        return False

    def check(operand: ast.expr) -> None:
        if isinstance(operand, (ast.Tuple, ast.Set)):
            for member in operand.elts:
                check(member)
        elif isinstance(operand, ast.Constant):
            if isinstance(operand.value, str) and operand.value.startswith("/"):
                violations.append(f"literal {operand.value} at line {operand.lineno}")
        elif isinstance(operand, ast.Name):
            if operand.id not in names or not registered(names[operand.id]):
                violations.append(f"unregistered {operand.id} at line {operand.lineno}")
        else:
            violations.append(f"unchecked operand at line {operand.lineno}")

    def is_route(node: ast.expr) -> bool:
        return isinstance(node, ast.Name) and node.id == "route"

    for tree_class in ast.walk(ast.parse(source)):
        if not (isinstance(tree_class, ast.ClassDef)
                and tree_class.name in ("ConsoleHandler", "GuestHandler")):
            continue
        for node in ast.walk(tree_class):
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                if any(is_route(operand) for operand in operands):
                    checked += 1
                    for operand in operands:
                        if not is_route(operand):
                            check(operand)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "startswith" and is_route(node.func.value)):
                checked += 1
                argument = node.args[0] if node.args else None
                if not (isinstance(argument, ast.Name) and argument.id == "PICTURE_PREFIX"):
                    violations.append(f"startswith without PICTURE_PREFIX at line {node.lineno}")
    return checked, violations


class GuestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "state/console/events.sqlite3"
        self.registry = self.root / "state/fleet/registry.json"

    def seed(self, tailnet=TAILNET, colleagues=None):
        colleagues = {COLLEAGUE: ["owner/p01"]} if colleagues is None else colleagues
        self.store.parent.mkdir(parents=True, exist_ok=True)
        log = EventLog(self.store)
        try:
            rows = [] if tailnet is None else [(SHARING_TAILNET, None, {"tailnet": tailnet})]
            rows += [(SHARING_COLLEAGUE, None, {"login": login, "projects": projects})
                     for login, projects in colleagues.items()]
            log.append(rows)
        finally:
            log.close()

    def start(self, **kwargs):
        support.write_registry(self.registry, support.entries(2))
        return support.service(self, self.store, self.registry, guest_port=0, **kwargs)

    def request(self, address, method, path, host, logins, headers, length):
        connection = http.client.HTTPConnection(*address, timeout=5)
        try:
            connection.putrequest(method, path, skip_host=True)
            if host is not None:
                connection.putheader("Host", host)
            for login in logins:
                connection.putheader("Tailscale-User-Login", login)
            for name, value in (headers or {}).items():
                for member in (value if isinstance(value, list) else [value]):
                    connection.putheader(name, member)
            if length is not None:
                connection.putheader("Content-Length", str(length))
            connection.endheaders()
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def guest(self, svc, method, path, host=TAILNET, logins=(COLLEAGUE,), headers=None,
              length=None):
        return self.request(svc.guest_address, method, path, host, logins, headers, length)

    def owner(self, svc, method, path, headers=None, length=None):
        return self.request(svc.address, method, path, f"{svc.address[0]}:{svc.address[1]}",
                            (), headers, length)

    def without_reading(self, raw):
        """The owner's view with the guest-port reading removed."""
        state = json.loads(raw)
        del state["sharing"]["last_request"]
        return state

    def unchanged(self, svc, action):
        rows, view = support.log_rows(self.store), self.without_reading(svc.view_bytes)
        result = action()
        self.assertEqual(support.log_rows(self.store), rows)
        self.assertEqual(self.without_reading(svc.view_bytes), view)
        return result

    def open_stream(self, svc):
        connection = http.client.HTTPConnection(*svc.guest_address, timeout=5)
        self.addCleanup(connection.close)
        connection.putrequest("GET", "/api/stream", skip_host=True)
        connection.putheader("Host", TAILNET)
        connection.putheader("Tailscale-User-Login", COLLEAGUE)
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        return response

    def owner_token(self):
        return (self.store.parent / "page-token").read_text().strip()

    def guest_token(self):
        return (self.store.parent / "guest-token").read_text().strip()

    def secret(self, sid):
        return (self.store.parent / "sprint-secrets" / sid).read_text().removesuffix("\n")

    def brief_with_picture(self, svc, project_id, goal, data):
        """A sprint of `project_id` whose brief carries one stored picture; its id."""
        sid = svc.state_goal(project_id, goal)
        status, _, answer = support.post_page(
            svc.address, "/api/picture",
            {"Content-Type": "image/png", "X-Console-Sprint": sid,
             "X-Console-Secret": self.secret(sid)}, data)
        self.assertEqual(status, 200, answer)
        picture_id = json.loads(answer)["picture"]
        body = json.dumps({"sprint_id": sid, "secret": self.secret(sid), "brief": {
            **PARTS, "pictures": [{"picture": picture_id, "line": "the shot"}]}}).encode()
        status, _, answer = support.post_page(svc.address, "/api/brief", JSON, body)
        self.assertEqual(status, 200, answer)
        return picture_id


class RouteTableTest(GuestCase):
    def test_the_table_names_every_route_of_the_service(self):
        self.assertEqual(set(TABLE), service.ROUTES)
        self.assertEqual({route for route, side in TABLE.items() if side == "owner"},
                         service.OWNER_ONLY)
        for name, value in vars(service).items():
            if (name.endswith(("_PATH", "_PREFIX")) and isinstance(value, str)
                    and value.startswith("/")):
                with self.subTest(name=name):
                    self.assertIn(value, TABLE)

    def test_no_handler_dispatches_on_an_unregistered_route(self):
        checked, violations = dispatch_violations(
            inspect.getsource(service), vars(service), service.ROUTES)
        self.assertEqual(violations, [])
        self.assertGreaterEqual(checked, 40)
        source = ("class GuestHandler:\n    def do_GET(self):\n        route = self.path\n"
                  "        if route == '/api/new':\n            pass\n"
                  "        elif route == NEW_PATH:\n            pass\n")
        _, found = dispatch_violations(source, {"NEW_PATH": "/api/other"}, service.ROUTES)
        self.assertEqual(len(found), 2)

    def test_every_owner_only_route_is_403_before_its_body_on_the_guest_port(self):
        self.seed()
        svc = self.start()
        for route in sorted(service.OWNER_ONLY):
            for method in ("GET", "POST"):
                with self.subTest(route=route, method=method):
                    status, headers, body = self.unchanged(
                        svc, lambda: self.guest(svc, method, route, headers=JSON, length=100))
                    self.assertEqual(status, 403)
                    self.assertEqual(body, guest.OWNER_ONLY_TEXT.encode() + b"\n")
                    self.assertTrue(headers["Content-Type"].startswith("text/plain"))

    def test_an_unsupported_method_is_refused_like_a_supported_one(self):
        self.seed()
        svc = self.start()
        for route in sorted(service.OWNER_ONLY):
            for method in ("TRACE", "CONNECT", "PROPFIND"):
                with self.subTest(route=route, method=method):
                    status, headers, body = self.unchanged(
                        svc, lambda: self.guest(svc, method, route, headers=JSON, length=100))
                    self.assertEqual(status, 403)
                    self.assertEqual(body, guest.OWNER_ONLY_TEXT.encode() + b"\n")
                    self.assertTrue(headers["Content-Type"].startswith("text/plain"))
        status, _, body = self.guest(svc, "TRACE", "/api/state", logins=(STRANGER,))
        self.assertEqual((status, body), (403, guest.NOT_SHARED_TEXT.encode() + b"\n"))
        status, headers, _ = self.guest(svc, "TRACE", "/api/state")
        self.assertEqual((status, headers["Allow"]), (405, "GET"))
        self.assertEqual(self.guest(svc, "TRACE", "/nowhere")[0], 404)

    def test_the_guest_reads_answer(self):
        self.seed()
        svc = self.start()
        status, headers, body = self.guest(svc, "GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(body, service.GUEST_PAGE.replace(
            write_guard.TOKEN_SLOT, svc.guest_token.encode()))
        self.assertIn(service.DOOR_GUEST, body)
        self.assertEqual(service.PAGE.count(service.DOOR_OWNER), 1)
        self.assertEqual(service.GUEST_PAGE.count(service.DOOR_GUEST), 1)
        _, _, owned = self.owner(svc, "GET", "/")
        self.assertIn(service.DOOR_OWNER, owned)
        self.assertNotIn(service.DOOR_GUEST, owned)
        self.assertNotIn(svc.page_token.encode(), body)
        self.assertEqual(headers["Content-Security-Policy"], service.CSP)
        status, headers, body = self.guest(svc, "GET", "/api/state")
        self.assertEqual((status, headers["Content-Type"]), (200, "application/json"))
        self.assertNotIn("sharing", json.loads(body))
        connection = http.client.HTTPConnection(*svc.guest_address, timeout=5)
        self.addCleanup(connection.close)
        connection.putrequest("GET", "/api/stream", skip_host=True)
        connection.putheader("Host", TAILNET)
        connection.putheader("Tailscale-User-Login", COLLEAGUE)
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "text/event-stream; charset=utf-8")
        self.assertTrue(next_frame(response).startswith(b"event: view\ndata: "))
        self.assertEqual(self.guest(svc, "GET", "/api/whoami")[0], 200)
        status, _, body = self.guest(
            svc, "GET", "/api/picture/" + "0" * 64,
            headers={"X-Console-Token": svc.guest_token})
        self.assertEqual((status, body), (404, b"this picture is not known\n"))
        status, headers, _ = self.guest(svc, "PUT", "/api/state")
        self.assertEqual((status, headers["Allow"]), (405, "GET"))
        self.assertEqual(self.guest(svc, "GET", "/nowhere")[0], 404)


class AdmissionTest(GuestCase):
    def test_an_unadmitted_request_is_refused_in_plain_words(self):
        rows = (
            (False, TAILNET, [COLLEAGUE], guest.SHARING_OFF_TEXT),
            (True, OTHER_HOST, [COLLEAGUE], guest.HOST_TEXT),
            (True, TAILNET + ":443", [COLLEAGUE], guest.HOST_TEXT),
            (True, None, [COLLEAGUE], guest.HOST_TEXT),
            (True, TAILNET, [], guest.NOT_SHARED_TEXT),
            (True, TAILNET, [COLLEAGUE, COLLEAGUE], guest.NOT_SHARED_TEXT),
            (True, TAILNET, [STRANGER], guest.NOT_SHARED_TEXT),
        )
        for seeded, host, logins, text in rows:
            with self.subTest(seeded=seeded, host=host, logins=logins):
                with tempfile.TemporaryDirectory() as tmp:
                    self.store = Path(tmp) / "state/console/events.sqlite3"
                    self.registry = Path(tmp) / "state/fleet/registry.json"
                    if seeded:
                        self.seed()
                    svc = self.start()
                    for route in sorted(service.ROUTES - {service.WHOAMI_PATH}):
                        status, _, body = self.unchanged(
                            svc, lambda: self.guest(svc, "GET", route, host=host, logins=logins))
                        self.assertEqual((route, status, body), (route, 403, text.encode() + b"\n"))
                        for marker in (b"owner/p0", b"/srv/p0", COLLEAGUE.encode(),
                                       STRANGER.encode()):
                            self.assertNotIn(marker, body)
                    svc.close()

    def test_whoami_answers_any_request(self):
        svc = self.start()
        status, _, body = self.guest(svc, "GET", "/api/whoami", host=OTHER_HOST, logins=())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "forwarded_for": False, "host": OTHER_HOST, "hosts": 1, "login_headers": 0,
            "probe_login_arrived": False})
        svc.close()
        self.seed()
        svc = self.start()
        status, _, body = self.guest(
            svc, "GET", "/api/whoami", logins=[FORGED],
            headers={"X-Console-Probe": FORGED, "X-Forwarded-For": "100.64.0.1"})
        self.assertEqual(status, 200)
        answer = json.loads(body)
        self.assertEqual(
            (answer["login_headers"], answer["forwarded_for"], answer["probe_login_arrived"]),
            (1, True, True))
        self.assertNotIn(FORGED.encode(), body)


class OwnerPortTest(GuestCase):
    def test_the_owner_port_refuses_identity_and_forwarded_headers(self):
        self.seed()
        svc = self.start()
        extra = ({"Tailscale-User-Login": COLLEAGUE}, {"Tailscale-User-Name": "Colleague"},
                 {"X-Forwarded-For": "100.64.0.1"})
        for route in sorted(service.ROUTES):
            for method in ("GET", "POST", "TRACE", "CONNECT", "PROPFIND"):
                for headers in extra:
                    with self.subTest(route=route, method=method, headers=headers):
                        status, _, body = self.unchanged(
                            svc, lambda: self.owner(svc, method, route, headers=headers))
                        self.assertEqual(
                            (status, body), (403, guest.OWNER_PORT_TEXT.encode() + b"\n"))
        status, _, body = self.owner(svc, "GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(body, service.PAGE.replace(
            write_guard.TOKEN_SLOT, svc.page_token.encode()))
        self.assertEqual(self.owner(svc, "GET", "/api/whoami")[0], 404)

    def test_each_token_is_refused_on_the_other_port(self):
        self.seed()
        svc = self.start()
        picture_id = self.brief_with_picture(svc, "owner/p01", GOAL, PIXEL)
        origin = f"http://127.0.0.1:{svc.address[1]}"
        status, _, body = support.post_page(
            svc.address, "/api/looked",
            {"Origin": origin, "X-Console-Token": self.guest_token(), **JSON}, b"{}")
        self.assertEqual((status, body), (403, b"token refused\n"))
        status, _, body = support.get_page(
            svc.address, "/api/picture/" + picture_id,
            {"X-Console-Token": self.guest_token()})
        self.assertEqual((status, body), (403, b"token refused\n"))
        path = "/api/picture/" + picture_id
        status, _, body = self.guest(svc, "GET", path,
                                     headers={"X-Console-Token": self.owner_token()})
        self.assertEqual((status, body), (403, b"token refused\n"))
        status, _, body = self.guest(svc, "GET", path, headers={
            "X-Console-Token": self.guest_token(), "Origin": "http://" + TAILNET})
        self.assertEqual((status, body), (403, b"origin refused\n"))
        status, headers, body = self.guest(svc, "GET", path, headers={
            "X-Console-Token": self.guest_token(), "Origin": "https://" + TAILNET})
        self.assertEqual((status, body), (200, PIXEL))
        self.assertEqual(headers["Content-Type"], "image/png")


class ScopedReadTest(GuestCase):
    def test_a_guest_reads_only_their_projects(self):
        self.seed()
        support.sign_in(self.store, "work-zq5")
        profile = self.root / "accounts" / "profiles" / "work-zq5"
        profile.mkdir(parents=True)
        reading = Activation("/srv/p00", ("python/agent_tools/console/view.py",), "a" * 40)
        svc = self.start(profile_dirs=[profile], activation_reader=lambda roots: reading,
                         activation_seconds=3600)
        svc.poll_activation()
        svc.poll_sessions()
        p0 = self.brief_with_picture(svc, "owner/p00", "other-goal-zq7", PIXEL)
        status, _, answer = support.post_page(
            svc.address, "/api/owner-notice",
            {"Origin": f"http://127.0.0.1:{svc.address[1]}",
             "X-Console-Token": self.owner_token(), **JSON},
            json.dumps({"project_id": "owner/p00", "text": "other-notice-zq6"}).encode())
        self.assertEqual(status, 204, answer)
        p1 = self.brief_with_picture(svc, "owner/p01", "own-goal-zq8", WIDE)
        self.assertNotEqual(p0, p1)
        status, _, state = self.guest(svc, "GET", "/api/state")
        self.assertEqual(status, 200)
        connection = http.client.HTTPConnection(*svc.guest_address, timeout=5)
        self.addCleanup(connection.close)
        connection.putrequest("GET", "/api/stream", skip_host=True)
        connection.putheader("Host", TAILNET)
        connection.putheader("Tailscale-User-Login", COLLEAGUE)
        connection.endheaders()
        frame = next_frame(connection.getresponse())
        for name, text in (("state", state), ("frame", frame)):
            for marker in ("owner/p00", "/srv/p00", "other-goal-zq7", "other-notice-zq6", p0,
                           "work-zq5", COLLEAGUE, TAILNET, '"sharing"'):
                with self.subTest(read=name, marker=marker):
                    self.assertNotIn(marker.encode(), text)
            for marker in ("own-goal-zq8", p1):
                with self.subTest(read=name, marker=marker):
                    self.assertIn(marker.encode(), text)
        seen = json.loads(state)
        for member in ("activation", "spend", "digest", "registration"):
            self.assertIsNone(seen[member])
        self.assertEqual(seen["capacity"]["profiles"], [])
        mine = json.loads(self.owner(svc, "GET", "/api/state")[2])
        self.assertIsNotNone(mine["activation"])
        self.assertIn(b"work-zq5", json.dumps(mine).encode())
        headers = {"X-Console-Token": self.guest_token(), "Origin": "https://" + TAILNET}
        status, _, body = self.guest(svc, "GET", "/api/picture/" + p1, headers=headers)
        self.assertEqual((status, body), (200, WIDE))
        status, _, body = self.guest(svc, "GET", "/api/picture/" + p0, headers=headers)
        self.assertEqual((status, body), (404, b"this picture is not known\n"))


class DoorTest(GuestCase):
    def test_without_a_guest_port_there_is_no_door(self):
        support.write_registry(self.registry, support.entries(2))
        svc = support.service(self, self.store, self.registry)
        self.assertIsNone(svc.guest_address)
        self.assertIsNone(svc.guest_token)
        self.assertFalse((self.store.parent / "guest-token").exists())

    def test_the_console_takes_a_guest_port(self):
        parser = console.build_parser()
        self.assertEqual(parser.parse_args([]).guest_port, service.DEFAULT_GUEST_PORT)
        self.assertEqual(service.DEFAULT_GUEST_PORT, 27185)
        self.assertEqual(parser.parse_args(["--guest-port", "0"]).guest_port, 0)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["--guest-port", "70000"])
        self.assertEqual(raised.exception.code, 2)
        held = socket.socket()
        self.addCleanup(held.close)
        held.bind(("127.0.0.1", 0))
        held.listen()
        number = held.getsockname()[1]
        captured = io.StringIO()
        with mock.patch.object(service, "default_store", return_value=self.store), \
                mock.patch.object(service, "default_registry", return_value=self.registry), \
                contextlib.redirect_stderr(captured):
            code = console.main(["--port", "0", "--guest-port", str(number)])
        self.assertEqual(code, 1)
        lines = captured.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("console: cannot listen on 127.0.0.1:"))
        self.assertIn(str(number), lines[0])


class AccessWriteTest(GuestCase):
    """The owner's three page writes that keep the guest access list (#1237)."""

    def write(self, svc, route, body, headers=None):
        headers = {"Origin": f"http://127.0.0.1:{svc.address[1]}",
                   "X-Console-Token": self.owner_token(), **JSON} if headers is None else headers
        return support.post_page(svc.address, route, headers, json.dumps(body).encode())

    def kinds(self):
        return [(kind, json.loads(payload))
                for _, _, kind, _, payload in support.log_rows(self.store)
                if kind.startswith("sharing.")]

    def guest_state(self, svc):
        return self.guest(svc, "GET", "/api/state")

    def test_add_replace_and_remove_a_colleague_then_their_next_request(self):
        svc = self.start()
        status, _, body = self.write(svc, "/api/share-tailnet", {"tailnet": TAILNET})
        self.assertEqual((status, body), (204, b""))
        status, _, body = self.guest_state(svc)
        self.assertEqual((status, body), (403, guest.NOT_SHARED_TEXT.encode() + b"\n"))
        status, _, body = self.write(
            svc, "/api/share-colleague", {"login": COLLEAGUE, "projects": ["owner/p01"]})
        self.assertEqual((status, body), (204, b""))
        status, _, state = self.guest_state(svc)
        self.assertEqual(status, 200)
        self.assertIn(b"owner/p01", state)
        self.assertNotIn(b"owner/p00", state)
        mine = json.loads(self.owner(svc, "GET", "/api/state")[2])
        self.assertEqual(mine["sharing"], {
            "tailnet": TAILNET, "colleagues": [{"login": COLLEAGUE, "projects": ["owner/p01"]}],
            "state": "unchecked", "last_request": {
                "admitted": True, "forwarded_for": False, "host": TAILNET,
                "host_form": "exact", "hosts": 1, "login_headers": 1, "login_valid": True,
                "probe": False, "probe_login_arrived": False, "reason": None}})
        status, _, body = self.write(
            svc, "/api/share-colleague", {"login": COLLEAGUE, "projects": ["owner/p00"]})
        self.assertEqual((status, body), (204, b""))
        status, _, state = self.guest_state(svc)
        self.assertEqual(status, 200)
        self.assertIn(b"owner/p00", state)
        self.assertNotIn(b"owner/p01", state)
        status, _, body = self.write(svc, "/api/share-remove", {"login": COLLEAGUE})
        self.assertEqual((status, body), (204, b""))
        status, _, body = self.guest_state(svc)
        self.assertEqual((status, body), (403, guest.NOT_SHARED_TEXT.encode() + b"\n"))
        self.assertEqual(self.kinds(), [
            ("sharing.tailnet", {"tailnet": TAILNET}),
            ("sharing.colleague", {"login": COLLEAGUE, "projects": ["owner/p01"]}),
            ("sharing.colleague", {"login": COLLEAGUE, "projects": ["owner/p00"]}),
            ("sharing.removed", {"login": COLLEAGUE})])

    def test_an_open_guest_stream_is_readmitted_on_every_change(self):
        rows = (("removed", lambda svc: svc.remove_colleague(COLLEAGUE)),
                ("sharing off", lambda svc: svc.set_tailnet(None)),
                ("tailnet moved", lambda svc: svc.set_tailnet(OTHER_HOST)))
        for name, action in rows:
            with self.subTest(change=name), tempfile.TemporaryDirectory() as tmp:
                self.store = Path(tmp) / "state/console/events.sqlite3"
                self.registry = Path(tmp) / "state/fleet/registry.json"
                self.seed()
                svc = self.start()
                response = self.open_stream(svc)
                self.assertTrue(next_frame(response).startswith(b"event: view\ndata: "))
                action(svc)
                lines = []
                while True:
                    line = response.readline()
                    if line == b"":
                        break
                    lines.append(line)
                self.assertEqual([line for line in lines if line.startswith(b"event: view")], [])
                svc.close()
        self.store = self.root / "state/console/events.sqlite3"
        self.registry = self.root / "state/fleet/registry.json"
        self.seed()
        svc = self.start()
        response = self.open_stream(svc)
        self.assertTrue(next_frame(response).startswith(b"event: view\ndata: "))
        svc.set_colleague(COLLEAGUE, ("owner/p00",))
        frame = next_frame(response)
        self.assertIn(b"owner/p00", frame)
        self.assertNotIn(b"owner/p01", frame)
        svc.set_colleague(COLLEAGUE, ("owner/p01",))
        frame = next_frame(response)
        self.assertIn(b"owner/p01", frame)
        self.assertNotIn(b"owner/p00", frame)

    def test_bad_bodies_and_refusals_append_nothing(self):
        self.seed()
        svc = self.start()
        rows = (
            ("/api/share-tailnet", {"tailnet": "desk.example.com"}, 400, "bad tailnet"),
            ("/api/share-colleague", {"login": "no-at-sign", "projects": ["owner/p01"]},
             400, "bad colleague"),
            ("/api/share-colleague", {"login": COLLEAGUE, "projects": ["owner/p99"]},
             409, "that project is not registered"),
            ("/api/share-remove", {"login": STRANGER}, 409, "that colleague is not listed"),
            ("/api/share-remove", {}, 400, "bad removal"))
        for route, body, status, text in rows:
            with self.subTest(route=route, body=body):
                got = self.unchanged(svc, lambda: self.write(svc, route, body))
                self.assertEqual((got[0], got[2]), (status, text.encode() + b"\n"))
        valid = {"/api/share-tailnet": {"tailnet": TAILNET},
                 "/api/share-colleague": {"login": COLLEAGUE, "projects": ["owner/p01"]},
                 "/api/share-remove": {"login": COLLEAGUE}}
        origin = {"Origin": f"http://127.0.0.1:{svc.address[1]}", **JSON}
        for route, body in valid.items():
            for label, headers in (
                    ("no token", origin),
                    ("guest token", {**origin, "X-Console-Token": self.guest_token()})):
                with self.subTest(route=route, token=label):
                    got = self.unchanged(svc, lambda: self.write(svc, route, body, headers))
                    self.assertEqual((got[0], got[2]), (403, b"token refused\n"))

    def test_clearing_the_tailnet_turns_sharing_off(self):
        self.seed()
        svc = self.start()
        self.assertEqual(self.guest_state(svc)[0], 200)
        status, _, body = self.write(svc, "/api/share-tailnet", {"tailnet": None})
        self.assertEqual((status, body), (204, b""))
        status, _, body = self.guest_state(svc)
        self.assertEqual((status, body), (403, guest.SHARING_OFF_TEXT.encode() + b"\n"))
        sharing = json.loads(self.owner(svc, "GET", "/api/state")[2])["sharing"]
        self.assertEqual(sharing["state"], "off")
        self.assertEqual(sharing["colleagues"], [{"login": COLLEAGUE, "projects": ["owner/p01"]}])

    def test_adr_008_lists_the_access_list_writes(self):
        adr = (ROOT / "docs/areas/console/adr/"
               "008-only-the-page-writes-with-a-token-and-its-origin.md").read_text()
        text = " ".join(adr.split())
        for needle in ("POST /api/share-tailnet", "POST /api/share-colleague",
                       "POST /api/share-remove", "#1237", "bad colleague"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        decided = next(row for row in adr.splitlines() if row.startswith("- **Decided in:**"))
        self.assertTrue(decided.endswith("#1193, #1237"))


class ReadingServiceTest(GuestCase):
    """The owner's `sharing.last_request`: the last guest-port request's reading (#1237)."""

    def reading(self, svc):
        return json.loads(self.owner(svc, "GET", "/api/state")[2])["sharing"]["last_request"]

    def test_the_owner_state_keeps_the_last_guest_request(self):
        self.seed()
        svc = self.start()
        rows = support.log_rows(self.store)
        self.assertIsNone(self.reading(svc))
        status, _, body = self.guest(svc, "GET", "/api/state", logins=[STRANGER],
                                     headers={"X-Forwarded-For": "100.64.0.1"})
        self.assertEqual((status, body), (403, guest.NOT_SHARED_TEXT.encode() + b"\n"))
        self.assertEqual(self.reading(svc), {
            "admitted": False, "forwarded_for": True, "host": TAILNET, "host_form": "exact",
            "hosts": 1, "login_headers": 1, "login_valid": True, "probe": False,
            "probe_login_arrived": False, "reason": "not_shared"})
        self.assertNotIn(STRANGER.encode(), svc.view_bytes.lower())
        status, _, _ = self.guest(svc, "GET", "/api/whoami", headers={"X-Console-Probe": FORGED})
        self.assertEqual(status, 200)
        got = self.reading(svc)
        self.assertTrue(got["admitted"] and got["probe"])
        self.assertIsNone(got["reason"])
        self.assertFalse(got["probe_login_arrived"])
        status, _, body = self.guest(svc, "GET", "/", host=TAILNET + ":443")
        self.assertEqual((status, body), (403, guest.HOST_TEXT.encode() + b"\n"))
        got = self.reading(svc)
        self.assertEqual((got["host_form"], got["reason"], got["host"]),
                         ("with_port", "host", TAILNET + ":443"))
        version = svc.version
        self.guest(svc, "GET", "/", host=TAILNET + ":443")
        self.assertEqual(svc.version, version)
        body = self.guest(svc, "GET", "/api/state")[2]
        frame = next_frame(self.open_stream(svc))
        for seen in (body, frame):
            for member in (b"last_request", b"host_form", b'"sharing"'):
                self.assertNotIn(member, seen)
        self.assertEqual(support.log_rows(self.store), rows)

    def test_a_new_reading_sends_no_guest_stream_frame(self):
        self.seed()
        svc = self.start()
        returned = queue.Queue()
        original = svc.wait_for_guest_change

        def spy(*args):
            result = original(*args)
            returned.put(result)
            return result

        svc.wait_for_guest_change = spy
        response = self.open_stream(svc)
        next_frame(response)
        self.assertIsNotNone(returned.get(timeout=5))
        kept = svc.guest_view_bytes(COLLEAGUE)
        version = svc.version
        self.assertEqual(self.guest(svc, "GET", "/api/state", logins=[STRANGER])[0], 403)
        woke = returned.get(timeout=5)
        self.assertIsNotNone(woke)
        self.assertGreater(woke[0], version)
        self.assertEqual(woke[2], kept)
        svc.set_colleague(COLLEAGUE, ("owner/p00",))
        frame = next_frame(response)
        self.assertIn(b"owner/p00", frame)
        self.assertNotIn(b"owner/p01", frame)

    def test_a_reading_keeps_the_guest_views(self):
        now = [time.time()]
        self.seed()
        svc = self.start(clock=lambda: now[0])
        svc.state_goal("owner/p01", "own-goal-zq8")
        before = svc.guest_view_bytes(COLLEAGUE)
        self.assertIn(b"own-goal-zq8", before)
        now[0] += 3 * 86400
        self.assertEqual(self.guest(svc, "GET", "/api/state", logins=[STRANGER])[0], 403)
        self.assertEqual(self.reading(svc)["reason"], "not_shared")
        self.assertEqual(svc.guest_view_bytes(COLLEAGUE), before)
        svc.set_colleague(COLLEAGUE, ("owner/p01",))
        self.assertNotEqual(svc.guest_view_bytes(COLLEAGUE), before)

    def test_every_parsed_request_is_read(self):
        self.seed()
        svc = self.start()
        rows = support.log_rows(self.store)
        table = [
            (("TRACE", "/api/state", {"logins": [STRANGER, STRANGER]}), 403, guest.NOT_SHARED_TEXT,
             {"login_headers": 2, "reason": "not_shared", "admitted": False}),
            (("POST", "/api/looked", {"host": OTHER_HOST}), 403, guest.HOST_TEXT,
             {"host_form": "other", "host": OTHER_HOST}),
            (("GET", "/api/whoami", {"logins": []}), 200, None,
             {"login_headers": 0, "reason": "not_shared"}),
            (("DELETE", "/api/state", {}), 405, None, {"admitted": True, "reason": None}),
            (("PROPFIND", "/api/state", {"logins": [STRANGER]}), 403, guest.NOT_SHARED_TEXT,
             {"login_headers": 1}),
        ]
        for (method, path, kwargs), status, text, expected in table:
            with self.subTest(method=method, path=path):
                got, headers, body = self.guest(svc, method, path, **kwargs)
                self.assertEqual(got, status)
                if text is not None:
                    self.assertEqual(body, text.encode() + b"\n")
                self.assertEqual(headers.get("Connection"), "close")
                reading = self.reading(svc)
                for name, value in expected.items():
                    self.assertEqual(reading[name], value, name)
                self.assertEqual(support.log_rows(self.store), rows)


class ConnectionTest(GuestCase):
    def exchange(self, svc, data):
        received = b""
        with socket.create_connection(svc.guest_address, timeout=5) as sock:
            sock.sendall(data)
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    return received
                received += chunk

    def test_a_second_request_on_one_connection_is_never_answered(self):
        self.seed()
        svc = self.start()
        inner = (b"GET /api/state HTTP/1.1\r\nHost: " + TAILNET.encode()
                 + b"\r\nTailscale-User-Login: " + COLLEAGUE.encode() + b"\r\n\r\n")

        def head(path, login=True, body=b""):
            lines = [f"GET {path} HTTP/1.1", f"Host: {TAILNET}"]
            if login:
                lines.append(f"Tailscale-User-Login: {COLLEAGUE}")
            if body:
                lines.append(f"Content-Length: {len(body)}")
            return "\r\n".join(lines).encode() + b"\r\n\r\n" + body

        rows = (
            ("a", head("/api/whoami", login=False, body=inner), 200),
            ("b", head("/api/state", body=inner), 200),
            ("c", head("/nowhere", body=inner), 404),
            ("d", head("/api/whoami", login=False) + inner, 200),
        )
        for name, data, status in rows:
            with self.subTest(row=name):
                received = self.exchange(svc, data)
                self.assertEqual(received.count(b"HTTP/1.1 "), 1)
                self.assertTrue(received.startswith(f"HTTP/1.1 {status} ".encode()))
                response_head = received.split(b"\r\n\r\n", 1)[0]
                self.assertEqual(response_head.count(b"Connection: close"), 1)
                if name != "b":
                    self.assertNotIn(b"owner/p01", received)


class ServeStatusTest(GuestCase):
    def test_the_sharing_state_follows_the_serve_status(self):
        self.seed()
        self.reading = None
        svc = self.start(serve_reader=lambda: self.reading, serve_seconds=3600)

        def proxy(port):
            return {"Web": {f"{TAILNET}:443": {"Handlers": {
                "/": {"Proxy": f"http://127.0.0.1:{port}"}}}}}

        rows = ((None, "unchecked"), ({}, "not_proxying"),
                (proxy(svc.guest_address[1]), "serving"),
                (proxy(svc.address[1]), "not_proxying"))
        for reading, state in rows:
            with self.subTest(state=state, reading=reading):
                self.reading = reading
                svc.poll_serve()
                self.assertEqual(
                    json.loads(self.owner(svc, "GET", "/api/state")[2])["sharing"]["state"], state)
                self.assertNotIn(
                    "sharing", json.loads(self.guest(svc, "GET", "/api/state")[2]))
        self.reading = proxy(svc.guest_address[1])
        svc.poll_serve()
        svc.set_tailnet(None)
        self.assertEqual(
            json.loads(self.owner(svc, "GET", "/api/state")[2])["sharing"]["state"], "off")

    def test_a_failing_reader_reads_unchecked(self):
        self.seed()

        def reader():
            raise RuntimeError("boom")

        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            svc = self.start(serve_reader=reader, serve_seconds=3600)
            svc.poll_serve()
        lines = captured.getvalue().splitlines()
        self.assertTrue(lines)
        self.assertEqual(set(lines), {"console: serve_status_failed RuntimeError: boom"})
        self.assertEqual(
            json.loads(self.owner(svc, "GET", "/api/state")[2])["sharing"]["state"], "unchecked")

    def test_the_serve_reader_runs_the_status_command(self):
        calls = []

        def run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, stdout='{"Web": {}}', stderr="")

        self.assertEqual(guest.serve_reader("/x/tailscale.exe", run=run)(), {"Web": {}})
        args, kwargs = calls[0]
        self.assertEqual(args, ["/x/tailscale.exe", "serve", "status", "--json"])
        self.assertEqual(kwargs["timeout"], 15.0)
        self.assertEqual(guest.SERVE_TIMEOUT_SECONDS, 15.0)
        self.assertNotIn("shell", kwargs)

        def failing(error):
            def run(args, **kwargs):
                raise error
            return run

        rows = (
            ("a nonzero exit", lambda args, **kw: subprocess.CompletedProcess(
                args, 1, stdout='{"Web": {}}', stderr="")),
            ("unparsable output", lambda args, **kw: subprocess.CompletedProcess(
                args, 0, stdout="not json", stderr="")),
            ("an OSError", failing(OSError("no such file"))),
            ("a timeout", failing(subprocess.TimeoutExpired("x", 15))),
        )
        for name, row in rows:
            with self.subTest(row=name):
                self.assertIsNone(guest.serve_reader("/x/tailscale.exe", run=row)())

    def test_the_console_takes_a_tailscale_path(self):
        parser = console.build_parser()
        self.assertIsNone(parser.parse_args([]).tailscale)
        self.assertEqual(
            parser.parse_args(["--tailscale", "/x/tailscale.exe"]).tailscale, "/x/tailscale.exe")
        self.addCleanup(signal.signal, signal.SIGTERM, signal.getsignal(signal.SIGTERM))
        self.addCleanup(signal.signal, signal.SIGINT, signal.getsignal(signal.SIGINT))
        for argv, wanted in ((["--tailscale", "/x/tailscale.exe"], True), ([], False)):
            with self.subTest(argv=argv), \
                    mock.patch.object(service, "default_store", return_value=self.store), \
                    mock.patch.object(service, "default_registry", return_value=self.registry), \
                    mock.patch.object(service, "ConsoleService") as made, \
                    contextlib.redirect_stdout(io.StringIO()):
                made.return_value.start.side_effect = lambda: os.kill(os.getpid(), signal.SIGTERM)
                self.assertEqual(console.main(argv), 0)
                kwargs = made.call_args.kwargs
                self.assertEqual(kwargs["guest_port"], 27185)
                if wanted:
                    self.assertTrue(callable(kwargs["serve_reader"]))
                else:
                    self.assertIsNone(kwargs["serve_reader"])


class HeldCheckServiceTest(GuestCase):
    def test_the_held_check_reads_the_running_service(self):
        self.seed()
        svc = self.start()

        def check():
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = serve_probe_check.main(["--port", str(svc.address[1])])
            self.assertNotIn("@", out.getvalue())
            return code, json.loads(out.getvalue())["status"]

        self.assertEqual(check(), (75, "no_request"))
        self.guest(svc, "GET", "/api/whoami",
                   headers={"X-Forwarded-For": "100.64.0.1", "X-Console-Probe": FORGED})
        self.assertEqual(check(), (0, "met"))
        svc.set_tailnet(OTHER_HOST)
        self.assertEqual(check(), (75, "stale"))
        self.guest(svc, "GET", "/api/whoami", host=OTHER_HOST, logins=[FORGED],
                   headers={"X-Forwarded-For": "100.64.0.1",
                            "X-Console-Probe": "other-probe@example.invalid"})
        self.assertEqual(check(), (1, "not_met"))


if __name__ == "__main__":
    unittest.main()
