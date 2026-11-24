"""deliver-standard.js verifies with the contract's pre-pull-request list when it sets one.

The program runs under the node harness against stub agents. The helpers come from the program test module,
imported as a module so that unittest does not collect its test classes a second time.
Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
import re
import unittest

from . import test_deliver_standard_program as program

TIER = "integration"

FULL = [{"id": "lint", "argv": ["just", "lint"], "cwd": "."}, {"id": "test", "argv": ["just", "test"], "cwd": "."}]
BEFORE = [FULL[0], {"id": "test-touched", "argv": ["just", "test-touched"], "cwd": "."}]
PASSED = {"head": program.SHA, "clean": True,
          "results": [{"id": "lint", "status": "pass", "summary": "ok"},
                      {"id": "test-touched", "status": "pass", "summary": "ok"}]}
FULL_PASSED = {"head": program.SHA, "clean": True,
               "results": [{"id": "lint", "status": "pass", "summary": "ok"},
                           {"id": "test", "status": "pass", "summary": "ok"}]}
LINT_ONLY = {"head": program.SHA, "clean": True, "results": [{"id": "lint", "status": "pass", "summary": "ok"}]}
PRE_PR_EVIDENCE = ("the verification above ran the pre-pull-request list, and CI on this pull request runs the full "
                   "declared verification")
SETUP_READ = ("- verification_before_pull_request: only when bindings.workflow.verification_before_pull_request is a list, "
              "for each of its ids its bindings.commands argv, its cwd relative to project.root (. for the root), and any "
              "bindings.workflow.verification_conditions entry for that id (when_changed globs, skip_reason); omit "
              "verification_before_pull_request when the binding is absent or null.")
MARKER = ("// suppress-standard:B17 the program's phases share module state (setup, verify, the look loop), so it stays one file")


def setup_with(**members):
    return {"setup": dict({"verification": FULL}, **members)}


class VerifyBeforePullRequestTest(unittest.TestCase):

    def test_a_set_binding_runs_only_its_ids_before_the_pull_request(self):
        result, calls = program.run(patch=setup_with(verification_before_pull_request=BEFORE),
                                    replies={"verify": PASSED})
        self.assertIn(program.slotted(BEFORE), program.prompt(calls, "verify"))
        self.assertNotIn(json.dumps(["just", "test"], separators=(",", ":")), program.prompt(calls, "verify"))
        self.assertEqual(result["stage"], "done")
        self.assertNotIn("verify-fix-1", program.labels(calls))
        self.assertIn(PRE_PR_EVIDENCE, program.prompt(calls, "pr"))

    def test_an_absent_binding_runs_every_declared_verification_id_before_the_pull_request(self):
        result, calls = program.run(patch=setup_with(), replies={"verify": FULL_PASSED})
        self.assertIn(program.slotted(FULL), program.prompt(calls, "verify"))
        self.assertEqual(result["stage"], "done")
        self.assertNotIn(PRE_PR_EVIDENCE, program.prompt(calls, "pr"))
        ready, _ = program.run(args=dict(program.ARGS, mode="ready"), patch=setup_with(),
                               replies={"verify": FULL_PASSED})
        self.assertNotIn("verify_scope", ready)

    def test_a_missing_pre_pull_request_result_fails_the_verification(self):
        _, calls = program.run(patch=setup_with(verification_before_pull_request=BEFORE),
                               replies={"verify": LINT_ONLY})
        fix = program.prompt(calls, "verify-fix-1")
        self.assertIn("test-touched", fix)
        self.assertIn("expected exactly one result, got 0", fix)

    def test_an_empty_or_malformed_binding_runs_the_full_list(self):
        for binding in ([], None, "lint"):
            with self.subTest(binding=binding):
                result, calls = program.run(patch=setup_with(verification_before_pull_request=binding),
                                            replies={"verify": FULL_PASSED})
                self.assertIn(program.slotted(FULL), program.prompt(calls, "verify"))
                self.assertEqual(result["stage"], "done")
                self.assertNotIn(PRE_PR_EVIDENCE, program.prompt(calls, "pr"))

    def test_the_ready_stop_names_the_pre_pull_request_scope(self):
        result, _ = program.run(args=dict(program.ARGS, mode="ready"),
                                patch=setup_with(verification_before_pull_request=BEFORE),
                                replies={"verify": PASSED})
        self.assertEqual(result["verify_scope"], "before_pull_request")

    def test_a_cached_full_verification_does_not_answer_the_pre_pull_request_list(self):
        ready, _ = program.run(args=dict(program.ARGS, mode="ready"), patch=setup_with(),
                               replies={"verify": FULL_PASSED})
        self.assertEqual(ready["cont"]["verified"]["contract"], json.dumps(
            [{"argv": ["just", "lint"], "cwd": ".", "id": "lint"}, {"argv": ["just", "test"], "cwd": ".", "id": "test"}],
            separators=(",", ":")))
        patch = setup_with(head=program.SHA, verification_before_pull_request=BEFORE)
        patch["verify"] = PASSED
        result, calls = program.run(args=dict(program.ARGS, cont=ready["cont"]), patch=patch)
        self.assertEqual(result["stage"], "done")
        self.assertIn("verify", program.labels(calls))
        self.assertIn(program.slotted(BEFORE), program.prompt(calls, "verify"))

    def test_an_evidence_command_of_a_pre_pull_request_only_id_is_still_refused(self):
        merge = "d" * 40
        bad = program.criterion(program.EVIDENCE, verify_run={"command": "test-touched"})
        patch = {"direct-impl": {"acceptance": [{"id": "AC1", "text": "works", "kind": "code"}, bad]},
                 "merge": {"merge_commit": merge}, "close-out": {"issue_state": "OPEN"},
                 **setup_with(verification_before_pull_request=BEFORE)}
        result, calls = program.run(args=program.DIRECT, patch=patch, replies={"verify": PASSED})
        self.assertEqual((result["stage"], result["unattended"]), ("hold", ["AC2"]))
        self.assertIn("hold-draft", program.labels(calls))
        self.assertNotIn("hold", program.labels(calls))

    def test_the_setup_reads_the_binding(self):
        _, calls = program.run(patch=setup_with())
        self.assertIn(SETUP_READ, program.prompt(calls, "setup"))

    def test_the_program_ends_in_its_reasoned_size_suppression(self):
        lines = program.PROGRAM.read_text(encoding="utf-8").split("\n")
        self.assertEqual(lines[-2:], [MARKER, ""])


UNTOUCHED_SENTENCE = "When untouched is true, run no verification command and return results []."


class UntouchedSyncTest(unittest.TestCase):
    """A sync that changes none of the pull request's files is not verified again locally."""

    CARRY = program.LookCarryLandingTest
    UNTOUCHED = {"head": program.D, "clean": True, "merge_only": True, "untouched": True, "results": []}
    LOOK_UNTOUCHED = {"head": program.D, "clean": True, "merge_only": True, "ahead": False, "untouched": True,
                      "results": []}
    MOVED = {"head": program.D, "clean": True, "merge_only": True, "untouched": True, "results": []}

    def approve(self, reply):
        return program.LookCarryLandingTest().approve(
            replies={"look-carry-verify": reply, "look-carry": self.CARRY.FILES_CARRIED})

    def stops_with_problems(self, reply):
        result, calls = self.approve(reply)
        self.assertEqual(result["stage"], "look-carry", program.labels(calls))
        self.assertIn("expected exactly one result, got 0", json.dumps(result["problems"]))

    def test_a_sync_that_changes_none_of_the_pull_requests_files_runs_no_verification(self):
        result, calls = self.approve(self.UNTOUCHED)
        got = program.labels(calls)
        self.assertEqual(result["stage"], "done", got)
        self.assertIn("--match-head-commit " + program.D, program.prompt(calls, "merge"))
        self.assertIn(UNTOUCHED_SENTENCE, program.prompt(calls, "look-carry-verify"))
        after = got[got.index("look-carry-verify") + 1:]
        self.assertFalse([l for l in after if l.startswith("verify") or l == "look-reverify"], after)
        self.assertEqual([r.get("carried_from") for r in result["verify"]], [program.SHA])
        carry = program.prompt(calls, "look-carry")
        for flag in (" --before ", " --after "):
            self.assertNotIn(flag, carry)

    def test_a_sync_that_touches_a_pull_request_file_still_verifies(self):
        self.stops_with_problems(dict(self.UNTOUCHED, untouched=False))

    def test_untouched_without_merge_only_does_not_skip(self):
        self.stops_with_problems(dict(self.UNTOUCHED, merge_only=False))

    def test_a_dirty_untouched_reply_does_not_skip(self):
        result, calls = self.approve(dict(self.UNTOUCHED, clean=False))
        self.assertEqual(result["stage"], "look-carry", program.labels(calls))

    def test_an_untouched_reply_with_results_uses_them(self):
        reply = dict(self.UNTOUCHED, results=self.CARRY.OK)
        result, calls = self.approve(reply)
        self.assertEqual(result["stage"], "done", program.labels(calls))
        fresh = [{"id": "build", "status": "pass", "summary": "ran again"}]
        moved, _ = program.run(
            patch={"setup": {"look": program.MARKED}, "look-pr": {"behind": True},
                   "sync-1": {"merge_commit": program.D, "head": program.D},
                   "look-reverify": dict(self.MOVED, results=fresh)})
        self.assertEqual(moved["cont"]["verified"]["results"], fresh)

    def test_a_second_landing_carry_measures_the_untouched_diff_from_the_verified_head(self):
        stale = {"merged": False, "behind": True, "notes": "Head branch is not up to date with the base branch",
                 "renew": {"verdict": "renewed"}, "lock": {"verdict": "already_held", "lock_sha": program.D}}
        landed = {"merged": True, "merge_commit": program.F, "notes": "merged", "renew": {"verdict": "renewed"},
                  "lock": {"verdict": "already_held", "lock_sha": program.F}}
        second = dict(self.UNTOUCHED, head=program.F)
        patch = dict(self.CARRY.NEEDED, **{"checks-3": {"state": "behind", "head": program.D},
                                           "sync-2": {"merge_commit": program.F, "head": program.F},
                                           "checks-4": {"state": "passed", "head": program.F, "required": ["ci"],
                                                        "passed": ["ci"]}})
        replies = {"look-status": [{"verdict": "needed", "kept_from": None}] * 2,
                   "look-carry-verify": [self.CARRY.BARE, second], "merge": [stale, landed],
                   "look-carry": [self.CARRY.FILES_CARRIED] * 2}
        result, calls = self.CARRY().approve(patch=patch, replies=replies)
        self.assertEqual(result["stage"], "done", program.labels(calls))
        prompts = [c["prompt"] for c in calls if c.get("label") == "look-carry-verify"]
        self.assertEqual(len(prompts), 2)
        self.assertIn("--name-only " + program.D + " " + program.F + " ", prompts[1])
        self.assertNotIn("--name-only " + program.SHA + " " + program.F + " ", prompts[1])

    def test_an_approved_head_that_only_gained_untouched_merges_is_recorded_without_verification(self):
        result, calls = program.LookResumeTest().approve(
            head=program.D, patch=program.LOOK_MERGED, replies={"look-verify": self.LOOK_UNTOUCHED})
        self.assertEqual(result["stage"], "done", program.labels(calls))
        self.assertIn(UNTOUCHED_SENTENCE, program.prompt(calls, "look-verify"))
        self.assertEqual([r.get("carried_from") for r in result["verify"]], [program.SHA])
        self.assertIn("--match-head-commit " + program.D, program.prompt(calls, "merge"))

    def test_a_moved_look_head_that_only_gained_untouched_merges_is_not_reverified(self):
        result, calls = program.run(
            patch={"setup": {"look": program.MARKED}, "look-pr": {"behind": True},
                   "sync-1": {"merge_commit": program.D, "head": program.D}, "look-reverify": self.MOVED})
        got = program.labels(calls)
        self.assertEqual(result["stage"], "awaiting-look", got)
        self.assertEqual(result["head"], program.D)
        self.assertIn(UNTOUCHED_SENTENCE, program.prompt(calls, "look-reverify"))
        self.assertFalse([l for l in got[got.index("look-reverify"):] if l.startswith("verify")], got)

    def test_the_carried_verification_names_the_head_it_ran_at(self):
        result, calls = program.run(
            patch={"setup": {"look": program.MARKED}, "look-pr": {"behind": True},
                   "sync-1": {"merge_commit": program.D, "head": program.D}, "look-reverify": self.MOVED})
        verified = result["cont"]["verified"]
        self.assertEqual(verified["head"], program.D)
        self.assertTrue(verified["results"])
        for r in verified["results"]:
            self.assertEqual(r["carried_from"], program.SHA)
        self.assertNotIn("pictures", verified)

    def test_a_moved_look_head_that_is_not_reverified_keeps_the_pictures_the_owner_looks_at(self):
        pics = program.LookStopTest.PICS
        result, calls = program.run(
            patch={"setup": {"look": program.MARKED}, "verify": {"pictures": pics}, "look-pr": {"behind": True},
                   "sync-1": {"merge_commit": program.D, "head": program.D}, "look-reverify": self.MOVED})
        self.assertEqual(result["stage"], "awaiting-look", program.labels(calls))
        self.assertIn("look-reverify", program.labels(calls))
        self.assertEqual(result["head"], program.D)
        self.assertEqual(result["pictures"], pics)
        self.assertEqual(result["cont"]["verified"]["pictures"], pics)

    def test_an_untouched_landing_sync_carries_the_approval_by_the_pictures_rule(self):
        pics = program.LookCarryLandingTest.PICS
        first, _ = program.run(patch={"setup": {"look": program.MARKED}, "verify": {"pictures": pics}})
        result, calls = program.LookCarryLandingTest().approve(
            cont=first["cont"], replies={"look-carry-verify": self.UNTOUCHED, "look-carry": self.CARRY.CARRIED})
        self.assertEqual(result["stage"], "done", program.labels(calls))
        self.assertIn("--match-head-commit " + program.D, program.prompt(calls, "merge"))
        self.assertIn(" --before /r/pics/before.png --after /r/pics/after.png", program.prompt(calls, "look-carry"))


