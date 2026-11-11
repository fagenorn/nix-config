"""forge-claim land (issue 629): the cross-host land lock against the fake gh and its ref store."""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
from datetime import datetime, timezone

from agent_tools.claims import forge_claim
from agent_tools.claims import forge_land_lock as land_lock
from agent_tools.claims import forge_markers as fm
from .forge_world import ForgeWorld, host_clock

SLUG, BRANCH = "octo/widgets", "main"
OWNER, NAME = SLUG.split("/")
REF = "refs/agent-locks/land/main"
A, B, C, D = "a" * 40, "b" * 40, "c" * 40, "d" * 40
OTHER = "eleven-m5/session-b"
T0 = "2026-11-06T10:00:00Z"


def pull(number, state="open", merged=False, base=BRANCH, sha=A):
    return {"number": number, "state": state, "merged_at": T0 if merged else None,
            "base": {"ref": base}, "head": {"ref": f"issue-{number}-x", "sha": sha}}


def land(action, sha, *extra):
    return ["land", action, "--repo", SLUG, "--branch", BRANCH, "--sha", sha, *extra]


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = forge_claim.main(list(argv))
    lines = out.getvalue().splitlines()
    assert len(lines) == 1, out.getvalue()
    return code, json.loads(lines[0])


def start_cli(*argv):
    return subprocess.Popen([sys.executable, "-m", "agent_tools.claims.forge_claim", *argv], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=dict(os.environ))


def finish(proc):
    stdout, _ = proc.communicate(timeout=120)
    lines = stdout.splitlines()
    assert len(lines) == 1, stdout
    return proc.returncode, json.loads(lines[0])


class Base(unittest.TestCase):
    def setUp(self):
        self.slept = []
        patcher = mock.patch.object(forge_claim, "sleep", self.slept.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.world = ForgeWorld(self)

    def lock(self, sha=None, **kwargs):
        self.world.ref_store(SLUG, {REF: sha} if sha else {}, **kwargs)
        self.closed = []
        self.respond_closed()

    def respond_closed(self):
        self.world.respond_json("gh", [
            "api", f"repos/{SLUG}/pulls?state=closed&base={BRANCH}&sort=updated&direction=desc&per_page=100&page=1"],
            self.closed)

    def pulls(self, sha, *prs, by_commit=False):
        """Register the forge's answers for `sha` the way GitHub gives them: the commit lookup lists
        only open pull requests (a commit outside the default branch), the closed listing has the
        closed ones; `by_commit` is a merge commit into the default branch, which lists them too."""
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{sha}/pulls?per_page=100"],
                                [p for p in prs if by_commit or p["state"] == "open"])
        self.closed = [p for p in self.closed if p not in prs] + [p for p in prs if p["state"] != "open"]
        self.respond_closed()
        for p in prs:
            self.closing(p["number"])

    def closing(self, pr, *issues):
        self.world.respond_json(
            "gh", ["api", "graphql", "-f", f"query={fm.CLOSING_ISSUES}", "-f", f"owner={OWNER}",
                   "-f", f"name={NAME}", "-F", f"number={pr}"],
            {"data": {"repository": {"pullRequest": {"closingIssuesReferences": {
                "nodes": [{"number": i} for i in issues]}}}}})

    def cas_calls(self):
        return [a for a in self.world.argvs("gh") if a[:2] == ["api", "graphql"] and "updateRefs(" in a[3]]

    def writes(self):
        return [a for a in self.world.argvs("gh") if a[:3] == ["api", "-X", "POST"]] + self.cas_calls()


