# Task 2: Move the post-selection sync into POST-SELECTION-SYNC.md and cut CI-MERGE.md

**Files** (under `home/common/agent-skills/`):
- Create: `skills/ship-issue/POST-SELECTION-SYNC.md`
- Modify: `skills/ship-issue/CI-MERGE.md`, `skills/ship-issue/REVIEW.md` (its `## Merge-delta check` and the delta route's sibling pointer only)
- Modify: `skills/ship-issue/SKILL.md` (the index and the pointers to the post-selection sync only)
- Modify: `skills/ship-issue/DELIVERY-LOOP.md`, `skills/ship-issue/REMAINDER.md` (pointer wording only, if Task 1 left any)
- Modify: `instruction-load.json`, `skill-lint-debt.json`
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's tree. `DELIVERY-LOOP.md` and `REMAINDER.md` call this route "the post-selection sync route", and `SKILL.md` has a `## Files beside this one` index.
- Produces:
  - `POST-SELECTION-SYNC.md`, headed `# Post-selection sync`, with sections in this order: `## Current selection and sync run`, `## Trigger`, `## Steps`, `## Merge-delta check`, `## A merge that already landed`, `## Stops`.
  - `CI-MERGE.md`, headed `# Phases 6–7 — CI escalation and merge quirks`, with sections `## Escalation after 40 minutes`, `## Failing checks`, `## Advisory overflow` and `## Merge exit code in a worktree`.
  - Test constant `SHIP_ISSUE_POST_SELECTION_SYNC` and its `SHIP_ISSUE_MACHINE_TEXT` key. The `SHIP_ISSUE_CI_MERGE` key is removed (per D16), and the constant too if nothing else reads it.

**Invariants:**
- The route's trigger cases, its seven steps, its `review_ref` values (`merge-delta-empty`, `merge-delta-clean`), the already-landed variant and every stop keep their meaning, order and argv (spec Decisions, "Route selection is unchanged").
- The escalation prompt keeps its four options verbatim, option "(c) merge without CI if the project allows admin-merge" included. It is finding 2 (per D12).
- Exit-code handling lives only in `SKILL.md` Phase 6 after this task. `CI-MERGE.md` keeps no copy of the watch commands.
- Neither `POST-SELECTION-SYNC.md` nor `CI-MERGE.md` nor `REVIEW.md` names a sibling basename (per D6). In particular, "under [`SYNC.md`]" becomes "under Phase 1's sync rules", "REVIEW.md's durable-detail rules" becomes "Phase 5's durable Minor/Discussion detail", and "see SYNC.md" becomes "Phase 1's scope-creep categories (retirement / addition)".
- Byte targets: `POST-SELECTION-SYNC.md` 4,800, `CI-MERGE.md` 3,000.

- [ ] **Step 1: Re-point the machine-read tests (they fail until Step 3)**

In `tests/test_workflow_skill_contracts.py`, add `SHIP_ISSUE_POST_SELECTION_SYNC = SHIP_ISSUE.parent / "POST-SELECTION-SYNC.md"` beside Task 1's constants. In `SHIP_ISSUE_MACHINE_TEXT`, delete the `SHIP_ISSUE_CI_MERGE` key and add:

```python
    SHIP_ISSUE_POST_SELECTION_SYNC: (
        "--kind current-selection", "--kind sync-selection", "--kind scope", "`test_ref`",
        "launch-commit", "gh pr view <pr-num> --json state,headRefOid,mergeable",
        "git merge --no-commit --no-ff origin/<integration>",
        "git merge-base --is-ancestor <second-parent> origin/<integration>",
        "git show --cc <merge-sha>", "`merge-delta-empty`", "`merge-delta-clean`",
    ),
```

Delete the `SHIP_ISSUE_CI_MERGE` constant when `rg -n SHIP_ISSUE_CI_MERGE home/common/agent-skills/tests` then finds only its definition.

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ship_issue_documents_carry` (timeout 300 s)
Expected: ERROR, a `FileNotFoundError` for `POST-SELECTION-SYNC.md`.

- [ ] **Step 3: Move and cut**

1. `POST-SELECTION-SYNC.md` gets the following, under the headings in Interfaces:
   - `CI-MERGE.md`'s `## Post-selection sync`, whole. Its paragraphs map to the sections in order. The probe sentence ("Step 3 dispatches a reviewer …") opens `## Steps`.
   - `REVIEW.md`'s `## Merge-delta check`, as `## Merge-delta check`, with its first sentence cut ("CI-MERGE.md's … Phase 5 never does"). Step 3 then says "Run the merge-delta check below over …".
   - Rewrite the sibling pointers as in Invariants. Keep `SKILL.md`'s heading names (`## Delivery loop`, `## Launch guard`, `### Local commits`, `## Remainder mode`) and "`SKILL.md`'s merge-delta reviewer".
   - Cut the trigger's restatement "A merge the provider refuses … record no `authority-observation` for it", because `DELIVERY-LOOP.md` step 6 holds that rule. Cut the probe parenthetical "(SKILL.md's Phase-0 reviewer-dispatch probe has already confirmed …)" too, since the steps' opening sentence states the probe.
