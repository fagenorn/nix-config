# Task 4: Admission read-back, clock skew, budgets and #337 replay

Issue: https://github.com/fagenorn/nix-config/issues/346. Spec: `.agents/artifacts/specs/2026-10-10-issue-346-attempt-identity-test-harness-prep-design.md`. Reference commit: `6ae38b0c`; base `901da282`. "Branch L<n>" means line `<n>` of `git show 6ae38b0c:home/common/agent-skills/tests/test_delivery_workflow.py`; "hunk -<m>" means the header `@@ -<m>…` of `git diff -U0 901da282 6ae38b0c -- home/common/agent-skills/tests/test_delivery_workflow.py`. Tasks 1–3 have landed: `LifecycleHarness.run_dirs()` (WS) and `BuilderHarness.runs` / `run_of` / `mint_run` (DW). WS = `home/common/agent-skills/tests/test_workflow_state.py`, DW = `home/common/agent-skills/tests/test_delivery_workflow.py`.

**Files:**
- Modify: `home/common/agent-skills/tests/test_delivery_workflow.py` (`DeliveryAdmissionTest`, `LedgerClockTest`)

**Interfaces:**
- Consumes: `LifecycleHarness.run_dirs() -> list[str]` and `self.run_id` (inherited by `LedgerClockTest`).
- Produces: `DeliveryAdmissionTest.remainder_sweeps(self, root, home, key) -> (control, checkpoint, run_id)`, where `run_id` is the `run_id` of the reply to `init-run --repo-root root --run-id key --now NOW`, and every later command of the sweep uses `("--repo-root", root, "--run-id", run_id)`.

**Invariants:**
- Every `init-run` keeps `--run-id <today's literal>`; later calls use the id read back from its reply, which equals that literal on main (D2, D3).
- The transact-on-legacy test's ledger is `orchestrate-151` (dir name and `run_id`), and its schema-7 assertions stay as today (D3).
- No `attempt_identity`, `TransactionStore`, `ORCHESTRATED`, `TRANSACTION`, `transaction_id`, `identity=`, `schema_version=8` or `LedgerClockTest.run_cli` text lands.
- No assertion removed or loosened; `LedgerClockTest`'s `assertEqual(self.run_dirs(), [self.run_id])` replaces `assertFalse(self.direct_state_path("direct-73-000001").exists())` only if it passes on main, else that site stays in #337 and the report names it (D7).

- [ ] **Step 1: Change one `remainder_sweeps` caller and watch it fail**

Apply hunk -1286 (branch L1305–1306): `root = Path(raw)` and `control, _, run_id = self.remainder_sweeps(root, home, "live-remainder")`.

Run: `launch-scope exec … -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k remainder` (timeout 1800 s)
Expected: errors — `ValueError: not enough values to unpack (expected 3, got 2)`.

- [ ] **Step 2: Make `remainder_sweeps` mint and return the run id**

Hunks -1220, -1225, -1233, -1262, -1274, with `--run-id` in place of `--creation-key`:

```python
        run_id = json.loads(invoke("init-run", "--repo-root", root, "--run-id", key,
                                   "--now", NOW))["run_id"]
        run = ("--repo-root", root, "--run-id", run_id)
```

Docstring line: ``(control, checkpoint, run_id)``, the run id `init-run --run-id key` replies with. Then the remaining callers: hunks -1311, -1340, -1349, -1380.

- [ ] **Step 3: Read back every other admission `init-run`**

Each with `--run-id <today's literal>` where the branch has `--creation-key`:
- admission: hunks -214, -216 (`minted = json.loads(initialized.stdout)["run_id"]`), -230.
- legacy-contractless: hunks -249, -265 (hunk -246 changes only the flag; leave that line as today).
- transact-on-legacy: hunks -291, -293, -297 (`orchestrate-151` dir, `{**self.legacy(2), "run_id": "orchestrate-151"}`, `transact(str(root), "orchestrate-151", …)`); hunk -300 stays.
- orchestrated: hunks -1121 (`run_id = invoke("init-run", "--repo-root", root, "--run-id", "orchestrated", "--now", NOW)["run_id"]`), -1157.
- refusal: hunks -1166, -1175, -1188.
- recovery-control: hunks -1391, -1401.
- dispatch-wire: hunks -1496, -1503 (keep `"--run-id", "dispatch-wire"`), -1505.
- `LedgerClockTest`: hunk -3636. Hunk -3443 (`run_cli`) stays.
- Leave in #337: hunks -144, -157, -168, -280, -306 to -368, -413, -417.

- [ ] **Step 4: Verify tests, AC2 proxy and AC1**

Run: `launch-scope exec … -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py` (timeout 1800 s)
Expected: `OK`, skip count as base.

```bash
BASE=$(git merge-base origin/main HEAD)
for f in home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py; do
  for spec in 'eq:^[[:space:]]*def test_' 'ge:self\.assert|\.assert_called' 'eq:skip'; do
    op=${spec%%:*}; pat=${spec#*:}
    a=$(git show "$BASE:$f" | grep -cE "$pat" || true); b=$(grep -cE "$pat" "$f" || true)
    if { [ "$op" = eq ] && [ "$a" != "$b" ]; } || { [ "$op" = ge ] && [ "$b" -lt "$a" ]; }; then
      echo "FAIL $f $pat $a -> $b"; else echo "ok $f $pat $a -> $b"; fi
  done
  if git diff "$BASE" -- "$f" | grep -vF 'state.pop("transaction_id", None)' | grep -E '^\+.*(TransactionStore|attempt_identity|attempt_store|ORCHESTRATED|TRANSACTION|LedgerRefused|creation-key|transaction_id)'; then echo "FAIL forbidden $f"; fi
done
git diff --name-only "$BASE" HEAD -- . ':!.agents/artifacts'
```

Expected: six `ok` lines, no `FAIL`, and the last command prints exactly the WS and DW paths (AC1).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_delivery_workflow.py
launch-commit … -- -m "test(delivery-workflow): read admission run ids back from init-run (#346)" -m "<trailers>"
```

- [ ] **Step 6: Measure AC4 and replay #337 for AC5 (on the committed head)**

```bash
BASE=$(git merge-base origin/main HEAD)
for f in home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py; do
  echo "AC4 $f $(git diff -U10 "$BASE" -- "$f" | wc -c)"; done
S=$(launch-scope scratch --repo-root /Users/anis/tmp/nix-config --run-id <run-id> --worker-id <worker-id>)
git worktree add --detach "$S/replay-337" HEAD
for f in home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_delivery_workflow.py; do
  git -C "$S/replay-337" show "6ae38b0c:$f" > "$S/replay-337/$f"
  echo "AC5 $f $(git -C "$S/replay-337" diff -U10 HEAD -- "$f" | wc -c)"; done
git worktree remove --force "$S/replay-337"
```

Expected: four numbers, each ≤ 60000. Report all four (and every D5 or D7 site left to #337) for acceptance-record rows AC4 and AC5 and the PR body. WS's AC4 number cannot change after Task 2, which gated it with D5; any number over 60000 here has no in-plan remedy: report BLOCKED with the numbers.
