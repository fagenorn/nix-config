# Launch-Fenced Workers Implementation Plan (#222)

> **For agentic workers:** execute this plan with the `sdd` skill, one implementer
> per task, with a review between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A superseded launch's workers cannot commit into a successor's worktree,
owners cannot exit while their registered workers are live, and the dispatcher
handles the two unaddressed notification cases without judgment.

**Architecture:** `workflow-state` (legacy flat script) gains ledger schema v5 with a
run-level `workers` registry and three verbs (`register-worker`, `release-worker`,
`check-worker`). One shared predicate fences the owner-exit verbs. A new
`agent_tools.launch_commit` command asks `check-worker` and runs `git commit` only
on a live verdict. Skill prose in sdd, ship-issue, from-issue and
orchestrate-issues routes writing dispatches through the registry and the fence.

**Tech stack:** Python 3 standard library, `unittest`, Nix (`lib/agent-tools.nix`
command table), Markdown skills.

Spec: `.agents/artifacts/specs/2026-10-02-issue-222-launch-fenced-workers-design.md`.
Its `## Decision ledger` (D1–D14) is authoritative, and this plan cites rows by ID.

## Global Constraints

- Ledger `SCHEMA_VERSION` becomes `5`. The only new top-level state member is `workers`, and the delivery model's remainder schema is unchanged (per D2).
- The registry verbs live in `home/common/agent-skills/scripts/workflow-state.py` and reply with exact-key, non-envelope JSON. They are not `workflow-response` kinds (per D3).
- `check-worker` is read-only, as `check-launch` is: no clock, no lock, no write, and no `transact` or `workflow_paths` (per D3, D10).
- Controller writes are never fenced: `control`, the deadline reaper, and `direct-owner` (per D4).
- `launch-commit` is a new `agent_tools` module and command-table row. It runs `workflow-state` by command name on `PATH` and never edits `sys.path` (agent-helpers rules 1–3, per D5).
- No change to the Claude settings allow surface, the lifecycle guard, `check-launch`, or the #125 transaction core (per D9 and the spec's Out of scope).
- New skill prose describes only behavior the implemented code has. Each task raises any `instruction-load.json` ceiling its growth breaches, to the measured value, and appends a `Ceiling raised for #222: <why> (#155 D10).` sentence to that profile's `note`.
- Commits are signed (never pass `--no-gpg-sign`) and end with the session's `Co-Authored-By` and `Claude-Session` trailers.

## Test seams

- `workflow-state` CLI via `LifecycleHarness` in `home/common/agent-skills/tests/test_workflow_state.py`, plus the existing delivery flows in `test_delivery_workflow.py` for `finish --summary-file` and a suspending `checkpoint-delivery`.
- `python -m agent_tools.launch_commit` in `tests/test_launch_commit.py`, with a PATH shim running the source `workflow-state.py` (per D14).
- Skill contract assertions in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, using the existing `normalized` and `assert_ordered` helpers.
- The live instruction-load ceilings in `home/common/agent-skills/tests/test_instruction_load.py` (`LiveModelTest`).
- Installed layout: the existing `tests/test_agent_tools_launchers.py` covers the new row.

## Delivery estimate and boundaries

These figures are estimates. About 14 changed files. `workflow-state.py` grows by
about 300 lines and its two test modules by about 450. The skill documents grow by
2–4 KB in total, which raises several instruction-load ceilings. Tasks 1–3 form
an independently deliverable code slice (registry, fence, command). Tasks 4–6 are
the prose slice and depend on the verbs that Tasks 1–3 ship. The diff should fit
one review package. If it does not, split at the 3/4 boundary.

## Task index

Task 1 — Ledger schema v5 and worker registry verbs — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/scripts/workflow_delivery.py, home/common/agent-skills/tests/test_workflow_state.py, home/common/agent-skills/tests/test_delivery_workflow.py, home/common/agent-skills/tests/test_host_admission.py — full — [task-1.md](2026-10-02-issue-222-launch-fenced-workers.tasks/task-1.md)
Task 2 — Owner-exit refusal while workers live — home/common/agent-skills/scripts/workflow-state.py, home/common/agent-skills/tests/test_workflow_state.py, home/common/agent-skills/tests/test_delivery_workflow.py — full — [task-2.md](2026-10-02-issue-222-launch-fenced-workers.tasks/task-2.md)
Task 3 — `launch-commit` command and acceptance test — python/agent_tools/launch_commit.py, lib/agent-tools.nix, justfile, tests/test_launch_commit.py — full — [task-3.md](2026-10-02-issue-222-launch-fenced-workers.tasks/task-3.md)
Task 4 — sdd registers writing workers and fences their commits — home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/skills/sdd/implementer-prompt.md, home/common/agent-skills/skills/sdd/fix-loop.md, home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-4.md](2026-10-02-issue-222-launch-fenced-workers.tasks/task-4.md)
Task 5 — from-issue and ship-issue register, fence and release before exit — home/common/agent-skills/skills/from-issue/SKILL.md, home/common/agent-skills/skills/from-issue/AUTO.md, home/common/agent-skills/skills/from-issue/ship-handoff.md, home/common/agent-skills/skills/ship-issue/SKILL.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-5.md](2026-10-02-issue-222-launch-fenced-workers.tasks/task-5.md)
Task 6 — Dispatcher rules (a) and (b), and CLAUDE.md — home/common/claude-code/skills/orchestrate-issues/SKILL.md, CLAUDE.md, home/common/agent-skills/instruction-load.json, home/common/agent-skills/tests/test_workflow_skill_contracts.py — full — [task-6.md](2026-10-02-issue-222-launch-fenced-workers.tasks/task-6.md)

## Decisions

Spec rows D1–D10 govern the design. Planning added D11 (owner-exit predicate and
the checkpoint `--worker-id` excuse), D12 (reply shapes and refusal vocabulary),
D13 (a fresh `worker_id` per dispatch, carried as a prompt line) and D14
(acceptance-test seam).

Final verification after Task 6: `just agent-workflow-tests` and `just build` both pass.
