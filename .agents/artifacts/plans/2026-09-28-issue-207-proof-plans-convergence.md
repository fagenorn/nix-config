# Transaction Core Proof Plans and Convergence Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** ship slice 4/6 of the transaction core. Every transaction carries an immutable,
digest-addressed proof plan compiled at creation. The core collects obligations itself,
gates `published` and `proving` on the plan's units, and makes `settle_proof`, which judges
a single convergence cohort, the only way into `succeeded`. That judgment parks
`proof_rejected` or `proof_did_not_converge` and never rolls back
([#207](https://github.com/fagenorn/nix-config/issues/207), parent
[#123](https://github.com/fagenorn/nix-config/issues/123)).

**Architecture:** two new pure modules. `agent_tools.transaction_plan` holds the declaration
schema, compile, materialize and makespan. `agent_tools.transaction_proof` holds the proof
event rules, evaluation, the cohort fold, the gates, the view and the pure decision halves of
the three new store operations (per D1, D22). `transaction_history` moves to
`transaction-state/v4` and dispatches proof events and gates to `transaction_proof`.
`transaction_core` gains `create(..., proof=)`, `collect_obligation`, `start_cohort` and
`settle_proof`, which keep only locks, clock, call and write. The import direction becomes
core → history → proof → plan → invocation → custody → storage. Tasks 1–2 build the plan,
Tasks 3–4 the proof operations, Task 5 the lifecycle gates, and Tasks 6–7 the sweep.

**Tech stack:** Python 3 standard library (`dataclasses`, `json`, `copy`, `math`, `types`,
`unittest`), `agent_tools.canonical.telemetry_digest`, `just`, Nix (`lib/agent-tools.nix`
import check, unchanged).

Spec (the source of truth, read it whole):
`.agents/artifacts/specs/2026-09-28-issue-207-proof-plans-convergence-design.md`, D1–D29.
The code base is commit `dd9f40b` (slices 1–3 as merged; the base for every budget check).

## Global Constraints

- Scope is exactly the spec's. Its `## Out of scope` list binds: no recovery, receipts,
  `active_probe`, fresh budget, unit-membership refusal, observation deadlines, CLI,
  command-table row, Nix or host change, or #125 cutover.
- The seven modules import only the standard library, `agent_tools.canonical` and each other,
  in the direction core → history → proof → plan → invocation → custody → storage: a module
  imports only modules to its right. Only `transaction_core` and `transaction_custody` read a
  file, lock or clock.
- `lib/agent-tools.nix` is not edited; its recursive walk import-checks new modules (stage
  new files with `git add` before `just build`).
- Digest and strict-JSON knowledge come only from `agent_tools.canonical` and the storage
  codecs (`docs/standards/agent-helpers.md` rule 4). No `sys.path`, `importlib` or `__file__`
  anywhere, tests included (rule 3).
- Every file the store writes is exactly
  `json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"`,
  replaced atomically with `atomic_write`.
- The code of all seven modules (comments and docstrings excluded) contains no word from the
  neutrality lists in `tests/test_transaction_core_sweep.py` (e.g. `push`, `tag`, `deploy`,
  `merge`, `switch`, `git`).
- No lock is held while an observer runs; the core catches nothing an observer raises.
- Refusals are typed and closed: `ProofPlanRejected.reason` in `PLAN_REJECTION_REASONS`,
  raised before any lock or write; `ProofRefused.reason` in `PROOF_REFUSAL_REASONS`, raised
  before any write or call. An out-of-shape observation is `EffectResultInvalid` with nothing
  recorded (per D18). Every message names the transaction id (or, from `create`, the creation
  key) and the rule.
- Constants, exact (per D19): schema `transaction-state/v4`, plan schema
  `transaction-proof-plan/v1`, `MAX_COLLECTION_LATENCY_MS = 300_000`,
  `MAX_FRESHNESS_MS = 7_200_000`, `MAX_COHORT_ATTEMPTS = 3`, `COHORT_MARGIN_PERCENT = 20`,
  `COHORT_MARGIN_FLOOR_MS = 5_000`, `RUNNING_IDENTITY_FRESHNESS_MS = 600_000`,
  `DEFAULT_CONVERGENCE_WINDOW_MS = 1_800_000`, `MAX_CONVERGENCE_WINDOW_MS = 7_200_000`.
- The explicit empty declaration is `{"units": [], "obligations": [], "collectors": {}}`
  (per D2); `create` has no default for `proof`.
- Size caps (per D22, #205 D33): after every task, `transaction_core.py` is at most 55000
  bytes, and each file's cumulative `git diff -U10 dd9f40b` is under 65536 bytes.
- Fixtures (provider names allowed) live only under `tests/`.
- Commits are signed (never `--no-gpg-sign`) and end with the two trailer lines the caller
  supplies.

## Test seams

- Seam 1: `TransactionStore(root, clock=FakeClock())` under a `tempfile` root, with the
  invocation tests' fake effects and in-memory **fake observers**. The observable side is
  each observer's returned outcome and the clock it advances, never a call log (per D20).
  Tests read returned snapshots (`proof_plan`, `proof`, `evidence`, `actions`), raised error
  classes and `.reason`, directory listings and `state.json` bytes, and may hand-edit
  `state.json`. They also call `compile_proof`/`materialize_plan` through their
  `transaction_core` re-exports.
- Seam 2: the fixture executor `drive(root, shape, scenario, world=None) -> str`, compared
  through a fresh `TransactionStore(root).load(...)` and the passed world (per D14).
- Seam 3: `neutrality_findings(source)` over all seven modules.
- No test calls or patches a `_`-prefixed name. No test imports `transaction_plan`,
  `transaction_proof`, `transaction_history`, `transaction_invocation`,
  `transaction_custody` or `transaction_storage`, except for re-export identity checks and
  the neutrality test.

## Delivery estimate and boundaries

These are estimates only. About 15 files change: new `transaction_plan.py` (~350 lines),
`transaction_proof.py` (~600 lines), `transaction_core.py` (46.7 KB → ~54 KB),
`transaction_history.py` (+~60 lines), `transaction_custody.py` (+~3),
`transaction_storage.py` (+~20), new `tests/test_transaction_plan.py` (~30 KB) and
`tests/test_transaction_proof.py` (~50 KB) (per D23), `tests/test_transaction_core.py`,
`tests/test_transaction_custody.py`, `tests/test_transaction_invocation.py`,
`tests/test_transaction_core_sweep.py`, `tests/transaction_core_sweep_support.py`,
`tests/transaction_core_world.py`, `justfile` (+2) and `CLAUDE.md` (one sentence).

The growth risks are the core cap and the proof test file. Tasks 3, 4, 5 and 7 end with an
asserting budget step. Every task leaves the suite green: Task 2 passes the empty
declaration everywhere, and Task 5 moves every existing `succeeded` onto `settle_proof`.

## Task index

Task 1 — Plan vocabulary, compile, materialize and the cohort schedule — `python/agent_tools/transaction_plan.py`, `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_plan.py`, `tests/test_transaction_core_sweep.py`, `justfile` — full — [task-1.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-1.md)

Task 2 — Schema v4: the stored plan, `create(proof=)` and plan validation — `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_plan.py`, `tests/test_transaction_core.py`, `tests/test_transaction_custody.py`, `tests/test_transaction_invocation.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py` — full — [task-2.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-2.md)

Task 3 — `collect_obligation`, evaluation and the proof view — `python/agent_tools/transaction_proof.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_custody.py`, `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_proof.py`, `tests/test_transaction_core_sweep.py`, `justfile` — full — [task-3.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-3.md)

Task 4 — The cohort: `start_cohort`, `settle_proof` and the typed parkings — `python/agent_tools/transaction_proof.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_proof.py` — full — [task-4.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-4.md)

Task 5 — Lifecycle gates and `succeeded` only through `settle_proof` — `python/agent_tools/transaction_proof.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_proof.py`, `tests/test_transaction_core.py`, `tests/test_transaction_custody.py`, `tests/transaction_core_sweep_support.py` — full — [task-5.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-5.md)

Task 6 — Sweep executor drives proof through the core — `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py` — full — [task-6.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-6.md)

Task 7 — Five new sweep rows, `slow_collection` and CLAUDE.md — `tests/transaction_core_world.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`, `CLAUDE.md` — full — [task-7.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-7.md)

## Decisions

The spec's `## Decision ledger` owns every decision. Tasks cite D1, D2, D4, D5, D9, D19,
D26 and D28 (Task 1); D2, D3, D13, D23 and D24 (Task 2); D5–D8, D13, D18, D20, D22,
D25 and D27 (Task 3); D9–D11, D16, D21, D22, D27 and D28 (Task 4); D10, D12, D27 (Task 5);
D14, D15 and D29 (Task 6); and D14, D16, D17 and D29 (Task 7). Planning added D22–D29; D23
amends D20.
