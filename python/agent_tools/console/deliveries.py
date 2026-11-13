"""The console's run journals (#858): what a workflow run has done so far, read without re-reading.

A run journal is the append-only JSON-lines file a workflow run writes as it goes, at
`<config>/projects/<slug>/<session_id>/subagents/workflows/<run_id>/journal.jsonl` (`JOURNAL_NAME`
is the file's name). Each line is one JSON object; the journal carries no timestamp, so a run's
last movement is the journal's modification time.

`JournalReader.read(path)` returns what was appended since its last read of that path, never the
whole file again. It keeps, per path, the inode, the byte offset and the bytes of a trailing line
that has no newline yet:

- `None` only when the journal is confirmed absent (`FileNotFoundError`, `NotADirectoryError` or, for
  a path that holds a NUL and so cannot exist, `ValueError` from `os.stat`); the reader then forgets
  the path.
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
  reads `WORKING`, never an error; a step with no stage moves nothing. A label ending in `RERUN_SUFFIX`
  (`-again`: a review step the program ran once more after an unusable reply) is read as the label
  before the suffix, in both tables.
- `RunFold(branch_pattern)` takes the project's configured branch pattern (`<num>` and `<slug>`
  placeholders, as `issue-branch` renders it) or None. A child's issue is the number its `setup`
  result's `branch` carries under that pattern (`branch_issue`; a branch that does not fit it, a
  pattern with no `<num>`, or None names no issue); a non-batch run's own `setup` result names the
  run's issue likewise. The issue is created at
  `PLANNING` if not yet known, and everything its owner did before then (stages, plan counts,
  close-outs) is applied at that moment, in order. Until then a child touches no issue.
- A `plan`, `plan-revise`, `plan-rules-revise`, `plan-branch-revise` or `plan-task-revise` result with `status` `"planned"` and a non-empty
  `tasks` list sets its issue's task total (latest wins; the count is per issue, so a later child
  of the same issue inherits it). A `BUILDING` label with a task sets the issue's task.
- A `plan`, `plan-revise`, `plan-rules-revise`, `plan-branch-revise` or `plan-task-revise` result's non-empty `acceptance` list also grades its
  issue (`Grading`; latest wins): held when a criterion has kind `evidence` or `human`, with notes
  when one has kind `note`.
- A `close-out` result (owner) or `close-out-<n>` result (batch) makes its issue `DONE` only when
  `closed_out(result, grading, batch)`: the close-out released the claim, ended the decision, and
  left the issue in the state the programs require (`CLOSED` when nothing is held; `OPEN` when held
  in a batch; either when held in a single run, whose hold step the console does not read, or when
  no plan graded the issue), with `notes_posted` true when the plan has notes and not false
  otherwise. Any other result leaves the issue as the label left it.
- `DONE` is final. A `QUEUED` step changes only an issue that is new or still `QUEUED`.

`configured_branch_pattern(repo)` is the service's default source of that pattern: the project
contract's `vcs.branch_pattern` through `resolve_project.resolve`, or None when it does not resolve.

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

Run summary: `run_summary(issues, moved)` reads a run as one sentence, `"<n> issue(s) in delivery:
<count> <stage>, ..., <moved>"`, the stages in `SUMMARY_ORDER` with a non-zero count, `moved` being
the moved text; a run with no issue reads `"No issue in delivery yet, <moved>"`. It names stages,
never issue numbers.
"""


import functools
import json
import os
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from stat import S_ISREG
from typing import BinaryIO, Callable, Iterable, Mapping

from agent_tools.console.event_log import Event
from agent_tools.project_contract import resolve_project

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


# A path that holds a NUL raises ValueError from the os calls: it cannot exist, so it is absent.
_ABSENT = (FileNotFoundError, NotADirectoryError, ValueError)


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
        except _ABSENT:
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


def _children(directory: Path) -> list[os.DirEntry] | None:
    """The entries of a directory; None when it is absent. Any other `OSError` propagates."""
    try:
        with os.scandir(directory) as entries:
            return sorted(entries, key=lambda entry: entry.name)
    except _ABSENT:
        return None


