"""The console's movement readers (#1110): what a project's pull requests, branches and release
transactions did lately, and the fold that keeps the last time each moved. Nothing here reads a
clock: the caller passes `now_ms`. `read_pulls` takes the `gh` call and a cancellation test as
arguments; `branch_updates` and `release_reading` only read files, start no process and take no lock.

Pull requests. One GraphQL query (`PULLS_QUERY`, `pulls_argv`) asks for the `MAX_PULLS` most recently
updated open pull requests with the head commit's `committedDate` and its check contexts counted by state. `read_pulls`
makes exactly one `call`, with `pulls_argv(slug)`, and asks `cancelled()` before it; when cancelled it
raises `ForgeError("cancelled")` and makes no call. With no `call` the transport is
`forge_api.gh_json(argv, cancelled=cancelled)`, which kills the `gh` process group in flight as soon
as `cancelled()` is true and raises `ForgeError("cancelled")`. A pull request is `running` when the head commit has a `CheckRun` counted
in a state of `RUNNING_CHECKS` (queued, in progress or pending) or a `StatusContext` counted in a state
of `RUNNING_STATUSES`, however many other contexts it has, since the counts cover every context and not
a first page of them. A check in `WAITING` is held on a person (a deployment environment's reviewer),
not running CI, so it does not count (ADR-console-049 D6); a null `statusCheckRollup` or no commit is not running. A pull's `issues` are
`deliveries.branch_issue(pattern, headRefName)` (when not None) united with `body_issues(body)`, which
matches `(?<![\\w/])#(\\d+)\\b`, so `owner/repo#6` and `abc#6` name nothing. `committed_ms` is the head
commit's `committedDate` in epoch milliseconds, None with no commit. An answer of another shape raises
`ForgeError("payload_invalid")`.

Branches. `branch_updates` reads only `<git_common_dir(root)>/logs/refs/heads/**` files (the branch
name is the path relative to that directory with `/`), keeps a branch only when
`deliveries.branch_issue(pattern, branch)` is not None, and takes the unix seconds of the last complete
reflog line in the file's final `REFLOG_TAIL_BYTES` bytes, times 1000; per issue the newest wins. An
unreadable file or an unparseable last line is skipped; no checkout or pattern None reads `()`.

Release. `release_reading` looks only at the child directories of
`<git_common_dir(root)>/agent-release/store` whose name is `transaction_storage.is_id`; any other
entry (`receipts/`, `creation-keys/`) is ignored, and a transaction directory with no `state.json` is
skipped silently (it is being created). A `state.json` that cannot be read, does not parse as a JSON
object, or whose `state` is not a str in `transaction_history.STATES` is an invalid reading: its id goes
into the returned invalid ids and it is never in progress, so it refreshes no movement. A valid state is
in progress when it is not in `TERMINALS` and not `HELD_FOR_A_PERSON`. No store reads `(False, ())`.

The fold. `merged` keys pull requests by number and returns them ascending by number. With `pulls` None
(a failed read) the result keeps `previous.pulls` and `previous.read_ms` unchanged. With `pulls` given,
`read_ms = now_ms`, and each read pull becomes a `PullMovement` with its read `issues` and
`committed_ms` (the larger of it and the previous pull's, so a rewritten head never moves it back,
as the branch fold keeps the larger time) and `running_ms = now_ms` when it is `running`, else the
`running_ms` of the previous pull with the same number (None if none). A previous pull absent from the read (merged, closed, or past
the newest `MAX_PULLS`) is kept exactly as it was, its times never refreshed, so its last movement ages
out under the quiet window like a run that ended. `branches` is the union of `previous.branches` and
`local.branches` by issue, the larger time winning, ascending by issue: a deleted branch keeps its last
time, never refreshed. `release_ms = now_ms` when `local.release`, else `previous.release_ms`. Nothing
is pruned: the service drops a project's whole reading once no sprint of it runs.
"""

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_tools.claims import owner_actions
from agent_tools.console.deliveries import branch_issue
from agent_tools.release.transaction_history import STATES, TERMINALS
from agent_tools.release.transaction_storage import is_id
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

