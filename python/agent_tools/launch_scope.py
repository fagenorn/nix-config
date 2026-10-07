"""Run a lifecycle launch's commands in a scope, and reap what they leave (#276).

    launch-scope exec --repo-root R --run-id I (--action-id A | --worker-id W) -- <argv>
    launch-scope reap --repo-root R --run-id I (--action-id A | --sweep)
    launch-scope scratch --repo-root R --run-id I (--action-id A | --worker-id W)

`exec` writes a registry row under `<git common dir of R>/agent-launch/I/A/`,
asks `workflow-state check-launch` (or `check-worker` for a worker, whose action
is its ID without the `:w<n>` suffix) and, only on a strict positive reply,
runs `<argv>` in a new session with `AGENT_LAUNCH_SCOPE=S/I/A/<nonce>` added to its
environment, where `S` is the repository scope: 16 hex characters of the
SHA-256 of the registry's real path, so a launch of another repository that
shares the run and action ids never carries this repository's marker (D17). SIGINT, SIGTERM and SIGHUP are forwarded to the command's group.
When the command exits, every process carrying that exact marker and every
member of the command's group is terminated, and the row is deleted.

`exec` exit codes:
  <status>  the command's own exit status, or 128 plus the signal that killed it
  3         refused: nothing started; one JSON line {"action_id", "reason", "started": false}
  126, 127  the command cannot be run, or is not found, as a shell reports it
  2         a usage or helper error, with nothing on stdout

A process that survives SIGKILL keeps the row for `reap`; `exec` names it on
stderr and still exits with the command's status.

`reap --action-id A` reaps that one launch without asking the ledger. `reap
--sweep` asks `check-launch` about every launch under the run, each launch
directory and each launch a live process's marker names under this repository's
scope (an earlier reap can
have deleted the directory of an exec paused before its spawn), and reaps each
one that is not current; a failed or malformed check skips it. A
reap terminates every live process whose marker names the launch, plus every
recorded group that such a process proves (a pid carrying that row's exact
marker, in that group). It then deletes the files it proved, and the launch's
directory once empty, only when no row changed since its snapshot and no marked
process is live; otherwise it runs one more round, and then keeps the directory
(`processes_survived`). It prints one JSON line
{"reaped": [{"action_id", "signalled"}], "skipped": [{"action_id", "reason"}]}.

`reap` exit codes:
  0  nothing was skipped
  1  a launch was skipped: its check failed or was malformed, or a process
     survived SIGKILL or a row kept changing (`processes_survived`, and its
     directory is kept)
  2  a usage or helper error, with nothing on stdout

Residual: a process that leaves the command's session and also scrubs
`AGENT_LAUNCH_SCOPE` from its environment is outside the scope. So is, on
darwin, an Apple platform binary that left the session, because its
environment cannot be read.

`scratch` asks the same liveness question as `exec` first, and creates nothing
for a launch that is not live. It prints the launch's scratch root: one
directory per launch, shared with its workers, made with `tempfile.mkdtemp`
under `TMPDIR` and recorded as `{"path": <real path>}` in `scratch.json` in the
launch's registry directory. The record is published once, by an exclusive
link, so concurrent callers all print the winner's root and the losers remove
the directory they made. A repeat call prints the same path, recreating the
directory (mode 0700) at that path if it has gone. A record that is not a strict
`{"path"}` object naming an absolute real path whose basename is
`launch-scope-<name>`, or a root that exists but is not a real directory, is an
error and is left as it is. A failure before the record is published removes
the root it just made.

`scratch` exit codes:
  0  the root's real path, one line
  3  refused: one JSON line {"action_id", "created": false, "reason"}
  2  a usage or helper error, with nothing on stdout
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from agent_tools.agent_platform import write_atomically
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.launch_commit import LIVE, MALFORMED_REPLY, LaunchCommitError, ask_worker
from agent_tools.launch_processes import (
    MARKER_ENV, ProcessTableError, UnsupportedPlatform, process_table, protected_pids,
    read_marker, require_supported_platform, terminate)

REGISTRY_DIR = "agent-launch"
SAFE_SEGMENT = re.compile(r"[A-Za-z0-9._:-]+")
NONCE = re.compile(r"[0-9a-f]{32}")
ROW_KEYS = frozenset({"nonce", "pgid", "started_at", "argv0"})
CURRENT = "current"
CHECK_LAUNCH_FAILED = "check_launch_failed"
PROCESSES_SURVIVED = "processes_survived"
REFUSED_EXIT = 3
USAGE_EXIT = 2
SEPARATOR = "--"
SCRATCH_RECORD = "scratch.json"
SCRATCH_PREFIX = "launch-scope-"
SCRATCH_NAME = re.compile(r"launch-scope-[a-z0-9_]+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

_REPLY_KEYS = frozenset({"action_id", "current", "current_action_id", "reason"})
_FORWARDED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
_IGNORED_SIGNAL_ERRORS = (ProcessLookupError, PermissionError)


class LaunchScopeError(Exception):
    """A usage or helper error; main exits 2."""


def canonical_line(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def is_safe_segment(value: str) -> bool:
    return SAFE_SEGMENT.fullmatch(value) is not None and value not in (".", "..")


def safe_segment(value: str, label: str) -> str:
    """`value`, when it is one safe path segment (D10)."""
    if not is_safe_segment(value):
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


def repository_scope(registry: Path) -> str:
    """The marker's first segment: 16 hex of the SHA-256 of the registry's real path (D17)."""
    return hashlib.sha256(os.fsencode(os.path.realpath(registry))).hexdigest()[:16]


def launch_marker(scope: str, run_id: str, action_id: str, nonce: str) -> str:
    return f"{scope}/{run_id}/{action_id}/{nonce}"


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
        """Forward each signal not ignored here; an ignored one stays ignored in the child."""
        for signum in _FORWARDED:
            if signal.getsignal(signum) is signal.SIG_IGN:
                continue
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
    return terminate(marked, [pgid], is_marked=lambda pid: read_marker(pid) == marker)[1]


def _clean_up_after_failure(marker: str, pgid: int) -> bool:
    """Best-effort cleanup after an exception past the spawn; True when proven clean (D14)."""
    _signal_group(pgid, signal.SIGTERM)
    try:
        return not _clean_up(marker, pgid)
    except ProcessTableError:
        _signal_group(pgid, signal.SIGKILL)
        return False


def _identity_reason(repo_root: str, run_id: str, action: str,
                     worker_id: str | None) -> tuple[str, bool]:
    """The ledger's reason for the launch (or its worker) and whether it is live."""
    if worker_id is None:
        reason = ask_launch(repo_root, run_id, action)
        return reason, reason == CURRENT
    try:
        reason = ask_worker(repo_root, run_id, worker_id)
    except LaunchCommitError as error:
        raise LaunchScopeError(str(error)) from error
    return reason, reason == LIVE


