"""The console's inbox reader (#859): what is waiting on the owner, read from the tracker, and how
recently a project was touched locally. Pure of the console's log and clock; `read_items` takes the
`gh` call and a cancellation test as arguments.

Markers decide, labels filter. One GraphQL search per repository asks for open issues and pull
requests carrying the `owner-action` or `owner-answered` label (`search_argv`, `QUERY`), at most
`PAGE_SIZE` nodes a page and the last `COMMENTS` comments of each. An item exists only for a live
(`forge_markers.is_live`) comment of kind `forge_owner_action.KIND` whose `reason` is one of
`forge_owner_action.REASONS`; a label alone raises nothing. Only comments whose `authorAssociation`
is in `forge_owner_action.TRUSTED` are parsed, `end` markers included. The reader never parses
marker text itself: the question is `marker_sentence`, the questions are `verified_questions`,
`answered` is `answered`, the items are `marker_items`.

A comment's id is `fullDatabaseId` (GitHub's `BigInt`, a decimal string) converted with `int`: the
32-bit `databaseId` is not read, because comment ids already exceed 2^31-1. A node's type is its
`__typename`: an `Issue` must carry `issueDependenciesSummary.blocking` (a non-negative integer) and
holds `1 + blocking` work, a `PullRequest` holds 1, any other node is refused.

`read_items` makes at most `MAX_CALLS` calls and asks `cancelled()` before each one (`ForgeError`
`cancelled`, no call made). A search still paging after the last call, a comment connection with
more comments than nodes, or fewer nodes than `issueCount` is `payload_incomplete`; an answer of an
unexpected shape, a bad comment id or a missing or repeated cursor is `payload_invalid`. The result
is sorted by `key` and holds only JSON-native values; every item is

    {"key": "<slug>#<issue>/<comment id>", "project_id", "repo", "issue", "comment_id", "url",
     "reason", "question", "questions": [{"question", "options", "chosen", "recommended"}] (decision only),
     "items": [str] (conflict and needs-label only), "answered", "held_work"}

`url` is built from the slug, the issue and the comment id, never read from the answer.

Activity: `local_activity(root)` is the newest modification time among `FETCH_HEAD`, `logs/HEAD`
and `index` of the checkout's common git dir and of each linked worktree's git dir (a linked
worktree's `FETCH_HEAD` is its own), or None when nothing is found or `root` is no checkout; it
starts no process. `is_active` holds when the newest of the last tracker event and the local
activity is at most `ACTIVE_WITHIN` seconds old; an unreadable or offset-less timestamp is ignored.
"""

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_tools.claims import forge_markers as fm
from agent_tools.claims import forge_owner_action as foa
from agent_tools.claims import owner_actions
from agent_tools.system import forge_api

MAX_CALLS = 4
PAGE_SIZE = 25
COMMENTS = 100
ACTIVE_WITHIN = 86400.0

QUERY = """query($search: String!, $after: String) {
  search(query: $search, type: ISSUE, first: 25, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      __typename
      ... on Issue {
        number
        issueDependenciesSummary { blocking }
        comments(last: 100) { totalCount nodes { fullDatabaseId body authorAssociation updatedAt } }
      }
      ... on PullRequest {
        number
        comments(last: 100) { totalCount nodes { fullDatabaseId body authorAssociation updatedAt } }
      }
    }
  }
}"""
ACTIVITY_FILES = (("FETCH_HEAD",), ("logs", "HEAD"), ("index",))


def search_argv(slug: str, after: str | None = None) -> list[str]:
    return ["api", "graphql", "-f", f"query={QUERY}",
            "-f", f"search=repo:{slug} is:open label:{foa.LABEL[0]},{foa.ANSWERED_LABEL[0]}",
            *(["-f", f"after={after}"] if after else [])]


def item_key(slug: str, issue: int, comment_id: int) -> str:
    return f"{slug}#{issue}/{comment_id}"


def _invalid(detail: str) -> forge_api.ForgeError:
    return forge_api.ForgeError("payload_invalid", detail)


