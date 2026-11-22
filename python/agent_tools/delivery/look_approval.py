"""look-approval (issues 1138, 1139): post, read and judge the owner's approval of a look.

An issue whose body carries a look marker (`look_marker`) waits for the owner to look at the
pull request head before it merges. The owner's answer is a `look` marker comment on the issue.
Every call prints one JSON object on one stdout line with `command` (`look-approval`) and
`action`. Exit 0 success, 1 a refusal or a forge error, 2 usage.

    look-approval post --repo <owner/name> --issue <n> --pr <n> --head <sha> --answer <approved|changes> --message <id>
    look-approval post ... --answer fix --message <id> --words-file <path|->
    look-approval status --repo <owner/name> --issue <n> --pr <n> --head <sha> [--merge-commit <sha>]
    look-approval tick --repo <owner/name> --issue <n> --pr <n> --head <sha> [--merge-commit <sha>]
    look-approval marked --repo <owner/name> --issue <n>
    look-approval carry --repo <owner/name> --issue <n> --pr <n> --from <sha> --head <sha> [--before <path>] [--after <path>] [--picture <path> ...]
    look-approval judge            (no options; reads stdin; no network)

1. `post` writes `look_marker.approval_body(...)` with `forge_markers.post`, then reads the issue's
   markers by trusted authors; `verdict` is `posted` (exit 0) when the new comment is among them,
   else `untrusted` (exit 1: the comment stays and never counts). Output keys: `repo`, `issue`,
   `pr`, `head`, `answer`, `message`, `verdict`, `comment_id`. The answer `fix` approves the head
   with one fix and takes `--words-file <path>` (the owner's words, UTF-8; `-` reads stdin), which
   goes into the comment as `look_marker.approval_body` renders it; `--words-file` with another
   answer, `fix` without it, an unreadable file and words `approval_body` rejects are usage errors
   (exit 2) before any `gh` call. The output gains nothing.
2. `status` reads the issue body and comments and prints `verdict`: `unmarked` (the body carries no
   look marker), `approved` (the latest trusted live `look` marker naming this issue, pull request
   and head has `answer=approved`) or `needed`; a matching marker with no `answer` field approves
   nothing but, being the latest, still decides. Exit 0. Output keys: `repo`, `issue`, `pr`,
   `head`, `verdict`, `covers` (the criteria text), `answer` (the latest marker's, or null),
   `comment_id` (the latest marker's, or null) and `kept_from`. An issue object with no `body` key
   is a forge error (`payload_invalid`, exit 1), never an unmarked issue.
   When the issue is marked and no trusted live look marker names the head, but
   `look_marker.carry_candidate` names an earlier approval, `status` reads `repos/<repo>/pulls/<pr>`
   once and asks `look_marker.settle` for the pinned base B, reading through `gh api` with a 404 as
   an absent read. For a pull request merged at `head` (`look_marker.merged_head`), B is the merge
   commit's first parent, read as `tick` reads it (`look_marker.merged_under_look`:
   `repos/<repo>/commits/<merge_commit_sha>`), never the base branch after the merge. Any other pull
   request keeps the base branch tip: its `base.ref` and `repos/<repo>/branches/<ref>`
   (`commit.sha`). When it holds the
   verdict is `approved` with the candidate's `answer` and `comment_id`, and `kept_from` is the
   candidate's head; otherwise it is `needed` with `answer` and `comment_id` null. `kept_from` is
   null when the verdict does not rest on a kept approval. A failed read, an unreadable field (no
   `base.ref`, a `commit.sha` that is not 40 lowercase hex) or a malformed successful answer
   (`look_marker.Unreadable`) is a forge error (`payload_invalid` for the last two), never `needed`.
   `--merge-commit <sha>` (40 lowercase hex, a usage error otherwise) names the landing commit when
   the caller resolved it, and replaces the pull request's `merge_commit_sha` in that read: a pull
   request merged indirectly has a null `merge_commit_sha`, which alone is `payload_invalid`. It
   changes nothing else.
3. `marked` reads the issue body only (no comment, nothing posted) and prints `verdict` `marked` or
   `unmarked`, `covers` (the criteria text) and `acs` (the `AC<n>` id of each acceptance criterion whose
   body line is a look marker that `tick` ticks (`look_marker.marker_lines`), `n` its 1-based place among the checkbox lines of the first
   `Acceptance criteria` section, the id a plan and a verify block give it; a plan that rewords the
   criterion is still named by its place). Two limits are stated, not handled: an issue whose
   checkboxes are reordered by hand while its delivery waits (an `AC<n>` id is a place, so it then
   names another checkbox), and fence layouts no generator writes (a fence opened on a list bullet
   and closed on an indented line), where the console's criteria parser and the marker reader may
   disagree. Exit 0, with the same `payload_invalid` rule as
   `status`: an issue object with no `body` key is a forge error. The delivery programs (issue
   1139) use it to decide whether a delivery stops at awaiting look. Output keys: `repo`, `issue`,
   `verdict`, `covers`, `acs`.
4. `judge` reads `{"pr": <positive int>, "head": <40 lowercase hex or null>, "issues":
   [{"number": <positive int>, "body": <string or null>, "comments": [<REST issue comment>, ...]}]}`
   from stdin and prints `verdict` `admit` (exit 0) with `marked` (the numbers of the marked issues
   it admitted, ascending, possibly none), or `refuse` (exit 1) with `issue` (the first marked
   issue lacking an approval) and `covers`, or `error` (exit 2) with `error` `usage` (not
   JSON, wrong types, a bool number, a missing key) or `payload_invalid` (a trusted comment
   `forge_markers.parse` rejects) and `detail`. It starts no subprocess, reads no environment and
   makes no network call: the merge guard runs it through its wrapper (see 8 for `carry`).
5. Trust (ADR-verification-004): only comments whose `author_association` is OWNER or MEMBER are
   read, in `post` and `status` as in `judge`.
6. Usage errors are found before any `gh` call: `repo` is `<owner>/<name>` of `[A-Za-z0-9_.-]`,
   numbers are positive decimals, `head`, `answer` and `message` are those of
   `look_marker.approval_fields` (`status` and `tick` check `head` only; `marked` takes `repo` and `issue` alone); output `verdict` `error`, `error`
   `usage`, `detail`, exit 2. A forge error in `post`, `status` or `marked` prints `verdict` `error`, `error`
   (the `ForgeError` code), `detail` and `repo`, `issue`, exit 1; nothing is retried.
7. `tick` ticks the box of the look marker once the owner's approved head has merged (issue 1186).
   It reads the issue body, and decides `verdict` in this order, each after the reads it needs:
   `unmarked` (exit 0: the body has no look marker; nothing else is read), `needed` (exit 1: the
   latest trusted live `look` marker naming this issue, pull request and head is not `approved`),
   `not_merged` (exit 1: `look_marker.merged_head` of `repos/<repo>/pulls/<pr>` is not `head`),
   `already` (exit 0: no unticked look-marker line remains) or `ticked` (exit 0: one PATCH of the
   issue body, `look_marker.tick_markers` of it, is written). A look-marker line inside a fence and
   every other criterion keep their boxes. That PATCH is the only write, made only for `ticked`.
   Output keys: `repo`, `issue`, `pr`, `head`, `verdict`, `covers` (the criteria text), `ticked`
   (the boxes this call ticked, 0 unless `ticked`) and `kept_from`. `head` is checked as in
   `status` before any `gh` call.
   When no marker names the head and there is no `look_marker.carry_candidate`, the verdict is
   `needed` with no pull read. With a candidate, the pull is read: `not_merged` when its merged
   head is not `head`; otherwise `look_marker.merged_under_look` decides, with the base B the merge
   commit's first parent, never the base branch after the merge. True goes on to `already` or
   `ticked` as an exact approval does, with `kept_from` the candidate's head; False is `needed`
   with no write. A failed read, or `look_marker.Unreadable` (`payload_invalid`), is a forge error
   (exit 1) with no write. `kept_from` is null when the verdict does not rest on a kept approval.
   `--merge-commit <sha>` is read as `status` reads it.
8. `judge` takes an optional key `carry: {"base": <40 lowercase hex>, "reads": {<path>: <JSON>}}`:
   any other shape (not an object, a missing or extra key, a base that is not 40 lowercase hex,
   `reads` not an object, a `reads` key for which `look_marker.read_path_ok(key, base)` is false)
   is `usage` (exit 2). The reads are the guard's: `judge` never reads the network or the
   environment. A refusal (exit 1) adds, after `covers` and each only when non-empty, `candidates`
   (`[{"issue", "head", "answer"}, ...]`, the carry candidates of the failing issues) and then
   `need` (the paths a further carry run must read). An admit is unchanged.
9. `carry` (issue 1566) records the carry line that lets the owner's approval of `--from` stand at
   `--head` when only merges of the integration branch came in and the re-rendered pictures are
   unchanged. `--from` and `--head` are 40 lowercase hex and different, and each `--before`, `--after`
   and `--picture` (a picture with no role) is a file read whole, at least one in all (the ids are
   `look_marker.picture_id`, the digest `look_marker.picture_digest` over each id with its role, so
   a card whose before and after pictures swapped is another card); a break of these, an unreadable
   file included, is a usage error (exit 2) before any `gh` call.
   Output keys, in order: `command`, `action`, `repo`, `issue`, `pr`, `head`, `verdict`, `from` (the
   head of the latest approval, or null), `reason` (null unless `needed`), `pictures` (the digest of
   the given files) and `comment_id` (or null). `verdict`, decided in this order after the reads each
   needs: `unmarked` (exit 0: nothing else read), `approved` (0: a trusted live exact `approved`
   marker names `--head`; nothing posted), `needed` (0) with `reason` `no-approval` (no candidate or
   one that is not an `approved` answer), `source-differs` (the candidate's head is not `--from`: the
   command records only the interval the caller checked), `no-pictures` (the approval names none),
   `pictures-differ` (its digest is not the given files') or, after one read of the pull request
   and of the compares, `not-merges`; `moved` (exit 1: the pull request is not open or its head is
   not `--head`); then `carried` (0) with the comment id of the carry line, an existing one posting
   nothing. Otherwise one line is written with `forge_markers.write` (one post, at most one delete
   of its own comment) and read back through the trusted authors: the own comment present is
   `carried`, absent is `untrusted` (exit 1); a lost write names the smallest trusted live line, so
   every writer that reports `carried` names the same one, and no such line is `untrusted`. A forge
   error is the `status` forge error, `look_marker.Unreadable` being `payload_invalid`. `carry`
   never posts a `look` marker and never reads the look file set.
"""
import argparse
import json
import re
import sys
from collections.abc import Callable
from typing import Any, NoReturn

