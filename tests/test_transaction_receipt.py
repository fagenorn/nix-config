"""Transaction core slice 6: terminal receipts (#209).

Run: just agent-workflow-tests
"""

import hashlib
import json
import os
import stat
import tempfile
import unittest

from agent_tools import transaction_core, transaction_receipt, transaction_storage
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import RECEIPT_SCHEMA, ReceiptInvalid, StateInvalid

from .test_transaction_custody import AUTHORITY, KEYS, PATH, SUBJECT, TTL, CustodyCase, plain, serialize
from .test_transaction_invocation import FakeEffect, FakeWorld
from .test_transaction_proof import CohortCase, Observer
from .test_transaction_recovery_plan import inert_recovery
from .test_transaction_recovery_settle import SettleCase

ENVELOPE = {"schema", "transaction_id", "creation_key", "recovers", "authority_class",
            "concurrency_keys", "subject_digest", "proof_plan_digest", "recovery_plan_digest",
            "outcome", "terminal_qualifier", "sealed_at", "revision", "history_digest",
            "outcome_proof"}
TRUTH = {"postconditions", "stops", "owner_results", "evaluations"}


class Sealed:
    """Assertions over the one receipt a terminal snapshot sealed, read from its file."""

    def receipt_files(self):
        directory = self.root / "receipts"
        return sorted(directory.iterdir()) if directory.is_dir() else []

    def assertSealed(self, after, outcome, qualifier=None):
        seal = dict(after.events[-1])
        self.assertEqual((after.state, seal["type"]), (outcome, "receipt_sealed"))
        digest = seal["receipt_digest"]
        path = self.root / "receipts" / (digest.removeprefix("sha256:") + ".json")
        self.assertIn(path, self.receipt_files())
        raw = path.read_bytes()
        self.assertEqual("sha256:" + hashlib.sha256(raw[:-1]).hexdigest(), digest)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
        receipt = self.store.read_receipt(digest)
        self.assertEqual(serialize(dict(receipt)).encode(), raw)
        self.assertEqual(set(receipt), ENVELOPE | TRUTH)
        events = [dict(e) for e in after.events[:-1]]
        created = events[0]
        at = [e for e in events if e["type"] == "transitioned"][-1]["at"]
        self.assertEqual(seal["at"], at)
        self.assertEqual(
            {k: receipt[k] for k in ENVELOPE - {"outcome_proof"}},
            {"schema": RECEIPT_SCHEMA, "transaction_id": after.transaction_id,
             "creation_key": after.creation_key, "recovers": created["recovers"],
             "authority_class": created["authority_class"],
             "concurrency_keys": list(after.concurrency_keys),
             "subject_digest": telemetry_digest(dict(after.subject)),
             "proof_plan_digest": created["proof_plan_digest"],
             "recovery_plan_digest": created["recovery_plan_digest"], "outcome": outcome,
             "terminal_qualifier": qualifier, "sealed_at": at, "revision": len(events),
             "history_digest": telemetry_digest(events)})
        self.assertEqual(dict(after.terminal), {"receipt_digest": digest, "outcome": outcome,
                                                "terminal_qualifier": qualifier})
        self.assertEqual(dict(self.store.load(after.transaction_id).terminal),
                         dict(after.terminal))
        return receipt


class SucceededReceiptTest(Sealed, CohortCase):
    def test_success_seals_the_proof_seal_as_its_outcome_proof(self):
        self.ready()
        self.start()
        self.members()
        after = self.settle()
        receipt = self.assertSealed(after, "succeeded")
        self.assertEqual(len(self.receipt_files()), 1)
        seal = next(dict(e) for e in after.events if e["type"] == "proof_sealed")
        self.assertEqual(receipt["outcome_proof"], {
            "proof_sealed_seq": seal["seq"], "proof_cutoff_at": seal["proof_cutoff_at"],
            "advisory_warnings": seal["advisory_warnings"]})


class RolledBackReceiptTest(Sealed, SettleCase):
    def test_rollback_seals_its_snapshot_selection_restores_and_residue(self):
        self.recovering()
        self.all_edges()
        after = self.settle()
        receipt = self.assertSealed(after, "rolled_back")
        started = [dict(e) for e in after.events if e["type"] == "recovery_started"][-1]
        settled = next(dict(e) for e in after.events if e["type"] == "recovery_settled")
        self.assertEqual(receipt["outcome_proof"], {
            "recovery_settled_seq": settled["seq"], "effect_snapshot": started["effect_snapshot"],
            "selected": started["selected"], "restored": settled["restored"],
            "residue": settled["residue"]})


