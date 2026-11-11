"""Read the unified rate-limit headers of one upstream reply, and the account that made the request (#860).

`reading(http_status, headers)` returns `None` (no reading) or this document, with keys exactly these:

    {"http_status": 429, "status": "rejected", "reset": 1794816000,
     "binding": "7d", "claim": "seven_day",
     "windows": {"7d": {"status": "rejected", "utilization": 1.0, "reset": 1794816000},
                 "5h": {"status": "allowed", "utilization": 0.0, "reset": 1794430800}}}

Header names are compared case-insensitively, the first value of a name wins and values are stripped.

- No `anthropic-ratelimit-unified-status` header, or a lowercased value not matching
  `^[a-z0-9_]{1,40}$`, gives `None`.
- `reset` is read from `-reset` and `windows.<w>.reset` from `-<w>-reset`: an integer only when the
  value matches `^[0-9]{1,11}$` and is at least 1 (so `1 <= reset < 10**11`), else `null`.
- `claim` is read from `-representative-claim`: the lowercased token when it matches
  `^[a-z0-9_]{1,40}$`, else `null`. `binding` is `"5h"` for `five_hour`, `"7d"` for any claim starting
  `seven_day`, else `null`.
- `windows.<w>` for `w` in `5h`, `7d` is present only when at least one of `-<w>-status`,
  `-<w>-utilization`, `-<w>-reset` is present. Its `status` is a token as above or `null`; its
  `utilization` is `float(value)` only when the value matches `^[0-9]+(\\.[0-9]+)?$` and
  `float(value) <= 10.0` (an over-long digit string becomes `inf` and fails the bound), else `null`.
- These numeric bounds are exactly those the console's `capacity.parse_report` accepts: every document
  `report_document` returns passes it unchanged.
- No other header is read: overage, fallback, organization and `retry-after` values never enter the result.

`identity(body)` returns `(account, session_id)` from the request body, each `None` when absent or
unusable. `json.loads(body)` must give an object whose `metadata.user_id` is a string. A `user_id`
starting with `{` is decoded as JSON and `account_uuid` and `session_id` are read from it; otherwise it
must fully match `^user_[0-9a-f]+_account_([0-9a-fA-F-]*)_session_([0-9a-fA-F-]+)$`. Each id is kept only
when it matches `^[A-Za-z0-9-]{1,64}$` (an empty account is `None`). `device_id` and every other member
are never returned, and no decoding error escapes.

`report_document(http_status, headers, body)` is `reading(...)` plus `"account"` and `"session_id"` from
`identity(body)`; `identity` is called only when the reading is not `None`.
"""

import json
import re
from collections.abc import Iterable

PREFIX = "anthropic-ratelimit-unified-"
WINDOWS = ("5h", "7d")
MAX_UTILIZATION = 10.0

_TOKEN = re.compile(r"[a-z0-9_]{1,40}")
_RESET = re.compile(r"[0-9]{1,11}")
_UTILIZATION = re.compile(r"[0-9]+(\.[0-9]+)?")
_LEGACY_USER = re.compile(r"user_[0-9a-f]+_account_([0-9a-fA-F-]*)_session_([0-9a-fA-F-]+)")
_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


def _token(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.lower()
    return value if _TOKEN.fullmatch(value) else None


def _reset(value: str | None) -> int | None:
    if value is None or not _RESET.fullmatch(value):
        return None
    number = int(value)
    return number if number >= 1 else None


def _utilization(value: str | None) -> float | None:
    if value is None or not _UTILIZATION.fullmatch(value):
        return None
    number = float(value)
    return number if number <= MAX_UTILIZATION else None


def reading(http_status: int, headers: Iterable[tuple[str, str]]) -> dict | None:
    """The unified limit reading of one reply, or `None` when it carries none."""
    found: dict[str, str] = {}
    for name, value in headers:
        name = name.lower()
        if name.startswith(PREFIX):
            found.setdefault(name[len(PREFIX):], value.strip())
    status = _token(found.get("status"))
    if status is None:
        return None
    claim = _token(found.get("representative-claim"))
    if claim == "five_hour":
        binding = "5h"
    elif claim is not None and claim.startswith("seven_day"):
        binding = "7d"
    else:
        binding = None
    windows = {}
    for window in WINDOWS:
        keys = [f"{window}-{field}" for field in ("status", "utilization", "reset")]
        if any(key in found for key in keys):
            windows[window] = {
                "status": _token(found.get(keys[0])),
                "utilization": _utilization(found.get(keys[1])),
                "reset": _reset(found.get(keys[2])),
            }
    return {
        "http_status": http_status,
        "status": status,
        "reset": _reset(found.get("reset")),
        "binding": binding,
        "claim": claim,
        "windows": windows,
    }


def _identifier(value: object) -> str | None:
    return value if isinstance(value, str) and _ID.fullmatch(value) else None


def identity(body: bytes) -> tuple[str | None, str | None]:
    """`(account, session_id)` named by the request body's `metadata.user_id`; never raises."""
    try:
        document = json.loads(body)
        user_id = document["metadata"]["user_id"]
        if not isinstance(user_id, str):
            return None, None
        if user_id.startswith("{"):
            members = json.loads(user_id)
            return _identifier(members.get("account_uuid")), _identifier(members.get("session_id"))
        legacy = _LEGACY_USER.fullmatch(user_id)
        if legacy is None:
            return None, None
        return _identifier(legacy.group(1)), _identifier(legacy.group(2))
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return None, None


def report_document(http_status: int, headers: Iterable[tuple[str, str]], body: bytes) -> dict | None:
    """`reading(...)` with the request's `account` and `session_id`, or `None` without a reading."""
    document = reading(http_status, headers)
    if document is None:
        return None
    account, session_id = identity(body)
    return {**document, "account": account, "session_id": session_id}
