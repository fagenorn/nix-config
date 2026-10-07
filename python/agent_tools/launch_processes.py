"""The launch-scope platform seam: process table, marker reader, guarded termination (#276).

- `process_table()` runs `ps -A -o pid=,ppid=,pgid=,stat=` by name on PATH
  (D11). A line is three integers and a `stat`, or just the three integers:
  a darwin procps `ps` prints an empty `stat` for live processes, and a missing
  `stat` means not a zombie (D15). An `OSError`, a non-zero exit, or any other
  non-blank line raises `ProcessTableError`. A process is a zombie when its
  `stat` starts with `Z`.
- `read_marker(pid)` returns the `AGENT_LAUNCH_SCOPE` value only when the pid's
  environment is readable and holds that variable: `/proc/<pid>/environ` on
  Linux, `sysctl {CTL_KERN, KERN_PROCARGS2, pid}` on darwin. An unreadable
  environment, a vanished pid, a zombie, or a value that does not decode as
  ASCII is `None`, which is "no proof" and never an error (D7). Any other
  platform raises `UnsupportedPlatform`. Residual (D15): darwin exposes no
  environment for Apple platform binaries (`/bin`, `/usr/bin`), so such a
  process is never proved by its marker and cannot be reaped by marker.
- `protected_pids(table)` is `{1, os.getpid()}` plus every ancestor, found by
  following `ppid` from `os.getpid()`; the walk stops at a pid missing from the
  table, at a pid of 1 or lower, or at a repeat.
- `terminate()` never signals a protected pid, and never calls `send_group` on
  a group with a protected member: that group's other members are signalled
  one by one (spec Signalling). SIGTERM, then SIGKILL for what remains. Every
  poll re-collects the targets from a fresh table (D16): a pid that joins a safe
  recorded group, or that the caller's `is_marked` proves, becomes a target and
  is signalled on its own, and a target whose group changed stays one while
  `is_marked` still proves it; otherwise it is a reused pid and is never sent
  SIGKILL (D11). Its count is the distinct targets SIGTERM actually reached (D14).
- Importing this module loads no libc, runs no `ps` and reads no `/proc`: the
  darwin `ctypes` handle is created lazily, under `functools.cache`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import ctypes
import ctypes.util
from dataclasses import dataclass
import functools
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time

MARKER_ENV = "AGENT_LAUNCH_SCOPE"
TERM_SECONDS = 5.0
KILL_SECONDS = 1.0
POLL_SECONDS = 0.05

_MARKER_PREFIX = MARKER_ENV.encode("ascii") + b"="
_PS_ARGV = ["ps", "-A", "-o", "pid=,ppid=,pgid=,stat="]
_IGNORED_SIGNAL_ERRORS = (ProcessLookupError, PermissionError)

CTL_KERN, KERN_ARGMAX, KERN_PROCARGS2 = 1, 8, 49


class UnsupportedPlatform(Exception):
    """The platform has no environment reader."""


class ProcessTableError(Exception):
    """`ps` could not run, failed, or printed a line that does not parse."""


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    pgid: int
    zombie: bool


def require_supported_platform() -> None:
    if sys.platform not in ("linux", "darwin"):
        raise UnsupportedPlatform(f"launch-scope does not support platform {sys.platform!r}")


def process_table() -> dict[int, Proc]:
    try:
        completed = subprocess.run(_PS_ARGV, capture_output=True, text=True, check=False)
    except OSError as error:
        raise ProcessTableError(f"ps could not run: {error}") from error
    if completed.returncode != 0:
        raise ProcessTableError(f"ps exited {completed.returncode}")
    table = {}
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) not in (3, 4):
            raise ProcessTableError(f"ps line does not have three or four fields: {line!r}")
        try:
            pid, ppid, pgid = (int(field) for field in fields[:3])
        except ValueError as error:
            raise ProcessTableError(f"ps line does not parse: {line!r}") from error
        zombie = len(fields) == 4 and fields[3].startswith("Z")  # no stat: not a zombie (D15)
        table[pid] = Proc(pid, ppid, pgid, zombie)
    return table


def read_marker(pid: int) -> str | None:
    require_supported_platform()
    environment = _linux_environ(pid) if sys.platform == "linux" else _darwin_environ(pid)
    if environment is None:
        return None
    for item in environment:
        if item.startswith(_MARKER_PREFIX):
            try:
                return item[len(_MARKER_PREFIX):].decode("ascii")
            except UnicodeDecodeError:
                return None
    return None


def _linux_environ(pid: int) -> list[bytes] | None:
    try:
        return Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return None


@functools.cache
def _libc():
    return ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)


def _darwin_environ(pid: int) -> list[bytes] | None:
    libc = _libc()
    argmax, size = ctypes.c_int(0), ctypes.c_size_t(ctypes.sizeof(ctypes.c_int))
    if libc.sysctl((ctypes.c_int * 2)(CTL_KERN, KERN_ARGMAX), 2,
                   ctypes.byref(argmax), ctypes.byref(size), None, 0) != 0:
        return None
    buffer, size = ctypes.create_string_buffer(argmax.value), ctypes.c_size_t(argmax.value)
    if libc.sysctl((ctypes.c_int * 3)(CTL_KERN, KERN_PROCARGS2, pid), 3,
                   buffer, ctypes.byref(size), None, 0) != 0:
        return None                      # EINVAL for pid 1, ESRCH, EPERM: no proof
    raw = buffer.raw[:size.value]
    if len(raw) < 4:
        return None
    (argc,) = struct.unpack_from("i", raw, 0)
    rest = raw[4:]
    end = rest.find(b"\0")               # end of the exec path
    if end < 0:
        return None
    while end < len(rest) and rest[end] == 0:
        end += 1                         # NUL padding
    strings = rest[end:].split(b"\0")
    if argc < 0 or len(strings) < argc:
        return None
    environment = []
    for item in strings[argc:]:
        if not item:
            break                        # the environment ends at the first empty string
        environment.append(item)
    return environment


def protected_pids(table: Mapping[int, Proc]) -> frozenset[int]:
    protected = {1, os.getpid()}
    current = os.getpid()
    while current in table:
        parent = table[current].ppid
        if parent <= 1 or parent in protected:
            break
        protected.add(parent)
        current = parent
    return frozenset(protected)


def terminate(pids: Iterable[int], groups: Iterable[int], *, read_table=process_table,
              send=os.kill, send_group=os.killpg, is_marked=None, term_seconds=TERM_SECONDS,
              kill_seconds=KILL_SECONDS) -> tuple[int, frozenset[int]]:
    """Signal the live, unprotected targets; return (SIGTERM reached, survivors).

    Membership is re-collected from every fresh table (D16): a target stays one
    while it is live in its group, or, when `is_marked` is given, while it still
    carries the launch's marker; and a pid that appears in a safe recorded group,
    or that `is_marked` proves, joins as a new target and is signalled on its own.
    """
    table = read_table()
    protected = protected_pids(table)
    groups = set(groups)
    unsafe = {proc.pgid for proc in table.values() if proc.pid in protected} | protected
    safe_groups = {group for group in groups if group > 1 and group not in unsafe}
    targets = {pid: table[pid].pgid for pid in pids
               if pid in table and not table[pid].zombie}
    targets.update({pid: proc.pgid for pid, proc in table.items()
                    if proc.pgid in groups and not proc.zombie})
    targets = {pid: pgid for pid, pgid in targets.items() if pid > 1 and pid not in protected}
    members = _Membership(targets, safe_groups, protected, is_marked)
    if is_marked is not None:
        # The caller's targets come from an earlier table: a marked process
        # forked since then (by a target that has exited) joins now (D16).
        targets = members.refresh(table)
    if not targets:
        return 0, frozenset()
    reached = _deliver(signal.SIGTERM, targets, safe_groups, send, send_group)
    remaining = _await(members, read_table, term_seconds, signal.SIGTERM, send, reached)
    if remaining:
        _deliver(signal.SIGKILL, remaining, safe_groups, send, send_group)
        remaining = _await(members, read_table, kill_seconds, signal.SIGKILL, send, set())
    return len(reached), frozenset(remaining)


class _Membership:
    """The cleanup's targets, re-collected from each fresh table (D16)."""

    def __init__(self, targets: Mapping[int, int], safe_groups: set[int],
                 protected: frozenset[int], is_marked) -> None:
        self.targets = dict(targets)
        self.signalled = set(targets)
        self.safe_groups = safe_groups
        self.protected = protected
        self.is_marked = is_marked
        self.markers: dict[tuple[int, int, int], bool] = {}

    def marked(self, proc: Proc) -> bool:
        """Whether `proc` carries the marker; one read per (pid, ppid, pgid) seen live."""
        key = (proc.pid, proc.ppid, proc.pgid)
        if key not in self.markers:
            self.markers[key] = bool(self.is_marked(proc.pid))
        return self.markers[key]

    def refresh(self, table: Mapping[int, Proc]) -> dict[int, int]:
        live = {pid: proc for pid, proc in table.items()
                if not proc.zombie and pid > 1 and pid not in self.protected}
        self.markers = {key: value for key, value in self.markers.items()
                        if key[0] in live and (live[key[0]].ppid, live[key[0]].pgid) == key[1:]}
        current = {}
        for pid, pgid in self.targets.items():
            proc = live.get(pid)
            if proc is None:
                continue                 # absent or a zombie: gone
            if proc.pgid == pgid or (self.is_marked is not None and self.marked(proc)):
                current[pid] = proc.pgid  # a marked group-changer is still live (D16)
            # an unmarked pid in another group is a reused pid (D11)
        for pid, proc in live.items():
            if pid not in current and (proc.pgid in self.safe_groups or (
                    self.is_marked is not None and self.marked(proc))):
                current[pid] = proc.pgid  # forked since the last table (D16)
        self.targets = current
        return current

    def unsignalled(self) -> dict[int, int]:
        return {pid: pgid for pid, pgid in self.targets.items() if pid not in self.signalled}