def exec_scoped(repo_root: str, run_id: str, argv: Sequence[str], *,
                action_id: str | None = None,
                worker_id: str | None = None) -> tuple[int, dict | None]:
    """Run `argv` in the launch's scope: (exit status, None) or (3, refusal)."""
    require_supported_platform()
    action = action_id if worker_id is None else worker_action(worker_id)
    safe_segment(run_id, "run id")
    safe_segment(action, "action id")
    registry = registry_root(repo_root)
    directory = launch_directory(registry, run_id, action)
    if not argv:
        raise LaunchScopeError(f"no command after {SEPARATOR}")

    nonce = secrets.token_hex(16)
    row = directory / f"{nonce}.json"
    marker = launch_marker(repository_scope(registry), run_id, action, nonce)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_row(row, nonce, None, started_at, argv[0])
    forwarder = _Forwarder()
    try:
        reason, positive = _identity_reason(repo_root, run_id, action, worker_id)
        if positive:
            forwarder.install()
    except BaseException:
        forwarder.restore()
        _delete_row(row)
        raise
    if not positive:
        _delete_row(row)
        return REFUSED_EXIT, {"action_id": action, "started": False, "reason": reason}

    try:
        return _run(argv, row, nonce, started_at, marker, forwarder)
    finally:
        forwarder.restore()


def _run(argv: Sequence[str], row: Path, nonce: str, started_at: str, marker: str,
         forwarder: _Forwarder) -> tuple[int, None]:
    try:
        child = subprocess.Popen(list(argv), start_new_session=True,
                                 env={**os.environ, MARKER_ENV: marker})
    except BaseException as error:
        _delete_row(row)                 # nothing started: the pgid-null row goes
        if not isinstance(error, OSError):
            raise
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


