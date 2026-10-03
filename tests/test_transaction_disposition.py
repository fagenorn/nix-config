"""Transaction core slice 6: authority, the failed disposition and its grounds (#209).

Run: just agent-workflow-tests
"""

import copy
import hashlib
import json
import os
import unittest
import unittest.mock

from agent_tools import (
    transaction_core, transaction_disposition, transaction_history, transaction_receipt,
    transaction_storage)
from agent_tools.transaction_core import (
    ACTOR_KINDS, CONSEQUENCES, DISPOSITION_REFUSAL_REASONS, GROUNDS, HAZARD_SCHEMA,
    KNOWN_STATE_GROUNDS, OBSERVABILITY_GROUNDS, OBSERVATION_SCHEMA, QUALIFIERS, RESIDUE_BOUNDS,
    CreationConflict, DispositionRefused, ReceiptInvalid, StateInvalid, TransitionRefused)

from .test_transaction_custody import (
    AUTHORITY, EMPTY_PROOF, EMPTY_RECOVERY, KEYS, PATH, SUBJECT, T0, TTL, CustodyCase, plain,
    serialize)
from .test_transaction_invocation import FakeEffect
from .test_transaction_receipt import Sealed
from .test_transaction_recovery import RecoveryCase
from .test_transaction_recovery_plan import RECOVERY

OTHER = "rel_01890a5d-ac96-7abc-8def-0123456789ab"


def appended(document, *events):
    """`document` with `events` appended by hand, each stamped with the last `at`."""
    document = copy.deepcopy(document)
    for fields in events:
        document["events"].append({"seq": len(document["events"]) + 1,
                                   "at": document["events"][-1]["at"], **fields})
    document["revision"] = len(document["events"])
    return document


def moved(source, target, reason="r", external_state="known"):
    return {"type": "transitioned", "from": source, "to": target, "reason": reason,
            "external_state": external_state}


