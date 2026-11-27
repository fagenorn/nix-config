"""A delivery cut anywhere after its setup and continued re-enters where it was cut.

The core cases read the shipped `deliver` procedure over hand-built ledgers: where `engine_core.reentry` sends a
continue after a cut that left no stop. The scenario cases kill a stubbed `engine deliver` while a session is open
(`tests/engine_stubbed_world.py`), run `engine deliver` again, and read the run directories and the launcher's log.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

from agent_tools.delivery import engine_core
from tests.engine_fixture import AdoptedFixtures
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import StepCoverage
from tests.engine_stubbed_world import IMPLEMENTED, StubbedRun
from tests.guard_policy_world import REAL_GIT, install_platform_manifest_in_environ
from tests.test_engine_stubbed_run import Scenario

TIER = "integration"  # the scenario cases build a repository and run the engine as a child process

FIXTURES = AdoptedFixtures()
STEPS = StepCoverage(PROCEDURES, ())
INPUTS = {"holder": "h", "issue": 41, "repo": "o/r", "repo_root": "/r"}
ISSUE = {"body": "Add a greet() function.\n\n## Acceptance criteria\n\n- [ ] [code] greet() returns the greeting\n",
         "marked": False, "lane_paths": {"guard": ["unrelated/"]}}
FOREVER = 600


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)


def deliver_document() -> dict:
    return json.loads((PROCEDURES / "deliver.json").read_text("utf-8"))


def called(step: str, end: str = "done") -> list[dict]:
    return [{"type": "entered", "step": step},
            {"type": "outcome", "step": step, "outcome": end, "result": {"items": [{"end": end}]}}]


def issue_read() -> list[dict]:
    return [{"type": "entered", "step": "issue"},
            {"type": "outcome", "step": "issue", "outcome": "read", "result": ISSUE}]


class ReentryTest(unittest.TestCase):
    def reentry(self, events: list[dict]) -> engine_core.Reentry:
        return engine_core.reentry(deliver_document(), INPUTS, events, "a" * 40)

    def setup_walk(self) -> list[dict]:
        return [*called("start"), *issue_read()]

    def test_a_run_cut_after_the_landing_merged_re_enters_at_the_close_out_with_nothing_stale(self):
        events = [*self.setup_walk(), *called("direct-lane"), *called("verification"), *called("landing"),
                  {"type": "entered", "step": "closing"}]

        self.assertEqual(self.reentry(events), engine_core.Reentry("closing", 1, ()))

    def test_a_run_cut_between_the_merge_and_the_close_out_re_enters_at_the_close_out(self):
        events = [*self.setup_walk(), *called("direct-lane"), *called("verification"), *called("landing")]

        self.assertEqual(self.reentry(events), engine_core.Reentry("closing", 1, ()))

    def test_a_run_cut_inside_the_direct_lane_re_enters_at_that_call(self):
        events = [*self.setup_walk(), {"type": "entered", "step": "direct-lane"}]

        self.assertEqual(self.reentry(events), engine_core.Reentry("direct-lane", 1, ()))

    def test_a_run_cut_inside_the_verification_re_enters_at_that_call(self):
        events = [*self.setup_walk(), *called("direct-lane"), {"type": "entered", "step": "verification"}]

        self.assertEqual(self.reentry(events), engine_core.Reentry("verification", 1, ()))

    def test_a_run_stopped_at_a_landing_stop_that_follows_a_change_re_enters_the_verification(self):
        document = deliver_document()
        landing = next(step for step in document["steps"] if step["id"] == "landing")
        stops = [name for name, target in landing["on"].items()
                 if name in document["stops"] and document["stops"][name]["reenter"] != "start"
                 and not document["stops"][name].get("pinned")]
        self.assertIn("checks-fix", stops)
        for stop in stops:
            with self.subTest(stop=stop):
                events = [*self.setup_walk(), *called("direct-lane"), *called("verification"),
                          *called("landing", stop)]

                point = self.reentry(events)

                self.assertEqual((point.step, point.visit), ("verification", 1))

    def test_a_run_stopped_at_a_pinned_landing_stop_re_enters_the_landing(self):
        events = [*self.setup_walk(), *called("direct-lane"), *called("verification"),
                  *called("landing", "merge")]

        point = self.reentry(events)

        self.assertEqual((point.step, point.visit, point.stale), ("landing", 1, ()))


class CutScenario(Scenario):
    """A stubbed delivery whose engine is killed while one agent session of its run is open."""

    def open_session(self, run: StubbedRun, procedure: str, step: str) -> bool:
        """Whether a child run of `procedure` started a process for `step`, stored no result for it and the launcher
        stand-in has logged that launch and reached its wait (a kill earlier would leave no launch to resume)."""
        if not run.asleep(step):
            return False
        try:
            for root in run.runs():
                for child in run.children(root):
                    if json.loads((child / "run.json").read_text("utf-8"))["procedure"] != procedure:
                        continue
                    events = run.events(child)
                    started = [e for e in events if e["event"] == "process_started" and e["step"] == step]
                    stored = [e for e in events if e["event"] == "result_stored" and e["step"] == step]
                    if started and not stored:
                        return True
        except (FileNotFoundError, ValueError):
            return False  # a run directory was being published or an event line was being written
        return False

    def cut_at(self, run: StubbedRun, procedure: str, step: str) -> None:
        run.deliver_until(lambda: self.open_session(run, procedure, step))
        self.assertTrue(self.open_session(run, procedure, step))

    def entered(self, run: StubbedRun, procedure: str, step: str) -> bool:
        """Whether a child run of `procedure` has entered `step`."""
        try:
            return any(e["event"] == "step_entered" and e["step"] == step
                       for child in run.children(run.runs()[0])
                       if json.loads((child / "run.json").read_text("utf-8"))["procedure"] == procedure
                       for e in run.events(child))
        except (FileNotFoundError, ValueError, IndexError):
            return False  # a run directory was being published or an event line was being written

    def branch_refs(self, run: StubbedRun) -> dict[str, list[str]]:
        """The names of the branches the checkout and the bare origin hold."""
        local = run.world.git(run.fixture.root, "for-each-ref", "--format=%(refname)", "refs/heads").split()
        remote = subprocess.run([REAL_GIT, "-C", run.bare, "for-each-ref", "--format=%(refname)", "refs/heads"],
                                capture_output=True, text=True, check=True).stdout.split()
        return {"local": sorted(local), "origin": sorted(remote)}

    def procedures_of(self, run: StubbedRun) -> Counter:
        return Counter(json.loads((child / "run.json").read_text("utf-8"))["procedure"]
                       for child in run.children(run.runs()[0]))

    def end_state(self, run: StubbedRun) -> dict:
        issue = run.forge.issue()
        return {"issue": issue["state"], "labels": sorted(issue["labels"]),
                "comments": len(run.forge.stored()), "created": len(issue["created"]),
                "pulls": [(pull["state"], pull["headRefName"]) for pull in run.pulls()],
                "claims": len(run.claims()), "lock_refs": run.lock_refs(),
                "worktree": run.worktree_path.exists(),
                "branch_on_origin": run.origin_tip(run.branch) is not None}


class CutContinueTest(CutScenario):
    def test_a_delivery_cut_while_a_child_runs_implement_session_is_open_resumes_that_session_in_the_same_child(self):
        run = self.stubbed(replies={"implement": {**IMPLEMENTED, "sleep": FOREVER}})
        self.cut_at(run, "direct", "implement")
        root = run.runs()[0]
        before = Counter(self.procedures_of(run))
        direct = self.child(run, "direct")
        session = next(e["session"] for e in run.events(direct)
                       if e["event"] == "session_starting" and e["step"] == "implement")
        self.assertEqual(before, Counter({"setup": 1, "direct": 1}))

        self.finish(run, "done")

        self.assertEqual(self.procedures_of(run), Counter({"setup": 1, "direct": 1, "verify": 1, "land": 1,
                                                           "close-out": 1}))
        self.assertEqual(len(run.runs()), 1)
        launches = [launch for launch in run.launches() if launch["key"] == "implement"]
        self.assertEqual(len(launches), 2)
        first, second = (launch["argv"] for launch in launches)
        self.assertIn("--resume", second, run.launches())
        self.assertEqual(first[first.index("--session-id") + 1], session)
        self.assertEqual(second[second.index("--resume") + 1], session)
        self.assertNotIn("--session-id", second)
        resumed = [e for e in run.events(direct) if e["event"] == "session_resuming" and e["step"] == "implement"]
        self.assertEqual([(e["session"], e["visit"]) for e in resumed], [(session, 1)])
        self.assertEqual([e["step"] for e in run.events(root) if e["event"] == "step_entered"],
                         ["start", "issue", "direct-lane", "verification", "landing", "closing"])
        self.assertEqual(run.pulls()[0]["state"], "MERGED")

    def test_a_delivery_cut_while_the_issue_was_parked_does_not_resume_the_open_implement_session(self):
        run = self.stubbed(replies={"implement": {**IMPLEMENTED, "sleep": FOREVER}})
        self.cut_at(run, "direct", "implement")
        run.park()

        done = run.deliver()

        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertEqual(len([launch for launch in run.launches() if launch["key"] == "implement"]), 1)
        direct = self.child(run, "direct")
        self.assertEqual([e for e in run.events(direct) if e["event"] == "session_resuming"], [])
        self.assertIn(("preflight", "parked"), run.transitions(direct))

    def test_an_unrelated_advance_of_the_main_checkout_during_the_cut_keeps_the_open_implement_session(self):
        run = self.stubbed(replies={"implement": {**IMPLEMENTED, "sleep": FOREVER}})
        self.cut_at(run, "direct", "implement")
        run.world.git(run.fixture.root, "commit", "--quiet", "--allow-empty", "-m", "unrelated")
        run.world.git(run.fixture.root, "push", "--quiet", "origin", "main")

        run.deliver()  # it later stops at the landing, behind the advanced main: not what this case is about

        launches = [launch for launch in run.launches() if launch["key"] == "implement"]
        self.assertEqual(len(launches), 2)
        self.assertIn("--resume", launches[1]["argv"])
        self.assertEqual(self.procedures_of(run)["direct"], 1)
        self.assertEqual([e["visit"] for e in run.events(self.child(run, "direct"))
                          if e["event"] == "step_entered" and e["step"] == "implement"], [1])

    def test_a_delivery_cut_in_a_code_only_close_out_after_its_merge_changes_nothing_the_uninterrupted_one_does_not(self):
        whole = self.stubbed()
        self.finish(whole, "done")
        run = self.stubbed()
        run.deliver_until(lambda: self.entered(run, "close-out", "hold-facts"), poll=0.005)
        root = run.runs()[0]
        self.assertNotIn("run_done", [e["event"] for e in run.events(root)])
        self.assertEqual([pull["state"] for pull in run.pulls()], ["MERGED"])
        events = len(run.events(root))
        children = self.procedures_of(run)
        claims = len(run.claims())
        comments = [comment["id"] for comment in run.forge.stored()]

        self.finish(run, "done")

        after = run.events(root)[events:]
        self.assertEqual([e["step"] for e in after if e["event"] == "step_entered"], [])
        self.assertEqual([(e["step"], e["outcome"]) for e in after if e["event"] == "transition_taken"],
                         [("closing", "done")])
        self.assertEqual(self.procedures_of(run), children)
        self.assertEqual(children["setup"], 1)
        self.assertEqual(claims, 1)
        self.assertEqual(len(run.pulls()), 1)
        ids = [comment["id"] for comment in run.forge.stored()]
        self.assertEqual(ids[:len(comments)], comments)
        self.assertEqual(ids, [comment["id"] for comment in whole.forge.stored()])
        self.assertEqual(self.branch_refs(run), self.branch_refs(whole))
        self.assertEqual(len(self.released_claims(run)), len(self.released_claims(whole)))
        self.assertEqual(self.end_state(run), self.end_state(whole))


if __name__ == "__main__":
    unittest.main()
