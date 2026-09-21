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

The contract has this closed semantic shape; the wire appendix below is
normative when names or optionality matter:

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
to a reviewed commit, tree or record digest. The slot is already the authorized
target: binding its exact value narrows the contract and does not demand a new
grant merely because the reviewed SHA is now known. It cannot add a stage,
target, audience or effect.

The contract contains no executable grant. New actual authorization is appended
as another immutable intent linked to its predecessor; neither the contract nor
an earlier intent is rewritten. A legacy issue with no contract cannot infer one
from tracker labels/body, a branch prefix, repository administration, a raw
transcript or an observed merge. Direct/control instead return a bounded
`delivery_contract` requirement. A legitimate current owner supplies the strict
object from an explicit user grant, standing repository authorization or an
already persisted parent handoff. The common validator authenticates that source
and predecessor before accepting the object; an arbitrary caller assertion is
not a source. The source reference is evidence of intent, not proof that a
mutation is presently allowed.

### Closed authorization scope and runtime authority

An `authorization-intent/v1` contains an id, source, issued time, nullable
expiry, revocation key and sorted unique scope tuples. Every tuple has
exactly:

- principal kind and stable principal identity;
- action and external effect class;
- project/provider/repository identity, issue, branch/base and either a literal
  PR identity or a declared selected-output slot;
- discriminated endpoint identity (`none | literal`);
- discriminated data identity (`none | literal`), with digest, classification
  and audience (`private`, `public`, or a named-audience digest);
- risk class and discriminated spend (`none | ceiling`) with unit/ceiling.

Canonical comparison uses all members and the closed narrowing grammar below.
There is no generic string subset rule. Expired intent or an observed revocation
is unusable. A selected PR/output binding must resolve before its effect; moving
branch state is not a binding.

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
guard, host and provider. The hard launch fence precedes every owner-authored
effect and ledger write. False, missing or malformed current-launch output
returns a refusal to that caller with zero external effect and byte-identical
ledger state.

After a successful guard, the current owner may request the native/host/provider
evaluation. Before persisting its returned `allowed`, `rejected` or `unknown`
observation, it checks the same launch again. If ownership changed meanwhile,
that owner writes nothing; the current successor or an authorized external
observation collector may later ingest the exact non-secret result through the
normal validated input. That collector is the direct/control lifecycle writer
under its ledger lock; it validates the original launch/result binding and
current state and never acts through the stale owner process. If the second
check succeeds, the observation is persisted before the caller stops or
advances. The same rule covers a provider effect that completed while its caller
lost custody: the stale caller cannot
write, while authenticated provider evidence remains ingestible. An `allowed`
event describes only that launch and effect and is never a future grant. A host
rejection remains operative across handoffs until actual new authorization or
permitted material evidence allows a fresh evaluation. New spelling, context,
owner or host is not such evidence.

If a human independently completes an effect, a later exact postcondition
observation may satisfy the deliverable while the old denial remains historical.
That fact grants the agent no mutation authority and does not mark the denial
allowed.

### Canonical wire and narrowing appendix

All new v1 objects are strict JSON objects: required keys are always present,
unknown or duplicate keys are invalid, and JSON `null` is accepted only where a
field below says nullable. Null means no value; it is never a wildcard. Canonical
bytes are UTF-8 JSON with lexicographically sorted object keys, compact
separators, shortest decimal integers and one trailing newline. Arrays keep
semantic order only for `stages`; every other array named below is sorted by
scalar value or member id and contains unique values. A digest is lowercase
`sha256:<64-hex>` over the object's canonical bytes with that object's own
derived `id` or `digest` member omitted. Producers and consumers use the same
serializer and reject a supplied derived value that differs.

The exact `delivery-contract/v1` members are:

| Key | Type and closed content |
|---|---|
| `schema_version`, `kind` | integer `1`; literal `delivery-contract` |
| `project` | object with exactly string `project_id`, `provider`, `repository_id`, and normalized `repository_slug` |
| `issue` | positive integer |
| `deliverable` | object with exactly string `id`, string `summary` bounded by the shared phase-report notes maximum, and `obligations`, an object containing exactly the four postcondition keys with `required \| not_applicable` values |
| `stages` | nonempty ordered array of strict stage objects with exactly string `id`, closed `kind`, `action`, `effect`, strict `target_ref`, closed `worktree_requirement`, sorted unique string `depends_on` ids and boolean `retryable` |
| `initial_authorization_intent_id`, `initial_authorization_intent_digest` | id and canonical digest of the first accepted intent; that exact intent is transported beside the contract |
| `provenance` | object with exactly source `kind`, stable string `reference`, evidence `digest` and RFC 3339 UTC `created_at`; raw messages and credentials are invalid |

