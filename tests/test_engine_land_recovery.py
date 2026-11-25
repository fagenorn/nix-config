"""Scenario tests for the land procedures' recovery: the probe, the sync under the lock, the conflict
resolution outside it and its review, each run as a whole stubbed `engine deliver` on the fixture project
(`tests/engine_stubbed_world.py`), plus the shape of `land.json` and `land-attempt.json` read as data.
The module checks `land-attempt` coverage from its own runs: every step of that procedure is visited by
a run of this module, and the module's runs take their fixtures from its own `FIXTURES`."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.delivery import engine_caps, land_tally, landing
from tests.engine_fixture import AdoptedFixtures
from tests.engine_step_coverage import StepCoverage, test_ids
from tests.engine_stubbed_world import StubbedRun
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_stubbed_run import (
    CONFLICTED, CONFLICTING_MAIN, FINDING, GREEN, PROCEDURES, RED, RESOLVED, RESOLVED_TEXT, SYNCED,
    UPSTREAM_IMPLEMENTED, Scenario, committing, keeping_the_run)

TIER = "integration"  # every run case builds a repository and runs the engine as a child process

FIXTURES = AdoptedFixtures()
STEPS = StepCoverage(PROCEDURES, ("land-attempt",))


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)


PASS = {"verdict": "pass", "findings": []}
FINDINGS = {"verdict": "findings", "findings": [FINDING]}
STOPS = ["land", "claim-lost", "claim", "head-moved", "checks", "checks-fix", "checks-fix-review",
         "checks-pending", "sync", "sync-contention", "sync-review", "sync-fix", "land-contended", "merge",
         "unreleased-lock"]
RETRY = ("claim", "land-contended", "sync-contention", "checks-pending")
PROMPTS = ("land-sync", "land-resolve", "land-sync-review", "land-sync-fix", "land-sync-rereview",
           "land-ci-fix", "land-ci-review", "land-stale")
FIXED = committing("fixture/fix.py", "FIXED = 1\n", tests=["checks/check_greet.py"])
RERAN = {"reply": {"status": "done", "notes": "runner lost", "tests": [], "declines": []}, "same_head": {}}
PRESYNCED = {"reply": {"status": "done", "notes": "n", "tests": ["checks/check_greet.py"]}, "merge": {}}
OTHER = [{"__typename": "CheckRun", "name": "Other", "status": "COMPLETED", "conclusion": "SUCCESS",
          "startedAt": "2026-11-06T10:00:00Z", "workflowName": "Other"}]


def procedure(name: str) -> dict:
    return json.loads((PROCEDURES / f"{name}.json").read_text("utf-8"))


def steps_of(name: str) -> dict[str, dict]:
    return {step["id"]: step for step in procedure(name)["steps"]}


class Landing(Scenario):
    def land_run(self, run: StubbedRun) -> Path:
        return self.child(run, "land")

    def attempt(self, run: StubbedRun) -> Path:
        """The last child of the land run that runs `land-attempt`."""
        found = [child for child in run.children(self.land_run(run))
                 if json.loads((child / "run.json").read_text("utf-8"))["procedure"] == "land-attempt"]
        return found[-1]

    def walk(self, run: StubbedRun) -> list[tuple[str, str]]:
        return run.transitions(self.attempt(run))

    def assert_in_order(self, walk: list, *edges: tuple[str, str]) -> None:
        """Each edge occurs in `walk`, each after the one before it."""
        at = 0
        for edge in edges:
            self.assertIn(edge, walk[at:], f"{edge} not after position {at} of {walk}")
            at = walk.index(edge, at) + 1

    def count(self, run: StubbedRun, step: str) -> int:
        return sum(1 for launch in run.launches() if launch["key"] == step)

    def main_file(self, run: StubbedRun, path: str) -> str:
        return run.world.git(run.fixture.root, "--git-dir", run.bare, "show", f"main:{path}")

    def probe_conflict(self, **replies) -> StubbedRun:
        return self.stubbed(replies={
            "implement": UPSTREAM_IMPLEMENTED, "resolve": RESOLVED, "merge-review": PASS, **replies})


class SyncTest(Landing):
    def test_a_branch_behind_at_the_lock_is_synced_pushed_and_merged(self):
        run = self.stubbed(advance_main=1, replies={"lock-sync": SYNCED})

        self.finish(run, "done")

        self.assert_in_order(self.walk(run), ("gate", "green"), ("lock", "held"), ("fresh", "behind"),
                             ("lock-sync", "done"), ("merge-of", "clean"), ("gate", "green"),
                             ("merge-pr", "ok"))
        self.assertEqual(run.transitions(self.land_run(run))[-1], ("release", "done"))
        self.assertIn("main-1.txt", run.world.git(run.fixture.root, "--git-dir", run.bare, "ls-tree",
                                                  "-r", "--name-only", "main"))
        self.assertIn("def farewell", self.main_file(run, "fixture/farewell.py"))
        self.assertEqual(run.lock_refs(), {})
        self.assertEqual(run.forge.issue()["state"], "closed")

    def test_a_third_sync_at_the_lock_stops_sync_contention_with_the_lock_released(self):
        run = self.stubbed(advance_main=3, replies={"lock-sync": SYNCED})

        self.finish(run, "sync-contention", "retry")

        self.assertEqual(self.count(run, "lock-sync"), 2)
        self.assertIn(("release", "sync-contention"), run.transitions(self.land_run(run)))
        self.assertEqual(run.lock_refs(), {})
        self.assertEqual([p["state"] for p in run.pulls()], ["OPEN"])


class ConflictTest(Landing):
    def test_a_conflict_the_probe_finds_is_resolved_before_the_lock_reviewed_relocked_and_merged(self):
        run = self.probe_conflict()

        self.finish(run, "done")

        walk = self.walk(run)
        self.assertIn(("probe", "conflicted"), walk)
        self.assertLess(walk.index(("probe", "conflicted")), min(
            i for i, (step, _) in enumerate(walk) if step == "lock"))
        for edge in (("resolve", "done"), ("merge-of", "review"), ("merge-review", "pass")):
            self.assertIn(edge, walk)
        self.assertEqual(self.count(run, "lock-sync"), 0)
        self.assertEqual(self.main_file(run, "fixture/farewell.py"), RESOLVED_TEXT)

    def test_a_conflict_at_the_lock_is_aborted_released_resolved_outside_it_and_relocked(self):
        run = self.stubbed(advance_main=1, main_change=CONFLICTING_MAIN, replies={
            "lock-sync": CONFLICTED, "resolve": RESOLVED, "merge-review": PASS})

        self.finish(run, "done")

        self.assert_in_order(self.walk(run), ("lock", "held"), ("lock-sync", "conflicted"),
                             ("resolve-unlock", "released"), ("resolve", "done"), ("lock", "held"))
        self.assertEqual(run.lock_refs(), {})

    def test_a_second_review_finding_stops_sync_review_after_the_one_fix(self):
        run = self.probe_conflict(**{
            "merge-review": FINDINGS, "merge-rereview": FINDINGS,
            "merge-fix": committing("fixture/fix.py", "FIX = 1\n", tests=["checks/check_greet.py"])})

        self.finish(run, "sync-review", "owner-decision")

        self.assertEqual(self.count(run, "merge-fix"), 1)
        self.assertEqual(run.lock_refs(), {})

    def test_a_sync_fix_that_records_no_test_stops_sync_fix_and_keeps_its_commit_unpushed(self):
        run = self.probe_conflict(**{
            "merge-review": FINDINGS, "merge-fix": committing("fixture/fix.py", "FIX = 1\n", tests=[])})

        self.finish(run, "sync-fix", "owner-decision")

        self.assertIn(("merge-fixed", "untested"), self.walk(run))
        self.assertEqual(self.count(run, "merge-fix"), 1)
        head = run.world.git(run.worktree_path, "rev-parse", "HEAD").strip()
        self.assertNotEqual(run.origin_tip(run.branch), head)
        self.assertEqual(run.world.git(run.worktree_path, "show", "--name-only", "--format=", head).strip(),
                         "fixture/fix.py")

    def test_a_sync_fix_that_declines_every_finding_and_commits_nothing_is_re_reviewed(self):
        declined = {"reply": {"status": "done", "notes": "declined the one finding", "tests": [], "declines": [
            {"finding": "merge-review:1", "reason": "farewell('') is refused before it reaches line 2"}]},
            "same_head": {}}
        run = self.probe_conflict(**{"merge-review": FINDINGS, "merge-fix": declined, "merge-rereview": PASS})

        self.finish(run, "done")

        self.assert_in_order(self.walk(run), ("merge-fixed", "unchanged"), ("merge-rereview", "pass"))
        self.assertEqual(self.count(run, "merge-fix"), 1)

    def test_a_resolution_that_does_not_merge_the_base_stops_sync(self):
        run = self.probe_conflict(resolve={"reply": {"status": "done", "notes": "n", "tests": []}})

        self.finish(run, "sync", "owner-decision")

        self.assertEqual(self.walk(run)[-2:], [("resolve", "done"), ("merge-of", "none")])
        self.assertEqual(self.count(run, "resolve"), 1)


class RedCheckTest(Landing):
    def fixing(self, **replies) -> dict:
        return {"ci-fix": FIXED, "ci-review": PASS, **replies}

    def test_one_red_check_gets_one_fix_and_its_review_and_then_merges(self):
        run = self.stubbed(rollups=[RED, GREEN], replies=self.fixing())

        self.finish(run, "done")

        self.assert_in_order(
            self.walk(run), ("gate", "red"), ("red", "fix"), ("fix-unlock", "released"), ("ci-fix", "done"),
            ("ci-fixed", "committed"), ("ci-review", "pass"), ("gate", "green"), ("lock", "held"),
            ("merge-pr", "ok"))
        self.assertEqual((self.count(run, "ci-fix"), self.count(run, "ci-review")), (1, 1))
        fix = self.stored(self.attempt(run), "ci-fix")["commit"]
        self.assertEqual(run.pulls()[0]["headRefOid"], fix)
        self.assertEqual(run.pulls()[0]["state"], "MERGED")
        self.assertEqual(run.lock_refs(), {})

    def test_a_second_red_poll_stops_checks_after_the_one_fix(self):
        run = self.stubbed(rollups=[RED, RED], replies=self.fixing())

        self.finish(run, "checks", "owner-decision")

        self.assertEqual(self.count(run, "ci-fix"), 1)
        self.assertEqual(self.walk(run)[-1], ("red", "checks"))
        self.assertEqual(run.lock_refs(), {})

    def test_a_rerun_answer_spends_the_one_fix_and_a_second_red_stops_checks(self):
        run = self.stubbed(rollups=[RED], replies={
            "ci-fix": RERAN, "stale": {"verdict": "real", "reran": [], "notes": "n"}})

        self.finish(run, "checks", "owner-decision")

        self.assert_in_order(self.walk(run), ("ci-fixed", "unchanged"), ("red", "stale"), ("stale", "real"),
                             ("red", "checks"))
        self.assertEqual(self.count(run, "ci-fix"), 1)

    def test_a_stale_answer_polls_once_more_without_counting_a_red_read(self):
        run = self.stubbed(rollups=[RED], replies={
            "ci-fix": RERAN, "stale": {"verdict": "stale", "reran": [7], "notes": "n"}})

        self.finish(run, "checks", "owner-decision")

        walk = self.walk(run)
        self.assert_in_order(walk, ("stale", "stale"), ("gate", "red"), ("red", "checks"))
        self.assertEqual(walk[walk.index(("stale", "stale")) + 1][0], "gate")
        self.assertEqual(self.count(run, "stale"), 1)

    def test_a_fix_with_no_test_recorded_stops_checks_fix_and_is_not_pushed(self):
        run = self.stubbed(rollups=[RED, GREEN], replies=self.fixing(
            **{"ci-fix": committing("fixture/fix.py", "FIXED = 1\n", tests=[])}))

        self.finish(run, "checks-fix", "owner-decision")

        self.assertIn(("ci-fixed", "untested"), self.walk(run))
        head = run.world.git(run.worktree_path, "rev-parse", "HEAD").strip()
        self.assertNotEqual(run.origin_tip(run.branch), head)
        self.assertEqual(self.count(run, "ci-review"), 0)

    def test_review_findings_on_the_fix_stop_checks_fix_review(self):
        run = self.stubbed(rollups=[RED, GREEN], replies=self.fixing(**{"ci-review": FINDINGS}))

        self.finish(run, "checks-fix-review", "owner-decision")

        self.assertIn(("ci-review", "findings"), self.walk(run))
        self.assertEqual(run.lock_refs(), {})

    def test_the_one_fix_per_delivery_holds_across_a_continue(self):
        run = self.stubbed(rollups=[RED, RED], replies=self.fixing())
        procedures = keeping_the_run(run.tmp)
        self.stopped(run, run.deliver(procedures), "checks", "owner-decision")
        first = self.attempt(run)

        self.stopped(run, run.deliver(procedures), "checks", "owner-decision")

        self.assertEqual(self.count(run, "ci-fix"), 1)
        second = [child for child in run.children(self.child(run, "land", last=True))
                  if child.name != first.name][-1]
        self.assertNotEqual(second, first)
        self.assertIn(("red", "checks"), run.transitions(second))

    def test_a_red_check_at_a_head_behind_its_base_is_synced_before_the_lock(self):
        run = self.stubbed(advance_main=1, rollups=[RED, GREEN], replies={"presync": PRESYNCED})

        self.finish(run, "done")

        walk = self.walk(run)
        self.assertIn(("red", "presync"), walk)
        self.assertLess(walk.index(("red", "presync")), min(
            i for i, (step, _) in enumerate(walk) if step == "lock"))
        self.assertEqual(self.count(run, "ci-fix"), 0)

    def test_a_third_presync_stops_sync_contention(self):
        run = self.stubbed(advance_main=3, rollups=[RED], replies={"presync": PRESYNCED})

        self.finish(run, "sync-contention", "retry")

        self.assertEqual(self.count(run, "presync"), 2)


class PendingTest(Landing):
    def test_three_pending_waits_stop_checks_pending(self):
        run = self.stubbed(rollup=[])

        self.finish(run, "checks-pending", "retry")

        walk = self.walk(run)
        self.assertEqual(walk.count(("gate", "pending")), 3)
        self.assertNotIn("lock", {step for step, _ in walk})

    def test_a_passed_poll_naming_no_passing_check_counts_as_pending(self):
        run = self.stubbed(rollup=OTHER)

        self.finish(run, "checks-pending", "retry")

        self.assertIn(("gate", "pending"), self.walk(run))

class MergeRefusalTest(Landing):
    def test_three_merge_refusals_for_being_behind_stop_merge(self):
        run = self.stubbed(merge_behind=3, replies={"resync": SYNCED})

        self.finish(run, "merge", "owner-decision")

        walk = self.walk(run)
        self.assertEqual(walk.count(("merge-state", "behind")), 3)
        self.assertEqual(self.count(run, "resync"), 2)
        self.assertEqual(run.transitions(self.land_run(run))[-1], ("release", "merge"))
        self.assertEqual(run.lock_refs(), {})
        self.assertEqual([p["state"] for p in run.pulls()], ["OPEN"])

    def test_a_merge_refused_for_being_behind_is_resynced_and_merged(self):
        run = self.stubbed(merge_behind=1, replies={"resync": SYNCED})

        self.finish(run, "done")

        self.assert_in_order(self.walk(run), ("merge-pr", "failed"), ("merged", "open"),
                             ("merge-state", "behind"), ("resync", "done"), ("merge-pr", "ok"))

    def test_a_policy_refusal_is_polled_once_more_and_then_merges(self):
        run = self.stubbed(merge_policy=1)

        self.finish(run, "done")

        self.assert_in_order(self.walk(run), ("merge-state", "blocked"), ("policy", "green"),
                             ("merge-pr", "ok"))

    def test_a_second_policy_refusal_stops_merge(self):
        run = self.stubbed(merge_policy=2)

        self.finish(run, "merge", "owner-decision")

        walk = self.walk(run)
        self.assertEqual(walk.count(("policy", "green")), 1)
        self.assertEqual(walk.count(("merge-state", "blocked")), 2)
        self.assertEqual(run.lock_refs(), {})


class LockTest(Landing):
    def test_a_lock_another_pull_request_holds_is_waited_for_within_the_budget_and_stops_land_contended(self):
        run = self.stubbed(forge_events=("steal-lock",))

        self.finish(run, "land-contended", "retry")

        waits = [outcome for step, outcome in self.walk(run) if step == "lock-wait"]
        self.assertEqual(waits[-1], "spent")
        self.assertIn("again", waits)
        answers = land_tally.lock_answers(self.attempt(run))
        self.assertIs(land_tally.lock_budget(answers), False)
        self.assertIs(land_tally.lock_budget(answers[:-1] + [answers[-1][:-1]]), True)
        self.assertEqual(run.lock_refs(), {"refs/agent-locks/land/main": run.stolen_sha})

    def test_a_lock_lost_at_the_re_check_is_waited_for_again(self):
        run = self.stubbed(forge_events=("steal-lock-at-head",))

        self.finish(run, "land-contended", "retry")

        walk = self.walk(run)
        self.assert_in_order(walk, ("recheck", "contended"), ("relock", "contended"), ("lock-wait", "again"))
        self.assertEqual([o for s, o in walk if s == "lock-wait"][-1], "spent")
        self.assertEqual(run.lock_refs(), {"refs/agent-locks/land/main": run.stolen_sha})

    def test_a_re_check_that_took_the_lock_again_polls_once_more_and_merges(self):
        run = self.stubbed(forge_events=("drop-lock-at-head",))

        self.finish(run, "done")

        self.assert_in_order(self.walk(run), ("recheck", "retaken"), ("retake", "green"), ("recheck", "held"))

    def test_a_second_retake_stops_land_contended(self):
        run = self.stubbed(forge_events=("drop-lock-at-head", "drop-lock-at-head"))

        self.finish(run, "land-contended", "retry")

        self.assertEqual(self.walk(run).count(("retake", "green")), 1)
        self.assertEqual(run.lock_refs(), {})


class ReleaseSweepTest(Landing):
    def scenarios(self):
        findings = {"verdict": "findings", "findings": [FINDING]}
        untested = committing("fixture/fix.py", "FIX = 1\n", tests=[])
        return (
            ("sync-contention", {"advance_main": 3, "replies": {"lock-sync": SYNCED}}),
            ("merge", {"merge_behind": 3, "replies": {"resync": SYNCED}}),
            ("merge", {"merge_policy": 2}),
            ("land-contended", {"forge_events": ("drop-lock-at-head", "drop-lock-at-head")}),
            ("land-contended", {"forge_events": ("steal-lock-at-head",)}),
            ("sync-fix", {"advance_main": 1, "main_change": CONFLICTING_MAIN, "replies": {
                "lock-sync": CONFLICTED, "resolve": RESOLVED, "merge-review": findings,
                "merge-fix": untested}}))

    def test_every_stop_after_the_lock_was_taken_leaves_no_land_lock_of_this_delivery(self):
        for stop, scenario in self.scenarios():
            with self.subTest(stop=stop, scenario=sorted(scenario)):
                run = self.stubbed(**scenario)

                done = run.deliver()

                self.assertEqual(run.line(done)["end"], stop, done.stdout + done.stderr)
                self.assertEqual(run.transitions(self.land_run(run))[-1], ("release", stop))
                root = run.runs()[0]
                holder = json.loads((root / "run.json").read_text("utf-8"))["inputs"]["holder"]
                held = land_tally.held_shas(holder, run.world.home / ".agents/state/engine/runs")
                self.assertTrue(held)
                self.assertFalse(held & set(run.lock_refs().values()), run.lock_refs())


class CoverageWiringTest(Scenario):
    def test_the_module_teardown_fails_naming_a_land_attempt_step_no_run_visited(self):
        module = sys.modules[__name__]
        scope = {procedure for procedure, _ in module.STEPS.declared()}
        self.assertEqual(scope, {"land-attempt"})
        coverage = StepCoverage(PROCEDURES, tuple(sorted(scope)))
        for test_id in test_ids(module, Scenario):
            coverage.select(test_id)
        coverage.record(coverage.declared() - {("land-attempt", "merge-rereview")})

        with mock.patch.object(module, "STEPS", coverage), self.assertRaises(AssertionError) as raised:
            module.tearDownModule()

        self.assertIn("land-attempt.merge-rereview", str(raised.exception))

    def test_a_land_recovery_run_records_its_steps_and_takes_its_fixture_from_this_module(self):
        module = sys.modules[__name__]
        coverage = StepCoverage(PROCEDURES, ("land-attempt",))
        fixtures = AdoptedFixtures()
        self.addCleanup(fixtures.close)

        with mock.patch.object(module, "STEPS", coverage), mock.patch.object(module, "FIXTURES", fixtures), \
                mock.patch.object(StubbedRun, "visited_steps", return_value={("land-attempt", "renew")}):
            self.stubbed()
            directory = fixtures.directory
            self.doCleanups()

        self.assertIsNotNone(directory)
        self.assertEqual(coverage.recorded(), {("land-attempt", "renew")})

    def test_this_test_is_selected_on_the_land_recovery_coverage(self):
        self.assertIn(self.id(), sys.modules[__name__].STEPS.selected_ids())


BOUNDS = {
    "expect": (12, "land"), "push": (12, "land"), "pushed": (12, "land"), "find-pull": (12, "land"),
    "create": (2, "land"), "opened": (12, "land"), "probe": (12, "land"), "gate": (12, "land"),
    "lock": (12, "land"), "fresh": (12, "land"), "head": (12, "land"), "recheck": (12, "land"),
    "merge-pr": (6, "merge"), "merged": (6, "merge"), "lock-sync": (2, "sync-contention"),
    "resolve-unlock": (6, "sync"), "resolve": (4, "sync"), "merge-of": (8, "sync"),
    "merge-review": (4, "sync-review"), "merge-fixes": (4, "sync-review"), "merge-fix": (1, "sync-review"),
    "merge-fixed": (1, "sync-fix"), "merge-rereview": (1, "sync-review"),
    "pending": (12, "checks-pending"), "red": (12, "checks"), "stale": (1, "checks"),
    "presync": (2, "sync-contention"), "fix-unlock": (2, "checks"), "ci-fix": (1, "checks"),
    "ci-fixed": (1, "checks-fix"), "ci-review": (1, "checks-fix-review"),
    "lock-wait": (12, "land-contended"), "relock": (3, "land-contended"), "retake": (1, "land-contended"),
    "merge-state": (6, "merge"), "policy": (1, "merge"), "resync": (2, "merge"),
}
STOP_TARGETS = {
    "renew": ("claim-lost", "claim"), "prepare": ("land",), "settled": (), "expect": ("land",),
    "pushed": ("head-moved", "land"), "find-pull": ("land",), "opened": ("land",),
    "probe": ("land",), "gate": ("head-moved", "land"),
    "lock": ("land",), "fresh": ("land",), "head": ("head-moved", "land"),
    "recheck": ("land",), "merge-pr": ("merge",), "merged": ("merge",),
    "lock-sync": ("sync", "sync-contention"), "resolve-unlock": ("unreleased-lock", "sync"),
    "resolve": ("sync",), "merge-of": ("sync", "land"), "merge-review": ("sync-review",),
    "merge-fixes": ("sync-review", "land"), "merge-fix": ("sync-fix", "sync-review"),
    "merge-fixed": ("sync-fix",), "merge-rereview": ("sync-review",),
    "pending": ("checks-pending", "land"), "red": ("checks", "land"), "stale": ("checks",),
    "presync": ("sync", "sync-contention"), "fix-unlock": ("unreleased-lock", "checks"),
    "ci-fix": ("checks-fix", "checks"), "ci-fixed": ("checks-fix", "land"),
    "ci-review": ("checks-fix-review",),
    "lock-wait": ("land-contended", "land"), "relock": ("land-contended", "land"),
    "retake": ("head-moved", "land-contended", "land"), "merge-state": ("merge",),
    "policy": ("head-moved", "merge", "land"), "resync": ("sync", "merge"),
}


class ShapeTest(unittest.TestCase):
    def test_each_bound_of_the_attempt_is_the_programs(self):
        steps = steps_of("land-attempt")
        for step, (bound, stop) in BOUNDS.items():
            with self.subTest(step):
                self.assertEqual(steps[step].get("max_visits"), bound)
                self.assertEqual(steps[step]["on"]["exhausted"], stop)

    def test_the_attempt_has_exactly_the_step_cap(self):
        self.assertEqual(len(procedure("land-attempt")["steps"]), engine_caps.PROCEDURE_STEPS)

    def test_every_counted_step_is_a_step_of_the_attempt(self):
        self.assertLessEqual(set(land_tally.COUNTED_STEPS) - {land_tally.ATTEMPT}, set(steps_of("land-attempt")))

    def test_a_red_check_fix_is_entered_only_through_the_release(self):
        steps = steps_of("land-attempt")
        into = [(step, outcome) for step, body in steps.items() for outcome, target in body["on"].items()
                if target == "ci-fix"]
        self.assertEqual(into, [("fix-unlock", "released")])
        self.assertEqual(steps["red"]["on"]["fix"], "fix-unlock")

    def test_every_end_of_the_attempt_is_released_by_the_wrapper(self):
        wrapper, attempt = procedure("land"), procedure("land-attempt")
        self.assertEqual(sorted(wrapper["stops"]), sorted(STOPS))
        self.assertEqual(sorted(attempt["stops"]), sorted(STOPS))
        self.assertEqual(sorted(landing.RELEASE_ENDS), sorted(["done", *STOPS]))
        steps = steps_of("land")
        self.assertEqual(list(steps), ["attempt", "release"])
        self.assertEqual(steps["attempt"]["kind"], "call")
        self.assertEqual(steps["attempt"]["procedure"], "land-attempt")
        self.assertEqual(steps["attempt"]["on"], {name: "release" for name in ["done", *STOPS]})
        want = {name: name for name in landing.RELEASE_ENDS if name != "done"}
        want.update({"done": "done", "unreleased": "unreleased-lock", "refused": "unreleased-lock"})
        self.assertEqual(steps["release"]["on"], want)
        self.assertEqual(steps["release"]["in"], ["run.repo_root", "run.issue", "run.repo", "run.holder",
                                                  "attempt.items"])
        for name in STOPS:
            need = "retry" if name in RETRY else "owner-decision"
            self.assertEqual(wrapper["stops"][name], {"need": need, "reenter": "attempt"}, name)
            self.assertEqual(attempt["stops"][name], {"need": need, "reenter": "renew"}, name)

    def test_no_step_is_named_as_a_stop_and_each_stop_target_is_a_stop(self):
        for name in ("land", "land-attempt"):
            document = procedure(name)
            self.assertFalse(set(steps_of(name)) & set(document["stops"]), name)
        steps, stops = steps_of("land-attempt"), procedure("land-attempt")["stops"]
        for step, targets in STOP_TARGETS.items():
            on = steps[step]["on"]
            for target in targets:
                with self.subTest(step=step, target=target):
                    self.assertIn(target, on.values())
                    self.assertIn(target, stops)
                    self.assertNotIn(target, steps)

    def test_the_landing_step_maps_every_land_stop_to_the_deliver_stop_of_the_same_name(self):
        deliver = procedure("deliver")
        landing_step = next(step for step in deliver["steps"] if step["id"] == "landing")
        self.assertEqual(landing_step["on"], {"done": "closing", **{name: name for name in STOPS}})
        for name in STOPS:
            stop = deliver["stops"][name]
            self.assertEqual(stop["reenter"], "landing" if name not in ("claim", "claim-lost") else "start", name)
            self.assertEqual(stop["need"], "retry" if name in RETRY else "owner-decision", name)
        for name in ("merge", "unreleased-lock"):
            self.assertTrue(deliver["stops"][name]["pinned"], name)
        for gone in ("checks-not-green", "merge-not-landed"):
            self.assertNotIn(gone, landing_step["on"])

    def test_the_lifecycle_steps_hold_run_and_the_readings_hold_live(self):
        for name in ("land", "land-attempt"):
            for step in steps_of(name).values():
                with self.subTest(procedure=name, step=step["id"]):
                    if step["kind"] == "agent":
                        self.assertEqual(step["holds"], "run")
                    elif step.get("command") in ("git-push", "pr-create", "pr-merge"):
                        self.assertEqual(step["holds"], "run")
                    else:
                        self.assertEqual(step["holds"], "live")

    def test_no_land_prompt_names_a_lifecycle_or_lock_command(self):
        for name in PROMPTS:
            text = (PROCEDURES / f"{name}.md").read_text("utf-8")
            for word in ("git push", "gh pr create", "gh pr merge", "forge-claim"):
                with self.subTest(prompt=name, word=word):
                    self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
