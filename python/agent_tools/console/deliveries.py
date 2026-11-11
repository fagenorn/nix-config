"""The console's run journals (#858): what a workflow run has done so far, read without re-reading.

A run journal is the append-only JSON-lines file a workflow run writes as it goes, at
`<config>/projects/<slug>/<session_id>/subagents/workflows/<run_id>/journal.jsonl` (`JOURNAL_NAME`
is the file's name). Each line is one JSON object; the journal carries no timestamp, so a run's
last movement is the journal's modification time.

`JournalReader.read(path)` returns what was appended since its last read of that path, never the
whole file again. It keeps, per path, the inode, the byte offset and the bytes of a trailing line
that has no newline yet:

- `None` only when the journal is confirmed absent (`FileNotFoundError` or `NotADirectoryError` from
  `os.stat`); the reader then forgets the path.
- `Unreadable(reason)`, `"<Type>: <message>"` of the `OSError` that stopped the read, for any other
  failure to stat, open or read. It is not absence: the journal may still be there, and the kept
  state is left unchanged, so the next successful read continues where the last one ended.
- `Chunk(records, moved_ms, from_start)` otherwise. `records` are the complete new lines parsed in
  file order (an empty line, invalid UTF-8 or JSON, or a value that is not a JSON object is
  skipped); `moved_ms` is the journal's `st_mtime_ns // 1_000_000` at this read; `from_start` is
  true when this read began at byte 0 (nothing known, a forgotten path, a different inode, or a
  size below the kept offset), and a caller holding a fold of earlier records must then start a
  new fold.

A journal whose size equals the kept offset is not opened. An opened journal is read once, for
exactly the bytes between the offset and the size `os.stat` reported; growth after the stat is
picked up by the next call. Pending bytes are never read from the file again. Nothing here reads a
clock.

The fold: `RunFold.apply(records)` reads journal records in file order, any number of times in any
chunking (folding a list in pieces equals folding it whole), and `RunFold.issues()` answers an
`IssueStage` per known issue, ascending by number. `stage_text` is the plain-words stage.

- Records: a `started` record needs a str `agentId`, `label` and `phase`; a `result` record needs a
  str `agentId` of an earlier `started`. Anything else (`launched`, a non-dict) is ignored.
- Owner: a `started` whose phase begins with `"▸ "` belongs to the child workflow that phase names;
  any other is top-level. A run becomes a batch once a top-level `facts-<n>` label has started.
- Labels are data: `OWNER_LABELS` (a single run's own labels and every child's) and `BATCH_LABELS`
  (the labels a batch program starts itself), one `(stage, pattern)` row per label template matched
  with `re.fullmatch`. In the batch table only the listed issue-bearing templates carry an issue
  (group 1); any other number there counts trains, sweeps or rounds and is never an issue, so an
  unknown batch label, or one with no issue, touches no issue. An owner label not in its table
  reads `WORKING`, never an error; a step with no stage moves nothing.
- A child's issue is named by its `setup` result's `branch` (`issue-<n>`, then `-` or the end); a
  non-batch run's own `setup` result names the run's issue likewise. The issue is created at
  `PLANNING` if not yet known, and everything its owner did before then (stages, plan counts,
  close-outs) is applied at that moment, in order. Until then a child touches no issue.
- A `plan`, `plan-revise` or `plan-rules-revise` result with `status` `"planned"` and a non-empty
  `tasks` list sets its issue's task total (latest wins; the count is per issue, so a later child
  of the same issue inherits it). A `BUILDING` label with a task sets the issue's task.
- A `close-out` result (owner) or `close-out-<n>` result (batch) makes its issue `DONE` only when
  `closed_out(result)`: the close-out released the claim, ended the decision, left the issue in
  `OPEN` (held) or `CLOSED` and did not report its notes unposted. Any other result leaves the
  issue as the label left it.
- `DONE` is final. A `QUEUED` step changes only an issue that is new or still `QUEUED`.

Delivery events (the log's rows for the run journals): `delivery.seen` (`DELIVERY_SEEN`) carries
`seen_payload(state)`, `{"session_id", "run_id", "moved_ms", "issues": [{"issue", "stage", "task",
"tasks"}, ...]}` with `None` as null, and `delivery.gone` (`DELIVERY_GONE`) carries
`{"session_id", "run_id"}`. `delivery_states(events, states=None)` folds them onto a `DeliveryState`
per `(session_id, run_id)`: a `seen` whose `session_id` and `run_id` are str, `moved_ms` an int (not
a bool) and `issues` a list of dicts each with an int (not bool) `issue`, a `stage` in `STAGES` and
`task`/`tasks` an int or null replaces any earlier state; a `seen` of any other shape is ignored
whole; a `gone` with str `session_id` and `run_id` removes the key; other kinds are ignored, and
folding onto earlier states equals folding all events. `delivery_changes(states, readings, scanned,
project_of)` lists what to append: a `seen` for each reading (in key order) that differs from the
known state, then a `gone` for each known state (in key order) of a scanned session that has no
reading; a state of a session not scanned yields nothing.

Moved text: `moved_text(elapsed_ms)` turns the time since a journal's last movement into
`(quiet, text)`. Below 0 counts as 0; under a minute reads `"moved just now"`; under
`QUIET_AFTER_MS` (15 minutes) `"moved <n> min ago"`; from then on it is quiet, `"quiet for <n> min"`.
A journal that has not moved carries no sign of why, so the console never calls a run stalled.
"""


