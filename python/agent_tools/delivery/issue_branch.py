"""`issue-branch`: the branch a delivery of one issue works on (issue 748).

`issue-branch --repo-root <path> --issue <n>` prints one JSON line
`{adopted, branch, derived, worktree_path}`. It writes no file; git and gh run only
through `derive`.

`derived` renders `bindings.vcs.branch_pattern` with the title slug: at most 6 ASCII
words and 40 characters, cut at a word boundary, `untitled` when empty. After
`git fetch origin` the command re-adopts an earlier branch of the issue: a local or
origin branch that fully matches the pattern with the issue number filled in and only
`<slug>` as a wildcard. A pattern without both placeholders, or with them adjacent,
re-adopts only the derived name, and the integration and default branches never count.
The order is the derived branch, else the head of the lowest-numbered open
same-repository PR, else the newest commit. `worktree_path` is
`<worktree.root>/<worktree.prefix><branch>` under the project root.

Exit 2 refuses (`resolver_refused`, `tracker_unsupported`, `derived_is_protected`);
exit 1 is a `forge_failed` or `git_failed` failure. Both write
`{"error": {code, detail}}` to stderr.

A fetch that fails on the network (issue 999: unreachable, timed out, reset, an
unresolved host, an early EOF, a hung-up remote) is run once more after
`FETCH_RETRY_PAUSE` seconds. When it fails again, and when the fetch times out, the
`git_failed` error carries `transient: true` beside `code` and `detail`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from collections.abc import Collection, Mapping

from agent_tools.delivery import worktree_forge
from agent_tools.project_contract import resolve_project
from agent_tools.system import forge_api

SLUG_WORDS = 6
SLUG_CHARS = 40
EMPTY_SLUG = "untitled"
SLUG_CLASS = "[a-z0-9][a-z0-9-]*"
GIT_TIMEOUT = 120
FETCH_RETRY_PAUSE = 2
NETWORK_FAILURES = ("network is unreachable", "connection timed out", "connection reset",
                    "could not resolve host", "early eof", "remote end hung up")
PLACEHOLDERS = re.compile(r"(<num>|<slug>)")


class BranchRefusal(Exception):
    """One refusal or failure: a closed code, its detail and the exit code (2 refuse, 1 fail)."""

    def __init__(self, code: str, detail: object, exit_code: int, *, transient: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.exit_code = exit_code
        self.transient = transient


def title_slug(title: str) -> str:
    """At most SLUG_WORDS ASCII words within SLUG_CHARS characters, cut at a word boundary."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    words = re.findall(r"[a-z0-9]+", ascii_title)[:SLUG_WORDS]
    if not words:
        return EMPTY_SLUG
    slug = words[0][:SLUG_CHARS]
    for word in words[1:]:
        if len(slug) + 1 + len(word) > SLUG_CHARS:
            break
        slug += "-" + word
    return slug


def render(pattern: str, issue: int, slug: str) -> str:
    parts = PLACEHOLDERS.split(pattern)
    return "".join(str(issue) if p == "<num>" else slug if p == "<slug>" else p for p in parts)


def matcher(pattern: str, issue: int) -> re.Pattern[str] | None:
    """The regex of the branches of `issue` under `pattern`, or None when it cannot be exact."""
    if "<num>" not in pattern or "<slug>" not in pattern:
        return None
    if "<num><slug>" in pattern or "<slug><num>" in pattern:
        return None
    parts = PLACEHOLDERS.split(pattern)
    return re.compile("".join(
        re.escape(str(issue)) if p == "<num>" else SLUG_CLASS if p == "<slug>" else re.escape(p)
        for p in parts))


def select(derived: str, refs: Mapping[str, int], pr_heads: Mapping[str, int],
           match: re.Pattern[str] | None, excluded: Collection[str]) -> str:
    candidates = [n for n in refs
                  if n not in excluded and n != "HEAD"
                  and (n == derived or (match is not None and match.fullmatch(n)))]
    if derived in candidates:
        return derived
    with_pr = [n for n in candidates if n in pr_heads]
    if with_pr:
        return min(with_pr, key=lambda n: pr_heads[n])
    if candidates:
        return sorted(candidates, key=lambda n: (-refs[n], n))[0]
    return derived


