# Task 1: Reject post-normalization absolute paths

**Files:**

- Modify: `home/common/agent-skills/scripts/diff-scope.py`
- Test: `home/common/agent-skills/tests/test_diff_scope.py`

**Interfaces:**

- Consumes: `normalize_artifact_path(value: str) -> bytes` and the `diff-scope` CLI.
- Produces: an exit-1 `DiffScopeError` for `.//x`, with the existing diagnostic rendering.

**Invariants:**

- Leading `./` prefixes are stripped before absolute-path validation, per D1.
- `./x` remains a repository-relative artifact path.
- `.//x` exits 1 and writes a `diff-scope:` diagnostic to stderr.

- [ ] **Step 1: Write the failing test**

Add `.//x` to the existing invalid artifact-path CLI table and assert exit 1 plus the diagnostic prefix.

- [ ] **Step 2: Run the targeted test and observe failure**

Run: `python3 home/common/agent-skills/tests/test_diff_scope.py`

Expected: the invalid-path test fails while `.//x` is accepted.

- [ ] **Step 3: Write the minimal implementation**

Move the existing leading-slash validation to immediately after the loop that strips leading `./` prefixes. Keep its existing error text and later normalization checks intact.

- [ ] **Step 4: Verify**

Run: `just agent-workflow-tests && just build`

Expected: both commands exit 0.

- [ ] **Step 5: Commit**

Commit the implementation and test with the configured signing and co-author trailer.
