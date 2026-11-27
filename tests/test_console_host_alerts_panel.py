"""The console's host alerts panel module: strict bodies, the save merge, owner words, route replies.

Runs `agent_tools.hosts.host_alerts_panel` against a scratch settings file and a loopback
stand-in for the Telegram bot API: what each body may carry, what a save writes and keeps, what
the view entry publishes, the owner's sentence for every Telegram reason, and the status, body and
log line of every route reply, none of which shows the bot token.
Run: just agent-workflow-tests
"""

import json
import os
import stat
import threading
import unittest
from unittest import mock

from agent_tools.hosts import host_alerts_panel
from agent_tools.hosts.host_alerts_panel import (
    BAD_BODY,
    CHATS_PATH,
    DELIVERED,
    EMPTY_FEED,
    FOLDER,
    NO_TOKEN,
    NOT_READY,
    PROBLEM,
    SAVE_PATH,
    SWITCH_PATH,
    TEST_PATH,
    UNAVAILABLE,
    UNREADABLE,
    Failed,
    Panel,
    Refused,
    Reply,
    Save,
    chats,
    entry,
    parse_chats,
    parse_save,
    parse_switch,
    parse_test,
    reason_words,
    respond,
    save,
    switch,
    test,
)
from agent_tools.hosts import host_alerts
from agent_tools.hosts.host_alerts import Settings, read_settings, write_settings
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures
from tests.test_host_alerts import SETTINGS, HostAlertsCase, grow_nested

TIER = "fast"

MISSING_ENTRY = {"token_set": False, "chat_id": None, "enabled": False, "problem": None}
PROBLEM_ENTRY = {"token_set": False, "chat_id": None, "enabled": False, "problem": PROBLEM}
ONE_CHAT = {"ok": True, "result": [{"update_id": 1, "message": {"chat": {"id": -1001234, "title": "Ops"}}}]}


class PanelCase(HostAlertsCase):
    def setUp(self):
        super().setUp()
        self.panel = Panel(self.settings, api=self.bot.api)
        self.lock = threading.Lock()


