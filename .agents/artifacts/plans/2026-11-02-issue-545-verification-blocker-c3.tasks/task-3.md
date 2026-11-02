# Task 3: Bootstrap interface 3 lists the awaited blockers

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow_delivery_wire.py` (`DeliveryProjection.bootstrap`)
- Modify: `home/common/agent-skills/scripts/delivery_model/_wire.py` (`_workflow_response`, the `workflow_bootstrap` branch)
- Modify: `home/common/agent-skills/tests/test_verification_control.py` (`BootstrapTest`)
- Modify: `home/common/agent-skills/tests/test_workflow_state.py`, `test_delivery_workflow.py`, `_delivery_model_fixtures.py`, `test_artifact_budget.py` (under `home/common/agent-skills/tests/`; bootstrap fixtures)
- Modify: `home/common/agent-skills/README.md` (`### Verification blockers`, second paragraph)

**Interfaces:**
- Consumes: Task 1's `verification_blocker.requirement`; Task 2's `_verification(item)` in `delivery_model/_wire.py`, `ControlHarness`, `asked`, `X`, `Y`, `observed`, `NEXT`.
- Produces: the interface-3 `workflow_bootstrap`, exactly `{interface_version: 3, kind, run_id, requirements, verification}`; `requirements` is unchanged (D6).

**Invariants:**
- `verification` lists, once each and sorted by `blocker_id`, `requirement(record)` of every `open` record that the latest attempt of an issue whose delivery is not complete is parked on; a `resolved` record is never listed (D6).
- The bootstrap stays a locked read; the projection reads the map it is given and writes nothing (D15).
- The validator admits interface 3 only, with `verification` a sorted, unique list of closed requirements whose `kind` is the literal `verification`; a wrong string or a non-string `kind` is refused by Task 2's `_verification` (D9).

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_verification_control.py`, insert before `if __name__ == "__main__":`:

```python
class BootstrapTest(ControlHarness, unittest.TestCase):
    """Issue 545 D6, D9: `init-run` lists each awaited open blocker once, by id."""

    def bootstrap(self):
        done = self.run_cli("init-run", "--repo-root", self.root, "--run-id", self.run_id)
        return self.validated_response(done.stdout)

    def test_the_bootstrap_lists_the_open_blockers_awaited_until_they_resolve(self):
        self.parked((61, X), (62, Y), (63, X))
        boot = self.bootstrap()
        self.assertEqual(boot["interface_version"], 3)
        self.assertEqual(boot["verification"],
                         sorted([asked(X), asked(Y)], key=lambda item: item["blocker_id"]))
        self.assertEqual([item["issue"] for item in boot["requirements"]], [61, 62, 63])
        resolved = self.sweep(9, observed(X, NEXT), issues=(61, 62, 63), max_parallel=1)
        self.assertEqual(self.dispatched(resolved), [("resume", "61:1:2")])
        self.assertEqual(self.bootstrap()["verification"], [asked(Y)])
        self.sweep(10, observed(Y, NEXT), issues=(61, 62, 63), max_parallel=1)
        self.assertEqual({record["state"] for record in self.blockers().values()},
                         {"resolved"})
        self.assertEqual(self.bootstrap()["verification"], [])

    def test_the_validator_admits_only_interface_three(self):
        self.parked((61, X), (62, Y))
        boot = self.bootstrap()
        model = self.delivery_model

        def mutated(change):
            value = json.loads(json.dumps(boot))
            change(value)
            return value

        def interface_two(value):
            value["interface_version"] = 2

        def without_member(value):
            del value["verification"]

        def unsorted(value):
            value["verification"].reverse()

        def repeated(value):
            value["verification"].append(value["verification"][0])

        def opened(value):
            value["verification"][0]["note"] = "x"

        def other_kind(value):
            value["verification"][0]["kind"] = "worktree_fact"

        def null_kind(value):
            value["verification"][0]["kind"] = None

        self.assertEqual(model.validate_delivery_object(
            boot, expected_kind="workflow-response", notes_max_characters=4096), boot)
        for change in (interface_two, without_member, unsorted, repeated, opened, other_kind,
                       null_kind):
            with self.subTest(case=change.__name__), \
                    self.assertRaises(model.DeliveryModelError):
                model.validate_delivery_object(
                    mutated(change), expected_kind="workflow-response",
                    notes_max_characters=4096)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_verification_control.py -k Bootstrap 2>&1 | tail -3'`
Expected: `Ran 2 tests` and `FAILED (failures=2, errors=6)`: `AssertionError: 2 != 3` (the interface-2 bootstrap), `DeliveryModelError not raised` for `interface_two`, and `KeyError: 'verification'` for the other six mutations.

- [ ] **Step 3: Implement bootstrap interface 3**