class AcquireTest(Base):
    def test_free_lock_is_acquired_by_create(self):
        self.lock()
        self.pulls(A, pull(11, sha=A))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"], out["took_over"]),
                         (0, "acquired", A, 11, None))
        self.assertEqual(self.world.refs(), {REF: A})
        self.assertEqual(self.cas_calls(), [])

    def test_own_sha_is_already_held(self):
        self.lock(A)
        self.pulls(A, pull(11, sha=A))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"]), (0, "already_held"))
        self.assertEqual(self.cas_calls(), [])

    def test_open_lock_is_held_by_with_derived_holder(self):
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, sha=B))
        self.closing(12, 7)
        self.world.comment_store(SLUG, 7, [{"id": 5, "updated_at": T0, "created_at": T0, "body": fm.render(
            "claim", {"issue": "7", "holder": OTHER}, f"Claimed by {OTHER}.")}])
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"], out["by"]), (3, "held_by", B, 12, OTHER))
        self.assertEqual(self.world.refs(), {REF: B})
        self.assertEqual(self.cas_calls(), [])

    def test_lock_without_pull_request_is_held_by(self):
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B)
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["pr"], out["by"]), (3, "held_by", None, None))
        self.assertEqual(self.cas_calls(), [])

    def test_no_open_pull_request_writes_nothing(self):
        for prs in ((), (pull(11, base="dev"),), (pull(11, state="closed", merged=True),), (pull(11, sha=B),)):
            with self.subTest(prs=prs):
                self.world.reset()
                self.lock()
                self.pulls(A, *prs)
                code, out = run(*land("acquire", A))
                self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "no_open_pr"))
                self.assertEqual(self.writes(), [])

    def test_same_pull_request_new_head_moves_the_lock(self):
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(11, sha=A))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (0, "moved", A))
        self.assertEqual(self.world.refs(), {REF: A})
        self.assertEqual([[a[-3], a[-1]] for a in self.cas_calls()], [[f"before={B}", f"after={A}"]])

    def test_merged_or_closed_lock_is_taken_over(self):
        for merged in (True, False):
            with self.subTest(merged=merged):
                self.world.reset()
                self.lock(B)
                self.pulls(A, pull(11, sha=A))
                self.pulls(B, pull(12, state="closed", merged=merged, sha=B))
                code, out = run(*land("acquire", A))
                self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "closed"))
                self.assertEqual(self.world.refs(), {REF: A})

    def test_a_merged_holder_the_commit_lookup_does_not_list_is_taken_over(self):
        """Squash or rebase merges and closed pull requests leave the head outside the default branch."""
        for state, merged in (("closed", True), ("closed", False)):
            with self.subTest(merged=merged):
                self.world.reset()
                self.lock(B)
                self.pulls(A, pull(11, sha=A))
                self.pulls(B, pull(12, state=state, merged=merged, sha=B))
                code, out = run(*land("status", A))
                self.assertEqual((code, out["verdict"], out["pr"]), (0, "stale", 12))
                code, out = run(*land("acquire", A))
                self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "closed"))
                self.assertEqual(self.world.refs(), {REF: A})

    def test_a_holder_listed_by_the_commit_lookup_needs_no_closed_listing(self):
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, state="closed", merged=True, sha=B), by_commit=True)
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "closed"))
        self.assertEqual([a for a in self.world.argvs("gh") if any("state=closed" in p for p in a)], [])

    def test_a_lying_cas_is_classified_by_the_re_read(self):
        self.lock(B, cas_lies=1)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, state="closed", merged=True, sha=B))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"]), (0, "acquired"))

    def stale_after_cas(self, *stale_reads):
        """A read_ref that answers each of `stale_reads` after the swap applied, then the truth."""
        real, pending = fm.read_ref, list(stale_reads)

        def read(*args):
            truth = real(*args)
            if truth == A and pending:
                return pending.pop(0)  # read-after-write lag: the swap applied, the read shows the old sha
            return truth
        return mock.patch.object(fm, "read_ref", read)

    def test_a_successful_cas_with_a_stale_read_back_answers_moved(self):
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(11, sha=A))
        with mock.patch.object(land_lock, "sleep", self.slept.append), self.stale_after_cas(B, B):
            code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (0, "moved", A))
        self.assertEqual(self.world.refs(), {REF: A})
        self.assertEqual(len(self.cas_calls()), 1)

    def test_a_read_back_that_stays_stale_past_the_retries_is_lost_to(self):
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(11, sha=A))
        with mock.patch.object(land_lock, "sleep", self.slept.append), self.stale_after_cas(*[B] * 20):
            code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (3, "lost_to", B))
        self.assertLessEqual(len(self.slept), land_lock.READBACK_RETRIES)

    def test_a_read_back_naming_a_third_sha_is_lost_to_without_a_retry(self):
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(11, sha=A))
        self.pulls(C, pull(12, sha=C))
        real = fm.cas_ref

        def racing_cas(*args):
            failure = real(*args)
            self.world.set_ref(REF, C)  # another host took the lock after our swap
            return failure
        with mock.patch.object(land_lock, "sleep", self.slept.append), mock.patch.object(fm, "cas_ref", racing_cas):
            code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (3, "lost_to", C))
        self.assertEqual(self.slept, [])

    def test_a_failed_cas_on_an_unchanged_lock_is_a_forge_error(self):
        for failure in ("gh_failed", "gh_timeout"):
            with self.subTest(failure=failure):
                self.world.reset()
                self.lock(B)
                self.pulls(A, pull(11, sha=A))
                self.pulls(B, pull(12, state="closed", merged=True, sha=B))
                with mock.patch.object(fm, "cas_ref", lambda *args, f=failure: fm.ForgeError(f, "x")):
                    code, out = run(*land("acquire", A))
                self.assertEqual((code, out["verdict"], out["error"]), (1, "error", failure))
                self.assertEqual(self.world.refs(), {REF: B})