import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO, Callable, Iterable, Mapping

from agent_tools.console.event_log import Event

JOURNAL_NAME = "journal.jsonl"


@dataclass(frozen=True)
class Chunk:
    """The complete new lines of a journal, the journal's mtime in ms, and whether this read began at byte 0."""

    records: tuple[dict, ...]
    moved_ms: int
    from_start: bool


@dataclass(frozen=True)
class Unreadable:
    """`"<Type>: <message>"` of the `OSError` that stopped a read; not absence."""

    reason: str


def _open_binary(path: Path) -> BinaryIO:
    return open(path, "rb")


def _reason(error: OSError) -> str:
    return f"{type(error).__name__}: {error}"


def _parse(line: bytes) -> dict | None:
    try:
        value = json.loads(line.decode("utf-8"))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


class JournalReader:
    def __init__(self, opener: Callable[[Path], BinaryIO] = _open_binary):
        self._opener = opener
        self._known: dict[Path, tuple[int, int, bytes]] = {}

    def forget(self, path: Path) -> None:
        self._known.pop(path, None)

    def read(self, path: Path) -> Chunk | Unreadable | None:
        try:
            stat = os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            self.forget(path)
            return None
        except OSError as error:
            return Unreadable(_reason(error))
        moved_ms = stat.st_mtime_ns // 1_000_000
        known = self._known.get(path)
        from_start = known is None or known[0] != stat.st_ino or stat.st_size < known[1]
        _, offset, pending = (stat.st_ino, 0, b"") if from_start else known
        if stat.st_size == offset:
            self._known[path] = (stat.st_ino, offset, pending)
            return Chunk((), moved_ms, from_start)
        try:
            with self._opener(path) as handle:
                handle.seek(offset)
                data = handle.read(stat.st_size - offset)
        except OSError as error:
            return Unreadable(_reason(error))
        *lines, pending = (pending + data).split(b"\n")
        self._known[path] = (stat.st_ino, offset + len(data), pending)
        records = tuple(record for record in map(_parse, lines) if record is not None)
        return Chunk(records, moved_ms, from_start)


QUEUED = "queued"
PLANNING = "planning"
PLAN_REVIEW = "plan review"
BUILDING = "building"
FINAL_REVIEW = "final review"
VERIFYING = "verifying"
LANDING = "landing"
DONE = "done"
WORKING = "working"
STAGES = (QUEUED, PLANNING, PLAN_REVIEW, BUILDING, FINAL_REVIEW, VERIFYING, LANDING, DONE, WORKING)

