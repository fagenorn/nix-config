"""The cut-and-continue rule over a sample of the stubbed delivery's cut points, against a committed record.

The rule: a delivery cut straight after any ledger write and continued ends where the uninterrupted run ends, and
launches no answered session afresh. This member continues one chain of sampled cuts and one deliberately broken
continue, and compares each against `tests/fixtures/engine-stubbed-run/cut-reference.json`, the committed outcome of
the uninterrupted run, so it runs no reference run. The full sweep of every cut point, and the check that the record
still matches the live run, are the nightly `tests/test_engine_cut_sweep_daily.py`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.engine_cut_sweep import (BROKEN_CUT, RECIPE, SAMPLE, STATE_KEYS, CutPoint, CutSweep, Outcome, again,
                                    contained, judge, outcome, read_record, reading, record_problems, select,
                                    write_record)
from tests.engine_fixture import AdoptedFixtures
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import StepCoverage
from tests.guard_policy_world import REPO_ROOT, install_platform_manifest_in_environ
from tests.test_engine_stubbed_run import Scenario
from tests.test_suite_tiers import recipe_paths

TIER = "integration"  # the sampled cases run the engine as a child process

FIXTURES = AdoptedFixtures()
STEPS = StepCoverage(PROCEDURES, ())


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)


class CutSweepTest(CutSweep):
    RECORDED = True

    def test_the_sampled_cuts_continued_end_where_the_committed_record_ends(self):
        expected = read_record()
        label = ", ".join(p.name() for p in SAMPLE)

        with self.subTest(cut=label):
            name, failures = self.cut_and_continue(SAMPLE, expected)

            self.assertEqual(failures, [],
                             f"if the uninterrupted run changed on purpose, rewrite the record with {RECIPE}")

    def test_a_continue_that_launches_an_answered_session_afresh_fails_the_rule_naming_the_cut(self):
        expected = read_record()
        prefix = f"cut after {BROKEN_CUT.name()}: "

        name, failures = self.cut_and_continue([BROKEN_CUT], expected, broken=True)

        self.assertEqual(name, BROKEN_CUT.name())
        self.assertTrue(failures)
        self.assertTrue(all(line.startswith(prefix) for line in failures), failures)
        mutating = re.escape(prefix) + r"mutates step implement launched fresh ([2-9]|[1-9][0-9]+) times, uninterrupted 1"
        session = re.escape(prefix) + r"session \S+ launched fresh ([2-9]|[1-9][0-9]+) times"
        self.assertTrue(any(re.fullmatch(mutating, line) for line in failures), failures)
        self.assertTrue(any(re.fullmatch(session, line) for line in failures), failures)
        self.assertTrue(any(line.startswith(prefix + "delivery 1 exited 1 with no result line: ")
                            for line in failures), failures)

    def test_a_local_main_behind_origin_is_a_state_the_rule_judges_against_the_record(self):
        run, start = self.world()
        git = run.world.git
        reference = read_record()
        self.assertIs(outcome(run, start).state["local main at origin"], True)
        git(run.fixture.root, "commit", "--quiet", "--allow-empty", "-m", "published")
        git(run.fixture.root, "push", "--quiet", "origin", "main")
        git(run.fixture.root, "update-ref", "refs/heads/main", "HEAD~1")

        behind = outcome(run, start)

        self.assertIs(behind.state["local main at origin"], False)
        self.assertIn("cut after x: local main at origin False, uninterrupted True",
                      judge("x", reference, replace(reference, state=behind.state)))

    def test_this_member_runs_no_reference_run(self):
        with self.assertRaises(AssertionError):
            self.reference()

    def test_the_committed_record_reads_back(self):
        recorded = read_record()

        self.assertIsInstance(recorded, Outcome)
        self.assertEqual(recorded.end, "done")
        self.assertEqual(recorded.fresh, {})
        self.assertEqual(recorded.fresh_steps["implement"], 1)

    def test_the_record_recipe_rewrites_the_record_through_the_daily_check(self):
        justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        start = justfile.index("engine-cut-reference:")
        body = []
        for line in justfile[start + 1:]:
            if not line.startswith((" ", "\t")):
                break
            body.append(line)
        text = "\n".join(body)

        for needle in ("ENGINE_CUT_RECORD=write", "tests/test_engine_cut_sweep_daily.py",
                       "-k test_the_uninterrupted_run_matches_the_committed_record"):
            self.assertIn(needle, text)


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

    def test_a_record_round_trips_without_session_ids(self):
        outcome = outcome_of(fresh={"s": 1}, state={key: [key] for key in STATE_KEYS})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            write_record(outcome, path)
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("fresh", document)
            self.assertEqual(list(document), ["end", "state", "effects", "fresh_steps"])
            self.assertEqual(read_record(path), replace(outcome, fresh={}))
            del document["effects"]
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError) as raised:
                read_record(path)
            self.assertIn("effects", str(raised.exception))

    def test_a_record_that_differs_from_the_live_run_names_each_member_and_the_recipe(self):
        recorded = outcome_of(state={"issue state": "closed", "main subjects": ["a"]})
        live = outcome_of(state={"issue state": "closed", "main subjects": ["a", "b"]},
                          effects={"comment posted": 4, "issue created": 0, "pull request created": 1,
                                   "pull request merged": 1})

        self.assertEqual(record_problems(recorded, live), [
            "record state main subjects ['a'], live run ['a', 'b']",
            "record effects comment posted 3, live run 4",
            f"rewrite the record with {RECIPE} if the uninterrupted run changed on purpose"])
        self.assertEqual(record_problems(recorded, recorded), [])


if __name__ == "__main__":
    unittest.main()
