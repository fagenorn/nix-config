"""The release driver's manual disposition of a release parked after an effect (issue 1050)."""
import dataclasses
import re
import unittest
from unittest import mock

from agent_tools.release import forge_adapter, release_driver
from . import release_driver_support as rs
from . import release_test_support as support
from .forge_world import ForgeWorld

GROUND = "no_recovery_path"
WHY = "api deploy failed on a migration timeout; the fix ships as the next version"
TOKEN = re.compile(r"^dispose:[0-9a-f]{12}$")


class MemoryForge:
    """`github-forge` for registry injection, held in memory so a release of any version
    publishes: an accepted invoke is what the next inspection of that operation and version
    reads. `answers` overrides one operation's effect outcome."""

    def __init__(self) -> None:
        self.done: set[tuple[str, str]] = set()
        self.answers: dict[str, str] = {}
        self.inspected: list[str] = []

    def describe(self):
        return forge_adapter.describe()

    def inspect(self, request):
        operation = request["operation"]
        present = (operation, request["parameters"]["candidate"]["version"]) in self.done
        if request["kind"] == "predicate":
            return {"outcome": "satisfied" if present else "unsatisfied",
                    "reason": "observed" if present else "ref_absent", "references": [],
                    "observed_at": 1}
        self.inspected.append(operation)
        outcome = self.answers.get(operation, "satisfied" if present else "absent")
        return {"outcome": outcome, "reason": f"{operation} {outcome}", "observed_subject": {},
                "references": [], "observed_at": 1, "facts": {}}

    def invoke(self, request):
        self.done.add((request["operation"], request["parameters"]["candidate"]["version"]))
        return {"result": "accepted", "error_class": None, "reference": "created"}


