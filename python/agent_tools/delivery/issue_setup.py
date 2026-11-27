"""`issue-setup`: the reads and writes an engine setup of one issue makes.

Every call prints exactly one compact JSON object on one stdout line with a `verdict`.
Exit 0 carries any verdict but `error`; exit 1 is `error` (`{verdict, error, transient,
detail}`, `error` the closed code, `transient` true for a failure worth retrying); a usage
error is exit 2 with `error` `usage`.

`preflight --repo-root <path> --issue <n> [--holder <h>]` prints `{verdict, branch, worktree_path,
integration_branch, issue_text, plan, pr, detail}`. The branch is `issue-branch`'s (it fetches
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

`plan-read --issue <n> --worktree-path <p> --task-numbers <json>` prints `{verdict: "read", text, digest}`: the plan the
planner wrote under `<p>/.superpowers/plans/issue-<n>/` (`plan.md`, then `task-<k>.md` for each k of the JSON list of
distinct positive integers the planner declared, in order of k under `## task-<k>.md`; another task file there, left by
an earlier plan, is never read) with its edges trimmed, and the first 16 hex digits of the SHA-256 of that text. Each
directory below `<p>` is opened relative to its parent's descriptor with no-follow semantics and only regular files
are read (a link on the way is `error` `plan_unsafe`, so is a directory or a pipe named like a plan file); a missing
`plan.md` or declared task file is `error` `plan_missing`. The files together are bounded by `PLAN_LIMIT` characters
(one comment's budget): a larger plan is `error` `plan_too_large` before any review. The review reads this text, so the
plan that is reviewed is the one `plan-note` posts.

`plan-note --repo <owner/name> --issue <n> --worktree-path <p> --holder <h> --digest <d> --task-numbers <json>` reads
the plan again and refuses with `error` `plan_changed` when its digest is not `<d>` (the files changed after the
review). Else it posts the text as one comment whose first line is `<!-- engine-plan:<digest> run:<h> -->`, `<h>` the
holder of the run that approved it: `{verdict: "posted", comment_id}`. The latest comment of the issue that carries
`<h>` answers a retry only when its whole body is that line and this text, so a retry after an interrupted post adds
no second comment, and an older plan comment of the run or an edited one never stands for the current one. It then
records the comment's id, the digest and `<h>` in `approved.json` beside the plan. The plan travels by reference (the
path), never as an argument, so no word in it reaches the lifecycle guard.

`preflight` prints `plan` too: with `--holder <h>`, the text of the plan the run `<h>` approved, else `""`. The
implementer is given that text, never a comment it picks by its marker: `plan` is the body of the comment
`approved.json` names, and only while that body still is the marker line of the recorded digest and run followed by
text of that digest, so a later comment that merely carries a marker and an edit of the approved comment are no plan.

`worktree` also makes git ignore `.superpowers/` in the repository (its `info/exclude`) when no rule does, so the
planner's untracked files never keep the worktree from being removed after the merge.

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
import contextlib
import hashlib
import json
import os
import re
import stat
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
PLAN_DIRECTORY = ".superpowers/plans"
# The characters of plan text one issue comment can hold with its marker line (the forge refuses a body over 65,536).
PLAN_LIMIT = 60000
# Beside the plan: which comment holds the plan the run approved (`plan-note` writes it, `preflight` verifies it).
PLAN_APPROVED = "approved.json"
APPROVED_LIMIT = 4096
# The first line of a plan comment, with the digest of the plan text it holds: the implementer's brief names it.
PLAN_MARKER = "<!-- engine-plan:"
# Between the digest and the closing of the first line, the run that approved the plan: its holder.
PLAN_RUN = " run:"
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
    plan = approved_plan(derived["worktree_path"], args.issue, args.holder, comments) if args.holder else ""
    detail = {"clear": "the issue may be delivered", "closed": "the issue is not open",
              "parked": "the issue is parked or awaits verification",
              "duplicate": f"pull request {pr} merged and closes the issue",
              "open-pr": f"pull request {pr} is open for the issue on another branch"}[verdict]
    return {"verdict": verdict, "branch": branch, "worktree_path": derived["worktree_path"],
            "integration_branch": snapshot["bindings"]["vcs"]["integration_branch"],
            "issue_text": issue_text(issue, comments), "plan": plan, "pr": pr, "detail": detail}


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


def _post(repo: str, issue: int, body: str) -> dict:
    try:
        _, out = forge_api.run_gh(["api", "-X", "POST", f"repos/{repo}/issues/{issue}/comments",
                                   "-f", f"body={body}"])
        comment = json.loads(out)
    except forge_api.ForgeError as error:
        raise _forge_failure(error) from None
    except ValueError:
        raise Failure("payload_invalid", "the comment reply is not JSON") from None
    if not isinstance(comment, dict) or "id" not in comment:
        raise Failure("payload_invalid", "the comment reply has no id")
    return {"verdict": "posted", "comment_id": comment["id"]}


def note(args: argparse.Namespace) -> dict:
    return _post(args.repo, args.issue, args.evidence)


def _open_below(parent: int, name: str, flags: int, shown: str, mode: int = 0o644) -> int:
    """`name` opened relative to the directory descriptor `parent`, never through a symbolic link.

    A name that is absent is `plan_missing`; one that is there but cannot be opened as the kind of file `flags`
    asks for without following a link (a link, a file where a directory is wanted) is `plan_unsafe`.
    """
    try:
        return os.open(name, flags | getattr(os, "O_NOFOLLOW", 0), mode, dir_fd=parent)
    except OSError as error:
        try:
            os.lstat(name, dir_fd=parent)
        except OSError:
            raise Failure("plan_missing", f"{shown} cannot be opened: {error}") from None
        raise Failure("plan_unsafe", f"{shown} is a symbolic link or not the kind of file expected: {error}") from None


@contextlib.contextmanager
def _plan_directory(worktree_path: str, issue: int):
    """The descriptor of the planner's directory, opened one component at a time below the worktree.

    Each directory is opened relative to its parent's descriptor with no-follow semantics, so a directory
    replaced by a link after it was checked redirects nothing: the descriptors name the directories that were
    opened, whatever the paths come to mean afterwards.
    """
    try:
        held = [os.open(worktree_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))]
    except OSError as error:
        raise Failure("plan_missing", f"the worktree {worktree_path} cannot be opened: {error}") from None
    try:
        shown = worktree_path
        for part in (*PLAN_DIRECTORY.split("/"), f"issue-{issue}"):
            shown = f"{shown}/{part}"
            held.append(_open_below(held[-1], part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0), shown))
        yield held[-1]
    finally:
        for descriptor in held:
            os.close(descriptor)


def _plain_file(directory: int, name: str, limit: int) -> bytes:
    """At most `limit` + 1 bytes of `name` below the directory descriptor: a regular file, never through a link.

    The type is read from the descriptor before anything wraps it, so a directory or a pipe named like the file
    is `plan_unsafe`, and a file larger than `limit` is never read whole.
    """
    descriptor = _open_below(directory, name, os.O_RDONLY | os.O_NONBLOCK, name)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise Failure("plan_unsafe", f"the plan file {name} is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read(limit + 1)
    except OSError as error:
        raise Failure("plan_missing", f"the plan file {name} cannot be read: {error}") from None
    finally:
        os.close(descriptor)


def _too_large(size: int) -> Failure:
    return Failure("plan_too_large", f"the plan holds more than the {PLAN_LIMIT} characters one issue comment "
                                     f"takes (at least {size})")


def plan_text(worktree_path: str, issue: int, tasks: Sequence[int]) -> str:
    """`plan.md`, then `task-<n>.md` for each declared n in order of n under `## task-<n>.md`.

    Only the declared task files are read: another `task-<k>.md` left by an earlier plan is no part of this one.
    Only regular files below real directories are read (a link on the way is `plan_unsafe`), so nothing outside
    the plan directory is published, and the files together are bounded by `PLAN_LIMIT` characters (a character
    is at most four bytes, so no read goes past four times that) before any text is built.
    """
    budget = PLAN_LIMIT * 4
    parts: list[str] = []
    with _plan_directory(worktree_path, issue) as directory:
        for name, heading in [("plan.md", None), *((f"task-{n}.md", f"## task-{n}.md") for n in sorted(tasks))]:
            data = _plain_file(directory, name, budget)
            budget -= len(data)
            if budget < 0:
                raise _too_large(PLAN_LIMIT * 4 - budget)
            try:
                parts += ([heading] if heading else []) + [data.decode("utf-8")]
            except ValueError as error:
                raise Failure("plan_missing", f"the plan file {name} cannot be read: {error}") from None
    # trimmed: the forge trims a comment's edges, so the posted body is exactly what was digested
    text = "\n\n".join(parts).strip()
    if len(text) > PLAN_LIMIT:
        raise _too_large(len(text))
    return text


def plan_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def plan_read(args: argparse.Namespace) -> dict:
    """The plan as the files hold it now with its digest: the one text the review reads and `plan-note` posts."""
    text = plan_text(args.worktree_path, args.issue, args.task_numbers)
    return {"verdict": "read", "text": text, "digest": plan_digest(text)}


def _plan_marker(digest: str, holder: str) -> str:
    return f"{PLAN_MARKER}{digest}{PLAN_RUN}{holder} -->"


def _record_approval(worktree_path: str, issue: int, comment_id: object, digest: str, holder: str) -> None:
    """Record which comment holds the approved plan, in the planner's directory (never in the issue)."""
    record = json.dumps({"comment_id": comment_id, "digest": digest, "holder": holder}, sort_keys=True)
    with _plan_directory(worktree_path, issue) as directory:
        descriptor = _open_below(directory, PLAN_APPROVED, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PLAN_APPROVED)
        try:
            os.write(descriptor, record.encode("utf-8"))
        except OSError as error:
            raise Failure("plan_missing", f"the approval record cannot be written: {error}") from None
        finally:
            os.close(descriptor)


