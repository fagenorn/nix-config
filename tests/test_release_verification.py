"""release_verification: the candidate's required-CI receipt (#128 spec §3, D5, D22)."""
import unittest
from unittest import mock

from agent_tools import release_verification as verification
from agent_tools.canonical import telemetry_digest
from .forge_world import CANONICAL, ForgeWorld

NOW = 1_790_000_000_000


def observe(**overrides):
    arguments = {"project_id": "fagenorn/nix-config", "profile_id": "github-release",
                 "profile_digest": "sha256:" + "a" * 64, "repository": CANONICAL["slug"],
                 "integration_branch": "main", "default_branch": "main",
                 "commit": CANONICAL["commit"], "version": "v1.2.3", "clock": lambda: NOW}
    return verification.observe(**{**arguments, **overrides})


def run(identifier, name, status="completed", conclusion="success", app=15368):
    return {"id": identifier, "name": name, "status": status, "conclusion": conclusion,
            "app": {"id": app}}


class ReceiptTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def test_passed_receipt_is_closed_and_canonical(self):
        self.world.verification_ready()
        receipt = observe()
        self.assertEqual(sorted(receipt), ["candidate", "checks", "observed_at", "profile",
                                           "profile_digest", "project", "required", "result",
                                           "schema"])
        self.assertEqual(receipt["schema"], "release-verification/v1")
        self.assertEqual(receipt["candidate"], {"commit": CANONICAL["commit"], "version": "v1.2.3"})
        self.assertEqual(receipt["required"], [{"context": "Nix Eval", "app_id": None},
                                               {"context": "Instruction Budget", "app_id": None}])
        self.assertEqual(receipt["checks"], [
            {"context": "Nix Eval", "status": "completed", "conclusion": "success"},
            {"context": "Instruction Budget", "status": "completed", "conclusion": "success"}])
        self.assertEqual((receipt["result"], receipt["observed_at"]),
                         ("passed", "2026-09-21T14:13:20.000Z"))
        self.assertEqual(verification.evidence_id(receipt),
                         "verification:" + telemetry_digest(receipt))
        self.assertNotIn("\n", verification.canonical_text(receipt))
        self.assertEqual([c["argv"][0] for c in self.world.calls()], ["api", "api", "api"])
        self.assertFalse(any(c["token_visible"] for c in self.world.calls()))

    def test_failed_pending_and_missing(self):
        cases = {"failed": [run(1, "Nix Eval", conclusion="failure"), run(2, "Instruction Budget")],
                 "pending": [run(1, "Nix Eval", status="in_progress", conclusion=None),
                             run(2, "Instruction Budget")],
                 "missing": [run(2, "Instruction Budget")]}
        for name, runs in cases.items():
            with self.subTest(case=name):
                self.world.verification_ready(runs=runs)
                receipt = observe()
                self.assertEqual(receipt["result"], "pending" if name == "missing" else name)
        self.assertEqual(receipt["checks"][0],
                         {"context": "Nix Eval", "status": "missing", "conclusion": None})

    def test_the_run_with_the_largest_id_decides(self):
        for runs, result in (([run(5, "Nix Eval", conclusion="failure"), run(7, "Nix Eval")],
                              "passed"),
                             ([run(7, "Nix Eval", conclusion="failure"), run(5, "Nix Eval")],
                              "failed")):
            with self.subTest(result=result):
                self.world.verification_ready(checks=[{"context": "Nix Eval", "app_id": None}],
                                              runs=runs)
                self.assertEqual(observe()["result"], result)

    def test_a_required_app_id_must_match(self):
        self.world.verification_ready(checks=[{"context": "Nix Eval", "app_id": 15368}],
                                      runs=[run(1, "Nix Eval", app=999)])
        receipt = observe()
        self.assertEqual((receipt["result"], receipt["checks"][0]["status"]), ("pending", "missing"))


class RefusalTest(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def assertRefused(self, code):
        with self.assertRaises(verification.VerificationRefused) as caught:
            observe()
        self.assertEqual(caught.exception.code, code)
        self.assertLessEqual(len(caught.exception.detail), 240)

    def test_a_moved_integration_tip_is_stale_and_reads_nothing_else(self):
        self.world.verification_ready(tip="9" * 40)
        self.assertRefused("candidate_stale")
        self.assertEqual(len(self.world.calls()), 1)

    def test_an_unestablished_floor_is_unavailable(self):
        for name, kwargs in (("protection 404", {"protection_exit": 1}),
                             ("no required checks", {"checks": [], "runs": []}),
                             ("more than one page", {"total_count": 101})):
            with self.subTest(case=name):
                self.world.reset()
                self.world.verification_ready(**kwargs)
                self.assertRefused("verification_unavailable")

    def test_a_failed_tip_read_is_unavailable(self):
        self.assertRefused("verification_unavailable")

    def test_the_shared_budget_bounds_every_read(self):
        self.world.verification_ready(sleep=2)
        with mock.patch.object(verification, "READ_BUDGET_SECONDS", 1):
            self.assertRefused("verification_unavailable")


if __name__ == "__main__":
    unittest.main()
