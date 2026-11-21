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
- Two `projects` paths with one `os.path.realpath` are walked once, and always through that real
  path, so a file's cursor survives a change of alias or of order.

Incremental: every file goes through one `deliveries.JournalReader`, so a second `read` opens only
a file whose size moved and reads only its new bytes. A file whose modification date (UTC) is before
`since` is not opened and its cursor is forgotten. A file the reader finds absent, or that this read
did not list, loses its cursor; but a directory whose listing fails with an `OSError` other than
`FileNotFoundError` or `NotADirectoryError` confirms nothing, so every cursor known under it is
kept and only bytes appended since are read once it lists again. `roots_unreadable` is True after a `read` whose every
`projects` directory failed to list that way (an absent one is empty, not a failure): the empty totals then say nothing
about spend, and a caller with no view yet must not publish them as zero. `read` never raises for a missing
or unreadable directory or file.

The key: `Key(day, session, run, agent, source)`, `day` the UTC date of the message `timestamp`,
`session` the line's `sessionId` (None when absent or empty). `totals` sums `Tokens` per key.

- A line with `type == "assistant"` and a `message` that holds a str `id`, a usage `priced` accepts
  and a parsable str `timestamp` is counted when its day is `>= since`: one message id is one count
  across every file and every read (the transcript writes one line per content block of a message,
  and a streamed message repeats its id with growing usage). A repeat raises the count to the larger
  of each usage field, under the key of the first record, and never lowers it. Seen ids and totals of days before `since`
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

The view: `spend_view(snapshot, today, project_of, profiles, questions)` is the wire object
`{"approximate": <bool>, "days": [<day>, ...]}`, `WINDOW_DAYS` days, `today` and the days before it
(UTC), oldest first. A day is `{"day", "total", <dimension>: {<key>: <tokens>}}` for each of
`DIMENSIONS`, every `<tokens>` a `Tokens.wire()`, plus `"sprint_phase": {<sprint id>: {<phase>:
<tokens>}}`, `"run_phase": {<run id>: {<phase>: <tokens>}}` and `"project_items": {<project id>:
{"run": {<run id>: {<phase>: <tokens>}}, "sprint": {<sprint id>: {<phase>: <tokens>}}}}` (#1271,
ADR-console-089), always present; a day with nothing
has a zero `total` and empty maps, and a key dated outside the days is ignored. Each message has
one key in `session`, `project`, `account` and `aspect`, so the sums over each equal `total`.
`approximate` is true when any message counted is, per day in `total` and for the view. The keys,
per message key:

- `session`: the key's session, else `UNATTRIBUTED`.
- `project`: `project_of(repo)` of the session's repository (`Snapshot.repos`), `UNATTRIBUTED` when
  the session, its repository or its project is unknown.
- `account`: `profiles[session]` (the profile the session was seen under), else `questions[session]`
  (the profile of its question row), else `UNATTRIBUTED`.
- `sprint`: the sprint id when the session's name fully matches `MANAGER_SESSION_NAME`, `UNATTRIBUTED`
  when the session is unknown, and not counted for any other session.
- `run` and `phase` (source `AGENT` only): the run id when the run has a journal, and the phase of
  the agent's journal label; `UNATTRIBUTED` when the run or the agent has no journal record.
- `aspect`: `KEEPALIVE` for a ping; `DELIVERIES` for a workflow agent; for a session's own and
  subagent transcripts `QUESTIONS` when the session is in `questions` (the sessions
  `question_sessions` folds from the log's `project_question.asked` rows, ADR-console-059),
  checked before `MANAGERS`, which is for a session that is a sprint's, `OUTSIDE` otherwise, and
  `UNATTRIBUTED` when the session is unknown.

`question_sessions(events, known)` maps a session id to the profile of the latest
`project_question.asked` row naming it; a row without a non-empty `session_id` and a `profile`
(one written before the row carried them) is ignored, `known` is copied, never mutated.

The two item breakdowns cover attributed items only: a key whose `sprint` is a sprint id (not
`UNATTRIBUTED`) is counted in `sprint_phase[sprint][p]`, and a key whose `run` is a run id in
`run_phase[run][p]`, where `p` is the key's `phase` (`UNATTRIBUTED` for an agent without a journal
label) and, for a key with no `phase` (a session's own or subagent transcript, only in
`sprint_phase`), `MANAGER_PHASE`; an `UNATTRIBUTED` item has no entry. Per day and item the
phase tokens sum to the item's entry in `sprint` or `run` (every count field; dollars to
rounding, since each `Tokens.wire()` rounds on its own).

