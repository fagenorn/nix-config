# Task 1: Budget check relays the checker's reason

**Files:**
- Modify: `python/agent_tools/review_budget.py` (`BudgetAuthority.check`)
- Modify: `python/README.md` (§ Review packaging and feasibility, the paragraph that starts "Actual production and generic projection share packing")
- Test: `tests/test_review_feasibility.py` (`SourceProjectionTest.test_budget_check_refusal_relays_the_checker_reason`)

**Interfaces:**
- Consumes: the `artifact-budget check` refusal: exit 2, empty stdout and one stderr line `artifact-budget: invalid input: <reason>`, where `<reason>` is issue 472's single-line, value-free text such as `invalid task index row`. `review-feasibility` already prints any `BudgetError` as `review-feasibility: <message>`, cut to 400 characters.
- Produces: `BudgetAuthority.check(kind: str, root: Path) -> BudgetCheck`, with its signature unchanged. When the checker exits outside {0, 3} or writes anything to stderr, it raises `BudgetError(f"budget check failed: {reason}")`. `reason` is the checker's last non-empty stderr line (decoded as UTF-8 with replacement), with each whitespace run collapsed to one space and cut to 200 characters, or `exit <returncode>` when stderr holds no non-empty line (D12, D13). Task 2's discovery refusal relies on this text.

**Invariants:**
- Only `check` changes. `describe`, `validate_report`, `validate_detail` and every other `BudgetError` message stay byte for byte (D12 names `check` only).
- The message is one line, contains no `\n`, and starts with `budget check failed: `.
- An accepted check (exit 0 or 3 with empty stderr) behaves exactly as before.

- [ ] **Step 1: Write the failing test**

Add this method to `SourceProjectionTest` in `tests/test_review_feasibility.py`, directly after `test_duplicate_json_and_ambiguous_sections`:

```python
    def test_budget_check_refusal_relays_the_checker_reason(self):
        plan = self.repo / 'all.md'
        plan.write_bytes(plan.read_bytes().replace('Task 1 — Case'.encode(), b'Task 1 Case', 1))
        self.commit('broken task index row')
        refused = self.project()
        self.assert_refused(refused)
        self.assertEqual(refused.stderr, b'review-feasibility: budget check failed: '
                                         b'artifact-budget: invalid input: invalid task index row\n')
```

The fixture's index row is `Task 1 — Case — shared.txt — full — [task-1.md](all.tasks/task-1.md)`. Without its first ` — ` the row no longer matches the checker's row grammar, so `artifact-budget check` refuses before `load_plan` reads any forecast block.

- [ ] **Step 2: Run the test and watch it fail**

Run (timeout 600 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests.test_review_feasibility -k test_budget_check_refusal_relays_the_checker_reason 2>&1 | tail -8'`
Expected: FAIL. The assertion shows `b'review-feasibility: budget check failed\n'` against the expected line, then `Ran 1 test` and `FAILED (failures=1)`.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/review_budget.py`, add a module-level helper `_refusal_reason(result: subprocess.CompletedProcess) -> str` that implements the Produces rule. It keeps the stderr lines that are non-empty after `strip()`, takes the last one, joins its `split()` parts with one space and slices it to `[:200]`; with no such line it returns `f"exit {result.returncode}"`. In `check`, the existing failure branch (`result.returncode not in {0, 3} or result.stderr`) raises `BudgetError(f"budget check failed: {_refusal_reason(result)}")`. Nothing else in the module changes.

In `python/README.md`, append this sentence to the end of the paragraph that starts "Actual production and generic projection share packing" (keep it one line):

> When `artifact-budget check` refuses, the budget authority's error is `budget check failed: ` followed by the checker's last non-empty stderr line (whitespace collapsed, at most 200 characters), so a `project`, `gate` or `sdd-gate` refusal names the checker's own reason, such as `artifact-budget: invalid input: invalid task index row` (issue 559 D12).

- [ ] **Step 4: Verify**

1. Focused test, green (timeout 600 s): the Step 2 command.
   Expected: `Ran 1 test` and `OK`.
2. Regression over the fixture class and the gate suite (timeout 2400 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests.test_review_feasibility tests.test_review_gate 2>&1 | tail -4'`
   Expected: `OK`. A failure here means another caller depended on the bare `budget check failed` text.
3. Static scope (instant): `grep -c 'raise BudgetError("budget check failed")' python/agent_tools/review_budget.py`
   Expected: prints `0` and exits 1. Exit 0 with `1` means the bare refusal is still raised.
4. Build (timeout 3600 s). The build imports every `agent_tools` module and sees only tracked content, so stage first: `git add python/agent_tools/review_budget.py python/README.md tests/test_review_feasibility.py`, then `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c 'set -o pipefail; just build 2>&1 | tail -3'`
   Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/review_budget.py python/README.md tests/test_review_feasibility.py
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "fix(issue-559): relay the artifact-budget check reason" -m "<the session's Co-Authored-By trailer>"
```

Then check the scope (instant): `test "$(git show --name-only --format= HEAD | sort | tr '\n' ' ')" = "python/README.md python/agent_tools/review_budget.py tests/test_review_feasibility.py "`
Expected: exit 0. A non-zero exit means the commit touched another file or missed one.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":1,"records":[{"bounds":[{"added_lines":10,"boundary":"all","deleted_lines":1,"record_bytes":6144,"support":{"covers":["r1-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1-1","last_task":1,"owner":1,"path":"python/agent_tools/review_budget.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":8192,"support":{"covers":["r1-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1-2","last_task":2,"owner":1,"path":"python/README.md"},{"bounds":[{"added_lines":12,"boundary":"all","deleted_lines":0,"record_bytes":6144,"support":{"covers":["r1-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1-3","last_task":2,"owner":1,"path":"tests/test_review_feasibility.py"}]}}
```
