"""The look marker, the look approval and the merge judgment over them (issue 1138).

A look marker is an acceptance criterion written exactly as one line of an issue body:

    - [ ] [human] before merge: <what the owner looks at> — measured: <who judges, where>

The dash before `measured:` is U+2014 EM DASH with one space each side. The box may be
ticked (`[x]`, `[X]`); a ticked box stays marked. Each body line is stripped of trailing
spaces, tabs and `\\r`, then must match the form in full: a misspelt form, a leading space,
an ordinary `[human]` criterion or a hold in prose is not a marker.

Fences: a line of at most three spaces then three or more backticks or tildes opens a fence
when none is open; while open, a line of at most three spaces, the same character at least as
many times as the opening run, and only spaces or tabs after it closes it. Lines inside a fence
and the fence lines never match; an unclosed fence runs to the end of the body.

The look approval is an issue comment whose first line is
`<!-- agent:look v1 issue=<issue> pr=<pr> head=<head> answer=<answer> message=<message> -->`
with `answer` one of `approved`, `changes` or `fix`, `head` the 40-hex head commit and `message` the
console message it came from (a `forge_markers.VALUE`). Line 2 is `The owner approved head
<head[:7]> of pull request <pr> after a look.`, or for `changes` `The owner asked for changes to
head <head[:7]> of pull request <pr>.` For `fix` line 2 is `The owner approved head <head[:7]> of
pull request <pr> with one fix.` and line 3 is `The fix: <the owner's words>`.

Trust and latest-wins: `look_answer` reads only comments whose `author_association` is in
`TRUSTED` (OWNER or MEMBER), filtered before parsing so an untrusted `end` marker ends nothing.
Among the live `look` markers naming the issue, the pull request and the head, the one with the
largest comment id is the answer, whatever fields it holds; a marker with no `answer` field is
a candidate that approves nothing.

`judge` walks the issues in ascending number. The first marked issue with no answer, whose
answer is not `approved`, or for which the head is unknown, yields `Verdict(False, number,
covers)`; otherwise `Verdict(True, marked=...)`, `marked` the numbers of the marked issues it
admitted, ascending. An unmarked issue needs nothing.

Near misses: a body line outside fences that is not a marker and, once its inline code spans
(backtick runs) are removed, is criterion-shaped is a near miss, a marker its author meant and
misspelt. Criterion-shaped is an optional list bullet (`-`, `*`, `+`) then one or more bracket
groups (`[ ]`, `[human]`, `[code]`); the line is a near miss when it matches `before[\\s_-]*merg`
(any case) and a bracket group is `[human]` (any case), or when the bracket groups are
immediately followed by `before[\\s_-]*merg`. Prose, a bullet that only talks about the
marker and text inside inline code are never near misses. `near_misses` returns them in body order with their 1-based
line numbers; `look-lint` prints them, and a body with any is refused even beside a valid marker.

The console reads a look-marker line with `marker_line`, and the lines `read_look` and `tick_markers` recognize with `marker_lines`. It names the pull requests an issue's
approvals mention with `look_prs` and asks `merged_under_look` whether a merged pull request's
head was merged under an approval, exact or kept; `merged_under_look` reads the head commit of
the merged REST pull request with `merged_head`. `tick_markers` returns a body with the box of every unticked
look-marker line outside fences changed from `- [ ]` to `- [x]` and the number it changed; every
other byte of the body, the rest of a changed line (trailing spaces, `\\r`) included, is kept, and
lines are split and joined on `\\n` alone.

Kept approvals (issue 1211). An approval of an earlier head A stays valid for the current head H of
the same pull request while no commit after A changes a look file. `.github/look-files.json`
(`{"version": 1, "sets": {<name>: [<glob>, ...]}}`, nothing else) names the look file sets, read at
the pinned base commit B. A set is covered when one of its globs matches a file name (or previous
name) of the compare `B...A`, the pull request's own change at the approved head; the look files
are the covered sets' globs. `glob_match` splits on `/`: `**` is zero or more whole segments, `*`
and `?` stay inside a segment, anything else is literal.
D3, the candidate: `carry_candidate` is the latest trusted live look marker of the issue and pull
request, whatever its head, only when no trusted live look marker names H and its answer is
`approved` or `fix` with a 40-hex head. A later `changes` withdraws the carry.
D4, `kept(candidate, head, carry)` judges from reads it is given (`Carry(base, reads)`) and names
the reads it lacks in `Kept.need`: round one is the set file at B and the compares `B...A`,
`A...H` and `B...H`; round two is one compare per commit the pull request added after A. A readable
refusal (a 404 read passed as None, `A...H` not `ahead`, no covered set) is `Kept(False)`; a
successful answer the rule cannot read raises `Unreadable`. There is no final-diff shortcut. The
commits after A are walked first-parent from H to A and must be exactly the commits `B...H` has
and `B...A` lacks, at most `CHAIN_LIMIT`, and no second parent may be a pull request commit. A
one-parent commit is a look commit when its compare lists a look file. A merge is clean when, for
every look file f its four compares list, f is neither renamed nor copied, every listing of f
carries a patch when a side lists f, and each side's added and removed lines of f equal the other side's change
(`P1...c` equals `P1...P2`, `P2...c` equals `P2...P1`; context lines and hunk bounds are ignored, since an independent edit moves them). An
`approved` candidate is kept at zero look commits, a `fix` at exactly one.
`settle` drives `kept` for at most `CARRY_RUNS` runs and `READ_LIMIT` reads through a `read`
callable (the parsed JSON, None for a 404, an exception for anything else), and
`merged_under_look` applies it to a merged pull request at its merge commit's first parent.
`judge` takes an optional `Carry`; a refusal lists the `candidates` and the `need` of undecided
issues, and an `Unreadable` read fails its issue with no need.

Carried approvals (issue 1566). An `approved` approval may carry a `pictures=<digest>` field, the
sha256 of the sorted, newline-joined console picture ids (`picture_id` is the sha256 of the
picture bytes, `picture_digest` folds the ids with their roles, `before` or `after`, so swapped
pictures are another card), and a trusted live `look-carry` line, written by
`look-approval carry`, may name it:
`<!-- agent:look-carry v1 issue=<issue> pr=<pr> from=<approved head> to=<head> pictures=<digest> -->`
then `Carried the owner's look approval of head <from[:7]> of pull request <pr> to head <to[:7]>:
only merges of the integration branch came in and the re-rendered pictures are unchanged.`
When overlapping writers leave several lines, `carry_line` names the smallest comment id, the one
`forge_markers.write` keeps. `carry_candidate` fills `pictures` only for an `approved` latest marker whose field is a 64-hex
digest, and `line` only when `carry_line` finds a trusted live line naming exactly the issue,
the pull request, the candidate head, the asked head and that digest. For such a candidate `kept`
asks `merges_only` first: it reads only `B...A`, `A...H` and `B...H` (never the set file), and keeps
the approval when `A...H` is `ahead` and every commit after A, walked first-parent from H, is a
merge with exactly two parents whose second parent is no pull request commit, at most
`CHAIN_LIMIT` of them. When it decides false and the set file was not yet read, `kept` names the
set file and the per-commit compares the issue 1211 rule wants in one batch, so the fallback
decides on the third run; `settle_merges` drives `merges_only` alone. A `fix` answer or an approval
without pictures is judged by the issue 1211 rule exactly as before. An approval with pictures and
no line is kept by nothing: the owner looked at pictures, so only a carry line, which attests the
re-rendered ones, lets a later head stand, whatever the look file sets say.

Carried look files (issue 1597). An `approved` approval with no `pictures` field at all is carried by
a trusted live `look-carry` line that names the look-files rule instead of a digest:
`<!-- agent:look-carry v1 issue=<issue> pr=<pr> from=<approved head> to=<head> rule=look-files -->`
then `Carried the owner's look approval of head <from[:7]> of pull request <pr> to head <to[:7]>:
only merges of the integration branch came in and the pull request's change to the look files is
unchanged.` `carry_matches` is the one predicate that tells the two lines apart: a digest line holds
no `rule` field and a look-files line no `pictures` field, so a line naming both carries nothing.
A malformed `pictures` field is not an absent one and takes no look-files line. `look_files_unchanged`
reads the set file at B and the compares `B...A`, `A...H` and `B...H`, and keeps the approval when
`merges_only` holds, `A...H` lists no look file (the globs of every set, so a merge that brought one in
from the integration branch is refused, and so is a look file that one merge brought in and a later
merge took out again, because each merge is compared with its first parent), and the look-file diff
of `B...A` equals that of `B...H` (a renamed or copied look file compares by its previous name and
blob sha, and a look-file listing with no patch is not comparable). A set file or a
listing it cannot read raises `Unreadable`. When it decides false the issue 1211 rule runs as for a
pictures line; `settle_look_files` drives it alone. `carry_rule` names the rule a candidate's line
must carry, or None.

This module reads no network of its own, runs no subprocess and reads no clock; `settle` and
`merged_under_look` read only through the `read` callable they are given.
"""
import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from agent_tools.claims import forge_markers

