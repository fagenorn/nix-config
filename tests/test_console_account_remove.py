"""The console's account remover (#1030): the request, the row, the sign-out run, the launcher's rm.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from agent_tools.console import event_log, probe
from agent_tools.console.account_remove import (
    REMOVAL, RemoveFailed, Remover, SignOutFailed, busy, parse_remove_request, remover_for,
    removed, removing, sign_out, signer_out_for)
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1030)
from .test_console_account_add import LAUNCHER, launcher_env


class RequestTest(unittest.TestCase):
    def test_the_request_is_exactly_a_profile_and_a_typed_name(self):
        self.assertEqual(parse_remove_request(b'{"profile":"work","typed":"work"}'),
                         ("work", "work"))
        self.assertEqual(parse_remove_request(b'{"profile":"work","typed":""}'), ("work", ""))
        long = "a" * 129
        self.assertEqual(parse_remove_request(json.dumps({"profile": long, "typed": long}).encode()),
                         (long, long))
        for body in (b"{}", b'{"profile":"work"}', b'{"profile":"","typed":"x"}',
                     b'{"profile":1,"typed":"x"}', b'{"profile":"w","typed":1}',
                     b'{"profile":"w","typed":"w","x":1}', b"[]", b"\xff"):
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    parse_remove_request(body)

    def test_the_row_names_the_owner_the_profile_and_how_it_ended(self):
        self.assertEqual(removed("work", "removed", None),
                         ("account.removal", None, {"by": "owner", "profile": "work",
                                                    "outcome": "removed", "kind": None}))
        self.assertEqual(removed("work", "signout_failed", "exited")[2]["kind"], "exited")
        self.assertEqual(removed("a" * 129, "removed", None)[2]["profile"], "a" * 129)
        self.assertEqual(busy("work"), "work is still being read; try again in a moment")
        self.assertEqual(removing("work"), "work is being removed")
        self.assertEqual(REMOVAL, "account.removal")
        self.assertEqual(event_log.ACCOUNT_REMOVAL, "account.removal")
        self.assertNotIn(REMOVAL, event_log.KEPT_KINDS)
        for args in (("default", "removed", None), ("Work", "removed", None),
                     ("work", "gone", None), ("work", "gone", "exited"), ("work", "removed", "exited"),
                     ("work", "remove_failed", None)):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    removed(*args)


class SignOutTest(unittest.TestCase):
    def recording(self, outcome):
        calls = []

        def fake(argv, **kw):
            cwd = Path(kw["cwd"])
            calls.append((argv, kw, cwd))
            self.assertTrue(cwd.name.startswith("console-signout-"))
            self.assertTrue(cwd.exists())
            if isinstance(outcome, BaseException):
                raise outcome
            return subprocess.CompletedProcess(argv, outcome)
        return fake, calls

    def test_sign_out_runs_the_clients_logout_under_the_profile_with_no_terminal(self):
        fake, calls = self.recording(0)
        environ = {"HOME": "/h", "PATH": "/bin", "ANTHROPIC_API_KEY": "k",
                   "CLAUDE_CACHE_PROXY": "1"}
        stop = threading.Event()
        sign_out(probe.Probe("work", "sid", stop), run=fake, environ=environ, timeout=7)
        (argv, kw, cwd), = calls
        self.assertEqual(argv, ["claude-account", "run", "auth", "logout"])
        self.assertEqual(kw["env"]["CLAUDE_ACCOUNT"], "work")
        self.assertEqual(kw["env"]["CLAUDE_CACHE_PROXY"], "0")
        self.assertNotIn("ANTHROPIC_API_KEY", kw["env"])
        for stream in ("stdin", "stdout", "stderr"):
            self.assertIs(kw[stream], subprocess.DEVNULL)
        self.assertIs(kw["start_new_session"], True)
        self.assertEqual(kw["timeout"], 7)
        self.assertIs(kw["cancel"], stop)
        self.assertFalse(cwd.exists())

    def test_a_failed_sign_out_names_its_kind(self):
        cases = [("timed_out", subprocess.TimeoutExpired(["x"], 1)),
                 ("not_installed", FileNotFoundError()), ("unavailable", OSError()),
                 ("exited", 1)]
        for kind, outcome in cases:
            with self.subTest(kind=kind):
                fake, calls = self.recording(outcome)
                with self.assertRaises(SignOutFailed) as caught:
                    sign_out(probe.Probe("work", "sid", None), run=fake, environ={})
                self.assertEqual(caught.exception.kind, kind)
                self.assertEqual(str(caught.exception), kind)
                self.assertFalse(calls[0][2].exists())


class RemoverTest(unittest.TestCase):
    def test_the_remover_runs_the_launchers_rm_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = launcher_env(root)
            subprocess.run([str(LAUNCHER), "add", "scratch"], env=env, check=True,
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
            profiles = root / "accounts" / "profiles"
            self.assertTrue((profiles / "scratch").is_dir())
            Remover(command=(str(LAUNCHER),), environ=env)("scratch")
            self.assertFalse((profiles / "scratch").exists())
            self.assertTrue(profiles.is_dir())
            marker = root / "ran"
            script = root / "marker"
            script.write_text(f"#!/bin/sh\ntouch {marker}\n")
            script.chmod(0o755)
            with self.assertRaises(ValueError):
                Remover(command=(str(script),), environ=env)("default")
            self.assertFalse(marker.exists())
            with self.assertRaises(ValueError):
                Remover(command=(str(LAUNCHER),), environ=env)("default")

    def test_a_failed_rm_names_its_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fail = root / "fail"
            fail.write_text("#!/bin/sh\nexit 3\n")
            slow = root / "slow"
            slow.write_text("#!/bin/sh\nsleep 5\n")
            for script in (fail, slow):
                script.chmod(0o755)
            cases = [("not_installed", Remover(command=("/nonexistent/claude-account",))),
                     ("failed", Remover(command=(str(fail),))),
                     ("timed_out", Remover(command=(str(slow),), timeout=0.2))]
            for kind, remover in cases:
                with self.subTest(kind=kind):
                    with self.assertRaises(RemoveFailed) as caught:
                        remover("x")
                    self.assertEqual(caught.exception.kind, kind)
                    self.assertEqual(str(caught.exception), kind)


class PlatformTest(unittest.TestCase):
    def test_only_linux_gets_a_signer_out_and_a_remover(self):
        self.assertIs(signer_out_for("linux"), sign_out)
        self.assertIsInstance(remover_for("linux"), Remover)
        self.assertIsNone(signer_out_for("darwin"))
        self.assertIsNone(remover_for("darwin"))


if __name__ == "__main__":
    sys.exit(unittest.main())
