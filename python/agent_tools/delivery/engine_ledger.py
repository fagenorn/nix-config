"""The engine run ledger: one run is a directory, written append-only (#1511).

Layout, under `~/.agents/state/engine/runs/<run id>/` (mode 0700):

    run.json            the run's identity: exactly `RUN_MEMBERS`, plus `tracker` (the identity of the
                        tracker its issue lives in) when the run was created with one
    procedure/          a byte copy of the entry procedure directory's `*.json`, `*.md`, `SHA256SUMS`
    events.jsonl        one compact JSON event per line, appended and fsynced
    lock  the deliver process's exclusive flock and its {"pid","started"}
    stop-request   a pending stop request for the lock holder it names (engine_stop)
    results/<step>.<visit>.json
                        a step visit's stored result
    sessions/<step>.<visit>.{system.md,prompt.md,json,resume.json,resume.prompt.md}
                        an agent step visit's launch files and raw result,
                        created with the first one stored

The run id is `<issue>-<UTC start as %Y%m%dT%H%M%SZ>-<four [a-z0-9]>`. It orders only to the second, so
`run.json` also carries `sequence`: one above the greatest `sequence` among the issue's earlier runs, the
order `find_runs` returns. The caller serialises the creation of an issue's runs. A run is assembled in
`<root>/.<run id>.tmp` and renamed into place, so a run directory is either complete or absent.

Every event has `event` (its type) and `at` (RFC3339 UTC); `EVENT_MEMBERS` lists, per type, exactly the
other members it carries. An agent step visit that hits a usage limit or an API error, or gives no valid
answer, is launched again in the same visit: `session_resuming` records each such launch (its `attempt`, 2 or
more) and `session_answered` the account the launcher answered for a launch whose process started.

Order rule: a result file is written to a writer-owned temporary file (fsynced), then linked into place,
which refuses a result that exists, before its `result_stored` event is appended; `append_event` refuses
that event while the file is absent. A crash between the two leaves a result with no event, never an
event naming no result. An append first cuts a write that was cut short back to the last newline, so a
torn tail never joins the next event; the cut and the write run under an exclusive `flock` on
`events.jsonl`.

The ledger holds no environment value and no credential: `run.json` carries only the names and values its
caller passes as `inputs`.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from agent_tools.canonical import (
    parse_rfc3339_utc,
    reject_duplicate_keys,
    reject_nonfinite_literal,
)
from agent_tools.delivery.procedure_check import (
    INPUT_RE, NAME_RE, NEEDS, ROLES, STAGES, _inside)

RUN_ID_RE = re.compile(r"^([1-9][0-9]*)-([0-9]{8}T[0-9]{6}Z)-([a-z0-9]{4})$")
TOKEN_RE = re.compile(r"^[a-z0-9]{4}$")
RUN_MEMBERS = ("host", "inputs", "issue", "platform_revision", "procedure", "project",
               "run", "sequence", "started")
OPTIONAL_RUN_MEMBERS = ("tracker",)
WAITS = ("usage-limit", "host-slot", "lock")
TOKEN_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
TOKEN_COUNTS = frozenset(("input", "cache_write", "cache_read", "output"))

# The members of each event type besides `event` and `at`.
EVENT_MEMBERS: Mapping[str, frozenset[str]] = {
    "step_entered": frozenset(("step", "visit", "stage")),
    "session_starting": frozenset(("step", "visit", "session", "role", "account")),
    "process_started": frozenset(("step", "visit", "pid", "started")),
    "session_resuming": frozenset(("step", "visit", "session", "attempt")),
    "session_answered": frozenset(("step", "visit", "session", "attempt", "account")),
    "result_stored": frozenset(("step", "visit", "result", "wall_seconds", "turns",
                                "tokens", "spend_usd")),
    "outcome_graded": frozenset(("step", "visit", "outcome")),
    "transition_taken": frozenset(("step", "visit", "outcome", "to")),
    "wait_started": frozenset(("wait", "until")),
    "wait_ended": frozenset(("wait",)),
    "stop_reached": frozenset(("step", "stop", "need")),
    "keep_alive_ran": frozenset(("step", "visit", "attempt", "verdict")),
    "run_continued": frozenset(),
    "run_done": frozenset(),
}


class LedgerError(Exception):
    """A run or an event the ledger refuses."""


def runs_root() -> Path:
    return Path(os.environ["HOME"]) / ".agents" / "state" / "engine" / "runs"


def _compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    if _is_int(value):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _is_name(value: object) -> bool:
    return isinstance(value, str) and value != ""


def make_run_id(issue: int, started: datetime, token: str) -> str:
    if not _is_int(issue) or issue < 1:
        raise LedgerError("issue must be an integer of at least 1")
    if not isinstance(started, datetime) or started.tzinfo is None \
            or started.utcoffset() is None:
        raise LedgerError("start time must be timezone-aware")
    if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
        raise LedgerError("token must be four characters of [a-z0-9]")
    return f"{issue}-{started.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{token}"


def _fsync_path(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_file(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def make_root(root: Path) -> None:
    """Create `root` and every missing ancestor, fsyncing the parent of each new directory."""
    missing = []
    probe = root
    while not probe.exists():
        missing.append(probe)
        probe = probe.parent
    for directory in reversed(missing):
        try:
            os.mkdir(directory)
        except FileExistsError:
            pass
        _fsync_path(directory)
        _fsync_path(directory.parent)


def _check_inputs(inputs: Mapping[str, str | int]) -> None:
    if not isinstance(inputs, Mapping):
        raise LedgerError("inputs must be a mapping")
    for key, value in inputs.items():
        if not isinstance(key, str) or not INPUT_RE.fullmatch(key):
            raise LedgerError(f"input name {key!r} is not a run input name")
        if not (isinstance(value, str) or _is_int(value)):
            raise LedgerError(f"input {key} must be a string or an integer")


def create_run(*, project: str, issue: int, procedure: str, procedures_dir: Path,
               platform_revision: str, host: str, inputs: Mapping[str, str | int],
               now: datetime, token: str | None = None, root: Path | None = None,
               tracker: str | None = None, before_publish: Callable[[Path], None] | None = None) -> Path:
    """Create the run directory and return its path; a `before_publish(staged)` raise leaves no run."""
    for label, value in (("project", project), ("platform_revision", platform_revision),
                         ("host", host)):
        if not _is_name(value):
            raise LedgerError(f"{label} must be a non-empty string")
    if not isinstance(procedure, str) or not NAME_RE.fullmatch(procedure):
        raise LedgerError("procedure is not a procedure name")
    procedures_dir = Path(procedures_dir)
    if _inside(procedures_dir, f"{procedure}.json") is None:
        raise LedgerError(f"no procedure file {procedure}.json in the procedure directory")
    _check_inputs(inputs)
    if token is None:
        token = "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(4))
    run_id = make_run_id(issue, now, token)
    started = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    root = runs_root() if root is None else Path(root)
    make_root(root)
    final = root / run_id
    if os.path.lexists(final):
        raise LedgerError(f"run {run_id} already exists")
    sequence = 1 + max((document["sequence"] for _, document in _issue_runs(root, issue)),
                       default=0)
    temporary = root / f".{run_id}.tmp"
    os.mkdir(temporary, 0o700)
    try:
        os.chmod(temporary, 0o700)
        document = {"host": host, "inputs": dict(inputs), "issue": issue,
                    "platform_revision": platform_revision, "procedure": procedure,
                    "project": project, "run": run_id, "sequence": sequence,
                    "started": started}
        if tracker is not None:
            document["tracker"] = tracker
        _write_file(temporary / "run.json", _compact(document).encode("utf-8"))
        copied = temporary / "procedure"
        os.mkdir(copied, 0o700)
        sources = sorted((entry for entry in procedures_dir.iterdir()
                          if entry.suffix in (".json", ".md")
                          and _inside(procedures_dir, entry.name) is not None),
                         key=lambda entry: entry.name)
        lines = []
        for source in sources:
            data = source.read_bytes()
            _write_file(copied / source.name, data)
            lines.append(f"{hashlib.sha256(data).hexdigest()}  {source.name}\n")
        _write_file(copied / "SHA256SUMS", "".join(lines).encode("utf-8"))
        _write_file(temporary / "events.jsonl", b"")
        os.mkdir(temporary / "results", 0o700)
        if before_publish is not None:
            before_publish(temporary)
        for directory in (copied, temporary / "results", temporary):
            _fsync_path(directory)
        os.rename(temporary, final)
        _fsync_path(root)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def _strict_load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=reject_duplicate_keys,
                          parse_constant=reject_nonfinite_literal)
    except (OSError, ValueError, RecursionError) as error:
        raise LedgerError(f"cannot read {path.name}: {error}") from error


def read_run(run_dir: Path) -> dict:
    document = _strict_load(Path(run_dir) / "run.json")
    if (not isinstance(document, dict) or not set(RUN_MEMBERS) <= set(document)
            or not set(document) <= set(RUN_MEMBERS + OPTIONAL_RUN_MEMBERS)):
        raise LedgerError("run.json does not have exactly the run members")
    if "tracker" in document and not (isinstance(document["tracker"], str) and document["tracker"]):
        raise LedgerError("run.json tracker is not a non-empty string")
    if not isinstance(document["project"], str):
        raise LedgerError("run.json project is not a string")
    if not _is_int(document["sequence"]) or document["sequence"] < 1:
        raise LedgerError("run.json sequence is not an integer of at least 1")
    if document["run"] != Path(run_dir).name:
        raise LedgerError("run.json run is not the name of its run directory")
    return document


def creation_lock_path(root: Path, issue: int) -> Path:
    return Path(root) / f".{issue}.deliver.lock"


def _issue_runs(root: Path, issue: int) -> list[tuple[Path, dict]]:
    """Every run directory of `issue` under `root` with its `run.json`; it writes nothing."""
    root = Path(root)
    if not root.is_dir():
        return []
    found = []
    for entry in root.iterdir():
        match = RUN_ID_RE.match(entry.name)
        if match is None or match.group(1) != str(issue) or not entry.is_dir():
            continue
        try:
            document = read_run(entry)
        except LedgerError:
            if not entry.exists():
                continue  # renamed away by a housekeeping sweep after the listing
            raise
        if document["issue"] == issue:
            found.append((entry, document))
    return found


def find_runs(root: Path, issue: int, project: str | None) -> list[Path]:
    """Every run directory of `issue` under `root`, oldest first (`sequence`, then name).

    With no `project`, runs of several projects are a `LedgerError`."""
    found = [(entry, document) for entry, document in _issue_runs(root, issue)
             if project is None or document["project"] == project]
    projects = sorted({document["project"] for _, document in found})
    if project is None and len(projects) > 1:
        raise LedgerError(f"runs of issue {issue} belong to several projects: "
                          + ", ".join(projects) + "; pass --project")
    found.sort(key=lambda pair: (pair[1]["sequence"], pair[0].name))
    return [entry for entry, _ in found]


def find_run(root: Path, issue: int, project: str | None) -> Path | None:
    """The newest run directory of `issue` under `root`, or None; it writes nothing."""
    runs = find_runs(root, issue, project)
    return runs[-1] if runs else None


def _instant(value: object, label: str) -> None:
    try:
        parse_rfc3339_utc(value)  # type: ignore[arg-type]
    except ValueError as error:
        raise LedgerError(f"{label} is not an RFC3339 instant") from error


def _check_member(event: Mapping[str, object], key: str) -> None:
    value = event[key]
    kind = event["event"]
    if key == "event":
        return
    if key in ("at", "started"):
        _instant(value, key)
    elif key == "until":
        if value is not None:
            _instant(value, key)
    elif key == "step":
        if not isinstance(value, str) or not NAME_RE.fullmatch(value):
            raise LedgerError("step is not a step id")
    elif key in ("visit", "attempt", "pid"):
        if not _is_int(value) or value < 1:  # type: ignore[operator]
            raise LedgerError(f"{key} must be an integer of at least 1")
    elif key == "turns":
        if not _is_int(value) or value < 0:  # type: ignore[operator]
            raise LedgerError("turns must be a non-negative integer")
    elif key in ("wall_seconds", "spend_usd"):
        if not _is_number(value) or value < 0:  # type: ignore[operator]
            raise LedgerError(f"{key} must be a finite non-negative number")
    elif key == "tokens":
        if not isinstance(value, dict) or set(value) != TOKEN_COUNTS \
                or not all(_is_int(count) and count >= 0 for count in value.values()):
            raise LedgerError("tokens must hold exactly the four non-negative counts")
    elif key == "stage":
        if value not in STAGES:
            raise LedgerError("stage is not a stage")
    elif key == "role":
        if value not in ROLES:
            raise LedgerError("role is not a role")
    elif key == "need":
        if value not in NEEDS:
            raise LedgerError("need is not a need")
    elif key == "wait":
        if value not in WAITS:
            raise LedgerError("wait is not a wait")
    elif key == "result":
        if value != f"results/{event['step']}.{event['visit']}.json":
            raise LedgerError("result must name results/<step>.<visit>.json")
    elif not _is_name(value):
        raise LedgerError(f"{key} of {kind} must be a non-empty string")


def validate_event(event: object) -> dict:
    """Check an event's shape and return it; `LedgerError` on any defect."""
    if not isinstance(event, Mapping) or not all(isinstance(key, str) for key in event):
        raise LedgerError("an event is an object")
    kind = event.get("event")
    if not isinstance(kind, str) or kind not in EVENT_MEMBERS:
        raise LedgerError("unknown event type")
    if set(event) != EVENT_MEMBERS[kind] | {"event", "at"}:
        raise LedgerError(f"{kind} does not have exactly its members")
    # `step` and `visit` are checked before `result`, which is derived from them.
    for key in sorted(event, key=lambda name: name == "result"):
        _check_member(event, key)
    return dict(event)


