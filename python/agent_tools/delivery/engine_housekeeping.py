"""The engine run history: one line per run end, kept 180 days (#1519).

Layout, under `~/.agents/state/engine/` (mode 0700):

    history.jsonl         one compact sorted-key JSON line per run end, appended and fsynced
    .history.jsonl.lock   the exclusive flock every append and prune of the history holds

A line has exactly `format`, `run`, `project`, `issue`, `end`, `need`, `ended` and `steps`: `end` is
`done` or the name of the stop the run reached, `need` the stop's need (null for done), `ended` the
instant the line was written, in UTC, and `steps` the per-step summaries `engine_ledger.fold` derives.
A run that is continued and ends again appends a second line; no earlier line is ever rewritten, so a
run's last line is its complete one.

A line holds no environment value, no credential, no prompt and no reply: only names, counts, outcomes
and times from the ledger.

`prune_history` drops a line whose `ended` is more than `HISTORY_DAYS` days before `now` and keeps every
other line byte for byte, whatever it holds.

Run directories expire `RUN_KEEP_DAYS` days after their issue closes. `sweep_runs` runs when the engine
starts: it asks the tracker once per issue (an open issue never expires), skips an issue the tracker
cannot read, and deletes nothing at all when the tracker call fails. A run whose lock another process
holds, or whose issue has a delivery being created, is skipped and swept by a later start. A run is
swept only under the tracker it was created under: `run.json` carries `tracker` (`tracker_identity`),
and a run with another identity is kept, so re-pointing a project's tracker never lets another
repository's issue of the same number expire a run; a run with none (made before the member existed) is
swept only when the project id is the tracker's repository slug. The forge answer must come from the host
`GH_HOST` names (github.com by default) and the read goes through the binding's `cli`. A run is renamed
under an exclusive run lock, so a reader holding the lock keeps it. Before a finished run (done or
stopped) is renamed, its complete history line (all eight members) is appended if the history holds none
for it and the run ended within the history's 180 days, and a run whose line cannot be appended is kept. The tracker budget (`SWEEP_SECONDS`) starts after the run directories are listed and read. A run is
renamed to `.<run id>.expired` before it is removed, so a removal that fails is finished by the next
sweep. `.sweep-cursor.json` remembers the last issue asked per project so that a sweep cut short by its
time budget resumes after it.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Mapping
from urllib.parse import urlsplit

from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.delivery import engine_ledger
from agent_tools.system import forge_api

HISTORY_FORMAT = 1
HISTORY_MEMBERS = ("format", "run", "project", "issue", "end", "need", "ended", "steps")
HISTORY_DAYS = 180
RUN_KEEP_DAYS = 14
SWEEP_SECONDS = 60


class TrackerError(Exception):
    """The forge call failed."""


class IssueUnreadable(Exception):
    """The forge answered, but not with a readable issue of this repository."""


Tracker = Callable[[int], datetime | None]


def engine_root() -> Path:
    return Path(os.environ["HOME"]) / ".agents/state/engine"


def history_path() -> Path:
    return engine_root() / "history.jsonl"


def history_line(state: engine_ledger.RunState, ended: datetime) -> dict:
    """The history line of a run that is done or stopped; `ValueError` for any other run."""
    if state.done:
        end, need = "done", None
    elif state.stop is not None:
        end, need = state.stop["name"], state.stop["need"]
    else:
        raise ValueError("a run that is neither done nor stopped has no history line")
    return {"format": HISTORY_FORMAT, "run": state.run, "project": state.project,
            "issue": state.issue, "end": end, "need": need,
            "ended": ended.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "steps": [dict(step) for step in state.steps]}


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock = os.open(path.parent / f".{path.name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
    finally:
        os.close(lock)


def append_history(line: Mapping, path: Path | None = None) -> None:
    """Append `line` as one compact line, after cutting a torn tail; fsynced under the lock."""
    path = history_path() if path is None else Path(path)
    data = json.dumps(line, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    engine_ledger.make_root(path.parent)
    with _locked(path):
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            engine_ledger._cut_torn_tail(descriptor)
            view = memoryview(data)
            while view:
                view = view[os.write(descriptor, view):]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _load(line: bytes) -> object:
    """The JSON value of `line`, or None when it is not readable (a deeply nested one included)."""
    try:
        return json.loads(line.decode("utf-8"))
    except (ValueError, RecursionError):
        return None


def _expired(line: bytes, cutoff: datetime) -> bool:
    try:
        return parse_rfc3339_utc(_load(line)["ended"]) < cutoff  # type: ignore[index]
    except (ValueError, KeyError, TypeError):
        return False


def _recorded(run: str, path: Path) -> bool:
    """Whether the history holds a complete line (exactly the line members) for `run`."""
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return False
    return any(isinstance(loaded, dict) and set(loaded) == set(HISTORY_MEMBERS)
               and loaded["run"] == run for loaded in map(_load, data.split(b"\n")))


def prune_history(now: datetime, path: Path | None = None) -> int:
    """Drop the lines older than `HISTORY_DAYS` days and any torn tail; return how many lines went."""
    path = history_path() if path is None else Path(path)
    if not path.exists():
        return 0
    cutoff = now - timedelta(days=HISTORY_DAYS)
    with _locked(path):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return 0
        *whole, tail = data.split(b"\n")
        kept = [part for part in whole if not _expired(part, cutoff)]
        dropped = len(whole) - len(kept)
        if dropped == 0 and not tail:
            return 0
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            os.fchmod(handle, 0o600)
            payload = b"".join(part + b"\n" for part in kept)
            view = memoryview(payload)
            while view:
                view = view[os.write(handle, view):]
            os.fsync(handle)
            os.close(handle)
            handle = -1
            os.replace(temporary, path)
        except BaseException:
            if handle >= 0:
                os.close(handle)
            Path(temporary).unlink(missing_ok=True)
            raise
        engine_ledger._fsync_path(path.parent)
        return dropped


def forge_host() -> str:
    """The GitHub host the CLI targets: `GH_HOST`, else github.com."""
    return (os.environ.get("GH_HOST") or "github.com").casefold()


def forge_tracker(slug: str, cli: str = "gh", host: str = "github.com") -> Tracker:
    """A tracker reading issues of the GitHub repository `slug` on `host` through the CLI `cli`:
    the closed time, or None when open."""
    def closed_at(number: int) -> datetime | None:
        try:
            payload = forge_api.api_get(f"repos/{slug}/issues/{number}", allow=(404, 410), cli=cli)
        except forge_api.ForgeError as error:
            raise TrackerError(str(error)) from error
        if not isinstance(payload, dict):
            raise IssueUnreadable(f"#{number} has no readable payload")
        answered = payload.get("number")
        if isinstance(answered, bool) or not isinstance(answered, int) or answered != number:
            raise IssueUnreadable(f"#{number} answered as {answered!r}")
        if "pull_request" in payload:
            raise IssueUnreadable(f"#{number} is a pull request")
        url = payload.get("repository_url")
        try:
            served = (urlsplit(url).hostname or "").casefold() if isinstance(url, str) else ""
        except ValueError:
            served = ""
        if served not in (host, f"api.{host}"):
            raise IssueUnreadable(f"#{number} answered from host {served!r}, not {host}")
        home = url.split("/repos/", 1)[1] if isinstance(url, str) and "/repos/" in url else None
        if home is None or home.casefold() != slug.casefold():
            raise IssueUnreadable(f"#{number} answered from repository {home!r}, not {slug}")
        state = payload.get("state")
        if state == "open":
            return None
        if state != "closed":
            raise IssueUnreadable(f"#{number} has state {state!r}")
        try:
            return parse_rfc3339_utc(payload.get("closed_at"))
        except ValueError as error:
            raise IssueUnreadable(f"#{number} has no readable closed_at: {error}") from error
    return closed_at


def tracker_identity(binding: Mapping) -> str:
    """The identity a run records for the tracker its issue lives in: `github:<repo slug>`, with the
    host before the slug when `GH_HOST` names one other than github.com, or the kind."""
    kind, slug = binding.get("kind"), binding.get("repo_slug")
    if not isinstance(slug, str):
        return str(kind)
    host = forge_host()
    return f"{kind}:{slug.casefold()}" if host == "github.com" else f"{kind}:{host}/{slug.casefold()}"


def default_tracker(binding: Mapping) -> Tracker:
    """The tracker of a project's tracker binding; a kind other than github fails on its first read."""
    kind = binding["kind"]
    if kind == "github":
        return forge_tracker(binding["repo_slug"], binding["cli"], forge_host())

    def unsupported(number: int) -> datetime | None:
        raise TrackerError(f"tracker kind {kind} is not supported")
    return unsupported


