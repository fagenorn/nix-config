"""`look_kept_check`: the verify script that a kept look approval merged without a second one (#1211, AC6).

`python -m agent_tools.console.look_kept_check --repo OWNER/NAME --since SHA --glob GLOB [--glob GLOB ...]`
finds the first marked pull request merged after this host activated the change in which the merge
guard carried an earlier look approval across a commit that changes no look file, and reports whether
the owner was needlessly asked a second time. It reads the forge only.

Usage. `--repo` is `<owner>/<name>` of `[A-Za-z0-9_.-]`, `--since` is the 40-hex merge commit of the
change, and each `--glob` is a path glob of the console files: not empty, no leading `/`, no empty, `.`
or `..` segment. Anything else, or no `--glob`, is a usage error (exit 2), before any read.

Boundary. The boundary is `look_check`'s: T is `commit.committer.date` of the `--since` commit, A the
first recorded activation on this host, and the boundary is `max(T, A)`, so a slice merged under the old
guard is never read. When the current activation is unknown the check exits 75 `activation_unknown`
with no pull listed. The candidates are `look_check.candidates`: the closed pulls merged at or after the
boundary, ascending `(merged_at, number)`.

Listings. Pull files, pull commits and issue comments are read `?per_page=100&page=k` from k = 1 until a
page of fewer than 100 items; a page that is not a list of objects, more than 30 pages of files or a
commit listing of 250 or more (incomplete evidence) is exit 2.

Counted. A candidate counts when one of its files (`filename` or `previous_filename`) matches a `--glob`
and it has a 40-hex `merge_commit_sha` (else it is passed over, before any compare read). Its issues
are the number of an `issue-<n>-` head ref and each body line `Refs|Closes|Fixes #<n>`, ascending; one
counts when its body carries a look marker. B is the first parent of the merge commit, C the pull
request's commit list (oldest first) and M its head, which must be in C.

Answers. `pre` is the counted issue's comments created before the pull request's `merged_at`, as the
merge guard saw them. The answers are the trusted live `look` markers of `pre` naming the issue and the
pull request, in comment id order, whatever their answer; the approvals are those whose answer is in
`look_marker.CARRIED`. A trusted comment created before the merge but updated at or after it, whose
current body is a `look` marker naming the issue, has a pre-merge body this read cannot see: that is
incomplete evidence (exit 2), as is such a marker with no readable `updated_at`. Any other marker (a
`claim` that `forge-claim release` edits after the merge, say) is not an answer and is not judged.

Needless. `gains(P, h)` holds when P's head and h are in C, P's first, and some commit c of C after P's
head up to h has one parent p, a readable compare `p...c` listing at least one file and no file
matching a `--glob`. An approval R is needless when the answer just before it is an approval P,
`gains(P, R.head)` holds and `look_marker.settle` keeps P for R's head at B: the guard would have
admitted R's head under P, so asking again was needless. Any other R answered something the guard had
to ask about.

Carried. K is `look_marker.carry_candidate(pre, issue, pr, M)`, the guard's own selection. K is carried
when it exists, `gains(K, M)` holds and `settle` keeps K for M.

Landing. The first counted issue, in candidate then issue order, with a needless approval or a carried
K; every other is passed over, so a merge that rested on an exact approval of its head is never selected.
No landing is 75 `waiting`.

Output and exits: one JSON line with sorted keys; the only file written is `look_check`'s activation
record. A landing with a needless approval is 1 `not_met`, any other 0 `met`, both with `issue`, `pr`,
`approvals` (how many) and `second` (how many are needless). 75 not yet; 2 a usage error, a forge error,
a malformed answer or incomplete evidence (`{"status": "error", "detail"}`). The seams of `main` are
`get`, `activated_at` and `fixed_activation`.
"""
import argparse
import json
import re
import sys
from collections.abc import Callable
from typing import Any

from agent_tools.claims import forge_markers
from agent_tools.console import look_check
from agent_tools.console.look_check import NOT_YET, parse_time
from agent_tools.delivery import look_marker
from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

PAGE = 100
FILE_PAGES = 30
COMMIT_LIMIT = 250
CLOSES = re.compile(r"^(?:Refs|Closes|Fixes) #(\d+)\s*$", re.MULTILINE)
BRANCH = re.compile(r"issue-(\d+)-")

Get = Callable[[str], Any]


def _sha(value: Any) -> bool:
    return isinstance(value, str) and look_marker.HEAD_PATTERN.fullmatch(value) is not None


