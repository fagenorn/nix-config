"""The expansion budget of the retained compact payloads (issue 256; D2, D3, D5)."""
import unittest
from unittest.mock import patch

from agent_tools import review_expansion, review_witness
from agent_tools.review_expansion import MEMBER_MAX_BYTES, Budget
from agent_tools.review_forecast import canonical_bytes


class Refused(Exception):
    pass


class BudgetTest(unittest.TestCase):
    def test_the_bound_is_the_decode_bound_with_one_home(self):
        self.assertEqual(MEMBER_MAX_BYTES, 1048576)
        self.assertIs(review_witness.MEMBER_MAX_BYTES, review_expansion.MEMBER_MAX_BYTES)

    def test_charges_sum_canonical_bytes_up_to_the_bound(self):
        budget, row = Budget(Refused), {"path": "a", "bytes": 1}
        self.assertIs(budget.charge(row), row)
        budget.add(MEMBER_MAX_BYTES - len(canonical_bytes(row)))  # exactly at the bound
        with self.assertRaises(Refused):
            budget.add(1)

    def test_the_bound_is_read_when_a_budget_starts(self):
        with patch("agent_tools.review_expansion.MEMBER_MAX_BYTES", 10):
            small = Budget(Refused)
        large = Budget(Refused)
        large.add(11)
        with self.assertRaises(Refused):
            small.add(11)

    def test_an_unencodable_value_is_the_refusal(self):
        for value in (object(), {1: "a", "b": 2}, {1, 2}):
            with self.subTest(value=repr(value)):
                with self.assertRaises(Refused):
                    Budget(Refused).charge(value)


if __name__ == "__main__":
    unittest.main()
