"""The post-release sync of a two-branch release (issue 845), through the real driver and forge.

After `github-release` is satisfied the driver pushes a disposable sync branch at the release
merge commit and opens one pull request from it into the integration branch. The sync is its own
outcome in the run result: it never parks, fails or rolls back the published release.
"""
import unittest
from unittest import mock

from agent_tools.release import forge_adapter, release_driver, release_sync
from . import release_driver_support as rs
from . import release_test_support as support
from .forge_world import CANONICAL, ROWS, SYNC, SYNC_ROWS, SYNC_URL, ForgeWorld, sync_pull

MERGED = CANONICAL["merge_commit"]
PUSH = SYNC_ROWS["sync_branch.push"]["argv"][1:]
CREATE = SYNC_ROWS["sync_pr.create"]["argv"][1:]
BRANCH = ["branch", "--no-track", SYNC["branch"], MERGED]
DONE = {"status": "done", "branch": SYNC["branch"], "pr": SYNC["pr"], "url": SYNC_URL,
        "reason": None, "manual": []}
MANUAL = [f"git branch --no-track {SYNC['branch']} {MERGED}",
          SYNC_ROWS["sync_branch.push"]["raw"], SYNC_ROWS["sync_pr.create"]["raw"]]


class Unreachable(rs.StatefulForge):
    """A forge whose sync operations raise: the sync code itself fails."""

    def inspect(self, request):
        if request.get("operation") in forge_adapter.SYNC_OPERATIONS:
            raise OSError("the network is gone")
        return super().inspect(request)


class DeniedAfterRelease(rs.StatefulForge):
    """A forge whose guard refuses every command once the GitHub Release exists."""

    def land(self, request):
        super().land(request)
        if request["operation"] == "release":
            self.world.respond("claude-bash-lifecycle-guard", [], exit=2,
                               stderr="lifecycle guard: refused")


class LookupDown(rs.StatefulForge):
    """A forge whose first `failures` readings of the sync pull request listing fail (HTTP 502)."""

    def __init__(self, world, failures):
        super().__init__(world)
        self.failures = failures

    def inspect(self, request):
        if request.get("operation") != "sync_pr" or not self.failures:
            return super().inspect(request)
        self.failures -= 1
        listing = SYNC_ROWS["sync_pr.list"]["argv"][1:]
        self.world.respond("gh", listing, exit=1, stderr="gh: Bad Gateway (HTTP 502)")
        try:
            return super().inspect(request)
        finally:
            self.world.respond_json("gh", listing, [])


class SyncCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(release_sync, "time")
        self.time = patcher.start()
        self.addCleanup(patcher.stop)
        self.world = ForgeWorld(self)
        self.world.verification_ready(integration="dev")
        self.world.merge_observation_ready()
        self.clock = rs.Clock()
        self.forge = rs.StatefulForge(self.world)
        self.world.merge_ready()
        self.world.sync_ready()
        self.world.land_lock_ready()

    def driver(self, forge=None, **project):
        project = rs.project(self, **{"profiles": {"two-branch": support.merge_profile()},
                                      "integration": "dev", **project})
        return release_driver.Driver(project, registry={"github-forge": forge or self.forge},
                                     clock=self.clock)

    def argvs(self, tool, head):
        return [c["argv"] for c in self.world.calls() if c["tool"] == tool and c["argv"][:len(head)] == head]

    def mutations(self):
        """Every provider mutation, in order, by its first two words."""
        words = (("gh", ["pr", "merge"]), ("git", ["push", "origin"]), ("gh", ["release", "create"]),
                 ("gh", ["pr", "create"]))
        return [(c["tool"], *c["argv"][:2]) for c in self.world.calls()
                if (c["tool"], c["argv"][:2]) in words]

    def assertPublished(self, driver, result):
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        release = driver.status()["release"]
        self.assertEqual((release["state"], release["reason"]), ("succeeded", None))
        self.assertIsNotNone(release["receipt"])
        self.assertEqual([a["status"] for a in release["actions"]], ["satisfied"] * 3)


