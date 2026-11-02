# Task 3: Cut REVIEW.md, SYNC.md and CONSOLIDATE.md

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/ship-issue/REVIEW.md`, `skills/ship-issue/SYNC.md`, `skills/ship-issue/CONSOLIDATE.md`
- Modify: `instruction-load.json` (`tighten` only), `skill-lint-debt.json`
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 2's tree. `REVIEW.md` no longer holds the merge-delta check and names no sibling.
- Produces:
  - `REVIEW.md` with these `##` headings in order: `Codex correctness route`, `Full two-axis review — templates`, `Delta route`, `Severity mapping (full path)`, `The five-step apply/push flow`, `Durable Minor/Discussion detail`. `## Delivery interface version 2` is gone.
  - `SYNC.md` and `CONSOLIDATE.md` with their headings unchanged, except that the policy-support sentences are gone.

**Invariants:**
- `REVIEW.md` stays the single carrier of `.superpowers/ship-review` and keeps `.superpowers/issue-delivery/`, `validate-detail-input`, `detail_state: "unpublished"`, `~/.agents/bin/review-package`, the five steps in order with their argv, and the `review range:` record lines byte for byte.
- `REVIEW.md` keeps the worktree-local retained candidate's path and its "do not relocate" rule (per D4). The severity mapping and the `--auto` Should-fix paragraph keep every clause, because from-issue's handoff calls them "ship-issue's auto-mode rules".
- `REVIEW.md` keeps the Codex failure semantics (binding-shape error stops, capacity rejection has no retry and no fallback, a call under `unsupported` is a routing error, one native fallback for a completed non-capacity failure). The rung list lives in `SKILL.md` Phase 5, so `REVIEW.md` drops its own copy of "Authored `unsupported` takes the caller's native correctness route directly".
- `SYNC.md`'s allowlist table stays byte for byte, `cargo update` included (finding 3, per D12). So does its escalation fence. Its two divergence cases and its `--auto` rule keep their meaning.
- `CONSOLIDATE.md` keeps the bar, the four-test rubric, the destination table, steps 1–6 with the proposal fence and the empty-outcome line, and the `docs(<scope>): <one-line summary>` commit form.
- Byte targets: `REVIEW.md` 5,800, `SYNC.md` 2,700, `CONSOLIDATE.md` 3,300. Every one ends at ≤ 100 reflowed lines.

- [ ] **Step 1: Delete the pins on the text this task cuts, and pin what stays**

In `tests/test_workflow_skill_contracts.py`:
- `RETAINED_SUPPORT_CONTRACTS`: delete the `"ship-issue/CONSOLIDATE.md"` and `"ship-issue/SYNC.md"` rows (spec item 3).
- `test_durable_review_detail_precedes_every_removable_cleanup`: remove `self.ship_review` from the `report_path` / `keep the worktree` loop, so it iterates `(self.sdd, self.ship_issue, self.ship_handoff)`. Keep `self.assertIn(".superpowers/issue-delivery/", self.ship_review)`.
- Add `SHIP_ISSUE_REVIEW`'s remaining machine text to its key:

```python
    SHIP_ISSUE_REVIEW: (
        "validate-detail-input", 'detail_state: "unpublished"',
        ".superpowers/ship-review/<issue>/retained-detail.json",
        "review range: delta <review_base7>..<head7> since final-review <R7> (<L> lines, <F> files)",
        "review range: empty since final-review <R7>", "review range: full (<reason>)",
    ),
```

- [ ] **Step 2: Run the focused tests**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ship_issue_documents_carry -k durable_review_detail -k listed_support_documents` (timeout 300 s)
Expected: OK. The pins removed in Step 1 would turn red on Step 3's cuts, which is why they go first. The new items already hold at Task 2's head.

- [ ] **Step 3: Cut**

1. `REVIEW.md`:
   - Replace the two opening paragraphs with one line: "Phase 5's review mechanics; `SKILL.md` Phase 5 holds the dispatch sites and the rung choice." Add `## Codex correctness route` holding the Codex failure semantics (Invariants), with no rung list.
   - Templates: keep. Cut "ship-issue records no reviewer identity; this records the scope only." and "A scoped Clean that reaches the PR body …" down to the record rule itself.
   - Five-step flow: cut the sentence "The failure mode is …", keep "`apply` and `push` are separate steps". Delete the paragraph "After step 5, a named finding … full Opus/high axis." (its home is the `ship-issue-scoped-fix-rereview` site in `SKILL.md` Phase 5).
   - Durable detail: keep the path, the publication sequence and the root split. Reduce the worktree-local exception to one sentence: the candidate is deliberately worktree-local, because a publication failure re-reads it and keeps the worktree; never relocate it to `$TMPDIR` or the primary checkout. Reduce the `workflow-state finish` explanation to one clause: `finish` resolves a `present` path against `--repo-root` and an `unpublished` one against the recorded worktree.
   - Delete `## Delivery interface version 2`.
2. `SYNC.md`:
   - Cut the policy-support sentence ("This included document receives …"), the audit anecdote ("Of three audited `--auto` sessions … Don't be those two."), and "Older flows let unrelated issues' spec/plan commits ride into a worktree."
   - Shorten the divergence bullets to their rule and one reason clause each.
3. `CONSOLIDATE.md`:
   - Cut the policy-support sentence. Merge "Project-agnostic: …" into one sentence.
   - Cut the destination table's trailing paragraph "A candidate requiring a brand-new top-level doc is a leap …", because the table's lead already says to drop a learning with no home.
   - Cut the explanatory half of `## The bar`'s first rule (from "junk compounds" to the end of that paragraph), keeping "**Default to drop.** A junk entry costs more than a missed learning."

- [ ] **Step 4: Models**

- `skill-lint-debt.json`: delete `L3 …/ship-issue/REVIEW.md` and `L3 …/ship-issue/CONSOLIDATE.md` (per D14).
- Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 5: Verify**

Run the focused suite, the lint and the gate. Expected: OK, exit 0, `check: pass`.
Run:

```bash
set -euo pipefail
PYTHONPATH=python python3 - <<'EOF'
from pathlib import Path
from agent_tools import skill_lint
S = Path("home/common/agent-skills/skills/ship-issue")
for name, cap in {"REVIEW.md": 5800, "SYNC.md": 2700, "CONSOLIDATE.md": 3300}.items():
    text = (S / name).read_text(encoding="utf-8")
    if len(text.encode()) > cap:
        print(f"over target: {name} {len(text.encode())} > {cap} (name it in the commit body)")
    assert skill_lint.reflowed_lines(text) <= 100, name
    assert "retained `ResolvedProject`" not in text, name
assert "## Delivery interface version 2" not in (S / "REVIEW.md").read_text(encoding="utf-8")
EOF
```

Expected: exit 0. At Task 2's head it fails, because `SYNC.md` still carries "retained `ResolvedProject`".

- [ ] **Step 6: Commit**

Commit as `refactor(ship-issue): cut REVIEW.md, SYNC.md and CONSOLIDATE.md to their rules (#296)`.
