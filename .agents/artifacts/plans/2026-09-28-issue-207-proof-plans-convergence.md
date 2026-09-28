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

**Tech stack:** Python 3 standard library, `agent_tools.canonical.telemetry_digest`, `just`,
Nix (`lib/agent-tools.nix` import check, unchanged).

Spec (the source of truth, read it whole):
`.agents/artifacts/specs/2026-09-28-issue-207-proof-plans-convergence-design.md`, D1–D34.
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
  raised before any lock or write; `ProofRefused.reason` in `PROOF_REFUSAL_REASONS`, at
  admission before any write or call, or after the call at `collect_obligation`'s second
  hold. That refusal and an out-of-shape observation (`EffectResultInvalid`) record nothing
  from the call; an interval's `interval_opened` stays (per D18, D33). Every message names
  the transaction id (or, from `create`, the creation key) and the rule.
- Constants, exact (per D19): schema `transaction-state/v4`, plan schema
  `transaction-proof-plan/v1`, `MAX_COLLECTION_LATENCY_MS = 300_000`,
  `MAX_FRESHNESS_MS = 7_200_000`, `MAX_COHORT_ATTEMPTS = 3`, `COHORT_MARGIN_PERCENT = 20`,
  `COHORT_MARGIN_FLOOR_MS = 5_000`, `RUNNING_IDENTITY_FRESHNESS_MS = 600_000`,
  `DEFAULT_CONVERGENCE_WINDOW_MS = 1_800_000`, `MAX_CONVERGENCE_WINDOW_MS = 7_200_000`.
- The explicit empty declaration is `{"units": [], "obligations": [], "collectors": {}}`
  (per D2); `create` has no default for `proof`.
- Size caps (per D22, #205 D33): after every task, `transaction_core.py` is at most 55000
  bytes, and each file's cumulative `git diff -U10 dd9f40b` is under 65536 bytes.
  Tasks 3, 4, 5 and 7 end by running this review-budget block with their `FILES`; a
  non-zero exit means the task is not done, so move judgment out of the core (per D22):

```bash
base=dd9f40b; fail=0
for f in $FILES; do
  n=$(git diff -U10 "$base" HEAD -- "$f" | wc -c); printf '%s %s\n' "$n" "$f"
  [ "$n" -lt 65536 ] || fail=1
done
[ "$(wc -c < python/agent_tools/transaction_core.py)" -le 55000 ] || fail=1
test "$fail" = 0
```
- Fixtures (provider names allowed) live only under `tests/`.
- Commits are signed (never `--no-gpg-sign`) and end with the two trailer lines the caller
  supplies.

## Test seams

- Seam 1: `TransactionStore(root, clock=FakeClock())` under a `tempfile` root, with fake
  effects and in-memory **fake observers**, observed by returned outcome and clock, never a
  call log (per D20). Tests read snapshots, error classes and `.reason`, listings and
  `state.json` bytes, may hand-edit `state.json`, and reach `compile_proof`/
  `materialize_plan` through the `transaction_core` re-exports.
- Seam 2: the fixture executor `drive(root, shape, scenario, world=None) -> str`, compared
  through a fresh `TransactionStore(root).load(...)` and the passed world (per D14).
- Seam 3: `neutrality_findings(source)` over all seven modules.
- The slice unit command (Tasks 3–5): `PYTHONPATH=python python3 -m unittest
  tests/test_transaction_{proof,plan,core,custody,invocation,core_sweep}.py 2>&1 | tail -3`.
- No test calls or patches a `_`-prefixed name. No test imports `transaction_plan`,
  `transaction_proof`, `transaction_history`, `transaction_invocation`,
  `transaction_custody` or `transaction_storage`, except for re-export identity checks and
  the neutrality test.

## Delivery estimate and boundaries

Estimates only: about 15 files, chiefly new `transaction_plan.py` (~350 lines) and
`transaction_proof.py` (~600 lines), `transaction_core.py` (46.7 KB → ~54 KB), and the new
test files `test_transaction_plan.py` (~30 KB) and `test_transaction_proof.py` (~50 KB, per
D23). The growth risks are the core cap and the proof test file. Every task leaves the suite
green: Task 2 passes the empty declaration everywhere, and Task 5 moves every existing
`succeeded` onto `settle_proof`.

## Task index

Task 1 — Plan vocabulary, compile, materialize and the cohort schedule — `python/agent_tools/transaction_plan.py`, `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_plan.py`, `tests/test_transaction_core_sweep.py`, `justfile` — full — [task-1.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-1.md)

Task 2 — Schema v4: the stored plan, `create(proof=)` and plan validation — `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `python/agent_tools/transaction_storage.py`, `tests/test_transaction_plan.py`, `tests/test_transaction_core.py`, `tests/test_transaction_custody.py`, `tests/test_transaction_invocation.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py` — full — [task-2.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-2.md)

Task 3 — `collect_obligation`, evaluation and the proof view — `python/agent_tools/transaction_proof.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_custody.py`, `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_proof.py`, `tests/test_transaction_core_sweep.py`, `justfile` — full — [task-3.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-3.md)

Task 4 — The cohort: `start_cohort`, `settle_proof` and the typed parkings — `python/agent_tools/transaction_proof.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_proof.py` — full — [task-4.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-4.md)

Task 5 — Lifecycle gates and `succeeded` only through `settle_proof` — `python/agent_tools/transaction_proof.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_proof.py`, `tests/test_transaction_core.py`, `tests/test_transaction_custody.py`, `tests/transaction_core_sweep_support.py` — full — [task-5.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-5.md)

Task 6 — Sweep executor drives proof through the core — `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py` — full — [task-6.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-6.md)

Task 7 — Five new sweep rows, `slow_collection` and CLAUDE.md — `tests/transaction_core_world.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`, `CLAUDE.md` — full — [task-7.md](2026-09-28-issue-207-proof-plans-convergence.tasks/task-7.md)

## Decisions

The spec's `## Decision ledger` owns every decision; each task ends with the rows it cites.
Planning added D22–D29 and the standards review D30–D34; D23 amends D20, D30 amends D10's
seal case and D33 amends D18.

## Standards review provenance

Reviewer of record: `Claude fallback` (isolated, read-only) at base
`488e95f963352eed1cb1ca9647b0553ce8813feb`. Fallback reason: the Codex run's JSONL lacked the
runtime model/effort selection event, so it failed metadata validation; its findings were
verified against the worktree and folded in as supplementary input. Dispositions: 8 accepted
(D30–D34, plus Task 2's docstrings, guard grep and `.create(` reference, and Task 4's
re-collecting cohort test), 0 rejected, 1 deferred (an explicit gated-edge table for Task 5:
low confidence and speculative, since `gate_violation` already names its three gated edges).
