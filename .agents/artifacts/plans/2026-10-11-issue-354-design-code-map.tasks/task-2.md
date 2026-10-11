# Task 2: Code map rule in the skill text, paid for byte by byte

Background for a reader with no context. Design and planning run as separate agents and only the spec passes between them. Issue 354 has the `design` skill leave a **code map** — a navigation file in the worktree's git directory, named after the spec — which the `writing-plans` skill reads before it maps files, and which the autonomous `from-issue` plan dispatch names. This task writes that rule into three skill documents and documents it in the agent-skills README.

The repository's Instruction Budget gate (`just agent-instruction-budget`) caps the bytes each agent profile loads, and two of the profiles these documents belong to have no spare byte. So each document must end no larger than it started: the new text is paid for by cuts in the same document (D8, D10). The cuts were chosen and measured on a prototype; you apply them with the script below and change nothing else.

**Files:**
- Modify: `home/common/agent-skills/skills/design/SKILL.md` (7272 → 7268 bytes)
- Modify: `home/common/agent-skills/skills/writing-plans/SKILL.md` (12771 → 12753 bytes)
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md` (11802 → 11776 bytes)
- Modify: `home/common/agent-skills/README.md` (a new `## Code map` section before `## Lifecycle helpers`; the README is outside the gate's corpus)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces, for Tasks 3 and 4 and for every later reader of these skills:
  - The code map's location: the git directory of the worktree (`git rev-parse --git-dir`), file name = the spec's file name with `.md` replaced by `.code-map.md` (D1).
  - The entry format in `design/SKILL.md`: a `## <the spec's name for it>` heading over `- Why:`, `- Code:` and `- Tests:` lines, paths backticked and outside parentheses.
  - The dispatch sentence in `AUTO.md`'s plan-subagent paragraph, which names the code map by that file name and "the worktree's git directory" (D4).

**Invariants:**
- After the script, the three skill documents have exactly the byte sizes above. The script refuses to write a file whose size before or after differs.
- No `<!-- agent-dispatch: … -->` marker line and no `Agent(...)` line changes. `git diff` on those lines is empty.
- These strings, which contract tests pin, are still present: in `design/SKILL.md`, `state: complete | decompose_required | failed` and the four metric names `root_bytes`, `total_bytes`, `file_count`, `largest_member_bytes`; in `writing-plans/SKILL.md`, `<stem>.tasks/task-1.md` (D10).
- Each of the three skill documents contains `.code-map.md`, and the words "code map" are always written in full: `writing-plans/SKILL.md`'s older bare "the map" becomes "the file map".
- `home/common/agent-skills/instruction-load.json` and `model-matrix.json` are unchanged.

What each edit is, by label in the script (D10). `duplicate`: a sentence or clause the same document, or a document in the same hot set, already states. `example`: a parenthetical example. `citation`: a bare decision-ID citation. `wording`: a shorter phrasing of the same statement. `add`: the new rule.

