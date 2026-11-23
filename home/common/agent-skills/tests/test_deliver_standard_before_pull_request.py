"""deliver-standard.js verifies with the contract's pre-pull-request list when it sets one.

The program runs under the node harness against stub agents. The helpers come from the program test module,
imported as a module so that unittest does not collect its test classes a second time.
Run: just agent-workflow-tests
"""

from __future__ import annotations

import json
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
MARKER = ("// suppress-standard:B17 the delivery program's phases share module state (setup, verify, the look loop), "
          "so the program stays one file")


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


if __name__ == "__main__":
    unittest.main()
