# Issue #281 — Clean deadline suspension at task boundaries

Slice 3 of the [light-lane budgets design](2026-10-06-light-lane-budgets-design.md),
which settles the rule itself (its D12) and the new value's meaning. This
document settles how slice 3 lands. It does not reopen D12.

## Problem

An owner running `sdd` learns that its attempt budget is spent in only one
way. The lazy reaper reads the clock against the attempt's `deadline_at`, and
the next `workflow-state progress` call is refused. That usually lands in the
middle of a task, after an implementer has been dispatched and while it still
holds a registered worker. The owner then exits with the task half done. The
ledger records the reaper's `suspended(unknown)`, which cannot be told apart
from an owner that died. Re-entry must then rebuild a task whose
implementer's commits may or may not have landed. Budget tuning (slice 5)
also cannot separate an owner that ran out of time cleanly from one that was
lost.

## Solution

At each task boundary, the owner compares the time left before the attempt's
`deadline_at` with what the next task is likely to need. When the time left
is short, the owner stops cleanly, in this order:

1. It releases its workers.
2. It records progress with `workflow-state mark-progress`.
3. It fences its launch with `workflow-state check-launch`, because
   `suspend` does not check the caller's launch; a launch that is no longer
   current prints the re-entry line and stops without suspending (D11).
4. It suspends with a new owner-writable cause, `blocked_on=deadline`.

`deadline` is auto-resumable like `usage_limit` or `transport`: any `control`
sweep and any direct re-entry resume the suspension in place, on the same
worktree, with a fresh window. Then `sdd`'s `progress.md` picks up at the
next task.

## Decisions

**Ledger value.** `workflow-state` adds `deadline` to the closed
`blocked_on` set and to the auto-resumable set. Because the owner set is
derived as "all values except `unknown` and `host_capacity`", `suspend
--blocked-on deadline` is accepted with no other change. `unknown` stays
reaper-only, and `host_capacity` stays control-only. Suspending, the
`stalled_resumes` count and the progress-marker reset are unchanged. The ledger
schema does not move (D2).

**Live-worker refusal.** `suspend` already runs through the owner-exit fence
from #222, which refuses with `live workers: <ids>` and writes nothing.
`deadline` gets that behavior for free. Slice 3 adds only a test that proves
it.

**Resume.** The acquisition predicate already resumes any suspension whose
cause is in the auto-resumable set, or any suspension at all when the request
is human-directed. Adding `deadline` to that set makes a `--label` or
`--milestone` sweep resume it, and a direct re-entry already resumes it. The
resume re-bases `deadline_at` exactly as it does for every other
suspension, including #280's lane-aware re-base. There is no gate like the
one on `host_capacity`.

**Wire contract.** The delivery model's closed `suspended` response admits
`deadline`. Without that change, `artifact-budget validate-report --boundary
workflow-response` rejects the owner's own suspend reply. The closed
`blocked_on` set on the delivery `checkpoint` response does not change, because
the rule never runs at a delivery checkpoint (D3). Control summaries already
carry `blocked_on` as an open string.

**`sdd` headroom rule (D12, restated where it runs).** Under a lifecycle
identity that carries a `deadline_at`, the controller runs the check at every
task boundary. A task boundary is the moment before it dispatches a plan task,
and the moment after the last task's `complete` line, before the final review.
The rule:

- `remaining` is `deadline_at` minus the current UTC time.
- `longest` is the largest wall time of any task this session completed
  (D4).
- When `remaining < max(15 minutes, longest)`, the controller:
  1. releases every worker this launch still has registered. Normally there
     are none, because each worker is released when it returns. A worker
     still live is stopped and released `--event stopped` by from-issue's
     **Writing workers** route;
  2. runs `workflow-state mark-progress`; a refusal does not stop these
     steps;
  3. runs `workflow-state check-launch`. On `current: false` or any helper
     failure it writes nothing more, prints `/from-issue <num> --auto` and
     stops, as from-issue's superseded route says, without suspending: a
     successor launch may already own the attempt, and `suspend` would park
     it (D11);
  4. on `current: true`, follows from-issue's suspension procedure with
     `blocked_on=deadline`.

