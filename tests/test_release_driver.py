"""The release driver library against the real TransactionStore (#128 spec §1, §2, §4, §7)."""
import dataclasses
import json
import os
import re
import unittest
from unittest import mock

from agent_tools import forge_adapter, release_driver, release_profile
from agent_tools.canonical import telemetry_digest
from agent_tools import transaction_core, transaction_storage
from agent_tools.transaction_core import TransactionStore
from agent_tools.transaction_proof import proof_refused
from agent_tools.transaction_storage import ProofRefused, StateInvalid
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
                 ("anchors_unsupported", "release.profile.anchor_unbound", restorable,
                  {"registry": registry}))
        for code, repair, project, kwargs in cases:
            with self.subTest(code=code):
                driver = self.driver(project, **kwargs)
                refusal = self.assertRefusal(code, driver.preview, rs.candidate())
                self.assertEqual(refusal.repair_id, repair)
                self.assertNotIn("ship-release", refusal.detail)
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


class CollectionRefusalTest(DriverCase):
    """Only the two refusals that mean "not yet" wait; any other is a defect that surfaces."""

    def refusing(self, reason):
        def refuse(_store, custody, **_):
            raise proof_refused(custody.transaction_id, reason, "collect_obligation")
        return mock.patch.object(TransactionStore, "collect_obligation", refuse)

    def run_released(self, reason):
        self.world.verification_ready()
        driver = self.driver(registry={"github-forge": rs.StatefulForge(self.world)})
        with self.refusing(reason):
            return rs.release(driver, rs.candidate())

    def test_a_defect_refusal_propagates_instead_of_parking(self):
        for reason in ("unknown_obligation", "unsupported_obligation", "state_not_proving",
                       "clock_regressed", "not_cohort_member"):
            with self.subTest(reason=reason):
                with self.assertRaises(ProofRefused) as caught:
                    self.run_released(reason)
                self.assertEqual(caught.exception.reason, reason)

    def test_a_dependency_not_yet_accepted_or_an_accepted_event_waits(self):
        for reason in ("dependency_not_accepted", "already_accepted"):
            with self.subTest(reason=reason):
                _, result = self.run_released(reason)
                self.assertEqual((result["state"], result["next"]), ("proving", "wait"))


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


