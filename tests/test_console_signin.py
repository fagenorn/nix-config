"""The console's sign-in reader (#1010): command, environment, parse rules, runner, fold and ask.

Run: just agent-workflow-tests
"""

import dataclasses
import json
import os
import subprocess
import sys
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.console import signin
from agent_tools.console.event_log import Event
from agent_tools.console.probe import Probe
from agent_tools.console.signin import SignIn, Status, StatusFailed
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

SID = "0b6f5a3e-2c1d-4e8f-9a7b-1c2d3e4f5a6b"
CREDENTIAL_NAMES = {".credentials.json", ".claude.json"}
ARMED = threading.Event()
HITS: list[str] = []


def _audit(event, args):
    if event == "open" and ARMED.is_set() and args and isinstance(args[0], (str, bytes, os.PathLike)):
        name = os.path.basename(os.fsdecode(args[0]))
        if name in CREDENTIAL_NAMES:
            HITS.append(name)


sys.addaudithook(_audit)

ENVIRON = {"HOME": "/home/u", "PATH": "/bin"}

SIGNED_IN = json.dumps({
    "loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
    "analyticsDisabled": False, "projectsDirectory": "/home/u/.claude/projects",
    "configDirectory": "/home/u/.claude", "loginExpiresAt": "2026-12-05T20:21:35.023Z",
    "email": "owner@example.invalid", "orgId": "00000000-0000-0000-0000-000000000000",
    "orgName": "Example", "subscriptionType": "team", "storedClaudeAiLogin": True,
    "planTier": "other"}).encode()
SIGNED_OUT = json.dumps({
    "loggedIn": False, "authMethod": "none", "apiProvider": "firstParty",
    "analyticsDisabled": False, "projectsDirectory": "/tmp/x/projects",
    "configDirectory": "/tmp/x", "loginExpiresAt": None}).encode()


def signed_in_with(end):
    document = json.loads(SIGNED_IN)
    document["loginExpiresAt"] = end
    return json.dumps(document).encode()


class Recorder:
    def __init__(self, returncode=0, stdout=b"", error=None):
        self.calls = []
        self.during = []
        self.returncode = returncode
        self.stdout = stdout
        self.error = error

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        cwd = Path(kwargs["cwd"])
        self.during.append((cwd.is_dir(), list(cwd.iterdir())))
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout)


class StatusCommandTest(unittest.TestCase):
    def test_the_status_command_is_the_clients_json_status(self):
        self.assertEqual(signin.status_command(),
                         ["claude-account", "run", "auth", "status", "--json"])

    def test_the_status_environment_names_the_profile_and_skips_the_proxy(self):
        environ = {"HOME": "/home/u", "PATH": "/bin", "LANG": "C", "CLAUDE_CONFIG_DIR": "/x",
                   "ANTHROPIC_BASE_URL": "http://e", "ANTHROPIC_API_KEY": "k",
                   "ANTHROPIC_AUTH_TOKEN": "t", "CLAUDE_CACHE_PROXY": "required",
                   "CONSOLE_SPRINT_SECRET": "s"}

        env = signin.status_environment("work", environ)

        self.assertEqual(env["CLAUDE_ACCOUNT"], "work")
        self.assertEqual(env["CLAUDE_CACHE_PROXY"], "0")
        self.assertEqual(env["PATH"], "/home/u/.agents/bin:/bin")
        self.assertEqual(env["LANG"], "C")
        for key in ("CLAUDE_CONFIG_DIR", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY",
                    "ANTHROPIC_AUTH_TOKEN", "CONSOLE_SPRINT_SECRET"):
            self.assertNotIn(key, env)


