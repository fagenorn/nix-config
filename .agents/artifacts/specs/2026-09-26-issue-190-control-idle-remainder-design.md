# Control queues only dispatches: live and stalled remainders, issue 190

## Problem

`workflow-state control` is the orchestration adapter's only view of the run.
When an issue's current custody is a live delivery remainder and a dispatch
slot is free, the command exits with `KeyError: 'idle'` and writes nothing. The
next sweep that includes the issue crashes the same way. The adapter can make
progress only by dropping the issue from `issues`, which also drops the running
owner from the run it belongs to.

Two more symptoms have the same cause. A remainder that expires at its stall
bound crashes the sweep with `KeyError: 'terminal'`. When the declared agent
slots are exhausted but `max_parallel` still has room, a live remainder does
not crash the sweep. It is listed in `admission.waiting` instead, and
orchestrate-issues reports every waiting issue to the human as "queued for
agent slots" while that issue's owner is in fact running.

Reproduced at `affa05e` on the `claude-code` route, using the committed 7-slot
declaration (a scratch test driving the CLI):

| Custody at the sweep | Base result | Required result |
|---|---|---|
| Active remainder that control just dispatched (`r1:2`), one free slot | `KeyError: 'idle'` | Same response as with capacity exhausted |
| Active remainder with an expired deadline at the stall bound (`r1:4`, `stalled_resumes` 2) | `KeyError: 'terminal'` | Remainder persisted `failed` (`stalled`), no dispatch |
| Live claimed remainder, 4 declared slots, `max_parallel` room | `waiting: [151]` | `waiting: []` |
| Suspended remainder (`human_gate`), recorded worktree observed, free slot | `delivery_remainder` `r1:2` | Unchanged |

### Cause

The lane selector does not describe the custody correctly, and the step that
queues a dispatch does not check what it queues.

1. **Classification.** Control plans every issue once with dispatch withheld and
   routes the issue to a lane by the result's `desired`. Only control's lanes
   read `desired`. The implementation lane labels live custody `idle` and a
   stall-bound terminal `terminal`. The remainder lane (`remainder_policy`)
   labels every result `resume`, so a live or stalled remainder enters the
   resume lane.
2. **Admission.** The resume lane plans again with dispatch permitted. It
   filters out `observe` (raises) and `contract` (skips), then queues whatever
   is left into `proposal_order`, charges a `max_parallel` unit and claims a
   role set. Five lanes repeat this queue-and-charge step, and each has its own
   filter. The action loop's closed `{spawn, resume, retry}` delta map then
   fails on `idle` or `terminal`.

The live-remainder crash needs an `idle` result with dispatch permitted. That
happens only for an `active` remainder whose owner is not observed unavailable.
A suspended remainder resumes, or asks for its worktree. The issue's first
sighting ("`150:r1:3` suspended") must therefore have had `r1:3` still `active`
in the ledger at the time. The crash writes nothing, and the ledger keeps no
event log, so this cannot be confirmed. The fix covers both cases either way
(D4).

## Solution

Each half gets one change, and each change becomes the only home of its rule
(D1).

1. **Truthful remainder classification.** Each remainder result says what its
   custody wants: `idle` for a live remainder, `terminal` for a stall-bound
   failure, and `resume` for everything else. The remainder's operations,
   ledger transitions and direct-owner behaviour do not change (D2).
2. **One admission step.** Inside `command_control`, a single step queues a
   planned result into `proposal_order` and charges it a `max_parallel` unit
   and a role-set claim. It queues only `CONTROL_DISPATCH_KINDS` operations,
   and every dispatch lane goes through it (D3).

After the change, a live remainder never enters a dispatch lane. A stalled
remainder is persisted by the existing expiry fallback, the same way a stalled
implementation attempt is. Nothing that is not a dispatch reaches the action
loop.

## Decisions

### Remainder classification (D2)

`remainder_policy` sets `desired` on every result it builds:

- **`idle`**: the remainder is `active` and its current launch is not observed
  unavailable, whether or not dispatch is permitted. The lane selector skips
  the issue entirely. It never reaches `refusal_gated` or `slot_withheld`, it
  joins no `waiting` set, it is not planned again, and it takes no slot or
  claim.