class SyncRunTest(SyncCase):
    def test_a_release_pushes_the_sync_branch_and_opens_one_pull_request_after_the_release(self):
        driver = self.driver()
        shown, result = rs.release(driver, rs.candidate())
        self.assertEqual([c["action"] for c in shown["confirmations"]], ["merge", "tag", "github-release"])
        self.assertPublished(driver, result)
        self.assertEqual(result["sync"], DONE)
        self.assertEqual(self.mutations(), [("gh", "pr", "merge"), ("git", "push", "origin"),
                                            ("gh", "release", "create"), ("git", "push", "origin"),
                                            ("gh", "pr", "create")])
        self.assertEqual(self.argvs("git", ["push"]), [ROWS["tag.push"]["argv"][1:], PUSH])
        self.assertEqual((self.argvs("git", ["branch"]), self.argvs("gh", ["pr", "create"])),
                         ([BRANCH], [CREATE]))
        self.assertEqual(len(self.argvs("gh", ["pr", "merge"])), 1)  # the release PR, never the sync PR
        self.assertEqual([a["name"] for a in result["actions"]], ["merge", "tag", "github-release"])

    def test_an_integration_branch_that_already_holds_the_merge_commit_is_a_no_op(self):
        self.world.sync_ready(contained="identical")
        driver = self.driver()
        _, result = rs.release(driver, rs.candidate())
        self.assertPublished(driver, result)
        self.assertEqual(result["sync"], {**DONE, "status": "noop", "pr": None, "url": None})
        self.assertEqual(self.mutations()[3:], [])
        self.assertEqual(self.argvs("git", ["branch"]), [])

    def test_a_branch_pushed_without_its_pull_request_is_finished_by_a_rerun(self):
        self.world.sync_ready(create_exit=1, create_stdout="", create_stderr="gh: connection reset")
        driver = self.driver()
        _, result = rs.release(driver, rs.candidate())
        self.assertPublished(driver, result)
        sync = result["sync"]
        self.assertEqual((sync["status"], sync["pr"], sync["manual"]), ("failed", None, MANUAL[2:]))
        self.assertEqual(sync["reason"],
                         "sync_pr: absent pr_absent after unknown transient_transport: gh pr: gh: connection reset")
        self.world.sync_ready(branch_tip=MERGED)
        rerun = driver.run(None, [])
        self.assertPublished(driver, rerun)
        self.assertEqual((rerun["sync"], rerun["transaction_id"], rerun["receipt_digest"]),
                         (DONE, result["transaction_id"], result["receipt_digest"]))
        self.assertEqual((self.argvs("git", ["push"])[1:], len(self.argvs("gh", ["pr", "create"]))),
                         ([PUSH], 2))
        self.assertEqual(len(driver.transactions()), 1)

    def test_a_local_branch_whose_push_failed_is_pushed_by_a_rerun(self):
        self.world.sync_ready(push_exit=1, push_stderr="fatal: unable to access")
        driver = self.driver()
        _, result = rs.release(driver, rs.candidate())
        self.assertPublished(driver, result)
        sync = result["sync"]
        self.assertEqual((sync["status"], sync["manual"]), ("failed", MANUAL))
        self.assertTrue(sync["reason"].startswith(
            "sync_branch: absent branch_absent after unknown transient_transport: "), sync["reason"])
        self.assertEqual(self.argvs("gh", ["pr", "create"]), [])
        self.world.sync_ready(local_branch=MERGED)
        rerun = driver.run(None, [])
        self.assertEqual(rerun["sync"], DONE)
        self.assertEqual((self.argvs("git", ["branch"]), self.argvs("git", ["push"])[1:]),
                         ([BRANCH], [PUSH, PUSH]))

    def test_a_finished_sync_is_read_again_and_mutates_nothing(self):
        driver = self.driver()
        rs.release(driver, rs.candidate())
        before = self.mutations()
        rerun = driver.run(None, [])
        self.assertEqual((rerun["state"], rerun["next"], rerun["sync"], rerun["legacy"]),
                         ("succeeded", "done", DONE, None))
        self.assertEqual(self.mutations(), before)
        refusal = None
        try:
            driver.run(None, ["tag:000000000000"])
        except release_driver.Refusal as caught:
            refusal = caught.code
        self.assertEqual(refusal, "confirmation_stale")


