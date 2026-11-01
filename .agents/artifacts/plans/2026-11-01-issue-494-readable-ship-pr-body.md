# Readable ship-issue PR Body Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A PR opened by ship-issue reads on its own (Why, What changes, Evidence, Merge danger), and the spec, plan, acceptance, review and verification notes sit in one collapsed Delivery record below them. The lines later steps read back do not change.

**Architecture:** Task 1 rewrites the Phase-4 `gh pr create` template in ship-issue's `SKILL.md` and the three paragraphs after it, renames the Phase-8 hold comment's table, and makes from-issue's inline fallback name the same sections. Two new contract cases guard this (per D1–D5, D7, D8, D10). Task 2 sends every Phase-2 and Phase-5 note, and `REVIEW.md`'s two records, to the Delivery record, guarded by a third case (per D6). Neighbouring prose is compressed to pay for the template, so no ceiling and no gate file moves (per D1, D10).

**Tech stack:** Markdown skill documents, Python 3 standard-library `unittest` and `re`, `just`, Nix (`just build`).

Spec: `.agents/artifacts/specs/2026-11-01-issue-494-readable-ship-pr-body-design.md` (a bare "Dn" cites its `## Decision ledger`; D1–D10 come from design and grill, and this plan appended D11). Issue: https://github.com/fagenorn/nix-config/issues/494

## Global Constraints

- Base `8d0bbc25` (`origin/main` at planning), spec at `0e33f19b`. Tasks run in index order.
- Files this plan changes, and no others: `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/skills/ship-issue/REVIEW.md`, `home/common/agent-skills/skills/from-issue/ship-handoff.md` and `home/common/agent-skills/tests/test_workflow_skill_contracts.py`. sdd's final review adds its acceptance record beside this plan.
- These stay unchanged: `HUMAN-GATE.md`, `REMAINDER.md`, `CI-MERGE.md` and `POST-SELECTION-SYNC.md` (ship-owner conditional has 2 B headroom), and `DELIVERY-LOOP.md`; `home/common/agent-skills/instruction-load.json` and every other Instruction Budget gate file; `home/common/claude-code/lifecycle_guard.py`; `SHIP_ISSUE_MACHINE_TEXT` and every existing test, including the frozen `## Summary` fixtures in `test_shell_example_contracts.py`; and every `evals/` file (per D1, D9, spec § Out of scope).
- Write every dictated byte exactly, line breaks included. The text is binding (spec § Budget fit). Measured on the plan's scratch prototype: after Task 1, `SKILL.md` is at 500/500 reflowed lines (skill lint L2), ship-owner hot has 127 B headroom and implementation-owner hot has 12 B. After Task 2 the figures are 499 lines and 112 B. Any re-wrap or rewording is a plan deviation, and must pass the Budget command before it is committed. Never add the `instruction-budget-raise` label and never raise a ceiling (per D1).
- `docs/standards/agent-helpers.md` rule 6: the new cases pin only template markup and the destination name, never a placeholder or guidance sentence (per D9).
- Process custody: every test, build or gate command runs in the foreground from the worktree root as `launch-scope exec --repo-root <R> --run-id <I> --worker-id <W> -- <argv>`. Below, this is written `launch-scope exec … --`, with the stated timeout. `<R>`, `<I>` and `<W>` come from the dispatch's `Lifecycle worker:` line. Scratch goes under the path `launch-scope scratch --repo-root <R> --run-id <I> --worker-id <W>` prints. Commits go through `launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- <git commit args>`. They are SSH-signed and end with the session's attribution trailer. Never push, never `just switch`.
- **PR body cases** (timeout 600 s): `launch-scope exec … -- bash -c 'PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k pr_body_reads_first -k inline_fallback_names -k notes_go_to_the_delivery_record 2>&1 | grep -E "^(FAIL|ERROR|AssertionError|Ran|OK|FAILED)"'`
- **Skill contract tests** (timeout 900 s): `launch-scope exec … -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -3'`. At the base this prints `Ran 293 tests` and `OK (skipped=3)`.
- **Budget** (timeout 600 s): `launch-scope exec … -- bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -3'`. The last line must be `check: pass`. The command runs skill lint too, so an L2 breach prints a `lint:` line.
- **Installed tier** (timeout 3600 s): `launch-scope exec … -- bash -c 'set -o pipefail; just agent-installed-skill-tests 2>&1 | tail -4'`. It runs `just build` first, then checks the installed skill trees.
- Final gate (sdd's, once on the final head): `just build` and `just agent-workflow-tests` (timeout 3600 s each), plus the Budget command.

## Test seams

- `WorkflowSkillContractsTest` in `test_workflow_skill_contracts.py`. Its existing helpers are `assert_ordered`, `section`, the module's `normalized`, and the class attributes `ship_issue` and `ship_handoff`. Three new cases sit beside `test_ship_issue_documents_carry_their_machine_text` (spec § Test seams, per D9).
- The existing `SHIP_ISSUE_MACHINE_TEXT` table and the remainder-prompt cases, kept byte-identical (AC2).
- The Instruction Budget gate, `just agent-instruction-budget`, with no raise label (per D1, D10).

## Delivery estimate and boundaries

Estimates: 4 files, about 30 changed lines of skill text and about 65 added test lines, in one review package. No independent slice is needed.

## Task index

Task 1 — Readable PR body template and inline fallback — `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/ship-handoff.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-1.md](2026-11-01-issue-494-readable-ship-pr-body.tasks/task-1.md)
Task 2 — Notes go to the Delivery record — `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/skills/ship-issue/REVIEW.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-2.md](2026-11-01-issue-494-readable-ship-pr-body.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `home/common/agent-skills/tests/test_workflow_skill_contracts.py::WorkflowSkillContractsTest::test_ship_issue_pr_body_reads_first_then_records` and `::test_inline_fallback_names_the_readable_body`, run by `just agent-workflow-tests` |
| AC2 | code | Task 1 | The unchanged `WorkflowSkillContractsTest::test_ship_issue_documents_carry_their_machine_text` (the `SHIP_ISSUE_MACHINE_TEXT` table), `::test_ship_handoff_v2_ship_summary_v2_and_remainder_prompt`, `::test_the_ship_prompt_returns_the_gap_line_and_the_remainder_prompt_never_does` and `LaunchFencedWorkerContractsTest::test_the_remainder_prompt_releases_itself_before_its_finish` in the same file, run by Task 1's Skill contract tests and `just agent-workflow-tests` |
| AC3 | code | Task 2 | `home/common/agent-skills/tests/test_workflow_skill_contracts.py::WorkflowSkillContractsTest::test_ship_issue_notes_go_to_the_delivery_record`, run by `just agent-workflow-tests` |
| AC4 | code | Task 2 | `just agent-workflow-tests` and `just build` pass on the final head, run by sdd's final gate. Task 2's Skill contract tests and Installed tier are their focused subset |

## Decisions

- The template's home, and why no gate file moves: per D1, paid for by the trims in D10.
- The compact template shape, the block layout and the kept `## Acceptance` heading: per D2 and D3.
- Blob URLs and the hold comment's record link: per D4. The four-column acceptance table: per D5.
- The note destinations: per D6. The inline fallback's wording: per D7. The single readability rule: per D8.
- What the new cases pin: per D9. The two-task split, the one-commit stale Summary between the tasks, and Task 2's `git grep` gate: per D11 (appended by this plan).

---
