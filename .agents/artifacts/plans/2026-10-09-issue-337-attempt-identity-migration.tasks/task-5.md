# Task 5: `workflow-state migrate` — dry run, apply and report

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (new `command_migrate`, its parser entry, and the row builder)
- Modify: `home/common/agent-skills/tests/test_attempt_migration.py` (new `MigrationAcceptanceTest`)

**Interfaces:**
- Consumes (Task 1): `attempt_identity.schema_refusal`, `classify`, `legacy_alias`, `legacy_identity`, `plan_migration`, `direct_key`, `legacy_key`, `report`, `REPORT_ROW_FIELDS`, `MigrationRefused`, `RunIdentity`; `print_json` (workflow-state's existing sorted-key, compact rendering) for output. (Task 2): `read_state_unlocked`-style detached checks, `bound_identity`, `lookup_run`, `transact`, `LedgerRefused` (with `.reason`), `attempt_store_root`. (Tasks 2–3 harness / `MigrationFixtures`): `install_legacy`, `install_orchestrated`, `delivered_207`, `tree_snapshot`, `store`, `store_root`, `direct_run_id`, `acquire_direct`.
- Produces:
  - CLI: `workflow-state migrate --repo-root <root> [--apply]`. Stdout: one canonical JSON document (sorted keys, compact separators, trailing newline) — `attempt_identity.report(mode, rows)`. Exit 0 whenever every ledger got a verdict; exit 2 on usage, a missing or unreadable `<root>/.superpowers/workflows`, or a store error (D8).
  - `migration_row(repo_root: Path, ledger: str, *, migrated: bool = False) -> dict` in `workflow-state.py` — one read-only row (below).

**Invariants:**
- **Inventory:** the non-dot entries of `<root>/.superpowers/workflows` that are non-symlink directories holding a regular `state.json`, in name order. Nothing else is read.
- **Row (read-only; never creates the store root, a lock or a directory):** parse the JSON (unparseable → `invalid_state`); `schema_refusal` → `unknown_schema`; `ledger` is the directory name; `run_id`, `schema_version`, `prior_run` and `issues` (sorted ints of the `issues` keys) are copied from the document when present and well-typed, else `null`; `dialect = classify(run_id)`; `alias = legacy_alias(run_id)` when the dialect is a legacy one, else the bound subject's `alias` for a schema-8 ledger, else `null`.
  - recorded `run_id != ledger` → `refused` / `location_mismatch` (checked before the plan).
  - schema 8 → `bound_identity` and `validate_state` succeed → `current`, `transaction_id` = recorded; failure → `refused` / `invalid_state`.
  - schema ≤ 7 → chain to 7 with empty migration contracts (D20) and schema-7 validation (failure → `invalid_state`), then `plan_migration` (refusal → its reason) → `migrate`; `transaction_id = lookup_run(root, plan.creation_key)` (`null` when unindexed or the store is absent).
  - `prior_transaction_id`: `null` when `prior_run` is `null`; the id itself when `prior_run` is `core`; `lookup_run(root, direct_key(issue, seq))` for a `direct` prior; `lookup_run(root, legacy_key(prior_run))` otherwise.
  - `reason` is `null` unless the verdict is `refused`.
- **Apply:** compute the dry-run rows; for each `migrate` row, call `transact(root, ledger, lambda state: (None, False))` so the bind half runs on bytes re-read under that ledger's lock; on `LedgerRefused` record `refused` with its `reason` (the advisory dry-run verdict loses). Then recompute the row with `migrated=True`, which turns a now-`current` row into `migrated`. `current` and `refused` rows are never passed to `transact` (no lock file is created for them). Report `mode: "apply"`.
- Idempotent: a second apply reports zero `migrated` and leaves the tree snapshot unchanged; two dry runs print identical bytes.
- No clock value appears in the report.

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
        self.assertTrue(all(row["verdict"] in ("current", "refused")
                            for row in again["ledgers"]))
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

Add `command_migrate` and `migration_row` per the invariants, with the subparser `migrate` (`--repo-root` required, `--apply` flag). Print with the existing `print_json`. Its docstring states: read-only dry run first; apply binds each `migrate` ledger by a no-op locked transaction on its handle; refusals are reported data with exit 0; exit 2 on usage, an unreadable workflows directory or a store error.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_migration.py`
Expected: OK (every class so far).

- [ ] **Step 5: Commit**

Stage the two files, then `launch-commit … -- -m "feat(workflow-state): migrate dry run and apply (#337)"` with the session trailers.
