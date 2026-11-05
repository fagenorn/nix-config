"""Verification blockers resolved by `workflow-state direct-owner` (issue 545), through the
CLI from source.

Run: just agent-workflow-tests
"""

import json
import unittest

from agent_tools import attempt_observations
from agent_tools import verification_blocker as vb

from .test_verification_suspension import (DIRECT_NOW, NEXT, VerificationHarness, failure,
                                           observed)

X = failure()
X_ID = vb.blocker_id(X)
REQUIREMENT = {"kind": "verification", "blocker_id": X_ID,
               "sources": [{"name": "flake-lock", "paths": ["flake.lock"]}]}


class DirectHarness(VerificationHarness):
    def setUp(self):
        super().setUp()
        self.acquire_direct(issue=73)
        self.run_id = self.direct_run_id(73, 1)
        self.park(73, X, now=DIRECT_NOW(5))

    def request(self, minute, *observations, **fields):
        return self.direct_request(issue=73, now=DIRECT_NOW(minute),
                                   verification=list(observations), **fields)

    def direct(self, minute, *observations, **fields):
        done = self.direct_owner_at_root(self.root, self.request(minute, *observations,
                                                                 **fields))
        return self.validated_response(done.stdout)

    def refused(self, raw):
        path = self.root / "refused-direct-request.json"
        path.write_bytes(raw)
        return self.run_cli("direct-owner", "--repo-root", self.root, "--request-file",
                            path, ok=False)

    def recorded_worktree(self):
        return self.worktree_fact(73, recorded={"path": self.attempt(73)["worktree"],
                                                "state": "matching_issue_branch"})


class GateTest(DirectHarness, unittest.TestCase):
    def test_ask_then_equal_then_a_change_resumes_and_commits_only_then(self):
        before = self.tree_snapshot()
        asked = self.direct(6)
        self.assertEqual((asked["kind"], asked["run_id"], asked["requirements"]),
                         ("observe", self.run_id,
                          [attempt_observations.describe(REQUIREMENT)]))
        self.assertEqual(self.tree_snapshot(), before)
        self.assertEqual(self.direct(7, observed(X)), self.suspended_reply(73))
        self.assertEqual(self.tree_snapshot(), before)
        unrecorded = self.direct(8, observed(X, NEXT))
        self.assertEqual((unrecorded["kind"],
                          [item["kind"] for item in unrecorded["requirements"]]),
                         ("observe", ["recorded_worktree"]))
        self.assertEqual(self.tree_snapshot(), before)
        owner = self.direct(9, observed(X, NEXT), worktree=self.recorded_worktree())
        self.assertEqual((owner["kind"], owner["launch_kind"], owner["action_id"]),
                         ("owner", "resume", "73:1:2"))
        record = self.read_state()["verification_blockers"][X_ID]
        self.assertEqual((record["state"], record["resolution"], record["attempts"]),
                         ("resolved", {"facts": observed(X, NEXT)["facts"]},
                          [{"issue": 73, "attempt": 1}]))
        attempt = self.attempt(73)
        self.assertEqual((attempt["state"], attempt["blocked_on"],
                          attempt["verification_blocker"], len(attempt["launches"])),
                         ("active", None, None, 2))

    def test_a_tracker_halt_still_comes_first(self):
        before = self.tree_snapshot()
        closed = self.direct(6, observed(X, NEXT),
                             tracker=self.tracker_fact(73, state="closed"))
        self.assertEqual((closed["kind"], closed["source"]), ("terminal", "tracker"))
        self.assertEqual(self.tree_snapshot(), before)

    def test_new_run_names_the_blocker_it_waits_on(self):
        before = self.tree_snapshot()
        done = self.direct_owner_raw(request=self.request(6, new_run=True), ok=False)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (
            2, "", "workflow-state: new_run is not applicable: suspended attempt resumes "
                   f"in place once verification blocker {X_ID} resolves\n"))
        self.assertEqual(self.tree_snapshot(), before)


class ExplicitRetryTest(DirectHarness, unittest.TestCase):
    def retry(self, *, blocker_id=X_ID, attempt=1, minute=6, ok=True):
        return self.run_cli("retry-verification", "--repo-root", self.root,
                            "--run-id", self.run_id, "--issue", 73,
                            "--attempt", attempt, "--blocker-id", blocker_id,
                            "--now", DIRECT_NOW(minute), ok=ok)

    def test_retry_preserves_failure_and_needs_normal_acquisition(self):
        before = self.read_state()
        reply = self.validated_response(self.retry().stdout)
        self.assertEqual((reply["kind"], reply["blocked_on"]), ("suspended", "human_gate"))
        after = self.read_state()
        self.assertEqual(after["verification_blockers"], before["verification_blockers"])
        held = self.attempt(73)
        expected = dict(before["issues"]["73"]["attempts"][-1],
                        blocked_on="human_gate", verification_blocker=None)
        self.assertEqual(held, expected)
        self.assertEqual(held["state"], "suspended")
        owner = self.direct(7, worktree=self.recorded_worktree())
        self.assertEqual((owner["kind"], owner["action_id"]), ("owner", "73:1:2"))
        self.assertEqual(self.read_state()["verification_blockers"],
                         before["verification_blockers"])

    def test_stale_identity_or_blocker_refuses_without_writes(self):
        before = self.tree_snapshot()
        for arguments in ({"blocker_id": "sha256:" + "0" * 64}, {"attempt": 2}):
            with self.subTest(arguments=arguments):
                done = self.retry(ok=False, **arguments)
                self.assertEqual((done.returncode, done.stdout), (2, ""))
                self.assertEqual(self.tree_snapshot(), before)

    def test_active_attempt_cannot_be_reclassified(self):
        self.retry()
        self.direct(7, worktree=self.recorded_worktree())
        before = self.tree_snapshot()
        done = self.retry(minute=8, ok=False)
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertEqual(self.tree_snapshot(), before)

    def test_an_unreleased_worker_prevents_retry(self):
        state = self.read_state()
        state["workers"].append({"worker_id": "73:1:1:w1", "launch": "73:1:1",
                                 "parent": None, "registered_at": DIRECT_NOW(4),
                                 "released_at": None, "release_event": None})
        self.write_state(state)
        before = self.tree_snapshot()
        done = self.retry(ok=False)
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertIn("all launch workers released", done.stderr)
        self.assertEqual(self.tree_snapshot(), before)

    def test_backward_time_refuses_without_writes(self):
        before = self.tree_snapshot()
        done = self.retry(minute=4, ok=False)
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertIn("time must not move backward", done.stderr)
        self.assertEqual(self.tree_snapshot(), before)


