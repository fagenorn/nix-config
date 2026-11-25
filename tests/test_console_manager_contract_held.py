"""The manager contract and the delivery skills raise a card for work held for someone."""

import unittest
from pathlib import Path

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures

TIER = "fast"
REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "python/agent_tools/console/manager-contract.md"


class HeldContractTest(unittest.TestCase):
    def test_the_contract_and_the_delivery_skills_raise_a_card_for_a_held_item(self) -> None:
        text = CONTRACT.read_text(encoding="utf-8")
        flat = " ".join(text.split())
        self.assertIn("## Holding work for someone", text)
        self.assertLess(text.index("## Questions"), text.index("## Holding work for someone"))
        self.assertLess(text.index("## Holding work for someone"), text.index("## A live fault"))
        for needle in (
            "raise a card for whoever it waits on at the moment you hold it",
            "names what is held, why it is held and the one action that releases it",
            "A status line, a report's `inbox` or `next`, or a reply is not an ask",
            "A merge the guard refuses is not such a hold",
            "when ten are open, first take back the one whose answer matters least with"
            " `sprint withdraw-question`, then send the round of nine replacements and the held"
            " question",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, flat)
        rule = (
            "A stop that holds work for the owner or the lead raises a card for whoever it waits on at once,"
            " on the caller's ask channel, naming what is held, why and the one action that releases it;"
            " a status line or a report is not an ask."
        )
        for skill in ("deliver-standard", "deliver-batch"):
            path = REPO_ROOT / "home/common/claude-code/skills" / skill / "SKILL.md"
            with self.subTest(skill=skill):
                self.assertIn(rule, " ".join(path.read_text(encoding="utf-8").split()))


if __name__ == "__main__":
    unittest.main()