class HeadClassificationTest(Base):
    """Plan D2/D5: the head of an open pull request holds the lock; containment never decides."""

    def test_a_stacked_branch_cannot_move_the_holders_lock(self):
        self.lock(B)  # head of host 1's open PR 11
        self.pulls(A, pull(13, sha=A))  # host 2's PR 13 is branched from PR 11, so it contains B
        self.pulls(B, pull(11, sha=B), pull(13, sha=A))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"]), (3, "held_by", B, 11))
        self.assertEqual(self.world.refs(), {REF: B})
        self.assertEqual(self.cas_calls(), [])

    def test_a_pull_request_containing_the_callers_sha_is_not_the_callers(self):
        self.lock(B)  # head of host 2's PR 13, stacked on the caller's PR 11
        self.pulls(A, pull(11, sha=A), pull(13, sha=B))
        self.pulls(B, pull(13, sha=B))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["pr"]), (3, "held_by", 13))
        self.assertEqual(self.cas_calls(), [])

    def test_a_merged_head_synced_into_open_pull_requests_is_stale(self):
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, state="closed", merged=True, sha=B), pull(14, sha=D))
        code, out = run(*land("status", A))
        self.assertEqual((code, out["verdict"], out["pr"]), (0, "stale", 12))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "closed"))
        self.assertEqual(self.world.refs(), {REF: A})

    def test_a_holder_past_its_lock_is_still_held(self):
        self.lock(B)  # PR 12's head moved to D; its lock has not moved yet
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, sha=D))
        code, out = run(*land("status", A))
        self.assertEqual((code, out["verdict"], out["pr"]), (0, "held_by", 12))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"]), (3, "held_by"))
        self.assertEqual(self.cas_calls(), [])

    def test_a_stacked_holder_cannot_move_its_own_lock(self):
        # Residual of plan D5: PR 11 moved from B to A, but PR 13 (another host's) also contains B.
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(11, sha=A), pull(13, sha=D))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"]), (3, "held_by", B, 11))
        self.assertEqual(self.cas_calls(), [])

    def test_classify_table(self):
        p = lambda n, state="open", sha=A: fm.Pull(n, state, state == "closed", BRANCH, f"issue-{n}-x", sha)
        rows = ((B, [p(11, sha=B)], {13}, ("held", 11)),
                (B, [p(11, sha=B), p(13)], {13}, ("held", 11)),
                (B, [p(11)], {11}, ("move", 11)),
                (B, [p(11), p(13, sha=D)], {11}, ("held", 11)),
                (B, [p(11, sha=B)], {11}, ("move", 11)),
                (B, [p(12, "closed", B), p(14, sha=D)], (), ("closed", 12)),
                (B, [p(12, "closed", D), p(14, "closed", D)], (), ("closed", 14)),
                (B, [p(12, sha=D)], (), ("held", 12)),
                (B, [], (), ("held", None)))
        for lock, theirs, mine, expected in rows:
            with self.subTest(theirs=theirs, mine=mine):
                self.assertEqual(land_lock.classify(lock, theirs, mine), expected)


