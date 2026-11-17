"""The console's comparison of a registered checkout with its remote, and its fast-forward (#1233).

Decided in ADR-console-070 (#1233). Two functions, both total (they never raise) and both
cancellable: `compare(root, cancel=None)` says whether the checkout is behind its remote's default
branch and whether that branch carries a `.agents/project.json`, and `update(root, cancel=None)` moves
the checkout forward to it when that is safe. `cancel` is a `threading.Event` (or anything with
`is_set()`); a set event ends the running child's whole process group and no later child starts, so
a cancelled fetch is never followed by a merge. The merge is the one child that is never ended: it
is checked once before it starts, and a started merge runs to its own end (git writes the working
tree before it moves `HEAD`, and a kill would leave a half-written tree and a stale `index.lock`).

Children. Every child is `git -c core.hooksPath=/dev/null -C <root> <args>`, with no shell, stdin
from `DEVNULL`, stdout and stderr piped, `GIT_TERMINAL_PROMPT=0`, run in its own session through
`manager.run_in_own_group` (the merge, which is never ended, through `subprocess.run`). A local read
is bound by `GIT_TIMEOUT` (10 seconds); `ls-remote` and `fetch` by `FETCH_TIMEOUT` (120 seconds);
the merge has no bound. The listing argv and its parse are
`adopt_inspection.REMOTE_HEADS_ARGS` and `adopt_inspection.parse_remote_heads`, the fetch argv is
`adopt_inspection.fetch_pinned_args(branch)`: this module writes no argv of its own for either, so
there is one fetch policy (only `refs/remotes/origin/<branch>` and its objects are written).

Compare. `Comparison(state, branch, behind, contract, failure)`. The states are `CURRENT` (nothing
on the remote that `HEAD` lacks), `BEHIND` (`behind` commits it lacks; `contract` says its tip
carries `CONTRACT`), `UNREADABLE` (the remote could not be read; `failure` says why) and `SKIPPED`
(no `origin`, or a default branch that is not `safe_branch`: nothing is fetched, a remote can never
steer the refspec). `compare` never moves `HEAD`, a local branch or the working tree.

Update. `Updated(reason, failure)`: `reason` is None when the checkout was moved or had nothing to
move, else one of `UNREAD_REASON`, `NOT_ON_BRANCH` (another branch or a detached `HEAD`),
`HAS_CHANGES` (tracked files differ), `DIVERGED` (commits the remote lacks) or `NOT_MOVED` (git
refused the move). The move is `merge --ff-only --no-overwrite-ignore`: it runs no hook and leaves
`HEAD` and every working-tree file, ignored ones included, unchanged on every refusal.

Failure. `Failure(step, detail)` is what the caller logs: `step` is the git subcommand that failed
and `detail` is `exit <code>: <git's stderr>` (decoded with `errors="replace"`, stripped, its last
`DETAIL_LIMIT` characters), `timed out after <seconds> s`, `cancelled`, or
`<ExceptionClass>: <message>` for a child that could not start. Git's stderr is never discarded and
no owner-facing word is built from it.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import typing

from agent_tools.console import manager
from agent_tools.project_contract import adopt_inspection

CONTRACT = ".agents/project.json"
GIT_TIMEOUT = 10
FETCH_TIMEOUT = 120
DETAIL_LIMIT = 2000

CURRENT = "current"
BEHIND = "behind"
UNREADABLE = "unreadable"
SKIPPED = "skipped"

UNREAD_REASON = "its remote could not be read"
NOT_ON_BRANCH = "another branch is checked out"
HAS_CHANGES = "it has changes that are not committed"
DIVERGED = "it has commits that are not on its remote"
NOT_MOVED = "git could not move it forward"

_SAFE_BRANCH = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._/-]*")


class Failure(typing.NamedTuple):
    step: str
    detail: str


class Comparison(typing.NamedTuple):
    state: str
    branch: str | None
    behind: int
    contract: bool
    failure: Failure | None


class Updated(typing.NamedTuple):
    reason: str | None
    failure: Failure | None


def safe_branch(name: str | None) -> bool:
    """Whether `name` is a branch name that can go into a refspec unquoted."""
    return (isinstance(name, str) and _SAFE_BRANCH.fullmatch(name) is not None
            and ".." not in name and "//" not in name
            and not name.endswith(("/", ".", ".lock")))


def _git(root: str, step: str, *arguments: str, timeout: float | None,
         cancel: threading.Event | None):
    """One git child: `(CompletedProcess, None)` or `(None, Failure)`.

    A `timeout` of None is a child that is never interrupted: it ignores `cancel` and runs to its own
    end (the merge, which writes the working tree before it moves `HEAD`).
    """
    if timeout is not None and cancel is not None and cancel.is_set():
        return None, Failure(step, "cancelled")
    argv = ["git", "-c", "core.hooksPath=/dev/null", "-C", root, *arguments]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        if timeout is None:
            done = subprocess.run(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, start_new_session=True, check=False)
        else:
            done = manager.run_in_own_group(
                argv, timeout=timeout, cancel=cancel, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    except subprocess.TimeoutExpired:
        return None, Failure(step, f"timed out after {timeout:g} s")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return None, Failure(step, f"{type(error).__name__}: {error}")
    if timeout is not None and cancel is not None and cancel.is_set():
        return None, Failure(step, "cancelled")
    return done, None


def _exit(step: str, done: subprocess.CompletedProcess) -> Failure:
    words = (done.stderr or b"").decode("utf-8", errors="replace").strip()
    return Failure(step, f"exit {done.returncode}: {words[-DETAIL_LIMIT:]}")


def _text(done: subprocess.CompletedProcess) -> str:
    return (done.stdout or b"").decode("utf-8", errors="replace").strip()


def _count(root: str, revisions: str, cancel):
    """`(n, None)` of `rev-list --count <revisions>`, or `(None, Failure)`."""
    done, failure = _git(root, "rev-list", "rev-list", "--count", revisions,
                         timeout=GIT_TIMEOUT, cancel=cancel)
    if failure is not None:
        return None, failure
    if done.returncode != 0:
        return None, _exit("rev-list", done)
    try:
        return int(_text(done)), None
    except ValueError:
        return None, Failure("rev-list", f"ValueError: {_text(done)}")


def compare(root: str, cancel: threading.Event | None = None) -> Comparison:
    """Whether the checkout at `root` is behind its remote's default branch; see the module docstring."""
    def unreadable(failure):
        return Comparison(UNREADABLE, None, 0, False, failure)

    skipped = Comparison(SKIPPED, None, 0, False, None)
    url, failure = _git(root, "config", "config", "--get", "remote.origin.url",
                        timeout=GIT_TIMEOUT, cancel=cancel)
    if failure is not None:
        return unreadable(failure)
    if url.returncode != 0 or not _text(url):
        return skipped
    listing, failure = _git(root, "ls-remote", *adopt_inspection.REMOTE_HEADS_ARGS,
                            timeout=FETCH_TIMEOUT, cancel=cancel)
    if failure is not None:
        return unreadable(failure)
    if listing.returncode != 0:
        return unreadable(_exit("ls-remote", listing))
    branch = adopt_inspection.parse_remote_heads(listing.stdout or b"").default
    if not safe_branch(branch):
        return skipped
    fetched, failure = _git(root, "fetch", *adopt_inspection.fetch_pinned_args(branch),
                            timeout=FETCH_TIMEOUT, cancel=cancel)
    if failure is not None:
        return unreadable(failure)
    if fetched.returncode != 0:
        return unreadable(_exit("fetch", fetched))
    tracking = f"refs/remotes/{adopt_inspection.REMOTE}/{branch}"
    behind, failure = _count(root, f"HEAD..{tracking}", cancel)
    if failure is not None:
        return unreadable(failure)
    if behind == 0:
        return Comparison(CURRENT, branch, 0, False, None)
    tip, failure = _git(root, "cat-file", "cat-file", "-e", f"{tracking}:{CONTRACT}",
                        timeout=GIT_TIMEOUT, cancel=cancel)
    if failure is not None:
        return unreadable(failure)
    return Comparison(BEHIND, branch, behind, tip.returncode == 0, None)


