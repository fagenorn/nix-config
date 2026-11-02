# Task 3: Over-budget overages and the strict consumer

**Files:**
- Modify: `home/common/agent-skills/scripts/artifact_budget.py`
- Modify: `python/agent_tools/review_budget.py`
- Modify: `home/common/agent-skills/tests/fixtures/artifact-budgets/small-issue.json`
- Modify: `home/common/agent-skills/tests/fixtures/artifact-budgets/oversized-issue.json`
- Test: `home/common/agent-skills/tests/test_artifact_budget.py`
- Test: `tests/test_sdd_gate.py`

**Interfaces:**
- Consumes: nothing from Tasks 1 and 2. Their tests stay green.
- Produces:
  - `artifact_budget._BOUNDS: tuple[tuple[str, str, Callable[[Mapping[str, int]], int]], ...]`, one row per code: the code, the `ArtifactLimits` field it is measured against, and the measured quantity.
  - `VIOLATIONS`, now `tuple(code for code, _, _ in _BOUNDS)`, with the same value as today.
  - `CheckResult.overages: Mapping[str, Mapping[str, int]]`, a new last field. `to_dict()` emits it as `"overages"`.
  - The `check` wire form gains `"overages": {<code>: {"limit": <int>, "over_by": <int>}}`. Its keys equal the set of `violations`, and it is `{}` within budget (D6).
  - In `tests/test_sdd_gate.py`: `force_check(result: dict) -> str` and `OVER_BUDGET: dict`, with `FORCE_OVER_BUDGET = force_check(OVER_BUDGET)`.

**Invariants:**
- `interface_version`, `kind`, `status`, `metrics`, `violations`, their order and the exit codes (0 within budget, 3 over, 2 failed) do not change (D7). The canonical output sorts `overages` keys like every other object.
- Each entry has `over_by >= 1`, and `limit + over_by` is the measured value: `metrics.root_bytes`, `metrics.largest_member_bytes`, `metrics.file_count - 1` or `metrics.total_bytes`.
- Every check result is classified as it is at base. A largest member of 0 with no members is never over `member_max_bytes`, because the policy keeps that limit at 0 or above.
- `BudgetCheck` and every `BudgetAuthority` caller are unchanged. The authority refuses, as `invalid budget check`, a result whose `overages` is missing, is not an object, has keys other than the set of `violations`, or has an entry other than exactly `{limit, over_by}`. It also refuses non-boolean integers outside `limit >= 0` and `over_by >= 1` (D8).

- [ ] **Step 1: Write the failing tests**

In `test_artifact_budget.py`:
- In `test_valid_measurement_is_deterministic_and_violations_are_closed`, the expected key set gains `"overages"`.
- In `test_repository_descriptors_drive_cli_results`, the expected `item["expected"]` key set gains `"overages"`, and the loop asserts `self.assertEqual(measured["overages"], expected["overages"])` after its `violations` assertion.
- Add after `test_valid_measurement_is_deterministic_and_violations_are_closed`:

```python
    def test_an_over_budget_check_reports_limit_and_overage(self):
        """Issue 472 AC3, D6, D7: overages carry each violated code's limit and how far over it is."""
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "handoff.md"
            path.write_bytes(b"h" * 8_193)
            over = self.run_check("handoff", path)
            self.assertEqual(over.returncode, 3, over.stderr)
            self.assertEqual(over.stdout, (
                '{"interface_version":1,"kind":"handoff","metrics":{"file_count":1,'
                '"largest_member_bytes":0,"root_bytes":8193,"total_bytes":8193},'
                '"overages":{"aggregate_bytes":{"limit":8192,"over_by":1},'
                '"root_bytes":{"limit":8192,"over_by":1}},"status":"over_budget",'
                '"violations":["root_bytes","aggregate_bytes"]}\n'))
            path.write_bytes(b"h" * 8_192)
            within = self.run_check("handoff", path)
            self.assertEqual(within.returncode, 0, within.stderr)
            self.assertEqual(json.loads(within.stdout)["overages"], {})
```

