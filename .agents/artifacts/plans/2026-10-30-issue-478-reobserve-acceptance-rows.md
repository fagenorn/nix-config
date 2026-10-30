# Ship Re-observes Agent-Checkable Acceptance Rows Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Before close-or-hold, ship-issue re-observes each `unverified` `code` row that only a required CI check or a read-only command left pending, records the result in the acceptance record, and closes or holds on the recomputed state, so only rows a human must judge still hold an issue.

**Architecture:** A new `agent_tools.acceptance_record` module, installed as `acceptance-record` with one verb, `reobserve`. It parses the record's table under a closed grammar, applies sdd's `code` rule to required-check and command observations, rewrites only the changed rows atomically and prints the derived state (D1, D3–D6, D12). ship-issue's Phase 6 gains a **Re-observe pending rows** paragraph that runs the command between the required watch and the selection gate, publishes a changed record and reruns Phase 6. SKILL.md stays inside skill-lint's 500-line cap (D2, D7, D8, D10, D11). The criteria cases drive the command from source and finish delivery through the real engine (D9).

**Tech stack:** Python 3 standard library (`argparse`, `json`, `re`, `os`, `tempfile`, `unittest`, `subprocess`), Markdown under the Instruction Budget gate and skill-lint L2, Nix (`just build`), Just.

Spec: `.agents/artifacts/specs/2026-10-30-issue-478-reobserve-acceptance-rows-design.md`. A bare "Dn" cites its `## Decision ledger`. This plan appends D11 and D12. Issue: https://github.com/fagenorn/nix-config/issues/478.

## Global Constraints

- Base `cb1d0ad5`, the spec commit on `origin/main` `07f89813`. Tasks land in index order, each on top of the one before.
- Declared verification: `just build`, then `just agent-workflow-tests` (from `bindings.workflow.verification`).
- Not edited: `home/common/agent-skills/instruction-load.json`, `.agents/project.json`, `home/common/claude-code/default.nix` (no allow-list entry), and every ship-issue document except `SKILL.md`. That includes `REMAINDER.md`, `CI-MERGE.md`, `HUMAN-GATE.md`, `DELIVERY-LOOP.md` and `REVIEW.md` (D7, D10). Also not edited: every from-issue and sdd document, `python/agent_tools/ship_delivery*.py`, the delivery model and wire scripts, `python/ship-delivery.md`, every existing `*.acceptance.md`, the `COMMAND_VOCABULARY` in `test_shell_example_contracts.py` and `LAUNCHER_FLOOR` in `tests/test_agent_tools_launchers.py`.
- Instruction load: never apply the user-only raise label, never name it in a command, and never edit `instruction-load.json`. `ship-issue/SKILL.md` grows by at most 1,608 bytes over base and measures at most 500 skill-lint reflowed lines (D10, D11).
- Comments, docstrings, README sentences and skill prose describe the code as it behaves at that task's commit. Write "issue 478", never a bare `#478`. No `TODO` or `FIXME`.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. Commits are SSH-signed and end with the session's trailer lines. Scratch files go under the root that `launch-scope scratch` prints. Never run `just switch`, and never push.
- **Budget** (timeout 600 s): `bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -2'`. It runs skill-lint too. A passing run ends `check: pass`.
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`.
- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each), plus the Budget run, which neither recipe covers.

## Test seams

- The command's process boundary (D9, D12): a new `tests/test_acceptance_record.py` drives `python -m agent_tools.acceptance_record` in a throwaway directory. It asserts exit code, canonical stdout JSON, the single stderr line and the record's bytes. No test imports `acceptance_record`.
- The criteria seam (D9): `home/common/agent-skills/tests/test_ship_delivery.py`'s `ShipDeliveryTest` runs the same command from source against a record in the harness root. It feeds the printed state to `deliver(acceptance_state=...)`, which finishes through the real compiler, validator and engine.
- The guidance (D9): `SHIP_ISSUE_MACHINE_TEXT` and one ordering case in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, on whitespace-normalized text. The Budget run checks the byte ceilings and skill-lint L2.

## Delivery estimate and boundaries

All figures are estimates. Eight changed files, about +700/−50 lines, plus this package and two spec ledger rows:

| File | Change |
|------|--------|
| `python/agent_tools/acceptance_record.py` | new, about 240 lines |
| `tests/test_acceptance_record.py` | new, about 290 lines |
| `lib/agent-tools.nix`, `justfile` | one line each |
| `python/README.md` | one new section, about 1.8 KB |
| `test_ship_delivery.py` | about +80/−3 |
| `ship-issue/SKILL.md` | about +1,150 bytes, reflowed lines unchanged at 500 |
| `test_workflow_skill_contracts.py` | about +15/−1 |

One review package. If a split is forced: S1 = Tasks 1 and 2 (AC1, AC2, AC4), S2 = Task 3 (AC3).

## Task index

Task 1 — `acceptance-record reobserve` command and its contract — `python/agent_tools/acceptance_record.py`, `tests/test_acceptance_record.py`, `lib/agent-tools.nix`, `justfile`, `python/README.md` — full — [task-1.md](2026-10-30-issue-478-reobserve-acceptance-rows.tasks/task-1.md)
Task 2 — Criteria cases: re-observed records close or hold through the engine — `home/common/agent-skills/tests/test_ship_delivery.py` — full — [task-2.md](2026-10-30-issue-478-reobserve-acceptance-rows.tasks/task-2.md)
Task 3 — ship-issue Phase 6 re-observes pending rows — `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-10-30-issue-478-reobserve-acceptance-rows.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `home/common/agent-skills/tests/test_ship_delivery.py::ShipDeliveryTest::test_a_ci_pending_code_row_observed_green_closes_the_issue` (at base it fails: there is no `acceptance-record` command, so the issue holds), run by `just agent-workflow-tests` |
| AC2 | code | Task 2 | `home/common/agent-skills/tests/test_ship_delivery.py::ShipDeliveryTest::test_a_pending_human_row_still_holds_the_issue`, run by `just agent-workflow-tests` |
| AC3 | code | Task 3 | `home/common/agent-skills/tests/test_workflow_skill_contracts.py::WorkflowSkillContractsTest::test_ship_issue_documents_carry_their_machine_text` (the two argv pins) and `::test_phase_six_reobserves_pending_rows_between_the_watch_and_the_merge`, run by `just agent-workflow-tests` |
| AC4 | code | Task 1 | `just agent-workflow-tests`, with `tests/test_acceptance_record.py` added to its members, on the Declared verification line, run by sdd's final gate on the final head |

