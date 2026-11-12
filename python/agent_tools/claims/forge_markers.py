"""Race-safe machine state on GitHub issue comments (issue 623).

A marker is an issue comment whose first line is `<!-- agent:<kind> v1 key=value ... -->`
(D1: a repeated key or any other first line is not a marker); the kind matches
`[a-z][a-z0-9-]*`, a key `[a-z][a-z0-9_]*` and a value `[A-Za-z0-9._:/@+-]+`. Line 2 is one human
sentence and later lines are free text. This module renders, parses, lists, posts, edits and
deletes markers through the `forge_api` transport. Labels (`in-progress`, `owner-action`) are
filters only; the markers decide.

D2, winner and write: among the live markers of one kind whose fields contain a match set, the
smallest comment id wins. `write` posts, re-lists, takes the contest over the re-read plus its
own id and deletes its own comment when it is not the winner. Safety assumes a listing
reflects every comment created before the listing started. A caller that names trusted
associations makes markers by any other author invisible to its contest.

D9, ending is append-only: a marker is ended by posting an `end` marker (`of=<id>`,
`reason=<reason>`) naming its id, and nothing edits or deletes an `end` marker. A marker is live
when it is not itself an `end` marker, carries no `released` field and no `end` marker in the
same listing names it, so a delayed edit that rewrites an older body can drop a field but can
never bring an ended marker back.

Ref primitives (issue 629): `read_ref`, `create_ref`, `repo_node_id`, `default_branch` and `cas_ref`, a
compare-and-swap through the GraphQL `updateRefs` mutation with `force: true` (the oid pair is
the guard; an `after` of `ZERO_OID` deletes). Any CAS error, timeout or lie is "not done": the
caller re-reads the ref to learn what happened and keeps the returned `ForgeError` (its code and
transport class) to report when the ref is unchanged (D1). REST ref deletion is never used.

Transport: the `gh api` calls, `ForgeError` and its transport class (issue 740), and the
server-time read (D5) are in `agent_tools.system.forge_api`; this module only calls them.
"""
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from agent_tools.system import forge_api
from agent_tools.system.forge_api import ForgeError

KIND = r"[a-z][a-z0-9-]*"
KEY = r"[a-z][a-z0-9_]*"
VALUE = r"[A-Za-z0-9._:/@+-]+"
MARKER = re.compile(rf"<!-- agent:(?P<kind>{KIND}) v1(?P<fields>(?: {KEY}={VALUE})*) -->")
FIELD = re.compile(rf" (?P<key>{KEY})=(?P<value>{VALUE})")
END_KIND = "end"
ZERO_OID = "0" * 40
OID = re.compile(r"[0-9a-f]{40}")
NODE_ID = re.compile(r"[A-Za-z0-9_=-]+")
UPDATE_REFS = ("mutation($repositoryId: ID!, $name: GitRefname!, $before: GitObjectID!, "
               "$after: GitObjectID!) { updateRefs(input: {repositoryId: $repositoryId, "
               "refUpdates: [{name: $name, beforeOid: $before, afterOid: $after, force: true}]}) "
               "{ clientMutationId } }")
CLOSING_ISSUES = ("query($owner: String!, $name: String!, $number: Int!) { "
                  "repository(owner: $owner, name: $name) { pullRequest(number: $number) { "
                  "closingIssuesReferences(first: 5) { nodes { number } } } } }")


@dataclass(frozen=True)
class Marker:
    comment_id: int
    kind: str
    fields: dict[str, str]
    body: str
    updated_at: datetime


@dataclass(frozen=True)
class WriteResult:
    won: bool
    own_id: int
    winner: Marker | None


@dataclass(frozen=True)
class Pull:
    number: int
    state: str
    merged: bool
    base_ref: str
    head_ref: str
    head_sha: str
    same_repo: bool = False  # the head branch lives in the base repository, not in a fork


