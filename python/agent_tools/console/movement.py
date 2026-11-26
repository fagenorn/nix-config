"""The console's movement readers (#1110): what a project's pull requests, branches and release
transactions did lately, and the fold that keeps the last time each moved. Nothing here reads a
clock: the caller passes `now_ms`. `read_pulls` takes the `gh` call and a cancellation test as
arguments; `branch_updates` and `release_reading` only read files, start no process and take no lock.

Pull requests. One GraphQL query (`PULLS_QUERY`, `pulls_argv`) asks for the `MAX_PULLS` most recently
updated open pull requests with the head commit's `committedDate` and its check contexts counted by state, and
each one's `headRefOid`, `baseRefName` and `isCrossRepository`. The land lock is read by a second call, REST
`git/matching-refs/agent-locks/land` (`locks_argv`), because GraphQL does not list `refs/agent-locks/`.
`locks_from_answer` maps base branch name to lock oid from every item whose `ref` starts with
`forge_land_lock.LOCK_PREFIX` (the branch is the rest of the ref); `land-beat/` refs are ignored there and
`land-wait/` refs are read by `waiters_from_answer` (below); an answer that is not a list, or an item that is not an object with a str `ref` and an object
`object` holding a str `sha`, raises `ForgeError("payload_invalid")`. A pull request is `holding` the lock
(forge_land_lock D2) when the lock of its base branch is at its head oid, or, being a release pull request,
when it is not cross-repository and the lock of its own head branch is at its head oid: a release's head is
the locked integration branch itself, whatever its base, and a fork's branch of that name never holds. A
node whose `headRefOid` or `baseRefName` is not a str or whose `isCrossRepository` is not a bool is
payload_invalid. Its place in the queue: `waiters_from_answer` maps base branch to the `(since, pr)`
pairs of every item whose ref starts with `forge_land_lock.WAIT_PREFIX`, the branch being the text up to the
last `/` and the last segment matching `WAITER` entirely (others are skipped, shape errors as for the
locks). A pull request's `queue_position` is its 1-based place among the pull requests of one read with the
same base that have a registration and are not `holding`, ordered by `(smallest since, number)`; it is
None otherwise, and a holder never has one. Display only: nothing is written and no call is added, the
registrations come from the same answer. `read_pulls` makes two `call`s, `pulls_argv(slug)` then `locks_argv(slug)`, and asks
`cancelled()` before each; when cancelled it raises `ForgeError("cancelled")` before that call, and a failed
lock read fails the whole read. With no `call` the transport is
`forge_api.gh_json(argv, cancelled=cancelled)`, which kills the `gh` process group in flight as soon
as `cancelled()` is true and raises `ForgeError("cancelled")`. A pull request is `running` when the head commit has a `CheckRun` counted
in a state of `RUNNING_CHECKS` (queued, in progress or pending) or a `StatusContext` counted in a state
of `RUNNING_STATUSES`, however many other contexts it has, since the counts cover every context and not
a first page of them. A check in `WAITING` is held on a person (a deployment environment's reviewer),
not running CI, so it does not count (ADR-console-050); a null `statusCheckRollup` or no commit is not running. A pull's `issues` are
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

The fold. `lock_held` is `any(p.holding for p in pulls)` for a read and the previous `lock_held` when
`pulls` is None. In a good read each issue of a read pull with `holding` that is in `live` (the issues whose delivery run is in a session not ended; None
gates nothing), and each issue of `locking` (the issues whose journal sits at a lock step) when that read's
`lock_held` is true, is seen: a run that died holding the lock leaves its pull request holding, so its issues
are seen no more and the sprint ages out to may be stuck (ADR-console-050); its `locks` time
becomes `max(now_ms, kept)`; an issue not seen keeps its time, never refreshed; `locks` is ascending by
issue. A failed read sees nothing and keeps `locks` unchanged whatever `locking` holds, so a lock time ages
out after the quiet window like every signal (ADR-console-050), a journal lock step's included. `positions` is each issue of a read pull with a `queue_position` mapped to its smallest, ascending by issue; a good read
replaces it and a failed read keeps it. `merged` keys pull requests by number and returns them ascending by number. With `pulls` None
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

Sessions. Two more readers say whether a sprint's sessions are working (#1185). `session_output_ms` is
the newest write among a session's transcript files: `<projects>/<slug>/<session_id>.jsonl` and every
`.jsonl` anywhere under `<projects>/<slug>/<session_id>/` (its subagents and workflow agents), over every
slug directory of every projects directory; None when there is none, and an absent or unreadable path is
skipped, never raised. An id that is empty, `.`, `..` or holds `/` or NUL names no path. `process_table`
reads `/proc` once (None without procfs): per all-digit entry its parent pid, start time and CPU in
milliseconds (utime + stime + cutime + cstime), parsed after the LAST `)` of `stat` as `sessions.py` does.
`descendant_cpu` lists the CPU of every process whose parent chain reaches a session's pid, NEVER the
session process itself: a background session's own process burns CPU while idle, so only the tool
shells and the processes they start say it is running something. `read_sessions` reads the table once
per call and returns one `SessionReading` per target, ascending by session id, with `cpu` None when
the table, the pid or the pid's entry is missing.

The session fold. `merged` also folds `local.sessions` into one `SessionMovement` per association of
a session with a sprint, at `sessions_ms` (the time the caller started the read) or else `now_ms`.
`output_ms` is the larger of the read and the last one, never moving back. A reading of a manager session carries `replies`, the `(sprint, idle-nudge time)` of
the sprints it manages that were nudged: an output or a CPU reading for such a sprint that falls from the
nudge to `NUDGE_REPLY_MS` (five minutes) after it is the manager's reply, so it is never folded and the
last qualifying time stays (a reply never erases earlier movement; ADR-console-042). `check_ms` is that time
when the CPU used since the last reading, summed per process key `(pid, start)` (a process new since
then counts all of its CPU), is at least `CHECK_CPU_MS` (one second: a watcher loop idling at a few
milliseconds per poll must not read as a running check), and with no earlier table to compare (the
first reading, or after a None) it moves nothing. Times are kept per association, not per session:
an association the reading does not carry is kept exactly, so a session that moved on to another
sprint never refreshes the times of the one it left (ADR-console-050). Sessions fold whether
`pulls` is None or not.

Held peer messages (#1229, ADR-console-042). `session_held` reads a
session's own transcript (`<projects>/<slug>/<session_id>.jsonl`, never its subagents') and is true
when its last peer-message record is a held one: a `system` line whose content starts `Held peer
message` and says `not delivered` (the client holds a message whose sender's permission mode class
differs, until a person approves it at the terminal). A record whose `origin.kind` is `peer`, on the
line or in its `attachment`, is a delivered message and clears it; a line that does not parse is
skipped. A transcript only grows, so each file is read once from its start and afterwards only from
where the last reading stopped (`_HELD_SEEN`, per file identity, through its last complete line): a held
marker stays in the reading however much follows it, and a poll costs what was appended. A file that
shrank or was replaced is read again from its start. `SessionReading.held` is that reading and the fold keeps the latest one in
`SessionMovement.held`, never the largest. The flag moves no sprint and names no wait. A
`SessionTarget` with `held_only` (a sprint's known manager session that is absent or ended, so a console
restart finds its transcript still ending in a held message) reads only that flag: no output time, no
CPU, so it moves nothing.

Turn time (#1424). `transcript_turn_ms` is the newest `timestamp` of a `user` or `assistant` record in a
session's own transcript and in every `.jsonl` anywhere under `<projects>/<slug>/<session_id>/` (its
subagents and workflow agents; a workflow agent's prompt carries the manager's session id while the
manager's own transcript gains nothing until the `Workflow` call returns), over every slug directory
of every projects directory, with the same id guard as `session_output_ms`. `system`, `progress` and
every other type do not count; a line that does not parse (a record nested too deeply included), is not an object, or has no tz-aware ISO
`timestamp` is skipped, as is an absent or unreadable file; None when no record counts. Each file is
read incrementally like the held reading (`_TURN_SEEN`, per file identity, through its last complete
line), so a poll costs what was appended; a file that shrank or was replaced is read again from its
start, and an incomplete last line is read but not kept. The service uses it to clear a wait.

Issue titles (#1793). `read_titles` asks the tracker what its issues are called, so a sprint's now line can
name the work; no title is read from a report. One GraphQL query (`titles_query`, `titles_argv`) holds one
`issueOrPullRequest(number: n)` alias `i<n>` per number, in the order given, and `titles_from_answer` reads
`data.repository.i<n>` for each: a null or absent node is skipped (the number names nothing there), a node that
is not an object, whose `number` is not that int or whose `title` is not a str, or a `data` or `repository`
that is not an object, is `ForgeError("payload_invalid")`; a title is collapsed to one line (whitespace runs
become one space) and an empty one is skipped. `read_titles` makes one call of at most `MAX_TITLES_PER_CALL`
numbers, the smallest distinct ones the query can name (`MAX_QUERY_NUMBER`, a signed 32-bit `Int`), ascending; `gh` fails the whole call when one number does not resolve, so a `gh_failed` that is not a transport error is asked again in halves, and a number that fails alone stays untitled; no numbers makes no call, and `cancelled()` true before the
call raises `ForgeError("cancelled")`; with no `call` the transport is `forge_api.gh_json(argv, cancelled=...)`.
`titles_batch(issues, known, asked)` picks which numbers the next poll asks: the outstanding ones (not
`known`) not yet `asked` in this round, the first `MAX_TITLES_PER_CALL` of them in ascending order; when every
outstanding number was asked, a new round starts from the smallest. It also returns the new asked set, so a
number the tracker did not answer for never blocks the numbers behind it, and is asked again in the next
round. `titles_plan` applies that to the report issues of each project's sprints that have not ended. Nothing here is logged or written.
"""

