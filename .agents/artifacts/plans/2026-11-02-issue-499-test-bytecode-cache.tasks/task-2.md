# Task 2: Test harness children inherit the cache

Spec § Decisions (**Test harnesses**, **Reach and limits**), § Test seams (the harness edits carry no test of their own). Rests on D2 and D3. After this task every test site that builds a child's environment by spreading the test process's environment stops setting `PYTHONDONTWRITEBYTECODE`, so the runner's cache from Task 1 reaches those children; the eval-case acceptance child keeps the setting.

**Files:**
- Modify: `tests/orchestrate_world.py`
- Modify: `home/common/agent-skills/tests/test_control_cutover.py`
- Modify: `home/common/agent-skills/tests/test_delivery_workflow.py`
- Modify: `home/common/agent-skills/tests/test_delivered_control.py`
- Modify: `python/README.md`

**Interfaces:**
- Consumes: Task 1's runner, which hands every member `PYTHONPYCACHEPREFIX` and no `PYTHONDONTWRITEBYTECODE`; the sentence of Task 1's README insertion that ends `gives that process its own \`PYTHONPYCACHEPREFIX\` directory.`
- Produces: nothing a later task calls.

**Invariants:**
- Each edited site still spreads `os.environ` and keeps every other entry it sets, byte for byte; only the `"PYTHONDONTWRITEBYTECODE": "1"` entry goes (D3).
- `home/common/agent-skills/tests/test_eval_cases.py` is not edited: its child is given only `PATH` and runs inside the tracked fixture tree (D3).
- The git-failure probe drops the entry too: no Python runs there, so the variable only misleads (D3).

- [ ] **Step 1: Run the harness check and watch it fail**

Run (timeout 60 s): the harness check from the plan root's Global Constraints.
Expected: exit 1, printing six paths: `home/common/agent-skills/tests/test_control_cutover.py home/common/agent-skills/tests/test_delivered_control.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_eval_cases.py tests/orchestrate_world.py tests/test_suite_runner.py`.

- [ ] **Step 2: Edit the seven sites**

Each edit removes exactly the `"PYTHONDONTWRITEBYTECODE": "1"` entry and its separator:

1. `tests/orchestrate_world.py`, `OrchestrateWorld.__init__`, the `self.env = {…}` literal: `"PYTHONPATH": str(ROOT / "python"), "PYTHONDONTWRITEBYTECODE": "1",` becomes `"PYTHONPATH": str(ROOT / "python"),`.
2. `home/common/agent-skills/tests/test_control_cutover.py`, `Cutover.cli`, the base generation's `subprocess.run`: `env={**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1",` becomes `env={**os.environ, "HOME": str(self.home),` (the `"PYTHONPATH": …` entry on the next line stays).
3. `home/common/agent-skills/tests/test_delivery_workflow.py`, `DeliveryAdmissionTest.test_contractless_public_outputs_are_requirement_only`: `root = Path(raw); env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}` becomes `root = Path(raw); env = dict(os.environ)`.
4. Same file, `DeliveryAdmissionTest.test_public_source_and_installed_admission_fail_closed`: `env = {**os.environ, "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}` becomes `env = {**os.environ, "HOME": str(home)}`.
5. and 6. Same file, `BuilderHarness.cli` and the nested `git_failure` probe in `LegacyWorktreeTest`: the text `env={**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"})` occurs exactly twice in the file, and both occurrences become `env={**os.environ, "HOME": str(self.home)})`.
7. `home/common/agent-skills/tests/test_delivered_control.py`, `test_a_rejected_reply_leaves_the_ledger_byte_identical`: `env = {**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}` becomes `env = {**os.environ, "HOME": str(self.home)}`.

In `python/README.md`, in the runner paragraph, directly after the sentence that ends `gives that process its own \`PYTHONPYCACHEPREFIX\` directory.`, insert:

> Outside the runner, as in a direct `python -m unittest` run, a test's Python children that inherit its environment write bytecode beside their sources where those are writable, as the test process itself does; the checkout ignores `__pycache__/`.

- [ ] **Step 3: Verify**

Run (timeout 60 s): the harness check from the plan root.
Expected: exit 0, printing `home/common/agent-skills/tests/test_eval_cases.py tests/test_suite_runner.py`.

Run (timeout 60 s): `bash -c 'set -e; test "$(git diff --unified=0 HEAD -- tests home/common/agent-skills/tests | grep -c "^-.*PYTHONDONTWRITEBYTECODE")" = 7; if git diff --unified=0 HEAD -- tests home/common/agent-skills/tests | grep "^+.*PYTHONDONTWRITEBYTECODE"; then exit 1; fi; echo seven-removed'`
Expected: `seven-removed` (seven removed lines carried the entry, and no added line does).

Run (timeout 1800 s; about 450 s wall on a loaded host): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m agent_tools.suite_runner --jobs 4 tests/test_orchestrate_control.py home/common/agent-skills/tests/test_admission_replay.py home/common/agent-skills/tests/test_control_cutover.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_delivered_control.py 2>&1 | grep -E "^suite-runner: (summary|failed)"'`
Expected: exactly one line, `suite-runner: summary members=5 passed=5 failed=0 jobs=4 wall=<s>s cpu=<s>s`. These are the three edited test modules and the two modules that use `tests/orchestrate_world.py`, run under Task 1's runner so their children share its cache.

- [ ] **Step 4: Commit**

```bash
git add tests/orchestrate_world.py home/common/agent-skills/tests/test_control_cutover.py home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_delivered_control.py python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "test: let harness children inherit the suite's bytecode cache (issue 499)" -m "<session trailer lines>"
```