TWO = [{"id": "build", "argv": ["make", "build"], "cwd": "."}, {"id": "test", "argv": ["make", "test"], "cwd": "."}]
LOCAL_ONE = [TWO[0]]
LC = json.dumps(LOCAL_ONE, separators=(",", ":"))
ONLY_PRE_COMMIT = "only what this prompt says to run before committing"
RUN_LATER = f"the delivery runs its pre-pull-request commands {LC} itself, and the pull request's checks run the rest"
REVIEW_TESTS = f"Run only the targeted tests a finding needs and no command the project declares: {RUN_LATER}."
PLAN_TESTS = f"Run no command the project declares: {RUN_LATER}."
PR_TESTS = f"Run no test and no command the project declares: {RUN_LATER}."
FOCUSED_SET = (f"Run only the tests covering the files you changed and, of the commands the project declares, "
               f"{ONLY_PRE_COMMIT}: the verify step runs the pre-pull-request commands {LC} once later.")
PUSH_SET = (f"(with none declared, the pre-pull-request commands {LC}, each argv with <worktree>/<its cwd> as working "
            f"directory) and, of the other commands the project declares, {ONLY_PRE_COMMIT},")
OWN_SET = ("Before returning, run in full every test file among or covering the files you changed (never a single test "
           f"class) and, of the commands the project declares, {ONLY_PRE_COMMIT}: the verify step runs the "
           f"pre-pull-request commands {LC} next; return tests: each command and its result.")
