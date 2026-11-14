"""The console's sign-in routes and runs (#1026): the three page writes, the rows, the read at once.

Run: just agent-workflow-tests
"""
import contextlib
import http.client
import io
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import probe, service, signin, signin_run

from . import console_test_support as support
from .test_console_signin_run import CODE, FAKE, LINK, LINUX, until
from .test_console_stream import next_frame, open_stream

SIGNIN = "/api/signin"
CODE_PATH = "/api/signin-code"
CANCEL = "/api/signin-cancel"
NOW = 1794000000
BODIES = {SIGNIN: {"profile": "work"}, CODE_PATH: {"profile": "work", "code": CODE},
          CANCEL: {"profile": "work"}}


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "state/console/events.sqlite3"
        self.registry = self.root / "state/fleet/registry.json"
        self.token_file = self.store.parent / "page-token"
        self.accounts = self.root / "accounts"
        self.spare = support.profile_dir(self.store, "spare")
        self.work = support.profile_dir(self.store, "work")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        script = bin_dir / "claude-account"
        script.write_text(FAKE % {"python": sys.executable})
        script.chmod(0o755)
        self.record = self.root / "record.jsonl"
        self.environ = {"HOME": str(self.root), "PATH": f"{bin_dir}:/usr/bin:/bin",
                        "FAKE_RECORD": str(self.record), "FAKE_MODE": "code", "FAKE_LINK": LINK}
        self.now = [NOW]
        self.mono = [1000.0]
        self.reads = []
        self.script = []
        self.entered = threading.Event()
        self.answers = {"spare": signin.Status("signed_out", None),
                        "work": signin.Status("signed_out", None)}
        support.write_registry(self.registry, [])

    def read(self, one):
        self.reads.append(one.profile)
        if self.script:
            answer, gate = self.script.pop(0)
            if gate is not None:
                self.entered.set()
                gate.wait(10)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return self.answers[one.profile]

    def begin(self, runs=True, link_wait=5, **extra):
        factory = None
        if runs:
            def factory(on_end):
                return signin_run.SignIns(on_end=on_end, environ=self.environ,
                                          clock=lambda: self.mono[0], link_wait=link_wait)
        self.svc = support.service(
            self, self.store, self.registry, profile_dirs=[self.spare, self.work],
            clock=lambda: self.now[0], session_poll_seconds=3600, probe_tick_seconds=3600,
            probe_dispatch=lambda job: job(), signin_reader=self.read, signin_runs=factory,
            **extra)
        self.now[0] += 30
        self.svc.probe_round()
        return self.svc

    def own(self, **headers):
        return {"Origin": f"http://127.0.0.1:{self.svc.address[1]}",
                "X-Console-Token": self.token_file.read_text().strip(), **headers}

    def post(self, path, body=None, headers=None, raw=None):
        payload = json.dumps(BODIES[path] if body is None else body).encode() if raw is None else raw
        sent = self.own(**{"Content-Type": "application/json"}) if headers is None else headers
        return support.post_page(self.svc.address, path, sent, payload)

    def rows(self, kind):
        return [(row[0], json.loads(row[4])) for row in support.log_rows(self.store)
                if row[2] == kind]

    def acted_rows(self):
        return self.rows("signin.acted")

    def ended_rows(self):
        return self.rows("signin.ended")

    def reading_rows(self, profile):
        return [payload for _, payload in self.rows("signin.reading")
                if payload["profile"] == profile]

    def view(self):
        return json.loads(self.svc.view_bytes)

    def open_keys(self):
        return [item["key"] for item in self.view()["inbox"]["open"]]

    def item(self, key):
        return next(item for item in self.view()["inbox"]["open"] if item["key"] == key)

    def wait_ended(self, count=1):
        def settled():
            states = [run["state"] for run in self.view()["signin_runs"].values()]
            return len(self.ended_rows()) >= count and "running" not in states
        until(self, settled)
        return self.ended_rows()

    def invocations(self):
        if not self.record.exists():
            return []
        lines = [json.loads(line) for line in self.record.read_text().splitlines()]
        return [line for line in lines if "argv" in line]

    def alive(self, pid):
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        except OSError:
            return False
        return fields[0] != "Z"

    def grandchild(self):
        found = []

        def has():
            lines = [json.loads(line) for line in self.record.read_text().splitlines()] \
                if self.record.exists() else []
            found[:] = [line for line in lines if "grandchild" in line]
            return bool(found)
        until(self, has)
        return found[-1]["grandchild"]


