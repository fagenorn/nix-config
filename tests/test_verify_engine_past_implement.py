"""`verify_checks.past_implement_verdict` and the `engine-direct-past-implement` wrapper: the first
direct-lane engine delivery after activation got past `implement` within two days."""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_tools.console import event_log
from agent_tools.verification import verify_checks

from tests.test_verify_checks import CHECKS, committed_mode, run_from_root

TIER = "integration"

WRAPPER = f"{CHECKS}/engine-direct-past-implement"
ANCHOR = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
HOUR, DAY = timedelta(hours=1), timedelta(days=1)


def stamp(offset):
    return (ANCHOR + offset).strftime("%Y-%m-%dT%H:%M:%SZ")


def met_events(entered=2 * HOUR):
    return [
        ("step_entered", "preflight", HOUR, {}),
        ("step_entered", "implement", HOUR, {}),
        ("outcome_graded", "implement", HOUR, {"outcome": "done"}),
        ("transition_taken", "implement", HOUR, {"outcome": "done", "to": "implemented"}),
        ("outcome_graded", "implemented", HOUR, {"outcome": "lite"}),
        ("transition_taken", "implemented", HOUR, {"outcome": "lite", "to": "lite-group"}),
        ("step_entered", "lite-group", entered, {}),
    ]


def blocked_events():
    return [
        ("step_entered", "preflight", HOUR, {}),
        ("step_entered", "implement", HOUR, {}),
        ("outcome_graded", "implement", HOUR, {"outcome": "blocked"}),
        ("transition_taken", "implement", HOUR, {"outcome": "blocked", "to": "implemented"}),
        ("outcome_graded", "implemented", HOUR, {"outcome": "task"}),
        ("transition_taken", "implemented", HOUR, {"outcome": "task", "to": "task"}),
        ("stop_reached", "task", HOUR, {"stop": "task", "need": "owner"}),
    ]


