# Task 2: Row-check timeout refusal marked transient

Spec § Row check: the transient marker, § Guard documentation, § Test seams. Rests on D6, D8 and D10. After this task, a row check that times out is refused ending `timed out; transient: rerun the command`, in place of `; repair: run claude-guard-policy`. That includes a row check whose bound the invocation deadline clipped. Every other row-check refusal keeps the repair clause and never carries the marker. Task 1's merge behaviour is untouched.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py` (`row_check_problem`)
- Modify: `tests/test_claude_permission_guard.py`
- Modify: `home/common/claude-code/README.md` (`## Guard policy`, the **Row check.** paragraph)

**Interfaces:**
- Consumes (all unchanged): `row_check_problem(derive_bin, repository, row, timeout)`, which is still the one builder of the row-check refusal for all four repository-bound verbs through `Context._row_problem` and `ownership_problem`. The tests use `run_guard`, `refusal_line`, `assert_unconfirmed`, `make_repo`, `assert_row_check_killed`, the fake row check's `FAKE_DERIVE_MODE` (`hang`, `slow`, `unavailable`, `garbage`, `refused_code`) and `NODO`.
- Produces: no new name. The refusal text for `why == "timed out"` becomes `repository <slug>: the row check did not confirm its derived policy row: timed out; transient: rerun the command`.

**Invariants:**
- Only the `subprocess.TimeoutExpired` branch of `row_check_problem` changes the closing clause. A start failure (`could not start (…)`), an unreadable report, a refused or unavailable report and a branch mismatch keep `; repair: run claude-guard-policy`, with no marker (D6).
- The literal-conflict refusal, the `origin/HEAD` refusal, the compiled-policy `; repair: run claude-guard-policy` in `ownership_problem` and `DEADLINE_REFUSAL` keep their texts (D6, D10).
- The guard file keeps exactly three occurrences of `repair: run claude-guard-policy` and gains exactly one `transient: rerun the command`.
- The 15 s row-check bound, the 5 s child bound and the 27 s deadline are unchanged.

- [ ] **Step 1: Write the failing tests**

All edits are in `tests/test_claude_permission_guard.py`.

1. `test_a_row_check_past_its_bound_is_killed_with_its_process_group`: replace

```python
        self.assertIn("the row check did not confirm its derived policy row: timed out",
                      result.stderr)
```

   with

```python
        line = self.refusal_line(result)
        self.assertTrue(line.endswith("the row check did not confirm its derived policy row: "
                                      "timed out; transient: rerun the command"), line)
        self.assertNotIn("claude-guard-policy", line)
```

2. `test_the_invocation_deadline_bounds_the_row_check_and_every_later_child` (D10): replace

```python
        self.assertIn("the row check did not confirm its derived policy row: timed out",
                      hung.stderr)
```

   with

```python
        self.assertTrue(self.refusal_line(hung).endswith(
            "the row check did not confirm its derived policy row: timed out; "
            "transient: rerun the command"), hung.stderr)
```

   and directly after `self.assertEqual(1, exhausted.stderr.count("lifecycle guard:"), exhausted.stderr)` add

```python
        self.assertNotIn("transient", exhausted.stderr)
```

3. `assert_unconfirmed`: directly after its `self.assertIn(expected, result.stderr)` add

```python
                self.assertNotIn("transient", result.stderr)
```

   Every caller passes a reason other than a timeout: `test_a_row_for_an_unregistered_repository_is_refused_at_use` (`refused (…)`, `refused (fetch_failed)`), `test_a_row_whose_branches_differ_from_the_derivation_is_refused` and `test_a_failing_row_check_refuses_with_no_fallback` (`unavailable (…)`, `unreadable report (exit 0)`, `could not start (`).

- [ ] **Step 2: Run the tests and watch them fail**

Run the Guard suite with `-k test_a_row_check_past_its_bound -k test_the_invocation_deadline_bounds -k test_a_failing_row_check -k test_a_row_for_an_unregistered -k test_a_row_whose_branches_differ` (about 35 s after the build).
Expected: `Ran 5 tests` and `FAILED (failures=2)`. Both timeout tests fail their `endswith` assertion, because each line still ends `timed out; repair: run claude-guard-policy`. The three `assert_unconfirmed` tests pass, since no refusal carries the marker yet.

- [ ] **Step 3: Write the minimal implementation**

1. `row_check_problem` in `lifecycle_guard.py`:
   - Add a third docstring paragraph: `A timeout's refusal ends in the transient marker, every other refusal in the claude-guard-policy repair (issue 476 D6).`
   - Directly after `why = None`, add `remedy = "repair: run claude-guard-policy"`.
   - In the `except subprocess.TimeoutExpired:` branch, directly after `why = "timed out"`, add:

```python
            # Issue 476 D6: a slow check clears on a plain rerun, and recompiling
            # the policy cannot speed it up.
            remedy = "transient: rerun the command"
```

   - The returned message's second f-string becomes `f"policy row: {why}; {remedy}"`.

2. `home/common/claude-code/README.md`, `## Guard policy`, **Row check.** paragraph: replace `and `claude-guard-policy` as the repair; step 2's names the live and recorded branch.` with `and `claude-guard-policy` as the repair, except that a row check that timed out at step 3 ends `timed out; transient: rerun the command` instead, because a plain rerun clears it and recompiling the policy cannot speed it up (issue 476); step 2's names the live and recorded branch.`

   Leave the **Cost and offline behaviour** paragraph's `fetch_failed` sentence unchanged (D6).

- [ ] **Step 4: Verify**

Run the Guard suite with no `-k`.
Expected: `Ran 94 tests` and `OK`.

Run: `bash -c 'set -e; test "$(grep -c "transient: rerun the command" home/common/claude-code/lifecycle_guard.py)" = 1; test "$(grep -c "repair: run claude-guard-policy" home/common/claude-code/lifecycle_guard.py)" = 3; grep -qF "timed out; transient: rerun the command" home/common/claude-code/README.md; if git diff -U0 -- home/common/claude-code/lifecycle_guard.py | grep -E "^\+.*(import |subprocess\.)"; then exit 1; fi'`
Expected: exit 0. The marker appears once, all three repair clauses survive, the README names the marker, and there is no new import or child process.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py home/common/claude-code/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(guard): mark a row-check timeout refusal transient (issue 476)" -m "<trailers>"
```