class SigninWriteTest(Case):
    def test_each_route_is_refused_without_the_origin_or_the_token(self):
        svc = self.begin()
        json_type = {"Content-Type": "application/json"}
        for path in BODIES:
            for name, headers, status, text in (
                    ("bare", json_type, 403, b"origin refused\n"),
                    ("no token", {"Origin": self.own()["Origin"], **json_type}, 403,
                     b"token refused\n"),
                    ("foreign", {"Origin": "http://evil.test", "X-Console-Token":
                                 self.own()["X-Console-Token"], **json_type}, 403,
                     b"origin refused\n")):
                with self.subTest(path=path, case=name):
                    rows, version = support.log_rows(self.store), svc.version
                    got = self.post(path, headers=headers)
                    self.assertEqual((got[0], got[2]), (status, text))
                    self.assertEqual(support.log_rows(self.store), rows)
                    self.assertEqual(svc.version, version)
                    self.assertFalse(self.record.exists())

    def test_each_accepted_write_appends_one_owner_action_row(self):
        self.begin()
        self.assertEqual(self.acted_rows(), [])
        expected = []

        def write(path, outcome_row):
            before = len(self.acted_rows())
            status = self.post(path)[0]
            self.assertIn(status, (200, 204))
            expected.append(outcome_row)
            self.assertEqual(len(self.acted_rows()), before + 1)

        write(SIGNIN, {"by": "owner", "profile": "work", "action": "start", "outcome": "started"})
        write(SIGNIN, {"by": "owner", "profile": "work", "action": "start", "outcome": "running"})
        write(CODE_PATH, {"by": "owner", "profile": "work", "action": "code", "outcome": "sent"})
        self.wait_ended(1)
        self.environ["FAKE_MODE"] = "hang"
        write(SIGNIN, {"by": "owner", "profile": "work", "action": "start", "outcome": "started"})
        write(CANCEL, {"by": "owner", "profile": "work", "action": "cancel",
                       "outcome": "cancelled"})
        self.assertEqual([payload for _, payload in self.acted_rows()], expected)

    def test_the_start_answers_the_link_and_a_pasted_code_reaches_the_client(self):
        self.begin()
        status, headers, body = self.post(SIGNIN)
        attempt = self.acted_rows()[0][0]
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(body), {"attempt": attempt, "link": LINK})
        self.assertEqual(self.view()["signin_runs"]["work"],
                         {"state": "running", "at": None, "attempt": attempt})
        self.assertEqual(self.post(CODE_PATH)[0], 204)
        until(self, lambda: {"code": CODE} in [json.loads(line) for line in
                                                self.record.read_text().splitlines()])
        self.assertEqual(self.wait_ended()[0][1]["attempt"], attempt)

    def test_a_code_the_clients_input_refuses_answers_502_and_the_run_stays_running(self):
        self.environ["FAKE_MODE"] = "deaf"
        self.begin()
        self.post(SIGNIN)
        until(self, lambda: self.record.exists() and {"deaf": True} in
              [json.loads(line) for line in self.record.read_text().splitlines()])
        rows = support.log_rows(self.store)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, _, body = self.post(CODE_PATH)
        self.assertEqual((status, body), (502, b"the code could not be passed on\n"))
        self.assertEqual(err.getvalue(), "console: signin_code_failed work BrokenPipeError\n")
        self.assertEqual(support.log_rows(self.store), rows)
        self.assertEqual(self.view()["signin_runs"]["work"]["state"], "running")

    def test_bodies_and_merits_are_refused_without_a_row(self):
        self.begin()
        rows = support.log_rows(self.store)
        json_headers = self.own(**{"Content-Type": "application/json"})
        for path, text in ((SIGNIN, b"bad sign-in"), (CODE_PATH, b"bad code"),
                           (CANCEL, b"bad cancel")):
            with self.subTest(path=path, check="body"):
                got = self.post(path, raw=b"{}")
                self.assertEqual((got[0], got[2]), (400, text + b"\n"))
            with self.subTest(path=path, check="media"):
                got = self.post(path, headers=self.own(**{"Content-Type": "text/plain"}))
                self.assertEqual((got[0], got[2]), (415, b"json only\n"))
            with self.subTest(path=path, check="large"):
                got = self.post(path, raw=b"x" * 4097, headers=json_headers)
                self.assertEqual((got[0], got[2]), (413, b"too large\n"))
            with self.subTest(path=path, check="unknown"):
                body = dict(BODIES[path], profile="nobody")
                got = self.post(path, body)
                self.assertEqual((got[0], got[2]), (409, b"unknown profile\n"))
        for path in (CODE_PATH, CANCEL):
            with self.subTest(path=path, check="idle"):
                got = self.post(path, dict(BODIES[path], profile="spare"))
                self.assertEqual((got[0], got[2]),
                                 (409, b"no sign-in is running for spare\n"))
        self.assertEqual(support.log_rows(self.store), rows)
        self.assertFalse(self.record.exists())

    def test_without_runs_the_host_refuses(self):
        self.begin(runs=False)
        rows = support.log_rows(self.store)
        got = self.post(SIGNIN)
        self.assertEqual((got[0], got[2]), (409, b"sign-in is not available on this host\n"))
        self.assertEqual(support.log_rows(self.store), rows)

    def test_other_methods_are_refused(self):
        svc = self.begin()
        for path in BODIES:
            for method in ("GET", "PUT", "DELETE"):
                with self.subTest(path=path, method=method):
                    status, headers, _ = support.request(svc.address, method, path)
                    self.assertEqual(status, 405)
                    self.assertEqual(headers["Allow"], "POST")


