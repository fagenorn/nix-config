"""`verify_checks.past_setup_verdict` and the `engine-deliver-past-setup` wrapper: the first direct-lane engine
delivery after activation got past setup, a direct child run entering a step within two days."""
import hashlib
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

WRAPPER = f"{CHECKS}/engine-deliver-past-setup"
ANCHOR = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
HOUR, DAY = timedelta(hours=1), timedelta(days=1)


def stamp(offset):
    return (ANCHOR + offset).strftime("%Y-%m-%dT%H:%M:%SZ")


def rid(label):
    """The run id a fixture's short label stands for: the shape the ledger names a run with."""
    return f"1-20261127T090000Z-{hashlib.sha1(label.encode()).hexdigest()[:4]}"


def write_run(root, label, started, events, procedure, parent=None, directory=None, claims=None):
    """Write the run `label` under `root`: in `directory` (default its id) and claiming `claims` (default its id)."""
    run = Path(root) / (directory or rid(label))
    (run / "results").mkdir(parents=True)
    document = {"procedure": procedure, "run": claims or rid(label), "started": stamp(started)}
    if parent is not None:
        document["parent"] = rid(parent)
    (run / "run.json").write_text(json.dumps(document), encoding="utf-8")
    lines = [json.dumps({"event": event, "step": step, "at": stamp(at), **extra})
             for event, step, at, extra in events]
    (run / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def entry(at, **members):
    """A `step_entered` event as the ledger writes it (a step, a visit and a stage), `members` overriding."""
    return ("step_entered", "preflight", at, {"visit": 1, "stage": "setup", **members})


def direct_root_events(started=HOUR):
    return [
        ("step_entered", "start", started, {}),
        ("transition_taken", "lane", started, {"visit": 1, "outcome": "direct", "to": "direct-lane"}),
        ("step_entered", "direct-lane", started, {}),
    ]


def standard_root_events(started=HOUR):
    return [
        ("step_entered", "start", started, {}),
        ("transition_taken", "lane", started, {"visit": 1, "outcome": "standard", "to": "standard-not-on-engine"}),
        ("stop_reached", "standard-not-on-engine", started,
         {"stop": "standard-not-on-engine", "need": "nothing"}),
    ]


def setup_stopped_events(started=HOUR):
    return [
        ("step_entered", "start", started, {}),
        ("stop_reached", "start", started, {"stop": "tool-denied", "need": "owner-decision"}),
    ]


def direct_delivery(root, run_id, started, entered):
    """A direct root `run_id`, its setup child and a direct child that enters `preflight` at `entered`."""
    write_run(root, run_id, started, direct_root_events(started), "deliver")
    write_run(root, f"{run_id}-s", started, [("step_entered", "preflight", started, {})], "setup", parent=run_id)
    events = [] if entered is None else [entry(entered)]
    write_run(root, f"{run_id}-d", started, events, "direct", parent=run_id)


class PastSetupVerdictTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def verdict(self, now):
        return verify_checks.past_setup_verdict(self.root, ANCHOR, ANCHOR + now)

    def test_a_direct_child_that_entered_a_step_in_time_is_met(self):
        write_run(self.root, "r", HOUR, direct_root_events(), "deliver")
        write_run(self.root, "s", HOUR, [("step_entered", "preflight", HOUR, {})], "setup", parent="r")
        write_run(self.root, "d", HOUR, [entry(2 * HOUR)], "direct", parent="r")
        code, report = self.verdict(3 * HOUR)
        self.assertEqual(code, 0)
        self.assertTrue(report["met"])
        self.assertEqual(report["verdict"], "met")
        self.assertEqual(report["run"], rid("r"))
        self.assertEqual(report["lane"], "direct")
        self.assertEqual(report["child"], rid("d"))
        self.assertEqual(report["entered"], "preflight")
        self.assertEqual(report["at"], stamp(2 * HOUR))
        self.assertEqual(report["anchor"], stamp(timedelta(0)))

    def test_the_lane_grade_is_the_transition_the_engine_writes_for_a_decide_step(self):
        write_run(self.root, "r", HOUR, direct_root_events(), "deliver")
        write_run(self.root, "d", HOUR, [entry(2 * HOUR)], "direct", parent="r")
        events =(self.root / rid("r") / "events.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("outcome_graded", events)
        self.assertIn('"event": "transition_taken", "step": "lane"', events)
        code, report = self.verdict(3 * HOUR)
        self.assertEqual((code, report["verdict"], report["lane"]), (0, "met", "direct"))

    def test_a_delivery_started_in_the_activation_second_is_not_before_the_activation(self):
        anchor = ANCHOR + timedelta(milliseconds=250)  # the activation keeps microseconds, a run's start does not
        write_run(self.root, "r", timedelta(0), direct_root_events(timedelta(0)), "deliver")
        write_run(self.root, "d", timedelta(0), [entry(HOUR)], "direct", parent="r")
        code, report = verify_checks.past_setup_verdict(self.root, anchor, ANCHOR + 3 * HOUR)
        self.assertEqual((code, report["verdict"], report["run"]), (0, "met", rid("r")))
        shutil.rmtree(self.root)
        self.root.mkdir()
        write_run(self.root, "r", -timedelta(seconds=1), direct_root_events(-timedelta(seconds=1)), "deliver")
        code, report = verify_checks.past_setup_verdict(self.root, anchor, ANCHOR + 3 * HOUR)
        self.assertEqual((code, report["run"]), (75, None))

    def test_a_delivery_stopped_before_its_lane_is_lane_unknown_and_no_later_one_stands_in(self):
        for standard_issue in (False, True):
            with self.subTest(standard_issue=standard_issue):
                shutil.rmtree(self.root)
                self.root.mkdir()
                write_run(self.root, "r", HOUR, setup_stopped_events(), "deliver")
                write_run(self.root, "r-s", HOUR, [("step_entered", "preflight", HOUR, {})], "setup", parent="r")
                if standard_issue:
                    (self.root / rid("r-s") / "results" / "preflight.1.json").write_text(
                        json.dumps({"issue_text": "a standard-lane issue body"}), encoding="utf-8")
                direct_delivery(self.root, "q", 5 * HOUR, 6 * HOUR)
                for now in (3 * HOUR, 3 * DAY):
                    code, report = self.verdict(now)
                    self.assertEqual(code, 75)
                    self.assertEqual(report["verdict"], "lane_unknown")
                    self.assertEqual(report["run"], rid("r"))
                    self.assertEqual(report["stop"], "tool-denied")
                    self.assertFalse(report["met"])

    def test_a_delivery_still_before_its_lane_is_not_yet_then_lane_unknown(self):
        write_run(self.root, "r", HOUR, [("step_entered", "start", HOUR, {})], "deliver")
        code, report = self.verdict(3 * HOUR)
        self.assertEqual((code, report["verdict"], report["run"]), (75, "not_yet", rid("r")))
        code, report = self.verdict(3 * DAY)
        self.assertEqual((code, report["verdict"], report["run"]), (75, "lane_unknown", rid("r")))

    def test_a_delivery_of_an_issue_not_on_the_direct_lane_is_skipped(self):
        cases = {
            "standard": standard_root_events(HOUR),
            "marked": [("step_entered", "start", HOUR, {}),
                       ("stop_reached", "look-not-on-engine", HOUR,
                        {"stop": "look-not-on-engine", "need": "nothing"})],
        }
        for name, events in cases.items():
            with self.subTest(name):
                shutil.rmtree(self.root)
                self.root.mkdir()
                write_run(self.root, "r", HOUR, events, "deliver")
                direct_delivery(self.root, "q", 2 * HOUR, 3 * HOUR)
                code, report = self.verdict(4 * HOUR)
                self.assertEqual(code, 0)
                self.assertEqual(report["run"], rid("q"))

    def test_a_direct_delivery_whose_child_entered_late_or_never_is_not_met(self):
        direct_delivery(self.root, "r", HOUR, 3 * DAY)
        code, report = self.verdict(4 * DAY)
        self.assertEqual(code, 1)
        self.assertEqual(report["verdict"], "not_met")
        self.assertEqual(report["child"], rid("r-d"))
        shutil.rmtree(self.root)
        self.root.mkdir()
        direct_delivery(self.root, "r", HOUR, None)
        self.assertEqual(self.verdict(3 * HOUR)[0], 75)
        code, report = self.verdict(3 * DAY)
        self.assertEqual(code, 1)
        self.assertEqual(report["verdict"], "not_met")

    def test_a_child_run_or_an_old_run_is_never_a_root(self):
        write_run(self.root, "p", HOUR, direct_root_events(), "deliver", parent="x")
        write_run(self.root, "p-d", HOUR, [entry(2 * HOUR)], "direct", parent="p")
        direct_delivery(self.root, "old", -DAY, -DAY + HOUR)
        code, report = self.verdict(3 * HOUR)
        self.assertEqual(code, 75)
        self.assertEqual(report["verdict"], "not_yet")
        self.assertIsNone(report["run"])


    def test_an_empty_runs_directory_is_not_yet_inside_the_window_and_not_met_once_it_has_passed(self):
        self.assertEqual(self.verdict(3 * HOUR)[0], 75)
        self.assertEqual(self.verdict(2 * DAY)[0], 75)
        code, report = self.verdict(3 * DAY)
        self.assertEqual((code, report["verdict"], report["met"], report["run"]), (1, "not_met", False, None))

    def test_a_child_whose_entry_the_ledger_would_not_replay_is_no_entry(self):
        broken = {"no visit and no stage": {"visit": ..., "stage": ...}, "no stage": {"stage": ...},
                  "no visit": {"visit": ...}, "an unknown stage": {"stage": "somewhere"},
                  "a zero visit": {"visit": 0}}
        for name, missing in broken.items():
            with self.subTest(name):
                shutil.rmtree(self.root)
                self.root.mkdir()
                write_run(self.root, "r", HOUR, direct_root_events(), "deliver")
                extra = entry(2 * HOUR)[3]
                members = {key: value for key, value in {**extra, **missing}.items() if value is not ...}
                write_run(self.root, "d", HOUR, [("step_entered", "preflight", 2 * HOUR, members)],
                          "direct", parent="r")
                code, report = self.verdict(3 * HOUR)
                self.assertEqual((code, report["verdict"], report["met"]), (75, "not_yet", False))
                code, report = self.verdict(3 * DAY)
                self.assertEqual((code, report["verdict"], report["met"]), (1, "not_met", False))

    def test_a_directory_the_ledger_never_published_is_never_a_run(self):
        cases = {
            "an unpublished temporary directory": {"directory": f".{rid('t')}.tmp"},
            "a directory that is no run id": {"directory": "scratch"},
            "a run.json naming another run": {"claims": rid("other")},
        }
        for name, extra in cases.items():
            with self.subTest(name):
                shutil.rmtree(self.root)
                self.root.mkdir()
                write_run(self.root, "t", HOUR, [("step_entered", "start", HOUR, {})], "deliver", **extra)
                direct_delivery(self.root, "q", 2 * HOUR, 3 * HOUR)
                code, report = self.verdict(4 * HOUR)
                self.assertEqual((code, report["verdict"], report["run"]), (0, "met", rid("q")))


class EngineDeliverPastSetupTest(unittest.TestCase):
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
        direct_delivery(self.runs, "r", HOUR, 2 * HOUR)
        self.activate(ok=False)
        code, report = verify_checks.engine_deliver_past_setup(
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
        direct_delivery(self.runs, "r", HOUR, 2 * HOUR)
        met = run_from_root(argv)
        self.assertEqual(met.returncode, 0, met.stderr)
        self.assertTrue(json.loads(met.stdout)["met"])
        for child in ("r", "r-s", "r-d"):
            shutil.rmtree(self.runs / rid(child))
        for now, code in ((3 * HOUR, 75), (3 * DAY, 1)):
            self.assertEqual(verify_checks.engine_deliver_past_setup(
                self.shas["S"], runs_root=self.runs, log=self.store, repo_root=self.repo,
                now=ANCHOR + now)[0], code)


if __name__ == "__main__":
    unittest.main()
