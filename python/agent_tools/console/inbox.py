"""The console's inbox reader (#859): what is waiting on the owner, read from the tracker, and how
recently a project was touched locally. Pure of the console's log and clock; `read_items` takes the
`gh` call and a cancellation test as arguments.

Markers decide, labels filter. One GraphQL search per repository asks for open issues and pull
requests carrying the `owner-action` or `owner-answered` label (`search_argv`, `QUERY`), at most `PAGE_SIZE`
nodes a page and the last `COMMENTS` comments of each; an Issue node also reads its `authorAssociation`,
`body` and `labels`. A second search, `held_argv`, asks the same for the `needs-verification` (`HELD_LABEL`)
label only; it is read after the first and is lenient (see `read_items`). An item exists only for a live
(`forge_markers.is_live`) comment of kind `forge_owner_action.KIND` whose `reason` is one of
`forge_owner_action.REASONS`; a label alone raises nothing. Only comments whose `authorAssociation`
is in `forge_owner_action.TRUSTED` are parsed, `end` markers included. The reader never parses
marker text itself: the question is `marker_sentence`, the questions are `verified_questions`,
`answered` is `answered`, the items are `marker_items`.

A verification owner prompt (#863) is the other kind of item. It is a live `owner-action` marker
that `verify_answer.is_runner_prompt` accepts (a `verify-*` reason carrying `block` and `check`), read
only from comments whose `authorAssociation` is in `verify_answer.TRUSTED` (OWNER and MEMBER, narrower
than the forge set): its liveness and `answered` are judged over the markers of those comments only
(`runner_markers`), so a collaborator's `end` never hides it and a collaborator's prompt is never one.
Its `kind` is `verify_answer.kind_of`, its `answers` are `verify_answer.ANSWERS[reason]`, `paid` is
`verify_answer.is_paid`, and `confirm` is `<slug>#<issue>` for every approval, live or paid, else
`""`. Its `detail` is the body after the sentence with the runner's own trailing answer boxes
(`verify_answer.labels`) and the empty lines around them dropped; a checkbox-shaped line inside the
ask text or the act fence stays. For a `verify-ask` prompt whose sentence names its check
(`verify_answer.ask_check_id`) and whose detail has a first line that opens no fence, `question` is
that line's first sentence (cut after the first `.`, `?` or `!`, with any closing quote or bracket,
that whitespace or the line end follows, else the whole line, whitespace collapsed), `check_id` is
the check id and `detail` is the rest; every other verification prompt keeps its sentence and whole
detail with `check_id` `""` (#1046).

Held reviews (#1113, ADR-console-054). A held issue with no live runner prompt raises review items
instead. An Issue node labelled `HELD_LABEL` whose `authorAssociation` is in `verify_answer.TRUSTED`
and that has no live trusted runner prompt (the verification-item predicate above) is read through
`acceptance_criteria` of its body: the checkbox lines of its first `Acceptance criteria` heading
section, outside fences (a fence closes only on a line of its own delimiter character, at least as
long as the one that opened it, with nothing after it but spaces; an unclosed fence runs to the end;
a fence opens and closes with up to three spaces of indent beyond the content column of the list item
enclosing it, so a fenced example nested under a checkbox is no criterion, a fence may open right after a
list marker (`- ~~~`) and then belongs to that item, and an open fence also ends at the first non-blank line
indented less than that column, as its list item does).
A heading inside a list item (indented to its content column) is part of that item and ends nothing; only a
heading outside every list item ends the section.
A criterion is `Criterion(index, ticked, kind, text, line)`, `kind` being a leading `[code]`,
`[evidence]`, `[human]` or `[note]` tag or None, and a checkbox line's bullet (`-`, `*` or `+`) may be
followed by any run of spaces or tabs. `review_criteria` is the unticked `human` criteria when no unticked
criterion has a kind outside `MET_KINDS` (`code`, `human`, `note`: an unticked `[code]` box of a held issue
counts as met, the hold step never ticks it; an unticked `evidence` or untagged criterion keeps the issue with
the runner), less the criteria the held verify block already asks: a criterion whose `ac_id` (`AC<index>`)
equals, case-insensitively, the `ac` of a check of the newest block of a trusted comment
(`verify_answer.held_acs`) is left to the runner, which asks it when due, so the owner is never asked twice.
Each remaining one raises one review item, keyed `<slug>#<issue>/ac<index>`,
with `reason` `held-review`, `kind` `owner-review`, `answers` `["passed", "note"]`, `comment_id` None,
`criterion` its index and `version` `criterion_version` (a digest of issue, index, kind and text, never the
tick), plus the `check_id` `""` and `reading` `""` of an owner check and a `detail` that is the criterion's whole text,
measured tail included, which the card shows in its "Show the check" fold. Its `question`, the card's
heading and the digest line, is the criterion's text cut before its first measured tail (a whitespace,
any dash, whitespace, `measured:`, case-insensitive: ` \u2014 measured:` and ` - measured:`), without any word that names a PNG file or a folder (a
`.png` name, or a word with a `/` that starts with `/`, `~/`, `./` or `../`, or ends with `/`, and has no `://`;
`attach_pictures` also drops a relative word with a `/` that is a folder under its roots; `and/or`, `light/dark`
and `1440/480` stay; `heading_text`), and without a connecting word (`in`, `under`, `and`...) left
dangling before one; `criterion_text` is the whole text, which is what `attach_pictures` reads the pictures
from, so the card shows the pictures and never a bare path. A text left with no word reads `REVIEW_HEADING`; the whole text, tail included, stays in `criterion_text`.

An approved look answers a look marker (#1186 and #1211, ADR-console-054 D8). A review criterion whose body line is a
look marker (`look_marker.marker_line`, issue 1138) raises no card when a pull request that a trusted (OWNER or MEMBER)
live `agent:look` approval of the issue names (`look_marker.look_prs`) reads merged with a head that the latest trusted
answer naming it approved, or that keeps an earlier approval (issue 1211), judged at the merge commit's first parent
(`look_marker.merged_under_look`). The check is one REST `repos/<slug>/pulls/<n>` read through `items_from_node`'s `call`
(`read_items` hands its own) per pull request a trusted approval names, ascending and stopping at the first match, then
at most one commit read and `look_marker.READ_LIMIT` carry reads, only for an issue that would otherwise raise a
look-marker card; it lies outside `MAX_CALLS`, `cancelled` is asked before each read, a `cancelled` `ForgeError`
propagates and any other failed or unreadable read keeps the card. An ordinary `[human]` criterion of the same issue
keeps its card.

A `verify-ask` prompt's `reading` (#1112) is the instruction for reading the check's result, written in
its ask as `Reading:` at the start of a detail line (after optional spaces) or right after whitespace
(case-sensitive). It is the rest of that line, stripped and whitespace-collapsed, and it leaves the
`detail`, which keeps every other character (text before `Reading:` on the line stays, a line left
blank is dropped, blank lines at either end are dropped). A line inside a fenced block (opened and
closed by a line starting with three backticks or `~~~`) is never read, an empty rest is no reading,
and only the first reading is taken: a later `Reading:` stays in the detail. Every other prompt has
`reading` `""` and its detail unchanged.

Pictures (#1112, ADR-console-045). `attach_pictures(item, roots, pictures_dir, home=None)` returns a
copy of a verification item with two more members, `pictures` (`[{"id", "line", "pair": None}]`, the
stored pictures the prompt names) and `missing_pictures` (the PNG names it gives that exist nowhere
under the roots). It reads the text `question`, `detail` and `reading` joined by a newline and never
changes the item; the same files give an equal result on every call. `named_pictures(text)` splits
the text on whitespace and strips each token of leading ``"`'([<{`` and trailing ``"`'.,;:!?)]}>``
until stable: a token holding `://` is ignored, one whose lowercase ends `.png` (and is longer than
four characters) is a PNG name, any other token holding `/` is a folder, each in first-seen order
without repeats. A path starting `/` is absolute, one starting `~/` is under `home`, any other is
under the first root (the project root). A root is a configured directory that exists; it is spelled
as written and as its realpath, and a candidate is inside it when its normalised path equals or
starts below either spelling. A relative PNG name is tried under each named folder in order, then
under the first root; the first candidate that opens is chosen. A candidate is never resolved by
its realpath: the root is opened, then each component is opened with `O_NOFOLLOW` relative to its
parent descriptor, so no symlink under a root is followed, even one swapped in after a check. A
candidate outside every root is dropped and records nothing; a name whose every candidate inside a
root does not exist (a plain file standing where a folder is named counts as not existing) goes to
`missing_pictures` as written; any other error skips the name. A named folder that opens as a
directory and into which no named PNG resolved directly (a PNG that a folder listing chose does not
count) contributes its direct entries ending `.png` (any case), sorted by name, each opened relative to the folder. A chosen file
is read only through the descriptor that opened it and is stored only when it is a regular file of
at most `pictures.MAX_BYTES` bytes that `pictures.checked_png` accepts; otherwise it is skipped, as
is a file whose store fails. At most `sprints.MAX_PICTURES` pictures and as many missing names are
kept, named PNGs first, then folder listings; each `line` is the file's base name cut to
`sprints.MAX_PICTURE_LINE_CHARS` characters; a path is listed once.

A waiting owner check (#1129). The runner posts an owner prompt only for a check that is due, so a held
issue whose owner checks are not due carries no prompt yet and would not reach the inbox by marker or
by the two owner labels: the held search (`held_argv`) finds it. An `Issue` node whose trusted (`OWNER` or `MEMBER`)
comments open a ```verify fence is read through `verify_wait.held_waits` (the block and its markers are
trusted exactly as the runner trusts them, never a collaborator's), which needs each comment's `createdAt`
and the node's `repository.defaultBranchRef.name`; a node holding a block without them is `payload_invalid`,
and a node with no block is read exactly as before (no clock, no `createdAt`, no `repository`). Every
item that answers a wait carries `"wait": {"reason": <verify_wait reason>, "until": <ISO 8601 UTC> or None,
"what": <text>}`. A prompted wait (only `no_when`) is set on the item of each live runner prompt whose
`block` and `check` marker fields are the held block's key and the wait's check index; an unprompted wait is
an item of its own,

    {"key": "<slug>#<issue>/wait/<block comment id>/<check index>", "reason": "verify-wait",
     "kind": "waiting", "question": <what>, "answers": [], "comment_id": <block comment id>, "wait", ...}

with the shape of the items above (no `check_id`, so it takes no pictures). `what` is the first sentence of
the check's text (cut after `.`, `?` or `!` as a prompt's heading is, whitespace collapsed) cut to
`sprints.MAX_ASK_CHARS`, or `<ac> waits for your approval to run` for a check with no text. A prompt with no
wait has no `wait` member. The clock is the forge's (`forge_api.server_now`, or the `now` argument),
asked at most once per read and only when a node holds an unprompted check to date; these forge reads
(`verify_wait`'s, not the search's) are outside `MAX_CALLS`. `cancelled()` is asked before each node's items
are built and handed to `held_waits`, which asks it before every forge read and the clock read, so a stop
lets only the read already running finish. The console posts nothing and reads no host revision.

A comment's id is `fullDatabaseId` (GitHub's `BigInt`, a decimal string) converted with `int`: the
32-bit `databaseId` is not read, because comment ids already exceed 2^31-1. A node's type is its
`__typename`: an `Issue` must carry `issueDependenciesSummary.blocking` (a non-negative integer) and
holds `1 + blocking` work, a `PullRequest` holds 1, any other node is refused.

An `Issue` must also carry its `blocking` connection (at most 100 nodes read; `totalCount` above the
nodes read is `payload_incomplete`, a malformed one `payload_invalid`), and `blocking` lists,
ascending and without repeats, the open issues of the same repository (the slug compared
case-insensitively) that the issue blocks; a pull request's is `[]`.

`read_items` makes at most `MAX_CALLS` calls for each of its two searches and asks `cancelled()` before
each one (`ForgeError` `cancelled`, no call made). In the owner search a search still paging after the last
call or fewer nodes than `issueCount` is `payload_incomplete`, and so is a comment connection with more
comments than nodes, except that a node whose comment connection holds more comments than the last `COMMENTS`
it returned (a long-held issue) has every comment read from the REST listing instead, as the runner reads it
(`verify_wait.with_every_comment`), outside `MAX_CALLS`, so it never fails the repository's read for its
length. The held search is lenient, because held issues stay open and labelled until the runner
verifies them, so their number and comments only grow: when it is still paging after its last call it keeps
the nodes it read, it does not compare them with `issueCount`, and an Issue node whose read is
`payload_incomplete` raises no item (the owner search, which carries every owner-action and owner-answered
label, still fails the read on such a node); a node the owner search already returned is read once, from
the owner search. In both, an answer of an
unexpected shape, a bad comment id or a missing or repeated cursor is `payload_invalid`. The result
is sorted by `key` and holds only JSON-native values; every item is

    {"key": "<slug>#<issue>/<comment id>", "project_id", "repo", "issue", "comment_id", "url",
     "reason", "kind", "question", "detail", "questions": [{"question", "options", "chosen", "recommended"}]
     (decision only), "items": [str] (conflict and needs-label only), "answers": [str], "paid": bool,
     "confirm", "answered", "held_work", "blocking": [int]} and, for a verification prompt or a review item, "version", "check_id"
     and "reading" (and, for a review item only, "criterion"; its "comment_id" is None)
(and, once `attach_pictures` has run, "pictures" and "missing_pictures")

For `decision`, `conflict` and `needs-label` the kind is the reason, `detail` and `confirm` are `""`,
`answers` is `[]`, `paid` is false and there is no `version`. A verification prompt's `version` is
`verify_answer.content_version` of its marker: the page returns it with an answer, and an answer to a
prompt whose text or fields have changed since is refused.

`url` is built from the slug, the issue and the comment id, never read from the answer.

Activity: `local_activity(root)` is the newest modification time among `FETCH_HEAD`, `logs/HEAD`
and `index` of the checkout's common git dir and of each linked worktree's git dir (a linked
worktree's `FETCH_HEAD` is its own), or None when nothing is found or `root` is no checkout; it
starts no process. `is_active` holds when the newest of the last tracker event and the local
activity is at most `ACTIVE_WITHIN` seconds old; an unreadable or offset-less timestamp is ignored.
"""

