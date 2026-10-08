# Task 3: Cut final-review.md and give it a Contents list

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/sdd/final-review.md`
- Modify: `skill-lint-debt.json`, `instruction-load.json` (by `tighten` only)
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's `SKILL.md` sections `### Review-package gate`, `### Lifecycle workers`, `### Cumulative delivery gate` and `## Finish`.
- Produces: `final-review.md` ≤ 10,500 bytes whose first `## ` heading is `## Contents`, followed by a `- ` list naming every other `##` heading in order. The `L3 home/common/agent-skills/skills/sdd/final-review.md` debt key is gone. ship-issue keeps citing `## Acceptance record` and `## Final verification` (per D9).

**Invariants:**
- Byte for byte (per D8): the four dispatch markers and their `Agent(...)` call lines (`sdd-final-review-fixer`, `sdd-final-conformance-rereview`, `sdd-final-correctness-rereview`, `sdd-final-rereview-escalation`); `review-package PLAN_FILE DELIVERY_BASE DELIVERY_HEAD`; `review-package PLAN_FILE FIX_BASE HEAD`; `<tracker-cli> issue view <num> --repo <repo_slug> --json body`; `Declared verification:`; the scope tokens `` `full` | `scoped: <N> of <M> product files` | `unmeasured` ``; the reviewer identities `` `Codex` | `native` | `fallback` ``; `observed <value> at <sha7> vs threshold <literal>`; ADDRESSED / NOT ADDRESSED; the grading tokens `met`, `unmet`, `unverified`, `human_pending` and `met (attested)`; the acceptance-record fence (labeled `markdown`) with its heading and table header; the lifecycle argv `workflow-state register-worker …`, `launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker_id> -- <git commit arguments>`, `workflow-state release-worker … --event returned`; `verified-tree check --verification <id>`, `verified-tree record --tree <the checked tree>`; the ledger lines `Final verification: passed (head <full sha>, tree <tree id>)` and `Final verification: none declared`.
- Axis routing shrinks to the three rungs (`blocked` stops; `available` with `codex-collaboration` installed → its `diff-review`; `unsupported` or not installed → the native Opus/high reviewer of `correctness-reviewer-prompt.md`) and the routing-error rule (a Codex call under `unsupported`: discard its outcome, ledger the routing error with identity `native`, run rung 3, no retry). Transport, capacity and fallback details go, because `diff-review` owns them.
- The first-pass package runs once on the ledger's pinned `DELIVERY_BASE`/`DELIVERY_HEAD`, never a recomputed merge base, and applies "`SKILL.md`'s `### Review-package gate`" by name; those two pins are the report's `base_sha`/`head_sha` and the fix wave does not move them. The file no longer contains `artifact-budget validate-report`, `stable-first-fit-whole-file`, the interface-version or EF designer reading rules (per D4, D15), or the review-study sentence.
- Both axes get the manifest root path and four metrics, never shard lists or diff contents; they run in parallel as isolated subagents; the two reports are never merged; both verdicts, the correctness identity and its scope are ledgered.
- The acceptance-criteria block, acceptance-verdict rules, "never parked", fixer rules (verify findings against the live worktree, one Opus/high fixer, focused tests only, dedupe at dispatch crediting both axes), the scoped re-review inputs and their gate, the conformance re-review rules, and "no second fix wave" all keep their meaning. The per-finding-fixer cost story goes.
- `## Acceptance record` keeps its placement rule, path `<plans dir>/<plan stem>.acceptance.md`, schema, column ownership, freshness rule and commit route. `## Final verification` keeps the capability routing and its four numbered steps.
- The file names `SKILL.md` sections by heading and the payloads `conformance-reviewer-prompt.md` and `correctness-reviewer-prompt.md`; it never names `fix-loop.md`.

- [ ] **Step 1: Remove the debt key first (the lint fails until Step 4)**

Delete `"L3 home/common/agent-skills/skills/sdd/final-review.md"` from `skill-lint-debt.json` (per D12).

- [ ] **Step 2: Watch the gate fail**

Run: `PYTHONPATH=python python3 -m agent_tools.skill_lint check` (timeout 300 s).
Expected: non-zero exit, with a line naming `L3 home/common/agent-skills/skills/sdd/final-review.md` (276 reflowed lines, no `## Contents`).

- [ ] **Step 3: Cut final-review.md**

Open with a one-line purpose, then `## Contents`. Apply the Invariants and spec § Cutting rules per document (`final-review.md`). Any `##` heading you add for the axis or fix-wave parts is listed in `## Contents`.

- [ ] **Step 4: Test edit (spec § Test changes item 5)**

In `tests/test_workflow_skill_contracts.py`, `SDD_MACHINE_TEXT[SDD_DIR / "final-review.md"]` loses `PRODUCER_VALIDATION` and `WHOLE_FILE_POLICY`; its other five items stay (per D15).

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
text = Path("home/common/agent-skills/skills/sdd/final-review.md").read_text(encoding="utf-8")
flat = re.sub(r"\s+", " ", text)
size = len(text.encode("utf-8"))
print(f"final-review.md {size} bytes, {skill_lint.reflowed_lines(text)} reflowed lines")
if size > 10500:
    print("over target: name it in the commit body")
assert skill_lint.has_contents(text), "## Contents first"
assert text.count("<!-- agent-dispatch:") == 4
for gone in ("artifact-budget validate-report", "stable-first-fit-whole-file", "review study",
             "interface version", "fix-loop.md"):
    assert gone not in flat, gone
assert "`SKILL.md`'s `### Review-package gate`" in flat
for heading in ("## Acceptance record", "## Final verification"):
    assert text.count(f"\n{heading}\n") == 1, heading
assert "```markdown\n# Acceptance record — issue #<n>" in text
EOF
if grep -q 'sdd/final-review.md' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi
```

Expected: exit 0. At Task 2's head it fails on `## Contents first`.
Run the lint. Expected: exit 0.
Run the focused suite. Expected: OK.
Run `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run the D13 diff-bound script. Expected: exit 0.

- [ ] **Step 7: Commit**

Commit `skills/sdd/final-review.md`, `skill-lint-debt.json`, the test file and `instruction-load.json` as `refactor(sdd): cut the final review and give it a contents list (#297)`.
