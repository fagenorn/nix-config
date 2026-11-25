"""`agent_tools.verification.console_release_rerun`: the console-release-rerun verify check."""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import event_log
from agent_tools.verification import console_release_rerun

from tests.test_verify_checks import CHECKS, ROOT, committed_mode, run_from_root
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"


class ConsoleReleaseRerunTest(unittest.TestCase):
    """`console-release-rerun`: a manager's allowed rerun of a release run, after activation."""

    SPRINT = "a" * 16
    SESSION = "manager-session"
    T0 = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
    EMPTY = {"run": None, "release": None, "judged_at": None, "activated_at": None}
    TARGET = {"run": 55, "pr": 9, "head": "c" * 40, "count": 1, "members": [], "release": "push"}

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
        self.open_log("events.sqlite3")

    def open_log(self, name):
        self.log_path = self.dir / name
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

    def judged(self, when, decision="allow", verb="rerun", target=None, sprint=SPRINT, session=SESSION):
        self.append("permit.judged", {"sprint_id": sprint, "session_id": session, "tool_use_id": "t-1",
                                      "repo": None, "verb": verb, "decision": decision, "reason": "",
                                      "target": dict(self.TARGET if target is None else target)}, when)

    def run_check(self, now=timedelta(days=1)):
        with mock.patch.object(console_release_rerun, "_utcnow", lambda: self.T0 + now):
            return console_release_rerun.console_release_rerun(self.shas["S"], log=self.log_path,
                                                               repo_root=self.root)

    def test_an_allowed_rerun_of_a_release_run_after_activation_is_met(self):
        for event in ("pull_request", "push"):
            with self.subTest(event=event):
                self.open_log(f"{event}.sqlite3")
                self.activated()
                self.judged(timedelta(hours=1), target={**self.TARGET, "release": event})
                self.assertEqual(self.run_check(), (0, {
                    "met": True, "verdict": "met", "run": 55, "release": event,
                    "judged_at": (self.T0 + timedelta(hours=1)).isoformat(),
                    "activated_at": self.T0.isoformat()}))

    def test_a_row_that_is_no_allowed_release_rerun_does_not_count(self):
        sprint_target = {k: v for k, v in self.TARGET.items() if k != "release"}
        rows = {
            "deny": {"decision": "deny"},
            "merge": {"verb": "merge"},
            "no release": {"target": sprint_target},
            "schedule": {"target": {**self.TARGET, "release": "schedule"}},
            "string run": {"target": {**self.TARGET, "run": "55"}},
            "no sprint": {"sprint": None},
            "no session": {"session": None},
        }
        for name, kwargs in rows.items():
            with self.subTest(row=name):
                self.open_log(f"{name.replace(' ', '-')}.sqlite3")
                self.activated()
                self.judged(timedelta(hours=1), **kwargs)
                self.assertEqual(self.run_check(), (75, {"met": False, "verdict": "not_yet", **self.EMPTY}))

    def test_the_window_is_twenty_one_days_from_activation(self):
        late = timedelta(days=22)
        self.activated()
        self.judged(-timedelta(hours=1))
        self.assertEqual(self.run_check(late), (1, {"met": False, "verdict": "not_met", **self.EMPTY}))
        self.open_log("after.sqlite3")
        self.activated()
        self.judged(timedelta(days=21, seconds=1))
        self.assertEqual(self.run_check(late)[0], 1)
        self.open_log("edge.sqlite3")
        self.activated()
        self.judged(timedelta(days=21))
        self.assertEqual(self.run_check(late)[0], 0)
        self.open_log("none.sqlite3")
        self.judged(timedelta(hours=1))
        self.assertEqual(self.run_check(late)[0], 75)

    def test_the_committed_wrapper_runs_this_check(self):
        script = f"{CHECKS}/console-release-rerun"
        self.assertEqual(committed_mode(script), "100755")
        for event in ("pull_request", "push"):
            with self.subTest(event=event):
                self.open_log(f"wrapper-{event}.sqlite3")
                self.activated()
                self.judged(timedelta(hours=1), target={**self.TARGET, "run": 56, "release": event})
                result = run_from_root([str(ROOT / script), "--since", self.shas["S"],
                                        "--log", str(self.log_path), "--repo-root", str(self.root)])
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual((report["run"], report["release"]), (56, event))
        self.assertEqual(run_from_root([str(ROOT / script), "--since", "x"]).returncode, 2)


if __name__ == "__main__":
    unittest.main()
