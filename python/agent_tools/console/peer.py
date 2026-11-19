"""`peer`: which process holds the client end of a loopback connection to the console (#1294).

The owner port admits only connections whose client end is held by the owner's own processes.
This module answers the lookup; it decides nothing about HTTP. A *holder* is a process seen
holding the client end (`Holder(pid, uid, command)`); on Linux the socket's recorded owner is
also a holder, with `pid=None`: it must match the owner but is never by itself evidence of a
process. A holder's `command` never affects `refusal`, so the owner's `sshd-session` (an SSH
local forward) is admitted like any other process of the owner.

`refusal(holders, owner_uid)` is `None` (admitted) or `(code, text)`: `unreadable` with
`UNREADABLE_TEXT` when the lookup did not complete (`holders` is `None`), `other_user` with
`NOT_OWNER_TEXT` when any holder has another uid, `not_found` with `NOT_OWNER_TEXT` when no
holder has a pid. The check fails closed: only a completed lookup whose every holder is the
owner admits.

macOS (`read_lsof`) runs `/usr/sbin/lsof -w -nP -iTCP@<client ip>:<client port> -Fpcun` once, with
a `LOOKUP_TIMEOUT_SECONDS` timeout and no state filter, so a half-closed client end (FIN_WAIT_1
or 2 after `shutdown(SHUT_WR)`) is attributed like an established one. `-i` matches both ends of
the connection; only the file named exactly `<client ip>:<client port>-><server ip>:<server
port>` makes its process a holder, never the server end. Only a completed lookup admits: exit 0
with empty stderr parses stdout; exit 1 with empty stdout and empty stderr (lsof found no
matching file) is `()`; every other outcome, including exit 1 with any stdout and any non-empty
stderr, is `None`. Measured cost: about 50 ms per lsof run.

Linux (`read_proc`) finds the row for the connection in `/proc/net/tcp` and `/proc/net/tcp6`
(an IPv4-mapped address in either), in any state; its `uid` column is the socket's owner, a
pid-less holder. Holders with a pid are the processes whose `/proc/<pid>/fd/*` links read
`socket:[<inode>]`, one holder per distinct value of the `Uid:` line of `/proc/<pid>/status`
(real, effective, saved, filesystem), so a set-user-ID process or a socket owned by another uid
refuses. A TIME_WAIT row (inode 0) has no holder. Either proc table unreadable, or a holder's
`status` or `comm` unreadable, is `None`, never a skipped table.

`read_lsof` and `read_proc` never raise: any `OSError`, `subprocess.TimeoutExpired` or `ValueError`
is `None`. `reader_for(platform)` names the reader (`darwin` lsof, `linux*` proc, else `None`).

What the lookup cannot see: a non-root lookup sees only its own user's processes, so another
user's connection has no holder (not-owner), and a descriptor an owner process hands to another
user's process is seen only through the owner's holder (ADR-console-076 D6).
"""

import os
import socket
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

LSOF = "/usr/sbin/lsof"
LOOKUP_TIMEOUT_SECONDS = 2.0
NOT_OWNER_TEXT = "this console answers only its owner's own processes"
UNREADABLE_TEXT = "the connecting process could not be read"

Address = tuple[str, int]


@dataclass(frozen=True)
class Holder:
    pid: int | None
    uid: int
    command: str | None


PeerReader = Callable[[Address, Address], tuple[Holder, ...] | None]


def refusal(holders: tuple[Holder, ...] | None, owner_uid: int) -> tuple[str, str] | None:
    if holders is None:
        return "unreadable", UNREADABLE_TEXT
    if any(holder.uid != owner_uid for holder in holders):
        return "other_user", NOT_OWNER_TEXT
    if not any(holder.pid is not None for holder in holders):
        return "not_found", NOT_OWNER_TEXT
    return None


def parse_lsof(output: str, client: Address, server: Address) -> tuple[Holder, ...]:
    wanted = f"{client[0]}:{client[1]}->{server[0]}:{server[1]}"
    holders: dict[int, Holder] = {}
    pid: int | None = None
    command: str | None = None
    uid: int | None = None
    for line in output.splitlines():
        tag, value = line[:1], line[1:]
        if tag == "p":
            pid, command, uid = int(value), None, None
        elif tag == "c":
            command = value
        elif tag == "u":
            uid = int(value)
        elif tag == "n" and value == wanted:
            if pid is None or uid is None:
                raise ValueError("a matching file before its process and user")
            holders.setdefault(pid, Holder(pid, uid, command))
    return tuple(holders.values())


def read_lsof(client: Address, server: Address, *, run=subprocess.run) -> tuple[Holder, ...] | None:
    argv = [LSOF, "-w", "-nP", f"-iTCP@{client[0]}:{client[1]}", "-Fpcun"]
    try:
        done = run(argv, capture_output=True, text=True, timeout=LOOKUP_TIMEOUT_SECONDS,
                   check=False)
        if done.returncode == 0 and done.stderr == "":
            return parse_lsof(done.stdout, client, server)
        if done.returncode == 1 and done.stdout == "" and done.stderr == "":
            return ()
        return None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _word(packed: bytes) -> str:
    return f"{int.from_bytes(packed, sys.byteorder):08X}"


def _proc_address(address: Address, mapped: bool) -> str:
    packed = socket.inet_aton(address[0])
    if mapped:
        words = _word(bytes(4)) + _word(bytes(4)) + _word(bytes([0, 0, 255, 255])) + _word(packed)
    else:
        words = _word(packed)
    return f"{words}:{address[1]:04X}"


def _rows(path: Path, client: Address, server: Address, mapped: bool) -> list[tuple[int, str]]:
    local = _proc_address(client, mapped)
    remote = _proc_address(server, mapped)
    found = []
    for line in path.read_text().splitlines()[1:]:
        fields = line.split()
        if not fields:
            continue
        if len(fields) < 10:
            raise ValueError("a short proc table row")
        if fields[1] == local and fields[2] == remote and fields[9] != "0":
            found.append((int(fields[7]), fields[9]))
    return found


def _credentials(status: str) -> list[int]:
    for line in status.splitlines():
        if line.startswith("Uid:"):
            return list(dict.fromkeys(int(value) for value in line.split()[1:]))
    raise ValueError("a status file without Uid")


def read_proc(client: Address, server: Address, *, root: Path = Path("/proc")) -> tuple[Holder, ...] | None:
    try:
        rows = (_rows(root / "net/tcp", client, server, False)
                + _rows(root / "net/tcp6", client, server, True))
        if not rows:
            return ()
        holders = [Holder(None, uid, None) for uid in dict.fromkeys(uid for uid, _ in rows)]
        inodes = {f"socket:[{inode}]" for _, inode in rows}
        for entry in sorted(name for name in os.listdir(root) if name.isdigit()):
            fd = root / entry / "fd"
            try:
                names = os.listdir(fd)
            except (PermissionError, FileNotFoundError):
                continue
            held = False
            for name in names:
                try:
                    held = os.readlink(fd / name) in inodes
                except FileNotFoundError:
                    continue
                if held:
                    break
            if not held:
                continue
            command = (root / entry / "comm").read_text().rstrip("\n")
            for uid in _credentials((root / entry / "status").read_text()):
                holders.append(Holder(int(entry), uid, command))
        return tuple(holders)
    except (OSError, ValueError):
        return None


def reader_for(platform: str) -> PeerReader | None:
    if platform == "darwin":
        return read_lsof
    if platform.startswith("linux"):
        return read_proc
    return None
