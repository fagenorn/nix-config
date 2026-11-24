"""`landing`: the readings an engine landing of one issue makes; none changes anything.

Every call prints exactly one compact JSON object on one stdout line with a `verdict`.
Exit 0 carries any verdict but `error`; exit 1 is `error` (`{verdict, error, transient,
detail}`, `error` the closed code, `transient` true for a failure worth retrying); a usage
error is exit 2 with `error` `usage`.

`prepare --repo-root <path> --issue <n> --repo <owner/name>` prints `{verdict, branch,
worktree_path, integration_branch, head, title, body, closes, detail}`. The branch and the
worktree are `issue-branch`'s. The verdict is `ready` exactly when the worktree is clean
(`git status --porcelain` prints nothing) and its current tree equals the tree in its
`verified-tree.json` record, so `ready` is never said for a tree that was not verified or for
a dirty worktree; else `unverified`. `head` is the worktree's `HEAD`. `title` is the issue
title with `"`, `'`, `$`, a backtick, a backslash, `!` and line breaks removed and runs of
spaces collapsed, so the guard accepts it in a command line. `closes` is `criteria_close` of
the issue body, and `body` is `Closes #<n>. Delivered by the engine.` when it is true, else
`Refs #<n>. Delivered by the engine.`.

`pushed --repo-root <path> --branch <b> --head <sha>` reads `git ls-remote origin
refs/heads/<b>` and prints `pushed` (origin holds `<sha>`), `head-moved` (it holds another
sha, the `remote` member) or `absent` (origin has no such branch).

`pull --repo <owner/name> --branch <b> --integration-branch <i>` reads the open pull requests
headed at `<b>` and keeps those into `<i>`: `open` (`pr`, `head`, `url` of the one), `absent`
(none); more than one is `error` `ambiguous_pull`.

`merged --repo <owner/name> --pr <n> --head <sha>` reads the pull request: `merged` (its
state is `MERGED`; `merge_commit` is the merge commit's sha) or `open` (it is not merged).
`head` is the pull request's own head sha, for the caller to compare with `<sha>`.

`lock --repo <owner/name> --integration-branch <i> --head <sha>` takes the land lock of `<i>` at
`<sha>`, waiting its turn (`forge-claim land acquire --wait`): `held` (the lock's verdict is
`acquired`, `already_held` or `moved`), `contended` (another pull request holds it past the wait),
`no-pull` (no open pull request into `<i>` is headed at `<sha>`, so no lock was taken) or `error`.
The lock's own answer is the `lock` member. `held` with the same flags reads the lock once and
never waits: `held` (`already_held` or `moved`), `retaken` (`acquired`: the lock was lost and taken
again, which is never `held`), `contended`, `no-pull` or `error`. `unlock` with the same flags
releases it: `released` (the lock is free or another pull request's) or `unreleased` (any failure,
`detail`; the lock may still be at `<sha>`); it never answers `error`.

`checks --repo-root <path> --repo <owner/name> --pr <n> --head <sha>` reads the pull request's check
rollup every `CHECK_POLL_SECONDS` for at most `CHECK_BOUND_SECONDS`: `green`, `red` (`failing`, the
names), `pending`, `moved` (the rollup was read at another head, `remote`) or `error`. A `CheckRun`
is green when it is `COMPLETED` with conclusion `SUCCESS`, `SKIPPED` or `NEUTRAL`, a `StatusContext`
when its state is `SUCCESS`. With required checks declared in the contract each must be named by an
entry and every entry naming it green; with none declared every entry counts and one is needed. A check is judged
by its latest runs only: an entry is skipped when another of the same name, type and `workflowName`
has a strictly later readable `startedAt` (the guard's rule; a tie or an unreadable one stays).

`pending --holder <h>` reads the delivery's ledger (`land_tally`): `wait` or `spent` (the last check read
that was pending used up `PENDING_WAITS`: reads before the lock reset on any other answer, reads under it never).
`red --holder <h> --worktree-path <w> --integration-branch <i>` answers what a red check read does next: `stale`
(the first poll after a rerun of the failed jobs), else `sync` (the worktree is behind `origin/<i>`, after a fetch,
and the lock is held) or `presync` (behind, no lock), else `checks` (a red-check fix was already entered in some
attempt of the delivery) or `fix`; `failing` carries the names of the latest check read and `behind` is true when
the worktree is behind. `lock-budget --holder <h>` answers `again` or `spent` by the lock wait budget of the
current attempt, with `waits` the contended answers counted. `sync-fixes --holder <h>` answers `spent` when a sync
review fix was already entered in any attempt of the delivery, else `fix`. Each of the four is `error` (`no_run`,
`no_attempt`, `ledger_unreadable`) when the ledger cannot be counted.

`free --repo <owner/name> --integration-branch <i> --holder <h>` frees the land lock of `<i>` when it is at a sha
the current attempt's lock steps held (`land_tally.locked_shas`): `released` (freed, free already, at another sha,
or the delivery has no attempt) or `unreleased` (any failure, `detail`); it never answers `error`. `release
--repo-root <path> --issue <n> --repo <owner/name> --holder <h> --items <json>` frees it the same way after a call
of the attempt (the attempt is the run `items[0].run` names, else the current one) and answers `items[0].end` when
it is one of `RELEASE_ENDS` (else `land`), or `unreleased`; it never answers `error` either.

`head --worktree-path <w>` prints `clean` or `dirty` (`git status --porcelain` prints anything) with `head`, the
worktree's `HEAD`. `probe --worktree-path <w> --integration-branch <i>` fetches `origin`, then runs `git merge-tree
--write-tree --name-only --no-messages HEAD origin/<i>` and prints `clean` (exit 0, `origin/<i>` an ancestor of
`HEAD`), `behind` (exit 0, not an ancestor) or `conflicted` (exit 1 whose first line is a 40 hex tree id; `files`
the remaining non-empty lines); any other exit or output is `error` `probe_failed`, for exit 1 alone proves no
conflict. It changes nothing in the worktree or its index. `merge-of --worktree-path <w> --integration-branch <i>`
runs no fetch and reads M, the newest first-parent merge commit of `HEAD`: `none` (no M, or `origin/<i>` is not an
ancestor of `HEAD`, `merge_commit` empty), `clean` (`HEAD` is M and a fresh merge of M's parents has M's tree) or
`review` (a conflicted merge, an evil merge, or commits on top of M); `merge_commit` is M and `head` is `HEAD`.

`fixed --status X --start-head S --commit C --tests T --notes N --head H` reads a fix reply: `untested` (C is not
empty and not H, and `T` is not a JSON list with at least one non-blank string), else `not-done` (X is not `done`,
S is not H or C is empty), else `unchanged` (C is H with non-blank N), `silent` (C is H with blank N) or `committed`.

`merge-state --repo <o/n> --pr <n>` reads `mergeStateStatus`: `behind` (`BEHIND`), `blocked` (`BLOCKED`) or `other`,
with `state` the raw string; a missing or non-string value is `error`. `pr-head --repo <o/n> --pr <n> --head <sha>`
prints `pushed` (the pull request's `headRefOid` is `<sha>`) or `head-moved`, with `remote`; a missing one is
`error`.

`LANDING_BOUND_SECONDS`, when a decimal integer from 0 up, replaces the check poll bound and the land lock wait
bound for the process (0: `checks` answers `pending` after one read and `lock` answers `contended` without
waiting); any other value is ignored.

`criteria_close(body)` and `placement(repo_root, issue)` are the policy the engine's later
steps import: whether the issue's criteria let a pull request close it, and the branch, the
worktree path, the integration branch and the tracker slug of the issue.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from collections.abc import Iterator, Mapping
from pathlib import Path

from agent_tools.claims import forge_land_lock
from agent_tools.delivery import engine_ledger, issue_branch, land_tally
from agent_tools.project_contract import resolve_project
from agent_tools.system import forge_api
from agent_tools.verification import verified_tree

GIT_TIMEOUT = 120
CHECK_POLL_SECONDS = 30
CHECK_BOUND_SECONDS = 3000
CHECK_FIELDS = "headRefOid,statusCheckRollup"
GREEN_CONCLUSIONS = ("SUCCESS", "SKIPPED", "NEUTRAL")
UNSETTLED_STATES = ("PENDING", "EXPECTED")
# GitHub's `YYYY-MM-DDTHH:MM:SSZ`, a year from 1970 on (the guard's `ROLLUP_STARTED_AT_PATTERN`).
TREE_ID = re.compile(r"^[0-9a-f]{40}$")
STARTED_AT = re.compile(r"^(19[7-9][0-9]|[2-9][0-9]{3})-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
LOCK_HELD = ("already_held", "moved")
# The ends of a land attempt that `release` passes on once the lock is free.
RELEASE_ENDS = ("done", "land", "claim-lost", "claim", "head-moved", "checks", "checks-pending", "checks-fix",
                "checks-fix-review", "sync", "sync-contention", "sync-review", "sync-fix", "land-contended",
                "merge", "unreleased-lock")
# The poll's clock and sleep, module level so a test can move time (as forge_land_lock does).
monotonic = time.monotonic
sleep = time.sleep
PULL_FIELDS = "number,headRefOid,baseRefName,url"
MERGE_FIELDS = "state,headRefOid,mergeCommit"
CRITERIA_HEADING = re.compile(r"^##\s+acceptance criteria\s*$", re.IGNORECASE)
HEADING = re.compile(r"^##\s")
CRITERION = re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s*(?:\[([a-z]+)\])?")
REMOVED_FROM_TITLE = re.compile("[\"'$`\\\\!\r\n]")
# The variables that select another repository than the one `-C` names (a copy of the engine's list).
REPOSITORY_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                  "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE",
                  "GIT_PREFIX", "GIT_IMPLICIT_WORK_TREE")


class Failure(Exception):
    """A closed failure: the code, its detail and whether a retry may succeed."""

    def __init__(self, code: str, detail: object, transient: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.transient = transient


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        emit({"verdict": "error", "error": "usage", "transient": False, "detail": message})
        raise SystemExit(2)


def emit(value: Mapping) -> None:
    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def criteria_close(body: str) -> bool:
    """True when the body has a criterion under `## Acceptance criteria` and each is `[code]` or `[note]`."""
    kinds: list[str | None] = []
    inside = False
    for line in body.splitlines():
        if CRITERIA_HEADING.match(line.strip()):
            inside = True
        elif HEADING.match(line):
            inside = False
        elif inside and (found := CRITERION.match(line)):
            kinds.append(found[1])
    return bool(kinds) and all(kind in ("code", "note") for kind in kinds)


def safe_title(title: str) -> str:
    """The title with every character the guard refuses in a quoted word removed."""
    return re.sub(" +", " ", REMOVED_FROM_TITLE.sub("", title)).strip()


def _resolve(repo_root: str) -> dict:
    try:
        return resolve_project.resolve(repo_root)
    except resolve_project.ContractError as error:
        raise Failure("resolver_refused", {"code": error.code, "repair_id": error.repair_id,
                                           "violations": error.violations}) from None


def placement(repo_root: str, issue: int) -> dict:
    """{branch, worktree_path, integration_branch, slug} of the issue, as `issue-branch` derives them."""
    snapshot = _resolve(repo_root)
    try:
        derived = issue_branch.derive(repo_root, issue)
    except issue_branch.BranchRefusal as refusal:
        wrapped = refusal.detail if isinstance(refusal.detail, dict) else {}
        raise Failure(refusal.code, refusal.detail,
                      refusal.transient or wrapped.get("transient") is True) from None
    return {"branch": derived["branch"], "worktree_path": derived["worktree_path"],
            "integration_branch": snapshot["bindings"]["vcs"]["integration_branch"],
            "slug": snapshot["bindings"]["tracker"]["repo_slug"]}


@contextmanager
def _own_repository() -> Iterator[None]:
    """Run with `REPOSITORY_ENV` removed from the process environment, restored on exit."""
    held = {name: os.environ.pop(name) for name in REPOSITORY_ENV if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(held)


def _git(root: str, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if k not in REPOSITORY_ENV}
    try:
        done = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT, check=False, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise Failure("git_failed", "timeout", transient=True) from None
    except OSError as error:
        raise Failure("git_failed", str(error)) from None
    if done.returncode != 0:
        raise Failure("git_failed", done.stderr.strip())
    return done.stdout


def _forge(argv: list[str]):
    try:
        return forge_api.gh_json(argv)
    except forge_api.ForgeError as error:
        raise Failure(error.code, error.detail, error.transient) from None


def prepare(args: argparse.Namespace) -> dict:
    place = placement(args.repo_root, args.issue)
    issue = _forge(["api", f"repos/{args.repo}/issues/{args.issue}"])
    if not isinstance(issue, dict) or not isinstance(issue.get("title"), str):
        raise Failure("payload_invalid", "the issue title is not a string")
    body = issue.get("body")
    closes = criteria_close(body if isinstance(body, str) else "")
    path = place["worktree_path"]
    head = _git(path, "rev-parse", "HEAD").strip()
    clean = not _git(path, "status", "--porcelain").strip()
    try:
        with _own_repository():
            recorded = verified_tree.read_record(verified_tree.record_path(Path(path)))
            tree = verified_tree.current_tree(Path(path))
    except verified_tree.VerifiedTreeError as error:
        raise Failure("verified_tree_failed", str(error)) from None
    ready = clean and recorded is not None and recorded["tree"] == tree
    detail = ("the worktree is clean and its tree is the verified one" if ready
              else "the worktree is dirty" if not clean
              else "the worktree's tree is not the recorded verified tree")
    return {"verdict": "ready" if ready else "unverified", "branch": place["branch"],
            "worktree_path": path, "integration_branch": place["integration_branch"],
            "head": head, "title": safe_title(issue["title"]), "closes": closes,
            "body": f"{'Closes' if closes else 'Refs'} #{args.issue}. Delivered by the engine.",
            "detail": detail}


def pushed(args: argparse.Namespace) -> dict:
    ref = f"refs/heads/{args.branch}"
    lines = _git(args.repo_root, "ls-remote", "origin", ref).splitlines()
    remote = next((line.split()[0] for line in lines if line.split()[1:] == [ref]), None)
    if remote is None:
        return {"verdict": "absent"}
    if remote == args.head:
        return {"verdict": "pushed"}
    return {"verdict": "head-moved", "remote": remote}


def pull(args: argparse.Namespace) -> dict:
    listing = _forge(["pr", "list", "--repo", args.repo, "--head", args.branch, "--state", "open",
                      "--json", PULL_FIELDS])
    if not isinstance(listing, list) or not all(isinstance(entry, dict) for entry in listing):
        raise Failure("payload_invalid", "the pull request list is not an array of objects")
    into = [entry for entry in listing if entry.get("baseRefName") == args.integration_branch]
    if not into:
        return {"verdict": "absent"}
    if len(into) > 1:
        raise Failure("ambiguous_pull", [entry.get("number") for entry in into])
    only = into[0]
    if not isinstance(only.get("number"), int) or not isinstance(only.get("headRefOid"), str):
        raise Failure("payload_invalid", "the pull request has no number or head")
    return {"verdict": "open", "pr": only["number"], "head": only["headRefOid"],
            "url": only.get("url") or ""}


def merged(args: argparse.Namespace) -> dict:
    view = _forge(["pr", "view", str(args.pr), "--repo", args.repo, "--json", MERGE_FIELDS])
    if not isinstance(view, dict) or not isinstance(view.get("state"), str):
        raise Failure("payload_invalid", "the pull request has no state")
    head = view.get("headRefOid") if isinstance(view.get("headRefOid"), str) else ""
    if view["state"] != "MERGED":
        return {"verdict": "open", "head": head}
    commit = view.get("mergeCommit")
    oid = commit.get("oid") if isinstance(commit, dict) else None
    if not isinstance(oid, str):
        raise Failure("payload_invalid", "the merged pull request has no merge commit")
    return {"verdict": "merged", "merge_commit": oid, "head": head}


def _land_lock(action: str, args: argparse.Namespace, *, wait: bool) -> tuple[int, dict]:
    """`forge_land_lock.run` on arguments built here; a forge failure is a `Failure`."""
    return _lock_call(action, args.repo, args.integration_branch, args.head, wait=wait)


def _lock_call(action: str, repo: str, branch: str, sha: str | None, *, wait: bool = False) -> tuple[int, dict]:
    request = argparse.Namespace(action=action, repo=repo, branch=branch, sha=sha, wait=wait,
                                 release=False, follow_head=False)
    try:
        status, answer = forge_land_lock.run(request)
    except forge_api.ForgeError as error:
        raise Failure(error.code, error.detail, error.transient) from None
    if not isinstance(answer, dict) or not isinstance(answer.get("verdict"), str):
        raise Failure("payload_invalid", "the land lock answered no verdict")
    return status, answer


def _lock_reading(status: int, answer: dict, held: Mapping[str, str]) -> dict:
    """The verdict of an acquire answer: `held` maps the lock verdicts that are not contention."""
    if status == 2 and answer.get("error") == "no_open_pr":
        return {"verdict": "no-pull", "lock": answer}
    if status == 2:
        raise Failure("usage", answer.get("detail"))
    if status == 0 and answer["verdict"] in held:
        return {"verdict": held[answer["verdict"]], "lock": answer}
    if status == 3:
        return {"verdict": "contended", "lock": answer}
    raise Failure("payload_invalid", f"the land lock answered exit {status}: {answer['verdict']}")


def lock(args: argparse.Namespace) -> dict:
    status, answer = _land_lock("acquire", args, wait=True)
    return _lock_reading(status, answer, {"acquired": "held", "already_held": "held", "moved": "held"})


def held(args: argparse.Namespace) -> dict:
    status, answer = _land_lock("acquire", args, wait=False)
    return _lock_reading(status, answer, {"acquired": "retaken", "already_held": "held", "moved": "held"})


def unlock(args: argparse.Namespace) -> dict:
    try:
        status, answer = _land_lock("release", args, wait=False)
    except Failure as failure:
        return {"verdict": "unreleased", "detail": f"{failure.code}: {failure.detail}"}
    if (status, answer["verdict"]) in ((0, "released"), (3, "not_held")):
        return {"verdict": "released", "lock": answer}
    return {"verdict": "unreleased", "detail": f"the land lock answered exit {status}: {answer['verdict']}"}


def _tally(read, *args):
    """`read(*args)` of `land_tally`, a `TallyError` made a `Failure`."""
    try:
        return read(*args)
    except land_tally.TallyError as error:
        raise Failure(error.code, error.detail) from None


def _git_exit(root: str, *args: str) -> tuple[int, str]:
    """`git -C root args` as (exit status, stdout); a failure to run it is a `Failure`."""
    env = {k: v for k, v in os.environ.items() if k not in REPOSITORY_ENV}
    try:
        done = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT, check=False, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise Failure("git_failed", "timeout", transient=True) from None
    except OSError as error:
        raise Failure("git_failed", str(error)) from None
    return done.returncode, done.stdout if done.returncode in (0, 1) else done.stderr.strip()


def _is_ancestor(worktree: str, integration_branch: str) -> bool:
    """Whether `origin/<integration_branch>` is an ancestor of the worktree's `HEAD`, as it is now."""
    status, detail = _git_exit(worktree, "merge-base", "--is-ancestor", f"origin/{integration_branch}", "HEAD")
    if status not in (0, 1):
        raise Failure("git_failed", detail)
    return status == 0


