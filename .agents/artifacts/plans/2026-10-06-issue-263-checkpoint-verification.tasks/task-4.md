# Task 4: Ship's one verification step

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (`## The flow` line 2, `## Phase 2 — Verify locally`)
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md` (step 2 of `## The five-step apply/push flow`)
- Modify: `home/common/agent-skills/skills/ship-issue/CI-MERGE.md` (`## Post-selection sync` steps 2 and 3)
- Modify: `home/common/agent-skills/instruction-load.json` (ceilings only, per Global Constraints)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the `verified-tree` command from Task 1 — `check` prints `{"status":"verified"|"unverified","tree":…}` with exit 0, or exits 2; `record --tree <id>` exits 0 recorded, 3 `tree_changed`, 2 error. The class `CheckpointVerificationContractsTest` (Task 2) with `self.assert_ordered(text, *anchors)` and `self.read(path)` (whitespace-normalized text); the module constants `SHIP_ISSUE`, `SHIP_ISSUE_REVIEW`, `SHIP_ISSUE_CI_MERGE`.
- Produces: nothing later tasks consume.

**Invariants:**
- Ship skips the declared-verification run only on `check` exit 0 `verified`; every other answer runs every command, and a full pass is recorded (per D5, D9).
- A `record` refused for `tree_changed` is a failing verification; a `check` exit 2 runs the commands and leaves the pass unrecorded (per D10, D12).
- The existing blocked-capability, failure and baselining rules stay verbatim and apply only to an actual run.
- REVIEW.md step 2 and both CI-MERGE.md reruns name Phase 2's step instead of restating commands, so all three sites share one procedure (per D5).
- A Phase 3 consolidation commit changes the tree after Phase 2 ran, so Phase 3 re-runs Phase 2's step before Phase 4; the merged head is never an unverified tree (per D13).
- The `gh pr create` body form is unchanged; the reuse note contains no `"`, `$`, backtick or backslash in the rendered body.

- [ ] **Step 1: Write the failing test**

Add these methods to `CheckpointVerificationContractsTest`:

```python
    def test_ship_phase_two_skips_only_on_a_verified_tree(self):
        phase = self.read(SHIP_ISSUE).split("## Phase 2 — Verify locally", 1)[1]
        phase = phase.split("## Phase 3", 1)[0]
        self.assert_ordered(
            phase, "This is the one verification step.",
            "Phase 3 after a promotion commit, REVIEW.md's apply/push step 2 and CI-MERGE.md's post-selection sync run it too.",
            "A blocked verification capability stops",
            "1. **Check.** Run `verified-tree check --verification <id>`",
            "in order, and keep the `tree` it prints.",
            "2. **Skip only on `verified`.**", "Exit 0 with `verified`", "skip the run",
            "`verification reused: tree <id>`",
            "3. **Otherwise run and record.**", "On any other answer, run every command id",
            "When every command passes, run `verified-tree record --tree <the checked tree>`",
            "`tree_changed` is a failing verification",
            "A `check` that exits 2 leaves no tree to record",
            "These failure rules apply only to an actual run.",
            "On a failing verification command, pause, ground, and surface",
            "baselining the same project in a scratch worktree")
        self.assertEqual(phase.count("verified-tree record"), 1)

    def test_review_and_ci_merge_reruns_use_phase_two(self):
        review = self.read(SHIP_ISSUE_REVIEW)
        self.assert_ordered(
            review, "## The five-step apply/push flow", "1. Edit the file(s).",
            "2. Run Phase 2's verification step (SKILL.md's `## Phase 2 — Verify locally`)",
            "3. `git add`")
        consolidate = self.read(SHIP_ISSUE).split("## Phase 3 — Consolidate learnings", 1)[1]
        consolidate = consolidate.split("## Phase 4", 1)[0]
        self.assert_ordered(
            consolidate, "Promoted candidates commit as",
            "When Phase 3 commits anything, run Phase 2's verification step again before Phase 4.")
        self.assertNotIn("Re-run every retained `bindings.workflow.verification` command",
                         review)
        ci_merge = self.read(SHIP_ISSUE_CI_MERGE)
        self.assert_ordered(
            ci_merge, "## Post-selection sync",
            "2. **Verify.** Run Phase 2's verification step.",
            "after every amend re-run Phase 2's verification step before the push.")
        self.assertNotIn("Phase 2 verification commands", ci_merge)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k CheckpointVerification 2>&1 | tail -4`
Expected: FAILED (failures=2) — the two new tests fail; Tasks 2–3's five pass.

- [ ] **Step 3: Implement**

In `home/common/agent-skills/skills/ship-issue/SKILL.md`:

1. In the `## The flow` block, replace `2. Verify locally          → lint + tests inside the worktree` with `2. Verify locally          → verified-tree check; run + record unless verified` (same column for `→`).
2. Replace the body of `## Phase 2 — Verify locally`, from the line after the heading up to (not including) the paragraph that begins `Test failures: separate *environmental*`, with exactly this; keep that `Test failures:` paragraph unchanged after it:

```markdown
This is the one verification step. Phase 3 after a promotion commit,
REVIEW.md's apply/push step 2 and CI-MERGE.md's post-selection sync run it too.

A blocked verification capability stops and reports its `reason_code` and
`repair_id`; authored unsupported follows only its documented no-verification
route.

1. **Check.** Run `verified-tree check --verification <id>` in the worktree,
   repeating `--verification` for every id in retained
   `bindings.workflow.verification`, in order, and keep the `tree` it prints.
2. **Skip only on `verified`.** Exit 0 with `verified` means this exact tree
   already passed these commands, at sdd's final gate or an earlier run of
   this step: skip the run. On Phase 2's own run, note
   `verification reused: tree <id>` in the PR body's Summary.
3. **Otherwise run and record.** On any other answer, run every command id in
   retained `bindings.workflow.verification` through its `bindings.commands`
   argv and cwd. When every command passes, run
   `verified-tree record --tree <the checked tree>` with the same
   `--verification` ids. A `record` that exits 3 with `tree_changed` is a
   failing verification under the rules below: the passing run no longer
   describes the worktree. A `check` that exits 2 leaves no tree to record:
   run the commands anyway, and leave the pass unrecorded.

These failure rules apply only to an actual run. On a failing verification
command, pause, ground, and surface; do not invent a fix command outside
retained `bindings.commands`.
```

This removes the old fenced `<each bindings.workflow.verification command, dereferenced through bindings.commands>` block and the old `Run every command id …` paragraph; their content now lives in steps 1 and 3.

3. In `## Phase 3 — Consolidate learnings`, append to the paragraph that ends `following retained \`bindings.vcs.commit.co_authored_by\`.` the sentence: `When Phase 3 commits anything, run Phase 2's verification step again before Phase 4.`

In `home/common/agent-skills/skills/ship-issue/REVIEW.md`, replace step 2 (`2. Re-run every retained \`bindings.workflow.verification\` command through` / `` `bindings.commands` against the modified surface.``) with:

```markdown
2. Run Phase 2's verification step (SKILL.md's `## Phase 2 — Verify locally`)
   on the modified worktree, before the commit.
```

In `home/common/agent-skills/skills/ship-issue/CI-MERGE.md` under `## Post-selection sync`:

- Replace `2. **Verify.** Run the Phase 2 verification commands.` with `2. **Verify.** Run Phase 2's verification step.`
- Replace `after every amend re-run the Phase 2 verification commands before the push.` with `after every amend re-run Phase 2's verification step before the push.`

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `test_ship_issue_post_selection_sync_route` (the second `assert_ordered` on `route`): replace the anchor `"Phase 2 verification"` with `"Run Phase 2's verification step."` and `"re-run the Phase 2 verification commands before the push"` with `"re-run Phase 2's verification step before the push"`.

Then apply the Global Constraints' instruction-load ceiling rule (`ship-issue/SKILL.md` and `REVIEW.md` are hot members); the note sentence's `<what grew>` is `ship-issue Phase 2 checks and records the verified tree`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -4`
Expected: `OK` — the two new tests (red in Step 2) and the updated post-selection-sync route test pass; the shell-example scan and ceilings stay green.

Build check (the skill tree is copied by the Nix build), per Global Constraints' long-command rule:

```bash
log="${TMPDIR:-/tmp}/build-263-t4.log"
{ just build; echo "exit=$?"; } > "$log" 2>&1; tail -3 "$log"; rm -f "$log"
```

Expected: `exit=0`. The full declared verification is not this task's gate: sdd's final gate runs it.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/REVIEW.md home/common/agent-skills/skills/ship-issue/CI-MERGE.md home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/instruction-load.json
launch-commit <Lifecycle worker values> -- -m "feat(ship-issue): skip verification only on a recorded tree (#263)" -m "<trailers>"
```