def _cut_torn_tail(descriptor: int) -> None:
    """Cut the file back to its last newline, dropping a write that was cut short."""
    end = os.fstat(descriptor).st_size
    if end == 0 or os.pread(descriptor, 1, end - 1) == b"\n":
        return
    keep = 0
    position = end
    while position > 0:
        start = max(0, position - 65536)
        chunk = os.pread(descriptor, position - start, start)
        found = chunk.rfind(b"\n")
        if found >= 0:
            keep = start + found + 1
            break
        position = start
    os.ftruncate(descriptor, keep)
    os.fsync(descriptor)


def _append_line(events_path: Path, line: bytes) -> None:
    try:
        descriptor = os.open(events_path, os.O_RDWR | os.O_APPEND)
    except FileNotFoundError as error:
        raise LedgerError(f"{events_path.name} is absent") from error
    try:
        # One writer at a time: the cut and the write are a unit, so a second
        # writer's stale cut offset can never erase a first writer's event.
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _cut_torn_tail(descriptor)
        view = memoryview(line)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def append_event(run_dir: Path, event: Mapping[str, object]) -> None:
    run_dir = Path(run_dir)
    checked = validate_event(event)
    if checked["event"] == "result_stored" and not (run_dir / str(checked["result"])).is_file():
        raise LedgerError("result_stored names a result file that is not stored")
    _append_line(run_dir / "events.jsonl", _compact(checked).encode("utf-8"))


