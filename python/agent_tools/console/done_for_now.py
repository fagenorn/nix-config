"""The desk's done-for-now heading: its words, the working count and the next expected time.

With a project registered and nothing open (no item, no all-out or stale statement), the
statement's headline is `HEADLINE` ("You're done for now") and its sentence is `sentence(working)`:
`SENTENCE` naming how many sprints are working ("No sprint is working", "1 sprint is working" or
"<n> sprints are working"). `working(projects)` counts the sprints whose `stoppable` is true over
every project entry's `sprints`, the quiet projects' included, so a finished sprint never counts.

`next_expected(projects, headline)` is the `now_until` with the earliest time among the sprints
whose `now_text` is `NOW_WAIT_TEXT` (a wait the sprint's report stated), copied as given; the
engine's `later_until` is never read. The times are compared as parsed at full precision (the
report states microseconds), never truncated to the millisecond. It is None whenever `headline` is
not `HEADLINE` and when no sprint states a wait. It is a member of the view, not of the statement.
"""
from collections.abc import Iterable, Mapping
from datetime import datetime

from agent_tools.console.sprints import NOW_WAIT_TEXT

HEADLINE = "You're done for now"
SENTENCE = "{working}; we'll put anything that needs you here."
NONE_TEXT = "No sprint is working"
ONE_TEXT = "1 sprint is working"
MANY_TEXT = "{n} sprints are working"


def _sprints(projects: Iterable[Mapping]) -> list[Mapping]:
    return [sprint for project in projects for sprint in project["sprints"]]


def working(projects: Iterable[Mapping]) -> int:
    return sum(1 for sprint in _sprints(projects) if sprint["stoppable"] is True)


def sentence(working: int) -> str:
    text = NONE_TEXT if working == 0 else ONE_TEXT if working == 1 else MANY_TEXT.format(n=working)
    return SENTENCE.format(working=text)


def next_expected(projects: Iterable[Mapping], headline: str) -> str | None:
    if headline != HEADLINE:
        return None
    return min(
        (sprint["now_until"] for sprint in _sprints(projects)
         if sprint["now_text"] == NOW_WAIT_TEXT and isinstance(sprint["now_until"], str)),
        key=datetime.fromisoformat, default=None)