def write_run(root, run_id, started, events, procedure="direct", implement_result=None):
    run = Path(root) / run_id
    (run / "results").mkdir(parents=True)
    (run / "run.json").write_text(json.dumps(
        {"procedure": procedure, "run": run_id, "started": stamp(started)}), encoding="utf-8")
    lines = [json.dumps({"event": event, "step": step, "at": stamp(at), **extra})
             for event, step, at, extra in events]
    (run / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if implement_result is not None:
        (run / "results" / "implement.1.json").write_text(json.dumps(implement_result), encoding="utf-8")


class PastImplementVerdictTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def verdict(self, now):
        return verify_checks.past_implement_verdict(self.root, ANCHOR, ANCHOR + now)

    def test_the_first_direct_delivery_after_activation_that_entered_a_review_step_in_time_is_met(self):
        write_run(self.root, "1919-20261127T100000Z-ab12", HOUR, met_events())
        code, report = self.verdict(3 * HOUR)
        self.assertEqual(code, 0)
        self.assertTrue(report["met"])
        self.assertEqual(report["verdict"], "met")
        self.assertEqual(report["run"], "1919-20261127T100000Z-ab12")
        self.assertEqual(report["implement"], "done")
        self.assertEqual(report["entered"], "lite-group")
        self.assertEqual(report["at"], stamp(2 * HOUR))
        self.assertEqual(report["anchor"], stamp(timedelta(0)))

    def test_a_blocked_implement_reply_is_not_met(self):
        write_run(self.root, "a", HOUR, blocked_events())
        code, report = self.verdict(HOUR)
        self.assertEqual(code, 1)
        self.assertEqual(report["verdict"], "not_met")
        self.assertEqual(report["implement"], "blocked")

    def test_decide_step_events_alone_are_not_yet(self):
        write_run(self.root, "a", HOUR, met_events()[:-1])
        code, report = self.verdict(3 * HOUR)
        self.assertEqual(code, 75)
        self.assertEqual(report["verdict"], "not_yet")
        self.assertIsNone(report["entered"])

    def test_a_run_stopped_at_implement_waits_until_the_window_ends(self):
        write_run(self.root, "a", HOUR, [
            ("step_entered", "preflight", HOUR, {}),
            ("step_entered", "implement", HOUR, {}),
            ("stop_reached", "tool-denied", HOUR, {"stop": "tool-denied", "need": "owner"}),
        ])
        self.assertEqual(self.verdict(HOUR)[0], 75)
        self.assertEqual(self.verdict(3 * DAY)[0], 1)

    def test_a_first_delivery_that_faulted_before_implement_is_the_one_judged(self):
        write_run(self.root, "a", HOUR, [("step_entered", "preflight", HOUR, {})])
        write_run(self.root, "b", 5 * HOUR, met_events(entered=6 * HOUR))
        code, report = self.verdict(7 * HOUR)
        self.assertEqual(code, 75)
        self.assertEqual(report["run"], "a")
        self.assertIsNone(report["implement"])
        self.assertIsNone(report["entered"])

    def test_a_first_delivery_that_never_entered_implement_is_not_met_when_the_window_ends(self):
        write_run(self.root, "a", HOUR, [("step_entered", "preflight", HOUR, {})])
        write_run(self.root, "b", 5 * HOUR, met_events(entered=6 * HOUR))
        code, report = self.verdict(3 * DAY)
        self.assertEqual(code, 1)
        self.assertEqual(report["verdict"], "not_met")
        self.assertEqual(report["run"], "a")

    def test_an_old_success_before_activation_is_not_counted(self):
        write_run(self.root, "a", -DAY, met_events())
        code, report = self.verdict(3 * HOUR)
        self.assertEqual(code, 75)
        self.assertIsNone(report["run"])

    def test_a_first_delivery_that_stalls_is_not_met_whatever_comes_after(self):
        write_run(self.root, "a", HOUR, blocked_events())
        write_run(self.root, "b", 5 * HOUR, met_events(entered=6 * HOUR))
        code, report = self.verdict(DAY)
        self.assertEqual(code, 1)
        self.assertEqual(report["run"], "a")

    def test_a_late_entry_is_not_met(self):
        write_run(self.root, "a", HOUR, met_events(entered=2 * DAY + timedelta(minutes=1)))
        code, report = self.verdict(3 * DAY)
        self.assertEqual(code, 1)
        self.assertEqual(report["verdict"], "not_met")

    def test_an_ineligible_delivery_is_skipped(self):
        write_run(self.root, "a", HOUR, [
            ("step_entered", "preflight", HOUR, {}),
            ("step_entered", "implement", HOUR, {}),
            ("outcome_graded", "implement", HOUR, {"outcome": "blocked"}),
            ("stop_reached", "ineligible", HOUR, {"stop": "ineligible", "need": "owner"}),
        ], implement_result={"ineligible": True, "status": "blocked"})
        write_run(self.root, "b", 2 * HOUR, met_events(entered=3 * HOUR))
        code, report = self.verdict(DAY)
        self.assertEqual(code, 0)
        self.assertEqual(report["run"], "b")

    def test_another_procedure_is_not_counted(self):
        write_run(self.root, "a", HOUR, met_events(), procedure="deliver")
        self.assertEqual(self.verdict(3 * HOUR)[0], 75)


class EngineDirectPastImplementTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.repo = self.dir / "repo"
        self.repo.mkdir()
        self.runs = self.dir / "runs"
        self.runs.mkdir()
        self.shas = {}
        self.git("init", "-q")
        for name in ("S", "C"):
            self.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                     "commit", "-q", "--allow-empty", "-m", name)
            self.shas[name] = self.git("rev-parse", "HEAD").strip()
        self.store = self.dir / "events.sqlite3"

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True,
                              check=True).stdout

    def activate(self, *, ok=True):
        log = event_log.EventLog(self.store, clock=lambda: ANCHOR.isoformat(timespec="microseconds"))
        self.addCleanup(log._connection.close)
        log.append([("activation.finished", None, {"root": "/r", "commit": self.shas["C"], "ok": ok,
                                                   "reason": None, "next_step": None})])

    def test_no_qualifying_activation_is_not_yet(self):
        write_run(self.runs, "a", HOUR, met_events())
        self.activate(ok=False)
        code, report = verify_checks.engine_direct_past_implement(
            self.shas["S"], runs_root=self.runs, log=self.store, repo_root=self.repo,
            now=ANCHOR + 3 * HOUR)
        self.assertEqual(code, 75)
        self.assertEqual(report["verdict"], "not_yet")
        self.assertIsNone(report["anchor"])

    def test_the_staged_wrapper_runs_from_the_root(self):
        self.assertEqual(committed_mode(WRAPPER), "100755")
        self.activate()
        argv = [WRAPPER, "--since", self.shas["S"], "--runs-root", str(self.runs), "--log", str(self.store),
                "--repo-root", str(self.repo)]
        write_run(self.runs, "a", HOUR, met_events())
        met = run_from_root(argv)
        self.assertEqual(met.returncode, 0, met.stderr)
        self.assertTrue(json.loads(met.stdout)["met"])
        shutil.rmtree(self.runs / "a")
        self.assertEqual(run_from_root(argv).returncode, 75)


if __name__ == "__main__":
    unittest.main()
