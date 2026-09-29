# Transaction Core Terminal Receipts Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** ship slice 6/6 of the transaction core. Every terminal seals one permanent,
content-addressed `transaction-terminal-receipt/v1` in the same write that enters it.
`failed` is entered only through `dispose_failed`, with a closed ground. The sweep reaches
its full gate, the prototype's 56 cells inside a 64-cell table
([#209](https://github.com/fagenorn/nix-config/issues/209), parent
[#123](https://github.com/fagenorn/nix-config/issues/123)).

**Architecture:** two new modules (per D1). `agent_tools.transaction_receipt` holds the
receipt derivation, the `receipt_sealed` rule, the `terminal` view and `ReceiptStore`, the
file store under the root-level `receipts/`, `hazards/` and `observations/` (per D6).
`agent_tools.transaction_disposition` holds the grounds, the disposition shape, the
`DispositionRefused` reasons, the admission and event halves of `dispose_failed` and its
validator rules. `transaction_history` moves to `transaction-state/v6` and dispatches both.
`transaction_core` seals inside `_append` and gains thin wrappers. The import direction
follows D19. Task 1 lays v6 down and closes `failed`. Tasks 2–3 build the receipt. Task 4
builds the disposition, Task 5 the hazard markers and post-terminal observations, and Task 6
the sweep.

**Tech stack:** Python 3 standard library, `agent_tools.canonical.telemetry_digest`, `just`,
Nix (`lib/agent-tools.nix` import check, unchanged).

Spec (the source of truth, read it whole):
`.agents/artifacts/specs/2026-09-29-issue-209-terminal-receipts-design.md`, D1–D22.
The code base is commit `93bf5fd` (slices 1–5 as merged; the base for every budget check).

## Global Constraints

- Scope is exactly the spec's, and its `## Out of scope` list binds: no `workflow-state`
  wiring, command-table row, Nix or host change, preflight acknowledgement,
  `hazard_discharged`, #84 authentication, or ledger deletion.
- The eleven modules import only the standard library, `agent_tools.canonical` and each
  other, in D19's direction: a module imports only modules to its right. Only
  `transaction_core`, `transaction_custody` and `transaction_receipt` read or write a
  file. Only the first two take a lock or read the clock.
- `lib/agent-tools.nix` is not edited. Its recursive walk import-checks new modules, so
  stage new files with `git add` before `just build`.
- Digests come only from `agent_tools.canonical`, and the storage codecs own strict JSON
  (`docs/standards/agent-helpers.md` rule 4). No `sys.path`, `importlib` or `__file__`
  anywhere, tests included (rule 3).
- Every file the store writes is exactly `serialize(doc)` from `transaction_storage`
  (sorted, compact, ASCII, no NaN, one trailing newline). `state.json` is replaced with
  `atomic_write`. Receipt-store files are create-if-absent, never replaced (per D6, D20).
- The code of all eleven modules, with comments and docstrings excluded, contains no word
  from the neutrality lists in `tests/test_transaction_core_sweep.py` (for example
  `merge`, `tag`, `deploy`, `push`). Delivery words appear only under `tests/` (per D4).
- No lock is held while an observer or effect runs, and the core catches nothing they
  raise. `dispose_failed` loads its successor with no lock held (per D21).
- Refusals are typed and closed, each with one construction path that raises
  `ValueError` on an unknown reason. `DispositionRefused.reason` is in
  `DISPOSITION_REFUSAL_REASONS`, raised before any write. Every message names the
  transaction id and the rule.
- Constants, exact: `SCHEMA = "transaction-state/v6"`, `RECEIPT_SCHEMA =
  "transaction-terminal-receipt/v1"`, `HAZARD_SCHEMA = "transaction-hazard-marker/v1"`,
  `OBSERVATION_SCHEMA = "transaction-post-terminal-observation/v1"`, `ACTOR_KINDS =
  ("human", "agent")`, `KNOWN_STATE_GROUNDS = ("successor_succeeded", "no_recovery_path")`,
  `OBSERVABILITY_GROUNDS = ("authority_retired", "tenancy_destroyed",
  "host_decommissioned", "credential_class_revoked_without_successor",
  "subject_scope_erased")`, `GROUNDS = KNOWN_STATE_GROUNDS + OBSERVABILITY_GROUNDS`,
  `CONSEQUENCES = ("effects_destroyed_with_authority",
  "effects_possibly_live_unobservable")`, `QUALIFIERS = ("final_state_known",
  "effects_unobservable")`, `RESIDUE_BOUNDS = ("bounded", "unbounded")`, and
  `DISPOSITION_REFUSAL_REASONS` exactly the eleven the spec lists, in its order.
- Size caps (per D17, D19): after every task, `transaction_core.py` is at most 64000 bytes
  and each touched file's cumulative `git diff -U10 93bf5fd` is under 65536 bytes. Every
  task ends by running this review-budget block with its `FILES`. A non-zero exit means the
  task is not done. Past 64000 the first remedy is docstring economy: a core wrapper's
  docstring points to its pure function's docstring instead of restating it (#208 D27).

```bash
base=93bf5fd; fail=0
for f in $FILES; do
  n=$(git diff -U10 "$base" HEAD -- "$f" | wc -c); printf '%s %s\n' "$n" "$f"
  [ "$n" -lt 65536 ] || fail=1
done
[ "$(wc -c < python/agent_tools/transaction_core.py)" -le 64000 ] || fail=1
test "$fail" = 0
```
- Docstrings and comments written into the code describe the code as implemented. Update
  every module and function docstring a task's change makes stale in that task.
- Commits are signed (never `--no-gpg-sign`) and end with the trailer line
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Test seams

- Seam 1 (per D16): `TransactionStore(root, clock=FakeClock())` under a `tempfile` root,
  with `FakeEffect`, the `Observer` and `Checker` fakes, observed through returned
  snapshots, error classes and `.reason`, the documented file layout
  (`<id>/state.json`, `receipts/`, `hazards/`, `observations/`) and file bytes. Tests may
  hand-edit `state.json` and receipt files, and may make `receipts` a file, a symlink or
  mode `0o500`. They reach pure names only through `transaction_core` re-exports.
- Seam 2: the fixture executor `drive(root, shape, scenario, world=None) -> str`, compared
  through a fresh `TransactionStore(root).load(...)`, the passed world and the receipt files.
- Seam 3: `neutrality_findings(source)` over all eleven modules.
- `SLICE` = `tests/test_transaction_core.py tests/test_transaction_custody.py
  tests/test_transaction_invocation.py tests/test_transaction_plan.py
  tests/test_transaction_proof.py tests/test_transaction_recovery_plan.py
  tests/test_transaction_recovery.py tests/test_transaction_recovery_settle.py
  tests/test_transaction_core_sweep.py`, plus `tests/test_transaction_receipt.py` and
  `tests/test_transaction_disposition.py` once they exist. The slice unit command is
  `PYTHONPATH=python python3 -m unittest $SLICE 2>&1 | tail -3`.
- No test calls or patches a `_`-prefixed name. No test imports `transaction_receipt`,
  `transaction_disposition` or another inner module, except for re-export identity checks,
  the neutrality test and Task 4's `ValueError` check of `disposition_refused`.

## Delivery estimate and boundaries

These are estimates only. About 20 files change. The new modules are
`transaction_receipt.py` (~350 lines) and `transaction_disposition.py` (~300 lines).
`transaction_core.py` goes from 61869 bytes to ~63.5 KB after Task 1's docstring cut.
`transaction_history.py` grows ~80 lines. The two new test files run ~25–35 KB each. The
growth risks are the core cap and `tests/test_transaction_core.py`, whose terminal tests
change in Tasks 1–2. Every task leaves the whole slice green.

## Task index

Task 1 — Schema v6: authority class, actor kind, and `failed` closed — `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_custody.py`, `python/agent_tools/transaction_disposition.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_disposition.py`, `justfile`, `tests/test_transaction_core.py`, `tests/test_transaction_custody.py`, `tests/test_transaction_invocation.py`, `tests/test_transaction_plan.py`, `tests/test_transaction_proof.py`, `tests/test_transaction_recovery_plan.py`, `tests/test_transaction_recovery.py`, `tests/test_transaction_recovery_settle.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py` — full — [task-1.md](2026-09-29-issue-209-terminal-receipts.tasks/task-1.md)

Task 2 — The sealed receipt: `ReceiptStore`, the seal and read-back — `python/agent_tools/transaction_receipt.py`, `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_receipt.py`, `tests/test_transaction_core.py`, `tests/test_transaction_custody.py`, `tests/test_transaction_invocation.py`, `tests/test_transaction_proof.py`, `tests/test_transaction_recovery.py`, `tests/test_transaction_recovery_settle.py`, `tests/test_transaction_core_sweep.py`, `justfile` — full — [task-2.md](2026-09-29-issue-209-terminal-receipts.tasks/task-2.md)

Task 3 — The receipt's truth: postconditions, stops, owner results, evaluations — `python/agent_tools/transaction_receipt.py`, `tests/test_transaction_receipt.py` — full — [task-3.md](2026-09-29-issue-209-terminal-receipts.tasks/task-3.md)

Task 4 — `dispose_failed`: the closed disposition and every refusal — `python/agent_tools/transaction_disposition.py`, `python/agent_tools/transaction_recovery.py`, `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_receipt.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_disposition.py` — full — [task-4.md](2026-09-29-issue-209-terminal-receipts.tasks/task-4.md)

Task 5 — Hazard markers and post-terminal observations — `python/agent_tools/transaction_receipt.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_disposition.py` — full — [task-5.md](2026-09-29-issue-209-terminal-receipts.tasks/task-5.md)

Task 6 — The full sweep gate, and CLAUDE.md — `tests/transaction_core_world.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`, `CLAUDE.md` — full — [task-6.md](2026-09-29-issue-209-terminal-receipts.tasks/task-6.md)

## Decisions

The spec's `## Decision ledger` owns every decision, and each task ends with the rows it
cites. Planning added D19–D22: the core budget and import direction, the receipt's byte
and derivation details, how `failed` closes early and how the validator re-derives it, and
the grant, hazard-marker and observation argument rules.
