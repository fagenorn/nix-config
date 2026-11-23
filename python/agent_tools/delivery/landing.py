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
from contextlib import contextmanager
from collections.abc import Iterator, Mapping
from pathlib import Path

from agent_tools.delivery import issue_branch
from agent_tools.project_contract import resolve_project
from agent_tools.system import forge_api
from agent_tools.verification import verified_tree

GIT_TIMEOUT = 120
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
    return parser


COMMANDS = {"prepare": prepare, "pushed": pushed, "pull": pull, "merged": merged}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        emit(COMMANDS[args.command](args))
    except Failure as failure:
        emit({"verdict": "error", "error": failure.code, "transient": failure.transient,
              "detail": failure.detail})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