import json
import os
import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_tools.claims import owner_actions
from agent_tools.claims.forge_land_lock import LOCK_PREFIX, WAIT_PREFIX, WAITER
from agent_tools.console import sprints
from agent_tools.console.deliveries import branch_issue
from agent_tools.console.sessions import at_ms
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
        headRefOid
        baseRefName
        isCrossRepository
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
HELD_PREFIX = "Held peer message"
HELD_SUFFIX = "not delivered"
CHECK_CPU_MS = 1000
# A nudged idle manager answers the nudge; the answer is not the sprint moving. Equal to
# `idle.IDLE_AFTER_MS`, defined here because `idle` imports `view`, which imports this module (#1185).
NUDGE_REPLY_MS = 300_000

_BODY_ISSUE = re.compile(r"(?<![\w/])#(\d+)\b")
_REFLOG_TIME = re.compile(r"(\d+) [+-]\d{4}$")


@dataclass(frozen=True)
class PullRequest:
    number: int
    issues: frozenset[int]
    running: bool
    committed_ms: int | None
    holding: bool = False
    queue_position: int | None = None


@dataclass(frozen=True)
class LocalReading:
    branches: tuple[tuple[int, int], ...]
    release: bool
    invalid: tuple[str, ...] = ()
    sessions: tuple["SessionReading", ...] = ()
    sessions_ms: int | None = None


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
    locks: tuple[tuple[int, int], ...] = ()
    lock_held: bool = False
    sessions: tuple["SessionMovement", ...] = ()
    positions: tuple[tuple[int, int], ...] = ()


