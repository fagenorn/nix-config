"""forge-claim land permit (D14): whether a merge holds the land lock and, when it has one, its lease."""
from unittest import mock

from agent_tools.claims import forge_land_lock as land_lock

from . import test_forge_land_lock as base

TIER = "fast"

REF = land_lock.lock_ref(base.BRANCH)
LIMIT = land_lock.LEASE_LAPSE - land_lock.MERGE_MARGIN
LOCK_READ = base.LOCK_READ
PERMIT = ["land", "permit", "--repo", base.SLUG, "--branch", base.BRANCH, "--pr", "11"]


def waiter(pr, since, beat, sha):
    ref = land_lock.lease_prefix(base.BRANCH) + f"{base.EPOCH + since}-{pr}-{base.EPOCH + beat}"
    return land_lock.Waiter(base.EPOCH + since, pr, base.EPOCH + beat, ref, sha)


def hold(lock, leases=(), now=None, confirmed=...):
    return land_lock.Hold(lock, tuple(leases), now, lock if confirmed is ... else confirmed)


def problem(held, head, *, pinned=True, pr=11, branch=base.BRANCH):
    return land_lock.merge_problem(held, branch, pr, head, pinned=pinned)


def not_at(lock, head, pr=11):
    return f"the land lock {REF} is at {lock[:7]}, not at the head {head[:7]} of pull request {pr}"


