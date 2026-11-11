"""The integration land lock of a two-branch release (issue 875), through the real driver, the
real forge adapter and the real `forge_land_lock` against the fake gh and its ref store.

The caller acquires the lock before the first preview; `run` re-checks it right before it may
merge, proceeds only on `already_held`, and releases it on every ending but a `confirm` or
`wait` that can still merge.
"""
import unittest
from unittest import mock

from agent_tools.claims import forge_markers as fm
from agent_tools.release import release_driver, release_lock
from . import release_driver_support as rs
from . import release_test_support as support
from .forge_world import CANONICAL, LAND_LOCK, SYNC_ROWS, ForgeWorld

SLUG, COMMIT = CANONICAL["slug"], CANONICAL["commit"]
REF = LAND_LOCK.format(branch="dev")
OTHER = "b" * 40
HELD = {"verdict": "already_held", "lock_sha": COMMIT, "detail": None}
RELEASED = {"verdict": "released", "lock_sha": None, "detail": None}


class MergeInProgress(rs.StatefulForge):
    """A forge whose merge is seen under way: the release waits before it has merged."""

    def inspect(self, request):
        observed = super().inspect(request)
        if request.get("kind") == "effect" and request.get("operation") == "pr_merge":
            observed = {**observed, "outcome": "in_progress"}
        return observed


class LockCase(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        self.world.verification_ready(integration="dev")
        self.world.merge_observation_ready()
        self.clock = rs.Clock()
        self.forge = rs.StatefulForge(self.world)
        self.world.merge_ready()
        self.world.sync_ready()
        self.world.land_lock_ready()

    def driver(self, forge=None):
        project = rs.project(self, profiles={"two-branch": support.merge_profile()},
                             integration="dev")
        return release_driver.Driver(project, registry={"github-forge": forge or self.forge},
                                     clock=self.clock)

    def index(self, matches):
        return next(i for i, call in enumerate(self.world.calls()) if matches(call["argv"]))

    def swaps(self):
        return [c["argv"] for c in self.world.calls()
                if c["argv"][:2] == ["api", "graphql"] and "updateRefs(" in c["argv"][3]]

    def merges(self):
        return [c for c in self.world.calls() if c["argv"][:2] == ["pr", "merge"]]

    def lock_reads(self):
        return [c for c in self.world.calls() if "agent-locks" in " ".join(c["argv"])]

    def refused(self, code, driver):
        shown = driver.preview(rs.candidate())
        self.assertTrue(shown["runnable"])
        with self.assertRaises(release_driver.Refusal) as caught:
            driver.run(rs.candidate(), [c["token"] for c in shown["confirmations"]])
        self.assertEqual(caught.exception.code, code)
        self.assertFalse((driver.project.common_dir / "agent-release").exists())
        self.assertEqual(self.merges(), [])
        return caught.exception.detail


class HeldLockTest(LockCase):
    def test_a_held_lock_lets_the_release_merge_and_is_released_before_the_sync(self):
        driver = self.driver()
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual((result["lock"], self.world.refs()), (RELEASED, {}))
        self.assertEqual(result["sync"]["status"], "done")
        merge = self.index(lambda argv: argv[:2] == ["pr", "merge"])
        release = self.index(lambda argv: argv[:2] == ["api", "graphql"] and "updateRefs(" in argv[3])
        sync = self.index(lambda argv: argv == SYNC_ROWS["sync.contained"]["argv"][1:])
        self.assertLess(merge, release)
        self.assertLess(release, sync)
        self.assertIn("--match-head-commit", self.merges()[0]["argv"])
        rerun = driver.run(None, [])
        self.assertEqual((rerun["next"], rerun["lock"]), ("done", None))
        self.assertEqual(len(self.swaps()), 1)

    def test_preview_never_touches_the_lock(self):
        self.driver().preview(rs.candidate())
        self.assertEqual(self.lock_reads(), [])
        self.assertEqual(self.world.refs(), {REF: COMMIT})

    def test_a_release_that_waits_before_its_merge_keeps_the_lock(self):
        _, result = rs.release(self.driver(MergeInProgress(self.world)), rs.candidate())
        self.assertEqual((result["next"], result["lock"], result["sync"]), ("wait", HELD, None))
        self.assertEqual((self.world.refs(), self.swaps()), ({REF: COMMIT}, []))

    def test_a_release_parked_before_its_merge_releases_the_lock(self):
        self.world.merge_ready(merge_exit=1, merge_stderr="GraphQL: Head branch is out of date")
        _, result = rs.release(self.driver(), rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
        self.assertEqual((result["lock"], result["sync"], self.world.refs()), (RELEASED, None, {}))

    def test_abandon_releases_the_lock(self):
        driver = self.driver()
        rs.seed(driver, merge=support.MERGE)
        result = driver.abandon()
        self.assertEqual((result["state"], result["lock"], self.world.refs()),
                         ("abandoned", RELEASED, {}))

    def crashed(self, operation):
        """A release whose run died right after `operation` took effect, ready to resume."""
        driver = self.driver(rs.CrashAt(self.forge, operation, after=True))
        shown = driver.preview(rs.candidate())
        with self.assertRaises(rs.Crash):
            driver.run(rs.candidate(), [c["token"] for c in shown["confirmations"]])
        self.assertEqual(self.world.refs(), {REF: COMMIT})  # a raised effect releases nothing
        self.clock.advance(release_driver.CUSTODY_TTL_MS + 1)
        return driver, [c["token"] for c in driver.preview(None)["confirmations"]]

    def test_a_resume_that_finds_the_merge_done_releases_without_checking(self):
        driver, tokens = self.crashed("pr_merge")
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{COMMIT}/pulls?per_page=100"], [])
        result = driver.run(None, tokens)
        self.assertEqual((result["next"], result["lock"], self.world.refs()), ("done", RELEASED, {}))

    def test_a_run_that_starts_after_the_merge_makes_no_lock_call(self):
        driver, tokens = self.crashed("tag")
        before = len(self.lock_reads())
        result = driver.run(None, tokens)
        self.assertEqual((result["next"], result["lock"]), ("done", None))
        self.assertEqual((len(self.lock_reads()), self.swaps()), (before, []))
        self.assertEqual(self.world.refs(), {REF: COMMIT})  # stale: its pull request is merged

    def test_a_resumed_release_checks_the_lock_before_it_invokes_the_merge(self):
        self.world.land_lock_ready(lock=None)
        driver = self.driver()
        rs.seed(driver, merge=support.MERGE)
        tokens = [c["token"] for c in driver.preview(None)["confirmations"]]
        with self.assertRaises(release_driver.Refusal) as caught:
            driver.run(None, tokens)
        self.assertEqual(caught.exception.code, "land_lock_lost")
        self.assertEqual((self.merges(), self.world.refs()), ([], {REF: COMMIT}))
        self.assertIsNone(driver.current()[1].custody)
        tokens = [c["token"] for c in driver.preview(None)["confirmations"]]
        result = driver.run(None, tokens)
        self.assertEqual((result["next"], result["lock"], len(self.merges())), ("done", RELEASED, 1))


class RefusedLockTest(LockCase):
    def test_a_lock_the_run_had_to_take_refuses_and_creates_nothing(self):
        """`acquired` exits 0 too, but means the lock was lost: the head may have moved."""
        self.world.land_lock_ready(lock=None)
        detail = self.refused("land_lock_lost", self.driver())
        self.assertIn("(acquired)", detail)
        self.assertIn("preview again", detail)
        self.assertEqual(self.world.refs(), {REF: COMMIT})

    def test_a_lock_another_pull_request_holds_refuses_and_creates_nothing(self):
        self.world.land_lock_ready(lock=OTHER)
        repo = {"full_name": SLUG}
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{OTHER}/pulls?per_page=100"], [{
            "number": 77, "state": "open", "merged_at": None, "base": {"ref": "dev", "repo": repo},
            "head": {"ref": "issue-77-x", "sha": OTHER, "repo": repo}}])
        owner, name = SLUG.split("/")
        self.world.respond_json(
            "gh", ["api", "graphql", "-f", f"query={fm.CLOSING_ISSUES}", "-f", f"owner={owner}",
                   "-f", f"name={name}", "-F", "number=77"],
            {"data": {"repository": {"pullRequest": {"closingIssuesReferences": {"nodes": []}}}}})
        detail = self.refused("land_lock_held", self.driver())
        self.assertIn(f"held_by {OTHER} (pull request 77)", detail)
        self.assertEqual((self.world.refs(), self.swaps()), ({REF: OTHER}, []))

    def test_a_lock_that_cannot_be_checked_refuses_and_creates_nothing(self):
        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{COMMIT}/pulls?per_page=100"], [])
        detail = self.refused("land_lock_unavailable", self.driver())
        self.assertIn("no_open_pr", detail)
        self.assertEqual(self.world.refs(), {REF: COMMIT})


