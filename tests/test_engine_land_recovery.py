"""Scenario tests for the land procedures' recovery: the probe, the sync under the lock, the conflict
resolution outside it and its review, each run as a whole stubbed `engine deliver` on the fixture project
(`tests/engine_stubbed_world.py`), plus the shape of `land.json` and `land-attempt.json` read as data."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_tools.delivery import landing
from tests.engine_stubbed_world import StubbedRun
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_stubbed_run import (
    CONFLICTED, CONFLICTING_MAIN, FINDING, PROCEDURES, RESOLVED, RESOLVED_TEXT, SYNCED, UPSTREAM_IMPLEMENTED,
    Scenario, committing)

TIER = "integration"  # every run case builds a repository and runs the engine as a child process

setUpModule = install_platform_manifest_in_environ

PASS = {"verdict": "pass", "findings": []}
FINDINGS = {"verdict": "findings", "findings": [FINDING]}
STOPS = ["land", "claim-lost", "claim", "head-moved", "checks", "checks-fix", "checks-fix-review",
         "checks-pending", "sync", "sync-contention", "sync-review", "sync-fix", "land-contended", "merge",
         "unreleased-lock"]
RETRY = ("claim", "land-contended", "sync-contention", "checks-pending")
PROMPTS = ("land-sync", "land-resolve", "land-sync-review", "land-sync-fix", "land-sync-rereview")


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
        return StubbedRun(self, replies={
            "implement": UPSTREAM_IMPLEMENTED, "resolve": RESOLVED, "merge-review": PASS, **replies})


class SyncTest(Landing):
    def test_a_branch_behind_at_the_lock_is_synced_pushed_and_merged(self):
        run = StubbedRun(self, advance_main=1, replies={"lock-sync": SYNCED})

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
        run = StubbedRun(self, advance_main=3, replies={"lock-sync": SYNCED})

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
        run = StubbedRun(self, advance_main=1, main_change=CONFLICTING_MAIN, replies={
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

    def test_a_resolution_that_does_not_merge_the_base_stops_sync(self):
        run = self.probe_conflict(resolve={"reply": {"status": "done", "notes": "n", "tests": []}})

        self.finish(run, "sync", "owner-decision")

        self.assertEqual(self.walk(run)[-2:], [("resolve", "done"), ("merge-of", "none")])
        self.assertEqual(self.count(run, "resolve"), 1)


BOUNDS = {
    "expect": (12, "land"), "push": (12, "land"), "pushed": (12, "land"), "find-pull": (12, "land"),
    "create": (2, "land"), "opened": (12, "land"), "probe": (12, "land"), "gate": (12, "land"),
    "lock": (12, "land"), "fresh": (12, "land"), "head": (12, "land"), "recheck": (12, "land"),
    "merge-pr": (6, "merge"), "merged": (6, "merge"), "lock-sync": (2, "sync-contention"),
    "resolve-unlock": (6, "sync"), "resolve": (4, "sync"), "merge-of": (8, "sync"),
    "merge-review": (4, "sync-review"), "merge-fixes": (4, "sync-review"), "merge-fix": (1, "sync-review"),
    "merge-fixed": (1, "sync-fix"), "merge-rereview": (1, "sync-review"),
}
STOP_TARGETS = {
    "renew": ("claim-lost", "claim"), "prepare": ("land",), "settled": (), "expect": ("land",),
    "pushed": ("head-moved", "land"), "find-pull": ("land",), "opened": ("land",),
    "probe": ("land",), "gate": ("checks", "checks-pending", "head-moved", "land"),
    "lock": ("land-contended", "land"), "fresh": ("land",), "head": ("head-moved", "land"),
    "recheck": ("land-contended", "land"), "merge-pr": ("merge",), "merged": ("merge",),
    "lock-sync": ("sync", "sync-contention"), "resolve-unlock": ("unreleased-lock", "sync"),
    "resolve": ("sync",), "merge-of": ("sync", "land"), "merge-review": ("sync-review",),
    "merge-fixes": ("sync-review", "land"), "merge-fix": ("sync-fix", "sync-review"),
    "merge-fixed": ("sync-fix",), "merge-rereview": ("sync-review",),
}


class ShapeTest(unittest.TestCase):
    def test_each_bound_of_the_attempt_is_the_programs(self):
        steps = steps_of("land-attempt")
        self.assertEqual(len(steps), 26)
        for step, (bound, stop) in BOUNDS.items():
            with self.subTest(step):
                self.assertEqual(steps[step].get("max_visits"), bound)
                self.assertEqual(steps[step]["on"]["exhausted"], stop)

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
