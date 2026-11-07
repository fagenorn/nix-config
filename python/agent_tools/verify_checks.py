"""The committed read-only checks that verify blocks name (issue 638).

Each check is a pure function plus one `main` subcommand, run through a wrapper in
`home/common/verify-pending/checks/`. Every check prints one JSON line and exits 0 when met,
1 when not met, 75 when not yet, and 2 on a usage error or an unreadable input.

`scheduled-pass --host H` is met only when the process running it descends from the installed
scheduled job: the store-path `verify-pending-pass H` started by the service manager (launchd,
pid 1, or `systemd --user`). With `--after-switch` it instead measures the gap from the change
time of `/run/current-system` to the first `pass start host=H` line at or after it.

`required-checks --repo R --base B --since T` is met when the first pull request merged into B
after T had every required check pass before its merge. It only reads the forge, across every
page of each listing, and refuses an incomplete or truncated listing rather than judging it.
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
from urllib.parse import quote

from agent_tools import forge_markers
from agent_tools.agent_costs import parse_rfc3339_utc

SWITCH_GAP = 60
PASS_SCRIPT = re.compile(r"^/nix/store/[0-9a-z]{32}-verify-pending-pass$")
CHAIN_BOUND = 64
HOST = re.compile(r"^[a-z0-9-]+$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
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


def _invalid(detail: str) -> forge_markers.ForgeError:
    return forge_markers.ForgeError("payload_invalid", detail)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _forge_time(value: object, what: str) -> datetime:
    try:
        return parse_rfc3339_utc(value)  # type: ignore[arg-type]
    except ValueError:
        raise _invalid(f"{what} is not an RFC 3339 instant") from None


def _counted_pages(pages: Sequence[object], key: str, what: str) -> list[object]:
    """The items of `key` over every page, refused when fewer than the first page's total_count."""
    found: list[object] = []
    total = None
    for page in pages:
        if (not isinstance(page, dict) or not isinstance(page.get(key), list)
                or not _is_int(page.get("total_count"))):
            raise _invalid(f"{what} page has no {key} list and total_count")
        if total is None:
            total = page["total_count"]
        found.extend(page[key])
    if total is not None and len(found) < total:
        raise _invalid(f"{what} is truncated: {len(found)} of {total}")
    return found


def _merged_pull_numbers(repo: str, base: str, since: datetime) -> list[int]:
    since_z = since.astimezone(timezone.utc).strftime(_STAMP)
    query = quote(f"repo:{repo} is:pr is:merged base:{base} merged:>{since_z}", safe="")
    pages = forge_markers.api_pages(
        f"search/issues?q={query}&sort=created&order=asc&per_page=100")
    for page in pages:
        if isinstance(page, dict) and page.get("incomplete_results") is not False:
            raise _invalid("search listing reports incomplete results")
    numbers = []
    for item in _counted_pages(pages, "items", "search listing"):
        if not isinstance(item, dict) or not _is_int(item.get("number")):
            raise _invalid("search item has no number")
        numbers.append(item["number"])
    return numbers


def _required_contexts(repo: str, base: str) -> set[str]:
    payload = forge_markers.api_get(
        f"repos/{repo}/branches/{base}/protection/required_status_checks")
    if not isinstance(payload, dict):
        raise _invalid("required_status_checks is not an object")
    found: set[str] = set()
    for entry in payload.get("checks") or []:
        if isinstance(entry, dict) and isinstance(entry.get("context"), str):
            found.add(entry["context"])
    for context in payload.get("contexts") or []:
        if isinstance(context, str):
            found.add(context)
    return found


def _context_met(context: str, runs: Sequence[object], statuses: Sequence[object],
                 merged_at: datetime) -> bool:
    for run in runs:
        if (isinstance(run, dict) and run.get("name") == context
                and run.get("status") == "completed" and run.get("conclusion") == "success"
                and _forge_time(run.get("completed_at"), "check run completed_at") <= merged_at):
            return True
    latest = None
    for status in statuses:
        if not isinstance(status, dict) or status.get("context") != context:
            continue
        updated = _forge_time(status.get("updated_at"), "status updated_at")
        if updated <= merged_at and (latest is None or updated > latest[0]):
            latest = (updated, status.get("state"))
    return latest is not None and latest[1] == "success"


def required_checks(repo: str, base: str, since: datetime) -> tuple[int, dict]:
    """Met when the first pull request merged into `base` after `since` passed every required check."""
    report: dict = {"pr": None, "merged_at": None, "required": [], "missing": []}
    first = None
    for number in _merged_pull_numbers(repo, base, since):
        pull = forge_markers.api_get(f"repos/{repo}/pulls/{number}")
        if not isinstance(pull, dict):
            raise _invalid(f"pull request {number} is not an object")
        if pull.get("merged_at") is None:
            continue
        merged_at = _forge_time(pull["merged_at"], "merged_at")
        if merged_at > since and (first is None or merged_at < first[0]):
            first = (merged_at, number, pull)
    if first is None:
        return 75, report
    merged_at, number, pull = first
    head = pull.get("head")
    sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(sha, str) or not sha:
        raise _invalid("pull request has no head sha")
    report.update(pr=number, merged_at=pull["merged_at"])
    required = _required_contexts(repo, base)
    report["required"] = sorted(required)
    if not required:
        return 1, report
    runs = _counted_pages(forge_markers.api_pages(
        f"repos/{repo}/commits/{sha}/check-runs?per_page=100"), "check_runs", "check-run listing")
    status_pages = forge_markers.api_pages(f"repos/{repo}/commits/{sha}/statuses?per_page=100")
    if not all(isinstance(page, list) for page in status_pages):
        raise _invalid("status page is not a list")
    statuses = [entry for page in status_pages for entry in page]
    report["missing"] = sorted(c for c in required
                               if not _context_met(c, runs, statuses, merged_at))
    return (0 if not report["missing"] else 1), report


def _host(value: str) -> str:
    if not HOST.match(value):
        raise argparse.ArgumentTypeError("must match ^[a-z0-9-]+$")
    return value


def _instant(value: str) -> datetime:
    at = _stamp(value)
    if at is None:
        raise argparse.ArgumentTypeError("must be YYYY-MM-DDTHH:MM:SSZ")
    return at


def _repo(value: str) -> str:
    if not REPO.match(value):
        raise argparse.ArgumentTypeError("must be OWNER/NAME")
    return value


def _rfc3339(value: str) -> datetime:
    try:
        return parse_rfc3339_utc(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an RFC 3339 instant with Z or an offset") from None


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
    required = checks.add_parser("required-checks",
                                 help="issue 627: required checks passed before the merge")
    required.add_argument("--repo", type=_repo, required=True)
    required.add_argument("--base", required=True)
    required.add_argument("--since", type=_rfc3339, required=True)
    args = parser.parse_args(argv)
    if args.check == "required-checks":
        try:
            code, report = required_checks(args.repo, args.base, args.since)
        except forge_markers.ForgeError as error:
            print(f"verify-checks: forge_error: {error.code}", file=sys.stderr)
            return 2
    elif args.after_switch:
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
