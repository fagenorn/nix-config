"""Scenario tests for the shipped outline route: `engine deliver --plan outline` on the fixture project.

Each case runs the engine as a child process against a built fixture project, a fake tracker and a stubbed launcher
(`tests/engine_stubbed_world.py`) and reads what the run left: the root run and its `outline-build` and
`outline-slice` children, the launches and the pull request. The module's coverage judges the three outline
procedures: its teardown fails while a step of any of them is unvisited.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from collections.abc import Iterator
from pathlib import Path

from agent_tools.delivery import engine_session, issue_setup
from tests.engine_fixture import AdoptedFixtures
from tests.engine_outline_fixtures import (DESIGN_FINDINGS, DESIGN_PASS, OUTLINE, READS, SLICE_ONE, SLICE_TWO,
                                           TWO_CRITERIA_BODY, TWO_SLICES, UNMAPPED, UNPROVEN, with_reads)
from tests.engine_plan_fixtures import NOHUP_PLAN_TEXT
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import StepCoverage
from tests.engine_stubbed_world import APPLIES, IMPLEMENTED, StubbedRun
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_plan_facts import PLAN_MEMBERS
from tests.test_engine_stubbed_run import (CLEAN_LITE, CLEAN_REREVIEW, SHA, Scenario, committing, full_findings,
                                           lite_findings, model_of)

TIER = "integration"  # every case builds a repository and runs the engine as a child process

FIXTURES = AdoptedFixtures()
STEPS = StepCoverage(PROCEDURES, ("outline", "outline-build", "outline-slice"))
STANDARD = ("Add a greet() function to the fixture module, next to `secrets/x.yaml`.\n\n"
            "## Acceptance criteria\n\n- [ ] [code] greet() returns the greeting\n")
BLOCKED_BUILD = {"status": "blocked", "start_head": SHA, "commit": SHA, "notes": "n", "acceptance": [],
                 "sensitive": False, "ineligible": False, "tests": []}
ROOT_ORDER = ["start", "plan-preflight", "outline", "outline-read", "design-review", "outline-note", "build",
              "verification", "landing", "closing"]


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)


def part_finished() -> None:
    STEPS.finish_part(sys.modules[__name__], Scenario)


def building(path: str, text: str) -> dict:
    """An implementer entry that commits `text` to `path` and reports the default acceptance."""
    return {"reply": dict(IMPLEMENTED["reply"]), "commit": {"path": path, "text": text}}


def procedure_of(run_dir: Path) -> str:
    return json.loads((run_dir / "run.json").read_text("utf-8"))["procedure"]


def session_of(launch: dict) -> str:
    argv = launch["argv"]
    return argv[argv.index("--resume" if "--resume" in argv else "--session-id") + 1]


def procedure_document(name: str) -> dict:
    return json.loads((PROCEDURES / f"{name}.json").read_text("utf-8"))


class OutlineScenario(Scenario):
    def outlined(self, replies: dict | None = None, body: str = STANDARD, reads: bool = False, **members) -> StubbedRun:
        """A run on a standard-lane body: the outline passes its design review and the implementer commits."""
        given = {"outline": OUTLINE, "design-review": DESIGN_PASS, "build": IMPLEMENTED, **(replies or {})}
        run = self.stubbed(body=body, replies=given, **members)
        if reads:
            run.answer("outline", with_reads(given["outline"], run.worktree_path))
        return run

    def finish(self, run: StubbedRun, end: str, need: str | None = None) -> dict:
        done = run.deliver(plan="outline")
        if need is None:
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(run.line(done)["end"], end)
            return run.line(done)
        return self.stopped(run, done, end, need)

    def descendants(self, run: StubbedRun, parent: Path) -> Iterator[Path]:
        for child in run.children(parent):
            yield child
            yield from self.descendants(run, child)

    def named(self, run: StubbedRun, procedure: str) -> list[Path]:
        return [child for child in self.descendants(run, run.runs()[0]) if procedure_of(child) == procedure]

    def entered(self, run: StubbedRun, run_dir: Path) -> list[str]:
        return [e["step"] for e in run.events(run_dir) if e["event"] == "step_entered"]

    def launched(self, run: StubbedRun, key: str) -> list[dict]:
        return [launch for launch in run.launches() if launch["key"] == key]

    def committed(self, run: StubbedRun, path: str) -> list[str]:
        """The non-merge commits on the origin's `main` that touch `path`."""
        return run.world.git(run.fixture.root, "--git-dir", run.bare, "log", "--no-merges", "--format=%H", "main",
                             "--", path).split()

    def sessions(self, run: StubbedRun, run_dir: Path, step: str) -> int:
        return len([e for e in run.events(run_dir) if e["event"] == "session_starting" and e["step"] == step])


