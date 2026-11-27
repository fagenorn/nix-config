"""`omlx-memory-verify-day`: the verify check that the first full working day after the deploy has a verify-tree peak.

`python3 -m agent_tools.hosts.omlx_memory_verify_day [--state-dir DIR]` reads the memory watcher's
`DIR/memory-watch.json` (default `~/.omlx/memory`) for its `verify_records_since` and each line of
`DIR/memory-peaks.jsonl`, one at a time. It prints one JSON line and exits 0 met, 1 not met, 75 not yet,
2 (stderr `omlx-memory-verify-day: <error>`, nothing on stdout) when the state or a peaks line is not a
JSON object, `verify_records_since` is neither null nor an ISO date, or a full day's line lacks
`verify_runs` or holds one that is not a non-negative integer.

A full day is a peaks line whose `day` is strictly after `verify_records_since`. The day of
`verify_records_since` itself (the deploy day, possibly partial) and every earlier line are never judged,
whatever keys they carry. A full day with `verify_runs` 0 is not a working day and is skipped. The first
working day decides:

1. No state file, or a null `verify_records_since`: `{"verdict": "not_yet", "verify_records_since": null,
   "full_days": 0}`.
2. No working day among the full days: `not_yet` with `verify_records_since` and `full_days`, the count of
   full days seen.
3. `peak_verify_gib` is not an integer or float (a boolean is neither), or is not finite and at least 0:
   `{"verdict": "not_met", "day", "reason": "no_peak", "verify_runs"}`.
4. `peak_verify_at` is not a string that `datetime.fromisoformat` parses with an offset and whose local
   date (`astimezone()`) is the line's `day`: `not_met`, `no_peak_time`.
5. Otherwise met: `{"verdict": "met", "day", "peak_verify_gib", "peak_verify_at", "verify_runs"}`.

The check reads no verify-slot history. Its answer is posted to the issue, so it carries no command,
repository or owner.
"""

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path

STATE_NAME = "memory-watch.json"
PEAKS_NAME = "memory-peaks.jsonl"
MET = 0
NOT_MET = 1
NOT_YET = 75
UNREADABLE = 2


def _objects(path: Path):
    """Each line of `path` as a JSON object, one at a time; a line that is not one is a ValueError."""
    with path.open(encoding="utf-8") as lines:
        for text in lines:
            if not text.strip():
                continue
            record = json.loads(text)
            if not isinstance(record, dict):
                raise ValueError(f"{path} holds a line that is not a JSON object")
            yield record


def _read_since(directory: Path) -> date | None:
    """The state's `verify_records_since`, None when there is no state or it is null."""
    try:
        with (directory / STATE_NAME).open(encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return None
    if not isinstance(state, dict):
        raise ValueError(f"{directory / STATE_NAME} is not a JSON object")
    since = state.get("verify_records_since")
    if since is None:
        return None
    if not isinstance(since, str):
        raise ValueError(f"verify_records_since is not an ISO date: {since!r}")
    return date.fromisoformat(since)


def _is_peak(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _is_time_on(value, day: str) -> bool:
    """Whether `value` is an offset-carrying ISO time whose local date is `day`."""
    if not isinstance(value, str):
        return False
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return False
    return moment.tzinfo is not None and moment.astimezone().date().isoformat() == day


def decide(directory: Path) -> tuple[int, dict]:
    """The exit code and the JSON answer for the state directory `directory`."""
    since = _read_since(directory)
    if since is None:
        return NOT_YET, {"verdict": "not_yet", "verify_records_since": None, "full_days": 0}
    full_days = 0
    try:
        for line in _objects(directory / PEAKS_NAME):
            day = line["day"]
            if date.fromisoformat(day) <= since:
                continue
            full_days += 1
            runs = line["verify_runs"]
            if not isinstance(runs, int) or isinstance(runs, bool) or runs < 0:
                raise ValueError(f"verify_runs of {day} is not a non-negative integer: {runs!r}")
            if runs == 0:
                continue
            peak, at = line.get("peak_verify_gib"), line.get("peak_verify_at")
            if not _is_peak(peak):
                return NOT_MET, {"verdict": "not_met", "day": day, "reason": "no_peak", "verify_runs": runs}
            if not _is_time_on(at, day):
                return NOT_MET, {"verdict": "not_met", "day": day, "reason": "no_peak_time", "verify_runs": runs}
            return MET, {"verdict": "met", "day": day, "peak_verify_gib": peak, "peak_verify_at": at,
                         "verify_runs": runs}
    except FileNotFoundError:
        pass
    return NOT_YET, {"verdict": "not_yet", "verify_records_since": since.isoformat(), "full_days": full_days}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="omlx-memory-verify-day", description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".omlx/memory")
    args = parser.parse_args(argv)
    try:
        code, answer = decide(args.state_dir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"omlx-memory-verify-day: {error}", file=sys.stderr)
        return UNREADABLE
    print(json.dumps(answer))
    return code


if __name__ == "__main__":
    sys.exit(main())