def _is_behind(worktree: str, integration_branch: str) -> bool:
    """Whether `origin/<integration_branch>`, fetched now, is not an ancestor of the worktree's `HEAD`."""
    _git(worktree, "fetch", "origin")
    return not _is_ancestor(worktree, integration_branch)


def pending(args: argparse.Namespace) -> dict:
    attempt = _tally(land_tally.current, args.holder)
    spent = land_tally.pending_spent(_tally(land_tally.transitions, attempt))
    return {"verdict": "spent" if spent else "wait"}


def red(args: argparse.Namespace) -> dict:
    attempt = _tally(land_tally.current, args.holder)
    trans = _tally(land_tally.transitions, attempt)
    latest = _tally(land_tally.latest_result, attempt, land_tally.CHECK_STEPS)
    failing = latest.get("failing") if isinstance(latest, dict) else None
    failing = failing if isinstance(failing, list) else []
    behind = _is_behind(args.worktree_path, args.integration_branch)
    if land_tally.stale_eligible(trans):
        verdict = "stale"
    elif behind:
        verdict = "sync" if land_tally.held(trans) else "presync"
    elif _tally(land_tally.entered, _tally(land_tally.attempts, args.holder), land_tally.CI_FIX) >= 1:
        verdict = "checks"
    else:
        verdict = "fix"
    return {"verdict": verdict, "failing": failing, "behind": behind}