A `target_ref` is one of `{"kind":"none"}`,
`{"kind":"literal","value":"..."}`, or
`{"kind":"slot","slot_id":"...","subject_kind":"...","constraints":{...}}`,
where `subject_kind` is exactly one of
`commit | tree | record | pull_request`. Slot constraints contain exactly
`project_id`, `provider`, `repository_id`, `repository_slug`, `branch`, `base`,
`deliverable_class`, and `data_ref`; the last uses a closed `none | literal`
discriminator whose literal contains digest, classification and audience.
Values not relevant to the subject use their
explicit `none` discriminator rather than null. A stage may refer only to a slot
declared in the same contract. Stage `kind` is one of the nine stage names above;
`worktree_requirement` is
`matching_required | cleanup_target | not_required`. The closed stage table owns
the corresponding action/effect literals; a stage cannot supply an alternate
action/effect for its kind.

The exact `authorization-intent/v1` members are `schema_version` 1, literal
`kind` `authorization-intent`, derived `id`, nullable
`predecessor_intent_id`, strict `source`, RFC 3339
UTC `issued_at`, nullable `expires_at`, string `revocation_key`, and nonempty
sorted unique `scopes`. `source` contains exactly `kind`
`explicit_user | standing_repository | parent_handoff`, stable `reference` and
`evidence_digest`. A successor must name the accepted predecessor and carry newly
validated source evidence. Appending it never deletes or changes an authority
observation. In particular, it can make a rejected tuple eligible for a fresh
evaluation only when the new source postdates the rejection and explicitly
covers that exact tuple, or when an accepted `reevaluation-evidence/v1` permits
reevaluation. Merely asserting a successor id cannot clear a refusal.

Each `scope-tuple/v1` has exactly `schema_version` 1, literal `kind`
`scope-tuple`, derived `id`; strict `principal` with exactly `kind` and
`stable_id`; strings `action` and `effect`; strict `target` containing exactly
`project_id`, `provider`, `repository_id`, `repository_slug`, `issue`, `branch`,
`base`, `pr_ref`, and `output_ref`; discriminated `endpoint` (`none | literal`);
discriminated `data`
(`none | literal`, with digest, classification and audience); string `risk`;
and discriminated `spend` (`none | ceiling`, with unit and nonnegative integer
ceiling). A literal ref is equality-only. A slot ref narrows exactly once through
a `selected-output/v1` containing exactly `schema_version` 1, literal `kind`
`selected-output`, derived `id`, `contract_digest`, `slot_id`, `subject_kind`,
`subject_value`, `repository_id`, `branch`, `base`, `evidence_digest`, and sorted
unique `review_evidence_ids`. The selected subject must satisfy every declared
slot constraint; the binding is immutable and a second value conflicts before
mutation.

Scope matching permits only these narrowings:

| Declared member | Permitted request |
|---|---|
| principal, action, effect, repository/project/issue, endpoint, data digest/classification/audience, risk | exact equality |
| literal PR/output/branch/base | exact equality |
| slot PR/output | the one immutable selected value for the same slot satisfying every declared constraint |
| spend `none` | exact `none` |
| spend ceiling | same unit and requested integer less than or equal to the ceiling |
| intent time/revocation | request time within the closed validity interval and no matching revocation observation |

`reevaluation-evidence/v1` has exactly `schema_version` 1, literal `kind`
`reevaluation-evidence`, derived `id`, `contract_digest`, `scope_id`,
`rejected_observation_id`, `source_kind` (`host | provider`), `reason_code`, UTC
`observed_at` and `evidence_digest`. It is
accepted only through the same trusted adapter that owns that source. It permits
one fresh evaluation of the same tuple; it neither authorizes the effect nor
predicts the result, and neither deletes nor changes the old rejection.

`authority-observation/v1` has exactly `schema_version` 1, literal `kind`
`authority-observation`, derived `id`,
`contract_digest`, `scope_id`, nullable `launch_id`, closed `authority_kind` and
`verdict`, `reason_code`, UTC `observed_at`, `evidence_digest` and nullable
`opaque_host_reference`, with the null restriction stated above.
`delivery-observation/v1` has exactly `schema_version` 1, literal `kind`
`delivery-observation`, derived `id`,
`contract_digest`, strict `project`, closed `observation_kind`, strict
kind-specific `subject`, `source`, UTC `observed_at` and `evidence_digest`. Each
kind's `subject` has the positive fields in the next
section and rejects all other shapes. `source` has exactly kind
`provider | tracker | repository | filesystem | human_completion` and a stable
reference; `human_completion` is evidence of an observed effect, never a grant.

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

