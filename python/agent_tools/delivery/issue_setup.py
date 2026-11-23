"""`issue-setup`: the reads and writes an engine setup of one issue makes.

Every call prints exactly one compact JSON object on one stdout line with a `verdict`.
Exit 0 carries any verdict but `error`; exit 1 is `error` (`{verdict, error, transient,
detail}`, `error` the closed code, `transient` true for a failure worth retrying); a usage
error is exit 2 with `error` `usage`.

`preflight --repo-root <path> --issue <n>` prints `{verdict, branch, worktree_path,
integration_branch, issue_text, pr, detail}`. The branch is `issue-branch`'s (it fetches
origin). The verdict is the first gate that refuses, in this order: `closed` (the issue is
not open), `parked` (it carries the label `needs-verification` or `parked`), `duplicate` (a
merged pull request whose closing references list the issue; one that only mentions it does
not count), `open-pr` (an open pull request found by searching the issue number whose head
is not the branch); else `clear`. `pr` is the number for `duplicate` and `open-pr`.

`worktree --repo-root <path> --branch <b> --worktree-path <p>` prints `{verdict, worktree,
branch, head, base_sha, status, detail}` after `git fetch origin`. It makes or adopts the
worktree: an existing worktree on the branch is adopted; else the local branch is added at
`<p>`; else the remote branch; else the branch is made from the integration branch
(`made`). `dirty` reports a worktree on the branch with changes (`status` holds the first 40
lines of `git status --porcelain`); `mismatch` is `<p>` on another branch, the branch
checked out at another path, or a detached HEAD that is not at the branch tip with a clean
tree. A clean detached HEAD at the branch tip is switched back to the branch (`adopted`).
It never resets, cleans, restores, stashes or deletes.

`worktree-check` takes the same flags and makes the same judgement with no fetch and no
change: `absent`, `adopted`, `dirty` or `mismatch`. A clean detached HEAD at the branch tip is
`absent` there, so a recheck runs `worktree`, which reattaches it.

`note --repo <owner/name> --issue <n> --evidence <text>` posts `<text>` as one issue
comment: `{verdict: "posted", comment_id}`.

`read --repo-root <path> --repo <owner/name> --issue <n>` prints
`{verdict: "read", text, body, marked, lane_paths}`: `text` is `issue_text(issue, comments)`
(the title, the body and every comment in order), `body` the issue body (`""` when null),
`marked` whether the body carries a look marker (`look_marker`), and `lane_paths` the
repository's lane path sets (`lane_paths`, null when none are declared). The engine's lane
step grades these members by the lane rule.

`lane --repo-root <path> --repo <owner/name> --issue <n>` prints `{verdict, reason}`, `verdict`
`direct` or `standard`: the lane rule (`lane_rule`) applied to the issue body, the look marker
read by `look_marker`, and the repository's `.github/lane-paths.json`. That file is
`{"version": 1, "sets": {<name>: [<entry>, ...]}}`: each name matches `[a-z0-9][a-z0-9-]*`,
each set is a non-empty list of path entries (a directory ends in `/`; no leading `/`, no `.`
or `..` segment). A missing or malformed file declares no lane paths, so every issue is standard.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_tools.delivery import issue_branch, lane_rule, look_marker
from agent_tools.project_contract import resolve_project
from agent_tools.system import forge_api

GIT_TIMEOUT = 120
STATUS_LINES = 40
LANE_PATHS = ".github/lane-paths.json"
PARKED_LABELS = ("needs-verification", "parked")
PR_FIELDS = "number,state,headRefName,closingIssuesReferences"
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


def issue_text(issue: Mapping, comments: Sequence[Mapping]) -> str:
    """The title, the body, then each comment under `## Comment <index>`, in order."""
    parts = [f"# {issue.get('title') or ''}", issue.get("body") or ""]
    for index, comment in enumerate(comments, 1):
        parts += [f"## Comment {index}", comment.get("body") or ""]
    return "\n\n".join(parts)


def judge(issue: Mapping, pulls: Sequence[Mapping], branch: str, number: int) -> tuple[str, int | None]:
    """The first refusing gate for the issue, with the pull request number when one decides it."""
    if str(issue.get("state", "")).lower() != "open":
        return "closed", None
    if any(label.get("name") in PARKED_LABELS for label in issue.get("labels") or ()):
        return "parked", None
    for pull in pulls:
        referenced = {ref.get("number") for ref in pull.get("closingIssuesReferences") or ()}
        if pull.get("state") == "MERGED" and number in referenced:
            return "duplicate", pull.get("number")
    for pull in pulls:
        if pull.get("state") == "OPEN" and pull.get("headRefName") != branch:
            return "open-pr", pull.get("number")
    return "clear", None


def _refusal(refusal: issue_branch.BranchRefusal) -> Failure:
    """`issue-branch`'s refusal as a failure; a forge failure it wrapped keeps its own flag."""
    wrapped = refusal.detail if isinstance(refusal.detail, dict) else {}
    return Failure(refusal.code, refusal.detail, refusal.transient or wrapped.get("transient") is True)


