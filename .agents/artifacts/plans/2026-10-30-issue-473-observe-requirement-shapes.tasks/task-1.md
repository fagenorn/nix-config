# Task 1: Observation vocabulary and `expects` catalogue

Spec § Decisions (The `expects` member; Vocabulary home); per D2, D3 and D10. Create the package module that holds the observation sets and the `expects` catalogue. Then make `workflow-state.py` and the delivery wire module import the sets they now define themselves. No helper output changes in this task: nothing attaches `expects` yet (Task 2 does).

**Files:**
- Create: `python/agent_tools/attempt_observations.py`
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (the constant block at about lines 217–223 and the `agent_tools` imports at about lines 22–39)
- Modify: `home/common/agent-skills/scripts/workflow_delivery_wire.py` (`DeliveryProjection._worktree`, about lines 120–137)
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (new module helpers and class `ObservationCatalogueTest`)

**Interfaces:**
- Consumes: nothing from earlier tasks. `load_source_module(path, name)`, `SCRIPT` (path of `workflow-state.py`) and the existing `from agent_tools import attempt_identity, attempt_store` line in `test_workflow_state.py`. `workflow-state.py`'s `validate_direct_owner_request(value) -> (request, context)` and `WorkflowError`. `workflow_delivery_build.py`'s module-level `_CONTRACT_INPUT` (a set) and `_SOURCE_KINDS` (a frozenset).
- Produces, all in `agent_tools.attempt_observations`:
  - `TRACKER_OBSERVATION_FIELDS`, `TRACKER_STATES`, `DECISION_BLOCKER_FIELDS`, `FORGE_OBSERVATION_FIELDS`, `FORGE_STATES`, `WORKTREE_OBSERVATION_FIELDS`, `WORKTREE_ENTRY_FIELDS`, `RECORDED_WORKTREE_STATES`, `CANDIDATE_WORKTREE_STATES`: `frozenset[str]`.
  - `EXPECTS_MEMBERS: tuple[str, ...]`, which is exactly `("slot", "members", "example", "build")` and written as a tuple literal so that `test_workflow_skill_contracts.py` can read it by AST (D11).
  - `CONTRACT_BUILD: str`.
  - `OBSERVE_KINDS: frozenset[str]`, the five kinds.
  - `describe(requirement: dict) -> dict`.
- Task 2 uses `describe` and `OBSERVE_KINDS`. Task 3 uses `EXPECTS_MEMBERS`. Task 5 reads `EXPECTS_MEMBERS` by AST.

**Invariants:**
- Every set has exactly the members it has at the base. The worktree sets are the literals `_worktree` writes today.
- `describe(r)` returns a new dict: a deep copy of `r` plus `"expects"`, a deep copy of the kind's constant entry. Mutating the result never changes a later result.
- `describe` raises `ValueError` when `r` is not a dict, its `kind` is not a string in `OBSERVE_KINDS`, or it already carries `expects`.
- Each entry has exactly the keys of `EXPECTS_MEMBERS`. `slot` follows the spec's table. `build` is `CONTRACT_BUILD` for `delivery_contract` and `None` otherwise. `members` is a non-empty map of non-empty ASCII strings. The key set of `example` equals the key set of `members`.
- `workflow-state.py` and `workflow_delivery_wire.py` bind the module's own set objects, so `is` holds. Their validation logic and refusal messages are unchanged.
- The module imports only `copy` and `typing`.

- [ ] **Step 1: Write the failing tests**

In `test_workflow_state.py`, change the import line to `from agent_tools import attempt_identity, attempt_observations, attempt_store`. Add these module-level definitions after `ORCHESTRATED`:

```python
BUILDER = Path(__file__).parents[1] / "scripts" / "workflow_delivery_build.py"
WIRE = Path(__file__).parents[1] / "scripts" / "workflow_delivery_wire.py"
# Each direct observe requirement kind in the bare shape the policy emits for issue 73.
BARE_REQUIREMENTS = {
    "tracker": {"kind": "tracker"},
    "recorded_worktree": {"kind": "recorded_worktree",
                          "path": "/repo/.worktrees/worktree-issue-73-example"},
    "candidate_worktree": {"kind": "candidate_worktree"},
    "forge_pr": {"kind": "forge_pr", "path": "issue-73-"},
    "delivery_contract": {"kind": "delivery_contract", "subject_id": "73",
                          "reason_code": "delivery_contract_required",
                          "detail_pointer": None},
}
OBSERVE_SLOTS = {"tracker": "tracker", "recorded_worktree": "worktree",
                 "candidate_worktree": "worktree", "forge_pr": "forge",
                 "delivery_contract": "delivery_contract"}


def empty_direct_request(issue=73):
    """acquire-direct.md's interface-2 request before any observation is sent."""
    return {"interface_version": 2, "issue": issue, "attempt_budget_minutes": 180,
            "new_run": False, "owner_unavailable": False, "tracker": None,
            "worktree": None, "forge": None, "delivery_contract": None,
            "authorization_intents": [], "authority_observations": [],
            "reevaluation_evidence": [], "delivery_observations": [],
            "requested_scope": None, "recovery": None}
```

