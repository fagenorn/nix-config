# Task 2: Frame sentence, budget offset and CLAUDE.md limits note

**Files:**
- Modify: `home/common/agent-guidance/AGENTS.md`
- Modify: `home/common/agent-skills/skills/doc-grounded-questions/REFERENCE.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Task 1's implemented guard behavior (`home/common/claude-code/lifecycle_guard.py`: `RAISE_LABEL`, `adds_raise_label`, the `label` operation refused first in `main()`). The `CLAUDE.md` sentence below must describe that code as committed; read it before writing the sentence.
- Produces: no code interface. The corpus change the `Instruction Budget` gate measures: +61 B frame, −116 B reference (D4).

**Invariants:**
- `AGENTS.md` ends with exactly its current 580 bytes, then `\n`, then the line `` Only the user applies the `instruction-budget-raise` label. `` and `\n` (61 bytes added). No other byte of `AGENTS.md` changes (D3, D4).
- `REFERENCE.md` loses exactly the 116 bytes `This does two things at once: shows the homework, and frames the question\nprecisely around what's actually unknown. ` (including its line break and trailing space), so its line reads `When the docs fully answer it:`. The worked example and the `"Per <ADR-NNN>…"` line stay (D4).
- No skill file restates the rule (D3); `instruction-load.json` and the gate files are untouched; `tighten` is not run (D4).
- `CLAUDE.md` is outside the instruction corpus; only its Claude Code guard bullet changes.

- [ ] **Step 1: Confirm the gates fail at the start commit**

Run:
```bash
grep -qxF 'Only the user applies the `instruction-budget-raise` label.' home/common/agent-guidance/AGENTS.md && echo present || echo absent
grep -c 'This does two things at once' home/common/agent-skills/skills/doc-grounded-questions/REFERENCE.md
grep -c '#294' CLAUDE.md
```
Expected: `absent`, `1`, `0`.

- [ ] **Step 2: Edit the frame and the reference**

Append the frame paragraph and cut the reference sentence with an exact-byte edit (Python `str.replace` with a `count == 1` assertion, not `sed`), per the two invariants above.

- [ ] **Step 3: Edit the CLAUDE.md guard bullet**

In the `just show-claude-settings` bullet:
1. Replace `and hands four lifecycle verbs to a fail-closed `PreToolUse` hook.` with `and hands four lifecycle verbs, and the raise-label rule below, to a fail-closed `PreToolUse` hook.`
2. Immediately after the sentence ending `that any change here must keep green.`, insert this sentence, adjusted only where Task 1's committed code behaves differently (then describe the code, not this text):

> The hook also refuses an agent adding the `instruction-budget-raise` label (#294): in a segment that mentions that label, case-insensitively, a `gh` invocation in any position whose `--add-label` value contains it is blocked, in every repository and before any other verb is judged, and an unparseable command or `eval`/`sh -c` source that mentions the label blocks too, while other labels, `--remove-label` and quoted mentions pass. This catches mistakes and is not enforcement: Codex has no hook, and `gh api`, GraphQL and `curl` are outside the guard, so the protection that holds is the required `Instruction Budget` check plus the user seeing the label on the PR (`.agents/knowledge/rejections/ungated-agent-merges.md`).

- [ ] **Step 4: Verify**

Run (timeout 600 s):
```bash
set -euo pipefail
grep -qxF 'Only the user applies the `instruction-budget-raise` label.' home/common/agent-guidance/AGENTS.md
test "$(wc -c < home/common/agent-guidance/AGENTS.md | tr -d ' ')" = 641
if grep -q 'This does two things at once' home/common/agent-skills/skills/doc-grounded-questions/REFERENCE.md; then exit 1; fi
grep -q 'When the docs fully answer it:' home/common/agent-skills/skills/doc-grounded-questions/REFERENCE.md
grep -q 'instruction-budget-raise` label (#294)' CLAUDE.md
if git diff --name-only origin/main -- home/common/agent-skills/instruction-load.json .github | grep -q .; then exit 1; fi
PYTHONPATH=python python3 -m agent_tools.instruction_load check --base origin/main 2>&1 | tail -3
PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -3
```
Expected: every line succeeds, the gate prints `check: pass` (no `--raise-label`), and the unit tests print `OK`. A gate failure means the byte arithmetic is off (D4): fix the edit, never raise a ceiling or run `tighten`.

- [ ] **Step 5: Commit**

Commit the three files through the lifecycle commit command your brief names (`launch-commit … -- <git commit args>`), subject `docs(guidance): only the user applies the instruction-budget-raise label (#294)`, with the brief's trailers.
