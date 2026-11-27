"""The `host-alerts-panel` screenshot (tests/console_screenshots.py): the owner's Host alerts panel, opened.

The state is the desk with no sprint, over a console that has a Host alerts panel. Its fixture seeds the
settings of an enabled bot (`TOKEN`, `CHAT`) in the file `host-alerts/telegram.json` under the fixture's own
root, never the real home, and a loopback stand-in for Telegram (`Telegram`) answers the bot's chats and
accepts a test message. The shot opens the panel (`#host-alerts-open`), presses Find chats, picks the one chat
it lists, presses Send test and waits for the result line. The token is never drawn: the page's token field is
an empty password input and the token lives only in the seeded file.

This module imports only the standard library, so the screenshots can run it beside the base commit's
`python/` and draw the before picture: a base console has no `host_alerts` argument, so `service_kwargs`
gives it nothing, writes no file, and its page has no Alerts button, so `open_panel` clicks nothing.
`Panel`, `Settings` and `write_settings` are imported inside `service_kwargs`, after that check.
"""
import http.server
import inspect
import json
import os
import threading
from pathlib import Path

STATE = "host-alerts-panel"
TOKEN = "123456:SHOT-TOKEN"
CHAT = "-1001234"
TITLE = "Owner alerts"
PROXY_VARIABLES = ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY")

UPDATES = {"ok": True, "result": [{"update_id": 1, "message": {"chat": {"id": int(CHAT), "title": TITLE,
                                                                       "type": "group"}}}]}
SENT = {"ok": True, "result": {}}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        answer = UPDATES if self.path.endswith("/getUpdates") else SENT
        body = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args) -> None:
        pass


class Telegram:
    """A loopback stand-in for the Telegram bot API; the proxy variables are removed while it is open."""

    def __init__(self) -> None:
        self._proxies = {name: os.environ.pop(name) for name in PROXY_VARIABLES if name in os.environ}
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.api: str = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
        os.environ.update(self._proxies)


def service_kwargs(constructor, root: Path, api: str) -> dict:
    """The constructor argument that gives a console its Host alerts panel, only when `constructor` takes one."""
    if "host_alerts" not in inspect.signature(constructor).parameters:
        return {}
    from agent_tools.hosts.host_alerts_panel import Panel
    from agent_tools.hosts.host_alerts import Settings, write_settings
    path = root / "host-alerts" / "telegram.json"
    write_settings(Settings(True, TOKEN, CHAT), path)
    return {"host_alerts": Panel(path, api=api)}


def open_panel(page) -> None:
    """Open the panel, find the chats, pick the one listed and send the test, only where the page has the button."""
    if page.query_selector("#host-alerts-open") is None:
        return
    page.click("#host-alerts-open")
    page.wait_for_selector("#host-alerts:not([hidden])")
    page.click("button.alerts-find")
    page.wait_for_selector("button.alerts-chat")
    page.click("button.alerts-chat")
    page.click("button.alerts-test")
    page.wait_for_selector(".alerts-result:not(:empty)")