class AbandonedReceiptTest(Sealed, CustodyCase):
    def abandon(self, transaction_id, custody=None):
        return self.store.advance(transaction_id, "abandoned", reason="r",
                                  external_state="known", custody=custody)

    def test_abandoning_seals_every_actions_effect_class(self):
        transaction_id = self.new()
        self.assertIsNone(self.store.load(transaction_id).terminal)
        receipt = self.assertSealed(self.abandon(transaction_id), "abandoned")
        self.assertEqual((receipt["outcome_proof"], receipt["authority_class"]),
                         ({"effect_snapshot": {}}, AUTHORITY))
        other = self.new("inspected", keys=("key:inspected",))
        custody = self.acquire(other)
        for target in ("awaiting_verification", "ready", "publishing"):
            self.store.advance(other, target, reason="r", external_state="known",
                               custody=custody)
        inspected = self.store.inspect_action(custody, name="build", parameters={"n": 1},
                                              effect=FakeEffect(FakeWorld()))
        self.store.advance(other, "attention_required", reason="r", external_state="known",
                           custody=custody)
        after = self.abandon(other, custody)
        self.assertEqual([e["type"] for e in after.events[-3:]],
                         ["transitioned", "lease_released", "receipt_sealed"])
        digest = after.terminal["receipt_digest"]
        self.assertEqual(self.store.read_receipt(digest)["outcome_proof"],
                         {"effect_snapshot": {inspected.actions[0]["action_id"]: "no_effect"}})

    def test_an_altered_or_missing_receipt_fails_every_load(self):
        self.assertTrue(issubclass(ReceiptInvalid, StateInvalid))
        transaction_id = self.new()
        self.abandon(transaction_id)
        [path] = self.receipt_files()
        receipt = json.loads(path.read_text())
        os.chmod(path, 0o644)
        for content in (serialize({**receipt, "revision": 99}), serialize(receipt) + " ", None):
            with self.subTest(content=content):
                if content is None:
                    path.unlink()
                else:
                    path.write_text(content)
                for call in (lambda: self.store.load(transaction_id),
                             lambda: self.abandon(transaction_id), self.new):
                    with self.assertRaises(ReceiptInvalid) as caught:
                        call()
                    self.assertIn(path.name, str(caught.exception))

    def test_a_broken_receipts_path_refuses_the_seal_leaving_the_state_nonterminal(self):
        receipts = self.root / "receipts"
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        self.addCleanup(lambda: receipts.is_dir() and os.chmod(receipts, 0o700))
        setups = {
            "file": (lambda: receipts.write_text("x"), receipts.unlink),
            "symlink": (lambda: receipts.symlink_to(elsewhere.name), receipts.unlink),
            "unwritable": (lambda: (receipts.mkdir(), os.chmod(receipts, 0o500)),
                           lambda: (os.chmod(receipts, 0o700), receipts.rmdir()))}
        for name, (arrange, restore) in setups.items():
            with self.subTest(name=name):
                transaction_id = self.new(name, keys=(f"key:{name}",))
                arrange()
                self.assertRefusedUnchanged(ReceiptInvalid,
                                            lambda: self.abandon(transaction_id))
                persisted = self.store.load(transaction_id)
                self.assertEqual((persisted.state, persisted.terminal), ("created", None))
                restore()
        self.assertEqual(os.listdir(elsewhere.name), [])

    def test_hand_edited_seals_are_state_invalid(self):
        transaction_id = self.new()
        self.abandon(transaction_id)
        document = self.state_doc(transaction_id)
        seal = document["events"][-1]

        def dropped(d):
            d["events"].pop()
            d["revision"] -= 1

        def doubled(d):
            d["events"].append({**seal, "seq": seal["seq"] + 1})
            d["revision"] += 1

        cases = (
            (lambda d: d["events"][-1].update(receipt_digest="sha256:" + "0" * 64),
             "receipt_sealed receipt_digest is not the digest of the terminal receipt"),
            (lambda d: d["events"][-1].update(at="2030-01-01T00:00:00.000Z"),
             "receipt_sealed at is not the terminal transition's at"),
            (lambda d: d["events"][-1].update(extra=1), "closed receipt_sealed event"),
            (dropped, "terminal state abandoned has no receipt_sealed as its last event"),
            (doubled, f"event {seal['seq'] + 1} follows the terminal state abandoned"))
        for edit, fragment in cases:
            with self.subTest(fragment=fragment):
                edited = json.loads(json.dumps(document))
                edit(edited)
                self.assertRuleRefuses(transaction_id, edited, fragment)
        open_id = self.new("open", keys=("key:open",))
        opened = self.state_doc(open_id)
        opened["events"].append({**seal, "seq": 2})
        opened["revision"] = 2
        self.assertRuleRefuses(open_id, opened, "receipt_sealed outside a terminal state")

    def test_read_receipt_refuses_an_unknown_or_malformed_digest(self):
        for digest in ("sha256:" + "0" * 64, "sha256:XYZ", "nope", 7):
            with self.subTest(digest=digest), self.assertRaises(ReceiptInvalid):
                self.store.read_receipt(digest)

    def test_the_receipt_names_are_re_exported(self):
        self.assertEqual(RECEIPT_SCHEMA, "transaction-terminal-receipt/v1")
        self.assertIs(transaction_core.RECEIPT_SCHEMA, transaction_receipt.RECEIPT_SCHEMA)
        self.assertIs(ReceiptInvalid, transaction_storage.ReceiptInvalid)


