# Transaction core 2/6: fenced custody — leases, epoch/term, evidence invalidation, grant fences

Design for [#205](https://github.com/fagenorn/nix-config/issues/205), slice 2 of 6 of
[#123](https://github.com/fagenorn/nix-config/issues/123), 2026-09-28, against main `66ccba5`.
Written in autonomous mode: every choice below is an agent judgment inside the issue's delegated
scope, recorded in the decision ledger, not a human answer.

## Problem

Slice 1 (#204) shipped a caller-rooted store of closed-schema transactions with a closed
lifecycle, but anyone may advance any transaction at any time: there is no notion of *who* holds
a transaction's concurrency keys, for how long, or since when. The settled decisions need exactly
that before any later slice can admit a side effect:

- #82 requires exclusive, fenced leases over an immutable set of concurrency keys before the first
  mutating action, and lease loss or a stale fence must stop work before another effect.
- #92 splits the fence into an ownership generation (`lease_epoch`) and an extension counter
  (`lease_term`), makes renewal a core duty that never enters history, and defines what an epoch
  change does to evidence and authorization. The prototype (`prototype-release-transactions/` at
  `dc98ba9`) had one counter bumped on every acquisition, so each renewal voided its own proof
  (its finding 3), and its takeover re-stamped the old authorization with the new epoch, carrying
  authority across a custody gap.
- #117 binds custody to the exact subject path, refuses a stale holder's write, and keeps an
  authentic late owner result beside a reaper's synthesized stop instead of dropping either.

Without these, the attempts cutover (#125) would have to fence owners in adapter code again — the
split authority #117 D1 exists to remove.

## Solution

Extend the transaction core with **fenced custody**: a local lease authority under the store's
root that owns one lease record per concurrency key, and a transaction-side custody projection
folded from typed custody events. A holder receives a `Custody` credential from `acquire` and
presents it on every fenced write; the core checks it against the lease authority's clock and the
transaction's current fence under the transaction lock, and refuses before any write when it is
stale or bound to another subject path.

Renewal extends a lease in place and bumps only its term, writing only the lease record, so
history and `state.json` are untouched. Any acquisition bumps the epoch and appends one custody
event. Evidence, intervals and grants carry the fence snapshot the core stamped when they were
recorded; their admissibility is derived on every load by comparing that snapshot with the custody
events that followed, so voiding is a computed verdict over an unedited history.

Two options were weighed for where lease truth lives (D2):

- **A root-level lease authority beside the transactions, with the transaction holding only a
  folded fence projection (chosen).** Concurrency keys are shared across transactions, so
  exclusivity must be decided above any one transaction; the authority record is the single home
  of expiry and term, and renewal never touches transaction state.
- **Leases inside each transaction's `state.json`.** Two transactions naming the same key could
  never see each other's lease, so exclusivity would need a scan of every transaction, and every
  renewal would rewrite transaction state.

A third, a pluggable lease-mechanism interface with the local authority as one implementation, was
rejected as speculative: #85's adapter conformance (acquire/renew/release/inspect, `single_term`)
arrives with the adapter slice, and the first consumer (#125) runs on one host.

## Decisions

### Modules

The custody concern is a second reason to change the store, so it gets its own module (D1):

- `agent_tools.transaction_core` keeps the public surface: `TransactionStore`, `Transaction`,
  `Custody`, the vocabularies and every error class. It owns the lifecycle fold and the
  transaction-state validator, now covering custody events.
- `agent_tools.transaction_custody` owns the local lease authority (lease records, the lease lock,
  epoch/term/expiry arithmetic, the renewal margin) and the pure admissibility fold for evidence
  and grants.
- `agent_tools.transaction_storage` receives slice 1's durable-file primitives unchanged (strict
  JSON read, atomic replace, non-blocking lock open, `lstat`/`O_NOFOLLOW` guards) and the error
  hierarchy, so both modules share one home. `transaction_core` re-exports the errors; its import
  surface is a superset of slice 1's.

All three stay standard-library only, have no command-table row, and are covered by the Nix build's
recursive import check. The neutrality check extends to all three modules.

### Clock

`TransactionStore(root, *, clock=None)` takes one clock: a zero-argument callable returning integer
Unix milliseconds; `None` means the wall clock. It is the **lease authority's clock** (#92): every
expiry decision and every event `at` come from it, so slice 1's timestamp function becomes a
formatter over this clock rather than a second time source (D3). Tests inject a fake clock and
move it explicitly. `at` stays non-monotonic by contract; ordering is still `seq`.

### Concurrency keys and subject path

`create(creation_key, subject, *, concurrency_keys)` gains a required keyword: a non-empty
collection of distinct non-empty strings, stored sorted as the immutable `concurrency_keys` (#82's
immutable canonical key set; which keys a consumer names is its policy, not the core's). A repeated
create with the same key must match both subject and keys, else `CreationConflict` (D4).

The subject path is bound by the **first** acquisition: an absolute path string equal to its own
`os.path.normpath`, compared by exact string equality. Every later acquisition, fenced write and
late result must present the same path, else `CustodyMisbound` before any write. The core never
resolves or touches the path (it writes only under `root`); canonicalising a worktree path is the
caller's job (D5).

### Lease authority

Under the store root the authority adds:

```
<root>/leases.lock                    stable lock serializing lease-record writes
<root>/leases/<sha256>.json           one record per concurrency key ever acquired
```

A lease record is the closed object `transaction-lease/v1`: `schema`, `key`, `epoch` (integer ≥ 1,
the key's ownership generation, retained forever), and `holder` — null, or the closed object
`transaction_id`, `executor_id`, `instance` (`lin_` + 32 lowercase hex from `secrets`), `term`
(integer ≥ 1), `ttl_ms`, `acquired_at`, `expires_at`, `renewal_count`, `last_renewed_at` (integer
milliseconds, the last null until the first renewal). A lease is **live** while
`clock() < expires_at`; an expired holder is not cleared, it simply stops counting (D6).

The four #92 mechanism operations, all over the transaction's whole key set as one group:

- **acquire** — all-or-nothing. If any key is live-held (by anyone, including this transaction's
  current custody), nothing is written and `LeaseUnavailable` is raised. Otherwise every key gets
  `epoch + 1` (a first acquisition gets `1`), a fresh `instance`, `term 1`, `expires_at = now +
  ttl_ms`. Every acquisition is by definition discontinuous, so every acquisition — first,
  after release, after lapse, by the same executor or another — advances the epoch (#92 "takeover
  is not privileged over self-reacquisition").
- **renew** — in place, only while live and only by the recorded instance: bumps `term` and
  `renewal_count`, sets `last_renewed_at` and `expires_at = now + ttl_ms`, keeps `epoch` and
  `instance`. It extends only once remaining validity is below the renewal margin, `min(ttl_ms,
  max(ttl_ms // 2, 60000))` (#92's default: half the TTL, floor 60 s); outside the margin it is a
  no-op that writes nothing. A lapsed lease is never renewed: renewal fails rather than silently
  reacquiring.
- **release** — sets `holder` to null, keeping `epoch`, on exactly the records that still name the
  releasing span's `instance`; a record another transaction has since taken is never touched (D24).
- **inspect** — `store.inspect_lease(key)` returns a read-only view of the record, or `None` for a
  key never acquired. It is the only public window onto `term`, expiry and renewal counts.

Because one lock serializes every record and the group is taken all-or-nothing, the local authority
never holds some keys while waiting on others, which is the deadlock #92's hold-and-try rule
forbids; the per-key partial reacquisition half of that rule needs a mechanism whose keys lapse
independently, and arrives with the adapter slice (D7).

**Lock order and crash order (D8).** A custody operation takes the transaction lock, then the lease
lock, both non-blocking (`TransactionBusy` on contention). Acquisition writes the lease records
first and the transaction second; release and quiesce write the transaction first and the records
second; renewal writes only records. A crash between the two writes therefore leaves at most a lease
the transaction never recorded, which blocks its keys until it expires by its TTL and was never
handed to any holder — the transaction never claims custody the authority did not grant.

### Transaction state `transaction-state/v2`

Slice 1's `transaction-state/v1` gains two keys and nine event types, so the schema string moves to
`transaction-state/v2`. A v1 document fails closed with `StateInvalid` naming its version: the
module has had no caller (#204 D1), so no v1 state exists outside tests, and a migration would be
code for data that cannot exist (D9). The creation index stays `transaction-creation-key/v1`.

New keys, both part of the closed set:

| Key | Type | Rule |
|---|---|---|
| `concurrency_keys` | array | non-empty, sorted, distinct non-empty strings; immutable |
| `custody` | object or null | the fold's current custody: `executor_id`, `subject_path`, `fence`; null when none is held |

A **fence** is the ordered map `{key: {"epoch": int, "instance": str}}` over every concurrency key.
Evidence, intervals and grants carry the fence of the custody that recorded them. #92 populates a
fence snapshot "only from keys covering that item's scope"; because the local authority acquires,
renews and lapses the whole group together, every key's epoch moves together, a narrower scope is
unobservable, and each snapshot therefore covers the full key set (D10).

New event types, each a closed object carrying `seq`, `type` and `at` plus:

| Type | Fields | Written by |
|---|---|---|
| `lease_acquired` | `executor_id`, `subject_path`, `fence` | first acquisition |
| `lease_reacquired` | `executor_id`, `subject_path`, `fence`, `prior_executor_id`, `prior_fence`, `reason` (`released` or `expired`) | every later acquisition |
| `lease_released` | `fence`, `reason` (`released`, `quiesced` or `terminal`) | release, quiesce, terminal advance |
| `lease_lapse_detected` | `fence`, `executor_id` | reap, or acquisition over an unreaped lapse |
| `stop_synthesized` | `fence`, `executor_id`, `reason` | reap |
| `owner_result` | `executor_id`, `fence`, `custody` (`current` or `stale`), `supersedes` (a `stop_synthesized` seq or null), `result` | late-result intake |
| `evidence_recorded` | `evidence_id`, `form` (`event`, `snapshot`, `interval`), `reference`, `fence` | record evidence |
| `interval_opened` | `evidence_id`, `fence` | open interval |
| `grant_issued` | `grant_id`, `actor`, `fence` | issue grant |

The **custody events** — the four `lease_*` types — are exactly #92's epoch-affecting facts; a
renewal appends none (#92's `lease_renewal_failed` has no local cause, since a live local lease
always renews). Every custody span is delimited by events: it opens with `lease_acquired` or
`lease_reacquired` and closes with `lease_released` or `lease_lapse_detected`, and an acquisition
over custody that lapsed unreaped appends `lease_lapse_detected` before its `lease_reacquired`.
The validator folds these into the stored `custody` projection exactly as it folds `state`, and
additionally requires: a custody span opens only when none is open; `lease_reacquired`'s
`prior_fence` equals the last span's fence and every key's epoch strictly increases; every span
carries the subject path the first one bound; no custody is open after a terminal; `evidence_id`
is unique across `evidence_recorded` and `interval_opened` events except for an interval's own
open/close pair, whose close follows exactly one open
`interval_opened` of the same id; `grant_id` is unique; and every fence, evidence, grant and owner
result sits inside an open custody span whose fence it equals, except `owner_result`, whose fence
must equal some span's fence. `reference`, `actor`, `reason` and the opaque `result` object are
secret-free by caller contract (#72), like `subject`. `revision` still equals the event count, so a
renewal leaves it unchanged (D11).

### Custody credential and the fence check

`Custody` is a frozen, caller-constructible dataclass: `transaction_id`, `executor_id`,
`subject_path`, `fence`. `acquire` returns it inside the resulting snapshot (`transaction.custody`),
and a holder in another process may persist and rebuild it. It is an ordering token, not a secret:
fencing orders handovers (#92); authenticating executors is outside the core.

A **fenced write** runs, under the transaction lock and before anything else: the presented
`transaction_id`, `executor_id` and `fence` must equal the stored `custody` projection (none held,
or any difference, is `StaleCustody`); the presented `subject_path` must equal the bound path
(`CustodyMisbound`); and every key's lease record must name that `instance` and still be live on
the clock (`StaleCustody`). Only then do the operation's own rules run. A refusal writes nothing to
either store; in particular a write under a lease that silently expired is refused without
recording the lapse — recording it is the reaper's or the next acquirer's job (D12). The check
reads lease records without the lease lock and judges liveness at one clock reading taken under the
transaction lock; the write is ordered at that instant. Another holder can acquire only once that
clock reaches `expires_at`, so a write accepted at a live instant precedes every successor epoch,
and fenced writes across transactions never contend on one global lock (D25).

A span has **lapsed** when any key's record is expired on the clock or no longer names the span's
`instance` (another transaction acquired it after expiry); reap and acquisition use this one
predicate.

### Store operations

Every mutation returns the resulting `Transaction`; every refusal happens before any write.

- `acquire(transaction_id, *, executor_id, subject_path, ttl_ms)` — refused on a terminal
  (`TransitionRefused`), on a misbound path, or when any key is live (`LeaseUnavailable`, which also
  covers the transaction's own live custody: no new launch steals a valid lease, #117). Appends
  `lease_acquired` or, after earlier custody, `lease_reacquired` with `reason` `released` when the
  prior span closed by release or quiesce, `expired` when it lapsed (preceded by
  `lease_lapse_detected` when unreaped). Takeover by another executor is visible as differing
  `executor_id`s, not a separate reason (#92: semantics key to the epoch change).
- `renew(custody)` — the core's renewal duty (D13). A fenced call the holder's host loop makes on a
  tick; the core alone decides whether to extend (inside the margin), by how much (the recorded
  TTL), and whether custody must instead be quiesced. It writes only lease records and never an
  event. Callers never pass an expiry or a term.
- `release(custody)` — voluntary release: `lease_released` reason `released`, records cleared.
- `advance(transaction_id, target, *, reason, external_state=None, custody=None)` — slice 1's
  transition, now fenced from `publishing` on (D14): a transition whose target is `publishing`, or
  on a transaction whose history has entered `publishing`, or on one that currently holds custody,
  requires a valid `custody` (D26); other transitions take none, so verification of transactions sharing keys still runs concurrently
  (#82). A custody presented where none is required is still checked, never ignored. Entering a
  terminal appends `lease_released` reason `terminal` in the same write and clears the records: a
  terminal holds no custody.
- `record_evidence(custody, *, evidence_id, form, reference)` — fenced; stamps the current fence.
  For `interval` it closes the interval opened under that id.
- `open_interval(custody, *, evidence_id)` — fenced; the core witnesses where the span starts, so a
  caller cannot backdate it (D15).
- `issue_grant(custody, *, grant_id, actor)` — fenced; mints a grant for the current custody only
  (#117 D11), stamped with its fence. Grant scopes, expiry and consumption are #84's and later.
- `check_grant(custody, grant_id)` — fenced and read-only: refuses with `GrantInvalid` unless the
  grant exists and its fence equals the presented, current fence. A renewal leaves the fence
  unchanged, so a grant survives it; a reacquisition changes it, so an older grant is refused and
  is never re-stamped (the prototype's bug, D16).
- `reap(transaction_id, *, reason)` — the reaper's core-authority entry; takes no custody. When
  custody is held and has lapsed, one write appends `lease_lapse_detected`,
  `stop_synthesized` and, from an unparked nonterminal state, a transition to `attention_required`
  with `external_state` `unknown`. With no custody, or live custody, it writes nothing and returns
  the unchanged snapshot, so a sweep may call it on every transaction (D17).
- `record_owner_result(transaction_id, *, executor_id, subject_path, fence, result)` — the separate
  late-result intake (#117). The presented executor and fence must equal some custody span in the
  history (else `StaleCustody`: the core never issued that credential) and the path must equal the
  bound one (`CustodyMisbound`). It appends `owner_result` with `custody` `current` when that span
  is the open, live one and `stale` otherwise, and `supersedes` naming the latest
  `stop_synthesized` carrying that fence, if any. It changes neither lifecycle state nor custody:
  the result is retained as evidence, never as restored authority, and the stop event stays. A
  terminal transaction refuses it (`TransitionRefused`); post-terminal supplements are slice 6's
  (D18).

### Custody quiesce

While the transaction is parked (`attention_required` or `recovering`), `renew` keeps extending
only until the parking is older than the core cap `PARKED_CUSTODY_WINDOW_MS` (15 minutes), measured
on the clock from the `at` of the transition that entered the parking. Past it, `renew` instead
quiesces: `lease_released` reason `quiesced`, records cleared, and the returned snapshot has no
custody. Resuming into a custodial state then needs a fresh `acquire`, which is an ordinary
reacquisition: the epoch advances, older snapshots, intervals and grants lapse, event evidence
stays. #92's exception — never quiesce while an issued call is still observed — has nothing to
observe until write intent lands in slice 3, which must add it; a profile-declared window below the
cap arrives with profiles (#124) (D19).

### Evidence and grant admissibility

`Transaction` gains `concurrency_keys`, `custody` (a `Custody` or `None`), `evidence` and `grants`.
Each `evidence` entry reports `evidence_id`, `form`, `reference`, `fence`, `seq`, `admissible` and
`void_reason`; each `grants` entry reports `grant_id`, `actor`, `fence`, `seq` and `valid`. These
verdicts are derived on every load from the persisted events and never stored, so no write can make
the verdict and the history disagree (D20). With *latest fence* meaning the fence of the most
recent custody span:

| Form | Admissible when | `void_reason` otherwise |
|---|---|---|
| `event` | always (an immutable past fact under a then-valid fence; #92) | — |
| `snapshot` | its fence equals the latest fence | `fence_changed` |
| `interval` | no custody event lies between its `interval_opened` and its close, and its fence equals the latest fence | `fence_discontinuity` for a break inside the span, else `fence_changed` |

A grant is `valid` when its fence equals the latest fence and that span is still open. A superseded
record is never edited; recollection records a new `evidence_id`. "No custody event in the span"
is #92's positive, auditable continuity test. An interval opened under one span and closed under a
later one is recorded, not refused, and reads `fence_discontinuity`; the holder opens a new one.

### Errors

New refusals join slice 1's hierarchy under `TransactionError` (D21): `FenceViolation`, the base of
`StaleCustody` (no, stale or lapsed custody; an unissued late-result credential), `CustodyMisbound`
(subject path differs from the bound one) and `GrantInvalid` (unknown grant or a fence that is not
current); and `LeaseUnavailable` (a key is live-held). Argument shape errors on the new operations
(an empty id, a non-positive TTL, an unknown evidence form, a `result` that is not a strictly
round-tripping JSON object) are `StateInvalid` raised before any lock, as slice 1's create does.

### Sweep fixture

The fixture executor acquires custody before `ready → publishing`, using the shape's
`target.concurrency_keys` from the ported shape data, and presents it on every later advance. The
sweep store's clock is the simulated world's clock (seconds scaled to milliseconds). The executor
records one evidence item per collected obligation — its declared `temporal` form for profile
obligations, `snapshot` for the derived floor — opening an interval before observing an `interval`
obligation. The `success` row still lands every shape on `succeeded` along slice 1's paths, now with
one `lease_acquired` and one terminal `lease_released`.

Two scenarios join `SCENARIOS`, each with a row for all four shapes (D22):

- `lease_renewal` — the world clock moves into the renewal margin twice during proving and the
  executor renews each time, reading the lease record's `term` as 3 before sealing. Landing:
  `succeeded` on the success path; exactly two custody events in history (`lease_acquired` and the
  terminal `lease_released`); every evidence item admissible; every released lease record still at
  `epoch` 1.
- `lease_lapse` — after half the obligations are recorded, the clock passes expiry; the executor's
  next evidence write is refused with `StaleCustody`; the reaper reaps, parking the transaction in
  `attention_required`; the executor reacquires (epoch 2), resumes to `proving`, recollects every
  obligation whose record is no longer admissible, and seals. Landing: `succeeded` on the success
  path with `attention_required, proving` inserted before `succeeded`; every pre-lapse `snapshot`
  and `interval` record void with `fence_changed`, every pre-lapse `event` record admissible, and
  every obligation's latest record admissible.

The asserted table grows a third column, the expected set of voided forms per cell, and the test
still asserts against a reloaded store.

### Documentation

CLAUDE.md's "Agent helper package" sentence on `agent_tools.transaction_core` names the custody
slice and its two sibling modules, still caller-less until #125. New test files join
`just agent-workflow-tests`. The #204 spec is a point-in-time record and is not edited.

## Test seams

The slice keeps slice 1's three seams and adds no other (D23):

1. **Store interface plus documented layout**, under a temporary root and an injected fake clock:
   returned snapshots, raised errors, `inspect_lease` views and the bytes of `state.json` and lease
   records. It carries every acceptance criterion: lapse versus renewal (epoch, term, events,
   `state.json` bytes, evidence verdicts); a stale holder's `advance`, evidence and grant writes
   refused with both stores byte-identical; grant before renewal valid, grant before lapse refused
   after reacquisition; reap then an authentic late `owner_result` recorded with `stop_synthesized`
   kept, state unchanged and the stale holder still refused; a misbound path refused on acquire,
   fenced write and late result; quiesce past the window; concurrency-key conflict and lock
   contention; the v2 validator's new rules by hand-edited documents; v1 refused.
2. **Fixture executor against the store** — the asserted sweep table, now three scenarios by four
   shapes.
3. **Neutrality checker** over the source of all three transaction modules.

Custody tests live in a new test file beside `tests/test_transaction_core.py`; slice 1's tests are
updated only where the new required `concurrency_keys` and custodial advances demand it. No test
asserts that an internal helper was called.

## Out of scope

The slice-6 receipt that records the owner result and the stop together; write intent,
inspect-before-retry and in-flight observation (slice 3, including the quiesce exception for an
observed call); proof plans, `proof_cutoff_at` and sealing; #84 grant scopes, expiry and
consumption; lease-mechanism adapters, `single_term`, per-key renewal failure and hold-and-try's
partial reacquisition, and `lease_state_unknown` for an unreachable remote authority (#85's adapter
slice); profile-declared TTL, margin and parked window (#124); executor authentication; the #87
parent claim (deferred rejection); wiring into workflow-state, attempts or control (#125); any
command-table row, Nix or host change; state cleanup.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Custody lives in a new `agent_tools.transaction_custody`; slice 1's durable-file primitives and errors move unchanged to `agent_tools.transaction_storage`; `transaction_core` keeps and re-exports the public surface; all three are covered by the neutrality check. | the-bar single responsibility ("split when the second concern arrives") and DRY; agent-helpers rule 1; #204 D11. | Growing one module past a thousand lines, or a custody module importing private helpers from the core (a cycle and two homes). |
| D2 | A local, root-level lease authority (one record per concurrency key) is the truth for epoch, term and expiry; the transaction stores only a folded fence projection. No pluggable mechanism interface yet. | #92 "the lease authority stays the truth for expiry and the projection is a cache"; #82 disjoint key sets release concurrently; #85 adapter conformance is a later slice; YAGNI. | Per-transaction leases (no cross-transaction exclusivity without a scan) or a mechanism protocol now (one implementation, no caller). |
| D3 | One injected clock, integer Unix ms, is the lease authority's clock and also stamps every event `at`; `None` means the wall clock. | #92 "expiry is evaluated only on the lease authority's clock"; #205 demo's fake clock; the-bar single home. | A clock only for leases beside slice 1's wall-clock timestamps (two time sources whose readings a test could not align). |
| D4 | `create` takes a required `concurrency_keys` (non-empty, distinct, stored sorted, immutable) that deduplication compares with the subject. | #82 immutable canonical key set before the first mutation; core neutrality: keys are opaque strings. | Keys declared at first acquisition (mutable until then, and a dedup that ignores them) or keys read out of the opaque subject (the core would interpret the subject). |
| D5 | The first acquisition binds a normalized absolute subject path, compared by exact string; every later acquisition, fenced write and late result must match; the core never resolves it. | #117 custody binds exact worktree identity, misbinding refused as fencing, never relocated; #204 "never touches anything outside `root`". | Binding at create (a subject path may not exist yet) or `realpath` inside the core (reads outside `root`). |
| D6 | Lease record `transaction-lease/v1` keeps the key's epoch forever and a nullable holder with instance, term, TTL, expiry and renewal counters; an expired holder is inert rather than cleared. | #92 field list (`lease_epoch`, `lease_term`, `lease_instance_id`, `expires_at`, `renewal_count`, `last_renewed_at`). | Deleting a record on release (loses the epoch, so a later acquirer could reuse a generation). |
| D7 | Every lease operation covers the transaction's whole key set: all-or-nothing acquire (any live key is `LeaseUnavailable`, including the caller's own), group renew; every acquisition advances every key's epoch; per-key partial reacquisition waits for independently lapsing mechanisms. | #92 epoch rules, "takeover is not privileged", hold-and-try exists to avoid hold-and-wait; #117 "no new launch steals a valid lease". | Per-key acquisition (hold-and-wait deadlock) or letting the same executor re-take its own live lease (steals custody from its own live holder). |
| D8 | Transaction lock then lease lock, both non-blocking; acquisition writes records then state, release and quiesce write state then records, renewal writes records only. | #204 D10; #92 "a renewal whose durable write is lost is harmless"; crash safety. | Any other order, which can leave a transaction claiming custody the authority never granted. |
| D9 | The schema becomes `transaction-state/v2`; a v1 document fails closed naming its version, with no migration. Narrows #204 D5's migration clause. | #204 D1 (no caller, so no v1 state exists); #82 unknown schemas fail closed; YAGNI. | Loosening v1 (breaks #204 D5) or a v1→v2 migration (untestable against real data, and v1 has no concurrency keys to migrate). |
| D10 | A fence covers every concurrency key; per-item scopes narrower than the key set are deferred. | #92 scoping; D7 makes every key's epoch move together, so a narrower scope is unobservable and untestable. | Per-item scope keys now (a code path no test can turn red). |
| D11 | Nine closed event types; the four `lease_*` ones are the only custody events, renewal appends none, every custody span is delimited by events, and the validator folds and cross-checks custody like `state`; `revision` stays the event count. | #92 ledger asymmetry and "absence of an epoch event" test; #204 D5 projection validation. | Recording renewals (bloats history, #92) or `lease_renewal_failed` (no local cause). |
| D12 | A fenced write checks credential against the projection, then path, then live lease records, under the transaction lock, before any write; a refusal never records a lapse. | #117 "every core mutation must validate that binding at its owning interface"; the-bar defense in depth; #204 "refused before any write". | Recording the lapse on the refused call (the acceptance criterion requires state unchanged). |
| D13 | Renewal is the core's decision inside `renew(custody)`, a tick the holder's host loop calls: extend only inside the margin `min(ttl, max(ttl/2, 60 s))`, by the recorded TTL, or quiesce; callers never pass expiry or term. | #92 "renewal is a core duty … once remaining validity drops below `renewal_margin` (default half the TTL, floor 60 s)". | A caller-computed extension (renewal becomes a workflow duty) or a background thread in a library (a process-lifetime side effect with no owner). |
| D14 | `advance` requires custody for a transition into `publishing` and every transition after history reached it; earlier transitions take none; a presented custody is always checked; entering a terminal releases custody in the same write. | #82 leases before the first mutating action, verification may run concurrently; the-bar fail loud. | Custody on every advance (serializes verification across transactions sharing keys) or none (#205 stale-write criterion unmet). |
| D15 | Intervals open through `open_interval` and close through `record_evidence`; continuity is judged by event `seq` between the two, not by timestamps. | #92 interval span continuity; #204 "`seq` alone orders history"; defense in depth. | A caller-supplied start (backdatable) or `at` comparison (non-monotonic clock). |
| D16 | Grants are minted only for the current custody with its fence and never re-stamped; `check_grant` is a read-only fenced check. | #92 grants carry `fence_snapshot`, renewal never invalidates, reacquisition does; prototype `dc98ba9` takeover re-stamp; #117 D11. | The prototype's single-epoch equality (renewal voids the grant) or re-stamping on takeover (authority crosses a custody gap). |
| D17 | `reap` is idempotent and custody-free: it writes lapse, synthesized stop and a park only when held custody has lapsed on the clock, and otherwise returns the unchanged snapshot. | #117 "owner expires; reaper observes → park, withdraw old rights"; a sweep reaps every transaction. | Raising on live or absent custody (every sweep would catch routine refusals). |
| D18 | Late results enter `record_owner_result`: authentic means the executor and fence match some custody span in history; recorded as `current` or `stale` with `supersedes` naming the matching synthesized stop; it never changes state or custody; terminal transactions refuse it. | #117 separate observation intake, both events kept, never restores stale authority; slice 6 owns receipts and supplements. | Refusing stale results (the #117 false-record defect) or letting them advance state (a stale executor's privileged mutation). |
| D19 | Quiesce happens inside `renew` once the parking exceeds the core cap `PARKED_CUSTODY_WINDOW_MS` = 15 min; resume is an ordinary reacquisition; the observed-call exception is slice 3's. | #92 finite, core-capped parked window and quiesce; #117 parked custody. | Quiescing on entry to a parking (drops custody during short human waits) or holding custody indefinitely (blocks other transactions on the keys). |
| D20 | Evidence and grant verdicts are derived on every load from events and the latest fence, never stored. | #92 "superseded, never edited"; #204 D5 projection discipline. | Storing verdicts (a second truth that can disagree with history). |
| D21 | New refusals `FenceViolation` (base of `StaleCustody`, `CustodyMisbound`, `GrantInvalid`) and `LeaseUnavailable`, all under `TransactionError`; argument shape errors stay `StateInvalid` before any lock. | #204 D9, D16 typed refusals; #117 misbinding is a fencing violation, not a write conflict. | Message parsing, or reusing `TransactionBusy` for a live lease (a lock race and a live holder are different). |
| D22 | The sweep gains `lease_renewal` and `lease_lapse` rows for all four shapes, with a voided-forms column; the executor acquires custody and records evidence by each obligation's declared temporal form. | #205 "the sweep gains a lease renewal/lapse fixture"; #204 D6 the executor grows as the core does. | One synthetic single-shape fixture (misses shapes whose obligations mix event, snapshot and interval). |
| D23 | Keep slice 1's three seams; custody behavior is tested through the store and lease inspection only. | design skill "prefer existing seams"; the-bar tests assert observable behavior. | Unit tests over the custody module's internals (bind the tests to the module split). |
| D24 | Release, quiesce and terminal release clear only lease records still naming the span's instance; lapse means any key expired or re-held by another instance, one predicate for reap and acquisition. | Grill scenario: A lapses unreaped, B acquires a shared key, A then reaps or ends — clearing by key would evict B's live lease; #92 fencing orders handovers. | Clearing every record of the key set (a stale transaction releases a successor's custody). |
| D25 | The fenced check reads lease records lock-free and judges liveness at one clock reading under the transaction lock; fenced writes never take the lease lock. | #92 expiry only on the authority clock; acquisition needs `clock >= expires_at`; #204 D10 non-blocking locks. | Holding the global lease lock across every fenced write (serializes all transactions and turns routine writes into `TransactionBusy`). |
| D26 | Amends D14: a transaction that currently holds custody requires it on every advance, whatever the region, so a pre-publishing terminal cannot end or release someone's live custody uncredentialed. | Grill scenario: custody acquired at `ready`, then an uncredentialed `abandoned` would release it; #117 every mutation validates the binding. | D14's region rule alone (a caller without custody could end a held transaction before `publishing`). |
| D27 | Refusal precedence: a terminal transaction refuses every mutating custody or lifecycle call (`advance`, `acquire`, `renew`, `release`, `record_evidence`, `open_interval`, `issue_grant`, `record_owner_result`) with `TransitionRefused` before the fence check; a required custody that is absent is `StaleCustody`; a reused `evidence_id` or `grant_id`, or closing an interval never opened, is `StateInvalid` under the lock before any write. | #204 D8 "a terminal refuses every target"; D12, D21; the v2 validator would refuse the candidate anyway. | Fence check first on terminals (the refusal class would hinge on a credential that can never be valid) or a new error class for id reuse (YAGNI). |
| D28 | The parked window runs from the `at` of the transition that entered the current parked run from an unparked state (`attention_required → recovering` keeps it); `renew` quiesces once `now − start > PARKED_CUSTODY_WINDOW_MS`. | D19; #92 finite, core-capped parked window. | Restarting the window at each parking transition (flipping between the two parkings would hold custody forever). |
| D29 | Amends D22: `lease_lapse` lapses after every obligation but the last is recorded (not half), so pre-lapse records span all three temporal forms (product's `event` survives, daemon's `interval` voids); `drive` takes the store root and builds its store on the world clock. | Planning count: each shape's first half is floor `snapshot`s only, so D22's event and interval assertions would be vacuous. | Half the obligations (the voided-forms column would read `{snapshot}` everywhere and prove nothing about the other forms). |
| D30 | The v2 validator also cross-checks what the spec leaves implicit: `lease_reacquired`'s `reason` matches how the prior span closed, `prior_executor_id` names that span's executor, one `instance` per fence, and `owner_result`'s executor and `supersedes` name a matching span and an earlier `stop_synthesized` of that fence. | #204 D5 projection validation; the-bar defense in depth. | Treating those fields as opaque (a hand-edited history could claim a false reason or supersession). |
| D31 | Transaction ids stay `rel_` UUIDv7 over the wall clock; only event `at` and lease arithmetic read the injected clock. | #204 D3 (id time is creation wall time); D3 names expiry and event `at` only. | Minting ids from the injected clock (a fake clock would stamp future or epoch-zero ids, breaking UUIDv7 time order). |
