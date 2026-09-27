# Delivery reconciliation and authorization continuity — issue 151

Decision for [#151](https://github.com/fagenorn/nix-config/issues/151), 2026-09-21.
Status: delegated. Nodo, Arcwave and Argus are deterministic simulations, not
claims about live state, grants or provider identities.

## Problem

Reviewed source can coexist with pending merge, closure or cleanup; one terminal
attempt result cannot truthfully express delivery, authority and finite custody.

## Solution

Persist the canonical contract/facts below and atomically adopt the pure model,
schema 3, interface 2, finite remainders and every caller. D1–D22 bind.

## Decisions

### One immutable delivery contract

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

The contract contains no executable grant. Authorization intent is append-only;
contract, intent and canonical digests prove identity only. A contractless legacy
issue returns a typed `delivery_contract` requirement; only the existing trusted
controller supplies normalized provenance, while native effect authority remains
independent.

### Closed authorization scope and runtime authority

Intent and scope use the exact closed fields in the canonical wire appendix.
Audience is private, public or a named-audience digest. Slot data takes its digest
only from that slot's reviewed binding.

Canonical comparison uses all members and the closed narrowing grammar below.
There is no generic string subset rule. Expired intent or an observed revocation
is unusable. A selected PR/output binding must resolve before its effect; moving
branch state is not a binding. Resolving a slot-bound data digest from that same
reviewed output is the declared narrowing, so it needs no new permission merely
because the bytes are now known. A different slot/target, classification,
audience, action or effect still refuses.

Public audience or changed payload/data never matches private publication intent,
even at the same repository URL. Administration grants nothing; the live #152
denial concerns one action and permits no retry.

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

The actual proposed effect is an independently built nullable
`scope-tuple/v1`, never copied from intent. After folding facts the model alone
binds it to the ordered ready stage/action/effect/target/selection. Wrong,
dependency-blocked, completed or contractless scope refuses with zero writes.
For a ready stage, null returns exactly
`{kind:scope_tuple,subject_id:<stage-id>,reason_code:scope_tuple_required,
detail_pointer:null}`; uncovered scope returns the
`authorization_intent_required` human gate; covered ordinary scope may
native-evaluate after the fence without prior allow. D18 alone requires durable
post-rejection consumption.

Each later stage/transfer/resume proposes fresh scope and effect output echoes
it. Null may persist facts/custody but permits no effect/evaluation. Checkpoint
scope applies only to the post-fold stage; completion/remainder is null. With no
ready stage, missing postconditions return exact
`{kind:observation,subject_id:<postcondition>,
reason_code:postcondition_observation_required,detail_pointer:null}`. Handoff
scope is history; terminal/stalled output has none.

### Canonical wire and narrowing appendix

New v1 objects require every named key, reject unknown/duplicate keys, and admit
JSON `null` only where nullable; null is never a wildcard. Canonical
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
`evidence_digest`, and sorted unique nonempty `acceptance_evidence_ids`,
`review_evidence_ids`, and `test_evidence_ids`. Each array contains nonempty
evidence-id strings. The trusted collector verifies that every reference proves
its declared category; ids/prefixes never imply category, and one report may
support several categories. The data identity is the reviewed payload-manifest
digest. The subject must satisfy every slot constraint; selection is immutable
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
| implementation delivered | selected reviewed commit/tree/record digest; integration subject; typed reachability or record-presence result; category-matched acceptance/review/test evidence references |
| PR merged | provider repository id; PR number/URL; expected head; base; merge SHA; provider-observed merged state |
| tracker closed | tracker repository/issue; observed closed state; close reason when available; tracker observation identity |
| cleanup complete | declared remote branch, local branch and worktree probes; all required objects absent; required durable detail/evidence pointer successfully re-read |

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
| `select_reviewed_output` | `select_output` / `ledger_write` | `selected_output`, including the immutable slot binding and its acceptance, review and test evidence |
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
claim; its selection supplies acceptance/test proof. Branch publication contains repository id, branch and selected head; PR
open/merge contains provider repository id, PR number/URL, expected head and
base, with merge SHA and merged state only for merge; tracker closure contains
tracker repository/issue, closed state, nullable close reason and observation
identity; remote/local absence contains repository id, exact branch and literal
`absent:true`; worktree absence contains canonical path, recorded identity,
`probe_mode:no_follow` and literal `absent:true`.

`implementation_delivered` is exactly `{selected_subject,integration_subject,
presence,merge_observation_id,acceptance_evidence_ids,review_evidence_ids,
test_evidence_ids}`. Both subjects are exact `{kind,value}` with kind
`commit | tree | record`; `presence` is exactly `{kind,repository_id,
selected_value,integration_value,integrated_ref,succeeded}` with kind
`reachability | record_presence` and literal `succeeded:true`.
`merge_observation_id` is null only when merge is inapplicable; the three
evidence-id arrays are sorted, unique and nonempty. `cleanup_complete` is exactly
`{remote_branch_observation_ids,local_branch_observation_ids,
worktree_observation_ids,durable_detail}`; the three sorted unique arrays contain
the accepted exact-target absence observations required by the contract, and
`durable_detail` is exactly `{detail_pointer,read_evidence_digest,succeeded}`
with literal `succeeded:true`. Reducer matching binds every referenced
observation to the same contract, selected/integrated subject and declared
cleanup target. Successful delivery contains the selected output's acceptance,
review and test references in the corresponding arrays; another category cannot
substitute. Failure, unknown, mismatched probe or unreadable detail has no
positive shape.

Dependencies are acyclic and earlier-only; selection precedes slot use and
publish precedes open. Pending stages scan contract order; unmet dependencies
return typed observation requirements. Merge needs all three evidence categories
and an open PR; fresh reachability/record presence proves delivery. Human
completion advances only its exact fact and grants no authority. Migration
promotes no legacy claim into stage/postcondition truth.

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
one pending predeclared stage or required pending postcondition, and no active
implementation owner. Its creation
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
current implementation-attempt ceiling without consuming it. Remainder 2 is allowed only under D21's exact terminal failure, successful
absence, retryable-stage and recovery-basis contract. A guard, host or provider rejection/unknown is not a
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

### Shared delivery model seam

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

Source loads `scripts/delivery_model/__init__.py`; installed loads lexical
`~/.agents/lib/python/delivery_model/__init__.py`. The loader creates that
package namespace/search location for relative imports and removes partial
members on failure. It never edits/searches `sys.path`, falls back or loads
private files independently. Missing entry/private files, non-file entry or
wrong interface refuses before decode/mutation. The managed directory symlink to
one store package is valid. Neither caller duplicates model policy.
Focused module tests exercise the canonical model and reduction directly,
including source and generated installed import layouts.
Workflow-state remains the sole state/transition writer; artifact-budget owns
only report boundary validation. Introducing the pure module and its tests does
not select schema 3 or interface 2, so it may be prepared and reviewed before the
single atomic adoption that moves every producer/consumer together.

Private source/installed `workflow_delivery.py` exposes exactly
`WORKFLOW_DELIVERY_INTERFACE_VERSION = 1` and `DeliveryRuntime`. It owns v2
admission, schema-3 delivery validation and the pure shared transition;
workflow-state owns CLI, custody, locks, one write and effects. Adjacent private
`workflow_delivery_wire.py` owns pure state/response projection and v2
owner/worktree grammar; runtime absorbs pure request/state correlations. Both
load lexically in source/managed-installed layouts and refuse missing/wrong
members before decode/mutation. No callbacks, fallback, `sys.path` edits,
policy copies, model-private calls or parallel v1 effect path.

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

Issue 151's active run finishes only through root's retained old-generation
operational bridge. Shipped source never opens/migrates that ledger, hardcodes
machine identities, installs a bridge or treats integration as activation.
Product tests use synthetic source/generated-installed layouts; root separately
retains topology, drift and legacy-finish evidence.

Control interface 2 is exactly `{interface_version,now,max_parallel,
attempt_budget_minutes,human_directed,issues,tracker,owners,worktrees,forge,
delivery_contracts,authorization_intents,authority_observations,
reevaluation_evidence,delivery_observations,requested_scopes}`. It replaces only
nested `owners` and adds the final seven issue-keyed maps. `forge` values are
exact `{state,url,merge_sha}`; contracts are strict object|null; the four fact
maps hold sorted unique named-object arrays (explicit `[]`); requested scopes
hold strict `scope-tuple/v1`|null. Every map has exactly the requested canonical
decimal issue keys. Missing/extra/noncanonical keys, or null contract with facts
or nonnull scope, refuses before lock. Direct interface 2 is exactly
`{interface_version,issue,now,attempt_budget_minutes,new_run,owner_unavailable,
tracker,worktree,forge,delivery_contract,authorization_intents,
authority_observations,reevaluation_evidence,delivery_observations,
requested_scope}` with the singular equivalents.

A control owner fact is exact `{event_id,issue,custody,state:unavailable}` with
nonempty event id. Duplicate event or `(issue,kind,ordinal,launch)` refuses;
custody must name a known issue-bound action. Historical facts are retained but
have no current effect; bootstrap requests a probe and is not an unavailable
fact. Every v2 owner/checkpoint/report uses `custody-ref/v1`: implementation is
exact `{kind:implementation,attempt,launch,action_id}` with action
`issue:attempt:launch`; remainder is exact
`{kind:remainder,remainder,launch,action_id}` with `issue:r<remainder>:launch`.
Ordinals/launches are positive.

The delivery requirement union is exact `{kind,subject_id,reason_code,
detail_pointer}`, kind `delivery_contract | scope_tuple | observation |
worktree_fact`, nullable durable detail pointer. Direct `observe` retains exact
v1 `{interface_version,kind,issue,run_id,requirements}` at v2; its ordered
requirements are exact `{kind:tracker}`, `{kind:recorded_worktree,path}`,
`{kind:candidate_worktree}`, `{kind:forge_pr,path}`, or one delivery requirement.
Direct `terminal` retains exact v1 `{interface_version,kind,issue,run_id,source,
reason,blockers,result,reentry}` at v2. Unknown/hybrid requirements refuse;
nullable legacy result uses the compositional check below. No contract yields
only the exact contract requirement and no owner/remainder action.

Implementation `owner` is exactly `{interface_version,kind,ledger_repo_root,
run_id,issue,attempt,owner,action_id,launch_kind,worktree,handoff_path,
deadline_at,custody,contract,contract_digest,pending_stage_ids,requirements,
authority_evaluation,requested_scope}`. Control `spawn | resume | retry` retains
exact v1 `{id,kind,issue,attempt,owner,worktree,handoff_path,deadline_at}` plus
that delivery block. `delivery_remainder` is exactly `{interface_version,kind,
ledger_repo_root,run_id,issue,source_attempt,owner,custody,worktree,contract,
contract_digest,pending_stage_ids,deadline_at,requirements,authority_evaluation,
requested_scope}`. Identities/timestamps/digest/custody must correlate; pending
stages are contract-ordered/unique and requirements sorted. Requested scope is
canonical and exactly the reducer-returned post-fold proposal. Null requires
completion or a local requirement. Finish remainder is custody-only with null:
a ready stage uses its stage-keyed scope requirement; with no ready stage, each
missing postcondition uses exact `{kind:observation,subject_id:<postcondition>,
reason_code:postcondition_observation_required,detail_pointer:null}`. No effect
stage is invented for observation-only proof.

Control output retains exact outer v1 `{interface_version,run_id,now,summaries,
deltas,actions,next_deadline}` at v2 and no ledger root. Summary replaces
`attempt` with nullable custody, retains `issue,state,owner,worktree,deadline_at,
blocked_on,blockers,result`, and adds nullable contract digest, ordered pending
stages and sorted requirements. Null digest requires no custody/pending/candidate
requirement except the contract requirement. Delta is exact
`{issue,custody,kind,state}`; wait `{id,kind,wake_on,deadline_at}`; finalize
`{id,kind}`. Actions use only owner/remainder shapes. All nested identities,
ordering, null/state and legacy-result correlations validate recursively.

`ship-checkpoint/v2` is exactly `{interface_version,issue,custody,
contract_digest,delivery_observations,authority_observations,
reevaluation_evidence,requested_scope,detail_state,report_path,notes}`. Validate
raw bytes, then under lock recheck custody, fold observations and persist before
response. Its scope proposes only the ready stage after that fold; completion
requires null, and nonnull with no ready stage refuses without write. Ordinary
`delivery_checkpointed` is exact `{interface_version,kind,ledger_repo_root,
run_id,issue,owner,custody,contract_digest,accepted_observation_ids,
pending_stage_ids,next_action,requirements,authority_evaluation,requested_scope,
state,blocked_on}`, state `active | suspended`, with exact scope/nested-action/
evaluation correlation. Count-3 instead returns `delivery_stalled`: common
identity/accepted/ordered-pending fields plus `state:terminal_failed`,
`stalled_resumes:3`, `result_source:stalled`, reason
`suspension_stalled_without_progress`, and no action/requirements/evaluation/
block/scope. Missing/new authority and operative denial map to `human_gate`,
provider wait to `external`, transport failure to `transport`; local evidence is
a requirement and `unknown` is reaper-only. Ordinary blocking preserves custody.

`ship-handoff/v2` has exactly `interface_version,state,ledger_repo_root,run_id,
owner,owner_worktree,custody,issue_number,branch,worktree_path,spec_artifact,
plan_artifact,head_sha,review_state,auto,report_path,notes,delivery_contract,
delivery_contract_digest,authorization_intents,authorization_chain_digest,
authority_observation_ids,reevaluation_evidence_ids,
authority_evaluation_consumption_ids,pending_stage_ids,selected_outputs,
requested_scope`. Scope is the prior action's historical echo and never inherited.
`ship-summary/v2` is exact `{interface_version,issue,state,custody,
historical_owner_result,delivery_contract_digest,delivery_observations,
authority_observations,reevaluation_evidence,detail_state,report_path,notes}`;
state is `delivery_complete | terminal_failed`. Finish validates before decode,
rechecks custody and persists before output. Common response is exact
`{interface_version,kind,ledger_repo_root,run_id,issue,owner,custody,
contract_digest,accepted_observation_ids,pending_stage_ids,state}`. Complete has
kind/state `delivery_complete` and no pending stage; failure adds
`result_source:owner,reason_code:owner_reported_failure` with kind/state
`terminal_failed`; stall uses its variant; eligible retry emits remainder.
Requirement/partial success never becomes failure.

`authority_evaluation` uses D18's exact nullable action, consumption and
operative-allow rules above, matching the enclosing contract/custody. The ordinary
checkpoint echoes its independently requested tuple even when only evaluation is
nonnull; declared scope/custody/use key remain the D18 permit bindings.

The workflow-response union is exactly current-launch; `workflow_bootstrap`;
control; direct observe/owner/terminal/remainder; ordinary/stalled checkpoint;
and complete/failed/remainder finish. Bootstrap is exact
`{interface_version,kind,run_id,requirements}` with sorted exact
`{issue,owner,custody,recorded_worktree}` requirements, selecting sole nonterminal
custody, else latest remainder, else implementation. Callers consume all before
control. Unknown keys, missing/extra members and legacy/new hybrids refuse before
decode. Current-launch is exact `{action_id,current,current_action_id,reason}`;
reason is `unknown_run | unknown_issue | unknown_attempt | superseded_attempt |
inactive_attempt | superseded_launch | current` with existing null/id rules for
both custody kinds. Nullable legacy result slots in summary, terminal and
`historical_owner_result` require both existing legacy validation and model
envelope validation before raw workflow-response acceptance. Structural
validation proves no ledger freshness or source authenticity; all callers cut
over together.

### Deterministic simulated acceptance cases

Synthetic `sim.invalid` cases cover Nodo delivery/cleanup, Arcwave partial
effect/denial/resume or human completion, Argus changed-audience/payload refusal,
and ordinary v3 evaluation/checkpoint/completion.

### D21 — proof required for remainder retry

Direct has nullable `recovery`, control issue-keyed `recoveries`, and
remainders nullable recovery plus `finished_at` (null live, terminal time
otherwise); checkpoint/handoff/summary have none. Recovery is exactly
`{schema_version:1,kind:delivery-recovery,id,contract_digest,stage_id,
requested_scope,failure,effect_absence,basis}`.

Failure is exact `{kind:effect_failure,effect_attempted:true,
classification:transient,source_kind,reference,observed_at,evidence_digest}`;
absence is exact
`{kind:effect_absence,absent:true,probe_succeeded:true}` plus those fields;
source kind is `provider|host|tracker|repository|filesystem`. Basis is exact
`{kind:changed_relevant_evidence,scope_id,source_kind,reference,observed_at,
evidence_digest}`, `{kind:new_authorization,id}`, or explicit-user
`{kind:human_transient_retry,id}`.
Every `reference` is a nonempty string, every `observed_at` is RFC 3339 UTC,
and every `evidence_digest` is a canonical SHA-256 digest.

Only latest terminal owner-failed/stalled R1, no live custody/R2, and ready
retryable work qualify. Failure follows the latest effect launch and precedes
finish; successful absence follows both and precedes request now; basis is newer
and same contract/scope. Rejected/unknown actual or declared scope parks.
Persist R2/proof atomically with no effect/evaluation/consumption and null scope.
Wrong/stale/reused/active/third refuses; replay returns existing/completed
without write; finish mints R1 only.
