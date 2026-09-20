# Task 1: Pin the CI and protection contracts

**Files:**
- Modify: `.github/workflows/ci.yaml`
- Modify: `.github/branch-protection.json`
- Test: `tests/test_branch_protection.py`

**Interfaces:**
- Consumes: the workflow's top-level indentation convention, job blocks, and complete JSON payload loaded by the existing test module.
- Produces: `workflow_permissions() -> dict[str, str]`, `job_name(line: str) -> str | None`, `required_contexts() -> list[str]`, and an exact `EXPECTED_PROTECTION_PAYLOAD` fixture used by the existing assertions.

**Invariants:**
- The only top-level token permission is `contents: read` (D1).
- The complete protection payload contains all four API keys and one provider-bound check: `{"context": "Nix Eval", "app_id": 15368}` (D2).
- `job_name` returns `Nix Eval` for plain, single-quoted, and double-quoted YAML scalar spellings, and returns `None` for non-job-name lines (D3).
- All existing trigger, plain-job, green-without-work, command, and evaluated-attribute assertions remain green.

- [ ] **Step 1: Write the failing contract tests**

Add an exact workflow-permission assertion, an exact full-payload assertion, and the scalar extraction cases before changing either fixture:

```python
EXPECTED_WORKFLOW_PERMISSIONS = {"contents": "read"}
EXPECTED_PROTECTION_PAYLOAD = {
    "required_status_checks": {
        "strict": False,
        "checks": [{"context": "Nix Eval", "app_id": 15368}],
    },
    "enforce_admins": True,
    "required_pull_request_reviews": None,
    "restrictions": None,
}


class WorkflowShape(unittest.TestCase):
    def test_workflow_uses_only_minimum_permissions(self):
        self.assertEqual(EXPECTED_WORKFLOW_PERMISSIONS, workflow_permissions())

    def test_job_name_extraction_removes_yaml_quotes(self):
        for source in (
            "    name: Nix Eval",
            '    name: "Nix Eval"',
            "    name: 'Nix Eval'",
        ):
            with self.subTest(source=source):
                self.assertEqual("Nix Eval", job_name(source))
        self.assertIsNone(job_name("      - name: step name"))


class ProtectionPayload(unittest.TestCase):
    def test_payload_is_the_exact_replacement_contract(self):
        self.assertEqual(EXPECTED_PROTECTION_PAYLOAD, payload())
```

Implement only the parsing helpers needed to let the tests run far enough to demonstrate fixture failures. `workflow_permissions()` must read the `permissions` top-level block through `_top_level_block` and accept only two-space `key: value` entries. `job_name()` must return the first non-`None` capture from `JOB_NAME_RE` or `None` when it does not match. Update `job_names()` to call `job_name()`.

- [ ] **Step 2: Run the focused suite and confirm the contract failures**

Run: `python3 -m unittest tests.test_branch_protection -v`

Expected: FAIL because `ci.yaml` has no top-level `permissions:` block and the protection payload still has `contexts`; the quoted-name cases must also fail before `JOB_NAME_RE` and `job_name()` are corrected.

- [ ] **Step 3: Apply the minimal fixture and extractor changes**

In `.github/workflows/ci.yaml`, add exactly:

```yaml
permissions:
  contents: read
```

at workflow scope before `jobs:`. In `.github/branch-protection.json`, replace the `contexts` member with:

```json
"checks": [{"context": "Nix Eval", "app_id": 15368}]
```

Keep the other three top-level payload members and `strict: false` unchanged. Define `JOB_NAME_RE` with three alternatives that separately capture double-quoted, single-quoted, or plain scalar contents; the quote delimiters must sit outside every capture. Make `required_contexts()` derive context strings from the `checks` array. Remove any assertion of the deprecated `contexts` member in favor of the full-payload equality test.

- [ ] **Step 4: Verify the focused and repository workflow suites**

Run: `python3 -m unittest tests.test_branch_protection -v`

Expected: PASS, with the permission, payload, quoted-name, and all pre-existing required-check tests green.

Run: `just agent-workflow-tests`

Expected: PASS with no failed test module; any failure in `tests/test_branch_protection.py` or a broader workflow invariant leaves the task incomplete.

Run: `git diff --check -- .github/workflows/ci.yaml .github/branch-protection.json tests/test_branch_protection.py`

Expected: exit 0 with no whitespace errors.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yaml .github/branch-protection.json tests/test_branch_protection.py
git commit -m "fix(ci): pin permissions and check provider"
```
