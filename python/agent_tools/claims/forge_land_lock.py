"""The cross-host land lock (issue 629): `forge-claim land acquire|release|status`.

The lock serialises landings on one branch across hosts. Each action takes `--repo <owner/name>`,
`--branch <name>` and `--sha <40 hex>`; `--wait` and `--release` exist on `acquire` only, as does
`--follow-head`, which needs both (a usage error otherwise).

D1, the lock is the ref `refs/agent-locks/land/<branch>`, whose value is a pull-request head sha:
created by REST `POST git/refs` (HTTP 422 means not created), moved and deleted by the
`updateRefs` compare-and-swap with `beforeOid` and `force: true`. A failed compare-and-swap
answers HTTP 200 with a generic error, so any CAS error counts as not done and the ref is
re-read to classify the outcome: the caller's sha is success, another oid or no ref is a lost
race, and the observed oid unchanged is a forge error carrying the CAS's own code and transport
class (issue 740), never a lost race. REST ref deletion is unconditional and never used.

D2, the holder is derived, not stored, and the head decides: `classify` reads the pull requests
that contain the lock sha (`_on_branch`: the forge's commit lookup `GET commits/<sha>/pulls`, which
for a commit outside the default branch lists open pull requests only, so a squash-merged,
rebase-merged or closed-unmerged holder gets `[]`; plus the closed pull requests headed at the
lock, found by head sha in the closed listing `GET pulls?state=closed&base=<branch>&sort=updated`,
at most 5 pages of 100), and only an open pull request whose head is the lock holds it: the lock
is held while it is the head of an open pull request other than the caller's, and a pull request
that merely contains the lock's sha (a branch stacked on the holder) never holds or moves it.
For a commit on the default branch the commit lookup lists merged pull requests only (issue 905),
so it leaves out an open pull request whose head is already there, as the head of every sync of
the default branch back into the locked branch is. When the lookup lists no pull request headed
at the lock, the open pull requests based on the branch are therefore read before the closed
ones (`GET pulls?state=open&base=<branch>&sort=updated`, at most 5 pages of 100, matched by head
sha), and a same-repository one headed at the lock holds it, whatever closed pull requests share
that head or contain it; the closed listing is read only when none is found. A fork's pull
request is never taken from this listing, and an open one beyond those pages is not seen.
A release pull request (issue 875) is one whose head is the locked branch itself, in the same
repository, at the lock: `_on_branch` counts it whatever its base, so every caller derives it as
the holder with no flag. The commit lookup lists it while it is open; when no listing above
has a pull request headed at the lock, one the lookup left out, open or closed, is found in `GET
pulls?state=all&head=<owner>:<branch>&sort=updated` (one page of 100), so a live release lock is
never judged by the merged pull requests that contain it. A fork's branch of the same name is
never counted.

D3, staleness follows the owner's option-B decision on issue 629
(https://github.com/fagenorn/nix-config/issues/629#issuecomment-6693579241): no wall clock and no
event is read; a one-shot `status` or `acquire` treats a lock as stale only when `classify` answers
`closed` (the lock of a merged or closed pull request), takes only that over, and never takes over
a `held` lock. A published (merged) or closed release pull request is stale the same way.

D4, the only idle takeover is `wait_acquire`'s, of an oid this process has itself watched
unchanged for `IDLE_AFTER` seconds (45 minutes) of `monotonic()`, counted from its first
observation of that oid; nothing is persisted, so every `--wait` invocation starts a fresh watch.
Every completed ref observation, a lost CAS's re-read and an observed absence included, restarts
the watch when the oid differs. A holder runs a one-shot `acquire` with its sha right before the
merge and merges only when its verdict is `already_held` or `moved`, never on exit status alone:
`acquired` also exits 0 and means the lock was lost and taken again, so the base may have moved and
the holder resyncs first. A release holder merges only on `already_held` (ADR-claims-009).

D5, a lock moves to the caller's new head (verdict `moved`: the lock sat at an earlier head of the
same pull request) only when every open pull request containing it is the caller's; a branch
merely stacked on the holder's head never moves it. A lock that a pull request headed by the
locked branch contains, in the same repository and whatever its head, never answers `moved`: the
branch itself has reached that sha, so where this rule would move the lock it is taken over as
`closed` instead and the caller, answered `acquired`, resyncs. That covers a published release
whose lock the caller's pull request alone still contains, and a release whose head moved past
its lock, which releases the old lock and acquires again. A following release wait (D6) does that
itself (issue 901): a poll that finds the lock held at `--sha` while the release pull request's
head is another sha sends the D9 delete of `--sha`, exactly what `release --sha` does, and attempts
again in the same poll, competing with every other waiter. It first reads the commit lookup of
`--sha` (and, when that lists no such head, the open listing of D2) and leaves the lock alone when
an open pull request other than the release has its head there: that one holds it. The answer is `acquired` or `already_held`, never `moved`, so nobody
merges on a lock that changed hands without a resync.

D6, `acquire` needs an open pull request whose head is the caller's sha with the branch as its
base before any ref write, and otherwise answers `error` with `no_open_pr` (exit 2). `--wait`
re-checks this before every attempt, the first included: a caller whose pull request no longer has
`--sha` as its head stops with `no_open_pr` and never moves the lock. When the commit lookup of
`--sha` lists no such pull request, the open listing of D2 is read once for a same-repository one
(issue 905: a head on the default branch), so the common path makes no extra call and `no_open_pr`
is answered only after both reads. With `--release` the pull
request needed is instead an open one whose head branch is `--branch` at `--sha`, in the same
repository (never a fork's branch of that name), with the repository's default branch as its base;
the default branch is read once per invocation (`GET repos/<slug>`). With `--follow-head` a
waiting release follows its pull request instead (issue 901), because every landing ahead of it
moves the release head: each poll of `--release --wait --follow-head` reads the open pull requests
headed by `--branch` (`GET pulls?state=open&head=<owner>:<branch>`, one call in place of the commit
lookup), keeps the same-repository one based on the default branch, and attempts the lock at that
pull request's current head. `--sha` is then only the caller's starting belief, and `no_open_pr`
means no such pull request is open. Without the flag nothing follows: a one-shot `--release`, and
a `--release --wait` whose caller is bound to `--sha` (a resumed release), stop with `no_open_pr`
when the head moved.

D7, every call prints one JSON object on one stdout line with `command`, `action`, `repo`,
`branch`, `sha`, `verdict`, `lock_sha`, `pr`, `by`, `took_over` (`null`, `"closed"` or `"idle"`)
and `waited_s`. `sha` is always `--sha` as given and `lock_sha` is where the lock is: a successful
`acquire --release --wait --follow-head` adds `head_moved`, true when it took the lock at a head other than
`--sha`, and the caller continues with `lock_sha` as its commit. The `acquire` verdicts are
`acquired`, `already_held` (the lock is already at `--sha`, or at the followed head), `moved`,
`held_by` and `lost_to`. Exit 0 is `acquired`, `already_held`, `moved`,
`released` and every `status` verdict (`free`, `held_by`, `stale`); exit 3 is contention
(`held_by`, `lost_to`, `land-contended`, and `not_held` on `release`); exit 1 a forge error; exit 2
a usage error or `no_open_pr`.

D8, `--wait` attempts at offsets 0, `POLL` (120 s), ... `BOUND` (3600 s) and then answers
`land-contended` (exit 3); a `gh_failed`/`gh_timeout` poll counts as failed, an unapplied CAS on an
unchanged lock included, and `FAILED_POLLS` in a row exit 1 with that error; only a poll that
completes with a verdict resets the count. Every poll, the first included, reads the caller's
eligible pull requests (D6) inside the poll, so a failed read is a failed poll and a transport
failure there waits for the next poll instead of exiting at once (issue 740). The whole-verb
transport retry of `forge_claim` never wraps `--wait`, whose failed-poll count is its own bound.

D9, `release` is a compare-and-swap delete sent without a prior read, then re-read.

D10, a swap that reported no failure whose read-back still shows the old lock is read again up to
`READBACK_RETRIES` times, `READBACK_DELAY` seconds apart, before it is judged: the git refs API can lag
a write (issue 816), so a ref that reaches the caller's sha answers `moved` or `acquired`, and only a
read-back that stays on the old lock, or names a third sha at once, is `lost_to`.
"""
import time
from collections.abc import Collection
from typing import Any, Callable, NamedTuple