class SigninRunServiceTest(Case):
    def test_the_clients_exit_reads_the_status_at_once_and_a_signed_in_result_closes_the_item(self):
        self.begin()
        self.assertIn("signin/work", self.open_keys())
        self.post(SIGNIN)
        attempt = self.acted_rows()[0][0]
        self.answers["work"] = signin.Status("signed_in", iso(NOW + 30 * 86400))
        reads_before = len(self.reads)
        self.post(CODE_PATH)
        ended = self.wait_ended()
        self.assertEqual(len(self.reads), reads_before + 1)
        self.assertEqual(ended[0][1], {"profile": "work", "outcome": "signed_in",
                                       "attempt": attempt})
        self.assertNotIn("signin/work", self.open_keys())
        self.assertEqual(self.view()["signin_runs"]["work"]["state"], "signed_in")

    def test_an_older_scheduled_reading_never_overwrites_the_exit_reading(self):
        svc = self.begin()
        self.post(SIGNIN)
        self.now[0] += probe.PROBE_SECONDS
        gate = threading.Event()
        self.script = [(self.answers["spare"], None),
                       (signin.Status("signed_out", None), gate),
                       (signin.Status("signed_in", iso(NOW + 30 * 86400)), None)]
        thread = threading.Thread(target=svc.probe_round)
        thread.start()
        self.addCleanup(gate.set)
        self.assertTrue(self.entered.wait(10))
        self.post(CODE_PATH)
        ended = self.wait_ended()
        gate.set()
        thread.join(10)
        self.assertEqual(ended[0][1]["outcome"], "signed_in")
        readings = self.reading_rows("work")
        self.assertEqual(readings[-1]["state"], "signed_in")
        self.assertNotIn("signed_out", [r["state"] for r in readings[
            [r["state"] for r in readings].index("signed_in"):]])
        self.assertNotIn("signin/work", self.open_keys())

    def test_a_failed_exit_ends_failed(self):
        self.environ["FAKE_EXIT"] = "1"
        self.begin()
        self.post(SIGNIN)
        self.post(CODE_PATH)
        self.assertEqual(self.wait_ended()[0][1]["outcome"], "failed")
        self.assertEqual(self.item("signin/work")["run"]["state"], "failed")

    def test_a_second_start_starts_no_second_client(self):
        self.begin()
        first = self.post(SIGNIN)
        second = self.post(SIGNIN)
        self.assertEqual((first[0], second[0]), (200, 200))
        self.assertEqual(first[2], second[2])
        self.assertEqual(len(self.invocations()), 1)
        acted = self.acted_rows()
        self.assertEqual(acted[1][1]["outcome"], "running")
        self.assertEqual(self.view()["signin_runs"]["work"],
                         {"state": "running", "at": None, "attempt": acted[0][0]})

    @unittest.skipUnless(LINUX, "reads /proc")
    def test_a_timed_out_or_cancelled_sign_in_is_killed_and_offered_again(self):
        self.environ["FAKE_MODE"] = "hang"
        svc = self.begin()
        self.post(SIGNIN)
        pid = self.grandchild()
        self.mono[0] += 600
        self.assertEqual(svc.expire_signins(), ["work"])
        ended = self.wait_ended(1)
        self.assertEqual(ended[0][1]["outcome"], "timed_out")
        until(self, lambda: not self.alive(pid), 5)
        self.assertEqual(self.item("signin/work")["run"]["state"], "timed_out")
        status, _, body = self.post(SIGNIN)
        again = json.loads(body)["attempt"]
        self.assertEqual(status, 200)
        self.assertGreater(again, ended[0][1]["attempt"])
        until(self, lambda: len(self.invocations()) == 2)
        self.post(CANCEL)
        ended = self.wait_ended(2)
        self.assertEqual((ended[1][1]["outcome"], ended[1][1]["attempt"]), ("cancelled", again))
        self.assertEqual(self.item("signin/work")["run"]["state"], "cancelled")

    @unittest.skipUnless(LINUX, "reads /proc")
    def test_an_unsuccessful_run_whose_status_read_fails_is_offered_again(self):
        for outcome in ("cancelled", "timed_out"):
            with self.subTest(outcome=outcome):
                self.setUp()
                self.environ["FAKE_MODE"] = "hang"
                svc = self.begin()
                self.post(SIGNIN)
                self.grandchild()
                readings = len(self.reading_rows("work"))
                self.script = [(signin.StatusFailed("timeout"), None)]
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    if outcome == "cancelled":
                        self.post(CANCEL)
                    else:
                        self.mono[0] += 600
                        svc.expire_signins()
                    ended = self.wait_ended()
                self.assertEqual(ended[0][1]["outcome"], outcome)
                self.assertEqual(len(self.reading_rows("work")), readings)
                self.assertNotIn("unknown", [r["state"] for r in self.reading_rows("work")])
                self.assertIn("console: signin_end_read_failed work timeout\n", err.getvalue())
                self.assertEqual(self.item("signin/work")["run"]["state"], outcome)

    def test_close_ends_a_running_sign_in_without_a_row(self):
        self.environ["FAKE_MODE"] = "hang"
        svc = self.begin()
        self.post(SIGNIN)
        pid = self.grandchild()
        svc.close()
        self.assertEqual(self.ended_rows(), [])
        until(self, lambda: not self.alive(pid), 5)