Cpu = tuple[tuple[tuple[int, str], int], ...]


@dataclass(frozen=True)
class ProcessStat:
    ppid: int
    start: str
    cpu_ms: int


@dataclass(frozen=True)
class SessionTarget:
    session_id: str
    pid: int | None
    sprints: frozenset[str]
    replies: tuple[tuple[str, int], ...] = ()
    held_only: bool = False


@dataclass(frozen=True)
class SessionReading:
    session_id: str
    sprints: frozenset[str]
    output_ms: int | None
    cpu: Cpu | None
    replies: tuple[tuple[str, int], ...] = ()
    held: bool = False


@dataclass(frozen=True)
class SessionMovement:
    session_id: str
    sprint_id: str
    output_ms: int | None
    check_ms: int | None
    cpu: Cpu | None
    read_ms: int | None = None
    held: bool = False


def pulls_argv(slug: str) -> list[str]:
    owner, name = slug.split("/", 1)
    return ["api", "graphql", "-f", f"query={PULLS_QUERY}", "-f", f"owner={owner}",
            "-f", f"name={name}"]


def locks_argv(slug: str) -> list[str]:
    return ["api", f"repos/{slug}/git/matching-refs/agent-locks/land"]


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


def locks_from_answer(answer: object) -> dict[str, str]:
    """Base branch name -> lock oid of one matching-refs answer; raises `ForgeError`."""
    held: dict[str, str] = {}
    for item in _list(answer, "locks answer"):
        item = _dict(item, "lock ref")
        ref, target = item.get("ref"), _dict(item.get("object"), "lock ref object")
        sha = target.get("sha")
        if not isinstance(ref, str) or not isinstance(sha, str):
            raise _invalid("lock ref has no ref and sha text")
        if ref.startswith(LOCK_PREFIX):
            held[ref[len(LOCK_PREFIX):]] = sha
    return held


