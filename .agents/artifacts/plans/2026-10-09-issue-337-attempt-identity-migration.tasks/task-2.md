# Task 2: Ledger schema 8 — bind on locked reads, check on unlocked reads, `init-run` minting, identity-based direct reservation

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py`
- Modify: `home/common/agent-skills/scripts/workflow_delivery.py` (`DeliveryRuntime.migrate` only)
- Modify: `python/agent_tools/transaction_core.py` (module docstring sentence only: "No command and no caller until #125." becomes "Its first caller is `workflow-state`, which mints and binds attempt run transactions (#337).")
- Modify: `python/agent_tools/launch_scope.py` (`SAFE_SEGMENT` only, D18)
- Modify: `home/common/agent-skills/tests/test_workflow_state.py` (harness only: `LifecycleHarness.init_run`, `_as_legacy`, new `install_legacy`, `store_root`, `tree_snapshot`)
- Create: `home/common/agent-skills/tests/test_attempt_migration.py`
- Modify: `tests/test_launch_scope.py` (one new test)
- Modify: `justfile` (add `home/common/agent-skills/tests/test_attempt_migration.py` to `agent-workflow-tests`, right after `test_workflow_state.py`)

**Interfaces:**
- Consumes (Task 1): `TransactionStore.lookup`, and from `agent_tools.attempt_identity`: `RunIdentity`, `RunPlan`, `MigrationRefused`, `classify`, `legacy_identity`, `plan_migration`, `minted_plan`, `schema_refusal`, `subject_violation`, `identity_of`, `subject_handle`, `prior_run_violation`, `creation_arguments`.
- Produces (in `workflow-state.py`; Tasks 3, 5, 6 rely on these names):
  - `SCHEMA_VERSION = 8`; `STATE_FIELDS` gains `"transaction_id"`.
  - `class LedgerRefused(WorkflowError)` with `reason: str` (a closed reason); message `"workflow state refused: <reason>: <detail>"`.
  - `class LockedRead(NamedTuple): state: dict; identity: RunIdentity; changed: bool`.
  - `attempt_store_root(repo_root: Path) -> Path` = `repo_root / ".superpowers" / "attempt-transactions"` (pure path).
  - `ensure_attempt_store(repo_root: Path) -> Path` — creates the root (non-symlink dir) and its `*` `.gitignore`; write paths only.
  - `mint_run(repo_root: Path, plan: RunPlan) -> str` — `ensure_attempt_store`, open `<store>/attempt-runs.lock` with `open_stable_lock(..., "attempt mint lock")`, blocking `fcntl.flock(LOCK_EX)`, `TransactionStore(store).create(plan.creation_key, plan.subject_json(), **creation_arguments(plan))`, close the lock, return the id. Any `TransactionError` becomes `WorkflowError("run transaction store: <error>")` (D9).
  - `lookup_run(repo_root: Path, creation_key: str) -> str | None` — `None` when the store root is absent; never creates it.
  - `bound_identity(repo_root: Path, state: dict, run_id: str) -> RunIdentity` — lock-free `load` of `state["transaction_id"]`; refuses (`WorkflowError`) a missing store root, an unknown or invalid transaction, a subject failing `subject_violation`, or `subject_handle(subject, id) != run_id`. Creates nothing.
  - `read_locked_state(state_path, run_id, *, repo_root: Path, migration_contracts) -> LockedRead` (replaces the tuple return).
  - `read_state_unlocked(state_path: Path, run_id: str, *, repo_root: Path) -> dict` (keyword added; every call site passes it).
  - `validate_state(value, *, run_id: str, identity: RunIdentity, schema_version: int = SCHEMA_VERSION) -> dict`; `validate_attempt(..., direct: bool)` replaces its `run_id` argument; `select_phase_action(*, direct: bool, ...)` replaces `run_id`; `commit_state(run_dir, state_path, state, *, run_id, identity)` (D20).
  - `transact(repo_root, run_id, mutation, *, allow_missing=False, migration_contracts=None, refuse_direct=False, new_identity: RunIdentity | None = None, with_identity=False)`.
  - `new_run_state(*, run_id, transaction_id, now, issues, prior_run=None)`.
  - `init-run` takes exactly one of `--run-id` and `--creation-key` (argparse mutually exclusive, required).
- Produces (harness, `test_workflow_state.py`): `init_run(*, now=DEFAULT_NOW, creation_key="lifecycle-harness")` runs `init-run --creation-key <key>` and sets `self.run_id` to the reply's `run_id`; `_as_legacy(state, version, *, keep_delivery=False, handle=None)` also drops `transaction_id` and, given `handle`, sets `run_id` to it; `install_legacy(state, handle, version=7)` writes `_as_legacy(state, version, handle=handle)` to `workflows/<handle>/state.json` beside an empty `state.lock` (creating the directory, as a retained ledger has both) and sets `self.run_id = handle`; `store_root` property; `tree_snapshot()` returning `{relative path: bytes or "<dir>"}` under `<root>/.superpowers`.

**Invariants:**
- Locked read order (spec § Migration transform; D14): `schema_refusal` → (schema 8) shape + `bound_identity` + `validate_state` → (schema ≤ 7) `DeliveryRuntime.migrate` to 7 (failure → `invalid_state`) → `validate_state(..., identity=legacy_identity(run_id) or orchestrated-placeholder, schema_version=7)` (failure → `invalid_state`) → `plan_migration` (→ its reason) → `mint_run` → set `transaction_id`, `schema_version: 8` → `validate_state` at 8. For an unknown dialect, validate the schema-7 candidate with `RunIdentity("orchestrated", None, None)` so the plan's `unknown_dialect` is the reason that surfaces. Every refusal raises `LedgerRefused` before any ledger write; a refused ledger gets no index entry.
- `transact` commits when the mutation changed the state **or** the read bound/migrated it (D14), refusing first when `refuse_direct and identity.direct` (`"direct run identities are reserved for direct-owner"`).
- Lock order: `state.lock` → mint lock → core locks; `init-run --creation-key` mints before it takes the ledger's `state.lock` (D9).
- Unlocked reads (`check-launch`, `current-launch`, `owner-liveness`, `mark-progress`'s pre-read, `resume-pack`, `check-worker`, the #193 lookup) create no store root, lock or directory: schema ≤ 7 is checked on a detached copy through the chain, schema-7 validation and `plan_migration`; schema 8 through `bound_identity`. The stored document is returned unchanged.
- `DeliveryRuntime.migrate` passes a schema-8 document through as a deep copy (loop condition `not in {7, 8}`); versions outside 1–8 still raise.
- Schema-8 `validate_state` adds: `transaction_id` passes `is_id`; a `core`-dialect `run_id` equals `transaction_id`; `prior_run_violation(identity, prior_run, run_id=run_id)` is `None`. Schema-7 validation keeps today's `prior_run` rule.
- D15: `select_phase_action` branches on `direct`. `transact` gains `with_identity: bool = False`; when true it calls `mutation(state, identity)` with the `LockedRead.identity` (or `new_identity` for a missing state), otherwise `mutation(state)` as today. `command_progress` uses it to compute its action, and its handoff-path check, inside the mutation. The pre-lock `reject_reserved_direct_run_id` name check stays for `control` and `init-run --run-id`; `transact(..., refuse_direct=True)` adds the identity check under the lock.
- `init-run --run-id X`: `reject_reserved_direct_run_id(X)`; if `<root>/.superpowers/workflows/X/state.json` is not a regular file, raise `WorkflowError("workflow run 'X' is not initialized")` before calling anything that creates a directory; else `transact(..., refuse_direct=True)` with a no-op mutation (migrates on write).
- `init-run --creation-key K`: `plan = minted_plan(identity=RunIdentity("orchestrated", None, None), prior_run=None, caller_key=K)` (`ValueError` → `WorkflowError("invalid creation key")`, exit 2, nothing created); `tx = mint_run(root, plan)`; `transact(root, tx, initialize, allow_missing=True, new_identity=...)` where `initialize` builds `new_run_state(run_id=tx, transaction_id=tx, ...)` only when missing. Same K → same `run_id`, no second ledger.
- `launch_scope.SAFE_SEGMENT = re.compile(r"[A-Za-z0-9_.:-]+")` (D18); `.` and `..` stay refused.

- [ ] **Step 1: Write the failing tests**

Harness edits first (they are the harness, not assertions). Then create `home/common/agent-skills/tests/test_attempt_migration.py`:

```python
"""Attempt run identity on workflow-state ledgers (#337), driven through the CLI from source.

Run: just agent-workflow-tests
"""

