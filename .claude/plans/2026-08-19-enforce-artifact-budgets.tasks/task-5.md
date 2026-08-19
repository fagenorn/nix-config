# Task 5: Close the orchestration contract and run repository gates

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/skills/from-issue/standards-review.md`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md`
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify/Test: `home/common/agent-skills/tests/test_workflow_state.py`
- Modify/Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1 checker and `validate-report` CLI; Task 2 plan package/report; Task 3 diff/delivery-detail review-package modes; Task 4 producer reports; D5–D7, D10–D11, and D14–D16.
- Produces: phase boundaries that accept only revalidated canonical JSON; exact D14 SDD report; exact ship handoff with `state`, fixed lifecycle/artifact fields, one `report_path`, and notes; exact terminal ship summary with one `report_path`; ship-time checker validation and plan-member exclusions.
- Preserves terminal keys `issue`, `state`, `pr_url`, `merge_sha`, `issue_closed`, `discussion_items`, `notes`, adds scalar `report_path`, and requires `discussion_items: []` only after any detail has been durably published. The former Phase-7 `summary` is removed.

**Invariants:**
- From-issue pipes every received JSON report through the matching `validate-report --input -` boundary before decoding it, then independently invokes the checker against reported artifact roots. Validator/checker exit 2, a claim mismatch, or missing/non-integer metric is `failed`; over budget never advances.
- The autonomous design and plan prompts require the new fixed report fields. The orchestrator holds returned root/metrics only, never member lists or artifact contents.
- Phase 5 rechecks both the full plan package and the spec after every accepted edit/ledger append. It uses the owning producer's remediation and returns `decompose_required` rather than dispatching SDD when the final check is over.
- SDD parses every review-package command report, passes root/metrics to the intended reviewer, and never dispatches on `decompose_required`/`failed`. Its final phase report remains compact and does not inline transient review evidence.
- The ship handoff carries current spec/plan roots and metrics. Ship-issue rechecks both on entry and after any writer changes either artifact; a stale/mismatched/over-budget artifact prevents merge.
- Per D10, ship-issue discovers checker-validated plan members locally and supplies root plus each member as individual `--artifact-path` arguments to `diff-scope`. No public report or prompt carries that list, and the existing ≤1,000-line/≤20-file gate is otherwise unchanged.
- Small fixture cases complete; oversized fixture cases map exactly to design/grill `decompose_required`, planning `decompose_required`, handoff `stopped`, and review-package `decompose_required`. `complete` plus `over_budget` is always a contract error.
- SDD's final phase report has exactly `state`, `review_state`, `conformance_verdict`, `correctness_verdict`, `verification_state`, `base_sha`, `head_sha`, `report_path`, and policy-bounded `notes`; parked-finding or verdict-detail lists are rejected and their detail remains at `report_path`.
- Resolve `<main-root>` as the parent of absolute `git rev-parse --git-common-dir`, require basename `.git`, and confirm it with `git -C <main-root> rev-parse --show-toplevel`; never use the feature worktree or a path inside `.git`. Before SDD workspace deletion, package every parked/residual finding through Task 3 delivery-detail mode at `<main-root>/.superpowers/issue-delivery/<issue>/<run-or-branch>/sdd-<head>.json`; before ship Phase 8 cleanup, package every Minor/Discussion item at the sibling `ship-review-<head>.json`. Leaves are per-run/branch and no-clobber.
- A non-empty detail set requires a checker-valid durable package and `report_path`; notes contain that exact path. Failure to publish/recheck it returns `failed` or `stopped` and preserves the feature worktree/workspace. With genuinely no detail, `report_path` is null. From-issue rechecks and consumes a non-null path before constructing Phase 7 or persisting the terminal result and never inlines its members.
- Every producer, SDD, ship-handoff, and ship-summary candidate is a temporary JSON file validated through the corresponding CLI boundary; only validated stdout bytes are transported. `discussion_items` becomes empty only after detail publication, and all numeric notes enforcement comes from the shared policy.
- `workflow-state finish` accepts the exact ship-summary schema including `report_path`, delegates schema/notes validation to Task 1's `validate_ship_summary` with the repository policy in source tests and installed policy in deployment, and preserves the scalar unchanged. It does not retain its old literal notes limit or accept a missing path key.

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
    self.assertIn("report_path", self.ship_handoff)
    self.assertIn("phase_reports.notes_max_characters", self.ship_handoff)
    self.assertIn("validate-report --boundary ship-handoff", self.ship_handoff)
    self.assertIn("validate-report --boundary ship-summary", self.ship_handoff)