In both descriptor fixtures, add `"overages"` to each case's `expected`, on one line directly after `"violations"`, in the style of `"metrics"`. Every `small-issue.json` case (`small-design`, `small-plan`, `small-handoff`, `small-review`) gets `"overages": {}`. The `oversized-issue.json` cases get:

| Case | `overages` |
|---|---|
| `design-root-plus-one` | `{"root_bytes": {"limit": 65536, "over_by": 1}, "aggregate_bytes": {"limit": 65536, "over_by": 1}}` |
| `plan-ninth-member` | `{"member_count": {"limit": 8, "over_by": 1}}` |
| `plan-member-plus-one` | `{"member_bytes": {"limit": 49152, "over_by": 1}}` |
| `handoff-root-plus-one` | `{"root_bytes": {"limit": 8192, "over_by": 1}, "aggregate_bytes": {"limit": 8192, "over_by": 1}}` |
| `review-member-plus-one` | `{"member_bytes": {"limit": 65536, "over_by": 1}}` |
| `review-aggregate-and-count` | `{"member_count": {"limit": 8, "over_by": 1}, "aggregate_bytes": {"limit": 524288, "over_by": 16736}}` |

In `tests/test_sdd_gate.py`, replace the `FORCE_OVER_BUDGET` string literal with:

```python
def force_check(result):
    """Shim code that makes the review-package check, and only it, print `result` and exit 3."""
    line = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return ('if sys.argv[1:5] == ["check", "--kind", "review-package", "--root"]:\n'
            f'    sys.stdout.write({line!r})\n'
            '    raise SystemExit(3)\n')


# The checker's over-budget wire form: metrics, violations and overages agree (issue 472 D6).
OVER_BUDGET = {"interface_version": 1, "kind": "review-package",
               "metrics": {"file_count": 1, "largest_member_bytes": 1, "root_bytes": 1,
                           "total_bytes": 2},
               "overages": {"aggregate_bytes": {"limit": 1, "over_by": 1}},
               "status": "over_budget", "violations": ["aggregate_bytes"]}
FORCE_OVER_BUDGET = force_check(OVER_BUDGET)
```

In `ReviewTest.test_an_over_budget_package_is_refused_at_budget_check`, bind `out = self.assert_gate_refused(...)` and add `self.assertEqual(out["detail"], "package is over_budget")` (D10). Add after that test:

```python
    def test_a_check_that_breaks_the_overages_contract_is_refused_at_budget_check(self):
        """Issue 472 D8, D14: the budget authority refuses a check whose overages break the wire form."""
        self.start_task(1, "src/app.py", "value = 2\n")
        self.ready(self.review(1))
        self.brief().unlink()
        broken = {
            "missing": {key: value for key, value in OVER_BUDGET.items() if key != "overages"},
            "keys": {**OVER_BUDGET, "overages": {}},
            "over_by": {**OVER_BUDGET,
                        "overages": {"aggregate_bytes": {"limit": 1, "over_by": 0}}},
        }
        for name, result in broken.items():
            with self.subTest(result=name):
                self.write_budget_shim(force_check(result))
                out = self.assert_gate_refused(
                    self.review(1), command="review", step="budget-check", gate="failed",
                    steps=["ledger", "review-package", "validate-report"])
                self.assertEqual(out["detail"], "budget check refused: invalid budget check")
                self.assertFalse(self.brief().exists())
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: the Unit run on `home/common/agent-skills/tests/test_artifact_budget.py` with `-k limit_and_overage -k violations_are_closed -k descriptors_drive`.
Expected: FAIL in 3 tests. The new test fails on a stdout mismatch, because there is no `"overages"`. The key-set test fails on a set mismatch. The descriptor test fails with `KeyError: 'overages'`.

Run: the Unit run on `tests/test_sdd_gate.py` with `-k budget_check`.
Expected: FAIL in 2 tests:
- `test_an_over_budget_package_is_refused_at_budget_check`: `'budget check refused: invalid budget check' != 'package is over_budget'`. Today's authority refuses any extra member.
- The new test's `missing` subtest: `'package is over_budget' != 'budget check refused: invalid budget check'`.

- [ ] **Step 3: Write the minimal implementation**

1. **`artifact_budget.py`.** Define `_BOUNDS` directly above `VIOLATIONS`, and derive `VIOLATIONS` from it:

```python
# One row per violation code: the code, the limit it is measured against and the
# measured quantity. `violations` and `overages` both derive from it (issue 472 D6).
_BOUNDS: tuple[tuple[str, str, Callable[[Mapping[str, int]], int]], ...] = (
    ("root_bytes", "root_max_bytes", lambda metrics: metrics["root_bytes"]),
    ("member_bytes", "member_max_bytes", lambda metrics: metrics["largest_member_bytes"]),
    ("member_count", "max_members", lambda metrics: metrics["file_count"] - 1),
    ("aggregate_bytes", "aggregate_max_bytes", lambda metrics: metrics["total_bytes"]),
)
VIOLATIONS = tuple(code for code, _, _ in _BOUNDS)
```

   `CheckResult` gains `overages: Mapping[str, Mapping[str, int]]` as its last field. `to_dict()` adds `"overages": {code: dict(entry) for code, entry in self.overages.items()}`, and every other member stays as it is. In `_check_artifact`, the four `if ... violations.append(...)` comparisons go. In their place, one loop over `_BOUNDS` reads `limit = getattr(policy, limit_name)` and `measured = measure(metrics)`. When `measured > limit`, it records `overages[code] = {"limit": limit, "over_by": measured - limit}`. Then `violations = list(overages)`, whose insertion order is the table's order, and `CheckResult(kind, "over_budget" if violations else "within_budget", metrics, violations, overages)`.
2. **`python/agent_tools/review_budget.py` (D8).** Add `_CHECK_KEYS = {"interface_version", "kind", "status", "metrics", "violations", "overages"}` and `_OVERAGE_KEYS = {"limit", "over_by"}` beside `_METRIC_KEYS`, and use `_CHECK_KEYS` in `check`'s first key-set test. Add:

```python
def _valid_overages(overages: object, violations: list[str]) -> bool:
    """Exactly one `{limit, over_by}` entry per violated code (issue 472 D8)."""
    return (isinstance(overages, dict) and set(overages) == set(violations)
            and all(isinstance(entry, dict) and set(entry) == _OVERAGE_KEYS
                    and type(entry["limit"]) is int and entry["limit"] >= 0
                    and type(entry["over_by"]) is int and entry["over_by"] >= 1
                    for entry in overages.values()))
```

   Append `or not _valid_overages(value["overages"], violations)` as the last term of `check`'s second `if`. By then the `violations` terms have passed, so `violations` holds only distinct codes. `BudgetCheck` and the returned value stay the same.

- [ ] **Step 4: Verify**

Run: the Unit run on `home/common/agent-skills/tests/test_artifact_budget.py`.
Expected: PASS, 54 tests, `OK`.

Run: the Unit run on `tests/test_sdd_gate.py` with `-k budget_check -k decompose_required -k over_budget`.
Expected: PASS, 4 tests, `OK`. The decompose case sends the real checker's result through the updated authority.

Run: the Unit run on `home/common/agent-skills/tests/test_review_package.py` with `-k oversized -k stop_on_member_count`.
Expected: PASS, 10 tests, `OK`, in about 13 s.

Run: the Unit run on `tests/test_review_feasibility.py` with `-k test_owned_candidate_matches_independent_actual_range`.
Expected: PASS, 1 test, `OK`, in about 60 s.

Run: the Build.
Expected: it exits 0 and the tail shows no error.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/artifact_budget.py python/agent_tools/review_budget.py home/common/agent-skills/tests/fixtures/artifact-budgets/small-issue.json home/common/agent-skills/tests/fixtures/artifact-budgets/oversized-issue.json home/common/agent-skills/tests/test_artifact_budget.py tests/test_sdd_gate.py
git commit -m "feat(artifact-budget): report limit and overage for each violated dimension (issue 472)"
```