def _forge_failure(error: forge_api.ForgeError) -> Failure:
    return Failure(error.code, error.detail, error.transient)


def _issue(slug: str, number: int) -> dict:
    issue = forge_api.api_get(f"repos/{slug}/issues/{number}")
    if not isinstance(issue, dict):
        raise forge_api.ForgeError("payload_invalid", "issue is not an object")
    return issue


def _comments(slug: str, number: int) -> list[dict]:
    comments = [c for page in forge_api.api_pages(f"repos/{slug}/issues/{number}/comments?per_page=100")
                for c in page]
    if not all(isinstance(c, dict) for c in comments):
        raise forge_api.ForgeError("payload_invalid", "comment is not an object")
    return comments


def _resolve(repo_root: str) -> dict:
    try:
        return resolve_project.resolve(repo_root)
    except resolve_project.ContractError as error:
        raise Failure("resolver_refused", {"code": error.code, "repair_id": error.repair_id,
                                           "violations": error.violations}) from None


def preflight(args: argparse.Namespace) -> dict:
    snapshot = _resolve(args.repo_root)
    try:
        derived = issue_branch.derive(args.repo_root, args.issue)
    except issue_branch.BranchRefusal as refusal:
        raise _refusal(refusal) from None
    slug = snapshot["bindings"]["tracker"]["repo_slug"]
    branch = derived["branch"]
    try:
        issue = _issue(slug, args.issue)
        pulls = forge_api.gh_json(["pr", "list", "--repo", slug, "--state", "all", "--search",
                                   str(args.issue), "--json", PR_FIELDS])
        if not isinstance(pulls, list):
            raise forge_api.ForgeError("payload_invalid", "pull request list is not an array")
        comments = _comments(slug, args.issue)
    except forge_api.ForgeError as error:
        raise _forge_failure(error) from None
    verdict, pr = judge(issue, pulls, branch, args.issue)
    detail = {"clear": "the issue may be delivered", "closed": "the issue is not open",
              "parked": "the issue is parked or awaits verification",
              "duplicate": f"pull request {pr} merged and closes the issue",
              "open-pr": f"pull request {pr} is open for the issue on another branch"}[verdict]
    return {"verdict": verdict, "branch": branch, "worktree_path": derived["worktree_path"],
            "integration_branch": snapshot["bindings"]["vcs"]["integration_branch"],
            "issue_text": issue_text(issue, comments), "pr": pr, "detail": detail}


def read(args: argparse.Namespace) -> dict:
    try:
        issue = _issue(args.repo, args.issue)
        text = issue_text(issue, _comments(args.repo, args.issue))
    except forge_api.ForgeError as error:
        raise _forge_failure(error) from None
    body = issue.get("body") or ""
    return {"verdict": "read", "text": text, "body": body, "marked": look_marker.read_look(body).marked,
            "lane_paths": lane_paths(args.repo_root)}


