# Task 4: Direct-owner request interface 3 and its gate

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (request constant and fields, `validate_direct_owner_request`, `load_direct_owner_request`, `_apply_one_issue_policy`'s `parked` branch, `command_direct_owner`, the `direct-owner` help)
- Modify: `python/agent_tools/attempt_observations.py` (docstring, `VERIFICATION_BUILD`, the `verification` entry)
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py` (`_OBSERVE_SLOTS`, `_observe_requirements`)
- Modify: `home/common/agent-skills/skills/from-issue/acquire-direct.md`, `home/common/agent-skills/README.md`, `justfile`
- Create: `home/common/agent-skills/tests/test_verification_direct.py`
- Modify (tests): `home/common/agent-skills/tests/test_workflow_state.py`, `test_verification_suspension.py`, `test_delivery_workflow.py`, `test_workflow_skill_contracts.py` (all under `home/common/agent-skills/tests/`)

**Interfaces:**
- Consumes: Task 1's `requirement`; Task 2's `load_json_request(..., strict=True)`, `verification_observations`, `resolve_verification`, the policy's `verification_blockers` keyword and its `blocker` local, `_requirements(..., verification=True)`, the harness's `observed`, `NEXT`, `failure`.
- Produces: `DIRECT_OWNER_REQUEST_INTERFACE_VERSION = 3` (replies keep `DIRECT_OWNER_INTERFACE_VERSION = 2`); `_apply_one_issue_policy(..., verification_equal: frozenset[str] = frozenset())`; `attempt_observations.VERIFICATION_BUILD`; `LifecycleHarness.direct_request(..., verification=())`.

**Invariants:**
- A direct-owner request is interface 3 with exactly the interface-2 members plus `verification`; interface 2 exits 2 before any lock; every reply stays interface 2 (D3, D7).
- The request file loads strictly (D8).
- The observations resolve against a deep copy of the selected run's map (an empty map for `new_run` or no run) after the applicability checks and before the terminal replay and any mint. A refusal writes no resolution, attempt, launch, index entry or run; the only bytes it can leave are those every call commits before resolving, the issue lock file and a legacy ledger's idempotent bind (D7, D17, D19).
- Gate, for a latest attempt parked on `verification`, after forge reconciliation, the tracker halt and the `forge_pr` requirement: `open` and not observed equal → `observe` with `[requirement(record)]`; observed equal → the `suspended` envelope; `resolved` → the ordinary resume lane. Only the `resume` write commits the copy (D7).
- `new_run` on a verification-parked latest attempt is refused naming the blocker id; other suspended causes keep their line (D7).
- acquire-direct grows only the digit and `"verification": [],`; the instruction budget check passes (D11, D18).

- [ ] **Step 1: Write the failing tests**

`home/common/agent-skills/tests/test_workflow_state.py`:
- Import `verification_blocker` beside `attempt_identity, attempt_observations, attempt_store`.
- `BARE_REQUIREMENTS` gains `"verification": {"kind": "verification", "blocker_id": "sha256:" + "0" * 64, "sources": [{"name": "flake-lock", "paths": ["flake.lock"]}]}`; `OBSERVE_SLOTS` gains `"verification": "verification"`.
- `empty_direct_request` is interface 3 and ends with `"verification": []`; its docstring says `interface-3`. `LifecycleHarness.direct_request` gains the keyword `verification=()` after `forge=UNOBSERVED`, is interface 3, and ends with `"verification": list(verification),`.
- `ObservationCatalogueTest.test_every_kind_carries_a_closed_constant_description`: the `build` assertion becomes `self.assertEqual(expects["build"], {"delivery_contract": attempt_observations.CONTRACT_BUILD, "verification": attempt_observations.VERIFICATION_BUILD}.get(kind))` (the lookup stays inside the loop).
- `test_each_observed_example_is_a_request_the_helper_accepts`: `request[expects["slot"]] = ([expects["example"]] if kind == "verification" else expects["example"])`, under the comment `# The verification slot is a list: the caller appends each observation to it.`
- `test_meanings_list_each_closed_value_set`: `listed` gains `("verification", "kind"): {verification_blocker.OBSERVATION_KIND}` and `("verification", "facts"): frozenset(verification_blocker.ENTRY_MODES)`.
- New test before `test_the_contract_description_restates_the_builder_input`:

```python
    def test_the_verification_description_reads_the_blocker_vocabulary(self):
        """Issue 545 D10: one observation, its example valid, built by the adapter."""
        expects = self.expects("verification")
        self.assertEqual(set(expects["members"]),
                         {"kind", "schema_version", "blocker_id", "repository", "facts"})
        self.assertIs(verification_blocker.validate_observation(expects["example"]),
                      expects["example"])
        self.assertIn(str(verification_blocker.SCHEMA_VERSION),
                      expects["members"]["schema_version"])
        self.assertIn("null", expects["members"]["facts"])
        self.assertEqual(expects["build"], "verification-observe observe --repo-root "
                                           "<ledger_repo_root> --input -")
```

- `DirectObserveExpectsTest.scenarios` gains `"verification": parked`, defined after `resumed`:

```python
        def parked():
            self.acquire_direct(issue=75)
            failure = self.root / "failure-75.json"
            failure.write_text(json.dumps({
                "kind": "verification-failure", "schema_version": 1,
                "repository": {"project_id": "fagenorn/nix-config",
                               "integration_branch": "main"},
                "command": {"id": "nix-build", "argv": ["just", "build"], "cwd": ".",
                            "env": []},
                "failure_class": "dependency",
                "facts": [{"name": "flake-lock", "source": {"paths": ["flake.lock"]},
                           "value": {"objects": [{"path": "flake.lock", "mode": "100644",
                                                  "object": "a" * 40}]}}]}), "utf-8")
            self.run_cli("suspend", "--repo-root", self.root, "--run-id",
                         self.direct_run_id(75, 1), "--issue", 75, "--attempt", 1,
                         "--blocked-on", "verification", "--verification-input", failure,
                         "--now", "2026-08-20T10:05:00Z", "--action-id", "75:1:1")
            return self.direct_request(issue=75, now="2026-08-20T10:06:00Z")
```

`test_verification_suspension.py`:
- `HelperGenerationTest.assert_refused_unchanged`: build the direct request into a variable and, for `generation == "base"`, set its `interface_version` to 2 and delete `verification` before writing it (the comment on the control request already covers both).
- `ParkedTest.test_direct_owner_replies_suspended_until_a_merge_reconciles` (D14): replace `self.assertEqual(direct(7), self.suspended_reply(73))` with

```python
        asked = direct(7)
        self.assertEqual((asked["kind"], [item["kind"] for item in asked["requirements"]]),
                         ("observe", ["verification"]))
        self.assertEqual(direct(7, verification=[observed(failure())]),
                         self.suspended_reply(73))
```

`test_delivery_workflow.py`: the three direct-owner requests (`DeliveryAdmissionTest.direct_request`, `BuilderHarness.direct_request` and the inline request of `HelperInputTest.test_every_input_flag_reads_stdin_and_refuses_relative_paths`) are interface 3 and end with `"verification": []`; `test_interface_two_maps_and_singular_inputs_are_closed` expects direct version 3.

`test_workflow_skill_contracts.py` (agent-helpers rule 6): rename `V2_DIRECT_REQUEST_KEYS` to `V3_DIRECT_REQUEST_KEYS` and add `"verification"`; rename `test_direct_and_control_requests_are_interface_two` to `test_direct_and_control_requests_carry_their_interfaces`, asserting `(set(request), request["interface_version"], request["verification"]) == (V3_DIRECT_REQUEST_KEYS, 3, [])`.

Create `home/common/agent-skills/tests/test_verification_direct.py`:

```python
"""Verification blockers resolved by `workflow-state direct-owner` (issue 545), through the
CLI from source.

Run: just agent-workflow-tests
"""

import json
import unittest

from agent_tools import attempt_observations
from agent_tools import verification_blocker as vb

from .test_verification_suspension import (DIRECT_NOW, NEXT, VerificationHarness, failure,
                                           observed)

X = failure()
X_ID = vb.blocker_id(X)
REQUIREMENT = {"kind": "verification", "blocker_id": X_ID,
               "sources": [{"name": "flake-lock", "paths": ["flake.lock"]}]}


class DirectHarness(VerificationHarness):
    def setUp(self):
        super().setUp()
        self.acquire_direct(issue=73)
        self.run_id = self.direct_run_id(73, 1)
        self.park(73, X, now=DIRECT_NOW(5))

    def request(self, minute, *observations, **fields):
        return self.direct_request(issue=73, now=DIRECT_NOW(minute),
                                   verification=list(observations), **fields)

    def direct(self, minute, *observations, **fields):
        done = self.direct_owner_at_root(self.root, self.request(minute, *observations,
                                                                 **fields))
        return self.validated_response(done.stdout)

    def refused(self, raw):
        path = self.root / "refused-direct-request.json"
        path.write_bytes(raw)
        return self.run_cli("direct-owner", "--repo-root", self.root, "--request-file",
                            path, ok=False)

    def recorded_worktree(self):
        return self.worktree_fact(73, recorded={"path": self.attempt(73)["worktree"],
                                                "state": "matching_issue_branch"})


class GateTest(DirectHarness, unittest.TestCase):
    def test_ask_then_equal_then_a_change_resumes_and_commits_only_then(self):
        before = self.tree_snapshot()
        asked = self.direct(6)
        self.assertEqual((asked["kind"], asked["run_id"], asked["requirements"]),
                         ("observe", self.run_id,
                          [attempt_observations.describe(REQUIREMENT)]))
        self.assertEqual(self.tree_snapshot(), before)
        self.assertEqual(self.direct(7, observed(X)), self.suspended_reply(73))
        self.assertEqual(self.tree_snapshot(), before)
        unrecorded = self.direct(8, observed(X, NEXT))
        self.assertEqual((unrecorded["kind"],
                          [item["kind"] for item in unrecorded["requirements"]]),
                         ("observe", ["recorded_worktree"]))
        self.assertEqual(self.tree_snapshot(), before)
        owner = self.direct(9, observed(X, NEXT), worktree=self.recorded_worktree())
        self.assertEqual((owner["kind"], owner["launch_kind"], owner["action_id"]),
                         ("owner", "resume", "73:1:2"))
        record = self.read_state()["verification_blockers"][X_ID]
        self.assertEqual((record["state"], record["resolution"], record["attempts"]),
                         ("resolved", {"facts": observed(X, NEXT)["facts"]},
                          [{"issue": 73, "attempt": 1}]))
        attempt = self.attempt(73)
        self.assertEqual((attempt["state"], attempt["blocked_on"],
                          attempt["verification_blocker"], len(attempt["launches"])),
                         ("active", None, None, 2))

    def test_a_tracker_halt_still_comes_first(self):
        before = self.tree_snapshot()
        closed = self.direct(6, observed(X, NEXT),
                             tracker=self.tracker_fact(73, state="closed"))
        self.assertEqual((closed["kind"], closed["source"]), ("terminal", "tracker"))
        self.assertEqual(self.tree_snapshot(), before)

    def test_new_run_names_the_blocker_it_waits_on(self):
        before = self.tree_snapshot()
        done = self.direct_owner_raw(request=self.request(6, new_run=True), ok=False)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (
            2, "", "workflow-state: new_run is not applicable: suspended attempt resumes "
                   f"in place once verification blocker {X_ID} resolves\n"))
        self.assertEqual(self.tree_snapshot(), before)


class RefusalTest(DirectHarness, unittest.TestCase):
    def test_an_observation_that_answers_no_open_blocker_exactly_is_refused(self):
        before = self.tree_snapshot()
        other = observed(X)
        other["repository"]["project_id"] = "fagenorn/other"
        unknown = "verification[0].blocker_id: names no open blocker of this run"
        cases = {
            "other repository": (self.request(6, other), "invalid verification observation: "
                                 "verification[0].repository: must equal the blocker's "
                                 "repository"),
            "repeated id": (self.request(6, observed(X), observed(X, NEXT)),
                            "invalid verification observation: verification[1].blocker_id: "
                            "repeats an earlier observation"),
            "unknown id": (self.request(6, observed(failure("environment"))),
                           f"invalid verification observation: {unknown}"),
            "interface 2": ({**self.request(6), "interface_version": 2},
                            "unsupported direct owner interface version"),
        }
        for label, (request, line) in cases.items():
            with self.subTest(case=label):
                done = self.refused(json.dumps(request).encode())
                self.assertEqual((done.returncode, done.stdout, done.stderr),
                                 (2, "", f"workflow-state: {line}\n"))
                self.assertEqual(self.tree_snapshot(), before)
        text = json.dumps(self.request(6))
        done = self.refused((text[:-1] + ', "verification": []}').encode())
        self.assertEqual((done.returncode, done.stdout, done.stderr), (
            2, "", "workflow-state: invalid direct owner request JSON: duplicate JSON key "
                   "'verification'\n"))
        self.assertEqual(self.tree_snapshot(), before)

    def test_an_observation_for_a_run_the_call_would_start_mints_nothing(self):
        before = self.tree_snapshot()
        done = self.refused(json.dumps(self.direct_request(
            issue=74, now=DIRECT_NOW(6), verification=[observed(X)])).encode())
        self.assertEqual((done.returncode, done.stdout, done.stderr), (
            2, "", "workflow-state: invalid verification observation: "
                   "verification[0].blocker_id: names no open blocker of this run\n"))
        # Only the issue lock the call held exists now; no run, index entry or ledger.
        self.assertEqual(self.tree_snapshot(), {**before, "workflows/.direct-74.lock": b""})

    def test_a_resolved_record_is_no_longer_answerable(self):
        self.direct(6, observed(X, NEXT), worktree=self.recorded_worktree())
        before = self.tree_snapshot()
        done = self.refused(json.dumps(self.request(7, observed(X, NEXT))).encode())
        self.assertEqual((done.returncode, done.stdout, done.stderr), (
            2, "", "workflow-state: invalid verification observation: "
                   "verification[0].blocker_id: names no open blocker of this run\n"))
        self.assertEqual(self.tree_snapshot(), before)


class ObserveWireTest(DirectHarness, unittest.TestCase):
    """Issue 545 D9, by behaviour: the observe slot and its build."""

    def test_the_observe_reply_requires_the_slot_and_the_build(self):
        reply = self.direct(6)
        model = self.delivery_model

        def validate(value):
            return model.validate_delivery_object(
                value, expected_kind="workflow-response", notes_max_characters=4096)

        self.assertEqual(validate(json.loads(json.dumps(reply))), reply)
        for member, value in (("build", None), ("slot", "worktree")):
            changed = json.loads(json.dumps(reply))
            changed["requirements"][0]["expects"][member] = value
            with self.subTest(member=member), self.assertRaises(model.DeliveryModelError):
                validate(changed)
        changed = json.loads(json.dumps(reply))
        del changed["requirements"][0]["sources"]
        with self.assertRaises(model.DeliveryModelError):
            validate(changed)


class LegacyBindTest(VerificationHarness, unittest.TestCase):
    """Issue 545 D19: a refused observation keeps only the bind every call commits first."""

    def test_a_refused_observation_leaves_a_legacy_ledger_bound_and_nothing_else(self):
        self.acquire_direct(issue=73)
        self.run_id = self.direct_run_id(73, 1)
        current = self.read_state()
        self.write_state(self._as_legacy(current, 10))
        self.assertEqual(self.read_state()["schema_version"], 10)
        path = self.root / "legacy-direct-request.json"
        path.write_text(json.dumps(self.direct_request(
            issue=73, now=DIRECT_NOW(6), verification=[observed(X)])), "utf-8")
        trees = []
        for call in (1, 2):
            with self.subTest(call=call):
                done = self.run_cli("direct-owner", "--repo-root", self.root,
                                    "--request-file", path, ok=False)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (
                    2, "", "workflow-state: invalid verification observation: "
                           "verification[0].blocker_id: names no open blocker of this run\n"))
                # The schema-11 bind alone: no blocker, attempt, launch or run was written.
                self.assertEqual(self.read_state(), current)
                trees.append(self.tree_snapshot())
        self.assertEqual(trees[1], trees[0])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 900 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_verification_direct.py 2>&1 | tail -3; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k ObservationCatalogue -k DirectObserveExpects 2>&1 | tail -3'`
Expected: `Ran 8 tests`, `FAILED (failures=8)`, each `command failed with 2: workflow-state: invalid direct owner request fields` (the interface-2 helper refuses the new member in `acquire_direct`); then `Ran 9 tests`, `FAILED (failures=2, errors=6)` (the catalogue has no `verification` entry, and the helper refuses the member).

- [ ] **Step 3: Implement the request, the gate and the catalogue**

`workflow-state.py`:
- After `DIRECT_OWNER_INTERFACE_VERSION = 2` add `DIRECT_OWNER_REQUEST_INTERFACE_VERSION = 3` under the comment `# A direct-owner request moves to interface 3 with `verification`; every reply stays at DIRECT_OWNER_INTERFACE_VERSION (issue 545 D3).` `DIRECT_OWNER_REQUEST_FIELDS` gains `"verification"`. `validate_direct_owner_request` checks the request constant and then calls `verification_observations(request["verification"])`. `load_direct_owner_request` passes `strict=True`.
- `_apply_one_issue_policy` gains `verification_equal: frozenset[str] = frozenset()` after `verification_blockers`. Its docstring's `returns ``parked``, which changes nothing (issue 544 D6, D7).` becomes `returns ``parked``, which changes nothing, when ``verification_equal`` holds the blocker's id (this call observed it unchanged), else ``observe`` with the blocker's requirement (issue 544 D7, issue 545 D7).` In the `if parked:` branch, after the `forge_pr` return: `if blocker["id"] in verification_equal: return decision("parked", expired=False)`, then `return decision("observe", requirements=[verification_blocker.requirement(blocker)], expired=False)`.
- `command_direct_owner`: in the `new_run` refusal for a suspended latest attempt, when its `verification_blocker` is not `None` raise `WorkflowError("new_run is not applicable: suspended attempt resumes in place " f"once verification blocker {parked_on} resolves")`, else the existing line; extend the comment with `A verification-parked one names the blocker it waits on (issue 545 D7).` Right after the `owner_unavailable is not applicable` check, under the comment `# The observations resolve against a copy of the selected run's blockers (a new run's map is empty), before any mint, so a refused one mints nothing and records no resolution; only the write that resumes commits the copy (issue 545 D7, D19).`:

```python
            blockers = copy.deepcopy(
                {} if selected is None or request["new_run"]
                else selected[4]["verification_blockers"])
            _, observed_equal = resolve_verification(blockers, request["verification"])
```

  The policy call passes `verification_blockers=blockers, verification_equal=observed_equal` (replacing Task 2's keyword). In the `spawn`/`resume`/`retry`/`refuse`/`recover` branch, right after its `if state is None: … else: state["issues"][str(issue)] = policy["issue_state"]` block and before `complete_direct_policy`, add `if operation == "resume": state["verification_blockers"] = blockers`; no other branch writes `blockers`.
- The `direct-owner` parser description becomes `Acquire, resume or replay one issue's direct owner from one interface-3 request read from --request-file, and print one observe, owner, delivery_remainder, suspended or terminal reply. Each requirement of an observe reply carries expects: slot names the request member its answer fills, members maps each member of that answer to its meaning, example is one illustrative answer, and build is null or the command that builds the answer.`

`attempt_observations.py` (D10): import `from agent_tools import verification_blocker`; the docstring's last `build` sentence becomes `` `build` is null, or the command that produces the slot's value from an `example`-shaped input (`delivery_contract`) or from the requirement less `expects` (`verification`, issue 545 D10).`` and the closing paragraph adds `The `verification` entry reads its closed values from `agent_tools.verification_blocker`.` Add `VERIFICATION_BUILD = "verification-observe observe --repo-root <ledger_repo_root> --input -"` after `CONTRACT_BUILD`, and the catalogue entry:

```python
_EXAMPLE_FACTS = [{"name": "flake-lock", "source": {"paths": ["flake.lock"]},
                   "value": {"objects": [{"path": "flake.lock", "mode": "100644",
                                          "object": "a" * 40}]}}]
```
```python
    "verification": {
        "slot": "verification",
        "members": {
            "kind": (f"the literal {verification_blocker.OBSERVATION_KIND}; the whole "
                     f"observation is one element of the request's verification list"),
            "schema_version": f"the integer {verification_blocker.SCHEMA_VERSION}",
            "blocker_id": "the requirement's blocker_id",
            "repository": ("the observed repository: an object with members "
                           "integration_branch, project_id"),
            "facts": ("one object per requirement source, in its order: name and source "
                      "{paths} as the requirement lists them, and value {objects}, one "
                      "{path, mode, object} per path, mode one of "
                      f"{', '.join(verification_blocker.ENTRY_MODES)}, and mode and object "
                      "null for an absent path"),
        },
        "example": {"kind": verification_blocker.OBSERVATION_KIND,
                    "schema_version": verification_blocker.SCHEMA_VERSION,
                    "blocker_id": "sha256:" + "0" * 64,
                    "repository": {"project_id": "fagenorn/nix-config",
                                   "integration_branch": "main"},
                    "facts": _EXAMPLE_FACTS},
        "build": VERIFICATION_BUILD,
    },
```

`delivery_model/_wire.py` (D9): `_OBSERVE_SLOTS` gains `"verification": "verification"`; `_observe_requirements`' docstring says `the six direct kinds` and cites `issue 473 D4, issue 545 D9`; its bare check calls `_requirements([bare], sorted_values=False, verification=True)`; `build` must be a string for `delivery_contract` and `verification`, `null` for the rest.

`acquire-direct.md` (D11): `interface_version 2 shape` becomes `interface_version 3 shape`; the block's `"interface_version": 2,` becomes `3`, and `"verification": [],` is a new line between `"requested_scope": null,` and `"recovery": null`. Nothing else.

`home/common/agent-skills/README.md`:
- `### Direct-owner observations`: after the `delivery_contract` `build` sentence add `` For `verification` it is `verification-observe observe --repo-root <ledger_repo_root> --input -`, which reads the requirement less `expects` and prints the observation, one element of the request's `verification` list (issue 545).``; `the five direct kinds` becomes `the six direct kinds`.
- `### Verification blockers`, first paragraph: delete the sentence `` `direct-owner`, after the tracker halt and the `forge_pr` observation it asks for, replies with the same `suspended` envelope and writes nothing.``. Second paragraph: replace ` Known limitation: … that is issue 546.` with:

```text
 The `direct-owner` request moves to interface 3 with the same `verification` member and checks (its replies stay interface 2, and its request file is strict JSON too), except that a refusal keeps what every call commits first: the issue lock file and a legacy ledger's bind. The observations resolve against a copy of the selected run's records before any run is minted, and for an attempt parked on `verification`, after the tracker halt and the `forge_pr` observation, the helper answers: `observe` with the record's requirement while the record is `open` and unobserved; the `suspended` envelope, writing nothing, when it was observed equal; and the ordinary resume lane once this call's observation resolved it, the resolution committed only in the write that resumes, so a call that ends in another `observe` writes nothing and the resent observation still names an `open` record. `new_run` stays refused for a suspended attempt, naming the record for a parked one: `new_run is not applicable: suspended attempt resumes in place once verification blocker <id> resolves`. Known limitation: no caller gathers observations yet: `orchestrate-control` sends `verification: []`, and acquire-direct fails loudly on a `verification` requirement and on a `suspended` reply; that is issue 546.
```

`justfile`: list `home/common/agent-skills/tests/test_verification_direct.py \` right after `test_verification_control.py`.

- [ ] **Step 4: Verify**

Run (timeout 3000 s): `PYTHONPATH="$PWD/python" python3 -m agent_tools.suite_runner --jobs 6 home/common/agent-skills/tests/test_verification_direct.py home/common/agent-skills/tests/test_verification_control.py home/common/agent-skills/tests/test_verification_suspension.py tests/test_verification_blocker.py tests/test_attempt_custody.py home/common/agent-skills/tests/test_attempt_custody.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_control_cutover.py home/common/agent-skills/tests/test_attempt_migration.py home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -2`
Expected: `suite-runner: summary members=13 passed=13 failed=0`.
Run: `PYTHONPATH="$PWD/python" python3 -m agent_tools.instruction_load check --base e692c9685c3e4b08f55c327c5f2b8c699fc95bc4; grep -c '"verification": \[\],' home/common/agent-skills/skills/from-issue/acquire-direct.md`
Expected: `check: pass`, then `1`.
Run (timeout 3600 s): `just build`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py python/agent_tools/attempt_observations.py home/common/agent-skills/scripts/delivery_model/_wire.py home/common/agent-skills/skills/from-issue/acquire-direct.md home/common/agent-skills/README.md justfile home/common/agent-skills/tests/test_verification_direct.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_verification_suspension.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit … -- -m "feat(workflow-state): direct-owner request 3 resolves blockers" -m "Issue 545." -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":4,"records":[{"bounds":[{"added_lines":125,"boundary":"all","deleted_lines":36,"record_bytes":36864,"support":{"covers":["r2a","r4a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4a","last_task":4,"owner":4,"path":"home/common/agent-skills/scripts/workflow-state.py"},{"bounds":[{"added_lines":40,"boundary":"all","deleted_lines":5,"record_bytes":7680,"support":{"covers":["r4b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4b","last_task":4,"owner":4,"path":"python/agent_tools/attempt_observations.py"},{"bounds":[{"added_lines":44,"boundary":"all","deleted_lines":16,"record_bytes":17408,"support":{"covers":["r2d","r3b","r4c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4c","last_task":4,"owner":4,"path":"home/common/agent-skills/scripts/delivery_model/_wire.py"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":2,"record_bytes":3072,"support":{"covers":["r4d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4d","last_task":4,"owner":4,"path":"home/common/agent-skills/skills/from-issue/acquire-direct.md"},{"bounds":[{"added_lines":7,"boundary":"all","deleted_lines":5,"record_bytes":29184,"support":{"covers":["r2k","r3h","r4e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4e","last_task":4,"owner":4,"path":"home/common/agent-skills/README.md"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["r2l","r4f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4f","last_task":4,"owner":4,"path":"justfile"},{"bounds":[{"added_lines":230,"boundary":"all","deleted_lines":0,"record_bytes":12800,"support":{"covers":["r4g"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r4g","last_task":4,"owner":4,"path":"home/common/agent-skills/tests/test_verification_direct.py"},{"bounds":[{"added_lines":72,"boundary":"all","deleted_lines":22,"record_bytes":23040,"support":{"covers":["r2o","r3d","r4h"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4h","last_task":4,"owner":4,"path":"home/common/agent-skills/tests/test_workflow_state.py"},{"bounds":[{"added_lines":44,"boundary":"all","deleted_lines":14,"record_bytes":10240,"support":{"covers":["r2n","r4i"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4i","last_task":4,"owner":4,"path":"home/common/agent-skills/tests/test_verification_suspension.py"},{"bounds":[{"added_lines":21,"boundary":"all","deleted_lines":20,"record_bytes":18432,"support":{"covers":["r2p","r3e","r4j"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4j","last_task":4,"owner":4,"path":"home/common/agent-skills/tests/test_delivery_workflow.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":6,"record_bytes":4608,"support":{"covers":["r4k"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r4k","last_task":4,"owner":4,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"}]}}
```