KIND = "look"
CARRY_KIND = "look-carry"
PICTURES_RULE = "pictures"
LOOK_FILES_RULE = "look-files"
# Only the owner's own association counts as the owner: ADR-verification-004.
TRUSTED: tuple[str, ...] = ("OWNER", "MEMBER")
ANSWERS: tuple[str, ...] = ("approved", "changes", "fix")
CARRIED: tuple[str, ...] = ("approved", "fix")
ROLES: tuple[str, ...] = ("before", "after")
LOOK_FILES_PATH = ".github/look-files.json"
COMPARE_FILE_LIMIT = 300
CHAIN_LIMIT = 10
CARRY_RUNS = 3
READ_LIMIT = 48
FILE_STATUSES: tuple[str, ...] = ("added", "removed", "modified", "renamed", "copied", "changed", "unchanged")
FIX_WORDS_LIMIT = 2000

LINE = re.compile(r"- \[[ xX]\] \[human\] before merge: (?P<what>\S.*?) — measured: (?P<measured>\S.*)")
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEAD_PATTERN = re.compile(r"[0-9a-f]{40}")
PICTURES_PATTERN = re.compile(r"[0-9a-f]{64}")
NEAR = re.compile(r"before[\s_-]*merg", re.IGNORECASE)
CODE_SPAN = re.compile(r"(`+).*?\1")
SHAPED = re.compile(r"\s*(?:[-*+]\s*)?(?P<groups>(?:\[[^\]]*\]\s*)+)")


@dataclass(frozen=True)
class LookCriterion:
    what: str
    measured: str


@dataclass(frozen=True)
class Look:
    criteria: tuple[LookCriterion, ...]

    @property
    def marked(self) -> bool:
        return bool(self.criteria)

    @property
    def covers(self) -> tuple[str, ...]:
        return tuple(criterion.what for criterion in self.criteria)


@dataclass(frozen=True)
class IssueFacts:
    number: int
    body: str | None
    comments: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class Verdict:
    admit: bool
    issue: int | None = None
    covers: tuple[str, ...] = ()
    marked: tuple[int, ...] = ()
    candidates: tuple["Candidate", ...] = ()
    need: tuple[str, ...] = ()


@dataclass(frozen=True)
class Candidate:
    issue: int
    head: str
    answer: str
    comment_id: int
    pictures: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class Carry:
    base: str
    reads: Mapping[str, Any]