class OutlineWalkTest(OutlineScenario):
    def test_plan_outline_walks_outline_graders_design_review_build_review_verify_and_landing_to_done(self):
        run = self.outlined(reads=True)

        line = self.finish(run, "done")

        self.assertEqual(line["end"], "done")
        root = run.runs()[0]
        entered = self.entered(run, root)
        self.assertEqual([step for step in entered if step in ROOT_ORDER], ROOT_ORDER)
        transitions = run.transitions(root)
        graded = [transitions.index(edge) for edge in (("outline-mapped", "mapped"), ("outline-proven", "proven"))]
        self.assertEqual(graded, sorted(graded))
        self.assertLess(graded[1], transitions.index(("design-review", "pass")))
        build = self.named(run, "outline-build")
        self.assertEqual(len(build), 1)
        self.assertEqual(self.entered(run, build[0])[:3], ["preflight", "build-slices", "implement"])
        self.assertIn(("implemented", "lite"), run.transitions(build[0]))
        self.assertEqual(len(self.named(run, "outline-slice")), 1)
        self.assertEqual([pull["state"] for pull in run.pulls()], ["MERGED"])
        review = self.launched(run, "design-review")
        self.assertEqual(len(review), 1)
        self.assertEqual(model_of(review[0]), "sonnet")
        argv = review[0]["argv"]
        self.assertIn("**Design review**", Path(argv[argv.index("--append-system-prompt-file") + 1]).read_text("utf-8"))


