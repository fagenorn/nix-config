# Task 3: Builder run labels and contract-lifecycle routing

Issue: https://github.com/fagenorn/nix-config/issues/346. Spec: `.agents/artifacts/specs/2026-10-10-issue-346-attempt-identity-test-harness-prep-design.md`. Reference commit: `6ae38b0c`; base `901da282`. "Branch L<n>" means line `<n>` of `git show 6ae38b0c:home/common/agent-skills/tests/test_delivery_workflow.py`; "hunk -<m>" means the header `@@ -<m>…` of `git diff -U0 901da282 6ae38b0c -- home/common/agent-skills/tests/test_delivery_workflow.py`.

**Files:**
- Modify: `home/common/agent-skills/tests/test_delivery_workflow.py` (`BuilderHarness`, `HelperInputTest`, `ContractLifecycleTest`)

**Interfaces:**
- Consumes: `BuilderHarness.cli(*args, stdin=None, ok=True)`, `BuilderHarness.root`, module constant `NOW` (unchanged).
- Produces on `BuilderHarness`, placed at branch L1587–1601 (hunk -1565):
  - `runs` property: `self.__dict__.setdefault("_runs", {})`, docstring "The run id each test-local label names." (branch verbatim).
  - `run_of(self, label) -> str`: `return self.runs.get(label, label)` (verbatim).
  - `mint_run(self, key, *, now=NOW) -> tuple`: `init-run --repo-root self.root --run-id key --now now`; sets `self.run_id = self.runs[key] = <reply run_id>`; returns `("--repo-root", self.root, "--run-id", self.run_id)`.
  - On `ContractLifecycleTest`: `write_run(self, label, attempts, *, schema=7)` with `run_id = self.runs[label] = label`; `direct_runs(self, issue)` with the branch body (L2904–2907).

**Invariants:**
- On main `run_of(label) == label` for every label used, so every `--run-id` argument and `.superpowers/workflows/<id>` path is byte-identical to today (D3).
- `mint_run` passes `--run-id`, never `--creation-key`, and reads the id back (D2 translation rule).
- No `attempt_identity`, `TransactionStore`, `ORCHESTRATED`, `TRANSACTION`, `transaction_id`, `schema_version=8`, `bound=` or `orchestrate-<issue>-r<n>` text lands; the legacy-inputs and survive renames stay in #337.
- No assertion removed or loosened; a routed site whose branch form fails on main stays in #337 and is named in the report (D7). In particular, if the branch `direct_runs` body makes an existing `direct_runs(171) == []` assertion fail on main because a non-direct ledger holds 171, keep today's `glob(f"direct-{issue}-*")` body and report it.

- [ ] **Step 1: Route one call site and watch it fail**

Apply hunk -2127 (branch L2164–2165, `HelperInputTest`): `run = self.mint_run("inputs")` and `state = self.root / ".superpowers/workflows" / self.run_id / "state.json"`.

Run: `launch-scope exec … -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k HelperInputTest` (timeout 1800 s)
Expected: errors — `AttributeError: … 'mint_run'`.

- [ ] **Step 2: Add the `BuilderHarness` helpers**

```python
    def mint_run(self, key, *, now=NOW):
        """`init-run --run-id key`: sets `self.run_id` to the run id it replies with, labels it
        `key`, and returns that run's `--repo-root` and `--run-id` arguments."""
        self.run_id = self.runs[key] = json.loads(self.cli(
            "init-run", "--repo-root", self.root, "--run-id", key,
            "--now", now).stdout)["run_id"]
        return ("--repo-root", self.root, "--run-id", self.run_id)
```

Plus `runs` and `run_of` verbatim from branch L1587–1593.

- [ ] **Step 3: Route `ContractLifecycleTest`**

- `control`: hunk -2807 (`self.run_of(run_id)`).
- `write_run`: hunk -2811 with this main body head (D1, D3):

```python
    def write_run(self, label, attempts, *, schema=7):
        """A retained legacy ledger under `label`, which is its run id."""
        run_id = self.runs[label] = label
        state = self.workflow.new_run_state(run_id=run_id, now=NOW, issues={})
```

  and the rest of the method unchanged (it already uses `run_id`).
- `direct_runs`: hunk -2859 (branch body and docstring).
- Sites: -2988 (chain), -3054, -3064, -3069 (orch), -3084 (legacy), -3258 (`legacy_finish`), -3270, -3275 (v2), -3328 (`spawn_contracted`: `self.mint_run(run_id)`), -3371, -3378 (forge-v2), -3385, -3387 (forge-wait), -3410 (orch-fail).
- Leave in #337: hunks -17, -32, -2849, -3220, -3238, -3249, -3282 to -3298 (survive), -2166 to -2179 (legacy-inputs).

- [ ] **Step 4: Verify**

Run: `launch-scope exec … -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py` (timeout 1800 s)
Expected: `OK`, skip count as base.

D7 proxy and forbidden text (any `FAIL` fails the task):

```bash
BASE=$(git merge-base origin/main HEAD); f=home/common/agent-skills/tests/test_delivery_workflow.py
for spec in 'eq:^[[:space:]]*def test_' 'ge:self\.assert|\.assert_called' 'eq:skip'; do
  op=${spec%%:*}; pat=${spec#*:}
  a=$(git show "$BASE:$f" | grep -cE "$pat" || true); b=$(grep -cE "$pat" "$f" || true)
  if { [ "$op" = eq ] && [ "$a" != "$b" ]; } || { [ "$op" = ge ] && [ "$b" -lt "$a" ]; }; then
    echo "FAIL $pat $a -> $b"; else echo "ok $pat $a -> $b"; fi
done
if git diff "$BASE" -- "$f" | grep -E '^\+.*(TransactionStore|attempt_identity|ORCHESTRATED|TRANSACTION|creation-key|transaction_id|orchestrate-)'; then echo FAIL; fi
git diff -U10 "$BASE" -- "$f" | wc -c
```

Expected: three `ok` lines, no `FAIL`, a byte count recorded in the report (Task 4 owns DW's 60000 B gate).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_delivery_workflow.py
launch-commit … -- -m "test(delivery-workflow): route contract-lifecycle run ids through run labels (#346)" -m "<trailers>"
```
