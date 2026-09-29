# Shared transaction history construction

Issue: [#230](https://github.com/fagenorn/nix-config/issues/230). Base:
`6d7a0b3a47d5a480e1540ce1931dd012f5f1ad0b` (`origin/main`, including #229).
Scope: two existing production modules and focused store tests, approximately
3–5 changed product/test files. Risk is full because every lifecycle writer is
touched. Decisions are autonomous within the issue's existing scope.

## Problem

Transaction operations currently compose events and separately assign their
derived document fields. Ordinary append, acquisition, release/quiesce, reap,
and late owner results each maintain some combination of `state`,
`parked_from`, `custody`, `revision`, and event sequence numbers. Loading then
derives the same projections independently. A lifecycle rule can therefore
change in validation without changing every writer, or vice versa.

The intent is one authoritative event-to-projection implementation, retaining
the existing transaction behavior and the store's ownership of effects.

## Solution

Extract the existing validating history walk into one pure history function
that returns the four derived document fields. A pure candidate constructor
accepts a validated prior document, an ordered list of event field dictionaries,
and one timestamp; it returns a complete, detached candidate document. It owns
sequence numbers, timestamp envelopes, and projection installation. Both this
constructor and stored-document validation call the same history walk.

The store remains the only public operation surface. Its recipes explicitly
select the events, retain their current admission checks, and persist complete
candidates with the existing lock and lease ordering. Creation already has one
construction site and remains unchanged.

### Requirements

- All five mutation families obtain their complete candidate from the shared
  constructor. None independently assigns any of the four derived fields or
  numbers appended events.
- Keep `transaction-state/v5`, every public method and snapshot contract,
  event order/content/timestamps, refusal classes and precedence, and no-op
  behavior. Preserve the external-result capture introduced by #229.
- Construction and validation use exactly the same transition, parking,
  custody, and revision rules. Preserve all action, proof, recovery, envelope,
  pairing, terminal and fence checks in their existing order.
- Loading compares stored projections and rejects tampering; it never replaces
  them with the computed values or saves a repaired document.
- Constructing a candidate performs one existing full history walk. Do not
  construct through one fold and then call full validation for another walk.
  Existing admission validation of the stored prior remains necessary.
- Construction and the shared walk perform no filesystem, lock, clock, index
  or lease-authority access. The existing validator retains its index callback;
  lease liveness and all persistence remain store judgments.

### Options considered

1. **Shared validating walk plus complete-document constructor — selected.**
   Extract the existing walk and its exact refusal ordering. Construction
   installs its result; loading compares against it. This adds a small internal
   interface and removes knowledge from every writer without a new subsystem.
2. **Small projection-only reducer followed by existing validation — rejected.**
   It either duplicates the event rules or performs an extra complete history
   pass. A shorter constructor would hide the same drift the issue removes.
3. **Incremental fold state returned by load and threaded through operations —
   rejected.** It might reduce work further, but adds cached action/proof/custody
   state and freshness obligations across operations. The issue requires reuse
   of the current walk, not a new incremental event engine.

## Decisions

### Internal construction interface

The history module exposes one constructor to the core module, conceptually
`append_events(prior, event_fields, *, at) -> dict`. The name is internal;
`TransactionStore` remains the public interface. The prior comes from the
store's existing validated load under its transaction lock. Recipes supply
event-specific fields without `seq` or `at`; the constructor assigns contiguous
sequence numbers after the existing history and stamps every appended event
with the passed timestamp. Existing created events retain their envelopes.

The constructor copies the prior and appended event data so neither input is
mutated or retained as a writable alias. It extends the history, obtains the
projection from the shared validating walk, and installs `state`,
`parked_from`, `custody`, and `revision` in one place. Revision is the complete
event count. Callers receive a fully checked event history and its projections,
never a partial document they must finish.

The constructor relies on the already validated prior for immutable document
metadata and the creation-key index binding. Appending cannot modify either.
It does not repeat those admission checks or perform index I/O; it does validate
the resulting event history, including the new events. The existing full
stored-document validator remains the path for load and creation. This is an
internal trusted-prior contract, not a public way to admit unchecked documents.

### One walk, two uses

Preserve the existing validator's document/schema/identity, plan, creation-key
index, subject, and concurrency-key checks before the history walk. Extract
the event-list and created-event checks, chronological dispatch and fold,
trailing pairing check, and terminal-custody check into the shared pure walk.
It returns only the four projections needed by these callers; auxiliary
custody/action/proof fold state remains local.

The stored-document validator then compares in the existing order: `state`,
`parked_from`, `custody`, `revision`, preserving exact type checks (including
rejecting boolean revisions) and named refusal messages. The constructor
installs that result instead. No mode flag silently turns validation into
repair, and no second independently maintained transition or custody reducer
survives. Existing history-dependent rule functions continue to receive the
same preceding events and current folded state/fence at the same point.

### Explicit operation recipes

| Mutation family | Ordered recipe and store responsibility |
|---|---|
| Ordinary append | Existing operation events; when the recipe enters a terminal under held custody, append `lease_released` with reason `terminal` last. Determine this from the explicit terminal transition, without maintaining a document-state projection. |
| Acquisition | If held custody lapsed, `lease_lapse_detected` first; then `lease_acquired` or `lease_reacquired` with unchanged prior-span fields and expired/released reason. The store checks liveness and obtains the next fence before constructing. |
| Release/quiesce | One `lease_released` carrying the current fence and existing released/quiesced reason. Renewal's quiesce decision stays in the store. |
| Reap | `lease_lapse_detected`, then `stop_synthesized`, then the existing transition to `attention_required` only outside a parking. The history recipe returns event fields, not a separately projected document. |
| Late owner result | One `owner_result` with existing current/stale classification and supersedes calculation. The store passes its lapsed judgment; the event helper supplies no sequence number or timestamp. |

Reacquisition can inspect prior events and the newly selected lapse event to
choose the opening recipe; it cannot manually assign custody or revision.
Reaping an already parked transaction preserves its original `parked_from`.
Owner results do not restore custody, alter lifecycle state, remove a synthesized
stop, or grant authority. Event payload fields such as owner-result `custody`
are distinct from the top-level derived custody projection.

### Effects and compatibility

Keep transaction-lock then lease-lock order and their current acquisition
points. Acquisition constructs a valid candidate, holds the leases, then saves
state. Voluntary/quiesced and terminal release save state before clearing the
previous fence under the lease lock. Reap and late result save only state;
neither clears expired or successor lease records. Ordinary non-releasing
append saves only state. Renewal without quiescence still appends nothing.

Admission checks remain in their current store locations: malformed arguments,
validated prior, terminal refusal, custody/path/fence and operation-specific
checks retain their current precedence. Moving construction must not reorder
lease availability checks or move any durable write before candidate checking.
No-op reaps and unchanged renewals do not invoke construction just to rewrite
identical state. External callbacks still use the #229 result-intake helper
before validation and retention; document copying is not a substitute for it.

## Test seams

Keep the accepted seams from [#205 D23](2026-09-28-issue-205-fenced-custody-design.md#decision-ledger)
and [#208 D16](2026-09-28-issue-208-recovery-plans-design.md#decision-ledger):
public store operations under a temporary root with a fake clock, documented
state/lease bytes and lease inspection; the asserted store sweep; and the
existing source neutrality check. Do not add direct constructor/fold tests or
mock assertions that an internal helper was called.

Use independently authored event payloads, event order and expected projection
values. Dynamic identifiers/fences may be captured from public results, but no
expected projection or history is generated by production construction or
folding code. For each changed writer, assert the returned snapshot, serialized
document and a fresh load agree with those expectations.

Coverage must demonstrate:

1. Ordinary transition, parking and resume, plus non-transition append preserving
   projections; a terminal recipe writes its transition before terminal release.
2. First acquisition, acquisition after voluntary release, and acquisition over
   unreaped lapse; correct contiguous sequences and newly held custody.
3. Voluntary release and parked-window quiesce clear custody while preserving
   lifecycle/parking projections, with expected lease records afterward.
4. Reap both outside and inside a parking; synthesized stop adjacency, original
   parking origin, and unchanged successor lease records. A repeated reap is
   byte-identical.
5. Current and stale authentic owner results, including after a synthesized stop;
   correct supersedes and unchanged lifecycle/custody/lease projections.
6. Hand-tampered state, parking origin, custody, revision and event sequence are
   refused by load without rewriting bytes. Competing faults retain the current
   order: document checks before event checks, event checks before projection
   checks, and state before parking before custody before revision.

Retain existing refused-without-write, lock contention, lease ordering and
external-result ownership regressions. Add assertions to existing appropriate
store scenarios where sufficient; avoid duplicating whole workflows. Run the
focused transaction suite and the resolved `agent-workflow-tests` and
`nix-build` verification commands. Baseline evidence supplied at entry: 281
focused tests and `nix-build` passed; the full workflow suite was still running.
This design phase changes no production code and claims no post-change test run.

Review the source as well as runtime behavior: no independent derived-field
assignment or appended-event numbering may remain in the five recipes. Check
the call graph for one candidate history walk; use inspection rather than a
helper call-count test or a benchmark project.

## Grill disposition

The review frontier is closed. Against #205 D8/D11/D33/D34 and #208 D17/D27,
the shared walk keeps history rules in their established module while leaving
one store and crash ordering intact. Concrete challenges resolved in scope:
tampered projections still fail through strict load validation; terminal
release is included before the shared walk enforces terminal custody; parked
reap does not replace its parking origin; takeover cannot clear a successor's
lease; and late-result construction cannot undo #229's earlier ownership
capture. The validated-prior requirement prevents constructor use as a repair
path. There are no unanswered design questions or documentation-map writes.

## Out of scope

- Creation redesign, schema migration, public methods or new transaction modules.
- Changed transitions, event vocabulary, refusal policy, snapshot semantics,
  result-intake ownership, clock/lease rules or persistence protocol.
- Incremental caching, event sourcing framework, generic persistence coordinator,
  benchmarks, consumer cutover, or new context maps/glossaries/ADRs.
- Broad rearrangement of action, proof or recovery rules and unrelated cleanup.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Use one pure complete-document constructor and extract the existing validating history walk as the sole source of all four projections. | #230 shared rules and no extra full-history pass; #205 D11/D33; the-bar DRY. | A separate reducer plus validator duplicates rules or walks; incremental fold caching expands the issue. |
| D2 | Construction takes a validated prior and event fields without envelopes; store load checks metadata/index first, construction validates the resulting history once, and load strictly compares projections. | #230 purity and refusal compatibility; existing validated-load admission and validator order; the-bar defense in depth. | Calling full validation after projection creates a second pass; normalizing stored projections conceals tampering; moving index I/O into history breaks purity. |
| D3 | Keep terminal release, acquisition, reap and owner-result event selection explicit while centralizing numbering and projection installation. | #230 explicit recipes; #205 D8/D34; #208 D17; landed #229 ownership D4. | A generic operation dispatcher hides differing admission/effect order; recipe-owned projection assignments preserve drift. |
| D4 | Prove behavior at the existing store/layout seams with independently authored expectations and source inspection for the structural guarantee. | #205 D23; #208 D16; #230 acceptance; the-bar tests that can fail. | Constructor unit tests or constructor-generated expectations can validate the same bug twice; helper call-count tests bind verification to implementation. |