class AuthorityTest(CustodyCase):
    def create(self, key="k", authority_class=AUTHORITY):
        return self.store.create(key, SUBJECT, concurrency_keys=KEYS, proof=EMPTY_PROOF,
                                 recovery=EMPTY_RECOVERY, authority_class=authority_class)

    def test_create_stores_a_required_authority_class_and_compares_it(self):
        created = self.create()
        document = self.state_doc(created.transaction_id)
        self.assertEqual((document["schema"], document["events"][0]["authority_class"]),
                         ("transaction-state/v6", AUTHORITY))
        with self.assertRaises(TypeError):
            self.store.create("k2", SUBJECT, concurrency_keys=KEYS, proof=EMPTY_PROOF,
                              recovery=EMPTY_RECOVERY)
        before = self.files()
        for bad in ("", None, 7):
            with self.subTest(bad=bad), self.assertRaises(StateInvalid):
                self.create("k3", authority_class=bad)
        with self.assertRaises(CreationConflict) as caught:
            self.create(authority_class="release:beta")
        self.assertIn("authority class", str(caught.exception))
        self.assertEqual(self.files(), before)
        self.assertEqual(self.create().transaction_id, created.transaction_id)

    def test_a_grant_records_its_actor_kind_and_authority_class(self):
        self.assertEqual(ACTOR_KINDS, ("human", "agent"))
        self.assertIs(transaction_core.ACTOR_KINDS, transaction_history.ACTOR_KINDS)
        custody = self.acquire(self.new())
        after = self.store.issue_grant(custody, grant_id="g", actor="op", actor_kind="human",
                                       authority_class=AUTHORITY)
        event = dict(after.events[-1])
        self.assertEqual((event["actor_kind"], event["authority_class"]), ("human", AUTHORITY))
        self.assertEqual((after.grants[0]["actor_kind"], after.grants[0]["authority_class"]),
                         ("human", AUTHORITY))
        for bad in ({"actor_kind": "robot"}, {"actor_kind": ""}, {"authority_class": ""}):
            arguments = {"actor_kind": "agent", "authority_class": AUTHORITY, **bad}
            with self.subTest(bad=bad):
                self.assertRefusedUnchanged(StateInvalid, lambda: self.store.issue_grant(
                    custody, grant_id="g2", actor="op", **arguments))
        with self.assertRaises(TypeError):
            self.store.issue_grant(custody, grant_id="g3", actor="op")

    def test_hand_edited_authority_fields_are_state_invalid(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.issue_grant(custody, grant_id="g", actor="op", actor_kind="agent",
                               authority_class=AUTHORITY)
        document = self.state_doc(transaction_id)
        grant = len(document["events"]) - 1
        cases = (
            (lambda d: d["events"][0].update(authority_class=""), "authority_class"),
            (lambda d: d["events"][0].pop("authority_class"), "closed created event"),
            (lambda d: d["events"][grant].update(actor_kind="robot"),
             "actor_kind is not human or agent"),
            (lambda d: d["events"][grant].update(authority_class=""), "authority_class"),
            (lambda d: d.update(schema="transaction-state/v5"), "transaction-state/v5"))
        for edit, fragment in cases:
            with self.subTest(fragment=fragment):
                edited = copy.deepcopy(document)
                edit(edited)
                self.assertRuleRefuses(transaction_id, edited, fragment)


class FailedClosedTest(CustodyCase):
    def test_advance_never_enters_failed_nor_writes_the_reserved_reason(self):
        transaction_id = self.new()
        custody = self.acquire(transaction_id)
        self.store.advance(transaction_id, "attention_required", reason="r",
                           external_state="known", custody=custody)
        for target, reason, fragment in (
                ("failed", "r", "failed is entered only through dispose_failed"),
                ("abandoned", "failure_disposed", "reserved reason failure_disposed"),
                ("created", "failure_disposed", "reserved reason failure_disposed")):
            with self.subTest(target=target, reason=reason):
                error = self.assertRefusedUnchanged(TransitionRefused, lambda: self.store.advance(
                    transaction_id, target, reason=reason, external_state="known",
                    custody=custody))
                self.assertIn(fragment, str(error))

    def test_a_hand_built_failed_or_reserved_reason_is_state_invalid(self):
        transaction_id = self.new()
        document = self.state_doc(transaction_id)
        cases = (
            ((moved("created", "attention_required"),
              moved("attention_required", "failed", "failure_disposed")),
             "transition into failed does not immediately follow failure_disposed"),
            ((moved("created", "attention_required"), moved("attention_required", "failed")),
             "transition into failed does not immediately follow failure_disposed"),
            ((moved("created", "abandoned", "failure_disposed"),),
             "reserved reason failure_disposed does not immediately follow its event"))
        for events, fragment in cases:
            with self.subTest(fragment=fragment):
                edited = appended(document, *events)
                last = edited["events"][-1]["to"]
                edited.update(state=last,
                              parked_from="created" if last == "attention_required" else None)
                self.assertRuleRefuses(transaction_id, edited, fragment)


def destroyed(unit):
    return {"unit": unit, "consequence": "effects_destroyed_with_authority",
            "residue_bound": None, "recheck": None}


def live(unit, bound="unbounded"):
    return {"unit": unit, "consequence": "effects_possibly_live_unobservable",
            "residue_bound": bound, "recheck": "re-read the target once authority returns"}


class DisposeCase(Sealed, RecoveryCase):
    def disposition(self, ground="no_recovery_path", **fields):
        return {"ground": ground, "reference": f"ops://{ground}", "occurred_at": None,
                "successor": None, "units": [], **fields}

    def unobservable(self, units=None, occurred_at=T0 - 1, **fields):
        build, start = self.act("build", n=1), self.act("start", n=2)
        return self.disposition("authority_retired", occurred_at=occurred_at,
                                units=[destroyed(build), live(start)] if units is None
                                else units, **fields)

    def dispose(self, grant_id="g-1", disposition=None, **fields):
        return self.store.dispose_failed(
            self.custody, grant_id=grant_id,
            disposition=self.disposition(**fields) if disposition is None else disposition)

    def human(self, grant_id="h-1", authority_class=AUTHORITY):
        return self.store.issue_grant(self.custody, grant_id=grant_id, actor="operator",
                                      actor_kind="human", authority_class=authority_class)

    def declined(self, reason, call):
        error = self.assertRefusedUnchanged(DispositionRefused, call)
        self.assertEqual(error.reason, reason)
        self.assertIn(self.transaction_id, str(error))
        return error

    def succeeded(self, transaction_id):
        custody = self.acquire(transaction_id)
        for target in ("awaiting_verification", "ready", "publishing", "published", "proving"):
            self.store.advance(transaction_id, target, reason="r", external_state="known",
                               custody=custody)
        self.store.start_cohort(custody)
        return self.store.settle_proof(custody)


# Every reason some `declined(...)` call in this file asserts; pinned to the vocabulary.
OBSERVED_REASONS = {"state_not_attention", "grant_required", "malformed", "no_effect",
                    "reconciliation_required", "effect_uncertain", "successor_not_succeeded",
                    "human_required", "authority_class_mismatch", "units_mismatch",
                    "inspection_not_exhausted"}


class DisposeTest(DisposeCase):
    def test_the_vocabularies_are_exactly_the_specified_ones(self):
        self.assertEqual(GROUNDS, KNOWN_STATE_GROUNDS + OBSERVABILITY_GROUNDS)
        self.assertEqual(KNOWN_STATE_GROUNDS, ("successor_succeeded", "no_recovery_path"))
        self.assertEqual(OBSERVABILITY_GROUNDS, (
            "authority_retired", "tenancy_destroyed", "host_decommissioned",
            "credential_class_revoked_without_successor", "subject_scope_erased"))
        self.assertEqual(CONSEQUENCES, ("effects_destroyed_with_authority",
                                        "effects_possibly_live_unobservable"))
        self.assertEqual(QUALIFIERS, ("final_state_known", "effects_unobservable"))
        self.assertEqual(RESIDUE_BOUNDS, ("bounded", "unbounded"))
        self.assertEqual(DISPOSITION_REFUSAL_REASONS, (
            "state_not_attention", "grant_required", "malformed", "no_effect",
            "reconciliation_required", "effect_uncertain", "successor_not_succeeded",
            "human_required", "authority_class_mismatch", "units_mismatch",
            "inspection_not_exhausted"))
        self.assertEqual(OBSERVED_REASONS, set(DISPOSITION_REFUSAL_REASONS))
        self.assertIs(DispositionRefused, transaction_storage.DispositionRefused)
        self.assertIs(GROUNDS, transaction_disposition.GROUNDS)
        with self.assertRaises(ValueError):
            transaction_disposition.disposition_refused("rel_x", "vibes", "d")

    def test_no_recovery_path_fails_with_a_sealed_known_state_receipt(self):
        self.parked()
        self.grant()
        after = self.dispose()
        self.assertEqual([e["type"] for e in after.events[-4:]],
                         ["failure_disposed", "transitioned", "lease_released", "receipt_sealed"])
        disposed, moved = dict(after.events[-4]), dict(after.events[-3])
        self.assertEqual((moved["from"], moved["to"], moved["reason"], moved["external_state"]),
                         ("attention_required", "failed", "failure_disposed", "known"))
        snapshot = {self.act("build", n=1): "target_satisfied",
                    self.act("start", n=2): "diverged"}
        self.assertEqual({k: v for k, v in disposed.items() if k not in ("seq", "type", "at")}, {
            "grant_id": "g-1", "ground": "no_recovery_path",
            "reference": "ops://no_recovery_path", "occurred_at": None, "successor": None,
            "successor_receipt": None, "qualifier": "final_state_known",
            "effect_snapshot": snapshot, "units": [], "fence": plain(self.custody.fence)})
        receipt = self.assertSealed(after, "failed", qualifier="final_state_known")
        self.assertEqual(receipt["outcome_proof"], {
            "disposition_seq": disposed["seq"], "ground": "no_recovery_path",
            "ground_reference": "ops://no_recovery_path", "ground_occurred_at": None,
            "successor": None, "successor_receipt": None, "effect_snapshot": snapshot,
            "units": []})
        self.assertFalse((self.root / "hazards").exists())

    def test_state_grant_shape_and_effect_refusals_come_first(self):
        self.published()
        self.grant()
        self.declined("state_not_attention", self.dispose)
        self.to("attention_required")
        self.declined("grant_required", self.dispose)
        self.grant("g-2")
        build = self.act("build", n=1)
        for shape in (["not", "an", "object"], {**self.disposition(), "extra": 1},
                      self.disposition("vibes"), self.disposition(reference=""),
                      self.disposition(occurred_at=T0 - 1), self.disposition(successor=OTHER),
                      self.disposition(units=[destroyed(build)]),
                      self.disposition("successor_succeeded"),
                      self.disposition("authority_retired", units=[destroyed(build)]),
                      self.unobservable(occurred_at=T0 + 1), self.unobservable(occurred_at=True),
                      self.unobservable(successor=OTHER),
                      self.unobservable(units=[{**destroyed(build), "consequence": "gone"}]),
                      self.unobservable(units=[{**destroyed(build), "residue_bound": "bounded"}]),
                      self.unobservable(units=[live(build, bound="some")]),
                      self.unobservable(units=[{**live(build), "recheck": ""}]),
                      self.unobservable(units=[destroyed(build), destroyed(build)])):
            with self.subTest(shape=shape):
                self.declined("malformed", lambda: self.dispose("g-2", disposition=shape))
        self.start_with(RECOVERY, key="bare", keys=("key:bare",))
        self.to("attention_required")
        self.grant()
        self.declined("no_effect", self.dispose)

    def test_an_inspection_under_an_older_fence_needs_reconciliation(self):
        self.parked()
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id, executor="exec-b")
        self.grant()
        self.declined("reconciliation_required", self.dispose)

    def test_an_uncertain_effect_never_becomes_a_known_state_failure(self):
        self.parked(start="unknown")
        self.grant()
        self.declined("effect_uncertain", self.dispose)
        self.start_with(RECOVERY, key="flight", keys=("key:flight",))
        self.parked(start="in_progress")
        self.human()
        self.declined("effect_uncertain", lambda: self.dispose(
            "h-1", disposition=self.unobservable()))

    def test_an_observability_ground_needs_a_human_at_the_class_and_exhausted_units(self):
        self.parked(start="unknown")
        self.grant()
        start = self.act("start", n=2)
        self.declined("human_required", lambda: self.dispose(disposition=self.unobservable()))
        self.human("h-beta", authority_class="release:beta")
        self.declined("authority_class_mismatch", lambda: self.dispose(
            "h-beta", disposition=self.unobservable()))
        self.human()
        self.declined("units_mismatch", lambda: self.dispose(
            "h-1", disposition=self.unobservable(units=[live(start)])))
        self.declined("inspection_not_exhausted", lambda: self.dispose(
            "h-1", disposition=self.unobservable(occurred_at=T0)))
        self.start_with(RECOVERY, key="seen", keys=("key:seen",))
        self.parked()
        self.human()
        self.declined("inspection_not_exhausted", lambda: self.dispose(
            "h-1", disposition=self.unobservable()))

    def test_successor_succeeded_needs_a_linked_child_that_succeeded(self):
        self.parked()
        self.grant()
        child = self.store.roll_forward(
            self.custody, grant_id="g-1", reason="unit_not_restorable", creation_key="forward",
            subject={**SUBJECT, "candidate": "sha256:def"}, concurrency_keys=("target:beta",),
            proof=EMPTY_PROOF, recovery=EMPTY_RECOVERY, authority_class=AUTHORITY)
        stranger = self.store.create(
            "stranger", SUBJECT, concurrency_keys=("target:gamma",), proof=EMPTY_PROOF,
            recovery=EMPTY_RECOVERY, authority_class=AUTHORITY).transaction_id
        self.succeeded(stranger)
        for successor in (child.transaction_id, stranger, OTHER):
            with self.subTest(successor=successor):
                self.declined("successor_not_succeeded", lambda: self.dispose(
                    ground="successor_succeeded", successor=successor))
        finished = self.succeeded(child.transaction_id)
        after = self.dispose(ground="successor_succeeded", successor=child.transaction_id)
        disposed = next(dict(e) for e in after.events if e["type"] == "failure_disposed")
        self.assertEqual((disposed["successor"], disposed["successor_receipt"]),
                         (child.transaction_id, finished.terminal["receipt_digest"]))
        receipt = self.assertSealed(after, "failed", qualifier="final_state_known")
        self.assertEqual(receipt["outcome_proof"]["successor_receipt"],
                         finished.terminal["receipt_digest"])

    def test_the_successor_named_at_entry_is_the_one_whose_success_is_cited(self):
        self.parked()
        self.grant()
        first, second = (self.store.roll_forward(
            self.custody, grant_id="g-1", reason="unit_not_restorable", creation_key=key,
            subject={**SUBJECT, "candidate": "sha256:def"}, concurrency_keys=(f"target:{key}",),
            proof=EMPTY_PROOF, recovery=EMPTY_RECOVERY, authority_class=AUTHORITY
        ).transaction_id for key in ("first", "second"))
        finished = self.succeeded(first)
        disposition = self.disposition("successor_succeeded", successor=first)
        real_load = self.store.load

        def load_then_rename(transaction_id):
            loaded = real_load(transaction_id)
            disposition["successor"] = second
            return loaded

        with unittest.mock.patch.object(self.store, "load", load_then_rename):
            after = self.dispose(disposition=disposition)
        disposed = next(dict(e) for e in after.events if e["type"] == "failure_disposed")
        self.assertEqual((disposed["successor"], disposed["successor_receipt"]),
                         (first, finished.terminal["receipt_digest"]))

    def test_an_unknown_action_no_unit_can_name_is_uncertain_under_every_ground(self):
        self.published()
        self.to("published", "activating")
        self.run_action("start", {"n": 2}, "unknown")
        self.store.inspect_action(self.custody, name="pin", parameters={"n": 3},
                                  effect=FakeEffect(self.world, inspect_outcome="unknown"))
        self.to("attention_required")
        self.human()
        error = self.declined("effect_uncertain", lambda: self.dispose(
            "h-1", disposition=self.unobservable()))
        self.assertIn(self.act("pin", n=3), str(error))

    def test_hand_edited_dispositions_are_state_invalid(self):
        self.parked()
        self.grant()
        self.dispose()
        document = self.state_doc(self.transaction_id)
        index = next(i for i, e in enumerate(document["events"])
                     if e["type"] == "failure_disposed")
        start = self.act("start", n=2)
        cases = (
            (lambda e: e.update(qualifier="effects_unobservable"),
             "failure_disposed does not match its re-derivation: qualifier"),
            (lambda e: e["effect_snapshot"].update({start: "no_effect"}),
             "failure_disposed does not match its re-derivation: effect_snapshot"),
            (lambda e: e.update(grant_id="g-9"), "failure_disposed grant_required"),
            (lambda e: e.update(ground="vibes"), "failure_disposed malformed"),
            (lambda e: e.update(successor_receipt="sha256:" + "0" * 64),
             "failure_disposed successor_receipt is not null or a receipt digest"),
            (lambda e: e.pop("units"), "closed failure_disposed event"))
        for edit, fragment in cases:
            with self.subTest(fragment=fragment):
                edited = copy.deepcopy(document)
                edit(edited["events"][index])
                self.assertRuleRefuses(self.transaction_id, edited, fragment)


