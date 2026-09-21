# Delivery Reconciliation Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Add one canonical delivery model and atomically move lifecycle state,
reports, and production callers to truthful delivery reconciliation with finite
remainder custody.

**Architecture:** Task 1 introduces and publishes an import-safe pure model that
owns delivery validation, canonical identity, exact scope narrowing, and pure
stage/postcondition reduction without selecting a workflow schema. Task 2 adopts
that reviewed seam in one source cutover: workflow schema 3, control/direct
interface 2, checkpoint/handoff/summary v2, every production caller, and their
public executable tests move together. It also adds D19's independent actual
scope proposal while the pure model remains the sole stage-policy owner. The two task commits form one delivery;
Task 1 alone is preparatory and does not activate or ship a partial wire.

**Tech stack:** Python 3 standard library, JSON CLI protocols, Nix/Home Manager
file publication, Markdown workflow skills, JSON orchestration evals, `unittest`,
Git, and repository `just` commands.

## Global Constraints

- Per D1–D4, ledger truth is one immutable `delivery-contract/v1` plus append-only
  intent, authority, reevaluation, selected-output and delivery observations;
  canonical digests prove identity but grant no authority.
- Per D2, exact scope matching includes principal, action/effect, project,
  provider, repository, issue, branch/base, endpoint, payload digest,
  classification, audience, risk and spend. Only the declared selected-output
  slot and a same-unit spend ceiling narrow; null is never a wildcard.
- Per D3, the exact custody launch is checked immediately before an effect and
  again before its observation is written. A stale or malformed launch causes
  zero external effects and a byte-identical ledger.
- Per D4, `implementation_delivered`, `pr_merged`, `tracker_closed`, and
  `cleanup_complete` remain independent. The immutable selected output carries
  explicit nonempty acceptance/review/test evidence arrays for merge; delivery
  repeats each category and adds fresh reachability or record presence.
- Per D5–D7, implementation attempts and `delivery_remainders` use disjoint finite
  ordinals and custody ids. In-place resume keeps its ordinal/deadline, merge is
  observed before expiry/reaping, and cleanup/record actions require exact
  predeclared worktree and subject identities.
- Per D8 and D14, preserve legacy attempts, outcomes, result bytes and detail
  pointers. Accept valid schemas 1 and 2 through an adjacent in-memory
  1→2→3 chain, validate schema 3, and perform no intermediate write; migration
  creates no contract, authority, stage fact, postcondition or cleanup success.
- Per D9, schema 3, control/direct interface 2, `ship-checkpoint/v2`,
  `ship-handoff/v2`, `ship-summary/v2`, and all production callers cut over in
  one Task 2 commit. No validator-first, caller-first, nullable-ordinal or hybrid
  compatibility path is accepted.
- Per D10, Nodo, Arcwave and Argus are deterministic `sim.invalid` simulations
  with synthetic ids. No external payload, transcript, SHA, grant or mutation is
  presented as historical fact.
- Per D12, this source delivery does not activate schema 3, migrate the live
  issue-151 ledger, install an ad hoc bridge, or commit old runtime copies. Root
  controller evidence alone covers the retained v2/v1 completion bridge.
- Per D13/D15, the pure import-safe `delivery_model` package exposes exactly
  eight names at interface version 1. Its private canonical/object/wire/reconcile
  modules own new policy once. Callers explicitly load `__init__.py` as a package
  and fail before decode/mutation on missing private members or version mismatch;
  the installed managed directory symlink to one store package is valid.
- Per D20, private `workflow_delivery.py` (installed beside workflow-state)
  exposes only interface version 1 and `DeliveryRuntime`. It owns v2 admission,
  schema-3 delivery-envelope validation and the shared locked transition;
  workflow-state retains CLI parsing, locks, atomic persistence and effects.
  There are no callbacks, policy copies, fallback imports or live v1 effect path.
- Per D22, the runtime's adjacent private `workflow_delivery_wire.py` owns
  state/response projection and interface-2 owner/worktree grammar. Runtime
  absorbs pure v2 state/request correlations; workflow-state keeps CLI, custody
  orchestration, locks, persistence and effects. Concrete lexical source/installed
  loading fails before decode/mutation when the helper is missing/incompatible.
  Both existing interfaces stay unchanged; no callbacks, cycles, policy copies,
  fallback imports or model-private access. Install the helper beside runtime;
  extend existing runtime tests, with no new test module.
- Per D21, only trusted direct/control recovery input may atomically allocate r2
  after a terminal failed/stalled r1: direct carries required nullable recovery,
  control carries the canonical issue-keyed recoveries map, and remainders carry
  nullable recovery and `finished_at`. Exact recovery proof binds the selected
  actual scope/stage, is folded null-first with successor intents, grants no
  authority, and cannot override D18 denial; allocation emits no evaluation,
  effect or consumption.