class PanelTest(PanelCase):
    def test_a_first_save_writes_a_private_enabled_file_with_the_typed_token_and_chat(self):
        save(self.panel, Save(bot_token="123:SECRET-TOKEN", chat_id="-1001234"))
        self.assertEqual(read_settings(self.settings), Settings(True, "123:SECRET-TOKEN", "-1001234"))
        self.assertEqual(stat.S_IMODE(self.settings.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.settings.parent.stat().st_mode), 0o700)
        self.assertEqual(self.bot.requests, [])

    def test_a_save_with_no_typed_token_keeps_the_saved_one_and_the_switch(self):
        write_settings(Settings(False, "123:SECRET-TOKEN", "-1"), self.settings)
        save(self.panel, Save(bot_token=None, chat_id="-1009"))
        self.assertEqual(read_settings(self.settings), Settings(False, "123:SECRET-TOKEN", "-1009"))

    def test_a_save_with_no_usable_token_is_refused(self):
        with self.assertRaises(Refused) as caught:
            save(self.panel, Save(bot_token=None, chat_id="-1"))
        self.assertEqual(str(caught.exception), NO_TOKEN)
        self.assertFalse(self.settings.exists())
        self.write(SETTINGS, 0o644)
        before = self.settings.read_bytes()
        with self.assertRaises(Refused) as caught:
            save(self.panel, Save(bot_token=None, chat_id="-1"))
        self.assertEqual(str(caught.exception), NO_TOKEN)
        self.assertEqual(self.settings.read_bytes(), before)
        self.write({**SETTINGS, "bot_token": "123:a/b"})
        with self.assertRaises(Refused) as caught:
            save(self.panel, Save(bot_token=None, chat_id="-1"))
        self.assertEqual(str(caught.exception), NO_TOKEN)

    def test_the_switch_off_keeps_the_token_and_chat(self):
        self.write(SETTINGS)
        switch(self.panel, False)
        self.assertEqual(read_settings(self.settings), Settings(False, "123:SECRET-TOKEN", "-1001234"))
        self.settings.unlink()
        switch(self.panel, False)
        self.assertEqual(json.loads(self.settings.read_text()),
                         {"enabled": False, "bot_token": None, "chat_id": None})

    def test_the_switch_on_needs_a_saved_token_and_chat(self):
        with self.assertRaises(Refused) as caught:
            switch(self.panel, True)
        self.assertEqual(str(caught.exception), NOT_READY)
        self.assertFalse(self.settings.exists())
        switch(self.panel, False)
        with self.assertRaises(Refused) as caught:
            switch(self.panel, True)
        self.assertEqual(str(caught.exception), NOT_READY)
        self.assertFalse(read_settings(self.settings).enabled)
        write_settings(Settings(False, "123:SECRET-TOKEN", "-1"), self.settings)
        switch(self.panel, True)
        self.assertTrue(read_settings(self.settings).enabled)

    def test_the_entry_publishes_only_validated_values_and_never_the_token(self):
        cases = []
        cases.append((MISSING_ENTRY, None))
        cases.append(({"token_set": True, "chat_id": "-1001234", "enabled": True, "problem": None},
                      (SETTINGS, 0o600)))
        cases.append((PROBLEM_ENTRY, (SETTINGS, 0o644)))
        cases.append((PROBLEM_ENTRY, ({**SETTINGS, "chat_id": "123:SECRET-TOKEN"}, 0o600)))
        cases.append((PROBLEM_ENTRY, ({**SETTINGS, "bot_token": "x 123:SECRET-TOKEN"}, 0o600)))
        for expected, content in cases:
            with self.subTest(content=content):
                self.settings.unlink(missing_ok=True)
                if content is not None:
                    self.write(*content)
                published = entry(self.panel)
                self.assertEqual(published, expected)
                self.assertNotIn("SECRET-TOKEN", json.dumps(published))
                self.assertEqual(set(published), {"token_set", "chat_id", "enabled", "problem"})

    def test_the_parsers_take_exact_strict_bodies_and_never_echo_a_value(self):
        self.assertEqual(parse_save(b'{"bot_token": "123:SECRET-TOKEN", "chat_id": "-1"}'),
                         Save(bot_token="123:SECRET-TOKEN", chat_id="-1"))
        self.assertEqual(parse_save(b'{"chat_id": "@alerts_chan"}'),
                         Save(bot_token=None, chat_id="@alerts_chan"))
        self.assertIs(parse_switch(b'{"enabled": false}'), False)
        self.assertIsNone(parse_chats(b"{}"))
        self.assertEqual(parse_chats(b'{"bot_token": "123:SECRET-TOKEN"}'), "123:SECRET-TOKEN")
        self.assertIsNone(parse_test(b"{}"))
        refused = [
            (parse_save, b'{"chat_id": "-1", "x": 1}'),
            (parse_save, b'{"bot_token": "123:SECRET-TOKEN"}'),
            (parse_save, b'{"bot_token": "123:a/b?SECRET", "chat_id": "-1"}'),
            (parse_save, b'{"chat_id": "12a"}'),
            (parse_save, b"[]"),
            (parse_save, b"not json"),
            (parse_save, b"\xff"),
            (parse_switch, b'{"enabled": false, "enabled": true}'),
            (parse_switch, b'{"enabled": "no"}'),
            (parse_switch, b'{"enabled": 1}'),
            (parse_switch, b'{"enabled": NaN}'),
            (parse_switch, b"{}"),
            (parse_chats, b'{"bot_token": "SECRET"}'),
            (parse_test, b'{"x": 1}'),
        ]
        for parse, body in refused:
            with self.subTest(parse=parse.__name__, body=body[:40]):
                with self.assertRaises(ValueError) as caught:
                    parse(body)
                self.assertEqual(str(caught.exception), BAD_BODY)
                self.assertNotIn("SECRET", str(caught.exception))

    def test_a_deeply_nested_body_is_a_bad_body_not_a_raise(self):
        def refuse(depth):
            for parse in (parse_save, parse_switch, parse_chats, parse_test):
                with self.assertRaises(ValueError) as caught:
                    parse(b"[" * depth)
                self.assertEqual(str(caught.exception), BAD_BODY)

        self.assertGreaterEqual(grow_nested(self, refuse), 8000)

    def test_a_deeply_nested_settings_file_is_a_problem_entry_not_a_raise(self):
        def view(depth):
            self.write("[" * depth)
            self.assertEqual(entry(self.panel), PROBLEM_ENTRY)

        self.assertGreaterEqual(grow_nested(self, view), 8000)

    def test_a_switch_off_never_replaces_an_unreadable_file(self):
        self.write(SETTINGS)
        panel = Panel(self.settings, api=self.bot.api)
        self.assertEqual(entry(panel)["enabled"], True)
        self.settings.chmod(0o644)
        before = self.settings.read_bytes()
        for wanted in (False, True):
            with self.subTest(enabled=wanted):
                with self.assertRaises(Refused) as caught:
                    switch(panel, wanted)
                self.assertEqual(str(caught.exception), UNREADABLE)
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(self.settings.stat().st_mode), 0o644)
        reply, published = respond(panel, SWITCH_PATH, b'{"enabled": false}', lock=self.lock)
        self.assertEqual((reply.status, published), (409, None))
        self.assertEqual(self.settings.read_bytes(), before)

    def test_a_write_hands_its_entry_over_before_the_lock_is_released(self):
        seen = []

        def publish(published):
            seen.append((published, self.lock.locked()))

        reply, published = respond(self.panel, SAVE_PATH,
                                   b'{"bot_token": "123:SECRET-TOKEN", "chat_id": "-1"}',
                                   lock=self.lock, publish=publish)
        self.assertEqual(reply.status, 204)
        self.assertEqual(seen, [(published, True)])
        respond(self.panel, SWITCH_PATH, b'{"enabled": false}', lock=self.lock, publish=publish)
        self.assertEqual([entry_["enabled"] for entry_, _ in seen], [True, False])
        self.assertTrue(all(held for _, held in seen))

    def test_reason_words_reads_each_reason_plainly(self):
        rows = [
            ("HTTP 400 chat moved to a supergroup",
             "that group became a supergroup, so its chat id changed: find the chat again and save the "
             "new id (HTTP 400)"),
            ("HTTP 401", "Telegram refused the bot token (HTTP 401)"),
            ("HTTP 404", "Telegram does not know that bot token (HTTP 404)"),
            ("HTTP 400 chat not found", "Telegram does not know that chat (HTTP 400)"),
            ("HTTP 400", "Telegram refused the message (HTTP 400)"),
            ("HTTP 403 blocked by the user", "the chat's owner blocked the bot (HTTP 403)"),
            ("HTTP 403 not a member", "the bot is not a member of that chat (HTTP 403)"),
            ("HTTP 403 removed from the chat", "the bot was removed from that chat (HTTP 403)"),
            ("HTTP 403", "Telegram does not let the bot post there (HTTP 403)"),
            ("HTTP 409 webhook set",
             "the bot sends its updates to a webhook, so it has no chat list (HTTP 409)"),
            ("HTTP 409 another reader", "another program reads the bot's updates (HTTP 409)"),
            ("HTTP 409", "Telegram answered HTTP 409"),
            ("HTTP 502", "Telegram answered HTTP 502"),
            ("HTTP 502 chat not found", "Telegram answered HTTP 502"),
            ("ok false", "Telegram answered without accepting it"),
            ("settings missing", "nothing is saved yet"),
            ("settings refused", "the saved settings could not be read"),
            ("settings incomplete", "save a bot token and a chat first"),
            ("bad token", "that is not a bot token"),
            ("URLError", "Telegram could not be reached (URLError)"),
        ]
        for reason, words in rows:
            with self.subTest(reason=reason):
                self.assertEqual(reason_words(reason), words)

    def test_the_test_and_chat_list_answer_in_owner_words(self):
        self.write(SETTINGS)
        self.assertEqual(test(self.panel), (True, DELIVERED))
        self.bot.status = 403
        self.bot.body = {"ok": False, "description": "Forbidden: bot was blocked by the user"}
        self.assertEqual(test(self.panel),
                         (False, "Not delivered: the chat's owner blocked the bot (HTTP 403)."))
        self.bot.body = {"ok": False, "description": "Forbidden: bot is not a member of the channel chat"}
        self.assertEqual(test(self.panel),
                         (False, "Not delivered: the bot is not a member of that chat (HTTP 403)."))
        self.bot.status = 200
        self.bot.body = ONE_CHAT
        self.bot.requests.clear()
        self.assertEqual(chats(self.panel, None), ([{"id": "-1001234", "title": "Ops"}], None))
        self.assertIn("123:SECRET-TOKEN", self.bot.requests[0]["path"])
        self.bot.body = {"ok": True, "result": []}
        self.assertEqual(chats(self.panel, None), ([], EMPTY_FEED))
        self.bot.status = 401
        self.bot.body = {"ok": False, "description": "Unauthorized"}
        with self.assertRaises(Failed) as caught:
            chats(self.panel, None)
        self.assertEqual(str(caught.exception),
                         "Telegram did not give the bot's chats: Telegram refused the bot token (HTTP 401).")
        self.settings.unlink()
        self.bot.requests.clear()
        with self.assertRaises(Refused) as caught:
            chats(self.panel, None)
        self.assertEqual(str(caught.exception), NO_TOKEN)
        self.assertEqual(self.bot.requests, [])

    def test_a_save_into_a_folder_owned_by_another_user_is_refused(self):
        self.settings.parent.mkdir(parents=True)
        with mock.patch.object(host_alerts.os, "geteuid", return_value=os.geteuid() + 1):
            with self.assertRaises(Refused) as caught:
                save(self.panel, Save(bot_token="123:SECRET-TOKEN", chat_id="-1"))
        self.assertEqual(str(caught.exception), FOLDER)
        self.assertFalse(self.settings.exists())

    def test_respond_answers_each_route_with_status_body_and_one_safe_line(self):
        replies = []

        def ask(route, body, panel=self.panel):
            reply, published = respond(panel, route, body, lock=self.lock)
            replies.append(reply)
            return reply, published

        self.assertEqual(
            ask(SAVE_PATH, b'{"chat_id": "-1"}', None),
            (Reply(409, "text/plain", (UNAVAILABLE + "\n").encode(), "console: host_alerts_refused save"),
             None))
        self.assertEqual(
            ask(SAVE_PATH, b'{"bot_token": "123:SECRET-TOKEN", "chat_id": "-1"}'),
            (Reply(204, None, b"", None),
             {"token_set": True, "chat_id": "-1", "enabled": True, "problem": None}))
        before = self.settings.read_bytes()
        self.assertEqual(
            ask(SWITCH_PATH, b'{"enabled": false, "enabled": true}'),
            (Reply(400, "text/plain", b"bad host alerts\n", None), None))
        self.assertEqual(self.settings.read_bytes(), before)
        self.bot.body = ONE_CHAT
        self.assertEqual(
            ask(CHATS_PATH, b"{}"),
            (Reply(200, "application/json", b'{"chats":[{"id":"-1001234","title":"Ops"}],"text":null}', None),
             None))
        self.bot.status = 401
        self.bot.body = {"ok": False}
        reply, published = ask(CHATS_PATH, b"{}")
        self.assertEqual((reply.status, reply.log, published), (502, "console: host_alerts_chats_failed", None))
        self.bot.status = 200
        self.bot.body = {"ok": True}
        self.assertEqual(
            ask(TEST_PATH, b"{}"),
            (Reply(200, "application/json",
                   b'{"delivered":true,"text":"Delivered: Telegram accepted the test message."}', None),
             None))
        with mock.patch.object(host_alerts_panel, "save", side_effect=OSError("123:SECRET-TOKEN")):
            self.assertEqual(
                ask(SAVE_PATH, b'{"chat_id": "-1"}'),
                (Reply(500, "text/plain", b"host alerts failed\n", "console: host_alerts_failed save OSError"),
                 None))
        for reply in replies:
            self.assertNotIn(b"SECRET-TOKEN", reply.body)
            self.assertNotIn("SECRET-TOKEN", reply.log or "")

    def test_a_held_lock_makes_a_save_wait(self):
        done = []

        def run():
            done.append(respond(self.panel, SAVE_PATH,
                                b'{"bot_token": "123:SECRET-TOKEN", "chat_id": "-1"}', lock=self.lock))

        self.lock.acquire()
        thread = threading.Thread(target=run)
        thread.start()
        thread.join(0.2)
        alive = thread.is_alive()
        self.lock.release()
        thread.join()
        self.assertTrue(alive)
        self.assertEqual(done[0][0].status, 204)


if __name__ == "__main__":
    unittest.main()