class StaleDecisionTest(Base):
    """Plan D3 (owner, option B): a lock on a sha with old events is not stale to a fresh observer."""

    EVENT_READS = ("check-runs", "/reviews", "/activity", "rate_limit", f"/commits/{B}/status")

    def setUp(self):
        super().setUp()
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, sha=B))
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{B}/check-runs?per_page=100"],
                                {"total_count": 1, "check_runs": [{"completed_at": "2020-01-01T00:00:00Z"}]})

    def assert_no_event_read(self):
        for argv in self.world.argvs("gh"):
            self.assertFalse(any(word in part for part in argv for word in self.EVENT_READS), argv)

    def test_status_is_held_by_not_stale(self):
        with host_clock(datetime(2100, 1, 1, tzinfo=timezone.utc), fm, forge_claim):
            code, out = run(*land("status", A))
        self.assertEqual((code, out["verdict"], out["pr"]), (0, "held_by", 12))
        self.assert_no_event_read()

    def test_one_shot_acquire_never_takes_an_open_lock(self):
        with host_clock(datetime(2100, 1, 1, tzinfo=timezone.utc), fm, forge_claim):
            code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"]), (3, "held_by"))
        self.assertEqual(self.cas_calls(), [])
        self.assert_no_event_read()


class ReleaseStatusTest(Base):
    def test_release_deletes_by_cas(self):
        self.lock(A)
        code, out = run(*land("release", A))
        self.assertEqual((code, out["verdict"]), (0, "released"))
        self.assertEqual(self.world.refs(), {})
        self.assertEqual([[a[-3], a[-1]] for a in self.cas_calls()], [[f"before={A}", f"after={fm.ZERO_OID}"]])
        self.assertEqual(self.world.argvs("gh")[0], ["api", f"repos/{SLUG}", "--jq", ".node_id"])

    def test_release_with_a_wrong_before_oid_changes_nothing(self):
        self.lock(B)
        self.pulls(B, pull(12, sha=B))
        code, out = run(*land("release", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"]), (3, "not_held", B, 12))
        self.assertEqual(self.world.refs(), {REF: B})

    def test_a_failed_delete_that_leaves_the_lock_is_a_forge_error(self):
        for failure in ("gh_failed", "gh_timeout"):
            with self.subTest(failure=failure):
                self.world.reset()
                self.lock(A)
                with mock.patch.object(fm, "cas_ref", lambda *args, f=failure: fm.ForgeError(f, "x")):
                    code, out = run(*land("release", A))
                self.assertEqual((code, out["verdict"], out["error"]), (1, "error", failure))
                self.assertEqual(self.world.refs(), {REF: A})

    def test_repeat_release_is_released(self):
        self.lock()
        code, out = run(*land("release", A))
        self.assertEqual((code, out["verdict"]), (0, "released"))

    def test_status_verdicts_and_no_writes(self):
        rows = ((None, (), "free", None), (B, (pull(12, sha=B),), "held_by", 12),
                (B, (pull(12, state="closed", merged=True, sha=B),), "stale", 12),
                (B, (pull(12, state="closed", sha=B), pull(14, state="closed", sha=B)), "stale", 14))
        for lock_sha, prs, verdict, pr in rows:
            with self.subTest(verdict=verdict, prs=len(prs)):
                self.world.reset()
                self.lock(lock_sha)
                if lock_sha:
                    self.pulls(lock_sha, *prs)
                code, out = run(*land("status", A))
                self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"]), (0, verdict, lock_sha, pr))
                self.assertEqual(self.writes(), [])


class CasTransportTest(Base):
    """Issue 740 D2: an unapplied compare-and-swap keeps its failure's transport class in the error."""

    def prepare(self, action):
        self.world.reset()
        if action == "acquire":  # a lock whose pull request merged: the one-shot acquire swaps it
            self.lock(B)
            self.pulls(A, pull(11, sha=A))
            self.pulls(B, pull(12, state="closed", merged=True, sha=B))
        else:
            self.lock(A)

    def raised(self, action, failure):
        args = forge_claim.build_parser().parse_args(land(action, A))
        with mock.patch.object(fm, "cas_ref", lambda *_: failure), \
                self.assertRaises(fm.ForgeError) as caught:
            land_lock.run(args)
        return caught.exception

    def test_an_unapplied_cas_keeps_its_transport_class(self):
        failures = ((fm.ForgeError("gh_failed", "gh: Bad Gateway (HTTP 502)", transient=True), True),
                    (fm.ForgeError("gh_timeout", "api graphql"), True),
                    (fm.ForgeError("gh_failed", "gh: Forbidden (HTTP 403)"), False))
        for action in ("acquire", "release"):
            for failure, transient in failures:
                with self.subTest(action=action, failure=failure.detail):
                    self.prepare(action)
                    before = self.world.refs()
                    error = self.raised(action, failure)
                    self.assertEqual((error.code, error.transient), (failure.code, transient))
                    self.assertEqual(self.world.refs(), before)

    def test_a_delete_reported_applied_that_left_the_lock_is_not_transient(self):
        self.prepare("release")
        error = self.raised("release", None)
        self.assertEqual((error.code, error.transient), ("gh_failed", False))
        self.assertEqual(self.world.refs(), {REF: A})


class TransientRetryTest(Base):
    """Issue 740 D3: one-shot land acquire and land release retry whole; --wait and status run once."""

    def test_acquire_after_two_network_failures_is_acquired(self):
        self.lock()
        self.pulls(A, pull(11, sha=A))
        self.world.outage(2)
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (0, "acquired", A))
        self.assertEqual(self.slept, [20, 40])

    def test_acquire_retried_after_its_create_lost_its_reply_is_acquired(self):
        # The retry cannot tell its own lost-reply create from a lock already held, so it reports
        # acquired: the programs recheck the base before merging on acquired, never on already_held.
        self.lock(lose_reply=["create"])
        self.pulls(A, pull(11, sha=A))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (0, "acquired", A))
        self.assertEqual(self.world.refs(), {REF: A})
        self.assertEqual(self.slept, [20])

    def test_release_retried_after_its_reread_lost_its_reply_is_released(self):
        self.lock(A, lose_reply=["get"])
        code, out = run(*land("release", A))
        self.assertEqual((code, out["verdict"]), (0, "released"))
        self.assertEqual(self.world.refs(), {})
        self.assertEqual(self.slept, [20])

    def bad_gateway_once(self):
        """`cas_ref` whose first swap answers HTTP 502 and does not apply; later swaps are real."""
        real, failed = fm.cas_ref, []

        def cas(*args):
            if not failed:
                failed.append(True)
                return fm.ForgeError("gh_failed", "gh: Bad Gateway (HTTP 502)", transient=True)
            return real(*args)
        return mock.patch.object(fm, "cas_ref", cas)

    def test_release_retried_after_an_unapplied_502_swap_is_released(self):
        self.lock(A)
        with self.bad_gateway_once():
            code, out = run(*land("release", A))
        self.assertEqual((code, out["verdict"]), (0, "released"))
        self.assertEqual(self.world.refs(), {})
        self.assertEqual(self.slept, [20])

    def test_acquire_retried_after_an_unapplied_502_swap_takes_the_closed_lock(self):
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, state="closed", merged=True, sha=B))
        with self.bad_gateway_once():
            code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (0, "acquired", A))
        self.assertEqual(self.world.refs(), {REF: A})
        self.assertEqual(self.slept, [20])

    def test_a_lasting_outage_is_error_transient_after_three_tries(self):
        for argv in (land("acquire", A), land("release", A)):
            with self.subTest(action=argv[1]):
                self.slept.clear()
                self.world.reset()
                self.lock(A)
                self.pulls(A, pull(11, sha=A))
                self.world.outage()
                code, out = run(*argv)
                self.assertEqual((code, out["verdict"], out["transient"]), (1, "error", True))
                self.assertEqual(self.slept, [20, 40])

    def test_wait_and_status_run_once(self):
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.world.outage()
        clock = FakeClock()
        with mock.patch.object(land_lock, "monotonic", clock.monotonic), \
                mock.patch.object(land_lock, "sleep", clock.sleep):
            code, out = run(*land("acquire", A, "--wait"))
        self.assertEqual((code, out["verdict"], out["transient"]), (1, "error", True))
        code, out = run(*land("status", A))
        self.assertEqual((code, out["verdict"], out["transient"]), (1, "error", True))
        self.assertEqual(self.slept, [])


