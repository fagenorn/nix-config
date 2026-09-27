# Task 2: `progress` replies with a closed v2 `phase_gate`

Per D5, D7, D9. Abbreviations: `S` = `home/common/agent-skills/scripts`,
`T` = `home/common/agent-skills/tests`.

**Files:**
- Modify: `S/delivery_model/_wire.py`, `S/workflow-state.py`
- Test: `T/_delivery_model_fixtures.py`, `T/test_delivery_model.py`,
  `T/test_workflow_state.py`

**Interfaces:**
- Consumes: `LifecycleHarness.validated_response(self, stdout: str) -> dict`
  from Task 1. It pipes `stdout` through the real `workflow-response` boundary,
  asserts exit 0 and byte-equal canonical output, and returns the decoded
  reply.
- Consumes: `DeliveryRuntime.custody_for_record(issue: int, kind: str, record: dict) -> dict`,
  reached in `workflow-state` as `_delivery().custody_for_record`. It is the one
  custody renderer and returns `{"kind", "attempt", "launch", "action_id"}`.
- Produces: the `phase_gate` wire kind. `workflow-state progress` prints it on
  success, and `_workflow_response` accepts it:
  `{"interface_version": 2, "kind": "phase_gate", "run_id": str, "issue": int, "custody": <implementation custody>, "action": "continue"|"fresh_start"|"handoff"|"delegate", "handoff_path": str|null}`.
- Produces: `LifecycleHarness.progress(...)` returns the decoded, validated
  reply when `ok=True`, and the `CompletedProcess` when `ok=False` (unchanged).
- Produces: the fixture `workflow_responses(model)["phase_gate"]`.

**Invariants:**
- `progress` persists exactly what it persists today. Every ledger-bytes
  assertion in `test_workflow_state.py` stays unchanged and green.
- `handoff_path` is the absolute path this call finalized with
  `--handoff-path`, else `null`. It is never the attempt's stored `handoff_path`.
- `custody` renders the attempt's current launch. `workflow-state` never
  composes the action id for this reply.
- `_workflow_response` stays a closed dispatch whose fallthrough is `_reject()`.

- [ ] **Step 1: Write the failing tests**

(a) In `T/_delivery_model_fixtures.py`, in `workflow_responses`'s returned
dict, insert this entry directly before the `"terminal"` entry:

```python
        "phase_gate": {"interface_version": 2, "kind": "phase_gate", "run_id": "run-1",
                       "issue": 151, "custody": active, "action": "handoff",
                       "handoff_path": "/repo/.superpowers/workflows/run-1/handoffs/issue-151.md"},
```

(b) In `T/test_delivery_model.py`, `test_workflow_response_validation_is_structural_only`,
add `"phase_gate"` to the expected fixture-name set, so its last line reads
`"host_route", "host_route_unsupported", "phase_gate"})`. Insert this method
immediately before `def test_current_launch_and_null_contract_correlations_are_exact`:

```python
    def test_phase_gate_reply_is_closed_and_bound_to_its_issue(self):
        """#191 D5: `progress` replies with one closed v2 `phase_gate`."""
        gate = workflow_responses(self.model)["phase_gate"]
        for action in ("continue", "fresh_start", "handoff", "delegate"):
            value = {**copy.deepcopy(gate), "action": action, "handoff_path": None}
            with self.subTest(action=action):
                self.assertEqual(self.validate(value, "workflow-response"), value)
        missing = copy.deepcopy(gate)
        del missing["handoff_path"]
        for name, bad in {
            "extra member": {**copy.deepcopy(gate), "phase_action": "handoff"},
            "missing member": missing,
            "interface 1": {**copy.deepcopy(gate), "interface_version": 1},
            "remainder custody": {**copy.deepcopy(gate), "custody": custody("remainder")},
            "another issue's custody": {**copy.deepcopy(gate), "issue": 152},
            "unknown action": {**copy.deepcopy(gate), "action": "retry"},
            "handoff path on continue": {**copy.deepcopy(gate), "action": "continue"},
            "empty handoff path": {**copy.deepcopy(gate), "handoff_path": ""},
            "null run": {**copy.deepcopy(gate), "run_id": None},
        }.items():
            with self.subTest(invalid=name):
                self.assert_invalid(bad, "workflow-response")
```

(c) In `T/test_workflow_state.py`, `LifecycleHarness.progress`, change the last
line to `return self.validated_response(completed.stdout) if ok else completed`.
Then insert this class immediately before `class ReconciledReplyBoundaryTest`,
which Task 1 added:

