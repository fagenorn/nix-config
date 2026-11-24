"""The eleven-m5 memory floor: which processes are workloads and which are protected.

A workload is a group of processes the floor may end together to give memory back. Every workload
belongs to a declared owner: the agent user, or a CI runner user.

- An agent-user process is a direct member of the workload `agent:<dir>` when its cwd is inside a
  declared root glob (`<dir>` is the part of the cwd the glob matched); otherwise it joins the
  workload of its nearest ancestor, and has none when the walk meets a protected or undeclared
  ancestor, or pid 1.
- A runner-user `Runner.Worker` starts the workload `ci:<user>:<pid>` and its descendants join it;
  a runner-user process whose parent is pid 1 and that is not protected joins `ci:<user>:orphans`.
- A process of any other user is never in a workload, wherever its cwd or ancestors are.

Protected processes are never in a workload: pids 0 and 1, the oMLX server and every descendant of
it, and each service process the host runs for the system (the process only, not its children).

The selection is pure over a process table, so it runs against stubbed tables. The enforcement loop
reaches the machine only through `Io`: it samples available memory, ends the largest workload while
memory stays under the floor for the declared samples (and any workload over the run bound), and
records each kill. The daemon runs as root and polices the agent uid, so it writes no path that uid
can write: its only writes are its record (through `omlx_memory_watch.write_record`, which replaces a
symlink rather than following it) and its lines on stdout, which launchd sends to the daemon's log.

launchd ignores this daemon's `JetsamProperties` for oMLX, so the kernel jetsam priority is set
here, on the running pid, through `memorystatus_control`: a relaunched oMLX gets the declared
priority on the next sample. The record keeps the value read at the start of each sample (before
any set) and counts the samples that found it changed again after a set succeeded, so a value that
does not hold shows; a read-back right after a set would prove nothing.

The `gate` command is the oMLX relaunch gate: it runs before `exec omlx serve` and waits while
available memory is under the floor, so it holds only a starting oMLX, never a serving one, and
launchd's KeepAlive still owns the relaunch. It only reads memory (it signals nothing and runs no
launchctl) and starts at once when memory cannot be read.
"""

import argparse
import ctypes
import errno
import fnmatch
import json
import os
import pwd
import signal
import struct
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_tools.hosts.omlx_memory_watch import (
    GIB,
    ReadingError,
    _run,
    kill_line,
    parse_launchctl,
    parse_vm_stat,
    used_bytes,
    write_record,
)

PROG = "memory-floor"
WORKER = "Runner.Worker"
RECENT = 50
FOOTPRINT_OFFSET = 72
CWD_OFFSET = 152
PROC_PIDVNODEPATHINFO = 9
LIBSYSTEM = "/usr/lib/libSystem.B.dylib"
GET_PRIORITY_LIST = 1
SET_PRIORITY_PROPERTIES = 2
ENTRY = struct.Struct("<iiQiI")  # memorystatus_priority_entry_t: pid, priority, user_data, limit, state
PROPERTIES = struct.Struct("<i4xQ")  # memorystatus_priority_properties_t: priority, user_data


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    uid: int
    command: str
    cwd: str | None
    footprint: int


@dataclass(frozen=True)
class Owners:
    agent_uid: int
    agent_user: str
    agent_roots: tuple[str, ...]
    runners: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class Workload:
    key: str
    owner: str
    root_pid: int
    root_command: str
    pids: tuple[int, ...]
    size: int


def parse_ps(text: str) -> dict[int, tuple[int, int, str]]:
    table = {}
    for line in text.splitlines():
        fields = line.split(None, 3)
        if len(fields) < 3:
            continue
        try:
            pid, ppid, uid = int(fields[0]), int(fields[1]), int(fields[2])
        except ValueError:
            continue
        table[pid] = (ppid, uid, fields[3] if len(fields) > 3 else "")
    if not table:
        raise ValueError("no process line parsed from ps output")
    return table


def parse_launchctl_list(text: str) -> set[int]:
    pids = set()
    for line in text.splitlines()[1:]:
        first = line.split("\t", 1)[0].strip()
        if first.isdigit():
            pids.add(int(first))
    return pids


def root_of(cwd: str | None, roots: tuple[str, ...]) -> str | None:
    if not cwd:
        return None
    parts = cwd.split("/")
    for root in roots:
        globs = root.split("/")
        count = len(globs)
        if len(parts) >= count and all(
            fnmatch.fnmatchcase(part, pattern) for part, pattern in zip(parts, globs)
        ):
            return "/".join(parts[:count])
    return None


