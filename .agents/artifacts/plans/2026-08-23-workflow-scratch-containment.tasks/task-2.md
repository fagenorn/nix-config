# Task 2: Lifecycle request files get a stated home

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: `normalized(text)` and `corpus_documents()` from Task 1 — module-level helpers in `test_workflow_skill_contracts.py`. If Task 1 has not landed, add them exactly as Task 1 defines them rather than inventing variants.
- Produces: the module-level constants `REQUEST_FILE_HOME` and `REQUEST_FILE_INVOCATION`.

**Invariants:**
- All three request-file prescriptions carry one identical literal, so the assertion is an occurrence count rather than three positional greps (per D17).
- No cleanup contract is added: `workflow-state` consumes these files within the call and never retains them, so tightening the location is the whole change (per D14).
- Nothing about the request payload changes — the version-1 JSON shape, the `null` observation slots, the "add no keys" rule and the `direct-owner` / `control` invocations are untouched.
- The corpus rule is non-vacuous: at least two documents carry the `--request-file` invocation today, and every one of them must name the home.

Cites D10, D14, D17.

- [ ] **Step 1: Write the failing tests**

Add at module level, beside the Task 1 constants:

```python
# One literal for all three lifecycle request-file prescriptions (D17).
REQUEST_FILE_HOME = "a new absolute temporary request file beneath `${TMPDIR:-/tmp}`"
REQUEST_FILE_INVOCATION = "--request-file <absolute-json-path>"
```

Add these two tests to `WorkflowSkillContractsTest`:

```python
    def test_request_file_prescriptions_name_the_temp_home(self):
        self.assertEqual(normalized(self.from_issue).count(REQUEST_FILE_HOME), 2)
        self.assertEqual(normalized(self.orchestrate).count(REQUEST_FILE_HOME), 1)

    def test_every_request_file_invocation_names_the_temp_home(self):
        carriers = [
            path.relative_to(REPO_ROOT)
            for path, text in corpus_documents()
            if REQUEST_FILE_INVOCATION in normalized(text)
        ]
        # Non-vacuity: the rule must have something to police.
        self.assertGreaterEqual(len(carriers), 2, carriers)
        missing = [
            str(path)
            for path in carriers
            if REQUEST_FILE_HOME not in normalized(
                (REPO_ROOT / path).read_text(encoding="utf-8")
            )
        ]
        self.assertEqual(missing, [])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k request_file -v`

Expected: FAIL twice — the counts are `0 != 2` and `0 != 1`, and `missing` lists both `home/common/agent-skills/skills/from-issue/SKILL.md` and `home/common/claude-code/skills/orchestrate-issues/SKILL.md`.

- [ ] **Step 3: State the home in all three prescriptions**

In `home/common/agent-skills/skills/from-issue/SKILL.md`, under "Direct autonomous acquisition" (around line 46), replace the sentence

> For every call, write a new absolute temporary request file containing exactly this version-1 shape.

with

> For every call, write a new absolute temporary request file beneath `${TMPDIR:-/tmp}` containing exactly this version-1 shape.

In the same file, in numbered item 1 (`kind: observe`, around line 99), replace the sentence

> Write a new absolute request file and call `direct-owner` again.

with

> Write a new absolute temporary request file beneath `${TMPDIR:-/tmp}` and call `direct-owner` again.

Keep the existing three-space list indentation and the trailing "Unknown, duplicate, or malformed requirements fail loudly." sentence exactly as they are. Re-wrap the paragraphs at the file's ~80-column width; the tests normalize whitespace, so wrapping is free.

In `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, under "## 3. Decide" (around line 85), replace the line

> Invoke the helper with the request file:

with

> Invoke the helper with a new absolute temporary request file beneath `${TMPDIR:-/tmp}`:

Leave the fenced `workflow-state control …` block and the paragraph after it unchanged.

- [ ] **Step 4: Verify**

```bash
python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -v 2>&1 | tail -5
```
Expected: `OK` — the two new tests pass and no existing contract test regresses.

```bash
if git diff HEAD -- home/common/agent-skills/skills/from-issue/SKILL.md \
      home/common/claude-code/skills/orchestrate-issues/SKILL.md \
   | grep -E '^[+-]' | grep -vE '^(\+\+\+|---)' | grep -q 'workflow-state '; then
  echo "a helper invocation line changed"; exit 1
fi
echo prose-only
```
Expected: `prose-only` — the `workflow-state direct-owner` / `workflow-state control` invocation blocks are untouched; only prose moved.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md \
        home/common/claude-code/skills/orchestrate-issues/SKILL.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "fix(agent-skills): give lifecycle request files a stated temp home"
```
