"""A re-review finding on a criterion of another kind than code, in a stubbed direct run.

The cases live here to keep tests/test_engine_stubbed_run.py under the size budget (rule B17). They run no
`deliver` procedure, so the module's coverage scope is empty and its runs take their fixtures from its own
`FIXTURES`.
"""

from __future__ import annotations

import sys
import unittest

from agent_tools.verification import verify_block
from tests.engine_fixture import AdoptedFixtures
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import StepCoverage
from tests.engine_stubbed_world import EVIDENCE_BODY, EVIDENCE_CHECK, IMPLEMENTED
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_stubbed_run import (
    CLEAN_FULL, FINDING, Scenario, committing, held_label, hold_comments)

TIER = "integration"  # every case builds a repository and runs the engine and the fake forge as child processes

FIXTURES = AdoptedFixtures()
STEPS = StepCoverage(PROCEDURES, ())

EVIDENCE_CRITERION = {"id": "AC2", "text": "the owner has seen the greeting", "kind": "evidence",
                      "result": "needs an activation, so it is a hold"}
EVIDENCE_FINDING = {"severity": "important", "file": "fixture/farewell.py:2",
                    "failing_input": "gh pr list --state merged",
                    "summary": "AC2 is evidence-kind and still has no evidence", "kind": "other",
                    "restates": "AC2"}


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)


class NonCodeFindingTest(Scenario):
    def run_with(self, rereview_finding: dict):
        reply = dict(IMPLEMENTED["reply"], sensitive=True,
                     acceptance=[*IMPLEMENTED["reply"]["acceptance"], EVIDENCE_CRITERION])
        return self.stubbed(body=EVIDENCE_BODY, replies={
            "implement": dict(IMPLEMENTED, reply=reply),
            "full-review": dict(CLEAN_FULL, verdict="findings", findings=[FINDING]),
            "full-fix": committing("fixture/second.py", "SECOND = 2\n"),
            "full-rereview": {"verdict": "findings", "findings": [rereview_finding]}})

    def settled_event(self, run) -> dict:
        direct = self.child(run, "direct")
        taken = [event for event in run.events(direct)
                 if event["event"] == "transition_taken" and event["step"] == "full-settled"]
        self.assertEqual(len(taken), 1)
        return taken[0]

    def test_a_re_review_finding_on_an_evidence_criterion_is_dropped_and_the_run_holds_that_criterion(self):
        run = self.run_with(EVIDENCE_FINDING)

        self.finish(run, "done")

        self.assertIn(("full-settled", "clean"), run.transitions(self.child(run, "direct")))
        self.assertEqual(self.settled_event(run)["dropped"],
                         [{"finding": "full-rereview:1", "criteria": ["AC2"]}])
        self.assertEqual(run.pulls()[0]["state"], "MERGED")
        closing = run.transitions(self.child(run, "close-out"))
        self.assertIn(("hold-draft", "drafted"), closing)
        self.assertIn(("hold-post", "posted"), closing)
        self.assertTrue(held_label(run))
        block = {"v": 1, "merge": run.pulls()[0]["mergeCommit"]["oid"], "checks": [EVIDENCE_CHECK]}
        self.assertEqual(verify_block.parse_block(hold_comments(run)[0]["body"]), (block, []))

    def test_a_re_review_finding_on_a_code_criterion_still_stops_direct_review(self):
        run = self.run_with(dict(EVIDENCE_FINDING, summary="AC1 has no evidence", restates="AC1"))

        self.finish(run, "direct-review", "owner-decision")

        self.assertEqual(run.transitions(self.child(run, "direct"))[-1], ("full-settled", "findings"))
        self.assertNotIn("dropped", self.settled_event(run))
        self.assertEqual(run.pulls(), [])


if __name__ == "__main__":
    unittest.main()
