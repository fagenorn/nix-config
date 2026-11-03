# Task 4: Phase 5 reviews the selected range

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (lines 41–42 plan-member sentence, flow line 5, the Phase-0 probe's "merge delta may turn out empty", and the whole of Phase 5 from `**Pick the path first.**` up to `Launch the native conformance axis with:`)
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md`
- Modify: `home/common/agent-skills/skills/ship-issue/evals/evals.json` (eval 1's degradation clause only)
- Modify: `home/common/agent-skills/skills/from-issue/ship-handoff.md` (task step 2 only)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify (ceilings only): `home/common/agent-skills/instruction-load.json`

**Interfaces:**
- Consumes: `~/.agents/bin/review-range` from Tasks 1–2. It prints one JSON line with `route` (`delta`|`empty`|`full`), `reason`, `final_review_head`, `head`, `review_base`, `product_lines` and `product_files`, and exit 1 means no decision. It also consumes the term *final-review head* that Task 3 defines (the handoff's `head_sha`).
- Produces: the PR-body record strings `review range: delta <review_base7>..<head7> since final-review <R7> (<L> lines, <F> files)`, `review range: empty since final-review <R7>` and `review range: full (<reason>)` (per D4), plus REVIEW.md's `## Delta route` brief.

**Invariants:**
- Every dispatch marker and call line in `ship-issue/SKILL.md` stays byte-identical, including `ship-issue-merge-delta-review` (per D11). `PYTHONPATH="$PWD/python" python3 -m agent_tools.agent_model_matrix validate` stays green.
- The anchor `**Full two-axis review.**` and the text up to `Axis reports are never merged` keep the correctness ladder unchanged, because `ship_correctness_route()` reads that span.
- The prerequisites keep their order and polarity: clean `review_state`, no manual sync escalation, the size bullet, no `risky` label plus the `capabilities.review.code` state (per D4).
- REVIEW.md's merge-delta section keeps its `git show --cc` scope and its checklist for CI-MERGE.md's post-selection sync. CI-MERGE.md is not edited in this task (per D11).
- Each breached instruction-load ceiling is raised per the root's Global Constraints.

- [ ] **Step 1: Write the failing tests**

In `test_workflow_skill_contracts.py`, replace the body of `test_degradation_gate_delegates_counting_and_carries_the_retuned_boundary` with:

```python
        # The gate states a policy and calls the helper; the ancestry and
        # accounting live in `agent_tools.review_range` / `diff_scope` (#264 D2).
        gate = self.section(self.ship_issue, "**Pick the range first.**",
                            "**Route the review.**")
        for fragment in (
            GATE_LINE_BOUNDARY,
            GATE_FILE_BOUNDARY,
            # the whole invocation: the thresholds passed must be the ones stated (D2).
            "review-range --integration-ref origin/<integration> --head $HEAD_SHA"
            " --final-review-head <final-review head> --max-lines 1000 --max-files 20"
            " --artifact-path <spec_path> --artifact-path <plan_path>",
            "distinct from the reviewed `HEAD_SHA`",
            "No measurement",
            "is not a small diff",
            "`review-range unavailable`",
            "a historical artifact that is itself the requested product still counts",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, gate)
        for absent in ("--numstat", "400", "--root", "diff-scope $BASE_SHA"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, gate)
        self.assert_ordered(
            gate,
            "`review_state` is `clean`",
            "needed no manual conflict escalation",
            GATE_LINE_BOUNDARY,
            "does NOT carry the `risky` label",
            "`capabilities.review.code` state",
        )
```

In `test_ship_issue_eval_restates_the_gate_boundary_it_grades`, replace the third fragment with `f"the delta is small ({GATE_LINE_BOUNDARY} / {GATE_FILE_BOUNDARY}," " measured with `review-range` rather than hand-counted numstat arithmetic)"`, and add `self.assertNotIn("measured with `diff-scope`", expected)` after the loop.

In `test_ship_expands_validated_plan_only_for_diff_scope_exclusion`, rename it to `test_ship_expands_validated_plan_only_for_review_range_exclusion` and change its ordered anchor `"diff-scope"` to `"review-range"`.

Add these methods to `WorkflowSkillContractsTest`:

```python
    def test_phase_five_reviews_the_selected_range_on_two_axes(self):
        phase_five = normalized(self.section(self.ship_issue, "## Phase 5 — Review the PR",
                                             "## Phase 6 — Wait for CI"))
        route = normalized(self.section(self.ship_issue, "**Route the review.**",
                                        "**Merge-delta reviewer (post-selection sync only).**"))
        self.assert_ordered(route, "`delta`", "`<review_base>..$HEAD_SHA`",
                            "delta-route conformance brief", "`empty`", "skip to Phase 6",
                            "`full`", "`$BASE_SHA..$HEAD_SHA`", "per REVIEW.md")
        merge_delta = self.section(self.ship_issue,
                                   "**Merge-delta reviewer (post-selection sync only).**",
                                   "**Full two-axis review.**")
        self.assertIn("Phase 5 never dispatches it", normalized(merge_delta))
        self.assertIn("<!-- agent-dispatch: id=ship-issue-merge-delta-review role=reviewer"
                      " model=opus effort=high -->", merge_delta)
        full = normalized(ship_correctness_route(self.ship_issue))
        self.assertIn("Both the `delta` and `full` routes run it", full)
        self.assertIn("`<review_base>..$HEAD_SHA` on `delta`, `$BASE_SHA..$HEAD_SHA` otherwise",
                      full)
        self.assertNotIn("merge-delta empty, nothing to review", phase_five)
        self.assertIn("5. Review the PR → review-range picks delta, empty or full;"
                      " two-axis review over it", normalized(self.ship_issue))
        self.assertIn("it dispatches zero (empty review range) or two first-pass reviewer"
                      " subagents", normalized(self.ship_handoff))
        self.assertNotIn("zero (empty merge-delta), one, or two", normalized(self.ship_handoff))

    def test_review_md_owns_the_delta_brief_and_the_range_record(self):
        review = normalized(self.ship_review)
        delta = normalized(self.section(self.ship_review, "## Delta route",
                                        "## Severity mapping (full path)"))
        for fragment in (
            "`<review_base>..$HEAD_SHA`",
            "already graded delivered-vs-promised for the branch at R",
            "scope-creep categories", "review hint path",
            "stale-prose audit limited to files the delta touches",
            "never grades the whole branch's delivery again",
            "`review range: delta <review_base7>..<head7> since final-review <R7>"
            " (<L> lines, <F> files)`",
            "`review range: empty since final-review <R7>`",
            "`review range: full (<reason>)`",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, delta)
        merge_delta = normalized(self.section(self.ship_review,
                                              "## Merge-delta check (post-selection sync)",
                                              "## Full two-axis review — templates"))
        self.assertIn("Phase 5 never does", merge_delta)
        self.assertIn("`git show --cc <merge-commit>`", merge_delta)
        self.assertNotIn("after the head sdd reviewed", review)
        self.assertNotIn("merge-delta empty, nothing to review", review)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k gate -k range -k delta 2>&1 | tail -3`
Expected: `FAILED`. `**Pick the range first.**` and `## Delta route` do not exist yet.

