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
BEAT = "refs/agent-locks/land-beat/main"
BEAT_READ = ["api", f"repos/{SLUG}/git/ref/agent-locks/land-beat/main"]
A, B, C, D, E = "a" * 40, "b" * 40, "c" * 40, "d" * 40, "e" * 40
OTHER = "eleven-m5/session-b"
T0 = "2026-11-06T10:00:00Z"
DEFAULT = "stable"  # the repository's default branch; BRANCH is the locked integration branch
FROM_BRANCH = ["api", f"repos/{SLUG}/pulls?state=all&head={OWNER}:{BRANCH}&sort=updated&direction=desc&per_page=100"]
DEFAULT_READ = ["api", f"repos/{SLUG}", "--jq", ".default_branch"]
OPEN_FROM = ["api", f"repos/{SLUG}/pulls?state=open&head={OWNER}:{BRANCH}&per_page=100"]
OPEN_BASED = ["api", f"repos/{SLUG}/pulls?state=open&base={BRANCH}&sort=updated&direction=desc&per_page=100&page=1"]
CLOSED_BASED = ["api", f"repos/{SLUG}/pulls?state=closed&base={BRANCH}&sort=updated&direction=desc&per_page=100&page=1"]


def pull(number, state="open", merged=False, base=BRANCH, sha=A):
    return {"number": number, "state": state, "merged_at": T0 if merged else None,
            "base": {"ref": base}, "head": {"ref": f"issue-{number}-x", "sha": sha}}


def release_pull(number, state="open", merged=False, base=DEFAULT, sha=A, head_repo=SLUG):
    """A release pull request: the locked branch itself is its head, the default branch its base."""
    return {"number": number, "state": state, "merged_at": T0 if merged else None,
            "base": {"ref": base, "repo": {"full_name": SLUG}},
            "head": {"ref": BRANCH, "sha": sha, "repo": {"full_name": head_repo} if head_repo else None}}


def sync_pull(number, state="open", merged=False, sha=A, head_repo=SLUG):
    """A sync pull request (issue 905): based on the locked branch, its head a commit that is
    already on the default branch, so the commit lookup never lists it."""
    return {"number": number, "state": state, "merged_at": T0 if merged else None,
            "base": {"ref": BRANCH, "repo": {"full_name": SLUG}},
            "head": {"ref": f"sync-{DEFAULT}-into-{BRANCH}", "sha": sha, "repo": {"full_name": head_repo}}}


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
        self.closed, self.from_branch, self.open_from, self.open_based = [], {}, {}, {}
        self.respond_closed()

    def respond_closed(self):
        self.world.respond_json("gh", CLOSED_BASED,
                                [p for p in self.closed if p["head"]["ref"] != BRANCH])  # no lander is headed by BRANCH
        self.world.respond_json("gh", OPEN_BASED, list(self.open_based.values()))
        self.world.respond_json("gh", FROM_BRANCH, list(self.from_branch.values()))
        self.world.respond_json("gh", OPEN_FROM, list(self.open_from.values()))

    def pulls(self, sha, *prs, by_commit=False):
        """Register the forge's answers for `sha` the way GitHub gives them: the commit lookup lists
        only open pull requests (a commit outside the default branch), the closed listing has the
        closed ones; `by_commit` is a merge commit into the default branch, which lists them too."""
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{sha}/pulls?per_page=100"],
                                [p for p in prs if by_commit or p["state"] == "open"])
        self.from_branch.update({p["number"]: p for p in prs if p["head"]["ref"] == BRANCH
                                 and (p["head"].get("repo") or {}).get("full_name") == SLUG})
        for p in prs:  # the open listing of the branch's own pull requests, forks included
            if p["head"]["ref"] == BRANCH and p["state"] == "open":
                self.open_from[p["number"]] = p
            else:
                self.open_from.pop(p["number"], None)
        self.based(*prs)

    def based(self, *prs):
        """Register `prs` in the open and closed listings of BRANCH only. Alone, it is what the
        forge shows of a pull request whose head is on the default branch (issue 905): the commit
        lookup of that head never lists it."""
        for p in prs:
            self.closed = [c for c in self.closed if c["number"] != p["number"]]
            self.open_based.pop(p["number"], None)
            if p["state"] != "open":
                self.closed.append(p)
            elif p["base"]["ref"] == BRANCH:
                self.open_based[p["number"]] = p
        self.respond_closed()
        for p in prs:
            self.closing(p["number"])

    def closing(self, pr, *issues):
        self.world.respond_json(
            "gh", ["api", "graphql", "-f", f"query={fm.CLOSING_ISSUES}", "-f", f"owner={OWNER}",
                   "-f", f"name={NAME}", "-F", f"number={pr}"],
            {"data": {"repository": {"pullRequest": {"closingIssuesReferences": {
                "nodes": [{"number": i} for i in issues]}}}}})

    def reads(self, argv):
        return [a for a in self.world.argvs("gh") if a == argv]

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

    def test_the_module_docstring_states_the_release_holder(self):
        doc = " ".join(land_lock.__doc__.split())
        for phrase in ("`--wait` and `--release` exist on `acquire` only",
                       "A release pull request (issue 875) is one whose head is the locked branch itself",
                       "A fork's branch of the same name is never counted",
                       "A published (merged) or closed release pull request is stale the same way",
                       "one the lookup left out, open or closed, is found in",
                       "whatever its head, never answers `moved`",
                       "with the repository's default branch as its base",
                       "With `--follow-head` a waiting release follows its pull request instead (issue 901)",
                       "`--follow-head`, which needs both (a usage error otherwise)",
                       "a `--release --wait` whose caller is bound to `--sha` (a resumed release), stop with "
                       "`no_open_pr` when the head moved",
                       "leaves the lock alone when an open pull request other than the release has its head there",
                       "(and, when that lists no such head, the open listing of D2)",
                       "attempts the lock at that pull request's current head",
                       "`no_open_pr` means no such pull request is open",
                       "adds `head_moved`, true when it took the lock at a head other than `--sha`",
                       "the caller continues with `lock_sha` as its commit",
                       "sends the D9 delete of `--sha`, exactly what `release --sha` does",
                       "The answer is `acquired` or `already_held`, never `moved`",
                       "A release holder merges only on `already_held` (ADR-claims-009)"):
            self.assertIn(phrase, doc)


    def test_the_module_docstring_states_the_default_branch_head(self):
        doc = " ".join(land_lock.__doc__.split())
        for phrase in ("For a commit on the default branch the commit lookup lists merged pull requests only "
                       "(issue 905)",
                       "When the lookup lists no pull request headed at the lock, the open pull requests based "
                       "on the branch are therefore read before the closed ones",
                       "`GET pulls?state=open&base=<branch>&sort=updated`, at most 5 pages of 100",
                       "the closed listing is read only when none is found",
                       "A fork's pull request is never taken from this listing, and an open one beyond those "
                       "pages is not seen",
                       "When the commit lookup of `--sha` lists no such pull request, the open listing of D2 is "
                       "read once for a same-repository one",
                       "so the common path makes no extra call"):
            self.assertIn(phrase, doc)
        self.assertEqual(fm.OPEN_PAGES, 5)