class LandPermitTest(base.Base):
    def lease(self, pr, since, beat, sha):
        self.world.set_ref(waiter(pr, since, beat, sha).ref, sha)

    def test_a_merge_after_a_takeover_a_moment_ago_is_refused_naming_the_holder(self):
        self.lock(base.B)
        self.lease(9, 0, 0, base.B)
        self.forge_time(5)
        code, out = base.run(*base.land("permit", base.A, "--pr", "11", "--pinned"))
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (3, "refuse", base.B))
        self.assertEqual(out["reason"], not_at(base.B, base.A) + "; pull request 9 holds it under a lease")

    def test_a_repository_with_no_land_lock_admits_and_reads_only_the_lock(self):
        self.lock(None)
        for extra in (["--pinned"], []):
            code, out = base.run(*PERMIT, "--sha", base.A, *extra)
            self.assertEqual((code, out["verdict"], out["lock_sha"]), (0, "admit", None))
        self.assertEqual(len(self.reads(LOCK_READ)), 2)
        self.assertEqual([a for a in self.world.argvs("gh") if "matching-refs" in " ".join(a)], [])
        self.assertEqual(self.reads(base.NOW), [])

    def test_a_lock_read_tells_absence_from_an_empty_answer(self):
        self.world.not_found("gh", LOCK_READ)
        code, out = base.run(*PERMIT, "--sha", base.A, "--pinned")
        self.assertEqual((code, out["verdict"]), (0, "admit"))
        self.world.respond("gh", LOCK_READ, stdout="null")
        code, out = base.run(*PERMIT, "--sha", base.A, "--pinned")
        self.assertEqual((code, out["verdict"]), (1, "error"))

    def test_a_lock_that_moves_between_the_reads_is_refused(self):
        self.lock(base.A)
        self.lease(11, 0, 0, base.A)
        self.forge_time(land_lock.LEASE_LAPSE + 1)
        real = land_lock.forge_now

        def moved():
            now = real()
            self.world.set_ref(REF, base.B)
            return now
        with mock.patch.object(land_lock, "forge_now", moved):
            code, out = base.run(*PERMIT, "--sha", base.A, "--pinned")
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (3, "refuse", base.A))
        self.assertEqual(out["reason"], f"the land lock {REF} moved from {base.A[:7]} to {base.B[:7]} "
                                        "while the merge was judged")
        self.assertEqual(problem(hold(base.A, confirmed=None), base.A),
                         f"the land lock {REF} at {base.A[:7]} was released while the merge was judged")

    def test_a_holder_with_no_lease_is_judged_by_the_lock_alone(self):
        self.lock(base.A)
        code, out = base.run(*PERMIT, "--sha", base.A, "--pinned")
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (0, "admit", base.A))
        self.assertEqual(len(self.reads(LOCK_READ)), 2)
        self.assertEqual(self.reads(base.NOW), [])

    def test_an_unpinned_merge_under_a_lock_is_refused(self):
        self.lock(base.A)
        code, out = base.run(*PERMIT, "--sha", base.A)
        self.assertEqual((code, out["verdict"]), (3, "refuse"))
        self.assertEqual(out["reason"], f"the land lock {REF} is held, so the merge must carry "
                                        f"--match-head-commit {base.A}")

    def test_a_lock_at_another_head_with_no_lease_names_no_holder(self):
        self.assertEqual(problem(hold(base.B), base.A), not_at(base.B, base.A))

    def test_the_lease_of_the_pull_request_itself_at_the_lock_names_no_holder(self):
        held = hold(base.B, [waiter(11, 0, 50, base.B)], base.EPOCH + 55)
        self.assertEqual(problem(held, base.A), not_at(base.B, base.A))

    def test_a_newest_lease_at_an_older_head_is_refused(self):
        held = hold(base.A, [waiter(11, 0, 0, base.B)], base.EPOCH + 5)
        self.assertEqual(problem(held, base.A),
                         f"the newest land lease of pull request 11 is at {base.B[:7]}, not at its head {base.A[:7]}")

    def test_the_newest_lease_decides_whatever_the_listing_order(self):
        now = base.EPOCH + 60
        for leases in ([waiter(11, 0, 50, base.A), waiter(11, 10, 10, base.B)],
                       [waiter(11, 10, 10, base.B), waiter(11, 0, 50, base.A)]):
            self.assertEqual(problem(hold(base.A, leases, now), base.A),
                             f"the newest land lease of pull request 11 is at {base.B[:7]}, "
                             f"not at its head {base.A[:7]}")
        for leases in ([waiter(11, 0, 50, base.B), waiter(11, 10, 10, base.A)],
                       [waiter(11, 10, 10, base.A), waiter(11, 0, 50, base.B)]):
            self.assertIsNone(problem(hold(base.A, leases, now), base.A))

    def test_a_beat_at_the_limit_refuses_and_one_second_younger_admits(self):
        held = hold(base.A, [waiter(11, 0, 0, base.A)], base.EPOCH + LIMIT)
        self.assertEqual(problem(held, base.A),
                         f"the newest land lease of pull request 11 last beat {LIMIT} s ago, "
                         f"and a merge needs a beat under {LIMIT} s")
        held = hold(base.A, [waiter(11, 0, 0, base.A)], base.EPOCH + LIMIT - 1)
        self.assertIsNone(problem(held, base.A))

    def test_the_limit_follows_lease_lapse(self):
        held = hold(base.A, [waiter(11, 0, 0, base.A)], base.EPOCH + LIMIT + 50)
        with mock.patch.object(land_lock, "LEASE_LAPSE", land_lock.LEASE_LAPSE + 100):
            self.assertIsNone(problem(held, base.A))

    def test_a_lease_held_past_its_bound_that_still_beats_admits(self):
        now = land_lock.HOLD_BOUND + 10
        held = hold(base.A, [waiter(11, 0, now, base.A)], base.EPOCH + now)
        self.assertIsNone(problem(held, base.A))

    def test_a_pull_request_whose_leases_are_all_dated_ahead_is_refused(self):
        now = base.EPOCH + 100
        ahead = land_lock.QUEUE_SKEW + 1
        self.assertEqual(problem(hold(base.A, [waiter(11, 0, 100 + ahead, base.A)], now), base.A),
                         f"no land lease of pull request 11 is dated at most {land_lock.QUEUE_SKEW} s "
                         "ahead of the forge's clock")
        self.assertIsNone(problem(hold(base.A, [waiter(11, 0, 100 + land_lock.QUEUE_SKEW, base.A)], now),
                                  base.A))

    def test_another_pull_requests_stale_lease_does_not_refuse(self):
        now = LIMIT + land_lock.LEASE_LAPSE
        self.assertIsNone(problem(hold(base.A, [waiter(9, 0, 0, base.A)], base.EPOCH + now), base.A))

    def test_an_unreadable_head_is_refused_only_when_a_lock_exists(self):
        self.lock(base.B)
        argv = ["land", "permit", "--repo", base.SLUG, "--branch", base.BRANCH, "--pr", "11", "--pinned"]
        code, out = base.run(*argv)
        self.assertEqual((code, out["verdict"]), (3, "refuse"))
        self.assertEqual(out["reason"], f"the land lock {REF} is at {base.B[:7]}, and the head of "
                                        "pull request 11 could not be read")
        self.lock(None)
        code, out = base.run(*argv)
        self.assertEqual((code, out["verdict"]), (0, "admit"))

    def test_a_refusal_on_a_long_branch_keeps_its_condition_and_both_heads(self):
        branch = "b" * 250
        number = 10 ** 10 - 1
        holder = [waiter(number, 0, 0, base.B)]
        for text, condition, shas in (
                (problem(hold(base.B, holder, base.EPOCH), base.A, pr=11, branch=branch),
                 ", not at the head ", (base.A[:7], base.B[:7], str(number))),
                (problem(hold(base.A), base.A, pinned=False, branch=branch),
                 "must carry --match-head-commit ", (base.A,)),
                (problem(hold(base.A, confirmed=base.B), base.A, branch=branch),
                 " moved from ", (base.A[:7], base.B[:7]))):
            self.assertLessEqual(len(text), land_lock.REASON_MAX)
            self.assertTrue(text.startswith(f"the land lock {land_lock.LOCK_PREFIX}"), text)
            self.assertIn(condition, text)
            for sha in shas:
                self.assertIn(sha, text)

    def test_a_failed_lock_read_is_a_forge_error_and_is_not_retried(self):
        self.lock(base.A, lose_reply=["get"])
        code, out = base.run(*PERMIT, "--sha", base.A, "--pinned")
        self.assertEqual((code, out["verdict"]), (1, "error"))
        self.assertEqual(len(self.reads(LOCK_READ)), 1)

    def test_a_branch_name_git_allows_is_judged_and_one_it_forbids_is_a_usage_error(self):
        self.lock(None)
        for branch in ("release+next", "rel@x,y=1", "a" * 100):
            with self.subTest(branch):
                code, out = base.run("land", "permit", "--repo", base.SLUG, "--branch", branch, "--pr", "11",
                                     "--sha", base.A, "--pinned")
                self.assertEqual((code, out["verdict"]), (0, "admit"))
        for branch in ("-x", "a b", "a~b", "a:b", "a\\b", ""):
            with self.subTest(branch):
                code, out = base.run("land", "permit", "--repo", base.SLUG, "--branch", branch, "--pr", "11")
                self.assertEqual((code, out["error"]), (2, "usage"))

    def test_permit_without_a_pull_request_is_a_usage_error(self):
        code, out = base.run("land", "permit", "--repo", base.SLUG, "--branch", base.BRANCH, "--sha", base.A)
        self.assertEqual((code, out["error"]), (2, "usage"))