def scratch_path(data: bytes) -> str | None:
    """The record's root path when `data` is a strict `{"path"}` object naming one (D4)."""
    try:
        value = json.loads(data, object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
    except (ValueError, RecursionError):
        return None
    if not isinstance(value, dict) or set(value) != {"path"}:
        return None
    path = value["path"]
    if (not isinstance(path, str) or _CONTROL.search(path) is not None
            or not os.path.isabs(path)
            or os.path.realpath(path) != path
            or SCRATCH_NAME.fullmatch(os.path.basename(path)) is None):
        return None
    return path


def _read_record(record: Path) -> str | None:
    """The root a record names; None when there is no record, an error when it is malformed."""
    try:
        data = record.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise LaunchScopeError(f"cannot read {record}: {error}") from error
    path = scratch_path(data)
    if path is None:
        raise LaunchScopeError(f"malformed scratch record {record}")
    return path


def _create_record(directory: Path) -> str:
    """Make the launch's root and publish its record once, by an exclusive link (D3, D11)."""
    record = directory / SCRATCH_RECORD
    try:
        directory.mkdir(parents=True, exist_ok=True)
        made = os.path.realpath(tempfile.mkdtemp(prefix=SCRATCH_PREFIX))
    except OSError as error:
        raise LaunchScopeError(f"cannot make the scratch root: {error}") from error
    temp = None
    try:
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".scratch.", suffix=".tmp",
                                             delete=False) as handle:
                temp = Path(handle.name)
                handle.write((canonical_line({"path": made}) + "\n").encode("utf-8"))
            os.link(temp, record)
        except FileExistsError:
            os.rmdir(made)               # the loser of the race: the winner's root stands
            winner = _read_record(record)
            if winner is None:
                raise LaunchScopeError(f"scratch record {record} vanished") from None
            return winner
        except BaseException as error:
            shutil.rmtree(made, ignore_errors=True)
            if isinstance(error, OSError):
                raise LaunchScopeError(f"cannot write {record}: {error}") from error
            raise
        return made
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def scratch(repo_root: str, run_id: str, *, action_id: str | None = None,
            worker_id: str | None = None) -> tuple[int, str | dict]:
    """The launch's scratch root, made on first use: (0, root) or (3, refusal)."""
    require_supported_platform()
    action = action_id if worker_id is None else worker_action(worker_id)
    safe_segment(run_id, "run id")
    safe_segment(action, "action id")
    directory = launch_directory(registry_root(repo_root), run_id, action)
    reason, positive = _identity_reason(repo_root, run_id, action, worker_id)
    if not positive:
        return REFUSED_EXIT, {"action_id": action, "created": False, "reason": reason}
    root = _read_record(directory / SCRATCH_RECORD)
    if root is None:
        root = _create_record(directory)
    if not os.path.lexists(root):
        try:
            os.mkdir(root, 0o700)
        except FileExistsError:
            pass                         # a concurrent caller recreated it
        except OSError as error:
            raise LaunchScopeError(f"cannot recreate scratch root {root}: {error}") from error
    if os.path.islink(root) or not os.path.isdir(root):
        raise LaunchScopeError(f"scratch root {root} is not a directory")
    return 0, root


def _parse_row(name: str, data: bytes) -> tuple[str, int | None] | None:
    """A row's (nonce, pgid), strictly loaded; None for anything malformed."""
    try:
        row = json.loads(data, object_pairs_hook=reject_duplicate_keys,
                         parse_constant=reject_nonfinite_literal)
    except ValueError:
        return None
    if not isinstance(row, dict) or set(row) != ROW_KEYS:
        return None
    nonce, pgid = row["nonce"], row["pgid"]
    if (not isinstance(nonce, str) or NONCE.fullmatch(nonce) is None
            or name != f"{nonce}.json"
            or not (pgid is None or (type(pgid) is int and pgid > 0))):
        return None
    return nonce, pgid


