# Delivery reconciliation and authorization continuity — issue 151

Decision for [#151](https://github.com/fagenorn/nix-config/issues/151), 2026-09-21.
Status: design under delegated architecture authority; implementation, planning,
publication and activation remain later phases. The recorded Nodo, Arcwave and
Argus cases below are deterministic simulations of audited behavior, not claims
about live external state, exact historical grants or provider identities.

## Problem

The ledger carries custody but not a durable deliverable or authorization intent,
and one terminal verdict conflates implementation, merge, tracker closure and
cleanup. Merge/closure replay can therefore leave delivered work rebuilt or an
authorized remainder ownerless. The design must preserve all historical claims
and operative refusals, observe each effect independently, and give only the
exact pending authorized remainder finite launch-fenced custody.

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
already persisted parent handoff. The reducer structurally validates the closed
source kind/reference/digest, predecessor link, scope and canonical identity;
it does not authenticate a user statement or approval transcript. The existing
trusted controller supplies the normalized source fact under the current caller
trust boundary, while the native host remains the independent effect authority;
owner summaries cannot append intent. Thus an
arbitrary caller-created successor is not accepted and cannot clear a refusal.
The source reference is evidence of intent, not proof that a mutation is
presently allowed. Its digest supplies canonical identity/integrity only and is
never authority.

### Closed authorization scope and runtime authority

An `authorization-intent/v1` contains an id, source, issued time, nullable
expiry, revocation key and sorted unique scope tuples. Every tuple has
exactly:

- principal kind and stable principal identity;
- action and external effect class;
- project/provider/repository identity, issue, branch/base and either a literal
  PR identity or a declared selected-output slot;
- discriminated endpoint identity (`none | literal`);
- discriminated data identity (`none | literal | selected_output_slot`), with
  fixed classification and audience (`private`, `public`, or a named-audience
  digest); literal carries its exact digest, while the slot form carries the
  contract slot id whose reviewed binding supplies the digest;
- risk class and discriminated spend (`none | ceiling`) with unit/ceiling.

Canonical comparison uses all members and the closed narrowing grammar below.
There is no generic string subset rule. Expired intent or an observed revocation
is unusable. A selected PR/output binding must resolve before its effect; moving
branch state is not a binding. Resolving a slot-bound data digest from that same
reviewed output is the declared narrowing, so it needs no new permission merely
because the bytes are now known. A different slot/target, classification,
audience, action or effect still refuses.

This makes the recorded private/public case explicit: the same repository URL
with a public audience or different payload/data digest does not match a private
publication intent. Repository administration is not a grant. The pending live
#152 denial is evidence about one concrete action, not universal policy and not
permission to retry it.

`authority-observation/v1` is append-only and binds contract digest, scope-tuple
id, nullable current launch, authority kind (`intent_revocation`, `native_guard`,
`host`, `provider`), verdict (`allowed`, `rejected`, `unknown`, `revoked`), reason
code, observation time, evidence digest, optional opaque host reference, and a
nullable strict `revocation_subject`. That subject is required exactly for
`intent_revocation`/`revoked`, contains the target `intent_id` and its exact
`revocation_key`, and is null otherwise. Launch is null exactly for that
revocation shape; every runtime verdict requires its original launch. The
observation id covers every canonical non-secret member. Scope equality alone
therefore cannot revoke a successor with a distinct key.

Durable intent authorizes requesting the normal native/host evaluation; it does
not require a pre-existing `allowed` observation that a tool cannot issue until
invocation. The effect boundary still evaluates the current launch, intent,
guard, host and provider. The hard launch fence precedes every owner-authored
effect and ledger write. False, missing or malformed current-launch output
returns a refusal to that caller with zero external effect and byte-identical
ledger state.

After a successful guard, the current owner may request the native/host/provider
evaluation. When a prior rejection requires a fresh evaluation, the transaction
first persists the one-shot consumption described below; only the response from
that first successful persistence carries the evaluation permit. Before persisting its returned `allowed`, `rejected` or `unknown`
observation, it checks the same launch again. If ownership changed meanwhile,
that owner writes nothing; the current successor or an authorized external
observation collector may later ingest the exact non-secret result through the
normal validated input. That collector is the direct/control lifecycle writer
under its ledger lock; it validates the original launch/result binding and
current state and never acts through the stale owner process. If the second
check succeeds, the observation is persisted before the caller stops or
advances. The same rule covers a provider effect that completed while its caller
lost custody: the stale caller cannot write, while validated source-bound
provider evidence remains ingestible through the trusted controller boundary.
An `allowed` event describes only that launch and effect and is never a future grant. A host
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
contract order for `stages`, `stage_facts`, and `pending_stage_ids`; every other array named below is sorted by
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
`deliverable_class`, and `data_ref`; the last uses a closed
`none | literal | selected_output_slot` discriminator. Literal contains digest,
classification and audience. Slot-bound data contains the same slot id plus
fixed classification and audience; its digest is absent until that slot is
immutably selected. The validator requires that data slot id to equal the
containing target slot id.
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
`evidence_digest`. A successor must name the accepted predecessor and carry a new
normalized source fact from the trusted controller boundary. The reducer checks
shape, identity and linkage, not whether a human actually spoke. Appending it
never deletes or changes an authority
observation. In particular, it can make a rejected tuple eligible for a fresh
evaluation only when the new source postdates the rejection and explicitly
covers that exact tuple, or when an accepted `reevaluation-evidence/v1` permits
reevaluation. Merely asserting a successor id cannot clear a refusal.

Each `scope-tuple/v1` has exactly `schema_version` 1, literal `kind`
`scope-tuple`, derived `id`; strict `principal` with exactly `kind` and
`stable_id`; strings `action` and `effect`; strict `target` containing exactly
`project_id`, `provider`, `repository_id`, `repository_slug`, `issue`, `branch`,
`base`, `pr_ref`, and `output_ref`; discriminated `endpoint` (`none | literal`);
discriminated `data` (`none | literal | selected_output_slot`, with the fields
defined above); string `risk`;
and discriminated `spend` (`none | ceiling`, with unit and nonnegative integer
ceiling). A literal ref is equality-only. A slot ref narrows exactly once through
a `selected-output/v1` containing exactly `schema_version` 1, literal `kind`
`selected-output`, derived `id`, `contract_digest`, `slot_id`, `subject_kind`,
`subject_value`, `data_identity_digest`, `repository_id`, `branch`, `base`,
`evidence_digest`, and sorted unique `review_evidence_ids`. The data identity is
the canonical digest of the reviewed output payload manifest. The selected
subject must satisfy every declared slot constraint; the binding is immutable
and a second value conflicts before mutation.

Scope matching permits only these narrowings:

| Declared member | Permitted request |
|---|---|
| principal, action, effect, repository/project/issue, endpoint, literal data digest, data classification/audience, risk | exact equality |
| literal PR/output/branch/base | exact equality |
| slot PR/output | the one immutable selected value for the same slot satisfying every declared constraint |
| slot-bound data | the selected output's exact data-identity digest for the same slot; declared classification and audience remain equal |
| spend `none` | exact `none` |
| spend ceiling | same unit and requested integer less than or equal to the ceiling |
| intent time/revocation | request time within the closed validity interval and no matching revocation observation |

`reevaluation-evidence/v1` has exactly `schema_version` 1, literal `kind`
`reevaluation-evidence`, derived `id`, `contract_digest`, `scope_id`,
`rejected_observation_id`, `source_kind` (`host | provider`), `reason_code`, UTC
`observed_at` and `evidence_digest`. The reducer accepts it only as a normalized
source-bound fact from the existing trusted controller/adapter boundary and
structurally binds it to the rejection; it provides no new authentication
service. It is one alternative basis for one fresh evaluation of the same tuple; a
post-rejection successor intent that independently covers the exact tuple is the
other. Neither alternative authorizes the effect, predicts the result, deletes
the rejection, or requires the other alternative.

`authority-evaluation-consumption/v1` is the append-only one-shot record. It has
exactly `schema_version` 1, literal `kind` `authority-evaluation-consumption`,
derived `id`, derived `use_key`, `contract_digest`, `scope_id`,
`rejected_observation_id`, strict `basis`, strict nonnull `custody`, and UTC
`consumed_at`. `basis` has exactly `kind` (`successor_intent |
reevaluation_evidence`) and `id`. `use_key` is the canonical digest of exactly
contract digest, scope id, rejected observation id and basis; it deliberately
excludes custody and time. The full object id covers all members except `id`.
The delivery array is unique by both id and use key. Thus a transfer, retry,
crash or later timestamp cannot mint a second use of the same basis.

For an otherwise eligible unconsumed basis, `reduce_delivery` returns a complete
next delivery containing the new consumption and one nullable
`authority_evaluation` action. That action has exactly literal kind
`native_authority_evaluation`, contract digest, scope id, custody, rejected
observation id, `basis_kind`, `basis_id`, and `use_key`. Workflow-state rechecks custody under
lock and atomically persists the returned next delivery before it emits a
response containing that action. The caller may run the external evaluation
only after validating that response. A persistence failure emits no action. A
replay after persistence returns `reevaluation_consumed` with no action; a crash
after persistence but before evaluation consumes the basis fail-closed rather
than silently resetting it. The returned provider/host fact follows the normal
second current-launch check and observation path.

`authority-observation/v1` has exactly `schema_version` 1, literal `kind`
`authority-observation`, derived `id`, `contract_digest`, `scope_id`, nullable
`launch_id`, closed `authority_kind` and `verdict`, `reason_code`, UTC
`observed_at`, `evidence_digest`, nullable `opaque_host_reference`, nullable
strict `revocation_subject`, and nullable `evaluation_use_key`. The latter is
nonnull only for the result of a D18 post-rejection evaluation and must name the
persisted consumption that caused that evaluation.
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
| `deliver_repository_record` | `write_record` / `repository_write` | `repository_record_proposed`, binding the exact selected record digest to the declared branch/live PR head without claiming integration |
| `publish_branch` | `push_branch` / `repository_write` | `branch_published`, binding repository, branch and exact selected head |
| `open_pr` | `open_pull_request` / `provider_write` | `pr_opened`, binding provider PR, head, base and selected output |
| `merge_pr` | `merge_pull_request` / `provider_write` | `pr_merged`, binding provider PR/head/base/merge SHA |
| `close_tracker` | `close_issue` / `tracker_write` | `tracker_closed`, binding repository/issue and observed closed state |
| `delete_remote_branch` | `delete_remote_branch` / `repository_write` | `remote_branch_absent`, from a successful exact-identity probe |
| `remove_worktree` | `remove_worktree` / `filesystem_write` | `worktree_absent`, from a successful no-follow exact-path/identity probe |
| `delete_local_branch` | `delete_local_branch` / `repository_write` | `local_branch_absent`, from a successful exact-identity probe |

Observation subjects are exact: `selected_output` contains the strict
`selected-output/v1`; record proposal contains repository id, selected record
digest, branch and live PR head plus sorted review evidence ids, but no integration
claim; branch publication contains repository id, branch and selected head; PR
open/merge contains provider repository id, PR number/URL, expected head and
base, with merge SHA and merged state required only for merge; tracker closure
contains tracker repository/issue, closed state, nullable close reason and
tracker observation identity; remote/local absence contains repository id,
exact branch and successful absence result; worktree absence contains canonical
path, recorded worktree identity, no-follow probe mode and successful absence
result. `implementation_delivered` uses the record/commit selected subject,
integration subject, fresh reachability or record-presence result,
merged/integrated subject evidence when merge applies, and sorted
acceptance/review/test evidence
ids. No failure, unknown or mismatched probe has a positive subject
shape.

The contract's `depends_on` graph is acyclic and may refer only to earlier stage
ids. Selection precedes every stage that uses the slot; publish precedes open.
Merge requires the selected output plus its pre-merge acceptance, review and test
evidence and an open PR; it does not require the implementation-delivered
postcondition. After merge, a fresh integration reachability/record-presence
observation establishes implementation delivered. The contract declares whether
closure depends on merge; cleanup depends on the last applicable delivery effect
and durable-detail reachability. The
ordered pending stages are a pure projection: scan contract order, omit observed
or not-applicable facts, and return a stage only after every dependency is
observed or not applicable. If the first pending fact has unmet dependencies,
the response is a typed requirement naming those observations rather than a
different action. Postconditions are likewise pure projections from accepted
observations and stage facts; provider/tracker state never advances an unrelated
stage.

For a normal unmerged PR, the sequence is selected reviewed output and
acceptance/test evidence, branch/PR observation, merge, then a fresh integration
reachability observation that establishes implementation delivered. For a
repository record, `deliver_repository_record` writes only the exact predeclared
reviewed record to the bound branch/PR head; it neither treats that head as
integrated nor reopens substantive implementation. Its integration-subject
presence is observed only after merge. For an already-delivered Nodo-style case,
fresh exact integration and merge observations may establish both postconditions
at intake, leaving only tracker/cleanup stages for remainder custody.

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
fresh full window. The persisted no-progress counter is 0 on the first
suspension at a new progress token, then 1 and 2 on the next two suspensions; those three suspensions
may resume. The fourth stores 3 before terminalizing as stalled and cannot
resume. Meaningful persisted stage/postcondition progress clears the remembered
phase and resets the counter to 0 before the next suspension starts a new epoch.

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

### Shared delivery model seam

One import-safe Python module at
`home/common/agent-skills/scripts/delivery_model.py`, published as
`~/.agents/lib/python/delivery_model.py`, owns only this issue's canonical JSON
bytes/digests, strict delivery object validators, scope narrowing, stage and
postcondition reduction, and custody/checkpoint/summary nested-shape validation.
Its public surface is a small set of pure functions plus model interface version
1. It has no CLI, ledger I/O, clock, provider, project policy, activation logic
or workflow schema selector.

That surface is exactly `MODEL_INTERFACE_VERSION = 1`,
`DeliveryModelError`, `canonical_bytes`, `canonical_digest`,
`validate_delivery_object`, `validate_custody_ref`, `match_scope`, and
`reduce_delivery`. `match_scope` receives the validated contract, one validated
intent, the requested scope tuple, selected outputs, explicit evaluation time,
and matching revocation observations; it never reads a clock or ledger.
`reduce_delivery` receives the validated contract and delivery value plus one
strict evaluation context containing explicit time, nullable custody/current
launch, nullable requested scope, a closed trusted-source kind and candidate
intent, authority, reevaluation and delivery observations. The source kind says
which validated workflow boundary supplied normalized facts; it is not proof of
authority. Reduction validates the intent chain and all bindings and returns a
complete normalized `next_delivery` for persistence, ordered pending stages,
nullable next stage, sorted requirements, completion state, nullable typed
blocking, and nullable `authority_evaluation`. Direct/control may persist a
well-formed trusted candidate authority fact bound to its original old launch;
only an allowed fact bound to the evaluation custody is eligible for the current
effect. Checkpoint/summary cannot introduce such a late fact. This preserves old
allowed/rejected history without turning an old allow into a new grant. The
one-shot consumption and action are returned together as above, so no caller
must infer persistence from free text.

`validate_delivery_object` is structural and canonical: it cannot know current
ledger custody or authenticate a normalized source/opaque host reference.
Workflow-state supplies trusted normalized inputs, then performs semantic
contract and freshness checks under its lock through `reduce_delivery`.
Artifact-budget invokes the structural validator only. A structurally valid but
stale custody or unverified host claim therefore passes the byte boundary and is
refused or left non-authoritative at the transaction/trust layer rather than
being rejected by invented hash authentication.

Source callers use an explicit-by-path loader, following the existing
`conformance.py` sibling-library pattern, to load the regular source sibling.
Installed workflow-state and artifact-budget use that same loader contract
against the one lexical `~/.agents/lib/python/delivery_model.py` publication;
they never rely on `sys.path`, a bare import or siblings behind independently
resolved Nix-store file targets. Both require model interface version 1;
absence, a directory/non-file resolution or a version mismatch fails before
decode/mutation. `Path.is_file()` deliberately accepts Home Manager's lexical
library symlink to its regular Nix-store target; loaders do not bypass that
public topology by resolving a different sibling. Neither caller keeps a
duplicate validator or narrowing table.
Focused module tests exercise the canonical model and reduction directly,
including source and generated installed import layouts.
Workflow-state remains the sole state/transition writer; artifact-budget owns
only report boundary validation. Introducing the pure module and its tests does
not select schema 3 or interface 2, so it may be prepared and reviewed before the
single atomic adoption that moves every producer/consumer together.

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
`reevaluation_evidence`, sorted `authority_evaluation_consumptions`, sorted
`delivery_observations`, sorted `selected_outputs`, ordered `stage_facts`, and
`postconditions` with exactly the
four named keys; each value has exactly `state`
`pending | observed | not_applicable` and nullable `observation_id`, with the
same state/id relationship as stage facts. A remainder record has exactly
`remainder`, `contract_digest`,
`source_attempt`, nullable `prior_remainder`, ordered `pending_stage_ids`,
`owner`, `worktree`, `state`, `launches`, `deadline_at`, `progress_token`,
`blocked_on`, `suspend_phase`, `stalled_resumes`, `result`, and `result_source`.

Migration is adjacent, atomic and idempotent. Mutation commands first validate
the complete interface-2 request, then under the ledger lock call
`upgrade_state(value, run_id=..., migration_contracts=...)`. The issue-keyed
migration contracts are the request's already structurally validated canonical
contracts or null; they are context, not inferred authority. A valid schema-1
ledger follows the already supported 1→2 migration and the new 2→3 migration
in memory, then `validate_state(candidate, run_id=run_id)` validates the complete
schema-3 value before at most one replacement with the command's actual
transition; no intermediate schema-2 write is exposed. Empty legacy delivery may
initialize with a null contract. Candidate delivery facts, remainder dispatch or
a nonempty authority chain require one unambiguous matching contract in that
context; missing, conflicting or repository-mismatched context refuses with no
write. Unknown fields, partial v3 shapes, malformed legacy rows or invalid input
likewise refuse before replacement.

Read-only `current-launch` never calls `upgrade_state`: it validates schema 1/2
through the retained legacy validator and projects only implementation custody,
or validates schema 3 normally. It returns the same exact four-key current result
at exit 0 for every well-formed negative and never locks, creates or persists.
A remainder id against legacy state is a well-formed negative. Older installed
helpers reject v3 without mutation. Later
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
workflow-state module, artifact-budget wrapper and dynamically loaded module,
shared budget policy, selected interpreter/runtime closure, and environment inputs that affect
HOME/PATH/shebang and policy resolution. The exact identities for this run live
only in retained controller evidence; production defaults and this design do not
hardcode machine hashes. Before finishing the old run, the controller re-resolves
the declared topology and compares the complete evidence set, then uses only the
retained compatible v2/v1 path. Drift fails closed without modifying the ledger,
installing a patch or asking a routine new permission question.

No shipped verifier owns or opens the live issue-151 ledger, and the product
does not commit copies of the historical runtime. The root controller retains
the exact old toolchain outside the product and owns isolated conformance for
legacy-summary finish after simulated worktree removal, old-helper schema-3
refusal, manifest/runtime drift refusal, the public-link pre-finish recheck and
proof that the real ledger stayed unchanged. Those complete receipts are primary
operational evidence for this run. Product tests instead exercise the new source
migration/report/caller interfaces with temporary ledgers in their normal source
and generated installed layouts. The source delivery adds no bridge runtime and
imposes no activation requirement.

Control interface 2 is exactly `{interface_version,now,max_parallel,
attempt_budget_minutes,human_directed,issues,tracker,owners,worktrees,forge,
delivery_contracts,authorization_intents,authority_observations,
reevaluation_evidence,delivery_observations}`. It replaces only each `owners`
member below and adds the final six issue-keyed maps. `forge` values are exactly
`{state,url,merge_sha}`; contracts are strict object or null; the other four
values are sorted unique named-object arrays, including explicit `[]`.
Every map has exactly the requested issues' canonical decimal keys.
Missing/extra/noncanonical keys, or null contract with candidate facts, refuse
before lock. Direct interface 2 is exactly `{interface_version,issue,now,
attempt_budget_minutes,new_run,owner_unavailable,tracker,worktree,forge,
delivery_contract,authorization_intents,authority_observations,
reevaluation_evidence,delivery_observations}`; its contract is strict or null
and its four fact arrays are sorted and unique.

A control `owners` member is exactly `{event_id, issue, custody, state:
unavailable}`. Duplicate event or `(issue,kind,ordinal,launch)` refuses. Custody
must name a known issue-bound action; hybrid, unknown and mismatch refuse. A
known historical fact is retained but affects no current custody; bootstrap
requests a probe and is not itself an unavailable fact.

Every v2 owner/checkpoint/report uses `custody-ref/v1`: implementation is exactly
`{kind:implementation,attempt,launch,action_id}` with action id
`issue:attempt:launch`; remainder is exactly
`{kind:remainder,remainder,launch,action_id}` with action id
`issue:r<remainder>:launch`. Ordinals and launches are positive integers.

The delivery requirement union is exact `{kind,subject_id,reason_code,
detail_pointer}` with kind `delivery_contract | scope_tuple | observation |
worktree_fact` and nullable durable detail pointer. A direct `observe` response
retains exact v1 `{interface_version,kind,issue,run_id,requirements}` at version
2; each ordered requirement is exactly `{kind:tracker}`,
`{kind:recorded_worktree,path}`, `{kind:candidate_worktree}`, one
`{kind:forge_pr,path}`, or one delivery requirement. Unknown/hybrid requirements
refuse. Direct `terminal` retains exact
v1 `{interface_version,kind,issue,run_id,source,reason,blockers,result,reentry}`
at version 2; its nullable legacy result uses the compositional validation below.
With no contract, direct returns `observe` containing the exact
`delivery_contract` requirement and issues no owner/remainder action.

An implementation `owner` response is exactly `{interface_version,kind,
ledger_repo_root,run_id,issue,attempt,owner,action_id,launch_kind,worktree,
handoff_path,deadline_at,custody,contract,contract_digest,pending_stage_ids,
requirements,authority_evaluation}`. Pending stages are contract ordered and
unique; requirements are sorted. Attempt/action/owner/issue must agree with
implementation custody. A control `spawn | resume | retry`
action retains exact v1 `{id,kind,issue,attempt,owner,worktree,handoff_path,
deadline_at}` and adds that same delivery block; outer control supplies run id
and the caller already owns repository-root context. A `delivery_remainder`
response is exactly `{interface_version,kind,ledger_repo_root,run_id,issue,
source_attempt,owner,custody,worktree,contract,contract_digest,pending_stage_ids,
deadline_at,requirements,authority_evaluation}`. It requires remainder custody,
canonical contract digest and exact identity/timestamp correlations.

Control response retains exact outer v1 `{interface_version,run_id,now,summaries,
deltas,actions,next_deadline}` at version 2 and adds no ledger root. Each summary
replaces `attempt` with nullable strict `custody`, retains `issue,state,owner,
worktree,deadline_at,blocked_on,blockers,result`, and adds nullable
`contract_digest`, contract-ordered unique `pending_stage_ids`, and sorted
`requirements`. Thus a
summary can return a `delivery_contract` requirement before an owner/action
exists; null digest requires empty pending stages and no candidate-derived
requirement. Each delta is exact `{issue,custody,kind,state}`, with nullable
custody replacing attempt. `wait` is exactly `{id,kind,wake_on,deadline_at}` and
`finalize` is exactly `{id,kind}`;
actions use only the implementation or remainder shapes above. All nested
members, null/state correlations, ordering and identities validate recursively.

Partial progress `ship-checkpoint/v2` is exactly `{interface_version,issue,
custody,contract_digest,delivery_observations,authority_observations,
reevaluation_evidence,detail_state,report_path,notes}`. Workflow-state validates
raw bytes before decode, locks, rechecks custody, folds facts and persists before
responding. Ordinary `delivery_checkpointed` is exactly `{interface_version,
kind,ledger_repo_root,run_id,issue,owner,custody,contract_digest,
accepted_observation_ids,pending_stage_ids,next_action,requirements,
authority_evaluation,state,blocked_on}` with state `active | suspended` and
correlated nullable members. Count-3 unchanged progress instead returns exact
`delivery_stalled`: the common identity/observation/contract-ordered unique
pending fields plus state
`terminal_failed`, `stalled_resumes:3`, `result_source:stalled`, and reason
`suspension_stalled_without_progress`, with no action/requirements/evaluation.
The reducer maps missing/new authority and operative denial to `human_gate`,
provider/forge wait to `external`, and actual tool transport failure to
`transport`; locally obtainable evidence remains a typed requirement and
`unknown` remains reaper-only. Blocking suspends the same custody and preserves
prior progress.

`ship-handoff/v2` has exactly `interface_version`, `state`, `ledger_repo_root`,
`run_id`, `owner`, `owner_worktree`, `custody`, `issue_number`, `branch`,
`worktree_path`, `spec_artifact`, `plan_artifact`, `head_sha`, `review_state`,
`auto`, `report_path`, `notes`, `delivery_contract`,
`delivery_contract_digest`, `authorization_intents`,
`authorization_chain_digest`, `authority_observation_ids`,
`reevaluation_evidence_ids`, `authority_evaluation_consumption_ids`,
`pending_stage_ids`, and `selected_outputs`.
`ship-summary/v2` is exactly `{interface_version,issue,state,custody,
historical_owner_result,delivery_contract_digest,delivery_observations,
authority_observations,reevaluation_evidence,detail_state,report_path,notes}`;
state is `delivery_complete | terminal_failed`. Finish validates it before
decode, rechecks custody under lock and persists before output. Its common
response is exactly `{interface_version,kind,ledger_repo_root,run_id,issue,owner,
custody,contract_digest,accepted_observation_ids,pending_stage_ids,state}`.
Complete requires kind/state `delivery_complete` and no pending stages. Failure
adds `result_source:owner` and reason `owner_reported_failure`, with kind/state
`terminal_failed`; count-3 stall uses `delivery_stalled`. An eligible retry emits
`delivery_remainder`. Requirements or partial success never become failure.

`authority_evaluation` is null or exactly `{kind:native_authority_evaluation,
contract_digest,scope_id,custody,rejected_observation_id,basis_kind,basis_id,
use_key}` and must match its enclosing contract/custody. After its persisted
consumption, a returned allowed observation satisfies operational authority only
when `evaluation_use_key` names that consumption, its contract/scope/custody
match, `observed_at >= consumed_at`, and a currently valid user intent covers the
exact tuple. The original denial remains historical. Any same-scope rejection at
or after that allow wins. An old-launch allow, unconsumed/cosmetic basis, or
allow lacking current intent never authorizes an effect.

The workflow-response union is exactly current-launch; `workflow_bootstrap`;
control; direct `observe | owner | terminal | delivery_remainder`; ordinary or
stalled checkpoint; and complete, failed or remainder finish. Bootstrap is exact
`{interface_version,kind,run_id,requirements}`; each sorted requirement is exact
`{issue,owner,custody,recorded_worktree}`. Every nested member validates before
decode. Unknown kinds, missing/extra keys and legacy/new hybrids refuse. The
validator proves structure and internal identity only; ledger freshness and
source authenticity remain locked/trusted checks. All callers cut over together.
Current-launch is exactly `{action_id,current,current_action_id,reason}` with
reason `unknown_run | unknown_issue | unknown_attempt | superseded_attempt |
inactive_attempt | superseded_launch | current` and source-defined null/id
correlations; inactive custody may name itself as current action. Remainder
custody uses the same closed reasons. Nullable legacy `result` members in control
summary and direct terminal are compositional slots: the pure model validates
the exact containing envelope and null/object position but does not copy the
legacy row schema. Artifact-budget/workflow-state must run the existing legacy
result validator on each nonnull slot before accepting raw workflow-response
bytes, then run the model validator; neither validator alone is boundary success.

### Deterministic simulated acceptance cases

Fixtures use reserved `sim.invalid` identities, fixed synthetic 40-hex object
ids and canonical fake-provider state. They contain no external repository
payload, raw transcript or asserted historical grant.

- **Nodo 1314 behavior:** a simulated six-criterion acceptance map and five-test
  evidence set bind the selected subject. Fake repository and forge observations
  establish implementation delivery and merge at intake; tracker and cleanup
  remain pending. Direct-owner returns `delivery_remainder(close_tracker, cleanup)`,
  never implementation. Fake closure and absence observations persist all four
  postconditions and complete the delivery.
- **Arcwave 113/record PR 116 behavior:** tracker closure is already observed,
  while the exact simulated decision-record digest and live PR/head remain
  pending. With matching intent/worktree/PR evidence, the same run dispatches
  `deliver_repository_record`; that stage proposes only the selected reviewed
  record. Review/acceptance evidence then permits merge, and a fresh integration
  record-presence observation establishes delivery. Without any required fact it
  returns the exact requirement. It never reopens the substantive decision or
  treats closure as cancellation/grant.
- **Argus iteration behavior:** an identical principal, endpoint, data identity,
  private audience, risk and spend tuple reuses the recorded intent. A different
  endpoint, transfer identity or public audience returns the missing tuple before
  effect. A simulated host rejection persists and cannot be retried through new
  spelling/context/host. A later fake human-completion observation may satisfy
  the effect while leaving that rejection historical and granting no agent right.
- **Normal v3 owner behavior:** a simulated implementation owner selects reviewed
  output with acceptance/test evidence, publishes and opens a PR, merges it, then
  records fresh integration reachability. Merge precedes implementation-delivered
  truth; neither fact is fabricated from the other.

## Test seams

Acceptance uses a small set of public executable seams plus caller contract
tests. Plan-only or prose-only evidence is insufficient.

1. **Workflow-state CLI round trip.** Temporary real ledgers invoke init,
   direct-owner/control, current-launch, checkpoint-delivery and finish through
   subprocesses. Feed strict fake-adapter observations for all simulations,
   including an ordinary source-v3 implementation owner. Assert the typed
   next stage, no implementation dispatch/attempt consumption, persisted
   historical result and observations, deduplicated replay, two-ordinal cap,
   exact four-suspension/three-resume stall behavior plus progress reset,
   merge-before-expiry, capacity ordering and
   no filesystem mutation from current-launch.
2. **Artifact/report/response CLI boundary.** Validate canonical v2
   handoff/checkpoint/summary and workflow-response bytes and reject legacy/new
   hybrids, internally inconsistent contract/custody ids, missing postcondition
   evidence, invalid host-reference types, unsuccessful absence probes and
   unknown fields. Then prove structurally valid stale custody, audience/data
   mismatch and a well-shaped opaque host reference reach workflow-state's
   locked semantic/trust checks, where freshness refuses byte-identically and a
   reference alone grants nothing. Assert stored facts/results, not helper calls.
3. **Controlled provider-effect replay.** A fake provider records effects and
   returns typed observations. Drive from the public direct response through
   checkpoint and terminal summary paths into the ledger. Prove one exact
   authorized effect occurs,
   rejected/missing scope causes zero effects, and a stale launch causes both zero
   effects and a byte-identical ledger. Prove a denial produced after custody
   changes cannot be written by the old owner but can be ingested by the current
   successor. Prove an authorized partial effect checkpoints durably, a later
   host denial atomically suspends the same custody, resume does not spend a
   retry, independently completed effects need no agent mutation, and
   Nodo/Arcwave/normal delivery terminate with the four truthful postconditions.
4. **Production caller contracts and orchestration eval.** Pin that from-issue,
   AUTO, ship-issue and orchestration validate before decode, copy the contract
   exactly, execute only the closed action/stage for the returned custody,
   persist before reporting, preserve denial and never synthesize
   implementation/new authority.
   These tests supplement, not replace, the executable round trips above.

All product v3 runtime replays use isolated temporary ledgers and the complete
reviewed new-source toolchain. They cover migration, checkpoint/summary
validation, caller interfaces and new installed layout without reading HOME, the
real issue-151 ledger, repository operational evidence or `/private/tmp`. The
controller separately runs and retains the exact-old-generation compatibility,
removed-worktree, schema refusal, drift, whole-generation recheck and live-ledger
byte-preservation receipts described above; none is replaced by a prose claim or
a shipped historical-code fixture.

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
| D2 | Keep authorization intent append-only and secret-free; match its exact canonical tuple with the closed per-field narrowing grammar, including target and data identities bound to the same immutable future-output slot, then evaluate current guard/host/provider authority at each effect. | #116 D1; retained #117 intent semantics; private/public denial case. | Requiring an unknowable initial payload digest repeats permission after review, while URL/action subsets or null wildcards omit payload/audience/risk. |
| D3 | Record host/guard/provider outcomes as launch-bound observations with derived non-secret ids and optional real host references only after a second current-launch check; a stale owner has zero effect and zero write. | Current read-only guard semantics; host may expose no stable id; issue 151 criterion 6. | Persisting a late denial from a stale owner weakens the same fence that protects effects. |
| D4 | Track exact stage facts plus delivered, merged, closed and cleanup as independent typed observations; pre-merge review/acceptance permits merge, while fresh post-merge integration reachability establishes implementation delivered. | Issue 151 criterion 2; truthful-terminal standard; retained #117 D7. | Requiring delivered-before-merge is circular, while deriving delivery from merge fabricates acceptance/reachability. |
| D5 | Add a separate capped remainder lineage with disjoint ordinals/action ids; in-place resumes do not spend implementation or remainder retry counts. | Nodo/Arcwave cases; #132/#133; root critical custody constraint. | Reopen implementation or append unbounded generic retries. |
| D6 | Permit one retry remainder only after authentic failure plus absent effect and a valid recovery basis; otherwise park while accepting independent completion evidence. | Current two-attempt cap; no-blind-retry and stall rules. | Unlimited successor churn or treating environment suspension as a failed attempt. |
| D7 | Make worktree absence positive only for a predeclared cleanup target; require exact matching worktree/subject/PR for record delivery. | Current phase-zero/misbinding rules; cleanup semantics. | Branch-prefix discovery or absence-as-general-success weakens fencing. |
| D8 | Preserve old result bytes/detail and migrate schema 2→3 without inventing contracts, grants or successful observations. | One ledger; immutable history; current schema baseline. | Rewrite a terminal result or promote legacy booleans into fresh evidence. |
| D9 | Cut over state, direct/control, checkpoint/terminal artifact reports, from-issue, shipping and orchestration as one versioned interface delivery using the closed implementation/remainder custody union. | Defense in depth; all production producers/consumers must agree. | A remainder-only terminal summary misrepresents ordinary owners and partial progress; validator-first rollout admits mixed shapes. |
| D10 | Accept the three audited behaviors only through deterministic simulated identities, intent and provider state. | Audit cases 2–4 lack safe exact live metadata and authorize no external mutation. | Copy transcripts/private payloads or present invented SHAs/grants as history. |
| D11 | Prove acceptance through public CLI/provider-effect round trips, including ordinary v3 delivery and partial-effect checkpoint/denial/resume, with text/eval contracts only as supplementary caller coverage. | The-bar tests that can fail; issue 151 runtime gap. | Terminal-only and plan-only tests can pass while partial facts are lost or a requirement is mislabeled failure. |
| D12 | Finish issue 151 through its run-specific retained v2/v1 operational bridge; keep exact-old-generation conformance/topology/runtime receipts with the root controller, test only new-source product interfaces in shipped suites, and activate v3 only through separate managed scope. | #66 bridge/activation separation; dynamic validator/module/policy resolution; worktree cleanup removes source. | Hardcoded machine hashes, committed historical runtime fixtures, a generic bridge runtime, migrating the live run or depending on its deleted worktree would mix product behavior with one delivery's operations. |
| D13 | Put canonical delivery validation, narrowing and pure reduction in one import-safe `delivery_model.py` published as a library and consumed by workflow-state and artifact-budget; adopt every wire atomically after the pure seam is reviewed. | DRY; review-package feasibility; current source/installed Python layouts. | Duplicate validators drift, while a generic framework or early schema cutover would exceed this issue and violate D9. |
| D14 | Keep valid schema-1 ledgers readable by applying the existing 1→2 migration and the new 2→3 migration as an adjacent in-memory chain, validating the complete schema-3 result, and performing at most one atomic write. | Current source already supports schema 1→2; D8 requires immutable legacy history; an interface cutover must not strand an older valid ledger. | Setting the sole prior version to 2 would reject supported schema-1 history, while persisting an intermediate schema-2 ledger would expose a partial cutover. |
| D15 | Give the pure model one closed eight-name public surface with explicit contract/intent/time/custody/candidate inputs and a complete persistable next-delivery result; checkpoint/owner/bootstrap output is closed; only durable one-shot consumption may expose an authority-evaluation action, and only the fourth unchanged suspension returns the stalled terminal variant. | D2/D3 require explicit facts; D9 atomic cutover; D13 one contract owner. | Caller-specific reduction dictionaries, ambient reads, free-text consumption, or an open response would duplicate policy and permit replay. |
| D16 | Keep artifact/model validation structural, add one raw `workflow-response` union boundary, and reserve ledger freshness plus normalized-source/host authenticity for workflow-state under lock and the existing trust boundary. | Defense in depth; D3 launch fence; normalized controller facts are not authenticated by digests or opaque references. | Asking the stateless artifact validator to reject a once-valid stale action or fabricated but well-shaped source claim would invent authority and make public tests impossible. |
| D17 | Upgrade schema 1/2 only inside a mutation transaction with explicit request-derived contract context and final `validate_state(..., run_id=...)`; keep current-launch on a no-write legacy read path. | D8/D14 immutable history and atomic migration; current no-lock/no-create launch guard. | Value-only migration cannot resolve new contract context, while upgrading during current-launch would make a read-only fence mutate or strand legacy runs. |
| D18 | Bind each fresh post-rejection evaluation to one append-only consumption keyed by rejection and its independent successor-intent or reevaluation-evidence basis; persist before action, bind the returned fact by use key/time/scope/custody, require current intent, and let a new rejection win while retaining all history. | Operative-denial and late-collector requirements; response-closure review. | Replayable evidence, crash-reset permission, cosmetic-basis authority, or old-launch allow reuse. |
