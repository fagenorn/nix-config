"""The console capacity-reading verify check (#860): a console shows a fresh reading for an account.

Run: just agent-workflow-tests
"""
import json
import socket
import subprocess
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-capacity-reading"


def serve(test, body, status=200):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    test.addCleanup(thread.join, 5)
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return f"http://127.0.0.1:{server.server_address[1]}/api/state"


def ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def view(*rows):
    return {"capacity": {"profiles": [{"profile": name, "read_at": at} for name, at in rows]}}


class CapacityCheckTest(unittest.TestCase):
    def run_check(self, *args):
        done = subprocess.run([ROOT / WRAPPER, *args], cwd=ROOT, capture_output=True, text=True,
                              timeout=60)
        return done.returncode, done.stdout

    def test_a_fresh_reading_is_met(self):
        url = serve(self, view(("home", ago(5000)), ("work", ago(60))))
        code, out = self.run_check("--url", url)
        document = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(document["status"], "met")
        self.assertEqual(document["profile"], "work")
        self.assertIn(document["age_seconds"], range(59, 70))

    def test_a_stale_or_missing_reading_is_not_met(self):
        for rows in ([("work", ago(601))], [("work", None)], []):
            with self.subTest(rows=rows):
                code, out = self.run_check("--url", serve(self, view(*rows)))
                document = json.loads(out)
                self.assertEqual(code, 1)
                self.assertEqual(document["status"], "not_met")
                self.assertEqual(document["profiles"], [name for name, _ in rows])

    def test_the_age_limit_is_an_argument(self):
        url = serve(self, view(("work", ago(601))))
        code, out = self.run_check("--url", url, "--max-age", "700")
        self.assertEqual((code, json.loads(out)["status"]), (0, "met"))

    def test_a_console_that_is_down_or_old_is_not_yet(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed = probe.getsockname()[1]
        cases = [(f"http://127.0.0.1:{closed}/api/state", "not_running"),
                 (serve(self, {"statement": {}}), "not_deployed"),
                 (serve(self, b"not json"), "not_deployed"),
                 (serve(self, view(), status=500), "not_running")]
        for url, status in cases:
            with self.subTest(status=status, url=url):
                code, out = self.run_check("--url", url)
                self.assertEqual((code, json.loads(out)), (75, {"status": status}))

    def test_every_profile_fresh_is_met(self):
        url = serve(self, view(("work", ago(60)), ("spare", ago(800))))
        code, out = self.run_check("--url", url, "--every", "--max-age", "900")
        document = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(document["status"], "met")
        self.assertEqual(document["profiles"], 2)
        self.assertIn(document["oldest_age_seconds"], range(799, 810))

    def test_a_profile_without_a_fresh_reading_is_not_yet_with_every(self):
        cases = [([("work", ago(60)), ("spare", None), ("old", ago(1000))], ["spare", "old"]),
                 ([], [])]
        for rows, names in cases:
            with self.subTest(rows=rows):
                code, out = self.run_check("--url", serve(self, view(*rows)), "--every",
                                           "--max-age", "900")
                self.assertEqual((code, json.loads(out)),
                                 (75, {"status": "pending", "profiles": names}))

    def test_without_every_one_fresh_profile_still_meets(self):
        url = serve(self, view(("work", ago(60)), ("spare", None)))
        code, out = self.run_check("--url", url)
        document = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(document["status"], "met")
        self.assertEqual(document["profile"], "work")

    def test_the_wrapper_is_committed_executable(self):
        listed = subprocess.run(["git", "ls-files", "-s", WRAPPER], cwd=ROOT,
                                capture_output=True, text=True, check=True).stdout
        self.assertTrue(listed.startswith("100755"), listed)

    def test_an_off_loopback_url_is_refused(self):
        for url in ("http://example.test/api/state", "https://127.0.0.1/api/state"):
            with self.subTest(url=url):
                self.assertEqual(self.run_check("--url", url)[0], 2)

    def test_a_bad_max_age_is_refused(self):
        for value in ("0", "-5", "x"):
            with self.subTest(value=value):
                self.assertEqual(self.run_check("--max-age", value)[0], 2)


if __name__ == "__main__":
    unittest.main()