def render(kind: str, fields: Mapping[str, str], sentence: str, extra: str = "") -> str:
    """The comment body of a marker; ValueError for anything outside the D1 grammar."""
    if not re.fullmatch(KIND, kind):
        raise ValueError(f"marker kind {kind!r} is outside the grammar")
    for key, value in fields.items():
        if not re.fullmatch(KEY, key):
            raise ValueError(f"marker key {key!r} is outside the grammar")
        if not isinstance(value, str) or not re.fullmatch(VALUE, value):
            raise ValueError(f"marker value {value!r} for {key} is outside the grammar")
    if not sentence or "\n" in sentence or "\r" in sentence:
        raise ValueError("a marker sentence is one non-empty line")
    first = f"<!-- agent:{kind} v1" + "".join(f" {k}={v}" for k, v in fields.items()) + " -->"
    return f"{first}\n{sentence}" + (f"\n{extra}" if extra else "")


def end_body(of: int, reason: str) -> str:
    return render(END_KIND, {"of": str(of), "reason": reason}, f"Ends marker comment {of} ({reason}).")


def _instant(value: Any) -> datetime:
    """An ISO 8601 timestamp (a trailing `Z` accepted) as an aware UTC datetime."""
    try:
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(text)
    except (AttributeError, TypeError, ValueError):
        raise ForgeError("payload_invalid", f"unreadable timestamp {value!r}") from None
    return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None
            else parsed.astimezone(timezone.utc))


def parse(comment: Mapping[str, Any]) -> Marker | None:
    """The marker a REST comment object carries, or None for any other comment."""
    body = comment.get("body")
    if not isinstance(body, str):
        return None
    first = body.split("\n", 1)[0].removesuffix("\r")
    match = MARKER.fullmatch(first)
    if match is None:
        return None
    pairs = [(m["key"], m["value"]) for m in FIELD.finditer(match["fields"])]
    fields = dict(pairs)
    if len(fields) != len(pairs):
        return None
    comment_id = comment.get("id")
    if isinstance(comment_id, bool) or not isinstance(comment_id, int):
        raise ForgeError("payload_invalid", f"comment id {comment_id!r}")
    return Marker(comment_id, match["kind"], fields, body, _instant(comment.get("updated_at")))


def with_fields(marker: Marker, **updates: str) -> str:
    """The marker's body with its first line re-rendered: existing keys keep their position
    and take the new value, new keys append in argument order; every other line is unchanged."""
    fields = {**marker.fields, **updates}
    rest = marker.body.split("\n", 1)[1] if "\n" in marker.body else ""
    first = render(marker.kind, fields, "x").split("\n", 1)[0]
    return first + ("\n" + rest if "\n" in marker.body else "")


def ended(markers: Iterable[Marker]) -> set[int]:
    """The comment ids that some `end` marker names."""
    return {int(m.fields["of"]) for m in markers
            if m.kind == END_KIND and m.fields.get("of", "").isdigit()}


def is_live(marker: Marker, markers: Iterable[Marker]) -> bool:
    return (marker.kind != END_KIND and "released" not in marker.fields
            and marker.comment_id not in ended(markers))


def contest(markers: Iterable[Marker], kind: str, match: Mapping[str, str]) -> list[Marker]:
    """The live markers of `kind` whose fields contain every `match` pair, ascending id."""
    markers = list(markers)
    return sorted((m for m in markers if m.kind == kind and is_live(m, markers)
                   and all(m.fields.get(k) == v for k, v in match.items())),
                  key=lambda m: m.comment_id)


def _comments(slug: str, issue: int) -> str:
    return f"repos/{slug}/issues/{issue}/comments"


def list_comments(slug: str, issue: int) -> list[dict]:
    """Every REST comment object of the issue, ascending comment id."""
    pages = forge_api.gh_json(["api", "--paginate", "--slurp", _comments(slug, issue) + "?per_page=100"])
    if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
        raise ForgeError("payload_invalid", "comment listing is not an array of pages")
    found = [c for page in pages for c in page if isinstance(c, dict)]
    return sorted(found, key=lambda c: c.get("id") if isinstance(c.get("id"), int) else -1)