class ConcurrencyTest(Base):
    """Children of `python -m agent_tools.claims.forge_claim land` racing on one ref store."""

    def test_racing_acquires_leave_one_holder(self):
        self.lock()
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, sha=B))
        results = [finish(p) for p in (start_cli(*land("acquire", A)), start_cli(*land("acquire", B)))]
        verdicts = sorted((code, out["verdict"]) for code, out in results)
        self.assertEqual(verdicts, [(0, "acquired"), (3, "held_by")])
        winner = next(out["sha"] for code, out in results if code == 0)
        self.assertEqual(self.world.refs(), {REF: winner})

    def test_two_stealers_of_a_merged_lock_one_wins(self):
        self.lock(C, schedule=["get", "get", "cas", "cas"])
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, sha=B))
        self.pulls(C, pull(10, state="closed", merged=True, sha=C))
        results = [finish(p) for p in (start_cli(*land("acquire", A)), start_cli(*land("acquire", B)))]
        verdicts = sorted((code, out["verdict"]) for code, out in results)
        self.assertEqual(verdicts, [(0, "acquired"), (3, "lost_to")])
        winner = next(out for code, out in results if code == 0)
        loser = next(out for code, out in results if code == 3)
        self.assertEqual(self.world.refs(), {REF: winner["sha"]})
        self.assertEqual(loser["lock_sha"], winner["sha"])
        self.assertEqual(len(self.cas_calls()), 2)

    def test_wrong_release_through_the_cli(self):
        self.lock(B)
        self.pulls(B, pull(12, sha=B))
        code, out = finish(start_cli(*land("release", A)))
        self.assertEqual((code, out["verdict"]), (3, "not_held"))
        self.assertEqual(self.world.refs(), {REF: B})