from agent_tools.claims import forge_markers as fm
from agent_tools.system import forge_api

LOCK_PREFIX = "refs/agent-locks/land/"
CREATE_ROUNDS = 3
READBACK_RETRIES = 3
READBACK_DELAY = 1.0
IDLE_AFTER = 2700
POLL = 120
BOUND = 3600
FAILED_POLLS = 3
ACTIONS = ("acquire", "release", "status")

monotonic = time.monotonic
sleep = time.sleep


class Attempts:
    """What earlier tries of one retried `acquire` may have written (issue 740).

    `unsure` is true once a try sent a create or a swap that was not refused and then raised, so
    its effect is unknown. A later try that finds the lock at its sha cannot tell its own write
    from a lock already held, and reports `acquired`, which the programs recheck before they
    merge, never `already_held`."""

    def __init__(self) -> None:
        self.wrote = False  # the running try has sent a write not yet known to be refused
        self.unsure = False

    def failed(self) -> None:
        """The running try raised: a write it sent may have taken effect."""
        self.unsure = self.unsure or self.wrote
        self.wrote = False


class Outcome(NamedTuple):
    verdict: str
    lock_sha: str | None
    pr: int | None
    took_over: str | None


def lock_ref(branch: str) -> str:
    return LOCK_PREFIX + branch


