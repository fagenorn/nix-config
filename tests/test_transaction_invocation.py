"""Transaction core slice 3: the administrative protocol (#206).

Run: just agent-workflow-tests
"""

import unittest

from agent_tools import transaction_history, transaction_storage
from agent_tools.canonical import telemetry_digest
from agent_tools.transaction_core import (
    MAX_ATTEMPTS, RETRY_WINDOW_MS, EffectResultInvalid, InvocationRefused, StateInvalid,
    TransactionError, action_id)

TID = "rel_01890a5d-ac96-7abc-8def-0123456789ab"


class ActionIdTest(unittest.TestCase):
    def test_the_id_is_act_plus_the_first_32_hex_of_the_digest(self):
        parameters = {"mode": "materialize", "subject": {"digest": "sha256:abc"}}
        expected = "act_" + telemetry_digest([TID, "build", parameters])[7:39]
        self.assertEqual(action_id(TID, "build", parameters), expected)
        self.assertRegex(expected, r"\Aact_[0-9a-f]{32}\Z")

    def test_re_derivation_is_stable_under_parameter_key_order(self):
        first = action_id(TID, "build", {"a": 1, "b": [1, 2]})
        self.assertEqual(action_id(TID, "build", {"b": [1, 2], "a": 1}), first)
        self.assertEqual(action_id(TID, "build", {"a": 1, "b": [1, 2]}), first)

    def test_any_changed_input_changes_the_id(self):
        base = action_id(TID, "build", {"a": 1})
        changed = {action_id(TID[:-1] + "c", "build", {"a": 1}),
                   action_id(TID, "stage", {"a": 1}), action_id(TID, "build", {"a": 2}),
                   action_id(TID, "build", {})}
        self.assertEqual(len(changed), 4)
        self.assertNotIn(base, changed)

    def test_malformed_inputs_are_refused(self):
        for args in ((TID, "", {}), (TID, 7, {}), (TID, "\ud800", {}), (TID, "b", []),
                     (TID, "b", {"x": float("nan")}), (TID, "b", {1: "x"}),
                     ("", "b", {}), (None, "b", {})):
            with self.subTest(args=args), self.assertRaises(StateInvalid):
                action_id(*args)


class VocabularyTest(unittest.TestCase):
    def test_the_retry_budget_constants(self):
        self.assertEqual((MAX_ATTEMPTS, RETRY_WINDOW_MS), (3, 900_000))

    def test_the_new_errors_are_transaction_errors_homed_in_storage(self):
        self.assertIs(InvocationRefused, transaction_storage.InvocationRefused)
        self.assertIs(EffectResultInvalid, transaction_storage.EffectResultInvalid)
        self.assertTrue(issubclass(InvocationRefused, TransactionError))
        self.assertTrue(issubclass(EffectResultInvalid, TransactionError))
        error = InvocationRefused("rel_x: refused", reason="window_closed")
        self.assertEqual((error.reason, str(error)), ("window_closed", "rel_x: refused"))

    def test_the_codecs_have_one_home_in_storage(self):
        for name in ("format_at", "parse_at", "json_object_violation"):
            self.assertIs(getattr(transaction_history, name),
                          getattr(transaction_storage, name))


if __name__ == "__main__":
    unittest.main()