class UnobservableTest(DisposeCase):
    def unobservable_failure(self):
        self.parked(start="unknown")
        self.human()
        after = self.dispose("h-1", disposition=self.unobservable())
        return after, after.terminal["receipt_digest"]

    def marker(self, key, digest):
        return (self.root / "hazards" / hashlib.sha256(key.encode()).hexdigest()
                / (digest.removeprefix("sha256:") + ".json"))

    def test_an_unobservable_disposition_seals_its_qualifier_and_marks_every_key(self):
        after, digest = self.unobservable_failure()
        receipt = self.assertSealed(after, "failed", qualifier="effects_unobservable")
        disposed = next(dict(e) for e in after.events if e["type"] == "failure_disposed")
        start = self.act("start", n=2)
        self.assertEqual(disposed["effect_snapshot"][start], "unknown")
        self.assertEqual(receipt["outcome_proof"]["units"], disposed["units"])
        self.assertEqual(receipt["outcome_proof"]["ground_occurred_at"], T0 - 1)
        moved = [e for e in after.events if e["type"] == "transitioned"][-1]
        self.assertEqual((moved["to"], moved["external_state"]), ("failed", "known"))
        self.assertEqual(HAZARD_SCHEMA, "transaction-hazard-marker/v1")
        self.assertIs(HAZARD_SCHEMA, transaction_receipt.HAZARD_SCHEMA)
        for key in KEYS:
            with self.subTest(key=key):
                self.assertEqual(self.store.hazard_markers(key), (digest,))
                self.assertEqual(json.loads(self.marker(key, digest).read_text()),
                                 {"schema": HAZARD_SCHEMA, "key": key, "receipt_digest": digest})
        self.assertEqual(self.store.hazard_markers("key:unmarked"), ())
        with self.assertRaises(StateInvalid):
            self.store.hazard_markers("")

    def test_every_unit_destroyed_seals_final_state_known_and_marks_nothing(self):
        self.parked()
        self.human()
        build, start = self.act("build", n=1), self.act("start", n=2)
        after = self.dispose("h-1", disposition=self.unobservable(
            units=[destroyed(build), destroyed(start)]))
        self.assertSealed(after, "failed", qualifier="final_state_known")
        self.assertFalse((self.root / "hazards").exists())
        self.assertEqual(self.store.hazard_markers(KEYS[0]), ())

    def test_post_terminal_observations_sit_beside_the_receipt_and_change_nothing(self):
        after, digest = self.unobservable_failure()
        receipt_path = self.root / "receipts" / (digest.removeprefix("sha256:") + ".json")
        before = (receipt_path.read_bytes(), self.state_doc(self.transaction_id))
        self.clock.advance(5)
        seen = {"outcome": "satisfied", "reason": "residue gone", "reference": "ops://recheck/1"}
        first = self.store.record_post_terminal(digest, observation=seen,
                                                contradicts_ground=False)
        second = self.store.record_post_terminal(
            digest, observation={**seen, "outcome": "unsatisfied"}, contradicts_ground=True)
        self.assertEqual((first["n"], second["n"]), (1, 2))
        self.assertEqual(OBSERVATION_SCHEMA, "transaction-post-terminal-observation/v1")
        listed = [dict(o) for o in self.store.post_terminal_observations(digest)]
        self.assertEqual(listed, [dict(first), dict(second)])
        self.assertEqual(listed[0], {
            "schema": OBSERVATION_SCHEMA, "receipt_digest": digest, "n": 1, "at": first["at"],
            "outcome": "satisfied", "reason": "residue gone", "reference": "ops://recheck/1",
            "contradicts_ground": False})
        self.assertGreater(first["at"], after.events[-1]["at"])
        self.assertTrue((self.root / "observations" / digest.removeprefix("sha256:")
                         / "2.json").is_file())
        self.assertEqual((receipt_path.read_bytes(), self.state_doc(self.transaction_id)),
                         before)
        self.assertEqual(self.store.load(self.transaction_id).state, "failed")

    def test_a_bad_post_terminal_observation_is_refused_before_any_write(self):
        after, digest = self.unobservable_failure()
        seen = {"outcome": "satisfied", "reason": "r", "reference": "ops://x"}
        for observation, contradicts in (({**seen, "extra": 1}, False),
                                         ({**seen, "outcome": "maybe"}, False),
                                         (seen, "yes")):
            with self.subTest(observation=observation, contradicts=contradicts):
                self.assertRefusedUnchanged(StateInvalid, lambda: self.store.record_post_terminal(
                    digest, observation=observation, contradicts_ground=contradicts))
        with self.assertRaises(ReceiptInvalid):
            self.store.record_post_terminal("sha256:" + "0" * 64, observation=seen,
                                            contradicts_ground=False)
        self.start_with(RECOVERY, key="known", keys=("key:known",))
        self.parked()
        self.grant()
        known = self.dispose().terminal["receipt_digest"]
        self.assertRefusedUnchanged(StateInvalid, lambda: self.store.record_post_terminal(
            known, observation=seen, contradicts_ground=True))
        self.assertEqual(self.store.record_post_terminal(
            known, observation=seen, contradicts_ground=False)["n"], 1)

    def test_a_tampered_marker_or_observation_fails_its_listing(self):
        after, digest = self.unobservable_failure()
        seen = {"outcome": "satisfied", "reason": "r", "reference": "ops://x"}
        self.store.record_post_terminal(digest, observation=seen, contradicts_ground=False)
        observation = (self.root / "observations" / digest.removeprefix("sha256:") / "1.json")
        for path, listing in ((self.marker(KEYS[0], digest),
                               lambda: self.store.hazard_markers(KEYS[0])),
                              (observation,
                               lambda: self.store.post_terminal_observations(digest))):
            with self.subTest(path=path.name):
                os.chmod(path, 0o644)
                document = json.loads(path.read_text())
                document["receipt_digest"] = "sha256:" + "1" * 64
                path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
                with self.assertRaises(ReceiptInvalid):
                    listing()

    def test_a_canonically_reserialized_bad_observation_value_fails_its_listing(self):
        self.parked()
        self.grant()
        known = self.dispose().terminal["receipt_digest"]
        seen = {"outcome": "satisfied", "reason": "r", "reference": "ops://x"}
        self.store.record_post_terminal(known, observation=seen, contradicts_ground=False)
        path = self.root / "observations" / known.removeprefix("sha256:") / "1.json"
        original = json.loads(path.read_text())
        os.chmod(path, 0o644)
        for edit in ({"outcome": "maybe"}, {"contradicts_ground": "yes"},
                     {"contradicts_ground": True}, {"at": "2027-13-01T08:00:00.000Z"},
                     {"at": "yesterday"}):
            with self.subTest(edit=edit):
                path.write_text(serialize({**original, **edit}))
                with self.assertRaises(ReceiptInvalid):
                    self.store.post_terminal_observations(known)
        path.write_text(serialize(original))
        self.assertEqual([dict(o) for o in self.store.post_terminal_observations(known)],
                         [original])

    def test_a_marker_failure_leaves_no_terminal_and_a_retry_succeeds(self):
        self.parked(start="unknown")
        self.human()
        disposition = self.unobservable()
        obstruction = self.root / "hazards" / hashlib.sha256(KEYS[0].encode()).hexdigest()
        obstruction.parent.mkdir()
        obstruction.write_text("not a directory\n")
        guarded = lambda: {name: raw for name, raw in self.files().items()  # noqa: E731
                           if name.startswith("leases") or name.endswith("state.json")}
        before = guarded()
        with self.assertRaises(ReceiptInvalid):
            self.store.dispose_failed(self.custody, grant_id="h-1", disposition=disposition)
        self.assertEqual(guarded(), before)
        self.assertNotIn("receipt_sealed", self.types(self.transaction_id))
        self.assertEqual(self.store.load(self.transaction_id).state, "attention_required")
        obstruction.unlink()
        after = self.store.dispose_failed(self.custody, grant_id="h-1", disposition=disposition)
        digest = after.terminal["receipt_digest"]
        self.assertSealed(after, "failed", qualifier="effects_unobservable")
        for key in KEYS:
            with self.subTest(key=key):
                self.assertEqual(self.store.hazard_markers(key), (digest,))

    def test_a_result_after_the_seal_is_a_post_terminal_observation_not_a_ledger_write(self):
        after, digest = self.unobservable_failure()
        self.assertRefusedUnchanged(TransitionRefused, lambda: self.store.record_owner_result(
            self.transaction_id, executor_id="exec-a", subject_path=PATH,
            fence=plain(self.custody.fence), result={"late": True}))
        record = self.store.record_post_terminal(
            digest, observation={"outcome": "satisfied", "reason": "late owner result",
                                 "reference": "owner://exec-a"}, contradicts_ground=False)
        self.assertEqual(record["receipt_digest"], digest)
