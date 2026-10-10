# Epoch-fenced attempt custody and late-result receipts, issue 338

Design for [issue 338][i338], package 2 of 3 of [issue 125][i125], executing the
[issue 117 decision](2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md) (cited below as
"the decision record") on top of
[package 1](2026-10-09-issue-337-attempt-identity-migration-design.md) ([issue 337][i337]).
Base: main `5bd914e1`. Decisions were taken autonomously under `from-issue --auto`; each non-obvious
one is a ledger row.

[i117]: https://github.com/fagenorn/nix-config/issues/117
[i125]: https://github.com/fagenorn/nix-config/issues/125
[i132]: https://github.com/fagenorn/nix-config/issues/132
[i133]: https://github.com/fagenorn/nix-config/issues/133
[i151]: https://github.com/fagenorn/nix-config/issues/151
[i280]: https://github.com/fagenorn/nix-config/issues/280
[i337]: https://github.com/fagenorn/nix-config/issues/337
[i338]: https://github.com/fagenorn/nix-config/issues/338
[i339]: https://github.com/fagenorn/nix-config/issues/339

## Problem

An attempt's custody is a deadline and an advisory file lock. Nothing marks which launch of an
attempt may write: a superseded owner's `progress`, `suspend` or legacy `finish` is admitted because
those transports name only the attempt, and a session standing in another attempt's worktree writes
without anyone noticing. When an owner outlives its deadline the reaper's record and the owner's
real result compete for one field: a legacy `finish` overwrites a synthetic stop and loses it, a
`finish` after an expiry suspension is refused, and a version-2 summary from that owner is refused
with nothing kept. So the ledger can end up saying `stopped` about work that was delivered, and no
record shows that both things happened.

The transaction core already has the vocabulary: a lease per concurrency key with an epoch, a reaper
entry that records a synthesized stop, a late-result intake that links a result to the stop it
supersedes, and a write-once receipt that lists both. Package 1 gave every run a core identity.
Nothing yet uses the core for custody.

## Solution