import os
import re
import stat
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_tools.claims import forge_markers as fm
from agent_tools.claims import forge_owner_action as foa
from agent_tools.claims import owner_actions
from agent_tools.canonical import telemetry_digest
from agent_tools.delivery import look_marker
from agent_tools.console import pictures
from agent_tools.console.sprints import MAX_ASK_CHARS, MAX_PICTURE_LINE_CHARS, MAX_PICTURES, cut
from agent_tools.system import forge_api
from agent_tools.verification import verify_answer, verify_wait

MAX_CALLS = 4
PAGE_SIZE = 25
COMMENTS = 100
ACTIVE_WITHIN = 86400.0
HELD_LABEL = "needs-verification"
REVIEW_REASON = "held-review"
REVIEW_KIND = "owner-review"
REVIEW_ANSWERS = ("passed", "note")

QUERY = """query($search: String!, $after: String) {
  search(query: $search, type: ISSUE, first: 25, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      __typename
      ... on Issue {
        number
        repository { defaultBranchRef { name } }
        authorAssociation
        body
        labels(first: 100) { nodes { name } }
        issueDependenciesSummary { blocking }
        blocking(first: 100) { totalCount nodes { number state repository { nameWithOwner } } }
        comments(last: 100) { totalCount nodes { fullDatabaseId body authorAssociation createdAt updatedAt } }
      }
      ... on PullRequest {
        number
        comments(last: 100) { totalCount nodes { fullDatabaseId body authorAssociation createdAt updatedAt } }
      }
    }
  }
}"""
ACTIVITY_FILES = (("FETCH_HEAD",), ("logs", "HEAD"), ("index",))