def list_markers(slug: str, issue: int,
                 associations: Collection[str] | None = None) -> list[Marker]:
    """Every parseable marker on the issue, ascending comment id.

    With `associations`, a comment whose `author_association` is not in it is dropped before
    parsing, `end` markers included; `None` reads every comment."""
    found = [parse(c) for c in list_comments(slug, issue)
             if associations is None or c.get("author_association") in associations]
    return sorted((m for m in found if m is not None), key=lambda m: m.comment_id)


def _posted(slug: str, issue: int, body: str) -> dict:
    comment = forge_api.gh_json(["api", "-X", "POST", _comments(slug, issue), "-f", f"body={body}"])
    comment_id = comment.get("id") if isinstance(comment, dict) else None
    if isinstance(comment_id, bool) or not isinstance(comment_id, int):
        raise ForgeError("payload_invalid", "posted comment has no id")
    return comment


def post(slug: str, issue: int, body: str) -> int:
    """Post a comment; the new comment's id."""
    return _posted(slug, issue, body)["id"]


def end(slug: str, issue: int, of: int, reason: str) -> int:
    """End marker `of` by appending an `end` marker (D9); the target is never touched."""
    return post(slug, issue, end_body(of, reason))


def write(slug: str, issue: int, kind: str, fields: Mapping[str, str], sentence: str,
          match: Mapping[str, str], extra: str = "",
          associations: Collection[str] | None = None) -> WriteResult:
    """Post a marker and settle contention for it (D2).

    `match` must be contained in `fields` (ValueError otherwise, before anything is posted).
    The post comes first and the listing after it. The winner is the smallest live comment id
    of `kind` matching `match` in the re-read plus this write's own comment. A loser deletes
    its own comment and reports the smallest other contested marker. One post, at most one
    delete, no retry. With `associations` the re-read is `list_markers(slug, issue,
    associations)`; the own comment counts whatever its association.
    """
    if any(fields.get(k) != v for k, v in match.items()):
        raise ValueError("match pairs must be contained in the marker's fields")
    body = render(kind, fields, sentence, extra)
    posted = _posted(slug, issue, body)
    own_id = posted["id"]
    reread = list_markers(slug, issue, associations)
    if not any(m.comment_id == own_id for m in reread):
        own = parse({"id": own_id, "body": body,
                     "updated_at": posted.get("updated_at") or "1970-01-01T00:00:00Z"})
        reread = sorted([*reread, own], key=lambda m: m.comment_id)
    contested = contest(reread, kind, match)
    if contested and contested[0].comment_id == own_id:
        return WriteResult(True, own_id, contested[0])
    delete(slug, own_id)
    others = [m for m in contested if m.comment_id != own_id]
    return WriteResult(False, own_id, others[0] if others else None)


def edit(slug: str, comment_id: int, body: str) -> None:
    forge_api.run_gh(["api", "-X", "PATCH", f"repos/{slug}/issues/comments/{comment_id}", "-f", f"body={body}"])


def delete(slug: str, comment_id: int) -> None:
    """Delete a comment; HTTP 404 means it is already gone."""
    forge_api.run_gh(["api", "-X", "DELETE", f"repos/{slug}/issues/comments/{comment_id}"], allow=(404,))


def latest_push(slug: str, branch: str) -> datetime | None:
    """The time of the branch's last push, None when it has none or no longer exists (D4)."""
    activity = forge_api.gh_json(["api", f"repos/{slug}/activity?ref=refs/heads/{quote(branch, safe='/')}"
                                  "&activity_type=push&per_page=1"], allow=(404,))
    if activity is None or activity == []:
        return None
    if not isinstance(activity, list) or not isinstance(activity[0], dict):
        raise ForgeError("payload_invalid", "activity is not an array of objects")
    return _instant(activity[0].get("timestamp"))