```python
class PhaseGateReplyTest(LifecycleHarness, unittest.TestCase):
    """#191 D5: `progress` replies with one closed, validated `phase_gate`."""

    def test_each_action_names_its_custody_and_only_this_calls_handoff(self):
        self.init_run()
        worktree = self.root / "wt-14"
        self.spawn(issue=14, worktree=worktree)
        gate = {"interface_version": 2, "kind": "phase_gate", "run_id": self.run_id,
                "issue": 14, "custody": {"kind": "implementation", "attempt": 1,
                                         "launch": 1, "action_id": "14:1:1"},
                "handoff_path": None}
        for phase, overrides, action in (
                (1, {}, "continue"),
                (2, {"next_needs_context": False, "artifacts_sufficient": True}, "fresh_start"),
                (3, {"turn_count": 118}, "handoff"),
                (4, {"remainder_self_contained": True}, "delegate")):
            with self.subTest(action=action):
                reply = self.progress(phase=phase, now=f"2026-08-13T20:0{phase}:00Z",
                                      **overrides)
                self.assertEqual(reply, {**gate, "action": action})
                attempt = self.read_state()["issues"]["14"]["attempts"][0]
                self.assertEqual((attempt["phase"], attempt["phase_action"], attempt["state"]),
                                 (phase, action, "active"))
        handoff = self.write_handoff(14)
        finalized = self.progress(phase=5, now="2026-08-13T20:05:00Z", turn_count=118,
                                  handoff_path=handoff)
        self.assertEqual(finalized, {**gate, "action": "handoff", "handoff_path": str(handoff)})
        attempt = self.read_state()["issues"]["14"]["attempts"][0]
        self.assertEqual((attempt["state"], attempt["handoff_path"]),
                         ("handed_off", str(handoff)))
        self.resume(issue=14, worktree=worktree, now="2026-08-13T20:06:00Z")
        resumed = self.progress(phase=6, now="2026-08-13T20:07:00Z")
        self.assertEqual(resumed, {**gate, "action": "continue", "custody": {
            "kind": "implementation", "attempt": 1, "launch": 2, "action_id": "14:1:2"}})
        self.assertEqual(
            self.read_state()["issues"]["14"]["attempts"][0]["handoff_path"], str(handoff))

    def test_a_direct_run_replies_with_its_own_run_and_issue(self):
        owner = self.acquire_direct(issue=191)
        self.run_id = owner["run_id"]
        reply = self.progress(issue=191, phase=1, now="2026-08-20T10:05:00Z",
                              remainder_self_contained=True)
        self.assertEqual(reply, {
            "interface_version": 2, "kind": "phase_gate", "run_id": "direct-191-000001",
            "issue": 191, "custody": {"kind": "implementation", "attempt": 1,
                                      "launch": 1, "action_id": "191:1:1"},
            "action": "delegate", "handoff_path": None})
```

(d) Existing call sites in `T/test_workflow_state.py` read ledger fields off
the old reply. Make these edits in class `WorkflowStateLifecycleTest`. Each
line on the left is the old text, which is unique within its test. Each ledger
read goes to the ledger (D7).

| Test | Old | New |
|---|---|---|
| `test_handed_off_finish_rejects_without_changing_state` | `self.assertEqual(handed_off["state"], "handed_off")` | `self.assertEqual(handed_off["handoff_path"], str(handoff_path))` then `self.assertEqual(self.read_state()["issues"]["14"]["attempts"][0]["state"], "handed_off")` |
| `test_progress_action_precedence_and_complete_inputs_are_persisted` | `result["phase_action"]` | `result["action"]` |
| `test_direct_progress_uses_complete_artifact_first_precedence` | `result["phase_action"]` | `result["action"]` |
| `test_non_direct_phase_order_and_ledger_bytes_remain_exact` | `self.assertEqual(result, expected_attempt)` | `self.assertEqual(result, {"interface_version": 2, "kind": "phase_gate", "run_id": run_id, "issue": 14, "custody": {"kind": "implementation", "attempt": 1, "launch": 1, "action_id": "14:1:1"}, "action": "handoff", "handoff_path": None})` |
| `test_zero_sequence_direct_shaped_dispatcher_keeps_non_direct_progress_and_reopen_bytes` | `self.assertEqual(result, expected_attempt)` | the same dict with `"run_id": "direct-14-000000"` |
| `test_delegate_requires_measured_usage_below_both_ceilings` | `delegated`/`unknown_usage`/`at_context_ceiling`/`at_turn_ceiling` `["phase_action"]` | `["action"]` |
| `test_unknown_usage_continues_a_dispatched_run_across_phase_gates` | `(decision["phase_action"], decision["state"])` and `at_ceiling["phase_action"]` | `(decision["action"], self.read_state()["issues"]["14"]["attempts"][0]["state"])` and `at_ceiling["action"]` |
| `test_durable_handoff_requires_safe_file_and_resumes_same_attempt` | `(decision["phase_action"], decision["state"]), ("handoff", "active")` | `(decision["action"], self.read_state()["issues"]["14"]["attempts"][0]["state"]), ("handoff", "active")` |
| same test | `self.assertEqual(finalized["state"], "handed_off")` | `self.assertEqual(self.read_state()["issues"]["14"]["attempts"][0]["state"], "handed_off")`, and keep the `finalized["handoff_path"]` assertion |
| same test, the stale-handoff regression (D5) | `self.assertEqual((continued["phase_action"], continued["state"]), ("continue", "active"))` and `self.assertEqual(continued["handoff_path"], str(handoff_path))` | `self.assertEqual((continued["action"], continued["handoff_path"], continued["custody"]["action_id"]), ("continue", None, "14:1:2"))`, then `attempt = self.read_state()["issues"]["14"]["attempts"][0]` and `self.assertEqual((attempt["state"], attempt["handoff_path"]), ("active", str(handoff_path)))` |
| `test_progress_rejects_threshold_continue_invalid_inputs_and_transitions` | `at_turn_threshold["phase_action"]`, `at_context_threshold["phase_action"]` | `["action"]` |
| `test_combined_controller_demo_has_one_authoritative_outcome_per_issue` | `decision["phase_action"]` | `decision["action"]` |
| `test_absent_direct_handoff_materializes_exact_worktree_then_records_phase_one` | `self.assertEqual(progressed["phase"], 1)` | `self.assertEqual(progressed["custody"]["action_id"], "73:1:2")`, and after its `attempts = state["issues"]["73"]["attempts"]` line add `self.assertEqual(attempts[0]["phase"], 1)` |
| `test_reserved_direct_ids_are_closed_to_init_and_control_but_open_to_owner_mutations` | `progress["phase_action"]` | `progress["action"]` |
| `test_direct_owner_resumes_a_suspension_in_a_fresh_budget_window` | `self.progress(issue=73, now="2026-08-20T15:30:00Z")["phase_action"]` | `...["action"]` |

