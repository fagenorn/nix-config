"""The wire entries `view` embeds that need no view state: a question card's look and action, a held sprint's
card, and a project's notices and claim overlaps.

`look_entry(question)` is `{"issue", "pr", "head", "state", "line", "approve_index"}` of a card that carries a look
and `action_entry(question)` is `{"command", "approve_index", "line"}` of one that carries an action; each
is None for a card without one. `view` documents both entries in its module docstring.

`notice_entries` and `overlap_entries` are the page lines of a project's open notices and unsettled claim overlaps.

The held-sprint card: a running sprint is held when its ball is `nobody`, no stop is requested, its manager's profile is
not out of usage and not recorded waiting on quota (a sprint waiting on a reset waits on no
person), no check card names its issues, no engine run of its issues is stopped needing the owner
(that run is already one counted item), its report names an issue not landed, held, dropped or
closed out, and nothing has moved for `HELD_AFTER_MS`, the one movement reading the quiet state and the
ball already use, restarted when the sprint's last open question is answered or taken back, and read with every
session associated with the sprint (`view.sprint_sessions_of`), not only the manager's own by name. A sprint named
by the view's `prompted_sprints` raises none (a guest view carries no permission card, so it is told which sprints
have one). It clears the moment the sprint moves or any card or question opens; the sprint's
`state`, `ball`, `ball_text` and `now_text` stay as they are. The card is one entry of `inbox.open`,
after the progress entries and before the sign-ins, ordered by `(held_since, sprint_id)`, and counts
in `inbox_items` and the headline:

    {"type": "inbox_item", "reason": "held_sprint", "key": "held-sprint/<sprint id>", "project_id",
     "sprint_id", "title", "headline": "<title> is holding work and has asked nobody for it",
     "last_status": <the sprint entry's status> | null, "answered": false,
     "waiting_since": "<time the sprint last moved>"}

`HELD_SENTENCE` says what the page offers and is used only when held cards are all that is counted;
`HELD_MIXED_SENTENCE` replaces the tracker sentence beside a held card, which has no tracker link.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from agent_tools.console import answer as owner_answer
from agent_tools.console.sprints import (
    MAX_OPTION_CHARS, NOTICE_OWNER, OVERLAP_UNSETTLED, Notice, Question, SprintState, claim_overlaps, cut,
    open_notices, project_notices)

HELD_AFTER_MS = 3_600_000
HELD_HEADLINE = "{title} is holding work and has asked nobody for it"
HELD_SENTENCE = "Tell the manager what to do from its sprint, or drop the sprint."
HELD_MIXED_SENTENCE = "Tracker cards link to the tracker; a held sprint is answered from its sprint."
NOTICE_KIND_TEXT = {"claim": "Claim", "heads-up": "Heads-up", "hand-off": "Hand-off"}
NOTICE_UNTIL_TEXT = "until {until}"
NOTICE_OWNER_TEXT = "for you"
NOTICE_FOR_TEXT = "for {title}"
NOTICE_OTHER_TEXT = "for another sprint"
NOTICE_YOU_TEXT = "You"
OVERLAP_UNSETTLED_TEXT = ("{first} and {second} both fix a live fault in {files}; "
                          "the rule could not decide which lands first")



def look_entry(question: Question) -> dict | None:
    look = question.look
    if look is None:
        return None
    state, line = "open", owner_answer.LOOK_APPROVES.format(
        option=cut(look.approve, MAX_OPTION_CHARS), head=look.head[:7], pr=look.pr, issue=look.issue)
    if question.look_state == "moved":
        state = "moved"
        line = (owner_answer.LOOK_MOVED.format(found=(question.look_found or "")[:7], head=look.head[:7])
                if question.look_found_state == "open" and question.look_found is not None
                else owner_answer.LOOK_CLOSED.format(state=question.look_found_state))
    elif question.look_state == "posting":
        state, line = "posting", owner_answer.LOOK_RECORDING.format(head=look.head[:7], issue=look.issue)
    elif question.look_state == "failed":
        state, line = "failed", question.look_reason
    approve = question.options.index(look.approve) if look.approve in question.options else None
    return {"issue": look.issue, "pr": look.pr, "head": look.head, "state": state, "line": line,
            "approve_index": approve}


def action_entry(question: Question) -> dict | None:
    action = question.action
    if action is None:
        return None
    approve = question.options.index(action.approve) if action.approve in question.options else None
    return {"command": action.command, "approve_index": approve,
            "line": owner_answer.ACTION_APPROVES.format(option=cut(action.approve, MAX_OPTION_CHARS))}


def _to_text(to: str | None, titles: Mapping[str, str]) -> str:
    if to == NOTICE_OWNER:
        return NOTICE_OWNER_TEXT
    if to in titles:
        return NOTICE_FOR_TEXT.format(title=titles[to])
    return NOTICE_OTHER_TEXT


def overlap_entries(group: Iterable[SprintState], titles: Mapping[str, str],
                    project_id: str) -> list[dict]:
    """One page line for each pair of open claims the default rule cannot order."""
    return [{
        "sprints": list(reading["sprints"]),
        "files": list(reading["files"]),
        "text": OVERLAP_UNSETTLED_TEXT.format(
            first=titles[reading["sprints"][0]], second=titles[reading["sprints"][1]],
            files=", ".join(reading["files"])),
    } for reading in claim_overlaps(project_notices(group, project_id))
        if reading["rule"] == OVERLAP_UNSETTLED]


def notice_entries(group: Iterable[SprintState], titles: Mapping[str, str],
                   owner: Iterable[Notice] = ()) -> list[dict]:
    """The open notices of `group`'s sprints and the owner's as page entries, newest first."""
    found = [(n, s) for s in group for n in open_notices(s)]
    entries = [{
        "id": n.notice_id,
        "sprint_id": s.sprint_id,
        "poster": titles[s.sprint_id],
        "kind": n.kind,
        "kind_text": NOTICE_KIND_TEXT[n.kind],
        "text": n.text,
        "what": n.what if n.kind == "claim" else None,
        "until_text": (NOTICE_UNTIL_TEXT.format(until=n.until) if n.kind == "claim" else None),
        "to_text": (_to_text(n.to, titles) if n.kind == "hand-off" else None),
        "at": n.at,
        "owner": False,
    } for n, s in found]
    entries.extend({
        "id": n.notice_id,
        "sprint_id": None,
        "poster": NOTICE_YOU_TEXT,
        "kind": n.kind,
        "kind_text": NOTICE_KIND_TEXT[n.kind],
        "text": n.text,
        "what": None,
        "until_text": None,
        "to_text": None,
        "at": n.at,
        "owner": True,
    } for n in owner)
    return sorted(entries, key=lambda entry: -entry["id"])


def held_since(now_ms: int | None, quiet_for: int | None, blocked: bool) -> int | None:
    """The milliseconds-since-epoch of a held sprint's latest movement, else None: the sprint is
    unblocked and has been quiet for `HELD_AFTER_MS` at `now_ms`."""
    if now_ms is None or blocked or quiet_for is None or quiet_for < HELD_AFTER_MS:
        return None
    return now_ms - quiet_for


def held_cards(projects: Sequence[Mapping], stops: str) -> list[dict]:
    """The held cards of the project entries' sprints, oldest movement first; `stops` are the
    characters trimmed from a title's end before the headline."""
    held = sorted(((project["project_id"], sprint) for project in projects
                   for sprint in project["sprints"] if sprint["held_since"] is not None),
                  key=lambda pair: (datetime.fromisoformat(pair[1]["held_since"]), pair[1]["sprint_id"]))
    return [{"type": "inbox_item", "reason": "held_sprint", "key": f"held-sprint/{sprint['sprint_id']}",
             "project_id": project_id, "sprint_id": sprint["sprint_id"], "title": sprint["title"],
             "headline": HELD_HEADLINE.format(title=sprint["title"].rstrip(stops)),
             "last_status": sprint["status"], "answered": False,
             "waiting_since": sprint["held_since"]} for project_id, sprint in held]
