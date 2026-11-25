"""`omlx-memory-watch`: the eleven-m5 memory watcher, one sample per run.

`omlx-memory-watch sample --state-dir DIR --floor-gib N --others-budget-gib N
--unowned-alert-gib N --omlx-jetsam-priority N --host NAME [--label org.nixos.omlx] [--health-url URL] [--vm-stat PATH]
[--sysctl PATH] [--launchctl PATH] [--ps PATH] [--footprint PATH] [--hdiutil PATH] [--slot-history FILE]
[--colima-pid-file FILE] [--alert-settings FILE] [--alert-log FILE] [--telegram-api URL] [--census-record FILE]
[--now ISO8601]` takes one reading of the host and
records it. Used memory is (anonymous pages - purgeable pages + wired pages + compressor pages)
x the page size of `vm_stat`; available is `hw.memsize` minus used. A model is loaded when the
health URL (read without any proxy, 5 s) answers `engine_pool.loaded_count >= 1`. The oMLX
footprint is `phys_footprint` of `footprint -p <pid>` for the pid `launchctl print
system/<label>` shows, unknown when that is missing or fails; the memory of everything else is
used minus that footprint, counted only on a loaded sample whose footprint is known. CI jobs
are the `Runner.Worker` processes of `ps -axwwo pid=,args=` (the `ww` keeps a ps whose output is not a
terminal from cutting the args), every user's, since a job runs under a runner account and other accounts'
processes show as `(name)`.

`DIR/memory-watch.json` (mode 0600 in a 0700 directory, replaced atomically) holds the day's
`since`, `day`, `peak_used_bytes`, `peak_others_bytes`, `peak_omlx_bytes`,
`min_available_bytes`, `samples`, `loaded_samples`, `min_loaded_available_bytes`,
`peak_ci_jobs`, `jetsam_exits`, `omlx_runs`, `omlx_jetsam_priority`, `low_memory_open` and
`pending` (alerts not yet delivered, each `{kind, text, logged}`). `DIR/memory-peaks.jsonl`
gets one line per finished day: `day`, the peaks and minimum in GiB (null where unmeasured),
`others_budget_gib`, `over_budget`, `jetsam_exits`, `peak_ci_jobs`, `samples`,
`loaded_samples`, `min_loaded_available_gib`, `floor_gib`, `omlx_jetsam_priority` and
`declared_jetsam_priority`, then `peak_fseventsd_gib` and `fseventsd_restarts`, then for each of
`sys_footprint`, `process_footprint`, `unowned`, `wired`, `anonymous` and `compressions` a
`peak_<name>_gib` and a `peak_<name>_at` (the first sample, as ISO 8601, that held that peak; null
where unmeasured), `peak_owners` (the day's five largest `{name, pid, gib, at}`), `census_samples`
and `records_since`.

Each successful sample also appends one line to `DIR/samples/<day>.jsonl` (directory 0700, file 0600):
`at`, `used_bytes`, `available_bytes`, `loaded`, `omlx_bytes`, `ci_jobs`, `wired_bytes`,
`anonymous_bytes`, `compressions_bytes` (null when `vm_stat` prints no `Compressions` line), then
`sys_footprint_bytes`, `process_footprint_bytes`, `unowned_bytes`, `top_owners`, `census_at` and
`census_seconds`, which are null without a fresh census, and last `events`, the list of changes since the previous
sample (RAM disks from `hdiutil info -plist`, the Colima VM from the pid in `--colima-pid-file`, default
`~/.colima/_lima/colima/vz.pid`, CI jobs and live `verify-slot run` processes from the ps listing, finished
verify runs from `--slot-history`, default the verify-slot history of the slot directory, and the floor kills
of the floor record). Their shapes and the baseline, unreadable-source and history-offset rules are in
`agent_tools.hosts.omlx_memory_events`; the watcher never takes a slot's lock. The state keeps what each
source last showed in `ci_pids_seen`, `vm_seen`, `ram_disks_seen`, `verify_live_seen` and `history_seen`.
RAM disks, CI jobs and live verify runs are snapshots: one that starts and ends between two samples is not
recorded. A failed `hdiutil`, an unreadable pid file or an unreadable history is not a failed reading. A census is fresh when its `error` is null,
its three figures are integers and its `at` is within 150 s of the sample. A finished day deletes the
files more than 14 days older than the new day. The state holds `census_peaks` (each figure's largest
`{bytes, at}`; a later equal value keeps the earlier time; the three vm figures fold on every sample,
the census figures only from a fresh census), `peak_owners` (each `(name, pid)` at its largest size,
earliest on a tie, the five largest kept), `census_samples` (samples with a fresh census), all three
reset each day, and `records_since`, the day of the first sample that kept them: it is set once and
carried across days, so a day rolled over from a state without it reports null.

An alert is queued when the service's `runs` changed and its last exit reason is the memory
killer's (`jetsam`), and when available memory falls under the floor while a model is loaded
(`low_memory`, once per episode). `unowned_memory` is queued once per episode when a fresh census's
unowned memory is over `--unowned-alert-gib` (strictly); an unowned figure at or under the line closes
the episode, and a sample without a fresh census changes nothing. The first sample only records a
baseline for the other alerts. Each queued alert
is delivered through `agent_tools.hosts.host_alerts`, in order, before the state is written;
one that fails stays queued, is logged once and is retried by the next sample.

`fseventsd --record FILE --limit-gib N [--min-restart-minutes 60] [--label com.apple.fseventsd]
[--launchctl PATH] [--footprint PATH] [--kill PATH] [--now ISO8601]` runs as root: it reads the
`pid` of `launchctl print system/<label>` and its `footprint`, and sends `kill -TERM` when the
footprint is known and over the limit (strictly) and the last restart is null or at least the
interval ago; over the limit inside the interval it holds. It replaces FILE (default
`/var/db/memory-watch/fseventsd.json`, directory 0755, file 0644, atomically) with `at`, `pid`,
`footprint_bytes` (null when unread), `limit_bytes`, `restarts`, `last_restart_at`, `held` and
`restart_failed`. Exit 1 when the kill fails (the record says `restart_failed`) or launchctl
shows no pid (no record). It never reads the alert settings and sends nothing: `sample
[--fseventsd-record FILE]` reads the record once per run, keeps `fseventsd_bytes`,
`peak_fseventsd_bytes`, `fseventsd_restarts_seen`, `fseventsd_restarts_today`,
`fseventsd_held_open` and `fseventsd_failed_open` in the state, writes `peak_fseventsd_gib` and
`fseventsd_restarts` to the day line, and queues `fseventsd_restarted` when `restarts` rose, and
`fseventsd_held` and `fseventsd_restart_failed` (the record says `restart_failed`) once per
episode each. A missing or non-JSON record is not a failed reading.

`census --record FILE [--footprint PATH] [--timeout-seconds N] [--now ISO8601]` runs as root: it
runs `footprint -a --sysFootprint --noCategories -j <path>`, with `<path>` inside a fresh private
temporary directory, and replaces FILE (default `/var/db/memory-watch/census.json`, directory 0755,
file 0644, atomically) with `at`, `seconds` (how long footprint took), `footprint_exit` (null when it
did not finish), `error` (null or text), `warnings` (the length of footprint's `warnings`),
`sys_footprint_bytes`, `process_footprint_bytes`, `unowned_bytes`, `processes` and `top_owners` (at
most five `{name, pid, bytes}`, largest first). Unowned memory is `sys_footprint` minus footprint's own
`total footprint`, never a sum of the processes (which double-counts shared memory), and may be
negative. A report is a census only when it is counted in bytes, carries both totals, has an empty
`errors` list and at least one process; footprint's exit code never decides on its own. Any other
outcome writes the record with `error` set and every figure null, prints `omlx-memory-watch: <error>`
to stderr and exits 1: `footprint timed out after <N> s`, `footprint could not run (<class>)`,
`footprint census incomplete (errors: <n>)` or `footprint output not parseable (exit <code>)`.

`sample [--census-record FILE]` (default `/var/db/memory-watch/census.json`) reads the census record once per run.

`sample [--floor-record FILE]` (default `/var/db/memory-watch/floor.json`, written by the root memory
floor daemon, which never writes this watcher's log or alerts) reads the floor record once per run
and keeps `floor_kills_seen`, `floor_unmet_seen`, `priority_unset_open` and `floor_log` (kill lines not yet printed) in
the state. Each `recent` entry whose `seq` is above `floor_kills_seen` queues one `memory_kill`
alert, in `seq` order, and puts its `kill_line` in `floor_log`; `sample` prints `floor_log` to
stdout, the watch log, and empties it before the state is written. The first sight of the record
only sets `floor_kills_seen` to its `kills`. When the record's `omlx_pid` is launchctl's pid, its
`omlx_kernel_priority` is an integer and `omlx_priority_resets` is 0, the kernel priority replaces
launchctl's in `omlx_jetsam_priority`. `omlx_priority_error` or `omlx_priority_resets` above 0
queues `jetsam_priority_unset` once per episode. Each `floor_unmet_recent` entry whose `seq` is above
`floor_unmet_seen` queues one `floor_unmet` alert, in `seq` order (the first sight only sets
`floor_unmet_seen` to `floor_unmets`, which a record without it counts as 0, so the first episode after
a healthy sample alerts). A missing or non-JSON record queues nothing.

Exit 0: recorded, every alert delivered or recorded. 3: recorded, at least one alert not sent
(stderr `host alert not sent: <reason>`). 1: `vm_stat`, `sysctl`, `launchctl` or `ps` failed
or printed nothing parseable (stderr names it; nothing is written). 2: usage. A failed
`footprint` is not a failed reading.
"""