class SyncHolderTest(Base):
    """Issue 905: sync pull request 30 is open on BRANCH with head A, a commit on the default
    branch. The commit lookup of A lists only merged release 9, whose head was D."""

    def world_with(self, lock_sha=None, sync=None):
        self.lock(lock_sha)
        self.pulls(A, release_pull(9, state="closed", merged=True, sha=D), by_commit=True)
        self.pulls(B, pull(11, sha=B))
        self.based(sync_pull(30) if sync is None else sync)

    def wait(self, clock, sha):
        with mock.patch.object(land_lock, "monotonic", clock.monotonic), \
                mock.patch.object(land_lock, "sleep", clock.sleep):
            return run(*land("acquire", sha, "--wait"))

    def test_the_sync_pull_request_acquires_a_free_lock_in_three_calls(self):
        self.world_with()
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"]), (0, "acquired", A, 30))
        self.assertEqual(self.world.refs(), {REF: A})
        # The commit lookup, the open listing, the create.
        self.assertEqual((len(self.reads(OPEN_BASED)), len(self.world.argvs("gh"))), (1, 3))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["pr"]), (0, "already_held", 30))

    def test_the_sync_pull_request_acquires_with_wait(self):
        self.world_with()
        code, out = self.wait(FakeClock(), A)
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"], out["waited_s"]),
                         (0, "acquired", A, 30, 0))

    def test_a_waiting_sync_pull_request_takes_the_lock_a_lander_releases(self):
        self.world_with(B)
        clock = FakeClock(lambda elapsed: self.world.set_ref(REF, None) if elapsed == 240 else None)
        code, out = self.wait(clock, A)
        self.assertEqual((code, out["verdict"], out["pr"], out["waited_s"]), (0, "acquired", 30, 240))

    def test_status_and_a_lander_see_the_sync_pull_request_as_the_holder(self):
        self.world_with(A)
        self.closing(30, 7)
        self.world.comment_store(SLUG, 7, [{"id": 5, "updated_at": T0, "created_at": T0, "body": fm.render(
            "claim", {"issue": "7", "holder": OTHER}, f"Claimed by {OTHER}.")}])
        code, out = run(*land("status", B))
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"], out["by"]), (0, "held_by", A, 30, OTHER))
        code, out = run(*land("acquire", B))
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"], out["by"]), (3, "held_by", A, 30, OTHER))
        self.assertEqual(self.cas_calls(), [])
        self.assertEqual(self.world.refs(), {REF: A})
        self.assertEqual(self.reads(CLOSED_BASED), [])  # the open listing answered first

    def test_a_lander_poll_behind_the_sync_pull_request_makes_five_forge_calls(self):
        self.world_with(A)
        mine = fm.commit_pulls(SLUG, B)
        outcome = land_lock.acquire_once(SLUG, BRANCH, B, mine, lambda _: False, lambda: "R_kgDOtest")
        self.assertEqual((outcome.verdict, outcome.lock_sha, outcome.pr), ("held_by", A, 30))
        # Eligibility, create, ref read, commit lookup of the lock, open listing.
        self.assertEqual((len(self.reads(OPEN_BASED)), len(self.world.argvs("gh"))), (1, 5))

    def test_a_waiting_lander_is_held_off_then_acquires_when_the_sync_releases(self):
        self.world_with(A)

        def released(elapsed):
            if elapsed == 240:
                self.assertEqual(self.cas_calls(), [])  # two polls behind the sync, never a takeover
                self.assertEqual(run(*land("release", A))[1]["verdict"], "released")
        code, out = self.wait(FakeClock(released), B)
        self.assertEqual((code, out["verdict"], out["took_over"], out["pr"], out["waited_s"]),
                         (0, "acquired", None, 11, 240))

    def test_a_waiting_lander_that_gives_up_names_the_sync_pull_request(self):
        self.world_with(A)
        with mock.patch.object(land_lock, "IDLE_AFTER", land_lock.BOUND + 1):
            code, out = self.wait(FakeClock(), B)
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"]), (3, "land-contended", A, 30))
        self.assertEqual(self.cas_calls(), [])

    def test_the_sync_pull_request_releases_its_lock(self):
        self.world_with(A)
        code, out = run(*land("release", A))
        self.assertEqual((code, out["verdict"]), (0, "released"))
        self.assertEqual(self.world.refs(), {})
        self.world.set_ref(REF, A)
        code, out = run(*land("release", B))  # a lander's wrong release names the sync as the holder
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"]), (3, "not_held", A, 30))

    def test_a_merged_or_closed_sync_lock_is_stale_and_taken_over(self):
        for merged in (True, False):
            with self.subTest(merged=merged):
                self.world.reset()
                self.world_with(A, sync_pull(30, state="closed", merged=merged))
                code, out = run(*land("status", B))
                self.assertEqual((code, out["verdict"], out["pr"]), (0, "stale", 30))
                code, out = run(*land("acquire", B))
                self.assertEqual((code, out["verdict"], out["took_over"], out["pr"]), (0, "acquired", "closed", 11))
                self.assertEqual(self.world.refs(), {REF: B})

    def test_an_open_sync_holds_although_a_closed_one_had_the_same_head(self):
        self.world_with(A)
        self.based(sync_pull(29, state="closed"))
        code, out = run(*land("status", B))
        self.assertEqual((code, out["verdict"], out["pr"]), (0, "held_by", 30))
        code, out = run(*land("acquire", B))
        self.assertEqual((code, out["verdict"], out["pr"]), (3, "held_by", 30))
        self.assertEqual(self.cas_calls(), [])

    def test_a_fork_pull_request_with_that_head_never_takes_or_holds_the_lock(self):
        self.world_with(sync=sync_pull(30, head_repo="mallory/widgets"))
        for extra in ((), ("--wait",)):
            code, out = run(*land("acquire", A, *extra))
            self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "no_open_pr"))
        self.assertEqual(self.writes(), [])
        self.world.set_ref(REF, A)
        code, out = run(*land("status", B))
        self.assertEqual((code, out["verdict"], out["pr"]), (0, "stale", 9))
        code, out = run(*land("acquire", B))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "closed"))

    def test_a_pull_request_on_another_base_or_at_another_head_is_not_eligible(self):
        other_base = {**sync_pull(30), "base": {"ref": "other", "repo": {"full_name": SLUG}}}
        for name, pr in (("another base", other_base), ("another head", sync_pull(30, sha=C)),
                         ("closed", sync_pull(30, state="closed", merged=True))):
            with self.subTest(name):
                self.world.reset()
                self.world_with(sync=pr)
                code, out = run(*land("acquire", A))
                self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "no_open_pr"))
                self.assertEqual(self.writes(), [])

    def test_the_open_listing_is_read_only_when_the_lookup_lists_no_head(self):
        """The cost of the fallback: nothing behind a listed head, one read before the closed listing."""
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, state="closed", merged=True, sha=B), by_commit=True)
        run(*land("acquire", A))
        self.assertEqual((self.reads(OPEN_BASED), self.reads(CLOSED_BASED)), ([], []))
        self.world.reset()
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, state="closed", merged=True, sha=B))  # squash-merged: the lookup lists nothing
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "closed"))
        self.assertEqual((len(self.reads(OPEN_BASED)), len(self.reads(CLOSED_BASED)), len(self.reads(FROM_BRANCH))),
                         (1, 1, 0))

    def test_a_release_is_unaffected(self):
        """A release head is the integration tip, outside the default branch: the lookup lists it."""
        self.lock()
        self.world.respond("gh", DEFAULT_READ, stdout=DEFAULT + "\n")
        self.pulls(A, release_pull(20))
        code, out = run(*land("acquire", A, "--release"))
        self.assertEqual((code, out["verdict"], out["pr"]), (0, "acquired", 20))
        self.pulls(B, pull(11, sha=B))
        code, out = run(*land("acquire", B))
        self.assertEqual((code, out["verdict"], out["pr"]), (3, "held_by", 20))
        self.assertEqual(self.reads(OPEN_BASED), [])


