"""Transaction core slice 6: authority, the failed disposition and its grounds (#209).

Run: just agent-workflow-tests
"""

import copy
import unittest

from agent_tools import (
    transaction_core, transaction_disposition, transaction_history, transaction_storage)
from agent_tools.transaction_core import (
    ACTOR_KINDS, CONSEQUENCES, DISPOSITION_REFUSAL_REASONS, GROUNDS, KNOWN_STATE_GROUNDS,
    OBSERVABILITY_GROUNDS, QUALIFIERS, RESIDUE_BOUNDS, CreationConflict, DispositionRefused,
    StateInvalid, TransitionRefused)

from .test_transaction_custody import (
    AUTHORITY, EMPTY_PROOF, EMPTY_RECOVERY, KEYS, SUBJECT, T0, TTL, CustodyCase, plain)
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