def lane_paths(repo_root: str) -> dict[str, list[str]] | None:
    """The repository's declared lane path sets, or None when the file is absent or malformed."""
    try:
        data = json.loads(Path(repo_root, LANE_PATHS).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    sets = data.get("sets")
    if (set(data) != {"version", "sets"} or type(data["version"]) is not int or data["version"] != 1
            or not isinstance(sets, dict) or not sets):
        return None
    for name, entries in sets.items():
        if (re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) is None or not isinstance(entries, list)
                or not entries or not all(_entry(e) for e in entries)):
            return None
    return sets


def _entry(entry: object) -> bool:
    return (isinstance(entry, str) and re.fullmatch(lane_rule.SHAPE, entry) is not None
            and not entry.startswith("/") and not {".", ".."} & set(entry.split("/")))


def lane(args: argparse.Namespace) -> dict:
    try:
        body = _issue(args.repo, args.issue).get("body")
    except forge_api.ForgeError as error:
        raise _forge_failure(error) from None
    chosen = lane_rule.choose(body, marked=look_marker.read_look(body).marked,
                              lane_paths=lane_paths(args.repo_root))
    return {"verdict": chosen.lane, "reason": chosen.reason}


def note(args: argparse.Namespace) -> dict:
    try:
        _, out = forge_api.run_gh(["api", "-X", "POST", f"repos/{args.repo}/issues/{args.issue}/comments",
                                   "-f", f"body={args.evidence}"])
        comment = json.loads(out)
    except forge_api.ForgeError as error:
        raise _forge_failure(error) from None
    except ValueError:
        raise Failure("payload_invalid", "the comment reply is not JSON") from None
    if not isinstance(comment, dict) or "id" not in comment:
        raise Failure("payload_invalid", "the comment reply has no id")
    return {"verdict": "posted", "comment_id": comment["id"]}


def _git(root: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in REPOSITORY_ENV}
    try:
        done = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT, check=False, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise Failure("git_failed", "timeout") from None
    except OSError as error:
        raise Failure("git_failed", str(error)) from None
    if check and done.returncode != 0:
        raise Failure("git_failed", done.stderr.strip())
    return done


def _worktrees(root: str) -> list[dict]:
    entries = []
    for block in _git(root, "worktree", "list", "--porcelain").stdout.split("\n\n"):
        entry: dict = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            entry[key] = value or True
        if "worktree" in entry:
            entry["real"] = os.path.realpath(entry["worktree"])
            entries.append(entry)
    return entries


def _rev(root: str, ref: str) -> str | None:
    done = _git(root, "rev-parse", "--verify", "--quiet", ref, check=False)
    return done.stdout.strip() if done.returncode == 0 else None


def _judge_worktree(args: argparse.Namespace) -> tuple[str, str]:
    """(verdict, detail) of the worktree at the path, from what git holds now; no change.

    The verdict is internal `detached` for a clean detached HEAD at the branch tip: `worktree`
    reattaches it as `adopted`, `worktree-check` reports it `absent` so a recheck runs `worktree`.
    """
    wanted = os.path.realpath(args.worktree_path)
    ref = f"refs/heads/{args.branch}"
    entries = _worktrees(args.repo_root)
    here = next((e for e in entries if e["real"] == wanted), None)
    elsewhere = next((e for e in entries if e.get("branch") == ref and e["real"] != wanted), None)
    if elsewhere is not None:
        return "mismatch", f"{args.branch} is checked out at {elsewhere['worktree']}"
    if here is None:
        return "absent", "no worktree at the path"
    path = here["worktree"]
    clean = not _git(path, "status", "--porcelain").stdout.strip()
    if here.get("branch") == ref:
        return ("adopted", "the worktree is on the branch") if clean else ("dirty", "the worktree has changes")
    if "detached" in here:
        if clean and here.get("HEAD") == _rev(args.repo_root, ref):
            return "detached", "a clean detached HEAD at the branch tip"
        return "mismatch", "the worktree is on a detached HEAD that is not the branch tip"
    return "mismatch", f"the worktree is on {here.get('branch', 'another branch')}"


