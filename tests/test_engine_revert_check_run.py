"""Scenario tests for the revert-check steps of the shipped `direct` procedure, run as a whole stubbed
`engine deliver` on the fixture project (`tests/engine_stubbed_world.py`). The module judges no procedure's step
coverage: the runs of `tests/test_engine_stubbed_run.py` pass through every revert-check step, and its own teardown
fails naming one no run visits."""

from __future__ import annotations

import sys
import unittest

from tests.engine_fixture import AdoptedFixtures
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import StepCoverage
from tests.engine_stubbed_world import StubbedRun
from tests.engine_verify_fixtures import implementing
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_stubbed_run import CLEAN_REREVIEW, Scenario, committing, lite_findings

TIER = "integration"  # every case builds a repository and runs the engine as a child process

FIXTURES = AdoptedFixtures()
STEPS = StepCoverage(PROCEDURES, ())


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)


KEPT = ('import unittest\n\nfrom fixture.greet import greet\n\n\nclass KeptCheck(unittest.TestCase):\n'
        '    def test_greet_still_greets(self):\n        self.assertEqual(greet("Ada"), "Hello, Ada.")\n')
KEPT_ID = "checks.check_kept.KeptCheck.test_greet_still_greets"
SECOND = ('import unittest\n\n\nclass SecondCheck(unittest.TestCase):\n'
          '    def test_second_runs(self):\n        self.assertTrue(True)\n')
SECOND_ID = "checks.check_second.SecondCheck.test_second_runs"


class RevertCheckTest(Scenario):
    def test_the_review_after_the_revert_check_names_a_new_test_that_passes_without_its_source(self):
        run = self.stubbed(replies={"implement": implementing("checks/check_kept.py", KEPT)})

        self.finish(run, "done")

        direct = self.child(run, "direct")
        checked = self.stored(direct, "revert-check")
        self.assertEqual((checked["still_passing"], checked["new_tests"], checked["reason"]),
                         ([KEPT_ID], [KEPT_ID], ""))
        self.assertIn(KEPT_ID, self.launch(run, "lite-review")["prompt"])
        transitions = run.transitions(direct)
        self.assertIn(("revert-check", "ok"), transitions)
        self.assertLess(transitions.index(("revert-check", "ok")), transitions.index(("implemented", "lite")))

    def test_a_fix_that_moves_the_head_runs_the_check_again_before_the_re_review_and_adds_no_review_round(self):
        run = self.stubbed(replies={
            "implement": implementing("checks/check_kept.py", KEPT),
            "lite-review": lite_findings(),
            "lite-fix": committing("checks/check_second.py", SECOND),
            "lite-rereview": CLEAN_REREVIEW})

        self.finish(run, "done")

        self.assertEqual(self.keys(run), ["applies", "implement", "lite-review", "lite-fix", "lite-rereview"])
        direct = self.child(run, "direct")
        wanted = {"implement", "revert-check", "lite-review", "lite-fix", "lite-revert-check", "lite-rereview"}
        entered = [e["step"] for e in StubbedRun.events(direct) if e["event"] == "step_entered" and e["step"] in wanted]
        self.assertEqual(entered, ["implement", "revert-check", "lite-review", "lite-fix", "lite-revert-check",
                                   "lite-rereview"])
        first, second = self.stored(direct, "revert-check"), self.stored(direct, "lite-revert-check")
        self.assertEqual(first["head"], self.stored(direct, "implement")["commit"])
        self.assertEqual(second["head"], self.stored(direct, "lite-fix")["commit"])
        self.assertNotEqual(second["head"], first["head"])
        self.assertEqual(first["still_passing"], [KEPT_ID])
        self.assertEqual(second["new_tests"], [KEPT_ID, SECOND_ID])
        self.assertEqual(second["still_passing"], [KEPT_ID, SECOND_ID])
        prompt = self.launch(run, "lite-rereview")["prompt"]
        self.assertIn(KEPT_ID, prompt)
        self.assertIn(SECOND_ID, prompt)


if __name__ == "__main__":
    unittest.main()
