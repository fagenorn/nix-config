"""An aggregating read of one project's delivery transcripts (#1274): counts, times and token sums only.

`project_runs` walks the Claude Code transcript tree and returns, for one project, one `RunDigest`
per workflow run: when it ran, how long, which issues it served (joined inside this read from the
`run_issues` the caller passes) and, per phase, agent, message and tool-call counts, seconds and
token sums. Nothing the caller receives holds a name, label, id, path or text read from the tree.

The tree read is spend's (`agent_tools.console.spend`): under each `projects` directory,
`<slug>/<sid>/subagents/workflows/<run>/` holds `journal.jsonl` and one `agent-<id>.jsonl` per
agent. The journal is read first; each `started` record maps its agent to `spend.phase_of(label)`,
and the run's script is `spend.run_program` of the phases that do not begin with
`deliveries.CHILD_PHASE_PREFIX`. An agent with no journal label has phase `spend.UNATTRIBUTED`.

Attribution is per record: a record counts only when its own str `cwd` maps through `repo_of`
(`sessions.main_checkout`, looked up at call time, when None) and then `project_of` to
`project_id`. A record with no str `cwd`, or whose repository is None, counts nothing, so the agents
of one run in different checkouts each count only where they ran.

The window: a record whose `timestamp` UTC date is before `since` (a `YYYY-MM-DD` date) counts
nothing, and a file whose modification date (UTC) is before `since` is not opened. Nothing here
reads a clock.

The dedupe rule is spend's: one assistant message id counts once across every file of one read,
under the run, agent and phase of its first counted record, its usage the per-field maximum
(`spend.larger_usage`) of every counted repeat. A tool call counts once the same way: a `tool_use` id
read again in another file of one read is counted only under the agent that read it first.

Closed vocabulary: every `script` is one of `spend.BATCH`, `spend.STANDARD`, `spend.OTHER`; every
phase key one of `spend.PHASES`, `spend.OTHER`, `spend.UNATTRIBUTED`; `issues` are the ints of
`run_issues`. No string of the result comes from transcript text.

Unreadable roots: an absent root is empty. `TranscriptsUnreadable` is raised, rather than an empty
digest returned, when at least one given root fails to list with an `OSError` other than
`FileNotFoundError` or `NotADirectoryError` and no given root listed (an absent root is not a
listing, so one absent root and one denied root raise). A lower directory that cannot be listed is
skipped.

Imports: the standard library, `canonical`, `spend`, `deliveries` and `sessions` only. Never
`view`, `project_question`, `question_records` or `service`: `view` imports `project_question`,
which imports `question_records`, which names this module's types, so such an import is a cycle.

Limits: a line that is not a valid UTF-8 JSON object is skipped (a stated limit); each file of the
window is read whole; a record without `cwd` is not attributed.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.canonical import parse_rfc3339_utc
from agent_tools.console import deliveries, sessions, spend

_ABSENT = (FileNotFoundError, NotADirectoryError)


class TranscriptsUnreadable(OSError):
    """Every given transcript root failed to list."""


@dataclass(frozen=True)
class PhaseFigures:
    agents: int
    messages: int
    tool_calls: int
    seconds: int
    tokens: spend.Tokens

    def __add__(self, other: PhaseFigures) -> PhaseFigures:
        return PhaseFigures(self.agents + other.agents, self.messages + other.messages,
                            self.tool_calls + other.tool_calls, self.seconds + other.seconds,
                            self.tokens + other.tokens)


@dataclass(frozen=True)
class RunDigest:
    issues: tuple[int, ...]
    script: str
    started_at: str
    ended_at: str
    seconds: int
    phases: Mapping[str, PhaseFigures]


@dataclass
class _Agent:
    phase: str
    first: datetime | None = None
    last: datetime | None = None
    messages: int = 0
    tokens: spend.Tokens = spend.Tokens()
    tool_ids: set[str] | None = None


@dataclass
class _Run:
    name: str
    script: str = spend.OTHER
    agents: dict[str, _Agent] | None = None


@dataclass
class _Seen:
    owner: _Agent
    model: object
    usage: dict


def _line_object(line: bytes) -> dict | None:
    try:
        record = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return record if isinstance(record, dict) else None


def _records(path: Path) -> Iterable[dict]:
    try:
        with open(path, "rb") as handle:
            for line in handle:
                record = _line_object(line)
                if record is not None:
                    yield record
    except OSError:
        return


def _mtime_day(path: str) -> str | None:
    try:
        seconds = os.stat(path).st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(seconds, timezone.utc).date().isoformat()


class _Reader:
    def __init__(self, project_id: str, project_of: Callable[[str], str | None], since: str,
                 repo_of: Callable[[str], str | None], scandir) -> None:
        self.project_id, self.project_of, self.since = project_id, project_of, since
        self.repo_of, self.scandir = repo_of, scandir
        self.failed: list[str] = []
        self.listed: set[str] = set()
        self.tool_ids: set[str] = set()
        self.projects: dict[str, str | None] = {}
        self.seen: dict[str, _Seen] = {}
        self.runs: list[_Run] = []

    def children(self, directory: str) -> list[os.DirEntry]:
        try:
            with self.scandir(directory) as entries:
                found = sorted(entries, key=lambda entry: entry.name)
            self.listed.add(directory)
            return found
        except _ABSENT:
            return []
        except OSError:
            self.failed.append(directory)
            return []

    @staticmethod
    def kind(entry: os.DirEntry) -> tuple[bool, bool]:
        try:
            return entry.is_file(), entry.is_dir()
        except OSError:
            return False, False

    def walk(self, root: str) -> None:
        for slug in self.children(root):
            if not self.kind(slug)[1]:
                continue
            for session in self.children(slug.path):
                if not self.kind(session)[1]:
                    continue
                for workflows in self.children(os.path.join(session.path, "subagents")):
                    if workflows.name != "workflows" or not self.kind(workflows)[1]:
                        continue
                    for run in self.children(workflows.path):
                        if self.kind(run)[1]:
                            self.walk_run(run.path, run.name)

    def walk_run(self, directory: str, name: str) -> None:
        entries = self.children(directory)
        files = {entry.name: entry for entry in entries if self.kind(entry)[0]}
        run = _Run(name, agents={})
        labels: dict[str, str] = {}
        tops: set[str] = set()
        if deliveries.JOURNAL_NAME in files:
            for record in _records(Path(files[deliveries.JOURNAL_NAME].path)):
                agent, label, phase = (record.get("agentId"), record.get("label"),
                                       record.get("phase"))
                if (record.get("type") == "started" and isinstance(agent, str)
                        and isinstance(label, str) and isinstance(phase, str)):
                    labels[agent] = label
                    if not phase.startswith(deliveries.CHILD_PHASE_PREFIX):
                        tops.add(phase)
        run.script = spend.run_program(tops)
        for file_name, entry in files.items():
            if not (file_name.startswith("agent-") and file_name.endswith(".jsonl")):
                continue
            day = _mtime_day(entry.path)
            if day is None or day < self.since:
                continue
            agent_id = file_name[len("agent-"):-len(".jsonl")]
            label = labels.get(agent_id)
            phase = spend.phase_of(label) if label is not None else spend.UNATTRIBUTED
            agent = _Agent(phase, tool_ids=set())
            self.read_agent(entry.path, agent)
            if agent.first is not None:
                run.agents[agent_id] = agent
        self.runs.append(run)

    def counts(self, record: dict) -> datetime | None:
        """The record's instant when it counts for the project, else None."""
        cwd = record.get("cwd")
        if not isinstance(cwd, str):
            return None
        if cwd not in self.projects:
            repo = self.repo_of(cwd)
            self.projects[cwd] = None if repo is None else self.project_of(repo)
        if self.projects[cwd] != self.project_id:
            return None
        stamp = record.get("timestamp")
        if not isinstance(stamp, str):
            return None
        try:
            moment = parse_rfc3339_utc(stamp)
        except ValueError:
            return None
        return moment if moment.date().isoformat() >= self.since else None

    def read_agent(self, path: str, agent: _Agent) -> None:
        for record in _records(Path(path)):
            moment = self.counts(record)
            if moment is None:
                continue
            agent.first = moment if agent.first is None else min(agent.first, moment)
            agent.last = moment if agent.last is None else max(agent.last, moment)
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, list):
                for item in content:
                    if (isinstance(item, dict) and item.get("type") == "tool_use"
                            and isinstance(item.get("id"), str) and item["id"] not in self.tool_ids):
                        self.tool_ids.add(item["id"])
                        agent.tool_ids.add(item["id"])
            mid = message.get("id")
            if record.get("type") != "assistant" or not isinstance(mid, str):
                continue
            if spend.priced(message.get("model"), message.get("usage")) is None:
                continue
            earlier = self.seen.get(mid)
            if earlier is None:
                self.seen[mid] = _Seen(agent, message.get("model"), message["usage"])
            else:
                earlier.usage = spend.larger_usage(earlier.usage, message["usage"])

    def settle(self) -> None:
        for entry in self.seen.values():
            tokens = spend.priced(entry.model, entry.usage)
            if tokens is not None:
                entry.owner.messages += 1
                entry.owner.tokens = entry.owner.tokens + tokens