def latest_pr_event(slug: str, branch: str) -> datetime | None:
    """The newest `updated_at` among pull requests whose head is the branch (D4)."""
    owner = slug.split("/", 1)[0]
    pulls = forge_api.gh_json(["api", f"repos/{slug}/pulls?state=all&head={owner}:{quote(branch, safe='/')}"
                               "&per_page=100"])
    if not isinstance(pulls, list) or not all(isinstance(p, dict) for p in pulls):
        raise ForgeError("payload_invalid", "pull requests are not an array of objects")
    return max((_instant(p.get("updated_at")) for p in pulls), default=None)


def read_ref(slug: str, ref: str) -> str | None:
    """The sha a full ref name (`refs/...`) points at, None when HTTP 404 says it is absent."""
    payload = forge_api.gh_json(["api", f"repos/{slug}/git/ref/{quote(ref.removeprefix('refs/'), safe='/')}"],
                                allow=(404,))
    if payload is None:
        return None
    obj = payload.get("object") if isinstance(payload, dict) else None
    sha = obj.get("sha") if isinstance(obj, dict) else None
    if (not isinstance(payload, dict) or payload.get("ref") != ref
            or not isinstance(sha, str) or not OID.fullmatch(sha)):
        raise ForgeError("payload_invalid", f"ref payload for {ref}")
    return sha


def create_ref(slug: str, ref: str, sha: str) -> bool:
    """Create the ref at `sha`: True when created, False on HTTP 422 (re-read to learn why)."""
    status, _ = forge_api.run_gh(["api", "-X", "POST", f"repos/{slug}/git/refs", "-f", f"ref={ref}",
                                  "-f", f"sha={sha}"], allow=(422,))
    return status == 0


def repo_node_id(slug: str) -> str:
    _, out = forge_api.run_gh(["api", f"repos/{slug}", "--jq", ".node_id"])
    node_id = out.strip()
    if not NODE_ID.fullmatch(node_id):
        raise ForgeError("payload_invalid", "repository node id")
    return node_id


def default_branch(slug: str) -> str:
    _, out = forge_api.run_gh(["api", f"repos/{slug}", "--jq", ".default_branch"])
    branch = out.strip()
    if not branch or branch == "null":
        raise ForgeError("payload_invalid", "repository default branch")
    return branch


def cas_ref(slug: str, repository_id: str, ref: str, before: str, after: str) -> ForgeError | None:
    """Move `ref` from `before` to `after` (`ZERO_OID` deletes) through `updateRefs`.

    None means gh reported the swap applied. Any other outcome returns its failure as a
    `ForgeError` (code and transport class kept, `gh_timeout` or `gh_failed`) without raising:
    a failed swap, a timeout and a swap that applied while reporting failure look alike, so the
    caller re-reads the ref (D1) and keeps the error to report if the ref is unchanged.
    `gh_missing` and `payload_invalid` raise.
    """
    try:
        payload = forge_api.gh_json(["api", "graphql", "-f", f"query={UPDATE_REFS}", "-f", f"repositoryId={repository_id}",
                                     "-f", f"name={ref}", "-f", f"before={before}", "-f", f"after={after}"])
    except ForgeError as error:
        if error.code in ("gh_timeout", "gh_failed"):
            return error
        raise
    data = payload.get("data") if isinstance(payload, dict) else None
    if (not isinstance(payload, dict) or "errors" in payload
            or not isinstance(data, dict) or data.get("updateRefs") is None):
        return ForgeError("gh_failed", "updateRefs reported no update")
    return None


def _pull(item: Any) -> Pull:
    base = item.get("base") if isinstance(item, dict) else None
    head = item.get("head") if isinstance(item, dict) else None
    number = item.get("number") if isinstance(item, dict) else None
    refs = (base.get("ref") if isinstance(base, dict) else None,
            head.get("ref") if isinstance(head, dict) else None,
            head.get("sha") if isinstance(head, dict) else None)
    if (isinstance(number, bool) or not isinstance(number, int)
            or item.get("state") not in ("open", "closed")
            or not all(isinstance(r, str) for r in refs)):
        raise ForgeError("payload_invalid", "pull entry")
    names = [side.get("repo").get("full_name") if isinstance(side.get("repo"), dict) else None
             for side in (base, head)]
    return Pull(number, item["state"], item.get("merged_at") is not None, *refs,
                same_repo=isinstance(names[0], str) and names[0] == names[1])