def protected_pids(table: dict[int, Proc], omlx_pid: int | None, service_pids: set[int]) -> set[int]:
    protected = {0, 1} | set(service_pids)
    if omlx_pid is not None:
        protected.add(omlx_pid)
        children: dict[int, list[int]] = {}
        for proc in table.values():
            children.setdefault(proc.ppid, []).append(proc.pid)
        pending = [omlx_pid]
        while pending:
            for child in children.get(pending.pop(), ()):
                if child not in protected:
                    protected.add(child)
                    pending.append(child)
    return protected


def _program(command: str) -> str:
    first = command.split(None, 1)
    return first[0].rsplit("/", 1)[-1] if first else ""


def _depth(table: dict[int, Proc], pid: int) -> int:
    seen = {pid}
    depth = 0
    parent = table[pid].ppid
    while parent in table and parent not in seen:
        seen.add(parent)
        depth += 1
        parent = table[parent].ppid
    return depth


def workloads(table: dict[int, Proc], owners: Owners, protected: set[int]) -> list[Workload]:
    runner_names = dict(owners.runners)
    assigned: dict[int, tuple[str, str] | None] = {}

    def assign(pid: int, visiting: frozenset[int] = frozenset()) -> tuple[str, str] | None:
        if pid in assigned:
            return assigned[pid]
        proc = table.get(pid)
        if proc is None or pid <= 1 or pid in protected or pid in visiting:
            return None
        found = None
        if proc.uid == owners.agent_uid:
            matched = root_of(proc.cwd, owners.agent_roots)
            if matched is not None:
                found = (f"agent:{matched}", owners.agent_user)
            else:
                found = assign(proc.ppid, visiting | {pid})
                if found is not None and found[1] != owners.agent_user:
                    found = None
        elif proc.uid in runner_names:
            name = runner_names[proc.uid]
            if _program(proc.command) == WORKER:
                found = (f"ci:{name}:{pid}", name)
            elif proc.ppid == 1:
                found = (f"ci:{name}:orphans", name)
            else:
                found = assign(proc.ppid, visiting | {pid})
                if found is not None and found[1] != name:
                    found = None
        assigned[pid] = found
        return found

    members: dict[str, tuple[str, list[int]]] = {}
    for pid in table:
        found = assign(pid)
        if found is not None:
            members.setdefault(found[0], (found[1], []))[1].append(pid)

    result = []
    for key, (owner, pids) in members.items():
        depths = {pid: _depth(table, pid) for pid in pids}
        root = min(pids, key=lambda pid: (depths[pid], pid))
        ordered = tuple(sorted(pids, key=lambda pid: (-depths[pid], -pid)))
        result.append(
            Workload(
                key=key,
                owner=owner,
                root_pid=root,
                root_command=table[root].command,
                pids=ordered,
                size=sum(table[pid].footprint for pid in pids),
            )
        )
    return sorted(result, key=lambda w: (-w.size, w.key))


@dataclass(frozen=True)
class Limits:
    floor_bytes: int
    floor_samples: int
    grace_seconds: float
    margin_bytes: int
    fall_bytes: int
    fast_seconds: float
    slow_seconds: float
    run_bound_bytes: int
    jetsam_priority: int


@dataclass
class Io:
    available: Callable[[], int]
    table: Callable[[], dict[int, Proc]]
    services: Callable[[], set[int]]
    omlx_pid: Callable[[], int | None]
    signal: Callable[[int, int], None]
    alive: Callable[[int], bool]
    sleep: Callable[[float], None]
    clock: Callable[[], float]
    now: Callable[[], datetime]
    priority_get: Callable[[int], int | None]
    priority_set: Callable[[int, int], None]


@dataclass
class Loop:
    streak: int = 0
    previous: int | None = None
    no_workload_open: bool = False
    priority_failed_pid: int | None = None
    priority_pid: int | None = None
    priority_reads: int = 0
    priority_resets: int = 0
    priority_set: bool = False


def kernel_priority(pid: int, control: Callable[[int, int, int, bytearray], int]) -> int | None:
    buffer = bytearray(ENTRY.size)
    if control(GET_PRIORITY_LIST, pid, 0, buffer) < ENTRY.size:
        return None
    entry_pid, priority, *_ = ENTRY.unpack(buffer)
    return priority if entry_pid == pid else None


def set_kernel_priority(pid: int, priority: int, control: Callable[[int, int, int, bytearray], int]) -> None:
    control(SET_PRIORITY_PROPERTIES, pid, 0, bytearray(PROPERTIES.pack(priority, 0)))


