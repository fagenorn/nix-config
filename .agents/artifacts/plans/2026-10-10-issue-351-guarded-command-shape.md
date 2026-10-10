# ship-issue States the Guarded Command Shape Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Every push, merge and branch delete the `ship-issue` skill family issues is spelled in a form the lifecycle guard has a verdict for and cites one run-alone rule, a deterministic check fails when one does not, and the guard suite pins those forms and the dressed shapes agents reach for.

**Architecture:** One JSON fixture, `tests/fixtures/guarded-command-shapes.json`, lists the skill's literal forms and the refused dressed shapes with the guard's verdict for each. The shell-example contract suite reads it through one new boundary function, `guarded_command_findings`, which reuses that suite's living-example extractor and reports rules R1 (form), R2 (citation) and R3 (coverage) over `skills/ship-issue/*.md`. The guard suite runs every fixture row through the built guard. The skill text states the rule once under `ship-issue/SKILL.md`'s existing `## gh hygiene` heading and cites it at each site, paid for byte by byte with named cuts. The guard source does not change.

**Tech stack:** Python 3 standard library `unittest`, Markdown skill documents, the `agent_tools.instruction_load` gate, the Nix-built Claude settings artifact for the guard suite.

Spec: `.agents/artifacts/specs/2026-10-10-issue-351-guarded-command-shape-design.md` (its `## Decision ledger` rows D1–D13 are cited by ID).

## Global Constraints

- Base: `02d2f378ad8c4abbb8e3a3960b4c93b10879bd6b` (`origin/main` at planning). Every byte count and line number in this plan was measured there.
- `home/common/claude-code/lifecycle_guard.py` is not edited (spec "Out of scope").
- None of the gate files is edited: `.github/workflows/instruction-budget.yaml`, `python/agent_tools/skill_lint.py`, `python/agent_tools/instruction_load.py`, `.github/branch-protection.json`. `home/common/agent-skills/instruction-load.json` is not edited either. `home/common/agent-skills/tests/test_skill_lint.py` is not touched (D3).
- No task asks for, applies or assumes the `instruction-budget-raise` label. If the Instruction Budget gate cannot pass with the cuts Task 2 names, the work stops and reports; it never raises a ceiling (D9).
- Skills outside `home/common/agent-skills/skills/ship-issue/` are not edited (D1).
- Tests pin only machine-consumed text: shell examples, the anchor token and fixture rows; no new test asserts an English phrase (`docs/standards/agent-helpers.md` rule 6).
- Prose that lands in the repository (skill sentences, docstrings, comments, the README sentence) describes the code as it behaves at that task's commit.
- Every long command, each test command included, runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration; commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Contract suites run as `env PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]` (timeout 900 s).
- The guard suite runs only against a built settings artifact: after `just build` (timeout 3600 s), `env CLAUDE_SETTINGS_PATH="$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')" python3 -m unittest tests/test_claude_permission_guard.py` (timeout 900 s). It is not part of `just agent-workflow-tests`.
- Final gate, once on the final head (sdd's, not per task): `just build` (timeout 3600 s), `just agent-workflow-tests` (timeout 3600 s), the guard suite command above, and `just agent-instruction-budget`, which must print `check: pass`.

## Test seams

- The skill documents as text, through `guarded_command_findings(document_text, shapes, document_name)` in `home/common/agent-skills/tests/test_shell_example_contracts.py`: fixture documents per failure class, then the source-tree sweep of `skills/ship-issue/*.md`.
- The built guard as a process, through `ClaudePermissionGuardTest.run_guard` and `make_repo` in `tests/test_claude_permission_guard.py`, driven by the fixture.
- The Instruction Budget gate, `just agent-instruction-budget`, unchanged.

## Delivery estimate and boundaries

Estimates: 11 changed files — the new fixture, `test_shell_example_contracts.py`, six `ship-issue` documents, `test_claude_permission_guard.py`, `home/common/claude-code/README.md` and the new acceptance record — about +75 fixture lines, +200 test lines, and a net +4 bytes of skill text. One review package. The aggregate-growth risk is the instruction budget alone, and Task 2 carries its measured table. Task 1 is independently deliverable; Task 3 needs only Task 1's fixture.

## Task index

Task 1 — The shape fixture and the skill check — `tests/fixtures/guarded-command-shapes.json`, `home/common/agent-skills/tests/test_shell_example_contracts.py` — full — [task-1.md](2026-10-10-issue-351-guarded-command-shape.tasks/task-1.md)
Task 2 — The skill family states and cites the run-alone rule — `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/skills/ship-issue/REVIEW.md`, `home/common/agent-skills/skills/ship-issue/SYNC.md`, `home/common/agent-skills/skills/ship-issue/POST-SELECTION-SYNC.md`, `home/common/agent-skills/skills/ship-issue/CI-MERGE.md`, `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`, `home/common/agent-skills/tests/test_shell_example_contracts.py` — full — [task-2.md](2026-10-10-issue-351-guarded-command-shape.tasks/task-2.md)
Task 3 — The guard suite pins every fixture row — `tests/test_claude_permission_guard.py`, `home/common/claude-code/README.md`, `.agents/artifacts/plans/2026-10-10-issue-351-guarded-command-shape.acceptance.md` — full — [task-3.md](2026-10-10-issue-351-guarded-command-shape.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence | Task 3 | Command: `grep -c "lifecycle guard: unsafe \(push\|merge\|branch deletion\)"` over the subagent transcripts of the run. Conditions: the next orchestrated run that ships at least 3 issues on nodocom, with the merged skill text installed on the orchestrating host. Threshold: 0 (baseline 15 refusals across 9 ship phases). Task 3's implementer writes acceptance-record row AC1 as `not measured — post-merge`, Verdict `unverified`; ship-issue then holds the issue `needs-verification` (D10). |
| AC2 | code | Task 2 | `test_shell_example_contracts.py`: `ShipIssueGuardedCommandSweepTest.test_every_guarded_command_is_a_cited_form` over the edited tree, with Task 1's `GuardedCommandShapeTest.test_each_failure_class_is_found` (the six falsifying documents of the spec's AC2), both run by `just agent-workflow-tests`. The check's home is D3's, not `skill-lint`. |
| AC3 | code | Task 3 | `tests/test_claude_permission_guard.py`: `ClaudePermissionGuardTest.test_every_guarded_command_shape_gets_its_verdict`, run against the built settings artifact with the guard suite command in Global Constraints. |

The spec's fourth criterion, the budget gate, is not an issue criterion (D11): Task 2's gate and the final gate both run `just agent-instruction-budget` and require `check: pass` with no `ceiling:`, `tightness:`, `lint:` or `raise:` line.

## Decisions

- Scope of the skill family: D1. What the guard does with each deletion, and why the remote delete stays in the skill as a refused row: D2.
- Where the check lives and why not `skill-lint`: D3. No exemption for a named verb: D4. One home for the rule, an anchor token at each site: D5.
- One fixture for both suites, commands derived from the skill's templates: D6, extended by D12 (appended by this plan).
- The push is prescribed run-alone although the guard tolerates more: D7. The refused mention is the unquoted one: D8.
- The byte budget and the stop rule: D9; the measured cut list and the two reflowed-line limits: D13 (appended by this plan).
- AC1 pending at merge: D10. The Acceptance map's three rows: D11 (appended by this plan).
- R1's comparison, R2's block for a fence, R3's line and the source-only sweep: D12.

---