- [ ] **Step 3: Write the prose**

`ship-issue/SKILL.md`:
1. Lines 41–42: `` for `diff-scope` exclusion `` → `` for `review-range` exclusion ``.
2. Flow line 5: `5. Review the PR           → review-range picks delta, empty or full; two-axis review over it`.
3. Phase-0 probe: `even when the merge delta may turn out empty` → `even when the review range may turn out empty`.
4. Replace the `**Pick the path first.**` lead sentence with: ``**Pick the range first.** The *final-review head* is the handoff's `head_sha` when `review_state` is `clean`; it is distinct from the reviewed `HEAD_SHA` this phase fixes. Check the first, second and fourth conditions first; when any fails, the range is full and `review-range` does not run. Select the range with `review-range` when ALL of these hold:`` Keep the first, second and fourth bullets verbatim.
5. Replace the size bullet with: ``- The delta since the final-review head is small: **≤1,000 product lines AND ≤20 product files**. Measure, never hand-count: start with `~/.agents/bin/review-range --integration-ref origin/<integration> --head $HEAD_SHA --final-review-head <final-review head> --max-lines 1000 --max-files 20 --artifact-path <spec_path> --artifact-path <plan_path>`, then append one argument for each plan member and any other process artifact this run wrote. Each exclusion is an individual `--artifact-path <path>` argument. It prints one JSON object whose `route` is `delta`, `empty` or `full`, with a closed `reason`; its `product_lines` and `product_files` measure `<review_base>..$HEAD_SHA` after dropping lockfiles, generated-header files, and those exact artifacts. The gate measures PRODUCT changes, not process artifacts; never exclude the resolved artifact directories themselves, which hold every artifact this repo has ever accepted, and a historical artifact that is itself the requested product still counts. No measurement — exit 1, unparseable stdout, or invalid plan discovery — is not a small diff: the range is full, recorded as `review-range unavailable`.``
6. Replace the `**Merge-delta check (degraded path).**` paragraph, its dispatch marker and call line, and the `An empty delta is recorded…` line with this text, keeping the marker and call line byte-identical: ``**Route the review.** `delta` → the full two-axis review below over `<review_base>..$HEAD_SHA`, with REVIEW.md's delta-route conformance brief. `empty` → nothing to review: record it and skip to Phase 6. `full`, a failed prerequisite, or an unavailable helper → the full two-axis review below over `$BASE_SHA..$HEAD_SHA`. Record the route in the PR body per REVIEW.md.`` Then a blank line, and ``**Merge-delta reviewer (post-selection sync only).** Phase 5 never dispatches it: CI-MERGE.md's `## Post-selection sync` reviews each later sync merge with it, over REVIEW.md's merge-delta scope and checklist:``, followed by the unchanged marker and call line.
7. `**Full two-axis review.**` sentence: ``Templates and fallback rubrics per REVIEW.md, over the post-sync range `$BASE_SHA..$HEAD_SHA`.`` → ``Both the `delta` and `full` routes run it. Templates and fallback rubrics per REVIEW.md, over the selected range: `<review_base>..$HEAD_SHA` on `delta`, `$BASE_SHA..$HEAD_SHA` otherwise.``

