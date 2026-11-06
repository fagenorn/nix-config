"""The cross-host land lock (issue 629): `forge-claim land acquire|release|status`.

D1, the lock is the ref `refs/agent-locks/land/<branch>`: created by REST (HTTP 422 means not
created), moved and deleted by the `updateRefs` compare-and-swap with `beforeOid`; a CAS that
reports failure is judged by re-reading the ref, and a ref left unchanged is a forge error
carrying the CAS's own code, never a lost race.

D2, the holder is derived, not stored, and the head decides: `classify` reads the pull requests
that contain the lock sha, and only an open pull request whose head is the lock holds it.

D3, staleness: no wall clock and no event is read; a lock is stale only when `classify` answers
`closed`, and a one-shot acquire never takes over a `held` lock.

D5, a lock moves to the caller's new head only when every open pull request containing it is the
caller's; a branch merely stacked on the holder's head never moves it.

D6, `acquire` needs an open pull request whose head is the caller's sha before any ref write.

D7, every call prints one JSON object; exit 0 success, 3 contention, 1 forge error, 2 usage.

D9, `release` is a compare-and-swap delete sent without a prior read, then re-read.
"""
import time
from collections.abc import Collection
from typing import Any, Callable, NamedTuple

from agent_tools import forge_markers as fm

LOCK_PREFIX = "refs/agent-locks/land/"
CREATE_ROUNDS = 3
ACTIONS = ("acquire", "release", "status")

monotonic = time.monotonic
sleep = time.sleep


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


def _on_branch(slug: str, sha: str, branch: str) -> list[fm.Pull]:
    return [p for p in fm.commit_pulls(slug, sha) if p.base_ref == branch]


def acquire_once(slug: str, branch: str, sha: str, mine: list[fm.Pull],
                 idle: Callable[[str], bool], node: Callable[[], str],
                 seen: Callable[[str | None], None] | None = None) -> Outcome:
    """One acquire attempt (D1, D2, D3, D5); `idle(lock)` lets a `held` lock be taken over."""
    ref = lock_ref(branch)

    def observe() -> str | None:
        oid = fm.read_ref(slug, ref)
        if seen is not None:
            seen(oid)
        return oid

    lock = None
    for _ in range(CREATE_ROUNDS):
        if fm.create_ref(slug, ref, sha):
            return Outcome("acquired", sha, pick_pr(mine), None)
        lock = observe()
        if lock is not None:
            break
    if lock is None:
        raise fm.ForgeError("gh_failed", "ref create refused while the ref is absent")
    if lock == sha:
        return Outcome("already_held", sha, pick_pr(mine), None)
    theirs = _on_branch(slug, lock, branch)
    kind, pr = classify(lock, theirs, {p.number for p in mine})
    if kind == "held":
        if not idle(lock):
            return Outcome("held_by", lock, pr, None)
        kind = "idle"
    failure = fm.cas_ref(slug, node(), ref, lock, sha)
    after = observe()
    if after == sha:
        if kind == "move":
            return Outcome("moved", sha, pick_pr(mine), None)
        return Outcome("acquired", sha, pick_pr(mine), kind)
    if after == lock and failure:
        raise fm.ForgeError(failure, "compare-and-swap not applied and the lock is unchanged")
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


def _acquire(args: Any) -> tuple[int, dict[str, Any]]:
    mine = [p for p in fm.commit_pulls(args.repo, args.sha)
            if p.state == "open" and p.base_ref == args.branch and p.head_sha == args.sha]
    if not mine:
        return 2, result(args, "error", error="no_open_pr",
                         detail=f"no open pull request on {args.branch} has head {args.sha}")
    cached: list[str] = []

    def node() -> str:
        if not cached:
            cached.append(fm.repo_node_id(args.repo))
        return cached[0]

    outcome = acquire_once(args.repo, args.branch, args.sha, mine, lambda _: False, node)
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
        raise fm.ForgeError(failure or "gh_failed", "compare-and-swap delete left the lock at the caller's sha")
    pr = _pr_of(args.repo, args.branch, after)
    return 3, result(args, "not_held", lock_sha=after, pr=pr, by=holder(args.repo, pr))


def _status(args: Any) -> tuple[int, dict[str, Any]]:
    lock = fm.read_ref(args.repo, lock_ref(args.branch))
    if lock is None:
        return 0, result(args, "free")
    kind, pr = classify(lock, _on_branch(args.repo, lock, args.branch), ())
    return 0, result(args, "stale" if kind == "closed" else "held_by", lock_sha=lock, pr=pr,
                     by=holder(args.repo, pr))


def run(args: Any) -> tuple[int, dict[str, Any]]:
    return {"acquire": _acquire, "release": _release, "status": _status}[args.action](args)