def project_runs(
    projects_dirs: Iterable[Path],
    project_id: str,
    project_of: Callable[[str], str | None],
    since: str,
    run_issues: Mapping[str, Sequence[int]],
    *,
    repo_of: Callable[[str], str | None] | None = None,
    scandir=os.scandir,
) -> tuple[RunDigest, ...]:
    """The project's workflow runs read from the transcript roots, oldest first."""
    reader = _Reader(project_id, project_of, since,
                     repo_of if repo_of is not None else sessions.main_checkout, scandir)
    walked: list[str] = []
    for projects in projects_dirs:
        real = os.path.realpath(projects)
        if real not in walked:
            walked.append(real)
            reader.walk(real)
    if any(real in reader.failed for real in walked) and not any(real in reader.listed for real in walked):
        raise TranscriptsUnreadable("no transcript root could be listed")
    reader.settle()
    digests = []
    for run in reader.runs:
        agents = [agent for agent in run.agents.values() if agent.first is not None]
        if not agents:
            continue
        started = min(agent.first for agent in agents)
        ended = max(agent.last for agent in agents)
        phases: dict[str, PhaseFigures] = {}
        for agent in agents:
            figures = PhaseFigures(1, agent.messages, len(agent.tool_ids),
                                   int((agent.last - agent.first).total_seconds()), agent.tokens)
            phases[agent.phase] = phases[agent.phase] + figures if agent.phase in phases \
                else figures
        digests.append(RunDigest(
            tuple(sorted(set(run_issues.get(run.name, ())))), run.script,
            started.isoformat(timespec="seconds"), ended.isoformat(timespec="seconds"),
            int((ended - started).total_seconds()), phases))
    return tuple(sorted(digests, key=lambda d: (d.started_at, d.ended_at, d.script)))
