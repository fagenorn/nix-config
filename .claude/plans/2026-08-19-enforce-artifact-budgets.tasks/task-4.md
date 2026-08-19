# Task 4: Enforce budgets in single-file artifact producers

**Files:**
- Modify: `home/common/agent-skills/skills/design/SKILL.md`
- Modify: `home/common/agent-skills/skills/grill-with-docs/SKILL.md`
- Modify: `home/common/agent-skills/skills/handoff/SKILL.md`
- Modify/Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's `artifact-budget check` and `validate_producer_report`; D2, D5, D6, D7, and D11.
- Produces: the same exact three-field report for design, grill, and handoff: `state`, one artifact whose `path` is the spec/handoff root, and policy-bounded `notes`. `spec_path`, `adr_paths`, `decisions`, `open_items`, and free-form `summary` are removed; committed roots/ledgers carry their detail.
- A complete artifact object has `kind`, root `path`, exactly four `metrics`, and `budget_status: within_budget`. Over budget adds sorted closed `violations`; failed measurement includes root path when known and omits fabricated metrics/status.

**Invariants:**
- Design checks the final spec after self-review and commit-ready edits. On over budget it compacts repetition/examples/evidence references without weakening required sections or ledger meaning, rechecks once after that strategy, and returns `decompose_required` with the draft when still over. It never calls the design approved/complete in that state.
- Grill owns remeasurement whenever it changes the spec or decision ledger. It uses the same design compaction/decomposition transition and may not report a clean grill with stale metrics.
- A handoff writes the full candidate before measurement. On over budget it performs one semantic rewrite removing duplicated artifacts/lifecycle/diff/log content, then rechecks. If still over, it returns `stopped` with candidate root/metrics and never installs a caller-provided durable destination.
- Durable handoff candidates are measured as sibling temporary regular files before the existing exclusive-create/atomic-replace operation. Any checker exit 2/3 leaves an old valid destination byte-identical and cleans unpublished temporary names.
- Any mutation after a successful check invalidates metrics and transfers remeasurement to that writer. Producers invoke the checker by stable command, never embed thresholds or use `wc`.
- Reports never inline contents, member lists, policy, logs, or decision-ledger rows; the shared policy alone supplies the notes limit.
- Each producer validates its report against Task 1's module before return; any extra legacy field or notes beyond the shared policy limit is `failed`, never truncated into apparent success.

- [ ] **Step 1: Add failing producer transition and publication-order tests**

Add these methods to `WorkflowSkillContractsTest` after exposing `design`, `grill`, and `handoff` in `setUpClass`:

```python
def test_design_and_grill_measure_after_last_write_and_stop_truthfully(self):
    for producer in (self.design, self.grill):
        self.assert_ordered(producer, "final mutation", "artifact-budget check",
                            "compact repetition", "artifact-budget check",
                            "decompose_required")
        self.assertIn("budget_status: within_budget", producer)
        self.assertIn("root_bytes", producer)
        self.assertIn("largest_member_bytes", producer)
        self.assertNotIn("wc -c", producer)
        self.assertRegex(producer, r"state:.*complete.*decompose_required.*failed")

def test_handoff_measures_candidate_before_durable_replace(self):
    self.assert_ordered(self.handoff, "sibling temporary", "artifact-budget check",
                        "remove duplicated", "artifact-budget check", "stopped")
    self.assert_ordered(self.handoff, "budget_status: within_budget", "atomically replace")
    self.assertIn("leave the existing destination byte-identical", self.handoff)
    self.assertIn("no fabricated metrics", self.handoff)

def test_artifact_reports_are_bounded_root_only_shapes(self):
    for producer in (self.design, self.grill, self.handoff):
        for field in ("kind", "path", "metrics", "budget_status", "notes"):
            self.assertIn(field, producer)
        self.assertIn("phase_reports.notes_max_characters", producer)
        self.assertIn("validate_producer_report", producer)
        self.assertIn("never inline artifact contents", producer)
        for forbidden in ("spec_path:", "adr_paths:", "decisions:", "open_items:", "summary:"):
            self.assertNotRegex(producer, rf"(?m)^\s*{re.escape(forbidden)}")
```

- [ ] **Step 2: Run the contract tests and see missing enforcement**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: FAIL because the three skills currently return paths without final budget checks, fixed metrics, or deterministic over-budget terminal states.

- [ ] **Step 3: Implement exact producer state machines and reports**

In `design`, put final measurement after its fresh-eyes fix pass. Define the exact generate/check/compact/recheck/complete-or-decompose sequence, exact D11 report, report validation, and failed-measurement behavior. Make clear that a later grill or plan ledger append owns a new spec check. Remove transported ADR/decision lists; the artifact root and bounded notes are sufficient routing.

In `grill-with-docs`, preserve glossary/ADR behavior, but make any spec/ledger mutation end in the same design-spec check. Its exact report includes the spec root/metrics and no doc/open-item lists; if the grill did not change the spec, it must still obtain a current check rather than repeat an earlier claim.

In `handoff`, integrate the checker into both temporary and durable routes. Write the candidate once, measure, rewrite once if over, and remeasure. Only an exit-0 result may reach the durable exclusive-create/replace operations. Return the exact complete/stopped/failed report shape, retain an over-budget nondurable candidate for inspection, and never alter an existing durable target on checker failure/oversize.

- [ ] **Step 4: Verify producer ordering and repository workflow contracts**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: PASS; moving a check before final mutation, allowing an over-budget completion, omitting one metric, or publishing before measurement fails at least one assertion.

Run: `just agent-workflow-tests`

Expected: PASS with no regressions in lifecycle or existing skill contracts.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/design/SKILL.md \
  home/common/agent-skills/skills/grill-with-docs/SKILL.md \
  home/common/agent-skills/skills/handoff/SKILL.md \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-49): enforce single-file artifact budgets" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
