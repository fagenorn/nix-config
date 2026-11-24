"""`omlx-memory-watch`: the eleven-m5 memory watcher, one sample per run.

`omlx-memory-watch sample --state-dir DIR --floor-gib N --others-budget-gib N
--omlx-jetsam-priority N --host NAME [--label org.nixos.omlx] [--health-url URL] [--vm-stat PATH]
[--sysctl PATH] [--launchctl PATH] [--ps PATH] [--footprint PATH] [--alert-settings FILE]
[--alert-log FILE] [--telegram-api URL] [--now ISO8601]` takes one reading of the host and
records it. Used memory is (anonymous pages - purgeable pages + wired pages + compressor pages)
x the page size of `vm_stat`; available is `hw.memsize` minus used. A model is loaded when the
health URL (read without any proxy, 5 s) answers `engine_pool.loaded_count >= 1`. The oMLX
footprint is `phys_footprint` of `footprint -p <pid>` for the pid `launchctl print
system/<label>` shows, unknown when that is missing or fails; the memory of everything else is
used minus that footprint, counted only on a loaded sample whose footprint is known. CI jobs
are the `Runner.Worker` processes of `ps -axo comm=`, every user's, since a job runs under a
runner account.

`DIR/memory-watch.json` (mode 0600 in a 0700 directory, replaced atomically) holds the day's
`since`, `day`, `peak_used_bytes`, `peak_others_bytes`, `peak_omlx_bytes`,
`min_available_bytes`, `samples`, `loaded_samples`, `min_loaded_available_bytes`,
`peak_ci_jobs`, `jetsam_exits`, `omlx_runs`, `omlx_jetsam_priority`, `low_memory_open` and
`pending` (alerts not yet delivered, each `{kind, text, logged}`). `DIR/memory-peaks.jsonl`
gets one line per finished day: `day`, the peaks and minimum in GiB (null where unmeasured),
`others_budget_gib`, `over_budget`, `jetsam_exits`, `peak_ci_jobs`, `samples`,
`loaded_samples`, `min_loaded_available_gib`, `floor_gib`, `omlx_jetsam_priority` and
`declared_jetsam_priority`.

An alert is queued when the service's `runs` changed and its last exit reason is the memory
killer's (`jetsam`), and when available memory falls under the floor while a model is loaded
(`low_memory`, once per episode). The first sample only records a baseline. Each queued alert
is delivered through `agent_tools.hosts.host_alerts`, in order, before the state is written;
one that fails stays queued, is logged once and is retried by the next sample.

Exit 0: recorded, every alert delivered or recorded. 3: recorded, at least one alert not sent
(stderr `host alert not sent: <reason>`). 1: `vm_stat`, `sysctl`, `launchctl` or `ps` failed
or printed nothing parseable (stderr names it; nothing is written). 2: usage. A failed
`footprint` is not a failed reading.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from agent_tools.hosts import host_alerts

GIB = 1024**3
PROG = "omlx-memory-watch"
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


def parse_vm_stat(text: str) -> dict:
    header = re.search(r"page size of (\d+) bytes", text)
    found = {"page_size": int(header.group(1))} if header else {}
    for line in text.splitlines():
        name, separator, value = line.partition(":")
        key = VM_FIELDS.get(name.strip())
        if separator and key and re.fullmatch(r"\s*\d+\.?\s*", value):
            found[key] = int(value.strip().rstrip("."))
    if len(found) != len(VM_FIELDS) + 1:
        raise ValueError("vm_stat output lacks the page size or a memory field")
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


def count_ci_jobs(text: str) -> int:
    names = (line.strip().strip("()") for line in text.splitlines())
    return sum(1 for name in names if name.rsplit("/", 1)[-1] == "Runner.Worker")


def parse_footprint(text: str) -> int | None:
    match = FOOTPRINT_LINE.search(text)
    return int(match.group(1)) if match else None


def fresh_day(since: str, day: str) -> dict:
    return {
        "since": since, "day": day, "peak_used_bytes": 0, "peak_others_bytes": None,
        "peak_omlx_bytes": None, "min_available_bytes": None, "samples": 0, "loaded_samples": 0,
        "min_loaded_available_bytes": None, "peak_ci_jobs": 0, "jetsam_exits": 0, "omlx_runs": None,
        "omlx_jetsam_priority": None, "low_memory_open": False, "pending": [],
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
    }


def decide(state, reading: dict, now: datetime, floor_bytes: int, others_budget_bytes: int):
    """Fold one reading into the state; answer the new state and the finished day's line or None."""
    day = now.date().isoformat()
    line = None
    if state is None:
        state = fresh_day(day, day)
    else:
        state = {**state, "pending": [dict(entry) for entry in state["pending"]]}
        if state["day"] != day:
            line = _day_line(state, floor_bytes, others_budget_bytes, reading["declared_jetsam_priority"])
            carried = fresh_day(state["since"], day)
            for key in ("omlx_runs", "omlx_jetsam_priority", "low_memory_open", "pending"):
                carried[key] = state[key]
            state = carried
    used, available, loaded = reading["used_bytes"], reading["available_bytes"], reading["loaded"]
    omlx = reading["omlx_bytes"]
    footprint = "unknown" if omlx is None else f"{omlx / GIB:.1f}"
    memory = f"Used {used / GIB:.1f} GiB, available {available / GIB:.1f} GiB, oMLX footprint {footprint} GiB."
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
    return state, line