def _argv(slug: str, labels: str, after: str | None) -> list[str]:
    return ["api", "graphql", "-f", f"query={QUERY}", "-f", f"search=repo:{slug} is:open label:{labels}",
            *(["-f", f"after={after}"] if after else [])]


def search_argv(slug: str, after: str | None = None) -> list[str]:
    return _argv(slug, f"{foa.LABEL[0]},{foa.ANSWERED_LABEL[0]}", after)


def held_argv(slug: str, after: str | None = None) -> list[str]:
    return _argv(slug, HELD_LABEL, after)


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


def _blocking(node: dict, slug: str) -> list[int]:
    """The open issues of `slug` that this issue blocks, ascending."""
    if node.get("__typename") == "PullRequest":
        return []
    connection = node.get("blocking")
    if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
        raise _invalid("issue blocking is not a connection")
    nodes = connection["nodes"]
    if _count(connection.get("totalCount"), "blocking.totalCount") > len(nodes):
        raise forge_api.ForgeError("payload_incomplete",
                                   f"issue {node.get('number')} blocks more issues than read")
    for blocked in nodes:
        number = blocked.get("number") if isinstance(blocked, dict) else None
        repository = blocked.get("repository") if isinstance(blocked, dict) else None
        if (isinstance(number, bool) or not isinstance(number, int) or blocked.get("state") not in ("OPEN", "CLOSED")
                or not isinstance(repository, dict) or not isinstance(repository.get("nameWithOwner"), str)):
            raise _invalid("a blocked issue is malformed")
    return sorted({b["number"] for b in nodes if b["state"] == "OPEN"
                   and b["repository"]["nameWithOwner"].casefold() == slug.casefold()})


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


