# Task 3: No eval prefixes an absolute artifact dir

**Files:**
- Modify: `home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json` (three asserts in cases 2 and 3)
- Modify: `home/common/agent-skills/evals/assert-lib.sh` (the `SPEC_DIR / PLAN_DIR` line of the header's environment list only)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (the three `required_shells` fragments in `ImproveCodebaseArchitectureSkillContractsTest.test_eval_assertion_shells_are_unique_and_behavioral`, per D11)
- Test: `home/common/agent-skills/tests/test_eval_cases.py`

**Interfaces:**
- Consumes: Task 2's state — writing-plans case 1 no longer prefixes `$REPO/` to an artifact dir — and `case_files()`, `REPO_ROOT` (existing).
- Produces: `EvalCasesTest.test_no_assert_prefixes_an_absolute_artifact_dir`, replacing `test_from_issue_asserts_never_prefix_an_absolute_artifact_dir`.

**Invariants:**
- No assert in any `evals.json` under either skill root (`case_files()`) concatenates a checkout variable (`$WT`, `$REPO`, `$PRE_WT`, braced or not) with a bare `$SPEC_DIR`/`$PLAN_DIR` (or `${SPEC_DIR}`/`${PLAN_DIR}`), and no `commits_touch "$WT"`/`"$PRE_WT"` call passes a bare artifact dir (D1, D3).
- The stripped form `${SPEC_DIR#"$REPO"/}` stays valid: from-issue's existing asserts pass the new test unchanged.
- improve-codebase-architecture asserts keep their names, order and count; only the three named below change, and each keeps its logic (D3).

- [ ] **Step 1: Write the failing test**

Replace `test_from_issue_asserts_never_prefix_an_absolute_artifact_dir` in `EvalCasesTest` with:

```python
    ARTIFACT_DIR = r'\$(?:(?:SPEC|PLAN)_DIR\b|\{(?:SPEC|PLAN)_DIR\})'

    def test_no_assert_prefixes_an_absolute_artifact_dir(self):
        prefixed = re.compile(r'\$\{?(?:WT|REPO|PRE_WT)\}?/' + self.ARTIFACT_DIR)
        touched = re.compile(
            r'commits_touch\s+"\$\{?(?:WT|PRE_WT)\}?"[^;&|]*"' + self.ARTIFACT_DIR + '"')
        samples = (
            ('has_file "$REPO/$PLAN_DIR"/*.md', True),
            ('has_file "$WT/${SPEC_DIR}"/*.md', True),
            ('commits_touch "$WT" "$SPEC_DIR"', True),
            ('has_file "$PLAN_DIR"/*.md', False),
            ('has_file "$WT/${PLAN_DIR#"$REPO"/}"/*.md', False),
            ('commits_touch "$WT" "${SPEC_DIR#"$REPO"/}"', False),
            ('git -C "$REPO" log main -- "$SPEC_DIR"', False),
        )
        for sample, flagged in samples:
            with self.subTest(sample=sample):
                self.assertEqual(bool(prefixed.search(sample) or touched.search(sample)), flagged)
        for path in case_files():
            for case in json.loads(path.read_text(encoding="utf-8"))["evals"]:
                for check in case.get("asserts") or []:
                    with self.subTest(path=str(path.relative_to(REPO_ROOT)), case=case["id"],
                                      name=check["name"]):
                        self.assertNotRegex(check["shell"], prefixed)
                        self.assertNotRegex(check["shell"], touched)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py -k prefixes_an_absolute 2>&1 | grep -E '^FAIL|^FAILED'`
Expected: `FAILED (failures=3)`, one subtest each for improve-codebase-architecture case 2 `design spec was committed`, case 2 `no plan was created` and case 3 `no spec or plan was created`; no from-issue or writing-plans subtest fails.

- [ ] **Step 3: Fix the three asserts (per D1, D3) and document the convention**

Edit `improve-codebase-architecture/evals/evals.json` so that, decoded with `jq -r`, the three asserts read:

- case 2 `design spec was committed`: `commits_touch "$WT" "${SPEC_DIR#"$REPO"/}"`
- case 2 `no plan was created`: `if has_file "$PLAN_DIR"/*.md "$WT/${PLAN_DIR#"$REPO"/}"/*.md; then fail "plan created before the scope gate"; fi`
- case 3 `no spec or plan was created`: `if has_file "$SPEC_DIR"/*.md "$PLAN_DIR"/*.md; then fail "created a spec or plan after fog routing"; fi`

In `assert-lib.sh`, replace the header line

```
#   SPEC_DIR / PLAN_DIR  absolute paths from the fixture's retained resolver snapshot
```

with

```
#   SPEC_DIR / PLAN_DIR  absolute paths from the fixture's retained resolver snapshot:
#             use them bare under REPO and as "$WT/${SPEC_DIR#"$REPO"/}" under another
#             checkout, never "$REPO/$SPEC_DIR"
```

In `test_workflow_skill_contracts.py`, `ImproveCodebaseArchitectureSkillContractsTest.test_eval_assertion_shells_are_unique_and_behavioral` pins the old text of these three asserts in `required_shells` (per D11, edit the existing fragments in place, add none):

- case 2 `design spec was committed`: `('commits_touch "$WT" "$SPEC_DIR"',)` becomes `('commits_touch "$WT" "${SPEC_DIR#"$REPO"/}"',)`
- case 2 `no plan was created`: `'if has_file "$REPO/$PLAN_DIR"/*.md "$WT/$PLAN_DIR"/*.md; then'` becomes `'if has_file "$PLAN_DIR"/*.md "$WT/${PLAN_DIR#"$REPO"/}"/*.md; then'`
- case 3 `no spec or plan was created`: `'if has_file "$REPO/$SPEC_DIR"/*.md "$REPO/$PLAN_DIR"/*.md; then'` becomes `'if has_file "$SPEC_DIR"/*.md "$PLAN_DIR"/*.md; then'`

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py 2>&1 | tail -n 1`
Expected: `OK`.

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ImproveCodebaseArchitectureSkillContractsTest 2>&1 | tail -n 1`
Expected: `OK` (fails at the Step 3 eval edit until the three pins are updated).

Run: `if grep -n 'test_from_issue_asserts_never_prefix' home/common/agent-skills/tests/test_eval_cases.py; then exit 1; fi`
Expected: exit 0 (the from-issue-only test is gone; it exits 1 at the starting commit).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json home/common/agent-skills/evals/assert-lib.sh home/common/agent-skills/tests/test_eval_cases.py home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit … -- -m "fix(evals): no assert prefixes an absolute artifact dir (#331)" -m "<trailers>"
```
