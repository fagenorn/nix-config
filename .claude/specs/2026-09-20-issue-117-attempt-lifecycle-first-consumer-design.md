# Attempt lifecycle as the transaction core's first consumer

Decision for [#117](https://github.com/fagenorn/nix-config/issues/117), 2026-09-20.
Status: architecture decision under delegated authority; implementation remains downstream.
The choices here are agent judgments within the caller's authorized reversible decision scope,
not claims that a human selected these options. The issue's historical human-required label
does not describe the delegation used for this record.

## Problem

The existing attempt engine and the proposed release core independently own lifecycle policy.
Attempts already exercise suspension, retries and late results, but lack custody fences and
evidence invalidation. A synthetic stop can conflict with delivered work; a stale executor can
write in the successor's shared worktree. Releases have not supplied equivalent operating load.

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

Local grounding: CLAUDE's lifecycle/storage guidance, the-bar's defense in depth, DRY and truthful
terminal states; the committed #132/#133 designs and current workflow-state suspension, resume,
finish, control and check-launch behavior. No context-map or ADR tree exists; this record follows
the existing spec convention and the architecture doc links to it. The host-contention rejection
excludes CPU/memory/build-load scheduling. [#150](https://github.com/fagenorn/nix-config/issues/150)
and [#151](https://github.com/fagenorn/nix-config/issues/151) own executable capacity and authority
propagation; their current prose delivery is not runtime conformance evidence.

## Decisions

### Ownership and identities

The deep transaction-state module alone owns strict state, its stable short advisory lock, atomic
read–validate–replace and typed append-only history. The lock serializes state updates; it is not
an effect lease or proof of custody. Compatibility output is derived from core state. Host task
handles and provider references remain typed external references, never transaction identities.

New core transactions use **`rel_` + UUIDv7**, including attempts: do not mint `run_` or new legacy
dialects. Creation deduplicates by a caller creation key. One transaction owns one immutable
issue-delivery subject, with monotonically numbered execution attempts and launch generations.
A resume retains the execution-attempt ordinal and gets a new launch identity; a genuine terminal
attempt retry increments that ordinal, retains predecessor lineage and the existing attempt cap.
Per-action invocation retry ordinals are separate: #82's initial invocation plus at most two
automatic retries within fifteen minutes cannot spend/reset a workflow attempt. Profiles may
lower those invocation limits, never raise them. Stable deterministic action IDs identify declared
actions; legacy `issue:attempt:launch` is a launch reference, not such an action ID.

A grouped orchestration run is a controller/collection reference to issue transactions. It is not
a shared mutable transaction or a second identity authority. Preserve all four legacy dialects as
typed aliases with original dialect, issue/grouping, attempt/launch and predecessor lineage. A
group alias need not resolve to one transaction; its issue member disambiguates. Unknown dialect,
schema or ambiguous lineage blocks migration rather than guessing from directory names. Canonical
lookup uses the state module's index and an explicit ledger root. #123/#125 own exact field names,
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
publication. A predeclared proof input may refer to that selected output; it is resolved to an exact
identity before its dependent effect or proof can run. Selection cannot add actions, widen scope or
change the immutable subject/obligations. A new output requires explicit selection/revalidation and
fresh candidate-bound proof/authority where needed, retaining the previous selection in history.
No unresolved output reference authorizes publication; no moving branch or local HEAD substitutes
for the reviewed SHA. This permits real implementation work without pretending its result was known
at transaction creation.

### Suspension and adapter vocabulary

| Core vocabulary/policy | Adapter or host responsibility |
|---|---|
| Nonterminal suspension; blocked-on set `usage_limit`, `transport`, `human_gate`, `external`, `unknown` | Provider quota/transport recognition and readable diagnostics. |
| Auto-resume subset `usage_limit`, `transport`, `unknown`; human-directed resume for other reasons after checks | Native notification/wakeup transport and tracker dependency observations. |
| Resume consumes no execution attempt; suspension resume receives a fresh full budget window | Phase numbers, skill names, artifact paths and readiness predicates. |
| Monotonic recorded progress token and no-progress stall bound of three | Domain validation of meaningful progress and translation from phase progress. |
| Synthetic versus authentic result provenance and immutable events | Legacy `merged/stopped/failed` rendering and provider status translation. |
| Fenced custody, scoped grants, inspect-before-effect | Worktree observation, host capabilities and credential resolution. |

`unknown` is reaper-derived, never an owner-supplied reason. Suspension is an attempt fact beneath
core nonterminal attention/recovery; it adds no fifth transaction terminal. Three consecutive
resumes without progress are permitted; the next suspension stops automatic dispatch. The counter
starts at zero on the first suspension at a progress token, then records one, two, three as resumes
are spent. Meaningful progress resets that streak. Repeated unpersisted observations cannot inflate
it. A synthetic stalled disposition parks unknown reality; it does not prove core failure.

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
creation or state write. It runs immediately before push/create/merge; false, missing helper,
nonzero or malformed output refuses the effect and the stale caller makes no ledger/cleanup write.
Compare the forge head to the immutable reviewed SHA. This precheck remains an early refusal, while
the new inner enforcement closes its check/invoke race for admitted effects.

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

Consume #150's declared host capability: inspect and reserve controller, owner, worker and independent
reviewer slots actually required before minting a launch or spending an attempt. Unavailable slots
queue work; observed completion atomically releases reservations and wakes the queue. Do not infer
nested capacity from max_parallel, repeatedly retry spawning, or add host capacity as a sixth
suspension failure cause. Unsupported host routes report unsupported. No CPU/memory/nix-daemon
scheduler or release-adapter scheduling is introduced.

Carry a secret-free **authorization-intent reference** through handoffs: issuer/source, deliverable,
repository/target, allowed action/effect set, principal and risk/spend limits, expiry/revocation and
candidate-specific scope where present. It preserves an unchanged authorized task without replaying
the conversation. It is not an executable grant and survives custody loss only as durable evidence
of intent, subject to its own validity limits.

On reacquisition, inspect first and evaluate intent against current exact subject, fence and principal.
Issue a new reversible executable grant only when that intent authorizes issuance within unchanged
scope; otherwise name the missing authority. Scoped grants never survive a relevant epoch change.
#84/#90 irreversible confirmations remain fresh, single-use and candidate-specific: general
delegation or an old intent cannot silently remint one after invalidation. Broader scope, changed
principal/risk/spend or extra invocation authority requires its declared gate. Host automatic approval
denial is authoritative and recorded, never bypassed. #151 owns propagation/reconciliation; this
decision supplies its semantics, not a competing authorization implementation.

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

Synthetic expiry/stall stops are provisional operational dispatch dispositions. A later authentic
owner report may supersede them as evidence while both events remain recorded; it never restores
stale mutation authority. The core reconciles selected subject-bound facts before terminal sealing.
Receipt bytes are content-addressed, stored and read back before atomic close. A sealed terminal
never reopens; later observations use immutable linked evidence/receipt supplements, not replacement
bytes or extra terminals. Required collectors are deterministic; model verdicts stay advisory.

| Named scenario | Required outcome |
|---|---|
| Owner expires; reaper observes | Suspend/park; withdraw old launch effect rights; no new execution attempt for expiry. |
| Late owner after synthetic stop | Authenticate subject/launch evidence; preserve both events; reconcile under current custody before sealing. |
| Late owner after successor launch | Refuse old progress/effects as fencing violations; useful authentic evidence remains tied to its original launch, not successor authority/verdict. |
| Worktree misbinding | Refuse before any write as subject/custody fencing violation, not a write conflict or relocation. |
| Merge before tracker close | Retain merge proof, reconcile authorized tracker/cleanup remainder; never rebuild or remint an implementation attempt. |
| Tracker close before merge | Record closure only; inspect its reason and remaining intent, respecting possible human cancellation; resume only if authorized, otherwise park for precise disposition. |
| Renewal during long proof | Same epoch; scoped grants/evidence survive, independent attempt budget still expires. |
| Lapse during proof/handoff | Advance affected epoch; retain events, recollect snapshots, restart broken intervals, obtain new executable authority before effect. |
| No worker/reviewer slot | Queue before launch/attempt consumption; capacity completion event wakes the queue. |
| Merge/CAS race or uncertain invocation | Inspect absent/in_progress/satisfied/diverged/unknown; only absent plus retry eligibility permits retry; divergence or unknown parks. |

For the last row, an observed candidate head check is not atomic compare-and-set on the prior target
tip. #90's old equation of the two is not a conformance proof. Provider admission must establish the
real target/candidate precondition at mutation; #124/provider-guard work owns that mechanism. This
decision adds no command spelling or provider authority.

### Migration, rollout and rollback

Inventory all old dialects and lineage in a deterministic read-only dry run. Apply one adjacent
state-schema migration atomically at a quiescent checkpoint; rerun is idempotent and unexpected,
partial or ambiguous state refuses without overwriting evidence. Preserve historical observations
and alias lineage, without treating synthetic stops as core failed receipts. In-flight old rows stay
with a compatible retained generation until quiescent. No new-core writer races a live legacy writer;
no dual writable store exists. Compatibility renderers can serve old interfaces from core truth.

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
regression floor at each package. It consumes #150/#151 rather than recreating them. Only after that
conformance does ship-release follow under #90/#124, including its distinct no-import, quiescent
legacy-release cutover. This decision is no claim that those dependencies are implemented.

## Test seams

Three seams carry acceptance, following the existing workflow-state contract suite and #85 adapter
interface; internal helper call counts cannot substitute for observable behavior.

1. **Core transaction interface:** immutable subject and selected-output binding; create deduplication;
   retry ordinals; authority-clock renewal/lapse; evidence/grant invalidation; authentic late-result
   intake; receipt store/read-back before seal; partial postconditions and never-reopened terminals.
2. **Compatibility workflow-state/control interface:** port the existing lifecycle regression floor,
   retaining #132/#133 projections except explicitly declared schema changes. Cover all legacy aliases,
   ambiguous migration refusal, repeated migration, quiescent rollback, same/later-sweep resume,
   phase-zero absence versus mismatch, handoff deadline/path, exact three-resume stall arithmetic,
   historical retry entrances/cap and merge-before-reap ordering. Check-launch must leave state and
   filesystem untouched even for expired/unknown rows and helper failures must block effects.
3. **Actual mutation guard/adapter and host seams:** interleave stale launch, reaper, renewal, lapse,
   misbound worktree and successor between precheck and invocation. No forbidden write may occur.
   Advance target tip while candidate stays fixed, and vice versa: provider mutation must refuse
   stale preconditions. Replay exhausted host slots and unchanged/broadened intent through #150/#151;
   verify queue wakeup, independent review capacity, authoritative denial and exact missing grant.

The scenario table is the adversarial review result: each potential conflation has an explicit
outcome. Acceptance cross-check: first/order and adoption/identity are covered by Ownership and
Migration; core/adapter vocabulary by Suspension; custody and all five named races by Custody and
Terminal truth; #132/#133 by Expiry; host admission and authority handoffs by their joint section;
the four independent postconditions by Terminal truth. No criterion is delegated away as a decision.
Exact implementation mechanics and executable tests are downstream work. This documentation-only
decision makes no runtime-test or live-conformance claim.

## Out of scope

Runtime implementation or activation; platform/core/adapters or permission-guard changes; provider
mutation; schema field spelling, grouped-run compilation and downstream profile mechanics; general
host scheduling; implementation of #150/#151; project-root/layout migration; release execution;
new provider commands; weakening #82/#88/#91–#94 proof or terminal rules. Publication, merge, tracker
closure and remote cleanup are not authorized by this decision task.

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