def commit_pulls(slug: str, sha: str) -> list[Pull]:
    """The pull requests the forge associates with commit `sha`.

    GitHub documents that a commit outside the default branch gets only its open pull requests
    (verified live: a closed-unmerged head answers `[]`), so this never finds a squash-merged,
    rebase-merged or closed holder; `closed_pulls_headed` does.
    """
    payload = forge_api.gh_json(["api", f"repos/{slug}/commits/{sha}/pulls?per_page=100"])
    if not isinstance(payload, list):
        raise ForgeError("payload_invalid", "commit pulls are not an array")
    return [_pull(item) for item in payload]


CLOSED_PAGES = 5  # 500 most recently updated closed pull requests


def closed_pulls_headed(slug: str, branch: str, sha: str) -> list[Pull]:
    """The closed pull requests on base `branch` whose head is `sha`, newest update first.

    Scans at most `CLOSED_PAGES` pages of the closed listing, which is not limited to the
    default branch: a closed holder older than that window is not found.
    """
    found: list[Pull] = []
    for page in range(1, CLOSED_PAGES + 1):
        payload = forge_api.gh_json(["api", f"repos/{slug}/pulls?state=closed&base={quote(branch, safe='/')}"
                                     f"&sort=updated&direction=desc&per_page=100&page={page}"])
        if not isinstance(payload, list):
            raise ForgeError("payload_invalid", "closed pulls are not an array")
        found += [pull for pull in map(_pull, payload) if pull.head_sha == sha]
        if len(payload) < 100:
            break
    return found


def pulls_from(slug: str, branch: str, sha: str) -> list[Pull]:
    """The pull requests, open or closed, whose head is `branch` of this repository at `sha`,
    whatever their base.

    One page: the 100 most recently updated pull requests headed by `branch`. Open ones are
    included because the commit lookup can leave an open pull request out. The `head` filter
    names the owner, and `same_repo` drops a same-owner fork's branch of that name.
    """
    owner = slug.split("/", 1)[0]
    payload = forge_api.gh_json(["api", f"repos/{slug}/pulls?state=all&head={quote(owner, safe='')}:"
                                 f"{quote(branch, safe='/')}&sort=updated&direction=desc&per_page=100"])
    if not isinstance(payload, list):
        raise ForgeError("payload_invalid", "branch pulls are not an array")
    return [pull for pull in map(_pull, payload)
            if pull.head_sha == sha and pull.head_ref == branch and pull.same_repo]


def open_pulls_from(slug: str, branch: str) -> list[Pull]:
    """The open pull requests whose head is `branch` of this repository, whatever their base and
    head sha (issue 901): one call, since a branch heads one open pull request per base."""
    owner = slug.split("/", 1)[0]
    payload = forge_api.gh_json(["api", f"repos/{slug}/pulls?state=open&head={quote(owner, safe='')}:"
                                 f"{quote(branch, safe='/')}&per_page=100"])
    if not isinstance(payload, list):
        raise ForgeError("payload_invalid", "open branch pulls are not an array")
    return [pull for pull in map(_pull, payload)
            if pull.state == "open" and pull.head_ref == branch and pull.same_repo]


def closing_issues(slug: str, pr: int) -> list[int]:
    """The issue numbers the pull request closes, in the forge's order."""
    owner, name = slug.split("/", 1)
    payload = forge_api.gh_json(["api", "graphql", "-f", f"query={CLOSING_ISSUES}", "-f", f"owner={owner}",
                                 "-f", f"name={name}", "-F", f"number={pr}"])
    try:
        nodes = payload["data"]["repository"]["pullRequest"]["closingIssuesReferences"]["nodes"]
        numbers = [node["number"] for node in nodes]
    except (KeyError, TypeError):
        raise ForgeError("payload_invalid", "closing issues payload") from None
    if any(isinstance(n, bool) or not isinstance(n, int) for n in numbers):
        raise ForgeError("payload_invalid", "closing issue number")
    return numbers