- **`terminal`**: the remainder is `failed`. The only way to reach this is the
  in-sweep reap that crosses the stall bound. The lanes skip the issue, and the
  expiry fallback (`issue not in planned`, from #133 D7) persists the failure
  and emits the `expired` delta. This is the same path a stalled
  implementation attempt takes.
- **`resume`**: every other result keeps its current label. That covers a
  suspended remainder, one reaped to suspended, an `active` remainder whose
  owner is unavailable, and every `observe` result.

`operation`, `changed`, the reaper and the stall bound do not change. The
direct owner never reads `desired`, so its behaviour is unchanged by
construction.

### The admission step (D3)

This is a nested helper beside `slot_withheld`, `refusal_gated` and `acquire`.
It takes an issue and its planned result, plus a `charge` flag that defaults to
true.

- If the operation is not in `CONTROL_DISPATCH_KINDS`, it queues nothing,
  charges nothing, and reports that it did not admit the issue. The planned
  result stays in `planned`, so a `changed` result is still persisted and its
  summary still reports it.
- Otherwise it appends the issue to `proposal_order`. When `charge` is true it
  also calls `acquire` and spends one `max_parallel` unit.

It has five callers. The first-remainder lane keeps its `custody_kind` filter.
The recover lane passes `charge` as its analysis's `changed`, because a
re-emitted recover takes no new claim (#150 D21). The resume, retry and spawn
lanes each keep their own `observe` refusal. Each lane also keeps its own
pre-checks: capacity, `slot_withheld`, `refusal_gated` and the round-still-owed
skip. The three per-lane `contract` skips are deleted, because the step's
membership test covers them. `refuse` stays a lifecycle entry: it is queued
without a charge, and the action loop handles it explicitly.

The action loop's closed delta map is still the fail-loud inner check, and it
is not edited. `proposal_order` now holds only `spawn`, `resume`, `retry`,
`recover` and `refuse`, and the loop covers all five. The expiry fallback's
`issue not in planned` guard stays too: it protects a result that has already
been queued from being planned again (D6).

### Response contract (D5)

- **Live remainder with a free slot.** The response is byte-identical to the
  same sweep with capacity exhausted. It carries no action and no delta for
  the issue. The summary shows `active` with the remainder custody, the `wait`
  action is armed on its deadline, and the issue is not in `waiting`.
- **Resumable suspended remainder.** No change: a `delivery_remainder` action
  for the next launch, a `resumed` delta, and one claim. Without a recorded
  worktree observation, the issue is still skipped as a round still owed.
- **Stall-bound expiry.** The remainder is persisted `failed` with
  `result_source: stalled`. The response carries no dispatch for it and
  charges no slot, and its summary shows `failed`.

## Test seams

These tests use S1, the `workflow-state` CLI run as a subprocess (`control`,
`finish`, `checkpoint-delivery`) with `HOME` set to a fixture declaration. They
live in the delivery workflow suite beside
`test_a_refused_remainder_launch_parks_under_host_capacity`, and build the
remainder the same way. Every free-slot case uses the `claude-code` route: the
`direct` route controls exactly one issue at `max_parallel` 1, so it can never
reach the resume lane with capacity. The first test also uses S3, the
`workflow-response` boundary (`artifact-budget validate-report`), following
`test_dispatching_control_response_passes_raw_workflow_response_validation`. No
test calls the admission step or `remainder_policy` directly (#150's "no other
seam") (D6).

| Test | Fixture | Assertion | At base |
|---|---|---|---|
| T1 live remainder, free slot | Remainder that control dispatched (`r1:2`, claimed), swept again at `max_parallel` 2 | Exit 0. The response passes `workflow-response`. The response bytes and the resulting ledger bytes both equal those of the same sweep at `max_parallel` 1, run from a copy of the same ledger | `KeyError: 'idle'` |
| T2 live remainder, slots short | A 4-slot declaration (the floor), so the controller plus the claimed `r1:2` fill it; `max_parallel` 2 | `admission.waiting == []`, and there is no `delivery_remainder` action | `waiting: [151]` |
| T3 stall-bound expiry | Denial checkpoint, then three control resumes with a no-progress checkpoint between each, which leaves `r1:4` `active` with `stalled_resumes` 2; then a sweep after its deadline | Exit 0. The remainder's `state`, `result_source` and `stalled_resumes` are `failed`, `stalled` and `3`, and there is no dispatch action | `KeyError: 'terminal'` |
| T4 suspended remainder, free slot | `human_gate` suspension, recorded worktree observed, `max_parallel` 2 | A `delivery_remainder` action for `r1:2` | Green: baseline coverage, kept because the acceptance criteria name a suspended remainder |

The recover lane gets no new test: with dispatch permitted it can only yield
`recover`. The admission step's membership test is pinned by existing suites.
With it removed from the prototype, three contract tests fail on
`KeyError: 'contract'`.

**Acceptance evidence.** T1 to T3 fail at base with the errors listed, and T1
to T4 pass after the change. `just agent-workflow-tests` and `just build` pass.
In a scratch prototype of this design, the 226 tests in the lifecycle,
admission and delivery suites passed. T1 reproduces the issue's instrumented
state: `operation=idle desired=resume custody_kind=remainder`, with capacity 1
spent on it. T3 reproduces the `r1:3` → `r1:4` sequence of the run in the
issue (D7).

## Out of scope

- **The `expired` delta for a reaped remainder.** The delta reports the source
  implementation attempt's state. A reap to suspended reports
  `(expired, failed, 151:r1:1)`, and a stall reports `151:1:1`. This is
  pre-existing and happens without any crash, so it is a candidate follow-up
  issue.
- **Whether `human_directed` should gate the resume of a `human_gate`
  remainder.** `remainder_policy` ignores `human_directed`, while the
  implementation lane honours it. That is a question about remainder semantics
  and is a candidate follow-up.
- **A remainder minted by `finish` holds no claim.** This is by design (#150
  D11).
- **Re-emitted recovers.** Their semantics are unchanged (#150 D21).
- **Moving `workflow-state` into `agent_tools`.** The legacy script meets that
  rule when its cluster moves.
- **Changing the action loop's error type.**

## Open questions

None remain. Phase 0's four questions are settled: Q1 by D3, Q2 by D2, Q3 by D4
and Q4 by D5.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Fix both halves: truthful remainder `desired` plus one admission step. The `desired` change is in scope because only control's lane selection reads it. Remainder operations, transitions and direct-owner behaviour stay out of scope | the-bar *Root causes*, *Defense in depth*; grep shows `desired` read only by `command_control`; the issue's Expected; Phase 0 puts remainder *semantics* out of scope, not its lane label | Admission guard alone (the issue's literal Expected): it fixes the crash, but a live remainder still reaches `slot_withheld` and is reported waiting (measured: `waiting: [151]`) |
| D2 | A live remainder is labelled `desired: idle` and a stall-bound failure `desired: terminal`, mirroring the implementation lane, so neither enters the resume lane. It gets no refusal gate, no `waiting` entry, no second plan, no slot and no claim | The implementation lane's `decision()` default; #150 D21 (`waiting` means withheld for slots); orchestrate-issues reports `waiting` as "queued for agent slots" | A liveness check in the resume lane: a second home for a fact the policy already decides, and the live set is only computed off the `direct` route |
| D3 | One nested admission step is the only place a result is queued and charged. It queues only `CONTROL_DISPATCH_KINDS`. All five dispatch lanes use it; recover charges only when its analysis changed. The per-lane `contract` skips are deleted as subsumed. Pre-checks, `observe` refusals and the uncharged `refuse` stay | the-bar *DRY*: #150 edited all five copies together. *Tests that can fail*: removing the membership test turns three existing contract tests red. The nested-helper idiom (`slot_withheld`, `refusal_gated`, `acquire`) | Separate guards at resume and recover: the recover guard is unreachable and so untested, and five copies stay free to drift |
| D4 | The stall-bound `KeyError: 'terminal'` is in scope as a third shape of the same defect. A suspended remainder is not a crashing shape, and gets only baseline coverage (T4) | Code reading: `idle` with dispatch permitted arises only for a live `active` remainder, and the stall reap returns `terminal` labelled `resume`. Scratch repro at `affa05e` | A separate guard for suspended remainders: measured, they resume as `delivery_remainder` at base |
| D5 | A live remainder with a free slot gets the byte-identical response a capacity-exhausted sweep gives. The resumable-suspended response is unchanged. A stall-bound remainder is persisted `failed` and gets no dispatch | The issue: "as they do when capacity is exhausted"; #133 D2 (same-sweep resume in the suspension lane) | A new summary field or action kind for live custody: an interface change no caller needs |
| D6 | Test seams are S1 plus S3 in the delivery workflow suite, on `claude-code`. The short-slot case uses a 4-slot fixture declaration, and the stall bound is reached through the CLI. No private-helper tests, no new recover test, and the action loop's closed map stays the fail-loud check | #150 test seams (S1, S3, D23, "no other seam"); `direct` controls one issue at `max_parallel` 1; the-bar *Fail loud*, *Tests that can fail* | Seeding the stall counters by editing the ledger (the CLI produces the real shape); changing the delta map's `KeyError` into a `WorkflowError` (an unreachable, untested branch) |
| D7 | Acceptance for "no longer crashes on the reproduction" is T1 (the instrumented state) plus T3 (the `r1:3` → `r1:4` sequence). The real run ledger is not rewound | Inspecting the real ledger: `r1` is `stopped` at schema 3, so the crashing custody no longer exists there | Rewinding a copy of the real ledger: it needs an eight-issue request rebuilt by hand, and gives no stronger evidence than T1 |
