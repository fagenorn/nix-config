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
with `answer` either `approved` or `changes`, `head` the 40-hex head commit and `message` the
console message it came from (a `forge_markers.VALUE`). Line 2 is `The owner approved head
<head[:7]> of pull request <pr> after a look.`, or for `changes` `The owner asked for changes to
head <head[:7]> of pull request <pr>.`

Trust and latest-wins: `look_answer` reads only comments whose `author_association` is in
`TRUSTED` (OWNER or MEMBER), filtered before parsing so an untrusted `end` marker ends nothing.
Among the live `look` markers naming the issue, the pull request and the head, the one with the
largest comment id is the answer, whatever fields it holds; a marker with no `answer` field is
a candidate that approves nothing.

`judge` walks the issues in ascending number. The first marked issue with no answer, whose
answer is not `approved`, or for which the head is unknown, yields `Verdict(False, number,
covers)`; otherwise `Verdict(True, marked=...)`, `marked` the numbers of the marked issues it
admitted, ascending. An unmarked issue needs nothing.

This module reads no network, runs no subprocess and reads no clock.
"""
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from agent_tools.claims import forge_markers

KIND = "look"
# Only the owner's own association counts as the owner: ADR-verification-004.
TRUSTED: tuple[str, ...] = ("OWNER", "MEMBER")
ANSWERS: tuple[str, ...] = ("approved", "changes")

LINE = re.compile(r"- \[[ xX]\] \[human\] before merge: (?P<what>\S.*?) — measured: (?P<measured>\S.*)")
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEAD_PATTERN = re.compile(r"[0-9a-f]{40}")


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


def read_look(body: str | None) -> Look:
    """The look criteria an issue body carries outside code fences, in body order."""
    found: list[LookCriterion] = []
    fence: tuple[str, int] | None = None
    for raw in (body or "").split("\n"):
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
        matched = LINE.fullmatch(line)
        if matched:
            found.append(LookCriterion(matched["what"], matched["measured"]))
    return Look(tuple(found))


def _positive(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} {value!r} is not a positive integer")


def approval_fields(issue: int, pr: int, head: str, answer: str, message: str) -> dict[str, str]:
    """The marker fields of a look approval, in marker order; ValueError outside the grammar."""
    _positive("issue", issue)
    _positive("pr", pr)
    if not isinstance(head, str) or not HEAD_PATTERN.fullmatch(head):
        raise ValueError(f"head {head!r} is not 40 lowercase hex")
    if answer not in ANSWERS:
        raise ValueError(f"answer {answer!r} is not one of {ANSWERS}")
    if not isinstance(message, str) or not re.fullmatch(forge_markers.VALUE, message):
        raise ValueError(f"message {message!r} is outside the marker value grammar")
    return {"issue": str(issue), "pr": str(pr), "head": head, "answer": answer, "message": message}


def approval_body(issue: int, pr: int, head: str, answer: str, message: str) -> str:
    """The comment body of a look approval."""
    fields = approval_fields(issue, pr, head, answer, message)
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


def judge(pr: int, head: str | None, issues: Iterable[IssueFacts]) -> Verdict:
    """Admit the merge, or name the first marked issue (by number) that lacks an approval.

    An admit names the marked issues it admitted in `marked`, ascending.
    """
    marked = []
    for facts in sorted(issues, key=lambda f: f.number):
        look = read_look(facts.body)
        if not look.marked:
            continue
        marked.append(facts.number)
        marker = look_answer(facts.comments, facts.number, pr, head) if head is not None else None
        if marker is None or marker.fields.get("answer") != "approved":
            return Verdict(False, facts.number, look.covers)
    return Verdict(True, marked=tuple(marked))