class OutlineBuildTest(OutlineScenario):
    def two_slices(self, **replies) -> StubbedRun:
        return self.outlined({"outline": TWO_SLICES, "build#1": building("fixture/one.txt", "ONE\n"),
                              "build#2": building("fixture/two.txt", "TWO\n"), **replies}, reads=True)

    def test_each_slice_is_a_fresh_implementer_session_given_the_outline_facts_and_planner_reads(self):
        pulls = [{"number": 5, "state": "MERGED", "headRefName": "docs-5", "closingIssuesReferences": []}]
        fact = "SETUP FACT: greet() is missing"
        run = self.outlined({"outline": TWO_SLICES, "build#1": building("fixture/one.txt", "ONE\n"),
                             "build#2": building("fixture/two.txt", "TWO\n"),
                             "applies": dict(APPLIES, details=fact)}, reads=True, pulls=pulls)

        self.finish(run, "done")

        builds = self.launched(run, "build")
        self.assertEqual(len(builds), 2)
        for prompt in (launch["prompt"] for launch in builds):
            self.assertIn(f"# Outline of issue #{run.issue}", prompt)
            self.assertIn(fact, prompt)
            self.assertIn('[{"closes":false,"number":5}]', prompt)
            for path in READS:
                self.assertIn(path.replace("<worktree>", str(run.worktree_path)), prompt)
        self.assertIn("SECOND SLICE CHANGE", builds[1]["prompt"])
        self.assertNotIn("diff --git a/fixture/one.txt", builds[0]["prompt"])
        self.assertIn("diff --git a/fixture/one.txt", builds[1]["prompt"])
        sessions = [session_of(launch) for launch in builds]
        self.assertEqual(len(set(sessions)), 2)
        for launch in run.launches():
            self.assertNotIn("--resume", launch["argv"])
        slices = self.named(run, "outline-slice")
        self.assertEqual([self.sessions(run, child, "build") for child in slices], [1, 1])

    def test_a_blocked_first_slice_stops_the_build_before_the_second_implementer_launches(self):
        run = self.two_slices(**{"build#1": BLOCKED_BUILD})

        self.finish(run, "task", "owner-decision")

        self.assertEqual(len(self.launched(run, "build")), 1)
        self.assertEqual(len(self.named(run, "outline-slice")), 1)

    def test_a_stopped_run_continued_builds_again_from_the_slice_that_stopped(self):
        run = self.two_slices(**{"build#2": BLOCKED_BUILD, "build#3": building("fixture/two.txt", "TWO\n")})
        self.finish(run, "task", "owner-decision")

        self.finish(run, "done")

        self.assertEqual(len(self.launched(run, "build")), 3)
        self.assertEqual(len(self.committed(run, "fixture/one.txt")), 1)
        second = self.named(run, "outline-build")[-1]
        first_slice = next(child for child in run.children(second)
                           if json.loads((child / "run.json").read_text("utf-8"))["inputs"]["item"] == 1)
        self.assertEqual(procedure_of(first_slice), "outline-slice")
        self.assertIn("slice", self.entered(run, first_slice))
        self.assertNotIn("build", self.entered(run, first_slice))
        self.assertIn(("slice", "built"), run.transitions(first_slice))

    def test_a_cut_during_the_second_slice_continues_it_and_keeps_the_first(self):
        slept = dict(building("fixture/two.txt", "TWO\n"), sleep=30)
        run = self.two_slices(**{"build#2": slept})

        run.deliver_until(lambda: run.asleep("build#2"), plan="outline")
        self.assertTrue(run.asleep("build#2"))
        before = self.first_slice_children(run)
        done = run.deliver(plan="outline")

        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(run.line(done)["end"], "done")
        self.assertEqual(len(before), 1)
        self.assertEqual(self.first_slice_children(run), before)
        builds = self.launched(run, "build")
        first = session_of(builds[0])
        self.assertEqual([session_of(launch) for launch in builds].count(first), 1)
        self.assertEqual(len(self.committed(run, "fixture/one.txt")), 1)
        second = builds[1]["argv"]
        self.assertIn("--session-id", second)
        resumed = builds[2]["argv"]
        self.assertIn("--resume", resumed)
        self.assertEqual(resumed[resumed.index("--resume") + 1], second[second.index("--session-id") + 1])

    def first_slice_children(self, run: StubbedRun) -> set[str]:
        """The children the `outline-build` run's `call` events of `build-slices` name at index 0."""
        calls = [e for build in self.named(run, "outline-build") for e in run.events(build)
                 if e["event"] == "call" and e["step"] == "build-slices"]
        return {e["child"] for e in calls if e["index"] == 0}

    def test_the_slices_come_from_the_approved_record_not_the_worktree(self):
        altered = dict(TWO_SLICES, slices=[SLICE_ONE, dict(SLICE_TWO, change="ALTERED")])
        run = self.two_slices()
        run.answer("outline", with_reads(TWO_SLICES, run.worktree_path) | {
            "leave": {"path": ".superpowers/plans/issue-41/plan.md", "text": "slice 2 says ALTERED\n"}})
        run.answer("build#1", dict(building("fixture/one.txt", "ONE\n"), leave={
            "path": ".superpowers/plans/issue-41/outline.json", "text": json.dumps(altered)}))

        run.deliver(plan="outline")

        builds = self.launched(run, "build")
        self.assertEqual(len(builds), 2)
        self.assertIn("SECOND SLICE CHANGE", builds[1]["prompt"])
        self.assertNotIn("ALTERED", builds[1]["prompt"])

    def test_an_outline_and_setup_facts_naming_nohup_reach_the_implementer(self):
        run = self.outlined({"outline": dict(OUTLINE, approach=NOHUP_PLAN_TEXT),
                             "applies": dict(APPLIES, details="the doc says never start a run with nohup")})

        self.finish(run, "done")

        self.assertIn(NOHUP_PLAN_TEXT, self.launched(run, "build")[0]["prompt"])
        root = run.runs()[0]
        outcomes = [outcome for directory in (root, *self.descendants(run, root))
                    for _, outcome in run.transitions(directory)]
        self.assertNotIn("refused", outcomes)


