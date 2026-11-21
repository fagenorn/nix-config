"""The console's release card routes (#1401): the lead's post, the owner's approval, the restart fold.

Run: just agent-workflow-tests
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import guest, release_card, service

from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

COMMIT = "a" * 40
OTHER = "b" * 40
JSON_TYPE = {"Content-Type": "application/json"}


def body(**fields) -> bytes:
    return json.dumps(fields).encode()


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.store = root / "state/console/events.sqlite3"
        self.registry = root / "state/fleet/registry.json"

    def start(self):
        return support.service(self, self.store, self.registry)

    def token(self):
        return (self.store.parent / "page-token").read_text().strip()

    def own(self, svc):
        return {"Origin": f"http://127.0.0.1:{svc.address[1]}", "X-Console-Token": self.token(),
                **JSON_TYPE}

    def lead_post(self, svc, commit=COMMIT, version="v1.2.0", headers=JSON_TYPE):
        return support.post_page(svc.address, release_card.PATH, headers,
                                 body(commit=commit, version=version))

    def answer(self, svc, card, answer, headers=None):
        return support.post_page(svc.address, release_card.ANSWER_PATH,
                                 self.own(svc) if headers is None else headers,
                                 body(card=card, answer=answer))

    def posted_rows(self):
        return [row for row in support.log_rows(self.store)
                if row[2] == "release_card.posted"]

    def state(self, svc):
        status, _, text = support.request(svc.address, "GET", "/api/state")
        self.assertEqual(status, 200)
        return json.loads(text)

    def release_items(self, svc):
        return [item for item in self.state(svc)["inbox"]["open"] if item["reason"] == "release"]


class ReleaseCardRouteTest(Case):
    def test_the_lead_posts_a_card_and_the_owner_approves_it_on_the_page(self):
        svc = self.start()
        status, _, text = self.lead_post(svc)
        self.assertEqual(status, 200)
        answered = json.loads(text)
        card = answered["card"]
        self.assertEqual(answered, {"card": card, "state": "open"})
        (item,) = self.release_items(svc)
        self.assertEqual((item["card"], item["commit"], item["version"]), (card, COMMIT, "v1.2.0"))
        self.assertEqual(self.answer(svc, card, "approve")[0], 204)
        self.assertEqual(self.release_items(svc), [])
        cards = release_card.store_cards(self.store)
        self.assertTrue(release_card.approved(cards, COMMIT, "v1.2.0"))
        self.assertFalse(release_card.approved(cards, COMMIT, "v1.2.1"))

    def test_posting_the_same_candidate_again_returns_the_standing_card(self):
        svc = self.start()
        first = json.loads(self.lead_post(svc)[2])
        second = json.loads(self.lead_post(svc)[2])
        self.assertEqual(second, first)
        self.assertEqual(len(self.posted_rows()), 1)
        self.assertEqual(self.answer(svc, first["card"], "approve")[0], 204)
        self.assertEqual(json.loads(self.lead_post(svc)[2]),
                         {"card": first["card"], "state": "approved"})
        declined = json.loads(self.lead_post(svc, OTHER, "v1.3.0")[2])
        self.assertEqual(self.answer(svc, declined["card"], "decline")[0], 204)
        again = json.loads(self.lead_post(svc, OTHER, "v1.3.0")[2])
        self.assertEqual(again["state"], "open")
        self.assertGreater(again["card"], declined["card"])

    def test_a_post_with_an_origin_or_a_bad_body_is_refused_and_appends_nothing(self):
        svc = self.start()
        rows = support.log_rows(self.store)
        origin = {**JSON_TYPE, "Origin": f"http://127.0.0.1:{svc.address[1]}"}
        refused = [
            (self.lead_post(svc, headers=origin), 403, b"origin refused\n"),
            (support.post_page(svc.address, release_card.PATH, {"Content-Type": "text/plain"},
                               body(commit=COMMIT, version="v1.2.0")), 415, b"json only\n"),
            (self.lead_post(svc, commit="A" * 40), 400, b"bad release card\n"),
            (support.post_page(svc.address, release_card.PATH, JSON_TYPE, b" " * 1025),
             413, b"too large\n"),
            (support.post_page(svc.address, release_card.PATH,
                               {**JSON_TYPE, "Transfer-Encoding": "chunked"}, b""),
             411, b"length required\n"),
        ]
        for (status, _, text), want_status, want_text in refused:
            with self.subTest(want=want_status):
                self.assertEqual((status, text), (want_status, want_text))
        self.assertEqual(support.log_rows(self.store), rows)

    def test_an_answer_without_the_page_guard_or_to_a_closed_card_approves_nothing(self):
        svc = self.start()
        card = json.loads(self.lead_post(svc)[2])["card"]
        origin = f"http://127.0.0.1:{svc.address[1]}"
        rows = support.log_rows(self.store)
        no_token = self.answer(svc, card, "approve", {"Origin": origin, **JSON_TYPE})
        self.assertEqual((no_token[0], no_token[2]), (403, b"token refused\n"))
        no_origin = self.answer(svc, card, "approve",
                                {"X-Console-Token": self.token(), **JSON_TYPE})
        self.assertEqual(no_origin[0], 403)
        missing = self.answer(svc, 99, "approve")
        self.assertEqual((missing[0], missing[2]),
                         (409, release_card.NOT_OPEN.encode() + b"\n"))
        self.assertEqual(support.log_rows(self.store), rows)
        self.assertEqual(self.answer(svc, card, "decline")[0], 204)
        closed = self.answer(svc, card, "approve")
        self.assertEqual((closed[0], closed[2]), (409, release_card.NOT_OPEN.encode() + b"\n"))
        self.assertFalse(release_card.approved(release_card.store_cards(self.store),
                                               COMMIT, "v1.2.0"))

    def test_a_bad_answer_body_is_refused_and_appends_nothing(self):
        svc = self.start()
        self.lead_post(svc)
        rows = support.log_rows(self.store)
        bad = support.post_page(svc.address, release_card.ANSWER_PATH, self.own(svc),
                                body(card=1, answer="maybe"))
        self.assertEqual((bad[0], bad[2]), (400, b"bad release answer\n"))
        text = support.post_page(svc.address, release_card.ANSWER_PATH,
                                 {**self.own(svc), "Content-Type": "text/plain"}, b"{}")
        self.assertEqual((text[0], text[2]), (415, b"json only\n"))
        self.assertEqual(support.log_rows(self.store), rows)

    def test_both_routes_are_owner_only_and_a_guest_view_carries_no_release_card(self):
        for path in (service.RELEASE_CARD_PATH, service.RELEASE_ANSWER_PATH):
            self.assertIn(path, service.OWNER_ONLY)
            self.assertIn(path, service.ROUTES)
        self.assertEqual(service.RELEASE_CARD_PATH, release_card.PATH)
        self.assertEqual(service.RELEASE_ANSWER_PATH, release_card.ANSWER_PATH)
        self.assertIn(service.RELEASE_ANSWER_PATH, service.PAGE_WRITES)
        self.assertNotIn(service.RELEASE_CARD_PATH, service.PAGE_WRITES)
        self.assertNotIn(service.RELEASE_ANSWER_PATH, service.GUEST_WRITES)
        self.assertEqual(guest.OWNER_ONLY_INPUTS["release_items"], ())
        svc = self.start()
        for path in (service.RELEASE_CARD_PATH, service.RELEASE_ANSWER_PATH):
            status, headers, _ = support.request(svc.address, "GET", path)
            self.assertEqual((status, headers["Allow"]), (405, "POST"))

    def test_a_restarted_console_shows_the_same_cards(self):
        first = self.start()
        kept = json.loads(self.lead_post(first)[2])["card"]
        done = json.loads(self.lead_post(first, OTHER, "v1.3.0")[2])["card"]
        self.assertEqual(self.answer(first, done, "approve")[0], 204)
        first.close()
        second = self.start()
        (item,) = self.release_items(second)
        self.assertEqual(item["card"], kept)
        self.assertEqual(json.loads(self.lead_post(second, OTHER, "v1.3.0")[2]),
                         {"card": done, "state": "approved"})


if __name__ == "__main__":
    unittest.main()
