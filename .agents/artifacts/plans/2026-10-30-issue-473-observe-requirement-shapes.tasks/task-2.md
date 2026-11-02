# Task 2: Observe replies carry `expects` and the validator checks it

Spec § Decisions (The `expects` member; Workflow-response validator); § Test seams (Every kind is described; The validator refuses bad shapes); per D1, D2, D4, D8, D9 and D11. One task, because the helper and the boundary must change together: the validator at the base rejects an observe requirement that carries `expects`, and the new one rejects one that lacks it.

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`direct_observe`, about line 3681; the `agent_tools` import line)
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py` (new `_OBSERVE_SLOTS` and `_observe_requirements`; the `kind == "observe"` branch of `_workflow_response`, about line 307)
- Modify: `home/common/agent-skills/tests/_delivery_model_fixtures.py` (the `"observe"` fixture, about line 340)
- Modify: `home/common/agent-skills/tests/test_delivery_workflow.py` (raw observe pins at about lines 230–232, 3139–3147, 3308–3309 and 3353–3354)
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (`LifecycleHarness._legacy_direct`; new class `DirectObserveExpectsTest`)
- Test: `home/common/agent-skills/tests/test_delivery_model.py` (new class `ObserveExpectsResponseTest`)

**Interfaces:**
- Consumes: Task 1's `attempt_observations.describe`, `OBSERVE_KINDS` and `EXPECTS_MEMBERS`, and its `BARE_REQUIREMENTS` in `test_workflow_state.py`. Also `LifecycleHarness.direct_request(*, issue, now, attempt_budget_minutes, new_run, owner_unavailable, tracker, worktree, forge)`, `tracker_fact(issue)`, `worktree_fact(issue, *, recorded, candidate)`, `acquire_direct(*, issue)` and `direct_owner_at_root(root, request) -> CompletedProcess` (raw `str` stdout, not projected), `validated_response(stdout) -> dict`, `load_source_module` and `SCRIPT`. In `test_delivery_model.py`: `load_model`, `SOURCE` and `workflow_responses`.
- Produces: `direct_observe(issue, run_id, requirements)` returns requirements that carry `expects`, and raises `WorkflowError` (exit 2, empty stdout through `main`) for a kind with no entry. `_observe_requirements(values) -> list` in the delivery model.

**Invariants:**
- The observe envelope keeps exactly `interface_version` (still 2, per D9), `kind`, `issue`, `run_id` and `requirements`. Each requirement keeps its bare members and gains only `expects`.
- `expects` is attached only in `direct_observe`, after the policy has compared bare requirements (D4). `_apply_one_issue_policy`, control summaries and delivery-block requirements stay bare.
- At `workflow-response`, an observe requirement is refused when it has no `expects`, its kind is outside the five direct kinds, its bare part repeats an earlier one or fails the shared member check, `expects` has other than its four members, `slot` is not its kind's, `build` is null for `delivery_contract` or non-null otherwise, `members` is empty or holds an empty name or a non-string or empty meaning, or `example` is not an object whose key set equals that of `members`.
- The validator does not compare `expects` with the catalogue. It keeps its own kind-to-slot table, which the AC1 scenarios pin to the catalogue (D4).
- A `delivery_checkpointed` reply whose requirement carries `expects` is still refused, because the shared check is unchanged.
- `_legacy_direct` deletes `expects` from each observe requirement, and a missing one raises `KeyError` (D11). Interface-1 pins therefore stay bare and still catch a helper that stops attaching it.

- [ ] **Step 1: Write the failing tests**

`test_workflow_state.py`: add this class after `ObservationCatalogueTest`:

```python
class DirectObserveExpectsTest(LifecycleHarness, unittest.TestCase):
    """Issue 473 AC1: every requirement kind a direct-owner observe reply returns carries
    its `expects`, attached at the envelope and accepted at the workflow-response boundary."""

    def scenarios(self):
        """One request per kind that makes `direct-owner` ask for exactly that kind."""
        def contract_missing():
            request = self.direct_request(
                issue=76, tracker=self.tracker_fact(76),
                worktree=self.worktree_fact(76, candidate={
                    "path": os.path.abspath(self.root / "worktree-issue-76"),
                    "state": "absent"}))
            request["delivery_contract"] = None
            request["authorization_intents"] = []
            return request

        def resumed():
            self.acquire_direct(issue=73)
            return self.direct_request(issue=73, owner_unavailable=True)

        return {
            "tracker": lambda: self.direct_request(issue=71),
            "forge_pr": lambda: self.direct_request(
                issue=72, tracker=self.tracker_fact(72), forge=None),
            "candidate_worktree": lambda: self.direct_request(
                issue=74, tracker=self.tracker_fact(74)),
            "delivery_contract": contract_missing,
            "recorded_worktree": resumed,
        }

    def test_every_observe_kind_is_described(self):
        scenarios = self.scenarios()
        self.assertEqual(set(scenarios), attempt_observations.OBSERVE_KINDS)
        for kind, request in scenarios.items():
            with self.subTest(kind=kind):
                completed = self.direct_owner_at_root(self.root, request())
                reply = self.validated_response(completed.stdout)
                self.assertEqual(reply["kind"], "observe")
                self.assertEqual([item["kind"] for item in reply["requirements"]], [kind])
                [item] = reply["requirements"]
                bare = {name: value for name, value in item.items() if name != "expects"}
                self.assertEqual(item, attempt_observations.describe(bare))
                expects = item["expects"]
                self.assertEqual(set(expects), set(attempt_observations.EXPECTS_MEMBERS))
                self.assertTrue(expects["members"])
                self.assertEqual(set(expects["example"]), set(expects["members"]))

    def test_an_undescribed_requirement_refuses_the_reply(self):
        workflow = load_source_module(SCRIPT, "workflow_state_undescribed_observe")
        scope_tuple = {"kind": "scope_tuple", "subject_id": "select",
                       "reason_code": "scope_tuple_required", "detail_pointer": None}
        with self.assertRaises(workflow.WorkflowError) as refused:
            workflow.direct_observe(73, None, [scope_tuple])
        self.assertIn("scope_tuple", str(refused.exception))
