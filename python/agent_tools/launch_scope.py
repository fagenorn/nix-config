"""Run a lifecycle launch's commands in a scope, and reap what they leave (#276).

    launch-scope exec --repo-root R --run-id I (--action-id A | --worker-id W) -- <argv>

`exec` writes a registry row under `<git common dir of R>/agent-launch/I/A/`,
asks `workflow-state check-launch` (or `check-worker` for a worker, whose action
is its ID without the `:w<n>` suffix) and, only on a strict positive reply,
runs `<argv>` in a new session with `AGENT_LAUNCH_SCOPE=I/A/<nonce>` added to its
environment. SIGINT, SIGTERM and SIGHUP are forwarded to the command's group.
When the command exits, every process carrying that exact marker and every
member of the command's group is terminated, and the row is deleted.

Exit codes:
  <status>  the command's own exit status, or 128 plus the signal that killed it
  3         refused: nothing started; one JSON line {"action_id", "reason", "started": false}
  126, 127  the command cannot be run, or is not found, as a shell reports it
  2         a usage or helper error, with nothing on stdout

A process that survives SIGKILL keeps the row for `reap`; `exec` names it on
stderr and still exits with the command's status.

Residual: a process that leaves the command's session and also scrubs
`AGENT_LAUNCH_SCOPE` from its environment is outside the scope. So is, on
darwin, an Apple platform binary that left the session, because its
environment cannot be read.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time

from agent_tools.agent_platform import write_atomically
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.launch_commit import (
    CHECK_WORKER_FAILED, LIVE, MALFORMED_REPLY, LaunchCommitError, ask_worker)
from agent_tools.launch_processes import (
    MARKER_ENV, ProcessTableError, UnsupportedPlatform, process_table, read_marker,
    require_supported_platform, terminate)

REGISTRY_DIR = "agent-launch"
SAFE_SEGMENT = re.compile(r"[A-Za-z0-9._:-]+")
NONCE = re.compile(r"[0-9a-f]{32}")
ROW_KEYS = frozenset({"nonce", "pgid", "started_at", "argv0"})
CURRENT = "current"
CHECK_LAUNCH_FAILED = "check_launch_failed"
REFUSED_EXIT = 3
USAGE_EXIT = 2
SEPARATOR = "--"

_REPLY_KEYS = frozenset({"action_id", "current", "current_action_id", "reason"})
_FORWARDED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
_IGNORED_SIGNAL_ERRORS = (ProcessLookupError, PermissionError)


class LaunchScopeError(Exception):
    """A usage or helper error; main exits 2."""


def canonical_line(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def safe_segment(value: str, label: str) -> str:
    """`value`, when it is one safe path segment (D10)."""
    if SAFE_SEGMENT.fullmatch(value) is None or value in (".", ".."):
        raise LaunchScopeError(f"{label} {value!r} is not a safe path segment")
    return value


def worker_action(worker_id: str) -> str:
    """The launch a worker belongs to: its ID without the `:w<n>` suffix (D2)."""
    return worker_id.rpartition(":w")[0]


def registry_root(repo_root: str) -> Path:
    """`<git common dir of repo_root>/agent-launch`."""
    try:
        completed = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "--path-format=absolute",
             "--git-common-dir"], capture_output=True, text=True, check=False)
    except OSError as error:
        raise LaunchScopeError(f"cannot run git: {error}") from error
    if completed.returncode != 0:
        raise LaunchScopeError(f"git cannot find the common dir of {repo_root!r}")
    return Path(completed.stdout.strip()) / REGISTRY_DIR


def launch_directory(registry: Path, run_id: str, action_id: str) -> Path:
    return registry / safe_segment(run_id, "run id") / safe_segment(action_id, "action id")


def launch_marker(run_id: str, action_id: str, nonce: str) -> str:
    return f"{run_id}/{action_id}/{nonce}"


def check_launch_reply(stdout: bytes, action_id: str) -> str:
    """The reply's reason for `action_id`, or "malformed_reply" for anything inexact (D4)."""
    try:
        reply = json.loads(stdout, object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except ValueError:
        return MALFORMED_REPLY
    if not isinstance(reply, dict) or set(reply) != _REPLY_KEYS:
        return MALFORMED_REPLY
    current, reason = reply["current"], reply["reason"]
    current_action_id = reply["current_action_id"]
    if (type(current) is not bool or reply["action_id"] != action_id
            or not isinstance(reason, str)
            or not (current_action_id is None or isinstance(current_action_id, str))
            or current is not (reason == CURRENT)
            or (current and current_action_id != action_id)):
        return MALFORMED_REPLY
    return reason


def ask_launch(repo_root: str, run_id: str, action_id: str) -> str:
    """Ask `workflow-state check-launch` on PATH; a non-zero exit is `check_launch_failed`."""
    try:
        completed = subprocess.run(
            ["workflow-state", "check-launch", "--repo-root", repo_root,
             "--run-id", run_id, "--action-id", action_id],
            capture_output=True, check=False)
    except OSError as error:
        raise LaunchScopeError(f"cannot run workflow-state: {error}") from error
    if completed.returncode != 0:
        return CHECK_LAUNCH_FAILED
    return check_launch_reply(completed.stdout, action_id)


def _write_row(row: Path, nonce: str, pgid: int | None, started_at: str, argv0: str) -> None:
    value = {"argv0": argv0, "nonce": nonce, "pgid": pgid, "started_at": started_at}
    try:
        write_atomically(row, (canonical_line(value) + "\n").encode("utf-8"))
    except OSError as error:
        raise LaunchScopeError(f"cannot write registry row {row}: {error}") from error


def _delete_row(row: Path) -> None:
    """Delete this exec's own row; one already gone (a reap got there first) is fine."""
    try:
        row.unlink(missing_ok=True)
    except OSError as error:
        raise LaunchScopeError(f"cannot delete registry row {row}: {error}") from error


def _signal_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except _IGNORED_SIGNAL_ERRORS:
        pass


class _Forwarder:
    """Forward SIGINT, SIGTERM and SIGHUP to the child's group, queueing until it exists."""

    def __init__(self) -> None:
        self.pgid: int | None = None
        self.detached = False
        self.pending: list[int] = []
        self.previous: dict[int, object] = {}

    def install(self) -> None:
        for signum in _FORWARDED:
            self.previous[signum] = signal.signal(signum, self._handle)

    def _handle(self, signum, frame) -> None:
        if self.detached:
            return                       # the child has exited and been cleaned up
        if self.pgid is None:
            self.pending.append(signum)
        else:
            _signal_group(self.pgid, signum)

    def attach(self, pgid: int) -> None:
        self.pgid = pgid
        pending, self.pending = self.pending, []
        for signum in pending:
            _signal_group(pgid, signum)

    def detach(self) -> None:
        """Stop forwarding before the child is reaped, after which its pgid may be reused (D11)."""
        self.detached = True

    def restore(self) -> None:
        for signum, handler in self.previous.items():
            signal.signal(signum, signal.SIG_DFL if handler is None else handler)


def _clean_up(marker: str, pgid: int) -> frozenset[int]:
    """Terminate every live pid carrying exactly `marker`, plus the child's group."""
    table = process_table()
    marked = [pid for pid, proc in table.items()
              if not proc.zombie and read_marker(pid) == marker]
    return terminate(marked, [pgid])[1]


def _clean_up_after_failure(marker: str, pgid: int) -> bool:
    """Best-effort cleanup after an exception past the spawn; True when proven clean (D14)."""
    _signal_group(pgid, signal.SIGTERM)
    try:
        return not _clean_up(marker, pgid)
    except ProcessTableError:
        _signal_group(pgid, signal.SIGKILL)
        return False


def exec_scoped(repo_root: str, run_id: str, argv: Sequence[str], *,
                action_id: str | None = None,
                worker_id: str | None = None) -> tuple[int, dict | None]:
    """Run `argv` in the launch's scope: (exit status, None) or (3, refusal)."""
    require_supported_platform()
    action = action_id if worker_id is None else worker_action(worker_id)
    safe_segment(run_id, "run id")
    safe_segment(action, "action id")
    directory = launch_directory(registry_root(repo_root), run_id, action)
    if not argv:
        raise LaunchScopeError(f"no command after {SEPARATOR}")

    nonce = secrets.token_hex(16)
    row = directory / f"{nonce}.json"
    marker = launch_marker(run_id, action, nonce)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_row(row, nonce, None, started_at, argv[0])
    try:
        if worker_id is None:
            reason = ask_launch(repo_root, run_id, action)
            positive = reason == CURRENT
        else:
            try:
                reason = ask_worker(repo_root, run_id, worker_id)
            except LaunchCommitError as error:
                raise LaunchScopeError(str(error)) from error
            positive = reason == LIVE
    except BaseException:
        _delete_row(row)
        raise
    if not positive:
        _delete_row(row)
        return REFUSED_EXIT, {"action_id": action, "started": False, "reason": reason}

    forwarder = _Forwarder()
    forwarder.install()
    try:
        return _run(argv, row, nonce, started_at, marker, forwarder)
    finally:
        forwarder.restore()


def _run(argv: Sequence[str], row: Path, nonce: str, started_at: str, marker: str,
         forwarder: _Forwarder) -> tuple[int, None]:
    try:
        child = subprocess.Popen(list(argv), start_new_session=True,
                                 env={**os.environ, MARKER_ENV: marker})
    except OSError as error:
        _delete_row(row)
        print(f"launch-scope: cannot run {argv[0]}: {error}", file=sys.stderr)
        return (127 if isinstance(error, FileNotFoundError) else 126), None

    try:
        forwarder.attach(child.pid)
        _write_row(row, nonce, child.pid, started_at, argv[0])
        os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)
        survivors = _clean_up(marker, child.pid)
    except BaseException as error:
        proven = _clean_up_after_failure(marker, child.pid)
        forwarder.detach()
        child.wait()
        if proven:
            _delete_row(row)
        if isinstance(error, OSError):
            raise LaunchScopeError(str(error)) from error
        raise
    forwarder.detach()
    rc = child.wait()
    if survivors:
        print("launch-scope: processes survived SIGKILL: "
              + " ".join(str(pid) for pid in sorted(survivors)), file=sys.stderr)
    else:
        _delete_row(row)
    return (rc if rc >= 0 else 128 - rc), None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="launch-scope", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    verbs = parser.add_subparsers(dest="verb", required=True)
    run = verbs.add_parser(
        "exec", help="run a command in the launch's scope",
        usage="%(prog)s --repo-root R --run-id I (--action-id A | --worker-id W) -- <argv>")
    run.add_argument("--repo-root", required=True, help="the ledger repository root")
    run.add_argument("--run-id", required=True, help="the lifecycle run id")
    identity = run.add_mutually_exclusive_group(required=True)
    identity.add_argument("--action-id", help="the launch's action id")
    identity.add_argument("--worker-id", help="a registered worker id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    separated = SEPARATOR in argv
    split = argv.index(SEPARATOR) if separated else len(argv)
    args = parser.parse_args(argv[:split])
    if not separated:
        parser.error(f"missing {SEPARATOR} before the command to run")
    try:
        status, refusal = exec_scoped(args.repo_root, args.run_id, argv[split + 1:],
                                      action_id=args.action_id, worker_id=args.worker_id)
    except (LaunchScopeError, LaunchCommitError, UnsupportedPlatform,
            ProcessTableError) as error:
        print(f"launch-scope: {error}", file=sys.stderr)
        return USAGE_EXIT
    if refusal is not None:
        print(canonical_line(refusal))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