def waiters_from_answer(answer: object) -> dict[str, tuple[tuple[int, int], ...]]:
    """Base branch name -> the `(since, pr)` of its land-wait registrations in one matching-refs
    answer; raises `ForgeError` as `locks_from_answer` does."""
    found: dict[str, list[tuple[int, int]]] = {}
    for item in _list(answer, "locks answer"):
        item = _dict(item, "lock ref")
        ref, target = item.get("ref"), _dict(item.get("object"), "lock ref object")
        if not isinstance(ref, str) or not isinstance(target.get("sha"), str):
            raise _invalid("lock ref has no ref and sha text")
        if not ref.startswith(WAIT_PREFIX):
            continue
        branch, slash, name = ref[len(WAIT_PREFIX):].rpartition("/")
        match = WAITER.fullmatch(name)
        if slash and match:
            found.setdefault(branch, []).append((int(match.group(1)), int(match.group(2))))
    return {branch: tuple(pairs) for branch, pairs in found.items()}


def _pull(node: object, pattern: str | None, held: Mapping[str, str]) -> PullRequest:
    node = _dict(node, "pull request")
    number = node.get("number")
    if type(number) is not int or number < 1:
        raise _invalid("pull request number is not a positive integer")
    head, body = node.get("headRefName"), node.get("body")
    if not isinstance(head, str) or not (body is None or isinstance(body, str)):
        raise _invalid("pull request head or body is not text")
    oid, base, cross = node.get("headRefOid"), node.get("baseRefName"), node.get("isCrossRepository")
    if not isinstance(oid, str) or not isinstance(base, str) or type(cross) is not bool:
        raise _invalid("pull request head oid, base or fork flag is of another type")
    holding = held.get(base) == oid or (not cross and held.get(head) == oid)
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
    return PullRequest(number, frozenset(issues), running, committed, holding)


def pulls_from_answer(answer: object, pattern: str | None,
                      locks: Mapping[str, str] | None = None,
                      waiters: Mapping[str, Iterable[tuple[int, int]]] | None = None,
                      ) -> tuple[PullRequest, ...]:
    """The open pull requests of one answer, ascending by number, each with its `queue_position`
    among the registered waiters of its base; raises `ForgeError`."""
    held = locks or {}
    data = _dict(_dict(answer, "answer").get("data"), "data")
    repository = _dict(data.get("repository"), "repository")
    nodes = _list(_dict(repository.get("pullRequests"), "pullRequests").get("nodes"),
                  "pullRequests.nodes")
    pulls = sorted(((_pull(node, pattern, held), node["baseRefName"]) for node in nodes),
                   key=lambda pair: pair[0].number)
    since: dict[tuple[str, int], int] = {}
    for base, pairs in (waiters or {}).items():
        for moment, number in pairs:
            since[(base, number)] = min(moment, since.get((base, number), moment))
    queue: dict[str, list[tuple[int, int]]] = {}
    for pull, base in pulls:
        if not pull.holding and (base, pull.number) in since:
            queue.setdefault(base, []).append((since[(base, pull.number)], pull.number))
    place = {(base, number): at for base, waiting in queue.items()
             for at, (_, number) in enumerate(sorted(waiting), 1)}
    return tuple(replace(pull, queue_position=place.get((base, pull.number)))
                 for pull, base in pulls)