def _publish(path: Path, data: bytes) -> None:
    """Publish `data` at `path` atomically, refusing a destination that exists."""
    token = "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(8))
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{token}.tmp")
    try:
        _write_file(temporary, data)
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise LedgerError(f"{path.name} is already stored") from error
    finally:
        temporary.unlink(missing_ok=True)
    _fsync_path(path.parent)


def _write_result(path: Path, document: object) -> None:
    """Publish `document` at `path` atomically, refusing a destination that exists."""
    _publish(path, _compact(document).encode("utf-8"))


def store_result(run_dir: Path, *, step: str, visit: int, result: object, at: str,
                 wall_seconds: float, turns: int, tokens: Mapping[str, int],
                 spend_usd: float) -> Path:
    """Write the step visit's result file, then append its `result_stored` event."""
    run_dir = Path(run_dir)
    relative = f"results/{step}.{visit}.json"
    event = validate_event({"event": "result_stored", "at": at, "step": step, "visit": visit,
                            "result": relative, "wall_seconds": wall_seconds, "turns": turns,
                            "tokens": dict(tokens), "spend_usd": spend_usd})
    path = run_dir / relative
    if os.path.lexists(path):
        raise LedgerError(f"{relative} is already stored")
    _write_result(path, result)
    append_event(run_dir, event)
    return path


