# Expiry suspends and resumes in place — Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A wall-clock expiry never consumes an attempt: the reaper demotes the
expired attempt to `suspended(unknown)` on every touch, and the existing
suspension lane resumes it in place under its own attempt number, whatever the
dispatcher's capacity happened to be.

**Architecture:** `_apply_one_issue_policy` gains a single, unconditional reaper
call placed before every lane predicate is derived, with the forge-merged
reconciliation hoisted above it; `expired` leaves `retryable`, so a reaped
attempt is an ordinary suspension and the four in-lane `demote_expired_attempt`
calls become unreachable and are deleted. `expired` and `changed` are propagated
truthfully out of every branch a reaped attempt can reach, `command_control`'s
fallback persistence pass is narrowed so it cannot overwrite a dispatched
resume, and `command_direct_owner` gains one branch for the anti-zombie
escalation that this change makes reachable for the first time.

**Spec (the contract):**
`.claude/specs/2026-08-25-issue-133-expiry-resume-in-place-design.md`. Read it
before any task. Its `## Decision ledger` (D1–D14) is the single home for
rationale; this plan cites rows by ID and never restates them. Its
`## Out of scope` is binding.

**Issue:** https://github.com/fagenorn/nix-config/issues/133

**Tech stack:** Python 3 standard library only (`argparse`, `json`, `copy`,
`pathlib`, `unittest`); Markdown skill prose; Nix flake (`just build`).

## Global Constraints

- Python: standard library only; no new third-party dependency, no new file, no
  new CLI verb, no new delta or action kind. `CONTROL_DELTA_KINDS` and
  `CONTROL_DISPATCH_KINDS` are unchanged closed sets (per D8).
- No persisted field changes shape: `schema_version` does not move and no ledger
  migration is written (per D8, and the spec's `## Out of scope`).
- Tests exercise the source at `home/common/agent-skills/scripts/workflow-state.py`
  through `run_cli(...)`, never the installed `~/.agents/bin/workflow-state`
  symlink (an older Nix generation). Do not run `just switch`.
- Skill prose is hard-wrapped at ~80 columns. Contract assertions over a wrapped
  sentence compare against `normalized(text)` (the module helper that collapses
  whitespace runs to one space).
- Prose a task gives inside a `>` block is the **text to insert**, quoted only
  for readability. Insert it as ordinary prose — never as a Markdown blockquote.
- Out of scope, in every task: issue #125 (epoch-fenced leases — this change is
  its regression floor); the attempt cap; `new_run`'s code; migrating ledgers
  already parked in `retry_refused`; the retry lane's other two entrances
  (owner-reported `failed`, legacy `stopped`/`result_source: "expiry"`);
  #132's `check-launch` verb and its tests; `CLAUDE.md`.
- Never weaken #132's tests. `test_check_launch_supersedes_a_predecessor_attempt_after_a_failed_owner`
  carries an inline comment forbidding an expiry-driven fixture — honour it.
  `test_check_launch_supersedes_a_predecessor_launch_after_a_resume` must keep
  passing untouched.
- Tests that asserted expiry → a fresh attempt 2 or a refusal are **rewritten to
  the new contract, never deleted** (issue AC4). Exactly four break; they are
  named in the Task index below and in Task 1.
- Commits are SSH-signed. **Never** pass `-c commit.gpgsign=false` or
  `--no-gpg-sign`; surface signing failures. Every commit carries
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Test seams

Existing seams only; no new ones (spec, `## Test seams`).

- **Seam 1 — the `workflow-state` CLI via subprocess.**
  `home/common/agent-skills/tests/test_workflow_state.py`,
  `WorkflowStateLifecycleTest`, through its `run_cli(...)`, `init_run`, `spawn`,
  `control`, `finish`, `suspend`, `resume`, `retry`, `expire`, `fail_owner`,
  `legacy_expiry_record`, `acquire_direct`, `direct_owner`, `dispatch_action`,
  `tracker_fact`, `worktree_fact` and `read_state` helpers. The module is never
  imported. The `expire(...)` helper drives a **tracker-closed** sweep, so it
  exercises the tracker-halt branch only; the capacity cases build their sweeps
  from `control(...)` directly with an open tracker.
- **Seam 2 — skill prose.**
  `home/common/agent-skills/tests/test_workflow_skill_contracts.py`,
  `WorkflowSkillContractsTest`, through its `section(...)`, `assert_ordered(...)`
  and `normalized(...)` helpers. Every new assertion anchors on wording that is
  absent at base, so it can actually fail.
- **Seam 3 — `just build`.** The Nix evaluation check; there is no unit-test
  suite for the Nix configs.
