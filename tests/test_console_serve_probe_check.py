"""The held check that reads the guest port's last request from the owner's state (#1237, AC8).

Run: just agent-workflow-tests
"""
import contextlib
import http.server
import io
import json
import re
import socket
import threading
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock

from agent_tools.console import guest, serve_probe_check
from agent_tools.console.serve_probe_check import FORGED, default_read_state
from tests.test_verify_checks import committed_mode
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-guest-door"
TAILNET = "desk.invented-tailnet.ts.net"
OTHER_HOST = "other.invented-tailnet.ts.net"
COLLEAGUE = "colleague@example.invalid"
OTHER_PROBE = "other-probe@example.invalid"
GOOD = {"admitted": False, "forwarded_for": True, "host": TAILNET, "host_form": "exact",
        "hosts": 1, "login_headers": 1, "probe": True, "probe_login_arrived": False,
        "reason": "not_shared"}


def state_of(reading):
    return {"sharing": {"tailnet": TAILNET, "last_request": reading}}


def run_check(state):
    """Run `main` on a stubbed state with the network closed; (exit code, printed JSON, raw text)."""
    out = io.StringIO()
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network")), \
            contextlib.redirect_stdout(out):
        code = serve_probe_check.main([], read_state=lambda port: state)
    return code, json.loads(out.getvalue()), out.getvalue()


class HeldCheckTest(unittest.TestCase):
    def test_a_forged_login_that_did_not_arrive_is_met(self):
        code, printed, text = run_check(state_of(GOOD))
        self.assertEqual(code, 0)
        self.assertEqual(printed, {"admitted": False, "forwarded_for": True, "host_form": "exact",
                                   "login_headers": 1, "probe": True,
                                   "probe_login_arrived": False, "reason": "not_shared",
                                   "status": "met"})
        self.assertNotIn(TAILNET, text.lower())

    def test_the_rules_in_order(self):
        def reading(**change):
            return {**GOOD, **change}

        without_probe = {k: v for k, v in GOOD.items() if k != "probe"}
        rows = [
            (None, 75, "not_running"),
            ([], 75, "not_running"),
            ({"sharing": {"tailnet": None, "last_request": GOOD}}, 75, "sharing_off"),
            ({}, 75, "sharing_off"),
            (state_of(None), 75, "no_request"),
            ({"sharing": {"tailnet": TAILNET}}, 75, "no_request"),
            (state_of("x"), 1, "bad_reading"),
            (state_of(without_probe), 1, "bad_reading"),
            (state_of(reading(login="x")), 1, "bad_reading"),
            (state_of(reading(login_headers=True)), 1, "bad_reading"),
            (state_of(reading(host_form="sideways")), 1, "bad_reading"),
            (state_of(reading(reason="because")), 1, "bad_reading"),
            (state_of(reading(forwarded_for=False)), 75, "not_through_serve"),
            (state_of(reading(host_form="with_port", host=TAILNET + ":443", reason="host")),
             1, "not_met"),
            (state_of(reading(host_form="other")), 1, "not_met"),
            (state_of(reading(host_form="none", hosts=0, host=None)), 1, "not_met"),
            (state_of(reading(login_headers=2)), 1, "not_met"),
            (state_of(reading(login_headers=0)), 1, "not_met"),
            (state_of(reading(probe=False)), 75, "no_probe"),
            (state_of(reading(probe_login_arrived=True)), 1, "not_met"),
            (state_of(reading(probe=False, probe_login_arrived=True)), 1, "not_met"),
            (state_of(reading(forwarded_for=False, host_form="with_port")),
             75, "not_through_serve"),
            (state_of(reading(login_headers=2, probe=False)), 1, "not_met"),
            (state_of(reading(host=None)), 1, "bad_reading"),
            ({"sharing": {"tailnet": OTHER_HOST, "last_request": GOOD}}, 75, "stale"),
            ({"sharing": {"tailnet": OTHER_HOST,
                          "last_request": reading(host_form="with_port", host=TAILNET + ":443")}},
             75, "stale"),
            ({"sharing": {"tailnet": TAILNET.upper(), "last_request": GOOD}}, 0, "met"),
        ]
        for state, want_code, want_status in rows:
            with self.subTest(state=state):
                code, printed, text = run_check(state)
                self.assertEqual((code, printed["status"]), (want_code, want_status))
                self.assertNotIn(TAILNET, text.lower())
                self.assertNotIn("@", text)

    def test_a_bad_argument_is_2(self):
        for argv in (["--port", "x"], ["--other"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    serve_probe_check.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_the_reading_feeds_the_check(self):
        access = guest.Access(TAILNET, MappingProxyType({COLLEAGUE: frozenset({"owner/p01"})}))
        rows = [([TAILNET], [COLLEAGUE], [FORGED], 0, "met"),
                ([TAILNET], [FORGED], [OTHER_PROBE], 1, "not_met"),
                ([TAILNET], [FORGED], [FORGED], 1, "not_met"),
                ([TAILNET], [COLLEAGUE], [OTHER_PROBE], 75, "no_probe"),
                ([TAILNET + ":443"], [COLLEAGUE], [FORGED], 1, "not_met")]
        for hosts, logins, probes, want_code, want_status in rows:
            with self.subTest(hosts=hosts, logins=logins, probes=probes):
                reading = guest.reading(access, hosts, logins, ["100.64.0.1"], probes)
                code, printed, _ = run_check(state_of(reading))
                self.assertEqual((code, printed["status"]), (want_code, want_status))


class DefaultReaderTest(unittest.TestCase):
    def serve(self, body):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == "/api/state" else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join()

        self.addCleanup(stop)
        return server.server_address[1]

    def test_the_default_reader_reads_loopback_state(self):
        self.assertEqual(default_read_state(self.serve(json.dumps(state_of(GOOD)).encode())),
                         state_of(GOOD))
        self.assertIsNone(default_read_state(self.serve(b"not json")))
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        self.assertIsNone(default_read_state(free))


class WrapperTest(unittest.TestCase):
    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual(committed_mode(WRAPPER), "100755")
        lines = [line for line in (ROOT / WRAPPER).read_text().splitlines() if line.strip()]
        self.assertEqual(lines[-1],
                         'PYTHONPATH=python exec python3 -m agent_tools.console.serve_probe_check "$@"')

    def test_adr_066_records_the_strict_rule_and_the_held_check(self):
        (path,) = (ROOT / "docs/areas/console/adr").glob("066-*.md")
        text = re.sub(r"\s+", " ", path.read_text())
        for needle in ("- **Decided in:** #1235, #1237", "refuses connections from its own machine",
                       "with no port form", "never a login value",
                       "home/common/verify-pending/checks/console-guest-door", "expiry 30 days",
                       "so that refusal stays as written"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertNotIn("confirmed by a read-only probe through Serve in a later slice", text)


if __name__ == "__main__":
    unittest.main()
