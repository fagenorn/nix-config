# Transaction Core Skeleton Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** ship slice 1/6 of the transaction core — a persisted, closed-schema,
lock-guarded transaction store with `rel_` + UUIDv7 identity, creation-key dedup and a
closed lifecycle whose terminals cannot be forged — plus an asserted sweep harness and a
neutrality check that fail when the core regresses
([#204](https://github.com/fagenorn/nix-config/issues/204), parent
[#123](https://github.com/fagenorn/nix-config/issues/123)).

**Architecture:** one standard-library-only library module,
`python/agent_tools/transaction_core.py`, with no command-table row and no caller (per D1).
Task 1 builds its vocabulary, identity, validator, `create` and `load`; Task 2 adds
`advance`. The prototype's world and four shapes are ported into `tests/` as fixtures
driven by a test-only executor over the public store API (Task 3), and a test-side
tokenizer checks the shipped module stays neutral (Task 4).

**Tech stack:** Python 3 standard library (`fcntl`, `json`, `secrets`, `uuid`,
`dataclasses`, `tokenize`, `ast`, `unittest`), `just`, Nix (`lib/agent-tools.nix`
import check, unchanged).

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-27-issue-204-transaction-core-skeleton-design.md`,
D1–D17. Prototype: `git show dc98ba9:prototype-release-transactions/<file>.py`.

## Global Constraints

- Scope is exactly the spec's; its `## Out of scope` list binds (no leases, retry,
  adapters in the core, proof, recovery mechanics, authorization, CLI, command row,
  non-success scenarios, migrations).
- `python/agent_tools/transaction_core.py` imports only the standard library and
  `agent_tools.canonical`; it never prints, never logs, and never touches a path outside
  the store's `root` (per D2).
- `lib/agent-tools.nix` is not edited: its recursive `listFilesRecursive` walk already
  import-checks every module under `agent_tools` (per D1).
- Digest and strict-load knowledge come only from `agent_tools.canonical`
  (`telemetry_digest`, `reject_duplicate_keys`, `reject_nonfinite_literal`) —
  `docs/standards/agent-helpers.md` rule 4.
- No `sys.path` edits, `importlib`, or `__file__` lookups anywhere, tests included —
  agent-helpers rule 3.
- On-disk serialization of every file the store writes is exactly
  `json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"`.
- The shipped module's code (comments and docstrings excluded) contains no word from the
  three D11 lists; Task 4's test enforces it, but Tasks 1–2 must already honor it — an
  error message or identifier saying e.g. `merge`, `push`, `tag`, `switch` or `git` is a
  defect.
- Every error message names the transaction id or path and the rule that failed.
- Fixtures (provider names allowed) live only under `tests/`, never under `python/`
  (per D6, D14).
- Commits are signed (never pass `--no-gpg-sign`) and end with the two trailer lines the
  caller supplies.

## Test seams

- Seam 1 — `TransactionStore` under a `tempfile.TemporaryDirectory` root: returned
  `Transaction` snapshots, raised error classes, and the bytes and listings of the
  documented layout (`creation.lock`, `creation-keys/<sha256>.json`, `<id>/lock`,
  `<id>/state.json`). Tests may write those files and hold those locks directly.
- Seam 2 — the fixture executor `drive(store, shape, scenario) -> str` against a real
  store, compared through a fresh `TransactionStore(root).load(...)`.
- Seam 3 — `neutrality_findings(source: str)` over `inspect.getsource(transaction_core)`.
- No test calls or patches a private (`_`-prefixed) name of `transaction_core`.

## Delivery estimate and boundaries

Estimates only: ~8 changed files — the module (~350–450 lines), two test files
(~350 and ~150 lines), three fixture files (~210, ~470, ~120 lines, mostly the
verbatim port), `justfile` (+2 lines), `CLAUDE.md` (+1 sentence). Aggregate-growth risk
sits in the ported shapes fixture; it is authored data and is not trimmed. The slice is
one deliverable: Tasks 1–2 ship a usable store on their own, Tasks 3–4 only add tests.

## Task index

Task 1 — Store vocabulary, identity, validator, `create` and `load` — `python/agent_tools/transaction_core.py`, `tests/test_transaction_core.py`, `justfile` — full — [task-1.md](2026-09-27-issue-204-transaction-core-skeleton.tasks/task-1.md)

Task 2 — Lifecycle `advance` with lock, terminal and unknown-state guards — `python/agent_tools/transaction_core.py`, `tests/test_transaction_core.py` — full — [task-2.md](2026-09-27-issue-204-transaction-core-skeleton.tasks/task-2.md)

Task 3 — Ported world/shapes fixtures, fixture executor and asserted `success` sweep row — `tests/transaction_core_world.py`, `tests/transaction_core_shapes.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`, `justfile` — full — [task-3.md](2026-09-27-issue-204-transaction-core-skeleton.tasks/task-3.md)

Task 4 — Neutrality checker test and CLAUDE.md sentence — `tests/test_transaction_core_sweep.py`, `CLAUDE.md` — low-risk — [task-4.md](2026-09-27-issue-204-transaction-core-skeleton.tasks/task-4.md)

## Decisions

The spec's `## Decision ledger` owns every decision. Tasks cite: D1, D2, D3, D4, D5, D7,
D8, D9, D10, D13, D15, D16 (Task 1); D7, D8, D9, D10, D13, D15, D16 (Task 2); D6, D14, D17
(Task 3); D11, D12, D14 (Task 4). Planning added D14–D17.

---