MAX_PULLS = 50
PULLS_QUERY = """query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number
        headRefName
        body
        commits(last: 1) {
          nodes {
            commit {
              committedDate
              statusCheckRollup {
                contexts(first: 1) {
                  checkRunCountsByState { state count }
                  statusContextCountsByState { state count }
                }
              }
            }
          }
        }
      }
    }
  }
}"""
RUNNING_CHECKS = frozenset({"QUEUED", "IN_PROGRESS", "PENDING"})
RUNNING_STATUSES = frozenset({"PENDING"})
HELD_FOR_A_PERSON = "attention_required"
REFLOG_TAIL_BYTES = 4096

_BODY_ISSUE = re.compile(r"(?<![\w/])#(\d+)\b")
_REFLOG_TIME = re.compile(r"(\d+) [+-]\d{4}$")


@dataclass(frozen=True)
class PullRequest:
    number: int
    issues: frozenset[int]
    running: bool
    committed_ms: int | None


@dataclass(frozen=True)
class LocalReading:
    branches: tuple[tuple[int, int], ...]
    release: bool
    invalid: tuple[str, ...] = ()


@dataclass(frozen=True)
class PullMovement:
    number: int
    issues: frozenset[int]
    running_ms: int | None
    committed_ms: int | None


@dataclass(frozen=True)
class ProjectMovement:
    pulls: tuple[PullMovement, ...] = ()
    read_ms: int | None = None
    branches: tuple[tuple[int, int], ...] = ()
    release_ms: int | None = None


def pulls_argv(slug: str) -> list[str]:
    owner, name = slug.split("/", 1)
    return ["api", "graphql", "-f", f"query={PULLS_QUERY}", "-f", f"owner={owner}",
            "-f", f"name={name}"]


def body_issues(body: str) -> frozenset[int]:
    return frozenset(int(number) for number in _BODY_ISSUE.findall(body))


def _invalid(detail: str) -> ForgeError:
    return ForgeError("payload_invalid", detail)


def _list(value: object, what: str) -> list:
    if not isinstance(value, list):
        raise _invalid(f"{what} is not a list")
    return value


def _dict(value: object, what: str) -> dict:
    if not isinstance(value, dict):
        raise _invalid(f"{what} is not an object")
    return value


def _committed_ms(text: object) -> int:
    if not isinstance(text, str):
        raise _invalid("committedDate is not a string")
    try:
        moment = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        raise _invalid("committedDate is not a time") from None
    if moment.tzinfo is None:
        raise _invalid("committedDate has no zone")
    return int(moment.timestamp() * 1000)


def _counts(value: object, what: str) -> dict[str, int]:
    counted: dict[str, int] = {}
    for entry in _list(value, what):
        entry = _dict(entry, what)
        state, count = entry.get("state"), entry.get("count")
        if not isinstance(state, str) or type(count) is not int or count < 0:
            raise _invalid(f"{what} has an entry without a state and a count")
        counted[state] = counted.get(state, 0) + count
    return counted


def _running(contexts: dict) -> bool:
    checks = _counts(contexts.get("checkRunCountsByState"), "checkRunCountsByState")
    statuses = _counts(contexts.get("statusContextCountsByState"), "statusContextCountsByState")
    return (any(checks.get(state) for state in RUNNING_CHECKS)
            or any(statuses.get(state) for state in RUNNING_STATUSES))


def _pull(node: object, pattern: str | None) -> PullRequest:
    node = _dict(node, "pull request")
    number = node.get("number")
    if type(number) is not int or number < 1:
        raise _invalid("pull request number is not a positive integer")
    head, body = node.get("headRefName"), node.get("body")
    if not isinstance(head, str) or not (body is None or isinstance(body, str)):
        raise _invalid("pull request head or body is not text")
    issues = set(body_issues(body or ""))
    named = branch_issue(pattern, head)
    if named is not None:
        issues.add(named)
    commits = _list(_dict(node.get("commits"), "commits").get("nodes"), "commits.nodes")
    committed: int | None = None
    running = False
    if commits:
        commit = _dict(_dict(commits[0], "commit node").get("commit"), "commit")
        committed = _committed_ms(commit.get("committedDate"))
        rollup = commit.get("statusCheckRollup")
        if rollup is not None:
            contexts = _dict(_dict(rollup, "statusCheckRollup").get("contexts"), "contexts")
            running = _running(contexts)
    return PullRequest(number, frozenset(issues), running, committed)


def pulls_from_answer(answer: object, pattern: str | None) -> tuple[PullRequest, ...]:
    """The open pull requests of one answer, ascending by number; raises `ForgeError`."""
    data = _dict(_dict(answer, "answer").get("data"), "data")
    repository = _dict(data.get("repository"), "repository")
    nodes = _list(_dict(repository.get("pullRequests"), "pullRequests").get("nodes"),
                  "pullRequests.nodes")
    return tuple(sorted((_pull(node, pattern) for node in nodes), key=lambda p: p.number))


