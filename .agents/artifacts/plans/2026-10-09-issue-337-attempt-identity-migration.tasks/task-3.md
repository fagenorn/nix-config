# Task 3: `direct-owner` on run transactions

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`command_direct_owner`, `_apply_one_issue_policy` and its three call sites)
- Modify: `home/common/agent-skills/tests/test_workflow_state.py` (harness only: new `direct_run_id`)
- Modify: `home/common/agent-skills/tests/test_attempt_migration.py` (new `DirectOwnerIdentityTest`)

**Interfaces:**
- Consumes (Task 1): `attempt_identity.direct_key`, `minted_plan`, `legacy_identity`, `identity_of`, `RunIdentity`, `classify`. (Task 2): `read_locked_state(...) -> LockedRead`, `commit_state(..., identity=)`, `validate_state(..., identity=)`, `mint_run`, `lookup_run`, `bound_identity`, `new_run_state(..., transaction_id=)`, `ensure_gitignore`, `LedgerRefused`; harness `install_legacy`, `store_root`, `tree_snapshot`, `init_run(creation_key=)`; `MigrationFixtures` in `test_attempt_migration.py`.
- Produces:
  - `_apply_one_issue_policy(*, issue: int, ...)` — a required `issue` keyword replaces the `run_dir.name` fallback (D17); `run_dir` stays only where the policy uses it for paths. `control` passes the issue it iterates, `direct-owner` passes `request["issue"]`. A ledger, tracker or worktree observation whose issue differs from `issue` is refused with the existing messages.
  - Harness `direct_run_id(issue: int, sequence: int) -> str` — `TransactionStore(self.store_root).lookup(attempt_identity.direct_key(issue, sequence))`, failing the test when `None`.

**Invariants:**
- The legacy scan of `direct-<issue>-*` names stays exactly as today (malformed entry → the same refusals; #339 removes it). For each scanned run, in sequence order, under its own `state.lock` (taken as today): `read = read_locked_state(..., repo_root=repo_root, ...)`; when `read.changed`, `commit_state(run_dir, state_path, read.state, run_id=run_id, identity=read.identity)` at once, still under that lock (D14). A refused legacy ledger refuses the whole call before any write to any other ledger and before any mint (spec § Migration transform).
- Index probe: after the scan, let `g` be the greatest scanned sequence (0 when none). For `s = g + 1, g + 2, …` read `lookup_run(repo_root, direct_key(issue, s))` until the first `None`. Each hit names `workflows/<id>`; if that directory has a `state.json`, lock and read it like a scanned run (identity from `bound_identity`) and append it as sequence `s`; if it has no ledger, stop: that entry is a reserved slot, not a retained run, and the probe ends there. The retained list is the union ordered by sequence; every later selection rule (nonterminal count, "below a newer terminal", greatest, selected) reads only that order, which is unchanged.
- The direct-owner `set(state["issues"]) != {str(issue)}` check applies to every retained run, scanned or probed.
- New run handle (D17): when the call will need a new run (`selected is None`, or `request["new_run"]`), compute `sequence = greatest + 1` (or 1) and `prior_run = greatest`'s handle (or `None`) exactly as today, then `run_id = mint_run(repo_root, minted_plan(identity=RunIdentity("direct", issue, sequence), prior_run=prior_run, caller_key=None))` before the policy runs. `run_dir = workflows_dir / run_id`. The sequence cap (`>= 999999` → `"direct run sequence exhausted"`) is checked before minting. The mint lock is taken while `.direct-<issue>.lock` and the retained `state.lock`s are held, which is the D9 order.
- Allocation (`spawn`/`resume`/`retry`/`refuse`/`recover` with no state) creates `workflows/<run_id>` and its `state.lock` exactly as today and writes `new_run_state(run_id=run_id, transaction_id=run_id, ..., prior_run=prior_run)`; its identity is `RunIdentity("direct", issue, sequence)`.
- An `observe` or `contract` reply that today names the unallocated new run's `run_id` names the minted `rel_` handle; a repeated call with the same facts mints nothing new (`create` deduplicates on `direct:<issue>:<sequence>` with the identical subject).
- `commit_state` and `validate_state` calls in `command_direct_owner` pass the selected run's identity (`read.identity`, or the new run's).
- `select_phase_action` for a minted direct run takes the direct branch (D15), because its identity is direct.

- [ ] **Step 1: Write the failing tests**

Append to `home/common/agent-skills/tests/test_attempt_migration.py`. Drive direct-owner through the existing harness helpers: `acquire_direct(issue=...)` (observe → observe → spawn), `direct_owner(**fields)`, `direct_owner_raw(..., ok=False)` and `control_raw(ok=False)`.

