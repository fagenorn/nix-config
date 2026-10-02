"""Transaction core slice 6: authority, the failed disposition and its grounds (#209).

Run: just agent-workflow-tests
"""

import copy
import unittest

from agent_tools import transaction_core, transaction_history
from agent_tools.transaction_core import (
    ACTOR_KINDS, CreationConflict, StateInvalid, TransitionRefused)

from .test_transaction_custody import (
    AUTHORITY, EMPTY_PROOF, EMPTY_RECOVERY, KEYS, SUBJECT, CustodyCase)


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