The ledger also stores one `delivery-stage-fact/v1` for every contract stage.
It has exactly `schema_version` 1, literal `kind` `delivery-stage-fact`, derived
`id`, `contract_digest`, `stage_id`, `state`
`pending | observed | not_applicable`, and nullable `observation_id`. Only a
contract stage whose obligation is inapplicable may initialize
`not_applicable`; pending has a null observation and observed has exactly one
accepted `delivery-observation/v1`. A conflicting observation for an already
observed stage refuses before mutation. The closed advancement map is:

| Stage | Exact action / effect | Required observation kind |
|---|---|---|
| `select_reviewed_output` | `select_output` / `ledger_write` | `selected_output`, including the immutable slot binding and its review evidence |
| `deliver_repository_record` | `write_record` / `repository_write` | `repository_record_present`, binding selected record digest and reachable integration subject |
| `publish_branch` | `push_branch` / `repository_write` | `branch_published`, binding repository, branch and exact selected head |
| `open_pr` | `open_pull_request` / `provider_write` | `pr_opened`, binding provider PR, head, base and selected output |
| `merge_pr` | `merge_pull_request` / `provider_write` | `pr_merged`, binding provider PR/head/base/merge SHA |
| `close_tracker` | `close_issue` / `tracker_write` | `tracker_closed`, binding repository/issue and observed closed state |
| `delete_remote_branch` | `delete_remote_branch` / `repository_write` | `remote_branch_absent`, from a successful exact-identity probe |
| `remove_worktree` | `remove_worktree` / `filesystem_write` | `worktree_absent`, from a successful no-follow exact-path/identity probe |
| `delete_local_branch` | `delete_local_branch` / `repository_write` | `local_branch_absent`, from a successful exact-identity probe |

Observation subjects are exact: `selected_output` contains the strict
`selected-output/v1`; record presence contains repository id, record digest,
integration subject, reachability result and sorted acceptance/review evidence
ids; branch publication contains repository id, branch and selected head; PR
open/merge contains provider repository id, PR number/URL, expected head and
base, with merge SHA and merged state required only for merge; tracker closure
contains tracker repository/issue, closed state, nullable close reason and
tracker observation identity; remote/local absence contains repository id,
exact branch and successful absence result; worktree absence contains canonical
path, recorded worktree identity, no-follow probe mode and successful absence
result. `implementation_delivered` uses the record/commit selected subject,
integration subject, reachability result and sorted acceptance/review/test
evidence ids. No failure, unknown or mismatched probe has a positive subject
shape.

The contract's `depends_on` graph is acyclic and may refer only to earlier stage
ids. Selection precedes every stage that uses the slot; publish precedes open;
open and the required implementation-delivered acceptance observation precede
merge; the contract declares whether closure depends on merge; cleanup depends
on the last applicable delivery effect and durable-detail reachability. The
ordered pending stages are a pure projection: scan contract order, omit observed
or not-applicable facts, and return a stage only after every dependency is
observed or not applicable. If the first pending fact has unmet dependencies,
the response is a typed requirement naming those observations rather than a
different action. Postconditions are likewise pure projections from accepted
observations and stage facts; provider/tracker state never advances an unrelated
stage.

Independent human completion advances the same fact only through its exact
typed observation. It neither creates authority nor bypasses dependencies. A
changed observation head while a nonterminal remainder exists is folded into
that record, and its pending-stage projection is recomputed; it never mints a
second active custody record. If no stages remain, that same remainder finishes.

For a legacy failed or merged implementation claim, migration first preserves
the claim and result bytes unchanged. Remainder 1 becomes eligible only after a
validated new contract, a fresh selected-output binding with review/acceptance
evidence, and fresh exact external observations have been ingested. Its source
points at the historical implementation attempt, but no legacy boolean is
promoted into a stage fact or postcondition.

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

Immediately before a destructive cleanup effect, the caller rechecks the current
launch, contract/selected-subject binding, durable-detail reachability and the
exact target's current identity. An already absent exact target records the
positive absence observation without issuing a delete. A recreated target,
different object at the path/name, stale positive observation or lookup failure
refuses. After an accepted delete, a fresh exact absence probe is required before
the stage advances; the effect result alone is not proof.

### Versioned state and transports

