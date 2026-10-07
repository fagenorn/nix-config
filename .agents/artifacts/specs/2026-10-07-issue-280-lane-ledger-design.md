# Lane ledger and lane budgets (#280) — design

Slice 2 of the [light-lane design](2026-10-06-light-lane-budgets-design.md).
That spec's "`workflow-state` ledger (schema 6 → 7)" paragraph, D10 and D11
are the requirements; this spec settles only what they leave open and does not
restate them.

## Problem

An owner that triages its issue cannot yet record the result. The ledger has no
lane, so a light attempt cannot get the shorter window, an escalation cannot
restore the full one, and a suspension resume always grants the request's flat
`attempt_budget_minutes`, whatever lane the attempt was running in.

## Solution

Bump the `workflow-state` ledger to schema 7 with the three attempt fields,
add the `declare-lane` verb, and make the suspension resume lane-aware. No
skill text calls `declare-lane` yet: #279 produces the triage, and #282 wires
the routes.

## Decisions

**Schema 7.** Each attempt carries `lane` (`null | "light" | "full"`),
`lane_budget_minutes` (`null | positive int`) and `lane_history` (a list of
closed `{lane, reason, at}` objects). The attempt validator checks that the
three fields agree (D3). A fresh attempt and a retry attempt both start at
`null`, `null`, `[]` (D5). The delivery runtime's migration chain gains a
`6 → 7` step, which sets those defaults. If a schema-6 attempt already carries
any of the three keys, the document is a hybrid and is refused, following the
precedent of every earlier step.

**`declare-lane`.**
`workflow-state declare-lane --repo-root <root> --run-id <id> --now <utc> --action-id <action_id> --lane <light|full> --budget-minutes <n> --reason <reason>`.
It is shaped like `mark-progress`. The launch must be `current` under
`launch_verdict`, a remainder launch (`:r`) is refused, `--now` must not
precede the run's `updated_at`, and the verb does not pass `fence_owner_exit`,
because it ends no launch and so does not care about live workers. Within one
locked transaction it:

1. refuses any transition other than `null→light`, `null→full` and `light→full`,
   and any reason that is not allowed for that transition (D2);
2. computes `launch_at + n` from the current launch event's `at`, and refuses
   when that instant is not after `--now`, for either lane (D1);
3. sets `lane`, `lane_budget_minutes = n` and `deadline_at`, appends
   `{lane, reason, at: --now}` to `lane_history`, and bumps `updated_at`.

It leaves `last_progress_at`, `phase` and the stall fields untouched. On
success it exits 0 and prints
`{"action_id", "lane", "budget_minutes", "deadline_at"}`. A refusal is a
`WorkflowError`, which exits non-zero and writes nothing (D4).

**Lane-aware resume.** `resume_attempt` keeps its signature. The suspension
branch of the one-issue policy passes `lane_budget_minutes` when it is set and
the request's `attempt_budget_minutes` otherwise. A resume inside the live
window (a handoff rollover, a dead-owner takeover) still passes `None`. The
lane persists across launches. `declare-lane` always re-bases from the
*current* launch's `at`.

**Unchanged surfaces.** `control` and `direct-owner` keep their request shapes,
response shapes and interface versions. `resume-pack` v1 is unchanged, because
its `deadline_at` already reflects the re-base (D6). CLAUDE.md gains no
`declare-lane` text until #282 gives the verb a caller; its `mark-progress`
bullet only reads "added in ledger schema 6", so the number stays true (D7).

## Test seams

The only seam is `test_workflow_state.py`, which drives the command as a
subprocess against a temporary ledger, following the `mark-progress` and
`register-worker` prior art. The cases are the issue's four acceptance
criteria, plus these refusals: a disallowed reason, a full declaration whose
re-based deadline has passed, a remainder launch, and a schema-6 hybrid. Every
existing fixture that builds or pops attempt fields is updated mechanically
to schema 7, in the same suites it lives in. No new seam is introduced.

## Out of scope

- `lane-triage` and the `light_lane` policy member (#279).
- `blocked_on=deadline` and the boundary-suspension rule (#281).
- Skill routes, escalation triggers and any skill text that calls `declare-lane` (#282).
- Budget enablement and the values 90 and 240 in `.agents/project.json` (#284).
- Making `workflow-state` read its own clock (#309). `--now` stays as it is on main.
- Exposing `lane` in `resume-pack` or in the `control` response.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Refuse a declaration of **either** lane when `launch_at + n` is not after `--now`. An owner that has outrun even the full window suspends; after the resume, it re-declares `full` on the new launch, which is re-based from that launch's `at` | The validator invariant `last_progress_at ≤ deadline_at`, with `--now ≥ updated_at ≥ last_progress_at`, makes a future deadline the condition under which a re-base stays valid; parent spec refuses light on this ground | Accept a passed `full` re-base: it writes an already-expired deadline that can precede `last_progress_at`, which the validator rejects. Keep the old deadline: the lane and the window disagree |
| D2 | Reasons are constrained per transition: `null→light` and `null→full` accept only `triage`; `light→full` accepts only `important_finding`, `second_fix_round`, `light_deadline` and `unpredicted_risk` | The parent spec's flows: shadow and interactive force `full --reason triage`, and the D8 triggers are the escalations; the-bar "Fail loud" | Any reason on any transition: it lets the history record an escalation that never happened, and the same reason set would need a cross-check later |
| D3 | The validator enforces consistency: `lane` is null ⇔ `lane_budget_minutes` is null ⇔ `lane_history` is empty; the last entry's lane equals `lane`; the entries follow the D2 transitions and reasons; each `at` parses as UTC, does not decrease and is not before `started_at` | Every attempt field is closed and validated on load (`validate_attempt`) | Trust the writer: a hand-edited or hybrid ledger would load with a lane its history contradicts |
| D4 | A repeated identical declaration (`light→light`, `full→full`) is refused like any other disallowed transition, not replayed. The refusal names the attempt's current lane, so a caller retrying after a lost reply can see that its first call landed | Acceptance criterion (`light→light` refused); `register-worker` is not idempotent either | Idempotent replay keyed on the action id: it adds state for a retry case no caller has yet |
| D5 | The lane is attempt-scoped. It survives every launch of its attempt, and a new attempt (a retry or a fresh acquisition) starts at `null` and is triaged again | Parent D10: acquisition always uses the full budget; triage happens after acquisition | Inherit the predecessor's lane: a failed attempt's triage is exactly the judgment in doubt |
| D6 | `declare-lane`'s reply has no `workflow-response` boundary kind, and `resume-pack` gains no `lane` | `mark-progress` precedent: its reply is unvalidated, and the boundary covers the `control` reply and `check-launch` only. No consumer of the lane in the pack exists before #282 | A new boundary kind and a pack v2: a contract change with no reader |
| D7 | No CLAUDE.md or skill text describes `declare-lane` in this slice | The verb has no caller before #282; CLAUDE.md is under the Instruction Budget gate; the-bar YAGNI | Document it now: it grows a gated budget for a verb no agent invokes yet |