CHILD_PHASE_PREFIX = "\u25b8 "


@dataclass(frozen=True)
class IssueStage:
    """One issue's stage, with the task being built and the plan's task total when known."""

    issue: int
    stage: str
    task: int | None = None
    tasks: int | None = None


def stage_text(stage: IssueStage) -> str:
    if stage.stage != BUILDING or stage.task is None:
        return stage.stage
    if stage.tasks is None:
        return f"building task {stage.task}"
    return f"building task {stage.task} of {stage.tasks}"


@dataclass(frozen=True)
class Step:
    """What one label means: `stage` None moves no stage; `issue` only from a batch label naming one."""

    stage: str | None
    task: int | None = None
    issue: int | None = None


# One (stage, pattern) row per label template. Owner rows: group 1, where present, is the task.
OWNER_LABELS: tuple[tuple[str | None, str], ...] = (
    (None, r"setup|acquire|worktree"),
    (PLANNING, r"owner-answer|amend|renew-plan|renew-amend|plan|plan-revise|plan-rules-revise"),
    (PLAN_REVIEW, r"plan-review|plan-codex|plan-rules-review"),
    (BUILDING, r"impl-(\d+)"),
    (BUILDING, r"review-(\d+)"),
    (BUILDING, r"fix-(\d+)-\d+"),
    (BUILDING, r"rereview-(\d+)-\d+"),
    (BUILDING, r"direct-impl"),
    (
        FINAL_REVIEW,
        r"renew-final-review|diff-size|final-codex|final-\d+|final-integration|fix-wave|fix-wave-\d+"
        r"|fix-wave-review|fix-wave-review-\d+|direct-codex|direct-review|direct-review-full|direct-fix"
        r"|direct-rereview",
    ),
    (VERIFYING, r"verify|verify-\d+|verify-fix-\d+|verify-fix-review-\d+|ws-check-\d+"),
    (
        LANDING,
        r"pr|hold|merge|close-out|land-unlock|fix-ci|fix-ci-review|land-lock-\d+|land-push-\d+|checks-\d+"
        r"|sync-\d+|sync-review-\d+|fix-sync-\d+|fix-sync-review-\d+",
    ),
)

# Batch rows: group 1, where present, is the issue number. The counters of trains, sweeps and rounds
# carry no group, so they can never be read as an issue.
BATCH_LABELS: tuple[tuple[str | None, str], ...] = (
    (
        None,
        r"setup|train-build-\d+|train-ready-\d+|train-merge-\d+|train-sweep-\d+|train-checks-\d+-\d+"
        r"|train-flip-\d+-\d+",
    ),
    (QUEUED, r"facts-(\d+)"),
    (PLANNING, r"acquire-(\d+)|readopt-(\d+)"),
    (WORKING, r"release-(\d+)|recover-end-(\d+)|ask-(\d+)|settle-(\d+)"),
    (LANDING, r"close-out-(\d+)|train-pr-(\d+)|land-[a-z]+(?:-[a-z]+)*-(\d+)(?:-\d+)?"),
)


def _group(match: re.Match) -> int | None:
    found = next((g for g in match.groups() if g is not None), None)
    return None if found is None else int(found)


def classify(label: str, *, batch: bool) -> Step | None:
    """The step a label stands for in the owner table or, with `batch`, the batch table; None if unknown."""
    for stage, pattern in BATCH_LABELS if batch else OWNER_LABELS:
        match = re.fullmatch(pattern, label)
        if match is None:
            continue
        number = _group(match)
        if batch:
            return Step(stage, issue=number)
        return Step(stage, task=number)
    return None


def closed_out(result: object) -> bool:
    """True for a close-out result showing the close-out finished (the programs' own test, less what the console cannot know)."""
    return (
        isinstance(result, dict)
        and result.get("released") is True
        and result.get("decision_ended") is True
        and result.get("issue_state") in ("OPEN", "CLOSED")
        and result.get("notes_posted") is not False
    )


