"""Crash and retry matrix over merge, tag, Release and deploy (#128 AC3, AC8; spec Test seams)."""
import unittest

from agent_tools import release_adapter, release_driver
from . import release_driver_support as rs
from .forge_world import ROWS, ForgeWorld

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


if __name__ == "__main__":
    unittest.main()
