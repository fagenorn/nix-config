"""The Task record and the states a task can be in."""

from dataclasses import dataclass

OPEN = "open"
DONE = "done"
STATES = (OPEN, DONE)


@dataclass
class Task:
    """One entry in the backlog. `id` is assigned by the store, never by the caller."""

    id: int
    title: str
    state: str = OPEN

    def __post_init__(self):
        if self.state not in STATES:
            raise ValueError("unknown state: %s" % self.state)

    @classmethod
    def from_dict(cls, raw):
        return cls(
            id=int(raw["id"]),
            title=str(raw["title"]),
            state=str(raw.get("state", OPEN)),
        )

    def to_dict(self):
        return {"id": self.id, "title": self.title, "state": self.state}
