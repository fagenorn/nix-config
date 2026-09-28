# Transaction core 5/6: recovery plans — restore, compensate, residue, roll-forward

Design for [#208](https://github.com/fagenorn/nix-config/issues/208), slice 5 of 6 of
[#123](https://github.com/fagenorn/nix-config/issues/123), 2026-09-28, against main `e1b3031`.
Written in autonomous mode: every choice below is an agent judgment inside the issue's
delegated scope, recorded in the decision ledger, not a human answer.

## Problem

Slices 1–4 (#204–#207) give a transaction a closed lifecycle, fenced custody, a safe way to
cause effects and a proof judge. They give it no safe way back. After a failed activation or a
rejected proof the transaction parks in `attention_required`, and from there:

- any caller may `advance` into `recovering`, then into `rolled_back`, with nothing restored;
- any caller may `advance` into `abandoned` after effects landed, although #82 allows
  `abandoned` only when no release effect exists;
- nothing says which units can be restored and which cannot, so a unit whose prior subject can
  never return (a forward-only migration, an immutable published version) could be "rolled
  back" by fiat;
- nothing checks, before the first mutation, that a unit claiming to be restorable has a
  retained anchor to restore to, or that the operations the transaction will need are ones its
  effects offer. Both are discovered mid-flight, after effects exist.

#83 settled the recovery contract: one immutable `recovery_plan` derived at creation; per-unit
postures `restorable | compensatable | supersedable_only | manual_only`; `restore` converges to
an exact prior subject while `compensate` mitigates without claiming reversal; `rolled_back` may
cite only predeclared bounded residue; roll-forward is a new linked child, never a mutation of
the parent. #82 fixed the terminal meanings. This slice ships that contract in the core.

## Solution

Every transaction gets a **recovery plan** at creation, beside its proof plan. The caller
passes a closed **recovery declaration**: the effects it will call and the operations each
offers, and for every proof-plan unit its forward operation, posture, rollback anchor,
compatibility check and recovery edges. The core compiles it before any lock. A unit naming an
operation its effect does not offer, a posture its edges contradict, or a unit set that differs
from the proof plan's is refused, and nothing is written. The plan is materialized under the new
id and pinned by digest on the `created` event, exactly as the proof plan is (#207 D3).

Four new fenced store operations run recovery, each around a pure half in the new modules:

- `verify_anchors` runs in `ready`. It observes every restorable unit's rollback anchor, and
  entering `publishing` is gated on its record. A missing anchor is refused before the first
  mutation, and nothing is written.
- `begin_recovery` runs in `attention_required` under a fresh grant. It freezes the effect
  snapshot from the reconciled action fold and selects the recovery edges. Then it observes
  each restorable unit's compatibility with the current state and enters `recovering`. A
  non-restorable affected unit, an incompatible restore, an uncertain effect, or no effect at
  all is refused with nothing written.
- `settle_recovery` is the single judge of a recovery. It enters `rolled_back` when every
  selected edge is satisfied, citing the restored units and the declared residue. Otherwise
  it parks `recovery_incomplete`.
- `roll_forward` creates a linked child transaction under a fresh grant and appends the link
  to the parent's history. The parent stays in `attention_required`.

`advance` can no longer enter `recovering` or `rolled_back`. It enters `abandoned` only when no
action has an effect. Recovery edges are ordinary actions driven through #206's protocol:
`invoke_action` now also runs in `recovering`, for the selected edges only.

Two options were weighed for how recovery reaches a terminal (D9):

- **A core judge, `settle_recovery` (chosen).** It mirrors #207's `settle_proof`: the verdict
  and the transition happen in one write under one fence. A caller cannot call a partial
  recovery `rolled_back`, and cannot cite residue that was never declared.
- **Caller-driven `advance` gated by a pure predicate.** That takes one write fewer, but the
  residue citation would come from the caller, and the gate and the citation could disagree.

A third option was rejected: executing recovery inside the core (the prototype's
`run_recovery`). Effects stay caller-passed per call (#206 D3), and the core never loops over
effects on its own.

## Decisions

### Modules

Two pure modules join the package, mirroring #207's plan/proof split (D1):

- `agent_tools.transaction_recovery_plan` holds the declaration's closed schema, the
  vocabularies, the compiler (`compile_recovery` for the declaration's own rules, and
  `bind_recovery` for the rules that also read the compiled proof plan), `materialize_recovery`,
  and the inverse and re-check the validator uses.
- `agent_tools.transaction_recovery` holds the recovery event rules the history validator calls,
  and the effect snapshot and selection. It also holds the admission rules of the four
  operations, the settlement verdict, the `no_effect` predicate, the lifecycle gates and the
  snapshot's `recovery` view.

Neither module reads a file, lock or clock. `transaction_core` gains the four store operations
as thin wrappers that hold locks, read the clock, call the observer and write. It re-exports
the new public names. Both modules are standard-library only, have no command-table row, are
import-checked by the Nix build, and join the neutrality check. `transaction_core` stays within
the 65536-byte review member cap, and the plan fixes its exact budget (D17).

### The recovery declaration

`create(creation_key, subject, *, concurrency_keys, proof, recovery)` gains a required
`recovery` keyword with no default. A transaction with nothing to recover passes
`{"effects": {}, "units": []}`, which pairs with the empty proof declaration (D2). The
declaration is a strict, secret-free JSON object with exactly these keys:

| Key | Content |
|---|---|
| `effects` | map from handle to `{operations}`: a list of distinct non-empty operation names the effect offers |
| `units` | list of `{name, parameters, effect, operation, posture, anchor, compatibility, edges}` |

A unit's `name` and `parameters` are those of exactly one proof-declaration unit, and every
proof unit has exactly one recovery unit (#83: every effectful unit declares its posture before
mutation). `effect` names a declared effect handle, and `operation` is the unit's forward
operation. `posture` is one of `restorable | compensatable | supersedable_only | manual_only`
(#83's spelling, D3). `anchor` and `compatibility` are each `{predicate, parameters}` or null.
`edges` is a list of `{action, operation, parameters, residue}`, where `action` is `restore` or
`compensate`.

Posture rules fix what a unit may do (D3, D4):

| Posture | `anchor`, `compatibility` | `edges` |
|---|---|---|
| `restorable` | both required | exactly one `restore` edge, first, then zero or more `compensate` edges |
| `compensatable` | both null | one or more `compensate` edges, no `restore` |
| `supersedable_only`, `manual_only` | both null | none |

A `compensate` edge carries a non-empty `residue` string: the bounded residue it leaves, declared
before mutation (#83). A `restore` edge carries `residue: null`. An edge is an action whose
`name` is its `operation` and whose `parameters` are its own, so its id is
`action_id(transaction_id, operation, parameters)` (#206 D4). Operation, predicate and handle
strings are opaque to the core, as action names and collector handles are, which keeps the core
provider-neutral.

This is what makes the first acceptance criterion structural. A unit that is not restorable
cannot declare a `restore` edge, so no recovery can reach `rolled_back` by restoring it. It
either compensates (`compensatable`) or refuses to recover at all (`supersedable_only`,
`manual_only`).

### Compilation and rejection (before any write)

`create` compiles in this order, before the creation lock and before any index, directory or
state file exists (D5):

1. `compile_recovery(recovery)`: the declaration's own rules;
2. `compile_proof(proof)`: unchanged from #207;
3. `bind_recovery(compiled_recovery, compiled_proof)`: the rules that read both.

A refusal is `RecoveryPlanRejected` with one `reason` from this closed set, first failure wins:

- `malformed`: any shape, type or closed-key violation, or an unknown posture or edge action. It
  also covers two edges, or an edge and a unit, that share one action identity.
- `posture_violation`: a unit whose anchor, compatibility or edges break its posture's row.
- `unknown_effect`: a unit naming an undeclared effect handle.
- `unsupported_operation`: a unit's `operation`, or one of its edges' operations, that its
  effect does not list.
- `unit_mismatch` (bind): the recovery units' `(name, parameters)` set differs from the proof
  units'.
- `unsupported_check` (bind): an anchor or compatibility predicate that the unit's proof
  collector does not list. The unit's collector is deterministic by #207's
  `required_model_judgment` rule, so a model never vouches for an anchor.

Recovery's own rules run before the proof compile because operation support is the first thing
resolution checks, as it was in the prototype (`resolve` at `dc98ba9`). A unit authored against
an operation its effect lacks is refused as `unsupported_operation`, whatever its collector.

### Materialization, storage and immutability

After the id is minted, `materialize_recovery(bound, transaction_id)` produces the stored
`recovery_plan`. It is a closed object with schema `transaction-recovery-plan/v1`, `effects`,
and `units` in the proof plan's unit order. Each unit carries its `action_id` (the proof plan's)
and its declared fields, and each edge carries its `action_id` (D6).

The plan is stored as the top-level `recovery_plan`, and its `telemetry_digest` is stored as
`recovery_plan_digest` on the `created` event. The validator accepts the stored plan only when
it serializes byte-identically to the re-materialization of its own declaration and hashes to
that digest. This is #207 D24's rule, with one home for the compile rules. There is no replace
operation. A same-key `create` whose recovery-plan digest differs is a `CreationConflict` naming
the recovery plan, and nothing is written. A hand-edited `recovery_plan` or digest is
`StateInvalid`. That is the "cannot be changed after creation" criterion.

### Rollback anchors before the first mutation

`verify_anchors(custody, *, observer)` runs only in `ready`; elsewhere it is `RecoveryRefused`
`state_not_ready`. With no restorable unit it returns the snapshot, with no call and no write.
Otherwise it takes the lock twice, as `collect_obligation` does (#207 D6):

- **First hold.** Refuse a terminal, run the fenced check and build one request per restorable
  unit, in plan order. A request is a read-only mapping of `transaction_id`, `unit` (the unit's
  action id), `check` (`anchor`), `predicate`, `collector` (the unit's proof collector),
  `parameters` and `fence`.
- **The calls.** Run `observer.observe` for every request with no lock held. Each result must be
  exactly `{outcome, reason, reference}`, with `outcome` in `satisfied | unsatisfied | unknown`
  and a non-empty, secret-free `reason` and `reference`. Anything else is
  `EffectResultInvalid`. What the observer raises propagates.
- **Second hold.** Repeat the terminal refusal and the fenced check, and refuse `history_changed`
  when the history grew since the first hold. If any outcome is not `satisfied`, refuse
  `rollback_anchor_missing` naming the first such unit. A missing and an unverifiable anchor
  are the same refusal (#83). Otherwise append `anchors_verified {anchors, fence}`, where
  `anchors` lists each restorable unit's `{unit, reference}` in plan order.

Every refusal writes nothing, so the transaction's `state.json` is byte-identical. The
lifecycle gate (D7) refuses `ready → publishing` as `TransitionRefused` unless an
`anchors_verified` stamped with the presented custody's fence exists, when the plan has any
restorable unit. #83's "fresh `rollback_readiness` before the first release mutation" becomes
"under the fence that enters publication". A lapse and reacquisition in `ready` needs a fresh
verification. A resume from a parking to `publishing` passes no gate (#207 D12), since the gate
was met when publication first began. The validator mirrors the gate: a `ready → publishing`
transition needs an earlier `anchors_verified` in the same custody span with that span's fence.

This preflight is distinct from a proof obligation of semantic `rollback_readiness` (#88). That
one is proven in `proving`. This one gates mutation.

### Reconciliation and the effect snapshot

A unit's effect class is derived from the #206 action fold of its action (D8):

| Action | Class |
|---|---|
| no attempt ever intended, or latest inspection `absent` with no open attempt | `no_effect` |
| latest inspection `satisfied` | `target_satisfied` |
| latest inspection `diverged` | `diverged` |
| open attempt, or latest inspection `in_progress` | `in_progress` |
| latest inspection `unknown` | `unknown` |

A unit is **affected** unless it is `no_effect`. #83's `effect_present` has no source in #206's
inspection vocabulary, so it is not produced. An action with no intended attempt is `no_effect`
whatever its inspection reads: the core reaches an effect only through `invoke_action`, behind a
durable intent (#206 D5), so a target already holding the expected subject without an intent was
not changed by this transaction, and recovery must not restore what it did not change (D19). The core runs no reconciliation itself. It refuses
until the caller has inspected every action that ever had an attempt under the held fence, using
`inspect_action`, which is legal in every parking.

The pure predicate `no_effect(document)` holds when every action in the history, forward or
edge, declared in the plan or not, is `no_effect`.

### `begin_recovery`

`begin_recovery(custody, *, grant_id, observer)` takes the lock twice. The first hold refuses a
terminal and runs the fenced check. Then it refuses `RecoveryRefused` with the first reason that
applies, before any write or call (D8):

1. `state_not_attention`: the state is not `attention_required`.
2. `grant_required`: `grant_id` names no admissible `grant_issued` recorded after the latest
   transition into `attention_required` (#205's grants; #83: no recovery mutation on an old
   release grant). The bound is the latest entry, not the start of the parked run, because a
   `recovery_incomplete` park stays inside one parked run, and #83 demands a new grant after a
   failed or uncertain edge (D19).
3. `reconciliation_required`: some action with an intended attempt is open, or its latest
   inspection was not made under the held fence.
4. `undeclared_effect`: an action that is neither a plan unit nor a plan edge is not
   `no_effect`. It has no posture, so nothing can recover it.
5. `effect_uncertain`: an affected unit is `in_progress` or `unknown`. Unknown never selects an
   action (#82, #83).
6. `no_effect`: no unit is affected. The truthful terminal is `abandoned`, which `advance`
   enters through the D10 gate.
7. `unit_not_restorable`: an affected unit is `supersedable_only` or `manual_only`. The first in
   plan order is named, and no observer is called.

The **selection** is every edge of every affected unit, in plan order and declaration order.
Every selected edge is required (#83: no best-effort unit). One request per affected
`restorable` unit, with `check: compatibility`, goes to the observer with no lock held. Its
result shape and failure rules are those of `verify_anchors`.

The second hold repeats the terminal refusal and the fenced check. It refuses
`history_changed` when the history grew since the first hold, as `verify_anchors` does. It refuses
`restore_incompatible`, naming the first unit whose compatibility outcome is not `satisfied`:
recovery never restores a prior subject it cannot prove compatible with the current state, and
never runs an implicit down migration (#83). None of these refusals writes anything. Otherwise
it appends, in one write:

- `recovery_started {grant_id, effect_snapshot, selected, checks, fence}`. `effect_snapshot`
  (#83's term) maps every plan unit's action id to its class, `selected` lists the selected edges' action ids, and `checks`
  lists each compatibility `{unit, reference}`.
- The transition `attention_required → recovering`, with reason `recovery_started` and external
  state `known`.

The `recovery_started` record is the durable write-intent #83 requires before `recovering`. A
later `begin_recovery`, after a `recovery_incomplete` park, needs a new grant and re-derives the
selection. Edges already satisfied stay satisfied, because invoking a satisfied action is a
no-op (#206 D7), so completed recovery work is kept and never blindly undone.

### Recovery edges through the administrative protocol

`EFFECT_STATES` gains `recovering`. `invoke_action` in `recovering` admits only an action named
in the latest `recovery_started`'s `selected`. An edge action of the plan invoked outside
`recovering` is refused the same way. The refusal is `InvocationRefused` with the new reason
`not_selected`, raised before any write or call (D15). Otherwise the #206 rules are unchanged:
a fresh `absent` inspection under the held fence, durable intent, the three-attempt budget
within 15 minutes, and inspection after the call. #83's recovery retry limits are #82's, which
the protocol already enforces. Forward actions cannot be invoked in `recovering`. Undeclared
actions stay invocable in `publishing` and `activating` (#207 D12).

### `settle_recovery`

`settle_recovery(custody)` runs only in `recovering` (`state_not_recovering`). One write decides
the first case that matches (D9):

1. **Rolled back.** Every selected edge's action status is `satisfied`. The call appends
   `recovery_settled {restored, residue, fence}`, where `restored` lists the units with a
   restore edge and `residue` lists `{unit, residue}` for each compensate edge, both in
   selection order. Then it appends the transition `recovering → rolled_back` with reason
   `recovery_settled` and external state `known`, and #205's terminal `lease_released`. Before
   any write, this case is refused `TransitionRefused` while any action is `open`,
   `in_progress` or `unknown`, as `settle_proof` does (#207 D21).
2. **Incomplete.** Some selected edge is `diverged` or `unknown`, or reads `absent` with no
   admissible retry (#206's `not_retryable`, `budget_exhausted` or `window_closed`). The call
   appends `recovery_incomplete {actions, fence}`, where `actions` lists those edges. Then it
   appends the transition `recovering → attention_required` with reason `recovery_incomplete`,
   and external state `unknown` if any edge is `unknown`, else `known`. Completed edges keep
   their facts (#83).
3. **Pending.** Otherwise, with some edge not yet inspected, absent with retry budget left,
   open or `in_progress`, the call is `RecoveryRefused` `recovery_pending`, and nothing is
   written.

A restore goal is met when its edge's own inspection reads `satisfied`. Under #206 that means
the effect observed the exact expected subject, which is the declared prior subject. The sealed
`rollback_receipt`, and target proof at a common cutoff, are #209's receipts. Partial recovery
never enters `rolled_back`, and the event ledger remains authoritative.

### Terminal gates and reserved reasons

These rules are shared by `advance` and the validator (D10):

- `advance` refuses `recovering`, which only `begin_recovery` enters, and `rolled_back`, which
  only `settle_recovery` enters, whatever the source.
- `abandoned` from any source needs `no_effect`. Otherwise `advance` refuses it
  `TransitionRefused` naming the first affected action, and the validator refuses such a
  history. #82: `abandoned` only when no release effect exists.
- `recovery_started` must be immediately followed by the transition into `recovering`, and that
  transition immediately preceded by it. The same pairing binds `recovery_settled` to
  `rolled_back`, and `recovery_incomplete` to its park, whose reason is reserved.
  `advance` refuses the reserved reasons `recovery_started`, `recovery_settled` and
  `recovery_incomplete`.
- The validator re-derives `recovery_started`'s `effect_snapshot` and `selected` from the fold
  before it, through the same pure selection function the writer uses, and re-checks
  `recovery_settled`'s citations against the plan and its edges' `satisfied` statuses. For
  `recovery_incomplete` it checks only the clock-free facts: every listed edge is selected and
  not `satisfied`. It does not re-judge the retry window, which compares `at` values (#207
  D31), or the compatibility outcomes, which are recorded only as references.

`failed` is untouched. Its positive-ground disposition is #209's.

### `roll_forward`

`roll_forward(custody, *, grant_id, reason, creation_key, subject, concurrency_keys, proof,
recovery)` returns the child `Transaction` (D11):

1. **Parent, first hold.** Refuse a terminal, run the fenced check, then refuse
   `state_not_attention` or `grant_required` with D8's meanings. Release the lock.
2. **The child.** Create it through the ordinary `create` path, with every compilation rule and
   the same deduplication, but with `recovers` set to the parent's id. The child's `created`
   event carries `recovers`, which is null for every other transaction. A same-key `create`
   whose `recovers` differs is a `CreationConflict`, so the parent's own key can never become
   its child.
3. **Parent, second hold.** Repeat the refusals, then append
   `roll_forward_linked {child_transaction_id, grant_id, reason, fence}`, unless a link to that
   child already exists. The parent's state does not change.

The parent's lock is never held across the creation lock, because a concurrent create of the
parent's key takes those locks in the opposite order. If the process dies between steps 2 and
3, the child exists, carrying its backlink, but the parent lacks the link. A retry with the
same creation key finds the same child and links it once. The parent's history is append-only,
so the link rewrites nothing. The child owns its own id, subject, plans, custody, grants and
attempts, and it is not driven here. When it shares the parent's concurrency keys it can
acquire custody only once the parent's parked custody is released or quiesces (#205 D19). Closing the parent `failed` with a no-recovery disposition
citing a successful child is #209's.

### Errors

`RecoveryPlanRejected` (compile, before any lock or write) and `RecoveryRefused` (runtime, before
any write) join `TransactionError`. Each has a closed `reason` and one construction path that
raises `ValueError` on an unknown reason (#206 D21). `RECOVERY_REFUSAL_REASONS` is
`state_not_ready`, `state_not_attention`, `state_not_recovering`, `history_changed`,
`rollback_anchor_missing`, `grant_required`, `reconciliation_required`, `undeclared_effect`,
`effect_uncertain`, `no_effect`, `unit_not_restorable`, `restore_incompatible` and
`recovery_pending` (D16).

### Transaction state `transaction-state/v5`

The schema moves to v5, and a v4 document fails closed naming its version (#207 D13's
reasoning: no caller, so no v4 state exists). The changes are:

- a new top-level `recovery_plan`;
- `created` gains `recovery_plan_digest` and `recovers`;
- five new fenced events: `anchors_verified`, `recovery_started`, `recovery_settled`,
  `recovery_incomplete` and `roll_forward_linked` (grants reuse `grant_issued`);
- `invocation_intended` becomes legal in `recovering` for selected edges.

`Transaction` gains `recovery_plan`, a read-only mapping, and `recovery`, which is derived on
every load and never stored: `{"plan_digest", "recovers", "effect_snapshot", "selected",
"children"}`. `effect_snapshot` and `selected` come from the latest `recovery_started` (null and empty before one),
and `children` lists linked child ids in link order (D12).

### Sweep fixture

The executor builds a recovery declaration from each shape through a new helper,
`recovery_declaration(profile, registry)`:

- `effects` maps each binding to its adapter's supported modes.
- Each publication and activation node becomes a unit with the same `name` and `parameters` as
  its proof unit, `effect` = its binding, `operation` = its mode and `posture` from the
  profile's `recovery.units`. The profile's top-level `recovery.posture` is not a core input.
- A restorable unit gets `anchor` = `{predicate: rollback_anchor, parameters: {expected_subject:
  <anchor>}}` and `compatibility` = the same with predicate `compatibility`.
- Each profile edge becomes an edge with `operation` = its `op`, `parameters` =
  `{mode: <op>, unit: <node id>, expected_subject: <anchor or {}>}` and its `residue`.

A router observer dispatches each check to its collector's adapter hook. It maps an adapter
`absent` to `unsatisfied`, reason `anchor_absent`.

In every scenario the executor calls `verify_anchors` after acquiring custody in `ready`, and a
refusal parks the transaction like any other. The five new scenarios carry `recover: True`.
After a park, and only then, the executor runs one recovery step:

1. It issues grant `recovery-1` and calls `begin_recovery`.
2. On `no_effect`, it advances to `abandoned`.
3. On `unit_not_restorable` or `restore_incompatible`, it calls `roll_forward`, passing the
   refusal reason as `reason` and creation key `<shape>:<scenario>:forward`. The child's subject
   is the parent's with `candidate` suffixed `-forward`, and it reuses the shape's declarations.
   The parent stays parked.
4. On any other refusal, it stays parked.
5. Once admitted, it drives each selected edge as `run_phase` drives a node, then calls
   `settle_recovery`.

The earlier ten scenarios carry no `recover`, so they park exactly where #207 committed (D13).

Two scenario mutations join the fixture. `unsupported_operation` ports `dc98ba9`'s
`_add_unsupported_publication`: a publication node `unsupported_promote`, mode `promote`, on the
first binding whose adapter does not offer `promote`, with a `manual_only` recovery entry.
`irreversible_migration` declares that a forward-only migration rides the shape's first
activation unit: its posture becomes `supersedable_only`, with no anchor, compatibility or
edges (D14).

#### Expected landings

`ACT_PARK` and `SUCCESS` are #207's. `ROLLED` = `ACT_PARK` + `recovering, rolled_back`.
`ABANDON` = `created, awaiting_verification, ready, attention_required, abandoned`. A
roll-forward cell ends with `roll_forward_linked` as its last event, carrying the refusal reason.
Its parent holds only `lease_acquired`, and it has no `recovering` and no edge action. The child
is in `created`, with a distinct id and `recovers` naming the parent. Every forward action is
invoked at most once, and every edge exactly once.

| Scenario | Shape | Final | Path | Asserted beyond path |
|---|---|---|---|---|
| rollback | platform | rolled_back | ROLLED | snapshot: `build_closure`, `tag_release` target_satisfied, `switch_host_a` diverged, `switch_host_b` no_effect; selected: `build_closure` compensate, `tag_release` compensate, `switch_host_a` restore, `switch_host_a` compensate; compatibility checked for `switch_host_a`; restored [`switch_host_a`]; residue units [`build_closure`, `tag_release`, `switch_host_a`]; custody acquired, released |
| | product | rolled_back | ROLLED | snapshot: `build_image`, `index_channel` target_satisfied, `deploy_api` diverged, `deploy_admin`, `converge_fleet` no_effect; selected: `build_image` compensate, `index_channel` restore, `deploy_api` restore; restored [`index_channel`, `deploy_api`]; residue units [`build_image`] |
| | daemon | rolled_back | ROLLED | snapshot: `build_helpers`, `stage_helpers` target_satisfied, `install_job` diverged, `restart_job` no_effect; selected: `build_helpers` compensate, `stage_helpers` restore, `install_job` restore; restored [`stage_helpers`, `install_job`]; residue units [`build_helpers`] |
| | library | succeeded | SUCCESS | fault inapplicable (no activation); no recovery step |
| irreversible_migration | platform | attention_required | ACT_PARK | refused `unit_not_restorable` naming `switch_host_a`, no compatibility checked; roll-forward cell; `anchors_verified` lists only `switch_host_b` |
| | product | attention_required | ACT_PARK | refused `unit_not_restorable` naming `deploy_api`; roll-forward cell; anchors: `index_channel`, `deploy_admin`, `converge_fleet` |
| | daemon | attention_required | ACT_PARK | refused `unit_not_restorable` naming `install_job`; roll-forward cell; anchors: `stage_helpers`, `restart_job` |
| | library | succeeded | SUCCESS | fault and mutation inapplicable (no activation unit) |
| incompatible_restore | platform | attention_required | ACT_PARK | refused `restore_incompatible` naming `switch_host_a`; roll-forward cell |
| | product | attention_required | ACT_PARK | refused `restore_incompatible` naming `index_channel`; roll-forward cell |
| | daemon | attention_required | ACT_PARK | refused `restore_incompatible` naming `stage_helpers`; roll-forward cell |
| | library | succeeded | SUCCESS | fault inapplicable |
| missing_rollback_anchor | platform | abandoned | ABANDON | `verify_anchors` refused `rollback_anchor_missing` naming `switch_host_a`, and the park's reason names it; no action declared, no invoke; `begin_recovery` refused `no_effect`; custody acquired, released |
| | product | abandoned | ABANDON | the same, naming `index_channel` |
| | daemon | abandoned | ABANDON | the same, naming `stage_helpers` |
| | library | succeeded | SUCCESS | no restorable unit, so the verification is vacuous |
| unsupported_operation | platform | refused at creation | — | `RecoveryPlanRejected` `unsupported_operation` naming `unsupported_promote` on binding `nix`; the root holds no index, directory or lock; no invoke |
| | product | refused at creation | — | the same, on binding `api` |
| | daemon | refused at creation | — | the same, on binding `job` |
| | library | refused at creation | — | the same, on binding `index` |

**Departures from the prototype's printed landings** (`drive.py` at `dc98ba9`):

- `rollback` and `unsupported_operation` keep their landings: the same units restored, the same
  residue, the same refusal and the same binding. `missing_rollback_anchor` keeps `ABANDONED`
  and library `SUCCEEDED`. The refusal now happens in `ready`, before publication, instead of
  in the prototype's preflight, which ran after authorization.
- `incompatible_restore` `FAILED` becomes a roll-forward cell parked in `attention_required`.
  The prototype disposed `failed` citing a stub successor. That disposition is #209's, and #83
  keeps the parent open while the child's path is live.
- `irreversible_migration` `SUCCEEDED` is redefined. The prototype's row exercised #84's
  one-action confirmation of irreversible effects, which is not in this slice. This slice's row
  exercises the issue's first criterion instead: an irreversible unit is refused rather than
  restored (D14).

#### Earlier rows

All forty earlier cells keep their final states, paths, custody events, attempt counts and
voided forms. Every history now also holds one `anchors_verified` in `ready` (none for
library), which no earlier assertion reads.

### Documentation

CLAUDE.md's sentence on `agent_tools.transaction_core` names slice 5 and the two new modules,
still caller-less until #125. The #204–#207 specs are point-in-time records and stay unedited.

## Test seams

The three existing seams stay, and none is added (D16):

1. **Store interface plus its documented layout**, under a temporary root, a fake clock, fake
   effects and fake observers (#207 D20). This seam carries the acceptance criteria:
   - Irreversible units. An affected `compensatable` unit reaches `rolled_back` through its
     compensate edge alone: no restore action exists for it, `restored` omits it and `residue`
     cites it. An affected `supersedable_only` or `manual_only` unit makes `begin_recovery`
     refuse `unit_not_restorable`, with bytes unchanged and the observer never called. A
     non-restorable unit declaring a `restore` edge is `posture_violation` at creation.
   - Refusal before mutation. `verify_anchors` with an `unsatisfied` or `unknown` anchor refuses
     `rollback_anchor_missing` with bytes unchanged. `ready → publishing` is refused without
     `anchors_verified` under the held fence, including after a reacquisition. Every
     `RecoveryPlanRejected` reason leaves the root's listing unchanged.
   - Roll-forward. The child's id differs from the parent's and its `created.recovers` names
     the parent. The parent's pre-link events serialize byte-identically after the link, and
     its state is unchanged. A retry after a simulated death between child creation and link
     links exactly once, and a repeated link to the same child writes nothing.
   - Immutability. A same-key `create` with another recovery declaration is `CreationConflict`
     with bytes unchanged, and a hand-edited `recovery_plan` or `recovery_plan_digest` is
     `StateInvalid`.
   - Also every `RecoveryRefused` reason, including a stale grant from before the parking; the
     `abandoned` gate after an effect; `advance` into `recovering` or `rolled_back`, or with a
     reserved reason; `not_selected` in both directions; each `settle_recovery` case, including
     `recovery_incomplete` with `unknown` external state and a re-begun recovery that keeps a
     satisfied edge; the v5 validator by hand-edited documents; and v4 refused.
2. **Fixture executor against the store**: the asserted sweep, now fifteen scenarios by four
   shapes, against the committed table above.
3. **Neutrality checker** over all nine transaction modules.

Recovery tests go in new test files beside the proof tests, which join `just
agent-workflow-tests`, split so that each file stays under the review member cap. Earlier test
files change only where the schema string, the required `recovery` argument and the new
`recovering`, `rolled_back` and `abandoned` gates demand it.

## Out of scope

- `failed` and its positive ground, `no_recovery_disposition`, closing a parent after its
  child succeeds, and `effects_unobservable` (#209, #94).
- `rollback_receipt`, terminal receipts, and target-identity proof at a common cutoff after a
  restore (#209).
- A profile-declared recovery dependency DAG, and parallel recovery. Edges run in the order
  the caller drives them, and the core judges only their outcomes (D18).
- Anchor retention, pinning and tombstone receipts (#83 retention, #72).
- #84 authorization content: grant scope, expiry, spend and actor class; one-action
  confirmation of irreversible effects; a fresh attempt after an exhausted edge.
- Data-epoch and migration-event tracking beyond the declared compatibility check.
- Driving the child transaction, and cross-repository composition (#87, a deferred rejection).
- Effect classes, adapter `describe`, versions and certification (#85); inferring posture from
  them.
- Automatic reconciliation inside the core: it refuses until the caller has inspected.
- The attempts cutover (#125); any command-table row, Nix or host change.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Two new pure modules: `transaction_recovery_plan` (declaration schema, vocabularies, `compile_recovery`, `bind_recovery`, materialize, validator inverse) and `transaction_recovery` (event rules, effect snapshot and selection, operation admission, settlement, gates, view); both join the neutrality check. | #207 D1 plan/proof split; the-bar single responsibility; agent-helpers rule 1. | Growing `transaction_plan`/`transaction_proof` (proof and recovery change for different reasons) or one recovery module mixing compile-time and history rules. |
| D2 | `create` requires a `recovery` declaration with no default (empty `{"effects": {}, "units": []}`); recovery units must be exactly the proof units by `(name, parameters)`, else `unit_mismatch`. | #83 "every effectful unit declares its posture before mutation"; #207 D2; bootstrap "no project policy is defaulted". | Postures folded into the proof declaration (would change the sealed `transaction-proof-plan/v1`) or an optional argument (a forgotten posture would silently recover nothing). |
| D3 | The posture vocabulary is #83's `restorable \| compensatable \| supersedable_only \| manual_only`; the issue's "compensable" is read as `compensatable`, and its "irreversible" as any non-restorable posture; a fixture `effect_class` is not a core input. | #83 resolution (the decision source); the shapes fixture's spelling; #85 owns effect classes. | Adding an `irreversible` posture or an effect-class flag (a second word for "no restore edge", and #83 closed the set). |
| D4 | Posture rules fix edges: restorable = one leading restore edge plus optional compensate edges, with anchor and compatibility; compensatable = compensate edges only; the other two = none; every compensate edge predeclares a non-empty `residue`; an edge is an action named by its operation. | #83 restore/compensate semantics, "rolled_back may cite only predeclared bounded residue", no best-effort unit; prototype edge shape at `dc98ba9`; #206 D4 action ids. | Residue computed at settle time from outcomes (undeclared residue #83 forbids) or edges as a separate non-action mechanism (a second write-intent protocol). |
| D5 | Effects are declared per handle with an operations list; each unit names its effect and forward operation; `compile_recovery` runs before `compile_proof`, then `bind_recovery`; reasons `malformed`, `posture_violation`, `unknown_effect`, `unsupported_operation`, `unit_mismatch`, `unsupported_check`, first failure wins; anchor/compatibility predicates must be listed by the unit's (deterministic) proof collector. | #207 D5 (collectors declare supported predicates); issue "unsupported operation refused before mutation"; prototype `resolve` checks modes before proof; #88 model judgments advise only. | Detecting unsupported operations at invoke through the effect's `unsupported_operation` error class (discovered during mutation, which the issue forbids) or a separate checker handle for anchors (a third handle kind). |
| D6 | The materialized `transaction-recovery-plan/v1` is stored top-level with `recovery_plan_digest` on `created`; the validator accepts it only as the byte-identical re-materialization of its own declaration; a same-key create with a different digest is `CreationConflict`; no replace operation. | #83 immutable schema-versioned plan; #207 D3, D24; agent-helpers rule 4. | Re-deriving on load from a stored declaration (the plan would not be the digest-addressed artifact) or a mutable plan with an audit trail (#83 forbids change). |
| D7 | `verify_anchors` runs in `ready`, observes every restorable unit's anchor through the caller's observer, and writes `anchors_verified` or refuses `rollback_anchor_missing` with nothing written; `ready → publishing` is gated on an `anchors_verified` under the entering fence; resumes are ungated. | #83 "preflight must accept a fresh rollback_readiness snapshot immediately before the first release mutation"; #207 D12 gate precedent; #205 fence as freshness. | Checking anchors at recovery time (discovered after mutation) or gating the first `invoke_action` (a refusal inside `publishing` changes the lifecycle first). |
| D8 | `begin_recovery` admission order: state, fresh grant (issued since the current parking began), reconciliation under the held fence, `undeclared_effect`, `effect_uncertain`, `no_effect`, `unit_not_restorable`; then compatibility observed per affected restorable unit, refused `restore_incompatible`; effect classes are #83's minus `effect_present`; the selection is every edge of every affected unit; `recovery_started` plus the transition is the durable write-intent. | #83 attention first, read-only reconciliation, fresh grant, unknown never selects an action, compatibility before restore, no down migration; #205 grants; #206 two-hold call pattern. | Core-run reconciliation (the core would loop over effects itself) or selecting only restorable units (compensatable units would leave undeclared residue). |
| D9 | `settle_recovery` is the only way into `rolled_back`: all selected edges `satisfied` seals `recovery_settled` (restored units plus declared residue) with the terminal and lease release in one write; a diverged, unknown or unretryable edge parks `recovery_incomplete`; else `recovery_pending`; a restore goal is its edge's own `satisfied` inspection. | #207 D10 (a single core judge); #83 partial recovery emits no rollback, completed facts are kept; #206 D7 inspection semantics. | Caller-driven `advance` with a predicate (caller-cited residue) or requiring a rollback receipt now (receipts are #209). |
| D10 | `advance` refuses `recovering`, `rolled_back` and the reserved reasons; `abandoned` from any source needs `no_effect` (every action, forward or edge, declared or not, without effect); the pairings are validated, and the validator re-derives the selection through the writer's function. | #82 "abandoned only when no release effect exists"; #207 D10, D27, D31 pairing and DRY-validator precedent. | Leaving `abandoned` ungated (the core would accept a false terminal) or adding an abandon outcome to `settle_recovery` (a second path to one gate). |
| D11 | `roll_forward` creates the child through the ordinary create path with `recovers` on its `created` event, then appends `roll_forward_linked {child_transaction_id, grant_id, reason, fence}` to the parent under a second hold; the parent lock is never held across creation; it is idempotent per child; the parent stays `attention_required`; the child is not driven. | #83 linked child with its own candidate, grants and proof, the parent stays open; #82 a terminal never reopens; #206 D3 two-hold pattern; lock order of `create`. | Holding the parent lock across child creation (deadlocks against a create of the parent's key) or mutating the parent's subject (the issue forbids it). |
| D12 | The schema becomes `transaction-state/v5` (top-level `recovery_plan`, `created.recovery_plan_digest` and `recovers`, five new fenced events); v4 fails closed; `Transaction` gains `recovery_plan` and a derived `recovery` view. | #207 D13, #205 D9 (no caller, so no older state); #205 D20 derived views. | Additive events under v4 (its closed dispatch would meet unknown types). |
| D13 | The sweep executor recovers only in scenarios flagged `recover`, so the ten earlier rows keep #207's parked landings. | #93 non-convergence never auto-rolls-back; #83 recovery needs a fresh grant; #207 D11 dispositions are explicit steps; the issue's "earlier rows still pass". | Recovering after every park (would silently rewrite #207's committed table and turn a stall into a rollback). |
| D14 | Row definitions: `rollback` = `failed_activation` recovered; `incompatible_restore` adds `restore_incompatible`; `missing_rollback_anchor` parks in `ready` and abandons through `no_effect`; `unsupported_operation` ports `_add_unsupported_publication` with a `manual_only` entry; `irreversible_migration` is redefined as the first activation unit declared `supersedable_only` (a forward-only migration rides it) under `activation_failure`; both refusal rows link a roll-forward child and stay parked. | The issue's first criterion and demo; the prototype scenarios at `dc98ba9`; #83 (supersedable_only or an incompatible epoch authorizes a child); #84 confirmation is out of scope. | Keeping the prototype's `irreversible_migration` (it tests #84's confirmation, and would land `succeeded` without touching recovery) or `FAILED` for `incompatible_restore` (#209's disposition). |
| D15 | `EFFECT_STATES` gains `recovering`; `InvocationRefused` gains `not_selected` for a non-selected action in `recovering` and for a plan edge outside it; recovery edges otherwise inherit #206's intent, inspection and budget unchanged. | #83 "recovery actions inherit #82 limits", deterministic recovery action ids, inspection protocol; #206 D5–D7. | A separate recovery invocation operation (a second copy of the write-intent protocol). |
| D16 | Keep the three seams (store with fake clock, effects and observers; asserted sweep; neutrality); `RecoveryPlanRejected` and `RecoveryRefused` with closed reasons and one construction path each; recovery tests in new files sized under the member cap. | #207 D18, D20, D23; #206 D21; the-bar "tests that can fail". | Tests over module internals, or one refusal class per reason. |
| D17 | Pure halves live in the two new modules; `transaction_core` gains only thin wrappers and stays within the 65536-byte review member cap, with the exact budget set by the plan. Amends #207 D22's 55000-byte ceiling, which the base (53375 bytes) leaves no room under. | #207 D22, #205 D33 review member cap; the-bar single responsibility. | Judging recovery inside `TransactionStore` (breaks the cap) or a new store class (a second store surface for one lifecycle). |
| D19 | Grill: a recovery or roll-forward grant must postdate the latest transition into `attention_required` (not the parked run's start); the `recovery_started` map is named `effect_snapshot` (#83's term, distinct from the declaration's `effects` handles); both two-hold operations refuse a grown history as `history_changed`; an action with no intended attempt is `no_effect` whatever it inspects. | #83 a failed or uncertain edge needs a new grant; `parked_since` spans `recovering → attention_required`; #206 D5 the core's only effect path is behind intent; #82 abandoned only when no release effect exists. | Parked-run freshness (would let one grant authorize a second recovery epoch) or inspection-based effect classes (a pre-existing target state would force a restore of something the transaction never changed, and would refuse a truthful `abandoned`). |
| D18 | No recovery dependency DAG or parallel recovery in this slice: selected edges are an ordered list the caller drives, and the core judges only their outcomes. | YAGNI; no sweep row needs ordering; #83's DAG is additive later (a new plan field under a new plan schema). | Porting #83's full DAG now (untested structure with no consumer). |
| D20 | Plan: `transaction_core.py` ends every task at most 64000 bytes (D17's exact budget) and each touched file's cumulative `git diff -U10 f999226` stays under 65536; `verify_anchors` and `begin_recovery` share one private two-hold helper whose zero-request case decides in the first hold, and all judgment lives in the pure modules. | D17; #207 D22 review member cap; the-bar DRY. | A copy of the two-hold pattern per operation (about 3 KB more core, and one change made twice). |
| D21 | Plan: a residue that does not match its edge action (null for `restore`, a non-empty string for `compensate`) and any shared action identity are `malformed`; each compile rule runs over every unit before the next rule; `unsupported_operation`'s detail names the unit, the operation and the effect handle; check results are shape-checked only (non-empty `reason` and `reference`), secret-freedom staying the caller's contract as for #207 observations. | Spec "Compilation and rejection"; #207 D26 rule order; no secret scanner exists in the transaction modules. | Residue mismatch as `posture_violation` (the posture table does not govern residue) or a new secret scanner (a second, unowned policy). |
| D22 | Plan: `invoke_action` refuses `not_selected` right after `state_not_effectful` and before the satisfied no-op, through one pure `selection_refusal` that the validator also applies to every `invocation_intended`; recovery's advance and transition rules run after the existing `unresolved` terminal check, so #206's messages keep precedence. | D15; D10; #207 D27 precedence. | Letting a satisfied non-selected action return a no-op in `recovering` (a forward action would cross the recovery boundary silently). |
| D23 | Plan: recovery events name units by action id (`anchors`, `checks`, `effect_snapshot`, `restored`, `residue`), and every `RecoveryRefused` naming a unit says `<name> (<action id>)`; the sweep maps ids to names through `proof_plan.units`, records each recovery refusal's message in `World.notes`, and `drive` lets `RecoveryPlanRejected` propagate. | #206 D4 ids are the stable handle; the spec's sweep table names units. | Names in events (edge names repeat across units) or a new refusal attribute (widens the closed error shape). |
| D24 | Plan: three new test files (`test_transaction_recovery_plan`, `test_transaction_recovery`, `test_transaction_recovery_settle`) share one `RecoveryCase`; `test_transaction_core` drops the `recovering` source and the `rolled_back` terminal, which `advance` can no longer reach, and the custody parking-window test moves into `recovering` through `begin_recovery`; a death between child creation and link is simulated by a second store whose clock lapses once the child's creation-key index exists. | D16; the spec's seams (store plus documented layout, no private patching). | Patching `_create` (a private name) or keeping hand-built `recovering` paths (the pairing refuses them). |