State schema 3 adds the immutable contract/digest, append-only intent and
authority lists, the four postconditions, and the separate remainder array to
each issue. Migration 2→3 preserves `attempts`, `outcome`, result bytes and detail
pointers unchanged. It initializes no contract, authorization, successful
postcondition or cleanup claim. A legacy result remains a historical claim; even
`issue_closed: true` is not promoted to a fresh tracker observation. Strict new
input and current observations are required before remainder custody.

The v3 issue object has exactly existing `issue`, `attempts`, and `outcome` plus
`delivery` and `delivery_remainders`. `delivery` has exactly `contract`,
`contract_digest`, sorted `authorization_intents`,
`authorization_chain_digest`, sorted `authority_observations`, sorted
`reevaluation_evidence`, sorted `delivery_observations`, sorted
`selected_outputs`, ordered `stage_facts`, and `postconditions` with exactly the
four named keys; each value has exactly `state`
`pending | observed | not_applicable` and nullable `observation_id`, with the
same state/id relationship as stage facts. A remainder record has exactly
`remainder`, `contract_digest`,
`source_attempt`, nullable `prior_remainder`, ordered `pending_stage_ids`,
`owner`, `worktree`, `state`, `launches`, `deadline_at`, `progress_token`,
`blocked_on`, `suspend_phase`, `stalled_resumes`, `result`, and `result_source`.

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

The own-delivery bridge is a run-specific root-controller operational protocol,
not new product runtime. Its retained `bridge-generation/v1` evidence names the
public entry topology and records resolved identity/digest/version for the
workflow-state module, artifact-budget wrapper and dynamically loaded module, shared budget
policy, selected interpreter/runtime closure, and environment inputs that affect
HOME/PATH/shebang and policy resolution. The exact identities for this run live
only in retained controller evidence; production defaults and this design do not
hardcode machine hashes. Before finishing the old run, the controller re-resolves
the declared topology and compares the complete evidence set, then uses only the
retained compatible v2/v1 path. Drift fails closed without modifying the ledger,
installing a patch or asking a routine new permission question.

No shipped verifier owns or opens the live issue-151 ledger. Portable product
tests copy reviewed old-generation workflow/artifact modules and policy into an
isolated source-layout fixture, choose a controlled interpreter/environment,
and use a temporary ledger plus simulated removed
worktree. The actual public-link/hash/runtime inventory, its pre-finish recheck
and proof that the real ledger stayed unchanged are controller evidence outside
the product suite. The source delivery adds no bridge runtime and imposes no
activation requirement.

Control interface 2 has exactly the existing interface-1 request keys plus
issue-keyed sorted `forge`, `delivery_contracts`, `authorization_intents`,
`authority_observations`, `reevaluation_evidence`, and
`delivery_observations`. Direct-owner interface 2 has exactly its interface-1
keys plus nullable `delivery_contract` and sorted `authorization_intents`,
`authority_observations`, `reevaluation_evidence`, and
`delivery_observations` for its one issue. Thus both accept the same versioned
input objects; control closes the current direct-only forge gap. Both validate
the whole request before locking/mutation and derive policy through the same
function.

Their closed action union adds `delivery_remainder`. That response has exactly
`interface_version` 2, literal `kind` `delivery_remainder`, `ledger_repo_root`,
`run_id`, `issue`, `remainder`, `source_attempt`, `owner`, `action_id`,
`worktree`, `contract`,
`contract_digest`, ordered `pending_stage_ids`, `deadline_at`, and
`requirements`. Each requirement has exactly `kind`
`delivery_contract | scope_tuple | observation | worktree_fact`, `subject_id`,
`reason_code`, and nullable durable `detail_pointer`. Callers never infer a
stage from tracker/forge state.

`ship-handoff/v2` has exactly the current handoff keys plus `interface_version`,
`delivery_contract`, `delivery_contract_digest`, `authorization_intents`,
`authorization_chain_digest`, `authority_observation_ids`,
`reevaluation_evidence_ids`, `remainder_identity`, `pending_stage_ids`, and
`selected_outputs`; existing lifecycle root/run/action and detail keys remain
mandatory. `ship-summary/v2` has exactly `interface_version` 2, `issue`, `state`
(`delivery_complete | failed`), nullable `historical_owner_result` in the exact
legacy result shape, `delivery_contract_digest`,
`remainder_action_id`, sorted `delivery_observations`, sorted
`authority_observations`, sorted `reevaluation_evidence`, `detail_state`,
nullable `report_path`, and bounded `notes`. It separates the historical owner
verdict from new delivery and authority observations. Artifact-budget validates
canonical stdout before from-issue or workflow-state decodes it. Workflow-state's
finish entry accepts the exact remainder action id, persists valid observations/result
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
   rejected/missing scope causes zero effects, and a stale launch causes both zero
   effects and a byte-identical ledger. Prove a denial produced after custody
   changes cannot be written by the old owner but can be ingested by the current
   successor, independently completed effects need no agent mutation, and
   Nodo/Arcwave terminate with the four truthful postconditions.