The suspension procedure's own release and self-reap steps still run, and
they are no-ops here. The procedure's `kind: terminal` branch, at the
anti-zombie bound, is handled exactly as the procedure already says. A
refusal because the attempt is no longer active means the reaper got there
first. The controller handles it as from-issue's existing expired-deadline
route: it prints the re-entry line and stops. It never retries.

**`deadline_at` reaches `sdd`.** from-issue's Phase 6 already hands `sdd`
the lifecycle identity (`ledger_repo_root`, `run_id`, `action_id`). It now
also hands over the `deadline_at` the owner holds. That value is the one the
owner adopted from its `kind: owner` envelope, or the one from a later
`declare-lane` reply, if any. Without a `deadline_at`, the rule does not
apply. That covers ledger-free runs and an `sdd` invoked by hand.

**from-issue suspension procedure.** The procedure's list of owner values
gains `deadline`, with a clause saying that only `sdd`'s headroom rule writes
it. The expired-deadline paragraph is not changed: it remains the fallback
when the reaper wins the race.

**orchestrate-issues.** No change. Its §5 lists only the causes a sweep
does not resume (`human_gate`, `external`, `agent_dispatch`), and `deadline`
is not one of them. Its re-entry line is the run's own re-invocation, like
any other auto-resumable cause.

**Instruction growth.** The new `sdd` and from-issue prose is small, but it
may still exceed the instruction-load ceilings. The Instruction Budget gate
(`just agent-instruction-budget`, a required check on `main`) decides whether
it does. Any raise is recorded in the affected profile's `note`, citing
#155 D10, in the same commit.

## Test seams

These are all existing seams that run under `just agent-workflow-tests`.

- **`workflow-state` command tests** (`test_workflow_state.py`, following
  the `agent_dispatch` tests):
  - `suspend --blocked-on deadline` parks an active attempt as
    `suspended(deadline)` without spending it, and the reply is a v2
    `suspended` reply with `blocked_on: deadline`.
  - The same `suspend` is refused with `live workers: …` and an unchanged
    ledger while a registered worker of the launch is live.
  - `control` with a non-human-directed (label) request resumes a `deadline`
    suspension on the same attempt and worktree.
  - Direct re-entry resumes it the same way.
  - Owner-path writes of `unknown` stay refused.
- **Delivery-model wire test** (`test_delivery_model.py`): the closed
  `suspended` reply accepts `blocked_on: deadline` (extends the existing
  cause loop).