Add this class at the end of the module, before any `if __name__ == "__main__":` block:

```python
class ObservationCatalogueTest(unittest.TestCase):
    """Issue 473 D2, D3, D10: the observation vocabulary's one home and its catalogue."""

    @classmethod
    def setUpClass(cls):
        cls.workflow = load_source_module(SCRIPT, "workflow_state_observation_catalogue")
        cls.builder = load_source_module(BUILDER, "workflow_state_observation_builder")
        cls.wire = load_source_module(WIRE, "workflow_state_observation_wire")

    @staticmethod
    def expects(kind):
        return attempt_observations.describe(BARE_REQUIREMENTS[kind])["expects"]

    def test_every_kind_carries_a_closed_constant_description(self):
        self.assertEqual(set(BARE_REQUIREMENTS), attempt_observations.OBSERVE_KINDS)
        self.assertEqual(attempt_observations.EXPECTS_MEMBERS,
                         ("slot", "members", "example", "build"))
        for kind, bare in BARE_REQUIREMENTS.items():
            with self.subTest(kind=kind):
                described = attempt_observations.describe(bare)
                self.assertEqual({k: v for k, v in described.items() if k != "expects"},
                                 bare)
                expects = described["expects"]
                self.assertEqual(set(expects), set(attempt_observations.EXPECTS_MEMBERS))
                self.assertEqual(expects["slot"], OBSERVE_SLOTS[kind])
                self.assertEqual(expects["build"],
                                 attempt_observations.CONTRACT_BUILD
                                 if kind == "delivery_contract" else None)
                self.assertTrue(expects["members"])
                for name, meaning in expects["members"].items():
                    self.assertTrue(name)
                    self.assertIsInstance(meaning, str)
                    self.assertTrue(meaning)
                    self.assertTrue(meaning.isascii())
                self.assertEqual(set(expects["example"]), set(expects["members"]))
                expects["members"].clear()
                expects["example"].clear()
                self.assertTrue(self.expects(kind)["members"])
                self.assertTrue(self.expects(kind)["example"])

    def test_each_observed_example_is_a_request_the_helper_accepts(self):
        for kind in sorted(attempt_observations.OBSERVE_KINDS - {"delivery_contract"}):
            expects = self.expects(kind)
            request = empty_direct_request()
            request[expects["slot"]] = expects["example"]
            with self.subTest(kind=kind):
                self.workflow.validate_direct_owner_request(request)
            if "issue" in expects["example"]:
                other = empty_direct_request(74)
                other[expects["slot"]] = expects["example"]
                with self.subTest(kind=kind, issue=74), \
                        self.assertRaises(self.workflow.WorkflowError):
                    self.workflow.validate_direct_owner_request(other)

    def test_the_contract_description_restates_the_builder_input(self):
        expects = self.expects("delivery_contract")
        self.assertEqual(set(expects["members"]), self.builder._CONTRACT_INPUT - {"now"})
        for source_kind in self.builder._SOURCE_KINDS:
            self.assertIn(source_kind, expects["members"]["source_kind"])
        self.assertIn(expects["example"]["source_kind"], self.builder._SOURCE_KINDS)
        self.assertEqual(expects["build"], "workflow-state build-delivery --repo-root "
                                           "<ledger_repo_root> --kind contract --input -")

    def test_meanings_list_each_closed_value_set(self):
        listed = {
            ("tracker", "state"): attempt_observations.TRACKER_STATES,
            ("tracker", "decision_blockers"): attempt_observations.DECISION_BLOCKER_FIELDS,
            ("forge_pr", "state"): attempt_observations.FORGE_STATES,
            ("recorded_worktree", "recorded"): attempt_observations.RECORDED_WORKTREE_STATES,
            ("candidate_worktree", "candidate"):
                attempt_observations.CANDIDATE_WORKTREE_STATES,
        }
        for (kind, member), values in listed.items():
            meaning = self.expects(kind)["members"][member]
            for value in sorted(values):
                with self.subTest(kind=kind, member=member, value=value):
                    self.assertRegex(meaning, rf"\b{re.escape(value)}\b")

    def test_the_helper_and_wire_module_check_the_shared_vocabulary(self):
        for module, names in (
                (self.workflow, ("TRACKER_OBSERVATION_FIELDS", "TRACKER_STATES",
                                 "DECISION_BLOCKER_FIELDS", "FORGE_OBSERVATION_FIELDS",
                                 "FORGE_STATES")),
                (self.wire, ("WORKTREE_OBSERVATION_FIELDS", "WORKTREE_ENTRY_FIELDS",
                             "RECORDED_WORKTREE_STATES", "CANDIDATE_WORKTREE_STATES"))):
            for name in names:
                with self.subTest(module=module.__name__, name=name):
                    self.assertIs(getattr(module, name), getattr(attempt_observations, name))

    def test_an_undescribed_requirement_is_refused(self):
        scope_tuple = {"kind": "scope_tuple", "subject_id": "select",
                       "reason_code": "scope_tuple_required", "detail_pointer": None}
        for value in (scope_tuple, {"kind": "observation"}, {"path": "issue-73-"},
                      {"kind": ["tracker"]}, "tracker", None,
                      attempt_observations.describe({"kind": "tracker"})):
            with self.subTest(value=value), self.assertRaises(ValueError):
                attempt_observations.describe(value)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (Unit run): `test_workflow_state.py -k ObservationCatalogueTest`
Expected: an import error, `cannot import name 'attempt_observations' from 'agent_tools'`.

- [ ] **Step 3: Write the module**

Create `python/agent_tools/attempt_observations.py` with exactly this content. The catalogue strings are the wire text agents read, so take them verbatim, except where a clause turns out false against the code. In that case rewrite the clause from the code, per the Global Constraints.

```python
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
```

- [ ] **Step 4: Import the sets where they are checked**

`workflow-state.py`: delete the five assignments `FORGE_OBSERVATION_FIELDS`, `FORGE_STATES`, `TRACKER_OBSERVATION_FIELDS` (all three lines), `TRACKER_STATES` and `DECISION_BLOCKER_FIELDS`. Then add this import beside the other `agent_tools` imports:

```python
from agent_tools.attempt_observations import (
    DECISION_BLOCKER_FIELDS, FORGE_OBSERVATION_FIELDS, FORGE_STATES,
    TRACKER_OBSERVATION_FIELDS, TRACKER_STATES)
