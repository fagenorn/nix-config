"""`omlx-memory-day`: the verify check that the eleven-m5 memory budget held through a loaded day.

`python3 -m agent_tools.hosts.omlx_memory_day [--state-dir DIR] [--slot-history FILE]` reads the
memory watcher's `DIR/memory-watch.json` (default `~/.omlx/memory`) for its `since` and each line
of `DIR/memory-peaks.jsonl`, and the verify-slot history (default: the slot directory's). It prints
one JSON line and exits 0 met, 1 not met, 75 not yet, 2 (stderr, nothing on stdout) when the
state or a peaks line is not JSON or the history is refused.

A full day is a peaks line whose `day` is later than `since`; with no state or no peaks file there
is none (`{"verdict": "not_yet", "full_days": 0}`). A verify run holds a slot from `started +
waited_seconds` for `held_seconds` (a null hold is skipped); a day's `peak_verify_runs` is the
most runs holding at one instant within that local day. A loaded day has `samples > 0` and
`loaded_samples * 10 >= samples * 9`.

Full days are taken in order and the first decision wins. A day with `jetsam_exits > 0` is not met
(`jetsam`); then `over_budget` (`over_budget`); then a `min_loaded_available_gib` that is not null
and under `floor_gib` (`floor`); then an `omlx_jetsam_priority` that is not null and differs from
`declared_jetsam_priority` (`jetsam_priority`); each prints `{"verdict": "not_met", "day",
"reason"}`. Otherwise the first loaded day with a `peak_others_gib`, an `omlx_jetsam_priority`
equal to the declared one, `peak_verify_runs >= 2` and `peak_ci_jobs >= 1` is met, with the
figures `day`, `peak_others_gib`, `others_budget_gib`, `loaded_samples`, `samples`,
`peak_verify_runs`, `peak_ci_jobs` and `omlx_jetsam_priority`; none is `{"verdict": "not_yet",
"full_days": n}`.
"""

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from agent_tools.delivery import verify_history, verify_slot

STATE_NAME = "memory-watch.json"
PEAKS_NAME = "memory-peaks.jsonl"
NOT_YET = 75
NOT_MET = 1
MET = 0
UNREADABLE = 2
PEAK_RUNS = 2
PEAK_CI_JOBS = 1


def _local(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone()


def peak_overlap(runs: list[dict], day: str) -> int:
    """The most verify runs holding a slot at one instant within the local `day`."""
    first = datetime.combine(date.fromisoformat(day), time()).astimezone()
    end = datetime.combine(date.fromisoformat(day) + timedelta(days=1), time()).astimezone()
    holds = []
    for run in runs:
        if run["held_seconds"] is None:
            continue
        began = _local(run["started"]) + timedelta(seconds=run["waited_seconds"])
        holds.append((began, began + timedelta(seconds=run["held_seconds"])))
    inside = [(began, over) for began, over in holds if began < end and over > first]
    instants = [first] + [began for began, _ in inside if began >= first]
    return max((sum(1 for began, over in inside if began <= at < over) for at in instants), default=0)


def _loaded(line: dict) -> bool:
    return line["samples"] > 0 and line["loaded_samples"] * 10 >= line["samples"] * 9


def _not_met(line: dict) -> str | None:
    floor, minimum = line["floor_gib"], line["min_loaded_available_gib"]
    priority = line["omlx_jetsam_priority"]
    if line["jetsam_exits"] > 0:
        return "jetsam"
    if line["over_budget"]:
        return "over_budget"
    if minimum is not None and minimum < floor:
        return "floor"
    if priority is not None and priority != line["declared_jetsam_priority"]:
        return "jetsam_priority"
    return None


def decide_day(since: str, lines: list[dict], runs: list[dict]) -> tuple[int, dict]:
    """The exit code and the JSON answer for the peaks `lines` after `since` and the verify `runs`."""
    days = sorted((line for line in lines if line["day"] > since), key=lambda line: line["day"])
    for line in days:
        reason = _not_met(line)
        if reason is not None:
            return NOT_MET, {"verdict": "not_met", "day": line["day"], "reason": reason}
    for line in days:
        peak_runs = peak_overlap(runs, line["day"])
        if (_loaded(line) and line["peak_others_gib"] is not None
                and line["omlx_jetsam_priority"] == line["declared_jetsam_priority"]
                and peak_runs >= PEAK_RUNS and line["peak_ci_jobs"] >= PEAK_CI_JOBS):
            return MET, {
                "verdict": "met", "day": line["day"], "peak_others_gib": line["peak_others_gib"],
                "others_budget_gib": line["others_budget_gib"], "loaded_samples": line["loaded_samples"],
                "samples": line["samples"], "peak_verify_runs": peak_runs,
                "peak_ci_jobs": line["peak_ci_jobs"], "omlx_jetsam_priority": line["omlx_jetsam_priority"]}
    return NOT_YET, {"verdict": "not_yet", "full_days": len(days)}


def _read_state(directory: Path) -> tuple[str, list[dict]] | None:
    """The state's `since` and the peaks lines, or None when there is no state or no peaks file."""
    try:
        state = json.loads((directory / STATE_NAME).read_text(encoding="utf-8"))
        text = (directory / PEAKS_NAME).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    lines = [json.loads(piece) for piece in text.splitlines() if piece.strip()]
    if not isinstance(state, dict) or not isinstance(state.get("since"), str):
        raise ValueError(f"{directory / STATE_NAME} has no since")
    if not all(isinstance(line, dict) and isinstance(line.get("day"), str) for line in lines):
        raise ValueError(f"{directory / PEAKS_NAME} holds a line that is not a day")
    return state["since"], lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="omlx-memory-day", description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".omlx/memory")
    parser.add_argument("--slot-history", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        state = _read_state(args.state_dir)
        if state is None:
            code, answer = NOT_YET, {"verdict": "not_yet", "full_days": 0}
        else:
            history = args.slot_history or verify_history.history_path(verify_slot.slot_dir())
            code, answer = decide_day(state[0], state[1], verify_history.read(history)[0])
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"omlx-memory-day: {error}", file=sys.stderr)
        return UNREADABLE
    print(json.dumps(answer))
    return code


if __name__ == "__main__":
    sys.exit(main())