class ReleaseHolderTest(Base):
    """Issue 875: a release pull request (head the locked branch, base the default branch) holds
    the lock of its head branch. A is the integration tip, 20 the release pull request."""

    def default_branch(self, name=DEFAULT):
        self.world.respond("gh", DEFAULT_READ, stdout=name + "\n")

    def test_the_release_pull_request_acquires_a_free_lock(self):
        self.lock()
        self.default_branch()
        self.pulls(A, release_pull(20), pull(11, sha=D))  # PR 11 merged the tip in
        code, out = run(*land("acquire", A, "--release"))
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"], out["took_over"]),
                         (0, "acquired", A, 20, None))
        self.assertEqual(self.world.refs(), {REF: A})
        code, out = run(*land("acquire", A, "--release"))
        self.assertEqual((code, out["verdict"], out["pr"]), (0, "already_held", 20))

    def test_a_pull_request_that_is_not_the_release_writes_nothing(self):
        rows = {"wrong base": release_pull(20, base="other"),
                "fork head": release_pull(20, head_repo="mallory/widgets"),
                "deleted fork": release_pull(20, head_repo=None),
                "head moved": release_pull(20, sha=D),
                "closed": release_pull(20, state="closed", merged=True),
                "a lander": pull(11, sha=A),
                "another head branch": {**release_pull(20), "head": {**release_pull(20)["head"], "ref": "hotfix"}}}
        for name, pr in rows.items():
            with self.subTest(name):
                self.world.reset()
                self.lock()
                self.default_branch()
                self.pulls(A, pr, by_commit=True)
                # Only a following wait follows a moved head (issue 901).
                for extra in ((), ("--wait",), ("--wait", "--follow-head"))[:2 if name == "head moved" else 3]:
                    code, out = run(*land("acquire", A, "--release", *extra))
                    self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "no_open_pr"))
                    self.assertEqual(len(self.reads(OPEN_FROM)), len(extra) // 2)
                self.assertIn("release pull request", out["detail"])
                self.assertEqual(self.writes(), [])

    def test_without_the_flag_a_release_pull_request_is_not_eligible(self):
        self.lock()
        self.pulls(A, release_pull(20))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "no_open_pr"))
        self.assertEqual(self.reads(DEFAULT_READ), [])
        self.assertEqual(self.writes(), [])

    def test_a_lander_sees_the_release_as_the_holder(self):
        self.lock(A)
        self.pulls(B, pull(11, sha=B))
        self.pulls(A, release_pull(20), pull(11, sha=B), pull(13, sha=D))  # both landers contain the tip
        code, out = run(*land("acquire", B))
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"], out["by"]), (3, "held_by", A, 20, None))
        code, out = run(*land("status", B))
        self.assertEqual((code, out["verdict"], out["pr"]), (0, "held_by", 20))
        self.assertEqual(self.cas_calls(), [])
        self.assertEqual(self.reads(DEFAULT_READ), [])
        self.assertEqual([a for a in self.world.argvs("gh") if any("state=closed" in p for p in a)], [])

    def test_the_only_lander_containing_the_tip_is_not_the_holder(self):
        self.lock(A)
        self.pulls(B, pull(11, sha=B))
        self.pulls(A, release_pull(20), pull(11, sha=B))
        code, out = run(*land("acquire", B))
        self.assertEqual((code, out["verdict"], out["pr"]), (3, "held_by", 20))
        self.assertEqual(self.world.refs(), {REF: A})

    def test_a_fork_branch_of_the_same_name_never_holds(self):
        self.lock(A)
        self.pulls(B, pull(11, sha=B))
        self.pulls(A, release_pull(20, head_repo="mallory/widgets"))
        code, out = run(*land("status", B))
        self.assertEqual((code, out["verdict"], out["pr"]), (0, "held_by", None))

    def test_a_merged_or_closed_release_is_stale_and_taken_over(self):
        for merged, by_commit in ((True, True), (True, False), (False, False)):
            with self.subTest(merged=merged, by_commit=by_commit):
                self.world.reset()
                self.lock(A)
                self.pulls(B, pull(11, sha=B))
                self.pulls(A, release_pull(20, state="closed", merged=merged), pull(13, sha=D), by_commit=by_commit)
                code, out = run(*land("status", B))
                self.assertEqual((code, out["verdict"], out["pr"]), (0, "stale", 20))
                code, out = run(*land("acquire", B))
                self.assertEqual((code, out["verdict"], out["took_over"], out["pr"]), (0, "acquired", "closed", 11))
                self.assertEqual(self.world.refs(), {REF: B})

    def test_a_published_release_lock_is_taken_over_not_moved(self):
        """D5: PR 11 is the only open pull request containing the tip, and the lock was never its own."""
        self.lock(A)
        self.pulls(B, pull(11, sha=B))
        self.pulls(A, release_pull(20, state="closed", merged=True), pull(11, sha=B), by_commit=True)
        code, out = run(*land("acquire", B))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "closed"))

    def test_a_live_release_the_commit_lookup_leaves_out_still_holds(self):
        """A is the merge commit of merged lander 9, which the lookup lists; it misses release 20."""
        self.lock(A)
        self.pulls(B, pull(11, sha=B))
        self.pulls(A, pull(9, state="closed", merged=True, sha=D), by_commit=True)
        self.from_branch[20] = release_pull(20)
        self.respond_closed()
        self.closing(20)
        code, out = run(*land("status", B))
        self.assertEqual((code, out["verdict"], out["pr"]), (0, "held_by", 20))
        code, out = run(*land("acquire", B))
        self.assertEqual((code, out["verdict"], out["pr"]), (3, "held_by", 20))
        self.assertEqual(self.cas_calls(), [])
        self.assertEqual(self.world.refs(), {REF: A})

    def test_a_lander_never_moves_a_lock_the_release_moved_past(self):
        """Lock A, release 20 now at C, lander 11 the only open lander containing A: never `moved`,
        which would let 11 merge without a resync although the branch moved."""
        self.lock(A)
        self.pulls(B, pull(11, sha=B))
        self.pulls(A, release_pull(20, sha=C), pull(11, sha=B))
        code, out = run(*land("acquire", B))
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (3, "held_by", A))
        self.assertEqual(self.cas_calls(), [])
        self.world.reset()
        self.lock(A)
        self.pulls(B, pull(11, sha=B))
        self.pulls(A, release_pull(20, state="closed", merged=True, sha=C), pull(11, sha=B), by_commit=True)
        code, out = run(*land("acquire", B))
        self.assertEqual((code, out["verdict"], out["took_over"]), (0, "acquired", "closed"))
        self.assertEqual(self.world.refs(), {REF: B})

    def test_a_release_alone_past_its_lock_takes_it_again_as_acquired(self):
        self.lock(A)
        self.default_branch()
        self.pulls(B, release_pull(20, sha=B))
        self.pulls(A, release_pull(20, sha=B))
        code, out = run(*land("acquire", B, "--release"))
        self.assertEqual((code, out["verdict"], out["took_over"], out["pr"]), (0, "acquired", "closed", 20))
        self.assertEqual(self.world.refs(), {REF: B})

    def test_a_release_whose_head_moved_does_not_move_a_lock_a_lander_contains(self):
        """The branch advanced from A to B under the release: its lock stays at A until it releases."""
        self.lock(A)
        self.default_branch()
        self.pulls(B, release_pull(20, sha=B))
        self.pulls(A, release_pull(20, sha=B), pull(13, sha=D))
        code, out = run(*land("acquire", B, "--release"))
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (3, "held_by", A))
        self.assertEqual(self.cas_calls(), [])
        code, out = run(*land("acquire", A, "--release"))
        self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "no_open_pr"))
        code, out = run(*land("release", A))
        self.assertEqual((code, out["verdict"]), (0, "released"))
        code, out = run(*land("acquire", B, "--release"))
        self.assertEqual((code, out["verdict"], out["pr"]), (0, "acquired", 20))

    def test_the_release_is_held_off_by_a_lander_and_releases_its_own_lock(self):
        self.lock(B)
        self.default_branch()
        self.pulls(A, release_pull(20))
        self.pulls(B, pull(12, sha=B))
        code, out = run(*land("acquire", A, "--release"))
        self.assertEqual((code, out["verdict"], out["pr"]), (3, "held_by", 12))
        code, out = run(*land("release", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"]), (3, "not_held", B, 12))
        self.world.set_ref(REF, A)
        code, out = run(*land("release", B))
        self.assertEqual((code, out["verdict"], out["pr"]), (3, "not_held", 20))
        code, out = run(*land("release", A))
        self.assertEqual((code, out["verdict"]), (0, "released"))
        self.assertEqual(self.world.refs(), {})

    def test_the_closed_release_listing_is_read_only_after_the_branch_listing_finds_nothing(self):
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, state="closed", merged=True, sha=B))
        run(*land("acquire", A))
        self.assertEqual(self.reads(FROM_BRANCH), [])
        self.world.reset()
        self.lock(B)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B)
        run(*land("acquire", A))
        self.assertEqual(len(self.reads(FROM_BRANCH)), 1)

    def test_classification_of_a_release_lock(self):
        release = lambda state="open", sha=A, same=True: fm.Pull(20, state, state == "closed", DEFAULT, BRANCH, sha, same)
        lander = fm.Pull(11, "open", False, BRANCH, "issue-11-x", B)
        rows = (([release(), lander], {11}, ("held", 20)),
                ([release("closed"), lander], {11}, ("closed", 20)),
                ([release("closed"), lander], (), ("closed", 20)),
                ([release("closed", same=False), lander], {11}, ("move", 11)),
                ([lander], {11}, ("move", 11)),
                ([release(sha=C), lander], {11}, ("held", 11)),
                ([release("closed", sha=C), lander], {11}, ("closed", 20)),
                ([release(sha=C)], {20}, ("closed", 20)))
        for theirs, mine, expected in rows:
            with self.subTest(theirs=theirs, mine=mine):
                self.assertEqual(land_lock._kind(A, theirs, mine, BRANCH), expected)