DC = {"basis": "deterministic", "max_collection_latency_ms": 30_000,
      "predicates": ["publication_visible", "running_subject_identity"]}
DELIVERY = {"collectors": {"c": DC}, "obligations": [], "units": [
    {"name": "deliver_implementation", "parameters": {"n": 1}, "phase": "publication",
     "collector": "c"},
    {"name": "merge_change", "parameters": {"n": 2}, "phase": "activation", "collector": "c"},
    {"name": "close_issue", "parameters": {"n": 3}, "phase": "activation", "collector": "c"},
    {"name": "clean_up", "parameters": {"n": 4}, "phase": "activation", "collector": "c"}]}


class SucceededTruthTest(Sealed, CohortCase):
    def test_success_records_the_final_evaluations_with_their_evidence(self):
        self.ready()
        self.start()
        self.members()
        after = self.settle()
        receipt = self.assertSealed(after, "succeeded")
        latest = {e["obligation_id"]: e["evidence_id"] for e in after.events
                  if e["type"] == "obligation_observed"}
        expected = [{"obligation_id": i, "evaluation": "accepted", "reason": "ok",
                     "evidence_id": latest[i]} for i in self.ids[:2] + ["migrated", "health",
                                                                        "smoke"]]
        expected += [{"obligation_id": "vibe", "evaluation": "indeterminate",
                      "reason": "evidence_missing", "evidence_id": None},
                     {"obligation_id": "uptime", "evaluation": "unsupported",
                      "reason": "predicate_unsupported", "evidence_id": None}]
        self.assertEqual(sorted(receipt["evaluations"], key=lambda e: e["obligation_id"]),
                         sorted(expected, key=lambda e: e["obligation_id"]))
        self.assertEqual([e["obligation_id"] for e in receipt["evaluations"]], self.ids)
        self.assertEqual((receipt["stops"], receipt["owner_results"]), ([], []))


class DeliveryCase(Sealed, CustodyCase):
    """A delivery-shaped declaration: one publication unit and three activation units."""

    def setUp(self):
        super().setUp()
        self.world = FakeWorld()
        self.transaction_id = self.store.create(
            "delivery", SUBJECT, concurrency_keys=KEYS, proof=DELIVERY,
            recovery=inert_recovery(DELIVERY), authority_class=AUTHORITY).transaction_id
        self.custody = self.acquire(self.transaction_id)
        self.plan = self.store.load(self.transaction_id).proof_plan

    def to(self, *targets):
        for target in targets:
            after = self.store.advance(self.transaction_id, target, reason="r",
                                       external_state="known", custody=self.custody)
        return after

    def unit(self, name, externally_satisfied=False):
        parameters = next(u["parameters"] for u in DELIVERY["units"] if u["name"] == name)
        if externally_satisfied:
            return self.store.inspect_action(
                self.custody, name=name, parameters=parameters,
                effect=FakeEffect(self.world, inspect_outcome="satisfied"))
        for operation in (self.store.inspect_action, self.store.invoke_action):
            after = operation(self.custody, name=name, parameters=parameters,
                              effect=FakeEffect(self.world))
        return after

    def observed(self, activation, externally=()):
        self.to("awaiting_verification", "ready", "publishing")
        self.unit("deliver_implementation")
        self.to("published", "activating")
        for name in activation:
            self.unit(name, name in externally)
        return self.to("proving")

    def collect_stale(self):
        for entry in self.store.load(self.transaction_id).proof["obligations"]:
            if entry["latest_admissible"] is not True:
                self.store.collect_obligation(self.custody, obligation_id=entry["obligation_id"],
                                              observer=Observer(self.clock))

    def sealed(self):
        """Collect, open one cohort, collect its members and settle into `succeeded`."""
        self.collect_stale()
        started = self.store.start_cohort(self.custody)
        for member in started.proof_plan["cohort"]["members"]:
            self.store.collect_obligation(self.custody, obligation_id=member,
                                          observer=Observer(self.clock))
        before = self.state_doc(self.transaction_id)["events"]
        after = self.store.settle_proof(self.custody)
        final = self.state_doc(self.transaction_id)["events"]
        self.assertEqual([serialize(e) for e in final[:len(before)]],
                         [serialize(e) for e in before])
        return self.assertSealed(after, "succeeded"), after

    def assertPostconditions(self, receipt, after, externally=()):
        units = self.plan["units"]
        self.assertEqual([p["unit"] for p in receipt["postconditions"]],
                         [u["action_id"] for u in units])
        for entry, unit in zip(receipt["postconditions"], units):
            seen = [dict(e) for e in after.events if e["type"] == "action_inspected"
                    and e["action_id"] == unit["action_id"] and e["outcome"] == "satisfied"][-1]
            self.assertEqual(entry, {
                "unit": unit["action_id"], "name": unit["name"], "phase": unit["phase"],
                "status": "satisfied",
                "observed": {"seq": seen["seq"], "at": seen["at"],
                             "reference": seen["reference"], "fence": seen["fence"]},
                "effected": unit["name"] not in externally})


