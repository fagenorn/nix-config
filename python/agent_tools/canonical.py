"""Canonical-JSON knowledge shared by the agent tools.

`telemetry_digest` is the telemetry digest format (agent-cost-telemetry D9).
The two hooks are strict-load building blocks: each caller passes exactly the
hooks it applies, so sharing them changes no command's accepted input.
"""

import hashlib
import json
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