- `design/SKILL.md`. DS1 the role sentence (the last paragraph already forbids planning and implementing); DS2 wording; DS3 "a question the docs answer…" (stated by `doc-grounded-questions`, which the same paragraph invokes); DS4 and DS8 examples; DS5 a repeated "within that scope"; DS6 the downstream half of the test-seam guard (`writing-plans` enforces it); DS7 wording; DS9 and DS10 the two references to the final-writer rule, with the clause saying the checker owns the thresholds (the report bullets still name the checker's metrics); DS11 wording; DS12 the contrapositive of the completion order; DS13 the later-writer sentence (the grill and the planner each carry their own remeasure rule); DS14 a citation; DS15 and DS16 wording; ADD the `## Code map` section before `## Return control`.
- `writing-plans/SKILL.md`. WP1 the task-content sentence (restated under `## Task members`); WP2 "the public plan path" (Return control reports the root path); WP3 the step list (the member template shows it); WP4 a repeated clause and its citation; WP5 the measure-after sentence (Self-review item 5 states it); WP6 an example; WP7 and WP8 restatements; WP9 "the map" → "the file map"; WP10–WP14 citations; ADD the code map paragraph before "Before defining tasks, map the files".
- `from-issue/AUTO.md`. AU1 the filter's examples (the decision-ledger format the same sentence cites lists them); AU2 an example; ADD the sentence naming the code map in the plan-subagent paragraph.
- `README.md`. R1 the `## Code map` section: the long form of what the skill text compresses.

- [ ] **Step 1: Confirm the gate is red for the right reason**

Run: `wc -c home/common/agent-skills/skills/design/SKILL.md home/common/agent-skills/skills/writing-plans/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md; grep -c 'code-map' home/common/agent-skills/skills/design/SKILL.md || true`
Expected, before any edit: `7272`, `12771`, `11802`, then `0`. A different size means the document moved since this plan was measured: stop and report it; do not adapt the cuts yourself.

- [ ] **Step 2: Apply the edits**

Extract the script, do not retype it (`T` is this task file's path, `SCRATCH` your scratch directory), and run it once:

```bash
block task-2-edits "$T" > "$SCRATCH/task-2-edits.py"
python3 "$SCRATCH/task-2-edits.py" "$PWD"
```

Expected output, four lines: `skills/design/SKILL.md: 7268 bytes`, `skills/writing-plans/SKILL.md: 12753 bytes`, `skills/from-issue/AUTO.md: 11776 bytes`, `README.md: <n> bytes`. The script is all-or-nothing: when an edit's old text is not found exactly once, or a size is off, it exits non-zero and writes no file. Report that output and stop.

The script holds the exact text, because the byte count is the contract:

```python
# begin task-2-edits
"""Issue 354: apply the byte-exact skill-text edits. Usage: python3 edits.py <worktree root>"""
import pathlib
import sys

BASE = pathlib.Path(sys.argv[1]) / "home/common/agent-skills"
F = "`" * 3  # a code fence, spelled so that this block holds none

DESIGN_ADD = f'''## Code map

Before the report, write the spec's **code map** into the git directory (`git rev-parse --git-dir`), named like the spec file with `.code-map.md` for `.md`: a title naming the spec file, then one entry per module, seam or contract the Decisions decide about.

{F}markdown
## <the spec's name for it>
- Why: <one line: why it matters to this change>
- Code: `<path>` (`<symbol>`, `<symbol>`); `<path>`
- Tests: `<path>` (`<test name>`)
{F}

Paths are repository-relative, outside the parentheses; `Tests:` may read `none read`. Use only what you already read: open no file for it and omit an entry you cannot fill. It holds no decision, requirement, rationale, line number or code excerpt, and is never committed or reported. If it cannot be written, still complete and say so in `notes`.

'''

PLANS_ADD = '''Before mapping files, look for the spec's **code map**: the path your caller named, else the spec's file name with `.code-map.md` for `.md` in the git directory (`git rev-parse --git-dir`). None is no error: plan as usual. Read it first and take its entries as leads: open a mapped file only where a task needs detail the entry lacks (an exact signature, the test to extend), and expect to read beyond it. Check every mapped path and symbol you write into a task against the current tree with a bounded search; drop a wrong entry and search afresh. Never cite, link or copy it into the plan: implementers and reviewers cannot see it.

'''

README_ADD = '''## Code map

The `design` skill leaves a code map for the planner: a navigation hint, never an authority (#354). It is one Markdown file in the git directory of the worktree the design ran in (`git rev-parse --git-dir`), named after the spec file with `.code-map.md` in place of `.md`. That is outside the working tree, so it is never staged, committed, pushed or reviewed, no artifact-budget kind measures it, and in a linked worktree it goes when the worktree is removed. A rerun of `design` on the same spec overwrites it; the grill and the planner's ledger appends leave it alone, so it may be stale when it is read.

Its first line is a title naming the spec file. Each entry names a module, seam or contract the spec's Decisions decide about, with a `Why:` line, a `Code:` line and a `Tests:` line; a path is repository-relative and stands outside parentheses, and its symbols or test names follow in parentheses. It holds no decision, requirement, rationale, line number or code excerpt, and only what the design agent had already read. When it cannot be written, the design still completes and its `notes` say so.

`writing-plans` looks for it at the path its caller named, else by that naming rule, before it maps files. It takes the entries as leads, checks every mapped path and symbol it writes into a task against the current tree, and never cites, links or copies the code map into the plan. With no code map it plans as before. The autonomous `from-issue` plan dispatch names the file; the design dispatch and the interactive Phase 4 text do not mention it.

'''

DESIGN = (
    "skills/design/SKILL.md", 7272, 7268, [
        ("DS1", "duplicate",
         " You own the interview and the spec; the caller owns planning, review and execution.",
         ""),
        ("DS2", "wording",
         "A question that depends on another question open in the same round",
         "A question that depends on one open in the same round"),
        ("DS3", "duplicate",
         " A question the docs answer is stated with its citation, not asked.",
         ""),
        ("DS4", "example",
         " (does the file exist, what is the signature)",
         ""),
        ("DS5", "duplicate",
         "is the answer** within that scope: post",
         "is the answer**: post"),
        ("DS6", "duplicate",
         " The plan and every implementer inherit them and invent no others.",
         ""),
        ("DS7", "wording",
         "which later phases cite by row ID (\"per D3\") instead of restating:",
         "cited later by row ID (\"per D3\"), never restated:"),
        ("DS8", "example",
         " (`TBD`, \"handle edge cases\")",
         ""),
        ("DS9", "duplicate",
         " That last edit is the final mutation before measurement.",
         ""),
        ("DS10", "duplicate",
         "Measurement follows the final-writer rule (D5). Run `artifact-budget check --kind design-spec --root <spec-root> --format json`; the checker owns the thresholds and the metrics.",
         "Run `artifact-budget check --kind design-spec --root <spec-root> --format json`."),
        ("DS11", "wording",
         "Still over budget: keep the draft and return `decompose_required` with the checker's `violations`, its `notes` naming the independently deliverable parts as a proposed decomposition.",
         "Still over: keep the draft and return `decompose_required` with the checker's `violations`, its `notes` proposing the independently deliverable parts."),
        ("DS12", "duplicate",
         " Never commit an over-budget or `decompose_required` draft as a completed design.",
         ""),
        ("DS13", "duplicate",
         "Any later writer (a grill edit, a planning-phase ledger append) voids these metrics and checks the whole spec again before its phase advances.\n\n",
         ""),
        ("DS14", "citation",
         "`{state, artifact, notes}` (D11, D14) with",
         "`{state, artifact, notes}` with"),
        ("DS15", "wording",
         " or member lists; the committed spec carries the detail.",
         " or member lists."),
        ("DS16", "wording",
         "commit exactly the newly measured within-budget content",
         "commit exactly the measured within-budget content"),
        ("ADD", "add", "## Return control\n", DESIGN_ADD + "## Return control\n"),
    ])

PLANS = (
    "skills/writing-plans/SKILL.md", 12771, 12753, [
        ("WP1", "duplicate",
         " Every task names the files it touches, the exact interfaces and invariants it must satisfy, and how to test and verify it.",
         ""),
        ("WP2", "duplicate",
         " The root path is the public plan path (D3, D6).",
         ""),
        ("WP3", "duplicate",
         " Steps are one action each: write the failing test, watch it fail, write the minimal implementation, run the tests, commit.",
         ""),
        ("WP4", "duplicate",
         "copied ledger rationale; numbered tasks live only in members (D3).",
         "copied ledger rationale."),
        ("WP5", "duplicate",
         "Measure after the final mutation, and check the amended spec too when planning appended a ledger row. Any later writer",
         "Any later writer"),
        ("WP6", "example",
         " (`clearLayers()` vs `clearFullLayers()` is a bug)",
         ""),
        ("WP7", "duplicate",
         "\"similar to Task N\" (tasks are read alone, so restate the interfaces, invariants and assertions);",
         "\"similar to Task N\" (tasks are read alone);"),
        ("WP8", "duplicate",
         "3. **Members**: exact files, consumed and produced interfaces, invariants, complete failing tests, implementation actions, a scoped falsifiable gate, decision IDs and commit scope.",
         "3. **Members**: every part of the member template, a scoped falsifiable gate, decision IDs and commit scope."),
        ("WP9", "wording",
         "When the map depends on one bounded repository fact,",
         "When the file map depends on one bounded repository fact,"),
        ("WP10", "citation",
         "carry every task-specific value (D3).",
         "carry every task-specific value."),
        ("WP11", "citation",
         "Never pass or report a member list (D5, D6, D8).",
         "Never pass or report a member list."),
        ("WP12", "citation",
         "`complete` is forbidden (D5).",
         "`complete` is forbidden."),
        ("WP13", "citation",
         "before advancing (D5, D14).",
         "before advancing."),
        ("WP14", "citation",
         "`{state, artifact, notes}` (D11, D14).",
         "`{state, artifact, notes}`."),
        ("ADD", "add", "Before defining tasks, map the files", PLANS_ADD + "Before defining tasks, map the files"),
    ])

AUTO = (
    "skills/from-issue/AUTO.md", 11802, 11776, [
        ("AU1", "duplicate",
         "applying the non-obvious-only filter — routine splits, commit boundaries,\n   and obvious verification commands are not rows. Plans and ADRs cite the ID.",
         "applying the non-obvious-only filter. Plans and ADRs cite the ID."),
        ("AU2", "example",
         "implies a scope change (\"the plan covers A but the spec promised A+B\") — back up",
         "implies a scope change — back up"),
        ("ADD", "add",
         "root and metrics plus notes — not a transcript. `SKILL.md`'s plan-prose ≠\ncode-prose rule goes in the prompt.",
         "root and metrics plus notes — not a transcript. Name the spec's code map: the\nspec's file name with `.code-map.md` for `.md`, in the worktree's git directory. `SKILL.md`'s\nplan-prose ≠ code-prose rule goes in the prompt."),
    ])

README = (
    "README.md", None, None, [
        ("R1", "add", "\n## Lifecycle helpers\n", "\n" + README_ADD + "## Lifecycle helpers\n"),
    ])

results = []
for relative, before, after, pairs in (DESIGN, PLANS, AUTO, README):
    path = BASE / relative
    text = path.read_text(encoding="utf-8")
    if before is not None and len(text.encode("utf-8")) != before:
        sys.exit(f"{relative}: {len(text.encode('utf-8'))} bytes, expected {before} before the edits; "
                 "the file moved since the plan was measured: nothing written")
    for label, _kind, old, new in pairs:
        if text.count(old) != 1:
            sys.exit(f"{relative}: edit {label} matches {text.count(old)} times, expected 1: nothing written")
        text = text.replace(old, new)
    size = len(text.encode("utf-8"))
    if after is not None and size != after:
        sys.exit(f"{relative}: {size} bytes after the edits, expected {after}: nothing written")
    results.append((path, relative, text, size))
for path, relative, text, size in results:
    path.write_text(text, encoding="utf-8")
    print(f"{relative}: {size} bytes")
# end task-2-edits
```

- [ ] **Step 3: Read what you changed**

Run: `git diff --word-diff=plain -U0 -- home/common/agent-skills/skills home/common/agent-skills/README.md | grep -v '^@@' | cut -c1-600`

Read every changed line once. Check that each cut sentence is covered as the list above says, and that the added text matches the spec's `### The code map`, `### The planner` and `### The dispatch` sections. If a sentence you were told is a duplicate is not stated elsewhere, stop and report it instead of committing.

- [ ] **Step 4: Verify**

Run: `wc -c home/common/agent-skills/skills/design/SKILL.md home/common/agent-skills/skills/writing-plans/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md | head -n 3 | awk '{print $1}' | tr '\n' ' '`
Expected: `7268 12753 11776 `

Run: `for f in design/SKILL.md writing-plans/SKILL.md from-issue/AUTO.md; do grep -q '\.code-map\.md' "home/common/agent-skills/skills/$f" || { echo "missing in $f"; exit 1; }; done; if git diff -U0 -- home/common/agent-skills/skills | grep -E '^[-+].*(agent-dispatch:|Agent\()'; then echo "a dispatch line changed"; exit 1; fi; if ! git diff --quiet -- home/common/agent-skills/instruction-load.json home/common/agent-skills/model-matrix.json; then echo "a model file changed"; exit 1; fi; grep -c '^## Code map$' home/common/agent-skills/README.md home/common/agent-skills/skills/design/SKILL.md`
Expected: two lines, each ending `:1`, and no `missing`, `a dispatch line changed` or `a model file changed` line.

Run: `just agent-instruction-budget`
Expected: `check: pass`.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_agent_model_matrix.py 2>&1 | tail -n 3`
Expected: PASS — `OK` (with `skipped=3`), no failure. A failure naming `root_bytes`, `state: complete` or `<stem>.tasks/task-1.md` means a pinned string was lost.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/design/SKILL.md home/common/agent-skills/skills/writing-plans/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/README.md
git commit -m "feat(skills): design leaves a code map and planning reads it (#354)"
```