@dataclass(frozen=True)
class Kept:
    kept: bool
    need: tuple[str, ...] = ()


class Unreadable(Exception):
    """A successful forge answer the kept-approval rule cannot read."""


def body_lines(body: str | None) -> Iterator[tuple[int, str]]:
    """Each `(n, line)` of a body outside code fences, `n` 1-based, `line` with its end stripped."""
    fence: tuple[str, int] | None = None
    for n, raw in enumerate((body or "").split("\n"), 1):
        line = raw.rstrip()
        if fence is None:
            opened = FENCE_OPEN.match(line)
            if opened:
                fence = (opened.group(1)[0], len(opened.group(1)))
                continue
        else:
            char, size = fence
            if re.fullmatch(rf" {{0,3}}{re.escape(char)}{{{size},}}[ \t]*", line):
                fence = None
            continue
        yield n, line


def read_look(body: str | None) -> Look:
    """The look criteria an issue body carries outside code fences, in body order."""
    found: list[LookCriterion] = []
    for _, line in body_lines(body):
        matched = LINE.fullmatch(line)
        if matched:
            found.append(LookCriterion(matched["what"], matched["measured"]))
    return Look(tuple(found))


@dataclass(frozen=True)
class NearMiss:
    line: int
    text: str


def _near(line: str) -> bool:
    text = CODE_SPAN.sub("", line)
    shaped = SHAPED.match(text)
    if shaped is None:
        return False
    return bool(NEAR.match(text, shaped.end())
                or (NEAR.search(text) and "[human]" in shaped["groups"].lower()))


def near_misses(body: str | None) -> tuple[NearMiss, ...]:
    """The criterion-shaped lines outside fences that read like a look marker but are not one."""
    return tuple(NearMiss(n, line) for n, line in body_lines(body)
                 if not LINE.fullmatch(line) and _near(line))


def _positive(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} {value!r} is not a positive integer")


def picture_id(data: bytes) -> str:
    """The console's id of one picture: the sha256 of its bytes."""
    return hashlib.sha256(data).hexdigest()


def picture_digest(pictures: Iterable[str | tuple[str | None, str]]) -> str:
    """The digest of a card's pictures: sha256 of the sorted entries joined by newlines.

    An entry is a picture id, or a `(role, id)` pair with `role` `before`, `after` or None; the role is
    part of the entry (`before:<id>`), so two pictures that swap roles are another card. An entry
    with no role is the bare id.
    """
    entries = []
    for item in pictures:
        role, ident = (None, item) if isinstance(item, str) else item
        if not isinstance(ident, str) or not PICTURES_PATTERN.fullmatch(ident) or role not in (None, *ROLES):
            raise ValueError("a picture digest needs 64-hex picture ids, each with no role, before or after")
        entries.append(ident if role is None else f"{role}:{ident}")
    if not entries:
        raise ValueError("a picture digest needs one or more picture ids")
    return hashlib.sha256("\n".join(sorted(entries)).encode("ascii")).hexdigest()


def _digest(value: Any) -> str:
    if not isinstance(value, str) or not PICTURES_PATTERN.fullmatch(value):
        raise ValueError(f"pictures {value!r} is not 64 lowercase hex")
    return value


def approval_fields(issue: int, pr: int, head: str, answer: str, message: str,
                    pictures: str | None = None) -> dict[str, str]:
    """The marker fields of a look approval, in marker order; ValueError outside the grammar."""
    _positive("issue", issue)
    _positive("pr", pr)
    if not isinstance(head, str) or not HEAD_PATTERN.fullmatch(head):
        raise ValueError(f"head {head!r} is not 40 lowercase hex")
    if answer not in ANSWERS:
        raise ValueError(f"answer {answer!r} is not one of {ANSWERS}")
    if not isinstance(message, str) or not re.fullmatch(forge_markers.VALUE, message):
        raise ValueError(f"message {message!r} is outside the marker value grammar")
    fields = {"issue": str(issue), "pr": str(pr), "head": head, "answer": answer, "message": message}
    if pictures is not None:
        if answer != "approved":
            raise ValueError("pictures go with the answer approved and no other")
        fields["pictures"] = _digest(pictures)
    return fields


def approval_body(issue: int, pr: int, head: str, answer: str, message: str,
                  words: str | None = None, pictures: str | None = None) -> str:
    """The comment body of a look approval; `words` is the owner's fix and goes with `fix` alone."""
    fields = approval_fields(issue, pr, head, answer, message, pictures)
    if (answer == "fix") != (words is not None):
        raise ValueError("words go with the answer fix and no other")
    if answer == "fix":
        fix = words.strip()
        if not fix or len(fix) > FIX_WORDS_LIMIT:
            raise ValueError(f"the fix words are empty or longer than {FIX_WORDS_LIMIT} characters")
        sentence = f"The owner approved head {head[:7]} of pull request {pr} with one fix."
        return forge_markers.render(KIND, fields, sentence, f"The fix: {fix}")
    if answer == "approved":
        sentence = f"The owner approved head {head[:7]} of pull request {pr} after a look."
    else:
        sentence = f"The owner asked for changes to head {head[:7]} of pull request {pr}."
    return forge_markers.render(KIND, fields, sentence)


def look_answer(comments: Iterable[Mapping[str, Any]], issue: int, pr: int,
                head: str) -> forge_markers.Marker | None:
    """The latest live look marker of this issue, pull request and head by a trusted author."""
    parsed = [forge_markers.parse(c) for c in comments if c.get("author_association") in TRUSTED]
    markers = [m for m in parsed if m is not None]
    wanted = {"issue": str(issue), "pr": str(pr), "head": head}
    matching = [m for m in markers
                if m.kind == KIND and forge_markers.is_live(m, markers)
                and all(m.fields.get(key) == value for key, value in wanted.items())]
    return max(matching, key=lambda m: m.comment_id, default=None)