class FinalReviewTest(DriverCase):
    """Custody renewal, a torn create, an optional unsupported obligation and profile drift."""

    def forge(self, project=None):
        self.world.verification_ready()
        return self.driver(project, registry={"github-forge": rs.StatefulForge(self.world)})

    def test_custody_is_renewed_before_every_action(self):
        driver = self.forge()
        calls = []
        renew, invoke = TransactionStore.renew, TransactionStore.invoke_action

        def spy_renew(store, custody, **kwargs):
            calls.append("renew")
            return renew(store, custody, **kwargs)

        def spy_invoke(store, custody, **kwargs):
            calls.append(kwargs["name"])
            return invoke(store, custody, **kwargs)

        with mock.patch.object(TransactionStore, "renew", spy_renew), \
                mock.patch.object(TransactionStore, "invoke_action", spy_invoke):
            _, result = rs.release(driver, rs.candidate())
        self.assertEqual(result["next"], "done")
        invoked = [i for i, call in enumerate(calls) if call != "renew"]
        self.assertEqual([calls[i] for i in invoked], ["tag", "github-release"])
        for index in invoked:
            self.assertEqual(calls[index - 1], "renew")

    def test_a_create_torn_before_its_state_is_recreated_under_the_same_key(self):
        driver = self.forge()
        shown = driver.preview(rs.candidate())
        tokens = [c["token"] for c in shown["confirmations"]]
        with mock.patch.object(transaction_core, "materialize_plan",
                               side_effect=rs.Crash("create")):
            with self.assertRaises(rs.Crash):
                driver.run(rs.candidate(), tokens)
        key = release_driver.creation_key(rs.PROJECT_ID, driver.profile_id, 1)
        torn = driver.store().lookup(key)
        self.assertIsNotNone(torn)
        self.assertIsNone(driver.status()["release"])
        self.assertEqual(driver.preview(rs.candidate()), shown)
        result = driver.run(rs.candidate(), tokens)
        self.assertEqual((result["transaction_id"], result["next"]), (torn, "done"))

    def test_an_unreadable_state_is_not_taken_for_a_torn_create(self):
        driver = self.driver()
        rs.seed(driver)
        real_lstat = transaction_storage.os.lstat

        def denied(path, *args, **kwargs):
            if str(path).endswith("state.json"):
                raise PermissionError(13, "Permission denied", str(path))
            return real_lstat(path, *args, **kwargs)

        with mock.patch.object(transaction_storage.os, "lstat", denied):
            for call in (driver.status, lambda: driver.preview(None)):
                with self.assertRaises(PermissionError):
                    call()

    def test_any_other_load_failure_still_propagates(self):
        driver = self.driver()
        tid = rs.seed(driver)
        (driver.store().root / tid / "state.json").write_text("{", encoding="utf-8")
        for call in (driver.status, lambda: driver.preview(None)):
            with self.assertRaises(StateInvalid):
                call()

    def test_an_optional_unsupported_obligation_is_never_collected(self):
        profile = support.forge_profile()
        profile["proof"]["obligations"].append({
            "id": "optional-up", "semantic": "liveness", "form": "event",
            "predicate": "service_up", "collector": "forge", "required": False, "deps": [],
            "parameters": {}})
        driver = self.forge(rs.project(self, profiles={"github-release": profile}))
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))

    def test_a_changed_profile_refuses_resume_before_any_write(self):
        driver = self.driver()
        tid = rs.seed(driver)
        profile = support.forge_profile()
        profile["publication"]["actions"][0]["observation_deadline_ms"] += 1
        drifted = self.driver(dataclasses.replace(driver.project, contract={
            **driver.project.contract, "release": {"profiles": {"github-release": profile}}}))
        before = driver.store().load(tid).events
        self.assertRefusal("profile_drift", drifted.preview, None)
        self.assertRefusal("profile_drift", drifted.run, None, [])
        self.assertEqual(driver.store().load(tid).events, before)
        self.assertEqual(drifted.status()["release"]["transaction_id"], tid)


if __name__ == "__main__":
    unittest.main()


