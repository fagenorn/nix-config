"""The console's Host alerts panel: strict bodies, the save merge, owner words and route replies.

The panel lets the owner set up the Telegram alerts of `agent_tools.hosts.host_alerts` from the
console page. This module holds every rule; the service only hands it a route, a body and a lock.

Bodies are decoded as UTF-8 and loaded with the strict hooks of `agent_tools.canonical` (a
repeated key and a non-finite number are refused). A body must be an object of exactly these keys:
- save: `{"chat_id"}` or `{"bot_token", "chat_id"}`; the token passes `valid_token`, the chat
  `valid_chat`;
- switch: `{"enabled"}`, a real boolean;
- chats: `{}` or `{"bot_token"}` with a valid token;
- test: `{}`.
Anything else, bad UTF-8 and a body nested too deeply included, is `ValueError(BAD_BODY)`, whose
text never carries a submitted value.

Settings are read through `_current`: the saved settings when the file is readable and its token
and chat, if present, match their patterns; otherwise none. `entry` publishes the owner's view of
them, `{"token_set", "chat_id", "enabled", "problem"}`, and never the token: a missing file is the
plain off entry, and a present but unusable one carries `PROBLEM`.
- `save` writes the typed token or else the saved one (none is `Refused(NO_TOKEN)`), the chat and
  the saved `enabled` (true when nothing is saved). A folder the writer refuses is `Refused(FOLDER)`.
- `switch` on needs a saved token and chat (else `Refused(NOT_READY)`); off keeps the saved values.
- `chats` lists the bot's chats with the typed token or else the saved one; a reason from Telegram
  is `Failed`. `test` sends the test message and answers `(delivered, sentence)`.
- `reason_words` turns a reason of `host_alerts` into the owner's words.

`respond(panel, route, body, *, lock)` answers `(Reply, entry | None)`, in this order:
- no panel: 409 `UNAVAILABLE`;
- a body its parser refuses: 400 `BAD_BODY`, no log line;
- save and switch read, merge and write while holding `lock`, and answer 204 with an empty body and
  the new entry; chats and test hold no lock and answer 200 `application/json`, `{"chats", "text"}`
  and `{"delivered", "text"}` as sorted compact JSON;
- `Refused`: 409 with its sentence; `Failed`: 502 with its sentence; any other exception: 500
  `FAILED` with a log line naming the class, never the message.
A refusal is `text/plain`, the sentence and a newline, the bytes `ConsoleHandler._refuse` writes.

This module never logs or prints: a `Reply` carries the one safe line (or None) for the caller.
"""

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.hosts import host_alerts
from agent_tools.hosts.host_alerts import (
    Settings,
    SettingsError,
    SettingsMissing,
    list_chats,
    read_settings,
    send_test_result,
    valid_chat,
    valid_token,
    write_settings,
)

SAVE_PATH = "/api/host-alerts-save"
SWITCH_PATH = "/api/host-alerts-switch"
CHATS_PATH = "/api/host-alerts-chats"
TEST_PATH = "/api/host-alerts-test"
ROUTES = frozenset({SAVE_PATH, SWITCH_PATH, CHATS_PATH, TEST_PATH})
MAX_BYTES = 4096

UNAVAILABLE = "Host alerts are not set up on this host."
NO_TOKEN = "Enter the bot token: none is saved yet."
NOT_READY = "Save a bot token and a chat first."
FOLDER = "The settings folder is not private to this user, so nothing was saved."
EMPTY_FEED = ("The bot has seen no chat yet. Send it any message in Telegram and press Find chats "
              "again, or type the chat id.")
DELIVERED = "Delivered: Telegram accepted the test message."
NOT_DELIVERED = "Not delivered: {reason}."
CHATS_FAILED = "Telegram did not give the bot's chats: {reason}."
PROBLEM = "The saved settings could not be read; saving again replaces them."
BAD_BODY = "bad host alerts"
FAILED = "host alerts failed"

# Reasons of `host_alerts`, exactly, in the owner's words.
REASONS = {
    "HTTP 401": "Telegram refused the bot token (HTTP 401)",
    "HTTP 404": "Telegram does not know that bot token (HTTP 404)",
    "HTTP 400 chat not found": "Telegram does not know that chat (HTTP 400)",
    "HTTP 400": "Telegram refused the message (HTTP 400)",
    "HTTP 403 blocked by the user": "the chat's owner blocked the bot (HTTP 403)",
    "HTTP 403 not a member": "the bot is not a member of that chat (HTTP 403)",
    "HTTP 403 removed from the chat": "the bot was removed from that chat (HTTP 403)",
    "HTTP 403": "Telegram does not let the bot post there (HTTP 403)",
    "HTTP 409 webhook set": "the bot sends its updates to a webhook, so it has no chat list (HTTP 409)",
    "HTTP 409 another reader": "another program reads the bot's updates (HTTP 409)",
    "ok false": "Telegram answered without accepting it",
    "settings missing": "nothing is saved yet",
    "settings refused": "the saved settings could not be read",
    "settings incomplete": "save a bot token and a chat first",
    "bad token": "that is not a bot token",
}


@dataclass(frozen=True)
class Panel:
    settings: Path
    api: str = host_alerts.API


@dataclass(frozen=True)
class Save:
    bot_token: str | None = field(repr=False)
    chat_id: str


@dataclass(frozen=True)
class Reply:
    status: int
    media: str | None
    body: bytes
    log: str | None


class Refused(Exception):
    """The request is understood but cannot be done now; its text is the owner's sentence."""


class Failed(Exception):
    """Telegram did not answer well; its text is the owner's sentence."""


