# Task 1: The capture test runs under the fixture's budget authority

**Files:**
- Modify: `tests/test_review_gate.py`
- Test: `tests/test_review_gate.py` (`GateTest.test_capture_refuses_output_no_real_producer_emits`)

**Interfaces:**
- Consumes: `SourceProjectionFixture.env` from `tests/test_review_feasibility.py`, a `dict` built in `setUp`. Its `HOME` is a fixture home whose `.agents/lib/python/artifact_budget.py` and `.agents/share/artifact-budget-policy.json` link to the source tree. Its `PYTHONPATH` is `<source>/python`, and its `PATH` starts with `<source>/home/common/agent-skills/scripts`. Also `agent_tools.review_budget.describe(kind: str) -> BudgetAuthority`, which runs `artifact-budget` by name on the process `PATH`, and `agent_tools.review_gate.capture(argv, *, cwd: Path, authority: BudgetAuthority) -> Capture` (fields `exit`, `raw`, `result`; raises `GateError`). `capture`'s child inherits the process environment.
- Produces: nothing a later task consumes. The change adds no test, helper or fixture.

**Invariants:**
- `describe('review-package')` and every `capture(...)` call in the test run inside one `with patch.dict(os.environ, self.env, clear=True):` block (D2).
- `good = self.project(0).stdout` stays the first statement and stays outside the block, because `self.project` already passes `self.env` to its subprocess (D2).
- The first statement inside the block after `describe` is the positive control. A `sys.executable -c` child writes the unmutated `good` bytes and exits 0, and `capture` accepts them with `(accepted.exit, accepted.raw) == (0, good)` (D3).
- The six refusal cases (`noncanonical`, `exit disagrees`, `unknown exit`, `oversized`, `duplicate key`, `one metric drift`) and the stderr case (`assertRaisesRegex(GateError, '^boom$')`) keep their inputs and assertions byte for byte (D3).
- `python/agent_tools/review_budget.py`, `python/agent_tools/review_gate.py`, `.github/workflows/ci.yaml` and `justfile` are not edited (D1). The file keeps its 9 tests.

**Hosted-runner stand-in.** Every run below uses this `bash -c` prefix, called `<no-installed>` here. It drops each `PATH` directory that holds an `artifact-budget` executable and fails when one is still found. The prefix runs from the worktree root:

```bash
set -o pipefail; PATH="$(printf %s "$PATH" | tr ":" "\n" | while IFS= read -r d; do [ -x "$d/artifact-budget" ] || printf "%s\n" "$d"; done | paste -sd: -)"; if command -v artifact-budget >/dev/null; then echo "artifact-budget still on PATH"; exit 1; fi;
```

- [ ] **Step 1: Watch the existing test fail**

This is a test-only fix, so the failing test already exists.

Run (timeout 600 s): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c '<no-installed> PYTHONPATH="$PWD/python" python3 -m unittest tests.test_review_gate -k test_capture_refuses_output_no_real_producer_emits 2>&1 | tail -6'`
Expected: FAIL. The output shows `agent_tools.review_budget.BudgetError: budget authority unavailable`, `Ran 1 test` and `FAILED (errors=1)`. Planning confirmed this at spec commit `d191db65`.

- [ ] **Step 2: Scope the environment and add the positive control**

Add `import os` after `import json` and `from unittest.mock import patch` after `import unittest`. Then replace the method body with the following. The positive control is new, and the rest is the existing body indented one level under the block:

```python
    def test_capture_refuses_output_no_real_producer_emits(self):
        good = self.project(0).stdout
        with patch.dict(os.environ, self.env, clear=True):
            authority = describe('review-package')
            script = f'import sys; sys.stdout.buffer.write({good!r}); sys.exit(0)'
            accepted = capture([sys.executable, '-c', script], cwd=self.repo, authority=authority)
            self.assertEqual((accepted.exit, accepted.raw), (0, good))
            over = json.loads(good); over['metrics']['root_bytes'] += 1
            cases = {
                'noncanonical': (good + b' ', 0), 'exit disagrees': (good, 3), 'unknown exit': (good, 1),
                'oversized': (b'x' * (authority.report_wire_max_bytes + 1), 0),
                'duplicate key': (b'{"a":1,"a":1}\n', 0), 'one metric drift': (canonical_bytes(over), 0)}
            for label, (raw, code) in cases.items():
                script = f'import sys; sys.stdout.buffer.write({raw!r}); sys.exit({code})'
                with self.subTest(label), self.assertRaises(GateError):
                    capture([sys.executable, '-c', script], cwd=self.repo, authority=authority)
            script = 'import sys; sys.stderr.write("review-feasibility: boom\\n"); sys.exit(2)'
            with self.assertRaisesRegex(GateError, '^boom$'):
                capture([sys.executable, '-c', script], cwd=self.repo, authority=authority)
```

Add no comment and no docstring. The other eight tests and the module docstring stay unchanged.

- [ ] **Step 3: Verify**

1. Focused run, green (timeout 600 s): the Step 1 command.
   Expected: `Ran 1 test` and `OK`. Planning ran this exact body under the stand-in and it passed.
2. Whole file under the stand-in (timeout 2400 s, because it took 500 s on a loaded host): `launch-scope exec --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- bash -c '<no-installed> PYTHONPATH="$PWD/python" python3 -m unittest tests.test_review_gate 2>&1 | tail -4'`
   Expected: `Ran 9 tests` and `OK`. Planning ran it at `d191db65` and got `FAILED (errors=1)`: this test was the only error, and the other eight passed.
3. Static scope (instant): `test "$(grep -c 'with patch.dict(os.environ, self.env, clear=True):' tests/test_review_gate.py)" = 1 && grep -q '(accepted.exit, accepted.raw), (0, good)' tests/test_review_gate.py`
   Expected: exit 0. Exit 1 means the block or the positive control is missing or duplicated.

No `just build` is needed here, because the task changes no file that it evaluates. sdd's final gate runs the project verification once.

- [ ] **Step 4: Commit**

```bash
git add tests/test_review_gate.py
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "test(issue-557): run the capture test under the fixture budget authority" -m "<the session's Co-Authored-By trailer>"
```

Then check the scope (instant): `test "$(git show --name-only --format= HEAD)" = tests/test_review_gate.py`
Expected: exit 0. A non-zero exit means the commit touched another file.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":1,"records":[{"bounds":[{"added_lines":40,"boundary":"all","deleted_lines":24,"record_bytes":8192,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1a","last_task":1,"owner":1,"path":"tests/test_review_gate.py"}]}}
```