```

`workflow_delivery_wire.py`: add the import below `from typing import Any` (precedent: `workflow_delivery.py` imports `agent_tools.attempt_custody`):

```python
from agent_tools.attempt_observations import (
    CANDIDATE_WORKTREE_STATES, RECORDED_WORKTREE_STATES, WORKTREE_ENTRY_FIELDS,
    WORKTREE_OBSERVATION_FIELDS)
```

In `DeliveryProjection._worktree`, write `set(value) != WORKTREE_OBSERVATION_FIELDS` and `set(item) != WORKTREE_ENTRY_FIELDS`, and make the loop's pairs `("recorded", RECORDED_WORKTREE_STATES)` and `("candidate", CANDIDATE_WORKTREE_STATES)`. Every message stays the same. Leave `remainder_worktree_requirements` as it is: its state literals are policy, not vocabulary.

- [ ] **Step 5: Verify**

1. Unit run: `test_workflow_state.py -k ObservationCatalogueTest`. Expected: `Ran 6 tests`, `OK`.
2. Unit run: `test_delivery_workflow.py -k test_interface_two_maps_and_singular_inputs_are_closed`, then `test_workflow_state.py -k test_control_rejects_bad_observations_without_rewriting_the_ledger -k direct`. Expected: `OK` (unchanged validation).
3. No copy is left behind (each gate exits 1 on a leftover):
   `bash -c 'if grep -nE "^(TRACKER|FORGE|DECISION)_[A-Z_]+ = " home/common/agent-skills/scripts/workflow-state.py; then exit 1; fi; if grep -nE "\"matching_issue_branch\", \"absent\", \"mismatch\"|\"available\", \"absent\"" home/common/agent-skills/scripts/workflow_delivery_wire.py; then exit 1; fi'`
4. `git add python/agent_tools/attempt_observations.py`, then Build. Expected: success. `lib/agent-tools.nix` discovers the module, and its `pythonImportsCheck` imports it.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/attempt_observations.py home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/scripts/workflow_delivery_wire.py home/common/agent-skills/tests/test_workflow_state.py
launch-commit ... -- -m "feat(agent-tools): home the direct-owner observation vocabulary and expects catalogue (issue 473)"
```
