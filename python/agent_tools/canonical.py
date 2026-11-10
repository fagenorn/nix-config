"""Canonical-JSON knowledge shared by the agent tools.

`telemetry_digest` is the telemetry digest format (agent-cost-telemetry D9).
The two hooks are strict-load building blocks: each caller passes exactly the
hooks it applies, so sharing them changes no command's accepted input.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import NoReturn


def telemetry_digest(body: object) -> str:
    """'sha256:' + sha256 over `body` as sorted, compact, ASCII-escaped JSON.

    No trailing newline, and `allow_nan` keeps json's default.
    """
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """`object_pairs_hook`: build the object, refusing the first repeated key."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def reject_nonfinite_literal(name: str) -> NoReturn:
    """`parse_constant` hook; json calls it only for NaN, Infinity and -Infinity."""
    raise ValueError(f"JSON constant {name} is not allowed")


RFC3339_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def parse_rfc3339_utc(value: str) -> datetime:
    """Parse an RFC3339 instant and return an aware UTC datetime."""
    if not isinstance(value, str) or not RFC3339_UTC_RE.fullmatch(value):
        raise ValueError("timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as error:
        raise ValueError("invalid RFC3339 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return parsed.astimezone(timezone.utc)