from agent_tools.claims import forge_markers
from agent_tools.console import inbox
from agent_tools.delivery import look_marker as lm
from agent_tools.system import forge_api

COMMAND = "look-approval"
VERBS = ("post", "status", "tick", "marked", "carry", "judge")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
NUMBER = re.compile(r"[0-9]+")
USAGE = 2


class UsageError(Exception):
    """The arguments or the stdin payload break the contract; carries the detail."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def _repo(value: str) -> str:
    if not REPO.fullmatch(value):
        raise argparse.ArgumentTypeError(f"{value!r} is not <owner>/<name>")
    return value


def _number(value: str) -> int:
    if not (NUMBER.fullmatch(value) and value.isascii() and int(value) > 0):
        raise argparse.ArgumentTypeError(f"{value!r} is not a positive decimal number")
    return int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog=COMMAND, description=__doc__)
    verbs = parser.add_subparsers(dest="action", required=True)
    for name in ("post", "status", "tick"):
        sub = verbs.add_parser(name)
        sub.add_argument("--repo", required=True, type=_repo)
        sub.add_argument("--issue", required=True, type=_number)
        sub.add_argument("--pr", required=True, type=_number)
        sub.add_argument("--head", required=True)
        if name != "post":
            sub.add_argument("--merge-commit", default=None)
        if name == "post":
            sub.add_argument("--answer", required=True)
            sub.add_argument("--message", required=True)
            sub.add_argument("--words-file", default=None)
    sub = verbs.add_parser("marked")
    sub.add_argument("--repo", required=True, type=_repo)
    sub.add_argument("--issue", required=True, type=_number)
    sub = verbs.add_parser("carry")
    sub.add_argument("--repo", required=True, type=_repo)
    sub.add_argument("--issue", required=True, type=_number)
    sub.add_argument("--pr", required=True, type=_number)
    sub.add_argument("--head", required=True)
    sub.add_argument("--from", dest="from_head", required=True)
    for flag in ("--before", "--after", "--picture"):
        sub.add_argument(flag, action="append", default=[])
    verbs.add_parser("judge")
    return parser


def emit(out: dict[str, Any]) -> None:
    print(json.dumps(out, sort_keys=False, separators=(",", ":")))


def usage_out(action: str | None, detail: str) -> int:
    emit({"command": COMMAND, "action": action, "verdict": "error", "error": "usage", "detail": detail})
    return USAGE


def forge_out(args: argparse.Namespace, error: forge_api.ForgeError) -> int:
    emit({"command": COMMAND, "action": args.action, "repo": args.repo, "issue": args.issue,
          "verdict": "error", "error": error.code, "detail": error.detail})
    return 1


def _words(args: argparse.Namespace) -> str | None:
    """The owner's fix words of `--words-file` (`-` is stdin); None without the option."""
    if args.words_file is None:
        return None
    if args.answer != "fix":
        raise UsageError("--words-file goes with the answer fix and no other")
    try:
        if args.words_file == "-":
            return sys.stdin.read()
        with open(args.words_file, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, ValueError) as error:
        raise UsageError(f"the words file {args.words_file!r} is unreadable: {error}") from None


