"""The host-alerts settings file and the Telegram sender that reads it.

The settings file is `~/.config/host-alerts/telegram.json` under the owner's home (`HOME` read
at call time), a regular file owned by the reading user with mode 0600 or narrower, in a
directory of mode 0700. It is one JSON object: `enabled` (a boolean), `bot_token` and
`chat_id` (a non-empty string; `chat_id` may also be a non-boolean integer, read as its
decimal string). When `enabled` is true both `bot_token` and `chat_id` must be present; when
it is false either may be null.

`read_settings` refuses a file that is missing, unreadable (a symlink included), not regular,
owned by another uid, wider than 0600, not a JSON object or lacking a field, with a
`SettingsError` that names the path and the reason and never a field's value.
`write_settings` writes the same object atomically with mode 0600 and raises `ValueError`
for settings the reader would refuse, writing nothing.

`send_message` posts one message to the Telegram bot API and answers `(accepted, reason)`:
accepted only on HTTP 200 with `"ok": true`, else the reason is `HTTP <code>`, `ok false` or
an exception class name. It never raises and never shows the token, the URL or the exception text.

`deliver(kind, text)` is the alert entry point and answers an `Outcome`:
- `sent`: Telegram accepted the alert; nothing is logged.
- `disabled`: `enabled` is false; the alert is recorded in the log only.
- `failed`: the settings were refused or Telegram did not accept the alert; `error` says why
  and, unless `record_failure` is false, the alert and the reason are logged.
The log is `~/.local/state/host-alerts/alerts.log` (mode 0600, directory 0700), one line per
recorded alert: `<ISO time> <kind> recorded only, alerts disabled: <text>` or
`<ISO time> <kind> not sent (<reason>): <text>`.

`SettingsMissing`, a `SettingsError`, is the refusal of a missing file alone; `record_note` adds a
`<ISO time> <kind> <text>` line to the log.

`send_test_result` posts `TEST_MESSAGE` whether or not `enabled` is true, writes no log line and
answers `(delivered, reason)`. Without a request the reason is `settings missing` (no file),
`settings refused` (the file is refused, or the token fails `valid_token` or the chat fails
`valid_chat`) or `settings incomplete` (no token or no chat id). Otherwise it is the request's
reason: `HTTP <code>` with the fixed cause `CAUSES` names, `ok false` or an exception class name.
`send_test` answers only whether Telegram accepted it.

`CAUSES` rows `(status, needle, cause)` turn an HTTP error body into a fixed cause: the first
row with that status whose needle is in the lowercased `description` of the JSON error body.
Telegram's own words are never returned, and `send_message` keeps its plain `HTTP <code>`.

`TOKEN_PATTERN` and `CHAT_PATTERN` are what `valid_token` and `valid_chat` accept: a `str` that
fully matches (`<digits>:<token characters>`; a numeric chat id, or `@username`).

`list_chats(bot_token)` posts `getUpdates` with an empty JSON body (it confirms no update) and
answers `(chats, reason)`: each `Chat(id, title)` once, in order of first appearance, read from
the `chat` of each `UPDATE_KINDS` member of every update. The title is the chat's title, else
its first and last names, else `@username`, else its type, else its id, cut to 128 characters;
a title that holds the token is shown as the id. The reason is `""`, `bad token` (nothing is
requested), `HTTP <code>` with its cause, `ok false` or an exception class name; the token is
never in it.

`write_settings` refuses a settings folder that is a symlink, not a directory or owned by
another uid with a `SettingsError` before it creates a file, and makes a wider folder 0700.
"""

import http.client
import json
import os
import re
import stat
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

API = "https://api.telegram.org"
RELATIVE_SETTINGS = Path(".config/host-alerts/telegram.json")
RELATIVE_LOG = Path(".local/state/host-alerts/alerts.log")
TEST_MESSAGE = "Host alerts test: Telegram delivery from this host works."
MAX_RESPONSE_BYTES = 65536
TOKEN_PATTERN = re.compile(r"[0-9]{1,20}:[A-Za-z0-9_-]{1,200}")
CHAT_PATTERN = re.compile(r"-?[0-9]{1,20}|@[A-Za-z0-9_]{5,32}")
UPDATE_KINDS = ("message", "edited_message", "channel_post", "edited_channel_post",
                "my_chat_member", "chat_member", "chat_join_request")
# (HTTP status, lowercase needle in Telegram's description, fixed cause shown instead of it)
CAUSES: tuple[tuple[int, str, str], ...] = (
    (400, "chat not found", "chat not found"),
    (403, "blocked by the user", "blocked by the user"),
    (403, "not a member", "not a member"),
    (403, "kicked", "removed from the chat"),
    (409, "webhook is active", "webhook set"),
    (409, "terminated by other getupdates request", "another reader"),
)