4. **Production caller contracts and orchestration eval.** Pin that from-issue,
   AUTO, ship-issue and orchestration validate before decode, copy the contract
   exactly, execute only the closed `delivery_remainder` stages, persist before
   reporting, preserve denial and never synthesize implementation/new authority.
   These tests supplement, not replace, the executable round trips above.

All v3 runtime replays use isolated temporary ledgers and the complete reviewed
source toolchain. Portable old-generation fixtures prove legacy-summary finish
after a simulated feature-worktree removal, manifest drift refusal before
mutation, and old-helper rejection of an isolated v3 ledger. They never inspect
the real issue-151 ledger, HOME configuration, repository root or `/private/tmp`.
The controller separately retains the actual whole-generation recheck and
live-ledger byte-preservation evidence for this run.

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
| D2 | Keep authorization intent append-only and secret-free; match its exact canonical tuple with the closed per-field narrowing grammar, including immutable future-output slots, then evaluate current guard/host/provider authority at each effect. | #116 D1; retained #117 intent semantics; private/public denial case. | URL/action string subsets, null wildcards or durable `authorized` omit payload/audience/risk and turn intent into a grant. |
| D3 | Record host/guard/provider outcomes as launch-bound observations with derived non-secret ids and optional real host references only after a second current-launch check; a stale owner has zero effect and zero write. | Current read-only guard semantics; host may expose no stable id; issue 151 criterion 6. | Persisting a late denial from a stale owner weakens the same fence that protects effects. |
| D4 | Track exact stage facts plus delivered, merged, closed and cleanup as independent typed observations with positive evidence, dependencies and fail-closed probes. | Issue 151 criterion 2; truthful-terminal standard; retained #117 D7. | Four aggregate booleans cannot prove intermediate delivery stages or their prerequisites. |
| D5 | Add a separate capped remainder lineage with disjoint ordinals/action ids; in-place resumes do not spend implementation or remainder retry counts. | Nodo/Arcwave cases; #132/#133; root critical custody constraint. | Reopen implementation or append unbounded generic retries. |
| D6 | Permit one retry remainder only after authentic failure plus absent effect and a valid recovery basis; otherwise park while accepting independent completion evidence. | Current two-attempt cap; no-blind-retry and stall rules. | Unlimited successor churn or treating environment suspension as a failed attempt. |
| D7 | Make worktree absence positive only for a predeclared cleanup target; require exact matching worktree/subject/PR for record delivery. | Current phase-zero/misbinding rules; cleanup semantics. | Branch-prefix discovery or absence-as-general-success weakens fencing. |
| D8 | Preserve old result bytes/detail and migrate schema 2→3 without inventing contracts, grants or successful observations. | One ledger; immutable history; current schema baseline. | Rewrite a terminal result or promote legacy booleans into fresh evidence. |
| D9 | Cut over state, direct/control, artifact reports, from-issue, shipping and orchestration as one versioned interface delivery. | Defense in depth; all production producers/consumers must agree. | Validator-first or prose-only rollout strands callers and admits mixed shapes. |
| D10 | Accept the three audited behaviors only through deterministic simulated identities, intent and provider state. | Audit cases 2–4 lack safe exact live metadata and authorize no external mutation. | Copy transcripts/private payloads or present invented SHAs/grants as history. |
| D11 | Prove acceptance through public CLI/provider-effect round trips, with text/eval contracts only as supplementary caller coverage. | The-bar tests that can fail; issue 151 runtime gap. | Plan-only tests can pass while no caller persists or executes the typed remainder. |
| D12 | Finish issue 151 through its run-specific retained v2/v1 operational bridge; keep actual topology/runtime identities in controller evidence, prove portable behavior with isolated fixtures, and activate v3 only through separate managed scope. | #66 bridge/activation separation; dynamic validator/module/policy resolution; worktree cleanup removes source. | Hardcoded machine hashes, a generic bridge runtime, migrating the live run or depending on its deleted worktree would mix product behavior with one delivery's operations. |
