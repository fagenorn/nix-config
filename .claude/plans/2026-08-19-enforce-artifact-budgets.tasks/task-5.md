# Task 5: Close the orchestration contract and run repository gates

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/skills/from-issue/standards-review.md`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify/Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1 checker and exact producer/SDD/ship-handoff/ship-summary validators/results/behavioral fixtures; Task 2 plan package/report; Task 3 review-package report; Task 4 design/grill/handoff reports; D5, D6, D7, D10, and D11.
- Produces: phase boundaries that accept exact three-field producer reports and accept `complete` only with `within_budget` and all four integers; Phase-7 handoff fields `spec_artifact` and `plan_artifact`, each root plus compact metrics/status, plus fixed lifecycle scalars and policy-bounded `notes`; ship-time checker validation and plan-member artifact exclusions.
- Preserves the terminal lifecycle result keys (`issue`, `state`, `pr_url`, `merge_sha`, `issue_closed`, `discussion_items`, `notes`) but requires `discussion_items` to be exactly `[]`; review detail remains behind its ledger/report path and bounded notes carry only a pointer/synopsis. The former Phase-7 `summary` is removed.

**Invariants:**
- From-issue validates each producer's closed state/status combination, then independently invokes the checker against the reported root before persisting phase progress or dispatching the next phase. A claim mismatch, missing helper, checker exit 2, or missing/non-integer metric is `failed`; over budget follows the producer's truthful terminal state and never advances.
- The autonomous design and plan prompts require the new fixed report fields. The orchestrator holds returned root/metrics only, never member lists or artifact contents.
- Phase 5 rechecks both the full plan package and the spec after every accepted edit/ledger append. It uses the owning producer's remediation and returns `decompose_required` rather than dispatching SDD when the final check is over.
- SDD parses every review-package command report, passes root/metrics to the intended reviewer, and never dispatches on `decompose_required`/`failed`. Its final phase report remains compact and does not inline transient review evidence.
- The ship handoff carries current spec/plan roots and metrics. Ship-issue rechecks both on entry and after any writer changes either artifact; a stale/mismatched/over-budget artifact prevents merge.
- Per D10, ship-issue discovers checker-validated plan members locally and supplies root plus each member as individual `--artifact-path` arguments to `diff-scope`. No public report or prompt carries that list, and the existing ≤1,000-line/≤20-file gate is otherwise unchanged.
- Small fixture cases complete; oversized fixture cases map exactly to design/grill `decompose_required`, planning `decompose_required`, handoff `stopped`, and review-package `decompose_required`. `complete` plus `over_budget` is always a contract error.
- SDD's final phase report has exactly `state`, `review_state`, `conformance_verdict`, `correctness_verdict`, `verification_state`, `base_sha`, `head_sha`, `report_path`, and policy-bounded `notes`; parked-finding or verdict-detail lists are rejected and their detail remains at `report_path`.
- Every phase and ship report rejects `decisions`, `open_items`, `adr_paths`, and `summary`; `validate_ship_summary` rejects non-empty `discussion_items`. Numeric notes enforcement comes only from the shared policy/report validators.

- [ ] **Step 1: Add failing end-to-end workflow contract assertions**

Add these methods to `WorkflowSkillContractsTest`; load the two Task 1 descriptors into `small_budget_fixture` and `oversized_budget_fixture` during class setup:

```python
def test_from_issue_validates_artifacts_before_every_phase_advance(self):
    self.assert_ordered(self.from_issue, "validate the returned state", "artifact-budget check",
                        "compare all four metrics", "workflow-state progress")
    self.assertIn("complete with anything other than within_budget", self.from_issue)
    self.assertIn("missing or non-integer metric", self.from_issue)
    self.assertIn("checker exit 2", self.from_issue)
    self.assertIn("independently run the checker", self.from_issue)

def test_autonomous_reports_and_ship_handoff_are_root_plus_metrics(self):
    for text in (self.auto, self.ship_handoff):
        for field in ("state", "artifact", "kind", "path", "metrics", "budget_status"):
            self.assertIn(field, text)
    self.assertIn("spec_artifact", self.ship_handoff)
    self.assertIn("plan_artifact", self.ship_handoff)
    self.assertIn("never carry task member paths", self.ship_handoff)
    self.assertIn("never inline artifact contents", self.auto)
    for forbidden in ("decisions:", "open_items:", "adr_paths:", "summary:"):
        self.assertNotRegex(self.auto, rf"(?m)^\s*{re.escape(forbidden)}")
        self.assertNotRegex(self.ship_handoff, rf"(?m)^\s*{re.escape(forbidden)}")
    self.assertIn("discussion_items: []", self.ship_handoff)
    self.assertIn("phase_reports.notes_max_characters", self.ship_handoff)
    self.assertIn("validate_ship_handoff", self.ship_handoff)
    self.assertIn("validate_ship_summary", self.ship_handoff)

