"""The events the eleven-m5 memory watcher records beside each sample, and what they are read from.

Each sample line of `omlx-memory-watch sample` ends with `events`, a list of the changes since the
previous sample, in this order (every event is a JSON object whose `kind` names its shape):

1. RAM disks, from `hdiutil info -plist`: `ram_disk_detached`, then `ram_disk_attached`, each by `dev`:
   `{"kind", "dev": "/dev/disk5", "mount": "/Volumes/X" or null, "gib": 1.0}`.
2. The Colima VM, from the pid in Colima's own `vz.pid` file while that pid is a live process:
   `vm_stopped` for the old pid, then `vm_started` for the new one: `{"kind", "pid": 71379}`. Only that
   file names the VM: the host runs other Virtualization-framework processes that are not Colima.
3. CI jobs, the `Runner.Worker` processes of `ps -axwwo pid=,args=`: `ci_job_ended`, then
   `ci_job_started`, by pid: `{"kind", "pid": 9002}`.
4. Live `verify-slot run` processes of the same listing: `verify_ended`, then `verify_started`, by pid:
   `{"kind", "pid": 25432, "command": "just test"}` (an ended run carries the command last seen).
5. Finished verify runs, the lines the verify-slot history gained: `verify_run`, one per run that held a
   slot, in history order: `{"kind", "repository", "command", "exit", "held_from", "held_until"}`, where
   `held_from` is the run's `started` plus its `waited_seconds` and `held_until` is `held_from` plus its
   `held_seconds`, both ISO 8601 in UTC (`+00:00`).
6. Floor kills (`floor_kill`, appended by the watcher from the floor record's new `recent` entries):
   `{"kind", "at", "reason", "owner", "root_pid", "signals", "tree_gib"}`.

A source seen for the first time records its baseline and emits nothing; for the history the baseline
consumes the whole file once. A source that could not be read emits nothing and keeps what it last saw: a
failed `hdiutil`, an unreadable pid file (`UNREAD`; an absent one is read, and means the VM is not
running) or an unreadable history. The history is read from the offset the state holds while its identity
(`[st_dev, st_ino]`) is unchanged and the file has not shrunk, and from its first line otherwise. The
watcher never takes a slot's lock. RAM disks, CI jobs and live verify runs are snapshots: one that starts
and ends between two samples is not recorded.

`fold_events(state, observed)` is the one entry point; the `*_seen` keys of `EVENT_DEFAULTS` are the
state it keeps. `parse_listing`, `ci_pids`, `verify_runs_live`, `colima_vm_pid`, `parse_ram_disks` and
`verify_events` read one source each.
"""

import plistlib
import re
from datetime import datetime, timedelta, timezone
from xml.parsers.expat import ExpatError

from agent_tools.delivery import verify_history

GIB = 1024**3
CI_PROCESS = "Runner.Worker"
VERIFY_MODULE = "agent_tools.delivery.verify_slot"
UNREAD = "unread"
EVENT_DEFAULTS = {
    "ci_pids_seen": None, "vm_seen": None, "ram_disks_seen": None, "verify_live_seen": None, "history_seen": None,
}
LISTING_LINE = re.compile(r"^\s*(\d+)\s+(.*?)\s*$")


def parse_listing(listing: str) -> dict[int, str]:
    """The pid -> args of `ps -axwwo pid=,args=`; a line that does not match is skipped."""
    found = {}
    for line in listing.splitlines():
        match = LISTING_LINE.match(line)
        if match:
            found[int(match.group(1))] = match.group(2)
    return found


def ci_pids(processes: dict[int, str]) -> list[int]:
    """The sorted pids of the `Runner.Worker` processes, shown by name as `(Runner.Worker)` to other accounts."""
    found = []
    for pid, args in processes.items():
        if args.startswith("(") and args.endswith(")"):
            args = args[1:-1]
        words = args.split()
        if words and words[0].rsplit("/", 1)[-1] == CI_PROCESS:
            found.append(pid)
    return sorted(found)


def _is_verify_run(words: list[str]) -> bool:
    if len(words) >= 2 and words[0].rsplit("/", 1)[-1] == "verify-slot" and words[1] == "run":
        return True
    return any(words[index:index + 3] == ["-m", VERIFY_MODULE, "run"] for index in range(len(words)))


def verify_runs_live(processes: dict[int, str]) -> dict[int, str]:
    """pid -> command of each live `verify-slot run`, the command being the words after its first `--`."""
    found = {}
    for pid, args in processes.items():
        words = args.split()
        if not _is_verify_run(words):
            continue
        command = words[words.index("--") + 1:][:verify_history.COMMAND_WORDS] if "--" in words else []
        found[pid] = " ".join(command)
    return found


def colima_vm_pid(pid_text: str | None, processes: dict[int, str]) -> int | None:
    """The pid in Colima's pid file when it is all digits and a live process; otherwise None."""
    if pid_text is None:
        return None
    text = pid_text.strip()
    if not (text.isascii() and text.isdigit()):
        return None
    pid = int(text)
    return pid if pid in processes else None