def update(root: str, cancel: threading.Event | None = None) -> Updated:
    """Fast-forward the checkout at `root` to its remote's default branch when safe; see the module docstring."""
    seen = compare(root, cancel)
    if seen.state == CURRENT:
        return Updated(None, None)
    if seen.state != BEHIND:
        return Updated(UNREAD_REASON, seen.failure)
    branch = seen.branch
    tracking = f"refs/remotes/{adopt_inspection.REMOTE}/{branch}"
    head, failure = _git(root, "symbolic-ref", "symbolic-ref", "--quiet", "HEAD",
                         timeout=GIT_TIMEOUT, cancel=cancel)
    if failure is not None:
        return Updated(NOT_MOVED, failure)
    if _text(head) != f"refs/heads/{branch}":
        return Updated(NOT_ON_BRANCH, None)
    status, failure = _git(root, "status", "status", "--porcelain", "--untracked-files=no",
                           timeout=GIT_TIMEOUT, cancel=cancel)
    if failure is not None:
        return Updated(NOT_MOVED, failure)
    if status.returncode != 0:
        return Updated(NOT_MOVED, _exit("status", status))
    if _text(status):
        return Updated(HAS_CHANGES, None)
    ahead, failure = _count(root, f"{tracking}..HEAD", cancel)
    if failure is not None:
        return Updated(NOT_MOVED, failure)
    if ahead > 0:
        return Updated(DIVERGED, None)
    if cancel is not None and cancel.is_set():
        return Updated(NOT_MOVED, Failure("merge", "cancelled"))
    merged, failure = _git(root, "merge", "merge", "--ff-only", "--no-overwrite-ignore",
                           "--quiet", tracking, timeout=None, cancel=None)
    if failure is not None:
        return Updated(NOT_MOVED, failure)
    if merged.returncode != 0:
        return Updated(NOT_MOVED, _exit("merge", merged))
    return Updated(None, None)
