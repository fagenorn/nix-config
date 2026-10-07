# Task 4: Cut HUMAN-GATE.md to the gates it alone holds

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/ship-issue/HUMAN-GATE.md`
- Modify: `instruction-load.json` (`tighten` only), `skill-lint-debt.json`
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 3's tree. `SKILL.md` Phase 4 still holds the `git push -u origin <branch>` fence and the guard-form `gh pr create` fence, which are the only copies after this task (per D7).
- Produces: `HUMAN-GATE.md` headed `# Consolidated operator gate`, with these `##` headings in order: `When to enter`, `In --auto`, `Gate 1 — before the first push (Phase 4)`, `Gate 2 — after CI, before the merge (Phase 7)`, `Grant semantics`, `Never route around a denial`.

**Invariants:**
- The `--auto` paragraph keeps both cases with their meaning. A fresh ship owner presents the block and returns a truthful `stopped` ship summary, validated through `artifact-budget validate-report --boundary ship-summary`, keeping the worktree. A `from-issue` owner running the path itself follows from-issue's suspension procedure (`blocked_on: human_gate`, the canonical re-entry line). It keeps the sentence "This file defines no new suspension shape and no new `blocked_on` value." The owner-runs-itself case is a cited anchor (per D4), and from-issue's `SKILL.md` names it.
- Gate 1 presents Phase 4's two commands as rendered there, in that order, fully rendered (bindings substituted, the `## Acceptance` section filled, the `Closes #<num>` trailer present on the close branch and absent on a hold). It carries no copy of either command (per D7). It still says that Gate 2 follows and what it will cover.
- Gate 2 keeps its chain list in order, with every command spelled as today: `gh issue close <num>`; the hold branch's `gh issue reopen <num>`, `gh label create needs-verification`, `gh issue edit <num> --add-label needs-verification`, `gh issue comment <num>`; `git push origin --delete <branch>` gated on `git ls-remote --heads origin <branch>`; `git worktree remove <worktree-path>`; `git branch -d <branch>`.
- `## Grant semantics` keeps its four rules. `## Never route around a denial` keeps its heading and its seven-item ban list byte for byte (per D11). No bypass spelling (`--admin`, `--force`, `--force-with-lease`, `git merge`, `git push origin <integration>`, `git reset`, `git rebase`) appears before that heading.
- Byte target: 3,800, at ≤ 100 reflowed lines.

- [ ] **Step 1: Re-point the machine-read test and delete the pin on the cut sentence**

In `tests/test_workflow_skill_contracts.py`:
- Replace the `SHIP_ISSUE_HUMAN_GATE` key of `SHIP_ISSUE_MACHINE_TEXT` (per D16):

```python
    SHIP_ISSUE_HUMAN_GATE: (
        "gh issue close <num>", "gh issue reopen <num>", "gh label create needs-verification",
        "gh issue edit <num> --add-label needs-verification", "gh issue comment <num>",
        "git push origin --delete <branch>", "git ls-remote --heads origin <branch>",
        "git worktree remove <worktree-path>", "git branch -d <branch>",
        "validate-report --boundary ship-summary", "## Never route around a denial",
    ),
```

- `RETAINED_SUPPORT_CONTRACTS`: delete the `"ship-issue/HUMAN-GATE.md"` row (spec item 3).
- Leave `test_human_gate_carries_no_affirmative_bypass_instruction` unchanged (per D11).

- [ ] **Step 2: Run the focused tests**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ship_issue_documents_carry -k bypass_instruction -k listed_support_documents` (timeout 300 s)
Expected: OK at Task 3's head. Every new item already holds there.

- [ ] **Step 3: Cut**

1. `## When to enter`: one paragraph. Enter only when `SKILL.md`'s `## Standing authorization` finds no policy or grant for the concrete action and target. Enter instead of attempting the verb. There are at most two gates, before the first push and before the merge, and only those that lack authority are entered. The gate makes effects reviewable but does not grant them, and the host's approval decision still governs. Cut the policy-support sentence.
2. `## In --auto`: the `--auto` paragraph, kept whole except for its pointer to from-issue's auto paragraph ("exactly as `from-issue/AUTO.md`'s final paragraph already says"), which is cut.
3. Gate 1: delete both fences and the `## Spec` / `## Plan` / `## Acceptance` body lines they carry. In their place write: "Present Phase 4's `git push` and `gh pr create` commands, in that order, as literal text the operator can read and repeat in their own message." Then keep the rendering sentence and the Gate-2 notice from Invariants. Cut "Both commands are fully determined at this moment, so neither needs a later correction."
4. Gate 2: cut "Its `<pr-num>` exists only now, which is why this cannot be folded into Gate 1." and "Phase 6's CI wait has already bound before this gate is entered, and the grant does not re-litigate it." Keep the chain list and the after-grant paragraph.
5. `## Grant semantics`: keep the four bullets, the fourth with its clause "the merge still requires the base branch's required status check". Cut its last sentence, "Nothing here weakens `.agents/knowledge/rejections/ungated-agent-merges.md`.", which that clause already states.
6. `## Never route around a denial`: keep it byte for byte, except the restating lead sentence "It restates for this path the ban Phase 1 already places on rewriting the integration branch.", which is cut.
7. Delete `## Delivery interface version 2`.

- [ ] **Step 4: Models**

- `skill-lint-debt.json`: delete `L3 …/ship-issue/HUMAN-GATE.md` (per D14).
- Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 5: Verify**

Run the focused suite, the lint and the gate. Expected: OK, exit 0, `check: pass`.
Run:

```bash
set -euo pipefail
PYTHONPATH=python python3 - <<'EOF'
from pathlib import Path
from agent_tools import skill_lint
text = Path("home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md").read_text(encoding="utf-8")
if len(text.encode()) > 3800:
    print(f"over target: HUMAN-GATE.md {len(text.encode())} > 3800 (name it in the commit body)")
assert skill_lint.reflowed_lines(text) <= 100
for gone in ("gh pr create --repo", "git push -u origin <branch>", "## Delivery interface version 2",
             "retained `ResolvedProject`"):
    assert gone not in text, gone
EOF
```

Expected: exit 0. At Task 3's head it fails, because `HUMAN-GATE.md` still holds the `gh pr create` fence.

- [ ] **Step 6: Commit**

Commit as `refactor(ship-issue): cut HUMAN-GATE.md to the operator gates (#296)`.
