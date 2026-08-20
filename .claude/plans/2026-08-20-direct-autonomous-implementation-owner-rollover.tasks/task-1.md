# Task 1: Select Direct Phase Actions from Durable Run Identity

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/tests/test_workflow_state.py`
- Modify: `.claude/specs/2026-08-17-workflow-lifecycle-hardening-design.md`
- Test: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: the existing validated `run_id`, unchanged `PHASE_INPUT_FIELDS`, `DIRECT_RUN_ID_PATTERN`, and `progress` CLI arguments.
- Produces: `select_phase_action(*, run_id: str, turn_count: int | None, context_tokens: int | None, turn_ceiling: int, context_ceiling: int, turn_headroom: int, context_headroom: int, next_needs_context: bool, artifacts_sufficient: bool, remainder_self_contained: bool) -> str`; run-aware persisted-action revalidation through `validate_attempt(..., run_id: str)`; unchanged progress JSON and ledger shapes.

**Invariants:**
- Per D1, a reserved direct identity selects `delegate` first when `remainder_self_contained` is true, then eligible `fresh_start`, any known near-ceiling `handoff`, no-context `handoff`, and otherwise `continue`.
- A missing measure is not itself near-ceiling: a known near-ceiling peer still hands off, while missing usage with context-required work can continue to the next durable seam.
- Per D2, selection and reopened-ledger validation derive the policy only from `run_id`; no phase input or persisted field carries a direct-mode assertion.
- Every non-direct run evaluates the current order unchanged: eligible `fresh_start`, missing-usage `handoff`, near-ceiling `handoff`, `delegate`, no-context `handoff`, `continue`.
- A direct/non-direct action transplanted across identities fails loudly before mutation; delegation never changes `deadline_at`.

- [ ] **Step 1: Write the failing direct precedence, compatibility, and identity-validation tests**

Add these complete methods to `WorkflowStateLifecycleTest`:

```python
def test_direct_progress_uses_complete_artifact_first_precedence(self):
    cases = (
        ({"turn_count": None, "context_tokens": None,
          "remainder_self_contained": True}, "delegate"),
        ({"turn_count": 118, "context_tokens": 20000,
          "remainder_self_contained": True}, "delegate"),
        ({"turn_count": 118, "context_tokens": 140000,
          "next_needs_context": False, "artifacts_sufficient": True,
          "remainder_self_contained": True}, "delegate"),
        ({"turn_count": None, "context_tokens": None,
          "next_needs_context": False, "artifacts_sufficient": True},
         "fresh_start"),
        ({"turn_count": 118, "context_tokens": 140000,
          "next_needs_context": False, "artifacts_sufficient": True},
         "fresh_start"),
        ({"turn_count": None, "context_tokens": 140000,
          "next_needs_context": True}, "handoff"),
        ({"turn_count": None, "context_tokens": None,
          "next_needs_context": True}, "continue"),
        ({"turn_count": None, "context_tokens": None,
          "next_needs_context": False, "artifacts_sufficient": False},
         "handoff"),
        ({"turn_count": 10, "context_tokens": 20000,
          "next_needs_context": True}, "continue"),
    )
    for offset, (overrides, expected) in enumerate(cases, start=80):
        with self.subTest(issue=offset, expected=expected):
            owner = self.acquire_direct(issue=offset)
            self.run_id = owner["run_id"]
            result = self.progress(
                issue=offset, phase=1, now="2026-08-20T10:05:00Z",
                **overrides,
            )
            attempt = json.loads(
                self.direct_state_path(owner["run_id"]).read_text()
            )["issues"][str(offset)]["attempts"][0]
            self.assertEqual(result["phase_action"], expected)
            self.assertEqual(attempt["phase_action"], expected)
            self.assertEqual(attempt["phase_inputs"]["remainder_self_contained"],
                             overrides.get("remainder_self_contained", False))
            self.assertEqual(attempt["deadline_at"], owner["deadline_at"])

def test_non_direct_phase_order_and_ledger_bytes_remain_exact(self):
    for run_id in ("dispatcher-owned", "durable-interactive"):
        with self.subTest(run_id=run_id):
            self.run_id = run_id
            self.init_run()
            worktree = os.path.abspath(self.root / f"{run_id}-worktree")
            self.spawn(issue=14, worktree=worktree)
            result = self.progress(
                issue=14, phase=1, turn_count=118, context_tokens=20000,
                remainder_self_contained=True,
            )
            expected_inputs = {
                "turn_count": 118, "context_tokens": 20000,
                "turn_ceiling": 120, "context_ceiling": 150000,
                "turn_headroom": 2, "context_headroom": 10000,
                "next_needs_context": True, "artifacts_sufficient": False,
                "remainder_self_contained": True,
            }
            expected_attempt = {
                "issue": 14, "attempt": 1, "owner": "14:1",
                "worktree": worktree, "started_at": DEFAULT_NOW,
                "deadline_at": "2026-08-13T20:30:00Z", "state": "active",
                "launch_kind": "fresh", "launches": [{
                    "kind": "fresh", "owner": "14:1",
                    "worktree": worktree, "at": DEFAULT_NOW,
                }],
                "prior_attempt": None, "result": None, "finished_at": None,
                "result_source": None, "handoff_path": None, "phase": 1,
                "last_progress_at": DEFAULT_NOW, "phase_action": "handoff",
                "phase_inputs": expected_inputs,
            }
            expected_state = {
                "schema_version": 1, "run_id": run_id,
                "created_at": DEFAULT_NOW, "updated_at": DEFAULT_NOW,
                "issues": {"14": {
                    "issue": 14, "attempts": [expected_attempt],
                    "outcome": None,
                }},
            }
            expected_bytes = (json.dumps(
                expected_state, sort_keys=True, separators=(",", ":")
            ) + "\n").encode()
            self.assertEqual(result, expected_attempt)
            self.assertEqual(self.state_path.read_bytes(), expected_bytes)

