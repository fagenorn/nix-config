"""The readings behind forge-claim's early takeover: who the caller is, whether a claim's holding session provably no longer runs on this host, and what the claimed worktree holds.

It only reads: this host's Claude Code session registry (the default config's `sessions` directory and each account profile's, under the accounts root the environment names and under the default root `~/.claude-accounts`), `/proc` through the console's strict process check (`agent_tools.console.sessions.process_matches`), and three read-only git commands. A session reads `gone` only when the registry was read whole without an error (every entry a readable regular file, every record well formed), the caller's own session has a running record (so the registry is the one the caller's sessions register in), and both the process its claim records (`pid`, `pstart`: the holder's own process at acquire or renew) and each record naming the session are conclusively dead: the strict check finds no match and either the process is absent or a canonical start time differs from the recorded one. The recorded process, not the missing record, is the proof, because a running session rewrites its record in place when its id changes (`/clear`, a resume). Every other reading is `running` or `unreadable`, and each keeps the day's wait and the owner's tick. Nothing here resets, cleans, stashes or discards a worktree.
"""
import json
import os
import re
import socket
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.claims.forge_markers import Marker
from agent_tools.console import sessions
from agent_tools.system import github_remote

SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
SPRINT_ENV = "CONSOLE_SPRINT_ID"
IDENTITY_KEYS = ("session", "sprint")
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SPRINT = re.compile(r"[0-9a-f]{16}")
START = re.compile(r"0|[1-9][0-9]*")
PID = re.compile(r"[1-9][0-9]*")
PROCESS_KEYS = ("pid", "pstart")
GONE, RUNNING, UNREADABLE = "gone", "running", "unreadable"
PROC = Path("/proc")
MACHINE_ID = Path("/etc/machine-id")
GIT_TIMEOUT = 30
# The variables that select another repository than the one git is pointed at (a copy of issue_setup's list).
REPOSITORY_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                  "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE",
                  "GIT_PREFIX", "GIT_IMPLICIT_WORK_TREE")


def _profile_sessions(profiles: Path) -> list[Path]:
    """Each profile's `sessions` path under `profiles`; an unreadable `profiles` raises `OSError`."""
    try:
        with os.scandir(profiles) as entries:
            names = sorted(entry.name for entry in entries)
    except FileNotFoundError:
        return []
    found = []
    for name in names:
        path = profiles / name / "sessions"
        try:
            os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            continue
        found.append(path)
    return found


def registry_dirs() -> list[Path]:
    """Every directory a session of this host registers in; raises `OSError` when a profile tree cannot be read."""
    home = Path.home()
    default = home / ".claude-accounts"
    named = Path(os.environ["CLAUDE_ACCOUNTS_DIR"]) if os.environ.get("CLAUDE_ACCOUNTS_DIR") else default
    # What service.default_session_dirs lists plus the default root's profiles, raising where Path.glob
    # would hide an unreadable profile; a test pins the two together.
    dirs = [home / ".claude" / "sessions", *_profile_sessions(named / "profiles")]
    if named != default:
        dirs.extend(path for path in _profile_sessions(default / "profiles") if path not in dirs)
    return dirs


def _json_files(directory: Path) -> list[Path]:
    """The `*.json` files of `directory`; a missing directory holds none, an unreadable one raises."""
    try:
        with os.scandir(directory) as entries:
            names = sorted(entry.name for entry in entries
                           if entry.name.endswith(".json") and not entry.name.startswith("."))
    except FileNotFoundError:
        return []
    return [directory / name for name in names]


def this_host() -> str:
    return socket.gethostname().split(".", 1)[0]


def identity_fields(environ: Mapping[str, str]) -> dict[str, str]:
    """The caller's session and sprint ids, each only when it fits its pattern."""
    result: dict[str, str] = {}
    session, sprint = environ.get(SESSION_ENV), environ.get(SPRINT_ENV)
    if isinstance(session, str) and SESSION.fullmatch(session):
        result["session"] = session
    if isinstance(sprint, str) and SPRINT.fullmatch(sprint):
        result["sprint"] = sprint
    return result


