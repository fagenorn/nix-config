# Task 2: Notes go to the Delivery record

This task covers spec § Target text — the note sites. Every step that today writes a verification or review note "in the PR body" or "the PR body's Summary" names the Delivery record instead: Phase 2's skipped, reused and baseline-diff notes, Phase 5's route record and routing error, and `REVIEW.md`'s diff-review scope and range record (per D6). Phase 2 step 1 is also trimmed (per D10). Task 1 already created the Delivery record in the Phase-4 template.

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md` (`## Phase 2 — Verify locally` steps 1 and 2 and the paragraph after them, and two sentences of `## Phase 5 — Review the PR`)
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md` (one line in `## Full two-axis review — templates` and one in `## Delta route`)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes, from Task 1: the module tuple `INLINE_FALLBACK_MARKUP`, whose closing lines are `    "Delivery record",` and `)`, and the method `WorkflowSkillContractsTest.test_inline_fallback_names_the_readable_body`. From the base: `re`, `normalized(text)`, `SHIP_ISSUE` (the path of ship-issue's `SKILL.md`) and `SHIP_ISSUE_REVIEW` (the path of its `REVIEW.md`).
- Produces: the module dict `NOTE_DESTINATION_ANCHORS: dict[Path, tuple[str, ...]]`, the module function `note_blocks(text: str) -> list[str]`, and the test `test_ship_issue_notes_go_to_the_delivery_record`.

**Invariants:**
- In `SKILL.md`, `` `verification skipped: <id> (<reason>)` `` and `` `verification reused: tree <id>` `` each sit in exactly one paragraph or list item. In `REVIEW.md`, so do `` `review range: delta `` and `` `unmeasured` ``. Each of those four blocks names `Delivery record` and does not contain `Summary`.
- Neither `in the PR body` nor `PR body's Summary` occurs in `SKILL.md` or `REVIEW.md`.
- `REVIEW.md` stays at 100 reflowed lines, every line under 100 characters, so skill lint L3 still needs no `## Contents`. `SKILL.md` ends at 499 reflowed lines.
- Task 1's template, its paragraphs, its hold wording and its two cases are unchanged. So are `SHIP_ISSUE_MACHINE_TEXT`, `HUMAN-GATE.md`, `REMAINDER.md` and `ship-handoff.md`.

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`:

1. Directly after the `)` that closes `INLINE_FALLBACK_MARKUP`, insert one blank line and then the block below. Two blank lines follow the function, so it is separated from the `# "sibling <=2 words> candidate"` comment as PEP 8 asks.

```python
# Each closed note line and the document that sends it to the PR body
# (#494 D6, D9): the paragraph or list item holding it names the Delivery record.
NOTE_DESTINATION_ANCHORS = {
    SHIP_ISSUE: ("`verification skipped: <id> (<reason>)`", "`verification reused: tree <id>`"),
    SHIP_ISSUE_REVIEW: ("`review range: delta", "`unmeasured`"),
}


def note_blocks(text):
    """Paragraphs and list items: the unit a note's destination sentence lives in."""
    return re.split(r"\n\s*\n|\n(?=\d+\. |- )", text)
```

2. In `WorkflowSkillContractsTest`, directly after `test_inline_fallback_names_the_readable_body`, add:

```python
    def test_ship_issue_notes_go_to_the_delivery_record(self):
        for path, anchors in NOTE_DESTINATION_ANCHORS.items():
            blocks = note_blocks(path.read_text(encoding="utf-8"))
            for anchor in anchors:
                with self.subTest(document=path.name, anchor=anchor):
                    holders = [block for block in blocks if anchor in block]
                    self.assertEqual(len(holders), 1)
                    self.assertIn("Delivery record", normalized(holders[0]))
                    self.assertNotIn("Summary", holders[0])
```

- [ ] **Step 2: Run the test and watch it fail**

Run the PR body cases command (timeout 600 s). Expected: `Ran 3 tests` and `FAILED (failures=4)`. All four failures are subtests of `test_ship_issue_notes_go_to_the_delivery_record`, one per anchor, each `AssertionError: 'Delivery record' not found in` the block. Task 1's two cases pass.

- [ ] **Step 3: Write the minimal implementation**

Make exactly these seven replacements. Each `old` text occurs exactly once at the starting commit, and nothing is re-wrapped.

In `SKILL.md`:

1. Phase 2 step 1. Replace
   `` keep the `tree`, `run` and `skipped` it prints. On Phase 2's own run, note each `skipped` entry as `verification skipped: <id> (<reason>)` in the PR body's Summary. ``
   with
   `` keep its `tree`, `run` and `skipped`. On Phase 2's own run, note each skip as `verification skipped: <id> (<reason>)` in the Delivery record. ``
2. Phase 2 step 2's second line. Replace `` `verification reused: tree <id>` in the PR body's Summary. `` with `` `verification reused: tree <id>` in the Delivery record. ``
3. The baseline sentence. Replace `note the baseline diff in the PR body)` with `note the baseline diff in the Delivery record)`.
4. Phase 5 **Route the review.** Replace `Record the route in the PR body per REVIEW.md.` with `Record the route in the Delivery record per REVIEW.md.`
5. Phase 5's routing-error paragraph. Replace `record the routing error in the PR body beside the correctness verdict` with `record the routing error in the Delivery record beside the correctness verdict`.

In `REVIEW.md`:

6. Replace the line `` in the PR body beside the correctness verdict and Phase 5's `review range:` record. `` with `` in the Delivery record beside the correctness verdict and Phase 5's `review range:` record. ``
7. Replace the line `**Range record.** Phase 5 records its route in the PR body as` with `**Range record.** Phase 5 records its route in the Delivery record as`.

- [ ] **Step 4: Verify**

Run the PR body cases command (timeout 600 s). Expected: `Ran 3 tests`, `OK`.

Run the Skill contract tests command (timeout 900 s). Expected: `Ran 296 tests`, `OK (skipped=3)`.

Run (timeout 60 s):

```bash
set -euo pipefail
if git grep -n -e 'in the PR body' -e "PR body's Summary" -- home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/REVIEW.md; then exit 1; fi
git diff --quiet HEAD -- home/common/agent-skills/skills/from-issue/ship-handoff.md home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md home/common/agent-skills/skills/ship-issue/REMAINDER.md home/common/agent-skills/instruction-load.json
echo note-sites-ok
```

Expected: `note-sites-ok`. At the starting commit, the `git grep` prints five lines of `SKILL.md` and two of `REVIEW.md`, and the script exits 1. This gate covers the three sites that carry no closed note line, which the committed case cannot see (per D11).

Run the Budget command (timeout 600 s). Expected: the last line is `check: pass`. As measured on the prototype, ship-owner hot is 51964 of 52076 B, `SKILL.md` is at 499 reflowed lines and `REVIEW.md` is at 100.

Run the Installed tier command (timeout 3600 s). Expected: the last line is `OK` or `OK (skipped=N)`, with no `FAIL` or `ERROR`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-issue/REVIEW.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- -m "feat(ship-issue): send verification and review notes to the Delivery record (issue 494)"
```

The message ends with the session's attribution trailer. Report DONE with the two test counts and the Budget line.
