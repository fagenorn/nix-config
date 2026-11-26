"""The desk page's card for a sprint that holds work and has asked nobody for it."""

import unittest

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_page import PROGRESS, START, frame, full, has_class, nodes, render

TIER = "integration"  # the renderer is a Node harness

HELD_SPRINT = {
    "type": "inbox_item", "reason": "held_sprint", "key": "held-sprint/" + "a" * 16,
    "project_id": "owner/p00", "sprint_id": "a" * 16, "title": "make the importer resumable",
    "headline": "make the importer resumable is holding work and has asked nobody for it",
    "last_status": "the last slice waits on the lead's go", "answered": False,
    "waiting_since": "2026-11-10T08:00:00+00:00",
}


class PageHeldSprintTest(unittest.TestCase):
    def test_a_held_sprint_card_shows_its_headline_and_the_managers_last_status(self) -> None:
        (snap,) = render([START, {"frame": frame([HELD_SPRINT])}, {"snapshot": True}])
        (card,) = [n for n in nodes(snap["inbox"]) if has_class(n, "held-sprint")]
        self.assertEqual(card["tag"], "article")
        self.assertTrue(has_class(card, "card"))
        self.assertIn(HELD_SPRINT["headline"], full(card))
        self.assertEqual([full(n) for n in nodes(card) if has_class(n, "reason")],
                         ["the last slice waits on the lead's go"])
        self.assertIn("nothing has moved since", full(card))
        self.assertEqual([n for n in nodes(card) if n["tag"] == "button"], [])
        self.assertEqual(
            [n for n in nodes(snap["inbox"])
             if n["tag"] == "li" and HELD_SPRINT["headline"] in full(n)], [])

    def test_a_held_sprint_card_sits_after_the_progress_cards(self) -> None:
        (snap,) = render([
            START, {"frame": frame([HELD_SPRINT, PROGRESS])}, {"snapshot": True},
        ])
        cards = [n for n in nodes(snap["inbox"]) if n["tag"] == "article"]
        order = [next(c for c in ("progress", "held-sprint") if has_class(n, c))
                 for n in cards]
        self.assertEqual(order, ["progress", "held-sprint"])


if __name__ == "__main__":
    unittest.main()
