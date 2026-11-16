"""look-approval (issues 1138, 1139): post, read and judge the owner's approval of a look.

An issue whose body carries a look marker (`look_marker`) waits for the owner to look at the
pull request head before it merges. The owner's answer is a `look` marker comment on the issue.
Every call prints one JSON object on one stdout line with `command` (`look-approval`) and
`action`. Exit 0 success, 1 a refusal or a forge error, 2 usage.

    look-approval post --repo <owner/name> --issue <n> --pr <n> --head <sha> --answer <approved|changes> --message <id>
    look-approval status --repo <owner/name> --issue <n> --pr <n> --head <sha>
    look-approval marked --repo <owner/name> --issue <n>
    look-approval judge            (no options; reads stdin; no network)

1. `post` writes `look_marker.approval_body(...)` with `forge_markers.post`, then reads the issue's
   markers by trusted authors; `verdict` is `posted` (exit 0) when the new comment is among them,
   else `untrusted` (exit 1: the comment stays and never counts). Output keys: `repo`, `issue`,
   `pr`, `head`, `answer`, `message`, `verdict`, `comment_id`.
2. `status` reads the issue body and comments and prints `verdict`: `unmarked` (the body carries no
   look marker), `approved` (the latest trusted live `look` marker naming this issue, pull request
   and head has `answer=approved`) or `needed`; a matching marker with no `answer` field approves
   nothing but, being the latest, still decides. Exit 0. Output keys: `repo`, `issue`, `pr`,
   `head`, `verdict`, `covers` (the criteria text), `answer` (the latest marker's, or null) and
   `comment_id` (the latest marker's, or null). An issue object with no `body` key is a forge error
   (`payload_invalid`, exit 1), never an unmarked issue.
3. `marked` reads the issue body only (no comment, nothing posted) and prints `verdict` `marked` or
   `unmarked` and `covers` (the criteria text), exit 0, with the same `payload_invalid` rule as
   `status`: an issue object with no `body` key is a forge error. The delivery programs (issue
   1139) use it to decide whether a delivery stops at awaiting look. Output keys: `repo`, `issue`,
   `verdict`, `covers`.
4. `judge` reads `{"pr": <positive int>, "head": <40 lowercase hex or null>, "issues":
   [{"number": <positive int>, "body": <string or null>, "comments": [<REST issue comment>, ...]}]}`
   from stdin and prints `verdict` `admit` (exit 0) with `marked` (the numbers of the marked issues
   it admitted, ascending, possibly none), or `refuse` (exit 1) with `issue` (the first marked
   issue lacking an approval) and `covers`, or `error` (exit 2) with `error` `usage` (not
   JSON, wrong types, a bool number, a missing key) or `payload_invalid` (a trusted comment
   `forge_markers.parse` rejects) and `detail`. It starts no subprocess, reads no environment and
   makes no network call: the merge guard runs it through its wrapper.
5. Trust (ADR-verification-004): only comments whose `author_association` is OWNER or MEMBER are
   read, in `post` and `status` as in `judge`.
6. Usage errors are found before any `gh` call: `repo` is `<owner>/<name>` of `[A-Za-z0-9_.-]`,
   numbers are positive decimals, `head`, `answer` and `message` are those of
   `look_marker.approval_fields` (`status` checks `head` only; `marked` takes `repo` and `issue` alone); output `verdict` `error`, `error`
   `usage`, `detail`, exit 2. A forge error in `post`, `status` or `marked` prints `verdict` `error`, `error`
   (the `ForgeError` code), `detail` and `repo`, `issue`, exit 1; nothing is retried.
"""
import argparse
import json
import re
import sys
from typing import Any, NoReturn

from agent_tools.claims import forge_markers
from agent_tools.delivery import look_marker as lm
from agent_tools.system import forge_api

COMMAND = "look-approval"
VERBS = ("post", "status", "marked", "judge")
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
    for name in ("post", "status"):
        sub = verbs.add_parser(name)
        sub.add_argument("--repo", required=True, type=_repo)
        sub.add_argument("--issue", required=True, type=_number)
        sub.add_argument("--pr", required=True, type=_number)
        sub.add_argument("--head", required=True)
        if name == "post":
            sub.add_argument("--answer", required=True)
            sub.add_argument("--message", required=True)
    sub = verbs.add_parser("marked")
    sub.add_argument("--repo", required=True, type=_repo)
    sub.add_argument("--issue", required=True, type=_number)
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


def post(args: argparse.Namespace) -> int:
    body = lm.approval_body(args.issue, args.pr, args.head, args.answer, args.message)
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
    look = lm.read_look(_issue_body(args))
    emit({"command": COMMAND, "action": "marked", "repo": args.repo, "issue": args.issue,
          "verdict": "marked" if look.marked else "unmarked", "covers": list(look.covers)})
    return 0


def status(args: argparse.Namespace) -> int:
    body = _issue_body(args)
    comments = forge_markers.list_comments(args.repo, args.issue)
    look = lm.read_look(body)
    marker = lm.look_answer(comments, args.issue, args.pr, args.head)
    answer = marker.fields.get("answer") if marker else None
    verdict = "unmarked" if not look.marked else "approved" if answer == "approved" else "needed"
    emit({"command": COMMAND, "action": "status", "repo": args.repo, "issue": args.issue, "pr": args.pr,
          "head": args.head, "verdict": verdict, "covers": list(look.covers), "answer": answer,
          "comment_id": marker.comment_id if marker else None})
    return 0


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def read_payload(text: str) -> tuple[int, str | None, list[lm.IssueFacts]]:
    try:
        data = json.loads(text)
    except ValueError:
        raise UsageError("stdin is not JSON") from None
    if not isinstance(data, dict) or not {"pr", "head", "issues"} <= set(data):
        raise UsageError("stdin needs the keys pr, head and issues")
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
    return pr, head, facts


def judge(stdin: str) -> int:
    base = {"command": COMMAND, "action": "judge"}
    try:
        pr, head, facts = read_payload(stdin)
    except UsageError as error:
        emit({**base, "verdict": "error", "error": "usage", "detail": str(error)})
        return USAGE
    try:
        verdict = lm.judge(pr, head, facts)
    except forge_api.ForgeError as error:
        emit({**base, "verdict": "error", "error": error.code, "detail": error.detail})
        return USAGE
    if verdict.admit:
        emit({**base, "verdict": "admit", "marked": list(verdict.marked)})
        return 0
    emit({**base, "verdict": "refuse", "issue": verdict.issue, "covers": list(verdict.covers)})
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = build_parser().parse_args(argv)
        if args.action == "judge":
            return judge(sys.stdin.read())
        if args.action == "post":
            lm.approval_fields(args.issue, args.pr, args.head, args.answer, args.message)
        elif args.action == "status" and not (isinstance(args.head, str) and lm.HEAD_PATTERN.fullmatch(args.head)):
            raise UsageError(f"head {args.head!r} is not 40 lowercase hex")
    except (UsageError, ValueError) as error:
        return usage_out(argv[0] if argv and argv[0] in VERBS else None, str(error))
    try:
        return {"post": post, "status": status, "marked": marked}[args.action](args)
    except forge_api.ForgeError as error:
        return forge_out(args, error)


if __name__ == "__main__":
    sys.exit(main())
