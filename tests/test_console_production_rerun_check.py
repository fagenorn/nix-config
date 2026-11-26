"""`agent_tools.verification.console_production_rerun`: the console-production-rerun verify check."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools.console import event_log
from agent_tools.system import forge_api
from agent_tools.verification import console_production_rerun
from agent_tools.verification.verify_checks import ToolError

from tests.test_verify_checks import CHECKS, ROOT, committed_mode, run_from_root
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"

RULE = {"id": "deploy-rerun", "argv": ["gh", "run", "rerun"]}


class Attempts:
    """A fake `read_attempts` that answers fixed start times and records its calls."""

    def __init__(self, *starts):
        self.starts = starts
        self.calls = []

    def __call__(self, slug, run):
        self.calls.append((slug, run))
        return list(self.starts)


class ConsoleProductionRerunTest(unittest.TestCase):
    """`console-production-rerun`: a manager's allowed, run rerun of its own pull request's check run."""

    SPRINT = "a" * 16
    SESSION = "manager-session"
    T0 = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
    HOUR = timedelta(hours=1)
    EMPTY = {"run": None, "pr": None, "judged_at": None, "landed_at": None, "attempt_started_at": None,
             "activated_at": None}
    TARGET = {"run": 55, "pr": 7, "head": "c" * 40, "count": 1, "members": []}

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

    def judged(self, when, decision="allow", verb="rerun", target=None, sprint=SPRINT, session=SESSION,
               repo="acme/deployer", call="t-1", rule=RULE):
        payload = {"sprint_id": sprint, "session_id": session, "tool_use_id": call, "repo": repo,
                   "verb": verb, "decision": decision, "reason": "",
                   "target": dict(self.TARGET if target is None else target), "rule": rule}
        if call is None:
            del payload["tool_use_id"]
        self.append("permit.judged", payload, when)

    def landed(self, when=HOUR + timedelta(seconds=20), **changes):
        payload = {"sprint_id": self.SPRINT, "session_id": self.SESSION, "tool_use_id": "t-1",
                   "repo": "acme/deployer", "verb": "rerun", "target": {"run": 55}, **changes}
        self.append("permit.landed", payload, when)

    def run_check(self, reader, now=timedelta(days=1)):
        with mock.patch.object(console_production_rerun, "_utcnow", lambda: self.T0 + now):
            return console_production_rerun.console_production_rerun(
                self.shas["S"], log=self.log_path, repo_root=self.root, read_attempts=reader)

    def met(self):
        return (0, {"met": True, "verdict": "met", "run": 55, "pr": 7,
                    "judged_at": (self.T0 + self.HOUR).isoformat(),
                    "landed_at": (self.T0 + self.HOUR + timedelta(seconds=20)).isoformat(),
                    "attempt_started_at": self.started().isoformat(),
                    "activated_at": self.T0.isoformat()})

    def started(self, seconds=30):
        return self.T0 + self.HOUR + timedelta(seconds=seconds)

    def not_yet(self):
        return 75, {"met": False, "verdict": "not_yet", **self.EMPTY}

    def test_an_allowed_own_pull_request_rerun_that_ran_in_a_declaring_project_after_activation_is_met(self):
        self.activated()
        self.judged(self.HOUR)
        self.landed()
        reader = Attempts(self.started())
        self.assertEqual(self.run_check(reader), self.met())
        self.assertEqual(reader.calls, [("acme/deployer", 55)])
        with self.subTest(rule="a program path and a mixed-case slug"):
            self.open_log("path.sqlite3")
            self.activated()
            self.judged(self.HOUR, repo="ACME/Deployer", rule={"id": "d", "argv": ["/usr/bin/gh", "run", "rerun"]})
            self.landed(repo="ACME/Deployer")
            self.assertEqual(self.run_check(Attempts(self.started())), self.met())

    def test_a_row_that_is_no_allowed_and_run_own_rerun_of_a_declaring_project_does_not_count(self):
        no_pr = {k: v for k, v in self.TARGET.items() if k != "pr"}
        # name: (judged changes, landed changes or None for no landing, attempt start seconds
        # or None for no attempt, whether the reader may be called)
        cases = {
            "deny": ({"decision": "deny"}, {}, 30, False),
            "merge verb": ({"verb": "merge"}, {}, 30, False),
            "release target": ({"target": {**self.TARGET, "release": "pull_request"}}, {}, 30, False),
            "no pr": ({"target": no_pr}, {}, 30, False),
            "string run": ({"target": {**self.TARGET, "run": "55"}}, {}, 30, False),
            "no sprint": ({"sprint": None}, {"sprint_id": None}, 30, False),
            "no session": ({"session": None}, {"session_id": None}, 30, False),
            "no repo": ({"repo": None}, {"repo": None}, 30, False),
            "no rule recorded": ({"rule": None}, {}, 30, False),
            "gh run only": ({"rule": {"id": "d", "argv": ["gh", "run"]}}, {}, 30, False),
            "another program": ({"rule": {"id": "d", "argv": ["glab", "run", "rerun"]}}, {}, 30, False),
            "a rule that is no entry": ({"rule": "gh run rerun"}, {}, 30, False),
            "an argv of non-words": ({"rule": {"id": "d", "argv": ["gh", 1, "rerun"]}}, {}, 30, False),
            "refused by the guard, rerun by hand": ({}, None, 54, False),
            "no call id": ({"call": None}, {"tool_use_id": None}, 30, False),
            "landed by another call": ({}, {"tool_use_id": "t-2"}, 30, False),
            "landed by another session": ({}, {"session_id": "s-2"}, 30, False),
            "landed in another sprint": ({}, {"sprint_id": "b" * 16}, 30, False),
            "landed for another repository": ({}, {"repo": "acme/other"}, 30, False),
            "landed for another run": ({}, {"target": {"run": 56}}, 30, False),
            "landed merge": ({}, {"verb": "merge", "target": {"run": 55, "pr": 7, "head": "c" * 40}}, 30, False),
            "landed before the verdict": ({}, {"when": self.HOUR - timedelta(seconds=1)}, 30, False),
            "no new attempt": ({}, {}, None, True),
            "attempt before the verdict": ({}, {}, -120, True),
            "attempt too late": ({}, {}, 16 * 60, True),
        }
        for name, (judged, landed, seconds, may_read) in cases.items():
            with self.subTest(row=name):
                self.open_log(f"{name.replace(' ', '-').replace(',', '')}.sqlite3")
                self.activated()
                self.judged(self.HOUR, **judged)
                if landed is not None:
                    self.landed(**landed)
                reader = Attempts() if seconds is None else Attempts(self.started(seconds))
                self.assertEqual(self.run_check(reader), self.not_yet())
                if not may_read:
                    self.assertEqual(reader.calls, [])

    def test_the_committed_wrapper_runs_this_check(self):
        script = f"{CHECKS}/console-production-rerun"
        self.assertEqual(committed_mode(script), "100755")
        self.assertTrue(os.access(ROOT / script, os.X_OK))
        result = run_from_root([str(ROOT / script), "--since", self.shas["S"], "--log", str(self.log_path),
                                "--repo-root", str(self.root)])
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(json.loads(result.stdout)["verdict"], "not_yet")
        self.assertEqual(run_from_root([str(ROOT / script), "--since", "x"]).returncode, 2)

    def test_the_window_is_twenty_one_days_from_activation(self):
        late = timedelta(days=22)

        def one(name, judged_at, landed_at=None):
            self.open_log(f"{name}.sqlite3")
            self.activated()
            self.judged(judged_at)
            self.landed(judged_at if landed_at is None else landed_at)
            return self.run_check(Attempts(self.T0 + judged_at + timedelta(seconds=30)), late)

        self.assertEqual(one("before", -self.HOUR), (1, {"met": False, "verdict": "not_met", **self.EMPTY}))
        self.assertEqual(one("after", timedelta(days=21, seconds=1))[0], 1)
        self.assertEqual(one("edge", timedelta(days=21, seconds=-60))[0], 0)
        self.assertEqual(one("attempt after the window", timedelta(days=21))[0], 1)
        self.assertEqual(one("landed late", timedelta(days=21, seconds=-10), timedelta(days=21, seconds=1))[0], 1)
        self.open_log("none.sqlite3")
        self.judged(self.HOUR)
        self.landed()
        self.assertEqual(self.run_check(Attempts(self.started()), late)[0], 75)

    def test_a_paired_rerun_the_forge_no_longer_has_is_skipped_and_a_later_one_is_examined(self):
        self.activated()
        self.judged(self.HOUR, call="t-1", target={**self.TARGET, "run": 54})
        self.landed(target={"run": 54})
        self.judged(2 * self.HOUR, call="t-2")
        self.landed(2 * self.HOUR + timedelta(seconds=20), tool_use_id="t-2")
        started = (self.T0 + 2 * self.HOUR + timedelta(seconds=30)).isoformat()

        def api_get(path, allow=(), cli="gh"):
            if path.endswith("/runs/54"):
                if 404 not in allow:
                    raise forge_api.ForgeError("gh_failed", "HTTP 404")
                return None
            if path.endswith("/runs/55"):
                return {"run_attempt": 2}
            return {"run_started_at": started}

        with mock.patch.object(forge_api, "api_get", api_get):
            code, report = self.run_check(console_production_rerun.attempt_starts)
        self.assertEqual((code, report["verdict"], report["run"]), (0, "met", 55))

    def test_an_unreadable_forge_is_a_tool_failure(self):
        self.activated()
        self.judged(self.HOUR)
        self.landed()
        failures = {
            "unreachable": mock.patch.object(forge_api, "api_get",
                                             side_effect=forge_api.ForgeError("unreachable", "x")),
            "mistyped attempt": mock.patch.object(forge_api, "api_get", return_value={"run_attempt": "2"}),
        }
        for name, patch in failures.items():
            with self.subTest(forge=name), patch:
                with self.assertRaises(ToolError) as caught:
                    console_production_rerun.console_production_rerun(
                        self.shas["S"], log=self.log_path, repo_root=self.root)
                self.assertEqual(caught.exception.kind, "forge_unreadable")
                self.assertEqual(console_production_rerun.main(
                    ["--since", self.shas["S"], "--log", str(self.log_path), "--repo-root", str(self.root)]), 2)


if __name__ == "__main__":
    unittest.main()