_BRANCH_ISSUE = re.compile(r"issue-(\d+)(-|$)")
_PLAN_LABELS = ("plan", "plan-revise", "plan-rules-revise")
_BATCH_CLOSE_OUT = re.compile(r"close-out-(\d+)")


class _Owner:
    """A run's own labels, or one child's: its issue once its setup result names it, and what waits for that."""

    def __init__(self) -> None:
        self.issue: int | None = None
        self.waiting: list[tuple[str, object]] = []


class RunFold:
    def __init__(self) -> None:
        self._issues: dict[int, IssueStage] = {}
        self._owners: dict[str | None, _Owner] = {}
        self._agents: dict[str, tuple[str, str | None]] = {}
        self._batch = False

    def issues(self) -> tuple[IssueStage, ...]:
        return tuple(self._issues[number] for number in sorted(self._issues))

    def apply(self, records: Iterable[object]) -> None:
        for record in records:
            if not isinstance(record, dict):
                continue
            agent, kind = record.get("agentId"), record.get("type")
            if not isinstance(agent, str):
                continue
            if kind == "started":
                label, phase = record.get("label"), record.get("phase")
                if isinstance(label, str) and isinstance(phase, str):
                    self._started(agent, label, phase)
            elif kind == "result" and agent in self._agents:
                self._result(*self._agents[agent], record.get("result"))

    def _owner(self, key: str | None) -> _Owner:
        return self._owners.setdefault(key, _Owner())

    def _started(self, agent: str, label: str, phase: str) -> None:
        key = phase if phase.startswith(CHILD_PHASE_PREFIX) else None
        self._agents[agent] = (label, key)
        if key is None:
            step = classify(label, batch=True)
            if step is not None and step.stage == QUEUED and step.issue is not None:
                self._batch = True
            if self._batch:
                if step is not None and step.issue is not None:
                    self._step(step.issue, step)
                return
        step = classify(label, batch=False) or Step(WORKING)
        self._effect(self._owner(key), "step", step)

    def _result(self, label: str, key: str | None, result: object) -> None:
        if key is None and self._batch:
            match = _BATCH_CLOSE_OUT.fullmatch(label)
            if match is not None and closed_out(result):
                self._done(int(match.group(1)))
            return
        owner = self._owner(key)
        if label == "setup":
            branch = result.get("branch") if isinstance(result, dict) else None
            match = _BRANCH_ISSUE.match(branch) if isinstance(branch, str) else None
            if match is not None:
                self._name(owner, int(match.group(1)))
        elif label in _PLAN_LABELS:
            if isinstance(result, dict) and result.get("status") == "planned":
                tasks = result.get("tasks")
                if isinstance(tasks, list) and tasks:
                    self._effect(owner, "tasks", len(tasks))
        elif label == "close-out" and closed_out(result):
            self._effect(owner, "done", None)

    def _name(self, owner: _Owner, issue: int) -> None:
        owner.issue = issue
        if issue not in self._issues:
            self._issues[issue] = IssueStage(issue, PLANNING)
        waiting, owner.waiting = owner.waiting, []
        for kind, value in waiting:
            self._effect(owner, kind, value)

    def _effect(self, owner: _Owner, kind: str, value: object) -> None:
        if owner.issue is None:
            owner.waiting.append((kind, value))
        elif kind == "step":
            self._step(owner.issue, value)
        elif kind == "tasks":
            self._update(owner.issue, tasks=value)
        else:
            self._done(owner.issue)

    def _update(self, issue: int, **fields) -> None:
        current = self._issues.get(issue)
        if current is None:
            current = IssueStage(issue, fields.pop("stage", PLANNING))
        if current.stage != DONE:
            self._issues[issue] = replace(current, **fields)

    def _step(self, issue: int, step: Step) -> None:
        if step.stage is None:
            return
        current = self._issues.get(issue)
        if step.stage == QUEUED and current is not None and current.stage != QUEUED:
            return
        if current is None:
            self._issues[issue] = IssueStage(issue, step.stage, step.task)
        elif current.stage != DONE:
            task = step.task if step.task is not None else current.task
            self._issues[issue] = replace(current, stage=step.stage, task=task)

    def _done(self, issue: int) -> None:
        self._update(issue, stage=DONE)