def read_pulls(slug: str, pattern: str | None, *,
               call: Callable[[list[str]], Any] | None = None,
               cancelled: Callable[[], bool] = lambda: False) -> tuple[PullRequest, ...]:
    """The open pull requests of one repository and the land lock, in two calls; raises
    `forge_api.ForgeError`. With no `call` the production transport runs, which ends the call in flight
    once `cancelled()` is true."""
    if call is None:
        def call(argv: list[str]) -> Any:
            return forge_api.gh_json(argv, cancelled=cancelled)
    if cancelled():
        raise ForgeError("cancelled")
    first = call(pulls_argv(slug))
    if cancelled():
        raise ForgeError("cancelled")
    refs = call(locks_argv(slug))
    return pulls_from_answer(first, pattern, locks_from_answer(refs), waiters_from_answer(refs))


MAX_TITLES_PER_CALL = 100
MAX_QUERY_NUMBER = 2 ** 31 - 1


def titles_query(numbers: Sequence[int]) -> str:
    lines = [f"    i{n}: issueOrPullRequest(number: {n}) "
             "{ ... on Issue { number title } ... on PullRequest { number title } }" for n in numbers]
    return ("query($owner: String!, $name: String!) {\n  repository(owner: $owner, name: $name) {\n"
            + "\n".join(lines) + "\n  }\n}")


def titles_argv(slug: str, numbers: Sequence[int]) -> list[str]:
    owner, name = slug.split("/", 1)
    return ["api", "graphql", "-f", "query=" + titles_query(numbers), "-f", "owner=" + owner,
            "-f", "name=" + name]


def titles_from_answer(answer: object, numbers: Sequence[int]) -> dict[int, str]:
    repository = _dict(_dict(_dict(answer, "answer").get("data"), "data").get("repository"), "repository")
    titles: dict[int, str] = {}
    for number in numbers:
        node = repository.get(f"i{number}")
        if node is None:
            continue
        node = _dict(node, f"i{number}")
        if node.get("number") != number or isinstance(node.get("number"), bool):
            raise _invalid(f"i{number} is another issue")
        title = node.get("title")
        if not isinstance(title, str):
            raise _invalid(f"i{number} title is not a string")
        title = " ".join(title.split())
        if title:
            titles[number] = title
    return titles


def askable(numbers: Iterable[int]) -> list[int]:
    """The distinct numbers the tracker can be asked about, ascending: the query's `Int` is 32-bit signed."""
    return sorted({number for number in numbers if 0 < number <= MAX_QUERY_NUMBER})


def read_titles(slug: str, numbers: Iterable[int], *,
                call: Callable[[list[str]], Any] | None = None,
                cancelled: Callable[[], bool] = lambda: False) -> dict[int, str]:
    """The titles of the smallest `MAX_TITLES_PER_CALL` distinct numbers the tracker can be asked about, in
    one call; raises `forge_api.ForgeError`. No numbers makes no call. `gh` fails a whole batch when one
    number does not resolve (a deleted issue, a typo), so a batch that failed for a reason other than the
    transport is asked again in halves: a number that fails alone is left untitled, and the rest keep theirs."""
    asked = askable(numbers)[:MAX_TITLES_PER_CALL]
    if not asked:
        return {}
    if call is None:
        def call(argv: list[str]) -> Any:
            return forge_api.gh_json(argv, cancelled=cancelled)

    def read(batch: list[int]) -> dict[int, str]:
        if cancelled():
            raise ForgeError("cancelled")
        try:
            return titles_from_answer(call(titles_argv(slug, batch)), batch)
        except ForgeError as error:
            if error.code != "gh_failed" or error.transient or error.exhausted:
                raise
            if len(batch) == 1:
                return {}
            middle = len(batch) // 2
            return {**read(batch[:middle]), **read(batch[middle:])}

    return read(asked)


def titles_batch(issues: Iterable[int], known: Collection[int],
                 asked: Collection[int]) -> tuple[list[int], frozenset[int]]:
    """The numbers to ask next and the asked set after asking them; see the module docstring."""
    outstanding = askable(set(issues) - set(known))
    fresh = [number for number in outstanding if number not in asked]
    if not fresh:
        asked, fresh = (), outstanding
    batch = fresh[:MAX_TITLES_PER_CALL]
    return batch, frozenset((set(asked) & set(outstanding)) | set(batch))