def carry_fields(issue: int, pr: int, approved_head: str, head: str, pictures: str | None) -> dict[str, str]:
    """The fields of a look-carry line, in marker order; ValueError outside the grammar.

    A digest names the pictures rule; None names the look-files rule (issue 1597).
    """
    _positive("issue", issue)
    _positive("pr", pr)
    for name, value in (("approved head", approved_head), ("head", head)):
        if not isinstance(value, str) or not HEAD_PATTERN.fullmatch(value):
            raise ValueError(f"{name} {value!r} is not 40 lowercase hex")
    if approved_head == head:
        raise ValueError("a carry names two different heads")
    fields = {"issue": str(issue), "pr": str(pr), "from": approved_head, "to": head}
    if pictures is None:
        return {**fields, "rule": LOOK_FILES_RULE}
    return {**fields, "pictures": _digest(pictures)}


def carry_sentence(pr: int, approved_head: str, head: str, rule: str = PICTURES_RULE) -> str:
    if rule not in (PICTURES_RULE, LOOK_FILES_RULE):
        raise ValueError(f"rule {rule!r} is not one of {(PICTURES_RULE, LOOK_FILES_RULE)}")
    what = ("the re-rendered pictures are unchanged" if rule == PICTURES_RULE
            else "the pull request's change to the look files is unchanged")
    return (f"Carried the owner's look approval of head {approved_head[:7]} of pull request {pr} "
            f"to head {head[:7]}: only merges of the integration branch came in and {what}.")


def carry_body(issue: int, pr: int, approved_head: str, head: str, pictures: str | None) -> str:
    """The comment body of a look-carry line."""
    fields = carry_fields(issue, pr, approved_head, head, pictures)
    rule = PICTURES_RULE if pictures is not None else LOOK_FILES_RULE
    return forge_markers.render(CARRY_KIND, fields, carry_sentence(pr, approved_head, head, rule))


def carry_matches(fields: Mapping[str, str], issue: int, pr: int, approved_head: str, head: str,
                  pictures: str | None) -> bool:
    """Whether a carry line's fields name exactly these and exactly one rule.

    A digest names the pictures rule and the line holds no `rule` field; None names the look-files
    rule and the line holds no `pictures` field. The reader and the writer's contention share it.
    """
    wanted = {"issue": str(issue), "pr": str(pr), "from": approved_head, "to": head}
    if any(fields.get(key) != value for key, value in wanted.items()):
        return False
    if pictures is not None:
        return fields.get("pictures") == pictures and "rule" not in fields
    return fields.get("rule") == LOOK_FILES_RULE and "pictures" not in fields


def carry_line(comments: Iterable[Mapping[str, Any]], issue: int, pr: int, approved_head: str,
               head: str, pictures: str | None) -> int | None:
    """The comment id of the smallest trusted live carry line naming exactly these, else None.

    The smallest id is the winner `forge_markers.write` elects among overlapping writers, so a read
    and a write name the same line.
    """
    parsed = [forge_markers.parse(c) for c in comments if c.get("author_association") in TRUSTED]
    markers = [m for m in parsed if m is not None]
    matching = [m.comment_id for m in markers
                if m.kind == CARRY_KIND and forge_markers.is_live(m, markers)
                and carry_matches(m.fields, issue, pr, approved_head, head, pictures)]
    return min(matching, default=None)


def marker_line(line: str) -> bool:
    """Whether one body line, end-stripped as `body_lines` strips it, is a look marker."""
    return LINE.fullmatch(line.rstrip()) is not None


def marker_lines(body: str | None) -> frozenset[int]:
    """The 1-based numbers of the look-marker lines `read_look` and `tick_markers` recognize, outside fences."""
    return frozenset(n for n, line in body_lines(body) if LINE.fullmatch(line))


def merged_head(pull: Any) -> str | None:
    """The head commit of a REST pull request read that is merged, else None."""
    if not isinstance(pull, dict) or pull.get("merged") is not True:
        return None
    head = pull.get("head")
    sha = head.get("sha") if isinstance(head, dict) else None
    return sha if isinstance(sha, str) and HEAD_PATTERN.fullmatch(sha) else None


def tick_markers(body: str | None) -> tuple[str, int]:
    """The body with every unticked look-marker line outside fences ticked, and how many changed."""
    lines = (body or "").split("\n")
    changed = 0
    for n, line in body_lines(body):
        if LINE.fullmatch(line) and line.startswith("- [ ] "):
            lines[n - 1] = "- [x] " + lines[n - 1][6:]
            changed += 1
    return "\n".join(lines), changed


def contents_path(base: str) -> str:
    return f"contents/{LOOK_FILES_PATH}?ref={base}"


def compare_path(a: str, b: str) -> str:
    return f"compare/{a}...{b}"


COMPARE_PATH = re.compile(r"compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}")


def read_path_ok(path: str, base: str) -> bool:
    """Whether `path` is the set file at `base` or a compare of two full commit shas."""
    return path == contents_path(base) or COMPARE_PATH.fullmatch(path) is not None


def _segment(pattern: str, name: str) -> bool:
    regex = "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in pattern)
    return re.fullmatch(regex, name) is not None