import argparse
import copy
import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from agent_tools.delivery import verify_history, verify_slot
from agent_tools.hosts import host_alerts, omlx_memory_events

GIB = 1024**3
PROG = "omlx-memory-watch"
FSEVENTSD_RECORD = "/var/db/memory-watch/fseventsd.json"
FSEVENTSD_LABEL = "com.apple.fseventsd"
FSEVENTSD_MINUTES = 60
FSEVENTSD_DEFAULTS = {
    "fseventsd_bytes": None, "peak_fseventsd_bytes": None, "fseventsd_restarts_seen": None,
    "fseventsd_restarts_today": 0, "fseventsd_held_open": False, "fseventsd_failed_open": False,
}
CENSUS_RECORD = "/var/db/memory-watch/census.json"
CENSUS_TIMEOUT = 50
CENSUS_FRESH_SECONDS = 150
SAMPLE_DAYS = 14
SAMPLES_DIR = "samples"
PEAK_FIGURES = ("sys_footprint", "process_footprint", "unowned", "wired", "anonymous", "compressions")
CENSUS_DEFAULTS = {
    "census_peaks": {}, "peak_owners": [], "census_samples": 0, "records_since": None, "unowned_open": False,
}
TOP_OWNERS = 5
FLOOR_RECORD = "/var/db/memory-watch/floor.json"
FLOOR_DEFAULTS = {"floor_kills_seen": None, "floor_unmet_seen": None, "priority_unset_open": False, "floor_log": []}
COLIMA_PID_FILE = ".colima/_lima/colima/vz.pid"
PID_FILE_BYTES = 64
STATE_NAME = "memory-watch.json"
PEAKS_NAME = "memory-peaks.jsonl"
RUN_TIMEOUT = 30
HEALTH_TIMEOUT = 5
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
VM_FIELDS = {
    "Anonymous pages": "anonymous",
    "Pages purgeable": "purgeable",
    "Pages wired down": "wired",
    "Pages occupied by compressor": "compressor",
}
LAUNCHCTL_FIELDS = {"runs": "runs", "pid": "pid", "jetsam priority": "jetsam_priority"}
FOOTPRINT_LINE = re.compile(r"^\s*phys_footprint:\s*(\d+) B\s*$", re.MULTILINE)
SEE = "See hosts/darwin/eleven-m5/README.md, Memory budget."