def pick_pr(pulls: list[fm.Pull]) -> int | None:
    """The smallest open number, else the largest closed number, else None."""
    opened = [p.number for p in pulls if p.state == "open"]
    if opened:
        return min(opened)
    closed = [p.number for p in pulls]
    return max(closed) if closed else None


def classify(lock: str, theirs: list[fm.Pull], mine: Collection[int]) -> tuple[str, int | None]:
    """D2: the kind (`held`, `move` or `closed`) and the pull request to report."""
    open_ = [p for p in theirs if p.state == "open"]
    heads = [p.number for p in open_ if p.head_sha == lock and p.number not in mine]
    if heads:
        return "held", min(heads)
    if mine and open_ and all(p.number in mine for p in open_):
        return "move", min(p.number for p in open_)
    closed = [p for p in theirs if p.state != "open"]
    closed_heads = [p.number for p in closed if p.head_sha == lock]
    if (theirs and not any(p.head_sha == lock for p in open_)
            and (len(closed) == len(theirs) or closed_heads)):
        return "closed", max(closed_heads) if closed_heads else max(p.number for p in closed)
    return "held", min(p.number for p in open_) if open_ else None


def holder(slug: str, pr: int | None) -> str | None:
    """The `holder` of the claim winner on the first closing issue of `pr` that has one (D2)."""
    if pr is None:
        return None
    for issue in fm.closing_issues(slug, pr):
        winners = fm.contest(fm.list_markers(slug, issue), "claim", {"issue": str(issue)})
        if winners:
            return winners[0].fields.get("holder")
    return None


def _releases(pull: fm.Pull, branch: str, sha: str) -> bool:
    """`pull` is a release pull request of `branch` at `sha`: its head is that branch itself."""
    return pull.same_repo and pull.head_ref == branch and pull.head_sha == sha


def _from_branch(pull: fm.Pull, branch: str) -> bool:
    """`pull` is headed by `branch` itself, in the same repository, whatever its head sha."""
    return pull.same_repo and pull.head_ref == branch