- Per D16, model/artifact checks prove canonical structure, while workflow-state
  owns locked freshness/semantic checks and native boundaries own source/host
  authenticity. Raw init/control/direct/current/checkpoint/finish responses pass
  the closed `workflow-response` boundary before caller decode.
- Per D17, schema 1/2 upgrades receive request-derived contract context only in a
  mutation transaction and finish with `validate_state(candidate, run_id=run_id)` before
  one write. Read-only current-launch validates legacy state without upgrading.
- Per D18, each post-rejection successor-intent or reevaluation-evidence basis
  has one append-only consumption use key persisted before its evaluation action
  is emitted. A resulting allow binds that use key, time, scope and current
  custody, still requires current user intent, and loses to a new rejection.
- Per D19, direct/checkpoint carry nullable `requested_scope` and control carries
  exact issue-keyed `requested_scopes`. The trusted caller builds actual tuples;
  the model binds them to the post-fold ordered stage. Missing scope is local,
  permits fact/custody persistence but no effect/evaluation; wrong-stage or
  slot-conflicting scope refuses without write, stage-valid uncovered scope is a human gate, and
  ordinary covered scope may run native evaluation without a prior allow. With
  no ready stage, null preserves dependency/postcondition observation requirements
  and no effect stage is invented.
- Every ordinary source file remains below the review packer's 65,536-byte
  per-file diff limit. Do not depend on an unpublished projector or raise any
  root, member, count or aggregate cap.
- Product tests use temporary ledgers, fake providers, source and generated
  installed layouts with an explicit temporary HOME only. They never read the real HOME, `/private/tmp`, the live
  issue-151 ledger, or controller operational evidence.
- Implementation commits are signed and include
  `Co-Authored-By: Codex <noreply@openai.com>`.

## Test seams

- Pure model tests call the public functions directly and load both source and
  generated installed module paths, proving canonical bytes/digests, strict
  objects, slot-bound narrowing, refusal preservation and ordered reduction.
  One private `_delivery_model_fixtures.py`
  supplies synthetic builders by explicit relative import with the model passed
  explicitly; it is not an entry point, production loader or I/O seam.
- Workflow CLI tests invoke real `init-run`, `control`, `direct-owner`,
  `current-launch`, `checkpoint-delivery`, and `finish` subprocesses against
  temporary ledgers. Every successful stdout validates before decode; init's
  exact bootstrap requirements drive owner/worktree observations before control.
- Private runtime tests load source and generated installed layouts, reject
  missing/wrong adjacent model packages before decode, and prove detached
  admission, delivery-envelope and transition results without filesystem I/O.
- Artifact boundary tests feed exact raw v2 handoff/checkpoint/summary and
  workflow-response bytes to
  `artifact-budget validate-report` before any workflow decode and exercise
  unknown keys, hybrids, internally mismatched digests/custody and unsuccessful
  probes. Valid stale custody and well-shaped host/source claims advance to the
  locked semantic/trust-layer tests instead of being misclassified structurally.
- The workflow-response union recursively validates every control summary,
  delta and action; direct observe/owner/terminal/remainder; bootstrap/current;
  checkpoint/stall; and complete/failed outcome. No placeholder dictionary is
  accepted for a producer that Task 2 has not connected yet.
- Pending stages stay unique in contract order. Every nonnull legacy result slot,
  including `historical_owner_result`, uses the existing legacy validator plus
  the model's exact envelope check; the model does not duplicate that schema.
- A controlled fake provider consumes only the typed direct response, records
  effects, and returns strict observations. It proves exact scope/action echo,
  ordinary evaluation, null/mismatch zero-effect refusals, double fencing,
  post-fold partial progress, denial, suspension, transfer and fresh proposals.
- Caller/eval tests supplement the executable round trips by pinning that
  from-issue, AUTO, ship-issue and orchestration validate before decode, carry
  exact objects, act only on the returned closed stage and persist before report.
- `just agent-workflow-tests` and `just build` run once on the complete Task 2
  state. They verify source integration and managed build, not activation or the
  retained old-generation bridge.

## Delivery estimate and boundaries

Estimate: 22–28 product/test/caller files plus this three-file plan package and
the amended one-file design spec. The complete source diff is likely 350–525 KiB
before review fixes; `workflow-state.py`, its existing test, and the new
end-to-end test are the largest likely contributors and each must remain below
65,536 diff bytes. Task 1 is an independently reviewable pure-library gate of
roughly 65–105 KiB across four product/test paths. Task 2 is an atomic adoption
gate of roughly 275–415 KiB across the remaining runtime, report, caller and test
paths. These are forecasts, not fit evidence: each task and the final cumulative
range requires a complete actual producer package under unchanged limits.