`ship-issue/REVIEW.md`:
1. Retitle `## Merge-delta check (degraded path)` as `## Merge-delta check (post-selection sync)` and rewrite its body as: ``CI-MERGE.md's `## Post-selection sync` runs this for each later sync merge; Phase 5 never does. The reviewable delta is that sync-merge commit's combined diff (`git show --cc <merge-commit>` — conflict resolutions and scope-creep sweeps). Dispatch SKILL.md's merge-delta reviewer over only that delta (SKILL.md's Phase-0 reviewer-dispatch probe has already confirmed this context can launch it)``. Then keep the old body verbatim, from `with Phase 1's scope-creep categories` through `file:line anchors.`.
2. `## Full two-axis review — templates`: ``over the post-sync range `$BASE_SHA..$HEAD_SHA`.`` → ``over the range SKILL.md's Phase 5 selected.``. In the diff-review scope paragraph, ``the same surface a degraded run uses for "merge-delta empty, nothing to review"`` → ``the same surface as Phase 5's `review range:` record``.
3. Insert a new section `## Delta route` right before `## Severity mapping (full path)`: ``On `delta`, both axes run the templates above over `<review_base>..$HEAD_SHA`, the range `review-range` printed. Correctness keeps its unchanged rubric and correctness route. The conformance brief adds three things to the template's issue, spec and plan paths. First, the final-review head R, with the statement that sdd's final review already graded delivered-vs-promised for the branch at R. Second, its job: judge whether each delta change — a fix commit resolving a finding, a sync resolution, a learning doc — keeps the branch consistent with the issue, spec, plan and standards without breaking a promise R already kept, with Phase 1's scope-creep categories (retirement / addition, see SYNC.md) and every review hint path passed in the retained snapshot as its checklist. Third, a stale-prose audit limited to files the delta touches. It never grades the whole branch's delivery again.`` Follow it with a paragraph: ``**Range record.** Phase 5 records its route in the PR body as `review range: delta <review_base7>..<head7> since final-review <R7> (<L> lines, <F> files)`, `review range: empty since final-review <R7>`, or `review range: full (<reason>)`, where `<reason>` is `review-range`'s `reason`, `review-range unavailable`, or the name of the failed prerequisite.``

`ship-issue/evals/evals.json` eval 1: in `expected_output`, replace ``degradation only when review_state is clean, sync conflict-free, and the diff is small (≤1,000 product lines / ≤20 product files, measured with `diff-scope` rather than hand-counted numstat arithmetic), otherwise two independent axes`` with ``two independent axes over `review-range`'s delta since the final-review head only when review_state is clean, the sync conflict-free, and the delta is small (≤1,000 product lines / ≤20 product files, measured with `review-range` rather than hand-counted numstat arithmetic), otherwise over the full branch``. Keep the JSON valid.

`from-issue/ship-handoff.md` task step 2: ``follow ship-issue's path selection — it may dispatch zero (empty merge-delta), one, or two reviewer subagents.`` → ``follow ship-issue's range selection — it dispatches zero (empty review range) or two first-pass reviewer subagents.``

Then run the root's ceiling snippet and raise each breached pair with the note `Ceiling raised for #264: ship-issue Phase 5 selects its review range with review-range (#155 D10).`

- [ ] **Step 4: Verify**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" timeout 900 python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | tail -3`
Expected: `OK`.

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m agent_tools.agent_model_matrix validate 2>&1 | tail -2`
Expected: exit 0.

Run: `git diff 40fa9c7 -- home/common/agent-skills/skills/ship-issue/SKILL.md | grep '^[-+].*agent-dispatch' || echo MARKERS-UNCHANGED`
Expected: `MARKERS-UNCHANGED`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/REVIEW.md home/common/agent-skills/skills/ship-issue/evals/evals.json home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/instruction-load.json
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-261-262-263-264-265 --worker-id <your worker id> -- -m "feat(ship-issue): review only the delta since final review (#264)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QpGEgn23dNP1QXn2of1cto"
```
