# Delivery Reconciliation Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one
> implementer per task, reviewed between tasks.

**Goal:** Add one canonical delivery model and atomically move lifecycle state,
reports, and production callers to truthful delivery reconciliation with finite
remainder custody.

**Architecture:** Task 1 publishes an import-safe pure model for delivery
validation, identity, scope matching and reduction. Task 2 adopts that accepted
seam in one schema-3/interface-2 source cutover with all reports, callers and
public executable tests. Task 1 is preparatory; the two tasks form one delivery.

**Tech stack:** Python 3, JSON, Nix/Home Manager, workflow skills/evals,
`unittest`, Git and repository `just` commands.

## Global Constraints

The accepted design's D1–D22 and canonical wire appendix bind both tasks. In
particular:

- **D1–D2:** One immutable `delivery-contract/v1` and append-only intent, authority,
  reevaluation, consumption, selection and delivery facts are ledger truth.
  Digests prove identity, never authority. Exact scope matching includes every
  principal/action/effect/target/data/audience/risk/spend member and only the
  design's slot/literal and spend narrowings; null is never a wildcard.
- **D3/D18:** The exact current custody launch is fenced immediately before every effect
  and again before its observation. Stale/malformed launch, wrong stage/slot or
  contract mismatch causes zero external effect and byte-identical ledger.
  Post-rejection evaluation uses one durably persisted D18 consumption; replay,
  transfer and crash cannot mint another use. Current intent and new rejection
  rules still apply.
- **D4/D7:** Delivery, merge, tracker closure and cleanup are independent. Evidence binds
  the immutable reviewed subject, all acceptance/review/test categories and the
  declared repository/PR/worktree/branch identities. Exact positive probes are
  required; absence and digest spelling do not imply success or authority.
- **D5–D6/D21:** Attempts and remainders have disjoint finite identities. Resume preserves its
  ordinal/deadline. Remainder 2 requires D21's terminal failure, successful
  effect absence and valid newer recovery basis; unresolved denial/unknown
  parks, replay is idempotent and no remainder 3 exists. Suspension persists
  0/1/2/3 and the fourth unchanged suspension stalls; progress resets it.
- **D8–D9/D14/D17:** Schema 1→2→3 migration is adjacent, detached and one-write. It preserves
  attempts, outcomes, result bytes/details and creates no contract, authority,
  fact or success. Read-only current-launch validates legacy state without
  upgrade/write. Schema 3, interface 2, v2 reports and all callers cut over in
  one Task-2 commit; no live v1 effect path or mixed generation is accepted.
- **D13/D20/D22:** The model exposes exactly its eight interface-1 names. Private model leaves
  own canonical/object/wire/reconciliation policy once. Private
  `workflow_delivery.py` exposes interface 1 plus `DeliveryRuntime`; adjacent
  `workflow_delivery_wire.py` owns pure projection and interface-2
  owner/worktree grammar. Workflow-state retains CLI, custody orchestration,
  locks, one atomic write and effects. Lexical source/installed loading fails
  before decode/mutation; no callbacks, registries, fallback, `sys.path` edits,
  policy copies or model-private calls.
- **D19:** Requested scope is an independent actual invocation tuple correlated by the
  model to the post-fold ready stage. Null may persist facts/custody but permits
  no effect/evaluation; wrong scope refuses; uncovered scope human-gates;
  covered ordinary scope may run native evaluation without prior allow.
  Effect-bearing output echoes the tuple; transfer/resume needs a fresh one.
- **D16:** Structural model/artifact checks do not prove ledger freshness or source/host
  authenticity. Workflow-state checks freshness under lock; existing trusted
  adapters supply normalized source facts; native boundaries decide effects.
  All raw workflow responses validate before caller decode.
- **D10–D12:** This source delivery does not activate schema 3, mutate the live issue-151
  ledger, install an ad hoc bridge or commit historical runtimes. Root-only
  operational evidence covers the retained old-generation completion bridge.
  Product tests use synthetic identities, temporary HOME/ledgers and generated
  source/installed layouts only.
- Every ordinary file diff remains at most 65,536 bytes. Fixed bases, artifact
  caps, complete path/line coverage and all product tests remain unchanged.
  Commits are signed with `Co-Authored-By: Codex <noreply@openai.com>`.

## Test seams and delivery gates

- Pure model tests use public functions and explicit relative-import fixture
  builders. They cover canonical bytes/digests, closed objects, selected-slot
  narrowing, category evidence, graph ordering, D18 consumption, D19 actual
  scope, all cleanup/record subjects and the complete response union.
- Workflow tests execute init, control, direct, current, checkpoint and finish
  against temporary ledgers in source and generated installed layouts. A fake
  provider records typed calls; raw validation, exact echo and both launch
  fences precede effect/observation. Negative cases prove zero calls and
  byte-identical state.
- Artifact tests validate raw v2 handoff/checkpoint/summary/workflow-response
  bytes and compose legacy-result validation. Caller/eval tests pin validation
  before decode and exact object propagation. `just agent-workflow-tests`,
  `just build`, and the three skill validations run on the complete Task 2
  candidate; they do not activate it.
- Each task/final delivery requires raw producer validation before decode,
  fresh checker equality, complete fixed-range coverage and all four metrics
  under unchanged policy. Task members retain exact commands/roles.

## Task index

Task 1 — Build and publish the pure delivery model — package, fixtures/tests, publication and test registration — full — [task-1.md](2026-09-21-issue-151-delivery-reconciliation.tasks/task-1.md)

Task 2 — Atomically adopt schema 3 and delivery transports — runtime, state, artifact boundary, production callers/evals and tests — full — [task-2.md](2026-09-21-issue-151-delivery-reconciliation.tasks/task-2.md)

## Decisions and review provenance

The design ledger is authoritative for D1–D22. Independent Sol/high plan rounds
and root Astra critical passes resolved every finding before implementation;
their reports and the D19–D22 scoped reviews remain retained evidence, never
runtime input.

---