def titles_plan(states: Iterable[sprints.SprintState], projects: Collection[str],
                known: Mapping[str, Mapping[int, str]],
                asked: Mapping[str, Collection[int]]) -> dict[str, tuple[list[int], frozenset[int]]]:
    """Per project in `projects` with a sprint not ended, `titles_batch` of the issue numbers its sprints'
    reports list, given the titles `known` and the numbers `asked` of that project."""
    wanted: dict[str, set[int]] = {}
    for state in states:
        if state.project_id in projects and sprints.ended_at(state) is None:
            wanted.setdefault(state.project_id, set()).update(
                issue for issue, _ in (state.report.issues if state.report else ()))
    return {project_id: titles_batch(issues, known.get(project_id, {}), asked.get(project_id, ()))
            for project_id, issues in wanted.items()}


def session_targets(belong: Mapping, absent: Mapping, nudged: Mapping,
                    registry: Mapping) -> tuple[SessionTarget, ...]:
    """The sessions one poll reads for a project: each `belong` session with its registry pid and
    nudge replies, then each `absent` manager session as `held_only`."""
    return tuple(
        SessionTarget(sid, registry[sid].pid if sid in registry else None, belong[sid],
                      nudged.get(sid, ()))
        for sid in sorted(belong)) + tuple(
        SessionTarget(sid, None, absent[sid], (), True) for sid in sorted(absent))


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


def session_output_ms(projects_dirs: Iterable[Path], session_id: str) -> int | None:
    if session_id in ("", ".", "..") or "/" in session_id or "\0" in session_id:
        return None
    newest: int | None = None

    def note(path: str) -> None:
        nonlocal newest
        try:
            stamp = os.stat(path).st_mtime_ns // 1_000_000
        except OSError:
            return
        newest = stamp if newest is None else max(newest, stamp)

    for projects in projects_dirs:
        try:
            slugs = [entry.path for entry in os.scandir(projects) if entry.is_dir()]
        except OSError:
            continue
        for slug in slugs:
            own = os.path.join(slug, session_id + ".jsonl")
            if os.path.isfile(own):
                note(own)
            for here, _, names in os.walk(os.path.join(slug, session_id)):
                for name in names:
                    path = os.path.join(here, name)
                    if name.endswith(".jsonl") and os.path.isfile(path):
                        note(path)
    return newest


def _peer_origin(record: Mapping) -> bool:
    for holder in (record, record.get("attachment")):
        origin = holder.get("origin") if isinstance(holder, dict) else None
        if isinstance(origin, dict) and origin.get("kind") == "peer":
            return True
    return False


_HELD_SEEN: dict[str, tuple[int, int, int, bool]] = {}  # path -> (dev, inode, bytes through the last newline, held)


def _held_after(held: bool, raws: Iterable[bytes]) -> bool:
    for raw in raws:
        if b"peer" not in raw and HELD_PREFIX.encode() not in raw:
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        content = record.get("content")
        if (record.get("type") == "system" and isinstance(content, str)
                and content.startswith(HELD_PREFIX) and HELD_SUFFIX in content):
            held = True
        elif _peer_origin(record):
            held = False
    return held


def _transcript_held(path: str) -> bool | None:
    try:
        with open(path, "rb") as handle:
            stat = os.fstat(handle.fileno())
            dev, ino, offset, held = _HELD_SEEN.get(path, (0, 0, 0, False))
            if (dev, ino) != (stat.st_dev, stat.st_ino) or offset > stat.st_size:
                offset, held = 0, False
            handle.seek(offset)
            for raw in handle:
                if not raw.endswith(b"\n"):
                    return _held_after(held, [raw])  # still being written: read, not kept
                offset += len(raw)
                held = _held_after(held, [raw])
                _HELD_SEEN[path] = (stat.st_dev, stat.st_ino, offset, held)
    except OSError:
        return None
    _HELD_SEEN[path] = (stat.st_dev, stat.st_ino, offset, held)
    return held