def _on_branch(slug: str, sha: str, branch: str) -> list[fm.Pull]:
    """The pull requests that contain `sha` and are on `branch` or headed by `branch` (D2, D5),
    plus the ones headed at it that the commit lookup did not list.

    The forge's commit lookup returns only open pull requests for a commit outside the default
    branch and only merged ones for a commit on it, so a holder it left out is found by its head
    sha instead, and only when no pull request already has that head: first among the open pull
    requests on `branch` (a head on the default branch, issue 905), then among the closed ones (a
    squash-merged, rebase-merged or closed holder), then, when none is found there, among the
    pull requests headed by `branch`, open ones included, because the lookup can leave an open
    release pull request out. Each listing is read only when the one before it found none.
    """
    pulls = [p for p in fm.commit_pulls(slug, sha) if p.base_ref == branch or _from_branch(p, branch)]
    if not any(p.head_sha == sha for p in pulls):
        known = {p.number for p in pulls}
        for listing in (fm.open_pulls_headed, fm.closed_pulls_headed, fm.pulls_from):
            headed = [p for p in listing(slug, branch, sha) if p.number not in known]
            if headed:
                return pulls + headed
    return pulls


def _kind(lock: str, theirs: list[fm.Pull], mine: Collection[int], branch: str) -> tuple[str, int | None]:
    """`classify`, except that a lock contained in a pull request headed by `branch` never moves (D5)."""
    kind, pr = classify(lock, theirs, mine)
    reached = [p.number for p in theirs if _from_branch(p, branch)]
    if kind == "move" and reached:
        return "closed", max(reached)
    return kind, pr


def acquire_once(slug: str, branch: str, sha: str, mine: list[fm.Pull],
                 idle: Callable[[str], bool], node: Callable[[], str],
                 seen: Callable[[str | None], None] | None = None,
                 attempts: Attempts | None = None) -> Outcome:
    """One acquire attempt (D1, D2, D3, D5); `idle(lock)` lets a `held` lock be taken over."""
    ref = lock_ref(branch)

    def observe() -> str | None:
        oid = fm.read_ref(slug, ref)
        if seen is not None:
            seen(oid)
        return oid

    lock = None
    for _ in range(CREATE_ROUNDS):
        if attempts is not None:
            attempts.wrote = True
        if fm.create_ref(slug, ref, sha):
            return Outcome("acquired", sha, pick_pr(mine), None)
        if attempts is not None:
            attempts.wrote = False
        lock = observe()
        if lock is not None:
            break
    if lock is None:
        raise forge_api.ForgeError("gh_failed", "ref create refused while the ref is absent")
    if lock == sha:
        verdict = "acquired" if attempts is not None and attempts.unsure else "already_held"
        return Outcome(verdict, sha, pick_pr(mine), None)
    theirs = _on_branch(slug, lock, branch)
    kind, pr = _kind(lock, theirs, {p.number for p in mine}, branch)
    if kind == "held":
        if not idle(lock):
            return Outcome("held_by", lock, pr, None)
        kind = "idle"
    if attempts is not None:
        attempts.wrote = True
    failure = fm.cas_ref(slug, node(), ref, lock, sha)
    after = observe()
    for _ in range(READBACK_RETRIES):
        if failure or after != lock:
            break
        sleep(READBACK_DELAY)  # an applied swap whose read-back still shows the old sha (issue 816)
        after = observe()
    if after == sha:
        if kind == "move":
            return Outcome("moved", sha, pick_pr(mine), None)
        return Outcome("acquired", sha, pick_pr(mine), kind)
    if after == lock and failure:
        raise forge_api.ForgeError(failure.code, "compare-and-swap not applied and the lock is unchanged",
                            transient=failure.transient)
    return Outcome("lost_to", after, _pr_of(slug, branch, after), None)


def _pr_of(slug: str, branch: str, lock: str | None) -> int | None:
    if lock is None:
        return None
    return classify(lock, _on_branch(slug, lock, branch), ())[1]


