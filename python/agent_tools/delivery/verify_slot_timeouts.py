"""The verify-slot timeout share: how much of a repository's recent requests gave up waiting for a slot.

Run: python3 -m agent_tools.delivery.verify_slot_timeouts --repository OWNER/REPO [--hours N] [--history FILE]

The requests are the readable history records of the repository started within the last `--hours` hours (not
after now). A request timed out when it exited 75 without ever holding a slot. The verdict is `met` when the
timed-out share is strictly below the share before the queue (`BASELINE_TIMED_OUT` of `BASELINE_REQUESTS`),
compared in integers, and `not_yet` while fewer than `MIN_REQUESTS` requests are in the window. One JSON line is
printed. Exit 0 met, 1 not met, 75 not yet, 2 when the history cannot be read or the hours are not positive.
"""

import argparse
import json
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


def count_requests(records: list[dict], repository: str, hours: int, now: datetime) -> tuple[int, int]:
    """The requests of `repository` started in the window, and how many of those timed out."""
    earliest = now - timedelta(hours=hours)
    requests = timed_out = 0
    for record in records:
        if record["repository"] != repository:
            continue
        if not earliest <= canonical.parse_rfc3339_utc(record["started"]) <= now:
            continue
        requests += 1
        if record["exit"] == verify_slot.NO_SLOT_EXIT and record["held_seconds"] is None:
            timed_out += 1
    return requests, timed_out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="verify-slot-timeouts", description=__doc__.splitlines()[0])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--hours", type=_positive_hours, default=DEFAULT_HOURS)
    parser.add_argument("--history", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        path = args.history or verify_history.history_path(verify_slot.slot_dir())
        records, _ = verify_history.read(path)
    except OSError as error:
        print(f"verify-slot-timeouts: {error}", file=sys.stderr)
        return UNREADABLE
    requests, timed_out = count_requests(records, args.repository.lower(), args.hours, datetime.now(timezone.utc))
    if requests < MIN_REQUESTS:
        verdict, code = "not_yet", NOT_YET
    elif timed_out * BASELINE_REQUESTS < BASELINE_TIMED_OUT * requests:
        verdict, code = "met", MET
    else:
        verdict, code = "not_met", NOT_MET
    print(json.dumps({"verdict": verdict, "repository": args.repository.lower(), "hours": args.hours,
                      "requests": requests, "timed_out": timed_out, "baseline_timed_out": BASELINE_TIMED_OUT,
                      "baseline_requests": BASELINE_REQUESTS}))
    return code


if __name__ == "__main__":
    sys.exit(main())
