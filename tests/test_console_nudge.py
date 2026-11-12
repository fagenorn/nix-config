"""The nudge commands: the relay and the wake that tell a manager to read its inbox (#889).

Run: just agent-workflow-tests
"""
import dataclasses
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import manager
from agent_tools.console.nudge import (NUDGE_TEXT, RELAY, WAKE, Nudge, NudgeFailed, nudge_command,
                                       nudger_for, run_nudge)

SID = "a" * 16
NAME = "owner/p01 sprint " + SID


class NudgeCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def nudge(self, route=RELAY, session_id="s-1", root=None):
        return Nudge(SID, route, NAME, session_id, "work", self.root if root is None else root)

    def fake(self, stdout="", returncode=0, stderr=b"", raises=None):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if raises is not None:
                raise raises
            if hasattr(kwargs["stdout"], "write"):
                kwargs["stdout"].write(stdout.encode())
            kwargs["stderr"].write(stderr)
            return subprocess.CompletedProcess(argv, returncode)
        run.calls = calls
        return run

    def test_the_relay_command_sends_the_fixed_sentence_to_the_session_by_name(self):
        argv = nudge_command(self.nudge(RELAY), "linux")
        prompt = ('Use the SendMessage tool exactly once, to the peer session named "' + NAME
                  + '", with this message and nothing else: ' + NUDGE_TEXT
                  + " Then print SENT on its own line if the tool reported the message sent "
                    "or accepted, otherwise print FAILED.")
        self.assertEqual(
            ["claude-account", "run", "-p", "--allowedTools", "SendMessage",
             "--no-session-persistence", prompt], argv)
        self.assertIn(NUDGE_TEXT, argv[-1])
        self.assertIn('"owner/p01 sprint ' + SID + '"', argv[-1])
        self.assertEqual(
            'The owner left you a message on the console. Run "sprint inbox" now and act on '
            "what it returns.", NUDGE_TEXT)

    def test_the_wake_command_resumes_the_session_in_place_in_its_own_scope(self):
        self.assertEqual(
            ["systemd-run", "--user", "--scope", "--quiet", "--collect",
             "--description=agent manager " + NAME, "--", "claude-account", "run",
             "--resume", "s-1", "--bg", NUDGE_TEXT],
            nudge_command(self.nudge(WAKE), "linux"))

    def test_there_is_no_command_off_linux(self):
        self.assertIsNone(nudge_command(self.nudge(RELAY), "darwin"))

    def test_no_argv_element_or_environment_value_carries_anything_but_the_fixed_sentence(self):
        self.assertEqual(
            {"sprint_id", "route", "session_name", "session_id", "profile", "cwd"},
            {f.name for f in dataclasses.fields(Nudge)})
        environ = {"HOME": "/h", "PATH": "/bin", "CONSOLE_SPRINT_SECRET": "x",
                   "CONSOLE_SPRINT_ID": SID, "CLAUDE_CONFIG_DIR": "/c"}
        for route in (RELAY, WAKE):
            run = self.fake(stdout="SENT\n")
            run_nudge(self.nudge(route), platform="linux", run=run, environ=environ)
            self.assertEqual(1, len(run.calls))
            argv, kwargs = run.calls[0]
            env = kwargs["env"]
            self.assertEqual("work", env["CLAUDE_ACCOUNT"])
            self.assertEqual("/h/.agents/bin:/bin", env["PATH"])
            for dropped in ("CONSOLE_SPRINT_SECRET", "CONSOLE_SPRINT_ID", "CLAUDE_CONFIG_DIR"):
                self.assertNotIn(dropped, env)
            for value in env.values():
                self.assertNotIn(NUDGE_TEXT, value)

    def test_a_relay_is_delivered_only_when_it_prints_sent(self):
        run_nudge(self.nudge(RELAY), platform="linux", environ={},
                  run=self.fake(stdout="working...\nSENT\n"))
        with self.assertRaises(NudgeFailed) as raised:
            run_nudge(self.nudge(RELAY), platform="linux", environ={},
                      run=self.fake(stdout="FAILED\n"))
        self.assertEqual("the relay did not confirm the message", str(raised.exception))

    def test_failures_are_one_line_reasons(self):
        def reason(nudge, platform="linux", **fake):
            run = self.fake(**fake)
            with self.assertRaises(NudgeFailed) as raised:
                run_nudge(nudge, platform=platform, environ={}, run=run)
            return str(raised.exception), run

        self.assertEqual(manager.UNAVAILABLE_TEXT, reason(self.nudge(), "darwin")[0])
        gone = str(Path(self.root) / "missing")
        self.assertEqual(f"the project root {gone} is not a directory",
                         reason(self.nudge(root=gone))[0])
        self.assertEqual("claude-account is not installed",
                         reason(self.nudge(RELAY), raises=FileNotFoundError())[0])
        self.assertEqual("systemd-run is not installed",
                         reason(self.nudge(WAKE), raises=FileNotFoundError())[0])
        timeout = subprocess.TimeoutExpired("x", 1)
        self.assertEqual("the nudge did not return within 180 s",
                         reason(self.nudge(RELAY), raises=timeout)[0])
        self.assertEqual("the nudge did not return within 60 s",
                         reason(self.nudge(WAKE), raises=timeout)[0])
        self.assertEqual("last line", reason(self.nudge(WAKE), returncode=1,
                                             stderr=b"a\n\nlast line\n")[0])
        self.assertEqual("the nudge exited 3", reason(self.nudge(WAKE), returncode=3)[0])
        text, run = reason(self.nudge(WAKE, session_id=None))
        self.assertEqual("the manager's session is not known", text)
        self.assertEqual([], run.calls)

    def test_the_runner_never_pipes_and_runs_in_its_own_session(self):
        for route, timeout in ((RELAY, 180), (WAKE, 60)):
            run = self.fake(stdout="SENT\n")
            run_nudge(self.nudge(route), platform="linux", environ={}, run=run)
            kwargs = run.calls[0][1]
            self.assertIs(subprocess.DEVNULL, kwargs["stdin"])
            self.assertNotEqual(subprocess.PIPE, kwargs["stderr"])
            self.assertTrue(hasattr(kwargs["stderr"], "write"))
            if route == RELAY:
                self.assertTrue(hasattr(kwargs["stdout"], "write"))
            else:
                self.assertIs(subprocess.DEVNULL, kwargs["stdout"])
            self.assertIs(True, kwargs["start_new_session"])
            self.assertEqual(self.root, kwargs["cwd"])
            self.assertEqual(timeout, kwargs["timeout"])
            self.assertIs(False, kwargs["check"])

    def test_nudger_for_is_linux_only(self):
        self.assertIs(run_nudge, nudger_for("linux"))
        self.assertIsNone(nudger_for("darwin"))


if __name__ == "__main__":
    unittest.main()
