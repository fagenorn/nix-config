"""The verify-slot timeout share: how much of a repository's recent requests gave up waiting for a slot.

Run: python3 -m agent_tools.delivery.verify_slot_timeouts --repository OWNER/REPO [--hours N] [--history FILE]
     [--command TEXT] [--max-timed-out N] [--median-wait-below SECONDS]

The requests are the readable history records of the repository started within the last `--hours` hours (not
after now); with `--command` only those of that command. A request timed out when it exited 75 without ever
holding a slot. The verdict is `met` when the timed-out share is strictly below the share before the queue
(`BASELINE_TIMED_OUT` of `BASELINE_REQUESTS`), compared in integers, and `not_yet` while fewer than `MIN_REQUESTS`
requests are in the window. With `--max-timed-out` the window is judged by count alone, whatever its size: `not_met`
when more than N requests timed out, else `met`, and `not_yet` only when no request is in the window; `MIN_REQUESTS`
gates the share rule only. With `--median-wait-below`, `met` also needs the median `waited_seconds` of those
requests, timed-out ones included, to be strictly below SECONDS, and the line gains `median_waited_seconds` and
`median_wait_below`. One JSON line is printed. Exit 0 met, 1 not met, 75 not yet, 2 when the history cannot be read
or the hours, the maximum or a limit are not valid.
"""

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_tools import canonical
from agent_tools.delivery import verify_history, verify_slot

BASELINE_TIMED_OUT = 85
BASELINE_REQUESTS = 149
MIN_REQUESTS = 20
DEFAULT_HOURS = 24
MET, NOT_MET, NOT_YET, UNREADABLE = 0, 1, 75, 2


def _positive_hours(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("hours must be positive")
    return value


def _non_negative(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("the maximum must not be negative")
    return value


def _positive_seconds(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("seconds must be positive")
    return value


def _window(records: list[dict], repository: str, hours: int, now: datetime,
            command: str | None = None) -> list[dict]:
    """The records of `repository` (of `command` when given) started in the window."""
    earliest = now - timedelta(hours=hours)
    return [record for record in records if record["repository"] == repository
            and (command is None or record["command"] == command)
            and earliest <= canonical.parse_rfc3339_utc(record["started"]) <= now]


def count_requests(records: list[dict], repository: str, hours: int, now: datetime,
                   command: str | None = None) -> tuple[int, int]:
    """The requests of `repository` (of `command` when given) started in the window, and how many timed out."""
    window = _window(records, repository, hours, now, command)
    timed_out = sum(1 for record in window
                    if record["exit"] == verify_slot.NO_SLOT_EXIT and record["held_seconds"] is None)
    return len(window), timed_out


def median_wait(records: list[dict], repository: str, hours: int, now: datetime,
                command: str | None = None) -> float | None:
    """The median `waited_seconds` of the requests `count_requests` counts, or None when there are none."""
    waits = [record["waited_seconds"] for record in _window(records, repository, hours, now, command)]
    return statistics.median(waits) if waits else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="verify-slot-timeouts", description=__doc__.splitlines()[0])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--hours", type=_positive_hours, default=DEFAULT_HOURS)
    parser.add_argument("--history", type=Path, default=None)
    parser.add_argument("--command", default=None)
    parser.add_argument("--max-timed-out", type=_non_negative, default=None)
    parser.add_argument("--median-wait-below", type=_positive_seconds, default=None)
    args = parser.parse_args(argv)
    try:
        path = args.history or verify_history.history_path(verify_slot.slot_dir())
        records, _ = verify_history.read(path)
    except OSError as error:
        print(f"verify-slot-timeouts: {error}", file=sys.stderr)
        return UNREADABLE
    repository, now = args.repository.lower(), datetime.now(timezone.utc)
    requests, timed_out = count_requests(records, repository, args.hours, now, args.command)
    median = median_wait(records, repository, args.hours, now, args.command)
    quick = args.median_wait_below is None or (median is not None and median < args.median_wait_below)
    if args.max_timed_out is not None:
        if timed_out > args.max_timed_out or (requests >= 1 and not quick):
            verdict, code = "not_met", NOT_MET
        elif requests >= 1:
            verdict, code = "met", MET
        else:
            verdict, code = "not_yet", NOT_YET
    elif requests < MIN_REQUESTS:
        verdict, code = "not_yet", NOT_YET
    elif timed_out * BASELINE_REQUESTS < BASELINE_TIMED_OUT * requests and quick:
        verdict, code = "met", MET
    else:
        verdict, code = "not_met", NOT_MET
    line = {"verdict": verdict, "repository": repository, "hours": args.hours, "requests": requests,
            "timed_out": timed_out, "baseline_timed_out": BASELINE_TIMED_OUT, "baseline_requests": BASELINE_REQUESTS}
    if args.command is not None:
        line["command"] = args.command
    if args.max_timed_out is not None:
        line["max_timed_out"] = args.max_timed_out
    if args.median_wait_below is not None:
        line.update(median_waited_seconds=median, median_wait_below=args.median_wait_below)
    print(json.dumps(line))
    return code


if __name__ == "__main__":
    sys.exit(main())