class OutlineRefusalTest(OutlineScenario):
    def refused(self, replies: dict, **members) -> StubbedRun:
        run = self.outlined(replies, **members)
        self.finish(run, "plan-refused", "owner-decision")
        self.assertEqual(self.launched(run, "design-review"), [])
        return run

    def test_an_outline_over_the_comment_limit_is_reviewed_and_refused_only_at_publication(self):
        text = "x" * (issue_setup.PLAN_LIMIT + 1)
        run = self.outlined({"outline": dict(OUTLINE, approach=text)})

        self.finish(run, "plan-not-posted", "retry")

        reviews = self.launched(run, "design-review")
        self.assertEqual(len(reviews), 1)
        self.assertIn(text, reviews[0]["prompt"])
        self.assertEqual(self.launched(run, "build"), [])

    def test_a_criterion_with_no_slice_is_refused_before_the_design_review(self):
        self.refused({"outline": UNMAPPED, "outline-fix": UNMAPPED})

    def test_an_issue_criterion_missing_from_the_outline_is_refused_before_the_design_review(self):
        run = self.refused({"outline": OUTLINE, "outline-fix": OUTLINE}, body=TWO_CRITERIA_BODY)

        self.assertIn(("outline-mapped", "unmapped"), run.transitions(run.runs()[0]))

    def test_a_slice_with_no_proving_test_is_refused_before_the_design_review(self):
        run = self.refused({"outline": UNPROVEN, "outline-fix": UNPROVEN})

        self.assertIn(("outline-proven", "unproven"), run.transitions(run.runs()[0]))

    def test_the_outline_reply_has_exactly_the_ruled_members(self):
        schema = json.loads((PROCEDURES / "outline.reply.json").read_text("utf-8"))
        properties = schema["properties"]
        self.assertEqual(set(properties), {"status", "approach", "rejected", "slices", "criteria", "risks", "questions"})
        self.assertEqual(properties["status"], {"enum": ["planned", "blocked"]})
        slice_schema = properties["slices"]["items"]
        self.assertEqual(set(slice_schema["properties"]), {"n", "change", "files", "test", "assertion"})
        self.assertEqual(slice_schema["properties"]["files"], {"type": "array", "items": {"type": "string"}})
        criterion = properties["criteria"]["items"]
        self.assertEqual(set(criterion["properties"]), {"id", "text", "kind", "slice"})
        self.assertEqual(criterion["properties"]["kind"], {"enum": ["code", "evidence", "human", "note"]})
        for node in (schema, slice_schema, criterion):
            self.assertIs(node["additionalProperties"], False)
            self.assertEqual(set(node["required"]), set(node["properties"]))
        self.assertEqual(properties["risks"], {"type": "array", "items": {"type": "string"}})
        self.assertEqual(properties["questions"], {"type": "array", "items": {"type": "string"}})

    def test_an_outline_session_at_its_role_bound_ends_at_plan_failed(self):
        run = self.outlined({"outline": {"reply": OUTLINE, "result": "max-budget"}})

        self.finish(run, "plan-failed", "retry")

        self.assertIn(("outline", "out-of-bounds"), run.transitions(run.runs()[0]))
        launches = self.launched(run, "outline")
        self.assertEqual(len(launches), 1)
        argv = launches[0]["argv"]
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], f"{engine_session.ROLE_BOUNDS['planner'].spend_usd:.2f}")
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "15.00")

    def test_no_agent_step_of_the_outline_procedures_carries_a_per_step_value(self):
        for name in ("outline", "outline-build", "outline-slice"):
            allowed = PLAN_MEMBERS | {"worktree"} | ({"max_visits"} if name == "outline-build" else set())
            for step in procedure_document(name)["steps"]:
                if step["kind"] == "agent":
                    self.assertLessEqual(set(step), allowed, f"{name}.{step['id']}")

    def test_no_command_step_of_the_outline_route_is_given_outline_or_setup_text(self):
        seen = 0
        for name in ("outline", "outline-build", "outline-slice"):
            for step in procedure_document(name)["steps"]:
                if step["kind"] == "command" and str(step.get("subcommand", "")).startswith("outline-"):
                    seen += 1
                    for path in step["in"]:
                        self.assertTrue(path.startswith("run.") or path.endswith(".digest"), f"{name}.{step['id']}: {path}")
        self.assertEqual(seen, 7)