def post(args: argparse.Namespace) -> int:
    body = lm.approval_body(args.issue, args.pr, args.head, args.answer, args.message, args.words)
    comment_id = forge_markers.post(args.repo, args.issue, body)
    seen = forge_markers.list_markers(args.repo, args.issue, lm.TRUSTED)
    trusted = any(m.comment_id == comment_id for m in seen)
    emit({"command": COMMAND, "action": "post", "repo": args.repo, "issue": args.issue, "pr": args.pr,
          "head": args.head, "answer": args.answer, "message": args.message,
          "verdict": "posted" if trusted else "untrusted", "comment_id": comment_id})
    return 0 if trusted else 1


def _issue_body(args: argparse.Namespace) -> str | None:
    issue = forge_api.gh_json(["api", f"repos/{args.repo}/issues/{args.issue}"])
    if not isinstance(issue, dict) or "body" not in issue or not (
            issue["body"] is None or isinstance(issue["body"], str)):
        raise forge_api.ForgeError("payload_invalid", "issue body is missing or not a string or null")
    return issue["body"]


def marked(args: argparse.Namespace) -> int:
    body = _issue_body(args)
    look = lm.read_look(body)
    emit({"command": COMMAND, "action": "marked", "repo": args.repo, "issue": args.issue,
          "verdict": "marked" if look.marked else "unmarked", "covers": list(look.covers),
          "acs": _look_acs(body)})
    return 0


