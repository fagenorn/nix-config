"""Race-safe machine state on GitHub issue comments (issue 623).

A marker is an issue comment whose first line is `<!-- agent:<kind> v1 key=value ... -->`
(D1: a repeated key or any other first line is not a marker); line 2 is one human sentence and
later lines are free. This module renders, parses, lists, posts, edits and deletes markers
through `gh api`, with `GITHUB_TOKEN` and `GH_TOKEN` removed from every child.

D2, winner and write: among the live markers of one kind whose fields contain a match set, the
smallest comment id wins. `write` posts, re-lists, takes the contest over the re-read plus its
own id and deletes its own comment when it is not the winner. Safety assumes a listing
reflects every comment created before the listing started. A caller that names trusted
associations makes markers by any other author invisible to its contest.

D9, ending is append-only: a marker is ended by posting an `end` marker naming its id, and
nothing edits or deletes an `end` marker. A marker is live when it is not itself an `end`
marker, carries no `released` field and no `end` marker in the same listing names it, so a
stale edit can drop a field but can never bring an ended marker back.

The module reads no host clock: "now" is the server's `Date` header (D5).
"""
import json
import os
import re
import subprocess
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

KIND = r"[a-z][a-z0-9-]*"
KEY = r"[a-z][a-z0-9_]*"
VALUE = r"[A-Za-z0-9._:/@+-]+"
MARKER = re.compile(rf"<!-- agent:(?P<kind>{KIND}) v1(?P<fields>(?: {KEY}={VALUE})*) -->")
FIELD = re.compile(rf" (?P<key>{KEY})=(?P<value>{VALUE})")
HTTP_STATUS = re.compile(r"\(HTTP (\d{3})\)")
END_KIND = "end"
TIMEOUT = 30
DETAIL_LIMIT = 240


class ForgeError(Exception):
    """A forge call failed: `code` is gh_missing, gh_failed, gh_timeout or payload_invalid."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail[:DETAIL_LIMIT]


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


def _gh(argv: list[str], allow: Iterable[int] = ()) -> tuple[int, str]:
    """Run `gh` without any token variable. Returns (0, stdout), or (status, stdout) when the
    call failed with an HTTP status in `allow`; every other failure is a ForgeError."""
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    try:
        done = subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        raise ForgeError("gh_timeout", " ".join(argv)) from None
    except OSError as error:
        raise ForgeError("gh_missing", str(error)) from None
    if done.returncode == 0:
        return 0, done.stdout
    found = HTTP_STATUS.search(done.stderr)
    status = int(found[1]) if found else 0
    if status and status in set(allow):
        return status, done.stdout
    raise ForgeError("gh_failed", done.stderr.strip())


def logged_in() -> bool:
    """Whether `gh` holds a credential: `gh auth status` succeeds. Any forge failure, a missing `gh` included, is False."""
    try:
        _gh(["auth", "status"])
    except ForgeError:
        return False
    return True


def _json(argv: list[str], allow: Iterable[int] = ()) -> Any:
    """The parsed stdout of a `gh` call, or None when it failed with a status in `allow`."""
    status, out = _gh(argv, allow)
    if status:
        return None
    try:
        return json.loads(out)
    except ValueError:
        raise ForgeError("payload_invalid", "stdout is not JSON") from None


def api_get(path: str, allow: Iterable[int] = ()) -> Any:
    """The parsed JSON of one `gh api` read, or None when it failed with a status in `allow`."""
    return _json(["api", path], allow)


def _comments(slug: str, issue: int) -> str:
    return f"repos/{slug}/issues/{issue}/comments"


def list_markers(slug: str, issue: int,
                 associations: Collection[str] | None = None) -> list[Marker]:
    """Every parseable marker on the issue, ascending comment id.

    With `associations`, a comment whose `author_association` is not in it is dropped before
    parsing, `end` markers included; `None` reads every comment."""
    pages = _json(["api", "--paginate", "--slurp", _comments(slug, issue) + "?per_page=100"])
    if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
        raise ForgeError("payload_invalid", "comment listing is not an array of pages")
    found = [parse(c) for page in pages for c in page if isinstance(c, dict)
             and (associations is None or c.get("author_association") in associations)]
    return sorted((m for m in found if m is not None), key=lambda m: m.comment_id)


def _posted(slug: str, issue: int, body: str) -> dict:
    comment = _json(["api", "-X", "POST", _comments(slug, issue), "-f", f"body={body}"])
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
    _gh(["api", "-X", "PATCH", f"repos/{slug}/issues/comments/{comment_id}", "-f", f"body={body}"])


def delete(slug: str, comment_id: int) -> None:
    """Delete a comment; HTTP 404 means it is already gone."""
    _gh(["api", "-X", "DELETE", f"repos/{slug}/issues/comments/{comment_id}"], allow=(404,))


def server_now() -> datetime:
    """The forge's current time: the `Date` header of a free `rate_limit` call (D5)."""
    _, out = _gh(["api", "--include", "rate_limit"])
    headers = re.split(r"\r?\n\r?\n", out, maxsplit=1)[0].splitlines()
    for line in headers[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "date":
            try:
                parsed = parsedate_to_datetime(value.strip())
            except (TypeError, ValueError):
                break
            return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None
                    else parsed.astimezone(timezone.utc))
    raise ForgeError("payload_invalid", "no readable Date header")


