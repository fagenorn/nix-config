"""The held check that another user is refused on the owner port and the owner's forward loads (#1294).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import subprocess
import unittest
from pathlib import Path

from agent_tools.console import owner_port_check, peer
from agent_tools.console.owner_port_check import (
    Forward, connect_as, forward_argv, request_as, request_through_forward)
from tests.test_verify_checks import committed_mode
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-owner-port"
NOT_OWNER = peer.NOT_OWNER_TEXT.encode() + b"\n"


def run_main(as_other, through_forward):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = owner_port_check.main(["--as", "_runner"], as_other=as_other,
                                     through_forward=through_forward)
    return code, json.loads(out.getvalue())


class MainTest(unittest.TestCase):
    def test_a_refused_other_user_and_a_loaded_owner_page_is_met(self):
        code, printed = run_main(lambda user, port: (403, NOT_OWNER),
                                 lambda port, user: Forward(200, "denied", None))
        self.assertEqual(code, 0)
        self.assertEqual(printed, {"forward_other_status": None, "other_status": 403,
                                   "owner_status": 200, "status": "met"})

    def test_an_answered_other_user_is_not_met(self):
        calls = []

        def forward(port, user):
            calls.append((port, user))
            return Forward(200, "denied", None)

        for answer in ((200, b"<html>"), (403, b"loopback only\n")):
            with self.subTest(answer=answer):
                code, printed = run_main(lambda user, port, a=answer: a, forward)
                self.assertEqual(code, 1)
                self.assertEqual(printed["reason"], "not_refused")
                self.assertEqual(printed["status"], "not_met")
        self.assertEqual(calls, [])

    def test_an_other_user_request_that_cannot_be_made_is_not_yet(self):
        code, printed = run_main(lambda user, port: None, lambda port, user: Forward(200, "denied", None))
        self.assertEqual(code, 75)
        self.assertEqual(printed["reason"], "cannot_request_as_other_user")

    def test_an_owner_page_that_does_not_load_is_not_met(self):
        code, printed = run_main(lambda user, port: (403, NOT_OWNER),
                                 lambda port, user: Forward(403, "denied", None))
        self.assertEqual(code, 1)
        self.assertEqual(printed["reason"], "owner_page_not_loaded")
        self.assertEqual(printed["owner_status"], 403)

    def test_a_forward_that_cannot_be_opened_is_not_yet(self):
        code, printed = run_main(lambda user, port: (403, NOT_OWNER), lambda port, user: None)
        self.assertEqual(code, 75)
        self.assertEqual(printed["reason"], "no_forward")

    def test_a_forward_another_user_can_open_is_not_met(self):
        code, printed = run_main(lambda user, port: (403, NOT_OWNER),
                                 lambda port, user: Forward(200, "connected", (200, b"<html>")))
        self.assertEqual(code, 1)
        self.assertEqual(printed["reason"], "forward_reachable_by_other_user")
        self.assertEqual(printed["forward_other_status"], 200)

    def test_isolation_without_a_permission_denied_proof_is_not_yet(self):
        code, printed = run_main(lambda user, port: (403, NOT_OWNER),
                                 lambda port, user: Forward(200, "unknown", None))
        self.assertEqual(code, 75)
        self.assertEqual(printed["status"], "not_yet")
        self.assertEqual(printed["reason"], "isolation_not_proven")

    def test_a_bad_argument_is_exit_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                owner_port_check.main([])
        self.assertEqual(raised.exception.code, 2)


class RequestAsTest(unittest.TestCase):
    BASE = ["/usr/bin/sudo", "-n", "-u", "_runner", "/usr/bin/curl", "-q", "--noproxy", "*", "-sS",
            "--max-time", "5", "-H", "Host: 127.0.0.1:27184", "-w", "\n%{http_code}",
            "http://127.0.0.1:27184/"]

    def stub(self, code, out, record):
        def run(argv, **kwargs):
            record.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, code, out, b"")
        return run

    def test_request_as_runs_curl_as_the_user_through_sudo(self):
        record = []
        result = request_as("_runner", 27184, run=self.stub(0, NOT_OWNER + b"\n403", record))
        self.assertEqual(result, (403, NOT_OWNER))
        (argv, kwargs), = record
        self.assertEqual(argv, self.BASE)
        self.assertIs(kwargs["capture_output"], True)
        self.assertNotIn("shell", kwargs)

        record = []
        request_as("_runner", 27184, unix_socket="/tmp/x/console.sock",
                   run=self.stub(0, NOT_OWNER + b"\n403", record))
        self.assertEqual(record[0][0], self.BASE[:11] + ["--unix-socket", "/tmp/x/console.sock"]
                         + self.BASE[11:])

    def test_a_request_that_was_not_made_is_none(self):
        def raising(exc):
            def run(argv, **kwargs):
                raise exc
            return run

        cases = [self.stub(7, b"\n000", []), self.stub(0, b"\n000", []), self.stub(1, b"", []),
                 self.stub(0, b"<html>", []), raising(OSError("no sudo")),
                 raising(subprocess.TimeoutExpired("sudo", 15))]
        for run in cases:
            with self.subTest(run=run):
                self.assertIsNone(request_as("_runner", 27184, run=run))


class ConnectAsTest(unittest.TestCase):
    def stub(self, code, record=None, kwargs_record=None):
        def run(argv, **kwargs):
            if record is not None:
                record.append(argv)
            if kwargs_record is not None:
                kwargs_record.append(kwargs)
            return subprocess.CompletedProcess(argv, code, b"", b"")
        return run

    def test_only_the_permission_denied_exit_is_denied(self):
        record = []
        self.assertEqual(connect_as("_runner", "/tmp/x/console.sock", run=self.stub(13, record)),
                         "denied")
        argv, = record
        self.assertEqual(argv[:5], ["/usr/bin/sudo", "-n", "-u", "_runner", "/usr/bin/python3"])
        self.assertEqual(argv[-1], "/tmp/x/console.sock")
        self.assertEqual(connect_as("_runner", "s", run=self.stub(0)), "connected")
        for code in (1, 14, 127):
            with self.subTest(code=code):
                self.assertEqual(connect_as("_runner", "s", run=self.stub(code)), "unknown")

    def test_the_probe_runs_isolated_from_a_folder_every_user_can_read(self):
        argvs, kwargs = [], []
        connect_as("_runner", "/tmp/x/console.sock", run=self.stub(13, argvs, kwargs))
        argv, = argvs
        self.assertEqual(argv[:6], ["/usr/bin/sudo", "-n", "-u", "_runner", "/usr/bin/python3",
                                    "-I"])
        self.assertEqual(argv[6], "-c")
        kw, = kwargs
        self.assertEqual(kw["cwd"], "/")

    def test_a_probe_that_did_not_run_is_unknown(self):
        def raising(exc):
            def run(argv, **kwargs):
                raise exc
            return run

        for exc in (OSError("no sudo"), subprocess.TimeoutExpired("sudo", 15)):
            with self.subTest(exc=exc):
                self.assertEqual(connect_as("_runner", "s", run=raising(exc)), "unknown")

    def test_the_probe_script_connects_and_reports_a_missing_socket_as_unknown(self):
        import socket
        import tempfile
        # A short path: Darwin allows 104 bytes in a socket pathname, and its temporary root is long.
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            sock = os.path.join(tmp, "s")
            server = socket.socket(socket.AF_UNIX)
            self.addCleanup(server.close)
            server.bind(sock)
            server.listen(1)

            def local(argv, **kwargs):
                return subprocess.run(argv[4:], capture_output=True, check=False)

            self.assertEqual(connect_as("ignored", sock, run=local), "connected")
            os.unlink(sock)
            self.assertEqual(connect_as("ignored", sock, run=local), "unknown")


class WrapperTest(unittest.TestCase):
    def test_the_wrapper_runs_the_module(self):
        path = ROOT / WRAPPER
        self.assertTrue(os.access(path, os.X_OK))
        lines = [line for line in path.read_text().splitlines() if line.strip()]
        self.assertEqual(lines[0], "#!/bin/sh")
        self.assertEqual(lines[-1],
                         'PYTHONPATH=python exec python3 -m agent_tools.console.owner_port_check "$@"')
        self.assertEqual(committed_mode(WRAPPER), "100755")


class ForwardTest(unittest.TestCase):
    def test_the_forward_listens_on_a_socket_in_a_private_temp_dir(self):
        popens, gets, others, events = [], [], [], []
        seen = {}

        class Proc:
            def poll(self):
                return None

            def terminate(self):
                events.append("terminate")

            def wait(self, timeout=None):
                events.append(("wait", timeout))

        def popen(argv, **kwargs):
            popens.append((argv, kwargs))
            return Proc()

        def get(sock, port, proc=None):
            gets.append((sock, port))
            st = os.stat(os.path.dirname(sock))
            seen["mode"], seen["uid"] = st.st_mode & 0o777, st.st_uid
            return 200

        def other(user, port, unix_socket=None):
            others.append((user, port, unix_socket))
            return None

        connects = []

        def connect(user, sock):
            connects.append((user, sock))
            return "denied"

        result = request_through_forward(27184, "_runner", owner="me", popen=popen, get=get,
                                         connect=connect, other=other)
        self.assertEqual(result, Forward(200, "denied", None))
        (argv, _), = popens
        (sock, port), = gets
        self.assertEqual(port, 27184)
        self.assertEqual(os.path.basename(sock), "console.sock")
        directory = os.path.dirname(sock)
        self.assertEqual(argv, forward_argv(sock, 27184, "me", os.path.join(directory, "known_hosts")))
        forwards = [argv[i + 1] for i, a in enumerate(argv) if a == "-L"]
        self.assertEqual(forwards, [f"{sock}:127.0.0.1:27184"])
        for value in forwards:
            self.assertFalse(value.startswith(("127.0.0.1:", "localhost:")) or value[0].isdigit())
        self.assertEqual(seen["mode"], 0o700)
        self.assertEqual(seen["uid"], os.geteuid())
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("ExitOnForwardFailure=yes", argv)
        self.assertIn("me@127.0.0.1", argv)
        self.assertEqual(connects, [("_runner", sock)])
        self.assertEqual(others, [])
        self.assertIn("terminate", events)
        self.assertTrue(any(e[0] == "wait" for e in events if isinstance(e, tuple)))
        self.assertFalse(os.path.exists(directory))

        others.clear()
        events.clear()
        connected = request_through_forward(27184, "_runner", owner="me", popen=popen, get=get,
                                            connect=lambda user, sock: "connected", other=other)
        self.assertEqual(connected.isolation, "connected")
        self.assertEqual([o[:2] for o in others], [("_runner", 27184)])
        others.clear()
        events.clear()
        self.assertIsNone(request_through_forward(27184, "_runner", owner="me", popen=popen,
                                                  get=lambda sock, port, proc=None: None,
                                                  other=other))
        self.assertEqual(others, [])
        self.assertIn("terminate", events)

    def test_a_forward_that_died_before_the_probe_proves_nothing(self):
        class Dead:
            def poll(self):
                return 255

            def terminate(self):
                pass

            def wait(self, timeout=None):
                pass

        result = request_through_forward(27184, "_runner", owner="me", popen=lambda *a, **k: Dead(),
                                         get=lambda sock, port, proc=None: 200,
                                         connect=lambda user, sock: "denied",
                                         other=lambda *a, **k: None)
        self.assertEqual(result, Forward(200, "unknown", None))

    def test_an_ssh_that_cannot_be_spawned_is_no_forward(self):
        def popen(argv, **kwargs):
            raise FileNotFoundError("ssh")

        self.assertIsNone(request_through_forward(27184, "_runner", owner="me", popen=popen))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = owner_port_check.main(
                ["--as", "_runner"], as_other=lambda user, port: (403, NOT_OWNER),
                through_forward=lambda port, user: request_through_forward(
                    port, user, owner="me", popen=popen))
        self.assertEqual(code, 75)
        self.assertEqual(json.loads(out.getvalue())["reason"], "no_forward")


if __name__ == "__main__":
    unittest.main()