def _look_acs(body: str) -> list[str]:
    """The AC ids of the acceptance criteria whose body line is a look marker `tick` will tick, in body order."""
    recognized = lm.marker_lines(body)
    return [inbox.ac_id(c) for c in inbox.acceptance_criteria(body or "") if c.line + 1 in recognized]


def _reader(repo: str) -> Callable[[str], Any]:
    """A carry read of `repos/<repo>/<path>`: the parsed JSON, None for a 404."""
    return lambda path: forge_api.gh_json(["api", f"repos/{repo}/{path}"], allow=(404,))


def _base_tip(args: argparse.Namespace, pull: Any) -> str:
    """The tip of the given pull request's base branch: the pinned base B of `status` for a pull not merged at the head."""
    base = pull.get("base") if isinstance(pull, dict) else None
    ref = base.get("ref") if isinstance(base, dict) else None
    if not isinstance(ref, str) or not ref:
        raise forge_api.ForgeError("payload_invalid", "the pull request has no base.ref")
    branch = forge_api.gh_json(["api", f"repos/{args.repo}/branches/{ref}"])
    commit = branch.get("commit") if isinstance(branch, dict) else None
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if not (isinstance(sha, str) and lm.HEAD_PATTERN.fullmatch(sha)):
        raise forge_api.ForgeError("payload_invalid", "the base branch has no 40-hex commit.sha")
    return sha


