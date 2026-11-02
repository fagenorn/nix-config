# Task 2: Legacy-install, init-run and finish helpers and their call sites

Issue: https://github.com/fagenorn/nix-config/issues/346. Spec: `.agents/artifacts/specs/2026-10-10-issue-346-attempt-identity-test-harness-prep-design.md`. Reference commit: `6ae38b0c`; base `901da282`. "Branch L<n>" means line `<n>` of `git show 6ae38b0c:home/common/agent-skills/tests/test_workflow_state.py`; "hunk -<m>" means the header `@@ -<m>…` of `git diff -U0 901da282 6ae38b0c -- home/common/agent-skills/tests/test_workflow_state.py`. Task 1 has already landed `direct_run_id`, `run_dirs` and `mint_direct_ledger`.

**Files:**
- Modify: `home/common/agent-skills/tests/test_workflow_state.py`

**Interfaces:**
- Consumes: `LifecycleHarness.write_state(state)`, `workflows_dir`, `state_path`, `run_cli(*args, ok=True)`, `_legacy_bootstrap(item)` (all unchanged).
- Produces on `LifecycleHarness` (branch positions):
  - `_as_legacy(state, version, *, keep_delivery=False, handle=None)` (static): hunks -91 and -93 verbatim — `if version < 8: state.pop("transaction_id", None)` and `if handle is not None: state["run_id"] = handle`, right after `state["schema_version"] = version`.
  - `store_root` property and `tree_snapshot()`: branch L175–183 verbatim.
  - `install_legacy(self, state, handle, version=7)`: branch L185–193 body verbatim (run dir `mkdir(parents=True, exist_ok=True)`, workflows `.gitignore` `"*\n"`, empty `state.lock`, `self.run_id = handle`, `self.write_state(self._as_legacy(state, version, handle=handle))`), docstring below.
  - `assert_bound(self, state)`: `self.assertEqual(state["schema_version"], 7)` only (D6).
  - `init_run(self, *, now=DEFAULT_NOW)`: body below (D2).
  - `_legacy_finish_input(self, stored)`: `return self._as_legacy(stored, 2)`, placed at branch L363.
  - Task 4 relies on none of these except through `LedgerClockTest`'s inherited `init_run`.

**Invariants:**
- `init-run` keeps receiving `--run-id self.run_id`; its reply's `run_id` equals the id sent, so the read-back is neutral (D2, D3).
- Product-produced ids keep today's values; only the test-chosen handles the issue names change (`orchestrate-<issue>`, `clock-seam`, `empty-override`), and every such test reads the id back (D3).
- An `assert_bound` call lands only where the ledger is schema 7 on main; a branch `schema_version == 8` / `transaction_id` expectation never lands (D6).
- No assertion is removed or loosened; a branch replacement that is stricter (e.g. `glob("*/state.json") == []` for `not state_path.exists()`) lands only if it passes on main, else the site stays in #337 and the report names it (D7).
- No `TransactionStore`, `attempt_identity`, `attempt_store`, `ORCHESTRATED`, `LedgerRefused`, `--creation-key`, `identity=`, `schema_version=` argument or `copytree` lands.

- [ ] **Step 1: Route one call site and watch it fail**

Apply hunk -326 (branch L376): `finish` writes `self.write_state(self._legacy_finish_input(json.loads(current_bytes)))`.

Run: `launch-scope exec … -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k finish` (timeout 1800 s)
Expected: errors — `AttributeError: … '_legacy_finish_input'`.

- [ ] **Step 2: Add the helpers**

```python
    def install_legacy(self, state, handle, version=7):
        """A retained legacy ledger: `state` as schema `version` under `handle`, beside its
        empty `state.lock` and the workflows `.gitignore`."""

    def assert_bound(self, state):
        """`state` is at the current schema, 7."""
        self.assertEqual(state["schema_version"], 7)

    def init_run(self, *, now=DEFAULT_NOW):
        """`init-run` of `self.run_id`; reads the run id back from the reply."""
        which = ("--run-id", self.run_id)
        completed = self.run_cli("init-run", "--repo-root", self.root, *which,
                                 *(() if now is None else ("--now", now)))
        value = json.loads(completed.stdout)
        self.run_id = value["run_id"]
        return {"interface_version": 1, "run_id": value["run_id"],
                "requirements": [self._legacy_bootstrap(item)
                                 for item in value["requirements"]]}

    def _legacy_finish_input(self, stored):
        """The ledger the legacy `finish` runs on: `stored` as schema 2."""
        return self._as_legacy(stored, 2)
```