def plan_note(args: argparse.Namespace) -> dict:
    """Post the plan the review read, once for this run: the files must still hold the text of `--digest`."""
    text = plan_text(args.worktree_path, args.issue, args.task_numbers)
    digest = plan_digest(text)
    if digest != args.digest:
        raise Failure("plan_changed", f"the plan files hold {digest}, the plan that was reviewed is {args.digest}")
    marker = _plan_marker(digest, args.holder)
    try:
        comments = _comments(args.repo, args.issue)
    except forge_api.ForgeError as error:
        raise _forge_failure(error) from None
    # this run's latest plan comment answers a retry only when it holds exactly this plan (an edited one, or an
    # older plan of the run, never does)
    mine = [c for c in comments if "id" in c
            and (first := str(c.get("body") or "").split("\n", 1)[0].strip()).startswith(PLAN_MARKER)
            and first.endswith(f"{PLAN_RUN}{args.holder} -->")]
    if mine and str(mine[-1].get("body") or "").strip() == f"{marker}\n\n{text}":
        posted = {"verdict": "posted", "comment_id": mine[-1]["id"]}
    else:
        posted = _post(args.repo, args.issue, f"{marker}\n\n{text}")
    _record_approval(args.worktree_path, args.issue, posted["comment_id"], digest, args.holder)
    return posted