class ReadingError(Exception):
    pass


class CommandFailed(ReadingError):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def parse_vm_stat(text: str) -> dict:
    header = re.search(r"page size of (\d+) bytes", text)
    found = {"page_size": int(header.group(1))} if header else {}
    compressions = None
    for line in text.splitlines():
        name, separator, value = line.partition(":")
        key = VM_FIELDS.get(name.strip())
        if separator and re.fullmatch(r"\s*\d+\.?\s*", value):
            if key:
                found[key] = int(value.strip().rstrip("."))
            elif name.strip() == "Compressions":
                compressions = int(value.strip().rstrip("."))
    if len(found) != len(VM_FIELDS) + 1:
        raise ValueError("vm_stat output lacks the page size or a memory field")
    found["compressions"] = compressions
    return found


def used_bytes(vm: dict) -> int:
    pages = vm["anonymous"] - vm["purgeable"] + vm["wired"] + vm["compressor"]
    return pages * vm["page_size"]


def parse_launchctl(text: str) -> dict:
    found = {"runs": None, "pid": None, "jetsam_priority": None, "last_exit_reason": None}
    for line in text.splitlines():
        match = re.fullmatch(r"\t([^\t=][^=]*?) = (.*)", line)
        if not match:
            continue
        name, value = match.group(1), match.group(2).strip()
        if name == "last exit reason":
            found["last_exit_reason"] = value
        elif name in LAUNCHCTL_FIELDS and re.fullmatch(r"\d+", value):
            found[LAUNCHCTL_FIELDS[name]] = int(value)
    if found["runs"] is None:
        raise ValueError("launchctl output has no runs line")
    return found


class CensusIncomplete(ValueError):
    def __init__(self, errors: int):
        super().__init__(f"footprint census incomplete (errors: {errors})")
        self.errors = errors


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_census(document) -> dict:
    """The figures of a complete `footprint -a --sysFootprint -j` report, or ValueError (CensusIncomplete)."""
    if not isinstance(document, dict) or document.get("unit") != "byte":
        raise ValueError("footprint report is not counted in bytes")
    per_unit = document.get("bytes per unit")
    if not _is_int(per_unit) or per_unit != 1:
        raise ValueError("footprint report is not counted in bytes")
    auxiliary = document.get("auxiliary")
    system = auxiliary.get("sys_footprint") if isinstance(auxiliary, dict) else None
    total = document.get("total footprint")
    if not _is_int(total) or not _is_int(system):
        raise ValueError("footprint report has no system or process total")
    errors, listed = document.get("errors"), document.get("processes")
    if not isinstance(errors, list) or not isinstance(listed, list):
        raise ValueError("footprint report has no errors or processes list")
    if errors:
        raise CensusIncomplete(len(errors))
    owners = [
        {"name": entry["name"], "pid": entry["pid"], "bytes": entry["footprint"]}
        for entry in listed
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        and _is_int(entry.get("pid")) and _is_int(entry.get("footprint"))
    ]
    if not owners:
        raise ValueError("footprint report has no process")
    owners.sort(key=lambda owner: (-owner["bytes"], owner["pid"]))
    warnings = document.get("warnings")
    return {
        "warnings": len(warnings) if isinstance(warnings, list) else 0,
        "sys_footprint_bytes": system, "process_footprint_bytes": total, "unowned_bytes": system - total,
        "processes": len(owners), "top_owners": owners[:TOP_OWNERS],
    }


def parse_footprint(text: str) -> int | None:
    match = FOOTPRINT_LINE.search(text)
    return int(match.group(1)) if match else None


def fresh_day(since: str, day: str) -> dict:
    return {
        "since": since, "day": day, "peak_used_bytes": 0, "peak_others_bytes": None,
        "peak_omlx_bytes": None, "min_available_bytes": None, "samples": 0, "loaded_samples": 0,
        "min_loaded_available_bytes": None, "peak_ci_jobs": 0, "jetsam_exits": 0, "omlx_runs": None,
        "omlx_jetsam_priority": None, "low_memory_open": False, "pending": [],
        **FSEVENTSD_DEFAULTS, **FLOOR_DEFAULTS, "floor_log": [], **copy.deepcopy(CENSUS_DEFAULTS),
        **omlx_memory_events.EVENT_DEFAULTS,
    }


def _gib(value: int | None) -> float | None:
    return None if value is None else round(value / GIB, 1)


def _lower(current: int | None, value: int) -> int:
    return value if current is None else min(current, value)


def _higher(current: int | None, value: int) -> int:
    return value if current is None else max(current, value)


