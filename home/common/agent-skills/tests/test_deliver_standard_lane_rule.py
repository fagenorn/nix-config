"""deliver-standard.js takes a lane-less fresh run's lane from the lane rule.

The program runs under the node harness against stub agents. The helpers come from the program test module,
imported as a module so that unittest does not collect its test classes a second time.
Run: just agent-workflow-tests
"""

from __future__ import annotations

import copy
import re
import unittest

from . import test_deliver_standard_program as program

TIER = "integration"

LANE_RULE_ARGV = re.compile(r"\bissue-setup lane --repo-root (\S+) --repo \S+ --issue (\d+)\b")
ARGS = program.ARGS
run, run_out, labels, prompt = program.run, program.run_out, program.labels, program.prompt
LIVE_PATCH = program.LIVE_PATCH


RULE_DIRECT = {"verdict": "direct", "reason": "named files 1 of at most 3"}


class LaneRuleTest(unittest.TestCase):
    """A lane-less fresh run outside plan mode takes the lane rule's direct or standard lane."""

    def test_a_lane_less_run_takes_the_rules_direct_lane(self):
        out = run_out(ARGS, None, {"setup": {"lane_rule": RULE_DIRECT}})
        names = labels(out["calls"])
        self.assertEqual(LANE_RULE_ARGV.findall(prompt(out["calls"], "setup")), [("/r", "9")])
        self.assertIn("direct-impl", names)
        self.assertFalse([l for l in names if l.startswith("plan")], names)
        self.assertEqual(out["result"]["stage"], "done")

    def test_the_rules_reason_reaches_the_log(self):
        out = run_out(ARGS, None, {"setup": {"lane_rule": RULE_DIRECT}})
        self.assertTrue([line for line in out["logs"] if "named files 1 of at most 3" in line], out["logs"])

    def test_an_explicit_lane_wins_and_reads_no_rule(self):
        for lane, rule, label in (("standard", "direct", "plan"), ("direct", "standard", "direct-impl")):
            with self.subTest(lane=lane):
                _, calls = run(args=dict(ARGS, lane=lane), patch={"setup": {"lane_rule": {"verdict": rule, "reason": "r"}}})
                self.assertEqual(LANE_RULE_ARGV.findall(prompt(calls, "setup")), [])
                self.assertIn(label, labels(calls))

    def test_a_cont_keeps_its_lane_and_reads_no_rule(self):
        planned, _ = run(args=dict(ARGS, mode="plan"))
        _, calls = run(args=dict(ARGS, cont=planned["cont"]), patch={"setup": {"lane_rule": RULE_DIRECT}})
        self.assertEqual(LANE_RULE_ARGV.findall(prompt(calls, "setup")), [])
        self.assertNotIn("direct-impl", labels(calls))

    def test_plan_mode_with_no_lane_reads_no_rule(self):
        result, calls = run(args=dict(ARGS, mode="plan"), patch={"setup": {"lane_rule": RULE_DIRECT}})
        self.assertEqual(result["stage"], "planned")
        self.assertEqual(LANE_RULE_ARGV.findall(prompt(calls, "setup")), [])

    def test_a_spec_or_fresh_decisions_keep_the_standard_lane_and_read_no_rule(self):
        for name, extra in (("spec", {"spec": "docs/specs/x.md"}), ("decisions", {"decisions": "use the cache"})):
            with self.subTest(given=name):
                _, calls = run(args=dict(ARGS, **extra), patch={"setup": {"lane_rule": RULE_DIRECT}})
                self.assertEqual(LANE_RULE_ARGV.findall(prompt(calls, "setup")), [])
                self.assertIn("plan", labels(calls))
                self.assertNotIn("direct-impl", labels(calls))

    def test_a_standard_or_unreadable_rule_keeps_the_standard_lane(self):
        for name, rule in (("standard", {"verdict": "standard", "reason": "r"}), ("error", {"verdict": "error", "reason": "e"}),
                           ("not an object", "direct"), ("absent", None)):
            with self.subTest(rule=name):
                patch = {"setup": {} if rule is None else {"lane_rule": rule}}
                _, calls = run(args=ARGS, patch=patch)
                self.assertIn("plan", labels(calls))
                self.assertNotIn("direct-impl", labels(calls))

    def test_a_declared_live_fault_keeps_the_live_lane_over_the_rule(self):
        patch = copy.deepcopy(LIVE_PATCH)
        patch["setup"]["lane_rule"] = {"verdict": "direct", "reason": "r"}
        result, calls = run(args=ARGS, patch=patch)
        self.assertEqual(result["stage"], "done")
        self.assertEqual([c["label"] for c in calls if c["agentType"] == "implementer"], ["live-impl"])
        self.assertNotIn("direct-impl", labels(calls))
        result, _ = run(args=ARGS, patch={"setup": {"live_fault": {"verdict": "error", "detail": "down"}, "lane_rule": RULE_DIRECT}})
        self.assertEqual(result["stage"], "live-fault")
        self.assertEqual(result["cont"]["lane"], "live")

    def test_the_rule_read_is_not_kept_in_the_cont(self):
        result, _ = run(args=ARGS, patch={"setup": {"lane_rule": RULE_DIRECT, "claim": {"ok": False, "reason": "worktree"}}})
        self.assertEqual(result["cont"]["lane"], "direct")
        self.assertNotIn("lane_rule", result["cont"]["setup"])