```

`test_delivery_model.py`: add `from agent_tools import attempt_observations` beside the other imports. Then add this class after `OwnerLivenessResponseTest`:

```python
class ObserveExpectsResponseTest(unittest.TestCase):
    """Issue 473 D4: a direct observe reply's requirements carry one closed `expects`."""

    BARE = (
        {"kind": "tracker"},
        {"kind": "recorded_worktree", "path": "/repo/.worktrees/worktree-issue-73-example"},
        {"kind": "candidate_worktree"},
        {"kind": "forge_pr", "path": "issue-73-"},
        {"kind": "delivery_contract", "subject_id": "73",
         "reason_code": "delivery_contract_required", "detail_pointer": None},
    )

    @classmethod
    def setUpClass(cls):
        cls.model = load_model(SOURCE, "delivery_model_observe_expects_test")

    def validate(self, value):
        return self.model.validate_delivery_object(
            value, expected_kind="workflow-response", notes_max_characters=4096)

    @staticmethod
    def observe(*bare):
        return {"interface_version": 2, "kind": "observe", "issue": 73, "run_id": None,
                "requirements": [attempt_observations.describe(item) for item in bare]}

    def test_each_direct_kind_is_accepted_with_its_description(self):
        for value in (*(self.observe(item) for item in self.BARE), self.observe(*self.BARE)):
            with self.subTest(kinds=[item["kind"] for item in value["requirements"]]):
                self.assertEqual(self.validate(copy.deepcopy(value)), value)

    def test_every_broken_expects_is_rejected(self):
        tracker, contract = self.observe(self.BARE[0]), self.observe(self.BARE[4])

        def mutated(base, change):
            value = copy.deepcopy(base)
            change(value["requirements"][0])
            return value

        scope_tuple = {"kind": "scope_tuple", "subject_id": "select",
                       "reason_code": "scope_tuple_required", "detail_pointer": None,
                       "expects": copy.deepcopy(tracker["requirements"][0]["expects"])}
        duplicate = copy.deepcopy(tracker)
        duplicate["requirements"].append(copy.deepcopy(duplicate["requirements"][0]))
        rejected = {
            "missing": mutated(tracker, lambda item: item.pop("expects")),
            "extra_member": mutated(tracker, lambda item: item["expects"].update(extra=1)),
            "missing_member": mutated(tracker, lambda item: item["expects"].pop("build")),
            "wrong_slot": mutated(tracker, lambda item: item["expects"].update(slot="forge")),
            "build_on_observed": mutated(
                tracker, lambda item: item["expects"].update(build="workflow-state x")),
            "null_build_on_contract": mutated(
                contract, lambda item: item["expects"].update(build=None)),
            "empty_build_on_contract": mutated(
                contract, lambda item: item["expects"].update(build="")),
            "example_keys_differ": mutated(
                tracker, lambda item: item["expects"]["example"].pop("state")),
            "example_not_object": mutated(
                tracker, lambda item: item["expects"].update(example=[])),
            "members_empty": mutated(tracker, lambda item: (
                item["expects"]["members"].clear(), item["expects"]["example"].clear())),
            "meaning_not_string": mutated(
                tracker, lambda item: item["expects"]["members"].update(state=1)),
            "meaning_empty": mutated(
                tracker, lambda item: item["expects"]["members"].update(state="")),
            "bare_extra_member": mutated(tracker, lambda item: item.update(path="issue-73-")),
            "control_only_kind": {**copy.deepcopy(tracker), "requirements": [scope_tuple]},
            "duplicate": duplicate,
        }
        for name, value in rejected.items():
            with self.subTest(mutation=name), self.assertRaises(self.model.DeliveryModelError):
                self.validate(value)

    def test_the_shared_requirement_shape_is_unchanged(self):
        checkpointed = copy.deepcopy(workflow_responses(self.model)["checkpointed"])
        checkpointed["requirements"][0]["expects"] = copy.deepcopy(
            self.observe(self.BARE[0])["requirements"][0]["expects"])
        with self.assertRaises(self.model.DeliveryModelError):
            self.validate(checkpointed)