def _object(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise ForgeError("payload_invalid", f"{what} is not an object")
    return value


class Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


def _parse(argv) -> argparse.Namespace:
    parser = _Parser(prog="look_kept_check", add_help=False)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--glob", action="append", default=[])
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        raise Usage("--repo is not owner/name")
    if not look_marker.HEAD_PATTERN.fullmatch(args.since):
        raise Usage("--since is not 40 lowercase hex")
    if not args.glob:
        raise Usage("there is no --glob")
    for glob in args.glob:
        if not glob or glob.startswith("/") or any(part in ("", ".", "..") for part in glob.split("/")):
            raise Usage(f"--glob {glob!r} is outside the set-file grammar")
    return args


def _emit(code: int, out: dict) -> int:
    print(json.dumps(out, sort_keys=True))
    return code


def _pages(get: Get, path: str, max_pages: int | None = None, max_items: int | None = None) -> list[dict]:
    """Every item of a paginated listing; ForgeError for a page that is not a list of objects or a listing past its bounds."""
    items: list[dict] = []
    page = 1
    while True:
        found = get(f"{path}?per_page={PAGE}&page={page}")
        if not isinstance(found, list) or not all(isinstance(item, dict) for item in found):
            raise ForgeError("payload_invalid", f"{path} page {page} is not a list of objects")
        items.extend(found)
        if max_items is not None and len(items) >= max_items:
            raise ForgeError("payload_invalid", f"{path} lists {len(items)} items or more: incomplete evidence")
        if len(found) < PAGE:
            return items
        if max_pages is not None and page >= max_pages:
            raise ForgeError("payload_invalid", f"{path} runs past {max_pages} pages: incomplete evidence")
        page += 1


class Pull:
    """One counted pull request: its commit list C, its merged head M and the base B, read once."""

    def __init__(self, get: Get, repo: str, number: int, pull: dict, globs: list[str]):
        self.number = number
        self.globs = globs
        self.repo = repo
        self._get = get
        self._reads: dict[str, Any] = {}
        self.head = pull["head"]["sha"]
        self.merge = pull["merge_commit_sha"]
        listing = _pages(get, f"repos/{repo}/pulls/{number}/commits", max_items=COMMIT_LIMIT)
        self.order: dict[str, int] = {}
        for position, item in enumerate(listing):
            parents = item.get("parents")
            if not _sha(item.get("sha")) or not isinstance(parents, list) \
                    or not all(isinstance(p, dict) and _sha(p.get("sha")) for p in parents):
                raise ForgeError("payload_invalid", f"a commit of pull request {number} is malformed")
            self.order[item["sha"]] = position
        self.parents = {item["sha"]: tuple(p["sha"] for p in item["parents"]) for item in listing}
        if self.head not in self.order:
            raise ForgeError("payload_invalid", f"head of pull request {number} is not in its commit list")
        commit = self.read_path(f"commits/{self.merge}")
        first = commit.get("parents") if isinstance(commit, dict) else None
        first = first[0] if isinstance(first, list) and first else None
        if not isinstance(first, dict) or not _sha(first.get("sha")):
            raise ForgeError("payload_invalid", "the merge commit has no readable first parent")
        self.base = first["sha"]

    def read_path(self, path: str) -> Any:
        if path not in self._reads:
            self._reads[path] = self._get(f"repos/{self.repo}/{path}")
        return self._reads[path]

    def matches(self, name: str) -> bool:
        return any(look_marker.glob_match(glob, name) for glob in self.globs)

    def gains(self, approved: str, head: str) -> bool:
        """Whether a one-parent commit after `approved` up to `head` changes files and no look file."""
        if approved not in self.order or head not in self.order or self.order[approved] >= self.order[head]:
            return False
        for commit, position in self.order.items():
            if not self.order[approved] < position <= self.order[head]:
                continue
            parents = self.parents[commit]
            if len(parents) != 1:
                continue
            names = look_marker.compare_files(self.read_path(f"compare/{parents[0]}...{commit}"))
            if names is None:
                raise ForgeError("payload_invalid", f"compare {parents[0]}...{commit} is unreadable")
            if names and not any(self.matches(name) for name in names):
                return True
        return False

    def kept(self, candidate: look_marker.Candidate, head: str) -> bool:
        return look_marker.settle(candidate, head, self.base, self.read_path)


def _names_issue(comment: dict, issue: int) -> bool:
    """Whether a trusted comment's current body is a `look` marker naming the issue."""
    if comment.get("author_association") not in look_marker.TRUSTED:
        return False
    marker = forge_markers.parse(comment)
    return marker is not None and marker.kind == look_marker.KIND and marker.fields.get("issue") == str(issue)


def _answers(pre: list[dict], issue: int, pr: int) -> list[forge_markers.Marker]:
    parsed = [forge_markers.parse(c) for c in pre if c.get("author_association") in look_marker.TRUSTED]
    markers = [m for m in parsed if m is not None]
    named = [m for m in markers
             if m.kind == look_marker.KIND and forge_markers.is_live(m, markers)
             and m.fields.get("issue") == str(issue) and m.fields.get("pr") == str(pr)]
    return sorted(named, key=lambda m: m.comment_id)


def _grade(pull: Pull, issue: int, pre: list[dict]) -> tuple[int, int, bool]:
    """`(approvals, needless, carried)` of one counted issue."""
    answers = _answers(pre, issue, pull.number)
    approved = [m.fields.get("answer") in look_marker.CARRIED for m in answers]
    needless = 0
    for index, marker in enumerate(answers):
        if not approved[index] or index == 0 or not approved[index - 1]:
            continue
        before = answers[index - 1]
        head, earlier = marker.fields.get("head"), before.fields.get("head")
        if pull.gains(earlier, head) and pull.kept(
                look_marker.Candidate(issue, earlier, before.fields["answer"], before.comment_id), head):
            needless += 1
    found = look_marker.carry_candidate(pre, issue, pull.number, pull.head)
    carried = found is not None and pull.gains(found.head, pull.head) and pull.kept(found, pull.head)
    return sum(approved), needless, carried


def _issues(pull: dict) -> list[int]:
    found: set[int] = set()
    ref = pull["head"].get("ref")
    named = BRANCH.match(ref) if isinstance(ref, str) else None
    if named:
        found.add(int(named.group(1)))
    body = pull.get("body")
    found.update(int(n) for n in CLOSES.findall(body if isinstance(body, str) else ""))
    return sorted(found)


def landing(get: Get, repo: str, globs: list[str], boundary) -> dict | None:
    """The graded output of the first landing at or after the boundary, or None."""
    for merged, number, pull in look_check.candidates(get, repo, boundary):
        files = _pages(get, f"repos/{repo}/pulls/{number}/files", max_pages=FILE_PAGES)
        names = [n for f in files for n in (f.get("filename"), f.get("previous_filename")) if isinstance(n, str)]
        if not any(look_marker.glob_match(g, n) for g in globs for n in names):
            continue
        if not _sha(pull.get("merge_commit_sha")):
            continue
        counted = []
        for issue in _issues(pull):
            found = get(f"repos/{repo}/issues/{issue}")
            body = found.get("body") if isinstance(found, dict) else None
            if look_marker.read_look(body if isinstance(body, str) else None).marked:
                counted.append(issue)
        if not counted:
            continue
        kept = Pull(get, repo, number, pull, globs)
        for issue in counted:
            pre = []
            for comment in _pages(get, f"repos/{repo}/issues/{issue}/comments"):
                created = parse_time(comment.get("created_at"))
                if created is None:
                    raise ForgeError("payload_invalid", f"comment {comment.get('id')} has no readable created_at")
                if created < merged:
                    if _names_issue(comment, issue):
                        updated = parse_time(comment.get("updated_at"))
                        if updated is None or updated >= merged:
                            raise ForgeError("payload_invalid", f"look marker comment {comment.get('id')} was "
                                             "edited at or after the merge: its pre-merge body is unknown")
                    pre.append(comment)
            approvals, second, carried = _grade(kept, issue, pre)
            if second or carried:
                return {"approvals": approvals, "issue": issue, "pr": number, "second": second,
                        "status": "not_met" if second else "met"}
    return None


def main(argv=None, *, get=None, activated_at=None, fixed_activation=None) -> int:
    get = get or forge_api.api_get
    activated_at = activated_at or look_check.default_activated_at
    fixed_activation = fixed_activation or look_check.default_fixed_activation
    try:
        args = _parse(sys.argv[1:] if argv is None else argv)
    except Usage as error:
        return _emit(2, {"status": "error", "detail": str(error)})
    activated = activated_at()
    if activated is None:
        return _emit(NOT_YET, {"status": "activation_unknown"})
    try:
        commit = _object(get(f"repos/{args.repo}/commits/{args.since}"), "the commit")
        since = parse_time(_object(_object(commit.get("commit"), "commit")
                                              .get("committer"), "committer").get("date"))
        if since is None:
            raise ForgeError("payload_invalid", "the commit has no readable committer date")
        out = landing(get, args.repo, args.glob, max(since, fixed_activation(args.since, activated)))
    except (ForgeError, look_marker.Unreadable, KeyError, TypeError, AttributeError, ValueError) as error:
        return _emit(2, {"status": "error", "detail": str(error)[:300]})
    if out is None:
        return _emit(NOT_YET, {"status": "waiting"})
    return _emit(1 if out["status"] == "not_met" else 0, out)


if __name__ == "__main__":
    sys.exit(main())