2. `CI-MERGE.md` keeps only:
   - The 40-minute escalation, as `## Escalation after 40 minutes`. It has one lead sentence ("After the eighth `124`, GitHub Actions webhooks may have failed to fire; escalate with:") and the prompt verbatim.
   - The failing-check route, as `## Failing checks`: pull `gh run view <run-id> --log-failed`, ground against the failing surface (lint → standards doc, test → area spec/plan), surface.
   - The advisory overflow rule, as `## Advisory overflow`: `+<n> more`, a non-null `report_path` named first, and the line in the legacy row's `notes` under lifecycle identity.
   - The worktree merge-exit quirk, as `## Merge exit code in a worktree`. It keeps the `fatal: '<branch>' is already used by worktree` error text and "run Phase 7's verify first".
   - Everything else is cut: the watch rationale, the 244-poll anecdote, the exit-code list (its home is Phase 6), the JSON-field notes, `--no-ff` (Phase 7 holds it), the `--delete-branch` explanation (Phase 7's `git ls-remote` line holds it), and the moved route.
3. `REVIEW.md`: delete `## Merge-delta check`. In `## Delta route`, change "(retirement / addition, see SYNC.md)" to "(retirement / addition)".
4. `SKILL.md`:
   - Index: rewrite the `CI-MERGE.md` bullet as "`CI-MERGE.md` — Phases 6–7: the 40-minute escalation, failing checks, advisory overflow, the worktree merge-exit quirk." Add "`POST-SELECTION-SYNC.md` — a stale or conflicting PR after selection; read it with `SYNC.md` and `REVIEW.md`'s severity mapping and durable detail."
   - Re-point every "CI-MERGE.md's `## Post-selection sync`" and "per CI-MERGE.md" in the Phase-0 probe, Phase 2's opening, Phase 5's merge-delta paragraph and Phase 6's divergence paragraph to `POST-SELECTION-SYNC.md`. Re-point "REVIEW.md's merge-delta scope and checklist" to "its merge-delta check".
   - Change Phase 6's last sentence to "Escalation, failing checks and advisory overflow: [`CI-MERGE.md`](./CI-MERGE.md)."

- [ ] **Step 4: Models**

- `instruction-load.json`: add `ship-issue/POST-SELECTION-SYNC.md` to `conditional` in `ship-owner`, `orchestrated-issue-owner` and `implementation-owner` (per D3).
- `skill-lint-debt.json`: delete `L3 …/ship-issue/CI-MERGE.md`, `L4b …/CI-MERGE.md names REVIEW.md`, `L4b …/CI-MERGE.md names SYNC.md`, `L4b …/REVIEW.md names CI-MERGE.md` and `L4b …/REVIEW.md names SYNC.md` (per D14).
- Run `just agent-instruction-load tighten` (timeout 300 s). The merge-delta check moved out of hot `REVIEW.md`. If the gate reports `ship-owner`'s conditional ceiling breached, set it to the measure and name it in the commit body.

- [ ] **Step 5: Verify**

Run the focused suite, the lint and the gate. Expected: OK, exit 0, `check: pass`.
Run:

```bash
set -euo pipefail
python3 - <<'EOF'
from pathlib import Path
S = Path("home/common/agent-skills/skills/ship-issue")
for name, cap in {"POST-SELECTION-SYNC.md": 4800, "CI-MERGE.md": 3000}.items():
    size = len((S / name).read_bytes())
    if size > cap:
        print(f"over target: {name} {size} > {cap} (name it in the commit body)")
ci = (S / "CI-MERGE.md").read_text(encoding="utf-8")
assert "## Post-selection sync" not in ci and "gh pr checks <pr-num> --required" not in ci
assert "(c) merge without CI if the project allows admin-merge" in " ".join(ci.split())
assert "## Merge-delta check" not in (S / "REVIEW.md").read_text(encoding="utf-8")
EOF
if grep -q 'skills/ship-issue/CI-MERGE.md' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi
```

Expected: exit 0. At Task 1's head it fails, because `CI-MERGE.md` still holds `## Post-selection sync`.

- [ ] **Step 6: Commit**

Commit as `refactor(ship-issue): move the post-selection sync into its route file and cut CI-MERGE.md (#296)`.
