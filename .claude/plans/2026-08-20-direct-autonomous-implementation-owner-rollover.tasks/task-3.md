# Task 3: Enforce the Reviewed-Plan Implementation-Owner Rollover

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the persisted direct-owner `owner` object, reviewed/committed design and implementation-plan root artifacts with current four-metric checker results, the Phase-5 `workflow-state progress` response, existing `sdd` producer report, Phase-7 ship-owner contract, ship-summary validator, and terminal `finish` CLI.
- Produces: one direct-autonomous Phase-5 delegation prompt containing exactly the unchanged owner object, `spec_artifact`, and `plan_artifact`; a fresh implementation owner that enters at Phase 6 and returns the canonical terminal JSON printed by `finish`; byte-for-byte relay by the earlier controller.

**Invariants:**
- Per D3, rollover occurs only after all Blocking and accepted Should-fix findings are dispositioned, review edits/ledger writes are committed, both artifact roots are freshly `within_budget`, and Phases 6–7 are self-contained.
- The earlier controller records completed Phase 5 with `next_needs_context=false`, `artifacts_sufficient=true`, and `remainder_self_contained=true`, requires persisted `delegate`, and dispatches exactly one fresh issue owner.
- Per D4, the continuation carries the exact closed owner fields and only two root-plus-metrics artifact objects; it contains no transcript, artifact contents, member paths, alternate worktree, reconstructed lifecycle value, or authorization flag.
- The fresh owner verifies matching worktree/branch, clean current HEAD, tracked roots, independent checker results, and all four metric values before reading artifacts; it adopts the envelope without `direct-owner` and enters Phase 6.
- The fresh owner owns SDD, fresh Phase-7 shipping, report validation, the single `finish`, and exact canonical return. The earlier controller only validates/relays those bytes and never writes `finish` again.
- Dispatcher-owned autonomous, explicitly durable interactive, ledger-free interactive, and direct pre-Phase-5 action handling remain unchanged.

- [ ] **Step 1: Write the failing installed-skill contract test**

Add this complete method to `WorkflowSkillContractsTest`:

```python
def test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner(self):
    rollover = self.section(
        self.auto,
        "### Mandatory direct implementation-owner rollover",
        "### Other Phase 5–7 routes",
    )
    self.assert_ordered(
        rollover,
        "dispositioned every Blocking and accepted Should-fix finding",
        "commit",
        "artifact-budget check --kind design-spec",
        "artifact-budget check --kind implementation-plan",
        "within_budget",
        "workflow-state progress",
        "next_needs_context=false",
        "artifacts_sufficient=true",
        "remainder_self_contained=true",
        "delegate",
        "exactly one fresh issue owner",
    )
    for field in (
        "interface_version", "kind", "ledger_repo_root", "run_id", "issue",
        "attempt", "owner", "action_id", "launch_kind", "worktree",
        "handoff_path", "deadline_at",
    ):
        self.assertIn(field, rollover)
    for block in ("spec_artifact", "plan_artifact"):
        self.assertIn(block, rollover)
    for field in (
        "root_bytes", "total_bytes", "file_count", "largest_member_bytes",
        "budget_status", "within_budget",
    ):
        self.assertIn(field, rollover)
    for excluded in (
        "no artifact contents", "no task-member paths", "no review transcript",
        "no conversation summary", "no alternate worktree",
        "no reconstructed lifecycle field", "no authorization flag",
    ):
        self.assertIn(excluded, rollover)
    self.assert_ordered(
        rollover,
        "verify that the worktree and branch match the owner envelope",
        "current clean HEAD",
        "both roots are tracked",
        "independently run `artifact-budget check`",
        "compare all four metrics",
        "adopt the owner envelope",
        "must not call `direct-owner`",
        "begin at Phase 6",
        "invoke `sdd`",
        "fresh Phase-7 ship owner",
        "workflow-state finish",
        "return only the exact canonical JSON",
    )
    for forbidden_parent_action in (
        "must not invoke `sdd`", "must not edit implementation files",
        "must not reacquire", "must not create a new attempt",
        "must not dispatch a second replacement owner",
        "must not call `workflow-state finish` after delegation",
    ):
        self.assertIn(forbidden_parent_action, rollover)
    self.assert_ordered(
        rollover,
        "received bytes",
        "artifact-budget validate-report --boundary ship-summary",
        "relay the canonical bytes unchanged",
        "stop",
    )
    self.assertIn("dispatch failure", rollover)
    self.assertIn("never permission to implement locally", rollover)

    phase_gate = self.section(
        self.from_issue,
        "## Dispatch, phase-budget and attempt-budget rules",
        "## Terminal return procedure",
    )
    self.assertIn("mandatory direct-autonomous Phase-5 rollover", phase_gate)
    self.assertIn("AUTO.md", phase_gate)
    self.assertIn("all other acquisition modes", phase_gate)
    self.assertIn("unchanged", phase_gate)
```