def _report(args: argparse.Namespace, verdict: str, detail: str, integration: str,
            made_base: str | None = None) -> dict:
    out = {"verdict": verdict, "worktree": args.worktree_path, "branch": args.branch,
           "head": "", "base_sha": "", "status": "", "detail": detail}
    if verdict in ("made", "adopted", "dirty"):
        path = args.worktree_path
        out["head"] = _git(path, "rev-parse", "HEAD").stdout.strip()
        if made_base is not None:
            out["base_sha"] = made_base
        else:
            base = _git(path, "merge-base", f"origin/{integration}", "HEAD", check=False)
            out["base_sha"] = base.stdout.strip()
        status = _git(path, "status", "--porcelain").stdout.splitlines()[:STATUS_LINES]
        out["status"] = "\n".join(status)
    return out


def _integration(args: argparse.Namespace) -> str:
    return _resolve(args.repo_root)["bindings"]["vcs"]["integration_branch"]


def worktree_check(args: argparse.Namespace) -> dict:
    verdict, detail = _judge_worktree(args)
    if verdict == "detached":
        verdict, detail = "absent", "the worktree is detached at the branch tip and worktree reattaches it"
    return _report(args, verdict, detail, _integration(args))


def worktree(args: argparse.Namespace) -> dict:
    integration = _integration(args)
    try:
        issue_branch.fetch_origin(args.repo_root)
    except issue_branch.BranchRefusal as refusal:
        raise _refusal(refusal) from None
    verdict, detail = _judge_worktree(args)
    base = None
    if verdict == "absent":
        branch, path = args.branch, args.worktree_path
        if _rev(args.repo_root, f"refs/heads/{branch}"):
            _git(args.repo_root, "worktree", "add", path, branch)
        elif _rev(args.repo_root, f"refs/remotes/origin/{branch}"):
            _git(args.repo_root, "worktree", "add", "--no-track", "-b", branch, path, f"origin/{branch}")
        else:
            base = _rev(args.repo_root, f"refs/remotes/origin/{integration}")
            if base is None:
                raise Failure("git_failed", f"origin/{integration} does not exist")
            _git(args.repo_root, "worktree", "add", "--no-track", "-b", branch, path, f"origin/{integration}")
            return _report(args, "made", "the branch was made from the integration branch", integration, base)
        verdict, detail = "adopted", "the existing branch was checked out"
    elif verdict == "detached":
        _git(args.worktree_path, "switch", args.branch)
        verdict = "adopted"
    return _report(args, verdict, detail, integration)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="issue-setup", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    def number(text: str) -> int:
        if not text.isdigit() or int(text) < 1:
            raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}")
        return int(text)

    sub = commands.add_parser("preflight")
    sub.add_argument("--repo-root", required=True)
    sub.add_argument("--issue", required=True, type=number)
    for name in ("worktree", "worktree-check"):
        sub = commands.add_parser(name)
        sub.add_argument("--repo-root", required=True)
        sub.add_argument("--branch", required=True)
        sub.add_argument("--worktree-path", required=True)
    sub = commands.add_parser("note")
    sub.add_argument("--repo", required=True)
    sub.add_argument("--issue", required=True, type=number)
    sub.add_argument("--evidence", required=True)
    sub = commands.add_parser("read")
    sub.add_argument("--repo-root", required=True)
    sub.add_argument("--repo", required=True)
    sub.add_argument("--issue", required=True, type=number)
    sub = commands.add_parser("lane")
    sub.add_argument("--repo-root", required=True)
    sub.add_argument("--repo", required=True)
    sub.add_argument("--issue", required=True, type=number)
    return parser


COMMANDS = {"preflight": preflight, "worktree": worktree, "worktree-check": worktree_check,
            "note": note, "read": read, "lane": lane}


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