def ensure_label(slug: str, name: str, color: str) -> None:
    """Create the label; HTTP 422 means it already exists (D7)."""
    _gh(["api", "-X", "POST", f"repos/{slug}/labels", "-f", f"name={name}", "-f", f"color={color}"],
        allow=(422,))


def add_label(slug: str, issue: int, name: str) -> None:
    _gh(["api", "-X", "POST", f"repos/{slug}/issues/{issue}/labels", "-f", f"labels[]={name}"])


def remove_label(slug: str, issue: int, name: str) -> None:
    """Remove the label; HTTP 404 means it is not there (D7)."""
    _gh(["api", "-X", "DELETE", f"repos/{slug}/issues/{issue}/labels/{quote(name, safe='')}"],
        allow=(404,))


def latest_push(slug: str, branch: str) -> datetime | None:
    """The time of the branch's last push, None when it has none or no longer exists (D4)."""
    activity = _json(["api", f"repos/{slug}/activity?ref=refs/heads/{quote(branch, safe='/')}"
                      "&activity_type=push&per_page=1"], allow=(404,))
    if activity is None or activity == []:
        return None
    if not isinstance(activity, list) or not isinstance(activity[0], dict):
        raise ForgeError("payload_invalid", "activity is not an array of objects")
    return _instant(activity[0].get("timestamp"))


def latest_pr_event(slug: str, branch: str) -> datetime | None:
    """The newest `updated_at` among pull requests whose head is the branch (D4)."""
    owner = slug.split("/", 1)[0]
    pulls = _json(["api", f"repos/{slug}/pulls?state=all&head={owner}:{quote(branch, safe='/')}"
                   "&per_page=100"])
    if not isinstance(pulls, list) or not all(isinstance(p, dict) for p in pulls):
        raise ForgeError("payload_invalid", "pull requests are not an array of objects")
    return max((_instant(p.get("updated_at")) for p in pulls), default=None)


def graphql(query: str, variables: Mapping[str, str]) -> Any:
    """The parsed JSON of one `gh api graphql` call with string variables."""
    return _json(["api", "graphql", "-f", f"query={query}",
                  *(arg for key, value in variables.items() for arg in ("-f", f"{key}={value}"))])


def create_issue(slug: str, title: str, body: str, labels: Sequence[str] = ()) -> int:
    """Create an issue; its number."""
    created = _json(["api", "-X", "POST", f"repos/{slug}/issues", "-f", f"title={title}",
                     "-f", f"body={body}", *(arg for name in labels for arg in ("-f", f"labels[]={name}"))])
    number = created.get("number") if isinstance(created, dict) else None
    if isinstance(number, bool) or not isinstance(number, int):
        raise ForgeError("payload_invalid", "created issue has no number")
    return number


def list_issues(slug: str, label: str, since: datetime) -> list[dict]:
    """The issues (any state) carrying `label` and updated since `since`, one page of 100."""
    issues = _json(["api", f"repos/{slug}/issues?labels={quote(label)}&state=all"
                    f"&since={since:%Y-%m-%dT%H:%M:%SZ}&per_page=100"])
    if not isinstance(issues, list) or not all(isinstance(i, dict) for i in issues):
        raise ForgeError("payload_invalid", "issues are not an array of objects")
    return issues


def close_issue(slug: str, issue: int, reason: str) -> None:
    """Close the issue with a state reason (`completed` or `not_planned`); closing a closed issue is a no-op."""
    _gh(["api", "-X", "PATCH", f"repos/{slug}/issues/{issue}", "-f", "state=closed",
         "-f", f"state_reason={reason}"])
