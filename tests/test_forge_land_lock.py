"""forge-claim land (issue 629): the cross-host land lock against the fake gh and its ref store."""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock
from datetime import datetime, timezone

from agent_tools import forge_claim
from agent_tools import forge_land_lock as land_lock
from agent_tools import forge_markers as fm
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
    return subprocess.Popen([sys.executable, "-m", "agent_tools.forge_claim", *argv], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=dict(os.environ))


def finish(proc):
    stdout, _ = proc.communicate(timeout=120)
    lines = stdout.splitlines()
    assert len(lines) == 1, stdout
    return proc.returncode, json.loads(lines[0])


class Base(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)

    def lock(self, sha=None, **kwargs):
        self.world.ref_store(SLUG, {REF: sha} if sha else {}, **kwargs)

    def pulls(self, sha, *prs):
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{sha}/pulls?per_page=100"], list(prs))
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

    def test_a_lying_cas_is_classified_by_the_re_read(self):
        self.lock(B, cas_lies=1)
        self.pulls(A, pull(11, sha=A))
        self.pulls(B, pull(12, state="closed", merged=True, sha=B))
        code, out = run(*land("acquire", A))
        self.assertEqual((code, out["verdict"]), (0, "acquired"))

    def test_a_failed_cas_on_an_unchanged_lock_is_a_forge_error(self):
        for failure in ("gh_failed", "gh_timeout"):
            with self.subTest(failure=failure):
                self.world.reset()
                self.lock(B)
                self.pulls(A, pull(11, sha=A))
                self.pulls(B, pull(12, state="closed", merged=True, sha=B))
                with mock.patch.object(fm, "cas_ref", lambda *args, f=failure: f):
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
                with mock.patch.object(fm, "cas_ref", lambda *args, f=failure: f):
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


class ConcurrencyTest(Base):
    """Children of `python -m agent_tools.forge_claim land` racing on one ref store."""

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
