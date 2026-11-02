# Task 4: Cut the task-loop payloads

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/sdd/implementer-prompt.md`, `skills/sdd/task-reviewer-prompt.md`, `skills/sdd/re-review-prompt.md`
- Modify: `instruction-load.json` (by `tighten` only)

**Interfaces:**
- Consumes: Task 3's tree. `SKILL.md` §1 and §3 and `fix-loop.md` fill these payloads' placeholders and dispatch them.
- Produces: `implementer-prompt.md` ≤ 5,200 bytes, `task-reviewer-prompt.md` ≤ 6,000, `re-review-prompt.md` ≤ 4,200. Placeholder names are unchanged, so no dispatch site changes.

**Invariants:**
- Each payload stays self-contained and shares no block with another file (per D5); it is cut only for redundancy within itself.
- Outside the fence (spec § Content classes, "Payload preamble"): the H1 title, then at most one non-empty line before the first dispatch marker; `implementer-prompt.md` keeps its one site-selector line before its second marker. The markers and call lines are byte for byte: `sdd-mechanic-implementation`, `sdd-nonmechanical-implementation`, `sdd-first-pass-task-review`, `sdd-scoped-task-rereview`. The two reviewer payloads' `**Placeholders:**` list after the fence stays with every placeholder name; descriptions may shorten. The closing "returns" summary line may go.
- Inside the fence: exactly one unlabeled fence per file; the `Subagent (...)` header, `description:`, the `model:`/`effort:` lines where present and `prompt: |` stay; the four leaf clauses stay byte for byte, each exactly once after `prompt: |`; every placeholder (`[BRIEF_FILE]`, `[REPORT_FILE]`, `[GLOBAL_CONSTRAINTS]`, `[BASE_SHA]`, `[FIX_BASE_SHA]`, `[HEAD_SHA]`, `[FINDINGS]`, `[MANIFEST_ROOT]`, `[ROOT_BYTES]`, `[TOTAL_BYTES]`, `[FILE_COUNT]`, `[LARGEST_MEMBER_BYTES]`, `Task N`, `[task name]`) stays where it is used.
- Output contracts stay byte for byte (per D8): the implementer's `- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT` line, the five report bullets, `launch fence refused: <reason>`, "Never deliver it via SendMessage"; the task reviewer's `### Spec Compliance` (✅/❌/⚠️), `### Strengths`, `### Issues` with `#### Critical (Must Fix)`, `#### Important (Should Fix)`, `#### Minor (Nice to Have)`, `### Assessment` and `**Task quality:** [Approved | Needs fixes]`; the re-reviewer's `### Finding Verdicts` (ADDRESSED | NOT ADDRESSED), `### New Breakage in the Fix Diff`, `### Out-of-Scope Observations`, `### Verdict` and `**Fix round:**`.
- `implementer-prompt.md`'s `## Lifecycle Worker` keeps its three argv byte for byte (`launch-commit … -- <git commit arguments>`, `launch-scope exec … -- <argv>`, `launch-scope scratch …`), "only the most recent one governs", and the exit-3 route.
- Reviewer manifest paragraph (task reviewer and re-reviewer), one compressed paragraph each that keeps every reviewer rule in spec § Cutting rules per document (Payloads): validate coverage and bytes against the four metrics; read every shard once, in order; report an unreadable or mismatched shard and never fetch a fallback diff or approve; for version 3 honor `packaging.context_lines` and `stable-first-fit-whole-file` and read the live file when context is short; for version 2, and version 3 with `generated_evidence`, corroborate against the companion migration and snapshot diff and the three implementer evidence items (no-pending-model-change, generated-SQL, provider-backed migration); never treat that evidence as a waiver. Read-only on the checkout; no git re-runs.
- Rubric bullets keep their meaning: Do Not Trust the Report, the test-rerun limits, Part 1 (Missing/Extra/Misunderstood, ⚠️ items), Part 2, Calibration (Important definition, plan-mandated defects reported as Important), the re-reviewer's scope and out-of-scope escalation.

- [ ] **Step 1: Write the falsifiable gate**

Save as `<launch scratch root>/task4_gate.py`:

```python
import re
from pathlib import Path
SDD = Path("home/common/agent-skills/skills/sdd")
TARGETS = {"implementer-prompt.md": 5200, "task-reviewer-prompt.md": 6000, "re-review-prompt.md": 4200}
CLAUSE_HEADS = ("Launch any subagent by type only", "Read an existing file before writing to it",
                "Run each long command, every verification command included, in the foreground with an explicit timeout above its expected duration.",
                "Never write an `until` or `while` loop around `sleep`")
for name, target in TARGETS.items():
    text = (SDD / name).read_text(encoding="utf-8")
    size = len(text.encode("utf-8"))
    print(f"{name} {size} bytes")
    if size > target:
        print("over target: name it in the commit body")
    preamble = text.split("\n", 1)[1].split("<!-- agent-dispatch:", 1)[0]
    assert len([l for l in preamble.splitlines() if l.strip()]) <= 1, f"{name}: preamble"
    fences = [l for l in text.splitlines() if l.startswith("```")]
    assert fences == ["```", "```"], f"{name}: one unlabeled fence"
    body = re.sub(r"\s+", " ", text.split("prompt: |", 1)[1])
    for head in CLAUSE_HEADS:
        assert body.count(head) == 1, f"{name}: {head}"
    if name != "implementer-prompt.md":
        assert "**Placeholders:**" in text, name
```

- [ ] **Step 2: Watch it fail**

Run: `python3 <scratch>/task4_gate.py` (timeout 120 s). Expected: AssertionError `implementer-prompt.md: preamble`.

- [ ] **Step 3: Cut the three payloads**

Apply the Invariants. The re-review prompt's leaf clauses and fence stay; its "Purpose" and "legal only because" paragraphs become the one preamble line.

- [ ] **Step 4: Models**

Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 5: Verify**

Run the Step 1 gate. Expected: exit 0.
Run the focused suite. Expected: OK (`SDD_MACHINE_TEXT` still finds `stable-first-fit-whole-file` in both reviewer payloads and the lifecycle argv in the implementer payload; `test_dispatch_contracts` finds each fence carrier's clauses).
Run the lint. Expected: exit 0.
Run `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run the D13 diff-bound script. Expected: exit 0.

- [ ] **Step 6: Commit**

Commit the three payloads and `instruction-load.json` as `refactor(sdd): cut the task-loop payloads (#297)`.