```

If `workflow_responses` is not yet in `test_delivery_model.py`'s import list from `._delivery_model_fixtures`, add it there.

- [ ] **Step 2: Run the tests and watch them fail**

Run (Unit run): `test_workflow_state.py -k DirectObserveExpectsTest`, then `test_delivery_model.py -k ObserveExpectsResponseTest`.
Expected: FAIL. In `DirectObserveExpectsTest`, the bare item differs from `describe(bare)`, and `direct_observe` raises nothing for `scope_tuple`. In `ObserveExpectsResponseTest`, every described reply is rejected (the shared check refuses `expects`), and `missing` is accepted.

- [ ] **Step 3: Attach `expects` where the envelope is built**

`workflow-state.py`: change `from agent_tools import attempt_store, phase_budget` to `from agent_tools import attempt_observations, attempt_store, phase_budget`. In `direct_observe`, build the requirements as `[_call(None, attempt_observations.describe, item) for item in requirements]`. `_call(None, ...)` turns the `ValueError` into `WorkflowError` with the same message. Change nothing else: both callers, the policy comparison `policy["requirements"] != [{"kind": "tracker"}]` and the contract-requirement literal stay as they are.

`test_workflow_state.py`: in the same step, make the interface-1 projection drop what it now receives. In `LifecycleHarness._legacy_direct`, after `value["interface_version"] = 1`, add:

```python
        if value.get("kind") == "observe":
            for item in value["requirements"]:
                del item["expects"]
```

- [ ] **Step 4: Give observe replies their own requirement check**

`delivery_model/_wire.py`: add, after `_requirements`:

```python
# Issue 473 D4: the request member that answers each direct observe requirement kind. This
# is the validator's own copy; the AC1 scenarios pin it to the agent_tools catalogue.
_OBSERVE_SLOTS = {"tracker": "tracker", "recorded_worktree": "worktree",
                  "candidate_worktree": "worktree", "forge_pr": "forge",
                  "delivery_contract": "delivery_contract"}


