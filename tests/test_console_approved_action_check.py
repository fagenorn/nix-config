"""`agent_tools.verification.console_approved_action`: the console-approved-action verify check."""
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import event_log
from agent_tools.verification import console_approved_action

from tests.test_verify_checks import CHECKS, ROOT, committed_mode, run_from_root


class ConsoleApprovedActionTest(unittest.TestCase):
    """`console-approved-action`: a manager ran an action the owner approved, from its own session."""

    SPRINT = "a" * 16
    SESSION = "manager-session"
    T0 = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
    EMPTY = {"round": None, "index": None, "judged_at": None, "landed_at": None, "activated_at": None}

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.root = self.dir / "repo"
        self.root.mkdir()
        self.shas = {}
        self.git("init", "-q")
        for name in ("P", "S", "C"):
            self.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                     "commit", "-q", "--allow-empty", "-m", name)
            self.shas[name] = self.git("rev-parse", "HEAD").strip()
        self.at = self.T0
        self.log_path = self.dir / "events.sqlite3"
        self.log = event_log.EventLog(self.log_path, clock=lambda: self.at.isoformat(timespec="microseconds"))
        self.addCleanup(self.log._connection.close)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True,
                              check=True).stdout

    def append(self, kind, payload, when):
        self.at = self.T0 + when
        self.log.append([(kind, None, payload)])

    def activated(self):
        self.append("activation.finished", {"root": "/r", "commit": self.shas["C"], "ok": True,
                                            "reason": None, "next_step": None}, timedelta(0))

    def seen(self, name=None):
        self.append("session.seen", {"session_id": self.SESSION, "cwd": "/r", "repo": None, "state": "idle",
                                     "name": name or f"owner/p00 sprint {self.SPRINT}"}, timedelta(0))

    def permit(self, kind, when, call="t-1", index=0, verb="action"):
        payload = {"sprint_id": self.SPRINT, "session_id": self.SESSION, "tool_use_id": call, "repo": None,
                   "verb": verb, "target": {"round": 41, "index": index}}
        if kind == "permit.judged":
            payload.update(decision="allow", reason="")
        self.append(kind, payload, when)

    def run_check(self, now=timedelta(days=1)):
        with mock.patch.object(console_approved_action, "_utcnow", lambda: self.T0 + now):
            return console_approved_action.console_approved_action(self.shas["S"], log=self.log_path, repo_root=self.root)

    def test_an_approved_action_the_managers_own_call_ran_is_met(self):
        self.activated()
        self.seen()
        self.permit("permit.judged", timedelta(hours=1))
        self.permit("permit.landed", timedelta(hours=1, seconds=5))
        self.assertEqual(self.run_check(), (0, {
            "met": True, "verdict": "met", "round": 41, "index": 0,
            "judged_at": (self.T0 + timedelta(hours=1)).isoformat(),
            "landed_at": (self.T0 + timedelta(hours=1, seconds=5)).isoformat(),
            "activated_at": self.T0.isoformat()}))

    def test_no_activation_containing_the_change_is_not_yet(self):
        self.seen()
        self.permit("permit.judged", timedelta(hours=1))
        self.permit("permit.landed", timedelta(hours=1, seconds=5))
        self.assertEqual(self.run_check(), (75, {"met": False, "verdict": "not_yet", **self.EMPTY}))

    def test_an_allow_that_never_landed_waits_then_fails(self):
        self.activated()
        self.seen()
        self.permit("permit.judged", timedelta(hours=1))
        self.assertEqual(self.run_check(timedelta(days=2)),
                         (75, {"met": False, "verdict": "not_yet", **self.EMPTY}))
        self.assertEqual(self.run_check(timedelta(days=31)),
                         (1, {"met": False, "verdict": "not_met", **self.EMPTY}))

    def test_another_call_or_a_session_no_sprint_names_does_not_count(self):
        hour, landed = timedelta(hours=1), timedelta(hours=1, seconds=5)

        def other_call():
            self.permit("permit.judged", hour)
            self.permit("permit.landed", landed, call="t-2")

        def other_index():
            self.permit("permit.judged", hour)
            self.permit("permit.landed", landed, index=1)

        def other_verb():
            self.permit("permit.judged", hour, verb="merge")
            self.permit("permit.landed", landed, verb="merge")

        def unnamed_session():
            self.seen(name="owner/p00 notes")
            self.permit("permit.judged", hour)
            self.permit("permit.landed", landed)

        def outside_window():
            self.permit("permit.judged", -hour)
            self.permit("permit.landed", -hour + timedelta(seconds=5))

        for case in (other_call, other_index, other_verb, unnamed_session, outside_window):
            with self.subTest(case=case.__name__):
                self.setUp()
                self.activated()
                if case is not unnamed_session:
                    self.seen()
                case()
                self.assertEqual(self.run_check()[0], 75)

    def test_the_script_is_committed_executable_and_runs_the_check(self):
        script = f"{CHECKS}/console-approved-action"
        self.assertEqual(committed_mode(script), "100755")
        result = run_from_root([str(ROOT / script), "--since", "x"])
        self.assertEqual(result.returncode, 2, result.stderr)