def _glob(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
    if not pattern:
        return not path
    if pattern[0] == "**":
        return any(_glob(pattern[1:], path[n:]) for n in range(len(path) + 1))
    return bool(path) and _segment(pattern[0], path[0]) and _glob(pattern[1:], path[1:])


def glob_match(pattern: str, path: str) -> bool:
    """Whether the glob matches the path: `**` is whole segments, `*` and `?` stay in a segment."""
    return _glob(tuple(pattern.split("/")), tuple(path.split("/")))


SET_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


def _good_glob(glob: Any) -> bool:
    if not isinstance(glob, str) or not glob:
        return False
    return all(part not in ("", ".", "..") for part in glob.split("/"))


def read_look_files(contents: Any) -> dict[str, tuple[str, ...]] | None:
    """The look file sets a contents read of `LOOK_FILES_PATH` declares, or None when unreadable."""
    if not isinstance(contents, dict) or contents.get("type") != "file" \
            or contents.get("encoding") != "base64" or not isinstance(contents.get("content"), str):
        return None
    try:
        raw = base64.b64decode(contents["content"].replace("\n", ""), validate=True)
        parsed = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError):
        return None
    if not isinstance(parsed, dict) or set(parsed) != {"version", "sets"}:
        return None
    version, sets = parsed["version"], parsed["sets"]
    if isinstance(version, bool) or version != 1 or not isinstance(sets, dict) or not sets:
        return None
    found: dict[str, tuple[str, ...]] = {}
    for name, globs in sets.items():
        if SET_NAME.fullmatch(name) is None or not isinstance(globs, list) or not globs \
                or not all(_good_glob(g) for g in globs):
            return None
        found[name] = tuple(globs)
    return found


def patch_hunks(patch: str) -> tuple[tuple[str, ...], ...] | None:
    """The hunks of a file patch, each the tuple of its lines after the `@@` line; None when unreadable."""
    lines = patch.split("\n")
    if lines[-1] == "":
        lines.pop()
    hunks: list[list[str]] = []
    for line in lines:
        if line.startswith("@@ "):
            hunks.append([])
        elif not hunks or line[:1] not in (" ", "+", "-", "\\"):
            return None
        else:
            hunks[-1].append(line)
    return tuple(tuple(hunk) for hunk in hunks)


def _entries(compare: Any) -> list[dict[str, Any]] | None:
    """The file entries of a compare read, or None when it is not readable."""
    if not isinstance(compare, dict):
        return None
    files = compare.get("files")
    if not isinstance(files, list) or len(files) >= COMPARE_FILE_LIMIT:
        return None
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("filename"), str) \
                or entry.get("status") not in FILE_STATUSES:
            return None
        if "previous_filename" in entry and not isinstance(entry["previous_filename"], str):
            return None
        if "patch" in entry and (not isinstance(entry["patch"], str) or patch_hunks(entry["patch"]) is None):
            return None
    return files


def compare_files(compare: Any) -> tuple[str, ...] | None:
    """Every file name and previous name a compare read lists, in order; None when unreadable."""
    files = _entries(compare)
    if files is None:
        return None
    names: list[str] = []
    for entry in files:
        names.append(entry["filename"])
        if "previous_filename" in entry:
            names.append(entry["previous_filename"])
    return tuple(names)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and HEAD_PATTERN.fullmatch(value) is not None


def compare_commits(compare: Any) -> dict[str, tuple[str, ...]] | None:
    """Each commit sha of a compare read mapped to its parent shas; None unless the list is complete."""
    if not isinstance(compare, dict) or not isinstance(compare.get("commits"), list):
        return None
    total = compare.get("total_commits")
    if isinstance(total, bool) or not isinstance(total, int) or total != len(compare["commits"]):
        return None
    found: dict[str, tuple[str, ...]] = {}
    for commit in compare["commits"]:
        parents = commit.get("parents") if isinstance(commit, dict) else None
        if not _sha(commit.get("sha") if isinstance(commit, dict) else None) or not isinstance(parents, list) \
                or not all(isinstance(p, dict) and _sha(p.get("sha")) for p in parents):
            return None
        found[commit["sha"]] = tuple(p["sha"] for p in parents)
    return found


def _look_markers(comments: Iterable[Mapping[str, Any]], issue: int, pr: int) -> list[forge_markers.Marker]:
    """The trusted live look markers naming this issue and pull request, whatever their head."""
    parsed = [forge_markers.parse(c) for c in comments if c.get("author_association") in TRUSTED]
    markers = [m for m in parsed if m is not None]
    return [m for m in markers
            if m.kind == KIND and forge_markers.is_live(m, markers)
            and m.fields.get("issue") == str(issue) and m.fields.get("pr") == str(pr)]


def carry_candidate(comments: Iterable[Mapping[str, Any]], issue: int, pr: int, head: str) -> Candidate | None:
    """The earlier approval that may carry to `head`, or None."""
    comments = list(comments)
    named = _look_markers(comments, issue, pr)
    if not named or any(m.fields.get("head") == head for m in named):
        return None
    latest = max(named, key=lambda m: m.comment_id)
    if latest.fields.get("answer") not in CARRIED or not _sha(latest.fields.get("head")):
        return None
    pictures = latest.fields.get("pictures")
    if latest.fields["answer"] == "approved" and "pictures" not in latest.fields:
        line = carry_line(comments, issue, pr, latest.fields["head"], head, None)
        return Candidate(issue, latest.fields["head"], "approved", latest.comment_id, None, line)
    if latest.fields["answer"] != "approved" or not isinstance(pictures, str) \
            or not PICTURES_PATTERN.fullmatch(pictures):
        return Candidate(issue, latest.fields["head"], latest.fields["answer"], latest.comment_id)
    line = carry_line(comments, issue, pr, latest.fields["head"], head, pictures)
    return Candidate(issue, latest.fields["head"], latest.fields["answer"], latest.comment_id, pictures, line)


def carry_rule(comments: Iterable[Mapping[str, Any]], candidate: Candidate) -> str | None:
    """The rule a carry line for this candidate would name, or None when no rule can carry it."""
    if candidate.pictures is not None:
        return PICTURES_RULE
    if candidate.answer != "approved":
        return None
    parsed = [forge_markers.parse(c) for c in comments if c.get("author_association") in TRUSTED]
    for m in parsed:
        if m is not None and m.comment_id == candidate.comment_id and m.kind == KIND \
                and "pictures" not in m.fields:
            return LOOK_FILES_RULE
    return None