class ReleaseWaitTest(Base):
    def wait(self, clock, sha, *extra):
        with mock.patch.object(land_lock, "monotonic", clock.monotonic), \
                mock.patch.object(land_lock, "sleep", clock.sleep):
            return run(*land("acquire", sha, "--wait", *extra))

    def test_a_lander_takes_over_a_dead_release_only_after_45_minutes(self):
        self.lock(A)
        self.pulls(B, pull(11, sha=B))
        self.pulls(A, release_pull(20), pull(11, sha=B))
        clock = FakeClock()
        code, out = self.wait(clock, B)
        self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]), (0, "acquired", "idle", 2760))
        self.assertEqual(len(self.cas_calls()), 1)
        self.assertEqual(self.world.refs(), {REF: B})

    def test_a_waiting_lander_acquires_when_the_release_releases(self):
        self.lock(A)
        self.pulls(B, pull(11, sha=B))
        self.pulls(A, release_pull(20))
        clock = FakeClock(lambda elapsed: self.world.set_ref(REF, None) if elapsed == 240 else None)
        code, out = self.wait(clock, B)
        self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]), (0, "acquired", None, 240))

    def test_a_waiting_release_acquires_behind_a_lander_and_reads_the_default_branch_once(self):
        self.lock(B)
        self.world.respond("gh", DEFAULT_READ, stdout=DEFAULT + "\n")
        self.pulls(A, release_pull(20))
        self.pulls(B, pull(12, sha=B))
        clock = FakeClock(lambda elapsed: self.world.set_ref(REF, None) if elapsed == 240 else None)
        code, out = self.wait(clock, A, "--release")
        self.assertEqual((code, out["verdict"], out["pr"], out["waited_s"]), (0, "acquired", 20, 240))
        self.assertNotIn("head_moved", out)
        self.assertEqual(len([a for a in self.world.argvs("gh") if a == DEFAULT_READ]), 1)
        self.assertEqual(self.reads(OPEN_FROM), [])

    def test_a_following_release_whose_head_stayed_answers_head_moved_false(self):
        clock, code, out = self.release_wait(
            B, lambda elapsed: self.world.set_ref(REF, None) if elapsed == 240 else None)
        self.assertEqual((code, out["verdict"], out["pr"], out["waited_s"]), (0, "acquired", 20, 240))
        self.assertEqual((out["sha"], out["lock_sha"], out["head_moved"]), (A, A, False))
        self.assertEqual(len(self.reads(DEFAULT_READ)), 1)

    def test_a_waiting_release_without_follow_head_stops_when_its_head_moved(self):
        """A resumed release is bound to its commit: its wait must not take the lock at another
        head, which its run could neither use nor release (issue 901 review)."""
        self.lock(B)
        self.world.respond("gh", DEFAULT_READ, stdout=DEFAULT + "\n")
        self.pulls(A, release_pull(20))
        self.pulls(B, pull(12, sha=B))

        def forge(elapsed):
            self.pulls(A)
            self.pulls(C, release_pull(20, sha=C))
            self.world.set_ref(REF, None)
        clock = FakeClock(forge)
        code, out = self.wait(clock, A, "--release")
        self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "no_open_pr"))
        self.assertEqual(out["detail"], f"no open release pull request from {BRANCH} has head {A}")
        self.assertNotIn("head_moved", out)
        # One write only, the first poll's refused create behind lander 12; none after the move.
        self.assertEqual((len(self.writes()), self.reads(OPEN_FROM), self.world.refs()), (1, [], {}))
        self.assertEqual(clock.slept, [120])

    def test_follow_head_needs_release_and_wait(self):
        self.lock()
        self.pulls(A, release_pull(20), pull(11, sha=A))
        for flags in ((), ("--release",), ("--wait",)):
            with self.subTest(flags=flags):
                code, out = run(*land("acquire", A, "--follow-head", *flags))
                self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "usage"))
        for action in ("status", "release"):
            code, out = run(*land(action, A, "--follow-head"))
            self.assertEqual((code, out["error"]), (2, "usage"))
        self.assertEqual(self.world.argvs("gh"), [])

    def release_wait(self, lock, on_sleep=None):
        """Release 20 at A waits with `--sha A --follow-head`; `on_sleep(elapsed)` changes the forge."""
        self.lock(lock)
        self.world.respond("gh", DEFAULT_READ, stdout=DEFAULT + "\n")
        self.pulls(A, release_pull(20))
        self.pulls(B, pull(12, sha=B))
        clock = FakeClock(on_sleep)
        return clock, *self.wait(clock, A, "--release", "--follow-head")

    def test_a_waiting_release_follows_its_head_past_two_landers(self):
        """Issue 901: lander 12 holds the lock and merges (head A to C), lander 13 takes the lock
        and merges (head C to E); the release acquires at E, the head it never named."""
        def forge(elapsed):
            if elapsed == 120:
                self.pulls(B, pull(12, state="closed", merged=True, sha=B))
                self.pulls(C, release_pull(20, sha=C))
                self.pulls(D, pull(13, sha=D))
                self.world.set_ref(REF, D)
            if elapsed == 240:
                self.pulls(D, pull(13, state="closed", merged=True, sha=D))
                self.pulls(E, release_pull(20, sha=E))
                self.world.set_ref(REF, None)
        clock, code, out = self.release_wait(B, forge)
        self.assertEqual((code, out["verdict"], out["sha"], out["lock_sha"], out["head_moved"]),
                         (0, "acquired", A, E, True))
        self.assertEqual((out["pr"], out["took_over"], out["waited_s"]), (20, None, 240))
        self.assertEqual(self.world.refs(), {REF: E})
        self.assertEqual(self.cas_calls(), [])
        calls = self.world.argvs("gh")
        # The open listing replaces the commit lookup of --sha: 5 calls a poll behind a live
        # holder (listing, create, read, the holder's lookup, the beat read of D11), the default
        # branch once.
        self.assertEqual((len(self.reads(OPEN_FROM)), len(self.reads(DEFAULT_READ)), len(calls)), (3, 1, 13))
        self.assertEqual([a for a in calls if f"commits/{A}/pulls" in a[1]], [])

    def test_a_release_pull_request_closed_while_waiting_stops_with_no_open_pr(self):
        for closed in (release_pull(20, state="closed"), release_pull(20, state="closed", merged=True, sha=C)):
            with self.subTest(closed=closed["head"]["sha"]):
                self.world.reset()
                clock, code, out = self.release_wait(B, lambda elapsed: self.pulls(closed["head"]["sha"], closed))
                self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "no_open_pr"))
                self.assertEqual(out["detail"], f"no open release pull request from {BRANCH} into the default branch")
                self.assertNotIn("head_moved", out)
                self.assertEqual(self.cas_calls(), [])
                self.assertEqual(self.world.refs(), {REF: B})
                self.assertEqual(clock.slept, [120])

    def test_a_one_shot_release_with_a_stale_sha_never_follows(self):
        self.lock()
        self.world.respond("gh", DEFAULT_READ, stdout=DEFAULT + "\n")
        self.pulls(A)
        self.pulls(C, release_pull(20, sha=C))
        code, out = run(*land("acquire", A, "--release"))
        self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "no_open_pr"))
        self.assertEqual(out["detail"], f"no open release pull request from {BRANCH} has head {A}")
        self.assertEqual((self.reads(OPEN_FROM), self.writes()), ([], []))
        code, out = run(*land("acquire", C, "--release"))
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (0, "acquired", C))
        self.assertNotIn("head_moved", out)

    def test_a_waiting_release_releases_its_own_lock_at_the_head_it_started_from(self):
        """D5: the lock is the release's own, at A, and lander 13 contains A, so the lock reads
        held. The wait deletes it as `release --sha A` would and acquires at the head, C:
        `acquired`, never `moved`."""
        self.lock(A)
        self.world.respond("gh", DEFAULT_READ, stdout=DEFAULT + "\n")
        self.pulls(C, release_pull(20, sha=C))
        self.pulls(A, release_pull(20, sha=C), pull(13, sha=D))
        clock = FakeClock()
        code, out = self.wait(clock, A, "--release", "--follow-head")
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["head_moved"], out["took_over"]),
                         (0, "acquired", C, True, None))
        self.assertEqual((len(self.cas_calls()), clock.slept, self.world.refs()), (1, [], {REF: C}))

    def test_a_lock_at_the_starting_sha_that_another_open_pull_request_heads_is_left_alone(self):
        """Lander 14 has its head at --sha, so the lock is its own: the following release never
        deletes it and waits, here until its own idle watch passes."""
        self.lock(A)
        self.world.respond("gh", DEFAULT_READ, stdout=DEFAULT + "\n")
        self.pulls(C, release_pull(20, sha=C))
        self.pulls(A, release_pull(20, sha=C), pull(14, sha=A))
        clock = FakeClock()
        code, out = self.wait(clock, A, "--release", "--follow-head")
        self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]), (0, "acquired", "idle", 2760))
        self.assertEqual(len(self.cas_calls()), 1)  # the idle takeover only, never a delete

    def test_a_lock_at_the_starting_sha_that_an_open_sync_pull_request_heads_is_left_alone(self):
        """Issue 905: sync 30 is headed at --sha and only the open listing shows it."""
        self.lock(A)
        self.world.respond("gh", DEFAULT_READ, stdout=DEFAULT + "\n")
        self.pulls(C, release_pull(20, sha=C))
        self.pulls(A, release_pull(20, sha=C))
        self.based(sync_pull(30))
        clock = FakeClock()
        code, out = self.wait(clock, A, "--release", "--follow-head")
        self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]), (0, "acquired", "idle", 2760))
        self.assertEqual(len(self.cas_calls()), 1)  # the idle takeover only, never a delete

    def test_a_waiting_release_never_deletes_a_lock_at_another_sha(self):
        """The lock of live lander 12 is not at --sha: the moved release only waits behind it."""
        clock, code, out = self.release_wait(
            B, lambda elapsed: self.pulls(C, release_pull(20, sha=C)) if elapsed == 120 else None)
        self.assertEqual((code, out["verdict"], out["took_over"], out["lock_sha"], out["head_moved"]),
                         (0, "acquired", "idle", C, True))
        self.assertEqual((out["waited_s"], len(self.cas_calls()), self.world.refs()), (2760, 1, {REF: C}))

    def test_a_lost_race_after_the_own_lock_delete_waits_behind_the_winner(self):
        """Release-then-acquire is not atomic: lander 13 takes the freed lock and the release
        waits behind it like any waiter."""
        self.lock(A)
        self.world.respond("gh", DEFAULT_READ, stdout=DEFAULT + "\n")
        self.pulls(C, release_pull(20, sha=C))
        self.pulls(A, release_pull(20, sha=C), pull(13, sha=D))
        self.pulls(D, pull(13, sha=D))
        cas = fm.cas_ref

        def racing(slug, node, ref, before, after):
            failure = cas(slug, node, ref, before, after)
            self.world.set_ref(REF, D)
            return failure
        clock = FakeClock(lambda elapsed: self.world.set_ref(REF, None) if elapsed == 120 else None)
        with mock.patch.object(fm, "cas_ref", racing):
            code, out = self.wait(clock, A, "--release", "--follow-head")
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["waited_s"]), (0, "acquired", C, 120))
        self.assertEqual(len(self.cas_calls()), 1)

    def test_a_lander_wait_has_no_head_moved_member(self):
        self.lock()
        self.pulls(B, pull(11, sha=B))
        code, out = self.wait(FakeClock(), B)
        self.assertEqual((code, out["verdict"]), (0, "acquired"))
        self.assertNotIn("head_moved", out)
        self.assertEqual(self.reads(OPEN_FROM), [])

    def test_a_waiting_lander_behind_a_live_holder_makes_five_forge_calls_a_poll(self):
        """Through `--wait` and its own eligibility read: the open listing of issue 905 is never
        read while the commit lookup lists the caller's pull request. The fifth call is the beat
        read (D11, issue 971), which only a waiter makes."""
        self.lock(A)
        self.pulls(B, pull(11, sha=B))
        self.pulls(A, pull(12, sha=A))
        clock = FakeClock(lambda elapsed: self.world.set_ref(REF, None) if elapsed == 240 else None)
        code, out = self.wait(clock, B)
        self.assertEqual((code, out["verdict"], out["waited_s"]), (0, "acquired", 240))
        # Two polls behind the holder (eligibility, create, ref read, lookup of the lock, beat
        # read), then eligibility and the create that takes the released lock.
        self.assertEqual((len(self.world.argvs("gh")), self.reads(OPEN_BASED)), (5 + 5 + 2, []))
        self.assertEqual(len(self.reads(BEAT_READ)), 2)

    def test_a_lander_poll_behind_a_live_holder_makes_four_forge_calls(self):
        """The waiter's cost per poll is the same behind a lander and behind a release."""
        for holder in (pull(12, sha=A), release_pull(20)):
            with self.subTest(holder=holder["number"]):
                self.world.reset()
                self.lock(A)
                self.pulls(B, pull(11, sha=B))
                self.pulls(A, holder)
                land_lock.acquire_once(SLUG, BRANCH, B, [p for p in fm.commit_pulls(SLUG, B)],
                                       lambda _: False, lambda: "R_kgDOtest")
                self.assertEqual(len(self.world.argvs("gh")), 4)
                self.assertEqual(self.reads(OPEN_BASED), [])  # issue 905: no fallback on this path


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
                         (3, "land-contended", 3000, C, 12))
        self.assertEqual(clock.slept, [120] * 25)
        self.assertEqual(len(self.attempts()), 26)
        self.assertEqual(self.cas_calls(), [])
        self.assertEqual(self.world.refs(), {REF: C})

    def test_a_wait_ends_by_itself_inside_a_sixty_minute_bash_call(self):
        """Issue 941: the wait answers land-contended with ten minutes to spare, and can still complete an idle watch."""
        self.assertEqual(land_lock.BOUND, 3000)
        self.assertLessEqual(land_lock.BOUND + 5 * land_lock.POLL, 3600)
        self.assertGreaterEqual(land_lock.BOUND, land_lock.IDLE_AFTER + 2 * land_lock.POLL)

    def test_a_wait_reports_the_pull_requests_it_waited_on(self):
        """Issue 913: the holders seen while polling, in order, whether the wait succeeds or gives up."""
        def handover(elapsed):
            if elapsed == 240:
                self.world.set_ref(REF, C)  # PR 12 moves its lock to its new head
                self.pulls(D, pull(13, sha=D))
            if elapsed == 480:
                self.world.set_ref(REF, D)  # PR 13 takes it next
            if elapsed == 720:
                self.world.set_ref(REF, None)
        code, out = self.wait(FakeClock(handover))
        self.assertEqual((code, out["verdict"], out["waited_s"], out["waited_on"]), (0, "acquired", 720, [12, 13]))
        self.world.reset()
        self.prepare(B)
        code, out = self.wait(FakeClock(self.move_once(2400, C)))
        self.assertEqual((code, out["verdict"], out["waited_on"]), (3, "land-contended", [12]))

    def test_a_wait_that_was_never_held_off_waited_on_nobody(self):
        self.world.reset()
        self.prepare(None)
        code, out = self.wait(FakeClock())
        self.assertEqual((code, out["verdict"], out["waited_s"], out["waited_on"]), (0, "acquired", 0, []))
        code, out = run(*land("acquire", A))  # a one-shot acquire never waits and carries no such key
        self.assertEqual((out["verdict"], "waited_on" in out), ("already_held", False))

    def test_waiter_takes_over_only_after_its_own_45_minute_watch(self):
        clock = FakeClock()
        with host_clock(datetime(2100, 1, 1, tzinfo=timezone.utc), fm, forge_claim):
            code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]), (0, "acquired", "idle", 2760))
        self.assertEqual(len(self.attempts()), 24)  # 0 .. 2640 held_by (< 2700), 2760 takes over
        self.assertEqual(len(self.cas_calls()), 1)
        self.assertEqual(self.world.refs(), {REF: A})

    def test_a_moved_oid_restarts_the_watch(self):
        clock = FakeClock(self.move_once(120, C))
        code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]), (0, "acquired", "idle", 2880))
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
        # The failed polls delay the watch, so the takeover is set early enough to fit the wait's bound.
        with mock.patch.object(fm, "create_ref", flaky), mock.patch.object(land_lock, "IDLE_AFTER", 1800):
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
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["waited_s"]), (3, "land-contended", B, 3000))
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
        self.assertEqual(self.cas_calls(), [])  # B's watch restarted at 1200: 3900 > 3000

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

    def test_release_is_only_an_acquire_flag(self):
        for action in ("status", "release"):
            code, out = run(*land(action, A, "--release"))
            self.assertEqual((code, out["error"]), (2, "usage"))
        parse = forge_claim.build_parser().parse_args
        self.assertEqual([parse(land("acquire", A, *flags)).release for flags in ((), ("--release",),
                          ("--release", "--wait"))], [False, True, True])
        self.assertTrue(parse(land("acquire", A, "--wait", "--release")).wait)


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