def result(args: Any, verdict: str, *, lock_sha: str | None = None, pr: int | None = None,
           by: str | None = None, took_over: str | None = None, waited_s: int | None = None,
           **extra: Any) -> dict[str, Any]:
    return {"command": "land", "action": args.action, "repo": args.repo, "branch": args.branch,
            "sha": args.sha, "verdict": verdict, "lock_sha": lock_sha, "pr": pr, "by": by,
            "took_over": took_over, "waited_s": waited_s, **extra}


def usage_result(argv: list[str], detail: str) -> dict[str, Any]:
    action = argv[1] if len(argv) > 1 and argv[1] in ACTIONS else None
    return {"command": "land", "action": action, "repo": None, "branch": None, "sha": None,
            "verdict": "error", "lock_sha": None, "pr": None, "by": None, "took_over": None,
            "waited_s": None, "error": "usage", "detail": detail}


def wait_acquire(args: Any, node: Callable[[], str],
                 eligible: Callable[[], list[fm.Pull]]) -> tuple[int, dict[str, Any]]:
    """D4, D8: poll `acquire_once` until it succeeds, the bound passes or polls keep failing.

    D6 holds at every attempt: `mine` is read inside every poll, the first included, so a failed
    read is a failed poll (issue 740), and a caller whose pull request no longer has its sha as
    head stops with `no_open_pr`. The attempt is made at the head of `mine`, which is `--sha`
    except for a following release, whose `eligible` follows its pull request (issue 901).
    """
    start = monotonic()
    watch: list[Any] = [object(), None]  # [oid or None, first seen]; the sentinel matches nothing
    failures = 0
    last: Outcome | None = None

    def seen(oid: str | None) -> None:
        if watch[0] != oid:
            watch[0], watch[1] = oid, monotonic()

    def idle(lock: str) -> bool:
        seen(lock)
        return monotonic() - watch[1] >= IDLE_AFTER

    while True:
        try:
            mine = eligible()
            if not mine:
                return _no_open_pr(args)
            sha = mine[0].head_sha
            mine = [p for p in mine if p.head_sha == sha]
            outcome = acquire_once(args.repo, args.branch, sha, mine, idle, node, seen)
            if (outcome.verdict == "held_by" and outcome.lock_sha == args.sha != sha
                    and not _headed_by_another(args, {m.number for m in mine})):
                # D5: the release's own lock at the head it started from; release it, try again.
                failure = fm.cas_ref(args.repo, node(), lock_ref(args.branch), args.sha, fm.ZERO_OID)
                outcome = acquire_once(args.repo, args.branch, sha, mine, idle, node, seen)
                if failure and outcome.verdict == "held_by" and outcome.lock_sha == args.sha:
                    raise forge_api.ForgeError(failure.code, "compare-and-swap delete not applied and "
                                               "the lock is unchanged", transient=failure.transient)
        except forge_api.ForgeError as error:
            failures += 1
            if error.code not in ("gh_failed", "gh_timeout") or failures >= FAILED_POLLS:
                raise
        else:
            failures = 0
            if outcome.verdict in ("acquired", "already_held", "moved"):
                moved = {"head_moved": sha != args.sha} if _follows(args) else {}
                return 0, result(args, outcome.verdict, lock_sha=outcome.lock_sha, pr=outcome.pr,
                                 took_over=outcome.took_over, waited_s=int(monotonic() - start),
                                 **moved)
            if outcome.lock_sha is not None:
                last = outcome
        if monotonic() - start >= BOUND:
            return 3, result(args, "land-contended", lock_sha=last.lock_sha if last else None,
                             pr=last.pr if last else None,
                             by=holder(args.repo, last.pr) if last else None,
                             waited_s=int(monotonic() - start))
        sleep(min(POLL, start + BOUND - monotonic()))


def _headed_by_another(args: Any, mine: Collection[int]) -> bool:
    """D5: an open pull request outside `mine` has its head at `--sha`, so it holds a lock there.

    Read as `_on_branch` reads it: the commit lookup, then the open listing of the branch when
    the lookup lists no such head (a head on the default branch, issue 905)."""
    heads = [p for p in fm.commit_pulls(args.repo, args.sha) if p.state == "open" and p.head_sha == args.sha]
    heads = heads or fm.open_pulls_headed(args.repo, args.branch, args.sha)
    return any(p.number not in mine for p in heads)


