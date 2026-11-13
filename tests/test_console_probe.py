"""The console's capacity probe (#1009): command, environment, runner and schedule.

Run: just agent-workflow-tests
"""

import inspect
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent_tools.console import manager, nudge, probe
from agent_tools.console.probe import Probe

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


class Recorder:
    def __init__(self, returncode=0, error=None):
        self.calls = []
        self.during = []
        self.returncode = returncode
        self.error = error

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        cwd = Path(kwargs["cwd"])
        self.during.append((cwd.is_dir(), list(cwd.iterdir())))
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(argv, self.returncode)


class ProbeCommandTest(unittest.TestCase):
    def test_the_probe_command_asks_once_under_a_fixed_session(self):
        argv = probe.probe_command(Probe("work", SID))

        self.assertEqual(probe.MODEL, "haiku")
        self.assertEqual(argv, ["claude-account", "run", "-p", "--session-id", SID,
                                "--no-session-persistence", "--strict-mcp-config",
                                "--model", "haiku", "--max-turns", "1",
                                "Reply with the single word OK."])

    def test_the_probe_environment_names_the_profile_and_requires_the_proxy(self):
        environ = {"HOME": "/home/u", "PATH": "/bin", "LANG": "C", "CLAUDE_CONFIG_DIR": "/x",
                   "ANTHROPIC_BASE_URL": "http://elsewhere", "ANTHROPIC_API_KEY": "k",
                   "ANTHROPIC_AUTH_TOKEN": "t", "CLAUDE_CACHE_PROXY": "0",
                   "CONSOLE_SPRINT_SECRET": "s"}

        env = probe.probe_environment("work", environ)

        self.assertEqual(env["CLAUDE_ACCOUNT"], "work")
        self.assertEqual(env["CLAUDE_CACHE_PROXY"], "required")
        self.assertEqual(env["PATH"], "/home/u/.agents/bin:/bin")
        self.assertEqual(env["LANG"], "C")
        for key in ("CLAUDE_CONFIG_DIR", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY",
                    "ANTHROPIC_AUTH_TOKEN", "CONSOLE_SPRINT_SECRET"):
            self.assertNotIn(key, env)

    def test_run_probe_starts_without_a_terminal_in_an_empty_directory(self):
        fake = Recorder()

        probe.run_probe(Probe("work", SID), run=fake, environ=ENVIRON)

        self.assertEqual(len(fake.calls), 1)
        argv, kwargs = fake.calls[0]
        self.assertEqual(argv, probe.probe_command(Probe("work", SID)))
        self.assertEqual(kwargs["env"], probe.probe_environment("work", ENVIRON))
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        self.assertIs(kwargs["start_new_session"], True)
        self.assertEqual(kwargs["timeout"], 120)
        self.assertIs(kwargs["check"], False)
        self.assertNotIn("capture_output", kwargs)
        self.assertEqual(fake.during, [(True, [])])
        self.assertTrue(Path(kwargs["cwd"]).name.startswith("console-probe-"))
        self.assertFalse(Path(kwargs["cwd"]).exists())

    def test_run_probe_reports_each_failure_by_its_kind(self):
        cases = [("not_installed", Recorder(error=FileNotFoundError("claude-account"))),
                 ("timed_out", Recorder(error=subprocess.TimeoutExpired(["x"], 120))),
                 ("unavailable", Recorder(error=PermissionError("denied"))),
                 ("exited", Recorder(returncode=3))]
        for kind, fake in cases:
            with self.subTest(kind=kind):
                with self.assertRaises(probe.ProbeFailed) as raised:
                    probe.run_probe(Probe("work", SID), run=fake, environ=ENVIRON)
                self.assertEqual(raised.exception.kind, kind)
                self.assertEqual(str(raised.exception), kind)
        self.assertIsNone(probe.run_probe(Probe("work", SID), run=Recorder(), environ=ENVIRON))

    def test_run_probe_opens_no_credential_file(self):
        HITS.clear()
        ARMED.set()
        try:
            probe.run_probe(Probe("work", SID), run=Recorder(), environ=ENVIRON)
        finally:
            ARMED.clear()

        self.assertEqual(HITS, [])

    def test_the_prober_is_linux_only(self):
        self.assertIs(probe.prober_for("linux"), probe.run_probe)
        self.assertIsNone(probe.prober_for("darwin"))

    @unittest.skipUnless(sys.platform.startswith("linux"), "reads /proc")
    def test_a_timed_out_probe_leaves_no_process_behind(self):
        with tempfile.TemporaryDirectory() as home:
            launcher = Path(home) / ".agents" / "bin" / "claude-account"
            launcher.parent.mkdir(parents=True)
            launcher.write_text(
                f"#!{sys.executable}\n"
                "import os, subprocess, sys\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
                "open(os.environ['PROBE_TEST_PIDFILE'], 'w').write(str(child.pid))\n"
                "child.wait()\n")
            launcher.chmod(0o755)
            pidfile = Path(home) / "child.pid"
            environ = {"HOME": home, "PATH": os.environ["PATH"],
                       "PROBE_TEST_PIDFILE": str(pidfile)}

            with self.assertRaises(probe.ProbeFailed) as raised:
                probe.run_probe(Probe("work", SID), environ=environ, timeout=2)

            self.assertEqual(raised.exception.kind, "timed_out")
            self.assertTrue(pidfile.exists())
            pid = int(pidfile.read_text())

            def kill_child():
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.addCleanup(kill_child)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and self.alive(pid):
                time.sleep(0.05)
            self.assertFalse(self.alive(pid), f"child {pid} outlived the probe's timeout")

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            return False
        return state != "Z"

    def test_one_group_killing_runner_serves_nudges_and_probes(self):
        for function in (probe.run_probe, nudge.run_nudge, nudge.read_full_entries,
                         nudge.read_full_listing):
            with self.subTest(function=function.__name__):
                self.assertIs(inspect.signature(function).parameters["run"].default,
                              manager.run_in_own_group)
        self.assertFalse(hasattr(nudge, "run_in_own_group"))


class DueTest(unittest.TestCase):
    def test_due_profiles_table(self):
        t = 1794000000.0
        rows = [(set(), {}, t + 29, []),
                (set(), {}, t + 30, ["a", "b"]),
                (set(), {"a": t + 30}, t + 629, ["b"]),
                (set(), {"a": t + 30, "b": t + 30}, t + 629, []),
                (set(), {"a": t + 30, "b": t + 30}, t + 630, ["a", "b"]),
                ({"a"}, {"a": t + 30, "b": t + 30}, t + 630, ["b"])]
        for in_flight, last_started, now, expected in rows:
            with self.subTest(in_flight=in_flight, last_started=last_started, now=now):
                self.assertEqual(
                    probe.due_profiles({"b", "a"}, in_flight, last_started, t, now), expected)
        self.assertEqual((probe.PROBE_SECONDS, probe.PROBE_FIRST_SECONDS, probe.PROBE_TIMEOUT,
                          probe.PROBE_MEMORY), (600, 30, 120, 256))


if __name__ == "__main__":
    unittest.main()
