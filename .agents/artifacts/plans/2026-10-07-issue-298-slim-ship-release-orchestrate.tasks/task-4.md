# Task 4: Give the Codex orchestrate-issues stub a third-person trigger description

**Files:**
- Modify: `home/common/codex/skills/orchestrate-issues/SKILL.md` (the `description:` line only)
- Modify: `home/common/agent-skills/skill-lint-debt.json`, `home/common/agent-skills/instruction-load.json` (via `tighten` only)

**Interfaces:**
- Consumes: Task 3's tree, where the ship-release and Claude orchestrate descriptions are already 179 B and 156 B.
- Produces: a stub of ≤ 1,035 B whose description is 153 B. The `L5 home/common/codex/skills/orchestrate-issues/SKILL.md` debt key is gone. The three scoped descriptions total ≤ 511 B (per D8), so `tighten` can only lower `description_ceiling_bytes`.

**Invariants:**
- Only the `description:` line changes. The body stays byte for byte: the spec found each of its 21 lines to be an instruction or its vetted command.
- The new line is exactly: `description: Reports that multi-owner orchestration is unsupported on Codex and names the sequential /from-issue route. Use for "orchestrate issues X, Y, Z" on Codex.`
- The file still starts with `---\nname: orchestrate-issues\n` and still carries `workflow-state host-route --route codex`, `--boundary workflow-response` and `/from-issue <n> --auto` (`test_codex_orchestrate_stub_relays_the_unsupported_route` and `ORCHESTRATE_MACHINE_TEXT` check them; no test changes in this task).

- [ ] **Step 1: Remove the L5 debt key and watch the gate fail**

Delete `"L5 home/common/codex/skills/orchestrate-issues/SKILL.md"` from `skill-lint-debt.json`. It is the array's last entry, so also delete the trailing comma on the line above it.
Run: `PYTHONPATH=python python3 -m agent_tools.skill_lint check` (timeout 300 s)
Expected: non-zero exit with `L5 home/common/codex/skills/orchestrate-issues/SKILL.md: description has no trigger clause (Use when, Use for, Use to, Use before, Use after, Invoke before)`.

- [ ] **Step 2: Replace the description line**

Replace line 3 of the stub with the Invariants line.

- [ ] **Step 3: Models**

Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m agent_tools.skill_lint check`. Expected: exit 0.
Run the focused suite (Global Constraints). Expected: OK.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run:

```bash
set -euo pipefail
PYTHONPATH=python python3 - <<'EOF'
import json, subprocess
from pathlib import Path
from agent_tools import skill_lint
BASE = "75784bed116805ee948d6e2f7f45a6d0ad3b4212"
STUB = "home/common/codex/skills/orchestrate-issues/SKILL.md"
base = subprocess.run(["git", "show", f"{BASE}:{STUB}"], capture_output=True, text=True, check=True).stdout
text = Path(STUB).read_text(encoding="utf-8")
assert skill_lint.parse_frontmatter(text)[1] == skill_lint.parse_frontmatter(base)[1], "body changed"
assert len(text.encode("utf-8")) <= 1035, "stub grew"
total = 0
for path in (STUB, "home/common/claude-code/skills/orchestrate-issues/SKILL.md",
             "home/common/agent-skills/skills/ship-release/SKILL.md"):
    description = skill_lint.parse_frontmatter(Path(path).read_text(encoding="utf-8"))[0]["description"]
    assert "Use for" in description and not description.startswith(("I ", "You ")), path
    total += len(description.encode("utf-8"))
print(f"descriptions {total} bytes")
assert total <= 511, "descriptions grew (D8)"
model = json.loads(Path("home/common/agent-skills/instruction-load.json").read_text(encoding="utf-8"))
assert model["description_ceiling_bytes"] <= 3145, "description ceiling rose"
EOF
if grep -q 'codex/skills/orchestrate-issues' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi
```

Expected: exit 0. At Task 3's head it fails on the stub's description (no `Use for`), and the final `grep` still finds the L5 key.

- [ ] **Step 5: Commit**

Commit `home/common/codex/skills/orchestrate-issues/SKILL.md`, `skill-lint-debt.json` and `instruction-load.json` as `refactor(orchestrate-issues): give the Codex stub a trigger description (#298)`.