class ClockTest(Base):
    """A wrong wall clock changes no verdict (no host clock is read)."""

    def test_verdicts_hold_under_a_wrong_host_clock(self):
        for instant in (datetime(1970, 1, 2, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc)):
            rows = (("acquire", None, (), "acquired", 0), ("acquire", B, (pull(12, sha=B),), "held_by", 3),
                    ("acquire", B, (pull(12, state="closed", merged=True, sha=B),), "acquired", 0),
                    ("release", B, (pull(12, sha=B),), "not_held", 3),
                    ("status", B, (pull(12, sha=B),), "held_by", 0),
                    ("status", B, (pull(12, state="closed", sha=B),), "stale", 0))
            for action, lock_sha, prs, verdict, exit_code in rows:
                with self.subTest(instant=instant.year, action=action, verdict=verdict):
                    self.world.reset()
                    self.lock(lock_sha)
                    self.pulls(A, pull(11, sha=A))
                    if lock_sha:
                        self.pulls(lock_sha, *prs)
                    with host_clock(instant, fm, forge_claim):
                        code, out = run(*land(action, A))
                    self.assertEqual((code, out["verdict"]), (exit_code, verdict))


class CliTest(Base):
    def test_usage_error_is_one_land_shaped_line(self):
        code, out = finish(start_cli("land", "acquire", "--repo", SLUG, "--branch", BRANCH, "--sha", "nothex"))
        self.assertEqual((code, out["command"], out["action"], out["verdict"], out["error"]),
                         (2, "land", "acquire", "error", "usage"))
        self.assertEqual(set(out) >= {"repo", "branch", "sha", "lock_sha", "pr", "by", "took_over", "waited_s"}, True)

    def test_forge_error_exit_1(self):
        self.lock()
        code, out = run(*land("acquire", A))  # commit pulls unregistered: fake gh exits 64
        self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "gh_failed"))

    def test_issue_claim_commands_unchanged(self):
        code, out = finish(start_cli("acquire", "--repo", SLUG, "--issue", "x", "--holder", OTHER))
        self.assertEqual((code, out["error"], out["issue"]), (2, "usage", None))


class DocstringTest(unittest.TestCase):
    def test_the_module_docstring_states_no_known_limitation(self):
        # The stacked-holder residual belongs to ADR-claims-004 Consequences, never to source (D4).
        self.assertNotIn("also contained", land_lock.__doc__)


class FakeClock:
    """`monotonic` and `sleep` for forge_land_lock; `on_sleep(elapsed)` runs after each sleep."""

    def __init__(self, on_sleep=None):
        self.start = self.now = 1000.0
        self.slept, self.on_sleep = [], on_sleep

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(self.now - self.start)


