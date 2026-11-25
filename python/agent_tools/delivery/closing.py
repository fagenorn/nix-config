"""`closing`: the steps an engine closes one merged issue out with, each an act that never forces.

Every call prints exactly one compact JSON object on one stdout line with a `verdict`.
Exit 0 carries any verdict but `error`; exit 1 is `error` (`{verdict, error, transient,
detail}`, `error` the closed code, `transient` true for a failure worth retrying); a usage
error is exit 2 with `error` `usage`. Nothing here forces, resets, stashes or deletes by force.

`read --repo-root <path> --issue <n> --repo <owner/name> [--head <sha>]` reads `gh pr list --head
<branch> --state merged` and prints `merged` (`branch`, `worktree_path`, `integration_branch`,
`closes` from the issue body as `landing.prepare` reads it, `pr`, `merge_commit`) or `unmerged`.
Given `--head`, only a merged pull request whose head is `<sha>` counts, so an earlier merged pull
request on the same branch at another head is `unmerged`.

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

The four `hold-*` subcommands read what the close-out hold decides from and post, edit,
label, file and close nothing. Every flag is the member name of the procedure input that feeds it; a
JSON-valued flag is strict JSON (no repeated key, no NaN), and one that does not parse is a usage error.

`hold-facts --repo-root <path> --repo <owner/name> --issue <n> --pr <n> --merge-commit <sha>` reads the
issue body: `bad-kinds` (`acs`) when a criterion's kind is not code, evidence, human or note; `closes` when
`landing.criteria_close` holds, after that one read; else it fetches origin and checks the merge commit
(`absent-merge` when the checkout lacks it) and prints `open` with `criteria`, `open` (evidence and human
ones), `verification`, `blocks`, `pr_head`, `pr_branch`, `workflows` and `posted` (`holding.posted_fences`).
Both verdicts carry `closes` (true for `closes`, false for `open`): the criteria the close step goes by, read
now, since an issue edited after `read` must not be closed on the earlier answer.

`hold-graded --verdict <v> --code-unmet <json> --acceptance <json> --criteria <json>` re-reads the regrade's whole
reply against the criteria: `unmet` (`code_unmet`: the ids it names, every graded criterion with `met` false and
every `code` criterion the reply does not grade) when the verdict is not `met` or any id is unmet, else `met`.

`hold-look --repo <owner/name> --issue <n> --pr <n> --pr-head <sha> --merge-commit <sha> --posted <json>`
prints `stale` (`answered`, `stale`) when the owner's approved look answers a criterion that a posted fence
the hold may not rewrite still checks, else `clear` (`answered`: the look-marked criteria when the look is
approved, else none).

`hold-gate --repo-root <path> --issue <n> --merge-commit <sha> --criteria <json> --posted <json> --blocks
<json> --answered <json> --written <json>` prints the `holding.gate` dict as is: `ready` or the refusal
verdict (`missing-checks`, `human-checks`, `unattended`, `owner-checks`, `script-checks`, `note-checks`).

`hold-lint --repo-root <path> --repo <owner/name> --issue <n> --pr-head <sha> --pr-branch <b> --workflows
<json> --blocks <json> --answered <json> --block <json> --split <json>` prints `valid` or `invalid` with
`lints`, one `{issue, ac, ok, errors}` for the parent block (its posted fence less the checks naming an
answered criterion, else `--block`, skipped when null) and for each `--split` entry (the child's posted
fence, else the entry's block, linted with no blocked issues).

The write-side `hold-*` subcommands post, label, file, close and run. Each is idempotent by
itself, because the engine owes a check only to an arrival a rewind discarded: a second call with the same
flags posts, files, labels and closes nothing more. Each prints the members its check prints (the engine
stores the check's document as the step's result), and its check changes nothing.

`hold-split --repo <owner/name> --issue <n> --pr <n> --merge-commit <sha> --split <json>` (`--split`: the
`hold-gate` list of `{ac, block}`) files, for each entry in order, the open `needs-verification` issue whose
body starts `Split from #<n>: <AC> after the merge <sha>.` unless one exists, then posts its hold comment
unless it has a fence: `split` or `none` (an empty `--split`), with `children`, one `{ac, issue}` per entry.
`hold-split-check` (same flags) prints `split` or `none` with the same `children` when every entry has its
child holding a fence, else `absent`.

`hold-post --repo --issue --pr --merge-commit --criteria <json> --answered <json> --block <json> --children
<json>` posts the hold comment of `--block` (naming the criteria its checks name) unless the issue has a
fence; when it has one whose checks name an answered criterion it edits those checks, and their lines, out
in place: `posted` with `comment_id` and the `block` as it stands. A null `--block` (every open criterion was
split) posts `Delivered by PR #<pr>; the human checks are held on #<child>, ...` once and closes the issue
as completed: `closed` with a null `comment_id` and `block`. `hold-posted` (same flags) prints `posted` or
`closed` when that holds now, else `absent`.

`hold-label --repo --issue` adds `needs-verification` (creating the label) unless the issue carries it:
`labelled`; `hold-labelled` prints `labelled` or `absent`.

`hold-run --repo --issue --holder <host/..> --verdict <v> --children <json>` runs `verify-pending run` once
for each child in order, then for the issue only when `--verdict` is `posted`, on the host that is the
holder's text before its first `/`, lower-cased (`failed` with `reason` `host` and no run when that is no
hostname): `ran` or `failed` (a run exited non-zero) with `runs`, one `{issue, exit}` each, and `issue_state`
(`OPEN` or `CLOSED`), read after the runs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools.delivery import holding, landing, look_marker
from agent_tools.delivery.landing import Failure, emit
from agent_tools.system import forge_api
from agent_tools.verification import verify_block

GIT_TIMEOUT = 120
MERGED_FIELDS = "number,mergeCommit,headRefOid"
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
    if args.head is not None:
        pulls = [pull for pull in pulls if pull.get("headRefOid") == args.head]
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


def _body(slug: str, number: int) -> str:
    body = _issue(slug, number).get("body")
    return body if isinstance(body, str) else ""


def hold_facts(args: argparse.Namespace) -> dict:
    body = _body(args.repo, args.issue)
    every = holding.criteria(body)
    bad = [item["id"] for item in every if item["kind"] not in holding.KINDS]
    if bad:
        return {"verdict": "bad-kinds", "acs": bad}
    if landing.criteria_close(body):
        return {"verdict": "closes", "closes": True}
    _git(args.repo_root, "fetch", "origin")
    if _run(args.repo_root, "cat-file", "-e", f"{args.merge_commit}^{{commit}}").returncode != 0:
        return {"verdict": "absent-merge"}
    return {"verdict": "open", "closes": False, "criteria": every,
            "open": [item for item in every if item["kind"] in holding.OPEN_KINDS],
            "verification": holding.verification(args.repo_root),
            "blocks": holding.blocking(args.repo, args.issue),
            **holding.pr_facts(args.repo, args.pr),
            "posted": holding.posted_fences(args.repo, args.issue, args.merge_commit)}


def hold_graded(args: argparse.Namespace) -> dict:
    graded = {entry["id"].upper() for entry in args.acceptance}
    refused = [entry["id"] for entry in args.acceptance if entry["met"] is not True]
    ungraded = [item["id"] for item in args.criteria if item.get("kind") == "code" and item["id"].upper() not in graded]
    unmet = list(dict.fromkeys([*args.code_unmet, *refused, *ungraded]))
    return {"verdict": "unmet" if args.verdict != "met" or unmet else "met", "code_unmet": unmet}


def hold_look(args: argparse.Namespace) -> dict:
    body = _body(args.repo, args.issue)
    answered: list[str] = []
    if look_marker.read_look(body).marked:
        status = holding.look_status(repo=args.repo, issue=args.issue, pr=args.pr, head=args.pr_head,
                                     merge=args.merge_commit)
        if status.get("verdict") == "approved":
            answered = holding.look_acs(body)
    entries = holding.stale(args.posted, answered, args.issue, holding.criteria(body))
    return {"verdict": "stale", "answered": answered, "stale": entries} if entries else {
        "verdict": "clear", "answered": answered}


def hold_gate(args: argparse.Namespace) -> dict:
    return holding.gate(criteria=args.criteria, posted=args.posted, blocks=args.blocks, answered=args.answered,
                        written=args.written, merge=args.merge_commit, issue=args.issue,
                        verification=holding.verification(args.repo_root))


def hold_lint(args: argparse.Namespace) -> dict:
    return holding.lint_all(repo_root=args.repo_root, repo=args.repo, issue=args.issue, pr_head=args.pr_head,
                            pr_branch=args.pr_branch, workflows=args.workflows, blocks=args.blocks,
                            answered=args.answered, block=args.block, split=args.split)


def hold_split(args: argparse.Namespace) -> dict:
    return holding.file_split(args.repo, args.issue, args.pr, args.merge_commit, args.split)


def hold_split_check(args: argparse.Namespace) -> dict:
    return holding.split_state(args.repo, args.issue, args.merge_commit, args.split)


def hold_post(args: argparse.Namespace) -> dict:
    return holding.post_hold(args.repo, args.issue, args.pr, args.merge_commit, args.criteria, args.answered,
                             args.block, args.children)


def hold_posted(args: argparse.Namespace) -> dict:
    return holding.post_state(args.repo, args.issue, args.answered, args.block)


def hold_label(args: argparse.Namespace) -> dict:
    holding.label_hold(args.repo, args.issue)
    return {"verdict": "labelled"}


def hold_labelled(args: argparse.Namespace) -> dict:
    return {"verdict": "labelled" if holding.label_state(args.repo, args.issue) else "absent"}


def hold_run(args: argparse.Namespace) -> dict:
    host = args.holder.split("/", 1)[0].lower()
    if not verify_block.HOST.fullmatch(host):
        return {"verdict": "failed", "reason": "host"}
    wanted = [child["issue"] for child in args.children] + ([args.issue] if args.verdict == "posted" else [])
    runs = [{"issue": number, "exit": holding.verify_run(host, args.repo, number)} for number in wanted]
    state = str(_issue(args.repo, args.issue).get("state", "")).upper()
    return {"verdict": "ran" if all(run["exit"] == 0 for run in runs) else "failed", "runs": runs,
            "issue_state": state}


def _json(text: str):
    try:
        return json.loads(text, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal)
    except (ValueError, RecursionError) as error:
        raise argparse.ArgumentTypeError(f"not strict JSON: {error}") from None


def _shaped(name: str, check):
    """A JSON flag type: strict JSON that `check` accepts."""
    def parse(text: str):
        value = _json(text)
        if not check(value):
            raise argparse.ArgumentTypeError(f"not a {name}")
        return value
    return parse


def _each(item):
    return lambda value: isinstance(value, list) and all(item(entry) for entry in value)


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value) -> bool:
    return isinstance(value, str)


def _is_criterion(value) -> bool:
    return (isinstance(value, dict) and _text(value.get("id")) and _text(value.get("text"))
            and (value.get("kind") is None or _text(value.get("kind"))))


def _is_posted(value) -> bool:
    return (isinstance(value, dict) and _int(value.get("issue")) and isinstance(value.get("checks"), list)
            and isinstance(value.get("results"), bool) and (value.get("merge") is None or _text(value.get("merge"))))


def _is_graded(value) -> bool:
    return isinstance(value, dict) and _text(value.get("id")) and isinstance(value.get("met"), bool)


def _is_written(value) -> bool:
    return isinstance(value, dict) and _text(value.get("ac")) and _text(value.get("check"))


def _is_child(value) -> bool:
    return isinstance(value, dict) and _text(value.get("ac")) and _int(value.get("issue"))


def _is_split(value) -> bool:
    return isinstance(value, dict) and _text(value.get("ac")) and "block" in value


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
    sub.add_argument("--head")
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
    texts = _shaped("list of strings", _each(_text))
    numbers = _shaped("list of integers", _each(_int))
    hold = commands.add_parser("hold-facts")
    hold.add_argument("--repo-root", required=True)
    hold.add_argument("--repo", required=True)
    hold.add_argument("--issue", required=True, type=number)
    hold.add_argument("--pr", required=True, type=number)
    hold.add_argument("--merge-commit", required=True)
    hold = commands.add_parser("hold-graded")
    hold.add_argument("--verdict", required=True)
    hold.add_argument("--code-unmet", required=True, type=texts)
    hold.add_argument("--acceptance", required=True, type=_shaped("list of graded criteria", _each(_is_graded)))
    hold.add_argument("--criteria", required=True, type=_shaped("list of criteria", _each(_is_criterion)))
    hold = commands.add_parser("hold-look")
    hold.add_argument("--repo", required=True)
    hold.add_argument("--issue", required=True, type=number)
    hold.add_argument("--pr", required=True, type=number)
    hold.add_argument("--pr-head", required=True)
    hold.add_argument("--merge-commit", required=True)
    hold.add_argument("--posted", required=True, type=_shaped("list of posted fences", _each(_is_posted)))
    hold = commands.add_parser("hold-gate")
    hold.add_argument("--repo-root", required=True)
    hold.add_argument("--issue", required=True, type=number)
    hold.add_argument("--merge-commit", required=True)
    hold.add_argument("--criteria", required=True, type=_shaped("list of criteria", _each(_is_criterion)))
    hold.add_argument("--posted", required=True, type=_shaped("list of posted fences", _each(_is_posted)))
    hold.add_argument("--blocks", required=True, type=numbers)
    hold.add_argument("--answered", required=True, type=texts)
    hold.add_argument("--written", required=True, type=_shaped("list of written checks", _each(_is_written)))
    hold = commands.add_parser("hold-lint")
    hold.add_argument("--repo-root", required=True)
    hold.add_argument("--repo", required=True)
    hold.add_argument("--issue", required=True, type=number)
    hold.add_argument("--pr-head", required=True)
    hold.add_argument("--pr-branch", required=True)
    hold.add_argument("--workflows", required=True, type=texts)
    hold.add_argument("--blocks", required=True, type=numbers)
    hold.add_argument("--answered", required=True, type=texts)
    hold.add_argument("--block", required=True, type=_json)
    hold.add_argument("--split", required=True, type=_shaped("list of split entries", _each(_is_split)))
    split = _shaped("list of split entries", _each(_is_split))
    children = _shaped("list of split children", _each(_is_child))
    for name in ("hold-split", "hold-split-check"):
        hold = commands.add_parser(name)
        hold.add_argument("--repo", required=True)
        hold.add_argument("--issue", required=True, type=number)
        hold.add_argument("--pr", required=True, type=number)
        hold.add_argument("--merge-commit", required=True)
        hold.add_argument("--split", required=True, type=split)
    for name in ("hold-post", "hold-posted"):
        hold = commands.add_parser(name)
        hold.add_argument("--repo", required=True)
        hold.add_argument("--issue", required=True, type=number)
        hold.add_argument("--pr", required=True, type=number)
        hold.add_argument("--merge-commit", required=True)
        hold.add_argument("--criteria", required=True, type=_shaped("list of criteria", _each(_is_criterion)))
        hold.add_argument("--answered", required=True, type=texts)
        hold.add_argument("--block", required=True,
                          type=_shaped("block or null", lambda value: value is None or isinstance(value, dict)))
        hold.add_argument("--children", required=True, type=children)
    for name in ("hold-label", "hold-labelled"):
        hold = commands.add_parser(name)
        hold.add_argument("--repo", required=True)
        hold.add_argument("--issue", required=True, type=number)
    hold = commands.add_parser("hold-run")
    hold.add_argument("--repo", required=True)
    hold.add_argument("--issue", required=True, type=number)
    hold.add_argument("--holder", required=True)
    hold.add_argument("--verdict", required=True)
    hold.add_argument("--children", required=True, type=children)
    return parser


COMMANDS = {"read": read, "worktree": worktree, "forward": forward, "branch": branch, "issue": issue,
            "hold-facts": hold_facts, "hold-graded": hold_graded, "hold-look": hold_look, "hold-gate": hold_gate, "hold-lint": hold_lint,
            "hold-split": hold_split, "hold-split-check": hold_split_check, "hold-post": hold_post,
            "hold-posted": hold_posted, "hold-label": hold_label, "hold-labelled": hold_labelled,
            "hold-run": hold_run}


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
