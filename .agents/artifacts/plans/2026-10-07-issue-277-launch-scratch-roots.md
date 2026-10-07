# Launch Scratch Roots Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `launch-scope scratch` hands each lifecycle launch one scratch root, `launch-scope reap` removes that root together with the git worktrees registered inside it, and every reap reports the worktrees outside the main checkout and outside every recorded root as `unattributed_worktrees`, deleting none of them (#277, slice S3 of the launch process reaping design).

**Architecture:** All code lands in the existing `agent_tools.launch_scope` module. Task 1 adds the `scratch` verb and its `scratch.json` record under the launch's registry directory. Task 2 adds the scratch step to reap's clean round and the `unattributed_worktrees` report member. Task 3 places one `scratch` sentence right after each #276 `exec` sentence in the skills, extends the Self-reap prose and CLAUDE.md, and raises the instruction-load ceilings that grow. Spec: `.agents/artifacts/specs/2026-10-07-issue-277-launch-scratch-roots-design.md` (ledger D1–D9). Its sections **Command surface**, **Scratch record**, **Reap**, **Unattributed worktrees** and **Adoption wiring** are normative, and the members cite them. Parents (read-only): `.agents/artifacts/specs/2026-10-06-launch-process-reaping-design.md` and `.agents/artifacts/specs/2026-10-07-issue-276-launch-scope-exec-reap-design.md`.

**Tech stack:** Python 3 standard library (`tempfile`, `shutil`, `os`, `subprocess`), `git worktree`, Markdown skill text, `unittest`.

## Global Constraints

- Standard library only, no new dependency. No change to `workflow-state`, the ledger schema, the lifecycle guard, `lib/agent-tools.nix`, the Claude settings allowlist, or the three leaf-agent clauses and their carriers (spec **Out of scope**, D7).
- No code path removes a worktree outside a recorded, valid scratch root. Unattributed worktrees are reported only (D6, parent D8).
- External programs are run by name on `PATH`: `git` and `workflow-state` (agent-helpers rule 3). Strict JSON loads compose `reject_duplicate_keys` and `reject_nonfinite_literal` from `agent_tools.canonical` (rule 4). Every JSON line printed to stdout, and the `scratch.json` record, is `canonical_line(value)` followed by one newline.
- Exit codes. `scratch`: 0 and the root's path, 3 and one refusal line, 2 with empty stdout for a usage or helper error. `reap`: #276 D6's 0, 1 and 2, with `scratch_not_removed` as one more skip reason (exit 1). Exit 2 always leaves stdout empty.
- Every test that runs `scratch` sets `TMPDIR` to a directory the test owns (D8). Test fixture environments drop the outer `AGENT_LAUNCH_SCOPE`, as `ScopeHarness` already does.
- Run every test command from the worktree root, in the foreground, with `PYTHONPATH="$PWD/python"` and a timeout of at least 600 s.
- The final gate runs once, on the final head: `just build` and `just agent-workflow-tests`, each with a 3600 s timeout. No task runs them as a per-task gate.

## Test seams

- `python -m agent_tools.launch_scope` subprocess runs through `ScopeHarness` in `tests/test_launch_scope.py`, with real `git worktree` operations, plus in-process calls to `launch_scope.scratch` and `launch_scope.reap` for the branches a real run cannot reach: the creation race and the removal failure (D8, #276 D12).
- Phrase-order contract tests (`assert_ordered` over `normalized()` text) in `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`LaunchScopeWiringContractsTest`, `LaunchScopeSweepContractsTest`).
- The instruction-load ceilings in `home/common/agent-skills/tests/test_instruction_load.py` (`LiveModelTest`) over `home/common/agent-skills/instruction-load.json` (#276 D9).
- `tests/test_agent_tools_launchers.py` and `just build`'s import check, unchanged.

## Delivery estimate and boundaries

Estimates only. About 12 changed files: about 150 added lines in `launch_scope.py`, about 300 added test lines, about 1.5 KB of skill prose over six skill files, one CLAUDE.md sentence and the ceiling bumps. One slice, far from any review-package boundary.

## Task index

Task 1 — `launch-scope scratch` and its record — python/agent_tools/launch_scope.py, tests/test_launch_scope.py — full — [task-1.md](2026-10-07-issue-277-launch-scratch-roots.tasks/task-1.md)
Task 2 — Reap removes the scratch root and reports unattributed worktrees — python/agent_tools/launch_scope.py, tests/test_launch_scope.py — full — [task-2.md](2026-10-07-issue-277-launch-scratch-roots.tasks/task-2.md)
Task 3 — Scratch sentences, Self-reap and CLAUDE.md — home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/skills/from-issue/AUTO.md, home/common/agent-skills/skills/from-issue/ship-handoff.md, home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/skills/sdd/implementer-prompt.md, home/common/agent-skills/skills/ship-issue/SKILL.md, CLAUDE.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-3.md](2026-10-07-issue-277-launch-scratch-roots.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `tests/test_launch_scope.py::ScratchTest::test_repeat_calls_print_one_recorded_root` |
| AC2 | code | Task 2 | `tests/test_launch_scope.py::ReapTest::test_a_reap_removes_the_root_and_the_worktrees_inside_it` and `::test_a_sweep_removes_a_superseded_launchs_root` |
| AC3 | code | Task 2 | `tests/test_launch_scope.py::ReapTest::test_worktrees_outside_every_root_are_reported_and_kept` |
| AC4 | code | Task 3 | `LaunchScopeWiringContractsTest::test_the_worker_sentence_follows_every_composed_worker_line` and `::test_the_owner_runs_long_commands_through_exec` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, under `just agent-workflow-tests`. Per D7 the lifecycle-identity sentences meet the "leaf clause" wording |

## Decisions

Tasks rest on spec rows D1–D8 and on the plan-level row D9 (`scratch` requires a supported platform; a locked, missing registration fails the scratch step). Each member cites the rows it uses.

---