def read_available(vm_stat: str, sysctl: str) -> int:
    try:
        return int(sysctl.strip()) - used_bytes(parse_vm_stat(vm_stat))
    except ValueError as error:
        raise ReadingError(f"memory output not parseable ({error})") from None


def wait_for_floor(
    read_available: Callable[[], int], floor_bytes: int, interval: float,
    sleep: Callable[[float], None], log: Callable[[str], None],
) -> int:
    """Wait while available memory is under the floor; return the number of waits."""
    waits = 0
    while True:
        try:
            available = read_available()
        except ReadingError as error:
            log(f"oMLX start: memory unreadable ({error}); starting")
            return waits
        if available >= floor_bytes:
            if waits:
                log(f"oMLX start: available {available / GIB:.1f} GiB, starting after {waits} waits")
            return waits
        if not waits:
            log(f"oMLX start waits: available {available / GIB:.1f} GiB is under the {floor_bytes // GIB} GiB floor")
        waits += 1
        sleep(interval)


def next_interval(limits: Limits, available: int, previous: int | None, streak: int) -> float:
    near = available < limits.floor_bytes + limits.margin_bytes
    falling = previous is not None and previous - available >= limits.fall_bytes
    return limits.fast_seconds if near or falling or streak > 0 else limits.slow_seconds


def _send(io: Io, pid: int, sig: int) -> None:
    try:
        io.signal(pid, sig)
    except ProcessLookupError:
        pass


def end_workload(workload: Workload, io: Io, grace_seconds: float, poll_seconds: float = 0.25) -> str:
    for pid in workload.pids:
        _send(io, pid, signal.SIGTERM)
    deadline = io.clock() + grace_seconds
    while io.clock() < deadline and any(io.alive(pid) for pid in workload.pids):
        io.sleep(poll_seconds)
    stubborn = [pid for pid in workload.pids if io.alive(pid)]
    for pid in stubborn:
        _send(io, pid, signal.SIGKILL)
    return "term+kill" if stubborn else "term"


def _complain(error: ReadingError) -> None:
    print(f"{PROG}: {error}", file=sys.stderr)


def _candidates(io: Io, owners: Owners) -> tuple[list[Workload], int | None] | None:
    """The workloads now, largest first, and the oMLX pid; None (after naming the cause) when a protection input is unreadable."""
    try:
        services, omlx_pid, table = io.services(), io.omlx_pid(), io.table()
    except ReadingError as error:
        _complain(error)
        return None
    return workloads(table, owners, protected_pids(table, omlx_pid, services)), omlx_pid


def enforce_once(
    limits: Limits, owners: Owners, io: Io, loop: Loop, record: dict, out: Callable[[str], None]
) -> float:
    try:
        available = io.available()
    except ReadingError as error:
        _complain(error)
        _stamp(limits, io, loop, record, None, limits.fast_seconds)
        return limits.fast_seconds
    loop.streak = loop.streak + 1 if available < limits.floor_bytes else 0
    if loop.streak == 0:
        loop.no_workload_open = False
    attempted: set[int] = set()

    def end(workload: Workload, reason: str) -> bool:
        """End one workload and read memory again; False when that reading failed."""
        nonlocal available
        before = available
        attempted.add(workload.root_pid)
        signals = end_workload(workload, io, limits.grace_seconds)
        try:
            available = io.available()
            readable = True
        except ReadingError as error:
            _complain(error)
            readable = False
        if available >= limits.floor_bytes:
            loop.streak = 0
        entry = {
            "seq": record.get("kills", 0) + 1, "at": io.now().isoformat(timespec="seconds"),
            "reason": reason, "owner": workload.owner, "root_pid": workload.root_pid,
            "root_command": workload.root_command, "processes": len(workload.pids),
            "tree_bytes": workload.size, "available_before_bytes": before,
            "available_after_bytes": available, "signals": signals,
        }
        record["kills"] = entry["seq"]
        record["recent"] = [*record.get("recent", []), entry][-RECENT:]
        out(kill_line(entry))
        return readable

    first = _candidates(io, owners)
    unreadable = first is None
    for workload in first[0] if first else ():
        if workload.size > limits.run_bound_bytes and not end(workload, "run_bound"):
            unreadable = True
            break
    while not unreadable and loop.streak >= limits.floor_samples:
        again = _candidates(io, owners)
        if again is None:
            break
        remaining = [w for w in again[0] if w.root_pid not in attempted]
        if not remaining:
            if not loop.no_workload_open:
                loop.no_workload_open = True
                out(
                    f"{io.now().isoformat(timespec='seconds')} floor_breached no agent workload"
                    f" to end available_gib={available / GIB:.1f}\n"
                )
            break
        unreadable = not end(remaining[0], "floor")
    if first is not None:
        _prioritize(limits, io, loop, record, first[1], out)
    interval = next_interval(limits, available, loop.previous, loop.streak)
    loop.previous = available
    _stamp(limits, io, loop, record, available, interval)
    return interval


