# Delivery reconciliation and authorization continuity — issue 151

Decision for [#151](https://github.com/fagenorn/nix-config/issues/151), 2026-09-21.
Status: design under delegated architecture authority; implementation, planning,
publication and activation remain later phases. The recorded Nodo, Arcwave and
Argus cases below are deterministic simulations of audited behavior, not claims
about live external state, exact historical grants or provider identities.

## Problem

The workflow carries ownership and a handoff path, but it does not durably carry
the concrete deliverable or the user's authorization intent. Its terminal result
also compresses implementation delivery, pull-request merge, tracker closure and
cleanup into one verdict. When a forge observation finds a merge, the lifecycle
truthfully records `issue_closed: false` but terminal replay leaves no owner for
the authorized closure and cleanup remainder. Conversely, a closed tracker can
hide an undelivered repository record.

This produces two bad outcomes: already delivered work may be rebuilt, and later
bookkeeping may require a fresh session or repeated permission ceremony. Adding
durable intent carelessly would create the opposite defect by treating a prior
grant, repository URL, admin role or old host allow as current executable
authority. The design must preserve historical claims and operative refusals,
observe each effect independently, and give only the exact authorized remainder
finite fenced custody.

## Solution

Extend the one workflow-state ledger with an immutable delivery contract,
append-only authorization and authority observations, four independent delivery
postconditions, and a separate bounded `delivery_remainder` custody lineage.
Implementation attempts and their retry budget remain unchanged. A remainder
has its own ordinal and launch identity, can execute only predeclared pending
stages, and cannot enter implementation phases.

Move the strict state migration and every direct, control, handoff and shipping
wire together. Current helpers validate all input before mutation. The lifecycle
persists observations before returning a next-stage action. Artifact validation
precedes decoding at report boundaries. Existing launch fencing, expiry, stalls,
capacity ordering, merge-before-expiry and retained detail remain authoritative.

This design targets integrated state schema 2 and control/direct interface 1.
The next versions are state schema 3 and control/direct interface 2. Unpublished
#152 C contributes no assumed fields; if another schema lands first, the owner
must reconcile and renumber rather than maintain parallel maps.

## Decisions

### One immutable delivery contract

Each new or reconciled issue may own one canonical `delivery-contract/v1`.
Workflow-state stores the object and its SHA-256 digest under the issue record.
Every lifecycle handoff carries the identical object/digest, the complete
append-only authorization-intent chain and its digest, and the operative
authority-observation ids. Progress and handoff ingestion compare canonical
bytes with ledger truth before persisting the handoff path. The ledger is
authoritative. Handoff documents may add prose/detail references but cannot
override or omit intent/refusal state.

The contract has this closed semantic shape:

| Member | Required content |
|---|---|
| identity | schema/kind, project id, provider repository identity, normalized repository slug, issue, deliverable id and bounded summary |
| obligations | exactly four applicability values for `implementation_delivered`, `pr_merged`, `tracker_closed`, `cleanup_complete` |
| stages | ordered closed stage ids and each stage's action, effect, output slot and worktree requirement |
| initial intent | one immutable `authorization-intent/v1` id/digest and its exact scope tuples |
| provenance | bounded legitimate source kind/reference and creation time; no raw message, policy snapshot or credential |

Applicability is `required | not_applicable` and is immutable. Missing evidence
never creates `not_applicable`. The first pass stage vocabulary is exactly
`select_reviewed_output`, `deliver_repository_record`, `publish_branch`,
`open_pr`, `merge_pr`, `close_tracker`, `delete_remote_branch`,
`remove_worktree`, and `delete_local_branch`. A contract includes only the
stages needed by its deliverable. Later output selection binds a declared slot
to a reviewed commit, tree or record digest; it narrows the contract and cannot
add a stage, target, audience or effect.

The contract contains no executable grant. New actual authorization is appended
as another immutable intent linked to its predecessor; neither the contract nor
an earlier intent is rewritten. A legacy issue with no contract cannot infer one
from tracker labels/body, a branch prefix, repository administration, a raw
transcript or an observed merge. Direct/control instead return a bounded
`delivery_contract` requirement. A legitimate current owner supplies the strict
object from an explicit user grant, standing repository authorization or an
already persisted parent handoff; the source reference is evidence of intent,
not proof that a mutation is presently allowed.

### Closed authorization scope and runtime authority

An `authorization-intent/v1` contains an id, source kind/reference, issued time,
nullable expiry, revocation key and sorted unique scope tuples. Every tuple has
exactly:

- principal kind and stable principal identity;
- action and external effect class;
- project/provider/repository identity, issue, branch/base and either a literal
  PR identity or a declared selected-output slot;
- nullable endpoint identity;
- nullable data identity digest, classification and audience (`private`,
  `public`, or a named-audience digest);
- risk class and nullable spend unit/ceiling.

Canonical comparison uses all members. A tuple may satisfy a request only when
principal, action, effect, resolved target, endpoint, data identity, audience,
risk and spend are equal or the request is a strict narrowing explicitly allowed
by that field's closed grammar. There is no generic string subset rule. Expired
intent or an observed revocation is unusable. A selected PR/output binding must
resolve before its effect; moving branch state is not a binding.

This makes the recorded private/public case explicit: the same repository URL
with a public audience or different payload/data digest does not match a private
publication intent. Repository administration is not a grant. The pending live
#152 denial is evidence about one concrete action, not universal policy and not
permission to retry it.

`authority-observation/v1` is append-only and binds contract digest, scope-tuple
id, nullable current launch, authority kind (`intent_revocation`, `native_guard`,
`host`, `provider`), verdict (`allowed`, `rejected`, `unknown`, `revoked`), reason
code, observation time, evidence digest and optional opaque host reference.
Launch may be null only for an intent-revocation observation with verdict
`revoked`; every runtime verdict requires the exact launch. Its observation id
is the SHA-256 of the canonical non-secret members, so a host need not provide a
stable receipt. An opaque host reference is retained only when actually returned.

Durable intent authorizes requesting the normal native/host evaluation; it does
not require a pre-existing `allowed` observation that a tool cannot issue until
invocation. The effect boundary still evaluates the current launch, intent,
guard, host and provider. Any returned rejection/unknown is persisted before the
caller stops. An `allowed` event, when available, describes only that launch and
effect and is never a future grant. A host rejection remains operative across
handoffs until actual new authorization or permitted material evidence allows a
fresh evaluation. New spelling, context, owner or host is not such evidence.

If a human independently completes an effect, a later exact postcondition
observation may satisfy the deliverable while the old denial remains historical.
That fact grants the agent no mutation authority and does not mark the denial
allowed.

### Four independent postconditions

The issue's `delivery` value always has the four named postconditions. Each is
`pending | observed | not_applicable`; only the contract may initialize
`not_applicable`. `observed` carries one strict `delivery-observation/v1`, whose
common fields bind observation id, contract digest, project/repository, source,
time and evidence digest. The kind-specific evidence is:

| Postcondition | Exact positive evidence |
|---|---|
| implementation delivered | selected reviewed commit/tree/record digest; integration subject; typed reachability or record-presence result; retained acceptance map plus review/test evidence references |
| PR merged | provider repository id; PR number/URL; expected head; base; merge SHA; provider-observed merged state |
| tracker closed | tracker repository/issue; observed closed state; close reason when available; tracker observation identity |
| cleanup complete | declared remote branch, local branch and worktree probes; all required objects absent; required durable detail/evidence pointer successfully re-read |

A provider merge does not establish the implementation acceptance map. Tracker
closure does not establish merge, delivery, cancellation, authorization or
cleanup. Cleanup needs successful absence probes; lookup failure is `unknown`, a
present object remains pending, and an identity/path mismatch is a refusal.
Observation objects are deduplicated by canonical id; conflicting evidence for
one identity fails before mutation and is not resolved by last-write wins.

Verbose proof remains behind an existing durable detail pointer. Cleanup cannot
remove the only retained evidence. All owner results, synthetic dispositions,
superseding facts, authority denials and observation events remain readable even
after later completion.

### Separate finite remainder custody

State schema 3 adds `delivery_remainders` beside existing implementation
`attempts`. The two arrays have independent ordinals and retry counts. Existing
attempt ordinals, the two-attempt implementation cap and historical results do
not change. A remainder record has exactly contract digest, remainder ordinal,
source implementation attempt, nullable prior remainder, pending stage ids,
owner/worktree, state, launches, fixed deadline, progress token, suspension
fields, result and result source.

Implementation launch ids retain `issue:attempt:launch`. Remainder launches use
the disjoint `issue:r<remainder>:launch` form. The read-only current-launch query
accepts this closed union and otherwise keeps its no-clock, no-lock, no-create,
no-write behavior. Every protected effect uses the received id verbatim. Every
remainder mutation of tracker, provider, branch or worktree is protected: the
caller invokes current-launch immediately before the effect, and false, missing
or malformed output permits no effect, ledger write or cleanup. This retains the
implementation path's existing pre-merge guard while fencing the new
successor-owned post-merge path.

There is at most one nonterminal custody record across implementation and
remainder lineages. Creating remainder 1 requires a validated contract, at least
one pending predeclared stage and no active implementation owner. Its creation
key is the canonical digest of contract, source attempt, sorted pending stages
and current postcondition/authorization heads. Repeating the same direct/control
request returns the existing record or completed replay without a write.

Owner unavailability, ordinary handoff, expiry and environmental suspension
resume the same remainder ordinal with a new launch. They never spend either
retry budget. Preserve the fixed wall-clock deadline: handoff/dead-owner resume
inside the window retains it; expiry suspends/parks before in-place resume gets a
fresh full window. The same no-progress arithmetic permits three resumes and
stops automatic dispatch on the next suspension. Meaningful persisted stage or
postcondition progress resets the streak.

The remainder lineage is independently capped at two ordinals, matching the
current implementation-attempt ceiling without consuming it. Remainder 2 is
allowed only after an authentic failed/stalled remainder, exact inspection says
the required effect is still absent, the action is declared retryable, and a
new recovery basis is present: changed relevant evidence, new actual
authorization, or explicit human-directed retry of an unchanged authorized
transient failure. A guard, host or provider rejection/unknown is not a
transient-failure basis and requires the authority/material-evidence rules above.
No third remainder is minted. A successor may still record
independent human/provider completion evidence without new custody.

Merge observation remains ahead of expiry/reaping. Persist observations first,
derive pending stages second, and only then select or resume custody under
capacity and deadline rules. An old terminal owner result is never overwritten;
an active result-less implementation attempt may receive the existing truthful
forge-reconciled closeout, while delivery truth stays in the independent record.
Terminal replay checks an eligible remainder before returning the historical
terminal envelope.

### Worktree and subject requirements

Normal implementation worktree rules do not change. Each remainder stage
predeclares exactly one requirement:

- `matching_required`: the recorded worktree exists on the exact issue branch
  and its current head/PR binding matches the selected subject;
- `cleanup_target`: the exact recorded worktree may still match or may be
  successfully observed absent; mismatch is always refusal;
- `not_required`: the stage has no worktree effect, such as tracker closure, but
  still binds repository/issue and current custody.

Absence is expected positive evidence only for `cleanup_target`, and only after
a successful no-follow lookup of the exact recorded identity. It never permits
relocation or candidate discovery. A record-delivery stage requires
`matching_required`, its exact predeclared record/output digest, and a fresh live
PR/head observation. A closed tracker neither cancels that stage nor supplies a
grant. An unbound record, absent/mismatched worktree, stale PR/head or broader
payload stops with the precise requirement.

Cleanup becomes observed only when every contract-required remote/local branch
and worktree absence is established and retained detail remains readable.
Failed probes and branch-prefix absence are not proof.

### Versioned state and transports

State schema 3 adds the immutable contract/digest, append-only intent and
authority lists, the four postconditions, and the separate remainder array to
each issue. Migration 2→3 preserves `attempts`, `outcome`, result bytes and detail
pointers unchanged. It initializes no contract, authorization, successful
postcondition or cleanup claim. A legacy result remains a historical claim; even
`issue_closed: true` is not promoted to a fresh tracker observation. Strict new
input and current observations are required before remainder custody.

Migration is adjacent, atomic and idempotent. Unknown fields, partial v3 shapes,
ambiguous repository identity, malformed legacy rows or invalid input refuse
before replacement. Older installed helpers reject v3 without mutation. Later
#152 C must migrate from the then integrated schema and merge its concerns rather
than creating parallel state.

The already-started issue-151 run is a deliberate bridge exception, not the
first v3 run. It remains owned and finished by its retained installed schema-2,
interface-1 generation and the current ship-summary shape. New source writers
must never open or migrate that live ledger, including during tests. Its feature
worktree may be removed after merge without stranding finish on source files.
Complete isolated source replays prove v3/interface 2. Source integration is not
installed activation; using v3 for real runs waits for a separately authorized
managed activation/cutover that makes one immutable helper generation available
to all producers and consumers for each upgraded run. No improvised installed
patch or worktree-path helper is a bridge.

The own-delivery bridge is a closed `bridge-generation/v1` manifest, not one
wrapper path. It binds resolved identity and SHA-256 for workflow-state, the
artifact-budget executable, its dynamically loaded module, and the shared
artifact-budget policy, plus state/interface/report versions. The read-only
entry observation for this run found digests `530077048a7b84536296da57de8e9e76bb38792a861180217d0168500b0d3403`,
`6dbba033797479bd8dad9f29cc502fafd966419452f30aaffd18e857a46bf8aa`,
`6855d08202a6d9ed97783f72c67a293e0fe6952b397a1fa788e5e37bce67b327`
and `eaae117b9e32f6ba4377c40c8a4db92a39061ae73fd6de452c664d8a0b9a2fe0`
respectively. These are observed bridge evidence, not source defaults or a raw
policy snapshot. Finish re-resolves and compares the whole set before validating
the legacy report. Drift fails closed without modifying the ledger, installing a
patch or asking a routine new permission question.

Control and direct-owner interface 2 accept the same versioned sorted collections
of delivery-contract inputs, authorization intents, delivery observations and
authority observations. Direct carries one issue; control carries issue-keyed
collections. Control additionally accepts forge evidence, closing the current
direct-only gap. Both validate the whole request before locking/mutation and
derive policy through the same function.

Their closed action union adds `delivery_remainder`. Its envelope carries
purpose, issue, remainder/source ordinals, owner, worktree, contract object and
digest, pending ordered stages, deadline and remainder action id. `requirement`
responses name exact missing contract, scope tuple, observation or worktree
fact. Callers never infer a stage from tracker/forge state.

`ship-handoff/v2` carries the exact contract/digest, authorization-intent chain
and digest, operative authority-observation ids, remainder identity, pending
stages, selected subject bindings, lifecycle root/run/action id and retained
detail pointer. `ship-summary/v2` separates the historical owner verdict from
new delivery and authority observations. Artifact-budget validates canonical
stdout before from-issue or workflow-state decodes it. Workflow-state's finish
entry accepts the exact remainder action id, persists valid observations/result
before output, advances only declared stages and emits the next requirement,
remainder dispatch or completed delivery summary.

From-issue, AUTO, ship-issue and orchestration move with these interfaces and
consume only the typed action. Wayfind/prototype cases enter this path through a
validated delivery contract; they do not become lifecycle writers. Report
validators keep the legacy row readable for old result files, while v3 writers
emit only v2 handoff/summary shapes. No validator-first or prose-only cutover is
allowed.

### Deterministic simulated acceptance cases

Fixtures use reserved `sim.invalid` identities, fixed synthetic 40-hex object
ids and canonical fake-provider state. They contain no external repository
payload, raw transcript or asserted historical grant.

- **Nodo 1314 behavior:** a simulated six-criterion acceptance map and five-test
  evidence set bind the selected subject. Fake repository and forge observations
  establish implementation delivery and merge; tracker and cleanup remain
  pending. Direct-owner returns `delivery_remainder(close_tracker, cleanup)`,
  never implementation. Fake closure and absence observations persist all four
  postconditions and complete the delivery.
- **Arcwave 113/record PR 116 behavior:** tracker closure is already observed,
  while the exact simulated decision-record digest and live PR/head remain
  pending. With matching intent/worktree/PR evidence, the same run dispatches
  `deliver_repository_record`; without any one of them it returns the exact
  requirement. It never reopens the substantive decision or treats closure as
  cancellation/grant.
- **Argus iteration behavior:** an identical principal, endpoint, data identity,
  private audience, risk and spend tuple reuses the recorded intent. A different
  endpoint, transfer identity or public audience returns the missing tuple before
  effect. A simulated host rejection persists and cannot be retried through new
  spelling/context/host. A later fake human-completion observation may satisfy
  the effect while leaving that rejection historical and granting no agent right.

## Test seams

Acceptance uses a small set of public executable seams plus caller contract
tests. Plan-only or prose-only evidence is insufficient.

1. **Workflow-state CLI round trip.** Temporary real ledgers invoke init,
   direct-owner/control, current-launch and finish through subprocesses. Feed
   strict fake-adapter observations for the three simulations. Assert the typed
   next stage, no implementation dispatch/attempt consumption, persisted
   historical result and observations, deduplicated replay, two-ordinal cap,
   exact three-resume stall behavior, merge-before-expiry, capacity ordering and
   no filesystem mutation from current-launch.
2. **Artifact/report CLI boundary.** Validate canonical v2 handoff/summary bytes
   and rejection of legacy/new hybrids, changed contract digest, stale action,
   missing postcondition evidence, audience/data mismatch, fabricated host ref,
   unsuccessful absence probes and unknown fields. Then pass the validated
   summary into workflow-state and assert the stored result, not helper calls.
3. **Controlled provider-effect replay.** A fake provider records effects and
   returns typed observations. Drive from the public direct response through the
   shipping summary into the ledger. Prove one exact authorized effect occurs,
   rejected/missing scope causes zero effects, independently completed effects
   need no agent mutation, and Nodo/Arcwave terminate with the four truthful
   postconditions.
4. **Production caller contracts and orchestration eval.** Pin that from-issue,
   AUTO, ship-issue and orchestration validate before decode, copy the contract
   exactly, execute only the closed `delivery_remainder` stages, persist before
   reporting, preserve denial and never synthesize implementation/new authority.
   These tests supplement, not replace, the executable round trips above.

All v3 runtime replays use isolated temporary ledgers and the complete reviewed
source toolchain. A regression proves the live issue-151 schema-2 ledger bytes
remain unchanged, its installed bridge can finish with the legacy summary after
the feature worktree is absent, whole-manifest drift refuses before mutation,
and old helpers reject an isolated v3 ledger.

Run the ordinary workflow suite and managed build for integration. The design
baseline already passed at the original integrated commit; implementation and
final verification must run again after source changes.

## Out of scope

Implementing or activating the transaction/release core, #117/#123/#125 schemas,
#152 shared verification blockers, host capacity scheduling, permission-guard or
provider enforcement changes, new provider commands, live external-project
mutation, publication, host activation, raw transcript/payload fixtures, or
policy snapshots. The separate clean-review plus failed-verification report row
is not required by these six criteria and remains a separate design disposition.

This design does not resolve the pending #152 publication denial, assert a real
Nodo/Arcwave/Argus SHA or grant, infer authority from repository ownership, or
add a universal approval ceremony. It records and carries existing intent while
leaving actual native/host/provider enforcement authoritative.
It does not activate schema 3 or migrate the live issue-151 ledger; source
integration and installed activation are reported as separate facts.

## Decision ledger

All choices are agent judgments under the user's delegated reversible
architecture authority. They are not recorded human answers.

| ID | Choice | Grounding | Rejected alternative |
|---|---|---|---|
| D1 | Store one immutable delivery contract in the sole lifecycle ledger and carry exact canonical bytes through every handoff. | Issue 151 criterion 1; the-bar DRY; current durable handoff seam. | Handoff-only prose or raw conversation replay creates competing truth and cannot be validated. |
| D2 | Keep authorization intent append-only and secret-free; evaluate exact canonical scope plus current guard/host/provider authority at each effect. | #116 D1; retained #117 intent semantics; private/public denial case. | URL/action string subsets or durable `authorized`: omit payload/audience/risk and turn intent into a grant. |
| D3 | Record host/guard/provider outcomes as launch-bound observations with derived non-secret ids and optional real host references. | Host may expose no stable id; issue 151 criterion 6. | Invent a receipt, require pre-call allow, or reuse an old allow as future authority. |
| D4 | Track delivered, merged, closed and cleanup as four independent typed postconditions with positive evidence and fail-closed probes. | Issue 151 criterion 2; truthful-terminal standard; retained #117 D7. | Merge/closure booleans as total completion manufacture implementation or cleanup truth. |
| D5 | Add a separate capped remainder lineage with disjoint ordinals/action ids; in-place resumes do not spend implementation or remainder retry counts. | Nodo/Arcwave cases; #132/#133; root critical custody constraint. | Reopen implementation or append unbounded generic retries. |
| D6 | Permit one retry remainder only after authentic failure plus absent effect and a valid recovery basis; otherwise park while accepting independent completion evidence. | Current two-attempt cap; no-blind-retry and stall rules. | Unlimited successor churn or treating environment suspension as a failed attempt. |
| D7 | Make worktree absence positive only for a predeclared cleanup target; require exact matching worktree/subject/PR for record delivery. | Current phase-zero/misbinding rules; cleanup semantics. | Branch-prefix discovery or absence-as-general-success weakens fencing. |
| D8 | Preserve old result bytes/detail and migrate schema 2→3 without inventing contracts, grants or successful observations. | One ledger; immutable history; current schema baseline. | Rewrite a terminal result or promote legacy booleans into fresh evidence. |
| D9 | Cut over state, direct/control, artifact reports, from-issue, shipping and orchestration as one versioned interface delivery. | Defense in depth; all production producers/consumers must agree. | Validator-first or prose-only rollout strands callers and admits mixed shapes. |
| D10 | Accept the three audited behaviors only through deterministic simulated identities, intent and provider state. | Audit cases 2–4 lack safe exact live metadata and authorize no external mutation. | Copy transcripts/private payloads or present invented SHAs/grants as history. |
| D11 | Prove acceptance through public CLI/provider-effect round trips, with text/eval contracts only as supplementary caller coverage. | The-bar tests that can fail; issue 151 runtime gap. | Plan-only tests can pass while no caller persists or executes the typed remainder. |
| D12 | Finish issue 151 through a whole-generation pinned installed v2/v1 bridge; prove v3 in isolated source replays and activate only through separate managed scope. | #66 bridge/activation separation; dynamic validator/module loading; worktree cleanup removes source. | Pinning one wrapper, migrating the live run or depending on its deleted worktree can strand or silently mix the delivery introducing the protocol. |