def test_phase_action_validation_is_bound_to_run_identity(self):
    self.run_id = "dispatcher-corruption"
    self.init_run()
    self.spawn(issue=14, worktree=self.root / "dispatcher-worktree")
    self.progress(
        issue=14, phase=1, turn_count=118, context_tokens=20000,
        remainder_self_contained=True,
    )
    state = self.read_state()
    state["issues"]["14"]["attempts"][0]["phase_action"] = "delegate"
    self.state_path.write_text(json.dumps(state), encoding="utf-8")
    before = self.state_path.read_bytes()
    rejected = self.control_raw(
        now=DEFAULT_NOW, issues=[14], tracker=[self.tracker_fact(14)],
        worktrees=[], max_parallel=1, ok=False,
    )
    self.assertIn("phase action does not match persisted inputs", rejected.stderr)
    self.assertEqual(self.state_path.read_bytes(), before)

    owner = self.acquire_direct(issue=73)
    self.run_id = owner["run_id"]
    self.progress(
        issue=73, phase=1, now="2026-08-20T10:05:00Z",
        turn_count=118, context_tokens=20000,
        remainder_self_contained=True,
    )
    direct_path = self.direct_state_path(owner["run_id"])
    state = json.loads(direct_path.read_text())
    state["issues"]["73"]["attempts"][0]["phase_action"] = "handoff"
    direct_path.write_text(json.dumps(state), encoding="utf-8")
    before = direct_path.read_bytes()
    rejected = self.direct_owner_raw(
        issue=73, now="2026-08-20T10:06:00Z", ok=False,
    )
    self.assertIn("phase action does not match persisted inputs", rejected.stderr)
    self.assertEqual(direct_path.read_bytes(), before)
```

- [ ] **Step 2: Run the focused tests and watch the direct contract fail**

Run: `python3 home/common/agent-skills/tests/test_workflow_state.py WorkflowStateLifecycleTest.test_direct_progress_uses_complete_artifact_first_precedence WorkflowStateLifecycleTest.test_non_direct_phase_order_and_ledger_bytes_remain_exact WorkflowStateLifecycleTest.test_phase_action_validation_is_bound_to_run_identity -v`

Expected: FAIL in the direct cases because the base selector returns `handoff` before `delegate`; the exact non-direct compatibility case passes.

- [ ] **Step 3: Make phase selection and revalidation run-aware**

Change `select_phase_action` to require `run_id: str`. Derive module-owned direct policy with `DIRECT_RUN_ID_PATTERN.fullmatch(run_id)` and implement the two complete orders from D1 without changing `PHASE_INPUT_FIELDS`. Thread `run_id` into `validate_attempt` from `validate_state`, and re-derive the stored action with that identity.

In `command_progress`, validate the phase-input object as today, select with `args.run_id`, retain the existing locked state/identity/deadline checks, and persist the unchanged input object and selected action. The selector still never receives or mutates the attempt deadline.

Append an issue-74 amendment marker to the issue-33 spec's accepted phase-order statement. It must state that issue 74 adds a reserved module-owned direct exception whose self-contained remainder delegates before usage, while the issue-33 order remains the complete non-direct order. Update the live selector docstring to describe these two actual orders.

- [ ] **Step 4: Verify the scoped lifecycle contract**

Run: `python3 home/common/agent-skills/tests/test_workflow_state.py WorkflowStateLifecycleTest.test_direct_progress_uses_complete_artifact_first_precedence WorkflowStateLifecycleTest.test_non_direct_phase_order_and_ledger_bytes_remain_exact WorkflowStateLifecycleTest.test_phase_action_validation_is_bound_to_run_identity WorkflowStateLifecycleTest.test_progress_action_precedence_and_complete_inputs_are_persisted WorkflowStateLifecycleTest.test_delegate_requires_measured_usage_below_both_ceilings -v`

Expected: PASS; the first and identity-validation tests prove the direct exception, while the compatibility and existing precedence tests prove non-direct bytes/order did not move.

Run: `git diff --check -- home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py .claude/specs/2026-08-17-workflow-lifecycle-hardening-design.md`

Expected: exit 0 with no output; any whitespace error or edit outside these owned files leaves the task incomplete.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_workflow_state.py .claude/specs/2026-08-17-workflow-lifecycle-hardening-design.md
git commit -m "feat(issue-74): select direct phase actions by run identity" -m "Co-Authored-By: Codex <noreply@openai.com>"
```
