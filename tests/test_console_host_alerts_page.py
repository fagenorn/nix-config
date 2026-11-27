"""The desk page's Host alerts panel.

Run: just agent-workflow-tests
"""
import json
import unittest

from agent_tools.console.host_alerts_panel import EMPTY_FEED, PROBLEM
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from .test_console_guest_page import GUEST, SHARED_FRAME, SNAP, harness
from .test_console_page import F3, START, nodes, posted, role, text

TIER = "integration"

ENTRY = {"token_set": False, "chat_id": None, "enabled": False, "problem": None}
SAVED = {"token_set": True, "chat_id": "-1001234", "enabled": True, "problem": None}
NO_REPLY = {"status": 204, "text": ""}


def frame(entry: dict | None) -> dict:
    return {"frame": {**SHARED_FRAME, "host_alerts": entry}}


def alert_posts(snap: dict) -> list:
    return [(p["url"], posted(p)) for p in snap["posts"] if p["url"].startswith("/api/host-alerts-")]


def opened(entry: dict | None) -> list:
    return [START, frame(entry), {"click": "alerts-open"}]


class HostAlertsPanelTest(unittest.TestCase):
    def test_the_panel_saves_the_typed_token_and_picked_chat_and_then_forgets_the_token(self) -> None:
        first, second = harness([
            START, frame(ENTRY), {"click": "alerts-open"},
            {"type": {"class": "alerts-token", "text": "123:SECRET-TOKEN"}},
            {"respond": {"status": 200, "text": '{"chats":[{"id":"-1001234","title":"Ops"}],"text":null}'}},
            {"click": "alerts-find"}, {"click": "alerts-chat"},
            {"respond": NO_REPLY}, {"click": "alerts-save"},
            frame(SAVED), {"focus_on": "alerts-token"}, SNAP,
            {"respond": NO_REPLY}, {"click": "alerts-save"}, SNAP])[-2:]
        self.assertEqual(alert_posts(first), [
            ("/api/host-alerts-chats", {"bot_token": "123:SECRET-TOKEN"}),
            ("/api/host-alerts-save", {"bot_token": "123:SECRET-TOKEN", "chat_id": "-1001234"})])
        self.assertEqual(first["field"]["value"], "")
        for part in ("host_alerts_body", "host_alerts", "host_alerts_open"):
            self.assertNotIn("SECRET-TOKEN", json.dumps(first[part]))
        self.assertIn("A bot token is saved.", text(first["host_alerts_body"]))
        self.assertEqual(alert_posts(second)[-1], ("/api/host-alerts-save", {"chat_id": "-1001234"}))

    def test_with_no_host_alerts_the_button_stays_hidden(self) -> None:
        gone, shown, closed = harness([
            START, frame(None), SNAP, frame(ENTRY), SNAP,
            {"click": "alerts-open"}, frame(None), SNAP])[-3:]
        self.assertIs(gone["host_alerts_open"]["hidden"], True)
        self.assertIs(shown["host_alerts_open"]["hidden"], False)
        self.assertIs(closed["host_alerts"]["hidden"], True)

    def test_the_guest_door_removes_the_button_and_the_panel(self) -> None:
        (snap,) = harness([START, frame(ENTRY), SNAP], GUEST)
        for part in ("host_alerts_open", "host_alerts", "host_alerts_body"):
            self.assertIsNone(snap[part])

    def test_the_lines_say_what_is_saved_and_never_show_a_token(self) -> None:
        (saved,) = harness([*opened(SAVED), SNAP])
        words = text(saved["host_alerts_body"])
        for line in ("A bot token is saved.", "Alerts go to chat -1001234.", "Alerts are on."):
            self.assertIn(line, words)
        (empty,) = harness([*opened(ENTRY), SNAP])
        words = text(empty["host_alerts_body"])
        for line in ("No bot token is saved yet.", "No chat is chosen yet.",
                     "Alerts are off: this computer records them in its log only."):
            self.assertIn(line, words)
        (problem,) = harness([*opened({**ENTRY, "problem": PROBLEM}), SNAP])
        self.assertIn(PROBLEM, text(problem["host_alerts_body"]))

    def test_send_test_shows_the_consoles_words(self) -> None:
        sentence = "Not delivered: the bot is not a member of that chat (HTTP 403)."
        (snap,) = harness([
            *opened(SAVED),
            {"respond": {"status": 200, "text": json.dumps({"delivered": False, "text": sentence})}},
            {"click": "alerts-test"}, SNAP])
        self.assertIn(sentence, text(snap["host_alerts_body"]))
        self.assertEqual(alert_posts(snap)[-1], ("/api/host-alerts-test", {}))
        (sent,) = [p for p in snap["posts"] if p["url"] == "/api/host-alerts-test"]
        self.assertEqual(sent["headers"], {"X-Console-Token": "__CONSOLE_TOKEN__", "Content-Type": "application/json"})

    def test_an_empty_chat_list_shows_its_words_and_a_typed_chat_id_saves(self) -> None:
        (snap,) = harness([
            *opened({**ENTRY, "token_set": True}),
            {"respond": {"status": 200, "text": json.dumps({"chats": [], "text": EMPTY_FEED})}},
            {"click": "alerts-find"}, SNAP])
        self.assertIn(EMPTY_FEED, text(snap["host_alerts_body"]))
        self.assertEqual(alert_posts(snap)[-1], ("/api/host-alerts-chats", {}))
        (snap,) = harness([
            *opened({**ENTRY, "token_set": True}),
            {"type": {"class": "alerts-chat-id", "text": "-1009876"}},
            {"click": "alerts-save"}, SNAP])
        self.assertEqual(alert_posts(snap)[-1], ("/api/host-alerts-save", {"chat_id": "-1009876"}))
        refusal = "Enter the bot token: none is saved yet."
        (snap,) = harness([
            *opened(ENTRY),
            {"type": {"class": "alerts-token", "text": "1:x"}},
            {"respond": {"status": 409, "text": refusal}},
            {"type": {"class": "alerts-chat-id", "text": "-1"}},
            {"click": "alerts-save"}, SNAP])
        (refused,) = [n for n in nodes(snap["host_alerts_body"]) if "alerts-refused" in n["cls"].split()]
        self.assertTrue(refused["text"].startswith("The console refused: "))
        self.assertIn(refusal, refused["text"])

    def test_the_chat_field_keeps_the_owners_typing_across_frames(self) -> None:
        (snap,) = harness([
            *opened({**ENTRY, "token_set": True}),
            {"type": {"class": "alerts-chat-id", "text": "-77"}}, frame({**ENTRY, "token_set": True}),
            {"focus_on": "alerts-chat-id"}, SNAP])
        self.assertEqual(snap["field"]["value"], "-77")

    def test_the_switch_posts_the_other_state(self) -> None:
        (off,) = harness([*opened(SAVED), {"click": "alerts-off"}, SNAP])
        self.assertEqual(alert_posts(off), [("/api/host-alerts-switch", {"enabled": False})])
        (on,) = harness([*opened({**SAVED, "enabled": False}), {"click": "alerts-on"}, SNAP])
        self.assertEqual(alert_posts(on), [("/api/host-alerts-switch", {"enabled": True})])
        (none,) = harness([
            *opened({**SAVED, "token_set": False, "enabled": False}), {"click": "alerts-on"}, SNAP])
        (button,) = [n for n in nodes(none["host_alerts_body"]) if "alerts-on" in n["cls"].split()]
        self.assertIs(button["disabled"], True)
        self.assertEqual(alert_posts(none), [])

    def test_one_top_bar_panel_at_a_time(self) -> None:
        frames = {"frame": {**SHARED_FRAME, "capacity": F3["capacity"], "host_alerts": ENTRY}}
        first, second, third = harness([
            START, frames, {"click": "share-open"}, {"click": "alerts-open"}, SNAP,
            {"click": "cap"}, SNAP,
            {"click": "alerts-open"}, {"click": "share-open"}, SNAP])
        self.assertIs(first["sharing"]["hidden"], True)
        self.assertIs(first["host_alerts"]["hidden"], False)
        self.assertIs(second["host_alerts"]["hidden"], True)
        self.assertIs(third["host_alerts"]["hidden"], True)
        self.assertIs(third["sharing"]["hidden"], False)

    def test_escape_closes_the_panel_and_returns_focus_to_the_button(self) -> None:
        (snap,) = harness([
            START, frame(ENTRY), {"focus_on": "alerts-open"}, {"click": "alerts-open"},
            {"key": "Escape"}, SNAP])
        self.assertIs(snap["host_alerts"]["hidden"], True)
        self.assertEqual(role(snap["active"]), "alerts-open")


if __name__ == "__main__":
    unittest.main()
