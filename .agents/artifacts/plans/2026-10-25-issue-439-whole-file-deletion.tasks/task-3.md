# Task 3: Reviewer prompts name both kinds, within the existing budget

**Superseded in part by spec D16:** no ceiling is raised and no label is needed. Commit 1a1aed46 reverted the raise steps below and reworded the three hot prompts to fit the existing `implementation-owner` ceiling; the steps that raise a ceiling or expect a `raise:` line no longer apply.

Spec § Reviewer prompts and § Instruction budget, per D8, D9, D10 and D13. The generated-evidence paragraph of the task, conformance, correctness and re-review prompts names each kind by its literal. The `ef-core-migration-designer` rule stays as it is, and `whole-file-deletion` gets its corroboration rule. Both literals are pinned as machine text. The growth breaches only the `implementation-owner` hot ceilings, on both hosts, so this task raises exactly those two values to their measure and adds a raise note. The PR then needs the user-applied `instruction-budget-raise` label (D9). This task never applies that label.

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/re-review-prompt.md`
- Modify: `home/common/agent-skills/instruction-load.json` (profile `implementation-owner`: `ceiling_bytes` and `note`)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`SDD_MACHINE_TEXT`, `WorkflowSkillContractsTest::test_sdd_documents_carry_their_machine_text`)

**Interfaces:**
- Consumes: the kind literals that Tasks 1 and 2 put on the wire, `ef-core-migration-designer` and `whole-file-deletion`.
- Produces: nothing that a later task consumes.

**Invariants:**
- Each of the four prompts contains both literals in backticks, with the corroboration rules exactly as Step 3 words them.
- `final-review.md` and `ship-issue/REVIEW.md` are unchanged (D8).
- In `instruction-load.json`, only `implementation-owner`'s `ceiling_bytes.claude` and `ceiling_bytes.codex` change, from 132694 to the hot measure M the gate prints in Step 3 (133142 before D15's re-review qualification), and its `note` gains one sentence. No other ceiling, profile or key changes.
- After the raise, `just agent-instruction-budget --raise-label` ends in `check: pass`. Without the flag, the gate's only failing line is the model `raise:` line.

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, add this line directly after `WHOLE_FILE_POLICY = "stable-first-fit-whole-file"`:

```python
GENERATED_EVIDENCE_KINDS = ("ef-core-migration-designer", "whole-file-deletion")
```

In the comment above `SDD_MACHINE_TEXT`, change "the review-package packing policy id and" to "the review-package packing policy id, the generated-evidence kinds and". Re-wrap the comment at the current width.

Replace the four reviewer-prompt entries of `SDD_MACHINE_TEXT` with:

```python
    SDD_DIR / "task-reviewer-prompt.md": (WHOLE_FILE_POLICY, *GENERATED_EVIDENCE_KINDS),
    SDD_DIR / "re-review-prompt.md": (WHOLE_FILE_POLICY, *GENERATED_EVIDENCE_KINDS),
    SDD_DIR / "conformance-reviewer-prompt.md": (
        WHOLE_FILE_POLICY, *GENERATED_EVIDENCE_KINDS, "[ACCEPTANCE_CRITERIA]",
    ),
    SDD_DIR / "correctness-reviewer-prompt.md": (
        WHOLE_FILE_POLICY, *GENERATED_EVIDENCE_KINDS,
        "git diff [MERGE_BASE_SHA]..[HEAD_SHA] -- ':(literal)<path>'",
    ),
```

- [ ] **Step 2: Run the test and watch it fail**

Run the focused form (Global Constraints) on `home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_sdd_documents_carry_their_machine_text`.
Expected: `FAILED (failures=8)`. The eight subtests are the two literals in each of the four prompts. Today the prompts say "auto-generated EF … designer" and name no kind literal.

- [ ] **Step 3: Write the minimal implementation**

Replace each block below exactly, old text → new text. Each block is unique in its file, and the 4-space indentation is part of it. The text is fixed verbatim because the raise is measured on it (D13).

`home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`:

```text
    declared context cannot settle a hunk. Version 2, and version 3 with
    `generated_evidence`, replace an oversized auto-generated EF migration
    designer with a bounded entry: check its identities and model-shape counts
    against the companion migration and snapshot diff, and require the
    implementer report to show no-pending-model-change, generated-SQL and
    provider-backed migration evidence. Missing or inconsistent corroboration
    is a finding; generated evidence is never a waiver to approve.
```
→
```text
    declared context cannot settle a hunk. Version 2, and version 3 with
    `generated_evidence`, replace an oversized `ef-core-migration-designer` or
    `whole-file-deletion` diff with a bounded entry. For a designer, check its
    identities and model-shape counts against the companion migration and
    snapshot diff, and require the implementer report to show
    no-pending-model-change, generated-SQL and provider-backed migration
    evidence; for a deletion, confirm the plan or spec intends the deletion and
    no surviving file references the deleted path. Missing or inconsistent
    corroboration is a finding; generated evidence is never a waiver to approve.
```

`home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`:

```text
    Version 2, or version 3 with non-empty `generated_evidence`: also check
    each bounded auto-generated EF designer evidence entry against the
    companion migration and snapshot diff, and require the
    reported no-pending-model-change, generated-SQL and provider-backed migration
    evidence the plan promised; the generated entry is never a review waiver. A non-SDD