```python
class DirectOwnerIdentityTest(MigrationFixtures, unittest.TestCase):
    def first_direct_run(self, issue=41):
        return self.acquire_direct(issue=issue)["run_id"]

    def test_a_first_direct_run_is_minted_and_named_by_its_transaction(self):
        run_id = self.first_direct_run()
        self.assertRegex(run_id, CORE)
        self.assertEqual(self.direct_run_id(41, 1), run_id)
        self.run_id = run_id
        state = self.read_state()
        self.assertEqual((state["transaction_id"], state["prior_run"]), (run_id, None))
        subject = self.store().load(run_id).subject
        self.assertEqual((subject["kind"], subject["issue"], subject["sequence"],
                          subject["alias"]), ("direct", 41, 1, None))
        self.assertFalse(any(p.name.startswith("direct-41-")
                             for p in self.workflows_dir.iterdir()))

    def test_a_new_run_after_a_legacy_terminal_links_the_legacy_handle(self):
        self.install_terminal_legacy_direct("direct-41-000001")
        reply = self.direct_owner(**self.new_run_fields(41))
        self.assertRegex(reply["run_id"], CORE)
        self.run_id = reply["run_id"]
        self.assertEqual(self.read_state()["prior_run"], "direct-41-000001")
        self.assertEqual(self.store().load(reply["run_id"]).subject["sequence"], 2)
        legacy = json.loads((self.workflows_dir / "direct-41-000001" / "state.json")
                            .read_text())
        self.assertEqual(legacy["schema_version"], 8)  # bound and committed (D14)
        self.assertEqual(self.store().lookup(ai.direct_key(41, 1)),
                         legacy["transaction_id"])

    def test_a_reserved_slot_without_a_ledger_is_reused(self):
        self.install_terminal_legacy_direct("direct-41-000001")
        plan = ai.minted_plan(identity=ai.RunIdentity("direct", 41, 2),
                              prior_run="direct-41-000001", caller_key=None)
        self.store_root.mkdir(parents=True, exist_ok=True)
        reserved = self.store().create(plan.creation_key, plan.subject_json(),
                                       **ai.creation_arguments(plan)).transaction_id
        reply = self.direct_owner(**self.new_run_fields(41))
        self.assertEqual(reply["run_id"], reserved)
        self.assertIsNone(self.store().lookup(ai.direct_key(41, 3)))

    def test_a_refused_legacy_ledger_refuses_the_call_and_mints_nothing(self):
        self.init_run()
        state = {**self.read_state(), "prior_run": "direct-42-000001"}
        self.install_legacy(state, "direct-41-000002")
        ledger = self.workflows_dir / "direct-41-000002" / "state.json"
        before = ledger.read_bytes()
        refused = self.direct_owner_raw(issue=41, ok=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("ambiguous_lineage", refused.stderr)
        self.assertEqual(ledger.read_bytes(), before)
        for sequence in (1, 2, 3):
            self.assertIsNone(self.store().lookup(ai.direct_key(41, sequence)))

    def test_control_refuses_a_minted_direct_run_under_its_lock(self):
        run_id = self.first_direct_run()
        self.run_id = run_id
        before = self.tree_snapshot()
        refused = self.control_raw(ok=False)
        self.assertIn("reserved for direct-owner", refused.stderr)
        self.assertEqual(self.tree_snapshot(), before)
```

Define two helpers in the same class from existing harness calls: `install_terminal_legacy_direct(handle)` — `run_id = self.first_direct_run(41)`, then drive it to a terminal with the same calls an existing direct-owner `new_run=True` test in `test_workflow_state.py` uses before its `new_run` request (grep `new_run=True`), read the state, `install_legacy(state, handle)`, then delete `workflows/<run_id>` and the `direct:41:1` index entry (`creation-keys/<sha256 of the key>.json`) so only the legacy ledger names sequence 1; and `new_run_fields(issue)` — the request fields of that same test's `new_run=True` call with `issue` substituted. Add no new request shape.

Harness: add `direct_run_id` (Interfaces), and change `acquire_direct`'s expected second-observe `"run_id": f"direct-{issue}-000001"` to `self.direct_run_id(issue, 1)` — the one harness expectation D17 changes.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_migration.py -k DirectOwnerIdentity`
Expected: FAIL — the first run's `run_id` is `direct-41-000001`, not a `rel_` id; `direct_run_id` finds no index entry.

- [ ] **Step 3: Write the minimal implementation**

Rewrite the scan/probe/handle part of `command_direct_owner` per the invariants; keep every selection rule and every response construction unchanged except for the handle value. Replace `_apply_one_issue_policy`'s `DIRECT_RUN_ID_PATTERN.fullmatch(run_dir.name)` fallback with the required `issue` argument and update its docstring to say the issue is the caller's. Update `new_run_state`'s docstring sentence "The link always points at a lower direct sequence" to say the predecessor is the handle of the issue's previous direct run (a legacy `direct-` id or a `rel_` id), as recorded.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_attempt_migration.py`
Expected: OK (Task 2's classes and this one).
Run: `grep -n 'fullmatch(run_dir.name)' home/common/agent-skills/scripts/workflow-state.py; test $? -eq 1`
Expected: exit 0 (no match).

- [ ] **Step 5: Commit**

Stage the three files, then `launch-commit … -- -m "feat(workflow-state): direct-owner mints direct runs as run transactions (#337)"` with the session trailers.