QUIET_AFTER_MS = 15 * 60 * 1000
DELIVERY_SEEN = "delivery.seen"
DELIVERY_GONE = "delivery.gone"


def moved_text(elapsed_ms: int) -> tuple[bool, str]:
    """`(quiet, text)` for the time since a journal last moved."""
    elapsed_ms = max(elapsed_ms, 0)
    minutes = elapsed_ms // 60_000
    if elapsed_ms < 60_000:
        return False, "moved just now"
    if elapsed_ms < QUIET_AFTER_MS:
        return False, f"moved {minutes} min ago"
    return True, f"quiet for {minutes} min"


@dataclass(frozen=True)
class DeliveryState:
    """One run of one session: when its journal last moved and each issue's stage."""

    session_id: str
    run_id: str
    moved_ms: int
    issues: tuple[IssueStage, ...]


def seen_payload(state: DeliveryState) -> dict:
    return {
        "session_id": state.session_id,
        "run_id": state.run_id,
        "moved_ms": state.moved_ms,
        "issues": [
            {"issue": i.issue, "stage": i.stage, "task": i.task, "tasks": i.tasks}
            for i in state.issues
        ],
    }


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _count(value: object) -> bool:
    return value is None or _integer(value)


def _issue_stage(row: object) -> IssueStage | None:
    if not isinstance(row, dict):
        return None
    issue, stage, task, tasks = (row.get(k) for k in ("issue", "stage", "task", "tasks"))
    if not _integer(issue) or stage not in STAGES or not _count(task) or not _count(tasks):
        return None
    return IssueStage(issue, stage, task, tasks)


def _seen_state(payload: dict) -> DeliveryState | None:
    session_id, run_id = payload.get("session_id"), payload.get("run_id")
    moved, rows = payload.get("moved_ms"), payload.get("issues")
    if not isinstance(session_id, str) or not isinstance(run_id, str):
        return None
    if not _integer(moved) or not isinstance(rows, list):
        return None
    issues = tuple(_issue_stage(row) for row in rows)
    if any(issue is None for issue in issues):
        return None
    return DeliveryState(session_id, run_id, moved, issues)


def delivery_states(
    events: Iterable[Event],
    states: Mapping[tuple[str, str], DeliveryState] | None = None,
) -> dict[tuple[str, str], DeliveryState]:
    result = dict(states or {})
    for event in events:
        payload = event.payload
        if not isinstance(payload, dict):
            continue
        if event.kind == DELIVERY_SEEN:
            state = _seen_state(payload)
            if state is not None:
                result[(state.session_id, state.run_id)] = state
        elif event.kind == DELIVERY_GONE:
            session_id, run_id = payload.get("session_id"), payload.get("run_id")
            if isinstance(session_id, str) and isinstance(run_id, str):
                result.pop((session_id, run_id), None)
    return result


def delivery_changes(
    states: Mapping[tuple[str, str], DeliveryState],
    readings: Mapping[tuple[str, str], DeliveryState],
    scanned: Iterable[str],
    project_of: Callable[[str], str | None],
) -> list[tuple[str, str | None, dict]]:
    scanned = frozenset(scanned)
    changes: list[tuple[str, str | None, dict]] = []
    for key in sorted(readings):
        if states.get(key) != readings[key]:
            changes.append((DELIVERY_SEEN, project_of(key[0]), seen_payload(readings[key])))
    for key in sorted(states):
        if key[0] in scanned and key not in readings:
            changes.append((DELIVERY_GONE, project_of(key[0]), {"session_id": key[0], "run_id": key[1]}))
    return changes