@dataclass(frozen=True)
class Chat:
    id: str
    title: str


@dataclass(frozen=True)
class Settings:
    enabled: bool
    bot_token: str | None = field(default=None, repr=False)
    chat_id: str | None = None


@dataclass(frozen=True)
class Outcome:
    status: str
    error: str | None
    missing: bool = False


class SettingsError(Exception):
    pass


class SettingsMissing(SettingsError):
    """There is no settings file: alerts are not configured on this host, which is not a refusal."""


def settings_path(home: Path | None = None) -> Path:
    return (home if home is not None else Path.home()) / RELATIVE_SETTINGS


def log_path(home: Path | None = None) -> Path:
    return (home if home is not None else Path.home()) / RELATIVE_LOG


def _token(value) -> str | None:
    return value if isinstance(value, str) and value else None


def _chat(value) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return _token(value)


def read_settings(path: Path | None = None, *, uid: int | None = None) -> Settings:
    path = path if path is not None else settings_path()
    uid = uid if uid is not None else os.geteuid()
    try:
        # O_NONBLOCK: a FIFO with no writer must open (and be refused below), not block the caller.
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise SettingsMissing(f"settings file {path} is missing") from None
    except OSError as error:
        raise SettingsError(f"settings file {path} is unreadable ({type(error).__name__})") from None
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise SettingsError(f"settings file {path} is not a regular file")
        if status.st_uid != uid:
            raise SettingsError(f"settings file {path} is owned by uid {status.st_uid}, not {uid}")
        if stat.S_IMODE(status.st_mode) & ~0o600:
            raise SettingsError(
                f"settings file {path} has mode {stat.S_IMODE(status.st_mode):04o}, wider than 0600")
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                document = json.loads(handle.read())
        except (OSError, ValueError):
            document = None
    finally:
        os.close(descriptor)
    if not isinstance(document, dict):
        raise SettingsError(f"settings file {path} is not a JSON object")
    enabled = document.get("enabled")
    token = _token(document.get("bot_token"))
    chat = _chat(document.get("chat_id"))
    failing = []
    if not isinstance(enabled, bool):
        failing.append("enabled")
    elif enabled:
        if token is None:
            failing.append("bot_token")
        if chat is None:
            failing.append("chat_id")
    if failing:
        raise SettingsError(f"settings file {path} lacks {', '.join(failing)}")
    return Settings(enabled, token, chat)


def write_settings(settings: Settings, path: Path | None = None, *, uid: int | None = None) -> None:
    path = path if path is not None else settings_path()
    uid = uid if uid is not None else os.geteuid()
    if not isinstance(settings.enabled, bool):
        raise ValueError("enabled is not a boolean")
    if settings.enabled and (_token(settings.bot_token) is None or _token(settings.chat_id) is None):
        raise ValueError("enabled settings need a bot_token and a chat_id")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except FileExistsError:
        pass  # a non-directory is named by the check below
    folder = os.lstat(path.parent)
    if stat.S_ISLNK(folder.st_mode):
        reason = "a symlink"
    elif not stat.S_ISDIR(folder.st_mode):
        reason = "not a directory"
    elif folder.st_uid != uid:
        reason = f"owned by uid {folder.st_uid}, not {uid}"
    else:
        reason = ""
    if reason:
        raise SettingsError(f"settings folder {path.parent} is {reason}")
    if stat.S_IMODE(folder.st_mode) & 0o077:
        os.chmod(path.parent, 0o700)
    body = json.dumps(
        {"enabled": settings.enabled, "bot_token": settings.bot_token, "chat_id": settings.chat_id},
        indent=2) + "\n"
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(body)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def valid_token(value: object) -> bool:
    return isinstance(value, str) and TOKEN_PATTERN.fullmatch(value) is not None


def valid_chat(value: object) -> bool:
    return isinstance(value, str) and CHAT_PATTERN.fullmatch(value) is not None


def _cause(status: int, error: urllib.error.HTTPError) -> str:
    """The fixed cause an error body names, or "" (Telegram's own words are never returned)."""
    try:
        document = json.loads(error.read(MAX_RESPONSE_BYTES))
    except (OSError, http.client.HTTPException, ValueError):
        return ""
    description = document.get("description") if isinstance(document, dict) else None
    if not isinstance(description, str):
        return ""
    lowered = description.lower()
    for code, needle, cause in CAUSES:
        if code == status and needle in lowered:
            return cause
    return ""


