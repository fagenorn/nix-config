"""The probe that a client-sent login header does not pass Serve as sent (#1237, AC6).

Run: just agent-workflow-tests
"""
import contextlib
import http.server
import io
import json
import socket
import threading
import unittest

from agent_tools.console import serve_probe_check
from agent_tools.console.serve_probe_check import FORGED, default_fetch
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

TAILNET = "desk.invented-tailnet.ts.net"
STATE = {"sharing": {"tailnet": TAILNET}}
GOOD = {"host": TAILNET, "hosts": 1, "login_headers": 1, "forwarded_for": True,
        "probe_login_arrived": False}


def run_check(state, answer):
    """Run `main` with the stubs; returns (exit code, the printed JSON line, the fetch calls)."""
    calls = []

    def fetch(url, headers):
        calls.append((url, dict(headers)))
        return answer

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = serve_probe_check.main([], read_state=lambda port: state, fetch=fetch)
    return code, json.loads(out.getvalue()), calls, out.getvalue()


def served(body):
    return 200, json.dumps(body).encode()


class ServeProbeTest(unittest.TestCase):
    def test_a_replaced_login_is_met(self):
        code, printed, calls, text = run_check(STATE, served(GOOD))
        self.assertEqual(code, 0)
        self.assertEqual(printed, {"forwarded_for": True, "host_form": "exact", "login_headers": 1,
                                   "probe_login_arrived": False, "status": "met"})
        self.assertEqual(calls, [("https://desk.invented-tailnet.ts.net/api/whoami",
                                  {"Tailscale-User-Login": FORGED, "X-Console-Probe": FORGED})])
        self.assertNotIn(TAILNET, text)

    def test_the_host_form_and_the_login_rule_judge_the_answer(self):
        rows = [({"host": TAILNET.upper()}, 0, "met", "exact"),
                ({"host": TAILNET + ":443"}, 0, "met", "with_port"),
                ({"host": "127.0.0.1:27185"}, 1, "not_met", "other"),
                ({"host": None}, 1, "not_met", "other"),
                ({"probe_login_arrived": True}, 1, "not_met", "exact"),
                ({"login_headers": 2}, 1, "not_met", "exact"),
                ({"login_headers": 0}, 1, "not_met", "exact")]
        for change, want_code, want_status, want_form in rows:
            with self.subTest(change=change):
                code, printed, _, text = run_check(STATE, served({**GOOD, **change}))
                self.assertEqual((code, printed["status"], printed["host_form"]),
                                 (want_code, want_status, want_form))
                self.assertNotIn(TAILNET, text.lower())

    def test_a_bad_answer_is_1(self):
        without = {k: v for k, v in GOOD.items() if k != "login_headers"}
        rows = [((403, b"Sharing is off on this console.\n"),
                 {"http_status": 403, "status": "bad_answer"}),
                ((200, b"[]"), None), ((200, b"not json"), None), (served(without), None),
                (served({**GOOD, "login_headers": "1"}), None)]
        for answer, want in rows:
            with self.subTest(answer=answer):
                code, printed, _, _ = run_check(STATE, answer)
                self.assertEqual(code, 1)
                self.assertEqual(printed["status"], "bad_answer")
                if want is not None:
                    self.assertEqual(printed, want)

    def test_nothing_to_probe_yet_is_75(self):
        rows = [(None, served(GOOD), "not_running"), ([], served(GOOD), "not_running"),
                ({"sharing": {"tailnet": None}}, served(GOOD), "sharing_off"),
                ({}, served(GOOD), "sharing_off"), (STATE, None, "unreachable")]
        for state, answer, want in rows:
            with self.subTest(state=state, answer=answer):
                code, printed, _, _ = run_check(state, answer)
                self.assertEqual((code, printed), (75, {"status": want}))

    def test_a_bad_argument_is_2(self):
        for argv in (["--port", "x"], ["--other"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    serve_probe_check.main(argv)
                self.assertEqual(caught.exception.code, 2)


class DefaultFetchTest(unittest.TestCase):
    def setUp(self):
        seen = self.seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get("X-Console-Probe"))
                status, body = (403, b"refused\n") if self.path == "/refused" else (200, b"{}")
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join()

        self.addCleanup(stop)

    def test_an_http_refusal_keeps_its_status(self):
        base = f"http://127.0.0.1:{self.port}"
        self.assertEqual(default_fetch(base + "/refused", {"X-Console-Probe": FORGED}, timeout=5),
                         (403, b"refused\n"))
        self.assertEqual(default_fetch(base + "/ok", {"X-Console-Probe": FORGED}, timeout=5),
                         (200, b"{}"))
        self.assertEqual(self.seen[-1], FORGED)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        self.assertIsNone(default_fetch(f"http://127.0.0.1:{free}/ok", {}, timeout=5))

    def test_main_reads_a_real_refusal_as_bad_answer(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = serve_probe_check.main(
                [], read_state=lambda port: STATE,
                fetch=lambda url, headers: default_fetch(
                    f"http://127.0.0.1:{self.port}/refused", headers, timeout=5))
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue()), {"http_status": 403, "status": "bad_answer"})


if __name__ == "__main__":
    unittest.main()
