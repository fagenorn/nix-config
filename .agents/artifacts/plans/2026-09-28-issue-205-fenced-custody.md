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

**Architecture:** four standard-library-only library modules with no command-table
row and no caller (per D1, D33): `agent_tools.transaction_storage` (slice 1's
durable-file primitives and the whole error hierarchy, moved),
`agent_tools.transaction_custody` (the lease authority under `<root>/leases/` and the
pure admissibility fold), `agent_tools.transaction_history` (the pure
`transaction-state/v2` document model: vocabularies, `Custody`/`Transaction`, the
validator and the snapshot fold, from Task 6) and `agent_tools.transaction_core` (the
public surface and the store operations). Task 1 moves the primitives and injects the
clock; Task 2 moves the schema to v2 with concurrency keys; Tasks 3–5 add custody,
renewal and fenced advances, evidence and grants; Task 6 extracts the document model;
Task 7 adds reap and late results; Task 8 grows the sweep.

**Tech stack:** Python 3 standard library (`fcntl`, `json`, `secrets`, `hashlib`,
`dataclasses`, `contextlib`, `unittest`), `just`, Nix (`lib/agent-tools.nix` import
check, unchanged).

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-28-issue-205-fenced-custody-design.md`, D1–D33.
Slice 1: `.agents/artifacts/specs/2026-09-27-issue-204-transaction-core-skeleton-design.md`
and `python/agent_tools/transaction_core.py` at the base commit.

## Global Constraints

- Scope is exactly the spec's; its `## Out of scope` list binds (no receipts, write
  intent, proof plans, grant scopes/expiry, mechanism adapters, profiles, CLI, command
  row, Nix or host change, wiring into workflow-state/attempts/control).
- The four modules import only the standard library, `agent_tools.canonical` and each
  other in the direction core → history → custody → storage (a module imports only
  those to its right, never back); `transaction_history` reads no file, lock or clock;
  none of them prints, logs or touches a path outside the store's `root`.
- `lib/agent-tools.nix` is not edited: its recursive walk already import-checks every
  module under `agent_tools`.
- Digest and strict-load knowledge come only from `agent_tools.canonical`
  (`docs/standards/agent-helpers.md` rule 4); no `sys.path`, `importlib` or `__file__`
  anywhere, tests included (rule 3).
- Every file the store writes is exactly
  `json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"`,
  replaced atomically with the slice-1 `atomic_write` primitive.
- The code of all four modules (comments and docstrings excluded) contains no word from
  the neutrality lists in `tests/test_transaction_core_sweep.py` — e.g. `tag`, `switch`,
  `merge`, `push`, `restart`, `git` in an identifier or message is a defect.
- Every refusal names the transaction id (or the lease key/path) and the rule that failed,
  and happens before any write to `state.json` or a lease record.
- Constants, exact: lease schema `transaction-lease/v1`; state schema
  `transaction-state/v2`; instance `lin_` + 32 lowercase hex (`secrets.token_hex(16)`);
  margin `min(ttl_ms, max(ttl_ms // 2, 60000))`; `PARKED_CUSTODY_WINDOW_MS = 900000`.
- Lock order is transaction lock then `<root>/leases.lock`, both non-blocking. The fenced
  check, and fenced writes that touch only `state.json`, never take the lease lock;
  operations that write lease records take it after the transaction lock (per D8, D25).
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
- Seam 3 — `neutrality_findings(source)` over `inspect.getsource` of all four modules
  (`NEUTRAL_MODULES` gains `transaction_history` in Task 6).
- No test calls or patches a `_`-prefixed name, and no test imports
  `transaction_storage`/`transaction_custody`/`transaction_history` except the re-export
  identity checks (Task 1's, Task 6's) and the neutrality test (per D23).

## Delivery estimate and boundaries

Estimates only: ~10 changed files — `transaction_core.py` (542 at base; 1053 after
Task 5; ~590 after Task 6; ~650 after Task 7), new `transaction_history.py` (~420 after
Task 6; ~490 after Task 7), `transaction_storage.py` (~200, mostly moved),
`transaction_custody.py` (~300), new `tests/test_transaction_custody.py` (~800 after
Task 7), `tests/test_transaction_core.py` (+~70), sweep support and sweep test (+~150),
`justfile` (+1), `CLAUDE.md` (1 sentence).

