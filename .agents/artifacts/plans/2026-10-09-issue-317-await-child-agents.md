# Await Child Agents Within the Turn Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A dispatched owner waits for a background child agent within its own turn: the `own-commands` leaf-agent clause names agents, and the **Interim child results** paragraph no longer lets an owner end its turn on a live child.

**Architecture:** Prompt text only. Task 1 rewrites the three **Interim child results** copies (from-issue, sdd, ship-issue) and their pins in `test_workflow_skill_contracts.py`. Task 2 rewords the second sentence of `CONTRACTS["own-commands"]` in `test_dispatch_contracts.py` and every enrolled carrier, and adds one stale-wording test over `guarded_documents()` that catches both the commands-only tail and the "host wakes you" premise.

**Tech stack:** Markdown skill and agent-definition text; Python 3 `unittest` contract tests; the `agent_tools.instruction_load` budget gate.

Spec: `.agents/artifacts/specs/2026-10-09-issue-317-await-child-agents-design.md` (its `## Decision ledger` rows D1–D7 are cited by ID below).

## Global Constraints

- No runtime, helper, hook, `instruction-load.json` or Codex-configuration change; no new test file; no new skill section (spec Out of scope, D3, D6).
- The clause id stays `own-commands`; `REMAINDER_PLACEHOLDER` and the four-clause and nine-skill-carrier counts are unchanged; the `from-issue-ship-owner` dispatch marker and call line and the dispatch-marker total are unchanged (D1, D3).
- `orchestrate-issues/SKILL.md` changes only inside its owner-prompt blockquote (spec Decisions).
- Byte neutrality (D4): every edited `*.md` under `home/` ends no larger than at the base `ef7eab96`. Gate, run from the worktree root:
  `git diff --name-only ef7eab96 -- 'home/*.md' | while read f; do b=$(git show ef7eab96:"$f" | wc -c); a=$(wc -c < "$f"); [ "$a" -le "$b" ] || { echo "GREW $f $b -> $a"; exit 1; }; done`
  (prints nothing and exits 0 when every edited document is no larger).
- Test commands run from the worktree root, in the foreground under `launch-scope exec … --`, as `PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]`, timeout at least 600 s.
- Final gate, once on the final head (sdd's final gate, not a per-task gate): `just build` (timeout 3600 s), `just agent-workflow-tests` (timeout 3600 s) and `just agent-instruction-budget` with no `--raise-label` (timeout 600 s), which must print `check: pass`. No agent applies the `instruction-budget-raise` label (D4).

## Test seams

- `InterimChildResultContractsTest` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (spec Test seams 2).
- `CONTRACTS["own-commands"]` and the existing carrier, mutation, stray-copy and enrolment tests in `home/common/agent-skills/tests/test_dispatch_contracts.py`, plus one new stale-wording test there over `guarded_documents()` (spec Test seams 1, D6).
- The Instruction Budget gate `just agent-instruction-budget` (spec Test seams 3).

## Delivery estimate and boundaries

Estimates: 17 changed files — 3 skill files for the interim paragraph, 13 carrier documents (9 skill carriers, 4 agent definitions; `from-issue/SKILL.md` and `sdd/SKILL.md` are in both sets, so 15 distinct documents) and 2 test files. Net document bytes fall by roughly 270 (about −107 each in from-issue and sdd, −26 in ship-issue, −1 per clause copy). One review package; no slicing needed.

## Task index

Task 1 — Interim child results waits within the turn — `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-1.md](2026-10-09-issue-317-await-child-agents.tasks/task-1.md)
Task 2 — `own-commands` names agents, plus the stale-wording guard — `home/common/agent-skills/tests/test_dispatch_contracts.py`, the 9 skill carriers and 4 agent definitions enrolled in `CARRIERS` — full — [task-2.md](2026-10-09-issue-317-await-child-agents.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | `test_dispatch_contracts.py`: `SourceTreeContractsTest.test_own_commands` against the reworded `CONTRACTS["own-commands"]` and `StaleTurnEndWordingTest.test_no_document_keeps_the_commands_only_or_host_wakes_wording` (with Task 1's `InterimChildResultContractsTest.test_no_copy_permits_ending_the_turn_on_a_live_child`), run by `just agent-workflow-tests` |
| AC2 | evidence | Task 2 | Command: the hand-back texts of the run's owner launches. Conditions: a post-merge orchestrate-issues run over two or more issues that reach Phase 7 on the merged skills. Threshold: zero matches of `waiting for`. Task 2's implementer writes acceptance-record row AC2 as `not measured — post-merge`, Verdict `unverified` (D5); ship-issue holds the issue `needs-verification` for the user to close. |

## Decisions

- Clause wording and id: D1. Interim paragraph rewrite: D2. No Phase-7 sentence: D3. Byte neutrality, no raise: D4. AC2 handling: D5. Test seams: D6.
- ship-issue's slim interim copy widens the undeliverable condition but keeps its direct "follow" without the "the child is one you cannot wait for" gloss, so the file shrinks: D7 (appended by this plan).

---