SESSION_FILE_RE = re.compile(r"[a-z][a-z0-9-]*\.[1-9][0-9]*\.(json|system\.md|prompt\.md|resume\.json|resume\.prompt\.md)")


def store_session_file(run_dir: Path, name: str, data: bytes) -> Path:
    """Write `sessions/<name>` once, creating `sessions/` (mode 0700) with the first."""
    run_dir = Path(run_dir)
    if not isinstance(name, str) or not SESSION_FILE_RE.fullmatch(name):
        raise LedgerError(f"{name!r} is not a session file name")
    directory = run_dir / "sessions"
    try:
        os.mkdir(directory, 0o700)
    except FileExistsError:
        pass
    else:
        _fsync_path(directory)
        _fsync_path(run_dir)
    path = directory / name
    if os.path.lexists(path):
        raise LedgerError(f"sessions/{name} is already stored")
    _publish(path, data)
    return path


def replay(events_path: Path) -> list[dict]:
    """The validated events of an event file, in order.

    A last segment with no newline is a write cut short and is dropped whatever it holds. A
    kept line that is not strict JSON or not a valid event is a `LedgerError` naming its line.
    """
    events_path = Path(events_path)
    try:
        data = events_path.read_bytes()
    except OSError as error:
        raise LedgerError(f"cannot read {events_path.name}: {error}") from error
    events = []
    for number, part in enumerate(data.split(b"\n")[:-1], start=1):
        try:
            loaded = json.loads(part.decode("utf-8"),
                                object_pairs_hook=reject_duplicate_keys,
                                parse_constant=reject_nonfinite_literal)
            events.append(validate_event(loaded))
        except (ValueError, LedgerError) as error:
            raise LedgerError(f"{events_path.name} line {number}: {error}") from error
    return events