def approved_plan(worktree_path: str, issue: int, holder: str, comments: Sequence[Mapping]) -> str:
    """The text of the plan the run `holder` approved, or "" when it approved none that still stands.

    The run's record (written by `plan-note`) names the comment and the digest; the plan is that comment's body
    only while it still is exactly the marker line of that digest and run followed by text of that digest. A
    later comment that merely carries a marker, and an edit of the approved comment, are therefore no plan.
    """
    try:
        with _plan_directory(worktree_path, issue) as directory:
            record = json.loads(_plain_file(directory, PLAN_APPROVED, APPROVED_LIMIT).decode("utf-8"))
    except (Failure, ValueError):
        return ""
    if not isinstance(record, dict) or record.get("holder") != holder or not isinstance(record.get("digest"), str):
        return ""
    comment = next((c for c in comments if c.get("id") == record.get("comment_id")), None)
    first, _, text = str((comment or {}).get("body") or "").strip().partition("\n\n")
    if first == _plan_marker(record["digest"], holder) and plan_digest(text) == record["digest"]:
        return text
    return ""


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


def _ignore_plans(path: str) -> None:
    """Make git ignore the planner's directory in the worktree at `path` when no rule of the repository does.

    A planner session leaves its files there untracked, and `git worktree remove` refuses such a worktree after
    the merge. The rule goes into the repository's `info/exclude` (never a tracked file) once.
    """
    probe = f"{PLAN_DIRECTORY}/issue-0/plan.md"
    if _git(path, "check-ignore", "--quiet", probe, check=False).returncode == 0:
        return
    exclude = Path(_git(path, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude").stdout.strip())
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as handle:
            handle.write(f"{PLAN_DIRECTORY.split('/')[0]}/\n")
    except OSError as error:
        raise Failure("git_failed", f"cannot write {exclude}: {error}") from None


def worktree(args: argparse.Namespace) -> dict:
    out = _worktree(args)
    if out["verdict"] in ("made", "adopted"):
        _ignore_plans(args.worktree_path)
    return out


def _worktree(args: argparse.Namespace) -> dict:
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

    def task_numbers(text: str) -> list[int]:
        try:
            value = json.loads(text)
        except ValueError:
            value = None
        if (not isinstance(value, list) or len(set(value)) != len(value)
                or not all(type(n) is int and n >= 1 for n in value)):
            raise argparse.ArgumentTypeError(f"not a JSON list of distinct positive integers: {text!r}")
        return value

    sub = commands.add_parser("preflight")
    sub.add_argument("--repo-root", required=True)
    sub.add_argument("--issue", required=True, type=number)
    sub.add_argument("--holder")
    for name in ("worktree", "worktree-check"):
        sub = commands.add_parser(name)
        sub.add_argument("--repo-root", required=True)
        sub.add_argument("--branch", required=True)
        sub.add_argument("--worktree-path", required=True)
    sub = commands.add_parser("note")
    sub.add_argument("--repo", required=True)
    sub.add_argument("--issue", required=True, type=number)
    sub.add_argument("--evidence", required=True)
    sub = commands.add_parser("plan-read")
    sub.add_argument("--issue", required=True, type=number)
    sub.add_argument("--worktree-path", required=True)
    sub.add_argument("--task-numbers", required=True, type=task_numbers)
    sub = commands.add_parser("plan-note")
    sub.add_argument("--repo", required=True)
    sub.add_argument("--issue", required=True, type=number)
    sub.add_argument("--worktree-path", required=True)
    sub.add_argument("--holder", required=True)
    sub.add_argument("--digest", required=True)
    sub.add_argument("--task-numbers", required=True, type=task_numbers)
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
            "note": note, "plan-read": plan_read, "plan-note": plan_note, "read": read, "lane": lane}


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