def look_prs(comments: Iterable[Mapping[str, Any]], issue: int) -> tuple[int, ...]:
    """The ascending pull request numbers a trusted live look approval of this issue names."""
    comments = list(comments)
    parsed = [forge_markers.parse(c) for c in comments if c.get("author_association") in TRUSTED]
    markers = [m for m in parsed if m is not None]
    found = set()
    for m in markers:
        pr = m.fields.get("pr")
        if m.kind == KIND and m.fields.get("issue") == str(issue) and forge_markers.is_live(m, markers) \
                and isinstance(pr, str) and re.fullmatch(r"[1-9][0-9]*", pr) \
                and _sha(m.fields.get("head")) and m.fields.get("answer") in CARRIED:
            found.add(int(pr))
    return tuple(sorted(found))


def _entry_of(compare: Any, name: str) -> dict[str, Any] | None:
    return next((e for e in compare["files"] if e["filename"] == name), None)


def _changes(compare: Any, name: str) -> tuple[str, ...]:
    """The added and removed lines of a file's patch, in order, without context or hunk bounds.

    Context lines (and a no-newline marker that follows one) are left out: an independent edit
    elsewhere in the file changes another patch's context and its hunk grouping, not its edit.
    """
    entry = _entry_of(compare, name)
    if entry is None or "patch" not in entry:
        return ()
    changed: list[str] = []
    after_change = False
    for hunk in patch_hunks(entry["patch"]) or ():
        for line in hunk:
            if line[:1] in ("+", "-"):
                changed.append(line)
                after_change = True
            elif line[:1] == "\\" and after_change:
                changed.append(line)
            else:
                after_change = False
    return tuple(changed)


def _clean_merge(parents: tuple[str, ...], commit: str, reads: Mapping[str, Any],
                 look: Callable[[Any], set[str]]) -> bool:
    p1, p2 = parents
    c1, c2, d12, d21 = (reads[compare_path(a, b)] for a, b in ((p1, commit), (p2, commit), (p1, p2), (p2, p1)))
    for name in look(c1) | look(c2) | look(d12) | look(d21):
        listings = [e for compare in (c1, c2, d12, d21) for e in compare["files"]
                    if name in (e["filename"], e.get("previous_filename"))]
        if any(e["status"] in ("renamed", "copied") for e in listings):
            return False
        lists_name = name in compare_files(c1) or name in compare_files(c2)
        if not lists_name:
            continue
        if any("patch" not in e for e in listings):
            return False
        if _changes(c1, name) != _changes(d12, name) or _changes(c2, name) != _changes(d21, name):
            return False
    return True


def _walk(approved_head: str, head: str, own_h: dict[str, tuple[str, ...]],
          own_a: dict[str, tuple[str, ...]]) -> list[str] | None:
    """The commits after the approved head, ascending, or None when the chain is not the 1211 shape."""
    added = set(own_h) - set(own_a) - {approved_head}
    if len(added) > CHAIN_LIMIT:
        return None
    chain: list[str] = []
    current = head
    while current != approved_head:
        parents = own_h.get(current, ())
        if current not in added or current in chain or not 1 <= len(parents) <= 2 \
                or (len(parents) == 2 and parents[1] in own_h):
            return None
        chain.append(current)
        current = parents[0]
    if set(chain) != added:
        return None
    chain.reverse()
    return chain


def _wanted(chain: list[str], own_h: dict[str, tuple[str, ...]]) -> list[str]:
    """The per-commit compares the issue 1211 rule reads for the chain, without repeats."""
    wanted: list[str] = []
    for commit in chain:
        parents = own_h[commit]
        if len(parents) == 1:
            paths = [compare_path(parents[0], commit)]
        else:
            p1, p2 = parents
            paths = [compare_path(p1, p2), compare_path(p2, p1), compare_path(p1, commit), compare_path(p2, commit)]
        wanted.extend(p for p in paths if p not in wanted)
    return wanted


def _chain_reads(approved_head: str, head: str, base: str, reads: Mapping[str, Any]) -> tuple[str, ...] | None:
    """The per-commit compares the issue 1211 rule wants for the chain from `head` to the approved head.

    None when a round-one compare is absent or unreadable or the chain walk refuses.
    """
    own_h = compare_commits(reads.get(compare_path(base, head)))
    own_a = compare_commits(reads.get(compare_path(base, approved_head)))
    if own_h is None or own_a is None:
        return None
    chain = _walk(approved_head, head, own_h, own_a)
    return None if chain is None else tuple(_wanted(chain, own_h))


def merges_only(approved_head: str, head: str, carry: Carry) -> Kept:
    """Whether only merges of the integration branch came in after the approved head (issue 1566)."""
    base, reads = carry.base, carry.reads
    if not (_sha(base) and _sha(approved_head) and _sha(head)) or approved_head == head:
        return Kept(False)
    base_a, a_head, base_h = (compare_path(base, approved_head), compare_path(approved_head, head),
                              compare_path(base, head))
    three = (base_a, a_head, base_h)
    missing = tuple(p for p in three if p not in reads)
    if missing:
        return Kept(False, missing)
    if any(reads[p] is None for p in three):
        return Kept(False)
    ahead = reads[a_head]
    if not isinstance(ahead, dict) or not isinstance(ahead.get("status"), str):
        raise Unreadable(a_head)
    if ahead["status"] != "ahead":
        return Kept(False)
    own_h, own_a = compare_commits(reads[base_h]), compare_commits(reads[base_a])
    if own_h is None or own_a is None:
        raise Unreadable(base_h)
    added = set(own_h) - set(own_a) - {approved_head}
    if len(added) > CHAIN_LIMIT:
        return Kept(False)
    walked: set[str] = set()
    current = head
    while current != approved_head:
        parents = own_h.get(current, ())
        if current not in added or current in walked or len(parents) != 2 or parents[1] in own_h:
            return Kept(False)
        walked.add(current)
        current = parents[0]
    return Kept(walked == added)