VERIFY_OWNED_SET = "The verify step runs the pre-pull-request commands after the review."
OLD_PHRASES = ("any fast suite the project declares", "not the declared verification",
               "not the full suite or the declared verification", "no suite: the verify step runs it next",
               "The verify step runs the declared verification")
FORBIDS = ("not the pre-pull-request commands", "no command the project declares",
           "no other command the project declares", "run none the project declares")
FMT_FLAGGED = ("Before committing, run the fast pre-commit checks of that verification: each of "
               + program.PreCommitFocusTest.NAMED)
MARK = "pre-pull-request commands"
PASSED_CHECKS = program.PreCommitFocusTest.PASSED
ABSENT = object()
DEFAULT = object()
SWEEP = program.PreCommitFocusTest.SCENARIOS + (
    ({}, {"plan", "impl-1", "pr"}),
    ({"patch": {"setup": {"look": program.MARKED}}}, {"look-pr"}),
    ({"replies": {"plan": dict(program.PLAN, tasks=program.tasks(4))}}, set()),
)


def whole_set(files):
    return (f"run in full every test file among or covering {files} (never a single test class) and the "
            f"pre-pull-request commands {LC} (each argv with <worktree>/<its cwd> as working directory) and, of the "
            f"other commands the project declares, {ONLY_PRE_COMMIT}; return tests: each command and its result")


