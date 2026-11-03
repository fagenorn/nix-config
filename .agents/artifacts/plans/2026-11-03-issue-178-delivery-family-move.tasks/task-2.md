# Task 2: Name the delivery format for delivery

Decision: D3 (parent D11). Spec § "The delivery model and its format rename"
in the Solution, the `delivery_model` item of § "How each file changes", and
AC4. Work from the worktree root. `PK` = `python/agent_tools`,
`T` = `home/common/agent-skills/tests`. This task's diff is the rename alone:
no other edit rides in it, so both Task 1's renames and this one stay pure.

**Files:**
- Modify: `PK/delivery_model/__init__.py`, `PK/delivery_model/_canonical.py`,
  `PK/delivery_model/_objects.py`, `PK/delivery_model/_reconcile.py`,
  `PK/delivery_model/_wire.py`, `PK/workflow_state.py`,
  `PK/workflow_delivery.py`, `PK/workflow_delivery_build.py`
- Modify (tests): `T/_delivery_model_fixtures.py`, `T/test_admission_replay.py`,
  `T/test_artifact_budget.py`, `T/test_attempt_custody.py`,
  `T/test_control_cutover.py`, `T/test_control_decisions.py`,
  `T/test_delivered_control.py`, `T/test_delivery_model.py`,
  `T/test_delivery_sealing.py`, `T/test_delivery_workflow.py`,
  `T/test_ship_delivery.py`, `T/test_verification_control.py`,
  `T/test_workflow_delivery.py`, `T/test_workflow_state.py`

**Interfaces:**
- Consumes: Task 1's `agent_tools.delivery_model` and the suites' `model`,
  `self.model`, `runtime.model` and `self._model` bindings to it.
- Produces: `agent_tools.delivery_model.delivery_bytes(value: object, *, omit_derived: str | None = None) -> bytes`
  and `delivery_digest(value: object, *, omit_derived: str | None = None) -> str`
  (the `sha256:` prefix plus the hex digest of `delivery_bytes`), with the
  bodies of today's `canonical_bytes` and `canonical_digest`. There is no
  alias. `__all__` lists the two new names where the old ones stood.

**Invariants:**
- Bytes and digests do not change:
  `test_the_contract_digest_for_an_unchanged_input_is_pinned` and
  `test_canonical_bytes_and_derived_digest_are_exact` keep their literals.
- Only the whole words `canonical_bytes` and `canonical_digest` change, and
  only in **Files**. `review_forecast.canonical_bytes`,
  `verification_blocker.canonical_bytes`, `agent_tools.canonical.telemetry_digest`,
  the private file `_canonical.py`, attempt_delivery's `canonical_text`
  parameter and every file under `tests/` keep their names.
- No line is reflowed; lines only get shorter.

- [ ] **Step 1: Write the failing test**

In `T/test_delivery_model.py`, `test_import_is_pure_and_interface_is_exact`'s
expected set (as Task 1 left it) becomes:

```python
            self.assertEqual(set(names), {
                "DeliveryModelError", "delivery_bytes",
                "delivery_digest", "validate_delivery_object", "validate_custody_ref",
                "match_scope", "current_selection", "reduce_delivery", "STAGE_ACTIONS",
                "OBSERVATION_KINDS",
            })
```

- [ ] **Step 2: Watch it fail**

Run (timeout 300 s): `PYTHONPATH=$PWD/python python3 -m unittest -v -k test_import_is_pure home/common/agent-skills/tests/test_delivery_model.py`
Expected: FAIL, an `AssertionError` whose set difference names
`canonical_bytes`, `canonical_digest`, `delivery_bytes` and `delivery_digest`.

- [ ] **Step 3: Rename**

Run, over exactly the **Files** paths:
`perl -pi -e 's/\bcanonical_bytes\b/delivery_bytes/g; s/\bcanonical_digest\b/delivery_digest/g' <paths>`.
Then read `git diff -U0 -- python home` once: every changed line differs only
in those words. In `PK/delivery_model/__init__.py` the import keeps its two
lines and `__all__` its layout.

- [ ] **Step 4: Verify**

1. `if git grep -nwE "canonical_digest|canonical_bytes" -- python/agent_tools/delivery_model python/agent_tools/workflow_state.py python/agent_tools/workflow_delivery.py python/agent_tools/workflow_delivery_build.py python/agent_tools/artifact_budget.py home/common/agent-skills/tests; then exit 1; fi`
2. `git grep -n "def telemetry_digest" -- python` lists only
   `python/agent_tools/canonical.py`, and
   `git grep -nE "def delivery_(bytes|digest)" -- python` lists only
   `python/agent_tools/delivery_model/_canonical.py`.