def _look_diff(compare: Any, globs: tuple[str, ...]) -> dict[str, tuple[Any, ...]] | None:
    """Each look file a compare lists mapped to what the pull request did to it; None when not comparable.

    A modified, added or removed file maps to its status and changed lines, and needs its patch. A
    renamed or copied one maps to its status, previous name, blob sha and changed lines, and needs a
    previous name and a sha (a pure rename has no patch).
    """
    found: dict[str, tuple[Any, ...]] = {}
    for entry in _entries(compare) or ():
        names = (entry["filename"], entry.get("previous_filename"))
        if not any(isinstance(n, str) and glob_match(g, n) for g in globs for n in names):
            continue
        name = entry["filename"]
        if entry["status"] in ("renamed", "copied"):
            previous, sha = entry.get("previous_filename"), entry.get("sha")
            if not isinstance(previous, str) or not isinstance(sha, str) or not sha:
                return None
            found[name] = (entry["status"], previous, sha, _changes(compare, name))
        elif "patch" not in entry:
            return None
        else:
            found[name] = (entry["status"], None, None, _changes(compare, name))
    return found


def look_files_unchanged(approved_head: str, head: str, carry: Carry) -> Kept:
    """Whether only merges came in and the pull request's change to the look files is the same (issue 1597).

    The look files are every set's globs. A merge that brought a look file in from the integration
    branch is refused, because `A...H` then lists it.
    """
    base, reads = carry.base, carry.reads
    if not (_sha(base) and _sha(approved_head) and _sha(head)) or approved_head == head:
        return Kept(False)
    contents = contents_path(base)
    base_a, a_head, base_h = (compare_path(base, approved_head), compare_path(approved_head, head),
                              compare_path(base, head))
    four = (contents, base_a, a_head, base_h)
    missing = tuple(p for p in four if p not in reads)
    if missing:
        return Kept(False, missing)
    if any(reads[p] is None for p in four):
        return Kept(False)
    if not merges_only(approved_head, head, carry).kept:
        return Kept(False)
    sets = read_look_files(reads[contents])
    if sets is None:
        raise Unreadable(contents)
    globs = tuple(g for group in sets.values() for g in group)
    for path in (a_head, base_a, base_h):
        if compare_files(reads[path]) is None:
            raise Unreadable(path)
    if any(glob_match(g, n) for g in globs for n in compare_files(reads[a_head]) or ()):
        return Kept(False)
    side_a, side_h = _look_diff(reads[base_a], globs), _look_diff(reads[base_h], globs)
    if side_a is None or side_a != side_h:
        return Kept(False)
    # A merge that brought a look file in and a later one that took it out leaves A...H clean: compare each merge with its first parent.
    own_h = compare_commits(reads[base_h])
    chain = _walk(approved_head, head, own_h, compare_commits(reads[base_a])) if own_h is not None else None
    if chain is None:
        return Kept(False)
    steps = tuple(dict.fromkeys(compare_path(own_h[commit][0], commit) for commit in chain))
    missing = tuple(p for p in steps if p not in reads)
    if missing:
        return Kept(False, missing)
    if any(reads[p] is None for p in steps):
        return Kept(False)
    for path in steps:
        names = compare_files(reads[path])
        if names is None:
            raise Unreadable(path)
        if any(glob_match(g, n) for g in globs for n in names):
            return Kept(False)
    return Kept(True)


def kept(candidate: Candidate, head: str, carry: Carry) -> Kept:
    """Whether the candidate's approval still holds at `head`, or the reads still needed to say."""
    if candidate.answer == "approved" and candidate.pictures is not None:
        if candidate.line is None:
            return Kept(False)
        found = merges_only(candidate.head, head, carry)
        if found.kept or found.need:
            return found
        base, reads = carry.base, carry.reads
        contents = contents_path(base)
        if contents not in reads and _sha(base) and _sha(candidate.head) and _sha(head):
            batch = _chain_reads(candidate.head, head, base, reads) or ()
            return Kept(False, (contents,) + tuple(p for p in batch if p not in reads))
    if candidate.answer == "approved" and candidate.pictures is None and candidate.line is not None:
        found = look_files_unchanged(candidate.head, head, carry)
        if found.kept or found.need:
            return found
    return _kept_by_files(candidate, head, carry)


