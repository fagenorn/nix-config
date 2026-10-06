# Owner Resume Pack Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Give every relaunched issue owner a compact, helper-derived resume
pack (`workflow-state resume-pack`), carried in the relaunch prompt, so a
relaunch starts from its exact next action instead of re-orienting by hand
(issue #265).

**Architecture:** A new read-only verb in the legacy `workflow-state` script
gates the action id (per D3, D12), reads the ledger with the unlocked reader,
probes the attempt's recorded worktree with read-only git, reads that
worktree's SDD bucket by `sdd-workspace`'s rule (per D5), and prints one
closed `resume-pack/v1` object ending in a closed `next_action` (per D6, D13).
Skill prose tells relaunchers to add the pack beside the envelope (per D2, D8)
and tells owners how to verify and use it (per D9, D14).

**Tech stack:** Python 3 standard library
(`home/common/agent-skills/scripts/workflow-state.py`), `git` by name on
`PATH`, `unittest`, Markdown skill sources, `instruction-load.json`.

Spec: [2026-10-06-issue-265-resume-pack-design.md](../specs/2026-10-06-issue-265-resume-pack-design.md).
Read it before any task; it owns the design, the pack shape and the decision
ledger. Where the spec says `attempt.<field>` of the pack, read
`ledger.<field>` (per D11).

## Global Constraints

- The command line is exactly
  `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`;
  it takes no `--now` and no other argument (per D3).
- Read-only like `check-launch`: no clock, no lock, no `transact`, no
  `workflow_paths`, nothing created anywhere (no `.superpowers/sdd/`, no
  `state.lock`); git runs only read-only subcommands, and `status` runs with
  `--no-optional-locks`.
- Exit 0 prints the pack through `print_json`; every refusal exits 2 with empty
  stdout and one stderr line `workflow-state: resume-pack refused: <clause>`
  (per D12).
- `check-launch`, `current-launch`, `launch_verdict`, `probe_progress_head`,
  `live_worktree_branch`, the ledger schema, `control` and `direct-owner` are
  not edited (spec Out of scope).
- New code lands in `workflow-state.py`: no new `agent_tools` module and no
  command-table row (per D1).
- Source carries no `TODO` or `FIXME`; comments say why and cite decisions as
  `#265 D<n>`.
- Commits are SSH-signed through `launch-commit` when a lifecycle worker line
  is given; never disable signing. Messages end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run commands from the worktree root; summarise test output to failing
  lines. A gate piping a runner into `tail` starts with `set -o pipefail;`.
- Final verification (sdd's final gate, not per task): `just build`
  (timeout 3600000 ms) and `just agent-workflow-tests` (timeout 3600000 ms).

## Test seams

- The verb runs through `LifecycleHarness.run_cli` in
  `home/common/agent-skills/tests/test_workflow_state.py`, against ledgers
  built by the harness's public commands (`spawn`, `suspend`, `resume`,
  `progress`, `mark_progress`, `fail_owner`, `retry`) and real git repositories
  under the test's temporary directory. No test mocks git or calls a pack
  function directly.
- The bucket rule is pinned by running the real
  `home/common/agent-skills/skills/sdd/scripts/sdd-workspace` against the same
  linked worktree (per D5).
- Skill wording is pinned by ordered-anchor assertions over normalised text in
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py`.

## Delivery estimate and boundaries

Estimates: about 7 files change — 1 script, 2 test modules, 3 skill sources,
`instruction-load.json` and `CLAUDE.md` — roughly 650 added lines, two thirds
of them tests. Growth risk: `test_workflow_state.py` (7,261 lines) and the
instruction-load ceilings, which have no headroom and must rise with the
prose. Tasks are sequential. Task 1 alone is a usable verb whose `sdd` is
always null; Tasks 1–2 complete the helper; Task 3 wires it into the skills.

## Task index

Task 1 — `resume-pack` verb: launch gate, ledger, worktree and commits — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-1.md](2026-10-06-issue-265-resume-pack.tasks/task-1.md)

Task 2 — SDD position and the task-level next actions — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-2.md](2026-10-06-issue-265-resume-pack.tasks/task-2.md)

Task 3 — Relauncher and owner guidance, contract test, CLAUDE.md and ceilings — `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/AUTO.md`, `home/common/agent-skills/instruction-load.json`, `CLAUDE.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-10-06-issue-265-resume-pack.tasks/task-3.md)

All three are `full`: Tasks 1–2 are lifecycle-helper code with a new public
interface, Task 3 changes the instructions that drive lifecycle owners.

## Acceptance coverage

| Issue criterion | Task |
|---|---|
| Read-only verb emitting ledger state, worktree head, commits since checkpoint | 1 |
| Last sdd progress entry, plan/task position, exact next action | 1 (handoff, diverged, start), 2 (SDD, resume/finish, ambiguous) |
| Refuses a non-current launch; active and suspended attempts tested | 1 |
| Relaunch routes carry the pack; owner reads only the current phase's sections; contract test | 3 |
| `just build` and `just agent-workflow-tests` pass | sdd final gate |

## Decisions

This plan rests on the spec's ledger: D1 (legacy script), D2 and D8 (who adds
the pack, which routes), D3 (which launches), D4 (marker as checkpoint), D5
(SDD bucket rule), D6 (closed next action), D7 (size bounds), D9 (owner
verification), and the plan-phase rows D11 (the `ledger` key), D12 (refusal
clauses), D13 (reorient reasons and extra bounds) and D14 (where the guidance
lands).

---