def sync_tests(wt, int_, frm):
    return (f"For a clean merge that changes none of the pull request's files (no path that git -C {wt} diff "
            f"--no-renames --name-only {frm} HEAD prints is among the paths git -C {wt} diff --no-renames "
            f"--name-only origin/{int_}...HEAD prints), run no test and, of the commands the project declares, "
            f"{ONLY_PRE_COMMIT}; for any other, run the pre-pull-request commands {LC} as well.")


def run_scenario(scenario, binding, verification=DEFAULT):
    """One scenario of the sweep, with the verification and the binding written into its setup reply."""
    patch = dict(scenario.get("patch", {}))
    setup = dict(patch.get("setup", {}))
    if verification is not DEFAULT:
        setup["verification"] = verification
    elif binding is not ABSENT:
        setup["verification"] = TWO
    if binding is not ABSENT:
        setup["verification_before_pull_request"] = binding
    patch["setup"] = setup
    return program.run(**dict(scenario, patch=patch))


def sweep(binding, verification=DEFAULT, scenarios=SWEEP):
    return [(set(expected), run_scenario(scenario, binding, verification)[1]) for scenario, expected in scenarios]


class SetBindingPromptsTest(unittest.TestCase):
    """With the pre-pull-request list set, every step that runs tests names its commands and no suite."""

    def test_with_the_binding_set_every_step_that_runs_tests_names_its_commands(self):
        for expected, calls in sweep(LOCAL_ONE):
            with self.subTest(expected=sorted(expected)):
                self.assertLessEqual(expected, set(program.labels(calls)))
                for label in expected:
                    self.assertIn(LC, program.prompt(calls, label), label)
                for call in calls:
                    if call["agentType"] in ("reviewer", "reviewer-lite"):
                        self.assertEqual(call["prompt"].count(REVIEW_TESTS), 1, call["label"])

    def test_with_the_binding_set_no_prompt_names_the_full_command_or_the_suite(self):
        for _, calls in sweep(LOCAL_ONE):
            for call in calls:
                text = call["prompt"]
                with self.subTest(label=call["label"]):
                    self.assertNotIn('"make","test"', text)
                    self.assertIsNone(re.search(r"\bmake test\b", text))
                    for phrase in OLD_PHRASES:
                        self.assertNotIn(phrase, text)

    def test_each_set_mode_sentence_reads_exactly(self):
        found = {}
        for _, calls in sweep(LOCAL_ONE):
            for call in calls:
                found[call["label"]] = call["prompt"]
        want = (("impl-1", FOCUSED_SET), ("fix-wave", OWN_SET), ("verify-fix-1", OWN_SET),
                ("sync-resolve-1", whole_set("the files you resolved by hand")), ("fix-ci", PUSH_SET),
                ("fix-sync-1", PUSH_SET), ("look-fix", PUSH_SET), ("final-1", VERIFY_OWNED_SET),
                ("plan", PLAN_TESTS), ("pr", PR_TESTS), ("look-pr", PR_TESTS))
        for label, sentence in want:
            with self.subTest(label=label):
                self.assertIn(sentence, found[label])

    def test_a_clean_landing_sync_that_changes_no_pull_request_file_runs_no_tests(self):
        patch = {"pr": {"checks": {"state": "behind", "head": program.SHA}}, "sync-1": {"merge_commit": program.MERGE}}
        replies = {"checks-2": {"state": "passed", "passed": ["ci"], "head": program.MERGE}}
        result, calls = program.run(patch=dict(setup_with(verification=TWO, verification_before_pull_request=LOCAL_ONE),
                                               **patch), replies=replies)
        want = sync_tests("/r/.wt/w-issue-9-x", "dev", program.SHA)
        got = program.labels(calls)
        self.assertIn(want, program.prompt(calls, "sync-1"))
        after = got[got.index("sync-1") + 1:]
        self.assertFalse([l for l in after if l.startswith("verify") or l == "look-reverify"], after)
        self.assertEqual(result["stage"], "done", got)
        _, bare = program.run(patch=patch, replies=replies)
        self.assertNotIn(want, program.prompt(bare, "sync-1"))

    def test_with_the_binding_absent_every_prompt_reads_as_before(self):
        found = {}
        for _, calls in sweep(ABSENT):
            for call in calls:
                found[call["label"]] = call["prompt"]
                for text in (MARK, REVIEW_TESTS, PLAN_TESTS, PR_TESTS):
                    self.assertNotIn(text, call["prompt"], call["label"])
        self.assertIn(program.FOCUSED_RUN + ", not the full suite or the declared verification (it runs once later).",
                      found["impl-1"])
        for label in ("fix-wave", "verify-fix-1"):
            self.assertIn(program.OWN_RUN, found[label])
        for needle in program.WHOLE_RUN:
            self.assertIn(needle, found["sync-resolve-1"])
        self.assertIn("(with none declared, any fast suite the project declares), not the declared verification,",
                      found["fix-ci"])
        self.assertIn("The verify step runs the declared verification: run only the targeted tests a finding needs, "
                      "never the whole suite.", found["final-1"])
        self.assertIn("then run any checks in one message.", found["plan"])

    def test_a_malformed_binding_leaves_every_prompt_as_absent(self):
        scenarios = ({}, program.PreCommitFocusTest.SCENARIOS[4][0])
        for scenario in scenarios:
            _, bare = run_scenario(scenario, ABSENT)
            want = {c["label"]: c["prompt"] for c in bare}
            for binding in ([], None, "lint"):
                with self.subTest(binding=binding):
                    _, calls = run_scenario(scenario, binding, verification=program.SETUP_OK["verification"])
                    self.assertEqual({c["label"]: c["prompt"] for c in calls}, want)

    def test_with_the_binding_set_the_pre_commit_checks_stay_asked_for(self):
        pre = program.PreCommitFocusTest
        scenarios = pre.SCENARIOS
        found = {}
        for scenario, expected in scenarios:
            _, calls = run_scenario(scenario, pre.UNFLAGGED, verification=pre.FLAGGED + [TWO[1]])
            prompts = {c["label"]: c["prompt"] for c in calls
                       if c["agentType"] == "implementer" and c["label"] in expected}
            self.assertLessEqual(set(expected), set(prompts), scenario)
            for label, text in prompts.items():
                with self.subTest(label=label):
                    self.assertIn(FMT_FLAGGED, text)
                    for forbidden in FORBIDS:
                        self.assertNotIn(forbidden, text)
            found.update(prompts)
        for label in ("impl-1", "fix-wave", "sync-1", "sync-resolve-1"):
            with self.subTest(only=label):
                self.assertIn(ONLY_PRE_COMMIT, found[label])


if __name__ == "__main__":
    unittest.main()
