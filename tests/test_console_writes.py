"""The console's page writes (#861): the per-install token, the console's origin, the look route.

Run: just agent-workflow-tests
"""
import contextlib
import io
import re
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import console, digest, service, write_guard

from . import console_test_support as support

LOOK = "/api/looked"


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.store = root / "state/console/events.sqlite3"
        self.registry = root / "state/fleet/registry.json"
        self.token_file = self.store.parent / "page-token"

    def start(self, **kwargs):
        return support.service(self, self.store, self.registry, **kwargs)

    def token(self):
        return self.token_file.read_text().strip()

    def own(self, svc, **headers):
        return {"Origin": f"http://127.0.0.1:{svc.address[1]}",
                "X-Console-Token": self.token(), **headers}

    def assert_unchanged(self, svc, action):
        rows, version = support.log_rows(self.store), svc.version
        result = action()
        self.assertEqual(support.log_rows(self.store), rows)
        self.assertEqual(svc.version, version)
        return result

    def assert_refused(self, svc, headers, status, text, **kwargs):
        got = self.assert_unchanged(
            svc, lambda: support.post_page(svc.address, LOOK, headers, **kwargs))
        self.assertEqual((got[0], got[2]), (status, text + b"\n"))
        return got


class WriteRouteTest(Case):
    def test_a_look_with_the_token_from_the_page_origin_is_recorded(self):
        svc = self.start()
        before = support.log_rows(self.store)
        status, headers, body = support.post_page(svc.address, LOOK, self.own(svc))
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(headers["Cache-Control"], "no-store")
        rows = support.log_rows(self.store)
        self.assertEqual(rows[:len(before)], before)
        self.assertEqual(len(rows), len(before) + 1)
        self.assertEqual(rows[-1][2:], (digest.LOOKED, None, "{}"))

    def test_a_write_without_the_token_is_refused_and_changes_nothing(self):
        svc = self.start()
        _, headers, _ = self.assert_refused(
            svc, {"Origin": f"http://127.0.0.1:{svc.address[1]}"}, 403, b"token refused")
        self.assertEqual(headers["Content-Type"], "text/plain")
        self.assertEqual(headers["Connection"], "close")

    def test_a_write_with_a_wrong_token_is_refused_and_changes_nothing(self):
        svc = self.start()
        self.assert_refused(
            svc, self.own(svc, **{"X-Console-Token": "A" * 43}), 403, b"token refused")

    def test_a_write_from_another_origin_is_refused_and_changes_nothing(self):
        svc = self.start()
        port = svc.address[1]
        for origin in ("http://example.test", "null", f"http://localhost:{port}",
                       f"https://127.0.0.1:{port}"):
            with self.subTest(origin=origin):
                self.assert_refused(svc, self.own(svc, Origin=origin), 403, b"origin refused")

    def test_a_write_from_a_terminal_without_an_origin_is_refused_and_changes_nothing(self):
        svc = self.start()
        self.assert_refused(svc, {}, 403, b"origin refused")
        self.assert_refused(
            svc, {"X-Console-Token": self.token()}, 403, b"origin refused")

    def test_two_origins_or_two_tokens_are_refused(self):
        svc = self.start()
        own = self.own(svc)
        self.assert_refused(
            svc, {**own, "Origin": [own["Origin"], own["Origin"]]}, 403, b"origin refused")
        self.assert_refused(
            svc, {**own, "X-Console-Token": [own["X-Console-Token"]] * 2}, 403, b"token refused")

    def test_a_write_with_a_body_is_refused(self):
        svc = self.start()
        self.assert_refused(svc, self.own(svc), 400, b"no body", body=b"{}")
        self.assert_refused(
            svc, self.own(svc, **{"Transfer-Encoding": "chunked"}), 400, b"no body")

    def test_a_foreign_host_is_refused_before_the_guard(self):
        svc = self.start()
        status, _, body = support.post_page(
            svc.address, LOOK, self.own(svc), host="evil.test")
        self.assertEqual((status, body), (403, b"loopback only\n"))

    def test_every_page_write_route_is_guarded(self):
        svc = self.start()
        self.assertEqual(service.PAGE_WRITES, {"/api/looked"})
        for path in service.PAGE_WRITES:
            with self.subTest(path=path):
                status, _, body = support.post_page(
                    svc.address, path,
                    {"Origin": f"http://127.0.0.1:{svc.address[1]}"})
                self.assertEqual((status, body), (403, b"token refused\n"))

    def test_other_methods_on_the_look_route_are_refused(self):
        svc = self.start()
        for method in ("GET", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            with self.subTest(method=method):
                status, headers, _ = support.request(svc.address, method, LOOK)
                self.assertEqual(status, 405)
                self.assertEqual(headers["Allow"], "POST")


class TokenTest(Case):
    def test_the_token_is_created_once_and_kept(self):
        first = self.start()
        mode = stat.S_IMODE(self.token_file.stat().st_mode)
        self.assertEqual(mode, 0o600)
        self.assertRegex(self.token_file.read_text(), r"^[A-Za-z0-9_-]{43}\n$")
        token = first.page_token
        first.close()
        second = self.start()
        self.assertEqual(second.page_token, token)

    def test_the_page_carries_the_token_and_nothing_else_does(self):
        svc = self.start()
        token = svc.page_token.encode()
        _, _, page = support.request(svc.address, "GET", "/")
        self.assertIn(token, page)
        self.assertNotIn(b"__CONSOLE_TOKEN__", page)
        support.post_page(svc.address, LOOK, self.own(svc))
        self.assertNotIn(token, support.request(svc.address, "GET", "/api/state")[2])
        self.assertNotIn(token, svc.view_bytes)
        self.assertFalse([row for row in support.log_rows(self.store)
                          if token.decode() in " ".join(map(str, row))])

    def test_a_malformed_token_file_stops_the_service(self):
        self.token_file.parent.mkdir(parents=True)
        self.token_file.write_text("short\n")
        with self.assertRaises(write_guard.TokenError):
            service.ConsoleService(self.store, self.registry, port=0)
        self.assertFalse(self.store.exists())

    def test_console_main_reports_an_unusable_token(self):
        self.token_file.parent.mkdir(parents=True)
        self.token_file.write_text("short\n")
        err = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(service, "default_store", return_value=self.store))
            stack.enter_context(
                mock.patch.object(service, "default_registry", return_value=self.registry))
            stack.enter_context(mock.patch.object(
                service.ConsoleService, "start", side_effect=AssertionError("started")))
            stack.enter_context(contextlib.redirect_stderr(err))
            code = console.main(["--port", "0"])
        self.assertEqual(code, 1)
        self.assertTrue(err.getvalue().startswith("console: page token unusable: "))


class GuardTest(unittest.TestCase):
    def test_the_refusal_table(self):
        token = "t" * 43
        origin, no, bad = (403, "origin refused"), None, (403, "token refused")
        table = [
            ("127.0.0.1:9", ["http://127.0.0.1:9"], [token], no),
            ("localhost:9", ["http://localhost:9"], [token], no),
            ("127.0.0.1:9", [], [token], origin),
            ("127.0.0.1:9", ["http://example.test"], [token], origin),
            ("127.0.0.1:9", ["http://127.0.0.1:9"] * 2, [token], origin),
            ("127.0.0.1:9", ["http://127.0.0.1:9"], [], bad),
            ("127.0.0.1:9", ["http://127.0.0.1:9"], ["u" * 43], bad),
            ("127.0.0.1:9", ["http://127.0.0.1:9"], [token, token], bad),
        ]
        for host, origins, tokens, expected in table:
            with self.subTest(origins=origins, tokens=tokens):
                self.assertEqual(write_guard.refusal(host, origins, tokens, token), expected)


if __name__ == "__main__":
    unittest.main()
