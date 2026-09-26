# Control refuses one issue's resume, not the whole sweep, issue 194

## Problem

`workflow-state control` plans a whole orchestration sweep in one ledger
transaction. When one issue's resume cannot proceed because the caller
reports that issue's recorded worktree as `absent` or `mismatch`, the sweep
exits 2 with empty stdout and leaves the ledger unchanged:

```
workflow-state: resume control action requires a matching recorded worktree observation
```

Nothing else in the run can then be dispatched, resumed or finalized. The
adapter cannot stop it by telling the truth: its contract is to report every
recorded worktree's real state and never omit one. The run is stuck until the
worktree comes back, which after a delivery clean-up never happens. In nodocom
run `orch-1643-1655`, issue #1648's owner merged its PR, closed the issue and
removed the worktree. It could not record delivery (#192), so a suspended
delivery remainder was left behind. Every later sweep that reported that
worktree as `absent` was refused, and the remaining issues had to move to a new
run.

Refusing the issue's resume is correct: a resume runs in place on the recorded
worktree, and there is nothing to run it in. The defect is the blast radius.
One issue's truthful observation takes down every other issue's dispatch.

### Where the refusal comes from

The resume lane plans each `resume` issue with dispatch permitted and raises
whenever the plan answers `observe`. Three truthful observations produce that
answer or an equivalent raise:

| Custody | Observation | Base behaviour |
|---|---|---|
| Implementation attempt: handed off, auto-resumable suspended, or active with its owner unavailable | `absent` past Phase 0, or `mismatch` | Policy answers `observe`; the lane raises |
| Suspended delivery remainder whose next stage needs a matching worktree | `absent` | Policy answers `observe`; the lane raises |
| Suspended delivery remainder, any next stage | `mismatch` | The remainder worktree check raises `remainder policy refused` |

This design covers the first two rows, where the policy already answers
`observe`. The third row is the policy's own refusal, raised inside the shared
remainder check, and is out of scope with the retry and spawn lanes' refusals
of the same kind (D10).

An omitted observation is different. For a suspension, the lane already skips
the issue as a round still owed (#133 D9). For a handoff or an
owner-unavailable attempt, it is a caller-protocol error, because the adapter
contract never omits a recorded path.

## Solution

A truthful `absent` or `mismatch` observation that makes the policy answer
`observe` for a resume becomes a per-issue verdict. The policy itself is not
edited (D10):

1. **The resume lane records the refusal instead of raising.** When the
   observation it was given is present and is `absent` or `mismatch`, the lane
   records the refusal and plans the issue again with dispatch withheld. Only
   what a withheld dispatch would write is persisted. The lane admits nothing
   for the issue, charges nothing, and moves on to the next one (D1, D4).
2. **The summary reports it.** The issue's summary carries a `worktree_fact`
   requirement that names the worktree and the observed state (D3). The
   `workflow-response` validator accepts it under closed rules, including for
   an issue with no contract (D6).
3. **The dispatcher reports it.** orchestrate-issues' final report lists the
   issue as unable to resume, with that reason (D9, D12).

Every other issue in the sweep proceeds as though the refused issue had asked
for no dispatch.

## Decisions

### Policy: unchanged (D10)

Both custody lanes already answer `observe` with
`[{"kind": "recorded_worktree", "path": <custody worktree>}]`. The
implementation lane does so when the recorded worktree is not on the issue
branch, unless this is a Phase-0 pause observed absent (#133 D7). The
remainder lane does so when its next stage needs a matching worktree and the
worktree is absent. Neither lane, the remainder worktree check nor the direct
owner is edited.

### Resume lane: refuse per issue (D1, D4, D5)

The resume lane keeps every pre-check in its current order: the capacity
check, the suspended-and-unobserved skip, `refusal_gated`, then
`slot_withheld`. After those, it plans the issue with dispatch permitted. When
that plan answers `observe`, the lane runs one check, in a nested helper
beside `slot_withheld` and `refusal_gated`. Its code names say
"unresumable", never "refused" or "refusal", which already name refused
launches and `refusal_gated` (D12). All of these must hold:

- the plan's requirements are exactly one `recorded_worktree` requirement;
- the issue's worktree observation carries a non-null `recorded`;
- `recorded.path` equals the requirement's path;
- `recorded.state` is `absent` or `mismatch`.

If any of these fails, the lane raises the existing message. That keeps an
omitted observation for a handoff or an owner-unavailable attempt a loud
caller-protocol error. If all of them hold, the lane:

1. records the refused observation `{path, state}` for the issue;
2. calls `apply_policy(issue, False)`, which replaces the issue's `planned`
   entry with the dispatch-withheld verdict (`idle`);
3. continues to the next issue without calling `admit`.

What persists is exactly what a sweep with no slot for the issue would
persist. An attempt reaped this sweep is saved as its suspension and emits its
`expired` delta. A remainder reaped this sweep is saved likewise. Nothing else
about the issue changes. The implementation lane's dispatch-permitted
`observe` plan has `changed: false` even when it reaped, so keeping it in
`planned` would drop the reap. The remainder's already carries its reap, and
the withheld plan keeps it. Because the issue is now in `planned`, the retry
lane's expiry fallback (`issue not in planned`) does not plan it a third
time. Sweep-level
effects are unchanged, for example releasing an unavailable owner's claim.
Today the raise discards those effects; with the refusal they persist like any
other sweep's. The issue takes no `max_parallel` unit, no role-set claim and
no `waiting` entry. A suspended record arms no deadline, so a run left with
only refused issues renders `finalize`.

The refusal is decided at the same point as today's raise: only when a dispatch
would otherwise follow. A sweep that has no capacity or slot for the issue
never reaches the check. It reports the issue exactly as it does today, as
the paused custody, or as `waiting` when a slot withheld it (D5).

### Summary: the `worktree_fact` refusal (D3)

`control_summary` gains one optional input: the refused recorded observation.
When it is present, the wire projection appends this to the summary's
`requirements`:

```json
{"kind": "worktree_fact", "subject_id": "<recorded worktree path>",
 "reason_code": "recorded_worktree_absent", "detail_pointer": null}
```

`reason_code` is `recorded_worktree_absent` or `recorded_worktree_mismatch`,
matching the observed state. The kind and member set are the delivery
requirement union's reserved `worktree_fact` (#151), which nothing emits yet.
The list stays sorted and unique in canonical-bytes order, as the validator
requires. The other members come from the ledger as before. In particular,
`blocked_on` keeps the record's own value, such as `human_gate`, and `state`
is the paused or live custody state.

### Wire: the control response validator (D6)

For each control summary, the validator adds these checks on top of the
generic requirement shapes:

- There is at most one `worktree_fact`. Its `reason_code` is one of the two
  codes above, its `detail_pointer` is null, and its `subject_id` equals the
  summary's `worktree` whenever that is non-null (D11).
- A summary with a null `contract_digest` still admits only `[]` or
  `[delivery_contract_required]` once that refusal is removed. A contractless
  refused summary is therefore `[worktree_fact]`.
- No action names an issue whose summary carries the refusal. This mirrors the
  existing rules for contractless and `waiting` issues.

## Test seams

The tests use the seams #190 and #150 already use. S1 is the `workflow-state`
CLI run as a subprocess (`control`, `spawn`, `progress`, `suspend`, `finish`,
`checkpoint-delivery`). S3 is the `workflow-response` boundary. Multi-issue
cases run on the `claude-code` route with a fixture declaration, because the
`direct` route controls one issue at `max_parallel` 1. No private-function
seam is added or changed (D8).

| Test | Fixture | Assertion | At base |
|---|---|---|---|
| T1 acceptance | Contracted attempt suspended past Phase 0, recorded worktree observed `absent`, next to a spawnable issue; `max_parallel` 2 | Exit 0; passes `workflow-response`; one `spawn` for the other issue; no action or delta for the first; its summary carries `recorded_worktree_absent` naming its worktree; its ledger entry is unchanged; it holds no claim | Exit 2, the `matching recorded worktree` message |
| T2 mismatch | T1 with `mismatch` | As T1, with `recorded_worktree_mismatch` | Exit 2 |
| T3 remainder | `remainder_sweeps` `human_gate` remainder whose next stage needs a matching worktree, observed `absent` | Exit 0; no `delivery_remainder` action; summary carries `recorded_worktree_absent`; remainder record unchanged | Exit 2, the `matching recorded worktree` message |
| T4 reap persists | Handoff past Phase 0, swept after its deadline with `absent` | Exit 0; an `expired` delta; attempt persisted `suspended`; summary refusal; no dispatch | Exit 2, nothing written |
| T5 wire | Control-response fixtures | The refusal is accepted on contracted and contractless summaries, and rejected for an unknown code, a non-null pointer, a subject other than a non-null summary worktree, two refusals, or an action for the issue | Contractless acceptance fails |

These existing tests are changed on purpose:

- **The owner-unavailable absent/mismatch test.** Without a candidate, each
  subtest now asserts the per-issue refusal. The candidate subtests stay
  atomic refusals, now caught by the current-action check. They keep proving
  that a candidate never relocates a resume.
- **The Phase-1 orchestrated handoff observed `absent`.** It now asserts the
  per-issue refusal on a contractless summary and passes `workflow-response`.
- **The unobserved-handoff test.** It is kept as it is. An omitted observation
  is a caller-protocol error.

**Acceptance evidence.** T1 to T4 fail at base as listed, T5's contractless
acceptance fails at base, and all of them pass after the change.
`just agent-workflow-tests` and `just build` pass.

## Out of scope

- **Closing out a delivered issue whose ledger cannot fold the delivery**
  (the issue's second Expected item). Three mechanisms exist, and none of them
  closes a stranded remainder:
  - the tracker-halt terminal parks only suspended implementation attempts,
    because the remainder lane ignores `tracker_halted`;
  - the forge-merged reconcile acts only on implementation attempts, because
    the remainder plan returns first;
  - the D21 recovery proof only allocates remainder two.

  After this change such an issue no longer blocks its neighbours, but it
  stays refused on every sweep until it is closed out. That is #192 part 2's
  remainder stranding, the named follow-up.
- **A suspended attempt whose worktree is gone has no exit.** This dead end
  predates this issue (#133 Out of scope). This change turns its whole-sweep
  failure into a per-issue report, but the issue still cannot resume. Direct
  owners still re-ask for the recorded worktree.
- **The shared policy's own truthful-mismatch refusals**: the retry and
  spawn lanes' raises ("refuses at once", D25/D44) and the remainder worktree
  check's `mismatch` raise (D10). They still take down the whole sweep. Making
  them per-issue means turning a shared-policy raise into a verdict, which
  changes direct owners too. That is a follow-up, and it would reuse this
  design's `worktree_fact` channel.
- **Caller-protocol raises.** An omitted handoff observation, a candidate for
  an issue that already has attempts, and a recorded path that differs from
  the ledger all stay whole-sweep errors.
- **Reporting a refusal on a sweep with no capacity for the issue** (D5).
- **Moving `workflow-state` into `agent_tools`.** The legacy script meets that
  rule when its cluster moves.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Scope: the resume lane's refusal on a truthful `absent`/`mismatch` recorded observation becomes a per-issue verdict for implementation and remainder custody. Omitted-observation, current-action, path-mismatch and retry/spawn raises stay whole-sweep | The issue's Expected and Acceptance; Phase 0's tight default (same blast radius *and* truthful trigger); orchestrate-issues §2 forbids omitting a recorded path, so the adapter cannot avoid the trigger | Making every control raise per-issue: it would hide caller-protocol bugs that the-bar *Fail loud* keeps loud, and would widen into the shared policy's D25/D44 refusals |
| D2 | The remainder worktree check answers a truthful `mismatch` with the `recorded_worktree` requirement for every stage requirement, instead of raising. A mismatch still never launches, and a direct remainder mismatch now answers `observe` like a direct implementation mismatch | Same blast radius and truthful trigger as D1, reached through a raise inside the helper; the-bar *DRY* and *Root causes*: one shape for "this worktree cannot serve the resume", not a catch in control | Catching the helper's `ValueError` in control (a catch that mutes an error); branching on `source_kind` to keep direct's raise (a second rule for one fact); leaving remainder mismatch out (the sweep still dies on it) |
| D3 | The summary reports the refusal as one `worktree_fact` requirement: `subject_id` is the recorded path, `reason_code` is `recorded_worktree_absent` or `recorded_worktree_mismatch`, `detail_pointer` is null. The wire projection renders it from the refused observation that control passes in. `blocked_on` and `state` stay the ledger's | `worktree_fact` is the reserved member of the #151 delivery requirement union; the-bar *Truthful terminal states*; summary members mirror the ledger record | Re-emitting `recorded_worktree` (it says an observation is owed when one was given, so the adapter would re-observe forever); overloading `blocked_on` (a summary value that disagrees with the ledger); a new summary member (an interface change no caller needs) |
| D4 | A refused issue is planned again with dispatch withheld, so the sweep persists exactly what a withheld dispatch would, including this sweep's reap and its `expired` delta. It gets no admission, capacity, claim or `waiting` entry | The implementation lane's dispatch-permitted `observe` plan reports `changed: false` even after a reap (code reading); #190 D8 (a non-dispatch verdict stays in `planned` and persists through it); #133 D1 (one reaper) | Leaving the ledger byte-identical (the reap is lost and the summary shows an expired attempt still `active`); keeping the `observe` plan in `planned` (same loss, and it blocks the expiry fallback) |
| D5 | The refusal is decided where today's raise sits, after the capacity, refusal-gate and slot pre-checks. A sweep without capacity or a slot for the issue reports it as it does today | the-bar *YAGNI*; #190 D31 (a contract is asked for only where a dispatch would follow); reordering would run the handoff-path check and the dispatch-permitted plan on sweeps that cannot dispatch | Checking the worktree before the gates: a second plan and replan per gated issue, and new raises on sweeps that dispatch nothing |
| D6 | The control-response validator admits the refusal under closed rules: at most one, the two reason codes, a null pointer, the subject equal to the summary's worktree, a custody state, and no action for the issue. The contractless rule holds once the refusal is removed | the-bar *Defense in depth*; the existing `missing_contracts` and `waiting` no-action rules; #151's "no contract yields only the exact contract requirement" rule is kept apart from the refusal | Accepting any `worktree_fact` (unchecked vocabulary); rejecting it for a contractless summary (a legacy `spawn`-created attempt would then fail the boundary) |
| D7 | The issue's second Expected item, closing out a delivered issue whose ledger cannot fold the delivery, is out of scope. The follow-up is #192 part 2 | Code reading: the tracker-halt terminal and the forge-merged reconcile cover implementation attempts only, and the D21 recovery allocates only remainder two; Phase 0 default | A synthetic close-out terminal here: a new lifecycle transition with its own design questions, and the stranding it cures is #192's |
| D8 | Tests: S1 plus S3 on the `claude-code` route (T1 to T5). The owner-unavailable test is split into per-issue subtests and candidate-carrying atomic subtests. The Phase-1 handoff test and the `remainder_policy` mismatch case flip. The unobserved-handoff test is kept | #190 D6 and #150's seams; the-bar *Tests that can fail*: T4 fails if the observe plan is kept, and T5 fails if a closed rule is dropped | A new private test of the refusal helper (no seam beyond the CLI); deleting the candidate subtests (the no-relocation proof would go unpinned) |
| D9 | Prose: one orchestrate-issues §5 sentence. A summary whose `worktree_fact` reads `recorded_worktree_absent` or `recorded_worktree_mismatch` is reported as refused for that reason, never as progressing. The Codex stub, from-issue and ship-issue are unchanged | Only the dispatcher reads control summaries; the Codex stub only relays `host-route`; owners never see summaries | No prose (the final report would show a paused issue with no reason); a §2 edit (its "mismatch refuses" wording stays true) |
| D10 | Grill, reverses D2: the remainder worktree check keeps raising on a truthful `mismatch`, and no policy code is edited. The remainder `mismatch` joins the retry and spawn lanes' shared-policy refusals as a named follow-up; the `remainder_policy` mismatch test stays as it is | Phase 0 puts direct-owner behaviour out of scope, and D2 changed it: a direct remainder mismatch would go from a loud exit 2 to an `observe` that from-issue's resend loop answers with the same fact. That raise is the same kind as the D25/D44 refusals this spec already leaves out | D2 as written (a direct-owner change and a possible unbounded direct loop); branching on `source_kind` (two rules for one fact) |
| D11 | Grill, refines D6: the validator matches `subject_id` to the summary's `worktree` only when that is non-null, and has no custody-state rule | Code reading: a summary names no custody once the delivery is complete, while the implementation lane can still plan a resume for that issue. A strict rule would then reject control's own truthful output at the dispatcher's boundary, after the ledger was written | Keeping the strict rules (the producer's output fails its own boundary); dropping the subject check altogether (loses the cheap path cross-check) |
| D12 | Grill: code names say "unresumable", never "refused"/"refusal", and the orchestrate-issues sentence says "cannot resume" rather than "refused" | Existing vocabulary: control's `refused` holds refused launches, `refusal_gated` gates `host_capacity`, and `refuse`/`retry_refused` is the third-attempt verdict; the-bar *Maintainability over cleverness* (name for intent) | `refused`/`refusal` names (they collide with three existing meanings in one function) |
| D13 | Plan: the projection renders the `worktree_fact` from the observation control passes as `unresumable`, and `DeliveryRuntime.control_summary` re-sorts that summary's requirements by the delivery model's `canonical_bytes` only when one was passed | agent-helpers rule 4 (one canonical-JSON home) and the projection's no-model boundary; the validator's canonical-bytes order; summaries without the fact stay byte-identical | A JSON sort key inside the projection (a second canonical form); appending unsorted (right only while every other requirement happens to sort first); sorting every summary (re-orders output this issue does not own) |
| D14 | Plan, refines D8: T1, T2, T4 and the two revisited tests run on `LifecycleHarness`, whose spawn goes through control with a contract. The Phase-1 handoff's refused summary is therefore contracted, not contractless as Test seams says. A harness helper passes each case's bytes through S3, and T5 alone pins contractless acceptance | Planning probe on `60f3ebf`: that summary carries a `contract_digest`; D8's seams; the-bar *Tests that can fail* | A migrated legacy ledger to reach a contractless CLI case (a new fixture for the one rule T5 already pins at the boundary) |