def test_sdd_report_is_exact_and_mechanically_validated(self):
    for field in ("state", "review_state", "conformance_verdict",
                  "correctness_verdict", "verification_state", "base_sha",
                  "head_sha", "report_path", "notes"):
        self.assertIn(field, self.sdd)
    self.assertIn("validate-report --boundary sdd", self.sdd)
    for forbidden in ("parked_findings:", "verdict_details:", "open_items:", "summary:"):
        self.assertNotRegex(self.sdd, rf"(?m)^\s*{re.escape(forbidden)}")

def test_received_reports_cross_the_same_json_wire_seam(self):
    self.assert_ordered(self.from_issue, "received stdout bytes",
                        "validate-report --boundary producer --input -", "decode JSON")
    self.assert_ordered(self.from_issue, "validate-report --boundary sdd --input -",
                        "construct the Phase-7 handoff")
    self.assertIn("return only validated stdout bytes", self.auto)

def test_durable_review_detail_precedes_every_removable_cleanup(self):
    self.assertIn(".superpowers/issue-delivery/", self.sdd)
    self.assert_ordered(self.sdd, "delivery-detail", "artifact-budget check",
                        "validate-report --boundary sdd", "delete this plan's workspace")
    self.assertIn(".superpowers/issue-delivery/", self.ship_review)
    self.assertIn("Minor/Discussion", self.ship_review)
    self.assert_ordered(self.ship_issue, "delivery-detail", "artifact-budget check",
                        "validate-report --boundary ship-summary", "remove the worktree")
    for text in (self.sdd, self.ship_review, self.ship_issue, self.ship_handoff):
        self.assertIn("report_path", text)
        self.assertIn("keep the worktree", text)
    self.assertIn("primary worktree", self.ship_handoff)
    self.assertIn("never inline the report", self.from_issue)

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

In `test_workflow_state.py`, add `report_path: None` to the shared terminal-result factory, use a
full lowercase SHA, update exact-key assertions, and add this behavioral contract:

```python
def test_terminal_result_report_path_is_one_validated_durable_scalar(self):
    self.init_run()
    attempt = self.spawn(issue=14, worktree=self.root / "wt-a")["attempt"]
    detail = ".superpowers/issue-delivery/14/run-1/ship-review-a.json"
    valid = {**self.merged_result(), "report_path": detail,
             "notes": f"details: {detail}"}
    invalid = (
        {key: value for key, value in valid.items() if key != "report_path"},
        {**valid, "report_path": [detail]},
        {**valid, "report_path": "/tmp/outside.json"},
        {**valid, "report_path": "../outside.json"},
        {**valid, "notes": "detail omitted"},
        {**valid, "discussion_items": ["not durably moved"]},
    )
    for candidate in invalid:
        before = self.state_path.read_bytes()
        self.finish(attempt, candidate, ok=False)
        self.assertEqual(self.state_path.read_bytes(), before)
    normalized = self.finish(attempt, valid)
    self.assertEqual(normalized["report_path"], detail)
    self.assertIn(detail, normalized["notes"])
```