def _well_formed(document: object) -> bool:
    if not isinstance(document, dict):
        return False
    session_id, cwd, pid = document.get("sessionId"), document.get("cwd"), document.get("pid")
    return (isinstance(session_id, str) and bool(session_id)
            and isinstance(cwd, str) and bool(cwd) and "\0" not in cwd
            and isinstance(pid, int) and not isinstance(pid, bool) and pid > 0)


def _record_reading(record: dict, procfs: bool, own: str | None) -> str:
    """One record's reading; raises `OSError` for a failed read."""
    pid, raw_start, domain = record["pid"], record.get("procStart"), record.get("pidDomain")
    start = (str(raw_start) if isinstance(raw_start, int) and not isinstance(raw_start, bool)
             else raw_start if isinstance(raw_start, str) else None)
    domain = domain if isinstance(domain, str) else None
    if not procfs:
        if sessions.process_matches(pid, None, None, proc=PROC, machine_id=MACHINE_ID, strict=True):
            return RUNNING
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return GONE
        except PermissionError:
            return RUNNING
        return RUNNING
    if start is None or START.fullmatch(start) is None or domain != own:
        return UNREADABLE
    if sessions.process_matches(pid, start, domain, proc=PROC, machine_id=MACHINE_ID, strict=True):
        return RUNNING
    try:
        line = (PROC / str(pid) / "stat").read_bytes()
    except (FileNotFoundError, ProcessLookupError):
        return GONE
    fields = line.rsplit(b")", 1)[1].split() if b")" in line else []
    if len(fields) < 20 or re.fullmatch(rb"[0-9]+", fields[19]) is None:
        return UNREADABLE
    return GONE if int(fields[19]) != int(start) else UNREADABLE