import json
import re
import unittest

from agent_tools import attempt_identity as ai
from agent_tools.transaction_core import TransactionStore

from .test_delivered_control import DeliveredControlHarness
from .test_workflow_state import DEFAULT_NOW

CORE = re.compile(
    r"^rel_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class MigrationFixtures(DeliveredControlHarness):
    """Legacy-dialect ledgers shaped like the retained ones (D21)."""

    def store(self):
        return TransactionStore(self.store_root)

    def delivered_207(self):
        self.init_run(creation_key="fixture-207")
        self.deliver_through_remainder()
        return self.read_state()

    def install_orchestrated(self, handle):
        source = self.delivered_207()
        self.install_legacy(source, handle)
        return source

    def run_cli_json(self, *args, ok=True):
        completed = self.run_cli(*args, ok=ok)
        return completed, (json.loads(completed.stdout) if ok else None)


class InitRunMintTest(MigrationFixtures, unittest.TestCase):
    def test_creation_key_mints_one_core_run(self):
        args = ("init-run", "--repo-root", self.root, "--creation-key", "k-337", "--now",
                DEFAULT_NOW)
        first = json.loads(self.run_cli(*args).stdout)
        second = json.loads(self.run_cli(*args).stdout)
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertRegex(first["run_id"], CORE)
        self.run_id = first["run_id"]
        state = self.read_state()
        self.assertEqual((state["schema_version"], state["transaction_id"]), (8, first["run_id"]))
        self.assertEqual(self.store().lookup(ai.run_key("k-337")), first["run_id"])
        runs = [p.name for p in self.workflows_dir.iterdir() if not p.name.startswith(".")]
        self.assertEqual(runs, [first["run_id"]])
        self.assertEqual((self.store_root / ".gitignore").read_text(), "*\n")

    def test_run_id_only_rebootstraps_and_never_creates(self):
        self.init_run()
        before = self.tree_snapshot()
        refused = self.run_cli("init-run", "--repo-root", self.root, "--run-id", "new-x",
                               ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(self.tree_snapshot(), before)
        again = json.loads(self.run_cli("init-run", "--repo-root", self.root, "--run-id",
                                        self.run_id).stdout)
        self.assertEqual(again["run_id"], self.run_id)
        self.assertEqual(self.tree_snapshot(), before)

    def test_bad_or_doubled_arguments_are_usage_errors(self):
        for extra in (("--creation-key", "-bad"), ("--creation-key", "a b"),
                      ("--creation-key", "k", "--run-id", "x"), ()):
            with self.subTest(extra=extra):
                refused = self.run_cli("init-run", "--repo-root", self.root, *extra, ok=False)
                self.assertEqual(refused.returncode, 2)
                self.assertFalse((self.root / ".superpowers").exists())


class MigrateOnWriteTest(MigrationFixtures, unittest.TestCase):
    def test_a_locked_write_binds_a_legacy_ledger_under_its_handle(self):
        self.install_orchestrated("orchestrate-21-24-r2")
        # A no-op locked command: its only write is the migration (D14).
        self.run_cli("init-run", "--repo-root", self.root, "--run-id", self.run_id)
        state = self.read_state()
        self.assertEqual((state["schema_version"], state["run_id"]), (8, "orchestrate-21-24-r2"))
        key = ai.legacy_key("orchestrate-21-24-r2")
        self.assertEqual(self.store().lookup(key), state["transaction_id"])
        subject = self.store().load(state["transaction_id"]).subject
        self.assertEqual((subject["kind"], subject["prior_run"], subject["alias"]["retry"]),
                         ("orchestrated", None, 2))

    def test_unlocked_reads_check_without_writing(self):
        self.install_orchestrated("orchestrate-21-24-r2")
        before = self.tree_snapshot()
        reply = self.run_cli("check-launch", "--repo-root", self.root, "--run-id", self.run_id,
                             "--action-id", "207:r1:1")
        self.assertEqual(self.tree_snapshot(), before)
        self.assertIn('"action_id":"207:r1:1"', reply.stdout)

    def test_refused_ledgers_keep_their_bytes_and_get_no_index_entry(self):
        source = self.delivered_207()
        cases = {"issue-14-test": "unknown_dialect",
                 "orchestrate-21": "ambiguous_lineage"}
        for handle, reason in cases.items():
            with self.subTest(handle=handle):
                state = dict(source)
                if handle == "orchestrate-21":
                    state = {**source, "prior_run": "orchestrate-20"}
                self.install_legacy(state, handle)
                before = self.tree_snapshot()
                for refused in (
                        self.run_cli("check-launch", "--repo-root", self.root, "--run-id",
                                     handle, "--action-id", "207:r1:1", ok=False),
                        self.progress(issue=207, ok=False)):
                    self.assertEqual(refused.returncode, 2)
                    self.assertIn(reason, refused.stderr)
                self.assertEqual(self.tree_snapshot(), before)

    def test_a_schema_8_ledger_whose_binding_breaks_is_refused(self):
        self.init_run()
        state = self.read_state()
        other = json.loads(self.run_cli("init-run", "--repo-root", self.root,
                                        "--creation-key", "other").stdout)["run_id"]
        self.write_state({**state, "transaction_id": other})
        before = self.tree_snapshot()
        refused = self.run_cli("check-launch", "--repo-root", self.root, "--run-id",
                               self.run_id, "--action-id", "1:1:1", ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(self.tree_snapshot(), before)


class DirectReservationTest(MigrationFixtures, unittest.TestCase):
    def test_control_and_rebootstrap_refuse_a_direct_identity_by_identity(self):
        # Task 3 adds the minted (rel_) direct case; here the legacy name is the identity.
        self.init_run()
        self.install_legacy(self.read_state(), "direct-14-000001")
        before = self.tree_snapshot()
        refused = self.run_cli("init-run", "--repo-root", self.root, "--run-id",
                               "direct-14-000001", ok=False)
        self.assertIn("reserved for direct-owner", refused.stderr)
        self.assertEqual(self.tree_snapshot(), before)
```

Add to `tests/test_launch_scope.py`, inside the class that holds `test_unsafe_ids_and_usage_errors_exit_two_and_delete_nothing`:

```python
    def test_a_minted_run_handle_is_a_safe_segment(self):
        handle = "rel_0190f0e0-0000-7000-8000-000000000000"
        self.assertTrue(launch_scope.is_safe_segment(handle))
        for unsafe in (".", "..", "a/b", ""):
            self.assertFalse(launch_scope.is_safe_segment(unsafe))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_migration.py tests/test_launch_scope.py -k InitRunMint -k MigrateOnWrite -k DirectReservation -k minted_run_handle`
Expected: FAIL — `init-run` rejects `--creation-key` (argparse exit 2 where a reply is expected), the legacy ledger stays at schema 7, and `is_safe_segment` returns False for the `rel_` handle.

- [ ] **Step 3: Write the minimal implementation**

Implement the interfaces above in `workflow-state.py`. Non-obvious points:
- Map every `attempt_identity.MigrationRefused` to `LedgerRefused(error.reason, ...)`; map a chain/validation failure of a schema ≤ 7 document to `LedgerRefused("invalid_state", ...)`; map `schema_refusal` to `LedgerRefused("unknown_schema", ...)`. `main` already turns a `WorkflowError` into exit 2 with the message on stderr.
- `ensure_gitignore` gains a `label` parameter (default `"workflows .gitignore"`) so `ensure_attempt_store` reuses it.
- Thread `identity` through every `commit_state`, `validate_state` and `validate_attempt` call site (18 sites today). In `command_direct_owner` (rewritten by Task 3) pass `legacy_identity(run_id)` for now so the module stays importable and the old direct path keeps its behaviour until Task 3.
- `_installed_delivery` and every `read_state_unlocked` caller pass `repo_root`.
- Update `read_state_unlocked`'s docstring to say what it now does: schemas 1–7 are checked on a detached copy through the chain and the migration plan, schema 8 through a lock-free load of the bound transaction; no store, lock or directory is created.
- Update `new_run_state`'s docstring: the run's `transaction_id` is its core run transaction; for a minted run it equals `run_id`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_migration.py tests/test_attempt_identity.py`
Expected: OK. Then `PYTHONPATH="$PWD/python" python3 -m unittest tests/test_launch_scope.py -k minted_run_handle -k unsafe_ids` — OK.
Then confirm the declared red window is the expected one, not a crash: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py 2>&1 | tail -3` ends with a `FAILED (failures=…, errors=…)` line, not an import error. Task 4 turns it green.

- [ ] **Step 5: Commit**

Stage exactly the eight files above, then `launch-commit … -- -m "feat(workflow-state): ledger schema 8 bound to a run transaction (#337)"` with the session trailers.