def _directory_files(directory: Path) -> dict[str, bytes]:
    """Every regular file in the launch directory, by name, with its bytes; none when missing."""
    files = {}
    try:
        with os.scandir(directory) as entries:
            names = [entry.name for entry in entries if entry.is_file(follow_symlinks=False)]
    except FileNotFoundError:
        return files
    except OSError as error:
        raise LaunchScopeError(f"cannot list {directory}: {error}") from error
    for name in names:
        try:
            files[name] = (directory / name).read_bytes()
        except FileNotFoundError:
            continue                     # deleted since the listing (an exec ended)
        except OSError as error:
            raise LaunchScopeError(f"cannot read {directory / name}: {error}") from error
    return files


def _launch_marked(launch: re.Pattern, table) -> dict[int, str]:
    """The live, non-zombie pids whose marker names the launch."""
    marked = {}
    for pid, proc in table.items():
        if proc.zombie:
            continue
        marker = read_marker(pid)
        if marker is not None and launch.fullmatch(marker):
            marked[pid] = marker
    return marked


def _remove_proved(directory: Path, proved: dict[str, bytes]) -> bool:
    """Remove each file still holding the bytes it was proved with, then the empty directory.

    A file is first renamed aside, so a row an exec rewrites meanwhile lands at
    its own name and is never the one deleted; a claimed file whose bytes
    changed is put back. False when the directory keeps anything (D16).
    """
    for name, data in proved.items():
        path = directory / name
        claimed = directory / f".{name}.reaping"
        try:
            os.rename(path, claimed)
        except FileNotFoundError:
            continue                     # deleted since the snapshot (an exec ended)
        except OSError as error:
            raise LaunchScopeError(f"cannot claim {path}: {error}") from error
        try:
            if claimed.read_bytes() == data:
                claimed.unlink()
            else:
                os.rename(claimed, path)  # rewritten after the snapshot: not ours to delete
        except OSError as error:
            raise LaunchScopeError(f"cannot remove {path}: {error}") from error
    try:
        directory.rmdir()
    except FileNotFoundError:
        pass
    except OSError as error:
        if error.errno != errno.ENOTEMPTY:
            raise LaunchScopeError(f"cannot remove {directory}: {error}") from error
        return False
    return True


REAP_ROUNDS = 2


def reap_launch(registry: Path, run_id: str, action_id: str) -> tuple[int, bool]:
    """Terminate what the launch left, proving before signalling: (signalled, survived).

    The directory goes only when a round ends with no survivor, with every file
    unchanged since that round's snapshot, and with no live process carrying the
    launch's marker. Otherwise one more round runs; after `REAP_ROUNDS` the
    directory is kept and the launch counts as survived (D16).
    """
    directory = launch_directory(registry, run_id, action_id)
    scope = repository_scope(registry)
    launch = re.compile(re.escape(f"{scope}/{run_id}/{action_id}/") + NONCE.pattern)

    def is_marked(pid: int) -> bool:
        marker = read_marker(pid)
        return marker is not None and launch.fullmatch(marker) is not None
    signalled = 0
    for _ in range(REAP_ROUNDS):
        snapshot = _directory_files(directory)
        rows = [row for row in (_parse_row(name, data) for name, data in sorted(snapshot.items())
                                if name.endswith(".json")) if row is not None]
        table = process_table()          # fresh, right before terminate: the pid-reuse window
        marked = _launch_marked(launch, table)
        proved = {pgid for nonce, pgid in rows if pgid is not None
                  and any(marker == launch_marker(scope, run_id, action_id, nonce)
                          and table[pid].pgid == pgid for pid, marker in marked.items())}
        reached, survivors = terminate(list(marked), proved, is_marked=is_marked)
        signalled += reached
        if survivors:
            return signalled, True
        if _directory_files(directory) != snapshot:
            continue                     # an exec registered or rewrote a row meanwhile
        after = process_table()
        protected = protected_pids(after)
        if any(pid not in protected for pid in _launch_marked(launch, after)):
            continue                     # a marked process started after the snapshot
        if _remove_proved(directory, snapshot):
            return signalled, False
    return signalled, True


def _launch_names(run_directory: Path) -> list[str]:
    """The safe-named child directories of `run_directory`, sorted; none when it is missing."""
    try:
        with os.scandir(run_directory) as entries:
            names = [entry.name for entry in entries
                     if entry.is_dir(follow_symlinks=False) and is_safe_segment(entry.name)]
    except FileNotFoundError:
        return []
    except OSError as error:
        raise LaunchScopeError(f"cannot list {run_directory}: {error}") from error
    return sorted(names)