class ActivationWatchTest(DriverCase):
    """Issue 555 D2, D4, D5: a github-actions-health unit is an inspect-only activation."""

    def watched(self, watch, project=None):
        self.world.reset()
        self.world.verification_ready()
        registry = {"github-forge": rs.StatefulForge(self.world), "github-actions-health": watch}
        project = project or rs.project(self, profiles={"watched": support.watched_profile()})
        return self.driver(project, registry=registry)

    def deploy(self, driver):
        return next(a for a in driver.status()["release"]["actions"] if a["name"] == "deploy")

    def test_a_watched_profile_compiles_and_passes_the_shape_gate(self):
        """AC1."""
        driver = self.watched(rs.ScriptedWatch())
        self.assertIsNone(driver.shape_refusal())
        self.assertIsNone(driver.status()["shape"])
        document = driver.preview(rs.candidate())
        self.assertEqual((document["runnable"], document["refusal"]), (True, None))
        self.assertEqual([(a["name"], a["phase"], a["mode"], a["effect"]) for a in document["actions"]],
                         [("tag", "publication", "index", "irreversible"),
                          ("github-release", "publication", "index", "irreversible"),
                          ("deploy", "activation", "publication_triggered",
                           "reversible_no_incremental_spend")])
        self.assertEqual([c["action"] for c in document["confirmations"]], ["tag", "github-release"])

    def test_the_watch_reads_run_without_the_tracker_credential_exclusions(self):
        """The contract's `unset_before_invocation` names are absent from every watch read,
        and are back in this process afterwards."""
        names = ["GITHUB_TOKEN", "GH_TOKEN"]
        project = rs.project(self, profiles={"watched": support.watched_profile()})
        project = dataclasses.replace(project, contract={
            **project.contract, "bindings": {**project.contract["bindings"], "tracker": {
                **project.contract["bindings"]["tracker"],
                "credential_env": {"unset_before_invocation": names}}}})
        watch = rs.ScriptedWatch(("satisfied", "deployed"))
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "expired", "GH_TOKEN": "expired",
                                          "KEPT": "kept"}):
            driver = self.watched(watch, project)
            _, result = rs.release(driver, rs.candidate())
            self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
            self.assertEqual(os.environ["GITHUB_TOKEN"], "expired")
        self.assertEqual({request["kind"] for request in watch.requests}, {"effect", "predicate"})
        for environment in watch.environments:
            self.assertEqual([name for name in names if name in environment], [])
            self.assertEqual(environment["KEPT"], "kept")

    def test_a_satisfied_watch_proves_and_succeeds_without_an_invoke(self):
        """AC4: satisfied."""
        watch = rs.ScriptedWatch(("satisfied", "deployed"))
        driver = self.watched(watch)
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual({request["kind"] for request in watch.requests}, {"effect", "predicate"})
        effect = next(request for request in watch.requests if request["kind"] == "effect")
        self.assertEqual(effect["parameters"]["candidate"],
                         {"version": CANONICAL["tag"], "commit": CANONICAL["commit"]})
        deploy = self.deploy(driver)
        self.assertEqual((deploy["phase"], deploy["status"], deploy["attempts"]),
                         ("activation", "satisfied", 0))
        events = driver.store().load(result["transaction_id"]).events
        self.assertNotIn(release_driver.ACTIVATION_NOT_APPLICABLE,
                         [event.get("evidence_id") for event in events])

    def test_pending_outcomes_wait_through_the_deadline(self):
        """AC4: in_progress, and absent within the window, wait (D5)."""
        for outcome, reason in (("in_progress", "run_in_progress"), ("absent", "run_absent"),
                                ("unknown", "health_unreachable")):
            with self.subTest(outcome=outcome):
                driver = self.watched(rs.ScriptedWatch((outcome, reason)))
                _, result = rs.release(driver, rs.candidate())
                self.assertEqual((result["state"], result["next"]), ("activating", "wait"))
                self.clock.advance(rs.WATCH_DEADLINE_MS)
                result = driver.run(None, [])
                self.assertEqual((result["state"], result["next"]), ("activating", "wait"))
                self.assertEqual(self.deploy(driver)["attempts"], 0)

    def test_pending_outcomes_past_the_deadline_park_with_the_run_reference(self):
        """AC4: absent past the window parks naming run_absent (no run exists to reference);
        in_progress and unknown are bounded too and name the run (D5)."""
        for outcome, reason in (("absent", "run_absent"), ("in_progress", "run_in_progress"),
                                ("unknown", "health_unreachable")):
            with self.subTest(outcome=outcome):
                driver = self.watched(rs.ScriptedWatch((outcome, reason)))
                rs.release(driver, rs.candidate())
                self.clock.advance(rs.WATCH_DEADLINE_MS + 1)
                result = driver.run(None, [])
                self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
                status = driver.status()["release"]
                self.assertEqual((status["parked_from"], status["terminal"]), ("activating", None))
                self.assertTrue(status["reason"].startswith(
                    f"deploy: {outcome} past {rs.WATCH_DEADLINE_MS} ms: "), status["reason"])
                self.assertIn(reason, status["reason"])
                if outcome == "absent":
                    self.assertNotIn("actions/runs/", status["reason"])
                else:
                    self.assertIn(rs.WATCH_RUN_REFERENCE, status["reason"])

    def test_a_failed_run_or_a_stale_health_commit_parks_and_never_succeeds(self):
        """AC2 and AC4: diverged parks with the run reference, and resuming parks again."""
        for reason in ("run_failed", "health_commit_mismatch", "silent_rollback", "superseded"):
            with self.subTest(reason=reason):
                driver = self.watched(rs.ScriptedWatch(("diverged", reason)))
                _, result = rs.release(driver, rs.candidate())
                self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
                status = driver.status()["release"]
                self.assertEqual((status["parked_from"], status["terminal"], status["receipt"]),
                                 ("activating", None, None))
                self.assertTrue(status["reason"].startswith("deploy: diverged: "), status["reason"])
                self.assertIn(rs.WATCH_RUN_REFERENCE, status["reason"])
                self.assertIn(reason, status["reason"])
                deploy = self.deploy(driver)
                self.assertEqual((deploy["phase"], deploy["status"], deploy["attempts"]),
                                 ("activation", "diverged", 0))
                self.assertIn(rs.WATCH_RUN_REFERENCE, deploy["reference"])
                again = driver.run(None, [])
                self.assertEqual((again["state"], again["next"]), ("attention_required", "attention"))

    def test_a_running_identity_left_on_the_previous_release_parks_in_proving(self):
        """AC2: the deploy run succeeded, but the running identity is still the previous release."""
        driver = self.watched(rs.ScriptedWatch(("satisfied", "deployed"), running="unsatisfied"))
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
        status = driver.status()["release"]
        self.assertEqual((status["parked_from"], status["reason"], status["terminal"]),
                         ("proving", "proof_rejected", None))


