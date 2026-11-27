"""Scenario tests for the fix rounds of the shipped `verify` procedure: the one rerun of an id failing outside the
diff, the reviewed fix, the narrowed rerun, the retest of an untested fix and each stop, run as a whole stubbed
`engine deliver` on the fixture project (`tests/engine_stubbed_world.py`), plus the shape of `verify.json` read as
data. The module checks `verify` coverage from its own runs: every step of that procedure is visited by a run of
this module, and the module's runs take their fixtures from its own `FIXTURES`."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import engine_session
from tests.engine_fixture import AdoptedFixtures
from tests.engine_procedure_copies import PROCEDURES
from tests.engine_step_coverage import StepCoverage
from tests.engine_stubbed_world import ROLES, StubbedRun
from tests.engine_verify_fixtures import (
    ATTESTED, FORMAT, FOUR, PASS_ATTESTED, PASS_PLAIN, RETESTED, TWO, TWO_SPACES, fixing, implementing)
from tests.guard_policy_world import install_platform_manifest_in_environ
from tests.test_engine_stubbed_run import Scenario

TIER = "integration"  # every run case builds a repository and runs the engine as a child process

REPO_ROOT = Path(__file__).resolve().parents[1]

FIXTURES = AdoptedFixtures()
STEPS = StepCoverage(PROCEDURES, ("verify",))


def setUpModule() -> None:
    install_platform_manifest_in_environ()
    unittest.addModuleCleanup(FIXTURES.close)


def tearDownModule() -> None:
    STEPS.finish(sys.modules[__name__], Scenario)


def part_finished() -> None:
    STEPS.finish_part(sys.modules[__name__], Scenario)


IMPORTANT = {"severity": "important", "file": "fixture/greeting.json:2", "failing_input": "indent 2",
             "summary": "s", "kind": "other"}
MINOR = dict(IMPORTANT, severity="minor")
FOUND = {"verdict": "findings", "findings": [IMPORTANT], **ATTESTED}
UNUSABLE = {"verdict": "findings", "findings": [dict(IMPORTANT, file="", failing_input="")], **ATTESTED}
CHANGED = fixing("fixture/greeting.json", '{\n  "greeting": "hi"\n}\n', tests=["checks/check_format.py"])
BROKEN = ("import unittest\n\n\nclass BrokenTest(unittest.TestCase):\n    def test_broken(self):\n"
          "        self.fail('always')\n")
UNRELATED = {"reply": {"status": "blocked", "notes": "n", "tests": [], "outside_diff": [],
                       "unrelated": {"test": "checks/check_broken.py", "evidence": "fails at origin/main too"}},
             "same_head": {}}
NEW_FILE_FIX = {
    "fix.1": fixing("fixture/second.py", "SECOND = 1\n", tests=["checks/check_format.py"]),
    "fix.2": fixing("fixture/third.py", "THIRD = 1\n", tests=["checks/check_format.py"])}
SECOND_FIX = fixing("fixture/second.py", "SECOND = 1\n", tests=["checks/check_format.py"])
STOPS = ("verify", "verify-unrelated", "verify-fix", "verify-fix-review")
VERIFY_STEPS = ("round", "fix", "fixed", "ws-check", "fix-review", "narrowing", "fix-review-again",
                "narrowing-again", "rerun", "retest", "retested")
BOUNDS = (("checks", 3), ("round", 3), ("fix", 2), ("fixed", 2), ("ws-check", 2), ("fix-review", 4),
          ("narrowing", 4), ("fix-review-again", 4), ("narrowing-again", 2), ("rerun", 2))


def procedure(name: str) -> dict:
    return json.loads((PROCEDURES / f"{name}.json").read_text("utf-8"))


def steps_of(name: str) -> dict[str, dict]:
    return {step["id"]: step for step in procedure(name)["steps"]}


class RoundsTest(Scenario):
    def verify(self, run: StubbedRun, last: bool = False) -> Path:
        return self.child(run, "verify", last=last)

    def walk(self, run: StubbedRun) -> list[tuple[str, str]]:
        return run.transitions(self.verify(run, last=True))

    def entered(self, run: StubbedRun, step: str) -> int:
        return sum(1 for e in run.events(self.verify(run, last=True))
                   if e["event"] == "step_entered" and e["step"] == step)

    def count(self, run: StubbedRun, step: str) -> int:
        return sum(1 for launch in run.launches() if launch["key"] == step)

    def nothing_pushed(self, run: StubbedRun) -> None:
        self.assertIsNone(run.origin_tip(run.branch))
        self.assertEqual(run.pulls(), [])

    def merged(self, run: StubbedRun) -> None:
        self.assertEqual([pull["state"] for pull in run.pulls()], ["MERGED"])

    def test_a_failure_inside_the_diff_is_fixed_reviewed_and_only_the_failed_id_rerun(self):
        run = self.stubbed(extra_files=FORMAT, replies={"implement": FOUR, "fix": TWO, "fix-review": PASS_ATTESTED})

        self.finish(run, "done")

        walk = self.walk(run)
        self.assertIn(("narrowing", "rerun-failed-only"), walk)
        self.assertIn(("round", "passed"), walk[walk.index(("narrowing", "rerun-failed-only")):])
        checks = self.stored(self.verify(run), "checks")
        rerun = {r["id"]: r for r in self.stored(self.verify(run), "rerun")["results"]}
        self.assertEqual(rerun["test"]["status"], "pass")
        self.assertEqual(rerun["lint"]["carried_from"], checks["head"])
        self.assertEqual(len(run.slot_history()), 3)
        self.merged(run)

    def test_an_id_failing_outside_the_diff_is_rerun_once_and_its_pass_is_recorded_flaky(self):
        marker_dir = Path(tempfile.mkdtemp(prefix="flaky-marker-"))
        self.addCleanup(shutil.rmtree, marker_dir, True)
        flaky = ("import unittest\nfrom pathlib import Path\n\nMARKER = Path(%r)\n\n\n"
                 "class FlakyTest(unittest.TestCase):\n    def test_once(self):\n"
                 "        if not MARKER.exists():\n            MARKER.write_text('x')\n"
                 "            self.fail('flaky once')\n" % str(marker_dir / "seen"))
        run = self.stubbed(extra_files={"checks/check_flaky.py": flaky})

        self.finish(run, "done")

        test = next(r for r in self.stored(self.verify(run), "checks")["results"] if r["id"] == "test")
        self.assertEqual(test["status"], "pass")
        self.assertIn("flaky once", test["flaky"])
        self.assertEqual(len(run.slot_history()), 3)
        self.assertEqual(self.count(run, "fix"), 0)

    def test_a_failure_inside_the_diff_gets_a_fix_and_a_full_review_and_lands(self):
        run = self.stubbed(extra_files=FORMAT, replies={"implement": FOUR, "fix": CHANGED, "fix-review": PASS_PLAIN})

        self.finish(run, "done")

        self.assertIn(("narrowing", "rerun-all"), self.walk(run))
        self.assertEqual(self.entered(run, "checks"), 2)
        self.assertEqual(self.count(run, "fix-review"), 1)
        role = engine_session.read_role(ROLES, "reviewer")
        argv = self.launch(run, "fix-review")["argv"]
        self.assertEqual((argv[argv.index("--model") + 1], argv[argv.index("--effort") + 1]),
                         (role.model, role.effort))
        self.merged(run)

    def test_a_third_failing_round_stops_verify_after_two_fixes(self):
        run = self.stubbed(extra_files=FORMAT, replies={"implement": FOUR, **NEW_FILE_FIX, "fix-review": PASS_PLAIN})

        self.finish(run, "verify", "owner-decision")

        self.assertEqual(self.count(run, "fix"), 2)
        self.assertIn(("round", "spent"), self.walk(run))
        self.nothing_pushed(run)

    def test_an_unrelated_reply_stops_verify_unrelated_and_nothing_ships(self):
        run = self.stubbed(extra_files={"checks/check_broken.py": BROKEN}, replies={"fix": UNRELATED})

        self.finish(run, "verify-unrelated", "owner-decision")

        test = next(r for r in self.stored(self.verify(run), "checks")["results"] if r["id"] == "test")
        self.assertIs(test["reran"], True)
        self.nothing_pushed(run)

    def test_findings_on_both_fix_reviews_stop_verify_fix_review_after_exactly_two_fix_sessions(self):
        run = self.stubbed(extra_files=FORMAT, replies={
            "implement": FOUR, "fix.1": TWO, "fix.2": SECOND_FIX, "fix-review": FOUND})

        self.finish(run, "verify-fix-review", "owner-decision")

        self.assertEqual(self.walk(run)[-2:], [("narrowing", "findings"), ("round", "review-spent")])
        self.assertEqual(self.count(run, "fix"), 2)
        self.assertEqual(self.count(run, "fix-review"), 2)
        self.assertEqual(self.entered(run, "checks"), 1)
        self.assertEqual(self.entered(run, "rerun"), 0)
        self.nothing_pushed(run)

    def test_a_first_fix_review_finding_gets_a_second_fix_that_is_briefed_with_it_and_lands_when_the_next_review_passes(self):
        found = dict(FOUND, findings=[dict(IMPORTANT, summary="the moved test dropped an assertion")])
        run = self.stubbed(extra_files=FORMAT, replies={
            "implement": FOUR, "fix.1": TWO, "fix.2": SECOND_FIX, "fix-review.1": found, "fix-review.2": PASS_PLAIN})

        self.finish(run, "done")

        walk = self.walk(run)
        self.assertEqual(walk[walk.index(("narrowing", "findings")):][:2], [("narrowing", "findings"), ("round", "fix")])
        self.assertEqual(self.count(run, "fix"), 2)
        first, second = [launch for launch in run.launches() if launch["key"] == "fix"]
        self.assertNotIn("the moved test dropped an assertion", first["prompt"])
        self.assertIn("the moved test dropped an assertion", second["prompt"])
        self.assertIn(("narrowing", "rerun-all"), walk)
        self.assertEqual(walk[-1], ("round", "passed"))
        self.merged(run)

    def test_a_passing_verdict_with_an_important_finding_gets_a_second_fix_and_then_stops_verify_fix_review(self):
        run = self.stubbed(extra_files=FORMAT, replies={
            "implement": FOUR, "fix.1": TWO, "fix.2": SECOND_FIX, "fix-review": dict(FOUND, verdict="pass")})

        self.finish(run, "verify-fix-review", "owner-decision")

        self.assertEqual(self.count(run, "fix"), 2)
        self.assertEqual(self.entered(run, "rerun"), 0)
        self.nothing_pushed(run)

    def test_a_finding_naming_no_file_and_no_input_is_discarded_and_the_review_runs_once_more(self):
        run = self.stubbed(extra_files=FORMAT, replies={
            "implement": FOUR, "fix": TWO, "fix-review": UNUSABLE, "fix-review-again": PASS_ATTESTED})

        self.finish(run, "done")

        self.assertIn(("narrowing", "unusable"), self.walk(run))
        self.assertEqual(self.count(run, "fix-review"), 1)
        self.assertEqual(self.count(run, "fix-review-again"), 1)
        self.assertIn(("narrowing-again", "rerun-failed-only"), self.walk(run))
        self.merged(run)

    def test_a_second_unusable_review_stops_verify_fix_review(self):
        run = self.stubbed(extra_files=FORMAT, replies={
            "implement": FOUR, "fix": TWO, "fix-review": UNUSABLE, "fix-review-again": UNUSABLE})

        self.finish(run, "verify-fix-review", "owner-decision")

        self.assertIn(("narrowing-again", "unusable"), self.walk(run))
        self.assertEqual(self.count(run, "fix-review"), 1)
        self.assertEqual(self.count(run, "fix-review-again"), 1)
        self.assertEqual(self.entered(run, "rerun"), 0)
        self.nothing_pushed(run)

    def test_a_lost_second_review_stops_verify_fix_review_without_asking_again(self):
        run = self.stubbed(extra_files=FORMAT, replies={"implement": FOUR, "fix": TWO, "fix-review": UNUSABLE})

        self.finish(run, "verify-fix-review", "owner-decision")

        self.assertIn(("fix-review-again", "no-reply"), self.walk(run))
        self.assertEqual(self.entered(run, "fix-review-again"), 1)
        self.assertEqual(self.entered(run, "rerun"), 0)
        self.nothing_pushed(run)

    def test_every_agent_step_maps_a_lost_or_over_bound_reply_to_a_stop_or_the_next_stage(self):
        for step in procedure("verify")["steps"]:
            if step["kind"] != "agent":
                continue
            for outcome in ("no-reply", "out-of-bounds"):
                with self.subTest(step=step["id"], outcome=outcome):
                    self.assertNotEqual(step["on"][outcome], step["id"])

    def test_a_fix_review_with_only_minor_findings_goes_on(self):
        run = self.stubbed(extra_files=FORMAT, replies={
            "implement": FOUR, "fix": TWO, "fix-review": dict(FOUND, findings=[MINOR])})

        self.finish(run, "done")

        self.assertIn(("narrowing", "rerun-failed-only"), self.walk(run))
        self.merged(run)

    def untested(self, retest: dict) -> StubbedRun:
        return self.stubbed(extra_files=FORMAT, replies={
            "implement": FOUR, "fix": fixing("fixture/greeting.json", TWO_SPACES), "fix-review": PASS_ATTESTED,
            "retest": retest})

    def retest_reply(self, **members) -> dict:
        return {**RETESTED, "reply": {**RETESTED["reply"], **members}}

    def test_an_untested_fix_is_retested_before_the_run_goes_on(self):
        run = self.untested(RETESTED)

        self.finish(run, "done")

        walk = self.walk(run)
        self.assertIn(("round", "retest"), walk)
        self.assertIn(("retested", "done"), walk[walk.index(("round", "retest")):])
        verify = self.verify(run)
        prompt = self.launch(run, "retest")["prompt"]
        self.assertIn(self.stored(verify, "checks")["head"], prompt)
        self.assertIn(self.stored(verify, "rerun")["head"], prompt)
        self.merged(run)

    def test_a_retest_with_no_recorded_test_stops_verify_fix(self):
        run = self.untested(self.retest_reply(tests=[]))

        self.finish(run, "verify-fix", "owner-decision")

        self.assertIn(("retested", "untested"), self.walk(run))
        self.nothing_pushed(run)

    def test_a_retest_that_leaves_the_tree_dirty_stops_verify_fix(self):
        run = self.untested(self.retest_reply(clean=False))

        self.finish(run, "verify-fix", "owner-decision")

        self.assertIn(("retested", "dirty"), self.walk(run))
        self.nothing_pushed(run)

    def test_a_retest_that_leaves_an_untracked_file_stops_verify_fix_whatever_it_reports(self):
        run = self.untested({**RETESTED, "leave": {"path": "fixture/scratch.txt", "text": "x\n"}})

        self.finish(run, "verify-fix", "owner-decision")

        self.assertIn(("retested", "dirty"), self.walk(run))
        self.nothing_pushed(run)

    def test_the_two_round_bound_holds_across_a_stop_and_a_continue(self):
        run = self.stubbed(extra_files=FORMAT, replies={
            "implement": FOUR, **NEW_FILE_FIX, "fix-review": FOUND})
        self.finish(run, "verify-fix-review", "owner-decision")
        run.answer("fix-review", PASS_PLAIN)

        self.finish(run, "verify", "owner-decision")

        self.assertEqual(len(run.runs()), 1)
        verifies = [child for child in run.children(run.runs()[0])
                    if json.loads((child / "run.json").read_text("utf-8"))["procedure"] == "verify"]
        self.assertEqual(len(verifies), 2)
        self.assertEqual(self.count(run, "fix"), 2)
        self.assertEqual(run.transitions(verifies[-1])[-1], ("round", "spent"))


class ShapeTest(unittest.TestCase):
    def test_each_bound_of_verify_is_the_programs(self):
        steps = steps_of("verify")
        for step_id, bound in BOUNDS:
            with self.subTest(step=step_id):
                self.assertEqual(steps[step_id]["max_visits"], bound)
                self.assertEqual(steps[step_id]["on"]["exhausted"], "verify")
        self.assertEqual((steps["fix"]["role"], steps["fix"]["mutates"]), ("implementer", True))
        self.assertEqual(steps["fix-review"]["role"], "reviewer")
        self.assertEqual(steps["retest"]["role"], "implementer")
        self.assertNotIn("mutates", steps["retest"])

    def test_the_round_step_reads_the_versioned_subcommand_and_the_old_subcommand_keeps_its_verdicts(self):
        declared = json.loads((REPO_ROOT / "python/agent_tools/delivery/command_verdicts.json")
                              .read_text("utf-8"))["verify-rounds"]["subcommands"]
        self.assertEqual(steps_of("verify")["round"]["subcommand"], "round-reviewed")
        self.assertEqual(declared["round"], ["passed", "retest", "fix", "spent", "verify", "error"])
        self.assertEqual(declared["round-reviewed"],
                         ["passed", "retest", "fix", "spent", "review-spent", "verify", "error"])

    def test_each_verification_stop_maps_to_the_deliver_stop_of_the_same_name(self):
        deliver, verify = procedure("deliver"), procedure("verify")
        mapped = steps_of("deliver")["verification"]["on"]
        for name in STOPS:
            with self.subTest(stop=name):
                self.assertEqual(verify["stops"][name]["need"], "owner-decision")
                self.assertEqual(deliver["stops"][name], {"need": "owner-decision", "reenter": "verification"})
                self.assertEqual(mapped[name], name)

    def test_no_verify_only_step_id_is_a_step_of_another_procedure(self):
        others = {path.stem for path in PROCEDURES.glob("*.json")
                  if not path.name.endswith(".reply.json")} - {"verify"}
        for name in others:
            with self.subTest(procedure=name):
                self.assertEqual(set(VERIFY_STEPS) & set(steps_of(name)), set())

    def test_no_verify_prompt_names_a_lifecycle_or_claim_command(self):
        for name in ("verify-fix.md", "verify-fix-review.md", "verify-retest.md"):
            text = (PROCEDURES / name).read_text("utf-8")
            for word in ("git push", "gh pr create", "gh pr merge", "forge-claim"):
                with self.subTest(prompt=name, word=word):
                    self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