_FENCE_OPEN = re.compile(r"^([ \t]*)(`{3,}|~{3,})")
_LIST_ITEM = re.compile(r"^([ \t]*)(?:[-*+]|\d{1,9}[.)])([ \t]+)")
_FENCE_RUN = re.compile(r"(`{3,}|~{3,})")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_AC_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+Acceptance criteria\s*#*\s*$", re.IGNORECASE)
_CRITERION = re.compile(r"^\s*[-*+][ \t]+\[( |x|X)\][ \t]+(.*)$")
_KIND = re.compile(r"\[(code|evidence|human|note)\]\s*(.*)$")


def _list_prefixes(line: str) -> tuple[list[int], str]:
    """The content column of each list marker that opens `line` (`- - x` has two), and the text after them."""
    columns: list[int] = []
    position = 0
    while True:
        item = _LIST_ITEM.match(line[position:])
        if not item:
            return columns, line[position:]
        position += item.end()
        columns.append(len(line[:position].expandtabs(4)))


def _fence(run: str, column: int) -> tuple[re.Pattern, int, int]:
    """A fence opened by `run` inside a container whose content column is `column`: its closer, the widest indent
    that closer may have and the column below which a line ends the fence."""
    return (re.compile(r"^([ \t]*)" + re.escape(run[0]) + "{" + str(len(run)) + r",}[ \t]*$"), column + 3, column)


@dataclass(frozen=True)
class Criterion:
    index: int
    ticked: bool
    kind: str | None
    text: str
    line: int


def acceptance_criteria(body: str) -> list[Criterion]:
    """The checkbox lines of the first `Acceptance criteria` section of an issue body, outside fences."""
    criteria: list[Criterion] = []
    inside = False
    fence: tuple[re.Pattern, int, int] | None = None
    containers: list[int] = []
    for number, raw in enumerate(body.split("\n")):
        line = raw.removesuffix("\r")
        indent = len(re.match(r"[ \t]*", line).group().expandtabs(4))
        if fence is not None:
            closer, limit, column = fence
            closing = closer.match(line)
            if line.strip() and indent < column:
                fence = None
            else:
                if closing and len(closing.group(1).expandtabs(4)) <= limit:
                    fence = None
                continue
        if line.strip():
            while containers and indent < containers[-1]:
                containers.pop()
        base = containers[-1] if containers else 0
        opened = _FENCE_OPEN.match(line)
        if opened and indent - base <= 3:
            run = opened.group(2)
            fence = _fence(run, base)
            continue
        columns, rest = _list_prefixes(line)
        containers.extend(columns)
        sheltered = _FENCE_RUN.match(rest) if columns else None
        if sheltered:
            fence = _fence(sheltered.group(1), columns[-1])
            continue
        if not inside:
            inside = bool(_AC_HEADING.match(line))
            continue
        if _HEADING.match(line) and not containers:
            break
        box = _CRITERION.match(line)
        if not box:
            continue
        rest = box.group(2)
        tagged = _KIND.match(rest)
        kind, rest = (tagged.group(1), tagged.group(2)) if tagged else (None, rest)
        criteria.append(Criterion(len(criteria) + 1, box.group(1) != " ", kind, " ".join(rest.split()), number))
    return criteria


def criterion_version(issue: int, criterion: Criterion) -> str:
    return telemetry_digest({"issue": issue, "index": criterion.index, "kind": criterion.kind,
                             "text": criterion.text})


MET_KINDS = ("code", "human", "note")


def ac_id(criterion: Criterion) -> str:
    """The id a verify block's `ac` uses for the criterion: `AC` and its 1-based index."""
    return f"AC{criterion.index}"


def review_criteria(criteria: Sequence[Criterion], asked: Collection[str] = ()) -> list[Criterion]:
    """The unticked `human` criteria the owner is asked about from the page.

    None when an unticked criterion of another kind than `MET_KINDS` still waits on the runner (a `code` box of a
    held issue counts as met). A criterion whose `ac_id` is in `asked`, the `ac` ids of the held verify block's
    checks (upper-cased), is left to the runner, which asks it when due."""
    open_ = [c for c in criteria if not c.ticked]
    if any(c.kind not in MET_KINDS for c in open_):
        return []
    return [c for c in open_ if c.kind == "human" and ac_id(c) not in asked]


def live_prompts(markers: Sequence[fm.Marker]) -> list[fm.Marker]:
    """The live runner prompts among `markers`, which are the trusted (OWNER, MEMBER) ones of one issue."""
    return [m for m in markers
            if m.kind == foa.KIND and verify_answer.is_runner_prompt(m) and fm.is_live(m, markers)]


def review_key(slug: str, issue: int, index: int) -> str:
    return f"{slug}#{issue}/ac{index}"


