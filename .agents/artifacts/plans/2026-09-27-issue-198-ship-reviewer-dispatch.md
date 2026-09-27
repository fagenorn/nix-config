# Ship Reviewer Dispatch Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** a `from-issue --auto` owner at any launch depth completes Phase 7
without a nested ship owner that lacks the subagent-launch tool, and a genuinely
missing dispatch capability suspends the attempt on `agent_dispatch` instead of
spending it
([#198](https://github.com/fagenorn/nix-config/issues/198)).

**Architecture:** workflow-state gains one owner-reportable suspension cause,
`agent_dispatch`, that only a human-directed re-entry clears (Task 1).
ship-issue probes for the subagent-launch tool as Phase 0's first step and, when
it is missing, returns the closed line `capability_gap: agent_dispatch` before any
write. REVIEW.md and the ship-handoff prompt stop claiming nested dispatch always
works (Task 2). from-issue Phase 7 answers that line with the dispatch-gap
fallback. That fallback runs `check-launch`, then ships inline through `Skill`, and
suspends on a second gap line (Task 3). AUTO.md's rollover owner names the
fallback, its earlier controller relays a delegated owner's re-entry or suspension
line, and the orchestrate report names the new cause (Task 4).

**Tech stack:** Python 3 stdlib (`argparse`, `unittest`), Markdown skill prose,
`just`.

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-27-issue-198-ship-reviewer-dispatch-design.md`,
D1–D19.

## Global Constraints

- Scope is exactly the spec's. Its `## Out of scope` list binds. Out: dispatch
  in Phases 2–6 from a depth-3 owner, the remainder launch at depth 3, a
  dispatcher-launched ship owner, host or host-declaration changes, retrying a
  Phase-5 launch failure after a passing probe, HUMAN-GATE's `stopped`
  return, and carrying `agent_dispatch` into #117's record or the core, which
  is #125's (D12, D13, D18).
- No task merges `origin/main` or edits `instruction-load.json`. ship-issue
  Phase 1's sync owns both, and resolves that file per D19 (D16).
- The gap line is exactly `capability_gap: agent_dispatch`: one closed line,
  compared byte for byte, never decoded and never validated. It is never
  hard-wrapped (D4).
- `agent_dispatch` joins `BLOCKED_ON_VALUES`, and so the derived owner set and
  the `suspend --blocked-on` choices. It is not in `AUTO_RESUMABLE_BLOCKED_ON`.
  `STALL_LIMIT`, `SCHEMA_VERSION`, the remainder blocker set in
  `workflow_delivery.py` and the checkpoint-response set in
  `delivery_model/_wire.py` do not change (D6, D7).
- The `from-issue-ship-owner` marker and its call line stay byte-identical.
  `model-matrix.json` gets no new site, and `ship-issue/HUMAN-GATE.md` does not
  change (D8, D9).
- New prose never contains the literal substring `Agent(`. The model-matrix
  validator flags any unregistered line holding it. Every new fence is labeled
  `text`, because ship-handoff.md keeps exactly one unlabeled fence and
  from-issue/SKILL.md's only unlabeled fence is its flow diagram.
- from-issue Phase 7 and AUTO.md's `#### Fresh delegated owner` never spell
  `workflow-state suspend`. AUTO.md never writes `blocked_on:` or `blocked_on=`
  followed by a value word other than `human_gate`. Existing pins enforce both.
- The route is named the **dispatch-gap fallback**. Wherever the Phase-7 summary
  may come from the inline run, it is "the ship report's", not "the ship
  owner's" (D14).
- Tests use only seams S1 and S2 below (D11). The helpers under `~/.agents/bin`
  are `main`'s build. Every gate runs this worktree's scripts, directly or
  through the tests. Never open or repair `.superpowers/workflows/` in the
  primary checkout.
- No file is created and no `.nix` file changes. `just build` runs once, in
  Task 4's final gate. Never run `just switch`.
- Run targeted tests from the worktree root as
  `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/<file>.py -k <pattern>`.
  A contract failure prints the whole skill file, so summarize output to the
  `FAIL:`/`ERROR:` ids and the `Ran`/`OK`/`FAILED` lines.
- Commits are conventional and SSH-signed. Never disable signing, and surface a
  signing failure. Each message ends with the two trailer lines
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_013ho926R9qjak8E3fLvEdq6`,
  unless the executing session's attribution names other lines.

Path abbreviations used in members: `S` = `home/common/agent-skills/scripts`,
`T` = `home/common/agent-skills/tests`, `K` = `home/common/agent-skills/skills`,
`O` = `home/common/claude-code/skills/orchestrate-issues/SKILL.md`.

## Test seams

- **S1, the workflow-state CLI driven from source:** `LifecycleHarness` in
  `T/test_workflow_state.py` (`spawn`, `suspend`, `control(human_directed=…)`,
  `acquire_direct`, `direct_owner`, `assert_controller_finalized`). It covers
  the spec's T1–T3 (D6, D11).
- **S2, the prose-contract suite:** `WorkflowSkillContractsTest` in
  `T/test_workflow_skill_contracts.py`, plus one module constant
  `CAPABILITY_GAP_LINE`. Each skill task adds its ordered-anchor tests (D11).
- **Unchanged and required green:** `T/test_dispatch_contracts.py`,
  `T/test_agent_model_matrix.py`, `T/test_shell_example_contracts.py`,
  `T/test_host_admission.py`, and every existing pin in the contract suite,
  including the HUMAN-GATE and final-report pins.

## Delivery estimate and boundaries

The tasks change nine files and create none. Product prose grows by about 65
lines net across six skill files, and `S/workflow-state.py` by about 5. Tests
grow by about 250 lines across two files. Tasks run in index order, and each
depends on every earlier one. The plan adds 10 tests: 3 in Task 1, 3 in Task 2,
2 in Task 3 and 2 in Task 4. Task 3 and Task 4 each also widen Task 2's identity
test by one document. The main risk is prose that breaks an existing ordered
pin, and each task's targeted suite run catches that before commit.

**Execution state (run 2).** Tasks 1–4 landed as `37b829a`, `880e370`,
`6674a5a` and `6859d0e`, and run 2 re-executes none of them (D16). Run 1's ship
sync of `447461c` (#155) then added `5361013` and `765f598`, which change
`home/common/agent-skills/instruction-load.json` and `T/test_instruction_load.py`
outside every task; D19 keeps their `conditional` ship-issue members. Measured
at `765f598` against `447461c`, the branch changes 11 files and its diff is
about 42 KB, so one review package still holds it. The post-sync size is an
estimate.

**Ship gate after the sync.** Run 2's ship-Phase 1 merges `origin/main`
(`6ab576e` or later), and `instruction-load.json` is its one expected conflict.
`just agent-workflow-tests` includes `T/test_instruction_load.py`, which fails
on the merged tree if the sync takes either side of that file, so the sync
resolves it per D19. Both verification commands, `just build` and
`just agent-workflow-tests`, are therefore graded on the post-sync head. D17
leaves Task 2's probe prose true under #195's
correctness routing, and D18 leaves #117's record to #125.

## Task index

Task 1 — workflow-state admits the `agent_dispatch` suspension cause — `S/workflow-state.py`, `T/test_workflow_state.py` — full — [task-1.md](2026-09-27-issue-198-ship-reviewer-dispatch.tasks/task-1.md)

Task 2 — ship-issue probes reviewer dispatch before any write and returns the gap line — `K/ship-issue/SKILL.md`, `K/ship-issue/REVIEW.md`, `K/from-issue/ship-handoff.md`, `T/test_workflow_skill_contracts.py` — full — [task-2.md](2026-09-27-issue-198-ship-reviewer-dispatch.tasks/task-2.md)

Task 3 — from-issue Phase 7 ships inline on the gap and suspends on a genuine one — `K/from-issue/SKILL.md`, `T/test_workflow_skill_contracts.py` — full — [task-3.md](2026-09-27-issue-198-ship-reviewer-dispatch.tasks/task-3.md)

Task 4 — Rollover owner, earlier controller and orchestrate report carry the new outcome, then the final gate — `K/from-issue/AUTO.md`, `O`, `T/test_workflow_skill_contracts.py` — full — [task-4.md](2026-09-27-issue-198-ship-reviewer-dispatch.tasks/task-4.md)

## Criterion → task trace

| Criterion | Task |
|---|---|
| AC1: an orchestrated or background `--auto` owner completes Phase 7 without a nested ship owner lacking the launch tool | 2 (the probe returns the gap before any write), 3 (the dispatch-gap fallback ships inline), 4 (the rollover owner's allowed departure) |
| AC2: a missing capability is a distinct outcome, not a generic `terminal_failed` | 1 (`agent_dispatch`), 3 (the suspension on a genuine gap) |
| AC2: it is resumable and does not consume the attempt | 1 (T1–T3), 4 (the earlier controller relays the suspension line, and the orchestrate report names the per-issue re-entry) |
| Spec prose corrections: ship-handoff "Nested Agent calls are supported.", REVIEW.md's nested-dispatch aside | 2 |
| Spec S2: probe first in Phase 0; one gap spelling; Phase-7 order; suspension list; AUTO order and relays; orchestrate report | 2, 3, 4 |

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D13 from design
and grill. Planning added **D14**, which names the route the dispatch-gap
fallback and renames every "ship owner's" summary sentence an inline run would
make false. Plan review added D15. The run-2 re-grill added D16–D19, and none
of them changes a task: Task 1 cites D18, Task 2 cites D17, Task 4's final gate
cites D19, and D16 and D19 bound the delivery section above. The run-2
re-verification added no ledger row.

A planning probe applied every task's code, tests and prose, as written, to a
scratch copy of `de7c558`. Each watch-it-fail step failed as its member says,
and each targeted gate passed. `T/test_workflow_state.py` and
`T/test_host_admission.py` together gave `Ran 174 tests` and `OK`. The four
contract suites (`T/test_workflow_skill_contracts.py`,
`T/test_dispatch_contracts.py`, `T/test_shell_example_contracts.py` and
`T/test_agent_model_matrix.py`) gave 217 tests at base, then 220, 222 and 224
after Tasks 2, 3 and 4, ending `OK (skipped=3)`. `agent_model_matrix validate`
printed `agent model matrix: valid`. `WORKFLOW_POLICY_SURFACE=source just
agent-workflow-tests` gave `Ran 1326 tests` and `OK (skipped=4)`, which is the
base 1316 plus these 10. `just build` was not probed.

## Standards review provenance

- Run 1 (`direct-198-000001`) reviewer: Claude fallback (one fresh native `reviewer`, Opus/high), isolated and
  read-only, against `REVIEW-CONTRACT.md`. Codex `plan-review` ran first and
  completed, but its `--json` stream carried no runtime-selection event naming
  the selected model and reasoning effort. That is a metadata failure, so
  Codex identity was not established, the one native fallback ran with the
  same packet, and Codex was not retried.
- Base `17da7f2d53c33886073a107ce72627f9e1ec5ce1`, plan reviewed at `0aacb50`;
  no focus configured.
- Accepted 2: SF-1 (Task 3, Step 4, items 5–6) and DI-1 (Task 1's T2
  attempt-count assertion), both per D15. Decided without an edit: DI-2 (the
  Phase-7 gate after an inline ship stays the spec's unchanged generic gate).
  Rejected 0, deferred 0. No Blocking findings.

---
