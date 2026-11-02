# Task 2: Cut ship-release CHANGELOG.md and add its Contents

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/ship-release/CHANGELOG.md`
- Modify: `skill-lint-debt.json`, `instruction-load.json` (via `tighten` only)
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's `skills/ship-release/SKILL.md` (≤ 20,500 B target, no `## The flow`, still linking `CHANGELOG.md#version-bump-signals`).
- Produces: a `CHANGELOG.md` of ≤ 7,500 B that starts its headings with a `## Contents` list. The `L3 home/common/agent-skills/skills/ship-release/CHANGELOG.md` debt key is gone. The `RETAINED_SUPPORT_CONTRACTS` row for this file is gone. `SKILL.md` + `CHANGELOG.md` together are ≤ 29,890 B (the spec's binding constraint for AC3).

**Invariants:**
- Byte for byte, from base: all four fenced blocks — the Step 1 `git fetch`/`git log` fence, the Step 1 `gh pr list --search` fence, the Step 5 PR-body template fence (the template is the PR body's output shape; the spec's Targets count it as fixed text), and the Version-bump worked-example fence.
- Kept text: the inline span `git describe --tags --abbrev=0 origin/<default>`; the slug sentence (URLs come from `bindings.tracker.repo_slug`, never a hardcoded owner/name); the single-branch range rule with its shell-variable clause (per D5); the PR-resolution capability rule and the no-PR commit-URL rule; the Step 2 decision table and its judgment notes; the Step 3 entry rule, its Bad/Good table and the bullets an agent would otherwise get wrong (full PR URL never bare `#N`, ADR links only from passed context paths, two entries for two changes); the Step 3 `bindings.paths.hints` sentence; Step 4's shape quote and one tone line; the empty-section and `deploy.adapter == none` rules after the template; the final `bindings.vcs` trailer line.
- `## Version bump signals` keeps its heading, its link `./SKILL.md#45d-decide-major--minor--patch`, "this table is the only copy of the rubric", top-down first-match, the table, the pre-1.0 caveat, the worked example and its one-line verdict, and the four ambiguity rules (each as its rule, without its rationale sentence).
- The sentence "This included document receives the phase owner's retained `ResolvedProject`; …" is deleted together with the `RETAINED_SUPPORT_CONTRACTS` row (#295 D10).
- `## Quality check before opening the PR` and `## Anti-patterns` become one checklist under the first heading, with each check once (per spec Duplicated text). `## Anti-patterns` is removed.
- `## Contents` is the first `##` heading outside fences and is followed by a `- ` list naming each remaining `##` section in order.

- [ ] **Step 1: Delete the support-contract row (the test now passes trivially) and the L3 debt key**

In `tests/test_workflow_skill_contracts.py`, delete the line `"ship-release/CHANGELOG.md": ("bindings.tracker", "bindings.vcs", "bindings.workflow.release"),` from `RETAINED_SUPPORT_CONTRACTS`. The dict keeps its other five rows; `assert_retained_policy_support` and both its callers stay unchanged. In `skill-lint-debt.json`, delete `"L3 home/common/agent-skills/skills/ship-release/CHANGELOG.md",`.

- [ ] **Step 2: Watch the gate fail**

Run: `PYTHONPATH=python python3 -m agent_tools.skill_lint check` (timeout 300 s)
Expected: non-zero exit with `L3 home/common/agent-skills/skills/ship-release/CHANGELOG.md: 224 reflowed lines and no ## Contents list before its first other ## heading`.

- [ ] **Step 3: Cut by content class and add `## Contents`**

1. Preface: one sentence saying this file owns the PR body's content (rubric, template, bump signals) and `SKILL.md` the workflow; the `<integration>`/`<default>` and slug sentence. Delete the retained-`ResolvedProject` sentence and the operator-audience paragraph.
2. Add `## Contents` with one `- ` line per remaining `##` section.
3. Step 1: fences unchanged; one line for the field and record separators; the single-branch rule, trimmed but with the shell-variable clause; the PR-resolution and no-PR rules; "read the PR body: it carries intent".
4. Step 2: table and judgment notes; cut padding phrasing only.
5. Step 3: keep as listed in Invariants; cut "Don't include the SHA" only if the Bad/Good table already shows it.
6. Step 4: the shape quote, then one line: factual tone, and a merge count is not a synthesis.
7. Step 5: the fence unchanged; keep the empty-section and `deploy.adapter == none` rules; cut the sentence explaining why the raw list is collapsible.
8. Merge `## Anti-patterns` into `## Quality check before opening the PR`: a single checklist covering the 90-second read, which PR to suspect, Deploy notes reflected in the deploy env before merging, Highlights earned, no `Various`/`Misc`, no flat SHA dump, no process-as-content entries, no internal churn in Highlights. Then one line: any "no" means iterate before opening.
9. `## Version bump signals`: keep per Invariants; cut "Operators needing to coordinate…", "Compatible from the application's side…" and "The cost is asymmetric" style rationale, keeping each ambiguity rule's verdict.
10. Keep the trailing `bindings.vcs` line.

- [ ] **Step 4: Models**

Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 5: Verify**

Run: `PYTHONPATH=python python3 -m agent_tools.skill_lint check`. Expected: exit 0.
Run the focused suite (Global Constraints). Expected: OK.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run:

```bash
set -euo pipefail
PYTHONPATH=python python3 - <<'EOF'
import subprocess
from pathlib import Path
from agent_tools import skill_lint
BASE = "75784bed116805ee948d6e2f7f45a6d0ad3b4212"
PATH = "home/common/agent-skills/skills/ship-release/CHANGELOG.md"
SKILL = "home/common/agent-skills/skills/ship-release/SKILL.md"
base = subprocess.run(["git", "show", f"{BASE}:{PATH}"], capture_output=True, text=True, check=True).stdout
text = Path(PATH).read_text(encoding="utf-8")
def fences(t):
    out, cur = [], None
    for line in t.splitlines(keepends=True):
        if cur is None:
            if line.startswith("```"):
                cur = [line]
        else:
            cur.append(line)
            if line.startswith("```"):
                out.append("".join(cur)); cur = None
    return out
blocks = fences(base)
assert len(blocks) == 4, len(blocks)
for block in blocks:
    assert block in text, "fence changed: " + block.splitlines()[1]
assert skill_lint.has_contents(text), "no ## Contents list first"
for kept in ("## Version bump signals", "./SKILL.md#45d-decide-major--minor--patch",
             "`git describe --tags --abbrev=0 origin/<default>`", "bindings.tracker.repo_slug"):
    assert kept in text, kept
for gone in ("retained `ResolvedProject`", "## Anti-patterns", "The cost is asymmetric"):
    assert gone not in text, gone
size = len(text.encode("utf-8"))
pair = size + len(Path(SKILL).read_bytes())
print(f"CHANGELOG.md {size} bytes; SKILL.md + CHANGELOG.md {pair} bytes")
assert pair <= 29890, "ship-release pair over the AC3 binding constraint"
if size > 7500:
    print("over target (name it in the commit body)")
EOF
if grep -q 'ship-release/CHANGELOG.md' home/common/agent-skills/skill-lint-debt.json home/common/agent-skills/tests/test_workflow_skill_contracts.py; then exit 1; fi
```

Expected: exit 0. At Task 1's head it fails on the missing `## Contents`.

- [ ] **Step 6: Commit**

Commit `skills/ship-release/CHANGELOG.md`, `tests/test_workflow_skill_contracts.py`, `skill-lint-debt.json` and `instruction-load.json` as `refactor(ship-release): cut CHANGELOG.md and give it a Contents list (#298)`.