def parse_ram_disks(text: str) -> dict[str, dict]:
    """The RAM disks of `hdiutil info -plist` as dev -> `{"mount", "bytes"}`; `ValueError` when it is no plist."""
    try:
        document = plistlib.loads(text.encode())
    except (plistlib.InvalidFileException, ExpatError) as error:
        raise ValueError(f"hdiutil output is not a plist ({type(error).__name__})") from None
    images = document.get("images") if isinstance(document, dict) else None
    if not isinstance(images, list):
        raise ValueError("hdiutil output has no images list")
    found = {}
    for image in images:
        if not isinstance(image, dict) or not str(image.get("image-path", "")).startswith("ram://"):
            continue
        entities = [entity for entity in image.get("system-entities") or []
                    if isinstance(entity, dict) and isinstance(entity.get("dev-entry"), str)]
        entities.sort(key=lambda entity: entity["dev-entry"])
        count, size = image.get("blockcount"), image.get("blocksize")
        if not entities or not all(isinstance(value, int) and not isinstance(value, bool) for value in (count, size)):
            continue
        dev = min((entity["dev-entry"] for entity in entities), key=lambda name: (len(name), name))
        mount = next((entity["mount-point"] for entity in entities
                      if isinstance(entity.get("mount-point"), str) and entity["mount-point"]), None)
        found[dev] = {"mount": mount, "bytes": count * size}
    return found


def _started(text: str) -> datetime:
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def verify_events(runs: list[dict]) -> list[dict]:
    """One `verify_run` per run that held a slot, in the order given."""
    events = []
    for run in runs:
        if run["held_seconds"] is None:
            continue
        try:
            held_from = _started(run["started"]) + timedelta(seconds=run["waited_seconds"])
            held_until = held_from + timedelta(seconds=run["held_seconds"])
        except (ValueError, OverflowError):
            continue
        events.append({
            "kind": "verify_run", "repository": run["repository"], "command": run["command"], "exit": run["exit"],
            "held_from": held_from.isoformat(),
            "held_until": held_until.isoformat(),
        })
    return events


def _disk_event(kind: str, dev: str, disk: dict) -> dict:
    return {"kind": kind, "dev": dev, "mount": disk["mount"], "gib": round(disk["bytes"] / GIB, 1)}


def _fold_ram_disks(state: dict, disks: dict | None) -> list[dict]:
    if disks is None:
        return []
    seen, state["ram_disks_seen"] = state["ram_disks_seen"], disks
    if seen is None:
        return []
    return ([_disk_event("ram_disk_detached", dev, seen[dev]) for dev in sorted(seen) if dev not in disks]
            + [_disk_event("ram_disk_attached", dev, disks[dev]) for dev in sorted(disks) if dev not in seen])


def _fold_vm(state: dict, pid) -> list[dict]:
    if pid == UNREAD:
        return []
    seen, state["vm_seen"] = state["vm_seen"], {"pid": pid}
    if seen is None or seen["pid"] == pid:
        return []
    events = []
    if seen["pid"] is not None:
        events.append({"kind": "vm_stopped", "pid": seen["pid"]})
    if pid is not None:
        events.append({"kind": "vm_started", "pid": pid})
    return events


def _fold_ci(state: dict, pids: list[int]) -> list[dict]:
    seen, state["ci_pids_seen"] = state["ci_pids_seen"], list(pids)
    if seen is None:
        return []
    return ([{"kind": "ci_job_ended", "pid": pid} for pid in sorted(set(seen) - set(pids))]
            + [{"kind": "ci_job_started", "pid": pid} for pid in sorted(set(pids) - set(seen))])


def _fold_verify_live(state: dict, live: dict[int, str]) -> list[dict]:
    seen, state["verify_live_seen"] = state["verify_live_seen"], {str(pid): command for pid, command in live.items()}
    if seen is None:
        return []
    ended = sorted(int(pid) for pid in seen if int(pid) not in live)
    return ([{"kind": "verify_ended", "pid": pid, "command": seen[str(pid)]} for pid in ended]
            + [{"kind": "verify_started", "pid": pid, "command": live[pid]} for pid in sorted(live) if str(pid) not in seen])


def _fold_history(state: dict, history: dict | None) -> list[dict]:
    if history is None:
        return []
    seen, state["history_seen"] = state["history_seen"], {"identity": history["identity"], "offset": history["offset"]}
    return [] if seen is None else verify_events(history["records"])


def fold_events(state: dict, observed: dict) -> list[dict]:
    """Update the five `*_seen` keys of `state` from `observed` and answer the events, in the module's order."""
    return (_fold_ram_disks(state, observed["ram_disks"])
            + _fold_vm(state, observed["vm_pid"])
            + _fold_ci(state, observed["ci_pids"])
            + _fold_verify_live(state, observed["verify_live"])
            + _fold_history(state, observed["history"]))