class WaitTest(Base):
    def setUp(self):
        super().setUp()
        self.prepare(B)

    def prepare(self, lock_sha):
        self.lock(lock_sha)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, sha=B))
        self.pulls(C, pull(12, sha=C))

    def wait(self, clock):
        with mock.patch.object(land_lock, "monotonic", clock.monotonic), \
                mock.patch.object(land_lock, "sleep", clock.sleep):
            return run(*land("acquire", A, "--wait"))

    def attempts(self):
        return [a for a in self.world.argvs("gh") if a[:4] == ["api", "-X", "POST", f"repos/{SLUG}/git/refs"]]

    def move_once(self, at, sha):
        done = []

        def on_sleep(elapsed):
            if elapsed >= at and not done:
                done.append(True)
                self.world.set_ref(REF, sha)
        return on_sleep

    def test_never_released_lock_gives_up_land_contended(self):
        clock = FakeClock(self.move_once(2400, C))  # the holder moves its lock: the watch restarts at 2400
        code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["waited_s"], out["lock_sha"], out["pr"]),
                         (3, "land-contended", 3600, C, 12))
        self.assertEqual(clock.slept, [120] * 30)
        self.assertEqual(len(self.attempts()), 31)
        self.assertEqual(self.cas_calls(), [])
        self.assertEqual(self.world.refs(), {REF: C})

    def test_waiter_takes_over_only_after_its_own_45_minute_watch(self):
        clock = FakeClock()
        with host_clock(datetime(2100, 1, 1, tzinfo=timezone.utc), fm, forge_claim):
            code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]), (0, "acquired", "idle", 2760))
        self.assertEqual(len(self.attempts()), 24)  # 0 .. 2640 held_by (< 2700), 2760 takes over
        self.assertEqual(len(self.cas_calls()), 1)
        self.assertEqual(self.world.refs(), {REF: A})

    def test_a_moved_oid_restarts_the_watch(self):
        clock = FakeClock(self.move_once(600, C))
        code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]), (0, "acquired", "idle", 3360))
        self.assertEqual([[a[-3], a[-1]] for a in self.cas_calls()], [[f"before={C}", f"after={A}"]])

    def test_a_release_while_waiting_is_acquired_by_create(self):
        clock = FakeClock(self.move_once(360, None))
        code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]), (0, "acquired", None, 360))
        self.assertEqual(self.cas_calls(), [])

    def test_transient_poll_failures_are_skipped_then_fatal(self):
        real, calls = fm.create_ref, [0]

        def flaky(*args):
            calls[0] += 1
            if calls[0] <= limit:
                raise fm.ForgeError("gh_failed", "boom")
            return real(*args)
        for limit, expected in ((2, (0, "acquired")), (3, (1, "error"))):
            with self.subTest(limit=limit):
                self.world.reset()
                self.prepare(None)
                calls[0] = 0
                clock = FakeClock()
                with mock.patch.object(fm, "create_ref", flaky):
                    code, out = self.wait(clock)
                self.assertEqual((code, out["verdict"]), expected)
                self.assertEqual(clock.slept, [120, 120])

    def test_only_consecutive_failed_polls_are_fatal(self):
        real, calls = fm.create_ref, [0]

        def flaky(*args):
            calls[0] += 1
            if calls[0] % 3:
                raise fm.ForgeError("gh_failed", "boom")  # two failed polls, then one that answers
            return real(*args)
        clock = FakeClock()
        with mock.patch.object(fm, "create_ref", flaky):
            code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "idle"))
        self.assertGreater(len(clock.slept), 3)

    def test_an_interrupted_watch_restarts(self):
        """Plan D4: watch B, lose the CAS and see C, then see B again: B's 45 minutes start afresh."""
        real, raced = fm.cas_ref, []

        def racing_cas(*args):
            if not raced:
                raced.append(True)
                self.world.set_ref(REF, C)  # another taker wins B first
            return real(*args)
        clock = FakeClock(self.move_once(2880, B))  # ... and B comes back
        with mock.patch.object(fm, "cas_ref", racing_cas):
            code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["waited_s"]), (3, "land-contended", B, 3600))
        self.assertEqual(len(self.cas_calls()), 1)  # 2760 lost to C; B seen anew at 2880 needs until 5580
        self.assertEqual(self.world.refs(), {REF: B})

    def test_an_observed_absence_restarts_the_watch(self):
        clock = FakeClock()
        real, gone = fm.read_ref, []

        def read(*args):
            if clock.now - clock.start >= 1200 and not gone:
                gone.append(True)
                return None  # released and re-taken at B between two reads
            return real(*args)
        with mock.patch.object(fm, "read_ref", read):
            code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (3, "land-contended", B))
        self.assertEqual(self.cas_calls(), [])  # B's watch restarted at 1200: 3900 > 3600

    def test_unchanged_cas_failures_exit_on_the_third_poll(self):
        for failure in ("gh_failed", "gh_timeout"):
            with self.subTest(failure=failure):
                self.world.reset()
                self.lock(B)
                self.pulls(A, pull(11, sha=A))
                self.pulls(B, pull(12, state="closed", merged=True, sha=B))
                clock = FakeClock()
                with mock.patch.object(fm, "cas_ref", lambda *args, f=failure: fm.ForgeError(f, "x")):
                    code, out = self.wait(clock)
                self.assertEqual((code, out["verdict"], out["error"]), (1, "error", failure))
                self.assertEqual(clock.slept, [120, 120])
                self.assertEqual(self.world.refs(), {REF: B})

    def test_a_waiter_whose_head_moved_stops_without_touching_the_lock(self):
        """PR 11 advances from A to C while the A-waiter sleeps and another process takes C."""
        def advance(elapsed):
            if elapsed >= 120 and not moved:
                moved.append(True)
                self.pulls(A, pull(11, sha=C))  # A is still contained in PR 11, whose head is now C
                self.pulls(C, pull(11, sha=C))
                self.world.set_ref(REF, C)
        moved = []
        clock = FakeClock(advance)
        code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "no_open_pr"))
        self.assertEqual(self.cas_calls(), [])
        self.assertEqual(self.world.refs(), {REF: C})
        self.assertEqual(clock.slept, [120])

    def test_one_shot_acquire_never_sleeps(self):
        with mock.patch.object(land_lock, "sleep", side_effect=AssertionError("slept")):
            code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["waited_s"]), (3, "held_by", None))

    def test_wait_is_only_an_acquire_flag(self):
        code, out = run(*land("status", A, "--wait"))
        self.assertEqual((code, out["error"]), (2, "usage"))