def lock_budget(args: argparse.Namespace) -> dict:
    runs = _tally(land_tally.lock_answers, _tally(land_tally.current, args.holder))
    return {"verdict": "again" if land_tally.lock_budget(runs) else "spent",
            "waits": sum(len(run) for run in runs)}


def sync_fixes(args: argparse.Namespace) -> dict:
    spent = _tally(land_tally.entered, _tally(land_tally.attempts, args.holder), land_tally.SYNC_FIX) >= 1
    return {"verdict": "spent" if spent else "fix"}


def _free(repo: str, integration_branch: str, run_dir: Path | None) -> dict:
    """Free the land lock when it is at a sha the run's lock steps held; `run_dir` None frees nothing."""
    try:
        shas = land_tally.locked_shas(run_dir) if run_dir is not None else set()
        status, reading = _lock_call("status", repo, integration_branch, None)
        sha = reading.get("lock_sha")
        if status != 0 or reading["verdict"] == "free" or sha not in shas:
            return {"verdict": "released"}
        status, answer = _lock_call("release", repo, integration_branch, sha)
    except (Failure, land_tally.TallyError) as failure:
        return {"verdict": "unreleased", "detail": f"{failure.code}: {failure.detail}"}
    if (status, answer["verdict"]) in ((0, "released"), (3, "not_held")):
        return {"verdict": "released", "lock": answer}
    return {"verdict": "unreleased", "detail": f"the land lock answered exit {status}: {answer['verdict']}"}