def _kept_by_files(candidate: Candidate, head: str, carry: Carry) -> Kept:
    """The issue 1211 rule: whether no commit after the approved head changed a look file."""
    base, approved_head, reads = carry.base, candidate.head, carry.reads
    if not (_sha(base) and _sha(approved_head) and _sha(head)):
        return Kept(False)
    contents = contents_path(base)
    base_a, a_head, base_h = (compare_path(base, approved_head), compare_path(approved_head, head),
                              compare_path(base, head))
    round_one = (contents, base_a, a_head, base_h)
    missing = tuple(p for p in round_one if p not in reads)
    if missing:
        return Kept(False, missing)
    if any(reads[p] is None for p in round_one):
        return Kept(False)
    sets = read_look_files(reads[contents])
    if sets is None:
        raise Unreadable(contents)
    own_names = compare_files(reads[base_a])
    if own_names is None:
        raise Unreadable(base_a)
    covered = [globs for globs in sets.values() if any(glob_match(g, n) for g in globs for n in own_names)]
    if not covered:
        return Kept(False)
    globs = tuple(g for group in covered for g in group)

    def look(compare: Any) -> set[str]:
        return {n for n in compare_files(compare) or () if any(glob_match(g, n) for g in globs)}

    ahead = reads[a_head]
    if not isinstance(ahead, dict) or not isinstance(ahead.get("status"), str) or compare_files(ahead) is None:
        raise Unreadable(a_head)
    if ahead["status"] != "ahead":
        return Kept(False)
    own_h, own_a = compare_commits(reads[base_h]), compare_commits(reads[base_a])
    if own_h is None or own_a is None:
        raise Unreadable(base_h)
    chain = _walk(approved_head, head, own_h, own_a)
    if chain is None:
        return Kept(False)
    wanted = _wanted(chain, own_h)
    missing = tuple(p for p in wanted if p not in reads)
    if missing:
        return Kept(False, missing)
    if any(reads[p] is None for p in wanted):
        return Kept(False)
    for path in wanted:
        answer = reads[path]
        if not isinstance(answer, dict) or not isinstance(answer.get("status"), str) \
                or compare_files(answer) is None:
            raise Unreadable(path)
    looks = 0
    for commit in chain:
        parents = own_h[commit]
        for p in parents:
            if reads[compare_path(p, commit)]["status"] != "ahead":
                return Kept(False)
        if len(parents) == 1:
            looks += bool(look(reads[compare_path(parents[0], commit)]))
        elif not _clean_merge(parents, commit, reads, look):
            return Kept(False)
    if candidate.answer == "approved":
        return Kept(looks == 0)
    if candidate.answer == "fix":
        return Kept(looks == 1)
    return Kept(False)


def _drive(decide: Callable[[Carry], Kept], base: str, read: Callable[[str], Any]) -> bool:
    """Run `decide` to a decision, reading what it names through `read`, within the carry bounds."""
    reads: dict[str, Any] = {}
    for run in range(1, CARRY_RUNS + 1):
        found = decide(Carry(base, reads))
        if not found.need:
            return found.kept
        if run == CARRY_RUNS or len(reads) + len(found.need) > READ_LIMIT:
            return False
        for path in found.need:
            reads[path] = read(path)
    return False


def settle(candidate: Candidate, head: str, base: str, read: Callable[[str], Any]) -> bool:
    """Run `kept` to a decision, reading what it names through `read`, within the carry bounds."""
    return _drive(lambda carry: kept(candidate, head, carry), base, read)


def settle_look_files(approved_head: str, head: str, base: str, read: Callable[[str], Any]) -> bool:
    """Run `look_files_unchanged` to a decision through `read`, within the same bounds as `settle`."""
    return _drive(lambda carry: look_files_unchanged(approved_head, head, carry), base, read)


def settle_merges(approved_head: str, head: str, base: str, read: Callable[[str], Any]) -> bool:
    """Run `merges_only` to a decision through `read`, within the same bounds as `settle`."""
    return _drive(lambda carry: merges_only(approved_head, head, carry), base, read)


def merged_under_look(comments: Iterable[Mapping[str, Any]], issue: int, pr: int, pull: Any,
                      read: Callable[[str], Any], merge_commit: str | None = None) -> bool:
    """Whether a merged pull request's head was merged under an approval, exact or kept.

    `merge_commit` names the landing commit when the caller resolved it (a pull request merged
    indirectly has a null `merge_commit_sha`); without it the pull's own is read.
    """
    comments = list(comments)
    head = merged_head(pull)
    if head is None:
        return False
    answer = look_answer(comments, issue, pr, head)
    if answer is not None:
        return answer.fields.get("answer") == "approved"
    found = carry_candidate(comments, issue, pr, head)
    if found is None:
        return False
    sha = merge_commit if merge_commit is not None else pull.get("merge_commit_sha")
    if not _sha(sha):
        raise Unreadable("merge_commit_sha")
    commit = read(f"commits/{sha}")
    parents = commit.get("parents") if isinstance(commit, dict) else None
    first = parents[0] if isinstance(parents, list) and parents else None
    if not isinstance(first, dict) or not _sha(first.get("sha")):
        raise Unreadable("merge commit parents")
    return settle(found, head, first["sha"], read)


def judge(pr: int, head: str | None, issues: Iterable[IssueFacts], carry: Carry | None = None) -> Verdict:
    """Admit the merge, or name the first marked issue (by number) that lacks an approval.

    An admit names the marked issues it admitted in `marked`, ascending. A refusal lists the
    candidates of its failing issues when each has one, and their `need` while each is undecided.
    """
    marked = []
    refusal: tuple[int, tuple[str, ...]] | None = None
    candidates: list[Candidate | None] = []
    needs: list[tuple[str, ...] | None] = []
    for facts in sorted(issues, key=lambda f: f.number):
        look = read_look(facts.body)
        if not look.marked:
            continue
        marked.append(facts.number)
        if head is None:
            found = None
        else:
            marker = look_answer(facts.comments, facts.number, pr, head)
            if marker is not None and marker.fields.get("answer") == "approved":
                continue
            found = carry_candidate(facts.comments, facts.number, pr, head)
        need: tuple[str, ...] | None = None
        if found is not None and carry is not None:
            try:
                decided = kept(found, head, carry)
            except Unreadable:
                decided = Kept(False)
            if decided.kept:
                continue
            need = decided.need or None
        if refusal is None:
            refusal = (facts.number, look.covers)
        candidates.append(found)
        needs.append(need)
    if refusal is None:
        return Verdict(True, marked=tuple(marked))
    listed = tuple(c for c in candidates if c is not None) if all(c is not None for c in candidates) else ()
    undecided = tuple(sorted({p for n in needs if n for p in n})) if all(needs) else ()
    return Verdict(False, refusal[0], refusal[1], candidates=listed, need=undecided)