def _read_record(path: Path) -> object | None:
    """The record at `path`; None for a name that vanished, `OSError` for anything but a readable regular file."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise OSError(f"not a regular file: {path}")
        return json.loads(handle.read(), object_pairs_hook=reject_duplicate_keys,
                          parse_constant=reject_nonfinite_literal)


def _scan(session_id: str, caller: str) -> tuple[list[dict], list[dict]]:
    """The well formed records naming `session_id` and `caller`; raises when any record cannot be read whole."""
    held, own = [], []
    for directory in registry_dirs():
        for path in _json_files(directory):
            document = _read_record(path)
            if document is None:
                continue
            if not _well_formed(document):
                raise ValueError(f"malformed record: {path}")
            if document["sessionId"] == session_id:
                held.append(document)
            if document["sessionId"] == caller:
                own.append(document)
    return held, own


def _procfs() -> tuple[bool, str | None]:
    procfs = (PROC / "self" / "stat").exists()
    return procfs, (sessions.own_pid_domain(PROC, MACHINE_ID, strict=True) if procfs else None)


def session_reading(session_id: str, caller: str, pid: int, start: str | None) -> str:
    """`GONE`, `RUNNING` or `UNREADABLE` for `session_id`, read by `caller`; never raises. The holder is the
    process `pid` (start time `start`) its claim records plus every record naming `session_id`, because a
    running session rewrites its record when its id changes and a missing record proves nothing."""
    try:
        held, own = _scan(session_id, caller)
        procfs, own_domain = _procfs()
        if RUNNING not in [_record_reading(record, procfs, own_domain) for record in own]:
            return UNREADABLE
        recorded = {"pid": pid, "procStart": start, "pidDomain": own_domain}
        readings = [_record_reading(record, procfs, own_domain) for record in [*held, recorded]]
        if RUNNING in readings:
            return RUNNING
        return UNREADABLE if UNREADABLE in readings else GONE
    except (OSError, ValueError, OverflowError, RecursionError):
        return UNREADABLE


def process_fields(environ: Mapping[str, str]) -> dict[str, str]:
    """The claim fields naming the caller's own running process (`pid`, and `pstart` when it has a canonical
    start time), read from the registry record of its session; empty when it cannot be named exactly."""
    session = identity_fields(environ).get("session")
    if session is None:
        return {}
    try:
        _, own = _scan(session, session)
        procfs, own_domain = _procfs()
        running = [record for record in own if _record_reading(record, procfs, own_domain) == RUNNING]
    except (OSError, ValueError, OverflowError, RecursionError):
        return {}
    if len(running) != 1:
        return {}
    start = running[0].get("procStart")
    start = str(start) if isinstance(start, int) and not isinstance(start, bool) else start
    fields = {"pid": str(running[0]["pid"])}
    if isinstance(start, str) and START.fullmatch(start):
        fields["pstart"] = start
    return fields


def qualifies(claim: Marker, environ: Mapping[str, str]) -> bool:
    """Whether the caller may take `claim` over now: same host and sprint, another session, holder gone."""
    session, sprint = claim.fields.get("session"), claim.fields.get("sprint")
    if session is None or SESSION.fullmatch(session) is None:
        return False
    if sprint is None or SPRINT.fullmatch(sprint) is None:
        return False
    pid, start = claim.fields.get("pid"), claim.fields.get("pstart")
    if pid is None or PID.fullmatch(pid) is None or (start is not None and START.fullmatch(start) is None):
        return False
    identity = identity_fields(environ)
    if not all(key in identity for key in IDENTITY_KEYS):
        return False
    if identity["sprint"] != sprint or identity["session"] == session:
        return False
    if (claim.fields.get("holder") or "").split("/", 1)[0] != this_host():
        return False
    return session_reading(session, identity["session"], int(pid), start) == GONE


def _git(*argv: bytes | str) -> bytes | None:
    """Stdout of a read-only git command, or None when it fails; no repository selector reaches it."""
    env = {key: value for key, value in os.environ.items() if key not in REPOSITORY_ENV}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        done = subprocess.run(["git", *argv], capture_output=True, timeout=GIT_TIMEOUT, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _worktree_of(listing: bytes, branch: str) -> bytes | None:
    wanted = b"branch refs/heads/" + os.fsencode(branch)
    record: list[bytes] = []
    for field in listing.split(b"\0") + [b""]:
        if field:
            record.append(field)
            continue
        if wanted in record and not any(f == b"prunable" or f.startswith(b"prunable ") for f in record):
            return next((f[len(b"worktree "):] for f in record if f.startswith(b"worktree ")), None)
        record = []
    return None


def _status_paths(status: bytes) -> list[str] | None:
    paths: list[str] = []
    fields = iter(status.split(b"\0"))
    for field in fields:
        if not field:
            continue
        if len(field) < 4 or field[2:3] != b" ":
            return None
        paths.append(os.fsdecode(field[3:]))
        if field[0:1] in (b"R", b"C") or field[1:2] in (b"R", b"C"):
            next(fields, None)
    return paths


def worktree_report(slug: str, branch: str | None) -> tuple[str | None, list[str] | None]:
    """The path of `branch`'s worktree in the repository `slug` and its changed paths; None for what cannot be read."""
    if branch is None:
        return None, None
    origin = _git("remote", "get-url", "origin")
    try:
        found = github_remote.github_slug(origin.decode("utf-8")) if origin is not None else None
    except UnicodeDecodeError:
        found = None
    if found is None or found.casefold() != slug.casefold():
        return None, None
    listing = _git("worktree", "list", "--porcelain", "-z")
    worktree = _worktree_of(listing, branch) if listing is not None else None
    if worktree is None:
        return None, None
    status = _git("-C", worktree, "status", "--porcelain", "-z", "--untracked-files=all")
    return os.fsdecode(worktree), (_status_paths(status) if status is not None else None)