def status(args: argparse.Namespace) -> int:
    body = _issue_body(args)
    comments = forge_markers.list_comments(args.repo, args.issue)
    look = lm.read_look(body)
    marker = lm.look_answer(comments, args.issue, args.pr, args.head)
    answer = marker.fields.get("answer") if marker else None
    comment_id = marker.comment_id if marker else None
    kept_from = None
    verdict = "unmarked" if not look.marked else "approved" if answer == "approved" else "needed"
    candidate = lm.carry_candidate(comments, args.issue, args.pr, args.head) if look.marked and marker is None else None
    if candidate is not None:
        pull = forge_api.gh_json(["api", f"repos/{args.repo}/pulls/{args.pr}"])
        try:
            if lm.merged_head(pull) == args.head:
                holds = lm.merged_under_look(comments, args.issue, args.pr, pull, _reader(args.repo), args.merge_commit)
            else:
                holds = lm.settle(candidate, args.head, _base_tip(args, pull), _reader(args.repo))
        except lm.Unreadable as error:
            raise forge_api.ForgeError("payload_invalid", str(error)) from None
        if holds:
            verdict, answer, comment_id, kept_from = "approved", candidate.answer, candidate.comment_id, candidate.head
    emit({"command": COMMAND, "action": "status", "repo": args.repo, "issue": args.issue, "pr": args.pr,
          "head": args.head, "verdict": verdict, "covers": list(look.covers), "answer": answer,
          "comment_id": comment_id, "kept_from": kept_from})
    return 0


def tick(args: argparse.Namespace) -> int:
    body = _issue_body(args)
    look = lm.read_look(body)
    base = {"command": COMMAND, "action": "tick", "repo": args.repo, "issue": args.issue, "pr": args.pr,
            "head": args.head}
    covers = list(look.covers)

    kept_from: str | None = None

    def finish(verdict: str, code: int, ticked: int = 0) -> int:
        emit({**base, "verdict": verdict, "covers": covers, "ticked": ticked, "kept_from": kept_from})
        return code

    if not look.marked:
        return finish("unmarked", 0)
    comments = forge_markers.list_comments(args.repo, args.issue)
    marker = lm.look_answer(comments, args.issue, args.pr, args.head)
    if marker is not None:
        if marker.fields.get("answer") != "approved":
            return finish("needed", 1)
        pull = forge_api.gh_json(["api", f"repos/{args.repo}/pulls/{args.pr}"])
        if lm.merged_head(pull) != args.head:
            return finish("not_merged", 1)
    else:
        candidate = lm.carry_candidate(comments, args.issue, args.pr, args.head)
        if candidate is None:
            return finish("needed", 1)
        pull = forge_api.gh_json(["api", f"repos/{args.repo}/pulls/{args.pr}"])
        if lm.merged_head(pull) != args.head:
            return finish("not_merged", 1)
        try:
            holds = lm.merged_under_look(comments, args.issue, args.pr, pull, _reader(args.repo), args.merge_commit)
        except lm.Unreadable as error:
            raise forge_api.ForgeError("payload_invalid", str(error)) from None
        if not holds:
            return finish("needed", 1)
        kept_from = candidate.head
    new_body, changed = lm.tick_markers(body)
    if not changed:
        return finish("already", 0)
    forge_api.run_gh(["api", "-X", "PATCH", f"repos/{args.repo}/issues/{args.issue}", "-f", "body=" + new_body])
    return finish("ticked", 0, changed)


