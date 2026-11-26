"""`omlx-reactive-restart-day`: the verify check that the first whole day after the reactive restart deploy held.

`python3 -m agent_tools.hosts.omlx_reactive_restart_day [--state-dir DIR]` reads the restart state
`DIR/omlx-restart.json` (default `~/.omlx/memory`) for its `since_at` and `limits`, each line of
`DIR/memory-peaks.jsonl`, the sample lines of `DIR/samples/<day>.jsonl` and the records of
`DIR/omlx-restarts.jsonl`. It prints one JSON line and exits 0 met, 1 not met, 75 not yet, 2 (stderr
`omlx-reactive-restart-day: <error>`, nothing on stdout) when the state, a day line, a sample line, a record or
an event is not a JSON object, or a `since_at`, a sample `at`, a record `at` or a floor kill's `at` is not an
ISO time.

The target day T is the date of `since_at` plus one day. The first decision that applies wins:

1. No state file, or a null `since_at`: `{"verdict": "not_yet", "day": null}`.
2. No day line has `day >= T` (no peaks file counts as none): `not_yet` with `day` T.
3. No day line has `day == T` but a later one exists: `not_met`, `missing_day`.
4. `samples/T.jsonl` is missing: `no_samples`.
5. The file's line count differs from the day line's `samples`: `records_disagree`, with `records` and `samples`.
6. A line whose `at` is not on T, or not after the line before it: `bad_timestamps`, with `outside_day` and
   `repeated` the counts of such lines.
7. `samples` is under `MIN_SAMPLES` (90 % of a day's minutes): `few_samples`.
8. `samples/<T+1>.jsonl` is missing: `no_next_samples` (its first sample carries the kills from before midnight).
9. A record dated T (by its `at`) whose `outcome` is not `restarted`, `deferred`, `failed` or `interrupted`, whose
   `available_bytes`, `unowned_bytes` or `compressor_bytes` is not an integer, or whose `reason` is empty:
   `bad_restart_record`.
10. The lines of `samples/<T-1>.jsonl` (when present) and of T's file are replayed with `limits`, merged in time
    order with the records dated T-1 or T (a record sorts after the sample line with the same `at`). A line's
    figure is `unowned_bytes + compressor_bytes`, None when either is not an integer. None resets the streak
    and keeps the episode; a figure at or under `trigger_bytes` resets the streak and reopens the episode; a
    figure over it adds one to the streak. A sample is due when the streak is at least `samples` and the episode
    is not done. Every due sample on T needs exactly one record with exactly its `at`: none adds to `missing`,
    more than one to `duplicated`. A `restarted` or `interrupted` record marks the episode done; `deferred`
    and `failed` leave it due, so the next due sample needs a record of its own. The episode's state carries
    across midnight from T-1's replay, and due samples of T-1 are not judged. An `interrupted` record whose `at`
    matches no sample line still marks the episode done (a run that stopped mid-attempt lost its sample line);
    any other record dated T that does not match a due sample adds to `stray`. Any of the three above 0:
    `episode_unlogged`, with `missing`, `duplicated` and `stray`.
11. Every `floor_kill` event of the files of T and T+1 whose own `at` is on T is judged by its own time, not by
    the sample that received it: the last sample line (of T-1, T or T+1) at or before the kill and the first
    after it. Either figure over the trigger: `kill_over_trigger`, with `kills` the count; both None or
    absent: `kill_unjudged`.
12. Otherwise met: `{"verdict": "met", "day", "samples", "floor_kills", "episodes", "restarts", "deferrals",
    "failures", "interruptions"}`. They are counts only: the answer is posted to the issue, so no reason text
    or model name.

Every not met answer is `{"verdict": "not_met", "day", "reason", ...}`.
"""

import argparse
import bisect
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

