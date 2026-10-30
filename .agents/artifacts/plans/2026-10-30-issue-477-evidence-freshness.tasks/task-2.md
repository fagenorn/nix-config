# Task 2: sdd freshness guidance runs the verb

Spec § sdd guidance. Rests on D5, D6 and D10. After this task, the three freshness sentences in sdd's final review and conformance reviewer prompt no longer judge a "measured surface" by hand: they run `verified-tree fresh` (Task 1), and the argv is pinned as machine text. Both documents end smaller than at base, so the Instruction Budget passes with no ceiling raised.

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/final-review.md`
- Modify: `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's CLI, `verified-tree fresh --since <commit> --record <path>`, which exits 0 printing `status` `fresh` or `stale`, or exits 2. `<record path>` is the acceptance record, `<plans dir>/<plan stem>.acceptance.md`, which `final-review.md` § Acceptance record already names. `<Commit>` is that record's `Commit` column.
- Consumes: `normalized()` in the contract test, which collapses whitespace runs, so the argv may sit on one line of the document while the pin is one string.
- Produces: the pinned argv literal `verified-tree fresh --since <Commit> --record <record path>` in both documents.

**Invariants:**
- The phrase `measured surface` appears in neither document.
- `final-review.md` ends at most 12932 bytes and `conformance-reviewer-prompt.md` at most 8962 bytes, their sizes at `79cf7e3f` (D5). The planned text gives 12882 and 8950.
- No other sentence of either document changes; no code span is broken across lines.

- [ ] **Step 1: Write the failing test**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `SDD_MACHINE_TEXT`:

- In the `SDD_DIR / "final-review.md"` tuple, insert `"verified-tree fresh --since <Commit> --record <record path>",` on its own line right after `"verified-tree record --tree <the checked tree>",`. (The same record pin appears again in ship-issue's tuple further down; do not touch that one.)
- In the `SDD_DIR / "conformance-reviewer-prompt.md"` tuple, add the same string on its own line after `WHOLE_FILE_POLICY, *GENERATED_EVIDENCE_KINDS, "[ACCEPTANCE_CRITERIA]",`.

- [ ] **Step 2: Run the test and watch it fail**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_sdd_documents_carry_their_machine_text 2>&1 | tail -3'`
Expected: `FAILED (failures=2)`, one subtest each for `final-review.md` and `conformance-reviewer-prompt.md`, item `verified-tree fresh --since <Commit> --record <record path>`.

- [ ] **Step 3: Rewrite the three sentences**

1. `final-review.md` § Acceptance record: replace the whole paragraph that begins `Before writing, check freshness against each `evidence` row's own `Commit`, not` and ends `an acceptance finding that survives the fix wave.` with exactly:

```markdown
Before writing, run
`verified-tree fresh --since <Commit> --record <record path>` for each
`evidence` row recorded `met`, with that row's own `Commit`, not the head the
conformance first pass graded (a fixer's re-measurement writes a fresh
`Commit`, so only later commits count). Run it also for a `code` row recorded
`met` on a cited run outside the Declared verification line, with that run's
commit, unless the check was run again and the fresh run cited. `stale`, or an
exit 2, makes the row `unverified`: an acceptance finding that survives the
fix wave.
```

2. `final-review.md` § Final verification, step 4: replace the two lines

```markdown
   package gate). With an acceptance record, every `met` `evidence` row whose
   measured surface the repair's commits touch becomes `unverified` in a record
```

with

```markdown
   package gate). With an acceptance record, every `met` `evidence` row that
   `verified-tree fresh` now reports `stale` becomes `unverified` in a record
```

3. `conformance-reviewer-prompt.md`, the `evidence` bullet under Acceptance criteria: replace its last five lines (from `        the criterion's literal threshold, and the commits after the` through `        `unverified`, and a value outside the threshold is `unmet`.`) with exactly these five lines (eight-space indent kept):

```markdown
        the criterion's literal threshold, and
        `verified-tree fresh --since <Commit> --record <record path>` prints
        `fresh`. An evidence `met` must cite the observed value and the
        threshold; rounding or "close enough" never counts. A row missing or
        not `fresh` is `unverified`; a value outside the threshold is `unmet`.
```

- [ ] **Step 4: Verify**

Run the Step 2 command.
Expected: `Ran 1 test`, `OK`.

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -1'`
Expected: `OK (skipped=2)`.

Run (timeout 60 s): `bash -c 'set -e; D=home/common/agent-skills/skills/sdd; for f in final-review.md conformance-reviewer-prompt.md; do test "$(wc -c < "$D/$f")" -le "$(git show 79cf7e3f:"$D/$f" | wc -c)"; if grep -n "measured surface" "$D/$f"; then exit 1; fi; done'`
Expected: exit 0. At the start commit it exits 1, printing the `measured surface` lines.

Run the Budget (Global Constraints).
Expected: `check: pass`.

Run the Build (Global Constraints).
Expected: no error line; the skill documents are read into the home configuration.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "docs(sdd): judge acceptance freshness with verified-tree fresh (issue 477)" -m "<trailers>"
```
