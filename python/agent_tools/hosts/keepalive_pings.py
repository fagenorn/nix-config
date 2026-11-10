"""The keepalive pings of one cache-proxy log (issue 503).

`read_pings` reads the `ping` lines of one log that `cache-proxy --keepalive` writes (through
agent_tools.hosts.cache_proxy.LineLog) and prices them through agent_tools.hosts.model_pricing. The ping
contract is the docstring of agent_tools.hosts.cache_keepalive. `end_turn_cap` is the measurement of
issue 502's AC2 (no ping after a completed `end_turn` reply once its period holds the cap), run
as `python -m agent_tools.hosts.keepalive_pings end-turn-cap` by the verify check
home/common/verify-pending/checks/keepalive-end-turn-cap.

The check runs `end_turn_cap` over the trailing `--days` (7) window ending at `--end` (now) of
`--log` (`~/Library/Logs/claude-cache-proxy.log`): per proxy run (a `listening` line starts a new
one), it counts the keepalive periods whose conversation's last reply was `end_turn` when they
closed and how many sent a ping after that reply completed while already holding the cap (pings
sent while the reply still streamed count toward the total but never mark a period over; a `ping`
line is written when its exchange completes, so its send time is its `ts` minus `duration_ms`, and
lines are judged and assigned to periods in send order). It prints one JSON line and exits 0 when
at least one such period exists and none is over, 1 when one is over, 75 when none exists yet, and
2 on a usage error or an unreadable log; the cap is `cache_keepalive.END_TURN_PINGS`.
"""

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.hosts.cache_keepalive import END_TURN_PINGS
from agent_tools.hosts.model_pricing import usage_cost


@dataclass(frozen=True)
class Ping:
    ts: datetime          # aware UTC
    conversation: str     # the conversation handle of agent_tools.hosts.cache_keepalive
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


@dataclass(frozen=True)
class CapReport:
    end_turn_periods: int  # periods whose conversation's last reply was end_turn when they closed
    over_cap: int          # of those, periods with a ping sent after that reply held `cap` pings
    max_pings: int         # the largest total of those periods


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _thread_request(entry, ts):
    """(conversation, (start, completion, reply)) of a thread `request` object, else None."""
    conversation = entry.get("conversation")
    keepalive = entry.get("keepalive")
    if (not isinstance(conversation, str) or keepalive is None
            or keepalive in ("untracked", "no_tail_mark")):
        return None
    duration = entry.get("duration_ms")
    if duration is None:
        duration = 0
    if not _number(duration):
        return None
    try:
        start = ts - timedelta(milliseconds=duration)
    except OverflowError:
        return None
    status = entry.get("status")
    reply = None
    if (isinstance(status, int) and not isinstance(status, bool) and 200 <= status < 300
            and entry.get("outcome") == "complete"):
        stop = entry.get("stop_reason")
        reply = stop if isinstance(stop, str) else None
    return conversation, (start, ts, reply)


def _reply_state(threads, conversation, at, before=None, pingless=False):
    """"idle", "streaming", or the reply of the thread request of `conversation` with the
    greatest start at or before `at` (the later line on a tie). A closing period passes
    `before`, the instant of its last ping: the request that resumed the conversation starts
    after it, and cache_proxy writes keepalive_end while that request still streams, so a
    request starting at or after `before` is not the period's reply. A period without a
    ping (`pingless`) cannot have had a reply stream during it, so a request still
    streaming at `at` is that resuming request."""
    chosen = None
    for request in threads.get(conversation, ()):
        if before is not None and request[0] >= before:
            continue
        if pingless and request[1] > at:
            continue
        if request[0] <= at and (chosen is None or request[0] >= chosen[0]):
            chosen = request
    if chosen is None:
        return "idle"
    return "streaming" if chosen[1] > at else chosen[2]


def _sent_at(entry, ts):
    """When a line's exchange began: cache_keepalive logs a `ping` after its exchange
    completes, with `duration_ms`, so the line's time is the completion, not the send. A
    missing or unusable duration leaves the line's own time."""
    duration = entry.get("duration_ms")
    if not _number(duration):
        return ts
    try:
        return ts - timedelta(milliseconds=duration)
    except OverflowError:
        return ts