class MergePreviewTest(DriverCase):
    """Issue 554 D3: a two-branch preview observes the release PR before the receipt."""

    def setUp(self):
        super().setUp()
        self.world.verification_ready(integration="dev")
        self.world.merge_observation_ready()

    def two_branch(self):
        return self.driver(rs.project(self, profiles={"two-branch": support.merge_profile()},
                                      integration="dev"))

    def test_a_two_branch_profile_passes_the_shape_gate_and_lists_three_confirmations(self):
        """Issue 554 AC1."""
        driver = self.two_branch()
        self.assertIsNone(driver.shape_refusal())
        document = driver.preview(rs.candidate())
        self.assertEqual((document["runnable"], document["refusal"]), (True, None))
        self.assertEqual([c["action"] for c in document["confirmations"]], ["merge", "tag", "github-release"])
        self.assertEqual(document["candidate"]["merge"], support.MERGE)
        self.assertFalse((driver.project.common_dir / "agent-release").exists())

    def test_merge_observation_refusals_create_nothing(self):
        """Issue 554 row 11."""
        stale = [{"number": CANONICAL["pr"], "head": {"sha": "9" * 40}}]
        for code, ready in (("release_pr_missing", dict(prs=[])), ("release_pr_stale", dict(prs=stale)),
                            ("release_pr_behind", dict(compare="diverged"))):
            with self.subTest(code=code):
                self.world.reset()
                self.world.verification_ready(integration="dev")
                self.world.merge_observation_ready(**ready)
                driver = self.two_branch()
                document = driver.preview(rs.candidate())
                self.assertEqual((document["runnable"], document["refusal"]["code"],
                                  document["refusal"]["repair_id"], document["verification"],
                                  document["candidate"]["merge"]), (False, code, None, None, None))
                self.assertEqual(len(document["confirmations"]), 3)
                self.assertFalse(any("check-runs" in c["argv"][-1] for c in self.world.calls()))
                self.assertRefusal(code, driver.run, rs.candidate(),
                                   [c["token"] for c in document["confirmations"]])
                self.assertFalse((driver.project.common_dir / "agent-release").exists())

    def test_a_moved_base_between_preview_and_run_is_stale(self):
        """Issue 554 row 12."""
        driver = self.two_branch()
        tokens = [c["token"] for c in driver.preview(rs.candidate())["confirmations"]]
        self.world.merge_observation_ready(base_tip="6" * 40)
        self.assertRefusal("confirmation_stale", driver.run, rs.candidate(), tokens)
        self.assertFalse((driver.project.common_dir / "agent-release").exists())

    def test_a_single_branch_preview_binds_no_merge(self):
        self.world.reset()
        self.world.verification_ready()
        document = self.driver().preview(rs.candidate())
        self.assertEqual((document["runnable"], document["candidate"]["merge"]), (True, None))
        self.assertFalse(any("/pulls?" in c["argv"][-1] for c in self.world.calls()))

    def test_a_resumed_preview_reads_merge_from_the_stored_subject(self):
        driver = self.two_branch()
        rs.seed(driver, merge=support.MERGE)
        self.world.reset()
        document = driver.preview(None)
        self.assertEqual((document["mode"], document["candidate"]["merge"]), ("resume", support.MERGE))
        self.assertEqual(self.world.calls(), [])