3. `git diff --stat HEAD -- tests` prints nothing.
4. Focused (timeout 1800 s): `PYTHONPATH=$PWD/python python3 -m agent_tools.suite_runner`
   over the 14 test paths of **Files** except `_delivery_model_fixtures.py`:
   exit 0, Step 1's test included.
5. `just build` (timeout 3600 s): exit 0.

- [ ] **Step 5: Commit**

One commit through `launch-commit`, subject
`refactor(issue-178): rename the delivery format functions`.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":2,"records":[{"bounds":[{"added_lines":6089,"boundary":"all","deleted_lines":0,"record_bytes":308224,"support":{"covers":["a02","b01"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b01","last_task":2,"owner":2,"path":"python/agent_tools/workflow_state.py"},{"bounds":[{"added_lines":1488,"boundary":"all","deleted_lines":0,"record_bytes":83968,"support":{"covers":["a04","b02"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b02","last_task":2,"owner":2,"path":"python/agent_tools/workflow_delivery.py"},{"bounds":[{"added_lines":710,"boundary":"all","deleted_lines":0,"record_bytes":41984,"support":{"covers":["a08","b03"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b03","last_task":2,"owner":2,"path":"python/agent_tools/workflow_delivery_build.py"},{"bounds":[{"added_lines":13,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["a10","b04"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b04","last_task":2,"owner":2,"path":"python/agent_tools/delivery_model/__init__.py"},{"bounds":[{"added_lines":126,"boundary":"all","deleted_lines":0,"record_bytes":6144,"support":{"covers":["a12","b05"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b05","last_task":2,"owner":2,"path":"python/agent_tools/delivery_model/_canonical.py"},{"bounds":[{"added_lines":654,"boundary":"all","deleted_lines":0,"record_bytes":47104,"support":{"covers":["a14","b06"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b06","last_task":2,"owner":2,"path":"python/agent_tools/delivery_model/_objects.py"},{"bounds":[{"added_lines":274,"boundary":"all","deleted_lines":0,"record_bytes":22528,"support":{"covers":["a16","b07"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b07","last_task":2,"owner":2,"path":"python/agent_tools/delivery_model/_reconcile.py"},{"bounds":[{"added_lines":707,"boundary":"all","deleted_lines":0,"record_bytes":53248,"support":{"covers":["a18","b08"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b08","last_task":2,"owner":2,"path":"python/agent_tools/delivery_model/_wire.py"},{"bounds":[{"added_lines":20,"boundary":"all","deleted_lines":20,"record_bytes":20480,"support":{"covers":["b09"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b09","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/_delivery_model_fixtures.py"},{"bounds":[{"added_lines":5,"boundary":"all","deleted_lines":5,"record_bytes":11264,"support":{"covers":["a50","b10"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b10","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_admission_replay.py"},{"bounds":[{"added_lines":43,"boundary":"all","deleted_lines":143,"record_bytes":79872,"support":{"covers":["a47","b11"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b11","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_artifact_budget.py"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":3,"record_bytes":8192,"support":{"covers":["b12"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b12","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_attempt_custody.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":5,"record_bytes":13312,"support":{"covers":["a57","b13"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b13","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_control_cutover.py"},{"bounds":[{"added_lines":3,"boundary":"all","deleted_lines":3,"record_bytes":8192,"support":{"covers":["b14"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b14","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_control_decisions.py"},{"bounds":[{"added_lines":26,"boundary":"all","deleted_lines":26,"record_bytes":24576,"support":{"covers":["a46","b15"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b15","last_task":3,"owner":2,"path":"home/common/agent-skills/tests/test_delivered_control.py"},{"bounds":[{"added_lines":55,"boundary":"all","deleted_lines":85,"record_bytes":65536,"support":{"covers":["a48","b16"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b16","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_delivery_model.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":4096,"support":{"covers":["b17"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b17","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_delivery_sealing.py"},{"bounds":[{"added_lines":109,"boundary":"all","deleted_lines":209,"record_bytes":147456,"support":{"covers":["a45","b18"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b18","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_delivery_workflow.py"},{"bounds":[{"added_lines":5,"boundary":"all","deleted_lines":6,"record_bytes":11264,"support":{"covers":["a59","b19"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b19","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_ship_delivery.py"},{"bounds":[{"added_lines":13,"boundary":"all","deleted_lines":13,"record_bytes":13312,"support":{"covers":["a55","b20"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b20","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_verification_control.py"},{"bounds":[{"added_lines":16,"boundary":"all","deleted_lines":18,"record_bytes":24576,"support":{"covers":["a49","b21"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b21","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_workflow_delivery.py"},{"bounds":[{"added_lines":92,"boundary":"all","deleted_lines":112,"record_bytes":102400,"support":{"covers":["a44","b22"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"b22","last_task":2,"owner":2,"path":"home/common/agent-skills/tests/test_workflow_state.py"}]}}
```
