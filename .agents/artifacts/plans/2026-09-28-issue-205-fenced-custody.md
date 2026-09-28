# Transaction Core Fenced Custody Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** ship slice 2/6 of the transaction core — a local lease authority with
epoch/term fencing, renewal as a core duty that writes no history, custody-fenced
writes, evidence and grant admissibility derived from the fence, custody quiesce,
reaping with a late authentic owner result kept beside the synthesized stop, and a
renewal/lapse sweep — so that, under a fake clock, a lapse advances the epoch and
voids snapshot evidence while an in-place renewal does neither
([#205](https://github.com/fagenorn/nix-config/issues/205), parent
[#123](https://github.com/fagenorn/nix-config/issues/123)).

**Architecture:** three standard-library-only library modules with no command-table
row and no caller (per D1): `agent_tools.transaction_storage` (slice 1's durable-file
primitives and the whole error hierarchy, moved), `agent_tools.transaction_custody`
(the lease authority under `<root>/leases/` and the pure admissibility fold) and
`agent_tools.transaction_core` (the public surface, `transaction-state/v2` validator
and store operations). Task 1 moves the primitives and injects the clock; Task 2
moves the schema to v2 with concurrency keys; Tasks 3–6 add custody, renewal and
fenced advances, evidence and grants, and reap/late results; Task 7 grows the sweep.

**Tech stack:** Python 3 standard library (`fcntl`, `json`, `secrets`, `hashlib`,
`dataclasses`, `contextlib`, `unittest`), `just`, Nix (`lib/agent-tools.nix` import
check, unchanged).

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-28-issue-205-fenced-custody-design.md`, D1–D31.
Slice 1: `.agents/artifacts/specs/2026-09-27-issue-204-transaction-core-skeleton-design.md`
and `python/agent_tools/transaction_core.py` at the base commit.

## Global Constraints

- Scope is exactly the spec's; its `## Out of scope` list binds (no receipts, write
  intent, proof plans, grant scopes/expiry, mechanism adapters, profiles, CLI, command
  row, Nix or host change, wiring into workflow-state/attempts/control).
- The three modules import only the standard library, `agent_tools.canonical` and each
  other in the direction core → custody → storage (never back); they never print, never
  log and never touch a path outside the store's `root`.
- `lib/agent-tools.nix` is not edited: its recursive walk already import-checks every
  module under `agent_tools`.
- Digest and strict-load knowledge come only from `agent_tools.canonical`
  (`docs/standards/agent-helpers.md` rule 4); no `sys.path`, `importlib` or `__file__`
  anywhere, tests included (rule 3).
- Every file the store writes is exactly
  `json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"`,
  replaced atomically with the slice-1 `atomic_write` primitive.
- The code of all three modules (comments and docstrings excluded) contains no word from
  the neutrality lists in `tests/test_transaction_core_sweep.py` — e.g. `tag`, `switch`,
  `merge`, `push`, `restart`, `git` in an identifier or message is a defect.
- Every refusal names the transaction id (or the lease key/path) and the rule that failed,
  and happens before any write to `state.json` or a lease record.
- Constants, exact: lease schema `transaction-lease/v1`; state schema
  `transaction-state/v2`; instance `lin_` + 32 lowercase hex (`secrets.token_hex(16)`);
  margin `min(ttl_ms, max(ttl_ms // 2, 60000))`; `PARKED_CUSTODY_WINDOW_MS = 900000`.
- Lock order is transaction lock then `<root>/leases.lock`, both non-blocking; fenced
  writes never take the lease lock (per D8, D25).
- Fixtures (provider names allowed) live only under `tests/`.
- Commits are signed (never `--no-gpg-sign`) and end with the two trailer lines the
  caller supplies.

## Test seams

- Seam 1 — `TransactionStore(root, clock=FakeClock())` under a `tempfile` root: returned
  `Transaction` snapshots, raised error classes, `inspect_lease` views, and the bytes of
  `state.json`, lease records and the documented layout. Tests may write those files and
  hold those locks directly.
- Seam 2 — the fixture executor `drive(root, shape, scenario) -> str`, compared through a
  fresh `TransactionStore(root).load(...)`.
- Seam 3 — `neutrality_findings(source)` over `inspect.getsource` of all three modules.
- No test calls or patches a `_`-prefixed name, and no test imports
  `transaction_storage`/`transaction_custody` except Task 1's re-export identity check and
  the neutrality test (per D23).

## Delivery estimate and boundaries

Estimates only: ~9 changed files — `transaction_core.py` (542 → ~950 lines),
`transaction_storage.py` (~200, mostly moved), `transaction_custody.py` (~300), new
`tests/test_transaction_custody.py` (~700), `tests/test_transaction_core.py` (+~60),
sweep support and sweep test (+~150), `justfile` (+1), `CLAUDE.md` (1 sentence).
Aggregate-growth risk sits in the custody test file and the v2 validator. Tasks 1–6 each
leave a working store; Task 7 adds only fixture and docs.

## Task index

Task 1 — Move storage primitives and errors; inject the lease-authority clock — `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_core.py`, `tests/test_transaction_core_sweep.py` — low-risk — [task-1.md](2026-09-28-issue-205-fenced-custody.tasks/task-1.md)

Task 2 — Schema v2: immutable concurrency keys, custody projection, v1 refused — `python/agent_tools/transaction_core.py`, `tests/test_transaction_core.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py` — full — [task-2.md](2026-09-28-issue-205-fenced-custody.tasks/task-2.md)

Task 3 — Lease authority, `acquire`/`release`/`inspect_lease`, the fenced check and custody validation — `python/agent_tools/transaction_custody.py`, `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_custody.py`, `tests/test_transaction_core_sweep.py`, `justfile` — full — [task-3.md](2026-09-28-issue-205-fenced-custody.tasks/task-3.md)

Task 4 — Renewal duty, custody quiesce, fenced `advance` and terminal release — `python/agent_tools/transaction_custody.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_custody.py`, `tests/test_transaction_core.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py` — full — [task-4.md](2026-09-28-issue-205-fenced-custody.tasks/task-4.md)

Task 5 — Evidence, intervals, grants and the lapse-versus-renewal demo — `python/agent_tools/transaction_custody.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_custody.py` — full — [task-5.md](2026-09-28-issue-205-fenced-custody.tasks/task-5.md)

Task 6 — Reap, synthesized stop and late owner-result intake — `python/agent_tools/transaction_core.py`, `tests/test_transaction_custody.py` — full — [task-6.md](2026-09-28-issue-205-fenced-custody.tasks/task-6.md)

Task 7 — Renewal and lapse sweep rows, voided-forms column, CLAUDE.md — `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`, `CLAUDE.md` — full — [task-7.md](2026-09-28-issue-205-fenced-custody.tasks/task-7.md)

## Decisions

The spec's `## Decision ledger` owns every decision. Tasks cite: D1, D3, D31 (Task 1);
D4, D9 (Task 2); D2, D5–D8, D10–D12, D21, D24, D25, D27, D30 (Task 3); D13, D14, D19,
D26, D27, D28 (Task 4); D10, D15, D16, D20, D27, D30 (Task 5); D17, D18, D27, D30
(Task 6); D22, D29 (Task 7). Planning added D27–D31.