If existing class attributes use different names, add the exact paths and decoded fixture values without changing the assertions' meaning; expose `SHIP_ISSUE_REVIEW` as `self.ship_review`. These static assertions only pin routing prose; Task 1 behaviorally exercises every report row through stdin/file CLI inputs, Task 3 behaviorally exercises package publication/lifetime, and these checks pin routing and cleanup order.

- [ ] **Step 2: Run the workflow suite and observe missing caller validation**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: FAIL because current phase schemas carry paths without budget states/metrics, Phase 5 can amend artifacts without rechecking, and ship excludes only the plan root.

- [ ] **Step 3: Wire producer reports through callers and final writers**

Update `from-issue`'s structured-report and phase rules to send every received producer stdout byte through `validate-report --boundary producer --input -` before JSON decoding, validate state/status/metrics, run its own checker, and stop before progress/dispatch on mismatch. Update both autonomous schemas to exact producer JSON; remove `spec_path`, `plan_path`, `adr_paths`, `decisions`, and `open_items`. Their prompts require candidate-file validation and return only CLI stdout. Keep caller context bounded to reports and paths.

Update `standards-review` so every accepted plan edit triggers a final plan-package check and every ledger/spec edit triggers a spec check. Apply the existing owner remediation once; unresolved oversize becomes `decompose_required` and returns to the decomposition checkpoint rather than Phase 6.

Update SDD's review-package handling to validate generator stdout through the producer boundary, compare root/status/metrics with a checker result, and stop dispatch truthfully on exit 2/3. Before deleting its workspace, collect every parked/residual finding and ruling into Task 3's exact detail input, resolve the primary worktree, generate/check a no-clobber `delivery-detail` package under D15's unique path, and set `report_path`. Null is legal only when the collection is empty. Write the exact SDD candidate JSON, run `validate-report --boundary sdd`, and return only stdout. Publication/validation failure retains workspace/worktree and returns a valid failed row. From-issue validates through stdin, rechecks and reads any detail root, and only then constructs Phase 7.

Update `ship-handoff` to the exact D14 state matrix with fixed lifecycle scalars, current spec/plan artifacts, SDD `report_path`, and notes; delete `summary`, validate a candidate with the ship-handoff boundary, and dispatch only stdout. Ship-issue revalidates that stdin, rechecks both artifact roots and any SDD detail root, then runs existing phases.

Update `ship-issue/REVIEW.md` to retain every Minor/Discussion item verbatim in a Task 3 detail input. Before Phase 8, resolve the primary worktree, generate/check the unique no-clobber `ship-review-<head>` delivery package when detail exists, and place its relative root in `report_path`; do not empty the compatibility list until this succeeds. Assemble the exact merged/stopped/failed candidate, make notes contain a non-null path, run the ship-summary boundary, and return only stdout. On publication/validation failure return stopped/failed and keep the feature worktree. From-issue validates/rechecks/reads that path before `workflow-state finish`, never inlines members, and persists `discussion_items: []`. For degradation measurement only, enumerate checker-validated plan members into literal `--artifact-path` arguments; keep current product gates and review routing unchanged.

Update `workflow-state.py`'s exact terminal fields to include `report_path` before `notes`; every internally synthesized expiry/refusal result sets it to null. Import Task 1's module from the source scripts directory or installed `~/.agents/lib/python`, select the adjacent repository policy for source execution and the module default when installed, and delegate the entire terminal object to `validate_ship_summary`; translate its `ValueError` to the existing `WorkflowError` without copying enum/notes rules. Update the test factory and exact-key assertions once so existing lifecycle cases inherit `report_path: None`, update any intentional raw exact fixtures, and add the invalid/valid persistence test above.

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
  home/common/agent-skills/skills/ship-issue/REVIEW.md \
  home/common/agent-skills/skills/sdd/SKILL.md \
  home/common/agent-skills/scripts/workflow-state.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  home/common/agent-skills/tests/test_workflow_state.py
git commit -m "feat(issue-49): enforce artifact budgets across workflow" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
