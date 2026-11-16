"""The console's spend reader (#1134): token spend read from the Claude Code transcripts, incrementally.

This module is the reader part of the spend feature: the tree read, the key, the dedup, the window,
the phase table and the sources. Nothing here reads a clock; the window start `since` is a
`YYYY-MM-DD` UTC date the caller passes in.

The tree, under every `projects` directory (`<config>/projects`):

- `<slug>/<sid>.jsonl` is a session's own transcript, and `<slug>/<sid>/subagents/agent-<id>.jsonl`
  a subagent transcript of that session outside any workflow: both are the session's spend (source
  `SESSION`, no run, no agent).
- `<slug>/<sid>/subagents/workflows/<run>/` holds `journal.jsonl` and one `agent-<id>.jsonl` per
  workflow agent (source `AGENT`, run key `(<sid>, <run>)`, agent id from the file name). The
  journal is read first, so an agent's label is known before its transcript is.
- Two `projects` paths with one `os.path.realpath` are walked once; the first is kept.

Incremental: every file goes through one `deliveries.JournalReader`, so a second `read` opens only
a file whose size moved and reads only its new bytes. A file whose modification date (UTC) is before
`since` is not opened and its cursor is forgotten. A file the reader finds absent, or that this read
did not list, loses its cursor; but a directory whose listing fails with an `OSError` other than
`FileNotFoundError` or `NotADirectoryError` confirms nothing, so every cursor known under it is
kept and only bytes appended since are read once it lists again. `read` never raises for a missing
or unreadable directory or file.

The key: `Key(day, session, run, agent, source)`, `day` the UTC date of the message `timestamp`,
`session` the line's `sessionId` (None when absent or empty). `totals` sums `Tokens` per key.

- A line with `type == "assistant"` and a `message` that holds a str `id`, a usage `priced` accepts
  and a parsable str `timestamp` is counted when its day is `>= since` and its id was not seen: one
  message id is one count across every file and every read (the transcript writes one line per
  content block of a message, all with the same usage). Seen ids and totals of days before `since`
  are dropped at each `read`.
- `priced(model, usage)` is the `Tokens` of one usage object, dollars from
  `hosts.model_pricing.usage_cost`; `approximate` is true when the model is not a known price row.
  A usage object with a negative, non-integer or boolean count is not priced (None).
- A `type` of `agent-name` (`agentName`) or `custom-title` (`customTitle`) names its `sessionId`
  (latest wins); the first str `cwd` seen for a session sets its repository through `repo_of`,
  called once per session, ever.
- The ping log (`ping_log`, the keepalive proxy's log): each `event == "ping"` line with a parsable
  `ts`, a str `conversation` and a priced `usage` is counted once per `(ts, conversation)` under
  `Key(day, None, None, None, PING)`.

Journals: a `started` record with str `agentId`, `label` and `phase` maps the agent to its label
(`Snapshot.journals[run][agentId]`); a journal that was read creates its run's entry, possibly
empty. A phase that does not begin with `CHILD_PHASE_PREFIX` is top-level, and the run's program is
`run_program` of its top-level phases: `BATCH` when any is `Intake`, `Deliver` or `Land`, else
`STANDARD` when any is `Plan` or `Tasks`, else `OTHER`.

The phase table: `phase_of(label)` reads a label (without a trailing `RERUN_SUFFIX`) through the
`PHASE_LABELS` rows, one `(phase, regex)` per row matched with `re.fullmatch`, in order, first match
wins; a label no row matches is `OTHER`. The rows follow the cost measurement's role mapping, so
they are deliberately not `deliveries.OWNER_LABELS`.

The view: `spend_view(snapshot, today, project_of, profiles)` is the wire object
`{"approximate": <bool>, "days": [<day>, ...]}`, `WINDOW_DAYS` days, `today` and the days before it
(UTC), oldest first. A day is `{"day", "total", <dimension>: {<key>: <tokens>}}` for each of
`DIMENSIONS`, every `<tokens>` a `Tokens.wire()`; a day with nothing has a zero `total` and empty
maps, and a key dated outside the days is ignored. Each message has one key in `session`, `project`,
`account` and `aspect`, so the sums over each equal `total`. `approximate` is true when any message
counted is, per day in `total` and for the view. The keys, per message key:

- `session`: the key's session, else `UNATTRIBUTED`.
- `project`: `project_of(repo)` of the session's repository (`Snapshot.repos`), `UNATTRIBUTED` when
  the session, its repository or its project is unknown.
- `account`: `profiles[session]` (the profile the session was seen under), else `UNATTRIBUTED`.
- `sprint`: the sprint id when the session's name fully matches `MANAGER_SESSION_NAME`, `UNATTRIBUTED`
  when the session is unknown, and not counted for any other session.
- `run` and `phase` (source `AGENT` only): the run id when the run has a journal, and the phase of
  the agent's journal label; `UNATTRIBUTED` when the run or the agent has no journal record.
- `aspect`: `KEEPALIVE` for a ping; `DELIVERIES` for a workflow agent; for a session's own and
  subagent transcripts `MANAGERS` when the session is a sprint's, `OUTSIDE` otherwise, and
  `UNATTRIBUTED` when the session is unknown.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from stat import S_ISREG
from typing import BinaryIO, NamedTuple

from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.console import deliveries, sessions
from agent_tools.console.deliveries import (
    CHILD_PHASE_PREFIX,
    JOURNAL_NAME,
    RERUN_SUFFIX,
    Chunk,
    Unreadable,
)
from agent_tools.console.sprints import MANAGER_SESSION_NAME
from agent_tools.hosts import model_pricing

UNATTRIBUTED = "unattributed"
OTHER = "other"
WINDOW_DAYS = 30
PHASES = ("setup", "plan", "plan review", "plan revise", "implement", "task review",
          "final review", "fix wave", "verify", "land", "close-out")

SESSION = "session"
AGENT = "agent"
PING = "ping"

MANAGERS = "managers"
DELIVERIES = "deliveries"
OUTSIDE = "outside_sprint"
KEEPALIVE = "keepalive"
DIMENSIONS = ("session", "project", "sprint", "run", "phase", "account", "aspect")

BATCH = "deliver-batch"
STANDARD = "deliver-standard"

PHASE_LABELS: tuple[tuple[str, str], ...] = (
    ("setup", r"setup|acquire|acquire-\d+|worktree|facts-\d+|settle-\d+|readopt-\d+"
              r"|readopt-push-\d+|owner-answer|lane-\d+|release-\d+|train-sweep-\d+"
              r"|ws-check-\d+|renew-plan|renew-tasks|renew-amend|amend"),
    ("plan", r"plan"),
    ("plan review", r"plan-review|plan-codex|plan-rules-review"),
    ("plan revise", r"plan-revise|plan-rules-revise|plan-task-revise|plan-branch-revise"),
    ("implement", r"impl-\d+|direct-impl"),
    ("task review", r"review-\d+|rereview-\d+(?:-\d+)*|fix-\d+(?:-\d+)*|direct-review"
                    r"|direct-review-full|direct-codex|direct-rereview|direct-fix|fix-ci"
                    r"|fix-ci-review"),
    ("final review", r"final-\d+|final-codex|final-integration|renew-final-review|diff-size"),
    ("fix wave", r"fix-wave|fix-wave-\d+|fix-wave-review|fix-wave-review-\d+"),
    ("verify", r"verify|verify-\d+|verify-rerun-\d+|verify-fix-\d+|verify-fix-review-\d+"),
    ("close-out", r"close-out|close-out-\d+|hold|land-unlock(?:-\d+)*"),
    ("land", r"pr|merge|checks-\d+|land-[a-z]+(?:-[a-z]+)*-\d+(?:-\d+)*|sync-\d+"
             r"|sync-resolve-\d+|sync-review-\d+|fix-sync-\d+|fix-sync-review-\d+"
             r"|train-(?:pr|checks|merge|ready|build|flip)-\d+(?:-\d+)*"),
)
_PHASE_PATTERNS = tuple((phase, re.compile(pattern)) for phase, pattern in PHASE_LABELS)

_TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
                 "cache_creation_input_tokens")
_SPLIT_FIELDS = ("ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens")
_ABSENT = (FileNotFoundError, NotADirectoryError)
_BATCH_PHASES = frozenset({"Intake", "Deliver", "Land"})
_STANDARD_PHASES = frozenset({"Plan", "Tasks"})


@dataclass(frozen=True)
class Tokens:
    """Token counts and the dollars they cost; `approximate` when any price was a family guess."""

    input: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0
    dollars: float = 0.0
    approximate: bool = False

    def __add__(self, other: Tokens) -> Tokens:
        return Tokens(self.input + other.input, self.cache_write + other.cache_write,
                      self.cache_read + other.cache_read, self.output + other.output,
                      self.dollars + other.dollars, self.approximate or other.approximate)

    def wire(self) -> dict:
        return {"input": self.input, "cache_write": self.cache_write,
                "cache_read": self.cache_read, "output": self.output,
                "dollars": round(self.dollars, 4), "approximate": self.approximate}


def _count(value: object) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool)
                             and value >= 0)


def priced(model: str | None, usage: object) -> Tokens | None:
    """The `Tokens` of one usage object, or None when a count is not a non-negative integer."""
    if not isinstance(usage, dict):
        return None
    split = usage.get("cache_creation")
    if not all(_count(usage.get(field)) for field in _TOKEN_FIELDS):
        return None
    if split is not None and not (isinstance(split, dict)
                                  and all(_count(split.get(field)) for field in _SPLIT_FIELDS)):
        return None
    dollars, approximate = model_pricing.usage_cost(model if isinstance(model, str) else None,
                                                    usage)
    return Tokens(usage.get("input_tokens") or 0, usage.get("cache_creation_input_tokens") or 0,
                  usage.get("cache_read_input_tokens") or 0, usage.get("output_tokens") or 0,
                  dollars, approximate)


def phase_of(label: str) -> str:
    """The phase a workflow agent label belongs to; `OTHER` when no row matches."""
    name = label.removesuffix(RERUN_SUFFIX)
    for phase, pattern in _PHASE_PATTERNS:
        if pattern.fullmatch(name):
            return phase
    return OTHER


def run_program(phases: Iterable[str]) -> str:
    """The program of a run from its top-level phase names."""
    names = set(phases)
    if names & _BATCH_PHASES:
        return BATCH
    if names & _STANDARD_PHASES:
        return STANDARD
    return OTHER


class Key(NamedTuple):
    day: str
    session: str | None
    run: tuple[str, str] | None
    agent: str | None
    source: str


@dataclass(frozen=True)
class Snapshot:
    totals: Mapping[Key, Tokens]
    journals: Mapping[tuple[str, str], Mapping[str, str]]
    programs: Mapping[tuple[str, str], str]
    names: Mapping[str, str]
    repos: Mapping[str, str | None]


def _day(timestamp: object) -> str | None:
    if not isinstance(timestamp, str):
        return None
    try:
        return parse_rfc3339_utc(timestamp).date().isoformat()
    except ValueError:
        return None


class _Walk:
    """What one `read` listed, and which directories it could not list."""

    def __init__(self) -> None:
        self.listed: set[Path] = set()
        self.failed: list[Path] = []


class SpendReader:
    def __init__(
        self,
        opener: Callable[[Path], BinaryIO] | None = None,
        repo_of: Callable[[str], str | None] = sessions.main_checkout,
        scandir: Callable[[Path], AbstractContextManager[Iterator[os.DirEntry]]] = os.scandir,
    ):
        self._lines = deliveries.JournalReader(opener) if opener else deliveries.JournalReader()
        self._repo_of = repo_of
        self._scandir = scandir
        self._totals: dict[Key, Tokens] = {}
        self._seen: dict[str, str] = {}
        self._pings: dict[tuple[str, str], str] = {}
        self._journals: dict[tuple[str, str], dict[str, str]] = {}
        self._top_phases: dict[tuple[str, str], set[str]] = {}
        self._programs: dict[tuple[str, str], str] = {}
        self._names: dict[str, str] = {}
        self._repos: dict[str, str | None] = {}
        self._known: set[Path] = set()

    def snapshot(self) -> Snapshot:
        return Snapshot(dict(self._totals),
                        {run: dict(labels) for run, labels in self._journals.items()},
                        dict(self._programs), dict(self._names), dict(self._repos))

    def read(self, projects_dirs: Iterable[Path], since: str, ping_log: Path | None = None) -> None:
        walk = _Walk()
        walked: set[str] = set()
        for projects in projects_dirs:
            real = os.path.realpath(projects)
            if real in walked:
                continue
            walked.add(real)
            self._walk_projects(Path(projects), since, walk)
        if ping_log is not None:
            self._read_pings(Path(ping_log), since)
        for path in sorted(self._known - walk.listed):
            if not any(path.is_relative_to(directory) for directory in walk.failed):
                self._lines.forget(path)
                self._known.discard(path)
        self._prune(since)

    def _children(self, directory: Path, walk: _Walk) -> list[os.DirEntry]:
        """The sorted entries of a directory; nothing when it is absent or cannot be listed."""
        try:
            with self._scandir(directory) as entries:
                return sorted(entries, key=lambda entry: entry.name)
        except _ABSENT:
            return []
        except OSError:
            walk.failed.append(directory)
            return []

    @staticmethod
    def _kind(entry: os.DirEntry) -> tuple[bool, bool]:
        """(is a regular file, is a directory) of an entry; neither when it cannot be told."""
        try:
            return entry.is_file(), entry.is_dir()
        except OSError:
            return False, False

    def _walk_projects(self, projects: Path, since: str, walk: _Walk) -> None:
        for slug in self._children(projects, walk):
            for entry in self._children(Path(slug.path), walk):
                is_file, is_dir = self._kind(entry)
                if is_file and entry.name.endswith(".jsonl"):
                    self._read_file(Path(entry.path), since, walk, SESSION, None, None)
                elif is_dir:
                    self._walk_session(Path(entry.path), entry.name, since, walk)

    def _walk_session(self, session_dir: Path, sid: str, since: str, walk: _Walk) -> None:
        subagents = session_dir / "subagents"
        for entry in self._children(subagents, walk):
            is_file, is_dir = self._kind(entry)
            if is_file and entry.name.startswith("agent-") and entry.name.endswith(".jsonl"):
                self._read_file(Path(entry.path), since, walk, SESSION, None, None)
            elif is_dir and entry.name == "workflows":
                for run in self._children(Path(entry.path), walk):
                    if self._kind(run)[1]:
                        self._walk_run(Path(run.path), sid, run.name, since, walk)

    def _walk_run(self, run_dir: Path, sid: str, run: str, since: str, walk: _Walk) -> None:
        key = (sid, run)
        entries = self._children(run_dir, walk)
        files = {entry.name: entry for entry in entries if self._kind(entry)[0]}
        if JOURNAL_NAME in files:
            self._read_file(Path(files[JOURNAL_NAME].path), since, walk, None, key, None)
        for name, entry in files.items():
            if name.startswith("agent-") and name.endswith(".jsonl"):
                agent = name[len("agent-"):-len(".jsonl")]
                self._read_file(Path(entry.path), since, walk, AGENT, key, agent)

    def _read_file(self, path: Path, since: str, walk: _Walk, source: str | None,
                   run: tuple[str, str] | None, agent: str | None) -> None:
        try:
            moved = os.stat(path)
        except _ABSENT:
            self._lines.forget(path)
            self._known.discard(path)
            return
        except OSError:
            walk.listed.add(path)
            return
        if not S_ISREG(moved.st_mode):
            return
        if _utc_date(moved.st_mtime) < since:
            self._lines.forget(path)
            self._known.discard(path)
            return
        walk.listed.add(path)
        chunk = self._lines.read(path)
        if chunk is None:
            self._known.discard(path)
            walk.listed.discard(path)
            return
        self._known.add(path)
        if not isinstance(chunk, Chunk):
            return
        if source is None:
            self._journal(run, chunk)
        else:
            for record in chunk.records:
                self._transcript(record, since, source, run, agent)

    def _journal(self, run: tuple[str, str] | None, chunk: Chunk) -> None:
        labels = self._journals.setdefault(run, {})
        for record in chunk.records:
            agent, label, phase = record.get("agentId"), record.get("label"), record.get("phase")
            if (record.get("type") != "started" or not isinstance(agent, str)
                    or not isinstance(label, str) or not isinstance(phase, str)):
                continue
            labels[agent] = label
            if not phase.startswith(CHILD_PHASE_PREFIX):
                top = self._top_phases.setdefault(run, set())
                top.add(phase)
                self._programs[run] = run_program(top)

    def _transcript(self, record: dict, since: str, source: str,
                    run: tuple[str, str] | None, agent: str | None) -> None:
        sid = record.get("sessionId")
        kind = record.get("type")
        if isinstance(sid, str):
            for tag, field in (("agent-name", "agentName"), ("custom-title", "customTitle")):
                if kind == tag and isinstance(record.get(field), str):
                    self._names[sid] = record[field]
            cwd = record.get("cwd")
            if isinstance(cwd, str) and sid not in self._repos:
                self._repos[sid] = self._repo_of(cwd)
        if kind != "assistant":
            return
        message = record.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("id"), str):
            return
        tokens = priced(message.get("model"), message.get("usage"))
        day = _day(record.get("timestamp"))
        if tokens is None or day is None or day < since or message["id"] in self._seen:
            return
        self._seen[message["id"]] = day
        key = Key(day, sid if isinstance(sid, str) and sid else None, run, agent, source)
        self._totals[key] = self._totals.get(key, Tokens()) + tokens

    def _read_pings(self, path: Path, since: str) -> None:
        chunk = self._lines.read(path)
        if not isinstance(chunk, Chunk):
            return
        for record in chunk.records:
            day = _day(record.get("ts"))
            conversation = record.get("conversation")
            if record.get("event") != "ping" or day is None or day < since \
                    or not isinstance(conversation, str):
                continue
            tokens = priced(record.get("model"), record.get("usage"))
            ident = (record["ts"], conversation)
            if tokens is None or ident in self._pings:
                continue
            self._pings[ident] = day
            key = Key(day, None, None, None, PING)
            self._totals[key] = self._totals.get(key, Tokens()) + tokens

    def _prune(self, since: str) -> None:
        self._totals = {key: value for key, value in self._totals.items() if key.day >= since}
        self._seen = {ident: day for ident, day in self._seen.items() if day >= since}
        self._pings = {ident: day for ident, day in self._pings.items() if day >= since}


def _utc_date(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).date().isoformat()


def spend_view(
    snapshot: Snapshot,
    *,
    today: str,
    project_of: Callable[[str], str | None],
    profiles: Mapping[str, str],
) -> dict:
    """The wire object of the last `WINDOW_DAYS` days of `snapshot`, attributed (see the docstring)."""
    last = date.fromisoformat(today)
    days = [(last - timedelta(days=n)).isoformat() for n in range(WINDOW_DAYS - 1, -1, -1)]
    totals: dict[str, Tokens] = {day: Tokens() for day in days}
    groups: dict[str, dict[str, dict[str, Tokens]]] = {
        day: {dimension: {} for dimension in DIMENSIONS} for day in days}
    for key, tokens in snapshot.totals.items():
        if key.day not in totals:
            continue
        totals[key.day] += tokens
        for dimension, name in _attribute(snapshot, key, project_of, profiles):
            bucket = groups[key.day][dimension]
            bucket[name] = bucket.get(name, Tokens()) + tokens
    return {
        "approximate": any(total.approximate for total in totals.values()),
        "days": [{"day": day, "total": totals[day].wire(),
                  **{dimension: {name: tokens.wire()
                                 for name, tokens in groups[day][dimension].items()}
                     for dimension in DIMENSIONS}}
                 for day in days],
    }


def _attribute(snapshot: Snapshot, key: Key, project_of: Callable[[str], str | None],
               profiles: Mapping[str, str]) -> Iterator[tuple[str, str]]:
    """The (dimension, name) pairs one key is counted under."""
    session = key.session
    repo = snapshot.repos.get(session) if session is not None else None
    project = project_of(repo) if repo is not None else None
    yield "session", session if session is not None else UNATTRIBUTED
    yield "project", project if project is not None else UNATTRIBUTED
    yield "account", profiles.get(session, UNATTRIBUTED) if session is not None else UNATTRIBUTED
    sprint = None
    if session is None:
        yield "sprint", UNATTRIBUTED
    else:
        match = MANAGER_SESSION_NAME.fullmatch(snapshot.names.get(session, ""))
        if match:
            sprint = match.group("sprint")
            yield "sprint", sprint
    if key.source == AGENT:
        labels = snapshot.journals.get(key.run) if key.run is not None else None
        label = labels.get(key.agent) if labels is not None else None
        yield "run", key.run[1] if labels is not None else UNATTRIBUTED
        yield "phase", phase_of(label) if label is not None else UNATTRIBUTED
        yield "aspect", DELIVERIES
    elif key.source == PING:
        yield "aspect", KEEPALIVE
    elif session is None:
        yield "aspect", UNATTRIBUTED
    else:
        yield "aspect", MANAGERS if sprint is not None else OUTSIDE