def _marked_launch_names(scope: str, run_id: str) -> set[str]:
    """The safe action ids a live, non-zombie process's marker names under `scope` and `run_id`."""
    launch = re.compile(re.escape(f"{scope}/{run_id}/") + r"([^/]+)/" + NONCE.pattern)
    names = set()
    for pid, proc in process_table().items():
        if proc.zombie:
            continue
        marker = read_marker(pid)
        match = None if marker is None else launch.fullmatch(marker)
        if match is not None and is_safe_segment(match.group(1)):
            names.add(match.group(1))
    return names


def reap(repo_root: str, run_id: str, *, action_id: str | None = None,
         sweep: bool = False) -> tuple[int, dict]:
    """Reap one launch, or sweep the run's non-current launches: (exit status, report)."""
    require_supported_platform()
    if (action_id is not None) == sweep:
        raise LaunchScopeError("reap takes exactly one of --action-id and --sweep")
    safe_segment(run_id, "run id")
    if action_id is not None:
        safe_segment(action_id, "action id")
    registry = registry_root(repo_root)
    reaped, skipped = [], []
    if action_id is not None:
        launches = [action_id]
    else:
        launches = []
        names = (set(_launch_names(registry / run_id))
                 | _marked_launch_names(repository_scope(registry), run_id))
        for name in sorted(names):
            reason = ask_launch(repo_root, run_id, name)
            if reason in (CHECK_LAUNCH_FAILED, MALFORMED_REPLY):
                skipped.append({"action_id": name, "reason": reason})
            elif reason != CURRENT:
                launches.append(name)
    for name in launches:
        signalled, survived = reap_launch(registry, run_id, name)
        if survived:
            skipped.append({"action_id": name, "reason": PROCESSES_SURVIVED})
        else:
            reaped.append({"action_id": name, "signalled": signalled})
    report = {"reaped": sorted(reaped, key=lambda item: item["action_id"]),
              "skipped": sorted(skipped, key=lambda item: item["action_id"])}
    return (0 if not skipped else 1), report


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
    made = verbs.add_parser(
        "scratch", help="print the launch's scratch root, creating it on first use",
        usage="%(prog)s --repo-root R --run-id I (--action-id A | --worker-id W)")
    made.add_argument("--repo-root", required=True, help="the ledger repository root")
    made.add_argument("--run-id", required=True, help="the lifecycle run id")
    owner = made.add_mutually_exclusive_group(required=True)
    owner.add_argument("--action-id", help="the launch's action id")
    owner.add_argument("--worker-id", help="a registered worker id")
    sweep = verbs.add_parser(
        "reap", help="terminate what a launch left behind, or sweep non-current launches",
        usage="%(prog)s --repo-root R --run-id I (--action-id A | --sweep)")
    sweep.add_argument("--repo-root", required=True, help="the ledger repository root")
    sweep.add_argument("--run-id", required=True, help="the lifecycle run id")
    selector = sweep.add_mutually_exclusive_group(required=True)
    selector.add_argument("--action-id", help="reap this launch, without asking the ledger")
    selector.add_argument("--sweep", action="store_true",
                          help="reap every launch of the run that is not current")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    separated = SEPARATOR in argv
    split = argv.index(SEPARATOR) if separated else len(argv)
    args = parser.parse_args(argv[:split])
    if args.verb in ("reap", "scratch") and separated:
        parser.error(f"{args.verb} takes no {SEPARATOR}")
    if args.verb == "exec" and not separated:
        parser.error(f"missing {SEPARATOR} before the command to run")
    try:
        if args.verb == "reap":
            status, report = reap(args.repo_root, args.run_id, action_id=args.action_id,
                                  sweep=args.sweep)
        elif args.verb == "scratch":
            status, report = scratch(args.repo_root, args.run_id, action_id=args.action_id,
                                     worker_id=args.worker_id)
            if status == 0:
                print(report)
                return 0
        else:
            status, report = exec_scoped(args.repo_root, args.run_id, argv[split + 1:],
                                         action_id=args.action_id, worker_id=args.worker_id)
    except (LaunchScopeError, LaunchCommitError, UnsupportedPlatform,
            ProcessTableError) as error:
        print(f"launch-scope: {error}", file=sys.stderr)
        return USAGE_EXIT
    if report is not None:
        print(canonical_line(report))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
