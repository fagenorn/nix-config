# Task 5: Cut the final-review payloads and drop the conformance policy-support rows

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/sdd/conformance-reviewer-prompt.md`, `skills/sdd/correctness-reviewer-prompt.md`
- Modify: `instruction-load.json` (by `tighten` only)
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 4's tree. `final-review.md` fills these payloads; ship-issue's `REVIEW.md` uses both as rubrics with the non-SDD fallback, and codex-collaboration's `DIFF-REVIEW.md` passes `correctness-reviewer-prompt.md` by absolute path with scoped packets (per D9).
- Produces: `conformance-reviewer-prompt.md` ≤ 6,500 bytes and `correctness-reviewer-prompt.md` ≤ 5,200, with unchanged placeholder names and output contracts.

**Invariants:**
- Each payload stays self-contained (per D5) and keeps exactly one unlabeled fence, its `Subagent (...)` header, `description:` and `prompt: |`, and the four leaf clauses byte for byte, each exactly once after `prompt: |`.
- Outside the fence: the H1 title, at most one non-empty line, then the marker and call line byte for byte (`sdd-final-conformance-review`, `sdd-final-correctness-review`), then after the fence the `**Placeholders:**` list with every placeholder name.
- `conformance-reviewer-prompt.md` loses its line-3 policy sentence (the one carrying `retained \`ResolvedProject\`` and `bindings.workflow.review.code`) and keeps the in-fence no-resolve clause "Receive the phase owner's retained snapshot." with the `bindings.paths.context` grounding rule (#295 D14). It keeps byte for byte: `[ACCEPTANCE_CRITERIA]`, `[DEFERRED_AND_PARKED_LINES]` and their omit rules (no criterion source, ship-issue's full review, no ledger lines), the fallback `` `git diff --stat [MERGE_BASE_SHA]..[HEAD_SHA]` then `git diff [MERGE_BASE_SHA]..[HEAD_SHA]` ``, the four grading tokens and the per-kind grading rules, "never parked with a ruling", `**Conformance:** Clean | Findings — 1–2 sentence assessment.`, `### Coverage`, `### Acceptance` with `| AC | Kind | Verdict | Citation |`, `observed <value> at <sha7> vs threshold <literal>`, `### Issues` with `#### Critical (Must Fix)`, `#### Important (Should Fix)`, `#### Minor`, and `### Ledger Triage`.
- `correctness-reviewer-prompt.md` keeps byte for byte: `git diff [MERGE_BASE_SHA]..[HEAD_SHA] -- ':(literal)<path>'` with the one-invocation-per-path rule (single literal argument after `--`, never shell-joined, `:(literal)` disables pathspec magic; the why-sentence about spaces and newlines may shrink to one clause), the scoped rule (manifest and metrics are range-coverage evidence only; do not read its shards), the non-SDD fallback, `**Correctness:** Clean | Findings — 1–2 sentence assessment.`, `scoped to <N> of <M> product files;` with its placement rule, the finding fields (stable ID, `path:line`, confidence `high` / `medium` / `low`, unknowns), and the headings `### Critical (Must Fix)`, `### Important (Should Fix)`, `### Minor`. Its body stays reviewer-agnostic: nothing in it assumes which model reads it.
- Manifest paragraph, one compressed paragraph per payload with every reviewer rule in spec § Cutting rules per document (Payloads): validate coverage and bytes against the four metrics; read every shard once, in order (unscoped); report an unreadable or mismatched shard, never fetch a fallback diff or report a clean axis; version 3 → honor `packaging.context_lines` and `stable-first-fit-whole-file`, read the live file when context is short; version 2, and version 3 with `generated_evidence` → corroborate against the companion migration and snapshot diff and the three implementer evidence items; never a waiver. Read the live file at HEAD when checking a finding; read-only checkout.
- Rubric bullets keep their meaning; only redundant wording goes.

- [ ] **Step 1: Write the falsifiable gate**

Save as `<launch scratch root>/task5_gate.py`:

```python
import re
from pathlib import Path
SDD = Path("home/common/agent-skills/skills/sdd")
KEEP = {
    "conformance-reviewer-prompt.md": (6500, (
        "Receive the phase owner's retained snapshot.", "[ACCEPTANCE_CRITERIA]",
        "[DEFERRED_AND_PARKED_LINES]", "`git diff --stat [MERGE_BASE_SHA]..[HEAD_SHA]`",
        "**Conformance:** Clean | Findings — 1–2 sentence assessment.",
        "| AC | Kind | Verdict | Citation |", "observed <value> at <sha7> vs threshold <literal>",
        "#### Critical (Must Fix)", "#### Important (Should Fix)", "stable-first-fit-whole-file")),
    "correctness-reviewer-prompt.md": (5200, (
        "git diff [MERGE_BASE_SHA]..[HEAD_SHA] -- ':(literal)<path>'",
        "`git diff --stat [MERGE_BASE_SHA]..[HEAD_SHA]`",
        "**Correctness:** Clean | Findings — 1–2 sentence assessment.",
        "scoped to <N> of <M> product files;", "### Critical (Must Fix)",
        "### Important (Should Fix)", "### Minor", "stable-first-fit-whole-file")),
}
for name, (target, items) in KEEP.items():
    text = (SDD / name).read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", text)
    size = len(text.encode("utf-8"))
    print(f"{name} {size} bytes")
    if size > target:
        print("over target: name it in the commit body")
    preamble = text.split("\n", 1)[1].split("<!-- agent-dispatch:", 1)[0]
    assert len([l for l in preamble.splitlines() if l.strip()]) <= 1, f"{name}: preamble"
    assert [l for l in text.splitlines() if l.startswith("```")] == ["```", "```"], name
    for item in items:
        assert item in flat, f"{name}: {item}"
conformance = (SDD / "conformance-reviewer-prompt.md").read_text(encoding="utf-8")
assert "retained `ResolvedProject`" not in conformance
assert "resolve-project resolve" not in conformance
```

- [ ] **Step 2: Watch it fail**

Run: `python3 <scratch>/task5_gate.py` (timeout 120 s). Expected: AssertionError `conformance-reviewer-prompt.md: preamble`.

- [ ] **Step 3: Cut the two payloads**

Apply the Invariants. Placeholder descriptions may shorten but keep each omit rule a dispatcher follows.

- [ ] **Step 4: Test edit (spec § Test changes item 4)**

In `tests/test_workflow_skill_contracts.py`, delete the line `"sdd/conformance-reviewer-prompt.md": ("bindings.workflow.review.code",),` from both `SHARED_POLICY_SUPPORT` and `RETAINED_SUPPORT_CONTRACTS`. Every other row stays; a sync conflict here resolves to the union of deletions (per D16).

- [ ] **Step 5: Models**

Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 6: Verify**

Run the Step 1 gate. Expected: exit 0.
Run the focused suite. Expected: OK (`test_the_final_conformance_marker_selects_opus_high`, the fence carriers and `SDD_MACHINE_TEXT`'s `[ACCEPTANCE_CRITERIA]` and literal-path items still pass).
Run the lint. Expected: exit 0.
Run `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run the D13 diff-bound script. Expected: exit 0.

- [ ] **Step 7: Commit**

Commit the two payloads, the test file and `instruction-load.json` as `refactor(sdd): cut the final-review payloads (#297)`.