def _review_item(project_id: str, slug: str, issue: int, held: int, criterion: Criterion,
                 blocking: list[int]) -> dict:
    return {
        "key": review_key(slug, issue, criterion.index), "project_id": project_id, "repo": slug,
        "issue": issue, "comment_id": None, "url": f"https://github.com/{slug}/issues/{issue}",
        "reason": REVIEW_REASON, "kind": REVIEW_KIND, "question": heading_text(criterion.text),
        "criterion_text": criterion.text, "detail": criterion.text,
        "check_id": "", "reading": "", "questions": [], "items": [], "answers": list(REVIEW_ANSWERS),
        "paid": False, "confirm": "", "answered": False, "held_work": held, "blocking": list(blocking),
        "version": criterion_version(issue, criterion), "criterion": criterion.index,
    }


def _look_answered(slug: str, issue: int, comments: Sequence[dict], call: Callable[[list[str]], Any] | None,
                   cancelled: Callable[[], bool]) -> bool:
    """Whether a pull request a trusted approval names merged under a look approval (ADR-console-054 D8).

    A merged head counts when the latest trusted answer naming it approves it, or when it keeps an earlier
    approval (issue 1211), judged at the merge commit's first parent. One pull is read per pull request a trusted
    approval names, ascending, stopping at the first match, then at most one commit read and
    `look_marker.READ_LIMIT` carry reads; the stop is asked before each read, a stopped read propagates and any
    other failed or unreadable read keeps the card."""
    rest = [{"id": _comment_id(c.get("fullDatabaseId")), "body": c.get("body"), "updated_at": c.get("updatedAt"),
             "author_association": c.get("authorAssociation")}
            for c in comments if c.get("authorAssociation") in look_marker.TRUSTED]

    def get(path: str) -> Any:
        if cancelled():
            raise forge_api.ForgeError("cancelled")
        return (call or forge_api.gh_json)(["api", f"repos/{slug}/{path}"])

    for pr in look_marker.look_prs(rest, issue):
        try:
            pull = get(f"pulls/{pr}")
            if look_marker.merged_under_look(rest, issue, pr, pull, get):
                return True
        except forge_api.ForgeError as error:
            if error.code == "cancelled":
                raise
        except look_marker.Unreadable:
            continue
    return False


def _labels(node: dict) -> list[str]:
    connection = node.get("labels")
    if connection is None:
        return []
    names = connection.get("nodes") if isinstance(connection, dict) else None
    if not isinstance(names, list) or not all(isinstance(n, dict) and isinstance(n.get("name"), str)
                                              for n in names):
        raise _invalid("issue labels is not a connection of names")
    return [n["name"] for n in names]


def _body(node: dict) -> str:
    body = node.get("body")
    if body is None:
        return ""
    if not isinstance(body, str):
        raise _invalid("issue body is not a string")
    return body


def _item(project_id: str, slug: str, issue: int, held: int, marker: fm.Marker,
          blocking: list[int]) -> dict:
    reason = marker.fields["reason"]
    decision = reason == "decision"
    return {
        "key": item_key(slug, issue, marker.comment_id), "project_id": project_id, "repo": slug,
        "issue": issue, "comment_id": marker.comment_id,
        "url": f"https://github.com/{slug}/issues/{issue}#issuecomment-{marker.comment_id}",
        "reason": reason, "kind": reason, "question": foa.marker_sentence(marker), "detail": "",
        "questions": ([{"question": q["question"], "options": list(q["options"]), "chosen": q["chosen"],
                        "recommended": rec}
                       for q, rec in zip(foa.verified_questions(marker), foa.recommended(marker))]
                      if decision else []),
        "items": [] if decision else foa.marker_items(marker), "answers": [], "paid": False, "confirm": "",
        "answered": foa.answered(marker), "held_work": held, "blocking": list(blocking),
    }


def _detail(marker: fm.Marker) -> str:
    """The body after the sentence, less the runner's own trailing answer boxes."""
    lines = [line.removesuffix("\r") for line in marker.body.split("\n")[2:]]
    while lines and not lines[-1]:
        lines.pop()
    boxes = re.compile(r"\s*[-*] \[[ xX]\] (?:" + "|".join(map(re.escape, verify_answer.labels(marker))) + r")\s*")
    while lines and verify_answer.labels(marker) and boxes.fullmatch(lines[-1]):
        lines.pop()
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines)


_SENTENCE_END = re.compile(r"[.?!][\"')\]]*(?=\s|$)")


def _ask_heading(marker: fm.Marker) -> tuple[str, str, str]:
    """The `(question, check_id, detail)` of a verification prompt: a manual check is headed by the
    first sentence of its ask, anything the reader cannot split keeps its sentence and whole detail."""
    sentence, detail = foa.marker_sentence(marker), _detail(marker)
    whole = (sentence, "", detail)
    if marker.fields.get("reason") != verify_answer.ASK or not detail:
        return whole
    check_id = verify_answer.ask_check_id(sentence)
    first, newline, rest = detail.partition("\n")
    if not check_id or first.strip().startswith(("```", "~~~")):
        return whole
    cut = _SENTENCE_END.search(first)
    head, tail = (first[:cut.end()], first[cut.end():]) if cut else (first, "")
    lines = [tail.strip(), *(rest.split("\n") if newline else [])]
    while lines and not lines[0].strip():
        lines.pop(0)
    return " ".join(head.split()), check_id, "\n".join(lines)


_READING = re.compile(r"(?<!\S)Reading:(.*)$")


def _reading(detail: str) -> tuple[str, str]:
    """The `(reading, detail_without_it)` of a manual check's detail: the rest of the first line holding
    `Reading:` outside a fence, whitespace collapsed; an empty rest is no reading."""
    lines = detail.split("\n")
    fenced = False
    for index, line in enumerate(lines):
        if line.strip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        found = None if fenced else _READING.search(line)
        reading = " ".join(found.group(1).split()) if found else ""
        if not reading:
            continue
        before = line[:found.start()].rstrip()
        kept = [*lines[:index], *([before] if before else []), *lines[index + 1:]]
        while kept and not kept[-1].strip():
            kept.pop()
        while kept and not kept[0].strip():
            kept.pop(0)
        return reading, "\n".join(kept)
    return "", detail