def _by_instant(segment):
    """The lines of a segment in the order they happened: a ping at its send time, any other
    line at its own time, equal instants keeping log order."""
    return sorted(segment, key=lambda line: _sent_at(line[1], line[2])
                  if line[0] == "ping" else line[2])


def _segment_periods(segment, closed_at, cap):
    """(counted periods, over, max pings) of one segment of (event, entry, ts) lines, with
    still-open periods closed at `closed_at`."""
    threads = {}
    for event, entry, ts in segment:
        if event == "request":
            found = _thread_request(entry, ts)
            if found is not None:
                threads.setdefault(found[0], []).append(found[1])
    periods = over_cap = max_pings = 0
    open_count, over, last_ping = {}, set(), {}

    def close(conversation, pings, at):
        nonlocal periods, over_cap, max_pings
        marked = conversation in over
        open_count.pop(conversation, None)
        over.discard(conversation)
        before = last_ping.pop(conversation, None)
        if _reply_state(threads, conversation, at, before, before is None) == "end_turn":
            periods += 1
            over_cap += marked
            max_pings = max(max_pings, pings)

    for event, entry, ts in _by_instant(segment):
        conversation = entry.get("conversation")
        if not isinstance(conversation, str):
            continue
        if event == "ping":
            sent = _sent_at(entry, ts)
            count = open_count.get(conversation, 0)
            if count >= cap and _reply_state(threads, conversation, sent) == "end_turn":
                over.add(conversation)
            open_count[conversation] = count + 1
            last_ping[conversation] = sent
        elif event == "keepalive_end":
            pings = entry.get("pings", 0)
            close(conversation, pings if _number(pings) else 0, ts)
    for conversation in list(open_count):
        close(conversation, open_count[conversation], closed_at)
    return periods, over_cap, max_pings


def end_turn_cap(lines: Iterable[str], start: datetime, end: datetime, cap: int) -> CapReport:
    """Issue 502's AC2 over the `[start, end)` lines of one cache-proxy log: how many keepalive
    periods ended after an `end_turn` reply and how many of them sent a ping after that reply
    completed while already holding `cap` pings. Pings sent while the reply still streams count
    toward the period's total but never mark it over."""
    segments, current = [], []
    for raw in lines:
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        try:
            ts = parse_rfc3339_utc(entry.get("ts"))
        except ValueError:
            continue
        if not start <= ts < end:
            continue
        event = entry.get("event")
        if event == "listening":
            segments.append((current, ts))
            current = []
        else:
            current.append((event, entry, ts))
    segments.append((current, end))
    periods = over_cap = max_pings = 0
    for segment, closed_at in segments:
        found, over, most = _segment_periods(segment, closed_at, cap)
        periods += found
        over_cap += over
        max_pings = max(max_pings, most)
    return CapReport(periods, over_cap, max_pings)


def _days(value):
    try:
        days = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if days < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return days


def _instant(value):
    try:
        return parse_rfc3339_utc(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="keepalive-pings")
    commands = parser.add_subparsers(dest="command", required=True)
    cap = commands.add_parser("end-turn-cap", help="issue 502 AC2: end_turn pings within the cap")
    cap.add_argument("--log", type=Path,
                     default=Path.home() / "Library/Logs/claude-cache-proxy.log")
    cap.add_argument("--days", type=_days, default=7)
    cap.add_argument("--end", type=_instant, default=None)
    args = parser.parse_args(argv)
    end = args.end if args.end is not None else datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    try:
        with open(args.log, "r", encoding="utf-8", errors="replace") as handle:
            report = end_turn_cap(handle, start, end, END_TURN_PINGS)
    except OSError as error:
        print(f"keepalive-pings: cannot read {args.log}: {error.strerror or error}",
              file=sys.stderr)
        return 2
    print(json.dumps({"end_turn_periods": report.end_turn_periods, "over_cap": report.over_cap,
                      "max_pings": report.max_pings, "cap": END_TURN_PINGS,
                      "start": start.isoformat(), "end": end.isoformat(),
                      "log": str(args.log)}, sort_keys=True))
    if report.over_cap > 0:
        return 1
    return 0 if report.end_turn_periods >= 1 else 75


if __name__ == "__main__":
    sys.exit(main())