def test_sdd_report_is_exact_and_mechanically_validated(self):
    for field in ("state", "review_state", "conformance_verdict",
                  "correctness_verdict", "verification_state", "base_sha",
                  "head_sha", "report_path", "notes"):
        self.assertIn(field, self.sdd)
    self.assertIn("validate_sdd_report", self.sdd)
    for forbidden in ("parked_findings:", "verdict_details:", "open_items:", "summary:"):
        self.assertNotRegex(self.sdd, rf"(?m)^\s*{re.escape(forbidden)}")

def test_phase_five_remeasures_every_artifact_it_mutates(self):
    self.assert_ordered(self.standards_review, "apply blocking fixes", "final mutation",
                        "artifact-budget check", "decompose_required")
    self.assertIn("check the spec too when its decision ledger changed", self.standards_review)
    self.assertIn("do not dispatch SDD", self.standards_review)

def test_ship_expands_validated_plan_only_for_diff_scope_exclusion(self):
    self.assert_ordered(self.ship_issue, "artifact-budget check", "discover the plan members",
                        "diff-scope", "--artifact-path")
    self.assertIn("one argument for the plan root and each discovered member", self.ship_issue)
    self.assertIn("≤1,000 product lines", self.ship_issue)
    self.assertIn("≤20 product files", self.ship_issue)
    self.assertIn("do not put the member list in the handoff", self.ship_issue)

def test_fixture_producer_states_supplement_behavioral_cli_cases(self):
    self.assertTrue(all(item["expected"]["producer_state"] == "complete"
                        for item in self.small_budget_fixture["artifacts"]))
    expected = {(item["kind"], item["case"]): item["expected"]["producer_state"]
                for item in self.oversized_budget_fixture["artifacts"]}
    self.assertEqual(expected[("design-spec", "root-plus-one")], "decompose_required")
    self.assertEqual(expected[("implementation-plan", "ninth-member")], "decompose_required")
    self.assertEqual(expected[("handoff", "root-plus-one")], "stopped")
    self.assertEqual(expected[("review-package", "member-plus-one")], "decompose_required")
    for text in (self.from_issue, self.auto, self.sdd):
        self.assertIn("complete", text)
        self.assertIn("within_budget", text)
        self.assertIn("contract error", text)
```

If existing class attributes use different names, add the exact paths and decoded fixture values without changing the assertions' meaning. These static assertions only pin routing prose; Task 1 must first materialize and execute every descriptor through the CLI, and Task 3 remains the review generator's behavioral seam.

- [ ] **Step 2: Run the workflow suite and observe missing caller validation**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: FAIL because current phase schemas carry paths without budget states/metrics, Phase 5 can amend artifacts without rechecking, and ship excludes only the plan root.

- [ ] **Step 3: Wire producer reports through callers and final writers**

Update `from-issue`'s structured-report and phase rules to call `validate_producer_report`, validate state/status/metrics, run its own checker, and stop before progress/dispatch on mismatch. Update both autonomous report schemas to exactly `state`, `artifact`, and policy-bounded `notes`; remove `spec_path`, `plan_path`, `adr_paths`, `decisions`, and `open_items` because `artifact.path` replaces the root fields. Keep the caller context bounded to reports and paths.

Update `standards-review` so every accepted plan edit triggers a final plan-package check and every ledger/spec edit triggers a spec check. Apply the existing owner remediation once; unresolved oversize becomes `decompose_required` and returns to the decomposition checkpoint rather than Phase 6.

Update SDD's review-package handling to parse command JSON, compare its root/status/metrics with a checker result, and stop review dispatch truthfully on exit 2/3. Its final report uses the exact nine-field schema above and calls `validate_sdd_report` before return—no parked-findings or verdict-detail lists. From-issue validates it again before constructing Phase 7.

Update `ship-handoff` with the exact fixed lifecycle scalars, current spec/plan artifact objects, and policy-bounded `notes`; delete its one-paragraph `summary`, and call `validate_ship_handoff` before dispatch. Require the ship return's legacy `discussion_items` to be `[]`, with any detail left in its review/ledger path and only a bounded synopsis in notes, and call `validate_ship_summary` before accepting the terminal result. In `ship-issue`, recheck both roots at preflight and after a ship-time mutation. For the existing degradation measurement only, enumerate the checker-validated plan sibling directory and add one literal `--artifact-path` per root/member; keep all current product thresholds, exclusions, and full-review routing unchanged.

- [ ] **Step 4: Run plan-level consistency and repository acceptance gates**

Run: `just agent-workflow-tests`

Expected: PASS; the checker CLI, plan adapter, review generator, producer/caller contracts, and small/oversized fixture transitions are all green with no failures/errors.

Run: `just build`

Expected: PASS; Home Manager/Nix evaluation installs the executable module, importable module, policy, and updated complete skill directories. A missing installed path or evaluation error fails the task.

Run: `git diff --check 416e7a92795a282c1b8cdd71e35a0f570cd35e56..HEAD -- home/common/agent-skills home/common/claude-code/skills Justfile`

Expected: exit 0 with no output; the pathspec excludes planning artifacts while covering every implementation file owned by Tasks 1–5.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue \
  home/common/agent-skills/skills/ship-issue/SKILL.md \
  home/common/agent-skills/skills/sdd/SKILL.md \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-49): enforce artifact budgets across workflow" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