def _verify_item(project_id: str, slug: str, issue: int, held: int, marker: fm.Marker,
                 runner_markers: Sequence[fm.Marker], blocking: list[int]) -> dict:
    reason = marker.fields["reason"]
    question, check_id, detail = _ask_heading(marker)
    reading, detail = _reading(detail) if reason == verify_answer.ASK else ("", detail)
    return {
        "key": item_key(slug, issue, marker.comment_id), "project_id": project_id, "repo": slug,
        "issue": issue, "comment_id": marker.comment_id,
        "url": f"https://github.com/{slug}/issues/{issue}#issuecomment-{marker.comment_id}",
        "reason": reason, "kind": verify_answer.kind_of(marker), "question": question,
        "detail": detail, "check_id": check_id, "reading": reading, "questions": [], "items": [],
        "answers": list(verify_answer.ANSWERS[reason]),
        "paid": verify_answer.is_paid(marker), "confirm": f"{slug}#{issue}" if reason == "verify-approve" else "",
        "answered": verify_answer.answered(marker, runner_markers), "held_work": held,
        "blocking": list(blocking), "version": verify_answer.content_version(marker),
    }


_BLOCK_FENCE = re.compile(r"(?m)^```verify[ \t]*\r?$")


def _holds_block(comments: list[dict]) -> bool:
    """Whether a trusted comment opens a verify fence, so the node must be read for its waits."""
    return any(c.get("authorAssociation") in verify_answer.TRUSTED and isinstance(c.get("body"), str)
               and _BLOCK_FENCE.search(c["body"]) for c in comments)


def _default_branch(node: dict) -> str:
    repository = node.get("repository")
    branch = repository.get("defaultBranchRef") if isinstance(repository, dict) else None
    name = branch.get("name") if isinstance(branch, dict) else None
    if not isinstance(name, str) or not name:
        raise _invalid("a node holding a verify block has no repository.defaultBranchRef.name")
    return name


def _what(wait: verify_wait.Wait) -> str:
    """What a wait is for: the first sentence of its check's text, else a plain waiting for approval."""
    text = " ".join(wait.text.split())
    if not text:
        return f"{wait.ac} waits for your approval to run"
    found = _SENTENCE_END.search(text)
    return cut(text[:found.end()] if found else text, MAX_ASK_CHARS)


def _wait_member(wait: verify_wait.Wait) -> dict:
    return {"reason": wait.reason,
            "until": wait.until.astimezone(timezone.utc).isoformat() if wait.until is not None else None,
            "what": _what(wait)}


def _waiting_item(project_id: str, slug: str, issue: int, held_work: int, held, wait: verify_wait.Wait,
                  blocking: list[int]) -> dict:
    member = _wait_member(wait)
    return {
        "key": f"{slug}#{issue}/wait/{held.block_id}/{wait.check}", "project_id": project_id, "repo": slug,
        "issue": issue, "comment_id": held.block_id,
        "url": f"https://github.com/{slug}/issues/{issue}#issuecomment-{held.block_id}",
        "reason": "verify-wait", "kind": "waiting", "question": member["what"], "detail": "", "questions": [],
        "items": [], "answers": [], "paid": False, "confirm": "", "answered": False, "held_work": held_work,
        "blocking": list(blocking), "wait": member,
    }


def items_from_node(project_id: str, slug: str, node: dict, clock: Callable[[], datetime] | None = None,
                    cancelled: Callable[[], bool] = lambda: False,
                    call: Callable[[list[str]], Any] | None = None) -> list[dict]:
    """The inbox items of one search node: one per live owner-action marker of a trusted comment, and
    for an issue holding a verify block one more per owner check that waits with no prompt (`wait`)."""
    if cancelled():
        raise forge_api.ForgeError("cancelled")
    if not isinstance(node, dict):
        raise _invalid("search node is not an object")
    held_work = _held_work(node)
    blocks = _blocking(node, slug)
    number = node.get("number")
    if isinstance(number, bool) or not isinstance(number, int):
        raise _invalid("search node number is not an integer")
    node = verify_wait.with_every_comment(slug, node)
    comments = _comments(node)
    markers = []
    runner_markers = []
    runner_comments = []
    for comment in comments:
        association = comment.get("authorAssociation")
        if association not in foa.TRUSTED:
            continue
        if association in verify_answer.TRUSTED and isinstance(comment.get("body"), str):
            runner_comments.append((_comment_id(comment.get("fullDatabaseId")), association, comment["body"]))
        marker = fm.parse({"id": _comment_id(comment.get("fullDatabaseId")), "body": comment.get("body"),
                           "updated_at": comment.get("updatedAt")})
        if marker is None:
            continue
        markers.append(marker)
        if association in verify_answer.TRUSTED:
            runner_markers.append(marker)
    markers.sort(key=lambda m: m.comment_id)
    runner_markers.sort(key=lambda m: m.comment_id)
    items = [_item(project_id, slug, number, held_work, m, blocks) for m in markers
             if m.kind == foa.KIND and m.fields.get("reason") in foa.REASONS and fm.is_live(m, markers)]
    live = live_prompts(runner_markers)
    prompts = [(m, _verify_item(project_id, slug, number, held_work, m, runner_markers, blocks)) for m in live]
    items += [item for _, item in prompts]
    if (node.get("__typename") == "Issue" and HELD_LABEL in _labels(node)
            and node.get("authorAssociation") in verify_answer.TRUSTED and not live):
        reviews = review_criteria(acceptance_criteria(_body(node)), verify_answer.held_acs(runner_comments))
        lines = _body(node).split("\n")
        looks = [c for c in reviews if look_marker.marker_line(lines[c.line])]
        if looks and _look_answered(slug, number, comments, call, cancelled):
            reviews = [c for c in reviews if c not in looks]
        items += [_review_item(project_id, slug, number, held_work, c, blocks) for c in reviews]
    if node.get("__typename") == "Issue" and _holds_block(comments):
        held, waits = verify_wait.held_waits(
            comments, slug, _default_branch(node), clock or (lambda: forge_api.server_now()), cancelled)
        for wait in waits:
            if wait.prompted:
                for marker, item in prompts:
                    if (marker.fields.get("reason") in verify_wait.ASKING and marker.fields.get("block") == held.key
                            and marker.fields.get("check") == str(wait.check)):
                        item["wait"] = _wait_member(wait)
            else:
                items.append(_waiting_item(project_id, slug, number, held_work, held, wait, blocks))
    return sorted(items, key=lambda item: item["key"])


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