class PostconditionTest(DeliveryCase):
    def test_merge_before_close_records_every_unit_observed_and_effected(self):
        self.observed(["merge_change", "close_issue", "clean_up"])
        receipt, after = self.sealed()
        self.assertPostconditions(receipt, after)
        self.assertEqual(len(self.receipt_files()), 1)

    def test_close_before_merge_records_the_closed_target_observed_but_not_effected(self):
        self.observed(["close_issue", "merge_change", "clean_up"], externally={"close_issue"})
        receipt, after = self.sealed()
        self.assertPostconditions(receipt, after, externally={"close_issue"})
        close = next(p for p in receipt["postconditions"] if p["name"] == "close_issue")
        merge = next(p for p in receipt["postconditions"] if p["name"] == "merge_change")
        self.assertLess(close["observed"]["seq"], merge["observed"]["seq"])
        self.assertEqual(len(self.receipt_files()), 1)

    def test_evidence_voided_by_a_lapse_is_recollected_and_cited(self):
        self.observed(["merge_change", "close_issue", "clean_up"])
        self.collect_stale()
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        lapse = self.store.load(self.transaction_id).revision
        self.custody = self.acquire(self.transaction_id, executor="exec-b")
        self.to("proving")
        receipt, after = self.sealed()
        self.assertPostconditions(receipt, after)
        observed = {e["evidence_id"]: e["seq"] for e in after.events
                    if e["type"] == "obligation_observed"}
        snapshots = [o["obligation_id"] for o in self.plan["obligations"]
                     if o["form"] == "snapshot"]
        self.assertTrue(snapshots)
        for entry in receipt["evaluations"]:
            self.assertEqual(entry["evaluation"], "accepted")
            if entry["obligation_id"] in snapshots:
                self.assertGreater(observed[entry["evidence_id"]], lapse)
        [stop] = receipt["stops"]
        self.assertEqual((stop["executor_id"], stop["superseded_by"]), ("exec-a", None))
        self.assertEqual(len(self.receipt_files()), 1)

    def test_a_late_owner_result_and_the_stop_it_supersedes_link_both_ways(self):
        self.observed(["merge_change", "close_issue", "clean_up"])
        self.collect_stale()
        lost = self.custody
        self.clock.advance(TTL)
        self.store.reap(self.transaction_id, reason="executor lost")
        self.custody = self.acquire(self.transaction_id, executor="exec-b")
        late = self.store.record_owner_result(
            self.transaction_id, executor_id="exec-a", subject_path=PATH,
            fence=plain(lost.fence), result={"done": True})
        self.to("proving")
        receipt, after = self.sealed()
        stop = next(dict(e) for e in after.events if e["type"] == "stop_synthesized")
        result = dict(late.events[-1])
        self.assertEqual(receipt["stops"], [{
            "seq": stop["seq"], "executor_id": "exec-a", "fence": stop["fence"],
            "reason": "executor lost", "superseded_by": result["seq"]}])
        self.assertEqual(receipt["owner_results"], [{
            "seq": result["seq"], "executor_id": "exec-a", "fence": result["fence"],
            "custody": "stale", "supersedes": stop["seq"],
            "result_digest": telemetry_digest({"done": True})}])
        self.assertNotIn('"done"', self.receipt_files()[0].read_text())

    def test_a_unit_with_no_event_records_nulls(self):
        after = self.store.advance(self.transaction_id, "abandoned", reason="r",
                                   external_state="known", custody=self.custody)
        receipt = self.assertSealed(after, "abandoned")
        self.assertEqual(receipt["postconditions"], [
            {"unit": u["action_id"], "name": u["name"], "phase": u["phase"], "status": None,
             "observed": None, "effected": False} for u in self.plan["units"]])
        self.assertEqual([e["evidence_id"] for e in receipt["evaluations"]],
                         [None] * len(self.plan["obligations"]))
