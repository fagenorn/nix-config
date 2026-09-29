# Shared transaction history construction Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make all five transaction mutation families obtain complete documents
from the history module's authoritative event rules without changing behavior.

**Architecture:** Extract the current validating history walk and use its four
projections in both strict stored-document validation and a detached candidate
constructor. Keep event recipes, admission, lease judgments, locks and writes in
their existing owners; migrate the shared walk and all callers together.

**Tech stack:** Python standard library, `unittest`, existing `agent_tools`
modules, `just` and the repository's Nix build.

Specification: [approved design](../specs/2026-09-29-issue-230-history-projection-design.md).
Implementation baseline: `6d7a0b3a47d5a480e1540ce1931dd012f5f1ad0b`, including #229;
planning starts at `3c4abea` with no production changes.

## Global Constraints

- Keep `transaction-state/v5`, every public method and snapshot contract,
  event order/content/timestamps, refusal classes and precedence, and no-op
  behavior. Preserve the external-result capture introduced by #229.
- Construction and validation use exactly the same transition, parking,
  custody, and revision rules. Preserve all action, proof, recovery, envelope,
  pairing, terminal and fence checks in their existing order.
- Loading compares stored projections and rejects tampering; it never replaces
  them with the computed values or saves a repaired document.
- Constructing a candidate performs one existing full history walk. Do not
  construct through one fold and then call full validation for another walk.
  Existing admission validation of the stored prior remains necessary.
- Construction and the shared walk perform no filesystem, lock, clock, index
  or lease-authority access. The existing validator retains its index callback;
  lease liveness and all persistence remain store judgments.
- Keep transaction-lock then lease-lock order and their current acquisition
  points. Acquisition constructs a valid candidate, holds the leases, then saves
  state. Voluntary/quiesced and terminal release save state before clearing the
  previous fence under the lease lock. Reap and late result save only state;
  neither clears expired or successor lease records. Ordinary non-releasing
  append saves only state. Renewal without quiescence still appends nothing.
- No creation redesign, schema migration, new transaction module, public API,
  incremental caching, dependency, persistence coordinator or unrelated cleanup.
- Follow `docs/standards/agent-helpers.md`; existing package imports and shared
  canonical/storage helpers remain authoritative. Update affected docstrings to
  describe the final code precisely; do not copy plan prose blindly into source.
- Commit with signing enabled and `Co-Authored-By: Codex <noreply@openai.com>`.
- Read bounded source ranges; summarize test output and retain long logs outside
  the worktree. Pass artifact paths between workers rather than their contents.

## Test seams

- Public `TransactionStore` operations with temporary roots and fake clocks,
  documented state/lease bytes and `inspect_lease`, per D4.
- Returned snapshot, serialized document and fresh store load agree with
  independently authored projection and appended-event expectations, per D4.
- Existing asserted store sweep, source neutrality check, and source inspection
  of construction/call paths; no direct constructor/fold tests or helper mocks.

## Delivery estimate and boundaries

Estimate: four production/test files change. `transaction_history.py` owns the
walk, constructor and event-field recipes; `transaction_core.py` owns operation
admission and effects; `test_transaction_custody.py` owns mutation round trips;
`test_transaction_core.py` owns competing corruption refusals. No new production
file is expected. The task includes all five writers because shipping a second
construction path beside the old writers would leave the central invariant
unfinished. Test additions and moved validation code are the estimated largest
diff contributors; expect one reviewable slice, subject to actual review-package
measurement during execution.

Baseline supplied by the controller: 281 focused transaction tests passed;
`just build` passed; `just agent-workflow-tests` passed 1745 tests in 545.960s
with 3 skips. These are baseline results, not implementation evidence.

## Task index

Task 1 — Centralize complete history construction and migrate every writer — python/agent_tools/transaction_history.py, python/agent_tools/transaction_core.py, tests/test_transaction_custody.py, tests/test_transaction_core.py — full — [task-1.md](2026-09-29-issue-230-history-projection.tasks/task-1.md)

## Decisions

The specification's ledger is authoritative: D1 and D2 govern the shared walk
and constructor; D3 governs operation recipes and their ownership; D4 governs
verification. This plan introduces no additional non-obvious decision.

---
