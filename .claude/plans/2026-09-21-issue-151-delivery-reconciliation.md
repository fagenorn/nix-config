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

The accepted design's D1–D22, closed wire tables and test scenarios bind both
tasks without restatement here. They require one model/policy owner; exact
contract, scope, evidence and custody identities; two current-launch fences;
append-only history and durable one-shot evaluation consumption; independent
delivery postconditions; adjacent detached schema migration; finite
implementation/remainder custody and D21 recovery; D19 actual-scope
correlation; and D22's lexical private runtime/projection split. Structural
validation never proves freshness, authority or provider success.

Task 2 is one source-only schema-3/interface-2 cutover. It performs no
activation, live-ledger/forge mutation, historical-runtime publication or
mixed-generation operation. Tests use synthetic identities, temporary
HOME/ledgers and generated source/installed layouts. Every ordinary diff stays
at most 65,536 bytes; fixed bases, artifact caps, full coverage and tests remain
unchanged. Commits are signed with the Codex coauthor trailer.

## Test seams and delivery gates

- Model, workflow, artifact and caller tests cover every design scenario through
  public seams, including source/installed layouts, fake-provider calls, raw
  validation and byte-identical refusals. Task 2 runs `just
  agent-workflow-tests`, `just build` and the three skill validations without
  activation.
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
