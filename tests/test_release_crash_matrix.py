"""Crash and retry matrix over merge, tag, Release and deploy (#128 AC3, AC8; spec Test seams)."""
import unittest

from agent_tools.release import release_adapter, release_driver
from . import forge_world, release_driver_support as rs, release_test_support as support
from .forge_world import CANONICAL, ROWS, ForgeWorld

ORDER = ["merge", "tag", "github-release", "deploy"]


class MatrixCase(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        self.world.verification_ready(integration="dev", default="main")
        self.clock = rs.Clock()
        self.forge, self.merge, self.deploy = (rs.StatefulForge(self.world), rs.FixtureMerge(),
                                               rs.FixtureDeploy())

    def driver(self, crash=None):
        registry = {"github-forge": self.forge, "fixture-merge": self.merge,
                    "fixture-deploy": self.deploy}
        if crash is not None:
            key, operation, after = crash
            registry[key] = rs.CrashAt(registry[key], operation, after=after)
        project = rs.project(self, profiles={"two-branch": rs.fixture_profile()}, integration="dev")
        return release_driver.Driver(project, registry=registry, clock=self.clock)

    def counts(self):
        pushes = sum(c["argv"] == ROWS["tag.push"]["argv"][1:] for c in self.world.calls())
        creates = sum(c["argv"][:2] == ["release", "create"] for c in self.world.calls())
        return {"merge": len(self.merge.mutations), "tag": pushes, "github-release": creates,
                "deploy": len(self.deploy.mutations)}

    def crash_then_resume(self, crash):
        driver = self.driver(crash)
        shown = driver.preview(rs.candidate())
        with self.assertRaises(rs.Crash):
            driver.run(rs.candidate(), [c["token"] for c in shown["confirmations"]])
        self.clock.advance(release_driver.CUSTODY_TTL_MS + 1)
        resumed = driver.preview(None)
        self.assertEqual(resumed["mode"], "resume")
        stale = [c["token"] for c in shown["confirmations"]]
        fresh = [c["token"] for c in resumed["confirmations"]]
        if fresh:
            with self.assertRaises(release_driver.Refusal) as caught:
                driver.run(None, stale)
            self.assertIn(caught.exception.code, ("confirmation_stale", "confirmation_required"))
        result = driver.run(None, fresh)
        return driver, result


class FixtureShapeTest(MatrixCase):
    def test_the_fixture_profile_compiles_in_order(self):
        compiled = self.driver().compiled
        self.assertEqual([n["id"] for n in (*compiled["publication"], *compiled["activation"])],
                         ORDER)
        for adapter in (self.merge, self.deploy):
            self.assertEqual(release_adapter.descriptor_problems(adapter.describe()), [])

    def test_a_moved_default_tip_never_merges(self):
        self.merge.default_tip = "9" * 40
        _, result = rs.release(self.driver(), rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
        self.assertEqual(self.counts(), {"merge": 0, "tag": 0, "github-release": 0, "deploy": 0})


class CrashMatrixTest(MatrixCase):
    def test_merge_done_tag_interrupted_resumes_without_remerge_or_retag(self):
        driver, result = self.crash_then_resume(("github-forge", "tag", True))
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual(self.counts(), {"merge": 1, "tag": 1, "github-release": 1, "deploy": 1})

    def test_each_arm_resumes_after_a_crash_past_its_mutation(self):
        arms = {"merge": ("fixture-merge", "merge"), "tag": ("github-forge", "tag"),
                "github-release": ("github-forge", "release"),
                "deploy": ("fixture-deploy", "deploy")}
        for arm, (key, operation) in arms.items():
            with self.subTest(arm=arm):
                self.setUp()
                _, result = self.crash_then_resume((key, operation, True))
                self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
                self.assertEqual(self.counts(), dict.fromkeys(ORDER, 1))

    def test_a_crash_before_the_mutation_retries_only_with_a_fresh_token(self):
        driver, result = self.crash_then_resume(("github-forge", "tag", False))
        self.assertEqual(result["next"], "done")
        self.assertEqual(self.counts()["tag"], 1)
        tag = next(a for a in driver.status()["release"]["actions"] if a["name"] == "tag")
        self.assertEqual(tag["attempts"], 2)

    def test_each_postcondition_is_inspected_before_the_next_action(self):
        driver = self.driver()
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual(result["next"], "done")
        events = driver.store().load(result["transaction_id"]).events
        names = {e["action_id"]: e["name"] for e in events if e["type"] == "action_declared"}
        firsts = {}
        lasts = {}
        for event in events:
            name = names.get(event.get("action_id"))
            if name is None:
                continue
            firsts.setdefault(name, event["seq"])
            if event["type"] == "action_inspected" and event["outcome"] == "satisfied":
                lasts[name] = event["seq"]
        for before, after in zip(ORDER, ORDER[1:]):
            self.assertLess(lasts[before], firsts[after], (before, after))


class WatchCrashTest(unittest.TestCase):
    """Issue 555 AC3: a crash while watching resumes by observing; publication never reruns."""

    def setUp(self):
        self.world = ForgeWorld(self)
        self.world.verification_ready()
        self.clock = rs.Clock()
        self.forge, self.watch = rs.StatefulForge(self.world), rs.ScriptedWatch(("satisfied", "deployed"))

    def counts(self):
        pushes = sum(c["argv"] == ROWS["tag.push"]["argv"][1:] for c in self.world.calls())
        creates = sum(c["argv"][:2] == ["release", "create"] for c in self.world.calls())
        return pushes, creates

    def test_a_crash_while_watching_resumes_by_observing_without_republishing(self):
        project = rs.project(self, profiles={"watched": support.watched_profile()})
        driver = release_driver.Driver(project, clock=self.clock, registry={
            "github-forge": self.forge, "github-actions-health": self.watch})
        self.watch.crash_next_inspect = True
        shown = driver.preview(rs.candidate())
        with self.assertRaises(rs.Crash):
            driver.run(rs.candidate(), [c["token"] for c in shown["confirmations"]])
        self.assertEqual(driver.status()["release"]["state"], "activating")
        self.assertEqual(self.counts(), (1, 1))
        self.clock.advance(release_driver.CUSTODY_TTL_MS + 1)
        resumed = driver.preview(None)
        self.assertEqual((resumed["mode"], resumed["confirmations"]), ("resume", []))
        result = driver.run(None, [])
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual(self.counts(), (1, 1))
        events = driver.store().load(result["transaction_id"]).events
        start = next(e["seq"] for e in events
                     if e["type"] == "transitioned" and e["to"] == "activating")
        names = {e["action_id"]: e["name"] for e in events if e["type"] == "action_declared"}
        later = [names[e["action_id"]] for e in events if e["seq"] > start and e["type"] in
                 ("action_inspected", "invocation_intended", "invocation_returned")]
        self.assertEqual(later, ["deploy"])


class WatchedTwoBranchTest(unittest.TestCase):
    """Issue 555 D6: in the JarBird shape the watch observes the merge binding."""

    def test_a_two_branch_watch_receives_the_merge(self):
        world = ForgeWorld(self)
        world.verification_ready(integration="dev")
        world.merge_observation_ready()
        forge, watch = rs.StatefulForge(world), rs.ScriptedWatch(("satisfied", "deployed"))
        world.merge_ready()
        world.land_lock_ready()
        project = rs.project(self, profiles={"watched": support.watched_merge_profile()},
                             integration="dev")
        driver = release_driver.Driver(project, clock=rs.Clock(), registry={
            "github-forge": forge, "github-actions-health": watch})
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        effect = next(request for request in watch.requests if request["kind"] == "effect")
        self.assertEqual(effect["parameters"]["candidate"],
                         {"version": CANONICAL["tag"], "commit": CANONICAL["commit"],
                          "merge": support.MERGE})


if __name__ == "__main__":
    unittest.main()


TWO_BRANCH = ["merge", "tag", "github-release", "deploy"]


class TwoBranchMatrixTest(unittest.TestCase):
    """Issue 554: the real forge merges, then tags its merge commit (spec §4, AC3)."""

    def setUp(self):
        self.world = ForgeWorld(self)
        self.world.verification_ready(integration="dev")
        self.world.merge_observation_ready()
        self.clock = rs.Clock()
        self.forge, self.deploy = rs.StatefulForge(self.world), rs.FixtureDeploy()
        self.world.merge_ready()
        self.world.land_lock_ready()

    def driver(self, forge=None, crash=None):
        forge = forge or self.forge
        if crash is not None:
            forge = rs.CrashAt(forge, crash, after=True)
        project = rs.project(self, profiles={"two-branch": rs.forge_merge_profile()}, integration="dev")
        return release_driver.Driver(project, registry={"github-forge": forge, "fixture-deploy": self.deploy},
                                     clock=self.clock)

    def merges(self):
        return [c for c in self.world.calls() if c["tool"] == "gh" and c["argv"][:2] == ["pr", "merge"]]

    def tags(self):
        return [c["argv"] for c in self.world.calls() if c["tool"] == "git" and c["argv"][:2] == ["tag", "-a"]]

    def test_a_confirmed_two_branch_release_merges_once_and_tags_the_merge_commit(self):
        driver = self.driver()
        shown, result = rs.release(driver, rs.candidate())
        self.assertEqual([c["action"] for c in shown["confirmations"]], TWO_BRANCH[:3])
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual(len(self.merges()), 1)
        self.assertEqual(self.tags(), [["tag", "-a", CANONICAL["tag"], CANONICAL["merge_commit"],
                                        "-m", f"release: {CANONICAL['tag']}"]])

    def test_a_crash_after_the_merge_tags_the_merge_commit(self):
        """Issue 554 row 10, AC3."""
        driver = self.driver(crash="pr_merge")
        shown = driver.preview(rs.candidate())
        with self.assertRaises(rs.Crash):
            driver.run(rs.candidate(), [c["token"] for c in shown["confirmations"]])
        self.clock.advance(release_driver.CUSTODY_TTL_MS + 1)
        resumed = driver.preview(None)
        self.assertEqual((resumed["mode"], resumed["candidate"]["merge"]), ("resume", support.MERGE))
        # The crash left merge's intent open with no recorded inspection, so it is not stored
        # satisfied and is confirmed again; the resumed run inspects it and never re-invokes.
        self.assertEqual([c["action"] for c in resumed["confirmations"]], TWO_BRANCH[:3])
        result = driver.run(None, [c["token"] for c in resumed["confirmations"]])
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual(len(self.merges()), 1)
        self.assertEqual([argv[3] for argv in self.tags()], [CANONICAL["merge_commit"]])
        actions = {a["name"]: (a["status"], a["attempts"]) for a in driver.status()["release"]["actions"]}
        # One attempt: the intent the crashed invoke opened. The resume adds an inspection, not an attempt.
        self.assertEqual(actions["merge"], ("satisfied", 1))

    def test_a_provider_refused_merge_parks_with_no_effect(self):
        """Issue 554 rows 6 and 7: GitHub refuses a moved base or a moved head; the PR stays open."""
        for stderr in ("GraphQL: Head branch is out of date (mergePullRequest)",
                       "GraphQL: Head branch was modified. Review and try the merge again."):
            with self.subTest(stderr=stderr):
                self.setUp()
                self.world.merge_ready(merge_exit=1, merge_stderr=stderr)
                driver = self.driver()
                _, result = rs.release(driver, rs.candidate())
                self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
                reason = driver.status()["release"]["reason"]
                self.assertTrue(reason.startswith("merge: absent after unknown transient_transport: "), reason)
                self.assertEqual((len(self.merges()), self.tags()), (1, []))
                self.assertEqual(driver.abandon()["state"], "abandoned")

    def test_a_landed_merge_that_exits_non_zero_is_satisfied(self):
        """Issue 554 row 8: the same-call inspection reads MERGED, and the tag follows."""
        forge = rs.LandedDespiteExit(self.world)
        self.world.merge_ready(merge_exit=1, merge_stderr="gh: connection reset")
        driver = self.driver(forge=forge)
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual(len(self.merges()), 1)
        self.assertEqual([argv[3] for argv in self.tags()], [CANONICAL["merge_commit"]])

    def test_a_floor_refusal_parks_with_its_reason_and_abandons(self):
        """Issue 554 row 16, AC2."""
        floor = forge_world.FLOOR_PROTECTION
        self.world.merge_ready(protection={**floor, "enforce_admins": {"enabled": False}})
        driver = self.driver()
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual(result["next"], "attention")
        self.assertEqual(driver.status()["release"]["reason"],
                         "merge: absent after rejected precondition_failed: "
                         "protection_floor_unmet: enforce_admins")
        self.assertEqual((self.merges(), self.tags()), ([], []))
        self.assertEqual(driver.abandon()["state"], "abandoned")