def cursor_path() -> Path:
    return engine_root() / "sweep-cursor.json"


def _read_cursor(cursor: Path) -> dict:
    try:
        loaded = json.loads(Path(cursor).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _update_cursor(cursor: Path, project: str, issue: int) -> None:
    """Set `project` to `issue` in the cursor file, keeping the other projects, under its lock."""
    cursor = Path(cursor)
    engine_ledger.make_root(cursor.parent)
    with _locked(cursor):
        entries = _read_cursor(cursor)
        entries[project] = issue
        payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        handle, temporary = tempfile.mkstemp(dir=cursor.parent, prefix=f".{cursor.name}.")
        try:
            os.fchmod(handle, 0o600)
            view = memoryview(payload)
            while view:
                view = view[os.write(handle, view):]
            os.fsync(handle)
            os.close(handle)
            handle = -1
            os.replace(temporary, cursor)
        except BaseException:
            if handle >= 0:
                os.close(handle)
            Path(temporary).unlink(missing_ok=True)
            raise


def _line(error: BaseException) -> str:
    return f"{type(error).__name__}: {' '.join(str(error).split())}"


def _remove(path: Path) -> bool:
    try:
        shutil.rmtree(path)
    except OSError as error:
        sys.stderr.write(f"engine: housekeeping could not remove {path}: {_line(error)}\n")
        return False
    return True


def _candidates(root: Path, entries: list[Path], project: str, tracker_id: str,
                skip_run: str | None) -> dict[int, list[Path]]:
    """The runs of `project` the sweep may delete, by issue; every other run is kept.

    A run made before runs recorded `tracker` is deleted only when the project id names the tracker's
    own repository (`github:<project id>`): a project is that repository's, so the run is its too."""
    adopt = tracker_id == f"github:{project.casefold()}"
    found: dict[int, list[Path]] = {}
    for entry in entries:
        match = engine_ledger.RUN_ID_RE.match(entry.name)
        if match is None or entry.name == skip_run or not entry.is_dir():
            continue
        try:
            document = engine_ledger.read_run(entry)
        except engine_ledger.LedgerError:
            continue
        issue = document["issue"]
        if (document["project"] == project
                and document.get("tracker", tracker_id if adopt else None) == tracker_id
                and isinstance(issue, int)
                and not isinstance(issue, bool) and issue >= 1 and issue == int(match.group(1))):
            found.setdefault(issue, []).append(entry)
    return found


def _rotated(issues: list[int], after: object) -> list[int]:
    ordered = sorted(issues)
    if isinstance(after, int) and not isinstance(after, bool):
        return [n for n in ordered if n > after] + [n for n in ordered if n <= after]
    return ordered


def _record_end(run: Path, history: Path, now: datetime) -> None:
    """Append the history line of a finished `run` the history lacks; the caller holds its locks.

    A run that ended before the history's own cutoff is not recorded: the prune would drop it again."""
    state = engine_ledger.fold(engine_ledger.read_run(run),
                               engine_ledger.replay(run / "events.jsonl"), lambda pid, started: False)
    if not (state.done or state.stop is not None) or _recorded(state.run, history):
        return
    ends = ("run_done",) if state.done else ("stop_reached",)
    ended = [event["at"] for event in engine_ledger.replay(run / "events.jsonl")
             if event["event"] in ends][-1]
    when = parse_rfc3339_utc(ended)
    if when >= now - timedelta(days=HISTORY_DAYS):
        append_history(history_line(state, when), history)


def _delete(root: Path, issue: int, run: Path, history: Path, now: datetime,
            on_locked: Callable[[Path], None] | None) -> bool:
    """Rename `run` aside while holding its creation and run locks; False when it was kept.

    A lock another process holds, or a run that vanished, keeps it silently; any other failure
    keeps it and writes one stderr line naming the run."""
    descriptors = []
    try:
        try:
            creation = os.open(engine_ledger.creation_lock_path(root, issue),
                               os.O_RDWR | os.O_CREAT, 0o600)
            descriptors.append(creation)
            fcntl.flock(creation, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = os.open(run / "lock", os.O_RDWR | os.O_CREAT, 0o600)
            descriptors.append(held)
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(held, 0)  # no deliver holds it: the old holder document must not read as one
            if on_locked is not None:
                on_locked(run)
            try:
                _record_end(run, history, now)
            except Exception as error:
                sys.stderr.write(f"engine: housekeeping kept {run}, its history line was not "
                                 f"recorded: {_line(error)}\n")
                return False
            os.rename(run, root / f".{run.name}.expired")
        except (BlockingIOError, FileNotFoundError):
            return False
        except Exception as error:
            sys.stderr.write(f"engine: housekeeping kept {run}: {_line(error)}\n")
            return False
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    return True


def sweep_runs(root: Path, *, project: str, tracker: Tracker, tracker_id: str, now: datetime,
               cursor: Path, history: Path | None = None, skip_run: str | None = None,
               monotonic: Callable[[], float] = time.monotonic,
               on_locked: Callable[[Path], None] | None = None) -> list[str]:
    """Delete the runs of `project` whose issue closed more than `RUN_KEEP_DAYS` days before `now`.

    Returns the deleted run ids, sorted. All tracker reads come before any deletion."""
    root = Path(root)
    history = history_path() if history is None else Path(history)
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    candidates = _candidates(root, entries, project, tracker_id, skip_run)
    order = _rotated(list(candidates), _read_cursor(cursor).get(project))
    start = monotonic()  # the tracker budget: listing and reading the runs above is not charged to it
    expired: list[int] = []
    asked = None
    for issue in order:
        if monotonic() >= start + SWEEP_SECONDS:
            break
        try:
            closed = tracker(issue)
        except TrackerError:
            return []
        except IssueUnreadable:
            asked = issue
            continue
        asked = issue
        if closed is not None and now - closed > timedelta(days=RUN_KEEP_DAYS):
            expired.append(issue)
    if asked is not None:
        _update_cursor(cursor, project, asked)
    for entry in entries:
        match = engine_ledger.RUN_ID_RE.match(entry.name[1:].removesuffix(".expired"))
        if entry.name.startswith(".") and entry.name.endswith(".expired") \
                and match is not None and entry.is_dir():
            _remove(entry)
    deleted = []
    for issue in sorted(expired):
        for run in candidates[issue]:
            if _delete(root, issue, run, history, now, on_locked) and _remove(root / f".{run.name}.expired"):
                deleted.append(run.name)
    return sorted(deleted)


def housekeep(*, project: str, run: str, clock: Callable[[], datetime],
              tracker: Callable[[], Tracker], identity: str) -> None:
    """Prune the history and sweep expired runs; a failure is one stderr line, never an exception."""
    try:
        now = clock()
    except Exception as error:
        sys.stderr.write("engine: housekeeping skipped the history prune and the run sweep: "
                         f"{_line(error)}\n")
        return
    try:
        prune_history(now)
    except Exception as error:
        sys.stderr.write(f"engine: housekeeping skipped the history prune: {_line(error)}\n")
    try:
        sweep_runs(engine_ledger.runs_root(), project=project, tracker=tracker(),
                   tracker_id=identity, now=now, cursor=cursor_path(), skip_run=run)
    except Exception as error:
        sys.stderr.write(f"engine: housekeeping skipped the run sweep: {_line(error)}\n")