def _current_or_none(holder: str) -> Path | None:
    try:
        return land_tally.current(holder)
    except land_tally.TallyError as error:
        if error.code in ("no_run", "no_attempt"):
            return None
        raise


def free(args: argparse.Namespace) -> dict:
    try:
        run_dir = _current_or_none(args.holder)
    except land_tally.TallyError as error:
        return {"verdict": "unreleased", "detail": f"{error.code}: {error.detail}"}
    return _free(args.repo, args.integration_branch, run_dir)


def release(args: argparse.Namespace) -> dict:
    try:
        items = json.loads(args.items)
        first = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
        named = first.get("run")
        run_dir = engine_ledger.runs_root() / named if isinstance(named, str) and named \
            and Path(named).name == named else None
        if run_dir is None or not run_dir.is_dir():
            run_dir = _current_or_none(args.holder)
        branch = placement(args.repo_root, args.issue)["integration_branch"]
    except (Failure, land_tally.TallyError) as failure:
        return {"verdict": "unreleased", "detail": f"{failure.code}: {failure.detail}"}
    except ValueError as error:
        return {"verdict": "unreleased", "detail": f"the items are not JSON: {error}"}
    freed = _free(args.repo, branch, run_dir)
    if freed["verdict"] != "released":
        return freed
    end = first.get("end")
    return {"verdict": end if end in RELEASE_ENDS else "land"}


