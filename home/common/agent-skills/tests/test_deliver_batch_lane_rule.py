"""deliver-batch.js takes each issue's lane from the lane rule's verdict at intake.

The helpers come from the program test module, imported as a module so that unittest does not collect its test
classes a second time. Run: just agent-workflow-tests
"""

from __future__ import annotations

import re
import unittest

from . import test_deliver_batch_program as batch

TIER = "integration"

LANE_RULE_ARGV = re.compile(r"\bissue-setup lane --repo-root (\S+) --repo (\S+) --issue (\d+)\b")


class IntakeLaneRuleTest(unittest.TestCase):
    """#1675: facts-n answers the lane the rule chose; needs-design is still refused."""

    def test_the_facts_lane_is_the_lane_rules_verdict(self):
        _, calls, _ = batch.run(patch={"facts-1": {"lane": "direct", "why": "named files 1 of at most 3"}})
        self.assertEqual(LANE_RULE_ARGV.findall(batch.prompt(calls, "facts-1")), [("/r", "owner/repo", "1")])
        args = batch.child(calls, 1)["args"]
        self.assertEqual(args["lane"], "direct")
        self.assertNotIn("cont", args)

    def test_needs_design_is_still_refused_with_the_rule(self):
        result, calls, _ = batch.run(patch={"facts-1": {"lane": "needs-design", "why": "no criteria"}})
        self.assertEqual(batch.row(result, 1)["outcome"], "needs-design")
        self.assertNotIn("child-1", batch.labels(calls))
        self.assertNotIn("acquire-1", batch.labels(calls))

    def test_a_standard_rule_reaches_the_child_as_its_explicit_lane(self):
        _, calls, _ = batch.run(patch={"facts-1": {"lane": "standard",
                                             "why": "acceptance criteria 4, over the 3 of the direct lane"}})
        first = next(c for c in calls if c["label"] == "child-1")
        self.assertEqual(first["args"]["lane"], "standard")

    def test_a_declared_live_fault_with_a_direct_rule_is_still_left_out(self):
        result, calls, _ = batch.run(patch={"facts-1": {"lane": "direct", "why": "r",
                                                        "live_fault": {"verdict": "declared"}}})
        self.assertEqual(batch.row(result, 1)["outcome"], "live-fault")
        self.assertEqual(batch.row(result, 1)["reason"], batch.LIVE_ROW)
        self.assertNotIn("acquire-1", batch.labels(calls))
        self.assertNotIn("child-1", batch.labels(calls))