def _day_line(state: dict, floor_bytes: int, others_budget_bytes: int, declared: int) -> dict:
    peak_others = state["peak_others_bytes"]
    return {
        "day": state["day"],
        "peak_used_gib": _gib(state["peak_used_bytes"]),
        "peak_others_gib": _gib(peak_others),
        "peak_omlx_gib": _gib(state["peak_omlx_bytes"]),
        "min_available_gib": _gib(state["min_available_bytes"]),
        "others_budget_gib": others_budget_bytes // GIB,
        "over_budget": peak_others is not None and peak_others > others_budget_bytes,
        "jetsam_exits": state["jetsam_exits"],
        "peak_ci_jobs": state["peak_ci_jobs"],
        "samples": state["samples"],
        "loaded_samples": state["loaded_samples"],
        "min_loaded_available_gib": _gib(state["min_loaded_available_bytes"]),
        "floor_gib": floor_bytes // GIB,
        "omlx_jetsam_priority": state["omlx_jetsam_priority"],
        "declared_jetsam_priority": declared,
        "peak_fseventsd_gib": _gib(state["peak_fseventsd_bytes"]),
        "fseventsd_restarts": state["fseventsd_restarts_today"],
        **_peak_figures(state["census_peaks"]),
        "peak_owners": [
            {"name": owner["name"], "pid": owner["pid"], "gib": _gib(owner["bytes"]), "at": owner["at"]}
            for owner in state["peak_owners"]
        ],
        "census_samples": state["census_samples"],
        "records_since": state["records_since"],
    }


def _peak_figures(peaks: dict) -> dict:
    figures = {}
    for name in PEAK_FIGURES:
        held = peaks.get(name)
        figures[f"peak_{name}_gib"] = None if held is None else _gib(held["bytes"])
        figures[f"peak_{name}_at"] = None if held is None else held["at"]
    return figures


def fresh_census(found: dict | None, now: datetime) -> dict | None:
    """The census record when it has no error, carries its three figures and is within the freshness window."""
    if not isinstance(found, dict) or found.get("error") is not None:
        return None
    if not all(_is_int(found.get(key)) for key in ("sys_footprint_bytes", "process_footprint_bytes", "unowned_bytes")):
        return None
    try:
        age = abs((now - datetime.fromisoformat(found["at"])).total_seconds())
    except (KeyError, TypeError, ValueError):
        return None
    return found if age <= CENSUS_FRESH_SECONDS else None


def _fold_peak(state: dict, name: str, value: int, at: str) -> None:
    held = state["census_peaks"].get(name)
    if held is None or value > held["bytes"]:
        state["census_peaks"][name] = {"bytes": value, "at": at}


def _fold_owners(state: dict, owners, at: str) -> None:
    kept = {(owner["name"], owner["pid"]): owner for owner in state["peak_owners"]}
    for owner in owners if isinstance(owners, list) else []:
        if not (isinstance(owner, dict) and isinstance(owner.get("name"), str)
                and _is_int(owner.get("pid")) and _is_int(owner.get("bytes"))):
            continue
        held = kept.get((owner["name"], owner["pid"]))
        if held is None or owner["bytes"] > held["bytes"]:
            kept[(owner["name"], owner["pid"])] = {
                "name": owner["name"], "pid": owner["pid"], "bytes": owner["bytes"], "at": at}
    state["peak_owners"] = sorted(kept.values(), key=lambda owner: (-owner["bytes"], owner["pid"]))[:TOP_OWNERS]


def _sample_line(reading: dict, now: datetime, census: dict | None, events: list) -> dict:
    keys = ("sys_footprint_bytes", "process_footprint_bytes", "unowned_bytes", "top_owners")
    found = census or {}
    return {
        "at": now.isoformat(), "used_bytes": reading["used_bytes"], "available_bytes": reading["available_bytes"],
        "loaded": reading["loaded"], "omlx_bytes": reading["omlx_bytes"], "ci_jobs": reading["ci_jobs"],
        "wired_bytes": reading["wired_bytes"], "anonymous_bytes": reading["anonymous_bytes"],
        "compressions_bytes": reading["compressions_bytes"],
        **{key: found.get(key) for key in keys},
        "census_at": found.get("at"), "census_seconds": found.get("seconds"), "events": events,
    }


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _gib_text(value) -> str:
    return "unknown" if _int(value) is None else f"{value / GIB:.1f}"