- [ ] **Step 2: Run the contract test and watch the rollover section fail**

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py WorkflowSkillContractsTest.test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner -v`

Expected: FAIL because the base `AUTO.md` has no mandatory direct implementation-owner rollover section and still describes Phases 5–7 as unchanged.

- [ ] **Step 3: Specify the mandatory checkpoint and bounded continuation**

In `AUTO.md`, replace the current direct-autonomous Phase-5–7 summary with `### Mandatory direct implementation-owner rollover` followed by `### Other Phase 5–7 routes`.

The mandatory section must encode this executable order per D3–D4:

1. Finish dispositioning Phase-5 findings; commit the reviewed plan and any ledger edit. Run fresh design-spec and implementation-plan checks after the last mutation, retain all four metrics, and repeat check/commit if a hook changes either artifact.
2. With no conversational dependency remaining, call `workflow-state progress` for completed Phase 5 using the three exact booleans and truthful available usage. Require the persisted action `delegate`; any other response is a contract failure, not permission to continue.
3. Dispatch exactly one fresh issue owner at the existing issue-owner tier using the existing `from-issue-phase-delegate` route. Give it a standing direct-autonomous/Phase-6 instruction plus three closed machine-shaped blocks: the unchanged complete owner object; `spec_artifact` with kind/path/four metrics/within-budget; and `plan_artifact` with the same shape.
4. State every excluded continuation field named in the invariants. Repository bindings are re-resolved in the delegated worktree.
5. Require the fresh owner to validate its worktree/branch/clean HEAD/tracked roots, independently check and compare both artifacts before reading them, adopt the owner envelope without acquisition, enter Phase 6, validate SDD, launch the existing fresh Phase-7 ship owner, validate the ship report, persist the one terminal `finish`, and return only its canonical stdout.
6. Require the earlier controller to validate the received bytes as `ship-summary`, relay canonical bytes unchanged, and stop. It performs none of the forbidden parent actions in the test. Only a dispatch failure may be terminally persisted by the earlier controller; it never enables local implementation.

In `SKILL.md`'s phase-action rules, point the direct-autonomous Phase-5 `delegate` case to this mandatory `AUTO.md` contract, state that all other acquisition modes retain the existing generic action semantics, and ensure the generic terminal procedure cannot be misread as authorizing a second `finish` after the delegated owner returned canonical terminal bytes.

The `### Other Phase 5–7 routes` section must retain the existing dispatcher-owned autonomous, explicit durable interactive, ledger-free interactive, mechanical-only, reviewer, SDD, and shipping behavior without changing their ordering or ownership.

- [ ] **Step 4: Verify the installed skill and repository distribution gates**

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py WorkflowSkillContractsTest.test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner WorkflowSkillContractsTest.test_owner_persists_exact_terminal_result_before_return WorkflowSkillContractsTest.test_owner_has_executable_phase_gate_and_action_semantics WorkflowSkillContractsTest.test_adjacent_from_issue_acquisition_modes_remain_unchanged WorkflowSkillContractsTest.test_auto_mode_never_skips_durable_checkpoints_or_terminal_writes -v`

Expected: PASS; the new direct rollover is ordered and bounded while the existing acquisition/terminal contracts remain green.

Run: `just agent-workflow-tests`

Expected: exit 0 with every deterministic lifecycle and installed-skill contract passing; any failed test leaves the task incomplete.

Run: `just build`

Expected: exit 0 and a successful Nix build of the current host configuration; a build failure means the helper and installed skill documentation have not passed the distribution gate.

Run: `git diff --check -- home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: exit 0 with no output; any whitespace error or edit outside these owned files leaves the task incomplete.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-74): roll reviewed implementation to a fresh owner" -m "Co-Authored-By: Codex <noreply@openai.com>"
```