def _prioritize(
    limits: Limits, io: Io, loop: Loop, record: dict, pid: int | None, out: Callable[[str], None]
) -> None:
    """Read oMLX's kernel jetsam priority and set it to the declared one when it differs."""
    declared = limits.jetsam_priority
    if pid != loop.priority_pid:
        loop.priority_pid = pid
        loop.priority_reads = loop.priority_resets = 0
        loop.priority_set = False
    current, error = None, None
    if pid is not None:
        loop.priority_reads += 1
        try:
            current = io.priority_get(pid)
            if current is not None and current != declared:
                io.priority_set(pid, declared)
                if loop.priority_set:
                    loop.priority_resets += 1
                loop.priority_set = True
                out(
                    f"{io.now().isoformat(timespec='seconds')} jetsam_priority pid={pid}"
                    f" from={current} to={declared} resets={loop.priority_resets}\n"
                )
        except OSError as failure:
            error = errno.errorcode.get(failure.errno or 0, type(failure).__name__)
            if loop.priority_failed_pid != pid:
                loop.priority_failed_pid = pid
                out(f"{io.now().isoformat(timespec='seconds')} jetsam_priority_failed pid={pid} error={error}\n")
    record.update(
        omlx_pid=pid, omlx_kernel_priority=current, omlx_priority_reads=loop.priority_reads,
        omlx_priority_resets=loop.priority_resets, declared_priority=declared, omlx_priority_error=error,
    )


def _stamp(limits: Limits, io: Io, loop: Loop, record: dict, available: int | None, interval: float) -> None:
    at = io.now().isoformat(timespec="seconds")
    record.setdefault("since", at)
    record.setdefault("kills", 0)
    record.setdefault("recent", [])
    record.update(
        at=at, floor_bytes=limits.floor_bytes, run_bound_bytes=limits.run_bound_bytes,
        streak=loop.streak, interval_seconds=interval,
    )
    if available is not None:
        record["available_bytes"] = available


def step(
    limits: Limits, owners: Owners, io: Io, loop: Loop, record: dict, record_path: Path,
    out: Callable[[str], None],
) -> float:
    interval = enforce_once(limits, owners, io, loop, record, out)
    try:
        write_record(record_path, record)
    except OSError as error:
        print(f"{PROG}: record not written ({type(error).__name__})", file=sys.stderr)
    return interval


def read_record(path: Path) -> dict | None:
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _libproc_readers(path: str) -> tuple[Callable[[int], int], Callable[[int], str | None]]:
    lib = ctypes.CDLL(path)
    lib.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    lib.proc_pidinfo.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int
    ]

    def footprint(pid: int) -> int:
        buffer = ctypes.create_string_buffer(96)
        if lib.proc_pid_rusage(pid, 0, buffer) != 0:
            return 0
        return struct.unpack_from("<Q", buffer, FOOTPRINT_OFFSET)[0]

    def cwd(pid: int) -> str | None:
        buffer = ctypes.create_string_buffer(2352)
        if lib.proc_pidinfo(pid, PROC_PIDVNODEPATHINFO, 0, buffer, 2352) <= CWD_OFFSET:
            return None
        return buffer.raw[CWD_OFFSET:].split(b"\0", 1)[0].decode(errors="replace") or None

    return footprint, cwd


def _memorystatus_control(path: str) -> Callable[[int, int, int, bytearray], int]:
    lib = ctypes.CDLL(path, use_errno=True)
    call = lib.memorystatus_control
    call.argtypes = [ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_size_t]
    call.restype = ctypes.c_int

    def control(command: int, pid: int, flags: int, buffer: bytearray) -> int:
        raw = (ctypes.c_char * len(buffer)).from_buffer(buffer)
        result = call(command, pid, flags, ctypes.addressof(raw), len(buffer))
        if result == -1:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        return result

    return control


