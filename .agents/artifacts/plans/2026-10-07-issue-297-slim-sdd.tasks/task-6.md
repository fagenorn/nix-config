# Task 6: Close the AC3 share gap with semantics-preserving cuts

**Files** (under `home/common/agent-skills/`):
- Modify: any of `skills/sdd/SKILL.md`, `skills/sdd/final-review.md`, `skills/sdd/fix-loop.md`, `skills/sdd/implementer-prompt.md`, `skills/sdd/task-reviewer-prompt.md`, `skills/sdd/re-review-prompt.md`, `skills/sdd/conformance-reviewer-prompt.md`, `skills/sdd/correctness-reviewer-prompt.md`
- Modify: `instruction-load.json` (by `tighten` only)
- Test: none expected; `tests/test_workflow_skill_contracts.py` only if a machine-read pin forces it (then report it)

**Interfaces:**
- Consumes: Task 5's tree (the eight files total 76,075 bytes, `wc -c`).
- Produces: the eight files totalling ≤ 74,653 bytes (so the sdd share is ≤ 223,960 = 3 × 74,653, the amended AC3 line per D19, D21), with no rule, anchor or machine-read text lost, narrowed or widened.

**Invariants:**
- Every Global Constraint holds: machine-read text byte for byte and never wrapped across a line; the 18 markers in their files; leaf clauses once per carrier; anchors per D9; payloads self-contained and naming no controller section; hub rule; no `resolve-project resolve` in `SKILL.md`'s opening; no file added, removed or reclassified; `tighten` the only writer of `instruction-load.json`; no `raise:` line.
- A cut is allowed only when the removed text is (a) said elsewhere in the same file (or, for a payload, elsewhere in that payload or the reader's agent definition), (b) enforced by a helper, (c) rationale or history, or (d) self-evident to an agent following the remaining rules. Each cut's class is listed in the report.
- Wording-narrowing restorations below are required even though they add bytes.

- [ ] **Step 1: Restore the deferred narrowings**

From the task reviews (SDD ledger "minor (deferred)" lines), restore the meaning of:
- `SKILL.md` initial validation: the batched question asks "which governs".
- `final-review.md`: "(when there is one)" on the acceptance record's commit in `## Final verification`, and the "with a record" condition on the `code`-row sentence of its step 4.
- `task-reviewer-prompt.md`: the `[GLOBAL_CONSTRAINTS]` placeholder describes copying "exact values, formats, and stated relationships between components"; the plan-mandated trigger says "explicitly mandates"; "a function or API contract".
- `conformance-reviewer-prompt.md`: the version-2 rule requires the "reported" evidence and says the generated entry is never a waiver; the stale-prose bullet keeps the "re-read" directive.
- `fix-loop.md`: a short lead-in before the `sdd-task-fix-redispatch` marker so it is not read as the Opus-escalated case; "Confirm the fix report carries all four elements".

- [ ] **Step 2: Cut**

Start from the safe cuts the task reviews named, then look for more of the same classes in all eight files:
- `SKILL.md`: "— the review package and fix-round diffs need it"; "— if the implementer said it's stuck, something must change"; "— controller fixes skip review"; "Parked findings are already available through the one durable report."; §5's progress-marker sentence where it repeats `### Lifecycle workers`.
- `final-review.md`: "That step's verified tree then already holds the record, so ship's `verified-tree check` still matches (#263)."; "so the verified tree holds the final record"; "No code parses the record".
- `task-reviewer-prompt.md`: "the plan does not grade its own work".
- `conformance-reviewer-prompt.md`: the preamble line that repeats the in-fence opening (at most one line is allowed, zero is fine); "e.g. ship-issue's full path, ".
- `correctness-reviewer-prompt.md`: "SDD and the Codex `diff-review` packet supply the manifest root and all four metrics; " (outside the fence); "the implementers' reported runs are the evidence, so ".
- `SKILL.md`'s Sonnet re-evaluation rule stays (per D6).

Run after each file: `wc -c home/common/agent-skills/skills/sdd/*.md | tail -1`. Stop cutting once the total is ≤ 74,653 with margin of your choosing; do not chase bytes past the line.

- [ ] **Step 3: Models**

Run `just agent-instruction-load tighten` (timeout 300 s), then `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`, no `raise:` line.

- [ ] **Step 4: Verify**

Run the focused suite and the lint from Global Constraints. Expected: OK and exit 0.
Run the D13 diff-bound script. Expected: exit 0.
Run `wc -c home/common/agent-skills/skills/sdd/*.md | tail -1`. Expected: ≤ 74653. If the safe cuts cannot reach it, stop at the safe total and report DONE_WITH_CONCERNS with the exact total; never cut a rule to reach it (per D21).

- [ ] **Step 5: Commit**

Commit the changed sdd files and `instruction-load.json` as `refactor(sdd): close the instruction-load gap with safe cuts (#297)`; the body lists each file's before and after size.