class SigninSecrecyTest(Case):
    def test_sign_in_material_is_in_no_log_row_stderr_line_state_or_stream_frame(self):
        buffer = io.StringIO()
        frames = []
        stop = threading.Event()
        with contextlib.redirect_stderr(buffer):
            svc = self.begin(link_wait=0.5)
            response = open_stream(self, svc)

            def collect():
                while not stop.is_set():
                    try:
                        frame = next_frame(response)
                    except (TimeoutError, socket.timeout, OSError, http.client.HTTPException):
                        continue
                    if not frame:
                        return
                    frames.append(frame)

            thread = threading.Thread(target=collect, daemon=True)
            thread.start()
            for count, extra in enumerate((
                    {}, {"FAKE_EXIT": "1"},
                    {"FAKE_EXIT": "0", "FAKE_LINK": "javascript:SENTINEL-LINK-bad"}), start=1):
                self.environ.update(extra)
                self.assertEqual(self.post(SIGNIN)[0], 200)
                self.assertEqual(self.post(CODE_PATH)[0], 204)
                self.wait_ended(count)
            state = support.request(svc.address, "GET", "/api/state")[2]
            time.sleep(0.2)
            stop.set()
            thread.join(5)
        texts = [json.dumps([str(column) for column in row]) for row in
                 support.log_rows(self.store)]
        self.assertTrue(texts)
        self.assertTrue(frames)
        for text in (*texts, buffer.getvalue(), state.decode(),
                     *(frame.decode() for frame in frames)):
            self.assertNotIn("SENTINEL-LINK", text)
            self.assertNotIn("SENTINEL-CODE", text)


if __name__ == "__main__":
    unittest.main()
