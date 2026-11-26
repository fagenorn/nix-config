"""`omlx-memory-census-day`: the verify check that the day after the census deploy holds the unowned figure.

`python3 -m agent_tools.hosts.omlx_memory_census_day [--state-dir DIR]` reads the memory watcher's
`DIR/memory-watch.json` (default `~/.omlx/memory`) for its `records_since` and `records_since_at`, each line of
`DIR/memory-peaks.jsonl` and the sample records of `DIR/samples/<day>.jsonl`. It prints one JSON line
and exits 0 met, 1 not met, 75 not yet, 2 (stderr `omlx-memory-census-day: <error>`, nothing on
stdout) when the state, a peaks line or a sample line is not a JSON object, or `records_since` is
neither null nor an ISO date.

The target day T is the first day the deploy leaves whole: `records_since_at` is the first sample the
new watcher wrote, and its day is T when that sample is within the first `1440 - MIN_SAMPLES` minutes of
it (a deploy that only reached its first sample just after midnight), the next day otherwise. A state
without `records_since_at` takes `records_since` plus one day. The first decision that applies wins:

1. No state file, or a null `records_since`: `{"verdict": "not_yet", "records_since", "day": null}`.
2. No peaks line has `day >= T` (no peaks file counts as none): `not_yet` with `day` T.
3. No peaks line has `day == T` but a later one exists: `not_met`, `missing_day`. A later day is
   never judged.
4. `samples/T.jsonl` is missing: `no_samples`.
5. The day line's `census_samples` is under its `samples`, or a record of the file has an
   `unowned_bytes` that is not an integer: `missing_figure`, with `missing` the larger of the
   difference and the count of such records.
6. The file holds a record count other than the day line's `samples`: `records_disagree`, with
   `records` and `samples`. A record whose `at` is not on T, or not after the record before it, makes
   it `bad_timestamps`, with `outside_day` and `repeated` the counts of such records.
7. `samples` is under `MIN_SAMPLES` (90 % of a day's minutes): `few_samples`.
8. `peak_unowned_at` is null: `no_peak`.
9. The records' largest `unowned_bytes` in GiB, rounded to 0.1, differs from `peak_unowned_gib`, or
   the earliest record holding it is not at `peak_unowned_at`: `records_disagree`, with
   `records_peak_gib` and `records_peak_at`.
10. Otherwise met: `{"verdict": "met", "day", "records_since", "samples", "census_samples",
    "peak_unowned_gib", "peak_unowned_at", "events_near_peak"}`.

Every not met answer is `{"verdict": "not_met", "day", "reason", ...}`. `events_near_peak` holds the
events of every existing `samples/<day>.jsonl` from the day `NEAR_PEAK` before the peak through T+1 (a
verify run that held a slot through the peak is recorded once it ends, possibly after midnight), in file
order, at most `NEAR_PEAK_LIMIT`, within `NEAR_PEAK` either side of the peak: a `verify_run` when its
`held_from` to `held_until` overlaps that window, a `floor_kill` when its own `at` is in it, any other
event when its record's `at` is. Each is only its kind and timing, `{"kind", "sample_at": the record's
at}` with `held_from` and `held_until` for a `verify_run` and `at` for a `floor_kill`: the answer is
posted to the issue, so no command, owner or other text of an event is repeated.
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

STATE_NAME = "memory-watch.json"
PEAKS_NAME = "memory-peaks.jsonl"
SAMPLES_NAME = "samples"
GIB = 1024 ** 3
DAY_MINUTES = 1440
MIN_SAMPLES = 1296
NEAR_PEAK = timedelta(minutes=30)
NEAR_PEAK_LIMIT = 50
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


def _read_state(directory: Path) -> tuple[date, date] | None:
    """The state's `records_since` and the target day, None when there is no state or it is null."""
    try:
        with (directory / STATE_NAME).open(encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return None
    if not isinstance(state, dict):
        raise ValueError(f"{directory / STATE_NAME} is not a JSON object")
    since = state.get("records_since")
    if since is None:
        return None
    if not isinstance(since, str):
        raise ValueError(f"records_since is not an ISO date: {since!r}")
    since_day = date.fromisoformat(since)
    first = state.get("records_since_at")
    if first is None:
        return since_day, since_day + timedelta(days=1)
    if not isinstance(first, str):
        raise ValueError(f"records_since_at is not an ISO time: {first!r}")
    started = datetime.fromisoformat(first)
    if started.date() != since_day:
        raise ValueError(f"records_since_at {first} is not on {since}")
    whole = started.hour * 60 + started.minute <= DAY_MINUTES - MIN_SAMPLES
    return since_day, since_day + timedelta(days=0 if whole else 1)


def _peaks_from(directory: Path, target: date) -> tuple[dict | None, bool]:
    """The last peaks line of `target`, and whether a line of a later day exists."""
    found, later = None, False
    try:
        for line in _objects(directory / PEAKS_NAME):
            day = date.fromisoformat(line["day"])
            if day == target:
                found = line
            elif day > target:
                later = True
    except FileNotFoundError:
        pass
    return found, later


def _is_figure(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _scan(path: Path, target: date) -> tuple[int, int, int | None, str | None, int, int]:
    """The record count, the count without a figure, the largest figure and its earliest `at`, then the counts
    of records off `target` and of records not after the one before."""
    records = missing = outside = repeated = 0
    largest, largest_at, last = None, None, None
    for record in _objects(path):
        records += 1
        moment = datetime.fromisoformat(record["at"])
        outside += moment.date() != target
        repeated += last is not None and moment <= last
        last = moment
        figure = record.get("unowned_bytes")
        if not _is_figure(figure):
            missing += 1
        elif largest is None or figure > largest:
            largest, largest_at = figure, record["at"]
    return records, missing, largest, largest_at, outside, repeated


def _timing(event: dict, stamp: str) -> dict:
    """The kind and timing of `event`, which carries more that must not be published."""
    kept = {"kind": event["kind"], "sample_at": stamp}
    if event["kind"] == "verify_run":
        kept.update(held_from=event["held_from"], held_until=event["held_until"])
    elif event["kind"] == "floor_kill":
        kept["at"] = event["at"]
    return kept


def _near_peak(directory: Path, target: date, peak: datetime) -> list[dict]:
    first, last = peak - NEAR_PEAK, peak + NEAR_PEAK
    kept: list[dict] = []
    day = first.date()
    while day <= target + timedelta(days=1):
        path = directory / SAMPLES_NAME / f"{day.isoformat()}.jsonl"
        day += timedelta(days=1)
        if not path.exists():
            continue
        for record in _objects(path):
            stamp = record["at"]
            for event in record.get("events") or []:
                if not isinstance(event, dict):
                    raise ValueError(f"{path} holds an event that is not a JSON object")
                kind = event.get("kind")
                if kind == "verify_run":
                    inside = (datetime.fromisoformat(event["held_from"]) <= last
                              and datetime.fromisoformat(event["held_until"]) >= first)
                elif kind == "floor_kill":
                    inside = first <= datetime.fromisoformat(event["at"]) <= last
                else:
                    inside = first <= datetime.fromisoformat(stamp) <= last
                if inside:
                    kept.append(_timing(event, stamp))
                    if len(kept) >= NEAR_PEAK_LIMIT:
                        return kept
    return kept


def decide(directory: Path) -> tuple[int, dict]:
    """The exit code and the JSON answer for the state directory `directory`."""
    anchored = _read_state(directory)
    if anchored is None:
        return NOT_YET, {"verdict": "not_yet", "records_since": None, "day": None}
    since, target = anchored
    line, later = _peaks_from(directory, target)
    if line is None and not later:
        return NOT_YET, {"verdict": "not_yet", "records_since": since.isoformat(), "day": target.isoformat()}
    day = target.isoformat()

    def not_met(reason: str, **more) -> tuple[int, dict]:
        return NOT_MET, {"verdict": "not_met", "day": day, "reason": reason, **more}

    if line is None:
        return not_met("missing_day")
    path = directory / SAMPLES_NAME / f"{day}.jsonl"
    if not path.exists():
        return not_met("no_samples")
    samples, census = line["samples"], line["census_samples"]
    records, missing, largest, largest_at, outside, repeated = _scan(path, target)
    if census < samples or missing > 0:
        return not_met("missing_figure", missing=max(samples - census, missing))
    if records != samples:
        return not_met("records_disagree", records=records, samples=samples)
    if outside or repeated:
        return not_met("bad_timestamps", outside_day=outside, repeated=repeated)
    if samples < MIN_SAMPLES:
        return not_met("few_samples")
    if line["peak_unowned_at"] is None:
        return not_met("no_peak")
    records_gib = round(largest / GIB, 1)
    if records_gib != line["peak_unowned_gib"] or largest_at != line["peak_unowned_at"]:
        return not_met("records_disagree", records_peak_gib=records_gib, records_peak_at=largest_at)
    peak = datetime.fromisoformat(line["peak_unowned_at"])
    return MET, {
        "verdict": "met", "day": day, "records_since": since.isoformat(), "samples": samples,
        "census_samples": census, "peak_unowned_gib": line["peak_unowned_gib"],
        "peak_unowned_at": line["peak_unowned_at"], "events_near_peak": _near_peak(directory, target, peak)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="omlx-memory-census-day", description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".omlx/memory")
    args = parser.parse_args(argv)
    try:
        code, answer = decide(args.state_dir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"omlx-memory-census-day: {error}", file=sys.stderr)
        return UNREADABLE
    print(json.dumps(answer))
    return code


if __name__ == "__main__":
    sys.exit(main())