def build_io(args, owners: Owners) -> Io:
    footprint, cwd = _libproc_readers(args.libproc)
    relevant = {owners.agent_uid, *(uid for uid, _ in owners.runners)}

    def available() -> int:
        return read_available(
            _run("vm_stat", [args.vm_stat]), _run("sysctl", [args.sysctl, "-n", "hw.memsize"])
        )

    def table() -> dict[int, Proc]:
        try:
            listing = parse_ps(_run("ps", [args.ps, "-axo", "pid=,ppid=,uid=,command="]))
        except ValueError as error:
            raise ReadingError(f"ps output not parseable ({error})") from None
        # Only the owners' processes can join a workload, so only theirs are measured.
        return {
            pid: Proc(
                pid, ppid, uid, command,
                cwd(pid) if uid == owners.agent_uid else None,
                footprint(pid) if uid in relevant else 0,
            )
            for pid, (ppid, uid, command) in listing.items()
        }

    def services() -> set[int]:
        return parse_launchctl_list(_run("launchctl", [args.launchctl, "list"]))

    def omlx_pid() -> int | None:
        try:
            return parse_launchctl(_run("launchctl", [args.launchctl, "print", f"system/{args.label}"]))["pid"]
        except ValueError as error:
            raise ReadingError(f"launchctl output not parseable ({error})") from None

    def alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    control = _memorystatus_control(LIBSYSTEM)
    return Io(
        available, table, services, omlx_pid, os.kill, alive, time.sleep, time.monotonic,
        lambda: datetime.now().astimezone(),
        lambda pid: kernel_priority(pid, control),
        lambda pid, priority: set_kernel_priority(pid, priority, control),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description="End the largest agent workload under the eleven-m5 memory floor.")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("enforce", help="sample memory and end workloads under the floor or over the run bound")
    run.add_argument("--floor-gib", type=int, required=True)
    run.add_argument("--floor-samples", type=int, default=3)
    run.add_argument("--grace-seconds", type=float, default=5)
    run.add_argument("--margin-gib", type=int, default=16)
    run.add_argument("--fall-gib", type=int, default=2)
    run.add_argument("--fast-seconds", type=float, default=2)
    run.add_argument("--slow-seconds", type=float, default=10)
    run.add_argument("--run-bound-gib", type=int, required=True)
    run.add_argument("--omlx-jetsam-priority", type=int, required=True)
    run.add_argument("--agent-user", required=True)
    run.add_argument("--agent-root", action="append", required=True)
    run.add_argument("--runner-user", action="append", default=[])
    run.add_argument("--record", type=Path, required=True)
    run.add_argument("--label", default="org.nixos.omlx")
    run.add_argument("--vm-stat", default="/usr/bin/vm_stat")
    run.add_argument("--sysctl", default="/usr/sbin/sysctl")
    run.add_argument("--launchctl", default="/bin/launchctl")
    run.add_argument("--ps", default="/bin/ps")
    run.add_argument("--libproc", default="/usr/lib/libproc.dylib")
    run.add_argument("--once", action="store_true")
    gate = commands.add_parser("gate", help="hold oMLX's start until available memory is back over the floor")
    gate.add_argument("--floor-gib", type=int, required=True)
    gate.add_argument("--interval-seconds", type=float, required=True)
    gate.add_argument("--vm-stat", default="/usr/bin/vm_stat")
    gate.add_argument("--sysctl", default="/usr/sbin/sysctl")
    return parser


def _owners(args) -> Owners:
    try:
        agent_uid = pwd.getpwnam(args.agent_user).pw_uid
    except KeyError:
        raise SystemExit(f"{PROG}: unknown agent user {args.agent_user}") from None
    runners = []
    for name in args.runner_user:
        try:
            runners.append((pwd.getpwnam(name).pw_uid, name))
        except KeyError:
            print(f"{PROG}: unknown runner user {name}, skipped", file=sys.stderr)
    return Owners(agent_uid, args.agent_user, tuple(args.agent_root), tuple(runners))


def _print_line(line: str) -> None:
    sys.stdout.write(line)
    sys.stdout.flush()


def enforce(args) -> int:
    owners = _owners(args)
    limits = Limits(
        args.floor_gib * GIB, args.floor_samples, args.grace_seconds, args.margin_gib * GIB,
        args.fall_gib * GIB, args.fast_seconds, args.slow_seconds, args.run_bound_gib * GIB,
        args.omlx_jetsam_priority,
    )
    io = build_io(args, owners)
    loop, record = Loop(), read_record(args.record) or {}
    while True:
        interval = step(limits, owners, io, loop, record, args.record, _print_line)
        if args.once:
            return 0
        io.sleep(interval)


def _log_line(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def gate(args) -> int:
    def available() -> int:
        return read_available(
            _run("vm_stat", [args.vm_stat]), _run("sysctl", [args.sysctl, "-n", "hw.memsize"])
        )

    wait_for_floor(available, args.floor_gib * GIB, args.interval_seconds, time.sleep, _log_line)
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return gate(args) if args.command == "gate" else enforce(args)


if __name__ == "__main__":
    sys.exit(main())
