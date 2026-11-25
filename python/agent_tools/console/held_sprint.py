"""The held-sprint card of the desk: a derived inbox item with no event row.

A running sprint is held when its ball is `nobody`, no stop is requested, its manager's profile is
not out of usage and not recorded waiting on quota (a sprint waiting on a reset waits on no
person), no check card names its issues, no engine run of its issues is stopped needing the owner
(that run is already one counted item), its report names an issue not landed, held, dropped or
closed out, and nothing has moved for `AFTER_MS`, the one movement reading the quiet state and the
ball already use. It clears the moment the sprint moves or any card or question opens; the sprint's
`state`, `ball`, `ball_text` and `now_text` stay as they are. The card is one entry of `inbox.open`,
after the progress entries and before the sign-ins, ordered by `(held_since, sprint_id)`, and counts
in `inbox_items` and the headline:

    {"type": "inbox_item", "reason": "held_sprint", "key": "held-sprint/<sprint id>", "project_id",
     "sprint_id", "title", "headline": "<title> is holding work and has asked nobody for it",
     "last_status": <the sprint entry's status> | null, "answered": false,
     "waiting_since": "<time the sprint last moved>"}

`SENTENCE` says what the page offers and is used only when held cards are all that is counted;
`MIXED_SENTENCE` replaces the tracker sentence beside a held card, which has no tracker link.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

AFTER_MS = 3_600_000
HEADLINE = "{title} is holding work and has asked nobody for it"
SENTENCE = "Tell the manager what to do from its sprint, or drop the sprint."
MIXED_SENTENCE = "Tracker cards link to the tracker; a held sprint is answered from its sprint."


def since(now_ms: int | None, quiet_for: int | None, blocked: bool) -> int | None:
    """The milliseconds-since-epoch of a held sprint's latest movement, else None: the sprint is
    unblocked and has been quiet for `AFTER_MS` at `now_ms`."""
    if now_ms is None or blocked or quiet_for is None or quiet_for < AFTER_MS:
        return None
    return now_ms - quiet_for


def cards(projects: Sequence[Mapping], stops: str) -> list[dict]:
    """The held cards of the project entries' sprints, oldest movement first; `stops` are the
    characters trimmed from a title's end before the headline."""
    held = sorted(((project["project_id"], sprint) for project in projects
                   for sprint in project["sprints"] if sprint["held_since"] is not None),
                  key=lambda pair: (datetime.fromisoformat(pair[1]["held_since"]), pair[1]["sprint_id"]))
    return [{"type": "inbox_item", "reason": "held_sprint", "key": f"held-sprint/{sprint['sprint_id']}",
             "project_id": project_id, "sprint_id": sprint["sprint_id"], "title": sprint["title"],
             "headline": HEADLINE.format(title=sprint["title"].rstrip(stops)),
             "last_status": sprint["status"], "answered": False,
             "waiting_since": sprint["held_since"]} for project_id, sprint in held]