@dataclass(frozen=True)
class RunState:
    """What a run's recorded events say it is doing; the console reads it too."""

    run: str
    project: str
    issue: int
    stage: str | None
    step: str | None
    wait: dict | None
    stop: dict | None
    done: bool
    last_event: str | None
    process: dict | None
    alive: bool
    steps: tuple[dict, ...] = field(default=(), hash=False)

    def as_json(self) -> dict:
        return {"run": self.run, "project": self.project, "issue": self.issue,
                "stage": self.stage, "step": self.step, "wait": self.wait,
                "stop": self.stop, "done": self.done, "last_event": self.last_event,
                "process": self.process, "alive": self.alive}


def fold(run: Mapping[str, object], events: Sequence[Mapping[str, object]],
         alive: Callable[[int, str], bool]) -> RunState:
    """Derive a run's state from its events in one pass; no file, clock or process.

    `process` is the last recorded process whose step visit has no stored result, and `alive` is
    the probe's answer for it, whatever the stop or done state: reading those first is the caller's.
    `steps` holds one summary per (step, visit), in the order the visits were first named.
    """
    stage = step = last_event = None
    wait = stop = None
    open_processes: dict[tuple[str, int], dict] = {}
    done = False
    entries: dict[tuple[str, int], dict] = {}
    graded: set[tuple[str, int]] = set()
    current: tuple[str, int] | None = None
    open_waits: list[tuple[dict, str]] = []

    def close_waits(at: str, kind: str | None) -> None:
        """Close the first open wait of `kind`, or every open wait when `kind` is None."""
        for pair in list(open_waits):
            summary, started = pair
            if kind is None or summary["wait"] == kind:
                summary["seconds"] = (parse_rfc3339_utc(at)
                                      - parse_rfc3339_utc(started)).total_seconds()
                open_waits.remove(pair)
                if kind is not None:
                    return

    for event in events:
        kind = event["event"]
        last_event = event["at"]
        visit = (event["step"], event["visit"]) if "visit" in event else None
        if kind in ("step_entered", "transition_taken") and visit not in entries:
            entries[visit] = {"step": visit[0], "visit": visit[1], "outcome": None,
                              "wall_seconds": None, "waits": [], "tokens": None,
                              "spend_usd": None, "account": None}
            current = visit
        if kind == "step_entered":
            stage, step = event["stage"], event["step"]
        elif kind in ("session_starting", "session_answered") and visit in entries:
            entries[visit]["account"] = event["account"]  # the last launch's answer wins
        elif kind == "outcome_graded" and visit in entries:
            entries[visit]["outcome"] = event["outcome"]
            graded.add(visit)
        elif kind == "transition_taken" and visit not in graded:
            entries[visit]["outcome"] = event["outcome"]
        elif kind == "wait_started":
            wait = {"wait": event["wait"], "since": event["at"], "until": event["until"]}
            if current is not None:
                summary = {"wait": event["wait"], "seconds": None}
                entries[current]["waits"].append(summary)
                open_waits.append((summary, event["at"]))
        elif kind == "wait_ended":
            close_waits(event["at"], event["wait"])
            if wait is not None and wait["wait"] == event["wait"]:
                wait = None
        elif kind == "stop_reached":
            stop = {"name": event["stop"], "need": event["need"]}
        elif kind == "run_continued":
            wait = stop = None
            close_waits(event["at"], None)
        elif kind == "run_done":
            done = True
        elif kind == "process_started":
            key = (event["step"], event["visit"])
            open_processes.pop(key, None)
            open_processes[key] = {"pid": event["pid"], "started": event["started"],
                                   "step": event["step"], "visit": event["visit"]}
        elif kind == "result_stored":
            open_processes.pop((event["step"], event["visit"]), None)
            if visit in entries:
                entries[visit].update(wall_seconds=event["wall_seconds"],
                                      tokens=dict(event["tokens"]), spend_usd=event["spend_usd"])
    process = list(open_processes.values())[-1] if open_processes else None
    running = alive(process["pid"], process["started"]) if process is not None else False
    return RunState(run=run["run"], project=run["project"], issue=run["issue"],  # type: ignore[arg-type]
                    stage=stage, step=step, wait=wait, stop=stop, done=done,
                    last_event=last_event, process=process, alive=running,
                    steps=tuple(entries.values()))


def process_alive(pid: int, started: str) -> bool:
    """Whether `pid` names a live process (`started` is kept for a later check)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True
