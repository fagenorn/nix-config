"""`memory-floor`: the post-deploy verify check of the eleven-m5 memory floor.

`python3 -m agent_tools.hosts.memory_floor_check week|priority [--record FILE]` reads the floor
daemon's record (default `/var/db/memory-watch/floor.json`) and prints one JSON line. Exit 0 met,
1 not met, 75 not yet, 2 (stderr, nothing on stdout) when an input is not JSON or cannot be read.

`week [--state-dir DIR] [--reports-dir DIR] [--days N] [--now ISO]`: not yet
(`{"verdict": "not_yet", "since"}`) when the record is missing or `now - since` is under `days`
(default 7). Otherwise `panics` are the sorted names matching `panic-full-*.panic` in the reports
directory (default `/Library/Logs/DiagnosticReports`) whose mtime is at or after `since`, and
`jetsam_exits` is the sum of `jetsam_exits` over the lines of `DIR/memory-peaks.jsonl` (default
`~/.omlx/memory`) with `day` on or after `since`'s local date, plus the watcher's
`DIR/memory-watch.json` when its `day` is on or after that date. A reports
directory, peaks file or watcher state file that is missing or cannot be read is exit 2, never an empty
count. Met
(`{"verdict": "met", "since", "panics": [], "jetsam_exits": 0}`) when both are empty, else not met
with the same members.

`priority`: not yet when the record is missing, `omlx_pid` is null or `omlx_priority_reads` is
under 2 (no read yet after the first sample's set). Met when `omlx_kernel_priority` is at least
`declared_priority` and `omlx_priority_resets` is 0, so a value launchd or the kernel puts back
between samples is not met although each set succeeds. Not met otherwise. The line carries
`omlx_kernel_priority`, `declared_priority`, `omlx_priority_resets` and `omlx_priority_error`.
"""

import argparse
import fnmatch
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RECORD = Path("/var/db/memory-watch/floor.json")
REPORTS = Path("/Library/Logs/DiagnosticReports")
STATE_NAME = "memory-watch.json"
PEAKS_NAME = "memory-peaks.jsonl"
MET = 0
NOT_MET = 1
NOT_YET = 75
UNREADABLE = 2


def _read_json(path: Path) -> dict | None:
    """The JSON object at `path`, None when there is no file, ValueError when it is not an object."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def _jetsam_exits(directory: Path, first_day: str) -> int:
    total = 0
    text = (directory / PEAKS_NAME).read_text(encoding="utf-8")
    for piece in text.splitlines():
        if not piece.strip():
            continue
        line = json.loads(piece)
        if line["day"] >= first_day:
            total += line["jetsam_exits"]
    state = _read_json(directory / STATE_NAME)
    if state is None:
        raise FileNotFoundError(f"{directory / STATE_NAME} does not exist")
    if state["day"] >= first_day:
        total += state["jetsam_exits"]
    return total


def week(args: argparse.Namespace) -> tuple[int, dict]:
    record = _read_json(args.record)
    if record is None:
        return NOT_YET, {"verdict": "not_yet", "since": None}
    since = datetime.fromisoformat(record["since"])
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now - since < timedelta(days=args.days):
        return NOT_YET, {"verdict": "not_yet", "since": record["since"]}
    with os.scandir(args.reports_dir) as listing:
        panics = sorted(
            entry.name for entry in listing
            if fnmatch.fnmatchcase(entry.name, "panic-full-*.panic") and entry.stat().st_mtime >= since.timestamp()
        )
    exits = _jetsam_exits(args.state_dir, since.astimezone().date().isoformat())
    met = not panics and exits == 0
    return (MET if met else NOT_MET), {
        "verdict": "met" if met else "not_met", "since": record["since"], "panics": panics,
        "jetsam_exits": exits,
    }


def priority(args: argparse.Namespace) -> tuple[int, dict]:
    record = _read_json(args.record)
    if record is None or record["omlx_pid"] is None or record["omlx_priority_reads"] < 2:
        return NOT_YET, {"verdict": "not_yet"}
    figures = {key: record[key] for key in (
        "omlx_kernel_priority", "declared_priority", "omlx_priority_resets", "omlx_priority_error")}
    met = figures["omlx_kernel_priority"] >= figures["declared_priority"] and figures["omlx_priority_resets"] == 0
    return (MET if met else NOT_MET), {"verdict": "met" if met else "not_met", **figures}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="memory-floor", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="check", required=True)
    for name in ("week", "priority"):
        one = sub.add_parser(name)
        one.add_argument("--record", type=Path, default=RECORD)
    weekly = sub.choices["week"]
    weekly.add_argument("--state-dir", type=Path, default=Path.home() / ".omlx/memory")
    weekly.add_argument("--reports-dir", type=Path, default=REPORTS)
    weekly.add_argument("--days", type=int, default=7)
    weekly.add_argument("--now", default=None)
    args = parser.parse_args(argv)
    try:
        code, answer = (week if args.check == "week" else priority)(args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"memory-floor: {error}", file=sys.stderr)
        return UNREADABLE
    print(json.dumps(answer))
    return code


if __name__ == "__main__":
    sys.exit(main())