def _no_open_pr(args: Any) -> tuple[int, dict[str, Any]]:
    detail = (f"no open pull request on {args.branch} has head {args.sha}" if not args.release
              else f"no open release pull request from {args.branch} into the default branch"
              if _follows(args) else f"no open release pull request from {args.branch} has head {args.sha}")
    return 2, result(args, "error", error="no_open_pr", detail=detail)


def _follows(args: Any) -> bool:
    """D6: `--follow-head`; a caller that builds its own arguments (`release_lock`) never follows."""
    return bool(getattr(args, "follow_head", False))


def _acquire(args: Any, attempts: Attempts | None = None) -> tuple[int, dict[str, Any]]:
    if _follows(args) and not (args.release and args.wait):
        return 2, result(args, "error", error="usage", detail="--follow-head needs --release and --wait")
    default: list[str] = []

    def eligible() -> list[fm.Pull]:
        if _follows(args):  # D6: a waiting release follows its pull request's head
            mine = fm.open_pulls_from(args.repo, args.branch)
        else:
            opened = [p for p in fm.commit_pulls(args.repo, args.sha) if p.state == "open"]
            if not args.release:
                mine = [p for p in opened if p.base_ref == args.branch and p.head_sha == args.sha]
                # D6: an open head on the default branch is not in the commit lookup (issue 905).
                return mine or fm.open_pulls_headed(args.repo, args.branch, args.sha)
            mine = [p for p in opened if _releases(p, args.branch, args.sha)]
        if mine and not default:
            default.append(fm.default_branch(args.repo))
        return [p for p in mine if p.base_ref == default[0]]

    cached: list[str] = []

    def node() -> str:
        if not cached:
            cached.append(fm.repo_node_id(args.repo))
        return cached[0]

    if args.wait:
        return wait_acquire(args, node, eligible)
    mine = eligible()
    if not mine:
        return _no_open_pr(args)
    outcome = acquire_once(args.repo, args.branch, args.sha, mine, lambda _: False, node,
                           attempts=attempts)
    if outcome.verdict in ("acquired", "already_held", "moved"):
        return 0, result(args, outcome.verdict, lock_sha=outcome.lock_sha, pr=outcome.pr,
                         took_over=outcome.took_over)
    return 3, result(args, outcome.verdict, lock_sha=outcome.lock_sha, pr=outcome.pr,
                     by=holder(args.repo, outcome.pr))


def _release(args: Any) -> tuple[int, dict[str, Any]]:
    ref = lock_ref(args.branch)
    failure = fm.cas_ref(args.repo, fm.repo_node_id(args.repo), ref, args.sha, fm.ZERO_OID)
    after = fm.read_ref(args.repo, ref)
    if after is None:
        return 0, result(args, "released")
    if after == args.sha:
        raise forge_api.ForgeError(failure.code if failure else "gh_failed",
                            "compare-and-swap delete left the lock at the caller's sha",
                            transient=failure is not None and failure.transient)
    pr = _pr_of(args.repo, args.branch, after)
    return 3, result(args, "not_held", lock_sha=after, pr=pr, by=holder(args.repo, pr))


def _status(args: Any) -> tuple[int, dict[str, Any]]:
    lock = fm.read_ref(args.repo, lock_ref(args.branch))
    if lock is None:
        return 0, result(args, "free")
    kind, pr = classify(lock, _on_branch(args.repo, lock, args.branch), ())
    return 0, result(args, "stale" if kind == "closed" else "held_by", lock_sha=lock, pr=pr,
                     by=holder(args.repo, pr))


def run(args: Any, attempts: Attempts | None = None) -> tuple[int, dict[str, Any]]:
    """Run the parsed action; a caller that retries `acquire` passes the same `attempts` each try."""
    if args.action == "acquire":
        return _acquire(args, attempts)
    return {"release": _release, "status": _status}[args.action](args)
