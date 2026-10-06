# Task 3: The per-task verification ladder

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/implementer-prompt.md` (`## Test Discipline`, `## After Review Findings`)
- Modify: `home/common/agent-skills/skills/sdd/fix-loop.md` (the `Every round:` paragraph)
- Modify: `home/common/agent-skills/skills/sdd/final-review.md` (one paragraph after the `sdd-final-review-fixer` dispatch)
- Modify: `home/common/agent-skills/skills/writing-plans/SKILL.md` (a rule after **Every task carries at least one verification line that could fail.**)
- Modify: `home/common/agent-skills/instruction-load.json` (ceilings only, per Global Constraints)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the class `CheckpointVerificationContractsTest` at the end of `test_workflow_skill_contracts.py` (Task 2), with `self.assert_ordered(text, *anchors)` (each anchor found after the previous one) and `self.read(path)` (file text with every whitespace run collapsed to one space); the module constants `SDD_DIR` and `WRITING_PLANS`. The `## Final verification` heading at the end of `sdd/final-review.md` (Task 2).
- Produces: nothing later tasks consume.

**Invariants:**
- No per-task actor — implementer, fix round, final-review fixer — runs the full declared verification; each runs the focused tests its brief or findings cover, plus the build check only when its change touches files the build evaluates (per D1, D2).
- Shared skill text names "the build check" and "files the build evaluates", never a concrete command (per D2); writing-plans tells a planner in doubt to include the build check (per D11).
- The sentence `run the full suite once before committing` no longer exists in `implementer-prompt.md`.
- The `own-commands` clause and every `<!-- agent-dispatch -->` marker and `Agent(…)` line stay byte-identical.

- [ ] **Step 1: Write the failing test**

Add these methods to `CheckpointVerificationContractsTest`:

```python
    def test_the_implementer_runs_focused_tests_and_the_build_check_only(self):
        prompt = self.read(SDD_DIR / "implementer-prompt.md")
        self.assertNotIn("run the full suite once before committing", prompt)
        self.assert_ordered(
            prompt, "## Test Discipline",
            "run the focused test commands your brief names, red before green",
            "and the brief's build check when your task changes files the build evaluates",
            "Do not run the full declared verification: the final gate runs it once, "
            "on the final head.",
            "## After Review Findings",
            "re-run the focused tests covering the amended code",
            "the brief's build check when the fix changes files the build evaluates")

    def test_fix_rounds_and_the_final_fixer_name_the_same_ladder(self):
        self.assert_ordered(
            self.read(SDD_DIR / "fix-loop.md"),
            "Every round: the implementer fixes, re-runs the covering focused tests",
            "when the fix changes files the build evaluates, the brief's build check",
            "(never the full declared verification)",
            "appends a fix report")
        self.assert_ordered(
            self.read(SDD_DIR / "final-review.md"),
            "id=sdd-final-review-fixer",
            "The fixer runs the focused tests covering each fix",
            "the build check when a fix changes files the build evaluates",
            "never the full declared verification",
            "the **Final verification** step below runs it after the fix wave",
            "Where both axes flag the same lines",
            "## Final verification")

    def test_writing_plans_names_focused_commands_per_task(self):
        self.assert_ordered(
            self.read(WRITING_PLANS),
            "**Every task carries at least one verification line that could fail.**",
            "**Each task names its focused test commands.**",
            "adds the project's build check only when the task changes files that "
            "check evaluates",
            "a planner unsure whether a task's files reach the build adds it",
            "No task names the full declared verification as a per-task gate",
            "sdd's final gate runs it once on the final head",
            "## Package construction and budget boundary")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k CheckpointVerification 2>&1 | tail -4`
Expected: FAILED (failures=3) — the three new tests fail; Task 2's two pass.

- [ ] **Step 3: Implement**

`home/common/agent-skills/skills/sdd/implementer-prompt.md` (inside the indented prompt block; keep its 4/6-space indentation):

- In `## Test Discipline`, replace the bullet
  `- While iterating, run the focused test for what you're changing; run the full suite once before committing, not after every edit.`
  with:

  ```
      - While iterating, run the focused test for what you're changing. Before
        committing, run the focused test commands your brief names, red before
        green, and the brief's build check when your task changes files the build
        evaluates. Do not run the full declared verification: the final gate
        runs it once, on the final head.
  ```

- In `## After Review Findings`, replace `Fix, re-run the tests covering the amended code, and append` with `Fix, re-run the focused tests covering the amended code (and the brief's build check when the fix changes files the build evaluates), and append`.

`home/common/agent-skills/skills/sdd/fix-loop.md`: replace `Every round: the implementer fixes, re-runs the covering tests, appends a fix report` with `Every round: the implementer fixes, re-runs the covering focused tests and, when the fix changes files the build evaluates, the brief's build check (never the full declared verification), appends a fix report`.

`home/common/agent-skills/skills/sdd/final-review.md`: directly after the line `Agent(subagent_type="implementer", model="opus", effort="high") fixes the verified whole-branch findings in one wave.` and before the paragraph beginning `Where both axes flag the same lines`, insert one paragraph, with a blank line on each side:

```markdown
The fixer runs the focused tests covering each fix, and the build check when a
fix changes files the build evaluates, never the full declared verification:
the **Final verification** step below runs it after the fix wave.
```

`home/common/agent-skills/skills/writing-plans/SKILL.md`: directly after the paragraph that begins `**Every task carries at least one verification line that could fail.**`, insert one paragraph, with a blank line on each side:

```markdown
**Each task names its focused test commands.** Its verify step runs the focused tests that cover the task, red then green, and adds the project's build check only when the task changes files that check evaluates; a planner unsure whether a task's files reach the build adds it. No task names the full declared verification as a per-task gate: sdd's final gate runs it once on the final head. Global Constraints may still name the verification commands with their timeouts, as the commands the final gate and ship run.
```

Then apply the Global Constraints' instruction-load ceiling rule (`implementer-prompt.md`, `final-review.md` and `writing-plans/SKILL.md` are hot members); the note sentence's `<what grew>` is `the implementer, fixer and writing-plans name the per-task verification ladder`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -4`
Expected: `OK` — the three new tests (red in Step 2) pass, and the #261 `own-commands` and interim-result anchors, the dispatch markers and the ceilings stay green.

Build check (the skill tree is copied by the Nix build), per Global Constraints' long-command rule:

```bash
log="${TMPDIR:-/tmp}/build-263-t3.log"
{ just build; echo "exit=$?"; } > "$log" 2>&1; tail -3 "$log"; rm -f "$log"
```

Expected: `exit=0`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/implementer-prompt.md home/common/agent-skills/skills/sdd/fix-loop.md home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/writing-plans/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/instruction-load.json
launch-commit <Lifecycle worker values> -- -m "feat(sdd): run focused tests per task and the full suite at the gate (#263)" -m "<trailers>"
```
