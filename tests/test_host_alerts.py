"""The host-alerts settings file and its Telegram sender, against a local stand-in for the bot API.

Runs `agent_tools.hosts.host_alerts` with a scratch settings file and log and a loopback server
that records each request: what is posted, what each refusal logs, and that no failure shows the
bot token.
Run: just agent-workflow-tests
"""

import errno
import http.server
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
import unittest
from datetime import datetime
from unittest import mock

from agent_tools.hosts.host_alerts import (
    Outcome,
    RELATIVE_LOG,
    RELATIVE_SETTINGS,
    Settings,
    SettingsError,
    TEST_MESSAGE,
    deliver,
    log_path,
    read_settings,
    send_test,
    settings_path,
    write_settings,
)

TIER = "fast"

SETTINGS = {"enabled": True, "bot_token": "123:SECRET-TOKEN", "chat_id": "-1001234"}
TEXT = "eleven-m5: test text"
NOW = datetime(2026, 11, 24, 12, 0)
PROXY_VARIABLES = ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY")


class Bot:
    """A loopback server that records each request and answers the status and body set."""

    def __init__(self):
        self.requests = []
        self.status = 200
        self.body = {"ok": True, "result": {}}
        bot = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                bot.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type"),
                    "body": json.loads(raw),
                })
                payload = json.dumps(bot.body).encode()
                self.send_response(bot.status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.api = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class HostAlertsCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in PROXY_VARIABLES:
            os.environ.pop(name, None)
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.settings = self.scratch / "cfg" / "telegram.json"
        self.log = self.scratch / "state" / "alerts.log"
        self.bot = Bot()
        self.addCleanup(self.bot.close)

    def write(self, content=SETTINGS, mode=0o600):
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        text = content if isinstance(content, str) else json.dumps(content)
        self.settings.write_text(text)
        self.settings.chmod(mode)

    def call(self, **kw):
        return deliver("jetsam", TEXT, settings=self.settings, log=self.log, api=self.bot.api, now=NOW, **kw)

    def log_lines(self):
        return self.log.read_text().splitlines(keepends=True)


class DeliverTest(HostAlertsCase):
    def test_an_alert_is_posted_to_the_bot_with_the_chat_id(self):
        self.write()
        outcome = self.call()
        self.assertEqual(outcome, Outcome("sent", None))
        self.assertEqual(self.bot.requests, [{
            "method": "POST",
            "path": "/bot123:SECRET-TOKEN/sendMessage",
            "content_type": "application/json",
            "body": {"chat_id": "-1001234", "text": TEXT},
        }])
        self.assertFalse(self.log.exists())

    def test_a_missing_file_logs_the_alert_and_fails(self):
        outcome = self.call()
        error = f"settings file {self.settings} is missing"
        self.assertEqual(outcome, Outcome("failed", error))
        self.assertEqual(self.bot.requests, [])
        self.assertEqual(self.log.read_text(), f"2026-11-24T12:00:00 jetsam not sent ({error}): {TEXT}\n")
        self.assertEqual(stat.S_IMODE(self.log.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.log.parent.stat().st_mode), 0o700)

    def test_an_unreadable_file_fails(self):
        self.write(mode=0o000)
        real_open = os.open

        def refuse_settings(path, *args, **kwargs):
            if Path(path) == self.settings:
                raise PermissionError(errno.EACCES, "Permission denied")
            return real_open(path, *args, **kwargs)

        with mock.patch("os.open", refuse_settings):
            outcome = self.call()
        self.assertEqual(outcome.status, "failed")
        self.assertTrue(outcome.error.endswith("is unreadable (PermissionError)"), outcome.error)
        self.assertEqual(len(self.log_lines()), 1)
        self.assertEqual(self.bot.requests, [])

    def test_a_file_that_is_not_json_fails(self):
        self.write("{")
        outcome = self.call()
        self.assertEqual(outcome.status, "failed")
        self.assertTrue(outcome.error.endswith("is not a JSON object"), outcome.error)
        self.assertEqual(len(self.log_lines()), 1)

    def test_a_file_wider_than_0600_is_refused(self):
        for mode in (0o644, 0o604, 0o700):
            with self.subTest(mode=oct(mode)):
                self.write(mode=mode)
                outcome = self.call()
                self.assertEqual(outcome.status, "failed")
                self.assertTrue(outcome.error.endswith(f"has mode {mode:04o}, wider than 0600"), outcome.error)
                self.assertEqual(self.bot.requests, [])
        self.write(mode=0o400)
        self.assertEqual(self.call().status, "sent")

    def test_a_file_owned_by_another_uid_is_refused(self):
        self.write()
        other = os.getuid() + 1
        with self.assertRaises(SettingsError) as raised:
            read_settings(self.settings, uid=other)
        self.assertTrue(
            str(raised.exception).endswith(f"is owned by uid {os.getuid()}, not {other}"), str(raised.exception))

    def test_an_incomplete_file_names_what_it_lacks(self):
        cases = (
            ({"enabled": True}, "lacks bot_token, chat_id"),
            ({"enabled": True, "bot_token": "", "chat_id": "-1"}, "lacks bot_token"),
            ({"bot_token": "t", "chat_id": "c"}, "lacks enabled"),
            ({"enabled": "yes", "bot_token": "t", "chat_id": "c"}, "lacks enabled"),
        )
        for content, lacks in cases:
            with self.subTest(content=content):
                self.log.unlink(missing_ok=True)
                self.write(content)
                outcome = self.call()
                self.assertEqual(outcome.status, "failed")
                self.assertTrue(outcome.error.endswith(lacks), outcome.error)
                self.assertEqual(len(self.log_lines()), 1)
                self.assertEqual(self.bot.requests, [])

    def test_a_rejected_post_fails_without_showing_the_token(self):
        self.write()
        self.bot.status, self.bot.body = 401, {"ok": False}
        first = self.call()
        self.bot.status, self.bot.body = 200, {"ok": False}
        second = self.call()
        self.assertEqual(first, Outcome("failed", "telegram did not accept the alert (HTTP 401)"))
        self.assertEqual(second, Outcome("failed", "telegram did not accept the alert (ok false)"))
        for shown in (first.error, second.error, self.log.read_bytes().decode()):
            self.assertNotIn("SECRET-TOKEN", shown)

    def test_an_unreachable_api_fails_without_showing_the_token(self):
        self.write()
        with socket.socket() as closed:
            closed.bind(("127.0.0.1", 0))
            port = closed.getsockname()[1]
        outcome = deliver("jetsam", TEXT, settings=self.settings, log=self.log,
                          api=f"http://127.0.0.1:{port}", now=NOW)
        self.assertEqual(outcome, Outcome("failed", "telegram did not accept the alert (URLError)"))
        self.assertNotIn("SECRET-TOKEN", outcome.error)
        self.assertNotIn("SECRET-TOKEN", self.log.read_text())

    def test_a_disabled_file_records_the_alert_only(self):
        self.write({"enabled": False})
        self.assertEqual(self.call(), Outcome("disabled", None))
        self.assertEqual(self.bot.requests, [])
        self.assertEqual(self.log.read_text(), f"2026-11-24T12:00:00 jetsam recorded only, alerts disabled: {TEXT}\n")

    def test_a_retried_failure_writes_no_second_log_line(self):
        outcome = self.call(record_failure=False)
        self.assertEqual(outcome.status, "failed")
        self.assertFalse(self.log.exists())


class SendTestTest(HostAlertsCase):
    def test_send_test_reports_whether_telegram_accepted(self):
        self.write({**SETTINGS, "enabled": False})
        self.assertIs(send_test(self.settings, api=self.bot.api), True)
        self.assertEqual([r["body"]["text"] for r in self.bot.requests], [TEST_MESSAGE])
        self.bot.status, self.bot.body = 401, {"ok": False}
        self.assertIs(send_test(self.settings, api=self.bot.api), False)
        self.assertEqual(len(self.bot.requests), 2)
        self.settings.unlink()
        self.assertIs(send_test(self.settings, api=self.bot.api), False)
        self.assertEqual(len(self.bot.requests), 2)
        self.assertFalse(self.log.exists())


class SettingsFileTest(HostAlertsCase):
    def test_the_settings_path_is_under_the_owners_home(self):
        self.assertEqual(settings_path(Path("/h")), Path("/h/.config/host-alerts/telegram.json"))
        self.assertEqual(log_path(Path("/h")), Path("/h/.local/state/host-alerts/alerts.log"))
        with mock.patch.dict(os.environ, {"HOME": str(self.scratch)}):
            self.assertEqual(settings_path(), self.scratch / RELATIVE_SETTINGS)
            self.assertEqual(log_path(), self.scratch / RELATIVE_LOG)

    def test_written_settings_are_private_and_read_back(self):
        path = self.scratch / "new" / "telegram.json"
        value = Settings(True, "123:SECRET-TOKEN", "-1001234")
        write_settings(value, path)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual(read_settings(path), value)
        self.assertNotIn("SECRET-TOKEN", repr(read_settings(path)))
        refused = self.scratch / "refused" / "telegram.json"
        with self.assertRaises(ValueError):
            write_settings(Settings(True, None, "-1"), refused)
        self.assertFalse(refused.exists())


if __name__ == "__main__":
    unittest.main()
