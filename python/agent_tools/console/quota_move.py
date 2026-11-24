"""Which profile a quota move may take a manager to.

A manager whose account is out of quota is moved to another profile, never to the one it runs
under. The target must be another account with room: it reads `ok` or `reset`, is not signed out
or excluded (`manager.has_room`), is not a duplicate of any profile, does not share a sign-in
account with the manager, is not a colleague's account kept for another login's waiting sprint,
and does not share a counted reading's account id with the manager. These are pure functions of
the capacity view and the readings the caller passes; this module imports neither `service` nor
`view`.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from agent_tools.console import capacity, manager, sprints

UNMATCHED_REASON = ("the session registry lists the manager under the sprint's name, "
                    "but no session the console holds carries that name")
NO_ROOM_TEXT = f"{sprints.NOW_QUOTA_TEXT}: no other account has room"
UNMATCHED_TEXT = (f"{sprints.NOW_QUOTA_TEXT}: its move did not start because the console "
                  "could not match its session")
CALLED_OFF_TEXT = f"{sprints.NOW_QUOTA_TEXT}: its move to an account with room was called off"
NO_ROOM_REFUSAL = "no other account has room"


@dataclass(frozen=True)
class Note:
    """The sprint line's sentence for a manager out of quota that is not moving, and whether it offers the move."""

    text: str
    offer: bool


def note(target: str | None, cancelled: bool, unmatched: bool) -> Note | None:
    """Why a manager out of quota is not moved: no target has room, its session is unmatched or its move was called off."""
    if target is None:
        return Note(NO_ROOM_TEXT, False)
    if unmatched:
        return Note(UNMATCHED_TEXT, True)
    return Note(CALLED_OFF_TEXT, True) if cancelled else None


def move_account(view: Mapping, readings: capacity.CapacityState, signins: Mapping,
                 profile: str) -> tuple[str | None, str | None]:
    """The identity of `profile`'s account, its sign-in account and its counted reading's account id."""
    entry = {e["profile"]: e for e in view["profiles"]}.get(profile)
    own = capacity.counted_reading(readings, profile, signins.get(profile))
    return (entry["account"] if entry is not None else None,
            own.account if own is not None else None)


def account_ids(readings: capacity.CapacityState, signins: Mapping,
                by_name: Mapping[str, Mapping], profile: str) -> set[str]:
    """The account ids the counted readings of `profile` and its sign-in aliases carry."""
    entry = by_name.get(profile)
    names = [profile, *(entry["same_account_as"] if entry is not None else ())]
    held = (capacity.counted_reading(readings, name, signins.get(name)) for name in names)
    return {reading.account for reading in held
            if reading is not None and reading.account is not None}


def room_for_move(view: Mapping, readings: capacity.CapacityState, signins: Mapping,
                  waiting_logins: frozenset[str], sprint: sprints.SprintState,
                  choice: object) -> bool:
    """Whether `choice` is another account with room.

    The reading behind the entry may be an alias's (profiles on one sign-in share the newest),
    so the account ids of the readings of `choice` and its aliases are compared with the
    manager's. A duplicate of any profile is not a move, and a colleague's account kept for a
    waiting sprint of another login is not either (the rule `manager.choose_profile` applies).
    """
    mine = sprint.manager.profile if sprint.manager else None
    if not isinstance(choice, str) or choice == mine:
        return False
    by_name = {entry["profile"]: entry for entry in view["profiles"]}
    chosen = by_name.get(choice)
    if chosen is None or not manager.has_room(chosen) or chosen.get("duplicate_of") is not None:
        return False
    if mine in chosen["same_account_as"]:
        return False
    starter = sprint.started_by
    owners = {owner for name in (choice, *chosen["same_account_as"])
              if (owner := (by_name.get(name) or {}).get("owner")) is not None}
    if any(login in waiting_logins and login != starter for login in owners):
        return False
    if mine is None:
        return True
    return not (account_ids(readings, signins, by_name, mine)
                & account_ids(readings, signins, by_name, choice))