Ledger reads such as `persisted["phase_action"]`, `attempt["phase_action"]` and
`state["issues"][...]["phase_action"] = …` stay as they are. So does
`result["state"]` in the reconcile tests, where `result` is a ledger result.
This gate matches 18 lines at the start and must print nothing after the edits:
`grep -nE '\b(decision|delegated|unknown_usage|at_[a-z_]+|continued|progress|progressed|finalized|handed_off)\["(phase_action|state|phase)"\]|\bresult\["phase_action"\]|\)\["phase_action"\]' home/common/agent-skills/tests/test_workflow_state.py`

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'`
Expected: `FAILED`. The fixtures fail with `invalid` in `test_workflow_response_validation_is_structural_only`,
and the four accepted actions fail in `test_phase_gate_reply_is_closed_and_bound_to_its_issue`.

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k PhaseGateReplyTest -k test_handed_off_finish_rejects 2>&1 | grep -E '^(FAIL|ERROR):|AssertionError|^Ran |^OK|^FAILED'`
Expected: `FAILED`, with `Tuples differ: (2, 'artifact-budget: invalid report\n') != (0, '')`.
The raw attempt is refused at the boundary.

- [ ] **Step 3: Implement**

1. `S/delivery_model/_wire.py`, `_workflow_response`: insert a `phase_gate`
   branch immediately before the `delivery_remainder` line. It checks, in
   order:
   - the exact member set via
     `_object(value, _members("interface_version kind run_id issue custody action handoff_path"))`;
   - `_v2(value)`, and `_string(value["run_id"], "phase gate run")`, which
     requires a non-empty string;
   - `issue = _integer(value["issue"], "phase gate issue", minimum=1)`;
   - `_reject()` unless
     `validate_custody_ref(value["custody"], issue=issue)["kind"] == "implementation"`;
   - `_reject()` unless `value["action"]` is in
     `{"continue", "fresh_start", "handoff", "delegate"}`;
   - `_reject()` when `value["handoff_path"] is not None` and either
     `value["action"] != "handoff"` or the path is not a non-empty `str`.

   It then returns `value`. Keep the file's one-statement-per-line density,
   like the neighbouring branches.
2. `S/workflow-state.py`, `command_progress`: bind `runtime = _delivery()` right
   after `run_dir, _, _ = workflow_paths(...)`. In the `progress` closure, keep
   every existing check and mutation. Replace `return attempt, True` with a
   return of this reply and `True`:
   ```python
   {"interface_version": 2, "kind": "phase_gate", "run_id": args.run_id,
    "issue": args.issue,
    "custody": runtime.custody_for_record(args.issue, "implementation", attempt),
    "action": action, "handoff_path": handoff_path}
   ```
   `handoff_path` is the closure's local: `None`, or the value
   `validate_handoff_path` returned for this call. Replace the tail
   `persisted = transact(...)` / `print_json(persisted)` with
   `print_json(transact(args.repo_root, args.run_id, progress))`.

- [ ] **Step 4: Verify**

Summarize every run with the Step 2 `grep -E` filter.

1. `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_model.py home/common/agent-skills/tests/test_artifact_budget.py` → `OK`. `test_artifact_budget` validates every fixture through the CLI.
2. `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_host_admission.py` → `OK`. This takes about 12 minutes, so run it once. Every `progress()` call is now a boundary regression.
3. `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_delivery.py home/common/agent-skills/tests/test_admission_replay.py` → `OK`. These call `progress` through the CLI without reading its reply.
4. The Step 1(d) `grep` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/delivery_model/_wire.py \
  home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/tests/_delivery_model_fixtures.py \
  home/common/agent-skills/tests/test_delivery_model.py \
  home/common/agent-skills/tests/test_workflow_state.py
git commit -m "fix(agent-skills): reply to progress with a closed phase_gate (#191)"
```
