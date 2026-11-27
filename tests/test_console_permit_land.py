"""The permit judge reads the land lock before it admits a merge: a merge whose pull request does not hold
the land lease is refused, and a project with no lock is judged as before."""
import os
import tempfile
import unittest
from unittest import mock

from agent_tools.claims import forge_land_lock
from agent_tools.claims.forge_land_lock import Hold, Waiter
from agent_tools.console import permit
from agent_tools.console.permit import ALLOW, DENY, ForgeUnreadable, Grant, judge, memoized
from agent_tools.system import forge_api

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_permit import HEAD, SHA, FakeForge

TIER = "fast"

LOCK = forge_land_lock.lock_ref("main")
LEASES = forge_land_lock.lease_prefix("main")
LIMIT = forge_land_lock.LEASE_LAPSE - forge_land_lock.MERGE_MARGIN
NOW = 1000


def lease(pr, oid, age=0):
    beat = NOW - age
    return Waiter(beat, pr, beat, f"{LEASES}{beat}-{pr}-{beat}", oid)


class LandLeaseJudgeTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, self.root)
        self.grant = Grant(
            slug="o/r", root=self.root, strategy="merge", delete_branch=True,
            branch_pattern="issue-<num>-<slug>", issues=frozenset({12}), others=frozenset({13}))
        self.fake = FakeForge()
        self.merge = f"gh pr merge 7 --repo o/r --merge --match-head-commit {SHA} --delete-branch"

    def judge(self, forge=None):
        return judge(self.merge, self.grant, forge or self.fake.forge())

    def assertLandRefused(self, problem):
        verdict = self.judge()
        self.assertEqual((DENY, permit.LAND_LEASE.format(pr=7, problem=problem)),
                         (verdict.decision, verdict.reason))

    def test_a_merge_whose_lock_was_taken_over_is_refused_naming_the_holder(self):
        self.fake.land = Hold(HEAD, (Waiter(100, 9, 100, LEASES + "100-9-100", HEAD),), 105, HEAD)
        verdict = self.judge()
        self.assertEqual(
            (DENY, permit.LAND_LEASE.format(
                pr=7, problem=f"the land lock {LOCK} is at {HEAD[:7]}, not at the head {SHA[:7]} of pull "
                              f"request 7; pull request 9 holds it under a lease")),
            (verdict.decision, verdict.reason))
        self.assertEqual([("land", "o/r", "main")], self.fake.land_calls)

    def test_a_merge_with_no_land_lock_is_allowed_as_before(self):
        verdict = self.judge()
        self.assertEqual((ALLOW, {"pr": 7, "head": SHA}), (verdict.decision, dict(verdict.target)))
        self.assertEqual([("pr", "o/r", 7)], self.fake.calls)
        self.assertEqual([("land", "o/r", "main")], self.fake.land_calls)

    def test_a_merge_holding_a_fresh_lease_at_its_head_is_allowed(self):
        self.fake.land = Hold(SHA, (lease(7, SHA),), NOW, SHA)
        verdict = self.judge()
        self.assertEqual((ALLOW, {"pr": 7, "head": SHA}), (verdict.decision, dict(verdict.target)))

    def test_each_failed_lease_condition_is_named(self):
        cases = {
            "a lease at another head": (
                Hold(SHA, (lease(7, HEAD),), NOW, SHA),
                f"the newest land lease of pull request 7 is at {HEAD[:7]}, not at its head {SHA[:7]}"),
            "a lease that beat too long ago": (
                Hold(SHA, (lease(7, SHA, age=LIMIT),), NOW, SHA),
                f"the newest land lease of pull request 7 last beat {LIMIT} s ago, "
                f"and a merge needs a beat under {LIMIT} s"),
            "a lock that moved while the merge was judged": (
                Hold(SHA, (lease(7, SHA),), NOW, HEAD),
                f"the land lock {LOCK} moved from {SHA[:7]} to {HEAD[:7]} while the merge was judged"),
        }
        for name, (hold, problem) in cases.items():
            with self.subTest(name):
                self.fake.land = hold
                self.assertLandRefused(problem)

    def test_the_land_lock_is_read_on_the_pull_requests_base(self):
        self.fake.pr["base"] = "dev"
        self.judge()
        self.assertEqual([("land", "o/r", "dev")], self.fake.land_calls)

    def test_no_land_read_before_the_head_check_passes(self):
        self.fake.pr["head"] = HEAD
        verdict = self.judge()
        self.assertEqual((DENY, permit.STALE_HEAD.format(pr=7)), (verdict.decision, verdict.reason))
        self.assertEqual([], self.fake.land_calls)

    def test_an_unreadable_land_lock_refuses_the_merge(self):
        self.fake.land_error = ForgeUnreadable("the land lock of main could not be read")
        verdict = self.judge()
        self.assertEqual(
            (DENY, permit.FORGE_UNREADABLE.format(reason="the land lock of main could not be read")),
            (verdict.decision, verdict.reason))

    def test_the_memo_replays_the_land_read(self):
        self.fake.land = Hold(HEAD, (), None, HEAD)
        memo = memoized(self.fake.forge())
        first = self.judge(memo)
        second = self.judge(memo.frozen())
        self.assertEqual(DENY, first.decision)
        self.assertEqual(first, second)
        self.assertEqual([("land", "o/r", "main")], self.fake.land_calls)

    def test_the_land_reader_says_an_unreadable_lock_plainly(self):
        with mock.patch.object(permit.forge_land_lock, "read_hold",
                               side_effect=forge_api.ForgeError("gh_failed", "boom")):
            with self.assertRaises(ForgeUnreadable) as caught:
                permit.read_land("o/r", "main")
        self.assertEqual("the land lock of main could not be read", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
