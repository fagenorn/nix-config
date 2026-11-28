"""Contract tests for what the plan and plan-revise steps are handed: the setup facts and the routed set."""

from __future__ import annotations

import json
import unittest

from tests.engine_fixture import AdoptedFixtures
from tests.engine_plan_fixtures import REFUSED_REPLIES
from tests.engine_stubbed_world import APPLIES, StubbedRun
from tests.guard_policy_world import REPO_ROOT, install_platform_manifest_in_environ

TIER = "integration"  # every case but the last runs the engine

FIXTURES = AdoptedFixtures()
PROCEDURES = REPO_ROOT / "python/agent_tools/delivery/procedures"
BODY = ("Add a greet() to `fixture/greet.py`, next to `secrets/x.yaml`.\n\n## Acceptance criteria\n\n"
        "- [ ] [code] greet() returns the greeting\n")
PLAN_STEPS = ("plan", "plan-revise")
PLAN_MEMBERS = {"id", "stage", "kind", "role", "prompt", "reply", "outcome_from", "holds", "mutates", "in", "on"}
APPENDED = ["start.details", "start.merged_refs", "plan-preflight.routed", "plan-preflight.route_detail"]


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def install_platform(run: StubbedRun) -> None:
    """The platform standards the router reads: the bar and the Python shard a `.py` path routes to."""
    standards = run.world.home / ".agents/standards"
    (standards / "stacks").mkdir(parents=True)
    (standards / "the-bar.md").write_text("# The bar\n\n### B1. One\n\nbody\n", encoding="utf-8")
    (standards / "stacks/python.md").write_text("# Python\n\n### P1. One\n\nbody\n", encoding="utf-8")


def procedure(name: str) -> dict:
    return json.loads((PROCEDURES / f"{name}.json").read_text(encoding="utf-8"))


def step(doc: dict, step_id: str) -> dict:
    return next(item for item in doc["steps"] if item["id"] == step_id)


class PlanFactsTest(unittest.TestCase):
    def refused(self, **members) -> tuple[StubbedRun, dict]:
        run = StubbedRun(self, fixtures=FIXTURES, body=BODY, **members)
        install_platform(run)
        done = run.deliver()
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        line = run.line(done)
        self.assertEqual((line["end"], line["need"]), ("plan-refused", "owner-decision"), line)
        return run, line

    def first_prompts(self, run: StubbedRun) -> dict[str, str]:
        launches = run.launches()
        return {key: next(launch for launch in launches if launch["key"] == key)["prompt"] for key in PLAN_STEPS}

    def test_the_plan_and_revise_prompts_carry_the_setup_details_and_the_merged_references(self):
        fact = "SETUP FACT: greet() is still missing from fixture/greet.py."
        pulls = [{"number": 5, "state": "MERGED", "headRefName": "docs-5", "closingIssuesReferences": []}]

        run, _ = self.refused(replies={**REFUSED_REPLIES, "applies": dict(APPLIES, details=fact)}, pulls=pulls)

        for key, prompt in self.first_prompts(run).items():
            self.assertIn(fact, prompt, key)
            self.assertIn('[{"closes":false,"number":5}]', prompt, key)

    def test_the_plan_and_revise_prompts_carry_the_routed_set_of_the_files_the_issue_names(self):
        run, _ = self.refused(replies=REFUSED_REPLIES)

        python_shard = str(run.world.home / ".agents/standards/stacks/python.md")
        for key, prompt in self.first_prompts(run).items():
            self.assertIn('"change":{"diff":null,"paths":["fixture/greet.py","secrets/x.yaml"]}', prompt, key)
            self.assertIn(python_shard, prompt, key)

    def test_the_plan_steps_read_the_setup_snapshot_route_only_while_planning_and_carry_no_spend_ceiling(self):
        deliver = procedure("deliver")

        self.assertEqual(step(deliver, "start")["returns"], ["applies.details", "preflight.merged_refs"])
        for key in PLAN_STEPS:
            planned = step(deliver, key)
            self.assertEqual(planned["in"][-4:], APPENDED, key)
            self.assertNotIn("plan-preflight.merged_refs", planned["in"], key)
            self.assertEqual(planned["role"], "planner", key)
            self.assertLessEqual(set(planned), PLAN_MEMBERS, key)
        self.assertEqual(step(deliver, "plan-preflight")["subcommand"], "plan-preflight")
        for name in ("setup", "direct", "verify"):
            self.assertEqual(step(procedure(name), "preflight")["subcommand"], "preflight", name)
        self.assertNotIn("plan-over-budget", deliver["stops"])


if __name__ == "__main__":
    unittest.main()
