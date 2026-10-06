# Task 3: Pin head_sha as the final-review head

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md` (`## Finish`)
- Modify: `home/common/agent-skills/skills/sdd/final-review.md`
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (the sentence ending `ship-issue's Phase-5 degradation decision reads them.`)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify (ceilings only): `home/common/agent-skills/instruction-load.json`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the term *final-review head*, defined as the sdd report's `head_sha` (sdd's first-pass `DELIVERY_HEAD`) and carried unchanged as the handoff's `head_sha`. Task 4's Phase-5 prose relies on this definition (per D1, D10).

**Invariants:**
- No validator, schema or key set changes. The sdd report keeps exactly `state`, `review_state`, `conformance_verdict`, `correctness_verdict`, `verification_state`, `base_sha`, `head_sha`, `detail_state`, `report_path` and `notes` (per D1).
- sdd's review mechanics (the final review, the single fix wave and the scoped re-reviews) are unchanged. Only the meaning of the field is stated.
- Every instruction-load ceiling breached by this task's prose growth is raised per the root's Global Constraints, and no other ceiling changes.

- [ ] **Step 1: Write the failing tests**

Add these two methods to `WorkflowSkillContractsTest` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, right after `test_sdd_report_is_exact_and_mechanically_validated`:

```python
    def test_sdd_head_sha_is_the_final_review_first_pass_head(self):
        # The report states the range both axes reviewed whole, not the branch
        # tip, so ship can review the fix wave again as its delta (#264 D1).
        finish = normalized(self.section(self.sdd, "## Finish", "If publication fails"))
        self.assertIn(
            "`base_sha` and `head_sha` are the `DELIVERY_BASE` and `DELIVERY_HEAD`"
            " the final review's first pass covered, never the branch tip", finish)
        self.assertIn("the tip is past `head_sha`", finish)
        final_review = normalized((SDD_DIR / "final-review.md").read_text(encoding="utf-8"))
        self.assert_ordered(final_review, "review-package PLAN_FILE DELIVERY_BASE DELIVERY_HEAD",
                            "Those two pins are the report's `base_sha` and `head_sha`",
                            "the fix wave below does not move them")

    def test_handoff_head_sha_is_the_sdd_report_head_sha(self):
        handoff = normalized(self.ship_handoff)
        self.assertIn("In both handoff shapes, `head_sha` is the validated sdd report's"
                      " `head_sha`", handoff)
        self.assertIn("the *final-review head* ship-issue's Phase 5 reviews from", handoff)
        from_issue = normalized(self.from_issue)
        self.assertIn("ship-issue's Phase-5 range selection reads them, taking `head_sha` as"
                      " the final-review head only when `review_state` is `clean`", from_issue)
        self.assertNotIn("Phase-5 degradation decision reads them", from_issue)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k head_sha 2>&1 | tail -3`
Expected: `FAILED (failures=2)`.

- [ ] **Step 3: Write the prose**

1. `sdd/SKILL.md` `## Finish`: right after the sentence that ends `` `artifact-budget validate-report --boundary sdd` and transport only canonical stdout. ``, insert: ``` `base_sha` and `head_sha` are the `DELIVERY_BASE` and `DELIVERY_HEAD` the final review's first pass covered, never the branch tip: when the fix wave adds commits, the tip is past `head_sha`, and ship-issue reviews those commits again as part of its delta since that final-review head. ```
2. `sdd/final-review.md`: append to the paragraph that begins ``Run `review-package PLAN_FILE DELIVERY_BASE DELIVERY_HEAD` once``, after its last sentence: ``` Those two pins are the report's `base_sha` and `head_sha` (SKILL.md's `## Finish`); the fix wave below does not move them. ```
3. `from-issue/ship-handoff.md`: append a new paragraph right after the paragraph that ends ``its boundary reads it under the `workflow_responses` wire bound.``: ``` In both handoff shapes, `head_sha` is the validated sdd report's `head_sha`, copied unchanged and never the branch tip: it is the *final-review head* ship-issue's Phase 5 reviews from. ```
4. `from-issue/SKILL.md`: replace ``After these gates, sdd's `review_state` (`clean | residuals | unknown`) and `report_path` may be used to construct the Phase-7 handoff — ship-issue's Phase-5 degradation decision reads them.`` with ``After these gates, sdd's `review_state` (`clean | residuals | unknown`), `head_sha` and `report_path` may be used to construct the Phase-7 handoff — ship-issue's Phase-5 range selection reads them, taking `head_sha` as the final-review head only when `review_state` is `clean`.`` (the original wraps across two lines; match it with whitespace collapsed).
5. Run the root's ceiling snippet. For each breached pair, set `ceiling_bytes[host]` to the measured hot bytes and append `Ceiling raised for #264: sdd and from-issue state that head_sha is the final-review head (#155 D10).` to that profile's `note`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_artifact_budget.py 2>&1 | tail -3`
Expected: `OK`. The two new tests pass, and `test_the_live_tree_breaches_no_ceiling` passes.

Run: `git diff --name-only 40fa9c7 -- home/common/agent-skills/skills/sdd home/common/agent-skills/skills/from-issue`
Expected: exactly the four prose files from **Files** are listed, with no evals or validators.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/instruction-load.json
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-261-262-263-264-265 --worker-id <your worker id> -- -m "docs(sdd,from-issue): pin head_sha as the final-review head (#264)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QpGEgn23dNP1QXn2of1cto"
```