def _minutes_since(last, at) -> int:
    try:
        return max(0, int((datetime.fromisoformat(at) - datetime.fromisoformat(last)).total_seconds() // 60))
    except (TypeError, ValueError):
        return FSEVENTSD_MINUTES


def _fold_fseventsd(state: dict, found: dict | None, host: str) -> None:
    found = found or {}
    size = _int(found.get("footprint_bytes"))
    state["fseventsd_bytes"] = size
    if size is not None:
        state["peak_fseventsd_bytes"] = _higher(state["peak_fseventsd_bytes"], size)
    limit = _int(found.get("limit_bytes"))
    limit_text = "unknown" if limit is None else str(limit // GIB)
    restarts = _int(found.get("restarts"))
    if restarts is not None:
        seen = state["fseventsd_restarts_seen"]
        if seen is not None and restarts > seen:
            state["fseventsd_restarts_today"] += restarts - seen
            state["pending"].append({
                "kind": "fseventsd_restarted", "logged": False,
                "text": f"{host}: fseventsd was restarted at {_gib_text(size)} GiB "
                        f"(limit {limit_text} GiB). {SEE}",
            })
        state["fseventsd_restarts_seen"] = restarts
    if found.get("held") is True:
        if not state["fseventsd_held_open"]:
            state["fseventsd_held_open"] = True
            minutes = _minutes_since(found.get("last_restart_at"), found.get("at"))
            state["pending"].append({
                "kind": "fseventsd_held", "logged": False,
                "text": f"{host}: fseventsd is at {_gib_text(size)} GiB, over {limit_text} GiB within "
                        f"{minutes} minutes of its last restart, and was not restarted. {SEE}",
            })
    else:
        state["fseventsd_held_open"] = False
    if found.get("restart_failed") is True:
        if not state["fseventsd_failed_open"]:
            state["fseventsd_failed_open"] = True
            state["pending"].append({
                "kind": "fseventsd_restart_failed", "logged": False,
                "text": f"{host}: fseventsd is at {_gib_text(size)} GiB, over {limit_text} GiB, "
                        f"and its restart failed. {SEE}",
            })
    else:
        state["fseventsd_failed_open"] = False


def _fold_floor(state: dict, found: dict | None, reading: dict, events: list) -> None:
    found = found or {}
    host = reading["host"]
    kills = _int(found.get("kills"))
    if kills is not None:
        seen = state["floor_kills_seen"]
        if seen is not None:
            entries = [entry for entry in found.get("recent") or []
                       if isinstance(entry, dict) and _int(entry.get("seq")) is not None and entry["seq"] > seen]
            for entry in sorted(entries, key=lambda entry: entry["seq"]):
                bound = entry["reason"] == "run_bound"
                why = (f"over the {found['run_bound_bytes'] // GIB} GiB run bound" if bound
                       else f"under the {found['floor_bytes'] // GIB} GiB floor")
                state["floor_log"].append(kill_line(entry))
                events.append({
                    "kind": "floor_kill", "at": entry["at"], "reason": entry["reason"], "owner": entry["owner"],
                    "root_pid": entry["root_pid"], "signals": entry["signals"],
                    "tree_gib": round(entry["tree_bytes"] / GIB, 1),
                })
                state["pending"].append({
                    "kind": "memory_kill", "logged": False,
                    "text": f"{host}: the memory floor ended {entry['owner']}'s workload "
                            f"{entry['root_command'][:200]} ({entry['processes']} processes, "
                            f"{entry['tree_bytes'] / GIB:.1f} GiB, {why}). Available "
                            f"{entry['available_before_bytes'] / GIB:.1f} GiB before, "
                            f"{entry['available_after_bytes'] / GIB:.1f} GiB after. {SEE}",
                })
        state["floor_kills_seen"] = kills
    unmets = _int(found.get("floor_unmets"))
    if unmets is None and kills is not None:
        unmets = 0
    if unmets is not None:
        seen = state["floor_unmet_seen"]
        if seen is not None:
            entries = [entry for entry in found.get("floor_unmet_recent") or []
                       if isinstance(entry, dict) and _int(entry.get("seq")) is not None and entry["seq"] > seen]
            for entry in sorted(entries, key=lambda entry: entry["seq"]):
                state["pending"].append({
                    "kind": "floor_unmet", "logged": False,
                    "text": f"{host}: the memory floor has no workload it may end that would bring available "
                            f"memory over the {found['floor_bytes'] // GIB} GiB floor. Available "
                            f"{entry['available_bytes'] / GIB:.1f} GiB, largest candidate "
                            f"{entry['largest_bytes'] / GIB:.1f} GiB. {SEE}",
                })
        state["floor_unmet_seen"] = unmets
    error, resets = found.get("omlx_priority_error"), _int(found.get("omlx_priority_resets")) or 0
    if error or resets > 0:
        if not state["priority_unset_open"]:
            state["priority_unset_open"] = True
            declared = _int(found.get("declared_priority"))
            declared = reading["declared_jetsam_priority"] if declared is None else declared
            current = _int(found.get("omlx_kernel_priority"))
            state["pending"].append({
                "kind": "jetsam_priority_unset", "logged": False,
                "text": f"{host}: oMLX's jetsam priority could not be set to {declared} "
                        f"({error or f'put back {resets} times'}); it is "
                        f"{'unknown' if current is None else current}. {SEE}",
            })
    else:
        state["priority_unset_open"] = False


def _fold_unowned(state: dict, census: dict | None, reading: dict, alert_bytes: int) -> None:
    if census is None:
        return
    unowned = census["unowned_bytes"]
    if unowned <= alert_bytes:
        state["unowned_open"] = False
    elif not state["unowned_open"]:
        state["unowned_open"] = True
        state["pending"].append({
            "kind": "unowned_memory", "logged": False,
            "text": f"{reading['host']}: {unowned / GIB:.1f} GiB of memory is in use but held by no process, "
                    f"over the {alert_bytes // GIB} GiB alert line (system footprint "
                    f"{census['sys_footprint_bytes'] / GIB:.1f} GiB, process footprints "
                    f"{census['process_footprint_bytes'] / GIB:.1f} GiB, wired {reading['wired_bytes'] / GIB:.1f} GiB, "
                    f"anonymous {reading['anonymous_bytes'] / GIB:.1f} GiB). {SEE}",
        })


def decide(state, reading: dict, now: datetime, floor_bytes: int, others_budget_bytes: int,
           unowned_alert_bytes: int):
    """Fold one reading into the state; answer the new state, the finished day's line or None, and the sample line."""
    day = now.date().isoformat()
    line = None
    if state is None:
        state = fresh_day(day, day)
    else:
        state = {**FSEVENTSD_DEFAULTS, **FLOOR_DEFAULTS, **copy.deepcopy(CENSUS_DEFAULTS),
                 **omlx_memory_events.EVENT_DEFAULTS, **state,
                 "pending": [dict(entry) for entry in state["pending"]]}
        state["floor_log"] = list(state["floor_log"])
        if state["day"] != day:
            line = _day_line(state, floor_bytes, others_budget_bytes, reading["declared_jetsam_priority"])
            carried = fresh_day(state["since"], day)
            for key in ("omlx_runs", "omlx_jetsam_priority", "low_memory_open", "pending",
                        "fseventsd_restarts_seen", "fseventsd_held_open", "fseventsd_failed_open",
                        "floor_kills_seen", "floor_unmet_seen", "priority_unset_open", "floor_log",
                        "records_since", "unowned_open", *omlx_memory_events.EVENT_DEFAULTS):
                carried[key] = state[key]
            state = carried
    if state["records_since"] is None:
        state["records_since"] = day
    used, available, loaded = reading["used_bytes"], reading["available_bytes"], reading["loaded"]
    omlx = reading["omlx_bytes"]
    footprint = "unknown" if omlx is None else f"{omlx / GIB:.1f}"
    memory = f"Used {used / GIB:.1f} GiB, available {available / GIB:.1f} GiB, oMLX footprint {footprint} GiB."
    at = now.isoformat()
    census = fresh_census(reading["census"], now)
    for name, key in (("wired", "wired_bytes"), ("anonymous", "anonymous_bytes"),
                      ("compressions", "compressions_bytes")):
        if reading[key] is not None:
            _fold_peak(state, name, reading[key], at)
    if census is not None:
        state["census_samples"] += 1
        for name in ("sys_footprint", "process_footprint", "unowned"):
            _fold_peak(state, name, census[f"{name}_bytes"], at)
        _fold_owners(state, census.get("top_owners"), at)
    state["samples"] += 1
    state["peak_used_bytes"] = max(state["peak_used_bytes"], used)
    state["min_available_bytes"] = _lower(state["min_available_bytes"], available)
    state["peak_ci_jobs"] = max(state["peak_ci_jobs"], reading["ci_jobs"])
    if reading["jetsam_priority"] is not None:
        state["omlx_jetsam_priority"] = reading["jetsam_priority"]
    if loaded:
        state["loaded_samples"] += 1
        state["min_loaded_available_bytes"] = _lower(state["min_loaded_available_bytes"], available)
        if omlx is not None:
            state["peak_others_bytes"] = _higher(state["peak_others_bytes"], max(0, used - omlx))
            state["peak_omlx_bytes"] = _higher(state["peak_omlx_bytes"], omlx)
    runs = reading["runs"]
    if state["omlx_runs"] is not None and runs != state["omlx_runs"] \
            and reading["last_exit_reason"] == "OS_REASON_JETSAM":
        state["jetsam_exits"] += 1
        state["pending"].append({
            "kind": "jetsam", "logged": False,
            "text": f"{reading['host']}: the memory killer ended oMLX (runs {runs}). {memory} {SEE}",
        })
    state["omlx_runs"] = runs
    if loaded and available < floor_bytes:
        if not state["low_memory_open"]:
            state["low_memory_open"] = True
            state["pending"].append({
                "kind": "low_memory", "logged": False,
                "text": f"{reading['host']}: available memory fell under {floor_bytes // GIB} GiB "
                        f"while a model was loaded. {memory} {SEE}",
            })
    else:
        state["low_memory_open"] = False
    _fold_fseventsd(state, reading["fseventsd"], reading["host"])
    events = omlx_memory_events.fold_events(state, reading["observed"])
    _fold_floor(state, reading["floor"], reading, events)
    _fold_unowned(state, census, reading, unowned_alert_bytes)
    return state, line, _sample_line(reading, now, census, events)


def read_health(url: str) -> bool:
    try:
        with DIRECT.open(url, timeout=HEALTH_TIMEOUT) as response:
            count = json.loads(response.read())["engine_pool"]["loaded_count"]
    except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError):
        return False
    return isinstance(count, int) and not isinstance(count, bool) and count >= 1


def read_footprint(footprint: str, pid: int | None) -> int | None:
    if pid is None:
        return None
    try:
        done = subprocess.run(
            [footprint, "-p", str(pid), "-f", "bytes", "--noCategories"],
            capture_output=True, text=True, timeout=RUN_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_footprint(done.stdout) if done.returncode == 0 else None


def read_fseventsd_record(path: Path) -> dict | None:
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def fseventsd_step(record, pid, footprint_bytes, now, limit_bytes, min_interval):
    """Decide one fseventsd check; answer the new record (as if a restart succeeds) and whether to kill."""
    record = record or {}
    restarts = _int(record.get("restarts")) or 0
    last = record.get("last_restart_at")
    over = footprint_bytes is not None and footprint_bytes > limit_bytes
    due = True
    if over and last is not None:
        try:
            due = now - datetime.fromisoformat(last) >= min_interval
        except (TypeError, ValueError):
            due = True
    restart = over and due
    if restart:
        restarts, last = restarts + 1, now.isoformat()
    return {
        "at": now.isoformat(), "pid": pid, "footprint_bytes": footprint_bytes,
        "limit_bytes": limit_bytes, "restarts": restarts, "last_restart_at": last,
        "held": over and not due, "restart_failed": False,
    }, restart


def write_record(path: Path, document: dict) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True)
        path.parent.chmod(0o755)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(json.dumps(document, indent=2) + "\n")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def kill_line(entry: dict) -> str:
    """The one-line wire format of a floor kill, shared by the floor daemon's log and the watch log."""
    return (
        f"{entry['at']} memory_kill reason={entry['reason']} owner={entry['owner']}"
        f" root_pid={entry['root_pid']} root={json.dumps(entry['root_command'][:200])}"
        f" processes={entry['processes']} tree_gib={entry['tree_bytes'] / GIB:.1f}"
        f" available_before_gib={entry['available_before_bytes'] / GIB:.1f}"
        f" available_after_gib={entry['available_after_bytes'] / GIB:.1f}"
        f" signals={entry['signals']}\n"
    )


def kernel_priority(service: dict, found: dict | None) -> int | None:
    """launchctl's jetsam priority, or the floor daemon's kernel reading when it is oMLX's own and not put back."""
    found = found or {}
    kernel = _int(found.get("omlx_kernel_priority"))
    if kernel is not None and service["pid"] is not None and found.get("omlx_pid") == service["pid"] \
            and found.get("omlx_priority_resets") == 0:
        return kernel
    return service["jetsam_priority"]


def fseventsd(args) -> int:
    now = args.now if args.now is not None else datetime.now().astimezone()
    try:
        service = parse_launchctl(_run("launchctl", [args.launchctl, "print", f"system/{args.label}"]))
    except (ReadingError, ValueError) as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 1
    pid = service["pid"]
    if pid is None:
        print(f"{PROG}: launchctl shows no pid for {args.label}", file=sys.stderr)
        return 1
    previous = read_fseventsd_record(args.record)
    document, restart = fseventsd_step(
        previous, pid, read_footprint(args.footprint, pid), now, args.limit_gib * GIB,
        timedelta(minutes=args.min_restart_minutes))
    status = 0
    if restart:
        try:
            killed = subprocess.run(
                [args.kill, "-TERM", str(pid)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
            failure = None if killed.returncode == 0 else f"kill exited {killed.returncode}"
        except (OSError, subprocess.SubprocessError) as error:
            failure = f"kill could not run ({type(error).__name__})"
        if failure:
            print(f"{PROG}: {failure}", file=sys.stderr)
            before = previous or {}
            document = {**document, "restarts": _int(before.get("restarts")) or 0,
                        "last_restart_at": before.get("last_restart_at"), "restart_failed": True}
            status = 1
    write_record(args.record, document)
    return status


def census(args) -> int:
    start = time.monotonic()
    code, error, figures = None, None, {}
    with tempfile.TemporaryDirectory() as scratch:
        target = Path(scratch) / "footprint.json"
        try:
            done = subprocess.run(
                [args.footprint, "-a", "--sysFootprint", "--noCategories", "-j", str(target)],
                capture_output=True, text=True, timeout=args.timeout_seconds)
            code = done.returncode
            try:
                figures = parse_census(json.loads(target.read_text()))
            except CensusIncomplete as incomplete:
                error = str(incomplete)
            except (OSError, ValueError):
                error = f"footprint output not parseable (exit {code})"
        except subprocess.TimeoutExpired:
            error = f"footprint timed out after {args.timeout_seconds} s"
        except (OSError, subprocess.SubprocessError) as failure:
            error = f"footprint could not run ({type(failure).__name__})"
    seconds = round(time.monotonic() - start, 1)
    at = args.now if args.now is not None else datetime.now().astimezone()
    keys = ("warnings", "sys_footprint_bytes", "process_footprint_bytes", "unowned_bytes", "processes", "top_owners")
    write_record(args.record, {
        "at": at.isoformat(), "seconds": seconds, "footprint_exit": code, "error": error,
        **{key: figures.get(key) for key in keys},
    })
    if error:
        print(f"{PROG}: {error}", file=sys.stderr)
    return 1 if error else 0


def _run(name: str, argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        raise ReadingError(f"{name} could not run ({type(error).__name__})") from None
    if done.returncode != 0:
        raise CommandFailed(f"{name} exited {done.returncode}", done.returncode)
    return done.stdout


def _read_pid_file(path: Path) -> str | None:
    """The first bytes of Colima's pid file, None when it is absent; `OSError` or `UnicodeDecodeError` when unreadable."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        return os.read(descriptor, PID_FILE_BYTES).decode()
    finally:
        os.close(descriptor)


def _observe(args, processes: dict[int, str], seen) -> dict:
    """What the sources of `omlx_memory_events` show now; None (or `UNREAD`) for one that could not be read."""
    try:
        ram_disks = omlx_memory_events.parse_ram_disks(_run("hdiutil", [args.hdiutil, "info", "-plist"]))
    except (ReadingError, ValueError):
        ram_disks = None
    pid_file = args.colima_pid_file or Path.home() / COLIMA_PID_FILE
    try:
        vm_pid = omlx_memory_events.colima_vm_pid(_read_pid_file(pid_file), processes)
    except (OSError, UnicodeDecodeError):
        vm_pid = omlx_memory_events.UNREAD
    identity, offset = (seen["identity"], seen["offset"]) if seen else (None, 0)
    path = args.slot_history or verify_history.history_path(verify_slot.slot_dir())
    try:
        records, found, consumed = verify_history.read_from(path, identity, offset)
        history = {"records": records, "identity": found, "offset": consumed}
    except (OSError, ValueError):
        history = None
    return {
        "ci_pids": omlx_memory_events.ci_pids(processes), "ram_disks": ram_disks, "vm_pid": vm_pid,
        "verify_live": omlx_memory_events.verify_runs_live(processes), "history": history,
    }


def take_reading(args, previous: dict | None = None) -> dict:
    try:
        vm = parse_vm_stat(_run("vm_stat", [args.vm_stat]))
        total = int(_run("sysctl", [args.sysctl, "-n", "hw.memsize"]).strip())
        service = parse_launchctl(_run("launchctl", [args.launchctl, "print", f"system/{args.label}"]))
    except ValueError as error:
        raise ReadingError(f"output not parseable ({error})") from None
    listing = _run("ps", [args.ps, "-axwwo", "pid=,args="])
    if not listing.strip():
        raise ReadingError("ps printed nothing")
    processes = omlx_memory_events.parse_listing(listing)
    used = used_bytes(vm)
    page = vm["page_size"]
    compressions = vm["compressions"]
    floor = read_fseventsd_record(args.floor_record)
    return {
        "host": args.host, "used_bytes": used, "available_bytes": total - used,
        "loaded": read_health(args.health_url), "ci_jobs": len(omlx_memory_events.ci_pids(processes)),
        "omlx_bytes": read_footprint(args.footprint, service["pid"]),
        "runs": service["runs"], "last_exit_reason": service["last_exit_reason"],
        "jetsam_priority": kernel_priority(service, floor),
        "declared_jetsam_priority": args.omlx_jetsam_priority,
        "fseventsd": read_fseventsd_record(args.fseventsd_record), "floor": floor,
        "wired_bytes": vm["wired"] * page, "anonymous_bytes": vm["anonymous"] * page,
        "compressions_bytes": None if compressions is None else compressions * page,
        "census": read_fseventsd_record(args.census_record),
        "observed": _observe(args, processes, (previous or {}).get("history_seen")),
    }


def read_state(path: Path):
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ReadingError(f"state file {path} is unreadable ({type(error).__name__})") from None
    try:
        document = json.loads(text)
        document["pending"]
    except (ValueError, TypeError, KeyError):
        raise ReadingError(f"state file {path} is not a state document") from None
    return document


def _append(path: Path, document: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, (json.dumps(document) + "\n").encode())
    finally:
        os.close(descriptor)


def _prune_samples(samples: Path, day: str) -> None:
    oldest = date.fromisoformat(day) - timedelta(days=SAMPLE_DAYS)
    for path in samples.glob("*.jsonl"):
        try:
            if date.fromisoformat(path.stem) < oldest:
                path.unlink()
        except (ValueError, FileNotFoundError):
            continue


def write_state(directory: Path, document: dict, line: dict | None, sample: dict | None = None) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    samples = directory / SAMPLES_DIR
    if sample is not None:
        samples.mkdir(mode=0o700, exist_ok=True)
        _append(samples / f"{document['day']}.jsonl", sample)
    if line is not None:
        _append(directory / PEAKS_NAME, line)
        _prune_samples(samples, document["day"])
    temporary = directory / f".{STATE_NAME}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(json.dumps(document, indent=2) + "\n")
        os.replace(temporary, directory / STATE_NAME)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def deliver_pending(state: dict, args, now: datetime) -> bool:
    kept, failed = [], False
    for entry in state["pending"]:
        outcome = host_alerts.deliver(
            entry["kind"], entry["text"], settings=args.alert_settings, log=args.alert_log,
            api=args.telegram_api or host_alerts.API, now=now, record_failure=not entry["logged"])
        if outcome.status == "failed":
            failed = True
            print(f"host alert not sent: {outcome.error}", file=sys.stderr)
            kept.append({**entry, "logged": True})
    state["pending"] = kept
    return failed


def sample(args) -> int:
    now = args.now if args.now is not None else datetime.now().astimezone()
    directory = args.state_dir
    try:
        previous = read_state(directory / STATE_NAME)
        reading = take_reading(args, previous)
    except ReadingError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 1
    state, line, record = decide(
        previous, reading, now, args.floor_gib * GIB, args.others_budget_gib * GIB, args.unowned_alert_gib * GIB)
    failed = deliver_pending(state, args, now)
    for entry in state["floor_log"]:
        print(entry, end="", flush=True)
    state["floor_log"] = []
    write_state(directory, state, line, record)
    return 3 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description="Record the eleven-m5 memory watcher's sample.")
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("sample", help="take one reading, record it and send the alerts it queues")
    one.add_argument("--state-dir", type=Path, required=True)
    one.add_argument("--floor-gib", type=int, required=True)
    one.add_argument("--others-budget-gib", type=int, required=True)
    one.add_argument("--unowned-alert-gib", type=int, required=True)
    one.add_argument("--omlx-jetsam-priority", type=int, required=True)
    one.add_argument("--host", required=True)
    one.add_argument("--label", default="org.nixos.omlx")
    one.add_argument("--health-url", default="http://127.0.0.1:8000/health")
    one.add_argument("--vm-stat", default="/usr/bin/vm_stat")
    one.add_argument("--sysctl", default="/usr/sbin/sysctl")
    one.add_argument("--launchctl", default="/bin/launchctl")
    one.add_argument("--ps", default="/bin/ps")
    one.add_argument("--footprint", default="/usr/bin/footprint")
    one.add_argument("--hdiutil", default="/usr/bin/hdiutil")
    one.add_argument("--slot-history", type=Path, default=None)
    one.add_argument("--colima-pid-file", type=Path, default=None)
    one.add_argument("--alert-settings", type=Path, default=None)
    one.add_argument("--alert-log", type=Path, default=None)
    one.add_argument("--telegram-api", default=None)
    one.add_argument("--fseventsd-record", type=Path, default=Path(FSEVENTSD_RECORD))
    one.add_argument("--floor-record", type=Path, default=Path(FLOOR_RECORD))
    one.add_argument("--census-record", type=Path, default=Path(CENSUS_RECORD))
    one.add_argument("--now", type=datetime.fromisoformat, default=None)
    trim = commands.add_parser("fseventsd", help="restart fseventsd above its limit and record its size")
    trim.add_argument("--record", type=Path, required=True)
    trim.add_argument("--limit-gib", type=int, required=True)
    trim.add_argument("--min-restart-minutes", type=int, default=FSEVENTSD_MINUTES)
    trim.add_argument("--label", default=FSEVENTSD_LABEL)
    trim.add_argument("--launchctl", default="/bin/launchctl")
    trim.add_argument("--footprint", default="/usr/bin/footprint")
    trim.add_argument("--kill", default="/bin/kill")
    trim.add_argument("--now", type=datetime.fromisoformat, default=None)
    count = commands.add_parser("census", help="record footprint -a's system and process footprints")
    count.add_argument("--record", type=Path, required=True)
    count.add_argument("--footprint", default="/usr/bin/footprint")
    count.add_argument("--timeout-seconds", type=int, default=CENSUS_TIMEOUT)
    count.add_argument("--now", type=datetime.fromisoformat, default=None)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {"fseventsd": fseventsd, "census": census}.get(args.command, sample)(args)


if __name__ == "__main__":
    sys.exit(main())
