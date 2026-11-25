"""`agent_tools.verification.console_takeover_merge`: the console-takeover-merge verify check."""
import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import event_log
from agent_tools.verification import console_takeover_merge

from tests.test_verify_checks import CHECKS, ROOT, committed_mode, run_from_root
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"

SPRINT = "a" * 16
TAKEOVER = "bbbbbbbb-2222-4222-8222-222222222222"
OTHER = "cccccccc-3333-4333-8333-333333333333"
T0 = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
DAY, HOUR = timedelta(days=1), timedelta(hours=1)
NOT_MET = {"met": False, "verdict": "not_met", "judged_at": None, "started_at": None, "activated_at": None}
NOT_YET = {**NOT_MET, "verdict": "not_yet"}


class ConsoleTakeoverMergeTest(unittest.TestCase):
    """`console-takeover-merge`: a takeover manager the console launched had its own merge allowed."""

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
        self.at = T0
        self.log_path = self.dir / "events.sqlite3"
        self.log = event_log.EventLog(self.log_path, clock=lambda: self.at.isoformat(timespec="microseconds"))
        self.addCleanup(self.log._connection.close)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True,
                              check=True).stdout

    def append(self, kind, payload, when):
        self.at = T0 + when
        self.log.append([(kind, None, payload)])

    def activated(self, commit="C", ok=True, when=timedelta(0)):
        self.append("activation.finished", {"root": "/r", "commit": self.shas[commit], "ok": ok,
                                            "reason": None, "next_step": None}, when)

    def started(self, when, takeover=True, short_id="bbbbbbbb", sprint=SPRINT):
        payload = {"sprint_id": sprint, "profile": "home", "session_name": "p00 sprint " + sprint,
                   "seen_after": 0}
        if takeover:
            payload["takeover"] = True
        if short_id is not None:
            payload["short_id"] = short_id
        self.append("manager.started", payload, when)

    def judged(self, when, session=TAKEOVER, decision="allow", verb="merge", sprint=SPRINT):
        self.append("permit.judged", {"sprint_id": sprint, "session_id": session, "tool_use_id": "t-1",
                                      "repo": "o/r", "verb": verb, "decision": decision, "reason": "",
                                      "target": {"pr": 7, "head": "b" * 40}}, when)

    def run_check(self, now, *argv):
        out = io.StringIO()
        with mock.patch.object(console_takeover_merge, "_utcnow", return_value=T0 + now), \
                contextlib.redirect_stdout(out):
            code = console_takeover_merge.main(["--since", self.shas["S"], "--log", str(self.log_path),
                                                "--repo-root", str(self.root), *argv])
        return code, json.loads(out.getvalue())

    def met_fixture(self):
        self.activated()
        self.started(DAY)
        self.judged(DAY + HOUR)

    def test_an_allowed_merge_by_the_takeover_session_after_activation_is_met(self):
        self.met_fixture()
        code, report = self.run_check(2 * DAY)
        self.assertEqual(code, 0)
        self.assertEqual(report, {"met": True, "verdict": "met",
                                  "judged_at": (T0 + DAY + HOUR).isoformat(),
                                  "started_at": (T0 + DAY).isoformat(), "activated_at": T0.isoformat()})

    def test_a_merge_whose_sprints_latest_start_is_not_a_takeover_is_not_counted(self):
        self.activated()
        self.started(DAY)
        self.started(DAY + timedelta(minutes=30), takeover=False)
        self.judged(DAY + HOUR)
        self.assertEqual(self.run_check(2 * DAY), (75, NOT_YET))
        self.assertEqual(self.run_check(15 * DAY), (1, NOT_MET))

    def test_a_session_the_takeover_did_not_launch_is_not_counted(self):
        self.activated()
        self.started(DAY)
        self.judged(DAY + HOUR, session=OTHER)
        self.assertEqual(self.run_check(2 * DAY), (75, NOT_YET))

    def test_a_takeover_row_without_a_short_id_is_not_counted(self):
        self.activated()
        self.started(DAY, short_id=None)
        self.judged(DAY + HOUR)
        self.assertEqual(self.run_check(2 * DAY), (75, NOT_YET))

    def test_a_denied_merge_or_another_verb_is_not_counted(self):
        for change in ({"decision": "deny"}, {"verb": "rerun"}):
            with self.subTest(change=change):
                self.setUp()
                self.activated()
                self.started(DAY)
                self.judged(DAY + HOUR, **change)
                self.assertEqual(self.run_check(2 * DAY), (75, NOT_YET))

    def test_a_merge_outside_the_window_is_not_counted(self):
        self.activated(when=HOUR)
        self.started(timedelta(0))
        self.judged(timedelta(minutes=30))
        self.started(14 * DAY)
        self.judged(15 * DAY + 2 * HOUR)
        self.assertEqual(self.run_check(16 * DAY), (1, NOT_MET))

    def test_without_an_activation_that_includes_since_it_is_not_yet(self):
        self.activated("P")
        self.activated(ok=False, when=HOUR)
        self.started(DAY)
        self.judged(DAY + HOUR)
        for now in (2 * DAY, 40 * DAY):
            self.assertEqual(self.run_check(now), (75, NOT_YET))

    def test_the_report_names_no_project_sprint_or_session(self):
        self.met_fixture()
        _, report = self.run_check(2 * DAY)
        self.assertEqual(set(report), {"met", "verdict", "judged_at", "started_at", "activated_at"})
        text = json.dumps(report)
        for named in (SPRINT, TAKEOVER, "bbbbbbbb", "o/r"):
            self.assertNotIn(named, text)

    def test_a_bad_since_or_an_unreadable_log_is_2(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            console_takeover_merge.main(["--since", "x"])
        self.assertEqual(raised.exception.code, 2)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = console_takeover_merge.main(["--since", self.shas["S"], "--repo-root", str(self.root),
                                                "--log", str(self.dir / "missing.sqlite3")])
        self.assertEqual(code, 2)
        self.assertTrue(err.getvalue().startswith("verify-checks: log_unreadable:"), err.getvalue())

    def test_the_script_is_committed_executable_and_runs_the_check(self):
        script = f"{CHECKS}/console-takeover-merge"
        self.assertEqual(committed_mode(script), "100755")
        result = run_from_root([str(ROOT / script), "--since", "x"])
        self.assertEqual(result.returncode, 2, result.stderr)