`workflow_delivery_wire.py`, `DeliveryProjection.bootstrap` (it already imports `verification_blocker` since Task 2): add the docstring `The interface-3 `workflow_bootstrap`: each unfinished issue's custody requirement, and the requirement of every `open` verification blocker that an unfinished issue's latest attempt is parked on, once per blocker in id order (issue 545 D6).` Keep an `awaited = {}` map. Inside the issue loop, right after the delivery-complete `continue`, take `latest = issue_state["attempts"][-1] if issue_state["attempts"] else None`; when `latest` is `suspended` with `blocked_on` `verification`, read `record = state["verification_blockers"][latest["verification_blocker"]]` and, when its `state` is `open`, set `awaited[record["id"]] = verification_blocker.requirement(record)`. Return `{"interface_version": 3, "kind": "workflow_bootstrap", "run_id": ..., "requirements": requirements, "verification": [awaited[key] for key in sorted(awaited)]}`.

`delivery_model/_wire.py`, `_workflow_response`, the `workflow_bootstrap` branch: the member set gains `verification`; replace `_v2(value)` with an interface check for exactly the integer 3; then, under the comment `# Issue 545 D9: the awaited open blockers, each the closed requirement, by id.`, require `verification` to be a list, pass each element to `_verification`, and `_sorted_unique(value["verification"], "bootstrap verification", key=lambda item: item["blocker_id"])`. The `requirements` checks are unchanged.

Fixtures (D13), each bootstrap literal at interface 3 with `"verification": []`:
- `test_workflow_state.py`: the zero-id run's `init-run` reply.
- `test_delivery_workflow.py`: the `admission` run's `init-run` reply.
- `_delivery_model_fixtures.py`: the `bootstrap` response.
- `test_artifact_budget.py`: every `workflow_bootstrap` object and byte literal (the valid-shape test, the wire-bound `bootstrap(count)`, the contract-digest cases, the duplicate-key and invalid-UTF-8 refusals, and both loader payloads).

`home/common/agent-skills/README.md`, `### Verification blockers`, second paragraph: insert before ` Known limitation:` the sentence:

```text
 `init-run`'s `workflow_bootstrap` is interface 3: beside `requirements` it carries `verification`, the requirement of every `open` record that an unfinished issue's latest attempt is parked on, once each and sorted by `blocker_id`, so one control call can answer every awaited record.
```

- [ ] **Step 4: Verify**

Run (timeout 3000 s): `PYTHONPATH="$PWD/python" python3 -m agent_tools.suite_runner --jobs 6 home/common/agent-skills/tests/test_verification_control.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/tests/test_control_cutover.py home/common/agent-skills/tests/test_control_decisions.py tests/test_orchestrate_control.py 2>&1 | tail -2`
Expected: `suite-runner: summary members=8 passed=8 failed=0`.
Run: `if grep -n '"interface_version": 2, "kind": "workflow_bootstrap"\|interface_version":2,"kind":"workflow_bootstrap' home/common/agent-skills/tests/*.py; then exit 1; fi`
Expected: no line printed.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow_delivery_wire.py home/common/agent-skills/scripts/delivery_model/_wire.py home/common/agent-skills/tests/test_verification_control.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/_delivery_model_fixtures.py home/common/agent-skills/tests/test_artifact_budget.py home/common/agent-skills/README.md
launch-commit … -- -m "feat(workflow-state): bootstrap 3 lists awaited blockers" -m "Issue 545." -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":3,"records":[{"bounds":[{"added_lines":28,"boundary":"all","deleted_lines":6,"record_bytes":10240,"support":{"covers":["r2b","r3a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3a","last_task":3,"owner":3,"path":"home/common/agent-skills/scripts/workflow_delivery_wire.py"},{"bounds":[{"added_lines":38,"boundary":"all","deleted_lines":11,"record_bytes":14848,"support":{"covers":["r2d","r3b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3b","last_task":4,"owner":3,"path":"home/common/agent-skills/scripts/delivery_model/_wire.py"},{"bounds":[{"added_lines":470,"boundary":"all","deleted_lines":0,"record_bytes":25600,"support":{"covers":["r2m","r3c"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r3c","last_task":3,"owner":3,"path":"home/common/agent-skills/tests/test_verification_control.py"},{"bounds":[{"added_lines":9,"boundary":"all","deleted_lines":8,"record_bytes":7680,"support":{"covers":["r2o","r3d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3d","last_task":4,"owner":3,"path":"home/common/agent-skills/tests/test_workflow_state.py"},{"bounds":[{"added_lines":12,"boundary":"all","deleted_lines":12,"record_bytes":12800,"support":{"covers":["r2p","r3e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3e","last_task":4,"owner":3,"path":"home/common/agent-skills/tests/test_delivery_workflow.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":4,"record_bytes":3072,"support":{"covers":["r2q","r3f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3f","last_task":3,"owner":3,"path":"home/common/agent-skills/tests/_delivery_model_fixtures.py"},{"bounds":[{"added_lines":16,"boundary":"all","deleted_lines":15,"record_bytes":11776,"support":{"covers":["r3g"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3g","last_task":3,"owner":3,"path":"home/common/agent-skills/tests/test_artifact_budget.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":2,"record_bytes":17408,"support":{"covers":["r2k","r3h"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3h","last_task":4,"owner":3,"path":"home/common/agent-skills/README.md"}]}}
```