def _call(token: str | None, method: str, payload: dict, api: str, timeout: float) -> tuple[object, str, str]:
    """One bot API POST: `(body | None, reason, cause)`; never raises, never shows the token."""
    try:
        request = urllib.request.Request(
            f"{api}/bot{token}/{method}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = response.status
            body = json.loads(response.read(MAX_RESPONSE_BYTES))
    except urllib.error.HTTPError as error:
        return None, f"HTTP {error.code}", _cause(error.code, error)
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as error:
        return None, type(error).__name__, ""
    if code != 200:
        return None, f"HTTP {code}", ""
    return body, "", ""


def send_message(settings: Settings, text: str, *, api: str = API, timeout: float = 20.0) -> tuple[bool, str]:
    body, reason, _ = _call(settings.bot_token, "sendMessage",
                            {"chat_id": settings.chat_id, "text": text}, api, timeout)
    if reason:
        return False, reason
    if not (isinstance(body, dict) and body.get("ok") is True):
        return False, "ok false"
    return True, ""


def _title(chat: dict, chat_id: str, token: str) -> str:
    names = " ".join(name for name in (chat.get("first_name"), chat.get("last_name"))
                     if isinstance(name, str) and name)
    username = chat.get("username")
    candidates = (
        chat.get("title"),
        names,
        f"@{username}" if isinstance(username, str) and username else "",
        chat.get("type"),
    )
    title = next((text for text in candidates if isinstance(text, str) and text), chat_id)
    return chat_id if token in title else title[:128]


def list_chats(bot_token: str, *, api: str = API, timeout: float = 20.0) -> tuple[tuple[Chat, ...], str]:
    """The chats the bot's pending updates name, each once, and a reason ("" on success)."""
    if not valid_token(bot_token):
        return (), "bad token"
    body, reason, cause = _call(bot_token, "getUpdates", {}, api, timeout)
    if reason:
        return (), f"{reason} {cause}" if cause else reason
    result = body.get("result") if isinstance(body, dict) and body.get("ok") is True else None
    if not isinstance(result, list):
        return (), "ok false"
    chats: dict[str, Chat] = {}
    for update in result:
        if not isinstance(update, dict):
            continue
        for kind in UPDATE_KINDS:
            part = update.get(kind)
            chat = part.get("chat") if isinstance(part, dict) else None
            identifier = chat.get("id") if isinstance(chat, dict) else None
            if isinstance(identifier, int) and not isinstance(identifier, bool):
                key = str(identifier)
                if key not in chats:
                    chats[key] = Chat(key, _title(chat, key, bot_token))
    return tuple(chats.values()), ""


def _record(log: Path, line: str) -> None:
    log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, line.encode())
    finally:
        os.close(descriptor)


def record_note(kind: str, text: str, *, log: Path | None = None, now: datetime | None = None) -> None:
    """Add one `<ISO time> <kind> <text>` line to the log, for a note that is not an alert."""
    stamp = (now if now is not None else datetime.now().astimezone()).isoformat(timespec="seconds")
    _record(log if log is not None else log_path(), f"{stamp} {kind} {text}\n")


def deliver(
    kind: str,
    text: str,
    *,
    settings: Path | None = None,
    log: Path | None = None,
    api: str = API,
    now: datetime | None = None,
    record_failure: bool = True,
) -> Outcome:
    log = log if log is not None else log_path()
    stamp = (now if now is not None else datetime.now().astimezone()).isoformat(timespec="seconds")
    try:
        loaded = read_settings(settings)
    except SettingsError as error:
        outcome = Outcome("failed", str(error), isinstance(error, SettingsMissing))
    else:
        if not loaded.enabled:
            _record(log, f"{stamp} {kind} recorded only, alerts disabled: {text}\n")
            return Outcome("disabled", None)
        accepted, reason = send_message(loaded, text, api=api)
        if accepted:
            return Outcome("sent", None)
        outcome = Outcome("failed", f"telegram did not accept the alert ({reason})")
    if record_failure:
        _record(log, f"{stamp} {kind} not sent ({outcome.error}): {text}\n")
    return outcome


def send_test_result(path: Path | None = None, *, api: str = API) -> tuple[bool, str]:
    try:
        loaded = read_settings(path)
    except SettingsMissing:
        return False, "settings missing"
    except SettingsError:
        return False, "settings refused"
    if loaded.bot_token is None or loaded.chat_id is None:
        return False, "settings incomplete"
    if not (valid_token(loaded.bot_token) and valid_chat(loaded.chat_id)):
        return False, "settings refused"
    body, reason, cause = _call(loaded.bot_token, "sendMessage",
                                {"chat_id": loaded.chat_id, "text": TEST_MESSAGE}, api, 20.0)
    if reason:
        return False, f"{reason} {cause}" if cause else reason
    if not (isinstance(body, dict) and body.get("ok") is True):
        return False, "ok false"
    return True, ""


def send_test(path: Path | None = None, *, api: str = API) -> bool:
    return send_test_result(path, api=api)[0]