`project_items` splits the same items by project, because a run id is unique only within a project
(two projects' runs may share one, and `run_phase` sums them): an item is counted under
`project_items[p][kind]` exactly when it is counted under `<kind>_phase` and the key's `project`
is `p`, not `UNATTRIBUTED`, with the same phase rule (`MANAGER_PHASE` for a sprint item with no
phase). So per kind, item and phase the sum over projects is at most the `<kind>_phase` figure,
and equal when every key is attributed. A project or kind with no item has no entry, an
`UNATTRIBUTED` project, run or sprint never has one, and a day with nothing has `{}`.

The check (`python -m agent_tools.console.spend check-shares`): reads the transcripts under each
`--projects` directory (default `~/.claude/projects`) from `--from` (default `2026-11-09`, the
reader's `since`) and sums, over the `AGENT` keys of runs whose program is `--program` (default
`deliver-batch`; nested deliver-standard children are inside the run) dated from `--from` to `--to`
(default `2026-11-16`) inclusive, input + cache_write + cache_read + output tokens per phase
(`phase_shares`; `UNATTRIBUTED` for an agent without a journal label). It prints one JSON line
`{"program", "from", "to", "tokens", "shares", "reference", "off", "tolerance"}` (`shares` in
percent rounded to 2 decimals, `reference` is `REFERENCE_BATCH_SHARES`, the delivery cost
measurement's deliver-batch table grouped into `PHASES`, `off` the phases of the reference, in
`PHASES` order, whose share is more than `--tolerance` points (default 3.0) from it). Exit 0 when
there are tokens and `off` is empty, 1 when a phase is off, 75 when the window holds no tokens (its
transcripts are gone or not yet read), 2 on a usage error or a `--from` after `--to`.
`--from` and `--to` take any ISO 8601 date `date.fromisoformat` accepts and are read as the
`YYYY-MM-DD` day it names.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
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
from agent_tools.console.event_log import PROJECT_QUESTION_ASKED, Event
from agent_tools.console.sprints import MANAGER_SESSION_NAME
from agent_tools.hosts import model_pricing

UNATTRIBUTED = "unattributed"
OTHER = "other"
MANAGER_PHASE = "manager"
ITEM_PHASES = ("sprint", "run")
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
QUESTIONS = "questions"
DIMENSIONS = ("session", "project", "sprint", "run", "phase", "account", "aspect")

BATCH = "deliver-batch"
STANDARD = "deliver-standard"

REFERENCE_BATCH_SHARES: dict[str, float] = {
    "setup": 2.6, "plan": 17.1, "plan review": 9.7, "plan revise": 7.9, "implement": 28.0,
    "task review": 7.9, "final review": 11.0, "fix wave": 8.3, "verify": 0.7, "land": 5.8,
    "close-out": 1.0}

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


@dataclass(frozen=True)
class _Message:
    """What one assistant message id has counted so far: where, its merged usage, its tokens."""

    day: str
    key: Key
    usage: dict
    tokens: Tokens


def _larger(first: dict, second: dict) -> dict:
    """The usage whose every count is the larger of the two (both already validated by `priced`)."""
    merged = {field: max(first.get(field) or 0, second.get(field) or 0)
              for field in _TOKEN_FIELDS}
    splits = [usage["cache_creation"] for usage in (first, second)
              if isinstance(usage.get("cache_creation"), dict)]
    if splits:
        merged["cache_creation"] = {field: max(split.get(field) or 0 for split in splits)
                                    for field in _SPLIT_FIELDS}
    return merged


def _difference(after: Tokens, before: Tokens) -> Tokens:
    return Tokens(after.input - before.input, after.cache_write - before.cache_write,
                  after.cache_read - before.cache_read, after.output - before.output,
                  after.dollars - before.dollars, after.approximate)


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
        self._seen: dict[str, _Message] = {}
        self._pings: dict[tuple[str, str], str] = {}
        self._journals: dict[tuple[str, str], dict[str, str]] = {}
        self._top_phases: dict[tuple[str, str], set[str]] = {}
        self._programs: dict[tuple[str, str], str] = {}
        self._names: dict[str, str] = {}
        self._repos: dict[str, str | None] = {}
        self._known: set[Path] = set()
        self.roots_unreadable = False

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
            self._walk_projects(Path(real), since, walk)
        self.roots_unreadable = bool(walked) and all(Path(real) in walk.failed for real in walked)
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
        if tokens is None or day is None or day < since:
            return
        earlier = self._seen.get(message["id"])
        if earlier is None:
            key = Key(day, sid if isinstance(sid, str) and sid else None, run, agent, source)
            self._seen[message["id"]] = _Message(day, key, message["usage"], tokens)
            self._totals[key] = self._totals.get(key, Tokens()) + tokens
            return
        # A streamed message repeats its id with growing usage: keep each field's maximum.
        usage = _larger(earlier.usage, message["usage"])
        raised = priced(message.get("model"), usage)
        if raised is None:
            return
        self._seen[message["id"]] = _Message(earlier.day, earlier.key, usage, raised)
        self._totals[earlier.key] = self._totals.get(earlier.key, Tokens()) + _difference(
            raised, earlier.tokens)

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
        self._seen = {ident: seen for ident, seen in self._seen.items() if seen.day >= since}
        self._pings = {ident: day for ident, day in self._pings.items() if day >= since}


def _utc_date(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).date().isoformat()


def spend_view(
    snapshot: Snapshot,
    *,
    today: str,
    project_of: Callable[[str], str | None],
    profiles: Mapping[str, str],
    questions: Mapping[str, str] | None = None,
) -> dict:
    """The wire object of the last `WINDOW_DAYS` days of `snapshot`, attributed (see the docstring)."""
    questions = {} if questions is None else questions
    last = date.fromisoformat(today)
    days = [(last - timedelta(days=n)).isoformat() for n in range(WINDOW_DAYS - 1, -1, -1)]
    totals: dict[str, Tokens] = {day: Tokens() for day in days}
    groups: dict[str, dict[str, dict[str, Tokens]]] = {
        day: {dimension: {} for dimension in DIMENSIONS} for day in days}
    items: dict[str, dict[str, dict[str, dict[str, Tokens]]]] = {
        day: {kind: {} for kind in ITEM_PHASES} for day in days}
    by_project: dict[str, dict[str, dict[str, dict[str, dict[str, Tokens]]]]] = {
        day: {} for day in days}
    for key, tokens in snapshot.totals.items():
        if key.day not in totals:
            continue
        totals[key.day] += tokens
        named = dict(_attribute(snapshot, key, project_of, profiles, questions))
        for dimension, name in named.items():
            bucket = groups[key.day][dimension]
            bucket[name] = bucket.get(name, Tokens()) + tokens
        for kind in ITEM_PHASES:
            item = named.get(kind, UNATTRIBUTED)
            if item == UNATTRIBUTED:
                continue
            phase = named.get("phase", MANAGER_PHASE if kind == "sprint" else None)
            if phase is None:
                continue
            bucket = items[key.day][kind].setdefault(item, {})
            bucket[phase] = bucket.get(phase, Tokens()) + tokens
            project = named["project"]
            if project != UNATTRIBUTED:
                kinds = by_project[key.day].setdefault(project, {})
                bucket = kinds.setdefault(kind, {}).setdefault(item, {})
                bucket[phase] = bucket.get(phase, Tokens()) + tokens
    return {
        "approximate": any(total.approximate for total in totals.values()),
        "days": [{"day": day, "total": totals[day].wire(),
                  **{dimension: {name: tokens.wire()
                                 for name, tokens in groups[day][dimension].items()}
                     for dimension in DIMENSIONS},
                  **{kind + "_phase": {
                      item: {phase: tokens.wire() for phase, tokens in phases.items()}
                      for item, phases in items[day][kind].items()}
                     for kind in ITEM_PHASES},
                  "project_items": {
                      project: {kind: {item: {phase: tokens.wire()
                                              for phase, tokens in phases.items()}
                                       for item, phases in by_item.items()}
                                for kind, by_item in kinds.items()}
                      for project, kinds in by_project[day].items()}}
                 for day in days],
    }


def _attribute(snapshot: Snapshot, key: Key, project_of: Callable[[str], str | None],
               profiles: Mapping[str, str], questions: Mapping[str, str]
               ) -> Iterator[tuple[str, str]]:
    """The (dimension, name) pairs one key is counted under."""
    session = key.session
    repo = snapshot.repos.get(session) if session is not None else None
    project = project_of(repo) if repo is not None else None
    yield "session", session if session is not None else UNATTRIBUTED
    yield "project", project if project is not None else UNATTRIBUTED
    if session is None:
        yield "account", UNATTRIBUTED
    elif session in profiles:
        yield "account", profiles[session]
    else:
        yield "account", questions.get(session, UNATTRIBUTED)
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
    elif session in questions:
        yield "aspect", QUESTIONS
    else:
        yield "aspect", MANAGERS if sprint is not None else OUTSIDE


def default_ping_log() -> Path | None:
    """The keepalive proxy's log file: `~/Library/Logs/claude-cache-proxy.log` on darwin, else None."""
    if sys.platform == "darwin":
        return Path.home() / "Library/Logs/claude-cache-proxy.log"
    return None


def session_profiles(events: Iterable[Event],
                     profiles: Mapping[str, str] | None = None) -> dict[str, str]:
    """Session id -> the account of its latest `SEEN` or `PROFILE` row; `GONE` forgets nothing."""
    found = dict(profiles) if profiles else {}
    for event in events:
        if event.kind not in (sessions.SEEN, sessions.PROFILE):
            continue
        session_id, profile = event.payload.get("session_id"), event.payload.get("profile")
        if isinstance(session_id, str) and isinstance(profile, str):
            found[session_id] = profile
    return found


def question_sessions(events: Iterable[Event],
                      known: Mapping[str, str] | None = None) -> dict[str, str]:
    """Session id -> the profile of its latest `project_question.asked` row; other rows are ignored."""
    found = dict(known) if known else {}
    for event in events:
        if event.kind != PROJECT_QUESTION_ASKED:
            continue
        session_id, profile = event.payload.get("session_id"), event.payload.get("profile")
        if isinstance(session_id, str) and session_id and isinstance(profile, str):
            found[session_id] = profile
    return found


def phase_shares(snapshot: Snapshot, program: str, start: str, end: str
                 ) -> tuple[int, dict[str, float]]:
    """(summed tokens, percent share per phase) of `program`'s workflow agents from day `start` to `end`."""
    sums: dict[str, int] = {phase: 0 for phase in (*PHASES, OTHER, UNATTRIBUTED)}
    for key, tokens in snapshot.totals.items():
        if (key.source != AGENT or key.run is None or snapshot.programs.get(key.run) != program
                or not start <= key.day <= end):
            continue
        label = snapshot.journals.get(key.run, {}).get(key.agent)
        phase = phase_of(label) if label is not None else UNATTRIBUTED
        sums[phase] += tokens.input + tokens.cache_write + tokens.cache_read + tokens.output
    total = sum(sums.values())
    return total, {phase: 100 * count / total if total else 0.0 for phase, count in sums.items()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spend", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check-shares", help="compare the phase shares with the measurement")
    check.add_argument("--projects", type=Path, action="append", metavar="DIR")
    check.add_argument("--from", dest="start", default="2026-11-09")
    check.add_argument("--to", dest="end", default="2026-11-16")
    check.add_argument("--tolerance", type=float, default=3.0)
    check.add_argument("--program", default=BATCH)
    try:
        args = parser.parse_args(argv)
        args.start = date.fromisoformat(args.start).isoformat()
        args.end = date.fromisoformat(args.end).isoformat()
        if args.start > args.end:
            parser.error("--from is after --to")
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else 2
    except ValueError as error:
        print(f"spend: {error}", file=sys.stderr)
        return 2
    reader = SpendReader()
    reader.read(args.projects or [Path.home() / ".claude/projects"], args.start)
    tokens, shares = phase_shares(reader.snapshot(), args.program, args.start, args.end)
    off = [phase for phase in PHASES
           if abs(shares[phase] - REFERENCE_BATCH_SHARES[phase]) > args.tolerance]
    print(json.dumps({"program": args.program, "from": args.start, "to": args.end,
                      "tokens": tokens,
                      "shares": {phase: round(share, 2) for phase, share in shares.items()},
                      "reference": REFERENCE_BATCH_SHARES, "off": off,
                      "tolerance": args.tolerance}, sort_keys=True))
    if tokens == 0:
        return 75
    return 1 if off else 0


if __name__ == "__main__":
    sys.exit(main())