## Decisions

- Task 1 rests on D1, D3, D4, D5, D6 and D12. Task 2 rests on D9. Task 3 rests on D2, D5, D7, D8, D10 and D11.
- Planning appended D11 (SKILL.md is at the skill-lint L2 cap, so the paragraph is cut to fit and five hard-wrapped paragraphs are joined) and D12 (the command's open interface details).
- A planning trial ran at `cb1d0ad5` in a scratch worktree, then was discarded. It used all three tasks' tests and edits as written here, plus a reference implementation of Task 1. Without the module, `tests/test_acceptance_record.py` ran 16 tests, `FAILED (failures=49)` with subtests counted; with it, `OK`. Re-deriving every committed record (no `--row`) succeeded for 66 of 71. `test_ship_delivery.py` ran 12 tests: `FAILED (errors=3)` with the old `deliver` signature, `OK` after Task 2. `test_workflow_skill_contracts.py` ran 158 tests: `FAILED (failures=3, skipped=1)` against base SKILL.md, `OK (skipped=1)` after Task 3. Before D11 the spec's paragraph took SKILL.md to 516 reflowed lines, which the Budget run refused under skill-lint L2. With Task 3 as written it measured 500 lines and +1,146 bytes. The Budget run gave `check: pass`. With the skill-lint and instruction-load modules added, the contract modules ran 293 tests: `OK (skipped=3)`. With all three tasks applied and the new files staged, `just build` passed in about a minute. An unstaged module fails evaluation, which is why Task 1 stages before building. `just agent-workflow-tests` passed 107 of 107 members in about 965 s.

---

## Standards review provenance

- Reviewer: Codex (`codex-plan-review`, `gpt-6-astra`, effort xhigh), fresh isolated read-only thread; no fallback.
- Base SHA `07f8981308f56c9ce136773868151a73a2e1da9b`, plan reviewed at `3640f411`; no optional focus.
- Findings: 0 Blocking, 2 Should fix, 0 Discussion. Accepted 2, rejected 0, deferred 0.
  - PR-1 (Task 1): a `--checks` `link` containing a line break would split the rewritten row; `load_checks` now refuses it as a malformed entry, with a boundary case.
  - PR-2 (Task 1): the README and module docstring now say that only a matched span left unobserved keeps a row unchanged, and that unmatched spans are the caller's `--row` judgment (spec § matching).
