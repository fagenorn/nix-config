# Task 2: sdd's Final verification gate

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/final-review.md` (append a `## Final verification` section at the end)
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md` (`## Final review — two axes` and `## Finish`)
- Modify: `home/common/agent-skills/instruction-load.json` (ceilings only, per Global Constraints)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the `verified-tree` command from Task 1 — `verified-tree check --verification <id> …` (exit 0 `{"status","tree"}`, exit 2 on git or record failure) and `verified-tree record --tree <id> --verification <id> …` (exit 0 recorded, exit 3 `tree_changed`, exit 2 error).
- Produces: a new test class `CheckpointVerificationContractsTest` at the end of `test_workflow_skill_contracts.py`, with `assert_ordered(self, text, *anchors)` and the static `read(path)` (normalized text). Tasks 3 and 4 add methods to it. The heading `## Final verification` in `final-review.md`, which Task 3's fixer sentence points to as "the **Final verification** step below".

**Invariants:**
- The step sits after the fix wave, its scoped re-reviews and the "no second fix wave" sentence, and before the terminal state is chosen (per D3).
- Its order is check → run unless `verified` → record → ledger line → one repair round → residual (per D3, D4, D10, D12).
- SKILL.md's Finish ties `verification_state: passed` and the Clean state to the step's recorded pass and points to the step without restating it: no `verified-tree` and no ledger-line text in `## Finish`.
- No `<!-- agent-dispatch -->` marker is added or edited; the repair round reuses the existing fixer and correctness re-review dispatches by reference.

- [ ] **Step 1: Write the failing test**

Append to `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, before the final `if __name__ == "__main__":` block if there is one, otherwise at the end:

```python
class CheckpointVerificationContractsTest(unittest.TestCase):
    """#263: the full declared verification runs at checkpoints, recorded by tree."""

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_final_verification_follows_the_fix_wave_in_order(self):
        self.assert_ordered(
            self.read(SDD_DIR / "final-review.md"),
            "There is no second fix wave",
            "## Final verification",
            "after the fix wave and its scoped re-reviews",
            "before you choose the terminal state",
            "`bindings.workflow.verification`",
            "1. **Check.**", "`verified-tree check --verification <id>`",
            "keep the `tree` it prints", "Exit 0 with `verified`", "skip step 2.",
            "2. **Run and record.**",
            "in the foreground with an explicit timeout above its duration",
            "only the tail read back",
            "When every command passes, run `verified-tree record --tree <the checked tree>`",
            "3. **Ledger.**",
            "`Final verification: passed (head <full sha>, tree <tree id>)`",
            "4. **Repair once.**", "`tree_changed`", "exits 2 is not a pass",
            "Dispatch the final-review fixer above once",
            "`git status --porcelain`",
            "one scoped correctness re-review",
            "then run steps 1–3 once more",
            "load-bearing correctness finding",
            "the terminal state is Residuals",
            "`verification_state: failed`")

    def test_sdd_finish_ties_passed_to_the_recorded_final_verification(self):
        sdd = self.read(SDD)
        self.assert_ordered(
            sdd, "## Final review — two axes", "the **Final verification** step",
            "## Finish",
            "`verification_state` is `passed` only when final-review.md's "
            "**Final verification** step recorded a pass on the reported `head_sha`",
            "- **Clean** —",
            "and the **Final verification** step recorded a pass on `head_sha`",
            "- **Residuals** —")
        finish = sdd.split("## Finish", 1)[1]
        for restated in ("verified-tree", "Final verification: passed"):
            with self.subTest(restated=restated):
                self.assertNotIn(restated, finish)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k CheckpointVerification 2>&1 | tail -4`
Expected: FAILED (failures=2) — the first missing anchors are `## Final verification` and `the **Final verification** step`.

- [ ] **Step 3: Implement**

Append to the end of `home/common/agent-skills/skills/sdd/final-review.md`, after the paragraph ending `There is no second fix wave — residual load-bearing findings surface to the caller.`, separated by one blank line:

```markdown
## Final verification

Run this after the fix wave and its scoped re-reviews, or right after the first
pass when neither axis had findings, and before you choose the terminal state.
It is the plan's one run of the full declared verification: every retained
`bindings.workflow.verification` id, in order, each dereferenced through
`bindings.commands`.

1. **Check.** In the worktree, run `verified-tree check --verification <id>`,
   repeating `--verification` for each id, and keep the `tree` it prints.
   Exit 0 with `verified` means this exact tree already passed these commands
   (a resumed controller, say): skip step 2.
2. **Run and record.** Otherwise run every declared verification command once,
   in the foreground with an explicit timeout above its duration, its output in
   a log on disk and only the tail read back. When every command passes, run
   `verified-tree record --tree <the checked tree>` with the same
   `--verification` ids.
3. **Ledger.** Append
   `Final verification: passed (head <full sha>, tree <tree id>)` to the SDD
   ledger. That line is the readable copy; the record file in the worktree's
   git directory is the one `verified-tree check` reads.
4. **Repair once.** A failing command, a `record` that exits 3 with
   `tree_changed`, or a `check` or `record` that exits 2 is not a pass.
   Dispatch the final-review fixer above once, carrying the failing command and
   its log path, the `git status --porcelain` output for `tree_changed`, or the
   helper's stderr line for an exit 2. Run one scoped correctness re-review of
   that fix diff, through the final correctness re-review above and the same
   fix-range package gate, then run steps 1–3 once more. If verification still
   does not pass, record the failure as a load-bearing correctness finding in
   the retained detail: the terminal state is Residuals and the report carries
   `verification_state: failed`.
```

In `home/common/agent-skills/skills/sdd/SKILL.md`:

1. In `## Final review — two axes`, replace `the scoped per-axis re-reviews, and the escalation rules.` with `the scoped per-axis re-reviews, the escalation rules, and the **Final verification** step.`
2. In `## Finish`, directly after the sentence ending `and transport only canonical stdout.`, insert: `` `verification_state` is `passed` only when final-review.md's **Final verification** step recorded a pass on the reported `head_sha`, and `failed` when that step's repair round did not pass. ``
3. In the **Clean** terminal bullet, replace `finding parked-with-ruling: delete this plan's workspace` with `finding parked-with-ruling, and the **Final verification** step recorded a pass on `head_sha`: delete this plan's workspace` (keep the line wrapping near 80 columns).

Then apply the Global Constraints' instruction-load ceiling rule (`final-review.md` and `SKILL.md` are hot members); the note sentence's `<what grew>` is `sdd's final-review gained the Final verification step`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -4`
Expected: `OK` — the two new tests (red in Step 2) pass, and the existing final-review anchors, dispatch markers and ceilings stay green.

Build check (the skill tree is copied by the Nix build), per Global Constraints' long-command rule:

```bash
log="${TMPDIR:-/tmp}/build-263-t2.log"
{ just build; echo "exit=$?"; } > "$log" 2>&1; tail -3 "$log"; rm -f "$log"
```

Expected: `exit=0`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/sdd/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/instruction-load.json
launch-commit <Lifecycle worker values> -- -m "feat(sdd): run and record the full verification at the final gate (#263)" -m "<trailers>"
```