def read_pulls(slug: str, pattern: str | None, *,
               call: Callable[[list[str]], Any] | None = None,
               cancelled: Callable[[], bool] = lambda: False) -> tuple[PullRequest, ...]:
    """The open pull requests of one repository in one call; raises `forge_api.ForgeError`. With no
    `call` the production transport runs, which ends the call in flight once `cancelled()` is true."""
    if cancelled():
        raise ForgeError("cancelled")
    if call is None:
        def call(argv: list[str]) -> Any:
            return forge_api.gh_json(argv, cancelled=cancelled)
    return pulls_from_answer(call(pulls_argv(slug)), pattern)


def _last_reflog_ms(path: Path) -> int | None:
    try:
        with open(path, "rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - REFLOG_TAIL_BYTES))
            tail = handle.read()
        lines = tail.decode("utf-8", errors="replace").split("\n")[:-1]
    except OSError:
        return None
    for line in reversed(lines):
        if line:
            match = _REFLOG_TIME.search(line.split("\t", 1)[0])
            return None if match is None else int(match.group(1)) * 1000
    return None


def branch_updates(root: str, pattern: str | None) -> tuple[tuple[int, int], ...]:
    """`(issue, newest branch update ms)` of the branches the reflogs name, ascending by issue."""
    common = owner_actions.git_common_dir(root)
    if common is None or pattern is None:
        return ()
    heads = common / "logs" / "refs" / "heads"
    newest: dict[int, int] = {}
    for directory, _, files in os.walk(heads):
        for name in files:
            path = Path(directory, name)
            issue = branch_issue(pattern, path.relative_to(heads).as_posix())
            if issue is None:
                continue
            moved = _last_reflog_ms(path)
            if moved is not None:
                newest[issue] = max(moved, newest.get(issue, moved))
    return tuple(sorted(newest.items()))


def _state_of(path: Path) -> str | None:
    """The known state in `path`, or None when it cannot be read as one."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    state = document.get("state") if isinstance(document, dict) else None
    return state if isinstance(state, str) and state in STATES else None


def release_reading(root: str) -> tuple[bool, tuple[str, ...]]:
    """Whether a release transaction is in progress, and the ids whose state is unreadable."""
    common = owner_actions.git_common_dir(root)
    if common is None:
        return (False, ())
    store = common / "agent-release" / "store"
    try:
        names = sorted(entry for entry in os.listdir(store) if is_id(entry))
    except OSError:
        return (False, ())
    live = False
    invalid: list[str] = []
    for name in names:
        path = store / name / "state.json"
        if not (store / name).is_dir() or not os.path.lexists(path):
            continue
        state = _state_of(path)
        if state is None:
            invalid.append(name)
        elif state not in TERMINALS and state != HELD_FOR_A_PERSON:
            live = True
    return (live, tuple(invalid))


def read_local(root: str, pattern: str | None) -> LocalReading:
    return LocalReading(branch_updates(root, pattern), *release_reading(root))


def merged(previous: ProjectMovement | None, pulls: tuple[PullRequest, ...] | None,
           now_ms: int, local: LocalReading) -> ProjectMovement:
    """Fold one reading into the last: every time kept is the last time its signal was seen."""
    before = previous or ProjectMovement()
    if pulls is None:
        kept, read_ms = before.pulls, before.read_ms
    else:
        old = {pull.number: pull for pull in before.pulls}
        fresh = {}
        for pull in pulls:
            seen = old.get(pull.number)
            running_ms = now_ms if pull.running else (None if seen is None else seen.running_ms)
            committed = pull.committed_ms
            if seen is not None and seen.committed_ms is not None:
                committed = seen.committed_ms if committed is None else max(committed, seen.committed_ms)
            fresh[pull.number] = PullMovement(pull.number, pull.issues, running_ms, committed)
        kept = tuple(sorted({**old, **fresh}.values(), key=lambda p: p.number))
        read_ms = now_ms
    branches = dict(before.branches)
    for issue, moved in local.branches:
        branches[issue] = max(moved, branches.get(issue, moved))
    return ProjectMovement(kept, read_ms, tuple(sorted(branches.items())),
                           now_ms if local.release else before.release_ms)