def read_health(url: str) -> bool:
    try:
        with DIRECT.open(url, timeout=HEALTH_TIMEOUT) as response:
            count = json.loads(response.read())["engine_pool"]["loaded_count"]
    except (OSError, ValueError, KeyError, TypeError):
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


def _run(name: str, argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        raise ReadingError(f"{name} could not run ({type(error).__name__})") from None
    if done.returncode != 0:
        raise ReadingError(f"{name} exited {done.returncode}")
    return done.stdout


def take_reading(args) -> dict:
    try:
        vm = parse_vm_stat(_run("vm_stat", [args.vm_stat]))
        total = int(_run("sysctl", [args.sysctl, "-n", "hw.memsize"]).strip())
        service = parse_launchctl(_run("launchctl", [args.launchctl, "print", f"system/{args.label}"]))
    except ValueError as error:
        raise ReadingError(f"output not parseable ({error})") from None
    listing = _run("ps", [args.ps, "-axo", "comm="])
    if not listing.strip():
        raise ReadingError("ps printed nothing")
    used = used_bytes(vm)
    return {
        "host": args.host, "used_bytes": used, "available_bytes": total - used,
        "loaded": read_health(args.health_url), "ci_jobs": count_ci_jobs(listing),
        "omlx_bytes": read_footprint(args.footprint, service["pid"]),
        "runs": service["runs"], "last_exit_reason": service["last_exit_reason"],
        "jetsam_priority": service["jetsam_priority"],
        "declared_jetsam_priority": args.omlx_jetsam_priority,
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


def write_state(directory: Path, document: dict, line: dict | None) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if line is not None:
        descriptor = os.open(directory / PEAKS_NAME, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(descriptor, (json.dumps(line) + "\n").encode())
        finally:
            os.close(descriptor)
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
        reading = take_reading(args)
    except ReadingError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 1
    state, line = decide(previous, reading, now, args.floor_gib * GIB, args.others_budget_gib * GIB)
    failed = deliver_pending(state, args, now)
    write_state(directory, state, line)
    return 3 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description="Record the eleven-m5 memory watcher's sample.")
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("sample", help="take one reading, record it and send the alerts it queues")
    one.add_argument("--state-dir", type=Path, required=True)
    one.add_argument("--floor-gib", type=int, required=True)
    one.add_argument("--others-budget-gib", type=int, required=True)
    one.add_argument("--omlx-jetsam-priority", type=int, required=True)
    one.add_argument("--host", required=True)
    one.add_argument("--label", default="org.nixos.omlx")
    one.add_argument("--health-url", default="http://127.0.0.1:8000/health")
    one.add_argument("--vm-stat", default="/usr/bin/vm_stat")
    one.add_argument("--sysctl", default="/usr/sbin/sysctl")
    one.add_argument("--launchctl", default="/bin/launchctl")
    one.add_argument("--ps", default="/bin/ps")
    one.add_argument("--footprint", default="/usr/bin/footprint")
    one.add_argument("--alert-settings", type=Path, default=None)
    one.add_argument("--alert-log", type=Path, default=None)
    one.add_argument("--telegram-api", default=None)
    one.add_argument("--now", type=datetime.fromisoformat, default=None)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return sample(args)


if __name__ == "__main__":
    sys.exit(main())