def _git(root: str, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise BranchRefusal("git_failed", "timeout", 1, transient=args[:1] == ("fetch",)) from None
    if done.returncode != 0:
        raise BranchRefusal("git_failed", done.stderr.strip(), 1)
    return done.stdout


def network_failure(detail: object) -> bool:
    """True when git's stderr names a failure of the network rather than of the repository."""
    return isinstance(detail, str) and any(marker in detail.lower() for marker in NETWORK_FAILURES)


def fetch_origin(root: str) -> None:
    """`git fetch origin`, run once more after a pause when the network failed it."""
    try:
        _git(root, "fetch", "--quiet", "origin")
    except BranchRefusal as refusal:
        if not network_failure(refusal.detail):
            raise
    else:
        return
    time.sleep(FETCH_RETRY_PAUSE)
    try:
        _git(root, "fetch", "--quiet", "origin")
    except BranchRefusal as refusal:
        refusal.transient = refusal.transient or network_failure(refusal.detail)
        raise


def ref_dates(root: str) -> dict[str, int]:
    """Commit time per branch name over local branches and origin's, the larger time winning."""
    out = _git(root, "for-each-ref", "--format=%(refname)%00%(committerdate:unix)",
               "refs/heads", "refs/remotes/origin")
    dates: dict[str, int] = {}
    for line in out.splitlines():
        ref, _, stamp = line.partition("\0")
        for prefix in ("refs/heads/", "refs/remotes/origin/"):
            if ref.startswith(prefix):
                name = ref[len(prefix):]
                break
        else:
            continue
        if name == "HEAD" and ref.startswith("refs/remotes/origin/"):
            continue
        dates[name] = max(dates.get(name, 0), int(stamp))
    return dates


def derive(repo_root: str, issue: int) -> dict:
    try:
        snapshot = resolve_project.resolve(repo_root)
    except resolve_project.ContractError as error:
        detail = {"code": error.code, "repair_id": error.repair_id, "violations": error.violations}
        if error.reason_code is not None:
            detail["reason_code"] = error.reason_code
        raise BranchRefusal("resolver_refused", detail, 2) from None
    tracker = snapshot["bindings"]["tracker"]
    if tracker["kind"] != "github":
        raise BranchRefusal("tracker_unsupported", tracker["kind"], 2)
    slug = tracker["repo_slug"]
    try:
        payload = forge_api.api_get(f"repos/{slug}/issues/{issue}")
        if not isinstance(payload, dict) or not isinstance(payload.get("title"), str):
            raise forge_api.ForgeError("payload_invalid", "issue title is not a string")
        title = payload["title"]
        vcs = snapshot["bindings"]["vcs"]
        derived = render(vcs["branch_pattern"], issue, title_slug(title))
        excluded = {vcs["integration_branch"], vcs["default_branch"]}
        if derived in excluded:
            raise BranchRefusal("derived_is_protected", derived, 2)
        root = snapshot["project"]["root"]
        fetch_origin(root)
        refs = ref_dates(root)
        pr_heads = {b: v["number"] for b, v in worktree_forge.open_pull_heads(slug).items()}
    except forge_api.ForgeError as error:
        raise BranchRefusal("forge_failed", {"code": error.code, "detail": error.detail,
                                             "transient": error.transient}, 1) from None
    branch = select(derived, refs, pr_heads, matcher(vcs["branch_pattern"], issue), excluded)
    worktree = vcs["worktree"]
    return {"adopted": branch != derived, "branch": branch, "derived": derived,
            "worktree_path": os.path.normpath(os.path.join(root, worktree["root"], worktree["prefix"] + branch))}


def _positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="issue-branch", description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--issue", required=True, type=_positive)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        value = derive(args.repo_root, args.issue)
    except BranchRefusal as refusal:
        error = {"code": refusal.code, "detail": refusal.detail}
        if refusal.transient:
            error["transient"] = True
        sys.stderr.write(json.dumps({"error": error}, sort_keys=True, separators=(",", ":")) + "\n")
        return refusal.exit_code
    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
