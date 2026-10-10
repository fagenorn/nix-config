# Task 1: Direct-run helpers and their call sites

Issue: https://github.com/fagenorn/nix-config/issues/346. Spec: `.agents/artifacts/specs/2026-10-10-issue-346-attempt-identity-test-harness-prep-design.md`. Reference commit: `6ae38b0c` (branch `worktree-issue-337-orchestrated`); base `901da282`. "Branch L<n>" below means line `<n>` of `git show 6ae38b0c:home/common/agent-skills/tests/test_workflow_state.py`; "hunk -<m>" means the hunk header `@@ -<m>…` of `git diff -U0 901da282 6ae38b0c -- home/common/agent-skills/tests/test_workflow_state.py`.

**Files:**
- Modify: `home/common/agent-skills/tests/test_workflow_state.py` (class `LifecycleHarness` and the `WorkflowStateLifecycleTest` / `PhaseGateReplyTest` call sites listed below)

**Interfaces:**
- Consumes: `LifecycleHarness.workflows_dir` (property), `LifecycleHarness.direct_state_path(run_id)` (unchanged; its index lookup stays in #337).
- Produces, as `LifecycleHarness` methods placed immediately before `def direct_state_path` (branch order, L578–603):
  - `direct_run_id(self, issue, sequence) -> str` returning `f"direct-{issue}-{sequence:06d}"`.
  - `run_dirs(self) -> list[str]`: sorted names of the directories under `self.workflows_dir` (branch text verbatim, L587–589).
  - `mint_direct_ledger(self, state, issue, sequence, prior_run) -> Path`: makes `workflows_dir / direct_run_id(issue, sequence)`, writes an empty `state.lock`, writes `json.dumps({**state, "run_id": run_id}, sort_keys=True, separators=(",", ":")) + "\n"` (UTF-8) as `state.json`, returns the run dir. `prior_run` is accepted and unused (D4). Task 4 (DW `LedgerClockTest`) relies on `run_dirs`.

**Invariants:**
- Every run id and ledger byte a test observes is today's: `direct_run_id(73, 2) == "direct-73-000002"`, and each `mint_direct_ledger` ledger is byte-identical to the hand-built one it replaces (D4).
- Signatures and routed lines are copied from `6ae38b0c` (D1); docstrings are the one-line main-true ones below, never the branch's store/minting docstrings (D1).
- No `TransactionStore`, `attempt_identity`, `attempt_store`, schema-8 or `transaction_id` text lands (Global Constraints).
- No assertion is removed or loosened; a routed site whose branch form fails on main stays in #337 and is named in the task report (D7).

- [ ] **Step 1: Route the first call site and watch it fail**

Apply hunk -544 (branch L626): in `LifecycleHarness`'s direct-acquire expectation, `"run_id": f"direct-{issue}-000001",` becomes `"run_id": self.direct_run_id(issue, 1),`.

Run: `launch-scope exec … -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py -k direct` (timeout 1800 s)
Expected: errors — `AttributeError: … has no attribute 'direct_run_id'`.

- [ ] **Step 2: Add the three helpers**

```python
    def direct_run_id(self, issue, sequence):
        """The run id `direct-owner` gives direct run `sequence` of `issue`."""
        return f"direct-{issue}-{sequence:06d}"

    def run_dirs(self):
        """The names of the run directories under `workflows`."""
        return sorted(path.name for path in self.workflows_dir.iterdir() if path.is_dir())

    def mint_direct_ledger(self, state, issue, sequence, prior_run):
        """Install `state` as direct run `sequence` of `issue` beside an empty `state.lock`;
        `prior_run` is unused."""
        run_id = self.direct_run_id(issue, sequence)
        run_dir = self.workflows_dir / run_id
        run_dir.mkdir()
        (run_dir / "state.lock").write_bytes(b"")
        (run_dir / "state.json").write_text(json.dumps(
            {**state, "run_id": run_id}, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8")
        return run_dir
```

- [ ] **Step 3: Route the remaining direct-family call sites**

Copy each branch line, keeping today's semantics:
- `direct_run_id` literals: hunks -3914 (L3995), -3992 (L4073), -4014 (L4095), -4310/-4323/-4325 (L4390–4407: `second = self.direct_run_id(73, 2)`, and `self.direct_state_path(owner["run_id"])` for the first run), -4520 first line (L4590), -4881 (L4943), -5110/-5113 (L5172, L5175), -7867 (L7937).
- `run_dirs()` listings: hunks -4270 (L4351), -4385 (L4466), -4520 remaining lines (L4591–4592).
- `mint_direct_ledger`: hunk -4464 (L4542, malformed-history test); hunks -4648, -4657, -4666 (L4718–4730, nonterminal-below-terminal test: drop `terminal["run_id"] = "direct-73-000002"`, call `mint_direct_ledger(terminal, 73, 2, owner["run_id"])`, snapshot `(self.direct_state_path(owner["run_id"]), second / "state.json")`).
- Leave untouched (stays in #337): hunks -4530, -4685, -4691, -4699 (schema-8 binding), -4743 (`direct_state_path` index lookup), every `--creation-key` hunk.

- [ ] **Step 4: Verify**

Run: `launch-scope exec … -- env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_state.py` (timeout 1800 s)
Expected: `OK` (same skip count as base); a failure is a routing error, or a D7 site to revert and report.

Run the D7 proxy (fails the task on any `FAIL` line):

```bash
BASE=$(git merge-base origin/main HEAD); f=home/common/agent-skills/tests/test_workflow_state.py
for spec in 'eq:^[[:space:]]*def test_' 'ge:self\.assert|\.assert_called' 'eq:skip'; do
  op=${spec%%:*}; pat=${spec#*:}
  a=$(git show "$BASE:$f" | grep -cE "$pat" || true); b=$(grep -cE "$pat" "$f" || true)
  if { [ "$op" = eq ] && [ "$a" != "$b" ]; } || { [ "$op" = ge ] && [ "$b" -lt "$a" ]; }; then
    echo "FAIL $pat $a -> $b"; else echo "ok $pat $a -> $b"; fi
done
git diff -U10 "$BASE" -- "$f" | wc -c
```

Expected: three `ok` lines, and a byte count (record it in the report; no threshold yet — Task 2 owns WS's 60000 B gate).

Forbidden-text gate: `if git diff "$BASE" -- "$f" | grep -E '^\+.*(TransactionStore|attempt_identity|attempt_store|creation-key|transaction_id)'; then exit 1; fi`

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_workflow_state.py
launch-commit … -- -m "test(workflow-state): route direct-run ids through harness helpers (#346)" -m "<trailers>"
```