The split follows D13: a reviewer can accept the pure unused model before any
wire changes, while no subset of Task 2 is independently shippable because a
mixed schema/report/caller generation would violate D9. The final delivery must
contain both accepted tasks and distinct final conformance and correctness
reviews; an accepted Task 1 is not a separately activated product.

## Task index

Task 1 — Build and publish the pure delivery model — `home/common/agent-skills/scripts/delivery_model/{__init__,_canonical,_objects,_wire,_reconcile}.py`, `home/common/agent-skills/tests/{_delivery_model_fixtures,test_delivery_model}.py`, `home/common/agent-skills/default.nix`, `justfile` — full — [task-1.md](2026-09-21-issue-151-delivery-reconciliation.tasks/task-1.md)

Task 2 — Atomically adopt schema 3 and delivery transports — delivery model, workflow state, artifact validation, production caller skills/evals, and tests — full — [task-2.md](2026-09-21-issue-151-delivery-reconciliation.tasks/task-2.md)

## Decisions

The plan implements D1–D13 as accepted. Planning added D14 because the current
runtime already supports schema 1→2: the new writer must compose that migration
with 2→3 in memory and preserve one atomic write rather than strand valid older
history or expose an intermediate schema. It added D15 to close the intermodule
model surface and the public checkpoint response instead of leaving caller-owned
reduction dictionaries or an open output envelope. Round-one review adds D16's
structural-versus-semantic boundary plus public response validator and D17's
explicit migration/read-only split. Round-two review adds D18's durable
post-rejection consumption/action rule, exact revocation subject, late-fact
history/current-effect split and persisted stall arithmetic. Round-three review
closes the count-3 stalled checkpoint response and restores strict bootstrap
requirements consumption for both custody kinds. Round four replaces only the
nested control owner observation with the custody union, preserving its existing
unavailable/event/dedup semantics and historical no-effect behavior. Round five
restores the exact six control maps and five direct additions after compaction.
The runtime-seam amendment adds D20 after the paused admission implementation
measured `workflow-state.py` at 62,664 U10 bytes from the fixed delivery base;
it changes structure only and preserves D1–D19 behavior and the atomic cutover.

Plan review provenance: an independent Sol/high review of head
`d1c9c47ea94daa8d4f97e127d72021f8e3896baf` reported 3 Blocking / 3 Should-fix /
0 Discussion in `/private/tmp/issue-151-plan-review-round1.md`; the root
Astra critical pass reported 3 Blocking / 2 Should-fix in
`/private/tmp/issue-151-root-plan-critical-round1.md`. All findings are accepted.
The corrected members bind PR/output evidence separately, supply complete pure
evaluation and migration context, add the actual raw response route, separate
structural/trust/ledger checks, make double fencing and stall/deadline scenarios
executable, and use temporary-index candidate inventories that include new files.

The independent Sol/high round-two review of corrected head
`a5e4250e9333f0fc4006f1814b5b0936278e678b` reported 4 Blocking / 2 Should-fix /
0 Discussion in `/private/tmp/issue-151-plan-review-round2.md`; root's Astra pass
reported 2 Blocking / 2 Should-fix in
`/private/tmp/issue-151-root-plan-critical-round2.md`. All residuals are accepted
and resolved by the D18 wire plus the focused executable-test repairs above.

The independent Sol/high round-three review of head
`e029d81081a81990bfe747f47365ddfebeab9e48` reported 2 Blocking / 2 Should-fix /
0 Discussion in `/private/tmp/issue-151-plan-review-round3.md`. Root verified all
four; the bounded corrections close the terminal stall/bootstrap wires and fix
the two executable model assertions without reopening prior dispositions.

The independent Sol/high round-four review of head
`c99759a3c493dc59c1db844078e30fad70af7b8e` reported 1 Blocking / 1 Should-fix
in `/private/tmp/issue-151-plan-review-round4.md`. Root verified both; this
correction closes the nested owner observation and qualifies ordinary checkpoint
language only.

The independent Sol/high round-five review of head
`b0aa4d76db40f1e09702d4f15ce552b0fa38ed08` reported 1 Blocking / 0 Should-fix
in `/private/tmp/issue-151-plan-review-round5.md`. Root verified it; exact control
map/direct key names and envelope-key negative fixtures are restored.

The D19 amendment follows the accepted root-controller proposal and independent
Sol/high critique: the pure reducer owns post-fold stage/scope correlation;
requests and effect-bearing responses carry exact proposed scope; handoff echo is
historical; finish remainder is custody-only; and ordinary authorization does
not acquire a preflight/prior-allow ceremony. Root's review of `e2b2cae` retained
those rules while requiring stage-independent fixtures, null-scope persistence,
slot-conflict refusal and explicit tuple-field/echo/provider-call coverage.

---
