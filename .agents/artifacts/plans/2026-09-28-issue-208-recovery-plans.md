# Transaction Core Recovery Plans Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** ship slice 5/6 of the transaction core. Every transaction carries an immutable
recovery plan compiled at creation beside its proof plan. Rollback anchors are verified in
`ready` before publication. `begin_recovery`, `settle_recovery` and `roll_forward` become the
only ways into `recovering`, into `rolled_back` and to a linked child transaction
([#208](https://github.com/fagenorn/nix-config/issues/208), parent
[#123](https://github.com/fagenorn/nix-config/issues/123)).

**Architecture:** two new pure modules (per D1). `agent_tools.transaction_recovery_plan`
holds the declaration schema, `compile_recovery`, `bind_recovery`, `materialize_recovery`
and the validator's inverse. `agent_tools.transaction_recovery` holds the effect classes, the
selection, the admission and decision halves of the four operations, the event and pairing
rules, the gates and the `recovery` view. `transaction_history` moves to
`transaction-state/v5` and dispatches recovery events and gates. `transaction_core` gains
`create(..., recovery=)`, `verify_anchors`, `begin_recovery`, `settle_recovery` and
`roll_forward`, which keep only locks, clock, observer calls and writes. The import direction
becomes core → history → recovery → recovery_plan → proof → plan → invocation → custody →
storage. Tasks 1–2 build the plan, Task 3 the anchors, Tasks 4–7 the recovery operations, and
Task 8 the sweep.

**Tech stack:** Python 3 standard library, `agent_tools.canonical.telemetry_digest`, `just`,
Nix (`lib/agent-tools.nix` import check, unchanged).

Spec (the source of truth, read it whole):
`.agents/artifacts/specs/2026-09-28-issue-208-recovery-plans-design.md`, D1–D24.
The code base is commit `f999226` (slices 1–4 as merged; the base for every budget check).

## Global Constraints

- Scope is exactly the spec's, and its `## Out of scope` list binds: no `failed`
  disposition, receipts, recovery DAG, anchor retention, #84 content, CLI, command-table row,
  Nix or host change, and no #125 cutover.
- The nine modules import only the standard library, `agent_tools.canonical` and each other,
  in the direction above: a module imports only modules to its right. Only
  `transaction_core` and `transaction_custody` read a file, lock or clock.
- `lib/agent-tools.nix` is not edited; its recursive walk import-checks new modules (stage
  new files with `git add` before `just build`).
- Digests come only from `agent_tools.canonical`, and the storage codecs own strict JSON
  (`docs/standards/agent-helpers.md` rule 4). No `sys.path`, `importlib` or `__file__`
  anywhere, tests included (rule 3).
- Every file the store writes is exactly
  `json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"`,
  replaced atomically with `atomic_write`.
- The code of all nine modules, with comments and docstrings excluded, contains no word from
  the neutrality lists in `tests/test_transaction_core_sweep.py` (for example `tag`,
  `deploy`, `switch`, `push`).
- No lock is held while an observer or effect runs, and the core catches nothing they raise.
  The parent lock is never held across a child's creation (per D11).
- Refusals are typed and closed, each with one construction path that raises `ValueError`
  on an unknown reason. `RecoveryPlanRejected.reason` is in `RECOVERY_REJECTION_REASONS`,
  raised before any lock or write. `RecoveryRefused.reason` is in
  `RECOVERY_REFUSAL_REASONS`, raised before any write. Every message names the transaction
  id (from `create`, the root and creation key) and the rule, and a refusal naming a unit
  says `<name> (<action id>)` (per D23).
- Constants, exact: schema `transaction-state/v5`, plan schema
  `transaction-recovery-plan/v1`, `POSTURES = ("restorable", "compensatable",
  "supersedable_only", "manual_only")`, `EDGE_ACTIONS = ("restore", "compensate")`, and
  `EFFECT_CLASSES = ("no_effect", "target_satisfied", "diverged", "in_progress", "unknown")`.
- The explicit empty declaration is `{"effects": {}, "units": []}`, and `create` has no
  default for `recovery` (per D2).
- Size caps (per D20): after every task, `transaction_core.py` is at most 64000 bytes and
  each touched file's cumulative `git diff -U10 f999226` is under 65536 bytes. Every task
  ends by running this review-budget block with its `FILES`. A non-zero exit means the task
  is not done: move judgment out of the core.

```bash
base=f999226; fail=0
for f in $FILES; do
  n=$(git diff -U10 "$base" HEAD -- "$f" | wc -c); printf '%s %s\n' "$n" "$f"
  [ "$n" -lt 65536 ] || fail=1
done
[ "$(wc -c < python/agent_tools/transaction_core.py)" -le 64000 ] || fail=1
test "$fail" = 0
```
- Fixtures, which may use provider names, live only under `tests/`.
- Commits are signed (never `--no-gpg-sign`) and end with the two trailer lines the caller
  supplies.

## Test seams

- Seam 1: `TransactionStore(root, clock=FakeClock())` under a `tempfile` root, with fake
  effects (`FakeEffect`) and in-memory **fake observers** (`Checker`), observed through
  returned snapshots, error classes and `.reason`, listings and `state.json` bytes. Tests
  may hand-edit `state.json`, and reach the pure names only through `transaction_core`
  re-exports (per D16, D24).
- Seam 2: the fixture executor `drive(root, shape, scenario, world=None) -> str`, compared
  through a fresh `TransactionStore(root).load(...)` and the passed world.
- Seam 3: `neutrality_findings(source)` over all nine modules.
- `SLICE` = `tests/test_transaction_core.py tests/test_transaction_custody.py
  tests/test_transaction_invocation.py tests/test_transaction_plan.py
  tests/test_transaction_proof.py tests/test_transaction_core_sweep.py`, plus every
  `tests/test_transaction_recovery*.py` that exists at the task. The slice unit command is
  `PYTHONPATH=python python3 -m unittest $SLICE 2>&1 | tail -3`.
- No test calls or patches a `_`-prefixed name. No test imports `transaction_recovery_plan`,
  `transaction_recovery` or another inner module, except for re-export identity checks and
  the neutrality test.

## Delivery estimate and boundaries

These are estimates only. About 16 files change. The main ones are the new
`transaction_recovery_plan.py` (~250 lines) and `transaction_recovery.py` (~550 lines),
`transaction_core.py` (53.4 KB → ~63 KB), `transaction_history.py` (+~60 lines) and three new
test files of ~25–40 KB each. The growth risks are the core cap (D20) and
`tests/test_transaction_recovery.py`. Every task leaves the suite green. Task 2 passes the
empty declaration to every existing store test and real declarations to the sweep, and
Task 3 makes the sweep verify anchors before publication.

## Task index

Task 1 — Recovery declaration: compile, bind and materialize — `python/agent_tools/transaction_recovery_plan.py`, `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_recovery_plan.py`, `tests/test_transaction_core_sweep.py`, `justfile` — full — [task-1.md](2026-09-28-issue-208-recovery-plans.tasks/task-1.md)

Task 2 — Schema v5: the stored plan, `create(recovery=)` and `recovers` — `python/agent_tools/transaction_recovery.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_recovery_plan.py`, `tests/test_transaction_core.py`, `tests/test_transaction_custody.py`, `tests/test_transaction_invocation.py`, `tests/test_transaction_plan.py`, `tests/test_transaction_proof.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py` — full — [task-2.md](2026-09-28-issue-208-recovery-plans.tasks/task-2.md)

Task 3 — `verify_anchors` and the publication gate — `python/agent_tools/transaction_recovery.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_storage.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_recovery.py`, `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`, `justfile` — full — [task-3.md](2026-09-28-issue-208-recovery-plans.tasks/task-3.md)

Task 4 — `begin_recovery`, effect classes and the `abandoned` gate — `python/agent_tools/transaction_recovery.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_recovery.py`, `tests/test_transaction_core.py`, `tests/test_transaction_custody.py` — full — [task-4.md](2026-09-28-issue-208-recovery-plans.tasks/task-4.md)

Task 5 — Recovery edges through the administrative protocol — `python/agent_tools/transaction_invocation.py`, `python/agent_tools/transaction_recovery.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_recovery.py`, `tests/test_transaction_invocation.py` — full — [task-5.md](2026-09-28-issue-208-recovery-plans.tasks/task-5.md)

Task 6 — `settle_recovery` and `rolled_back` — `python/agent_tools/transaction_recovery.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_recovery_settle.py`, `justfile` — full — [task-6.md](2026-09-28-issue-208-recovery-plans.tasks/task-6.md)

Task 7 — `roll_forward` and the linked child — `python/agent_tools/transaction_recovery.py`, `python/agent_tools/transaction_history.py`, `python/agent_tools/transaction_core.py`, `tests/test_transaction_recovery_settle.py` — full — [task-7.md](2026-09-28-issue-208-recovery-plans.tasks/task-7.md)

Task 8 — Five recovery rows in the sweep, and CLAUDE.md — `tests/transaction_core_sweep_support.py`, `tests/test_transaction_core_sweep.py`, `CLAUDE.md` — full — [task-8.md](2026-09-28-issue-208-recovery-plans.tasks/task-8.md)

## Decisions

The spec's `## Decision ledger` owns every decision, and each task ends with the rows it
cites. Planning added D20–D24: the core budget and shared two-hold helper, the compile rule
classification, `not_selected` precedence, id-named units in events, and the test split.