def _count(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid(f"{what} is not a non-negative integer")
    return value


def _comment_id(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    raise _invalid(f"comment id {value!r}")


def _held_work(node: dict) -> int:
    kind = node.get("__typename")
    if kind == "PullRequest":
        return 1
    if kind == "Issue":
        summary = node.get("issueDependenciesSummary")
        if not isinstance(summary, dict):
            raise _invalid("issue has no dependency summary")
        return 1 + _count(summary.get("blocking"), "issueDependenciesSummary.blocking")
    raise _invalid(f"search node type {kind!r}")


def _comments(node: dict) -> list[dict]:
    connection = node.get("comments")
    if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
        raise _invalid("search node comments is not a connection")
    nodes = connection["nodes"]
    if _count(connection.get("totalCount"), "comments.totalCount") > len(nodes):
        raise forge_api.ForgeError("payload_incomplete", f"issue {node.get('number')} has more comments than read")
    if not all(isinstance(c, dict) for c in nodes):
        raise _invalid("a comment is not an object")
    return nodes


def _item(project_id: str, slug: str, issue: int, held: int, marker: fm.Marker) -> dict:
    reason = marker.fields["reason"]
    decision = reason == "decision"
    return {
        "key": item_key(slug, issue, marker.comment_id), "project_id": project_id, "repo": slug,
        "issue": issue, "comment_id": marker.comment_id,
        "url": f"https://github.com/{slug}/issues/{issue}#issuecomment-{marker.comment_id}",
        "reason": reason, "question": foa.marker_sentence(marker),
        "questions": ([{"question": q["question"], "options": list(q["options"]), "chosen": q["chosen"],
                        "recommended": rec}
                       for q, rec in zip(foa.verified_questions(marker), foa.recommended(marker))]
                      if decision else []),
        "items": [] if decision else foa.marker_items(marker),
        "answered": foa.answered(marker), "held_work": held,
    }


def items_from_node(project_id: str, slug: str, node: dict) -> list[dict]:
    """The inbox items of one search node: one per live owner-action marker of a trusted comment."""
    if not isinstance(node, dict):
        raise _invalid("search node is not an object")
    held = _held_work(node)
    number = node.get("number")
    if isinstance(number, bool) or not isinstance(number, int):
        raise _invalid("search node number is not an integer")
    markers = []
    for comment in _comments(node):
        if comment.get("authorAssociation") not in foa.TRUSTED:
            continue
        marker = fm.parse({"id": _comment_id(comment.get("fullDatabaseId")), "body": comment.get("body"),
                           "updated_at": comment.get("updatedAt")})
        if marker is not None:
            markers.append(marker)
    markers.sort(key=lambda m: m.comment_id)
    return [_item(project_id, slug, number, held, m) for m in markers
            if m.kind == foa.KIND and m.fields.get("reason") in foa.REASONS and fm.is_live(m, markers)]


def _page(answer: Any) -> tuple[list, bool, str | None, int]:
    data = answer.get("data") if isinstance(answer, dict) else None
    search = data.get("search") if isinstance(data, dict) else None
    if (not isinstance(search, dict) or not isinstance(search.get("nodes"), list)
            or not isinstance(search.get("pageInfo"), dict)):
        raise _invalid("search page has an unexpected shape")
    info = search["pageInfo"]
    if not isinstance(info.get("hasNextPage"), bool):
        raise _invalid("search pageInfo.hasNextPage is not a boolean")
    return (search["nodes"], info["hasNextPage"], info.get("endCursor"),
            _count(search.get("issueCount"), "search issueCount"))


def read_items(project_id: str, slug: str, *,
               call: Callable[[list[str]], Any] = forge_api.gh_json,
               cancelled: Callable[[], bool] = lambda: False) -> list[dict]:
    """Every inbox item of one repository, sorted by `key`; raises `forge_api.ForgeError`."""
    nodes: list = []
    cursors: set[str] = set()
    after: str | None = None
    total = 0
    for _ in range(MAX_CALLS):
        if cancelled():
            raise forge_api.ForgeError("cancelled")
        page, more, cursor, total = _page(call(search_argv(slug, after)))
        nodes += page
        if not more:
            break
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise _invalid("search endCursor is missing or repeated")
        cursors.add(cursor)
        after = cursor
    else:
        raise forge_api.ForgeError("payload_incomplete", f"more than {MAX_CALLS} pages")
    if len(nodes) < total:
        raise forge_api.ForgeError("payload_incomplete", f"{len(nodes)} of {total} search results")
    return sorted((i for node in nodes for i in items_from_node(project_id, slug, node)),
                  key=lambda item: item["key"])


def local_activity(root: str) -> float | None:
    """The newest git write of the checkout at `root` and its linked worktrees, or None."""
    common = owner_actions.git_common_dir(root)
    if common is None:
        return None
    try:
        linked = [w for w in (common / "worktrees").iterdir() if w.is_dir()]
    except OSError:
        linked = []
    newest: float | None = None
    for directory in (common, *linked):
        for parts in ACTIVITY_FILES:
            try:
                modified = os.stat(directory.joinpath(*parts)).st_mtime
            except OSError:
                continue
            newest = modified if newest is None else max(newest, modified)
    return newest


def is_active(last_event_at: str | None, local: float | None, now: float) -> bool:
    """Whether the newest of the last tracker event and the local activity is within `ACTIVE_WITHIN`."""
    times = [] if local is None else [local]
    if isinstance(last_event_at, str):
        try:
            parsed = datetime.fromisoformat(last_event_at)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.utcoffset() is not None:
            times.append(parsed.timestamp())
    return bool(times) and now - max(times) <= ACTIVE_WITHIN