class RailwayActivationWatchTest(DriverCase):
    """AC3: a railway-deploy unit is an inspect-only activation the driver waits on or parks."""

    def watched(self, watch, **project):
        self.world.reset()
        self.world.verification_ready()
        registry = {"github-forge": rs.StatefulForge(self.world), "railway-deploy": watch}
        return self.driver(rs.project(self, profiles={"railway": support.railway_watched_profile()},
                                      **project), registry=registry)

    def deploy(self, driver):
        return next(a for a in driver.status()["release"]["actions"] if a["name"] == "deploy")

    def test_the_profile_passes_the_shape_gate_and_only_with_bindings_deploy_none(self):
        driver = self.watched(rs.ScriptedRailway())
        self.assertIsNone(driver.shape_refusal())
        document = driver.preview(rs.candidate())
        self.assertEqual((document["runnable"], document["refusal"]), (True, None))
        self.assertEqual([(a["name"], a["phase"], a["mode"]) for a in document["actions"]][-1],
                         ("deploy", "activation", "publication_triggered"))
        refusal = self.watched(rs.ScriptedRailway(), deploy_adapter="railway").shape_refusal()
        self.assertEqual((refusal.code, refusal.repair_id),
                         ("deploy_watch_unowned", "release.profile.activation_unbound"))

    def test_a_deployed_watch_succeeds_without_an_invoke(self):
        watch = rs.ScriptedRailway(("satisfied", "deployed"))
        driver = self.watched(watch)
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(self.deploy(driver)["attempts"], 0)
        self.assertTrue(watch.requests)

    def test_a_failed_or_rolled_back_deployment_parks_with_its_reference(self):
        for reason in ("deployment_failed", "silent_rollback", "superseded", "removed"):
            with self.subTest(reason=reason):
                driver = self.watched(rs.ScriptedRailway(("diverged", reason)))
                _, result = rs.release(driver, rs.candidate())
                self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
                status = driver.status()["release"]
                self.assertEqual(status["parked_from"], "activating")
                self.assertTrue(status["reason"].startswith("deploy: diverged: "), status["reason"])
                self.assertIn(rs.RAILWAY_REFERENCE, status["reason"])
                self.assertIn(reason, status["reason"])

    def test_an_unfinished_deployment_waits_inside_its_deadline(self):
        driver = self.watched(rs.ScriptedRailway(("in_progress", "deployment_in_progress")))
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual(result["next"], "wait")
        self.assertEqual(self.deploy(driver)["status"], "in_progress")

    def test_an_absent_deployment_waits_then_parks_past_its_deadline_and_never_succeeds(self):
        """AC3: no Railway deployment of the released commit waits inside the deadline, parks
        attention_required past it with no invoke and no receipt, and resuming while it is still
        absent parks again (release_driver watched(): absent past the deadline parks)."""
        watch = rs.ScriptedRailway(("absent", "deployment_absent"))
        driver = self.watched(watch)
        _, result = rs.release(driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("activating", "wait"))
        self.clock.advance(rs.WATCH_DEADLINE_MS)
        self.assertEqual(driver.run(None, [])["next"], "wait")
        self.clock.advance(1)
        result = driver.run(None, [])
        self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
        status = driver.status()["release"]
        self.assertEqual((status["parked_from"], status["terminal"], status["receipt"]),
                         ("activating", None, None))
        self.assertTrue(status["reason"].startswith(
            f"deploy: absent past {rs.WATCH_DEADLINE_MS} ms: "), status["reason"])
        self.assertIn("deployment_absent", status["reason"])
        self.assertNotIn(rs.RAILWAY_REFERENCE, status["reason"])
        self.assertEqual(self.deploy(driver)["attempts"], 0)
        inspected = len(watch.requests)
        again = driver.run(None, [])
        self.assertEqual((again["state"], again["next"]), ("attention_required", "attention"))
        status = driver.status()["release"]
        self.assertEqual((status["terminal"], status["receipt"]), (None, None))
        self.assertEqual(self.deploy(driver)["attempts"], 0)
        self.assertGreaterEqual(len(watch.requests), inspected)