Review-package boundary (per D33): the whole-branch package caps each member's
cumulative `git diff -U10` from the base at 65536 bytes. After Task 5 the core's diff
was 65625 bytes. A dry run of Task 6's move puts it at ~49000 bytes and the new module
at ~24000; Task 7 is estimated to bring them to ~54000 and ~29000 and the custody test
file to ~43000. Tasks 6 and 7 each end with a budget step that measures every touched
Python file against a ≤ 55000 cap (≤ 50000 for the core after Task 6).

Each task leaves the suite green, with one known gap: between Tasks 3 and 4 an advance
into a terminal while custody is held raises `StateInvalid` (the validator forbids open
custody after a terminal) until Task 4's terminal release lands; no test reaches it.
Task 6 changes no behavior; Task 8 adds only fixture and docs.

## Task index

Task 1 — Move storage primitives and errors; inject the lease-authority clock — `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_core.py`, `tests/test_transaction_core_sweep.py` — low-risk — [task-1.md](2026-09-28-issue-205-fenced-custody.tasks/task-1.md)

Task 2 — Schema v2: immutable concurrency keys, custody projection, v1 refused — `python/agent_tools/transaction_core.py`, `python/agent_tools/transaction_storage.py`, `tests/test_transaction_core.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py` — full — [task-2.md](2026-09-28-issue-205-fenced-custody.tasks/task-2.md)

Task 3 — Lease authority, `acquire`/`release`/`inspect_lease`, the fenced check and custody validation — `python/agent_tools/transaction_custody.py`, `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_custody.py`, `tests/test_transaction_core_sweep.py`, `justfile` — full — [task-3.md](2026-09-28-issue-205-fenced-custody.tasks/task-3.md)

Task 4 — Renewal duty, custody quiesce, fenced `advance` and terminal release — `python/agent_tools/transaction_custody.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_custody.py`, `tests/test_transaction_core.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py` — full — [task-4.md](2026-09-28-issue-205-fenced-custody.tasks/task-4.md)

Task 5 — Evidence, intervals, grants and the lapse-versus-renewal demo — `python/agent_tools/transaction_custody.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_custody.py` — full — [task-5.md](2026-09-28-issue-205-fenced-custody.tasks/task-5.md)

Task 6 — Extract the transaction-state document model into `transaction_history` — `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_core.py`, `tests/test_transaction_core_sweep.py` — full — [task-6.md](2026-09-28-issue-205-fenced-custody.tasks/task-6.md)

Task 7 — Reap, synthesized stop and late owner-result intake — `python/agent_tools/transaction_core.py`, `python/agent_tools/transaction_history.py`, `tests/test_transaction_custody.py` — full — [task-7.md](2026-09-28-issue-205-fenced-custody.tasks/task-7.md)

Task 8 — Renewal and lapse sweep rows, voided-forms column, CLAUDE.md — `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`, `CLAUDE.md` — full — [task-8.md](2026-09-28-issue-205-fenced-custody.tasks/task-8.md)

## Decisions

The spec's `## Decision ledger` owns every decision. Tasks cite: D1, D3, D31, D32 (Task 1);
D4, D9, D32 (Task 2); D2, D5–D8, D10–D12, D21, D24, D25, D27, D30 (Task 3); D13, D14, D19,
D26, D27, D28 (Task 4); D10, D15, D16, D20, D27, D30 (Task 5); D1, D23, D33 (Task 6);
D17, D18, D27, D30, D33 (Task 7); D22, D29, D33 (Task 8). Planning added D27–D31; the
standards review added D32; the execution back-up added D33.

---

## Standards review provenance

- Reviewer: Claude fallback (isolated, read-only). Codex ran, but its JSONL carried no
  runtime-selection event naming the model and effort, so its result failed metadata
  validation and one native fallback took the same packet.
- Base SHA: 66ccba5844eab2af9c68962c54a28f874585ee80.
- Counts: 7 accepted (SF1–SF6, DI3), 1 rejected (DI1: stricter `owner_result`
  cross-checks beyond D30), 1 deferred (DI2: test-structure duplication, left to
  execution). SF1's fail-loud unknown event type and SF6's clock upper bound are recorded
  as D32; the rest are routine corrections: rule-specific validator cases, a grant issued
  before renewal, stale-epoch writes after reacquisition, scheduled docstring rewrites,
  the lease-lock wording and the Task 3→4 gap note.
