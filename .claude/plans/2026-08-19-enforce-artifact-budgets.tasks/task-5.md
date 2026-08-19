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
- Preserves terminal keys `issue`, `state`, `pr_url`, `merge_sha`, `issue_closed`, `discussion_items`, `notes`, adds scalar `detail_state`/`report_path`, and keeps `discussion_items: []` only when detail is absent, durably published, or explicitly retained behind an `unpublished` path. The former Phase-7 `summary` is removed.

**Invariants:**
- From-issue pipes every received JSON report through the matching `validate-report --input -` boundary before decoding it, then independently invokes the checker against reported artifact roots. Validator/checker exit 2, a claim mismatch, or missing/non-integer metric is `failed`; over budget never advances.
- The autonomous design and plan prompts require the new fixed report fields. The orchestrator holds returned root/metrics only, never member lists or artifact contents.
- Phase 5 rechecks both the full plan package and the spec after every accepted edit/ledger append. It uses the owning producer's remediation and returns `decompose_required` rather than dispatching SDD when the final check is over.
- SDD parses every review-package command report, passes root/metrics to the intended reviewer, and never dispatches on `decompose_required`/`failed`. Its final phase report remains compact and does not inline transient review evidence.
- The ship handoff carries current spec/plan roots and metrics. Ship-issue rechecks both on entry and after any writer changes either artifact; a stale/mismatched/over-budget artifact prevents merge.
- Per D10, ship-issue discovers checker-validated plan members locally and supplies root plus each member as individual `--artifact-path` arguments to `diff-scope`. No public report or prompt carries that list, and the existing ≤1,000-line/≤20-file gate is otherwise unchanged.
- Small fixture cases complete; oversized fixture cases map exactly to design/grill `decompose_required`, planning `decompose_required`, handoff `stopped`, and review-package `decompose_required`. `complete` plus `over_budget` is always a contract error.
- SDD's final phase report has exactly `state`, `review_state`, `conformance_verdict`, `correctness_verdict`, `verification_state`, `base_sha`, `head_sha`, `detail_state`, `report_path`, and policy-bounded `notes`; lists are rejected. `none` requires empty detail/null path, `present` requires a checker-valid durable package, and failure-only `unpublished` requires a readable retained candidate in the live workspace.
- Task 3's producer independently resolves `<main-root>` from the absolute Git common directory, confirms the primary checkout, derives the only permitted leaf, and establishes the ignore boundary. Task 5 callers supply only issue/branch/run/head identity (an optional expected path is an assertion, never authority). Before SDD workspace deletion, package every parked/residual finding through delivery-detail mode; before ship Phase 8 cleanup, package every Minor/Discussion item at the derived sibling leaf. Leaves are per-run/branch, primary-root-owned, and no-clobber.
- A non-empty detail set requires either `present` plus a checker-valid durable package or `unpublished` plus its readable retained source; notes contain the exact path. The latter returns only `failed`/`stopped` and preserves the feature worktree/workspace. With genuinely no detail, the state is `none` and path null. From-issue distinguishes the states, consumes durable detail before advancing, and never inlines either file.
- Every producer, SDD, ship-handoff, and ship-summary candidate is validated through the corresponding CLI boundary; only validated stdout bytes are transported. `discussion_items` is empty for `unpublished` only after the retained source is re-read and named; all numeric notes enforcement comes from the shared policy.
- `workflow-state finish` accepts the exact ship-summary schema including `detail_state`/`report_path`, delegates validation to Task 1, and preserves both scalars unchanged. It does not retain its old literal notes limit or accept missing keys.

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
                  "head_sha", "detail_state", "report_path", "notes"):
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

def test_review_package_failure_before_dispatch_has_no_fabricated_detail(self):
    self.assert_ordered(self.sdd, "base_sha and head_sha", "review-package",
                        "exit 2", 'detail_state: "none"', "report_path: null",
                        "validate-report --boundary sdd")
    self.assertIn("before reviewer dispatch", self.sdd)
    self.assertIn("do not dispatch", self.sdd)

def test_unpublished_detail_keeps_readable_sources_and_forbids_cleanup(self):
    self.assert_ordered(self.sdd, "write the retained candidate", 'detail_state: "unpublished"',
                        "validate-report --boundary sdd", "keep the workspace")
    self.assert_ordered(self.ship_review, "write the retained candidate",
                        'detail_state: "unpublished"', "keep the worktree")
    for text in (self.sdd, self.ship_review, self.ship_issue):
        self.assertIn("confirm the retained candidate is readable", text)
        self.assertIn("do not remove", text)

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

In `test_workflow_state.py`, add `detail_state: "none"` and `report_path: None` to the shared terminal-result factory, use a
full lowercase SHA, update exact-key assertions, and add this behavioral contract:

```python
def test_terminal_result_report_path_is_one_validated_durable_scalar(self):
    self.init_run()
    attempt = self.spawn(issue=14, worktree=self.root / "wt-a")["attempt"]
    detail = ".superpowers/issue-delivery/14/run-1/ship-review-a.json"
    valid = {**self.merged_result(), "detail_state": "present", "report_path": detail,
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

def test_unpublished_ship_detail_retains_a_readable_candidate(self):
    self.init_run()
    worktree = self.root / "wt-a"
    attempt = self.spawn(issue=14, worktree=worktree)["attempt"]
    relative = ".superpowers/ship-review/14/retained-detail.json"
    retained = worktree / relative
    payload = ('{"interface_version":1,"findings":[{"axis":"ship","ruling":null,'
               '"severity":"Minor","status":"minor","text":"kept"}]}')
    result = {**self.merged_result(), "state": "stopped", "pr_url": None,
              "merge_sha": None, "issue_closed": False,
              "detail_state": "unpublished", "report_path": relative, "discussion_items": [],
              "notes": f"publication failed; retained: {relative}"}
    before = self.state_path.read_bytes()
    self.finish(attempt, result, ok=False)
    self.assertEqual(self.state_path.read_bytes(), before)
    retained.parent.mkdir(parents=True)
    retained.write_text(payload, encoding="utf-8")
    normalized = self.finish(attempt, result)
    self.assertEqual(normalized["detail_state"], "unpublished")
    self.assertEqual(retained.read_text(encoding="utf-8"), payload)
```

If existing class attributes use different names, add the exact paths and decoded fixture values without changing the assertions' meaning; expose `SHIP_ISSUE_REVIEW` as `self.ship_review`. These static assertions only pin routing prose; Task 1 behaviorally exercises every report row through stdin/file CLI inputs, Task 3 behaviorally exercises package publication/lifetime, and these checks pin routing and cleanup order.

- [ ] **Step 2: Run the workflow suite and observe missing caller validation**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: FAIL because current phase schemas carry paths without budget states/metrics, Phase 5 can amend artifacts without rechecking, and ship excludes only the plan root.

- [ ] **Step 3: Wire producer reports through callers and final writers**

Update `from-issue`'s structured-report and phase rules to send every received producer stdout byte through `validate-report --boundary producer --input -` before JSON decoding, validate state/status/metrics, run its own checker, and stop before progress/dispatch on mismatch. Update both autonomous schemas to exact producer JSON; remove `spec_path`, `plan_path`, `adr_paths`, `decisions`, and `open_items`. Their prompts require candidate-file validation and return only CLI stdout. Keep caller context bounded to reports and paths.

Update `standards-review` so every accepted plan edit triggers a final plan-package check and every ledger/spec edit triggers a spec check. Apply the existing owner remediation once; unresolved oversize becomes `decompose_required` and returns to the decomposition checkpoint rather than Phase 6.

Update SDD's review-package handling as above. A pre-dispatch failure uses `none`/null. Before delivery publication, write the non-empty exact detail input at `<workspace>/retained-detail.json` and confirm it is readable. Success uses `present` plus the durable root; publication/check failure uses `failed`, `unpublished`, and the repository-relative retained path, validates that SDD report, and explicitly does not remove the workspace/worktree. From-issue never advances an unpublished result to Phase 7.

Update `ship-handoff` to the exact D14 state matrix with fixed lifecycle scalars, current spec/plan artifacts, SDD `report_path`, and notes; delete `summary`, validate a candidate with the ship-handoff boundary, and dispatch only stdout. Ship-issue revalidates that stdin, rechecks both artifact roots and any SDD detail root, then runs existing phases.

Update `ship-issue/REVIEW.md` to write every Minor/Discussion item verbatim to a readable `.superpowers/ship-review/<issue>/retained-detail.json` candidate before delivery publication. Success uses `present` and the durable root. Publication/check failure uses stopped/failed plus `unpublished` and the repository-relative retained path, leaves `discussion_items: []` because notes/path preserve the detail, validates the summary, and explicitly does not remove the worktree. From-issue never treats that path as a durable package. Keep the existing degradation gate behavior.

Update `workflow-state.py`'s exact terminal fields to include `detail_state` and `report_path` before `notes`; internally synthesized results use `none`/null. Delegate the whole object to `validate_ship_summary`, then for `unpublished` resolve the path beneath the recorded live attempt worktree with no-follow regular-file checks and read it once before accepting `finish`; missing/unreadable/escaping candidates leave state unchanged. Translate validation failures to `WorkflowError`. Update factories/exact fixtures and add the persistence test above.

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