def _read_pages(argv: Callable[[str | None], list[str]], call: Callable[[list[str]], Any],
                cancelled: Callable[[], bool]) -> tuple[list, bool, int]:
    """The nodes of one search, whether it was still paging after `MAX_CALLS` calls, and its `issueCount`."""
    nodes: list = []
    cursors: set[str] = set()
    after: str | None = None
    total = 0
    for _ in range(MAX_CALLS):
        if cancelled():
            raise forge_api.ForgeError("cancelled")
        page, more, cursor, total = _page(call(argv(after)))
        nodes += page
        if not more:
            return nodes, False, total
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise _invalid("search endCursor is missing or repeated")
        cursors.add(cursor)
        after = cursor
    return nodes, True, total


def read_items(project_id: str, slug: str, *,
               call: Callable[[list[str]], Any] = forge_api.gh_json,
               cancelled: Callable[[], bool] = lambda: False,
               now: Callable[[], datetime] | None = None) -> list[dict]:
    """Every inbox item of one repository, sorted by `key`; raises `forge_api.ForgeError`.

    `now` is the clock of the waits, `forge_api.server_now` when None (looked up at call time); it is
    called at most once per read, whatever the number of nodes, and across both searches."""
    memo: list[datetime] = []

    def clock() -> datetime:
        if not memo:
            memo.append((now if now is not None else forge_api.server_now)())
        return memo[0]

    nodes, paging, total = _read_pages(lambda after: search_argv(slug, after), call, cancelled)
    if paging:
        raise forge_api.ForgeError("payload_incomplete", f"more than {MAX_CALLS} pages")
    if len(nodes) < total:
        raise forge_api.ForgeError("payload_incomplete", f"{len(nodes)} of {total} search results")
    items = [i for node in nodes for i in items_from_node(project_id, slug, node, clock, cancelled, call)]
    seen = {node.get("number") for node in nodes if isinstance(node, dict)}
    held, _, _ = _read_pages(lambda after: held_argv(slug, after), call, cancelled)
    for node in held:
        if isinstance(node, dict) and node.get("number") in seen:
            continue
        try:
            items += items_from_node(project_id, slug, node, clock, cancelled, call)
        except forge_api.ForgeError as error:
            if error.code != "payload_incomplete":
                raise
    return sorted(items, key=lambda item: item["key"])


_OPEN_LEADING = "\"`'([<{"
_CLOSE_TRAILING = "\"`'.,;:!?)]}>"
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _core(raw: str) -> str:
    """The word `raw` without the quotes, brackets and punctuation around it."""
    token = raw
    while True:
        stripped = token.lstrip(_OPEN_LEADING).rstrip(_CLOSE_TRAILING)
        if stripped == token:
            return token
        token = stripped


_PATH_START = ("/", "~/", "./", "../")


def _names_a_path(token: str, is_folder: Callable[[str], bool] | None = None) -> bool:
    """Whether `token` is a PNG name, a path written as one (`/`, `~/`, `./`, `../` first or `/` last) or,
    when `is_folder` says so, a relative word with a `/`; `and/or`, `light/dark` and `1440/480` are words."""
    if not token or "://" in token:
        return False
    if token.lower().endswith(".png") and len(token) > 4:
        return True
    if "/" not in token:
        return False
    return token.startswith(_PATH_START) or token.endswith("/") or (is_folder is not None and is_folder(token))


_CONNECTORS = frozenset(("in", "under", "at", "on", "from", "of", "into", "by", "to", "and", "or"))
REVIEW_HEADING = "Review what this issue asks you to check."


_MEASURED = re.compile(r"\s[-\u2010-\u2015\u2212]+\s+measured:", re.IGNORECASE)


def heading_text(text: str, is_folder: Callable[[str], bool] | None = None) -> str:
    """`text` cut before its first measured tail, without the words that name a PNG file or a folder and the
    connecting words left before them.

    A word with a `/` is a folder only when written as a path or when `is_folder` says it is one."""
    text = _MEASURED.split(text, 1)[0]
    kept: list[str] = []
    for raw in text.split():
        core = _core(raw)
        if not _names_a_path(core, is_folder):
            kept.append(raw)
            continue
        while kept and _core(kept[-1]).lower() in _CONNECTORS and kept[-1] == _core(kept[-1]):
            kept.pop()
        punctuation = "".join(c for c in raw[raw.rfind(core) + len(core):] if c in ".,;:!?")
        if kept and punctuation and kept[-1][-1] not in ".,;:!?":
            kept[-1] += punctuation[0]
    return " ".join(kept) or REVIEW_HEADING


def named_pictures(text: str) -> tuple[list[str], list[str]]:
    """The PNG names and the folders a prompt's text mentions, first-seen order, no repeats."""
    names: list[str] = []
    folders: list[str] = []
    for raw in text.split():
        token = _core(raw)
        if not token or "://" in token:
            continue
        if token.lower().endswith(".png") and len(token) > 4:
            if token not in names:
                names.append(token)
        elif "/" in token and token not in folders:
            folders.append(token)
    return names, folders