```
→
```text
    Version 2, or version 3 with non-empty `generated_evidence`: also check
    each `ef-core-migration-designer` entry against the companion migration
    and snapshot diff, and require the reported no-pending-model-change,
    generated-SQL and provider-backed migration evidence the plan promised; for
    each `whole-file-deletion` entry, confirm the plan or spec intends the
    deletion and no surviving file references the deleted path. Missing
    corroboration is a finding; the generated entry is never a review waiver. A non-SDD
```

`home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`:

```text
    Version 2, or version 3 with non-empty `generated_evidence`: also check
    each bounded auto-generated EF designer evidence entry's identities and
    model-shape counts against the companion migration and snapshot diff, and
    require the report's no-pending-model-change, generated-SQL and
    provider-backed migration evidence; it is never a waiver.
```
→
```text
    Version 2, or version 3 with non-empty `generated_evidence`: also check
    each `ef-core-migration-designer` entry's identities and model-shape counts
    against the companion migration and snapshot diff, and require the report's
    no-pending-model-change, generated-SQL and provider-backed migration
    evidence; for each `whole-file-deletion` entry, confirm the plan or spec
    intends the deletion and no surviving file references the deleted path.
    Missing corroboration is a finding; generated evidence is never a waiver.
```

`home/common/agent-skills/skills/sdd/re-review-prompt.md`:

```text
    diff or approve the fix. Version 3 keeps every whole handwritten file
    diff, declares the adaptive unchanged context and packs with
```
→
```text
    diff or approve the fix. Version 3 keeps every whole handwritten file
    diff that no generated-evidence entry replaces, declares the adaptive
    unchanged context and packs with
```

and, later in the same paragraph:

```text
    file when that context is insufficient. Version 2, and version 3 with
    `generated_evidence`, may replace an oversized auto-generated EF migration
    designer with a bounded entry: verify it against the companion
    migration/snapshot diff and the report's no-pending-model-change,
    generated-SQL and provider-backed migration evidence; that evidence is
    never a waiver. Do not re-run git commands.
```
→
```text
    file when that context is insufficient. Version 2, and version 3 with
    `generated_evidence`, may replace an oversized `ef-core-migration-designer`
    or `whole-file-deletion` diff with a bounded entry: verify a designer
    against the companion migration/snapshot diff and the report's
    no-pending-model-change, generated-SQL and provider-backed migration
    evidence, and confirm the plan or spec intends a deletion and no surviving
    file references the deleted path; that evidence is never a waiver. Do not
    re-run git commands.
```

Record each file's size with `wc -c` (the re-review figure grows with the Version 3 qualification above, per D15).

Run the **Budget gate** (timeout 600 s): `bash -c 'just agent-instruction-budget 2>&1 | grep -E "^(ceiling|tightness|lint|raise):"'`.
Expected: exactly two lines, `ceiling: profile implementation-owner on claude: hot measures M bytes, above its ceiling 132694; …` and the same line for `codex`, with the same M on both, M above 132694 (133142 before D15's re-review qualification; at most a few dozen bytes more after it, if the re-review prompt is in the hot set). Call the printed measure M. If any other line appears, the two values differ, or M exceeds 133300, the prompt text deviates from this step: stop as BLOCKED with the gate output.

In `home/common/agent-skills/instruction-load.json`, profile `implementation-owner`:
1. Replace the unique block `"ceiling_bytes": {\n        "claude": 132694,\n        "codex": 132694\n      }` so that both values are M.
2. In its `note`, replace the unique text

   ```text
   so it never loads the ship-issue members (#352 D1)."
   ```

   with this text, still on the same line:

   ```text
   so it never loads the ship-issue members (#352 D1). Ceiling raised for #439: the task, conformance and correctness reviewer prompts name the `whole-file-deletion` and `ef-core-migration-designer` generated-evidence kinds and the deletion's corroboration rule (#155 D10)."
   ```

   The backticks and the apostrophe are literal characters in the JSON string and need no escape.

- [ ] **Step 4: Verify**

Run the focused form (timeout 900 s) on `home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_skill_lint.py`.
Expected: `OK` (`skipped` allowed). The machine-text test finds both literals in all four prompts. `LiveModelTest` and `LiveBudgetTest` find no breached or loose ceiling.

Run (timeout 600 s):

```bash
set -e
out=$(just agent-instruction-budget 2>&1 | grep -E '^(ceiling|tightness|lint|raise):' || true)
test "$out" = "raise: home/common/agent-skills/instruction-load.json changes more than lowering a ceiling; revert it, or have a human apply the instruction-budget-raise label"
just agent-instruction-budget --raise-label 2>&1 | tail -1 | grep -qx 'check: pass'
git diff --quiet 3f4c5072746747c44bee51b1a24c13288923b27f -- home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/ship-issue/REVIEW.md
test "$(git diff 3f4c5072746747c44bee51b1a24c13288923b27f -- home/common/agent-skills/instruction-load.json | grep -c '^[-+] ')" -eq 6
```

Expected: every command exits 0. The last check counts six changed lines: two ceiling values and one note line, each removed and added.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/task-reviewer-prompt.md home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md home/common/agent-skills/skills/sdd/re-review-prompt.md home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit … -- -m "feat(sdd): reviewer prompts name the whole-file-deletion evidence kind (issue 439)" -m "Raises the implementation-owner hot ceilings; the PR needs the user-applied instruction-budget-raise label." -m "<session trailers>"
```

Verify: `git status --short -- home` prints nothing. Report to the controller that the PR must hold for the user to apply `instruction-budget-raise` (D9).
