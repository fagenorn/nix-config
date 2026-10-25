"""Per-model list prices for the agent-costs reports (issue 432).

Rates are dollars per million tokens, one row per model ID, from the Anthropic
pricing page named by SOURCE_URL and fetched on SOURCE_DATE. An ID equal to a row's
ID, or to it plus a `-<8 digits>` date suffix, takes that row. Any other ID takes
the newest row of the family its name contains, and `rates` reports it as
approximate. Haiku 5.5 is priced by the request's prompt size: a prompt over
100,000 tokens (input plus cache reads plus cache writes) takes its second tier.
The per-issue report and the cache report read this table.
"""

import re
from typing import NamedTuple

SOURCE_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
SOURCE_DATE = "2026-10-25"
HAIKU_TIER_PROMPT_TOKENS = 100_000


class Rates(NamedTuple):
    input: float
    output: float
    write_5m: float
    write_1h: float
    read: float


_OPUS_5 = Rates(5.0, 25.0, 6.25, 10.0, 0.50)
_SONNET_4 = Rates(3.0, 15.0, 3.75, 6.0, 0.30)

# Exact model ID -> Rates; Haiku 5.5 maps to its (up to 100k, over 100k) pair.
_ROWS = {
    "claude-opus-5-5": Rates(4.0, 20.0, 5.0, 8.0, 0.20),
    "claude-opus-5": _OPUS_5,
    "claude-opus-4-8": _OPUS_5,
    "claude-opus-4-7": _OPUS_5,
    "claude-opus-4-6": _OPUS_5,
    "claude-opus-4-5": _OPUS_5,
    "claude-sonnet-5-5": Rates(2.0, 10.0, 2.50, 4.0, 0.10),
    "claude-sonnet-5": Rates(2.0, 10.0, 2.50, 4.0, 0.20),
    "claude-sonnet-4-6": _SONNET_4,
    "claude-sonnet-4-5": _SONNET_4,
    "claude-haiku-5-5": (Rates(0.10, 0.50, 0.125, 0.20, 0.01),
                         Rates(0.50, 2.50, 0.625, 1.0, 0.05)),
    "claude-haiku-4-5": Rates(1.0, 5.0, 1.25, 2.0, 0.10),
    "claude-fable-5-1": Rates(10.0, 50.0, 12.50, 20.0, 0.25),
    "claude-fable-5": Rates(10.0, 50.0, 12.50, 20.0, 1.0),
}
# Family name -> the ID of its newest row, for an ID the table does not list.
_NEWEST = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "haiku": "claude-haiku-5-5",
    "fable": "claude-fable-5-1",
}
_FALLBACK = "claude-opus-5-5"
_SYNTHETIC = "<synthetic>"
_FREE = Rates(0.0, 0.0, 0.0, 0.0, 0.0)
_DATE_SUFFIX = re.compile(r"-\d{8}$")


def cache_write_split(usage):
    """(1-hour, 5-minute) cache-write tokens of one usage object.

    A usage object that records no TTL breakdown is taken as all 5-minute writes.
    """
    split = usage.get("cache_creation") or {}
    cw_1h = split.get("ephemeral_1h_input_tokens") or 0
    cw_5m = split.get("ephemeral_5m_input_tokens") or 0
    if cw_1h + cw_5m == 0:
        return 0, usage.get("cache_creation_input_tokens") or 0
    return cw_1h, cw_5m


def _row_id(model):
    """(row ID, approximate) for a model name."""
    name = (model or "").lower()
    base = _DATE_SUFFIX.sub("", name)
    if base in _ROWS:
        return base, False
    for family, newest in _NEWEST.items():
        if family in name:
            return newest, True
    return _FALLBACK, True


def rates(model, prompt_tokens):
    """(Rates, approximate) for a model ID and the request's prompt size in tokens."""
    if model == _SYNTHETIC:
        return _FREE, False
    row_id, approximate = _row_id(model)
    row = _ROWS[row_id]
    if not isinstance(row, Rates):
        row = row[1] if prompt_tokens > HAIKU_TIER_PROMPT_TOKENS else row[0]
    return row, approximate


def usage_cost(model, usage):
    """(dollars, approximate) of one deduplicated usage object."""
    fresh = usage.get("input_tokens") or 0
    output = usage.get("output_tokens") or 0
    read = usage.get("cache_read_input_tokens") or 0
    created = usage.get("cache_creation_input_tokens") or 0
    cw_1h, cw_5m = cache_write_split(usage)
    price, approximate = rates(model, fresh + read + created)
    dollars = (fresh * price.input + output * price.output + cw_5m * price.write_5m
               + cw_1h * price.write_1h + read * price.read) / 1e6
    return dollars, approximate