def run_journals(projects_dirs: Iterable[Path], session_id: str) -> list[Path] | Unreadable:
    """The `journal.jsonl` files of a session's runs, under every `projects` directory, sorted.

    The tree is `<projects>/<slug>/<session_id>/subagents/workflows/<run_id>/journal.jsonl`, walked
    with `os.scandir` per level and `os.stat` on each journal. A branch that is absent
    (`FileNotFoundError`, `NotADirectoryError`, or `ValueError` for a session id holding a NUL, which
    names no path) contributes nothing; any other `OSError` makes the
    whole answer `Unreadable`, because a listing that failed cannot confirm what is absent. Never
    raises.
    """
    found: list[Path] = []
    try:
        for projects in projects_dirs:
            for slug in _children(Path(projects)) or ():
                workflows = Path(slug.path) / session_id / "subagents" / "workflows"
                for run in _children(workflows) or ():
                    journal = Path(run.path) / JOURNAL_NAME
                    try:
                        regular = S_ISREG(os.stat(journal).st_mode)
                    except _ABSENT:
                        continue
                    if regular:
                        found.append(journal)
    except OSError as error:
        return Unreadable(_reason(error))
    return sorted(found)


def final_record(journal: Path) -> Path:
    """`<session dir>/workflows/<run_id>.json`, which exists only once the run has ended."""
    return journal.parents[3] / "workflows" / f"{journal.parent.name}.json"


def has_final_record(journal: Path) -> bool | Unreadable:
    """Whether the run has ended; `Unreadable` (not False) when that cannot be told. Never raises."""
    try:
        os.stat(final_record(journal))
    except _ABSENT:
        return False
    except OSError as error:
        return Unreadable(_reason(error))
    return True


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
    (PLANNING, r"owner-answer|amend|renew-plan|renew-amend|plan|plan-revise|plan-rules-revise|plan-branch-revise|plan-task-revise"),
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
    (VERIFYING, r"verify|verify-\d+|verify-rerun-\d+|verify-fix-\d+|verify-fix-review-\d+|ws-check-\d+"),
    (
        LANDING,
        r"pr|hold|merge|close-out|land-unlock|fix-ci|fix-ci-review|land-lock-\d+|land-relock-\d+|land-push-\d+|checks-\d+"
        r"|sync-\d+|sync-resolve-\d+|sync-review-\d+|fix-sync-\d+|fix-sync-review-\d+",
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
    # land-open opens the PR of an issue that waits in the land queue: no stage of its own, so the issue keeps the one it has.
    (QUEUED, r"facts-(\d+)|land-open-(\d+)"),
    (PLANNING, r"acquire-(\d+)|readopt-(\d+)|readopt-push-(\d+)"),
    (WORKING, r"release-(\d+)|recover-end-(\d+)|ask-(\d+)|settle-(\d+)"),
    (LANDING, r"close-out-(\d+)|train-pr-(\d+)|land-[a-z]+(?:-[a-z]+)*-(\d+)(?:-\d+)?"),
)


# What both programs append to the label of a review step they run once more after an unusable reply.
RERUN_SUFFIX = "-again"


def _group(match: re.Match) -> int | None:
    found = next((g for g in match.groups() if g is not None), None)
    return None if found is None else int(found)


def classify(label: str, *, batch: bool) -> Step | None:
    """The step a label stands for in the owner table or, with `batch`, the batch table; None if unknown."""
    label = label.removesuffix(RERUN_SUFFIX)
    for stage, pattern in BATCH_LABELS if batch else OWNER_LABELS:
        match = re.fullmatch(pattern, label)
        if match is None:
            continue
        number = _group(match)
        if batch:
            return Step(stage, issue=number)
        return Step(stage, task=number)
    return None


@dataclass(frozen=True)
class Grading:
    """What a plan's acceptance criteria require of the close-out: `held` (an evidence or human criterion) and `notes`."""

    held: bool
    notes: bool


def grading_of(acceptance: object) -> Grading | None:
    """The grading of a plan's non-empty `acceptance` list; None for anything else."""
    if not isinstance(acceptance, list) or not acceptance:
        return None
    kinds = [item.get("kind") for item in acceptance if isinstance(item, dict)]
    return Grading(any(k in ("evidence", "human") for k in kinds), "note" in kinds)