- **Skill contract tests** (`test_workflow_skill_contracts.py`), under the
  agent-helpers standard rule 6:
  - `sdd`'s `### Lifecycle workers` section carries a `workflow-state
    release-worker` argv, then a `workflow-state mark-progress` argv, then a
    `workflow-state check-launch` argv with its `current: false` and
    `current: true` keys, then a suspension naming `deadline`, in that order, inside the paragraph that
    states the headroom rule.
  - The from-issue suspension procedure admits `` `deadline` `` (extends
    `test_suspension_procedure_admits_agent_dispatch`).

  The 15-minute and longest-task wording is English, and no new test pins it
  (D5).

## Out of scope

- Lane triage (#279), lane declaration (#280, merged), and the active light
  route with its escalation triggers (#282). That includes how a light-lane
  owner reacts to its light deadline, which D8 of the parent design routes to
  escalation and #282 owns. This rule applies in every lane, and #282 may run
  its escalation check first at the same boundary.
- Headroom checks outside `sdd` task boundaries: Phases 0–5, from-issue's
  mechanical route, Phase 7 delivery and ship checkpoints.
- Any new helper verb, persisted task timing, or ledger schema change.
- Changes to the reaper, to expiry, or to anti-zombie accounting.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The headroom rule runs only at `sdd` task boundaries: before each task dispatch, and after the last task before the final review. from-issue only lists the value and hands over `deadline_at` | Parent D12 scopes it to task boundaries; the issue scope; YAGNI | Checks in every phase or at ship checkpoints: no task-duration signal exists there, and the scope would grow beyond slice 3 |
| D2 | `deadline` joins the closed and auto-resumable sets with no ledger schema bump | Precedent: `agent_dispatch` (37b829a5) added a value without a bump; existing ledgers stay valid | Bump to schema 8: no migration is needed, because no stored value changes |
| D3 | Only the `suspended` wire reply admits `deadline`; the delivery `checkpoint` response's closed set is unchanged | D1: the rule never runs at a delivery checkpoint; the closed-shape discipline | Widen every `blocked_on` set: this would admit a value that no writer can produce there |
| D4 | The owner measures time itself. `remaining` is its held `deadline_at` minus `date -u`. `longest` is the maximum wall time, from the dispatch instant to the `complete` line, of tasks completed in this session, kept in context. An unknown `longest` counts as 0, so the 15-minute floor governs | The issue asks for no new helper unless needed; "this launch" is per-session, and a resume starts a fresh window | A helper verb or timings persisted in `progress.md`: new surface for a heuristic, and it would carry timings from earlier launches |
| D5 | The contract test pins the ordered argv sequence (release-worker → mark-progress → suspend `deadline`). It does not pin the headroom formula's prose | agent-helpers standard rule 6 (no new English-phrase pins) | Pin the "max(15 minutes, …)" sentence: this violates rule 6 |
| D6 | An owner whose `mark-progress` or `suspend` is refused because the attempt is no longer active follows from-issue's existing expired-deadline route, and never retries | The existing from-issue route for a reaper that wins the race; the-bar's "Truthful terminal states" | A new recovery path: it would duplicate the existing route |
| D7 | orchestrate-issues is unchanged | §5 lists only non-sweep-resumable causes, and `deadline` is auto-resumable | Add `deadline` to §5: that would misreport it as needing per-issue re-entry |
| D8 | The new skill prose is not offset by trimming other text. Each breached instruction-load ceiling (hot, per profile and host, and the corpus ceiling) is raised to its exact measured bytes in the commit that grows it, with a `Ceiling raised for #281: … (#155 D10)` note sentence and an `instruction-budget-raise needed: …` commit-body line. The `instruction-budget-raise` label stays a human authorization that ship requests; no agent applies it | #155 D10; the #309 precedent (ba40a826); headroom at the base is 81 B (from-issue-controller) and 0 B (orchestrated-issue-owner, implementation-owner) | Cutting unrelated skill prose to net zero: scope creep into text this issue does not own |
| D9 | The `sdd` contract test finds the headroom paragraph by the ledger value `` `blocked_on=deadline` `` (exactly one blank-line-delimited paragraph of `### Lifecycle workers` carries it) and pins, inside it, the `release-worker` argv prefix, then the `mark-progress` argv, then that value. The from-issue Phase-6 test gains the `` `deadline_at` `` key between the identity and `register-worker`. Refines D5 | agent-helpers rule 6 admits `workflow-state` argv and lifecycle JSON keys | A bold label such as `**Deadline headroom.**` as the anchor: an English phrase pin |
| D10 | from-issue's Phase 6 hands `sdd` the `deadline_at` the owner currently holds (a later `declare-lane` reply's value supersedes the acquired one), and sdd's **Continuous execution** stop list names the deadline headroom rule | Phase-5 plan review (Codex): the acquired value goes stale after `declare-lane` re-bases it, and the opening directive's exclusive stop list would contradict the new rule | Pass the acquisition-time value: can miss the window or suspend early. Leave the stop list alone: two conflicting instructions |
| D11 | Before the deadline suspension, the owner fences its launch with `workflow-state check-launch`. On `current: false` or any helper failure it writes nothing more, prints `/from-issue <num> --auto` and stops (from-issue's superseded route); only on `current: true` does it suspend with `blocked_on=deadline`. A refused `mark-progress` is tolerated only while the launch stays current. The contract test pins the `check-launch` argv between the `mark-progress` argv and the value. Extends D5 and D9 | Final correctness review C-001: `suspend` selects only the issue and attempt and checks that the attempt is active, not the caller's launch, so a superseded owner whose `mark-progress` was refused (`superseded_launch`) could park its successor's live attempt | Add a launch fence inside `suspend`: new helper behaviour, out of scope under D2 and D4 |