def _object(body: bytes, members: tuple[frozenset[str], ...]) -> dict:
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except (ValueError, RecursionError):
        raise ValueError(BAD_BODY) from None
    if not isinstance(value, dict) or frozenset(value) not in members:
        raise ValueError(BAD_BODY)
    return value


def parse_save(body: bytes) -> Save:
    value = _object(body, (frozenset({"chat_id"}), frozenset({"bot_token", "chat_id"})))
    token = value.get("bot_token")
    if ("bot_token" in value and not valid_token(token)) or not valid_chat(value["chat_id"]):
        raise ValueError(BAD_BODY)
    return Save(bot_token=token, chat_id=value["chat_id"])


def parse_switch(body: bytes) -> bool:
    enabled = _object(body, (frozenset({"enabled"}),))["enabled"]
    if type(enabled) is not bool:
        raise ValueError(BAD_BODY)
    return enabled


def parse_chats(body: bytes) -> str | None:
    value = _object(body, (frozenset(), frozenset({"bot_token"})))
    token = value.get("bot_token")
    if "bot_token" in value and not valid_token(token):
        raise ValueError(BAD_BODY)
    return token


def parse_test(body: bytes) -> None:
    _object(body, (frozenset(),))


def _read(panel: Panel) -> tuple[Settings | None, bool]:
    """The usable saved settings (or None) and whether the file is simply missing."""
    try:
        saved = read_settings(panel.settings)
    except SettingsMissing:
        return None, True
    except SettingsError:
        return None, False
    if (saved.bot_token is not None and not valid_token(saved.bot_token)) or \
            (saved.chat_id is not None and not valid_chat(saved.chat_id)):
        return None, False
    return saved, False


def _current(panel: Panel) -> Settings | None:
    return _read(panel)[0]


def entry(panel: Panel) -> dict:
    saved, missing = _read(panel)
    if saved is None:
        return {"token_set": False, "chat_id": None, "enabled": False,
                "problem": None if missing else PROBLEM}
    return {"token_set": saved.bot_token is not None, "chat_id": saved.chat_id,
            "enabled": saved.enabled, "problem": None}


def _write(panel: Panel, settings: Settings) -> None:
    try:
        write_settings(settings, panel.settings)
    except SettingsError:
        raise Refused(FOLDER) from None


def save(panel: Panel, request: Save) -> None:
    current = _current(panel)
    token = request.bot_token if request.bot_token is not None else (
        current.bot_token if current is not None else None)
    if token is None:
        raise Refused(NO_TOKEN)
    enabled = current.enabled if current is not None else True
    _write(panel, Settings(enabled, token, request.chat_id))


def switch(panel: Panel, enabled: bool) -> None:
    current = _current(panel)
    token = current.bot_token if current is not None else None
    chat = current.chat_id if current is not None else None
    if enabled and (token is None or chat is None):
        raise Refused(NOT_READY)
    _write(panel, Settings(enabled, token, chat))


def reason_words(reason: str) -> str:
    if reason in REASONS:
        return REASONS[reason]
    parts = reason.split(" ", 2)
    if parts[0] == "HTTP" and len(parts) > 1 and parts[1].isdigit():
        return f"Telegram answered HTTP {parts[1]}"
    return f"Telegram could not be reached ({reason})"


def chats(panel: Panel, bot_token: str | None) -> tuple[list[dict], str | None]:
    if bot_token is None:
        current = _current(panel)
        bot_token = current.bot_token if current is not None else None
    if bot_token is None:
        raise Refused(NO_TOKEN)
    found, reason = list_chats(bot_token, api=panel.api)
    if reason:
        raise Failed(CHATS_FAILED.format(reason=reason_words(reason)))
    listed = [{"id": chat.id, "title": chat.title} for chat in found]
    return listed, (None if listed else EMPTY_FEED)


def test(panel: Panel) -> tuple[bool, str]:
    delivered, reason = send_test_result(panel.settings, api=panel.api)
    if delivered:
        return True, DELIVERED
    return False, NOT_DELIVERED.format(reason=reason_words(reason))


def _refusal(status: int, text: str, log: str | None) -> Reply:
    return Reply(status, "text/plain", text.encode() + b"\n", log)


def _json(document: dict) -> Reply:
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return Reply(200, "application/json", body, None)


def respond(panel: Panel | None, route: str, body: bytes, *,
            lock: threading.Lock) -> tuple[Reply, dict | None]:
    name = route.rsplit("-", 1)[-1]
    if panel is None:
        return _refusal(409, UNAVAILABLE, f"console: host_alerts_refused {name}"), None
    try:
        if route == SAVE_PATH:
            request = parse_save(body)
        elif route == SWITCH_PATH:
            enabled = parse_switch(body)
        elif route == CHATS_PATH:
            typed = parse_chats(body)
        else:
            parse_test(body)
    except ValueError:
        return _refusal(400, BAD_BODY, None), None
    try:
        if route == SAVE_PATH:
            with lock:
                save(panel, request)
                return Reply(204, None, b"", None), entry(panel)
        if route == SWITCH_PATH:
            with lock:
                switch(panel, enabled)
                return Reply(204, None, b"", None), entry(panel)
        if route == CHATS_PATH:
            listed, text = chats(panel, typed)
            return _json({"chats": listed, "text": text}), None
        delivered, text = test(panel)
        return _json({"delivered": delivered, "text": text}), None
    except Refused as error:
        return _refusal(409, str(error), f"console: host_alerts_refused {name}"), None
    except Failed as error:
        return _refusal(502, str(error), "console: host_alerts_chats_failed"), None
    except Exception as error:
        return _refusal(500, FAILED, f"console: host_alerts_failed {name} {type(error).__name__}"), None
