# Task 7: Prose single truth, re-entry lines, contract tests

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (Standing authorization, lines ~54–56)
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (Notes line ~397; Terminal return procedure ~249–259; phase-gate/handoff bullets ~193–217)
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md` (authorization-inference block ~10–16; add suspension guidance)
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (run-id selection ~top; wait handling ~148–172; Final report ~173–183)
- Modify: `home/common/claude-code/skills/orchestrate-issues/evals/evals.json` (only if its expected outputs pin the replaced wait wording)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's `suspend` subcommand + envelope (`reentry` field), Task 4's summary `blocked_on` + finalize-over-deadline-less-wait, Task 5's guard scope, the canonical stop line (Global Constraints, D14).
- Produces — exact prose contracts (each backed by a new test):
  1. **Shared authorization sentence** — this literal appears in BOTH ship-issue/SKILL.md (replacing the line-56 claim) and from-issue/SKILL.md (replacing the line-397 tail): `Standing authorization exists exactly where the lifecycle guard grants it: pushing a non-default branch, opening a PR to the default branch, and the guarded merge, in fagenorn-owned repositories; everywhere else these commands stay per-action gated — suspend with blocked_on=human_gate and print the re-entry line instead of dying at the prompt.` ship-issue keeps its byte-identical `gh pr merge <pr-num> --repo <repoSlug> --merge [--subject "<rendered mergeSubjectTemplate>"] --delete-branch` rendering in an adjacent sentence (the existing byte-identity test must keep passing).
  2. **Suspension procedure** (new subsection in from-issue/SKILL.md beside the Terminal return procedure, referenced from AUTO.md): when to suspend (imminent quota/session limit, repeated transport failure, a permission prompt only a human can approve, an external wait), the exact call `workflow-state suspend --repo-root <ledger_repo_root> --run-id <run-id> --now <utc> --issue <n> --attempt <k> --blocked-on <value>`, then print the canonical line `Suspended (blocked_on=<value>). Resume: <reentry from the envelope>` as the final user-facing output, and stop. Suspension is NOT a terminal return: no `finish` call, no result JSON.
  3. **Distinction sentence** (same subsection, verbatim): `Handoff is the deliberate context rollover with a handoff document; suspension is the environmental pause with none.`
  4. **Re-entry relay**: the Terminal return procedure gains one line — a terminal replay envelope's `reentry` field is printed to the user verbatim on its own line.
  5. **orchestrate-issues run reuse** (per D13, replacing the pick-a-fresh-dated-name instruction): before `init-run`, list `<ledger_repo_root>/.superpowers/workflows/` for an existing run whose state covers the same issue set and has any non-final attempt or missing outcome; reuse that run id; only otherwise mint a new one.
  6. **orchestrate-issues wait rule** (replacing the "optional deadline" wording at ~166): `control never returns a deadline-less wait; every wait carries deadline_at, and when nothing can proceed without a human, control returns finalize instead.` The Final report section adds two columns sourced from finalize summaries: `blocked_on` and a re-entry line — `/from-issue <issue> --auto` for issues suspended on a human gate, the orchestrate re-invocation itself for the run.
  7. **AUTO.md**: the denial-of-inference block (~10–16) gains one clarifying sentence: resuming a `suspended` attempt requires neither `new_run` nor `owner_unavailable` — suspension is not a terminal replay. The Phase-5/ship sections reference the suspension procedure at the push/merge gates.
- Produces — contract-test changes in `test_workflow_skill_contracts.py`:
  - New: `test_authorization_truth_is_single_and_shared` (the exact shared sentence appears in both files; `assertNotIn("Don't re-prompt for `git push`", ship_issue)`); `test_suspension_procedure_pins_verb_line_and_distinction` (the `workflow-state suspend` call, the canonical line template `Suspended (blocked_on=`, the distinction sentence, and `assert_ordered` suspend-before-stop); `test_orchestrate_reuses_nonfinal_runs` (the reuse instruction, and `assertNotRegex` on any instruction to always mint dated fresh ids); `test_no_deadline_less_wait_is_armed` (the wait rule sentence; `assertNotIn("and optional deadline", orchestrate)`); `test_terminal_replay_relays_reentry` (the relay line in the Terminal return procedure).
  - Updated (repoint, never delete): `test_from_issue_routes_a_deadline_rejected_progress_to_the_terminal_return` (~981) — a deadline-expired attempt now surfaces as a suspension, so the anchor becomes the suspension route; `test_dispatcher_is_a_control_adapter_not_a_policy_owner` (~118) and `test_orchestrate_evals_grade_control_and_reject_retired_policy` (~995) — verify the new wording introduces no retired-policy vocabulary and update `evals/evals.json` expected outputs if they pin the old wait wording; `test_ship_issue_merge_is_bound_to_the_resolved_repository` (~1459) — keep all three byte-identical merge renderings intact through the rewrite; `test_direct_auto_authorizations_are_explicit_and_never_inferred` (~941) — extend its anchor set with the suspension-resume clarification.

**Invariants:**
- No skill file retains a claim of standing authorization for push/PR/merge that is not scoped to the guard (per D4); `grep -rn "Don't re-prompt" home/common/agent-skills/skills/ship-issue/` returns nothing after the task.
- The closed control action set in prose stays exactly `spawn | resume | retry | wait | finalize` (per D12 — no `yield`).
- `new_run`/`owner_unavailable` denial-of-inference text is extended, not weakened (per D5).
- Every edit keeps the full contract suite green — the suite is the reviewer of record for prose.

- [ ] **Step 1: Write the failing tests** — add the five new tests above to `WorkflowSkillContractsTest` using the suite's own idioms (`assertIn` on exact literals from Produces; `section()` to scope; `assert_ordered` for sequencing). Test code for the sharpest one:

```python
def test_authorization_truth_is_single_and_shared(self):
    sentence = (
        "Standing authorization exists exactly where the lifecycle guard grants it: "
        "pushing a non-default branch, opening a PR to the default branch, and the "
        "guarded merge, in fagenorn-owned repositories; everywhere else these commands "
        "stay per-action gated — suspend with blocked_on=human_gate and print the "
        "re-entry line instead of dying at the prompt."
    )
    self.assertIn(sentence, self.ship_issue)
    self.assertIn(sentence, self.from_issue)
    self.assertNotIn("Don't re-prompt for `git push`", self.ship_issue)
    self.assertNotIn("Push, PR open/merge, force-push, and hook bypass stay per-action gated.",
                     self.from_issue)
```

- [ ] **Step 2: Run and watch them fail**

Run: `python3 -m unittest -v -k authorization_truth -k suspension_procedure -k reuses_nonfinal -k deadline_less -k relays_reentry home/common/agent-skills/tests/test_workflow_skill_contracts.py` (one per `-k`)
Expected: FAIL — all five anchors absent.

- [ ] **Step 3: Edit the four skill files** per Produces. Smallest sufficient diffs; keep every existing anchored phrase you are not deliberately replacing (run the suite after each file to catch collateral anchor breaks early).

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py && just agent-workflow-tests`
Expected: PASS — the full contract suite (89+ tests) and the whole workflow suite.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/claude-code/skills/orchestrate-issues/evals/evals.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(agent-skills): single authorization truth, suspension procedure, and re-entry prose contracts"
```

(Drop the evals.json path from the add list if it needed no change.)

**Verification (falsifiable):** at base, `if grep -q "Standing authorization exists exactly where the lifecycle guard grants it" home/common/agent-skills/skills/ship-issue/SKILL.md; then exit 1; fi` passes (sentence absent) while `grep -q "Don't re-prompt" home/common/agent-skills/skills/ship-issue/SKILL.md` succeeds; after the task, both conditions invert and the five new tests pass. Cite: D4, D5, D7, D9, D12, D13, D14.