class RefreshTest(Base):
    """Issue 971, D11: a holder whose lock stays at one sha refreshes it through the beat ref,
    and a waiter's idle watch restarts at every refresh it sees. The lock is at B, held by pull
    request 12; the waiter is pull request 11 at A."""
    prepare, wait = WaitTest.prepare, WaitTest.wait

    def setUp(self):
        super().setUp()
        self.prepare(B)

    def parents(self, *chain):
        """Register the history `chain[0]` -> `chain[1]` -> ...; the last commit is a root."""
        for sha, parent in zip(chain, (*chain[1:], None)):
            self.world.respond_json("gh", ["api", f"repos/{SLUG}/git/commits/{sha}"],
                                    {"sha": sha, "parents": [{"sha": parent}] if parent else []})

    def holder_every(self, seconds, *argv):
        """A holder that runs `argv` every `seconds` of the waiter's wait; its answers are kept."""
        self.answers = []

        def on_sleep(elapsed):
            if elapsed % seconds == 0:
                self.answers.append(run(*argv))
        return FakeClock(on_sleep)

    def test_refresh_moves_the_beat_one_step_and_never_brings_a_value_back(self):
        self.parents(B, C, D)
        seen = []
        for expected in (B, C, D, None):
            code, out = run(*land("refresh", B))
            self.assertEqual((code, out["verdict"], out["lock_sha"], out["beat"]), (0, "refreshed", B, expected))
            self.assertEqual(self.world.refs(), {REF: B, **({BEAT: expected} if expected else {})})
            seen.append(expected)
        # No two refreshes in a row, and no refresh after the next, show a waiter the same beat.
        self.assertEqual(len(set(seen)), len(seen))
        self.assertEqual([[a[-3], a[-1]] for a in self.cas_calls()],
                         [[f"before={B}", f"after={C}"], [f"before={C}", f"after={D}"], [f"before={D}", f"after={fm.ZERO_OID}"]])

    def test_refresh_writes_nothing_unless_the_lock_is_at_the_callers_sha(self):
        code, out = run(*land("refresh", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"], out["pr"]), (3, "not_held", B, 12))
        self.assertEqual((self.writes(), self.world.refs()), ([], {REF: B}))
        self.world.reset()
        self.prepare(None)
        code, out = run(*land("refresh", A))
        self.assertEqual((code, out["verdict"], out["lock_sha"]), (3, "not_held", None))
        self.assertEqual((self.writes(), self.world.refs()), ([], {}))

    def test_an_unapplied_beat_swap_is_a_forge_error(self):
        self.parents(B, C)
        self.world.set_ref(BEAT, B)
        with mock.patch.object(fm, "cas_ref", lambda *args: fm.ForgeError("gh_failed", "x")):
            code, out = run(*land("refresh", B))
        self.assertEqual((code, out["verdict"], out["error"]), (1, "error", "gh_failed"))
        self.assertEqual(self.world.refs(), {REF: B, BEAT: B})

    def test_a_lock_refreshed_every_eight_minutes_is_never_taken_over_as_idle(self):
        """The train's checks wait: a refresh at the start of each 8-minute round, for a whole wait
        of the waiter, 50 minutes, which is longer than the train's 40 plus 6."""
        self.parents(B, C, D, E, A)
        clock = self.holder_every(480, *land("refresh", B))
        code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["waited_s"], out["lock_sha"], out["pr"]),
                         (3, "land-contended", 3000, B, 12))
        self.assertEqual([(c, o["verdict"]) for c, o in self.answers], [(0, "refreshed")] * 6)
        self.assertEqual(self.world.refs()[REF], B)
        self.assertEqual([a for a in self.cas_calls() if f"name={REF}" in a], [])

    def test_an_acquire_at_the_same_sha_refreshes_nothing(self):
        """What the train could do before D11: `already_held` writes nothing, so the waiter takes
        the lock over 45 minutes after it first saw it, whatever the holder re-asserted."""
        clock = self.holder_every(480, *land("acquire", B))
        code, out = self.wait(clock)
        self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]), (0, "acquired", "idle", 2760))
        self.assertEqual([(c, o["verdict"]) for c, o in self.answers], [(0, "already_held")] * 5)
        self.assertEqual(self.world.refs(), {REF: A})

    def test_the_idle_watch_counts_from_the_last_refresh_seen(self):
        clock = FakeClock(lambda elapsed: run(*land("refresh", B)) if elapsed == 480 else None)
        with mock.patch.object(land_lock, "IDLE_AFTER", 1200):
            code, out = self.wait(clock)
        # Unrefreshed the takeover is the poll at 1200; the refresh the poll at 480 saw moves it to 480 + 1200.
        self.assertEqual((code, out["verdict"], out["took_over"], out["waited_s"]), (0, "acquired", "idle", 1680))

    def test_the_docstring_states_the_refresh(self):
        doc = " ".join(land_lock.__doc__.split())
        for phrase in ("`forge-claim land acquire|release|status|refresh`",
                       "A one-shot `acquire` at the lock's own sha answers `already_held` and changes nothing, "
                       "so it restarts no watch",
                       "the beat `refs/agent-locks/land-beat/<branch>`",
                       "writes nothing unless the lock is at `--sha`",
                       "A waiter reads the beat in every poll that finds the lock held",
                       "restarts its watch exactly as a changed lock does",
                       "No clock is read (D3)"):
            self.assertIn(phrase, doc)


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
