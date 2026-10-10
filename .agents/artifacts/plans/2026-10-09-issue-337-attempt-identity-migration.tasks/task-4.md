# Task 4: Move the attempt store into `agent_tools.attempt_store` (no behaviour change)

**Files:**
- Create: `python/agent_tools/attempt_store.py`
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `python/agent_tools/attempt_identity.py` (module docstring only)

No test file changes. This task restructures the code Tasks 2 and 3 committed (`aae76ba`, `b5519a4`) so that `workflow-state.py`'s cumulative diff fits one review-package member (D27–D29). Every CLI reply, exit code, stderr message, ledger byte and `.superpowers` path stays what it is at the task's start head. If any focused test needs an edit to pass, stop and report BLOCKED with the test name: that is a behaviour change.

**Interfaces:**
- Consumes (Task 1): from `agent_tools.attempt_identity`: `RunIdentity`, `RunPlan`, `MigrationRefused`, `REFUSAL_REASONS`, `classify`, `creation_arguments`, `identity_of`, `legacy_identity`, `minted_plan`, `plan_migration`, `schema_refusal`, `subject_handle`, `subject_violation`; `TransactionStore` (`create`, `load`, `lookup`), `TransactionError`; `transaction_storage.is_id`.
- Produces, in `agent_tools.attempt_store` (Tasks 6–8 use these names):
  - `class StoreRefused(Exception)` — every refusal the moved code raised as `WorkflowError`, with the identical message text.
  - `class LedgerRefused(StoreRefused)` — `reason` (one of `REFUSAL_REASONS`, else `ValueError`), message `"workflow state refused: <reason>: <detail>"`. Replaces workflow-state's `LedgerRefused`.
  - `class LockedRead(NamedTuple)`: `state: dict`, `identity: RunIdentity`, `changed: bool`.
  - `store_root(superpowers: Path) -> Path` = `superpowers / "attempt-transactions"` (pure).
  - `ledger_store(state_path: Path) -> Path` = `store_root(state_path.parents[2])`: the store beside the `workflows` directory that holds `<run>/state.json` (pure, D28).
  - `ensure_store(store: Path) -> Path` — creates `store.parent` (label `.superpowers`) and `store` (label `attempt transactions`) as non-symlink directories and the `*` `.gitignore` (label `attempt transactions .gitignore`, `*\n`, mode 0o644).
  - `creation_key_plan(caller_key: str) -> RunPlan` — `minted_plan(identity=RunIdentity("orchestrated", None, None), prior_run=None, caller_key=caller_key)`; `ValueError` → `StoreRefused("invalid creation key")`.
  - `mint_run(store: Path, plan: RunPlan) -> str`, `lookup_run(store: Path, creation_key: str) -> str | None`, `bound_identity(store: Path, state: dict, run_id: str) -> RunIdentity`, `require_known_schema(document) -> None`, `plan_legacy_run(document: dict) -> RunPlan` — today's functions of the same names (`attempt_store_root`'s callers pass `store` instead of `repo_root`), same order of checks, same messages.
  - `locked_read(state_path: Path, document, *, run_id: str, upgrade, validate) -> LockedRead` and `check_unlocked(state_path: Path, document, *, run_id: str, upgrade, validate) -> None` — today's `read_locked_state` and `read_state_unlocked` bodies after the JSON load. Callback contract: `upgrade(document, *, run_id, identity) -> dict` returns the validated schema-7 candidate or raises `LedgerRefused("invalid_state", …)`; `validate(state, *, run_id, identity) -> dict` validates a schema-8 state. The package passes `identity=` (the bound identity, or `legacy_identity(run_id)` falling back to `RunIdentity("orchestrated", None, None)` for an unknown dialect) and catches neither callback's errors.
  - `indexed_direct_runs(store: Path, workflows_dir: Path, issue: int, *, after: int) -> Iterator[tuple[int, str, Path]]` — a generator over `s = after + 1, after + 2, …` with today's probe rules: stop at the first `lookup_run` miss; a hit whose `classify` is not `core` raises `StoreRefused("direct run index entry is not a run transaction")`; stop when `workflows_dir / id` is absent; a symlink or non-directory raises `StoreRefused("direct run entry must be a non-symlink directory")`; stop when it has no `state.json`; otherwise yield `(s, id, workflows_dir / id)`. It is lazy so `direct-owner` locks and checks each run before the next lookup, as today.
