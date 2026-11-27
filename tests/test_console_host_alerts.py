"""The console's Host alerts routes: save, switch, the chat list and the test send, end to end.

Starts a console service with a `host_alerts_panel.Panel` on a scratch settings file and a loopback
stand-in for the Telegram bot API, and drives the four owner-only page writes through the guard:
what each answers, what the view shows, what stays out of the event log, the page state and
stderr (the bot token), and that a guest's view never carries the panel.
Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import console, guest, view
from agent_tools.console.host_alerts_panel import (
    CHATS_PATH, DELIVERED, EMPTY_FEED, NO_TOKEN, NOT_READY, PROBLEM, SAVE_PATH, SWITCH_PATH,
    TEST_PATH, UNAVAILABLE, Panel)
from agent_tools.hosts import host_alerts
from agent_tools.hosts.host_alerts import Outcome, Settings, TEST_MESSAGE, read_settings

from . import console_test_support as support
from .test_host_alerts import NOW, SETTINGS, TEXT, HostAlertsCase
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

TIER = "integration"

TOKEN = "123:SECRET-TOKEN"


class HostAlertsRouteTest(HostAlertsCase):
    def setUp(self):
        super().setUp()
        self.store = self.scratch / "state/console/events.sqlite3"
        self.registry = self.scratch / "state/fleet/registry.json"
        self.stderr = io.StringIO()
        redirect = contextlib.redirect_stderr(self.stderr)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def start(self, panel=True):
        extra = {"host_alerts": Panel(self.settings, api=self.bot.api)} if panel else {}
        return support.service(self, self.store, self.registry, **extra)

    def post(self, svc, path, body, token=True):
        headers = {"Origin": f"http://127.0.0.1:{svc.address[1]}",
                   "Content-Type": "application/json"}
        if token:
            headers["X-Console-Token"] = (self.store.parent / "page-token").read_text().strip()
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        status, _, answer = support.post_page(svc.address, path, headers, payload)
        return status, answer

    def host_alerts_of(self, svc):
        return json.loads(svc.view_bytes)["host_alerts"]

    def test_saving_writes_a_private_file_and_the_token_stays_out_of_the_log_and_page_state(self):
        svc = self.start()
        before = support.log_rows(self.store)
        got = self.post(svc, SAVE_PATH, {"bot_token": TOKEN, "chat_id": "-1001234"})
        self.assertEqual(got, (204, b""))
        self.assertEqual(read_settings(self.settings), Settings(True, TOKEN, "-1001234"))
        self.assertEqual(stat.S_IMODE(self.settings.stat().st_mode), 0o600)
        self.assertEqual(support.log_rows(self.store), before)
        self.assertEqual(self.host_alerts_of(svc), {
            "token_set": True, "chat_id": "-1001234", "enabled": True, "problem": None})
        self.assertNotIn(b"SECRET-TOKEN", svc.view_bytes)
        for path in sorted(self.store.parent.rglob("*")):
            if path.is_file():
                with self.subTest(file=path.name):
                    self.assertNotIn(b"SECRET-TOKEN", path.read_bytes())
        self.assertNotIn("SECRET-TOKEN", self.stderr.getvalue())

    def test_the_chat_list_shows_the_feeds_chats_and_a_typed_chat_is_saved_when_it_is_empty(self):
        svc = self.start()
        self.bot.body = {"ok": True, "result": [
            {"update_id": 1, "message": {"chat": {"id": -1001234, "title": "Ops"}}},
            {"update_id": 2, "message": {"chat": {"id": 42, "first_name": "Anis",
                                                  "last_name": "S"}}},
            {"update_id": 3, "message": {"chat": {"id": -77, "title": "ops 123:SECRET-TOKEN"}}}]}
        answers = []
        status, raw = self.post(svc, CHATS_PATH, {"bot_token": TOKEN})
        answers.append(raw)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw), {"chats": [
            {"id": "-1001234", "title": "Ops"}, {"id": "42", "title": "Anis S"},
            {"id": "-77", "title": "-77"}], "text": None})
        self.assertFalse(self.settings.exists())
        self.bot.body = {"ok": True, "result": []}
        status, raw = self.post(svc, CHATS_PATH, {"bot_token": TOKEN})
        answers.append(raw)
        self.assertEqual((status, json.loads(raw)), (200, {"chats": [], "text": EMPTY_FEED}))
        got = self.post(svc, SAVE_PATH, {"bot_token": TOKEN, "chat_id": "-1009876"})
        self.assertEqual(got, (204, b""))
        self.assertEqual(read_settings(self.settings).chat_id, "-1009876")
        status, raw = self.post(svc, CHATS_PATH, {})
        answers.append(raw)
        self.assertEqual(status, 200)
        self.assertEqual(self.bot.requests[-1]["path"], "/bot123:SECRET-TOKEN/getUpdates")
        for raw in answers:
            self.assertNotIn(b"SECRET-TOKEN", raw)

    def test_send_test_shows_delivered_or_telegrams_refusal_without_the_token(self):
        self.write(SETTINGS)
        svc = self.start()
        raws = []

        def sent(status, body):
            self.bot.status, self.bot.body = status, body
            code, raw = self.post(svc, TEST_PATH, {})
            raws.append(raw)
            self.assertEqual(code, 200)
            return json.loads(raw)

        self.assertEqual(sent(200, {"ok": True}), {"delivered": True, "text": DELIVERED})
        self.assertEqual(self.bot.requests[-1]["body"],
                         {"chat_id": "-1001234", "text": TEST_MESSAGE})
        self.assertEqual(sent(401, {"ok": False}), {
            "delivered": False,
            "text": "Not delivered: Telegram refused the bot token (HTTP 401)."})
        blocked = sent(403, {"ok": False, "description": "Forbidden: bot was blocked by the user"})
        absent = sent(403, {"ok": False,
                            "description": "Forbidden: bot is not a member of the channel chat"})
        self.assertEqual(blocked["text"],
                         "Not delivered: the chat's owner blocked the bot (HTTP 403).")
        self.assertEqual(absent["text"],
                         "Not delivered: the bot is not a member of that chat (HTTP 403).")
        self.assertEqual(
            sent(400, {"ok": False, "description": "Bad Request: 123:SECRET-TOKEN"})["text"],
            "Not delivered: Telegram refused the message (HTTP 400).")
        for raw in raws:
            self.assertNotIn(b"SECRET-TOKEN", raw)
        self.assertNotIn("SECRET-TOKEN", self.stderr.getvalue())

    def test_switching_off_writes_enabled_false_and_the_sender_then_only_records(self):
        self.write(SETTINGS)
        svc = self.start()
        self.assertEqual(self.post(svc, SWITCH_PATH, {"enabled": False}), (204, b""))
        self.assertEqual(json.loads(self.settings.read_text()),
                         {"enabled": False, "bot_token": TOKEN, "chat_id": "-1001234"})
        self.assertFalse(self.host_alerts_of(svc)["enabled"])
        sent = len(self.bot.requests)
        outcome = host_alerts.deliver("jetsam", TEXT, settings=self.settings, log=self.log,
                                      api=self.bot.api, now=NOW)
        self.assertEqual(outcome, Outcome("disabled", None))
        self.assertEqual(len(self.bot.requests), sent)
        self.assertEqual(self.log.read_text(),
                         f"2026-11-24T12:00:00 jetsam recorded only, alerts disabled: {TEXT}\n")
        self.assertEqual(self.post(svc, SWITCH_PATH, {"enabled": True}), (204, b""))
        self.assertTrue(json.loads(self.settings.read_text())["enabled"])

    def test_a_refused_chat_list_answers_502_in_owner_words_and_logs_no_token(self):
        svc = self.start()
        self.bot.status, self.bot.body = 401, {"ok": False}
        got = self.post(svc, CHATS_PATH, {"bot_token": TOKEN})
        self.assertEqual(got, (502, b"Telegram did not give the bot's chats: "
                                    b"Telegram refused the bot token (HTTP 401).\n"))
        self.assertEqual(self.stderr.getvalue(), "console: host_alerts_chats_failed\n")

    def test_without_a_panel_every_host_alerts_route_is_refused(self):
        svc = self.start(panel=False)
        bodies = {SAVE_PATH: {"bot_token": TOKEN, "chat_id": "-1"}, SWITCH_PATH: {"enabled": False},
                  CHATS_PATH: {"bot_token": TOKEN}, TEST_PATH: {}}
        for path, body in bodies.items():
            with self.subTest(path=path):
                self.assertEqual(self.post(svc, path, body), (409, (UNAVAILABLE + "\n").encode()))
        self.assertFalse(self.settings.exists())
        self.assertEqual(self.bot.requests, [])
        self.assertIsNone(self.host_alerts_of(svc))

    def test_the_host_alerts_routes_refuse_bad_bodies_and_an_early_switch_on(self):
        svc = self.start()
        before = support.log_rows(self.store)
        self.assertEqual(self.post(svc, SAVE_PATH, {"chat_id": "-1"}),
                         (409, (NO_TOKEN + "\n").encode()))
        self.assertEqual(self.post(svc, SAVE_PATH, {"bot_token": "123:a/b", "chat_id": "-1"}),
                         (400, b"bad host alerts\n"))
        self.assertEqual(self.post(svc, SWITCH_PATH, b'{"enabled": false, "enabled": true}'),
                         (400, b"bad host alerts\n"))
        self.assertEqual(self.post(svc, SAVE_PATH, b"x" * 4097), (413, b"too large\n"))
        self.assertEqual(self.post(svc, SWITCH_PATH, {"enabled": True}),
                         (409, (NOT_READY + "\n").encode()))
        self.assertEqual(support.log_rows(self.store), before)
        self.assertFalse(self.settings.exists())
        self.assertEqual(
            self.post(svc, SAVE_PATH, {"bot_token": TOKEN, "chat_id": "-1"}, token=False),
            (403, b"token refused\n"))

    def test_a_guest_view_carries_no_host_alerts(self):
        self.assertIsNone(guest.OWNER_ONLY_INPUTS["host_alerts"])
        self.assertIsNone(guest.scoped({"host_alerts": {"token_set": True}},
                                       frozenset())["host_alerts"])
        owner = view.derive_view([], host_alerts={
            "token_set": True, "chat_id": "-1", "enabled": True, "problem": None})
        self.assertEqual(owner["host_alerts"]["chat_id"], "-1")
        self.assertIsNone(guest.scrub(owner)["host_alerts"])
        self.assertIsNone(view.derive_view([])["host_alerts"])

    def test_a_saved_file_holding_the_token_in_the_wrong_place_never_reaches_the_view(self):
        self.write({**SETTINGS, "chat_id": TOKEN})
        svc = self.start()
        self.assertEqual(self.host_alerts_of(svc), {
            "token_set": False, "chat_id": None, "enabled": False, "problem": PROBLEM})
        self.assertNotIn(b"SECRET-TOKEN", svc.view_bytes)
        self.assertEqual(self.post(svc, CHATS_PATH, {}), (409, (NO_TOKEN + "\n").encode()))
        self.assertEqual(self.bot.requests, [])
        status, raw = self.post(svc, TEST_PATH, {})
        self.assertEqual((status, json.loads(raw)), (200, {
            "delivered": False, "text": "Not delivered: the saved settings could not be read."}))
        self.assertEqual(self.bot.requests, [])


class ConsoleFlagTest(unittest.TestCase):
    """`console --host-alerts` gives the service the owner's panel on the file the watcher reads."""

    class Stop(Exception):
        pass

    def kwargs_of(self, home, argv):
        recorded = {}

        def stop(*args, **kwargs):
            recorded.update(kwargs)
            raise self.Stop

        with mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.object(console.service, "ConsoleService", side_effect=stop):
            with self.assertRaises(self.Stop):
                console.main(argv)
        return recorded

    def test_the_flag_gives_the_service_the_owners_panel(self):
        with tempfile.TemporaryDirectory() as home:
            shown = self.kwargs_of(home, ["--port", "0", "--host-alerts"])
            hidden = self.kwargs_of(home, ["--port", "0"])
            self.assertEqual(shown["host_alerts"],
                             Panel(Path(home) / ".config/host-alerts/telegram.json"))
            self.assertIsNone(hidden["host_alerts"])


if __name__ == "__main__":
    unittest.main()