class SyncLookupTest(SyncCase):
    """Issue 998: one failed lookup is read again, and a run that still fails is finished by the
    next one, which opens the pull request or finds the one opened by hand."""

    LOOKUP_FAILED = "sync_pr: unknown lookup_failed (gh: Bad Gateway (HTTP 502))"

    def lookups(self):
        return len(self.argvs("gh", SYNC_ROWS["sync_pr.list"]["argv"][1:]))

    def test_one_failed_lookup_is_read_again_and_the_same_run_opens_the_pull_request(self):
        driver = self.driver(forge=LookupDown(self.world, 1))
        _, result = rs.release(driver, rs.candidate())
        self.assertPublished(driver, result)
        self.assertEqual(result["sync"], DONE)
        self.assertEqual(self.argvs("gh", ["pr", "create"]), [CREATE])
        self.assertEqual(self.lookups(), 3)  # failed, read again, and once after the create
        self.assertEqual(self.time.sleep.call_args_list,
                         [mock.call(release_sync.RETRY_PAUSE_SECONDS)])

    def failed_after_the_push(self):
        """A release whose sync branch is pushed and whose pull request lookup failed twice."""
        self.world.sync_ready(branch_tip=MERGED)
        forge = LookupDown(self.world, 2)
        driver = self.driver(forge=forge)
        _, result = rs.release(driver, rs.candidate())
        self.assertPublished(driver, result)
        self.assertEqual(result["sync"], {
            "status": "failed", "branch": SYNC["branch"], "pr": None, "url": None,
            "reason": self.LOOKUP_FAILED, "manual": MANUAL[2:]})
        self.assertEqual((self.lookups(), forge.failures, self.argvs("gh", ["pr", "create"])),
                         (2, 0, []))  # read twice, never a third time, and nothing opened blind
        return driver, result

    def test_a_rerun_after_a_failed_lookup_with_the_branch_pushed_opens_the_pull_request(self):
        driver, result = self.failed_after_the_push()
        rerun = driver.run(None, [])
        self.assertPublished(driver, rerun)
        self.assertEqual((rerun["sync"], rerun["transaction_id"]), (DONE, result["transaction_id"]))
        self.assertEqual(self.argvs("gh", ["pr", "create"]), [CREATE])
        self.assertEqual(self.argvs("git", ["push"])[1:], [])  # the pushed branch is not pushed again

    def test_a_rerun_after_a_failed_lookup_finds_the_pull_request_opened_by_hand(self):
        driver, _ = self.failed_after_the_push()
        self.world.sync_ready(branch_tip=MERGED, prs=[sync_pull()])
        rerun = driver.run(None, [])
        self.assertEqual(rerun["sync"], DONE)
        self.assertEqual(self.argvs("gh", ["pr", "create"]), [])

    def test_a_lookup_that_is_not_transient_is_not_read_again(self):
        self.world.sync_ready(branch_tip=MERGED)
        self.world.respond("gh", SYNC_ROWS["sync_pr.list"]["argv"][1:], stdout="not json")
        driver = self.driver()
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["sync"]["status"], result["sync"]["reason"]),
                         ("failed", "sync_pr: unknown payload_invalid"))
        self.assertEqual((self.lookups(), self.time.sleep.call_args_list), (1, []))