- Produces, in `workflow-state.py`: `upgrade_state(value, *, run_id, identity, migration_contracts) -> dict` (the base name, at the base position): `_call(None, _delivery().migrate, …)` then `validate_state(candidate, run_id=run_id, identity=identity, schema_version=7)`, a `WorkflowError` re-raised as `attempt_store.LedgerRefused("invalid_state", str(error))`. `read_locked_state(state_path, run_id, *, migration_contracts) -> LockedRead` and `read_state_unlocked(state_path, run_id) -> dict` keep their base signatures.

**Invariants:**
- The package module follows `docs/standards/agent-helpers.md`: standard library and `agent_tools` imports only, no `sys.path`, `importlib` or `__file__` use, no command-table row.
- Its file-system helpers are copies of workflow-state's `path_status`, `ensure_directory`, `require_regular_path`, `open_existing_regular`, `verify_open_file`, `open_stable_lock`, `ensure_gitignore` and `fsync_directory`, narrowed to what the store uses and raising `StoreRefused` with the same message for the same label (D27). The mint lock is still `<store>/attempt-runs.lock`, mode 0o600, a blocking `LOCK_EX` around `create` (D9).
- `main` catches `(WorkflowError, OSError, attempt_store.StoreRefused)`; the output stays `workflow-state: <message>` with exit 2. No other `except` clause in `workflow-state.py` gains or loses a store call: `_installed_delivery`'s `except Exception` is the only handler around one, as today.
- `workflow-state.py` no longer defines `LedgerRefused`, `LockedRead`, `attempt_store_root`, `ensure_attempt_store`, `_existing_attempt_store`, `mint_run`, `lookup_run`, `bound_identity`, `require_known_schema`, `_legacy_identity_or_placeholder`, `plan_legacy_run` or `legacy_candidate`, and no longer imports `NamedTuple`, `TransactionStore` or `TransactionError`.
- The store location comes from paths only (D28): `transact` drops `root = run_dir.parents[2]`, and no reader takes `repo_root`. Before relying on `ledger_store`, confirm that every `read_state_unlocked` and `read_locked_state` caller builds its `state_path` as `<resolve_repo_root(...)>/.superpowers/workflows/<run>/state.json`. If one does not, stop and report BLOCKED naming it.

- [ ] **Step 1: Record the starting point and watch the gate fail**

Run, from the worktree root (`$SCRATCH` is the directory `launch-scope scratch` printed; each run under `launch-scope exec`, timeout ≥ 900 s):

```bash
BASE=eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7
WS=home/common/agent-skills/scripts/workflow-state.py
FLOOR="home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_host_admission.py home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_admission_replay.py tests/test_launch_scope.py tests/test_launch_commit.py"
PYTHONPATH="$PWD/python" python3 -m unittest $FLOOR > "$SCRATCH/t4-start.log" 2>&1
grep -E '^(FAIL|ERROR):' "$SCRATCH/t4-start.log" | sort -u > "$SCRATCH/t4-start.txt"
git diff -U10 "$BASE"..HEAD -- "$WS" | wc -c
```

Expected: `74942`, above the 55000 ceiling, so Step 4's ceiling check fails here. `t4-start.txt` is the declared red set (Tasks 2–3 opened it; Task 5 closes it).

- [ ] **Step 2: Create `attempt_store.py` and delete the moved code**