class WaitFirstReadTest(Base):
    """Issue 740 D3: --wait reads its first eligibility inside its bounded polls (D8)."""

    def wait(self, clock):
        with mock.patch.object(land_lock, "monotonic", clock.monotonic), \
                mock.patch.object(land_lock, "sleep", clock.sleep):
            return run(*land("acquire", A, "--wait"))

    def test_a_failed_first_read_is_a_failed_poll_then_acquires(self):
        self.lock()
        self.pulls(A, pull(11, sha=A))
        self.world.outage(1)
        clock = FakeClock()
        code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (0, "acquired", A))
        self.assertEqual(clock.slept, [land_lock.POLL])
        self.assertEqual(self.slept, [])  # the whole-verb retry never wraps --wait

    def test_first_reads_failing_every_poll_are_fatal_on_the_third_and_write_nothing(self):
        self.lock()
        self.pulls(A, pull(11, sha=A))
        self.world.outage()
        clock = FakeClock()
        code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["error"], out["transient"]),
                         (1, "error", "gh_failed", True))
        self.assertEqual(clock.slept, [land_lock.POLL, land_lock.POLL])
        self.assertEqual(self.world.refs(), {})
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.slept, [])

    def test_no_open_pr_on_the_first_read_stops_at_once(self):
        self.lock()
        self.pulls(A)
        clock = FakeClock()
        code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "no_open_pr"))
        self.assertEqual(clock.slept, [])


class IdleRaceTest(Base):
    def test_concurrent_idle_stealers_one_wins(self):
        self.lock(C, schedule=["get", "get", "cas", "cas"])
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(13, sha=B))
        self.pulls(C, pull(12, sha=C))
        mine = {A: [fm.Pull(11, "open", False, BRANCH, "issue-11-x", A)],
                B: [fm.Pull(13, "open", False, BRANCH, "issue-13-x", B)]}

        def steal(sha):
            return land_lock.acquire_once(SLUG, BRANCH, sha, mine[sha], lambda _: True, lambda: "R_kgDOtest")
        with ThreadPoolExecutor(2) as pool:
            outcomes = list(pool.map(steal, (A, B)))
        self.assertEqual(sorted(o.verdict for o in outcomes), ["acquired", "lost_to"])
        winner = next(o for o in outcomes if o.verdict == "acquired")
        self.assertEqual(winner.took_over, "idle")
        self.assertEqual(self.world.refs(), {REF: winner.lock_sha})
