# Transaction Core Administrative Protocol Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** ship slice 3/6 of the transaction core — `inspect_action` and `invoke_action`,
which persist a write intent before every external call, refuse a retry that no fresh
inspection precedes, record success without calling again when an inspection reads
`satisfied`, and bound automatic retries to 1 + 2 within 15 minutes, all folded from the
transaction's own history under `transaction-state/v3`
([#206](https://github.com/fagenorn/nix-config/issues/206), parent
[#123](https://github.com/fagenorn/nix-config/issues/123)).

**Architecture:** a new pure module `agent_tools.transaction_invocation` holds the
vocabularies, retry constants, `action_id`, effect-result checks, the action fold, the
admission rules and the per-action view (per D1). `transaction_history` dispatches the
four new event types to it and adds `Transaction.actions`; `transaction_core` gains the
two store operations, the quiesce exception and the terminal refusal (per D3, D9). Import
direction becomes core → history → invocation → custody → storage, with the shared
codecs and the two new errors in storage (per D15). Task 1 lays the vocabulary; Tasks
2–4 build the protocol; Task 5 ties it to custody and lifecycle; Task 6 grows the sweep.

**Tech stack:** Python 3 standard library (`dataclasses`, `json`, `copy`, `types`,
`unittest`), `agent_tools.canonical.telemetry_digest`, `just`, Nix (`lib/agent-tools.nix`
import check, unchanged).

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-28-issue-206-administrative-protocol-design.md`, D1–D18.
Slices 1–2 code at the base commit `ce33847bd60d4dc40a8a241d9f35b2bbdc9aaae1`.

## Global Constraints

- Scope is exactly the spec's; its `## Out of scope` list binds (no authorized extra
  attempt, profiles, backoff, adapter `describe`, proof plans, recovery, receipts, CLI,
  command-table row, Nix or host change, #125 cutover).
- The five modules import only the standard library, `agent_tools.canonical` and each
  other, in the direction core → history → invocation → custody → storage (a module
  imports only those to its right). `transaction_invocation` and `transaction_history`
  read no file, lock or clock.
- `lib/agent-tools.nix` is not edited; its recursive walk import-checks the new module.
- Digest and strict-JSON knowledge come only from `agent_tools.canonical` and the storage
  codecs (`docs/standards/agent-helpers.md` rule 4); no `sys.path`, `importlib` or
  `__file__` anywhere, tests included (rule 3).
- Every file the store writes is exactly
  `json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"`,
  replaced atomically with `atomic_write`.
- The code of all five modules (comments and docstrings excluded) contains no word from
  the neutrality lists in `tests/test_transaction_core_sweep.py` (e.g. `push`, `tag`,
  `deploy`, `git`, `switch`).
- No lock is held while an effect runs (per D3); the core catches nothing an effect raises.
- Every refusal names the transaction id and the rule, and happens before any write and,
  for `InvocationRefused`, before any effect call (per D7).
- Constants, exact: schema `transaction-state/v3`; `MAX_ATTEMPTS = 3`;
  `RETRY_WINDOW_MS = 900_000`; action id `act_` + 32 lowercase hex.
- Size caps (per #205 D33): after every task, `transaction_core.py` ≤ 55000 bytes and each
  file's cumulative `git diff -U10` from the base commit < 65536 bytes.
- Fixtures (provider names allowed) live only under `tests/`.
- Commits are signed (never `--no-gpg-sign`) and end with the two trailer lines the caller
  supplies.

## Test seams

- Seam 1 — `TransactionStore(root, clock=FakeClock())` under a `tempfile` root with fake
  effects: in-memory worlds whose applied effects and invoke counts are the external
  side's observable state (per D13). Tests read returned snapshots, raised error classes
  and `.reason`, `inspect_lease` views, and the bytes of `state.json`; they may hand-edit
  `state.json`. An effect's `reference` may encode what the request carried.
- Seam 2 — the fixture executor `drive(root, shape, scenario, world=None) -> str`, compared
  through a fresh `TransactionStore(root).load(...)` and the passed world (per D18).
- Seam 3 — `neutrality_findings(source)` over all five modules.
- No test calls or patches a `_`-prefixed name; no test imports `transaction_invocation`,
  `transaction_history`, `transaction_custody` or `transaction_storage` except re-export
  identity checks and the neutrality test.

## Delivery estimate and boundaries

Estimates only: 11 changed files — new `transaction_invocation.py` (~300 lines),
`transaction_core.py` (651 → ~800 lines, ~44000 bytes), `transaction_history.py` (+~40
lines net after moving the codecs), `transaction_storage.py` (+~50), new
`tests/test_transaction_invocation.py` (~900 lines, ~45000 bytes), `tests/test_transaction_core.py`
(2 lines), `tests/test_transaction_core_sweep.py` (+~40), `tests/transaction_core_world.py`
(+~15), `tests/transaction_core_sweep_support.py` (+~90), `justfile` (+1), `CLAUDE.md` (one
sentence). Growth risk: the new test file; Tasks 3, 4 and 6 end with an asserting budget
step. Every task leaves the suite green; interim gaps are named in the task that closes
them (Task 3 refuses interrupted attempts as `not_retryable` until Task 4).

## Task index

Task 1 — Invocation vocabulary, `action_id`, errors and moved codecs — `python/agent_tools/transaction_invocation.py`, `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_invocation.py`, `tests/test_transaction_core_sweep.py`, `justfile` — full — [task-1.md](2026-09-28-issue-206-administrative-protocol.tasks/task-1.md)

Task 2 — Schema v3, declared/inspected events, `Transaction.actions` and `inspect_action` — `python/agent_tools/transaction_invocation.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_invocation.py`, `tests/test_transaction_core.py` — full — [task-2.md](2026-09-28-issue-206-administrative-protocol.tasks/task-2.md)

Task 3 — `invoke_action`: intent, return, post-inspection and the retry budget — `python/agent_tools/transaction_invocation.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_invocation.py` — full — [task-3.md](2026-09-28-issue-206-administrative-protocol.tasks/task-3.md)

Task 4 — Crash seam: interrupted attempts, `attempt_in_flight` and the second-write re-check — `python/agent_tools/transaction_invocation.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_invocation.py` — full — [task-4.md](2026-09-28-issue-206-administrative-protocol.tasks/task-4.md)

Task 5 — Quiesce exception, terminal refusal and refusal precedence — `python/agent_tools/transaction_invocation.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_invocation.py` — full — [task-5.md](2026-09-28-issue-206-administrative-protocol.tasks/task-5.md)

Task 6 — Sweep rows `throttled_retry` and `resume_after_crash`, attempts column, CLAUDE.md — `tests/transaction_core_world.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`, `CLAUDE.md` — full — [task-6.md](2026-09-28-issue-206-administrative-protocol.tasks/task-6.md)

## Decisions

The spec's `## Decision ledger` owns every decision. Tasks cite: D1, D4, D7, D11, D15
(Task 1); D2, D3, D5, D8, D11, D13, D17 (Task 2); D3, D5–D8, D10, D11, D17 (Task 3); D3,
D6, D14, D16 (Task 4); D7, D9 (Task 5); D12, D18 (Task 6). Planning added D15–D18.

---
