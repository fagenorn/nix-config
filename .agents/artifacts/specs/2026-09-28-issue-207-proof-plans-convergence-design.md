# Transaction core 4/6: proof plans, obligations and the convergence cohort

Design for [#207](https://github.com/fagenorn/nix-config/issues/207), slice 4 of 6 of
[#123](https://github.com/fagenorn/nix-config/issues/123), 2026-09-28, against main `488e95f`.
Written in autonomous mode: every choice below is an agent judgment inside the issue's
delegated scope, recorded in the decision ledger, not a human answer.

## Problem

Slices 1–3 (#204, #205, #206) give a transaction a closed lifecycle, fenced custody and a safe
way to cause effects, but nothing decides whether the effects worked. Any caller may advance
`proving → succeeded` whenever it likes, and `published` or `proving` may be entered while an
action is still diverged. The settled decisions need more before a consumer can trust a
`succeeded`:

- #88 fixes one immutable `proof_plan` per transaction, derived at creation. It also fixes the
  five profile semantics (`liveness | readiness | product_smoke | observability |
  rollback_readiness`), the three evidence forms, the adapter outcomes
  `satisfied | unsatisfied | unknown`, the evaluations
  `accepted | rejected | indeterminate | not_applicable | unsupported` and one
  `proof_cutoff_at`. Model judgments may only advise.
- #91 adds the core-derived identity floor as a disjoint `derived_obligation_class`
  (`published_artifact_identity`, form `event`; `running_subject_identity`, form `snapshot`),
  which a profile may never author. A profile that names one is rejected when it is compiled.
- #93 makes convergence a pre-mutation feasibility check plus a single cutoff cohort. A stall
  becomes the nonterminal `proof_did_not_converge`, distinct from `proof_rejected` and never an
  automatic rollback.

The prototype (`prototype-release-transactions/` at `dc98ba9`) showed what goes wrong without
these rules. A healthy release was rolled back, or failed on a burned version, because its
snapshot set could not converge (NOTES finding 2). Its floor carried a semantic outside the
closed set (finding 1).

## Solution

Every transaction gets a **proof plan** at creation. The caller passes a closed **proof
declaration**: the units it will act on, the obligations it wants proven, and the collectors
that observe them. The core compiles the declaration before taking any lock. Compilation rejects
a derived class, a reserved predicate, an unsupported or model-judged required obligation, an
undeclared latency or an infeasible cohort, and nothing is written. The core then materializes
the plan under the new transaction id: it adds the two derived classes per unit and computes the
cohort schedule. It stores the plan once, with its digest pinned in the `created` event.

Proof runs through three new fenced store operations, all in `proving`:

- `collect_obligation` makes the external observation itself, with no lock held, as #206's
  `inspect_action` does, and records it with the measured latency.
- `start_cohort` opens the one re-collection barrier.
- `settle_proof` is the single judge. It seals `proof_cutoff_at` and enters `succeeded`, parks
  `proof_rejected`, records a failed cohort, or parks `proof_did_not_converge`. It never enters
  `recovering`.

`advance` can no longer reach `succeeded`. `published` and the entry to `proving` are gated on
the plan's units being satisfied.

Two options were weighed for who decides the proof outcome (D10):

- **The core judges and moves the lifecycle in `settle_proof` (chosen).** The cutoff, the
  evaluation and the terminal transition happen in one write under one fence, as #88/#93
  require. The two parkings are typed by the core, so a caller cannot label a stall as a
  rejection or turn either one into a rollback.
- **Pure evaluation that the caller reads before calling `advance`.** Slices 1–3 keep the
  lifecycle caller-driven (#206 D8). Here, though, the cutoff and the transition would be two
  writes that another fenced write could slip between, and the typed reason would be free text.

A third option was rejected: letting the caller hand in outcomes, as `record_evidence` does
today. The core could then neither measure collection latency (#93 `collection_bound_exceeded`)
nor ensure that the observation followed its commit point.

## Decisions

### Modules

Two pure modules join the package (D1):

- `agent_tools.transaction_plan` holds the proof declaration's closed schema, the vocabularies
  and core caps, `compile_proof` (tx-independent validation and rejection), `materialize_plan`
  (adds derived obligations under a transaction id), the cohort makespan and the plan digest.
- `agent_tools.transaction_proof` holds the proof event rules the history validator calls, the
  obligation evaluation at a given cutoff, the cohort fold, the phase gates, and the snapshot's
  `proof` view.

Neither module reads a file, lock or clock. `transaction_core` gains the store operations and
re-exports the new public names. The import order becomes core → history → proof → plan →
invocation → custody → storage. Both modules are standard-library only, have no command-table
row, are import-checked by the Nix build, and join the neutrality check.

### The proof declaration

`create(creation_key, subject, *, concurrency_keys, proof)` gains a required `proof` keyword. It
has no default: a transaction with nothing to prove passes the explicit empty declaration
`{"units": [], "obligations": [], "collectors": {}}` (D2). The declaration is a strict,
secret-free JSON object with these closed keys:

| Key | Content |
|---|---|
| `units` | list of `{name, parameters, phase, collector}`. `phase` is `publication` or `activation`. `name`/`parameters` are exactly what the caller will pass to `invoke_action`, so the unit's action id is #206's `action_id(transaction_id, name, parameters)`. |
| `obligations` | list of `{id, semantic, form, predicate, collector, required, deps, parameters, freshness_ms}`. `freshness_ms` is required exactly for `form: snapshot`. |
| `collectors` | map from handle to `{basis, predicates, max_collection_latency_ms, max_concurrent_collections}`. `basis` is `deterministic` or `model`; `predicates` lists the predicate handles the collector supports; the concurrency cap is optional and defaults to 1 (serial, #93). |
| `convergence_window_ms` | optional; defaults to 1 800 000 and may not exceed 7 200 000 (#93) |

A unit's `collector` observes its derived identity obligations. Collector handles and predicates
are opaque strings to the core, the way action names are (#206), which keeps the core
provider-neutral.

### Compilation and rejection (before any write)

`compile_proof(declaration)` runs in `create`'s argument check, before the creation lock and
before any index, directory or state file exists. A refusal is `ProofPlanRejected` with one
`reason` from this closed set (D4, D5, D18):

- `malformed`: any shape, type or closed-key violation, an unknown semantic, form, phase or
  basis, or a duplicate unit name + parameters.
- `derived_class_named`: an obligation whose `semantic` is a derived class, which carries a
  `derived_class` or `obligation_kind` key, or whose `id` starts with `derived:`.
- `reserved_predicate`: a declared obligation whose predicate is `publication_visible` or
  `running_subject_identity`.
- `unknown_collector`, `duplicate_id`, `unknown_dependency`, `dependency_cycle`.
- `required_unsupported`: a required obligation whose collector does not list its predicate, or
  a unit whose collector does not list its phase's reserved predicate (#91 conformance per
  capable mode).
- `required_model_judgment`: a required obligation, or any unit, bound to a `model` collector
  (#88).
- `latency_out_of_bounds`: a latency or freshness that is absent where required, not positive,
  or above its core cap.
- `infeasible_cohort`: the cohort's makespan plus margin exceeds its governing window or the
  convergence window.

A `deps` entry names a declared obligation id, or a derived one written as
`derived:<class>:<unit name>` (#91: a profile may depend on the floor but never author it).

### Materialization and the stored plan

After the id is minted, `materialize_plan(compiled, transaction_id)` produces the stored
`proof_plan`. It is a closed object with schema `transaction-proof-plan/v1`,
`convergence_window_ms`, `units` (each with its `action_id`), `collectors`, `obligations` and
`cohort` (D3).

The obligations are listed in one stable topological order: publication derived, then
activation derived, then declared, each group in declaration order. Each obligation carries
`obligation_id`, `obligation_kind` (`profile_declared` or `core_derived`), `semantic` and
`derived_class` (exactly one of them non-null), `form`, `predicate`, `collector`, `required`,
`deps`, `parameters` and `freshness_ms`.

Each unit gets one derived obligation, `derived:<class>:<action_id>`, with `required: true` and
no deps (#91 dependency roots):

- a publication unit gets `published_artifact_identity`: form `event`, predicate
  `publication_visible`;
- an activation unit gets `running_subject_identity`: form `snapshot`, predicate
  `running_subject_identity`, `freshness_ms` = the core constant 600 000 (#91: core policy, not
  authorable).

Its `parameters` are the unit's `name` and `parameters`. Declared deps written against a unit
name are rewritten to these ids.

`cohort` records the members, `makespan_ms`, `margin_ms` and `governing_window_ms` (below). The
plan's `telemetry_digest` is stored as `proof_plan_digest` on the `created` event. The validator
requires the top-level `proof_plan` to be a valid materialized plan for this transaction id that
hashes to that digest. The `created` event is the first entry of an append-only history, so no
later write can replace the plan.

There is no replace operation. A repeated `create` with the same creation key compiles and
materializes the new declaration under the existing id. If its digest differs, `create` raises
`CreationConflict` naming the proof plan, and nothing is written. That is the "attempt to
replace it is refused" criterion.

### Feasibility: the cohort schedule

The cohort's members are the required `snapshot` obligations, in plan order. Events never
re-collect, closed intervals are never re-run, and advisory ones never gate (#93). The makespan
is a deterministic list schedule. Each member starts at the later of two times: when its
snapshot prerequisites among the members finish, and when a slot of its collector frees up under
`max_concurrent_collections`. It runs for its collector's `max_collection_latency_ms`, and the
makespan is the latest finish.

`margin_ms = max(ceil(makespan × 20 / 100), 5 000)`. The governing window is the smallest member
`freshness_ms`. The plan is feasible when `makespan + margin ≤ governing window` and
`makespan + margin ≤ convergence_window_ms`. An empty cohort has makespan 0, the floor
margin and a null governing window, and is always feasible; its seal has no window check. Because the plan
is immutable, feasibility is decided once, at compile time. Nothing in the plan can change on
resume (D9).

The core caps are `MAX_COLLECTION_LATENCY_MS` 300 000, `MAX_FRESHNESS_MS` 7 200 000,
`MAX_COHORT_ATTEMPTS` 3, `COHORT_MARGIN_PERCENT` 20, `COHORT_MARGIN_FLOOR_MS` 5 000,
`RUNNING_IDENTITY_FRESHNESS_MS` 600 000, `DEFAULT_CONVERGENCE_WINDOW_MS` 1 800 000 and
`MAX_CONVERGENCE_WINDOW_MS` 7 200 000 (D19).

### Collecting an obligation

`collect_obligation(custody, *, obligation_id, observer)` runs only in `proving` (D7). The
`observer` is any object with a callable `observe(request)`. The request is a read-only mapping
of `transaction_id`, `obligation_id`, `predicate`, `collector`, `parameters`, `fence` and
`cohort` (the open cohort's number, or null).

The operation takes the lock twice, like `inspect_action` (#206 D3):

- **First hold.** Refuse a terminal, run the fenced check, then apply the admission rules below.
  Read the clock as `started`. For an `interval` obligation, append `interval_opened` under the
  minted evidence id, so the core witnesses the start (#205 D15). Release the lock.
- **The call.** Run `observer.observe` with no lock held. The result must be exactly
  `{outcome, reason, reference}`: `outcome` in `satisfied | unsatisfied | unknown`, and
  `reason` and `reference` non-empty, secret-free strings. For a derived obligation, a
  non-`satisfied` reason must belong to its class's closed space from #91. Anything else is
  `EffectResultInvalid` with nothing recorded (D18).
- **Second hold.** Repeat the terminal refusal and the fenced check. Then append
  `obligation_observed`: `obligation_id`, `evidence_id` (`<obligation_id>@<n>`, numbered by the
  core), `form`, `outcome`, `reason`, `reference`, `fence`, `cohort` and
  `latency_ms = now − started`.

Whatever the observer raises propagates; an interval it leaves open reads
`fence_discontinuity` or stays unclosed, and the next collection mints a new id.

Admission, as `ProofRefused` with a closed `reason` before any write or call:

- `state_not_proving` outside `proving`;
- `unknown_obligation`;
- `unsupported_obligation` when the collector does not list the predicate, which only an
  advisory obligation can reach;
- `dependency_not_accepted` unless every dep evaluates `accepted` now (#88 topological order,
  with a rejected or indeterminate prerequisite suppressing collection);
- `already_accepted` for an `event` or `interval` obligation that is already `accepted` (events
  never re-collect);
- inside an open cohort, `not_cohort_member` for anything that is not a member of that cohort.

Every observation joins the snapshot's `evidence` entries under its `evidence_id`, with #205's
admissibility unchanged. An `event` survives reacquisition; a `snapshot` is voided by a fence
change; an `interval` needs continuity (D6).

### Evaluation

`evaluate(plan, events, cutoff_ms)` is pure and gives each obligation exactly one evaluation and
one reason (D8). It walks the plan's topological order:

1. If any dep is `rejected` or `indeterminate`, the obligation is `indeterminate` with reason
   `dependency_suppressed`.
2. An advisory obligation whose collector does not list its predicate is `unsupported`.
3. Otherwise it uses the obligation's latest `obligation_observed`:
   - none: `indeterminate`, `evidence_missing`;
   - not admissible: `indeterminate`, `fence_lost`;
   - a `snapshot` with `cutoff_ms > observed_at + freshness_ms`: `indeterminate`,
     `evidence_stale`;
   - otherwise `satisfied` is `accepted`, `unsatisfied` is `rejected` with the observer's
     reason, and `unknown` is `indeterminate` with `unreachable`.

`not_applicable` stays in the closed vocabulary but nothing in this slice produces it: #88
reserves it for phase receipts, which are slice 6's. Advisory evaluations never park or block.
The seal lists those that are not `accepted` as `advisory_warnings`, and a `model`-basis
collector can only ever sit behind an advisory obligation (D5).

### The cohort and `settle_proof`

`start_cohort(custody)` runs in `proving` and appends `proof_cohort_started {cohort, fence}`. The
first attempt is cohort 1. It is refused (`ProofRefused`) in these cases:

- `proof_incomplete` unless every required obligation has been accepted at least once: it has an
  admissible `satisfied` observation, whatever its age (#93 barrier).
- `cohort_open` while a cohort is open under the held fence. A cohort left open under an older
  fence is first closed by an appended `proof_cohort_failed {reason: fence_changed}`, which
  counts as a used attempt: reacquisition restarts the cohort but not the budget (#93).
- `convergence_exhausted` when `MAX_COHORT_ATTEMPTS` cohorts were used, or when the time left
  in the convergence window is below `makespan_ms + margin_ms`. The window starts at the `at` of
  the history's first transition into `proving`, and parks never reset it.

`settle_proof(custody)` runs in `proving`. It takes one clock reading, which is the candidate
`proof_cutoff_at`, and one write decides the first matching case in order (D10, D11):

1. **Rejected.** If any required obligation evaluates `rejected` at the cutoff, it appends
   `proof_rejected {obligations, fence}` (the rejected ids in plan order), then a transition
   `proving → attention_required` with reason `proof_rejected` and external state `known`.
   Authoritative disproval dominates whether or not a cohort is open.
2. **Seal.** A cohort is open under the held fence. Every member has an observation recorded in
   this cohort, the cutoff is no more than `governing_window_ms` past the cohort's start and
   inside the convergence window, and every required obligation evaluates `accepted`. It then
   appends `proof_sealed {cohort, proof_cutoff_at, makespan_ms, governing_window_ms,
   advisory_warnings, fence}`, the transition `proving → succeeded` with external state `known`,
   and #205's terminal `lease_released`.
3. **Cohort failed.** A cohort is open and case 2 fails. It appends `proof_cohort_failed
   {cohort, reason, fence}`. The reason is the first that applies of `fence_changed`,
   `cohort_expired` (past the governing window, or a member not fresh at the cutoff),
   `member_missing` (a member with no observation in this cohort; a pre-cohort snapshot never
   counts), `collection_bound_exceeded` (a member observation over its collector's declared
   latency, #93) and `member_indeterminate`. It then falls through to case 4.
4. **Exhausted.** No cohort is open and the budget or window is exhausted as `start_cohort`
   judges it. It appends `proof_convergence_exhausted {cohorts, exhausted_by: budget | window,
   fence}` and the transition `proving → attention_required` with reason
   `proof_did_not_converge` and external state `known`.
5. **Nothing to decide.** After case 3 with budget left, it returns the snapshot and the caller
   may start the next cohort. With no open cohort and budget left, it is refused
   `ProofRefused` `no_open_cohort`.

Before any write, `settle_proof` refuses a terminal entry as `advance` does (#206 D9): if an
`inspect_action` made in `proving` left some action `open`, `in_progress` or `unknown`, case 2 is
`TransitionRefused` naming that action, and nothing is recorded (D21). `settle_proof` never
enters `recovering`, `failed`, `rolled_back` or `abandoned`, and it never invokes anything. The dispositions #93 lists (a fresh budget under #84 authorization, #83
rollback, `abandoned`, `failed`) are the caller's later explicit steps (D11).

`proof_rejected` and `proof_did_not_converge` are **reserved transition reasons**. Their events
must be immediately followed by the matching transition, and a `proving → attention_required`
transition carrying either reason must be immediately preceded by its event. The same pairing
binds `proof_sealed` to `succeeded`.

### Lifecycle gates

Pure predicates in `transaction_proof`, used by both `advance` and the validator (D12):

- entering `published` needs every publication unit's action to have latest status `satisfied`;
- `activating → proving` needs every activation unit satisfied;
- `published → proving` needs a plan with no activation unit (the declared `activation: none`
  path);
- `succeeded` is reachable only through `settle_proof`: `advance(…, "succeeded")` is
  `TransitionRefused` whatever its source, and the validator refuses a `succeeded` transition
  not immediately preceded by `proof_sealed`.

A resume from a parking to its `parked_from` passes through no gate. With the empty declaration
every gate is vacuous, so the earlier slices' store tests keep their paths.

### Transaction state `transaction-state/v4`

The schema moves to v4, and a v3 document fails closed naming its version, by #205 D9's reasoning
(D13). The changes:

- a new top-level key, `proof_plan`;
- `created` gains `proof_plan_digest`;
- six new fenced event types: `obligation_observed`, `proof_cohort_started`,
  `proof_cohort_failed`, `proof_convergence_exhausted`, `proof_rejected`, `proof_sealed`.

Interval obligations reuse `interval_opened`. The validator re-checks everything that needs no
clock:

- event closed shapes and fences inside an open span;
- `obligation_observed` only in `proving`, of a plan obligation, with the core's evidence
  numbering;
- cohort numbering from 1, at most `MAX_COHORT_ATTEMPTS`, one open at a time;
- seal membership: every member observed in the sealing cohort;
- the reserved-reason pairings and the phase gates.

Freshness is judged at write time on the store clock, because `at` is not monotonic (#205 D3).

`Transaction` gains `proof_plan` (a read-only mapping) and `proof`, which is derived on every
load and never stored: `{"plan_digest", "obligations", "cohorts", "proof_cutoff_at"}`.

- Each `obligations` entry reports `obligation_id`, `obligation_kind`, `semantic`,
  `derived_class`, `form`, `required`, `observations`, `latest_outcome` and
  `latest_admissible`.
- Each `cohorts` entry reports `cohort`, `status` (`open | failed | sealed`) and `reason`.

The view carries no clock-dependent evaluation, as with #206's `retry_deadline_at`.

### Sweep fixture

The executor now drives proof through the core. It builds a proof declaration from each shape:

- each node becomes a unit with its binding as collector;
- each `proof` entry becomes an obligation, with `temporal` as form and seconds scaled to ms;
- each binding becomes a collector whose `predicates` are its adapter's supported predicates,
  with `basis` `deterministic`, `max_collection_latency_ms` 30 000 and no concurrency cap.

One observer per binding wraps the adapter's predicate hooks and maps a hook's prose reason onto
a stable token (a derived obligation's onto its class space: identity mismatches to
`subject_mismatch`). The executor then works in this order:

1. Collect every plan obligation in plan order through `collect_obligation`, skipping advisory
   unsupported ones and any refused `dependency_not_accepted`.
2. `start_cohort`, then collect every member. A `proof_incomplete` or `convergence_exhausted`
   refusal goes straight to step 3, which parks a rejection or an exhausted budget.
3. `settle_proof`, repeating from step 2 while `settle_proof` leaves the transaction in `proving`;
   any `ProofRefused` parks with its reason.

It still parks on a non-`satisfied` action view or an invocation refusal, as in #206. Two faults
join the world:

- `slow_collection` (`expired_snapshot`): every cohort collection moves the world clock 250 s,
  beyond its declared 30 s; the executor renews custody after each one.
- `stale_health`, `partial_publication`, `activation_failure`, `member_stale`: ported unchanged
  from `dc98ba9`.

Five scenarios join `SCENARIOS`. Every row is asserted against a freshly loaded store (D14).

#### Expected landings

Path names: `SUCCESS` is the success row's path (`library` without `activating`); `PUB_PARK` =
`created, awaiting_verification, ready, publishing, attention_required`; `ACT_PARK` = the path
through `activating, attention_required`; `PROOF_PARK` = the path through
`proving, attention_required`. Every parked cell holds its single `lease_acquired` custody and no
`lease_released`.

| Scenario | Shape | Final | Path | Asserted beyond path |
|---|---|---|---|---|
| partial_publication | platform | attention_required | PUB_PARK | `build_closure` satisfied; `tag_release` diverged, 1 invoke; no activation action declared; no obligation observed |
| | product | attention_required | PUB_PARK | `build_image` satisfied; `index_channel` diverged, 1 invoke; same absences |
| | daemon | attention_required | PUB_PARK | `build_helpers` satisfied; `stage_helpers` diverged, 1 invoke; same absences |
| | library | attention_required | PUB_PARK | `upload_artifact` satisfied; `bind_version` diverged, 1 invoke; same absences |
| failed_activation | platform | attention_required | ACT_PARK | publication satisfied; `switch_host_a` diverged, 1 invoke; `switch_host_b` undeclared |
| | product | attention_required | ACT_PARK | `deploy_api` diverged, 1 invoke; `deploy_admin`, `converge_fleet` undeclared |
| | daemon | attention_required | ACT_PARK | `install_job` diverged, 1 invoke; `restart_job` undeclared |
| | library | succeeded | SUCCESS | fault inapplicable (no activation); identical to `success` |
| stale_false_positive_health | platform | attention_required | PROOF_PARK | reason `proof_rejected`; rejected = identity of `switch_host_a`, `switch_host_b`; no cohort |
| | product | attention_required | PROOF_PARK | rejected = identity of `deploy_api`, `deploy_admin`; `api_liveness`, `admin_liveness` observed `satisfied`; no cohort |
| | daemon | attention_required | PROOF_PARK | rejected = identity of `install_job`, `restart_job`; `job_liveness` observed `satisfied`; no cohort |
| | library | succeeded | SUCCESS | fault inapplicable (no running subject) |
| expired_snapshot | platform | attention_required | PROOF_PARK | reason `proof_did_not_converge`; 3 cohorts, each failed `cohort_expired`; `exhausted_by: budget`; no `recovering`, no invoke after the park |
| | product | attention_required | PROOF_PARK | 2 cohorts failed `cohort_expired`; `exhausted_by: window`; same absences |
| | daemon | attention_required | PROOF_PARK | 2 cohorts failed `cohort_expired`; `exhausted_by: window`; same absences |
| | library | succeeded | SUCCESS | the cohort has no member (identity is `event`); 1 cohort, sealed |
| fleet_stall | platform | succeeded | SUCCESS | fault inapplicable |
| | product | attention_required | ACT_PARK | `converge_fleet` `in_progress`, 1 invoke, never re-invoked; no obligation observed |
| | daemon | succeeded | SUCCESS | fault inapplicable |
| | library | succeeded | SUCCESS | fault inapplicable |

The cohort counts follow from the plan's arithmetic. A cohort takes `members × 250 s`:

- platform: 3 members, makespan 90 s + margin 18 s;
- product: 6 members over 3 collectors, makespan 90 s + margin 18 s;
- daemon: 5 members over 2 collectors, makespan 90 s + margin 18 s.

The governing window is 600 s and the convergence window 1 800 s from entry to `proving`.

**Departures from the prototype's printed landings** (`drive.py` at `dc98ba9`):

- Every prototype `ROLLED_BACK` becomes the park above: platform/product/daemon
  `failed_activation` and `stale_false_positive_health`, product/daemon `partial_publication`,
  and product/daemon `expired_snapshot`. The prototype's autopilot ran #83 recovery, which is
  slice 5's (#208). #82 and #88 keep a rejected or unfinished release in `attention_required`
  while a recovery exists, and the fixture carries no recovery (#204 D6).
- library `partial_publication` `FAILED` becomes a park, because a `failed` disposition needs
  #83/#94's positive ground (slices 5–6).
- library `expired_snapshot` `FAILED` becomes `succeeded`. #91 makes publication identity an
  `event`, so the shape has no snapshot to expire, and #93 forbids non-convergence from ever
  sealing `failed`.
- platform `expired_snapshot`: the prototype's park reason (`required proof not accepted at
  cutoff`) becomes the typed `proof_did_not_converge` after a bounded budget (#93).
- `partial_publication` platform, `fleet_stall` (all four shapes) and the library cells of
  `failed_activation`/`stale_false_positive_health` keep their prototype landings.

#### Earlier rows

`success`, `lease_renewal`, `throttled_retry`, `lease_lapse` and `resume_after_crash` keep their
final states, paths, custody events and attempt counts; each now seals through a cohort. One
column changes: library `lease_lapse` voids `∅` instead of `{snapshot}`, because its only
required evidence is publication identity, which is now an `event` (#91) and survives the
reacquisition (D15). Every other voided-forms cell is unchanged, and product and daemon still
exercise all three forms before the lapse.

### Documentation

CLAUDE.md's sentence on `agent_tools.transaction_core` names slice 4 and the two new modules,
still caller-less until #125. The #204–#206 specs are point-in-time records and stay unedited.

## Test seams

The three seams of #204–#206 stay, and none is added (D20):

1. **Store interface plus its documented layout**, under a temporary root, a fake clock, fake
   effects and **fake observers**: in-memory callables whose returned outcomes and advancing
   clock are the observable side, never a call log. This seam carries these criteria:
   - Derived-class rejection (every `derived_class_named` form, `reserved_predicate`,
     `required_model_judgment`, `required_unsupported`) raises `ProofPlanRejected` with the
     root's directory listing unchanged: no index, directory, lock or event.
   - Replacement: a same-key `create` with another declaration is `CreationConflict` with bytes
     unchanged, and a hand-edited `proof_plan` or digest is `StateInvalid`.
   - Infeasible cohort: a 590 s latency against a 600 s window raises `infeasible_cohort` before
     any write.
   - Non-convergence: a cohort whose observer outruns its window fails `cohort_expired`, budget
     exhaustion parks `proof_did_not_converge`, and the history holds no `recovering` and no
     invocation after the park.
   - Stale health: a satisfied snapshot recorded before the cohort makes `settle_proof` fail the
     cohort `member_missing`, and a cohort member older than its freshness at the cutoff fails
     it `cohort_expired`. Neither can seal.
   - Every `ProofRefused` reason; the gates on `published`/`proving`/`succeeded`; the advisory
     model obligation that warns but never blocks; latency and `collection_bound_exceeded`;
     reacquisition failing an open cohort `fence_changed` without resetting the budget;
     `EffectResultInvalid` for a bad observation or an out-of-space derived reason; the v4
     validator by hand-edited documents; v3 refused.
2. **Fixture executor against the store**: the asserted sweep, now ten scenarios by four
   shapes, against the committed table above.
3. **Neutrality checker** over all seven transaction modules.

Proof tests live in a new test file beside the invocation tests, which joins
`just agent-workflow-tests`. Earlier test files change only where the schema string, the required
`proof` argument and the `succeeded` gate demand it.

## Out of scope

- `recovery_plan`, rollback and restore execution, and invoking from `recovering` (#83, slice 5,
  #208).
- `failed` with `effects_unobservable` and human-only assertion (#94).
- Terminal receipts and their store writes, and the phase receipts behind `not_applicable`
  (slice 6, #209).
- `active_probe` collectors: probes are release actions under #84 authorization and spend, so
  this slice accepts only passive observers.
- A fresh cohort budget after exhaustion (#84 authorization).
- Refusing `invoke_action` on actions outside the plan's units, and unit-membership conformance
  (#85/#124 profile resolution).
- Adapter `describe`, versions and certification, and the doctor surface for
  `collection_bound_exceeded` (#69, #85).
- Target-membership snapshots and `membership_drift`, evidence conflict resolution beyond
  latest-wins-per-obligation (`evidence_conflicting`), and `adapter_or_policy_changed`.
- `single_term` lease coverability of the window (adapter slice).
- #84 activation observation deadlines, which `fleet_stall` would need to end on its own (#124).
- The #87 parent cutoff (deferred rejection).
- The remaining unported sweep scenarios; the attempts cutover (#125); any command-table row,
  Nix or host change.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Two new pure modules: `transaction_plan` (declaration schema, vocabularies, caps, compile, materialize, makespan, digest) and `transaction_proof` (proof event rules, evaluation, cohort fold, gates, view); import order core → history → proof → plan → invocation → custody → storage; both join the neutrality check. | the-bar single responsibility (compiling a profile and judging history are two reasons to change); #205 D33 / #206 D1 keep pure models out of the capped core; agent-helpers rule 1. | Growing `transaction_core`/`transaction_history` (both near the review member cap) or one proof module mixing compile-time and history rules. |
| D2 | `create` requires a `proof` declaration with no default; a transaction with nothing to prove passes the explicit empty declaration, making every gate vacuous. | #88 "one proof_plan derived at creation" for every transaction; bootstrap "no project policy is defaulted"; the-bar fail loud. | An optional argument defaulting to an empty plan (a forgotten plan would silently prove nothing). |
| D3 | Compile (tx-independent, all rejections) before any lock, then materialize under the minted id; the plan is stored top-level with its `telemetry_digest` on the `created` event; a same-key create with a different plan digest is `CreationConflict`; no replace operation exists. | #88 immutable digest-addressed plan; #91 derived ids `derived:<class>:<action_id>` need the transaction id (#206 D4); #204 D4 dedup; agent-helpers rule 4. | Storing only the declaration and re-deriving on load (the plan would not be the digest-addressed artifact) or a digest in the creation index (a second file to keep in step). |
| D4 | A declaration naming a derived class (as `semantic`, a `derived_class`/`obligation_kind` key, or a `derived:` id) or binding a reserved predicate is rejected at compile time with a typed reason; declared deps may reference `derived:<class>:<unit name>`, rewritten at materialize. | #91 classification, "may name a derived id as prerequisite", reserved predicate handles; #207 criterion 1. | Silently dropping or renaming the derived entry (a runtime carve-out #91 rejects) or forbidding derived deps (#91 allows them). |
| D5 | Collectors are declared per handle with a supported-predicate list, `basis` `deterministic`/`model`, mandatory capped `max_collection_latency_ms` and an optional concurrency cap (default 1); a required or unit obligation on an unsupported predicate or `model` basis is rejected; advisory unsupported evaluates `unsupported`; only passive observers exist this slice. | #88 unsupported only for advisory, model judgments advisory only; #91 mandatory reserved-handle support; #93 mandatory latency, serial default; #84 governs probes. | A per-obligation `supported` flag (support is a collector fact) or accepting `active_probe` now (needs authorization and spend gates that do not exist). |
| D6 | The core calls a per-call `observer` with no lock held, measures latency on its clock, mints `<obligation_id>@<n>` evidence ids, opens intervals itself, and records a new `obligation_observed` event that joins the existing `evidence` view under #205 admissibility. | #206 D3 precedent (core makes the call); #93 `collection_bound_exceeded` needs a core-measured latency; #205 D15 intervals witnessed by the core; #88 envelope binds obligation, outcome, reason. | Caller-reported outcomes through `record_evidence` (latency and ordering unverifiable) or a separate evidence ledger (a second admissibility rule). |
| D7 | Obligations are collected only in `proving` and only once every dep is `accepted`, so evidence structurally follows every action's commit point; an accepted `event`/`interval` is never re-collected. | #88 relational freshness and topological DAG evaluation; #93 events never re-collect; phase gates (D12) make `proving` post-activation. | Tracking a per-obligation commit-point seq (the same guarantee with more rules). |
| D8 | Evaluation is pure at a cutoff: dependency suppression, `unsupported`, then latest observation → `evidence_missing`, `fence_lost`, `evidence_stale`, or outcome mapping (`unsatisfied`→`rejected`, `unknown`→`indeterminate/unreachable`); derived non-satisfied reasons must be in #91's class spaces; `not_applicable` stays reserved for slice 6 phase receipts. | #88 evaluation vocabulary; #91 reason spaces; the-bar fail loud. | Emitting `not_applicable` for the missing activation phase now (a receipt concept with no consumer) or free-form core reasons. |
| D9 | The cohort's members are the required snapshots; the makespan is a deterministic list schedule under per-collector caps along snapshot dep chains, margin `max(20 %, 5 s)`, feasible iff within both the governing (minimum) freshness and the convergence window; decided once at compile, since the plan is immutable. | #93 makespan, margin, one cohort, re-check only because inputs could change (here they cannot). | Measured latency (#93 forbids it as an admissibility input) or a re-check on resume (identical inputs, untestable branch). |
| D10 | `settle_proof` is the only way into `succeeded` and the only producer of the typed parkings `proof_rejected` and `proof_did_not_converge`; one write fixes `proof_cutoff_at` with the transition; `advance` refuses `succeeded`; reserved reasons and seal pairings are validated. | #88 "fix one cutoff … seal atomically under the lock"; #93 distinct typed nonterminal, never auto-rollback; the-bar truthful terminal states. Narrows #206 D8 (the protocol never moves the lifecycle) for this judgment, as `reap` already does. | Caller-driven `advance` after a pure evaluation (two writes, free-text reasons, a caller could roll back on a stall). |
| D11 | The convergence window runs from the first entry into `proving`; the budget of 3 cohorts is durable across parks and reacquisitions (an open cohort under an old fence fails `fence_changed` and counts); rejection dominates; `settle_proof` never enters `recovering` or another terminal; no fresh-budget operation this slice. | #93 whole-plan window, budget, reacquisition restarts the cohort not the budget, dispositions are explicit; #84 owns fresh authorization. | Resetting the window or budget on resume (launders an exhausted budget, which #93 forbids) or an auto-disposition. |
| D12 | Pure phase gates shared by `advance` and the validator: `published` needs every publication unit satisfied, `activating → proving` every activation unit, `published → proving` a plan with no activation unit; resumes to `parked_from` are ungated; invoking undeclared actions stays allowed. | #206 out-of-scope hands "gating published/succeeded on the action set" to slice 4; #82 activation-none path; #206 D20 validator mirrors `advance`. | Gating every forward edge (breaks empty-plan store tests for no gain) or refusing undeclared invocations now (unit-membership conformance is #85/#124's). |
| D13 | The schema becomes `transaction-state/v4`: top-level `proof_plan`, `created.proof_plan_digest`, six fenced proof events; v3 fails closed without migration; `Transaction` gains `proof_plan` and a clock-free derived `proof` view. | #205 D9 / #206 D2 (no caller, so no v3 state); #205 D20 derived views. | Additive events under v3 (a closed v3 dispatch would meet unknown types). |
| D14 | Five sweep rows with the committed landing table above; `slow_collection` slows only cohort collections by 250 s against a declared 30 s and the executor renews after each; `fleet_stall`, `failed_activation` and `partial_publication` park through the executor's existing non-`satisfied` rule; inapplicable faults land on the success path. | #207 demo; prototype scenarios at `dc98ba9` (`tick: 250`); #204 D6 (the executor grows as the core does). | Slowing every collection (a pre-cohort window exhaustion that never exercises the cohort budget) or porting the prototype's recovery to reach its printed terminals (slice 5). |
| D15 | library `lease_lapse` now voids `∅` instead of `{snapshot}`; every other earlier cell keeps its landing. | #91 `published_artifact_identity` is `event`; #92 events survive reacquisition. | Keeping the floor as `snapshot` to preserve the old cell (contradicts #91). |
| D16 | The criterion "health evidence captured before the proof cutoff cannot satisfy an obligation" is carried two ways. In the row, satisfied health never outweighs a rejected running identity. In the store seam, a pre-cohort or over-age snapshot cannot seal (`member_missing`, `cohort_expired`). | #88 freshness at the cutoff, expired evidence recollected never extended; #91 identity never satisfied by liveness; prototype scenario note. | Asserting only the row (the cutoff rule itself would be untested) or only the store seam (the demo row would prove nothing new). |
| D17 | `fleet_stall` parks from `activating` on the first `in_progress` view with the fleet action never re-invoked; ending the stall on a deadline stays #124's observation-deadline work. | #206 D10 defers observation deadlines; #206 D9 no terminal over `in_progress`; prototype printed the same nonterminal park. | Inventing a core observation deadline here (#84/#124 policy). |
| D18 | New refusals `ProofPlanRejected` (closed `reason`, before any lock or write) and `ProofRefused` (closed `reason`, before any write or call) under `TransactionError`; an out-of-shape observation reuses `EffectResultInvalid`. | #204 D9, #206 D7 typed refusals with closed reasons; #206 D21 fail-loud reason construction. | One class per reason, or `StateInvalid` for plan rejection (indistinguishable from a corrupt file). |
| D19 | Core constants: latency cap 300 s, freshness and convergence-window cap 2 h, default window 30 min, 3 cohort attempts, margin 20 % / 5 s floor, running-identity freshness 600 s. | #93 defaults and caps; #91 identity freshness is core policy; fixture freshness 600 s. | Profile-declarable budget or identity freshness (#91 forbids tightening the floor; #93 fixes the budget). |
| D20 | Keep the three seams; fake observers are in-memory callables asserted by outcomes and clock, never call logs; one new proof test file. | #205 D23, #206 D13; the-bar tests assert observable behaviour. | Tests over module internals (they bind the tests to the module split). |
| D21 | Grill: `settle_proof`'s seal is refused `TransitionRefused` with nothing written while any action is `open`, `in_progress` or `unknown`, because `inspect_action` stays legal in `proving` and can re-open reality after the phase gates passed; the parkings are unaffected. | #206 D9/D20 no terminal over unresolved reality, enforced by `advance` and the validator alike; #82 unknown is never terminal. | Trusting the phase gates alone (a later inspection in `proving` could make the seal claim success over an unknown action). |