def carry(args: argparse.Namespace) -> int:
    """Record the carry line of `--from`'s approval at `--head` once only merges came in (issue 1566)."""
    body = _issue_body(args)
    state: dict[str, Any] = {"from": None, "reason": None, "comment_id": None}

    def finish(verdict: str, code: int = 0, **found: Any) -> int:
        state.update(found)
        emit({"command": COMMAND, "action": "carry", "repo": args.repo, "issue": args.issue, "pr": args.pr,
              "head": args.head, "verdict": verdict, "from": state["from"], "reason": state["reason"],
              "pictures": args.digest, "comment_id": state["comment_id"]})
        return code

    def needed(reason: str) -> int:
        return finish("needed", reason=reason)

    if not lm.read_look(body).marked:
        return finish("unmarked")
    comments = forge_markers.list_comments(args.repo, args.issue)
    exact = lm.look_answer(comments, args.issue, args.pr, args.head)
    if exact is not None and exact.fields.get("answer") == "approved":
        return finish("approved")
    candidate = lm.carry_candidate(comments, args.issue, args.pr, args.head)
    if candidate is None or candidate.answer != "approved":
        return needed("no-approval")
    state["from"] = candidate.head
    if candidate.head != args.from_head:
        return needed("source-differs")
    if candidate.pictures is None:
        return needed("no-pictures")
    if candidate.pictures != args.digest:
        return needed("pictures-differ")
    pull = forge_api.gh_json(["api", f"repos/{args.repo}/pulls/{args.pr}"])
    head = pull.get("head") if isinstance(pull, dict) else None
    if not isinstance(pull, dict) or pull.get("state") != "open" or not isinstance(head, dict) \
            or head.get("sha") != args.head:
        return finish("moved", 1)
    try:
        holds = lm.settle_merges(args.from_head, args.head, _base_tip(args, pull), _reader(args.repo))
    except lm.Unreadable as error:
        raise forge_api.ForgeError("payload_invalid", str(error)) from None
    if not holds:
        return needed("not-merges")
    if candidate.line is not None:
        return finish("carried", comment_id=candidate.line)
    fields = lm.carry_fields(args.issue, args.pr, args.from_head, args.head, args.digest)
    result = forge_markers.write(args.repo, args.issue, lm.CARRY_KIND, fields,
                                 lm.carry_sentence(args.pr, args.from_head, args.head), match=fields,
                                 associations=lm.TRUSTED)
    if result.won:
        trusted = any(m.comment_id == result.own_id
                      for m in forge_markers.list_markers(args.repo, args.issue, lm.TRUSTED))
        return finish("carried", comment_id=result.own_id) if trusted else finish("untrusted", 1)
    if result.winner is None:
        return finish("untrusted", 1)
    return finish("carried", comment_id=result.winner.comment_id)


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _carry(value: Any) -> lm.Carry:
    if not isinstance(value, dict) or set(value) != {"base", "reads"}:
        raise UsageError("carry needs exactly the keys base and reads")
    base, served = value["base"], value["reads"]
    if not (isinstance(base, str) and lm.HEAD_PATTERN.fullmatch(base)):
        raise UsageError("carry base is not 40 lowercase hex")
    if not isinstance(served, dict):
        raise UsageError("carry reads is not an object")
    for path in served:
        if not lm.read_path_ok(path, base):
            raise UsageError(f"carry reads names a path outside the grammar: {path!r}")
    return lm.Carry(base, served)