def session_held(projects_dirs: Iterable[Path], session_id: str) -> bool:
    """True when the session's own transcript (never its subagents') shows a peer message the client
    held and did not deliver, and no peer message was delivered after it (#1229). The whole transcript
    counts, read incrementally; a line that does not parse is skipped, and an absent or unreadable
    file, or an id that names no path, is not held."""
    if session_id in ("", ".", "..") or "/" in session_id or "\0" in session_id:
        return False
    held = False
    for projects in projects_dirs:
        try:
            slugs = [entry.path for entry in os.scandir(projects) if entry.is_dir()]
        except OSError:
            continue
        for slug in slugs:
            if _transcript_held(os.path.join(slug, session_id + ".jsonl")):
                held = True
    return held


_TURN_SEEN: dict[str, tuple[int, int, int, int | None]] = {}  # path -> (dev, inode, bytes through the last newline, newest turn ms)


def _turn_after(newest: int | None, raw: bytes) -> int | None:
    if b'"user"' not in raw and b'"assistant"' not in raw:
        return newest
    try:
        record = json.loads(raw)
    except (ValueError, RecursionError):  # a record nested too deeply to parse is skipped, as any unreadable one
        return newest
    if not isinstance(record, dict) or record.get("type") not in ("user", "assistant"):
        return newest
    stamp = record.get("timestamp")
    at = at_ms(stamp) if isinstance(stamp, str) else None
    if at is None:
        return newest
    return at if newest is None else max(newest, at)


def _transcript_turn(path: str) -> int | None:
    try:
        with open(path, "rb") as handle:
            stat = os.fstat(handle.fileno())
            dev, ino, offset, newest = _TURN_SEEN.get(path, (0, 0, 0, None))
            if (dev, ino) != (stat.st_dev, stat.st_ino) or offset > stat.st_size:
                offset, newest = 0, None
            handle.seek(offset)
            for raw in handle:
                if not raw.endswith(b"\n"):
                    return _turn_after(newest, raw)  # still being written: read, not kept
                offset += len(raw)
                newest = _turn_after(newest, raw)
                _TURN_SEEN[path] = (stat.st_dev, stat.st_ino, offset, newest)
    except OSError:
        return None
    _TURN_SEEN[path] = (stat.st_dev, stat.st_ino, offset, newest)
    return newest


def transcript_turn_ms(projects_dirs: Iterable[Path], session_id: str) -> int | None:
    """The newest user or assistant record time, in epoch milliseconds, of the session's own transcript
    and of every transcript under its directory (its subagents and workflow agents), over every slug
    directory; None when no record counts or the id names no path (#1424). Read incrementally."""
    if session_id in ("", ".", "..") or "/" in session_id or "\0" in session_id:
        return None
    newest: int | None = None
    paths: list[str] = []
    for projects in projects_dirs:
        try:
            slugs = [entry.path for entry in os.scandir(projects) if entry.is_dir()]
        except OSError:
            continue
        for slug in slugs:
            paths.append(os.path.join(slug, session_id + ".jsonl"))
            for here, _, names in os.walk(os.path.join(slug, session_id)):
                paths.extend(os.path.join(here, name) for name in names if name.endswith(".jsonl"))
    for path in paths:
        turn = _transcript_turn(path)
        if turn is not None:
            newest = turn if newest is None else max(newest, turn)
    return newest


