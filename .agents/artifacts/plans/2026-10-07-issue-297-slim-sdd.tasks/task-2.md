# Task 2: Cut fix-loop.md under 100 lines

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/sdd/fix-loop.md`
- Modify: `skill-lint-debt.json`, `instruction-load.json` (by `tighten` only)
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's `SKILL.md`, whose `### Review-package gate` is the one home of the gate, and its `### Lifecycle workers` section.
- Produces: `fix-loop.md` ≤ 4,300 bytes and ≤ 95 reflowed lines, with no `## Contents` (it is under 100). The `L3 home/common/agent-skills/skills/sdd/fix-loop.md` debt key is gone.

**Invariants:**
- Byte for byte (per D8): the six dispatch markers and their `Agent(...)` call lines, in their current order (`sdd-task-fix-redispatch`, `sdd-codex-rescue-transport`, `sdd-post-rescue-implementation`, `sdd-rescue-fallback-implementation`, `sdd-round-five-implementation`, `sdd-task-rereview-escalation`); the ledger formats `Task <N>: fix round <R>/5 (<X> addressed, <Y> open — <one-liners>; commits <a7>..<b7>)`, `Task <N>: parked — <finding> — ruling: <why the code stands>` and `Task <N>: BLOCKED — <reason>`; the range argv `review-package PLAN_FILE FIX_BASE HEAD`; the `Lifecycle worker:` token.
- The five rounds keep their tiers, order and caps: rounds 1–3 resume the original implementer at its launch tier (a BLOCKED-escalated task stays on Opus/high via another `sdd-blocked-reasoning-escalation` dispatch); round 4 is the Codex stuck-breaker, "verify its diagnosis against the live worktree", then Opus/high, with the Codex-unavailable fallback framing; round 5 is the last, on Opus/high. Round 4's explanation shrinks to one clause: three same-context failures escalate the model, not only the context.
- Every round's fix report (what changed, covering tests, command, output) is confirmed before the re-review; implementers never run the full declared verification.
- The lifecycle-workers line names `SKILL.md`'s `### Lifecycle workers`, keeps "fresh `worker_id`" per round, the `Lifecycle worker:` line in the prompt or resume message, the release on return, and "a `launch fence refused` report ends the loop".
- The re-review paragraph runs `review-package PLAN_FILE FIX_BASE HEAD` (FIX_BASE = the head the previous review saw) and applies "`SKILL.md`'s `### Review-package gate`" by name; it no longer contains `artifact-budget validate-report` or the exit routes (per D3, D15). It keeps the re-review inputs (findings, brief and report paths, manifest root path and four metrics; never shard lists or diff contents), ADDRESSED / NOT ADDRESSED, new-breakage-only scope, deferred minors, and the escalation site.
- The breaker keeps its three outcomes and "adjudicate only at the cap; every adjudication is a ledger entry".
- `## Common rationalizations` is deleted. The file names no sibling reference file (`final-review.md`); it may name the payload `re-review-prompt.md`.

- [ ] **Step 1: Remove the debt key first (the lint fails until Step 4)**

Delete `"L3 home/common/agent-skills/skills/sdd/fix-loop.md"` from `skill-lint-debt.json` (per D12).

- [ ] **Step 2: Watch the gate fail**

Run: `PYTHONPATH=python python3 -m agent_tools.skill_lint check` (timeout 300 s).
Expected: non-zero exit, with a line naming `L3 home/common/agent-skills/skills/sdd/fix-loop.md` (114 reflowed lines, no `## Contents`).

- [ ] **Step 3: Cut fix-loop.md**

Apply the Invariants and spec § Cutting rules per document (`fix-loop.md`). Cut rationale ("the report file is the persistent memory", "reviewers do not re-run tests" stays only as the rule to confirm the fix report), the gate restatement and the rationalizations table.

- [ ] **Step 4: Test edit (spec § Test changes item 5, per D17)**

In `tests/test_workflow_skill_contracts.py`, delete the whole `SDD_DIR / "fix-loop.md": (PRODUCER_VALIDATION,),` entry from `SDD_MACHINE_TEXT`. Add no replacement item.

- [ ] **Step 5: Models**

Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 6: Verify**

Run (timeout 120 s):

```bash
set -euo pipefail
PYTHONPATH=python python3 - <<'EOF'
import re
from pathlib import Path
from agent_tools import skill_lint
text = Path("home/common/agent-skills/skills/sdd/fix-loop.md").read_text(encoding="utf-8")
flat = re.sub(r"\s+", " ", text)
lines, size = skill_lint.reflowed_lines(text), len(text.encode("utf-8"))
print(f"fix-loop.md {size} bytes, {lines} reflowed lines")
assert lines <= 100, "L3 line"
if lines > 95 or size > 4300:
    print("over target: name it in the commit body")
assert text.count("<!-- agent-dispatch:") == 6
assert "## Common rationalizations" not in text
assert "artifact-budget validate-report" not in flat
assert "`SKILL.md`'s `### Review-package gate`" in flat
assert "review-package PLAN_FILE FIX_BASE HEAD" in flat
assert "final-review.md" not in text
EOF
if grep -q 'sdd/fix-loop.md' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi
```

Expected: exit 0. At Task 1's head it fails on `L3 line` (114).
Run the lint. Expected: exit 0.
Run the focused suite. Expected: OK.
Run `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run the D13 diff-bound script. Expected: exit 0.

- [ ] **Step 7: Commit**

Commit `skills/sdd/fix-loop.md`, `skill-lint-debt.json`, the test file and `instruction-load.json` as `refactor(sdd): cut the fix loop under 100 lines (#297)`.