class RefusalTest(DirectHarness, unittest.TestCase):
    def test_an_observation_that_answers_no_open_blocker_exactly_is_refused(self):
        before = self.tree_snapshot()
        other = observed(X)
        other["repository"]["project_id"] = "fagenorn/other"
        unknown = "verification[0].blocker_id: names no open blocker of this run"
        cases = {
            "other repository": (self.request(6, other), "invalid verification observation: "
                                 "verification[0].repository: must equal the blocker's "
                                 "repository"),
            "repeated id": (self.request(6, observed(X), observed(X, NEXT)),
                            "invalid verification observation: verification[1].blocker_id: "
                            "repeats an earlier observation"),
            "unknown id": (self.request(6, observed(failure("environment"))),
                           f"invalid verification observation: {unknown}"),
            "interface 2": ({**self.request(6), "interface_version": 2},
                            "unsupported direct owner interface version"),
        }
        for label, (request, line) in cases.items():
            with self.subTest(case=label):
                done = self.refused(json.dumps(request).encode())
                self.assertEqual((done.returncode, done.stdout, done.stderr),
                                 (2, "", f"workflow-state: {line}\n"))
                self.assertEqual(self.tree_snapshot(), before)
        text = json.dumps(self.request(6))
        done = self.refused((text[:-1] + ', "verification": []}').encode())
        self.assertEqual((done.returncode, done.stdout, done.stderr), (
            2, "", "workflow-state: invalid direct owner request JSON: duplicate JSON key "
                   "'verification'\n"))
        self.assertEqual(self.tree_snapshot(), before)

    def test_an_observation_for_a_run_the_call_would_start_mints_nothing(self):
        before = self.tree_snapshot()
        done = self.refused(json.dumps(self.direct_request(
            issue=74, now=DIRECT_NOW(6), verification=[observed(X)])).encode())
        self.assertEqual((done.returncode, done.stdout, done.stderr), (
            2, "", "workflow-state: invalid verification observation: "
                   "verification[0].blocker_id: names no open blocker of this run\n"))
        # Only the issue lock the call held exists now; no run, index entry or ledger.
        self.assertEqual(self.tree_snapshot(), {**before, "workflows/.direct-74.lock": b""})

    def test_a_resolved_record_is_no_longer_answerable(self):
        self.direct(6, observed(X, NEXT), worktree=self.recorded_worktree())
        before = self.tree_snapshot()
        done = self.refused(json.dumps(self.request(7, observed(X, NEXT))).encode())
        self.assertEqual((done.returncode, done.stdout, done.stderr), (
            2, "", "workflow-state: invalid verification observation: "
                   "verification[0].blocker_id: names no open blocker of this run\n"))
        self.assertEqual(self.tree_snapshot(), before)


class ObserveWireTest(DirectHarness, unittest.TestCase):
    """Issue 545 D9, by behaviour: the observe slot and its build."""

    def test_the_observe_reply_requires_the_slot_and_the_build(self):
        reply = self.direct(6)
        model = self.delivery_model

        def validate(value):
            return model.validate_delivery_object(
                value, expected_kind="workflow-response", notes_max_characters=4096)

        self.assertEqual(validate(json.loads(json.dumps(reply))), reply)
        for member, value in (("build", None), ("slot", "worktree")):
            changed = json.loads(json.dumps(reply))
            changed["requirements"][0]["expects"][member] = value
            with self.subTest(member=member), self.assertRaises(model.DeliveryModelError):
                validate(changed)
        changed = json.loads(json.dumps(reply))
        del changed["requirements"][0]["sources"]
        with self.assertRaises(model.DeliveryModelError):
            validate(changed)


class LegacyBindTest(VerificationHarness, unittest.TestCase):
    """Issue 545 D19: a refused observation keeps only the bind every call commits first."""

    def test_a_refused_observation_leaves_a_legacy_ledger_bound_and_nothing_else(self):
        self.acquire_direct(issue=73)
        self.run_id = self.direct_run_id(73, 1)
        current = self.read_state()
        self.write_state(self._as_legacy(current, 10))
        self.assertEqual(self.read_state()["schema_version"], 10)
        path = self.root / "legacy-direct-request.json"
        path.write_text(json.dumps(self.direct_request(
            issue=73, now=DIRECT_NOW(6), verification=[observed(X)])), "utf-8")
        trees = []
        for call in (1, 2):
            with self.subTest(call=call):
                done = self.run_cli("direct-owner", "--repo-root", self.root,
                                    "--request-file", path, ok=False)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (
                    2, "", "workflow-state: invalid verification observation: "
                           "verification[0].blocker_id: names no open blocker of this run\n"))
                # The schema-11 bind alone: no blocker, attempt, launch or run was written.
                self.assertEqual(self.read_state(), current)
                trees.append(self.tree_snapshot())
        self.assertEqual(trees[1], trees[0])


if __name__ == "__main__":
    unittest.main()