def process_table(proc: Path = Path("/proc"), clock_ticks: int | None = None) -> dict[int, ProcessStat] | None:
    if not (proc / "self" / "stat").exists():
        return None
    ticks = clock_ticks or os.sysconf("SC_CLK_TCK")
    table: dict[int, ProcessStat] = {}
    try:
        names = os.listdir(proc)
    except OSError:
        return None
    for name in names:
        if not name.isdigit():
            continue
        try:
            text = (proc / name / "stat").read_text(encoding="utf-8", errors="replace")
            fields = text.rsplit(")", 1)[1].split()
            if len(fields) < 20:
                continue
            used = sum(int(fields[i]) for i in (11, 12, 13, 14))
            table[int(name)] = ProcessStat(int(fields[1]), fields[19], used * 1000 // ticks)
        except (OSError, IndexError, ValueError):
            continue
    return table


def descendant_cpu(table: Mapping[int, ProcessStat], pid: int) -> Cpu:
    if pid not in table:
        return ()
    children: dict[int, list[int]] = {}
    for child, stat in table.items():
        children.setdefault(stat.ppid, []).append(child)
    seen = {pid}
    queue = [pid]
    found = []
    while queue:
        for child in children.get(queue.pop(), ()):
            if child not in seen:
                seen.add(child)
                queue.append(child)
                found.append(((child, table[child].start), table[child].cpu_ms))
    return tuple(sorted(found))


def read_sessions(projects_dirs: Iterable[Path], targets: Iterable[SessionTarget], *,
                  proc: Path = Path("/proc"), clock_ticks: int | None = None) -> tuple[SessionReading, ...]:
    projects = list(projects_dirs)
    table = process_table(proc, clock_ticks)
    readings = []
    for target in sorted(targets, key=lambda t: t.session_id):
        if target.held_only:
            readings.append(SessionReading(target.session_id, target.sprints, None, None,
                                           target.replies, session_held(projects, target.session_id)))
            continue
        alive = table is not None and target.pid is not None and target.pid in table
        cpu = descendant_cpu(table, target.pid) if alive else None
        readings.append(SessionReading(target.session_id, target.sprints,
                                       session_output_ms(projects, target.session_id), cpu,
                                       target.replies, session_held(projects, target.session_id)))
    return tuple(readings)


def _fold_sessions(previous: tuple[SessionMovement, ...], readings: tuple[SessionReading, ...],
                   at: int) -> tuple[SessionMovement, ...]:
    old = {(s.session_id, s.sprint_id): s for s in previous}
    fresh = {}
    for reading in readings:
        for sprint in reading.sprints:
            seen = old.get((reading.session_id, sprint))
            nudged = dict(reading.replies).get(sprint)

            def reply(ms: int | None) -> bool:
                return ms is not None and nudged is not None and nudged <= ms < nudged + NUDGE_REPLY_MS

            outputs = [m for m in (None if reply(reading.output_ms) else reading.output_ms,
                                   seen and seen.output_ms) if m is not None]
            check = seen.check_ms if seen else None
            if reading.cpu is not None and seen is not None and seen.cpu is not None:
                prev = dict(seen.cpu)
                used = sum(max(0, ms - prev.get(key, 0)) for key, ms in reading.cpu)
                if used >= CHECK_CPU_MS and not reply(at):
                    check = at
            fresh[(reading.session_id, sprint)] = SessionMovement(
                reading.session_id, sprint, max(outputs) if outputs else None, check,
                reading.cpu, at, reading.held)
    return tuple(sorted({**old, **fresh}.values(), key=lambda s: (s.session_id, s.sprint_id)))


def merged(previous: ProjectMovement | None, pulls: tuple[PullRequest, ...] | None,
           now_ms: int, local: LocalReading,
           locking: Collection[int] = (), live: Collection[int] | None = None) -> ProjectMovement:
    """Fold one reading into the last: every time kept is the last time its signal was seen."""
    before = previous or ProjectMovement()
    locks = dict(before.locks)
    positions = dict(before.positions)
    if pulls is None:
        kept, read_ms, lock_held = before.pulls, before.read_ms, before.lock_held
    else:
        positions = {}
        for pull in pulls:
            if pull.queue_position is not None:
                for issue in pull.issues:
                    positions[issue] = min(pull.queue_position, positions.get(issue, pull.queue_position))
        lock_held = any(pull.holding for pull in pulls)
        seen_locking = {issue for pull in pulls if pull.holding for issue in pull.issues
                        if live is None or issue in live}
        if lock_held:
            seen_locking.update(locking)
        for issue in seen_locking:
            locks[issue] = max(now_ms, locks.get(issue, now_ms))
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
    at = now_ms if local.sessions_ms is None else local.sessions_ms
    return ProjectMovement(kept, read_ms, tuple(sorted(branches.items())),
                           now_ms if local.release else before.release_ms,
                           tuple(sorted(locks.items())), lock_held,
                           _fold_sessions(before.sessions, local.sessions, at),
                           tuple(sorted(positions.items())))