def _entry_name(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return None
    name = entry.get("name") if entry.get("__typename") == "CheckRun" else entry.get("context")
    return name if isinstance(name, str) else None


def _entry_state(entry: dict) -> str:
    """`green`, `red` (settled and not green) or `pending` (still running or unknown)."""
    if entry.get("__typename") == "CheckRun":
        if entry.get("status") != "COMPLETED":
            return "pending"
        return "green" if entry.get("conclusion") in GREEN_CONCLUSIONS else "red"
    state = entry.get("state")
    if state == "SUCCESS":
        return "green"
    return "pending" if state in UNSETTLED_STATES or not isinstance(state, str) else "red"


def _started(entry: dict) -> str | None:
    """The entry's `startedAt` when it is a readable UTC instant from 1970 on, else None."""
    started = entry.get("startedAt")
    if isinstance(started, str) and STARTED_AT.match(started):
        try:
            datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None
        return started
    return None


def _latest_runs(entries: list[dict]) -> list[dict]:
    """The entries of one check that no later run supersedes: the guard's rule (its `latest_runs`).

    An entry drops only when another of its group (same type and string `workflowName`) has a
    strictly later readable `startedAt` and its own is readable; a tie and an unstamped entry stay."""
    def group(entry: dict) -> tuple:
        workflow = entry.get("workflowName")
        return entry.get("__typename"), workflow if isinstance(workflow, str) else None

    latest: dict[tuple, str] = {}
    for entry in entries:
        stamp = _started(entry)
        if stamp is not None and (group(entry) not in latest or stamp > latest[group(entry)]):
            latest[group(entry)] = stamp
    return [entry for entry in entries
            if _started(entry) is None or _started(entry) == latest[group(entry)]]


def _rollup_reading(rollup: object, declared: list[str]) -> tuple[str, list[str]]:
    """(`green`, `red` or `pending`, the names of the failing checks) of one rollup read.

    Each check is judged by its latest runs only, as the guard's floor judges it."""
    if not isinstance(rollup, list) or not all(_entry_name(entry) for entry in rollup):
        raise Failure("payload_invalid", "the check rollup is not a list of named checks")
    entries: dict[str, list[dict]] = {}
    for entry in rollup:
        entries.setdefault(_entry_name(entry), []).append(entry)
    groups = {name: [_entry_state(entry) for entry in _latest_runs(runs)] for name, runs in entries.items()}
    if declared:
        groups = {name: groups.get(name, ["pending"]) for name in declared}
    failing = sorted(name for name, states in groups.items() if "red" in states)
    if failing:
        return "red", failing
    settled = bool(groups) and all(state == "green" for states in groups.values() for state in states)
    return ("green" if settled else "pending"), []


def checks(args: argparse.Namespace) -> dict:
    declared = _resolve(args.repo_root)["bindings"]["vcs"]["merge"].get("required_checks") or []
    started = monotonic()
    while True:
        view = _forge(["pr", "view", str(args.pr), "--repo", args.repo, "--json", CHECK_FIELDS])
        if not isinstance(view, dict) or not isinstance(view.get("headRefOid"), str):
            raise Failure("payload_invalid", "the pull request has no head")
        if view["headRefOid"] != args.head:
            return {"verdict": "moved", "remote": view["headRefOid"]}
        verdict, failing = _rollup_reading(view.get("statusCheckRollup"), declared)
        if verdict == "red":
            return {"verdict": "red", "failing": failing}
        if verdict == "green":
            return {"verdict": "green"}
        if monotonic() - started >= CHECK_BOUND_SECONDS:
            return {"verdict": "pending"}
        sleep(CHECK_POLL_SECONDS)


def head(args: argparse.Namespace) -> dict:
    sha = _git(args.worktree_path, "rev-parse", "HEAD").strip()
    dirty = bool(_git(args.worktree_path, "status", "--porcelain").strip())
    return {"verdict": "dirty" if dirty else "clean", "head": sha}


def probe(args: argparse.Namespace) -> dict:
    _git(args.worktree_path, "fetch", "origin")
    status, out = _git_exit(args.worktree_path, "merge-tree", "--write-tree", "--name-only", "--no-messages",
                            "HEAD", f"origin/{args.integration_branch}")
    if status == 0:
        return {"verdict": "clean" if _is_ancestor(args.worktree_path, args.integration_branch) else "behind",
                "files": []}
    lines = out.splitlines() if status == 1 else []
    if lines and TREE_ID.match(lines[0]):
        return {"verdict": "conflicted", "files": [line for line in lines[1:] if line]}
    raise Failure("probe_failed", f"merge-tree answered exit {status}: {out}")


def merge_of(args: argparse.Namespace) -> dict:
    path = args.worktree_path
    sha = _git(path, "rev-parse", "HEAD").strip()
    merge = _git(path, "rev-list", "--first-parent", "--min-parents=2", "--max-count=1", "HEAD").strip()
    if not merge or not _is_ancestor(path, args.integration_branch):
        return {"verdict": "none", "merge_commit": "", "head": sha}
    status, out = _git_exit(path, "merge-tree", "--write-tree", f"{merge}^1", f"{merge}^2")
    tree = _git(path, "rev-parse", f"{merge}^{{tree}}").strip()
    clean = sha == merge and status == 0 and out.splitlines()[:1] == [tree]
    return {"verdict": "clean" if clean else "review", "merge_commit": merge, "head": sha}


def fixed(args: argparse.Namespace) -> dict:
    try:
        tests = json.loads(args.tests)
    except ValueError:
        tests = None
    tested = isinstance(tests, list) and any(isinstance(test, str) and test.strip() for test in tests)
    if args.commit and args.commit != args.head and not tested:
        return {"verdict": "untested"}
    if args.status != "done" or args.start_head != args.head or not args.commit:
        return {"verdict": "not-done"}
    if args.commit == args.head:
        return {"verdict": "unchanged" if args.notes.strip() else "silent"}
    return {"verdict": "committed"}


def merge_state(args: argparse.Namespace) -> dict:
    view = _forge(["pr", "view", str(args.pr), "--repo", args.repo, "--json", "mergeStateStatus"])
    state = view.get("mergeStateStatus") if isinstance(view, dict) else None
    if not isinstance(state, str):
        raise Failure("payload_invalid", "the pull request has no merge state")
    return {"verdict": {"BEHIND": "behind", "BLOCKED": "blocked"}.get(state, "other"), "state": state}


def pr_head(args: argparse.Namespace) -> dict:
    view = _forge(["pr", "view", str(args.pr), "--repo", args.repo, "--json", "headRefOid"])
    remote = view.get("headRefOid") if isinstance(view, dict) else None
    if not isinstance(remote, str):
        raise Failure("payload_invalid", "the pull request has no head")
    return {"verdict": "pushed" if remote == args.head else "head-moved", "remote": remote}


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="landing", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    def number(text: str) -> int:
        if not text.isdigit() or int(text) < 1:
            raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}")
        return int(text)

    sub = commands.add_parser("prepare")
    sub.add_argument("--repo-root", required=True)
    sub.add_argument("--issue", required=True, type=number)
    sub.add_argument("--repo", required=True)
    sub = commands.add_parser("pushed")
    sub.add_argument("--repo-root", required=True)
    sub.add_argument("--branch", required=True)
    sub.add_argument("--head", required=True)
    sub = commands.add_parser("pull")
    sub.add_argument("--repo", required=True)
    sub.add_argument("--branch", required=True)
    sub.add_argument("--integration-branch", required=True)
    sub = commands.add_parser("merged")
    sub.add_argument("--repo", required=True)
    sub.add_argument("--pr", required=True, type=number)
    sub.add_argument("--head", required=True)
    for name in ("lock", "held", "unlock"):
        sub = commands.add_parser(name)
        sub.add_argument("--repo", required=True)
        sub.add_argument("--integration-branch", required=True)
        sub.add_argument("--head", required=True)
    for name in ("pending", "lock-budget", "sync-fixes"):
        sub = commands.add_parser(name)
        sub.add_argument("--holder", required=True)
    sub = commands.add_parser("red")
    sub.add_argument("--holder", required=True)
    sub.add_argument("--worktree-path", required=True)
    sub.add_argument("--integration-branch", required=True)
    sub = commands.add_parser("free")
    sub.add_argument("--repo", required=True)
    sub.add_argument("--integration-branch", required=True)
    sub.add_argument("--holder", required=True)
    sub = commands.add_parser("release")
    sub.add_argument("--repo-root", required=True)
    sub.add_argument("--issue", required=True, type=number)
    sub.add_argument("--repo", required=True)
    sub.add_argument("--holder", required=True)
    sub.add_argument("--items", required=True)
    sub = commands.add_parser("head")
    sub.add_argument("--worktree-path", required=True)
    for name in ("probe", "merge-of"):
        sub = commands.add_parser(name)
        sub.add_argument("--worktree-path", required=True)
        sub.add_argument("--integration-branch", required=True)
    sub = commands.add_parser("fixed")
    for name in ("status", "start-head", "commit", "tests", "notes", "head"):
        sub.add_argument(f"--{name}", required=True)
    sub = commands.add_parser("merge-state")
    sub.add_argument("--repo", required=True)
    sub.add_argument("--pr", required=True, type=number)
    sub = commands.add_parser("pr-head")
    sub.add_argument("--repo", required=True)
    sub.add_argument("--pr", required=True, type=number)
    sub.add_argument("--head", required=True)
    sub = commands.add_parser("checks")
    sub.add_argument("--repo-root", required=True)
    sub.add_argument("--repo", required=True)
    sub.add_argument("--pr", required=True, type=number)
    sub.add_argument("--head", required=True)
    return parser


COMMANDS = {"prepare": prepare, "pushed": pushed, "pull": pull, "merged": merged, "lock": lock,
            "checks": checks, "held": held, "unlock": unlock, "pending": pending, "red": red,
            "lock-budget": lock_budget, "sync-fixes": sync_fixes, "free": free, "release": release,
            "head": head, "probe": probe, "merge-of": merge_of, "fixed": fixed, "merge-state": merge_state,
            "pr-head": pr_head}


def _apply_bound() -> None:
    """`LANDING_BOUND_SECONDS`, a decimal integer from 0 up, bounds the check poll and the lock wait."""
    text = os.environ.get("LANDING_BOUND_SECONDS", "")
    if text.isascii() and text.isdigit():
        global CHECK_BOUND_SECONDS
        CHECK_BOUND_SECONDS = forge_land_lock.BOUND = int(text)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _apply_bound()
    try:
        emit(COMMANDS[args.command](args))
    except Failure as failure:
        emit({"verdict": "error", "error": failure.code, "transient": failure.transient,
              "detail": failure.detail})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
