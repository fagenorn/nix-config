# Task 3: Enforce the Reviewed-Plan Implementation-Owner Rollover

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the persisted direct-owner `owner` object, reviewed/committed design and implementation-plan root artifacts with current four-metric checker results, the Phase-5 `workflow-state progress` response, existing `sdd` producer report, Phase-7 ship-owner contract, ship-summary validator, and terminal `finish` CLI.
- Produces: one direct-autonomous Phase-5 delegation prompt containing exactly the unchanged owner object, `reviewed_head_sha`, `spec_artifact`, and `plan_artifact`; a fresh implementation owner that enters at Phase 6 and returns the canonical terminal JSON printed by `finish`; byte-for-byte relay by the earlier controller.

**Invariants:**
- Per D3, rollover occurs only after all Blocking and accepted Should-fix findings are dispositioned, review edits/ledger writes are committed, both artifact roots are freshly `within_budget`, and Phases 6–7 are self-contained.
- The earlier controller records completed Phase 5 with `next_needs_context=false`, `artifacts_sufficient=true`, and `remainder_self_contained=true`, requires persisted `delegate`, and dispatches exactly one fresh issue owner.
- Per D4/D7/D10, the continuation is one closed object with exactly `owner`, `reviewed_head_sha`, `spec_artifact`, and `plan_artifact`; tests separately prove the exact nested field sets, delegated-owner duties, and earlier-controller stop.
- The fresh owner verifies matching worktree/branch, clean current HEAD equal to `reviewed_head_sha`, tracked roots at that exact commit, independent checker results, and all four metric values before reading artifacts; it adopts the envelope without `direct-owner` and enters Phase 6.
- Per D11, the fresh owner records Phase 6 and fulfills `delegate` through the existing fresh ship owner, then records Phase 7 and fulfills its ledger-only `delegate` through the exact finish bookkeeper. The earlier controller's post-delegation action set is closed to ship-summary validation, byte relay, and stop.
- Per D9, mechanical-only module-owned direct autonomous runs use this same mandatory rollover, then the fresh owner invokes the existing mechanical Phase-6 mechanic/reviewer route.
- Dispatcher-owned autonomous, explicitly durable interactive, ledger-free interactive, and direct pre-Phase-5 action handling remain unchanged.

**Task-start baseline:** Before editing, run `test -z "$(git status --porcelain=v1)" && git rev-parse --verify HEAD`. Expected: exit 0 and one baseline SHA; non-empty status fails the task start. Keep `HEAD` at this baseline until the task's final verification so its tracked, staged, and untracked comparison excludes every earlier task commit.

- [ ] **Step 1: Write the failing installed-skill contract test**

Add this complete method to `WorkflowSkillContractsTest`:

```python
def test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner(self):
    transfer = self.section(
        self.auto,
        "#### Mandatory transfer gate",
        "#### Fresh delegated owner",
    )
    delegated = self.section(
        self.auto,
        "#### Fresh delegated owner",
        "#### Earlier controller stop",
    )
    earlier = self.section(
        self.auto,
        "#### Earlier controller stop",
        "### Other Phase 5–7 routes",
    )
    self.assert_ordered(
        transfer,
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
    match = re.search(r"```json\n(\{.*?\})\n```", transfer, re.DOTALL)
    self.assertIsNotNone(match)
    continuation = json.loads(match.group(1))
    self.assertEqual(set(continuation), {
        "owner", "reviewed_head_sha", "spec_artifact", "plan_artifact",
    })
    self.assertEqual(set(continuation["owner"]), {
        "interface_version", "kind", "ledger_repo_root", "run_id", "issue",
        "attempt", "owner", "action_id", "launch_kind", "worktree",
        "handoff_path", "deadline_at",
    })
    self.assertEqual(continuation["owner"]["kind"], "owner")
    self.assertRegex(continuation["reviewed_head_sha"], r"^[0-9a-f]{40}$")
    artifact_fields = {"kind", "path", "metrics", "budget_status"}
    metric_fields = {
        "root_bytes", "total_bytes", "file_count", "largest_member_bytes",
    }
    for block, kind in (
        ("spec_artifact", "design-spec"),
        ("plan_artifact", "implementation-plan"),
    ):
        artifact = continuation[block]
        self.assertEqual(set(artifact), artifact_fields)
        self.assertEqual(artifact["kind"], kind)
        self.assertEqual(set(artifact["metrics"]), metric_fields)
        self.assertTrue(all(type(value) is int
                            for value in artifact["metrics"].values()))
        self.assertEqual(artifact["budget_status"], "within_budget")
    for excluded in (
        "no artifact contents", "no task-member paths", "no review transcript",
        "no conversation summary", "no alternate worktree",
        "no reconstructed lifecycle field", "no authorization flag",
    ):
        self.assertIn(excluded, transfer)
    self.assertIn("mechanical-only direct autonomous", transfer)
    self.assert_ordered(
        delegated,
        "verify that the worktree and branch match the owner envelope",
        "current clean HEAD",
        "equal `reviewed_head_sha`",
        "both roots are tracked at that exact reviewed HEAD",
        "independently run `artifact-budget check`",
        "compare all four metrics",
        "adopt the owner envelope",
        "must not call `direct-owner`",
        "begin at Phase 6",
        "invoke `sdd`",
        "completed Phase 6",
        "remainder_self_contained=true",
        "persisted action `delegate`",
        "fresh Phase-7 ship owner",
        "must not dispatch a second issue owner",
        "completed Phase 7",
        "ledger-only remainder",
        "ledger-only bookkeeper",
        "exact `workflow-state finish` command",
        "return only the exact canonical JSON",
    )
    self.assertIn("existing mechanical Phase-6 mechanic/reviewer route", delegated)
    self.assert_ordered(
        earlier,
        "received bytes",
        "artifact-budget validate-report --boundary ship-summary",
        "relay the canonical bytes unchanged",
        "stop",
    )
    self.assertIn(
        "post-delegation action set is exactly validate, relay, and stop",
        earlier,
    )
    affirmative_permission = re.compile(
        r"\b(?:may|can|could|must|should|is allowed to|is authorized to|is permitted to)\s+(?:"
        r"invoke `sdd`|edit implementation files|reacquire|"
        r"call `direct-owner`|(?:start|create) (?:a )?new attempt|"
        r"dispatch (?:a )?second (?:replacement )?owner|"
        r"call `workflow-state finish` after delegation|"
        r"continue after (?:the )?delegated report)",
        re.IGNORECASE,
    )
    self.assertIsNone(affirmative_permission.search(earlier))
    for denial in (
        "does not invoke `sdd`", "does not edit implementation files",
        "does not reacquire or call `direct-owner`",
        "does not start or create a new attempt", "does not dispatch a second owner",
        "does not call `workflow-state finish` after delegation",
        "does not continue after the delegated report",
    ):
        self.assertIn(denial, earlier)
    self.assertIn("dispatch failure", earlier)
    self.assertIn("never permission to implement locally", earlier)

    other_start = self.auto.index("### Other Phase 5–7 routes")
    other = self.auto[other_start:]
    self.assertIn(
        "Mechanical-only module-owned direct autonomous runs are excluded from this section",
        other,
    )
    self.assertIn("mechanical-only ordering and ownership for other acquisition routes", other)

    phase_gate = self.section(
        self.from_issue,
        "## Dispatch, phase-budget and attempt-budget rules",
        "## Terminal return procedure",
    )
    self.assertIn("mandatory direct-autonomous Phase-5 rollover", phase_gate)
    self.assertIn("AUTO.md", phase_gate)
    self.assertIn("all other acquisition modes", phase_gate)
    self.assertIn("post-rollover Phase-6 and Phase-7 gates", phase_gate)
    self.assertIn("unchanged", phase_gate)
```

- [ ] **Step 2: Run the contract test and watch the rollover section fail**

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py WorkflowSkillContractsTest.test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner -v`

Expected: FAIL because the base `AUTO.md` has no mandatory direct implementation-owner rollover section and still describes Phases 5–7 as unchanged.

- [ ] **Step 3: Specify the mandatory checkpoint and bounded continuation**

In `AUTO.md`, replace the current direct-autonomous Phase-5–7 summary with `### Mandatory direct implementation-owner rollover` followed by `### Other Phase 5–7 routes`.

The mandatory section must contain three level-four seams, in order: `#### Mandatory transfer gate`, `#### Fresh delegated owner`, and `#### Earlier controller stop`. Encode this executable behavior per D3–D4, D7, and D9–D11:

1. In `Mandatory transfer gate`, finish dispositioning Phase-5 findings; commit the reviewed plan and any ledger edit. Run fresh design-spec and implementation-plan checks after the last mutation, retain all four metrics, and repeat check/commit if a hook changes either artifact. Require a clean worktree and capture its full lowercase 40-hex HEAD as `reviewed_head_sha`. With no conversational dependency remaining, call `workflow-state progress` for completed Phase 5 using the three exact booleans and truthful available usage. Require persisted `delegate`, then dispatch exactly one fresh issue owner at the existing `from-issue-phase-delegate` tier. State explicitly that this includes mechanical-only direct autonomous runs.
2. Put one valid representative JSON object in that subsection. Its top-level fields are exactly `owner`, `reviewed_head_sha`, `spec_artifact`, and `plan_artifact`; `owner` has exactly the twelve canonical direct-owner fields asserted by the test; `reviewed_head_sha` is a full lowercase 40-hex commit; each artifact has exactly `kind`, `path`, `metrics`, and `budget_status`; each `metrics` object has exactly the four asserted integer fields; kinds are `design-spec`/`implementation-plan` and both statuses are `within_budget`. State every excluded continuation field named in the invariants. Repository bindings are re-resolved in the delegated worktree.
3. In `Fresh delegated owner`, require worktree/branch validation, clean-HEAD equality with `reviewed_head_sha`, tracked roots at that exact commit, independent checks and four-metric comparison before artifact reads, envelope adoption without acquisition, and Phase-6 entry. After validating SDD, record Phase 6 with the self-contained booleans, require `delegate`, and fulfill it through the existing fresh Phase-7 ship owner without a second issue owner. After validating the ship report, record Phase 7 with the exact finish command as the ledger-only remainder, require `delegate`, and fulfill it through the existing bookkeeper. Return canonical finish stdout. For mechanical-only direct autonomous work invoke the existing mechanical Phase-6 mechanic/reviewer route without changing that route's order or ownership.
4. In `Earlier controller stop`, define its closed post-delegation action set as exactly validate, relay, and stop. After ship-summary validation it relays bytes and stops. Use the exact negative sentences pinned by the test so no affirmative permission exists to invoke SDD, edit implementation, reacquire/call `direct-owner`, start an attempt, dispatch a second owner, call `finish`, or continue after the delegated report. Only dispatch failure may be terminally persisted; it never enables local implementation.

In `SKILL.md`'s phase-action rules, point the direct-autonomous Phase-5 `delegate` case and its post-rollover Phase-6/7 action routing to this mandatory `AUTO.md` contract, state that all other acquisition modes retain the existing generic action semantics, and ensure the generic terminal procedure cannot be misread as authorizing a second `finish` after the delegated owner returned canonical terminal bytes.

The `### Other Phase 5–7 routes` section must explicitly say `Mechanical-only module-owned direct autonomous runs are excluded from this section` because they rolled above. It retains the existing dispatcher-owned autonomous, explicit durable interactive, ledger-free interactive, reviewer, SDD, and shipping behavior, and must use the phrase `mechanical-only ordering and ownership for other acquisition routes` to make that compatibility boundary executable in the test.

- [ ] **Step 4: Verify the installed skill and repository distribution gates**

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py WorkflowSkillContractsTest.test_direct_auto_phase_five_rolls_to_one_fresh_implementation_owner WorkflowSkillContractsTest.test_owner_persists_exact_terminal_result_before_return WorkflowSkillContractsTest.test_owner_has_executable_phase_gate_and_action_semantics WorkflowSkillContractsTest.test_adjacent_from_issue_acquisition_modes_remain_unchanged WorkflowSkillContractsTest.test_auto_mode_never_skips_durable_checkpoints_or_terminal_writes -v`

Expected: PASS; the new direct rollover is ordered and bounded while the existing acquisition/terminal contracts remain green.

Run: `just agent-workflow-tests`

Expected: exit 0 with every deterministic lifecycle and installed-skill contract passing; any failed test leaves the task incomplete.

Run: `just build`

Expected: exit 0 and a successful Nix build of the current host configuration; a build failure means the helper and installed skill documentation have not passed the distribution gate.

Run: `git diff --check -- home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: exit 0 with no output; any whitespace error in these owned files leaves the task incomplete.

Run: `bash -c 'set -euo pipefail; allowed=$(mktemp); actual=$(mktemp); trap '\''rm -f "$allowed" "$actual"'\'' EXIT; printf "%s\n" "home/common/agent-skills/skills/from-issue/SKILL.md" "home/common/agent-skills/skills/from-issue/AUTO.md" "home/common/agent-skills/tests/test_workflow_skill_contracts.py" | LC_ALL=C sort -u >"$allowed"; { git diff --name-only HEAD --; git ls-files --others --exclude-standard; } | LC_ALL=C sort -u >"$actual"; unexpected=$(comm -23 "$actual" "$allowed"); if [ -n "$unexpected" ]; then printf "unexpected current-task path: %s\n" "$unexpected"; exit 1; fi'`

Expected: exit 0 with no output. The command compares all tracked, staged, and untracked current-task edits with the exact `Files:` set; an outside path is printed and fails, while commits completed by earlier tasks are already in `HEAD` and are not graded.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-74): roll reviewed implementation to a fresh owner" -m "Co-Authored-By: Codex <noreply@openai.com>"
```