def _observe_requirements(values: Any) -> list[Any]:
    """A direct observe reply's requirements: the five direct kinds, none twice, each with
    its bare members and one closed `expects` (issue 473 D4)."""
    if not isinstance(values, list): _reject()
    seen: set[bytes] = set()
    for item in values:
        if (not isinstance(item, dict) or not isinstance(item.get("kind"), str)
                or item["kind"] not in _OBSERVE_SLOTS or "expects" not in item): _reject()
        bare = {name: member for name, member in item.items() if name != "expects"}
        _requirements([bare], sorted_values=False)
        if canonical_bytes(bare) in seen: _reject()
        seen.add(canonical_bytes(bare))
        expects = _object(item["expects"], _members("slot members example build"),
                          "requirement expects")
        if expects["slot"] != _OBSERVE_SLOTS[item["kind"]]: _reject()
        if item["kind"] == "delivery_contract": _string(expects["build"], "requirement build")
        elif expects["build"] is not None: _reject()
        members = expects["members"]
        if not isinstance(members, dict) or not members or any(
                not name or not isinstance(meaning, str) or not meaning
                for name, meaning in members.items()): _reject()
        if not isinstance(expects["example"], dict) or set(expects["example"]) != set(members):
            _reject()
    return values
```

In `_workflow_response`'s `kind == "observe"` branch, replace `_requirements(value["requirements"], sorted_values=False)` with `_observe_requirements(value["requirements"])`. `canonical_bytes` is already imported from `._canonical`.

- [ ] **Step 5: Move the raw pins and the fixture to the described shape**

- `_delivery_model_fixtures.py`: add `from agent_tools.attempt_observations import describe`. In the `"observe"` fixture, set `"requirements": [describe({"kind": "tracker"})]`.
- `test_delivery_workflow.py`: add `from agent_tools.attempt_observations import describe`. After `CONTRACT_REQUIRED_172`, add `DIRECT_CONTRACT_REQUIRED = [describe(item) for item in CONTRACT_REQUIRED]`. Then pin the described shape at each raw direct observe site:
  - about line 232 (`test_contractless_public_outputs_are_requirement_only`): `"requirements": [describe({"kind": "tracker"})]`;
  - the loop's three `expected` lists in `test_direct_acquisition_asks_for_the_contract_last`: wrap each bare requirement in `describe(...)`;
  - the three direct observe dicts that use `"requirements": CONTRACT_REQUIRED` (about lines 3147, 3309 and 3354): use `DIRECT_CONTRACT_REQUIRED`.
- Leave each control-summary use of `CONTRACT_REQUIRED` and `CONTRACT_REQUIRED_172` bare (D4).

- [ ] **Step 6: Verify**

Unit run each of the following (timeout 900 s each; durations at the base in brackets):
1. `test_workflow_state.py -k DirectObserveExpectsTest -k ObservationCatalogueTest -k direct` [about 20 s]. Expected: `OK`, including the unchanged interface-1 pins that now pass through `del item["expects"]`.
2. `test_delivery_model.py` [about 1 s]. Expected: `OK`.
3. `test_artifact_budget.py` [25–125 s, depending on load]. Expected: `OK`. Every fixture reply, the described observe included, still passes, and the checkpointed reply with a bare `tracker` requirement is still refused.
4. `test_delivery_workflow.py -k direct -k ContractLifecycleTest -k test_contractless_public_outputs_are_requirement_only` [50–130 s]. Expected: `OK`.
5. Scope (exits 1 when either file changed, so the policy and the remainder requirements stay bare): `bash -c 'test -z "$(git diff --stat HEAD -- home/common/agent-skills/scripts/workflow_delivery.py home/common/agent-skills/scripts/workflow_delivery_wire.py)"'`.

- [ ] **Step 7: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/scripts/delivery_model/_wire.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/_delivery_model_fixtures.py home/common/agent-skills/tests/test_delivery_workflow.py
launch-commit ... -- -m "feat(workflow-state): observe requirements carry their expects description (issue 473)"
```