class SyncFailureTest(SyncCase):
    def test_a_failed_sync_leaves_the_release_published_and_reports_itself(self):
        for forge, ready, reason, manual in (
                (None, dict(branch_tip="7" * 40, branch_compare="diverged"),
                 "sync_branch: diverged branch_elsewhere", MANUAL),
                (None, dict(branch_exit=1), "sync_branch: absent branch_absent after rejected "
                                            "provider_unavailable: git branch: failed", MANUAL),
                (Unreachable, {}, "sync_branch: OSError: the network is gone", [])):
            with self.subTest(reason=reason):
                self.setUp()
                self.world.sync_ready(**ready)
                driver = self.driver(forge=forge(self.world) if forge else None)
                _, result = rs.release(driver, rs.candidate())
                self.assertPublished(driver, result)
                self.assertEqual(result["sync"], {"status": "failed", "branch": SYNC["branch"], "pr": None,
                                                  "url": None, "reason": reason, "manual": manual})
                self.assertEqual(self.argvs("gh", ["pr", "create"]), [])

    def test_a_guard_denial_of_the_sync_push_is_reported_not_parked(self):
        driver = self.driver(forge=DeniedAfterRelease(self.world))
        _, result = rs.release(driver, rs.candidate())
        self.assertPublished(driver, result)
        self.assertEqual(result["sync"]["status"], "failed")
        self.assertIn("authorization_denied: guard: lifecycle guard: refused", result["sync"]["reason"])
        self.assertEqual(self.mutations()[3:], [])

    def test_no_sync_runs_before_publication_is_satisfied(self):
        self.world.merge_ready(merge_exit=1, merge_stderr="GraphQL: Head branch is out of date")
        driver = self.driver()
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"], result["sync"]),
                         ("attention_required", "attention", None))
        self.assertNotIn(SYNC_ROWS["sync.contained"]["argv"][1:], self.argvs("gh", ["api"]))
        self.assertNotIn(ROWS["pr_merge.merge_commit"]["argv"][1:], self.argvs("gh", ["api"]))


class SingleBranchUnchangedTest(SyncCase):
    """A profile whose integration branch is its default branch has no sync: its actions,
    confirmations and documents are what they were."""

    def setUp(self):
        self.world = ForgeWorld(self)
        self.world.verification_ready()
        self.clock = rs.Clock()
        self.forge = rs.StatefulForge(self.world)

    def single(self):
        return release_driver.Driver(rs.project(self), registry={"github-forge": self.forge},
                                     clock=self.clock)

    def test_the_documents_carry_no_sync_and_a_finished_release_still_needs_a_candidate(self):
        driver = self.single()
        shown, result = rs.release(driver, rs.candidate())
        self.assertEqual(sorted(shown), ["actions", "candidate", "confirmations", "mode", "plan_digest",
                                         "profile", "refusal", "runnable", "schema_version", "verification"])
        self.assertEqual([c["action"] for c in shown["confirmations"]], ["tag", "github-release"])
        self.assertEqual(sorted(result), ["actions", "legacy", "next", "receipt_digest", "schema_version",
                                          "state", "transaction_id"])
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual(self.mutations(), [("git", "push", "origin"), ("gh", "release", "create")])
        calls = len(self.world.calls())
        with self.assertRaises(release_driver.Refusal) as caught:
            driver.run(None, [])
        self.assertEqual((caught.exception.code, len(self.world.calls())), ("candidate_required", calls))

    def test_tokens_do_not_depend_on_the_sync(self):
        """The plan digest covers the profile digest, which covers the forge descriptor: the
        sync operations are not in it, so a single-branch token is what it was."""
        driver = self.single()
        shown = driver.preview(rs.candidate())
        descriptor = forge_adapter.describe()
        self.assertEqual(sorted(descriptor["operations"]), ["pr_merge", "release", "tag"])
        self.assertEqual([entry["token"] for entry in shown["confirmations"]],
                         [release_driver.token(shown["plan_digest"], name, 1, 1)
                          for name in ("tag", "github-release")])
        self.assertIsNone(release_sync.binding(driver.compiled, driver.project))


if __name__ == "__main__":
    unittest.main()