class OutlineRevisionTest(OutlineScenario):
    REVISED = {"outline": UNPROVEN, "outline-fix": OUTLINE, "design-review": DESIGN_FINDINGS,
               "outline-revise": OUTLINE, "design-rereview": DESIGN_FINDINGS}

    def test_one_revision_with_findings_again_ends_at_plan_refused(self):
        run = self.outlined(self.REVISED)

        self.finish(run, "plan-refused", "owner-decision")

        self.assertEqual(len(self.launched(run, "design-review")), 1)
        self.assertEqual(len(self.launched(run, "design-rereview")), 1)
        self.assertEqual(self.launched(run, "build"), [])

    def test_a_revision_the_rereview_passes_is_posted_and_built(self):
        run = self.outlined({**self.REVISED, "design-rereview": DESIGN_PASS})

        self.finish(run, "done")

        self.assertIn(("outline-revised-note", "posted"), run.transitions(run.runs()[0]))
        self.assertEqual(len(self.launched(run, "build")), 1)


class OutlineReviewHalfTest(OutlineScenario):
    def edges(self, run: StubbedRun) -> list[tuple[str, str]]:
        return run.transitions(self.named(run, "outline-build")[0])

    def test_lite_findings_are_fixed_once_and_land_after_a_clean_rereview(self):
        run = self.outlined({"lite-review": lite_findings(), "lite-fix": committing("fixture/second.py", "SECOND = 2\n"),
                             "lite-rereview": CLEAN_REREVIEW})

        self.finish(run, "done")

        for edge in (("lite-tally", "findings"), ("lite-fixed", "done"), ("lite-settled", "clean")):
            self.assertIn(edge, self.edges(run))

    def test_findings_of_the_full_review_of_a_sensitive_change_are_fixed_once_and_land_after_a_clean_rereview(self):
        sensitive = dict(IMPLEMENTED, reply=dict(IMPLEMENTED["reply"], sensitive=True))
        run = self.outlined({"build": sensitive, "full-review": full_findings(),
                             "full-fix": committing("fixture/second.py", "SECOND = 2\n"),
                             "full-rereview": CLEAN_REREVIEW})

        self.finish(run, "done")

        for edge in (("implemented", "full"), ("full-tally", "findings"), ("full-fixed", "done"),
                     ("full-settled", "clean")):
            self.assertIn(edge, self.edges(run))

    def test_findings_of_the_escalated_review_are_fixed_once_and_land_after_a_clean_rereview(self):
        run = self.outlined({"lite-review": dict(CLEAN_LITE, escalate=True), "escalated": full_findings(),
                             "escalated-fix": committing("fixture/second.py", "SECOND = 2\n"),
                             "escalated-rereview": CLEAN_REREVIEW})

        self.finish(run, "done")

        for edge in (("lite-tally", "escalate"), ("escalated-tally", "findings"), ("escalated-fixed", "done"),
                     ("escalated-settled", "clean")):
            self.assertIn(edge, self.edges(run))


if __name__ == "__main__":
    unittest.main()
