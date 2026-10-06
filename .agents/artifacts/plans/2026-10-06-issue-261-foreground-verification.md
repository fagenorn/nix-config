# Foreground Verification and In-Turn Waits Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Stop the forced-suspend cascade of issue #261 by raising the host's Bash
timeout ceiling, giving every leaf agent a third clause about its own long commands,
and teaching owners and the dispatcher that an interim child result is not a return.

**Architecture:** One Nix settings key (per D2, D7), one new clause in the existing
dispatch-contract table and its carriers plus the four Claude agent definitions (per
D3, D4, D10, D11), one canonical owner paragraph in three skills with two pointers
(per D5, D8), and one dispatcher classification case (per D6, D9). All behavior is
prose read by agents; the contract tests are the executable surface. Spec:
`.agents/artifacts/specs/2026-10-06-issue-261-foreground-verification-design.md`.

**Tech stack:** Nix (home-manager settings attrset), Markdown skill documents,
Python `unittest` contract suites run by `just`.

## Global Constraints

- The leaf clause text is exactly: `Run each long command, every verification command included, in the foreground with an explicit timeout above its expected duration. If the host moves one to the background anyway, wait for it within the same turn: never end your turn while a command you started is still running.`
- `settings.env.BASH_MAX_TIMEOUT_MS = "3600000"`; `BASH_DEFAULT_TIMEOUT_MS` stays unset (per D2).
- No skill document under `from-issue/` or `sdd/` may contain the literal `run_in_background` (existing nested-workflow test).
- Instruction-load ceilings in `home/common/agent-skills/instruction-load.json` sit exactly at measured bytes. Any task that grows a hot member runs `test_instruction_load.py`; for each `profile <id> on <host>: hot <N> bytes exceed ceiling <M>` line it sets that profile's `ceiling_bytes.<host>` to `<N>` and appends one sentence to that profile's `note`: `Ceiling raised for #261: <what grew> (#155 D10).` — one sentence per profile per task, never a raise above the measured value.
- Long commands: run `just build` (up to 15 min) and `just agent-workflow-tests` (8–10 min) in the foreground with Bash timeout 600000, output redirected to a log ending in an `exit=<status>` line. If the host moves one to the background, wait for that log's `exit=` line within the same turn; never end the turn while it runs.
- Commits go through `launch-commit` with the `Lifecycle worker:` line the dispatch carries, SSH-signed, ending with the session's Co-Authored-By and Claude-Session lines.

## Test seams

- `home/common/agent-skills/tests/test_dispatch_contracts.py` — clause table, carriers, region kinds, stray-copy guard, mutations, enrolment (per D3, D4, D11).
- `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — `normalized` + `assert_ordered` anchors for the owner paragraph, its identity across skills, the pointers and the dispatcher case (per D5, D6, D9).
- `tests/test_claude_permission_guard.py` run with `CLAUDE_SETTINGS_PATH` naming the built settings artifact (per D7).
- `home/common/agent-skills/tests/test_instruction_load.py` — ceilings only; no new test.

## Delivery estimate and boundaries

Estimate: about 18 changed files (1 Nix, 1 CLAUDE.md, 3 test files, 1 JSON model,
9 skill documents, 4 agent definitions), each by a few lines; well inside one review
package. No slice needs to ship on its own: per D1 the three links land together.

## Task index

Task 1 — Raise the Bash timeout ceiling — `home/common/claude-code/default.nix`, `tests/test_claude_permission_guard.py`, `CLAUDE.md` — low-risk — [task-1.md](2026-10-06-issue-261-foreground-verification.tasks/task-1.md)
Task 2 — The `own-commands` leaf clause in every carrier and agent definition — `home/common/agent-skills/tests/test_dispatch_contracts.py`, five `sdd/*-prompt.md`, `from-issue/ship-handoff.md`, `from-issue/SKILL.md`, `from-issue/AUTO.md`, `sdd/SKILL.md`, `orchestrate-issues/SKILL.md`, four `home/common/claude-code/agents/*.md`, `instruction-load.json` — full — [task-2.md](2026-10-06-issue-261-foreground-verification.tasks/task-2.md)
Task 3 — The Interim child results owner rule — `from-issue/SKILL.md`, `from-issue/AUTO.md`, `sdd/SKILL.md`, `ship-issue/SKILL.md`, `test_workflow_skill_contracts.py`, `instruction-load.json` — full — [task-3.md](2026-10-06-issue-261-foreground-verification.tasks/task-3.md)
Task 4 — The dispatcher's interim owner case and final verification — `orchestrate-issues/SKILL.md`, `test_workflow_skill_contracts.py`, `instruction-load.json` — full — [task-4.md](2026-10-06-issue-261-foreground-verification.tasks/task-4.md)

## Decisions

The spec's `## Decision ledger` owns every decision. Tasks cite D1–D8 from design and
D9–D11 appended at planning.

---