def _spellings(roots: Sequence[Path]) -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = []
    for root in roots:
        written = os.path.normpath(os.path.abspath(root))
        if os.path.isdir(written):
            found.append((written, os.path.realpath(root)))
    return found


def _open_inside(path: str, roots: Sequence[tuple[str, ...]], *, directory: bool = False) -> int | None:
    """An open descriptor of `path` found by walking down from a root, or None when no root holds it.

    No component below the root is followed through a symlink; raises OSError."""
    match = None
    for spellings in roots:
        for spelling in spellings:
            if path == spelling or path.startswith(spelling.rstrip(os.sep) + os.sep):
                match = (spellings[1], [part for part in path[len(spelling):].split(os.sep) if part])
                break
        if match:
            break
    if match is None:
        return None
    real, parts = match
    current = os.open(real, os.O_RDONLY | _DIRECTORY)
    try:
        if not parts:
            if not directory:
                raise IsADirectoryError(path)
            handed, current = current, -1
            return handed
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            if last and not directory:
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            else:
                flags = os.O_RDONLY | os.O_NOFOLLOW | _DIRECTORY
            try:
                child = os.open(part, flags, dir_fd=current)
            except NotADirectoryError:
                # A plain file standing where a folder is named holds nothing; a symlink does not.
                if not stat.S_ISLNK(os.stat(part, dir_fd=current, follow_symlinks=False).st_mode):
                    raise FileNotFoundError(part) from None
                raise
            os.close(current)
            current = child
            if not last and not stat.S_ISDIR(os.fstat(current).st_mode):
                raise FileNotFoundError(part)
        if directory and not stat.S_ISDIR(os.fstat(current).st_mode):
            raise NotADirectoryError(path)
        handed, current = current, -1
        return handed
    finally:
        if current >= 0:
            os.close(current)


def _serve(fd: int, pictures_dir: Path) -> str | None:
    """The stored id of the PNG behind `fd`, or None when it is no regular, small, readable PNG."""
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > pictures.MAX_BYTES:
            return None
        data = b""
        while len(data) <= pictures.MAX_BYTES:
            piece = os.read(fd, pictures.MAX_BYTES + 1 - len(data))
            if not piece:
                break
            data += piece
        if len(data) > pictures.MAX_BYTES:
            return None
        pictures.checked_png(data)
        return pictures.store(pictures_dir, data)[0]
    except (OSError, pictures.NotPng):
        return None


def attach_pictures(item: dict, roots: Sequence[Path], pictures_dir: Path, *,
                    home: Path | None = None) -> dict:
    """`item` with the pictures its text names stored and listed (module docstring, Pictures)."""
    names, folders = named_pictures("\n".join((item["question"], item.get("criterion_text", ""), item["detail"],
                                                item.get("reading", ""))))
    allowed = _spellings(roots)
    home_dir = str(home if home is not None else Path.home())
    project = os.path.abspath(roots[0]) if roots else os.getcwd()

    def absolute(token: str, folder: str | None = None) -> str:
        if token.startswith("/"):
            return os.path.normpath(token)
        if token.startswith("~/"):
            return os.path.normpath(os.path.join(home_dir, token[2:]))
        return os.path.normpath(os.path.join(folder if folder is not None else project, token))

    found: list[dict] = []
    missing: list[str] = []
    listed: set[str] = set()
    chosen: list[str] = []
    named_pass = True

    def add(path: str, fd: int) -> None:
        try:
            if path in listed or len(found) >= MAX_PICTURES:
                return
            picture_id = _serve(fd, pictures_dir)
            if picture_id is None:
                return
            listed.add(path)
            if named_pass:
                chosen.append(path)
            found.append({"id": picture_id, "line": os.path.basename(path)[:MAX_PICTURE_LINE_CHARS],
                          "pair": None})
        finally:
            os.close(fd)

    folder_paths = [absolute(folder) for folder in folders]
    for name in names:
        if name.startswith(("/", "~/")):
            candidates = [absolute(name)]
        else:
            candidates = [absolute(name, folder) for folder in folder_paths] + [absolute(name)]
        inside, absent, skipped = 0, 0, False
        for path in candidates:
            try:
                fd = _open_inside(path, allowed)
            except FileNotFoundError:
                inside += 1
                absent += 1
                continue
            except OSError:
                skipped = True
                break
            if fd is None:
                continue
            add(path, fd)
            skipped = True
            break
        if not skipped and inside and inside == absent and len(missing) < MAX_PICTURES:
            missing.append(name)

    named_pass = False
    for folder in folder_paths:
        if len(found) >= MAX_PICTURES:
            break
        if any(os.path.dirname(path) == folder.rstrip(os.sep) for path in chosen):
            continue
        try:
            folder_fd = _open_inside(folder, allowed, directory=True)
        except OSError:
            continue
        if folder_fd is None:
            continue
        try:
            for entry in sorted(name for name in os.listdir(folder_fd) if name.lower().endswith(".png")):
                path = os.path.join(folder, entry)
                try:
                    fd = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder_fd)
                except OSError:
                    continue
                add(path, fd)
        except OSError:
            pass
        finally:
            os.close(folder_fd)
    if "criterion_text" in item:
        def is_folder(token: str) -> bool:
            try:
                fd = _open_inside(absolute(token), allowed, directory=True)
            except OSError:
                return False
            if fd is None:
                return False
            os.close(fd)
            return True

        item = {**item, "question": heading_text(item["criterion_text"], is_folder)}
    return {**item, "pictures": found, "missing_pictures": missing}


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