Every implementation attempt gets one core transaction, its *custody transaction*, in the attempt
store package 1 created. It holds what the engine could not express: who holds the attempt (one
custody span per launch, under a lease keyed by the attempt's worktree), when that hold lapsed, each
suspension as a parking, every reaper stop and every owner result as immutable events, and the
receipt that seals them.

The ledger keeps its attempt fields, but for these facts they are a *projection*: every committed
ledger write first makes the core agree, and the core can refuse the write. Readers, wires and the
launch and expiry answers of [issue 132][i132] and [issue 133][i133] do not change. Control still
decides from the ledger; [issue 339][i339] moves it onto core state.

Three things become fencing events:

- **Reaper reclaim.** An expired launch's lease has lapsed on the same comparison the reaper uses, so
  the reaper's write is the core's `reap`: lapse, synthesized stop, parking. The next launch takes
  the next epoch.
- **Finish after expiry.** An owner's `finish` is always recorded through the late-result intake
  against the span of the launch that sent it. From the attempt's last launch it becomes the
  attempt's verdict and supersedes a synthesized stop. From an earlier launch it is refused as a
  fencing violation and kept as evidence.
- **Misbinding.** An owner transport whose process stands inside another attempt's worktree is
  refused before any lock, directory or file is created.

## Decisions

### Custody transaction

- **One per implementation attempt** (per D1), created in the write that creates the attempt, under
  creation key `attempt-custody/v1:<run transaction id>:<issue>:<attempt>`, with authority class
  `attempt-custody`, the core's empty proof and recovery plans, and one concurrency key,
  `attempt-worktree:<worktree>`. It is found by `TransactionStore.lookup`; the ledger gains no field.
- **Subject `attempt-custody/v1`**, a closed JSON object:

  | Field | Value |
  |---|---|
  | `schema` | `"attempt-custody/v1"` |
  | `run` | the run transaction id |
  | `issue`, `attempt` | the attempt's issue and ordinal |
  | `worktree` | the attempt's recorded worktree as an absolute path with existing parents resolved, as the engine's `canonical_worktree_path` gives it at creation; it is the core's bound subject path and is never recomputed |
  | `prior` | the custody transaction id of this issue's previous attempt in the run, else `null` |
  | `bound_launch` | for an attempt that existed before its ledger reached schema 9, its launch count at that write; `null` for an attempt created at schema 9 |

- **A launch is a custody span** (per D3). Launch `n` of the attempt is the span opened with
  `executor_id` equal to its action id (`<issue>:<attempt>:<n>`), so the legacy implementation
  launch reference is the core launch identity. The epoch of the worktree key is the launch
  generation: every launch advances it.
- **Delivery-remainder custody is not moved** (per D10). `issue:r<n>:launch` launches stay in the
  ledger alone until [issue 339][i339] ports remainders.

### Lease window, renewal and lapse

- **The lease's validity is the attempt's budget window** (per D2). A launch acquires with
  `ttl_ms = deadline_at − now`, so the lease expires at `deadline_at` exactly, and "expired" means the
  same instant to the reaper and to the core. Nothing an owner writes extends it: `progress`,
  `mark-progress` and worker registration never renew, which keeps the deadline independent of
  progress as [issue 133][i133] requires.
- **The one in-place renewal is `declare-lane`** ([issue 280][i280]), which re-bases a live launch's
  deadline. It calls the core's renewal with the new window: same epoch, same instance, term and
  renewal count plus one, expiry at the new `deadline_at`.
- **A lapse advances the epoch.** After a lapse or a release, the next launch (a suspension resume
  with a fresh window, a handoff resume or a dead-owner takeover inside the old window) is a new
  acquisition at the next epoch. The core already voids `snapshot` and `interval` evidence and grants
  recorded under the old fence and keeps `event` evidence.
- **Clock.** Every core call a write makes reads one clock: the write's ledger time in
  milliseconds (the supplied `--now`, else the ledger clock read under the ledger lock).
- **Two core additions, nothing else** (per D12):
  - `TransactionStore.check_custody(custody)`: the fenced check alone, under the transaction lock at
    one clock reading. It writes nothing and raises what a fenced write would.
  - `TransactionStore.renew(custody, *, ttl_ms=None)`: without `ttl_ms` it is unchanged. With a
    positive integer it sets every record's TTL to `ttl_ms` and its expiry to `now + ttl_ms`,
    whatever the margin, keeping epoch and instance and adding one term and one renewal. A lapsed
    span is `StaleCustody` with nothing written.

  No attempt word enters a `transaction_*` module, so the neutrality check keeps passing.

### Ledger projection and write order

Ledger schema becomes 9. The field sets do not change; schema 9 means "this ledger's attempt custody
is held in the core" and exists so that a helper from before this package refuses the ledger instead
of writing custody fields the core never saw (per D4, D14).

At schema 9 these hold for each issue's latest implementation attempt after every committed write:

| Ledger attempt | Custody transaction | Custody span |
|---|---|---|
| `active` | `created` | open, `executor_id` is the current action id, lease expires at `deadline_at` |
| `handed_off` | `created` | none; the last span closed `released` |
| `suspended` | `attention_required` | none |
| `stopped`, source `stalled` | `attention_required` | none; not sealed |
| `stopped` or `failed`, source `owner` or `refused` | `abandoned`, sealed | none |
| `merged`, any source | not terminal | none; not sealed |

An attempt that was already terminal when its ledger reached schema 9 has no custody transaction and
keeps today's behaviour everywhere (per D11).

The one writer is a *custody settle* step inside `commit_state`, the boundary every committed ledger
write already passes. For each issue's latest attempt it reads the custody transaction and applies
the operations that bring the core to the row above. It is the only place workflow-state changes
custody, so `control`, `direct-owner`, the reaper, both `finish` transports, `checkpoint-delivery`,
`suspend`, `progress` and `declare-lane` are all covered without touching the delivery runtime
(per D4, D10).

| Ledger change in this write | Core operations, in order |
|---|---|
| attempt created | `create`, `acquire` |
| new launch on an existing attempt | `release` of a still-live span (handoff already released; a dead-owner takeover releases here, per D3), `acquire`, then `advance` back to `created` when parked |
| `active` → `handed_off` | `release` |
| `active` → `suspended` by an owner or by control | `advance` to `attention_required` with reason `suspended:<blocked_on>`, `release` |
| expired `active` → `suspended` (`unknown`) | `reap` with reason `expiry` |
| expired `handed_off` → `suspended` (`unknown`) | `advance` to `attention_required` with reason `suspended:unknown` |
| → `stopped`, source `stalled` | `reap` with reason `stalled` when the span lapsed, else `advance` to `attention_required` with reason `stalled` and `release` |
| owner verdict (source `owner`) | `record_owner_result` unless that span already holds a result with the same digest; `merged`: `release` a live span; otherwise seal |
| `merged`, source `superseded` | `release` a live span |
| source `refused` | seal, when not already sealed |
| `deadline_at` moved on the current launch | `renew` with the new window |

Order and failure:

- **The core goes first.** Every operation except the seal runs before the ledger file is replaced.
  A core refusal aborts the write with the ledger untouched. `LeaseUnavailable` from `acquire`,
  another custody transaction holding the worktree live, is the fencing refusal
  `custody_unavailable`; no launch steals a live lease.
- **The seal goes last.** `advance` to `abandoned` runs after the ledger file is replaced, so a
  crash leaves a ledger verdict whose transaction is not yet sealed, never a sealed transaction the
  ledger contradicts. The settle step of the run's next write, or `migrate --apply`, completes it.
- **Every operation is idempotent against the core's own state**: an open span with the launch's
  `executor_id` is not acquired again, a reaped span is not reaped again, a recorded result is not
  recorded twice. So the command that crashed between the core and the ledger converges when it
  is repeated. A span left open for a launch the ledger never recorded is closed by the settle step
  the next time that attempt is settled. A combination the two tables do not produce is refused as
  `custody projection mismatch` before any write.
- **Locks.** `.direct-<issue>.lock` → ledger `state.lock`s → the attempt store's blocking lock →
  core `creation.lock` → core `<id>/lock` → core `leases.lock`. Package 1's blocking lock now wraps
  every core write workflow-state makes, because `leases.lock` is shared by every run and
  non-blocking (per D15). Lock-free readers take none of them.

`check-launch`, `current-launch`, `owner-liveness` and `resume-pack` stay read-only and print the
same bytes: they answer from the projection, with no clock and no core write.

### Migration 8 → 9

One adjacent step after package 1's, with the same shape: a pure plan in the package and the bind
under the ledger's lock on the next write or through `workflow-state migrate --apply`, after the
read-only dry run.

- **Plan (pure):** for each issue whose latest attempt is `active`, `handed_off` or `suspended`,
  the subject above with `bound_launch` set to its launch count. A worktree that is not an absolute
  path is `invalid_state`. No new refusal reason and no new report field: a schema-8 ledger's
  verdict is `migrate`.
- **Bind:** the settle step creates each planned transaction, and acquires a span only for an
  attempt that is `active` and unexpired at the write's time. A suspended attempt is parked with
  its recorded cause. No history is replayed into the core: migration states what is held now
  (per D11).
- A helper from before this package refuses schema 9 through its existing version check, with the
  ledger unchanged. There is no reverse transform.

### Owner transports and the launch fence

Owner transports are `progress`, `suspend`, both `finish` transports, `checkpoint-delivery`,
`mark-progress`, `declare-lane`, `register-worker` and `release-worker`.

- **Naming the launch** (per D9). `progress`, `suspend` and the legacy `finish` gain an optional
  `--action-id`. With it, the caller is that launch, and it must name the same issue and attempt.
  Without it the transport is *attempt-keyed*: it speaks for the attempt's `bound_launch`. An
  attempt-keyed transport on an attempt whose `bound_launch` is `null` is refused as
  `launch_identity_required`. The from-issue skill's `progress` and `suspend` argv gain
  `--action-id <action_id>`.
- **The fence.** Under the ledger lock, before the mutation: when the attempt is `active` and the
  caller's launch is not the attempt's last launch, the transport is refused as
  `superseded_launch`. When the caller's launch is the last launch and the attempt is `active`,
  `check_custody` must pass. Every refusal the engine already makes keeps its message, including
  the two the from-issue skill matches (`progress requires an active attempt`,
  `cannot record progress at or after attempt deadline`).
- **Fencing refusals** are one closed set, printed as
  `workflow-state: fencing violation: <reason>: <detail>` with exit 2 (per D13):

  | Reason | When |
  |---|---|
  | `custody_misbound` | the process stands inside another custody subject's worktree |
  | `superseded_launch` | the caller's launch is not the attempt's last launch |
  | `launch_identity_required` | an attempt-keyed transport on an attempt with no `bound_launch` |
  | `custody_unavailable` | a launch would acquire a worktree another custody transaction holds live |

### Misbinding

Before an owner transport takes a lock or creates anything, it reads the process's own working
directory, resolved to a physical path. For that directory and each ancestor, nearest first, it reads
the lease record of `attempt-worktree:<path>` with the core's lock-free `inspect_lease`. The first
path that has a record is the worktree the session stands in. If that path is not the `worktree` of
the custody transaction the transport addresses, the transport is refused as `custody_misbound`
(per D7).

- The directory is observed by the helper. No argument or environment variable supplies it.
- A session standing in no attempt worktree (the main checkout, a scratch directory, a Phase-0
  owner before its worktree exists) is admitted: it is bound to nothing.
- The check reads only the core's store. It runs no child process, and when the store does not
  exist yet it finds no record.
- A record counts whether or not its holder is live: the question is whose worktree this is, not
  who holds it now.

### Late-result intake and terminal truth

The intake is the core's `record_owner_result` on the attempt's custody transaction (per D6). It
keeps the validated report exactly as submitted (the legacy result object, or the version-2
summary) with the launch's `executor_id` and fence, `custody` `current` or `stale` as the lease says
at that instant, and `supersedes` naming that span's latest synthesized stop. There is no second
store.

- **Adoption.** A `finish` from the attempt's last launch is the attempt's verdict when no verdict
  is recorded yet and one of these holds: the span is live; the span has lapsed and nobody reaped it
  (the engine's existing "finish after the deadline records the report"); or the reaper closed that
  span with a synthesized stop, whether the ledger now shows the expiry suspension or a `stalled`
  stop. The last case is new for a suspension and for the version-2 summary: workflow-state hands
  the delivery runtime the record as it stood before the reaper's write, so the summary is judged
  exactly as an on-time one, and a refusal still writes nothing. The ledger then shows the owner's
  result with source `owner`, as the legacy replacement of a synthetic stop does today.
- **Refusal with retention.** A `finish` the fence or the engine refuses for custody, whose launch
  the core issued a span for, is recorded in the intake (`custody: stale`) before the refusal is
  printed. The ledger's bytes do not change. A checkpoint carries no result and is only refused.
  A result that arrives after the seal is refused and not retained; receipt supplements are
  [issue 339][i339]'s.
- **What seals** (per D5). A synthesized stop never seals: it parks. A verdict that is not `merged`
  (an owner's `stopped` or `failed`, a lifecycle `refused`) seals the transaction `abandoned`: the
  custody ended and no delivery effect happened under it. The core writes the
  `transaction-terminal-receipt/v1`, reads it back, and only then closes. Its `stops` lists every
  synthesized stop with `superseded_by`, and its `owner_results` lists every owner result with
  `supersedes`, its custody flag and a digest of the report.
- **`merged` does not seal in this package.** The owner's result is recorded and supersedes the
  stop in the transaction's history, the ledger shows `merged`, and the transaction stays
  non-terminal with no custody. Sealing a delivered attempt `succeeded` needs the delivery proof,
  and delivered, merged, closed and cleanup stay the four separately observed postconditions of
  [issue 151][i151] in the ledger until [issue 339][i339] ports them. No core event or receipt in
  this package says that an attempt was delivered.

### Suspension in core terms

- A suspension is the custody transaction parked in `attention_required` with no custody. Its cause
  is the parking transition's `reason`: `suspended:<blocked_on>`, or the reaper's `expiry`, which is
  the cause `unknown`. It adds no terminal.
- A resume is a new span on the same transaction and a return to `created`. It creates no
  transaction, so it consumes no attempt. A retry is a new custody transaction with `prior` set.
- The closed vocabulary and its pure rules move to one home, the new package module
  `agent_tools.attempt_custody`, which workflow-state imports: the blocked-on set, the owner-supplied
  and auto-resumable subsets, the stall limit and the stall arithmetic (per D8). The values are the
  shipped ones, including `agent_dispatch` and `deadline`, which were added after the decision
  record.
- The stall counter, `suspend_phase` and the progress marker stay ledger fields: phases and
  markers are adapter facts, and control still reads them from the ledger until
  [issue 339][i339].
- An owner-called suspension that reaches the stall bound parks with reason `stalled`. Its span
  did not lapse, so the core records no synthesized stop for it; a later owner result is recorded
  with `supersedes: null`.

### Packaging and prose

- `agent_tools.attempt_custody` (new, pure): the subject, key and creation-key rules, the vocabulary
  above, the fencing reasons, the migration plan and the settle planner, which maps a ledger attempt
  and a transaction snapshot to an ordered operation list.
- `agent_tools.attempt_store` gains the effects: applying an operation list under the blocking
  lock, the misbinding lookup, the intake call and the read used by the fence. Its refusals are
  subclasses of `StoreRefused`, which workflow-state's `main` already maps to exit 2.
- Contract prose goes to the transaction-core paragraph of `python/README.md` and a new subsection
  of `home/common/agent-skills/README.md` § Lifecycle helpers. Root `CLAUDE.md` gains no detail.
  The skill argv change fits the current instruction ceilings; an edit that would exceed one is
  paid for by condensing nearby text (per D9).

## Test seams

Three seams, all already in `just agent-workflow-tests`. No other seam may be invented.

1. **The workflow-state CLI**, driven from source as `LifecycleHarness` and
   `DeliveredControlHarness` do, with a new `home/common/agent-skills/tests/test_attempt_custody.py`.
   Observable behaviour is the command's output and exit code, the ledger's bytes, and the store read
   through the core's public readers (`lookup`, `load`, `inspect_lease`, `read_receipt`). A "tree
   snapshot" is every path under the test root with its bytes.
2. **`agent_tools.attempt_custody`'s pure functions**, imported normally by a new
   `tests/test_attempt_custody.py`, as `tests/test_attempt_identity.py` does for package 1.
3. **The core store with an injected clock**, in the existing `tests/test_transaction_custody.py`,
   for `check_custody` and `renew(ttl_ms=…)`.

| Criterion | Deterministic check (seam) |
|---|---|
| AC1 state in the core, epoch-fenced; lapse advances, renewal does not | A spawn creates the custody transaction: `lookup` of its creation key answers, its custody names action id `…:1:1`, and the worktree key's lease is at epoch 1 and expires at `deadline_at`. `declare-lane` leaves epoch and instance, makes the term 2 and moves the expiry to the new `deadline_at`. A control sweep after the deadline appends `lease_lapse_detected` and `stop_synthesized`; the resume appends `lease_reacquired` with reason `expired` at epoch 2. A `snapshot` evidence recorded under launch 1 through the store reads back inadmissible, `fence_changed`, after the resume. Core: `renew(ttl_ms=…)` keeps the epoch and refuses a lapsed span (1, 3) |
| AC2 late owner result supersedes a synthesized stop; receipt holds both | Expire an owner, let control reap, then send that launch's `finish` with a `stopped` result, once by the legacy transport and once as a version-2 summary. The command succeeds, the ledger shows the owner's result with source `owner`, and the receipt read back by its digest has outcome `abandoned`, one stop with reason `expiry` whose `superseded_by` is the owner result's seq, and one owner result with `custody: stale` whose `supersedes` is the stop's seq. The same with a `merged` result: both events are in the loaded history, linked the same way, and the transaction is not terminal (1) |
| AC3 misbound session refused before any write | Two issues are active in one run and both worktrees exist. Each owner transport, table-driven, is sent for issue A's launch with the process standing inside issue B's worktree: exit 2, `fencing violation: custody_misbound`, and the tree snapshot is unchanged. The same transport from the test root is admitted (1) |
| AC4 fixtures: late owner, misbinding, separate postconditions | The AC2 and AC3 fixtures, plus a contracted issue whose owner's `merged` summary arrives after a reap: the custody transaction holds the owner result and no receipt, the ledger's `pr_merged` postcondition is observed while `tracker_closed` is pending, and a later sweep that observes the tracker closed changes that one postcondition and no core file (1) |
| AC5 attempt-keyed transport after a successor launch | A schema-8 fixture with a live owner at launch 1 is migrated by control's write (`bound_launch` 1), expired, reaped and resumed to launch 2. Attempt-keyed `progress` and `suspend` exit 2 with `fencing violation: superseded_launch` and an unchanged tree. Attempt-keyed legacy `finish` exits 2 the same way, the ledger's bytes are unchanged, and the custody transaction gains one owner result for launch 1's span with `custody: stale`. On an attempt created at schema 9, an attempt-keyed transport is `launch_identity_required` and one naming launch 1 is `superseded_launch` (1, 2) |
| AC6 regression floor; launch and expiry projections unchanged | The whole `just agent-workflow-tests` suite is green at the package head. Its declared changes are: the current schema number, harness owner transports naming their launch, and the fixtures' down-converter. `check-launch` and `current-launch` print the same bytes for both launch forms before and after the 8 → 9 bind; the committed admission-replay baseline is unchanged; the helper extracted with `git archive` from the pinned base commit `5bd914e199f3e57217780596beefe69838f4efd4` exits 2 on a schema-9 ledger with the tree unchanged, and a missing commit fails the test. `just build` and `just agent-installed-skill-tests` pass (1) |

## Out of scope

- Control deciding from core state, replacing directory scans with the index, event-driven wakeups
  and worker-slot admission changes ([issue 339][i339]).
- Custody transactions for delivery remainders, and porting admission claims and the delivery
  contract, intents, observations and remainders onto the core ([issue 339][i339]).
- Sealing a delivered attempt `succeeded`, any proof or recovery plan for attempts, and receipt
  supplements for results or observations that arrive after a seal.
- Any change to delivery reconciliation: the delivery runtime and the delivery model are not edited,
  and the remainder lane's window rule stays as shipped.
- Close-before-merge holds on resume lanes (the decision record's D15, D18), compare-and-set at the
  forge, and enforcement inside the mutation guard.
- Replaying pre-migration history into the core, any reverse migration, and moving workflow-state
  into the package.

## Triage

> **Lane triage.** Input: contract_change=hit (attempt state gains custody epochs and a receipt; legacy transport gains a fencing refusal); concurrency_or_persistence=hit (leases, epochs, reaper/owner races, persisted receipts); open_design_questions=doubt (vocabulary fixed by the decision spec, mapping left to design); criteria_shape=hit (six criteria); paths: `home/common/agent-skills/scripts/workflow-state.py`, `python/agent_tools/attempt_store.py`, `python/agent_tools/attempt_identity.py`, `python/agent_tools/transaction_custody.py`, `python/agent_tools/transaction_receipt.py`, `home/common/agent-skills/tests/test_workflow_state.py`, `home/common/agent-skills/tests/test_attempt_migration.py`, `python/README.md`, `home/common/agent-skills/README.md`. Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}`. ran: full (shadow)

## Decision ledger

"Record" is the issue 117 decision record; "P1" is the package 1 design. The five Phase-0 open
questions are answered by D1 (which object carries the lease), D5 (supersede and the receipt), D6
(the intake), D7 (misbinding) and D8 (suspension vocabulary).

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The lease is carried by a custody transaction per implementation attempt, with one concurrency key naming the attempt's worktree. | The core binds one subject path for a transaction's life, and the engine lets a retry take a different worktree; concurrency keys are fixed at creation; a lease record names its holder, so the key also answers "whose worktree is this" across runs; record "bind execution custody to … exact repository/worktree identity". | The run transaction's key (one key cannot hold several issues of an orchestrated run, and the record rejects a shared mutable group transaction); a per-issue transaction (cannot follow a relocated retry; P1 D1 forecast it before the bound-path rule was weighed). |
| D2 | The lease's validity is the attempt's budget window; nothing an owner writes renews it; `declare-lane` is the one in-place renewal. | Issue 133: expiry is one fixed instant; the core's `reap` records a synthesized stop only for a lapsed span, so reaper and lease must agree on that instant; issue 280 re-bases a live launch's deadline. | A shorter lease renewed by owner writes: it either lapses before the deadline (a reap issue 133 forbids, or one launch split over several epochs) or outlives it (the reaper could then record no stop). The record's separate effect lease belongs with core-invoked effects, which this package has none of. |
| D3 | A launch is a custody span whose executor is the action id; a dead-owner takeover releases the old span in the write that acquires the new one. | P1 D5 left launch references to alias core launch identities here; every `acquire` already advances the epoch; `owner_unavailable` is the host's observation that the holder is gone, and the engine takes over in the same sweep today. | A separate launch id table (a second identity for one launch); waiting out the dead owner's lease (changes the shipped same-sweep takeover the regression floor covers). |
| D4 | The ledger's attempt fields stay as a projection written by one settle step inside `commit_state`: core first, seal last, every operation idempotent, schema 9 as the marker. | Record: adapters "retain no independently writable lifecycle ledger" and a mirrored pair is rejected, so the core must be able to refuse a write; `commit_state` is already the one write boundary; issue 339 owns control reading core state; the-bar defense in depth. | Rewriting each command to call the core (touches every lane and the delivery runtime, far over the review cap); ledger first with the core following (the core could never refuse, which is the mirror the record rejects). |
| D5 | A non-`merged` verdict seals `abandoned`; a synthesized stop parks; a `merged` attempt records its result and stays unsealed. | Record: synthetic stops are provisional and "park unknown reality"; `abandoned` needs absence of declared effects, and review staging is not delivery (record D13); success needs the plan's proof; the-bar truthful terminal states. | Sealing every closed attempt `abandoned` (labels delivered work abandoned); sealing `merged` as `succeeded` over an empty plan (success with no proof); a proof plan over the four postconditions now (ports issue 151's objects, which is issue 339's, and legacy contractless issues could never satisfy it). |
| D6 | The intake is `record_owner_result` on the custody transaction, holding the report as submitted. A `finish` from the last launch is adopted, also over a reaper suspension and for a version-2 summary; one from an earlier launch is refused and retained. | Issue 338 "never refusing the result into a false `stopped`"; record: authentic late evidence stays tied to its launch and never restores authority; the engine already adopts a late report over a synthetic stop; the core intake needs an issued span. | A separate intake file (a second evidence store); refusing every late report (the defect being fixed); adopting a report from a superseded launch (overrides the successor's custody). |
| D7 | Misbinding is found from the process's own physical working directory: the nearest ancestor with a worktree lease record must be the addressed attempt's worktree. | Record: "a caller-supplied current directory … is not authority"; `inspect_lease` is lock-free and writes nothing; lease records keep their key forever; AC3 "before any write". | A `--cwd` argument (caller-supplied); `git rev-parse` in the directory (a child process, and it names a checkout, not an attempt); requiring every transport to run inside its own worktree (refuses controllers and Phase-0 owners, whose worktree does not exist yet). |
| D8 | Suspension is a parking with a closed reason; the vocabulary and stall arithmetic move to the package as their one home; the counters and the progress marker stay ledger fields. | Record's core/adapter table: suspension adds no terminal, phases and progress translation are adapter facts; agent-helpers rule 1; the neutrality check forbids attempt words in `transaction_*`. | Blocked-on names inside the core modules (fails neutrality); moving the counters into core events now (control reads them from the ledger until issue 339, so it would be a second home). |
| D9 | `progress`, `suspend` and legacy `finish` take an optional `--action-id`; without it they speak for the attempt's `bound_launch`, and an attempt created at schema 9 has none, so they are refused. Skill argv gains the flag inside the current instruction ceilings. | Record D16: an attempt-keyed transport binds to the launch current at migration, and later owners name their launch on every write; owners already hold their action id; only the user applies the budget-raise label. | Binding an unnamed transport to launch 1 (a resumed owner is refused anyway, and the rule says nothing true about who is calling); leaving new attempts attempt-keyed (the superseded-owner write the record rejects). |
| D10 | Remainder custody, delivery objects and the delivery runtime are untouched: late version-2 summaries are adopted by handing the runtime the pre-reap record. | Issue 339 ports remainders and delivery objects; issue 338 scope excludes delivery reconciliation changes; `workflow_delivery*.py` are risk paths. | Editing the runtime's custody check (changes delivery admission for remainders too); giving remainders custody transactions now (issue 339's port, done twice). |
| D11 | Migration binds only attempts that are not terminal, issues a span only to one that is active and unexpired, and replays no history. An attempt terminal before migration keeps today's behaviour. | Record: migration preserves history "without treating synthetic stops as core failed receipts" and applies the dry run's transform on write; the core records what it witnessed, and its event times are the write's. | Replaying recorded launches and stops into the core (events dated at migration that the core never witnessed); binding terminal history (transactions that can never change). |
| D12 | The core gains exactly `check_custody` and `renew(…, ttl_ms=…)`. | The fenced check is private and the adapter must not re-implement it (the-bar DRY); the shipped renewal extends only by the recorded TTL inside its margin, so it cannot follow a declared re-base; P1 added `lookup` the same way. | Reading lease files from the adapter (a second judge of custody); releasing and reacquiring on `declare-lane` (advances the epoch, so no renewal would exist to satisfy AC1). |
| D13 | Fencing refusals are one closed set under one prefix, and every refusal the engine makes today keeps its text. | Issue 338: classified as fencing events, "never as write conflicts or silent execution"; the from-issue skill matches two existing `progress` messages; the-bar fail loud. | Rewording existing refusals (breaks the skill's matches and the floor); one generic refusal (the classification is the criterion). |
| D14 | The old-helper check runs the real base generation, extracted from the pinned base commit, and schema 9 changes no field. | P1 D13 and D10: exclusion by schema bump, tested with the real older helper; the-bar tests that can fail. | A field-level marker (churns every hand-built fixture for no reader); asserting only the current helper's refusal of schema 10. |
| D15 | Package 1's blocking attempt-store lock wraps every core write workflow-state makes. | The core's locks are non-blocking and `leases.lock` is shared by every run under one root; P1 D9 solved the same contention for `create`. | Retrying on `TransactionBusy` (a sleep-shaped race fix) or a blocking core lock (changes the core contract for every consumer). |
