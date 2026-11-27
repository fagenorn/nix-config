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

`send_test` posts `TEST_MESSAGE` whether or not `enabled` is true, writes no log line and
answers whether Telegram accepted it; refused settings or a missing token or chat id answer
False without a request.
"""

import http.client
import json
import os
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


def write_settings(settings: Settings, path: Path | None = None) -> None:
    path = path if path is not None else settings_path()
    if not isinstance(settings.enabled, bool):
        raise ValueError("enabled is not a boolean")
    if settings.enabled and (_token(settings.bot_token) is None or _token(settings.chat_id) is None):
        raise ValueError("enabled settings need a bot_token and a chat_id")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
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


def send_message(settings: Settings, text: str, *, api: str = API, timeout: float = 20.0) -> tuple[bool, str]:
    try:
        request = urllib.request.Request(
            f"{api}/bot{settings.bot_token}/sendMessage",
            data=json.dumps({"chat_id": settings.chat_id, "text": text}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = response.status
            body = json.loads(response.read(MAX_RESPONSE_BYTES))
    except urllib.error.HTTPError as error:
        return False, f"HTTP {error.code}"
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as error:
        return False, type(error).__name__
    if code != 200:
        return False, f"HTTP {code}"
    if not (isinstance(body, dict) and body.get("ok") is True):
        return False, "ok false"
    return True, ""


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


def send_test(path: Path | None = None, *, api: str = API) -> bool:
    try:
        loaded = read_settings(path)
    except SettingsError:
        return False
    if loaded.bot_token is None or loaded.chat_id is None:
        return False
    return send_message(loaded, TEST_MESSAGE, api=api)[0]
