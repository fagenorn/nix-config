"""Owner-action markers a batch posts for the owner (issue 636): `forge-claim owner-action`.

1. A marker's first line is `<!-- agent:owner-action v1 issue=<n> reason=<reason> holder=<holder> -->`,
   line 2 is the sentence of its reason and every item follows as one line `- <item>` with its
   whitespace collapsed (D1). `reason` is `decision`, `conflict` or `needs-label`.
2. The marker carries no `claim` field (D6): claim retirement (`forge_claim.retire_obsolete`,
   `retire_owner_actions`) ends only owner-action markers that name a claim, so `forge-claim
   status`, `renew` and `release` never end one of these.
3. `post` never posts while a live marker of the same issue and reason exists (`already_posted`
   with the smallest live id) and always ensures and adds the `owner-action` label afterwards.
4. `end` ends every live marker of the reason (end reason `resolved`) and removes the label only
   when no live owner-action of any reason remains; nothing live is `none`, with no mutation.
5. `status` only reads. A reply is a comment after the marker that is not a marker and whose
   `author_association` is in `TRUSTED`; the verdict is `none`, `open` or `answered`.
6. `--items-file` holds a JSON array of 1 to `MAX_ITEMS` strings, each non-empty once its
   whitespace is collapsed; anything else is a usage error before any `gh` call.
7. Every call prints one JSON object on one line; exit 0 success, 1 forge error, 2 usage.
"""
import json
from pathlib import Path
from typing import Any

from agent_tools import forge_markers as fm

KIND = "owner-action"
LABEL = ("owner-action", "D93F0B")
REASONS = ("decision", "conflict", "needs-label")
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
MAX_ITEMS = 20
ACTIONS = ("post", "end", "status")
RESOLVED = "resolved"
USAGE = 2
SENTENCES = {
    "decision": "Delivery waits for the owner's answers below; reply on this issue or relaunch "
                "the batch with decisions.",
    "conflict": "Landing stopped on a second merge conflict with the integration branch; "
                "resolve it or say how.",
    "needs-label": "A required check needs a label that only the owner applies.",
}


class _ItemsError(Exception):
    """The items file broke the items invariant; carries the usage detail."""


def add_actions(sub: Any) -> None:
    from agent_tools.forge_claim import HOLDER, REPO, _issue  # forge_claim imports this module
    actions = sub.add_subparsers(dest="action", required=True)
    for name in ACTIONS:
        parser = actions.add_parser(name)
        parser.add_argument("--repo", required=True, type=REPO)
        parser.add_argument("--issue", required=True, type=_issue)
        if name == "post":
            parser.add_argument("--holder", required=True, type=HOLDER)
        parser.add_argument("--reason", required=True, choices=REASONS)
        if name == "post":
            parser.add_argument("--items-file", required=True)


def result(args: Any, verdict: str, comment_id: int | None = None, **extra: Any) -> dict[str, Any]:
    return {"command": "owner-action", "action": args.action, "repo": args.repo, "issue": args.issue,
            "reason": args.reason, "verdict": verdict, "comment_id": comment_id, **extra}


def usage_result(argv: list[str], detail: str) -> dict[str, Any]:
    action = argv[1] if len(argv) > 1 and argv[1] in ACTIONS else None
    return {"command": "owner-action", "action": action, "repo": None, "issue": None, "reason": None,
            "verdict": "error", "comment_id": None, "error": "usage", "detail": detail}


def _read_items(path: str) -> list[str]:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError) as error:
        raise _ItemsError(f"items file {path!r} is unreadable: {error}") from None
    except ValueError:
        raise _ItemsError(f"items file {path!r} is not JSON") from None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _ItemsError("items must be a JSON array of strings")
    if not 1 <= len(value) <= MAX_ITEMS:
        raise _ItemsError(f"items must hold 1 to {MAX_ITEMS} entries, not {len(value)}")
    items = [" ".join(item.split()) for item in value]
    if not all(items):
        raise _ItemsError("an item is empty")
    return items


def _match(args: Any) -> dict[str, str]:
    return {"issue": str(args.issue), "reason": args.reason}


def _post(args: Any) -> tuple[int, dict[str, Any]]:
    try:
        items = _read_items(args.items_file)
    except _ItemsError as error:
        return USAGE, result(args, "error", holder=args.holder, error="usage", detail=str(error))
    live = fm.contest(fm.list_markers(args.repo, args.issue), KIND, _match(args))
    if live:
        verdict, comment_id = "already_posted", live[0].comment_id
    else:
        written = fm.write(args.repo, args.issue, KIND, {**_match(args), "holder": args.holder},
                           SENTENCES[args.reason], _match(args),
                           "\n".join(f"- {item}" for item in items))
        if written.won:
            verdict, comment_id = "posted", written.own_id
        else:
            verdict = "already_posted"
            comment_id = written.winner.comment_id if written.winner else None
    fm.ensure_label(args.repo, *LABEL)
    fm.add_label(args.repo, args.issue, LABEL[0])
    return 0, result(args, verdict, comment_id, holder=args.holder)


def _end(args: Any) -> tuple[int, dict[str, Any]]:
    markers = fm.list_markers(args.repo, args.issue)
    named = [m.comment_id for m in fm.contest(markers, KIND, _match(args))]
    for comment_id in named:
        fm.end(args.repo, args.issue, comment_id, RESOLVED)
    if not named:
        return 0, result(args, "none", ended=[])
    if not any(m.kind == KIND and m.comment_id not in named and fm.is_live(m, markers)
               for m in markers):
        fm.remove_label(args.repo, args.issue, LABEL[0])
    return 0, result(args, "ended", named[0], ended=named)


def _status(args: Any) -> tuple[int, dict[str, Any]]:
    comments = fm.list_comments(args.repo, args.issue)
    markers = [m for m in map(fm.parse, comments) if m is not None]
    live = fm.contest(markers, KIND, _match(args))
    if not live:
        return 0, result(args, "none", items=[], replies=[])
    marker = live[0]
    items = [line[2:] for line in marker.body.splitlines()[2:] if line.startswith("- ")]
    replies = [{"comment_id": c["id"], "author": (c.get("user") or {}).get("login", ""),
                "body": c["body"]}
               for c in comments
               if isinstance(c.get("id"), int) and c["id"] > marker.comment_id
               and isinstance(c.get("body"), str) and fm.parse(c) is None
               and c.get("author_association") in TRUSTED]
    return 0, result(args, "answered" if replies else "open", marker.comment_id,
                     items=items, replies=replies)


def run(args: Any) -> tuple[int, dict[str, Any]]:
    return {"post": _post, "end": _end, "status": _status}[args.action](args)
