"""The cut harness of the stubbed delivery: a run killed straight after one ledger write, then continued.

`tests/engine_cut_sweep.py` runs the engine through `tests/fixtures/engine-stubbed-run/cut_engine.py`, which
kills the whole process group right after the write that makes a named cut point. These cases prove the harness
itself: where the kill lands, that it waits for the cut run's processes, that it names a point never reached, that
no thread writes after the kill, and that a deliberately broken continue is told apart from a sound one.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import unittest

from tests.engine_cut_sweep import (BROKEN_CUT, NAMED, RESULT_NAME, SAMPLE, CutPoint, CutSweep, Outcome, again,
                                    contained, cut_at, cut_points, deliver, end_spawned, judge, live_started,
                                    reading, select, settle)
from tests.guard_policy_world import REPO_ROOT
from tests.engine_fixture import AdoptedFixtures
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import StepCoverage
from tests.engine_stubbed_world import IMPLEMENTED, StubbedRun
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_stubbed_run import Scenario
from tests.test_suite_tiers import recipe_paths

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


class CutSweepDailyTest(CutSweep):
    def test_every_cut_point_continued_ends_where_the_uninterrupted_run_ends(self):
        reference, points = self.reference()
        self.assertTrue(set(NAMED) <= set(points))
        self.assertTrue(set(SAMPLE) <= set(points))
        chosen = select(points, os.environ.get("ENGINE_CUT_SWEEP_SLICE"), os.environ.get("ENGINE_CUT_SWEEP_ONLY"))
        self.assertTrue(chosen)
        print(f"cut sweep: {len(points)} cut points, {len(chosen)} selected", file=sys.stderr)

        for point in chosen:
            with self.subTest(cut=point.name()):
                started = time.monotonic()
                name, failures = self.cut_and_continue([point], reference)
                seconds = time.monotonic() - started
                print(f"cut done: {name}: {seconds:.1f} s, {'pass' if not failures else 'FAIL'}", file=sys.stderr)
                self.assertEqual(failures, [])

    def test_the_sampled_chain_and_a_broken_continue_end_as_the_rule_says(self):
        reference, _ = self.reference()

        started = time.monotonic()
        _, chain = self.cut_and_continue(SAMPLE, reference)
        chain_seconds = time.monotonic() - started
        reached = self.cuts_reached
        started = time.monotonic()
        _, broken = self.cut_and_continue([BROKEN_CUT], reference, broken=True)
        broken_seconds = time.monotonic() - started
        print(f"rehearsal: chain {chain_seconds:.1f} s, {reached} of 4 cuts reached; broken {broken_seconds:.1f} s",
              file=sys.stderr)

        self.assertEqual(chain, [])
        prefix = f"cut after {BROKEN_CUT.name()}: "
        self.assertTrue(all(line.startswith(prefix) for line in broken), broken)
        mutating = re.escape(prefix) + r"mutates step implement launched fresh ([2-9]|[1-9][0-9]+) times, uninterrupted 1"
        session = re.escape(prefix) + r"session \S+ launched fresh ([2-9]|[1-9][0-9]+) times"
        self.assertTrue(any(re.fullmatch(mutating, line) for line in broken), broken)
        self.assertTrue(any(re.fullmatch(session, line) for line in broken), broken)


def outcome_of(**changes) -> Outcome:
    members = {"end": "done",
               "state": {"issue state": "closed", "pull requests": [[1, "MERGED", "issue-41"]]},
               "effects": {"comment posted": 3, "issue created": 0, "pull request created": 1,
                           "pull request merged": 1},
               "fresh": {"s": 1}, "fresh_steps": {"implement": 1, "lite-review": 1}}
    return Outcome(**{**members, **changes})


def points_named(count: int) -> list[CutPoint]:
    return [CutPoint("direct#1", "step_entered", f"s{i}", 1, 1) for i in range(count)]


class JudgeTest(unittest.TestCase):
    def test_identical_outcomes_pass(self):
        o = outcome_of()

        self.assertEqual(judge("x", o, o), [])

    def test_a_session_id_launched_fresh_twice_fails(self):
        reference = outcome_of(fresh={})
        got = outcome_of(fresh={"s": 2})

        self.assertEqual(judge("x", reference, got), ["cut after x: session s launched fresh 2 times"])

    def test_a_mutating_step_launched_fresh_once_more_fails(self):
        got = outcome_of(fresh_steps={"implement": 2, "lite-review": 1})

        self.assertEqual(judge("x", outcome_of(), got),
                         ["cut after x: mutates step implement launched fresh 2 times, uninterrupted 1"])

    def test_a_review_launched_again_under_a_new_session_passes(self):
        reference = outcome_of(fresh={"a": 1, "b": 1}, fresh_steps={"implement": 1, "lite-review": 1})
        got = outcome_of(fresh={"a": 1, "b": 1, "c": 1}, fresh_steps={"implement": 1, "lite-review": 2})

        self.assertEqual(judge("x", reference, got), [])

    def test_a_repeated_effect_fails(self):
        got = outcome_of(effects={"comment posted": 4, "issue created": 0, "pull request created": 1,
                                  "pull request merged": 1})

        self.assertEqual(judge("x", outcome_of(), got), ["cut after x: comment posted 4 times, uninterrupted 3"])

    def test_a_different_end_or_state_fails(self):
        got = outcome_of(end="stop land",
                         state={"issue state": "closed", "pull requests": [[1, "OPEN", "issue-41"]]})

        self.assertEqual(judge("x", outcome_of(), got), [
            "cut after x: ended stop land, uninterrupted done",
            "cut after x: pull requests [[1, 'OPEN', 'issue-41']], uninterrupted [[1, 'MERGED', 'issue-41']]"])

    def test_a_cut_run_is_delivered_again_only_after_a_retry_stop_and_at_most_three_times(self):
        self.assertIs(again("run_done", None, 0), False)
        self.assertIs(again("step_entered", None, 0), True)
        self.assertIs(again("stop_reached", "retry", 1), True)
        self.assertIs(again("stop_reached", "owner-decision", 1), False)
        self.assertIs(again("stop_reached", None, 1), False)
        self.assertIs(again("stop_reached", "retry", 3), False)

    def test_a_delivery_with_no_result_line_is_read_as_a_note(self):
        faulted = subprocess.CompletedProcess([], 1, "", "x\nengine: step implement gave no structured reply, exit 1\n")
        stopped = subprocess.CompletedProcess([], 3, '{"end": "land", "need": "retry"}\n', "")

        self.assertEqual(reading(faulted),
                         (None, "exited 1 with no result line: engine: step implement gave no structured reply, exit 1"))
        self.assertEqual(reading(stopped), ("retry", None))

    def test_a_sweep_selects_a_slice_or_named_points_and_refuses_an_unknown_name(self):
        ps = points_named(5)

        self.assertEqual(select(ps, "1/2", None), (ps[1], ps[3]))
        self.assertEqual(select(ps, None, f"{ps[3].name()}|{ps[0].name()}"), (ps[0], ps[3]))
        self.assertEqual(select(ps, None, None), tuple(ps))
        with self.assertRaises(ValueError):
            select(ps, None, "nope")
        with self.assertRaises(ValueError):
            select(ps, "2/2", None)

    def test_slices_follow_the_names_and_not_the_logged_order(self):
        ps = points_named(5)
        rev = tuple(reversed(ps))

        for k in (0, 1, 2):
            self.assertEqual(select(rev, f"{k}/3", None), select(ps, f"{k}/3", None))
        held = [p for k in (0, 1, 2) for p in select(ps, f"{k}/3", None)]
        self.assertEqual(sorted(held, key=CutPoint.name), sorted(ps, key=CutPoint.name))
        for k in (0, 1):
            self.assertEqual(set(select(ps, f"{k}/2", None)),
                             set(select(ps, f"{k}/4", None)) | set(select(ps, f"{k + 2}/4", None)))

    def test_an_error_in_one_cut_becomes_that_cuts_line(self):
        def timed_out():
            raise subprocess.TimeoutExpired(["engine"], 600)

        lines = contained("a", timed_out)

        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("cut after a: TimeoutExpired: "), lines)
        self.assertEqual(contained("b", lambda: []), [])

    def test_the_daily_workflow_runs_every_slice_of_the_full_sweep(self):
        text = (REPO_ROOT / ".github/workflows/cut-sweep.yaml").read_text(encoding="utf-8")

        for needle in ("schedule:", "slice: [0, 1, 2, 3]", "ENGINE_CUT_SWEEP_SLICE: ${{ matrix.slice }}/4",
                       "just engine-cut-sweep"):
            self.assertIn(needle, text)
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
        self.assertEqual(recipe_paths(justfile, "engine-cut-sweep", modules=False),
                         ["tests/test_engine_cut_sweep_daily.py"])


if __name__ == "__main__":
    unittest.main()