STATE_NAME = "omlx-restart.json"
PEAKS_NAME = "memory-peaks.jsonl"
RESTARTS_NAME = "omlx-restarts.jsonl"
SAMPLES_NAME = "samples"
MIN_SAMPLES = 1296
OUTCOMES = ("restarted", "deferred", "failed", "interrupted")
FIGURES = ("available_bytes", "unowned_bytes", "compressor_bytes")
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


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _read_state(directory: Path) -> tuple[date, dict | None] | None:
    """The target day and the state's limits, None when there is no state or its `since_at` is null."""
    try:
        with (directory / STATE_NAME).open(encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return None
    if not isinstance(state, dict):
        raise ValueError(f"{directory / STATE_NAME} is not a JSON object")
    since = state.get("since_at")
    if since is None:
        return None
    if not isinstance(since, str):
        raise ValueError(f"since_at is not an ISO time: {since!r}")
    return datetime.fromisoformat(since).date() + timedelta(days=1), state.get("limits")


def _limits(limits) -> tuple[int, int]:
    """The trigger and the sample count of the state's limits."""
    if not isinstance(limits, dict) or not _is_int(limits.get("trigger_bytes")) or not _is_int(limits.get("samples")):
        raise ValueError("the restart state holds no limits")
    return limits["trigger_bytes"], limits["samples"]


def _day_line(directory: Path, target: date) -> tuple[dict | None, bool]:
    """The last day line of `target`, and whether a line of a later day exists."""
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


def _figure(line: dict) -> int | None:
    unowned, compressor = line.get("unowned_bytes"), line.get("compressor_bytes")
    return unowned + compressor if _is_int(unowned) and _is_int(compressor) else None


def _read_samples(path: Path, kills: bool) -> tuple[list[tuple[datetime, int | None]], list[datetime]]:
    """The (time, figure) of each line of `path` in file order and, when asked, the `at` of its floor kills."""
    samples: list[tuple[datetime, int | None]] = []
    found: list[datetime] = []
    if not path.exists():
        return samples, found
    for line in _objects(path):
        samples.append((datetime.fromisoformat(line["at"]), _figure(line)))
        if not kills:
            continue
        events = line.get("events") or []
        if not isinstance(events, list):
            raise ValueError(f"{path} holds events that are not a list")
        for event in events:
            if not isinstance(event, dict):
                raise ValueError(f"{path} holds an event that is not a JSON object")
            if event.get("kind") == "floor_kill":
                found.append(datetime.fromisoformat(event["at"]))
    return samples, found


def _bad_record(record: dict) -> bool:
    reason = record.get("reason")
    return (record.get("outcome") not in OUTCOMES or not all(_is_int(record.get(key)) for key in FIGURES)
            or not isinstance(reason, str) or not reason)


def _replay(samples, records, target: date, trigger: int, needed: int) -> tuple[int, int, int, set[int]]:
    """The counts of due samples without a record, with several and of stray records, and the due episodes."""
    items = [(moment, 0, figure, None) for moment, figure in samples]
    items += [(moment, 1, None, record) for moment, record in records]
    items.sort(key=lambda item: (item[0], item[1]))
    logged = Counter(moment for moment, record in records if moment.date() == target)
    lines = {moment for moment, _ in samples}
    streak, done, episode = 0, False, 0
    missing = duplicated = 0
    due: set[datetime] = set()
    episodes: set[int] = set()
    for moment, rank, figure, record in items:
        if rank == 1:
            done = done or record["outcome"] in ("restarted", "interrupted")
            continue
        if figure is None:
            streak = 0
        elif figure <= trigger:
            streak, done, episode = 0, False, episode + 1
        else:
            streak += 1
        if figure is not None and streak >= needed and not done and moment.date() == target:
            due.add(moment)
            episodes.add(episode)
            missing += logged[moment] == 0
            duplicated += logged[moment] > 1
    stray = sum(1 for moment, record in records if moment.date() == target and moment not in due
                and not (record["outcome"] == "interrupted" and moment not in lines))
    return missing, duplicated, stray, episodes


def _judge_kills(samples, kills, target: date, trigger: int) -> tuple[int, int]:
    """The count of the target day's kills with a neighbouring figure over the trigger and with none to judge by."""
    ordered = sorted(samples, key=lambda sample: sample[0])
    moments = [moment for moment, _ in ordered]
    over = unjudged = 0
    for kill in kills:
        before = bisect.bisect_right(moments, kill) - 1
        figures = [ordered[before][1] if before >= 0 else None,
                   ordered[before + 1][1] if before + 1 < len(ordered) else None]
        if any(figure is not None and figure > trigger for figure in figures):
            over += 1
        elif all(figure is None for figure in figures):
            unjudged += 1
    return over, unjudged


def decide(directory: Path) -> tuple[int, dict]:
    """The exit code and the JSON answer for the state directory `directory`."""
    anchored = _read_state(directory)
    if anchored is None:
        return NOT_YET, {"verdict": "not_yet", "day": None}
    target, limits = anchored
    day = target.isoformat()
    line, later = _day_line(directory, target)
    if line is None and not later:
        return NOT_YET, {"verdict": "not_yet", "day": day}

    def not_met(reason: str, **more) -> tuple[int, dict]:
        return NOT_MET, {"verdict": "not_met", "day": day, "reason": reason, **more}

    if line is None:
        return not_met("missing_day")
    folder = directory / SAMPLES_NAME
    path = folder / f"{day}.jsonl"
    if not path.exists():
        return not_met("no_samples")
    today, today_kills = _read_samples(path, True)
    samples = line["samples"]
    if len(today) != samples:
        return not_met("records_disagree", records=len(today), samples=samples)
    outside = sum(moment.date() != target for moment, _ in today)
    repeated = sum(later_moment <= moment for (moment, _), (later_moment, _) in zip(today, today[1:]))
    if outside or repeated:
        return not_met("bad_timestamps", outside_day=outside, repeated=repeated)
    if samples < MIN_SAMPLES:
        return not_met("few_samples")
    next_path = folder / f"{(target + timedelta(days=1)).isoformat()}.jsonl"
    if not next_path.exists():
        return not_met("no_next_samples")
    records = [(datetime.fromisoformat(record["at"]), record) for record in _objects(directory / RESTARTS_NAME)] \
        if (directory / RESTARTS_NAME).exists() else []
    watched = [record for moment, record in records if moment.date() == target]
    if any(_bad_record(record) for record in watched):
        return not_met("bad_restart_record")
    trigger, needed = _limits(limits)
    before, _ = _read_samples(folder / f"{(target - timedelta(days=1)).isoformat()}.jsonl", False)
    after, after_kills = _read_samples(next_path, True)
    near = [(moment, record) for moment, record in records if moment.date() in (target, target - timedelta(days=1))]
    missing, duplicated, stray, episodes = _replay(before + today, near, target, trigger, needed)
    if missing or duplicated or stray:
        return not_met("episode_unlogged", missing=missing, duplicated=duplicated, stray=stray)
    kills = [moment for moment in today_kills + after_kills if moment.date() == target]
    over, unjudged = _judge_kills(before + today + after, kills, target, trigger)
    if over:
        return not_met("kill_over_trigger", kills=over)
    if unjudged:
        return not_met("kill_unjudged", kills=unjudged)
    counts = Counter(record["outcome"] for record in watched)
    return MET, {
        "verdict": "met", "day": day, "samples": samples, "floor_kills": len(kills), "episodes": len(episodes),
        "restarts": counts["restarted"], "deferrals": counts["deferred"], "failures": counts["failed"],
        "interruptions": counts["interrupted"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="omlx-reactive-restart-day", description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".omlx/memory")
    args = parser.parse_args(argv)
    try:
        code, answer = decide(args.state_dir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"omlx-reactive-restart-day: {error}", file=sys.stderr)
        return UNREADABLE
    print(json.dumps(answer))
    return code


if __name__ == "__main__":
    sys.exit(main())
