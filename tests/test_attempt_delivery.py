"""Delivery custody's pure rules (#339): the delivery transaction and remainder custody.

Run: just agent-workflow-tests
"""

import json
import unittest
from types import SimpleNamespace

from agent_tools import attempt_custody as ac
from agent_tools import attempt_delivery as ad
from agent_tools.transaction_plan import compile_proof

RUN = "rel_01890a5d-ac96-774b-bcce-b302099a8057"
DIGEST = "sha256:" + "c" * 64


def text(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def contract(**obligations):
    marks = {**dict.fromkeys(ad.POSTCONDITIONS, "required"), **obligations}
    return {"issue": 41, "deliverable": {"id": "d", "summary": "é", "obligations": marks}}


def delivery(**obligations):
    post = {name: {"state": "observed", "observation_id": f"sha256:{name}"}
            for name in ad.POSTCONDITIONS}
    for name, mark in obligations.items():
        post[name] = {"state": mark, "observation_id": None}
    return {"contract": contract(**obligations), "contract_digest": DIGEST,
            "postconditions": post, **{kind: [] for kind in ad.JOURNAL_KINDS},
            "delivery_observations": [{"id": "sha256:o2", "n": "é"}, {"id": "sha256:o1"}],
            "authorization_intents": [{"id": "sha256:i1"}], "stage_facts": [{"id": "x"}]}


class DeliveryTransactionTest(unittest.TestCase):
    def test_keys_and_the_closed_subject(self):
        self.assertEqual(ad.delivery_key(41, DIGEST, 2), f"attempt-delivery/v1:41:{DIGEST}:2")
        self.assertEqual(ad.delivery_lease_key(RUN, 41), f"attempt-delivery:{RUN}:41")
        self.assertEqual(ad.delivery_executor(41), "delivery:41")
        subject = ad.delivery_subject(run=RUN, issue=41, contract_digest=DIGEST,
                                      contract=contract())
        self.assertEqual(subject, {"schema": "attempt-delivery/v1", "run": RUN, "issue": 41,
                                   "contract_digest": DIGEST, "contract": contract()})
        for changes in ({"schema": "attempt-custody/v1"}, {"run": "orchestrate-41"},
                        {"issue": 0}, {"contract_digest": ""}, {"contract": {"issue": 42}},
                        {"extra": 1}):
            with self.subTest(changes=changes):
                self.assertIsNotNone(ad.delivery_subject_violation({**subject, **changes}))
        with self.assertRaises(ValueError):
            ad.delivery_subject(run=RUN, issue=42, contract_digest=DIGEST, contract=contract())

    def test_the_proof_plan_is_the_contracts_required_postconditions(self):
        subject = ad.delivery_subject(run=RUN, issue=41, contract_digest=DIGEST,
                                      contract=contract(tracker_closed="not_applicable"))
        arguments = ad.delivery_creation_arguments(subject)
        self.assertEqual((arguments["concurrency_keys"], arguments["authority_class"],
                          arguments["recovery"]),
                         ([f"attempt-delivery:{RUN}:41"], "attempt-delivery",
                          {"effects": {}, "units": []}))
        declared = arguments["proof"]
        self.assertEqual(
            [(o["id"], o["predicate"], o["form"], o["required"], o["semantic"])
             for o in declared["obligations"]],
            [(name, name, "event", True, "readiness")
             for name in ("implementation_delivered", "pr_merged", "cleanup_complete")])
        self.assertEqual(declared["collectors"], {"delivery": {
            "basis": "deterministic", "max_collection_latency_ms": 30_000,
            "predicates": ["implementation_delivered", "pr_merged", "cleanup_complete"]}})
        compile_proof(declared)  # the core accepts it
        none = contract(**dict.fromkeys(ad.POSTCONDITIONS, "not_applicable"))
        self.assertEqual(ad.proof_declaration(none),
                         {"units": [], "obligations": [], "collectors": {}})

    def test_a_complete_delivery_is_collected_from_its_postconditions(self):
        value = delivery(tracker_closed="not_applicable")
        self.assertEqual(ad.collections(value), tuple(
            (name, f"sha256:{name}")
            for name in ("implementation_delivered", "pr_merged", "cleanup_complete")))
        value["postconditions"]["pr_merged"] = {"state": "pending", "observation_id": None}
        with self.assertRaises(ValueError):
            ad.collections(value)

    def test_the_journal_is_every_object_in_kind_then_stored_order(self):
        value = delivery()
        entries = ad.journal_entries(value, text)
        self.assertEqual(entries, (
            ad.JournalEntry("authorization_intents:sha256:i1", '{"id":"sha256:i1"}\n'),
            ad.JournalEntry("delivery_observations:sha256:o2", '{"id":"sha256:o2","n":"é"}\n'),
            ad.JournalEntry("delivery_observations:sha256:o1", '{"id":"sha256:o1"}\n')))
        self.assertEqual(ad.JOURNAL_KINDS, (
            "authorization_intents", "authority_observations", "reevaluation_evidence",
            "authority_evaluation_consumptions", "delivery_observations", "selected_outputs"))
        held = SimpleNamespace(evidence=[{"evidence_id": entries[0].evidence_id}])
        self.assertEqual(ad.journaled(held), {"authorization_intents:sha256:i1"})
        self.assertEqual(ad.journaled(held, [{"reason": entries[2].evidence_id}]),
                         {"authorization_intents:sha256:i1", "delivery_observations:sha256:o1"})


class RemainderSubjectTest(unittest.TestCase):
    def test_key_launch_and_closed_subject(self):
        self.assertEqual(ad.remainder_key(RUN, 41, 2), f"attempt-custody/v1:{RUN}:41:r2")
        self.assertEqual(ad.remainder_launch_id(41, 2, 3), "41:r2:3")
        subject = ad.remainder_subject(run=RUN, issue=41, remainder=2, worktree="/work/wt",
                                       prior=RUN, bound_launch=None)
        self.assertEqual(subject, {
            "schema": "remainder-custody/v1", "run": RUN, "issue": 41, "remainder": 2,
            "worktree": "/work/wt", "prior": RUN, "bound_launch": None})
        self.assertEqual(ac.creation_arguments(subject)["concurrency_keys"],
                         ["attempt-worktree:/work/wt"])
        for changes in ({"schema": "attempt-custody/v1"}, {"run": "x"}, {"remainder": 0},
                        {"worktree": "wt"}, {"prior": "x"}, {"bound_launch": 0},
                        {"attempt": 1}):
            with self.subTest(changes=changes):
                self.assertIsNotNone(ad.remainder_subject_violation({**subject, **changes}))
        with self.assertRaises(ValueError):
            ad.remainder_subject(run=RUN, issue=41, remainder=1, worktree="wt", prior=None,
                                 bound_launch=None)

    def test_the_bind_plans_each_live_remainder_at_its_launch_count(self):
        def remainder(ordinal, state, launches):
            return {"remainder": ordinal, "state": state, "launches": [{}] * launches}

        document = {"issues": {
            "41": {"delivery_remainders": [remainder(1, "failed", 2),
                                           remainder(2, "suspended", 3)]},
            "42": {"delivery_remainders": [remainder(1, "active", 1)]},
            "43": {"delivery_remainders": []}}}
        self.assertEqual(ad.plan_remainder_migration(document), {(41, 2): 3, (42, 1): 1})


if __name__ == "__main__":
    unittest.main()
