"""The keepalive pings of one cache-proxy log (issue 503).

`read_pings` reads the `ping` lines of one log that `cache-proxy --keepalive` writes (through
agent_tools.cache_proxy.LineLog) and prices them through agent_tools.model_pricing; the owner
report matches them to transcripts by conversation handle. python/README.md (agent-costs) holds
the contract.
"""

import json
import math
from dataclasses import dataclass
from datetime import datetime

from agent_tools.agent_costs import parse_rfc3339_utc
from agent_tools.model_pricing import usage_cost


@dataclass(frozen=True)
class Ping:
    ts: datetime          # aware UTC
    conversation: str     # the conversation handle of agent_tools.cache_keepalive
    dollars: float
    priced: bool          # the line had a `usage` object
    approximate: bool     # the model is not in the price table


@dataclass(frozen=True)
class PingLog:
    log: str              # the path as given
    pings: tuple
    skipped: int          # lines that were not JSON objects or were unusable pings


_TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
                 "cache_creation_input_tokens")
_SPLIT_FIELDS = ("ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens")


def _count(value):
    """Whether `value` is a token count the pricing reads: absent (None), or a non-negative
    finite int or float that is not a bool."""
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)
                             and math.isfinite(value) and value >= 0)


def _priceable(usage):
    """Whether model_pricing.usage_cost can price `usage`: every token field it reads is a
    `_count`, and `cache_creation` is absent, null or an object whose split fields are."""
    split = usage.get("cache_creation")
    return (all(_count(usage.get(field)) for field in _TOKEN_FIELDS)
            and (split is None or (isinstance(split, dict)
                                   and all(_count(split.get(field)) for field in _SPLIT_FIELDS))))


def _ping(entry):
    """The Ping of a `ping` object, None when its `ts` or `conversation` is unusable or its
    `usage` is an object that cannot be priced."""
    try:
        ts = parse_rfc3339_utc(entry.get("ts"))
    except ValueError:
        return None
    conversation = entry.get("conversation")
    if not isinstance(conversation, str):
        return None
    usage = entry.get("usage")
    if not isinstance(usage, dict):
        return Ping(ts, conversation, 0.0, False, False)
    if not _priceable(usage):
        return None
    model = entry.get("model")
    dollars, approximate = usage_cost(model if isinstance(model, str) else None, usage)
    return Ping(ts, conversation, dollars, True, approximate)


def read_pings(path: str) -> PingLog:
    """The pings of the log at `path`; OSError propagates."""
    pings, skipped = [], 0
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                entry = None
            if not isinstance(entry, dict):
                skipped += 1
            elif entry.get("event") == "ping":
                ping = _ping(entry)
                if ping is None:
                    skipped += 1
                else:
                    pings.append(ping)
    return PingLog(path, tuple(pings), skipped)
