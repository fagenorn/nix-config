"""The committed read-only checks that verify blocks name (issue 638).

Each check is a pure function plus one `main` subcommand, run through a wrapper in
`home/common/verify-pending/checks/`. Every check prints one JSON line and exits 0 when met,
1 when not met, 75 when not yet, and 2 on a usage error or an unreadable input.

`scheduled-pass --host H` is met only when the process running it descends from the installed
scheduled job: the store-path `verify-pending-pass H` started by the service manager (launchd,
pid 1, or `systemd --user`). With `--after-switch` it instead measures the gap from the change
time of `/run/current-system` to the first `pass start host=H` line at or after it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

SWITCH_GAP = 60
PASS_SCRIPT = re.compile(r"^/nix/store/[0-9a-z]{32}-verify-pending-pass$")
CHAIN_BOUND = 64
HOST = re.compile(r"^[a-z0-9-]+$")
_PASS_START = re.compile(r"^(\S+) pass start host=([a-z0-9-]+)$")
_STAMP = "%Y-%m-%dT%H:%M:%SZ"

Proc = tuple[int, int, tuple[str, ...]]  # (pid, ppid, argv)


def _started_by_service_manager(ppid: int, parent: Proc | None) -> bool:
    if ppid == 1:
        return True
    if parent is None or not parent[2]:
        return False
    return os.path.basename(parent[2][0]) == "systemd" and "--user" in parent[2]


def job_ancestor(chain: Sequence[Proc], host: str) -> int | None:
    """The pid of the installed pass script for `host` that the service manager started."""
    for index, (pid, ppid, argv) in enumerate(chain):
        named = any(PASS_SCRIPT.match(token) and following == host
                    for token, following in zip(argv, argv[1:]))
        parent = chain[index + 1] if index + 1 < len(chain) else None
        if named and _started_by_service_manager(ppid, parent):
            return pid
    return None


def _read_proc(pid: int) -> Proc | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        ppid = int(stat.rsplit(")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return None
    argv = tuple(part.decode("utf-8", "replace") for part in raw.split(b"\0") if part)
    return (pid, ppid, argv)


def _read_ps(pid: int) -> Proc | None:
    try:
        done = subprocess.run(["ps", "-o", "ppid=", "-o", "args=", "-p", str(pid)],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    fields = done.stdout.split()
    if done.returncode != 0 or not fields:
        return None
    try:
        return (pid, int(fields[0]), tuple(fields[1:]))
    except ValueError:
        return None


def process_chain(pid: int) -> list[Proc]:
    """The processes from `pid` upward, ending at pid 1, a failed read or CHAIN_BOUND entries."""
    read = _read_proc if Path("/proc/self/stat").exists() else _read_ps
    chain: list[Proc] = []
    while len(chain) < CHAIN_BOUND:
        entry = read(pid)
        if entry is None:
            break
        chain.append(entry)
        if pid == 1 or entry[1] <= 0:
            break
        pid = entry[1]
    return chain


def scheduled_pass(chain: Sequence[Proc], host: str) -> tuple[int, dict]:
    pid = job_ancestor(chain, host)
    if pid is None:
        return 75, {"host": host, "job_pid": None}
    return 0, {"host": host, "job_pid": pid}


def _stamp(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, _STAMP).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def after_switch(lines: Sequence[str], host: str, switched_at: datetime,
                 now: datetime) -> tuple[int, dict]:
    boundary = switched_at.replace(microsecond=0)
    started = None
    for line in lines:
        found = _PASS_START.match(line.strip())
        if not found or found.group(2) != host:
            continue
        at = _stamp(found.group(1))
        if at is not None and at >= boundary:
            started = at
            break
    gap = None if started is None else int((started - boundary).total_seconds())
    report = {"host": host, "switched_at": boundary.strftime(_STAMP),
              "pass_start": None if started is None else started.strftime(_STAMP),
              "gap_s": gap}
    if started is not None:
        return (0 if gap <= SWITCH_GAP else 1), report
    if (now - boundary).total_seconds() > SWITCH_GAP:
        return 1, report
    return 75, report


def _host(value: str) -> str:
    if not HOST.match(value):
        raise argparse.ArgumentTypeError("must match ^[a-z0-9-]+$")
    return value


def _instant(value: str) -> datetime:
    at = _stamp(value)
    if at is None:
        raise argparse.ArgumentTypeError("must be YYYY-MM-DDTHH:MM:SSZ")
    return at


def _read_log(log: Path) -> list[str]:
    lines: list[str] = []
    rotated = Path(f"{log}.1")
    if rotated.exists():
        lines += rotated.read_text(encoding="utf-8", errors="replace").splitlines()
    try:
        lines += log.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        pass
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify-checks")
    checks = parser.add_subparsers(dest="check", required=True)
    sched = checks.add_parser("scheduled-pass",
                              help="issues 630, 632: inside the installed scheduled pass")
    sched.add_argument("--host", type=_host, required=True)
    sched.add_argument("--after-switch", action="store_true")
    sched.add_argument("--log", type=Path,
                       default=Path.home() / ".agents/state/verify-pending/runner.log")
    sched.add_argument("--current-system", type=Path, default=Path("/run/current-system"))
    sched.add_argument("--now", type=_instant, default=None)
    args = parser.parse_args(argv)
    if args.after_switch:
        try:
            switched_at = datetime.fromtimestamp(os.lstat(args.current_system).st_mtime,
                                                 timezone.utc)
            lines = _read_log(args.log)
        except OSError as error:
            print(f"verify-checks: cannot read: {error.strerror or error}", file=sys.stderr)
            return 2
        now = args.now if args.now is not None else datetime.now(timezone.utc)
        code, report = after_switch(lines, args.host, switched_at, now)
    else:
        code, report = scheduled_pass(process_chain(os.getppid()), args.host)
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
