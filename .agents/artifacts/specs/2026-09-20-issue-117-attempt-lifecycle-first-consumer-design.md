# Attempt lifecycle as the transaction core's first consumer

Decision for [#117](https://github.com/fagenorn/nix-config/issues/117), 2026-09-20; refreshed
2026-09-27 against main at `17da7f2` (per D9).
Status: architecture decision under delegated authority; runtime core delivery remains downstream.
The choices here are agent judgments within the caller's authorized reversible decision scope,
not claims that a human selected these options. The issue's historical human-required label
does not describe the delegation used for this record.

## Problem

The existing attempt engine and the proposed release core independently own lifecycle policy.
Attempts already exercise suspension, retries and late results, but lack custody fences and
evidence invalidation. A synthetic stop can conflict with delivered work; a stale executor can
write in the successor's shared worktree. Releases have not supplied equivalent operating load.
Since the first draft the engine itself shipped agent-slot admission (#150) and delivery
contracts, separate postconditions, delivery remainders and authorization continuity (#151,
#171). This record maps them onto the core rather than treating them as pending.

Phase-0 restatement: settle the first consumer, adoption and identity, suspension vocabulary,
fenced custody, launch/expiry compatibility, host admission, terminal observations and authority
continuity. Deliver a committed decision and discovery pointer, without implementing or activating
the core, adapters or downstream schemas. The live issue's nine acceptance criteria govern scope.

## Solution

**Attempt lifecycle is first; ship-release is second, after core and attempt-path conformance.**
Reimplement the engine's policy-facing interface on the single transaction-state module.
Keep workflow-state and orchestration control as compatibility adapters and projection renderers;
they retain no independently writable lifecycle ledger. Domain phase logic proposes typed requests;
the core validates transitions, custody, retry accounting, evidence and receipts.

Two architectural options were considered. Absorbing the whole engine into the core would centralize
writes quickly, but would embed issue phases, tracker rules and native launch mechanics in a module
that must also serve releases. The selected reimplementation preserves its useful interface while
moving shared policy behind it. A temporary mirrored engine/core pair was rejected: disagreement
would recreate the terminal-truth defect and violate the single-authority rule. Release-first was
also rejected because it delays validation against the workload that exposes the custody failures.

## Grounding

Primary resolutions, rather than their superseded issue proposals, constrain this decision:

| Source | Binding constraint |
|---|---|
| [#66 resolution](https://github.com/fagenorn/nix-config/issues/66#issuecomment-5358319109) | Adjacent migration, dry run, atomic apply, retained bridge and rollback; no automatic activation. |
| [#72 resolution](https://github.com/fagenorn/nix-config/issues/72#issuecomment-5358956541) | Explicit ledger root across worktrees, one owning module, state-based cleanup. |
| [#82 resolution](https://github.com/fagenorn/nix-config/issues/82#issuecomment-5362787401) | Opaque identity separate from immutable subject/profile; one state module; four terminals; inspect before retry. |
| [#84 resolution](https://github.com/fagenorn/nix-config/issues/84#issuecomment-5367692860) | Scoped reversible authorization; fresh, one-action irreversible confirmation; explicit spend and principal limits. |
| [#85 resolution](https://github.com/fagenorn/nix-config/issues/85#issuecomment-5368248608) | Closed profiles; adapter describe/inspect/invoke; typed outcomes; core owns scheduling and truth. |
| [#88 resolution](https://github.com/fagenorn/nix-config/issues/88#issuecomment-5367876268) | Immutable proof plan, deterministic required collectors, evidence forms, cutoff and permanent receipts. |
| [#90 resolution](https://github.com/fagenorn/nix-config/issues/90#issuecomment-5379534641) | Release subject remains the preselected candidate; host waits are adapter mechanics; release cutover is quiescent. |
| [#92 resolution](https://github.com/fagenorn/nix-config/issues/92#issuecomment-5371623519) | Epoch versus term, scoped fence vector, authority clock, quiescence, grant/evidence invalidation. |
| [#132](https://github.com/fagenorn/nix-config/issues/132), [#133](https://github.com/fagenorn/nix-config/issues/133) | Read-only launch query and reviewed SHA; fixed wall-clock expiry, in-place resume and stall arithmetic. |
| [#150](2026-09-24-issue-150-host-capacity-admission-design.md), [#151](2026-09-21-issue-151-delivery-reconciliation-design.md), [#171](2026-09-23-issue-171-delivery-contract-source-design.md) designs | Shipped engine contracts: declared agent-slot admission; delivery contract, four postconditions, remainders and intent/scope/authority wire; builder, contract-last acquisition, migrate-on-write without a bridge. |

Local grounding: CLAUDE's lifecycle/storage guidance; the-bar's defense in depth, DRY, truthful
terminal states and moves-keep-history; the agent-helpers standard, which places new core code in
the `agent_tools` package; the committed #132/#133 designs; and current workflow-state behavior at
state schema 4 and control interface 3 (suspension, resume, finish, control, check-launch,
host-route, build-delivery and the delivery runtime). No context-map or ADR tree exists; this
record follows the existing spec convention and the architecture doc links to it. The
host-contention rejection still excludes CPU/memory/build-load scheduling; #150 admits agent slots
only. #150, #151 and #171 are delivered engine behavior, not core conformance evidence: #123, #124
and #125 remain open.

## Decisions

### Ownership and identities

The deep transaction-state module alone owns strict state, its stable short advisory lock, atomic
read–validate–replace and typed append-only history. The lock serializes state updates; it is not
an effect lease or proof of custody. Compatibility output is derived from core state. Host task
handles and provider references remain typed external references, never transaction identities.

New core transactions use **`rel_` + UUIDv7**, including attempts: do not mint `run_` or new legacy
dialects. Creation deduplicates by a caller creation key. One transaction owns one immutable
issue-delivery subject, with monotonically numbered execution attempts, delivery-remainder custody
(D12) and launch generations. A resume retains its custody ordinal and gets a new launch identity;
a genuine terminal attempt retry increments that ordinal, retains predecessor lineage and the
existing attempt cap. Per-action invocation retry ordinals are separate: #82's initial invocation
plus at most two automatic retries within fifteen minutes cannot spend/reset a workflow attempt.
Profiles may lower those invocation limits, never raise them. Stable deterministic action IDs
identify declared actions; legacy launch references are not such action IDs.

A grouped orchestration run is a controller/collection reference to issue transactions. It is not
a shared mutable transaction or a second identity authority. Preserve all four legacy run-id
dialects as typed aliases with original dialect, issue/grouping, attempt/launch and predecessor
lineage. Legacy launch references are the two `custody-ref/v1` action-id forms, implementation
`issue:attempt:launch` and remainder `issue:r<n>:launch`, which also key #150's admission claims;
both alias core launch identities. A group alias need not resolve to one transaction; its
issue member disambiguates. Unknown dialect, schema or ambiguous lineage blocks migration rather
than guessing from directory names. Canonical lookup uses the state module's index and an explicit
ledger root; the shipped direct-run discovery and #193's installed-contract lookup still scan the
workflows directory, and #125 replaces both with that index. #123/#125 own exact field names,
alias indexing, grouped-run mapping and closed schema mechanics.

### Immutable entry subject and later delivery output

An attempt starts before its final reviewed commit exists. Its immutable entry subject records the
repository/issue, concrete authorized deliverable and scope, exact starting inputs and versioned
profile. This is a distinct **attempt-entry intent subject**, not a release candidate with an empty
or mutable commit field. The profile fixes action membership, required postconditions, proof and
recovery plans at creation. Changing the deliverable or required gates creates a new linked subject;
changing worktree HEAD never changes the existing one.

The semantic generalization of #82 is a typed entry subject for this consumer, while preserving
the release consumer's immutable candidate manifest and versioned profile at creation unchanged.
Implementation must compile that distinction in #123/#125's strict schema/profile package before
admission; this record does not invent a parallel profile grammar or weaken release conformance.

Later products are outputs of predeclared actions. Core selection records the exact artifact
digest/reviewed commit, producing action and attempt, source and fence as immutable evidence before
any delivery effect. A predeclared proof input may refer to that selected output; it is resolved to an exact
identity before its dependent effect or proof can run. Selection cannot add actions, widen scope or
change the immutable subject/obligations. A new output requires explicit selection/revalidation and
fresh candidate-bound proof/authority where needed, retaining the previous selection in history.
No unresolved output reference authorizes a delivery effect (the merge or any later stage); no
moving branch or local HEAD substitutes for the reviewed SHA. This permits real implementation
work without pretending its result was known at transaction creation.

Shipped mapping (per D13). `delivery-contract/v1` is today's attempt-entry intent subject: the
deliverable, four obligations, ordered stages with targets and worktree requirements, the initial
authorization intent and provenance. `workflow-state build-delivery` derives it read-only from
resolved policy and invocation facts, and it is immutable once installed. `selected-output/v1` is
the selection: it binds the contract's `reviewed` slot once, at the pre-merge gate on the final
CI-green head, and the slot PR binding narrows open/merge without a new grant. Review publication
(branch push, review PR, fix pushes, CI) precedes selection under the native guard and launch
fence; it is review staging, not delivery. #125 must admit it as a declared, fenced profile action.
The contract carries no profile version or #88 proof plan, and a changed deliverable is refused
rather than linked to a successor subject; #123/#125 own both.

### Suspension and adapter vocabulary

| Core vocabulary/policy | Adapter or host responsibility |
|---|---|
| Nonterminal suspension; blocked-on set `usage_limit`, `transport`, `human_gate`, `external`, `unknown`, plus control-only `host_capacity` (D10) | Provider quota/transport recognition, host launch-refusal reports and readable diagnostics. |
| Auto-resume subset `usage_limit`, `transport`, `unknown`, and `host_capacity` gated on a later non-refusal claim release; human-directed resume for other reasons after checks | Native notification/wakeup transport and tracker dependency observations. |
| Resume consumes no execution attempt; suspension resume receives a fresh full budget window | Phase numbers, skill names, artifact paths and readiness predicates. |
| Monotonic recorded progress token and no-progress stall bound of three | Domain validation of meaningful progress and translation from phase progress. |
| Synthetic versus authentic result provenance and immutable events | Legacy `merged/stopped/failed` rendering and provider status translation. |
| Fenced custody, scoped grants, inspect-before-effect | Worktree observation, host capabilities and credential resolution. |

`unknown` is reaper-derived and `host_capacity` is derived by control from a host launch refusal;
neither is owner-supplied. Suspension is an attempt fact beneath core nonterminal
attention/recovery; it adds no fifth transaction terminal. The persisted counter is 0 at the first
suspension at a progress token (the phase for an attempt, the progress token for a remainder), then
1 and 2; each of those three suspensions may resume, and the fourth consecutive one stops automatic
dispatch as `stalled`. Meaningful progress resets that streak. Repeated unpersisted observations
cannot inflate it. A synthetic stalled disposition parks unknown reality; it does not prove core
failure.

### Expiry and launch compatibility

Preserve #133's **fixed wall-clock attempt deadline**, independent of progress timestamps and effect
lease renewal. Active or handed-off expiry suspends as `unknown`, spends no execution attempt and
can resume in place with a fresh full window. Ordinary handoff/dead-owner resume inside an unexpired
window retains its original deadline. Lease renewal neither extends that deadline nor resets stalls.

Observed merge reconciliation precedes expiry/stall classification. Reaping remains next-touch in
control/direct-owner, not a new background timer; same-sweep resume occurs when existing tracker,
capacity and recorded-worktree checks allow it, otherwise a later eligible sweep may resume. The
direct caller resumes in the same call when eligible. Preserve handoff validation whenever its path
is returned, the phase-zero absent-worktree exception, and refusal of mismatch or absence after
phase zero. Never silently relocate. Preserve owner-failed and legacy stopped(expiry) retry entrances,
their cap and refusal lineage; do not retroactively reclassify historical retry_refused accounting.

#132's current-launch query remains read-only: no clock, lock creation, lazy reaper, directory
creation or state write; older schemas are validated on a detached copy. It answers both action-id
forms and reports a launch inactive once delivery completes. It runs before every forge
or `origin` write through the merge and before and after each post-selection delivery effect;
false, missing helper, nonzero or malformed output refuses the effect and the stale caller makes no
ledger/cleanup write. Compare the forge head to the immutable reviewed SHA. Interface-2 checkpoints
and summary finishes already recheck custody under the ledger lock, an inner check for ledger
writes. Forge effects still have only this precheck plus the guard; the new inner enforcement
closes that check/invoke race for admitted effects.

### Custody and races at invocation

Bind execution custody to subject, attempt, launch, exact repository/worktree identity and the
ordered scoped fence vector. Every core mutation and effect must validate that binding at its owning
interface; a caller-supplied current directory or phase is not authority. The actual mutation route
must enforce the current fence and candidate/preconditions; merely checking before a subprocess is
insufficient. Unsupported enforcement is inadmissible, not an optimistic permission grant. #125
owns lifecycle integration; provider/guard conformance remains with its owning implementation.

Lease validity uses the authority's clock. Same live holder and instance renewal increments only
lease_term; lapse, ownership transfer or same-owner reacquisition after expiry advances lease_epoch
for affected keys. Renewal is the core's duty. No new launch steals a valid lease. Voluntary handoff
quiesces/releases old custody before the successor acquires; expiry of the workflow window withdraws
old launch rights even if core observation custody still needs renewal for an unresolved call.

After lapse, event evidence survives if authentic; scoped snapshots are superseded and recollected;
intervals spanning the gap break and restart; scoped executable grants are invalid. An unavailable
lease authority produces lease_state_unknown attention, never presumed validity. Preserve #92's
hold-and-try rule: bounded reacquire of a lapsed key, then release the rest and reacquire canonically
if unsuccessful. Parked custody uses the finite capped quiesce window. Observe an issued external
call before release; unresolved observation deadlines park without blind replay or granting an old
owner new rights. An authenticated late result enters a separate observation intake under current
core authority; it is never a stale executor's privileged state mutation.
Authenticity permits retaining a report, not accepting it as required proof: a historical event
must establish its then-valid fence, and current deterministic inspection must establish any
remaining exact-output/postcondition proof. Evidence first produced under stale custody cannot
masquerade as an admissible historical event.

### Host admission and authorization continuity

Host admission is #150's shipped mechanism (per D10). The host declaration gives each route its
support and, when supported, its `agent_slots` per root session. `workflow-state control` claims
the whole fixed role set (owner, worker and independent reviewer) in the step that creates a
launch, beside one controller claim per run. It dispatches only when both `max_parallel` and a free
role set allow; otherwise the issue is `waiting`, recomputed each sweep, and no launch or attempt is
spent. One commit-time settle releases a claim in the write that ends its custody, and the
owner-exit notification wakes the next sweep. A host-refused launch parks as `host_capacity`,
releases its claim and resumes only after a later non-refusal release, within the stall bound.
`host-route` returns the typed supported/unsupported answer: `claude-code` is supported, `codex` is
declared unsupported, and the single-owner `direct` route records no claims. Nothing schedules CPU,
memory or Nix-daemon load, and nested launches beyond one worker and one reviewer stay outside the
accounting. #125 moves claims into core state, bound to custody and released atomically with the
custody transition. Route names, the
declaration and role-set sizes stay host/adapter policy, so the core's neutrality check holds.

Authorization continuity is #151/#171's shipped wire (per D11). The secret-free
authorization-intent reference is `authorization-intent/v1`: source kind, reference and evidence
digest, issue time, optional expiry, revocation key and exact `scope-tuple/v1` scopes (principal,
action, effect, target, endpoint, data, risk, spend), bound to the contract's deliverable. The
ledger holds the chain append-only. `ship-handoff/v2` carries it with a builder-sealed chain digest;
a requested scope crosses a handoff only as a historical echo, never inherited. `build-delivery`
derives every scope from the contract stage, never from the intent, and the principal is stable
across attempts and remainders, so an unchanged authorized task matches exactly without re-asking.
The intent is not an executable grant and survives custody loss only as durable evidence of intent,
subject to its own validity limits.

On reacquisition the launch fence runs first; the model then matches the requested scope against
the current contract, selection, time and revocations. Covered scope permits one native
guard/host/provider evaluation of that effect, recorded as an `authority-observation/v1` bound to
that launch; an allow is never a future grant. Uncovered scope returns the
`authorization_intent_required` human gate naming the exact tuple. A rejection stays operative
across handoffs until a post-rejection successor intent covering that tuple, or accepted
reevaluation evidence, permits one fresh evaluation, consumed once. The shipped engine therefore
persists no executable grant. The core's #84 scoped reversible grant may exist only as a derivative
minted from intent for the current launch and epoch, carrying its fence snapshot, never inferred
from an `allowed` observation. #84/#90 irreversible confirmations remain fresh, single-use and
candidate-specific: general delegation or an old intent cannot silently remint one after
invalidation. Broader scope, changed principal/risk/spend or extra invocation authority requires its
declared gate. Host automatic approval denial is authoritative and recorded, never bypassed. The
core adopts #151's wire objects as its authority vocabulary rather than defining a parallel one.

### Terminal truth and named scenarios

Keep exactly `succeeded`, `abandoned`, `rolled_back`, `failed`. Success needs the immutable plan's
applicable proof; abandoned needs absence of declared effects; rolled_back needs declared recovery
and proof; failed needs settled positive grounds and exhausted declared recovery, including #94's
human-only effects_unobservable exception, qualifier and hazard rules. Unknown reality otherwise
parks. Owner failure may close an execution attempt and permit retry without declaring core failed.

Observe **implementation delivered, PR merged, tracker closed, cleanup complete** independently,
with exact subject, source, time and evidence. Missing data never means not applicable; applicability
is predeclared. Partial completion remains visible while the authorized remainder is reconciled.
Cleanup required for deliverable success must be proved before that success. Runtime-ledger deletion
is a separate post-terminal #72 operation and cannot be a circular prerequisite of its own receipt.
Shipped: the contract fixes each obligation as `required` or `not_applicable`; the ledger holds
each postcondition as `pending`, `observed` or `not_applicable`, bound to one
`delivery-observation/v1`, beside one fact per contract stage. Migration promotes no legacy result
into that truth, and `ship-summary/v2` reports `delivery_complete` only when all four are settled.
The core seals these as receipt content (#123).

Work still pending after the implementation attempt closes gets **delivery-remainder custody** (per
D12): its own ordinal capped at two, independent of the attempt cap; `issue:r<n>:launch` launches;
and at most one nonterminal custody across both lineages. It follows the same fence, expiry,
suspension and stall rules, including a fresh full window on every suspension resume; the shipped
remainder lane refreshes it only once the deadline has passed, and #125 aligns it. Forge
reconciliation, direct or control, runs only without live custody and only on a nonterminal or
retryable latest attempt, never over a final owner verdict: it records the truthful merged closeout
and mints remainder one for the pending stages.

Close before merge (per D15): while merge is pending, an observed tracker closure withholds dispatch
and merge admission in every custody lineage until its reason, where the tracker supplies one, and
the remaining intent are inspected. It writes no terminal, cancels no stage and grants nothing; a
reopened tracker or a human-directed resume after that inspection releases the hold. After merge,
closure is only the `close_tracker` observation.

Synthetic expiry/stall stops are provisional operational dispatch dispositions. A later authentic
owner report may supersede them as evidence while both events remain recorded; it never restores
stale mutation authority. The core reconciles selected subject-bound facts before terminal sealing.
Receipt bytes are content-addressed, stored and read back before atomic close. A sealed terminal
never reopens; later observations use immutable linked evidence/receipt supplements, not replacement
bytes or extra terminals. Required collectors are deterministic; model verdicts stay advisory.

| Named scenario | Required outcome | Shipped engine today |
|---|---|---|
| Owner expires; reaper observes | Suspend/park; withdraw old launch effect rights; no new execution attempt for expiry. | Next-touch reap suspends `unknown` in place; the claim releases; the old launch answers inactive, then superseded. |
| Late owner after synthetic stop | Authenticate subject/launch evidence; preserve both events; reconcile under current custody before sealing. | Legacy finish replaces a synthetic `expiry`/`stalled` result in place, losing that event (#125 gap). |
| Late owner after successor launch | Refuse old progress/effects as fencing violations; useful authentic evidence remains tied to its original launch, not successor authority/verdict. | `check-launch` refuses its forge writes and v2 writes recheck custody; `progress`, `suspend` and legacy finish check only the attempt ordinal (#125 gap, D16). |
| Worktree misbinding | Refuse before any write as subject/custody fencing violation, not a write conflict or relocation. | The contract binds custody's worktree and a mismatch refuses without a write or relocation; the working directory is not yet fenced. |
| Merge before tracker close | Retain merge proof, reconcile authorized tracker/cleanup remainder; never rebuild or remint an implementation attempt. | Forge reconciliation closes out the attempt and mints remainder one (D12). |
| Tracker close before merge | Record closure only; inspect its reason and remaining intent, respecting possible human cancellation; resume only if authorized, otherwise park for precise disposition (D15). | A suspended attempt is withheld from resume without a write; remainders and a live owner's merge ignore closure (#125 gap). |
| Renewal during long proof | Same epoch; scoped grants/evidence survive, independent attempt budget still expires. | No lease exists; only the fixed deadline. |
| Lapse during proof/handoff | Advance affected epoch; retain events, recollect snapshots, restart broken intervals, obtain new executable authority before effect. | No epoch exists; the launch fence and per-effect evaluation are the only invalidation. |
| No worker/reviewer slot | Queue before launch/attempt consumption; capacity completion event wakes the queue. | `waiting` before launch; settle release and owner-exit wake (D10). |
| Merge/CAS race or uncertain invocation | Inspect absent/in_progress/satisfied/diverged/unknown; only absent plus retry eligibility permits retry; divergence or unknown parks. | Tip check and the guard only; no compare-and-set. |

For the last row, an observed candidate head check is not atomic compare-and-set on the prior target
tip. #90's old equation of the two is not a conformance proof. Provider admission must establish the
real target/candidate precondition at mutation; #124/provider-guard work owns that mechanism. This
decision adds no command spelling or provider authority.

### Migration, rollout and rollback

Inventory all old dialects and lineage in a deterministic read-only dry run, which passes over the
retained ledgers before the migrating helper is activated. Forward migration then applies that
identical transform on write under the owning module's lock (per D14): adjacent,
atomic and idempotent, refusing unexpected, partial or ambiguous state without overwriting evidence,
as the shipped 1→2→3→4 steps already do. Preserve historical observations and alias lineage,
without treating synthetic stops as core failed receipts. Live legacy owners continue because the
compatibility adapters accept every legacy owner transport (progress, suspend, check-launch, legacy
finish) against migrated core truth. Accepting them does not waive D5's fence (per D16): an
attempt-keyed transport binds to the launch current when its state migrated and is admitted only
while that launch stays current; after a successor launch it is a fencing violation, and any result
it carries enters the late-result intake. Owners launched after the cutover name their launch on
every write. The legacy location stops being writable by any older helper,
which refuses newer state without mutation, so neither a dual writable store nor an old-generation
writer exists. Compatibility renderers serve old interfaces from core truth.

State-schema migration is distinct from #66 project-contract migration and platform activation.
Retain a bridge able to read the migrated state; rollback uses that generation at quiescence, never
an old writer against unknown/newer state or an ad-hoc reverse transform. Freeze and retain evidence
if compatibility cannot be proved. Project changes still use the one-commit rollback under the
compatible bridge. Support retirement requires zero fleet users, a verified successor, candidate and
retained-bridge preflights; adjacent migration records remain executable after normal-reader removal.

The owning module supplies explicit runtime roots under #72; this decision performs no layout move
and does not override today's resolved artifact paths. Active/handed-off state is never auto-deleted.
Successful cleanup needs durable authoritative results and disposable referenced worktrees; failed
or stopped residue needs acknowledged cleanup and renewed disposability proof. Worktree removal
also refuses uncommitted work, unpushed commits, live/retained runs or unresolved tracker/branch
ownership. Age and an expired lease confer no deletion authority.

[#123](https://github.com/fagenorn/nix-config/issues/123) delivers state/identity/leases, then
inspect/retry/write intent, then proof/receipts; it retains the four-shape/fourteen-scenario sweep and
core-neutrality check including #91–#94. [#125](https://github.com/fagenorn/nix-config/issues/125)
delivers schema/identity, custody/late-result receipts, then control cutover, passing the migrated
regression floor at each package. #150, #151 and #171 are delivered engine contracts; #125 ports
their admission claims, delivery contract, intents, observations and remainders onto the core rather
than recreating them, and closes the gaps named above. Only after that conformance does ship-release
follow under #90/#124, including its distinct no-import, quiescent legacy-release cutover. #123,
#124 and #125 remain open; this record claims no core implementation.

## Test seams

Three seams carry acceptance, following the existing workflow-state contract suite and #85 adapter
interface; internal helper call counts cannot substitute for observable behavior.

1. **Core transaction interface:** immutable subject and selected-output binding; create deduplication;
   retry ordinals; authority-clock renewal/lapse; evidence/grant invalidation; authentic late-result
   intake; receipt store/read-back before seal; partial postconditions and never-reopened terminals.
2. **Compatibility workflow-state/control interface:** port the existing lifecycle regression floor,
   retaining #132/#133 projections except explicitly declared schema changes. The floor includes the
   schema-4 admission and claim-release tests, the #150 replay's committed exact-match baseline, and
   the delivery suite: builder CLI, contract-last acquisition, delivery loop, legacy finish on
   migrated issues, forge reconciliation and remainders. Cover all legacy aliases including remainder
   launch references, ambiguous migration refusal, migrate-on-write under a live legacy owner,
   an attempt-keyed transport after a successor launch (D16), repeated migration, quiescent rollback, same/later-sweep resume, phase-zero absence versus
   mismatch, handoff deadline/path, exact three-resume stall arithmetic, historical retry
   entrances/cap and merge-before-reap ordering. Check-launch must leave state and filesystem
   untouched even for expired/unknown rows and helper failures must block effects.
3. **Actual mutation guard/adapter and host seams:** interleave stale launch, reaper, renewal, lapse,
   misbound worktree and successor between precheck and invocation. No forbidden write may occur.
   Advance target tip while candidate stays fixed, and vice versa: provider mutation must refuse
   stale preconditions. Replay exhausted host slots through #150's limited-slot and scripted-refusal
   variants and unchanged/broadened intent through #151's simulated cases; verify queue wakeup,
   independent review capacity, authoritative denial and exact missing grant. Close the tracker
   before merge under remainder and live custody (D15).

The scenario table is the adversarial review result: each potential conflation has an explicit
outcome. Acceptance cross-check, one row per issue criterion:

| Criterion | Covered by |
|---|---|
| First consumer and order of the second | Solution; Migration; D1 |
| Adoption shape, new-run identity, legacy dialects readable | Solution; Ownership and identities; Migration; D1, D2, D12, D14 |
| Core versus adapter-local suspension semantics | Suspension; D4, D10 |
| Custody as fencing: reaper versus owner, worktree misbinding | Custody; Expiry; scenario table; D5, D16 |
| #132/#133 launch and expiry preserved and mapped | Expiry and launch compatibility; D4, D12 |
| Declared host capability owns worker slots; queue, not spawn retries | Host admission; D6, D10 |
| Four separately observed postconditions | Terminal truth; D7, D12 |
| Late owner, reaper, misbinding, merge-before-close, close-before-merge outcomes | Scenario table; D7, D15 |
| Authorization crosses handoffs without broadening or re-asking | Authorization continuity; D6, D11 |

No criterion is delegated away as a decision. Exact implementation mechanics and executable tests
are downstream work. This documentation-only decision makes no runtime-test or live-conformance
claim.

## Out of scope

Runtime implementation or activation; platform/core/adapters or permission-guard changes; changes
to the shipped #150/#151/#171 engine mechanisms, whose gaps named here belong to #125; provider
mutation; schema field spelling, grouped-run compilation and downstream profile mechanics; general
host scheduling; project-root/layout migration; release execution; new provider commands; weakening
#82/#88/#91–#94 proof or terminal rules. This record grants no publication, merge, tracker or cleanup
authority. A separately scoped delivery authorization may govern those actions, subject to current
host enforcement; this record neither grants that permission nor weakens an actual denial.

## Decision ledger

All choices below are agent judgments under delegated authority, constrained by the cited settled
decisions. They are not recorded human answers.

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Attempt lifecycle first; reimplement its interface over the sole state module; release second after conformance. | #117 operating evidence; #82 single authority; #85 neutrality. | Absorb phase/host engine internals or mirror ledgers: leaks domain policy or preserves conflicting truth. |
| D2 | Mint rel_ UUIDv7 per immutable issue-delivery subject; separate attempts, launches and invocation retries; retain typed legacy/group aliases. | #82 identity and retry model; #117/#125 lineage; #66 migration. | New run_ dialect or one group transaction: splits identity authority and conflates independent subjects. |
| D3 | Freeze attempt-entry intent/profile; select exact produced outputs as fenced proof inputs; preserve release candidate-at-creation semantics. | #82 immutable subject; #88 immutable proof plan; #90 candidate boundary. | Pretend final commit exists at entry or use moving HEAD: allows identity drift and unreviewed publication. |
| D4 | Promote suspension taxonomy, bounded stalls and provenance; keep phases/provider mechanics adapter-local and fixed attempt time independent of leases. | #132/#133; #85 interface; #92 renewal; current three-resume arithmetic. | Reset budget on progress/renewal or count expiry as retry: restores unbounded or environment-dependent accounting. |
| D5 | Fence every mutation/effect by subject/launch/worktree and scoped lease vector; intake late evidence under current authority. | #82/#92; #132 residual race; the-bar defense in depth. | Advisory precheck alone or stale finish writes: permits successor corruption and misbinding. |
| D6 | Consume declared #150 slot reservations before launch; retain #151 intent across handoffs while reissuing only eligible fenced grants. | #117 added criteria; #150/#151; #84/#90/#92. | Spawn retries or inherited executable grants: wastes attempts or carries revoked custody/irreversible authority. |
| D7 | Keep four real terminals, provisional synthetic dispositions and separate delivered/merged/closed/cleanup observations; seal immutable receipts. | #82/#88 and #94 as retained by #123; #72 cleanup; #117 races. | Map stopped to failed or merge to total completion: manufactures truth and loses authorized remainder. |
| D8 | Use quiescent adjacent migration with aliases, retained compatible rollback and staged interface/race conformance. | #66/#72; #123/#125 package contracts; #132/#133 regression floor. | Dual writes, directory discovery or happy-path-only cutover: loses lineage, fencing and rollback proof. |
| D9 | Refresh the accepted record in place against main `17da7f2`, reached by merging `origin/main` at Phase 1, and accept git's relocation of the artifacts into the resolved `.agents/artifacts/` paths; map shipped mechanisms onto D1–D8, with an amending row only where shipped code contradicts one. | Orchestrator's Phase-1 sync; resolved `bindings.paths.artifacts`; the-bar "moves keep their history"; #117's nine criteria. | Rebase (rewrites signed commits and hides the accepted base) or restart (discards a grilled record the shipped code does not contradict). |
| D10 | Amends D4 and D6: host admission is #150's shipped declared per-route slots, fixed owner/worker/reviewer role set claimed with the launch plus a controller claim, recomputed `waiting`, commit-time release and completion wake; core vocabulary gains control-only `host_capacity` for a host-refused launch, resumable after a later non-refusal release; unavailable slots stay pre-launch waiting; #125 holds claims in core state, routes and role sets stay host policy. | #150 D4–D7, D26, D31; #117 "queues work rather than consuming attempts"; #85/#123 neutrality; the-bar DRY. | D6's letter (no sixth cause) sends refused launches back to `unavailable`, the measured spawn loop; per-need slot sets are YAGNI and cannot guarantee a reviewer. |
| D11 | Refines D6: authorization continuity is #151/#171's wire: the `authorization-intent/v1` chain, builder-derived scopes, per-effect evaluation after the launch fence recorded per launch, rejection cleared only by a covering successor intent or reevaluation evidence consumed once, and `ship-handoff/v2` with a sealed chain digest and uninherited scope; the core adopts it, minting any #84 grant for the current launch and epoch only. | #151 authority rules and D18; #171 D3, D5, D7, D43; #84/#92; #117 handoff criterion. | A parallel core authority grammar (two homes) or treating a prior `allowed` observation as a grant on reacquisition (carries authority across custody loss). |
| D12 | Amends D2 and D7: delivery-remainder custody is a second custody lineage in the same transaction, with its own ordinal capped at two, `issue:r<n>:launch` aliases, one nonterminal custody across lineages, and the attempt fence/expiry/stall rules, including a fresh full window on every suspension resume, which the shipped remainder lane grants only once its deadline has passed. | #151 remainder custody; #171 D13, D14; #133 fresh-window rationale; #117 merge-before-close outcome. | A new execution attempt (spends the cap, rebuilds shipped work) or a separate transaction (two truths for one subject); per-lane window rules (a leftover window expires into a stall step). |
| D13 | Amends D3: `delivery-contract/v1` and `selected-output/v1` realize the entry subject and selection; selection stays at the pre-merge gate after review publication, so D3's publication rule governs delivery effects only, and #125 admits review publication as a declared, fenced action. | #171 D3, D4, D7, D15; #151 slot narrowing; D5's every-effect fencing. | Selecting before review publication (sync and fix pushes move the head, so merge never matches) or treating review publication as delivery (an unselected head would carry delivery authority). |
| D14 | Reverses D8's quiescent forward migration and retained old-generation writer: migration applies the dry run's transform on write under the owning lock, live legacy owners continue through legacy transports the adapters still accept, and older helpers refuse newer state; quiescence remains for rollback and the release cutover. | #171 D11 after a mid-run migration stranded three merged PRs; #151's bridge never shipped; #66 adjacency and retained reader; #125 dry run first. | Quiescent cutover (nothing enforces quiescence) or a retained legacy-writer bridge (a second writable store). |
| D15 | Refines D7's close-before-merge outcome: while merge is pending, an observed tracker closure withholds dispatch and merge admission in every custody lineage until its reason and remaining intent are inspected, writing no terminal and cancelling no stage; after merge it is only the `close_tracker` observation; #125 extends the shipped attempt-lane hold to remainders and live-custody merges. | #117 criterion; #151 "a closed tracker neither cancels a stage nor supplies a grant"; the shipped suspended-attempt hold; the-bar defense in depth. | The remainder lane's indifference (could merge over a human cancellation) or halting every remainder on closure (strands post-merge cleanup whose closure is expected). |
| D16 | Refines D5 and D14: legacy continuity never waives the launch fence. An attempt-keyed transport (`progress`, `suspend`, legacy finish) binds to the launch current when its state migrated and is admitted only while that launch stays current; after a successor launch it is a fencing violation and its result enters the late-result intake; post-cutover owners name their launch on every write. | Grill: those transports carry no launch identity today; #125 late-owner and misbinding criteria; D5; the-bar defense in depth. | Accept attempt-keyed writes as today (a superseded owner mutates its successor's custody) or refuse every legacy transport at cutover (strands live owners, the #171 failure). |
| D17 | Correct the record's shipped-engine inventory in place (the "Shipped engine today" cells, shipped-behavior prose and D15's gap clause), because it states live-code facts, not choices; an amending row stays reserved for a changed choice. | Plan-phase audit of the branch's live code: an unexpired handed-off attempt resumes over a closed tracker, a v2 report after a stop refuses as not current, `host-route` refuses `direct`; D9's in-place refresh of this unshipped record. | An amending row per factual fix (logs non-decisions, leaves D15's clause wrong) or leaving the inventory as written (#125 would port without the handed-off and late-v2 gaps). |
