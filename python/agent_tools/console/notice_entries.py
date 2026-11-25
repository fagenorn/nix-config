"""The page lines of a project's open notices and unsettled claim overlaps."""

from collections.abc import Iterable, Mapping

from agent_tools.console.sprints import (
    NOTICE_OWNER, OVERLAP_UNSETTLED, Notice, SprintState, claim_overlaps, open_notices,
    project_notices)

NOTICE_KIND_TEXT = {"claim": "Claim", "heads-up": "Heads-up", "hand-off": "Hand-off"}
NOTICE_UNTIL_TEXT = "until {until}"
NOTICE_OWNER_TEXT = "for you"
NOTICE_FOR_TEXT = "for {title}"
NOTICE_OTHER_TEXT = "for another sprint"
NOTICE_YOU_TEXT = "You"
OVERLAP_UNSETTLED_TEXT = ("{first} and {second} both fix a live fault in {files}; "
                          "the rule could not decide which lands first")


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
