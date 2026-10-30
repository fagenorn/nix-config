"""The direct-owner observation vocabulary and its `expects` catalogue (issue 473).

This is the one home of the member and state sets of the tracker, forge and
worktree observations a direct-owner request carries. `workflow-state` imports
the tracker and forge sets and the delivery wire module the worktree sets, and
their validators check requests against them. For each requirement kind a
direct-owner `observe` reply can return, it also holds the constant `expects`
description of the answer that requirement asks for. `slot` is the request
member the answer is sent in. `members` maps each member of that answer to a
one-line meaning that lists any closed value set. `example` is one illustrative
issue-73 answer with exactly those members. `build` is null, or the command that
turns an `example`-shaped input into the slot's value.

Pure: no I/O, and nothing imported from the skill scripts. The contract
builder's input set and source kinds stay with the builder; the
`delivery_contract` entry restates them, and a test pins the two together.
"""

import copy
from typing import Any

TRACKER_OBSERVATION_FIELDS = frozenset({"issue", "state", "open_blockers", "decision_blockers"})
TRACKER_STATES = frozenset({"open", "closed"})
DECISION_BLOCKER_FIELDS = frozenset({"issue", "url"})
FORGE_OBSERVATION_FIELDS = frozenset({"state", "url", "merge_sha"})
FORGE_STATES = frozenset({"none", "open", "closed", "merged"})
WORKTREE_OBSERVATION_FIELDS = frozenset({"issue", "recorded", "candidate"})
WORKTREE_ENTRY_FIELDS = frozenset({"path", "state"})
RECORDED_WORKTREE_STATES = frozenset({"matching_issue_branch", "absent", "mismatch"})
CANDIDATE_WORKTREE_STATES = frozenset({"available", "absent"})

# A tuple literal, so that a test can read it without importing the package.
EXPECTS_MEMBERS = ("slot", "members", "example", "build")
CONTRACT_BUILD = ("workflow-state build-delivery --repo-root <ledger_repo_root> "
                  "--kind contract --input -")


def _listed(values: frozenset[str]) -> str:
    return ", ".join(sorted(values))


_ISSUE = "the issue number; it must equal the request's issue"
_EXAMPLE_WORKTREE = "/repo/.worktrees/worktree-issue-73-example"
_ONE_WORKTREE = ("one worktree object answers both worktree kinds: set the member a "
                 "requirement asks for and keep any member set earlier in this acquisition")
_WORKTREE_MEMBERS = {
    "issue": _ISSUE,
    "recorded": (f"null, or the recorded_worktree requirement's path as observed: an object "
                 f"with members {_listed(WORKTREE_ENTRY_FIELDS)}, the path absolute and the "
                 f"state one of {_listed(RECORDED_WORKTREE_STATES)}; {_ONE_WORKTREE}"),
    "candidate": (f"null, or one reserved issue-branch candidate: an object with members "
                  f"{_listed(WORKTREE_ENTRY_FIELDS)}, the path absolute and the state one of "
                  f"{_listed(CANDIDATE_WORKTREE_STATES)}; {_ONE_WORKTREE}"),
}

_CATALOGUE: dict[str, dict[str, Any]] = {
    "tracker": {
        "slot": "tracker",
        "members": {
            "issue": _ISSUE,
            "state": f"the issue's tracker state, one of {_listed(TRACKER_STATES)}",
            "open_blockers": "the numbers of the open issues blocking it, each once",
            "decision_blockers": (f"the open blocking issues that await a decision, each "
                                  f"once: objects with members "
                                  f"{_listed(DECISION_BLOCKER_FIELDS)}"),
        },
        "example": {"issue": 73, "state": "open", "open_blockers": [],
                    "decision_blockers": []},
        "build": None,
    },
    "recorded_worktree": {
        "slot": "worktree",
        "members": _WORKTREE_MEMBERS,
        "example": {"issue": 73, "recorded": {"path": _EXAMPLE_WORKTREE,
                                              "state": "matching_issue_branch"},
                    "candidate": None},
        "build": None,
    },
    "candidate_worktree": {
        "slot": "worktree",
        "members": _WORKTREE_MEMBERS,
        "example": {"issue": 73, "recorded": None,
                    "candidate": {"path": _EXAMPLE_WORKTREE, "state": "absent"}},
        "build": None,
    },
    "forge_pr": {
        "slot": "forge",
        "members": {
            "state": (f"the pull request of the issue branch the requirement's path "
                      f"prefix names, one of {_listed(FORGE_STATES)}; none when there is "
                      f"no pull request"),
            "url": "the pull request URL; null when the state is none, required when merged",
            "merge_sha": "the 40-character lowercase hex merge commit when merged, else null",
        },
        "example": {"state": "none", "url": None, "merge_sha": None},
        "build": None,
    },
    "delivery_contract": {
        "slot": "delivery_contract",
        "members": {
            "issue": "the issue number",
            "worktree": ("the absolute, normalized worktree path: the recorded worktree when "
                         "a recorded_worktree requirement named one, else the reserved "
                         "candidate"),
            "source_kind": ("the source of the initial authorization intent, one of "
                            "explicit_user, standing_repository"),
            "source_reference": "a non-empty reference to that source",
        },
        "example": {"issue": 73, "worktree": _EXAMPLE_WORKTREE,
                    "source_kind": "explicit_user",
                    "source_reference": "invocation:/from-issue 73 --auto"},
        "build": CONTRACT_BUILD,
    },
}
OBSERVE_KINDS = frozenset(_CATALOGUE)


def describe(requirement: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of one direct observe requirement with its kind's `expects` attached.

    Raises ValueError when `requirement` is not an object, names a kind outside
    OBSERVE_KINDS, or already carries `expects`.
    """
    kind = requirement.get("kind") if isinstance(requirement, dict) else None
    if not isinstance(kind, str) or kind not in _CATALOGUE:
        raise ValueError(f"observe requirement kind {kind!r} has no expects description")
    if "expects" in requirement:
        raise ValueError(f"observe requirement {kind!r} already carries expects")
    return {**copy.deepcopy(requirement), "expects": copy.deepcopy(_CATALOGUE[kind])}
