# Checkpoint Verification Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Move the full declared verification (`just build` + `just agent-workflow-tests`)
from every task to two checkpoints, sdd's final gate and ship, and prove a pass with a
recorded tree identity so ship can skip a rerun of exactly the bytes that already passed.

**Architecture:** A new packaged command `verified-tree` (`check` / `record`) computes the
working tree's git tree in a temporary index and keeps one latest-pass record in the
worktree's git directory (per D6–D9). sdd's final-review gains a Final verification step
after the fix wave (per D3, D4, D10, D12); the implementer, fix rounds, final fixer and
writing-plans name the per-task ladder of focused tests plus a build check (per D1, D2,
D11); ship-issue Phase 2 becomes check → skip on `verified` → run and record, and its two
rerun sites point to it (per D5, D10, D12). Spec:
`.agents/artifacts/specs/2026-10-06-issue-263-checkpoint-verification-design.md`.

**Tech stack:** Python 3 standard library (`agent_tools` package), git plumbing, Nix
command table (`lib/agent-tools.nix`), Markdown skill documents, `unittest` suites run by `just`.

## Global Constraints

- Per-task verification follows this issue's own ladder: each task runs the focused test commands its member names, red then green, plus `just build` because every task here changes files the Nix build reads (`python/`, `lib/`, or the copied skill tree under `home/common/agent-skills/skills/`; per D11). No task runs `just agent-workflow-tests`; sdd's final gate runs the full declared verification once.
- Long commands: run `just build` (up to 15 min) in the foreground with Bash timeout 1800000 when the session runs under the raised `BASH_MAX_TIMEOUT_MS`, otherwise 600000, output redirected to a log ending in an `exit=<status>` line and only its tail read back. If the host moves it to the background, wait for that log's `exit=` line within the same turn; never end the turn while it runs.
- Focused Python commands run from the worktree root with `PYTHONPATH="$PWD/python"` (absolute, because tests that spawn subprocesses change cwd).
- Instruction-load ceilings in `home/common/agent-skills/instruction-load.json` sit exactly at measured bytes. Any task that grows a hot member runs `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -8`; for each `profile <id> on <host>: hot <N> bytes exceed ceiling <M>` line it sets that profile's `ceiling_bytes.<host>` to `<N>` and appends one sentence to that profile's `note`: `Ceiling raised for #263: <what grew> (#155 D10).` — one sentence per profile per task, never a raise above the measured value.
- Never edit an `<!-- agent-dispatch: … -->` marker or the `Agent(…)` line under it: `home/common/agent-skills/model-matrix.json` pins those lines.
- Skill text stays project-neutral: shared skills say "the build check" and "files the build evaluates", never `just build` (per D2).
- Commits go through `launch-commit` with the `Lifecycle worker:` line the dispatch carries, SSH-signed, ending with the session's Co-Authored-By and Claude-Session lines.

## Test seams

- `tests/test_verified_tree.py` (new, added to `agent-workflow-tests`) — runs `python -m agent_tools.verified_tree` in temporary git repositories; asserts stdout JSON, exit status and the record file (per D6–D9).
- `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — new class `CheckpointVerificationContractsTest` with `normalized` + `assert_ordered` anchors; the existing post-selection-sync anchors are updated in place.
- The build's module import check (`pythonImportsCheck`) and the built `.agents/bin/verified-tree` launcher cover the command-table row.
- `home/common/agent-skills/tests/test_dispatch_contracts.py` and `test_instruction_load.py` — regression only; no new test.

## Delivery estimate and boundaries

Estimate: about 14 changed files — 1 new module (~170 lines), 1 new test file (~200 lines),
1 Nix line, 1 justfile line, a CLAUDE.md sentence, 8 skill documents changed by a few
lines to one section each, 1 contract test file, 1 JSON model. Well inside one review
package; no slice needs to ship alone, since the skill text in Tasks 2–4 calls the command
Task 1 adds.

## Task index

Task 1 — The `verified-tree` command — `python/agent_tools/verified_tree.py`, `tests/test_verified_tree.py`, `lib/agent-tools.nix`, `justfile`, `CLAUDE.md` — full — [task-1.md](2026-10-06-issue-263-checkpoint-verification.tasks/task-1.md)
Task 2 — sdd's Final verification gate — `home/common/agent-skills/skills/sdd/final-review.md`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` — full — [task-2.md](2026-10-06-issue-263-checkpoint-verification.tasks/task-2.md)
Task 3 — The per-task verification ladder — `home/common/agent-skills/skills/sdd/implementer-prompt.md`, `home/common/agent-skills/skills/sdd/fix-loop.md`, `home/common/agent-skills/skills/sdd/final-review.md`, `home/common/agent-skills/skills/writing-plans/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` — full — [task-3.md](2026-10-06-issue-263-checkpoint-verification.tasks/task-3.md)
Task 4 — Ship's one verification step — `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/skills/ship-issue/REVIEW.md`, `home/common/agent-skills/skills/ship-issue/CI-MERGE.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` — full — [task-4.md](2026-10-06-issue-263-checkpoint-verification.tasks/task-4.md)

## Decisions

The spec's `## Decision ledger` owns every decision. Tasks cite D1–D11 from design and
D12, appended at planning.

## Standards review provenance

Reviewer: Codex (gpt-6-astra, xhigh), isolated read-only plan-review, base 40fa9c7db3863a49d31960a71f3c5c1c479b9377, no fallback. Findings: 3 accepted (B1 consolidation commits re-verify, per D13; B2 absolute `PYTHONPATH` for subprocess-spawning tests; S1 stage new files before `just build`), 0 rejected, 0 deferred.
