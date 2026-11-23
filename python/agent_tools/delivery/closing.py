"""`closing`: the steps an engine closes one merged issue out with, each an act that never forces.

Every call prints exactly one compact JSON object on one stdout line with a `verdict`.
Exit 0 carries any verdict but `error`; exit 1 is `error` (`{verdict, error, transient,
detail}`, `error` the closed code, `transient` true for a failure worth retrying); a usage
error is exit 2 with `error` `usage`. Nothing here forces, resets, stashes or deletes by force.

`read --repo-root <path> --issue <n> --repo <owner/name>` reads `gh pr list --head <branch>
--state merged` and prints `merged` (`branch`, `worktree_path`, `integration_branch`, `closes`
from the issue body as `landing.prepare` reads it, `pr`, `merge_commit`) or `unmerged`.

`worktree --repo-root <path> --worktree-path <w>` runs `git worktree remove <w>` with no
`--force`: `removed` (removed now, or `<w>` is no worktree of the repository) or `dirty` (git
refused for changes: the worktree is kept).

`forward --repo-root <path> --integration-branch <i>` fetches origin, then fast-forwards the
checkout to `origin/<i>`: `forwarded` (also when already up to date) or `skipped` (the checkout is
not on `<i>`, or a tracked file has changes; untracked files do not count).

`branch --repo-root <path> --branch <b>` prints `gone` (no `refs/heads/<b>`) or `kept`.

`issue --repo <owner/name> --issue <n> --closes <true|false>` prints `closed` (the issue is
closed, now as `completed` and read back, or already) or `open-criteria` (`--closes false`: the
issue's criteria do not let the pull request close it, and nothing changed).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from agent_tools.delivery import landing
from agent_tools.delivery.landing import Failure, emit
from agent_tools.system import forge_api

GIT_TIMEOUT = 120
MERGED_FIELDS = "number,mergeCommit"
DIRTY = "contains modified or untracked files"


def _run(root: str, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in landing.REPOSITORY_ENV}
    try:
        return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT, check=False, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise Failure("git_failed", "timeout", transient=True) from None
    except OSError as error:
        raise Failure("git_failed", str(error)) from None


def _git(root: str, *args: str) -> str:
    done = _run(root, *args)
    if done.returncode != 0:
        raise Failure("git_failed", done.stderr.strip())
    return done.stdout


def _forge(argv: list[str]):
    try:
        return forge_api.gh_json(argv)
    except forge_api.ForgeError as error:
        raise Failure(error.code, error.detail, error.transient) from None


def _issue(slug: str, number: int) -> dict:
    issue = _forge(["api", f"repos/{slug}/issues/{number}"])
    if not isinstance(issue, dict):
        raise Failure("payload_invalid", "the issue is not an object")
    return issue


def read(args: argparse.Namespace) -> dict:
    place = landing.placement(args.repo_root, args.issue)
    pulls = _forge(["pr", "list", "--repo", args.repo, "--head", place["branch"], "--state", "merged",
                    "--json", MERGED_FIELDS])
    if not isinstance(pulls, list) or not all(isinstance(pull, dict) for pull in pulls):
        raise Failure("payload_invalid", "the pull request list is not an array of objects")
    if not pulls:
        return {"verdict": "unmerged"}
    pull = max(pulls, key=lambda entry: entry.get("number") if isinstance(entry.get("number"), int) else 0)
    commit = pull.get("mergeCommit")
    oid = commit.get("oid") if isinstance(commit, dict) else None
    if not isinstance(pull.get("number"), int) or not isinstance(oid, str):
        raise Failure("payload_invalid", "the merged pull request has no number or merge commit")
    body = _issue(args.repo, args.issue).get("body")
    return {"verdict": "merged", "branch": place["branch"], "worktree_path": place["worktree_path"],
            "integration_branch": place["integration_branch"],
            "closes": landing.criteria_close(body if isinstance(body, str) else ""),
            "pr": pull["number"], "merge_commit": oid}


def _is_worktree(root: str, path: str) -> bool:
    wanted = os.path.realpath(path)
    return any(os.path.realpath(line[len("worktree "):]) == wanted
               for line in _git(root, "worktree", "list", "--porcelain").splitlines()
               if line.startswith("worktree "))


def worktree(args: argparse.Namespace) -> dict:
    if not _is_worktree(args.repo_root, args.worktree_path):
        return {"verdict": "removed"}
    done = _run(args.repo_root, "worktree", "remove", args.worktree_path)
    if done.returncode == 0:
        return {"verdict": "removed"}
    if DIRTY in done.stderr:
        return {"verdict": "dirty"}
    raise Failure("git_failed", done.stderr.strip())


def forward(args: argparse.Namespace) -> dict:
    root, integration = args.repo_root, args.integration_branch
    _git(root, "fetch", "origin")
    if _git(root, "branch", "--show-current").strip() != integration:
        return {"verdict": "skipped"}
    if _git(root, "status", "--porcelain", "--untracked-files=no").strip():
        return {"verdict": "skipped"}
    _git(root, "merge", "--ff-only", f"origin/{integration}")
    return {"verdict": "forwarded"}


def branch(args: argparse.Namespace) -> dict:
    done = _run(args.repo_root, "rev-parse", "--verify", "--quiet", f"refs/heads/{args.branch}")
    if done.returncode == 0:
        return {"verdict": "kept"}
    if done.returncode == 1:
        return {"verdict": "gone"}
    raise Failure("git_failed", done.stderr.strip())


def issue(args: argparse.Namespace) -> dict:
    if not args.closes:
        return {"verdict": "open-criteria"}
    if str(_issue(args.repo, args.issue).get("state", "")).lower() != "closed":
        try:
            forge_api.close_issue(args.repo, args.issue, "completed")
        except forge_api.ForgeError as error:
            raise Failure(error.code, error.detail, error.transient) from None
        if str(_issue(args.repo, args.issue).get("state", "")).lower() != "closed":
            raise Failure("issue_still_open", "the issue is open after the close", transient=True)
    return {"verdict": "closed"}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        emit({"verdict": "error", "error": "usage", "transient": False, "detail": message})
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="closing", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    def number(text: str) -> int:
        if not text.isdigit() or int(text) < 1:
            raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}")
        return int(text)

    def flag(text: str) -> bool:
        if text not in ("true", "false"):
            raise argparse.ArgumentTypeError(f"not true or false: {text!r}")
        return text == "true"

    sub = commands.add_parser("read")
    sub.add_argument("--repo-root", required=True)
    sub.add_argument("--issue", required=True, type=number)
    sub.add_argument("--repo", required=True)
    sub = commands.add_parser("worktree")
    sub.add_argument("--repo-root", required=True)
    sub.add_argument("--worktree-path", required=True)
    sub = commands.add_parser("forward")
    sub.add_argument("--repo-root", required=True)
    sub.add_argument("--integration-branch", required=True)
    sub = commands.add_parser("branch")
    sub.add_argument("--repo-root", required=True)
    sub.add_argument("--branch", required=True)
    sub = commands.add_parser("issue")
    sub.add_argument("--repo", required=True)
    sub.add_argument("--issue", required=True, type=number)
    sub.add_argument("--closes", required=True, type=flag)
    return parser


COMMANDS = {"read": read, "worktree": worktree, "forward": forward, "branch": branch, "issue": issue}


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
