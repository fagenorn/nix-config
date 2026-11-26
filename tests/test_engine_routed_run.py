"""Scenario tests for the route steps of the shipped `direct` procedure, each run as a whole stubbed
`engine deliver` on the fixture project (`tests/engine_stubbed_world.py`): the routed files each briefed step
reads are the router's answer for the head it works on, at the stage it works in, and a continue reuses or
renews that answer by the head. The route steps' visits are checked by `test_engine_stubbed_run`'s coverage,
whose runs pass through every one of them, so this module declares no steps of its own."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

from agent_tools.delivery import independent_review
from tests.engine_fixture import AdoptedFixtures
from tests.engine_guards import payloads
from tests.engine_procedure_copies import stopping_after_verify
from tests.engine_step_coverage import StepCoverage
from tests.engine_stubbed_world import IMPLEMENTED, StubbedRun
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_stubbed_run import (
    CLEAN_REREVIEW, PROCEDURES, UNNAMED_LITE, Scenario, committing, lite_findings)

TIER = "integration"  # every run case builds a repository and runs the engine as a child process

FIXTURES = AdoptedFixtures()
STEPS = StepCoverage(PROCEDURES, ())


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)


PREFIX = "Routed files (the standards, hints and decision records routed to this change; read them and no other standards): "
CODEX_CLEAN = {"stdout": json.dumps({"status": 0, "touchedFiles": [],
                                     "runtime": {"model": independent_review.MODEL,
                                                 "reasoningEffort": independent_review.EFFORT},
                                     "rawOutput": "## Critical\nNone.\n## Important\nNone.\n## Minor\nNone.\n"}),
               "exit": 0}
NO_COMMIT = {"reply": {"status": "done", "notes": "n", "tests": [], "declines": []}, "same_head": {}}
BLOCKED = {"reply": {"status": "blocked", "notes": "n", "tests": [], "declines": []}, "same_head": {}}
NODE = "export const hi = 1;\n"


def routed_of(prompt: str) -> list[str]:
    line = next(line for line in prompt.splitlines() if line.startswith(PREFIX))
    return json.loads(line[len(PREFIX):])


def routed_section(stdin: str) -> list[str]:
    lines = stdin.splitlines()
    rest = lines[lines.index("Routed files:") + 1:]
    return rest[:rest.index("")] if "" in rest else rest


def stored_event(run_dir: Path, step: str, visit: int = 1) -> dict:
    return next(e for e in StubbedRun.events(run_dir)
                if e["event"] == "result_stored" and (e["step"], e["visit"]) == (step, visit))


def router_answer(run: StubbedRun, stage: str, head: str) -> dict:
    done = subprocess.run(
        [sys.executable, "-m", "agent_tools.delivery.router", "--repo-root", str(run.worktree_path),
         "--stage", stage, "--diff", f"refs/remotes/origin/main...{head}",
         "--platform-standards", str(run.world.home / ".agents/standards")],
        capture_output=True, text=True, env=run.env, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.splitlines()[-1])


class RouteTest(Scenario):
    def test_the_sessions_of_the_reviewed_head_get_the_same_routed_files(self):
        run = self.stubbed(review_code=[CODEX_CLEAN],
                           extra_files={".agents/knowledge/hints/building.md": "Building hint.\n"},
                           replies={"lite-review": lite_findings(),
                                    "lite-fix": committing("fixture/greeting.js", NODE),
                                    "lite-rereview": CLEAN_REREVIEW})
        procedures = stopping_after_verify(run.tmp)

        self.stopped(run, run.deliver(procedures), "verified", "owner-decision")

        direct = self.child(run, "direct")
        standards = run.world.home / ".agents/standards"
        hint = f"{run.worktree_path}/.agents/knowledge/hints/building.md"
        building = self.stored(direct, "route")["routed_files"]
        start = self.stored(direct, "implement")["start_head"]
        self.assertEqual(stored_event(direct, "route")["head"], start)
        self.assertEqual(routed_of(self.launch(run, "implement")["prompt"]), building)
        self.assertEqual(router_answer(run, "building", start)["routed_files"], building)
        self.assertIn(hint, building)
        head = stored_event(direct, "route-lite")["head"]
        self.assertEqual(head, self.stored(direct, "implement")["commit"])
        routed = self.stored(direct, "route-lite")["routed_files"]
        self.assertEqual(self.stored(direct, "route-lite")["change"]["diff"], f"refs/remotes/origin/main...{head}")
        self.assertEqual(router_answer(run, "final review", head)["routed_files"], routed)
        self.assertIn(f"{standards}/stacks/python.md", routed)
        self.assertNotIn(hint, routed)
        self.assertEqual(routed_of(self.launch(run, "lite-review")["prompt"]), routed)
        self.assertEqual(routed_of(self.launch(run, "lite-fix")["prompt"]), routed)
        reviews = [shlex.split(p["payload"]["tool_input"]["command"]) for p in payloads(run.guard_log)]
        reviews = [argv for argv in reviews if "agent_tools.delivery.independent_review" in argv]
        self.assertEqual(len(reviews), 1)
        self.assertEqual(json.loads(reviews[0][reviews[0].index("--routed-files") + 1]), routed)
        stdin = run.companion_launches()[0]["stdin"]
        self.assertEqual(routed_section(stdin), routed)
        self.assertIn(f"Head: {head}", stdin)
        self.assertNotIn("Standards:", stdin)
        fixed = self.stored(direct, "route-lite-fixed")["routed_files"]
        self.assertIn(f"{standards}/stacks/node.md", fixed)
        self.assertNotEqual(fixed, routed)
        self.assertEqual(routed_of(self.launch(run, "lite-rereview")["prompt"]), fixed)

    def test_a_fix_that_commits_nothing_reuses_the_review_route(self):
        run = self.stubbed(replies={"lite-review": lite_findings(), "lite-fix": NO_COMMIT,
                                    "lite-rereview": CLEAN_REREVIEW})

        self.stopped(run, run.deliver(stopping_after_verify(run.tmp)), "verified", "owner-decision")

        direct = self.child(run, "direct")
        self.assertEqual(stored_event(direct, "route-lite-fixed")["reused_from"],
                         {"run": direct.name, "step": "route-lite", "visit": 1})
        started = [e["step"] for e in StubbedRun.events(direct) if e["event"] == "process_started"]
        self.assertNotIn("route-lite-fixed", started)
        self.assertEqual(routed_of(self.launch(run, "lite-rereview")["prompt"]),
                         self.stored(direct, "route-lite")["routed_files"])

    def test_a_blocked_fix_stops_direct_fix_without_routing_again(self):
        run = self.stubbed(replies={"lite-review": lite_findings(), "lite-fix": BLOCKED})

        self.finish(run, "direct-fix", "owner-decision")

        direct = self.child(run, "direct")
        self.assertIn(("lite-fixed", "not-done"), run.transitions(direct))
        entered = [e["step"] for e in StubbedRun.events(direct) if e["event"] == "step_entered"]
        self.assertNotIn("route-lite-fixed", entered)
        self.assertNotIn("lite-rereview", self.keys(run))

    def test_a_route_that_fails_stops_route_failed_before_its_review(self):
        run = self.stubbed()
        (run.world.home / ".agents/standards/stacks/python.md").unlink()

        self.finish(run, "route-failed", "owner-decision")

        self.assertNotIn("lite-review", self.keys(run))


class RouteContinueTest(Scenario):
    def first_stop(self, run: StubbedRun) -> None:
        self.finish(run, "direct-review", "owner-decision")

    def second_stop(self, run: StubbedRun) -> None:
        run.answer("implement", {"reply": IMPLEMENTED["reply"], "same_head": {}})
        self.finish(run, "direct-review", "owner-decision")

    def last_review(self, run: StubbedRun) -> dict:
        return [launch for launch in run.launches() if launch["key"].startswith("lite-review")][-1]

    def test_a_continue_at_the_same_head_reuses_the_review_route(self):
        run = self.stubbed(replies={"lite-review": UNNAMED_LITE})
        self.first_stop(run)
        self.second_stop(run)

        first, second = self.child(run, "direct"), self.child(run, "direct", last=True)
        implements = [launch for launch in run.launches() if launch["key"] == "implement"]
        continued = [e for e in StubbedRun.events(run.runs()[0]) if e["event"] == "run_continued"]
        self.assertEqual(continued[-1]["step"], "start")
        self.assertNotEqual(first, second)
        self.assertEqual(stored_event(second, "route-lite")["reused_from"],
                         {"run": first.name, "step": "route-lite", "visit": 1})
        started = {child: [e["step"] for e in StubbedRun.events(child) if e["event"] == "process_started"]
                   for child in (first, second)}
        self.assertNotIn("route-lite", started[second])
        self.assertEqual(sum(steps.count(name) for steps in started.values() for name in ("route", "route-lite")), 3)
        self.assertNotEqual(stored_event(first, "route")["head"], stored_event(second, "route")["head"])
        self.assertEqual(stored_event(second, "route")["head"], stored_event(first, "route-lite")["head"])
        self.assertEqual(stored_event(second, "route")["head"], self.stored(second, "implement")["start_head"])
        self.assertEqual(routed_of(implements[-1]["prompt"]), self.stored(second, "route")["routed_files"])
        self.assertEqual(routed_of(self.last_review(run)["prompt"]), self.stored(first, "route-lite")["routed_files"])

    def test_a_continue_after_a_new_commit_routes_again_before_the_next_briefed_step(self):
        run = self.stubbed(replies={"lite-review": UNNAMED_LITE})
        self.first_stop(run)
        (run.worktree_path / "fixture/greeting.js").write_text(NODE, encoding="utf-8")
        run.world.git(run.worktree_path, "add", "fixture/greeting.js")
        run.world.git(run.worktree_path, "-c", "user.name=stub", "-c", "user.email=stub@example.invalid",
                      "commit", "-q", "-m", "a new commit")
        new = run.world.git(run.worktree_path, "rev-parse", "HEAD").strip()
        self.second_stop(run)

        first, second = self.child(run, "direct"), self.child(run, "direct", last=True)
        implements = [launch for launch in run.launches() if launch["key"] == "implement"]
        node = f"{run.world.home}/.agents/standards/stacks/node.md"
        events = StubbedRun.events(second)
        started = [e["step"] for e in events if e["event"] == "process_started"]
        entered = [e["step"] for e in events if e["event"] == "step_entered"]
        for name in ("route", "route-lite"):
            self.assertIn(name, started)
            self.assertNotIn("reused_from", stored_event(second, name))
            self.assertIn(node, self.stored(second, name)["routed_files"])
            self.assertNotIn(node, self.stored(first, name)["routed_files"])
        self.assertEqual(stored_event(second, "route")["head"], new)
        self.assertEqual(self.stored(second, "implement")["start_head"], new)
        self.assertEqual(routed_of(implements[-1]["prompt"]), self.stored(second, "route")["routed_files"])
        self.assertLess(entered.index("route"), entered.index("implement"))
        self.assertLess(entered.index("route-lite"), entered.index("lite-review"))
        self.assertEqual(routed_of(self.last_review(run)["prompt"]), self.stored(second, "route-lite")["routed_files"])


if __name__ == "__main__":
    unittest.main()
