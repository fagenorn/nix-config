# Task 6: `workflow-state migrate` — dry run, apply and report

**Files:**
- Modify: `python/agent_tools/attempt_store.py` (inventory, row builder and report: `migration_row`, `migration_report`; the `StoreFault` split, D37)
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (a thin `command_migrate` and its parser entry only, D27)
- Modify: `home/common/agent-skills/tests/test_attempt_migration.py` (new `MigrationAcceptanceTest`)

**Interfaces:**
- Consumes (Task 1): `attempt_identity.schema_refusal`, `classify`, `legacy_alias`, `legacy_identity`, `plan_migration`, `direct_key`, `legacy_key`, `report`, `REPORT_ROW_FIELDS`, `MigrationRefused`, `RunIdentity`; `print_json` (workflow-state's existing sorted-key, compact rendering) for output. (Task 2): `transact(repo_root, run_id, mutation)`, `validate_state(value, *, run_id, identity, schema_version=8)`. (Task 4, `agent_tools.attempt_store`): `StoreRefused`, `LedgerRefused` (with `.reason`), `UnknownTransaction` (`agent_tools.transaction_storage`), `store_root`, `bound_identity`, `lookup_run`, `require_known_schema`, `plan_legacy_run`, and the callback contract of `locked_read`/`check_unlocked`; in `workflow-state.py`, `upgrade_state(value, *, run_id, identity, migration_contracts)`. (Tasks 2–3 harness / `MigrationFixtures`): `install_legacy`, `install_orchestrated`, `delivered_207`, `tree_snapshot`, `store`, `store_root`, `direct_run_id`, `acquire_direct`.
- Produces:
  - CLI: `workflow-state migrate --repo-root <root> [--apply]`. Stdout: one canonical JSON document (sorted keys, compact separators, trailing newline) — `attempt_identity.report(mode, rows)`. Exit 0 whenever every ledger got a verdict; exit 2 on usage, a missing or unreadable `<root>/.superpowers/workflows`, or a store error (D8).
  - In `attempt_store`: `migration_row(superpowers: Path, ledger: str, *, upgrade, validate, refusals: tuple[type[Exception], ...], migrated: bool = False) -> dict` — one read-only row (below); and `migration_report(superpowers: Path, *, apply: bool, upgrade, validate, bind, refusals) -> dict` — the inventory, the rows, the apply loop and `attempt_identity.report`. `upgrade` and `validate` follow Task 4's callback contract; `bind(handle: str) -> None` is the caller's locked no-op write; `refusals` are the caller's own error types, which a row reports as `invalid_state`. A missing or non-directory `workflows` raises `StoreRefused`.
  - In `attempt_store` (D37): `class StoreFault(StoreRefused)` — the store itself cannot be read. `_existing_store`'s non-directory refusal and the `TransactionError` wrappers in `lookup_run` and `bound_identity` raise `StoreFault`, with their messages unchanged, except that `bound_identity` keeps a plain `StoreRefused` for `UnknownTransaction` (the ledger names a transaction the store does not hold). Every other caller still catches `StoreRefused`, so no other behaviour or message changes.
  - In `workflow-state.py`: `command_migrate(args)` only — `root = resolve_repo_root(args.repo_root)`, then `print_json(attempt_store.migration_report(root / ".superpowers", apply=args.apply, upgrade=partial(upgrade_state, migration_contracts={}), validate=validate_state, bind=lambda handle: transact(args.repo_root, handle, lambda state: (None, False)), refusals=(WorkflowError,)))` and `return 0`, plus the `migrate` subparser (`--repo-root` required, `--apply` flag). No row logic lives in `workflow-state.py`.

**Invariants:**
- **Inventory:** the non-dot entries of `<root>/.superpowers/workflows` that are non-symlink directories holding a regular `state.json`, in name order. Nothing else is read.
- **Row (read-only; never creates the store root, a lock or a directory):** parse the JSON (unparseable → `invalid_state`); `schema_refusal` → `unknown_schema`; `ledger` is the directory name; `run_id`, `schema_version`, `prior_run` and `issues` (sorted ints of the `issues` keys) are copied from the document when present and well-typed, else `null`; `dialect = classify(run_id)`; `alias = legacy_alias(run_id)` when the dialect is a legacy one, else the bound subject's `alias` for a schema-8 ledger, else `null`.
  - recorded `run_id != ledger` → `refused` / `location_mismatch` (checked before the plan).
  - schema 8 → `bound_identity` and `validate` succeed → `current`, `transaction_id` = recorded; a ledger-attributable failure — a plain `StoreRefused` (malformed or unknown `transaction_id`, absent store root, bad subject, handle mismatch) or one of `refusals` — → `refused` / `invalid_state`; a `StoreFault` propagates, and the command exits 2 (spec § Exit codes, D37).
  - schema ≤ 7 → `upgrade` (the chain to 7 with empty migration contracts, D20, and schema-7 validation; its `LedgerRefused` → `invalid_state`), then `plan_legacy_run` (refusal → its reason) → `migrate`; `transaction_id = lookup_run(store, plan.creation_key)` (`null` when unindexed or the store is absent; its `StoreFault` propagates).
  - `prior_transaction_id`: `null` when `prior_run` is `null`; the id itself when `prior_run` is `core`; `lookup_run(store, direct_key(issue, seq))` for a `direct` prior; `lookup_run(store, legacy_key(prior_run))` otherwise.
  - `store` is `store_root(superpowers)`; nothing in a row creates it.
  - `reason` is `null` unless the verdict is `refused`.
- **Apply:** compute the dry-run rows; for each `migrate` row, call `bind(ledger)` (workflow-state's `transact(root, ledger, lambda state: (None, False))`) so the bind half runs on bytes re-read under that ledger's lock; on `LedgerRefused` record `refused` with its `reason` (the advisory dry-run verdict loses); a `StoreFault` propagates (exit 2). Then recompute the row with `migrated=True`, which turns a now-`current` row into `migrated`. `current` and `refused` rows are never passed to `transact` (no lock file is created for them). Report `mode: "apply"`.
- Idempotent: a second apply reports zero `migrated` and leaves the tree snapshot unchanged; two dry runs print identical bytes.
- No clock value appears in the report.
- Budget (D29, measured from the merge base per D33): after the commit, `git diff -U10 907dba234933e1457c2883530bf5f1b83e07a0ec..HEAD -- home/common/agent-skills/scripts/workflow-state.py | wc -c` prints at most 60000, and the same measure of `home/common/agent-skills/tests/test_attempt_migration.py` at most 60000.

- [ ] **Step 1: Write the failing tests**

```python
class MigrationAcceptanceTest(MigrationFixtures, unittest.TestCase):
    LEGACY = ("orchestrate-21-24-r2", "issues-29-30-20260817-r2")

    def migrate(self, *flags, ok=True):
        completed = self.run_cli("migrate", "--repo-root", self.root, *flags, ok=ok)
        return completed, (json.loads(completed.stdout) if ok else None)

    def rows(self, report):
        return {row["ledger"]: row for row in report["ledgers"]}

    def install_all(self):
        source = self.delivered_207()       # built in the driver's own root (D24)
        for handle in self.LEGACY:
            self.install_legacy(source, handle)
        self.init_run(creation_key="fixture-337")
        self.spawn(issue=337, worktree=str(self.root / "wt-337"))
        self.install_legacy(self.read_state(), "run-20261009-337-338-339")
        self.install_direct_pair()          # direct-41-000001 (terminal) and -000002 (D21)
        return source

    def launch_bytes(self, handle):
        return [self.run_cli(command, "--repo-root", self.root, "--run-id", handle,
                             "--action-id", action).stdout
                for command in ("check-launch", "current-launch")
                for action in ("207:1:4", "207:r1:1")]

    def test_ac1_minted_runs_and_legacy_rows_with_lineage(self):
        self.install_all()
        before = {handle: self.launch_bytes(handle) for handle in self.LEGACY}
        _, report = self.migrate("--apply")
        rows = self.rows(report)
        for handle in (*self.LEGACY, "run-20261009-337-338-339", "direct-41-000001",
                       "direct-41-000002"):
            with self.subTest(handle=handle):
                self.assertEqual(rows[handle]["verdict"], "migrated")
                key = (ai.direct_key(41, int(handle[-6:])) if handle.startswith("direct-")
                       else ai.legacy_key(handle))
                self.assertEqual(self.store().lookup(key), rows[handle]["transaction_id"])
        self.assertEqual(rows["direct-41-000002"]["prior_transaction_id"],
                         rows["direct-41-000001"]["transaction_id"])
        _, again = self.migrate()
        again_rows = self.rows(again)
        self.assertEqual(set(again_rows), set(rows))
        self.assertEqual({handle: row["verdict"] for handle, row in again_rows.items()},
                         {handle: "current" for handle in rows})
        self.assertEqual({handle: self.launch_bytes(handle) for handle in self.LEGACY}, before)

    def test_ac2_identity_never_comes_from_names(self):
        self.install_all()
        _, report = self.migrate()
        grouped = self.rows(report)["run-20261009-337-338-339"]
        self.assertEqual((grouped["alias"]["issues"], grouped["issues"]),
                         ([337, 338, 339], [337]))
        retried = self.rows(report)["orchestrate-21-24-r2"]
        self.assertEqual((retried["alias"]["retry"], retried["prior_run"],
                          retried["prior_transaction_id"]), (2, None, None))
        self.migrate("--apply")
        subject = self.store().load(self.store().lookup(
            ai.legacy_key("run-20261009-337-338-339"))).subject
        self.assertNotIn("issues", subject)
        moved = self.workflows_dir / "orchestrate-99"
        (self.workflows_dir / "issues-29-30-20260817-r2").rename(moved)
        snapshot = self.tree_snapshot()
        _, report = self.migrate()
        self.assertEqual((self.rows(report)["orchestrate-99"]["verdict"],
                          self.rows(report)["orchestrate-99"]["reason"]),
                         ("refused", "location_mismatch"))
        refused = self.run_cli("check-launch", "--repo-root", self.root, "--run-id",
                               "orchestrate-99", "--action-id", "207:1:4", ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(self.tree_snapshot(), snapshot)

    def test_ac3_dry_run_then_idempotent_apply(self):
        self.install_all()
        snapshot = self.tree_snapshot()
        first, _ = self.migrate()
        second, _ = self.migrate()
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(self.tree_snapshot(), snapshot)
        self.migrate("--apply")
        applied = self.tree_snapshot()
        _, again = self.migrate("--apply")
        self.assertEqual(again["counts"]["migrated"], 0)
        self.assertEqual(self.tree_snapshot(), applied)

    def test_ac3_dry_run_before_any_store_creates_nothing(self):
        source = self.install_orchestrated("orchestrate-21-24-r2")
        self.install_legacy(source, "issues-29-30-20260817-r2")
        self.assertFalse(self.store_root.exists())
        snapshot = self.tree_snapshot()
        first, report = self.migrate()
        second, _ = self.migrate()
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual({row["verdict"] for row in report["ledgers"]}, {"migrate"})
        self.assertEqual({row["transaction_id"] for row in report["ledgers"]}, {None})
        self.assertEqual(self.tree_snapshot(), snapshot)
        self.assertFalse(self.store_root.exists())

    def test_ac3_ledger_refusal_is_data_and_a_store_fault_exits_2(self):
        self.init_run(creation_key="fixture-unknown")
        unknown = self.run_id
        shutil.rmtree(self.store_root / unknown)      # the ledger names a missing transaction
        _, report = self.migrate()
        self.assertEqual((self.rows(report)[unknown]["verdict"],
                          self.rows(report)[unknown]["reason"]), ("refused", "invalid_state"))
        self.init_run(creation_key="fixture-fault")
        (self.store_root / self.run_id / "state.json").write_bytes(b"{")  # unreadable record
        snapshot = self.tree_snapshot()
        for flags in ((), ("--apply",)):
            with self.subTest(flags=flags):
                completed, _ = self.migrate(*flags, ok=False)
                self.assertEqual((completed.returncode, completed.stdout), (2, ""))
                self.assertTrue(completed.stderr.startswith("workflow-state: "),
                                completed.stderr)
                self.assertEqual(self.tree_snapshot(), snapshot)

    def test_ac3_refusals_are_byte_identical(self):
        fixtures = self.install_refusal_fixtures()
        snapshot = self.tree_snapshot()
        index = sorted((self.store_root / "creation-keys").iterdir())
        _, report = self.migrate("--apply")
        rows = self.rows(report)
        after = self.tree_snapshot()
        for handle, reason in fixtures.items():
            with self.subTest(handle=handle):
                self.assertEqual((rows[handle]["verdict"], rows[handle]["reason"]),
                                 ("refused", reason))
                prefix = f"workflows/{handle}/"
                self.assertEqual({k: v for k, v in after.items() if k.startswith(prefix)},
                                 {k: v for k, v in snapshot.items() if k.startswith(prefix)})
        self.assertEqual(sorted((self.store_root / "creation-keys").iterdir()), index)

    def test_ac3_precreated_transaction_is_bound(self):
        self.install_all()
        plan = ai.plan_migration(json.loads(
            (self.workflows_dir / "orchestrate-21-24-r2" / "state.json").read_text()))
        reserved = self.store().create(plan.creation_key, plan.subject_json(),
                                       **ai.creation_arguments(plan)).transaction_id
        _, report = self.migrate("--apply")
        self.assertEqual(self.rows(report)["orchestrate-21-24-r2"]["transaction_id"], reserved)

    def test_ac3_held_mint_lock_makes_apply_wait(self):
        self.install_all()
        ledger = self.workflows_dir / "orchestrate-21-24-r2" / "state.json"
        before = ledger.read_bytes()
        with open(self.store_root / "attempt-runs.lock", "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            child = subprocess.Popen(
                [sys.executable, str(SCRIPT), "migrate", "--repo-root", str(self.root),
                 "--apply"], env=self.cli_env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            with self.assertRaises(subprocess.TimeoutExpired):
                child.wait(timeout=3)
            self.assertEqual(ledger.read_bytes(), before)
        stdout, stderr = child.communicate(timeout=120)
        self.assertEqual(child.returncode, 0, stderr)
        self.assertEqual(self.rows(json.loads(stdout))["orchestrate-21-24-r2"]["verdict"],
                         "migrated")
```

Add `import fcntl`, `import subprocess`, `import sys` and `from .test_workflow_state import SCRIPT` to the module imports. Add the two fixture helpers to `MigrationFixtures`:
- `install_direct_pair()` — per D21: `run_id = self.acquire_direct(issue=41)["run_id"]`, drive it to a terminal and request `new_run` with the same calls Task 3's `install_terminal_legacy_direct` uses, read both minted ledgers, `install_legacy(first, "direct-41-000001")` and `install_legacy({**second, "prior_run": "direct-41-000001"}, "direct-41-000002")`, then delete both minted run directories and both `direct:41:<n>` index entries, so only the legacy ledgers name issue 41.
- `install_refusal_fixtures() -> dict[str, str]` — returns `{handle: expected reason}` after installing, all at schema 7 through `install_legacy` and then edited on disk:
  - `issue-14-test`: the `delivered_207()` ledger as is → `unknown_dialect`;
  - `orchestrate-90`: same, then its file's `schema_version` set to `9` → `unknown_schema`;
  - `orchestrate-91`: same with `prior_run: "orchestrate-90"` → `ambiguous_lineage`;
  - `direct-41-000002`: `install_direct_pair()`'s `direct-41-000002` ledger with `prior_run` rewritten to `"direct-42-000001"` (and `direct-41-000001` removed) → `ambiguous_lineage`;
  - `orchestrate-92`: the 207 ledger written as `self._as_legacy(state, 1, handle="orchestrate-92")` with `"extra": 1` added to each issue object, which the 1 → 7 chain refuses ("invalid legacy issue schema") as it refuses the retained schema-1 ledgers → `invalid_state`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_migration.py -k MigrationAcceptance`
Expected: FAIL — argparse rejects the `migrate` command (exit 2, `invalid choice: 'migrate'`).

- [ ] **Step 3: Write the minimal implementation**

Add `migration_row` and `migration_report` to `attempt_store.py` per the invariants, then the thin `command_migrate` and the `migrate` subparser to `workflow-state.py` exactly as Interfaces gives them. Print with the existing `print_json`. `migration_report`'s docstring states: read-only dry run first; apply binds each `migrate` ledger through the caller's locked no-op write on its handle; refusals are reported data; a missing workflows directory or a `StoreFault` raises. `StoreFault`'s docstring states it is a store that cannot be read, never a ledger refusal (D37). `command_migrate`'s one-line docstring states exit 0 with refusals as data and exit 2 on usage, an unreadable workflows directory or a store error.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_migration.py`
Expected: OK (every class so far).
Run: `just build` (timeout 3600 s; the package module changed) — succeeds.

- [ ] **Step 5: Commit**

Stage the three files, then `launch-commit … -- -m "feat(workflow-state): migrate dry run and apply (#337)"` with the session trailers. Then, on the new head, check the Invariants' two ceilings and the cumulative package: `review-package .agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.md 907dba234933e1457c2883530bf5f1b83e07a0ec "$(git rev-parse HEAD)" "$SCRATCH/review-task6.json" | artifact-budget validate-report --boundary producer --input -` reports `"state":"complete"`. A ceiling over its limit is a failed task: move logic from `workflow-state.py` into `attempt_store.py` until it holds.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64],"id":6,"records":[{"bounds":[{"added_lines":520,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":22000,"support":{"covers":["t5-11","t6-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t6-1","last_task":6,"owner":6,"path":"python/agent_tools/attempt_store.py"},{"bounds":[{"added_lines":216,"boundary":"attempt-identity","deleted_lines":96,"record_bytes":58000,"support":{"covers":["t5-1","t6-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t6-2","last_task":6,"owner":6,"path":"home/common/agent-skills/scripts/workflow-state.py"},{"bounds":[{"added_lines":630,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":35000,"support":{"covers":["t5-4","t6-3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t6-3","last_task":6,"owner":6,"path":"home/common/agent-skills/tests/test_attempt_migration.py"}]}}
```
