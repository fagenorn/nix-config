"""Asserted sweep of the transaction core across four unlike project shapes (#204 D6, D17).

The prototype's autopilot printed where each (shape, scenario) cell landed; this table
asserts it against persisted history. Only the success row exists in this slice.

Run: just agent-workflow-tests
"""

import tempfile
import unittest
from pathlib import Path

from agent_tools.transaction_core import TransactionStore

from .transaction_core_shapes import SHAPES
from .transaction_core_sweep_support import SCENARIOS, drive

WITH_ACTIVATION = ("created", "awaiting_verification", "ready", "publishing", "published",
                   "activating", "proving", "succeeded")
WITHOUT_ACTIVATION = tuple(s for s in WITH_ACTIVATION if s != "activating")

# (shape, scenario) -> (final state, every state the persisted history passes through)
SWEEP = {
    ("platform", "success"): ("succeeded", WITH_ACTIVATION),
    ("product", "success"): ("succeeded", WITH_ACTIVATION),
    ("daemon", "success"): ("succeeded", WITH_ACTIVATION),
    ("library", "success"): ("succeeded", WITHOUT_ACTIVATION),
}


def states_passed(transaction):
    return ("created",) + tuple(event["to"] for event in transaction.events[1:])


class SweepTableTest(unittest.TestCase):
    def test_the_table_covers_every_shape_for_every_ported_scenario(self):
        self.assertEqual(set(SWEEP), {(shape, scenario) for shape in SHAPES
                                      for scenario in SCENARIOS})

    def test_every_cell_lands_where_the_table_says(self):
        for (shape, scenario), (final, path) in SWEEP.items():
            with self.subTest(shape=shape, scenario=scenario), \
                    tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                transaction_id = drive(TransactionStore(root), shape, scenario)
                persisted = TransactionStore(root).load(transaction_id)
                self.assertEqual(persisted.creation_key, f"{shape}:{scenario}")
                self.assertEqual(persisted.state, final)
                self.assertEqual(states_passed(persisted), path)
                self.assertEqual({e["external_state"] for e in persisted.events[1:]},
                                 {"known"})

    def test_recreating_a_driven_cell_returns_its_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TransactionStore(Path(tmp))
            first = drive(store, "library", "success")
            subject = dict(store.load(first).subject)
            again = store.create("library:success", subject)
            self.assertEqual(again.transaction_id, first)
            self.assertEqual(len(again.events), len(store.load(first).events))


if __name__ == "__main__":
    unittest.main()