Plus `_as_legacy`'s `handle` parameter and two branches, `store_root` and `tree_snapshot`, as listed under Interfaces.

- [ ] **Step 3: Route the family's call sites**

- `_legacy_finish_input`: hunk -951 (L1030, `concurrent_finish`).
- Prior-schema reconcile helper: hunk -927 (L1009): `if prior_schema: self.install_legacy(state, f"orchestrate-{issue}", 2)` / `else: self.write_state(state)`.
- Schema upgrade and hybrid tests: hunks -5474 (+ -5480 `assert_bound(upgraded)`), -5510, -5517 (`assert_bound(value)` replaces `assertEqual(value["schema_version"], 7)`), -5565, -5586, -5614 (its first two lines only: `install_legacy(...)` and `_as_legacy(..., handle=self.run_id)`; the `LedgerRefused` lines of -5616/-5618 stay).
- `WorkerRegistryTest`: -6536, -6543. `ProgressMarkerSchemaTest`: -6634, -6648. `LaneSchemaTest`: -6736, -6750, -6754. `ProgressMarkerTest`: -7217.
- `assert_bound` at hunk -2489: keep `self.assertEqual(state["schema_version"], 7)` and add `self.assert_bound(state)` after it (D6).
- Read-back: stable-lock/state test hunks -3644/-3649/-3653 (`initialized = self.run_cli(... "--run-id", f"stable-{stable_name.replace('.', '-')}", ...)`, then `run_id = json.loads(initialized.stdout)["run_id"]`); reserved-ids test hunks -4412/-4414/-4416 (`--run-id`, `"direct-73-000000"`, then `zero_id = json.loads(initialized.stdout)["run_id"]`) and -4437/-4438 (`run_id = owner["run_id"]`).
- Phase-gate replies: hunks -2898 and -2946 use `"run_id": self.run_id` (the ledger expectations of -2886/-2935 stay).
- `LedgerClockSeamTest`: hunk -8222 with `"--run-id", key` in place of `"--creation-key", key`; hunks -8234, -8245, -8251, -8253.
- Leave in #337: hunks -6427, -6620, -6645, -6711, -6746, -7224 (schema-8 literals), -5494, -5498, -5543, -5562, -5520, -5616, -5618, -992, -3609, -3627, -3813 and every `--creation-key` key the issue does not name.

- [ ] **Step 4: Verify**

Run: `launch-scope exec … -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py` (timeout 1800 s)
Expected: `OK`, skip count as base.

D7 proxy and budget (any `FAIL` line, or a byte count above 60000, fails the task):

```bash
BASE=$(git merge-base origin/main HEAD); f=home/common/agent-skills/tests/test_workflow_state.py
for spec in 'eq:^[[:space:]]*def test_' 'ge:self\.assert|\.assert_called' 'eq:skip'; do
  op=${spec%%:*}; pat=${spec#*:}
  a=$(git show "$BASE:$f" | grep -cE "$pat" || true); b=$(grep -cE "$pat" "$f" || true)
  if { [ "$op" = eq ] && [ "$a" != "$b" ]; } || { [ "$op" = ge ] && [ "$b" -lt "$a" ]; }; then
    echo "FAIL $pat $a -> $b"; else echo "ok $pat $a -> $b"; fi
done
n=$(git diff -U10 "$BASE" -- "$f" | wc -c); echo "WS -U10 $n"; [ "$n" -le 60000 ] || echo FAIL
if git diff "$BASE" -- "$f" | grep -vF 'state.pop("transaction_id", None)' | grep -E '^\+.*(TransactionStore|attempt_identity|attempt_store|ORCHESTRATED|LedgerRefused|creation-key|transaction_id|copytree)'; then echo FAIL; fi
```

Over 60000: apply D5 — revert pure literal-to-`direct_run_id` sites from Task 1 (smallest value per byte first, never a helper definition) until it fits, and list each reverted site in the report for the PR body.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_workflow_state.py
launch-commit … -- -m "test(workflow-state): route legacy installs and init-run read-back through harness helpers (#346)" -m "<trailers>"
```