def read_payload(text: str) -> tuple[int, str | None, list[lm.IssueFacts], lm.Carry | None]:
    try:
        data = json.loads(text)
    except ValueError:
        raise UsageError("stdin is not JSON") from None
    if not isinstance(data, dict) or not {"pr", "head", "issues"} <= set(data):
        raise UsageError("stdin needs the keys pr, head and issues")
    carry = _carry(data["carry"]) if "carry" in data else None
    pr, head, issues = data["pr"], data["head"], data["issues"]
    if not _int(pr):
        raise UsageError("pr is not a positive integer")
    if head is not None and not (isinstance(head, str) and lm.HEAD_PATTERN.fullmatch(head)):
        raise UsageError("head is not 40 lowercase hex or null")
    if not isinstance(issues, list):
        raise UsageError("issues is not an array")
    facts = []
    for item in issues:
        if (not isinstance(item, dict) or not {"number", "body", "comments"} <= set(item)
                or not _int(item["number"])
                or not (item["body"] is None or isinstance(item["body"], str))
                or not isinstance(item["comments"], list)
                or not all(isinstance(c, dict) for c in item["comments"])):
            raise UsageError("an issue needs a positive number, a string or null body and an array of comments")
        facts.append(lm.IssueFacts(item["number"], item["body"], tuple(item["comments"])))
    return pr, head, facts, carry


def judge(stdin: str) -> int:
    base = {"command": COMMAND, "action": "judge"}
    try:
        pr, head, facts, carry = read_payload(stdin)
    except UsageError as error:
        emit({**base, "verdict": "error", "error": "usage", "detail": str(error)})
        return USAGE
    try:
        verdict = lm.judge(pr, head, facts, carry)
    except forge_api.ForgeError as error:
        emit({**base, "verdict": "error", "error": error.code, "detail": error.detail})
        return USAGE
    if verdict.admit:
        emit({**base, "verdict": "admit", "marked": list(verdict.marked)})
        return 0
    out: dict[str, Any] = {**base, "verdict": "refuse", "issue": verdict.issue, "covers": list(verdict.covers)}
    if verdict.candidates:
        out["candidates"] = [{"issue": c.issue, "head": c.head, "answer": c.answer} for c in verdict.candidates]
    if verdict.need:
        out["need"] = list(verdict.need)
    emit(out)
    return 1


def _carry_usage(args: argparse.Namespace) -> None:
    """The `carry` usage checks, before any `gh` call; stores the pictures' digest on `args`."""
    for name, value in (("head", args.head), ("from", args.from_head)):
        if not (isinstance(value, str) and lm.HEAD_PATTERN.fullmatch(value)):
            raise UsageError(f"{name} {value!r} is not 40 lowercase hex")
    if args.from_head == args.head:
        raise UsageError("from and head are the same sha")
    ids: list[tuple[str | None, str]] = []
    for role, paths in (("before", args.before), ("after", args.after), (None, args.picture)):
        for path in paths:
            try:
                with open(path, "rb") as handle:
                    ids.append((role, lm.picture_id(handle.read())))
            except OSError as error:
                raise UsageError(f"the picture {path!r} is unreadable: {error}") from None
    if not ids:
        raise UsageError("carry needs at least one --before, --after or --picture")
    args.digest = lm.picture_digest(ids)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = build_parser().parse_args(argv)
        if args.action == "judge":
            return judge(sys.stdin.read())
        if args.action == "post":
            args.words = _words(args)
            lm.approval_body(args.issue, args.pr, args.head, args.answer, args.message, args.words)
        elif args.action == "carry":
            _carry_usage(args)
        elif args.action in ("status", "tick"):
            if not (isinstance(args.head, str) and lm.HEAD_PATTERN.fullmatch(args.head)):
                raise UsageError(f"head {args.head!r} is not 40 lowercase hex")
            if args.merge_commit is not None and not lm.HEAD_PATTERN.fullmatch(args.merge_commit):
                raise UsageError(f"merge commit {args.merge_commit!r} is not 40 lowercase hex")
    except (UsageError, ValueError) as error:
        return usage_out(argv[0] if argv and argv[0] in VERBS else None, str(error))
    try:
        return {"post": post, "status": status, "tick": tick, "marked": marked, "carry": carry}[args.action](args)
    except forge_api.ForgeError as error:
        return forge_out(args, error)


if __name__ == "__main__":
    sys.exit(main())