class ParseStatusTest(unittest.TestCase):
    def test_recorded_outputs_are_read(self):
        rows = [(0, SIGNED_IN, Status("signed_in", "2026-12-05T20:21:35.023000+00:00")),
                (1, SIGNED_OUT, Status("signed_out", None)),
                (0, signed_in_with(None), Status("signed_in", None)),
                (0, signed_in_with("2026-12-05T22:21:35+02:00"),
                 Status("signed_in", "2026-12-05T20:21:35+00:00"))]
        for returncode, stdout, expected in rows:
            with self.subTest(returncode=returncode, stdout=stdout[:60]):
                self.assertEqual(signin.parse_status(returncode, stdout), expected)

    def test_unexpected_output_is_unreadable(self):
        rows = [(0, b""), (0, b"not json"), (0, b"\xff"), (0, b"[]"),
                (0, b'{"loggedIn": "yes"}'), (0, b'{"loggedIn": false}'),
                (1, SIGNED_IN), (0, signed_in_with("soon")),
                (0, signed_in_with("2026-12-05T20:21:35")), (0, signed_in_with(5))]
        for returncode, stdout in rows:
            with self.subTest(returncode=returncode, stdout=stdout[:60]):
                with self.assertRaises(StatusFailed) as raised:
                    signin.parse_status(returncode, stdout)
                self.assertEqual(raised.exception.kind, "unreadable")
                self.assertEqual(str(raised.exception), "unreadable")

    def test_another_exit_status_is_exited(self):
        for returncode, stdout in ((2, SIGNED_OUT), (127, b""), (-9, b"")):
            with self.subTest(returncode=returncode):
                with self.assertRaises(StatusFailed) as raised:
                    signin.parse_status(returncode, stdout)
                self.assertEqual(raised.exception.kind, "exited")

    def test_only_the_flag_and_the_end_are_kept(self):
        self.assertEqual([f.name for f in dataclasses.fields(Status)], ["state", "ends_at"])

        entry = signin.entry("work", signin.parse_status(0, SIGNED_IN))

        self.assertEqual(entry, ("signin.reading", None,
                                 {"profile": "work", "state": "signed_in",
                                  "ends_at": "2026-12-05T20:21:35.023000+00:00"}))
        self.assertNotIn("owner@example.invalid", json.dumps(entry))


class ReadStatusTest(unittest.TestCase):
    def test_read_status_runs_without_a_terminal_in_an_empty_directory(self):
        fake = Recorder(0, SIGNED_IN)

        status = signin.read_status(Probe("work", SID), run=fake, environ=ENVIRON, timeout=7)

        self.assertEqual(status, Status("signed_in", "2026-12-05T20:21:35.023000+00:00"))
        self.assertEqual(len(fake.calls), 1)
        argv, kwargs = fake.calls[0]
        self.assertEqual(argv, signin.status_command())
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.PIPE)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        self.assertIs(kwargs["start_new_session"], True)
        self.assertEqual(kwargs["timeout"], 7)
        self.assertIs(kwargs["check"], False)
        self.assertNotIn("cancel", kwargs)
        self.assertEqual(kwargs["env"]["CLAUDE_ACCOUNT"], "work")
        self.assertEqual(fake.during, [(True, [])])
        self.assertTrue(Path(kwargs["cwd"]).name.startswith("console-signin-"))
        self.assertFalse(Path(kwargs["cwd"]).exists())

        stop = threading.Event()
        with_stop = Recorder(0, SIGNED_IN)
        signin.read_status(Probe("work", SID, stop), run=with_stop, environ=ENVIRON)
        self.assertIs(with_stop.calls[0][1]["cancel"], stop)

    def test_runner_failures_are_kinds(self):
        rows = [("not_installed", FileNotFoundError()),
                ("timed_out", subprocess.TimeoutExpired("x", 1)),
                ("unavailable", PermissionError())]
        for kind, error in rows:
            with self.subTest(kind=kind):
                with self.assertRaises(StatusFailed) as raised:
                    signin.read_status(Probe("work", SID), run=Recorder(error=error),
                                       environ=ENVIRON)
                self.assertEqual(raised.exception.kind, kind)

    def test_read_status_opens_no_credential_file(self):
        HITS.clear()
        ARMED.set()
        try:
            signin.read_status(Probe("work", SID), run=Recorder(1, SIGNED_OUT), environ=ENVIRON)
        finally:
            ARMED.clear()

        self.assertEqual(HITS, [])

    def test_the_reader_is_linux_only(self):
        self.assertIs(signin.reader_for("linux"), signin.read_status)
        self.assertIsNone(signin.reader_for("darwin"))


