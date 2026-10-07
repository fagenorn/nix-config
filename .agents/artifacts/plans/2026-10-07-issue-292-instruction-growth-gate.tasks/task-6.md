# Task 6: Test policy, CLAUDE.md mentions, final tighten and budget check

Per D1, D2, D7, D13 (and program D6). Measures issue #292 AC5 (recorded as remaining) and AC6. This is the final task. Its last step runs after every other edit in the plan.

**Files:**
- Modify: `docs/standards/agent-helpers.md` (add rule 6 after rule 5, before the closing lifecycle-guard paragraph)
- Modify: `docs/standards/README.md` (the `agent-helpers.md` row)
- Modify: `CLAUDE.md` (the CI paragraph under `## Commands`, and one line in its `sh` block)
- Modify: `home/common/agent-skills/instruction-load.json` (only if `tighten` lowers something)

**Interfaces:**
- Consumes: `python3 -m agent_tools.instruction_load tighten` and `check [--base REV]` (Task 4); `python3 -m agent_tools.skill_lint check` (Task 2); `.github/workflows/instruction-budget.yaml` and the two-context payload (Task 5).
- Produces: none for later tasks.

**Invariants:**
- No skill document, `AGENTS.md` frame or agent definition changes, so no measured instruction byte moves in this task (`CLAUDE.md` and `docs/` are not measured).
- `CLAUDE.md` changes are limited to naming both required contexts and the one Commands line (spec "The workflow and protection"; program "Out of scope").
- After the final step, `loose(...)` and `breached(...)` are both empty for the live tree, and `check --base origin/main` exits 0.
- No step runs `just protect-main`, `just unprotect-main`, `gh api` with a write method, or creates the label (per D2).

- [ ] **Step 1: Write the failing check**

Run:
```bash
set -u
fail=0
grep -q '^6\. \*\*Skill-text tests pin only what a tool or subagent consumes\.\*\*' docs/standards/agent-helpers.md || { echo "rule 6 missing"; fail=1; }
grep -q 'home/common/agent-skills/tests/\*\*' docs/standards/README.md || { echo "governs glob missing"; fail=1; }
if grep -q 'remains the sole required context' CLAUDE.md; then echo "CLAUDE.md still says sole"; fail=1; fi
grep -q '^just agent-instruction-budget' CLAUDE.md || { echo "Commands line missing"; fail=1; }
exit $fail
```
Expected now: exit 1, printing all four messages.

- [ ] **Step 2: Write the documentation**

Insert into `docs/standards/agent-helpers.md`, as a new paragraph after rule 5 (blank line before and after):

```markdown
6. **Skill-text tests pin only what a tool or subagent consumes.** A test under `home/common/agent-skills/tests/` may assert the dispatch marker lines and the `Agent(...)` call lines mirrored in `model-matrix.json`, the carrier clauses `test_dispatch_contracts` places in dispatch regions, shell examples vetted by `test_shell_example_contracts`, frontmatter, the JSON key sets of lifecycle contracts, and `workflow-state`/`resolve-project` argv. No new test pins an English phrase. Existing phrase pins are deleted in the slice that slims their skill, and a heading anchor that only tests read may be renamed with its test in the same commit. ([design](../../.agents/artifacts/specs/2026-10-07-issue-291-skill-best-practices-design.md))
```

In `docs/standards/README.md`, on the `agent-helpers.md` row:
- Append `, `home/common/agent-skills/tests/**`` to the `governs` cell, after `home/common/claude-code/lifecycle_guard.py`.
- Append ` Skill-text tests pin only machine-consumed text.` to the Gist cell (per D13).

In `CLAUDE.md`:
- In the `sh` block under `## Commands`, add after the `just show-claude-settings` line:
  `just agent-instruction-budget # the Instruction Budget gate against origin/main (--raise-label for a labelled raise)`
- In the CI paragraph, replace `and is the context `.github/branch-protection.json` makes required on `main`**` with `and is one of the two contexts `.github/branch-protection.json` makes required on `main`, the other being `Instruction Budget` (`.github/workflows/instruction-budget.yaml`), with `strict` on**`.
- Replace `is refused until `Nix Eval` is green` with `is refused until both are green on a branch that is up to date with `main``.
- Replace `; `Nix Eval` remains the sole required context.` with `, which is not a required context.`

Change nothing else in `CLAUDE.md`.

- [ ] **Step 3: Run the check again**

Run the Step 1 script.
Expected: exit 0, no output.

- [ ] **Step 4: Final tighten and budget check (last step of the plan)**

Run, in order, with nothing edited in between:

```bash
PYTHONPATH=python timeout 300 python3 -m agent_tools.instruction_load tighten; echo "tighten exit=$?"
PYTHONPATH=python timeout 300 python3 -m agent_tools.skill_lint check; echo "lint exit=$?"
PYTHONPATH=python timeout 300 python3 -m agent_tools.instruction_load check; echo "push-mode exit=$?"
PYTHONPATH=python timeout 300 python3 -m agent_tools.instruction_load check --base origin/main; echo "pr-mode exit=$?"
PYTHONPATH=python python3 - <<'EOF'
from pathlib import Path
from agent_tools import instruction_load as il, skill_lint
snapshot = skill_lint.working_tree(Path("."))
model = il.load_model(snapshot.read(il.MODEL_PATH))
found = il.ceilings(model, il.measure(model, snapshot.read), il.measure_corpus(snapshot))
bad = [c.label for c in il.loose(found) + il.breached(found)]
print(len(found), "ceilings;", "outside the band:", bad)
raise SystemExit(1 if bad else 0)
EOF
```

Expected:
- `tighten exit=0`. It prints `lowered …` lines only if an earlier task left slack.
- `lint exit=0`, `push-mode exit=0` (`check: pass`) and `pr-mode exit=0`, with the stderr note that the base has no gate workflow (D1).
- The script prints an empty `outside the band` list and exits 0.

If `tighten` changed `instruction-load.json`, run `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py`. Expected: PASS.

Record acceptance-record row AC5 as `remaining — user-run after merge (D2): just protect-main, then just show-protection shows "Instruction Budget" and "strict": true`. Record AC6 as measured by the commands above, and by the `Instruction Budget` job on the PR.

- [ ] **Step 5: Commit**

```bash
git add docs/standards/agent-helpers.md docs/standards/README.md CLAUDE.md home/common/agent-skills/instruction-load.json
git commit -m "docs: record the skill-text test policy and the two required contexts (#292)"
```

`git add` of an unchanged `instruction-load.json` is a no-op.