def _deliver(sig, targets: Mapping[int, int], safe_groups: set[int], send,
             send_group) -> set[int]:
    reached = set()
    for group in sorted(safe_groups & set(targets.values())):
        try:
            send_group(group, sig)
        except _IGNORED_SIGNAL_ERRORS:  # darwin: EPERM for a zombie-only group (D11)
            continue
        reached.update(pid for pid, pgid in targets.items() if pgid == group)
    for pid, pgid in sorted(targets.items()):
        if pgid in safe_groups:
            continue
        try:
            send(pid, sig)
        except _IGNORED_SIGNAL_ERRORS:
            continue
        reached.add(pid)
    return reached


def _await(members: _Membership, read_table, seconds: float, sig, send,
           reached: set[int]) -> dict[int, int]:
    """Poll until every target is gone, sending `sig` to each target that joins meanwhile."""
    deadline = time.monotonic() + seconds
    members.signalled = set(members.targets)
    while True:
        remaining = members.refresh(read_table())
        for pid in sorted(members.unsignalled()):
            members.signalled.add(pid)
            try:
                send(pid, sig)           # one by one: its group may hold a target mid-shutdown
            except _IGNORED_SIGNAL_ERRORS:
                continue
            reached.add(pid)
        if not remaining or time.monotonic() >= deadline:
            return remaining
        time.sleep(POLL_SECONDS)