class LockFailureTest(LockCase):
    def test_a_lock_that_cannot_be_released_never_fails_the_published_release(self):
        run = release_lock.forge_land_lock.run

        def failing(args, attempts=None):
            if args.action == "release":
                raise OSError("the network is gone")
            return run(args, attempts)

        driver = self.driver()
        with mock.patch.object(release_lock.forge_land_lock, "run", failing):
            _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual(result["lock"], {"verdict": "error", "lock_sha": None,
                                          "detail": "OSError: the network is gone"})
        self.assertEqual(result["sync"]["status"], "done")
        self.assertIsNotNone(driver.status()["release"]["receipt"])

    def test_a_lock_that_moved_during_the_run_is_left_alone(self):
        class Moved(rs.StatefulForge):
            def land(inner, request):
                super().land(request)
                if request["operation"] == "pr_merge":
                    self.world.set_ref(REF, OTHER)

        self.world.respond_json("gh", ["api", f"repos/{SLUG}/commits/{OTHER}/pulls?per_page=100"], [])
        owner = SLUG.split("/")[0]
        for listing in (f"pulls?state=closed&base=dev&sort=updated&direction=desc&per_page=100&page=1",
                        f"pulls?state=all&head={owner}:dev&sort=updated&direction=desc&per_page=100"):
            self.world.respond_json("gh", ["api", f"repos/{SLUG}/{listing}"], [])
        _, result = rs.release(self.driver(Moved(self.world)), rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual(result["lock"], {"verdict": "not_held", "lock_sha": OTHER, "detail": None})
        self.assertEqual(self.world.refs(), {REF: OTHER})


class SingleBranchTest(unittest.TestCase):
    """A profile whose integration branch is its default branch has no lock."""

    def test_no_lock_call_and_no_lock_member(self):
        world = ForgeWorld(self)
        world.verification_ready()
        driver = release_driver.Driver(rs.project(self), clock=rs.Clock(),
                                       registry={"github-forge": rs.StatefulForge(world)})
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["next"], "lock" in result), ("done", False))
        self.assertFalse(any("agent-locks" in " ".join(c["argv"]) or c["argv"][:2] == ["api", "graphql"]
                             for c in world.calls()))
        seeded = release_driver.Driver(rs.project(self), clock=rs.Clock())
        rs.seed(seeded)
        self.assertNotIn("lock", seeded.abandon())


if __name__ == "__main__":
    unittest.main()