- **Seam 4 — the built Claude settings.** `tests/test_claude_permission_guard.py`.
  Untouched: `workflow-state` is not on the allow surface and no verb is added,
  so this is a gate here, never a target.

## Task index

Task 1 — Reap first, resume in place — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-1.md](2026-08-25-issue-133-expiry-resume-in-place.tasks/task-1.md)
Task 2 — The anti-zombie escalation becomes a real terminal — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-2.md](2026-08-25-issue-133-expiry-resume-in-place.tasks/task-2.md)
Task 3 — Expired handoffs resume in place with a validated document — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` — full — [task-3.md](2026-08-25-issue-133-expiry-resume-in-place.tasks/task-3.md)
Task 4 — Corrected prose in three homes, then the whole-change gate — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-4.md](2026-08-25-issue-133-expiry-resume-in-place.tasks/task-4.md)

Lane notes: every task is `full`, as the spec's `## Test seams` requires. Tasks
1–3 rewrite lifecycle policy and its two callers outright. Task 4 is `full` too
despite being prose: the `low-risk` lane excludes anything touching lifecycle or
public contracts, and Task 4 rewrites the accounting statements two agent
audiences act on, pinned by contract tests. Being small is not what qualifies a
lane. Nothing here is `mechanical` — the four deleted `demote_expired_attempt`
call sites are deleted *because* the semantics moved, not as tidying.

**The four tests rewritten, not deleted** (issue AC4), all in
`test_workflow_state.py`, all in Task 1:

| Test | Line at base | Why it breaks |
|---|---|---|
| `test_control_combined_six_stage_single_ledger_replay` | 1243 | asserts `["expired","retried","spawned"]` and action id `51:2:1` |
| `test_control_demo_3_expires_retries_and_fills_unrelated_capacity` | 1380 | asserts `["retry","spawn","wait"]` and `51:2:1` |
| `test_control_attempt_two_deadline_emits_only_retry_refused` | 1638 | asserts a `retry_refused` delta reached by attempt 2's deadline |
| `test_direct_expiry_retries_on_absent_candidate_then_refuses_attempt_two` | 4612 | asserts a direct `retry` on attempt 2, then a `refused` terminal |

`test_control_expiry_deltas_follow_reversed_request_order` (1409) stays green
unchanged but is **strengthened** in Task 1 to assert the whole delta object, so
the reaped state it now reports is pinned rather than merely unobserved.

## Acceptance-criteria coverage

| AC | Discharged by |
|----|---------------|
| AC1 — expiry never enters the retry lane; free slot suspends and resumes the same attempt with a fresh deadline | Task 1 |
| AC2 — two expiries yield two resume launches, not `retry_refused`; the anti-zombie bound still escalates | Task 1 (double expiry), Task 2 (escalation) |
| AC3 — the retry lane still opens one fresh attempt for owner-reported `failed` and legacy `stopped`/`expiry` | Task 1 (untouched-suite gate) |
| AC4 — free-slot / no-slot / double-expiry coverage; the four expiry→attempt-2 tests rewritten, not deleted | Task 1 |
| AC5 — the ledger's same-sweep-vs-next-sweep row; corrected from-issue and orchestrate-issues prose guarded by `test_workflow_skill_contracts.py` | spec row D2 (already committed), Task 4 |
| AC6 — `just build` succeeds | Task 4 (whole-change gate) |

## Decisions

Spec rows D1–D12 are the design record; cite them, never restate them. Planning
appended two rows to the **spec's** ledger:

- **D13** — the rewritten direct-run test pins resume-in-place on the *recorded*
  worktree (the reaped attempt is at phase 0, so `absent_phase_zero_pause`
  covers an `absent` observation) and pins the inherited dead end with a
  `mismatch` observation instead (Task 1).
- **D14** — `retry_refused` keeps live coverage through the owner-reported
  entrance after its expiry-driven test is re-pointed (Task 1).

## Follow-up, not filed here

The spec's `## Out of scope` proposes one new issue — *"A suspended attempt whose
recorded worktree is gone has no exit"*. This plan does not file it and does not
fix it; Task 1 pins the inherited behaviour so it is visible rather than silent.
Surface it as a ship-time discussion item.

## Verification

Whole-change gates, all run from the worktree root:

```sh
just agent-workflow-tests
python3 tests/test_claude_permission_guard.py
just build
```

`just agent-workflow-tests` is 455 tests and green at base; it covers
`test_workflow_state.py` and `test_workflow_skill_contracts.py`, the two suites
this change touches. The permission-guard suite is not in that recipe and is run
separately; it must stay green untouched (Seam 4). Task 4 runs all three; every
earlier task runs the single suite it moves.