E = 1796000000


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def reading(seq, at, **payload):
    return Event(seq, at, "signin.reading", None, payload)


class FoldTest(unittest.TestCase):
    def test_the_last_reading_per_profile_is_kept_and_malformed_ones_are_ignored(self):
        valid = [reading(1, "t1", profile="work", state="signed_in", ends_at=iso(E)),
                 reading(2, "t2", profile="spare", state="signed_out", ends_at=None),
                 reading(3, "t3", profile="work", state="signed_out", ends_at=None)]
        malformed = [reading(4, "t4", state="signed_out", ends_at=None),
                     reading(5, "t5", profile="work", state="maybe", ends_at=None),
                     reading(6, "t6", profile="work", state="signed_out", ends_at=iso(E)),
                     reading(7, "t7", profile="work", state="signed_in", ends_at="x"),
                     Event(8, "t8", "capacity.reading", None,
                           {"profile": "work", "state": "signed_in", "ends_at": None})]

        folded = signin.signin_state(valid + malformed)

        self.assertEqual(folded, {"work": SignIn("signed_out", None, "t3", ever=True),
                                  "spare": SignIn("signed_out", None, "t2")})
        self.assertEqual(signin.signin_state(valid[1:] + malformed, signin.signin_state(valid[:1])),
                         folded)

    def test_a_profile_once_signed_in_stays_ever_signed_in(self):
        readings = [reading(1, "t1", profile="work", state="signed_in", ends_at=iso(E)),
                    reading(2, "t2", profile="spare", state="signed_out", ends_at=None),
                    reading(3, "t3", profile="work", state="signed_out", ends_at=None)]

        folded = signin.signin_state(readings)
        split = signin.signin_state(readings[1:], signin.signin_state(readings[:1]))

        self.assertEqual(folded["work"], SignIn("signed_out", None, "t3", ever=True))
        self.assertIs(folded["spare"].ever, False)
        self.assertEqual(split, folded)


class ProfileSigninTest(unittest.TestCase):
    def test_the_ask_table(self):
        unknown = {"state": "unknown", "ends_at": None, "days_left": None, "ask": False,
                   "since": None, "ever_signed_in": False}
        signed_in = SignIn("signed_in", iso(E), "t1")
        rows = [(signed_in, E - 259201, {"state": "signed_in", "ends_at": iso(E), "days_left": 3,
                                         "ask": False, "since": None, "ever_signed_in": True}),
                (signed_in, E - 259200, {"state": "signed_in", "ends_at": iso(E), "days_left": 3,
                                         "ask": True, "since": iso(E - 259200),
                                         "ever_signed_in": True}),
                (signed_in, E + 10, {"state": "signed_in", "ends_at": iso(E), "days_left": 0,
                                     "ask": True, "since": iso(E - 259200),
                                     "ever_signed_in": True}),
                (SignIn("signed_out", None, "t2"), E,
                 {"state": "signed_out", "ends_at": None, "days_left": None, "ask": True,
                  "since": "t2", "ever_signed_in": False}),
                (None, E, unknown),
                (SignIn("unknown", None, "t3"), E, unknown),
                (SignIn("signed_in", None, "t4"), E,
                 {"state": "signed_in", "ends_at": None, "days_left": None, "ask": False,
                  "since": None, "ever_signed_in": True})]
        for sign, now, expected in rows:
            with self.subTest(sign=sign, now=now):
                self.assertEqual(signin.profile_signin(sign, now), expected)

    def test_ever_signed_in_is_reported_in_every_state(self):
        for sign, expected in [(SignIn("signed_out", None, "t2", ever=True), True),
                               (SignIn("signed_out", None, "t2"), False),
                               (None, False),
                               (SignIn("unknown", None, "t3", ever=True), True),
                               (SignIn("signed_in", None, "t4"), True)]:
            with self.subTest(sign=sign):
                self.assertIs(signin.profile_signin(sign, E)["ever_signed_in"], expected)


if __name__ == "__main__":
    unittest.main()