def closed_out(result: object, grading: Grading | None = None, batch: bool = False) -> bool:
    """True for a close-out result showing the close-out finished and left the issue as the programs require."""
    if not isinstance(result, dict) or result.get("released") is not True or result.get("decision_ended") is not True:
        return False
    if grading is None or (grading.held and not batch):
        states = ("OPEN", "CLOSED")
    else:
        states = ("OPEN",) if grading.held else ("CLOSED",)
    posted = result.get("notes_posted")
    notes_ok = posted is True if grading is not None and grading.notes else posted is not False
    return result.get("issue_state") in states and notes_ok


_SLUG_CLASS = "[a-z0-9][a-z0-9-]*"
_PLACEHOLDERS = re.compile(r"(<num>|<slug>)")


@functools.lru_cache(maxsize=64)
def _branch_matcher(pattern: str) -> re.Pattern[str] | None:
    if "<num>" not in pattern or "<num><slug>" in pattern or "<slug><num>" in pattern:
        return None
    seen = False
    parts = []
    for part in _PLACEHOLDERS.split(pattern):
        if part == "<num>":
            parts.append("(?P=n)" if seen else "(?P<n>\\d+)")
            seen = True
        else:
            parts.append(_SLUG_CLASS if part == "<slug>" else re.escape(part))
    return re.compile("".join(parts))


def branch_issue(pattern: str | None, branch: str) -> int | None:
    """The issue number `branch` carries under the project's branch `pattern`; None when it does not fit."""
    matcher = None if pattern is None else _branch_matcher(pattern)
    match = None if matcher is None else matcher.fullmatch(branch)
    return None if match is None else int(match.group("n"))


def configured_branch_pattern(repo: str) -> str | None:
    """The `vcs.branch_pattern` the project contract of the repository at `repo` resolves to; None if it does not."""
    try:
        pattern = resolve_project.resolve(repo)["bindings"]["vcs"]["branch_pattern"]
    except Exception:
        return None
    return pattern if isinstance(pattern, str) else None


_PLAN_LABELS = ("plan", "plan-revise", "plan-rules-revise", "plan-branch-revise", "plan-task-revise")
_BATCH_CLOSE_OUT = re.compile(r"close-out-(\d+)")


class _Owner:
    """A run's own labels, or one child's: its issue once its setup result names it, and what waits for that."""

    def __init__(self) -> None:
        self.issue: int | None = None
        self.waiting: list[tuple[str, object]] = []


class RunFold:
    def __init__(self, branch_pattern: str | None = None) -> None:
        self.branch_pattern = branch_pattern
        self._gradings: dict[int, Grading] = {}
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
            if match is not None:
                issue = int(match.group(1))
                if closed_out(result, self._gradings.get(issue), True):
                    self._done(issue)
            return
        owner = self._owner(key)
        if label == "setup":
            branch = result.get("branch") if isinstance(result, dict) else None
            issue = branch_issue(self.branch_pattern, branch) if isinstance(branch, str) else None
            if issue is not None:
                self._name(owner, issue)
        elif label in _PLAN_LABELS:
            if isinstance(result, dict) and result.get("status") == "planned":
                tasks = result.get("tasks")
                if isinstance(tasks, list) and tasks:
                    self._effect(owner, "tasks", len(tasks))
                grading = grading_of(result.get("acceptance"))
                if grading is not None:
                    self._effect(owner, "grading", grading)
        elif label == "close-out":
            self._effect(owner, "close-out", result)

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
        elif kind == "grading":
            self._gradings[owner.issue] = value
        elif closed_out(value, self._gradings.get(owner.issue)):
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


SUMMARY_ORDER = (DONE, LANDING, VERIFYING, FINAL_REVIEW, BUILDING, PLAN_REVIEW, PLANNING,
                 WORKING, QUEUED)


def run_summary(issues: Sequence[IssueStage], moved: str) -> str:
    """One sentence for a run: how many issues, how many at each stage, and `moved`."""
    if not issues:
        return f"No issue in delivery yet, {moved}"
    counts = Counter(i.stage for i in issues)
    parts = ", ".join(f"{counts[stage]} {stage}" for stage in SUMMARY_ORDER if counts[stage])
    n = len(issues)
    return f"{n} {'issue' if n == 1 else 'issues'} in delivery: {parts}, {moved}"


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
