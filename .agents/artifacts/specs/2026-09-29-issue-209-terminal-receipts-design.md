# Transaction core 6/6: terminal receipts, the failed disposition and the full-sweep gate

Design for [#209](https://github.com/fagenorn/nix-config/issues/209), slice 6 of 6 of
[#123](https://github.com/fagenorn/nix-config/issues/123), 2026-09-29, against main `93bf5fd`.
Written in autonomous mode: every choice below is an agent judgment inside the issue's
delegated scope, recorded in the decision ledger, not a human answer.

## Problem

Slices 1–5 (#204–#208) give a transaction a closed lifecycle, fenced custody, a safe way to
cause effects, a proof judge and a way back. Nothing proves what a terminal says:

- a transaction enters `succeeded`, `abandoned` or `rolled_back` with nothing more than a
  `transitioned` event. No permanent, content-addressed receipt survives the ledger, which
  #88 and #72 require before any terminal and before the ledger may ever be collected;
- any caller may `advance` into `failed`, from `attention_required` or `recovering`, citing
  nothing. #88 and #83 allow `failed` only on known final state plus a positive disposition,
  and #94 adds exactly one second form: a human-asserted ground that the subject became
  permanently unobservable, carrying the `effects_unobservable` qualifier, residue and a
  standing hazard;
- the #205 reaper already keeps a late owner result beside the stop it synthesized
  (`owner_result.supersedes`). No terminal record carries both, so once the ledger goes the
  supersession is lost;
- each unit's observed postcondition exists only as a line in a mutable ledger, never as a
  sealed fact;
- the sweep lacks `unknown_external_state`, the prototype's one unported row and the cell of
  its finding 4.

## Solution

**Every terminal seals one receipt.** The transition into any terminal goes through one
choke point in the store's append path. It derives a canonical
`transaction-terminal-receipt/v1` from the history, writes it create-if-absent under the
store root, and reads the bytes back and checks their digest. Only then does it append
`receipt_sealed {receipt_digest}` as the document's last event, in the same `state.json`
write as the transition. A store or read-back failure raises before `state.json` is written,
so the transaction stays nonterminal with its ledger intact (#88). The validator re-derives the
receipt from the history and requires the pinned digest. `load` of a terminal document also
reads the receipt file back and refuses bytes that are not the pinned receipt, so a sealed
receipt cannot be rewritten undetected. No operation rewrites or removes one.

**`failed` is entered only through `dispose_failed`.** It runs under custody and a fresh grant,
takes a closed disposition naming one ground from a closed set, and applies that ground's rules
before any write. There are two known-state grounds (a succeeded linked successor, or an
authorized no-recovery-path disposition) and #94's five observability-termination grounds. A
disposition with a possibly-live unit is `effects_unobservable`, and only a human grant at the
transaction's authority class may assert it. That form writes a standing hazard marker for each
concurrency key before the terminal. Later observations append to the durable receipt store and
reference the receipt digest. They never touch the receipt or the ledger.

**The receipt carries the terminal's truth for readers after the ledger is gone:** each proof-plan
unit's postcondition as separately observed, every synthesized stop with the owner result that
superseded it, the final obligation evaluations, and the outcome's own proof.

**The sweep reaches its full gate.** `unknown_external_state` is ported, so the table covers the
prototype's fourteen scenarios (56 cells) plus #205's two lease rows. Every terminal cell's
receipt is asserted against its bytes on disk.

Two options were weighed for where the seal happens (D2):

- **One choke point in the append path (chosen).** Every terminal writer (`advance`,
  `settle_proof`, `settle_recovery`, `dispose_failed`) already funnels through the one
  function that writes a terminal and releases custody. Sealing there makes "no terminal
  without a receipt" structural.
- **A separate `seal` operation after each terminal writer.** That leaves a window where the
  transaction is terminal with no receipt, which is exactly what #88 forbids.

## Decisions

### Modules

Two modules join the package, one per concern, as each earlier slice added (D1):

- `agent_tools.transaction_receipt` holds the receipt schema and its pure derivation
  (`terminal_receipt`). It also holds the validator's `receipt_sealed` rule, the derived
  `terminal` view, and `ReceiptStore`, the durable receipt store over the store root:
  receipts, hazard markers and post-terminal observations. `transaction_custody` pairs
  `LeaseAuthority` with its pure rules in the same way.
- `agent_tools.transaction_disposition` holds the ground and consequence vocabularies, the
  disposition's closed shape, the `DispositionRefused` reasons, the admission rules, the
  `failure_disposed` events, and the validator rules for that event and for the `failed`
  transition. It is pure.

`transaction_core` gains `dispose_failed`, the receipt read and observation operations, and the
seal inside its append path, all as thin wrappers. It re-exports the new public names. Both
modules are standard-library only, have no command-table row, are import-checked by the Nix
build, and join the neutrality check. `transaction_core` stays within #208 D20's 64000-byte
budget. Docstring economy comes first (#208 D27), and the plan fixes the exact figure (D17).

### The receipt

`terminal_receipt(document)` is a pure function of a document whose last event is a terminal
transition or the terminal `lease_released` that follows it. The receipt is a closed object
with exactly these keys (D3):

| Key | Content |
|---|---|
| `schema` | `transaction-terminal-receipt/v1` |
| `transaction_id`, `creation_key`, `recovers`, `authority_class`, `concurrency_keys` | as stored |
| `subject_digest`, `proof_plan_digest`, `recovery_plan_digest` | `telemetry_digest` of the subject; the two plan digests from `created` |
| `outcome` | the terminal state |
| `terminal_qualifier` | null unless `outcome` is `failed`; then `final_state_known` or `effects_unobservable` (#94) |
| `sealed_at` | the terminal write's `at` |
| `revision`, `history_digest` | the number of events the receipt covers, and `telemetry_digest` of those events: the receipt binds the whole ledger it closes |
| `postconditions` | one entry per proof-plan unit, in plan order (below) |
| `stops` | each `stop_synthesized` as `{seq, executor_id, fence, reason, superseded_by}` |
| `owner_results` | each `owner_result` as `{seq, executor_id, fence, custody, supersedes, result_digest}` |
| `evaluations` | each plan obligation's `{obligation_id, evaluation, reason, evidence_id}` at `sealed_at`, through #207's `evaluate` |
| `outcome_proof` | the outcome's closed section (below) |

A postcondition entry is `{unit, name, phase, status, observed, effected}`. `unit` is the action
id. `status` is the action's #206 status at the seal. `observed` is the latest `satisfied`
inspection as `{seq, at, reference, fence}`, or null. `effected` is true when the action ever
had an intended attempt, so a target observed satisfied without this transaction's intent is
recorded as observed but not effected (#208 D19). Each unit is thus observed and recorded
separately. A consumer's delivery postconditions (delivered, merged, closed, cleaned up) are
units of its proof plan and never core vocabulary, which keeps the core neutral (D4).

`superseded_by` is the seq of the first `owner_result` whose `supersedes` names that stop, or
null. Both events stay in the history and both are in the receipt (#117). The receipt carries
the owner result's digest, never its body: #88 bars raw payloads from receipts.

`outcome_proof` is closed per outcome (#88's outcome proof):

| Outcome | `outcome_proof` |
|---|---|
| `succeeded` | `{proof_sealed_seq, proof_cutoff_at, advisory_warnings}` from `proof_sealed` |
| `abandoned` | `{effect_snapshot}`: every action's #208 effect class, all `no_effect` |
| `rolled_back` | `{recovery_settled_seq, effect_snapshot, selected, restored, residue}` from the latest `recovery_started` and `recovery_settled` |
| `failed` | `{disposition_seq, ground, ground_reference, ground_occurred_at, successor, successor_receipt, effect_snapshot, units}` from `failure_disposed` |

The `rolled_back` section is the #83 rollback receipt's content, folded into the one terminal
receipt rather than stored as a second artifact. A restore goal is its edge's own `satisfied`
inspection (#208 D9). Target proof at a common cutoff after a restore stays out of scope (D5).

### Receipt storage, sealing and read-back

`ReceiptStore(root)` owns three directories under the store root. They sit beside the
transaction directories, never inside one, because the receipt must outlive a collected ledger
(#94, #72) (D6):

| Path | Content |
|---|---|
| `receipts/<hex>.json` | the receipt's `serialize` bytes, where `sha256:<hex>` is its `telemetry_digest` (agent-helpers rule 4); mode `0444` |
| `hazards/<sha256 hex of key, as the creation-key index names keys>/<hex>.json` | `{schema: transaction-hazard-marker/v1, key, receipt_digest}` |
| `observations/<hex>/<n>.json` | post-terminal observation `n`, from 1 (below) |

Every file is written create-if-absent: `O_CREAT|O_EXCL` on a temporary name in the same
directory, fsync, a hard link to the final name (which fails if the name exists), then the
directory is fsynced. An existing receipt at the digest's name is accepted only when its bytes
are the expected bytes, so a retried seal is idempotent. Anything else is `ReceiptInvalid`.
`read(digest)` reads the file, parses it with the strict loader, and requires that
re-serializing the parse gives the file's exact bytes and that its digest is the name. It
returns a read-only view.

The seal, inside the append that enters a terminal (D2):

1. Build the candidate as today: the transition, then `lease_released` reason `terminal` if
   custody is held.
2. Derive `terminal_receipt(candidate)` and write it.
3. Read it back through `read` and compare with the derived receipt. A mismatch is
   `ReceiptInvalid`.
4. For an `effects_unobservable` outcome, write one hazard marker per concurrency key.
5. Append `receipt_sealed {receipt_digest}` as the last event, validate, and write
   `state.json` (clearing the lease records as today).

Any failure in steps 2–4 propagates before step 5, and the transaction stays nonterminal. A
retry after a death between steps 2 and 5 seals at a new `at`, so it writes a new receipt and
leaves an unreferenced one behind. That is harmless, because a receipt is authoritative only
through the `receipt_sealed` that names it. An orphaned hazard marker errs on the safe side: a
spurious warning, never a hidden hazard (D6).

### `receipt_sealed` and the validator

`receipt_sealed` is `{seq, type, at, receipt_digest}`, with `at` equal to the terminal
transition's `at`. The validator requires it exactly when the state is terminal, as the
document's last event, immediately after the terminal transition or its `lease_released`. It
requires `receipt_digest` to equal the `telemetry_digest` of `terminal_receipt` over the
events before it, through the writer's own function (#208 D10). No event may follow it. The
store's `_validated_document` then reads a terminal document's receipt through
`ReceiptStore.read`, and a missing or altered receipt is `ReceiptInvalid` (a `StateInvalid`),
so a tampered receipt fails every load (D7).

`Transaction` gains `terminal`, derived on every load and never stored: null before a terminal,
else `{receipt_digest, outcome, terminal_qualifier}`.

### The failed disposition

`advance` refuses `failed` from any source, as it refuses `succeeded` and `rolled_back`, and it
refuses the reserved reason `failure_disposed` (D8).
`dispose_failed(custody, *, grant_id, disposition)` is the only way in. It runs only in
`attention_required`: a failed recovery returns there through `recovery_incomplete` first. It
decides in one write under one fence, through `_decide`.

A disposition is a strict, secret-free JSON object with exactly these keys:

| Key | Content |
|---|---|
| `ground` | one of `GROUNDS` |
| `reference` | non-empty: the ground's evidence reference |
| `occurred_at` | integer epoch milliseconds when the ground occurred, or null |
| `successor` | a transaction id, or null |
| `units` | list of `{unit, consequence, residue_bound, recheck}` |

`GROUNDS` is closed (D9):

- **Known final state** (qualifier `final_state_known`). `successor_succeeded` requires a
  `successor` this transaction linked with `roll_forward_linked` whose snapshot is
  `succeeded` (#83), and records that child's receipt digest. `no_recovery_path` is #83's
  authorized manual disposition. Both require `occurred_at` null and `units` empty.
- **Observability termination** (#94's closed set): `authority_retired`,
  `tenancy_destroyed`, `host_decommissioned`,
  `credential_class_revoked_without_successor` and `subject_scope_erased`. They require an
  `occurred_at` no later than the clock, `successor` null, and `units` listing exactly the
  actions with effect, in history order. Each unit's `consequence` is
  `effects_destroyed_with_authority`, with `residue_bound` and `recheck` null (the ground
  itself proves empty residue), or `effects_possibly_live_unobservable`, with `residue_bound`
  `bounded | unbounded` and `recheck` naming what a future observer must check. The qualifier
  is `effects_unobservable` exactly when some unit is possibly live. Otherwise it is
  `final_state_known`, so the path cannot become a catch-all (#94).

`dispose_failed` refuses `DispositionRefused` with the first reason that applies, before any
write. The core passes the successor's snapshot, loaded lock-free before the parent's lock:

1. `state_not_attention`.
2. `grant_required`: `grant_id` names no grant issued under the held fence after the latest
   transition into `attention_required` (#208 D19's freshness).
3. `malformed`: any closed-shape, vocabulary or per-ground field rule above.
4. `no_effect`: no action has an effect, so the truthful terminal is `abandoned` (#94:
   pre-intent releases are abandoned).
5. `reconciliation_required`: an action with an intended attempt is open, or its latest
   inspection was not made under the held fence (#83: fresh authoritative inspection).
6. For a known-state ground, `effect_uncertain`: some action is `in_progress` or `unknown`.
   Unknown never becomes terminal failure (#83). For `successor_succeeded`,
   `successor_not_succeeded`: the child is not linked, or not `succeeded`.
7. For an observability ground, `human_required`: the grant's `actor_kind` is not `human`.
   Then `authority_class_mismatch`: the grant's `authority_class` differs from the
   transaction's. #94 has only a human at the release's authority class assert a ground.
8. `units_mismatch`: `units` differs from the actions with effect.
9. `inspection_not_exhausted`: some possibly-live unit's latest inspection is not `unknown`,
   is not under the held fence, or is not later than `occurred_at` (#94's exhausted
   inspection).

Otherwise the one write appends `failure_disposed`, then the transition `attention_required ->
failed` with reason `failure_disposed` and external state `known`, the terminal
`lease_released`, and `receipt_sealed`. `failure_disposed` carries `{grant_id, ground,
reference, occurred_at, successor, successor_receipt, qualifier, effect_snapshot, units,
fence}`. `effect_snapshot` is every action's #208 class, verbatim. A unit last classified
`unknown` stays `unknown` in it, never `no_effect` (#94's hard prohibition). Every terminal
transition keeps external state `known`. The honesty of an unobservable disposition is carried
by its qualifier, units and residue (#94), never by relaxing #82's rule (D10).

The validator pairs `failure_disposed` with the `failed` transition, both ways. It re-checks
every clock-free rule against the fold before it: the grant's freshness, fence and fields, the
units set, and each possibly-live unit's latest inspection against `occurred_at`, both being
recorded values. It checks only that the successor is a linked child. It cannot read the
child's state, which the writer checked (#207 D31).

### Authority class and actor kind

`create` gains a required `authority_class` keyword with no default: a non-empty string that is
opaque to the core. It is stored on `created`, and a same-key `create` whose class differs is a
`CreationConflict`. `roll_forward` gains the same required keyword for its child, which may
declare its own class (D18). `issue_grant` gains the required keywords `actor_kind` (`human | agent`)
and `authority_class`, both stored on `grant_issued`. The core records a declared actor kind. It
cannot authenticate a human. That is the host's and #84's job, and this record is what their
gate will bind to (D11).

### Hazard markers and post-terminal observations

`hazard_markers(key)` lists the receipt digests marked on `key`, sorted, reading nothing else.
The markers are permanent. #94's mandatory preflight acknowledgement and `hazard_discharged`
belong to the consumer's preflight and are out of scope (D12).

`record_post_terminal(receipt_digest, *, observation, contradicts_ground)` needs no ledger. It
reads the receipt through `ReceiptStore.read`. `observation` must be exactly `{outcome, reason,
reference}` under #207's `closed_result_violation`. `contradicts_ground` is a boolean, and true
is legal only on a receipt with an observability ground. It writes
`observations/<hex>/<n>.json`, `{schema: transaction-post-terminal-observation/v1,
receipt_digest, n, at, outcome, reason, reference, contradicts_ground}`, taking the next free
`n` through the exclusive create. `post_terminal_observations(receipt_digest)` returns them in
order, each re-validated. The receipt's bytes, the ledger and the terminal are never touched
(#94: a re-observation never reopens terminal history) (D12).

### Errors

`DispositionRefused` (closed reasons, before any write) and `ReceiptInvalid` (a `StateInvalid`)
join `TransactionError`. Each has one construction path, and an unknown reason is a
`ValueError` (#206 D21). `DISPOSITION_REFUSAL_REASONS` is exactly the eleven reasons the
list above names: `state_not_attention`, `grant_required`, `malformed`, `no_effect`,
`reconciliation_required`, `effect_uncertain`, `successor_not_succeeded`, `human_required`,
`authority_class_mismatch`, `units_mismatch` and `inspection_not_exhausted`.

### Transaction state `transaction-state/v6`

The schema moves to v6, and a v5 document fails closed naming its version (#207 D13):
`created.authority_class`; `grant_issued.actor_kind` and `authority_class`; the events
`failure_disposed` and `receipt_sealed`; and `failed` only through the pairing above. Proof
and recovery plan schemas are unchanged.

### Late owner results

`reap` and `record_owner_result` are unchanged. A late owner result whose span the core issued
supersedes that span's latest synthesized stop as evidence. It never restores authority, and it
changes no state (#205 D18, #117). What is new is that the receipt keeps both, linked both ways.
The core adds no "terminal result" flag: the result body stays opaque, and consumer semantics
are #125's (D13). `record_owner_result` still refuses a terminal. A result that arrives after
the seal is a post-terminal observation referencing the receipt, never a ledger write (D18).

### Sweep

`unknown_external_state` is ported (D14). A new world fault `unobservable_after_invoke` arms
`unknown_inspection` once the first invocation is applied. The first publication action is
therefore intended, applied and inspected `unknown`, and the executor parks with external state
`unknown`. The row carries `recover: True`. The recovery step is refused `effect_uncertain`. The
executor, on that refusal alone, then tries `dispose_failed` twice under grant `recovery-1`
(actor kind `agent`): `no_recovery_path`, refused `effect_uncertain`, and `authority_retired`
with the unit possibly live, refused `human_required`. Every refusal goes into `World.notes`.

| Scenario | Shape | Final | Asserted |
|---|---|---|---|
| unknown_external_state | platform, product, daemon | attention_required | path `PUB_PARK`; last transition external state `unknown`; the first publication action invoked once and `unknown`; the three refusals in order; no `receipt_sealed`, no `receipts/` entry, custody held |
| | library | attention_required | the same on its first publication action |

The sweep then has sixteen scenarios by four shapes: 64 cells. `PROTOTYPE_SCENARIOS` names the
fourteen ported from `dc98ba9`, whose 56 cells are the issue's gate. `lease_renewal` and
`lease_lapse` are #205's own rows (D15). A test pins the fourteen names. Another pins the four
gap cells to their rows: subject identity to `stale_false_positive_health`, lease loss to
`resume_after_crash` (the prototype's executor-loss takeover), convergence livelock to
`expired_snapshot`, and unobservable release to `unknown_external_state`.

Every terminal cell (`succeeded`, `rolled_back`, `abandoned`) also asserts four things:
`receipt_sealed` is its last event; `read_receipt` returns a receipt whose `outcome` is the
final state; the receipt file's bytes hash to the digest; and, for `succeeded`, every
postcondition is `observed` and `effected`. Every parked cell asserts no `receipt_sealed`. No
earlier final state, path or attempt count changes.

### Documentation

CLAUDE.md's sentence on `agent_tools.transaction_core` names slice 6 and the two new modules,
still caller-less until #125. The #204–#208 specs are point-in-time records and stay unedited.

## Test seams

The three existing seams stay, and none is added (D16):

1. **Store interface plus its documented layout**, with a temporary root, a fake clock, fake
   effects and fake observers. This seam carries the criteria:
   - **Receipts.** For each of the four terminals, `receipts/<hex>.json` exists, its bytes
     hash to the digest `receipt_sealed` names, and `read_receipt` returns it. A byte-altered
     receipt makes `load` raise `ReceiptInvalid`. A `receipts` path that is a file or a
     symlink, or an unwritable `receipts/`, refuses the seal with `state.json` byte-identical
     and the state nonterminal. A hand-edited `receipt_digest`, a missing `receipt_sealed` or
     an event after it is `StateInvalid`.
   - **`failed`.** An observability ground under an `agent` grant is refused `human_required`,
     and under a human grant of another class `authority_class_mismatch`, with bytes unchanged.
     Under a human grant at the class with a possibly-live unit, it seals
     `effects_unobservable` and one hazard marker per key. With every unit destroyed it seals
     `final_state_known` and writes no marker. Every other `DispositionRefused` reason is
     covered, and so are `advance` refusing `failed` and the reserved reason, and a
     `successor_succeeded` over a driven child. A post-terminal observation, with and without
     `contradicts_ground`, leaves the receipt bytes and `state.json` unchanged.
   - **Late owner result.** Reap, then a stale owner result, then a terminal. The receipt's
     stop names the result in `superseded_by`, and the result names the stop in `supersedes`.
   - **Postcondition fixtures** on a delivery-shaped declaration: one publication unit and
     three activation units standing for implementation delivered, merged, closed and cleaned
     up. *Merge-before-close* and *close-before-merge* observe the middle two in opposite
     orders; in the second, the closed target is observed satisfied before any intent.
     *Evidence invalidation* lapses the lease after every unit is observed. Snapshot evidence
     is voided and recollected before the seal. In each fixture, exactly one receipt exists,
     every pre-terminal event serializes byte-identically in the final document, and the
     receipt records all four units, each with its own observation (`effected` false for the
     externally closed target). In the third, the receipt's evaluations cite the recollected
     evidence.
   - The v6 validator by hand-edited documents, and v5 refused.
2. **Fixture executor against the store**: the asserted sweep, sixteen scenarios by four
   shapes, against the committed table.
3. **Neutrality checker** over all eleven transaction modules.

New tests go in `test_transaction_receipt` and `test_transaction_disposition`, beside the
recovery tests and run by `just agent-workflow-tests`. Each file stays under the review member
cap. Earlier test files change only where v6 demands it: the schema string, the required
`authority_class` and grant keywords, `failed` no longer reachable by `advance`, and the
terminal's trailing `receipt_sealed`.

## Out of scope

- Wiring the core into `workflow-state` or the attempts cutover (#125), and ship-release as a
  consumer. There is no command-table row, Nix or host change.
- The consumer's delivery postcondition vocabulary, `not_applicable` applicability, and
  delivery remainders (#151/#171 as ported by #125).
- Target-identity proof at a common cutoff after a restore, and a separate content-addressed
  `rollback_receipt` artifact (D5).
- #94's preflight acknowledgement, `hazard_discharged`, anchor retention, tombstones and the
  doctor's surfacing (#69, #72, #83 retention).
- #84 authorization content: authenticating a human, grant expiry, spend, single-use
  confirmation tokens.
- Runtime-ledger deletion (#72), and replicating receipts to more than one durable store.
- Driving roll-forward children in the sweep, and cross-repository composition (#87).

## Open questions

None remain: every frontier question was self-answered in the ledger below.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Two new modules: `transaction_receipt` (receipt schema, pure derivation, `receipt_sealed` rule, `terminal` view, `ReceiptStore` IO) and `transaction_disposition` (pure grounds, disposition shape, refusals, events, validator rules); both join the neutrality check. | #207 D1 / #208 D1 split per concern; `transaction_custody` pairs pure rules with its file authority; the-bar single responsibility. | Growing `transaction_recovery` or `transaction_history` (a disposition and a receipt change for different reasons) or a separate pure/IO module pair for receipts (a third module for one store). |
| D2 | The seal happens at the one append path that enters a terminal: derive, write create-if-absent, read back, write hazard markers, then append `receipt_sealed` last in the same `state.json` write; any failure leaves the transaction nonterminal. | #88 "read back by digest before the release-state module atomically records the digest, terminal state"; every terminal writer already funnels through `_append`. | A separate `seal` call after each terminal writer (a terminal without a receipt in between) or sealing only `succeeded` (#88 requires all four). |
| D3 | The receipt is a closed `transaction-terminal-receipt/v1` derived purely from the history: identity, plan digests, outcome, qualifier, `sealed_at`, a `history_digest` over the covered events, per-unit postconditions, stops and owner results linked both ways, final evaluations, and a closed per-outcome proof; owner-result bodies appear only as digests. | #88 common envelope and outcome proof; #117 "the receipt records both"; #88 bars raw payloads. | Copying events verbatim into the receipt (unbounded, payload-bearing) or a receipt holding only the outcome (useless once the ledger is collected). |
| D4 | Postconditions are the proof plan's units, each recorded from its own action fold (latest `satisfied` inspection, and whether this transaction had intent); delivery words are consumer unit names, never core vocabulary. | #88 unit postconditions are per-unit; #123 fixes five semantics plus two derived classes; the neutrality check forbids `merge`; #208 D19 observed versus effected. | A sixth proof semantic `postcondition` (reopens #123's closed set) or a core-declared four-postcondition list (provider vocabulary in the core). |
| D5 | The `rolled_back` receipt section carries #83's rollback content (snapshot, selection, restored, residue); target proof at a common cutoff after a restore and a separate `rollback_receipt` file stay out of scope. | #209 lists neither in its build or criteria; #208 D9 restore goal is the edge's own `satisfied` inspection; YAGNI. | A rollback proof cohort now (a second convergence machine with no criterion) or a second receipt artifact (two authorities for one terminal). |
| D6 | Receipts, hazard markers and post-terminal observations live under root-level `receipts/`, `hazards/<sha256 key>/` and `observations/<hex>/`, beside rather than inside transaction directories; files are exclusive-create plus link, fsynced; a receipt's name is its `telemetry_digest` over the `serialize` bytes; an orphan from a death before the state write is inert. | #94 "the receipt outlives the ledger"; #72 ledger collection; agent-helpers rule 4; #88 create-if-absent. | Storing under `<id>/` (dies with the ledger) or content-addressing raw file bytes with a local sha (a second digest format). |
| D7 | The validator requires `receipt_sealed` as a terminal document's last event and re-derives its digest through `terminal_receipt`; `load` also reads the receipt file back, so a tampered receipt is `ReceiptInvalid` on every load; nothing rewrites or deletes a receipt. | #88 "terminal receipts are permanent"; #208 D10 writer-function re-derivation; the-bar defense in depth. | Trusting the pinned digest without reading the file (an altered receipt would go unnoticed) or a mutable receipt with an audit trail. |
| D8 | `advance` refuses `failed` and the reserved reason `failure_disposed`; `dispose_failed` runs only in `attention_required` under a fresh grant and decides in one write through `_decide`. | #88/#83 failed needs known final state plus a disposition; #207 D10 and #208 D9 single-judge precedent; #208 D19 grant freshness. | Leaving `failed` to `advance` with a predicate (the caller cites the ground) or admitting `recovering -> failed` (a live recovery would be closed under its own edges). |
| D9 | `GROUNDS` = `successor_succeeded`, `no_recovery_path` (known state) plus #94's five observability grounds; per-unit consequence `effects_destroyed_with_authority` or `effects_possibly_live_unobservable` (with `residue_bound` and `recheck`); qualifier `effects_unobservable` iff some unit is possibly live; refusal order state, grant, malformed, `no_effect`, reconciliation, then ground rules. | #94 resolution (grounds, consequences, qualifier rule, residue, exhausted inspection, pre-intent is abandoned); #83 successor and manual dispositions; #208 D8 admission order. | Only #94's grounds (leaves #83's ordinary failed and #208's deferred successor close unreachable) or a free-text ground (not closed, #69 fail loud). |
| D10 | Every terminal transition keeps external state `known`; an unobservable disposition's honesty is its qualifier, verbatim effect snapshot and residue; a unit last `unknown` is never recorded `no_effect`. | #82 unknown is never terminal; #94 "honesty comes from the qualifier and residue record, never from softening the outcome", its hard prohibition. | Admitting a terminal with external state `unknown` for this path (breaks #82's invariant and the sweep's "never terminal on unknown"). |
| D11 | `create` requires an opaque `authority_class` (stored, compared on same-key create); `issue_grant` requires `actor_kind` (`human \| agent`) and `authority_class`; observability grounds need a human grant whose class equals the transaction's; the core records, not authenticates, the actor kind. | #94 "a human operator at the same authority class that authorized the release's mutations"; #209 "at the release's authority class"; bootstrap "no project policy is defaulted"; #84 owns authentication. | An ordered class vocabulary (#209 asks for equality, an order is YAGNI) or the assertion outside a grant (a second authorization record beside #205's grants). |
| D12 | `hazard_markers(key)` reads the permanent markers; `record_post_terminal` appends numbered observations referencing the receipt digest, with `contradicts_ground` legal only on an observability ground, and never touches the receipt or ledger; acknowledgement and discharge are the consumer's. | #94 hazard marker on the key, post-terminal observation in the durable evidence store not runtime state, `disposition_ground_contradicted`; YAGNI. | Appending post-terminal events to `state.json` (a collected ledger would lose them, and it rewrites terminal history) or building preflight acknowledgement now (no consumer). |
| D13 | Late owner results keep #205's semantics (evidence only, `supersedes` the span's latest stop); the receipt links stop and result both ways; no core "terminal result" flag. | #117 "may supersede them as evidence while both events remain recorded; it never restores stale mutation authority"; #205 D18. | A flag marking terminal owner results (consumer semantics that are #125's) or letting a late result change state (restores stale authority). |
| D14 | `unknown_external_state` arms `unknown_inspection` after the first applied invoke, so an intended effect becomes unobservable; the automated executor's recovery and both dispositions are refused and the cell stays parked with no receipt. | Prototype finding 4 is about effects that became unobservable; #94 pre-intent is abandoned, so an always-on fault would test nothing about effects; #94 never automatic, and the executor is an agent. | Porting the fault as always-on (parks before any intent) or letting the fixture assert the human ground (automation posing as a human). |
| D15 | The sweep has 16 scenarios by 4 shapes (64 cells); `PROTOTYPE_SCENARIOS` pins the 14 `dc98ba9` names whose 56 cells are #209's gate; the gap cells are `stale_false_positive_health`, `resume_after_crash`, `expired_snapshot` and `unknown_external_state`; every terminal cell asserts its receipt. | #209 and #123 "four-shape by fourteen-scenario"; #205 added the two lease rows; the prototype's lease finding surfaced at executor takeover. | Dropping the #205 lease rows to hit 56 literally (loses coverage) or counting 64 as the gate (misstates the issue). |
| D16 | Keep the three seams (store with documented layout, fake clock, effects and observers; asserted sweep; neutrality over eleven modules); new tests in `test_transaction_receipt` and `test_transaction_disposition`, the postcondition fixtures on a delivery-shaped declaration. | #208 D16, D24; the-bar tests that can fail; the issue's fixtures. | Patching private store methods to inject read-back failures (the documented layout gives an unwritable or non-directory `receipts/`). |
| D17 | Schema `transaction-state/v6`, v5 fails closed; `transaction_core` stays within 64000 bytes, docstring economy first, the plan fixing the exact budget. | #207 D13, #208 D12; #208 D17, D20, D27 (the base is 61869 bytes). | Additive events under v5 (its closed dispatch meets unknown types) or raising the core budget (breaks the review member cap margin). |
| D18 | Grill: `roll_forward` takes the child's `authority_class` explicitly; a late owner result after the seal goes through `record_post_terminal`, since `record_owner_result` keeps refusing terminals; hazard key directories hash the key as the creation-key index does. | #208 D11 the child is created through the ordinary create path; #117 "later observations use immutable linked evidence/receipt supplements"; #204 index naming. | Inheriting the parent's class silently (a default the bootstrap forbids) or appending a late result to a terminal ledger (rewrites terminal history). |