class DisposeCase(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        self.world.verification_ready()
        self.clock = rs.Clock()
        self.forge = MemoryForge()
        self.watch = rs.ScriptedRailway(("diverged", "silent_rollback"))
        self.project = rs.project(self, profiles={"railway": support.railway_watched_profile()})
        self.driver = release_driver.Driver(
            self.project, approvals=rs.approve_all, clock=self.clock,
            registry={"github-forge": self.forge, "railway-deploy": self.watch})

    def parked(self):
        """Publish the tag and the GitHub release, then park on the diverged deploy."""
        _, result = rs.release(self.driver, rs.candidate())
        self.assertEqual((result["state"], result["next"]), ("attention_required", "attention"))
        return result["transaction_id"]

    def load(self, transaction_id):
        return self.driver.store().load(transaction_id)

    def token(self, reference=WHY):
        return self.driver.preview_dispose(GROUND, reference)["confirmations"][0]["token"]

    def assertRefusal(self, code, call, *args):
        with self.assertRaises(release_driver.Refusal) as caught:
            call(*args)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def assertStillParked(self, transaction_id, events=None):
        held = self.load(transaction_id)
        self.assertEqual((held.state, held.terminal, held.custody),
                         ("attention_required", None, None))
        if events is not None:
            self.assertEqual(len(held.events), events)


class DisposeTest(DisposeCase):
    def test_preview_shows_one_dispose_token_and_writes_nothing(self):
        tid = self.parked()
        events, watched, inspected = (len(self.load(tid).events), len(self.watch.requests),
                                      len(self.forge.inspected))
        document = self.driver.preview_dispose(GROUND, WHY)
        self.assertEqual((document["mode"], document["transaction_id"], document["ordinal"],
                          document["state"], document["runnable"], document["refusal"]),
                         ("dispose", tid, 1, "attention_required", True, None))
        self.assertEqual(document["disposition"], {"ground": GROUND, "reference": WHY})
        self.assertTrue(document["reason"].startswith("deploy: diverged: "))
        confirmation, = document["confirmations"]
        self.assertEqual({k: v for k, v in confirmation.items() if k != "token"}, {
            "action": "dispose", "ground": GROUND, "version": rs.candidate()["version"],
            "commit": rs.candidate()["commit"]})
        self.assertRegex(confirmation["token"], TOKEN)
        acquisition = release_driver._next_acquisition(self.load(tid))
        self.assertEqual(confirmation["token"],
                         release_driver.dispose_token(tid, GROUND, WHY, acquisition))
        self.assertNotEqual(confirmation["token"],
                            release_driver.dispose_token(tid, GROUND, WHY, acquisition + 1))
        self.assertNotEqual(confirmation["token"],
                            release_driver.dispose_token("rel_other", GROUND, WHY, acquisition))
        self.assertEqual(self.token(), confirmation["token"])
        self.assertNotEqual(self.token("another reason"), confirmation["token"])
        self.assertNotIn(confirmation["token"],
                         [c["token"] for c in self.driver.preview(None)["confirmations"]])
        self.assertEqual((len(self.load(tid).events), len(self.watch.requests),
                          len(self.forge.inspected)), (events, watched, inspected))

    def test_a_confirmed_disposition_seals_failed_and_never_succeeded(self):
        tid = self.parked()
        token = self.token()
        self.forge.inspected.clear()
        watched = len(self.watch.requests)
        result = self.driver.dispose(GROUND, WHY, [token])
        self.assertEqual((result["transaction_id"], result["state"], result["next"]),
                         (tid, "failed", "disposed"))
        self.assertEqual(result["disposition"], {"ground": GROUND, "reference": WHY})
        self.assertTrue(result["receipt_digest"].startswith("sha256:"))
        self.assertEqual((self.forge.inspected, len(self.watch.requests)),
                         (["tag", "release"], watched + 1))
        after = self.load(tid)
        disposed = next(e for e in after.events if e["type"] == "failure_disposed")
        self.assertEqual((disposed["ground"], disposed["reference"], disposed["grant_id"],
                          disposed["qualifier"]), (GROUND, WHY, token, "final_state_known"))
        grant = next(e for e in after.events
                     if e["type"] == "grant_issued" and e["grant_id"] == token)
        self.assertEqual((grant["actor_kind"], grant["authority_class"], grant["fence"]),
                         ("human", release_driver.ADMITTED_CLASS, disposed["fence"]))
        for name in ("tag", "github-release", "deploy"):
            action_id = next(v["action_id"] for v in after.actions if v["name"] == name)
            latest = [e for e in after.events if e["type"] == "action_inspected"
                      and e["action_id"] == action_id][-1]
            self.assertEqual(latest["fence"], disposed["fence"], name)
        release = self.driver.status()["release"]
        self.assertEqual((release["state"], release["ordinal"], release["reason"]),
                         ("failed", 1, None))
        self.assertEqual(release["disposition"], {
            "ground": GROUND, "reference": WHY, "qualifier": "final_state_known",
            "grant_id": token})
        self.assertEqual((release["terminal"]["receipt_digest"],
                          release["receipt"]["outcome_proof"]["ground"],
                          release["receipt"]["outcome_proof"]["ground_reference"]),
                         (result["receipt_digest"], GROUND, WHY))
        self.assertNotIn("succeeded", [e.get("to") for e in after.events])
        self.assertRefusal("no_release", self.driver.dispose, GROUND, WHY, [token])
        self.assertRefusal("no_release", self.driver.preview_dispose, GROUND, WHY)

    def test_a_new_version_releases_in_full_after_the_disposition(self):
        self.parked()
        self.driver.dispose(GROUND, WHY, [self.token()])
        again = self.driver.preview(rs.candidate())
        self.assertEqual((again["mode"], again["runnable"], again["refusal"]["code"]),
                         ("new", False, "version_reserved"))
        self.assertRefusal("version_reserved", self.driver.run, rs.candidate(), [])
        self.watch.effects = [("satisfied", "deployed")]
        successor = rs.candidate(version="v1.2.4")
        shown, result = rs.release(self.driver, successor)
        self.assertEqual((shown["mode"], shown["runnable"]), ("new", True))
        self.assertEqual([c["action"] for c in shown["confirmations"]], ["tag", "github-release"])
        self.assertEqual((result["state"], result["next"]), ("succeeded", "done"))
        self.assertEqual([(ordinal, t.state, t.subject["candidate"]["version"])
                          for ordinal, t in self.driver.transactions()],
                         [(1, "failed", "v1.2.3"), (2, "succeeded", "v1.2.4")])
        self.assertEqual(self.driver.status()["release"]["disposition"], None)
        self.assertEqual(self.forge.done, {("tag", "v1.2.3"), ("release", "v1.2.3"),
                                           ("tag", "v1.2.4"), ("release", "v1.2.4")})

    def test_a_candidate_beside_a_release_parked_after_an_effect_is_told_the_dispose_form(self):
        self.parked()
        refusal = self.assertRefusal("release_in_flight", self.driver.preview,
                                     rs.candidate(version="v1.2.4"))
        self.assertIn("resume it with no candidate", refusal.detail)
        self.assertIn(f"release transaction preview --repo-root {self.project.root} --dispose "
                      'no_recovery_path --reference "<why>"', refusal.detail)
        self.assertIn("--confirm <token>", refusal.detail)


class DisposeRefusalTest(DisposeCase):
    def test_a_release_that_is_absent_or_not_parked_refuses(self):
        self.assertRefusal("no_release", self.driver.preview_dispose, GROUND, WHY)
        tid = rs.seed(self.driver)
        for call, args in ((self.driver.preview_dispose, (GROUND, WHY)),
                           (self.driver.dispose, (GROUND, WHY, ["dispose:000000000000"]))):
            refusal = self.assertRefusal("not_parked", call, *args)
            self.assertIn("created", refusal.detail)
        refusal = self.assertRefusal("release_in_flight", self.driver.preview,
                                     rs.candidate(version="v1.2.4"))
        self.assertNotIn("dispose", refusal.detail)
        self.assertEqual((self.load(tid).state, len(self.load(tid).events)), ("created", 1))

    def test_a_park_before_any_effect_refuses_and_is_abandoned_instead(self):
        self.forge.answers["tag"] = "diverged"
        tid = self.parked()
        events = len(self.load(tid).events)
        for call, args in ((self.driver.preview_dispose, (GROUND, WHY)),
                           (self.driver.dispose, (GROUND, WHY, ["dispose:000000000000"]))):
            self.assertIn("abandon", self.assertRefusal("no_effect", call, *args).detail)
        refusal = self.assertRefusal("release_in_flight", self.driver.preview,
                                     rs.candidate(version="v1.2.4"))
        self.assertNotIn("dispose", refusal.detail)
        self.assertStillParked(tid, events)
        self.assertEqual(self.driver.abandon()["state"], "abandoned")

    def test_a_missing_wrong_or_stale_token_writes_nothing(self):
        tid = self.parked()
        token = self.token()
        events = len(self.load(tid).events)
        action = self.driver.preview(None)["confirmations"]
        self.assertEqual(action, [])
        for code, supplied in (("confirmation_required", []),
                               ("confirmation_stale", ["dispose:000000000000"]),
                               ("confirmation_stale", [token, "tag:000000000000"]),
                               ("confirmation_stale", [self.token("another reason")])):
            with self.subTest(supplied=supplied):
                self.assertRefusal(code, self.driver.dispose, GROUND, WHY, supplied)
                self.assertStillParked(tid, events)
        self.assertEqual(self.driver.run(None, [])["next"], "attention")
        events = len(self.load(tid).events)
        self.assertNotEqual(self.token(), token)
        self.assertRefusal("confirmation_stale", self.driver.dispose, GROUND, WHY, [token])
        self.assertStillParked(tid, events)
        self.assertRefusal("confirmation_stale", self.driver.run, None, [self.token()])
        self.assertStillParked(tid, events)

    def test_a_missing_reference_or_another_ground_refuses_before_any_write(self):
        tid = self.parked()
        events = len(self.load(tid).events)
        for code, ground, reference in (("reference_required", GROUND, ""),
                                        ("reference_required", GROUND, "  \n"),
                                        ("ground_unsupported", "successor_succeeded", WHY),
                                        ("ground_unsupported", "authority_retired", WHY)):
            with self.subTest(ground=ground, reference=reference):
                self.assertRefusal(code, self.driver.preview_dispose, ground, reference)
                self.assertRefusal(code, self.driver.dispose, ground, reference, ["dispose:x"])
        self.assertStillParked(tid, events)

    def test_a_grant_that_is_not_a_human_is_refused_by_the_core(self):
        tid = self.parked()
        for member, value, reason in (("DISPOSE_ACTOR_KIND", "agent", "human_required"),):
            with self.subTest(reason=reason), mock.patch.object(release_driver, member, value):
                refusal = self.assertRefusal("dispose_refused", self.driver.dispose,
                                             GROUND, WHY, [self.token()])
                self.assertTrue(refusal.detail.startswith(reason + ": "), refusal.detail)
                self.assertStillParked(tid)
                self.assertNotIn("failure_disposed", [e["type"] for e in self.load(tid).events])
        self.assertEqual(self.driver.dispose(GROUND, WHY, [self.token()])["state"], "failed")

    def test_an_action_in_progress_or_unknown_after_the_inspection_refuses(self):
        tid = self.parked()
        for operation, outcome in (("tag", "unknown"), ("release", "in_progress")):
            with self.subTest(operation=operation, outcome=outcome):
                self.forge.answers = {operation: outcome}
                refusal = self.assertRefusal("dispose_refused", self.driver.dispose,
                                             GROUND, WHY, [self.token()])
                self.assertTrue(refusal.detail.startswith("effect_uncertain: "), refusal.detail)
                self.assertStillParked(tid)
        self.forge.answers = {}
        self.watch.effects = [("unknown", "lookup_failed")]
        refusal = self.assertRefusal("dispose_refused", self.driver.dispose,
                                     GROUND, WHY, [self.token()])
        self.assertTrue(refusal.detail.startswith("effect_uncertain: "), refusal.detail)
        self.assertStillParked(tid)
        self.watch.effects = [("diverged", "superseded")]
        self.assertEqual(self.driver.dispose(GROUND, WHY, [self.token()])["state"], "failed")

    def test_live_custody_and_a_changed_profile_refuse(self):
        tid = self.parked()
        self.driver.store().acquire(tid, executor_id="other", ttl_ms=10_000_000,
                                    subject_path=str(self.project.root))
        self.assertRefusal("release_busy", self.driver.dispose, GROUND, WHY, [self.token()])
        profile = support.railway_watched_profile()
        profile["publication"]["actions"][0]["observation_deadline_ms"] += 1
        drifted = release_driver.Driver(
            dataclasses.replace(self.project, contract={
                **self.project.contract, "release": {"profiles": {"railway": profile}}}),
            approvals=rs.approve_all,
            clock=self.clock, registry=self.driver.registry)
        refusal = self.assertRefusal("profile_drift", drifted.preview_dispose, GROUND, WHY)
        self.assertTrue(refusal.detail.endswith(": restore that profile"), refusal.detail)
        self.assertNotIn("abandon", refusal.detail)
        resume = self.assertRefusal("profile_drift", drifted.preview, None)
        self.assertTrue(resume.detail.endswith(
            ": restore that profile or abandon the release"), resume.detail)

    def test_a_release_whose_actions_all_read_satisfied_since_is_resumed_not_disposed(self):
        tid = self.parked()
        self.watch.effects = [("satisfied", "deployed")]
        refusal = self.assertRefusal("recovered", self.driver.dispose, GROUND, WHY,
                                     [self.token()])
        self.assertIn("resume it with no candidate", refusal.detail)
        self.assertStillParked(tid)
        types = [e["type"] for e in self.load(tid).events]
        self.assertNotIn("failure_disposed", types)
        self.assertNotIn(self.token(), [g["grant_id"] for g in self.load(tid).grants])
        resumed = self.driver.run(None, [])
        self.assertEqual((resumed["state"], resumed["next"]), ("succeeded", "done"))

    def test_an_acquisition_between_the_token_check_and_custody_is_stale(self):
        tid = self.parked()
        token = self.token()
        acquire = release_driver.Driver._acquire

        def racing(driver, store, transaction):
            other = store.acquire(tid, executor_id="other", ttl_ms=1000,
                                  subject_path=str(self.project.root))
            store.release(other.custody)
            return acquire(driver, store, transaction)

        with mock.patch.object(release_driver.Driver, "_acquire", racing):
            refusal = self.assertRefusal("confirmation_stale", self.driver.dispose,
                                         GROUND, WHY, [token])
        self.assertIn("preview again", refusal.detail)
        self.assertStillParked(tid)
        self.assertNotIn("grant_issued", [e["type"] for e in self.load(tid).events
                                          if e.get("grant_id") == token])
        self.assertEqual(self.driver.dispose(GROUND, WHY, [self.token()])["state"], "failed")


PARKED_FOR_MS = 33_009_000  # the real park this crashed on: nine hours ten minutes


class DisposeCustodyTest(DisposeCase):
    """Custody across a disposition (the crash after issue 1050): the fixtures above dispose
    on the clock reading they parked at, inside the core's parked custody window."""

    def test_a_release_parked_past_the_custody_window_is_disposed(self):
        tid = self.parked()
        self.clock.advance(PARKED_FOR_MS)
        store = self.driver.store()
        probe = store.acquire(tid, executor_id="probe", ttl_ms=1000,
                              subject_path=str(self.project.root))
        self.assertIsNone(store.renew(probe.custody).custody)  # a renewal here quiesces
        self.assertEqual(self.load(tid).events[-1]["reason"], "quiesced")
        result = self.driver.dispose(GROUND, WHY, [self.token()])
        self.assertEqual((result["state"], result["next"]), ("failed", "disposed"))
        after = self.load(tid)
        self.assertEqual([e["reason"] for e in after.events if e["type"] == "lease_released"][-1],
                         "terminal")
        self.assertIsNone(self.driver.store().inspect_lease(after.concurrency_keys[0])["holder"])
        self.watch.effects = [("satisfied", "deployed")]
        _, successor = rs.release(self.driver, rs.candidate(version="v1.2.4"))
        self.assertEqual((successor["state"], successor["next"]), ("succeeded", "done"))

    def test_an_inspection_that_raises_refuses_and_gives_custody_up(self):
        tid = self.parked()
        self.clock.advance(PARKED_FOR_MS)
        token = self.token()
        for shape in ("raise", "malformed"):
            with self.subTest(shape=shape):
                if shape == "raise":
                    patch = mock.patch.object(self.watch, "crash_next_inspect", True)
                else:
                    patch = mock.patch.object(self.watch, "inspect", lambda request: {})
                with patch:
                    refusal = self.assertRefusal("inspection_failed", self.driver.dispose,
                                                 GROUND, WHY, [self.token()])
                self.assertTrue(refusal.detail.startswith("deploy could not be inspected"),
                                refusal.detail)
                self.assertIn("preview the disposition again", refusal.detail)
                self.assertStillParked(tid)
                self.assertEqual(self.load(tid).events[-1]["reason"], "released")
        self.assertNotIn("failure_disposed", [e["type"] for e in self.load(tid).events])
        self.assertRefusal("confirmation_stale", self.driver.dispose, GROUND, WHY, [token])
        self.assertEqual(self.driver.dispose(GROUND, WHY, [self.token()])["state"], "failed")

    def test_custody_lost_during_an_inspection_refuses_and_a_new_token_disposes(self):
        tid = self.parked()
        token = self.token()
        inspect = self.watch.inspect

        def slow(request):
            self.clock.advance(release_driver.CUSTODY_TTL_MS + 1)
            return inspect(request)

        with mock.patch.object(self.watch, "inspect", slow):
            refusal = self.assertRefusal("custody_lost", self.driver.dispose, GROUND, WHY,
                                         [token])
        self.assertIn("custody has lapsed", refusal.detail)
        self.assertIn("preview the disposition again", refusal.detail)
        held = self.load(tid)
        self.assertEqual((held.state, held.terminal), ("attention_required", None))
        self.assertNotIn("failure_disposed", [e["type"] for e in held.events])
        self.assertRefusal("confirmation_stale", self.driver.dispose, GROUND, WHY, [token])
        self.assertEqual(self.driver.dispose(GROUND, WHY, [self.token()])["state"], "failed")


if __name__ == "__main__":
    unittest.main()
