"""The release driver library against the real TransactionStore (#128 spec §1, §2, §4, §7)."""
import json
import re
import unittest

from agent_tools import forge_adapter, release_driver, release_profile
from agent_tools.canonical import telemetry_digest
from . import release_driver_support as rs
from . import release_test_support as support
from .forge_world import CANONICAL, ROWS, ForgeWorld

TOKEN = re.compile(r"^(tag|github-release):[0-9a-f]{12}$")


class DriverCase(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        self.clock = rs.Clock()

    def driver(self, project=None, **kwargs):
        return release_driver.Driver(project or rs.project(self), clock=self.clock, **kwargs)

    def assertRefusal(self, code, call, *args, **kwargs):
        with self.assertRaises(release_driver.Refusal) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception


class SelectionTest(DriverCase):
    def test_the_sole_publication_profile_is_selected(self):
        project = rs.project(self, profiles={"github-release": support.forge_profile(),
                                             "forge-target": support.publication_free_profile()})
        self.assertEqual(self.driver(project).profile_id, "github-release")

    def test_ambiguous_unknown_and_inadmissible_refuse(self):
        two = rs.project(self, profiles={"a-release": support.forge_profile(),
                                         "b-release": support.forge_profile()})
        refusal = self.assertRefusal("profile_ambiguous", self.driver, two)
        self.assertIn("a-release, b-release", refusal.detail)
        self.assertEqual(self.driver(two, profile_id="b-release").profile_id, "b-release")
        self.assertRefusal("profile_unknown", self.driver, two, profile_id="nope")
        bad = rs.project(self, profiles={"github-release": support.missing_deadline_profile()})
        self.assertRefusal("profile_inadmissible", self.driver, bad)


class GateTest(DriverCase):
    def test_unrunnable_shapes_refuse_preview_and_show_in_status(self):
        restorable = rs.project(self, profiles={"restorable": support.restorable_profile()})
        registry = {"github-forge": forge_adapter, "fixture-store": rs.FixtureStore()}
        cases = (("merge_not_declared", "release.profile.merge_unsupported",
                  rs.project(self, integration="dev"), {}),
                 ("deploy_watch_unowned", "release.profile.activation_unbound",
                  rs.project(self, deploy_adapter="github-actions-health"), {}),
                 ("anchors_unsupported", "release.profile.anchor_unbound", restorable,
                  {"registry": registry}))
        for code, repair, project, kwargs in cases:
            with self.subTest(code=code):
                driver = self.driver(project, **kwargs)
                refusal = self.assertRefusal(code, driver.preview, rs.candidate())
                self.assertEqual(refusal.repair_id, repair)
                self.assertEqual(driver.status()["shape"]["code"], code)
        self.assertEqual(self.world.calls(), [])

    def test_main_checkout_and_cwd_read_the_filesystem(self):
        root = rs.project(self).root
        self.assertEqual(release_driver.main_checkout(root), root / ".git")
        (root / "sub").mkdir()
        release_driver.require_cwd(root, root / "sub")
        linked = root.parent / "linked"
        linked.mkdir()
        (linked / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        self.assertRefusal("not_main_checkout", release_driver.main_checkout, linked)
        self.assertRefusal("cwd_mismatch", release_driver.require_cwd, root, linked)


class PreviewTest(DriverCase):
    def test_new_preview_names_both_irreversible_actions_and_writes_nothing(self):
        self.world.verification_ready()
        driver = self.driver()
        document = driver.preview(rs.candidate())
        self.assertEqual((document["mode"], document["runnable"], document["refusal"]),
                         ("new", True, None))
        self.assertEqual([(a["name"], a["effect"], a["status"]) for a in document["actions"]],
                         [("tag", "irreversible", None), ("github-release", "irreversible", None)])
        names = [c["action"] for c in document["confirmations"]]
        self.assertEqual(names, ["tag", "github-release"])
        for confirmation in document["confirmations"]:
            self.assertRegex(confirmation["token"], TOKEN)
            self.assertEqual(confirmation["token"], release_driver.token(
                document["plan_digest"], confirmation["action"], 1, 1))
        self.assertFalse((driver.project.common_dir / "agent-release").exists())
        self.assertEqual({c["argv"][0] for c in self.world.calls()}, {"api"})

    def test_tokens_are_stable_and_follow_their_inputs(self):
        self.world.verification_ready()
        driver = self.driver()
        first, again = driver.preview(rs.candidate()), driver.preview(rs.candidate())
        self.assertEqual(first, again)
        retitled = driver.preview(rs.candidate(title="v1.2.3 — other"))
        self.assertNotEqual(retitled["plan_digest"], first["plan_digest"])
        self.assertNotEqual(retitled["confirmations"][0]["token"], first["confirmations"][0]["token"])

    def test_unready_ci_is_not_runnable_but_still_names_the_confirmations(self):
        cases = (("verification_pending", {"runs": []}),
                 ("candidate_stale", {"tip": "9" * 40}))
        for code, kwargs in cases:
            with self.subTest(code=code):
                self.world.reset()
                self.world.verification_ready(**kwargs)
                document = self.driver().preview(rs.candidate())
                self.assertEqual((document["runnable"], document["refusal"]["code"]), (False, code))
                self.assertEqual(len(document["confirmations"]), 2)

    def test_new_mode_needs_a_valid_candidate(self):
        self.assertRefusal("candidate_required", self.driver().preview, None)
        self.assertRefusal("candidate_invalid", self.driver().preview, rs.candidate(version="1.2.3"))

    def test_a_nonterminal_release_is_previewed_for_resume_only(self):
        driver = self.driver()
        tid = rs.seed(driver)
        refusal = self.assertRefusal("release_in_flight", driver.preview, rs.candidate())
        self.assertIn("v1.2.3", refusal.detail)
        document = driver.preview(None)
        digest = driver.store().load(tid).events[0]["proof_plan_digest"]
        self.assertEqual((document["mode"], document["verification"]), ("resume", None))
        self.assertEqual(document["plan_digest"], telemetry_digest(
            {"transaction_id": tid, "proof_plan_digest": digest}))
        self.assertEqual(document["candidate"]["title"], rs.candidate()["title"])
        self.assertEqual(self.world.calls(), [])

    def test_an_abandoned_release_frees_its_version(self):
        self.world.verification_ready()
        driver = self.driver()
        tid = rs.seed(driver)
        store = driver.store()
        custody = store.acquire(tid, executor_id="t", subject_path=str(driver.project.root),
                                ttl_ms=1000).custody
        store.advance(tid, "abandoned", reason="test", external_state="known", custody=custody)
        document = driver.preview(rs.candidate())
        self.assertEqual((document["mode"], document["runnable"]), ("new", True))


class StatusTest(DriverCase):
    def test_no_store_reads_as_no_release(self):
        driver = self.driver()
        self.assertEqual(driver.status()["release"], None)
        self.assertFalse((driver.project.common_dir / "agent-release").exists())

    def test_status_shows_a_nonterminal_release(self):
        driver = self.driver()
        tid = rs.seed(driver)
        store = driver.store()
        custody = store.acquire(tid, executor_id="t", subject_path=str(driver.project.root),
                                ttl_ms=1000).custody
        store.issue_grant(custody, grant_id="g", actor="operator", actor_kind="human",
                          authority_class="release-irreversible")
        release = driver.status()["release"]
        self.assertEqual((release["transaction_id"], release["ordinal"], release["state"],
                          release["version"], release["terminal"], release["receipt"]),
                         (tid, 1, "created", "v1.2.3", None, None))
        self.assertEqual(release["grants"], [{"grant_id": "g",
                                              "authority_class": "release-irreversible",
                                              "valid": True}])
        self.assertEqual([(a["name"], a["status"], a["attempts"]) for a in release["actions"]],
                         [("tag", None, 0), ("github-release", None, 0)])
        self.assertEqual(sorted(release["hazard_markers"]), [rs.KEY])


def pushes(world):
    return [c for c in world.calls() if c["argv"] == ROWS["tag.push"]["argv"][1:]]


def creates(world):
    return [c for c in world.calls() if c["argv"][:2] == ["release", "create"]]


class RunTest(DriverCase):
    def forge(self, cls=rs.StatefulForge):
        self.world.verification_ready()
        return self.driver(registry={"github-forge": cls(self.world)})

    def test_a_confirmed_release_publishes_once_and_seals(self):
        driver = self.forge()
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertTrue(result["receipt_digest"].startswith("sha256:"))
        self.assertEqual((len(pushes(self.world)), len(creates(self.world))), (1, 1))
        events = driver.store().load(result["transaction_id"]).events
        def seq(predicate):
            return next(e["seq"] for e in events if predicate(e))
        verification = next(e for e in events if e["type"] == "evidence_recorded"
                            and e["evidence_id"].startswith("verification:"))
        self.assertEqual(json.loads(verification["reference"])["result"], "passed")
        self.assertLess(verification["seq"], seq(lambda e: e.get("to") == "ready"))
        self.assertLess(seq(lambda e: e.get("evidence_id") == "activation-not-applicable"),
                        seq(lambda e: e.get("to") == "proving"))
        self.assertIsNone(driver.store().load(result["transaction_id"]).custody)

    def test_actions_run_in_bind_candidate_order_with_its_parameters(self):
        driver = self.forge()
        _, result = rs.release(driver, rs.candidate())
        declared = [(e["name"], dict(e["parameters"]))
                    for e in driver.store().load(result["transaction_id"]).events
                    if e["type"] == "action_declared"]
        units = release_profile.bind_candidate(driver.compiled, rs.candidate())["proof"]["units"]
        self.assertEqual(declared, [(u["name"], u["parameters"]) for u in units])

    def test_a_diverged_tag_parks_and_is_never_reported_released(self):
        driver = self.forge()
        self.world.respond_json("gh", ROWS["tag.ref"]["argv"][1:],
                                {"object": {"type": "tag", "sha": CANONICAL["tag_object"]}})
        self.world.respond_json("gh", ROWS["tag.object"]["argv"][1:],
                                {"object": {"type": "commit", "sha": "9" * 40}})
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
        status = driver.status()["release"]
        self.assertEqual((status["reason"], status["terminal"]), ("tag: diverged", None))
        self.assertEqual(pushes(self.world), [])

    def test_proof_that_never_converges_parks(self):
        driver = self.forge(rs.NeverVisible)
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("proving", "wait"))
        self.clock.advance(1_800_000)
        result = driver.run(None, [])
        self.assertEqual(result["next"], "attention")
        status = driver.status()["release"]
        self.assertEqual((status["state"], status["parked_from"], status["reason"],
                          status["terminal"]),
                         ("attention_required", "proving", "proof_did_not_converge", None))


class RunRefusalTest(DriverCase):
    def setUp(self):
        super().setUp()
        self.registry = {"github-forge": rs.StatefulForge(self.world)}

    def test_missing_partial_or_stale_tokens_write_nothing(self):
        self.world.verification_ready()
        driver = self.driver(registry=self.registry)
        tokens = [c["token"] for c in driver.preview(rs.candidate())["confirmations"]]
        for code, supplied in (("confirmation_required", []),
                               ("confirmation_required", tokens[:1]),
                               ("confirmation_stale", ["tag:000000000000", tokens[1]])):
            with self.subTest(supplied=supplied):
                self.assertRefusal(code, driver.run, rs.candidate(), supplied)
        self.assertFalse((driver.project.common_dir / "agent-release").exists())

    def test_red_or_pending_ci_reserves_no_version(self):
        driver = self.driver(registry=self.registry)
        for code, runs in (("verification_failed",
                            [{"id": 1, "name": "Nix Eval", "status": "completed",
                              "conclusion": "failure", "app": {"id": 15368}}]),
                           ("verification_pending", [])):
            with self.subTest(code=code):
                self.world.verification_ready(runs=runs)
                self.assertRefusal(code, driver.run, rs.candidate(), [])
                self.assertFalse((driver.project.common_dir / "agent-release").exists())
        self.world.verification_ready()
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((driver.current()[0], result["next"]), (1, "done"))

    def test_a_published_version_is_never_reused(self):
        self.world.verification_ready()
        driver = self.driver(registry=self.registry)
        rs.release(driver, rs.candidate())
        self.assertEqual(driver.preview(rs.candidate())["refusal"]["code"], "version_reserved")
        self.assertRefusal("version_reserved", driver.run, rs.candidate(), [])

    def test_live_custody_is_release_busy(self):
        driver = self.driver(registry=self.registry)
        tid = rs.seed(driver)
        driver.store().acquire(tid, executor_id="other", subject_path=str(driver.project.root),
                               ttl_ms=10_000_000)
        tokens = [c["token"] for c in driver.preview(None)["confirmations"]]
        self.assertRefusal("release_busy", driver.run, None, tokens)


class AbandonTest(DriverCase):
    def test_guard_denied_first_action_abandons_and_frees_the_version(self):
        self.world.verification_ready()
        forge = rs.StatefulForge(self.world)
        self.world.invoke_ready(guard_exit=1)
        driver = self.driver(registry={"github-forge": forge})
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
        self.assertEqual(driver.abandon()["state"], "abandoned")
        self.assertEqual(pushes(self.world), [])
        self.world.invoke_ready()
        again = driver.preview(rs.candidate())
        self.assertEqual((again["mode"], again["runnable"]), ("new", True))

    def test_abandon_refuses_after_an_effect_or_with_nothing_to_abandon(self):
        self.assertRefusal("no_release", self.driver().abandon)
        self.world.verification_ready()
        forge = rs.StatefulForge(self.world)
        self.world.invoke_ready(create_exit=1, create_stderr="gh: HTTP 422")
        driver = self.driver(registry={"github-forge": forge})
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual(result["next"], "attention")
        self.assertEqual(len(pushes(self.world)), 1)
        self.assertRefusal("abandon_refused", driver.abandon)
        self.assertEqual(driver.status()["release"]["state"], "attention_required")


if __name__ == "__main__":
    unittest.main()