Module docstring: the effectful half of attempt run identity (#337 D27): the store root beside `workflows`, the blocking mint lock, mint and lookup, the binding check, the locked-read and unlocked-check transform under the caller's lock, and the direct index probe; `workflow-state` keeps the ledger lock, the ledger read and commit, the delivery chain and `validate_state`. Move each function body unchanged except for `repo_root` → `store` parameters and `WorkflowError` → `StoreRefused`. Restore `ensure_gitignore` to its exact base text (`git show "$BASE:$WS"`), since the store now has its own copy.

- [ ] **Step 3: Collapse the call sites in `workflow-state.py`**

1. Imports: `from functools import partial`; `from agent_tools import attempt_store`; from `attempt_identity` only the names `workflow-state.py` still uses (expected: `RunIdentity`, `classify`, `minted_plan`, `prior_run_violation`); `is_id` stays.
2. `read_locked_state`: base signature; after the base JSON load, `return attempt_store.locked_read(state_path, value, run_id=run_id, upgrade=partial(upgrade_state, migration_contracts=migration_contracts), validate=validate_state)`.
3. `read_state_unlocked`: base signature; after the load, `attempt_store.check_unlocked(state_path, raw_state, run_id=run_id, upgrade=partial(upgrade_state, migration_contracts={}), validate=validate_state)` then `return raw_state` (`validate_state` returns its argument, so this is today's value). Keep its docstring's current behaviour sentence, pointing at `attempt_store.check_unlocked`.
4. Revert to their base text: `transact`'s `read_locked_state` call, `_installed_delivery`'s signature and its three callers, and the `read_state_unlocked` calls in `check-launch`, `owner-liveness`, `mark-progress`, `resume-pack` and `check-worker`.
5. `init-run --creation-key`: `plan = attempt_store.creation_key_plan(args.creation_key)` before `resolve_repo_root`, as today, then `attempt_store.mint_run(attempt_store.store_root(resolve_repo_root(args.repo_root) / ".superpowers"), plan)`; `mint_run` calls `ensure_store` itself, as `mint_run` calls `ensure_attempt_store` today.
6. `direct-owner`: `attempts = attempt_store.store_root(repo_root / ".superpowers")` once; the `while True` probe becomes `for sequence, probed_id, probed_dir in attempt_store.indexed_direct_runs(attempts, workflows_dir, issue, after=sequence): candidates.append(retain(sequence, probed_id, probed_dir, True))`; `lookup_run`, `mint_run`, `bound_identity` take `attempts`; the reader calls drop `repo_root=`. Write each `commit_state(..., identity=identity)` on one line where it fits in 99 columns.
7. `attempt_identity.py` docstring: replace "`workflow-state` owns every effect: it reads the ledgers, takes the locks, calls `TransactionStore.create` and `lookup`, and renders the report." with a sentence naming `agent_tools.attempt_store` as the owner of the store effects and `workflow-state` of the ledgers and their locks.

- [ ] **Step 4: Verify**

Each command under `launch-scope exec`, timeout ≥ 900 s unless stated:

```bash
PYTHONPATH="$PWD/python" python3 -m unittest tests/test_attempt_identity.py tests/test_transaction_core.py tests/test_transaction_core_sweep.py home/common/agent-skills/tests/test_attempt_migration.py
PYTHONPATH="$PWD/python" python3 -m unittest tests/test_launch_scope.py -k minted_run_handle -k unsafe_ids
PYTHONPATH="$PWD/python" python3 -m unittest $FLOOR > "$SCRATCH/t4-end.log" 2>&1
grep -E '^(FAIL|ERROR):' "$SCRATCH/t4-end.log" | sort -u > "$SCRATCH/t4-end.txt"
diff "$SCRATCH/t4-start.txt" "$SCRATCH/t4-end.txt"
bytes=$(git diff -U10 "$BASE"..HEAD -- "$WS" | wc -c); echo "$bytes"; [ "$bytes" -le 55000 ]
if grep -nE '^(def (attempt_store_root|ensure_attempt_store|mint_run|lookup_run|bound_identity|legacy_candidate|plan_legacy_run|require_known_schema)|class (LedgerRefused|LockedRead))\b' "$WS"; then exit 1; fi
```

Expected: the first two `OK`; `diff` prints nothing (the red set is unchanged, so no lifecycle behaviour moved); `bytes` ≤ 55000; the `grep` finds nothing. Run the ceiling check after the commit (it reads `HEAD`). A replay of these moves measured about 54600 bytes before any docstring trim, so also cut each docstring this issue added or changed in `workflow-state.py` (`init-run`, `transact`, `new_run_state`, `select_phase_action`, `_apply_one_issue_policy`, `read_state_unlocked`) to the sentences that state its current contract, pointing at `attempt_store` for the moved detail. If the check still fails, report BLOCKED with the byte count. Never move a `state.lock` acquisition out of `workflow-state.py`.

Then `just build` (timeout 3600 s; it import-checks every `agent_tools` module) — succeeds. Then the cumulative package gate:
`review-package .agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.md "$BASE" "$(git rev-parse HEAD)" "$SCRATCH/review-task4.json" | artifact-budget validate-report --boundary producer --input -` — `"state":"complete"` and `"budget_status":"within_budget"`.

- [ ] **Step 5: Commit**

Stage the three files, then `launch-commit … -- -m "refactor: move the attempt store into agent_tools.attempt_store (#337)"`, with the measured byte count in the body and the session trailers.
