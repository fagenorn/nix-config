"""The cut harness of the stubbed delivery: a run killed straight after one ledger write, then continued.

`tests/engine_cut_sweep.py` runs the engine through `tests/fixtures/engine-stubbed-run/cut_engine.py`, which
kills the whole process group right after the write that makes a named cut point. These cases prove the harness
itself: where the kill lands, that it waits for the cut run's processes, that it names a point never reached, that
no thread writes after the kill, and that a deliberately broken continue is told apart from a sound one.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
import unittest

from tests.engine_cut_sweep import (BROKEN_CUT, RESULT_NAME, CutPoint, cut_at, cut_points, deliver, end_spawned,
                                    live_started, settle)
from tests.guard_policy_world import REPO_ROOT
from tests.engine_fixture import AdoptedFixtures
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import StepCoverage
from tests.engine_stubbed_world import IMPLEMENTED, StubbedRun
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_stubbed_run import Scenario

TIER = "nightly"  # walks the stubbed delivery once per cut point
PROBE = REPO_ROOT / "tests/fixtures/engine-stubbed-run/cut_spawn_probe.py"

FIXTURES = AdoptedFixtures()
STEPS = StepCoverage(PROCEDURES, ())


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)


class CutHarnessTest(Scenario):
    def test_a_cut_after_the_implement_session_id_is_recorded_ends_the_engine_before_its_process_starts(self):
        run = self.stubbed()
        point = CutPoint("direct#1", "session_starting", "implement", 1, 1)

        cut_at(run, point)

        direct = self.child(run, "direct")
        events = StubbedRun.events(direct)
        self.assertEqual((events[-1]["event"], events[-1]["step"]), ("session_starting", "implement"))
        self.assertEqual([e for e in events if e["event"] == "process_started" and e.get("step") == "implement"], [])
        self.assertEqual([k for k in self.keys(run) if k == "implement"], [])
        self.assertEqual(cut_points(run.tmp / "cuts.log")[-1], point)

        done = run.deliver()

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(run.line(done)["end"], "done")
        implement = [launch for launch in run.launches() if launch["key"] == "implement"]
        self.assertEqual(len(implement), 1)
        argv = implement[0]["argv"]
        self.assertEqual(argv[argv.index("--session-id") + 1], events[-1]["session"])
        self.assertNotIn("--resume", argv)
        self.assertEqual([p["state"] for p in run.pulls()], ["MERGED"])

    def test_a_cut_after_a_process_started_waits_for_that_process_to_end(self):
        run = self.stubbed(replies={"implement": {**IMPLEMENTED, "sleep": 3}})

        cut_at(run, CutPoint("direct#1", "process_started", "implement", 1, 1))

        events = StubbedRun.events(self.child(run, "direct"))
        self.assertEqual((events[-1]["event"], events[-1]["step"]), ("process_started", "implement"))
        self.assertEqual(live_started(run), [])

    def test_a_cut_point_the_run_never_reaches_fails_naming_it(self):
        run = self.stubbed()

        with self.assertRaises(AssertionError) as raised:
            cut_at(run, CutPoint("direct#1", "session_starting", "no-such-step", 1, 1))

        self.assertEqual(str(raised.exception),
                         "cut point direct#1 session_starting no-such-step.1 #1 never reached: exit 0")

    def test_a_cut_inside_the_parallel_review_group_leaves_no_write_after_the_cut(self):
        run = self.stubbed()

        # the command member enters just before the agent member's thread writes its own events
        cut_at(run, CutPoint("direct#1", "step_entered", "lite-independent", 1, 1))

        events = StubbedRun.events(self.child(run, "direct"))
        self.assertEqual((events[-1]["event"], events[-1]["step"], events[-1]["visit"]),
                         ("step_entered", "lite-independent", 1))
        logged = cut_points(run.tmp / "cuts.log")
        lines = sum(len(StubbedRun.events(directory)) for directory in run.run_dirs())
        files = sum(1 for directory in run.run_dirs() if (directory / "results").is_dir()
                    for path in (directory / "results").iterdir() if RESULT_NAME.fullmatch(path.name))
        self.assertEqual(sum(1 for p in logged if p.event != "result-file"), lines)
        self.assertEqual(sum(1 for p in logged if p.event == "result-file"), files)

    def test_a_broken_continue_launches_the_answered_implement_session_afresh_under_its_own_id(self):
        run = self.stubbed()

        cut_at(run, BROKEN_CUT)
        done = deliver(run, broken=True)

        implement = [launch for launch in run.launches() if launch["key"] == "implement"]
        self.assertEqual(len(implement), 2)
        ids = set()
        for launch in implement:
            argv = launch["argv"]
            ids.add(argv[argv.index("--session-id") + 1])
            self.assertNotIn("--resume", argv)
        self.assertEqual(len(ids), 1)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertIn("gave no structured reply", done.stderr)

    def test_a_cut_run_process_still_alive_at_the_deadline_fails_the_cut_naming_it(self):
        run = self.stubbed(replies={"implement": {**IMPLEMENTED, "sleep": 600}})
        point = CutPoint("direct#1", "process_started", "implement", 1, 1)

        deliver(run, cut=point, log=run.tmp / "cuts.log")
        with self.assertRaises(AssertionError) as raised:
            settle(run, wait=1.0)

        self.assertTrue(str(raised.exception).startswith("cut run processes still alive after 1.0 s: ["),
                        str(raised.exception))
        deadline = time.monotonic() + 5
        while live_started(run) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(live_started(run), [])

    def test_a_process_spawned_just_before_the_cut_that_the_ledger_never_recorded_is_still_found(self):
        run = self.stubbed()
        runs = run.world.home / ".agents/state/engine/runs/probe-run"
        runs.mkdir(parents=True)
        (runs / "run.json").write_text(json.dumps({"procedure": "direct", "sequence": 1}), encoding="utf-8")
        (runs / "events.jsonl").write_text("", encoding="utf-8")
        point = CutPoint("direct#1", "step_entered", "x", 1, 1)
        env = {**run.env, "ENGINE_CUT_AT": json.dumps(point.to_json()), "ENGINE_CUT_LOG": str(run.tmp / "cuts.log")}
        run.test.addCleanup(end_spawned, run)

        done = subprocess.run([sys.executable, str(PROBE), str(runs)], cwd=run.fixture.root, env=env,
                              start_new_session=True, capture_output=True, text=True, timeout=60)

        self.assertEqual(done.returncode, -signal.SIGKILL, done.stdout + done.stderr)
        pid = int(done.stdout.split()[0])
        self.assertEqual([e["event"] for e in StubbedRun.events(runs)], ["step_entered"])
        self.assertEqual(live_started(run), [pid])
        with self.assertRaises(AssertionError) as raised:
            settle(run, wait=1.0)
        self.assertIn(str(pid), str(raised.exception))
        deadline = time.monotonic() + 5
        while live_started(run) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(live_started(run), [])


if __name__ == "__main__":
    unittest.main()
